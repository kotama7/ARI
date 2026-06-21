#include "erfc_kernel.h"
#include <math.h>

/* CANDIDATE — the file you edit. Seeded identical to the poor baseline. It uses a
 * tiny-x Taylor series for erf and is only roughly accurate very near 0 — wrong
 * in the mid range and catastrophically wrong in the tail. The agent must
 * replace it with proper per-regime numerics (series near 0, asymptotic /
 * continued fraction for large x). Do not edit this baseline file. */
double myerfc(double x)
{
    const double two_over_sqrt_pi = 1.1283791670955126;
    /* erf(x) ~ (2/sqrt(pi)) (x - x^3/3 + x^5/10 - x^7/42)  -- only valid near 0 */
    double x2 = x * x;
    double erf_approx = two_over_sqrt_pi * (x - x2 * x / 3.0
                        + x2 * x2 * x / 10.0 - x2 * x2 * x2 * x / 42.0);
    if (erf_approx > 1.0) erf_approx = 1.0;
    if (erf_approx < -1.0) erf_approx = -1.0;
    return 1.0 - erf_approx;
}
