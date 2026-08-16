---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-core/ari/cli_ear.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/clone
    role: implementation
  - path: ari-core/ari/registry
    role: implementation
  - path: ari-core/ari/publish
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/config/reviewer_rubrics
    role: config
  - path: ari-core/ari/pipeline/driver.py
    role: implementation
  - path: ari-skill-paper/src
    role: implementation
  - path: ari-skill-idea/src/server.py
    role: implementation
  - path: ari-skill-vlm/src/review.py
    role: implementation
  - path: ari-skill-web/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/config.py
    role: implementation
  - path: scripts/setup/install_deps.sh
    role: implementation
last_verified: 2026-08-16
---

# ARI CLI Reference

Complete reference for ARI command-line operations. The CLI provides the same functionality as the [web dashboard](../getting-started/quickstart.md) for terminal-based workflows.

---

## Commands Overview

| Command | Description | Dashboard Equivalent |
|---------|-------------|---------------------|
| `ari run` | Run a new experiment | New Experiment wizard → Launch |
| `ari resume` | Resume an interrupted experiment | Experiments page → Resume button |
| `ari paper` | Generate paper only (skip experiments) | `POST /api/run-stage {stage: "paper"}` |
| `ari manuscript <subcmd>` | Compile, inspect, repair, and lock Manuscript Complete attempts | — |
| `ari status` | Show experiment tree and summary | Monitor / Tree page |
| `ari viz` | Launch the web dashboard | — |
| `ari projects` | List all past experiments | Experiments page |
| `ari show` | Show detailed results for a run | Results page |
| `ari delete` | Delete a checkpoint | Experiments page → Delete button |
| `ari settings` | View or modify configuration | Settings page |
| `ari skills-list` | List available tools | Settings → MCP Skills |
| `ari knowledge <subcmd>` | Inspect non-executable Knowledge Skills (`search` / `show` / `import` / `validate-manifest` / `validate-registration`, plus `lock` and `use`) | — |
| `ari provider <subcmd>` | Inspect executable Capability Providers (`search` / `show` / `probe` / `validate-manifest`, plus `lock` and `bindings`) | — |
| `ari harness <subcmd>` | Inspect Harnesses and assurance evidence (`search` / `show` / `resolve` / `verify` / `validate-manifest` / `validate-registration`, plus `lock`, `attestation`, `suite`) | — |
| `ari memory ...` | Manage the Letta memory backend | Settings → Memory (Letta) |
| `ari ear <subcmd>` | EAR curation/publishing/promotion lifecycle (v0.7.0) | — |
| `ari clone <ref>` | Fetch a curated EAR bundle (file/https/ari/gh/doi); verify by digest (v0.7.0) | — |
| `ari registry <subcmd>` | Self-hosted EAR registry: `serve` / `token issue|revoke|list` (v0.7.0) | — |
| `ari migrate node-reports <checkpoint>` | Backfill `node_report.json` for legacy (v0.6.0) checkpoints | — |
| `ari doctor claude-code` | Health-check the `claude_code` LLM backend (binary/policy/flags; `--live` runs one real call) | — |

> **Execution modes.** The opt-in `ari_rqgm` mode adds **no CLI flags** in
> v1 — it is enabled purely via config (`ari.mode: ari_rqgm` +
> `rqgm.enabled: true` in workflow.yaml) or the `ARI_MODE` /
> `ARI_RQGM_ENABLED` environment overrides. Every command above behaves
> identically under the default `simple_bfts` mode. See
> [Execution modes](../guides/execution_modes.md).

## `ari manuscript` — completeness and publication operations

This command group is the machine-readable operator surface for the opt-in
exploration-to-authoring compiler. It does not run on the default
`manuscript.mode: "off"` path.

```bash
ari manuscript compile CHECKPOINT [--mode audit|enforce] \
  [--profile generic_empirical_v1] [--repair-policy disabled|explicit|auto] \
  [--config WORKFLOW]
ari manuscript status CHECKPOINT [--fail-if-blocked]
ari manuscript inspect CHECKPOINT [--requirement ID] [--lane LANE] [--node ID]
ari manuscript plan-repair CHECKPOINT [--config WORKFLOW]
ari manuscript repair CHECKPOINT [--request REQUEST_ID]... [--config WORKFLOW]
ari manuscript explain-publication CHECKPOINT
ari manuscript lock-publication CHECKPOINT
```

`plan-repair` is read-only with respect to external systems. `repair` first
persists the admitted request and budget, then uses the normal bounded research
runtime; `ari paper` never starts research repair. `--mode` defaults to `audit`;
`--repair-policy auto` is rejected unless `--mode enforce` is also given.
`--request` is repeatable, and **omitting it selects every request in the
plan** — an unknown id is rejected with `unknown request IDs: ...`.
`lock-publication` succeeds
only for a fresh, publishable decision bound to the exact final build and PDF.
See the [operator runbook](../guides/manuscript_complete_operations.md).

---

## ari run

Run a new experiment from an experiment Markdown file.

```bash
ari run <experiment.md> [--config <config.yaml>] [--profile <profile>] \
                        [--virsci-live/--no-virsci-live] \
                        [--virsci-k N] [--virsci-team-size N] \
                        [--virsci-n-authors N] [--virsci-n-papers N] \
                        [--kca-audit/--no-kca-audit] [--task-tag TAG]...
```

| Argument | Required | Description |
|----------|----------|-------------|
| `experiment.md` | Yes | Path to experiment Markdown file |
| `--config` | No | Custom config YAML (auto-generated if omitted) |
| `--profile` | No | Environment profile: `laptop`, `hpc`, or `cloud` |
| `--virsci-live` / `--no-virsci-live` | No | Idea skill: run VirSci's real multi-agent engine on a live Semantic Scholar snapshot (vendor-wrap) instead of the re-implemented discussion loop. Sets `ARI_IDEA_VIRSCI_REAL`. Default off. |
| `--virsci-k` | No | VirSci-live discussion turns (vendor `group_max_discuss_iteration`). Sets `ARI_IDEA_VIRSCI_K`. Default 7. |
| `--virsci-team-size` | No | VirSci-live max team members per team. Sets `ARI_IDEA_VIRSCI_TEAM_SIZE`. Default 3. |
| `--virsci-n-authors` | No | VirSci-live author pool size for `select_coauthors`. Sets `ARI_IDEA_VIRSCI_N_AUTHORS`. Default 16. |
| `--virsci-n-papers` | No | VirSci-live SPECTER2 retrieval corpus size. Sets `ARI_IDEA_VIRSCI_N_PAPERS`. Default 800. |
| `--kca-audit` / `--no-kca-audit` | No | Put Knowledge, capability-binding and assurance into `audit` mode and expose their query Skills. Also defaults `assurance.tolerance_policy` to `hpc-floating-point/v1` when unset. Default off. |
| `--task-tag` | No | Deterministic Knowledge/Harness task tag; repeat for multiple tags. Tags are lower-cased, stripped and de-duplicated, then recorded under `resolved_launch.task_tags` in the checkpoint's `workflow.yaml`. |

These flags set the `ARI_IDEA_VIRSCI_*` env contract that the idea skill reads
(see [Idea Generation (VirSci-live)](#idea-generation-virsci-live) below). When
`--virsci-live` is on, hypothesis generation runs VirSci's real
`select_coauthors` + `generate_idea` mechanism grounded on a live Semantic
Scholar snapshot; on missing deps or any runtime error it degrades to the
re-implemented loop with an identical `idea.json` contract.

**Examples:**

```bash
# Basic run (auto-detects configuration)
ari run experiment.md

# With environment profile
ari run experiment.md --profile laptop

# With custom config
ari run experiment.md --config ari-core/config/workflow.yaml

# With environment variable overrides
ARI_MAX_NODES=10 ARI_PARALLEL=2 ari run experiment.md

# Use VirSci's real multi-agent engine for idea generation (vendor-wrap)
ari run experiment.md --virsci-live --virsci-k 7 --virsci-team-size 3
```

**What happens:**

1. ARI generates a unique project name (LLM-generated title)
2. Creates checkpoint directory: `./workspace/checkpoints/<run_id>/`
3. Searches related papers on arXiv and Semantic Scholar
4. Generates hypotheses via VirSci multi-agent deliberation
5. Runs Best-First Tree Search (BFTS) experiments
6. Evaluates results with LLM peer review
7. Writes a LaTeX paper with figures and citations
8. Verifies reproducibility independently

---

## ari resume

Resume an interrupted experiment from its checkpoint.

```bash
ari resume <checkpoint_dir> [--config <config.yaml>]
```

**Example:**

```bash
ari resume ./workspace/checkpoints/20260328_matrix_opt/
```

Loads the saved tree, identifies pending/failed nodes, and continues from where it stopped.

---

## ari paper

Generate the paper without running experiments. Useful when experiments are already complete.

```bash
ari paper <checkpoint_dir> [--experiment <experiment.md>] [--config <config.yaml>] \
                           [--rubric <rubric_id>] \
                           [--fewshot-mode static|dynamic] \
                           [--num-reviews-ensemble N] \
                           [--num-reflections N]

# 23 bundled rubrics: neurips, iclr, icml, cvpr, acl, sc, chi, osdi, stoc,
#   icra, siggraph, nature, usenix_security, aer, econometrica, qje, apsr,
#   ahr, philreview, pmla, journal_generic, workshop, generic_conference.
#   Drop a new <id>.yaml into ari-core/config/reviewer_rubrics/ to add any
#   venue.
```

**Example — packaged default (`generic_conference` form):**

```bash
ari paper ./workspace/checkpoints/20260328_matrix_opt/
```

**Example — Supercomputing (SC) rubric with 5-reviewer ensemble + meta-review:**

```bash
ari paper ./workspace/checkpoints/20260328_matrix_opt/ \
          --rubric sc --num-reviews-ensemble 5
```

> **`--rubric` does not reach the paper reviewer.** The flag (and `ARI_RUBRIC`)
> selects the rubric that ARI's own evaluator derives its scoring axes from
> (default `neurips`) and that lineage decisions inherit. The `write_paper` and
> `review_paper` stages take `rubric_id` from the workflow's top-level
> `paper_rubric:` key instead — `generic_conference` in the packaged
> `ari-core/config/workflow.yaml`. The paper skill deliberately refuses to read
> `ARI_RUBRIC` or guess a default (`resolve_rubric` raises `rubric_id is
> required`), so changing the reviewing venue means editing `paper_rubric` in
> the workflow YAML.

The paper pipeline runs: data transformation, figure generation, paper writing,
claim-evidence gates, VLM figure review, **rubric-driven paper review** (rubric
form + reflection + optional ensemble + Area Chair meta-review), refine/render
and finalize, and the ORS reproducibility track (`ors_generate_rubric` →
`ors_audit_rubric` → `ors_seed_sandbox` → `ors_build_reproduce` →
`ors_run_reproduce` → `ors_grade`, served by `paper-re-skill` and
`replicate-skill`).

CLI flags can also be set via env vars: `ARI_RUBRIC`, `ARI_FEWSHOT_MODE`,
`ARI_NUM_REVIEWS_ENSEMBLE`, `ARI_NUM_REFLECTIONS`. Of these only
`ARI_NUM_REVIEWS_ENSEMBLE` and `ARI_NUM_REFLECTIONS` are read by the reviewer
(`review_compiled_paper` resolves both as arg > env > rubric default).
`--fewshot-mode` is currently inert: it validates the value and exports
`ARI_FEWSHOT_MODE`, but nothing reads that variable — `fewshot_mode` comes from
the rubric YAML's `params` block alone.

---

## ari status

Display the experiment tree and summary statistics.

```bash
ari status <checkpoint_dir>
```

**Example:**

```bash
ari status ./workspace/checkpoints/20260328_matrix_opt/

# Output:
# Run: 20260328_matrix_opt
# └── root d=0 success
#     ├── improve_1 d=1 success
#     │   ├── ablation_1 d=2 success
#     │   └── validation_1 d=2 success
#     └── draft_2 d=1 failed
#
#         Summary
# ┏━━━━━━━━━┳━━━━━━━┓
# ┃ Status  ┃ Count ┃
# ┡━━━━━━━━━╇━━━━━━━┩
# │ failed  │     1 │
# │ success │     4 │
# └─────────┴───────┘
```

Node lines carry the id, depth and status only — `ari status` prints **no
score**; the per-node score field was deprecated and the command was not given a
replacement.

---

## ari viz

Launch the web dashboard for visual experiment management.

```bash
ari viz <checkpoint_dir> [--port <port>]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `checkpoint_dir` | (required) | Checkpoint directory to monitor |
| `--port` | 8765 | Port to serve on |

**Examples:**

```bash
# Start dashboard
ari viz ./workspace/checkpoints/ --port 8765

# Monitor a specific run
ari viz ./workspace/checkpoints/20260328_matrix_opt/ --port 9878
```

Open `http://localhost:<port>` in your browser. See the [QuickStart Guide](../getting-started/quickstart.md) for dashboard usage.

---

## ari projects

List all past experiment runs.

```bash
ari projects [--checkpoints <dir>]
```

`--checkpoints` defaults to `./checkpoints`, **not** the `workspace/checkpoints/`
tree that `ari run` actually writes to — a bare `ari projects` in the repo root
reports `Directory not found: checkpoints` and exits 1. Point it at the real
root explicitly.

**Example:**

```bash
ari projects --checkpoints ./workspace/checkpoints

# Output:
#                       ARI Projects
# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━┓
# ┃ ID                         ┃ Nodes ┃ Status  ┃ Score ┃ Modified    ┃
# ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━┩
# │ 20260328_matrix_opt        │    28 │ done    │ 8.40  │ 03/28 14:02 │
# │ 20260327_sorting_benchmark │    12 │ running │ —     │ 03/27 09:15 │
# │ 20260326_sample_experiment │     0 │ empty   │ —     │ 03/26 22:41 │
# └────────────────────────────┴───────┴─────────┴───────┴─────────────┘
```

Status is derived from `tree.json` (or `nodes_tree.json`) and is one of
`running` / `done` / `empty` / `corrupt` — it is not a success/failure verdict.
Score is `scientific_score` (else `score`) from `review_report.json`, formatted
to two decimals, and `—` when there is no review report.

---

## ari show

Show detailed results for a specific experiment.

```bash
ari show <checkpoint> [--checkpoints-dir <dir>]
```

Displays the experiment tree, review report summary, and list of artifacts.
`<checkpoint>` is used as a path first; only if that path does not exist is it
resolved against `--checkpoints-dir` (default `./checkpoints`).

---

## ari delete

Delete a checkpoint directory.

```bash
ari delete <checkpoint> [--checkpoints-dir <dir>] [--yes]
```

| Flag | Description |
|------|-------------|
| `--checkpoints-dir` | Base dir used only when `<checkpoint>` is not itself an existing path. Default `./checkpoints` |
| `-y` / `--yes` | Skip confirmation prompt |

Before the directory is removed, `ari delete` purges the checkpoint's Letta
memory namespace. That step is best-effort: a failure is logged as a warning and
the local `rmtree` proceeds anyway, leaving orphaned Letta entries for
`ari memory prune-local` to sweep.

---

## ari settings

View or modify ARI configuration.

```bash
ari settings [--config <config.yaml>] [options]
```

| Option | Description |
|--------|-------------|
| `--model <name>` | Set LLM model name |
| `--api-key <key>` | Set API key |
| `--partition <name>` | Set SLURM partition |
| `--cpus <count>` | Set CPU count |
| `--mem <GB>` | Set memory in GB |

`--config` defaults to `./config.yaml` and the command exits 1 if that file does
not exist — it never falls back to the packaged workflow. `--partition`,
`--cpus` and `--mem` are written into the typed `resources:` block (as
`partition` / `cpus` / `mem_gb`); the per-run `slurm_partition` /
`slurm_max_cpus` hints parsed from the experiment.md header are separate and are
not overridden by what you set here.

**Examples:**

```bash
# View current settings
ari settings

# Change model
ari settings --model gpt-4o

# Set multiple options
ari settings --model qwen3:32b --partition gpu --cpus 64 --mem 128
```

---

## ari migrate node-reports

v0.7.0 (task2.md) introduces a per-node `node_report.json` substrate
recorded into `experiments/{run_id}/{node_id}/`. Pre-existing checkpoints
do not have these reports, so the downstream consumers (`generate_ear`,
`nodes_to_science_data`, `bfts.expand`, the GUI Tree Report tab) fall
back to legacy heuristics. Run this command once per legacy checkpoint
to backfill reports best-effort:

```bash
ari migrate node-reports /path/to/checkpoint
ari migrate node-reports /path/to/checkpoint --overwrite   # also rewrite existing reports
```

Fields that cannot be inferred (`original_direction`, `next_steps_hints`)
are nulled.

---

## ari doctor claude-code

Health-checks the `claude_code` LLM backend (see
[claude_code_provider.md](./claude_code_provider.md)): claude binary +
version, fail-loud policy validation of the resolved config, the exact
strict-mode command that would run, and a static flag-support report
(`--max-turns` / `--system-prompt-file` are hidden-but-supported flags not
listed by `claude --help`).

```bash
ari doctor claude-code           # offline checks only
ari doctor claude-code --live    # + one real hermetic call with schema validation (spends tokens)
```

---

## ari ear — v0.7.0

Curation, publishing, and promotion of the **Experiment Artifact
Repository** for one checkpoint. Curation is deterministic (no LLM);
publishing ships the curated tarball to a backend that returns a
verifiable reference.

```bash
ari ear curate   <checkpoint> [--show-files] [--json]
ari ear status   <checkpoint>
ari ear publish  <checkpoint> [--backend ari-registry|local-tarball|gh|zenodo] \
                              [--visibility staged] [--dry-run]
ari ear promote  <checkpoint> [--target public|unlisted]
```

| Subcommand | What it does |
|------------|--------------|
| `curate` | Apply `ear/publish.yaml` allowlist + built-in deny list (`.env*`, `secrets/**`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`); write `{checkpoint}/ear_published/` + `manifest.lock` (with deterministic `bundle_sha256`). Skips silently if `publish.yaml` is absent. |
| `status` | Show curation manifest summary + `publish_record.json` if any. |
| `publish` | Build a reproducible tarball from `ear_published/`, ship to backend. Always starts at `visibility=staged` (FR-P5). `ARI_PUBLISH_DRYRUN=1` forces `--dry-run`. |
| `promote` | Move staged → `public`/`unlisted`. Demotion is rejected. |

Backends: `ari-registry` (self-hosted, see `ari registry`),
`local-tarball` (no server), `gh` (GitHub release), `zenodo` (DOI mint).

**Example end-to-end**:

```bash
# 1. Author curates the bundle (after running the paper pipeline).
ari ear curate ./workspace/checkpoints/run_20260504_xy/

# 2. Inspect what made it past the allow/deny rules.
ari ear status ./workspace/checkpoints/run_20260504_xy/
# bundle_sha256: 0ccabb16...
# files:         42
# visibility:    staged

# 3. Ship it to a registry (still staged).
ari ear publish ./workspace/checkpoints/run_20260504_xy/ --backend ari-registry

# 4. After the reviewer + reproducibility check pass, promote to public.
ari ear promote ./workspace/checkpoints/run_20260504_xy/ --target public
```

The `bundle_sha256` is the value baked into the paper's
`\codedigest{...}` macro by the `finalize_paper` stage. Anyone with
the paper can verify any future copy of the bundle by digest, even
if the registry has gone offline.

---

## ari memory

Admin commands for the Letta memory backend added in v0.6.0. Each
subcommand resolves the target checkpoint from `--checkpoint <path>`
or the `ARI_CHECKPOINT_DIR` env var.

```bash
ari memory <subcommand> [options]
```

| Subcommand | Description |
|------------|-------------|
| `health` | Ping the backend; show latency, namespace hash, server version. |
| `migrate` | One-shot import of v0.5.x `memory_store.jsonl` (+ `memory.json` with `--react`) into the checkpoint's Letta collections. Source files are renamed to `*.migrated-<ts>`. `--dry-run` counts without importing. |
| `backup` | Snapshot Letta-stored memory to `{ckpt}/memory_backup.v1.json.gz` — one gzipped, digest-bound JSON document, not JSONL. `ari run` registers it with `atexit`, so it lands once at process exit; `ARI_HANDOFF_MEMORY_OFF=1` suppresses that automatic write (the explicit command still works). |
| `restore` | Inverse of `backup`. `--on-conflict=skip\|overwrite\|merge` (default `skip`). Auto-invoked on `ari resume` when Letta is empty. |
| `start-local` | Bring up a local Letta server: `--path=auto\|docker\|singularity\|pip`. |
| `stop-local` | Stop docker/singularity/pip Letta (best-effort). |
| `prune-local` | Delete local Letta state (volumes / venv / `~/.letta`). Requires `--yes`. |
| `compact-access` | Summarise rotated `memory_access.<ts>.jsonl` files into `memory_access.summary.json` and delete the originals. |

**Examples:**

```bash
# Check Letta reachability for the current checkpoint
ARI_CHECKPOINT_DIR=/path/to/ckpt ari memory health

# Upgrade a v0.5.x checkpoint
ari memory migrate --checkpoint /path/to/ckpt --react

# Portable archival
ari memory backup  --checkpoint /path/to/ckpt
rsync -a /path/to/ckpt/ other-host:/home/user/ckpt/
ssh other-host "ari memory restore --checkpoint /home/user/ckpt"

# Start a local Letta if ari setup didn't
ari memory start-local --path=docker
```

---

## ari skills-list

List all available MCP tools and their descriptions.

```bash
ari skills-list [--config <config.yaml>]
```

---

## Environment Variables

### Core Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_BACKEND` | LLM backend. Routed identifiers: `ollama`, `openai`, `anthropic` / `claude`, `claude_code` / `claude-code`, `cli-shim` / `cli_shim`; anything else is passed to LiteLLM unprefixed | `ollama` |
| `ARI_MODEL` | Model name | `qwen3:8b` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `OLLAMA_HOST` | Ollama server URL | `http://localhost:11434` |
| `LLM_API_BASE` | Generic API base URL (fallback) | — |
| `ARI_MODE` | Execution-mode override: `simple_bfts` / `ari_rqgm` (see [Execution modes](../guides/execution_modes.md)) | `simple_bfts` |
| `ARI_RQGM_ENABLED` | RQGM safety interlock override (`0`/`1`/`true`/`false`; must agree with `ARI_MODE=ari_rqgm`) | off |

### BFTS Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_MAX_NODES` | Maximum total experiments | 50 |
| `ARI_MAX_DEPTH` | Maximum tree depth | 5 |
| `ARI_PARALLEL` | Concurrent experiments | 4 |
| `ARI_MAX_REACT` | Max ReAct steps per node | 20 |
| `ARI_TIMEOUT_NODE` | Timeout per node (seconds) | 7200 |

### HPC Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_EXECUTOR` | Execution-backend hint. Only the orchestrator skill touches it: it seeds a sub-experiment's `executor` field and is re-exported into the child run's environment when non-empty. The contract is a free-form string (≤128 chars) with no enum check, and nothing in `ari-core` reads it | — (unset) |
| `ARI_SLURM_PARTITION` | SLURM partition name | — |
| `ARI_SLURM_CPUS` | Override CPU count for SLURM jobs | (unset in `auto_config`; the PaperBench reproduce path falls back to `8`) |
| `ARI_SLURM_MEM_GB` | Memory (GB) recorded in `resources` | — |
| `ARI_SLURM_GPUS` | GPU count recorded in `resources` | — |
| `ARI_SLURM_WALLTIME` | Walltime recorded in `resources` | — |

### Retrieval & VLM

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_RETRIEVAL_BACKEND` | Default paper-search provider: `semantic_scholar` (alias `semantic-scholar`) / `arxiv` / `alphaxiv`. `both` is **rejected** — issue two pinned `search_papers` calls and merge by aliases | `semantic_scholar` |
| `ARI_VLM_MODEL` | VLM model for figure review. Falls back to `VLM_MODEL`; if neither is set the VLM review raises `ARI_VLM_MODEL must select a visual review model` | — (no default) |
| `ARI_ORCHESTRATOR_HTTP_PORT` | HTTP port for the orchestrator skill (must parse as an integer in 1–65535). Host is `ARI_ORCHESTRATOR_HTTP_HOST`, default `127.0.0.1` | `9890` |

### Memory (Letta)

| Variable | Description | Default |
|----------|-------------|---------|
| `LETTA_BASE_URL` | Letta server endpoint | `http://localhost:8283` |
| `LETTA_API_KEY` | Required for Letta Cloud | — |
| `LETTA_EMBEDDING_CONFIG` | Embedding handle for archival memory (the agent's chat LLM is hardcoded; ARI never invokes it) | `letta-default` |
| `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA` | `auto` / `pip` / `docker` / `singularity` / `none` | `auto` |
| `ARI_MEMORY_LETTA_TIMEOUT_S` | Per-call timeout | `10` |
| `ARI_MEMORY_LETTA_OVERFETCH` | Over-fetch K for ancestor post-filter fallback | `200` |
| `ARI_MEMORY_LETTA_DISABLE_SELF_EDIT` | Disable Letta self-edit (CoW-safe) | `true` |
| `ARI_MEMORY_ACCESS_LOG` | Write `{checkpoint}/memory_access.jsonl` | `on` |
| `ARI_MEMORY_ACCESS_LOG_MAX_MB` | Rotate threshold | `100` |
| `ARI_MEMORY_AUTO_RESTORE` | Auto-restore backup on `ari resume` | `true` |

### Per-Phase Model Overrides

Read as `ARI_MODEL_<PHASE>`; an unset or empty value leaves the phase on the
global `cfg.llm.model`.

| Variable | Phase |
|----------|-------|
| `ARI_MODEL_IDEA` | Idea generation |
| `ARI_MODEL_CODING` | AgentLoop / ReAct (the in-process coding agent) |
| `ARI_MODEL_BFTS` | BFTS experiments |
| `ARI_MODEL_EVAL` | Evaluator / judge |
| `ARI_MODEL_PAPER` | Paper writing |

### Idea Generation (VirSci-live)

Opt-in vendor-wrap path for idea generation. When `ARI_IDEA_VIRSCI_REAL` is
on, the idea skill runs VirSci's real multi-agent mechanism
(`select_coauthors` + `generate_idea`) on a live Semantic Scholar snapshot;
default off keeps behaviour unchanged. The `ari run` flags
`--virsci-live` / `--virsci-k` / `--virsci-team-size` / `--virsci-n-authors`
/ `--virsci-n-papers` set these variables. The deliberation LLM follows the
per-phase `ARI_MODEL_IDEA` model. Requires the `virsci` pip extra; when absent
or on any runtime error the skill degrades to the re-implemented loop with an
identical `idea.json` contract.

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_IDEA_VIRSCI_REAL` | Toggle the real vendor-wrap path | (unset/off) |
| `ARI_IDEA_VIRSCI_K` | Discussion turns (vendor `group_max_discuss_iteration`) | 7 |
| `ARI_IDEA_VIRSCI_TEAM_SIZE` | Max team members (vendor `max_teammember`) | 3 |
| `ARI_IDEA_VIRSCI_N_AUTHORS` | Author pool for `select_coauthors` | 16 |
| `ARI_IDEA_VIRSCI_N_PAPERS` | SPECTER2 retrieval corpus size | 800 |
| `ARI_IDEA_VIRSCI_MAX_TEAMS` | Cap on teams driven through `generate_idea` | =`n_ideas` |
| `ARI_IDEA_VIRSCI_SPECTER2_MODEL` | Local query embedder | `allenai/specter2_base` |

### .env File

ARI loads `.env` files automatically (checked in order):

1. `$ARI_CHECKPOINT_DIR/.env` — only when that variable is set (highest priority)
2. `<project_root>/.env` — `$ARI_ROOT` when set, else the repository root
3. `<project_root>/ari-core/.env`
4. `~/.env` (lowest priority)

Format: `KEY=VALUE` (lines starting with `#` are ignored).

Every file is loaded with `override=False`, so a variable already exported in
your shell beats **all four** files, and among the files the first one to set a
key wins.

---

## Running on HPC (SLURM)

```bash
# Set executor
export ARI_EXECUTOR=slurm
export ARI_SLURM_PARTITION=your_partition

# Submit as a SLURM job
sbatch << 'EOF'
#!/bin/bash
#SBATCH --job-name=ari
#SBATCH --partition=your_partition
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --time=04:00:00
#SBATCH --output=ari_%j.out

# If using Ollama on a GPU node:
ollama serve &
sleep 10

export ARI_BACKEND=ollama
export ARI_MODEL=qwen3:32b

cd /path/to/ARI
ari run /path/to/experiment.md --profile hpc
EOF
```

**Important rules:**

- Always use absolute paths (not `~` or relative paths)
- Never redirect stdout in SLURM scripts (SLURM captures it via `--output`)
- Never add `--account` or `-A` flags unless your cluster requires them

---

## `ari clone <ref> [<dest>]` — v0.7.0+

Fetch + verify + extract a curated EAR bundle. **No code execution** —
this command only retrieves bytes and confirms their digest. Designed to
be the "1 line install" path for readers reproducing a paper's
experiments.

### Supported refs

| Scheme | Resolver |
|---|---|
| `file://<path>` | local file/dir |
| `https://<url>` / `http://<url>` | tarball download |
| `ari://<id>` | ari-registry |
| `gh:<user>/<repo>` | GitHub repo or release |
| `doi:<doi>` | Zenodo deposition |

### Flags

```
--expect-sha256 <hex>   Required bundle digest. Hard fail on mismatch.
                        Ignored under --no-extract (see below).
--no-extract            Just fetch the tarball; do not extract it. This also
                        skips ALL digest verification — the digest can only be
                        recomputed from the extracted files, so the reported
                        bundle_sha256 is empty and --expect-sha256 is never
                        compared.
--registry <name>       Limit ari:// resolver to a named registry from
                        registries.yaml.  Set $ARI_REGISTRIES_FILE or
                        place the file at ./.ari/registries.yaml; the
                        legacy $HOME/.ari/registries.yaml fallback was
                        removed in v0.5.0 and emits a
                        DeprecationWarning until v1.0.  An unmatched
                        name yields no registries and the command
                        fails with "no ari-registry configured".
--token <env-or-value>  Bearer token. Looked up in $ENV first, falls back
                        to the literal value (so you can pass either
                        --token MY_TOKEN_VAR or --token "raw-token-string").
```

### Verification model

1. The resolver writes the artifact (tarball or directory) into a temp dir.
2. The orchestrator extracts into a *sibling* temp dir (`_stage`), rejecting
   absolute paths, `..` escapes and links that point outside it.
3. Each file's sha256 is recomputed and compared against `manifest.lock`;
   a file the manifest names but the bundle lacks is a hard failure.
4. The whole-bundle digest is re-derived from the canonical manifest
   (`{version, files:[{path, sha256, size}]}`, plus each file's `role` for
   `version: 2`) and compared to `manifest.lock.bundle_sha256` — but only when
   the manifest actually declares one; an absent `bundle_sha256` is accepted.
5. If `--expect-sha256` was given, that value must equal the recomputed
   digest. Hard fail on mismatch.
6. The stage dir is renamed into `dest`. A failure at any earlier step
   leaves no partial dest behind. `dest` must not exist or must be empty.

Steps 2–5 only run when extraction is enabled; `--no-extract` copies the raw
artifact and verifies nothing.

### Example

```bash
# Step 1: author curates the bundle.
ari ear curate <checkpoint>

# Step 2: reader fetches with digest verification.
ari clone file:///path/to/bundle.tar.gz ./reproduce \
  --expect-sha256 0ccabb16f05c0d3476f2f074fbd229469f11295cf928959526fc93f370c76edf
```

The digest baked into the paper (`\codedigest{...}`) is the same
value as `manifest.lock.bundle_sha256`. The reader does not need to
trust the registry at runtime; the paper itself is the trust anchor.

---

## `ari registry` — v0.7.0+

Run a self-hosted HTTP registry for curated EAR bundles. Acts as the
default backend for `ari ear publish` and the `ari://` resolver in
`ari clone`. Optional — `local-tarball` works without a server, and
Zenodo / GitHub release backends are recommended for academic
permanence.

```bash
ari registry serve   [--host 0.0.0.0] [--port 8290] [--data-dir <dir>]
ari registry token issue  <user>          # plaintext shown ONCE
ari registry token revoke <token-id>
ari registry token list
```

Setup:

```bash
# 1. Server deps are already in requirements.txt / the lockfile, so a normal
#    ./setup.sh installs them. --with-registry is now informational only.
./setup.sh --with-registry        # or pip install fastapi uvicorn[standard] python-multipart

# 2. Point the server at a data directory and start it (default port 8290).
#    NOTE: $HOME/.ari/registry-data was removed as a default in v0.5.0;
#    set $ARI_REGISTRY_DATA explicitly. The legacy fallback emits a
#    DeprecationWarning and disappears in v1.0.
export ARI_REGISTRY_DATA="$PWD/.ari_registry"
./scripts/registry/start_local.sh

# 3. Mint a token for a user.
ari registry token issue alice
# Plaintext shown once — store securely.
```

| Aspect | Detail |
|---|---|
| Endpoints | `POST /artifact`, `GET\|HEAD /artifact/<id>`, `GET /artifact/<id>/manifest.lock`, `POST /artifact/<id>/promote?target=...`, `DELETE /artifact/<id>`, `/healthz`, `/version` |
| Auth | bearer-token (sqlite-hashed); upload + delete + promote require owner token. `HEAD /artifact/<id>` and `GET /artifact/<id>/manifest.lock` take **no** token — a staged bundle's digest, length, visibility and full file manifest are readable by anyone who knows the id |
| Visibility | `staged` (owner only) → `unlisted` (id-only) / `public` (open). Demotion rejected. |
| Artifact id | `sha256(bundle.tar.gz)[:16]` (content-addressed) |
| Storage | `${ARI_REGISTRY_DATA}/artifacts/<id>/{bundle.tar.gz, manifest.lock, meta.json}` |

Deploy modes (see [docs/reference/registry.md](registry.md) for full details):

- `scripts/registry/start_local.sh` — uvicorn + sqlite, single-process. Laptop / dev.
- `scripts/registry/docker-compose.yml` — nginx + uvicorn + sqlite-on-volume. Production.
- `scripts/registry/start_singularity.sh` — Apptainer / Singularity SIF. HPC.

Configure the client by writing `registries.yaml` to `$ARI_REGISTRIES_FILE` or
`./.ari/registries.yaml`; the legacy `$HOME/.ari/registries.yaml` fallback emits
a DeprecationWarning and is removed in v1.0. A checkpoint-scoped
`.ari/registries.yaml` is described in the resolver docstrings but is **not**
reachable today — neither `ari clone` nor the `ari-registry` publish backend
passes a checkpoint to the lookup, so point `$ARI_REGISTRIES_FILE` at it if you
want it honoured:

```yaml
registries:
  - name: default
    url: http://127.0.0.1:8290
    token: $ARI_REGISTRY_TOKEN
```

Then `export ARI_REGISTRY_TOKEN=ari_<paste-from-issue>` and use
`ari clone ari://<id>` (or `ari clone ari://<registry-name>/<id>` to pin one
entry) or `ari ear publish --backend ari-registry`. With no `registries.yaml`
anywhere, both fall back to a single registry built from `$ARI_REGISTRY_URL` +
`$ARI_REGISTRY_TOKEN`.
