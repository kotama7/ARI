# scripts/letta/pg-init

Postgres init SQL run once on fresh Letta volume init (loaded by the postgres/pgvector entrypoint from `/docker-entrypoint-initdb.d/`).

## Contents

- `README.md` — this file.
- `01-vector.sql` — `CREATE EXTENSION IF NOT EXISTS vector` (pgvector).
