"""Public versioned contracts for scheduler-backed research jobs."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


SCHEMA_JOB_REQUEST_V1 = "ari.hpc.job-request/v1"
SCHEMA_JOB_HANDLE_V1 = "ari.hpc.job-handle/v1"
SCHEMA_JOB_STATUS_V1 = "ari.hpc.job-status/v1"
SCHEMA_JOB_RESULT_V1 = "ari.hpc.job-result/v1"

Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
SafeIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}$"),
]
SlurmNodeExpression = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9,._+\[\]-]{0,1023}$"),
]
SlurmConstraintExpression = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@+&|*?\[\]-]{0,1023}$"),
]
JobId = Annotated[str, StringConstraints(pattern=r"^[0-9]+(?:_[0-9]+)?$")]

_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_SECRET_NAME_RE = re.compile(
    r"(?:^|_)(?:API_?KEY|AUTH|BEARER|COOKIE|CREDENTIAL|PASSWORD|PRIVATE|SECRET|TOKEN)(?:_|$)"
)
_MODULE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+/@:-]{0,127}$")


class ContractModel(BaseModel):
    """Strict immutable base used by all public HPC contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _absolute_path(value: str, *, field: str) -> Path:
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"{field} must be a non-empty inert path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{field} must be absolute")
    if ".." in path.parts:
        raise ValueError(f"{field} must not contain parent traversal")
    if any(character.isspace() for character in value):
        raise ValueError(f"{field} must not contain whitespace")
    return path


class ArtifactPinV1(ContractModel):
    logical_name: SafeIdentifier
    path: str = Field(min_length=1, max_length=4096)
    digest: Digest
    size_bytes: int = Field(ge=0, le=1_099_511_627_776)
    media_type: str = Field(default="application/octet-stream", max_length=255)

    @model_validator(mode="after")
    def validate_path(self) -> ArtifactPinV1:
        _absolute_path(self.path, field="artifact path")
        return self


class OutputDeclarationV1(ContractModel):
    logical_name: SafeIdentifier
    path: str = Field(min_length=1, max_length=4096)
    required: bool = True
    max_bytes: int = Field(default=1_073_741_824, ge=0, le=1_099_511_627_776)
    media_type: str = Field(default="application/octet-stream", max_length=255)

    @model_validator(mode="after")
    def validate_path(self) -> OutputDeclarationV1:
        _absolute_path(self.path, field="output path")
        return self


class BindMountV1(ContractModel):
    source: str = Field(min_length=1, max_length=4096)
    target: str = Field(min_length=1, max_length=4096)
    read_only: bool = True

    @model_validator(mode="after")
    def validate_paths(self) -> BindMountV1:
        _absolute_path(self.source, field="bind source")
        _absolute_path(self.target, field="bind target")
        return self


class ContainerRequestV1(ContractModel):
    runtime: Literal["apptainer", "singularity"] = "apptainer"
    image: ArtifactPinV1
    binds: tuple[BindMountV1, ...] = ()
    gpu: bool = False
    network: Literal["host", "none"] = "host"
    contain_all: bool = True
    clean_environment: bool = True

    @model_validator(mode="after")
    def validate_binds(self) -> ContainerRequestV1:
        targets = [item.target for item in self.binds]
        if len(targets) != len(set(targets)):
            raise ValueError("container bind targets must be unique")
        return self


class ResourceRequestV1(ContractModel):
    partition: SafeIdentifier
    nodes: int = Field(default=1, ge=1, le=4096)
    tasks: int = Field(default=1, ge=1, le=1_048_576)
    tasks_per_node: int | None = Field(default=None, ge=1, le=1_048_576)
    cpus_per_task: int = Field(default=1, ge=1, le=65_536)
    memory_mb_per_node: int | None = Field(default=None, ge=1, le=16_777_216)
    memory_mb_per_cpu: int | None = Field(default=None, ge=1, le=16_777_216)
    gpus_per_node: int = Field(default=0, ge=0, le=1024)
    gpus_per_task: int = Field(default=0, ge=0, le=1024)
    gpu_type: SafeIdentifier | None = None
    walltime: Annotated[
        str, StringConstraints(pattern=r"^(?:[0-9]{1,3}-)?[0-9]{2}:[0-9]{2}:[0-9]{2}$")
    ] = "01:00:00"
    nodelist: SlurmNodeExpression | None = None
    exclude_nodes: SlurmNodeExpression | None = None
    exclusive: bool = False
    constraint: SlurmConstraintExpression | None = None
    hint: (
        Literal["compute_bound", "memory_bound", "multithread", "nomultithread"] | None
    ) = None
    account: SafeIdentifier | None = None
    qos: SafeIdentifier | None = None
    reservation: SafeIdentifier | None = None

    @model_validator(mode="after")
    def validate_resource_shape(self) -> ResourceRequestV1:
        if self.tasks_per_node is not None and self.tasks_per_node > self.tasks:
            raise ValueError("tasks_per_node cannot exceed total tasks")
        if self.memory_mb_per_node and self.memory_mb_per_cpu:
            raise ValueError(
                "memory per node and memory per CPU are mutually exclusive"
            )
        if self.gpus_per_node and self.gpus_per_task:
            raise ValueError(
                "GPU per-node and per-task requests are mutually exclusive"
            )
        if self.gpu_type and not (self.gpus_per_node or self.gpus_per_task):
            raise ValueError("gpu_type requires an explicit GPU count")
        if self.nodelist and self.exclude_nodes and self.nodelist == self.exclude_nodes:
            raise ValueError("the same node expression cannot be included and excluded")
        return self


class EnvironmentPolicyV1(ContractModel):
    """A clean job environment containing only reviewed non-secret literals."""

    export_mode: Literal["NIL"] = "NIL"
    path: str = "/usr/local/bin:/usr/bin:/bin"
    variables: dict[str, str] = Field(default_factory=dict)
    modules: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_environment(self) -> EnvironmentPolicyV1:
        path_entries = self.path.split(":")
        if (
            not path_entries
            or any(
                not entry.startswith("/")
                or ".." in Path(entry).parts
                or any(character.isspace() for character in entry)
                for entry in path_entries
            )
            or any(character in self.path for character in "\x00\n\r")
        ):
            raise ValueError("environment PATH must contain inert absolute entries")
        for name, value in self.variables.items():
            if not _ENV_NAME_RE.fullmatch(name):
                raise ValueError(f"invalid environment variable name: {name!r}")
            if _SECRET_NAME_RE.search(name):
                raise ValueError(
                    f"credential-like variable {name!r} cannot be embedded in a job request"
                )
            if len(value.encode("utf-8")) > 4096 or any(
                character in value for character in "\x00\n\r"
            ):
                raise ValueError(
                    f"environment variable {name!r} is not an inert literal"
                )
        if len(self.variables) > 128:
            raise ValueError("at most 128 explicit environment variables are allowed")
        if len(self.modules) > 128 or any(
            not _MODULE_RE.fullmatch(module) for module in self.modules
        ):
            raise ValueError("module names must be bounded inert identifiers")
        if len(self.modules) != len(set(self.modules)):
            raise ValueError("module names must be unique")
        return self


class JobRequestV1(ContractModel):
    schema_version: Literal["ari.hpc.job-request/v1"] = SCHEMA_JOB_REQUEST_V1
    request_id: SafeIdentifier
    backend: Literal["slurm"] = "slurm"
    job_name: SafeIdentifier
    work_dir: str = Field(min_length=1, max_length=4096)
    argv: tuple[str, ...] = Field(min_length=1, max_length=256)
    resources: ResourceRequestV1
    environment: EnvironmentPolicyV1 = Field(default_factory=EnvironmentPolicyV1)
    container: ContainerRequestV1 | None = None
    inputs: tuple[ArtifactPinV1, ...] = ()
    outputs: tuple[OutputDeclarationV1, ...] = ()
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_request(self) -> JobRequestV1:
        work_dir = _absolute_path(self.work_dir, field="work_dir")
        for index, argument in enumerate(self.argv):
            if (
                not argument
                or len(argument.encode("utf-8")) > 16_384
                or any(character in argument for character in "\x00\n\r")
            ):
                raise ValueError(f"argv[{index}] must be a bounded inert argument")
        names = [item.logical_name for item in (*self.inputs, *self.outputs)]
        if len(names) != len(set(names)):
            raise ValueError("input and output logical names must be unique")
        for output in self.outputs:
            output_path = _absolute_path(output.path, field="output path")
            try:
                output_path.relative_to(work_dir)
            except ValueError as exc:
                raise ValueError("declared outputs must remain below work_dir") from exc
        if len(self.metadata) > 128:
            raise ValueError("job metadata is too large")
        for key, value in self.metadata.items():
            if not _ENV_NAME_RE.fullmatch(key.upper()) or _SECRET_NAME_RE.search(
                key.upper()
            ):
                raise ValueError("job metadata keys must be inert and non-secret")
            if isinstance(value, str) and (
                len(value.encode("utf-8")) > 4096
                or any(character in value for character in "\x00\n\r")
            ):
                raise ValueError("job metadata string values must be bounded literals")
        return self

    @property
    def request_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))


class JobSubmitArgumentsV1(ContractModel):
    """MCP argument wrapper that keeps all JSON Schema references at the root."""

    request: JobRequestV1


class JobHandleV1(ContractModel):
    schema_version: Literal["ari.hpc.job-handle/v1"] = SCHEMA_JOB_HANDLE_V1
    handle_id: SafeIdentifier
    request_id: SafeIdentifier
    request_digest: Digest
    backend: Literal["slurm"] = "slurm"
    cluster_identity: Digest
    job_id: JobId
    submission_digest: Digest
    workspace_scope: str
    artifact_scope: str
    state: Literal["submitted"] = "submitted"
    status: Literal["submitted"] = "submitted"
    submitted_at: str

    @model_validator(mode="after")
    def validate_scopes(self) -> JobHandleV1:
        _absolute_path(self.workspace_scope, field="workspace_scope")
        _absolute_path(self.artifact_scope, field="artifact_scope")
        return self


NormalizedJobState = Literal[
    "submitted", "running", "succeeded", "failed", "cancelled", "unknown"
]


class JobStatusV1(ContractModel):
    schema_version: Literal["ari.hpc.job-status/v1"] = SCHEMA_JOB_STATUS_V1
    handle_id: SafeIdentifier | None = None
    job_id: JobId
    state: NormalizedJobState
    scheduler_state: str = Field(min_length=1, max_length=128)
    exit_code: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    reason: str | None = Field(default=None, max_length=2000)


class JobLogV1(ContractModel):
    stream: Literal["stdout", "stderr", "scheduler"]
    path: str
    digest: Digest | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    text: str | None = Field(default=None, max_length=1_048_576)
    truncated: bool = False


class JobErrorV1(ContractModel):
    kind: Literal[
        "validation",
        "transport",
        "scheduler",
        "execution",
        "artifact",
        "unknown",
    ]
    message: str = Field(min_length=1, max_length=2000)
    retryable: bool = False


class JobResultV1(ContractModel):
    schema_version: Literal["ari.hpc.job-result/v1"] = SCHEMA_JOB_RESULT_V1
    handle: JobHandleV1
    status: JobStatusV1
    request_digest: Digest
    environment_digest: Digest
    module_digest: Digest
    module_snapshot_digest: Digest | None = None
    container_digest: Digest | None = None
    inputs: tuple[ArtifactPinV1, ...] = ()
    outputs: tuple[ArtifactPinV1, ...] = ()
    provenance: tuple[ArtifactPinV1, ...] = ()
    logs: tuple[JobLogV1, ...] = ()
    error: JobErrorV1 | None = None
    result_digest: Digest | None = None

    def with_digest(self) -> JobResultV1:
        payload = self.model_dump(mode="json")
        payload.pop("result_digest", None)
        return self.model_copy(update={"result_digest": sha256_digest(payload)})
