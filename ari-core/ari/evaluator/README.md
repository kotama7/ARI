# ari.evaluator

LLM-driven metric extraction and dynamic axis generation — the BFTS judge
that scores each completed node into the multi-axis composite the
orchestrator consumes.

## Contents

- `README.md` — this file.
- `__init__.py` — public symbols + axis design.
- `deterministic_evaluator.py` — `DeterministicEvaluator`: non-LLM judge owning the kernel measurement; writes `metrics._scientific_score` to drive BFTS selection (handoff study). Selected via `ARI_EVALUATOR=deterministic`; task via `ARI_TASK` (spmm default | gemm | erfc | meshpart | stencil), which also picks the scoring (spmm linear-speedup / gemm log-speedup / stencil log-speedup / erfc pass-fraction / meshpart cut+balance objective). Performance kernels (gemm/spmm/stencil) score a speedup; erfc/meshpart store a bounded [0,1] score in the same field for analyzer reuse (it is NOT a speedup — the analyzer reports each on its native axis).
- `dynamic_axes.py` — venue/run-specific evaluation-axis derivation.
- `erfc_harness.py` — erfc accuracy-coverage measurement core (task B, the "Goldilocks" task): scipy reference, region-stratified hidden points, score = fraction within rel-tol 1e-9 over a wide domain (`measure_node` returns a score-shaped dict). Long cumulative ladder (center→mid→tail→deeptail) no model one-shots; selftest uses a distinct seed (anti-gaming). Login-testable.
- `gemm_harness.py` — dense GEMM measurement core (task A): fp64 reference oracle, contraction-length correctness bound, fixed shapes, geomean aggregation (`measure_node`). Compute-bound counterpart to SpMM with a multi-rung optimization gradient; pure parts login-tested, compile/run runner compute-node only.
- `handoff_stats.py` — run-level analysis statistics for the handoff study (Stage 4 core): geomean, run-cluster bootstrap CI, TOST equivalence (RQ1 parity), Holm correction, per-arm summary. Pure; consumed by `scripts/analyze_handoff_ablation.py`.
- `llm_evaluator.py` — `LLMEvaluator`: extraction + multi-axis composite scoring.
- `meshpart_harness.py` — balanced k-way graph-partitioning measurement core (task C, the combinatorial "Goldilocks" task): procedural custom mesh (2-D k-NN graph + long edges → CSR, no memorized answer), recursive-spectral reference cut, score = `bal · q ∈ [0,1]` combining balance and edge-cut quality (`measure_node` returns a score-shaped dict). ANY partition is valid/scoreable (no compile-or-die None) and the optimum is NP-hard, so mid models make valid-but-suboptimal partitions children can refine; selftest mesh uses a distinct seed (anti-gaming). Pure parts login-tested; compile/run runner login-capable too.
- `spmm_harness.py` — SpMM measurement core (handoff study B2b): fp64 reference oracle, per-element correctness bound (eps model), seeded matrix families, geomean aggregation (`measure_node`). Pure parts login-tested; compile/run/timing runner is compute-node only.
- `stencil_harness.py` — 3-D 7-point Jacobi stencil measurement core (task D, a genuine memory-bandwidth-bound performance kernel): fp64 nt-sweep reference oracle, nt-scaled per-element correctness bound, fixed grid shapes (one cube + two anisotropic boxes), geomean-speedup aggregation (`measure_node`). Plain parallelism saturates the bandwidth roofline (the one-shot rung); SIMD + spatial blocking + NUMA first-touch + temporal/time tiling climb above it, leaving headroom above the one-shot rung. Pure parts login-tested; compile/run runner compute-node only.
- `erfc_kernels/` — C fixtures for the handoff-study **erfc accuracy-coverage** task (task B — the
  - `README.md` — erfc_kernels index.
  - `baseline_erfc.c` — FROZEN poor baseline (tiny-x series only; the low-scoring seed).
  - `candidate_erfc.c` — agent-edited `myerfc()` template (seeded identical to baseline); copied per node into the work_dir.
  - `erfc_kernel.h` — the `myerfc()` contract (no erf/erfc allowed).
  - `erfc_main.c` — FROZEN driver: reads x points, prints myerfc(x); agent must not edit.
  - `experiment.md` — the erfc task handed to the agent (goal + contract + region structure + judging).
  - `Makefile` — manual build (`make candidate` / `make selftest`).
  - `selftest.c` — local accuracy self-test: per-region pass rates vs seeded `ref_points.csv` (distinct seed from the evaluator, so hardcoding can't pass); the diagnostic the agent iterates on.
- `gemm_kernels/` — C kernel fixtures for the handoff-study **dense GEMM** task (task A). GEMM is the
  - `README.md` — gemm_kernels index.
  - `baseline_gemm.c` — FROZEN 1x reference GEMM (naive ijl, single-thread); the speedup denominator.
  - `candidate_gemm.c` — agent-edited `gemm()` template (seeded identical to baseline); copied per node into the work_dir.
  - `experiment.md` — the GEMM optimization task handed to the agent (goal + `gemm()` contract + judging rules; BLAS forbidden).
  - `gemm_kernel.h` — the `gemm()` contract the candidate must keep.
  - `gemm_main.c` — FROZEN timing + binary-I/O harness (warmup/reps/median); agent must not edit.
  - `Makefile` — manual build (`make candidate` / `make selftest`); mirrors the Python runner's identical flags.
  - `selftest.c` — local developer self-test (`make selftest`): correctness (evaluator eps bound) + estimated speedup vs the naive baseline; seeded for agent iteration, not used for scoring.
- `meshpart_kernels/` — C fixtures for the handoff-study **balanced k-way graph partitioning** task (task C — the combinatorial "Goldilocks" task: any partition is valid/scoreable, optimum NP-hard).
  - `README.md` — meshpart_kernels index.
  - `baseline_meshpart.c` — FROZEN poor baseline (round-robin `i % k`: balanced but
  - `candidate_meshpart.c` — the file the agent edits (starts as the baseline).
  - `experiment.md` — the task statement handed to the BFTS agent.
  - `Makefile` — `make candidate` / `make baseline` / `make selftest`.
  - `meshpart_kernel.h` — the `partition()` contract (CSR in, labels out). Frozen.
  - `meshpart_main.c` — FROZEN driver: reads `mesh.bin` (CSR), prints the partition.
  - `selftest.c` — local self-test: reports edge-cut and imbalance on the seeded
- `spmm_kernels/` — C kernel fixtures for the handoff-study SpMM measurement (B2b). The frozen
  - `README.md` — spmm_kernels index.
  - `baseline_spmm.c` — FROZEN 1x reference CSR SpMM (naive, single-thread); the speedup denominator.
  - `candidate_spmm.c` — agent-edited `spmm()` template (seeded identical to baseline); copied per node into the work_dir.
  - `experiment.md` — the SpMM optimization task handed to the agent (goal + `spmm()` contract + the deterministic-evaluator judging rules); the experiment file for the pilot/MVP runs.
  - `Makefile` — manual build (the Python runner compiles directly with identical flags for baseline/candidate).
  - `Plan.md` — B2b compile/run/timing runner plan (deps + deletion requirement).
  - `selftest.c` — local developer self-test (`make selftest`): runs the candidate on a seeded problem, checks correctness with the evaluator's eps bound, and prints an estimated speedup vs the naive baseline; NOT used for scoring (seeded so the agent can iterate locally).
  - `spmm_kernel.h` — the `spmm()` contract the candidate must keep.
  - `spmm_main.c` — FROZEN timing + binary-I/O harness (warmup/reps/median); agent must not edit.
- `stencil_kernels/` — C kernel fixtures for the handoff-study **3-D 7-point Jacobi stencil** task (task D — a genuine memory-bandwidth-bound performance kernel; tests whether the central finding replicates on a true perf kernel).
  - `README.md` — stencil_kernels index.
  - `baseline_stencil.c` — FROZEN naive single-thread ping-pong sweep (the speedup denominator).
  - `candidate_stencil.c` — the ONLY file the agent edits (seeded = correct naive sweep).
  - `experiment.md` — the task statement shown to the agent (contract, scoring, ladder, self-test).
  - `Makefile` — `make candidate` / `make baseline` / `make selftest` / `make check` / `make clean`.
  - `selftest.c` — LOCAL developer self-test (correctness + speedup estimate; `make check`).
  - `stencil_kernel.h` — the `jacobi()` contract (frozen; signature must not change).
  - `stencil_main.c` — FROZEN timing + binary-I/O harness (`prog <problem.bin> <out.bin> <warmup> <reps>`).

## See also

- **Public symbols (`LLMEvaluator`, `MetricSpec`) & axis design** → the `__init__.py` module docstring (authoritative).
- **Plan / Venue contract** → `docs/concepts/architecture.md`.
- **History** → `git log -- ari-core/ari/evaluator/`.
