# ari-skill-coding

Code-writing and execution MCP skill for ARI's research agent.

The skill is the agent's "hands": it writes source files into the
node's working directory, runs them under a sandboxed subprocess
group, and reports back stdout/stderr.  Optional Singularity /
Apptainer wrapping keeps user code isolated from the host on shared
clusters.

## MCP tools

| Tool | Purpose |
|---|---|
| `write_code` | Write a file (any text) into the node's working directory |
| `run_code` | Execute a script with a timeout and capture stdout / stderr |
| `run_bash` | Run an ad-hoc bash command (short, no timeout management) |
| `emit_results` | Emit a structured JSON record (`metrics`, `has_real_data`) for the evaluator |
| `read_file` | Read back a file the agent wrote earlier (truncated to 8 KB) |

`emit_results` is the only tool that affects evaluation scoring; the
others are scratch-space operations.

## Determinism (P2)

Code execution itself is deterministic at the subprocess level — same
inputs, same outputs.  Whatever the *user code* does is its own
business; ARI's role is to launch it cleanly and capture the trace.

The skill makes no LLM calls.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `ARI_MAX_CHILD_PROCS` | RLIMIT_NPROC cap inside the sandbox | `1024` |
| `ARI_WORK_DIR` | Override the per-node working directory root | `/tmp/ari_work` |
| `ARI_CONTAINER_IMAGE` | Path to a SIF / OCI image for sandbox wrapping | unset (host execution) |
| `ARI_CONTAINER_MODE` | `exec` or `shell`; chooses the singularity invocation | `exec` |

When `ARI_CONTAINER_IMAGE` is set, every spawned subprocess is wrapped
in `singularity exec` (or `apptainer exec`).  See
`ari-core/ari/container.py` for the resolver and
`docs/guides/troubleshooting.md` for sandbox failure modes.

## Sandbox guarantees

- New process group via `setsid()` so a hung child can be SIGKILLed
  cleanly without taking the parent.
- `RLIMIT_NPROC` hard-capped at `ARI_MAX_CHILD_PROCS` to prevent
  fork-bomb regressions (the limit was added after a 70 k-process
  incident).
- stdout / stderr truncated to 4 KB / 2 KB respectively before being
  returned to the LLM, so a runaway log cannot blow the prompt budget.

## ari-core boundary

Tests import `ari.container` directly today (see
`tests/test_server.py`).  Phase 4 of the master refactor moves this
to `ari.public.container`; the migration is tracked in
`ari-skill-coding/REFACTORING.md`.

## Development

```bash
pytest tests/ -q
```

Two test files: `test_server.py` (MCP-level happy path) and
`test_sandbox.py` (RLIMIT_NPROC + setsid behaviour).

## See also

- `docs/reference/skills.md#ari-skill-coding` — high-level summary in the master skill index.
- `docs/reference/environment_variables.md` — full env-var table.
- `ari-core/ari/container.py` — container wrapping helpers.
