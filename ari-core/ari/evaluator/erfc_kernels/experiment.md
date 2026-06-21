# Experiment: implement a high-accuracy complementary error function (erfc)

Goal: implement `double myerfc(double x)` = erfc(x) = 1 − erf(x) to **relative
error < 1e-9** across the wide domain **x ∈ [−5, 26]**. A fixed deterministic
evaluator scores you — there is no LLM judge.

## What you produce

Your working directory is **already seeded** — list it:

- `candidate_erfc.c` — the file you edit (starts as a poor tiny-x approximation).
- `erfc_kernel.h` — the `myerfc()` contract (do not change the signature).
- `erfc_main.c` — the FROZEN driver (do not edit).
- `baseline_erfc.c` — the FROZEN poor baseline.
- `selftest.c` — local accuracy self-test (per-region pass rates).
- `ref_points.csv` — seeded reference points for the self-test.
- `Makefile` — `make candidate` / `make selftest`.

**Edit `candidate_erfc.c`.** You MAY `#include <math.h>` for exp, log, fabs,
sqrt, pow, etc., but you **MUST NOT call erf, erfc, erff, or erfcf** — implement
the numerics yourself.

## How you are judged (fixed, deterministic)

- The evaluator evaluates your `myerfc` at many HIDDEN points across the domain
  and reports **score = fraction of points with relative error < 1e-9** (a number
  in [0, 1]). Partial credit: covering more of the domain raises the score.
- The domain spans regimes that each need a DIFFERENT approximation:
  - `center [−5, 2)` — a series / rational approximation of erf;
  - `mid [2, 6)` — accuracy starts to require care;
  - `tail [6, 15)` and `deeptail [15, 26)` — erfc becomes tiny (down to ~1e-296)
    and `1 − erf(x)` cancels catastrophically, so use an **asymptotic expansion
    or continued fraction** there.
- The evaluator's points are NOT the self-test's points, so you cannot pass by
  hardcoding — only a genuinely accurate function generalizes.

## Notes
- **Iterate with the self-test**: `make selftest && ./selftest` prints the
  per-region pass rate and the worst relative error. Improve the
  **lowest-passing region** next, round by round, until all regions pass.
- This is hard to get right in one shot — expect to conquer the domain region by
  region (center → mid → tail → deep tail). Keep what works; fix the worst part.
- Do NOT write your own `main()` or call erf/erfc. Just implement `myerfc`.
