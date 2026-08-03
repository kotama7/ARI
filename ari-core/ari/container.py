"""Unified container runtime abstraction.

Detects Docker (local) or Singularity/Apptainer (HPC), provides image pull
and command execution helpers, and refuses an implicit host fallback when a
configured runtime cannot be honored.
"""

from __future__ import annotations

import glob as _glob
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path as _Path
from typing import Literal as _Literal
from typing import Optional

from ari.execution import (
    ExecutionLimitsV1 as _ExecutionLimitsV1,
    ExecutionRequestV1 as _ExecutionRequestV1,
    WorkspaceRefV1 as _WorkspaceRefV1,
    build_minimal_environment as _build_minimal_environment,
    execute_local as _execute_local,
)

# ── Fail-safe: process sandbox ──────────────────────────
# RLIMIT_NPROC is per real-uid, not per process: capping the child also counts
# every existing task of the same user, so a 1024 cap fires fork EAGAIN as soon
# as the user already has >1024 threads anywhere (VSCode, Letta, BFTS workers,
# …). Only honor the cap when the operator explicitly opts in via
# ARI_MAX_CHILD_PROCS.
_MAX_CHILD_PROCS_ENV = os.environ.get("ARI_MAX_CHILD_PROCS", "").strip()
_MAX_CHILD_PROCS: int | None = (
    int(_MAX_CHILD_PROCS_ENV) if _MAX_CHILD_PROCS_ENV else None
)


# ── Runtime detection ────────────────────────────────


def _cmd_ok(cmd: list[str], timeout: int = 10) -> Optional[str]:
    """Run *cmd* and return stdout if exit-code == 0, else ``None``."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


_shell_cache: dict[tuple[str, str], str] = {}


def _detect_container_shell(mode: str, image_ref: str) -> str:
    """Return ``"bash"`` if the image provides bash, else ``"sh"`` (cached per image).

    Defaults to ``"bash"``: nearly every image used for ML/HPC work ships bash,
    and when it is missing the shell invocation fails loudly rather than
    silently downgrading. Only falls back to ``"sh"`` when a probe explicitly
    reports ``sh``.
    """
    key = (mode, image_ref)
    if key in _shell_cache:
        return _shell_cache[key]
    shell = "bash"
    probe_cmd: list[str] | None = None
    if mode == "docker":
        # `docker exec` targets a running container, not an image — use `run --rm`.
        probe_cmd = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            image_ref,
            "sh",
            "-c",
            "command -v bash >/dev/null 2>&1 && echo bash || echo sh",
        ]
    elif mode in ("singularity", "apptainer"):
        probe_cmd = [
            mode,
            "exec",
            "--cleanenv",
            "--containall",
            "--net",
            "--network",
            "none",
            image_ref,
            "sh",
            "-c",
            "command -v bash >/dev/null 2>&1 && echo bash || echo sh",
        ]
    if probe_cmd is not None:
        try:
            probe = subprocess.run(
                probe_cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if probe.returncode == 0 and probe.stdout.strip() == "sh":
                shell = "sh"
        except Exception:
            pass
    _shell_cache[key] = shell
    return shell


def detect_runtime() -> str:
    """Return the best available container runtime.

    Returns one of ``"docker"``, ``"singularity"``, ``"apptainer"``, or
    ``"none"``.  On HPC (``SLURM_JOB_ID`` present) Singularity / Apptainer
    is preferred over Docker.
    """
    on_hpc = bool(os.environ.get("SLURM_JOB_ID"))

    have_docker = (
        shutil.which("docker") is not None and _cmd_ok(["docker", "info"]) is not None
    )
    have_singularity = (
        shutil.which("singularity") is not None
        and _cmd_ok(["singularity", "--version"]) is not None
    )
    have_apptainer = (
        shutil.which("apptainer") is not None
        and _cmd_ok(["apptainer", "--version"]) is not None
    )

    if on_hpc:
        if have_apptainer:
            return "apptainer"
        if have_singularity:
            return "singularity"
        if have_docker:
            return "docker"
    else:
        if have_docker:
            return "docker"
        if have_apptainer:
            return "apptainer"
        if have_singularity:
            return "singularity"

    return "none"


# ── Configuration dataclass ──────────────────────────


@dataclass
class ContainerConfig:
    """Configuration for container execution."""

    image: str = ""  # e.g. "ghcr.io/kotama7/ari:latest"
    mode: str = "auto"  # auto | docker | singularity | apptainer | none
    pull: str = "on_start"  # always | on_start | never
    extra_args: list[str] = field(default_factory=list)


# ── Image reference resolution ───────────────────────


def _resolve_singularity_ref(image: str) -> str:
    """Resolve *image* to a string that ``singularity exec`` can consume.

    Accepts three kinds of values:
      * An explicit scheme (``docker://``, ``library://``, ``oras://``, …) — returned as-is.
      * A local SIF path (absolute, relative, or a bare ``*.sif`` filename
        discoverable under ``./containers`` or the process cwd) — returned as a filesystem path.
      * A ``repo:tag``-style Docker reference — returned with ``docker://`` prefix.
    """
    if "://" in image:
        return image

    # Direct path (absolute or relative) that exists on disk.
    if os.path.isfile(image):
        return image

    # Bare SIF filename: search standard locations.
    if image.endswith(".sif"):
        search_dirs: list[str] = []
        env_dir = os.environ.get("ARI_CONTAINERS_DIR", "")
        if env_dir:
            search_dirs.append(env_dir)
        search_dirs.extend(
            [
                os.path.join(os.getcwd(), "containers"),
                os.getcwd(),
                os.path.expanduser("~/containers"),
            ]
        )
        # Walk up from cwd looking for a ``containers/`` sibling — covers the
        # case where MCP skills are invoked from an experiment workdir nested
        # several levels below the ARI project root.
        _cur = os.path.abspath(os.getcwd())
        for _ in range(8):
            search_dirs.append(os.path.join(_cur, "containers"))
            _parent = os.path.dirname(_cur)
            if _parent == _cur:
                break
            _cur = _parent
        # Finally, the ARI package itself lives at <repo>/ari-core/ari/, so
        # three levels up is the canonical ``<repo>/containers``.
        _pkg_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        search_dirs.append(os.path.join(_pkg_root, "containers"))

        seen: set[str] = set()
        for d in search_dirs:
            if not d or d in seen:
                continue
            seen.add(d)
            candidate = os.path.join(d, image)
            if os.path.isfile(candidate):
                return candidate
        # Fall through — let singularity emit its own error rather than
        # silently rewriting a SIF filename into a docker:// pull.
        return image

    return f"docker://{image}"


# ── Image pulling ────────────────────────────────────


def pull_image(config: ContainerConfig) -> bool:
    """Pull the container image.  Returns ``True`` on success."""
    if not config.image:
        return False

    mode = config.mode
    if mode == "auto":
        mode = detect_runtime()

    if mode == "docker":
        r = subprocess.run(
            ["docker", "pull", config.image],
            capture_output=True,
            text=True,
            timeout=600,
        )
        return r.returncode == 0

    if mode in ("singularity", "apptainer"):
        exe = mode  # singularity or apptainer
        # If the configured image is already a local SIF file, nothing to pull.
        if _resolve_singularity_ref(config.image) == config.image and (
            os.path.isfile(config.image) or config.image.endswith(".sif")
        ):
            return os.path.isfile(_resolve_singularity_ref(config.image))
        os.makedirs("containers", exist_ok=True)
        # Derive a stable filename (repo_tag.sif) so list_images() can find it.
        _name = config.image.rsplit("/", 1)[-1].replace(":", "_")
        if not _name.endswith(".sif"):
            _name = f"{_name}.sif"
        out_path = os.path.join("containers", _name)
        r = subprocess.run(
            [exe, "pull", "--force", out_path, f"docker://{config.image}"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        return r.returncode == 0

    return False


# ── Run inside container ─────────────────────────────


def run_in_container(
    config: ContainerConfig,
    cmd: list[str],
    env: dict[str, str] | None = None,
    workdir: str = ".",
) -> subprocess.Popen:
    """Execute *cmd* inside the configured container (or directly).

    Returns a :class:`subprocess.Popen` handle.
    """
    mode = config.mode
    if mode == "auto":
        mode = detect_runtime() if config.image else "none"
    run_env = _build_minimal_environment(env)

    if mode == "none" or not config.image:
        return subprocess.Popen(
            cmd,
            env=run_env,
            cwd=workdir,
            start_new_session=True,
            close_fds=True,
        )

    workdir = os.path.abspath(workdir)

    if mode == "docker":
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{workdir}:{workdir}",
            "-w",
            workdir,
        ]
        if env:
            for k, v in env.items():
                docker_cmd.extend(["-e", f"{k}={v}"])
        docker_cmd.extend(config.extra_args)
        docker_cmd.append(config.image)
        docker_cmd.extend(cmd)
        return subprocess.Popen(
            docker_cmd, env=run_env, start_new_session=True, close_fds=True
        )

    if mode in ("singularity", "apptainer"):
        exe = mode
        # --writable-tmpfs lets the agent install missing tools (e.g.
        # `apk add git`, `apt-get install ...`) into a per-invocation
        # tmpfs overlay. The SIF itself stays immutable; changes vanish
        # at process exit. Without this flag the image is fully read-only
        # and the agent cannot recover from a missing-tool situation.
        sif_cmd = [exe, "exec", "--writable-tmpfs", "--bind", workdir]
        sif_cmd.extend(config.extra_args)
        sif_cmd.append(_resolve_singularity_ref(config.image))
        sif_cmd.extend(cmd)
        return subprocess.Popen(
            sif_cmd, env=run_env, start_new_session=True, close_fds=True
        )

    raise ValueError(f"unsupported container mode {mode!r}; refusing host fallback")


def _run_shell_sandboxed(
    cmd: str | list[str],
    *,
    shell: bool = False,
    timeout: int = 120,
    cwd: str | None = None,
) -> subprocess.CompletedProcess:
    """Compatibility adapter over the canonical execution contract."""

    workdir = _Path(cwd or ".").resolve(strict=True)
    if not workdir.is_dir():
        raise NotADirectoryError(workdir)
    common = {
        "workspace": _WorkspaceRefV1(root=str(workdir)),
        "timeout_seconds": timeout,
        "limits": _ExecutionLimitsV1(max_processes=_MAX_CHILD_PROCS),
    }
    if isinstance(cmd, str):
        if not shell:
            raise ValueError("string commands require explicit shell=True")
        request = _ExecutionRequestV1(shell_command=cmd, **common)
    else:
        request = _ExecutionRequestV1(argv=cmd, **common)
    result = _execute_local(request)
    logs: dict[str, str] = {}
    for artifact in result.artifacts:
        logs[artifact.logical_role] = (
            _Path(request.workspace.root) / artifact.relative_path
        ).read_text(encoding="utf-8", errors="replace")
    if result.status == "timed_out":
        raise subprocess.TimeoutExpired(
            cmd,
            timeout,
            output=logs.get("stdout", ""),
            stderr=logs.get("stderr", ""),
        )
    return subprocess.CompletedProcess(
        cmd,
        result.exit_code if result.exit_code is not None else -1,
        logs.get("stdout", ""),
        logs.get("stderr", ""),
    )


def run_shell_in_container(
    config: ContainerConfig,
    shell_cmd: str,
    *,
    cwd: str | None = None,
    timeout: int = 120,
    network: _Literal["inherit", "deny"] = "inherit",
) -> subprocess.CompletedProcess:
    """Run a shell command string inside the container (blocking).

    This is the high-level helper for MCP ``run_bash``: it accepts the same
    ``shell=True`` style command string, wraps it in the container when
    configured, and returns a :class:`subprocess.CompletedProcess`.

    All execution paths use process-group isolation: on timeout the entire
    descendant tree is killed via ``SIGKILL`` to the process group, preventing
    orphan / fork-bomb scenarios.

    When ``config.image`` is empty or mode resolves to ``"none"``, the
    command runs directly on the host.
    """
    full_cmd = container_shell_argv(
        config,
        shell_cmd,
        cwd=cwd,
        network=network,
    )
    if full_cmd is None:
        if network == "deny":
            raise ValueError(
                "network denial requires a container; refusing host fallback"
            )
        return _run_shell_sandboxed(
            shell_cmd,
            shell=True,
            timeout=timeout,
            cwd=cwd,
        )
    return _run_shell_sandboxed(
        full_cmd,
        timeout=timeout,
        cwd=cwd,
    )


def container_shell_argv(
    config: ContainerConfig,
    shell_cmd: str,
    *,
    cwd: str | None = None,
    network: _Literal["inherit", "deny"] = "inherit",
) -> list[str] | None:
    """Build the exact container argv for a shell command.

    ``None`` means the configuration selects host execution.  Callers that
    require a container must treat that value as an error rather than silently
    weakening isolation.
    """

    workdir = os.path.abspath(cwd) if cwd else os.path.abspath(".")
    mode = config.mode
    if mode == "auto":
        mode = detect_runtime() if config.image else "none"
    if network == "deny" and any(
        argument == "--net"
        or argument.startswith("--network")
        or argument.startswith("--netns")
        for argument in config.extra_args
    ):
        raise ValueError(
            "container extra_args cannot override an explicit network denial"
        )

    if mode == "none" or not config.image:
        return None

    if mode == "docker":
        shell = _detect_container_shell("docker", config.image)
        full_cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{workdir}:{workdir}",
            "-w",
            workdir,
            *(["--network", "none"] if network == "deny" else []),
            *config.extra_args,
            config.image,
            shell,
            "-c",
            shell_cmd,
        ]
    elif mode in ("singularity", "apptainer"):
        image_ref = _resolve_singularity_ref(config.image)
        shell = _detect_container_shell(mode, image_ref)
        full_cmd = [
            mode,
            "exec",
            "--cleanenv",
            "--containall",
            "--writable-tmpfs",
            *(["--net", "--network", "none"] if network == "deny" else []),
            "--bind",
            workdir,
            *config.extra_args,
            image_ref,
            shell,
            "-c",
            shell_cmd,
        ]
    else:
        raise ValueError(f"unsupported container mode {mode!r}; refusing host fallback")
    return full_cmd


def config_from_env() -> ContainerConfig | None:
    """Build a ContainerConfig from ARI_CONTAINER_* environment variables.

    Returns ``None`` when no container image is configured.
    """
    image = os.environ.get("ARI_CONTAINER_IMAGE", "")
    if not image:
        return None
    mode = os.environ.get("ARI_CONTAINER_MODE", "auto")
    return ContainerConfig(image=image, mode=mode)


# ── Image listing ───────────────────────────────────


def list_images(mode: str = "auto") -> list[dict]:
    """Return locally available container images.

    Each entry is ``{"name": "<repo>:<tag>", "size": "<human-readable>"}``.
    """
    if mode == "auto":
        mode = detect_runtime()

    images: list[dict] = []

    if mode == "docker":
        out = _cmd_ok(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}"],
            timeout=15,
        )
        if out:
            for line in out.splitlines():
                parts = line.split("\t", 1)
                name = parts[0]
                if name == "<none>:<none>":
                    continue
                images.append(
                    {"name": name, "size": parts[1] if len(parts) > 1 else ""}
                )

    elif mode in ("singularity", "apptainer"):
        # Scan common SIF cache locations
        cache_dirs = [
            os.path.expanduser("~/.singularity/cache/oci-tmp"),
            os.path.expanduser("~/.apptainer/cache/oci-tmp"),
            os.environ.get("SINGULARITY_CACHEDIR", ""),
            os.environ.get("APPTAINER_CACHEDIR", ""),
        ]
        # Also scan current directory and ./containers for .sif files
        cache_dirs.append(".")
        cache_dirs.append("containers")
        # Repo-root-relative containers/ (server may run with cwd=ari-core)
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        cache_dirs.append(os.path.join(repo_root, "containers"))
        seen: set[str] = set()
        for d in cache_dirs:
            if not d or not os.path.isdir(d):
                continue
            for sif in _glob.glob(os.path.join(d, "*.sif")):
                basename = os.path.basename(sif)
                if basename in seen:
                    continue
                seen.add(basename)
                try:
                    sz = os.path.getsize(sif)
                    if sz >= 1 << 30:
                        size_str = f"{sz / (1 << 30):.1f} GB"
                    else:
                        size_str = f"{sz / (1 << 20):.0f} MB"
                except OSError:
                    size_str = ""
                images.append({"name": basename, "size": size_str})

    return images


# ── Info helper ──────────────────────────────────────


def get_container_info() -> dict:
    """Return runtime information for the GUI."""
    runtime = detect_runtime()
    version = ""
    if runtime == "docker":
        version = _cmd_ok(["docker", "--version"]) or ""
    elif runtime in ("singularity", "apptainer"):
        version = _cmd_ok([runtime, "--version"]) or ""

    return {
        "runtime": runtime,
        "version": version,
        "available": runtime != "none",
    }
