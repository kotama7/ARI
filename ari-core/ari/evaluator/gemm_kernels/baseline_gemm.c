/* FROZEN 1x reference GEMM — the speedup denominator. Textbook naive ijl order
 * (single-thread, cache-unfriendly B column access). Compiled with the SAME
 * compiler + flags as the candidate so the speedup measures the agent's
 * algorithm (loop order, parallelism, blocking), not the build. Do not edit. */
#include "gemm_kernel.h"

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
