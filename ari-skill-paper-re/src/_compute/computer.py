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

* Network revocation is fail-closed. Apptainer commands switch to an isolated
  network namespace. Local execution rejects revocation unless an operator
  explicitly attests that the host/allocation is already network isolated.

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
import re
import signal
import shlex
import shutil
from pathlib import Path
from typing import Sequence

import _vendor_path  # noqa: F401  (ensures vendor on sys.path)

from ari.public.execution import WorkspaceRefV1

from nanoeval.solvers.computer_tasks.code_execution_interface import (
    ComputerInterface,
    ExecutionResult,
)

log = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_SEC = 60 * 30  # 30 min per shell command (matches PaperBench tools)
_MAX_TRANSFER_BYTES = 1024**3
_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


# ─── helpers ─────────────────────────────────────────────────────────────


def _agent_environment(work_dir: Path, explicit: dict[str, str] | None) -> dict[str, str]:
    """Build a deterministic environment without copying parent secrets."""

    home = work_dir / ".ari_home"
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    environment = {
        "HOME": str(home),
        "LOGNAME": "ari-agent",
        "USER": "ari-agent",
        "SHELL": "/bin/bash",
        "TERM": "dumb",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    for name, value in (explicit or {}).items():
        if (
            not _ENV_NAME_RE.fullmatch(name)
            or not isinstance(value, str)
            or "\x00" in value
        ):
            raise ValueError(f"invalid explicit agent environment entry: {name!r}")
        environment[name] = value
    return environment


def _immutable_apptainer_image(reference: str) -> str:
    """Return a canonical immutable SIF/ref or reject a mutable image tag."""

    path = Path(reference).expanduser()
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError("Apptainer image must be a regular non-symlink file")
        return str(path.resolve(strict=True))
    marker = "@sha256:"
    if marker not in reference:
        raise ValueError(
            "remote Apptainer image must be pinned with @sha256:<digest>; "
            "prefer a local immutable SIF"
        )
    digest = reference.rsplit(marker, 1)[1]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("Apptainer image digest is invalid")
    return reference


def _workspace(work_dir: Path | str) -> tuple[Path, WorkspaceRefV1]:
    path = Path(work_dir)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("work_dir must be a real directory")
    resolved = path.resolve(strict=True)
    return resolved, WorkspaceRefV1(root=str(resolved))


# ─── LocalComputer ───────────────────────────────────────────────────────


def _install_apply_patch_command(work_dir: Path, env: dict[str, str]) -> Path | None:
    """Expose an ``apply_patch`` / ``applypatch`` command on PATH, mirroring the
    vendor's ``Dockerfile.base`` (``COPY apply_patch.py`` → ``/bin/apply_patch``
    wrapper). gpt-5 / codex agents reflexively edit files via
    ``apply_patch <<'PATCH' … PATCH`` even with no such instruction in any
    prompt; the vendor's Docker image provides the command, but ARI's host-side
    :class:`LocalComputer` never builds that image, so each such call dies with
    ``command not found`` and the agent burns tool-call budget before falling
    back to ``cat``-heredoc (observed in SC41406 v3-A11: 7/8 applypatch calls
    failed). Reuse the vendor's own ``apply_patch.py`` (reads the patch from
    stdin) so behaviour matches the container exactly. Returns the bin dir to
    prepend to PATH, or ``None`` if the vendor module is not importable (caller
    leaves PATH untouched and the agent's cat-heredoc fallback still works).
    """
    import importlib.util
    import sys

    try:
        spec = importlib.util.find_spec("paperbench.solvers.apply_patch")
        ap_py = spec.origin if spec and spec.origin else None
    except Exception:  # noqa: BLE001
        ap_py = None
    if not ap_py or not Path(ap_py).is_file():
        return None
    bindir = work_dir / ".ari_bin"
    try:
        bindir.mkdir(parents=True, exist_ok=True)
        wrapper = bindir / "apply_patch"
        wrapper.write_text(
            "#!/usr/bin/env bash\n"
            f"exec {shlex.quote(sys.executable)} {shlex.quote(ap_py)} \"$@\"\n"
        )
        wrapper.chmod(0o755)
        # codex/gpt-5 sometimes emit the concatenated name ``applypatch``.
        alias = bindir / "applypatch"
        if alias.exists() or alias.is_symlink():
            alias.unlink()
        alias.write_text(wrapper.read_text())
        alias.chmod(0o755)
    except OSError as e:  # noqa: BLE001
        log.warning("could not install apply_patch shim in %s: %s", bindir, e)
        return None
    return bindir


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
        network_isolation_attested: bool = False,
    ) -> None:
        self.work_dir, self.workspace = _workspace(work_dir)
        self.env = _agent_environment(self.work_dir, env)
        # Provide the vendor's apply_patch command on PATH (the Docker image
        # installs it at /bin/apply_patch; this host-side sandbox does not).
        _ap_bin = _install_apply_patch_command(self.work_dir, self.env)
        if _ap_bin is not None:
            self.env["PATH"] = f"{_ap_bin}{os.pathsep}{self.env.get('PATH', '')}"
            log.info("LocalComputer: apply_patch/applypatch on PATH via %s", _ap_bin)
        self.timeout_sec = timeout_sec
        self.network_isolation_attested = network_isolation_attested
        self.network_disabled = False
        self._stopped = False

    async def disable_internet(self) -> None:
        if not self.network_isolation_attested:
            raise RuntimeError(
                "LocalComputer cannot enforce network revocation; use "
                "ApptainerComputer or an administrator-attested isolated host"
            )
        self.network_disabled = True

    async def upload(self, file: bytes, destination: str) -> None:
        if self._stopped:
            raise RuntimeError("computer stopped")
        if len(file) > _MAX_TRANSFER_BYTES:
            raise ValueError("upload exceeds the 1 GiB transfer limit")
        self.workspace.atomic_write_bytes(destination, file)

    async def download(self, file: str) -> bytes:
        if self._stopped:
            raise RuntimeError("computer stopped")
        return self.workspace.read_bytes(file, max_bytes=_MAX_TRANSFER_BYTES)

    async def send_shell_command(
        self,
        cmd: str,
        *,
        idempotent: bool = False,
    ) -> ExecutionResult:
        if self._stopped:
            raise RuntimeError("computer stopped")
        return await _run_subprocess(
            argv=["bash", "--noprofile", "--norc", "-c", cmd],
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
                    "neither apptainer nor singularity is on PATH; "
                    "install one or use LocalComputer instead"
                )
        self.work_dir, self.workspace = _workspace(work_dir)
        self.image = _immutable_apptainer_image(image)
        self.runner = runner
        agent_environment = _agent_environment(self.work_dir, env)
        self.env = dict(agent_environment)
        for name, value in agent_environment.items():
            container_value = "/work/.ari_home" if name == "HOME" else value
            self.env[f"APPTAINERENV_{name}"] = container_value
        self.extra_binds = list(extra_binds)
        if any("\x00" in binding for binding in self.extra_binds):
            raise ValueError("extra bind contains a NUL byte")
        self.timeout_sec = timeout_sec
        self.network_disabled = False
        self._stopped = False

    async def disable_internet(self) -> None:
        self.network_disabled = True
        probe = await self.send_shell_command("true")
        if probe.exit_code != 0:
            self.network_disabled = False
            raise RuntimeError(
                "Apptainer could not establish an isolated network namespace"
            )

    async def upload(self, file: bytes, destination: str) -> None:
        if self._stopped:
            raise RuntimeError("computer stopped")
        if len(file) > _MAX_TRANSFER_BYTES:
            raise ValueError("upload exceeds the 1 GiB transfer limit")
        self.workspace.atomic_write_bytes(destination, file)

    async def download(self, file: str) -> bytes:
        if self._stopped:
            raise RuntimeError("computer stopped")
        return self.workspace.read_bytes(file, max_bytes=_MAX_TRANSFER_BYTES)

    async def send_shell_command(
        self,
        cmd: str,
        *,
        idempotent: bool = False,
    ) -> ExecutionResult:
        if self._stopped:
            raise RuntimeError("computer stopped")
        argv = [
            self.runner,
            "exec",
            "--cleanenv",
            "--containall",
            "--no-home",
        ]
        if self.network_disabled:
            argv += ["--net", "--network", "none"]
        argv += ["--bind", f"{self.work_dir}:/work:rw", "--pwd", "/work"]
        for binding in self.extra_binds:
            argv += ["--bind", binding]
        argv += [
            self.image,
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            cmd,
        ]
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
    network_isolation_attested: bool = False,
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
        return LocalComputer(
            work_dir,
            env=env,
            timeout_sec=timeout_sec,
            network_isolation_attested=network_isolation_attested,
        )
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
        start_new_session=True,
    )
    communicate_task = asyncio.create_task(proc.communicate())
    try:
        stdout, _ = await asyncio.wait_for(
            asyncio.shield(communicate_task), timeout=timeout_sec
        )
        exit_code = int(proc.returncode or 0)
        await _terminate_process_group(proc)
        return ExecutionResult(output=stdout or b"", exit_code=exit_code)
    except asyncio.TimeoutError:
        await _terminate_process_group(proc)
        try:
            partial = await asyncio.wait_for(
                asyncio.shield(communicate_task), timeout=5.0
            )
            stdout = (partial[0] or b"") + b"\n[ari] command timed out\n"
        except Exception:
            stdout = b"[ari] command timed out (no output captured)\n"
        return ExecutionResult(output=stdout, exit_code=124)
    except asyncio.CancelledError:
        await _terminate_process_group(proc)
        try:
            await asyncio.wait_for(asyncio.shield(communicate_task), timeout=5.0)
        except Exception:
            communicate_task.cancel()
        raise


async def _terminate_process_group(proc: asyncio.subprocess.Process) -> None:
    """Terminate the complete command process group, including descendants."""

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        pass
    await asyncio.sleep(0)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


__all__ = ["LocalComputer", "ApptainerComputer", "make_computer"]
