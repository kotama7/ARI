# Experiment: optimize a dense matrix multiply (GEMM)

Goal: make `C = A · B` as fast as possible, where `A` is `n×p`, `B` is `p×m`, and
`C` is `n×m`, all dense, row-major, fp64. Correctness and speed are judged by a
fixed non-LLM evaluator.

## What you produce

Your working directory is **already seeded** with the scaffolding — list it:

- `candidate_gemm.c` — the file you edit (starts as a correct naive triple loop).
- `gemm_kernel.h` — the `gemm()` contract (do not change the signature).
- `gemm_main.c` — the FROZEN timing/I-O harness (do not edit).
- `baseline_gemm.c` — a FROZEN naive kernel, kept only as an absolute anchor.
  It is **not** what you are scored against; see "How you are judged".
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

## How you are judged

- **Your score is `t_reference / t_candidate`.** The evaluator owns compilation,
  the matrices `A`/`B`, and the timing. It runs your kernel against a FROZEN
  REFERENCE IMPLEMENTATION on square, tall, and wide shapes. Each repetition is a
  matched candidate/reference pair on a fresh problem; the shape score is the
  median of the per-pair ratios, and the overall score is the geometric mean over
  all shapes. **A score of 1.0 means you matched the reference.**
- **The reference is a competent kernel, not a naive one.** It is register-blocked
  and vectorised, written in the same plain C + OpenMP you are allowed to use —
  no intrinsics, no assembly, no library. Nothing about it is out of your reach.
  It is not shown to you. On this machine it reaches roughly:

  | shape (n×p×m) | reference |
  |---|---|
  | 1000×1000×1000 | ~384 GF/s |
  | 2000×500×500 | ~388 GF/s |
  | 1500×600×1500 | ~369 GF/s |

  The reference is a competent kernel, **not the fastest possible one**, but it
  is strong on all three of these shapes: measured against the best kernels
  previous agents produced, it wins by 1.16–1.29×. Scores above 1.0 are possible
  and are not capped, but do not assume any shape is an easy one.

  Your self-test prints your own GF/s per shape, so `your GF/s ÷ the number
  above` is a close estimate of your score on that shape. Scoring **above** 1.0
  is possible and is not capped.
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
  YOUR kernel only. The reference is built with its own fixed flags, including
  vectorisation for this target — flags you are equally free to use, and on this
  machine the right `-march` is worth more than a factor of two on its own.
  Both `make candidate` and the scorer read this file, so what you build locally
  is what you are scored on.
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
- The kernel is timed with a **fixed OpenMP thread budget**. Gains come from loop
  order, cache use, parallelism, vectorisation and blocking — these multiply. For
  scale: the seeded naive triple loop is roughly 1/900 of the reference, so the
  first correct parallel + cache-friendly rewrite moves you a long way, and the
  remaining distance to 1.0 is where blocking and vectorisation decide it.
- **Valid** requires: compiles, runs, and is correct on every shape. Correctness
  is per output element vs an fp64 reference with a contraction-length-scaled
  tolerance (FP reduction reorderings are allowed; dropping terms, precomputing
  the answer, or calling BLAS are NOT). Any invalid shape → the node is invalid
  (score 0).
- You may NOT edit the timing harness or the reference; only `candidate_gemm.c`.

## Rules the build enforces

These are checked mechanically when your kernel is compiled. Breaking one makes the
candidate invalid, which scores 0 — so they are worth reading once.

- **Export only `gemm()`.** Everything else in `candidate_gemm.c` must be `static`.
  Your kernel object is linked into the same executable as the frozen measurement
  driver, so a second exported symbol can silently replace one of the driver's.
- **All your work must happen inside `gemm()`.** A constructor, a destructor or an
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
- You do not need to write your own timing, I/O, or test data — just `gemm()`.
- **Check your work before finishing** with the provided self-test:

  ```
  make selftest && ./selftest
  ```

  It prints `correct=yes/NO`, your **GF/s and milliseconds per shape**, and
  `SELFTEST: PASS` / `FAIL`. Divide your GF/s by the reference GF/s in the table
  above to estimate your score. Iterate until it says **PASS with a high
  GF/s**. **Never finish while it says `SELFTEST: FAIL`** — `correct=NO` means
  your kernel is wrong and the evaluator scores it 0; a correct slower kernel
  beats a fast wrong one. Do NOT write your own `main()` or `#include "gemm_main.c"`.
- The evaluator (several shapes, fresh data) is authoritative; the self-test is a
  fast local proxy using the same correctness rule.
