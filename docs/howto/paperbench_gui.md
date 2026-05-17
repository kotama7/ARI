# PaperBench GUI guide

The dashboard exposes PaperBench at the **📚 PaperBench** sidebar entry.
Two top-level pages:

- `/paperbench` — paper registry list
- `/paperbench/run` — 5-step run wizard

## Paper registry (`/paperbench`)

Shows every paper in `~/.ari/paper_registry/manifest.jsonl` (override
with `ARI_PAPER_REGISTRY_DIR`). Each row:

- ☑ checkbox — multi-select for the wizard.
- `paper_id` — sanitized filesystem-safe slug.
- Title.
- License badge — green ✅ when permissive (MIT, Apache, CC BY/SA, CC0,
  arXiv non-exclusive), amber ⚠ otherwise. Hover for the assessment
  note.
- Source — `arxiv:2404.14193`, `doi:10.1109/...`, etc.
- Delete — drops the manifest entry and the paper's directory.

Top action bar:
- **📥 Import paper** → `/paperbench/import`
- **🚀 Run PaperBench (N)** → `/paperbench/run` (disabled until N≥1)
- **Refresh** — re-reads the manifest.

## Paper import (`/paperbench/import`)

Minimal form for v0.7.2:

| Field | Notes |
|---|---|
| Source type | `arxiv` \| `doi` \| `upload` \| `local` |
| Source identifier | arXiv ID (`2404.14193`), DOI, PDF path |
| Title | required |
| Authors | comma-separated |
| Venue / Year | optional |
| License | free-form; classified server-side |
| Artifact URL | optional code repo URL |

The license badge under the input mirrors the server's
`_classify_license` output:

- ✅ "Permissive license — usable" — MIT, Apache-2.0, BSD, CC0, CC BY,
  CC BY-SA.
- ⚠ "License may require review" — anything else, including unknown
  strings.

Auto-fetch of arXiv metadata + PDF (FR-PI-2 in
[`PLAN_GUI_PAPERBENCH.md`](../../ari-core/PLAN_GUI_PAPERBENCH.md))
remains a v0.7.3 follow-up.

## Run wizard (`/paperbench/run`)

5 steps, all configs flow into a single `POST /api/paperbench/run` body.

### Step 1 — Papers

Multi-select from the registry. The Next button stays disabled until
at least one paper is selected.

### Step 2 — Rubric config

- **Model** — `gemini-2.5-pro` (default), `gpt-5.4`, `claude-opus-4-7`.
- **Two-stage** — skeleton + parallel subtree calls. ~4× more leaves,
  ~5× the API cost. Default on.
- **Target leaves** — `0` (auto from paper length, ~1 leaf / 75 words).

### Step 3 — Reproduce config

Top form:
- **Model** — replicator agent model (default `gpt-5-mini`).
- **Time limit** — seconds; default 12 h (PaperBench paper §5.2).
- **Sandbox** — `auto` / `slurm` / `local` / `apptainer` / `docker`.
- **Partition** — only relevant for `slurm`.

**Execution profile override** (the v0.7.2 focal point):

A 16-field grid lets you override any rubric-supplied execution_profile
hint. When the selected paper's rubric already carries an
`execution_profile`, the fields pre-fill from it; otherwise they start
at 0/"".

| Field | Type | SLURM flag |
|---|---|---|
| nodes | int | `--nodes` |
| ntasks | int | `--ntasks` |
| ntasks_per_node | int | `--ntasks-per-node` |
| gpus_per_task | int | `--gpus-per-task` |
| memory_gb_per_node | int | `--mem` |
| exclusive | bool | `--exclusive` |
| gpu_type | str | `--gres=gpu:<type>:N` (gated by `_slurm_has_gres()`) |
| constraint | str | `--constraint` |
| cpu_bind | str | `--cpu-bind` |
| mem_bind | str | `--mem-bind` |
| hint | str | `--hint` |
| nodelist | str | `--nodelist` |
| extra_sbatch_args | str (space-sep) | pass-through |

See [Execution profile reference](../reference/execution_profile.md)
for full semantics.

### Step 4 — Judge config

- **Model** — `gpt-5-mini` (default), `claude-haiku-4-5-20251001`.
- **n_runs** — 1 (PaperBench paper §4.1).
- **Skip negative control** — leave off; it's a cheap sanity check.

### Step 5 — Launch

Shows the summary + live cost estimate
(`POST /api/paperbench/cost-estimate`). Click *Dry run (cost estimate
only)* to verify, then *🚀 Launch all* to enqueue jobs. Each paper
becomes one `job_id`.

## Monitoring

The Run wizard returns the `job_id` list. Status:

```bash
curl http://localhost:8765/api/paperbench/run/<job_id>
```

Results (when status flips to `completed`):

```bash
curl http://localhost:8765/api/paperbench/run/<job_id>/results
```

## See also

- [Paper import](paper_import.md)
- [Quickstart](paperbench_quickstart.md)
- [Execution profile reference](../reference/execution_profile.md)
- [API reference](../reference/api_paperbench.md)
