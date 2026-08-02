---
sources:
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/mcp/child_environment.py
    role: implementation
  - path: ari-core/ari/skill_manifest.py
    role: implementation
last_verified: 2026-08-02
---

# Environment Variable Reference

ARI honours roughly 90 environment variables, drawn together here for
convenience.  Most have sensible defaults; the **Required?** column
flags the ones a fresh checkout cannot operate without.

`docs/reference/configuration.md` walks the same surface as a tutorial; this
page is the alphabetical lookup.

## Skill subprocess isolation

Built-in Skill subprocesses do not inherit the full parent environment. Each
`skill.yaml` has `environment_policy: complete`; only the small platform/TLS
baseline, core-owned isolated runtime variables, declared ordinary variables,
and present variables in a named credential scope cross the process boundary.
Static undeclared or unresolvable dynamic environment reads fail manifest CI.

Credential values are never written to manifests, `SKILLS.lock`, result
provenance, HTTP MCP config payloads, or traces. Those surfaces carry only scope
IDs and environment variable names/presence. Provider responses and stderr are
redacted, and reconnect is refused if scope presence changes. The manifest is
the normative per-Skill allowlist; this page documents the union of supported
operator settings.

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
| `ARI_MODEL_EVAL` | Model for the core BFTS evaluator (legacy shared alias; not read by `ari-skill-evaluator`) | falls through to `ARI_MODEL` |
| `ARI_MODEL_METRIC_PROPOSAL` | Model for the explicit evaluator-skill metric proposal | falls through to `ARI_LLM_MODEL` |
| `ARI_MODEL_SEMANTIC_REVIEW` | Model for the evaluator-skill semantic advisory | falls through to `ARI_LLM_MODEL` |
| `ARI_SEMANTIC_REVIEW_MODEL_REVISION` | Recorded semantic-review model revision | (none) |
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
| `ARI_MEMORY_AUTO_RESTORE` | Validate and restore from `memory_backup.v1.json.gz` on resume |
| `ARI_MEMORY_ACCESS_LOG` | Path to `memory_access.jsonl` |
| `ARI_MEMORY_CONSOLIDATE` | Typed-memory consolidation + artifact-grounded `verified_context.json` for paper claims. **Default ON**; set `0`/`false`/`no`/`off` to disable |
| `ARI_LETTA_VENV` | Virtualenv path for the bundled Letta server |

### Reviewer rubrics + paper review

| Variable | Purpose |
|---|---|
| `ARI_RUBRIC` | Selects BFTS dynamic evaluation axes and is read only by the offline paper-rubric migration helper; paper runtime selection requires explicit `rubric_id` |
| `ARI_RUBRIC_DIR` | Override the directory containing explicitly selected paper rubrics |
| `ARI_MODEL_PAPER_PROVIDER` | Provenance provider identity recorded for paper model calls |
| `ARI_MODEL_PAPER_REVISION` | Optional immutable model revision recorded for paper model calls |
| `ARI_STRICT_DYNAMIC` | Force BFTS dynamic-axis generation |
| `ARI_NUM_REFLECTIONS` | Reflection rounds in `review_compiled_paper` |
| `ARI_NUM_REVIEWS_ENSEMBLE` | Ensemble size for rubric review |
| `ARI_JUDGE_N_RUNS` | SimpleJudge re-run count for `grade_with_simplejudge` |

### Claim-evidence gate

| Variable | Purpose | Default |
|---|---|---|
| `ARI_CLAIM_GATE_MODE` | Claim/evidence gate switch. `off` never blocks; `warn` blocks only final objective-integrity findings; `strict` also blocks configured final findings | `warn` (`off` / `warn` / `strict`) |
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
| `ARI_PAPERBENCH_PATH` + `ARI_PAPERBENCH_COMMIT` | Exact-commit-only override of the reviewed PaperBench source | vendored commit |
| `ARI_REPLICATOR_TIME_LIMIT_SEC` | Wall-time cap for `run_reproduce` | `43200` (12 h) |
| `ARI_REPLICATOR_ITERATIVE` | Use the iterative replicator agent | – |
| `ARI_REPLICATOR_MAX_STEPS` | Iteration cap when iterative is on | – |

### Orchestrator skill

| Variable | Purpose | Default |
|---|---|---|
| `ARI_ORCHESTRATOR_HTTP_HOST` / `ARI_ORCHESTRATOR_HTTP_PORT` | MCP Streamable HTTP bind address | `127.0.0.1` / `9890` |
| `ARI_ORCHESTRATOR_HTTP_TOKENS_FILE` | Required mode-0600 bearer-token digest file for network transport | – |
| `ARI_ORCHESTRATOR_LOGS` | Checkpoint and durable registry root | `$ARI_WORKSPACE/logs` |
| `ARI_ORCHESTRATOR_DRY_RUN` | Skip real `ari run` (smoke testing) | – |
| `ARI_ORCHESTRATOR_MAX_ACTIVE_RUNS` | Deployment-wide active-run ceiling | `16` |
| `ARI_ORCHESTRATOR_MAX_TOTAL_NODES` | Per-lineage deployment node ceiling | `10000` |
| `ARI_ORCHESTRATOR_MAX_COST_USD` | Per-lineage deployment cost ceiling | `10000` |

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
| `ARI_SCHEDULER_PATH` | Fixed executable search path for shell-free scheduler control commands. Parent `PATH` is not inherited. |

### PaperBench reproduction phase (Stage 2)

| Variable | Purpose |
|---|---|
| `ARI_PHASE1_SANDBOX` | `auto` / `local` / `docker` / `apptainer` / `singularity` / `slurm`. Forces the sandbox runner used by `server.run_reproduce` and `bridge.reproduce_submission`. |
| `ARI_PHASE1_DOCKER_IMAGE` | Docker image when no explicit `container_image` is supplied. Use a full `sha256:<image-id>` or `name@sha256:<digest>`; no mutable default exists. |
| `ARI_PHASE1_APPTAINER_IMAGE` | Local non-symlink SIF or digest-pinned remote URI for Apptainer/Singularity when no explicit `container_image` is supplied. |
| `ARI_PAPERBENCH_PATH` | Optional PaperBench project override. Requires an exact reviewed Git identity and `ARI_PAPERBENCH_COMMIT`; arbitrary source trees are rejected. |
| `ARI_PAPERBENCH_COMMIT` | Commit claim required with `ARI_PAPERBENCH_PATH`; currently `51052cede8cc608f95bb00346635e03759013e5a`. |
| `ARI_REPLICATOR_TIME_LIMIT_SEC` | Default Stage 1 agent rollout time budget when the caller passes `0`. |
| `ARI_REPLICATOR_ITERATIVE` | `1` ⇒ default to IterativeAgent variant for Stage 1 rollouts. |
| `ARI_REPLICATOR_MAX_STEPS` | Default Stage 1 step cap. |
| `ARI_AGENT_ENV_PATH` | Credential-scoped default path to the vendor-style `agent.env` file (one `KEY=VALUE` per line) that `bridge.rollout_submission` loads when its `agent_env_path` argument is unset. The Skill receives an isolated `HOME`, so an operator home-directory fallback is not available through the normal ARI launch path. Used to surface explicitly approved per-paper credentials to the Stage 1 agent. |
| `HF_TOKEN` | Hugging Face Hub token. When set on the calling process, `bridge.rollout_submission` automatically forwards it into the agent's env (vendor `nano/eval.py:172-179` well-known-credential pattern). Required for any PaperBench paper whose Stage 1 rollout invokes `huggingface-cli login`. |
| `ARI_JUDGE_N_RUNS` | Default `n_runs` for the SimpleJudge call when the wizard / caller passes `0`. PaperBench paper §4.1 single-pass default is 1. |
| `ARI_MODEL_JUDGE` | Default judge model id (LiteLLM-routed). |
| `ARI_MODEL_REPLICATOR` | Default Stage 1 rollout model id. |

## SLURM (`SLURM_*`)

| Variable | Purpose |
|---|---|
| `SLURM_MODE` | `local` (default) / `remote` (`ssh` remains accepted as an alias) |
| `SLURM_SSH_HOST` | SSH host for remote SLURM mode (required) |
| `SLURM_SSH_USER` | Explicit SSH user (required in remote mode) |
| `SLURM_SSH_PORT` | SSH port (default `22`) |
| `SLURM_SSH_KNOWN_HOSTS` | Absolute reviewed known-hosts file; unknown or mismatched keys fail closed |
| `SLURM_SSH_KEY` | Credential-scoped absolute private-key path; implicit user keys and agents are disabled |
| `SLURM_SSH_PASSWORD` | Credential-scoped explicit password alternative |
| `SLURM_SSH_CONNECT_TIMEOUT` | SSH connect/banner/auth timeout in seconds (default `15`) |
| `SLURM_COMMAND_TIMEOUT` | Scheduler control-command timeout in seconds (default `30`) |
| `SLURM_SHARED_FILESYSTEM` | Whether MCP and compute nodes share exact absolute artifact paths (default `true`) |
| `SLURM_DEFAULT_PARTITION` | Default partition for sub-jobs ARI launches |
| `SLURM_PARTITION` | Per-job partition override |
| `SLURM_VALID_PARTITIONS` | Legacy PaperBench allow-list; canonical `JobRequestV1` validates its explicit partition atom |
| `SLURM_LOG_DIR` | Where to write `*.out` / `*.err` |
| `SLURM_CLUSTER_NAME` | Display name shown in the dashboard |
| `ARI_HPC_LEDGER_PATH` | Absolute durable idempotency ledger path for scheduler submissions |
| `ARI_SCHEDULER_PATH` | Minimal PATH used only to resolve scheduler control binaries |
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

### Credential scopes

The `model.provider` scope recognizes provider credentials including
`ANTHROPIC_API_KEY`, AWS access/secret/session credentials,
`AZURE_API_KEY`, `AZURE_OPENAI_API_KEY`, `COHERE_API_KEY`,
`DATABRICKS_API_TOKEN`, `DEEPINFRA_API_KEY`, `DEEPSEEK_API_KEY`,
`GEMINI_API_KEY`, `GOOGLE_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`,
`GROQ_API_KEY`, `MISTRAL_API_KEY`, `OPENAI_API_KEY`,
`OPENROUTER_API_KEY`, `REPLICATE_API_TOKEN`, `TOGETHERAI_API_KEY`,
`VERTEXAI_CREDENTIALS`, `WATSONX_APIKEY`, and `XAI_API_KEY`. A Skill receives
only the scopes declared in its own manifest. Hugging Face, Semantic Scholar,
Letta, scheduler SSH, and PaperBench agent-env
authority use separate scopes so they need not be granted with model access.

## VLM

| Variable | Purpose | Default |
|---|---|---|
| `ARI_VLM_MODEL` | Preferred ARI override for figure / table review | falls through to `VLM_MODEL` |
| `VLM_MODEL` | Vision LLM fallback for figure / table review | `openai/gpt-4o` |

## See also

- `docs/reference/configuration.md` — narrative tour of the same env vars,
  grouped by use case.
- `ari-core/ari/config.py` — Pydantic settings model that consumes
  most of the `ARI_*` group.
- Each skill's `README.md` — env vars specific to that skill.
