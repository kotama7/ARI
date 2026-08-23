"""Reviewed execution substrates for locked Harness requests."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Any

from ari.assurance.container_identity import read_binding
from ari.execution import ExecutionRequestV1, ExecutionResultV1, execute_local


class HarnessSubstrateError(RuntimeError):
    pass


#: What the container RUNTIME needs of the address space, on top of whatever the
#: verifier is given. RLIMIT_AS is set on the process the executor exec's, and
#: for a containerised harness that process is the runtime, not the verifier.
#:
#: MEASURED, eight launches per bound, nothing inside the container: 4 GiB never
#: started, 5 GiB started three times in eight, 6 GiB and 8 GiB started every
#: time. The requirement is NOT a fixed number -- the runtime's arena and thread
#: count vary per launch -- so this is set where it stopped varying rather than
#: at the lowest value ever observed to work. A tight allowance here buys
#: nothing and costs intermittent infrastructure failures.
CONTAINER_LAUNCHER_ADDRESS_SPACE = 6 * 1024**3


_LOGICAL_SIF_REFERENCE = re.compile(
    r"^(?P<runtime>apptainer|singularity):(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]{0,255}\.sif)$"
)


def _require_pinned_content(image: Path, pinned_content_digest: str | None) -> None:
    """Refuse an image that is not the CONTENT the manifest pinned.

    The manifest pins what is in the image, because that is what a verdict
    depends on and it is what survives the image being fetched again -- two
    pulls of one tag differ byte for byte and agree on every one of the 109,596
    filesystem entries that is not the runtime's own build-date metadata.

    Reading the whole rootfs on every run would cost more than the verification
    does, so the expensive comparison is made once by an operator and recorded
    in a site-local binding beside the image. What happens here is the cheap
    pair: the binding must vouch for the content the manifest names, and the
    file on disk must be the one the binding vouched for. A missing binding is
    refused rather than waved through -- an unbound image is one nobody has
    checked.
    """
    if not pinned_content_digest:
        raise HarnessSubstrateError(
            "the Harness container pin carries no content digest, so nothing "
            "identifies the image beyond the bytes it happened to arrive in")
    binding = read_binding(image.parent, image.name)
    if binding is None:
        raise HarnessSubstrateError(
            f"no site binding records what is inside {image.name}; run the "
            f"container binding tool against it before verifying with it")
    if binding.get("content_digest") != pinned_content_digest:
        raise HarnessSubstrateError(
            "the bound image is not the content this Harness pins")
    if binding.get("file_digest") != _file_digest(image):
        raise HarnessSubstrateError(
            f"{image.name} has changed since its content was established; the "
            f"binding no longer describes this file")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _resolve_sif_reference(reference: str) -> Path:
    """Resolve a public logical SIF identity through a private local root.

    Production manifests must not embed cluster paths or node names.  A plain
    path remains a compatibility input; new verified entries use
    ``apptainer:<name>.sif`` and require an administrator-supplied local root.
    """

    match = _LOGICAL_SIF_REFERENCE.fullmatch(reference)
    if match is None:
        return Path(reference)
    configured = os.environ.get("ARI_HARNESS_CONTAINER_ROOT", "").strip()
    if not configured:
        raise HarnessSubstrateError(
            "logical SIF reference requires ARI_HARNESS_CONTAINER_ROOT"
        )
    root = Path(configured)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise HarnessSubstrateError(
            "ARI_HARNESS_CONTAINER_ROOT must be an absolute real directory"
        )
    root = root.resolve(strict=True)
    image = root / match.group("name")
    if image.is_symlink():
        raise HarnessSubstrateError("logical SIF reference cannot resolve to a symlink")
    try:
        resolved = image.resolve(strict=True)
    except OSError as exc:
        raise HarnessSubstrateError("logical SIF image is unavailable") from exc
    if resolved.parent != root or not resolved.is_file():
        raise HarnessSubstrateError("logical SIF image escapes its private root")
    return resolved


class PinnedContainerExecutor:
    """Execute a request in an immutable Docker/Apptainer container.

    The candidate receives a read-only content-addressed copy of declared
    inputs, a read-only verifier package, no host workspace, no credentials,
    and a denied network namespace.  Container launch still goes through the
    canonical local executor for timeout, process-group, log, and resource
    handling.
    """

    def __init__(self, *, package_root: str | Path | None = None) -> None:
        self.package_root = Path(package_root or Path(__file__).resolve().parents[2])
        if self.package_root.is_symlink() or not self.package_root.is_dir():
            raise HarnessSubstrateError("ARI package root must be a real directory")

    def _snapshot_inputs(self, request: ExecutionRequestV1) -> tuple[Path, dict[str, str]]:
        digest = hashlib.sha256()
        for name, value in sorted(request.input_digests.items()):
            digest.update(name.encode("utf-8"))
            digest.update(value.encode("ascii"))
        relative_root = ".ari-assurance-inputs/" + digest.hexdigest()
        root = request.workspace.ensure_directory(relative_root)
        mapped: dict[str, str] = {}
        for name, expected in request.input_digests.items():
            payload = request.workspace.read_bytes(name, max_bytes=256 * 1024 * 1024)
            actual = "sha256:" + hashlib.sha256(payload).hexdigest()
            if actual != expected:
                raise HarnessSubstrateError(f"Harness input changed before snapshot: {name}")
            destination = root / (expected.removeprefix("sha256:") + "-" + Path(name).name)
            relative = destination.relative_to(request.workspace.root).as_posix()
            if destination.exists():
                if destination.is_symlink() or _file_digest(destination) != expected:
                    raise HarnessSubstrateError("content-addressed Harness snapshot mismatch")
            else:
                request.workspace.atomic_write_bytes(relative, payload)
                os.chmod(destination, 0o400)
            mapped[name] = "/ari/inputs/" + destination.name
        return root, mapped

    def _inside_argv(self, request: ExecutionRequestV1, mapped: dict[str, str]) -> list[str]:
        if request.argv is None:
            raise HarnessSubstrateError("Harness containers require argv, not a shell command")
        argv = list(request.argv)
        if not argv:
            raise HarnessSubstrateError("empty Harness argv")
        argv[0] = "python3" if Path(argv[0]).name.startswith("python") else argv[0]
        absolute_inputs = {
            str(Path(request.workspace.root) / name): destination
            for name, destination in mapped.items()
        }
        for index, value in enumerate(argv):
            path = Path(value)
            if path.is_absolute():
                try:
                    relative = path.resolve(strict=True).relative_to(self.package_root)
                except (OSError, ValueError):
                    pass
                else:
                    argv[index] = "/opt/ari-core/" + relative.as_posix()
            if value in mapped:
                argv[index] = mapped[value]
            elif value in absolute_inputs:
                argv[index] = absolute_inputs[value]
        if request.limits.memory_bytes is not None:
            # THE VERIFIER'S BOUND, ON THE VERIFIER.
            #
            # RLIMIT_AS is set on the process the executor exec's, which for a
            # containerised harness is the container RUNTIME, and is inherited
            # by whatever that runtime starts. One number was therefore bounding
            # two very different things, and the launcher's own appetite decided
            # it: at the 4 GiB a verifier was given, the runtime aborted in
            # pthread_create and the verifier never ran at all.
            #
            # Lowering it again inside the container gives the manifest's number
            # back its literal meaning. It is prepended AFTER the input mapping
            # so it cannot be mistaken for a path, and it appears in the argv
            # rather than being arranged out of band because the argv is what a
            # reviewer reads to see what was enforced -- the same reason the
            # network flags are there. A container without prlimit fails the
            # exec loudly rather than running the verifier unbounded.
            argv = ["prlimit", f"--as={request.limits.memory_bytes}", *argv]
        return argv

    def _container_argv(
        self,
        request: ExecutionRequestV1,
        snapshot_root: Path,
        inside: list[str],
    ) -> list[str]:
        container = request.container
        if container is None or container.resolution_status != "resolved" or not container.digest:
            raise HarnessSubstrateError("Harness container identity is not resolved")
        reference = container.reference
        if container.runtime == "docker":
            match = re.search(r"@sha256:([0-9a-f]{64})$", reference)
            if match is None or "sha256:" + match.group(1) != container.digest:
                raise HarnessSubstrateError("Docker Harness reference is not digest-pinned")
            if shutil.which("docker") is None:
                raise HarnessSubstrateError("docker executable is unavailable")
            return [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                str(request.limits.max_processes or 256),
                "--mount",
                f"type=bind,src={self.package_root},dst=/opt/ari-core,readonly",
                "--mount",
                f"type=bind,src={snapshot_root},dst=/ari/inputs,readonly",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=256m",
                "--env",
                "PYTHONPATH=/opt/ari-core",
                reference,
                *inside,
            ]
        if container.runtime in {"apptainer", "singularity"}:
            executable = shutil.which(container.runtime)
            image = _resolve_sif_reference(reference)
            if executable is None:
                raise HarnessSubstrateError(f"{container.runtime} executable is unavailable")
            if image.is_symlink() or not image.is_file():
                raise HarnessSubstrateError("SIF Harness image is unavailable")
            _require_pinned_content(image, container.digest)
            return [
                executable,
                "exec",
                "--containall",
                "--cleanenv",
                "--no-home",
                "--net",
                "--network",
                "none",
                "--bind",
                f"{self.package_root}:/opt/ari-core:ro",
                "--bind",
                f"{snapshot_root}:/ari/inputs:ro",
                "--env",
                "PYTHONPATH=/opt/ari-core",
                str(image),
                *inside,
            ]
        raise HarnessSubstrateError("unsupported pinned Harness container runtime")

    def _launcher_limits(self, limits):
        """What the OUTER process is held to: the verifier's bound plus the
        runtime's own allowance.

        The verifier is held to the manifest's number inside the container, so
        adding the launcher's allowance here does not loosen what the verifier
        gets -- it stops the launcher's appetite from deciding it.
        """
        if limits.memory_bytes is None:
            return limits
        return limits.model_copy(
            update={"memory_bytes": limits.memory_bytes + CONTAINER_LAUNCHER_ADDRESS_SPACE}
        )

    def __call__(
        self,
        request: ExecutionRequestV1,
        *,
        network_isolation_verified: bool = False,
    ) -> ExecutionResultV1:
        if request.network != "deny":
            raise HarnessSubstrateError("Harness request must deny network")
        snapshot_root, mapped = self._snapshot_inputs(request)
        inside = self._inside_argv(request, mapped)
        container_argv = self._container_argv(request, snapshot_root, inside)
        update: dict[str, Any] = {
            "argv": container_argv,
            "shell_command": None,
            "limits": self._launcher_limits(request.limits),
        }
        outer = request.model_copy(update=update)
        # Network isolation is proven by the reviewed argv above, not by a
        # caller-provided boolean.  execute_local remains the sole process and
        # resource-control implementation.
        result = execute_local(outer, network_isolation_verified=True)
        for name, expected in request.input_digests.items():
            if request.workspace.file_digest(name) != expected:
                raise HarnessSubstrateError(f"Harness input changed during execution: {name}")
        return result


__all__ = ["HarnessSubstrateError", "PinnedContainerExecutor"]
