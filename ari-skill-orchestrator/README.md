# ari-skill-orchestrator

Authenticated, durable MCP control plane for asynchronous ARI experiment runs.
It exposes a fixed 12-tool surface over a SQLite run registry and verified,
content-addressed artifacts.

## Guarantees

- `run_experiment` requires an idempotency key; a retry cannot start a second run.
- Run state is an atomic state machine, not a checkpoint-directory guess.
- Restart recovery verifies a digest-bound runner receipt plus PID start time.
- Cancellation reaches the child process group and settles one terminal state.
- Principal ownership is enforced for status, cancellation, and every artifact read.
- Recursion, run count, node count, cost, CPU, and timeout quotas fail before launch.
- Parent environment variables are allowlisted; model credentials cross only through
  the declared `model.provider` scope and are never stored in request metadata.
- Callers receive artifact SHA-256 references, never checkpoint paths.
- Skill/workflow inspection reads only the run's verified `SKILLS.lock` and removes
  entrypoints, environment declarations, credentials, and raw schemas.

## Tools

| Tool | Purpose |
|---|---|
| `run_experiment` | Idempotently submit a bounded run |
| `get_status`, `get_result`, `stop_experiment` | Poll, collect, or cancel its lifecycle |
| `list_runs`, `list_children` | Read an owner-scoped run/lineage index |
| `list_artifacts`, `read_artifact` | Resolve verified content by SHA-256 |
| `get_paper`, `get_ear` | Return scoped publication/evidence references |
| `list_skills`, `get_workflow` | Return sanitized immutable lock views |

`read_file`, `list_files`, a request-level API key, substring run lookup, checkpoint
state inference, and the custom REST/SSE server were removed in v2.

## Transports

Stdio is the canonical local transport:

```bash
python ari-skill-orchestrator/src/server.py
```

The optional network surface is MCP Streamable HTTP, not a parallel REST API. It
binds to loopback by default and refuses to start without a mode-0600 file of bearer
token SHA-256 digests:

```bash
ARI_ORCHESTRATOR_HTTP_TOKENS_FILE=/secure/token-digests.json \
  python ari-skill-orchestrator/src/server.py --transport streamable-http
```

See [Orchestrator control plane](../docs/reference/orchestrator.md) for contracts,
token-file format, quotas, recovery, artifact admission, and migration.

## Verification

```bash
pytest -q ari-skill-orchestrator/tests
python ari-skill-orchestrator/scripts/sync_contracts.py
python scripts/check_skill_manifests.py
```
