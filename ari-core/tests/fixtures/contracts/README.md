# ari-core/tests/fixtures/contracts

Golden JSON snapshots of ARI's four stable contract surfaces — the single, machine-diffable "contract diff" that later refactor subtasks must not silently drift.

## Contents

- `README.md` — this file.
- `cli_tree.json` — golden of the `ari = ari.cli:app` Typer/Click command tree (11 commands + `memory`/`ear`/`registry`/`migrate` sub-typers, per-node arguments/options) plus curated flag→env-var side effects; built in-process by `build_cli()`.
- `mcp_tools.json` — golden catalog of the 15 `ari-skill-*/src/server.py` MCP tool surfaces (90 unique names from 59 FastMCP + 33 low-level `Tool` defs, with arg names), the return-envelope/naming invariants, and recorded cross-skill collisions; built by static AST in `build_mcp_static()`.
- `public_api.json` — golden per-submodule exported-symbol tables for the 11 `ari.public.*` re-export modules (the stable core→skill API surface); built in-process by `build_public()`.
- `viz_endpoints.json` — golden dashboard REST contract: curated method+path+owner endpoint inventory, mirrored `/api/*` response-key sets, and the AST-resolved `self.path` route literals from `viz/routes.py`; built by `build_viz()`.

## What each golden pins

| Fixture | Surface | Pins | How built |
| --- | --- | --- | --- |
| `public_api.json` | public API | Exact exported-symbol set for every module listed by `scripts/snapshot_contracts.py::_PUBLIC_SUBMODULES`. | In-process `importlib` of each submodule, capturing its resolved `__all__`. |
| `cli_tree.json` | CLI | Structural command/option tree of `ari` (commands, sub-typers, positional-argument order, options), plus the curated flag→env-var side effects (`ARI_IDEA_VIRSCI_*`, `ARI_RUBRIC`, …) Typer cannot expose. | In-process Typer→Click introspection. |
| `mcp_tools.json` | MCP catalog | Per-skill tool names + arg lists across all 15 `ari-skill-*` servers, the FastMCP/low-level counts, the `mcp__<skill>__<tool>` / `["error","result"]` invariants, and the recorded flat-namespace collisions (last-skill-wins clobber guard). | Static AST scan of each `src/server.py` (never launches a skill server). |
| `viz_endpoints.json` | viz REST | Curated method+path+owner endpoint inventory, `self.path` route literals (drift-exact), and response-key sets mirrored (not forked) from `test_api_schema_contract.py` (additive/subset semantics). | Curated inventory + AST scan of `viz/routes.py`. |

Each golden is consumed by `ari-core/tests/test_contract_snapshots.py`, which imports the same `build_*` / `compare` helpers so `pytest` and `--check` can never disagree.

## The `_meta` / `schema_version` envelope

Every fixture is a JSON object wrapped in a fixed envelope:

- `schema_version` (int, currently `1`) — the fixture's own shape version; bump it only when the JSON layout itself changes (not on a content update).
- `_meta` — provenance block, identical shape across all four surfaces:
  - `generated_by` — always `scripts/snapshot_contracts.py`.
  - `surface` — one of `public` / `cli` / `mcp` / `viz`.
  - `ari_core_version` — the ari-core version the snapshot was taken against (currently `0.9.1`).
  - `note` — the exact `--surface <x> --update` command that regenerates this file.

The envelope deliberately carries **no timestamps and no commit SHAs**: payloads are emitted with `json.dumps(sort_keys=True, ensure_ascii=False, indent=2)` plus a trailing newline, so every regeneration is byte-stable and any diff is a real contract change (design principle P2, determinism — stdlib only, no LLM, no network).

## Regenerate / verify

The generator/verifier is `scripts/snapshot_contracts.py` (stdlib only):

```
# verify the live tree still matches every golden (default mode; exits 1 on drift)
python scripts/snapshot_contracts.py --surface all --check

# regenerate a golden after an INTENTIONAL surface change
python scripts/snapshot_contracts.py --surface public --update   # or cli / mcp / viz / all
```

`--check` prints per-surface, actionable drift hints (removed/added symbols, changed route literals, new cross-skill collisions, …). It is exactly equivalent to running `pytest ari-core/tests/test_contract_snapshots.py` — both paths share one source of truth. When a surface change is intentional, run `--update`, and the resulting byte-stable JSON diff becomes the reviewable contract diff. This directory wires no CI gate itself (that is handled by separate subtasks).

## See also

- `scripts/snapshot_contracts.py` — the deterministic generator/verifier for these goldens.
- `ari-core/tests/test_contract_snapshots.py` — the pytest consumer (exact-set, structural, and additive/subset guards).
- `ari-core/tests/test_api_schema_contract.py` — canonical viz response-shape guard mirrored by `viz_endpoints.json`.
- `docs/refactoring/010_contract_preservation_policy.md` — the contract-preservation catalog/policy.
- `docs/refactoring/subtasks/034_add_contract_snapshot_fixtures.md` — the originating subtask.
