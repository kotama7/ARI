-- Letta migrations create columns with embedding VECTOR(...) — Postgres needs
-- the pgvector extension. This runs once on fresh volume init (official
-- postgres/pgvector entrypoint loads /docker-entrypoint-initdb.d/*.sql).
CREATE EXTENSION IF NOT EXISTS vector;
