"""Explicit handoff from the common execution contract to a SLURM request."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ari.public.execution import ExecutionRequestV1

from .contracts import (
    ArtifactPinV1,
    ContainerRequestV1,
    ContractModel,
    EnvironmentPolicyV1,
    JobRequestV1,
    OutputDeclarationV1,
    ResourceRequestV1,
    sha256_digest,
)


class ExecutionHandoffV1(ContractModel):
    """Auditable mapping record; it never implies substrate equivalence."""

    schema_version: Literal["ari.hpc.execution-handoff/v1"] = (
        "ari.hpc.execution-handoff/v1"
    )
    execution_identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    substrate: Literal["slurm"] = "slurm"
    job_request: JobRequestV1
    mapped_fields: tuple[str, ...]
    unmapped_policies: tuple[str, ...]
    policy_equivalent: Literal[False] = False
    handoff_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_digest(self) -> "ExecutionHandoffV1":
        if self.handoff_digest is not None:
            payload = self.model_dump(mode="json", exclude={"handoff_digest"})
            if self.handoff_digest != sha256_digest(payload):
                raise ValueError("execution handoff digest differs")
        return self

    def with_digest(self) -> "ExecutionHandoffV1":
        payload = self.model_dump(mode="json", exclude={"handoff_digest"})
        return self.model_copy(update={"handoff_digest": sha256_digest(payload)})


def _walltime_seconds(value: str) -> int:
    day_part, clock = value.split("-", 1) if "-" in value else ("0", value)
    hours, minutes, seconds = (int(item) for item in clock.split(":"))
    return int(day_part) * 86_400 + hours * 3_600 + minutes * 60 + seconds


def handoff_execution_to_slurm(
    request: ExecutionRequestV1,
    *,
    request_id: str,
    job_name: str,
    resources: ResourceRequestV1,
    container: ContainerRequestV1 | None = None,
    outputs: tuple[OutputDeclarationV1, ...] = (),
    modules: tuple[str, ...] = (),
    network_isolation_attested: bool = False,
) -> ExecutionHandoffV1:
    """Map reproducible fields and enumerate policies SLURM does not preserve."""

    if request.argv is None:
        raise ValueError("SLURM handoff requires structured argv, not a shell command")
    if request.timeout_seconds > _walltime_seconds(resources.walltime):
        raise ValueError("SLURM walltime is shorter than the execution timeout")
    if request.network == "deny" and not (
        (container is not None and container.network == "none")
        or network_isolation_attested
    ):
        raise ValueError("network denial requires an HPC container network namespace")
    if (request.container is None) != (container is None):
        raise ValueError("execution and HPC container selections differ")
    if request.container is not None:
        if container is None:
            raise ValueError("execution container identity is missing from HPC handoff")
        if request.container.digest is None:
            raise ValueError(
                "unresolved execution container cannot enter SLURM handoff"
            )
        if request.container.digest != container.image.digest:
            raise ValueError("execution and HPC container digests differ")
        if request.container.runtime != container.runtime:
            raise ValueError("execution and HPC container runtimes differ")

    pins: list[ArtifactPinV1] = []
    job_argv = list(request.argv)
    unbound_inputs: list[str] = []
    for index, (relative_path, expected_digest) in enumerate(
        request.input_digests.items()
    ):
        payload = request.workspace.read_bytes(
            relative_path, max_bytes=256 * 1024 * 1024
        )
        actual_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if actual_digest != expected_digest:
            raise ValueError(f"execution input digest changed: {relative_path}")
        snapshot_name = (
            ".ari-execution/hpc-inputs/"
            f"{actual_digest.removeprefix('sha256:')}/{Path(relative_path).name}"
        )
        snapshot = request.workspace.atomic_write_bytes(snapshot_name, payload)
        pins.append(
            ArtifactPinV1(
                logical_name=f"execution-input-{index:03d}",
                path=str(snapshot),
                digest=actual_digest,
                size_bytes=len(payload),
            )
        )
        original_absolute = str(Path(request.workspace.root) / relative_path)
        bound_to_argv = False
        for argument_index, argument in enumerate(job_argv):
            if argument in {relative_path, original_absolute}:
                job_argv[argument_index] = str(snapshot)
                bound_to_argv = True
        if not bound_to_argv:
            unbound_inputs.append(relative_path)

    metadata: dict[str, str | int | float | bool | None] = {
        "execution_identity": request.execution_identity,
        "execution_schema": request.schema_version,
        "execution_network": request.network,
        "network_isolation_attested": network_isolation_attested,
        "execution_timeout_seconds": request.timeout_seconds,
        "execution_limits_digest": sha256_digest(
            request.limits.model_dump(mode="json")
        ),
    }
    if request.limits.memory_bytes is not None:
        requested_mb = math.ceil(request.limits.memory_bytes / (1024 * 1024))
        scheduled_mb = resources.memory_mb_per_node
        if scheduled_mb is not None and scheduled_mb < requested_mb:
            raise ValueError("SLURM memory request is below the execution limit")

    job_request = JobRequestV1(
        request_id=request_id,
        job_name=job_name,
        work_dir=request.workspace.root,
        argv=tuple(job_argv),
        resources=resources,
        environment=EnvironmentPolicyV1(
            variables=request.environment,
            modules=modules,
        ),
        container=container,
        inputs=tuple(pins),
        outputs=outputs,
        metadata=metadata,
    )
    unmapped = ["posix_output_file_limit"]
    if request.limits.cpu_seconds is not None:
        unmapped.append("posix_cpu_limit")
    if request.limits.max_processes is not None:
        unmapped.append("posix_process_count_limit")
    if request.limits.memory_bytes is not None and resources.memory_mb_per_node is None:
        unmapped.append("posix_address_space_limit")
    unmapped.extend(f"input_operand_binding:{path}" for path in unbound_inputs)
    return ExecutionHandoffV1(
        execution_identity=request.execution_identity,
        job_request=job_request,
        mapped_fields=(
            "argv",
            "environment",
            "input_artifact_pins",
            "network_policy",
            "module_environment",
            "timeout_upper_bound",
        ),
        unmapped_policies=tuple(unmapped),
    ).with_digest()


__all__ = ["ExecutionHandoffV1", "handoff_execution_to_slurm"]
