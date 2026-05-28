# report/scripts

Build and CI-check scripts for the en/ja/zh report (HTML rendering, figures, bibliography, prompt snapshots).

## Contents

- `README.md` — this file.
- `build_html.sh` — drive the pandoc HTML build for one or all languages.
- `build_html_pandoc.py` — render the report HTML via pandoc (replaces the old make4ht toolchain).
- `build_tables.py` — auto-generate report tables T2 (skill × role) and T3 (env vars) from implementation source.
- `check_bib.py` — Gate 4 / C1..C11 bibliography validation (DOI resolves, title match, etc.).
- `check_figures.py` — figure lint check.
- `check_glossary.py` — Gate 7 glossary term-ban check.
- `check_i18n.py` — Gate 6 i18n structural-parity check across en/ja/zh.
- `check_logs_for_secrets.py` — scan logs for leaked secrets.
- `check_notation.py` — notation-macro registration check.
- `check_prompt_snapshots.py` — Gate 10 Appendix prompt snapshots match upstream `ari-core` prompts.
- `check_tikz.py` — TikZ source lint check.
- `check_toc_consistency.py` — table-of-contents consistency check.
- `fetch_bib.py` — fetch a BibTeX entry from a primary source, verify against Semantic Scholar, append to `shared/references.bib` + log.
- `inject_langnav.py` — inject the en | ja | zh language switcher into the generated HTML index.
- `normalize_title.py` — normalize a paper title for cross-source comparison.
- `paperbench_report.py` — PaperBench audit report generator (per-paper LaTeX + figures).
- `pull_pdfs.py` — re-download reference PDFs missing locally, per `shared/references_pdf/<key>.pdf.meta.yaml`.
- `render_tikz.py` — standalone TikZ render for visual inspection (`make figure FIG=<name>`).
- `requirements.txt` — pins the report-pipeline Python deps.
- `snapshot_prompts.py` — snapshot runtime LLM prompts into the report Appendix.
- `test_paperbench_report.py` — tests for `paperbench_report.py`.
