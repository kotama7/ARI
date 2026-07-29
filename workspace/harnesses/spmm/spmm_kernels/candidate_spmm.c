#include "spmm_kernel.h"

/* CANDIDATE kernel — the file the agent edits to optimize CSR SpMM.
 * Seeded identical to the baseline (a correct, valid starting point); the agent
 * improves it (OpenMP scheduling, blocking, row-length bucketing, SIMD, …).
 * Keep the spmm() signature from spmm_kernel.h exactly. Correctness is checked
 * against an fp64 reference with a row-length-scaled epsilon. The harness draws
 * a FRESH random X for EVERY timed rep and runs each rep in its own process (one
 * cold spmm() call per process), then verifies that rep's Y against the fp64
 * reference for THAT X — so you cannot skip terms, precompute a result outside
 * the call, or cache across reps: a stale/memoized answer is wrong for the new X
 * and is rejected, and a kernel that does not fill Y leaves the NaN poison.
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
