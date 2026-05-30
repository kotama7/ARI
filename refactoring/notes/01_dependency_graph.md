# Dependency & Boundary Graph (baseline)

Produced by requirement `01_dependency_and_boundary_graph.md` (now deleted).
Task-control baseline note. Static inspection only — dynamic edges flagged in §6.
Captured on branch `refactoring` (2026-05-30).

Target direction (from `GLOBAL_RULES.md`):
`frontend component → hooks/context → services/api.ts|websocket.ts → REST/WS API`;
`routes → thin parse/format → viz service modules → core public/protocol interfaces`;
`skill → ari.public/ari.protocols → stable core`.

## 1. Frontend: raw `fetch()` in components (target = go through `services/`)

`services/api.ts` is the sanctioned wrapper (4 `fetch` calls, exposes `get<T>`/`post<T>`).
**7 components bypass it** with raw `fetch()` (17 calls total):

| Component | calls | lines (approx) |
|-----------|-------|------|
| `PaperBench/results/ResultsView.tsx` | 4 | 72,79,106,119 |
| `PaperBench/PaperBenchWizard.tsx` | 3 | 103,110,137 |
| `PaperBench/PaperImportDialog.tsx` | 3 | 53,75,~119 |
| `PaperBench/PaperRegistryPage.tsx` | 2 | 42,67 |
| `Tree/FileExplorer.tsx` | 2 | 179,213 |
| `Results/ResultsPage.tsx` | 1 | 2771 |
| `Monitor/MonitorPage.tsx` | 1 | 518 |

→ Requirement `02` (consolidate into `services/api.ts`). PaperBench cluster dominates.

## 2. Backend (`ari-core/ari/viz/*.py`) → core imports

Stable/public used: `ari.paths.PathManager` (widely), `ari.cost_tracker`.

**Reaches into private core internals** (candidates for `09`/boundary work):
- `api_state.py`: `ari.checkpoint.load_nodes_tree`, `ari.clone.clone/CloneError`, `ari.lineage._resolve_ckpt_by_run_id`
- `api_paperbench_worker.py`: `ari.config.{auto_config,_discover_skills,find_profile_yaml,package_config_root}`, `ari.mcp.client.MCPClient`
- `api_fewshot.py`: `ari.llm.client.LLMClient`, `ari.prompts.FilesystemPromptLoader`
- `api_experiment.py`: `ari.pidfile.{check_pid,read_pid,remove_pid}`
- `api_orchestrator.py`: `ari.pipeline._build_auto_append_block`
- `api_publish.py`: `ari.publish.{publish,promote,PublishError}`
- container helpers: `ari.container.{get_container_info,list_images,pull_image,ContainerConfig}` (multiple)
- memory: `ari_skill_memory.backends.get_backend` (3 files)

Viz files using `subprocess`: `api_experiment.py`, `api_fewshot.py`, `api_memory.py`,
`api_orchestrator.py`, `routes.py`, `server.py` (+ `state.py` stores Popen handles).
→ subprocess origination inside route/handler layer is a `05`/`12` concern.

## 3. Skills → `ari.*` classification

Clean (public only, mostly `ari.cost_tracker`): benchmark, evaluator, memory,
orchestrator, paper, plot, replicate, vlm, web.

**Reach into private internals** (feeds `09`):
- `ari-skill-coding`: `ari.agent.run_env`, `ari.container`
- `ari-skill-hpc`: `ari.agent.run_env`
- `ari-skill-idea`: `ari.lineage`
- `ari-skill-paper-re`: `ari.clone`, `ari.lineage`
- `ari-skill-transform`: `ari.orchestrator.node_selection`, `ari.publish`

Note: `ari.cost_tracker` and `ari.container` are exposed via `ari.public`, so a
skill importing `ari.container` directly (vs `ari.public.container`) is a path
violation even though the symbol is "public" — confirm exact import path per case in `09`.

## 4. Core purity violations (core → viz / frontend / concrete skill)

- `ari-core/ari/cli/commands.py:177` → `import ari.viz.server as viz_srv`
- `ari-core/ari/cli/lineage.py:151` → `from ari.viz.api_orchestrator import _api_launch_sub_experiment`

Both live in `ari.cli` (a thin wrapper) but import **private viz implementation**.
This is the only `core → ari.viz` edge set found. `ari_skill_memory` is imported
by `agent/loop.py`, `memory/auto_migrate.py`, `memory/letta_client.py`,
`pipeline/orchestrator.py` — expected (memory is tightly integrated), no other
`ari_skill_*` imported by core.

## 5. Side-effect origination

subprocess/SLURM/container/git originate in:
- viz handlers (see §2) — **route-layer subprocess** is the smell (`05`/`12`)
- core legitimate: `agent/run_env.py`, `clone/resolvers/gh.py`, `container.py`,
  `env_detect.py`, `llm/cli_server.py`, `memory_cli.py`, `pipeline/stage_runner.py`,
  `publish/backends/gh.py`
- SLURM config forwarded (not called directly) in `api_paperbench_worker.py` → MCP skill tools

## 6. Dynamic edges (static graph misses these)

- `ari/core.py`: `importlib.util` plugin load
- `ari/viz/api_paperbench.py`: `importlib.util.spec_from_file_location` (rubric defs)
- `ari/mcp/client.py`: spawns skill servers dynamically (subprocess + MCP dispatch)
- `ari/config`: `_discover_skills()` installed-skill discovery

## 7. Prioritized coupling list

| Pri | Issue | Blocks / routed to |
|-----|-------|--------------------|
| P1 | 7 components raw `fetch` | `02` (first impl requirement) |
| P1 | `routes.py` 1344 lines + route-layer subprocess | `05` |
| P2 | viz reaching private core internals | `06`/`09` contract work |
| P2 | 5 skills reaching private core internals | `09` |
| P2 | `core(cli) → ari.viz` private imports (2 edges) | boundary; address with `09`/`05` (introduce a public seam or move launch logic) |
| P3 | `state.py` 19 globals | constraint across `05`/`07`/`08` (do not expand) |
| P3 | LLM/HPC/container behind boundaries | `11`/`12` |

## 8. Proposed follow-ups (not implemented here)

- Boundary-enforcement lint (import-linter for Python, eslint rule banning raw
  `fetch` in components) — **proposed only**, route to a guard task.
- The `core(cli) → ari.viz` edge is not explicitly owned by any single `02`–`14`
  file; recommend `09` (core/skill public contract) absorb a "core must not import
  viz private modules" clause, or `05` expose a public launch seam. Recorded as a
  follow-up candidate rather than silently left.

## Reproducible commands

```bash
# raw fetch in components
grep -rn "fetch(" ari-core/ari/viz/frontend/src --include="*.tsx" --include="*.ts" | grep -v ".test."
# viz -> ari imports
grep -h "from ari\|import ari" ari-core/ari/viz/*.py | sort -u
# skill -> ari imports
for d in ari-skill-*/src; do grep -rh "from ari\|import ari" "$d"; done | sort -u
# core -> viz violations
grep -rn "from ari.viz\|import ari.viz" ari-core/ari --include="*.py" | grep -v "/viz/"
# subprocess origins
grep -rln "subprocess\." ari-core/ari --include="*.py"
# dynamic imports
grep -rn "importlib\|__import__" ari-core/ari --include="*.py"
```
