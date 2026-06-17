#!/usr/bin/env python3
"""Analyze a handoff-study sweep into per-arm outcomes + the PREREG contrasts.

Consumes the manifest written by ``run_handoff_ablation.py`` (one line per
(arm, seed) run, with the run's experiment dir), reduces each run to its
outcome — the **best valid geomean speedup over its BFTS nodes** (the PREREG
unit of analysis is the run, not the node) — groups outcomes by arm, and
reports:

  * per-arm: success rate (runs with >=1 valid node) + geomean speedup with a
    run-level bootstrap CI;
  * the PREREG primary contrast (code_plus_summary vs code_plus_full_log) as a
    log-domain TOST equivalence test (margin = log(1.05));
  * the other pairwise differences with Holm-adjusted TOST p-values.

Pure analysis (no LLM/API). Writes ``analysis.json`` next to the manifest.

Usage:
    python scripts/analyze_handoff_ablation.py <out_dir|manifest.jsonl>
"""
from __future__ import annotations

import json
import math
import os
import sys
from glob import glob
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ari-core"))

from ari.evaluator.handoff_stats import (  # noqa: E402
    geomean, summarize_arm, tost_equivalence, holm_adjust,
)

PRIMARY = ("code_plus_summary", "code_plus_full_log")
TOST_MARGIN = math.log(1.05)  # PREREG equivalence band half-width (log units)


def run_outcome(run_dir: str | None) -> tuple[float, int, int]:
    """Reduce a run to (best_valid_geomean_speedup, n_valid_nodes, n_nodes).

    A node is valid iff the deterministic evaluator wrote a positive
    valid_geomean_speedup (it zeroes any node that fails a family). The run's
    outcome is the best such speedup; 0.0 if the run produced no valid node.
    """
    if not run_dir or not os.path.isdir(run_dir):
        return (0.0, 0, 0)
    best, n_valid, n_nodes = 0.0, 0, 0
    for rpt in glob(os.path.join(run_dir, "node_*", "node_report.json")):
        n_nodes += 1
        try:
            with open(rpt) as fh:
                d = json.load(fh)
        except Exception:
            continue
        m = d.get("metrics") or {}
        g = m.get("valid_geomean_speedup")
        if isinstance(g, (int, float)) and g > 0:
            n_valid += 1
            best = max(best, float(g))
    return (best, n_valid, n_nodes)


def lineage_stats(run_dir: str | None) -> dict:
    """Node-level, handoff-SENSITIVE stats from the run's tree.json (lineage).

    The 'best valid @ N' outcome is a max over noisy attempts — insensitive to
    handoff. Handoff acts on the DISTRIBUTION: whether a child, inheriting a
    valid parent, improves it (vs breaks it), and the overall success rate /
    mean node quality. Returns counts to aggregate across runs:
      n_nodes, n_valid, valid_speedups, child_total (children of a VALID parent),
      child_improve (child valid & >1.01x parent), child_break (child invalid).
    """
    out = {"n_nodes": 0, "n_valid": 0, "valid_speedups": [],
           "child_total": 0, "child_improve": 0, "child_break": 0}
    if not run_dir:
        return out
    # tree.json lives in the checkpoint dir paired with the experiments run dir
    ck = run_dir.replace("/experiments/", "/checkpoints/")
    tree = None
    for cand in (os.path.join(ck, "tree.json"), os.path.join(run_dir, "tree.json")):
        if os.path.isfile(cand):
            try:
                with open(cand) as fh:
                    tree = json.load(fh)
            except Exception:
                tree = None
            break
    if not tree:
        return out
    nodes = tree.get("nodes", [])
    def vg(nd):
        g = (nd.get("metrics") or {}).get("valid_geomean_speedup")
        return float(g) if isinstance(g, (int, float)) and g > 0 else 0.0
    gm = {nd.get("id"): vg(nd) for nd in nodes}
    for nd in nodes:
        out["n_nodes"] += 1
        g = vg(nd)
        if g > 0:
            out["n_valid"] += 1
            out["valid_speedups"].append(g)
        pg = gm.get(nd.get("parent_id"), 0.0)
        if pg > 0:  # parent was valid: did the child build on it or break it?
            out["child_total"] += 1
            if g > pg * 1.01:
                out["child_improve"] += 1
            elif g == 0.0:
                out["child_break"] += 1
    return out


def load_manifest(path: Path) -> list[dict]:
    mf = path / "manifest.jsonl" if path.is_dir() else path
    if not mf.is_file():
        sys.exit(f"manifest not found: {mf}")
    rows = [json.loads(line) for line in mf.read_text().splitlines() if line.strip()]
    return rows


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    target = Path(sys.argv[1]).resolve()
    rows = load_manifest(target)
    out_dir = target if target.is_dir() else target.parent

    # arm -> list of run records {seed, outcome, n_valid, n_nodes}
    by_arm: dict[str, list[dict]] = {}
    lin_by_arm: dict[str, dict] = {}
    for r in rows:
        best, nv, nn = run_outcome(r.get("run_dir"))
        by_arm.setdefault(r["arm"], []).append(
            {"seed": r.get("seed"), "outcome": best, "n_valid": nv, "n_nodes": nn}
        )
        ls = lineage_stats(r.get("run_dir"))
        agg = lin_by_arm.setdefault(r["arm"], {"n_nodes": 0, "n_valid": 0,
            "valid_speedups": [], "child_total": 0, "child_improve": 0, "child_break": 0})
        for k in ("n_nodes", "n_valid", "child_total", "child_improve", "child_break"):
            agg[k] += ls[k]
        agg["valid_speedups"].extend(ls["valid_speedups"])

    summary: dict[str, dict] = {}
    print(f"\n=== Handoff ablation: {out_dir.name} ===")
    print(f"{'arm':<22} {'runs':>5} {'valid':>6} {'geomean':>8}  95% CI   (outcome = best valid @ N)")
    for arm in sorted(by_arm):
        runs = by_arm[arm]
        valid = [x["outcome"] for x in runs if x["outcome"] > 0]
        s = summarize_arm(valid) if valid else {"n_runs": 0, "geomean": float("nan"),
                                                "ci_lo": float("nan"), "ci_hi": float("nan")}
        s["n_total"] = len(runs)
        s["n_valid_runs"] = len(valid)
        s["outcomes"] = [x["outcome"] for x in runs]
        summary[arm] = s
        print(f"{arm:<22} {len(runs):>5} {len(valid):>6} {s['geomean']:>8.2f}"
              f"  [{s['ci_lo']:.2f}, {s['ci_hi']:.2f}]")

    # Handoff-SENSITIVE distribution stats (node level, from lineage). The
    # best-valid outcome above is a max over noisy attempts; handoff acts here.
    print(f"\n{'arm':<22} {'succ%':>6} {'mean_sp':>8} {'child improve/break/tot':>24}")
    for arm in sorted(lin_by_arm):
        a = lin_by_arm[arm]
        vs = a["valid_speedups"]
        msp = geomean(vs) if vs else float("nan")
        succ = 100.0 * a["n_valid"] / a["n_nodes"] if a["n_nodes"] else float("nan")
        ct = a["child_total"]
        s = summary.setdefault(arm, {})
        s["node_success_rate"] = succ / 100.0 if a["n_nodes"] else None
        s["node_mean_geomean"] = msp
        s["n_nodes"] = a["n_nodes"]
        s["child_total"] = ct
        s["child_improve_rate"] = (a["child_improve"] / ct) if ct else None
        s["child_break_rate"] = (a["child_break"] / ct) if ct else None
        print(f"{arm:<22} {succ:>5.0f}% {msp:>8.1f}"
              f"  {a['child_improve']:>3}/{a['child_break']:<3}/{ct:<3}"
              f"  (imp {100*a['child_improve']/ct if ct else 0:.0f}% / brk {100*a['child_break']/ct if ct else 0:.0f}%)")

    # PREREG primary contrast: equivalence (TOST) in log-speedup.
    contrasts = {}
    a_name, b_name = PRIMARY
    a = [x for x in summary.get(a_name, {}).get("outcomes", []) if x > 0]
    b = [x for x in summary.get(b_name, {}).get("outcomes", []) if x > 0]
    if len(a) >= 2 and len(b) >= 2:
        t = tost_equivalence([math.log(v) for v in a], [math.log(v) for v in b],
                             margin=TOST_MARGIN)
        contrasts[f"{a_name}_vs_{b_name}"] = t
        print(f"\nPRIMARY (TOST equivalence, margin=log(1.05)): "
              f"{a_name} vs {b_name}")
        print(f"  mean log-diff={t['mean_diff']:+.4f}  equivalent={t['equivalent']}  "
              f"(geomean ratio={math.exp(t['mean_diff']):.3f}x)")
    else:
        print(f"\nPRIMARY: insufficient valid runs (need >=2 each; have "
              f"{len(a)} / {len(b)}) — add seeds.")

    # Secondary pairwise TOSTs (Holm-adjusted) for context. The PREREG primary
    # contrast is confirmatory and reported UN-adjusted above, so it is excluded
    # here — including it would both violate the protocol and corrupt the
    # secondary arms' step-down adjusted p-values.
    arms = sorted(summary)
    primary_set = frozenset(PRIMARY)
    pairs, pvals = [], []
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            if frozenset((arms[i], arms[j])) == primary_set:
                continue  # primary contrast: confirmatory, not Holm-adjusted
            ai = [x for x in summary[arms[i]]["outcomes"] if x > 0]
            aj = [x for x in summary[arms[j]]["outcomes"] if x > 0]
            if len(ai) >= 2 and len(aj) >= 2:
                t = tost_equivalence([math.log(v) for v in ai], [math.log(v) for v in aj],
                                     margin=TOST_MARGIN)
                pairs.append((arms[i], arms[j], t))
                pvals.append(max(t["p_lower"], t["p_upper"]))
    if pairs:
        adj = holm_adjust(pvals)
        print("\nPairwise (Holm-adjusted TOST p):")
        for (ai, aj, t), p in zip(pairs, adj):
            contrasts[f"{ai}_vs_{aj}"] = {**t, "holm_p": p}
            print(f"  {ai:<20} vs {aj:<20} ratio={math.exp(t['mean_diff']):.3f}x  holm_p={p:.3f}")

    result = {"out_dir": str(out_dir), "n_runs": len(rows),
              "arms": summary, "contrasts": contrasts,
              "tost_margin_log": TOST_MARGIN}
    (out_dir / "analysis.json").write_text(json.dumps(result, indent=2))
    print(f"\nwrote {out_dir / 'analysis.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
