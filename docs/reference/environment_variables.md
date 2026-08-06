---
sources:
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: scripts/setup/setup_env.sh
    role: config
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
last_verified: 2026-08-06
---

# Environment Variable Reference

ARI honours roughly 90 environment variables, drawn together here for
convenience.  Most have sensible defaults; the **Required?** column
flags the ones a fresh checkout cannot operate without.

`docs/reference/configuration.md` walks the same surface as a tutorial; this
page is the alphabetical lookup.

> v0.5.0 removed the global `$HOME/.ari/` directory.  Where this
> reference says "must be set", the legacy fallback emits a
> `DeprecationWarning` and disappears in v1.0.

## Core (`ARI_*`)

### Checkpoint + paths

| Variable | Purpose | Default | Required? |
|---|---|---|:---:|
| `ARI_CHECKPOINT_DIR` | Active checkpoint root | (none — must be set) | ✓ |
| `ARI_WORKSPACE` | Parent directory for new runs (used by orchestrator skill) | (none) | ✓ for `ari-skill-orchestrator` |
| `ARI_WORK_DIR` | Per-node working directory root (`ari-skill-coding`) | `/tmp/ari_work` | – |
| `ARI_LOG_DIR` | Application log directory | `$ARI_CHECKPOINT_DIR` | – |
| `ARI_ROOT` | ARI source tree root (used in tests) | (auto-detect) | – |
| `ARI_SOURCE_FILE` | Override input experiment.md path | (none) | – |

### LLM model selection

| Variable | Purpose | Default |
|---|---|---|
| `ARI_LLM_MODEL` | Default LiteLLM model id | (none) |
| `ARI_LLM_API_BASE` | LiteLLM API base override | LiteLLM default |
| `ARI_MODEL` | Cross-skill fallback model id | (falls through to `ARI_LLM_MODEL`) |
| `ARI_MODEL_EVAL` | Model for the LLM evaluator | falls through to `ARI_MODEL` |
| `ARI_MODEL_PAPER` | Model for paper writing and refinement | falls through to `ARI_LLM_MODEL` |
| `ARI_MODEL_RUBRIC` | Model for independent rubric review and the fixed paper panel | falls through to `ARI_LLM_MODEL` |
| `ARI_PANEL_SEED` | Requested seed recorded for each fixed-panel rubric completion | unset; sampling control is provider/backend dependent |
| `ARI_MODEL_JUDGE` | Model for the BFTS judge | falls through to `ARI_MODEL` |
| `ARI_MODEL_LINEAGE` | Model for stagnation / lineage decisions (v0.7.0) | falls through to `ARI_MODEL` |
| `ARI_MODEL_ROOT_SELECT` | Model that picks the seed idea | falls through to `ARI_MODEL` |
| `ARI_MODEL_IDEA` | Model for `generate_ideas` | falls through to `ARI_MODEL` |
| `ARI_MODEL_REPLICATE` | Model for replicator high-level reasoning (v0.7.0) | falls through to `ARI_MODEL` |
| `ARI_MODEL_REPLICATOR` | Model used by `ari-skill-paper-re.build_reproduce_sh` | falls through |
| `ARI_MODEL_RUBRIC_GEN` | Model for `ari-skill-replicate.generate_rubric` | falls through |
| `ARI_MODEL_RUBRIC_AUDIT` | Model for `ari-skill-replicate.audit_rubric` | falls through |
| `LLM_MODEL` | Cross-skill fallback (used by `ari-skill-transform`, `ari-skill-plot`) | (none) |
| `LLM_API_BASE` | API base for `LLM_MODEL` | (none) |

### Claude Code backend (`ARI_CLAUDE_CODE_*`)

Only read when `ARI_BACKEND=claude_code` /
`llm.backend: claude_code` — see
[claude_code_provider.md](./claude_code_provider.md).

| Variable | Purpose | Default |
|---|---|---|
| `ARI_CLAUDE_CODE_MODE` | `strict_reproducibility` (fresh `claude -p` per call) or `low_overhead` (resident Agent SDK worker, fresh query per request) | `strict_reproducibility` |
| `ARI_CLAUDE_CODE_MODEL` | Model override, applied only when the resolved backend is `claude_code` | `llm.model` |
| `ARI_CLAUDE_CODE_MAX_TURNS` | `--max-turns` per call (>1 needs `allow_multi_turn`) | `1` |
| `ARI_CLAUDE_CODE_TIMEOUT_SEC` | Per-call subprocess/SDK timeout | `300` |
| `ARI_CLAUDE_CODE_RECORD_PROVENANCE` | Persist per-call artifacts under `{checkpoint}/claude_code/{call_id}/` (`1`/`0`) | `1` |
| `ARI_CLAUDE_CODE_BIN` | Claude Code binary | `claude` |
| `ANTHROPIC_AUTH_TOKEN` | Token auth alternative to `ANTHROPIC_API_KEY`; either enables the hermetic `--bare` profile | (none) |

### Idea skill — VirSci-live

Opt-in vendor-wrap path for `generate_ideas`. Default-off keeps current
behaviour (the lightweight re-implemented discussion loop). When on, `generate_ideas`
runs VirSci's real multi-agent mechanism on a live Semantic Scholar snapshot; on
missing deps / any runtime error it degrades to the re-impl loop. The deliberation
LLM follows `ARI_MODEL_IDEA`.

| Variable | Purpose | Default |
|---|---|---|
| `ARI_IDEA_VIRSCI_REAL` | Toggle the real vendor-wrap path (`1`/true). Unset ⇒ current re-impl behaviour | (unset / off) |
| `ARI_IDEA_VIRSCI_K` | Discussion turns (vendor `group_max_discuss_iteration`) | `7` |
| `ARI_IDEA_VIRSCI_TEAM_SIZE` | Max team members (vendor `max_teammember`) | `3` |
| `ARI_IDEA_VIRSCI_N_AUTHORS` | Author pool size for `select_coauthors` | `16` |
| `ARI_IDEA_VIRSCI_N_PAPERS` | SPECTER2 retrieval corpus size | `800` |
| `ARI_IDEA_VIRSCI_MAX_TEAMS` | Cap on teams driven through `generate_idea` | `=n_ideas` |
| `ARI_IDEA_VIRSCI_SPECTER2_MODEL` | Local query embedder | `allenai/specter2_base` |

### BFTS exploration

| Variable | Purpose | Default |
|---|---|---|
| `ARI_MAX_NODES` | Hard cap on BFTS nodes | (workflow-controlled) |
| `ARI_MAX_DEPTH` | Hard cap on tree depth | (workflow-controlled) |
| `ARI_MAX_REACT` | ReAct iteration cap per node | (workflow-controlled) |
| `ARI_PARALLEL` | Concurrent node executors | `1` |
| `ARI_TIMEOUT_NODE` | Per-node wall-time cap (seconds) | (none) |
| `ARI_BFTS_ALLOW_WEB` | Opt-in: expose `web-skill` (web_search / fetch_url / arXiv / Semantic Scholar) to the BFTS node agent **during exploration**. Default-off keeps the search loop reproducible (P5); when on, ARI records a non-reproducible-trajectory marker (`bfts_web_provenance.json`). `idea-skill`'s `survey` already does a bounded literature lookup regardless. `1`/`true`/`yes`/`on` to enable | `false` |
| `ARI_RECURSION_DEPTH` | Current depth in nested ARI runs (auto-set) | (auto) |
| `ARI_MAX_RECURSION_DEPTH` | Cap for orchestrator recursion | `3` |
| `ARI_PARENT_RUN_ID` | Parent run id during recursion (auto-set) | (auto) |
| `ARI_DISABLED_TOOLS_FOR_CHILD` | Toolset trimmed for child runs | (none) |
| `ARI_REACT_MEMORY_SEARCH_LIMIT` | `search_memory` `top_k` ceiling | (skill default) |
| `ARI_NODE_EXEC_BUDGET_S` | Per-node wall-clock budget shared by all `run_bash` / `run_code` calls. A single call is capped by its own timeout, but nothing capped the sum, so one node could burn the whole per-node timeout on shell calls and be killed with no report at all. A call is refused once the budget is gone, and no single call is allowed to outlast what remains. `0` disables | `1800` |
| `ARI_V2_SUPPRESS_TOOLS` | Hide `describe_environment` / `run_code` / `emit_results` from the **search loop** (they stay available to every other phase and to other users of ARI). Each hidden call is a step returned to editing the kernel, which matters at a 20-step budget. Opt-in, because it is not a local trim: `system.md` gates *finishing* on `emit_results`, so enabling it also rewrites that sentence — otherwise the agent is left with a stop condition it cannot satisfy — and the evidence path a run is scored through changes with it. Paper-reproduction routes need exactly these tools, so nothing is hidden unless asked | (unset ⇒ every tool offered) |

### Parent→child handoff (`ARI_HANDOFF_*`)

Applied by `apply_handoff_env_overrides` **after** profile overrides, so an
explicit choice wins. `ARI_HANDOFF_MODE` rebuilds `HandoffConfig` so the
mode→channel resolution runs; the individual switches below then override single
channels for ablation. Config equivalents live under the `handoff:` block.

| Variable | Purpose | Default |
|---|---|---|
| `ARI_HANDOFF_MODE` | Selects the arm, e.g. `disabled` / `code_only` / `summary_only` / `code_plus_summary` / `code_plus_full_log` / `evidence_only` / `evidence_plus_reflection`. An unrecognised value is ignored. Also names the run directory by task + arm + seed | (config) |
| `ARI_HANDOFF_COPY_WORKDIR` | Whether the child inherits the parent's work_dir (the artifact/code channel) | (from mode) |
| `ARI_HANDOFF_AGENT_BLOCK` | Inject the parent's operational summary into the child's agent prompt | (from mode) |
| `ARI_HANDOFF_PLANNER_BLOCK` | Inject the parent's summary into the planner prompt | (from mode) |
| `ARI_HANDOFF_MEMORY_OFF` | Suppress the de-facto memory channel, so an arm receives no operational state beyond its explicit handoff channels | (from mode) |
| `ARI_HANDOFF_LOG_MODE` | `none` / `full` / `truncated` / `masked` — how much of the parent's execution log is passed | (from mode) |
| `ARI_HANDOFF_LOG_LIMIT` | Character cap on the injected parent log | `48000` |
| `ARI_HANDOFF_SUMMARY_FORM` | `extractive` / `rolling` / `failure_only` / `evidence` / `evidence_reflection` | (from mode) |
| `ARI_HANDOFF_SUMMARY_FIELDS` | Comma-separated allowlist of summary fields (field-drop ablation) | (all) |
| `ARI_HANDOFF_PAIRED_MODES` | Comma-separated arms to run paired within one invocation | (none) |

### Execution mode (RQGM)

| Variable | Purpose | Default |
|---|---|---|
| `ARI_MODE` | Execution-mode override: `simple_bfts` \| `ari_rqgm` (overrides `ari.mode` in workflow.yaml; invalid values warn and are ignored). RQGM activation additionally requires the `ARI_RQGM_ENABLED` interlock — any disagreement falls back to `simple_bfts`. `export_resolved_config_to_skill_env` `setdefault`s this to the *effective* mode for skill subprocesses (no skill reads it in v1). On `ari resume` the mode persisted in `rqgm_state.json` wins over this variable. See `docs/guides/execution_modes.md` | `simple_bfts` |
| `ARI_RQGM_ENABLED` | RQGM master-interlock override: `0`/`1`/`true`/`false` (overrides `rqgm.enabled` in workflow.yaml). Both this AND `ARI_MODE=ari_rqgm` must agree for the governance runtime to be constructed | `false` |
| `ARI_PAPER_AGENT_AS_JUDGE` | Agent-as-judge draft-scoring override: `0`/`1`/`true`/`false` (overrides `rqgm.paper.reviewer.agent_as_judge.enabled`; invalid values warn and are ignored). Applied by `apply_paper_env_overrides` with the same validate-before-assign posture as `ARI_PAPER_MODE` / `ARI_RQGM_PAPER_ENABLED`. Off ⇒ the deterministic, LLM-free venue-rubric scorer, so no live LLM call sits on the draft-scoring path (P2). On ⇒ a real `LLMClient`-backed reviewer scores each archive draft over the *same* venue-rubric axes, weighted by the ACTIVE governed `paper_reviewer` prompt's emphasis, and can read axes no deterministic reader can (`novelty`, `significance`); it fails open to the deterministic rubric on an LLM error, an unparseable reply or one covering too little of the rubric's axis weight. Only meaningful under the effective `rqgm_archive` paper mode (`ARI_PAPER_MODE=rqgm_archive` + `ARI_RQGM_PAPER_ENABLED=1`) | (unset ⇒ off) |

### Manuscript Complete

| Variable | Purpose | Default |
|---|---|---|
| `ARI_MANUSCRIPT_MODE` | New-attempt posture: `off` \| `audit` \| `enforce`. It is independent of research and paper modes; resume cannot rewrite a persisted attempt binding. | `off` |
| `ARI_MANUSCRIPT_REPAIR_POLICY` | Repair posture: `disabled` \| `explicit` \| `auto`. `auto` is invalid unless the effective manuscript mode is `enforce`. | `disabled` |

The additional `ARI_MANUSCRIPT_*_PATH`, budget, topology, and effective-policy
variables are private, scoped hand-offs installed by the paper dispatcher.
Operators should configure them through `workflow.yaml`, not export them
directly. See the [Manuscript Complete runbook](../guides/manuscript_complete_operations.md).

### Backend + executor

| Variable | Purpose |
|---|---|
| `ARI_BACKEND` | Backend selector for the agent runtime |
| `ARI_EXECUTOR` | Executor backend (sync / async) |
| `ARI_CONTAINER_IMAGE` | SIF / OCI image for sandboxed execution |
| `ARI_CONTAINER_MODE` | `exec` / `shell` (singularity invocation style) |
| `ARI_CONTAINERS_DIR` | Container image cache root |
| `ARI_MAX_CHILD_PROCS` | RLIMIT_NPROC cap inside the coding sandbox (default 1024) |
| `ARI_LOG_LEVEL` | Python `logging` level (`INFO` / `DEBUG` / ...) |

### Memory backend

| Variable | Purpose |
|---|---|
| `ARI_MEMORY_BACKEND` | `letta` (default) or `in_memory` (no Letta required; ephemeral RAM-only backend for local smoke tests) |
| `ARI_MEMORY_AUTO_RESTORE` | Auto-restore from `memory_backup.jsonl.gz` on resume |
| `ARI_MEMORY_ACCESS_LOG` | Path to `memory_access.jsonl` |
| `ARI_MEMORY_CONSOLIDATE` | Typed-memory consolidation + artifact-grounded `verified_context.json` for paper claims. **Default ON**; set `0`/`false`/`no`/`off` to disable |
| `ARI_CURRENT_NODE_ID` | Set by the agent loop; skills read it but never set it |
| `ARI_LETTA_VENV` | Virtualenv path for the bundled Letta server |

### Reviewer rubrics + paper review

| Variable | Purpose |
|---|---|
| `ARI_RUBRIC` | Selects which `reviewer_rubrics/<id>.yaml` is active |
| `ARI_RUBRIC_DIR` | Override rubric directory |
| `ARI_STRICT_DYNAMIC` | Force dynamic-axis generation for `ari-skill-paper` |
| `ARI_NUM_REFLECTIONS` | Reflection rounds in `review_compiled_paper` |
| `ARI_NUM_REVIEWS_ENSEMBLE` | Ensemble size for rubric review |
| `ARI_JUDGE_N_RUNS` | SimpleJudge re-run count for `grade_with_simplejudge` |

### Claim-evidence gate

| Variable | Purpose | Default |
|---|---|---|
| `ARI_CLAIM_GATE_MODE` | Claim-evidence / metric-correctness gate evaluation switch. `off` never blocks; `warn` reports errors/warnings but never blocks finalize; `strict` blocks the final gate when blocking errors exist | `warn` (`off` / `warn` / `strict`) |
| `ARI_COMPARISON_SCOPE` | Governs whether a cross-environment comparison is treated as a transparency warning (`any`) or a blocking error (`same_environment`, for single-architecture optimization studies) | `any` (`any` / `same_environment`) |

### Rubric auto-generation (v0.7.0)

| Variable | Purpose |
|---|---|
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | Target leaf count for `generate_rubric` |
| `ARI_RUBRIC_GEN_TEMPERATURE` | LLM temperature override |
| `ARI_RUBRIC_GEN_TWO_STAGE` | Use the two-stage skeleton + subtree synthesis |
| `ARI_PAPERBENCH_RUBRIC_DIR` | Override search root for venue-conditioned PaperBench rubric templates (unreleased — see `docs/reference/rubric_schema.md#venue-conditioned-templates`) |

### PaperBench reproducibility (v0.7.0)

| Variable | Purpose | Default |
|---|---|---|
| `ARI_PAPERBENCH_PATH` | Override the bundled `vendor/paperbench/` path | `vendor/paperbench/` |
| `ARI_REPLICATOR_TIME_LIMIT_SEC` | Wall-time cap for `run_reproduce` | `43200` (12 h) |
| `ARI_REPLICATOR_ITERATIVE` | Use the iterative replicator agent | – |
| `ARI_REPLICATOR_MAX_STEPS` | Iteration cap when iterative is on | – |

### Orchestrator skill

| Variable | Purpose | Default |
|---|---|---|
| `ARI_ORCHESTRATOR_PORT` | MCP server port | `9890` |
| `ARI_ORCHESTRATOR_LOGS` | Log directory | `$ARI_WORKSPACE/orchestrator_logs` |
| `ARI_ORCHESTRATOR_DRY_RUN` | Skip real `ari run` (smoke testing) | – |
| `ARI_ORCHESTRATOR_SSE_ONESHOT` | One-shot SSE response mode | – |
| `ARI_ORCHESTRATOR_SSE_TIMEOUT` | SSE timeout (seconds) | – |

### Transform skill

| Variable | Purpose |
|---|---|
| `ARI_TRANSFORM_MEMORY_MAX_CHARS` | Total memory budget per call |
| `ARI_TRANSFORM_MEMORY_MAX_ENTRIES` | Per-call entry cap |

### Web / retrieval skill

| Variable | Purpose |
|---|---|
| `ARI_RETRIEVAL_BACKEND` | `semantic_scholar` / `arxiv` / `alphaxiv` |

### Publish + registry + clone

| Variable | Purpose |
|---|---|
| `ARI_PUBLISH_DRYRUN` | Force `--dry-run` (CI safety, v0.7.0) |
| `ARI_PUBLISH_SETTINGS` | Path to a publish settings JSON |
| `ARI_REGISTRY_DATA` | sqlite + artifact root for `ari registry serve` (must be set) |
| `ARI_REGISTRY_TOKEN` | Bearer token for `ari clone ari://...` and `ari ear publish --backend ari-registry` |
| `ARI_REGISTRY_URL` | Override the registry endpoint |
| `ARI_REGISTRY_NAME` | Default registry name when multiple are listed |
| `ARI_REGISTRIES_FILE` | Override `registries.yaml` location (else looked up under the active checkpoint) |
| `ARI_LOCAL_TARBALL_OUT` | Output path for the `local-tarball` publish backend |
| `ARI_GH_REPO` | GitHub repo target for the `gh` backend |
| `ARI_GH_MODE` | `release` / `repo` mode for the `gh` backend |
| `ARI_CLONE_HTTP_TIMEOUT` | HTTP timeout for `ari clone` |

### SLURM defaults

| Variable | Purpose |
|---|---|
| `ARI_SLURM_PARTITION` | Default partition |
| `ARI_HPC_ALLOWED_NODES` | Site policy: the only nodes ARI may place work on, in SLURM hostlist syntax (`cn01,cn02`, `cn[01-04]`). Unset = no restriction, and requests pass through untouched. When set it is enforced at the scheduler boundary, so it covers `job_submit`, `container_submit` and `slurm_submit` alike: a request naming **no** nodes is confined to this set — without a nodelist the scheduler is free to pick any node in the partition, which is what the policy exists to prevent — and one naming anything outside it is refused before submission. Confinement is applied before the request digest, so where a job may run is part of its claim identity and a resumed run cannot inherit a claim made under a wider policy. A nodelist that cannot be expanded exactly is refused rather than admitted. Held in the environment, not a tracked file, because node names are site identity |
| `ARI_SLURM_CPUS` | Default `--cpus-per-task` |
| `ARI_SLURM_GPUS` | Default `--gres=gpu:N` |
| `ARI_SLURM_MEM_GB` | Default memory request |
| `ARI_SLURM_WALLTIME` | Default `--time` |
| `ARI_SLURM_ALLOW_NO_GRES` | `1` ⇒ when the cluster has no GRES configured for GPUs, silently drop `--gres` / `--gpus-*` flags (legacy v0.7.2 behaviour). Default (unset) ⇒ raise `RuntimeError` with an actionable message so a GPU request never silently runs on CPU. |

### PaperBench reproduction phase (Stage 2)

| Variable | Purpose |
|---|---|
| `ARI_PHASE1_SANDBOX` | `auto` / `local` / `docker` / `apptainer` / `singularity` / `slurm`. Forces the sandbox runner used by `server.run_reproduce` and `bridge.reproduce_submission`. |
| `ARI_PHASE1_DOCKER_IMAGE` | Default docker image when `sandbox_kind=docker` and no explicit `container_image` is supplied. Defaults to `ubuntu:24.04`. |
| `ARI_PHASE1_APPTAINER_IMAGE` | Default SIF / docker URI when `sandbox_kind=apptainer`/`singularity` and no explicit `container_image` is supplied. |
| `ARI_PHASE1_SINGULARITY_IMAGE` | Legacy alias for `ARI_PHASE1_APPTAINER_IMAGE`. |
| `ARI_PHASE1_ALLOW_FALLBACK` | `1` ⇒ when a requested sandbox tool is missing (docker daemon / apptainer / sbatch / partition), fall back to host-local execution with only a warning (legacy v0.7.2 behaviour). Default (unset) ⇒ raise `RuntimeError` so the user's isolation intent isn't silently bypassed. |
| `ARI_PAPERBENCH_PATH` | Override the vendored PaperBench source tree path (default: `ari-skill-paper-re/vendor/paperbench/project/paperbench`). |
| `ARI_REPLICATOR_TIME_LIMIT_SEC` | Default Stage 1 agent rollout time budget when the caller passes `0`. |
| `ARI_REPLICATOR_ITERATIVE` | `1` ⇒ default to IterativeAgent variant for Stage 1 rollouts. |
| `ARI_REPLICATOR_MAX_STEPS` | Default Stage 1 step cap. |
| `ARI_AGENT_ENV_PATH` | Default path to the vendor-style `agent.env` file (one `KEY=VALUE` per line) that `bridge.rollout_submission` auto-loads when its `agent_env_path` argument is unset. Falls back to `~/.ari/agent.env` when this is also empty. This vendored PaperBench-replicate credentials lookup (`ari-skill-paper-re/src/_paperbench_bridge.py`) is distinct from ARI's own `$HOME/.ari/` run storage removed in v0.5.0, so the fallback remains live. Used to surface per-paper credentials (e.g. `HF_TOKEN`) to the Stage 1 agent. |
| `HF_TOKEN` | Hugging Face Hub token. When set on the calling process, `bridge.rollout_submission` automatically forwards it into the agent's env (vendor `nano/eval.py:172-179` well-known-credential pattern). Required for any PaperBench paper whose Stage 1 rollout invokes `huggingface-cli login`. |
| `ARI_JUDGE_N_RUNS` | Default `n_runs` for the SimpleJudge call when the wizard / caller passes `0`. PaperBench paper §4.1 single-pass default is 1. |
| `ARI_MODEL_JUDGE` | Default judge model id (LiteLLM-routed). |
| `ARI_MODEL_REPLICATOR` | Default Stage 1 rollout model id. |

### GUI server (`ARI_GUI_*`)

Eight switches govern the `ari viz` dashboard shell, its network exposure and
its operational surfaces. All eight are declared (commented out) by
`scripts/setup/setup_env.sh`, and all are **rollback levers**: unsetting them
gives the current default, setting them restores a documented earlier
behaviour without a redeploy.

| Variable | Default (unset) | Effect when set | Rollback semantics |
|---|---|---|---|
| `ARI_GUI_V2` | on (`1`) | `0` / `false` reverts to the legacy dashboard shell. | Kill-switch for the v2 shell; removal gate G6. |
| `ARI_GUI_BIND` | loopback only (`127.0.0.1` + `::1`) | A bind address: `::` = legacy all-interfaces dual-stack, `0.0.0.0` = IPv4 wildcard, or a single address. | Restores the historical all-interfaces bind. Any non-loopback value switches the server into **remote mode** (see `ARI_GUI_TOKEN`). |
| `ARI_GUI_CORS_ANY` | off — same-origin echo only | `1` restores the legacy `Access-Control-Allow-Origin: *` wildcard. | Needed only for cross-origin tunnel/portal topologies; the Vite dev proxy on `:5173` does **not** need it. |
| `ARI_GUI_CHALLENGES` | on — challenges required | `0` disables the server-issued confirmation challenges on delete-checkpoint / stop / gpu-monitor-stop, restoring direct execution. | With it on, those endpoints answer `428` without a valid `challenge_id`; the issuing endpoint stays available either way. |
| `ARI_GUI_CSP` | on — headers sent | `0` drops `Content-Security-Policy`, `X-Content-Type-Options` and `Referrer-Policy` from the GUI index/static responses. | Only needed if a proxy topology remaps the WebSocket port and the policy blocks it (the GUI then degrades to polling). |
| `ARI_GUI_TOKEN` | unset | The bearer token remote mode requires: every request except the `/health*` prefix must send `Authorization: Bearer <token>`; SSE and WebSocket accept it as `?token=`. | Unset **while remote-bound** is fail-secure, not open: the server generates a random 32-hex token at startup and prints it once to stderr. Never required on the loopback default. |
| `ARI_GUI_AUTH` | on (in remote mode) | `0` disables the remote token gate, restoring an unauthenticated remote bind. | The documented escape hatch for a trusted network that terminates its own auth (e.g. an authenticating reverse proxy). Loopback binds are unauthenticated either way. |
| `ARI_GUI_HEALTH` | on | `0` disables the operational-visibility surfaces: `GET /health/live` and `/health/ready` fall back to the SPA response and `GET /api/v1/diagnostics` answers the typed 404. | Restores the exact pre-probe wire behaviour for probe-scraping topologies that must not see the new JSON. |

See [REST API → Authentication](rest_api.md#authentication) for the full trust
model and [REST API → Confirmation challenges](rest_api.md#confirmation-challenges)
for the challenge protocol.

## SLURM (`SLURM_*`)

| Variable | Purpose |
|---|---|
| `SLURM_MODE` | `local` (default) / `ssh` |
| `SLURM_SSH_HOST` | SSH host for remote SLURM mode |
| `SLURM_SSH_USER` | SSH user (defaults to current user) |
| `SLURM_SSH_PORT` | SSH port (default `22`) |
| `SLURM_SSH_KEY` | Private key path |
| `SLURM_SSH_PASSWORD` | Optional password (prefer key) |
| `SLURM_DEFAULT_PARTITION` | Default partition for sub-jobs ARI launches |
| `SLURM_PARTITION` | Per-job partition override |
| `SLURM_VALID_PARTITIONS` | Comma-separated allow-list |
| `SLURM_LOG_DIR` | Where to write `*.out` / `*.err` |
| `SLURM_CLUSTER_NAME` | Display name shown in the dashboard |
| `SLURM_JOB_ID` / `SLURM_JOB_NODELIST` / `SLURM_JOB_PARTITION` | Set by SLURM itself when ARI runs inside a job |

## Letta (`LETTA_*`)

| Variable | Purpose |
|---|---|
| `LETTA_BASE_URL` | Letta API base (default `http://127.0.0.1:8283`) |
| `LETTA_API_KEY` | API key when Letta requires auth |
| `LETTA_EMBEDDING_CONFIG` | Path to embedding config JSON (required) |

## Ollama / OpenAI (`OLLAMA_*` / `OPENAI_*`)

| Variable | Purpose |
|---|---|
| `OLLAMA_HOST` | Ollama listen address (default `127.0.0.1:11434`) |
| `OLLAMA_BASE_URL` | LiteLLM-side base URL |
| `OPENAI_API_KEY` | OpenAI / OpenAI-compatible API key |

## VLM

| Variable | Purpose | Default |
|---|---|---|
| `VLM_MODEL` | Vision LLM for figure / table review | `openai/gpt-4o` |

## See also

- `docs/reference/configuration.md` — narrative tour of the same env vars,
  grouped by use case.
- `ari-core/ari/config.py` — Pydantic settings model that consumes
  most of the `ARI_*` group.
- Each skill's `README.md` — env vars specific to that skill.
