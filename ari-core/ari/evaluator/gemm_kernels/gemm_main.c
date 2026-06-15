/* FROZEN timing + binary-I/O harness for the GEMM task (handoff study task A).
 * The agent must NOT edit this file. It is compiled with the candidate's
 * gemm() (and, separately, with the frozen baseline) using identical flags, so
 * the measured speedup reflects the algorithm, not the build.
 *
 * Usage:  prog <problem.bin> <out.bin> <warmup> <reps>
 * problem.bin (little-endian, written by the Python runner):
 *   int32 n, int32 m, int32 p
 *   double A[n*p]   (row-major)
 *   double B[p*m]   (row-major)
 * out.bin: double C[n*m] (row-major). stdout: "median_sec=<seconds>".
 */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "gemm_kernel.h"

static double now_sec(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

static int cmp_d(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

int main(int argc, char **argv) {
    if (argc < 5) {
        fprintf(stderr, "usage: %s <problem.bin> <out.bin> <warmup> <reps>\n", argv[0]);
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

    int warmup = atoi(argv[3]);
    int reps = atoi(argv[4]);
    if (warmup < 0) warmup = 0;
    if (reps < 1) reps = 1;

    for (int w = 0; w < warmup; ++w)
        gemm(n, m, p, A, B, C);

    double *t = (double *)malloc(sizeof(double) * (size_t)reps);
    for (int r = 0; r < reps; ++r) {
        double t0 = now_sec();
        gemm(n, m, p, A, B, C);
        t[r] = now_sec() - t0;
    }
    qsort(t, (size_t)reps, sizeof(double), cmp_d);
    double median = t[reps / 2];

    FILE *o = fopen(argv[2], "wb");
    if (!o) { perror("open out"); return 2; }
    fwrite(C, sizeof(double), (size_t)n * m, o);
    fclose(o);
    printf("median_sec=%.9f\n", median);

    free(A); free(B); free(C); free(t);
    return 0;
}
