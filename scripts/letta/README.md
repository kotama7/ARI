# scripts/letta

Deployment helpers for the Letta memory backend (used by `ari.memory`).

## Contents

- `README.md` — this file.
- `docker-compose.yml` — Letta + Postgres (laptop/workstation).
- `patch_091_missing_greenlet.py` — applies ARI's narrow Letta 0.9.1 SQLite/SQLAlchemy compatibility fixes. Agent creation flushes a row with server-default timestamps and immediately serializes it; current SQLAlchemy expires those defaults, so serialization performs forbidden implicit async IO and raises `MissingGreenlet`. An explicit async refresh keeps the exact transaction while loading the defaults through the supported awaitable path.
- `start_pip.sh` — container-less single-user deployment with SQLite.
- `start_singularity.sh` — Singularity/Apptainer deployment for HPC.
- `pg-init/` — Postgres init SQL for the Letta store.
  - `README.md` — pg-init index.
  - `01-vector.sql` — `CREATE EXTENSION IF NOT EXISTS vector` (pgvector).
