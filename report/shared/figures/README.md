# report/shared/figures

Generated and source figures shared across the en/ja/zh report builds.

## Contents

- `README.md` — this file.
- `CLAUDE.md` — figure-authoring contract.
- `style.tikzstyles` — shared TikZ styles.
- `data/` — figure data files (not enumerated)
- `dot/` — Graphviz figure sources (not enumerated)
- `pgf/` — generated PGF figures (not enumerated)
- `scripts/` — figure generation scripts (not enumerated).
  - `build_all.py` — regenerate all data-driven figures (`--only Fxx` for one); idempotent for git-diff drift checks.
  - `rubric_dist.py` — F09: rubric score-distribution violin plot (`data/F09_reviews.jsonl` → `pgf/F09_rubric_dist.pgf`).
  - `rubric_render.py` — F07: rubric tree (`data/F07_rubric.yaml` → `dot/` + TikZ via dot2tex).
  - `standalone.tex.tmpl` — auto-generated LaTeX wrapper for stand-alone TikZ rendering (article class).
  - `style.mplstyle` — pinned matplotlib PGF style (Okabe-Ito palette, fonts owned by the LaTeX preamble).
  - `tree_curve.py` — F08: best-reward vs exploration-step curve per seed (`data/F08_curve.csv` → `pgf/F08_curve.pgf`).
  - `tree_render.py` — F02: example BFTS tree from frozen `data/F02_tree.json` → `dot/` only (the TikZ realisation `tikz/F02_tree.tex` is hand-maintained in the `_style.tex` house language).
- `tikz/` — TikZ figure sources (not enumerated)
