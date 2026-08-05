"""Is the generated code fast in ABSOLUTE terms? (KATAGIRI: 性能が出ているか)

THE REVIEW POINT THIS ANSWERS. A speedup is a ratio and says nothing about
whether the machine is being used well: "GEMM 33 GFLOPS" was the objection, and
no ratio can answer it. This reports, for any candidate source, the achieved
GF/s per scored case and what fraction that is of the ceiling this machine
actually reaches — so "is the code any good" becomes a number instead of an
impression.

TWO DENOMINATORS, BOTH MEASURED, because they answer different questions:

  measured FMA ceiling — what a hand-written SVE-intrinsic FMA loop reaches here
      (workspace/tools/measure_fma_ceiling.c). This is the honest upper bound for
      code on this machine, and it is BELOW the architectural peak: it reaches
      about 1.65 FMA/cycle of the 2 the hardware offers.

  architectural peak — cores x clock x lanes x 2 flop x 2 FMA pipes, with the
      clock MEASURED via perf_event_open (workspace/tools/measure_clock.c),
      because this machine reports no cpufreq and only "BogoMIPS 200".

WHY THE FRACTION IS LOW, AND WHY THAT IS NOT ONLY THE SEARCH'S FAULT. The task
contract forbids intrinsics and assembly, so a candidate depends on the
compiler's auto-vectoriser — and measured here, that vectoriser emits few or no
SVE FMAs (gcc spilled the accumulators; clang emitted zero z-register FMAs on
the same loop). The ceiling a candidate can reach is therefore bounded by the
toolchain, not only by the code. Report both fractions and say which is which.

USAGE
    python measure_absolute_performance.py --task gemm [--candidate PATH]
                                           [--ceiling-gfs 2534] [--out DIR]
Without --candidate the frozen reference is measured, which is the denominator
every score is expressed against and therefore the number to quote first.
"""
import argparse
import json
import pathlib
import statistics
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

# flops per scored case: 2*n*m*p for the dense products, 2*nnz*k for spmm,
# and 8 flops per interior point per sweep for the 7-point stencil.
_FLOPS = {
    "gemm": lambda n, m, p: 2.0 * n * m * p,
    "stencil": lambda nx, ny, nz, nt: 8.0 * (nx - 2) * (ny - 2) * (nz - 2) * nt,
}

CHILD = r'''
import json, os, pathlib, statistics, sys, tempfile
task, src, reps = sys.argv[1], sys.argv[2], int(sys.argv[3])
repo = "%s"
sys.path.insert(0, repo + "/ari-core")
os.environ["ARI_WORKSPACE"] = repo + "/workspace"
os.environ["ARI_HARNESS_CACHE"] = repo + "/workspace/checkpoints/harness_cache"
sys.path.insert(0, repo + f"/workspace/harnesses/{task}")
H = __import__(f"{task}_harness")
KD = pathlib.Path(H.kernels_dir())
with tempfile.TemporaryDirectory() as td:
    wd = pathlib.Path(td, "n"); wd.mkdir(); H.seed_work_dir(str(wd))
    text = (pathlib.Path(src).read_text() if src != "-"
            else (KD / f"reference_{task}.c").read_text())
    (wd / f"candidate_{task}.c").write_text(text)
    (wd / "candidate_flags.txt").write_text(" ".join(H._REFERENCE_CFLAGS) + "\n")
    kw = {"n": 20000, "k": 64} if task == "spmm" else {}
    r = H.measure_node(str(wd), reps=reps, **kw)
out = {}
for name, fam in (r.get("families") or {}).items():
    secs = []
    for rec in fam.get("repetitions") or []:
        v = (rec.get("measurements") or {}).get("candidate_credited_seconds")
        if isinstance(v, (int, float)) and v > 0:
            secs.append(v)
    out[name] = {"credited_median_s": statistics.median(secs) if secs else None,
                 "valid": bool(fam.get("valid"))}
print("@@" + json.dumps(out))
''' % REPO


def _case_flops(task: str, name: str) -> float | None:
    """Flops for a case, from its family name. Returns None when unknown."""
    try:
        if task == "gemm":
            n, m, p = (int(x) for x in name.split("x"))
            return _FLOPS["gemm"](n, m, p)
        if task == "stencil":
            dims, _, nt = name.partition("t")
            nx, ny, nz = (int(x) for x in dims.split("x"))
            return _FLOPS["stencil"](nx, ny, nz, int(nt))
    except Exception:
        return None
    # spmm's flop count needs the generated matrix's nnz, which is not in the
    # family name; report time only rather than guess.
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default="gemm", choices=("gemm", "spmm", "stencil"))
    ap.add_argument("--candidate", default=None,
                    help="candidate source; default = the frozen reference")
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--ceiling-gfs", type=float, default=2534.0,
                    help="measured FMA ceiling; re-measure with measure_fma_ceiling.c")
    ap.add_argument("--clock-ghz", type=float, default=1.9984,
                    help="measured core clock; re-measure with measure_clock.c")
    ap.add_argument("--cores", type=int, default=48)
    ap.add_argument("--lanes", type=int, default=8, help="fp64 lanes per SVE register")
    ap.add_argument("--fma-pipes", type=int, default=2)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    peak = args.cores * args.clock_ghz * args.lanes * 2.0 * args.fma_pipes
    p = subprocess.run(
        [sys.executable, "-c", CHILD, args.task, args.candidate or "-", str(args.reps)],
        capture_output=True, text=True, timeout=7200)
    line = [l for l in p.stdout.splitlines() if l.startswith("@@")]
    if not line:
        print(f"measurement failed\n{p.stdout[-500:]}\n{p.stderr[-500:]}")
        return 1
    cases = json.loads(line[-1][2:])

    what = args.candidate or "(frozen reference)"
    print(f"task={args.task}  source={what}  reps={args.reps}")
    print(f"measured FMA ceiling {args.ceiling_gfs:.0f} GF/s   "
          f"architectural peak {peak:.0f} GF/s "
          f"(= {args.cores} cores x {args.clock_ghz} GHz x {args.lanes} lanes "
          f"x 2 flop x {args.fma_pipes} pipes)")
    print(f"the ceiling is {args.ceiling_gfs / peak * 100:.1f}% of peak, i.e. "
          f"{args.ceiling_gfs / peak * args.fma_pipes:.2f} FMA/cycle of {args.fma_pipes}")
    print()
    print(f"{'case':22s} {'time ms':>9s} {'GF/s':>9s} {'of ceiling':>11s} {'of peak':>9s}")
    rows = {}
    for name in sorted(cases):
        t = cases[name].get("credited_median_s")
        if not t:
            print(f"{name:22s}  no valid measurement")
            continue
        fl = _case_flops(args.task, name)
        if fl is None:
            print(f"{name:22s} {t*1e3:9.3f} {'n/a':>9s} {'n/a':>11s} {'n/a':>9s}"
                  "   (flop count needs the generated problem)")
            rows[name] = {"time_ms": t * 1e3}
            continue
        gfs = fl / t * 1e-9
        rows[name] = {"time_ms": t * 1e3, "gflops": gfs,
                      "frac_ceiling": gfs / args.ceiling_gfs,
                      "frac_peak": gfs / peak}
        print(f"{name:22s} {t*1e3:9.3f} {gfs:9.1f} "
              f"{gfs/args.ceiling_gfs*100:10.1f}% {gfs/peak*100:8.1f}%")

    print()
    print("A low fraction is not by itself a verdict on the search: the contract")
    print("forbids intrinsics, so the reachable ceiling is set by the compiler's")
    print("auto-vectoriser, which on this machine emits few or no SVE FMAs.")

    out_dir = pathlib.Path(args.out) if args.out else (
        REPO / "workspace/checkpoints/absolute_performance")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"absolute_{args.task}.json"
    dst.write_text(json.dumps(
        {"task": args.task, "source": what, "reps": args.reps,
         "ceiling_gfs": args.ceiling_gfs, "peak_gfs": peak,
         "clock_ghz": args.clock_ghz, "cases": rows}, indent=1))
    print(f"wrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
