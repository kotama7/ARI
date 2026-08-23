/* PARITY PROBE, negative control 1: CORRECT but SLOW.
 *
 * Must fail on the RATIO. Together with the fast-but-wrong control it is what
 * distinguishes a performance harness from a stopwatch: a probe with only this
 * control would pass on an instrument that never checked an answer, and a probe
 * with only the other would pass on one that never timed anything. The probe
 * asserts not just that both fail but that they fail for DIFFERENT reasons.
 *
 * Naive ijk, single-threaded, no ISA help. Measured at 0.0017x of the frozen
 * reference on an aarch64 compute node.
 */
#include "gemm_kernel.h"

void gemm(int n, int m, int p,
          const double *A, const double *B, double *C) {
  for (int i = 0; i < n; i++)
    for (int j = 0; j < m; j++) {
      double s = 0.0;
      for (int l = 0; l < p; l++) s += A[i * p + l] * B[l * m + j];
      C[i * m + j] = s;
    }
}
