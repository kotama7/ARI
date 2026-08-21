# Task 00: Current Paper-Pipeline Investigation

> **Status**: planned · **Depends on**: none · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

The ARI-RQGM *paper-archive co-evolution* plan set adds a **third, opt-in execution
path** — `paper.mode: rqgm_archive` — that brings the RQGM co-evolution loop to the
**paper-writing phase**, paralleling how `simple_bfts` and `ari_rqgm` parallel each
other for the exploration phase. The load-bearing insight is that the governance layer
(epochs, evolvable roles, kernel, adversarial + replay, selective erasure, the Task-12
budget) is **topology-agnostic** — it keys on records, roles, prompt hashes and epoch
boundaries, never on tree depth — so the paper phase runs the **same genuine best-first
tree** the exploration phase already runs, under the same `SearchStrategy` Protocol.
Paper writing is therefore realized as a **best-first tree over draft space**: the root
is the paper task seeded from the exploration winner, **K seed drafts at depth 1**, each
expandable into **refined / variant child drafts at depth 2–3**, scored by a co-evolving
`paper_reviewer`, best-belief selected, with writer/reviewer prompts co-evolving only at
epoch boundaries. "Archive" is RQGM's own word for the node population and a tree **is**
an archive with lineage, so the `PaperArchiveRuntime` / `PaperArchiveStrategy` /
`paper_draft_archive.jsonl` / `rqgm.paper.archive.*` vocabulary is unchanged — only the
topology claim is.

Before any of that can be designed safely, the seven implementation docs (01–07) need
a shared, verified picture of **what the paper phase actually is today**: where
`ari paper` enters, how `run_paper_candidate_escalation` *already* hooks the exploration
runtime into paper pre-flight, how `WorkflowDriver` runs the linear stages in file
order, how the claim-evidence hard gate acts as a never-evolving Layer-0, how the best
node is picked (`select_best_node`), and what the `ari-skill-paper` subprocess exposes
as tools and prompts. This document **is** that picture, plus the two pieces every
downstream doc cites: the **reuse map** (which RQGM machinery is topology-agnostic and
reused unchanged vs. what is genuinely new) and the **must-not-break register**
(the compatibility contract for `paper.mode: linear`).

All findings were verified against the working tree at branch `RQGM`
(ari-core v0.9.1). All paths are repo-relative. This plan set sits alongside the
exploration-phase set at [../ari_rqgm/INDEX.md](../ari_rqgm/INDEX.md) and inherits its
investigation ([../ari_rqgm/00_current_ari_investigation.md](../ari_rqgm/00_current_ari_investigation.md));
this doc records only what is *new or specific to the paper phase*.

## 2. Scope

Investigation and organization only:

- The current paper-phase control flow: `ari paper` entry
  (`ari-core/ari/cli/projects.py`), the already-present RQGM paper hook
  (`run_paper_candidate_escalation`), best-node selection
  (`ari-core/ari/pipeline/verified_context.py:select_best_node`), and the linear
  `WorkflowDriver` stage sequence.
- The claim-evidence hard gate as Layer-0 and its blocking matrix.
- The `ari-skill-paper` subprocess tool surface (`write_paper_iterative`,
  `paper_refine`, `review_compiled_paper`, `merge_reviews`, `link_paper_claims`,
  `compile_paper`) and its five committed prompts — the raw material for the seed-prompt
  lift (Task 03) and the draft executor (Task 02).
- The **reuse map**: enumerate the RQGM components that are topology-agnostic and reused
  unchanged (mode resolution, kernel + capability matrix + context views, epoch /
  registry / transition, adversarial + replay, selective erasure, budget) vs. the small
  set that is new (a paper mode enum, a paper runtime, a draft-tree archive strategy, a
  paper draft executor, one new evaluable role, one new adversary type, an anchor
  corpus, two checkpoint files).
- The **must-not-break register** (BP-1 …): everything that holds byte-identically under
  `paper.mode: linear`.
- An **open-questions table** (Q-1 …) routing each unresolved decision to the paper-set
  doc (01–07) that owns it, including re-opening the anchor half of parent-set Q-49.

## 3. Non-goals

- No implementation. No code, config, schema, prompt, or CI change is made by this task.
- No design decisions that belong to Tasks 01–07. Where this document sketches a
  direction (e.g. §5.4 on seed-prompt lift, §5.6 on the `paper.mode` config home), it
  records the *constraint landscape* and the owning task decides.
- No governance of the `ari-skill-paper` subprocess. The plan set's whole point is to
  **avoid cross-process governance**: the skill is demoted to a dumb "draft executor"
  (the NodeExecutor hands), and the governed prompts live in ari-core roles.
- No change to BFTS exploration behavior, no change to the linear paper pipeline under
  `paper.mode: linear`, no change to the claim gate.
- No master plan / sequencing beyond dependency links; that lives in
  [INDEX.md](INDEX.md).

## 4. Existing paper-phase touchpoints

This section is the subsystem map for the paper phase. Every downstream plan's own "§4
Existing ARI touchpoints" should be a subset of (or refinement of) this section. All
paths repo-relative, verified against branch `RQGM`.

### 4.1 Paper entry and the already-wired RQGM paper hook

- `ari-core/ari/cli/projects.py` — the `paper()` Typer command (lines 61–191) is the
  paper-phase entry. It reads `{ckpt}/tree.json`, reconstructs `Node` objects
  (lines 126–145), resolves the config (`_resolve_cfg`, line 118), then calls
  `build_runtime(cfg, experiment_text, checkpoint_dir=checkpoint_dir)` (line 148) and
  unpacks the 6-tuple **positionally**: `mcp_paper = _runtime[2]`,
  `_bfts_paper = _runtime[3]` (lines 149–150).
- **The RQGM paper hook already exists** (lines 155–175). At paper pre-flight it does
  `_rqgm_paper = getattr(_bfts_paper, "rqgm", None)` (line 163) — the exact duck-typed
  attribute-presence detection Task 01 of the exploration set reserved
  (`getattr(bfts, "rqgm", None) -> RQGMRuntime | None`) — and when present:
  ```python
  # projects.py:164-175 (verbatim shape)
  if _rqgm_paper is not None:
      try:
          from ari.pipeline.verified_context import select_best_node as _select_best_node
          _best_paper_node = _select_best_node(all_nodes)
          if _best_paper_node is not None:
              _rqgm_paper.run_paper_candidate_escalation(_best_paper_node, all_nodes=all_nodes)
      except Exception as _esc_e:
          log.warning("rqgm paper-candidate escalation failed: %s", _esc_e)
  ```
- `run_paper_candidate_escalation` lives in
  `ari-core/ari/rqgm/runtime.py:1573`. Its docstring is explicit that it is a
  **light-touch, single-node** escalation *through existing per-node machinery* — it runs
  ONE final adversarial round on the best node with `paper_candidate=True` (so
  `should_attack` fires the paper-candidate clause and the budget ladder assigns L3),
  then admits the round's `ValidatedAttackRecord`s into the `AdversarialReplayPool`.
  It is **not** a co-evolution loop, does **not** create a draft population, does **not**
  govern the writer/reviewer prompts, and does **not** wrap the claim gate. §5.3 is the
  full delta between what this already does and what the archive path adds.
- After the hook, `projects.py` resolves the paper `workflow.yaml` checkpoint-first
  (lines 176–187) and calls `generate_paper_section(all_nodes, experiment_data,
  checkpoint_dir, mcp_paper, _cfg_str)` inside `pid_context` (lines 188–190). This is
  the **linear driver run** the archive loop plugs in *before/around* (Task 01).

### 4.2 Best-node selection — the archive's single seed

- `ari-core/ari/pipeline/verified_context.py:select_best_node(all_nodes)` (line 36):
  filters to nodes with `has_real_data` (falling back to all nodes), sorts by
  `_scientific_score` (`_scientific_score`, line 20 — reads `node.metrics["_scientific_score"]`,
  else the max numeric metric), and returns the single top node. This is the **one best
  exploration result** the paper is about — and the seed for the draft archive: the
  archive branches *from this one node's lineage*, not the whole tree, which is exactly
  why the paper phase is a single-entry-point search (a cost guard, doc 06).
- The same module builds `{ckpt}/verified_context.json` (`build_verified_context` /
  `write_verified_context`, lines 52 / 84) scoped to the best node's root→best lineage,
  and renders the grounded-claims prompt block (`render_grounded_block`, line 108) that
  the writer consumes. `verified_context` is one of the three fields on the existing
  `paper_writer` context view (§4.6) and one of the anchors of the future
  `paper_reviewer` view (Task 03).

### 4.3 The linear paper pipeline (WorkflowDriver, file-order stages)

- `ari-core/ari/core.py:generate_paper_section` (line 268) loads the pipeline from the
  checkpoint-first `workflow.yaml` and calls `run_pipeline` over a `WorkflowDriver`.
- `ari-core/ari/pipeline/driver.py` — `WorkflowDriver.run()` (line 68) runs YAML-declared
  stages in **file order (no topological sort)** via an index-based cursor loop
  (`while _stage_idx < len(stages)`, line 466), with `loop_back_to` the **only** bounded
  generate→verify→regenerate rewind primitive (a per-source-stage counter caps
  iterations, lines 457–465). Pre-flight it writes `nodes_tree.json`,
  `evaluation_criteria.json`, and the artifact-grounded `verified_context.json`
  (lines 150–219). Per-stage work is delegated to `ari-core/ari/pipeline/stages.py`
  (`make_stage` → `SubprocessMCPStage` / `ReActStage`); a stage that returns an
  error-only dict `{"error": ...}` fails, which is how blocking works
  (`ari-core/ari/pipeline/stage_runner.py`).
- The committed paper stage sequence (`ari-core/config/workflow.yaml`), in file order,
  is the pipeline the archive best-draft is handed to unchanged:

  | Stage | Tool | Role in the flow |
  |---|---|---|
  | `write_paper` | `write_paper_iterative` (:178) | seed draft with `% CLAIM:Cx:NCx` anchors |
  | `link_paper_claims_draft` | `link_paper_claims` (:222) | resolve claim anchors |
  | `claim_evidence_hard_gate_draft` | `claim_evidence_hard_gate` (:239) | Layer-0, draft never blocks |
  | `review_paper` | `review_compiled_paper` (:263) | rubric peer review |
  | `evidence_grounded_semantic_review` | `evidence_grounded_semantic_review` (:282) | advisory LLM review |
  | `merge_reviews` | `merge_reviews` (:301) | structural merge of the two reviews |
  | `paper_refine` | `paper_refine` (:323) | anchor-preserving revision |
  | `render_paper` | `compile_paper` (:339) | `full_paper.tex → full_paper.pdf` |
  | `link_paper_claims_final` | `link_paper_claims` (:354) | re-resolve after refine |
  | `evidence_grounded_semantic_review_post_refine` | `evidence_grounded_semantic_review` (:371) | post-refine advisory |
  | `claim_evidence_hard_gate_final` | `claim_evidence_hard_gate` (:390) | **Layer-0, blocks at final** |

  Observations that matter for the archive: (a) `write_paper` → `paper_refine` is already
  a seed-then-refine shape at depth 1 — the archive generalizes it from **one** draft to
  **K** drafts each with `refine_rounds` refinements; (b) output paths are **fixed and
  overwritten in place** (`full_paper.tex`), and `skip_if_exists` short-circuits
  re-register OLD outputs — the parent set's Q-49 recorded per-epoch versioning as open,
  and this set resolves the draft half of it by making drafts **archive nodes** rather
  than overwrites (§5.3, doc 02).

### 4.4 Claim gate = Layer 0

- `ari-core/ari/pipeline/claim_gate/` (`gate.py:run_hard_gate`, `policy.py`, `numeric.py`,
  `resolve.py`, `invariants.py`, `contract.py`, `formula_eval.py`, `latex.py`) with the
  public surface `ari-core/ari/public/claim_gate.py`. This is the **deterministic,
  RQGM-independent, never-evolving hard gate** — the same Layer-0 fixed layer that
  [Execution Modes → Constitutional kernel (Layer 0)](../../guides/execution_modes.md#constitutional-kernel-layer-0)
  records as never an evolution target and never kernel-wrapped. Blocking matrix
  (unchanged, a global invariant of this set too): **draft never blocks**; `always_block_on` objective falsehoods block at
  final in ANY mode; the gate **fails open** on infrastructure errors.
- The gate is mirrored across process boundaries by `ari-skill-paper/src/claim_links.py`
  (mirrors `claim_gate/latex.py`) and `ari-skill-transform/src/claims.py` (mirrors
  `claim_gate/numeric.py`); these registries must stay in sync (parent B-10). The archive
  hands its **best** draft to this exact gate unchanged — the gate is a sibling, never a
  kernel-wrapped node (doc 07).

### 4.5 `ari-skill-paper`: the draft executor (tool surface + prompts)

- `ari-skill-paper/src/server.py` (137 KB) is a **separate stdio subprocess** that imports
  **zero** `ari.rqgm`. Its `@mcp.tool()` surface is the draft executor's hands:
  - `write_paper_iterative` (line 1091) — seeds a LaTeX draft, emits `% CLAIM:Cx:NCx`
    forward-declaration anchors, consumes `verified_context` by path. **The archive's
    NodeExecutor calls this to seed each of the K draft candidates.**
  - `paper_refine` (line 2446) — applies suggested revisions **preserving** `% CLAIM`
    anchors (deterministic explicit substitutions + bounded multi-pass LLM find/replace;
    on net anchor loss it keeps the original). **The archive's NodeExecutor calls this
    for each delta/refine expansion.**
  - `review_compiled_paper` (line 2084) — rubric-driven peer review (N-reviewer ensemble
    + Area Chair meta). **NOT used as the archive scorer**: the governed `paper_reviewer`
    role scores (doc 03); the skill just renders/compiles.
  - `merge_reviews` (line 2235), `link_paper_claims` (line 2372), `compile_paper`
    (line 446) — structural / rendering tools, reused by the linear tail unchanged.
- Prompts under `ari-skill-paper/src/prompts/` (the seed material for the lift, Task 03):
  - `paper_writer.md` (330 B) — a terse "fix LaTeX errors, do NOT hallucinate results,
    return the ENTIRE corrected document" reflection prompt.
  - `fill_in_writer.md` (2502 B) — the substantive writer prompt: placeholder-fill rules,
    `\cite{}` discipline, reproducibility rules, and the **RESEARCH CONTRACT — FORWARD
    DECLARATION** block (rule 10) that generates the `% CLAIM` anchors.
  - `academic_reviewer.md` (828 B) — the reviewer prompt: returns `overall` / `strengths`
    / `weaknesses` / `suggestions` / `accept_recommendation` JSON, with a reproducibility
    weakness criterion.
  - `global_coherence.md`, `figure_inserter.md` — coherence-refine and figure-insert
    prompts (out of scope for the lift; the skill keeps all five for `linear`).
- **Reviewer independence is already embodied here**: `review_compiled_paper` sees paper
  text only; `merge_reviews` is purely structural — the same role-separation the
  `paper_reviewer` same-role isolation generalizes (doc 03, mirroring `peer_review`).

### 4.6 The already-shipped RQGM governance substrate

The exploration set's `ari-core/ari/rqgm/` package (v0.9.1) is fully present and is the
substrate this set bolts onto. The topology-agnostic pieces relevant here:

- `ari-core/ari/rqgm/mode.py` — `EffectiveMode` enum + `resolve_effective_mode(cfg)`
  (pure, never raises, interlock table). The **direct template** for the new
  `PaperMode` / `resolve_paper_mode` (doc 01).
- `ari-core/ari/core.py:154-173` — the lazy-import guard: `bfts = BFTS(cfg.bfts, bfts_llm)`
  then `if _ari_mode == "ari_rqgm" or _rqgm_enabled:` imports `ari.rqgm.runtime` and
  wraps. The default path imports **no** `ari.rqgm` module. The paper-mode construction
  site (doc 01) mirrors this exactly at the paper entry.
- `ari-core/ari/rqgm/events.py` — `EVOLVABLE_ROLES` (line 57:
  `generator, reviewer, adversary, defender, judge, router, prompt_mutator,
  clean_room_generator, replay_selector, failure_summary_compressor`), `canonical_json`,
  `hash12`, `TransitionEvent`, the id formats. `paper_writer` and `paper_reviewer` are
  **added here** (doc 03).
- `ari-core/ari/rqgm/kernel_rules.py` — `CAPABILITY_MATRIX` (line 161),
  `CONTEXT_VIEW_WHITELISTS` (line 234), `CONSTITUTION_HASH` (line 304), `SEVERITY`
  (line 170, incl. `CK-CTX-001: warn` for context-scope overflow). **Crucially,
  `CONTEXT_VIEW_WHITELISTS["paper_writer"]` already exists** (lines 247–251):
  ```python
  "paper_writer": frozenset({"verified_context", "science_data", "claim_registry"}),
  ```
  Its comment (lines 226–233) says this is a **context-scope role only**, deliberately
  NOT an `EVOLVABLE_ROLES` member "in v1", precisely because the paper skill's prompts
  live in a separate ungoverned subprocess. This set **promotes** that entry to a full
  evolvable role and **unifies** the whitelist with the role's context view (doc 03) —
  a constitutional amendment that re-pins `CONSTITUTION_HASH` (see the amendment note at
  `kernel_rules.py:226-233` and the re-pin in `ari-core/tests/test_rqgm_kernel.py`).
- `ari-core/ari/rqgm/prompt_spec.py` — `FOUNDING_PROMPT_TABLE` (line 153),
  `FOUNDING_COMPONENT_TABLE` (line 232), `PromptSpec`, `build_founding_specs`. The lifted
  writer/reviewer seed prompts register as **founding specs** here (doc 03), byte-hashed
  by `founding_spec_from_entry` (`prompt_hash == load_versioned(key)[1]`).
- `ari-core/ari/rqgm/budget.py` — `GovernanceBudgetManager`, `assign_level` /
  `level_with_triggers` (lines 420 / 433), level ladder `L0 sterile → L3 adjudicated`,
  the `paper_candidate` trigger → `LEVEL_ADJUDICATED` (line 468), `full_governance_only_on_top_k`
  gate (line 461). **Inherited verbatim** for the archive's per-draft budgeting (doc 06).
- `ari-core/ari/rqgm/adversarial/` — `engine.py:should_attack` (line 334, with the
  `paper_candidate` clause line 361), `build_artifact_bundle` (line 266), `AdversaryEngine`
  / `Defender` / `ArtifactJudge`, `apply_utility_penalty`; `pool.py:AdversarialReplayPool`;
  `records.py:ValidatedAttackRecord`; `round.py:AdversarialRound`. The
  attack→`ValidatedAttackRecord`→replay→boundary-reward machinery is **reused as-is**; only
  a new `paper_self_preference` adversary type + a human/AI paper corpus are new (doc 05).
- `ari-core/ari/rqgm/frontier_repair.py`, `erasure_state.py` — selective erasure keyed on
  `prompt_hash` dependency closure, topology-independent, reused as-is (doc 03/04 rely on
  it for staling superseded reviewer scores).
- `ari-core/ari/rqgm/transition_engine.py`, `transition_rules.py` —
  `RegistryTransitionEngine` + the frozen transition table; the writer/reviewer
  co-evolution at epoch boundaries rides this unchanged (doc 03).
- `ari-core/ari/paths.py:META_FILES` (line 404) and
  `ari-core/ari/orchestrator/node_report/builder.py:_INTERNAL_JSON_NAMES` (line 327) —
  both already register the RQGM state files (`rqgm_state.json`, `epoch_state.json`,
  `rqgm_registry.json`, `rqgm_transitions.jsonl`, `rqgm_audit.jsonl`). The two new paper
  files (`paper_archive_state.json`, `paper_draft_archive.jsonl`) are added the same way
  (doc 01/02).

## 5. Findings

Here, "findings" = the organized attachment-point map, the reuse map, the register, and
the routed open questions that all downstream designs build on.

### 5.1 The load-bearing insight: the draft archive is a genuine BFTS tree

The exploration set already proved RQGM governance is **topology-agnostic** by bolting it
onto ARI's exploration tree: the kernel, epochs, registry/transition, adversarial+replay,
selective erasure, and budget all key on *records, roles, prompt hashes, and epoch
boundaries* — never on tree depth. Concretely, `should_attack`
(`adversarial/engine.py:334`) and `assign_level` (`budget.py:433`) take a node, a
frontier score list, and flags; neither reads tree structure. The
`RegistryTransitionEngine` and selective erasure key on `prompt_hash` closure, not
lineage.

Therefore the paper phase is realized as a **genuine best-first tree over draft space**,
identical in shape to exploration BFTS — root → K seed drafts at depth 1 → refined /
variant child drafts at depth 2–3:

```
              select_best_node(all_nodes)            ← §4.2, the ONE seed
                        │
                   paper_root                        ← depth 0: the paper task
                        │
        ┌───────────┬───┴───────┬───────────┐        depth 1: K seed drafts
     draft_0     draft_1     draft_2     draft_3     (write_paper_iterative seeds,
        │           │           │                     archive.width = K)
   ┌────┴────┐      │           │
draft_0a  draft_0b  draft_1a  draft_2a               depth 2: CHILD drafts
(refine)  (variant) (refine)   (refine)              ← a paper_refine / re-framing pass
   │                                                   creates a CHILD NODE, not a
draft_0a′                                              lineage column (doc 02)
(refine)                                             depth 3: archive.depth cap = 3

  every node scored by paper_reviewer  ← governed EVALUATOR role (doc 03)
  select_best_to_expand picks the frontier node to grow  ← REAL best-first selection
  (paper_reviewer score + a REAL diversity_bonus rewarding divergent framings, doc 02)
                        │
              best-belief selection  ← the winning draft, anywhere in the tree
                        │
              EXISTING compile + claim_gate  ← §4.3/§4.4 unchanged (doc 07)
```

Note the tree is **unbalanced by construction**: best-first spends its budget where the
reviewer score is highest, so `draft_0` may grow three levels while `draft_3` is never
expanded. That is the search working, not a defect.

This maps onto the *existing* `ari-core/ari/orchestrator/bfts.py` with `depth` and
`branch` constraints (`archive.depth` = 3 → BFTS `max_depth`, `archive.width` = K →
branch) plugged into the SAME `ari-core/ari/protocols/search.py:SearchStrategy` Protocol
(the 7 methods `select_next_node` / `select_best_to_expand` / `should_prune` / `expand` /
`record_run` / `expansion_count` / `diversity_bonus`, lines 34–77). Nothing about the
depth is special-cased: `ari-core/ari/config/__init__.py:1559` already defaults
exploration to `max_depth=5` under that same Protocol, so a real draft tree is
**inherited and available**, not invented here. The new `PaperArchiveStrategy` is a
**reuse, not a rewrite** (doc 02).

**A tree is not a cost risk.** `bfts.py:501-503` — `should_prune` caps BOTH
`current_total >= cfg.max_total_nodes` *and* `node.depth >= cfg.max_depth`, and the
**total-node cap binds first and binds at any depth**. The branching factor never
multiplies into `b^d`, because the substrate stops minting nodes once the total cap is
hit regardless of how deep or wide the frontier is. Cost is therefore
O(`max_expansions`), a config cap, at **any** depth — bounding cost and flattening the
topology are independent knobs, and only the former is load-bearing (BP-10, doc 06). The
best-belief selection mechanics and the width/depth/refine defaults are doc 02's; the
point here is only that the substrate already fits a real tree.

### 5.2 Reuse map — reused unchanged vs. new

The whole economy of this plan set is in this table. **The overwhelming majority of the
machinery is reused unchanged**; the new surface is small and additive.

| RQGM component | File / symbol | Paper-phase disposition | Owner |
|---|---|---|---|
| Mode resolution (enum + pure resolver + interlock table) | `ari/rqgm/mode.py` | **Pattern reused**; new sibling `PaperMode` / `resolve_paper_mode` in `ari/rqgm/paper_mode.py` | [01](01_paper_execution_mode.md) |
| Lazy-import construction guard | `ari/core.py:154-173` | **Pattern reused**; new `PaperArchiveRuntime` construction site at the paper entry | [01](01_paper_execution_mode.md) |
| `SearchStrategy` / `NodeExecutor` Protocols | `ari/protocols/search.py:34,78` | **Reused unchanged**; `PaperArchiveStrategy` + a draft NodeExecutor plug in | [02](02_paper_draft_archive_search.md) |
| BFTS tree core (depth/branch constraints) | `ari/orchestrator/bfts.py` | **Reused unchanged** as a genuine best-first tree (`archive.depth` = 3 → `max_depth`, `archive.width` = K → branch); the `max_total_nodes` cap at `bfts.py:501-503` bounds cost at any depth | [02](02_paper_draft_archive_search.md) |
| Kernel + capability matrix + severity | `ari/rqgm/kernel_rules.py` | **Reused unchanged** (CK-* codes apply as-is) | [03](03_writer_reviewer_governed_roles.md) |
| Context-view whitelist | `ari/rqgm/kernel_rules.py:234` | **Extended**: `paper_writer` promoted, `paper_reviewer` added → `CONSTITUTION_HASH` re-pin | [03](03_writer_reviewer_governed_roles.md) |
| Evolvable-role vocabulary | `ari/rqgm/events.py:57` | **Extended**: `+paper_writer`, `+paper_reviewer` | [03](03_writer_reviewer_governed_roles.md) |
| Founding prompt/component tables | `ari/rqgm/prompt_spec.py:153,232` | **Extended**: lifted writer/reviewer seed specs | [03](03_writer_reviewer_governed_roles.md) |
| Registry / transition / epoch boundary | `ari/rqgm/transition_engine.py`, `transition_rules.py`, `store.py`, `state.py` | **Reused unchanged**; writer/reviewer co-evolve at boundaries | [03](03_writer_reviewer_governed_roles.md) |
| Governance orchestrator (reliability → evidence → motion → adjudication → self-audit) | `ari/rqgm/governance/*` (`GovernanceOrchestrator`, `audit_epoch`, `__init__.py:39,79`) | **Reused unchanged**; constructed *inside* `PaperArchiveRuntime` (ctor mirrors `runtime.py:463-477`), since the `simple_bfts` × `rqgm_archive` cell has no exploration `RQGMRuntime` to inherit one from. `resolve_transition` requires its `governance_report` — without this row the paper boundary adopts nothing | [01](01_paper_execution_mode.md), [03](03_writer_reviewer_governed_roles.md) |
| Utility-policy rewrite at epoch boundaries (P1's score half) | `ari/rqgm/state.py:313` `capture_utility_policy`, `frontier_repair.py:97-101` `INVALIDATE_ROLES` | **INHERITED from the new parent task [../ari_rqgm/14_governed_utility_evolution.md]**, topology-agnostically. The cause side (a T-rule that rewrites `composite` / `axis_weights` / `frontier_score`, and `utility_policy`'s role limbo at `events.py:57,73`) is a **method-wide** gap the exploration phase shares; this set invents **no paper-local utility machinery** | [14](../ari_rqgm/14_governed_utility_evolution.md) (parent) |
| Prompt evolution (mutation candidates, caps) | `ari/rqgm/prompt_evolution.py` | **Reused unchanged**; degradable via `rqgm.paper.prompt_evolution.enabled` | [03](03_writer_reviewer_governed_roles.md), [06](06_cost_control_and_budget.md) |
| Selective erasure / frontier repair | `ari/rqgm/frontier_repair.py`, `erasure_state.py` | **Reused unchanged**; stales superseded reviewer scores by `prompt_hash` closure | [03](03_writer_reviewer_governed_roles.md), [04](04_anchor_utility_and_epoch_winners.md) |
| Adversarial loop (attack→judge→replay→reward) | `ari/rqgm/adversarial/*` | **Reused unchanged**; only `+paper_self_preference` type + a human/AI corpus are new | [05](05_adversarial_self_preference.md) |
| Adversarial replay pool | `ari/rqgm/adversarial/pool.py` | **Reused unchanged**; already admits paper-candidate attacks (`_admit_paper_validated_attacks`) | [05](05_adversarial_self_preference.md) |
| Governance budget ladder (L0–L3, top-K, per-epoch caps) | `ari/rqgm/budget.py`, `ari/configs/defaults.yaml` | **Inherited verbatim**; `full_governance_only_on_top_k:3`, `max_attacks_per_node:3`, `max_adversary_calls_per_epoch:24`, `max_total_candidates_per_epoch:4` | [06](06_cost_control_and_budget.md) |
| Existing paper-candidate escalation hook | `ari/rqgm/runtime.py:1573`, `projects.py:163` | **Reused as-is**; the archive loop composes with it (§5.3) | [01](01_paper_execution_mode.md), [05](05_adversarial_self_preference.md) |
| Best-node selection | `ari/pipeline/verified_context.py:36` | **Reused unchanged** as the archive's single seed | [02](02_paper_draft_archive_search.md) |
| Linear stage driver + claim gate | `ari/pipeline/driver.py`, `ari/pipeline/claim_gate/*` | **Reused unchanged**; best draft handed to the existing tail | [07](07_claim_gate_handoff_and_evaluation.md) |
| Checkpoint file registration | `ari/paths.py:404`, `node_report/builder.py:327` | **Extended**: `+paper_archive_state.json`, `+paper_draft_archive.jsonl` | [01](01_paper_execution_mode.md), [02](02_paper_draft_archive_search.md) |
| **NEW** paper mode enum + resolver | `ari/rqgm/paper_mode.py` (planned) | new file | [01](01_paper_execution_mode.md) |
| **NEW** paper runtime facade | `ari/rqgm/paper_runtime.py` — `PaperArchiveRuntime` (planned) | new file | [01](01_paper_execution_mode.md) |
| **NEW** draft-tree archive strategy + draft executor | `PaperArchiveStrategy` + draft `NodeExecutor` (planned) | new symbols | [02](02_paper_draft_archive_search.md) |
| **NEW** anchor corpus + reviewer utility | APReS-equivalent accept/reject corpus (planned) | new data + policy | [04](04_anchor_utility_and_epoch_winners.md) |
| **NEW** self-preference adversary | `paper_self_preference` type (planned) | new adversary spec | [05](05_adversarial_self_preference.md) |

Net-new surface: **one enum file, one runtime file, one strategy + executor, two evolable
constitutional entries, one adversary type, one anchor corpus, two checkpoint files.**
Everything else is the existing exploration substrate reused across the topology
boundary. This is the "bright spot" doc 05 emphasizes for the adversarial half, and it
generalizes to the whole set.

### 5.3 What already exists vs. what the archive adds

The current `run_paper_candidate_escalation` (`runtime.py:1573`, wired at
`projects.py:163`) already delivers *some* paper→RQGM feedback: at pre-flight it takes
the single best node, runs one L3 adversarial round on its real artifacts, and admits
validated attacks to the replay pool. It is deliberately **light-touch and single-node**.
The archive path is a **strict superset** that adds four things, without removing the
existing hook:

1. **A draft population, not a single node.** Today one best node → one linear draft.
   The archive expands the best node into K draft candidates + `refine_rounds` refinements
   each (doc 02). Per-epoch draft versioning is resolved *inside the archive*: drafts are
   archive nodes (`paper_draft_archive.jsonl`), not overwrites of `full_paper.tex` — this
   resolves the draft half of parent-set Q-49 (which Task 13 there resolved as "no
   per-epoch versioning" for the linear pipeline).
2. **A governed evaluator.** Today scoring is the ungoverned skill
   `review_compiled_paper` (in the linear tail) plus a one-shot adversarial round. The
   archive scores drafts with the **governed `paper_reviewer` role** whose prompt RQGM
   evolves (doc 03), anchored on an accept/reject corpus (doc 04).
3. **A governed writer.** Today the writer prompt is the ungoverned skill prompt
   (`fill_in_writer.md`). The archive promotes `paper_writer` to a full evolvable role
   whose founding prompt is *lifted* from the skill prompt (doc 03); the skill keeps its
   copy for `linear`.
4. **Epoch-boundary co-evolution + a self-preference adversary.** The writer/reviewer
   prompts co-evolve only at epoch boundaries through the existing
   `RegistryTransitionEngine`; a new `paper_self_preference` adversary detects
   AI-authorship over-leniency and feeds the replay pool (doc 05), reusing the exact
   machinery the existing escalation already touches.

The existing hook composes cleanly: under the archive path, `run_paper_candidate_escalation`
still runs on the *winning* draft's node before the linear tail (its fail-open contract is
unchanged), so nothing regresses (doc 05 §"already wired" reuse).

### 5.4 Seed-prompt lift landscape

The founding prompts for the two governed roles are **lifted** from the skill prompts into
ari-core governed founding prompts; the skill keeps its copies for `linear` mode:

- `paper_writer` founding prompt ← `ari-skill-paper/src/prompts/fill_in_writer.md`
  (the substantive writer with the `% CLAIM` forward-declaration contract) and/or
  `paper_writer.md` (the reflection/fix prompt). Which of the two is the founding seed —
  or a merge — is a doc 03 decision.
- `paper_reviewer` founding prompt ← `ari-skill-paper/src/prompts/academic_reviewer.md`
  (the accept-recommendation JSON reviewer). Doc 03 decides the exact contract.

Mechanics constraints (recorded for doc 03; it decides):
- Founding specs are byte-hashed by `prompt_spec.py:founding_spec_from_entry`
  (`prompt_hash == load_versioned(key)[1]`). Lifted prompts must therefore become
  **committed `ari-core/ari/prompts/**.md`** templates with loader keys, so all four
  prompt snapshot layers (parent §4.10 / B-19) apply — a runtime-only lifted string would
  break the Gate-10 "every prompt in the appendix verbatim" doctrine (parent Q-30).
- The skill prompt files are NOT edited (they stay the `linear`-mode source), so the lift
  is a *copy-with-provenance*, not a move. Keeping the two in sync (or deliberately letting
  them diverge) is a doc 03 decision.
- `paper_reviewer` is DISTINCT from the exploration `reviewer` (`evaluator/peer_review`,
  a founding `reviewer_prompt_v1`): the manuscript reviewer is a manuscript-scoped
  evaluator with context view `{draft_manuscript, verified_context, science_data,
  reference_context/anchor_case}`, whereas the exploration reviewer scores nodes. Same-role
  isolation for `paper_reviewer` mirrors `peer_review` (doc 03).

### 5.5 State / checkpoint registration landscape

- Two new checkpoint-root files must be registered exactly as the RQGM state files were
  (parent §4.9 persistence playbook): `paper_archive_state.json` (paper-phase mode
  provenance, mirrors `rqgm_state.json`) and `paper_draft_archive.jsonl` (the draft
  population + scores + lineage). Registration goes in `ari-core/ari/paths.py:META_FILES`
  (line 404 — otherwise the file is copied into every node work dir) and, for the JSON
  snapshot, `ari-core/ari/orchestrator/node_report/builder.py:_INTERNAL_JSON_NAMES`
  (line 327 — otherwise it surfaces as a publishable data output). Both are **absent on
  `linear` runs** (the P5 absence-is-default marker convention, parent B-14): absence of
  `paper_archive_state.json` == a pure linear paper run == byte-identical to today.
- `paper_archive_state.json` mirrors `rqgm_state.json`'s shape: `schema_version`, the
  effective `paper.mode`, `rqgm_paper_enabled`, a `mode_source` provenance field, and a
  best-effort byte-fixed writer (`indent=2, ensure_ascii=False`) via a
  `ari-core/ari/checkpoint.py` store method + shim. The exact schema is doc 01's; the
  draft-archive JSONL schema is doc 02's.
- The paper phase **runs once** (there is no outer `while` loop like `_run_loop`): the
  archive's epochs are *internal* to the paper phase, so the epoch boundary is the
  archive's own round boundary, not the exploration loop's. Mode is resolved once at the
  paper entry and persisted before the first draft — there is **no mid-phase switch**
  (doc 01).

### 5.6 Config surface findings (paper.mode home)

- The switch is a **top-level `paper:` block** with `paper.mode: linear | rqgm_archive`
  (default `linear`) plus a redundant interlock `rqgm.paper.enabled: false` (mirrors
  `rqgm.enabled`). Effective `PAPER_RQGM_ARCHIVE` requires
  `paper.mode == rqgm_archive AND rqgm.paper.enabled == true`; disagreement fails safe to
  `linear` with a warning — the exact shape of `resolve_effective_mode`'s table
  (`mode.py:37-56`), which doc 01 mirrors as `resolve_paper_mode`. Env overrides:
  `ARI_PAPER_MODE`, `ARI_RQGM_PAPER_ENABLED`.
  ```python
  # planned: ari-core/ari/rqgm/paper_mode.py (OWNED BY doc 01 — shape only, not a decision here)
  class PaperMode(str, Enum):
      LINEAR = "linear"
      RQGM_ARCHIVE = "rqgm_archive"
  def resolve_paper_mode(cfg) -> PaperMode:   # pure; env applied upstream; never raises; warning table
      ...
  ```
- **Config-home caveat (mirror parent Task 01).** `ari-core/ari/config/__init__.py`
  filters raw YAML to `ARIConfig.model_fields` (parent §4.11), so a bare `paper:` block is
  **silently dropped** unless it becomes a first-class typed field on `ARIConfig`. The
  same route parent Task 01 chose (typed `AriModeConfig` / `RQGMConfig`) is the only clean
  home; the raw-YAML re-read alternative already produced the package-vs-checkpoint
  inconsistency parent §4.11 records. There is a **naming collision to resolve**:
  `rqgm.paper.*` is a *new subsection under the existing `rqgm:` block*, whose Pydantic
  model is `RQGMConfig` with `model_config = {"extra": "allow"}` (parent §6.1) — so
  `rqgm.paper.*` parses warn-free today and must be typed by doc 01, exactly as parent
  Task 12 typed its subsections. Whether `paper.mode` also needs a `PaperConfig` model or
  rides an existing block is doc 01's decision (Q-1).
- Archive knobs live under `rqgm.paper.archive` (`width` = K, default 4; `refine_rounds`
  default 2; `max_expansions` default 12 **per epoch**; `depth` default **3** → BFTS
  `max_depth`, a real draft tree, §5.1); anchor knobs under
  `rqgm.paper.anchor` (`corpus_path`, `sample_size`, `enabled`); the on-ramp toggle is
  `rqgm.paper.prompt_evolution.enabled` (default true; false = best-of-N reviewed drafts
  with **no** co-evolution — the cheap on-ramp). These are cited from the reused Task-12
  numeric-defaults home `ari-core/ari/configs/defaults.yaml` (which already carries
  `rqgm.governance.full_governance_only_on_top_k: 3` at line 35,
  `rqgm.adversarial.max_attacks_per_node: 3` / `max_adversary_calls_per_epoch: 24` at lines
  81–82, `rqgm.prompt_evolution.max_total_candidates_per_epoch: 4` at line 110). Doc 01
  pins the schema; docs 02/04/06 pin the individual knob semantics.

### 5.7 Must-not-break register (paper-phase)

This is the paper-phase compatibility contract. Everything below holds byte-identically
under `paper.mode: linear`; `rqgm_archive` is additive and config-gated. These labels are
**BP-** (paper) to distinguish them from the parent set's B-1…B-19, which this set also
inherits verbatim (a `rqgm_archive` run is still an `ari_rqgm`-substrate run and must
honor them). Downstream plans cite these by number.

- **BP-1 `linear` is identity.** A config without a `paper:` block (or with
  `paper.mode: linear`) produces a paper phase byte-identical to today: same
  `WorkflowDriver` stage order, same fixed output paths, same `full_paper.tex` /
  `full_paper.pdf`, and no `paper_archive_state.json` / `paper_draft_archive.jsonl` left
  behind. No `ari.rqgm` paper module is imported on the linear path.
- **BP-2 The claim gate stays Layer-0, unchanged.** `claim_evidence_hard_gate` blocking
  matrix (draft never blocks; `always_block_on` blocks at final in any mode; fails open on
  infra errors) is preserved; the gate is never kernel-wrapped; the best archive draft is
  handed to the *existing* compile + gate tail unchanged.
- **BP-3 The linear stage sequence and file-order execution** (`driver.py:466`,
  `loop_back_to` the only rewind, `skip_if_exists` / `depends_on` semantics, error-only
  dict ⇒ stage failure) are unchanged; the archive plugs in **before/around** the driver
  run at the paper entry, never inside a stage.
- **BP-4 `% CLAIM:Cx:NCx` anchor survival.** `write_paper_iterative` emits anchors and
  `paper_refine` preserves them (net-anchor-loss ⇒ keep original); the mirrored registries
  `claim_gate/latex.py ↔ ari-skill-paper/src/claim_links.py` and
  `claim_gate/numeric.py ↔ ari-skill-transform/src/claims.py` stay in sync. Draft
  candidates must carry anchors so the winner passes the final gate.
- **BP-5 `ari-skill-paper` is not governed cross-process and is not edited for governance.**
  It stays a stdio subprocess importing zero `ari.rqgm`; the governed prompts live in
  ari-core roles. The skill's five prompt files are the `linear` source and are not moved.
  The skill is the draft executor's hands (`write_paper_iterative` seeds, `paper_refine`
  refines); `review_compiled_paper` is NOT the archive scorer.
- **BP-6 `select_best_node` semantics** (`verified_context.py:36`) are unchanged: prefer
  `has_real_data`, rank by `_scientific_score`. The archive seeds from its single winner;
  it does not change how the winner is chosen.
- **BP-7 The existing `run_paper_candidate_escalation` hook is preserved.** Its duck-typed
  `getattr(bfts, "rqgm", None)` detection, its fail-open contract, and its light-touch
  single-node behavior stay; the archive composes with it (runs it on the winning draft's
  node), never removes it.
- **BP-8 Reviewer independence and structural merge.** `review_compiled_paper` sees paper
  text only; `merge_reviews` is purely structural. The governed `paper_reviewer`'s
  same-role isolation must not weaken this (mirror `peer_review`).
- **BP-9 Opt-in independence.** Exploration `ari.mode` × paper `paper.mode` are orthogonal
  (all four 2×2 combinations valid); `paper.mode` resolution never reads `ari.mode` and
  vice versa (mirror the parent `mode.py` VirSci-independence discipline).
- **BP-10 Cost is bounded by budget caps, not by topology.** The bound comes from
  `rqgm.paper.archive.max_expansions` → BFTS `max_total_nodes`: `should_prune`
  (`bfts.py:501-503`) returns True once `current_total >= cfg.max_total_nodes`, **before**
  and independently of the `node.depth >= cfg.max_depth` clause, so the node count is
  capped at **any** depth and no branching factor can compound into `b^d`. Cost is
  O(`max_expansions`) per epoch × E epochs, both config caps ⇒ linear in a tunable budget,
  never exponential (doc 06). The other bounds are likewise budget-shaped, not
  topology-shaped: lazy LaTeX compile (only threshold-passing drafts compile),
  single-entry-point (one best node → one draft space), `full_governance_only_on_top_k`,
  per-epoch adversary/candidate caps, anchor scoring on a sample, epoch-amortized
  co-evolution. The degraded on-ramp (`rqgm.paper.prompt_evolution.enabled=false`) is
  ≈ today's cost. **This invariant does NOT pin the topology flat**: `archive.depth > 1`
  is the design (§5.1, default 3), it is not a risk, and any future change to `depth` or
  `width` is a tuning decision that leaves BP-10 intact so long as the expansion cap
  holds. Only the caps are frozen here.
- **BP-11 Within-epoch freeze.** The active writer/reviewer prompt hashes and the reviewer
  utility policy are frozen per epoch; co-evolution happens only at boundaries through the
  `RegistryTransitionEngine` + `ConstitutionalKernel` — never mid-archive.
- **BP-12 Checkpoint hygiene / P2 / P5.** New files registered in `META_FILES` +
  `_INTERNAL_JSON_NAMES`; byte-fixed formatting; no wall-clock/git-SHA/host in any hash;
  `hash12 = sha256[:12]` the single prompt-hash scheme; `CONSTITUTION_HASH` re-pinned on
  the amendment and asserted in `ari-core/tests/test_rqgm_kernel.py`.

### 5.8 Open-questions table

Each unresolved decision is routed to the doc that owns it — normally a paper-set doc
(01–07), but a method-wide concern is routed **out** to the parent set rather than
re-solved locally (Q-19). (These are paper-set Q-ids; where a parent-set question is
re-opened it is cited explicitly.)

| # | Open question | Owner |
|---|---|---|
| Q-1 | `paper.mode` config home: a typed `PaperConfig` on `ARIConfig` vs. reusing the `rqgm:` block for `rqgm.paper.*`; resolve the `RQGMConfig.extra:allow` subsection typing; env-override names (`ARI_PAPER_MODE`, `ARI_RQGM_PAPER_ENABLED`) and precedence. | [01](01_paper_execution_mode.md) |
| Q-2 | `PaperMode` enum + `resolve_paper_mode` table; the redundant-interlock disagreement fallback to `linear` with warning (mirror `mode.py:37-56`). | [01](01_paper_execution_mode.md) |
| Q-3 | `PaperArchiveRuntime` construction site at the paper entry (`projects.py` around line 148) — lazy-import guard mirroring `core.py:154-173`; independence from exploration `ari.mode` (2×2 matrix). | [01](01_paper_execution_mode.md) |
| Q-4 | `paper_archive_state.json` schema + provenance + resume; mode-switch timing (paper phase runs once; no mid-phase switch); registration in `META_FILES` / `_INTERNAL_JSON_NAMES`. | [01](01_paper_execution_mode.md) |
| Q-5 | `PaperArchiveStrategy` (depth = `archive.depth`, branch = `archive.width`) plugging into `SearchStrategy`; how it maps onto `bfts.py` depth/branch constraints (reuse, not rewrite); the **real** `select_best_to_expand` frontier selection over draft nodes and the **real** `diversity_bonus` (§5.1 — neither may be degenerate); best-belief selection over the whole tree. | [02](02_paper_draft_archive_search.md) |
| Q-6 | The draft `NodeExecutor` wrapping `ari-skill-paper` (`write_paper_iterative` seeds, `paper_refine` = delta/refine expansions; `review_compiled_paper` NOT the scorer). | [02](02_paper_draft_archive_search.md) |
| Q-7 | `paper_draft_archive.jsonl` schema (draft population + scores + lineage); per-epoch draft versioning inside the archive (resolves the draft half of parent Q-49). | [02](02_paper_draft_archive_search.md) |
| Q-8 | Lazy LaTeX compile: only threshold-passing drafts compile (`compile_paper` gating). | [02](02_paper_draft_archive_search.md), [06](06_cost_control_and_budget.md) |
| Q-9 | Promote `paper_writer` (context-scope-only `kernel_rules.py:247`) to a full `EVOLVABLE_ROLES` member; unify the existing `{verified_context, science_data, claim_registry}` whitelist with the role's context view; `CONSTITUTION_HASH` re-pin. | [03](03_writer_reviewer_governed_roles.md) |
| Q-10 | Add `paper_reviewer` as a NEW evaluator role (context view `{draft_manuscript, verified_context, science_data, reference_context/anchor_case}`); capability matrix + transition presence; same-role isolation mirroring `peer_review`. | [03](03_writer_reviewer_governed_roles.md) |
| Q-11 | Seed-prompt lift: which skill prompt (`fill_in_writer.md` vs `paper_writer.md`, or a merge) founds `paper_writer`; `academic_reviewer.md` founds `paper_reviewer`; committed-template + founding-spec mechanics (all four snapshot layers); keep-vs-diverge from the skill copies. | [03](03_writer_reviewer_governed_roles.md) |
| Q-12 | Writer/reviewer co-evolution at epoch boundaries via the existing `RegistryTransitionEngine` + `prompt_evolution`; how governed prompts DRIVE the skill executor (skill = hands). | [03](03_writer_reviewer_governed_roles.md) |
| Q-13 | The APReS-equivalent accept/reject anchor corpus for the `paper_reviewer` utility; reviewer scored on agreement with anchor labels on a held-out `sample_size`; the writer anchored separately to the Layer-0 claim gate's deterministic faithfulness (so its PROMPT co-evolves) while its DRAFT winners stay epoch-local. **Resolves the anchor half of parent Q-49.** | [04](04_anchor_utility_and_epoch_winners.md) |
| Q-14 | Anchor corpus curation cost + a minimal bootstrap (reuse ARI's own accepted/rejected artifacts, or a small seed set); `rqgm.paper.anchor.{corpus_path, sample_size, enabled}` semantics; utility-policy freeze in the epoch fingerprint. | [04](04_anchor_utility_and_epoch_winners.md) |
| Q-15 | The `paper_self_preference` adversary type (AI-authorship / over-leniency detector, §5.4 analog); the displaced-reviewer-accepted-AI-papers → `AdversarialReplayPool` → next-epoch dual objective; reuse of the existing attack→`ValidatedAttackRecord`→replay→boundary-reward machinery. | [05](05_adversarial_self_preference.md) |
| Q-16 | Cost model: expected token ≈ f(K width, `refine_rounds`, epochs, top_k); inherit Task-12 budget verbatim (`GovernanceBudgetManager`, level ladder, `full_governance_only_on_top_k`, per-epoch caps); the `prompt_evolution.enabled=false` on-ramp ≈ today's cost. | [06](06_cost_control_and_budget.md) |
| Q-17 | Best archive draft → EXISTING compile + `claim_gate` Layer-0 handoff (unchanged; gate stays a sibling, never kernel-wrapped). | [07](07_claim_gate_handoff_and_evaluation.md) |
| Q-18 | Evaluation / ablation harness: acceptance-rate under a fixed external reviewer panel + RQGM detection metrics; B-baselines (B0 linear, B_archive-no-coevo, B_full); whole-set completion + deletion posture summary. | [07](07_claim_gate_handoff_and_evaluation.md) |
| Q-19 | **P1's score-rewrite half — NOT owned by this set.** At epoch boundaries the utility function itself (`composite` / `axis_weights` / `frontier_score`) is rewritten, not merely the prompts. The consequence side already ships (`frontier_repair.py:97-101` `INVALIDATE_ROLES` includes `utility_policy`; `UtilityRecord` freezes weights by value at `adversarial/engine.py:948`; `epoch_fingerprint` covers `utility_policy`), but the **cause** side is missing: `state.py:313` `capture_utility_policy` reads only the static resolved cfg, so `utility_policy_hash` is byte-identical every epoch (its own docstring: "the frozen policy is constant across epochs within a run"); no transition rule targets utility/weight/axis; and `utility_policy` is in neither `EVOLVABLE_ROLES` nor `FIXED_ROLES` (`events.py:57,73`). This is **method-wide** — the exploration phase violates P1 identically — so it is fixed **once at the parent level** and the paper phase inherits it topology-agnostically. **The paper set invents no utility machinery** (§5.2); docs 02/04/06 cite task 14 rather than re-pinning "axes frozen per run". | [14](../ari_rqgm/14_governed_utility_evolution.md) (parent) |

## 6. Data structures / schema changes

**None introduced by this task.** For downstream reference, the existing data contracts
new paper-archive schemas must respect:

- The `WorkflowDriver` stage contract and fixed output paths (`full_paper.tex` /
  `full_paper.pdf`, §4.3) — the archive versions drafts *beside* these, never replacing
  the linear tail's fixed paths (BP-1, BP-3; doc 02 owns `paper_draft_archive.jsonl`).
- The claim-gate report shape (§4.4) — the best draft's gate report is a ready-made
  per-run scorecard for the doc 07 evaluation harness.
- The existing RQGM record envelope, `PromptSpec`, `FOUNDING_PROMPT_TABLE`, and
  `CONTEXT_VIEW_WHITELISTS` shapes (§4.6) — the two new evolable entries are additive
  extensions of these, owned by doc 03.

## 7. Completion criteria

This investigation is complete when all of the following hold:

1. **Current paper phase mapped** — the `ari paper` entry, the already-wired
   `run_paper_candidate_escalation` hook, `select_best_node`, the file-order
   `WorkflowDriver` stage sequence, the claim-gate Layer-0 blocking matrix, and the
   `ari-skill-paper` tool surface + prompts are documented with real file:line refs
   (§4).
2. **Reuse map settled** — §5.2 enumerates which RQGM components are topology-agnostic
   and reused unchanged vs. the net-new surface, each routed to an owning doc.
3. **Delta from the existing hook stated** — §5.3 makes explicit that the archive is a
   strict superset of the current single-node escalation and composes with it.
4. **Must-not-break register written** — the paper-phase BP-1…BP-12 contract (§5.7) is
   recorded, with its relationship to the inherited parent B-1…B-19 stated.
5. **Open questions routed** — every unresolved decision (Q-1…Q-19) is assigned to the
   doc that owns it (§5.8): the paper-set docs (01–07) for paper-local decisions,
   including the re-opened anchor half of parent Q-49 (Q-13) and the resolved
   draft-versioning half (Q-7); and the parent set for the one method-wide concern
   (Q-19, P1's score-rewrite half → [../ari_rqgm/14_governed_utility_evolution.md](../ari_rqgm/14_governed_utility_evolution.md)),
   which this set inherits rather than re-solving.
6. **Downstream docs can cite attachment points without re-discovery** — docs 01–07 build
   their §4 from this section.

## 8. Deletion posture

This investigation doc is **not deletable** until the whole paper-archive plan set (01–07)
merges into main and its findings are migrated to permanent docs — mirroring
[../ari_rqgm/00_current_ari_investigation.md](../ari_rqgm/00_current_ari_investigation.md)'s
"not deletable" status in [../ari_rqgm/INDEX.md](../ari_rqgm/INDEX.md). Standard deletion
gates (target merged, tests added, CI green, decisions moved to permanent docs, no
unresolved open questions or they are re-homed, no downstream task depends solely on this
file, INDEX status updated, no developer stranded, content preserved in git history) apply
to the set as a whole. Task-specific: the §5.8 open questions must all be consumed or
re-homed by docs 01–07 before this file is removed.
