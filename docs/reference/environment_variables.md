# Environment Variable Reference

ARI honours roughly 90 environment variables, drawn together here for
convenience.  Most have sensible defaults; the **Required?** column
flags the ones a fresh checkout cannot operate without.

`docs/configuration.md` walks the same surface as a tutorial; this
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

### BFTS exploration

| Variable | Purpose | Default |
|---|---|---|
| `ARI_MAX_NODES` | Hard cap on BFTS nodes | (workflow-controlled) |
| `ARI_MAX_DEPTH` | Hard cap on tree depth | (workflow-controlled) |
| `ARI_MAX_REACT` | ReAct iteration cap per node | (workflow-controlled) |
| `ARI_PARALLEL` | Concurrent node executors | `1` |
| `ARI_TIMEOUT_NODE` | Per-node wall-time cap (seconds) | (none) |
| `ARI_RECURSION_DEPTH` | Current depth in nested ARI runs (auto-set) | (auto) |
| `ARI_MAX_RECURSION_DEPTH` | Cap for orchestrator recursion | `3` |
| `ARI_PARENT_RUN_ID` | Parent run id during recursion (auto-set) | (auto) |
| `ARI_DISABLED_TOOLS_FOR_CHILD` | Toolset trimmed for child runs | (none) |
| `ARI_REACT_MEMORY_SEARCH_LIMIT` | `search_memory` `top_k` ceiling | (skill default) |

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
| `ARI_MEMORY_BACKEND` | `letta` (default since v0.6) / `file` / `local` |
| `ARI_MEMORY_AUTO_RESTORE` | Auto-restore from `memory_backup.jsonl.gz` on resume |
| `ARI_MEMORY_ACCESS_LOG` | Path to `memory_access.jsonl` |
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
| `ARI_SLURM_CPUS` | Default `--cpus-per-task` |
| `ARI_SLURM_GPUS` | Default `--gres=gpu:N` |
| `ARI_SLURM_MEM_GB` | Default memory request |
| `ARI_SLURM_WALLTIME` | Default `--time` |

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

- `docs/configuration.md` — narrative tour of the same env vars,
  grouped by use case.
- `ari-core/ari/config.py` — Pydantic settings model that consumes
  most of the `ARI_*` group.
- Each skill's `README.md` — env vars specific to that skill.
