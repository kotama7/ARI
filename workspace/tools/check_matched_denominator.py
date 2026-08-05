"""Does the matched denominator still return 1 for identical code?

THE INVARIANT. The harness scores against two denominators built from the same
frozen source: the ANCHOR, always compiled with the default toolchain, and the
MATCHED one, compiled the way the candidate chose. Score the reference AS the
candidate and the matched ratio must come out at 1: the two programs are the same
program. The anchor ratio need not, and does not.

WHY IT MATTERS. The anchor compares across a compiler boundary whenever a
candidate picks a non-default compiler, and anything acting on one side of that
boundary moves the ratio without either program changing. Measured on hardware
2026-08-03: with `XOS_MMM_L_PAGING_POLICY` unset the stencil anchor ratio is
0.2004, with `demand:demand:demand` it is 1.1781 -- 5.9x -- because the variable
is read only by the vendor large-page library, which only that vendor's builds
link. Over the same runs the matched ratio was 1.0028 and 0.9993.

Across three tasks and two compilers the matched ratios were 0.9921--1.0006 while
the anchor ratios spanned 0.17--1.09. On identical code, that entire anchor spread
is toolchain and flags.

This is the check that the separation still works. It needs a compute node: the
unit tests can only pin the structure, not the number.

USAGE (from a batch job on a compute node)
    python check_matched_denominator.py --tasks gemm,spmm,stencil --cc gcc,fcc
    python check_matched_denominator.py --tolerance 0.02
"""
import argparse
import json
import pathlib
import statistics
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
FLAGS = {"fcc": "-Nclang -O3", "gcc": "-O3", "clang": "-O3"}


def check(task: str, cc: str, reps: int) -> dict:
    sys.path.insert(0, str(REPO / "ari-core"))
    sys.path.insert(0, str(REPO / "workspace/harnesses" / task))
    H = __import__(f"{task}_harness")
    kw = {"n": 20000, "k": 64} if task == "spmm" else {}
    with tempfile.TemporaryDirectory() as td:
        wd = pathlib.Path(td, "w")
        wd.mkdir()
        H.seed_work_dir(str(wd))
        ref = (pathlib.Path(H.kernels_dir()) / f"reference_{task}.c").read_text()
        (wd / f"candidate_{task}.c").write_text(ref)
        (wd / "candidate_flags.txt").write_text(FLAGS.get(cc, "-O3") + "\n")
        (wd / "candidate_cc.txt").write_text(cc + "\n")
        try:
            r = H.measure_node(str(wd), reps=reps, **kw)
        except Exception as exc:
            return {"task": task, "cc": cc, "error": f"{type(exc).__name__}: {exc}"}
    if not r.get("compile_ok"):
        return {"task": task, "cc": cc, "error": f"compile: {r.get('reason')}"}
    anchor, matched, errs = [], [], []
    for fam in (r.get("families") or {}).values():
        for rec in fam.get("repetitions") or []:
            m = rec.get("measurements") or {}
            if m.get("speedup"):
                anchor.append(m["speedup"])
            if m.get("speedup_matched"):
                matched.append(m["speedup_matched"])
            if m.get("reference_matched_error"):
                errs.append(m["reference_matched_error"][:80])
    return {"task": task, "cc": cc,
            "anchor": statistics.median(anchor) if anchor else None,
            "matched": statistics.median(matched) if matched else None,
            "matched_errors": errs[:2]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", default="gemm,spmm,stencil")
    ap.add_argument("--cc", default="gcc,fcc")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--tolerance", type=float, default=0.03,
                    help="how far the matched ratio may sit from 1")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rows, failures = [], []
    print(f"{'task':9s} {'cc':6s} {'anchor':>9s} {'matched':>9s}  verdict")
    for cc in [c.strip() for c in args.cc.split(",") if c.strip()]:
        for task in [t.strip() for t in args.tasks.split(",") if t.strip()]:
            row = check(task, cc, args.reps)
            rows.append(row)
            if row.get("error"):
                print(f"{task:9s} {cc:6s} {'-':>9s} {'-':>9s}  ERROR {row['error'][:60]}")
                failures.append(row)
                continue
            m = row.get("matched")
            ok = m is not None and abs(m - 1.0) <= args.tolerance
            print(f"{task:9s} {cc:6s} {row['anchor'] or float('nan'):9.4f} "
                  f"{m if m is not None else float('nan'):9.4f}  "
                  f"{'ok' if ok else 'BROKEN'}"
                  + (f"   {row['matched_errors'][0]}" if row.get("matched_errors") else ""))
            if not ok:
                failures.append(row)

    print()
    anchors = [r["anchor"] for r in rows if r.get("anchor")]
    if anchors:
        print(f"anchor ratios on IDENTICAL code span "
              f"{min(anchors):.4f}--{max(anchors):.4f}; all of that is toolchain "
              f"and flags, none of it is the code.")
    if failures:
        print(f"\n{len(failures)} case(s) failed: the matched denominator is not "
              f"returning 1 for identical source, so the separation between what "
              f"the code did and what the compiler did is not trustworthy.")

    out_dir = pathlib.Path(args.out) if args.out else (
        REPO / "workspace/checkpoints/matched_denominator")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "matched_denominator.json"
    dst.write_text(json.dumps({"tolerance": args.tolerance, "rows": rows}, indent=1))
    print(f"wrote {dst}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
