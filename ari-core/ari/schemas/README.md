# ari.schemas

JSON Schemas shipped with ari-core, loaded by basename via
`ari.schemas.load(name)`.

## Contents

- `README.md` — this file.
- `call_context_v1.schema.json` — explicit run, node, ordered-lineage, and call provenance context.
- `__init__.py` — `load(name)` loader.
- `node_report.schema.json` — per-node report schema.
- `publish.schema.json` — publish record / manifest schema.
- `result_envelope_v1.schema.json` — typed MCP result plus value-free credential-scope provenance.
- `skill_manifest_v1.schema.json` — canonical Skill package, environment, and credential-scope contract.
- `skills_lock_v1.schema.json` — immutable provider/schema/phase/credential-authority snapshot.
- `viz_checkpoint.schema.json` — TODO
- `viz_checkpoint_summary.schema.json` — TODO
- `viz_settings.schema.json` — TODO
- `viz_state.schema.json` — TODO
- `viz_tree_node.schema.json` — TODO

## See also

- **Loader** → the `load()` docstring in `__init__.py` (authoritative).
- **File formats these schemas validate** → `docs/reference/file_formats.md`.
