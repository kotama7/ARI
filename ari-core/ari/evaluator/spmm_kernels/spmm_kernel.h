#ifndef SPMM_KERNEL_H
#define SPMM_KERNEL_H

/* CSR SpMM:  Y[n*k] = A[n x m] (CSR) * X[m*k],  X and Y row-major dense.
 *
 * Handoff study (B2b). The AGENT edits ONLY this function (in
 * candidate_spmm.c); the timing + I/O harness (spmm_main.c) is FROZEN and
 * checksum-guarded, so the agent cannot touch the timer or the reference
 * comparison (anti-gaming). The candidate must keep this exact signature.
 *
 *   n        rows of A (= rows of Y)
 *   m        cols of A (= rows of X)
 *   k        columns of X / Y
 *   indptr   CSR row pointers, length n+1
 *   indices  CSR column indices, length indptr[n]
 *   values   CSR values, length indptr[n]
 *   X        dense input,  length m*k (row-major)
 *   Y        dense output, length n*k (row-major), written by the kernel
 */
void spmm(int n, int m, int k,
          const int *indptr, const int *indices, const double *values,
          const double *X, double *Y);

#endif /* SPMM_KERNEL_H */
