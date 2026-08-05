"""Did a Reflection's proposal reach the child's code, and did it help?

This is the analysis the review asked for by name: "Reflection がどのような最適化
方針を提案したのか / 子ノードがその提案を実際に採用したのか / その結果、探索経路や
性能がどのように変化したのか". Final scores alone cannot answer it, and without
it "Reflection did not help" is a claim about an outcome with no mechanism.

It runs entirely on the existing corpus - no new measurement.

METHOD, and its limits stated up front. For every parent->child pair in the
+reflection arm: take the parent's next_steps_hints, classify each proposal into
an optimisation CATEGORY by keyword, diff the parent's and child's candidate
source, classify the diff into the same categories, and call a proposal ADOPTED
when its category appears in the child's diff. Then compare the child's score
with the parent's.

That is a proxy, not a reading of intent: a child could block its loops for its
own reasons and be counted as having adopted a blocking proposal. So the script
(a) reports the base rate - how often a category shows up in the OTHER arms,
which received no proposals at all - and (b) prints a sample of pairs for manual
checking. Without the base rate an adoption rate is meaningless, because most
of these categories are things an optimising agent does anyway.
"""
import json
import pathlib
import re
import statistics
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2] / "workspace/experiments"
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


OUT = _out_dir("reflection_trajectory")

# Categories of HPC optimisation, with the words a PROPOSAL uses and the code
# markers a DIFF shows. Kept deliberately small and literal; a fuzzy classifier
# would be impossible to audit.
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


def classify_prose(text: str) -> set:
    t = (text or "").lower()
    return {c for c, pat in CATEGORIES.items() if re.search(pat["prose"], t)}


def classify_code_delta(before: str, after: str) -> set:
    """Categories whose marker count CHANGED between the two sources."""
    out = set()
    for c, pat in CATEGORIES.items():
        if not pat["code"]:
            continue
        nb = len(re.findall(pat["code"], before or "", re.I))
        na = len(re.findall(pat["code"], after or "", re.I))
        if nb != na:
            out.add(c)
    return out


def score_of(rep: dict):
    m = rep.get("metrics") or {}
    for k in ("valid_geomean_speedup", "geomean_speedup", "_scientific_score"):
        v = m.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def load_arm(pattern: str):
    """-> {node_id: (report, source_text, flags_text, run_dir)}"""
    nodes = {}
    for nr in ROOT.glob(f"{pattern}/node_*/node_report.json"):
        try:
            rep = json.loads(nr.read_text())
        except Exception:
            continue
        d = nr.parent
        src = ""
        for cand in d.glob("candidate_*.c"):
            try:
                src = cand.read_text(errors="ignore")
            except OSError:
                pass
            break
        fl = ""
        f = d / "candidate_flags.txt"
        if f.is_file():
            try:
                fl = f.read_text(errors="ignore")
            except OSError:
                pass
        nodes[str(rep.get("node_id") or d.name)] = (rep, src, fl, d.parent.name)
    return nodes


def main():
    arms = {
        "evidence_plus_reflection": load_arm("*evidence_plus_reflection*"),
        "evidence_only": load_arm("*evidence_only*"),
        "code_only": load_arm("*code_only*"),
    }
    for a, n in arms.items():
        print(f"{a:26s} {len(n):5d} nodes")
    print()

    # ── base rate: how often does each category CHANGE parent->child anyway? ──
    print("=" * 78)
    print("BASE RATE — how often each category changes parent->child, per arm")
    print("(the +reflection arm is the only one that received proposals; the other")
    print(" two are what an agent does unprompted, and an adoption rate that does")
    print(" not clear them means nothing)")
    print("=" * 78)
    base = {}
    for arm, nodes in arms.items():
        counts = Counter()
        pairs = 0
        for nid, (rep, src, fl, run) in nodes.items():
            pid = rep.get("parent_id")
            if not pid or pid not in nodes:
                continue
            psrc = nodes[pid][1]
            if not psrc or not src:
                continue
            pairs += 1
            for c in classify_code_delta(psrc, src):
                counts[c] += 1
            if fl.strip() != nodes[pid][2].strip():
                counts["flags"] += 1
        base[arm] = (pairs, counts)
        print(f"\n{arm}  ({pairs} parent-child pairs with both sources)")
        for c in CATEGORIES:
            n = counts.get(c, 0)
            print(f"    {c:18s} {n:5d}  {100*n/max(pairs,1):5.1f}%")

    # ── adoption: proposal category present in the child's diff ──────────────
    print()
    print("=" * 78)
    print("ADOPTION — parent's proposal category vs the child's actual code change")
    print("=" * 78)
    nodes = arms["evidence_plus_reflection"]
    prop_total = Counter()
    prop_adopted = Counter()
    deltas_adopted, deltas_not = [], []
    samples = []
    for nid, (rep, src, fl, run) in nodes.items():
        pid = rep.get("parent_id")
        if not pid or pid not in nodes:
            continue
        prep, psrc, pfl, _ = nodes[pid]
        if not psrc or not src:
            continue
        hints = prep.get("next_steps_hints") or []
        if not isinstance(hints, list) or not hints:
            continue
        changed = classify_code_delta(psrc, src)
        if fl.strip() != pfl.strip():
            changed.add("flags")
        ps, cs = score_of(prep), score_of(rep)
        rel = (cs / ps - 1.0) if (ps and cs) else None
        for h in hints:
            for c in classify_prose(str(h)):
                prop_total[c] += 1
                if c in changed:
                    prop_adopted[c] += 1
                    if rel is not None:
                        deltas_adopted.append(rel)
                    if len(samples) < 6:
                        samples.append((pid[-8:], nid[-8:], c, str(h)[:110],
                                        None if rel is None else round(100 * rel, 2)))
                elif rel is not None:
                    deltas_not.append(rel)

    print(f"\n{'category':18s} {'proposed':>9s} {'adopted':>8s} {'rate':>7s} "
          f"{'base(evid)':>11s} {'base(code)':>11s}")
    for c in CATEGORIES:
        t, a = prop_total.get(c, 0), prop_adopted.get(c, 0)
        if not t:
            continue
        be = 100 * base["evidence_only"][1].get(c, 0) / max(base["evidence_only"][0], 1)
        bc = 100 * base["code_only"][1].get(c, 0) / max(base["code_only"][0], 1)
        print(f"{c:18s} {t:9d} {a:8d} {100*a/t:6.1f}% {be:10.1f}% {bc:10.1f}%")

    def summ(v, label):
        if len(v) < 5:
            print(f"  {label:34s} n={len(v)} too few")
            return
        print(f"  {label:34s} n={len(v):5d}  median {100*statistics.median(v):+7.2f}%  "
              f"mean {100*statistics.mean(v):+7.2f}%")

    print()
    print("CHILD SCORE CHANGE vs PARENT, split by whether the proposal was adopted:")
    summ(deltas_adopted, "proposal adopted")
    summ(deltas_not, "proposal not adopted")

    print()
    print("SAMPLES for manual checking (the keyword match is a proxy, not intent):")
    for p, c, cat, h, d in samples:
        print(f"  {p} -> {c}  [{cat}]  delta={d}%")
        print(f"      proposal: {h}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trajectory.json").write_text(json.dumps({
        "base_rate": {a: {"pairs": p, "counts": dict(c)} for a, (p, c) in base.items()},
        "proposed": dict(prop_total),
        "adopted": dict(prop_adopted),
        "n_delta_adopted": len(deltas_adopted),
        "n_delta_not": len(deltas_not),
        "median_delta_adopted": (statistics.median(deltas_adopted)
                                 if len(deltas_adopted) >= 5 else None),
        "median_delta_not": (statistics.median(deltas_not)
                             if len(deltas_not) >= 5 else None),
    }, indent=1))
    print(f"\nwrote {OUT / 'trajectory.json'}")


if __name__ == "__main__":
    main()
