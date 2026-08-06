/* FROZEN REFERENCE SpMM — the score denominator. Do not edit.
 *
 * v2 replaces v1's naive single-threaded CSR kernel with a COMPETENT reference,
 * for the same reason as the GEMM task: against a naive denominator the score
 * says how far a candidate is from doing nothing, not how good it is.
 *
 * WHAT THIS IS, and why each part is here rather than being "more optimisation":
 *
 *  1. ROW PARALLELISM WITH DYNAMIC SCHEDULING, CHUNK 8. Two of the six scored
 *     matrix families (power_law, skewed) have heavy-tailed row counts by
 *     construction — a few rows carry a large share of the nonzeros. A static
 *     schedule hands one thread those rows and the rest idle, so the schedule is
 *     part of being competent here, not a micro-optimisation: measured, static
 *     runs 31.9 ms on power_law against 23.8 ms dynamic.
 *
 *     THE CHUNK IS 8 BECAUSE IT WAS MEASURED, and it matters for the SCORE'S
 *     STABILITY as much as its speed. At chunk 32 the run-to-run spread on the
 *     heavy-tailed families was 1.38% and 3.40%, against 0.26-0.61% on the other
 *     four — the assignment of the dense rows to threads differs every run, and
 *     candidate and reference draw that lottery independently, so it does not
 *     cancel in the ratio. At chunk 8 the same source is both FASTER (23.8 /
 *     23.9 / 15.2 ms against 24.3 / 24.9 / 15.6) and far tighter (0.51% / 0.72%
 *     / 0.26%). guided and static were also tried: both are 10-30% slower.
 *     A sibling comparison should not be decided by which thread got the dense
 *     rows.
 *
 *  2. UNROLLING OVER FOUR NONZEROS. The naive kernel does a read-modify-write of
 *     the whole k-wide output row once PER NONZERO. Consuming four nonzeros per
 *     pass cuts that traffic fourfold and gives the FMA units four independent
 *     chains, which is the same register-blocking idea the GEMM reference uses
 *     on its rows. Remainders are handled by an obviously correct tail loop, so
 *     nothing assumes a row length divisible by anything.
 *
 *  3. A VECTORISED, UNIT-STRIDE INNER LOOP. The k loop is contiguous in both X
 *     and Y, which is the shape this compiler vectorises well. The irregular
 *     access is the X ROW SELECTION (indices[p]), which happens once per
 *     nonzero, outside the inner loop — so the gather cost is amortised over k
 *     contiguous doubles rather than paid per element.
 *
 * IT IS IN CONTRACT. Plain C, OpenMP and compile flags — no intrinsics, no
 * assembly, no library, and no assumption about k or row lengths. Everything
 * here is something the agent is allowed to write.
 *
 * IT IS NOT SEEDED into the agent's working directory: it is the denominator,
 * and a copy of the denominator would score 1.0 for free.
 */
#include "spmm_kernel.h"

void spmm(int n, int m, int k,
          const int *indptr, const int *indices, const double *values,
          const double *X, double *Y)
{
    (void)m;

#pragma omp parallel for schedule(dynamic, 8)
    for (int i = 0; i < n; ++i) {
        double *__restrict yi = Y + (long)i * k;
        for (int c = 0; c < k; ++c) yi[c] = 0.0;

        const int p0 = indptr[i];
        const int p1 = indptr[i + 1];
        int p = p0;

        for (; p + 3 < p1; p += 4) {
            const double a0 = values[p + 0], a1 = values[p + 1];
            const double a2 = values[p + 2], a3 = values[p + 3];
            const double *__restrict x0 = X + (long)indices[p + 0] * k;
            const double *__restrict x1 = X + (long)indices[p + 1] * k;
            const double *__restrict x2 = X + (long)indices[p + 2] * k;
            const double *__restrict x3 = X + (long)indices[p + 3] * k;
#pragma omp simd
            for (int c = 0; c < k; ++c)
                yi[c] += a0 * x0[c] + a1 * x1[c] + a2 * x2[c] + a3 * x3[c];
        }

        for (; p < p1; ++p) {
            const double a = values[p];
            const double *__restrict xj = X + (long)indices[p] * k;
#pragma omp simd
            for (int c = 0; c < k; ++c) yi[c] += a * xj[c];
        }
    }
}
