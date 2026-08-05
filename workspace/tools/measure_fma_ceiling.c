/* FMA ceiling with EXPLICIT SVE intrinsics.
 *
 * FIVE earlier attempts are worth recording, because each failed for a different
 * reason and all of them reported a "ceiling" BELOW the 382 GF/s the GEMM
 * reference achieves — which is a broken benchmark, not a slow machine:
 *   1. accumulators in a plain array: spilled to memory, 65 GF/s
 *   2-3. relying on auto-vectorisation: gcc emitted few SVE FMAs, clang emitted
 *        ZERO (objdump: 0 z-register fmla), 95-300 GF/s
 *   4. arm_sve.h with gcc 8.5: the header predates that compiler
 *   5. svfloat64_t a[NACC]: "array has sizeless element type" — SVE vector types
 *      cannot be array elements, struct members, or sizeof operands
 * Hence: named accumulators expanded by macro, built by a compiler that has the
 * header. A ceiling probe is not a scored candidate, so it is not bound by the
 * task contract and may say exactly what it means. */
#include <stdio.h>
#include <time.h>
#include <omp.h>
#include <arm_sve.h>

#ifndef ITER
#define ITER 20000000L
#endif

static double now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

/* 16 independent chains: comfortably more than the FMA latency, so the pipes
   never stall waiting on a dependency. */
#define ACCS(X) X(0) X(1) X(2) X(3) X(4) X(5) X(6) X(7) \
                X(8) X(9) X(10) X(11) X(12) X(13) X(14) X(15)
#define NACC 16

int main(void) {
    int nt = 0;
#pragma omp parallel
    { if (omp_get_thread_num() == 0) nt = omp_get_num_threads(); }
    const unsigned long long vl = (unsigned long long)svcntd();
    double sink = 0.0;
    double t0 = now();
#pragma omp parallel reduction(+ : sink)
    {
        const svbool_t pg = svptrue_b64();
        const svfloat64_t b = svdup_f64(1.0000001), c = svdup_f64(0.9999999);
#define DECL(i) svfloat64_t a##i = svdup_f64((double)(i) + 1.0);
        ACCS(DECL)
#undef DECL
        for (long it = 0; it < ITER; ++it) {
#define STEP(i) a##i = svmla_f64_x(pg, c, a##i, b);
            ACCS(STEP)
#undef STEP
        }
        double s = 0.0;
#define RED(i) s += svaddv_f64(pg, a##i);
        ACCS(RED)
#undef RED
        sink += s;
    }
    double dt = now() - t0;
    double gf = 2.0 * (double)NACC * (double)vl * (double)ITER * (double)nt / dt * 1e-9;
    printf("threads %d  lanes %llu  NACC %d  elapsed %.3f s  ceiling %.1f GF/s  (sink %.3e)\n",
           nt, vl, NACC, dt, gf, sink);
    return 0;
}
