# `stencil_kernels/` — 3-D 7-point Jacobi stencil task fixtures

Frozen scaffolding for the handoff-study **stencil** task (a genuine
memory-bandwidth-bound *performance kernel*: pure speed axis, numerical-
equivalence correctness, no NP-hardness or accuracy tradeoff). The agent edits
only `candidate_stencil.c`; everything else is frozen and (re)seeded into each
node's work_dir by `ari/evaluator/stencil_harness.py:seed_work_dir`.

The task: apply `nt` sweeps of the 3-D 7-point Jacobi stencil
(`u_new = 0.5*u + (1/12)*Σ6-neighbours`, fixed Dirichlet boundary) to an
`nx×ny×nz` fp64 field, as fast as possible. Score = geomean speedup over the grid
shapes vs the naive single-thread baseline; the deterministic evaluator owns the
data, timing, and baseline. The optimization ladder (parallel → SIMD →
spatial blocking → NUMA first-touch → **temporal/time blocking**) compounds and
its tail is non-obvious, leaving headroom above the one-shot rung.

## Contents

- `README.md` — this file.
- `baseline_stencil.c` — FROZEN naive single-thread ping-pong sweep (the speedup denominator).
- `candidate_stencil.c` — the ONLY file the agent edits (seeded = correct naive sweep).
- `experiment.md` — the task statement shown to the agent (contract, scoring, ladder, self-test).
- `Makefile` — `make candidate` / `make baseline` / `make selftest` / `make check` / `make clean`.
- `selftest.c` — LOCAL developer self-test (correctness + speedup estimate; `make check`).
- `stencil_kernel.h` — the `jacobi()` contract (frozen; signature must not change).
- `stencil_main.c` — FROZEN timing + binary-I/O harness (`prog <problem.bin> <out.bin> <warmup> <reps>`).
