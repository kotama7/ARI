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

1. Declare either a direct stdio MCP provider or a reviewed collection adapter
   in `sources.yaml`. Launchers are shell-free, Python-only,
   architecture-aware, and pinned to the interpreter, package
   source/dependency declaration closure, adapter, and provider digest.
2. Run `python src/sync_catalog.py`. A first catalog is created. A changed
   catalog produces `*.pending` files and a machine-readable diff, then exits 3.
3. Review source identity, schemas, permissions, evidence, provenance chains,
   semantic overlap, and quarantine decisions.
4. Run `python src/sync_catalog.py --approve` to replace the reviewed lock.
   A leaf schema/default change additionally requires
   `--approve-schema-changes` so a bulk package update cannot hide a contract
   change among ordinary additions.
5. Regenerate/check public contracts with
   `python scripts/sync_contracts.py --write` or, in CI, without `--write`.

Runtime reads `CATALOG.lock` and `catalog.index.json` once. It never refreshes a
source or auto-admits a new leaf during a run.

## ToolUniverse collection

ToolUniverse is one optional collection source, not a dependency of the generic
registry and not a public tool namespace. The reviewed support matrix currently
contains ToolUniverse `1.3.1` and pins its PyPI wheel/sdist, upstream commit,
license, upstream dependency lock, compact contract, and the canonical tree of
all 3,542 files in the installed `tooluniverse` package. Sync and runtime both
verify that tree before starting the exact
`tooluniverse.smcp_server:run_stdio_server` entry point.

The adapter uses only `list_tools`, `get_tool_info`, and `execute_tool` from the
four-tool compact surface. It applies its own category filter because an
upstream CLI filter is not a trust boundary, expands leaf schemas in bounded
pages/batches, and executes only names present in the active lock. Dynamic MCP
loaders, agentic/composition/code-execution types, unprofiled categories,
credential-requiring leaves, and invalid schemas are quarantined. The known
v1.3.1 property-level `required: true` dialect is translated deterministically
to standard JSON Schema and the translation is recorded; argument values are
never coerced.

Verify an isolated installation and obtain its provider digest before adding a
source declaration (start from
`providers/tooluniverse-source.example.yaml`):

```bash
python scripts/verify_tooluniverse.py \
  --python /absolute/provider-env/bin/python \
  --package-root /absolute/provider-env/lib/python3.13/site-packages/tooluniverse \
  --category uniprot --smoke
```

Category profiles assign effects, determinism, permissions, limitations, and
lineage to groups of leaves. They do not confer scientific validity. Collection
evidence is capped below per-leaf replay/scientific validation, provider caches
and update checks are disabled, and ARI cassette/EAR remains the replay
authority. The optional dependency is installed only with
`ari-skill-tool-registry[tooluniverse]`; production environments should be built
from the reviewed upstream lock rather than resolving current transitive
versions.

## OpenROAD experiment profiles

The official OpenROAD-MCP integration is a domain adapter, not another exposed
interactive shell. One immutable `OpenRoadExperimentV1` becomes one virtual
asynchronous leaf. The only invocation argument is a bounded `request_id`; Tcl,
cwd, environment, executable, input/output paths, seed, threads, PDK, libraries,
toolchain commits, and image digest all come from the reviewed catalog profile.

Runtime copies a closed digest-verified input workspace to a new private
directory per run, starts `openroad -no_init -metrics <declared-json>` through a
single stateful MCP connection, and accepts only the adapter's closed verb and
inert argument grammar. It captures only declared regular outputs, rejects
missing, unexpected, oversized, symlinked, or digest-mismatched files, and
normalizes each metric with unit, corner, mode, stage, report digest, and JSON
pointer. Golden and replay evidence are regular files whose bytes and contents
are checked; metadata assertions alone cannot raise admission.

Submission, status, result, and cancellation use the registry's generic async
handle. Termination runs in cleanup, local process/session recovery fails closed,
and output plus the sanitized command transcript are content-addressed artifacts.
The broker independently verifies every adapter artifact's logical path, size,
and SHA-256 before publishing it. Record mode includes these references in the
cassette, so replay and inspection do not start OpenROAD or require the PDK.

The reviewed support line is OpenROAD-MCP Python 0.6.1 with ORFS 26Q3. The
upstream Python release is deprecated/final and its npm distribution is active;
an npm launcher will require a separate reviewed adapter. Start from
`providers/openroad-source.example.yaml` and verify exact installations with:

```bash
python scripts/verify_openroad.py \
  --python /absolute/openroad-mcp-env/bin/python \
  --package-root /absolute/openroad-mcp-env/lib/python3.13/site-packages/openroad_mcp \
  --experiment /absolute/profile.yaml --smoke
```

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
