# scripts/docs

Documentation lint/gate scripts run against the `docs/` tree.

## Contents

- `README.md` — this file.
- `assemble_site.sh` — assemble the single Pages artifact `_site/` (L3): bespoke landing at the root, VitePress dist at `/docs/`, a noindex `docs.html` redirect stub, and `.nojekyll`. Run after `vitepress build`.
- `check_doc_links.py` — verify intra-docs links and HTML hrefs resolve to real files.
- `check_doc_sources.py` — validate the `sources` front-matter each doc declares against the tree.
- `check_i18n_js.py` — verify `docs/i18n/landing.{en,ja,zh}.js` declare an identical key set (the docs surface moved to VitePress in L3).
- `check_readme_parity.py` — verify root `README.{md,ja,zh}` share one Markdown heading shape (fence-aware).
- `check_ref_coupling.py` — diff gate (warn): a changed `sources:` file should bump its referencing doc's `last_verified`.
- `check_report_cochange.py` — diff gate: `report/{en,ja,zh}` language-paired files (chapters, strings, main) must change together in a PR.
- `check_site_i18n.py` — HTML-site i18n integrity: surface parity (reuses `check_i18n_js`), no orphan `t-` ids, en→ja/zh co-change, report-PDF sync, and version single-source.
- `check_translation_freshness.py` — detect translation drift via `last_verified` front-matter.
- `sync_report_pdf.sh` — mirror `report/{en,ja,zh}/main.pdf` into `docs/assets/report/<lang>.pdf` (landing) and `docs/public/report/<lang>.pdf` (VitePress); `--check` fails on drift.
