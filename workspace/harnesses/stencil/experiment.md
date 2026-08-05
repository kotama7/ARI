# Experiment: optimize a 3-D 7-point Jacobi stencil

Goal: make `nt` sweeps of a 3-D 7-point Jacobi stencil over an `nx×ny×nz` fp64
field as fast as possible. Correctness and speed are judged by a fixed non-LLM
evaluator.

## What you produce

Your working directory is **already seeded** with the scaffolding — list it:

- `candidate_stencil.c` — the file you edit (starts as a correct naive single-thread sweep).
- `stencil_kernel.h` — the `jacobi()` contract (do not change the signature).
- `stencil_main.c` — the FROZEN timing/I-O harness (do not edit).
- `baseline_stencil.c` — a FROZEN naive single-thread kernel, kept only as an
  absolute anchor. It is **not** what you are scored against.
- `selftest.c` — a local self-test you can run (`make check`).
- `Makefile` — `make candidate` builds your kernel; `make check` builds+runs the self-test.

**Edit `candidate_stencil.c`** so it defines exactly this function (from `stencil_kernel.h`):

```c
void jacobi(int nx, int ny, int nz, int nt,
            const double *u0, double *u);
```

One sweep updates every INTERIOR point (`1<=i<nx-1`, `1<=j<ny-1`, `1<=k<nz-1`),
where element `(i,j,k)` is at index `((long)i*ny + j)*nz + k`:

```
u_new[i,j,k] = c0*u[i,j,k]
             + cw*( u[i-1,j,k] + u[i+1,j,k]
                  + u[i,j-1,k] + u[i,j+1,k]
                  + u[i,j,k-1] + u[i,j,k+1] )
```

with `c0 = 0.5` and `cw = 1.0/12.0` (the seven weights sum to 1). **Boundary
planes are FIXED (Dirichlet): every face point keeps its `u0` value for all
sweeps.** Apply `nt` sweeps to `u0` and write the final field into `u`. Your
kernel MAY allocate its own scratch (e.g. a ping-pong buffer). Do NOT change the
signature, and do NOT call an external stencil/HPC library — write it yourself.

This kernel is **memory-bandwidth bound**: each point reads 7 values and writes
1, with almost no arithmetic reuse, so plain parallelism saturates the memory
roofline quickly. The wins **compound**:
1. OpenMP parallelism across the outer (`i`) loop,
2. SIMD along the contiguous `k` dimension,
3. spatial cache blocking (tile `i`/`j`/`k` so reused planes stay hot in cache),
4. NUMA first-touch initialisation of the scratch buffers,
5. **temporal / time blocking** (advance several sweeps over a cache-resident
   tile before moving on) — this reduces memory traffic and is what breaks past
   the bandwidth roofline.

The first rungs are easy; the last (correct time tiling at the halos) is the long
road.

## How you are judged

- **Your score is `t_reference / t_candidate`.** The evaluator owns compilation,
  the field data `u0`, and the timing. It runs your kernel against a FROZEN
  REFERENCE IMPLEMENTATION on one cubic and two anisotropic grid shapes. Each
  repetition is a matched candidate/reference pair on a fresh field; the shape
  score is the median of the per-pair ratios and the overall score is the
  geometric mean. **A score of 1.0 means you matched the reference.**
- **The reference is a competent kernel, not a naive one.** It is plain C and
  OpenMP — no intrinsics, no assembly, nothing you are forbidden to write — and
  it uses the kernel's own scratch allocation, which this task explicitly allows.
  It is not shown to you. For scale, measured on this machine: the seeded naive
  kernel scores about 0.04, a straightforward parallel sweep about 0.29, and the
  best kernel produced in a previous campaign of this task reached 0.90.
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
  equally free to use. Both `make candidate` and the scorer read this file, so what
  you build locally is what you are scored on. Be aware that on THIS problem the
  vector flags are worth almost nothing — measured, a plain parallel sweep scores
  0.294 without them and 0.288 with them. This kernel is bandwidth-bound, and the
  large factors are elsewhere.
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
- The kernel is timed with a **fixed OpenMP thread budget**. Gains come from
  parallelism, memory placement, spatial blocking and temporal tiling. One
  measured data point worth having: on this machine, taking an already-parallel
  kernel and changing ONLY how its scratch buffers are first written — so that
  each thread writes the pages it will later read, instead of one thread writing
  all of them — moves the score from 0.296 to 1.003, a factor of 3.4, with no
  change to the arithmetic. The field is 134 MB per buffer; where the pages live
  dominates everything else.
- **Valid** requires: compiles, runs, and is correct on every shape. Correctness
  is per-element vs an fp64 reference with an **nt-scaled** tolerance (FP
  reassociation of the 6-neighbour sum is allowed; changing the coefficients,
  dropping terms, doing fewer/more sweeps, or precomputing the answer are NOT).
  Any invalid shape → the node is invalid (score 0).
- You may NOT edit the timing harness or the reference; only `candidate_stencil.c`.

## Rules the build enforces

These are checked mechanically when your kernel is compiled. Breaking one makes the
candidate invalid, which scores 0 — so they are worth reading once.

- **Export only `jacobi()`.** Everything else in `candidate_stencil.c` must be `static`.
  Your kernel object is linked into the same executable as the frozen measurement
  driver, so a second exported symbol can silently replace one of the driver's.
- **All your work must happen inside `jacobi()`.** A constructor, a destructor or an
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

- You do not need to write your own timing, I/O, or test data — just `jacobi()`.
- **Check your work before finishing** with the provided self-test:

  ```
  make check
  ```

  It prints `correct=yes/NO` and an estimated `speedup~Nx` **against the naive
  kernel, which is NOT the scoring denominator**. To convert: the reference is
  about 53x the naive kernel here, so your score is roughly `speedup / 53`.
  A self-test speedup of 53 is a score of about 1.0. The printed number is
  still the right thing to watch while iterating, since it moves with your
  kernel;
  and `SELFTEST: PASS` / `FAIL`. Iterate until it says **PASS with a high
  speedup**. **Never finish while it says `SELFTEST: FAIL`** — `correct=NO` means
  your kernel is wrong and the evaluator scores it 0; a correct slower kernel
  beats a fast wrong one. Do NOT write your own `main()` or `#include "stencil_main.c"`.
- The evaluator (several shapes, fresh data) is authoritative; the self-test is a
  fast local proxy using the same correctness rule.
