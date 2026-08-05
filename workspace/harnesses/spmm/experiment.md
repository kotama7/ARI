# Experiment: optimize a CSR sparse-dense matrix multiply (SpMM)

Goal: make `Y = A · X` as fast as possible, where `A` is a sparse matrix in CSR
format (n×m) and `X` is a dense matrix (m×k), producing a dense `Y` (n×k,
row-major). Correctness and speed are judged by a fixed non-LLM evaluator.

## What you produce

Your working directory is **already seeded** with the scaffolding — list it and
you will find:

- `candidate_spmm.c` — the file you edit (starts as a correct naive triple loop).
- `spmm_kernel.h` — the `spmm()` contract (do not change the signature).
- `spmm_main.c` — the FROZEN timing/I-O harness (do not edit).
- `baseline_spmm.c` — a FROZEN naive kernel, kept only as an absolute anchor.
  It is **not** what you are scored against; see "How you are judged".
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

## How you are judged

- The evaluator owns compilation, the matrices `A`/`X`, the timing loop, and the
  baseline. It compiles your `candidate_spmm.c` against a FROZEN harness
  (`spmm_main.c`) with the same compiler and default flags as a frozen naive
  baseline. It runs both on six seeded sparse-structure families. Each repetition
  is a matched candidate/reference pair, and the reported family score is the
  median of the accepted per-pair ratios. The overall score is the geometric mean
  over all families. **Your score is `t_reference / t_candidate`, so 1.0 means you
  matched the reference.**
- **The reference is a competent kernel, not a naive one.** Plain C and OpenMP —
  no intrinsics, no assembly, no library — so nothing about it is out of your
  reach. It is not shown to you. For scale, measured on this machine: the seeded
  naive kernel scores about 0.007, a straightforward parallel-over-rows kernel
  about 0.30, the same kernel with vector flags about 0.66, and the best kernel
  produced in a previous campaign of this task reached 0.77. Scoring above 1.0 is
  possible and is not capped.
- **You may select the compiler.** Put one name in `candidate_cc.txt`: `gcc`,
  `clang`, or `fcc` (the vendor compiler for this architecture). `#` comments and
  blank lines are ignored; no file, or an empty one, means the default compiler.
  Your whole process — including the frozen timing driver — is then built with the
  compiler you named, so the OpenMP runtime stays consistent within your binary.
  The reference is always built with the default compiler, so this moves your side
  of the ratio only.
  The compilers do not agree on what to do with the same source, the disagreement
  runs in both directions, and it is not the same size for every kernel — this is a
  real axis, not a formality. Your `candidate_flags.txt` is passed to whichever
  compiler you select, and the compilers do not share all flag spellings, so a flag
  set tuned for one may be ignored or rejected by another.
  A name outside the list, or a compiler not installed on this node, falls back to
  the default and is recorded as such; it does not fail your node. Which compiler
  actually ran is recorded with your score.
- **You may tune the compile flags.** Put optimization flags in `candidate_flags.txt`
  (whitespace-separated, `#` comments allowed). They are appended to the defaults for
  YOUR kernel only; the reference is built with its own fixed flags, which you are
  equally free to use. Measured here, adding vector flags to a plain parallel
  kernel moves it from 0.296 to 0.660 — worth more than a factor of two on its
  own. Both `make candidate` and the scorer read this file, so what you build
  locally is what you are scored on.
  Only optimization/tuning flags are accepted (`-O*`, `-f*`, `-m*`, `--param=*`,
  and the vendor namespaces `-K*` and `-N*` — a compiler's own spellings are
  available to you when you select it, including the ones that change its
  compilation mode);
  anything that changes the build itself is dropped (`-I`/`-D`/`-include`, `-l`/`-L`/`-Wl`,
  `-o`/`-c`/`-S`/`-E`, `-fplugin`/`-specs`, `-fprofile-*`, and the vendor
  equivalents of those behaviours — anything that links a numerical library
  or switches OpenMP off). Numerics are NOT restricted:
  `-ffast-math` is allowed, but correctness is still decided by the reference oracle's
  error bound, so a transform that leaves the bound fails like any wrong answer.
- The kernel is timed on a **large** matrix with a **fixed 48-thread OpenMP budget**.
  Gains come from parallelising across rows, memory locality, and vectorisation.
  Note that two of the scored matrix families have heavy-tailed row lengths — a
  few rows hold a large share of the nonzeros — so how work is distributed across
  threads matters, not just that it is distributed.
- The provided `selftest` reports a speedup against the NAIVE kernel, which is
  **not** the scoring denominator. The reference is about 148x the naive kernel
  here (geometric mean; it ranges 132x to 199x across the scored families), so
  your score is roughly `selftest speedup / 148`. The printed number is
  still the right thing to watch while iterating, because it moves with your
  kernel.
- **Valid** requires: compiles, runs, and is correct on every required family.
  Correctness is checked per output element against an fp64 reference with a
  row-length-scaled tolerance (FP reduction reorderings are allowed; dropping
  terms, precomputing the answer, or trivializing the matrix are NOT — a fresh
  `X` is used for the correctness check). Any invalid family → the node is
  invalid (score 0).
- You may NOT edit the timing harness or the reference; only `candidate_spmm.c`.

## Rules the build enforces

These are checked mechanically when your kernel is compiled. Breaking one makes the
candidate invalid, which scores 0 — so they are worth reading once.

- **Export only `spmm()`.** Everything else in `candidate_spmm.c` must be `static`.
  Your kernel object is linked into the same executable as the frozen measurement
  driver, so a second exported symbol can silently replace one of the driver's.
- **All your work must happen inside `spmm()`.** A constructor, a destructor or an
  ifunc resolver runs outside the measured call — before the timer starts or after the
  result has been written — so the object is rejected if it carries `.init_array`,
  `.preinit_array`, `.ctors`, `.fini_array`, `.dtors` or an IFUNC symbol.
- **No file I/O, exit hooks or subprocesses.** The kernel may not reference `fopen`,
  `open`, `atexit`, `system`, `fork`, `exec*`, `dlopen` and similar. A compute kernel
  needs none of them; every candidate in the previous campaign referenced only the
  OpenMP runtime, `malloc`/`free`/`posix_memalign`/`aligned_alloc`/`memcpy`/`memset`
  and `stderr`/`fprintf`/`abort`.
- **Flags additionally denied:** `-fno-openmp` (the driver creates the thread team
  outside the timer, so switching OpenMP off for your object alone would distort the
  measurement), and `-flto`/`-fwhole-program` (they defeat the object-level checks
  above). `-fopenmp-simd` is fine.
- **The build is split, and your local build matches it.** The frozen driver is
  compiled with the default flags only; your flags apply to your kernel object and to
  the link. `make candidate` does exactly the same three steps.
- **`candidate_flags.txt` is created for you** and is parsed identically by `make` and
  by the scorer: a `#` starts a comment that runs to the end of that LINE, and a
  literal backslash-n is treated as a newline.

## Notes
- You do not need to write your own timing, I/O, or test data — just the
  `spmm()` function. Everything else is provided.
- **Check your work before finishing** with the provided self-test:

  ```
  make selftest && ./selftest
  ```

  It tests two sparsity structures (a uniform and a skewed/heavy-tailed matrix),
  printing per-structure `correct=yes/NO` and `speedup~Nx`, then an overall
  `SELFTEST: PASS` / `FAIL`. Iterate until it says **PASS with a speedup > 1**.
  **Never finish while it says `SELFTEST: FAIL` — `correct=NO` means your kernel
  is wrong (e.g. you forgot to zero `Y` before accumulating, you have a data
  race, or you mishandle very dense rows) and the evaluator will score it 0.**
  A correct ~1x kernel beats a fast wrong one. If you cannot fix correctness,
  revert to the last PASS version. Do NOT write your own `main()`, your own
  problem generator, or `#include "spmm_main.c"` — `selftest.c` already runs and
  checks your kernel.
- The evaluator (6 matrix families, fresh data it generates itself) is the
  authoritative score; the self-test uses the same correctness rule but only two
  structures, so a local PASS with speedup>1 is a strong — not complete —
  predictor. Write a kernel that is correct for ANY CSR input, not one tuned to
  these two cases.
