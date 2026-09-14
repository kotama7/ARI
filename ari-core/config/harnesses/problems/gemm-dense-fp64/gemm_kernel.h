/* PINNED SCAFFOLDING, owned by the problem definition beside it (problem.yaml).
 * The problem's digest covers these bytes, and a harness manifest pins that
 * digest, so a modified byte refuses to measure rather than measuring
 * differently.
 *
 * It lives with the PROBLEM rather than in ARI core because which contract a
 * candidate must keep is part of the question being asked, and questions are
 * meant to be added without editing ARI. What ARI still owns is the instrument:
 * the flags this is compiled with, the timed window, and the oracle. A problem
 * cannot reach any of those.
 *
 * The measurement this defines is unchanged from the prototype: one cold timed
 * call per process, the output poisoned to NaN so a kernel that does not write
 * it fails the oracle, and the OpenMP team created before the timer so team
 * setup is not charged to the kernel.
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
