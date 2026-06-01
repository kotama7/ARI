# Pipeline / Workflow / Phase Boundary (requirement 10)

Task-control note from `10_pipeline_workflow_phase_boundary.md`. Captured
2026-05-30 from a 3-agent map of the orchestration layer. **Documentation-only**
(§5: document the model + propose seams; out of scope: any pipeline rewrite or
YAML-semantics change). No production code changed by this requirement.

## 1. Phase model — there are TWO engines, not one linear pipeline

`workflow.yaml` declares two phase tags (`bfts`, `paper`); the ORS reproduction
stages also run under `paper`. But the runtime split is across **two distinct
engines**:

| Phase | Engine / driver | Notes |
|-------|-----------------|-------|
| **BFTS** | `cli/bfts_loop.py:_run_loop` (NOT the pipeline pkg) | `bfts_pipeline[]` is read only for enabled/disabled flags; the real loop (generate_idea → select_and_run → evaluate → frontier_expand) is hardcoded in the `while pending or frontier` loop. `frontier_expand.loop_back_to` is realized by that outer loop, not the pipeline loop_back machinery. |
| **BFTS → post-BFTS transition** | `cli/run.py:run()` → `core.py:generate_paper_section()` (run.py:391) | Resolves the checkpoint-local `workflow.yaml`, then hands off. |
| **post-BFTS pipeline** (transform / figures / paper / review) | `core.py:generate_paper_section` → `pipeline.load_pipeline` → `pipeline/orchestrator.py:run_pipeline` (core.py:280) | A single linear stage loop over `pipeline[]`. All post-BFTS sub-phases are just consecutive entries. |
| **reproduction (ORS)** | same `run_pipeline` loop | `ors_generate_rubric / ors_seed_sandbox / ors_build_reproduce / ors_run_reproduce / ors_grade` — ordinary pipeline[] stages, no separate driver. |
| **publish** | same `run_pipeline` loop | `ear_publish`, `finalize_paper` — ordinary stages. |

Phase markers: `run.py:367` clears `.pipeline_started`; `orchestrator.py:155`
touches it at pipeline start (GUI phase detection). A BFTS-sanity gate
(`orchestrator.py:463-495`, `ARI_FORCE_PAPER` override) can abort the whole
post-BFTS pipeline early (`{"_aborted": …}`).

## 2. Single-stage state machine (`run_pipeline` loop, orchestrator.py:506-862)

Index-cursor loop (so `loop_back` can rewind). Per stage, in order: disabled_tools
skip → depends_on resolution → skip_if_exists → input resolution (`params`/`inputs`/
`*_from`/`load_inputs`, plus paper_text/actual_metrics back-compat) → dispatch
(`react:` → `stage_runner._run_react_stage`, else `_run_stage_subprocess` with
5-retry transient backoff) → output save (`.tex`+bib / pdf / json / figures_manifest)
→ loop_back (`stage_control._should_loop_back`, capped by `loop_max_iterations`) →
failure path (log + `{"error":…}`, advance; downstream `depends_on` skips). The
`_run_react_stage` lazy-delegator (orchestrator.py:43-55) exists for test
monkeypatching — itself a signal that a seam is wanted.

## 3. Where orchestration touches concrete side effects (seam candidates)

- **Direct LLM call** (the one bypass of `ari.llm.client.LLMClient`):
  `context_builder.py:_extract_keywords_from_nodes` (107-138) imports `litellm`
  and calls `litellm.completion()` directly with its own ARI_MODEL/ARI_BACKEND
  resolution. **Strongest seam candidate** — route through `LLMClient`.
- **Subprocess (the MCP boundary)**: `stage_runner._run_stage_subprocess`
  (331-471) does NOT call `MCPClient` in-process — it builds a Python script
  string and `subprocess.run([sys.executable, "-c", script], timeout=5400)`; the
  child constructs `MCPClient` + `load_config` + `call_tool`. So every non-react
  stage is a direct fork. It also reads `~/.env` line-by-line into the child env.
- **Direct filesystem I/O** throughout `run_pipeline` (raw `Path.read_text/
  write_text`, `shutil.copy2`, `.touch()`) — no FS interface.
- **Env mutation**: `PathManager.set_checkpoint_dir_env` (orchestrator.py:151)
  and `ARI_WORK_DIR` set before MCP spawn.

## 4. BFTS / ReAct plug points

- **BFTS construction**: `core.py:build_runtime` (line 83) builds
  `BFTS(cfg.bfts, bfts_llm)` + `AgentLoop(...)` and returns them in a tuple — the
  single construction seam.
- **BFTS invocation**: `cli/run.py` → `_run_loop(...)`; `run.py._run_loop` and
  `cli/__init__._run_loop` are thin lazy delegators to `cli/bfts_loop._run_loop`
  (test-monkeypatch seam).
- **Engine boundary**: `bfts_loop._run_loop` depends on four BFTS methods
  (`select_best_to_expand`, expand, evaluate, `should_prune`) — the real
  algorithm seam — plus `agent` ReAct execution.
- **ReAct**: `agent/react_driver.run_react` invoked from
  `stage_runner._run_react_stage` (pipeline `react:` stages) and from the BFTS
  per-node execution; tool dispatch + phase filtering in `agent/tool_manager`.

## 5. Concurrency hazards any future seam MUST preserve (§11)

1. **Env-var-at-fork timing**: MCP servers snapshot `os.environ` at spawn.
   `ARI_WORK_DIR` and the `setup_sandbox_shims` vars (ARI_REAL_GIT, ARI_REPRO_*,
   PATH) must be set **before** `MCPClient` spawns; deferring MCP construction or
   reordering env setup silently breaks sandboxing/work-dir pinning.
2. **Shared-process global-env race** under parallel workers: ≤4 `AgentLoop`
   threads share ONE process + ONE `MCPClient`. Memory CoW keys off the
   process-global `ARI_CURRENT_NODE_ID`; the only safe path is
   `mcp.call_tool(name, args, cow_node_id=node_id)` (serializes the
   set-node+write pair under `MCPClient._cow_lock`). A per-run single
   `_set_current_node` is unsafe at `max_parallel_nodes > 1`.
3. **Shared checkpoint-tree writes** ("the worktree"): there is **no git
   worktree** — concurrent committers all write the same `tree.json` /
   `nodes_tree.json` / `results.json` via one shared `agent._progress_cb` →
   `_save_tree_incremental`; thread-safety + throttle live in
   `ari.checkpoint.save_tree_incremental` (lock + mtime throttle). Per-node
   work-dirs are isolated by `PathManager.node_work_dir(run_id, node_id)`. Any
   staging/commit-touching seam must keep finalizing stages promptly (§7).

## 6. How viz observes/drives phases

`viz/api_workflow.py` converts `workflow.yaml` ⇄ a React Flow DAG
(`workflow_yaml_to_flow` / `flow_to_workflow_yaml` / `_merge_stages` /
`_normalize_phase_value`) and saves edits back to the checkpoint copy. It can
toggle `enabled`, reorder/edit stages, and set `disabled_tools` — but the actual
phase *ordering* is whatever `pipeline[]` lists; it cannot change the two-engine
split. `WorkflowPage.tsx` (~1720 lines) holds the DAG edit state (a req-03/15
decomposition target — **not** touched here).

## 7. Seam proposals (ALL PROPOSE-ONLY — implementation is a separate requirement)

Ranked value/risk (per §5 "propose, do not implement"):

1. **[HIGH value / LOW risk] FlowMapping seam in `api_workflow.py`** — the 5
   handlers copy-paste the same workflow.yaml path-resolution block (lines
   275-282, 307-312, 391-396, 426-431, 450-452); the converters are already pure.
   Inject the read/write as one function, keep converters pure → unit-testable
   without disk, removes 5× duplication. (Overlaps the req-08 finder-migration
   follow-up.)
2. **[HIGH value / LOW-MED risk] A canonical Stage schema** shared by editor +
   runtime. Today `_FLOW_FIELDS` (api_workflow.py:149), the orchestrator's
   `stage_cfg.get(...)` reads, and the frontend's hand-built `node.data`
   serialization each independently enumerate stage fields — the source of
   silent `pre_tool`/`post_tool`/`react`/edge-condition field loss. A single
   declared Stage type (marking editor-owned vs preserve-only) would codify
   today's behavior. Crosses py↔ts; keep behavior-preserving.
3. **[MED value / MED risk] A StageRunner protocol** (`run(stage_cfg, args, ctx)
   -> result`) so the orchestrator depends on an interface and tests/dry-run can
   inject a no-op runner. The `_run_react_stage` lazy-delegator already signals
   the need. Enables testability without subprocess forks.
4. **[MED value] Route `context_builder` keyword extraction through `LLMClient`**
   (close the one direct `litellm.completion()` bypass).

## 8. Checks

No production code changed. `pytest ari-core/tests` and
`bash scripts/run_all_tests.sh` remain green (recorded for this requirement as a
no-op baseline confirmation: 2231 / 2843 passed respectively, unchanged from req
09). Environment-sensitive phase transitions (real BFTS run, SLURM ORS) are
compute-node-gated and not exercised on the login node — documented, not skipped.

## 9. Follow-up candidates (→ §12)

- Implement seam #1 (FlowMapping) — small, low-risk; coordinate with the req-08
  workflow.yaml-discovery finder migration.
- Implement seam #2 (Stage schema) — a dedicated requirement; fixes the
  field-loss bug class.
- Implement seam #3 (StageRunner protocol) and #4 (LLMClient for context_builder)
  — dedicated requirements; each must preserve the §5 concurrency hazards above.
- Decompose `WorkflowPage.tsx` — coordinate with req-03/15.
