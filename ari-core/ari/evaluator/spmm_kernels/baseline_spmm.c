#include "spmm_kernel.h"

/* Reference CSR SpMM — the 1x speedup baseline. Naive, correct, single-thread.
 * FROZEN (checksum-guarded): defines the speedup denominator. Compiled with the
 * SAME compiler + flags as the candidate so the speedup measures the agent's
 * algorithm, not a flag difference. */
void spmm(int n, int m, int k,
          const int *indptr, const int *indices, const double *values,
          const double *X, double *Y)
{
    (void)m;
    for (int i = 0; i < n; ++i) {
        double *yi = Y + (long)i * k;
        for (int c = 0; c < k; ++c) yi[c] = 0.0;
        for (int p = indptr[i]; p < indptr[i + 1]; ++p) {
            const double a = values[p];
            const double *xj = X + (long)indices[p] * k;
            for (int c = 0; c < k; ++c) yi[c] += a * xj[c];
        }
    }
}
