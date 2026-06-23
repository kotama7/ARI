/* EDIT THIS FILE. Implement a balanced k-way graph partitioner that minimizes
 * the edge-cut (see meshpart_kernel.h for the contract).
 *
 * It starts as the poor round-robin baseline (perfectly balanced, but cut ~
 * random -> score ~ 0). Improve it: e.g. grow k balanced regions from seeds via
 * BFS, or bisect recursively, then refine the boundary (Kernighan-Lin / FM swaps)
 * to lower the cut while keeping max part size <= 1.05 * n/k.
 *
 * Iterate with the self-test: `make selftest && ./selftest` prints your edge-cut
 * and imbalance. Do NOT write main() (the harness provides it).
 */
#include "meshpart_kernel.h"

void partition(int n, int k, const int *xadj, const int *adjncy, int *part) {
    (void)xadj; (void)adjncy;
    for (int i = 0; i < n; i++) part[i] = i % k;
}
