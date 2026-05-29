# ari-skill-coding/src

MCP server package for the coding skill — the agent's "hands": writes source
files into a node's working directory and runs them under a sandboxed
subprocess group. `__init__.py` is empty; the package is imported as `src`.

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `server.py` — MCP entry point exposing `write_code`, `run_code`, `run_bash`, `emit_results`.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
