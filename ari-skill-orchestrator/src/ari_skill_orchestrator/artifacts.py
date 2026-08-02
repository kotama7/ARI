"""Closed, digest-verified artifact projection for one authorized run."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import ArtifactRefV1


MAX_INLINE_BYTES = 2 * 1024 * 1024
_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_SECRET_PART_RE = re.compile(
    r"(^|[._-])(secret|credential|token|password|passwd|private[-_]?key|api[-_]?key)([._-]|$)",
    re.IGNORECASE,
)
_BLOCKED_NAMES = frozenset(
    {
        ".env",
        "authorized_keys",
        "credentials",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "known_hosts",
        "netrc",
    }
)

_ROOT_FILES: dict[str, str] = {
    "experiment.md": "experiment-spec",
    "orchestrator.log": "execution-log",
    "results.json": "execution-results",
    "nodes_tree.json": "experiment-tree",
    "bfts_tree.json": "experiment-tree",
    "science_data.json": "science-data",
    "research_contract.json": "research-contract",
    "metric_contract.json": "metric-contract",
    "SKILLS.lock": "skills-lock",
    "experiment_section.tex": "paper-tex",
    "full_paper.tex": "paper-tex",
    "full_paper.pdf": "paper-pdf",
}


class ArtifactPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedArtifact:
    reference: ArtifactRefV1
    root: Path
    path: Path


def _open_regular(root: Path, path: Path) -> int:
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise ArtifactPolicyError("artifact escapes its run scope") from exc
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ArtifactPolicyError("artifact path is invalid")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(
        root,
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
        descriptor = os.open(parts[-1], flags, dir_fd=directory_fd)
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            os.close(descriptor)
            raise ArtifactPolicyError("artifact is not a regular file")
        return descriptor
    except OSError as exc:
        raise ArtifactPolicyError(
            "artifact path changed or contains a symlink"
        ) from exc
    finally:
        os.close(directory_fd)


def _fingerprint(root: Path, path: Path) -> tuple[str, int]:
    descriptor = _open_regular(root, path)
    digest = hashlib.sha256()
    try:
        before = os.fstat(descriptor)
        size = before.st_size
        consumed = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            consumed += len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        consumed != size
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        raise ArtifactPolicyError("artifact changed while being fingerprinted")
    return "sha256:" + digest.hexdigest(), size


def _read_bytes(root: Path, path: Path, *, max_bytes: int) -> bytes:
    descriptor = _open_regular(root, path)
    try:
        before = os.fstat(descriptor)
        if before.st_size > max_bytes:
            raise ArtifactPolicyError("artifact exceeds inline read limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    payload = b"".join(chunks)
    if len(payload) > max_bytes:
        raise ArtifactPolicyError("artifact grew beyond inline read limit")
    if after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
        raise ArtifactPolicyError("artifact changed while being read")
    return payload


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(part.lower() in _BLOCKED_NAMES for part in path.parts)
        or any(_SECRET_PART_RE.search(part) for part in path.parts)
    ):
        raise ArtifactPolicyError("artifact manifest contains an unsafe path")
    return path.as_posix()


def _closed_file(root: Path, relative: str) -> Path:
    relative = _safe_relative(relative)
    candidate = root / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise ArtifactPolicyError("artifact is missing, non-regular, or symbolic")
    try:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ArtifactPolicyError("artifact escapes its run scope") from exc
    if resolved != candidate.absolute():
        # Any symlink in a parent component is refused as well.
        raise ArtifactPolicyError("artifact path traverses a symbolic component")
    return candidate


def _media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _resolved(run_id: str, root: Path, path: Path, role: str) -> ResolvedArtifact:
    digest, size = _fingerprint(root, path)
    return ResolvedArtifact(
        reference=ArtifactRefV1(
            run_id=run_id,
            artifact_id=digest,
            digest=digest,
            role=role,
            media_type=_media_type(path),
            size_bytes=size,
        ),
        root=root,
        path=path,
    )


def _canonical_digest(value: Any, *, prefixed: bool = True) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    value = hashlib.sha256(payload).hexdigest()
    return "sha256:" + value if prefixed else value


def _published_artifacts(run_id: str, checkpoint: Path) -> list[ResolvedArtifact]:
    root = checkpoint / "ear_published"
    manifest_path = root / "manifest.lock"
    if root.is_symlink() or manifest_path.is_symlink() or not manifest_path.is_file():
        return []
    try:
        manifest = json.loads(
            _read_bytes(checkpoint, manifest_path, max_bytes=8 * 1024 * 1024).decode(
                "utf-8"
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactPolicyError("published EAR manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise ArtifactPolicyError("published EAR manifest must be an object")
    if (
        manifest.get("schema_version") != "ari.ear-manifest/v2"
        or manifest.get("version") != 2
    ):
        raise ArtifactPolicyError("published EAR requires manifest v2")
    records = manifest.get("files")
    if not isinstance(records, list):
        raise ArtifactPolicyError("published EAR manifest has no file records")
    if len(records) > 10_000:
        raise ArtifactPolicyError("published EAR manifest exceeds the record limit")
    rebuilt: list[dict[str, Any]] = []
    artifacts: list[ResolvedArtifact] = []
    declared: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ArtifactPolicyError("published EAR file record is invalid")
        relative = _safe_relative(str(record.get("path") or ""))
        if relative in declared:
            raise ArtifactPolicyError("published EAR manifest contains duplicate paths")
        declared.add(relative)
        path = _closed_file(root, relative)
        digest, size = _fingerprint(checkpoint, path)
        bare_digest = digest.removeprefix("sha256:")
        role = str(record.get("role") or "")
        if (
            not role
            or record.get("sha256") != bare_digest
            or record.get("size") != size
        ):
            raise ArtifactPolicyError("published EAR artifact integrity mismatch")
        rebuilt.append(
            {
                "path": relative,
                "sha256": bare_digest,
                "size": size,
                "role": role,
            }
        )
        artifacts.append(_resolved(run_id, checkpoint, path, role))
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ArtifactPolicyError("published EAR contains a symbolic path")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.lock"
    }
    if actual != declared:
        raise ArtifactPolicyError("published EAR contains untracked or missing files")
    canonical = {"version": 2, "files": sorted(rebuilt, key=lambda item: item["path"])}
    if _canonical_digest(canonical, prefixed=False) != manifest.get("bundle_sha256"):
        raise ArtifactPolicyError("published EAR bundle digest mismatch")
    deterministic_lock = {
        **canonical,
        "bundle_sha256": manifest.get("bundle_sha256"),
        "policy_digest": manifest.get("policy_digest"),
        "evidence_index_digest": manifest.get("evidence_index_digest"),
        "evidence": manifest.get("evidence"),
        "admission_status": manifest.get("admission_status"),
    }
    if _canonical_digest(deterministic_lock) != manifest.get("lock_digest"):
        raise ArtifactPolicyError("published EAR lock digest mismatch")
    artifacts.append(_resolved(run_id, checkpoint, manifest_path, "ear-manifest"))
    return artifacts


def _evidence_artifacts(run_id: str, checkpoint: Path) -> list[ResolvedArtifact]:
    root = checkpoint / "ear"
    index_path = root / "evidence.index.json"
    if root.is_symlink() or index_path.is_symlink() or not index_path.is_file():
        return []
    try:
        index = json.loads(
            _read_bytes(checkpoint, index_path, max_bytes=8 * 1024 * 1024).decode(
                "utf-8"
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactPolicyError("EAR evidence index is invalid") from exc
    if not isinstance(index, dict):
        raise ArtifactPolicyError("EAR evidence index must be an object")
    if index.get("schema_version") != "ari.ear-evidence-index/v1":
        raise ArtifactPolicyError("unsupported EAR evidence index")
    unsigned = dict(index)
    supplied_digest = unsigned.pop("index_digest", None)
    encoded = (
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    expected = "sha256:" + hashlib.sha256(encoded).hexdigest()
    if supplied_digest != expected:
        raise ArtifactPolicyError("EAR evidence index digest mismatch")
    artifacts: list[ResolvedArtifact] = []
    seen: set[str] = set()
    records = index.get("records") or []
    if not isinstance(records, list) or len(records) > 10_000:
        raise ArtifactPolicyError("EAR evidence records are invalid or excessive")
    for record in records:
        if not isinstance(record, dict):
            raise ArtifactPolicyError("EAR evidence record is invalid")
        relative = _safe_relative(str(record.get("path") or ""))
        if relative in seen:
            raise ArtifactPolicyError("EAR evidence index contains duplicate paths")
        seen.add(relative)
        path = _closed_file(root, relative)
        digest, size = _fingerprint(checkpoint, path)
        role = str(record.get("role") or "")
        if (
            not role
            or record.get("digest") != digest
            or record.get("size_bytes") != size
        ):
            raise ArtifactPolicyError("EAR evidence artifact integrity mismatch")
        artifacts.append(_resolved(run_id, checkpoint, path, role))
    artifacts.append(_resolved(run_id, checkpoint, index_path, "evidence-index"))
    return artifacts


def inventory(run_id: str, checkpoint: Path) -> list[ResolvedArtifact]:
    """Build a closed inventory; arbitrary checkpoint traversal is never performed."""

    if checkpoint.is_symlink() or not checkpoint.is_dir():
        raise ArtifactPolicyError("run checkpoint is missing or symbolic")
    output: list[ResolvedArtifact] = []
    for relative, role in sorted(_ROOT_FILES.items()):
        candidate = checkpoint / relative
        if candidate.exists() or candidate.is_symlink():
            output.append(
                _resolved(
                    run_id,
                    checkpoint,
                    _closed_file(checkpoint, relative),
                    role,
                )
            )
    output.extend(_evidence_artifacts(run_id, checkpoint))
    output.extend(_published_artifacts(run_id, checkpoint))
    unique: dict[tuple[str, str], ResolvedArtifact] = {}
    for item in output:
        key = (item.reference.artifact_id, item.reference.role)
        unique.setdefault(key, item)
    return sorted(
        unique.values(),
        key=lambda item: (item.reference.role, item.reference.artifact_id),
    )


def resolve(checkpoint: Path, run_id: str, artifact_id: str) -> ResolvedArtifact:
    if not _DIGEST_RE.fullmatch(artifact_id):
        raise ArtifactPolicyError("artifact_id must be a SHA-256 reference")
    matches = [
        item
        for item in inventory(run_id, checkpoint)
        if item.reference.artifact_id == artifact_id
    ]
    if not matches:
        raise ArtifactPolicyError("artifact is not admitted for this run")
    chosen = matches[0]
    if _fingerprint(chosen.root, chosen.path)[0] != artifact_id:
        raise ArtifactPolicyError("artifact changed after inventory")
    return chosen


def read_inline(checkpoint: Path, run_id: str, artifact_id: str) -> dict[str, Any]:
    item = resolve(checkpoint, run_id, artifact_id)
    size = item.reference.size_bytes
    if size > MAX_INLINE_BYTES:
        raise ArtifactPolicyError(
            f"artifact exceeds inline read limit ({size} > {MAX_INLINE_BYTES} bytes)"
        )
    payload = _read_bytes(item.root, item.path, max_bytes=MAX_INLINE_BYTES)
    if (
        "\x00" not in payload.decode("utf-8", errors="ignore")
        and item.reference.media_type != "application/pdf"
    ):
        try:
            content = payload.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            content = base64.b64encode(payload).decode("ascii")
            encoding = "base64"
    else:
        content = base64.b64encode(payload).decode("ascii")
        encoding = "base64"
    if "sha256:" + hashlib.sha256(payload).hexdigest() != artifact_id:
        raise ArtifactPolicyError("artifact changed while being read")
    return {
        "artifact": item.reference.model_dump(mode="json"),
        "encoding": encoding,
        "content": content,
    }


__all__ = [
    "MAX_INLINE_BYTES",
    "ArtifactPolicyError",
    "ResolvedArtifact",
    "inventory",
    "read_inline",
    "resolve",
]
