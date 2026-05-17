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
3. **Reproduce** — choose the replicator model + time budget. Expand
   *Execution profile override* to override SLURM allocation flags
   (`--nodes`, `--gpus-per-task`, `--exclusive`, ...). When the rubric
   already carries an `execution_profile`, these fields pre-fill from it.
4. **Judge** — set the SimpleJudge model + `n_runs` (default 1 — see
   PaperBench paper §4.1).
5. **Launch** — review the cost estimate, then click *Dry run* to verify
   or *Launch all* to enqueue the jobs.

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

## Next steps

- [Rubric schema + venue templates](../reference/rubric_schema.md)
- [Execution profile reference](../reference/execution_profile.md)
- [Multi-node setup](multi_node_setup.md)
- [Compute-node safety conventions](compute_node_safety.md)
- [Troubleshooting](paperbench_troubleshooting.md)
