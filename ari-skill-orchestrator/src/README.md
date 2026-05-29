# ari-skill-orchestrator/src

MCP server package that exposes ARI itself as an MCP server, so external
agents/IDEs/scripts can trigger ARI runs — including recursive ARI-inside-ARI
launches (depth-capped). No `__init__.py`; `server.py` is the entry point.

## Contents

- `README.md` — this file.
- `requirements.txt` — runtime dependencies for the standalone server.
- `server.py` — exposes `run_experiment`, `get_status`, `list_runs`, `list_children`, `get_paper`.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools, transports (stdio / HTTP) & recursion contract.
