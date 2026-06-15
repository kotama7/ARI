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
