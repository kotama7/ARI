# PaperBench quickstart

A 5-minute walkthrough from importing an external paper to viewing its
PaperBench audit score.

## Prerequisites

- ARI installed (`pip install -e ari-core/`).
- The viz server running (`ari viz` or `python -m ari.viz.server`).
- An LLM provider configured in `.env` (e.g. `OPENAI_API_KEY` or
  `GEMINI_API_KEY`).
- For SLURM dispatch: `sbatch` on PATH plus
  [`docs/howto/multi_node_setup.md`](multi_node_setup.md).

## 1. Import a paper

Open the dashboard, click the **📚 PaperBench** sidebar entry, then
**📥 Import paper**. Fill in the form (arXiv ID / DOI / upload), then
**Save to registry**. The license badge turns green when the input is
auto-classified as permissive (MIT, Apache-2.0, CC BY/SA, CC0).

Equivalent CLI:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "arxiv",
    "source": "2404.14193",
    "title": "LLAMP: assessing latency tolerance",
    "license": "CC BY 4.0",
    "authors": ["Alice", "Bob"]
  }'
```

## 2. Launch the PaperBench wizard

From the registry page, tick one or more papers and click
**🚀 Run PaperBench**. The 5-step wizard walks through:

1. **Papers** — verify your selection.
2. **Rubric** — pick the generator model (default `gemini-2.5-pro`,
   two-stage on). See [Rubric schema](../reference/execution_profile.md).
3. **Reproduce** — choose the replicator model + time budget +
   sandbox kind (`auto` / `local` / `apptainer` / `docker` / `slurm`) +
   `container_image` (SIF path, `docker://` URI, or short alias
   `pb-env` / `pb-reproducer` when you ran
   `scripts/build_pb_images.sh`). Expand *Execution profile override*
   to override SLURM allocation flags (`--nodes`, `--gpus-per-task`,
   `gpu_type`, `memory_gb_per_node`, `--exclusive`, `extra_sbatch_args`,
   …). When the rubric already carries an `execution_profile`, these
   fields pre-fill from it. Caller args always win over rubric hints.
4. **Judge** — set the SimpleJudge model + `n_runs` (default 1 — see
   PaperBench paper §4.1). When Stage 2 (reproduce) is skipped, the
   judge auto-enables `code_only` mode so the rubric is pruned to
   Code Development leaves (mirrors vendor `paperbench/grade.py:109-112`
   and prevents systematic 0s on Result Analysis leaves the agent
   was never asked to execute).
5. **Launch** — review the cost estimate, then click *Dry run* to verify
   or *Launch all* to enqueue the jobs.

> **Fail-loud preconditions.** Wizard requests sandbox/GPU resources
> the host cannot satisfy raise loudly rather than silently downgrading
> to the host CPU. To opt back into the legacy silent fallback, set:
> - `ARI_PHASE1_ALLOW_FALLBACK=1` — when docker daemon / apptainer
>   binary / sbatch / partition is missing, fall back to local exec.
> - `ARI_SLURM_ALLOW_NO_GRES=1` — when the cluster has no GRES
>   configured for GPUs, drop `--gres` / `--gpus-*` flags.
>
> Both default OFF (refuses the request, surfaces an actionable error).

## 3. Wait

The wizard returns one job ID per paper. The Monitor page polls
`GET /api/paperbench/run/<job_id>` for status. Typical wall-time:
~30 min for a CPU-only smoke, several hours for a faithful GPU
reproduction.

## 4. Read the score

When status flips to `completed`, the Results page renders the rubric
tree with per-leaf pass/fail colouring and the aggregate ORS score. The
underlying JSON is available at
`GET /api/paperbench/run/<job_id>/results`.

## 5. Generate the audit report (optional)

For a human-readable PDF/HTML write-up:

```bash
make -C report audit-report \
  CHECKPOINT=/var/tmp/ari/.../<checkpoint-id> \
  PAPER_ID=<paper_id> \
  AUDIT_LANGS="en ja zh"
```

See [`report/scripts/paperbench_report.py`](../../report/scripts/paperbench_report.py)
for the Python API.

## 6. (Advanced) Switch rubric framing by venue

`generate_rubric` defaults to the original PaperBench framing — direct
children decompose the paper by contribution, leaves grade submission
output. For **paper-audit** research (does the paper itself describe
enough to reproduce?) select a venue-conditioned template via
`paperbench_rubric_id`. Shipped IDs:

- `generic` — back-compat default
- `sc` — six HPC axes (env / data / execution / figures / scaling / conclusion)
- `neurips` — NeurIPS Reproducibility Checklist axes
- `nature` — wet-lab Reporting Summary axes

CLI dogfood (no GUI, no SLURM — calls `generate_rubric_async` directly
through `scripts/sc_paper_dogfood.py`):

```bash
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/sc24_paper.pdf \
    --rubric-template sc \
    --rubric-model gpt-5-mini \
    --target-leaves 30
```

The output `rubric.json` will have exactly six direct children
matching `sc.yaml`'s `top_level_axes`, with leaves phrased as
`"X is identifiable in the paper or AD"` instead of `"the
implementation does X"`. Adding a new venue is a YAML-only change —
see [`rubric_schema.md`](../reference/rubric_schema.md#venue-conditioned-templates).

## 7. (Advanced) Full 3-stage protocol via CLI

The dogfood script also drives PaperBench's full Stage 1 → Stage 2 →
Stage 3 protocol via the bridge surface
(`ari-skill-paper-re/src/_paperbench_bridge.py`). Stage 1
(`rollout_submission`) runs a vendor BasicAgent / IterativeAgent that
writes `reproduce.sh`. Stage 2 (`reproduce_submission`) executes it in
the chosen sandbox and captures `reproduce.log` + an
`submission_executed_<UTC>.tar.gz` provenance snapshot. Stage 3
(`judge_submission`) grades the executed submission.

```bash
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/paper.pdf \
    --rubric-model gpt-5-mini --two-stage \
    --with-rollout \
        --rollout-model gpt-5-mini \
        --rollout-time-limit-sec 14400 \
        --rollout-sandbox local \
    --with-reproduction \
        --reproduce-sandbox slurm \
        --reproduce-partition <PARTITION> \
        --reproduce-gpus-per-task 1 \
        --reproduce-time-limit-sec 7200 \
    --judge-dryrun --judge-model gpt-5-mini \
    --out $HOME/.ari_pb_<run_id>
```

Mutually exclusive with `--paper-audit-mode` (and with `paper_audit`
rubric templates such as `sc.yaml` — these grade the paper itself,
not an executed submission). To run the full protocol with vendor
images, first build `pb-env` / `pb-reproducer` via
`scripts/build_pb_images.sh` then pass
`--rollout-container-image pb-env --reproduce-container-image pb-reproducer`.

## HPC cluster sbatch wrapper (illustrative)

The ARI bridge does NOT auto-load cluster modules — that is the user's
responsibility, following standard HPC practice (NERSC / OLCF / LLNL
all recommend putting `module load` at the TOP of your sbatch script).
The bridge probes `module avail` at rollout start and surfaces the
cluster catalog to the agent as DATA; the agent decides which module
to load. If you want deterministic toolchain availability, pre-load
the modules in your sbatch wrapper BEFORE invoking ARI — this is the
canonical HPC pattern.

Example (R-CCS ai-l40s partition — **adjust the module / partition /
GPU spec for YOUR cluster**):

```bash
#!/bin/bash
#SBATCH --partition=ai-l40s
#SBATCH --gres=gpu:L40S-44GB:1
#SBATCH --cpus-per-task=8
#SBATCH --time=08:00:00
#SBATCH --output=workspace/checkpoints/<ts>_<slug>/sbatch.log
#SBATCH --export=ALL
set -eu

# Pre-load the toolchain modules your paper needs. The names below are
# R-CCS specific — replace with your cluster's equivalents (use
# `module avail` on a login node to discover the catalog).
module load system/ai-l40s        # cluster-specific entry module
module load nvhpc                  # if the paper needs CUDA / nvcc
# module load openmpi              # if the paper needs MPI
# module load fftw                 # if the paper needs FFTW

cd /path/to/ARI
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/paper.pdf \
    --rubric-model gpt-5-mini --two-stage \
    --with-rollout --rollout-model gpt-5-mini \
        --rollout-time-limit-sec 14400 --rollout-sandbox local \
    --with-reproduction --reproduce-sandbox local \
        --reproduce-time-limit-sec 7200 \
    --judge-dryrun --judge-model gpt-5-mini \
    --out workspace/checkpoints/<ts>_<slug>
```

What this gives you:

- The python process inherits the loaded env (PATH includes nvcc, etc).
- Stage 1's agent subprocess inherits the same env via `Popen` env
  inheritance → agent's bash tool sees nvcc on PATH from turn 1.
- Stage 2's `bash submission/reproduce.sh` inherits the same env →
  reproduce.sh works at grade time even if the agent forgot to
  `module load` inside reproduce.sh itself.

What this does NOT replace:

- The agent should STILL put `module load <NAME>` at the top of
  `submission/reproduce.sh` so the script is portable to grading
  environments (vendor PaperBench eval runs in Docker with no module).
  The bridge's env-truth notes + paper-kind addendum explicitly
  instruct the agent to do this in STEP 2.

If you DO NOT pre-load (Pattern A: minimal sbatch with no module load):

- The bridge still works.
- The agent self-discovers via the `module avail` catalog in the
  env-truth notes and the paper-kind addendum's runbook STEP 1.
- Less deterministic — the agent may forget to module load in its
  iteration shell and produce a Python proxy of a CUDA paper.
- Use Pattern A for ML / pure-Python papers where toolchain
  pre-loading is unnecessary.

## Next steps

- [Rubric schema + venue templates](../reference/rubric_schema.md)
- [Execution profile reference](../reference/execution_profile.md)
- [Multi-node setup](multi_node_setup.md)
- [Compute-node safety conventions](compute_node_safety.md)
- [Troubleshooting](paperbench_troubleshooting.md)
- [PaperBench bridge API](../reference/api_paperbench.md)
- [Environment variables](../reference/environment_variables.md)
