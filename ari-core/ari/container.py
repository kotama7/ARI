from __future__ import annotations
"""Unified container runtime abstraction.

Detects Docker (local) or Singularity/Apptainer (HPC), provides image pull
and command execution helpers.  Falls back to bare subprocess when no
container runtime is selected.
"""

import glob as _glob
import os
import signal
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional


# ── Fail-safe: process sandbox ──────────────────────────
_MAX_CHILD_PROCS = int(os.environ.get("ARI_MAX_CHILD_PROCS", "1024"))


def _sandbox_preexec() -> None:
    """Pre-exec hook: new process group + RLIMIT_NPROC cap."""
    os.setsid()
    try:
        import resource
        _soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
        cap = min(hard, _MAX_CHILD_PROCS)
        resource.setrlimit(resource.RLIMIT_NPROC, (cap, hard))
    except Exception:
        pass


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
            "docker", "run", "--rm", image_ref,
            "sh", "-c", "command -v bash >/dev/null 2>&1 && echo bash || echo sh",
        ]
    elif mode in ("singularity", "apptainer"):
        probe_cmd = [
            mode, "exec", image_ref,
            "sh", "-c", "command -v bash >/dev/null 2>&1 && echo bash || echo sh",
        ]
    if probe_cmd is not None:
        try:
            probe = subprocess.run(
                probe_cmd, capture_output=True, text=True, timeout=30,
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

    have_docker = shutil.which("docker") is not None and _cmd_ok(["docker", "info"]) is not None
    have_singularity = shutil.which("singularity") is not None and _cmd_ok(["singularity", "--version"]) is not None
    have_apptainer = shutil.which("apptainer") is not None and _cmd_ok(["apptainer", "--version"]) is not None

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
        search_dirs.extend([
            os.path.join(os.getcwd(), "containers"),
            os.getcwd(),
            os.path.expanduser("~/containers"),
        ])
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
        _pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
            capture_output=True, text=True, timeout=600,
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
            capture_output=True, text=True, timeout=600,
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

    run_env = dict(os.environ)
    if env:
        run_env.update(env)

    if mode == "none" or not config.image:
        return subprocess.Popen(cmd, env=run_env, cwd=workdir, preexec_fn=_sandbox_preexec)

    workdir = os.path.abspath(workdir)

    if mode == "docker":
        docker_cmd = ["docker", "run", "--rm", "-v", f"{workdir}:{workdir}", "-w", workdir]
        if env:
            for k, v in env.items():
                docker_cmd.extend(["-e", f"{k}={v}"])
        docker_cmd.extend(config.extra_args)
        docker_cmd.append(config.image)
        docker_cmd.extend(cmd)
        return subprocess.Popen(docker_cmd, env=run_env, preexec_fn=_sandbox_preexec)

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
        return subprocess.Popen(sif_cmd, env=run_env, preexec_fn=_sandbox_preexec)

    # Fallback — direct execution
    return subprocess.Popen(cmd, env=run_env, cwd=workdir, preexec_fn=_sandbox_preexec)


def _run_shell_sandboxed(
    cmd: str | list[str],
    *,
    shell: bool = False,
    timeout: int = 120,
    cwd: str | None = None,
) -> subprocess.CompletedProcess:
    """Run with process-group isolation. Kill entire tree on timeout."""
    proc = subprocess.Popen(
        cmd,
        shell=shell,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        preexec_fn=_sandbox_preexec,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout or "", stderr or "")
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.wait()
        raise


def run_shell_in_container(
    config: ContainerConfig,
    shell_cmd: str,
    *,
    cwd: str | None = None,
    timeout: int = 120,
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
    workdir = os.path.abspath(cwd) if cwd else os.path.abspath(".")
    mode = config.mode
    if mode == "auto":
        mode = detect_runtime() if config.image else "none"

    if mode == "none" or not config.image:
        return _run_shell_sandboxed(
            shell_cmd, shell=True, timeout=timeout, cwd=cwd,
        )

    # Build the container command that wraps the shell command
    if mode == "docker":
        shell = _detect_container_shell("docker", config.image)
        full_cmd = [
            "docker", "run", "--rm",
            "-v", f"{workdir}:{workdir}", "-w", workdir,
            *config.extra_args,
            config.image,
            shell, "-c", shell_cmd,
        ]
    elif mode in ("singularity", "apptainer"):
        image_ref = _resolve_singularity_ref(config.image)
        shell = _detect_container_shell(mode, image_ref)
        # --writable-tmpfs: see comment in run_in_container. Needed so the
        # agent can install missing tools (git, build-essentials, …)
        # without rebuilding the SIF.
        full_cmd = [
            mode, "exec", "--writable-tmpfs", "--bind", workdir,
            *config.extra_args,
            image_ref,
            shell, "-c", shell_cmd,
        ]
    else:
        # Unknown mode — fall back to sandboxed direct execution
        return _run_shell_sandboxed(
            shell_cmd, shell=True, timeout=timeout, cwd=cwd,
        )

    return _run_shell_sandboxed(
        full_cmd, timeout=timeout, cwd=cwd,
    )


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
                images.append({"name": name, "size": parts[1] if len(parts) > 1 else ""})

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
