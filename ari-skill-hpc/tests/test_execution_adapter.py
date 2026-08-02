"""Common execution request to explicit SLURM handoff conformance."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ari.public.execution import (
    ContainerIdentityV1,
    ExecutionRequestV1,
    WorkspaceRefV1,
    execute_local,
)
from ari_skill_hpc.contracts import (
    ArtifactPinV1,
    ContainerRequestV1,
    ResourceRequestV1,
)
from ari_skill_hpc.execution_adapter import handoff_execution_to_slurm


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def test_same_request_identity_survives_local_and_slurm_handoff(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceRefV1(root=str(tmp_path / "workspace"))
    source = b"print('portable')\n"
    workspace.atomic_write_bytes("run.py", source)
    request = ExecutionRequestV1(
        workspace=workspace,
        argv=["python3", "run.py"],
        environment={"EXPERIMENT_MODE": "validation"},
        input_digests={"run.py": _digest(source)},
        timeout_seconds=30,
    )

    local = execute_local(request)
    handoff = handoff_execution_to_slurm(
        request,
        request_id="portable-1",
        job_name="portable",
        resources=ResourceRequestV1(partition="cpu", walltime="00:01:00"),
    )
    repeated = handoff_execution_to_slurm(
        request,
        request_id="portable-1",
        job_name="portable",
        resources=ResourceRequestV1(partition="cpu", walltime="00:01:00"),
    )

    assert local.execution_identity == handoff.execution_identity
    assert handoff.job_request.metadata["execution_identity"] == (
        request.execution_identity
    )
    assert handoff.job_request.environment.variables == {
        "EXPERIMENT_MODE": "validation"
    }
    assert handoff.job_request.inputs[0].digest == _digest(source)
    assert handoff.job_request.inputs[0].path != str(Path(workspace.root) / "run.py")
    assert handoff.job_request.argv[-1] == handoff.job_request.inputs[0].path
    assert handoff.policy_equivalent is False
    assert "posix_output_file_limit" in handoff.unmapped_policies
    assert handoff.handoff_digest == repeated.handoff_digest


def test_container_handoff_requires_matching_resolved_identity(tmp_path: Path) -> None:
    workspace = WorkspaceRefV1(root=str(tmp_path / "workspace"))
    image = tmp_path / "runtime.sif"
    image.write_bytes(b"immutable-sif")
    image_digest = _digest(image.read_bytes())
    execution = ExecutionRequestV1(
        workspace=workspace,
        argv=["python3", "-c", "print('inside')"],
        network="deny",
        container=ContainerIdentityV1(
            runtime="apptainer",
            reference=str(image),
            digest=image_digest,
            resolution_status="resolved",
        ),
    )
    hpc_container = ContainerRequestV1(
        runtime="apptainer",
        image=ArtifactPinV1(
            logical_name="runtime-image",
            path=str(image),
            digest=image_digest,
            size_bytes=image.stat().st_size,
        ),
        network="none",
    )
    handoff = handoff_execution_to_slurm(
        execution,
        request_id="container-1",
        job_name="container-job",
        resources=ResourceRequestV1(partition="gpu", walltime="00:02:00"),
        container=hpc_container,
    )
    assert handoff.job_request.container == hpc_container
    assert handoff.job_request.metadata["execution_network"] == "deny"

    mutable = execution.model_copy(
        update={
            "container": ContainerIdentityV1(
                runtime="apptainer",
                reference="example:latest",
                resolution_status="unresolved",
            )
        }
    )
    with pytest.raises(ValueError, match="unresolved"):
        handoff_execution_to_slurm(
            mutable,
            request_id="container-2",
            job_name="container-job",
            resources=ResourceRequestV1(partition="gpu", walltime="00:02:00"),
            container=hpc_container,
        )


def test_handoff_rejects_shell_and_unenforced_network_deny(tmp_path: Path) -> None:
    workspace = WorkspaceRefV1(root=str(tmp_path / "workspace"))
    resources = ResourceRequestV1(partition="cpu", walltime="00:01:00")
    shell = ExecutionRequestV1(workspace=workspace, shell_command="echo unsafe")
    with pytest.raises(ValueError, match="structured argv"):
        handoff_execution_to_slurm(
            shell,
            request_id="shell-1",
            job_name="shell",
            resources=resources,
        )
    denied = ExecutionRequestV1(workspace=workspace, argv=["true"], network="deny")
    with pytest.raises(ValueError, match="network denial"):
        handoff_execution_to_slurm(
            denied,
            request_id="network-1",
            job_name="network",
            resources=resources,
        )

    attested = handoff_execution_to_slurm(
        denied,
        request_id="network-attested",
        job_name="network",
        resources=resources,
        modules=("cuda/12.4",),
        network_isolation_attested=True,
    )
    assert attested.job_request.environment.modules == ("cuda/12.4",)
    assert attested.job_request.metadata["network_isolation_attested"] is True
    assert attested.policy_equivalent is False


def test_handoff_marks_inputs_not_bound_to_argv_as_unmapped(tmp_path: Path) -> None:
    workspace = WorkspaceRefV1(root=str(tmp_path / "workspace"))
    configuration = b"threshold = 0.5\n"
    workspace.atomic_write_bytes("experiment.toml", configuration)
    request = ExecutionRequestV1(
        workspace=workspace,
        argv=["python3", "-c", "print('configuration loaded indirectly')"],
        input_digests={"experiment.toml": _digest(configuration)},
    )

    handoff = handoff_execution_to_slurm(
        request,
        request_id="indirect-input-1",
        job_name="indirect-input",
        resources=ResourceRequestV1(partition="cpu", walltime="00:01:00"),
    )

    assert handoff.job_request.inputs[0].digest == _digest(configuration)
    assert (
        "input_operand_binding:experiment.toml" in handoff.unmapped_policies
    )
    assert handoff.policy_equivalent is False
