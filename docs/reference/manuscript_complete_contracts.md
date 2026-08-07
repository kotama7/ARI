# Manuscript Complete V1 contracts

All normative documents reject unknown fields, use safe checkpoint-relative
paths, canonical JSON SHA-256 identities, and validate their advertised digest
on read. Generated JSON Schemas live in `ari-core/ari/schemas/` and are checked
with:

```bash
PYTHONPATH=ari-core python scripts/sync_manuscript_schemas.py --check
```

| Document | Schema version | Permanent role |
|---|---|---|
| requirement profile | `ari.manuscript-requirement-profile/v1` | requirements, applicability and severity |
| exploration snapshot | `ari.manuscript-exploration-snapshot/v1` | complete node/artifact inventory and scientific winner |
| omission manifest | `ari.manuscript-omission-manifest/v1` | conservation of included plus omitted inventory |
| context | `ari.manuscript-context/v1` | deterministic requirement-oriented projection |
| readiness | `ari.manuscript-readiness/v1` | per-requirement status and authoring/publication verdicts |
| section brief bundle | `ari.manuscript-section-brief-bundle/v1` | bounded, lane-aware writer input with no silent required omission |
| authoring binding | `ari.manuscript-authoring-binding/v1` | exact profile/context/readiness/brief and target build |
| segment record | `ari.manuscript-segment-record/v1` | resumable workflow input/output transaction |
| repair request/plan | `ari.research-repair-request/v1`, `ari.research-repair-plan/v1` | fixed action, authority and cumulative budget |
| repair transaction | `ari.manuscript-repair-transaction/v1` | immutable committed resolver result and exact resource use |
| automatic repair round | `ari.manuscript-auto-repair-round/v1` | contiguous coordinator round and cumulative usage |
| publication decision | `ari.manuscript-publication-decision/v1` | six independent gate verdicts bound to one build |
| publication lock | `ari.manuscript-publication-lock/v1` | final fresh decision/build/PDF interlock |
| evaluation report | `ari.manuscript-evaluation-report/v1` | labelled program metrics with explicit denominator applicability |
| transition | `ari.manuscript-transition/v1` | append-only state hash chain |

## Digest lineage

The normative chain is:

```text
profile + source files/nodes
  → snapshot
  → context + omission manifest
  → readiness
  → section briefs
  → authoring binding
  → PaperBuildV1
  → PublicationDecisionV1
  → PublicationLockV1
```

Changing any parent invalidates downstream reuse. The finalizer re-hashes the
snapshot sources, every nested `PaperArtifactV1`, all five manuscript inputs,
the reproduction result, and the final PDF before a lock is written. It also
checks the exact final TeX against the brief's contextual-negative/forbidden
evidence IDs and required disclosures. A passing upstream paper gate cannot
compensate for a failure of that bound content check.

Both evidence-lane checks — the archive's per-candidate screen and the
finalizer's check of the exact final TeX — are identifier-mention checks, not
judgements about how a draft uses the evidence. Each searches the draft for the
evidence ID itself as a delimited, case-insensitive token, taking
`A-Za-z0-9_:/-` as the token alphabet so that a trailing period is a delimiter,
over the union across all section briefs of `contextual_negative_ids` and
`forbidden_evidence_ids`. Any occurrence of such an ID anywhere in the draft
trips the check; neither site inspects the polarity of the surrounding claim,
and neither restricts a section brief's IDs to that section. The coarseness is
deliberate: the rule is deterministic and leaves nothing to argue about intent.
The rendered brief block states the weaker polarity rule in prose
("disclose, never use as positive support"), but the mechanically enforced
condition is the stricter one — the ID must not appear at all. Negative and
inconclusive history therefore reaches the manuscript through the brief's
`required_disclosures` and through the `negative-results` and `limitations`
content items, which carry their own item IDs rather than evidence IDs. The
`results` content items are the sharp edge: they include exploratory-lane
evidence records keyed by evidence ID, and the exploratory lane is also part of
`forbidden_evidence_ids`, so a brief can hand a writer content whose identifier
must never be written into the draft.

The two sites differ only in consequence. The finalizer's check is not
mode-scoped: it is applied whenever a publication decision is computed at all,
and it is ANDed into the `claim_evidence` sub-verdict, so a mention makes the
decision non-publishable and the lock step refuses it. In the archive screen a
mention becomes a hard disqualification — recorded as
`contextual_negative_evidence:<id>` or `forbidden_evidence:<id>`, with the
candidate additionally marked `_valid_for_frontier: false` — only under
`enforce`; `audit` records the identical diagnostics and leaves candidate
eligibility unchanged.

## Status semantics

Requirement status is exactly `satisfied`, `not_applicable`, `unavailable`, or
`missing`. `unavailable` is evidence about resolver availability, not success.
Authoring is blocked by authoring-critical `missing|unavailable`; publication
is blocked by every unresolved publication-critical requirement.

The top-level publication decision is publishable only if the applicable
`manuscript_readiness`, `claim_evidence`, `assurance`, `build_compile`,
`reproduction`, and `freshness` sub-verdicts do not fail. The model validator
recomputes this logical AND.

## Publication gates

### Sub-verdict invariants

`PublicationDecisionV1` carries exactly six `PublicationSubVerdictV1` entries and
its `decision` is a function of those six alone. The structure is enforced on
read, so a hand-edited or truncated decision document cannot present a softer
verdict than its own reasons support:

- The gate names must be exactly the six named under
  [Status semantics](#status-semantics), each appearing once. A missing gate, a
  repeated gate, or a gate outside that set is rejected.
- A `fail` sub-verdict with no reason code is rejected, so a blocked decision
  always states why it is blocked.
- Duplicate artifact digests inside one sub-verdict are rejected.
- `decision` must equal the recomputed logical AND of the six statuses.

What the contract does *not* constrain matters as much as what it does. The six
sub-verdicts are validated as a set, not a sequence: a decision whose gates
appear in another order still validates, but the order is part of the canonical
JSON and therefore changes `decision_digest`, so a reordered copy is a different
decision to everything downstream. `artifact_digests` and `reason_codes` are
plain strings with no pattern and no closed vocabulary; nothing at this layer
checks that a linked digest is a digest. And `reason_codes` are permitted on
`pass` and `not_required` too — only the producer declines to write them.

That producer is the fixed assembler in
`ari-core/ari/manuscript/publication.py`, and it narrows the schema in four ways:
it emits the gates in the order below, it writes reason codes only for `fail`,
it writes exactly one reason code per failed gate, and it emits `not_required`
for the `assurance` gate alone.

| Gate | Reason code on `fail` | Artifacts linked |
|---|---|---|
| `manuscript_readiness` | `manuscript_not_publication_ready` | the readiness report digest |
| `claim_evidence` | `final_claim_gate_failed` | the paper build's claim gate report digest |
| `assurance` | `required_certification_missing_or_failed` | the admitted certify-attestation digests — zero or more |
| `build_compile` | `paper_compile_failed` | the build's compile digest |
| `reproduction` | `paper_reproduction_failed` | the reproduction record digest |
| `freshness` | `publication_input_stale` | none |

Two gates break the one-gate-one-artifact pattern. `freshness` links nothing at
all, deliberately: it is the conjunction of the re-hashed attempt snapshot
sources, the recorded manuscript state being `authored` or `finalized`, the
`PaperArtifactV1` set nested in the exact build being non-empty and re-hashing to
its recorded identities, and — under enforce only — the five bound manuscript
inputs. It is a property of that whole input set rather than of any one artifact.
`assurance` links a set that may be empty: the snapshot digests of the admitted
certify-attestation items, which is an empty tuple whenever no item was admitted
or the attempt's `source_snapshot.json` could not be read. The other four always
link exactly one digest.

The third case is the absent record. When the evidence a gate judges does not
exist at all — the paper build carries no claim gate, or no compile record, or
the checkpoint has no reproduction file at a safe non-symlinked path — the
runtime still emits the gate and links the all-zero sentinel
`sha256:0000…0000` in place of a real digest. In all three cases the gate is
already `fail`, so the sentinel is diagnostic rather than load-bearing: it
records that no evidence existed, and it never marks a passing gate.

### Evidence and pass conditions

Each gate names the evidence it reads and applies one fixed pass condition.
Nothing is inferred from an absence: a gate whose evidence is missing,
unreadable, or not reachable at a safe non-symlinked path fails.

| Gate | Evidence | Passes when |
|---|---|---|
| `manuscript_readiness` | the bound `ManuscriptReadinessReportV1` | its `publication_verdict` is `ready` |
| `claim_evidence` | the build's claim gate and the exact final TeX | the gate status is `pass` **and** the final TeX carries every disclosure the bound briefs require and mentions no contextual-negative or forbidden evidence ID from those briefs |
| `assurance` | the compiled context's `assurance` block and the attempt's `source_snapshot.json` | the conditions in [Assurance sub-verdict and the reserved kernel binding](#assurance-sub-verdict-and-the-reserved-kernel-binding) hold; it is `not_required` unless the context records `assurance.mode: enforce` |
| `build_compile` | `PaperBuildV1.status` and its compile record | the status is `finalized` and the compile record's status is `completed` |
| `reproduction` | `ors_phase1.json` in the checkpoint | the file exists at a non-symlinked path and records `executed`, `exit_code = 0`, an empty `missing` list, and no `error` |
| `freshness` | the attempt snapshot, the recorded manuscript state, the build's nested artifacts, and under enforce the five bound inputs | every one of those re-hashes to its recorded identity and the state is `authored` or `finalized` — the conjunction set out under [Sub-verdict invariants](#sub-verdict-invariants) |

Two of those conditions are broader than their evidence column suggests.
`claim_evidence` also fails when the section brief bundle is not exposed inside
the checkpoint, is symlinked, or does not parse; when the build does not name
exactly one `final-tex` artifact; or when that TeX is unreadable — an obligation
cannot be discharged by making it unreadable. Its disclosure half is a substring
test run after both the required text and the TeX are normalised (TeX control
sequences dropped, every non-alphanumeric character folded to a single space,
case-folded), so markup, punctuation, casing, and line breaks do not defeat it,
though the disclosure's words must still appear contiguously; its evidence-ID
half is the delimited-token rule under [Digest lineage](#digest-lineage).

`freshness` also fails when a source the attempt snapshot recorded as `missing`
has reappeared, and when a path-bearing source carries no recorded digest and
size — an entry with no stable byte identity cannot authorise publication. Its
enforce-only bound-input clause requires the five inputs to be the attempt
directory's own `requirement_profile.json`, `context.json`, `readiness.json`,
`section_briefs.json`, and `authoring_binding.json`, declared at exactly those
relative paths among the build's input artifacts, to re-hash to the identities
the build declares, to share one profile/context/readiness/brief lineage with the
binding, to name the target build's ID, revision, and run, and to carry an
authoring verdict of `ready` or `ready_with_disclosures`. Under `audit` that
clause is not applied at all, because audit deliberately does not bind the writer
to the compiled bundle; the snapshot, state, and build-artifact clauses still
hold.

A decision is computed only when the runtime manuscript mode is not `off`,
`paper_build.json` exists, and the context, readiness, and binding paths are
exposed; otherwise none is written, and an absent decision is not a pass. For
those three paths and `paper_build.json`, a location outside the checkpoint or a
symlinked component raises rather than failing a gate. The decision is written to
the attempt as `publication_decision.json` under both `audit` and `enforce`; only
`enforce` also records the transition, to `finalized` or `publication_blocked`
with reason code `publication_publishable` or `publication_blocked`. The lock
step re-runs all three freshness checks — including the bound-input clause,
whatever the mode — requires the recorded attempt to be the binding's and its
state to be `finalized`, and additionally refuses a decision whose `reproduction`
sub-verdict is not `pass`, an `ors_phase1.json` that no longer hashes to a digest
that sub-verdict recorded, and a build that does not identify exactly one final
PDF.

### What the decision does not bind

The record itself is deliberately narrow. Its entire field set is
`schema_version`, `run_id`, `attempt_id`, `paper_build_digest`,
`authoring_binding_digest`, `readiness_digest`, the six sub-verdicts, `decision`
and `decision_digest`, and unknown fields are rejected, so nothing else can be
attached to it. Every other identity in the lineage is reached by dereferencing
one of those digests, and a consumer that needs one has to read the artifact it
points at:

| Identity | Reached through |
|---|---|
| profile, context, brief-bundle and source-snapshot digests; target build ID and revision | `authoring_binding_digest` |
| checkpoint ID | the exploration snapshot named by the binding's `source_snapshot_digest` |
| PDF and claim-links artifact digests | `paper_build_digest`, in the finalized build's `final_artifacts` |
| EAR digest | `paper_build_digest`, as the required `PaperBuildV1.ear_digest` |
| code-bundle lock path and digest | the context's `reproducibility`, when the checkpoint carries that lock |
| readiness evaluator version | `readiness_digest`, as `ManuscriptReadinessReportV1.evaluator_version` |
| requirement-profile policy version | the profile named by the binding's `profile_digest` |

A linked digest can also be narrower than the check behind it. `claim_evidence`
is the conjunction of the final hard gate and the finalizer's check of the exact
final TeX described under [Digest lineage](#digest-lineage), yet it links only
the gate report digest and, on failure, the one reason code above. The
sub-verdict therefore does not identify the brief bundle or the final TeX that
second check read, nor which of the two conditions failed.

Two absences are real rather than indirect. The Harness catalog snapshot digest
has no field on the decision and none anywhere in `ari.manuscript`; as
[RQGM node projection](#rqgm-node-projection) records, it stays inside the
retained attestation file, addressed only by that file's relative path and
content digest. And the decision carries no version of its own beyond the
`schema_version` constant — no evaluator or policy version on the record naming
the code that produced it. Reproducing a decision therefore rests on
`decision_digest` together with the fixed assembler and the pinned inputs, not on
a recorded evaluator identity.

## Harness attestation projection

Every non-blank string in a node's `attestation_refs` becomes one
`harness-attestation` artifact in the exploration snapshot. The artifact's
recorded status is a statement about admissibility, not a copy of the
attestation's own verdict:

| Artifact status | Condition |
|---|---|
| `invalid` | the recorded path is not a safe checkpoint-relative path, or traverses a symlink component, or the file is unreadable or not valid JSON, or it fails `HarnessAttestationV1` validation (which includes recomputing its self-advertised `attestation_digest`), or its `node_id` is not the node that referenced it |
| `missing` | the safe relative path resolves to no regular file |
| `stale` | valid and node-owned, but its `target_digest` is not the node's `verified_target_digest` — including the case where the node has none |
| `present` | valid, node-owned, and bound to the node's exact current target |

An attestation that parses is never discarded on rejection: the artifact keeps
`attestation_digest`, `target_digest`, `verdict`, `tiers` (the sorted distinct
property tiers), `belongs_to_node`, `target_matches`,
`verification_contract_digest`, and `baseline_harness_lock_digest` as metadata,
so a node-mismatched or stale attestation stays diagnosable. An attestation
rejected before it parses carries less: an unsafe recorded path records an
`unsafe_path` marker — plus the verbatim `recorded_ref` when the path itself is
unusable — while a file that is absent, unreadable, or invalid carries no
metadata at all. The attestation's own content, the
`screen`/`validate`/`certify` tier ladder, and the verdict vocabulary are
defined in
[Knowledge, Capability, and Scientific Assurance](knowledge_capability_assurance.md).

`certify_pass` is a further metadata fact, recorded independently of the
artifact status. It is the conjunction of four conditions and is never inferred
from any one of them: the attestation belongs to the node, its overall `verdict`
is `pass`, its `target_digest` equals the node's `verified_target_digest`, and
it carries at least one `certify`-tier property result with every `certify`-tier
result passing. `HarnessAttestationV1` already refuses a `pass` verdict whose
properties do not all pass, so the load-bearing part of the last condition is
the presence of a `certify` tier at all.

Only `present` artifacts whose `certify_pass` is true enter the node's
`certify_attestation_item_ids`. Under the `enforce` assurance mode, a node that
survives the earlier lane rules is `publishable` only if that tuple is non-empty
*and* `assurance_status` is `pass` *and* `assurance_tier` is `certify` *and*
`verified_target_digest` is non-empty; missing any of the four puts the node in
the `exploratory` lane with reason `certification_required`. A screen-tier pass,
and a certify pass bound to a superseded target, are therefore both retained as
admissible evidence, and neither is a publication certification.

Admissibility is decided once, when the snapshot is compiled, and no later step
revisits it. `ari.manuscript.snapshot` is the only place an attestation file is
opened and judged; every downstream consumer reads the frozen result instead —
the context's `assurance.attestation_item_ids`, the `MC-AS-001` readiness
resolver, and the finalizer all take the item IDs and statuses as given. Neither
`finalize_runtime_publication` nor `lock_runtime_publication` parses an
attestation again, re-checks node ownership or target matching, or certifies
anything. The only attestation fact the finalizer consumes is the digest already
recorded for the admitted item IDs, which it reads back out of the attempt's
`source_snapshot.json` so that the `assurance` sub-verdict cites bytes it did not
re-interpret.

What the later steps do re-verify is the file, not the verdict. The finalizer and
the lock step both re-hash every path-bearing snapshot artifact — harness
attestations included — against the digest and size recorded at compile time,
require that an artifact recorded `missing` still be absent, and refuse any
path-bearing artifact that carries no byte identity at all. That last rule is why
a symlinked or unparseable attestation is not merely inert: it is `invalid` with
no recorded digest, so it fails `freshness` and blocks the decision wherever a
decision is computed at all. Editing a retained attestation in place likewise
fails freshness rather than changing what it is admitted as. An unsafe recorded
path that never resolved to a relative path is the one rejection freshness does
not see, because no path was stored to re-hash.

Certification on demand does exist, but upstream of the decision and under
budget, never inside it. `assurance_certification` is a repair resolver kind
whose executor calls the RQGM runtime's own `certify_node` on the selected
candidate and rewrites the checkpoint, is charged one experiment run, and records
`unavailable` with `certification_runtime_unavailable` when that runtime is not
reachable. Its effect on admissibility appears only when the snapshot is
recompiled in the repair loop's rebuild step. Recompilation is in fact the only
thing that can move an attestation between statuses: a `stale` attestation
becomes `present` when the node that names it carries the matching
`verified_target_digest` at the next compile, and not before.

## Assurance sub-verdict and the reserved kernel binding

The `assurance` sub-verdict is computed inside the manuscript layer; it is not
delegated to the Constitutional Kernel. It is required only when the context's
`assurance.mode` is `enforce`, and is otherwise recorded as `not_required`, in
which case it cannot fail the decision. Under enforce it passes only when the
context carries a `publication_candidate`, at least one admitted certify
attestation item ID, and a non-empty set of digests for those items read back
from the attempt's `source_snapshot.json`. A missing candidate, an empty item
set, or an unreadable snapshot fails closed with
`required_certification_missing_or_failed`. The admission rule behind those item
IDs is the `certify_pass` conjunction above; nothing at this layer re-opens the
attestation, and nothing compares its recorded
`verification_contract_digest` or `baseline_harness_lock_digest` against a
current lock.

`ConstitutionalKernel.validate_harness_integrity` accepts a `publication`
argument and raises `CK-HAR-018` when a publication is claimed while the
attestation does not pass, or while the verification contract requires a
`certify` tier or carries a `block-publication` failure policy and no passing
certify property result exists. **No production path passes
`publication=True`.** The RQGM runtime's K/C/A harness reports call the check
without it, and the manuscript publication evaluator does not call the check at
all. The only code that sets the flag is the kernel's per-code test fixture and
the K/C/A fault-injection probe's `reviewer_publishes_uncertified` mutation,
which exist to demonstrate that the rule fires — not to gate a real
publication.

A binding between the two layers is designed but **not implemented**. It would
have the publication evaluator hand the exact target contract and attestation to
the fixed integrity check, covering the publication subject node and
configuration ID, the selected source and code digest set, the covered
ScienceData measurements, the Harness ID/version, the runner, container and
dataset locks, the environment or Provider binding the Harness contract
requires, and the current catalog lock and attestation revision — with any
mismatch, missing required certification, block-publication finding, or stale
binding raised as its own publication failure rather than folded into the
assurance verdict. None of that exists today. The binding that actually holds is
whatever `HarnessAttestationV1` itself carries, plus the node-ownership,
target-digest, verdict and certify-tier conditions recorded at projection time.

### Certification is validated, never re-run

The finalizer cannot obtain a certification. `finalize_runtime_publication`
reads the `assurance` block the compile already projected into the context,
resolves the admitted item IDs to digests in the attempt's
`source_snapshot.json`, and stops there: it dispatches no Harness run and
imports no assurance runner. The `assurance` gate can only ratify or refuse that
projection; it cannot add to it.

The projection rules above are therefore also the failure modes. An attestation
the projection refused — not owned by the node, bound to a superseded target, or
carrying no passing `certify` tier — contributes nothing to
`attestation_item_ids`, so under `enforce` a candidate whose certifications were
all refused reaches the finalizer as an empty admitted set and fails closed
exactly like one for which certification was never attempted. Both land on
`required_certification_missing_or_failed`; the finalizer neither distinguishes
the two cases nor repairs either.

Obtaining a current attestation is a separate, earlier action. The
`assurance_certification` repair kind is the path that exists: its executor in
`ari-core/ari/cli/manuscript_repair_runtime.py` calls the RQGM runtime's
`certify_node` on the candidate the verified-context selector returns, charging
the one experiment run its minimum cost declares, and refuses with
`certification_budget_exhausted` when the remaining budget cannot fund it or
`certification_runtime_unavailable` when no such runtime is attached. The
coordinator runs it during manuscript preparation — before authoring, and before
the paper stages the finalizer follows — and `ari manuscript repair` admits the
same request explicitly. There is no certify-on-publish path: publication
consumes certification evidence and never manufactures it.

## RQGM node projection

The compiler reads RQGM state off the node objects it is handed. `ari.manuscript`
imports nothing from `ari.rqgm`, and every read is duck-typed: attribute or
mapping key, missing means default. The typed per-node projection on
`ManuscriptNodeSnapshotV1` is `assurance_status`, `assurance_tier`,
`frontier_class`, `attestation_refs`, `certify_attestation_item_ids`,
`verified_target_digest`, and `property_verdicts`, plus the repair lineage
`repair_request_id`, `repair_requirement_ids`, `repair_context_digest`, and
`repair_allowed_changes`.

`valid_for_frontier` is derived, not read: it is false when the node's metrics
carry `_valid_for_frontier: false` or a truthy `_stale`, the sentinels RQGM
frontier repair writes for logical erasure. `metrics` itself is copied verbatim
whenever it is JSON-serialisable, so the remaining RQGM sentinels —
`_stale_reason`, `_erasure_event_id`, and the `_utility_policy_hash` stamp —
survive into the snapshot as untyped metrics that no compiler rule reads. The
one metric key the compiler does interpret is `_scientific_score`, which becomes
the typed `scientific_score`; when it is absent the compiler falls back to the
largest finite non-underscore metric.

A missing optional field is explicit absence, not a legacy success:

| Field | Default | What the default asserts |
|---|---|---|
| `assurance_status`, `assurance_tier`, `frontier_class` | `""` | no assurance verdict was recorded |
| `verified_target_digest` | null | no verified target was bound |
| `certify_attestation_item_ids` | empty | no attestation both belongs to the node and passed certify |
| `valid_for_frontier` | true | no erasure sentinel was present |

Those defaults never satisfy the `enforce` certification rule above. Under `off`
and `audit` they are the legacy posture and do not by themselves demote a node:
`audit` demotes only a node that recorded a non-`pass` `assurance_status`, so a
node that carries no assurance state at all and survives the earlier lane rules
stays `publishable` in both modes.

Run-level identity is thinner than the node projection. `run_id` is read from
`tree.json` or `nodes_tree.json` and falls back to the checkpoint directory
name, `checkpoint_id` is that directory name; `exploration_mode`,
`research_contract_digest`, and `research_question` are carried alongside them.
`selection_policy_digest` is the digest of the compiler's own fixed
scientific-winner policy, not of any RQGM utility policy — it is a constant of
the compiler version, so it identifies how the winner was chosen and never which
policy scored the nodes.

Not projected: RQGM epoch identity and the Harness catalog snapshot digest have
no field on `ExplorationSnapshotV1` or `ManuscriptNodeSnapshotV1`. The
attestation's own `epoch_id` and `producer_epoch_id`, and the catalog snapshot
digest reachable through the `baseline_harness_lock_digest` recorded above, stay
in the retained attestation file, addressed only by its relative path and
content digest. Governance and adversarial findings are not an admissibility
input at all: `ari.manuscript` contains no reference to either subsystem, so
they reach the manuscript only through state already written into the node
fields above or into the checkpoint artifacts the compiler reads.

## PaperBuild relationship

The legacy `PaperBuildV1` remains the paper build contract. Under enforce, its
input artifact set additionally contains `manuscript-profile`,
`manuscript-context`, `manuscript-readiness`, `section-briefs`, and
`manuscript-authoring-binding`. `PaperBuildV1.status=finalized` alone does not
mean Manuscript Complete publication is permitted; `PublicationLockV1` is the
final interlock.

Stable read types and fixed compiler helpers are exported from
`ari.public.manuscript`; mutable coordinator internals are not public API.

## RQGM archive provenance

`paper_draft_archive.jsonl` remains the paper archive's existing record stream.
When Manuscript Complete is enabled, each record additionally carries the
attempt, binding/profile/context/readiness/brief digests, ordered section brief
digests, evidence-lane ID sets, disclosures, omission count, and a canonical
`manuscript_input_fingerprint`. Candidate diagnostics record the exact artifact
digest, read-only gate-report digest, contextual-negative and forbidden
evidence-ID mentions, missing disclosures, and hard-disqualification reasons.

`paper_archive_state.json.manuscript_authoring` freezes the same fingerprint and
records the run's current status. That status is not a closed set of outcomes.
One value is written before any draft is generated — `bound` under enforce,
`audit_legacy_authoring_observed` under audit, or `stale_detected` when the
prior state, the manuscript mode, or an already recorded draft disagrees with
the current bundle — and it is then overwritten with the outcome
`manuscript_bound_winner`, `bound_linear_fallback`, `authoring_backend_failed`,
`audit_legacy_archive_winner`, `audit_legacy_linear_fallback`, or
`verification_or_fallback_failed`, the last written when the handoff to the
common verification tail — or to the linear fallback itself — raised. A
checkpoint left at `bound` is one whose archive never reached its outcome write.
`stale_detected` is terminal only under enforce, which refuses to continue;
under audit the run proceeds and the record is overwritten with
`audit_legacy_linear_fallback`. A resumed enforce run therefore rejects a
missing, different, or unbound draft fingerprint before continuation. These
archive records are provenance surfaces; they do not replace the normative
readiness or final `PublicationDecisionV1` contracts.

Exactly one archive winner reaches the canonical draft path.
`materialize_winner` is a pure select-and-copy: it copies the winning draft's
own `.tex` to the checkpoint's `full_paper.tex` and does nothing else — no gate
call, no re-scoring, no LLM call — and it leaves that path untouched when the
winner has no materialisable `.tex`, so a winner-less archive degrades to the
linear result instead of failing. Among the stages that *generate* that file it
is the only writer on the archive path: `write_paper` no-ops through its own
`skip_if_exists: {{checkpoint_dir}}/full_paper.tex` guard, and `paper_refine` —
the only other stage in `ari-core/config/workflow.yaml` that declares
`{{checkpoint_dir}}/full_paper.tex` as an output, and which would otherwise
refine over the materialised bytes — is named by `HANDOFF_DISABLED_STAGES` and
passed as a disabled stage in the handoff call into the linear pipeline. That
set holds `paper_refine` and nothing else. The suppression is conditional on a
winner actually existing: the handoff keys on the durable best-belief archive
record *and* an existing `full_paper.tex`, so a fail-open or fallback run passes
the original stage set and both stages behave exactly as in a linear run.
Disabling a stage does not cascade — a stage whose `depends_on` names a disabled
stage still runs — and because `paper_refine` is the only stage disabled,
`review_paper` and `merge_reviews` still produce their usual artifacts. What the
handoff suppresses is the application of those reviews to the TeX, not their
computation.

Single-writer is a statement about generation, not about immutability. The
verification tail still performs its own in-place edits on the canonical path
exactly as it does for a linear draft — `finalize_paper` injects or refreshes
the Code Availability block, and the locked claim-evidence checks re-run
afterwards on the edited file. What the handoff guarantees is that nothing
re-authors or revises the winner's content between materialisation and the
claim-evidence gate that reads it.

The outcome record names the winner it materialised. When the winning draft's
`.tex` is readable, `manuscript_authoring` additionally carries `winner_id` and
`winner_tex_sha256` — the SHA-256 of that draft's own `.tex`, the exact bytes
copied to the canonical path — so a build can be tied back to the candidate
record in `paper_draft_archive.jsonl`. One consequence is deliberate and worth
stating: an archive winner never receives the linear pipeline's `paper_refine`
revision pass. The archive's own reviewer-driven `paper_refine` children are
where that revision happens instead, which makes it exactly as live as the
active reviewer — the deterministic, LLM-free default reviewer that runs until a
governed `paper_reviewer` prompt is active returns no actionable revisions at
all.

## Program evaluation

`scripts/evaluate_manuscript_complete.py CASES.json --output REPORT.json`
builds a `ManuscriptEvaluationReportV1`. Each ratio retains its numerator,
denominator, and evidence refs. A zero denominator has status
`not_applicable` and no value; it is never reported as a perfect score.
Object inputs may provide `dataset_id`; bare lists require
`--dataset-id DATASET_ID`.

The report is versioned by a fixed evaluator identity: `evaluator_version` is
always `manuscript-program-evaluator-v1`, a constant of
`ari-core/ari/manuscript/evaluation.py` rather than anything read from the
cases. It is a different identity from the compiler's `manuscript-evaluator-v1`,
which is what the requirement profile advertises as its
`evaluator_compatibility` and what requirement results and readiness reports
carry; the two strings version different things and move independently. The
evaluator function is exported as `evaluate_labelled_cases` from
`ari.public.manuscript` and refuses a case set with duplicate `case_id`s.
Nothing in the compile, authoring, or publication path calls it: this is an
offline measurement over hand-labelled cases, never a gate.

### Metric vocabulary

The vocabulary is closed and unconditional. Every report carries the same
thirteen metric IDs in the same order, whatever the cases contain — a metric
with nothing to measure is present with a zero denominator and status
`not_applicable`, never omitted. Twelve are ratios; `silent-omission-count` is
the one count, and a count has a null denominator, keeps its numerator as its
value, and is therefore always `measured`.

| Metric ID | Numerator | Denominator |
|---|---|---|
| `requirement-accounting-rate` | labelled requirements whose `observed_status` is one of the four status values | all labelled requirements |
| `missing-detection-precision` | requirements labelled `expected_missing` and observed `missing` or `unavailable` | all requirements observed `missing` or `unavailable` |
| `missing-detection-recall` | the same numerator | all requirements labelled `expected_missing` |
| `silent-omission-count` | Σ `max(0, inventory_count − included_count − omission_count)` | none — this is a count |
| `inventory-projection-accounting-rate` | Σ (`included_count` + `omission_count`) | Σ `inventory_count` |
| `headline-publishable-evidence-coverage` | Σ `headline_evidence_covered` | Σ `headline_claim_count` |
| `negative-result-visibility` | Σ `negative_result_visible` | Σ `negative_result_count` |
| `unnecessary-repair-rate` | Σ `unnecessary_repair_count` | Σ `repair_request_count` |
| `repair-success-rate` | Σ `repair_satisfied_count` | Σ `repair_request_count` |
| `repair-marginal-cost` | Σ `repair_cost` | Σ `repair_satisfied_count` |
| `attempts-to-finalization` | Σ `attempt_count` over finalized cases | finalized cases |
| `rounds-to-finalization` | Σ `round_count` over finalized cases | finalized cases |
| `legacy-off-identity-rate` | cases whose `off_identity` is truthy | cases that carry an `off_identity` key |

Four of those denominators carry the argument rather than the arithmetic.

Missing-detection precision and recall fold `missing` and `unavailable` into a
single detection event, because both are statements about evidence the compiler
could not resolve. Neither metric distinguishes an absent artifact from a
resolver outage.

`silent-omission-count` is the inventory that is neither included nor recorded
as an omission, so a conserving projection reports zero. It is clamped at zero
per case, which means a case that projects more than its inventory contributes
nothing rather than cancelling a real omission in another case.
`inventory-projection-accounting-rate` has no such clamp and can exceed 1, so
over-projection stays visible there instead of hiding inside the count.

Attempts and rounds are summed and divided over finalized cases only. An
unfinished case contributes to neither numerator nor denominator, so abandoning
a hard case cannot flatter the average.

`legacy-off-identity-rate` is denominated in the cases that state an
`off_identity` verdict at all. A case that omits the key falls outside both
numerator and denominator rather than counting as a failure, so the metric
describes the labelled off-mode subset and not the dataset.

Every metric's `evidence_refs` is the same full, ordered tuple of case IDs. The
refs identify the case set a metric was computed over; they are not per-metric
provenance and do not narrow to the cases that moved a particular number.

### Report fields that are not metrics

Two report fields are not metrics, carry no denominator semantics, and are
outside the zero-denominator rule.

`blocked_reason_distribution` counts every string a case listed under
`blocked_reasons`, keyed by reason and sorted. The vocabulary is whatever the
labelled cases supplied; the evaluator neither validates it against a contract
nor defines a closed set of reasons.

`topology_costs` is one row per distinct `topology` value, sorted by that value,
carrying the case count plus the summed `llm_calls`, `experiment_runs`, and
`resource_units` the cases reported under `cost`. A case with no `topology` is
accumulated under `unspecified`. Those three counters are the whole cost
vocabulary this contract emits: there is no token counter and no wall-clock
field.

## Release evidence

`scripts/manuscript_complete_release_gates.json` is the permanent closed
release manifest. It names all four research/paper topologies, the 13 required
failure-injection families, legacy migration/rollback tests, and each
executable suite. `scripts/run_manuscript_complete_release.py` validates that
every owned test still exists, runs the suites, retains stdout/stderr by
SHA-256, and emits `ari.manuscript-release-evidence/v1` bound to the exact Git
commit/tree and manifest digest. This is an operational release record, not a
scientific Attestation and not a substitute for the retained native Harness
evidence.

## Repair admission and ordering

The set of repair requests is derived from the readiness report alone; the plan
around them only adds the admitted policy, budget, and authority digest. Every
requirement whose status is `missing` or `unavailable` and whose profile entry
declares at least one resolver contributes its ID to exactly one request,
grouped by its resolver kind — the first entry of that requirement's
`resolver_kinds`. Several
requirements sharing a resolver kind therefore become one bounded request rather
than one request each. A `satisfied` or `not_applicable` requirement, and a
requirement whose profile declares no resolver, produce no request at all.

Request identity is a canonical digest over the source context digest, the
sorted requirement IDs, the resolver kind, and the success predicate, truncated
to 24 hex characters behind a `repair-` prefix. The same gap over the same
context therefore always yields the same request ID, which is what lets the
committed transaction named after it act as an idempotency key.

Requests are ordered by a fixed priority table in
`ari-core/ari/manuscript/repair.py` and, within a tier, by resolver-kind name; a
kind absent from the table sorts last. Requirement IDs inside a request are
sorted. The order is load-bearing rather than cosmetic: execution walks the
plan's requests in exactly that order and charges the shared budget as it goes,
so the cheap recoveries always run before an experiment can exhaust it. Under
`repair.policy: auto` the coordinator admits every request in the plan;
`ari manuscript repair --request` admits only the named subset; a plan whose
policy is `disabled` executes nothing whatever its requests say.

| Tier | Resolver kinds | Why it sorts here |
|---:|---|---|
| 1 | `projection_rebuild`, `artifact_recovery` | may close the gap by recomputing or recovering what already exists |
| 2 | `assurance_certification` | certifies evidence that is already present |
| 3 | `literature_search` | recorded retrieval, no new measurement |
| 4 | `validation_experiment` | validates a contradictory or integrity-critical result |
| 5 | `baseline_comparison`, `repetition_or_uncertainty`, `ablation` | new minimal measurements for blocking claims |
| 6 | `method_clarification` | needs an admitted method record |
| 7 | `limitation_disclosure` | records a disclosure, never a fact |
| 8 | `human_decision` | cannot be closed without a person |

Each request carries the plan budget as its own ceiling, and each kind carries a
fixed minimum cost. Before a resolver is called, the remaining budget is the
plan budget minus the already-committed use; a request whose kind cannot fit is
recorded as `exhausted` with reason `plan_budget_exhausted` **without its
resolver being invoked**, so an under-budgeted round cannot half-run an
experiment. A kind with no registered executor is likewise recorded as
`unavailable` with reason `resolver_unavailable`, spending nothing.

| Resolver kind | Minimum new nodes / experiment runs / LLM calls |
|---|---|
| `baseline_comparison`, `repetition_or_uncertainty`, `ablation`, `validation_experiment` | 1 / 1 / 1 |
| `assurance_certification` | 0 / 1 / 0 |
| `literature_search`, `method_clarification` | 0 / 0 / 1 |
| every other kind | 0 / 0 / 0 |

That admission test covers only those three counters. `max_resource_units` is
not part of it: a resource overrun is caught after the executor returns, when
its reported use exceeds the request or the plan ceiling and the call fails
closed.

Grouping never merges budget attribution. Each request keeps its own success
predicate, its own allowed-change set, and its own committed transaction
recording exactly the nodes, experiment runs, LLM calls, and resource units it
consumed. Cumulative use is recomputed by summing those verified transaction
records rather than carried in memory, so a resumed round starts from committed
evidence.

## Repair commit records

Automatic repair persists each executed request as a
`ManuscriptRepairTransactionV1` and each coordinator round as a
`ManuscriptAutoRepairRoundV1`. Both are immutable and digest-bound. Resume
validates the request/authority identity, transaction digest, round digest,
contiguous round sequence, and cumulative budget before invoking another
resolver. A modified or symlinked transaction/round record fails closed.

A round is identified by the digest of the plan it executed. Its record is
stored under `auto-rounds/` in a file named for the first 32 characters of that
digest with the `sha256:` prefix removed, and both the write and the resume read
enforce that name, so a record whose filename disagrees with its own
`plan_digest` is rejected — as are a blank or duplicated `plan_digest` and a
`round` sequence that is not exactly `0 … n-1`. A transaction is identified by
its request and stored under `repair-transactions/` in a file named for the
`request_id`, under the same filename rule. Both writes go through the state
store's write-once path, which refuses to replace an existing record whose bytes
differ.

`repair.max_rounds` therefore bounds the number of distinct committed rounds for
the whole checkpoint, not per invocation. A new invocation loads every persisted
round record before its first executor call, and the guard compares the total
number of persisted rounds — those recovered plus any committed since — against
the maximum, terminating as `round_budget_exhausted`. Restarting does not refill
the round budget. The `rounds` count the loop returns is the narrower number of
rounds committed by that one invocation.

Cumulative `new_nodes`, `experiment_runs`, `llm_calls`, and `resource_units` are
recovered the same way, by summing the recorded use of every persisted
transaction before the loop starts. A recovered value that is non-numeric,
negative, or non-finite fails the invocation closed rather than being read as
zero. Recovered use that already exceeds a configured maximum ends the loop as
`cumulative_budget_exhausted` with no resolver invoked; that check runs after the
round-budget check, so an invocation past both limits reports
`round_budget_exhausted`. A maximum absent from the runtime environment reads as
zero, except the resource maximum, which is optional and bounds nothing when it
is unset.

Within a round the recovered use is subtracted from the plan budget to give each
request the budget that remains, and a request whose kind's fixed minimum cost
does not fit in the remainder is returned `exhausted` instead of being attempted.
A round in which nothing was `executed` or `satisfied` terminates the loop, and
the reason is read off the remaining statuses in a fixed order: any
`human_required` gives `human_decision_required`, otherwise any `exhausted`
gives `cumulative_budget_exhausted`, otherwise `required_resolver_unavailable`.
An executor that reports more use than its own request budget, or that pushes
cumulative use past the plan budget, is a hard error rather than a silent
truncation.

Re-execution is blocked at the request, not only at the round. Resolvers are
wrapped so that a request whose transaction file already exists is never called
again: the wrapper re-reads that transaction, requires its run, request,
request digest, source context digest and authority digest to match the request
being admitted, and returns the recorded status with zeroed use plus an
`idempotent_reuse` marker and the `prior_budget_use` it originally charged. A
resumed run therefore cannot repeat a committed side effect, cannot double-count
its cost, and cannot re-admit it under a different authority. One case
deliberately precedes both budget checks: a plan whose round record is already
persisted is reconciled at most once per invocation by rebuilding evidence and
recompiling without calling any resolver, which closes the window between
committing a round and rebuilding the evidence that round produced; if the
recompile returns the same context digest and requirement-status vector, the loop
stops as `no_progress_cycle`.
