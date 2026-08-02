"""Deterministic catalog builder, lock verifier, and review workflow."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from admission import AdmissionEngine, AdmissionPolicyV1, resolve_overlaps
from models import (
    AdmissionDecisionV1,
    AdmissionEvidenceV1,
    CanonicalToolDescriptorV1,
    CatalogIndexEntryV1,
    CatalogIndexV1,
    CatalogLockV1,
    QuarantinedCandidateV1,
    admission_rank,
    catalog_lock_digest,
    sanitize_text,
    sha256_digest,
)
from sources import CatalogCandidateV1, CatalogSource


CATALOG_LOCK_FILENAME = "CATALOG.lock"
CATALOG_INDEX_FILENAME = "catalog.index.json"
_MAX_LOCK_BYTES = 100_000_000
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._:+/-]*")


class CatalogError(RuntimeError):
    pass


class CatalogCorruptError(CatalogError):
    pass


class CatalogImmutableError(CatalogError):
    pass


@dataclass(frozen=True)
class CatalogBuildResult:
    lock: CatalogLockV1
    index: CatalogIndexV1


def _candidate_digest(candidate: CatalogCandidateV1) -> str:
    return sha256_digest(candidate.model_dump(mode="json"))


def _origin_problem(
    descriptor: CanonicalToolDescriptorV1,
    *,
    max_origin_depth: int,
) -> tuple[str, str] | None:
    for chain in descriptor.origin_chains:
        if len(chain) > max_origin_depth:
            return (
                "depth-exceeded",
                f"origin depth {len(chain)} exceeds {max_origin_depth}",
            )
        visited: set[tuple[str, str]] = set()
        for hop in chain:
            key = (hop.kind, hop.id)
            if key in visited:
                return ("cycle", f"origin chain repeats {hop.kind}:{hop.id}")
            visited.add(key)
        if not chain or chain[-1].kind != "tool":
            return ("hidden-leaf", "origin chain does not terminate in a tool")
        if chain[-1].id != descriptor.leaf_identity:
            return (
                "hidden-leaf",
                "origin leaf does not match descriptor leaf_identity",
            )
    return None


def _strongest_decision(
    engine: AdmissionEngine,
    descriptor: CanonicalToolDescriptorV1,
    evidences: list[AdmissionEvidenceV1],
) -> AdmissionDecisionV1:
    if not evidences:
        return engine.evaluate(descriptor, AdmissionEvidenceV1())
    decisions = [engine.evaluate(descriptor, evidence) for evidence in evidences]
    return max(
        decisions,
        key=lambda decision: (
            admission_rank(decision.level),
            decision.evidence_digest,
        ),
    )


async def build_catalog(
    sources: Iterable[CatalogSource],
    *,
    policy: AdmissionPolicyV1 | None = None,
    max_origin_depth: int = 16,
) -> CatalogBuildResult:
    """Sync sources once and build an immutable lock and derived index."""

    if max_origin_depth < 2:
        raise ValueError("max_origin_depth must be at least 2")
    engine = AdmissionEngine(policy)
    source_list = sorted(sources, key=lambda source: source.locked_source.source_id)
    source_ids = [source.locked_source.source_id for source in source_list]
    if len(source_ids) != len(set(source_ids)):
        raise CatalogError("duplicate catalog source_id values")

    accepted_candidates: list[CatalogCandidateV1] = []
    quarantined: list[QuarantinedCandidateV1] = []
    for source in source_list:
        source_id = source.locked_source.source_id
        try:
            candidates = await source.sync()
        except Exception as exc:
            detail = sanitize_text(f"{type(exc).__name__}: {exc}", limit=1_000)
            quarantined.append(
                QuarantinedCandidateV1(
                    source_id=source_id,
                    candidate_name="<source-sync>",
                    reason_code="source-failure",
                    detail=detail,
                    candidate_digest=sha256_digest(
                        {"source_id": source_id, "failure": detail}
                    ),
                )
            )
            continue
        for candidate in candidates:
            descriptor = candidate.descriptor
            if source_id not in descriptor.source_ids:
                quarantined.append(
                    QuarantinedCandidateV1(
                        source_id=source_id,
                        candidate_name=descriptor.name,
                        reason_code="descriptor-invalid",
                        detail="candidate does not name the source that produced it",
                        candidate_digest=_candidate_digest(candidate),
                    )
                )
                continue
            problem = _origin_problem(descriptor, max_origin_depth=max_origin_depth)
            if problem is not None:
                reason_code, detail = problem
                quarantined.append(
                    QuarantinedCandidateV1(
                        source_id=source_id,
                        candidate_name=descriptor.name,
                        reason_code=reason_code,  # type: ignore[arg-type]
                        detail=detail,
                        candidate_digest=_candidate_digest(candidate),
                    )
                )
                continue
            accepted_candidates.append(candidate)

    descriptors, overlaps = resolve_overlaps(
        candidate.descriptor for candidate in accepted_candidates
    )
    evidence_by_ref: dict[str, list[AdmissionEvidenceV1]] = {}
    for candidate in accepted_candidates:
        evidence_by_ref.setdefault(candidate.descriptor.tool_ref, []).append(
            candidate.evidence
        )
    admissions = [
        _strongest_decision(
            engine,
            descriptor,
            evidence_by_ref.get(descriptor.tool_ref, []),
        )
        for descriptor in descriptors
    ]
    admissions.sort(key=lambda decision: decision.tool_ref)

    provisional: dict[str, Any] = {
        "schema_version": "ari.catalog-lock/v1",
        "catalog_digest": "sha256:" + "0" * 64,
        "policy_digest": engine.policy.digest,
        "sources": [
            source.locked_source.model_dump(mode="json") for source in source_list
        ],
        "tools": [descriptor.model_dump(mode="json") for descriptor in descriptors],
        "admissions": [decision.model_dump(mode="json") for decision in admissions],
        "quarantined": [
            item.model_dump(mode="json")
            for item in sorted(
                quarantined,
                key=lambda value: (
                    value.source_id,
                    value.candidate_name,
                    value.reason_code,
                    value.candidate_digest,
                ),
            )
        ],
        "overlaps": [item.model_dump(mode="json") for item in overlaps],
    }
    provisional["catalog_digest"] = catalog_lock_digest(provisional)
    lock = CatalogLockV1.model_validate(provisional)
    return CatalogBuildResult(lock=lock, index=build_catalog_index(lock))


def _terms(descriptor: CanonicalToolDescriptorV1) -> list[str]:
    raw = " ".join(
        (
            descriptor.name,
            descriptor.capability_ref,
            descriptor.description,
            descriptor.provider_id,
            *descriptor.source_ids,
            *descriptor.semantics.keys(),
            *descriptor.units.keys(),
        )
    ).casefold()
    return sorted(set(_TOKEN_RE.findall(raw)))[:256]


def build_catalog_index(lock: CatalogLockV1) -> CatalogIndexV1:
    admission_by_ref = {item.tool_ref: item for item in lock.admissions}
    entries = [
        CatalogIndexEntryV1(
            tool_ref=descriptor.tool_ref,
            name=descriptor.name,
            capability_ref=descriptor.capability_ref,
            admission_level=admission_by_ref[descriptor.tool_ref].level,
            source_ids=descriptor.source_ids,
            terms=_terms(descriptor),
            description=sanitize_text(descriptor.description, limit=500),
        )
        for descriptor in lock.tools
    ]
    return CatalogIndexV1(
        catalog_digest=lock.catalog_digest,
        entries=sorted(entries, key=lambda entry: entry.tool_ref),
    )


def load_catalog_lock(path: str | Path) -> CatalogLockV1:
    lock_path = Path(path)
    if lock_path.is_symlink():
        raise CatalogCorruptError(f"symbolic catalog locks are refused: {lock_path}")
    try:
        if lock_path.stat().st_size > _MAX_LOCK_BYTES:
            raise CatalogCorruptError(
                f"catalog lock exceeds {_MAX_LOCK_BYTES} bytes: {lock_path}"
            )
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
        return CatalogLockV1.model_validate(raw)
    except CatalogCorruptError:
        raise
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise CatalogCorruptError(f"invalid catalog lock {lock_path}: {exc}") from exc


def load_catalog_index(
    path: str | Path,
    *,
    expected_catalog_digest: str,
) -> CatalogIndexV1:
    index_path = Path(path)
    if index_path.is_symlink():
        raise CatalogCorruptError(f"symbolic catalog indexes are refused: {index_path}")
    try:
        index = CatalogIndexV1.model_validate_json(
            index_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError) as exc:
        raise CatalogCorruptError(f"invalid catalog index {index_path}: {exc}") from exc
    if index.catalog_digest != expected_catalog_digest:
        raise CatalogCorruptError("catalog index was derived from a different lock")
    return index


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def write_catalog_lock(
    path: str | Path,
    lock: CatalogLockV1,
    *,
    replace: bool = False,
) -> None:
    lock_path = Path(path)
    payload = (
        json.dumps(
            lock.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if lock_path.exists() and not replace:
        existing = load_catalog_lock(lock_path)
        if existing.catalog_digest == lock.catalog_digest:
            return
        raise CatalogImmutableError(
            f"refusing to replace active {lock_path}; write a pending review diff"
        )
    _atomic_write(lock_path, payload)


def write_catalog_index(path: str | Path, index: CatalogIndexV1) -> None:
    payload = (
        json.dumps(
            index.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    _atomic_write(Path(path), payload)


def catalog_diff(old: CatalogLockV1, new: CatalogLockV1) -> dict[str, Any]:
    old_refs = {tool.tool_ref for tool in old.tools}
    new_refs = {tool.tool_ref for tool in new.tools}
    old_sources = {source.source_id: source.source_digest for source in old.sources}
    new_sources = {source.source_id: source.source_digest for source in new.sources}
    return {
        "schema_version": "ari.catalog-diff/v1",
        "base_catalog_digest": old.catalog_digest,
        "candidate_catalog_digest": new.catalog_digest,
        "tools_added": sorted(new_refs - old_refs),
        "tools_removed": sorted(old_refs - new_refs),
        "sources_added": sorted(set(new_sources) - set(old_sources)),
        "sources_removed": sorted(set(old_sources) - set(new_sources)),
        "sources_changed": sorted(
            source_id
            for source_id in set(old_sources) & set(new_sources)
            if old_sources[source_id] != new_sources[source_id]
        ),
        "quarantine_count": len(new.quarantined),
        "policy_changed": old.policy_digest != new.policy_digest,
    }


def write_reviewable_catalog(
    *,
    lock_path: str | Path,
    index_path: str | Path,
    result: CatalogBuildResult,
    approve: bool = False,
) -> dict[str, Any]:
    """Write initial/approved output, otherwise a pending lock and diff."""

    lock_target = Path(lock_path)
    index_target = Path(index_path)
    if not lock_target.exists():
        write_catalog_lock(lock_target, result.lock)
        write_catalog_index(index_target, result.index)
        return {"status": "created", "catalog_digest": result.lock.catalog_digest}
    current = load_catalog_lock(lock_target)
    if current.catalog_digest == result.lock.catalog_digest:
        return {"status": "unchanged", "catalog_digest": current.catalog_digest}
    difference = catalog_diff(current, result.lock)
    if approve:
        write_catalog_lock(lock_target, result.lock, replace=True)
        write_catalog_index(index_target, result.index)
        return {"status": "approved", **difference}

    pending_lock = lock_target.with_name(lock_target.name + ".pending")
    pending_index = index_target.with_name(index_target.name + ".pending")
    diff_path = lock_target.with_name(lock_target.name + ".diff.json")
    write_catalog_lock(pending_lock, result.lock, replace=True)
    write_catalog_index(pending_index, result.index)
    _atomic_write(
        diff_path,
        json.dumps(difference, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return {
        "status": "pending-review",
        "pending_lock": str(pending_lock),
        "pending_index": str(pending_index),
        "diff": str(diff_path),
        **difference,
    }


__all__ = [
    "CATALOG_INDEX_FILENAME",
    "CATALOG_LOCK_FILENAME",
    "CatalogBuildResult",
    "CatalogCorruptError",
    "CatalogError",
    "CatalogImmutableError",
    "build_catalog",
    "build_catalog_index",
    "catalog_diff",
    "load_catalog_index",
    "load_catalog_lock",
    "write_catalog_index",
    "write_catalog_lock",
    "write_reviewable_catalog",
]
