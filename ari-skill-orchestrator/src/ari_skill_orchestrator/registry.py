"""SQLite authority for idempotent ARI run lifecycle and lineage quotas."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .contracts import PrincipalV1, RunRequestV1, RunState
from .registry_schema import REGISTRY_SCHEMA
from .registry_types import (
    ACTIVE_STATES,
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    IdempotencyConflictError,
    InvalidTransitionError,
    QuotaExceededError,
    RegistryError,
    RunAuthorizationError,
    RunNotFoundError,
    RunRecord,
    record_from_row,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"run_{stamp}_{uuid.uuid4().hex[:16]}"


class RunRegistry:
    """One connection per transaction keeps thread/process concurrency explicit."""

    def __init__(self, logs_root: str | Path) -> None:
        self.logs_root = Path(logs_root).resolve()
        self.state_root = self.logs_root / ".ari-orchestrator"
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.state_root.is_symlink():
            raise RegistryError("orchestrator state root cannot be symbolic")
        os.chmod(self.state_root, 0o700)
        self.database = self.state_root / "runs.sqlite3"
        if self.database.is_symlink():
            raise RegistryError("orchestrator database cannot be symbolic")
        self._database_uri = self.database.as_uri() + "?mode=rwc&nofollow=1"
        self.receipts_root = self.state_root / "receipts"
        self.receipts_root.mkdir(mode=0o700, exist_ok=True)
        if self.receipts_root.is_symlink():
            raise RegistryError("orchestrator receipt root cannot be symbolic")
        os.chmod(self.receipts_root, 0o700)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_uri, timeout=30.0, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(REGISTRY_SCHEMA)
            connection.commit()
            try:
                os.chmod(self.database, 0o600)
            except OSError:
                pass
        finally:
            connection.close()

    @staticmethod
    def _record(row: sqlite3.Row) -> RunRecord:
        return record_from_row(row)

    @staticmethod
    def _require_access(row: sqlite3.Row, principal: PrincipalV1) -> None:
        if row["principal_id"] != principal.principal_id and not principal.is_admin:
            raise RunAuthorizationError("principal is not authorized for this run")

    def claim(
        self,
        request: RunRequestV1,
        principal: PrincipalV1,
        *,
        max_active_runs: int,
    ) -> tuple[RunRecord, bool]:
        """Atomically return an identical prior claim or create one new run."""

        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM runs WHERE principal_id=? AND idempotency_key=?",
                (principal.principal_id, request.idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["request_digest"] != request.request_digest:
                    raise IdempotencyConflictError(
                        "idempotency key was already used for a different request"
                    )
                return self._record(existing), True

            active_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM runs WHERE state IN ('submitted','running','cancelling')"
                ).fetchone()[0]
            )
            if active_count >= max_active_runs:
                raise QuotaExceededError("global active-run quota exceeded")

            parent: sqlite3.Row | None = None
            if request.parent_run_id:
                parent = connection.execute(
                    "SELECT * FROM runs WHERE run_id=?", (request.parent_run_id,)
                ).fetchone()
                if parent is None:
                    raise RunNotFoundError("parent run does not exist")
                self._require_access(parent, principal)
                if parent["state"] == "cancelled":
                    raise QuotaExceededError(
                        "cancelled parent cannot launch descendants"
                    )
                root_run_id = str(parent["root_run_id"])
                recursion_depth = int(parent["recursion_depth"]) + 1
                effective_max_depth = min(
                    int(parent["max_recursion_depth"]), request.max_recursion_depth
                )
                root = connection.execute(
                    "SELECT * FROM runs WHERE run_id=?", (root_run_id,)
                ).fetchone()
                if root is None:
                    raise RegistryError("run lineage has no root authority")
                root_request = RunRequestV1.model_validate_json(root["request_json"])
                if recursion_depth > effective_max_depth:
                    raise QuotaExceededError("recursion-depth quota exceeded")
                descendants = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM runs WHERE root_run_id=? AND run_id<>?",
                        (root_run_id, root_run_id),
                    ).fetchone()[0]
                )
                if descendants >= root_request.max_descendant_runs:
                    raise QuotaExceededError("descendant-run quota exceeded")
                used_nodes = int(
                    connection.execute(
                        "SELECT COALESCE(SUM(json_extract(request_json, '$.max_nodes')),0) "
                        "FROM runs WHERE root_run_id=?",
                        (root_run_id,),
                    ).fetchone()[0]
                )
                if used_nodes + request.max_nodes > root_request.max_total_nodes:
                    raise QuotaExceededError("lineage node quota exceeded")
                used_cost = float(
                    connection.execute(
                        "SELECT COALESCE(SUM(json_extract(request_json, '$.estimated_cost_usd')),0) "
                        "FROM runs WHERE root_run_id=?",
                        (root_run_id,),
                    ).fetchone()[0]
                )
                if used_cost + request.estimated_cost_usd > root_request.max_cost_usd:
                    raise QuotaExceededError("lineage cost quota exceeded")
            else:
                root_run_id = ""
                recursion_depth = 0
                effective_max_depth = request.max_recursion_depth

            run_id = _new_run_id()
            if not root_run_id:
                root_run_id = run_id
            checkpoint = self.logs_root / run_id
            receipt = self.receipts_root / f"{run_id}.json"
            created_at = _now()
            rendered_request = json.dumps(
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
                    created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    principal.principal_id,
                    request.idempotency_key,
                    request.request_digest,
                    rendered_request,
                    request.parent_run_id,
                    root_run_id,
                    recursion_depth,
                    effective_max_depth,
                    str(checkpoint),
                    "submitted",
                    str(receipt),
                    created_at,
                ),
            )
            connection.execute(
                "INSERT INTO run_events(run_id,from_state,to_state,occurred_at,reason,version) "
                "VALUES(?,NULL,'submitted',?,'idempotent claim',0)",
                (run_id, created_at),
            )
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            assert row is not None
            return self._record(row), False

    def get(self, run_id: str, principal: PrincipalV1) -> RunRecord:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise RunNotFoundError("run does not exist")
        self._require_access(row, principal)
        return self._record(row)

    def get_system(self, run_id: str) -> RunRecord:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise RunNotFoundError("run does not exist")
        return self._record(row)

    def list(
        self, principal: PrincipalV1, *, parent_run_id: str | None = None
    ) -> list[RunRecord]:
        connection = self._connect()
        try:
            clauses: list[str] = []
            arguments: list[object] = []
            if not principal.is_admin:
                clauses.append("principal_id=?")
                arguments.append(principal.principal_id)
            if parent_run_id is not None:
                clauses.append("parent_run_id=?")
                arguments.append(parent_run_id)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            rows = connection.execute(
                "SELECT * FROM runs" + where + " ORDER BY created_at DESC, run_id DESC",
                arguments,
            ).fetchall()
        finally:
            connection.close()
        return [self._record(row) for row in rows]

    def transition(
        self,
        run_id: str,
        to_state: RunState,
        *,
        reason: str = "",
        exit_code: int | None = None,
        error: str | None = None,
    ) -> RunRecord:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise RunNotFoundError("run does not exist")
            current = str(row["state"])
            if current == to_state:
                return self._record(row)
            if to_state not in ALLOWED_TRANSITIONS[current]:
                raise InvalidTransitionError(
                    f"invalid run transition {current}->{to_state}"
                )
            now = _now()
            version = int(row["version"]) + 1
            started_at = row["started_at"]
            completed_at = row["completed_at"]
            if to_state == "running" and started_at is None:
                started_at = now
            if to_state in TERMINAL_STATES:
                completed_at = now
            connection.execute(
                """
                UPDATE runs SET state=?, started_at=?, completed_at=?, exit_code=?,
                    error=?, version=? WHERE run_id=? AND version=?
                """,
                (
                    to_state,
                    started_at,
                    completed_at,
                    exit_code if exit_code is not None else row["exit_code"],
                    error if error is not None else row["error"],
                    version,
                    run_id,
                    row["version"],
                ),
            )
            connection.execute(
                "INSERT INTO run_events(run_id,from_state,to_state,occurred_at,reason,version) "
                "VALUES(?,?,?,?,?,?)",
                (run_id, current, to_state, now, reason[:512], version),
            )
            updated = connection.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            assert updated is not None
            return self._record(updated)

    def attach_process(
        self, run_id: str, *, pid: int, pid_start_ticks: int
    ) -> RunRecord:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise RunNotFoundError("run does not exist")
            if row["state"] != "submitted":
                raise InvalidTransitionError(
                    "process can only attach to a submitted run"
                )
            now = _now()
            version = int(row["version"]) + 1
            connection.execute(
                """
                UPDATE runs SET state='running', pid=?, pid_start_ticks=?,
                    started_at=?, version=? WHERE run_id=? AND version=?
                """,
                (pid, pid_start_ticks, now, version, run_id, row["version"]),
            )
            connection.execute(
                "INSERT INTO run_events(run_id,from_state,to_state,occurred_at,reason,version) "
                "VALUES(?,'submitted','running',?,'runner attached',?)",
                (run_id, now, version),
            )
            updated = connection.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            assert updated is not None
            return self._record(updated)

    def request_cancellation(self, run_id: str, principal: PrincipalV1) -> RunRecord:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise RunNotFoundError("run does not exist")
            self._require_access(row, principal)
            current = str(row["state"])
            if current in TERMINAL_STATES:
                return self._record(row)
            if current == "cancelling":
                return self._record(row)
            now = _now()
            version = int(row["version"]) + 1
            target = "cancelled" if current == "submitted" else "cancelling"
            completed_at = now if target == "cancelled" else row["completed_at"]
            connection.execute(
                """
                UPDATE runs SET state=?, cancel_requested=1, completed_at=?, version=?
                WHERE run_id=? AND version=?
                """,
                (target, completed_at, version, run_id, row["version"]),
            )
            connection.execute(
                "INSERT INTO run_events(run_id,from_state,to_state,occurred_at,reason,version) "
                "VALUES(?,?,?,?,?,?)",
                (run_id, current, target, now, "cancellation requested", version),
            )
            updated = connection.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            assert updated is not None
            return self._record(updated)

    def lineage_usage(self, root_run_id: str) -> dict[str, int | float]:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT COUNT(*) AS runs,
                       COALESCE(SUM(json_extract(request_json, '$.max_nodes')),0) AS nodes,
                       COALESCE(SUM(json_extract(request_json, '$.estimated_cost_usd')),0) AS cost
                FROM runs WHERE root_run_id=?
                """,
                (root_run_id,),
            ).fetchone()
        finally:
            connection.close()
        assert row is not None
        return {
            "claimed_runs": int(row["runs"]),
            "claimed_nodes": int(row["nodes"]),
            "estimated_cost_usd": float(row["cost"]),
        }

    def events(self, run_id: str) -> list[dict[str, object]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT from_state,to_state,occurred_at,reason,version "
                "FROM run_events WHERE run_id=? ORDER BY event_id",
                (run_id,),
            ).fetchall()
        finally:
            connection.close()
        return [dict(row) for row in rows]

    def import_legacy(
        self,
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
        """Explicitly import one pre-v2 checkpoint; never used by normal reads."""

        from .registry_legacy import import_legacy_record

        return import_legacy_record(
            self,
            run_id=run_id,
            request=request,
            principal=principal,
            checkpoint_dir=checkpoint_dir,
            parent_run_id=parent_run_id,
            root_run_id=root_run_id,
            recursion_depth=recursion_depth,
            max_recursion_depth=max_recursion_depth,
            state=state,
            created_at=created_at,
            exit_code=exit_code,
            error=error,
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
    "RunRegistry",
]
