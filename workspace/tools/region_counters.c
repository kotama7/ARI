/* Hardware counters around a region, on a machine that has no `perf`.
 *
 * WHY THIS EXISTS. A review objection is that asking an LLM to reflect without
 * profiling feedback is a poor design: with only end-to-end GF/s it can see THAT
 * a kernel is slow but not WHY, so "what to try next" is guesswork and every run
 * lands somewhere different. Measured mid-campaign, the paired within-seed
 * difference between arms had sd 0.12-0.41, several times any effect present --
 * that run-to-run variance is what a missing procedure produces.
 *
 * The objection is answerable here even though `perf` is not installed and no
 * module provides it (checked on a compute node with the vendor entry module
 * loaded; no perf, PAPI or likwid module exists). The PMU is still exposed as
 * armv8_pmuv3_0 and perf_event_paranoid is 0, so perf_event_open(2) works
 * directly -- the same route that measures the core clock at 1.9984 GHz here.
 * What is missing is a tool, not the counters.
 *
 * This reads a small, deliberately chosen set around a region the caller marks,
 * and reports the ratios an optimizer actually acts on rather than raw counts:
 *
 *   IPC                instructions per cycle
 *   L1D refill/access  how often an access leaves L1
 *   L2D refill rate    how often it leaves L2 as well, i.e. goes to memory
 *   bytes/cycle        achieved traffic, for deciding bandwidth vs compute bound
 *
 * USAGE
 *   cc -O2 region_counters.c -o region_counters
 *   ./region_counters -- <command ...>      # counts the child
 *   ./region_counters --self                # self-test on a known loop
 *
 * The counter numbers are ARMv8 PMUv3 architectural events, so this is not
 * A64FX-specific; on a chip that does not implement one, that row reads as
 * unavailable rather than as zero, because a silent zero would be read as "no
 * misses".
 */
#define _GNU_SOURCE
#include <asm/unistd.h>
#include <errno.h>
#include <linux/perf_event.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <unistd.h>

/* ARMv8 PMUv3 architectural event numbers. */
#define EV_CPU_CYCLES       0x11
#define EV_INST_RETIRED     0x08
#define EV_L1D_CACHE        0x04
#define EV_L1D_CACHE_REFILL 0x03
#define EV_L2D_CACHE_REFILL 0x17

struct ctr {
    const char *name;
    uint64_t config;
    int fd;
    uint64_t value;
    int ok;
};

static long perf_open(struct perf_event_attr *a, pid_t pid, int cpu, int grp,
                      unsigned long flags) {
    return syscall(__NR_perf_event_open, a, pid, cpu, grp, flags);
}

static int open_one(struct ctr *c, pid_t pid) {
    struct perf_event_attr a;
    memset(&a, 0, sizeof(a));
    a.size = sizeof(a);
    a.type = PERF_TYPE_RAW;
    a.config = c->config;
    a.disabled = 1;
    a.inherit = 1;              /* follow threads: OpenMP kernels are the point */
    a.exclude_kernel = 1;
    a.exclude_hv = 1;
    c->fd = (int)perf_open(&a, pid, -1, -1, 0);
    c->ok = (c->fd >= 0);
    return c->ok;
}

int main(int argc, char **argv) {
    struct ctr ctrs[] = {
        {"cycles",      EV_CPU_CYCLES,       -1, 0, 0},
        {"instructions",EV_INST_RETIRED,     -1, 0, 0},
        {"l1d_access",  EV_L1D_CACHE,        -1, 0, 0},
        {"l1d_refill",  EV_L1D_CACHE_REFILL, -1, 0, 0},
        {"l2d_refill",  EV_L2D_CACHE_REFILL, -1, 0, 0},
    };
    const int N = (int)(sizeof(ctrs) / sizeof(ctrs[0]));

    int self = (argc > 1 && strcmp(argv[1], "--self") == 0);
    char **cmd = NULL;
    for (int i = 1; i < argc; ++i)
        if (strcmp(argv[i], "--") == 0 && i + 1 < argc) { cmd = &argv[i + 1]; break; }
    if (!self && !cmd) {
        fprintf(stderr, "usage: %s --self | %s -- <command ...>\n", argv[0], argv[0]);
        return 2;
    }

    pid_t child = 0;
    if (cmd) {
        child = fork();
        if (child < 0) { perror("fork"); return 2; }
        if (child == 0) {
            /* Wait to be counted, then exec. Stopping ourselves lets the parent
             * arm the counters before a single instruction of the target runs. */
            raise(SIGSTOP);
            execvp(cmd[0], cmd);
            perror("exec");
            _exit(127);
        }
        int st; waitpid(child, &st, WUNTRACED);
    }

    int opened = 0;
    for (int i = 0; i < N; ++i) opened += open_one(&ctrs[i], cmd ? child : 0);
    if (!opened) {
        fprintf(stderr, "perf_event_open failed for every counter: %s\n"
                        "(perf_event_paranoid too high, or no PMU exposed)\n",
                strerror(errno));
        if (child) kill(child, SIGKILL);
        return 3;
    }

    for (int i = 0; i < N; ++i)
        if (ctrs[i].ok) { ioctl(ctrs[i].fd, PERF_EVENT_IOC_RESET, 0);
                          ioctl(ctrs[i].fd, PERF_EVENT_IOC_ENABLE, 0); }

    if (cmd) {
        kill(child, SIGCONT);
        int st; waitpid(child, &st, 0);
    } else {
        /* --self: a loop with a known character, so a wrong reading is visible. */
        const size_t n = 1u << 22;
        double *a = malloc(n * sizeof(double));
        for (size_t i = 0; i < n; ++i) a[i] = (double)i;
        double s = 0.0;
        for (int r = 0; r < 8; ++r)
            for (size_t i = 0; i < n; ++i) s += a[i];
        fprintf(stderr, "self-test sink %.1f\n", s);
        free(a);
    }

    for (int i = 0; i < N; ++i)
        if (ctrs[i].ok) {
            ioctl(ctrs[i].fd, PERF_EVENT_IOC_DISABLE, 0);
            if (read(ctrs[i].fd, &ctrs[i].value, sizeof(uint64_t)) != sizeof(uint64_t))
                ctrs[i].ok = 0;
            close(ctrs[i].fd);
        }

    for (int i = 0; i < N; ++i)
        printf("%-14s %s\n", ctrs[i].name,
               ctrs[i].ok ? "" : "UNAVAILABLE (event not implemented here)");
    for (int i = 0; i < N; ++i)
        if (ctrs[i].ok) printf("%-14s %llu\n", ctrs[i].name,
                               (unsigned long long)ctrs[i].value);

    /* The ratios an optimizer acts on. A missing counter suppresses its ratio
     * rather than printing a plausible wrong one. */
    double cyc = ctrs[0].ok ? (double)ctrs[0].value : 0;
    double ins = ctrs[1].ok ? (double)ctrs[1].value : 0;
    double acc = ctrs[2].ok ? (double)ctrs[2].value : 0;
    double r1  = ctrs[3].ok ? (double)ctrs[3].value : 0;
    double r2  = ctrs[4].ok ? (double)ctrs[4].value : 0;
    puts("");
    if (cyc > 0 && ins > 0) printf("IPC                  %.3f\n", ins / cyc);
    if (acc > 0 && r1 > 0)  printf("L1D refill / access  %.4f\n", r1 / acc);
    if (r1  > 0 && r2 > 0)  printf("L2D refill / L1D     %.4f  (fraction reaching memory)\n", r2 / r1);
    if (cyc > 0 && r2 > 0)  printf("bytes/cycle (256B)   %.3f\n", 256.0 * r2 / cyc);
    return 0;
}
