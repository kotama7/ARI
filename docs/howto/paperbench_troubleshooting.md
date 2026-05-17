# PaperBench troubleshooting

Common failure modes and their fixes. The audit run pipeline is
`rubric_path → build_reproduce_sh → run_reproduce → grade_with_simplejudge`;
issues usually fall into one of those four stages.

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

If empty, regenerate the rubric (the v0.7.2 `skeleton.md` prompt now
instructs the LLM to populate `execution_profile` from the paper's
experimental-setup section).

### Q. Agent did not use `srun` for an MPI paper.

Check the user message that landed in `agent.log` for the
`COMPUTE-NODE EXECUTION CONVENTIONS` block. If missing, the call site
didn't pass `execution_profile`. Verify the wiring with:

```bash
python -c "
from ari_skill_paper_re._replicator_agent import _format_hpc_appendix
print(_format_hpc_appendix(
    expected_artifacts=['results.csv'],
    execution_profile={'kind': 'mpi_gpu', 'metric_columns': ['x']},
    cluster_shape={'SLURM_JOB_NUM_NODES':'4','SLURM_NTASKS':'32','GPU_LIST':'v100'}
))"
```

The output must contain `srun -n $SLURM_NTASKS`.

## SLURM dispatch (`run_reproduce`)

### Q. `sbatch: error: Invalid GRES gpu:v100:1`.

The cluster has no GRES configured. v0.7.2 auto-drops the flag via
`_slurm_has_gres()` — if you still see the error you are on an older
build, or `sinfo` is not on PATH. Workaround: leave `gpu_type` empty
in the wizard's *Execution profile override*.

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
  `module_loads`.
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

### Q. `ors_score` is exactly `0.0`.

The grader could not locate `reproduce.sh` or any expected artefacts.
Check:

```bash
ls repro_sandbox/                  # reproduce.sh present?
jq '.executed, .exit_code' repro_result.json   # ran cleanly?
jq '.missing' repro_result.json    # missing expected_artifacts?
```

A common cause: the agent wrote `submission/reproduce.sh` instead of
the workspace root. v0.7+ auto-promotes that path; if you are on an
older build, copy it up manually.

### Q. Negative control did not pass (boilerplate scored > 5%).

The rubric's leaves are too easy to satisfy — they pattern-match
generic boilerplate. Re-audit the rubric with stricter
`task_category="Code Execution"` claims that demand specific log
output or artefact contents.

## GUI / Wizard

### Q. The wizard shows "No papers registered yet" forever.

Check `~/.ari/paper_registry/manifest.jsonl` exists and is non-empty.
If you set `ARI_PAPER_REGISTRY_DIR`, the path moves accordingly.

### Q. Launch button stays disabled.

Step 1 (Papers) requires at least one paper selected. The button stays
disabled until `selected_count >= 1`.

### Q. Cost estimate is `$0`.

You haven't set a `time_limit_sec` in Step 3 (Reproduce). The
default is 12 h; a 0 means the estimate's reproduction wall-time term
collapses.

## Report generation

### Q. `latexmk: command not found`.

XeLaTeX is required for the audit report PDF target. Install
`texlive-xetex` (Debian/Ubuntu) or `mactex` (macOS), or skip PDF and
emit `.tex` sources only:

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

## See also

- [Quickstart](paperbench_quickstart.md)
- [Multi-node setup](multi_node_setup.md)
- [Compute-node safety](compute_node_safety.md)
- [Execution profile reference](../reference/execution_profile.md)
