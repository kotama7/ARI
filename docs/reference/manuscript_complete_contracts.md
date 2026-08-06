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

## Status semantics

Requirement status is exactly `satisfied`, `not_applicable`, `unavailable`, or
`missing`. `unavailable` is evidence about resolver availability, not success.
Authoring is blocked by authoring-critical `missing|unavailable`; publication
is blocked by every unresolved publication-critical requirement.

The top-level publication decision is publishable only if the applicable
`manuscript_readiness`, `claim_evidence`, `assurance`, `build_compile`,
`reproduction`, and `freshness` sub-verdicts do not fail. The model validator
recomputes this logical AND.

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
digest, read-only gate-report digest, forbidden mentions, missing disclosures,
and hard-disqualification reasons.

`paper_archive_state.json.manuscript_authoring` freezes the same fingerprint and
records one of the explicit outcomes: bound archive winner, bound linear
fallback, authoring backend failure, audit legacy archive/fallback, or stale
input detection. A resumed enforce run rejects a missing, different, or
unbound draft fingerprint before continuation. These archive records are
provenance surfaces; they do not replace the normative readiness or final
`PublicationDecisionV1` contracts.

## Program evaluation

`scripts/evaluate_manuscript_complete.py CASES.json --output REPORT.json`
builds a `ManuscriptEvaluationReportV1`. Each ratio retains its numerator,
denominator, and evidence refs. A zero denominator has status
`not_applicable` and no value; it is never reported as a perfect score.
Object inputs may provide `dataset_id`; bare lists require
`--dataset-id DATASET_ID`.

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

## Repair commit records

Automatic repair persists each executed request as a
`ManuscriptRepairTransactionV1` and each coordinator round as a
`ManuscriptAutoRepairRoundV1`. Both are immutable and digest-bound. Resume
validates the request/authority identity, transaction digest, round digest,
contiguous round sequence, and cumulative budget before invoking another
resolver. A modified or symlinked transaction/round record fails closed.
