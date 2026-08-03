# ari-skill-coding/src

MCP server package for the coding skill — the agent's "hands": writes source
files into a closed node workspace and delegates execution/measurement
validation to `ari.public.execution`. `__init__.py` is empty; the package is
imported as `src`.

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `server.py` — MCP entry point exposing atomic `write_code`, digest-bound

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
