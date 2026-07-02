# report/shared

Shared assets included by every language build (en/ja/zh) of the report.

## Contents

- `README.md` — this file.
- `glossary.yaml` — glossary terms (+ `forbidden_alternatives`).
- `i18n.json` — per-language UI strings.
- `notation.tex` — notation macros (gate-registered symbols).
- `preamble.tex` — common LaTeX preamble.
- `references.bib` — bibliography (BibTeX).
- `appendix/` — verbatim appendix material (prompt snapshots).
  - `README.md` — appendix index.
  - `prompts/` — runtime LLM prompt snapshots, grouped by subsystem.
    - `README.md` — prompts index.
    - `agent/` — agent prompt snapshots (auto-generated): `system.md`.
      - `system.md` — agent system prompt.
    - `evaluator/` — evaluator prompt snapshots (auto-generated): `extract_metrics.md`, `peer_review.md`.
      - `extract_metrics.md` — metric-extraction prompt.
      - `peer_review.md` — peer-review prompt.
    - `orchestrator/` — orchestrator prompt snapshots (auto-generated): `bfts_expand.md`, `bfts_expand_select.md`, `bfts_select.md`, `lineage_decision.md`, `root_idea_selector.md`.
      - `bfts_expand.md` — BFTS expand prompt.
      - `bfts_expand_select.md` — BFTS combined expand+select prompt.
      - `bfts_select.md` — BFTS select prompt.
      - `lineage_decision.md` — lineage-decision prompt.
      - `root_idea_selector.md` — root-idea selection prompt.
    - `pipeline/` — pipeline prompt snapshots (auto-generated): `keyword_librarian.md`.
      - `keyword_librarian.md` — keyword-librarian prompt.
    - `viz/` — viz prompt snapshots (auto-generated): `wizard_chat_goal.md`, `wizard_generate_config.md`.
      - `wizard_chat_goal.md` — wizard chat goal prompt.
      - `wizard_generate_config.md` — wizard config-generation prompt.
- `assets/` — binary assets embedded into the report build.
  - `sample_paper.pdf` — the autonomously generated sample paper, bound in full into the appendix (`\includepdf`, "The Generated Sample Paper").
- `figures/` — shared figure sources, previews, and generation scripts.
  - `README.md` — figures index.
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
- `references_pdf/` — This directory holds local copies of papers cited in `../references.bib`
- `tables/` — TODO
