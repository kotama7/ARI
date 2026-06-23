/* FROZEN poor baseline — round-robin labels. Perfectly balanced but ignores the
 * graph structure entirely, so its edge-cut is roughly that of a RANDOM partition
 * (score ~ 0). Beat it by clustering graph-adjacent vertices into the same part.
 */
#include "meshpart_kernel.h"

void partition(int n, int k, const int *xadj, const int *adjncy, int *part) {
    (void)xadj; (void)adjncy;
    for (int i = 0; i < n; i++) part[i] = i % k;
}
