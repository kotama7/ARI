"""Private attempt workspaces and fail-closed reproduction execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import shutil
import signal
import stat
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ari.public.execution import (
    ContainerIdentityV1,
    ExecutionLimitsV1,
    ExecutionRequestV1,
    WorkspaceRefV1,
    build_minimal_environment,
    execute_local,
    record_completed_execution,
)

from contracts import (
    FailureEvidenceV1,
    ReproductionAttemptV1,
    ReproductionContractError,
    ReproductionPlanV1,
    ReproductionPolicyV1,
    ReproductionRunV1,
    SandboxImageV1,
    artifact_from_path,
    bytes_digest,
    canonical_digest,
    safe_relative_path,
)


_INTERNAL_DIR = ".ari-reproduction"
log = logging.getLogger(__name__)
_MAX_TREE_FILE_BYTES = 1024**3
_MAX_TREE_BYTES = 8 * 1024**3
_RUNTIME_IDENTITY_COMMAND = (
    "umask 077; { "
    "echo 'schema=ari.runtime-identity/v1'; "
    "echo \"hostname=$(hostname 2>/dev/null || true)\"; "
    "echo \"uname=$(uname -a 2>/dev/null || true)\"; "
    "echo \"machine=$(uname -m 2>/dev/null || true)\"; "
    "echo \"gcc=$(gcc --version 2>/dev/null | head -n 1 || true)\"; "
    "echo \"clang=$(clang --version 2>/dev/null | head -n 1 || true)\"; "
    "echo \"nvcc=$(nvcc --version 2>/dev/null | tail -n 1 || true)\"; "
    "echo \"gpu=$(nvidia-smi --query-gpu=name,uuid,driver_version "
    "--format=csv,noheader 2>/dev/null || true)\"; "
    "} > .ari-runtime-identity.txt 2>&1 || true; "
    "exec /bin/bash reproduce.sh"
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tool_version(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    if path is None:
        return {"status": "absent"}
    try:
        result = subprocess.run(
            [path, "--version"],
            env=build_minimal_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=5,
            check=False,
        )
        text = (result.stdout or result.stderr).decode(
            "utf-8", errors="replace"
        )[:4096]
        return {
            "status": "observed",
            "path": path,
            "exit_code": result.returncode,
            "version": text.splitlines()[0] if text else "",
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "error", "path": path, "error": str(exc)[:1000]}


def host_environment_identity() -> dict[str, Any]:
    cpu_model = ""
    try:
        for line in Path("/proc/cpuinfo").read_text(errors="replace").splitlines():
            if line.casefold().startswith("model name") and ":" in line:
                cpu_model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {
        "observation_scope": "submission-host",
        "hostname": platform.node(),
        "platform": platform.platform(),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu": {"logical_count": os.cpu_count(), "model": cpu_model},
        "compilers": {
            name: _tool_version(name) for name in ("gcc", "clang", "nvcc", "mpicc")
        },
    }


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    temporary.write_bytes(payload)
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _iter_files(root: Path) -> Iterable[tuple[str, Path]]:
    total = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == _INTERNAL_DIR:
            continue
        if path.is_symlink():
            raise ReproductionContractError(
                f"reproduction input/output contains a symlink: {relative}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise ReproductionContractError(
                f"reproduction tree contains a non-regular file: {relative}"
            )
        size = path.stat().st_size
        if size > _MAX_TREE_FILE_BYTES:
            raise ReproductionContractError(
                f"reproduction file is too large: {relative}"
            )
        total += size
        if total > _MAX_TREE_BYTES:
            raise ReproductionContractError("reproduction tree exceeds 8 GiB")
        yield relative.as_posix(), path


def tree_manifest(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for relative, path in _iter_files(root):
        payload = path.read_bytes()
        entries.append(
            {
                "relative_path": relative,
                "digest": bytes_digest(payload),
                "size_bytes": len(payload),
                "executable": bool(path.stat().st_mode & 0o111),
            }
        )
    return entries


def _copy_manifest(source: Path, destination: Path, entries: list[dict]) -> None:
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    for entry in entries:
        relative = safe_relative_path(entry["relative_path"])
        source_file = source / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(source_file, target, follow_symlinks=False)
        target.chmod(0o555 if entry["executable"] else 0o444)
    for directory in sorted(
        (path for path in destination.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        directory.chmod(0o555)
    destination.chmod(0o555)


def _make_writable_copy(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, symlinks=False)
    destination.chmod(0o700)
    for path in destination.rglob("*"):
        if path.is_symlink():
            raise ReproductionContractError(
                "attempt copy unexpectedly contains a symlink"
            )
        if path.is_dir():
            path.chmod(0o700)
        elif path.is_file():
            executable = bool(path.stat().st_mode & 0o111)
            path.chmod(0o700 if executable else 0o600)


def resolve_image(sandbox: str, reference: str) -> SandboxImageV1 | None:
    if sandbox not in {"docker", "apptainer", "singularity"}:
        if reference:
            raise ReproductionContractError(
                "container_image is only valid for a container sandbox"
            )
        return None
    if not reference:
        raise ReproductionContractError(
            f"sandbox_kind={sandbox} requires an immutable container image"
        )
    if sandbox == "docker":
        marker = "@sha256:"
        if reference.startswith("sha256:"):
            digest = reference.removeprefix("sha256:")
        elif marker in reference:
            digest = reference.rsplit(marker, 1)[1]
        else:
            raise ReproductionContractError(
                "Docker reproduction image must be a full sha256:<image-id> "
                "or be pinned with @sha256:<digest>"
            )
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ReproductionContractError("Docker image digest is invalid")
        return SandboxImageV1(
            runtime="docker", reference=reference, digest="sha256:" + digest
        )

    path = Path(reference).expanduser()
    if path.is_file() and not path.is_symlink():
        digest = bytes_digest(path.read_bytes())
        return SandboxImageV1(
            runtime=sandbox, reference=str(path.resolve()), digest=digest
        )
    marker = "@sha256:"
    if marker not in reference:
        raise ReproductionContractError(
            "remote Apptainer image must be pinned with @sha256:<digest>; "
            "prefer a local immutable SIF"
        )
    digest = reference.rsplit(marker, 1)[1]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ReproductionContractError("Apptainer image digest is invalid")
    return SandboxImageV1(
        runtime=sandbox, reference=reference, digest="sha256:" + digest
    )


@dataclass(frozen=True)
class PreparedReproduction:
    source: Path
    base: Path
    input_dir: Path
    plan_path: Path
    run_path: Path
    plan: ReproductionPlanV1


@dataclass(frozen=True)
class AttemptWorkspace:
    ordinal: int
    attempt_id: str
    parent_attempt_id: str | None
    root: Path
    work_dir: Path
    started_at: str


def prepare_reproduction(
    *,
    source_workspace: str,
    rubric_schema_version: str,
    rubric_sha256: str,
    sandbox_kind: str,
    container_image: str,
    timeout_seconds: int,
    expected_artifacts: list[str],
    network_policy: str,
    network_isolation_attested: bool,
    resources: dict[str, Any],
) -> PreparedReproduction:
    source_input = Path(source_workspace).expanduser()
    if source_input.is_symlink():
        raise ReproductionContractError("source workspace must be a real directory")
    source = source_input.resolve(strict=True)
    if not source.is_dir():
        raise ReproductionContractError("source workspace must be a real directory")
    script = source / "reproduce.sh"
    if not script.is_file() or script.is_symlink():
        raise ReproductionContractError("reproduce.sh missing or unsafe")
    entries = tree_manifest(source)
    input_digest = canonical_digest(entries)
    script_digest = bytes_digest(script.read_bytes())
    sandbox_kind = sandbox_kind.lower()
    image = resolve_image(sandbox_kind, container_image)
    if network_policy not in {"deny", "inherit"}:
        raise ReproductionContractError("network_policy must be deny or inherit")
    if network_policy == "inherit":
        enforcement = "unverified"
    elif sandbox_kind in {"docker", "apptainer", "singularity"}:
        enforcement = "container-namespace"
    elif network_isolation_attested:
        enforcement = "administrator-attested"
    else:
        raise ReproductionContractError(
            f"sandbox_kind={sandbox_kind} cannot prove network denial; choose a "
            "container, set network_policy=inherit explicitly, or supply the "
            "administrator isolation attestation"
        )
    policy = ReproductionPolicyV1(
        network=network_policy,
        network_enforcement=enforcement,
    )
    plan = ReproductionPlanV1.create(
        rubric_schema_version=rubric_schema_version,
        rubric_digest="sha256:" + rubric_sha256,
        source_workspace=str(source),
        input_tree_digest=input_digest,
        script_digest=script_digest,
        argv=("/bin/bash", "reproduce.sh"),
        sandbox=sandbox_kind,
        image=image,
        timeout_seconds=int(timeout_seconds),
        expected_artifacts=tuple(sorted(set(expected_artifacts))),
        policy=policy,
        resources=resources,
    )
    base = source / _INTERNAL_DIR / plan.plan_digest.removeprefix("sha256:")
    input_dir = base / "input"
    if input_dir.exists():
        if canonical_digest(tree_manifest(input_dir)) != input_digest:
            raise ReproductionContractError("stored read-only input snapshot differs")
    else:
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        _copy_manifest(source, input_dir, entries)
    plan_path = base / "plan.json"
    if plan_path.exists():
        existing = ReproductionPlanV1.model_validate_json(plan_path.read_text())
        if existing != plan:
            raise ReproductionContractError("plan digest collision")
    else:
        _atomic_json(plan_path, plan.model_dump(mode="json"))
    input_manifest_path = base / "input-manifest.json"
    if not input_manifest_path.exists():
        _atomic_json(
            input_manifest_path,
            {"tree_digest": input_digest, "files": entries},
        )
    return PreparedReproduction(
        source=source,
        base=base,
        input_dir=input_dir,
        plan_path=plan_path,
        run_path=base / "run.json",
        plan=plan,
    )


def load_run(prepared: PreparedReproduction) -> ReproductionRunV1 | None:
    if not prepared.run_path.is_file():
        return None
    run = ReproductionRunV1.model_validate_json(prepared.run_path.read_text())
    if run.plan != prepared.plan:
        raise ReproductionContractError("stored run belongs to another plan")
    return run


def begin_attempt(
    prepared: PreparedReproduction,
    previous: ReproductionRunV1 | None,
) -> AttemptWorkspace:
    ordinal = len(previous.attempts) + 1 if previous else 1
    parent = previous.attempts[-1].attempt_id if previous else None
    attempt_id = hashlib.sha256(
        f"{prepared.plan.plan_digest}:{ordinal}".encode()
    ).hexdigest()[:32]
    root = prepared.base / "attempts" / f"{ordinal:04d}-{attempt_id}"
    work = root / "work"
    if root.exists():
        raise ReproductionContractError("attempt workspace already exists")
    root.mkdir(parents=True, mode=0o700)
    _make_writable_copy(prepared.input_dir, work)
    return AttemptWorkspace(
        ordinal=ordinal,
        attempt_id=attempt_id,
        parent_attempt_id=parent,
        root=root,
        work_dir=work,
        started_at=now_utc(),
    )


def execution_request(
    prepared: PreparedReproduction,
    attempt: AttemptWorkspace,
) -> ExecutionRequestV1:
    workspace = WorkspaceRefV1(root=str(attempt.work_dir))
    image = prepared.plan.image
    container = None
    if image is not None:
        container = ContainerIdentityV1(
            runtime=image.runtime,
            reference=image.reference,
            digest=image.digest,
            resolution_status="resolved",
        )
    return ExecutionRequestV1(
        workspace=workspace,
        argv=list(prepared.plan.argv),
        timeout_seconds=prepared.plan.timeout_seconds,
        environment={},
        limits=ExecutionLimitsV1(
            max_processes=4096,
            max_output_bytes=256 * 1024 * 1024,
        ),
        network=prepared.plan.policy.network,
        request_id=f"paper-re-{attempt.attempt_id}",
        input_digests={"reproduce.sh": prepared.plan.script_digest},
        container=container,
    )


async def execute_local_attempt(
    prepared: PreparedReproduction,
    attempt: AttemptWorkspace,
) -> dict[str, Any]:
    request = execution_request(prepared, attempt)
    cancel_event = threading.Event()
    task = asyncio.create_task(
        asyncio.to_thread(
            execute_local,
            request,
            cancel_event=cancel_event,
            network_isolation_verified=(
                prepared.plan.policy.network_enforcement == "administrator-attested"
            ),
        )
    )
    try:
        result = await task
    except asyncio.CancelledError:
        cancel_event.set()
        try:
            result = await asyncio.shield(task)
        except Exception:
            raise
    stdout = request.workspace.read_bytes(
        result.artifacts[0].relative_path,
        max_bytes=request.limits.max_output_bytes,
    )
    stderr = request.workspace.read_bytes(
        result.artifacts[1].relative_path,
        max_bytes=request.limits.max_output_bytes,
    )
    return {
        "status": (
            "succeeded"
            if result.status == "completed"
            else "failed"
            if result.status == "failed"
            else result.status
        ),
        "exit_code": result.exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "execution_identity": result.execution_identity,
        "substrate_request_digest": None,
        "environment": {
            "launched": True,
            "substrate": "local",
            "identity": host_environment_identity(),
            "environment_names": result.environment_names,
            "network": result.network_report,
            "limits": result.limit_report.model_dump(mode="json"),
            "input_bindings": result.input_bindings,
        },
    }


async def _terminate_async_process_group(
    process: asyncio.subprocess.Process,
) -> None:
    """Terminate a launcher and every descendant in its process group."""

    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await asyncio.wait_for(process.wait(), timeout=5)


async def _remove_docker_container(name: str | None) -> None:
    """Best-effort removal for a named container after interrupted launch."""

    docker = shutil.which("docker")
    if not name or docker is None:
        return
    try:
        cleanup = await asyncio.create_subprocess_exec(
            docker,
            "rm",
            "-f",
            name,
            env=build_minimal_environment(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        await asyncio.wait_for(cleanup.wait(), timeout=15)
    except (OSError, asyncio.TimeoutError):
        log.warning("could not confirm removal of Docker container %s", name)


def _external_command(
    prepared: PreparedReproduction,
    attempt: AttemptWorkspace,
) -> tuple[list[str], str | None]:
    image = prepared.plan.image
    if image is None:
        raise ReproductionContractError("container attempt has no image")
    if prepared.plan.sandbox == "docker":
        name = f"ari-paper-re-{attempt.attempt_id}"
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=1g",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=4096",
            "--mount",
            f"type=bind,src={attempt.work_dir},dst=/work,rw",
            "--workdir=/work",
        ]
        if prepared.plan.policy.network == "deny":
            command += ["--network=none"]
        command += [
            image.reference,
            "/bin/bash",
            "--noprofile",
            "--norc",
            "-c",
            _RUNTIME_IDENTITY_COMMAND,
        ]
        return command, name
    runner = prepared.plan.sandbox
    command = [
        runner,
        "exec",
        "--cleanenv",
        "--containall",
        "--no-home",
        "--bind",
        f"{attempt.work_dir}:/work",
        "--pwd",
        "/work",
    ]
    if prepared.plan.policy.network == "deny":
        command += ["--net", "--network", "none"]
    command += [
        image.reference,
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
        _RUNTIME_IDENTITY_COMMAND,
    ]
    return command, None


async def execute_container_attempt(
    prepared: PreparedReproduction,
    attempt: AttemptWorkspace,
) -> dict[str, Any]:
    request = execution_request(prepared, attempt)
    command, docker_name = _external_command(prepared, attempt)
    if shutil.which(command[0]) is None:
        raise ReproductionContractError(f"sandbox runtime is unavailable: {command[0]}")

    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=attempt.work_dir,
        env=build_minimal_environment(),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        close_fds=True,
        start_new_session=True,
    )
    communication = asyncio.create_task(process.communicate())
    terminal = "exited"
    try:
        stdout, stderr = await asyncio.wait_for(
            asyncio.shield(communication),
            timeout=prepared.plan.timeout_seconds,
        )
    except asyncio.TimeoutError:
        terminal = "timed_out"
        await _terminate_async_process_group(process)
        await _remove_docker_container(docker_name)
        stdout, stderr = await communication
    except asyncio.CancelledError:
        terminal = "cancelled"
        await asyncio.shield(_terminate_async_process_group(process))
        await asyncio.shield(_remove_docker_container(docker_name))
        stdout, stderr = await asyncio.shield(communication)
    stdout = stdout or b""
    stderr = stderr or b""
    returncode = process.returncode if terminal == "exited" else None
    runtime_identity_path = attempt.work_dir / ".ari-runtime-identity.txt"
    runtime_identity = (
        runtime_identity_path.read_text(errors="replace")[:65_536]
        if runtime_identity_path.is_file() and not runtime_identity_path.is_symlink()
        else ""
    )
    if terminal == "exited":
        normalized = record_completed_execution(
            request,
            stdout=stdout,
            stderr=stderr,
            returncode=int(returncode or 0),
            inputs_verified=True,
            network_verified=prepared.plan.policy.network == "deny",
        )
        execution_identity = normalized.execution_identity
    else:
        execution_identity = request.execution_identity
    return {
        "status": (
            "timed_out"
            if terminal == "timed_out"
            else "cancelled"
            if terminal == "cancelled"
            else "succeeded"
            if returncode == 0
            else "failed"
        ),
        "exit_code": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "execution_identity": execution_identity,
        "substrate_request_digest": None,
        "environment": {
            "launched": True,
            "substrate": prepared.plan.sandbox,
            "submission_host": host_environment_identity(),
            "runtime_identity": runtime_identity,
            "runtime_identity_digest": bytes_digest(runtime_identity.encode("utf-8")),
            "runtime_path": shutil.which(command[0]),
            "image": prepared.plan.image.model_dump(mode="json"),
            "environment_names": sorted(build_minimal_environment()),
            "network": prepared.plan.policy.network_enforcement,
        },
    }


def classify_failure(
    status: str, exit_code: int | None, log_text: str
) -> FailureEvidenceV1:
    lowered = log_text.casefold()
    if status == "timed_out":
        return FailureEvidenceV1(kind="timeout", message="reproduction timed out")
    if status == "cancelled":
        return FailureEvidenceV1(kind="cancelled", message="reproduction was cancelled")
    if "out of memory" in lowered or "oom" in lowered or exit_code in {137, -9}:
        kind = "oom"
    elif "command not found" in lowered or "no module named" in lowered:
        kind = "missing-dependency"
    elif "cuda" in lowered and (
        "not available" in lowered or "no device" in lowered or "driver" in lowered
    ):
        kind = "gpu-mismatch"
    elif "permission denied" in lowered or "read-only file system" in lowered:
        kind = "filesystem-policy"
    else:
        kind = "process-exit"
    return FailureEvidenceV1(
        kind=kind,
        message=(
            f"reproduction exited with code {exit_code}"
            if exit_code is not None
            else "reproduction failed"
        ),
    )


def _sanitize_output_tree(root: Path, *, preserve: set[str]) -> list[str]:
    """Remove unsafe private outputs and return an auditable incident list."""

    incidents: list[str] = []
    total = 0
    paths = sorted(root.rglob("*"), key=lambda item: item.as_posix())
    # Account for evidence files first so a full output tree cannot evict them.
    paths.sort(key=lambda item: item.relative_to(root).as_posix() not in preserve)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            path.unlink()
            incidents.append(f"removed symlink output: {relative}")
            continue
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            path.unlink()
            incidents.append(f"removed non-regular output: {relative}")
            continue
        size = path.stat().st_size
        if size > _MAX_TREE_FILE_BYTES or total + size > _MAX_TREE_BYTES:
            if relative in preserve:
                raise ReproductionContractError(
                    f"required evidence file exceeds output limits: {relative}"
                )
            path.unlink()
            incidents.append(f"removed over-limit output: {relative}")
            continue
        total += size
    return incidents


def finalize_attempt(
    prepared: PreparedReproduction,
    attempt: AttemptWorkspace,
    execution: dict[str, Any],
    previous: ReproductionRunV1 | None,
) -> tuple[ReproductionRunV1, Path]:
    stdout = bytes(execution.get("stdout") or b"")
    stderr = bytes(execution.get("stderr") or b"")
    log_path = attempt.work_dir / "reproduce.log"
    workspace = WorkspaceRefV1(root=str(attempt.work_dir))
    policy_incidents: list[str] = []
    if log_path.is_symlink() or (log_path.exists() and not log_path.is_file()):
        policy_incidents.append("removed unsafe reproduce.log output")
        if log_path.is_dir() and not log_path.is_symlink():
            shutil.rmtree(log_path)
        else:
            log_path.unlink()
    workspace.atomic_write_bytes(
        "reproduce.log",
        stdout + (b"\n" if stdout and stderr else b"") + stderr,
    )
    policy_incidents.extend(
        _sanitize_output_tree(attempt.work_dir, preserve={"reproduce.log"})
    )
    manifest_before = {
        item["relative_path"]: item for item in tree_manifest(prepared.input_dir)
    }
    manifest_after_list = tree_manifest(attempt.work_dir)
    manifest_after = {item["relative_path"]: item for item in manifest_after_list}
    changes: list[dict[str, Any]] = []
    for path in sorted(set(manifest_before) | set(manifest_after)):
        before = manifest_before.get(path)
        after = manifest_after.get(path)
        if before == after:
            continue
        changes.append(
            {
                "relative_path": path,
                "change": "added"
                if before is None
                else "deleted"
                if after is None
                else "modified",
                "before_digest": before.get("digest") if before else None,
                "after_digest": after.get("digest") if after else None,
                "size_bytes": after.get("size_bytes") if after else 0,
            }
        )
    output_tree_digest = canonical_digest(manifest_after_list)
    output_manifest_path = attempt.root / "output-manifest.json"
    _atomic_json(
        output_manifest_path,
        {
            "schema_version": "ari.reproduction-output-manifest/v1",
            "input_tree_digest": prepared.plan.input_tree_digest,
            "output_tree_digest": output_tree_digest,
            "files": manifest_after_list,
            "changes": changes,
            "policy_incidents": policy_incidents,
        },
    )
    missing = tuple(
        path
        for path in prepared.plan.expected_artifacts
        if not (attempt.work_dir / path).is_file()
    )
    status = str(execution.get("status") or "failed")
    exit_code = execution.get("exit_code")
    failure = None
    if policy_incidents:
        status = "failed"
        failure = FailureEvidenceV1(
            kind="filesystem-policy",
            message="; ".join(policy_incidents)[:4096],
        )
    elif status == "succeeded" and missing:
        status = "failed"
        failure = FailureEvidenceV1(
            kind="filesystem-policy",
            message="expected artifacts are missing: " + ", ".join(missing),
        )
    elif status != "succeeded":
        explicit = execution.get("failure")
        failure = (
            explicit
            if isinstance(explicit, FailureEvidenceV1)
            else classify_failure(
                status, exit_code, log_path.read_text(errors="replace")
            )
        )
    attempt_record = ReproductionAttemptV1.create(
        attempt_id=attempt.attempt_id,
        ordinal=attempt.ordinal,
        parent_attempt_id=attempt.parent_attempt_id,
        plan_digest=prepared.plan.plan_digest,
        status=status,
        started_at=attempt.started_at,
        completed_at=now_utc(),
        exit_code=exit_code,
        execution_identity=execution.get("execution_identity"),
        substrate_request_digest=execution.get("substrate_request_digest"),
        environment=dict(execution.get("environment") or {}),
        log_artifact=artifact_from_path(
            log_path,
            base=prepared.source,
            role="reproduce-log",
            media_type="text/plain; charset=utf-8",
        ),
        output_manifest=artifact_from_path(
            output_manifest_path,
            base=prepared.source,
            role="reproduction-output-manifest",
        ),
        output_tree_digest=output_tree_digest,
        expected_missing=missing,
        failure=failure,
    )
    attempts = (
        tuple(previous.attempts) + (attempt_record,) if previous else (attempt_record,)
    )
    run = ReproductionRunV1.create(
        plan=prepared.plan,
        attempts=attempts,
        status=status,
        selected_attempt_id=attempt.attempt_id if status == "succeeded" else None,
    )
    _atomic_json(prepared.run_path, run.model_dump(mode="json"))
    pointer = publish_latest_pointer(
        prepared,
        run,
        attempt_id=attempt.attempt_id,
        work_dir=attempt.work_dir,
    )
    return run, pointer


def _verified_attempt_workspace(
    source: Path,
    run: ReproductionRunV1,
    attempt_id: str,
) -> Path:
    attempt = next(
        (item for item in run.attempts if item.attempt_id == attempt_id),
        None,
    )
    if attempt is None:
        raise ReproductionContractError("reproduction attempt is absent")
    paths: list[Path] = []
    for artifact in (attempt.log_artifact, attempt.output_manifest):
        path = (source / artifact.relative_path).resolve(strict=True)
        try:
            path.relative_to(source)
        except ValueError as exc:
            raise ReproductionContractError(
                "run artifact escapes workspace"
            ) from exc
        payload = path.read_bytes()
        if (
            bytes_digest(payload) != artifact.digest
            or len(payload) != artifact.size_bytes
        ):
            raise ReproductionContractError("run artifact differs from its digest")
        paths.append(path)
    log_path, manifest_path = paths
    work = log_path.parent
    if (
        log_path.name != "reproduce.log"
        or manifest_path.name != "output-manifest.json"
        or manifest_path.parent != work.parent
        or not work.is_dir()
        or work.is_symlink()
    ):
        raise ReproductionContractError("attempt artifact layout is inconsistent")
    if canonical_digest(tree_manifest(work)) != attempt.output_tree_digest:
        raise ReproductionContractError("executed workspace differs from its digest")
    return work


def publish_latest_pointer(
    prepared: PreparedReproduction,
    run: ReproductionRunV1,
    *,
    attempt_id: str,
    work_dir: Path | None = None,
) -> Path:
    """Publish one verified run as the source workspace's active result."""

    verified_work = _verified_attempt_workspace(
        prepared.source, run, attempt_id
    )
    if work_dir is not None and verified_work != work_dir.resolve(strict=True):
        raise ReproductionContractError("attempt workspace differs from its record")
    pointer = prepared.source / _INTERNAL_DIR / "latest.json"
    _atomic_json(
        pointer,
        {
            "schema_version": "ari.reproduction-pointer/v1",
            "run_relative_path": prepared.run_path.relative_to(
                prepared.source
            ).as_posix(),
            "executed_workspace": verified_work.relative_to(
                prepared.source
            ).as_posix(),
            "run_digest": run.run_digest,
            "attempt_id": attempt_id,
            "status": next(
                item.status for item in run.attempts if item.attempt_id == attempt_id
            ),
        },
    )
    return pointer


def resolve_latest_run(source_workspace: Path) -> tuple[ReproductionRunV1, Path] | None:
    source = source_workspace.resolve(strict=True)
    pointer_path = source / _INTERNAL_DIR / "latest.json"
    if not pointer_path.is_file() or pointer_path.is_symlink():
        return None
    pointer = json.loads(pointer_path.read_text())
    if pointer.get("schema_version") != "ari.reproduction-pointer/v1":
        raise ReproductionContractError("unknown reproduction pointer version")
    run_path = (source / safe_relative_path(pointer["run_relative_path"])).resolve(
        strict=True
    )
    work = (source / safe_relative_path(pointer["executed_workspace"])).resolve(
        strict=True
    )
    try:
        run_path.relative_to(source)
        work.relative_to(source)
    except ValueError as exc:
        raise ReproductionContractError(
            "reproduction pointer escapes workspace"
        ) from exc
    run = ReproductionRunV1.model_validate_json(run_path.read_text())
    if run.run_digest != pointer.get("run_digest"):
        raise ReproductionContractError("reproduction pointer digest differs")
    attempt_id = pointer.get("attempt_id")
    if not isinstance(attempt_id, str):
        raise ReproductionContractError("reproduction pointer has no attempt")
    verified_work = _verified_attempt_workspace(source, run, attempt_id)
    if verified_work != work:
        raise ReproductionContractError("reproduction pointer workspace differs")
    attempt = next(item for item in run.attempts if item.attempt_id == attempt_id)
    if attempt.status != pointer.get("status"):
        raise ReproductionContractError("reproduction pointer status differs")
    return run, work


__all__ = [
    "AttemptWorkspace",
    "PreparedReproduction",
    "begin_attempt",
    "execute_container_attempt",
    "execute_local_attempt",
    "execution_request",
    "finalize_attempt",
    "load_run",
    "now_utc",
    "prepare_reproduction",
    "publish_latest_pointer",
    "resolve_latest_run",
    "tree_manifest",
]
