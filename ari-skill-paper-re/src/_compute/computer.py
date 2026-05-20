"""Concrete :class:`ComputerInterface` implementations for ari.

PaperBench upstream's reference :class:`ComputerInterface` implementation
(``AlcatrazComputerInterface``) requires Docker-in-Docker via the alcatraz
runtime. ari's sandbox stack is HPC-flavoured (Slurm partitions, Apptainer
images, local subprocess), so we provide a pair of concrete implementations
that satisfy the abstract contract without dragging in alcatraz / docker SDK.

Design notes
============

* The agent's ReAct loop sends *many* short shell commands per minute. A
  per-command ``sbatch`` would be fatal — every command would queue behind
  every other slurm submission. We therefore treat the **work_dir as a
  persistent, host-resident directory** (typically the agent's checkpoint
  ``repro_sandbox/``) and keep a single subprocess context throughout the
  rollout. When ari is itself running inside an sbatch allocation, the
  agent's commands automatically run on that node — that is the intended
  Slurm story. Per-command ``srun`` / ``sbatch`` is *not* used here.

* :meth:`disable_internet` is a no-op. PaperBench's reference setup uses
  Docker network namespace tricks to revoke outbound access mid-rollout;
  ari's HPC environment is typically network-restricted by default
  (Slurm-managed firewalls / proxy whitelists), so retroactive revocation
  is the cluster admin's job, not ours. PaperBench's paper §2.5 in any
  case only invokes the per-paper *blacklist* check post-hoc, not a runtime
  cut-off. Documenting the substitution.

* :meth:`fetch_container_names` is ``@deprecated`` upstream (CTF-only) and
  returns ``[]``.

Verified compliance: every abstract method on ``ComputerInterface`` has a
concrete implementation; ``ExecutionResult`` (a pydantic ``BaseModel``) is
constructed via the upstream type, not stubbed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
from pathlib import Path
from typing import Sequence

import _vendor_path  # noqa: F401  (ensures vendor on sys.path)

from nanoeval.solvers.computer_tasks.code_execution_interface import (
    ComputerInterface,
    ExecutionResult,
)

log = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_SEC = 60 * 30  # 30 min per shell command (matches PaperBench tools)


# ─── helpers ─────────────────────────────────────────────────────────────


def _resolve_dest(dest: str, work_dir: Path) -> Path:
    """Resolve a tool-supplied destination path.

    Absolute paths are honoured (the agent may want to read e.g. ``/etc``).
    Relative paths are placed inside ``work_dir``.
    """
    p = Path(dest)
    if p.is_absolute():
        return p
    return work_dir / p


# ─── LocalComputer ───────────────────────────────────────────────────────


class LocalComputer(ComputerInterface):
    """Run shell commands as plain subprocesses in a persistent host directory.

    Suitable for local development and for HPC runs that already happen
    inside an sbatch / salloc allocation (since ``subprocess`` then inherits
    the allocation's environment automatically).

    No isolation between the agent's commands and the host environment —
    the agent has the same privileges as the ari process. PaperBench's
    upstream reference uses container isolation; ari users who need
    isolation should pick :class:`ApptainerComputer` instead.
    """

    def __init__(
        self,
        work_dir: Path | str,
        *,
        env: dict[str, str] | None = None,
        timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.env = {**os.environ, **(env or {})}
        self.timeout_sec = timeout_sec
        self._stopped = False

    async def disable_internet(self) -> None:
        # See module docstring. PaperBench's notion of mid-rollout cutoff
        # has no portable Slurm equivalent and is not load-bearing for the
        # methodology (paper §2.5 blacklist is post-hoc).
        log.info("LocalComputer.disable_internet() is a no-op (HPC substrate)")

    async def upload(self, file: bytes, destination: str) -> None:
        if self._stopped:
            raise RuntimeError("computer stopped")
        path = _resolve_dest(destination, self.work_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file)

    async def download(self, file: str) -> bytes:
        if self._stopped:
            raise RuntimeError("computer stopped")
        path = _resolve_dest(file, self.work_dir)
        return path.read_bytes()

    async def send_shell_command(
        self,
        cmd: str,
        *,
        idempotent: bool = False,
    ) -> ExecutionResult:
        if self._stopped:
            raise RuntimeError("computer stopped")
        return await _run_subprocess(
            argv=["bash", "-lc", cmd],
            cwd=self.work_dir,
            env=self.env,
            timeout_sec=self.timeout_sec,
        )

    async def fetch_container_names(self) -> list[str]:  # type: ignore[override]
        return []

    async def stop(self) -> None:
        self._stopped = True


# ─── ApptainerComputer ───────────────────────────────────────────────────


class ApptainerComputer(ComputerInterface):
    """Run shell commands inside ``apptainer exec`` against a SIF image.

    Each command is dispatched as
    ``apptainer exec --bind {work_dir} {image} bash -lc {cmd}`` so the agent
    sees a containerised filesystem but writes persist to ``work_dir`` on
    the host. ``upload`` / ``download`` operate directly on the bind-mount
    (no need to round-trip through the container).

    Falls back to ``singularity`` if Apptainer is not installed.
    """

    def __init__(
        self,
        work_dir: Path | str,
        image: str,
        *,
        runner: str = "apptainer",
        env: dict[str, str] | None = None,
        extra_binds: Sequence[str] = (),
        timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
    ) -> None:
        if not image:
            raise ValueError("ApptainerComputer requires a non-empty image")
        if shutil.which(runner) is None:
            alt = "singularity" if runner == "apptainer" else "apptainer"
            if shutil.which(alt) is not None:
                runner = alt
            else:
                raise RuntimeError(
                    f"neither apptainer nor singularity is on PATH; "
                    f"install one or use LocalComputer instead"
                )
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.image = image
        self.runner = runner
        self.env = {**os.environ, **(env or {})}
        self.extra_binds = list(extra_binds)
        self.timeout_sec = timeout_sec
        self._stopped = False

    async def disable_internet(self) -> None:
        # Apptainer doesn't have a portable namespace-revoke. No-op; rely on
        # cluster network policy (same posture as LocalComputer).
        log.info("ApptainerComputer.disable_internet() is a no-op (HPC substrate)")

    async def upload(self, file: bytes, destination: str) -> None:
        if self._stopped:
            raise RuntimeError("computer stopped")
        path = _resolve_dest(destination, self.work_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file)

    async def download(self, file: str) -> bytes:
        if self._stopped:
            raise RuntimeError("computer stopped")
        path = _resolve_dest(file, self.work_dir)
        return path.read_bytes()

    async def send_shell_command(
        self,
        cmd: str,
        *,
        idempotent: bool = False,
    ) -> ExecutionResult:
        if self._stopped:
            raise RuntimeError("computer stopped")
        argv = [self.runner, "exec"]
        for b in [str(self.work_dir), *self.extra_binds]:
            argv += ["--bind", b]
        argv += [self.image, "bash", "-lc", cmd]
        return await _run_subprocess(
            argv=argv,
            cwd=self.work_dir,
            env=self.env,
            timeout_sec=self.timeout_sec,
        )

    async def fetch_container_names(self) -> list[str]:  # type: ignore[override]
        return []

    async def stop(self) -> None:
        self._stopped = True


# ─── factory ─────────────────────────────────────────────────────────────


def make_computer(
    work_dir: Path | str,
    *,
    kind: str = "auto",
    image: str | None = None,
    env: dict[str, str] | None = None,
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
) -> ComputerInterface:
    """Factory honouring ``ARI_PHASE1_SANDBOX`` semantics.

    ``kind`` resolution mirrors :func:`server._phase1_sandbox_kind`:

      ``auto``    → apptainer/singularity if image given, else local
      ``local``   → :class:`LocalComputer` (always)
      ``apptainer``/``singularity`` → :class:`ApptainerComputer`
      ``slurm``   → :class:`LocalComputer` (the assumption is that ari is
                    *already* running inside an allocation; per-command
                    sbatch is not viable at ReAct cadence)

    Docker is intentionally not supported here; PaperBench's alcatraz
    Docker path is excluded by design.
    """
    kind = (kind or "auto").lower()
    explicit = os.environ.get("ARI_PHASE1_SANDBOX", "").strip().lower()
    if explicit:
        kind = explicit

    if kind == "auto":
        kind = "apptainer" if image else "local"

    if kind in ("local", "slurm"):
        if kind == "slurm":
            log.warning(
                "Stage 1 (agent rollout) with sandbox_kind=%r executes on the "
                "host filesystem — there is NO container isolation. The "
                "agent's bash/python tools run as plain subprocesses against "
                "%s. This is intentional (per-command sbatch is not viable at "
                "ReAct cadence; the assumption is that ari itself is already "
                "running inside an sbatch allocation), but if you expected the "
                "agent to be sandboxed inside %r, pass sandbox_kind=apptainer "
                "with container_image=<SIF or docker://… URI> instead.",
                kind, str(work_dir), kind,
            )
        return LocalComputer(work_dir, env=env, timeout_sec=timeout_sec)
    if kind in ("apptainer", "singularity"):
        if not image:
            raise ValueError(
                f"sandbox kind={kind!r} requires an Apptainer SIF image"
            )
        return ApptainerComputer(
            work_dir, image, runner=kind, env=env, timeout_sec=timeout_sec,
        )
    raise ValueError(f"unsupported sandbox kind: {kind!r}")


# ─── subprocess plumbing ─────────────────────────────────────────────────


async def _run_subprocess(
    *,
    argv: Sequence[str],
    cwd: Path,
    env: dict[str, str],
    timeout_sec: int,
) -> ExecutionResult:
    """Run ``argv`` and return an :class:`ExecutionResult`.

    Captures stdout+stderr together (matching ``BashTool``'s expectation
    that tool output is a single byte stream). On timeout, kills the
    process tree and synthesises an exit code of ``124`` (the ``timeout(1)``
    convention) with the partial output collected so far.
    """
    log.debug("run: %s (cwd=%s, timeout=%s)", argv, cwd, timeout_sec)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        exit_code = int(proc.returncode or 0)
        return ExecutionResult(output=stdout or b"", exit_code=exit_code)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        # Drain whatever was buffered so the agent sees partial progress.
        try:
            partial = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            stdout = (partial[0] or b"") + b"\n[ari] command timed out\n"
        except Exception:
            stdout = b"[ari] command timed out (no output captured)\n"
        return ExecutionResult(output=stdout, exit_code=124)


__all__ = ["LocalComputer", "ApptainerComputer", "make_computer"]
