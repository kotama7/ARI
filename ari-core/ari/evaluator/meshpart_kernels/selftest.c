/* Local self-test — reports your partition's edge-cut and imbalance on a SEEDED
 * mesh (NOT the hidden mesh the evaluator scores you on, so you cannot hardcode).
 * Lower edge-cut at imbalance <= 1.05 is better. Run: make selftest && ./selftest
 */
#include <stdio.h>
#include <stdlib.h>
#include "meshpart_kernel.h"

int main(void) {
    FILE *f = fopen("selftest_mesh.bin", "rb");
    if (!f) { fprintf(stderr, "selftest_mesh.bin not found (work dir not seeded)\n"); return 2; }
    int hdr[3];
    if (fread(hdr, sizeof(int), 3, f) != 3) { fprintf(stderr, "bad header\n"); fclose(f); return 2; }
    int n = hdr[0], k = hdr[1], m = hdr[2];
    int *xadj = (int *)malloc(sizeof(int) * (size_t)(n + 1));
    int *adjncy = (int *)malloc(sizeof(int) * (size_t)(m > 0 ? m : 1));
    int *part = (int *)calloc((size_t)n, sizeof(int));
    if (!xadj || !adjncy || !part) { fprintf(stderr, "oom\n"); return 2; }
    if (fread(xadj, sizeof(int), (size_t)(n + 1), f) != (size_t)(n + 1)) { fclose(f); return 2; }
    if (m > 0 && fread(adjncy, sizeof(int), (size_t)m, f) != (size_t)m) { fclose(f); return 2; }
    fclose(f);
    partition(n, k, xadj, adjncy, part);
    for (int i = 0; i < n; i++) {
        if (part[i] < 0 || part[i] >= k) {
            printf("SELFTEST: INVALID label %d at vertex %d (must be 0..%d)\n", part[i], i, k - 1);
            return 1;
        }
    }
    long cut = 0, edges = 0;
    for (int i = 0; i < n; i++)
        for (int e = xadj[i]; e < xadj[i + 1]; e++) {
            int j = adjncy[e];
            if (j > i) { edges++; if (part[i] != part[j]) cut++; }
        }
    int *sz = (int *)calloc((size_t)k, sizeof(int));
    for (int i = 0; i < n; i++) sz[part[i]]++;
    int mx = 0;
    for (int p = 0; p < k; p++) if (sz[p] > mx) mx = sz[p];
    double imb = (double)mx / ((double)n / k);
    printf("self-test mesh: n=%d k=%d edges=%ld\n", n, k, edges);
    printf("part sizes:");
    for (int p = 0; p < k; p++) printf(" %d", sz[p]);
    printf("\nedge_cut=%ld  imbalance=%.3f  (target imbalance <= 1.05)\n", cut, imb);
    if (imb <= 1.05)
        printf("SELFTEST: balanced OK — now lower edge_cut further (currently %ld).\n", cut);
    else
        printf("SELFTEST: IMBALANCED (%.3f > 1.05) — rebalance before chasing cut.\n", imb);
    free(xadj); free(adjncy); free(part); free(sz);
    return 0;
}
