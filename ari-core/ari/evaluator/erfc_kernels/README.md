# ari.evaluator.erfc_kernels

C fixtures for the handoff-study **erfc accuracy-coverage** task (task B — the
"Goldilocks" task). The agent implements `double myerfc(double x)` (= erfc;
library erf/erfc forbidden) to relative tolerance over a wide domain; the score
is the FRACTION of hidden points within tolerance. Unlike the kernel-speed tasks
(SpMM/GEMM) which have a short ladder + hard ceiling a strong model one-shots,
erfc has a LONG, GRADED, CUMULATIVE ladder — distinct domain regions
(center/mid/tail/deeptail) each need a different numerical regime and the tail
cancels catastrophically, so even gpt-5.2 cannot one-shot it (validated 4-round
trajectory 6%→4%→65%→99.6%). This is where handoff content (inherited partial
implementation + per-region diagnostics) can actually matter. Selected via
`ARI_TASK=erfc`. Tracked despite the repo-wide `*.c` ignore via `.gitignore`
negations.

## Contents

- `README.md` — this file.
- `baseline_erfc.c` — FROZEN poor baseline (tiny-x series only; the low-scoring seed).
- `candidate_erfc.c` — agent-edited `myerfc()` template (seeded identical to baseline); copied per node into the work_dir.
- `erfc_kernel.h` — the `myerfc()` contract (no erf/erfc allowed).
- `erfc_main.c` — FROZEN driver: reads x points, prints myerfc(x); agent must not edit.
- `experiment.md` — the erfc task handed to the agent (goal + contract + region structure + judging).
- `Makefile` — manual build (`make candidate` / `make selftest`).
- `selftest.c` — local accuracy self-test: per-region pass rates vs seeded `ref_points.csv` (distinct seed from the evaluator, so hardcoding can't pass); the diagnostic the agent iterates on.

## See also

- **Measurement core / scorer** → `ari-core/ari/evaluator/erfc_harness.py`.
- **Why this is the Goldilocks task** → `workspace/HARD_TASK_DESIGN.md` (gitignored).
