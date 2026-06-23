#ifndef MESHPART_KERNEL_H
#define MESHPART_KERNEL_H
/* Balanced k-way graph partitioning (handoff study task C).
 *
 * Partition the n graph vertices into k parts so as to MINIMIZE the number of
 * cut edges (edges whose two endpoints land in different parts) while keeping
 * the parts BALANCED: max part size must stay <= 1.05 * (n / k).
 *
 * The graph is undirected and given in CSR adjacency form:
 *   - xadj has length n+1.
 *   - vertex i's neighbors are adjncy[xadj[i] .. xadj[i+1]-1].
 *   - every edge appears in both endpoints' lists.
 * Write each vertex's part label (an integer in 0..k-1) into part[0..n-1].
 *
 * Do NOT write main() — the harness provides it. You MAY use <stdlib.h> and
 * <math.h>. No external libraries (no METIS/Scotch); implement it yourself.
 */
void partition(int n, int k, const int *xadj, const int *adjncy, int *part);
#endif
