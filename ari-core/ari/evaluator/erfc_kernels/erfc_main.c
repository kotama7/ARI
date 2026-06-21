/* FROZEN driver for the erfc task. Reads whitespace-separated x values from the
 * file given as argv[1] and prints myerfc(x), one per line (%.17e). The agent
 * must NOT edit this file. Compiled with the candidate using identical flags. */
#include <stdio.h>
#include <stdlib.h>
#include "erfc_kernel.h"

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s <points.txt>\n", argv[0]); return 2; }
    FILE *f = fopen(argv[1], "r");
    if (!f) { perror("open points"); return 2; }
    double x;
    while (fscanf(f, "%lf", &x) == 1)
        printf("%.17e\n", myerfc(x));
    fclose(f);
    return 0;
}
