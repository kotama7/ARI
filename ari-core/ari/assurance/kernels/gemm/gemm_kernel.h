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
#ifndef GEMM_KERNEL_H
#define GEMM_KERNEL_H

/* The contract the candidate must keep EXACTLY.
 *
 *   C = A * B   (dense, row-major, fp64)
 *     A is n x p, B is p x m, C is n x m.
 *     C[i*m + j] = sum_l A[i*p + l] * B[l*m + j]
 *
 * Edit only candidate_gemm.c (this function's body). Do not change the
 * signature. You may NOT call a BLAS/LAPACK library (the build does not link
 * one) — write the kernel yourself. */
void gemm(int n, int m, int p,
          const double *A, const double *B, double *C);

#endif /* GEMM_KERNEL_H */
