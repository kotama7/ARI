# ari.evaluator.spmm_kernels

C kernel fixtures for the handoff-study SpMM measurement (B2b). The frozen
timing/I-O harness (`spmm_main.c`) + frozen 1x `baseline_spmm.c` define an
un-gameable speedup; the agent edits only `candidate_spmm.c` (the `spmm()`
function). Compiled by `ari/evaluator/spmm_harness.py` with identical flags for
baseline and candidate. Tracked despite the repo-wide `*.c` ignore via
`.gitignore` negations.

## Contents

- `README.md` — this file.
- `baseline_spmm.c` — FROZEN 1x reference CSR SpMM (naive, single-thread); the speedup denominator.
- `candidate_spmm.c` — agent-edited `spmm()` template (seeded identical to baseline); copied per node into the work_dir.
- `experiment.md` — the SpMM optimization task handed to the agent (goal + `spmm()` contract + the deterministic-evaluator judging rules); the experiment file for the pilot/MVP runs.
- `Makefile` — manual build (the Python runner compiles directly with identical flags for baseline/candidate).
- `Plan.md` — B2b compile/run/timing runner plan (deps + deletion requirement).
- `selftest.c` — local developer self-test (`make selftest`): runs the candidate on a seeded problem, checks correctness with the evaluator's eps bound, and prints an estimated speedup vs the naive baseline; NOT used for scoring (seeded so the agent can iterate locally).
- `spmm_kernel.h` — the `spmm()` contract the candidate must keep.
- `spmm_main.c` — FROZEN timing + binary-I/O harness (warmup/reps/median); agent must not edit.

## See also

- **Measurement core / runner** → `ari-core/ari/evaluator/spmm_harness.py`.
- **Plan / deletion requirement** → `Plan.md`.
- **Kernel contract** → `spmm_kernel.h`.
