# ari-skill-tool-registry

Provider-neutral federation for large scientific MCP collections. The Skill is
default-off and exposes exactly five operations to the agent:

| Operation | Purpose |
|---|---|
| `discover` | Search a bounded immutable catalog and return opaque `tool_ref` values |
| `describe` | Page through schema, provenance, admission, semantics, and limitations |
| `invoke` | Execute one admitted exact `tool_ref` in `live`, `record`, or `replay` mode |
| `get_status` | Poll a descriptor-bound asynchronous operation |
| `get_result` | Retrieve and normalize its final result |

Leaf schemas are generated from source discovery into `CATALOG.lock`; they are
never registered directly as LLM tools. Adding a 1,000-tool collection therefore
requires one reviewed source declaration, not 1,000 hand-written records.

## Catalog workflow

1. Declare a direct stdio MCP provider in `sources.yaml`. The launcher is
   shell-free, Python-only, architecture-aware, and pinned to the interpreter,
   package source/dependency declaration closure, adapter, and provider digest.
2. Run `python src/sync_catalog.py`. A first catalog is created. A changed
   catalog produces `*.pending` files and a machine-readable diff, then exits 3.
3. Review source identity, schemas, permissions, evidence, provenance chains,
   semantic overlap, and quarantine decisions.
4. Run `python src/sync_catalog.py --approve` to replace the reviewed lock.
5. Regenerate/check public contracts with
   `python scripts/sync_contracts.py --write` or, in CI, without `--write`.

Runtime reads `CATALOG.lock` and `catalog.index.json` once. It never refreshes a
source or auto-admits a new leaf during a run.

## Admission and scientific meaning

Admission is explicit and monotonic:

- `discovered`: visible but not executable;
- `callable`: protocol, provider pin, launcher, and permission checks pass;
- `reproducible`: dependency closure and an offline replay fixture are present;
- `scientifically_admitted`: validation evidence, limitations, units, semantics,
  and method/backend identity are documented.

Policy identity is separate from execution identity. Changing only policy does
not rewrite `tool_ref`; changing provider, adapter, schema, defaults, permissions,
semantic execution fields, or lifecycle does.

Exact duplicates collapse. Similar capabilities remain separate unless evidence
establishes equivalence; same-backend and independent-method overlap are recorded
explicitly. Results are never averaged merely because names look similar.

## Record and replay

`record` stores the exact arguments, catalog/policy digests, selection reason,
rejected alternatives, raw response digest/artifact, and normalized
`ari.result-envelope/v1`. `replay` requires the same immutable catalog and does
not start the provider. Evidence is written under `{checkpoint}/ear/catalog/`
and is included by the default EAR curator.

## Verification

```bash
pytest -q
python scripts/sync_contracts.py
python ../scripts/check_skill_manifests.py
```

The suite uses real stdio MCP processes, malformed-output and environment
isolation fixtures, async lifecycle tests, graph-cycle quarantine, deterministic
lock diffs, offline replay, and a 1,000-tool resource-bound import.

See [the federation reference](../docs/reference/tool_registry.md) for the
normative operator and adapter contract.
