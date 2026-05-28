# ari-skill-idea/src

MCP server package for the idea skill — literature survey (deterministic:
arXiv + Semantic Scholar) and LLM-based research-idea generation, the latter
adapted from VirSci's multi-agent discussion flow. `__init__.py` is empty; the
package is imported as `src`.

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `server.py` — MCP entry point (`survey`, `make_metric_spec`, `generate_ideas`); wraps the vendored VirSci core under `vendor/virsci/`.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools, attribution & VirSci integration points.
