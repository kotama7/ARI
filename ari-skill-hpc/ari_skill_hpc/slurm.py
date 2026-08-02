"""SLURM compatibility facade and compute-platform capability probe.

New consumers should use :mod:`ari_skill_hpc.contracts` and
:class:`ari_skill_hpc.scheduler.SlurmScheduler`.
The ``SlurmClient`` facade preserves the existing MCP aliases while routing every
scheduler operation through the same shell-free backend.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ari_skill_hpc.scheduler import (
    LocalCommandRunner,
    RemoteCommandRunner,
    RemoteConfig,
    SchedulerError,
    SchedulerValidationError,
    SlurmScheduler,
)

__all__ = [
    "RemoteConfig",
    "SlurmClient",
    "probe_platform_capabilities",
]

_JOB_ID_RE = re.compile(r"^[0-9]+(?:_[0-9]+)?$")


@dataclass
class SlurmClient:
    """Backward-compatible adapter around the canonical SLURM scheduler."""

    mode: str = "local"
    remote_config: RemoteConfig | None = None
    ledger_path: Path | None = None
    _scheduler: SlurmScheduler = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.mode == "local":
            runner = LocalCommandRunner(
                scheduler_path=os.environ.get(
                    "ARI_SCHEDULER_PATH", "/usr/local/bin:/usr/bin:/bin"
                )
            )
            shared_filesystem = True
        elif self.mode in {"remote", "ssh"}:
            if self.remote_config is None:
                raise ValueError("remote_config is required for remote mode")
            runner = RemoteCommandRunner(self.remote_config)
            shared_filesystem = self.remote_config.shared_filesystem
        else:
            raise ValueError("SLURM mode must be local or remote")
        if self.ledger_path is None:
            self._scheduler = SlurmScheduler(
                runner=runner, shared_filesystem=shared_filesystem
            )
        else:
            from ari_skill_hpc.scheduler import SubmissionLedger

            self._scheduler = SlurmScheduler(
                runner=runner,
                ledger=SubmissionLedger(self.ledger_path),
                shared_filesystem=shared_filesystem,
            )

    @property
    def scheduler(self) -> SlurmScheduler:
        return self._scheduler

    async def submit(self, script: str, **kwargs: object) -> dict[str, Any]:
        work_dir = str(
            kwargs.get("work_dir")
            or os.environ.get("SLURM_DEFAULT_WORK_DIR")
            or os.environ.get("ARI_WORK_DIR")
            or os.getcwd()
        )
        partition = str(
            kwargs.get("partition")
            or os.environ.get("SLURM_DEFAULT_PARTITION")
            or os.environ.get("ARI_SLURM_PARTITION")
            or ""
        )
        try:
            handle = await self._scheduler.submit_legacy_script(
                script=script,
                job_name=str(kwargs.get("job_name") or "mcp_job"),
                partition=partition,
                nodes=int(kwargs.get("nodes") or 1),
                walltime=str(kwargs.get("walltime") or "01:00:00"),
                work_dir=work_dir,
                cpus_per_task=int(
                    kwargs.get("cpus_per_task") or os.environ.get("ARI_SLURM_CPUS") or 1
                ),
                memory_gb=_optional_int(
                    kwargs.get("memory_gb") or os.environ.get("ARI_SLURM_MEM_GB")
                ),
                gres=str(kwargs.get("gres") or _gres_from_environment() or "") or None,
                account=str(kwargs.get("account") or "") or None,
            )
        except SchedulerError as exc:
            return {
                "job_id": "",
                "status": "error",
                "message": str(exc),
                "partition": partition,
            }
        return {
            "schema_version": handle.schema_version,
            "handle_id": handle.handle_id,
            "job_id": handle.job_id,
            "state": handle.state,
            "status": handle.status,
            "message": f"Job {handle.job_id} submitted successfully",
            "request_digest": handle.request_digest,
            "submission_digest": handle.submission_digest,
        }

    async def status(self, job_id: str) -> dict[str, Any]:
        if not job_id:
            return {
                "job_id": "",
                "status": "ERROR",
                "normalized_state": "unknown",
                "exit_code": None,
                "start_time": None,
                "end_time": None,
                "stdout": None,
                "stderr": None,
                "message": "job_id is empty; submission did not return a handle",
            }
        try:
            status = await self._scheduler.status(job_id)
            logs = ()
            if status.state in {"succeeded", "failed", "cancelled"}:
                try:
                    logs = await self._scheduler.logs(job_id)
                except SchedulerError:
                    logs = ()
        except SchedulerError as exc:
            return {
                "job_id": job_id,
                "status": "ERROR",
                "normalized_state": "unknown",
                "exit_code": None,
                "start_time": None,
                "end_time": None,
                "stdout": None,
                "stderr": None,
                "message": str(exc),
            }
        by_stream = {item.stream: item.text for item in logs}
        return {
            "schema_version": status.schema_version,
            "handle_id": status.handle_id,
            "job_id": status.job_id,
            "status": status.scheduler_state,
            "normalized_state": status.state,
            "exit_code": status.exit_code,
            "start_time": status.start_time,
            "end_time": status.end_time,
            "reason": status.reason,
            "stdout": by_stream.get("stdout"),
            "stderr": by_stream.get("stderr"),
        }

    async def cancel(self, job_id: str) -> dict[str, Any]:
        try:
            result = await self._scheduler.cancel(job_id)
        except SchedulerError as exc:
            return {"success": False, "message": str(exc), "job_id": job_id}
        return {
            **result,
            "success": True,
            "message": f"Job {result['job_id']} cancellation requested",
        }

    async def get_stdout(self, job_id: str) -> str | None:
        return await self._get_log(job_id, "stdout")

    async def get_stderr(self, job_id: str) -> str | None:
        return await self._get_log(job_id, "stderr")

    async def _get_log(self, job_id: str, stream: str) -> str | None:
        if not _JOB_ID_RE.fullmatch(job_id):
            raise SchedulerValidationError("invalid SLURM job id")
        try:
            logs = await self._scheduler.logs(job_id)
            for item in logs:
                if item.stream == stream:
                    return item.text
        except SchedulerError:
            pass
        suffix = "out" if stream == "stdout" else "err"
        candidates: list[Path] = []
        for root in (
            os.environ.get("SLURM_LOG_DIR", ""),
            os.environ.get("ARI_WORK_DIR", ""),
            os.getcwd(),
        ):
            if root:
                candidates.extend(
                    [
                        Path(root) / f"slurm_job_{job_id}.{suffix}",
                        Path(root) / f"slurm-{job_id}.{suffix}",
                    ]
                )
        for path in candidates:
            if self.mode == "local":
                if path.exists():
                    info = path.lstat()
                    if stat.S_ISREG(info.st_mode) and not path.is_symlink():
                        return (
                            path.read_bytes()[:1_048_576]
                            .decode("utf-8", errors="replace")
                            .strip()
                        )
            else:
                response = await self._scheduler.runner.run(["cat", "--", str(path)])
                if response.returncode == 0 and response.stdout:
                    return response.stdout
        return None

    def close(self) -> None:
        self._scheduler.close()


def _optional_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


def _gres_from_environment() -> str | None:
    value = os.environ.get("ARI_SLURM_GPUS", "").strip()
    if not value:
        return None
    count = int(value)
    return f"gpu:{count}" if count else None


# Platform capability probing remains best-effort, but validates every atom and
# writes the cache atomically without following a symlink.
_DEFAULT_PROBE_TOOLS = "perf,numactl,papi_avail,likwid-perfctr,valgrind"
_TOOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")
_PARTITION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}$")
_ARCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")


def _parse_capability_output(text: str) -> dict[str, Any]:
    output: dict[str, Any] = {"available": {}}
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("arch="):
            architecture = line.split("=", 1)[1]
            if _ARCH_RE.fullmatch(architecture):
                output["arch"] = architecture
        elif "=" in line:
            name, value = line.split("=", 1)
            if value in {"yes", "no"} and _TOOL_RE.fullmatch(name):
                output["available"][name] = value == "yes"
    return output


async def probe_platform_capabilities(
    checkpoint_dir: str,
    partition: str = "",
    tools: str = "",
    timeout_s: int = 120,
) -> dict[str, Any]:
    checkpoint = Path(checkpoint_dir)
    if (
        not checkpoint.is_absolute()
        or ".." in checkpoint.parts
        or any(character.isspace() for character in checkpoint_dir)
        or checkpoint.is_symlink()
    ):
        return {
            "status": "skipped",
            "reason": "checkpoint_dir must be a safe absolute path",
        }
    output_path = checkpoint / "platform_capabilities.json"
    if output_path.is_file() and not output_path.is_symlink():
        try:
            cached = json.loads(output_path.read_text(encoding="utf-8"))
            if _valid_capability_record(cached):
                return {**cached, "status": "cached"}
        except (OSError, json.JSONDecodeError):
            pass

    selected_partition = (
        partition or os.environ.get("ARI_SLURM_PARTITION", "")
    ).strip()
    if not selected_partition:
        return {"status": "skipped", "reason": "no partition configured"}
    if not _PARTITION_RE.fullmatch(selected_partition):
        return {"status": "skipped", "reason": "partition is invalid"}
    tool_list = [
        item.strip()
        for item in (
            tools or os.environ.get("ARI_PROBE_TOOLS", _DEFAULT_PROBE_TOOLS)
        ).split(",")
        if item.strip()
    ]
    if not tool_list:
        return {"status": "skipped", "reason": "no tools to probe"}
    if len(tool_list) > 128 or any(not _TOOL_RE.fullmatch(item) for item in tool_list):
        return {"status": "skipped", "reason": "probe tool list is invalid"}
    if len(tool_list) != len(set(tool_list)):
        return {"status": "skipped", "reason": "probe tool list contains duplicates"}
    if not 1 <= timeout_s <= 3_600:
        return {"status": "skipped", "reason": "probe timeout is out of bounds"}

    checks = "; ".join(
        f"(command -v {item} >/dev/null 2>&1 && echo {item}=yes || echo {item}=no)"
        for item in tool_list
    )
    script = f'echo "arch=$(uname -m)"; {checks}'
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            "srun",
            "-p",
            selected_partition,
            "-N",
            "1",
            "-n",
            "1",
            "-t",
            "00:01:30",
            "bash",
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                "PATH": os.environ.get(
                    "ARI_SCHEDULER_PATH", "/usr/local/bin:/usr/bin:/bin"
                ),
                "LANG": "C.UTF-8",
            },
        )
        stdout, _stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout_s
        )
    except (TimeoutError, FileNotFoundError, OSError) as exc:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        return {"status": "skipped", "reason": f"probe failed: {exc!r}"}
    if process.returncode != 0:
        return {"status": "skipped", "reason": "probe scheduler command failed"}
    parsed = _parse_capability_output(stdout.decode("utf-8", errors="replace"))
    if not parsed.get("available"):
        return {"status": "skipped", "reason": "probe produced no capability lines"}
    record = {"partition": selected_partition, **parsed}
    try:
        checkpoint.mkdir(parents=True, exist_ok=True)
        if checkpoint.is_symlink() or output_path.is_symlink():
            raise OSError("unsafe capability cache path")
        descriptor, temporary = tempfile.mkstemp(
            prefix=".platform-capabilities.", dir=checkpoint
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, output_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except OSError as exc:
        return {"status": "unsaved", "reason": str(exc), **record}
    return {"status": "probed", **record}


def _valid_capability_record(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if not _PARTITION_RE.fullmatch(str(value.get("partition", ""))):
        return False
    architecture = value.get("arch")
    if architecture is not None and not _ARCH_RE.fullmatch(str(architecture)):
        return False
    available = value.get("available")
    return isinstance(available, dict) and all(
        _TOOL_RE.fullmatch(str(name)) and isinstance(present, bool)
        for name, present in available.items()
    )
