# scripts/letta

Deployment helpers for the Letta memory backend (used by `ari.memory`).

## Contents

- `README.md` — this file.
- `docker-compose.yml` — Letta + Postgres (laptop/workstation).
- `start_pip.sh` — container-less single-user deployment with SQLite.
- `start_singularity.sh` — Singularity/Apptainer deployment for HPC.
- `pg-init/` — Postgres init SQL for the Letta store.
  - `README.md` — pg-init index.
  - `01-vector.sql` — `CREATE EXTENSION IF NOT EXISTS vector` (pgvector).
