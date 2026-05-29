# scripts/docs

Documentation lint/gate scripts run against the `docs/` tree.

## Contents

- `README.md` — this file.
- `check_doc_links.py` — verify intra-docs links and HTML hrefs resolve to real files.
- `check_doc_sources.py` — validate the `sources` front-matter each doc declares against the tree.
- `check_translation_freshness.py` — detect translation drift via `last_verified` front-matter.
