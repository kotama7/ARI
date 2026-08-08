---
sources:
  - path: ari-core/ari/viz/v1/rqgm.py
    role: implementation
  - path: ari-core/ari/viz/v1/dto.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/GovernancePage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/OverviewTab.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/RegistryTab.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/AccountabilityTab.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/ScoreLineageTab.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/EpochTimelineTab.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/EvolutionTab.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/PaperArchiveTab.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/AuditTab.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/ScientificAssuranceTab.tsx
    role: implementation
  - path: ari-core/ari/viz/api_kca.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/shared.tsx
    role: implementation
  - path: ari-core/tests/test_gui_v1_rqgm.py
    role: test
  - path: ari-core/ari/viz/frontend/src/components/Governance/__tests__/GovernancePage.test.tsx
    role: test
last_verified: 2026-08-09
---

# RQGM Governance Workspace Guide

`#/governance?run=<run_id>` is the read-only window onto one run's RQGM
governance record: which institutions exist, what they did to each other,
and how that changed the scores.

**The GUI is read-only for governance.** There is no mutation endpoint on
the `/api/v1` RQGM surface at all — every route under
`/api/v1/runs/{run_id}/rqgm/*` is a GET, and the one tab served outside that
surface (Knowledge · Capability · Assurance) reads
`GET /api/checkpoint/{run_id}/kca` through its own client, likewise a GET.
The other eight tabs draw their data from those `rqgm/*` read models through
the typed `/api/v1` client hooks. The only other read that feeds the page is
the shared node selector's option list, filled from the run tree read model
(`GET /api/v1/runs/{run_id}/tree`) purely to enumerate node ids — a GET as
well. Nothing you can click in this workspace registers a component, adopts
a policy, opens an epoch, or rewrites a score. Governance changes come from the run itself. (The Studio
can pick `ari_rqgm` for a **new** run — that decides which algorithm a run
executes, not what the institutions do; see below.)

The workspace also never re-executes a governance decision. The read
models parse committed checkpoint artifacts directly (`rqgm_state.json`,
`rqgm_transitions.jsonl`, `rqgm_audit.jsonl`,
`rqgm_adversarial_cases.jsonl`, `rqgm_registry.json`,
`prompt_evolution.jsonl`, `rqgm_meta_outputs.jsonl`,
`paper_archive_state.json`, the `rqgm/kca/admission-v1/` snapshots, the node
metric sentinels) and import no kernel code. What you see is a replay, not a
rerun.

## Getting there, and the capability state

Governance is a **v2-only route**, gated on the shell's `gui_v2` capability
flag. With `ARI_GUI_V2=0` or `false` the sidebar drops the Governance entry
and `#/governance` resolves to Home exactly like an unknown hash — silently,
with no message. That fallback lives in the shell router, above this
workspace, so it cannot show the capability screen described below: nothing
governance-specific ever mounts to explain itself. In practice you meet this
only when someone set the kill-switch on purpose — the flag ships on, and a
failed `GET /api/capabilities` is treated as `gui_v2: true` rather than
dropping you into the fallback shell (see
[Dashboard guide → The capability flag](dashboard.md#the-capability-flag)).

Open the tab from the run Overview, or type the URL. If the run has no
`rqgm_state.json` you do **not** get an error — you get a capability
screen:

> **Governance is not active for this run**
> This is a capability state, not an error.
> This run executed in the `simple_bfts` execution mode, so no RQGM
> governance artifacts exist for it.
> To govern a run, launch it with execution mode `ari_rqgm`
> (`ari.mode: ari_rqgm`). Existing runs are never modified retroactively.

Underneath it, three chips always render together — **Execution mode**,
**Mode source**, and **Paper mode** — because execution mode (`ari.mode`)
and paper mode (`paper.mode`) are independent axes and the bare word
"mode" alone is never used as a label.

Artifact presence *is* the capability signal: `rqgm/capabilities` answers
for any run, while the other RQGM routes answer a typed 404 for a
`simple_bfts` run. To get a governed run you pick `ari_rqgm` when the run
**starts** — in `workflow.yaml`, in the environment, or from the
Configuration Studio's Execution control (new runs only; see
[Execution modes](execution_modes.md) and
[Configuration Studio](configuration_studio.md)). Choosing a mode there is
a launch decision, not a governance mutation: it registers no component,
adopts no policy and rewrites no score, so this workspace stays read-only
either way. The 104 `rqgm.*` governance and tuning parameters are still
configuration-file only.

**Known gap — no governance tab shows those parameters either.** There is
no effective-configuration snapshot anywhere in this workspace: no
Governance tab reads a configuration endpoint, and the Overview tab reports
the current epoch, the policy and constitution hashes, the integrity flags,
the registry summary and the last-commit timestamp — nothing about
configuration. The one piece of configuration provenance on the page is the
**Mode source** chip, and it names where the run's execution mode was
recorded as coming from, not where any `rqgm.*` value came from. What the workspace
shows you is what the run *did*, replayed from its artifacts; what it was
*told to do* has to be read from the run's own configuration.

The tab strip is a real `role="tablist"` composite with
`aria-selected` / `aria-controls` wiring, so it is fully keyboard
navigable.

## Tab by tab

The tab strip itself has nine tabs, reading **Overview**, **Epoch Timeline**,
**Registry**, **Accountability**, **Score Lineage**, **Evolution**, **Paper
Archive**, **Knowledge · Capability · Assurance**, **Audit**. The
sections below follow a reading order instead: current state first, then
the two node-scoped tabs (Accountability and Score Lineage share one node
selector), then the run-wide timelines, then the frozen knowledge/capability/
assurance record, then the raw log.

### Overview — "what is the current governed state?"

Current epoch, the epoch's utility policy hash, the constitution hash, the
timestamp of the last committed transition, by-status registry counts, and
three **tri-state** integrity flags.

![The Governance Overview tab: the run id with the Execution mode, Mode source and Paper mode chips, the eight-tab strip, the current-epoch / epoch-utility-policy / constitution-hash cards, the Integrity panel with its three flags, and the Registry summary counting components and prompts by standing](../assets/images/en/dashboard_governance.png)

*The screenshot is a **fixture** checkpoint (`20260727120000_rqgm_governance_demo`),
generated purely to photograph this workspace. Every hash, epoch number and
count in it belongs to that prop — yours will differ, and there is nothing
to compare against. It also predates the Knowledge · Capability · Assurance
tab, so the strip in the image shows eight tabs rather than the current nine.*

Read the tri-state literally:

| Badge | Value | Meaning |
|---|---|---|
| `verified` | `true` | the chain/snapshot checked out |
| `broken` | `false` | it did not |
| `source missing` | `null` | there was nothing to check |

A missing source is **never** displayed as clean. That distinction is the
whole point: "we verified nothing bad happened" and "we have no record" are
different claims.

Current state is the replay of **committed** transitions. A torn trailing
JSONL line (an append interrupted mid-write) is ignored, and events after
an `epoch_transaction_prepare` with no matching commit are never adopted.

### Registry — "which institutions exist, in what standing?"

Two tables — components and prompts — over the committed replay. Standing
uses the closed 10-value lifecycle vocabulary, rendered verbatim:

`candidate` · `validated` · `shadow` · `probationary_active` · `active` ·
`warning` · `probation` · `quarantine` · `retired` · `banned`

Membership of the active set (`active` + `probationary_active`) carries
its own explicit marker, so "registered" is never mistaken for "in force".

`rqgm_registry.json` is a **rollup snapshot used for verification only** —
its `as_of_event_hash` is compared against the replay tail and reported as
`snapshot verified` / `snapshot mismatch` / `snapshot missing`. The rollup
never becomes the current state.

Note that node score states (`computed`, `recomputed`, `stale`,
`invalidated`, `removed`) are a **different state machine** with a
different colour family. The two vocabularies are structurally kept apart
so one can never borrow the other's meaning.

**Known gap — there is no lifecycle graph.** The Registry tab is those two
tables under a snapshot-verification badge, and nothing else. The workspace
draws no node-and-edge view of the
lifecycle, no accountability edges between components, and no per-entry
transition history; the only provenance a row carries is its
`source_event_ids`.

The `rule_id` of the T1–T21 transition that moved an entry is not rendered
anywhere either. The transitions read model does carry `rule_ids` per
committed transaction, but no tab consumes it, so "why did this component
become `quarantine`?" cannot be answered from the UI. Read
`rqgm_transitions.jsonl` for that — see
[File Formats Reference](../reference/file_formats.md), section
"`rqgm_transitions.jsonl`".

### Accountability — "who attacked this node, and did it stick?"

Pick a node from the selector; you get two clearly separated tables.

**Raw attacks** are `atk_*` claims. The DTO behind this table has no
score, penalty, or confidence field at all, and the table renders a fixed
`no penalty (unadjudicated)` cell. A raw row is *structurally* incapable
of showing a penalty number. The column is called **Claimed severity**
because that is what it is: the attacker's claim.

**Validated attacks** are adjudicated `vat_*` records — the only kind that
may drive a penalty — shown with their chain references (raw `atk_*` id →
judgment `jdg_*` id → verdict, severity) plus the impeachment-facing
fields (`target_component_id`, `affected_components`) when present.

**Reading raw vs validated is the single most important habit here.** A
long list of raw attacks is not evidence of a bad node; an empty
validated-attack table is not proof of innocence. Only the adjudication
chain converts a claim into a consequence.

**Known gap — the chain shown here stops at the validated attack.**
Adjudication continues past `vat_*` in the run itself: the epoch-boundary
audit appends `evidence_bundle`, `impeachment_motion`, `governance_defense`
and `impeachment_outcome` records to `rqgm_audit.jsonl`, and the epoch's
`governance_report` carries the `bond_accounting` block (`posted`,
`refunded`, `forfeited`, `remaining_budget`) and a `recommendations` list.
None of that reaches this tab. The RQGM read models parse no motion,
defense, outcome, bond or recommendation field, so the workspace can tell
you that an attack was validated but not whether anyone was impeached for
it, what action was requested, or how it was decided.

To follow the rest of the chain, use the Audit tab's **Record type**
filter — it is a free-text box, so you type the record type name yourself —
or read the bytes at the offsets the Audit rows give you. The record shapes
are in [RQGM artifact schemas](../reference/rqgm_schemas.md), under "The
motion-pipeline records".

### What "zero attacks" does and does not mean

Zero recorded attacks is a **data point, not evidence of health**. The UI
states this next to every empty adversarial table.

There is a stronger case the workspace calls out explicitly. When the
run's registry contains only exploration adversary roles (no `paper_*`
roles), the impeachment chain cannot fire at all — the adversaries target
the ungoverned generator role, so no amount of adversarial activity could
produce a sanction. In that configuration you see:

> **Impeachment chain structurally inert** — This run registers only
> exploration adversary roles, which target the ungoverned generator
> role — the impeachment chain cannot fire by design. Zero attacks here
> is a capability state, not evidence of health.

Three different situations, three different readings:

1. **No attacks recorded, chain live** — the adversaries ran and found
   nothing worth filing. Weak positive evidence.
2. **No attacks recorded, chain inert** — nothing could have been filed.
   No evidence at all.
3. **Attacks recorded, none validated** — claims were filed and the
   adjudication rejected them. That is a governance outcome, and it is
   visible in the validated table's verdicts.

### Score Lineage — "why is this node's score what it is?"

Two channels for one node, never merged:

**Channel 1 — adversarial penalty (within epoch).** A waterfall table:
base score → validated penalty → final score, from `UtilityRecord`
observations plus the node's metric sentinels
(`_pre_penalty_score`, `_validated_attack_penalty`, `_scientific_score`,
`_utility_policy_hash`, `_stale`). The Evidence column lists the
adjudicated `vat_*` ids the record cites. **Every row names its policy
hash** — a score is never displayed without its policy identity.

**Channel 2 — epoch utility policy history (run-wide).** Observations are
**faceted** by policy hash: one bordered facet per hash, with the
standing note:

> Scores under different policy hashes are not comparable; each policy
> hash is shown as its own facet, never one continuous series.

**Why the facets matter.** A utility policy defines what a score *means*.
When an epoch boundary supersedes the policy, the numbers before and after
are measurements on different instruments. Plotting them as one line would
manufacture a trend that does not exist. An observation with no hash
facets under `unknown` and is never folded into a hashed facet.

Below the channels, run-wide context: the **Epoch utility policies** table
(hash, lifecycle status, epochs used, adopted-via transition, and the
write-once body — shown only when the stored bytes verify against the
registered hash, otherwise `body withheld (hash mismatch)`, never
guessed), and the **Score rewrites (policy supersessions)** table joining
each utility-policy supersession with its consequences: from-policy →
to-policy, invalidated nodes, recomputes, frontier removals and
reinstatements. Those node sets come from the real event fields — they are
not recomputed by the GUI.

**Known gap — no policy diff is computed.** A score rewrite tells you
`from_policy_hash` → `to_policy_hash` and which nodes the boundary touched;
it does not tell you *what changed inside the policy*. Nothing in the read
models or the UI diffs two policy bodies, and no rewrite carries a reason
code for the change. The **Epoch utility policies** table renders each body
as a one-line `key=value` summary with nested values elided, so to compare
two policies you open their epochs on the Epoch Timeline tab — where the
body is rendered in its five governed keys — and compare them yourself.

Missing numbers render as `unknown`, never as `0`.

### Epoch Timeline — "what happened at each boundary?"

Committed epochs from the transitions replay, each as its own facet.

There is deliberately **no cross-epoch score comparison UI**, and the tab
says so:

> No cross-epoch score comparison is offered: epochs with different
> utility policy hashes are not directly comparable, so each epoch renders
> as its own facet.

Absence stays absence:

- a still-open epoch has no committed boundary transaction, so it shows
  *"No committed boundary transaction yet — transition counts do not exist
  (this is absence, not zero activity)"* rather than a row of zeros;
- `fallbacks` renders as *"fallbacks: unknown (no audit source)"* unless
  the real `epoch_transition` audit record supplied the array.

Selecting an epoch loads the committed detail: sequence, status, nodes at
open, previous epoch, registry version, epoch fingerprint; the write-once
**utility policy body** in its 5 governed keys (`composite`,
`axis_weights`, `frontier_score`, `depth_penalty_lambda`, `ucb_c`); the
opening and closing boundary transactions each with their raw source
(`rqgm_transitions.jsonl@<byte offset>`); and whether a governance report
is present.

### Evolution — "what was proposed, and what was actually adopted?"

Grouped by kind: prompt evolution, utility policy evolution, meta outputs.
The separation is structural:

- every row **is a raw candidate record** with its own candidate-status
  vocabulary, labelled `candidate (not adopted)` by default;
- validation runs are counted separately — evidence of validation, not of
  adoption;
- `adopted` is derived **only** by joining the proposed hash against the
  committed registry replay. An adopted row cites the transition that
  adopted it (`Adopted via`). The proposal record can never promote
  itself;
- meta outputs are `adopted = null` and render as `inert provenance (not
  adoptable)` — an observation, not a failed candidate.

A missing log renders as *"`prompt_evolution.jsonl` not present for this
run"*, never as an empty-but-healthy table. Every row names its raw source
as `file@offset`.

### Paper Archive — "how was the paper selected?"

Bounded scalars with two independence rules enforced in the UI:

- **Execution mode and paper mode are independent axes.** Both chips
  always render side by side with an explicit note; the bare word "mode"
  is never used alone.
- **The best-belief draft is a reviewed selection** — never equated with
  the governance winner or with the research result.

Absence stays absence here too: when `paper_archive_state.json` is absent,
the `linear` chip renders **with** the "derived from absence" note
(`state_present = false` is surfaced, so the derivation is transparent
rather than fabricated); an absent draft archive shows "not present"
instead of a `draft_count` of 0; and `anchor.enabled = null` means
"no frozen paper utility policy" — unknown, not disabled.

When `anchor.enabled` is `false`, the tab carries the consequence
verbatim: the archive is reviewed best-of-N and writer sanctions cannot
fire.

### Knowledge · Capability · Assurance — "what was this run allowed to know, run, and verify with?"

Served by `GET /api/checkpoint/{run_id}/kca` (`ari.viz-kca/v1`), which reads
the run's committed `rqgm/kca/admission-v1/` snapshots directly and imports no
registry or resolver. Three cards, kept apart in both the wire shape and the
UI so one domain's authority can never be read as another's:

- **ARI Knowledge Skill Registry** — non-executable, content-addressed
  procedural knowledge; it grants no tool authority. Catalog snapshot digest,
  Knowledge Skill Lock digest, active-skill and node-use-record counts, and
  the catalog table.
- **ARI Capability Provider Federation** — executable providers and their
  run-frozen tool schemas (MCP is transport, not a Knowledge Skill). Provider
  Lock and Capability Binding Lock digests, plus the bound and unsatisfied
  capability counts.
- **ARI Harness Registry / Scientific Assurance** — independent, target-bound
  verification; provider success is not an Attestation. Verification Contract
  and Baseline Harness Lock digests, plus the requirement and Attestation
  counts.

A run with no `run_admission.json` gets *"This run has no K/C/A admission
snapshot."* — a capability state, not an error. A snapshot file that is
unreadable, oversized, or truncated at the record cap surfaces as a
`degraded_reasons` entry in the same degraded panel the rest of the workspace
uses, rather than silently shrinking a table.

### Audit — "show me the raw log"

A cursor-paged table over `rqgm_audit.jsonl` with **Record type** and
**Epoch** filters and a [Load more] appender. The cursor is the backend's
stable byte offset, so appended pages never duplicate rows of the
append-only log. Changing a filter starts a fresh page chain — a filtered
view can never inherit rows from a differently-filtered one.

Every row names its raw source: `rqgm_audit.jsonl@<byte offset>` plus the
event hash. The table ends with an explicit *"End of committed log"*.

**Known gap — the transition log has no table of its own.**
`GET /api/v1/runs/{run_id}/rqgm/transitions` is a published endpoint with
the same byte-offset cursor contract, but nothing in this workspace calls
it: the typed client exposes eleven RQGM fetchers and the transition page is
not one of them. Transition evidence reaches the UI only indirectly — as the
Overview tab's transitions-chain integrity flag, as an epoch's opening and
closing boundary transactions on the Epoch Timeline detail, and as the
`source_event_ids` on a Registry row. To walk the transition log itself,
call the endpoint directly; it is listed in
[REST API reference](../reference/rest_api.md) under "RQGM governance
(read-only)".

## Drilling from an aggregate to the raw artifact

The workspace's traceability rule is that every aggregate view must trace
back to raw events or artifacts. In practice:

| You are looking at | The drill-down handle on the row |
|---|---|
| an audit event | `rqgm_audit.jsonl@<byte offset>` + event hash |
| an epoch boundary transaction | `rqgm_transitions.jsonl@<byte offset>` |
| an evolution candidate | `prompt_evolution.jsonl@<offset>` / `rqgm_meta_outputs.jsonl@<offset>` |
| a score observation | the record id and the `vat_*` ids it cites |
| a registry entry | the `source_event_ids` that produced its current standing |
| a score rewrite | its transition id and `source_event_ids` |

To go from an aggregate to the bytes, take the offset and read the file
inside the checkpoint directly, for example:

```bash
# the exact line an audit row came from
tail -c +$((OFFSET + 1)) "$CKPT/rqgm_audit.jsonl" | head -1 | python -m json.tool
```

Offsets are 0-based byte positions of the line start, which is why they
are stable for an append-only log. The event hash contract is
schema-scoped: a legacy `schema_version: 1` record hashes its payload alone
(`sha256(canonical_json(payload))[:12]`), while every newly written
`schema_version: 2` record carries a full-length
`sha256(canonical_json({schema_version, event_id, event_type,
transaction_id, payload, prev_event_hash}))` — the whole replay-relevant
envelope, not just the payload.

## Degraded and broken chains

A corrupt artifact yields an honest **HTTP 200 with flags**, never a 500,
and never a blank screen. Two visible layers:

1. **Integrity flags** on the Overview tab flip to `broken` (or
   `source missing`), and the read model attaches `degraded_reasons`
   describing what failed — including the byte offset where a hash chain
   broke.
2. **The degraded panel** replaces or accompanies the affected view:

   > **Governance record degraded** — Parts of the governance record are
   > missing or inconsistent. This describes the governance artifacts
   > only — it does not mean the research run failed.

That last sentence is a deliberate invariant of the whole workspace:
**governance blocked ≠ research failed.** The run Overview repeats it when
it surfaces governance blockers.

Rows still render under a broken chain — honestly flagged, not hidden. A
broken audit chain does not erase the audit table; it tells you the table
can no longer be trusted as tamper-evident, and you can still walk the raw
offsets yourself.

## See also

- [Execution modes](execution_modes.md) — turning on `ari_rqgm` and paper mode.
- [RQGM architecture](../concepts/rqgm_architecture.md) — what the institutions are.
- [RQGM evaluation guide](rqgm_evaluation.md) — running and measuring governed experiments.
- [RQGM artifact schemas](../reference/rqgm_schemas.md) — the on-disk record shapes.
- [Dashboard guide](dashboard.md) — navigation, deep links, freshness.
- [Configuration Studio](configuration_studio.md) — selecting the execution/paper mode for a new run, and why the governance tuning fields stay read-only.
