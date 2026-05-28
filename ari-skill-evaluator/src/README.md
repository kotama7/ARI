# ari-skill-evaluator/src

MCP server package for the evaluator skill — a data extractor (not a judge):
LLM-generated extractors pull metrics out of node artefacts and return
`(metrics, has_real_data, extractor_code)`. `__init__.py` is empty; the
package is imported via `where = ["src"]` (see `pyproject.toml`).

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `server.py` — MCP entry point exposing `make_artifact_extractor` / `evaluate`.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
