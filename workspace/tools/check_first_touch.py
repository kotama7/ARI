"""Does the code do first touch, and does its decomposition MATCH its compute?

THE REVIEW POINT THIS ANSWERS. Both reviewers named NUMA placement / first touch
as mandatory on this machine (4 CMGs). Reading a source for "does it have a
parallel init loop" is not enough, and the preliminary corpus shows why: the
best stencil candidate DID first-touch its buffers, but touched them with
`collapse(3)` over nx*ny*nz while sweeping with `collapse(2)` over
(nx-2)*(ny-2). The thread that first wrote a page was therefore not the thread
that later swept it, so the pages were placed but not placed WHERE THEY ARE
USED — which looks correct on inspection and buys a fraction of the benefit.

So this checks three things, in increasing order of what they cost to run:

  1. PRESENT — is there a parallel write over the buffers before the compute?
  2. MATCHED — do the touch loop and the compute loop iterate the same space
     with the same schedule? A mismatch is reported with both pragmas, because
     that is the failure the corpus actually contains.
  3. MEASURED — optionally, score the source as-is against a variant with the
     touch loop removed, so the claim "first touch matters here" is a number.

STEPS 1-2 ARE STATIC AND CHEAP; STEP 3 COMPILES AND TIMES. Static analysis alone
would repeat the mistake it is meant to catch: the reference's own comment
claimed its touch matched its sweep, and measuring showed the ranges differ by
one row — which turned out not to matter (aligning them measured 1.2% SLOWER),
but nobody knew that until it was measured.

USAGE
    python check_first_touch.py --source PATH [--task stencil] [--measure]
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

_PRAGMA = re.compile(r"#pragma\s+omp\s+([^\n]*)")
_FOR = re.compile(r"for\s*\(\s*(?:int|long|size_t)?\s*(\w+)\s*=\s*([^;]+);\s*\1\s*<\s*([^;]+);")


def _pragma_loops(text: str) -> list[dict]:
    """Every `#pragma omp ... for` with the loop header that follows it."""
    out = []
    for m in _PRAGMA.finditer(text):
        clause = m.group(1).strip()
        if " for" not in f" {clause}":
            continue
        tail = text[m.end():m.end() + 400]
        f = _FOR.search(tail)
        out.append({
            "clause": clause,
            "collapse": int(re.search(r"collapse\s*\(\s*(\d+)", clause).group(1))
            if "collapse" in clause else 1,
            "schedule": (re.search(r"schedule\s*\(\s*(\w+)", clause).group(1)
                         if "schedule" in clause else "(default)"),
            "var": f.group(1) if f else None,
            "lo": f.group(2).strip() if f else None,
            "hi": f.group(3).strip() if f else None,
            "body": tail[:200],
        })
    return out


def _looks_like_touch(loop: dict) -> bool:
    b = loop.get("body") or ""
    return any(k in b for k in ("memcpy", "memset", "= 0.0", "=0.0", "= 0;"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True)
    ap.add_argument("--task", default="stencil")
    ap.add_argument("--measure", action="store_true",
                    help="also score with and without the touch loop")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    text = pathlib.Path(args.source).read_text()
    loops = _pragma_loops(text)
    touches = [l for l in loops if _looks_like_touch(l)]
    computes = [l for l in loops if not _looks_like_touch(l)]

    print(f"source: {args.source}")
    print(f"parallel loops: {len(loops)}  (touch-like {len(touches)}, compute {len(computes)})")
    if not touches:
        print("\n1. PRESENT: NO parallel first-touch loop found.")
        print("   On a 4-CMG machine every page then lands wherever the allocating")
        print("   thread happened to run. For the stencil, where the candidate owns")
        print("   its buffers, the corpus median with parallel init is 1.77x the")
        print("   median without, and 100% of the top decile has it.")
    else:
        print("\n1. PRESENT: yes")
    for t in touches:
        print(f"   touch  : omp {t['clause']}")
        print(f"            range {t['var']} in [{t['lo']}, {t['hi']})  "
              f"collapse={t['collapse']} schedule={t['schedule']}")

    print("\n2. MATCHED:")
    if not touches or not computes:
        print("   cannot compare — need both a touch loop and a compute loop")
    for t in touches:
        for c in computes:
            same_axis = t["var"] == c["var"]
            same_range = (t["lo"], t["hi"]) == (c["lo"], c["hi"])
            same_shape = (t["collapse"], t["schedule"]) == (c["collapse"], c["schedule"])
            verdict = ("MATCH" if (same_axis and same_range and same_shape)
                       else "MISMATCH")
            print(f"   {verdict}: touch {t['var']} [{t['lo']},{t['hi']}) "
                  f"collapse={t['collapse']}/{t['schedule']}  vs  "
                  f"compute {c['var']} [{c['lo']},{c['hi']}) "
                  f"collapse={c['collapse']}/{c['schedule']}")
            if verdict == "MISMATCH" and same_axis and same_shape and not same_range:
                print("            -> same axis and schedule but DIFFERENT bounds: "
                      "static chunking offsets the thread->index map, so each "
                      "thread computes some indices it did not touch.")
            elif verdict == "MISMATCH" and not same_shape:
                print("            -> different collapse/schedule: the thread->index "
                      "maps are unrelated, which is the corpus's actual failure.")

    result = {"source": args.source, "loops": loops,
              "n_touch": len(touches), "n_compute": len(computes)}

    if args.measure:
        print("\n3. MEASURED: scoring with the touch loop, and with it removed")
        stripped = text
        for t in touches:
            # remove the pragma line only: the loop still runs, just serially and
            # from one thread, which is exactly "no first touch"
            stripped = stripped.replace(f"#pragma omp {t['clause']}\n", "", 1)
        if stripped == text:
            print("   could not remove the touch pragma; skipping")
        else:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                alt = pathlib.Path(td, "no_touch.c")
                alt.write_text(stripped)
                for label, src in (("with first touch", args.source),
                                   ("without", str(alt))):
                    r = subprocess.run(
                        [sys.executable,
                         str(REPO / "workspace/tools/measure_absolute_performance.py"),
                         "--task", args.task, "--candidate", src, "--reps", "5"],
                        capture_output=True, text=True, timeout=7200)
                    ms = [l for l in r.stdout.splitlines() if "  " in l and "ms" not in l]
                    print(f"   {label}:")
                    for l in r.stdout.splitlines():
                        if l.strip() and l[0].isalnum() and "x" in l.split()[0]:
                            print(f"     {l}")

    out_dir = pathlib.Path(args.out) if args.out else (
        REPO / "workspace/checkpoints/first_touch")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"first_touch_{pathlib.Path(args.source).stem}.json"
    dst.write_text(json.dumps(result, indent=1))
    print(f"\nwrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
