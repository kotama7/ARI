/* PARITY PROBE, negative control 2: FAST but WRONG.
 *
 * Must fail on the ORACLE, not the ratio. Writes every element of Y, so it
 * also gets past the driver's NaN poison and the output size check; what
 * catches it is the per-row backward-error bound.
 */
#include "spmm_kernel.h"
#include <stddef.h>   /* size_t: the contract header declares none */

void spmm(int n, int m, int k,
          const int *indptr, const int *indices, const double *values,
          const double *X, double *Y) {
  (void)m; (void)indptr; (void)indices; (void)values; (void)X;
  for (size_t i = 0; i < (size_t)n * (size_t)k; ++i) Y[i] = 0.0;
}
