"""Run-registry state, records, and typed failures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .contracts import RunRequestV1, RunState


ACTIVE_STATES = ("submitted", "running", "cancelling")
TERMINAL_STATES = ("succeeded", "failed", "cancelled")
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "submitted": frozenset({"running", "failed", "cancelled"}),
    "running": frozenset({"cancelling", "succeeded", "failed", "cancelled"}),
    "cancelling": frozenset({"succeeded", "failed", "cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


class RegistryError(RuntimeError):
    pass


class RunNotFoundError(RegistryError):
    pass


class IdempotencyConflictError(RegistryError):
    pass


class InvalidTransitionError(RegistryError):
    pass


class QuotaExceededError(RegistryError):
    pass


class RunAuthorizationError(RegistryError):
    pass


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    principal_id: str
    idempotency_key: str
    request_digest: str
    request: RunRequestV1
    parent_run_id: str | None
    root_run_id: str
    recursion_depth: int
    max_recursion_depth: int
    checkpoint_dir: Path
    state: RunState
    pid: int | None
    pid_start_ticks: int | None
    runner_receipt: Path
    created_at: str
    started_at: str | None
    completed_at: str | None
    exit_code: int | None
    error: str | None
    cancel_requested: bool
    version: int


def record_from_row(row: Mapping[str, Any]) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        principal_id=row["principal_id"],
        idempotency_key=row["idempotency_key"],
        request_digest=row["request_digest"],
        request=RunRequestV1.model_validate_json(row["request_json"]),
        parent_run_id=row["parent_run_id"],
        root_run_id=row["root_run_id"],
        recursion_depth=int(row["recursion_depth"]),
        max_recursion_depth=int(row["max_recursion_depth"]),
        checkpoint_dir=Path(row["checkpoint_dir"]),
        state=row["state"],
        pid=row["pid"],
        pid_start_ticks=row["pid_start_ticks"],
        runner_receipt=Path(row["runner_receipt"]),
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        exit_code=row["exit_code"],
        error=row["error"],
        cancel_requested=bool(row["cancel_requested"]),
        version=int(row["version"]),
    )


__all__ = [
    "ACTIVE_STATES",
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATES",
    "IdempotencyConflictError",
    "InvalidTransitionError",
    "QuotaExceededError",
    "RegistryError",
    "RunAuthorizationError",
    "RunNotFoundError",
    "RunRecord",
    "record_from_row",
]
