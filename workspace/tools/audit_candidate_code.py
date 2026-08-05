"""What optimisations does this code actually contain? (MUKUNOKI: コードの分析)

THE REVIEW POINT THIS ANSWERS. "データの取り直しとコードの分析は必須" — a score
says a candidate was fast, not what it did. This classifies a source into the
optimisation techniques it actually contains, so a claim like "the search found
blocking" can be checked rather than assumed.

IT IS DELIBERATELY LITERAL. The markers are regexes over the source, small
enough to audit by eye, because a fuzzy classifier would be impossible to
defend. That has a known consequence, and the corpus shows it: the best stencil
candidate's own comment claims "temporal blocking: process all sweeps in one
pass" and there is no temporal blocking in it — it keeps ONE parallel region
open across sweeps, which is a real saving but a different one. So a comment is
never evidence; only the code markers count, and `--comments` reports what the
source CLAIMS separately so the two can be compared.

WHAT IT FOUND ON THE PRELIMINARY CORPUS, as calibration for reading its output:
not one of the 87 best gemm candidates carried a blocking constant, and the
single best was textbook ikj plus the vectorisation flag. "The search found good
optimisations" was not true there, and this is the tool that shows it.

USAGE
    python audit_candidate_code.py --source PATH [--comments]
    python audit_candidate_code.py --corpus DIR --task gemm --top 10
"""
import argparse
import json
import pathlib
import re
from collections import Counter

REPO = pathlib.Path(__file__).resolve().parents[2]

CATEGORIES = {
    "schedule": {
        "prose": r"schedul|chunk|static|dynamic|guided|load[- ]balanc",
        "code": r"schedule\s*\(",
    },
    "blocking": {
        "prose": r"block|tile|tiling|cache[- ]block",
        "code": r"\b(BLOCK|TILE|BS|MR|NR|KC|NC|MC)\b|for\s*\(\s*\w+\s*=\s*\w+\s*;.*\+=\s*\w*(BLOCK|TILE|BS)",
    },
    "vectorise": {
        "prose": r"simd|vector|sve|neon|intrinsic",
        "code": r"#pragma\s+omp\s+simd|svfloat|vld1|__builtin_.*vec",
    },
    "unroll": {
        "prose": r"unroll",
        "code": r"#pragma\s+(GCC\s+)?unroll|#pragma\s+omp\s+simd\s+.*unroll",
    },
    "prefetch": {
        "prose": r"prefetch",
        "code": r"__builtin_prefetch|svprf",
    },
    "numa_first_touch": {
        "prose": r"numa|first[- ]touch|page|affinity",
        # A parallel loop whose BODY writes the buffers — the write may be
        # several lines below the pragma (declarations, an opening brace), so
        # this scans a window rather than the next line. The one-line version
        # matched NONE of the ordinary spellings, including the frozen
        # reference's own touch loop, and so reported first touch as absent
        # wherever it was written normally.
        "code": r"#pragma\s+omp\s+parallel\s+for(?:[^\n]*\n){1,6}[^\n]*(?:memset|memcpy|=\s*0\.0|=\s*0\.0f|\[[^\]]*\]\s*=\s*0)",
    },
    "restrict_alias": {
        "prose": r"restrict|alias|__restrict",
        "code": r"__restrict",
    },
    "flags": {
        "prose": r"flag|-O[0-9]|ffast-math|march|compil",
        "code": r"",           # handled separately from candidate_flags.txt
    },
}


_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)


def classify_source(text: str) -> dict:
    """Marker counts per category, from CODE only (comments stripped)."""
    code = _COMMENT.sub(" ", text)
    out = {}
    for name, pat in CATEGORIES.items():
        if not pat["code"]:
            continue
        out[name] = len(re.findall(pat["code"], code, re.I))
    return out


def classify_comments(text: str) -> dict:
    """Categories the source CLAIMS in its comments — never evidence, only a
    claim to check against the code."""
    said = " ".join(m.group(0) for m in _COMMENT.finditer(text)).lower()
    return {name: bool(re.search(pat["prose"], said))
            for name, pat in CATEGORIES.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source")
    ap.add_argument("--corpus", help="directory of run dirs to summarise")
    ap.add_argument("--task", default="gemm")
    ap.add_argument("--top", type=int, default=10, help="report the top N%% by score")
    ap.add_argument("--comments", action="store_true",
                    help="also show what the comments CLAIM, and flag disagreement")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.source:
        text = pathlib.Path(args.source).read_text()
        code = classify_source(text)
        print(f"source: {args.source}")
        print(f"{'technique':20s} {'markers in code':>16s}")
        for k, v in sorted(code.items(), key=lambda kv: -kv[1]):
            print(f"{k:20s} {v:16d}")
        if args.comments:
            said = classify_comments(text)
            print()
            print("claims in comments vs markers in code:")
            for k in sorted(said):
                c = code.get(k, 0)
                if said[k] and c == 0:
                    print(f"  {k:20s} CLAIMED but no code marker  <-- check this")
                elif said[k]:
                    print(f"  {k:20s} claimed, {c} marker(s)")
        result = {"source": args.source, "code": code}
    elif args.corpus:
        root = pathlib.Path(args.corpus)
        rows = []
        for nr in root.glob(f"*{args.task}*/node_*/node_report.json"):
            try:
                rep = json.loads(nr.read_text())
            except Exception:
                continue
            m = rep.get("metrics") or {}
            s = m.get("valid_geomean_speedup") or m.get("_scientific_score")
            src = next(iter(nr.parent.glob(f"candidate_{args.task}.c")), None)
            if not (isinstance(s, (int, float)) and s > 0 and src):
                continue
            rows.append((float(s), classify_source(src.read_text())))
        if not rows:
            print("no scored candidates found"); return 1
        rows.sort(key=lambda r: -r[0])
        cut = max(1, len(rows) * args.top // 100)
        print(f"{args.task}: {len(rows)} scored candidates; top {args.top}% = {cut}")
        print(f"{'technique':20s} {'top decile':>11s} {'all':>8s}")
        for name in sorted(CATEGORIES):
            if not CATEGORIES[name]["code"]:
                continue
            t = sum(1 for _, c in rows[:cut] if c.get(name, 0) > 0) / cut * 100
            a = sum(1 for _, c in rows if c.get(name, 0) > 0) / len(rows) * 100
            print(f"{name:20s} {t:10.1f}% {a:7.1f}%")
        result = {"task": args.task, "n": len(rows), "top_n": cut}
    else:
        ap.error("give --source or --corpus")

    out_dir = pathlib.Path(args.out) if args.out else (
        REPO / "workspace/checkpoints/code_audit")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "code_audit.json"
    dst.write_text(json.dumps(result, indent=1))
    print(f"\nwrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
