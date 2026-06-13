---
sources:
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/configs
    role: config
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
last_verified: 2026-06-10
---

# Configuration Reference

## Configuration Precedence (observed)

ARI configuration enters from several sources. There are **two precedence
chains** — the value a setting resolves to depends on *who is asking*:

- **Runtime (core/CLI)** — what the agent loop and pipeline actually use.
  Built by `ari.config.load_config()` (or `auto_config()` when no YAML):
  **`ARI_*` env var > workflow.yaml/config YAML > Pydantic field default**.
  Env always wins because the `_apply_*_env_overrides` functions run *last*
  (after profile merge). `auto_config()` is the no-file fallback (env over
  hardcoded). Profiles (`--profile laptop|hpc|cloud`) deep-merge between YAML
  and env.
- **GUI Settings panel** — what `/api/settings` shows. Built by
  `_api_get_settings()`: **saved `settings.json` (if truthy) > `ARI_*` env >
  `workflow.yaml` > hardcoded default**, with a falsy-re-force quirk (a
  saved-but-empty `llm_model`/`llm_provider` is re-filled from `workflow.yaml`
  only, dropping the env tier).

The **bridge**: the GUI `/api/launch` does **not** pass choices to the spawned
CLI as args — it writes them into the subprocess `ARI_*` env **and** snapshots
them into `{checkpoint}/launch_config.json`. The CLI then resolves via the
runtime chain above. `launch_config.json` is re-read on disk only by
`/api/run-stage` and to rehydrate the dashboard display state; it is *not*
re-parsed by `ari.config`.

| Setting | Winning order (highest first) | Decided in |
|---------|-------------------------------|-----------|
| `llm_model` (runtime) | `ARI_MODEL` > `ARI_LLM_MODEL` > YAML `llm.model` > `qwen3:8b` | `config/__init__.py:_apply_llm_env_overrides` |
| `llm_model` (GUI display) | in-mem `_launch_llm_model` > `launch_config.json` > `settings.json` > `workflow.yaml` > `''` | `viz/routes.py`, `viz/ui_helpers.py` |
| `llm_model` (Settings merge) | saved `settings.json` (if truthy) > `ARI_LLM_MODEL` > `workflow.yaml` > `''` | `viz/api_settings.py:_api_get_settings` |
| `llm_provider`/`backend` (runtime) | `ARI_BACKEND` > YAML `llm.backend` > `ollama` | `config/__init__.py:_apply_llm_env_overrides` |
| paper `language` | `ARI_PAPER_LANGUAGE` env **only** (set by GUI launch; *not* re-derived from `launch_config.json` on a hand-run CLI) | `ari-skill-paper` reads env; `viz/api_experiment.py` sets it |
| GUI port | `ARI_GUI_PORT` (via `start.sh`) > `--port` (argparse default **8765**) > `state.py` `9886` placeholder | `start.sh`, `viz/server.py:main` |
| SLURM partition | explicit tool `partition` kwarg (sinfo-validated) > `SLURM_DEFAULT_PARTITION` > sinfo first; the kwarg is chosen from: experiment.md `Partition:` > `ARI_SLURM_PARTITION` > sinfo | `ari-skill-hpc/slurm.py`, `ari/agent/workflow.py` |
| checkpoint dir | `ARI_CHECKPOINT_DIR` > YAML `checkpoint.dir` > `workspace/checkpoints/{run_id}` | `config/__init__.py:_apply_checkpoint_env_overrides`, `PathManager` |

**Falsy-vs-missing:** the core env-override guards (`if _m:` etc.) treat an
empty env var as missing (YAML/default kept; `base_url` uses an explicit
`!= ""`). The GUI merge `{**defaults, **saved}` lets a present-but-empty saved
key win, then re-forces only `llm_model`/`llm_provider` from `workflow.yaml`.

> ⚠ This precedence is **documented as observed today**, not changed. Per the
> refactoring rules, the order is locked by tests
> (`test_config.py`, `test_default_provider.py`, `test_launch_config.py`,
> `test_settings_*`) before any consolidation. A central config-loader is a
> proposed follow-up — see `refactoring/notes/08_config_precedence.md`.

## workflow.yaml (Canonical Developer Config)

`workflow.yaml` is the **single source of truth** for the full ARI pipeline.
Place it at `ari-core/config/workflow.yaml`.

Use `{{ari_root}}` in skill paths — it resolves to `$ARI_ROOT` env var or the project root.

```yaml
llm:
  backend: openai          # ollama | openai | anthropic
  model: gpt-5.2           # Model identifier
  base_url: ""             # Leave empty for OpenAI; set for Ollama/vLLM

author_name: "Autonomous Research Infrastructure"

resources:
  cpus: 48                 # Default CPU count for reproducibility experiments
  timeout_minutes: 60      # Default job timeout
  executor: slurm          # Job executor: slurm / local / pbs / lsf

# BFTS phase stages (executed in order during tree search)
bfts_pipeline:
  - stage: generate_idea
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
  - stage: select_and_run
    skill: hpc-skill
    phase: bfts
  - stage: evaluate
    skill: evaluator-skill
    tool: evaluate_node
    phase: bfts
  - stage: frontier_expand
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
    loop_back_to: select_and_run

# Post-BFTS pipeline stages
pipeline:
  - stage: search_related_work
    skill: web-skill
    tool: collect_references_iterative
    skip_if_exists: '{{ckpt}}/related_refs.json'
    # ...
  - stage: transform_data
    skill: transform-skill
    tool: nodes_to_science_data
    inputs:
      nodes_json_path: '{{ckpt}}/nodes_tree.json'
      llm_model: '{{llm.model}}'
      llm_base_url: '{{llm.base_url}}'
    outputs:
      file: '{{ckpt}}/science_data.json'
    skip_if_exists: '{{ckpt}}/science_data.json'
  - stage: generate_figures
    skill: plot-skill
    tool: generate_figures_llm
    depends_on: [transform_data]
    # ...
  - stage: write_paper
    skill: paper-skill
    tool: write_paper_iterative
    depends_on: [search_related_work, generate_figures]
    # ...
  - stage: review_paper
    skill: paper-skill
    tool: review_compiled_paper
    depends_on: [write_paper]
    # ...
  # ─── EAR curation/publishing/finalization ── (v0.7.0) ───
  - stage: ear_curate
    skill: transform-skill
    tool: curate_ear
    depends_on: [generate_ear]
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'
    outputs:
      file: '{{checkpoint_dir}}/ear_curate.status.json'
  - stage: finalize_paper
    skill: paper-skill
    tool: inject_code_availability
    depends_on: [write_paper, ear_curate]
    # Auto-loads ref/sha/doi from ear_published/manifest.lock and
    # publish_record.json; injects \codeavailability/\codedigest/\coderef
    # macros into full_paper.tex. Skips silently when no curated bundle.
  - stage: ear_publish
    skill: transform-skill
    tool: publish_ear
    depends_on: [ear_curate]
    enabled: false           # opt-in; set to true (or pass publish=true)
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'
      backend: ari-registry
      visibility: staged
      dry_run: false
    outputs:
      file: '{{checkpoint_dir}}/publish_record.json'
  - stage: merge_reviews
    skill: paper-skill
    tool: merge_reviews
    depends_on: [review_paper, vlm_review_figures]
    # Post-hoc structural merge of text + VLM reviewer outputs (no LLM).

  # ─── ORS auto-rubric reproducibility (PaperBench, v0.7.0) ───
  # Replaces the legacy `reproducibility_check` stage.
  - stage: ors_generate_rubric
    skill: replicate-skill
    tool: generate_rubric
    depends_on: [write_paper]
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      output_path: '{{checkpoint_dir}}/ors_rubric.json'
      target_leaf_count: 0     # 0 = auto from paper length
  - stage: ear_publish          # v0.7.0+: enabled by default with local-tarball
    skill: transform-skill
    tool: publish_ear
    depends_on: [ear_curate]
    enabled: true
    inputs:
      backend: local-tarball    # zero-deps; writes bundle.tar.gz next to ckpt
      visibility: staged
  - stage: ors_seed_sandbox     # v0.7.0+: deterministic seed from EAR bundle
    skill: paper-re-skill
    tool: fetch_code_bundle
    depends_on: [ear_publish]
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'    # auto-load ref from publish_record.json
      dest: '{{checkpoint_dir}}/repro_sandbox'
  - stage: ors_build_reproduce  # v0.7.0+: LLM fallback (skips if seeded above)
    skill: paper-re-skill
    tool: build_reproduce_sh
    depends_on: [ors_generate_rubric, ors_seed_sandbox, finalize_paper]
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      output_dir: '{{checkpoint_dir}}/repro_sandbox'
      overwrite: false
  - stage: ors_run_reproduce
    skill: paper-re-skill
    tool: run_reproduce        # Phase 1 (sandbox-execute reproduce.sh)
    depends_on: [ors_generate_rubric, ors_build_reproduce]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      repo_dir: '{{checkpoint_dir}}/repro_sandbox'
      sandbox_kind: ''         # auto: slurm → docker → apptainer → singularity → local
      timeout_global_sec: 0    # 0 = use rubric.reproduce_contract.max_runtime_sec
      partition: ''            # blank → ARI_SLURM_PARTITION → launch_config.json
      cpus: 0                  # blank → ARI_SLURM_CPUS (default 8)
      walltime: ''             # blank → ARI_SLURM_WALLTIME → derived from timeout
  - stage: ors_grade
    skill: paper-re-skill
    tool: grade_with_simplejudge   # Phase 2 (PaperBench SimpleJudge via LiteLLM)
    depends_on: [ors_run_reproduce]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      repo_dir: '{{checkpoint_dir}}/repro_sandbox'
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      n_runs: 3
      judge_model: gpt-5-mini  # any LiteLLM-recognised model id

retrieval:
  backend: semantic_scholar    # semantic_scholar | alphaxiv | both
  alphaxiv_endpoint: https://api.alphaxiv.org/mcp/v1

# ── Paper review (rubric-driven, AI Scientist v1/v2-compatible) ────────
# Override via CLI (--rubric, --fewshot-mode, --num-reviews-ensemble,
# --num-reflections) or environment variables (ARI_RUBRIC,
# ARI_FEWSHOT_MODE, ARI_NUM_REVIEWS_ENSEMBLE, ARI_NUM_REFLECTIONS).
# Bundled rubrics (16 YAMLs in ari-core/config/reviewer_rubrics/):
#   neurips (default, v2-compatible) | iclr | icml | cvpr | acl | sc | osdi
#   | usenix_security | stoc | siggraph | chi | icra | nature
#   | journal_generic | workshop | generic_conference
# Plus the built-in `legacy` fallback (v0.5 schema). Add new venues by
# dropping <id>.yaml into reviewer_rubrics/ — no code changes required.
#
# `prompt_overrides.author_hint` (unreleased) is the inverse of
# system_hint: it's injected into paper-drafting prompts by
# `generate_section` so writing is venue-conditioned at the same
# strength as peer review. SC and NeurIPS ship calibrated hints;
# other venues default to empty (legacy weak append).
#
# PaperBench rubric templates (separate venue YAMLs for the rubric
# generator) live under ari-core/config/paperbench_rubrics/. See
# docs/reference/rubric_schema.md#venue-conditioned-templates for the
# YAML schema; shipped templates: generic | sc | neurips | nature.
#
# Few-shot corpus management
# --------------------------
# Files under reviewer_rubrics/fewshot_examples/<rubric>/ may be managed
# from the GUI (New Experiment Wizard → Paper Review → Few-shot Examples)
# or scripts/fewshot/sync.py. REST endpoints exposed by the viz server:
#   GET  /api/rubrics                         list rubrics (Wizard dropdown)
#   GET  /api/fewshot/<rubric>                list fewshot examples
#   POST /api/fewshot/<rubric>/sync           pull entries from manifest.yaml
#   POST /api/fewshot/<rubric>/upload         upload one example (JSON body)
#   POST /api/fewshot/<rubric>/<example>/delete  remove one example
# All four endpoints reject unknown rubrics and strip ../ sequences.

memory:
  # v0.6.0: Letta is the sole production backend; values here are
  # exported into the skill subprocess env at load time. The agent's
  # chat LLM handle is hardcoded to `letta/letta-free` because
  # ari-skill-memory only ever calls archival_insert / archival_search
  # — no chat messages — so the picker had no runtime effect.
  backend: letta
  letta:
    base_url: http://localhost:8283
    collection_prefix: ari_
    embedding_config: letta-default

container:
  mode: auto                   # auto | docker | singularity | apptainer | none
  image: ""                    # Container image name (empty = no container)
  pull: on_start               # always | on_start | never

skills:
  # `phase` controls which pipeline-phase ReAct agents see the skill's
  # MCP tools. A single string opts the skill into exactly one phase;
  # a list opts it into several. Skills tagged `reproduce` are exposed
  # to any future stage that opts in via a `react:` block. The default
  # v0.7.0 workflow no longer routes the reproducibility check through
  # `react_driver` — it uses the deterministic PaperBench Phase 1 +
  # Phase 2 chain (`ors_run_reproduce` / `ors_grade`) instead.
  - name: web-skill
    path: "{{ari_root}}/ari-skill-web"
    phase: [paper, reproduce]
  - name: plot-skill
    path: "{{ari_root}}/ari-skill-plot"
    phase: paper
  - name: paper-skill
    path: "{{ari_root}}/ari-skill-paper"
    phase: paper
  - name: paper-re-skill
    path: "{{ari_root}}/ari-skill-paper-re"
    phase: paper
  - name: memory-skill
    path: "{{ari_root}}/ari-skill-memory"
    phase: bfts
  - name: evaluator-skill
    path: "{{ari_root}}/ari-skill-evaluator"
    phase: bfts
  - name: idea-skill
    path: "{{ari_root}}/ari-skill-idea"
    phase: none
  - name: hpc-skill
    path: "{{ari_root}}/ari-skill-hpc"
    phase: [bfts, reproduce]
  - name: coding-skill
    path: "{{ari_root}}/ari-skill-coding"
    phase: [bfts, reproduce]
  - name: transform-skill
    path: "{{ari_root}}/ari-skill-transform"
    phase: paper
  - name: benchmark-skill
    path: "{{ari_root}}/ari-skill-benchmark"
    phase: bfts
  - name: vlm-skill
    path: "{{ari_root}}/ari-skill-vlm"
    phase: [paper, reproduce]
  # v0.7.0: PaperBench-format auto-rubric generator + auditor.
  - name: replicate-skill
    path: "{{ari_root}}/ari-skill-replicate"
    phase: paper
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_MAX_NODES` | Maximum BFTS nodes to explore (hard cap; pruning predicate input) | `50` |
| `ARI_MAX_DEPTH` | Hard cap on BFTS tree depth (activated in v0.7.2) | `5` |
| `ARI_PARALLEL` | Concurrent node execution | `1` |
| `ARI_EXECUTOR` | Execution backend: `local`, `slurm`, `pbs`, `lsf` | `local` |
| `ARI_SLURM_PARTITION` | SLURM partition name | (none) |
| `ARI_SLURM_CPUS` | Override CPU count for SLURM jobs | (auto-detected) |
| `SLURM_LOG_DIR` | Where SLURM output files go | (none) |
| `OLLAMA_HOST` | Ollama server address | `127.0.0.1:11434` |
| `OPENAI_API_KEY` | OpenAI API key | (none) |
| `ANTHROPIC_API_KEY` | Anthropic API key | (none) |
| `ARI_RETRIEVAL_BACKEND` | Paper search backend: `semantic_scholar`, `alphaxiv`, `both` | `semantic_scholar` |
| `VLM_MODEL` | VLM model for figure review | `openai/gpt-4o` |
| `ARI_ORCHESTRATOR_PORT` | HTTP port for orchestrator skill | `9890` |
| `LETTA_BASE_URL` | Letta server endpoint | `http://localhost:8283` |
| `LETTA_API_KEY` | Required for Letta Cloud; optional for self-hosted | (none) |
| `LETTA_EMBEDDING_CONFIG` | Embedding handle Letta uses for archival memory (the agent's chat LLM is hardcoded to `letta/letta-free` since ARI never invokes it) | `letta-default` |
| `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA` | `auto` / `pip` / `docker` / `singularity` / `none` | `auto` |
| `ARI_MEMORY_LETTA_TIMEOUT_S` | Per-call timeout (viz + skill) | `10` |
| `ARI_MEMORY_LETTA_OVERFETCH` | Over-fetch size for the post-filter ancestor-scope fallback | `200` |
| `ARI_MEMORY_LETTA_DISABLE_SELF_EDIT` | Keep Letta self-edit off so CoW holds | `true` |
| `ARI_MEMORY_ACCESS_LOG` | `on` / `off` — enable `{checkpoint}/memory_access.jsonl` | `on` |
| `ARI_MEMORY_AUTO_RESTORE` | Auto-restore `memory_backup.jsonl.gz` on `ari resume` | `true` |
| `ARI_CURRENT_NODE_ID` | Runtime-only; set by ari-core per-node to enforce write-side CoW | (runtime) |
| `ARI_MODEL_RUBRIC_GEN` | Generator LLM for `ari-skill-replicate.generate_rubric` (v0.7.0) | `gemini/gemini-2.5-pro` |
| `ARI_MODEL_RUBRIC_AUDIT` | Auditor LLM for `audit_rubric` (independent of generator) | `anthropic/claude-opus-4-7` |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | Override per-paper target leaf count consumed by `generate_rubric`. `0`/unset → auto from paper length (~1 leaf / 75 words, clamped to [50, 400]). Set by the GUI Wizard's "Target leaves" field. | (unset) |
| `ARI_RUBRIC_GEN_TEMPERATURE` | Override generator temperature. Set by the GUI Wizard's "Temperature" field. | (unset) |
| `ARI_RUBRIC_GEN_TWO_STAGE` | Force the rubric generator's two-stage path on/off (`1`/`true`/`on` vs `0`/`false`/`off`). Two-stage = skeleton + parallel subtree calls; produces ~4× more leaves and 1–2 levels more depth than a single call at ~5× more API tokens. Unset → kwarg default (currently on). Set by the GUI Wizard's "Two-stage generation" toggle. | (unset, default on) |
| `ARI_PAPERBENCH_RUBRIC_DIR` | Override the search root for venue-conditioned PaperBench rubric templates. The loader checks this dir first, then `<cwd>/ari-core/config/paperbench_rubrics/`, `<cwd>/config/paperbench_rubrics/`, and the repo-relative fallback. Unset → built-in defaults. | (unset) |
| `ARI_MODEL_REPLICATE` | Replicator LLM for `build_reproduce_sh` (paper → reproduce.sh, v0.7.0) | `claude-opus-4-7` |
| `ARI_MODEL_JUDGE` | Judge LLM for `grade_with_simplejudge` (PaperBench Phase 2, v0.7.0; routed via LiteLLM, any provider OK) | `gpt-5-mini` |
| `ARI_MODEL_LINEAGE` | LLM judge for `decide_lineage_action` (lineage decision, v0.7.0). Falls through `ARI_MODEL_EVAL` → `ARI_MODEL` → `ARI_LLM_MODEL` → `gpt-4o-mini` | (auto) |
| `ARI_MODEL_ROOT_SELECT` | LLM that picks `ideas[0]` from the VirSci pool (lineage decision, v0.7.0). Same fallback chain as `ARI_MODEL_LINEAGE` | (auto) |
| `ARI_RUBRIC` | Rubric id used by both review and the BFTS dynamic axis evaluator (Phase 3, v0.7.0). Reads `ari-core/config/reviewer_rubrics/<id>.yaml` | `neurips` |
| `ARI_PHASE1_SANDBOX` | Phase 1 sandbox: `auto` / `slurm` / `docker` / `apptainer` / `singularity` / `local` | `auto` |
| `ARI_PHASE1_DOCKER_IMAGE` | Container image for the docker sandbox runner | `ubuntu:24.04` |
| `ARI_PHASE1_APPTAINER_IMAGE` / `ARI_PHASE1_SINGULARITY_IMAGE` | Image for the Apptainer/Singularity sandbox runner | `docker://ubuntu:24.04` |
| `ARI_SLURM_WALLTIME` | `--time` HH:MM:SS for the SLURM Phase 1 sandbox (v0.7.0, restored). Falls back to a value derived from the rubric's `max_runtime_sec`. | (auto) |
| `ARI_PUBLISH_DRYRUN` | Force `ari ear publish --dry-run` (CI safety, v0.7.0) | (off) |
| `ARI_REGISTRY_DATA` | sqlite + artifact storage root for `ari registry serve` | (none — must be set explicitly; the pre-v0.5 `$HOME/.ari/registry-data` fallback emits a `DeprecationWarning` and is removed in v1.0) |
| `ARI_REGISTRY_TOKEN` | Bearer token for `ari clone ari://...` / `ari ear publish --backend ari-registry` | (none) |
| `ARI_REPRO_CLONE_POLICY` | Git-shim policy in the reproducibility sandbox: `passthrough` / `deny` / `warn` | `passthrough` |

## Memory backend (Letta)

v0.6.0 replaces the deterministic JSONL memory store with
[Letta](https://docs.letta.com). Letta runs in one of four modes:

| Mode | Requirement | Store | Notes |
|------|-------------|-------|-------|
| Docker Compose | `docker` + `docker compose` | Postgres | Laptop default, pre-filter supported |
| Singularity / Apptainer | `singularity` / `apptainer` | Postgres | HPC default; SLURM-aware data dir |
| pip (container-less) | Python 3.10+ | SQLite | Falls back to over-fetch + post-filter ancestor scoping |
| Letta Cloud | API key | Managed | `LETTA_BASE_URL=https://api.letta.com` |

`ari setup` auto-detects the best mode; you can force one via
`ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA`. Start/stop/health/backup/restore
are handled by the `ari memory` subcommand — see
`docs/reference/cli_reference.md`.

One-shot migration for a v0.5.x checkpoint:

```bash
ari memory migrate --checkpoint /path/to/ckpt --react
```

## LLM Backends

### Ollama (local, recommended for offline HPC)

```yaml
llm:
  backend: ollama
  model: qwen3:32b
  base_url: http://127.0.0.1:11434
```

### OpenAI

```yaml
llm:
  backend: openai
  model: gpt-4o
```

### Anthropic

```yaml
llm:
  backend: anthropic
  model: claude-sonnet-4-5
```

### Any OpenAI-compatible API (vLLM, LM Studio, etc.)

```yaml
llm:
  backend: openai
  model: your-model-name
  base_url: http://your-server:8000/v1
```

---

## Template Variables in workflow.yaml

Any value in `inputs:` supports `{{variable}}` substitution:

| Variable | Value |
|----------|-------|
| `{{ckpt}}` | Checkpoint directory path |
| `{{ari_root}}` | ARI project root (`$ARI_ROOT` or auto-detected) |
| `{{llm.model}}` | LLM model name from `llm:` section |
| `{{llm.base_url}}` | LLM base URL from `llm:` section |
| `{{resources.cpus}}` | CPU count from `resources:` section |
| `{{resources.timeout_minutes}}` | Timeout from `resources:` section |
| `{{stages.<name>.outputs.file}}` | Output file path of a completed stage |
| `{{author_name}}` | Author name from top-level config |
| `{{vlm_feedback}}` | VLM review feedback (injected on loop-back from `vlm_review_figures`) |
| `{{paper_context}}` | Science-facing experiment summary |
| `{{keywords}}` | LLM-generated search keywords |

---

## skip_if_exists Validation

Stages with `skip_if_exists` will **re-run** if the output file:
- Does not exist
- Is empty
- Is a JSON file containing an `"error"` key at the top level

This prevents broken outputs from silently blocking downstream stages.

---

## Plan Promote (v0.7.0+)

`plan_promote` controls how VirSci's experiment plan is materialised into
the in-checkpoint `experiment.md`. The user's source `experiment.md`
(passed on the CLI) is **never** modified — only the in-checkpoint copy
gets the auto-appended block, between HTML comment markers so re-runs
are idempotent.

```yaml
plan_promote: index_only          # full | index_only | off
```

| Mode | Block contents | Typical size |
|---|---|---|
| `full` | Selected idea + every plan §-tag body + alternatives | ~5 KB |
| `index_only` (default) | Selected idea + plan §-tag titles + alternatives | ~1.5 KB |
| `off` | (no auto-append) | 0 |

The Phase 3 evaluator and the BFTS expand idea-context both read the
**raw** plan from `idea.json`, so the choice between `full` and
`index_only` is mostly cosmetic — it decides what humans (and
paper-skill) see in `experiment.md`.

## Lineage Decision Hook (v0.7.0+)

When a BFTS run stagnates, an LLM judge decides whether to keep
exploring, switch to one of the alternative ideas, fan out to a
parallel child run, or terminate the lineage. The judge is constrained
to four actions, every output is validated against the alternatives
pool, and any error degrades silently to `continue` so the BFTS loop
never blocks on this hook.

```yaml
lineage_decision:
  mode: stagnation_rule           # off | stagnation_rule | every_node
  stagnation_window: 5            # composite-score window
  stagnation_threshold: 0.02      # max-min < threshold ⇒ stagnant
  min_nodes_before_decision: 3    # never fire on the very first nodes
  rate_limit_per_run: 5           # cap escalations per run
```

| Mode | Trigger | Cost |
|---|---|---|
| `off` | never | 0 |
| `stagnation_rule` (default) | composite scores flat for `stagnation_window` consecutive nodes | 0–`rate_limit_per_run` LLM calls per run |
| `every_node` | every BFTS step (LLM also decides timing) | 1 LLM call per node |

Every fired decision (including `continue`) is appended to
`{checkpoint}/lineage_decisions.jsonl` so post-hoc analysis can
correlate lineage actions with outcome quality. The same file holds
`root_idea_selection` records (different `trigger` field) so a single
log captures all lineage decisions LLM judgements.

## Root Idea Selection (v0.7.0+)

After VirSci writes `idea.json`, an LLM picks which entry should be the
run's root, given the venue rubric and the ancestor research thread.
The default keeps VirSci's score-based ordering (`ideas[0]`); an
out-of-range LLM choice falls back to the same default. One LLM call
per run start; no per-node cost.

```yaml
root_idea_selection:
  enabled: true                   # default v0.7.0+
```

The decision is logged to `lineage_decisions.jsonl` as
`{trigger: "root_idea_selection", action: "root_swap" | "root_keep"}`
and persisted in `idea.json` as `_root_choice`. Children (recursion)
detect either marker and skip re-selection.

## Claim Gate Policy (v0.7.0+)

`claim_gate_policy` is the top-level block that governs the
claim–evidence hard gate (Story2Proposal Phase B3). The gate stages run
on every paper build and are wired with `{{claim_gate_policy}}`; the
block is loaded by `ari-core/ari/pipeline/claim_gate/policy.py`.

```yaml
claim_gate_policy:
  mode: warn                  # off | warn | strict
  comparison_scope: any       # any | same_environment
  numeric_coverage:
    target_sections:
      strict: [abstract, results, conclusion]
      warn: [introduction, discussion, limitations]
      excluded: [related_work, references, appendix, equations]
  numeric_match:
    default_tolerance: {absolute: 0.0, relative: 0.02}
  blocking:
    block_on: [numeric_mismatch, operand_unresolved, missing_evidence]
```

`mode` controls blocking (env `ARI_CLAIM_GATE_MODE` overrides it):

| Mode | Behaviour |
|---|---|
| `off` | Never blocks. |
| `warn` (default) | Reports errors/warnings but never blocks `finalize_paper`. |
| `strict` | The **final** gate blocks (`finalize_paper` is skipped) when a `block_on` error exists, and uncovered result numbers in the strict sections become blocking. The draft gate never blocks. |

`comparison_scope` is the injected research intent (env
`ARI_COMPARISON_SCOPE` overrides it):

| Scope | Cross-environment comparison |
|---|---|
| `any` (default) | Transparency **warning** — correct for cross-architecture studies where the cross-host comparison is the contribution. |
| `same_environment` | **Blocking** error — correct for single-architecture optimization studies. |

`numeric_coverage.target_sections` lists, per gate severity, which paper
sections are checked for numeric claims (`strict`/`warn`) and which are
ignored (`excluded`). `numeric_match.default_tolerance` is the
match tolerance applied when a claim carries no per-claim tolerance:
`absolute: 0.0`, `relative: 0.02` (2%). `blocking.block_on` is the list
of finding types that block the final gate under `strict`:
`numeric_mismatch`, `operand_unresolved`, `missing_evidence`.

> A separate set of **objective-falsehood** finding types
> (`invariant_violation`, `correctness_failed`, `correctness_uncovered`,
> `placeholder_denominator`, `recompute_mismatch`, `claim_evidence_missing`,
> `ceiling_unmeasured`) blocks the final paper **regardless** of
> `mode`. These defaults live in `policy.py`'s `blocking.always_block_on`
> and are not set in `workflow.yaml`.

## BFTS Tuning

Control BFTS behavior via environment variables:

```bash
export ARI_MAX_NODES=12      # Explore up to 12 nodes (small run)
export ARI_MAX_DEPTH=5       # Hard depth cap (v0.7.2: now actually enforced)
export ARI_PARALLEL=4        # Run 4 nodes concurrently
export ARI_EXECUTOR=slurm    # Submit each node as a SLURM job
```

`BFTSConfig` (defined in `ari/config/__init__.py`) exposes the full set of
knobs:

| Field | Default | Notes |
|-------|---------|-------|
| `max_depth` | 5 | Hard cap on depth (`ARI_MAX_DEPTH`). Activated in v0.7.2 (B-2). |
| `max_total_nodes` | 50 | Hard cap on node count (`ARI_MAX_NODES`). |
| `max_react_steps` | 80 | Per-node ReAct iteration cap. |
| `timeout_per_node` | 7200 | Per-node wall-time budget (s). |
| `max_parallel_nodes` | 4 | Worker concurrency. |
| `max_expansions_per_node` | 4 | New in v0.7.2 (B-6). After N expansions of the same frontier node, BFTS retires it. |
| `label_saturation_threshold` | 2 | New in v0.7.2 (L-6). When ≥ N children of one parent share a label, the next expand prompt flags the label as saturated. |
| `allow_web` | false | Opt-in: expose `web-skill` to the node agent **during exploration** (`ARI_BFTS_ALLOW_WEB`). Default-off keeps the search loop reproducible (P5); when on, ARI records `bfts_web_provenance.json` flagging the trajectory non-reproducible. `idea-skill`'s `survey` already does a bounded literature lookup regardless. |

The pre-audit `max_retries_per_node` field has been **removed** in v0.7.2
(B-3 / B-10) — ARI never retries; failed nodes produce DEBUG children
instead. YAML configs that still set `max_retries_per_node` are ignored
silently (Pydantic `extra='ignore'`).

---

## BFTS Evaluation Layers (configurable)

The BFTS pipeline has four evaluation layers, each independently selectable
through `default.yaml` (or a custom YAML). Defaults reproduce the
pre-existing behaviour, so an unmodified config is a no-op.

```yaml
bfts:
  frontier_score: scientific_plus_diversity   # how the fallback selector ranks frontier nodes
  depth_penalty_lambda: 0.05                  # used by frontier_score=depth_penalized
  ucb_c: 0.5                                  # used by frontier_score=ucb_like
  select_prompt: orchestrator/bfts_select               # LLM prompt for select_next_node
  expand_select_prompt: orchestrator/bfts_expand_select # LLM prompt for select_best_to_expand

evaluator:
  composite: harmonic_mean   # formula used to collapse per-axis scores → _scientific_score
  axis_mode: dynamic         # which axis set to send to the judge LLM
  custom_axes: []            # consulted only when axis_mode=custom
  axis_weights: { ... }      # unchanged; per-axis weight overrides
```

### Layer A — `evaluator.composite`

Selects the formula used to collapse the per-axis judge scores into the
scalar `_scientific_score` stored on each node (see
`ari/evaluator/llm_evaluator.py`). The composite is also what drives
ranking, lineage decisions, and report best-of selection.

| Value | Behaviour |
|-------|-----------|
| `harmonic_mean` (default) | Weighted harmonic mean. Heavily penalises any single weak axis — reproduces the pre-audit behaviour. |
| `arithmetic_mean` | Weighted arithmetic mean. Axes trade linearly; permissive. |
| `weighted_min` | Returns the lowest axis (bottleneck view). Weights gate which axes participate; they do not scale the score. |
| `geometric_mean` | Weighted geometric mean — between harmonic and arithmetic in how harshly it punishes weak axes. |

### Layer B — `bfts.frontier_score`

Strategy used by BFTS's **deterministic** fallback when the LLM selector
cannot pick a candidate (`_select_fallback` in
`ari/orchestrator/bfts.py`). The LLM selector itself is unchanged.

| Value | Score expression |
|-------|------------------|
| `scientific_plus_diversity` (default) | `_scientific_score + diversity_bonus` |
| `scientific_only` | `_scientific_score` (no diversity tiebreaker) |
| `depth_penalized` | `_scientific_score + diversity_bonus − λ·depth`, where `λ = bfts.depth_penalty_lambda` |
| `ucb_like` | `_scientific_score + diversity_bonus + c · √(log N / (visits + 1))`, where `c = bfts.ucb_c`, `visits` is the number of times the node has been expanded, and `N = total_visits + frontier_size` |

`depth_penalty_lambda = 0.0` reduces `depth_penalized` to the default
strategy; `ucb_c = 0.0` reduces `ucb_like` to the default strategy.

### Layer C — `evaluator.axis_mode`

Decides which axis set the judge LLM is asked to score against.

| Value | Source of axes |
|-------|----------------|
| `dynamic` (default) | Generic 5-axis floor + axes derived from the active rubric (`ARI_RUBRIC`) + plan-keyword axes lifted from `idea.json`. Refreshes automatically when `idea.json` changes mtime. |
| `legacy` | The fixed 5-axis canonical set (`measurement_validity`, `comparative_rigor`, `novelty`, `reproducibility`, `clarity_of_contribution`). No rubric / plan input. |
| `custom` | Uses `evaluator.custom_axes` verbatim. |

`custom_axes` is a list of `{name, description, weight}` records; the
`description` is sent to the judge LLM so it knows what each axis means:

```yaml
evaluator:
  axis_mode: custom
  custom_axes:
    - name: speedup
      description: "Wall-clock speedup vs. baseline (1.0 = no change)."
      weight: 0.5
    - name: accuracy
      description: "Numerical accuracy preserved within tolerance."
      weight: 0.5
```

When `axis_mode=custom`, the names listed under `axis_weights` are *not*
automatically translated to the custom axis set — duplicate the new
names there if you want to override the per-axis weight from the YAML
weights table.

### Layer D — `bfts.select_prompt` / `bfts.expand_select_prompt`

Each value is a [`FilesystemPromptLoader`](../../ari-core/ari/prompts/_loader.py)
key (path relative to `ari-core/ari/prompts/`, without `.md`). The
defaults point at the shipped templates.

A user-supplied template must declare the same placeholders the BFTS
formatter uses:

- `select_prompt`: `{experiment_goal}`, `{memory_context}`, `{candidates}` — the LLM must reply with a single 0-based integer index.
- `expand_select_prompt`: `{experiment_goal}`, `{candidates}` — same reply format.

When the file at the configured key is missing, `FilesystemPromptLoader`
raises immediately (fail-fast); there is no silent fallback.

### Quick recipes

- **Permissive scoring + UCB exploration:**
  ```yaml
  evaluator: { composite: arithmetic_mean }
  bfts: { frontier_score: ucb_like, ucb_c: 1.0 }
  ```
- **Bottleneck scoring (publish only when *every* axis is good):**
  ```yaml
  evaluator: { composite: weighted_min }
  ```
- **Pin the judge to the canonical 5 axes (legacy reproduction):**
  ```yaml
  evaluator: { axis_mode: legacy }
  ```

---

## EAR Curation (`ear/publish.yaml`) — v0.7.0+

Curation gates which subset of `{checkpoint}/ear/` becomes the publish-ready
bundle (`{checkpoint}/ear_published/` + `manifest.lock`). The author owns
this allowlist; ari-core enforces a **built-in deny list** that always
outranks `include`.

### Schema (`ari-core/ari/schemas/publish.schema.json`)

```yaml
# Example: <checkpoint>/ear/publish.yaml
include:                     # Glob allowlist (relative to ear/)
  - "README.md"
  - "LICENSE"
  - "reproduce.sh"
  - "code/**"                # verbatim source files (best chain contributing union)
  - "data/**"                # uploaded inputs only — never experiment outputs
  - "figures/**"             # top-level figures
  - "environment.json"
# Note: EVOLUTION.md and _provenance.json are ARI audit logs at checkpoint
# root, *outside* ear/ — they are never candidates for the published bundle.
exclude: []                  # User-controlled exclusions (applied after `include`)
max_file_mb: 100             # Files larger than this fail curation explicitly
visibility: staged           # staged|public|unlisted|private-token|embargoed-until:YYYY-MM-DD
required: false              # If true, a publish failure hard-fails the paper pipeline
auto_promote: false          # If true, reproducibility-pass auto-promotes staged->public
license: MIT                 # SPDX id; the LICENSE file is generated from this template
backend: ari-registry        # ari-registry|gh|zenodo|s3|local-tarball (CLI --backend overrides)
```

The legacy v0.6.0 paths (`code/<node_id>/**`, `data/raw_metrics.json`,
`logs/**`, `reproducibility/**`) are no longer produced by `generate_ear`
and should be removed from older `publish.yaml` files. See
`docs/reference/skills.md` for the full new layout description.

### Built-in deny patterns

These are **always** filtered, even if `include` matches them:

```
.env, .env.*, **/.env, **/.env.*
**/secrets/**, secrets/**
**/*.pem, **/*.key
**/id_rsa, **/id_ed25519
```

Paths of denied files are **not** recorded in `manifest.lock` — only the
count, so the manifest itself never leaks the names of secrets that were
present in `ear/`.

### Behaviour

- If `publish.yaml` is **absent**, the `ear_curate` stage is skipped silently and
  the paper's Code Availability section is omitted (full back-compat with v0.6.0
  checkpoints).
- The **bundle digest** (`bundle_sha256` in `manifest.lock`) is `sha256` of a
  canonical JSON containing the sorted file records (path + size + sha256). It
  is reproducible across machines and is the value baked into the paper.
- Curation is **atomic**: a hard failure (e.g. `max_file_mb` violation) leaves
  any previously good `ear_published/` intact.

### CLI

```bash
# Curate
ari ear curate <checkpoint>            # Pretty output
ari ear curate <checkpoint> --json     # Machine-readable
ari ear status <checkpoint>            # Show manifest summary

# Publish & promote
ari ear publish <checkpoint> --backend ari-registry --visibility staged
ari ear promote <checkpoint> --target public
```

### Pipeline integration

`workflow.yaml` adds the `ear_curate` stage between `generate_ear` and
`generate_figures`. The stage is wired to the transform skill's
`curate_ear` MCP tool and is a no-op when `publish.yaml` is absent.
