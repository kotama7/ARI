"""Safe SLURM scheduler adapter for public ARI HPC job contracts."""

from __future__ import annotations

import asyncio
import concurrent.futures
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence

from ari_skill_hpc.contracts import (
    ArtifactPinV1,
    JobErrorV1,
    JobHandleV1,
    JobLogV1,
    JobRequestV1,
    JobResultV1,
    JobStatusV1,
    ResourceRequestV1,
    file_digest,
    sha256_digest,
    utc_now,
)


_JOB_ID_RE = re.compile(r"^[0-9]+(?:_[0-9]+)?$")
_STATE_SUFFIX_RE = re.compile(r"[+ ].*$")
_TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
_OUTPUT_LIMIT = 1_048_576


class SchedulerError(RuntimeError):
    """Base error for a scheduler boundary failure."""


class SchedulerValidationError(SchedulerError):
    pass


class SchedulerTransportError(SchedulerError):
    """The outcome of a scheduler transport operation may be uncertain."""


class SchedulerProtocolError(SchedulerError):
    pass


class SubmissionUncertainError(SchedulerError):
    pass


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


class CommandRunner(Protocol):
    @property
    def identity(self) -> dict[str, Any]: ...

    async def run(
        self,
        argv: Sequence[str],
        *,
        stdin: bytes | None = None,
        timeout: float | None = None,
    ) -> CommandResult: ...

    def close(self) -> None: ...


@dataclass
class LocalCommandRunner:
    command_timeout: float = 30.0
    scheduler_path: str = "/usr/local/bin:/usr/bin:/bin"

    @property
    def identity(self) -> dict[str, Any]:
        return {"transport": "local", "scheduler_path": self.scheduler_path}

    async def run(
        self,
        argv: Sequence[str],
        *,
        stdin: bytes | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        if not argv or any("\x00" in argument for argument in argv):
            raise SchedulerValidationError("scheduler argv must contain inert atoms")
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    "PATH": self.scheduler_path,
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                },
            )
        except (FileNotFoundError, OSError) as exc:
            raise SchedulerTransportError(
                f"scheduler command unavailable: {argv[0]}"
            ) from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=stdin),
                timeout=timeout or self.command_timeout,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise SchedulerTransportError(
                f"scheduler command timed out: {argv[0]}"
            ) from exc
        return CommandResult(
            stdout=_bounded_decode(stdout),
            stderr=_bounded_decode(stderr),
            returncode=process.returncode or 0,
        )

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class RemoteConfig:
    hostname: str
    username: str
    known_hosts: str
    port: int = 22
    key_filename: str | None = None
    password: str | None = field(default=None, repr=False)
    connect_timeout: float = 15.0
    command_timeout: float = 30.0
    shared_filesystem: bool = True

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", self.hostname):
            raise ValueError("remote hostname is invalid")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}", self.username):
            raise ValueError("remote username is invalid")
        if not 1 <= self.port <= 65535:
            raise ValueError("remote SSH port is invalid")
        known_hosts = Path(self.known_hosts)
        if not known_hosts.is_absolute():
            raise ValueError("SLURM_SSH_KNOWN_HOSTS must be absolute")
        if self.key_filename and not Path(self.key_filename).is_absolute():
            raise ValueError("SLURM_SSH_KEY must be absolute")
        if not self.key_filename and not self.password:
            raise ValueError(
                "remote SSH requires an explicit key or password credential"
            )


@dataclass
class RemoteCommandRunner:
    config: RemoteConfig
    _client: Any = field(default=None, init=False, repr=False)

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "transport": "ssh",
            "hostname": self.config.hostname,
            "port": self.config.port,
            "username": self.config.username,
            "known_hosts_digest": _known_hosts_digest(self.config.known_hosts),
            "shared_filesystem": self.config.shared_filesystem,
        }

    def _connect(self) -> Any:
        if self._client is not None:
            return self._client
        import paramiko

        known_hosts = Path(self.config.known_hosts)
        if not known_hosts.is_file() or known_hosts.is_symlink():
            raise SchedulerTransportError(
                "strict SSH known_hosts file is missing or unsafe"
            )
        kwargs: dict[str, Any] = {
            "hostname": self.config.hostname,
            "port": self.config.port,
            "username": self.config.username,
            "timeout": self.config.connect_timeout,
            "banner_timeout": self.config.connect_timeout,
            "auth_timeout": self.config.connect_timeout,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if self.config.key_filename:
            key_path = Path(self.config.key_filename)
            if not key_path.is_file() or key_path.is_symlink():
                raise SchedulerTransportError(
                    "SSH private key path is missing or unsafe"
                )
            if key_path.stat().st_mode & 0o077:
                raise SchedulerTransportError(
                    "SSH private key permissions must exclude group and other access"
                )
            kwargs["key_filename"] = str(key_path)
        if self.config.password:
            kwargs["password"] = self.config.password
        client = paramiko.SSHClient()
        try:
            client.load_host_keys(str(known_hosts))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(**kwargs)
        except Exception as exc:
            client.close()
            raise SchedulerTransportError(
                f"strict SSH connection failed for {self.config.hostname}"
            ) from exc
        self._client = client
        return client

    async def run(
        self,
        argv: Sequence[str],
        *,
        stdin: bytes | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        if not argv or any("\x00" in argument for argument in argv):
            raise SchedulerValidationError("scheduler argv must contain inert atoms")

        def execute() -> CommandResult:
            client = self._connect()
            command = shlex.join(list(argv))
            try:
                remote_stdin, remote_stdout, remote_stderr = client.exec_command(
                    command,
                    timeout=timeout or self.config.command_timeout,
                    get_pty=False,
                )
                if stdin is not None:
                    remote_stdin.write(stdin)
                    remote_stdin.flush()
                try:
                    remote_stdin.channel.shutdown_write()
                except Exception:
                    remote_stdin.close()
                # Drain both channels before waiting for the exit status;
                # waiting first can deadlock when a Paramiko window fills.
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    stdout_future = pool.submit(remote_stdout.read, _OUTPUT_LIMIT + 1)
                    stderr_future = pool.submit(remote_stderr.read, _OUTPUT_LIMIT + 1)
                    read_timeout = timeout or self.config.command_timeout
                    stdout = stdout_future.result(timeout=read_timeout)
                    stderr = stderr_future.result(timeout=read_timeout)
                exit_status = remote_stdout.channel.recv_exit_status()
            except Exception as exc:
                self.close()
                raise SchedulerTransportError(
                    f"remote scheduler command failed: {argv[0]}"
                ) from exc
            return CommandResult(
                stdout=_bounded_decode(stdout),
                stderr=_bounded_decode(stderr),
                returncode=exit_status,
            )

        return await asyncio.to_thread(execute)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def _bounded_decode(value: bytes | str) -> str:
    if isinstance(value, str):
        raw = value.encode("utf-8", errors="replace")
    else:
        raw = value
    if len(raw) > _OUTPUT_LIMIT:
        raw = raw[:_OUTPUT_LIMIT]
    return raw.decode("utf-8", errors="replace").strip()


def _known_hosts_digest(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        return sha256_digest({"known_hosts": "unavailable"})
    return "sha256:" + __import__("hashlib").sha256(candidate.read_bytes()).hexdigest()


class SubmissionLedger:
    """Atomic durable idempotency ledger with a fail-closed unknown claim state."""

    def __init__(self, path: Path):
        if not path.is_absolute():
            raise ValueError("HPC ledger path must be absolute")
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    def _prepare(self) -> None:
        if self.path.parent.exists() and self.path.parent.is_symlink():
            raise SchedulerProtocolError("HPC ledger directory must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": "ari.hpc.submission-ledger/v1", "records": {}}
        if self.path.is_symlink():
            raise SchedulerProtocolError("HPC ledger must not be a symlink")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SchedulerProtocolError("HPC ledger is unreadable") from exc
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != "ari.hpc.submission-ledger/v1"
            or not isinstance(value.get("records"), dict)
        ):
            raise SchedulerProtocolError("HPC ledger contract is invalid")
        return value

    def _write_unlocked(self, value: dict[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _locked(self):
        self._prepare()
        descriptor = os.open(
            self.lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        lock = os.fdopen(descriptor, "a+", encoding="utf-8")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return lock

    def claim(self, digest: str, request: dict[str, Any]) -> dict[str, Any] | None:
        with self._locked() as lock:
            value = self._load_unlocked()
            record = value["records"].get(digest)
            if record is not None:
                if record.get("state") == "submitted" and isinstance(
                    record.get("handle"), dict
                ):
                    return record
                raise SubmissionUncertainError(
                    "an earlier identical submission has an unknown outcome; refusing to duplicate it"
                )
            value["records"][digest] = {
                "state": "claim",
                "claimed_at": utc_now(),
                "request": request,
            }
            self._write_unlocked(value)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return None

    def complete(
        self,
        digest: str,
        *,
        handle: JobHandleV1,
        request: dict[str, Any],
        script_digest: str,
        terminal_evidence_policy: str = "scheduler-accounting",
        completion_nonce_sha256: str | None = None,
    ) -> None:
        with self._locked() as lock:
            value = self._load_unlocked()
            record = value["records"].get(digest)
            if not isinstance(record, dict) or record.get("state") != "claim":
                raise SchedulerProtocolError(
                    "submission claim disappeared before commit"
                )
            committed = {
                "state": "submitted",
                "claimed_at": record["claimed_at"],
                "committed_at": utc_now(),
                "handle": handle.model_dump(mode="json"),
                "request": request,
                "script_digest": script_digest,
            }
            if terminal_evidence_policy != "scheduler-accounting":
                committed.update(
                    {
                        "terminal_evidence_policy": terminal_evidence_policy,
                        "completion_nonce_sha256": completion_nonce_sha256,
                    }
                )
            value["records"][digest] = committed
            self._write_unlocked(value)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def release(self, digest: str) -> None:
        with self._locked() as lock:
            value = self._load_unlocked()
            record = value["records"].get(digest)
            if isinstance(record, dict) and record.get("state") == "claim":
                value["records"].pop(digest, None)
                self._write_unlocked(value)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def find(self, handle_or_job_id: str) -> dict[str, Any] | None:
        with self._locked() as lock:
            value = self._load_unlocked()
            for record in value["records"].values():
                handle = record.get("handle") if isinstance(record, dict) else None
                if isinstance(handle, dict) and handle_or_job_id in {
                    handle.get("handle_id"),
                    handle.get("job_id"),
                }:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                    return record
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return None


def default_ledger_path() -> Path:
    explicit = os.environ.get("ARI_HPC_LEDGER_PATH", "").strip()
    if explicit:
        return Path(explicit)
    checkpoint = os.environ.get("ARI_CHECKPOINT_DIR", "").strip()
    if checkpoint:
        return Path(checkpoint) / "hpc-jobs-v1.json"
    work_dir = os.environ.get("ARI_WORK_DIR", "").strip()
    if work_dir:
        return Path(work_dir) / ".ari" / "hpc-jobs-v1.json"
    return (
        Path(tempfile.gettempdir())
        / f"ari-hpc-state-{os.getuid()}"
        / "hpc-jobs-v1.json"
    )


@dataclass
class SlurmScheduler:
    runner: CommandRunner
    ledger: SubmissionLedger = field(
        default_factory=lambda: SubmissionLedger(default_ledger_path())
    )
    shared_filesystem: bool = True
    terminal_evidence_policy: Literal[
        "scheduler-accounting", "fixed-wrapper-marker"
    ] = "scheduler-accounting"

    def __post_init__(self) -> None:
        if (
            self.terminal_evidence_policy == "fixed-wrapper-marker"
            and not self.shared_filesystem
        ):
            raise ValueError(
                "fixed-wrapper terminal evidence requires a shared filesystem"
            )

    @property
    def cluster_identity(self) -> str:
        if self.terminal_evidence_policy == "scheduler-accounting":
            return sha256_digest(self.runner.identity)
        return sha256_digest(
            {
                "runner": self.runner.identity,
                "terminal_evidence_policy": self.terminal_evidence_policy,
            }
        )

    async def submit(self, request: JobRequestV1) -> JobHandleV1:
        self._verify_request_artifacts(request)
        request_payload = request.model_dump(mode="json")
        request_digest = request.request_digest
        prior = self.ledger.claim(request_digest, request_payload)
        if prior is not None:
            return JobHandleV1.model_validate(prior["handle"])

        try:
            artifact_scope = self._ensure_artifact_scope(
                request.work_dir, request_digest
            )
            completion_nonce = (
                secrets.token_hex(32)
                if self.terminal_evidence_policy == "fixed-wrapper-marker"
                else None
            )
            script = self._render_script(
                request,
                artifact_scope,
                completion_nonce=completion_nonce,
            )
        except Exception:
            self.ledger.release(request_digest)
            raise
        script_digest = (
            "sha256:" + __import__("hashlib").sha256(script.encode("utf-8")).hexdigest()
        )
        submission_digest = sha256_digest(
            {
                "argv": ["sbatch", "--parsable", "--export=NIL"],
                "script_digest": script_digest,
                "cluster_identity": self.cluster_identity,
            }
        )
        self._write_submission_record(
            artifact_scope,
            request=request_payload,
            script_digest=script_digest,
            submission_digest=submission_digest,
            terminal_evidence_policy=self.terminal_evidence_policy,
            completion_nonce_sha256=(
                hashlib.sha256(completion_nonce.encode("ascii")).hexdigest()
                if completion_nonce is not None
                else None
            ),
        )
        try:
            response = await self.runner.run(
                ["sbatch", "--parsable", "--export=NIL"],
                stdin=script.encode("utf-8"),
            )
        except Exception:
            # The transport may have delivered stdin before failing. The durable
            # claim intentionally remains, so a retry cannot duplicate the job.
            raise
        if response.returncode != 0:
            self.ledger.release(request_digest)
            raise SchedulerProtocolError(
                _safe_error(
                    "sbatch rejected the request", response.stderr or response.stdout
                )
            )
        job_id = _parse_job_id(response.stdout)
        handle = JobHandleV1(
            handle_id=_handle_id(self.cluster_identity, request_digest, job_id),
            request_id=request.request_id,
            request_digest=request_digest,
            cluster_identity=self.cluster_identity,
            job_id=job_id,
            submission_digest=submission_digest,
            workspace_scope=request.work_dir,
            artifact_scope=str(artifact_scope),
            submitted_at=utc_now(),
        )
        self.ledger.complete(
            request_digest,
            handle=handle,
            request=request_payload,
            script_digest=script_digest,
            terminal_evidence_policy=self.terminal_evidence_policy,
            completion_nonce_sha256=(
                hashlib.sha256(completion_nonce.encode("ascii")).hexdigest()
                if completion_nonce is not None
                else None
            ),
        )
        return handle

    async def submit_script_bridge(
        self,
        *,
        script: str,
        job_name: str,
        partition: str,
        nodes: int = 1,
        walltime: str = "01:00:00",
        work_dir: str,
        cpus_per_task: int = 1,
        memory_gb: int | None = None,
        gres: str | None = None,
        account: str | None = None,
    ) -> JobHandleV1:
        """Compile the retained core-agent script bridge into a durable claim."""
        if len(script.encode("utf-8")) > 4 * 1024 * 1024 or "\x00" in script:
            raise SchedulerValidationError(
                "batch script bridge input is invalid or too large"
            )
        gpus = 0
        gpu_type = None
        if gres:
            match = re.fullmatch(r"gpu(?::([A-Za-z0-9_.+-]+))?:(\d+)", gres)
            if not match:
                raise SchedulerValidationError("gres must use gpu[:type]:count")
            gpu_type = match.group(1)
            gpus = int(match.group(2))
        resources = ResourceRequestV1(
            partition=partition,
            nodes=nodes,
            cpus_per_task=cpus_per_task,
            memory_mb_per_node=memory_gb * 1024 if memory_gb else None,
            gpus_per_node=gpus,
            gpu_type=gpu_type,
            walltime=walltime,
            account=account,
        )
        work = _validated_work_dir(work_dir)
        payload = {
            "schema_version": "ari.hpc.script-bridge/v1",
            "script_digest": "sha256:"
            + __import__("hashlib").sha256(script.encode("utf-8")).hexdigest(),
            "job_name": job_name,
            "work_dir": str(work),
            "resources": resources.model_dump(mode="json"),
        }
        request_digest = sha256_digest(payload)
        prior = self.ledger.claim(request_digest, payload)
        if prior is not None:
            return JobHandleV1.model_validate(prior["handle"])
        try:
            artifact_scope = self._ensure_artifact_scope(str(work), request_digest)
            rendered = self._render_script_bridge(
                script=script,
                job_name=job_name,
                resources=resources,
                work_dir=str(work),
                artifact_scope=artifact_scope,
            )
        except Exception:
            self.ledger.release(request_digest)
            raise
        script_digest = (
            "sha256:"
            + __import__("hashlib").sha256(rendered.encode("utf-8")).hexdigest()
        )
        submission_digest = sha256_digest(
            {
                "argv": ["sbatch", "--parsable", "--export=NIL"],
                "script_digest": script_digest,
                "cluster_identity": self.cluster_identity,
            }
        )
        self._write_submission_record(
            artifact_scope,
            request=payload,
            script_digest=script_digest,
            submission_digest=submission_digest,
        )
        try:
            response = await self.runner.run(
                ["sbatch", "--parsable", "--export=NIL"],
                stdin=rendered.encode("utf-8"),
            )
        except Exception:
            raise
        if response.returncode != 0:
            self.ledger.release(request_digest)
            raise SchedulerProtocolError(
                _safe_error(
                    "sbatch rejected the request", response.stderr or response.stdout
                )
            )
        job_id = _parse_job_id(response.stdout)
        handle = JobHandleV1(
            handle_id=_handle_id(self.cluster_identity, request_digest, job_id),
            request_id="script-" + request_digest.removeprefix("sha256:")[:24],
            request_digest=request_digest,
            cluster_identity=self.cluster_identity,
            job_id=job_id,
            submission_digest=submission_digest,
            workspace_scope=str(work),
            artifact_scope=str(artifact_scope),
            submitted_at=utc_now(),
        )
        self.ledger.complete(
            request_digest,
            handle=handle,
            request=payload,
            script_digest=script_digest,
        )
        return handle

    async def status(self, handle_or_job_id: str) -> JobStatusV1:
        record, handle, job_id = self._resolve(handle_or_job_id)
        response = await self.runner.run(
            [
                "sacct",
                "-j",
                job_id,
                "--noheader",
                "--parsable2",
                "--allocations",
                "--format=JobID,State,ExitCode,Start,End,Reason",
            ]
        )
        if response.returncode == 0 and response.stdout:
            parsed = _parse_sacct(response.stdout, job_id)
            if parsed is not None:
                return JobStatusV1(
                    handle_id=handle.handle_id if handle else None,
                    job_id=job_id,
                    **parsed,
                )
        queue = await self.runner.run(
            ["squeue", "-j", job_id, "--noheader", "--format=%T|%R"]
        )
        if queue.returncode == 0 and queue.stdout:
            raw_state, _, reason = queue.stdout.splitlines()[0].partition("|")
            return JobStatusV1(
                handle_id=handle.handle_id if handle else None,
                job_id=job_id,
                state=_normalize_state(raw_state),
                scheduler_state=_base_state(raw_state),
                reason=reason[:2000] or None,
            )
        marker_status = self._fixed_wrapper_marker_status(record, handle, job_id)
        if marker_status is not None:
            return marker_status
        return JobStatusV1(
            handle_id=handle.handle_id if handle else None,
            job_id=job_id,
            state="unknown",
            scheduler_state="UNKNOWN",
            reason=_safe_error(
                "scheduler returned no job record", response.stderr or queue.stderr
            ),
        )

    def _fixed_wrapper_marker_status(
        self,
        record: dict[str, Any] | None,
        handle: JobHandleV1 | None,
        job_id: str,
    ) -> JobStatusV1 | None:
        if (
            self.terminal_evidence_policy != "fixed-wrapper-marker"
            or record is None
            or handle is None
            or record.get("terminal_evidence_policy") != "fixed-wrapper-marker"
            or not self.shared_filesystem
        ):
            return None
        path = Path(handle.artifact_scope) / "wrapper-completion-v1.json"
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            return None
        try:
            marker = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        expected_keys = {
            "schema_version",
            "request_digest",
            "cluster_identity",
            "job_id",
            "exit_code",
            "completion_nonce",
        }
        nonce = marker.get("completion_nonce") if isinstance(marker, dict) else None
        exit_code = marker.get("exit_code") if isinstance(marker, dict) else None
        if (
            not isinstance(marker, dict)
            or set(marker) != expected_keys
            or marker.get("schema_version") != "ari.hpc.wrapper-completion/v1"
            or marker.get("request_digest") != handle.request_digest
            or marker.get("cluster_identity") != handle.cluster_identity
            or marker.get("job_id") != job_id
            or not isinstance(exit_code, int)
            or isinstance(exit_code, bool)
            or not 0 <= exit_code <= 255
            or not isinstance(nonce, str)
            or not re.fullmatch(r"[0-9a-f]{64}", nonce)
        ):
            return None
        observed_nonce_digest = hashlib.sha256(nonce.encode("ascii")).hexdigest()
        expected_nonce_digest = str(record.get("completion_nonce_sha256") or "")
        if not hmac.compare_digest(observed_nonce_digest, expected_nonce_digest):
            return None
        succeeded = exit_code == 0
        return JobStatusV1(
            handle_id=handle.handle_id,
            job_id=job_id,
            state="succeeded" if succeeded else "failed",
            scheduler_state="COMPLETED" if succeeded else "FAILED",
            exit_code=exit_code,
            reason="fixed-wrapper-completion-v1",
        )

    async def cancel(self, handle_or_job_id: str) -> dict[str, Any]:
        _record, handle, job_id = self._resolve(handle_or_job_id)
        response = await self.runner.run(["scancel", job_id])
        if response.returncode != 0:
            raise SchedulerProtocolError(
                _safe_error(
                    "scancel rejected the request", response.stderr or response.stdout
                )
            )
        return {
            "schema_version": "ari.hpc.job-cancel/v1",
            "handle_id": handle.handle_id if handle else None,
            "job_id": job_id,
            "status": "cancel_requested",
        }

    async def logs(self, handle_or_job_id: str) -> tuple[JobLogV1, ...]:
        record, handle, job_id = self._resolve(handle_or_job_id)
        if record is None or handle is None:
            raise SchedulerValidationError("logs require a job submitted through ARI")
        logs: list[JobLogV1] = []
        for stream, suffix in (("stdout", "out"), ("stderr", "err")):
            path = Path(handle.artifact_scope) / f"slurm-{job_id}.{suffix}"
            value = await self._read_log(path, stream)
            if value is not None:
                logs.append(value)
        return tuple(logs)

    async def result(self, handle_or_job_id: str) -> JobResultV1:
        record, handle, _job_id = self._resolve(handle_or_job_id)
        if record is None or handle is None:
            raise SchedulerValidationError(
                "result requires a job submitted through ARI"
            )
        request_payload = record.get("request")
        if (
            not isinstance(request_payload, dict)
            or request_payload.get("schema_version") != "ari.hpc.job-request/v1"
        ):
            raise SchedulerValidationError(
                "legacy jobs expose status/logs but not a typed JobResultV1"
            )
        request = JobRequestV1.model_validate(request_payload)
        status = await self.status(handle.handle_id)
        if status.state not in _TERMINAL_STATES:
            raise SchedulerValidationError(
                "job result is unavailable before a terminal state"
            )
        logs = await self.logs(handle.handle_id)
        error: JobErrorV1 | None = None
        outputs: list[ArtifactPinV1] = []
        try:
            self._verify_request_artifacts(request)
            outputs = self._collect_outputs(request)
        except SchedulerError as exc:
            error = JobErrorV1(kind="artifact", message=str(exc), retryable=False)
        if error is None and status.state != "succeeded":
            error = JobErrorV1(
                kind="execution",
                message=f"scheduler job ended in {status.scheduler_state}",
                retryable=status.scheduler_state
                in {"NODE_FAIL", "PREEMPTED", "REQUEUED"},
            )
        provenance = tuple(self._collect_provenance(handle))
        module_snapshot = next(
            (
                item.digest
                for item in provenance
                if item.logical_name == "module-snapshot"
            ),
            None,
        )
        result = JobResultV1(
            handle=handle,
            status=status,
            request_digest=request.request_digest,
            environment_digest=sha256_digest(
                request.environment.model_dump(mode="json")
            ),
            module_digest=sha256_digest(list(request.environment.modules)),
            module_snapshot_digest=module_snapshot,
            container_digest=request.container.image.digest
            if request.container
            else None,
            accelerator_allocation_digest=(
                sha256_digest(
                    request.accelerator_allocation.model_dump(mode="json")
                )
                if request.accelerator_allocation is not None
                else None
            ),
            accelerator_inventory_digest=next(
                (
                    item.digest
                    for item in provenance
                    if item.logical_name == "observed-accelerator-inventory"
                ),
                None,
            ),
            inputs=request.inputs,
            outputs=tuple(outputs),
            provenance=provenance,
            logs=logs,
            error=error,
        ).with_digest()
        self._write_json_atomic(
            Path(handle.artifact_scope) / "result-v1.json",
            result.model_dump(mode="json"),
        )
        return result

    def _resolve(
        self, handle_or_job_id: str
    ) -> tuple[dict[str, Any] | None, JobHandleV1 | None, str]:
        if not isinstance(handle_or_job_id, str) or not handle_or_job_id:
            raise SchedulerValidationError("job handle is empty")
        record = self.ledger.find(handle_or_job_id)
        if record is not None:
            handle = JobHandleV1.model_validate(record["handle"])
            return record, handle, handle.job_id
        if not _JOB_ID_RE.fullmatch(handle_or_job_id):
            raise SchedulerValidationError("unknown or invalid job handle")
        return None, None, handle_or_job_id

    def _artifact_scope(self, work_dir: str, digest: str) -> Path:
        work = _validated_work_dir(work_dir)
        scope = work / ".ari-hpc" / digest.removeprefix("sha256:")
        try:
            scope.relative_to(work)
        except ValueError as exc:
            raise SchedulerValidationError("artifact scope escaped work_dir") from exc
        return scope

    def _ensure_artifact_scope(self, work_dir: str, digest: str) -> Path:
        scope = self._artifact_scope(work_dir, digest)
        root = scope.parent
        if root.exists() and root.is_symlink():
            raise SchedulerValidationError(".ari-hpc must not be a symlink")
        root.mkdir(mode=0o700, exist_ok=True)
        if scope.exists() and scope.is_symlink():
            raise SchedulerValidationError("job artifact scope must not be a symlink")
        scope.mkdir(mode=0o700, exist_ok=True)
        return scope

    def _verify_request_artifacts(self, request: JobRequestV1) -> None:
        work_dir = _validated_work_dir(request.work_dir)
        for artifact in request.inputs:
            _verify_file_pin(artifact)
        for output in request.outputs:
            path = Path(output.path)
            parent = path.parent
            if not parent.is_dir() or parent.is_symlink():
                raise SchedulerValidationError(
                    f"output parent is missing or unsafe: {output.logical_name}"
                )
            try:
                parent.resolve(strict=True).relative_to(work_dir.resolve(strict=True))
            except ValueError as exc:
                raise SchedulerValidationError(
                    f"output resolves outside work_dir: {output.logical_name}"
                ) from exc
            if path.is_symlink():
                raise SchedulerValidationError(
                    f"output path is a symlink: {output.logical_name}"
                )
        if request.container:
            _verify_file_pin(request.container.image)
            for bind in request.container.binds:
                source = Path(bind.source)
                if not source.exists() or source.is_symlink():
                    raise SchedulerValidationError(
                        f"container bind source is missing or unsafe: {bind.source}"
                    )
            sources = [
                Path(request.work_dir),
                *[Path(b.source) for b in request.container.binds],
            ]
            for artifact in request.inputs:
                if artifact.path == request.container.image.path:
                    continue
                if not any(
                    _is_below(Path(artifact.path), source) for source in sources
                ):
                    raise SchedulerValidationError(
                        f"container input {artifact.logical_name} is outside declared binds"
                    )
        if request.accelerator_allocation is not None:
            _verify_file_pin(request.accelerator_allocation.inventory_probe)

    def _collect_outputs(self, request: JobRequestV1) -> list[ArtifactPinV1]:
        if not self.shared_filesystem:
            raise SchedulerValidationError(
                "typed outputs require a configured shared filesystem"
            )
        values: list[ArtifactPinV1] = []
        for output in request.outputs:
            path = Path(output.path)
            if not path.exists():
                if output.required:
                    raise SchedulerValidationError(
                        f"required output is missing: {output.logical_name}"
                    )
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or path.is_symlink():
                raise SchedulerValidationError(
                    f"output is not a regular non-symlink file: {output.logical_name}"
                )
            try:
                path.resolve(strict=True).relative_to(
                    Path(request.work_dir).resolve(strict=True)
                )
            except ValueError as exc:
                raise SchedulerValidationError(
                    f"output resolved outside work_dir: {output.logical_name}"
                ) from exc
            if info.st_size > output.max_bytes:
                raise SchedulerValidationError(
                    f"output exceeds declared size: {output.logical_name}"
                )
            values.append(
                ArtifactPinV1(
                    logical_name=output.logical_name,
                    path=str(path),
                    digest=file_digest(path),
                    size_bytes=info.st_size,
                    media_type=output.media_type,
                )
            )
        return values

    @staticmethod
    def _collect_provenance(handle: JobHandleV1) -> list[ArtifactPinV1]:
        values: list[ArtifactPinV1] = []
        scope = Path(handle.artifact_scope)
        for logical_name, filename, media_type in (
            ("submission-record", "submission-v1.json", "application/json"),
            (
                "wrapper-completion",
                "wrapper-completion-v1.json",
                "application/json",
            ),
            ("execution-environment", "execution-environment.txt", "text/plain"),
            ("module-snapshot", "module-list.txt", "text/plain"),
            ("container-runtime", "container-runtime.txt", "text/plain"),
            (
                "expected-accelerator-inventory",
                "accelerator-inventory.expected.csv",
                "text/csv",
            ),
            (
                "observed-accelerator-inventory",
                "accelerator-inventory.observed.csv",
                "text/csv",
            ),
            ("exit-code", "exit-code.txt", "text/plain"),
        ):
            path = scope / filename
            if not path.exists():
                continue
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or path.is_symlink()
                or info.st_size > 16 * 1024 * 1024
            ):
                raise SchedulerProtocolError("job provenance artifact is unsafe")
            values.append(
                ArtifactPinV1(
                    logical_name=logical_name,
                    path=str(path),
                    digest=file_digest(path),
                    size_bytes=info.st_size,
                    media_type=media_type,
                )
            )
        return values

    def _render_script(
        self,
        request: JobRequestV1,
        scope: Path,
        *,
        completion_nonce: str | None = None,
    ) -> str:
        lines = self._header(
            job_name=request.job_name,
            resources=request.resources,
            work_dir=request.work_dir,
            artifact_scope=scope,
        )
        lines.extend(self._clean_environment(request.environment.path))
        for name, value in sorted(request.environment.variables.items()):
            lines.append(f"export {name}={shlex.quote(value)}")
        if request.environment.modules:
            lines.extend(self._module_init_lines())
            lines.extend(
                [
                    # Kept as the honest failure for a node with no module
                    # system at all: a job that asked for modules must not
                    # quietly run without them.
                    "if ! command -v module >/dev/null 2>&1; then",
                    "  echo 'ARI: requested environment modules are unavailable' >&2",
                    "  exit 86",
                    "fi",
                    "module --force purge",
                ]
            )
            for module in request.environment.modules:
                lines.append(f"module load {shlex.quote(module)}")
            module_path = scope / "module-list.txt"
            lines.append(f"module -t list 2> {shlex.quote(str(module_path))} || true")
        if request.accelerator_allocation is not None:
            lines.extend(self._accelerator_inventory_check(request, scope))
        lines.extend(self._runtime_snapshot(request, scope))
        for artifact in request.inputs:
            lines.extend(_digest_check_lines(artifact.path, artifact.digest))
        command = list(request.argv)
        if request.container:
            lines.extend(
                _digest_check_lines(
                    request.container.image.path, request.container.image.digest
                )
            )
            command = self._container_command(request)
        exit_path = scope / "exit-code.txt"
        lines.extend(
            [
                "set +e",
                shlex.join(command),
                "ari_job_rc=$?",
                "set -e",
                f"printf '%s\\n' \"$ari_job_rc\" > {shlex.quote(str(exit_path))}",
            ]
        )
        if completion_nonce is not None:
            completion_path = scope / "wrapper-completion-v1.json"
            completion_temporary = scope / ".wrapper-completion-v1.tmp"
            record = (
                "{\"schema_version\":\"ari.hpc.wrapper-completion/v1\","
                f"\"request_digest\":\"{request.request_digest}\","
                f"\"cluster_identity\":\"{self.cluster_identity}\","
                "\"job_id\":\"%s\",\"exit_code\":%s,"
                f"\"completion_nonce\":\"{completion_nonce}\"}}"
            )
            lines.extend(
                [
                    (
                        f"printf '{record}\\n' \"${{SLURM_JOB_ID:?}}\" "
                        f'"$ari_job_rc" > {shlex.quote(str(completion_temporary))}'
                    ),
                    f"chmod 600 {shlex.quote(str(completion_temporary))}",
                    (
                        f"mv -f -- {shlex.quote(str(completion_temporary))} "
                        f"{shlex.quote(str(completion_path))}"
                    ),
                ]
            )
        lines.append('exit "$ari_job_rc"')
        return "\n".join(lines) + "\n"

    @staticmethod
    def _accelerator_inventory_check(
        request: JobRequestV1, scope: Path
    ) -> list[str]:
        allocation = request.accelerator_allocation
        assert allocation is not None
        expected_path = scope / "accelerator-inventory.expected.csv"
        observed_path = scope / "accelerator-inventory.observed.csv"
        expected_lines = [
            (
                f"{item.uuid}, {item.name}, {item.driver_version}, "
                f"{item.memory_mb}, {item.compute_capability}"
            )
            for item in allocation.devices
        ]
        probe = allocation.inventory_probe
        lines = _digest_check_lines(probe.path, probe.digest)
        lines.append(
            "printf '%s\\n' "
            + " ".join(shlex.quote(item) for item in expected_lines)
            + f" > {shlex.quote(str(expected_path))}"
        )
        lines.extend(
            [
                (
                    f"{shlex.quote(probe.path)} "
                    "--query-gpu=uuid,name,driver_version,memory.total,compute_cap "
                    "--format=csv,noheader,nounits | LC_ALL=C sort > "
                    f"{shlex.quote(str(observed_path))}"
                ),
                (
                    f"if ! cmp -s -- {shlex.quote(str(expected_path))} "
                    f"{shlex.quote(str(observed_path))}; then"
                ),
                "  echo 'ARI: exclusive-node accelerator inventory mismatch' >&2",
                (
                    f"  diff -u -- {shlex.quote(str(expected_path))} "
                    f"{shlex.quote(str(observed_path))} >&2 || true"
                ),
                "  exit 87",
                "fi",
            ]
        )
        return lines

    @staticmethod
    def _runtime_snapshot(request: JobRequestV1, scope: Path) -> list[str]:
        snapshot = scope / "execution-environment.txt"
        command = shlex.quote(request.argv[0])
        lines = [
            "{",
            "  printf 'hostname=%s\\n' \"$(hostname)\"",
            "  printf 'architecture=%s\\n' \"$(uname -m)\"",
            "  printf 'kernel=%s\\n' \"$(uname -sr)\"",
            "  printf 'cpu_model=%s\\n' \"$(lscpu 2>/dev/null | "
            "awk -F: '/Model name/{sub(/^[ \\t]+/, \"\", $2); print $2; exit}' || true)\"",
            "  printf 'cpu_logical_count=%s\\n' \"$(getconf _NPROCESSORS_ONLN "
            "2>/dev/null || true)\"",
            "  printf 'gcc=%s\\n' \"$(gcc --version 2>/dev/null | head -n 1 || true)\"",
            "  printf 'clang=%s\\n' \"$(clang --version 2>/dev/null | head -n 1 || true)\"",
            "  printf 'mpicc=%s\\n' \"$(mpicc --version 2>/dev/null | head -n 1 || true)\"",
            "  printf 'nvcc=%s\\n' \"$(nvcc --version 2>/dev/null | tail -n 1 || true)\"",
            "  printf 'gpu=%s\\n' \"$(nvidia-smi --query-gpu=name,uuid,driver_version "
            "--format=csv,noheader 2>/dev/null | paste -sd ';' - || true)\"",
            "  printf 'slurm_job_id=%s\\n' \"${SLURM_JOB_ID:-}\"",
            f"  printf 'command_path=%s\\n' \"$(command -v -- {command} 2>/dev/null || true)\"",
            f"}} > {shlex.quote(str(snapshot))}",
        ]
        if request.container:
            container_snapshot = scope / "container-runtime.txt"
            runtime = shlex.quote(request.container.runtime)
            lines.extend(
                [
                    f"{{ {runtime} version 2>&1 || true; }} > "
                    f"{shlex.quote(str(container_snapshot))}",
                ]
            )
        return lines

    def _render_script_bridge(
        self,
        *,
        script: str,
        job_name: str,
        resources: ResourceRequestV1,
        work_dir: str,
        artifact_scope: Path,
    ) -> str:
        lines = self._header(
            job_name=job_name,
            resources=resources,
            work_dir=work_dir,
            artifact_scope=artifact_scope,
        )
        lines.extend(self._clean_environment("/usr/local/bin:/usr/bin:/bin"))
        # The bridge hands the agent a raw script, and on a cluster whose
        # toolchain is reachable only through modules the first thing such a
        # script writes is `module load`. Without this it died with a bare
        # "module: command not found" (exit 127) and no explanation — correct
        # HPC code failing for a reason the agent could not see or fix.
        # Unconditional and guarded, rather than conditional on the script
        # mentioning `module`: matching on the body would be guesswork, and
        # this is a no-op wherever there is no module system.
        lines.extend(self._module_init_lines())
        # Generated executable content appears first, so #SBATCH text in the
        # compute-node body cannot override scheduler policy.
        lines.extend(["# ARI core-agent script bridge", script])
        return "\n".join(lines) + "\n"

    def _header(
        self,
        *,
        job_name: str,
        resources: ResourceRequestV1,
        work_dir: str,
        artifact_scope: Path,
    ) -> list[str]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}", job_name):
            raise SchedulerValidationError("job name is invalid")
        lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name={job_name}",
            f"#SBATCH --partition={resources.partition}",
            f"#SBATCH --nodes={resources.nodes}",
            f"#SBATCH --ntasks={resources.tasks}",
            f"#SBATCH --cpus-per-task={resources.cpus_per_task}",
            f"#SBATCH --time={resources.walltime}",
            f"#SBATCH --chdir={work_dir}",
            f"#SBATCH --output={artifact_scope}/slurm-%j.out",
            f"#SBATCH --error={artifact_scope}/slurm-%j.err",
            "#SBATCH --export=NIL",
        ]
        if resources.memory_mb_per_node:
            lines.append(f"#SBATCH --mem={resources.memory_mb_per_node}M")
        if resources.memory_mb_per_cpu:
            lines.append(f"#SBATCH --mem-per-cpu={resources.memory_mb_per_cpu}M")
        if resources.tasks_per_node:
            lines.append(f"#SBATCH --ntasks-per-node={resources.tasks_per_node}")
        if resources.nodelist:
            lines.append(f"#SBATCH --nodelist={resources.nodelist}")
        if resources.exclude_nodes:
            lines.append(f"#SBATCH --exclude={resources.exclude_nodes}")
        if resources.gpus_per_task:
            value = ""
            if resources.gpu_type:
                value = f"{resources.gpu_type}:"
            value += str(resources.gpus_per_task)
            lines.append(f"#SBATCH --gpus-per-task={value}")
        elif resources.gpus_per_node:
            value = "gpu:"
            if resources.gpu_type:
                value += f"{resources.gpu_type}:"
            value += str(resources.gpus_per_node)
            lines.append(f"#SBATCH --gres={value}")
        if resources.exclusive:
            lines.append("#SBATCH --exclusive")
        if resources.constraint:
            lines.append(f"#SBATCH --constraint={resources.constraint}")
        if resources.hint:
            lines.append(f"#SBATCH --hint={resources.hint}")
        if resources.account:
            lines.append(f"#SBATCH --account={resources.account}")
        if resources.qos:
            lines.append(f"#SBATCH --qos={resources.qos}")
        if resources.reservation:
            lines.append(f"#SBATCH --reservation={resources.reservation}")
        return lines

    @staticmethod
    def _module_init_lines() -> list[str]:
        """Make `module` usable on the node, inheriting nothing.

        `module` is a SHELL FUNCTION defined by the module system's profile
        script. A batch job gets one from neither direction: --export=NIL
        carries nothing over from the submitting shell, and `#!/bin/bash` is
        not a login shell so no profile is read. Sourcing the init ON THE NODE
        is what keeps --export=NIL meaningful — nothing is inherited, the node
        describes itself, and a login node's state still cannot reach a
        measurement.

        These are the module SOFTWARE's standard install paths, not any one
        site's, so no cluster knowledge is added here. A no-op where there is
        no module system, which is why the callers keep their own checks.
        """
        return [
            "if ! command -v module >/dev/null 2>&1; then",
            # A profile script is not written for `set -euo pipefail` and may
            # read unset variables; relaxing around the source keeps it from
            # aborting an otherwise valid job.
            "  set +eu +o pipefail",
            "  for _ari_module_init in"
            " /etc/profile.d/modules.sh"
            " /etc/profile.d/lmod.sh"
            ' "${MODULESHOME:-}/init/bash"; do',
            '    [ -r "$_ari_module_init" ] || continue',
            '    . "$_ari_module_init" >/dev/null 2>&1',
            "    command -v module >/dev/null 2>&1 && break",
            "  done",
            "  unset _ari_module_init",
            "  set -eu -o pipefail",
            "fi",
        ]

    @staticmethod
    def _clean_environment(path: str) -> list[str]:
        return [
            "set -euo pipefail",
            "unset BASH_ENV ENV CDPATH GLOBIGNORE PYTHONHOME PYTHONPATH VIRTUAL_ENV",
            f"export PATH={shlex.quote(path)}",
            "export LANG=C.UTF-8",
            "export LC_ALL=C.UTF-8",
            # srun steps may inherit the now-clean script environment. No parent
            # login-node variables or credential file is sourced.
            "export SLURM_EXPORT_ENV=ALL",
        ]

    @staticmethod
    def _container_command(request: JobRequestV1) -> list[str]:
        assert request.container is not None
        container = request.container
        command = [container.runtime, "exec"]
        if container.contain_all:
            command.append("--containall")
        if container.clean_environment:
            command.append("--cleanenv")
        if container.network == "none":
            command.extend(["--net", "--network", "none"])
        if container.gpu:
            command.append("--nv")
        binds = list(container.binds)
        if not any(
            bind.source == request.work_dir and bind.target == request.work_dir
            for bind in binds
        ):
            from ari_skill_hpc.contracts import BindMountV1

            binds.append(
                BindMountV1(
                    source=request.work_dir,
                    target=request.work_dir,
                    read_only=False,
                )
            )
        for bind in binds:
            mode = "ro" if bind.read_only else "rw"
            command.extend(["--bind", f"{bind.source}:{bind.target}:{mode}"])
        command.extend(["--pwd", request.work_dir])
        for name, value in sorted(request.environment.variables.items()):
            command.extend(["--env", f"{name}={value}"])
        command.append(container.image.path)
        command.extend(request.argv)
        return command

    async def _read_log(self, path: Path, stream: str) -> JobLogV1 | None:
        if self.shared_filesystem:
            if not path.exists():
                return None
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or path.is_symlink():
                raise SchedulerProtocolError("scheduler log is not a safe regular file")
            raw = path.read_bytes()
            truncated = len(raw) > _OUTPUT_LIMIT
            shown = raw[:_OUTPUT_LIMIT]
            return JobLogV1(
                stream=stream,
                path=str(path),
                digest="sha256:" + __import__("hashlib").sha256(raw).hexdigest(),
                size_bytes=len(raw),
                text=shown.decode("utf-8", errors="replace"),
                truncated=truncated,
            )
        response = await self.runner.run(["cat", "--", str(path)])
        if response.returncode != 0:
            return None
        raw = response.stdout.encode("utf-8")
        return JobLogV1(
            stream=stream,
            path=str(path),
            digest="sha256:" + __import__("hashlib").sha256(raw).hexdigest(),
            size_bytes=len(raw),
            text=response.stdout,
            truncated=len(raw) >= _OUTPUT_LIMIT,
        )

    @staticmethod
    def _write_submission_record(
        artifact_scope: Path,
        *,
        request: dict[str, Any],
        script_digest: str,
        submission_digest: str,
        terminal_evidence_policy: str = "scheduler-accounting",
        completion_nonce_sha256: str | None = None,
    ) -> None:
        value = {
            "schema_version": "ari.hpc.submission/v1",
            "request": request,
            "script_digest": script_digest,
            "submission_digest": submission_digest,
            "recorded_at": utc_now(),
        }
        if terminal_evidence_policy != "scheduler-accounting":
            value.update(
                {
                    "terminal_evidence_policy": terminal_evidence_policy,
                    "completion_nonce_sha256": completion_nonce_sha256,
                }
            )
        SlurmScheduler._write_json_atomic(
            artifact_scope / "submission-v1.json", value
        )

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def close(self) -> None:
        self.runner.close()


def _validated_work_dir(value: str) -> Path:
    path = Path(value)
    if (
        not path.is_absolute()
        or any(character.isspace() for character in value)
        or ".." in path.parts
        or any(character in value for character in "\x00\n\r")
    ):
        raise SchedulerValidationError("work_dir must be an inert absolute path")
    if not path.is_dir() or path.is_symlink():
        raise SchedulerValidationError(
            "work_dir must be an existing non-symlink directory"
        )
    return path


def _verify_file_pin(artifact: ArtifactPinV1) -> None:
    path = Path(artifact.path)
    if not path.exists():
        raise SchedulerValidationError(f"input is missing: {artifact.logical_name}")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise SchedulerValidationError(
            f"input is not a regular non-symlink file: {artifact.logical_name}"
        )
    if info.st_size != artifact.size_bytes:
        raise SchedulerValidationError(f"input size drift: {artifact.logical_name}")
    if file_digest(path) != artifact.digest:
        raise SchedulerValidationError(f"input digest drift: {artifact.logical_name}")


def _digest_check_lines(path: str, digest: str) -> list[str]:
    expected = digest.removeprefix("sha256:")
    quoted_path = shlex.quote(path)
    return [
        f"ari_actual_digest=$(sha256sum -- {quoted_path} | awk '{{print $1}}')",
        f'if [ "$ari_actual_digest" != {shlex.quote(expected)} ]; then',
        f"  echo {shlex.quote('ARI: input digest mismatch: ' + path)} >&2",
        "  exit 85",
        "fi",
    ]


def _is_below(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        return True
    except ValueError:
        return False


def _parse_job_id(stdout: str) -> str:
    first = stdout.splitlines()[0].strip() if stdout else ""
    candidate = first.split(";", 1)[0]
    if not _JOB_ID_RE.fullmatch(candidate):
        # Compatibility with older Slurm output if --parsable is ignored.
        match = re.fullmatch(r"Submitted batch job ([0-9]+(?:_[0-9]+)?)", first)
        if match:
            return match.group(1)
        raise SchedulerProtocolError("sbatch returned an invalid job identifier")
    return candidate


def _handle_id(cluster: str, request: str, job_id: str) -> str:
    value = sha256_digest({"cluster": cluster, "request": request, "job_id": job_id})
    return "hpc-" + value.removeprefix("sha256:")[:48]


def _base_state(value: str) -> str:
    base = _STATE_SUFFIX_RE.sub("", value.strip().upper())
    return base or "UNKNOWN"


def _normalize_state(value: str) -> str:
    state = _base_state(value)
    if state in {"PENDING", "CONFIGURING", "REQUEUED", "RESIZING", "SPECIAL_EXIT"}:
        return "submitted"
    if state in {"RUNNING", "COMPLETING", "SUSPENDED", "STAGE_OUT"}:
        return "running"
    if state == "COMPLETED":
        return "succeeded"
    if state in {"CANCELLED", "CANCELED", "DEADLINE", "REVOKED"}:
        return "cancelled"
    if state in {
        "BOOT_FAIL",
        "FAILED",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "TIMEOUT",
    }:
        return "failed"
    return "unknown"


def _parse_sacct(text: str, job_id: str) -> dict[str, Any] | None:
    chosen: list[str] | None = None
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 6:
            continue
        if parts[0] == job_id:
            chosen = parts
            break
        if chosen is None and not any(
            suffix in parts[0] for suffix in (".batch", ".extern")
        ):
            chosen = parts
    if chosen is None:
        return None
    state = _base_state(chosen[1])
    exit_code = None
    exit_atom = chosen[2].split(":", 1)[0]
    if exit_atom.lstrip("-").isdigit():
        exit_code = int(exit_atom)
    return {
        "state": _normalize_state(state),
        "scheduler_state": state,
        "exit_code": exit_code,
        "start_time": chosen[3] if chosen[3] not in {"", "Unknown"} else None,
        "end_time": chosen[4] if chosen[4] not in {"", "Unknown"} else None,
        "reason": chosen[5][:2000] if chosen[5] not in {"", "None"} else None,
    }


def _safe_error(prefix: str, detail: str) -> str:
    cleaned = " ".join(detail.replace("\x00", "").split())[:1500]
    return f"{prefix}: {cleaned}" if cleaned else prefix
