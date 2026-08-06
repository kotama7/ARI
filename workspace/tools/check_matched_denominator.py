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

WHAT COUNTS AS A COMPILER BOUNDARY. Only a compiler that resolves to a DIFFERENT
binary than the default one. Where `cc` is a symlink to `gcc`, `--cc gcc` is the
default compiler under another name: the harness builds no matched reference and
this tool reports `n/a` for that pair rather than pretending to have checked it.

EXIT CODES
    0  at least one pair was checked and every checked pair holds
    1  a checked pair failed — the separation is not trustworthy
    2  nothing was checked (every requested compiler was the default one)

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


def _same_binary_as_default(task: str, cc: str) -> bool:
    """Does *cc* resolve to the compiler the anchor already uses?

    ``cc`` is commonly a symlink to ``gcc``, in which case ``--cc gcc`` names one
    binary with the default and there is no compiler boundary to remove. The
    harness now declines to build a matched reference in that case (it would
    differ from the anchor only by _REFERENCE_CFLAGS, and the quotient would
    report the reference's own flags as a toolchain effect), so this tool must
    report it as inapplicable rather than as a broken separation."""
    import os
    import shutil
    chosen = shutil.which(cc)
    default_name = os.environ.get(f"ARI_{task.upper()}_CC", "cc")
    default = shutil.which(default_name)
    if not chosen or not default:
        return False
    return os.path.realpath(chosen) == os.path.realpath(default)


def check(task: str, cc: str, reps: int) -> dict:
    # Through the registry, so the pins are verified: a separation demonstrated
    # against an unverified harness says nothing about the one that scores.
    sys.path.insert(0, str(REPO / "workspace/tools"))
    from _harness_access import verified_harness
    harness, H = verified_harness(task)
    if _same_binary_as_default(task, cc):
        return {"task": task, "cc": cc, "not_applicable":
                f"{cc} resolves to the same binary as the default compiler — "
                f"no compiler boundary, so there is no matched denominator"}
    with tempfile.TemporaryDirectory() as td:
        wd = pathlib.Path(td, "w")
        wd.mkdir()
        H.seed_work_dir(str(wd))
        ref = (pathlib.Path(H.kernels_dir()) / f"reference_{task}.c").read_text()
        (wd / f"candidate_{task}.c").write_text(ref)
        (wd / "candidate_flags.txt").write_text(FLAGS.get(cc, "-O3") + "\n")
        (wd / "candidate_cc.txt").write_text(cc + "\n")
        try:
            # measure() applies the manifest's [measure_kwargs]; the scored size
            # used to be restated here as a literal n=20000/k=64.
            r = harness.measure(str(wd), reps=reps)
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
            if row.get("not_applicable"):
                # Not a failure and not a pass: there is no second denominator to
                # check. Counting it either way would be a verdict about nothing.
                print(f"{task:9s} {cc:6s} {'-':>9s} {'-':>9s}  n/a   "
                      f"{row['not_applicable'][:60]}")
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

    # An all-inapplicable run must not read as a pass. Same rule as
    # compare_harnesses.py: a rate over zero decided cases is an absence of
    # evidence, not a perfect result.
    checked = [r for r in rows if not r.get("error") and not r.get("not_applicable")]
    if not checked and not failures:
        print("\nNOTHING WAS CHECKED: every requested compiler resolves to the "
              "same binary as the default, so no matched denominator was built "
              "anywhere. That is an absence of evidence, not a working "
              "separation — pass --cc a compiler that is a different binary.")

    out_dir = pathlib.Path(args.out) if args.out else (
        REPO / "workspace/checkpoints/matched_denominator")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "matched_denominator.json"
    dst.write_text(json.dumps({"tolerance": args.tolerance, "rows": rows}, indent=1))
    print(f"wrote {dst}")
    if failures:
        return 1
    return 0 if checked else 2      # 2 = nothing usable, never reported as clean


if __name__ == "__main__":
    raise SystemExit(main())
