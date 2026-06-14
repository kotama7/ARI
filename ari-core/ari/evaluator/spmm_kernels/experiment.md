# Experiment: optimize a CSR sparse-dense matrix multiply (SpMM)

Goal: make `Y = A · X` as fast as possible, where `A` is a sparse matrix in CSR
format (n×m) and `X` is a dense matrix (m×k), producing a dense `Y` (n×k,
row-major). Correctness and speed are judged by a fixed deterministic evaluator —
there is no LLM judge.

## What you produce

Your working directory is **already seeded** with the scaffolding — list it and
you will find:

- `candidate_spmm.c` — the file you edit (starts as a correct naive triple loop).
- `spmm_kernel.h` — the `spmm()` contract (do not change the signature).
- `spmm_main.c` — the FROZEN timing/I-O harness (do not edit).
- `baseline_spmm.c` — the FROZEN naive baseline (the speedup denominator).
- `Makefile` — `make candidate` builds your kernel against the frozen harness.

**Edit `candidate_spmm.c`** so that it defines exactly this function (signature
from `spmm_kernel.h`):

```c
void spmm(int n, int m, int k,
          const int *indptr, const int *indices, const double *values,
          const double *X, double *Y);
```

`indptr/indices/values` are the CSR arrays of `A`; `X` is row-major `m×k`; write
the row-major `n×k` result into `Y`. Improve the seeded naive triple loop
(OpenMP scheduling, row-length bucketing, blocking, SIMD, prefetch, locality,
load balance, …). Do NOT change the signature.

## How you are judged (fixed, deterministic — do not try to game it)

- The evaluator owns compilation, the matrices `A`/`X`, the timing loop, and the
  baseline. It compiles your `candidate_spmm.c` against a FROZEN harness
  (`spmm_main.c`) with the SAME compiler and flags as a frozen naive baseline,
  runs both on several seeded matrix families, and reports
  **best valid geomean speedup** = geomean over families of (baseline_time /
  your_time).
- **Valid** requires: compiles, runs, and is correct on every required family.
  Correctness is checked per output element against an fp64 reference with a
  row-length-scaled tolerance (FP reduction reorderings are allowed; dropping
  terms, precomputing the answer, or trivializing the matrix are NOT — a fresh
  `X` is used for the correctness check). Any invalid family → the node is
  invalid (score 0).
- You may NOT edit the timing harness or the baseline; only `candidate_spmm.c`.

## Notes
- You do not need to write your own timing or I/O — just the `spmm()` function.
- **Verify it builds before finishing**: run `make candidate` in your working
  directory (it compiles `candidate_spmm.c` against the frozen harness with
  `-O3 -fopenmp`). A clean build means the evaluator can measure it. Do NOT add
  your own `main()` or `#include "spmm_main.c"` — the harness already provides
  `main()`; just keep the `spmm()` function.
- The evaluator generates the matrices and the problem input, so a full local
  *run* is not needed (and not possible without its data) — the evaluator's
  measurement is authoritative.
