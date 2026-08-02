"""Explicit terminal-record insertion for legacy orchestrator repair."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .contracts import PrincipalV1, RunRequestV1, RunState
from .registry_types import (
    TERMINAL_STATES,
    IdempotencyConflictError,
    RegistryError,
    RunRecord,
)

if TYPE_CHECKING:
    from .registry import RunRegistry


def import_legacy_record(
    registry: "RunRegistry",
    *,
    run_id: str,
    request: RunRequestV1,
    principal: PrincipalV1,
    checkpoint_dir: Path,
    parent_run_id: str | None,
    root_run_id: str,
    recursion_depth: int,
    max_recursion_depth: int,
    state: RunState,
    created_at: str,
    exit_code: int | None,
    error: str | None,
) -> tuple[RunRecord, bool]:
    """Import one terminal pre-v2 checkpoint without enabling scan-based reads."""

    if state not in TERMINAL_STATES:
        raise RegistryError("legacy imports must be terminal and fail closed")
    checkpoint = checkpoint_dir.resolve(strict=True)
    try:
        checkpoint.relative_to(registry.logs_root)
    except ValueError as exc:
        raise RegistryError("legacy checkpoint is outside the logs root") from exc
    with registry._transaction() as connection:
        existing = connection.execute(
            "SELECT * FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if existing is not None:
            registry._require_access(existing, principal)
            return registry._record(existing), True
        key_owner = connection.execute(
            "SELECT request_digest FROM runs WHERE principal_id=? AND idempotency_key=?",
            (principal.principal_id, request.idempotency_key),
        ).fetchone()
        if key_owner is not None:
            raise IdempotencyConflictError("legacy idempotency identity collides")
        if parent_run_id is not None:
            parent = connection.execute(
                "SELECT run_id FROM runs WHERE run_id=?", (parent_run_id,)
            ).fetchone()
            if parent is None:
                raise RegistryError("legacy parent must be imported before its child")
        request_json = json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        connection.execute(
            """
            INSERT INTO runs(
                run_id, principal_id, idempotency_key, request_digest,
                request_json, parent_run_id, root_run_id, recursion_depth,
                max_recursion_depth, checkpoint_dir, state, runner_receipt,
                created_at, completed_at, exit_code, error
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                principal.principal_id,
                request.idempotency_key,
                request.request_digest,
                request_json,
                parent_run_id,
                root_run_id,
                recursion_depth,
                max_recursion_depth,
                str(checkpoint),
                state,
                str(checkpoint / ".orchestrator-runner.json"),
                created_at,
                created_at,
                exit_code,
                error,
            ),
        )
        connection.execute(
            "INSERT INTO run_events(run_id,from_state,to_state,occurred_at,reason,version) "
            "VALUES(?,NULL,?,?,?,0)",
            (run_id, state, created_at, "explicit legacy repair import"),
        )
        row = connection.execute(
            "SELECT * FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        assert row is not None
        return registry._record(row), False


__all__ = ["import_legacy_record"]
