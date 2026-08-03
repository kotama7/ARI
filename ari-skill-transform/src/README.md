# ari-skill-transform/src

MCP server package for the transform skill — walks the BFTS tree
(`nodes_tree.json`) and uses an LLM to extract methodology + key findings,
and owns the EAR publication lifecycle (curate / publish / promote).
`__init__.py` is empty; the package is imported as `src`.

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `annotations.py` — report-only, content-addressed, non-authoritative model interpretation.
- `claims.py` — deterministic Research Contract claim generator using the core-owned formula registry through `ari.public.science_data`.
- `curate.py` — deterministic EAR curator producing recoverably-swapped `ear_published/` + manifest v2.
- `ear.py` — closed-path Skill/CATALOG lock, cassette, admission, contract, and ResultEnvelope evidence hand-off.
- `publish_adapter.py` — thin adapter to the core-owned publication backend interface.
- `science_data.py` — deterministic raw/derived/provenance materializer for canonical `ScienceDataV1`.
- `server.py` — MCP declaration and orchestration entry point for the five public tools.
- `licenses/` — bundled license texts used when curating EAR bundles.
  - `README.md` — licenses index.
  - `apache-2.0.txt` — Apache-2.0 license body.
  - `bsd-3-clause.txt` — BSD-3-Clause license body.
  - `cc-by-4.0.txt` — CC-BY-4.0 license body.
  - `gpl-3.0.txt` — GPL-3.0 license body.
  - `mit.txt` — MIT license body.
- `prompts/` — `science_interpretation.md` is the static, reviewable prompt for the optional
- `schemas/` — JSON Schemas for transform outputs.
  - `science_data_claims.schema.json` — retained pre-v1 schema for the offline migration support window; native schema is generated at `ari-core/ari/schemas/science_data_v1.schema.json`.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
