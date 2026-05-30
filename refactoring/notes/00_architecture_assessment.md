# Architecture Assessment (baseline)

Produced by requirement `00_repository_architecture_assessment.md` (now deleted).
This is a **task-control baseline note**, not durable architecture documentation.
Durable knowledge belongs in `docs/` and per-directory `README.md` files.

Captured against the repository as of branch `refactoring` (2026-05-30). Verify
before relying on any number — the tree may have moved.

## 1. Public entrypoints

| Entry | Path / form | Notes |
|-------|-------------|-------|
| `ari` CLI | `ari-core/ari/cli/` (Typer app; `__main__.py` = `python -m ari.cli`) | thin wrapper; construction delegated to `ari.core` |
| `ari viz` | `ari viz <checkpoint_dir> --port 8765` → `ari-core/ari/viz/server.py` | dashboard launch |
| `start.sh` | `all`(default)`, `letta`, `registry`, `gui`, `shim`, `status`, `stop` | brings up Letta `:8283`, registry `:8290`, **GUI `:8765`**, CLI shim `:8900`; logs in `$HOME/.ari/` |
| `shutdown.sh` | `all`(default)`, `shim`, `gui`, `registry`, `letta` | pidfile-based stop; reaps orphan postgres/redis from Letta SIF (user-owned only) |
| `setup.sh` | interactive installer; `--with-registry`/`--without-registry` | staged install (core, deps, PDF, LaTeX, frontend, verify) |

CLI subcommands (top-level): `run`, `resume`, `clone`, `delete`, `paper`,
`status`, `projects`/`show`, `viz`, `settings`, `skills-list`. Sub-apps:
`ari memory` (`memory_cli.py`), `ari ear` (`cli_ear.py`), `ari migrate`
(`cli/migrate.py`), `ari registry` (loaded on-demand when registry deps present).

GUI port is **8765**, managed by `start.sh`/`shutdown.sh` (matches project convention).

## 2. Module responsibility table — `ari-core/ari/`

### Subpackages

| Module | Responsibility |
|--------|----------------|
| `agent/` | ReAct loop, environment capture, per-node LLM decision-making (`run_env.py`, `loop.py`); `agent/shims/` = PATH shims in repro sandbox |
| `cli/` | thin Typer wrapper; delegates construction to `ari.core` |
| `clone/` | fetch+verify+extract curated EAR bundles via scheme dispatch (`file://`,`https://`,`ari://`,`gh:`,`doi:`); `clone/resolvers/` per scheme |
| `config/` | Pydantic config models (LLMConfig, BFTSConfig) + env-var overrides; `_discover_skills()` |
| `configs/` | external config tables (`defaults.yaml`, `model_prices.yaml`) |
| `evaluator/` | LLM-driven metric extraction + dynamic axis generation (BFTS judge) |
| `llm/` | LiteLLM wrappers (`LLMClient`, message dataclasses); `cli_server.py` for shim |
| `mcp/` | MCP client; owns stdio lifecycle of `ari-skill-*` subprocesses, routes tool calls |
| `memory/` | node-memory backend abstraction (Letta default; File legacy; Local for tests) |
| `migrations/` | shims keeping old (v0.5/v0.6) checkpoints readable |
| `orchestrator/` | BFTS exploration + lineage decisions (breadth-first tree search) |
| `pipeline/` | generic workflow engine driven by `workflow.yaml`; `stage_runner.py`, `orchestrator.py` |
| `prompts/` | external prompt templates (`FilesystemPromptLoader`) |
| `protocols/` | Protocols/ABCs for core contracts (`evaluator.py`) |
| `public/` | stable public API surface for skills (`config_schema.py`, `container.py`, `cost_tracker.py`, `llm.py`, `paths.py`) |
| `publish/` | package+ship curated EAR to backends (local_tarball, S3, gh) |
| `registry/` | minimal HTTP registry for EAR bundles (token auth, sqlite token store) |
| `schemas/` | JSON Schemas (`node_report.schema.json`), loaded by basename via `ari.schemas.load()` |
| `viz/` | HTTP + WebSocket dashboard server + bundled React frontend |

### Top-level modules (all confirmed present)

`checkpoint.py` (checkpoint JSON I/O), `cli_ear.py` (`ari ear`), `container.py`
(container runtime abstraction), `core.py` (generic runtime builder),
`cost_tracker.py` (cost logs/summaries), `env_detect.py` (scheduler/runtime/HPC
detection), `lineage.py` (parent_run_id chain walk), `memory_cli.py`
(`ari memory`), `paths.py` (`PathManager`), `pidfile.py` (PID lifecycle),
`_deprecation.py` (v0.5→v1.0 deprecation warnings).

## 3. Skill packages

14 packages, **all with `README.md`**: benchmark, coding, evaluator, hpc, idea,
memory, orchestrator, paper, paper-re, plot, replicate, transform, vlm, web.
(`orchestrator` and `plot` have no `tests/` dir — see test matrix note.)

## 4. Risky coupling — first pass (feeds requirement 01)

1. **`ari-core/ari/viz/routes.py` = 1344 lines** — large dispatch+logic file (req `05`).
2. **`ari-core/ari/viz/state.py` = 19 module-level mutables** — `_settings_path`,
   `_ari_root`, `_env_write_path`, `_port`, `_server_port` (duplicate of `_port`),
   `_clients`, `_loop`, `_checkpoint_dir`, `_last_mtime`, `_last_proc`,
   `_running_procs` (dict of `subprocess.Popen`), `_last_log_fh`, `_last_log_path`,
   `_last_experiment_md`, `_launch_llm_model`, `_launch_llm_provider`,
   `_launch_config`, `_gpu_monitor_proc`, `_sub_experiments`, `_staging_dir`. No
   visible locking. `GLOBAL_RULES.md` forbids expanding this surface.
3. **Large frontend pages** (req `03`): `Results/ResultsPage.tsx` **3177**,
   `Workflow/WorkflowPage.tsx` 1720, `Wizard/StepResources.tsx` 1558,
   `Settings/SettingsPage.tsx` 1123, `Tree/DetailPanel.tsx` 938,
   `Monitor/MonitorPage.tsx` 857; `services/api.ts` itself 764.
4. **`core → ari.viz` imports** (req `09`-adjacent / boundary): `cli/commands.py:177`
   (`import ari.viz.server`), `cli/lineage.py:151` (`from ari.viz.api_orchestrator
   import _api_launch_sub_experiment`). See req 01 note for full edge list.
5. **Raw `fetch()` in 7 frontend components** (req `02`). See req 01 note.

## 5. Downstream-assumption cross-check

- `00`/`01`/`13` section-4 paths: **all present** (no gaps).
- `services/api.ts` exists (764 lines) → req `02` premise holds.
- `ari.public` / `ari.protocols` contracts exist as documented → reqs `09`/`11` premise holds.
- `state.py` global-state list matches `GLOBAL_RULES.md` enumeration (plus extras
  `_server_port`, `_last_*`, `_launch_*`, `_gpu_monitor_proc`, `_staging_dir`).

No requirement assumptions were contradicted; no `02`–`14` edits required from this pass.
