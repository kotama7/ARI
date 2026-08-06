"""Hardware counters for the region a candidate is SCORED on — you choose the
size and the number of runs.

WHAT IT ANSWERS. `measure_absolute_performance.py` says how fast a candidate is;
this says WHY. IPC, how often an access leaves L1, what fraction of those reach
memory, and (where the machine reports its line size) achieved bytes/cycle —
taken over exactly the region the score is built from, with the candidate's own
compiler and screened flags.

WHY IT IS NOT PART OF SCORING. The numbers here never enter `speedup` or `valid`.
A profile that could move a score would be a second scoring channel with none of
the first one's anti-gaming surface. `scored: false` is in every record.

SIZE. Defaults to the manifest's `[measure_kwargs]` — the size the score is taken
at — because the harnesses' own defaults are not that: spmm's is ~39x smaller,
where parallel overhead dominates and every kernel looks alike. Override with
`--n/--k` (spmm) or `--cases` (which shapes/families to cover).

COUNT. `--reps` is how many independent PROCESSES per case, with the same
input-seed formula the scored repetitions use, so profile point r lines up with
scored repetition r. It defaults to 3 because one point has no spread, and this
study has already mistaken run-to-run variance for an effect once. The record
carries `ratio_spread` so you can see whether a ratio is worth acting on before
acting on it. There is no in-process warmup and no in-process repetition: the
score is one cold call per process, and a warm profile would describe a regime
the score never measures.

WHERE IT MUST RUN. On the node class that does the measuring. The counter event
numbers are ARMv8 PMUv3 encodings; on another architecture they read zero and
`region_counters` exits rather than printing a clean empty result. The submit
node is a different architecture from the compute nodes here, and the vendor tree
is not even visible from it — so run this through the batch system.

USAGE (from a batch job on a compute node)
    python workspace/tools/profile_candidate.py --task stencil --work-dir DIR
    python workspace/tools/profile_candidate.py --task spmm --n 20000 --k 64 --reps 5
    python workspace/tools/profile_candidate.py --task gemm --cases 1000x1000x1000 --reps 3
    python workspace/tools/profile_candidate.py --task stencil --plan-only

With no `--work-dir` it profiles the harness's own seeded starter candidate,
which is what you want when you are checking the instrument rather than a node.

EXIT CODES
    0  every point produced counters
    1  at least one point failed (its error is in the record)
    2  nothing ran
"""
import argparse
import json
import os
import pathlib
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "workspace/tools"))


def _parse_case(task: str, text: str):
    """'1000x1000x1000' -> (1000,1000,1000); '256x256x256t10' -> (...,10);
    a family name is passed through unchanged."""
    if task == "spmm":
        return text
    body, _, nt = text.partition("t")
    dims = [int(v) for v in body.split("x")]
    if nt:
        dims.append(int(nt))
    return tuple(dims)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True,
                    help="a registered speedup harness (gemm, spmm, stencil)")
    ap.add_argument("--work-dir", default=None,
                    help="node work_dir holding candidate_<task>.c; omit to "
                         "profile the harness's own seeded starter candidate")
    ap.add_argument("--reps", type=int, default=3,
                    help="independent processes per case (default 3; one point "
                         "has no spread)")
    ap.add_argument("--cases", default=None,
                    help="comma-separated shapes (1000x1000x1000, 256x256x256t10) "
                         "or spmm family names; default = every scored case")
    ap.add_argument("--seed", type=int, default=None,
                    help="run seed; the input seed per rep follows the scored formula")
    ap.add_argument("--n", type=int, default=None, help="spmm rows (default: the manifest's)")
    ap.add_argument("--k", type=int, default=None, help="spmm columns (default: the manifest's)")
    ap.add_argument("--line-bytes", type=int, default=None,
                    help="MEASURED L2 line size, for bytes/cycle. Without it that "
                         "ratio is suppressed rather than computed from a guess "
                         "when the machine does not report its cache geometry.")
    ap.add_argument("--plan-only", action="store_true",
                    help="print what would run, and its cost, without running it")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from _harness_access import verified_harness      # noqa: E402

    harness, H = verified_harness(args.task)
    overrides = {"reps": args.reps}
    if args.seed is not None:
        overrides["seed"] = args.seed
    if args.line_bytes:
        overrides["line_bytes"] = args.line_bytes
    if args.cases:
        cases = [_parse_case(args.task, c.strip())
                 for c in args.cases.split(",") if c.strip()]
        overrides["cases"] = cases
    for name in ("n", "k"):
        if getattr(args, name) is not None:
            overrides[name] = getattr(args, name)

    sized = dict(harness._kwargs())
    sized.update({k: v for k, v in overrides.items() if k in sized})
    default_cases = (list(getattr(H, "FAMILIES", ())) if args.task == "spmm"
                     else [list(s) for s in getattr(H, "SHAPES", ())])
    plan_cases = overrides.get("cases", default_cases)
    print(f"task        {args.task}")
    print(f"machine     {os.uname().machine}")
    print(f"sizes       {sized or '(none declared)'}")
    print(f"cases       {plan_cases}")
    print(f"reps        {args.reps}   -> {len(plan_cases) * args.reps} processes, "
          f"one build")
    print(f"work_dir    {args.work_dir or '(seeded starter candidate)'}")
    if args.plan_only:
        print("\n--plan-only: nothing was run.")
        return 0

    td = None
    wd = args.work_dir
    if not wd:
        td = tempfile.TemporaryDirectory()
        wd = str(pathlib.Path(td.name, "node"))
        pathlib.Path(wd).mkdir(parents=True)
        H.seed_work_dir(wd)
    t0 = time.monotonic()
    try:
        rec = harness.profile(wd, **overrides)
    finally:
        if td is not None:
            td.cleanup()
    rec["wall_seconds"] = round(time.monotonic() - t0, 2)

    points = rec.get("points") or []
    print()
    for p in points:
        c = (p.get("counters") or {})
        r = c.get("ratios") or {}
        if p.get("error"):
            print(f"  {p['case']:24s} seed={p['input_seed']:<12} FAILED {p['error'][:70]}")
            continue
        print(f"  {p['case']:24s} seed={p['input_seed']:<12} "
              f"t={p['credited_seconds']:.6f}s  IPC={r.get('ipc')}  "
              f"L1refill/acc={r.get('l1d_refill_per_access')}  "
              f"L2/L1={r.get('l2d_refill_per_l1d_refill')}  "
              f"B/cyc={r.get('bytes_per_cycle', 'suppressed')}")
    # Spread is PER CASE. Pooling two shapes would report their genuine
    # difference as measurement noise, which is the confusion this study already
    # spent a campaign untangling.
    print()
    for key, per_case in (rec.get("ratio_spread") or {}).items():
        for case, sp in (per_case or {}).items():
            rel = sp.get("rel_spread")
            tail = f" rel_spread={rel:.3%}" if rel is not None else ""
            print(f"  spread {key:28s} {case:24s} n={sp['n']} "
                  f"median={sp['median']:.4g}{tail}")
    env = (rec.get("measurement_environment") or {}).get("sha256", "")
    print(f"\n  environment digest {env[:16]}  (a profile is only comparable with a "
          f"score whose digest matches)")
    print(f"  wall {rec['wall_seconds']} s")

    out_dir = pathlib.Path(args.out) if args.out else (
        REPO / "workspace/checkpoints/profile_candidate")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"profile_{args.task}.json"
    dst.write_text(json.dumps(rec, indent=1, default=str))
    print(f"  wrote {dst}")

    if not points:
        return 2
    return 1 if any(p.get("error") for p in points) else 0


if __name__ == "__main__":
    raise SystemExit(main())
