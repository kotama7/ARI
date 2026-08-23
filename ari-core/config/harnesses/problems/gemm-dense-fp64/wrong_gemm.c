/* PARITY PROBE, negative control 2: FAST but WRONG.
 *
 * Must fail on the ORACLE, not on the ratio -- it is much faster than the
 * reference and would be credited by any instrument that only timed. It writes
 * every element, so it also gets past the driver's NaN poison and the output
 * size check; what catches it is the residual bound (measured at 2.79e11x the
 * bound on an aarch64 compute node).
 */
#include "gemm_kernel.h"

void gemm(int n, int m, int p,
          const double *A, const double *B, double *C) {
  (void)A; (void)B; (void)p;
  for (int i = 0; i < n * m; i++) C[i] = 0.0;
}
