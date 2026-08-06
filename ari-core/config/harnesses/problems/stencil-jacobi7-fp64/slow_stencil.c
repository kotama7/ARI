/* PARITY PROBE, negative control 1: CORRECT but SLOW.
 *
 * Must fail on the RATIO. Textbook naive ijk sweep, single-threaded, with a
 * ping-pong buffer initialised by one thread -- which also places every page on
 * the master's NUMA domain, against a reference that first-touches in parallel.
 */
#include "stencil_kernel.h"
#include <stdlib.h>
#include <string.h>

void jacobi(int nx, int ny, int nz, int nt,
            const double *u0, double *u) {
  const double c0 = 0.5, cw = 1.0 / 12.0;
  const size_t N = (size_t)nx * (size_t)ny * (size_t)nz;
  double *a = (double *)malloc(sizeof(double) * N);
  double *b = (double *)malloc(sizeof(double) * N);
  if (!a || !b) { free(a); free(b); return; }
  memcpy(a, u0, sizeof(double) * N);
  memcpy(b, u0, sizeof(double) * N);
  for (int t = 0; t < nt; ++t) {
    for (int i = 1; i < nx - 1; ++i)
      for (int j = 1; j < ny - 1; ++j)
        for (int kk = 1; kk < nz - 1; ++kk) {
          const size_t c = ((size_t)i * ny + j) * nz + kk;
          b[c] = c0 * a[c]
               + cw * (a[c - (size_t)ny * nz] + a[c + (size_t)ny * nz]
                     + a[c - nz] + a[c + nz]
                     + a[c - 1] + a[c + 1]);
        }
    double *tmp = a; a = b; b = tmp;
  }
  memcpy(u, a, sizeof(double) * N);
  free(a); free(b);
}
