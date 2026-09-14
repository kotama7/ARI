/* PINNED SCAFFOLDING. This file is content-addressed by the harness manifest
 * (ari-core/config/harnesses/builtin/hpc_gemm_performance.yaml) and verified
 * before any measurement runs; a modified byte refuses to measure rather than
 * measuring differently.
 *
 * It moved into ari-core so a registered performance harness no longer depends
 * on a workspace directory being present. The measurement it defines is
 * unchanged: one cold timed call per process, the output poisoned to NaN so a
 * kernel that does not write it fails the oracle, and the OpenMP team created
 * before the timer so team setup is not charged to the kernel.
 */
/* FROZEN timing + binary-I/O harness for the GEMM task (handoff study task A).
 * The agent must NOT edit this file. It is compiled with the candidate's
 * gemm() (and, separately, with the frozen baseline) using identical flags, so
 * the measured speedup reflects the algorithm, not the build.
 *
 * ANTI-GAMING of the TIMER (pre-run audit fix):
 *   - ONE cold timed call per process; NO in-process warmup. A candidate can no
 *     longer compute during warmup and no-op the timed call (there is no warmup
 *     call in the same process to prime a cache from). The Python runner invokes
 *     this program once per rep, each with a FRESH random problem, and verifies
 *     EVERY rep's output — so a kernel that caches an earlier result in static
 *     state produces a WRONG answer for the new problem and is rejected.
 *   - The output buffer C is POISONED to NaN before the timed call, so a kernel
 *     that returns without writing C leaves NaN and fails the correctness check.
 *   - The measured time is written to a PRIVATE file (argv[3]), never to stdout,
 *     so a candidate cannot forge it (e.g. via a destructor printing a fake
 *     "median_sec="): the kernel gets only A/B/C pointers, not the file path,
 *     and the runner uses an unguessable temp path.
 *
 * Usage:  prog <problem.bin> <out.bin> <timing.bin>
 * problem.bin (little-endian, written by the Python runner):
 *   int32 n, int32 m, int32 p
 *   double A[n*p]   (row-major)
 *   double B[p*m]   (row-major)
 * out.bin:    double C[n*m] (row-major).
 * timing.bin: double seconds (the single cold timed call).
 */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <time.h>
#include "gemm_kernel.h"

static double now_sec(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s <problem.bin> <out.bin> <timing.bin>\n", argv[0]);
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror("open problem"); return 2; }
    int hdr[3];
    if (fread(hdr, sizeof(int), 3, f) != 3) { fprintf(stderr, "bad header\n"); return 2; }
    int n = hdr[0], m = hdr[1], p = hdr[2];
    if (n <= 0 || m <= 0 || p <= 0) { fprintf(stderr, "bad dims\n"); return 2; }
    double *A = (double *)malloc(sizeof(double) * (size_t)n * (size_t)p);
    double *B = (double *)malloc(sizeof(double) * (size_t)p * (size_t)m);
    double *C = (double *)malloc(sizeof(double) * (size_t)n * (size_t)m);
    if (!A || !B || !C) { fprintf(stderr, "oom\n"); return 2; }
    if (fread(A, sizeof(double), (size_t)n * p, f) != (size_t)n * p) return 2;
    if (fread(B, sizeof(double), (size_t)p * m, f) != (size_t)p * m) return 2;
    fclose(f);

    /* Poison the output so a kernel that does not write every element is caught
     * by the correctness check (NaN never satisfies the residual bound). */
    const size_t NM = (size_t)n * (size_t)m;
    for (size_t i = 0; i < NM; ++i) C[i] = NAN;

    /* v2: create the OpenMP thread team OUTSIDE the timed window.
     * This is NOT a warmup: the candidate kernel is not called here, so
     * the candidate cannot precompute the answer. The pragma lowers to an
     * external GOMP_parallel call, which a candidate translation unit could
     * define; that is closed now, not merely noted. The candidate object is
     * audited before it is linked and may define no global symbol but the
     * entry point, so a candidate defining GOMP_parallel is REFUSED rather
     * than measured. Verified by compiling one: it is rejected, as is a
     * candidate defining clock_gettime and one carrying an .init_array
     * constructor, while an honest kernel builds. It
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
    gemm(n, m, p, A, B, C);
    double elapsed = now_sec() - t0;

    FILE *o = fopen(argv[2], "wb");
    if (!o) { perror("open out"); return 2; }
    fwrite(C, sizeof(double), NM, o);
    fclose(o);

    FILE *tf = fopen(argv[3], "wb");
    if (!tf) { perror("open timing"); return 2; }
    fwrite(&elapsed, sizeof(double), 1, tf);
    fclose(tf);

    free(A); free(B); free(C);
    return 0;
}
