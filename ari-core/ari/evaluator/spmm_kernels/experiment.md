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
- `selftest.c` — a local self-test you can run to check correctness + speedup.
- `Makefile` — `make candidate` builds your kernel; `make selftest` builds the
  self-test.

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
- The kernel is timed on a **large** matrix with a **fixed OpenMP thread budget**
  (the baseline is single-threaded). So the speedup comes from parallelising
  across rows (and good memory locality / vectorisation) — a serial kernel scores
  ~1x. The provided `selftest` uses the same size and thread count, so its
  reported speedup is a good predictor of your score.
- **Valid** requires: compiles, runs, and is correct on every required family.
  Correctness is checked per output element against an fp64 reference with a
  row-length-scaled tolerance (FP reduction reorderings are allowed; dropping
  terms, precomputing the answer, or trivializing the matrix are NOT — a fresh
  `X` is used for the correctness check). Any invalid family → the node is
  invalid (score 0).
- You may NOT edit the timing harness or the baseline; only `candidate_spmm.c`.

## Notes
- You do not need to write your own timing, I/O, or test data — just the
  `spmm()` function. Everything else is provided.
- **Check your work before finishing** with the provided self-test:

  ```
  make selftest && ./selftest
  ```

  It prints `correct=yes/NO`, an estimated `speedup~Nx` vs the naive baseline,
  and `SELFTEST: PASS` / `FAIL`. Iterate until it says **PASS with a speedup > 1**.
  Do NOT write your own `main()`, your own problem generator, or
  `#include "spmm_main.c"` — `selftest.c` already runs and checks your kernel.
- The evaluator (more matrix families, fresh data it generates itself) is the
  authoritative score; the self-test is a fast local proxy that uses the same
  correctness rule, so a local PASS with speedup>1 should score well.
