/* FROZEN driver — do NOT edit. Reads a mesh (CSR) from argv[1] and prints the
 * partition (one label per line). Binary format, all int32 native-endian:
 *   header [n, k, m]   then   xadj[n+1]   then   adjncy[m]   (m = len(adjncy)).
 */
#include <stdio.h>
#include <stdlib.h>
#include "meshpart_kernel.h"

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s mesh.bin\n", argv[0]); return 2; }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror("open mesh"); return 2; }
    int hdr[3];
    if (fread(hdr, sizeof(int), 3, f) != 3) { fprintf(stderr, "bad header\n"); fclose(f); return 2; }
    int n = hdr[0], k = hdr[1], m = hdr[2];
    if (n <= 0 || k <= 0 || m < 0) { fprintf(stderr, "bad dims\n"); fclose(f); return 2; }
    int *xadj = (int *)malloc(sizeof(int) * (size_t)(n + 1));
    int *adjncy = (int *)malloc(sizeof(int) * (size_t)(m > 0 ? m : 1));
    int *part = (int *)calloc((size_t)n, sizeof(int));
    if (!xadj || !adjncy || !part) { fprintf(stderr, "oom\n"); return 2; }
    if (fread(xadj, sizeof(int), (size_t)(n + 1), f) != (size_t)(n + 1)) {
        fprintf(stderr, "bad xadj\n"); fclose(f); return 2;
    }
    if (m > 0 && fread(adjncy, sizeof(int), (size_t)m, f) != (size_t)m) {
        fprintf(stderr, "bad adjncy\n"); fclose(f); return 2;
    }
    fclose(f);
    partition(n, k, xadj, adjncy, part);
    for (int i = 0; i < n; i++) printf("%d\n", part[i]);
    free(xadj); free(adjncy); free(part);
    return 0;
}
