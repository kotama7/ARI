"""SQLite schema owned by the durable orchestrator registry."""

REGISTRY_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    request_json TEXT NOT NULL,
    parent_run_id TEXT REFERENCES runs(run_id),
    root_run_id TEXT NOT NULL,
    recursion_depth INTEGER NOT NULL,
    max_recursion_depth INTEGER NOT NULL,
    checkpoint_dir TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    pid INTEGER,
    pid_start_ticks INTEGER,
    runner_receipt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    exit_code INTEGER,
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 0,
    UNIQUE(principal_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS runs_parent_idx ON runs(parent_run_id);
CREATE INDEX IF NOT EXISTS runs_root_idx ON runs(root_run_id);
CREATE INDEX IF NOT EXISTS runs_owner_idx ON runs(principal_id, created_at);
CREATE TABLE IF NOT EXISTS run_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    from_state TEXT,
    to_state TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    reason TEXT,
    version INTEGER NOT NULL
);
"""


__all__ = ["REGISTRY_SCHEMA"]
