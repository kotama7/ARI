# Refactor Audit (Phase 0)

> Living document.  Mirrors `REFACTORING.md` / `DEPRECATION_REMOVAL.md`
> while the cleanup is in flight.  Will be folded into
> `docs/architecture.md` and `CONTRIBUTING.md` when Phase 6 lands and
> the temporary planning files are removed.

## 1. Giant modules (Phase 3 split targets)

| File | Lines | Plan |
|---|---:|---|
| `ari-core/ari/cli.py` | 1,962 | Phase 3A — split into `ari/cli/{lineage,bfts_loop,run,projects,commands,migrate}.py` |
| `ari-core/ari/pipeline.py` | 1,641 | Phase 3C — split into `ari/pipeline/{experiment_md,yaml_loader,stage_control,context_builder,stage_runner,orchestrator}.py` |
| `ari-core/ari/viz/server.py` | 1,489 | Phase 3B — split into `viz/{websocket,ui_helpers,routes}.py` |
| `ari-core/ari/agent/loop.py` | 1,459 | Phase 3D — extract `agent/{message_utils,tool_manager,guidance}.py` |
| `ari-core/ari/viz/api_state.py` | 1,434 | Phase 3B — split into `viz/{checkpoint_finder,state_sync,checkpoint_api,ear,file_api,checkpoint_lifecycle,node_work_api}.py` |
| `ari-core/ari/orchestrator/node_report.py` | 706 | Phase 3E — split into `node_report/{builder,legacy_reconstruct}.py` |

Total: **8,691 lines** in six files.

## 2. `ARI_CHECKPOINT_DIR` direct env reads (Phase 1 target)

31 occurrences spread across cli/pipeline/agent/orchestrator/viz/memory.
After Phase 1 (PR-1A + PR-1B) all of these go through
`PathManager.from_env()`:

```text
ari-core/ari/config.py:153,244
ari-core/ari/orchestrator/bfts.py:27,58
ari-core/ari/lineage.py:56
ari-core/ari/cost_tracker.py:197
ari-core/ari/cli.py:1203,1445,1898
ari-core/ari/pipeline.py:786,791,829,976
ari-core/ari/memory_cli.py:36,46
ari-core/ari/memory/letta_client.py:25
ari-core/ari/memory/auto_migrate.py:51
ari-core/ari/viz/api_experiment.py:622
ari-core/ari/viz/api_memory.py:38
ari-core/ari/viz/api_orchestrator.py:284
ari-core/ari/viz/api_state.py:1389
ari-core/ari/viz/server.py:383
```

(Read locations only; writes that synchronise into MCP child env stay as
``os.environ[...] = ...`` — those are not what Phase 1 targets.)

## 3. Cross-file duplication

| Concern | Implementations |
|---|---|
| `workflow.yaml` discovery | `cli.py:_resolve_cfg`, `pipeline.py:load_workflow`, `viz/server.py:_build_experiment_detail_config` |
| Checkpoint tree.json I/O | `cli.py:_save_tree_incremental`, `cli.py` (delete path), `viz/api_state.py:_load_nodes_tree` |

Phase 2 collapses each into one module:
- `ari/config/finder.py` (PR-2A)
- `ari/checkpoint.py` (PR-2B)

## 4. Skill → core internal-import boundary violations

| Caller | Imports |
|---|---|
| `ari-skill-coding/tests/test_server.py:102` | `import ari.container` |
| `ari-skill-plot/src/server.py:28` | `from ari import cost_tracker` |

Phase 4 routes both through `ari/public/` and adds
`tests/test_public_api_boundary.py` to prevent regressions.

## 5. `~/.ari/` legacy paths in code (DEPRECATION_REMOVAL.md §1-1)

13 occurrences across publish/clone/registry/memory/viz_api_publish:

| File:Line | Tier | Action |
|---|:---:|---|
| `ari/memory/file_client.py:25` | A | DR1 — delete default arg |
| `ari/memory_cli.py:111` | C | DR3 / Phase 5 — move to `migrations/v05_to_v07/memory.py` |
| `ari/memory_cli.py:306` | B | DR2 → warning, DR5 → required env |
| `ari/memory/auto_migrate.py:43` | C | Move to migrations module (Phase 5) |
| `ari/publish/backends/ari_registry.py:29,98` | B | DR2 warning + checkpoint-scoped lookup |
| `ari/clone/resolvers/ari.py:29,78` | B | Same as publish (shared helper) |
| `ari/registry/app.py:29` | B | DR2 + `resolve_data_dir()` helper |
| `ari/registry/cli.py:20` | B | Same as `app.py` |
| `ari/viz/api_publish.py:24` | B | Move module-level Path.home() into a function |
| `ari/core.py:91` (docstring) | doc | Phase 6 |
| `ari/paths.py:113` (docstring) | doc | Phase 6 |

## 6. `~/.ari/` legacy paths in docs (Phase 6)

`grep -rln "~/\.ari" docs/` → 16 files (en + ja + zh).  Phase 0 adds a
`[DEPRECATED since v0.5.0]` banner to each occurrence; Phase 6 finishes
the rewrite into `$ARI_CHECKPOINT_DIR/...` style.

## 7. Migration debt to isolate (Phase 5)

| Source | Description |
|---|---|
| `cli.py:246–305 cmd_migrate_node_reports` | v0.5 → v0.7 node_report migrator |
| `cli.py:1135–1352 backfill_node_reports` (call site) | Legacy on-demand backfill |
| `memory/auto_migrate.py` | v0.5 global JSONL → checkpoint memory |
| `evaluator/llm_evaluator.py:586–589` | Legacy 5-axis fallback |
| `orchestrator/node_report.py:650 reconstruct_report_from_legacy` | Old-tree → node_report rebuilder |

All move to `ari/migrations/v05_to_v07/` with thin shims left at the
original import paths.

## 8. Prompt / config externalisation (PROMPTS_AND_CONFIG.md §1)

8 prompts + 1 price table + 1 defaults table targeted for Phase PC0–PC8:

| File:Line | Sink |
|---|---|
| `agent/loop.py:41 SYSTEM_PROMPT` | `ari/prompts/agent/system.md` |
| `orchestrator/lineage_decision.py:239` | `ari/prompts/orchestrator/lineage_decision.md` |
| `orchestrator/root_idea_selector.py:57` | `ari/prompts/orchestrator/root_idea_selector.md` |
| `orchestrator/bfts.py:215,296,481` | `ari/prompts/orchestrator/bfts_*.md` |
| `pipeline.py:430` | `ari/prompts/pipeline/keyword_librarian.md` |
| `evaluator/llm_evaluator.py:165,324` | `ari/prompts/evaluator/{extract_metrics,peer_review}.md` |
| `cost_tracker.py:16–33` price dict | `ari/configs/model_prices.yaml` |
| `config.py` defaults | `ari/configs/defaults.yaml` |

## 9. Test-side audit (DEPRECATION_REMOVAL.md §1-3)

| File:Line | Issue | Action |
|---|---|---|
| `tests/test_ollama_gpu.py:25,125,150,175,190` | `_st._settings_path.write_text(...)` | DR4 — verify each call sits behind `monkeypatch.setattr` |
| `tests/test_letta_restart_live.py:43` | reads `Path.home() / ".ari" / "letta-pid"` | DR4 — `monkeypatch.setenv("ARI_LETTA_PIDFILE", ...)` fixture |
| `tests/test_settings_roundtrip.py:8` | docstring mentions `~/.ari/settings.json` | Phase 6 — comment edit |
| `tests/test_clone.py:190` | docstring | Phase 6 |
| `tests/test_paths.py:131` | comment ("no global ~/.ari anymore") | OK as-is |

## 10. Sub-plan map

| Plan | Owner |
|---|---|
| `REFACTORING.md` (root) | Master |
| `ari-core/REFACTORING.md` | cli/pipeline/core split + shared modules |
| `ari-core/ari/agent/REFACTORING.md` | agent/loop.py split + tests |
| `ari-core/ari/viz/REFACTORING.md` | viz server/api_state split |
| `ari-core/ari/orchestrator/REFACTORING.md` | node_report split + legacy isolation |
| `ari-core/ari/evaluator/REFACTORING.md` | prompt extraction + Evaluator Protocol |
| `ari-core/ari/memory/REFACTORING.md` | tier A/B/C cleanup |
| `ari-core/ari/publish/REFACTORING.md` | tier B cleanup |
| `ari-core/ari/clone/REFACTORING.md` | tier B cleanup (shares helper with publish) |
| `ari-core/ari/registry/REFACTORING.md` | tier B cleanup (`resolve_data_dir`) |
| `ari-core/tests/REFACTORING.md` | tier D test isolation |
| `ari-skill-coding/REFACTORING.md` | `ari.public.container` migration |
| `ari-skill-plot/REFACTORING.md` | `ari.public.cost_tracker` migration |
| `PROMPTS_AND_CONFIG.md` | Prompt/config externalisation master |
| `DEPRECATION_REMOVAL.md` | Tier classification + DR0–DR5 phases |
