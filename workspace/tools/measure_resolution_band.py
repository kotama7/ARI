"""What repetition count actually resolves a decision? (KATAGIRI: 結果がぶれない)

THE REVIEW POINT THIS ANSWERS. "結果がぶれない問題設定" — a benchmark whose score
moves more than the effect being studied cannot support any conclusion. This
measures that directly, so the repetition count is chosen from data rather than
assumed.

METHOD. Score IDENTICAL builds repeatedly and look at the spread. Any spread is
pure measurement noise, because the thing being measured does not change between
trials. The band at a rep count is the p95 of |score - median| / median over
trials, reported next to the wall-clock cost of one scoring so the count can be
chosen against a real budget.

READ IT AGAINST THE DECISION IT SERVES. A band is only "good enough" relative to
the gap the search must resolve: on the preliminary corpus the winner beat the
runner-up by less than the identical-build band in about 70% of runs, so the
search was choosing between siblings it could not tell apart. Re-run this
whenever the denominator, the problem sizes or the timed region change — all
three moved during this study, and the old band did not survive any of them.
"""
import json, os, pathlib, statistics, sys, tempfile, time

REPO = pathlib.Path(__file__).resolve().parents[2]
TASK = sys.argv[1] if len(sys.argv) > 1 else "gemm"
REP_COUNTS = [int(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2
                               else "3,5,15,30".split(","))]
TRIALS = int(sys.argv[3]) if len(sys.argv) > 3 else 12

sys.path.insert(0, str(REPO / "ari-core"))
sys.path.insert(0, str(REPO / f"workspace/harnesses/{TASK}"))
os.environ["ARI_WORKSPACE"] = str(REPO / "workspace")
os.environ.setdefault("ARI_HARNESS_CACHE",
                      str(REPO / "workspace/checkpoints/harness_cache"))

H = __import__(f"{TASK}_harness")
seed_work_dir = H.seed_work_dir
measure_node = H.measure_node
CAND = f"candidate_{TASK}.c"
KD = pathlib.Path(H.kernels_dir())

# What gets scored, repeatedly and identically. A speedup harness ships a frozen
# reference and that is the natural subject; a score-axis harness (erfc,
# meshpart) ships no reference C source at all, and for a band it does not need
# one -- the band is the spread of scoring the SAME build, so the starter
# candidate that seed_work_dir writes serves exactly as well. Assuming a
# reference existed is why this tool could not measure two of the five
# registered harnesses, which is why their bands are undeclared.
_ref = KD / f"reference_{TASK}.c"
REF_SRC = _ref.read_text() if _ref.is_file() else None
REF_CFLAGS = getattr(H, "_REFERENCE_CFLAGS", None)

import inspect as _inspect
try:
    ACCEPTS_REPS = ("reps" in _inspect.signature(measure_node).parameters
                    or any(p.kind is _inspect.Parameter.VAR_KEYWORD
                           for p in _inspect.signature(measure_node).parameters.values()))
except (TypeError, ValueError):
    ACCEPTS_REPS = True

EXTRA = {}
if TASK == "spmm":                       # scored size lives in harness.toml
    EXTRA = {"n": int(os.environ.get("ARI_SPMM_N", "20000")),
             "k": int(os.environ.get("ARI_SPMM_K", "64"))}

# The v1 median top1-top2 sibling gaps, in percent, for the tasks that had a v1.
# A rep count "resolves siblings" when the band is at most a third of this.
# Absent for a task with no such measurement: inventing a target would turn an
# unmeasured requirement into a passing verdict.
V1_SIBLING_GAP_PCT = {"gemm": 0.71, "spmm": 0.51, "stencil": 0.32}
TARGET_BAND_PCT = (V1_SIBLING_GAP_PCT[TASK] / 3.0
                   if TASK in V1_SIBLING_GAP_PCT else None)

print(f"task              = {TASK}")
print(f"subject           = " + ("frozen reference" if REF_SRC
                                 else "seeded starter candidate (no reference "
                                      "source in this harness)"))
print(f"rep counts        = " + (str(REP_COUNTS) if ACCEPTS_REPS else
      "n/a (this harness has no repetition knob; the band is the spread over "
      "independent scorings)"))
print(f"trials per count  = {TRIALS}")
if TARGET_BAND_PCT is not None:
    print(f"v1 median sibling gap = {V1_SIBLING_GAP_PCT[TASK]}%  -> band target "
          f"{TARGET_BAND_PCT:.3f}%")
else:
    print("no v1 sibling gap for this task: the band is reported without a "
          "pass/fail target, because there is no measured gap to compare it to")
print()


def score_once(reps):
    with tempfile.TemporaryDirectory() as td:
        wd = pathlib.Path(td, "node")
        wd.mkdir()
        seed_work_dir(str(wd))
        if REF_SRC is not None:
            (wd / CAND).write_text(REF_SRC)
        if REF_CFLAGS:
            (wd / "candidate_flags.txt").write_text(" ".join(REF_CFLAGS) + "\n")
        t0 = time.monotonic()
        # `reps` is a timing-harness knob. A score-axis harness has no such
        # axis at all -- its measure_node does not take one -- and passing it
        # anyway raised TypeError, which read as "the harness is broken" rather
        # than "this dimension does not exist here".
        r = (measure_node(str(wd), reps=reps, **EXTRA) if ACCEPTS_REPS
             else measure_node(str(wd), **EXTRA))
        wall = time.monotonic() - t0
    # The harness's NATIVE outcome, whatever its axis is. Reading `families`
    # unconditionally returned None for every score-axis harness, which the
    # caller could not tell from "the build failed".
    fams = r.get("families") or {}
    if fams:
        if not all(v.get("valid") for v in fams.values()):
            return None, wall
        g = 1.0
        for v in fams.values():
            g *= max(v.get("speedup", 0.0), 1e-12)
        return g ** (1.0 / len(fams)), wall
    if r.get("compile_ok") and r.get("score") is not None:
        return float(r["score"]), wall
    return None, wall


out = {}
for reps in REP_COUNTS:
    scores, walls = [], []
    for i in range(TRIALS):
        s, w = score_once(reps)
        walls.append(w)
        if s is not None:
            scores.append(s)
        print(f"  reps={reps:3d} trial {i + 1:2d}/{TRIALS}: "
              f"score={s if s is None else round(s, 5)}  {w:.1f}s", flush=True)
    if len(scores) < 3:
        out[reps] = {"error": "too few valid trials", "walls": walls}
        continue
    med = statistics.median(scores)
    if med == 0:
        out[reps] = {"error": "median score is 0; a relative band is undefined",
                     "n_valid": len(scores)}
        continue
    devs = sorted(abs(s - med) / med for s in scores)
    # p95 of the deviations, index-clamped for small trial counts
    p95 = devs[min(len(devs) - 1, int(round(0.95 * (len(devs) - 1))))]
    out[reps] = {
        "n_valid": len(scores),
        "median_score": round(med, 5),
        "band_p95_pct": round(100 * p95, 4),
        "max_dev_pct": round(100 * devs[-1], 4),
        "mean_wall_s": round(statistics.mean(walls), 2),
        # None, not False, when no target exists: "not known to resolve" and
        # "known not to resolve" are different claims.
        "resolves_siblings": (None if TARGET_BAND_PCT is None
                              else bool(100 * p95 <= TARGET_BAND_PCT)),
    }
    print(f"  => reps={reps}: band(p95)={out[reps]['band_p95_pct']}%  "
          f"cost={out[reps]['mean_wall_s']}s/scoring  "
          f"resolves={out[reps]['resolves_siblings']}", flush=True)
    print()

print(json.dumps(out, indent=1))
print()
print("=" * 70)
ok = [r for r in REP_COUNTS if isinstance(out.get(r), dict)
      and out[r].get("resolves_siblings")]
if ok:
    r = min(ok)
    print(f"SMALLEST TESTED REP COUNT THAT RESOLVES THE MEDIAN SIBLING GAP: {r}")
    print(f"  band {out[r]['band_p95_pct']}% <= target {TARGET_BAND_PCT:.3f}%")
    print(f"  cost {out[r]['mean_wall_s']}s per node scoring")
else:
    print("NO TESTED REP COUNT RESOLVES THE MEDIAN SIBLING GAP.")
    print("The gate must then either raise reps further or accept that sibling")
    print("choices below the band are coin flips and say so in the analysis.")
    for r in REP_COUNTS:
        if isinstance(out.get(r), dict) and "band_p95_pct" in out[r]:
            print(f"  reps={r:3d}  band={out[r]['band_p95_pct']:.3f}%  "
                  f"cost={out[r]['mean_wall_s']}s")

import os as _o
dst = pathlib.Path(_o.environ.get("ARI_TOOL_OUT")
                   or REPO / "workspace/checkpoints/resolution_band") / f"band_{TASK}.json"
dst.parent.mkdir(parents=True, exist_ok=True)
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps({"task": TASK, "target_band_pct": TARGET_BAND_PCT,
                           "by_reps": out}, indent=1))
print(f"\nwrote {dst}")
