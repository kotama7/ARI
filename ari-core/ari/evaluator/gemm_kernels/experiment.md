# Experiment: optimize a dense matrix multiply (GEMM)

Goal: make `C = A · B` as fast as possible, where `A` is `n×p`, `B` is `p×m`, and
`C` is `n×m`, all dense, row-major, fp64. Correctness and speed are judged by a
fixed deterministic evaluator — there is no LLM judge.

## What you produce

Your working directory is **already seeded** with the scaffolding — list it:

- `candidate_gemm.c` — the file you edit (starts as a correct naive triple loop).
- `gemm_kernel.h` — the `gemm()` contract (do not change the signature).
- `gemm_main.c` — the FROZEN timing/I-O harness (do not edit).
- `baseline_gemm.c` — the FROZEN naive baseline (the speedup denominator).
- `selftest.c` — a local self-test you can run.
- `Makefile` — `make candidate` builds your kernel; `make selftest` the self-test.

**Edit `candidate_gemm.c`** so it defines exactly this function (from `gemm_kernel.h`):

```c
void gemm(int n, int m, int p,
          const double *A, const double *B, double *C);
```

`C[i*m + j] = sum_l A[i*p + l] * B[l*m + j]` (row-major). Improve the seeded
naive triple loop. Two big wins **compound**:
1. a cache-friendly loop order (e.g. `ikj`: stream a row of `B`, accumulate into `C[i,:]`),
2. OpenMP parallelism across rows,
then blocking / SIMD-friendly layout for more. Do NOT change the signature, and
**do NOT call a BLAS/LAPACK library** — the build links none; write it yourself.

## How you are judged (fixed, deterministic — do not try to game it)

- The evaluator owns compilation, the matrices `A`/`B`, the timing loop, and the
  baseline. It compiles your `candidate_gemm.c` against a FROZEN harness with the
  SAME compiler and flags as a frozen naive baseline, runs both on several
  problem shapes (square, tall, fat), and reports the **geomean speedup** =
  geomean over shapes of (baseline_time / your_time).
- The kernel is timed with a **fixed OpenMP thread budget**; the baseline is the
  single-thread naive `ijl` triple loop. Speedup comes from loop order, cache
  use, parallelism and blocking — these multiply, so the best kernels are
  hundreds of times faster than the naive baseline.
- **Valid** requires: compiles, runs, and is correct on every shape. Correctness
  is per output element vs an fp64 reference with a contraction-length-scaled
  tolerance (FP reduction reorderings are allowed; dropping terms, precomputing
  the answer, or calling BLAS are NOT). Any invalid shape → the node is invalid
  (score 0).
- You may NOT edit the timing harness or the baseline; only `candidate_gemm.c`.

## Notes
- You do not need to write your own timing, I/O, or test data — just `gemm()`.
- **Check your work before finishing** with the provided self-test:

  ```
  make selftest && ./selftest
  ```

  It prints `correct=yes/NO`, an estimated `speedup~Nx` vs the naive baseline,
  and `SELFTEST: PASS` / `FAIL`. Iterate until it says **PASS with a high
  speedup**. **Never finish while it says `SELFTEST: FAIL`** — `correct=NO` means
  your kernel is wrong and the evaluator scores it 0; a correct slower kernel
  beats a fast wrong one. Do NOT write your own `main()` or `#include "gemm_main.c"`.
- The evaluator (several shapes, fresh data) is authoritative; the self-test is a
  fast local proxy using the same correctness rule.
