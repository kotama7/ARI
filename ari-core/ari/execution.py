"""Closed workspace and local-process execution contracts.

This module owns the low-level process-group, environment, resource, log, and
workspace primitives shared by Skills.  It intentionally does not own scheduler
or container lifecycle; those adapters bind their own substrate identity to the
same request/result records.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import signal
import stat
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EXECUTION_REQUEST_V1 = "ari.execution-request/v1"
EXECUTION_RESULT_V1 = "ari.execution-result/v1"
MEASUREMENT_SET_V1 = "ari.measurement-set/v1"
WORKSPACE_REF_V1 = "ari.workspace-ref/v1"
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_SECRET_NAME_RE = re.compile(
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|PRIVATE_?KEY|CREDENTIAL)",
    re.IGNORECASE,
)
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin"
_PLATFORM_ENV = ("LANG", "LC_ALL", "SSL_CERT_DIR", "SSL_CERT_FILE")
_MAX_INPUT_BYTES = 256 * 1024 * 1024


class ExecutionPolicyError(RuntimeError):
    """The request cannot be executed under its declared security policy."""


class MeasurementDocumentError(ValueError):
    """A typed or supported legacy measurement document is inconsistent."""


MeasurementDocumentFormat = Literal[
    "canonical", "legacy-v1", "legacy-unversioned"
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(payload)


class WorkspaceRefV1(BaseModel):
    """One canonical writable root with no caller-controlled escape path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.workspace-ref/v1"] = WORKSPACE_REF_V1
    root: str

    @field_validator("root")
    @classmethod
    def _canonical_root(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("workspace root must be absolute")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink() or not path.is_dir():
            raise ValueError("workspace root must be a real directory")
        return str(path.resolve(strict=True))

    def _parts(self, value: str, *, allow_absolute: bool) -> tuple[str, ...]:
        path = Path(value)
        root = Path(self.root)
        if path.is_absolute():
            if not allow_absolute:
                raise ExecutionPolicyError("absolute workspace paths are not allowed")
            try:
                path = path.relative_to(root)
            except ValueError as exc:
                raise ExecutionPolicyError("path escapes the workspace root") from exc
        pure = PurePosixPath(path.as_posix())
        if not pure.parts or pure == PurePosixPath("."):
            raise ExecutionPolicyError("workspace path must name a file")
        if any(part in {"", ".", ".."} for part in pure.parts):
            raise ExecutionPolicyError("workspace path traversal is not allowed")
        return tuple(pure.parts)

    def resolve(
        self,
        value: str,
        *,
        allow_absolute: bool = True,
        must_exist: bool = True,
        require_file: bool = False,
    ) -> Path:
        parts = self._parts(value, allow_absolute=allow_absolute)
        current = Path(self.root)
        for index, part in enumerate(parts):
            current = current / part
            if current.is_symlink():
                raise ExecutionPolicyError("workspace symlinks are not allowed")
            if current.exists() and index < len(parts) - 1 and not current.is_dir():
                raise ExecutionPolicyError("workspace parent is not a directory")
        if must_exist and not current.exists():
            raise FileNotFoundError(current)
        if require_file and (not current.is_file() or current.is_symlink()):
            raise ExecutionPolicyError("workspace path is not a regular file")
        try:
            current.resolve(strict=must_exist).relative_to(Path(self.root))
        except ValueError as exc:
            raise ExecutionPolicyError("resolved path escapes the workspace") from exc
        return current

    def read_bytes(self, value: str, *, max_bytes: int) -> bytes:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        fd = self.open_read_fd(value)
        try:
            size = os.fstat(fd).st_size
            if size > max_bytes:
                raise ExecutionPolicyError("workspace file exceeds the read limit")
            chunks: list[bytes] = []
            remaining = max_bytes + 1
            while remaining:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
        finally:
            os.close(fd)
        if len(payload) > max_bytes:
            raise ExecutionPolicyError("workspace file grew beyond the read limit")
        return payload

    def open_read_fd(self, value: str) -> int:
        """Open a regular file through dirfds so path swaps cannot escape root."""

        parts = self._parts(value, allow_absolute=True)
        directory_fd = os.open(
            self.root,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            for part in parts[:-1]:
                child_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = child_fd
            fd = os.open(
                parts[-1],
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            status = os.fstat(fd)
            if not stat.S_ISREG(status.st_mode):
                os.close(fd)
                raise ExecutionPolicyError("workspace path is not a regular file")
            return fd
        except OSError as exc:
            raise ExecutionPolicyError(
                "workspace path changed or contains a symlink"
            ) from exc
        finally:
            os.close(directory_fd)

    def file_digest(self, value: str) -> str:
        fd = self.open_read_fd(value)
        digest = hashlib.sha256()
        try:
            while chunk := os.read(fd, 1024 * 1024):
                digest.update(chunk)
        finally:
            os.close(fd)
        return "sha256:" + digest.hexdigest()

    def ensure_directory(self, value: str) -> Path:
        """Create a caller-selected subdirectory without following symlinks."""

        parts = self._parts(value, allow_absolute=True)
        directory_fd = os.open(
            self.root,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            for part in parts:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=directory_fd)
                except FileExistsError:
                    pass
                child_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = child_fd
        except OSError as exc:
            raise ExecutionPolicyError(
                "workspace directory changed or contains a symlink"
            ) from exc
        finally:
            os.close(directory_fd)
        return Path(self.root).joinpath(*parts)

    def atomic_write_bytes(self, value: str, payload: bytes) -> Path:
        parts = self._parts(value, allow_absolute=False)
        directory_fd = os.open(
            self.root,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=directory_fd)
                except FileExistsError:
                    pass
                child_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = child_fd
            final_name = parts[-1]
            try:
                status = os.stat(final_name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                status = None
            if status is not None and not stat.S_ISREG(status.st_mode):
                raise ExecutionPolicyError("write target is not a regular file")
            temporary = f".ari-write-{secrets.token_hex(12)}.tmp"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
            try:
                try:
                    view = memoryview(payload)
                    while view:
                        written = os.write(fd, view)
                        view = view[written:]
                    os.fsync(fd)
                finally:
                    os.close(fd)
                os.replace(
                    temporary,
                    final_name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
                os.fsync(directory_fd)
            except Exception:
                try:
                    os.unlink(temporary, dir_fd=directory_fd)
                except OSError:
                    pass
                raise
        finally:
            os.close(directory_fd)
        return Path(self.root).joinpath(*parts)

    def atomic_write_text(self, value: str, text: str) -> Path:
        return self.atomic_write_bytes(value, text.encode("utf-8"))


class ExecutionLimitsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cpu_seconds: int | None = Field(default=None, ge=1, le=86_400)
    memory_bytes: int | None = Field(default=None, ge=16 * 1024 * 1024)
    max_processes: int | None = Field(default=None, ge=1, le=65_536)
    max_output_bytes: int = Field(default=64 * 1024 * 1024, ge=1024, le=1024**3)


class ResourceLimitReportV1(BaseModel):
    """What the launcher actually enforced, distinct from requested limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    substrate: Literal["posix-kernel", "external-unverified"]
    wall_time: Literal["executor", "external-unverified"]
    process_group: Literal["executor", "external-unverified"]
    enforced: list[Literal["cpu", "memory", "processes", "output"]] = Field(
        default_factory=list
    )

    @field_validator("enforced")
    @classmethod
    def _unique_enforced(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("enforced resource limits must be unique")
        return value

    @model_validator(mode="after")
    def _report_is_coherent(self) -> "ResourceLimitReportV1":
        if self.substrate == "external-unverified":
            if (
                self.wall_time != "external-unverified"
                or self.process_group != "external-unverified"
                or self.enforced
            ):
                raise ValueError("external resource report cannot claim enforcement")
        elif (
            self.wall_time != "executor"
            or self.process_group != "executor"
            or "output" not in self.enforced
        ):
            raise ValueError("POSIX resource report is incomplete")
        return self


class ContainerIdentityV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime: Literal["docker", "singularity", "apptainer", "unknown"]
    reference: str
    digest: str | None = None
    resolution_status: Literal["resolved", "unresolved"]

    @field_validator("digest")
    @classmethod
    def _digest(cls, value: str | None) -> str | None:
        if value is not None and not _DIGEST_RE.fullmatch(value):
            raise ValueError("container digest must be SHA-256")
        return value

    @model_validator(mode="after")
    def _status_matches_digest(self) -> "ContainerIdentityV1":
        if (self.digest is not None) != (self.resolution_status == "resolved"):
            raise ValueError("container resolution status and digest differ")
        return self


class ExecutionRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.execution-request/v1"] = EXECUTION_REQUEST_V1
    workspace: WorkspaceRefV1
    argv: list[str] | None = Field(default=None, min_length=1, max_length=256)
    shell_command: str | None = Field(default=None, max_length=100_000)
    timeout_seconds: float = Field(default=60, gt=0, le=86_400)
    environment: dict[str, str] = Field(default_factory=dict, max_length=128)
    limits: ExecutionLimitsV1 = Field(default_factory=ExecutionLimitsV1)
    network: Literal["inherit", "deny"] = "inherit"
    request_id: str | None = None
    input_digests: dict[str, str] = Field(default_factory=dict, max_length=1_024)
    container: ContainerIdentityV1 | None = None

    @field_validator("argv")
    @classmethod
    def _argv(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(
            not isinstance(item, str) or "\x00" in item or len(item) > 100_000
            for item in value
        ):
            raise ValueError("execution argv contains an invalid item")
        return value

    @field_validator("shell_command")
    @classmethod
    def _shell(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or "\x00" in value):
            raise ValueError("shell command is empty or invalid")
        return value

    @field_validator("environment")
    @classmethod
    def _environment(cls, value: dict[str, str]) -> dict[str, str]:
        for name, item in value.items():
            if (
                not _ENV_NAME_RE.fullmatch(name)
                or _SECRET_NAME_RE.search(name)
                or not isinstance(item, str)
                or "\x00" in item
            ):
                raise ValueError("execution environment contains an unsafe entry")
        return dict(sorted(value.items()))

    @field_validator("request_id")
    @classmethod
    def _request_id(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_ID_RE.fullmatch(value):
            raise ValueError("execution request_id is invalid")
        return value

    @field_validator("input_digests")
    @classmethod
    def _input_digests(cls, value: dict[str, str]) -> dict[str, str]:
        for path, digest in value.items():
            pure = PurePosixPath(path)
            if (
                not path
                or pure.is_absolute()
                or any(part in {"", ".", ".."} for part in pure.parts)
            ):
                raise ValueError("execution input digest path is unsafe")
            if not _DIGEST_RE.fullmatch(digest):
                raise ValueError("execution input digests must be SHA-256")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _one_command(self) -> "ExecutionRequestV1":
        if (self.argv is None) == (self.shell_command is None):
            raise ValueError("execution requires exactly one of argv or shell_command")
        return self

    @property
    def execution_identity(self) -> str:
        payload = self.model_dump(mode="json")
        payload.pop("request_id", None)
        return _canonical_digest(payload)


class ExecutionArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_role: Literal["stdout", "stderr"]
    relative_path: str
    digest: str
    size_bytes: int = Field(ge=0)
    media_type: Literal["text/plain; charset=utf-8"] = "text/plain; charset=utf-8"

    @field_validator("digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        if not _DIGEST_RE.fullmatch(value):
            raise ValueError("execution artifact digest must be SHA-256")
        return value

    @field_validator("relative_path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        pure = PurePosixPath(value)
        if (
            not value
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise ValueError("execution artifact path must be safe and relative")
        return value


class ExecutionResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.execution-result/v1"] = EXECUTION_RESULT_V1
    status: Literal["completed", "failed", "timed_out", "cancelled"]
    execution_identity: str
    request_id: str | None = None
    attempt_id: str
    exit_code: int | None
    started_at: str
    completed_at: str
    stdout_preview: str
    stderr_preview: str
    stdout_truncated: bool
    stderr_truncated: bool
    artifacts: list[ExecutionArtifactV1]
    environment_names: list[str]
    network: Literal["inherit", "deny"]
    network_report: Literal["inherited", "isolated", "external-unverified"]
    limits: ExecutionLimitsV1
    limit_report: ResourceLimitReportV1
    input_digests: dict[str, str] = Field(default_factory=dict)
    input_bindings: dict[
        str,
        Literal["immutable-snapshot", "verified-at-launch", "external-unverified"],
    ] = Field(default_factory=dict)
    container: ContainerIdentityV1 | None = None

    @field_validator("execution_identity")
    @classmethod
    def _identity(cls, value: str) -> str:
        if not _DIGEST_RE.fullmatch(value):
            raise ValueError("execution identity must be SHA-256")
        return value

    @field_validator("attempt_id")
    @classmethod
    def _attempt_id(cls, value: str) -> str:
        if not _SAFE_ID_RE.fullmatch(value):
            raise ValueError("execution attempt_id is invalid")
        return value

    @field_validator("started_at", "completed_at")
    @classmethod
    def _timestamp(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("execution timestamp must be ISO-8601") from exc
        if parsed.utcoffset() is None:
            raise ValueError("execution timestamp must include a timezone")
        return value

    @field_validator("environment_names")
    @classmethod
    def _environment_names(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(
            not _ENV_NAME_RE.fullmatch(name) or _SECRET_NAME_RE.search(name)
            for name in value
        ):
            raise ValueError("execution environment names are unsafe or duplicated")
        return value

    @field_validator("input_digests")
    @classmethod
    def _result_input_digests(cls, value: dict[str, str]) -> dict[str, str]:
        for path, digest in value.items():
            pure = PurePosixPath(path)
            if (
                not path
                or pure.is_absolute()
                or any(part in {"", ".", ".."} for part in pure.parts)
                or not _DIGEST_RE.fullmatch(digest)
            ):
                raise ValueError("execution result input digest is invalid")
        return value

    @model_validator(mode="after")
    def _input_reports_match(self) -> "ExecutionResultV1":
        if set(self.input_bindings) != set(self.input_digests):
            raise ValueError("execution input binding report is incomplete")
        roles = [artifact.logical_role for artifact in self.artifacts]
        if sorted(roles) != ["stderr", "stdout"]:
            raise ValueError("execution result requires one stdout and one stderr artifact")
        paths = [artifact.relative_path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("execution artifact paths must be unique")
        started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
        completed = datetime.fromisoformat(self.completed_at.replace("Z", "+00:00"))
        if completed < started:
            raise ValueError("execution completion predates its start")
        return self


def build_minimal_environment(
    explicit: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the non-secret environment inherited by reviewed launchers."""

    explicit = explicit or {}
    for name, item in explicit.items():
        if (
            not _ENV_NAME_RE.fullmatch(name)
            or _SECRET_NAME_RE.search(name)
            or not isinstance(item, str)
            or "\x00" in item
        ):
            raise ExecutionPolicyError("execution environment contains an unsafe entry")
    environment = {
        "HOME": "/nonexistent",
        "LOGNAME": "ari-executor",
        "USER": "ari-executor",
        "SHELL": "",
        "TERM": "dumb",
        "PATH": _DEFAULT_PATH,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    for name in _PLATFORM_ENV:
        value = os.environ.get(name)
        if value:
            environment[name] = value
    environment.update(explicit)
    return environment


def _resource_limit_report(limits: ExecutionLimitsV1) -> ResourceLimitReportV1:
    if os.name != "posix":
        raise ExecutionPolicyError("local execution requires POSIX resource controls")
    try:
        import resource
    except ImportError as exc:  # pragma: no cover - POSIX Python always provides it
        raise ExecutionPolicyError("POSIX resource controls are unavailable") from exc

    requested = ["output"]
    required = {"output": "RLIMIT_FSIZE"}
    if limits.cpu_seconds is not None:
        requested.append("cpu")
        required["cpu"] = "RLIMIT_CPU"
    if limits.memory_bytes is not None:
        requested.append("memory")
        required["memory"] = "RLIMIT_AS"
    if limits.max_processes is not None:
        requested.append("processes")
        required["processes"] = "RLIMIT_NPROC"
    missing = [name for name, attr in required.items() if not hasattr(resource, attr)]
    if missing:
        raise ExecutionPolicyError(
            "kernel cannot enforce requested limits: " + ", ".join(sorted(missing))
        )
    return ResourceLimitReportV1(
        substrate="posix-kernel",
        wall_time="executor",
        process_group="executor",
        enforced=requested,
    )


def _preexec(limits: ExecutionLimitsV1) -> None:
    os.setsid()
    import resource

    if limits.cpu_seconds is not None:
        resource.setrlimit(
            resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds)
        )
    if limits.memory_bytes is not None:
        resource.setrlimit(
            resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes)
        )
    if limits.max_processes is not None:
        _soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
        cap = (
            limits.max_processes
            if hard == resource.RLIM_INFINITY
            else min(hard, limits.max_processes)
        )
        resource.setrlimit(resource.RLIMIT_NPROC, (cap, cap))
    resource.setrlimit(
        resource.RLIMIT_FSIZE,
        (limits.max_output_bytes, limits.max_output_bytes),
    )


def _terminate_group(process: subprocess.Popen[Any]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        process.kill()
    process.wait()


def _preview(value: bytes, limit: int) -> tuple[str, bool]:
    text = value.decode("utf-8", errors="replace")
    if len(text) <= limit:
        return text, False
    marker_template = "\n... [{} chars truncated; full log is an artifact] ...\n"
    marker = marker_template.format(len(text))
    if len(marker) >= limit:
        return marker[:limit], True
    content_budget = limit - len(marker)
    omitted = len(text) - content_budget
    marker = marker_template.format(omitted)
    # The omitted digit count can make the final marker a few characters wider.
    content_budget = max(0, limit - len(marker))
    head = (content_budget + 1) // 2
    tail = content_budget - head
    return text[:head] + marker + (text[-tail:] if tail else ""), True


def _store_log(
    workspace: WorkspaceRefV1, role: Literal["stdout", "stderr"], value: bytes
) -> ExecutionArtifactV1:
    digest = _sha256_bytes(value)
    name = f".ari-execution/{digest.removeprefix('sha256:')}.{role}.log"
    path = workspace.atomic_write_bytes(name, value)
    return ExecutionArtifactV1(
        logical_role=role,
        relative_path=path.relative_to(workspace.root).as_posix(),
        digest=digest,
        size_bytes=len(value),
    )


def _snapshot_inputs(
    request: ExecutionRequestV1,
    temp: Path,
) -> tuple[list[str] | None, dict[str, str]]:
    """Verify declared inputs and bind argv file operands to private snapshots."""

    argv = list(request.argv) if request.argv is not None else None
    bindings: dict[str, str] = {}
    for relative_path, expected_digest in request.input_digests.items():
        payload = request.workspace.read_bytes(
            relative_path, max_bytes=_MAX_INPUT_BYTES
        )
        actual_digest = _sha256_bytes(payload)
        if actual_digest != expected_digest:
            raise ExecutionPolicyError(
                f"input digest changed before launch: {relative_path}"
            )
        snapshot_dir = temp / "inputs" / actual_digest.removeprefix("sha256:")
        snapshot_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        snapshot = snapshot_dir / Path(relative_path).name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(snapshot, flags, 0o400)
        except FileExistsError:
            if snapshot.read_bytes() != payload:
                raise ExecutionPolicyError("content-addressed input snapshot collision")
        else:
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
        binding = "verified-at-launch"
        if argv is not None:
            absolute = str(Path(request.workspace.root) / relative_path)
            replacements = {relative_path, absolute}
            replaced = False
            for index, item in enumerate(argv):
                if item in replacements:
                    argv[index] = str(snapshot)
                    replaced = True
            if replaced:
                binding = "immutable-snapshot"
        bindings[relative_path] = binding
    return argv, bindings


def execute_local(
    request: ExecutionRequestV1,
    *,
    cancel_event: threading.Event | None = None,
    network_isolation_verified: bool = False,
) -> ExecutionResultV1:
    """Execute one exact request without a parent environment copy.

    A request for network denial is rejected unless a reviewed caller has
    already wrapped the command in an isolation boundary (for example Docker's
    ``--network none``). Merely asking for denial never changes provenance.
    """

    if request.network == "deny" and not network_isolation_verified:
        raise ExecutionPolicyError(
            "host execution cannot prove network denial; use a reviewed isolated substrate"
        )
    limit_report = _resource_limit_report(request.limits)
    started_at = _now()
    attempt_id = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="ari-execution-log-") as temp_text:
        temp = Path(temp_text)
        argv, input_bindings = _snapshot_inputs(request, temp)
        command = (
            argv
            if argv is not None
            else [
                "/bin/bash",
                "--noprofile",
                "--norc",
                "-c",
                request.shell_command or "",
            ]
        )
        stdout_path = temp / "stdout"
        stderr_path = temp / "stderr"
        terminal_reason: Literal["exited", "timed_out", "cancelled"] = "exited"
        with (
            stdout_path.open("wb") as stdout_stream,
            stderr_path.open("wb") as stderr_stream,
        ):
            process = subprocess.Popen(
                command,
                cwd=request.workspace.root,
                env=build_minimal_environment(request.environment),
                stdin=subprocess.DEVNULL,
                stdout=stdout_stream,
                stderr=stderr_stream,
                shell=False,
                close_fds=True,
                preexec_fn=lambda: _preexec(request.limits),
            )
            deadline = time.monotonic() + request.timeout_seconds
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    terminal_reason = "cancelled"
                    _terminate_group(process)
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    terminal_reason = "timed_out"
                    _terminate_group(process)
                    break
                time.sleep(min(0.05, remaining))
        stdout = stdout_path.read_bytes()
        stderr = stderr_path.read_bytes()
    stdout_preview, stdout_truncated = _preview(stdout, 4_000)
    stderr_preview, stderr_truncated = _preview(stderr, 2_000)
    artifacts = [
        _store_log(request.workspace, "stdout", stdout),
        _store_log(request.workspace, "stderr", stderr),
    ]
    if terminal_reason == "timed_out":
        status: Literal["completed", "failed", "timed_out", "cancelled"] = "timed_out"
    elif terminal_reason == "cancelled":
        status = "cancelled"
    else:
        status = "completed" if process.returncode == 0 else "failed"
    return ExecutionResultV1(
        status=status,
        execution_identity=request.execution_identity,
        request_id=request.request_id,
        attempt_id=attempt_id,
        exit_code=None if terminal_reason != "exited" else process.returncode,
        started_at=started_at,
        completed_at=_now(),
        stdout_preview=stdout_preview,
        stderr_preview=stderr_preview,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        artifacts=artifacts,
        environment_names=sorted(build_minimal_environment(request.environment)),
        network=request.network,
        network_report="isolated" if request.network == "deny" else "inherited",
        limits=request.limits,
        limit_report=limit_report,
        input_digests=request.input_digests,
        input_bindings=input_bindings,
        container=request.container,
    )


def record_completed_execution(
    request: ExecutionRequestV1,
    *,
    stdout: str | bytes,
    stderr: str | bytes,
    returncode: int,
    started_at: str | None = None,
    inputs_verified: bool = False,
    network_verified: bool = False,
) -> ExecutionResultV1:
    """Normalize an already-executed reviewed substrate into the same record."""

    stdout_bytes = stdout.encode("utf-8") if isinstance(stdout, str) else stdout
    stderr_bytes = stderr.encode("utf-8") if isinstance(stderr, str) else stderr
    if (
        len(stdout_bytes) > request.limits.max_output_bytes
        or len(stderr_bytes) > request.limits.max_output_bytes
    ):
        raise ExecutionPolicyError("external execution log exceeds the declared limit")
    stdout_preview, stdout_truncated = _preview(stdout_bytes, 4_000)
    stderr_preview, stderr_truncated = _preview(stderr_bytes, 2_000)
    return ExecutionResultV1(
        status="completed" if returncode == 0 else "failed",
        execution_identity=request.execution_identity,
        request_id=request.request_id,
        attempt_id=secrets.token_hex(16),
        exit_code=returncode,
        started_at=started_at or _now(),
        completed_at=_now(),
        stdout_preview=stdout_preview,
        stderr_preview=stderr_preview,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        artifacts=[
            _store_log(request.workspace, "stdout", stdout_bytes),
            _store_log(request.workspace, "stderr", stderr_bytes),
        ],
        environment_names=sorted(build_minimal_environment(request.environment)),
        network=request.network,
        network_report=(
            "isolated"
            if request.network == "deny" and network_verified
            else "external-unverified"
        ),
        limits=request.limits,
        limit_report=ResourceLimitReportV1(
            substrate="external-unverified",
            wall_time="external-unverified",
            process_group="external-unverified",
        ),
        input_digests=request.input_digests,
        input_bindings={
            path: "verified-at-launch" if inputs_verified else "external-unverified"
            for path in request.input_digests
        },
        container=request.container,
    )


class MeasurementRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str
    value: int | float
    unit: str | None = None
    unit_status: Literal["declared", "missing"]
    provenance: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    artifact_digests: list[str] = Field(default_factory=list)
    execution_identity: str | None = None
    execution_attempt_id: str | None = None
    execution_status: Literal[
        "completed", "failed", "timed_out", "cancelled", "unreported"
    ] = "unreported"
    exit_code: int | None = None

    @field_validator("metric_id")
    @classmethod
    def _metric_id(cls, value: str) -> str:
        if not value.strip() or len(value) > 256 or value.startswith("_"):
            raise ValueError("measurement metric_id is invalid")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, value: Any) -> int | float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError("measurement value must be a finite number")
        return value

    @field_validator("unit")
    @classmethod
    def _unit(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or len(value) > 100):
            raise ValueError("measurement unit is invalid")
        return value

    @field_validator("provenance")
    @classmethod
    def _provenance(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or len(value) > 1_000):
            raise ValueError("measurement provenance is invalid")
        return value

    @field_validator("parameters")
    @classmethod
    def _parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("measurement parameters must be finite JSON") from exc
        return value

    @field_validator("artifact_digests")
    @classmethod
    def _artifact_digests(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(
            not _DIGEST_RE.fullmatch(item) for item in value
        ):
            raise ValueError("measurement artifact digests must be unique SHA-256")
        return sorted(value)

    @field_validator("execution_identity")
    @classmethod
    def _execution_identity(cls, value: str | None) -> str | None:
        if value is not None and not _DIGEST_RE.fullmatch(value):
            raise ValueError("measurement execution identity must be SHA-256")
        return value

    @field_validator("execution_attempt_id")
    @classmethod
    def _execution_attempt_id(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_ID_RE.fullmatch(value):
            raise ValueError("measurement execution attempt ID is invalid")
        return value

    @model_validator(mode="after")
    def _unit_status(self) -> "MeasurementRecordV1":
        if (self.unit is not None) != (self.unit_status == "declared"):
            raise ValueError("measurement unit status differs from unit")
        if self.execution_status == "unreported":
            if (
                self.execution_identity is not None
                or self.execution_attempt_id is not None
                or self.exit_code is not None
            ):
                raise ValueError(
                    "unreported execution cannot carry identity, attempt, or exit code"
                )
        elif self.execution_identity is None or self.execution_attempt_id is None:
            raise ValueError(
                "reported execution requires an execution identity and attempt ID"
            )
        if self.execution_status in {"completed", "failed"}:
            if self.exit_code is None:
                raise ValueError("completed or failed execution requires an exit code")
        elif self.exit_code is not None:
            raise ValueError("non-exited execution cannot carry an exit code")
        return self


class MeasurementSetV1(BaseModel):
    """Canonical typed view plus an explicit compatibility projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.measurement-set/v1"] = MEASUREMENT_SET_V1
    parameters: dict[str, Any] = Field(default_factory=dict)
    measurements: list[MeasurementRecordV1] = Field(default_factory=list)
    predictions: dict[str, Any] = Field(default_factory=dict)
    scores: dict[str, Any] = Field(default_factory=dict)
    artifact_digests: list[str] = Field(default_factory=list)

    @field_validator("parameters", "predictions", "scores")
    @classmethod
    def _json_groups(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("measurement groups must be finite JSON") from exc
        return value

    @field_validator("artifact_digests")
    @classmethod
    def _set_artifacts(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(
            not _DIGEST_RE.fullmatch(item) for item in value
        ):
            raise ValueError("measurement-set artifact digests must be unique SHA-256")
        return sorted(value)

    @model_validator(mode="after")
    def _disjoint_names(self) -> "MeasurementSetV1":
        measurement_names = [item.metric_id for item in self.measurements]
        if len(measurement_names) != len(set(measurement_names)):
            raise ValueError("measurement IDs must be unique")
        groups = [
            set(self.parameters),
            set(measurement_names),
            set(self.predictions),
            set(self.scores),
        ]
        if any(
            groups[left] & groups[right]
            for left in range(4)
            for right in range(left + 1, 4)
        ):
            raise ValueError(
                "parameter, measurement, prediction, and score names overlap"
            )
        record_artifacts = {
            digest for record in self.measurements for digest in record.artifact_digests
        }
        if not record_artifacts.issubset(set(self.artifact_digests)):
            raise ValueError("measurement artifact is absent from measurement set")
        if any(record.parameters != self.parameters for record in self.measurements):
            raise ValueError("measurement record parameters differ from measurement set")
        return self


def measurement_document_format(document: dict[str, Any]) -> MeasurementDocumentFormat:
    """Classify compatibility usage without parsing values a second time."""

    if document.get("typed_schema_version") is not None:
        return "canonical"
    if document.get("schema_version") is None:
        return "legacy-unversioned"
    return "legacy-v1"


def parse_measurement_document(
    document: dict[str, Any], *, allow_legacy: bool = True
) -> MeasurementSetV1:
    """Validate a canonical measurement set or migrate one supported v1 file.

    Typed documents are cross-checked against every retained flat projection so
    consumers cannot be shown different values by old and new readers.
    Unversioned and ``schema_version: 1.x`` files remain read-only inputs during
    the P6 support window; their absent units and execution provenance stay
    explicitly absent.
    """

    if not isinstance(document, dict):
        raise MeasurementDocumentError("measurement document must be an object")
    typed_version = document.get("typed_schema_version")
    if typed_version is not None:
        if typed_version != MEASUREMENT_SET_V1:
            raise MeasurementDocumentError(
                f"unsupported typed measurement schema: {typed_version!r}"
            )
        projection_version = document.get("schema_version")
        if projection_version is not None and (
            not isinstance(projection_version, str)
            or projection_version.split(".", 1)[0] != "1"
        ):
            raise MeasurementDocumentError(
                "typed measurement compatibility projection is not v1"
            )
        canonical = document.get("measurement_set")
        if not isinstance(canonical, dict):
            raise MeasurementDocumentError("typed measurement_set is missing")
        try:
            value = MeasurementSetV1.model_validate(canonical)
        except Exception as exc:
            raise MeasurementDocumentError("typed measurement_set is invalid") from exc
        projections: tuple[tuple[str, Any], ...] = (
            ("params", value.parameters),
            (
                "measurements",
                {record.metric_id: record.value for record in value.measurements},
            ),
            ("predictions", value.predictions),
            ("scores", value.scores),
            (
                "measurement_records",
                [record.model_dump(mode="json") for record in value.measurements],
            ),
        )
        for key, expected in projections:
            if key in document and document[key] != expected:
                raise MeasurementDocumentError(
                    f"typed measurement projection differs at {key}"
                )
        projected_provenance = {
            record.metric_id: record.provenance
            for record in value.measurements
            if record.provenance is not None
        }
        if (
            "_provenance" in document
            and document["_provenance"] != projected_provenance
        ):
            raise MeasurementDocumentError(
                "typed measurement provenance projection differs"
            )
        return value

    if not allow_legacy:
        raise MeasurementDocumentError("legacy measurement document is not admitted")
    if "measurement_set" in document or "measurement_records" in document:
        raise MeasurementDocumentError(
            "canonical measurement fields require typed_schema_version"
        )
    legacy_version = document.get("schema_version")
    if legacy_version is not None and (
        not isinstance(legacy_version, str) or legacy_version.split(".", 1)[0] != "1"
    ):
        raise MeasurementDocumentError(
            f"unsupported legacy measurement schema: {legacy_version!r}"
        )
    parameters = document.get("params", {})
    measurements = document.get("measurements", {})
    predictions = document.get("predictions", {})
    scores = document.get("scores", {})
    provenance = document.get("_provenance", {})
    if not all(
        isinstance(group, dict)
        for group in (parameters, measurements, predictions, scores, provenance)
    ):
        raise MeasurementDocumentError("legacy measurement groups must be objects")
    if set(provenance) - set(measurements):
        raise MeasurementDocumentError("legacy provenance names an unknown measurement")
    try:
        records = [
            MeasurementRecordV1(
                metric_id=str(metric_id),
                value=value,
                unit=None,
                unit_status="missing",
                provenance=provenance.get(metric_id),
                parameters=parameters,
            )
            for metric_id, value in sorted(measurements.items())
        ]
        return MeasurementSetV1(
            parameters=parameters,
            measurements=records,
            predictions=predictions,
            scores=scores,
        )
    except Exception as exc:
        raise MeasurementDocumentError(
            "legacy measurement document is invalid"
        ) from exc


__all__ = [
    "ContainerIdentityV1",
    "EXECUTION_REQUEST_V1",
    "EXECUTION_RESULT_V1",
    "ExecutionArtifactV1",
    "ExecutionLimitsV1",
    "ExecutionPolicyError",
    "ExecutionRequestV1",
    "ExecutionResultV1",
    "MEASUREMENT_SET_V1",
    "MeasurementRecordV1",
    "MeasurementDocumentError",
    "MeasurementDocumentFormat",
    "MeasurementSetV1",
    "ResourceLimitReportV1",
    "WORKSPACE_REF_V1",
    "WorkspaceRefV1",
    "build_minimal_environment",
    "execute_local",
    "measurement_document_format",
    "parse_measurement_document",
    "record_completed_execution",
]
