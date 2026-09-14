"""Validation and schema tests for the public HPC v1 contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ari_skill_hpc.contracts import (
    AcceleratorDeviceIdentityV1,
    ArtifactPinV1,
    EnvironmentPolicyV1,
    ExclusiveNodeAcceleratorV1,
    JobRequestV1,
    JobSubmitArgumentsV1,
    OutputDeclarationV1,
    ResourceRequestV1,
    file_digest,
)


def _pin(path: Path) -> ArtifactPinV1:
    return ArtifactPinV1(
        logical_name="input-data",
        path=str(path),
        digest=file_digest(path),
        size_bytes=path.stat().st_size,
    )


def _valid_request(tmp_path: Path) -> JobRequestV1:
    source = tmp_path / "input.dat"
    source.write_bytes(b"abc")
    return JobRequestV1(
        request_id="request-1",
        job_name="science-job",
        work_dir=str(tmp_path),
        argv=("/usr/bin/true",),
        resources=ResourceRequestV1(partition="cpu"),
        inputs=(_pin(source),),
        outputs=(
            OutputDeclarationV1(
                logical_name="result-data", path=str(tmp_path / "result.dat")
            ),
        ),
    )


def test_request_digest_is_stable_and_schema_is_root_resolvable(tmp_path: Path) -> None:
    request = _valid_request(tmp_path)
    round_trip = JobRequestV1.model_validate(request.model_dump(mode="json"))
    assert request.request_digest == round_trip.request_digest
    schema = JobSubmitArgumentsV1.model_json_schema()
    assert "$defs" in schema
    assert schema["properties"]["request"]["$ref"].startswith("#/$defs/")


@pytest.mark.parametrize(
    "name",
    ["OPENAI_API_KEY", "HF_TOKEN", "DATABASE_PASSWORD", "AUTH_COOKIE"],
)
def test_environment_rejects_embedded_credentials(name: str) -> None:
    with pytest.raises(ValidationError, match="cannot be embedded"):
        EnvironmentPolicyV1(variables={name: "should-never-enter-the-script"})


def test_request_rejects_output_outside_workspace(tmp_path: Path) -> None:
    request = _valid_request(tmp_path)
    with pytest.raises(ValidationError, match="below work_dir"):
        request.model_copy(
            update={
                "outputs": (
                    OutputDeclarationV1(
                        logical_name="escaped",
                        path=str(tmp_path.parent / "escaped.dat"),
                    ),
                )
            }
        ).model_validate(
            {
                **request.model_dump(mode="json"),
                "outputs": [
                    {
                        "logical_name": "escaped",
                        "path": str(tmp_path.parent / "escaped.dat"),
                    }
                ],
            }
        )


def test_contract_rejects_parent_traversal_and_newline_argv(tmp_path: Path) -> None:
    payload = _valid_request(tmp_path).model_dump(mode="json")
    payload["work_dir"] = str(tmp_path / ".." / tmp_path.name)
    with pytest.raises(ValidationError, match="parent traversal"):
        JobRequestV1.model_validate(payload)
    payload = _valid_request(tmp_path).model_dump(mode="json")
    payload["argv"] = ["python", "x\ntouch /tmp/pwn"]
    with pytest.raises(ValidationError, match="bounded inert"):
        JobRequestV1.model_validate(payload)


def test_contract_rejects_secret_like_metadata(tmp_path: Path) -> None:
    payload = _valid_request(tmp_path).model_dump(mode="json")
    payload["metadata"] = {"api_token": "value"}
    with pytest.raises(ValidationError, match="non-secret"):
        JobRequestV1.model_validate(payload)


def test_extra_fields_fail_closed(tmp_path: Path) -> None:
    payload = _valid_request(tmp_path).model_dump(mode="json")
    payload["shell"] = "bash -c anything"
    with pytest.raises(ValidationError, match="Extra inputs"):
        JobRequestV1.model_validate(payload)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"memory_mb_per_node": 1024, "memory_mb_per_cpu": 512}, "mutually"),
        ({"gpus_per_node": 1, "gpus_per_task": 1}, "mutually"),
        ({"gpu_type": "h100"}, "explicit GPU count"),
        ({"tasks": 2, "tasks_per_node": 4}, "cannot exceed"),
        ({"nodelist": "node01", "exclude_nodes": "node01"}, "included and excluded"),
    ],
)
def test_resource_contract_rejects_contradictory_shapes(
    payload: dict, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        ResourceRequestV1(partition="compute", **payload)


def test_resource_contract_accepts_typed_placement_shape() -> None:
    resources = ResourceRequestV1(
        partition="compute",
        nodes=4,
        tasks=32,
        tasks_per_node=8,
        cpus_per_task=2,
        memory_mb_per_node=262144,
        gpus_per_task=1,
        gpu_type="v100",
        nodelist="node[01-04]",
        exclude_nodes="node03",
        constraint="skylake|haswell",
        hint="nomultithread",
        reservation="paperbench",
    )
    assert resources.tasks_per_node == 8


def _exclusive_accelerator(tmp_path: Path) -> ExclusiveNodeAcceleratorV1:
    probe = tmp_path / "nvidia-smi"
    probe.write_bytes(b"pinned nvidia-smi fixture\n")
    return ExclusiveNodeAcceleratorV1(
        partition="gpu-private",
        node_name="gpu-node-a",
        inventory_probe=ArtifactPinV1(
            logical_name="nvidia-smi-inventory-probe",
            path=str(probe),
            digest=file_digest(probe),
            size_bytes=probe.stat().st_size,
        ),
        devices=(
            AcceleratorDeviceIdentityV1(
                uuid="GPU-27714578-959a-9314-ad8a-21773f5e5649",
                name="Tesla V100-SXM2-16GB",
                driver_version="575.64.03",
                memory_mb=16384,
                compute_capability="7.0",
            ),
        ),
    )


def test_no_gres_accelerator_requires_exact_exclusive_node(tmp_path: Path) -> None:
    request = _valid_request(tmp_path)
    allocation = _exclusive_accelerator(tmp_path)
    payload = request.model_dump(mode="json")
    payload.update(
        {
            "resources": {
                "partition": "gpu-private",
                "nodes": 1,
                "tasks": 1,
                "cpus_per_task": 1,
                "walltime": "00:05:00",
                "nodelist": "gpu-node-a",
                "exclusive": True,
            },
            "accelerator_allocation": allocation.model_dump(mode="json"),
        }
    )
    accepted = JobRequestV1.model_validate(payload)
    assert accepted.resources.gpus_per_node == 0
    assert accepted.accelerator_allocation == allocation

    for resources, message in (
        ({**payload["resources"], "exclusive": False}, "--exclusive"),
        ({**payload["resources"], "nodelist": "other"}, "nodelist"),
        ({**payload["resources"], "gpus_per_node": 1}, "must not claim"),
    ):
        invalid = {**payload, "resources": resources}
        with pytest.raises(ValidationError, match=message):
            JobRequestV1.model_validate(invalid)
