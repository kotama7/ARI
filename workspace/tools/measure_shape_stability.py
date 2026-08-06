"""Choose a third gemm shape that a row-parallel kernel can be measured on.

WHY THE CURRENT ONE FAILS. 500x500x2000 exists to cover the long-reduction /
small-output regime. But n=500 over 48 threads is 10.4 rows per thread, so any
row-parallel implementation is load-imbalanced there, and measured over 10
independent scorings the credited time of the row-parallel path spreads 11.87%
against 0.76% for the blocked path. That is not a property of one kernel: the
unblocked ikj is what the corpus's best gemm candidates actually write, so the
shape makes the SCORE noisy for exactly the code the search produces. Keeping
the blocked reference restores stability but leaves it 1.313x slower than ikj
there, i.e. a denominator the textbook kernel beats.

WHAT IS MEASURED. For each candidate shape, both implementations are scored and
their OWN credited time recorded across N independent scorings:

    blocked  - the frozen reference kernel (MR=4, NC=2048)
    ikj      - the unblocked row-parallel kernel from the corpus ladder

A usable shape needs BOTH to be stable (spread comparable to the other two
scored shapes, which measure 0.65-2.97%) and the blocked reference not to be
beaten by ikj. The regime must also survive: p/m stays well above 1 so the shape
still stresses a long reduction, and the working set stays past the last-level
cache.

Shapes are passed through the ordinary harness path, so compile flags, timed
region and oracle are the scored ones.
"""
import json
import pathlib
import statistics
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
def _out_dir(default_slug: str) -> "pathlib.Path":
    """Where to write results: ``--out DIR``, else ARI_TOOL_OUT, else a
    checkpoint named for this tool. Kept out of the tool's body so re-running it
    never silently overwrites the checkpoint of an earlier, different run."""
    import argparse
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--out", default=None, help="directory for results")
    args, _ = ap.parse_known_args()
    if args.out:
        return pathlib.Path(args.out)
    import os as _o
    env = _o.environ.get("ARI_TOOL_OUT")
    if env:
        return pathlib.Path(env)
    return (pathlib.Path(__file__).resolve().parents[2]
            / "workspace/checkpoints" / default_slug)


HERE = _out_dir("shape_stability")
KD = REPO / "workspace/harnesses/gemm/gemm_kernels"
LADDER = (REPO / "workspace/checkpoints/20260801_hpc_quality_audit"
          / "ladder/graded_ladder/rungs/gemm/R2s")

SHAPES = [
    ("500x500x2000", 500, 500, 2000),      # incumbent, for reference
    ("1000x600x2000", 1000, 600, 2000),
    ("1200x600x1600", 1200, 600, 1600),
    ("1500x600x1500", 1500, 600, 1500),
]
N_REPEAT, REPS = 8, 5

CHILD = r'''
import json, os, pathlib, statistics, sys, tempfile
src, flags, n, m, p, reps = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
repo = "%s"
os.environ["ARI_WORKSPACE"] = repo + "/workspace"
os.environ["ARI_HARNESS_CACHE"] = repo + "/workspace/checkpoints/harness_cache"
# Through the registry, so the pins are verified. `shapes` is a candidate-shape
# probe, not a manifest kwarg, so measure_node is still the call — but only
# after load() has checked the harness. See workspace/tools/_harness_access.py.
sys.path.insert(0, repo + "/workspace/tools")
from _harness_access import verified_module
H = verified_module("gemm")
with tempfile.TemporaryDirectory() as td:
    wd = pathlib.Path(td, "node"); wd.mkdir(); H.seed_work_dir(str(wd))
    (wd / "candidate_gemm.c").write_text(pathlib.Path(src).read_text())
    (wd / "candidate_flags.txt").write_text(
        pathlib.Path(flags).read_text() if flags != "-"
        else " ".join(H._REFERENCE_CFLAGS) + "\n")
    r = H.measure_node(str(wd), reps=reps, shapes=((n, m, p),))
fam = next(iter((r.get("families") or {}).values()), {})
secs = []
for rec in fam.get("repetitions") or []:
    v = (rec.get("measurements") or {}).get("candidate_credited_seconds")
    if isinstance(v, (int, float)) and v > 0:
        secs.append(v)
print("@@" + json.dumps({"credited": statistics.median(secs) if secs else None,
                         "speedup": fam.get("speedup"),
                         "valid": bool(fam.get("valid"))}))
''' % REPO

IMPLS = [("blocked", KD / "reference_gemm.c", "-"),
         ("ikj", LADDER / "candidate_gemm.c", LADDER / "candidate_flags.txt")]


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    results = {}
    for sh_label, n, m, p in SHAPES:
        results[sh_label] = {}
        for impl, src, flags in IMPLS:
            vals = []
            t0 = time.monotonic()
            for _ in range(N_REPEAT):
                r = subprocess.run(
                    [sys.executable, "-c", CHILD, str(src), str(flags),
                     str(n), str(m), str(p), str(REPS)],
                    capture_output=True, text=True, timeout=1800)
                line = [l for l in r.stdout.splitlines() if l.startswith("@@")]
                if not line:
                    continue
                d = json.loads(line[-1][2:])
                if d.get("credited"):
                    vals.append(d["credited"])
            results[sh_label][impl] = vals
            if vals:
                med = statistics.median(vals)
                print(f"  {sh_label:16s} {impl:8s} {med*1e3:8.3f} ms  "
                      f"spread {(max(vals)-min(vals))/med*100:6.2f}%  "
                      f"({time.monotonic()-t0:4.1f}s)", flush=True)

    print()
    print(f"{'shape':16s} {'blocked ms':>11s} {'spread':>8s} {'ikj ms':>9s} "
          f"{'spread':>8s} {'ikj/blocked':>12s}")
    for sh_label, _, _, _ in SHAPES:
        b = results[sh_label].get("blocked") or []
        k = results[sh_label].get("ikj") or []
        if len(b) < 2 or len(k) < 2:
            print(f"{sh_label:16s} incomplete")
            continue
        mb, mk = statistics.median(b), statistics.median(k)
        print(f"{sh_label:16s} {mb*1e3:11.3f} {(max(b)-min(b))/mb*100:7.2f}% "
              f"{mk*1e3:9.3f} {(max(k)-min(k))/mk*100:7.2f}% {mb/mk:12.3f}")

    print()
    print("Usable shape: BOTH spreads in the 0.65-2.97% band the other two scored")
    print("shapes achieve, AND ikj/blocked <= 1 so the textbook kernel does not")
    print("beat the denominator.")
    (HERE / "shape.json").write_text(json.dumps(results, indent=1))
    print(f"wrote {HERE / 'shape.json'}")


if __name__ == "__main__":
    main()
