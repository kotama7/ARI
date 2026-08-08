---
sources:
  - path: ari-core/ari/manuscript/profiles.py
    role: implementation
  - path: ari-core/ari/manuscript/builder.py
    role: implementation
  - path: ari-core/ari/manuscript/snapshot.py
    role: implementation
  - path: ari-core/ari/manuscript/readiness.py
    role: implementation
  - path: ari-core/ari/manuscript/briefs.py
    role: implementation
  - path: ari-core/ari/manuscript/publication.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-core/ari/manuscript/contracts.py
    role: schema
  - path: ari-core/ari/config/__init__.py
    role: config
  - path: ari-core/config/workflow.yaml
    role: config
  - path: docs/adr/manuscript_complete/MC-ADR-007-runner-up.md
    role: doc
last_verified: 2026-08-09
---

# `generic_empirical_v1` profile

The initial profile is for empirical papers. Applicability is derived from
typed context characteristics; a writer cannot opt a requirement out.

| Requirement | Applies when | Authoring | Publication | Primary resolver |
|---|---|---:|---:|---|
| MC-RQ-001 question/objective | always | block | block | method/human clarification |
| MC-RQ-002 hypothesis/falsification | hypothesis testing | block | block | method/human clarification |
| MC-ME-001 method | always | block | block | artifact recovery |
| MC-ME-002 configuration/environment | empirical | block | block | artifact recovery |
| MC-ME-003 protocol/workload/stopping | empirical | block | block | artifact recovery/validation |
| MC-RS-001 primary result identity | result claim | block | block | projection/validation |
| MC-RS-002 uncertainty | stochastic claim | block | block | repetition |
| MC-CP-001 baseline | comparative claim | block | block | baseline experiment |
| MC-CP-002 equivalent protocol | comparator exists | block | block | validation |
| MC-AB-001 component ablation | multi-component claim | block | block | ablation |
| MC-CL-001 claim coverage | result claim | block | block | projection rebuild |
| MC-CL-002 numeric reproducibility | numeric result | block | block | projection/validation |
| MC-NG-001 negative accounting | always | report | block | projection/disclosure |
| MC-SL-001 selection accounting | multiple candidates | report | block | projection rebuild |
| MC-RW-001 recorded related work | always | block | block | recorded retrieval |
| MC-RW-002 novelty distinction | novelty claim | block | block | recorded retrieval/human |
| MC-LM-001 limitations | always | block | block | disclosure |
| MC-LM-002 validity threats | empirical | report | block | disclosure |
| MC-RP-001 EAR/source/environment | empirical | block | block | artifact recovery |
| MC-RP-002 commands/locks | reproducibility claim | block | block | artifact recovery |
| MC-AS-001 current certification | assurance enforce | report | block | fixed certification |
| MC-OM-001 omission accounting | manuscript enabled | block | block | projection rebuild |

Characteristics such as `stochastic_claim`, `comparative_claim`, and
`multi_component_claim` come from recorded measurements, configurations,
metric vocabulary, contribution structure, and node labels. They are not
inferred from reviewer prose. A future profile change requires a new profile
ID/version and therefore a new attempt identity.

## Evidence lane assignment

`build_manuscript_context` gives every node of the exploration snapshot exactly
one evidence lane by running a fixed ordered test list (`_lane` in
`ari-core/ari/manuscript/builder.py`). The first test that matches wins; it
supplies the lane and the reason codes recorded on
`EvidenceRecordV1.reason_codes`.

The provenance statuses read by tests 2-5 are the union of the per-node status
recorded in `node_provenance_audit.json` (workflow stage
`audit_node_provenance`) and the status the snapshot projection recomputes for
every artifact the node references.

| # | Test | Lane | Reason code |
|---:|---|---|---|
| 1 | terminal execution status: `failed`, `abandoned`, `cancelled`, `error`, `inconclusive`, `null` | contextual_negative | `execution_<status>` |
| 2 | any referenced artifact whose re-hash disagrees with the recorded digest/size | excluded | `artifact_digest_mismatch` |
| 3 | any referenced artifact that is gone from the checkpoint | excluded | `artifact_missing` |
| 4 | any referenced artifact that is unsafe: path escape, symlink component, unreadable/unparseable, or an attestation naming another node | excluded | `artifact_invalid` |
| 5 | any referenced artifact the audit could not verify against a recorded baseline hash, or a node artifact entry that names no path at all | exploratory | `artifact_unhashed` |
| 6 | `valid_for_frontier` false — RQGM selective erasure (`_valid_for_frontier: false`) or a `_stale` metric sentinel | excluded | `stale_or_erased` |
| 7 | no real data, or no metrics | contextual_negative | `no_real_measurement` |
| 8 | `frontier_class == "debug_frontier"` | exploratory | `debug_frontier` |
| 9 | `frontier_class == "uncertified_frontier"` | exploratory | `uncertified_frontier` |
| 10 | any property verdict `fail` or `tampered` | excluded | `assurance_property_failed` |
| 11 | `assurance.mode: enforce` without **all four** of: assurance status `pass`, assurance tier `certify`, at least one admitted certify attestation, a recorded verified target digest | exploratory | `certification_required` |
| 12 | `assurance.mode: audit` with a *recorded* assurance status that is not `pass` | exploratory | `assurance_<status>` |
| 13 | otherwise | publishable | `typed_measurement` |

The order is normative. Provenance integrity (2-5) is tested before assurance
(10-12), so a node whose artifacts cannot be re-hashed against their recorded
identity is excluded however well it was certified. The frontier classes (8-9)
are tested before the mode-dependent tests, so a debug or uncertified frontier
node is never publishable under any mode: RQGM already recorded that the node's
harness verdict was `fail` (`debug_frontier`), or that no `pass` verdict was
established at all — inconclusive, infrastructure error, or KCA-blocked
(`uncertified_frontier`). No assurance mode may promote that back into
publication support.

### Mode dependence

Tests 1-10 and 13 are mode-independent. Only tests 11-12 read
`assurance.mode` (`off` | `audit` | `enforce`, `AssuranceRuntimeConfig`):

| Node shape | `off` | `audit` | `enforce` |
|---|---|---|---|
| typed measurement, no attestation | publishable | publishable | exploratory |
| screen attestation, no certify | publishable | publishable | exploratory |
| certify `pass` admitted against the recorded target | publishable | publishable | publishable |
| recorded assurance status not `pass`, properties still `pass` | publishable | exploratory | exploratory |
| any property `fail` or `tampered` | excluded | excluded | excluded |
| stale or logically erased | excluded | excluded | excluded |
| only certify attestation is bound to a different target | publishable | publishable | exploratory |
| debug or uncertified frontier | exploratory | exploratory | exploratory |

`audit` deliberately does not downgrade evidence that merely lacks a
certification. Test 12 fires only on a *recorded* non-`pass` assurance status;
an empty `assurance_status` falls through to `publishable`. Absence of an
assurance record means assurance was not run, which is the legacy posture, and
refusing it as publication support is precisely what `enforce` adds.

An attestation whose `target_digest` does not match the node's
`verified_target_digest` is projected with artifact status `stale`. `stale` is
not one of the statuses that exclude a node (2-4), so such a node stays
admissible under `off` and `audit`; the attestation is simply not admitted into
`certify_attestation_item_ids`, which is why test 11 demotes the node under
`enforce` when it was the only certify attestation.

### Consequences of the lane

`publishable` is the only lane whose records enter a section brief's allowed
positive-claim evidence; `exploratory` and `excluded` records are listed as
forbidden, and `contextual_negative` records are listed as disclose-only.
Separately, `EvidenceRecordV1.claim_eligible_fact` is true for `publishable`
and `exploratory` and false for `contextual_negative` and `excluded`; the
contract refuses any record that claims publication eligibility outside the
`publishable` lane, or claim eligibility inside a negative/excluded lane.

## Subject selection

MC-SL-001 and MC-AS-001 both depend on how the compiler picks the paper's
subject. That decision is projected onto two `ManuscriptContextV1` blocks:
`subjects`, which carries two subjects computed by different policies, and
`assurance`, which repeats the outcome beside the certification evidence.

`scientific_winner` comes from the snapshot's own selection policy, whose
payload is hashed into `ExplorationSnapshotV1.selection_policy_digest`:

| Payload key | Value |
|---|---|
| `policy` | `manuscript-scientific-winner-v1` |
| `validity` | `valid_for_frontier` |
| `eligibility` | `real_data_then_all` |
| `order` | `scientific_score_desc`, then `node_id_desc` |

`real_data_then_all` means the valid nodes carrying real data when any valid
node does, and otherwise every valid node. A node's score is
`metrics["_scientific_score"]` when that value is a real number, otherwise the
largest numeric metric whose key does not start with `_`, otherwise absent;
booleans never count, and an unscored node sorts below every scored one.
Metrics reach the snapshot through a JSON safety pass that stringifies the
whole mapping when any value is non-finite, so a single `NaN` leaves that node
unscored.

`publication_candidate` is the scientific winner if and only if the winner's
own evidence record is in the `publishable` lane. Otherwise the candidate is
null, and `selection_reason` records which case applies:

| `selection_reason` | Meaning |
|---|---|
| `scientific_winner_is_publishable` | the candidate is the winner |
| `certified_alternative_available:<node-id>` | candidate null; the named node is the highest-scoring publishable node under the same ordering |
| `no_publishable_candidate` | candidate null; no node is publishable |

`certified_alternatives` lists every publishable node other than the scientific
winner, in snapshot order — depth, then node ID — not in score order, so the
node named by the reason code is not necessarily the first entry. Both that
field and `assurance.certified_node_ids` say "certified", but the predicate
they apply is the `publishable` lane; only under `assurance_mode=enforce` does
that lane require a certify-tier attestation.

The `assurance` block repeats `publication_candidate`, `scientific_winner`, and
`selection_reason` beside `certified_node_ids` — every publishable node, the
winner included — the `present` harness-attestation items a node recorded as
its own certify attestation, and every harness-attestation item that is not
`present`. MC-AS-001 reads exactly that block: it is satisfied only when the
candidate is non-null and appears in `certified_node_ids`, and it reports
`unavailable` rather than `missing` when no certify attestation item is present
at all. Under `enforce`, a null candidate additionally adds an automatic
limitation stating that the scientific winner does not yet have
publication-admissible certification. MC-SL-001 reads `node_count` and
`selection_reason`, and is satisfied only when the exploration history has one
entry per snapshot node and a reason is recorded.

Recording an alternative is not selecting it. Per
[MC-ADR-007](../adr/manuscript_complete/MC-ADR-007-runner-up.md) the compiler
never substitutes a publishable runner-up for a blocked winner: no code reads
`certified_alternatives` back as a subject, and a silent substitution would
change what the paper is about without saying so. The winner stays
publication-blocked until an explicit selection decision creates a new attempt.
The whole `subjects` block also reaches the abstract section brief as the
`subject-selection` item, so the writer receives the divergence and its reason
rather than only the surviving subject.

### When no publication candidate exists

MC-AS-001 is applicable only under `assurance.mode: enforce` — the
`assurance_enforce` characteristic is `assurance_mode == "enforce"` and nothing
else — and it is publication-blocking but not authoring-blocking. A null
candidate therefore costs different things in different modes:

| `assurance.mode` and attestation state | MC-AS-001 status / reason | Effect on authoring verdict | Effect on publication verdict |
|---|---|---|---|
| `off` or `audit` | `not_applicable` / `applicability_rule_false` | none | none |
| `enforce`, `assurance.attestation_item_ids` non-empty | `missing` / `publication_certification_missing` | none | `blocked` |
| `enforce`, `assurance.attestation_item_ids` empty | `unavailable` / `publication_certification_unavailable` | at best `ready_with_disclosures` | `blocked` |

In `off` and `audit` the requirement is inert: no evidence refs, no resolver,
no verdict effect. The `assurance` sub-verdict of `PublicationDecisionV1` is
then `not_required` rather than passing, because the runtime marks assurance
required only when the mode is `enforce`. The null candidate and its
`selection_reason` are still recorded in both blocks.

The third row moves the authoring verdict only through the general rule that
any `unavailable` requirement downgrades a `ready` report to
`ready_with_disclosures`. MC-AS-001 never blocks authoring in either failing
row, and never improves an authoring verdict the other requirements already
depress.

That asymmetry is the design. Because the enforce lane admits a node as
`publishable` only with a passing certify-tier assurance status, at least one
admitted certify attestation, and a verified target digest, a non-null
candidate under `enforce` is always certified — so the two failing rows are
exactly the runs that get the automatic certification limitation. An enforce
run with an uncertified winner still authors, and the limitation puts the gap
in the manuscript. A draft that states the gap is a legitimate artifact; the
same draft presented as certified is not. Only the publication lock stays
unreachable, until a current certification covers the subject.

### Reserved: an explicit selection decision

MC-ADR-007 permits reversing the no-fallback default only with a versioned
selection policy and mandatory disclosure. **No such policy is implemented.**
No field of `ManuscriptRequirementProfileV1` or `RequirementSpecV1`, no
configuration key, and no code path promotes a runner-up to the subject; when
the winner is not publishable, the candidate is null unconditionally. The
`selection_policy_digest` above is not that policy either — it pins how the
scientific winner is ordered, not whether the subject may be replaced.

If such a policy is ever added, the subject change must recompute
applicability, every requirement result, and `limitations` against the new
subject before readiness may report `ready`: a requirement set evaluated
against the old subject does not describe the new one, and a limitation
inherited across a subject change is a disclosure about a node that is no
longer the paper's subject. That obligation is reserved design, not available
behaviour.
