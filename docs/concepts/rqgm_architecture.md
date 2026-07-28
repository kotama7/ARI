---
sources:
  - path: ari-core/ari/rqgm
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/configs/defaults.yaml
    role: config
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/rqgm/events.py
    role: implementation
  - path: ari-core/ari/rqgm/transition_rules.py
    role: implementation
  - path: ari-core/ari/rqgm/utility_evolution.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_mode.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_archive.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_anchor.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_self_preference.py
    role: implementation
  - path: ari-core/ari/schemas
    role: schema
  - path: ari-core/ari/prompts/rqgm
    role: prompt
  - path: ari-core/ari/prompts/governance
    role: prompt
last_verified: 2026-07-16
---

# Constitutional ARI-RQGM Architecture

Constitutional ARI-RQGM is ARI's opt-in `ari_rqgm` execution mode: an
epoch-based governance and co-evolution layer wrapped around the unchanged
BFTS loop. `simple_bfts` remains the default; with no `ari:`/`rqgm:` config
blocks, no `ari.rqgm` module is even imported and checkpoints stay
byte-identical to pre-RQGM ARI. Activation, the mode interlock, and the
mode-switch policy live in [Execution Modes](../guides/execution_modes.md);
this page is the architecture: why the mode exists, what its layers are, how
an epoch runs, and which invariants hold.

> **For the runtime walkthrough see
> [RQGM Runtime Walkthrough](rqgm_runtime_walkthrough.md)** — one real
> `ari_rqgm` run traced step by step (boot → founding registration →
> per-node hooks → boundary → what lands on disk), with event-log excerpts
> and an observability cheat-sheet.

---

## Motivation

ARI's institutional components — the LLM roles that propose research
directions, review nodes, and judge quality — are themselves prompt-defined
artifacts. Letting them evolve unlocks improvement, but unconstrained
self-modification is exactly what the Gödel-machine literature warns about:
a component that can rewrite its own evaluator will eventually reward
itself. The Red Queen Gödel Machine line of work
([arXiv:2606.26294](https://arxiv.org/abs/2606.26294)) adds the Red-Queen
dynamic — components improve *because* adversaries co-evolve against them —
but co-evolution alone does not bound the failure modes (score inflation,
metric gaming, evidence fabrication, collusion between roles).

Constitutional ARI-RQGM takes the co-evolutionary loop and places it under a
**fixed constitutional layer that never evolves**. Prompts and components
compete, attack, defend, and get adopted or retired — but every state change
is validated by a deterministic, non-LLM kernel against rule tables frozen
in code. The enforcement stance is "block the institution, not the
research": governance can veto its *own* state changes (adoptions,
retirements, registry writes), never a node's execution.

---

## The four pillars

Constitutional ARI-RQGM rests on four defining commitments. Every
mechanism on this page serves one of them, and each is honest about how far
the current implementation carries it:

1. **A tree search whose score is itself rewritten at every boundary.**
   BFTS is a best-first *tree*, and the utility policy that ranks its
   frontier is not a run-constant — it is a governed object frozen per epoch
   and rewritten at boundaries through the same lifecycle that evolves
   prompts (see [Governed utility evolution](#governed-utility-evolution)).
   The *consequence* half has always been live: a rewrite retires the old
   policy and `frontier_repair` invalidates every node scored under it. The
   *cause* half — a `policy_mutator` that proposes the successor — is Task 14.
2. **Adversaries attack artifacts *and* evaluations; collusion is
   forbidden.** The seven exploration adversaries attack a node's
   *artifacts*; the eighth, `paper_self_preference`, attacks a *reviewer's
   decisions* (an AI draft the reviewer over-accepted). A score policy is
   never proposed from the frontier's own scores — a policy tuned to flatter
   the nodes it already produced is exactly the self-referential loop the
   determinism/no-collusion principle forbids (`PolicyMutator` sees only the
   boundary's already-abstract evidence, `utility_evolution.py`).
3. **The adversary is itself in the audit network — no absolute ruler.**
   The components that attack, that propose the score, and that audit are all
   themselves registered, sanctionable, evolvable rows: `policy_mutator_v1`
   is a founding meta component whose own template evolves like any other,
   and a governance recommendation against it resolves into an ordinary
   sanction. Nothing sits outside the transition table.
4. **Everything is constitution-bound; impeachment follows the
   constitution.** Every state change is validated by the non-evolving
   kernel against frozen rule tables pinned by `constitution_hash`; the only
   way a healthy behavioral component loses its seat is an
   `ImpeachmentMotion` filed by the Auditor, adjudicated at a boundary. The
   two supersession edges (T20/T21) are the *sole* exceptions to the
   sanction-only replacement model, and each is kernel-guarded to one role
   family.

---

## The three layers

The role and tier vocabularies are closed sets in `ari/rqgm/events.py`
(`EVOLVABLE_ROLES`, `FIXED_ROLES`, `TIERS`); component ids are
`{role}_v{N}`, prompt ids `{role}_prompt_v{N}`.

| Layer | Tier | Roles | Evolves? |
|---|---|---|---|
| **0 — constitutional (fixed)** | `fixed` | `constitutional_kernel`, `fixed_verifier` (the deterministic `results.json` merge / metric recompute path), `audit_log` | **Never.** Registered for provenance only; rule tables live in code (`kernel_rules.py`, `transition_rules.py`, `clean_room_rules.py`, `meta_rules.py`), pinned by a `constitution_hash` that any rule edit must explicitly re-pin in `tests/test_rqgm_kernel.py`. |
| **1 — institutional** | `institutional` | `generator`, `reviewer`, `adversary`, `defender`, `judge`, `router`; the governed evaluation criterion `utility_policy`; and (paper-mode only) `paper_writer`, `paper_reviewer` | Yes — through the prompt-evolution lifecycle, at epoch boundaries only. `utility_policy` is not prompt-defined — its incumbent is a policy *document* — but it is evolvable in exactly the same sense: one incumbent, replaced only through the transition engine at a boundary. |
| **2 — meta** | `meta` | `prompt_mutator`, `clean_room_generator`, `replay_selector`, `failure_summary_compressor`, `policy_mutator` | Yes — the agents that evolve Layer 1 are themselves governed, with strictly narrower authority (see invariants). `policy_mutator` proposes successor utility policies. |

The role and tier vocabularies were closed sets from day one; Task 14 and the
paper phase un-froze `policy_mutator` and `utility_policy` (both were named by
live code but registrable by neither half of `ROLES`) and added
`paper_writer` / `paper_reviewer` as paper-mode-gated founding rows, so an
exploration `ari_rqgm` boot registers byte-identically to before
(`EVOLVABLE_ROLES`, `ari/rqgm/events.py`).

The bundled `constitution.yaml` copied into each `ari_rqgm` checkpoint is a
human-readable statement only — editing it changes nothing; the code tables
are authoritative.

---

## The four facades

`ari.core.build_runtime` constructs a single `RQGMRuntime`
(`ari/rqgm/runtime.py`) only when `ari.mode: ari_rqgm` and
`rqgm.enabled: true` agree, then wraps the BFTS strategy in a
pure-delegation `GovernedSearchStrategy`. The run loop discovers RQGM by one
duck-typed read — `getattr(bfts, "rqgm", None)` — so `simple_bfts` pays a
single failed attribute lookup. Inside the runtime, four facades own the
governance machinery (all constructed lazily, all fail-open):

| Facade | Module | Owns |
|---|---|---|
| `ConstitutionalKernel` | `ari/rqgm/kernel.py` | Layer 0. Twelve closed `validate_*` entry points (record schema, hashes, capability, epoch invariance, transitions, role separation, selective erasure, audit-log integrity, clean-room bundle, contamination, authority non-expansion, context scope) plus the enforcement adapters (`should_block`, fail-open `per_node_warn_check`, pre-flight `CapabilityGatedMCPClient`). Deterministic and non-evolving: zero LLM calls, zero network, zero wall-clock decisions. `rqgm.kernel.enforcement: audit_only` downgrades every context to warn-and-log. |
| `GovernanceOrchestrator` | `ari/rqgm/governance/` | The epoch-boundary audit: `audit_epoch(...) -> GovernanceReport`, a nine-step pipeline (observe → assess reliability → assemble evidence → prosecute → defend → adjudicate → replay-pool update → self-audit → report). Every LLM decision (Auditor / Defender / GovernanceJudge, prompts under `ari/prompts/governance/`) has a total deterministic fallback, so `llm=None` still produces a complete audit. The report is *advisory input* to the transition engine — the orchestrator never mutates registries. |
| `RegistryTransitionEngine` | `ari/rqgm/transition_engine.py` | The **sole** registry status writer. Pure `resolve_transition(...)` against the fixed T1–T21 table, then a five-step boundary protocol: freeze → resolve → kernel-validate → prepare → apply/commit over the epoch transaction. `emergency_quarantine` is the only mid-epoch path. |
| `FrontierRepairEngine` | `ari/rqgm/frontier_repair.py` | After a committed transition with retirements: the pure `trace_dependents` staleness closure and `rebuild_frontier`, emitting `SelectiveErasureEvent` / `FrontierRebuildEvent` records. Failure ladder: kernel-validation failure → conservative re-repair (flagged nodes dropped) → drain-only degradation (`expansion_halted`: the run finishes pending work but expands no further). Never a crash. |

Supporting components hang off the same runtime: the `ProposalRouter` +
generators (`ari/rqgm/proposals/`, with the optional MCP-only
`VirSciAdapter`), the per-node `AdversarialRound` and `AdversarialReplayPool`
(`ari/rqgm/adversarial/`), the prompt-evolution pipeline and
`GovernedPromptLoader` (`ari/rqgm/prompt_evolution.py`, `prompt_loader.py`),
the `CleanRoomCoordinator` (`clean_room.py`), the
`MetaEvolutionCoordinator` (`meta_evolution.py`), and the
`GovernanceBudgetManager` (`budget.py`).

---

## The epoch cycle

Governance is epoch-based. An epoch freezes the institution; the boundary is
the only window where the institution may change. The v1 boundary trigger is
node count (`rqgm.epoch.boundary: node_count`,
`rqgm.epoch.nodes_per_epoch: 10`), checked by the run loop's
`ensure_epoch` tick at loop start and at each outer-loop head — main
thread, no node in flight. The same tick runs once more at end-of-run,
so the boundary still fires when the Nth node is created in the final
loop iteration (a trailing epoch that has not met the trigger stays
open).

```mermaid
flowchart TB
    freeze["1 freeze — epoch_NNN opens<br/>EpochState: active set, prompt hashes,<br/>utility policy frozen (epoch_fingerprint)"]
    search["2 search — BFTS runs unchanged<br/>per node: proposal recording,<br/>attack → defend → judge round,<br/>fail-open kernel warn checks"]
    audit["3 audit_epoch — GovernanceReport<br/>(nine-step pipeline, advisory)"]
    meta["4 meta-evolution step<br/>(candidates only, kernel-gated)"]
    transition["5 resolve_transition → kernel-validate<br/>→ apply/commit (T1–T21, transactional)"]
    repair["6 frontier repair<br/>(only if retirements: selective erasure<br/>+ frontier rebuild)"]
    cleanroom["7 clean-room regeneration<br/>(candidates for retired roles)"]
    next["8 next freeze — epoch_NNN+1 opens"]

    freeze --> search
    search -->|nodes_per_epoch new nodes| audit
    audit --> meta --> transition --> repair --> cleanroom --> next
    next -.-> search
```

1. **Freeze.** `freeze_epoch` (`ari/rqgm/state.py`) pins the active
   component set, prompt hashes, and utility policy into an immutable
   `EpochState` with a deterministic `epoch_fingerprint`. The frozen policy
   is the **adopted** one — `capture_utility_policy(cfg, registries=)` reads
   the active `utility_policy` entry, falling back to the resolved `cfg`
   only at epoch 0 or when no policy has been adopted (byte-identical to the
   pre-Task-14 function). Epoch ids are
   `epoch_000`, `epoch_001`, … On a fresh checkpoint, the **founding
   registration** runs at boot, before `epoch_000` ever opens: one
   transaction registers the frozen founding tables
   (`ari/rqgm/prompt_spec.py` — 29 prompts, 16 components; 28 prompt rows and all
   16 component rows are frozen code constants, and `utility_policy_prompt_v1` is
   derived from the resolved config, plan 14 §5.3) on
   `rqgm_transitions.jsonl`, so the first freeze carries a non-empty
   active set. Write-once: resume replays it, never re-registers.
2. **Search.** BFTS explores exactly as in `simple_bfts`. Per node, three
   best-effort hooks run: expansion directions are captured as
   `ProposalRecord`s, evaluated nodes get an adversarial round (one of the
   seven adversary types attacks the node's *artifacts*; the defender
   responds; the `ArtifactJudge` adjudicates; only judge-validated attacks
   apply a bounded score penalty), and per-node kernel checks warn-and-flag.
3. **Audit.** At the boundary the closing epoch is audited *first*, so the
   `GovernanceReport` is available to the transition engine.
4. **Meta step.** The meta tier (prompt mutator, clean-room generator, …)
   runs sandboxed and may emit outputs — every one enters the lifecycle at
   `status: candidate`, never as an activation.
5. **Transition.** `resolve_transition` is a pure function of (epoch state,
   governance report, candidate evaluations, registries, status history,
   config) — byte-identical on re-run. The kernel validates the resolved
   transition; a blocked transition aborts fail-closed with the incumbent
   active set still serving (governance-suspended carry-over — the run
   never aborts). Commits are transactional: a double-commit of the same
   `transition_id` is a guarded no-op, and interrupted transactions are
   discarded on resume and re-run deterministically.
6. **Frontier repair.** If the committed transition retired components or
   prompts, every record materially dependent on a retired `prompt_hash`
   is logically erased from frontier scoring and the frontier is rebuilt
   (see invariant 7).
7. **Clean room.** Pending clean-room requests execute inside the boundary
   window; admissible outputs enter the lifecycle as candidates for the
   *next* cycle. A retired role's slot is meanwhile served by the baseline
   fallback, so no governed role is ever vacant.
8. **Next freeze.** The new epoch opens with the (possibly changed) active
   set frozen again.

Components move through ten statuses (`candidate`, `validated`, `shadow`,
`probationary_active`, `active`, `warning`, `probation`, `quarantine`,
`retired`, `banned`) along the fixed T1–T21 table in
`ari/rqgm/transition_rules.py`. Only `rqgm.transition.*` numeric thresholds
are configurable; the table topology is a constitutional amendment surface
(code + test change), never config. The last two rows are the
**supersession edges**, each kernel-guarded to one role family and each
firing only *inside* a same-role T6 adoption (there is never a displacement
without an adopted successor to justify it):

* **T20** (`active → retired`, `superseded_by_adopted_successor`) is the
  `utility_policy` edge (Task 14): a validated, shadow-passed successor
  policy that scores at least as well displaces the *healthy* incumbent and
  retires it with the **old** `utility_policy_hash`. This is the only
  `active → retired` edge; for every behavioral role the kernel rejects it
  (retirement must still stage through quarantine).
* **T21** (`active → shadow`, `reinstatable_standby`) is the paper-role edge
  (`paper_writer` / `paper_reviewer`): when a shadow-passed successor prompt
  adopts, the demoted incumbent moves to a reinstatable `shadow` standby so
  exactly one active entry survives per paper role. Unlike T20 it is not a
  retirement — a later boundary can re-climb the standby.

---

## Governed utility evolution

The defining claim is that the search is tree-structured **and that at each
epoch boundary the entire score — the utility function itself — is
rewritten.** The *consequence* half was always live: `frontier_repair` can
destroy every score a retired utility policy produced. Task 14 supplies the
*cause* half — something that proposes a successor policy — and repeals the
one invariant (I-11) that used to forbid the score from changing.

**The utility policy is a governed object.** The policy body
(`composite`, `axis_weights`, `frontier_score`, `depth_penalty_lambda`,
`ucb_c`) is frozen per epoch and rewritten at boundaries.
`capture_utility_policy(cfg, registries=)` (`ari/rqgm/state.py`) reads the
**adopted** policy from the registry, degrading to the resolved `cfg` at
epoch 0, under `simple_bfts`, or on any read/verify failure (always the
incumbent regime, never a raise). Before Task 14 this function read only the
static cfg, so `utility_policy_hash` was a run-constant and the retirement
`frontier_repair` waits for could never fire.

**The proposer.** `PolicyMutator` (`ari/rqgm/utility_evolution.py`) is a
`PromptMutator` analog: it emits `UtilityPolicyCandidate` records **only** and
exposes no registry/store write surface. Its four default mutation kinds
(`axis_reweighting`, `composite_swap`, `frontier_score_swap`,
`exploration_tuning`) are pure arithmetic over the boundary's already-abstract
evidence — no LLM, no clock, no randomness — so the default rewrite is fully
reproducible; only the opt-in `freeform_policy_proposal` consults an LLM (and
returns `None` when none is configured). The candidate is kernel-validated
against the `CK-UTL-001…008` legality rules (allowed `composite` /
`frontier_score` sets, per-axis weight bounds, the weight-sum constraint,
range checks, and a body-hash-matches-id check). It is a founding **meta**
component (`policy_mutator_v1`) whose own template evolves like any other and
which a governance recommendation can sanction — no absolute ruler.

**The rewrite invalidates the past.** A `_utility_policy_hash` sentinel
(`UtilityPolicyStamp`) is stamped onto every node's `metrics`, so a rewrite
can invalidate **every** node scored under the old policy — not just the
attacked-and-penalised subset that carries a `UtilityRecord`. When T20
retires the incumbent with the old hash, `frontier_repair` marks those nodes
`utility_invalidated` and rebuilds the frontier under the new policy's frozen
weights (or drops them as frontier-invalid — erase, don't re-scale).

**I-11 repealed.** The utility policy is now frozen per *epoch* and rewritten
at boundaries, not held constant for the whole run. Within an epoch it is
still immutable (invariant 1 is intact); the repeal is only about the
cross-epoch axis.

**Honest limit — the "at least as well" gate can be vacuous.** At the default
config (`axis_mode: dynamic`, empty static `axis_weights`) there is no fixed
per-axis basis to compare two policies on, so the T3 "scores at least as
well" quality gate has no ordering to evaluate: supersession reduces to
legality plus non-degeneracy, and the criterion rolls *within* the legal
simplex rather than provably improving. This is the honest Red-Queen posture
— with no ground truth there is nothing to be strictly-better *against* — not
a bug. A genuine strictly-better gate needs an anchored per-axis basis, which
is exactly what the paper phase's accept/reject anchor (Task 04, below)
supplies for the `paper_reviewer` criterion.

---

## The paper-archive layer

The paper phase is the four-pillar method applied to *paper writing*. It is
gated by its **own** execution axis, `paper.mode: linear | rqgm_archive`,
with a redundant `rqgm.paper.enabled` interlock (`ari/rqgm/paper_mode.py`,
`PaperMode`, `resolve_paper_mode`). This axis is **orthogonal** to
`ari.mode` — all four combinations are valid — and `linear` (the default) is
byte-identical to today's paper pipeline: no `ari.rqgm` module is imported on
the paper path unless `rqgm_archive` is effective.

**A real tree over draft space.** `PaperArchiveRuntime.run_archive`
(`ari/rqgm/paper_runtime.py`) runs a genuine shallow best-first tree over
*draft* space via `PaperArchiveStrategy` (`ari/rqgm/paper_archive.py`): one
`paper_root`, up to `archive.width` (K, default 4) seed drafts at depth 1,
each expandable into up to `archive.refine_rounds` refine children down to
`archive.depth` (default 3). It reuses BFTS's prune/count logic and a real
`select_best_to_expand` frontier selection with a real `diversity_bonus`;
`paper_refine` passes are **child nodes** (tree depth), not in-place edits.
`PaperDraftExecutor` wraps `ari-skill-paper` as the dumb "hands" — a seed via
`write_paper_iterative`, refine children via `paper_refine` — and the skill
imports no `ari.rqgm` and is **never governed cross-process**.

**Governed roles and the eighth adversary.** `paper_writer` and
`paper_reviewer` are evolvable institutional roles registered only under the
effective `rqgm_archive` mode (so exploration boots stay byte-identical); the
governed ari-core prompts *drive* the skill. A new eighth adversary type,
`paper_self_preference`, attacks the reviewer's **over-acceptance** — an AI
draft the incumbent reviewer scored high that the anchor would reject
(pillar 2: it attacks the *evaluation*, not an artifact) — and, when the claim
gate finds that same draft unfaithful, the **writer** that produced it as
well. On a paper-role adoption, T21 moves the demoted incumbent to shadow
standby.

**The two anchors.** The *reviewer* is anchored to an APReS-equivalent
accept/reject corpus (`ari/rqgm/paper_anchor.py`,
`paper_anchor_corpus.jsonl`): it earns trust by *agreeing* with a held-out,
human-labelled ground truth. Every case declares a `label_source`, and a
`max_bootstrap_label_fraction` cap is machine-enforced over the corpus and
the held-out subset — a breach **refuses the corpus** (degrades to `None`,
never raises). The anchor defaults to `enabled: false` — the degraded
on-ramp; full co-evolution needs `anchor.enabled: true` **and** a curated
corpus.

The *writer* is anchored too — to a ground truth the RQGM paper's writer
never had. ARI writes about experiments that were actually **run**, so the
Layer-0 claim-evidence hard gate scores a draft's faithfulness
**deterministically**: `writer_faithfulness_score` folds the gate's
`execution_grounded_claim_rate`, `numeric_claim_reproducible_rate` and
`numeric_coverage_rate` into a score ∈ [0,1] (no LLM, no wall clock), and
`WRITER_ANCHOR_DESCRIPTOR` — the metric id `claim_evidence_faithfulness_v1`,
its Layer-0 source, its three components, its threshold — is frozen into
`paper_utility_policy`, so the paper epoch fingerprint records *what* the
writer is anchored to. This makes ARI's paper writer the shape of the RQGM
paper's **coding** domain (a deterministic verifier *plus* a co-evolving
reviewer), not its anchor-less paper-writing domain. The gate itself stays
Layer 0: RQGM only **reads** its findings (`run_hard_gate(write=False)`,
never persisted, never wrapped, never evolved).

**The impeachment chain (Task 15).** The adversary's pre-signal (which
over-accepted drafts to attack) drives a *genuine*
adversary → Defender → ArtifactJudge round. The resulting
`ValidatedAttackRecord` now carries an optional `target_component_id`,
resolved at construction from the implicated role to the epoch-frozen
`paper_reviewer_v1` / `paper_writer_v1` (`ari/rqgm/adversarial/round.py`).
This closes the
`validated_attack → validated_attack_involvement → classify_target →`
impeachment chain that was dead upstream for every adversary. *Honest limit:*
this only fires in production for `paper_self_preference`, whose targets are
registered founding components. The seven exploration adversaries attack
artifacts authored by the `generator` role, which has **no** registered
component, so their chain stays inert **by design** (registering a generator
component is a separate decision).

**Two culpable components, one round.** An over-accepted draft that the claim
gate *also* finds unfaithful has **two** culpable components: the reviewer
that accepted it and the writer that produced it. So
`_AFFECTED_ROLES_BY_TYPE["paper_self_preference"]` names both roles and the
round emits **one validated attack per resolvable role**
(`round.py:_resolve_bindings`), each naming the single role it targets. The
writer binding is gated per node on that draft's Layer-0 faithfulness: an
over-accepted but **faithful** draft binds the reviewer only. `paper_writer`
resolves to `""` off the paper phase, so exploration records stay
byte-identical.

**The best draft flows to the untouched gate.** The archive's best draft is
copied **once** to `{ckpt}/full_paper.tex` by the pure, LLM-free
`materialize_winner`, and the **existing** compile + claim-evidence hard gate
(Layer 0, untouched, never kernel-wrapped) runs on it under the same contract
as a linear run — `write_paper`'s `skip_if_exists` picks it up. Cost is
bounded: `node_budget = min(width·(1+refine_rounds), max_expansions)` becomes
the BFTS `max_total_nodes` at **any** depth (a deeper tree redistributes the
same M nodes, never multiplies them), and the whole phase inherits the
Task-12 governance budget verbatim.

**Honest limits (paper phase).**

* **Both prompts co-evolve — but the writer only on a regression.** The
  `paper_writer` *prompt* co-evolves through the ordinary governed path
  (sanction → role opening → the existing T6; **no** new transition edge), and
  an execution proof observes the active writer `prompt_hash` change across
  the adoption. What it does **not** do is adopt merely because a challenger
  looks better: a writer successor climbs to `shadow` and **waits there**
  until the incumbent is sanctioned for *regressing* on claim-gate
  faithfulness. That is the conservative behavioural-role model, and it is
  causal, not incidental — with faithful drafts the same driver produces zero
  writer attacks, zero writer motions and a constant writer hash, while the
  reviewer is still attacked and impeached. Separately, the writer's *draft*
  winners remain **epoch-local** (ranked by the in-epoch-frozen reviewer, so
  drafts scored by different reviewer versions are never compared).
* **A writer sanction rides the reviewer's round.** The writer-targeted attack
  is emitted by the `paper_self_preference` round, which fires only on an
  **over-accepted** anchor case. A writer whose drafts are unfaithful while
  the reviewer over-accepts nothing is therefore not sanctioned today; a
  dedicated writer-adversary type is a separate decision.
* **Default rounds do not complete an adoption.** At the default
  `rqgm.paper.epoch.rounds: 2` the boundary and the impeachment motion *fire*,
  but the `validated → shadow → probationary_active` climb (~5 boundaries)
  does not complete an adoption; a full adoption needs more rounds (the
  execution proofs drive 8).
* **Anchor off ⇒ best-of-N, for *both* roles.** With the anchor at its default
  `false`, the `rqgm_archive` mode is reviewed best-of-N drafts with no
  co-evolution until the user supplies a corpus;
  `rqgm.paper.prompt_evolution.enabled: false` is the same posture at roughly
  today's cost. This gates the **writer** too: the writer's faithfulness case
  is landed on the anchor pool, so with no pool there is no writer board score
  and no writer sanction — even though the writer's own anchor (the claim
  gate) needs no curated data of its own.
* **The in-phase penalty is synthetic.** The self-preference round currently
  demotes a *synthetic* accountability node, not a real over-accepted archive
  draft (that in-phase demotion is deferred). The channel that actually fires
  is the reviewer's accountability / co-evolution one, through the genuine
  validated-attack record.

---

## Key invariants

1. **Epoch-frozen active set.** The active components (`active`,
   `probationary_active`), prompt hashes, and utility policy cannot change
   mid-epoch. `validate_epoch_invariance` re-derives this from the event
   log. (The utility policy may change *at boundaries* — the repeal of the
   former I-11 "constant score" invariant, [above](#governed-utility-evolution)
   — but never within an epoch.)
2. **Boundary-only transitions, one exception.** Every status change
   commits inside the epoch-boundary transaction. The sole mid-epoch edge
   is `emergency_quarantine` (rule T16: `probationary_active` / `active` /
   `warning` / `probation` → `quarantine`), restricted to kernel-critical
   trigger codes, still logged and kernel-validated.
3. **Single registry writer.** Only the `RegistryTransitionEngine` writes
   component/prompt statuses (global invariant 10) — enforced structurally
   at the storage layer (`ari/rqgm/store.py`, event-replay-only registry
   mutation) and validated by the kernel. There is no `candidate → active`
   edge (no instant activation), no resurrection out of `retired`, and
   `banned` is absorbing.
4. **Raw attacks never touch scores.** An adversary's `RawAttackRecord` has
   no scoring effect; only a judge-validated attack feeds the bounded
   utility penalty (epoch-frozen policy: `rqgm.adversarial.penalty.cap`,
   per-severity weights), and the pre-penalty score is preserved in
   additive metric keys. Judge failure falls back to `invalid` — no
   penalty. Adversaries attack *artifacts*, never components: the attack
   schema has no component field.
5. **Same-role accusations are forbidden.** Same-role outputs are
   observations only. Enforced constructively in the governance record
   builders and authoritatively by the kernel's
   `validate_role_separation`; inadmissible evidence is excluded during
   evidence assembly.
6. **Selective erasure is logical-only.** Nothing is physically deleted.
   Staleness lives in audit-log events, the derived
   `rqgm_erasure_state.json` rollup, and additive `Node.metrics` sentinels
   (`_stale`, `_valid_for_frontier`, `_stale_reason`,
   `_erasure_event_id`) persisted through `tree.json`. Erasure is
   slot-scoped (a retired reviewer stales that reviewer's records and
   their downstream utility consequences, never unrelated work), and
   utilities are recomputed from surviving inputs under the *original*
   epoch's frozen weights — when impossible, the node becomes
   frontier-invalid instead (erase, don't re-scale).
7. **Clean-room contamination rules.** A replacement prompt for a retired
   role is generated from a closed, kernel-screened input bundle
   (committed catalogs + abstract failure summaries) assembled by the
   fixed tier — never from registry prompt text. Retired prompt text is
   unreadable everywhere: registry views stub it out, and the
   `RetiredPromptAccessGuard` denies access at the capability gate. The
   kernel's word-shingle contamination screen
   (`rqgm.clean_room.contamination_screen`) blocks contaminated candidates
   at admission; generation is one-shot (no tool-bearing loop that could
   read retired text).
8. **Meta-tier authority limits.** Meta agents run in a read-only sandbox
   (`MetaSandboxMCPProxy` allowlist + a synthesized submit tool), their
   capability flags are deny-by-default with hard-denied flags const-false
   (`ari/rqgm/meta_rules.py`), the kernel checks authority non-expansion
   as subset arithmetic (invariant 18), and every meta output enters the
   lifecycle at `status: candidate` — the meta tier can propose, never
   appoint.
9. **The fixed layer never evolves.** Kernel, fixed verifier, audit log,
   transition/severity/capability tables, the selective-erasure rule, and
   the claim-evidence hard gate are not evolution targets;
   `constitution_hash` pins the tables.
10. **Block the institution, never the research.** The hard-block set
    vetoes RQGM state changes only (transition commits, registry writes,
    frontier-rebuild commits, candidate promotion); node execution is
    never vetoed. Every run-loop hook is best-effort/fail-open — a
    governance failure degrades governance, not the experiment.
11. **Determinism (P2).** Kernel verdicts, transition resolution, frontier
    repair, budget levels, shadow sampling (hash-based), and the
    evaluation metrics are pure functions — no randomness, no wall-clock
    decisions, byte-identical on replay.

---

## Records on the checkpoint

All RQGM state is checkpoint-scoped and additive: **absence of
`rqgm_state.json` means a pure `simple_bfts` run.** The storage pattern is
append-only JSONL as truth plus derived JSON snapshots for fast reads;
resume replays the event logs (and re-verifies audit-log integrity — a
failure degrades to governance-suspended carry-over, never a refusal to
resume). All of these files are in `PathManager.META_FILES`
(`ari/paths.py`), so none is ever copied into node work dirs.

| File(s) | Written by | Holds |
|---|---|---|
| `rqgm_state.json`, `constitution.yaml` | run start (`ari/rqgm/state.py`) | Mode provenance (`mode_source` ∈ `config\|env\|resume`, switch journal); the copy-once human-readable constitution. |
| `rqgm_transitions.jsonl` → `epoch_state.json`, `rqgm_registry.json` | `RqgmStateStore` / transition engine | Event-log truth for epochs + registries; frozen-epoch and registry snapshots. |
| `rqgm_audit.jsonl` | `ImmutableAuditLog` (all facades) | The hash-chained, append-only audit log: kernel reports, governance records, budget/level lines, erasure + rebuild events. |
| `proposals/` (`proposal_records.jsonl`, `proposal_index.json`) + the `idea.json` projection | `ProposalStore` / `ProposalRouter` | Full proposal records ("store everything"); BFTS only ever sees the capped `ProposalSummaryView`. |
| `rqgm_adversarial_cases.jsonl` → `rqgm/adversarial_replay_pool.json` | adversarial loop | Raw/defense/judgment/validated-attack/utility records; the replay-pool snapshot (updated at boundaries only). |
| `prompt_evolution.jsonl` → `prompt_specs.json`; bodies under `rqgm_prompts/` | prompt-evolution pipeline / `GovernedPromptLoader` | Candidate/validation/shadow records; the PromptSpec rollup; write-once evolved prompt bodies (hash-verified, no in-place mutation). |
| `rqgm_cleanroom.jsonl` | `CleanRoomCoordinator` | Request/screen/fallback event log. |
| `rqgm_erasure_state.json` | `FrontierRepairEngine` | Derived stale/invalid rollup (pure fold over the audit-log erasure/rebuild events; absence == nothing stale). |
| `rqgm_meta_outputs.jsonl` | `MetaEvolutionCoordinator` | Meta-agent outputs (content-derived ids; retry-dedup at read time). |
| `rqgm_governance_cache.jsonl` | `GovernanceCache` | Deterministic replay/result cache keyed by artifact/prompt/role/epoch/context hashes. |
| `rqgm_eval_metrics.json`, `rqgm_injection_provenance.json` | evaluation harness only | Per-run metric report; durable marker for injected (synthetic) runs. |
| `paper_archive_state.json`, `paper_draft_archive.jsonl` | `PaperArchiveRuntime` / paper archive (paper mode only) | Paper-phase mode provenance (write-once); the scored draft population (one record per draft, `is_best_belief` / `compiled` flags). |
| `paper_anchor_corpus.jsonl`, `rqgm/paper_self_preference_stat.json` | anchor loader / self-preference statistic (paper mode only) | The accept/reject ground-truth corpus (each case's `label_source`); the deterministic AI-vs-human self-preference margin the adversary's pre-signal cites. |

The four `paper_*` files exist only under the effective `rqgm_archive` paper
mode — their absence, like `rqgm_state.json`'s, marks a linear paper run.

Exact on-disk formats: [File Formats Reference](../reference/file_formats.md);
JSON Schemas (in `ari-core/ari/schemas/`, e.g. `epoch_state`,
`rqgm_registry`, `rqgm_transition_event`, `governance_report`,
`proposal_record`, `selective_erasure_event`, `frontier_rebuild_event`,
`erasure_state`): [RQGM Schema Reference](../reference/rqgm_schemas.md).

---

## Configuration surface

`ari.mode` + the `rqgm.enabled` interlock activate the mode (both must
agree — see [Execution Modes](../guides/execution_modes.md)). The tunable
surface is deliberately limited to switches, budgets, and numeric
thresholds: `rqgm.epoch`, `rqgm.kernel`,
`rqgm.governance`, `rqgm.replay`, `rqgm.transition`, `rqgm.adversarial`,
`rqgm.shadow`, `rqgm.prompt_evolution`, `rqgm.clean_room`,
`rqgm.frontier_repair`, `rqgm.meta_evolution`, `rqgm.budgets`, `rqgm.eval`,
plus the `proposal_router.*` block (defaults in
`ari-core/ari/configs/defaults.yaml`, typed models in
`ari-core/ari/config/__init__.py`). Rule tables are never config. VirSci is
optional and orthogonal: `proposal_router.generators.virsci.enabled`
defaults to `false` in both modes — see
[VirSci Integration](../guides/virsci_integration.md).

The paper phase is a **second, orthogonal** axis: `paper.mode`
(`linear | rqgm_archive`) + the `rqgm.paper.enabled` interlock, with its own
`rqgm.paper.*` block (`archive` — `width` / `depth` / `refine_rounds` /
`max_expansions`; `epoch.rounds`; `anchor`; `self_preference`;
`prompt_evolution`; `reviewer.agent_as_judge` — `enabled` (default `false`,
env override `ARI_PAPER_AGENT_AS_JUDGE`) / `max_tokens`, the opt-in
`LLMClient`-backed draft scorer that reads the rubric axes no deterministic
reader can and falls back to the deterministic venue rubric on any failure).
All four `ari.mode` × `paper.mode` combinations are valid; both default to
their linear/`simple_bfts` value, so a run opts into each axis independently
— see [The paper-archive layer](#the-paper-archive-layer).

Cost control is built in: the `GovernanceBudgetManager` gates every
governance decision point (`allow | degrade | skip`) against per-epoch
per-role call caps and the `rqgm.budgets` spend caps, and assigns each node
a governance level (L0 fixed … L3 adjudicated). Exhaustion degrades
governance, never node execution; the Layer-0 fixed checks are exempt by
construction.

---

## See also

[RQGM Runtime Walkthrough](rqgm_runtime_walkthrough.md) ·
[Execution Modes](../guides/execution_modes.md) ·
[BFTS algorithm → RQGM wrapping](bfts.md#governed-bfts-under-ari_rqgm-opt-in) ·
[RQGM Evaluation and Ablation](../guides/rqgm_evaluation.md) ·
[RQGM Schema Reference](../reference/rqgm_schemas.md) ·
[VirSci Integration](../guides/virsci_integration.md) ·
[RQGM Migration](../guides/rqgm_migration.md) ·
[File Formats Reference](../reference/file_formats.md) ·
[ARI Architecture](architecture.md)
