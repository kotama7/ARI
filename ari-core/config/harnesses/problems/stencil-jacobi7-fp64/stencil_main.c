/* FROZEN timing + binary-I/O harness for the 3-D 7-point Jacobi stencil task
 * (handoff study task D). The agent must NOT edit this file. It is compiled with
 * the candidate's jacobi() (and, separately, with the frozen baseline) using
 * identical flags, so the measured speedup reflects the algorithm, not the build.
 *
 * ANTI-GAMING of the TIMER (pre-run audit fix — mirrors the GEMM harness):
 *   - ONE cold timed call per process; NO in-process warmup. A candidate can no
 *     longer compute during a warmup sweep and no-op the timed call (there is no
 *     warmup call in the same process to prime a buffer from). The Python runner
 *     invokes this program once per rep, each with a FRESH random field u0, and
 *     verifies EVERY rep's output — so a kernel that caches an earlier result in
 *     static state produces a WRONG answer for the new problem and is rejected.
 *   - The output buffer u is POISONED to NaN before the timed call, so a kernel
 *     that returns without writing the whole field leaves NaN and fails the
 *     correctness check.
 *   - The measured time is written to a PRIVATE file (argv[3]), never to stdout,
 *     so a candidate cannot forge it (e.g. via a destructor printing a fake
 *     "median_sec="): the kernel gets only u0/u pointers, not the file path,
 *     and the runner uses an unguessable temp path.
 *
 * Usage:  prog <problem.bin> <out.bin> <timing.bin>
 * problem.bin (little-endian, written by the Python runner):
 *   int32 nx, int32 ny, int32 nz, int32 nt
 *   double u0[nx*ny*nz]   (row-major, index ((i*ny)+j)*nz+k)
 * out.bin:    double u[nx*ny*nz] (the field after nt sweeps).
 * timing.bin: double seconds (the single cold timed call).
 */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <time.h>
#include "stencil_kernel.h"

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
    int hdr[4];
    if (fread(hdr, sizeof(int), 4, f) != 4) { fprintf(stderr, "bad header\n"); return 2; }
    int nx = hdr[0], ny = hdr[1], nz = hdr[2], nt = hdr[3];
    if (nx <= 0 || ny <= 0 || nz <= 0 || nt < 0) { fprintf(stderr, "bad dims\n"); return 2; }
    size_t N = (size_t)nx * (size_t)ny * (size_t)nz;
    double *u0 = (double *)malloc(sizeof(double) * N);
    double *u  = (double *)malloc(sizeof(double) * N);
    if (!u0 || !u) { fprintf(stderr, "oom\n"); return 2; }
    if (fread(u0, sizeof(double), N, f) != N) { fprintf(stderr, "short read\n"); return 2; }
    fclose(f);

    /* Poison the output so a kernel that does not write every element (e.g. a
     * no-op, or one that skips the boundary planes) is caught by the correctness
     * check (NaN never satisfies the nt-scaled bound). */
    for (size_t i = 0; i < N; ++i) u[i] = NAN;

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
    jacobi(nx, ny, nz, nt, u0, u);
    double elapsed = now_sec() - t0;

    FILE *o = fopen(argv[2], "wb");
    if (!o) { perror("open out"); return 2; }
    fwrite(u, sizeof(double), N, o);
    fclose(o);

    FILE *tf = fopen(argv[3], "wb");
    if (!tf) { perror("open timing"); return 2; }
    fwrite(&elapsed, sizeof(double), 1, tf);
    fclose(tf);

    free(u0); free(u);
    return 0;
}
