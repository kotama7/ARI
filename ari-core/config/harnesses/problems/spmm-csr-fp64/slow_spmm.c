/* PARITY PROBE, negative control 1: CORRECT but SLOW.
 *
 * Must fail on the RATIO. Naive single-threaded CSR row loop against a
 * reference that is row-parallel with a measured dynamic schedule.
 */
#include "spmm_kernel.h"
#include <stddef.h>   /* size_t: the contract header declares none */

void spmm(int n, int m, int k,
          const int *indptr, const int *indices, const double *values,
          const double *X, double *Y) {
  (void)m;
  for (int i = 0; i < n; ++i) {
    for (int c = 0; c < k; ++c) Y[(size_t)i * k + c] = 0.0;
    for (int idx = indptr[i]; idx < indptr[i + 1]; ++idx) {
      const double a = values[idx];
      const int j = indices[idx];
      for (int c = 0; c < k; ++c)
        Y[(size_t)i * k + c] += a * X[(size_t)j * k + c];
    }
  }
}
