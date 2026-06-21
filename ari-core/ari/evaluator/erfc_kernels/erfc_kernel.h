#ifndef ERFC_KERNEL_H
#define ERFC_KERNEL_H

/* The contract the candidate must keep EXACTLY.
 *
 *   double myerfc(double x);   == erfc(x) = 1 - erf(x)
 *
 * Target: relative error < 1e-9 vs the true erfc for x in [-5, 26].
 * You MAY use <math.h> for exp, log, fabs, sqrt, pow, etc., but you MUST NOT
 * call erf, erfc, erff, or erfcf (implement the numerics yourself).
 *
 * The domain spans several regimes that each need a different approximation:
 *   - near 0: a series / rational approximation of erf,
 *   - large x: erfc is tiny (down to ~1e-296) and 1-erf cancels catastrophically,
 *     so use an asymptotic expansion or continued fraction there.
 * Edit only candidate_erfc.c. */
double myerfc(double x);

#endif /* ERFC_KERNEL_H */
