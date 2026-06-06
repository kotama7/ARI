# ari-skill-idea/src

MCP server package for the idea skill — literature survey (deterministic:
arXiv + Semantic Scholar) and LLM-based research-idea generation, the latter
adapted from VirSci's multi-agent discussion flow. `__init__.py` is empty; the
package is imported as `src`.

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `server.py` — MCP entry point (`survey`, `generate_ideas`); wraps the vendored VirSci core under `vendor/virsci/`. `generate_ideas` gates the real vendor-wrap engine on `ARI_IDEA_VIRSCI_REAL` and degrades to the re-implemented discussion loop otherwise (see `_virsci_*` env helpers, `_run_real_virsci`).
- `snapshot.py` — Semantic Scholar live-snapshot builder (`build_snapshot`): corpus + `embedding.specter_v2` faiss index + author profiles + co-author adjacency, frozen under `<out_dir>/virsci_snapshot/` (the freshness/diversity/retrieval source for the real path).
- `virsci_runtime.py` — Vendor-wrap runtime: meta-path auto-stubber (imports the vendored VirSci with `vendor/` unedited), `LivePlatform` (snapshot-grounded `Platform` subclass + SPECTER2 `reference_paper`), `build_model_configs` (ARI shim), and the `run_virsci_live` driver (real `select_coauthors` + `generate_idea`).

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools, attribution & VirSci integration points.
