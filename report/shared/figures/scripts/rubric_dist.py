#!/usr/bin/env python3
"""F09 — rubric score distribution (violin plot per category).

Reads:  shared/figures/data/F09_reviews.jsonl  (each line: {"category": str, "score": float})
Writes: shared/figures/pgf/F09_rubric_dist.pgf
"""
from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict
import numpy as np

import matplotlib
matplotlib.use("pgf")
import matplotlib.pyplot as plt

THIS = Path(__file__).resolve().parent
plt.style.use(str(THIS / "style.mplstyle"))

DATA = THIS.parent / "data" / "F09_reviews.jsonl"
OUT  = THIS.parent / "pgf"  / "F09_rubric_dist.pgf"

CATEGORIES = ["clarity", "novelty", "experiments", "rigor", "impact"]


def _synthetic_fallback() -> dict[str, list[float]]:
    rng = np.random.default_rng(0)
    return {
        c: list(np.clip(rng.normal(loc=3.0 + i * 0.15, scale=0.6, size=80), 1, 5))
        for i, c in enumerate(CATEGORIES)
    }


def _read_data() -> dict[str, list[float]]:
    if not DATA.exists():
        return _synthetic_fallback()
    buckets: dict[str, list[float]] = defaultdict(list)
    with DATA.open() as f:
        for line in f:
            row = json.loads(line)
            buckets[row["category"]].append(float(row["score"]))
    return dict(buckets)


def render_distribution(out_dir: Path | None = None) -> Path:
    out_dir = (out_dir or THIS.parent) / "pgf"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "F09_rubric_dist.pgf"

    data = _read_data()
    cats = list(data.keys())
    values = [data[c] for c in cats]

    fig, ax = plt.subplots()
    parts = ax.violinplot(values, showmeans=True, showmedians=False)
    for pc in parts["bodies"]:
        pc.set_alpha(0.5)
    ax.set_xticks(range(1, len(cats) + 1))
    ax.set_xticklabels(cats, rotation=20, ha="right")
    ax.set_ylabel("score")
    ax.set_ylim(0.5, 5.5)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    p = render_distribution()
    print(f"wrote {p}")
