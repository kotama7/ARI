"""Do two harnesses agree about which candidate is better?

WHY THE POOL EXISTS. Choosing a harness is only half the point. The other half is
asking whether a finding survives the choice. If two defensible harnesses order
two candidates differently, then "candidate A is better" was a claim about the
harness as much as about the code, and a paper that reports it as a property of
the code is reporting something it did not establish.

THIS IS NOT PART OF SELECTION. Selection reads declarations and is structurally
denied access to scores, because "pick the harness where the candidate does best"
is a machine for score hacking. This tool is the opposite: it exists to read
scores. Keep them apart. Nothing here may ever feed back into `harness_select`,
and if that wiring ever looks tempting, the thing being built is a score-hacking
loop with extra steps.

THREE RULES THAT MAKE THE COMPARISON HONEST.

1. **Only orderings are compared, never scores.** Two harnesses with different
   denominators and different problems produce numbers on different scales by
   construction. "gemm scored 1.2 here and 0.8 there" says nothing; "this one
   ranks A above B and that one does not" says everything.

2. **A pair inside a harness's band is NOT an opinion.** If two candidates differ
   by less than the smallest difference a harness can resolve, that harness has
   no view about them, and counting it as either agreement or disagreement is a
   fabrication. Such pairs are reported separately as ABSTENTIONS. This is why
   the declared band matters here and not only at selection time.

3. **A candidate missing from one harness is reported, never dropped.** Agent
   code may fail to build under a variant. Silently comparing only the
   candidates that ran everywhere biases the comparison toward candidates that
   are easy to build, which is not the property under study.

INPUT
    A JSON mapping: {"<harness>": {"<candidate>": <score>, ...}, ...}
    plus, optionally, the declared band per harness so abstentions can be found:
    {"bands": {"<harness>": 0.00251}}

USAGE
    python compare_harnesses.py scores.json
    python compare_harnesses.py scores.json --json out.json
"""
import argparse
import itertools
import json
import pathlib
import sys


def _pair_view(scores: dict, a: str, b: str, band: float | None) -> str:
    """One harness's view of an ordered pair: 'a', 'b', or 'abstain'."""
    if a not in scores or b not in scores:
        return "missing"
    x, y = float(scores[a]), float(scores[b])
    if band is not None:
        denom = max(abs(x), abs(y))
        if denom > 0 and abs(x - y) / denom < band:
            return "abstain"
    if x == y:
        return "abstain"
    return a if x > y else b


def compare(by_harness: dict, bands: dict | None = None) -> dict:
    """Pairwise agreement between every pair of harnesses."""
    bands = bands or {}
    names = sorted(by_harness)
    everyone = sorted({c for s in by_harness.values() for c in s})
    coverage = {h: sorted(set(everyone) - set(by_harness[h])) for h in names}

    out = {"harnesses": names, "candidates": everyone,
           "missing_from": {h: v for h, v in coverage.items() if v},
           "pairs": []}

    for h1, h2 in itertools.combinations(names, 2):
        agree = disagree = abstained = incomparable = 0
        conflicts = []
        for a, b in itertools.combinations(everyone, 2):
            v1 = _pair_view(by_harness[h1], a, b, bands.get(h1))
            v2 = _pair_view(by_harness[h2], a, b, bands.get(h2))
            if "missing" in (v1, v2):
                incomparable += 1
            elif "abstain" in (v1, v2):
                abstained += 1
            elif v1 == v2:
                agree += 1
            else:
                disagree += 1
                conflicts.append({"pair": [a, b], h1: v1, h2: v2})
        decided = agree + disagree
        out["pairs"].append({
            "harnesses": [h1, h2], "agree": agree, "disagree": disagree,
            "abstained": abstained, "incomparable": incomparable,
            # None, not 1.0, when nothing was decided: an agreement rate over
            # zero decided pairs is not perfect agreement, it is no evidence.
            "agreement": (agree / decided) if decided else None,
            "conflicts": conflicts[:20],
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scores", help="JSON: {harness: {candidate: score}}")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    doc = json.loads(pathlib.Path(args.scores).read_text())
    bands = doc.pop("bands", {})
    result = compare(doc, bands)

    if len(result["harnesses"]) < 2:
        print("fewer than two harnesses: there is nothing to compare. A pool "
              "with one member cannot tell you whether a finding depends on "
              "the harness.", file=sys.stderr)
        return 2

    for h, missing in result["missing_from"].items():
        print(f"{h}: {len(missing)} candidate(s) absent — {', '.join(missing[:6])}"
              + (" ..." if len(missing) > 6 else ""))
    if result["missing_from"]:
        print("  Absent candidates are excluded from the pairs below and "
              "reported here on purpose: comparing only what ran everywhere\n"
              "  would favour candidates that are easy to build, which is not "
              "the property under study.\n")

    disagreed = False
    for p in result["pairs"]:
        h1, h2 = p["harnesses"]
        rate = "n/a" if p["agreement"] is None else f"{p['agreement']*100:.1f}%"
        print(f"{h1} vs {h2}: {rate} agreement over {p['agree']+p['disagree']} "
              f"decided pairs "
              f"({p['abstained']} inside a band, {p['incomparable']} incomparable)")
        for c in p["conflicts"]:
            a, b = c["pair"]
            print(f"    {a} vs {b}: {h1} prefers {c[h1]}, {h2} prefers {c[h2]}")
        if p["disagree"]:
            disagreed = True
        if p["agreement"] is None:
            print("    nothing was decided: every pair fell inside a band or "
                  "was missing. This is not agreement — it is an absence of "
                  "evidence, and reporting it as 100% would invert its meaning.")

    if disagreed:
        print("\nThe harnesses order some candidates differently. Any claim that "
              "one candidate\nis better is, for those pairs, a claim about the "
              "harness as much as the code.")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(result, indent=1))
        print(f"\nwrote {args.json}")
    return 1 if disagreed else 0


if __name__ == "__main__":
    raise SystemExit(main())
