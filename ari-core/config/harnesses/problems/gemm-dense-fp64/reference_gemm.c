/* PINNED SCAFFOLDING. This file is content-addressed by the harness manifest
 * (ari-core/config/harnesses/builtin/hpc_gemm_performance.yaml) and verified
 * before any measurement runs; a modified byte refuses to measure rather than
 * measuring differently.
 *
 * It moved into ari-core so a registered performance harness no longer depends
 * on a workspace directory being present. The measurement it defines is
 * unchanged: one cold timed call per process, the output poisoned to NaN so a
 * kernel that does not write it fails the oracle, and the OpenMP team created
 * before the timer so team setup is not charged to the kernel.
 */
/* FROZEN REFERENCE GEMM — the score denominator. Do not edit.
 *
 * v2 replaces v1's naive single-threaded ijl kernel with a COMPETENT reference.
 * The reason is measured, not stylistic. Against the naive kernel the objective
 * had a hard ceiling that compressed the whole in-contract range: at 512^3 the
 * median agent candidate scored 81.3 against a best-known rung of 95.51 and an
 * unreachable ceiling of 111, i.e. 1.17x of room, so "did the search find a
 * better kernel" was below the measurement band. Scoring against THIS reference
 * at the v2 problem size opens that range to 2.86x.
 *
 * WHAT THIS IS. Register blocking over i with MR=4 accumulator rows, keeping the
 * j loop long and unit-stride so the compiler can still vectorise it. B traffic
 * is n*p*m*8/MR bytes against a plain ikj kernel's n*p*m*8 — a 4x reduction.
 * MR=4 is the measured optimum, not a guess: a correctly written 8-row body
 * measured 0.77-0.85x of this, because 8 accumulator rows need 8*NC*8 B of L1
 * and evict the B stream they are supposed to amortise.
 * Compiled with _REFERENCE_CFLAGS, which adds SVE.
 *
 * WHY THIS SHAPE AND NOT A FULLY UNROLLED REGISTER TILE. gcc 8.5 vectorises
 * long, contiguous, unit-stride inner loops well but does NOT vectorise a fully
 * unrolled register tile — objdump of such a rung shows it keeping 159 NEON
 * operands and only 8 z operands even with +sve. Two hand-blocked rungs written
 * that way measured BELOW a plain vectorised kernel at both problem sizes, and
 * got worse as the problem grew. That is a property of those implementations,
 * not of blocking: this independently written kernel beats the plain vectorised
 * one by 1.29x once the working set leaves the 8 MiB CMG L2.
 *
 * IT IS IN CONTRACT, DELIBERATELY. Plain C, OpenMP, and one compile flag — no
 * intrinsics, no assembly, nothing an agent is forbidden from writing. The
 * agent is not asked to beat something it could not have produced. It is also
 * not a strawman: at the v2 problem sizes this runs 374-389 GF/s, against the
 * out-of-contract vendor DGEMM's 1867 GF/s. How much of that remaining factor
 * is reachable in plain C is NOT known — an FMA microbenchmark was tried as a
 * ceiling estimate and returned 70 GF/s under gcc and 200 under clang, i.e.
 * BELOW the real kernels, so it was latency-bound and measured nothing useful.
 * Do not cite a plain-C ceiling here until one is actually measured.
 *
 * The toolchain is NOT what limits this: clang 20 compiles the same sources to
 * within 1% of gcc 8.5 on every scored shape (385.9/393.8/222.1 against
 * 388.9/394.1/223.3), so switching compilers would not widen the objective.
 *
 * THREE STRUCTURAL IMPROVEMENTS WERE TRIED AND ALL LOST. Recorded so they are
 * not retried: (a) MR=8 with a properly written 8-row body, 0.77-0.85x — eight
 * accumulator rows need 8*NC*8 B of L1 and evict the B stream they exist to
 * amortise; (b) collapse(2) over i-tiles and j-panels, +2.6%, kept only because
 * it is harmless; (c) panel blocking with the k-slice and column-panel loops
 * outermost so B is reused across all rows, 0.76-0.95x — it does cut B traffic
 * from about 2 GB to about 72 MB at the square shape, but the extra
 * read-modify-write of C per k-slice and the shorter inner loop cost more than
 * the traffic saved, so this kernel is not bandwidth-limited in the way that
 * analysis assumed. Every variant above was correctness-gated before timing.
 * NOTE this is evidence that the frozen shape is good, NOT evidence of a
 * ceiling: no valid in-contract ceiling has been measured.
 *
 * DELIBERATELY NOT DONE (both are latent bugs seen in the v1 corpus):
 *   - no `aligned(...)` clause: the evaluator's malloc buffers are 16-byte
 *     aligned, so declaring 64 would be false and is UB.
 *   - no assumption that n, m or p divides any blocking factor: the remainder
 *     rows are handled by a separate, obviously correct loop.
 */
#include "gemm_kernel.h"

#define MR 4
/* NC=2048 chosen by a correctness-gated sweep, not by reasoning: at 1024 the
 * widest scored shape (m=2000) split into panels of 1024 and 976 and lost
 * 7.3% there, and NC=2048 leaves every scored shape as a single panel. The
 * geomean gain is 2.8%, at the edge of the 2.8% band, so this is a tidy-up
 * rather than a real tuning lever. MR stays 4: a properly written 8-row body
 * measured 0.77-0.85x of this, because 8 accumulator rows need 8*NC*8 B of L1
 * and evict the B stream. (An earlier sweep appeared to show MR=8 winning 2x;
 * that sweep raised the MR macro without widening the explicitly unrolled
 * 4-row body, so the kernel skipped half its output rows and was timed, not
 * checked. It left 1024 of 2048 elements wrong.) */
#define NC 2048

void gemm(int n, int m, int p,
          const double *__restrict A,
          const double *__restrict B,
          double *__restrict C)
{
    const int nti = n / MR;         /* number of full MR-row tiles */
    /* NO HYBRID DISPATCH — tried, MEASURED, and REVERTED (20260803_stable).
     * HISTORY, kept because it explains why the scored shapes are what they are.
     * The third shape used to be 500x500x2000, where this blocked path lost
     * 1.313x to a plain ikj: blocking divides the parallel iteration count by
     * MR, leaving 125 units for 48 threads at n=500. Dispatching to the
     * row-parallel path below closed that gap (1.021) but cost stability — over
     * 10 scorings the credited time spread went 0.76% -> 11.87% and the band
     * metric that sets the rep count went 0.46% -> 2.27% — and smaller NC was
     * worse on both axes (NC=256: 5.565 ms/9.28%, NC=128: 5.722 ms/11.33%).
     * No decomposition was both fast and stable at n=500.
     *
     * The cause was the SHAPE, not this kernel: 10.4 rows per thread makes ANY
     * row-parallel implementation unstable, including the ikj candidates
     * actually write. The shape was replaced by 1500x600x1500 (31.2 rows per
     * thread), where this path measures 7.341 ms / 0.18% against ikj's
     * 8.871 ms / 3.37% — the stable path is now also the fast one and no
     * dispatch is needed. See 20260803_shape/shape.json. */
    const int i_edge = nti * MR;    /* first row not covered by a full tile */

    /* collapse(2) over both the i-tiles and the j-panels. Each (it, j0) pair
     * writes a disjoint column range of its own MR rows, so this is race-free.
     * HONEST NOTE ON WHY IT IS HERE: it was added to fix the fat shape, which
     * ran 199.6 GF/s against 372.4 and 387.0 on the other two. The diagnosis was
     * that blocking by MR divides the parallel iteration count by MR, leaving
     * 125 units for 48 threads at n=500. That diagnosis was WRONG: equalising
     * the unit count bought 2.6%, and the shape only improved once NC rose past
     * m so the panel split disappeared. The collapse is kept because it is
     * harmless and does help slightly when NC < m, not because it explained
     * anything. */
#pragma omp parallel for collapse(2) schedule(static)
    for (int it = 0; it < nti; ++it) {
      for (int j0 = 0; j0 < m; j0 += NC) {
        const int i0 = it * MR;
        double *__restrict c0 = C + (long)(i0 + 0) * m;
        double *__restrict c1 = C + (long)(i0 + 1) * m;
        double *__restrict c2 = C + (long)(i0 + 2) * m;
        double *__restrict c3 = C + (long)(i0 + 3) * m;
        const double *__restrict a0 = A + (long)(i0 + 0) * p;
        const double *__restrict a1 = A + (long)(i0 + 1) * p;
        const double *__restrict a2 = A + (long)(i0 + 2) * p;
        const double *__restrict a3 = A + (long)(i0 + 3) * p;

        {
            const int nc = (m - j0 < NC) ? (m - j0) : NC;
            double *__restrict d0 = c0 + j0;
            double *__restrict d1 = c1 + j0;
            double *__restrict d2 = c2 + j0;
            double *__restrict d3 = c3 + j0;

            for (int j = 0; j < nc; ++j) {
                d0[j] = 0.0; d1[j] = 0.0; d2[j] = 0.0; d3[j] = 0.0;
            }

            for (int k = 0; k < p; ++k) {
                const double v0 = a0[k], v1 = a1[k], v2 = a2[k], v3 = a3[k];
                const double *__restrict b = B + (long)k * m + j0;
#pragma omp simd
                for (int j = 0; j < nc; ++j) {
                    const double bv = b[j];
                    d0[j] += v0 * bv;
                    d1[j] += v1 * bv;
                    d2[j] += v2 * bv;
                    d3[j] += v3 * bv;
                }
            }
        }
      }
    }

    /* ---- remainder rows (dead when MR divides n; kept for correctness) ---- */
    if (i_edge < n) {
#pragma omp parallel for schedule(static)
        for (int i = i_edge; i < n; ++i) {
            double *__restrict cr = C + (long)i * m;
            for (int j = 0; j < m; ++j) cr[j] = 0.0;
            for (int k = 0; k < p; ++k) {
                const double v = A[(long)i * p + k];
                const double *__restrict b = B + (long)k * m;
#pragma omp simd
                for (int j = 0; j < m; ++j) cr[j] += v * b[j];
            }
        }
    }
}
