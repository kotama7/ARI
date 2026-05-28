# ari-skill-plot/src

MCP server package for the plot skill — scientific figure generation, either
deterministically from a fixed schema (`generate_figures`, P2-safe) or by
letting an LLM write matplotlib code (`generate_figures_llm`). No `__init__.py`;
`server.py` is the entry point.

## Contents

- `README.md` — this file.
- `server.py` — the only module; an independent MCP server with no dependency on the paper skill.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
