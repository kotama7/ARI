"""Read-only Knowledge/Provider/Assurance dashboard projection.

The projection reads committed checkpoint JSON directly.  It never imports
the production registries, re-runs a resolver, or exposes an administrative
operation.  The three domains remain separate in both the wire shape and the
UI so the legacy ``ari-skill-*`` package name cannot blur their authority.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .checkpoint_finder import _resolve_checkpoint_dir


_MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
_MAX_NODE_RECORDS = 1_000


def _read_document(root: Path, relative: str, degraded: list[str]) -> dict[str, Any] | None:
    path = root.joinpath(*Path(relative).parts)
    try:
        if path.is_symlink() or not path.is_file():
            return None
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root.resolve(strict=True)):
            degraded.append(f"unsafe-path:{relative}")
            return None
        if resolved.stat().st_size > _MAX_DOCUMENT_BYTES:
            degraded.append(f"oversized:{relative}")
            return None
        value = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            degraded.append(f"not-object:{relative}")
            return None
        return value
    except (OSError, ValueError, json.JSONDecodeError):
        degraded.append(f"unreadable:{relative}")
        return None


def _node_documents(
    checkpoint: Path,
    filename: str,
    degraded: list[str],
) -> list[dict[str, Any]]:
    root = checkpoint / "rqgm" / "kca" / "nodes"
    if root.is_symlink() or not root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for node_dir in sorted(root.iterdir(), key=lambda item: item.name):
        if len(records) >= _MAX_NODE_RECORDS:
            degraded.append(f"truncated:{filename}")
            break
        if node_dir.is_symlink() or not node_dir.is_dir():
            continue
        value = _read_document(
            checkpoint,
            (node_dir / filename).relative_to(checkpoint).as_posix(),
            degraded,
        )
        if value is not None:
            records.append(value)
    return records


def _attestations(checkpoint: Path, degraded: list[str]) -> list[dict[str, Any]]:
    root = checkpoint / "rqgm" / "kca" / "nodes"
    if root.is_symlink() or not root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for node_dir in sorted(root.iterdir(), key=lambda item: item.name):
        attestation_dir = node_dir / "attestations"
        if attestation_dir.is_symlink() or not attestation_dir.is_dir():
            continue
        for path in sorted(attestation_dir.glob("*.json")):
            if len(records) >= _MAX_NODE_RECORDS:
                degraded.append("truncated:harness-attestations")
                return records
            value = _read_document(
                checkpoint, path.relative_to(checkpoint).as_posix(), degraded
            )
            if value is not None:
                records.append(value)
    return records


def _api_checkpoint_kca(checkpoint_id: str) -> dict[str, Any]:
    """GET ``/api/checkpoint/{id}/kca`` — separated, read-only K/C/A view."""

    checkpoint = _resolve_checkpoint_dir(checkpoint_id)
    if checkpoint is None:
        return {
            "schema_version": "ari.viz-kca/v1",
            "run_id": checkpoint_id,
            "present": False,
            "error": "checkpoint not found",
            "knowledge": {},
            "providers": {},
            "assurance": {},
            "degraded_reasons": [],
        }
    checkpoint = checkpoint.resolve(strict=True)
    degraded: list[str] = []
    prefix = "rqgm/kca/admission-v1/"
    admission = _read_document(checkpoint, prefix + "run_admission.json", degraded)

    knowledge_catalog = _read_document(
        checkpoint, prefix + "knowledge_catalog_snapshot.json", degraded
    )
    knowledge_lock = _read_document(
        checkpoint, prefix + "knowledge_skill_lock.json", degraded
    )
    provider_catalog = _read_document(
        checkpoint, prefix + "provider_catalog_snapshot.json", degraded
    )
    provider_lock = _read_document(
        checkpoint, prefix + "provider_lock.json", degraded
    )
    binding_lock = _read_document(
        checkpoint, prefix + "capability_binding_lock.json", degraded
    )
    verification = _read_document(
        checkpoint, prefix + "verification_contract.json", degraded
    )
    harness_catalog = _read_document(
        checkpoint, prefix + "harness_catalog_snapshot.json", degraded
    )
    harness_lock = _read_document(
        checkpoint, prefix + "baseline_harness_lock.json", degraded
    )

    return {
        "schema_version": "ari.viz-kca/v1",
        "run_id": checkpoint.name,
        "present": admission is not None,
        "modes": dict((admission or {}).get("modes") or {}),
        "knowledge": {
            "catalog_digest": (knowledge_catalog or {}).get("snapshot_digest"),
            "catalog_entries": (knowledge_catalog or {}).get("entries") or [],
            "active_lock_digest": (knowledge_lock or {}).get("lock_digest"),
            "active_skills": (knowledge_lock or {}).get("admitted") or [],
            "node_use_records": _node_documents(
                checkpoint, "node_knowledge_skill_use.json", degraded
            ),
        },
        "providers": {
            "catalog_digest": (provider_catalog or {}).get("snapshot_digest"),
            "catalog_entries": (provider_catalog or {}).get("providers") or [],
            "provider_lock_digest": (admission or {}).get("provider_lock_digest"),
            "locked_tools": (provider_lock or {}).get("tools") or [],
            "binding_lock_digest": (binding_lock or {}).get("lock_digest"),
            "bindings": (binding_lock or {}).get("bindings") or [],
            "unsatisfied": (binding_lock or {}).get("unsatisfied") or [],
        },
        "assurance": {
            "verification_contract_digest": (verification or {}).get("contract_digest"),
            "requirements": (verification or {}).get("requirements") or [],
            "catalog_digest": (harness_catalog or {}).get("snapshot_digest"),
            "catalog_entries": (harness_catalog or {}).get("manifests") or [],
            "baseline_lock_digest": (harness_lock or {}).get("lock_digest"),
            "active_harnesses": (harness_lock or {}).get("harnesses") or [],
            "unsatisfied_atom_digests": (
                (harness_lock or {}).get("unsatisfied_atom_digests") or []
            ),
            "attestations": _attestations(checkpoint, degraded),
        },
        "degraded_reasons": sorted(set(degraded)),
    }


__all__ = ["_api_checkpoint_kca"]
