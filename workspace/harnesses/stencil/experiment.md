# Experiment: optimize a 3-D 7-point Jacobi stencil

Goal: make `nt` sweeps of a 3-D 7-point Jacobi stencil over an `nx×ny×nz` fp64
field as fast as possible. Correctness and speed are judged by a fixed non-LLM
evaluator.

## What you produce

Your working directory is **already seeded** with the scaffolding — list it:

- `candidate_stencil.c` — the file you edit (starts as a correct naive single-thread sweep).
- `stencil_kernel.h` — the `jacobi()` contract (do not change the signature).
- `stencil_main.c` — the FROZEN timing/I-O harness (do not edit).
- `baseline_stencil.c` — the FROZEN naive single-thread baseline (the speedup denominator).
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

- The evaluator owns compilation, the field data `u0`, the timing loop, and the
  baseline. It compiles your `candidate_stencil.c` against a FROZEN harness with
  the same compiler and default flags as a frozen naive baseline. It runs both on
  one cubic and two anisotropic grid shapes. Each repetition is a matched
  candidate/baseline pair, and the reported shape speedup is the median of the
  accepted per-pair speedup ratios. The overall score is the geometric mean over
  all shapes.
- **You may tune the compile flags.** Put optimization flags in `candidate_flags.txt`
  (whitespace-separated, `#` comments allowed). They are appended to the defaults for
  YOUR kernel only — the naive baseline always keeps the defaults, since it is the
  reference point the speedup is measured against. Both `make candidate` and the
  scorer read this file, so what you build locally is what you are scored on.
  Only optimization/tuning flags are accepted (`-O*`, `-f*`, `-m*`, `--param=*`);
  anything that changes the build itself is dropped (`-I`/`-D`/`-include`, `-l`/`-L`/`-Wl`,
  `-o`/`-c`/`-S`/`-E`, `-fplugin`/`-specs`, `-fprofile-*`). Numerics are NOT restricted:
  `-ffast-math` is allowed, but correctness is still decided by the reference oracle's
  error bound, so a transform that leaves the bound fails like any wrong answer.
- The kernel is timed with a **fixed OpenMP thread budget**; the baseline is the
  single-thread naive `ijk` ping-pong sweep. Speedup comes from parallelism,
  SIMD, spatial blocking and temporal tiling — these multiply.
- **Valid** requires: compiles, runs, and is correct on every shape. Correctness
  is per-element vs an fp64 reference with an **nt-scaled** tolerance (FP
  reassociation of the 6-neighbour sum is allowed; changing the coefficients,
  dropping terms, doing fewer/more sweeps, or precomputing the answer are NOT).
  Any invalid shape → the node is invalid (score 0).
- You may NOT edit the timing harness or the baseline; only `candidate_stencil.c`.

## Notes

- You do not need to write your own timing, I/O, or test data — just `jacobi()`.
- **Check your work before finishing** with the provided self-test:

  ```
  make check
  ```

  It prints `correct=yes/NO`, an estimated `speedup~Nx` vs the naive baseline,
  and `SELFTEST: PASS` / `FAIL`. Iterate until it says **PASS with a high
  speedup**. **Never finish while it says `SELFTEST: FAIL`** — `correct=NO` means
  your kernel is wrong and the evaluator scores it 0; a correct slower kernel
  beats a fast wrong one. Do NOT write your own `main()` or `#include "stencil_main.c"`.
- The evaluator (several shapes, fresh data) is authoritative; the self-test is a
  fast local proxy using the same correctness rule.
