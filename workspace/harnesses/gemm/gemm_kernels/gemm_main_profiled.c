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

#include <unistd.h>                                                          /*GATE*/
                                                                             /*GATE*/
/* NOT SCORED. This file is gemm_main.c plus a counter gate, and it exists so     *//*GATE*/
/* the SCORED driver never has to change: the pins, the timing semantics and *//*GATE*/
/* the anti-gaming surface of the scored build stay exactly as they were.    *//*GATE*/
/* Every added line is marked, and a test asserts that deleting the marked   *//*GATE*/
/* lines reproduces the scored driver byte for byte -- otherwise this copy   *//*GATE*/
/* would drift and the profile would describe a different program.           *//*GATE*/
/*                                                                           *//*GATE*/
/* PROTOCOL (see workspace/tools/region_counters.c): write one byte, BLOCK   *//*GATE*/
/* until the parent has armed the counters, run the region, write one more.  *//*GATE*/
/* Blocking is the point -- without it the counters start a few microseconds *//*GATE*/
/* into the region. With no gate fds in the environment this is inert, so    *//*GATE*/
/* the binary still runs standalone.                                         *//*GATE*/
static int _g_w = -1, _g_r = -1;                                             /*GATE*/
static void gate_init(void) {                                                /*GATE*/
    const char *w = getenv("ARI_COUNTER_GATE_FD");                           /*GATE*/
    const char *r = getenv("ARI_COUNTER_ACK_FD");                            /*GATE*/
    if (w) _g_w = atoi(w);                                                   /*GATE*/
    if (r) _g_r = atoi(r);                                                   /*GATE*/
}                                                                            /*GATE*/
static void gate_enter(void) {                                               /*GATE*/
    char b = 1;                                                              /*GATE*/
    if (_g_w < 0) return;                                                    /*GATE*/
    if (write(_g_w, &b, 1) != 1) return;                                     /*GATE*/
    if (_g_r >= 0 && read(_g_r, &b, 1) != 1) return;                         /*GATE*/
}                                                                            /*GATE*/
static void gate_leave(void) {                                               /*GATE*/
    char b = 1;                                                              /*GATE*/
    if (_g_w >= 0) { ssize_t n = write(_g_w, &b, 1); (void)n; }              /*GATE*/
}                                                                            /*GATE*/
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
    gate_init();                                                             /*GATE*/
    gate_enter();                                                            /*GATE*/
    double t0 = now_sec();
    gemm(n, m, p, A, B, C);
    double elapsed = now_sec() - t0;
    gate_leave();                                                            /*GATE*/

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
