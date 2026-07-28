# ARI-RQGM Paper-Archive Task Plan Index

## Purpose

This directory contains temporary task-level implementation plans for **ARI-RQGM paper-archive
co-evolution** — the opt-in third execution path that brings the RQGM co-evolution loop to the
paper-writing phase, paralleling how `simple_bfts` and `ari_rqgm` parallel each other for the
exploration phase. Each task plan must define completion criteria, deletion criteria, and a
delete-after checklist. Completed plans should be deleted after their essential design decisions
are moved to permanent docs or implementation. This index is NOT a master plan and contains no
detailed design; it manages only the table of contents, progress, dependencies, and deletion
status of the task plans. Auxiliary plans may be added only if this index records their
dependencies and deletion requirements. This set sits alongside the exploration-phase set at
[../ari_rqgm/INDEX.md](../ari_rqgm/INDEX.md) and inherits its investigation and invariants. It now
also depends on two NEW parent tasks that close method-wide seams this set must NOT fix locally:
[../ari_rqgm/14_governed_utility_evolution.md](../ari_rqgm/14_governed_utility_evolution.md) — the
per-epoch rewrite of the utility function itself (composite / axis_weights / frontier_score), and
[../ari_rqgm/15_validated_attack_target_binding.md](../ari_rqgm/15_validated_attack_target_binding.md)
— binding a `ValidatedAttackRecord` to the component it implicates so the impeachment chain can
fire. Both are inherited topology-agnostically; the paper phase adds no local copy of either.

## Execution Modes

Two orthogonal axes select the runtime. All four combinations are valid (the 2×2 matrix); the
paper axis is resolved independently of the exploration axis.

Exploration axis (`ari.mode`, exploration phase — the parent set):

- `simple_bfts` — preserves current ARI exploration behavior unchanged; the default mode.
- `ari_rqgm` — the opt-in governance/co-evolution mode enabled via config.

Paper axis (`paper.mode`, paper phase — this set):

- `linear` — preserves the current paper pipeline byte-for-byte; the default mode.
- `rqgm_archive` — the opt-in paper-archive co-evolution mode. Effective activation requires
  `paper.mode == rqgm_archive` **and** the redundant interlock `rqgm.paper.enabled == true`;
  disagreement fails safe to `linear` with a warning. Env overrides: `ARI_PAPER_MODE`,
  `ARI_RQGM_PAPER_ENABLED`.

## Active task plans

| ID | Plan | Status | Depends on | Deletion status |
|---|---|---|---|---|
| 00 | 00_paper_pipeline_investigation | planned | none | not deletable |
| 01 | 01_paper_execution_mode | implemented | 00 | not deletable |
| 02 | 02_paper_draft_archive_search | implemented | 00, 01 | not deletable |
| 03 | 03_writer_reviewer_governed_roles | implemented¹ | 00, 02, ../ari_rqgm/04, ../ari_rqgm/07 | not deletable |
| 04 | 04_anchor_utility_and_epoch_winners | implemented¹ | 00, 03, ../ari_rqgm/10, ../ari_rqgm/13, ../ari_rqgm/14 | not deletable |
| 05 | 05_adversarial_self_preference | implemented¹ | 00, 03, 04, ../ari_rqgm/06, ../ari_rqgm/15 | not deletable |
| 06 | 06_cost_control_and_budget | implemented | 00, 01, 02, 03, 05, ../ari_rqgm/12 | not deletable |
| 07 | 07_claim_gate_handoff_and_evaluation | implemented | 00, 01, 02, 03, 04, 05, 06, ../ari_rqgm/13, ../ari_rqgm/15 | not deletable |

Status legend: `planned` = design written and cross-checked, no code or tests landed yet. Plans
stay `not deletable` until their deletion criteria are met (merge to main, CI green, key design
decisions migrated to permanent docs). Because 07 depends on all of 00–06, the whole-set deletion
posture it carries (07 §12) gates the set: no plan is deletable until the set merges, `linear` is
confirmed byte-identical, and the four 2×2 exploration×paper cells are validated.

¹ **`implemented` with a dated residual (2026-07-17; extended 2026-07-18).** The plan set claimed
candidate prompts run the six-stage `CandidateValidationPipeline` (03 §5.9 step 2; 05 §1 "bright
spot" / §5.5 "already implemented"; 04 §4 anchor stage). That class is instantiated NOWHERE in
production, for any role. Rather than the OBJECT, `_paper_candidate_evaluator` calls the pipeline's
pure-function stage checks DIRECTLY, in the plan's monotonic order, over every pending paper
candidate. As of **2026-07-18** the deterministic stages are all wired for paper candidates:
`static_validation` (log-reconstructed spec) → `constitutional_validation` (metadata +
`role_instruction` bytes) run ALWAYS; `schema_dry_run` is wired behind the `schema_dry_run_fn` LLM
reply seam (RUNS when injected, documented SKIP — never a fabricated pass — when not, which is
production); the §5.4 dual-objective boards are computed by `_candidate_replay_board` +
`score_reviewer_on_anchor`. So "execution-verified" now covers the two deterministic DROP stages
(static + constitutional), the LLM-gated schema_dry_run, and the dual boards.

**Remaining conformance residuals (2026-07-17, verified open on the tree; #18/H3 updated 2026-07-18):**
- **#18/H3 — `CandidateValidationPipeline` never instantiated for ANY role.** For paper candidates
  the stage checks are now called DIRECTLY (`static_validation` + `constitutional_validation` always;
  `schema_dry_run` LLM-gated — 03 §5.9 step 2, 2026-07-18); the only remaining paper residual is that
  `schema_dry_run` has no production LLM reply source (honest SKIP). Still dead code / unwired for
  exploration roles. Owner: a parent task against `../ari_rqgm/07` (03 §5.9 residual).
- **#40 — the over-accepted attack count is a magic `over[:max(2,min(len,4))]`** at
  `paper_runtime.py:1511`, not a config knob (the per-round `ADVERSARY_CALL` gate still bounds total
  spend at `max_adversary_calls_per_epoch`, so cost stays inside §5.6). Owner: 06 §5.5 residual.
- **#25 — `paper_writer`/`paper_reviewer` are in no `frontier_repair` role set** (`INVALIDATE_ROLES`
  / `_ROLE_STALE_REASONS` / `RECOMPUTE_ROLES`, `frontier_repair.py:103-120`), and no record carries
  `role="paper_writer"`, so a retired writer prompt does not invalidate/recompute its drafts. A
  two-line role add without the emitter is inert and risks a `KeyError` in `repair()`'s blanket
  except. Owner: 04 §5.6 residual.
- **Not re-audited this pass:** the remaining P2/P3 work-order items (#2 live_axes, #15, #23/#26/#28,
  #37, the doc-side #4/#5/#6, the test gaps #7/#9/#19/#20, #29/#33/#36/#43-47) were not re-verified
  against the current tree; their status is UNKNOWN, not "closed". They remain owed before merge.

## Deleted task plans

| ID | Former plan | Deleted in | Reason |
|---|---|---|---|
| — | — | — | — |

## Global invariants

Only the most important invariants are summarized here; detailed invariants live in the task
plans (the paper-phase BP-1…BP-12 register in [00_paper_pipeline_investigation.md](00_paper_pipeline_investigation.md)
§5.7). A `rqgm_archive` run is still an `ari_rqgm`-substrate run and additionally honors the
parent set's B-invariants ([../ari_rqgm/INDEX.md](../ari_rqgm/INDEX.md)).

- `paper.mode: linear` (default) is byte-identical to today's paper pipeline; when off, no
  `ari.rqgm` module is imported on the paper path and no new files are written.
- The claim-evidence hard gate is Layer-0: deterministic, RQGM-independent, never evolved, never
  kernel-wrapped; the best archive draft passes through the existing compile + gate tail unchanged.
- The draft archive is a **genuine best-first tree** over draft space (`rqgm.paper.archive.depth`
  default 3, width K), identical in shape to exploration BFTS, which already runs a real
  `max_depth=5` tree under the same `SearchStrategy` Protocol
  (`ari-core/ari/config/__init__.py:1559`): root (the paper task seeded from the exploration
  winner) → K seed drafts (depth 1) → refined/variant child drafts (depth 2, 3, …). A
  `paper_refine` pass IS a child node, not a lineage column; `select_best_to_expand` is a real
  frontier selection over draft nodes by `paper_reviewer` score, and `diversity_bonus` really
  rewards structurally divergent framings. Depth is never traded away to buy governance.
- RQGM governance is topology-agnostic: the kernel, epochs, registry/transition, adversarial +
  replay, selective erasure, and budget are reused unchanged across the topology boundary.
- `ari-skill-paper` is NOT governed cross-process; it is the dumb draft executor. The governed
  writer/reviewer prompts live in ari-core roles (`paper_writer`, `paper_reviewer`).
- Cost is bounded by **budget caps, never by flattening the topology**. `max_expansions` maps to
  BFTS `max_total_nodes`, and `should_prune` (`ari-core/ari/orchestrator/bfts.py:501-503`) tests
  `current_total >= cfg.max_total_nodes` before it ever reaches `node.depth >= cfg.max_depth` — the
  total-node cap already bounds the search at ANY depth, so the archive costs O(`max_expansions`)
  whether depth is 1 or 3, and `depth > 1` is not a cost risk. Best-first frontier selection +
  top-K governance + delta refine + lazy compile + single-entry-point + anchor sampling +
  per-epoch caps + epoch-amortized co-evolution ⇒ linear in a tunable budget, never exponential;
  the degraded on-ramp (`rqgm.paper.prompt_evolution.enabled: false`) is ≈ today's cost.
- Opt-in and independent: exploration `ari.mode` × paper `paper.mode` are orthogonal (all four 2×2
  combinations valid); neither resolver reads the other's flags.
- A paper epoch is **one archive round**, and the boundary FIRES at defaults — co-evolution is
  never nominal. `PaperArchiveRuntime.run_archive` builds the full tree under frozen
  writer/reviewer hashes, then closes the epoch exactly once at round end (the 03 §5.9 boundary
  sequence); the next round rebuilds drafts under the ADOPTED prompts.
  `rqgm.paper.epoch.rounds` default **2** is SIZING ONLY: it reuses the inherited
  `rqgm.epoch.boundary: "node_count"` trigger ticked by the archive's own node count (one schema
  home, 01 §5.1), wired through the existing `ensure_epoch` / `_run_epoch_boundary` path in place
  of the inert restore-only `ensure_epoch(0, run_id="paper")` call
  (`ari-core/ari/rqgm/runtime.py:1615`). `max_expansions` (12) is therefore a PER-EPOCH budget
  (24 across the default 2 rounds), and **E = 2 is the default in every cost model**.
- Within-epoch freeze: the active writer/reviewer prompt hashes and the reviewer utility policy are
  frozen per epoch; co-evolution happens only at epoch boundaries through the RegistryTransitionEngine
  and is validated by the ConstitutionalKernel.
- The score itself is rewritten at epoch boundaries (P1's second half), but that machinery is
  **inherited, not reimplemented here**: per-epoch rewrite of composite / axis_weights /
  frontier_score is owned by parent
  [../ari_rqgm/14_governed_utility_evolution.md](../ari_rqgm/14_governed_utility_evolution.md) and
  fixed once for the whole method, since the exploration phase needs it identically. That fix has since LANDED:
  `capture_utility_policy` (`ari-core/ari/rqgm/state.py:354-382`) now resolves the ADOPTED
  `utility_policy` entry from the registries (cfg fallback only at epoch 0 / `simple_bfts` / a
  pre-14 resume), so `utility_policy_hash` is epoch-varying, and `utility_policy` is a registered
  evolvable role. Before Task 14 the function read only the static resolved cfg, the hash was a
  run-constant, and the role was in neither `EVOLVABLE_ROLES` nor `FIXED_ROLES` — while the consequence
  side is already live (`ari-core/ari/rqgm/frontier_repair.py:97-101` `INVALIDATE_ROLES` retires
  nodes whose score came from a retired `utility_policy`). This set adds **no paper-local utility
  machinery**: 04's `capture_paper_utility_policy` extends the inherited capture, it does not fork
  it.

## Plan deletion procedure

A plan file is deleted only through the following operation:

1. Satisfy the plan's completion criteria.
2. Satisfy the plan's deletion criteria.
3. Move key design decisions to permanent docs or code comments.
4. Update INDEX.md (status, deletion status, Deleted task plans table).
5. Delete the plan file.
6. State the deletion reason in the commit message.

A plan must NOT be deleted when any of these hold: implementation is incomplete; no tests exist;
CI is failing; open questions remain; a downstream task depends only on this plan; design
decisions have not yet been moved to permanent docs; INDEX.md has not been updated; or deleting
the plan would lose specification.

## Current focus

> **Correction (2026-07-17; extended 2026-07-18).** The "execution-verified" claims below do NOT
> cover the `CandidateValidationPipeline` OBJECT — that class never runs in production (for any role).
> Instead `_paper_candidate_evaluator` calls its pure-function stage checks DIRECTLY over every
> pending paper candidate. As of **2026-07-18** the deterministic stages are all wired for paper
> candidates: `static_validation` (log-reconstructed spec) and `constitutional_validation` (metadata +
> `role_instruction` bytes) run ALWAYS and DROP a failing candidate before scoring; `schema_dry_run`
> is wired behind the `schema_dry_run_fn` LLM reply seam (RUNS when injected, documented SKIP — never
> a fabricated pass — when not, which is production); the §5.4 dual boards are computed by
> `_candidate_replay_board`/`score_reviewer_on_anchor`. The only remaining paper residual is that
> `schema_dry_run` has no production LLM reply source (03 §5.9). The 06 §9 required tests (cost
> acceptance, closed-form/linearity/doubling, resume double-count) were absent and are now landed.
> See the ¹ footnote above.

**Status (2026-07-16): IMPLEMENTED + execution-verified.** Tasks 01–07 are `implemented` (00 is the
investigation); the two upstream parent tasks 14 and 15 are `implemented` too. Full suite 3802
passed; permanent docs + report (en/ja/zh) + CHANGELOG updated. Each wave was proven by EXECUTION
(not a green suite alone): the `utility_policy_hash` changes across real boundaries; the
`paper_reviewer` prompt_hash co-evolves via a REAL adversary→judge round (anchor-removed ⇒ no attack,
no adoption); the best draft materializes to `{ckpt}/full_paper.tex` and the existing claim gate runs
on it. All uncommitted on branch `RQGM`.

**IMPLEMENTED + execution-verified — writer-prompt co-evolution via the claim-evidence anchor
([04](04_anchor_utility_and_epoch_winners.md) §5.1, revised 2026-07-16).** BOTH paper prompts now
co-evolve. ARI writes about REAL experiments, and the Layer-0 claim-evidence gate scores a draft's
faithfulness deterministically, so the writer IS anchored (the RQGM-paper *coding*-domain shape: a
deterministic verifier + a co-evolving reviewer). `WRITER_ANCHOR_DESCRIPTOR` replaces the interim
`writer_anchor: None`; `PaperAnchorPool.record_writer_faithfulness` lands the gate score on the
AnchorBoard (the seam that was dead — the score was computed and discarded, so every writer motion
was dismissed for want of a board score); an over-accepted AND unfaithful draft binds
`paper_writer_v1` in a REAL round; the role opens and the waiting shadow successor adopts via the
existing T6 (no new edge). Observed: the active writer `prompt_hash` moves
`f38a15f0f140 → b2c36f9a8232` over 8 rounds; the causal control (faithful drafts) yields zero writer
attacks and a constant hash while the reviewer is still impeached. **Honest nuances:** the writer
adopts only on a REGRESSION (a better challenger alone never displaces a faithful incumbent); its
DRAFT winners stay epoch-local; and its sanction rides the `paper_self_preference` round, so it needs
an over-accepted anchor case to fire (a dedicated writer-adversary type is a separate decision).

The feature is **opt-in** (`paper.mode: rqgm_archive` plus the `rqgm.paper.enabled` interlock) and, when off,
**preserves the linear paper pipeline byte-for-byte** — the default paper run imports no `ari.rqgm`
module on the paper path and writes no new files. The set adds one paper mode enum + runtime, one
best-first archive-tree strategy + draft executor, two governed evolvable roles (`paper_writer`,
`paper_reviewer`), one new adversary type (`paper_self_preference`), an accept/reject anchor corpus,
and two checkpoint files (`paper_archive_state.json`, `paper_draft_archive.jsonl`) — everything else
is the existing exploration RQGM substrate reused across the topology boundary. Two of this set's
premises are now owned upstream and must land with it: the boundary rewrite of the utility function
([../ari_rqgm/14_governed_utility_evolution.md](../ari_rqgm/14_governed_utility_evolution.md), which
04 rides) and the validated-attack → component binding that makes the impeachment chain reachable
([../ari_rqgm/15_validated_attack_target_binding.md](../ari_rqgm/15_validated_attack_target_binding.md),
which 05 and 07's PI3 ride); both are method-wide seams that the exploration phase needs identically,
so neither is reimplemented here — and both parent tasks are now `implemented`. Done: implementation
+ tests (suite 3785 passed), `paper.mode: linear` byte-identity and the four 2×2 exploration×paper
cells confirmed, and the key design decisions migrated into the permanent docs (execution-mode guide,
paper-pipeline guide, evaluation guide, schema reference) + report (en/ja/zh) + CHANGELOG. Remaining
before any plan becomes deletable: merge to main with remote CI green, and land the specified
writer-anchor enhancement (04 §5.1) if "both roles co-evolve" is to hold in fact rather than as a
role-driven mechanism awaiting its anchor.
