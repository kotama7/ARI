---
sources:
  - path: ari-core/ari/viz/v1/dto.py
    role: implementation
  - path: ari-core/ari/viz/v1/queries.py
    role: implementation
  - path: ari-core/ari/viz/v1/rqgm.py
    role: implementation
  - path: ari-core/ari/viz/checkpoint_lifecycle.py
    role: implementation
  - path: ari-core/ari/viz/v1/challenges.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Overview/OverviewPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/ScoreLineageTab.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Governance/AccountabilityTab.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/TreeV2/treeNodes.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/i18n/en.ts
    role: implementation
  - path: ari-core/ari/rqgm/frontier_repair.py
    role: implementation
  - path: ari-core/ari/rqgm/events.py
    role: implementation
  - path: ari-core/ari/rqgm/utility_evolution.py
    role: implementation
  - path: ari-core/tests/test_gui_v1_rqgm.py
    role: test
  - path: ari-core/ari/viz/frontend/src/components/Overview/__tests__/OverviewPage.test.tsx
    role: test
last_verified: 2026-07-28
---

# Research and Governance State

An ARI run has more than one state at any moment, and the states answer
different questions. "The run is still executing", "the run has reached the
paper stage", "the governance record for this run is degraded", and "this
node's score no longer counts" are four independent facts. Conflating any two
of them produces a claim ARI cannot support.

This page is the conceptual home of those distinctions. It is what the
dashboard's truth rules are derived from — the labels, the separate rows, the
refusal to draw one continuous score line — and it applies equally to anyone
reading a checkpoint by hand.

Related pages: [Dashboard Architecture](gui_architecture.md) for how these
rules are enforced in the UI, and
[Constitutional ARI-RQGM Architecture](rqgm_architecture.md) for the kernel
that produces the governance artifacts.

---

## 1. Four state machines, not one

| State machine | Question it answers | Scope | Exists for |
|---|---|---|---|
| Run lifecycle | Is this run executing right now? | one run | every run |
| Research phase | How far along the research pipeline is it? | one run | every run |
| Governance stage | Which governed epoch and score policy is in force? | one run | `ari_rqgm` runs only |
| Node score state | Does this node's score still count, and under which policy? | one node | `ari_rqgm` runs only |

They advance for different reasons, at different times, and none of them
implies any of the others. A run can be `running` with no phase yet, or
`completed` while its governance record is degraded, or governed and healthy
while one particular node's score is invalidated.

---

## 2. Run lifecycle and research phase

Both are derived read-only from committed artifacts — nothing in the
dashboard *records* a lifecycle or a phase.

**Run lifecycle** is derived per checkpoint directory: a live process for the
run means `running`; otherwise the node tree decides — a tree that still says
`running` with no live process is an orphaned `stopped`, an otherwise
populated tree is `completed`, and a present `review_report.json` also settles
it as `completed`. With nothing to go on, the honest answer is `unknown`.

| Value | Means |
|---|---|
| `running` | A live process for this run was found |
| `stopped` | The tree says a node was running, but no process is alive (orphaned) |
| `completed` | The tree is populated with no running node, or a review report exists |
| `unknown` | Not enough evidence — deliberately not defaulted to "completed" |

**Research phase** is a separate derivation from artifact presence: a review
report means `review`; a paper (or a started pipeline) means `paper`; an idea
artifact means `bfts`; nothing yet means no phase at all. The frozen phase
vocabulary the UI renders is `idle`, `starting`, `bfts`, `paper`, `review`,
with "no phase derived yet" displayed as `idle`.

The two are orthogonal on purpose. `stopped` + `paper` is a perfectly
coherent state (the pipeline was interrupted after the paper was written), and
so is `running` + `idle` (the run just started and nothing is on disk yet).

---

## 3. Governance stage is a different timeline

For runs executed in the `ari_rqgm` execution mode, a *governance stage* also
exists: the currently open epoch and the utility policy hash in force, read
from the replay of committed governance transitions.

The rules that follow from it being a separate state machine:

- **It is rendered as its own labelled row**, never merged into the research
  phase. A run's phase says nothing about its epoch, and the epoch says
  nothing about its phase.
- **It does not exist for `simple_bfts` runs.** Absence here is a capability
  state — "governance is not active for this run" with the reason attached —
  not an error, and not a zero.
- **Governance accepted ≠ research completed.** A governance transition
  committing successfully means the institution followed its own rules. It
  makes no claim about whether the science worked.
- **Execution mode and paper mode are independent axes.** A run is governed or
  not (`ari.mode`), and separately uses the archive paper flow or the linear
  one; all four combinations are valid.

### What "governance blocked" does **not** mean

The dashboard surfaces governance blockers when the governance read model
reports degraded reasons or a failing integrity chain (transitions chain,
registry snapshot, audit chain — each tri-state: verified / broken / source
missing). This is one of the easiest signals to misread, so state it plainly.

A governance blocker means: **parts of the governance record are missing,
inconsistent, or fail their hash chain.** It is a statement about the
governance *artifacts*.

It does **not** mean:

- the research run failed, or produced bad results;
- the run stopped, or is stuck;
- a component was sanctioned, quarantined or banned (those are registry
  lifecycle events with their own statuses — §4);
- the results shown elsewhere on the page are wrong.

The inverse misreading is equally wrong: **zero recorded attacks is a data
point, not evidence of health.** The registered generator can now be bound
through a node's write-once producer provenance, but an attack still requires
triggering, adjudication, and matching epoch provenance. Legacy or ambiguous
nodes remain targetless. Silence therefore says nothing without coverage and
provenance data.

---

## 4. Registry lifecycle vs node score state

These are the two vocabularies most often confused, because both are
sometimes called "status". They are separate state machines and are never
mixed into one field — in the API they are two distinct closed types, so a
registry status cannot even be *represented* in a node-state field.

**Registry component lifecycle** — the state of a *governed component or
prompt* (a role's implementation). A ten-value closed vocabulary, mirrored
verbatim from the kernel in its declared order: `candidate`, `validated`,
`shadow`, `probationary_active`, `active`, `warning`, `probation`,
`quarantine`, `retired`, `banned`. Roughly, the first five are the admission
path and the last five the sanction path; the transitions between them are
kernel rules, not a UI concern, and the dashboard only ever replays what was
committed.

**Node score state** — the state of *one node's score*, a five-value
vocabulary:

| State | Means |
|---|---|
| `computed` | Scored normally under the epoch's policy |
| `recomputed` | Re-scored from surviving inputs (the record names the epoch) |
| `stale` | Contaminated by a retired component — no longer feeds frontier scoring or best-node selection |
| `invalidated` | The policy the score was formed under was superseded |
| `removed` | Withdrawn from the frontier |

Two further discipline rules apply on the accountability side, and they are
enforced structurally rather than by convention:

- **A raw attack can never carry a number.** Raw adversarial claims and
  adjudicated ones are different record kinds; the raw kind has no score,
  penalty or confidence field at all, and its "claimed severity" is the
  attacker's claim, not a penalty. Only an adjudicated validated attack can
  drive a penalty.
- **Current state is the committed replay.** A rollup snapshot is read only
  to check that it agrees with the replay; an uncommitted tail is never
  adopted.

---

## 5. Scores are only comparable inside one policy

Every score observation the dashboard shows carries the **utility policy
hash** it was made under. That hash is a content hash of the canonical policy
body, so two different hashes mean two literally different scoring functions.

This is not a display nicety. In the `ari_rqgm` mode, an epoch boundary can
rewrite the utility function itself, and the consequence is that *the entire
score is rewritten* — including for nodes that were never attacked. A number
computed under policy `A` and a number computed under policy `B` are not two
points on one curve; they are two measurements from two different instruments.

The rules that follow:

- **No score is displayed without its policy identity.** "Score under policy
  `<hash>`", never a bare number.
- **Different policy hashes are faceted, never joined.** Each hash gets its
  own group; there is no single continuous series across a policy change,
  and no cross-epoch score comparison is offered at all.
- **The two lineage channels stay separate.** Channel 1 is the adversarial
  penalty *within* an epoch (base score → validated penalty → final score,
  with the adjudicated record ids as evidence). Channel 2 is the
  epoch-boundary policy rewrite. They are separate lists precisely so no
  consumer can accidentally merge them into one history.
- **Two recompute paths are explicit.** When scored evidence goes stale,
  penalty utility is recomputed from surviving inputs under the original
  epoch's frozen weights. When the policy itself is superseded, the boundary
  re-scores the node's stored policy-independent raw axes under the new
  criterion and stamps the new policy hash. It never converts an old
  composite; missing raw axes invalidate the node.

---

## 6. Stale, invalidated, removed, deleted — four different things

The word "deleted" is banned in this vocabulary because three of these four
states involve no deletion whatsoever. Governance erasure is **logical only**:
nothing is physically deleted or rewritten. The evidence stays on disk; what
changes is whether it is allowed to influence anything.

| # | State | What actually happened | Where it lives | Reversible? |
|---|---|---|---|---|
| 1 | **Stale** | A record was produced by, or materially depends on, a retired component. It stops feeding frontier scoring and best-node selection. | Additive node sentinels (`_stale`, `_valid_for_frontier`, `_stale_reason`, `_erasure_event_id`) persisted through the tree, plus a selective-erasure event in the audit log | Yes — the record and its provenance are intact |
| 2 | **Invalidated** | The utility policy the score was formed under was superseded, so the score itself no longer holds. | Same sentinel channel, with a distinct stale reason, plus the erasure event's invalidated-node list | Yes — recompute under surviving inputs is a normal outcome |
| 3 | **Removed** | The node was withdrawn from the search frontier (it stops being expanded). | Frontier-rebuild events list removed and reinstated nodes | Yes — reinstatement is an ordinary event |
| 4 | **Physically deleted** | The checkpoint directory and its logs are gone from disk. | Nothing — this is the absence of everything above | **No** |

Only the fourth is destruction, and it is the one operation the system treats
as dangerous: deleting a checkpoint through the dashboard is refused unless it
carries a server-issued, single-use confirmation challenge bound to that exact
path, and the deletion is scoped to inside a `checkpoints/` directory.

The practical consequences of the logical/physical split:

- A stale or invalidated node is still **auditable**. You can still read what
  it did, why it was staled, and which event staled it. That is the entire
  point: retracting a result must not destroy the record of having produced
  it.
- A stale reason is **diagnostic provenance**. It exists so a human — or a
  read model rendering a label — can say *why* a node was staled; the kernel
  makes no control decision from it.
- **Evidence is never retroactively rewritten.** Existing runs are never
  modified to gain governance, and superseded records remain on disk rather
  than being overwritten. A live boundary may deliberately replace the
  in-memory frontier score by re-composing stored raw axes under the newly
  adopted policy; the erasure event records that re-score and both policy
  identities.

---

## 7. Vocabulary quick reference

| Term | Use it for | Do not use it for |
|---|---|---|
| Run lifecycle | Is a process alive / did it finish | Research quality |
| Research phase | Position in the pipeline (bfts / paper / review) | Governance progress |
| Governance stage | Current epoch + policy in force | Research success or failure |
| Governance blocked | The governance artifacts are degraded or fail integrity | A failed experiment or a stopped run |
| Registry status | A governed component's lifecycle (candidate … banned) | A node's score |
| Node score state | One node's score (computed … removed) | A component's lifecycle |
| Raw attack | An unadjudicated adversarial claim | Anything numeric |
| Validated penalty | The adjudicated, score-affecting outcome | An attacker's claimed severity |
| Stale / invalidated / removed | Logical states, fully auditable | "Deleted" |
| Deleted | Physical removal of a checkpoint from disk | Any governance state |

---

## See also

- [Dashboard Architecture](gui_architecture.md) — where these rules are
  enforced, and why read models cannot fabricate a verdict.
- [Dashboard Guide](../guides/dashboard.md) — where each of these states is
  displayed in the UI.
- [Constitutional ARI-RQGM Architecture](rqgm_architecture.md) — epochs,
  registry transitions, selective erasure and frontier repair.
- [RQGM Runtime Walkthrough](rqgm_runtime_walkthrough.md) — one governed run
  traced end to end.
- [Execution Modes](../guides/execution_modes.md) — how a run becomes
  governed in the first place.
- [Glossary](../reference/glossary.md).
