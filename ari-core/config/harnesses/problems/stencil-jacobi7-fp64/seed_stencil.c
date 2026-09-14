/* FROZEN 1x reference 3-D 7-point Jacobi — the speedup denominator. Textbook
 * naive single-thread sweep with a ping-pong buffer, ijk order. Compiled with
 * the SAME compiler + flags as the candidate so the speedup measures the agent's
 * algorithm (parallelism, SIMD, spatial blocking, temporal/time tiling), not the
 * build. Do not edit. */
#include "stencil_kernel.h"
#include <stdlib.h>
#include <string.h>

void jacobi(int nx, int ny, int nz, int nt,
            const double *u0, double *u)
{
    const double c0 = 0.5, cw = 1.0 / 12.0;
    const size_t N = (size_t)nx * (size_t)ny * (size_t)nz;
    const size_t si = (size_t)ny * (size_t)nz; /* stride for i +/- 1 */
    const size_t sj = (size_t)nz;              /* stride for j +/- 1 */
    double *cur = (double *)malloc(sizeof(double) * N);
    double *nxt = (double *)malloc(sizeof(double) * N);
    if (!cur || !nxt) { free(cur); free(nxt); return; }
    memcpy(cur, u0, sizeof(double) * N);
    memcpy(nxt, u0, sizeof(double) * N); /* boundary planes stay = u0 forever */

    for (int t = 0; t < nt; ++t) {
        for (int i = 1; i < nx - 1; ++i)
            for (int j = 1; j < ny - 1; ++j)
                for (int k = 1; k < nz - 1; ++k) {
                    size_t c = ((size_t)i * ny + j) * nz + k;
                    nxt[c] = c0 * cur[c]
                           + cw * (cur[c - si] + cur[c + si]
                                 + cur[c - sj] + cur[c + sj]
                                 + cur[c - 1]  + cur[c + 1]);
                }
        double *tmp = cur; cur = nxt; nxt = tmp;
    }
    memcpy(u, cur, sizeof(double) * N);
    free(cur); free(nxt);
}
