#include "stencil_kernel.h"
#include <stdlib.h>
#include <string.h>

/* CANDIDATE kernel — the file you edit to optimize the 3-D 7-point Jacobi sweep.
 * Seeded identical to the baseline (a correct, valid starting point: naive
 * single-thread ijk ping-pong). This kernel is MEMORY-BANDWIDTH bound, so the
 * optimization rungs compound:
 *   1. OpenMP parallelism over the outer (i) loop,
 *   2. SIMD along the contiguous k dimension,
 *   3. spatial cache blocking (tile i/j/k so reused planes stay hot),
 *   4. NUMA first-touch initialisation of the scratch buffers,
 *   5. TEMPORAL / time blocking (advance several sweeps over a cache-resident
 *      tile before moving on) — this is what breaks past the bandwidth roofline.
 * Keep the jacobi() signature from stencil_kernel.h EXACTLY. Boundary planes are
 * fixed (Dirichlet) = u0. Correctness is checked against an fp64 reference with
 * an nt-scaled epsilon (reassociating the 6-neighbour sum is allowed; changing
 * the coefficients, dropping terms, or precomputing the answer is NOT). */
void jacobi(int nx, int ny, int nz, int nt,
            const double *u0, double *u)
{
    const double c0 = 0.5, cw = 1.0 / 12.0;
    const size_t N = (size_t)nx * (size_t)ny * (size_t)nz;
    const size_t si = (size_t)ny * (size_t)nz;
    const size_t sj = (size_t)nz;
    double *cur = (double *)malloc(sizeof(double) * N);
    double *nxt = (double *)malloc(sizeof(double) * N);
    if (!cur || !nxt) { free(cur); free(nxt); return; }
    memcpy(cur, u0, sizeof(double) * N);
    memcpy(nxt, u0, sizeof(double) * N);

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
