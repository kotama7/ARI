#include "spmm_kernel.h"

/* CANDIDATE kernel — the file the agent edits to optimize CSR SpMM.
 * Seeded identical to the baseline (a correct, valid starting point); the agent
 * improves it (OpenMP scheduling, blocking, row-length bucketing, SIMD, …).
 * Keep the spmm() signature from spmm_kernel.h exactly. Correctness is checked
 * against an fp64 reference with a row-length-scaled epsilon (do NOT skip terms
 * or precompute outside the call — a fresh X is used for the correctness check).
 *
 * NOTE: this is the per-node TEMPLATE; the run harness copies it into each
 * node's work_dir, where the agent edits its own copy. */
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
