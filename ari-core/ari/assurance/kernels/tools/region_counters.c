/* PINNED INSTRUMENT. Content-addressed by the performance driver's digest
 * alongside the frozen scaffolding, because a counter tool that could change
 * under a pinned manifest would make every profile unattributable.
 *
 * Moved into ari-core so profiling survives the retirement of the prototype
 * workspace. The measurement it defines is unchanged; the history below is kept
 * because each defect it records is a way the numbers looked right and were not.
 */
/* Hardware counters for a marked region, on a machine that has no `perf`.
 *
 * WHY THIS EXISTS. A review objection is that asking an LLM to reflect without
 * profiling feedback is a poor design: with only end-to-end GF/s it can see THAT
 * a kernel is slow but not WHY, so "what to try next" is guesswork and every run
 * lands somewhere different. Measured mid-campaign, the paired within-seed
 * difference between arms had sd 0.12-0.41, several times any effect present --
 * that run-to-run variance is what a missing procedure produces.
 *
 * The objection is answerable here even though `perf` is not installed and no
 * module provides it. The PMU is still exposed (armv8_pmuv3_0 on the aarch64
 * compute nodes) and perf_event_open(2) works directly. What is missing is a
 * tool, not the counters.
 *
 * WHAT CHANGED, AND WHY IT HAD TO. v1 of this file counted the WHOLE CHILD
 * PROCESS -- fork, SIGSTOP, arm, SIGCONT, wait -- while its header claimed to
 * count "a region the caller marks". There was no marking mechanism at all. That
 * is not a naming quibble on this harness: the scored kernel call is ONE
 * statement, and around it in the same process sit a 134 MB read, a 134 MB
 * serial NaN-poison write and a 134 MB write-out. Measured on the same timed
 * region (0.122-0.123 s, 4 threads), adding an untimed prologue took the
 * reported count from 1.604 G to 3.157 G cycles -- +97% -- while the region
 * itself did not change. Every ratio v1 printed was a weighted average of the
 * kernel and its I/O, with the weight set by whatever the setup happened to
 * cost, so two candidates with identical kernels would receive different
 * "profiler feedback". Worse, the poison pass is pure write-allocate traffic, so
 * the L2D-refill ratios were pushed toward "memory bound" for every candidate.
 *
 * So the region is now real, and it is marked BY THE TARGET:
 *
 *   --gate   The parent hands the child two inherited pipe fds, named in
 *            ARI_COUNTER_GATE_FD (child -> parent) and ARI_COUNTER_ACK_FD
 *            (parent -> child). The target writes one byte when it is about to
 *            enter the region and then BLOCKS until the parent answers, so the
 *            counters are armed before the first instruction of the region
 *            rather than a few microseconds into it. It writes a second byte
 *            when the region ends. Measured here: parent wake-up is 4.2 us mean
 *            / 26.6 us worst, and only the CLOSING edge carries that lag -- on a
 *            161 ms region, under 0.02%.
 *
 * Without --gate the scope is the whole child process, which is still useful for
 * a standalone microbenchmark. The scope is PRINTED either way, because a
 * whole-process number labelled as a region number is the defect above.
 *
 * It reads a small, deliberately chosen set and reports the ratios an optimizer
 * acts on rather than raw counts:
 *
 *   IPC                    instructions per cycle
 *   L1D refill/access      how often an access leaves L1
 *   L2D refill / L1D       refill EVENTS per L1 line -- see the units note below;
 *                          it is not a "fraction reaching memory" and its
 *                          ceiling here is about 2, not 1
 *   L1 fill bytes/cycle    achieved traffic into L1, for bandwidth vs compute
 *   L2 refill bytes/cycle  the same on the L2 side, when its granule is known
 *
 * THREE MORE v1 DEFECTS, all of which made a wrong number look like a right one:
 *
 *   - A counter was called "ok" if its fd opened. An event the chip does not
 *     implement but the kernel accepts opens fine and reads 0 -- which is then
 *     printed as "no misses". Now every counter also carries time_enabled /
 *     time_running, and a counter that reads 0 while the region demonstrably ran
 *     is reported as SUSPECT rather than as zero.
 *   - read_format was 0, so five events sharing fewer PMU slots were multiplexed
 *     and silently under-reported. Now the scaling factor is computed AND
 *     printed; a heavily multiplexed run says so instead of quietly halving.
 *   - bytes/cycle hardcoded a 256-byte line in a file claiming to be
 *     architecture-neutral, AND applied it to the wrong counter. Measured on an
 *     aarch64 compute node by counting lines under a stride sweep
 *     (workspace/checkpoints/20260807_020000_cache_line_measure): the L1 line is
 *     256 B, but L2D_CACHE_REFILL ticks per 128 B granule, so the old formula
 *     reported roughly twice the traffic. The two units are now separate, each
 *     taken from the OS where it answers and SUPPRESSED rather than guessed
 *     where it does not.
 *
 * exclude_kernel is on by default, which drops page-fault handling. Pass
 * --include-kernel to count it; that needs a lower perf_event_paranoid on most
 * systems. Note the harness deliberately first-touches its buffers OUTSIDE the
 * timed region, so for a scored kernel there is little fault work to miss.
 *
 * ROOT IS NOT NEEDED, and neither is perf_event_paranoid=0: pid>=0 with cpu=-1
 * and exclude_kernel=1 is permitted at paranoid=2. (v1's comments said
 * otherwise; the requirement was overstated.)
 *
 * USAGE
 *   cc -O2 region_counters.c -o region_counters
 *   ./region_counters --self                    # self-test on a known loop
 *   ./region_counters -- <command ...>          # whole child process
 *   ./region_counters --gate -- <command ...>   # only the region it marks
 *   ./region_counters --json --gate -- <cmd>    # machine-readable
 *
 * The counter numbers are ARMv8 PMUv3 architectural events. On a chip that does
 * not implement one, that row reads as unavailable or suspect, never as zero,
 * because a silent zero would be read as "no misses".
 */
#define _GNU_SOURCE
#include <asm/unistd.h>
#include <dirent.h>
#include <errno.h>
#include <linux/perf_event.h>
#include <signal.h>
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

/* PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING */
struct ctr_read {
    uint64_t value;
    uint64_t time_enabled;
    uint64_t time_running;
};

struct ctr {
    const char *name;
    uint64_t config;
    int fd;
    struct ctr_read r;
    int opened;          /* the fd came back */
    int read_ok;         /* the read returned a full record */
};

static long perf_open(struct perf_event_attr *a, pid_t pid, int cpu, int grp,
                      unsigned long flags) {
    return syscall(__NR_perf_event_open, a, pid, cpu, grp, flags);
}

static int open_one(struct ctr *c, pid_t pid, int include_kernel) {
    struct perf_event_attr a;
    memset(&a, 0, sizeof(a));
    a.size = sizeof(a);
    a.type = PERF_TYPE_RAW;
    a.config = c->config;
    a.disabled = 1;
    a.inherit = 1;              /* follow threads: OpenMP kernels are the point */
    a.exclude_kernel = include_kernel ? 0 : 1;
    a.exclude_hv = 1;
    /* Without these two, multiplexing is invisible: five events sharing fewer
     * counters each run part of the time and read back a fraction of the truth,
     * with nothing in the output to say so. */
    a.read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
    c->fd = (int)perf_open(&a, pid, -1, -1, 0);
    c->opened = (c->fd >= 0);
    return c->opened;
}

/* The scaling perf applies when an event did not run for the whole window.
 * Returns 1.0 when it ran throughout, 0.0 when it never ran. */
static double ctr_scale(const struct ctr *c) {
    if (!c->read_ok || c->r.time_running == 0) return 0.0;
    if (c->r.time_running >= c->r.time_enabled) return 1.0;
    return (double)c->r.time_enabled / (double)c->r.time_running;
}

static double ctr_value(const struct ctr *c) {
    double s = ctr_scale(c);
    return s > 0.0 ? (double)c->r.value * s : 0.0;
}

/* A counter that reads zero while the region demonstrably ran is far more
 * likely to be an event this chip does not implement than a real absence of
 * the thing it counts. v1 printed it as zero, i.e. as "no misses". */
static int ctr_suspect(const struct ctr *c, int region_did_work) {
    return c->read_ok && c->r.time_running > 0 && c->r.value == 0 && region_did_work;
}

/* Cache line size from sysfs, for the level whose refills we are counting.
 * Returns 0 when it cannot be determined, and the caller then suppresses the
 * ratio rather than assuming a line size. */
static int coherency_line_size(int want_level) {
    char path[512];
    DIR *d = opendir("/sys/devices/system/cpu/cpu0/cache");
    if (!d) return 0;
    struct dirent *e;
    int found = 0;
    while ((e = readdir(d)) != NULL) {
        if (strncmp(e->d_name, "index", 5) != 0) continue;
        int level = 0, line = 0;
        FILE *f;
        snprintf(path, sizeof(path),
                 "/sys/devices/system/cpu/cpu0/cache/%s/level", e->d_name);
        if ((f = fopen(path, "r"))) { if (fscanf(f, "%d", &level) != 1) level = 0; fclose(f); }
        if (level != want_level) continue;
        snprintf(path, sizeof(path),
                 "/sys/devices/system/cpu/cpu0/cache/%s/coherency_line_size", e->d_name);
        if ((f = fopen(path, "r"))) { if (fscanf(f, "%d", &line) != 1) line = 0; fclose(f); }
        if (line > 0) { found = line; break; }
    }
    closedir(d);
    if (found) return found;
    /* sysfs is not universal -- the aarch64 compute nodes here publish no cache
     * directory at all. glibc still answers from the same place the kernel does,
     * so ask it before giving up. Still a MEASURED/reported value, never a
     * guess: if this is 0 too, the ratio is suppressed. */
#ifdef _SC_LEVEL1_DCACHE_LINESIZE
    if (want_level == 1) {
        long v = sysconf(_SC_LEVEL1_DCACHE_LINESIZE);
        if (v > 0) return (int)v;
    }
#endif
#ifdef _SC_LEVEL2_CACHE_LINESIZE
    if (want_level == 2) {
        long v = sysconf(_SC_LEVEL2_CACHE_LINESIZE);
        if (v > 0) return (int)v;
    }
#endif
    return 0;
}

static void usage(const char *me) {
    fprintf(stderr,
        "usage: %s [--gate] [--include-kernel] [--json] -- <command ...>\n"
        "       %s [--json] --self\n"
        "\n"
        "  --gate            count only the region the target marks. The target\n"
        "                    must write one byte to ARI_COUNTER_GATE_FD, read one\n"
        "                    byte from ARI_COUNTER_ACK_FD, run the region, then\n"
        "                    write one more byte. Without it the scope is the\n"
        "                    whole child process, which is printed as such.\n"
        "  --include-kernel  also count kernel mode (page faults); needs a lower\n"
        "                    perf_event_paranoid on most systems.\n"
        "  --line-bytes N    L1 data cache LINE size, if the OS will not say. Used\n"
        "                    for L1 fill bytes/cycle. For a MEASURED value only.\n"
        "  --l2-granule-bytes N\n"
        "                    the unit L2D_CACHE_REFILL ticks in. It is NOT the L1\n"
        "                    line: measured on the aarch64 compute nodes here it\n"
        "                    ticks per 128B, so passing the 256B line would double\n"
        "                    the traffic. Suppressed rather than guessed.\n", me, me);
}

int main(int argc, char **argv) {
    struct ctr ctrs[] = {
        {"cycles",      EV_CPU_CYCLES,       -1, {0,0,0}, 0, 0},
        {"instructions",EV_INST_RETIRED,     -1, {0,0,0}, 0, 0},
        {"l1d_access",  EV_L1D_CACHE,        -1, {0,0,0}, 0, 0},
        {"l1d_refill",  EV_L1D_CACHE_REFILL, -1, {0,0,0}, 0, 0},
        {"l2d_refill",  EV_L2D_CACHE_REFILL, -1, {0,0,0}, 0, 0},
    };
    const int N = (int)(sizeof(ctrs) / sizeof(ctrs[0]));

    int self = 0, gate = 0, include_kernel = 0, as_json = 0, line_opt = 0, l2_opt = 0;
    char **cmd = NULL;
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--self") == 0) self = 1;
        else if (strcmp(argv[i], "--gate") == 0) gate = 1;
        else if (strcmp(argv[i], "--include-kernel") == 0) include_kernel = 1;
        else if (strcmp(argv[i], "--json") == 0) as_json = 1;
        else if (strcmp(argv[i], "--line-bytes") == 0 && i + 1 < argc) line_opt = atoi(argv[++i]);
        else if (strcmp(argv[i], "--l2-granule-bytes") == 0 && i + 1 < argc) l2_opt = atoi(argv[++i]);
        else if (strcmp(argv[i], "--") == 0 && i + 1 < argc) { cmd = &argv[i + 1]; break; }
        else { usage(argv[0]); return 2; }
    }
    if (line_opt < 0 || l2_opt < 0) { usage(argv[0]); return 2; }
    if (!self && !cmd) { usage(argv[0]); return 2; }
    if (self && gate) {
        fprintf(stderr, "--gate needs a target to mark the region; not usable with --self\n");
        return 2;
    }

    int c2p[2] = {-1, -1}, p2c[2] = {-1, -1};
    if (gate && (pipe(c2p) != 0 || pipe(p2c) != 0)) { perror("pipe"); return 2; }

    pid_t child = 0;
    if (cmd) {
        child = fork();
        if (child < 0) { perror("fork"); return 2; }
        if (child == 0) {
            if (gate) {
                char buf[32];
                close(c2p[0]); close(p2c[1]);
                snprintf(buf, sizeof(buf), "%d", c2p[1]);
                setenv("ARI_COUNTER_GATE_FD", buf, 1);
                snprintf(buf, sizeof(buf), "%d", p2c[0]);
                setenv("ARI_COUNTER_ACK_FD", buf, 1);
            }
            /* Wait to be counted, then exec. Stopping ourselves lets the parent
             * open the counters before a single instruction of the target runs.
             * With --gate they are opened but stay DISABLED until the target
             * says the region has begun. */
            raise(SIGSTOP);
            execvp(cmd[0], cmd);
            perror("exec");
            _exit(127);
        }
        if (gate) { close(c2p[1]); close(p2c[0]); }
        int st; waitpid(child, &st, WUNTRACED);
    }

    int opened = 0;
    for (int i = 0; i < N; ++i) opened += open_one(&ctrs[i], cmd ? child : 0, include_kernel);
    if (!opened) {
        fprintf(stderr, "perf_event_open failed for every counter: %s\n"
                        "(no PMU exposed, or perf_event_paranoid too high for the\n"
                        " requested scope -- --include-kernel needs a lower value)\n",
                strerror(errno));
        if (child) kill(child, SIGKILL);
        return 3;
    }

    int gate_ok = 1;
    if (cmd && gate) {
        char b;
        kill(child, SIGCONT);
        /* EOF here means the target exited without marking. Reporting a
         * whole-process count as a region count is exactly the defect this
         * option exists to remove, so refuse instead of falling back. */
        ssize_t n = read(c2p[0], &b, 1);
        if (n != 1) {
            fprintf(stderr, "target did not mark a region start "
                            "(is it built with the gate protocol?)\n");
            gate_ok = 0;
        } else {
            for (int i = 0; i < N; ++i)
                if (ctrs[i].opened) { ioctl(ctrs[i].fd, PERF_EVENT_IOC_RESET, 0);
                                      ioctl(ctrs[i].fd, PERF_EVENT_IOC_ENABLE, 0); }
            b = 1;
            if (write(p2c[1], &b, 1) != 1) { perror("ack"); gate_ok = 0; }
            n = read(c2p[0], &b, 1);          /* region end */
            for (int i = 0; i < N; ++i)
                if (ctrs[i].opened) ioctl(ctrs[i].fd, PERF_EVENT_IOC_DISABLE, 0);
            if (n != 1) {
                fprintf(stderr, "target did not mark a region end\n");
                gate_ok = 0;
            }
        }
        int st; waitpid(child, &st, 0);
        if (!gate_ok) { for (int i = 0; i < N; ++i) if (ctrs[i].opened) close(ctrs[i].fd); return 4; }
    } else {
        for (int i = 0; i < N; ++i)
            if (ctrs[i].opened) { ioctl(ctrs[i].fd, PERF_EVENT_IOC_RESET, 0);
                                  ioctl(ctrs[i].fd, PERF_EVENT_IOC_ENABLE, 0); }
        if (cmd) {
            kill(child, SIGCONT);
            int st; waitpid(child, &st, 0);
        } else {
            /* --self: a loop with a known character, so a wrong reading is
             * visible. The bracket spans the allocation and the init pass too,
             * which is why this is a smoke test and not a measurement. */
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
            if (ctrs[i].opened) ioctl(ctrs[i].fd, PERF_EVENT_IOC_DISABLE, 0);
    }

    for (int i = 0; i < N; ++i)
        if (ctrs[i].opened) {
            ssize_t got = read(ctrs[i].fd, &ctrs[i].r, sizeof(ctrs[i].r));
            ctrs[i].read_ok = (got == (ssize_t)sizeof(ctrs[i].r));
            close(ctrs[i].fd);
        }

    const char *scope = gate ? "marked region" : (cmd ? "whole child process" : "self-test");
    double cyc = ctr_value(&ctrs[0]);
    int did_work = (ctrs[0].read_ok && ctrs[0].r.value > 0);

    /* THE CYCLE COUNTER READING ZERO IS NOT A MEASUREMENT. These are raw ARMv8
     * PMUv3 encodings; on another vendor's PMU the same numbers are accepted by
     * perf_event_open and count something else, or nothing. Running this on the
     * x86 submit node returns 0 for all five and every ratio is then suppressed
     * -- which prints as a clean, empty, successful result. A region that
     * demonstrably executed cannot have burned zero cycles, so say so and fail,
     * rather than let "no counters" read as "nothing to report". */
    if (ctrs[0].opened && ctrs[0].read_ok && ctrs[0].r.time_running > 0
        && ctrs[0].r.value == 0) {
        fprintf(stderr,
            "cycles read 0 over a region that ran: these are raw ARMv8 PMUv3\n"
            "event encodings and this CPU is not counting them. Run this on the\n"
            "node class the measurement runs on; a zero here is a wrong tool,\n"
            "not a fast kernel.\n");
        return 5;
    }
    double ins = ctr_value(&ctrs[1]);
    double acc = ctr_value(&ctrs[2]);
    double r1  = ctr_value(&ctrs[3]);
    double r2  = ctr_value(&ctrs[4]);
    /* TWO UNITS, because the two counters do not tick in the same one. Measured
     * on an aarch64 compute node by counting lines under a stride sweep
     * (workspace/checkpoints/20260807_020000_cache_line_measure):
     *
     *   L1D_CACHE_REFILL ticks per L1 LINE. The knee in refills-per-access sits
     *   at 256 B: only that value keeps refills/(footprint/max(S,L)) >= 1 at
     *   every stride and inside one narrow band. It is a clean per-thread
     *   counter -- it reproduced to 0.004% with seven neighbours thrashing.
     *
     *   L2D_CACHE_REFILL does NOT tick per L1 line. Against the same data it
     *   reads ~2.0 per L1 line when both 128 B halves are demanded (stride <=
     *   128), ~1.0 when one is (stride >= 512), and 1.47 at stride 256 where
     *   consecutive lines let the streamer complete whole lines. So it ticks per
     *   128 B GRANULE, plus prefetch. Feeding it the L1 line size doubles the
     *   traffic it reports, which is what this file used to do.
     *
     * The L1 line comes from the OS where it answers (this machine reports the
     * L1 line and nothing else -- every capacity reads 0 and sysfs is empty).
     * The L2 granule has no OS source here, so it is suppressed unless supplied.
     * Which source was used travels in the output.
     */
    int line = line_opt > 0 ? line_opt : coherency_line_size(1);
    const char *line_src = line <= 0 ? "unknown"
                          : (line_opt > 0 ? "caller" : "os");
    int l2g = l2_opt > 0 ? l2_opt : coherency_line_size(2);
    const char *l2g_src = l2g <= 0 ? "unknown"
                          : (l2_opt > 0 ? "caller" : "os");

    /* The largest scaling factor across the set: 1.0 means nothing was
     * multiplexed, 2.0 means an event ran half the time and its count has been
     * doubled to compensate. Printed, because a compensated count is an
     * estimate and the reader is entitled to know how much of one. */
    double worst_scale = 1.0;
    for (int i = 0; i < N; ++i) {
        double s = ctr_scale(&ctrs[i]);
        if (s > worst_scale) worst_scale = s;
    }

    if (as_json) {
        printf("{\"scope\":\"%s\",\"include_kernel\":%s,\"multiplex_scale\":%.4f,"
               "\"l1_line_bytes\":%d,\"l1_line_source\":\"%s\","
               "\"l2_granule_bytes\":%d,\"l2_granule_source\":\"%s\",\"counters\":{", scope,
               include_kernel ? "true" : "false", worst_scale,
               line, line_src, l2g, l2g_src);
        for (int i = 0; i < N; ++i) {
            printf("%s\"%s\":", i ? "," : "", ctrs[i].name);
            if (!ctrs[i].opened || !ctrs[i].read_ok) printf("null");
            else printf("{\"value\":%.0f,\"raw\":%llu,\"scale\":%.4f,\"suspect\":%s}",
                        ctr_value(&ctrs[i]),
                        (unsigned long long)ctrs[i].r.value, ctr_scale(&ctrs[i]),
                        ctr_suspect(&ctrs[i], did_work) ? "true" : "false");
        }
        printf("},\"ratios\":{");
        int first = 1;
        if (cyc > 0 && ins > 0) { printf("%s\"ipc\":%.4f", first ? "" : ",", ins / cyc); first = 0; }
        if (acc > 0 && r1 > 0)  { printf("%s\"l1d_refill_per_access\":%.6f", first ? "" : ",", r1 / acc); first = 0; }
        if (r1 > 0 && r2 > 0)   { printf("%s\"l2d_refill_per_l1d_refill\":%.6f", first ? "" : ",", r2 / r1); first = 0; }
        if (cyc > 0 && r1 > 0 && line > 0)
                                { printf("%s\"l1_fill_bytes_per_cycle\":%.4f", first ? "" : ",", (double)line * r1 / cyc); first = 0; }
        if (cyc > 0 && r2 > 0 && l2g > 0)
                                { printf("%s\"l2_refill_bytes_per_cycle\":%.4f", first ? "" : ",", (double)l2g * r2 / cyc); }
        printf("}}\n");
        return 0;
    }

    printf("scope          %s%s\n", scope, include_kernel ? " (kernel mode included)" : "");
    if (worst_scale > 1.0001)
        printf("multiplexing   counts scaled by up to %.3fx -- an estimate, not a count\n",
               worst_scale);
    for (int i = 0; i < N; ++i) {
        if (!ctrs[i].opened) { printf("%-14s UNAVAILABLE (perf_event_open refused it)\n", ctrs[i].name); continue; }
        if (!ctrs[i].read_ok) { printf("%-14s UNAVAILABLE (short read)\n", ctrs[i].name); continue; }
        if (ctrs[i].r.time_running == 0) { printf("%-14s UNAVAILABLE (never scheduled)\n", ctrs[i].name); continue; }
        if (ctr_suspect(&ctrs[i], did_work)) {
            printf("%-14s SUSPECT 0 -- the region ran, so this is far more likely an\n"
                   "%-14s event this chip does not implement than an absence\n",
                   ctrs[i].name, "");
            continue;
        }
        printf("%-14s %.0f\n", ctrs[i].name, ctr_value(&ctrs[i]));
    }

    /* The ratios an optimizer acts on. A missing counter suppresses its ratio
     * rather than printing a plausible wrong one. */
    puts("");
    if (cyc > 0 && ins > 0) printf("IPC                  %.3f\n", ins / cyc);
    if (acc > 0 && r1 > 0)  printf("L1D refill / access  %.4f\n", r1 / acc);
    /* NOT a "fraction reaching memory": measured here, this reads ~2 when both
     * 128 B halves of an L1 line move and ~1 when one does, so its ceiling is 2.
     * It is refill EVENTS per L1 line, and it is useful as a relative number. */
    if (r1  > 0 && r2 > 0)  printf("L2D refill / L1D     %.4f  (events per L1 line; ~2 = both "
                                   "128B halves moved, ~1 = one)\n", r2 / r1);
    if (cyc > 0 && r1 > 0) {
        if (line > 0) printf("L1 fill bytes/cycle  %.3f   (%dB line, from %s)\n",
                             (double)line * r1 / cyc, line, line_src);
        else puts("L1 fill bytes/cycle  suppressed: no L1 line size from the OS and none\n"
                  "                     supplied; guessing one would fabricate traffic");
    }
    if (cyc > 0 && r2 > 0) {
        if (l2g > 0) printf("L2 refill bytes/cycle %.3f  (%dB granule, from %s)\n",
                            (double)l2g * r2 / cyc, l2g, l2g_src);
        else puts("L2 refill bytes/cycle suppressed: the L2 refill GRANULE has no OS source\n"
                  "                     here and is not the L1 line -- measured, this counter\n"
                  "                     ticks per 128B. Pass --l2-granule-bytes to enable it.");
    }
    return 0;
}
