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
registry and not a public tool namespace. The support matrix retains upstream
ToolUniverse `1.3.1` as a candidate and admits the separately identified
`1.3.1+ari.1` patched wheel for one verified PubMed capability. Both records pin
the upstream commit, license, compact contract, and canonical installed package
tree. The patched record additionally pins the metadata-only patch, reproducible
wheel recipe, complete runtime lock, Provider manifest, and exact wheel digest.
Sync and runtime verify that closure before starting the exact
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
  --version 1.3.1+ari.1 \
  --wheel /absolute/artifact-store/tooluniverse-1.3.1+ari.1-py3-none-any.whl \
  --dependency-lock providers/tooluniverse/1.3.1+ari.1/runtime.uv.lock \
  --verified-lock providers/tooluniverse/1.3.1+ari.1/verified-lock-v1.json \
  --category pubmed --tool PubMed_search_articles --smoke
```

Category profiles assign effects, determinism, permissions, limitations, and
lineage to groups of leaves. They do not confer scientific validity. Collection
evidence is capped below per-leaf replay/scientific validation, provider caches
and update checks are disabled, and ARI cassette/EAR remains the replay
authority. ToolUniverse is not installed through a registry package extra: the
upstream `fitz` dependency resolves
to an unrelated legacy distribution and breaks supported Python runtimes. The
ARI artifact changes only package metadata (`fitz` to `PyMuPDF==1.26.4`) and its
local version; two controlled builds produced the same wheel bytes. Production
must install that retained wheel from `runtime.uv.lock`, never resolve mutable
transitive versions. Verification checks wheel, raw lock, package tree,
`pip check`, runtime target, compact MCP startup, and the evidence-bound lock.

A profile may additionally project an exact reviewed leaf name to one canonical
versioned `capability_ref`, equivalence key, and result normalizer. This is an
explicit per-name map: descriptions, substrings, and nearby names never grant
semantic authority, and a mapped leaf disappearing or changing category/type
fails sync. The initial
`tooluniverse-pubmed-retrieval/v1` normalizer converts only
`PubMed_search_articles` success envelopes to
`ari.retrieval-result/v1`, preserving the compact collection and leaf-spec
digests in provenance. Only this exact leaf is `verified`; every other
ToolUniverse leaf remains unadmitted. Formal promotion additionally requires
the checked-in `promotion-approval-v1.json`, which binds an explicit human
maintainer authorization to the exact registration report, evidence bundle,
Provider manifest, and approved capability scope. Removing or mutating that
approval invalidates the verified lock. The verified identity has no credential
scope: although upstream declares optional `NCBI_API_KEY`, the environment does
not pass it and the anonymous live probe is part of promotion evidence. A keyed
variant requires a separate Provider identity and promotion.

The default admission policy accepts the ontology's exact `network-read`
permission without granting network write. A source synchronized from this
verified identity therefore becomes one `callable` PubMed leaf; the committed
default catalog remains empty. Promotion changes the governed Provider status;
it does not auto-activate a Provider. Activation remains an explicit,
environment-specific catalog sync followed by a run-frozen Provider/Binding
lock, so existing and resumed runs cannot acquire the Provider implicitly.

`scripts/promote_tooluniverse_pubmed.py` is the explicit admin operation and
requires `--authorized-by` for the human maintainer identity. It
rechecks the artifact and environment, live four-tool MCP surface, exact leaf
and schema digests, Capability contract, normalized live result, isolation,
timeout/process-group cleanup, schema drift, prompt-description boundaries, and
unbound invocation rejection. It stages the immutable evidence bundle and
fifteen-gate registration report, then publishes `verified-lock-v1.json` last;
an interrupted or mixed set fails closed. Merely editing `status` cannot pass
lock verification. Provider execution runs behind a value-free stdio supervisor
that reaps the complete child process group on normal exit, timeout, and
cancellation.

## OpenROAD experiment profiles

The official OpenROAD-MCP integration is a domain adapter, not another exposed
interactive shell. One immutable `OpenRoadExperimentV1` becomes one virtual
asynchronous leaf. The only invocation argument is a bounded `request_id`; Tcl,
cwd, environment, executable, input/output paths, seed, threads, PDK, libraries,
toolchain commits, and image digest all come from the reviewed catalog profile.

Each profile selects one closed execution backend. `local-mcp` copies a closed
digest-verified input workspace to a new private directory, compiles the typed
command list to a runtime-owned fixed Tcl file, and starts
`openroad -no_init -metrics <declared-json> <fixed-tcl>` through MCP. It polls
read-only session state and collects artifacts only after normal process exit;
it does not use PTY input echo as a completion signal.
`slurm` compiles the same closed commands into a digest-pinned Tcl program,
copies a standard-library-only reviewed worker, and submits both through C06's
typed `JobRequestV1` in a digest-pinned clean Apptainer/Singularity container.
No caller-supplied command, scheduler flag, module, path, or environment crosses
the virtual leaf boundary. Both backends capture only declared regular outputs, reject
missing, unexpected, oversized, symlinked, or digest-mismatched files, and
normalize each metric with unit, corner, mode, stage, report digest, and JSON
pointer. Golden and replay evidence are regular files whose bytes and contents
are checked; metadata assertions alone cannot raise admission.

Submission, status, result, and cancellation use the registry's generic async
handle. Local termination closes the MCP session. SLURM cancellation is confirmed
before its private shared-filesystem workspace is removed; an ambiguous scheduler
transport leaves that workspace intact for reconciliation. C06 handle, resources,
environment/module/container digests, logs, and runtime provenance join the output
and sanitized transcript as content-addressed artifacts.
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

The checked-in promotion bundle
`providers/openroad/0.6.1+orfs-26q3-gcd-nangate45/` formally verifies exactly
one credential-free local-MCP CPU profile. Lock
`sha256:ecd7cc79542acfcfa177186d3bbe154678f1a378454834b6276efb1383eeab28`
binds OpenROAD-MCP 0.6.1, the retained ORFS image and inner OpenROAD binary,
GCD placed database, Nangate45 PDK/library/license, typed command sequence,
golden/replay fixtures, live MCP schemas, DRC-zero result, output contracts,
all fifteen Provider gates, and explicit human promotion approval. The 1.54 GB
SIF is a digest-pinned external retained artifact ignored by Git and must be
materialized at the bundle's `runtime/openroad-orfs-26q3.sif` path.
The independent
`providers/openroad/0.6.1+orfs-26q3-gcd-nangate45-slurm-cpu/` bundle formally
verifies the same closed scientific profile on an anonymous exclusive-node
SLURM CPU allocation. Its lock
`sha256:d640dd226c101f9027e11f11c2201afd694b4914c11d7d45b458d142bc2971fd`
binds the salted site identity, controller-client snapshot, PRoot 5.3.1,
unsquashfs 4.6.1, retained SIF, worker Python, fixed-wrapper terminal evidence,
live route result, and human approval. It requests zero GPUs and grants no GPU
capability. GPU execution, other designs/PDKs/corners, and another image remain
separate candidate identities.
Promotion does not add this leaf to the checked-in empty `CATALOG.lock`.
`scripts/promote_openroad_gcd_cpu.py` and
`scripts/promote_openroad_gcd_slurm_cpu.py` are the human-admin promotion
commands; they rebuild their separate evidence/report/approval/lock closures
and cannot broaden either fixed profile through command-line arguments.

SLURM promotion keeps its physical cluster, partition, and node selectors in an
ignored runtime site file, never in a tracked profile or evidence document. The
site file must carry a 256-bit nonce; public artifacts bind only its salted full
SHA-256 identity. `site_privacy.py` checks both current Git-tracked files and all
non-ignored untracked candidates before submission and after bundle generation,
and separately scans staged blob bytes, including staged content that differs
from the worktree. Symlink targets and filenames are also covered. Removing the
ignore rule or leaking a selector therefore aborts promotion. Run the same gate
directly with `python scripts/check_site_privacy.py`; this checkout installs it
as the repository pre-commit gate through `.githooks/pre-commit`. The private
configuration remains ignored (or outside the repository), and an alternate
location is supplied only through `ARI_PRIVATE_SLURM_SITE_CONFIG` or local Git
configuration. A promotion checkout sets `ari.sitePrivacy.required=true`, so
removing the private configuration cannot silently disable the hook.

## Qiskit experiment profiles

The Qiskit integration imports the official Qiskit MCP servers as two pinned
providers but exposes only immutable sampling profiles. It deliberately does
not expose account management, arbitrary QASM/Python, arbitrary backend
selection, or the upstream tool sets as leaf tools. Four different capability
references keep local ideal Aer, local noisy Aer, remote simulator, and IBM
hardware results from becoming interchangeable semantic matches.

Each `QiskitExperimentV1` fixes a QPY circuit and producer version, parameter
bindings with explicit units, transpiler level/seed/layout, basis gates,
coupling map and target digest, shots, simulation method/precision/threads,
simulator seed and noise model, or Runtime backend/access-tier/mitigation
identity. The caller supplies only an idempotent `request_id`. The adapter uses
the official core MCP for transpilation; a digest-pinned, distribution-checked
worker runs local Aer because the reviewed core provider does not execute
circuits. Remote profiles use only the reviewed Runtime setup, snapshot,
sampler, status, result, and cancellation operations.

Remote submission returns the common asynchronous handle immediately. The raw
backend property, coupling, calibration, submission, status, and result records
are stored as role-distinct content-addressed artifacts. A stable scientific
snapshot digest excludes queue/operational timestamps while the original live
snapshot remains preserved. Backend or target mismatch fails before submission,
timeout requests cancellation, and an ambiguous submit/cancel race is reconciled
without silently orphaning the provider job.

`QISKIT_IBM_TOKEN` is the only admitted Runtime credential. It enters the Skill
through the `quantum.ibm-runtime` credential scope and is forwarded only to the
isolated Runtime MCP process. Exact-value redaction covers provider text,
structured output, diagnostics, and exceptions; locks, source records,
cassettes, artifacts, and identity digests contain neither the token nor a raw
instance CRN. The profile stores only an `instance_digest` and an access-tier ID.

The reviewed stack is Qiskit MCP server 0.3.1, IBM Runtime MCP server 0.6.1,
Qiskit 2.5.1, Qiskit Aer 0.17.2, and Qiskit IBM Runtime 0.48.0. Aer 0.17.2 is in
reduced maintenance, so any version change needs a new support record and
scientific fixture review. Start from `providers/qiskit-source.example.yaml` and
verify isolated installations, provider contracts, profiles, and optionally a
local run with:

```bash
python scripts/verify_qiskit.py \
  --core-python /absolute/qiskit-env/bin/python \
  --core-package-root /absolute/qiskit-env/lib/python3.13/site-packages/qiskit_mcp_server \
  --runtime-python /absolute/runtime-env/bin/python \
  --runtime-package-root /absolute/runtime-env/lib/python3.13/site-packages/qiskit_ibm_runtime_mcp_server \
  --experiment /absolute/profile.yaml --smoke
```

The checked-in promotion bundle
`providers/qiskit/core-0.3.1+aer-0.17.2-local-ideal/` formally verifies exactly
one credential-free, seeded Bell-state local-Aer profile. Lock
`sha256:57b60bbdb84ba0364e038a6df51f3de2a48cdf8c776d31066efeec5ea68be195`
binds Qiskit MCP 0.3.1, Qiskit 2.5.1, Aer 0.17.2, QPY bytes/version, target,
seeds, counts bounds, golden/replay evidence, live schemas, fifteen Provider
gates, and explicit human approval. It does not promote the IBM Runtime MCP,
remote simulator, or IBM hardware: those require a separate credential-scoped
identity with a pinned backend/configuration/calibration snapshot and live
golden/replay evidence. Promotion does not activate the default catalog.
`scripts/promote_qiskit_local_aer.py` is the human-admin promotion command; it
recreates the QPY/golden/replay and complete evidence/report/approval/lock
closure for this exact local profile only.

See [the Qiskit profile guide](../docs/reference/qiskit_profiles.md) for the
scientific contract, credential procedure, provider update gate, and rollback.

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
