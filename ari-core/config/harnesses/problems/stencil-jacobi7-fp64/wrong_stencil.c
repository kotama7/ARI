/* PARITY PROBE, negative control 2: FAST but WRONG.
 *
 * Must fail on the ORACLE, not the ratio. Applies zero sweeps and hands back
 * the input field. It writes every element, so the NaN poison and the size
 * check both pass; the nt-scaled residual bound is what refuses it. Every
 * scored case has nt >= 1, so this is wrong by construction rather than by
 * accident.
 */
#include "stencil_kernel.h"
#include <string.h>

void jacobi(int nx, int ny, int nz, int nt,
            const double *u0, double *u) {
  (void)nt;
  memcpy(u, u0, sizeof(double) * (size_t)nx * (size_t)ny * (size_t)nz);
}
