"""Fail-closed, explicit migration of pre-v2 orchestrator checkpoints."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import PrincipalV1, RUN_ID_PATTERN, RunRequestV1, RunState
from .registry import RunRegistry
from .runtime import ServiceConfig, ServiceError, safe_bytes_file, safe_json_file


@dataclass(frozen=True)
class LegacyCandidate:
    checkpoint: Path
    metadata: dict[str, Any]
    experiment: str
    parent_run_id: str | None


def _read_candidate(checkpoint: Path) -> LegacyCandidate | None:
    if (
        checkpoint.name.startswith(".")
        or checkpoint.is_symlink()
        or not checkpoint.is_dir()
    ):
        return None
    metadata = safe_json_file(checkpoint / "meta.json") or {}
    run_id = str(metadata.get("run_id") or checkpoint.name)
    if not re.fullmatch(RUN_ID_PATTERN, run_id):
        return None
    parent = metadata.get("parent_run_id")
    parent_run_id = str(parent) if parent else None
    if parent_run_id and not re.fullmatch(RUN_ID_PATTERN, parent_run_id):
        return None
    payload = safe_bytes_file(checkpoint / "experiment.md", max_bytes=1_048_576)
    if payload is None:
        return None
    try:
        experiment = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not experiment:
        return None
    return LegacyCandidate(checkpoint, metadata, experiment, parent_run_id)


def _discover(
    config: ServiceConfig,
) -> tuple[dict[str, LegacyCandidate], set[str], list[dict[str, str]]]:
    candidates: dict[str, LegacyCandidate] = {}
    ambiguous: set[str] = set()
    skipped: list[dict[str, str]] = []
    for checkpoint in sorted(config.logs_root.iterdir()):
        candidate = _read_candidate(checkpoint)
        if candidate is None:
            continue
        run_id = str(candidate.metadata.get("run_id") or checkpoint.name)
        if run_id in candidates:
            candidates.pop(run_id)
            ambiguous.add(run_id)
            skipped.append({"run_id": run_id, "reason": "duplicate legacy run ID"})
        elif run_id not in ambiguous:
            candidates[run_id] = candidate
    return candidates, ambiguous, skipped


def _lineage(
    identifier: str,
    candidates: dict[str, LegacyCandidate],
    ambiguous: set[str],
) -> tuple[str, int]:
    current = identifier
    depth = 0
    seen: set[str] = set()
    while True:
        if current in seen:
            raise ServiceError("legacy registry contains a lineage cycle")
        seen.add(current)
        parent = candidates[current].parent_run_id
        if parent in ambiguous:
            raise ServiceError("legacy parent run ID is ambiguous")
        if parent not in candidates:
            return current, depth
        depth += 1
        if depth > 32:
            raise ServiceError("legacy lineage exceeds depth 32")
        current = parent


def _terminal_state(
    candidate: LegacyCandidate,
) -> tuple[RunState, int | None, str | None]:
    raw_state = str(candidate.metadata.get("status") or "").lower()
    results = safe_json_file(candidate.checkpoint / "results.json")
    raw_exit = candidate.metadata.get("exit_code")
    exit_code = (
        raw_exit
        if isinstance(raw_exit, int) and not isinstance(raw_exit, bool)
        else None
    )
    if raw_state in {"completed", "succeeded"} and results is not None:
        return "succeeded", 0, None
    if raw_state in {"cancelled", "canceled"}:
        return "cancelled", exit_code, "imported terminal cancellation"
    return (
        "failed",
        exit_code,
        "legacy state lacked a durable v2 runner receipt",
    )


def _request(
    candidate: LegacyCandidate,
    *,
    parent_run_id: str | None,
    depth: int,
    candidate_count: int,
) -> tuple[RunRequestV1, int]:
    results = safe_json_file(candidate.checkpoint / "results.json") or {}
    nodes = results.get("nodes")
    max_nodes = min(10_000, max(1, len(nodes))) if isinstance(nodes, dict) else 10
    raw_depth = candidate.metadata.get("max_recursion_depth")
    declared_depth = (
        raw_depth
        if isinstance(raw_depth, int) and not isinstance(raw_depth, bool)
        else 3
    )
    max_depth = min(32, max(depth, declared_depth))
    digest = hashlib.sha256(
        (str(candidate.checkpoint) + "\0" + candidate.experiment).encode("utf-8")
    ).hexdigest()
    request = RunRequestV1.from_parameters(
        experiment_md=candidate.experiment,
        idempotency_key="legacy:" + digest[:32],
        parent_run_id=parent_run_id,
        max_recursion_depth=max_depth,
        max_nodes=max_nodes,
        max_total_nodes=max(max_nodes, 100),
        max_descendant_runs=min(10_000, max(candidate_count - 1, 0)),
    )
    return request, max_depth


def _created_at(candidate: LegacyCandidate) -> str:
    raw = candidate.metadata.get("created_at")
    if isinstance(raw, str) and raw:
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).isoformat(
                    timespec="microseconds"
                )
        except ValueError:
            pass
    return datetime.fromtimestamp(
        candidate.checkpoint.stat().st_mtime,
        tz=timezone.utc,
    ).isoformat(timespec="microseconds")


def repair_legacy_registry(
    config: ServiceConfig,
    registry: RunRegistry,
    principal: PrincipalV1,
) -> dict[str, Any]:
    """Import terminal legacy state; normal read paths never call this scanner."""

    candidates, ambiguous, skipped = _discover(config)
    ordered: list[tuple[int, str, str]] = []
    for run_id in candidates:
        try:
            root, depth = _lineage(run_id, candidates, ambiguous)
        except ServiceError as exc:
            skipped.append({"run_id": run_id, "reason": str(exc)})
            continue
        ordered.append((depth, run_id, root))
    imported: list[str] = []
    reused: list[str] = []
    for depth, run_id, root in sorted(ordered):
        candidate = candidates[run_id]
        parent = candidate.parent_run_id
        parent_run_id = parent if parent in candidates else None
        state, exit_code, error = _terminal_state(candidate)
        request, max_depth = _request(
            candidate,
            parent_run_id=parent_run_id,
            depth=depth,
            candidate_count=len(candidates),
        )
        _record, was_reused = registry.import_legacy(
            run_id=run_id,
            request=request,
            principal=principal,
            checkpoint_dir=candidate.checkpoint,
            parent_run_id=parent_run_id,
            root_run_id=root,
            recursion_depth=depth,
            max_recursion_depth=max_depth,
            state=state,
            created_at=_created_at(candidate),
            exit_code=exit_code,
            error=error,
        )
        (reused if was_reused else imported).append(run_id)
    return {
        "schema_version": "ari.orchestrator-registry-repair/v1",
        "imported": imported,
        "already_present": reused,
        "skipped": skipped,
    }


__all__ = ["repair_legacy_registry"]
