/* WHERE THE AGENT STARTS. Correct, single-threaded, and deliberately naive.
 *
 * This is NOT the reference. The reference is the denominator the verdict is
 * measured against and it is withheld from the work dir on purpose: a task that
 * seeds its own denominator is a copying exercise. What is seeded is something
 * that compiles, keeps the contract and produces right answers, so a run that
 * improves nothing still produces a scoreable candidate rather than a build
 * failure that is indistinguishable from an infrastructure fault.
 *
 * The loop order is ijk, which is the slow one for row-major B: it strides
 * through B by m. That is left as-is. Making the seed already-good would
 * compress the range the search has to work in and flatter every arm equally.
 */
#include "gemm_kernel.h"

void gemm(int n, int m, int p,
          const double *A, const double *B, double *C) {
  for (int i = 0; i < n; i++) {
    for (int j = 0; j < m; j++) {
      double sum = 0.0;
      for (int l = 0; l < p; l++) {
        sum += A[i * p + l] * B[l * m + j];
      }
      C[i * m + j] = sum;
    }
  }
}
