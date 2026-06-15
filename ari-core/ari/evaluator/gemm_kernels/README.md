# ari.evaluator.gemm_kernels

C kernel fixtures for the handoff-study **dense GEMM** task (task A). GEMM is the
compute-bound counterpart to SpMM: two independent insights (cache loop-order,
parallelism) compound multiplicatively (~hundreds× over the naive baseline), so
the task has a genuine multi-rung optimization-QUALITY gradient (unlike SpMM's
parallelize-or-not cliff). The frozen timing/I-O harness (`gemm_main.c`) + frozen
naive `baseline_gemm.c` define an un-gameable speedup; the agent edits only
`candidate_gemm.c` (the `gemm()` function) and may NOT link BLAS. Selected via
`ARI_TASK=gemm`. Tracked despite the repo-wide `*.c` ignore via `.gitignore`
negations.

## Contents

- `README.md` — this file.
- `baseline_gemm.c` — FROZEN 1x reference GEMM (naive ijl, single-thread); the speedup denominator.
- `candidate_gemm.c` — agent-edited `gemm()` template (seeded identical to baseline); copied per node into the work_dir.
- `experiment.md` — the GEMM optimization task handed to the agent (goal + `gemm()` contract + judging rules; BLAS forbidden).
- `gemm_kernel.h` — the `gemm()` contract the candidate must keep.
- `gemm_main.c` — FROZEN timing + binary-I/O harness (warmup/reps/median); agent must not edit.
- `Makefile` — manual build (`make candidate` / `make selftest`); mirrors the Python runner's identical flags.
- `selftest.c` — local developer self-test (`make selftest`): correctness (evaluator eps bound) + estimated speedup vs the naive baseline; seeded for agent iteration, not used for scoring.

## See also

- **Measurement core / runner** → `ari-core/ari/evaluator/gemm_harness.py`.
- **Design / why GEMM** → `workspace/HARD_TASK_DESIGN.md` (gitignored).
- **Kernel contract** → `gemm_kernel.h`.
