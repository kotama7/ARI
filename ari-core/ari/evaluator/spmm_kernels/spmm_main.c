/* FROZEN timing + I/O harness for the SpMM measurement (handoff study B2b).
 * The agent must NOT edit this file (checksum-guarded): it owns the timer and
 * the warmup/repetition protocol, so candidate kernels cannot game the timing.
 *
 * Usage:  prog <problem.bin> <out.bin> <warmup> <reps>
 * problem.bin (little-endian, written by the Python runner):
 *   int32[4] = {n, m, k, nnz}
 *   int32[n+1]   indptr
 *   int32[nnz]   indices
 *   float64[nnz] values
 *   float64[m*k] X  (row-major)
 * out.bin: float64[n*k] Y (row-major). stdout: "median_sec=<double>".
 */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "spmm_kernel.h"

static double now_sec(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static int cmp_d(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

int main(int argc, char **argv)
{
    if (argc < 5) {
        fprintf(stderr, "usage: %s <problem.bin> <out.bin> <warmup> <reps>\n", argv[0]);
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

    int warmup = atoi(argv[3]);
    int reps = atoi(argv[4]);
    if (reps < 1) reps = 1;
    if (warmup < 0) warmup = 0;

    for (int w = 0; w < warmup; ++w)
        spmm(n, m, k, indptr, indices, values, X, Y);

    double *t = (double *)malloc(sizeof(double) * (size_t)reps);
    if (!t) { fprintf(stderr, "oom\n"); return 2; }
    for (int r = 0; r < reps; ++r) {
        double s = now_sec();
        spmm(n, m, k, indptr, indices, values, X, Y);
        t[r] = now_sec() - s;
    }
    qsort(t, (size_t)reps, sizeof(double), cmp_d);
    double median = t[reps / 2];

    FILE *o = fopen(argv[2], "wb");
    if (!o) { perror("open out"); return 2; }
    fwrite(Y, sizeof(double), (size_t)n * (size_t)k, o);
    fclose(o);
    printf("median_sec=%.9g\n", median);

    free(indptr); free(indices); free(values); free(X); free(Y); free(t);
    return 0;
}
