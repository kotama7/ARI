# ari-skill-paper/src

MCP server package for the paper skill — AI Scientist v2-style iterative
LaTeX paper generation (generate → review → revise per section), plus a
rubric-driven peer-review engine. `__init__.py` is empty; the package is
imported as `src`.

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `review_engine.py` — rubric-driven review pipeline (score dimensions, reflection loop, few-shot).
- `rubric.py` — venue-agnostic YAML rubric loader/validator (sha256 for P2 determinism).
- `server.py` — MCP entry point exposing `write_paper_iterative`.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
