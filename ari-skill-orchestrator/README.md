# ari-skill-orchestrator

Exposes ARI itself as an MCP server so external agents, IDEs, and
scripts can trigger ARI experiment runs.  Recursive ARI-inside-ARI
launches are supported (with a depth cap).

## Overview

ARI can act both as a standalone CLI and as an MCP server embedded
in other systems.  This skill is that bridge.  When invoked from
inside a parent ARI run, it inherits the parent's checkpoint scope
via `ARI_PARENT_RUN_ID` and refuses to spawn beyond
`ARI_MAX_RECURSION_DEPTH`.

## Tools

| Tool | Description |
|---|---|
| `run_experiment` | Accept an experiment.md, launch `ari run` asynchronously, return `{run_id, checkpoint_dir, status}` |
| `get_status` | Per-run progress, node count, best metric, elapsed seconds |
| `list_runs` | Summary list of every known run |
| `get_paper` | Generated LaTeX section / compiled PDF path for a run |

## Files written under the checkpoint

- `orchestrator_logs/<run_id>/ari.log` — per-child run log
- `orchestrator_logs/<run_id>/launch_config.json` — exact env + args
- `orchestrator_logs/<run_id>/run_meta.json` — run metadata

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `ARI_WORKSPACE` | Root directory for all runs | (none — required) |
| `ARI_ORCHESTRATOR_PORT` | MCP server listen port | `9890` |
| `ARI_ORCHESTRATOR_LOGS` | Per-run log directory | `$ARI_WORKSPACE/orchestrator_logs` |
| `ARI_PARENT_RUN_ID` | Parent run id (auto-set during recursion) | (auto) |
| `ARI_MAX_RECURSION_DEPTH` | Depth cap for ARI-inside-ARI | `3` |

## Recursion safety

`run_experiment` invoked from inside ARI sets `ARI_PARENT_RUN_ID`
on the child, and `ARI_MAX_RECURSION_DEPTH` is decremented as the
chain grows.  When the depth would exceed the cap the call is
rejected before any subprocess is spawned, preventing runaway
recursion.

## Use cases

- **Claude Desktop**: trigger ARI experiments directly from chat.
- **Multi-agent orchestration**: chain ARI with other research
  agents.
- **CI / CD integration**: automate experiment pipelines.

## Test gap

This skill currently has **no automated tests**.  A minimal smoke
test (MCP handshake + mocked `ari run` subprocess) is the
recommended next step.  Track this as part of the skill's future
work — `docs/guides/testing.md` describes the pattern to follow.

## Development

```bash
python -m ari_skill_orchestrator.server &
curl -X POST http://localhost:9890/api/run -d '{...}'
```

## See also

- `docs/reference/skills.md#ari-skill-orchestrator` — high-level summary.
- `docs/reference/mcp_tools.md` — argument signatures.
- `docs/reference/environment_variables.md` — env var table.
