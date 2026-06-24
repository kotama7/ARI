/* Local self-test. ALWAYS run it via `make check`, which RECOMPILES this test
 * against your CURRENT candidate_meshpart.c and runs it in one step — never run a
 * stale `./selftest` binary, or you will see an OLD partition's numbers.
 *
 * It runs on a SEEDED mesh (NOT the hidden mesh the evaluator scores you on, so
 * you cannot hardcode) and reports your partition's edge-cut and imbalance, plus
 * two reference points ON THE SAME MESH: the random-partition cut (the baseline
 * you must beat) and a graph-aware BFS-block cut (a good, reachable target).
 * Lower edge-cut at imbalance <= 1.05 is better.
 */
#include <stdio.h>
#include <stdlib.h>
#include "meshpart_kernel.h"

static long cut_of(const int *part, int n, const int *xadj, const int *adjncy) {
    long cut = 0;
    for (int i = 0; i < n; i++)
        for (int e = xadj[i]; e < xadj[i + 1]; e++) {
            int j = adjncy[e];
            if (j > i && part[i] != part[j]) cut++;
        }
    return cut;
}

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

    /* your candidate */
    partition(n, k, xadj, adjncy, part);
    for (int i = 0; i < n; i++)
        if (part[i] < 0 || part[i] >= k) {
            printf("SELFTEST: INVALID label %d at vertex %d (must be 0..%d)\n", part[i], i, k - 1);
            return 1;
        }
    long cut = cut_of(part, n, xadj, adjncy);
    int *sz = (int *)calloc((size_t)k, sizeof(int));
    for (int i = 0; i < n; i++) sz[part[i]]++;
    int mx = 0;
    for (int p = 0; p < k; p++) if (sz[p] > mx) mx = sz[p];
    double imb = (double)mx / ((double)n / k);

    /* random baseline on this mesh (the cut you must beat) */
    int *rp = (int *)malloc(sizeof(int) * (size_t)n);
    srand(12345);
    for (int i = 0; i < n; i++) rp[i] = rand() % k;
    long rand_cut = cut_of(rp, n, xadj, adjncy);

    /* graph-aware reference: BFS order -> equal contiguous blocks (a good,
     * reachable target far below random — clusters graph-neighbors together) */
    int *order = (int *)malloc(sizeof(int) * (size_t)n);
    char *seen = (char *)calloc((size_t)n, 1);
    int *q = (int *)malloc(sizeof(int) * (size_t)n);
    int qh = 0, qt = 0, oi = 0;
    for (int s = 0; s < n; s++) {
        if (seen[s]) continue;
        seen[s] = 1; q[qt++] = s;
        while (qh < qt) {
            int u = q[qh++]; order[oi++] = u;
            for (int e = xadj[u]; e < xadj[u + 1]; e++) { int v = adjncy[e]; if (!seen[v]) { seen[v] = 1; q[qt++] = v; } }
        }
    }
    int *bp = (int *)malloc(sizeof(int) * (size_t)n);
    int per = (n + k - 1) / k;
    for (int i = 0; i < n; i++) { int p = i / per; bp[order[i]] = p < k ? p : k - 1; }
    long ref_cut = cut_of(bp, n, xadj, adjncy);

    printf("self-test mesh: n=%d k=%d edges=%d\n", n, k, m / 2);
    printf("part sizes:");
    for (int p = 0; p < k; p++) printf(" %d", sz[p]);
    printf("\nYOUR edge_cut=%ld  imbalance=%.3f  (need imbalance <= 1.05)\n", cut, imb);
    printf("on this mesh:  random_cut=%ld   good_reference_cut=%ld\n", rand_cut, ref_cut);
    if (imb > 1.05)
        printf("SELFTEST: IMBALANCED (%.3f > 1.05) — rebalance before chasing cut.\n", imb);
    else if (cut >= rand_cut)
        printf("SELFTEST: balanced, but edge_cut (%ld) is NOT better than random (%ld) — "
               "your partition must put GRAPH-NEIGHBORS in the SAME part; aim toward %ld.\n",
               cut, rand_cut, ref_cut);
    else
        printf("SELFTEST: balanced and below random — keep lowering edge_cut toward %ld and beyond.\n", ref_cut);

    free(xadj); free(adjncy); free(part); free(sz);
    free(rp); free(order); free(seen); free(q); free(bp);
    return 0;
}
