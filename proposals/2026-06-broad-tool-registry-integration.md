# RFC: Federated MCP control plane and scientific tool admission for ARI

| | |
|---|---|
| **Status** | **Proposed — architecture consolidated; the existing R-CCS fx700/A64FX launch spike is cleared. Ready for a small Stage A.0 implementation PR.** |
| **Date** | 2026-06-08; substantially revised 2026-08-01 |
| **Scope** | Design only. No runtime, API, or skill implementation is included in this PR. |
| **Relates to** | `docs/concepts/PHILOSOPHY.md` (P1–P5), `ari-skill-web`, `ari-skill-orchestrator`, `ari-skill-hpc`, `ari-skill-paper-re`, and the VirSci-live vendor-wrap precedent |

> **概要 (Japanese TL;DR)** — ARI に個別の MCP やツールを一件ずつ追加するのではなく、ToolUniverse、公式 MCP Registry、OpenROAD、Qiskit、将来の MCP 集合を **CatalogSource 単位で連合する MCP federation control plane** を導入する。LLM に見せる表面は `discover` / `describe` / `invoke` / `get_status` / `get_result` の 5 ツールに固定する。大量の候補は自動同期するが、実行できるのは ARI の Admission を通過して `CATALOG.lock` に固定されたものだけとする。ToolUniverse は生命科学を中心とする有力な provider だが、ARI の基盤形式にも科学的権威にもせず、交換可能な一 provider として統合する。一般的な MCP 接続・検索・実行は汎用層、出典・単位・独立性・再現性・EAR は ARI 科学層が担う。

---

## 1. Decision

ARI will implement a **provider-neutral, federated MCP control plane** packaged initially as one in-tree stdio skill, `ari-skill-tool-registry`.

The design has two deliberately separate layers:

1. **Generic MCP federation core** — catalog-source synchronization, normalized descriptors, namespacing, search, provider dispatch, capability negotiation, result normalization, and immutable snapshots.
2. **ARI scientific policy layer** — scientific admission, source and data provenance, units and ontologies, method independence, reproducibility evidence, domain validators, and EAR/cassette integration.

The manual extension unit is a **catalog source or provider adapter**, never an individual tool. A standards-conforming MCP collection should require configuration only; a compact or proprietary collection should require one collection-level adapter.

The design explicitly rejects these alternatives:

- making ToolUniverse's internal model ARI's canonical model;
- copying every tool into a hand-maintained `catalog.json`;
- discovering and executing arbitrary registry entries during an experiment;
- treating registry publication, package ownership, or aggregator approval as scientific validation;
- silently replacing one tool with a superficially similar tool during replay.

## 2. Goals and non-goals

### Goals

- Add or update thousands of upstream tools without per-tool ARI code or YAML edits.
- Keep the LLM-facing surface bounded and stable as the upstream catalog grows.
- Compose ToolUniverse and future MCP collections without nested-broker lock-in.
- Prevent technical name collisions and resolve semantic capability overlap explicitly.
- Preserve the origin chain down to the leaf code, data source, and method.
- Separate broad discovery from permission to execute.
- Pin every executed tool, adapter, schema, data dependency, and result artifact needed for replay.
- Support local synchronous tools and long-running submit/poll tools through one result contract.
- Remain compatible with ARI's current Python/stdio skill launch path through Stages A and B.

### Non-goals

- ARI will not become a public global MCP marketplace in the first implementation.
- ARI will not claim that MCP conformance implies scientific correctness.
- ARI will not replace domain engines such as ToolUniverse, OpenROAD, Qiskit, or Globus.
- ARI will not adopt an upstream agent loop or workflow harness; only passive tool capabilities are federated.
- Streamable HTTP, OAuth delegation, and the experimental MCP Tasks capability are deferred until the stdio contract is proven.

## 3. Evidence and ecosystem roles

No single upstream project satisfies ARI's complete breadth, reproducibility, security, and scientific-validity requirements.

| Source | Useful role in ARI | Why it is not the sole authority |
|---|---|---|
| **ToolUniverse** | Large scientific provider; native MCP stdio/HTTP; Compact Mode already exposes discovery/info/execute meta-tools | Coverage and quality vary by tool; its internal cache and review process do not pin every external dataset or validate an ARI experiment's conclusion |
| **Official MCP Registry** | Discovery of server metadata and installation descriptions | Namespace ownership is identity, not code safety or scientific validity; execution admission remains downstream responsibility |
| **mcp.science / Globus science MCPs** | Materials, physics, computation, and submit/poll design patterns | Reproducibility and provenance still need an ARI-owned contract |
| **OpenROAD MCP** | Maintainer-owned EDA provider and a stateful-session test case | Stateful command execution, PDKs, design files, and artifacts require a domain sandbox and domain manifest |
| **Qiskit MCP Servers** | IBM-maintained quantum tools, simulators, runtime jobs, and documentation | Backend, circuit, transpiler, noise-model, credential, and job provenance must be recorded separately |
| **Future MCP collections** | New domains and alternative implementations | Trust and semantics cannot be inherited transitively from the collection |

ToolUniverse is therefore a strong initial provider, especially for life-science workflows, but it is neither the federation substrate nor the scientific trust boundary.

## 4. Architecture

```text
 ToolUniverse      Official MCP Registry      Future collections
 OpenROAD MCP      Qiskit MCP Servers         Local/organization catalogs
       \                    |                         /
        +------------ CatalogSource adapters -------+
                              |
                       Candidate catalog
                     (large, not executable)
                              |
                normalization + policy + tests
                              |
                    Scientific Admission
                              |
                 content-addressed CATALOG.lock
                              |
             discover / describe / invoke / poll
                              |
                    ProviderAdapter dispatch
                              |
                ResultEnvelope + EAR/cassettes
```

### 4.1 Generic core versus ARI science extension

| Generic federation core | ARI scientific extension |
|---|---|
| `CatalogSource` and incremental sync | scientific source and citation evidence |
| canonical `tool_ref` and namespaces | dataset/version/acquisition provenance |
| MCP schema normalization | units, dimensions, identifiers, and ontology |
| semantic discovery and hard filtering | validation profile and known limitations |
| stdio provider execution | method/backend independence graph |
| async handles and artifact references | experiment-specific admissibility |
| package/schema snapshots | EAR, cassette, and replay rules |
| generic security/risk annotations | domain validators and comparison policy |

This boundary makes the federation core reusable outside science without weakening ARI's stronger scientific contract.

### 4.2 Extension contracts

The implementation defines four small interfaces. Their concrete Python API may evolve, but the responsibilities must not merge.

```text
CatalogSource.sync(previous_cursor) -> CandidateBatch
ProviderAdapter.describe(upstream_ref) -> UpstreamDescriptor
ProviderAdapter.invoke(upstream_ref, args, context) -> ResultEnvelope | Handle
ProviderAdapter.poll(handle) / result(handle) / cancel(handle)
AdmissionPolicy.evaluate(candidate, evidence) -> AdmissionDecision
ResultNormalizer.normalize(upstream_result) -> ResultEnvelope
```

Required initial adapters:

- `StaticCatalogSource` — deterministic fixture used by Stage A.0;
- `GenericStdioMcpProvider` — `initialize`, paginated `tools/list`, and `tools/call`;
- `CompactCollectionProvider` — collection-level discovery/info/execute mapping, first exercised by ToolUniverse;
- `RegistryCatalogSource` — metadata discovery only, deferred until Stage C.

A normal MCP server or collection uses the generic adapter. A ToolUniverse-like compact collection needs one adapter for the whole collection. No adapter is written per leaf tool.

### 4.3 Federation graph and cycle safety

Collections may themselves import other collections. Every discovered descriptor therefore carries an `origin_chain` and leaf provenance. Synchronization must:

- maintain a visited set of canonical provider identities;
- reject cycles such as `ARI -> collection A -> collection B -> ARI`;
- impose a configurable maximum federation depth;
- deduplicate identical descriptor and package digests;
- preserve the full route used for indirect execution;
- quarantine a tool when the collection cannot identify its leaf implementation or data source.

Trust is explicitly **non-transitive**: trusting collection A proves nothing automatically about a tool that A loaded from collection B.

## 5. Catalog lifecycle: broad discovery, narrow execution

The old idea of a hand-written whitelist containing every active server does not scale. It is replaced by a generated lifecycle:

```text
sources.yaml
    -> source sync
candidate descriptors / source diffs
    -> schema, supply-chain, policy, and conformance checks
admission decisions
    -> generated content-addressed snapshot
CATALOG.lock + catalog.index
```

### 5.1 Files and ownership

- `sources.yaml` is human-maintained and small. It names catalog sources, source pins, sync policy, transport allowance, and admission profile.
- Candidate records are generated. They may be large and are not executable merely because they were discovered.
- `CATALOG.lock` is generated and committed. It records each admitted logical tool, descriptor digest, provider/adapter digest, schema digest, origin chain, admission policy version, and leaf dependency identifiers.
- `catalog.index` is derived from the lock and descriptor objects. It is replaceable search data, not authority.
- Runtime reads only the locked active snapshot. It performs no registry refresh and admits no `listChanged` update during an experiment.

An upstream change creates a candidate diff. Unchanged low-risk tools may be re-admitted automatically by policy and conformance tests; high-risk, semantically changed, or provenance-incomplete tools remain quarantined for review. This preserves scalable ingestion without live-registry nondeterminism.

### 5.2 Canonical descriptor

Every candidate is normalized into a provider-neutral descriptor containing at least:

```yaml
tool_ref: source/provider/tool@sha256:<execution-contract-digest>  # opaque to clients
provider_ref: source/provider@sha256:<provider-digest>
upstream_ref: <provider-native tool identifier>
capability_ref: <normalized scientific or operational capability>
input_schema: <canonical JSON Schema>
output_schema: <canonical schema when supplied>
origin_chain: [<catalog>, <collection>, <leaf provider>]
execution:
  transport: stdio
  async: false
  side_effects: read-only | stateful | destructive
  permissions: [filesystem, network, credential-scope]
  deterministic: true | false | conditional | unknown
science:
  citations: []
  data_dependencies: []
  units: []
  limitations: []
  independence_group: <leaf method/data lineage>
admission:
  level: discovered | callable | reproducible | scientifically_admitted
  policy_version: <digest>
  evidence_digest: <digest>
```

`tool_ref` is an opaque execution identity. Its digest covers the executable leaf, provider/adapter, upstream identifier, schemas, defaults, and other execution semantics; admission scores and ranking metadata have separate digests. Clients must not reconstruct or parse it. A changed execution contract, provider, adapter, or schema produces a new reference, while a policy-only re-evaluation can retain the same execution identity. Old references remain resolvable from archived locks for replay.

## 6. Stable five-tool surface

ARI exposes exactly five MCP tools regardless of catalog size.

| Tool | Contract |
|---|---|
| `discover(query, constraints, strategy, top_k)` | Search the locked index, apply hard constraints, return bounded candidates, admission/independence metadata, and an explainable recommendation |
| `describe(tool_ref, section, cursor)` | Return exact schema, provenance, risks, and limitations by section with pagination; never exceed ARI's tool-output cap |
| `invoke(tool_ref, args, mode)` | Execute one explicit immutable reference in `live`, `record`, or `replay` mode; never resolve an unqualified name at invocation time |
| `get_status(handle)` | Normalize upstream jobs or MCP task state into one bounded status envelope |
| `get_result(handle)` | Return the normalized result and content-addressed artifact references when complete |

`discover` returns tool descriptions as data because ARI snapshots registered MCP tools when the phase starts and currently has no mid-session tool-registration channel. The five tool names remain stable even if the broker later moves into `ari-core`.

Large schemas and results must be paginated or stored as artifacts. The current `react_driver._MAX_TOOL_OUTPUT = 4000` limit means an implementation that returns an unbounded schema inline is incorrect.

## 7. Overlap and conflict resolution

Multiple providers will expose similar names and functions. That plurality is useful for scientific comparison, but it must be modeled rather than hidden.

| Overlap class | Example | Resolution |
|---|---|---|
| Exact duplicate | Same leaf package and digest through two catalogs | Collapse to aliases of one descriptor |
| Different wrapper, same leaf source | Two MCP wrappers over the same database/API | Select the better wrapper; do not count agreement as independent evidence |
| Same capability, independent method/source | Two simulators or analysis methods | Preserve both; allow explicit comparison |
| Superficially similar, different semantics | Ideal versus noisy quantum simulation | Assign different capability contracts unless an explicit semantic adapter is validated |

Names are isolated by `tool_ref`. Semantic overlap is represented separately by `capability_ref`, equivalence evidence, and `independence_group`.

The resolver applies hard filters before ranking:

1. exact input/output semantics, units, and experiment constraints;
2. required admission level and permission ceiling;
3. package, data, and environment availability;
4. reproducibility and validation evidence;
5. source authority and method suitability;
6. operational cost, latency, and observed health.

Selection is explainable and policy-versioned; it is not one opaque popularity score and is not based solely on an upstream description. `discover` may recommend a candidate, but `invoke` receives the selected immutable `tool_ref`. Replay never reranks.

When results disagree, ARI records the disagreement, provenance, methods, units, and uncertainty. It does not silently average or majority-vote incompatible results.

## 8. Scientific Admission

MCP validates communication shape, not scientific truth. ARI therefore assigns one of four explicit levels:

| Level | Meaning |
|---|---|
| `discovered` | Metadata was imported; execution is forbidden |
| `callable` | The provider passed protocol, dependency, sandbox, and smoke tests |
| `reproducible` | Code/environment/schema/data dependencies and replay artifacts satisfy the reproducibility contract |
| `scientifically_admitted` | A domain validation profile, limitations, and evidence requirements have passed for the declared capability and scope |

Admission is automated by tool class where possible, not reviewed one leaf tool at a time. Example profiles include read-only official data retrieval, deterministic local computation, predictive ML, remote simulation, stateful EDA, and destructive/action tools. Each profile supplies required tests and evidence.

Scientific admission records:

- authoritative publisher and source repository;
- package, image, adapter, and schema digests;
- dataset release, query timestamp, ETag or snapshot identity where available;
- algorithm/model citation and version;
- units, coordinate system, ontology, identifier namespace, and accepted conversions;
- determinism conditions, random seeds, numerical tolerances, and hardware sensitivity;
- benchmark/golden tests and known limitations;
- leaf dependency lineage used to determine independent evidence;
- license and use restrictions.

An admitted tool can still produce a wrong result outside its declared scope. Admission states evidence and applicability; it is not a blanket truth certificate.

## 9. ToolUniverse integration

ToolUniverse is integrated as one `CompactCollectionProvider`, not as ARI's registry or trust engine.

| ARI operation | ToolUniverse Compact Mode |
|---|---|
| catalog sync / `discover` | `list_tools`, `grep_tools`, or `find_tools` |
| `describe` | `get_tool_info` |
| `invoke` | `execute_tool` |
| job handling | adapter-normalized async operation or ARI-owned handle |

At sync time the adapter expands approved ToolUniverse metadata into ARI's normalized candidate catalog. At runtime ARI dispatches the locked leaf reference through `execute_tool`. This avoids both bad extremes: exposing thousands of schemas directly to the LLM, or exposing only ToolUniverse's four meta-tools without unified cross-provider discovery.

ARI's ToolUniverse profile must:

- pin the package/repository and dependency closure; never use refresh-on-launch;
- use Compact Mode and an explicit approved tool/category profile;
- disable runtime auto-loading of remote MCP collections;
- enable strict input validation and disable implicit type coercion for scientific record mode;
- treat ToolUniverse's internal cache only as an optimization, recording cache metadata or disabling it during ARI record mode;
- retain ARI's result envelope, EAR, and admission decision as the authoritative provenance.

The same compact-collection pattern applies to future aggregators without making ToolUniverse-specific concepts part of the public five-tool API.

## 10. Domain-provider profiles

The federation contract is generic; scientific evidence remains domain-specific.

### OpenROAD

The profile records the OpenROAD/ORFS commit or image digest, PDK and standard-cell versions, RTL/LEF/DEF/SDC inputs, initialization policy, seeds, commands, reports, and artifact hashes. Stateful command execution runs in a restricted working directory with an allowlisted command surface. Session state is part of the handle and provenance, never implicit global state.

### Qiskit and IBM Quantum

The profile records Qiskit/provider/backend versions, circuit hash and serialization, transpiler configuration and seed, basis gates/coupling map, shots, simulator/noise model, mitigation options, job identifier, and result metadata. Credentials are scoped to the provider process and never written to the EAR. Local simulator results and remote hardware results are different capability contracts.

These providers should be added as Stage-B pilots because they exercise state, artifacts, async jobs, and domain-specific reproducibility without changing the generic core.

## 11. Execution, results, and reproducibility

### 11.1 Result envelope

Every adapter returns a normalized envelope while preserving the raw upstream response as a content-addressed artifact:

```yaml
status: ok | error | submitted | running | cancelled
structured_content: <bounded JSON or null>
artifacts: [{digest, media_type, size, logical_role}]
error: {kind, message, retryable} | null
provenance:
  tool_ref: <immutable ref>
  origin_chain: []
  adapter_digest: <digest>
  started_at: <timestamp>
  completed_at: <timestamp or null>
  upstream_job_ref: <redacted/non-secret ref or null>
```

Submit-style calls must return a handle well under ARI's outer 300-second tool timeout. Polling and internal cancellation during timeout or shutdown are capability-negotiated; explicit user cancellation is outside the initial five-tool surface. An adapter must not claim a capability it cannot preserve.

### 11.2 Cassette and EAR contract

ARI, not an upstream collection, owns record/replay. A cassette key includes:

- immutable `tool_ref`, provider and adapter digests;
- canonical arguments after explicit default resolution;
- relevant non-secret execution context and declared credential scope identity;
- data/backend version or acquisition identity;
- output schema and normalization version.

Secrets are never stored or hashed directly. A non-secret credential-scope identifier prevents collisions between tenants or access tiers. Results, logs, artifacts, admission evidence, selection reasons, candidate set, and policy version are written to the EAR. Empty/auth-failed responses fail loudly rather than becoming valid cached results.

Frozen cassettes, `CATALOG.lock`, and a dependency-free replay shim are included through the existing `ear/publish.yaml` -> curate -> publish -> clone chain. Reproduction runs from those on-disk fixtures with no broker, MCP server, credentials, or network and fails on any missing digest.

### 11.3 Existing ARI blocker resolution

The earlier RFC identified two real hand-off mismatches; their zero-core-change resolution remains valid:

- There is no `ARI_PHASE` propagated to skill subprocesses. The broker does not infer phase; live/record/replay is controlled by workflow scoping, a default-off live flag, and explicit `invoke(mode=...)`.
- The reproduction sandbox cannot see runtime skill state. Cassettes and the lock are explicitly published into the reproducibility bundle and read as fixtures.

## 12. Security and supply chain

- Candidate discovery never grants execution.
- Registry namespace verification and aggregator signatures establish identity only; downstream code and scientific checks remain mandatory.
- Provider launch descriptors use validated launcher kinds and argument schemas, never arbitrary shell strings.
- Packages and dependency closures are pinned by immutable digest; bare tags and refresh-on-launch are rejected.
- Each child receives a minimal environment and declared credential scopes, not the parent's full `os.environ`.
- Filesystem, network, process, and resource permissions are profile-controlled and recorded.
- Upstream names, descriptions, schemas, annotations, and search scores are untrusted input and are sanitized before indexing or prompting.
- Unexpected stdout is recorded and rejected or redirected without corrupting MCP JSON-RPC. A sanitizer must not silently discard evidence of a malformed server.
- Stateful/destructive tools require stronger policy and, where appropriate, explicit human approval.
- A provider cannot modify the active catalog during an experiment.

Initial transport remains stdio. Streamable HTTP and remote OAuth add materially different trust, session, and credential boundaries and are a later adapter, not an expansion of the five-tool surface.

## 13. Verified launch constraint: R-CCS fx700/A64FX

The existing real-hardware spike launched pinned `uvx mcp-science <server>` children over stdio through the same MCP client pattern used by ARI, then completed initialization and tool listing. Light and heavy servers passed online and from a pre-warmed offline cache.

Stage A.0 must preserve the three provisions discovered by real failures:

1. select or provision a `uv` binary matching the compute-node architecture;
2. clear inherited `VIRTUAL_ENV`/`CONDA_PREFIX` and use an architecture-correct managed interpreter;
3. isolate malformed launcher stdout from the JSON-RPC channel while retaining it as diagnostic evidence.

The cache must be pre-warmed per architecture. Docker is not assumed on compute nodes. A heavy cold spawn may fit the current timeout but is not an acceptable reproducibility path.

## 14. Staged implementation plan

Each stage lands as a separate, reviewable PR. Interfaces are introduced before broad behavior; unused future machinery is not implemented early.

| Stage | Deliverable | `ari-core` change |
|---|---|---|
| **A.0 — broker kernel** | New default-off skill; fixed five tools; opaque `tool_ref`; `StaticCatalogSource`; `GenericStdioMcpProvider`; one pinned mcp.science fixture; bounded outputs; fx700 launch provisions | **zero** |
| **A.1 — generated federation catalog** | `sources.yaml`; descriptor normalization; generated `CATALOG.lock`/index; bulk MCP `tools/list` import; namespace/digest/cycle handling; conformance tests | **zero** |
| **A.2 — first collection provider** | ToolUniverse Compact adapter; approved profile; strict validation; demonstrate bulk import and cross-provider discovery without per-tool edits | **zero** |
| **B.0 — reproducibility and admission** | cassette/EAR publishing; four admission levels; policy-versioned manifests; child env isolation; result/artifact envelope | **zero** |
| **B.1 — conflict and domain pilots** | capability/equivalence/independence model; explainable resolver; OpenROAD and Qiskit local/sandboxed pilots; comparison records | **zero unless a proven launch limitation requires otherwise** |
| **C — federated sources and transports** | official Registry source, additional MCP collections, Streamable HTTP/OAuth, MCP Tasks mapping, domain packs; optional command-agnostic core launch path | **demand-gated and reviewed separately** |

Stage C may add a command-agnostic `SkillConfig` path to `ari-core`, but only together with a strict command/transport allowlist. The public five-tool contract and archived `tool_ref`/cassette formats remain stable.

## 15. Validation plan and acceptance criteria

### Unit and property tests

- canonical schema and argument hashing are order-independent;
- a changed schema/provider/adapter produces a new `tool_ref`;
- source cycles and excessive depth are rejected;
- exact duplicates collapse while independent implementations remain distinct;
- the same leaf database through two wrappers receives one independence group;
- unadmitted candidates cannot be invoked;
- no secret value appears in logs, locks, cassettes, errors, or artifacts;
- discover/describe/status/result always respect output bounds.

### MCP conformance fixtures

- normal stdio server with pagination;
- malformed-stdout server;
- compact meta-collection;
- synchronous error and structured-content results;
- submit/poll/cancel server;
- large artifact and resource-link result;
- schema-change and `listChanged` event, which must create a pending diff rather than live activation.

### Scientific-policy fixtures

- incompatible units or simulator semantics are not clustered as equivalent;
- same-backend wrappers are not treated as independent confirmation;
- a deterministic seeded result replays byte-for-byte;
- a live mutable database result records acquisition identity and cannot claim byte reproducibility without a frozen payload;
- disagreement between independent tools is preserved, not silently combined.

### Stage exit criteria

1. A mock collection with at least 1,000 generated tools is imported through one source declaration and no per-tool file edits.
2. Adding a second collection requires at most one source manifest or one collection-level adapter.
3. An upstream update yields a reviewable lock/admission diff and cannot change a running experiment.
4. Record/replay succeeds in the isolated reproduction sandbox with network and credentials absent.
5. The fx700/A64FX online and pre-warmed-offline launch tests remain green.
6. ToolUniverse, a direct MCP server, and a compact test collection appear in one unified `discover` result with collision-free references.
7. Selection reasons, rejected candidates, policy version, execution path, and leaf provenance are present in the EAR.

## 16. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Scope grows into a marketplace or workflow engine | Keep Stage A to four small interfaces and five public tools; defer remote registry and orchestration features |
| Semantic clustering incorrectly merges tools | Default to distinct capabilities; require evidence for equivalence; retain raw descriptors |
| Aggregator hides leaf provenance | Quarantine rather than infer trust or independence |
| Large catalogs increase index/context cost | Derived local index, progressive disclosure, bounded top-k, paginated describe |
| Adapter-specific behavior leaks into public API | Normalize behind `tool_ref`, `ResultEnvelope`, and capability metadata |
| Reproducibility conflicts with live APIs/hardware | Record immutable payloads and acquisition identity; label the achievable reproducibility level honestly |
| Automatic admission becomes a supply-chain bypass | Candidate/active separation, immutable locks, policy-versioned CI, default-off live execution |
| One provider becomes a de facto lock-in | Conformance fixtures include direct, compact, and future-collection shapes from Stage A/A.2 |

## 17. Sources

- ToolUniverse: <https://github.com/mims-harvard/ToolUniverse>, <https://arxiv.org/abs/2509.23426>, MCP support <https://zitniklab.hms.harvard.edu/ToolUniverse/guide/building_ai_scientists/mcp_support.html>, Compact Mode <https://zitniklab.hms.harvard.edu/ToolUniverse/guide/building_ai_scientists/compact_mode.html>, architecture <https://zitniklab.hms.harvard.edu/ToolUniverse/expand_tooluniverse/architecture.html>, and validation defaults <https://zitniklab.hms.harvard.edu/ToolUniverse/en/reference/environment_variables.html>
- Model Context Protocol: tools <https://modelcontextprotocol.io/specification/2025-11-25/server/tools>, transports <https://modelcontextprotocol.io/specification/2025-11-25/basic/transports>, tasks <https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks>, and Registry trust boundary <https://modelcontextprotocol.io/registry/about>
- Official MCP Registry implementation: <https://github.com/modelcontextprotocol/registry>
- OpenROAD MCP: <https://github.com/The-OpenROAD-Project/openroad-mcp>
- IBM Quantum Qiskit MCP Servers: <https://quantum.cloud.ibm.com/docs/en/guides/qiskit-mcp-servers>
- mcp.science: <https://github.com/pathintegral-institute/mcp.science>
- MCP servers for Science & HPC: arXiv:2508.18489, <https://github.com/globus-labs/science-mcps>
- ARI internals referenced: `ari-core/ari/mcp/client.py`, `ari-core/ari/agent/react_driver.py`, `ari-core/config/workflow.yaml`, `ari-core/ari/clone/__init__.py`, `ari-skill-paper-re/src/server.py`, `ari-skill-transform/src/curate.py`, and `ari-skill-web/src/server.py`
