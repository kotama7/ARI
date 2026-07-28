# Task 06: Cost Control and Budget (paper-archive)

> **Status**: planned · **Depends on**: 00, 01, 02, 03, 05, ../ari_rqgm/12 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

The paper-archive co-evolution path adds new LLM-consuming actors to the paper phase:
a co-evolving `paper_reviewer` scoring each draft candidate, a `paper_self_preference`
adversary (Task 05, [05_adversarial_self_preference.md](05_adversarial_self_preference.md)),
anchor-agreement utility scoring (Task 04,
[04_anchor_utility_and_epoch_winners.md](04_anchor_utility_and_epoch_winners.md)), and
writer/reviewer prompt co-evolution at epoch boundaries (Task 03,
[03_writer_reviewer_governed_roles.md](03_writer_reviewer_governed_roles.md)). Left
unbounded, this reintroduces exactly the failure mode the parent set's Task 12 exists to
prevent — governance cost growing superlinearly with the draft population — one phase
later. This task designs the containment so that the paper-archive path stays **linear in a
tunable budget, never exponential**, and so that the degraded on-ramp is
**≈ today's linear-pipeline cost**.

The core claim, and why this task is mostly a reuse exercise: the budget machinery is
**topology-agnostic**. `GovernanceBudgetManager`
(`ari-core/ari/rqgm/budget.py`) already gates the paper phase today — the
`run_paper_candidate_escalation` hook
(`ari-core/ari/cli/projects.py:163-175` → `ari-core/ari/rqgm/runtime.py:1573-1635`) drives
the best exploration node through the SAME per-node level ladder, adversary cap, and
`paper_candidate` L3 trigger that exploration nodes use. The archive loop plugs the
`paper_reviewer` / `paper_self_preference` / anchor actors into that same manager. So this
plan **inherits the parent-set Task 12 budget verbatim**
([../ari_rqgm/12_cost_control_and_context_budget.md](../ari_rqgm/12_cost_control_and_context_budget.md))
and adds only the paper-specific *structural* guards that keep the draft tree cheap:

1. **best-first under a hard node cap** — the draft search is a genuine tree, and its cost is
   bounded by the *node budget*, not by its shape: `rqgm.paper.archive.max_expansions` maps to
   BFTS `max_total_nodes`, which `should_prune` enforces **at any depth**
   (`ari-core/ari/orchestrator/bfts.py:501-503` checks `current_total >= cfg.max_total_nodes`
   BEFORE and independently of `node.depth >= cfg.max_depth`). Depth is a shape knob, never a
   cost knob;
2. **delta refine nodes** — refine expansions are bounded LaTeX deltas, not full rewrites;
3. **lazy LaTeX compile** — only threshold-passing drafts compile;
4. **single entry point** — exactly one best exploration result seeds exactly one draft
   space (`select_best_node`), so there is no cross-product with the exploration frontier;
5. **anchor scoring on a held-out sample** — `paper_reviewer` utility is measured on
   `rqgm.paper.anchor.sample_size` labeled papers, not the whole corpus;
6. **epoch-amortized co-evolution** — writer/reviewer prompts evolve only at epoch
   boundaries, at most `rqgm.prompt_evolution.max_total_candidates_per_epoch` (4) candidates.

The plan gives an explicit cost model (§5.6) and shows every term is a config cap.

## 2. Scope

- **Inherit the Task-12 budget verbatim**: reuse `GovernanceBudgetManager`, `BudgetedAction`,
  `BudgetVerdict`, the L0–L3 level ladder, `assign_level`/`level_with_triggers`, deterministic
  shadow sampling, the `check`/`consume`/`gate` decision-point API, and the audit-line
  vocabulary (`budget_consumed` / `budget_degraded` / `governance_level`) with no rewrite.
- Define the **paper budget config schema** under `rqgm.paper.archive` (`width`,
  `refine_rounds`, `max_expansions`, `depth`) and `rqgm.paper.anchor`
  (`corpus_path`, `sample_size`, `enabled`), plus the co-evolution on/off interlock
  `rqgm.paper.prompt_evolution.enabled`.
- Map the paper-phase actors onto **budgeted-action kinds** (which reuse existing kinds,
  which are additive), and fix the **single schema home** for each cap.
- Define the **structural cost guards** (§1 items 1–6) and their enforcement points on the
  paper path (`PaperArchiveRuntime`, `PaperArchiveStrategy`, the draft NodeExecutor).
- Give the **cost model** — expected LLM calls/tokens ≈ *f(K, refine_rounds, epochs, top_k,
  sample_size)* — and prove linearity in the budget.
- Define the **degraded on-ramp** cost (`rqgm.paper.prompt_evolution.enabled: false` =
  best-of-N reviewed drafts, no co-evolution) and its collapse to today's cost at width 1.
- Define **cost attribution** (`cost_tracker` phase/skill/epoch tagging for the paper actors)
  and the resume-safe counter homes (`paper_archive_state.json`).
- Define the **cost regression / budget check test** for the paper path.

## 3. Non-goals

- No implementation (design only; implementation is a deletion-criteria item).
- Does **not** redesign `GovernanceBudgetManager` — it is reused; this plan only adds the
  paper action kinds and their cap wiring, and constructs the manager at the paper entry.
- Does **not** own the co-evolution *mechanics* (Task 03), the anchor *utility function*
  (Task 04), the `paper_self_preference` *adversary* (Task 05), or the archive *search
  substrate* (Task 02, [02_paper_draft_archive_search.md](02_paper_draft_archive_search.md)) —
  only how often each may run and how it is counted.
- Does **not** add cost enforcement to `paper.mode: linear`. The linear pipeline's only
  budget levers (`max_revision_rounds` on `write_paper_iterative` /`paper_refine`,
  the reviewer `--num-reviews-ensemble` / `--num-reflections` knobs at
  `ari-core/ari/cli/projects.py:68-69`) remain the sole limits there.
- Does **not** change `cost_tracker` from passive accounting into a hard killer of in-flight
  LLM calls. Enforcement is decision-point gating (skip/degrade the next action), never
  mid-call interruption — identical posture to `budget.py`.
- Does **not** wrap or budget the Layer-0 claim-evidence gate. The best draft's compile +
  claim-gate handoff (Task 07,
  [07_claim_gate_handoff_and_evaluation.md](07_claim_gate_handoff_and_evaluation.md)) is
  never kernel-wrapped and never budgetable (global invariant: the constitutional floor
  always runs).
- No CLI surface changes (config + env only; avoids contract-snapshot churn per Task 01,
  [01_paper_execution_mode.md](01_paper_execution_mode.md)).

## 4. Existing ARI touchpoints

All paths repo-relative. Verified against branch `RQGM` (ari-core v0.9.1).

| Touchpoint | File / symbol | Why it matters here |
|---|---|---|
| **Budget manager (reused verbatim)** | `ari-core/ari/rqgm/budget.py` — `GovernanceBudgetManager` (line 127), `BudgetedAction` (line 79), `BudgetVerdict` (line 97), `check`/`consume`/`gate` (lines 335/371/403) | The read-side, decision-point (`allow`/`degrade`/`skip`), never-raises manager. Duck-typed config reads (`_get`, line 120) mean it already accepts a paper-runtime `cfg` unchanged. Counters rebuilt from the audit log (`_restore`, line 175) → resume-safe. This plan constructs one on the paper path and adds paper action kinds. |
| **Level ladder + triggers** | `ari-core/ari/rqgm/budget.py` — `LEVEL_FIXED..LEVEL_ADJUDICATED` (lines 72-76), `level_with_triggers` (line 433), `_in_top_k` (line 550) | The `paper_candidate` trigger already forces L3 (lines 465-467) and `full_governance_only_on_top_k` already bounds top-K governance (line 461). The archive's per-draft level assignment reuses this pure function unchanged. Sterile/pruned drafts never exceed L0 (line 454). |
| **Action kinds + caps** | `ari-core/ari/rqgm/budget.py` — `ACTION_KINDS` (line 58), `_cap` (line 230) | The closed v1 kind set and their single-schema-home caps. `ADVERSARY_CALL` → `rqgm.adversarial.max_adversary_calls_per_epoch` (line 235-237); `PROMPT_CANDIDATE` → per-role + `max_total_candidates_per_epoch` (lines 261/350-357). Paper actors map onto these; anchor scoring is the one additive kind (§6.2). |
| **Paper entry / existing hook** | `ari-core/ari/cli/projects.py:148-190` — `paper()`; `_rqgm_paper = getattr(_bfts_paper, "rqgm", None)` (line 163) | The paper phase already discovers the RQGM runtime by duck-typed attribute and drives budget-gated escalation. The `PaperArchiveRuntime` (Task 01) attaches here the same way; the archive loop and its budget manager are constructed at this site, BEFORE the linear `generate_paper_section` call (line 190). |
| **Existing paper-candidate escalation** | `ari-core/ari/rqgm/runtime.py:1573-1635` — `run_paper_candidate_escalation`; `budget_manager` property (lines 420-447) | Proof the paper phase already routes through the SAME `GovernanceBudgetManager` and `run_adversarial_round` with `paper_candidate=True` (line 1628). The `budget_manager` construction pattern (lazy, fail-open to `None`, `epoch_state=lambda: self.current_epoch`, `cost_tracker=cost_tracker.get()`, `proposal_store=…`) is the exact template `PaperArchiveRuntime.budget_manager` copies. |
| **Best-node single entry** | `ari-core/ari/pipeline/verified_context.py:36` — `select_best_node` | The one function that picks the single best exploration node handed to the paper phase (already called at `projects.py:169`). This is the "single entry point → one draft space" guarantee: the archive seeds from ONE node, so there is no exploration×paper cross-product. |
| **Draft executor tools (the hands)** | `ari-skill-paper/src/server.py` — `write_paper_iterative` (line 1091), `paper_refine` (line 2446), `review_compiled_paper` (line 2084), `compile_paper` (line 446) | The seed/refine/compile hands. `write_paper_iterative`'s `max_revision_rounds` (default 2) and `paper_refine`'s bounded 3-pass edit loop are per-expansion internal caps the archive budget rides ON TOP of. `review_compiled_paper` is NOT the scorer (the governed `paper_reviewer` role scores); `compile_paper` is the lazy-compile lever. These run in a SEPARATE subprocess — ungoverned cross-process, budgeted only by `max_expansions`. |
| **Cost accounting (attribution foundation)** | `ari-core/ari/cost_tracker.py` — `CallRecord.epoch` (lines 76-79), `record(..., phase=, skill=, epoch=)` (line 126), `set_default_metadata` (line 249), `bootstrap_skill` (line 345), `_summary` by_phase rollup (lines 171-186) | The additive `epoch` field and phase/skill tagging already exist for the exploration governance. Paper governed actors ride the REUSED actors and inherit their `phase="governance"` tags (there is no `phase="paper_governance"` — see the §5.8 correction); `bootstrap_skill("paper")` carries `skill="paper"` into the `ari-skill-paper` subprocess; per-paper-epoch separation rides `CallRecord.epoch`. `cost_summary.json` rolls up paper spend under the shared `governance` phase. |
| **Config defaults home** | `ari-core/ari/configs/defaults.yaml:32-113` — `rqgm.governance`/`rqgm.adversarial`/`rqgm.shadow`/`rqgm.prompt_evolution` | The REUSED Task-12 knobs live here (`full_governance_only_on_top_k: 3` line 35, `max_attacks_per_node: 3` line 81, `max_adversary_calls_per_epoch: 24` line 82, `max_total_candidates_per_epoch: 4` line 110). The paper path reads the SAME blocks; the new `rqgm.paper.*` block is additive and inert unless the effective paper mode is `rqgm_archive`. |
| **Checkpoint registration** | `ari-core/ari/paths.py` — `META_FILES` (line 404), `_TRACE_FILES` (line 68); `ari-core/ari/orchestrator/node_report/builder.py` — `_INTERNAL_JSON_NAMES` (line 327) | `paper_archive_state.json` and `paper_draft_archive.jsonl` (Task 01/02) must be registered so budget counters and per-draft scores never contaminate node work dirs or `node_report.files_changed`. `rqgm_audit.jsonl` (already registered, line 443) carries the paper actors' `budget_consumed` lines. |

## 5. Proposed design

### 5.1 Inherit the Task-12 budget verbatim

The paper-archive path constructs a `GovernanceBudgetManager` with the SAME arguments the
exploration runtime uses (`ari-core/ari/rqgm/runtime.py:436-443`), differing only in the
`epoch_state`/`proposal_store` sources being the paper runtime's:

```python
# planned: ari-core/ari/rqgm/paper_runtime.py  (PaperArchiveRuntime)
@property
def budget_manager(self):
    """Reuses ari.rqgm.budget.GovernanceBudgetManager unchanged (Task 12).
    Lazy, fail-open to None, never blocks the paper loop."""
    if self._budget_manager is None:
        try:
            from ari import cost_tracker
            from ari.rqgm.budget import GovernanceBudgetManager
            from ari.rqgm.store import ImmutableAuditLog
            self._budget_manager = GovernanceBudgetManager(
                self.cfg,                                   # same duck-typed cfg
                epoch_state=lambda: self.current_paper_epoch,
                cost_tracker=cost_tracker.get(),
                checkpoint_dir=self.checkpoint_dir,
                audit_log=ImmutableAuditLog(self.checkpoint_dir),
                proposal_store=None,                        # no VirSci on the paper path
            )
        except Exception:
            log.warning("paper GovernanceBudgetManager construction failed",
                        exc_info=True)
    return self._budget_manager
```

**Reused unchanged (no code churn):**

- **Level ladder** L0–L3 (`budget.py:72-76`). The paper phase's floor is L0 — the fixed
  claim-evidence gate + deterministic LaTeX compile checks — never budgetable (matches
  invariant "the constitutional floor always runs", `budget.py:427-428`).
- **`level_with_triggers`** (`budget.py:433`). The `paper_candidate` trigger (line 465) and
  `full_governance_only_on_top_k` top-K trigger (line 461) already do the right thing for
  drafts: only the top `rqgm.governance.full_governance_only_on_top_k` (3) drafts by
  `_scientific_score` and any node flagged a paper candidate reach L3.
- **Adversary cap.** `paper_self_preference` (Task 05) is dispatched as `ADVERSARY_CALL`;
  its per-epoch cap is `rqgm.adversarial.max_adversary_calls_per_epoch` (24, `budget.py:236`)
  and its per-node attack cap is `rqgm.adversarial.max_attacks_per_node` (3). No new adversary
  budget key is invented (single schema home).
- **Prompt-evolution caps.** Writer/reviewer co-evolution candidates are `PROMPT_CANDIDATE`
  actions, capped per-role at `rqgm.prompt_evolution.max_candidates_per_role_per_epoch` (1)
  and in total at `rqgm.prompt_evolution.max_total_candidates_per_epoch` (4) — the SAME keys
  and the SAME total-cap check (`budget.py:350-357`) exploration uses.
- **`check`/`consume`/`gate`** decision-point API and the `budget_consumed` /
  `budget_degraded` / `governance_level` audit lines (`budget.py:42-44`), appended to the
  already-registered `rqgm_audit.jsonl`.
- **Resume-safety.** Counters rebuild from the audit log (`_restore`, `budget.py:175-203`);
  no in-memory-only counter that would double budgets on `ari paper` re-invocation.

### 5.2 Paper budget config (authoritative shape)

Added as a typed `rqgm.paper` subsection (Task 01 owns `RQGMPaperConfig`; this plan pins the
budget-bearing fields). Defaults live in the Pydantic model AND mirror
`ari-core/ari/configs/defaults.yaml`, so an absent `rqgm.paper` block is inert:

```yaml
rqgm:
  paper:
    enabled: false               # redundant safety interlock (mirrors rqgm.enabled)
    archive:
      depth: 3                    # draft-tree depth -> BFTS max_depth (shape, not cost)
      width: 4                    # K sibling draft candidates (branch factor)
      refine_rounds: 2            # paper_refine child expansions per draft (= tree depth)
      max_expansions: 12          # HARD PER-EPOCH node cap -> BFTS max_total_nodes
    # epoch:                      # Task 01 owns this schema; rounds: 2 is E in the §5.6 model
    #   rounds: 2                 # paper epochs per run (one archive round each)
    anchor:
      enabled: false              # DEFAULT false (Task 04 owns this field): the degraded
                                  # on-ramp. Full reviewer co-evolution requires BOTH
                                  # anchor.enabled: true AND a curated corpus_path — without a
                                  # corpus, load_anchor_corpus degrades to None anyway. Default
                                  # rqgm_archive is reviewed best-of-N until the user supplies
                                  # ground truth (matches the §5.7 cost on-ramp).
      corpus_path: ""             # accept/reject labeled corpus (Task 04 owns curation)
      sample_size: 8              # held-out labeled papers scored per reviewer candidate
    prompt_evolution:
      enabled: true               # false = degraded on-ramp: best-of-N, NO co-evolution (§5.7)
  # ── REUSED verbatim (single schema home; NOT duplicated under rqgm.paper) ──
  governance:
    full_governance_only_on_top_k: 3     # top-K drafts get L3 (defaults.yaml:35)
  adversarial:
    max_attacks_per_node: 3              # per-draft attack cap (defaults.yaml:81)
    max_adversary_calls_per_epoch: 24    # paper_self_preference cap (defaults.yaml:82)
  prompt_evolution:
    max_total_candidates_per_epoch: 4    # writer+reviewer co-evolution cap (defaults.yaml:110)
```

**Decisions (each resolves an open cost question):**

- **D1 — Two on/off keys, one meaning each.** `rqgm.paper.prompt_evolution.enabled` toggles
  *whether writer/reviewer prompts co-evolve at all* (the on-ramp); when `true`, the *number*
  of candidates is bounded by the shared `rqgm.prompt_evolution.max_total_candidates_per_epoch`
  (4). The paper path never introduces a `rqgm.paper.prompt_evolution.max_*` alias — the count
  cap has exactly one home. Rationale: mirrors the parent-set rule that adversary/score-jump
  knobs have one schema home ([../ari_rqgm/12](../ari_rqgm/12_cost_control_and_context_budget.md) §5.3).
- **D2 — the effective per-epoch node cap is `node_budget = min(width·(1 + refine_rounds),
  max_expansions)`, and it is PER-EPOCH.** The single source of truth is
  `paper_archive.archive_node_budget(knobs)`: `PaperArchiveStrategy` caps on it (`self.node_budget`)
  and `paper_runtime.paper_expansion_budget(cfg)` delegates to it, so the cost model's formula and
  the live strategy cap can never diverge. At the default config the two terms coincide
  (`4·(1+2) = 12 = max_expansions`), so `max_expansions` is the binding cap there; the `min` only
  matters when a user sizes them apart. Every draft executor expansion (one `write_paper_iterative`
  seed or one `paper_refine` child) counts against `node_budget` **within one archive round**. This
  is not merely the paper *analog* of exploration's `BFTSConfig.max_total_nodes` — it MAPS to it, and
  that is precisely why the cap does the whole job: `should_prune` retires a frontier node the
  moment `current_total >= cfg.max_total_nodes` (`ari-core/ari/orchestrator/bfts.py:501-502`),
  a test that is taken **before and independently of** the depth test at `bfts.py:503-504`. A
  deeper tree therefore cannot buy more nodes; it can only spend the same 12 differently.
  `width × (1 + refine_rounds) = 4 × 3 = 12` at defaults, so the cap is exactly the natural
  per-epoch population size (equivalently Task 02 §6.2's `width + width·refine_rounds = 4 + 8
  = 12`, which stays true as a per-epoch identity); at the default `rqgm.paper.epoch.rounds: 2`
  (Task 01) that is **24 expansions total across the run**. Lowering it degrades gracefully
  (seeds land before refines — best-first order, §5.4).
- **D3 — `anchor.sample_size` bounds the utility measurement, not the corpus.** The reviewer's
  anchor agreement (Task 04) is scored on a held-out sample of `sample_size` (8) labeled
  papers, NOT the full `corpus_path`. This is the "anchor scoring on a sample" guard that keeps
  utility measurement O(candidates × sample_size), not O(candidates × |corpus|).

### 5.3 Budgeted-action mapping (reuse first; one additive kind)

| Paper actor | BudgetedAction kind | Cap (single schema home) | New? |
|---|---|---|---|
| `paper_reviewer` scoring a draft | *(no per-epoch cap)* — bounded structurally by `max_expansions` | `rqgm.paper.archive.max_expansions` (12) | reuse |
| `paper_self_preference` adversary | `ADVERSARY_CALL` | `rqgm.adversarial.max_adversary_calls_per_epoch` (24), `max_attacks_per_node` (3) | **reuse verbatim** |
| Writer/reviewer co-evolution candidate | `PROMPT_CANDIDATE` (role=`paper_writer`/`paper_reviewer`) | `max_candidates_per_role_per_epoch` (1), `max_total_candidates_per_epoch` (4) | reuse verbatim |
| Anchor-agreement utility scoring | `PAPER_ANCHOR_SCORING` | `rqgm.paper.anchor.sample_size` (8) per candidate | **additive** |

Decision **D4 — the `paper_reviewer` L1 score has no per-epoch cap by design.** In the
exploration ladder the L1 Reviewer likewise has no explicit `_cap` entry (`budget.py:230-270`
lists no reviewer kind): it is bounded by node count. On the paper path the "node count" is the
draft population, itself hard-capped at `max_expansions`. So one reviewer score per draft is
already bounded — adding a separate per-epoch reviewer cap would be redundant and could starve
scoring below the population size. The reviewer is instead gated by the level ladder: a draft
that is sterile/pruned never reaches L1 (`budget.py:454`).

Decision **D5 — `PAPER_ANCHOR_SCORING` is the only additive action kind.** It is appended to
`ACTION_KINDS` (`budget.py:58`) and given a `_cap` branch reading
`rqgm.paper.anchor.sample_size` (returning 0 when `rqgm.paper.anchor.enabled: false`, mirroring
the `SHADOW_CALL`/`VIRSCI_CALL` disabled-returns-0 pattern at `budget.py:246-248/257-258`). It
is consumed once per anchor paper scored. The writer IS anchored (Task 04 §5.1, revised 2026-07-16),
but to the **deterministic** Layer-0 claim gate — no LLM call, no network, no token spend — so it
still needs no budgeted action kind of its own; `run_hard_gate(write=False)` on a draft costs the
same CPU the gate already costs. (The writer-targeted attack it can trigger is an
`ADVERSARY_CALL` on the EXISTING `paper_self_preference` round, already gated by
`rqgm.adversarial.max_adversary_calls_per_epoch` — not a new budget line either.) This keeps the
budget surface minimal (invariant: "the bright spot — how little is new" carries into cost control
too).

### 5.4 Structural cost guards on the paper path

The **ceiling** is the per-epoch node budget (guard 1) — that is what makes the path bounded, at
any topology. The remaining guards keep the *typical* cost well below that ceiling by making each
node, compile and measurement cheap. Each guard is enforced at a named site:

1. **Best-first under a hard node cap** (`PaperArchiveStrategy`, Task 02). The draft search is
   a genuine best-first tree — root → K seed drafts (depth 1) → refined/variant child drafts
   (depth 2, 3) — and it is cheap because of the **node budget**, not because of its shape.
   `PaperArchiveStrategy` plugs into the SAME `SearchStrategy` protocol as exploration (Task
   02) with `max_total_nodes = archive.max_expansions`, `max_depth = archive.depth`, and
   `branch = archive.width`, so the existing `bfts.py` clamps do the bounding — no new loop.
   The load-bearing clamp is the total-node one: `should_prune` returns `True` as soon as
   `current_total >= cfg.max_total_nodes` (`ari-core/ari/orchestrator/bfts.py:501-502`),
   evaluated **before** the depth cutoff at `bfts.py:503-504` and never conditioned on it.
   Per-epoch draft count is therefore `≤ min(width × (1 + refine_rounds), max_expansions)` —
   **linear in the budget at any depth**. Note that exploration already runs this exact
   substrate at a genuine `max_depth=5` (`ari-core/ari/config/__init__.py:1559`) under the same
   total-node cap, which is the existence proof: a `width^depth` term never materializes,
   because the cap is reached first and expansion simply stops. `depth > 1` buys the archive
   structurally divergent framings at **zero** marginal budget; it does not buy nodes.
2. **Delta refine nodes.** A refine expansion calls `paper_refine`
   (`ari-skill-paper/src/server.py:2446`), which applies bounded suggested-revision deltas
   (its own ≤3-pass edit loop) and PRESERVES `% CLAIM` anchors — it does not re-draft the
   paper. Cost per refine expansion is a bounded edit, not a fresh `write_paper_iterative`.
3. **Lazy LaTeX compile.** `compile_paper` (`ari-skill-paper/src/server.py:446`) runs only for
   drafts that pass the reviewer score threshold (top-K by `_scientific_score`). Non-threshold
   drafts are scored on their `.tex`/section text and never pay compile CPU. Enforced in the
   draft NodeExecutor (Task 02): compile is gated on `level >= LEVEL_ADJUDICATED` OR
   best-belief membership. LaTeX compile is 0 LLM cost but non-trivial wall-clock; bounding it
   to top-K keeps the paper phase from compiling `max_expansions` PDFs.
4. **Single entry point.** `select_best_node` (`ari-core/ari/pipeline/verified_context.py:36`,
   called at `projects.py:169`) yields ONE best exploration node; the archive seeds ONE draft
   space from it. There is no exploration-frontier × draft cross-product — the paper budget is
   independent of exploration node count, and of the exploration `ari.mode` (2×2 orthogonality,
   Task 01).
5. **Anchor scoring on a sample** (D3). Utility measurement is O(candidates × `sample_size`),
   not O(candidates × |corpus|).
6. **Epoch-amortized co-evolution.** Writer/reviewer prompts are frozen within an epoch
   (within-epoch freeze invariant); co-evolution runs ONLY at epoch boundaries through the
   existing `RegistryTransitionEngine` + `prompt_evolution` (Task 03), at most
   `max_total_candidates_per_epoch` (4) candidates. Over an E-epoch paper run the co-evolution
   term is `≤ 4·E` candidate generations + `≤ 4·E·sample_size` anchor scores — **linear in E**,
   amortized across all drafts scored in the epoch.

### 5.5 Enforcement points (decision-point gating, never mid-call)

Where the manager is consulted on the paper path (all fail-open — `budget.py:367-369`):

- **Per-draft expansion** — the `PaperArchiveStrategy`/draft NodeExecutor checks the running
  expansion count for the CURRENT epoch against `max_expansions` before seeding/refining
  (the counter resets per archive round; §6.3 scopes it by `paper_epoch_id`). Exceeded ⇒ the
  archive stops expanding at whatever depth it has reached and proceeds to best-belief
  selection — this is `should_prune`'s total-node cutoff (`bfts.py:501-502`) doing the work,
  not a depth clamp.
- **Per-draft governance** — before scoring/attacking a draft, `assign_level` sets the draft's
  level; `paper_self_preference` runs only at L2+ and only within
  `max_adversary_calls_per_epoch` (`manager.gate(BudgetedAction(ADVERSARY_CALL))`,
  degrade/skip audit-logged as in `budget.py:403-416`).
- **Epoch boundary** — before generating co-evolution candidates,
  `manager.gate(BudgetedAction(PROMPT_CANDIDATE, role=...))` enforces per-role + total caps;
  before anchor-scoring each candidate,
  `manager.gate(BudgetedAction(PAPER_ANCHOR_SCORING))` enforces `sample_size`.
- **Failure posture** — budget exhaustion **degrades** governance (caps the draft's effective
  level or skips the single action per `rqgm.budgets.on_exhausted`, `budget.py:290-293`); it
  never fails a draft, never blocks best-belief selection, and never blocks the compile +
  claim-gate handoff. The best draft always reaches Task 07's Layer-0 gate.

> **Residual (2026-07-17, verified open on branch `RQGM` — work order #31 + #44).** Two of the
> enforcement points above are partial in shipped code:
>
> - **Per-CANDIDATE anchor scoring is UNGATED.** The active reviewer's anchor loop *is* gated
>   (`_score_reviewer_on_anchor`, `paper_runtime.py`: `manager.gate(BudgetedAction(PAPER_ANCHOR_
>   SCORING))` per case). But the co-evolution candidate evaluator scores each candidate through
>   `score_reviewer_on_anchor(pool, verdict_fn)` (`paper_anchor.py`) with **no `gate`/`consume`**,
>   so the per-candidate C·S term of the §5.6 model is not enforced (a corpus with cases pinned
>   `split: "held_out"` drives it to O(|corpus|)). The intended fix is a PER-CANDIDATE counter
>   (`BudgetedAction(PAPER_ANCHOR_SCORING, role=<prompt_id>)`, `counter_key = f"{kind}:{role}"`),
>   NOT a bare shared `PAPER_ANCHOR_SCORING` (which shares the active reviewer's exhausted counter
>   and would route every candidate to a free `verdict="pass"`). Cost-only impact; no governance
>   softening, and the candidate evaluator does not fire at the default `rounds <= 2`.
> - **No `assign_level`/`level_with_triggers` per-draft ladder runs on the archive path.** The
>   "per-draft governance" bullet's `assign_level` is not called; the archive drives
>   `AdversarialRound.run` directly, bypassing `RQGMRuntime.run_adversarial_round`'s ladder hook.
>   Adding an L2+ gate would be vacuous (the ladder is observational, `runtime.py`), so only the
>   §6.3 `draft_levels` provenance is owed — recorded as a residual under §6.3 below.

### 5.6 Cost model (linear, tunable)

Let **K** = `archive.width` (4), **R** = `archive.refine_rounds` (2), **M** =
`archive.max_expansions` (12, **per epoch** — D2), **E** = paper epochs =
`rqgm.paper.epoch.rounds` (2; one epoch = one archive round, Task 01 owns the schema), **T** =
`governance.full_governance_only_on_top_k` (3), **A** =
`adversarial.max_adversary_calls_per_epoch` (24), **C** =
`prompt_evolution.max_total_candidates_per_epoch` (4), **S** = `anchor.sample_size` (8).

Draft population per epoch (guard §5.4.1):

```
N_draft = min( K · (1 + R), M )          # = min(4·3, 12) = 12 at defaults
```

Per-epoch LLM calls, by actor:

```
writer (skill, ungoverned by caps)   =  N_draft                     # seed + delta refine
paper_reviewer (governed, L1)        =  N_draft                     # one score / draft (D4)
paper_self_preference (governed, L2+)=  min( A, |top-K ∪ paper_cand| · max_attacks_per_node )
co-evolution candidate gen (bnd)     =  C            if prompt_evolution.enabled else 0
anchor utility scoring (governed)    =  C · S        if prompt_evolution.enabled and anchor.enabled else 0
LaTeX compiles (0 LLM, bounded)      ≤  T                            # lazy, top-K only
```

Total governed LLM calls over the run:

```
Calls(E) ≈ E · [ N_draft            (reviewer)
               + min(A, T·max_attacks_per_node)   (adversary)
               + C + C·S            (co-evolution + anchor) ]
         + E · N_draft              (writer skill calls)
```

Every factor — **K, R, M, E, T, A, C, S** — is a config cap. There is **no exponential term**,
and the reason is the *budget*, not the *shape*: `N_draft` is capped at **M** by
`should_prune`'s total-node cutoff at ANY depth (`ari-core/ari/orchestrator/bfts.py:501-502`,
§5.4.1), so no `width^depth` factor can ever enter the sum — a deeper tree redistributes the
same M nodes rather than multiplying them. `Calls(E)` therefore grows **linearly** in each
tunable, and raising `archive.depth` moves no term in the model.

At defaults — **E = 2**, since one paper epoch is one archive round and
`rqgm.paper.epoch.rounds` is 2 (Task 01) — the governed cost is roughly

```
per epoch: 12 (reviewer) + ≤24 (adversary) + 4 + 32 (co-evo + anchor)  ≈  72
run (E=2): ≈ 144 governed calls, plus 24 writer skill calls (12 per epoch)
```

i.e. the full co-evolving default costs **≈ 2×** the single-round degraded on-ramp (§5.7), not
3× and not a multiple of the exploration tree size. The per-epoch row above needs no adjustment
for the boundary: the `C + C·S (bnd)` term ALREADY budgets exactly one boundary's worth of
writer/reviewer co-evolution per epoch (§5.4.6 — the epoch closes once, at round end), so E
multiplies a row that already contains its boundary. This is a fixed, small, tunable budget.

Token cost scales the same way, weighted by the role context views (which are capped
projections per the parent-set §5.7 context-budget rules
([../ari_rqgm/12](../ari_rqgm/12_cost_control_and_context_budget.md) §5.7)): the
`paper_reviewer` sees `{draft_manuscript, verified_context, science_data,
reference_context/anchor_case}` (Task 03), each capped, so per-call tokens are bounded and
`Tokens(E) ≈ Calls(E) · O(capped context)` — still linear.

### 5.7 Degraded on-ramp (best-of-N, ≈ today's cost)

`rqgm.paper.prompt_evolution.enabled: false` is the cheap on-ramp (analog of the parent set's
B4/B5 baselines): the archive still produces K reviewed drafts and best-belief selects the
winner, but **no co-evolution and no anchor scoring run**. From §5.6 with the co-evolution and
anchor terms zeroed and E = 1 (the on-ramp is single-round by construction, not by default: with
co-evolution off a boundary adopts nothing, so a second round would rebuild drafts under
byte-identical prompts and buy nothing — the E = 2 default of §5.6 exists *because* the default
config co-evolves):

```
Calls ≈ N_draft (writer) + N_draft (reviewer) + ≤ A (adversary, if L2+ triggers) + ≤ T compiles
```

- With `archive.width: 1, refine_rounds: 0, prompt_evolution.enabled: false, anchor.enabled:
  false, adversarial.enabled: false`, the archive collapses to a **single reviewed draft** —
  one `write_paper_iterative` seed + one `paper_reviewer` score + one compile — i.e.
  **≈ today's linear-pipeline cost** (today's `write_paper_iterative` already runs its own
  internal draft→review→revise loop; the archive at width 1 adds only one governed reviewer
  score on top).
- At the default `width: 4`, the on-ramp costs **≈ K× a single reviewed pass** (best-of-N) with
  NO co-evolution — the honest price of best-of-N quality, tunable down to 1× via `width`.

This gives a monotone cost dial: `width 1 no-co-evo` (≈ today) → `width K no-co-evo` (best-of-N)
→ `width K + co-evo` (full paper-archive), each step's added cost bounded by the §5.6 terms.

### 5.8 Cost attribution and provenance

> **Implementation correction — no `phase="paper_governance"` string exists; attribution is
> inherited, not paper-specific (recorded 2026-07-17, verified open on branch `RQGM`).** The
> `phase="paper_governance"` prescription below was never implemented and MUST NOT be: the string
> occurs nowhere in the repository outside this plan, and minting it would be *actively harmful*.
> `GovernanceBudgetManager._spend_exhausted` filters `phase == "governance"` (`budget.py:314,333`),
> so a distinct `phase="paper_governance"` would be **invisible to the spend cap**, silently
> disabling `rqgm.budgets.max_governance_cost_usd_per_epoch` on the paper path — contradicting §2's
> inherit-verbatim mandate, §3's no-redesign non-goal, and parent
> [../ari_rqgm/12](../ari_rqgm/12_cost_control_and_context_budget.md)'s single phase vocabulary.
> The corrected, landed convention is in the bullet below.

- **Phase/skill tagging (landed convention).** Paper governed actors ride the REUSED actors and
  inherit their tags: the `paper_self_preference` round is dispatched through `AdversarialRound`,
  whose `_PromptedActor._complete` tags `phase="governance", skill="rqgm_adversarial"`
  (`ari-core/ari/rqgm/adversarial/engine.py`); co-evolution candidate minting tags
  `phase="governance", skill="clean_room"` (`clean_room.py`). Paper spend is separated from
  exploration spend by the `epoch` field (paper epochs carry a distinct `epoch_id`), **NOT** by a
  paper-specific phase string. The draft executor subprocess tags `skill="paper"` via the
  pre-existing `bootstrap_skill("paper")` (`ari-skill-paper/src/server.py`; no phase argument, so
  `phase=""`). The by_phase rollup in `cost_summary.json` (`cost_tracker.py:171-186`) attributes
  paper spend under the shared `governance` phase; per-paper-epoch separation rides
  `CallRecord.epoch`.
- **Epoch attribution.** At each paper-epoch open, `cost_tracker.set_default_metadata(
  epoch=paper_epoch_id)` (`cost_tracker.py:249`) stamps the additive `CallRecord.epoch` field
  (`cost_tracker.py:76-79`) so spend caps (`rqgm.budgets.max_governance_cost_usd_per_epoch`,
  read by `budget.py:295-331`) apply per paper epoch. On a `linear` run the field stays `None`
  and is dropped from the JSONL line (`cost_tracker.py:156-159`) — byte-identical trace.
- **Provenance.** `paper_archive_state.json` (Task 01) records the effective paper mode and,
  additively, the per-epoch budget counters (§6.3), so `ari paper` re-invocation rebuilds
  counters (resume-safety) exactly as `RQGMRuntime` does from `rqgm_audit.jsonl`.

## 6. Data structures / schema changes

### 6.1 `RQGMPaperConfig` budget fields (Pydantic sketch)

Task 01 owns the top-level `RQGMPaperConfig` shell; this plan fixes the budget-bearing
nested models:

```python
class RQGMPaperArchiveConfig(BaseModel):
    depth: int = 3                 # draft-tree depth -> BFTS max_depth (shape, not cost)
    width: int = 4                 # K sibling drafts (branch factor)
    refine_rounds: int = 2         # paper_refine child expansions per draft (= tree depth)
    max_expansions: int = 12       # HARD PER-EPOCH cap -> BFTS max_total_nodes (D2)

class RQGMPaperAnchorConfig(BaseModel):
    enabled: bool = True
    corpus_path: str = ""          # Task 04 owns curation; empty => anchor scoring disabled
    sample_size: int = 8           # held-out labeled papers per reviewer candidate

class RQGMPaperPromptEvolutionConfig(BaseModel):
    enabled: bool = True           # false = degraded on-ramp (best-of-N, no co-evolution)

class RQGMPaperConfig(BaseModel):
    model_config = {"extra": "allow"}   # forward-compat (Task 01 pattern)
    enabled: bool = False
    archive: RQGMPaperArchiveConfig = Field(default_factory=RQGMPaperArchiveConfig)
    anchor: RQGMPaperAnchorConfig = Field(default_factory=RQGMPaperAnchorConfig)
    prompt_evolution: RQGMPaperPromptEvolutionConfig = Field(
        default_factory=RQGMPaperPromptEvolutionConfig)
```

These nest under `RQGMConfig.paper` (Task 01). The count/attack caps consumed by the paper
actors are NOT duplicated here — they are read from the existing `rqgm.governance`,
`rqgm.adversarial`, `rqgm.prompt_evolution` blocks (D1/§5.3) via the same
`GovernanceBudgetManager._cap` reads (`budget.py:230-270`).

### 6.2 Additive budgeted-action kind (`ari-core/ari/rqgm/budget.py`)

```python
# additive to the closed v1 set (budget.py:46-68) — one new kind only
PAPER_ANCHOR_SCORING = "paper_anchor_scoring"
ACTION_KINDS = (..., PAPER_ANCHOR_SCORING)

# additive branch in GovernanceBudgetManager._cap (budget.py:230)
if action.kind == PAPER_ANCHOR_SCORING:
    anchor = _get(_get(_get(r, "paper"), "anchor"), None) or _get(_get(r, "paper"), "anchor")
    if not bool(_get(anchor, "enabled", True)):
        return 0                                   # zero-cost when anchor disabled
    return _num(_get(anchor, "sample_size", 8), 8)
```

The `paper_reviewer` L1 score and the writer skill call reuse existing counting (D4/§5.3): the
reviewer has no `_cap` branch (bounded by `max_expansions`); `paper_self_preference` reuses
`ADVERSARY_CALL`; co-evolution reuses `PROMPT_CANDIDATE`. Net budget-surface change: **one**
action kind, **one** `_cap` branch — the manager is otherwise untouched.

### 6.3 `paper_archive_state.json` budget counters (extends Task 01/02 schema, additive)

```jsonc
"budget_counters": {
  "paper_epoch_id": "paper_epoch_000",   // counters are PER-EPOCH (one archive round)
  "draft_expansions": 0,                 // vs rqgm.paper.archive.max_expansions (per epoch)
  "adversary_calls": 0,                  // vs rqgm.adversarial.max_adversary_calls_per_epoch
  "prompt_candidates": {"paper_writer": 0, "paper_reviewer": 0},
  "anchor_scoring_calls": 0,             // vs rqgm.paper.anchor.sample_size (× candidates)
  "governance_cost_usd": 0.0, "governance_tokens": 0,
  "compiles": 0                          // lazy-compile audit (bounded by top_k)
},
"draft_levels": [ {"node_id": "draft_003", "level": 3, "triggers": ["paper_candidate"]} ]
```

Counters are derived-from-durable-records (rebuilt from `rqgm_audit.jsonl` `budget_consumed`
lines by `GovernanceBudgetManager._restore`, `budget.py:175-203`) so they survive `ari paper`
re-invocation. `paper_archive_state.json` is the provenance mirror; the audit log is the source
of truth (same discipline as the parent set's EpochState counters).

> **Residual (2026-07-17, verified open on branch `RQGM` — work order #45 + #44).** Two fields of
> the mirror above are not yet emitted by `_persist_budget_counters` (`paper_runtime.py`):
>
> - **`governance_cost_usd` / `governance_tokens` are omitted.** The manager accumulates both
>   (`_spend_usd` / `_spend_tokens`, `budget.py`) and persists them on every `budget_consumed`
>   line, but the paper counters dict does not mirror them. They are **deliberately left absent
>   rather than stamped `0.0`/`0`**: the two paper `consume` sites do not yet pass `cost_usd` /
>   `tokens`, so a stamped `0.0` would be a fabricated value advertising zero governance spend.
>   The honest fix is to meter the two consume sites (anchor scoring + adversary) with the LLM
>   response's cost/tokens, then derive both keys from the epoch-filtered `budget_consumed` lines.
> - **`draft_levels` is not written.** No `assign_level` runs on the archive path (see the §5.5
>   residual), so the observational per-draft level provenance is absent. When wired it must reuse
>   `level_with_triggers` (`budget.py`) and `record_level` exactly as `run_adversarial_round`
>   does — it gates nothing.
>
> Consumers must treat both `governance_cost_usd`/`governance_tokens` and `draft_levels` as
> OPTIONAL keys until this lands. The other counters (`draft_expansions`, `adversary_calls`,
> `anchor_scoring_calls`, `prompt_candidates`, `compiles`) are emitted and audit-derived today.

### 6.4 `paper_draft_archive.jsonl` cost-relevant fields (Task 02 owns full schema)

This plan pins only the budget-relevant per-draft fields (Task 02 owns the rest):

```jsonc
{ "node_id": "draft_003", "parent_id": "draft_001",     // lineage (delta refine chain)
  "expansion_kind": "refine",                            // "seed" | "refine"
  "score": 0.71, "level": 2, "compiled": false,          // reviewer score, level, lazy-compile flag
  "expansion_index": 5 }                                 // vs max_expansions (best-first order)
```

`compiled: false` records the lazy-compile decision (§5.4.3); `expansion_index` records
best-first order so a lowered `max_expansions` truncates deterministically.

### 6.5 Checkpoint registration

`paper_archive_state.json` and `paper_draft_archive.jsonl` are added to
`PathManager.META_FILES` (`ari-core/ari/paths.py:404`) and `_INTERNAL_JSON_NAMES`
(`ari-core/ari/orchestrator/node_report/builder.py:327`); `paper_draft_archive.jsonl` also to
`_TRACE_FILES` (`ari-core/ari/paths.py:68`) — so budget counters and per-draft scores never
leak into node work dirs or `node_report.files_changed`. (Registration is shared with Task 01/02;
this plan asserts it as a cost-hygiene requirement.) No `cost_tracker` file changes: the paper
actors ride the existing `cost_trace.jsonl` / `cost_summary.json`.

## 7. API / class changes

All new symbols stay out of `ari.public.*` (no public-API snapshot churn — same posture as
Task 01 and parent-set Task 12).

| Symbol | Location (planned) | Contract |
|---|---|---|
| `PaperArchiveRuntime.budget_manager` (property) | `ari-core/ari/rqgm/paper_runtime.py` | Lazily constructs and reuses `ari.rqgm.budget.GovernanceBudgetManager` unchanged (§5.1); fail-open to `None`; every paper consumer tolerates absence. |
| `PAPER_ANCHOR_SCORING` (constant) | `ari-core/ari/rqgm/budget.py` | Additive action kind; appended to `ACTION_KINDS`; `_cap` reads `rqgm.paper.anchor.sample_size`, returns 0 when `anchor.enabled=false`. |
| `RQGMPaperArchiveConfig`, `RQGMPaperAnchorConfig`, `RQGMPaperPromptEvolutionConfig` | `ari-core/ari/config/__init__.py` | §6.1; nested under `RQGMPaperConfig` (Task 01). |
| `paper_expansion_budget(cfg) -> int` (helper) | `ari-core/ari/rqgm/paper_runtime.py` | Pure; returns `min(width·(1+refine_rounds), max_expansions)` — the §5.4.1 **per-epoch** population bound consumed by `PaperArchiveStrategy` (Task 02) as its BFTS `max_total_nodes`. Independent of `archive.depth`. |

Changed (existing) code, all additive:

- `ari-core/ari/rqgm/budget.py` — one constant + one `_cap` branch (§6.2). No change to
  `check`/`consume`/`gate`/`level_with_triggers`/`shadow_sample`; the manager is otherwise
  byte-identical, and all exploration budget behavior is untouched.
- `ari-core/ari/cli/projects.py:paper()` — the archive loop + its `budget_manager` are
  constructed inside the existing `if _rqgm_paper is not None:` branch (line 164), only when
  the effective paper mode is `rqgm_archive` (Task 01). The `linear` path (the fall-through to
  `generate_paper_section`, line 190) is unchanged.
- `ari-core/ari/paths.py`, `ari-core/ari/orchestrator/node_report/builder.py` — filename
  registrations (§6.5), shared with Task 01/02.
- No CLI command/flag changes; no `ari.public.*` changes; no MCP tool changes ⇒ zero contract
  golden regeneration for v1.

## 8. Migration / compatibility

Preserve-existing-behavior policy (normative):

1. **`paper.mode: linear` (default) is byte-identical to today's cost.** No
   `GovernanceBudgetManager` is constructed on the paper path (the `if _rqgm_paper is not None:`
   branch at `projects.py:164` is a dead branch under `linear`, exactly as today); no
   `rqgm.paper.*` block is read; `cost_trace.jsonl` has no `epoch` field
   (`cost_tracker.py:156-159`); the only paper budget levers remain the linear ones
   (`max_revision_rounds`, `--num-reviews-ensemble`, `--num-reflections`). No new files written.
2. **`rqgm.paper.enabled: false` / absent `rqgm.paper` block** is identical to `linear`
   (defaults inert; effective mode resolves to `LINEAR` per Task 01's `resolve_paper_mode`
   table). The interlock is structural (lazy construction), not a scatter of per-feature flags.
3. **Parent-set budget unchanged.** The single additive action kind and `_cap` branch (§6.2)
   do not alter any exploration budget decision; the exploration `GovernanceBudgetManager`
   returns identical verdicts. The parent-set Task-12 tests
   ([../ari_rqgm/12](../ari_rqgm/12_cost_control_and_context_budget.md) §9) pass untouched.
4. **Degraded on-ramp is opt-out of cost, not of correctness.**
   `prompt_evolution.enabled: false` removes co-evolution + anchor spend (§5.7) while keeping
   best-of-N reviewed drafts and the Layer-0 claim gate; it is a pure cost dial.
5. **Resume-safety.** Paper budget counters rebuild from `rqgm_audit.jsonl` (`_restore`,
   `budget.py:175`); no in-memory-only counter that would double budgets on `ari paper`
   re-invocation. `paper_archive_state.json` is the provenance mirror.
6. **Degradation ordering.** Budget exhaustion reduces the draft's governance level or skips a
   single governance action; it never fails a draft, never blocks best-belief selection, and
   never blocks the compile + claim-gate handoff — the L0 floor is exempt (`budget.py:427-428`).
7. **Independence.** The paper budget is orthogonal to exploration cost (`ari.mode`): one best
   node in, one draft space out (§5.4.4); all 2×2 exploration×paper combos have well-defined,
   independent budgets.

## 9. Tests

Unit (deterministic, no LLM):

1. **Population-bound test**: `paper_expansion_budget` returns `min(width·(1+refine_rounds),
   max_expansions)` for a table of `(width, refine_rounds, max_expansions)`, and returns the
   SAME value for every `archive.depth` in `{1, 3, 5}` — the bound is depth-independent
   (§5.4.1). Paired with a `should_prune` assertion at `archive.depth: 5`: a draft tree stops
   at `max_expansions` nodes with depth budget still unspent, pinning that the total-node cutoff
   (`bfts.py:501-502`) fires first and no `width^depth` term can exist.
2. **`PAPER_ANCHOR_SCORING` cap test**: `_cap(BudgetedAction(PAPER_ANCHOR_SCORING))` returns
   `sample_size` when `anchor.enabled=true`, 0 when `false` (mirrors the `SHADOW_CALL`
   disabled-returns-0 test, parent set §9).
3. **Reuse-verbatim test**: `paper_self_preference` dispatched as `ADVERSARY_CALL` is capped at
   `max_adversary_calls_per_epoch` (24); co-evolution `PROMPT_CANDIDATE` per-role (1) + total
   (4) caps fire — asserted against the SAME `budget.py` code the exploration tests exercise.
4. **`assign_level` on drafts**: a draft flagged `paper_candidate=True` → L3; a top-`full_
   governance_only_on_top_k` draft by `_scientific_score` → L3; a sterile draft → L0
   (`budget.py:454`). No paper-specific level code — the exploration `level_with_triggers`
   table test is reused with draft fixtures.
5. **Cost-model closed-form test**: for fixed `(K, R, E, T, A, C, S)`, the counted governed
   calls in a stub run match the §5.6 formula within the per-actor caps; grows linearly when
   each tunable is doubled (no super-linear term), and is **unchanged when `archive.depth` is
   doubled** — depth is absent from the model (§5.6). Includes the default `E = 2` row: ≈ 144
   governed + 24 writer calls, i.e. 2× the `E = 1` on-ramp.
6. **Resume-safety**: paper budget counters round-trip through `rqgm_audit.jsonl` →
   `_restore`; a second `ari paper` invocation does not double-count (counters continue, not
   reset).

Regression (linear paper pipeline unchanged):

7. **`paper.mode: linear` no-op**: with the default config, `paper()` writes no
   `paper_archive_state.json` / `paper_draft_archive.jsonl`, `cost_trace.jsonl` has no `epoch`
   field, no `GovernanceBudgetManager` is constructed on the paper path, and `sys.modules` has
   no paper-archive budget import. Byte-level `cost_summary.json` compatibility.
8. **Parent-set budget untouched**: the full parent-set Task-12 budget suite
   (`ari-core/tests/test_rqgm_*` budget tests) passes unchanged after the additive kind.

Smoke (paper-archive cost):

9. **Cost regression / budget check** (the required acceptance test): a `rqgm_archive` paper
   smoke run with a stub LLM and tiny caps (`archive.max_expansions: 3`,
   `adversarial.max_adversary_calls_per_epoch: 1`, `anchor.sample_size: 2`) asserts
   (a) draft expansions ≤ `max_expansions` per epoch, at `archive.depth: 3` (the cap binds
   before the depth clamp); (b) per-actor governed call counts never exceed configured caps —
   read from the `budget_counters` mirror in `paper_archive_state.json` (`draft_expansions`,
   `adversary_calls`, `anchor_scoring_calls`, `prompt_candidates`), which is DERIVED from the
   `rqgm_audit.jsonl` `budget_consumed` lines (the audit log is the source of truth); (c) the run
   completes (degrade-never-block) and the best draft reaches the Task-07 claim gate
   (`{ckpt}/full_paper.tex` exists); (d) compiles ≤ `full_governance_only_on_top_k`.
   *(Amended 2026-07-17: 9(b) originally said "recorded in `cost_trace.jsonl`, filtered by
   `phase="paper_governance"`". No such phase string exists in the code — see #35 — and minting it
   would make paper governance spend invisible to `_spend_exhausted`'s `phase=="governance"` filter,
   silently disabling the spend cap. The counters are asserted against the audit-log-derived
   `budget_counters` instead, matching `test_budget_counters_mirror_metered_anchor_and_adversary_spend`.)*
10. **Degraded-on-ramp cost parity**: `prompt_evolution.enabled: false, width: 1,
    refine_rounds: 0, anchor.enabled: false, adversarial.enabled: false` produces a governed
    call count equal to a single reviewed draft (≈ linear-pipeline cost); doubling `width`
    exactly K-scales the reviewer/writer call count and nothing else.

Resume:

11. A `rqgm_archive` paper run interrupted after some expansions, re-invoked: counters restore
    from `rqgm_audit.jsonl`, the archive resumes at the persisted `expansion_index`, and total
    expansions for the interrupted epoch across both invocations still respect the per-epoch
    `max_expansions` (a resume must not re-fund the round).

CI placement: all of the above are plain ari-core tests (run hard via `refactor-guards.yml`);
no new workflow. The cost regression test (item 9) is the spec-required budget check.

## 10. Risks

- **R1 — `max_expansions` set below `width·(1+refine_rounds)` starves refine.** A user lowering
  `max_expansions` to below the natural population truncates refine rounds. Mitigation:
  best-first ordering (§5.4.1) lands seeds before refines, and `expansion_index` (§6.4) makes
  the truncation deterministic; the population-bound test (item 1) documents the interaction.
- **R2 — Anchor scoring cost creep.** `sample_size × candidates` per epoch can grow if a user
  raises both `sample_size` and `max_total_candidates_per_epoch`. Mitigation: both are capped
  config; the cost-model test (item 5) bounds the product; Task 04 owns whether the held-out
  sample is fixed per epoch (recommended) to reuse cache across candidates.
- **R3 — Cross-process attribution gaps.** The `ari-skill-paper` writer subprocess is tagged
  via `bootstrap_skill`/`set_default_metadata`, but an epoch opened after the subprocess forks
  keeps the old `epoch` default (same caveat as parent set §10 for skills). Mitigation:
  best-effort epoch attribution for the writer (documented); the archive population is bounded
  by `max_expansions` regardless of attribution precision, so budget *enforcement* is unaffected.
- **R4 — Lazy-compile threshold mis-set.** Too low a compile threshold compiles too many drafts
  (wall-clock, not LLM); too high risks the winner never compiling before the claim gate.
  Mitigation: compile is gated on top-K / best-belief membership (§5.4.3), so the winner always
  compiles; the smoke test (item 9d) bounds compiles at `full_governance_only_on_top_k`.
- **R5 — Additive action kind drift.** Appending `PAPER_ANCHOR_SCORING` to the closed
  `ACTION_KINDS` set touches shared `budget.py`. Mitigation: the reuse-verbatim test (item 3)
  and parent-set suite (item 8) pin that no existing kind's cap changes; the new branch is
  guarded by `anchor.enabled` returning 0.
- **R6 — `paper.mode` config collision.** A top-level `paper:` block plus a nested
  `rqgm.paper:` block could confuse readers. Mitigation: Task 01 owns the `paper.mode` /
  `rqgm.paper.enabled` disambiguation (mode switch vs governance interlock); this plan reads
  only `rqgm.paper.*` budget fields and never `paper.mode` (independence, as `budget.py` never
  reads `ari.mode`).
- **R7 — On-ramp cost surprises.** Users may expect `rqgm_archive` to cost ≈ `linear` and be
  surprised by the default `width: 4` (4× best-of-N). Mitigation: §5.7's monotone cost dial is
  documented; the on-ramp collapses to today's cost at `width: 1`.

**Residual (2026-07-17, verified open — work order #40).** The over-accepted self-preference attack
count in `_attack_over_accepted` (`paper_runtime.py:1511`) is a hardcoded magic slice
`over[: max(2, min(len(over), 4))]`, not a config knob. It is NOT a spend hole — each iteration is
gated by `bm.gate(BudgetedAction(ADVERSARY_CALL))`, so the per-epoch `max_adversary_calls_per_epoch`
(24) still bounds total spend inside the §5.6 model (the cost-acceptance test item 9 confirms this at
`max_adversary_calls_per_epoch: 1`). The residual is that the ≤4 bound is arbitrary rather than tied
to a documented knob; the work order proposes `rqgm.paper.anchor.sample_size` (loosening ≤4 → ≤8,
still inside §5.6). Deferred pending a decision on which knob owns the bound — this doc does not
currently specify one, so wiring it needs a dated amendment naming the knob, not a silent constant
swap.

## 11. Completion criteria

This task is complete when all of the following hold:

1. **Task-12 budget inheritance stated** — the reuse of `GovernanceBudgetManager`, the L0–L3
   ladder, `level_with_triggers` (incl. the `paper_candidate` / `full_governance_only_on_top_k`
   triggers), the adversary cap, and the prompt-evolution caps is specified verbatim with the
   paper-path construction site (§5.1, §5.3), with NO budget-manager rewrite.
2. **Paper budget config defined** — `rqgm.paper.archive` (`depth`, `width`, `refine_rounds`,
   `max_expansions`), `rqgm.paper.anchor` (`enabled`, `corpus_path`, `sample_size`),
   `rqgm.paper.prompt_evolution.enabled`, and the reused single-schema-home Task-12 knobs are
   specified with types, defaults, and enforcement points (§5.2, §6.1); no cap is duplicated.
3. **Structural cost guards specified** — best-first under the hard node cap, delta refine,
   lazy compile, single entry point, anchor sampling, epoch-amortized co-evolution — each with
   its enforcement site (§5.4, §5.5).
4. **Cost model given** — the closed-form `Calls(E)`/`Tokens(E)` ≈ *f(K, R, E, T, A, C, S)* with
   a worked default-config number at **E = 2**, and the linearity argument: the bound comes from
   `max_expansions` → `max_total_nodes` capping the tree at any depth (`bfts.py:501-502`), NOT
   from constraining the topology, and `archive.depth` appears nowhere in the model (§5.6).
5. **Degraded on-ramp defined** — `prompt_evolution.enabled: false` = best-of-N reviewed drafts,
   its cost formula, and the collapse to ≈ today's cost at `width: 1` (§5.7).
6. **Budgeted-action mapping fixed** — every paper actor's action kind, cap, and single schema
   home is fixed; exactly one additive kind (`PAPER_ANCHOR_SCORING`) is introduced (§5.3, §6.2).
7. **Attribution + resume-safety specified** — phase/skill/epoch tagging, counter homes in
   `paper_archive_state.json`, derive-from-audit-log restore (§5.8, §6.3).
8. **Cost regression / budget check test agreed** — the §9 item 9 smoke test is the
   implementation acceptance test; the `linear` no-op regression (item 7) and parent-set
   untouched (item 8) are pinned.

## 12. Deletion criteria

This plan file may be deleted only when all of the following hold:

- The target feature/design is merged into the main branch.
- Corresponding tests have been added.
- CI is green.
- Key design decisions have been moved to permanent docs or code comments.
- No unresolved open questions remain, or they have been moved to another task plan.
- No downstream task depends solely on this plan file.
- INDEX.md task status has been updated to completed/deleted.
- Developers will not be confused by this file's absence.
- The deleted content remains available in git history.

Task-specific criteria (all additionally required):

- The `rqgm.paper.archive` / `rqgm.paper.anchor` / `rqgm.paper.prompt_evolution` budget config
  is implemented as typed fields with defaults mirrored in `defaults.yaml`.
- The paper path constructs and reuses `GovernanceBudgetManager` unchanged, with the single
  additive `PAPER_ANCHOR_SCORING` kind + `_cap` branch landed and no existing cap altered.
- The structural guards (best-first population bound, lazy compile, single entry point) are
  implemented and enforced at the `PaperArchiveStrategy` / draft NodeExecutor sites.
- The cost regression / budget check test (§9 item 9) exists and runs in CI, plus the `linear`
  no-op regression (item 7) and the parent-set-untouched assertion (item 8).
- The degraded on-ramp (`prompt_evolution.enabled: false`) is implemented and its cost parity
  test (§9 item 10) passes.
- The cost model and the budget knob semantics are migrated to permanent docs (execution-mode
  guide / schema reference), and `docs/reference/` entries exist for the new `rqgm.paper.*`
  keys and the `paper_archive_state.json` budget counters.

## 13. Delete-after checklist

Verify before deleting this file:

- [ ] Implementation is complete.
- [ ] Tests exist.
- [ ] CI is green.
- [ ] Key design decisions have been moved to permanent docs.
- [ ] Unfinished items have been moved to another task plan.
- [ ] INDEX.md has been updated.
- [ ] Deleting this plan file will not strand any developer.
- [ ] The deletion reason can be stated in the commit message.

Task-specific items:

- [ ] `rqgm.paper.archive` / `rqgm.paper.anchor` / `rqgm.paper.prompt_evolution` budget config
      implemented as typed fields with defaults mirrored in `defaults.yaml`.
- [ ] `GovernanceBudgetManager` reused unchanged on the paper path (only `PAPER_ANCHOR_SCORING`
      + its `_cap` branch added); parent-set budget suite green.
- [ ] Structural guards (population bound, lazy compile, single entry point, anchor sampling)
      implemented and enforced.
- [ ] Cost regression / budget check test passing in CI; `linear` no-op regression passing.
- [ ] Degraded on-ramp implemented; best-of-N cost parity test passing.
- [ ] `paper_archive_state.json` / `paper_draft_archive.jsonl` registered in
      `PathManager.META_FILES`, `_TRACE_FILES`, and node-report `_INTERNAL_JSON_NAMES`.
- [ ] Cost model, budget-knob semantics, and the `rqgm.paper.*` keys documented in permanent
      docs (`docs/reference/` + execution-mode guide).
