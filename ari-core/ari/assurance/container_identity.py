"""Identify a Harness container by what is in it, not by the bytes it arrived in.

WHY THIS EXISTS. A manifest pinned its container by the SHA-256 of the SIF file.
That file is not reproducible: pulling the same image twice produces two
different files, so an image that had to be re-obtained could not satisfy the pin
that named it, and re-pinning meant re-registering every harness and collecting a
human signature again. That is a large, recurring cost for a change that alters
nothing a verdict depends on.

WHAT IS ACTUALLY STABLE. Measured on two independent pulls of one tag: the SIF
files differ, the squashfs partitions differ, and of the 109,597 filesystem
entries inside them exactly ONE differs -- ``.singularity.d/labels.json``, which
the container runtime writes at build time and which records the build date. All
109,596 others match in content, mode and size.

So the rootfs is the stable identity, and this module digests it: every entry's
path, mode, and either its content digest, its symlink target, or its kind, in a
fixed order. The one runtime-written metadata file is excluded by name and the
exclusion is recorded in the binding, so a reader sees exactly what the digest
does not cover. Nothing else is excluded -- in particular ``.singularity.d/env``
stays in, because those scripts are sourced on every exec and a change to them
changes what runs.

WHAT IT COSTS, AND THE BINDING. Computing it means reading the whole rootfs,
which is far too slow to do on every verification run. So it is computed once per
image, by an operator, and recorded in a SITE-LOCAL binding beside the image:
this file, with these bytes, was found to carry that content. Verification then
checks the cheap thing (the file's bytes against the binding) and the meaningful
thing (the binding's content digest against the manifest's pin). Re-obtaining an
image is a new binding; it is not a new registration.

The extraction is done from the host with ``unsquashfs``. Nothing inside the
image is executed to compute its own identity, because an image that describes
itself is not evidence about itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

#: Written by the container runtime when it builds the SIF, not part of the
#: image. It is the ONE entry that differs between two pulls of one tag, and it
#: differs because it records the build date. It is data, never executed.
RUNTIME_WRITTEN_METADATA = (".singularity.d/labels.json",)

#: Where the squashfs payload starts in a SIF built by the runtimes we launch.
#: Read from the SIF rather than assumed; this is only the fallback.
_DEFAULT_SQUASHFS_OFFSET = 36864

#: The name of the site-local binding file, kept beside the images it describes.
BINDING_FILE = ".ari-container-bindings.json"


class ContainerIdentityError(RuntimeError):
    """The image's content identity could not be established."""


def _squashfs_offset(image: Path) -> int:
    """Where the filesystem partition begins, from the SIF's own descriptor list."""
    try:
        listing = subprocess.run(
            ["singularity", "sif", "list", str(image)],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return _DEFAULT_SQUASHFS_OFFSET
    if listing.returncode != 0:
        return _DEFAULT_SQUASHFS_OFFSET
    for line in listing.stdout.splitlines():
        if "FS (Squashfs" not in line:
            continue
        for field in line.split("|"):
            if "-" in field and field.strip().split("-")[0].strip().isdigit():
                return int(field.strip().split("-")[0].strip())
    return _DEFAULT_SQUASHFS_OFFSET


def _entries(root: Path) -> list[tuple[str, str, str, str]]:
    root = root.resolve()
    excluded = set(RUNTIME_WRITTEN_METADATA)
    out: list[tuple[str, str, str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            path = Path(dirpath) / name
            relative = path.relative_to(root).as_posix()
            if relative in excluded:
                continue
            status = path.lstat()
            mode = oct(status.st_mode)
            if path.is_symlink():
                out.append((relative, mode, "link", os.readlink(path)))
            elif path.is_dir():
                out.append((relative, mode, "dir", ""))
            elif path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1 << 20), b""):
                        digest.update(chunk)
                out.append((relative, mode, str(status.st_size), digest.hexdigest()))
            else:
                out.append((relative, mode, "special", ""))
    return out


def rootfs_content_digest(image: Path, *, work_dir: Path | None = None) -> tuple[str, int]:
    """The image's content identity, and how many entries it covers.

    Extracts the filesystem payload with ``unsquashfs`` and digests the result.
    Slow by construction -- it reads everything -- which is why the result is
    bound to the file once rather than recomputed per run.
    """
    image = Path(image).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="ari-container-identity-",
                                     dir=str(work_dir) if work_dir else None) as scratch:
        target = Path(scratch) / "rootfs"
        extraction = subprocess.run(
            ["unsquashfs", "-o", str(_squashfs_offset(image)), "-d", str(target),
             "-no-progress", str(image)],
            capture_output=True, text=True, timeout=7200)
        if extraction.returncode != 0 or not target.is_dir():
            raise ContainerIdentityError(
                f"could not read the image filesystem: "
                f"{(extraction.stderr or extraction.stdout).strip()[-400:]}")
        entries = _entries(target)
        if not entries:
            raise ContainerIdentityError("the image filesystem is empty")
        body = hashlib.sha256()
        for entry in entries:
            body.update(("\x00".join(entry) + "\n").encode("utf-8", "surrogateescape"))
        return "sha256:" + body.hexdigest(), len(entries)


def file_digest(image: Path) -> str:
    digest = hashlib.sha256()
    with Path(image).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 22), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def binding_path(container_root: Path) -> Path:
    return Path(container_root) / BINDING_FILE


def read_binding(container_root: Path, image_name: str) -> dict[str, Any] | None:
    """The binding for one image file, keyed by the name the reference resolves to."""
    path = binding_path(container_root)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = (document.get("bindings") or {}).get(image_name)
    return entry if isinstance(entry, dict) else None


def write_binding(container_root: Path, *, image: Path,
                  content_digest: str, entry_count: int) -> dict[str, Any]:
    """Record that this file, with these bytes, was found to carry that content.

    Site-local: it names a local file, so it belongs beside the image and never
    in a published manifest.
    """
    path = binding_path(Path(container_root))
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        document = {"schema_version": "ari.container-binding/v1", "bindings": {}}
    entry = {
        "file_digest": file_digest(image),
        "content_digest": content_digest,
        "entry_count": entry_count,
        "excluded_paths": list(RUNTIME_WRITTEN_METADATA),
    }
    document.setdefault("bindings", {})[Path(image).name] = entry
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)
    return entry


__all__ = [
    "BINDING_FILE",
    "ContainerIdentityError",
    "RUNTIME_WRITTEN_METADATA",
    "binding_path",
    "file_digest",
    "read_binding",
    "rootfs_content_digest",
    "write_binding",
]
