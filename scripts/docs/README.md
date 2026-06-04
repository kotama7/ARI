# scripts/docs

Documentation lint/gate scripts run against the `docs/` tree.

## Contents

- `README.md` — this file.
- `check_doc_links.py` — verify intra-docs links and HTML hrefs resolve to real files.
- `check_doc_sources.py` — validate the `sources` front-matter each doc declares against the tree.
- `check_i18n_js.py` — verify `docs/i18n/{en,ja,zh}.js` declare an identical set of string keys.
- `check_readme_parity.py` — verify root `README.{md,ja,zh}` share one Markdown heading shape (fence-aware).
- `check_ref_coupling.py` — diff gate (warn): a changed `sources:` file should bump its referencing doc's `last_verified`.
- `check_report_cochange.py` — diff gate: `report/{en,ja,zh}` language-paired files (chapters, strings, main) must change together in a PR.
- `check_translation_freshness.py` — detect translation drift via `last_verified` front-matter.
