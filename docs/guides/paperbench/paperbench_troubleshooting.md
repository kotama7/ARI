---
sources:
  - path: ari-skill-paper-re
    role: implementation
  - path: ari-skill-replicate
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/PaperBench/PaperBenchWizard.tsx
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: report/scripts/paperbench_report.py
    role: implementation
last_verified: 2026-08-16
---

# PaperBench troubleshooting

Common failure modes and their fixes. The audit run pipeline is
`generate_rubric → audit_rubric → build_reproduce_sh → run_reproduce →
grade_with_simplejudge`; issues usually fall into one of those stages.
`audit_rubric` is non-fatal — a failing audit is logged and the run
continues.

## Rubric generation

### Q. The rubric has 0 leaves.

The generator fell back through all 3 retries without producing valid
JSON. Inspect the worklog for the last failure. Typical causes:
- LLM rate limit (retry after a few minutes).
- The paper PDF parsed to an empty string — re-upload, or convert with
  `pdftotext` first.

### Q. `task_category` errors on grader load.

The grader rejects `"Result Visualization"` or other non-PaperBench
categories. The generator's `normalize_rubric_node` pass should clamp
these to the allow-list (`Code Development`, `Code Execution`,
`Result Analysis`). If the error persists, re-generate with the
latest `gemini-2.5-pro` build — older models drift more.

## Replicator (BasicAgent)

### Q. Agent never wrote `reproduce.sh`.

The 12 h rollout exhausted its time without invoking `submit`.
Possible causes:
- Model output was truncated (look for `TOOL OUTPUT TRUNCATED` in
  `agent.log` — usually benign).
- The paper text was beyond the model's context; try a smaller paper
  or use `iterative_agent=true`.

### Q. Agent submitted CPU code for a GPU paper.

The rubric's `execution_profile.kind` was probably empty. Verify with:

```bash
jq '.reproduce_contract.execution_profile' rubric.json
```

Regenerating will not necessarily fill it in: `skeleton.md` tells the
generator to **omit `execution_profile` entirely** unless the paper
explicitly states parallel/distributed execution properties ("we
evaluated at N MPI ranks", "we trained on M GPUs with data
parallelism", ...). An absent profile is the intended outcome for a
single-machine paper — including single-GPU ones — because
`_format_hpc_appendix` emits no HPC guidance at all when the profile is
empty. If the paper really does specify a GPU/parallel setup and the
generator missed it, regenerate; otherwise set the profile explicitly in
the rubric (`kind` is one of `cpu_single`, `gpu_single`, `gpu_multi`,
`mpi`, `mpi_gpu`).

### Q. Agent did not use `srun` for an MPI paper.

Check the user message that landed in `agent.log` for the
`COMPUTE-NODE EXECUTION CONVENTIONS` block. If missing, the call site
didn't pass `execution_profile`. Verify the wiring with the following —
the skill ships flat top-level modules (`_replicator_agent`, `server`,
...) rather than an `ari_skill_paper_re` package, so the import needs
`ari-skill-paper-re/src` on `PYTHONPATH`:

```bash
PYTHONPATH=ari-skill-paper-re/src python -c "
from _replicator_agent import _format_hpc_appendix
print(_format_hpc_appendix(
    expected_artifacts=['results.csv'],
    execution_profile={'kind': 'mpi_gpu', 'metric_columns': ['x']},
    cluster_shape={'SLURM_JOB_NUM_NODES':'4','SLURM_NTASKS':'32','GPU_LIST':'v100'}
))"
```

The output must contain `srun -n $SLURM_NTASKS`.

## SLURM dispatch (`run_reproduce`)

### Q. `sbatch: error: Invalid GRES gpu:v100:1`.

The selected partition cannot satisfy the typed GPU request. Check
`sinfo -o '%P %G'`, select a compatible partition, or correct the site's GRES
configuration. ARI intentionally does not drop the request or run on CPU.

### Q. sbatch went through but `reproduce.sh` ran on a single node.

`reproduce.sh` starts as one rank on the first allocated node. The
agent's prompt instructs `srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS`
fan-out — verify the script actually has that line:

```bash
grep -E 'srun.*-N.*-n' repro_sandbox/reproduce.sh
```

If missing, append it manually or regenerate with a stronger model.

### Q. `mpirun: command not found` on the compute node.

OpenMPI is not loaded in the compute node's environment. Either:
- Add `"openmpi/4.1"` (or your cluster's name) to the rubric's
  `reproduce_contract.execution_profile.module_loads`.
- Switch the script to `srun` (PMI-integrated; works without an
  explicit OpenMPI module on most SLURM sites).

### Q. Job runs but `repo_dir` files are missing on rank > 0.

`repo_dir` is on a node-local FS. ARI warns about this; the fix is
to move the checkpoint to a shared mount (`$HOME`, `/work/...`,
`/scratch/...`).

### Q. `--mem=256G` exceeds the partition limit.

The rubric over-specified memory for your site. Override at the
wizard's Step 3 (`memory_gb_per_node = <your limit>`), or edit
`execution_profile.memory_gb_per_node` directly in the rubric JSON.

## Grading (`grade_with_simplejudge`)

### Q. There is no `ors_score` in the grade response at all.

`ors_score` / `raw_score` / `score_stddev` are only present when the
grade report's status is not `failed`. A grader that could not reach a
verified reproduction publishes no number: it returns
`grade_status: "failed"` with `error` / `errors` and the stored report
carries `ors_score: null`. `grade_with_simplejudge` refuses unless it
resolves a `ReproductionRunV1` whose `status` is `succeeded`; the common
`errors` values are `no verified ReproductionRunV1 is available`,
`reproduction status is <state>; only succeeded runs are gradable`, and
`judge returned invalid scores for leaves: ...`.

The reproduction record lives under the reproduction workspace, not in a
flat result file:

```bash
ls repro_sandbox/                                  # reproduce.sh present?
jq . repro_sandbox/.ari-reproduction/latest.json   # pointer: status, run path, executed workspace
jq '.attempts[-1].status, .attempts[-1].exit_code, .attempts[-1].expected_missing' \
   repro_sandbox/.ari-reproduction/<plan_digest>/run.json
```

The grade report itself is written to `grade-report.json` under the
grade root that `grade_report_path` names.

### Q. Negative control did not pass (boilerplate scored > 5%).

The rubric's leaves are too easy to satisfy — they pattern-match
generic boilerplate. Re-audit the rubric with stricter
`task_category="Code Execution"` claims that demand specific log
output or artefact contents.

## GUI / Wizard

### Q. The wizard shows "No papers registered yet" forever.

Check `<workspace_root>/paper_registry/manifest.jsonl` exists and is
non-empty. The registry is workspace-rooted — resolved through
`PathManager.paper_registry_root` — not a per-user directory under
`~/.ari`; ARI has kept no global per-user data directory since v0.5.
`ARI_PAPER_REGISTRY_DIR` overrides the location when set.

### Q. Launch button stays disabled.

Step 1 (Papers) requires at least one paper selected. The Launch button
and the Next button on the paper step are both guarded by
`selectedIds.size === 0`.

### Q. Cost estimate is `$0`.

No paper is selected. The wizard shows
`llm_cost_usd × selectedIds.size`, so an empty selection renders
`$0.00` however Step 3 is configured.

`time_limit_sec` is not the cause: the server-side estimate reads
`time_limit_sec or 12*3600`, so a `0` falls back to the 12 h default, and
in any case the LLM-cost term is a fixed per-paper constant
(rubric `$0.45` + reproduce `$2.00` + judge `$0.10 × n_runs`) that does
not depend on the time limit — only `wall_time_sec` does. The other way
to get no number is a rejected estimate request: an unrecognised
`rubric_config` key makes `POST /api/paperbench/cost-estimate` answer
`{"error": "unknown rubric_config fields: ..."}` with no cost fields at
all.

## Report generation

### Q. The audit report came out as `.tex` with no PDF.

You will not see a `latexmk: command not found` error — the PDF step is
guarded by `shutil.which("latexmk")` and is skipped silently when the
tool is absent, so the command exits `ok` with only `.tex` sources
written. (Even when `latexmk` *is* present it runs with `check=False`, so
a LaTeX failure simply leaves no `main.pdf` behind and never raises.)
XeLaTeX is
required for the PDF target: install `texlive-xetex` (Debian/Ubuntu) or
`mactex` (macOS). To ask for `.tex` only on purpose:

```bash
python -m report.scripts.paperbench_report paper \
    --checkpoint <ckpt> --paper-id <id> \
    --output-root report/audit/<id> \
    --formats tex   # skip PDF
```

### Q. CJK characters render as boxes in the ja/zh PDF.

The ja/zh mirrors require XeLaTeX + Noto CJK fonts. Run
`report/setup_fonts.sh` and verify with
`fc-list | grep -i 'noto.*cjk'`.

## Reproduction sandbox / GPU errors (v0.8.0)

### Q. `"error": "sandbox runtime is unavailable: docker"`, `failure_kind: "sandbox-unavailable"`

`run_reproduce` refuses to silently fall back to host-local execution
when the caller explicitly picks a sandbox kind. It does not raise: the
refusal is recorded as an immutable failed attempt and returned as a
dict carrying `executed: false`, `error` and `failure_kind`
(`sandbox-unavailable`, or `scheduler-failure` for the SLURM path). Do
not go looking for a `RuntimeError` in the caller.

The check is `shutil.which(<runtime>)` at launch — the docker *daemon*
is never probed for an explicit `sandbox_kind=docker`, only for `auto`
resolution — so "runtime unavailable" means the binary is not on `PATH`.
The same fail-closed rule applies to `apptainer` / `singularity`
(binary missing) and `slurm` (sbatch missing OR partition not resolved).

### Q. `"error": "reproduction plan rejected: ..."`

The plan was refused before any attempt existed, so nothing ran. The
three common causes:

1. `sandbox_kind=<container> requires an immutable container image` — no
   `container_image` and no `ARI_PHASE1_DOCKER_IMAGE` /
   `ARI_PHASE1_APPTAINER_IMAGE`.
2. A mutable image reference. Docker must be a full `sha256:<image-id>`
   or `name@sha256:<digest>`; a remote Apptainer ref must carry
   `@sha256:<digest>`; a local SIF must be a regular non-symlink file.
3. `sandbox_kind=... cannot prove network denial` — `network_policy`
   defaults to `deny`, and `local` / `slurm` are not container
   namespaces. Pass `network_policy="inherit"` explicitly, supply the
   administrator attestation via `network_isolation_attested=True`, or
   run in a container.

### Q. A GPU request came back without GPUs

There is intentionally no silent downgrade: ARI submits the typed
request exactly as given. `gpus_per_task` is emitted as
`#SBATCH --gpus-per-task=[<type>:]<n>` and `gpus_per_node` as
`#SBATCH --gres=gpu:[<type>:]<n>` — the two are mutually exclusive
branches, and requesting both is rejected before submission with
"mutually exclusive". If the scheduler rejects the GRES, fix the site's
GRES configuration or pick a partition that advertises the resource
(`sinfo -o '%P %G'`).

### Q. `sbatch: error: --gpus-per-task ... used without either --gpus or -n/--ntasks is not allowed`

This message should not surface through the typed scheduler — it always pairs
`--gpus-per-task` with `--ntasks 1` when the caller didn't supply
`ntasks` or `--gpus`. If you see it, the request is being routed
through a non-bridge path or an older `server.py`.

### Q. `sbatch: error: Invalid GRES specification (with and without type identification)`

This is caused by mixing typed and untyped GPU requests. The common scheduler
emits one typed directive and rejects simultaneous per-task/per-node shapes.
If you see it on a fresh checkout, re-run the affected tests:

```bash
pytest ari-skill-paper-re/tests/test_run_reproduce_slurm.py \
    -k contradictory_or_nonportable
```

### Q. Stage 1 agent had no web search

Pre-v0.8.0, the bridge / `build_reproduce_sh` constructed a fresh
`OpenAIResponsesTurnCompleterConfig(model=...)` without `tools=`, which
silently dropped the vendor `BasicAgentSolver` default of
`[WebSearchToolParam(type="web_search_preview")]`. v0.8.0 explicitly
forwards the tool. If your model doesn't surface web results at all,
check:

- The agent model is an OpenAI Responses model (`gpt-*`, `o[1-5]-*`).
  Anthropic / Gemini routes through LiteLLM, which does NOT inject
  web_search.
- `iterative_agent=True` does not strip the web tool — IterativeAgent
  retains web search (it only strips PythonTool / SearchFile per
  vendor `solver.py:88-95`).

### Q. `reproduce.sh` fails with `src/…: No such file or directory` even though I committed the source

The agent built its repository one directory too deep. ARI's host-side
sandbox presents the workspace as the cwd and the vendor's
`/home/submission` path is rewritten to a relative `submission/`, so an
agent that follows the prompt literally lands its self-contained repo
(with `reproduce.sh` + `src/`) under `<workspace>/submission/`. A
post-rollout step had promoted only `reproduce.sh` up to the workspace
root, orphaning it from its sources; Stage 2 then ran that orphan and the
build could not find `src/…`, zeroing every Code Execution / Result
Analysis leaf.

v0.8.0 resolves this automatically: `reproduce_submission` and
`judge_submission` descend into a nested `submission/` when it holds the
real repository (`reproduce.sh` co-located with `.git` / sources), so
`reproduce.sh`'s relative paths resolve exactly as during the agent's own
`cd submission && bash reproduce.sh` check. No action needed; the orphaned
top-level copy is ignored. If you see the old failure, confirm you are on
v0.8.0.

### Q. Agent's `apply_patch` / `applypatch` edits fail with `command not found`

gpt-5 / codex models reflexively edit files via `apply_patch <<'PATCH' …
PATCH` even though no ARI or vendor prompt instructs it. The vendor Docker
image installs `/bin/apply_patch`, but the host-side `LocalComputer`
builds no image, so pre-v0.8.0 every such call failed and the agent burned
tool-call budget before falling back to `cat`-heredoc.

v0.8.0 mirrors the vendor setup: `LocalComputer` drops a wrapper around the
vendor's own `apply_patch.py` into a workspace `bin/` dir (under both
`apply_patch` and `applypatch`) and prepends it to the shell PATH shared by
every agent command. It degrades gracefully (PATH untouched, heredoc
fallback) if the vendor module cannot be located. No action needed; this is
host-sandbox-only (Apptainer SIFs already carry `/bin/apply_patch`).

## Hugging Face / agent.env credentials (v0.8.0)

### Q. Paper needs `HF_TOKEN` for gated dataset / model

Set the token via `setup.sh`'s interactive prompt OR add to `.env`:

```
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

`bridge.rollout_submission` automatically forwards `HF_TOKEN` from the
calling process into the agent's env (vendor `nano/eval.py:172-179`
well-known-credential pattern). For per-paper credentials (different
`HF_TOKEN` per paper, additional secrets), place them in
`~/.ari/agent.env` (one `KEY=VALUE` per line) — the bridge
auto-discovers this path when `agent_env_path=None`. Override with
`ARI_AGENT_ENV_PATH=/path/to/agent.env`.

### Q. Agent runs Stage 1 but Stage 3 grades all leaves 0

Two distinct causes (v0.8.0 addresses both):

1. **No `reproduce.log` in submission** — Stage 2 was skipped, so the
   vendor SimpleJudge safeguard "`reproduce.sh` failed to modify or
   create any files. All result analysis tasks will be graded as 0"
   would fire in upstream. ARI instead rejects the missing reproduction
   record without publishing a score. Run Stage 2, or explicitly choose a
   code-only study and still create a verified Stage 2 record.
2. **`paper_audit_mode` accidentally on** — paper-audit mode flips
   the judge's prompt to grade the paper itself rather than a
   submission. Mutually exclusive with `code_only`; the bridge
   raises `ValueError` if both are True.

## Retries + executed-submission tarballs

### Q. Reproduce.sh fails fast on missing Python 3.11 / missing venv

There is no salvage wrapper. `salvage_retries` and
`retry_threshold_sec` are **not** parameters of
`bridge.reproduce_submission` — the vendor's
`reproduce_on_computer_with_salvaging` path, which rewrites the
submission's environment and re-runs, has no ARI equivalent, and
`test_reproduce_submission_signature_includes_tarball_not_unsafe_salvage`
asserts those parameters stay absent. Fix the environment inside
`reproduce.sh` itself (or in the container image), then call
`reproduce_submission` again with the same plan: `run_reproduce` appends
an immutable linked attempt rather than mutating your script.

### Q. Where is the executed submission tarball?

Default behaviour writes `submission_executed_<UTC>.tar.gz` after every
reproduce call, next to the *executed* submission — that is, inside the
private attempt tree under `.ari-reproduction`, not next to the
`submission_dir` you passed in. The returned dict's `executed_tarball`
key is the absolute path, with `executed_tarball_digest` and
`executed_tarball_size_bytes` alongside it. Override the destination
with `tarball_dir=...` or disable via `capture_tarball=False`. A capture
failure never fails the run: it is logged and appended to the result's
`warnings` list, so an absent `executed_tarball` key with a `warnings`
entry is the signature to look for.

## See also

- [Quickstart](paperbench_quickstart.md)
- [PaperBench API + bridge contract](../../reference/api_paperbench.md)
- [Environment variables](../../reference/environment_variables.md)
- [Multi-node setup](multi_node_setup.md)
- [Compute-node safety](compute_node_safety.md)
- [Execution profile reference](../../reference/execution_profile.md)
