---
sources:
  - path: ari-core/ari/llm/routing.py
    role: implementation
  - path: ari-core/ari/cost_tracker.py
    role: implementation
  - path: ari-core/ari/llm/client.py
    role: implementation
  - path: ari-core/ari/container.py
    role: implementation
  - path: ari-core/ari/mcp/client.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/ari/pipeline/orchestrator.py
    role: implementation
  - path: ari-core/ari/viz/state.py
    role: implementation
last_verified: 2026-06-10
---

# Internal boundaries

How ARI talks to the three things it cannot do in pure Python: **LLM
providers**, **the OS / schedulers / containers**, and **the two orchestration
engines**. This is contributor-facing reference: where the boundary lives, what
the sanctioned call shape is, and the concurrency hazards any change here must
preserve. (For the stable cross-package surface see
[public_api.md](public_api.md); for config precedence see
[configuration.md](configuration.md); for on-disk layout see
[glossary.md](glossary.md) and [Architecture](../concepts/architecture.md).)

## LLM boundary

ARI's LLM boundary is **not** "everything must call `LLMClient`". It is a
three-part pattern, and direct `litellm.{completion,acompletion}` calls are the
**sanctioned** shape:

1. **`litellm`** is the provider-abstraction layer — modules call
   `litellm.completion` / `acompletion` directly with a model id.
2. **`ari.llm.routing.resolve_litellm_model(model, backend)`** is the single
   model-normalisation helper. It applies the provider prefix (including the
   CLI-shim `openai/claude-cli` rule) so a bare model name routes correctly.
3. **`ari.cost_tracker._install_litellm_metadata_injector()`** monkey-patches
   `litellm.completion`/`acompletion` **process-wide** to (a) merge default cost
   metadata (skill / phase / node) and (b) apply `_apply_ari_routing`
   (`resolve_litellm_model` + CLI-shim `api_base` fill-in) on every call. Once
   installed, *every* direct litellm call — from any module or skill — gets ARI
   routing + cost capture transparently, at one point.

`ari.llm.client.LLMClient` is a **convenience wrapper** over `litellm.completion`
used by the ReAct agent loop; it is **not** a mandatory chokepoint, and the
codebase deliberately does not funnel everything through it.

The injector is installed via `cost_tracker.set_default_metadata` /
`init_from_env`, reached through `bootstrap_skill("<name>")` at the top of every
skill `server.py`.

**Fragility to preserve:** CLI-shim routing and cost capture depend on the
injector being installed **before the first litellm call** in a process. Skills
guarantee this at import via `bootstrap_skill`. Core CLI/pipeline modules
(`evaluator`, `orchestrator/lineage_decision`, `root_idea_selector`,
`pipeline/context_builder`) call litellm directly and pass `api_base`/model
themselves, so they route correctly even without the global injector — but they
would miss cost capture if it is absent. `pipeline/context_builder` is the one
pipeline-package direct call that does its own env resolution rather than
`resolve_litellm_model` (a known low-value seam).

## Execution boundary (OS / scheduler / container)

Sanctioned exec modules — changes to execution behaviour belong here:

| Module | Owns |
|--------|------|
| `ari/container.py` | container exec: `detect_runtime`, `build_run_cmd`, `run_in_container` (Popen + `_sandbox_preexec` = `os.setsid` new process group + optional `RLIMIT_NPROC` via `ARI_MAX_CHILD_PROCS`), `_run_with_timeout` (group SIGTERM→SIGKILL), `pull_image`, `exec_in_container`. Re-exported by `ari.public.container`. |
| `ari/env_detect.py` | scheduler/runtime probes (`sinfo`, `qstat`, `docker info`, `lscpu`) — read-only, best-effort, no hardcoded cluster knowledge. |
| `ari/mcp/client.py` | spawns skill stdio servers via the MCP SDK `stdio_client` (a wrapper, not a raw spawn). |
| `ari-skill-hpc/src/slurm.py` | the canonical SLURM submit/status/cancel (`SlurmClient`: `_run_local` asyncio subprocess, `_run_remote` paramiko), incl. `ARI_SBATCH_EXPORT_MODE` clean-env logic. |

Known duplication to consolidate toward these owners (not incorrect behaviour,
but drift risk): `viz/api_memory.py` re-derives container-runtime dispatch;
`ari-skill-paper-re/src/server.py` re-implements `sbatch`/`apptainer exec` and
already diverges from `slurm.py` (it hardcodes `--export ALL`); its local
fallback lacks `setsid`/`killpg`, so a hung reproduce can orphan.

**`ari.viz.state` process-handle coupling.** `ari/viz/state.py` holds live OS
handles as module globals (imported as `_st`): `_last_proc` (most-recent
experiment Popen; torn down by `api_process._api_stop` via
`os.killpg(os.getpgid(pid))`), `_running_procs` (checkpoint-path→Popen map,
written by the two launch paths), and `_gpu_monitor_proc` (its logic lives in
`api_process.py`; the server reaps a stale monitor across restarts). This is the
canonical example of the "avoid hidden coupling through global mutable state"
caution — touch its lifecycle only deliberately.

## The two orchestration engines

The runtime is **two distinct engines**, not one linear pipeline — `workflow.yaml`
declares phase tags (`bfts`, `paper`) but the split is across:

| Phase | Driver |
|-------|--------|
| **BFTS** | `cli/bfts_loop.py:_run_loop` — a hardcoded `while pending or frontier` loop (generate_idea → select_and_run → evaluate → frontier_expand). `bfts_pipeline[]` is read only for enabled/disabled flags. |
| **post-BFTS pipeline** (transform / figures / paper / review / ORS reproduction / publish) | `core.generate_paper_section` → `pipeline.orchestrator.run_pipeline` — a single linear cursor loop over `pipeline[]`; all sub-phases are consecutive stages. |

`run.py` clears `.pipeline_started`; `orchestrator` touches it at pipeline start
(GUI phase detection). A BFTS-sanity gate can abort the post-BFTS pipeline early
(`ARI_FORCE_PAPER` overrides). Non-`react:` stages run via
`stage_runner._run_stage_subprocess`, which builds a Python script string and
`subprocess.run([sys.executable, "-c", ...])` — each non-react stage is a direct
fork that constructs its own `MCPClient` in the child.

### Concurrency hazards (preserve under any change here)

1. **Env-var-at-fork timing.** MCP servers snapshot `os.environ` at spawn.
   `ARI_WORK_DIR` and the sandbox vars (`ARI_REAL_GIT`, `ARI_REPRO_*`, `PATH`)
   must be set **before** `MCPClient` spawns; deferring MCP construction or
   reordering env setup silently breaks sandboxing / work-dir pinning.
2. **Shared-process global-env race under parallel workers.** Up to 4
   `AgentLoop` threads share one process and one `MCPClient`. Memory
   copy-on-write keys off the process-global `ARI_CURRENT_NODE_ID`; the only safe
   write path is `mcp.call_tool(name, args, cow_node_id=node_id)` (it serializes
   the set-node+write pair under `MCPClient._cow_lock`). A per-run single
   `_set_current_node` is unsafe at `max_parallel_nodes > 1`.
3. **Shared checkpoint-tree writes.** There is **no git worktree**: concurrent
   committers all write the same `tree.json` / `nodes_tree.json` / `results.json`
   via one shared `agent._progress_cb` → `_save_tree_incremental`; thread-safety
   + throttle live in `ari.checkpoint.save_tree_incremental` (lock + mtime
   throttle). Per-node work-dirs are isolated by
   `PathManager.node_work_dir(run_id, node_id)`.
