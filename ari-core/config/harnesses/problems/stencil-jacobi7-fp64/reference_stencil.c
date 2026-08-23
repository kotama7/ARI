/* FROZEN REFERENCE 3-D 7-point Jacobi — the score denominator. Do not edit.
 *
 * v2 replaces v1's naive single-threaded sweep with a COMPETENT reference. On
 * this task that word means one specific thing before it means anything else:
 *
 *   PARALLEL FIRST TOUCH. The field is 134 MB per buffer at the scored grid, so
 *   this kernel is bandwidth-bound and nothing else matters until the pages are
 *   on the right NUMA domain. Measured on this machine: 602.8 GB/s when the
 *   buffers are first touched by the same threads that later sweep them, against
 *   192.3 GB/s when one thread touches them all — a factor of 3.1 for a change
 *   that adds no arithmetic. The v1 baseline initialised its buffers with a
 *   single-threaded memcpy, which places every page on the master's domain, and
 *   the campaign's candidates then measured 71.8 GB/s, 11.9% of the achievable
 *   figure. A reference that did not do this would be measuring the agents
 *   against a kernel crippled in the one way that dominates the problem.
 *
 * The touch loop uses the SAME static decomposition over i as the sweep, so each
 * thread writes the pages it will later read. That correspondence is the whole
 * mechanism; changing either schedule without the other silently undoes it.
 *
 * The rest is unremarkable and deliberately so: parallel over i, contiguous
 * unit-stride innermost k loop for the vectoriser, ping-pong buffers, boundary
 * planes carried through untouched. No spatial or temporal blocking — those are
 * real further levers and are left for the candidate to find.
 *
 * IT IS IN CONTRACT: plain C, OpenMP, and the kernel's own scratch allocation,
 * which the task contract explicitly permits. Nothing here is closed to the
 * agent. IT IS NOT SEEDED into the agent's working directory — it is the
 * denominator, and a copy of the denominator would score 1.0 for free.
 */
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

    /* PARALLEL FIRST TOUCH. malloc has only reserved address space; each page is
     * bound to a NUMA domain when it is first WRITTEN. Doing that here, from the
     * same thread that will own this i-range in the sweep below, is what makes
     * the loads local. Both buffers are touched: nxt is written first in sweep 0
     * and read after the first swap. */
#pragma omp parallel for schedule(static)
    for (int i = 0; i < nx; ++i) {
        const size_t off = (size_t)i * si;
        memcpy(cur + off, u0 + off, sizeof(double) * si);
        memcpy(nxt + off, u0 + off, sizeof(double) * si);
    }

    for (int t = 0; t < nt; ++t) {
        /* schedule(static) over the same i axis as the touch loop, but NOT the
         * same iteration space: the touch runs [0, nx) and the sweep [1, nx-1),
         * so static chunking offsets the thread->row map by one. Each thread
         * therefore sweeps one row it did not touch. MEASURED
         * (20260803_stencil_ft): making the two spaces agree exactly - touch
         * over [1, nx-1) with the halo rows touched by the thread that reads
         * them - scores 0.9876 against this loop's 0.9993 self-check, i.e. 1.2%
         * SLOWER, so the offset is not worth removing. Recorded because the
         * corpus audit faults candidates for exactly this mismatch; here it was
         * checked rather than assumed. */
#pragma omp parallel for schedule(static)
        for (int i = 1; i < nx - 1; ++i) {
            for (int j = 1; j < ny - 1; ++j) {
                const size_t base = ((size_t)i * ny + j) * nz;
                const double *__restrict cc = cur + base;
                const double *__restrict cim = cur + base - si;
                const double *__restrict cip = cur + base + si;
                const double *__restrict cjm = cur + base - sj;
                const double *__restrict cjp = cur + base + sj;
                double *__restrict out = nxt + base;
#pragma omp simd
                for (int k = 1; k < nz - 1; ++k)
                    out[k] = c0 * cc[k]
                           + cw * (cim[k] + cip[k]
                                 + cjm[k] + cjp[k]
                                 + cc[k - 1] + cc[k + 1]);
            }
        }
        double *tmp = cur; cur = nxt; nxt = tmp;
    }

    /* Copy out in parallel too, for the same page-locality reason. */
#pragma omp parallel for schedule(static)
    for (int i = 0; i < nx; ++i) {
        const size_t off = (size_t)i * si;
        memcpy(u + off, cur + off, sizeof(double) * si);
    }

    free(cur); free(nxt);
}
