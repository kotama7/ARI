#include "gemm_kernel.h"

/* CANDIDATE kernel — the file you edit to optimize dense GEMM (C = A*B).
 * Seeded identical to the baseline (a correct, valid starting point: textbook
 * naive ijl). Improve it — the two big wins compound:
 *   1. cache-friendly loop order (ikj: stream a row of B, accumulate into C[i,:])
 *   2. OpenMP parallelism over rows
 * then blocking / SIMD-friendly layout for more. Keep the gemm() signature from
 * gemm_kernel.h exactly. Correctness is checked against an fp64 reference with a
 * contraction-length-scaled epsilon (FP reduction reorderings are allowed;
 * dropping terms or precomputing the answer is NOT). You may NOT call BLAS — the
 * build links no BLAS; write the kernel yourself. */
void gemm(int n, int m, int p,
          const double *A, const double *B, double *C)
{
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < m; ++j) {
            double s = 0.0;
            for (int l = 0; l < p; ++l)
                s += A[(long)i * p + l] * B[(long)l * m + j];
            C[(long)i * m + j] = s;
        }
    }
}
