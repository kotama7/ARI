/* FROZEN timing + binary-I/O harness for the SpMM task (handoff study B2b).
 * The agent must NOT edit this file. It is compiled with the candidate's
 * spmm() (and, separately, with the frozen baseline) using identical flags, so
 * the measured speedup reflects the algorithm, not the build.
 *
 * ANTI-GAMING of the TIMER (pre-run audit fix — mirrors the GEMM harness):
 *   - ONE cold timed call per process; NO in-process warmup. A candidate can no
 *     longer compute during warmup and no-op the timed call (there is no warmup
 *     call in the same process to prime a cache from). The Python runner invokes
 *     this program once per rep, each with a FRESH random X, and verifies EVERY
 *     rep's output — so a kernel that caches an earlier result in static state
 *     produces a WRONG answer for the new problem and is rejected.
 *   - The output buffer Y is POISONED to NaN before the timed call, so a kernel
 *     that returns without writing Y leaves NaN and fails the correctness check.
 *   - The measured time is written to a PRIVATE file (argv[3]), never to stdout,
 *     so a candidate cannot forge it (e.g. via a destructor printing a fake
 *     "median_sec="): the kernel gets only the CSR/X/Y pointers, not the file
 *     path, and the runner uses an unguessable temp path.
 *
 * Usage:  prog <problem.bin> <out.bin> <timing.bin>
 * problem.bin (little-endian, written by the Python runner):
 *   int32[4] = {n, m, k, nnz}
 *   int32[n+1]   indptr
 *   int32[nnz]   indices
 *   float64[nnz] values
 *   float64[m*k] X  (row-major)
 * out.bin:    float64[n*k] Y (row-major).
 * timing.bin: double seconds (the single cold timed call).
 */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <time.h>
#include "spmm_kernel.h"

static double now_sec(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

int main(int argc, char **argv)
{
    if (argc < 4) {
        fprintf(stderr, "usage: %s <problem.bin> <out.bin> <timing.bin>\n", argv[0]);
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror("open problem"); return 2; }
    int hdr[4];
    if (fread(hdr, sizeof(int), 4, f) != 4) { fprintf(stderr, "bad header\n"); return 2; }
    int n = hdr[0], m = hdr[1], k = hdr[2], nnz = hdr[3];
    if (n < 0 || m < 0 || k < 0 || nnz < 0) { fprintf(stderr, "bad dims\n"); return 2; }

    int *indptr = (int *)malloc(sizeof(int) * (size_t)(n + 1));
    int *indices = (int *)malloc(sizeof(int) * (size_t)(nnz ? nnz : 1));
    double *values = (double *)malloc(sizeof(double) * (size_t)(nnz ? nnz : 1));
    double *X = (double *)malloc(sizeof(double) * (size_t)m * (size_t)k);
    double *Y = (double *)malloc(sizeof(double) * (size_t)n * (size_t)k);
    if (!indptr || !indices || !values || !X || !Y) { fprintf(stderr, "oom\n"); return 2; }

    if (fread(indptr, sizeof(int), (size_t)(n + 1), f) != (size_t)(n + 1)) return 2;
    if (nnz && fread(indices, sizeof(int), (size_t)nnz, f) != (size_t)nnz) return 2;
    if (nnz && fread(values, sizeof(double), (size_t)nnz, f) != (size_t)nnz) return 2;
    if (fread(X, sizeof(double), (size_t)m * (size_t)k, f) != (size_t)m * (size_t)k) return 2;
    fclose(f);

    /* Poison the output so a kernel that does not write every element is caught
     * by the correctness check (NaN never satisfies the residual bound). */
    const size_t NK = (size_t)n * (size_t)k;
    for (size_t i = 0; i < NK; ++i) Y[i] = NAN;

    /* v2: create the OpenMP thread team OUTSIDE the timed window.
     * This is NOT a warmup: the candidate kernel is not called here, so
     * the candidate cannot precompute the answer. NOTE this is not a
     * zero-surface region: the pragma lowers to an external GOMP_parallel
     * call, which a candidate translation unit could define. Closing that
     * needs a symbol allowlist on the candidate object (tracked
     * separately). It
     * removes a fixed ~3.2 ms 48-thread team-creation cost that the
     * single-threaded frozen reference never paid, and it pins the master
     * thread under OMP_PROC_BIND, so reference and candidate are finally
     * measured under the same binding regime (v1 timed an UNPINNED reference
     * against PINNED candidates). Paired with credited = internal timer;
     * without that change this is provably inert, because the wall-derived
     * clamp does not contain the candidate's internal time. */
    {
        static volatile double team_sink;
        double s = 0.0;
#pragma omp parallel for reduction(+ : s)
        for (int i = 0; i < 64; ++i) s += (double)i;
        team_sink = s;
    }

    /* ONE cold timed call on the candidate. */
    double t0 = now_sec();
    spmm(n, m, k, indptr, indices, values, X, Y);
    double elapsed = now_sec() - t0;

    FILE *o = fopen(argv[2], "wb");
    if (!o) { perror("open out"); return 2; }
    fwrite(Y, sizeof(double), NK, o);
    fclose(o);

    FILE *tf = fopen(argv[3], "wb");
    if (!tf) { perror("open timing"); return 2; }
    fwrite(&elapsed, sizeof(double), 1, tf);
    fclose(tf);

    free(indptr); free(indices); free(values); free(X); free(Y);
    return 0;
}
