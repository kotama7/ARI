---
sources:
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/PaperBench
    role: implementation
  - path: ari-core/ari/viz/frontend/src/app/routeRegistry.ts
    role: implementation
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/src/sandbox.py
    role: implementation
  - path: ari-skill-replicate/src/generator.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/contracts.py
    role: implementation
last_verified: 2026-08-16
---

# PaperBench GUI guide

The dashboard exposes PaperBench at the **📚 PaperBench** sidebar entry.
Routes are hash routes (`#/paperbench…`); only the registry has a nav
entry, the other three are reachable in-page only:

- `#/paperbench` — paper registry list
- `#/paperbench/import` — import form
- `#/paperbench/run` — 5-step run wizard
- `#/paperbench/results?job=<job_id>` — rubric tree + live log stream

## Paper registry (`#/paperbench`)

Shows every paper in `{workspace_root}/paper_registry/manifest.jsonl`.
The root is `ARI_PAPER_REGISTRY_DIR` when set, otherwise
`PathManager.from_env().paper_registry_root` — a workspace-rooted
directory (`{workspace}/paper_registry`, falling back to
`./paper_registry` when no checkpoint is active). It is **not** under
`~/.ari/`; v0.5+ ARI keeps no global per-user data directory. Each row:

- ☑ checkbox — multi-select. The selection is not carried into the
  wizard; step 1 asks again.
- `paper_id` — sanitized filesystem-safe slug.
- Title.
- License badge — green ✅ when the assessment is `usable`
  (permissive AND redistributable AND not non-commercial), red ⚠
  otherwise. Hover for the assessment note.
- Source — `arxiv: 2404.14193`, `doi: 10.1109/...`, etc.
- Delete — `POST /api/paperbench/papers/<paper_id>/delete`; drops the
  manifest entry and the paper's directory.

Top action bar:
- **📥 Import paper** → `#/paperbench/import`
- **🚀 Run PaperBench (N)** → `#/paperbench/run` (disabled until N≥1)
- **Refresh** — re-reads the manifest.

## Paper import (`#/paperbench/import`)

| Field | Notes |
|---|---|
| Source type | `arxiv` \| `doi` \| `upload` \| `local` |
| Source identifier | arXiv ID (`2404.14193`), DOI, PDF path |
| PDF file | shown only for `source_type=upload`; staged via `POST /api/upload` |
| Title | required |
| Authors | comma/semicolon-separated |
| Venue / Year | optional |
| License | free-form; classified server-side |
| Artifact URL | optional code repo URL |

The badge under the license input is **not** the server's verdict: it
is an optimistic client-side regex
(`/^cc(\s|-)by(\s|-)?(4\.?0)?$|^(mit|apache|bsd|arxiv)/i`) that only
approximates `_classify_license`, so e.g. `CC0` shows ⚠ in the form and
comes back `usable` from the server. The authoritative
`license_assessment` arrives in the import response and is what the
registry row renders.

- ✅ "Permissive license — usable" — MIT, Apache-2.0, BSD-2/3-Clause,
  CC0, CC BY, CC BY-SA, arXiv non-exclusive.
- ⚠ "License may require review" — anything else, including unknown
  strings **and CC BY-NC**, which `_classify_license` reports as
  permissive but non-commercial and therefore NOT usable.

arXiv metadata auto-fetch has shipped: with `source_type=arxiv` a
**Fetch metadata** button calls `GET /api/paperbench/arxiv/<id>` and
fills title / authors / year / license (`"arXiv non-exclusive"`). It
does **not** fetch the PDF — the response carries a `pdf_url` that
nothing downloads. Since the run worker aborts when
`papers/<paper_id>/paper.pdf` is missing, an arXiv-only import still
needs the PDF attached by hand.

## Run wizard (`#/paperbench/run`)

5 steps, all configs flow into a single `POST /api/paperbench/run` body.

### Step 1 — Papers

Multi-select from the registry. The Next button stays disabled until
at least one paper is selected.

### Step 2 — Rubric config

- **Model** — a free-text field, not a dropdown; default
  `gemini/gemini-2.5-pro`. Anything LiteLLM understands works.
- **Target leaves** — `0` (auto from paper length: `words // 75`,
  clamped to `[50, 400]`).

There is no two-stage toggle. The generator is unconditionally
`hierarchical-v2` (skeleton pass + parallel subtree passes); its
`max_model_calls` (64) and `subtree_concurrency` (4) are accepted by
`POST /api/paperbench/run` but have no wizard field.

### Step 3 — Reproduce config

Top form:
- **Model** — replicator agent model (default `gpt-5-mini`).
- **Time limit** — seconds; default 12 h (PaperBench paper §5.2).
- **Sandbox** — `auto` / `slurm` / `local` / `apptainer` / `docker`.
- **Container image** (v1.0) — local non-symlink SIF, full Docker
  `sha256:<image-id>`, or a `docker://` / `library://` URI pinned with
  `@sha256:<digest>`. Mutable tags and short aliases are rejected —
  including the ones the field's own placeholder shows. Required
  for `sandbox=docker` / `apptainer` / `singularity`; for `local` /
  `slurm` it is **rejected, not ignored** (`resolve_image` raises
  *"container_image is only valid for a container sandbox"*), so clear
  the box when you switch back to a non-container sandbox.
- **Partition** — only relevant for `slurm`.

**Execution profile override** (the v0.7.2 focal point):

A 13-field grid lets you override any rubric-supplied execution_profile
hint. The fields always start at `0` / `""` — the wizard does no
pre-filling. Merging with the rubric's `execution_profile` happens
server-side in `run_reproduce`, where a non-zero caller value wins and a
zero/empty one falls through to the rubric hint.

| Field | Type | SLURM flag |
|---|---|---|
| nodes | int | `--nodes` (defaults to 1) |
| ntasks | int | `--ntasks` — always emitted; defaults to `ntasks_per_node × nodes`, else 1 |
| ntasks_per_node | int | `--ntasks-per-node` |
| gpus_per_task | int | `--gpus-per-task=[<gpu_type>:]<n>` |
| memory_gb_per_node | int | `--mem=<n×1024>M` |
| exclusive | bool | `--exclusive` |
| gpu_type | str | prefixes the GPU count; alone (no count) it implies `gpus_per_node=1` → `--gres=gpu:<type>:1` |
| constraint | str | `--constraint` |
| cpu_bind | str | **rejected for `sandbox=slurm`** — see below |
| mem_bind | str | **rejected for `sandbox=slurm`** — see below |
| hint | str | `--hint`; only `compute_bound`, `memory_bound`, `multithread`, `nomultithread` validate |
| nodelist | str | `--nodelist` |
| extra_sbatch_args | str (space-separated) | **not** a pass-through: only `--account=`, `--qos=`, `--reservation=`, `--hint=` are accepted and translated into typed fields; any other entry fails the run |

Two traps in that grid:

- `cpu_bind` / `mem_bind` are not translated into `srun --cpu-bind` /
  `--mem-bind`. Setting either with `sandbox=slurm` makes
  `_execute_reproduction_slurm` raise *"cpu_bind and mem_bind are srun
  job-step settings; place them explicitly in reproduce.sh"*, which the
  tool records as a failed attempt. Put the binding in `reproduce.sh`.
- `gpus_per_node` and `gpus_per_task` are mutually exclusive at the
  contract layer, and `gpu_type` without any count is rejected there —
  the skill's implicit `gpus_per_node=1` is what keeps a bare `gpu_type`
  legal.

See [Execution profile reference](../../reference/execution_profile.md)
for full semantics.

**Fail-loud preconditions (v0.8.0).** When the requested sandbox /
GPU resource is unavailable on the host, the run fails rather than
silently downgrading to local CPU. The exceptions do not propagate to
the caller: `run_reproduce` catches them and returns
`{"executed": false, "error": …, "failure_kind": …, "attempt_status":
"failed"}`, with the attempt retained as evidence.

- `sandbox=apptainer`/`singularity`/`docker` but the runtime binary is
  missing → `ReproductionContractError` *"sandbox runtime is
  unavailable"* → `failure_kind: "sandbox-unavailable"`
- `sandbox=slurm` but `sbatch` missing or no partition resolved →
  `RuntimeError` → `failure_kind: "scheduler-failure"`
- contradictory or unsupported typed GPU shape → validation/scheduler
  error, recorded the same way

A docker daemon that is down but whose client is on PATH is not caught
by the precondition — it surfaces as a non-zero `docker run` exit.

There is no missing-sandbox fallback. GPU requests likewise have no
silent-drop override. See
[environment variables](../../reference/environment_variables.md#paperbench-reproduction-phase-stage-2).

**Network policy is not exposed by the wizard.** `run_reproduce`
defaults to `network_policy="deny"` with
`network_isolation_attested=False`, and the worker forwards neither, so
a wizard launch with `sandbox=local` or `slurm` is rejected at plan
time with *"sandbox_kind=… cannot prove network denial"*. Only a
container sandbox proves denial through its namespace; otherwise drive
Stage 2 from the MCP tool or the bridge, where both arguments exist.

### Step 4 — Judge config

- **Model** — free-text; default `gpt-5-mini`.
- **n_runs** — 1 (PaperBench paper §4.1). `0` resolves to
  `ARI_JUDGE_N_RUNS`, else 1; the tool rejects anything outside `[1, 100]`.
- **Skip negative control** — leave off; it's a cheap sanity check.
- **Code-only** — explicit opt-in that prunes a verified reproduction to Code
  Development leaves. A missing Stage 2 record fails without a score; it does
  not silently change grading scope. Mirrors vendor
  `paperbench/grade.py:109-112`; prevents
  agent was never asked to execute. The wizard has **no** control for it:
  `judge_config.code_only` reaches the skill only if you hand-craft the
  `POST /api/paperbench/run` body.

`grade_with_simplejudge` resolves a verified `ReproductionRunV1` from
`repo_dir` before anything else. No record, an unreadable record, or a
record whose `status` is not `succeeded` produces a `GradeReportV1` with
`status="failed"` and `ors_score=None` — never a silently rescoped pass.

### Step 5 — Launch

Shows the summary + live cost estimate
(`POST /api/paperbench/cost-estimate`). Click *Dry run (cost estimate
only)* to verify, then *🚀 Launch all* to enqueue jobs. Each paper
becomes one `job_id`.

## Monitoring

The Run wizard returns the `job_id` list. In the GUI, open
`#/paperbench/results?job=<job_id>`: it reads the status once, then
opens an `EventSource` on `/api/paperbench/run/<job_id>/logs` and
appends `log` events until a `done` event arrives. Each stream is capped
at 5 minutes server-side; the browser resumes with `Last-Event-ID`.

Status:

```bash
curl http://localhost:8765/api/paperbench/run/<job_id>
```

Results (when status flips to `completed`):

```bash
curl http://localhost:8765/api/paperbench/run/<job_id>/results
```

Job records are persisted to `{registry_root}/jobs/<job_id>.json`
(mode `0o600`), so they survive a viz-server restart. A record still
carrying `queued`/`running` after a restart is reported with the
additive status `interrupted` — the worker thread died with the old
process and is deliberately never respawned. `/results` answers
`{"error": "results not available", "status": …}` for anything but
`completed`.

## See also

- [Paper import](paper_import.md)
- [Quickstart](paperbench_quickstart.md)
- [Execution profile reference](../../reference/execution_profile.md)
- [API reference](../../reference/api_paperbench.md)
