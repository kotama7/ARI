"""Is every frozen reference at least as good as what the agents actually wrote?

The same check applied to gemm found the reference LOSING to a plain ikj at one
of three scored shapes by 1.313x, which had gone unnoticed because the reference
sweep only ever compared variants of the reference against each other. That
failure mode is not gemm-specific, so the other two denominators get the same
treatment before the campaign is run.

WHAT IS SCORED. The highest-scoring candidate the previous campaign produced for
each task, taken verbatim from the corpus with its own compile flags, and scored
as a candidate through the ordinary harness path against today's frozen
reference. Reported number is the harness's speedup, t_reference / t_candidate:

    > 1  the AGENT'S code beats the denominator - the reference is not competent
    < 1  the reference wins

These sources were written under the v1 problem sizes, so this is not a fair
test of the agents; it is a test of the REFERENCE, using real agent-written code
as the yardstick. A denominator that loses to code the search already produced
cannot support the claim that the score measures optimisation quality.

Correctness is enforced by the harness's own oracle at the scored size, so a
candidate that is merely wrong scores invalid rather than fast.
"""
import json
import pathlib
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


HERE = _out_dir("reference_competence")
BEST = json.loads((HERE / "best_corpus.json").read_text())
# The scored problem size comes from the manifest's [measure_kwargs] via
# Harness.measure; restating it here made this file a second source of truth.
EXTRA = {}
REPS = 7

CHILD = r'''
import json, os, pathlib, sys, tempfile
task, src, flags, reps = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
extra = json.loads(sys.argv[5])
repo = "%s"
os.environ["ARI_WORKSPACE"] = repo + "/workspace"
os.environ["ARI_HARNESS_CACHE"] = repo + "/workspace/checkpoints/harness_cache"
# Through the registry, so the pins are verified: this program decides whether
# the DENOMINATOR is competent, and it cannot answer that about a harness it
# never checked. See workspace/tools/_harness_access.py.
sys.path.insert(0, repo + "/workspace/tools")
from _harness_access import verified_harness
harness, H = verified_harness(task)
with tempfile.TemporaryDirectory() as td:
    wd = pathlib.Path(td, "node"); wd.mkdir(); H.seed_work_dir(str(wd))
    (wd / f"candidate_{task}.c").write_text(pathlib.Path(src).read_text())
    fp = pathlib.Path(flags)
    (wd / "candidate_flags.txt").write_text(
        fp.read_text() if fp.is_file() else " ".join(H._REFERENCE_CFLAGS) + "\n")
    r = harness.measure(str(wd), reps=reps, **extra)
out = {"reason": r.get("reason"), "families": {}}
for name, fam in (r.get("families") or {}).items():
    out["families"][name] = {"speedup": fam.get("speedup"),
                             "valid": bool(fam.get("valid"))}
print("@@" + json.dumps(out))
''' % REPO


def main() -> None:
    results = {}
    for task in ("gemm", "spmm", "stencil"):
        info = BEST.get(task)
        if not info:
            print(f"  {task}: no corpus source")
            continue
        t0 = time.monotonic()
        r = subprocess.run(
            [sys.executable, "-c", CHILD, task, info["src"], info["flags"],
             str(REPS), json.dumps(EXTRA.get(task, {}))],
            capture_output=True, text=True, timeout=3600)
        line = [l for l in r.stdout.splitlines() if l.startswith("@@")]
        if not line:
            print(f"  {task:8s} FAILED\n{r.stdout[-400:]}\n{r.stderr[-400:]}",
                  flush=True)
            continue
        got = json.loads(line[-1][2:])
        results[task] = got
        fams = got["families"]
        print(f"  {task:8s} corpus-best (v1 score {info['score']:.2f})  "
              f"({time.monotonic()-t0:5.1f}s)", flush=True)
        for name, fam in sorted(fams.items()):
            flag = ""
            if fam["valid"] and fam["speedup"] and fam["speedup"] > 1.0:
                flag = "  <-- AGENT CODE BEATS THE REFERENCE"
            sp = fam["speedup"]
            sp_s = f"{sp:7.4f}" if isinstance(sp, (int, float)) else "    n/a"
            print(f"      {name:22s} {sp_s}  valid={fam['valid']}{flag}",
                  flush=True)
        if got.get("reason"):
            print(f"      reason: {str(got['reason'])[:150]}", flush=True)

    print()
    print("speedup = t_reference / t_corpus_candidate; > 1 means the reference LOSES")
    (HERE / "corpus_vs_ref.json").write_text(json.dumps(results, indent=1))
    print(f"wrote {HERE / 'corpus_vs_ref.json'}")


if __name__ == "__main__":
    main()
