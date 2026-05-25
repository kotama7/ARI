---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-core/ari/cli_ear.py
    role: implementation
last_verified: 2026-05-25
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
| `ari status` | Show experiment tree and summary | Monitor / Tree page |
| `ari viz` | Launch the web dashboard | — |
| `ari projects` | List all past experiments | Experiments page |
| `ari show` | Show detailed results for a run | Results page |
| `ari delete` | Delete a checkpoint | Experiments page → Delete button |
| `ari settings` | View or modify configuration | Settings page |
| `ari skills-list` | List available tools | Settings → MCP Skills |
| `ari memory ...` | Manage the Letta memory backend | Settings → Memory (Letta) |
| `ari ear <subcmd>` | EAR curation/publishing/promotion lifecycle (v0.7.0) | — |
| `ari clone <ref>` | Fetch a curated EAR bundle (file/https/ari/gh/doi); verify by digest (v0.7.0) | — |
| `ari registry <subcmd>` | Self-hosted EAR registry: `serve` / `token issue|revoke|list` (v0.7.0) | — |
| `ari migrate node-reports <checkpoint>` | Backfill `node_report.json` for legacy (v0.6.0) checkpoints | — |

---

## ari run

Run a new experiment from an experiment Markdown file.

```bash
ari run <experiment.md> [--config <config.yaml>] [--profile <profile>]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `experiment.md` | Yes | Path to experiment Markdown file |
| `--config` | No | Custom config YAML (auto-generated if omitted) |
| `--profile` | No | Environment profile: `laptop`, `hpc`, or `cloud` |

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
```

**What happens:**

1. ARI generates a unique project name (LLM-generated title)
2. Creates checkpoint directory: `./checkpoints/<run_id>/`
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
ari resume ./checkpoints/20260328_matrix_opt/
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

# 16 bundled rubrics: neurips (default, v2-compatible), iclr, icml, cvpr, acl,
#   sc, chi, osdi, stoc, icra, siggraph, nature, usenix_security,
#   journal_generic, workshop, generic_conference. Plus the built-in `legacy`
#   fallback for v0.5 schema. Drop a new <id>.yaml into
#   ari-core/config/reviewer_rubrics/ to add any venue.
```

**Example — v2-compatible default (NeurIPS form, 1-shot, 5 reflections):**

```bash
ari paper ./checkpoints/20260328_matrix_opt/
```

**Example — Supercomputing (SC) rubric with 5-reviewer ensemble + meta-review:**

```bash
ari paper ./checkpoints/20260328_matrix_opt/ \
          --rubric sc --num-reviews-ensemble 5
```

The paper pipeline runs: data transformation, figure generation, paper writing,
VLM figure review, **rubric-driven paper review** (rubric form + reflection +
optional ensemble + Area Chair meta-review), and reproducibility check (ReAct
agent driven by `ari/agent/react_driver.py`).

CLI flags can also be set via env vars: `ARI_RUBRIC`, `ARI_FEWSHOT_MODE`,
`ARI_NUM_REVIEWS_ENSEMBLE`, `ARI_NUM_REFLECTIONS`.

---

## ari status

Display the experiment tree and summary statistics.

```bash
ari status <checkpoint_dir>
```

**Example:**

```bash
ari status ./checkpoints/20260328_matrix_opt/

# Output:
# ── Experiment Tree ──
# root (success) score=153736
# ├── improve_1 (success) score=180200
# │   ├── ablation_1 (success) score=120000
# │   └── validation_1 (success) score=178500
# └── draft_2 (failed)
#
# Summary: 4 success, 1 failed, 0 running, 0 pending
```

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
ari viz ./checkpoints/ --port 8765

# Monitor a specific run
ari viz ./checkpoints/20260328_matrix_opt/ --port 9878
```

Open `http://localhost:<port>` in your browser. See the [QuickStart Guide](../getting-started/quickstart.md) for dashboard usage.

---

## ari projects

List all past experiment runs.

```bash
ari projects [--checkpoints <dir>]
```

**Example:**

```bash
ari projects

# Output:
# ID                              Nodes  Status    Best Score  Modified
# 20260328_matrix_opt             28     complete  153736      2h ago
# 20260327_sorting_benchmark      12     complete  0.95        1d ago
# 20260326_sample_experiment           5      failed    --          2d ago
```

---

## ari show

Show detailed results for a specific experiment.

```bash
ari show <checkpoint> [--checkpoints-dir <dir>]
```

Displays the experiment tree, review report summary, and list of artifacts.

---

## ari delete

Delete a checkpoint directory.

```bash
ari delete <checkpoint> [--yes]
```

| Flag | Description |
|------|-------------|
| `-y` / `--yes` | Skip confirmation prompt |

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

The reconstructed reports get `migration_source: "auto"` so downstream
filters can apply slightly more conservative rules (e.g. `for_code` keeps
auto-reconstructed nodes even if the recovered `files_changed` is empty,
since the diff may have been impossible to recover). Fields that cannot
be inferred (`original_direction`, `delta_vs_parent`, `next_steps_hints`)
are nulled.

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
ari ear curate ./checkpoints/run_20260504_xy/

# 2. Inspect what made it past the allow/deny rules.
ari ear status ./checkpoints/run_20260504_xy/
# bundle_sha256: 0ccabb16...
# files:         42
# visibility:    staged

# 3. Ship it to a registry (still staged).
ari ear publish ./checkpoints/run_20260504_xy/ --backend ari-registry

# 4. After the reviewer + reproducibility check pass, promote to public.
ari ear promote ./checkpoints/run_20260504_xy/ --target public
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
| `migrate` | One-shot import of v0.5.x `memory_store.jsonl` (+ `memory.json` with `--react`) into the checkpoint's Letta collections. Source files are renamed to `*.migrated-<ts>`. |
| `backup` | Snapshot Letta-stored memory to `{ckpt}/memory_backup.jsonl.gz` (gzipped JSONL). Written automatically at pipeline-stage boundaries and on shutdown. |
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
| `ARI_BACKEND` | LLM backend (`ollama` / `openai` / `anthropic` / `claude`) | `ollama` |
| `ARI_MODEL` | Model name | `qwen3:8b` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `OLLAMA_HOST` | Ollama server URL | `http://localhost:11434` |
| `LLM_API_BASE` | Generic API base URL (fallback) | — |

### BFTS Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_MAX_NODES` | Maximum total experiments | 50 |
| `ARI_MAX_DEPTH` | Maximum tree depth | 5 |
| `ARI_PARALLEL` | Concurrent experiments | 4 |
| `ARI_MAX_REACT` | Max ReAct steps per node | 80 |
| `ARI_TIMEOUT_NODE` | Timeout per node (seconds) | 7200 |

### HPC Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_EXECUTOR` | Execution backend (`local` / `slurm` / `pbs` / `lsf`) | `local` |
| `ARI_SLURM_PARTITION` | SLURM partition name | — |
| `ARI_SLURM_CPUS` | Override CPU count for SLURM jobs | (auto-detected) |

### Retrieval & VLM

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_RETRIEVAL_BACKEND` | Paper search: `semantic_scholar` / `alphaxiv` / `both` | `semantic_scholar` |
| `VLM_MODEL` | VLM model for figure review | `openai/gpt-4o` |
| `ARI_ORCHESTRATOR_PORT` | HTTP port for orchestrator skill | `9890` |

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
| `ARI_MEMORY_BACKUP_INTERVAL_S` | Opportunistic backup during run (0 = off) | `0` |

### Per-Phase Model Overrides

| Variable | Phase |
|----------|-------|
| `ARI_MODEL_IDEA` | Idea generation |
| `ARI_MODEL_BFTS` | BFTS experiments |
| `ARI_MODEL_PAPER` | Paper writing |

### .env File

ARI loads `.env` files automatically (checked in order):

1. `<checkpoint_dir>/.env` (highest priority)
2. `<project_root>/.env`
3. `<project_root>/ari-core/.env`
4. `~/.env` (lowest priority)

Format: `KEY=VALUE` (lines starting with `#` are ignored).

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
--no-extract            Just fetch the tarball; do not extract it.
--registry <name>       Limit ari:// resolver to a named registry from
                        registries.yaml.  Set $ARI_REGISTRIES_FILE or
                        place the file under
                        $ARI_CHECKPOINT_DIR/.ari/registries.yaml; the
                        legacy $HOME/.ari/registries.yaml fallback was
                        removed in v0.5.0 and emits a
                        DeprecationWarning until v1.0.
--token <env-or-value>  Bearer token. Looked up in $ENV first, falls back
                        to the literal value (so you can pass either
                        --token MY_TOKEN_VAR or --token "raw-token-string").
```

### Verification model

1. The resolver writes the artifact (tarball or directory) into a temp dir.
2. The orchestrator extracts into a *sibling* temp dir.
3. Each file's sha256 is recomputed and compared against `manifest.lock`.
4. The whole-bundle digest is re-derived from the canonical
   files-only manifest and compared to `manifest.lock.bundle_sha256`.
5. If `--expect-sha256` was given, that value must equal the recomputed
   digest. Hard fail on mismatch.
6. The temp dir is renamed into `dest`. A failure at any earlier step
   leaves no partial dest behind.

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
# 1. Install server deps (skipped by the default install to stay slim).
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
| Endpoints | `POST /artifact`, `GET\|HEAD /artifact/<id>`, `GET /artifact/<id>/manifest.lock`, `POST /artifact/<id>/promote`, `DELETE /artifact/<id>`, `/healthz`, `/version` |
| Auth | bearer-token (sqlite-hashed); upload + delete + promote require owner token |
| Visibility | `staged` (owner only) → `unlisted` (id-only) / `public` (open). Demotion rejected. |
| Artifact id | `sha256(bundle.tar.gz)[:16]` (content-addressed) |
| Storage | `${ARI_REGISTRY_DATA}/artifacts/<id>/{bundle.tar.gz, manifest.lock, meta.json}` |

Deploy modes (see [docs/reference/registry.md](registry.md) for full details):

- `scripts/registry/start_local.sh` — uvicorn + sqlite, single-process. Laptop / dev.
- `scripts/registry/docker-compose.yml` — nginx + uvicorn + sqlite-on-volume. Production.
- `scripts/registry/start_singularity.sh` — Apptainer / Singularity SIF. HPC.

Configure the client by writing `registries.yaml` to one of the
v0.5.0+ locations (`$ARI_REGISTRIES_FILE` env override, the active
`$ARI_CHECKPOINT_DIR/.ari/registries.yaml`, or
`./.ari/registries.yaml`); the legacy `$HOME/.ari/registries.yaml`
fallback emits a DeprecationWarning and is removed in v1.0:

```yaml
registries:
  - name: default
    url: http://127.0.0.1:8290
    token: $ARI_REGISTRY_TOKEN
```

Then `export ARI_REGISTRY_TOKEN=ari_<paste-from-issue>` and use
`ari clone ari://<id>` or `ari ear publish --backend ari-registry`.
