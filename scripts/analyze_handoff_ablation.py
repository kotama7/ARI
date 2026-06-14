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
            d = json.load(open(rpt))
        except Exception:
            continue
        m = d.get("metrics") or {}
        g = m.get("valid_geomean_speedup")
        if isinstance(g, (int, float)) and g > 0:
            n_valid += 1
            best = max(best, float(g))
    return (best, n_valid, n_nodes)


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
    for r in rows:
        best, nv, nn = run_outcome(r.get("run_dir"))
        by_arm.setdefault(r["arm"], []).append(
            {"seed": r.get("seed"), "outcome": best, "n_valid": nv, "n_nodes": nn}
        )

    summary: dict[str, dict] = {}
    print(f"\n=== Handoff ablation: {out_dir.name} ===")
    print(f"{'arm':<22} {'runs':>5} {'valid':>6} {'geomean':>8}  95% CI")
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

    # Secondary pairwise TOSTs (Holm-adjusted) for context.
    arms = sorted(summary)
    pairs, pvals = [], []
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
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
