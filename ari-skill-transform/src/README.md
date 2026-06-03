# ari-skill-transform/src

MCP server package for the transform skill — walks the BFTS tree
(`nodes_tree.json`) and uses an LLM to extract methodology + key findings,
and owns the EAR publication lifecycle (curate / publish / promote).
`__init__.py` is empty; the package is imported as `src`.

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `claims.py` — TODO
- `curate.py` — deterministic (P1/P2) EAR curator producing `ear_published/` + `manifest.lock`.
- `server.py` — MCP entry point (`nodes_to_science_data`, `generate_ear`, `curate_ear`, `publish_ear`).
- `licenses/` — bundled license texts used when curating EAR bundles.
  - `README.md` — licenses index.
  - `apache-2.0.txt` — Apache-2.0 license body.
  - `bsd-3-clause.txt` — BSD-3-Clause license body.
  - `cc-by-4.0.txt` — CC-BY-4.0 license body.
  - `gpl-3.0.txt` — GPL-3.0 license body.
  - `mit.txt` — MIT license body.
- `schemas/` — TODO
  - `science_data_claims.schema.json` — TODO

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
