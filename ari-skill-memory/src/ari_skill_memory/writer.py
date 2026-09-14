"""Immutable, artifact-verified research-memory writes."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from ari.public.memory import (
    MemoryArtifactRefV1,
    MemoryNodeReportRefV1,
    build_memory_record,
    canonical_memory_digest,
)

from .schemas import MEMORY_KINDS, REPRO_STATUSES, ArtifactRef


_EVENT_SCHEMA = "ari.memory-event/v1"


def _sha256_relative_file(root: Path, relative_path: str) -> tuple[str, int]:
    """Hash a regular file through a no-symlink dirfd walk."""

    digest = hashlib.sha256()
    size = 0
    parts = PurePosixPath(relative_path).parts
    directory_fd = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        for component in parts[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            parts[-1],
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise OSError("memory artifact is not a regular file")
            while chunk := os.read(file_fd, 1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        finally:
            os.close(file_fd)
    finally:
        os.close(directory_fd)
    return "sha256:" + digest.hexdigest(), size


def _normalized_digest(value: str | None) -> str:
    raw = str(value or "")
    if raw and not raw.startswith("sha256:"):
        raw = "sha256:" + raw
    if len(raw) != 71:
        raise ValueError("memory artifact requires a complete SHA-256 digest")
    return raw


def _safe_relative_path(value: str) -> str:
    pure = PurePosixPath(value)
    if (
        not value
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError("memory artifact path must be safe and relative")
    return value


def _refs_payload(
    artifact_refs: list[ArtifactRef] | list[dict] | None,
    *,
    artifact_root: Path | None,
) -> list[MemoryArtifactRefV1]:
    out: list[MemoryArtifactRefV1] = []
    root = artifact_root.resolve(strict=True) if artifact_root is not None else None
    for item in artifact_refs or []:
        raw = item.to_dict() if isinstance(item, ArtifactRef) else dict(item)
        relative_path = _safe_relative_path(
            str(raw.get("relative_path") or raw.get("path") or "")
        )
        expected = _normalized_digest(raw.get("digest") or raw.get("sha256"))
        role = str(raw.get("role") or "unknown")
        if root is None:
            size = int(raw.get("size_bytes") or 0)
            status = "unverified"
        else:
            try:
                actual, size = _sha256_relative_file(root, relative_path)
            except OSError as exc:
                raise ValueError(
                    f"memory artifact is missing or unsafe: {relative_path}"
                ) from exc
            if actual != expected:
                raise ValueError(
                    f"memory artifact digest mismatch for {relative_path}: "
                    f"expected {expected}, got {actual}"
                )
            status = "verified"
        out.append(
            MemoryArtifactRefV1(
                relative_path=relative_path,
                digest=expected,
                size_bytes=size,
                role=role,
                integrity_status=status,
            )
        )
    return out


def _node_report_ref(value: dict | None) -> MemoryNodeReportRefV1 | None:
    if value is None:
        return None
    raw = dict(value)
    digest = raw.get("digest") or raw.get("sha256")
    if not digest:
        raise ValueError("node_report_ref requires its immutable digest")
    return MemoryNodeReportRefV1(
        run_id=str(raw.get("run_id") or ""),
        node_id=str(raw.get("node_id") or ""),
        digest=_normalized_digest(str(digest)),
    )


@contextmanager
def _event_lock(backend: Any) -> Iterator[tuple[Path, Any] | None]:
    cfg = getattr(backend, "cfg", None)
    root = getattr(cfg, "checkpoint_dir", None)
    if root is None:
        yield None
        return
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "memory_events.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield root / "memory_events.jsonl", lock
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _existing_event(path: Path, record_digest: str) -> dict | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    matched: dict | None = None
    for line_number, line in enumerate(lines, start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"memory event ledger is corrupt at line {line_number}"
            ) from exc
        if not isinstance(event, dict) or event.get("schema_version") != _EVENT_SCHEMA:
            raise ValueError(
                f"memory event ledger has an invalid event at line {line_number}"
            )
        claimed = event.get("event_digest")
        payload = {key: value for key, value in event.items() if key != "event_digest"}
        if claimed != canonical_memory_digest(payload):
            raise ValueError(
                f"memory event ledger digest mismatch at line {line_number}"
            )
        if event.get("record_digest") == record_digest:
            if matched is not None:
                raise ValueError(
                    "memory event ledger contains duplicate record events"
                )
            matched = event
    return matched


def _append_event(path: Path, event: dict) -> None:
    payload = (
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("memory event ledger append made no progress")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_record(backend: Any, record: Any) -> dict:
    metadata = {
        "memory_record": record.model_dump(mode="json"),
        "record_digest": record.record_digest,
        # Read-only projections retained for current consumers. The canonical
        # record above is always authoritative and cross-checked on retrieval.
        "type": record.kind,
        "mem_kind": record.kind,
        "metric_ptr": record.metric_ptr.model_dump(mode="json") if record.metric_ptr else None,
        "artifact_refs": [ref.model_dump(mode="json") for ref in record.artifact_refs],
        "node_report_ref": (
            record.node_report_ref.model_dump(mode="json") if record.node_report_ref else None
        ),
        "repro_target_id": record.repro_target_id,
        "repro_status": record.repro_status,
        "confidence": record.confidence,
    }
    with _event_lock(backend) as locked:
        existing = None
        if locked is not None:
            event_path, _ = locked
            existing = _existing_event(event_path, record.record_digest)
        # The event ledger is an audit log, not the storage authority. Always
        # exercise the backend's idempotent insert so a checkpoint restored or
        # administratively purged after an earlier event cannot return a stale
        # backend_entry_id without recreating the record.
        result = backend.add_memory(
            record.source_node_id,
            record.text,
            metadata,
            idempotency_key=record.record_digest,
        )
        if not result.get("ok", False):
            return result
        if locked is not None and existing is None:
            event = {
                "schema_version": _EVENT_SCHEMA,
                "record_digest": record.record_digest,
                "record_id": record.record_id,
                "source_run_id": record.source_run_id,
                "source_node_id": record.source_node_id,
                "backend_entry_id": result.get("id"),
            }
            event["event_digest"] = canonical_memory_digest(event)
            _append_event(event_path, event)
    return {
        **result,
        "record_id": record.record_id,
        "record_digest": record.record_digest,
        "deduplicated": bool(
            existing is not None or result.get("deduplicated", False)
        ),
    }


def add_typed_memory(
    backend: Any,
    node_id: str,
    kind: str,
    text: str,
    *,
    run_id: str,
    ancestor_ids: list[str],
    created_by_tool_ref: str,
    metric_ptr: dict | None = None,
    artifact_refs: list[ArtifactRef] | list[dict] | None = None,
    artifact_root: Path | None = None,
    node_report_ref: dict | None = None,
    extra: dict | None = None,
    attributes: dict | None = None,
) -> dict:
    """Validate, content-address, and idempotently append one record."""

    if kind not in MEMORY_KINDS:
        raise ValueError(f"unknown MemoryKind {kind!r}")
    extra = dict(extra or {})
    record = build_memory_record(
        kind=kind,
        text=text,
        source_run_id=run_id,
        source_node_id=node_id,
        ancestor_node_ids=list(ancestor_ids),
        artifact_refs=[
            ref.model_dump(mode="json")
            for ref in _refs_payload(artifact_refs, artifact_root=artifact_root)
        ],
        node_report_ref=(
            _node_report_ref(node_report_ref).model_dump(mode="json")
            if node_report_ref is not None
            else None
        ),
        metric_ptr=metric_ptr,
        confidence=extra.pop("confidence", None),
        repro_target_id=extra.pop("repro_target_id", None),
        repro_status=extra.pop("repro_status", None),
        created_by_tool_ref=created_by_tool_ref,
        attributes={**(attributes or {}), **extra},
    )
    return _write_record(backend, record)


def add_observation(
    backend: Any,
    node_id: str,
    text: str,
    *,
    run_id: str,
    ancestor_ids: list[str],
    created_by_tool_ref: str,
    attributes: dict | None = None,
) -> dict:
    return add_typed_memory(
        backend,
        node_id,
        "observation",
        text,
        run_id=run_id,
        ancestor_ids=ancestor_ids,
        created_by_tool_ref=created_by_tool_ref,
        attributes=attributes,
    )


def add_experiment_result(backend, node_id, text, **kw) -> dict:
    return add_typed_memory(backend, node_id, "experiment_result", text, **kw)


def add_failure_case(backend, node_id, text, **kw) -> dict:
    return add_typed_memory(backend, node_id, "failure_case", text, **kw)


def add_procedure_memory(backend, node_id, text, **kw) -> dict:
    return add_typed_memory(backend, node_id, "procedure", text, **kw)


def add_reflection(
    backend, node_id, text, *, confidence: float | None = None, **kw
) -> dict:
    extra = kw.pop("extra", None) or {}
    if confidence is not None:
        extra["confidence"] = confidence
    return add_typed_memory(backend, node_id, "reflection", text, extra=extra, **kw)


def add_reproducibility_event(
    backend,
    node_id: str,
    target_memory_id: str,
    status: str,
    *,
    artifact_refs: list[ArtifactRef] | list[dict] | None = None,
    text: str | None = None,
    **kw,
) -> dict:
    if status not in REPRO_STATUSES:
        raise ValueError(f"unknown ReproStatus {status!r}")
    body = text or f"reproducibility: {target_memory_id} -> {status}"
    return add_typed_memory(
        backend,
        node_id,
        "reproducibility_event",
        body,
        artifact_refs=artifact_refs,
        extra={"repro_target_id": target_memory_id, "repro_status": status},
        **kw,
    )
