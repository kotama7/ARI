# Manuscript Complete architecture

Manuscript Complete is the fixed boundary between research exploration and
paper authoring. It does not mean that every possible fact is known. It means
that every requirement in a selected profile has an explicit status, reason,
evidence reference, and repair posture before a writer receives input.

```text
simple BFTS or ARI-RQGM
        │
        ▼
evidence segment ── provenance / ScienceData / retrieval / EAR / figures / KCA
        │
        ▼
fixed compiler ── snapshot → context + omissions → readiness → section briefs
        │                         │
        │ ready                   └─ gap → bounded repair → research runtime
        ▼
linear writer or RQGM archive
        │
        ▼
verification segment
        │
        ▼
readiness ∧ claim gate ∧ assurance ∧ compile ∧ reproduction ∧ freshness
        │
        ▼
PublicationDecisionV1 → PublicationLockV1 or an explicit block
```

The three independent axes are `ari.mode` (`simple_bfts|ari_rqgm`),
`paper.mode` (`linear|rqgm_archive`), and `manuscript.mode`
(`off|audit|enforce`). No axis enables another. All four research/paper
topologies consume the same context and readiness contracts.

## Authority layers

- The compiler owns inventory, applicability, evidence lanes, omissions, and
  readiness. These are deterministic facts, not model judgments.
- Writers and reviewers own prose annotations only. They cannot change a
  requirement status or promote evidence.
- RQGM governs repair proposal lineage when active; the repair envelope fixes
  requirement IDs, variables, allowed changes, budget, and source context.
- KCA supplies Knowledge locks, Provider bindings, and exact-target Harness
  attestations. Repair inherits those identities and never promotes a new
  Provider or Harness.
- The publication evaluator keeps hard gates independent. A review score cannot
  compensate for a failed claim, certification, compile, reproduction, or
  freshness gate.

## Evidence lanes and subject selection

`publishable` evidence may support positive claims. `exploratory` evidence may
be discussed but is forbidden as headline proof. `contextual_negative` evidence
must remain visible as failed, null, abandoned, or inconclusive history and
cannot support a positive fact. `excluded` evidence is stale, erased, tampered,
or otherwise inadmissible.

The scientific winner is frozen before publication eligibility is evaluated.
A certified runner-up is reported as an available alternative, but it does not
silently replace an uncertified winner. Such a change requires an explicit
selection policy decision and a new bound attempt.

## Workflow and state

The single `ari-core/config/workflow.yaml` carries additive
`evidence|authoring|verification` metadata. Selected runs derive temporary
disabled-stage views; there is no second manuscript workflow. Each segment
records its workflow digest, resolved stages, logical inputs, changed outputs,
status, and source attempt. A completed record is reusable only while every
input and output digest remains fresh.

Attempts are derived from snapshot and profile digests and stored under
`.ari-manuscript/attempts/<attempt-id>/`. State changes form an append-only,
digest-linked transition log. New source bytes create a new attempt; old
attempts and blocked drafts are retained for audit.

## Backend integration

In `audit`, legacy writer inputs and output behavior remain authoritative while
the compiler emits a shadow bundle and shadow publication decision. In
`enforce`, the linear writer receives rendered section briefs instead of the
unbounded legacy context. RQGM archive candidates receive the same brief and
authoring binding; archive failure may fall back only to the bound linear
writer. Neither backend receives a research executor.

Before an RQGM archive starts or resumes, it validates the exact attempt-local
profile, snapshot, omission, context, readiness, brief, and binding chain. A
canonical archive-input fingerprint additionally covers every section brief
digest, allowed/contextual-negative/forbidden evidence ID, required disclosure,
and omission count. The fingerprint is stored on `paper_archive_state.json`,
every draft record, and governed reviewer review records. Evolved writer or
reviewer prompt hashes remain separate identities: prompt evolution cannot
change the fixed manuscript block.

In enforce mode, each candidate receives a read-only preliminary claim gate,
artifact/provenance check, contextual-negative/forbidden evidence-ID check, and
mandatory-disclosure check before best-belief selection. A hard-failing
candidate remains in archive history but has `_valid_for_frontier=false`;
reviewer utility cannot compensate for it. The final publication evaluator
repeats the evidence-lane and disclosure check against the exact final TeX for
both linear and archive authoring, so candidate screening is never the sole
interlock. Audit mode records the same diagnostics without changing authoring
eligibility and labels the result as legacy authoring. An unchanged resume
reuses bound records, while a changed fingerprint is detected before either
the winner-skip path or a new model call. If archive generation fails under
enforce, only a fallback explicitly marked as consuming the same binding is
allowed.

Automatic research repair exists only in `ari run` and `ari resume`. It creates
at most the admitted nodes, uses the normal BFTS/RQGM execution loop, and runs
normal RQGM/KCA hooks. `ari paper` can report a repair plan but cannot start an
experiment.

See [contracts](../reference/manuscript_complete_contracts.md), the
[profile guide](../reference/manuscript_complete_profile.md), and the
[operator runbook](../guides/manuscript_complete_operations.md).
