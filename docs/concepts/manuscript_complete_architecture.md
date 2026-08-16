---
sources:
  - path: ari-core/ari/manuscript
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/cli/manuscript.py
    role: implementation
  - path: ari-core/ari/cli/manuscript_repair_runtime.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-core/ari/cli/projects.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_archive.py
    role: implementation
  - path: ari-core/ari/rqgm/runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/adversarial/round.py
    role: implementation
  - path: ari-core/ari/manuscript/briefs.py
    role: implementation
  - path: ari-core/ari/pipeline/driver.py
    role: implementation
  - path: ari-core/ari/pipeline/verified_context.py
    role: implementation
  - path: ari-skill-paper/src/server.py
    role: implementation
  - path: ari-core/ari/science_data_contract.py
    role: schema
  - path: ari-core/ari/viz/v1/openapi.json
    role: schema
  - path: docs/reference/rest_api.md
    role: doc
  - path: docs/concepts/gui_architecture.md
    role: doc
last_verified: 2026-08-16
---

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
- Assurance authority stops above the fact layer. The `ScienceData` contract
  carries no attestation, tier, or certification state, and the compiler
  inventories `science_data.json` as an ordinary checkpoint artifact that it
  digests but never rewrites. `assurance.mode` therefore moves a node's
  measurement only between `publishable` and `exploratory`, which are both
  claim-eligible facts; demotion to `contextual_negative` or `excluded` comes
  only from mode-independent signals — execution outcome, artifact provenance,
  staleness, an absent measurement, or a recorded failed/tampered property
  verdict. Raising the assurance mode changes which evidence is admissible for
  a positive claim, not which measurements were recorded.
- Knowledge and Capability records are provenance, not promotion. Neither is an
  input to the evidence-lane decision, which reads only the node's execution
  status, whether it carries a real measurement, its artifact provenance, its
  frontier validity and class, its property verdicts, and its assurance and
  attestation state. A node with no recorded Knowledge coverage is therefore not
  a failed measurement, only a measurement with less recorded context.
- Under `enforce`, an absent Harness attestation makes the current-certification
  requirement `unavailable`, and an attested but uncertified candidate makes it
  `missing`. Both carry the `assurance_certification` resolver, so the gap stays
  repairable while publication stays blocked. Neither is an implicit grant of
  legacy access. The repair request that follows names the capability and
  Harness identities it needs; the manuscript layer records those identities and
  does not itself grant them.
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

What `audit` does not produce is a comparison. An audit-mode artifact diffing
the legacy writer payload against the manuscript inventory — recording items
available in context but absent from the writer payload, items in the writer
payload with no typed context source, cap- or budget-induced observed
omissions, failed, null and off-lineage visibility differences, and assurance
and provenance fields not surfaced to authoring — is reserved design and is not
implemented. `compile_manuscript` in `ari-core/ari/manuscript/coordinator.py`
persists the same kinds of attempt artifact under `audit` as under `enforce` —
snapshot, requirement profile, context, omission manifest, readiness, and, when
briefs are built, the brief bundle and authoring binding — and no comparison
record is among them. The loss an audit run leaves unquantified is therefore
the difference between what the compiler assembled and what the writer was
actually handed.

There is no shared backend interface object. Both backends consume the same
authoring binding and section brief bundle, but through separate call paths:
linear authoring runs the workflow's `authoring` segment, while the archive
runs `PaperArchiveRuntime.run_archive`, which receives the linear pipeline as
an explicit fallback callable. A common `PaperBackend` type — one `generate`
entry point returning backend, mode, input digests, candidate and winner
lineage, draft artifact digests, model usage and cost, and hard-disqualification
reasons in a single record — is reserved design and is not implemented. The
archive's actual result surface is `manuscript_authoring` on
`paper_archive_state.json`: status, the bound manuscript inputs and their
fingerprint, `stale_reasons`, `failure_reason`, `winner_id`, and
`winner_tex_sha256`. Model usage and cost are not part of it; per-epoch
expansion, adversary, anchor-scoring, prompt-candidate, and compile counts are
mirrored separately into `budget_counters` on the same file. Whether a fallback
is admissible under enforce is carried by an `_ari_manuscript_bound` attribute
set on the fallback callable itself, not by an interface.

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
mandatory-disclosure check before best-belief selection. Each candidate is also
re-checked against the frozen bundle itself, not only for content: its draft
record for that node and epoch must carry the bundle's own input fingerprint
together with its binding, profile, context, readiness, and brief-bundle
digests, and under `enforce` that record must also be marked manuscript-bound.
A candidate with no matching draft record for the current epoch fails these
checks the same way. Such a mismatch is a hard reason in its own right, so a
draft written under an earlier bundle cannot win under a later one even when
its text is clean. A hard-failing candidate remains in archive history but has
`_valid_for_frontier=false`; reviewer utility cannot compensate for it. The
final publication evaluator
repeats the evidence-lane and disclosure check against the exact final TeX for
both linear and archive authoring, so candidate screening is never the sole
interlock. Audit mode records the same diagnostics without changing authoring
eligibility and labels the result as legacy authoring. An unchanged resume
reuses bound records, while a changed fingerprint is detected before either
the winner-skip path or a new model call. If archive generation fails under
enforce, only a fallback explicitly marked as consuming the same binding is
allowed.

Manuscript binding contributes no additive utility term to archive selection.
A candidate's manuscript evaluation writes diagnostics and, under `enforce`, the
non-compensable `_valid_for_frontier=false` sentinel; the draft's
`_scientific_score` remains the score the archive's reviewer assigned it, and
the manuscript pass never rewrites it. Graded manuscript axes — required
section-item coverage, claim-evidence link coverage, citation suitability
against recorded references, and disclosure completeness expressed as a score
rather than a pass/fail — are reserved design and are not implemented, and the
brief does not carry what scoring them would need: its evidence lanes bind
evidence IDs rather than references, references reach the writer only as
ordinary `related-work` content items, and no structure in the brief links an
individual claim to the evidence or reference that supports it. What exists is
three-valued and non-compensable: a candidate is `admissible`, carries
`audit_findings`, or, under `enforce`, is `hard_disqualified`.

Archive findings stay inside the archive. They are persisted on the draft record
and on the archive state, and nothing outside the archive reads them: there is
no typed `paper_diagnostic` record, no validator that maps a drafting finding
onto a requirement ID, and no path from an archive finding into a repair
request. A repair plan is derived only from readiness requirement rows whose
status is `missing` or `unavailable` and which name a resolver kind, and each
request is bound to the requirement IDs it answers. Admitting eligible archive
diagnostics into a later repair round through a fixed validator is reserved
design, not current behaviour, and so is the rule that would have to govern it:
any diagnostic-to-repair mapping must bind the offending draft, build, claim,
and evidence digests onto the request it raises, and must be deduplicated
against the readiness and pre-flight signals for the same gap. Neither half is
implemented. `ResearchRepairRequestV1` declares `target_claim_ids` and
`target_node_ids`, but the only producer leaves both empty and nothing except
the contract's own duplicate-identity validator reads them; the digests a draft
record does carry — its TeX hash, its preliminary claim-gate report digest, and
the manuscript input, binding, profile, context, readiness, and brief-bundle
digests it was written under — are screening evidence for that one candidate and
key no request. Prose-quality findings have no route out of the archive at all:
this boundary holds today by construction rather than by a check.

### RQGM paper-candidate pre-flight

Under `ari.mode: ari_rqgm` the shared paper dispatch runs the RQGM
paper-candidate pre-flight *before* it resolves the manuscript axis or compiles
anything. A judge-validated attack in that round applies the bounded utility
penalty, which rewrites the node's `_scientific_score` in place, and the
exploration snapshot reads exactly that key when it orders candidates and fixes
`scientific_winner_id`. A demotion at pre-flight can therefore move the
manuscript's scientific winner, which is the intent: the subject the paper is
about should be the winner after the last governance round, not before it.

The round attacks the paper's own artifacts, so it is gated on at least one of
them already existing. When none does, the pre-flight defers, and the dispatch
re-invokes it once after the paper phase on both the linear and the archive
branch, guarded so it never runs twice in one dispatch. That later round runs
after the pipeline has finished — including, when the manuscript axis is on,
the snapshot, readiness report, briefs and verification of this attempt — and
nothing rebuilds the snapshot afterwards, so its penalty reaches selection on
the next invocation through replay rather than in the run that produced it.

Ordering is the whole division of labour at this seam. Requirement status is
assigned only by the readiness evaluator, which is a pure function of the
requirement profile, the compiled context and the omission manifest; it never
reads the adversarial case log. The escalation round mutates only in-memory
nodes, and the snapshot inventories a fixed list of known checkpoint artifacts
that contains none of the governance logs, so the pre-flight's only channel
into the manuscript compiler is the node score the snapshot reads. A
post-pipeline round can therefore not turn an already-recorded `missing` or
`unavailable` requirement into `satisfied`.

Re-application is prevented by record identity, not by a bundle digest. Each
penalty is a `utility_record` line in the adversarial case log that carries its
base, penalty and final score by value. On reload, a record is replayed onto a
node only while the node's current score still equals that record's stored base
score; a score already at the final value, or since recomputed or re-scored, is
left alone; and a record named by a later record's `supersedes` is never
re-applied, so a frontier repair that exonerated a node is not undone. The
round marker is one-shot per node per round kind, so the paper-candidate round
runs at most once for a given node across every invocation. Every step is
fail-open: a failure logs and never blocks the paper pipeline.

The pre-flight sits on the exploration axis. `manuscript.mode: off` removes the
manuscript compile and the readiness gate but not the pre-flight, and no value
of `manuscript.mode` changes whether the round fires.

## The legacy context assembly and the conditions for deleting it

The legacy path builds writer input by concatenating projected ScienceData,
per-configuration results, candidate claims, source excerpts, figure context
and retrieved references into a single `experiment_summary` string, and keeps
that string finite with four fixed caps rather than with a budget.

| What is capped | Cap | Where |
|---|---|---|
| per-configuration result entries | 10 | `ari-skill-paper/src/server.py`, `write_paper_iterative` |
| candidate claims | 20 | same function; mirrored by `render_grounded_block`'s `max_claims` in `ari-core/ari/pipeline/verified_context.py` |
| available references offered for citation | 12 | same function, reference-context block |
| characters of experiment context in the authoring prompt | 48,000 | same function, at the authoring call |

These are truncations, not budgets. Nothing records what the slice dropped,
nothing dropped stays addressable, and a required fact and an optional one are
discarded by the same rule — position in a list.

Manuscript mode does not loosen these caps; it bypasses them. The first three
blocks are built only when the authoring inputs carry no manuscript binding, so
a bound run never assembles them at all. Under `enforce`, the manuscript
boundary in `ari-core/ari/pipeline/driver.py` replaces the `experiment_summary`
and `paper_context` template variables with the rendered section-brief bundle
before any authoring model call, and the RQGM archive binds the same bundle
into its writer and reviewer prompts. `audit` deliberately leaves writer bytes
and template inputs untouched, and under `off` the boundary is a no-op down to
its imports. The 10 / 20 / 12 / 48k behaviour is therefore exactly what an
`off` or `audit` run still gets.

What replaces the caps under `enforce` is per-section budgeting with
accounting. `manuscript.brief_character_budget` (default 24,000 characters, per
section rather than per run) bounds each section brief; a required disclosure
or required item that cannot fit raises rather than being silently dropped; and
each brief carries `omitted_item_ids`, which the renderer prints, so anything
the budget did drop stays addressable by ID.

Two properties of the shipped implementation are worth stating exactly, because
each is a place the replacement could be over-read:

- The builder in `ari-core/ari/manuscript/briefs.py` currently *splits* rather
  than omits. An over-budget section becomes `<section>`, `<section>.part-002`,
  and so on, and `omitted_item_ids` is left empty on every brief it produces.
  The omission channel exists in the contract and in the renderer; no shipped
  code path fills it yet.
- The 48,000-character truncation is not conditional on manuscript mode. It is
  applied to whatever `experiment_summary` holds at the authoring call,
  including a rendered brief bundle. Because the brief budget is per section, a
  bundle of enough sections can exceed 48,000 characters and be cut by the
  legacy slice.

Deletion of the legacy assembly and its caps is not licensed by manuscript mode
existing. It requires all four of the following to hold:

1. every supported manuscript-enabled backend consumes section briefs;
2. the `off` compatibility policy has an approved replacement, or a deprecation
   release;
3. equivalent legacy fixture coverage exists in the new path;
4. migration and release docs identify the changed output behaviour.

Until all four hold, the legacy and manuscript paths stay explicit rather than
merged. They are not fully disjoint today, though. The figure-context block is
the one legacy block that is *not* gated on the manuscript binding, and both
backends still hand the writer a figures manifest, so under `enforce` the
writer input is the rendered bundle with those figure lines concatenated onto
it. What a binding actually replaces is the three capped blocks and the two
template variables.

These are conditions on a possible future deletion, not a schedule and not a
commitment that the deletion happens. What is observable in the code today is
only that the conditions still gate something live — the legacy assembly is
present and reachable, and it is what every `off` and `audit` run uses — and
that both shipped authoring backends already receive briefs under `enforce`.
Whether that discharges the first condition is a release decision about which
backends are supported, not something the code answers.

## The automatic repair round

Automatic research repair exists only in `ari run` and `ari resume`, and only
when `manuscript.mode` is `enforce` and `manuscript.repair.policy` is `auto`.
Those two entries are the only ones that build research executors and hand them
to the paper dispatch, so `ari paper` can report a repair plan but cannot start
an experiment. Repair creates at most the admitted nodes, uses the normal
BFTS/RQGM execution loop, and runs normal RQGM/KCA hooks.

Under that posture the paper phase runs a bounded outer loop between the
evidence segment and the first authoring call. One round is:

```text
evidence segment
        │
        ▼
compile ── context / omissions / readiness
        │
        ├─ authoring-ready ────────► leave the loop and author
        ├─ no admitted request ────► stop, blocked
        ▼
admit the ordered plan → execute each admitted request once
        │
        ▼
commit the round record → rebuild evidence → recompile as the next round
```

Rounds are numbered from zero and must stay contiguous. The round budget caps
how many rounds the checkpoint commits in total, counted from the persisted
round records rather than per invocation or per attempt. Those records live in
one `.ari-manuscript/auto-rounds/` directory with no attempt component, and the
guard compares every record in it against the maximum; since an attempt ID is
derived from the snapshot and profile digests, and each round rebuilds evidence
and so moves the snapshot, successive rounds of one loop can belong to different
attempts while still drawing down the same counter.

The loop never authors ahead of readiness. Both the linear and the archive
backend run the evidence segment, compile, and enter the loop before any
authoring model call. If the loop returns unready, the phase raises an
authoring block instead of writing a draft, and on the archive branch it raises
before the state moves to `authoring`. Audit mode never enters the loop.

Requests are grouped by resolver kind and ordered by a fixed resolver priority —
derived rebuilds and retrieval before new experiments, human decisions last — so
the same readiness always produces the same plan. Execution asserts nothing
scientific. The coordinator performs no measurement, and no executor result
closes a requirement: a requirement closes only because the rebuilt evidence and
the recompiled readiness say so.

Each request commits an immutable transaction as soon as its resolver returns,
and the round record commits after the whole plan has run, before the evidence
rebuild. An interruption therefore replays rather than repeats: an
already-recorded request is reused from its transaction at zero further budget
cost instead of being invoked again, and an already-recorded round skips
straight to the rebuild and the recompile.

Automation may spend budget; it never widens authority. Every admitted request
is re-checked immediately before its resolver runs, against the current source
context digest and against the authority digest that was captured when the plan
was admitted. A stale context or a changed authority fails the request instead
of executing it under the old envelope. The authority snapshot it is compared to
is a list of artifact identities and mode names carrying an explicit
no-credential marker, so re-validating it can only confirm that the envelope is
unchanged; it is never itself a grant.

An admitted experiment request materialises exactly one node. That node's
identity is derived from the request digest, and the request ID, requirement
IDs, source context digest, and allowed changes are fields on the node itself.
It is written to the checkpoint before the research loop is entered, so an
interrupted round resumes onto the same lineage-bound node rather than opening a
second one for the same request. When RQGM is active the node goes through the
same two hooks an ordinary expansion does, called with the same arguments: the
producer stamp, which writes the epoch's component, prompt hash, and epoch ID
onto the node when the current epoch carries them, and the expansion-proposal
record for the parent → repair-node pair. Repair therefore enters the lineage
through the normal door rather than beside it.

The node is then executed by the ordinary research loop, with the run's own node
limit held at the current tree size for the duration. The loop expands only while
the tree is smaller than that limit, so the repair node runs to completion but
cannot then expand a frontier of its own. The run's original limit is restored
afterwards, including when the loop raises. This is what keeps a repair round
additive: it consumes the admitted budget and leaves behind one bound node, not a
new exploration.

Stopping is not the same as blocking. Exhausting the round budget or the
cumulative budget, or completing a round that changed neither the context digest
nor any requirement status, leaves the attempt in `repair_pending`. An empty
plan, an absent resolver, or a `human_required` result records
`blocked_unavailable` instead. Either transition is written only when it is
legal from the attempt's current state, so a repeated stop does not append a
second identical hop.

The loop is entered at most once per invocation, at that one point before
authoring. A diagnostic that first becomes visible during authoring, during
verification, or at the publication decision does not re-enter it: under
`enforce` the publication evaluator records `finalized` or
`publication_blocked`, the pipeline returns that decision, and nothing calls the
loop again. The loop's own admission step promotes only `blocked_unavailable`
into `repair_pending`, never `publication_blocked`. Leaving
`publication_blocked` for a further repair is therefore an operator action — the
explicit `ari manuscript repair` is the only code path that emits that
transition, and it executes the selected admitted requests and recompiles.
Re-running `ari run` or `ari resume` instead binds the current source bytes
again and re-enters the automatic loop only if that fresh compile is once more
not authoring-ready. A same-invocation return from a
post-authoring diagnostic to a new numbered round, with automatic invalidation
of the draft, is reserved design and is not implemented.

## Read surfaces

Manuscript Complete has no GUI and no REST surface. The committed
`ari-core/ari/viz/v1/openapi.json` declares no manuscript endpoint, and neither
the [REST reference](../reference/rest_api.md) nor the
[GUI architecture](gui_architecture.md) describes one.

What an operator reads is the `ari manuscript` command group and the attempt
artifacts under `.ari-manuscript/`. Every subcommand prints JSON, and the four
that decide something exit `2` when the answer is no: `status --fail-if-blocked`
on a `repair_required` or `blocked` authoring verdict or a `blocked` publication
verdict, `repair` when the recompile that follows its executed requests leaves
any admitted request's requirements unclosed, `explain-publication` on any
decision other than `publishable`, and `lock-publication` when the lock is
refused — a non-publishable decision, a decision that no longer names the
current build, an unfinalized attempt, changed inputs, stale reproduction
evidence, or no single final PDF. That is the
property which makes the missing viewer harmless: no publication-safety
guarantee may depend on one existing, so an unavailable dashboard can never be
the reason an unsafe build was published.

A read model is reserved design and is not implemented. If one is added it must
read the same `ari.public.manuscript` contracts, show only what those contracts
already carry — the requirement matrix, evidence lanes, omissions, repair
budgets, attempt lineage, and the independent publication gates — and never
recompute readiness or derive a gate verdict of its own. A second implementation
of the readiness rules would be a second source of truth.

See [contracts](../reference/manuscript_complete_contracts.md), the
[profile guide](../reference/manuscript_complete_profile.md), and the
[operator runbook](../guides/manuscript_complete_operations.md).
