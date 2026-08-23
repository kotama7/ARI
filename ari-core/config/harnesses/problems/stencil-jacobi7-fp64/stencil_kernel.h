#ifndef STENCIL_KERNEL_H
#define STENCIL_KERNEL_H

/* The contract the candidate must keep EXACTLY.
 *
 *   3-D 7-point Jacobi stencil, fp64, row-major.
 *     Field u has dims nx x ny x nz; element (i,j,k) lives at
 *     index ((long)i*ny + j)*nz + k.
 *     One sweep updates every INTERIOR point (1<=i<nx-1, 1<=j<ny-1, 1<=k<nz-1):
 *       u_new[i,j,k] = c0*u[i,j,k]
 *                    + cw*( u[i-1,j,k] + u[i+1,j,k]
 *                         + u[i,j-1,k] + u[i,j+1,k]
 *                         + u[i,j,k-1] + u[i,j,k+1] )
 *     with c0 = 0.5 and cw = 1.0/12.0 (the 7 weights sum to 1).
 *     BOUNDARY planes (any index on a face) are FIXED (Dirichlet): they keep
 *     their u0 value for all sweeps.
 *     Apply nt sweeps to the input field u0 and write the final field into u.
 *
 * Edit only candidate_stencil.c (this function's body). Do not change the
 * signature. The kernel MAY allocate its own scratch (e.g. a ping-pong buffer).
 * Correctness is checked against an fp64 reference with an nt-scaled epsilon
 * (FP reassociation of the 6-neighbour sum is allowed; dropping terms, changing
 * the coefficients, or precomputing the answer is NOT). */
void jacobi(int nx, int ny, int nz, int nt,
            const double *u0, double *u);

#endif /* STENCIL_KERNEL_H */
