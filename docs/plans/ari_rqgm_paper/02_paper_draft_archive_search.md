# Task 02: Paper Draft Archive Search

> **Status**: planned · **Depends on**: 00, 01 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

The paper-archive co-evolution path realizes paper writing as a **genuine
best-first tree over draft space** — the same shape the exploration phase already
searches with, under the same `SearchStrategy` Protocol: one paper-task root, `K`
seed drafts at depth 1 (distinct framings), each expandable into refined/variant
child drafts at depth 2, 3, …, every draft scored by the governed `paper_reviewer`,
the frontier expanded best-first, and the winner best-belief selected. This task designs the **search
substrate only** — the ranking/selection policy and the single-node executor that
turn `ari-skill-paper`'s tool surface into an archive of scored drafts. It does
**not** design co-evolution (that is [03](03_writer_reviewer_governed_roles.md) /
[04](04_anchor_utility_and_epoch_winners.md)); it builds the plumbing those tasks
plug into.

Concretely this task settles:

- `PaperArchiveStrategy` — a new `ari.protocols.search.SearchStrategy` that maps
  the archive onto the **existing** `ari-core/ari/orchestrator/bfts.py` depth /
  branch constraints (reuse, not rewrite);
- `PaperDraftExecutor` — a new `ari.protocols.search.NodeExecutor` wrapping the
  `ari-skill-paper` subprocess (`write_paper_iterative` seeds, `paper_refine`
  delta-refine expansions, `compile_paper` for the lazy compile);
- **why a genuine tree over draft space** is the correct topology for paper
  drafting, and why its cost is bounded by `archive.max_expansions` at **any**
  depth (`bfts.py:501-503`) rather than by flattening the topology;
- **best-belief selection**, reusing `ari-core/ari/pipeline/verified_context.py:36
  select_best_node` verbatim;
- the `paper_draft_archive.jsonl` draft-population schema (resolving the
  per-epoch draft-versioning half of Q-49 — drafts are archive nodes, not
  overwrites of `full_paper.tex`);
- **lazy compile** — scoring is on `.tex` text; only the threshold-passing
  best-belief draft compiles once.

Downstream tasks hang their mechanics off this substrate: [03](03_writer_reviewer_governed_roles.md)
supplies the writer/reviewer prompts the executor calls,
[04](04_anchor_utility_and_epoch_winners.md) supplies the reviewer utility,
[06](06_cost_control_and_budget.md) bounds the archive's cost, and
[07](07_claim_gate_handoff_and_evaluation.md) owns the handoff of the best-belief
`.tex` to the Layer-0 claim gate.

## 2. Scope

- The `PaperArchiveStrategy` topology: a best-first tree of one `paper_root`
  (depth 0), `K` seed drafts (depth 1) and refine/variant children below them, with
  `archive.width` → root branch factor, `archive.refine_rounds` → draft branch
  factor, `archive.depth` → `max_depth`, and `archive.max_expansions` → the
  per-epoch node budget cap (→ `max_total_nodes`), which is what bounds cost.
- The mapping onto `bfts.py`'s three levers — `should_prune` (total-count cutoff
  checked **before** the depth cutoff, lines 501–503), one-child-per-`expand()`
  (invariant), and `select_best_to_expand` / `select_next_node` — showing which are
  reused and which the archive overrides.
- `PaperDraftExecutor.run(node, experiment)`: one generative skill call per node —
  `write_paper_iterative` for a seed, `paper_refine` for a refine child; the
  reviewer is an **injected scoring oracle** (its prompt/utility live in 03/04).
- The `paper_draft_archive.jsonl` schema (draft population + scores + lineage +
  content hashes) and `paper_archive_state.json` interplay (provenance file owned
  by [01](01_paper_execution_mode.md); this task only writes the draft records).
- Best-belief selection via `select_best_node` reuse; deterministic (LLM-free)
  best-first frontier selection, framing-keyed `diversity_bonus`, and
  intra-archive candidate ordering for P2 reproducibility.
- Lazy compile: text-only scoring, single deferred `compile_paper` on the winner,
  gated by `rqgm.paper.archive.compile_threshold`.
- The degraded on-ramp: when `rqgm.paper.prompt_evolution.enabled=false`, the same
  substrate degrades to reviewed best-of-N with a static prompt population — the
  strategy/executor are byte-identical, only the prompt set is frozen-and-single.
- Checkpoint-file registration for `paper_draft_archive.jsonl` (META_FILES +
  node-report internal-names).

## 3. Non-goals

- **No co-evolution mechanics.** The writer/reviewer prompt population, epoch
  boundaries, `RegistryTransitionEngine` wiring, and same-role isolation belong to
  [03](03_writer_reviewer_governed_roles.md). This task treats the active writer
  prompt set and the reviewer as frozen inputs for **one paper epoch** — one
  archive round, whose boundary and its `rqgm.paper.epoch.rounds` sizing knob are
  [01](01_paper_execution_mode.md)'s; the tree this task builds is rebuilt under
  the adopted prompts on the next round.
- **No anchor / utility definition.** The reviewer's ground-truth anchor corpus,
  held-out agreement scoring, and epoch-winner policy are
  [04](04_anchor_utility_and_epoch_winners.md). This task calls the reviewer as a
  score oracle and does not define what the score means.
- **No adversarial machinery.** `paper_self_preference`, `AdversarialReplayPool`
  reuse, and the dual objective are [05](05_adversarial_self_preference.md).
- **No cost model / budget ladder.** The `GovernanceBudgetManager` inheritance,
  the L0–L3 level ladder, `full_governance_only_on_top_k`, and the token model are
  [06](06_cost_control_and_budget.md). This task only pins the `max_expansions`
  cap that bounds skill calls structurally.
- **No claim-gate handoff.** How the best-belief `.tex` enters the existing
  `link_paper_claims → claim_evidence_hard_gate → … → finalize` chain, and the
  evaluation harness, are [07](07_claim_gate_handoff_and_evaluation.md).
- **No mode switch / runtime construction.** `paper.mode`, `resolve_paper_mode`,
  `PaperArchiveRuntime` construction at the `projects.py` paper entry, and
  `paper_archive_state.json` provenance are [01](01_paper_execution_mode.md).
- **No changes to `bfts.py`.** `PaperArchiveStrategy` is a **sibling** strategy
  behind the same Protocol, exactly as `GovernedSearchStrategy`
  (`ari-core/ari/rqgm/runtime.py:38`) is a sibling wrapper — the exploration BFTS
  is not touched.
- **No new linear-mode behavior.** Under `paper.mode: linear` (default) nothing in
  this task is constructed or imported.

## 4. Existing ARI touchpoints

All paths repo-relative. Verified against branch `RQGM` (ari-core v0.9.1).

| Touchpoint | File / symbol | Why it matters here |
|---|---|---|
| Search Protocols | `ari-core/ari/protocols/search.py` — `SearchStrategy` (line 34), `NodeExecutor` (line 77) | `PaperArchiveStrategy` implements the 7 `SearchStrategy` methods; `PaperDraftExecutor` implements `NodeExecutor.run(node, experiment) -> Node`. Both are satisfied **structurally** (no subclassing), the same way `BFTS`/`AgentLoop` satisfy them — so `PaperArchiveRuntime` binds to abstractions, not concretes. |
| Core tree (reuse target) | `ari-core/ari/orchestrator/bfts.py` — `BFTS.should_prune` (line 481), `BFTS.expand` (line 564), `BFTS.select_best_to_expand` (line 512), `_fallback_score` (line 313), `expansion_count` (line 258) | The three levers the archive reuses: `should_prune` caps `current_total >= cfg.max_total_nodes` (line 501) **before** `node.depth >= cfg.max_depth` (line 503) — the total-node cap binds first and binds at **any** depth, which is precisely why the archive can be a real tree at no extra cost (§5.1); `expand()` yields **at most one child per call** (hard cap `directions[:1]`, line 643) — the one-child-per-expand invariant the archive preserves; `expansion_count` tracks per-parent fan-out; `_select_fallback` (line 346) / `_fallback_score` (line 313) are the deterministic frontier-ranking shape the archive's `select_best_to_expand` follows. The archive borrows this **logic** without importing BFTS internals. |
| Inherited tree defaults (the precedent) | `ari-core/ari/config/__init__.py:1559` — `BFTSConfig(max_depth=int(os.environ.get("ARI_MAX_DEPTH", 5)), max_total_nodes=int(os.environ.get("ARI_MAX_NODES", 50)), …)` | Proof the tree is **inherited and available**, not absent: exploration already runs a genuine `max_depth = 5` tree under the same `SearchStrategy` Protocol this task implements, bounded by `max_total_nodes = 50` rather than by depth. The paper archive pulls the identical levers with `archive.depth = 3` / `archive.max_expansions = 12` (§5.1, §6.2). |
| Sibling-strategy precedent | `ari-core/ari/rqgm/runtime.py:38` — `GovernedSearchStrategy` | Proof that a non-`BFTS` object can satisfy `SearchStrategy` by delegation and plug into `build_runtime` / `_run_loop` with zero changes elsewhere. `PaperArchiveStrategy` is the paper-phase analog (standalone, not a wrapper). |
| Best-node ranking (reuse verbatim) | `ari-core/ari/pipeline/verified_context.py:36` — `select_best_node`; `_scientific_score` (line 20) | Best-belief selection **is** this function: ranks by `metrics["_scientific_score"]` desc, prefers `has_real_data`. The paper reviewer writes its composite into `node.metrics["_scientific_score"]`, so the archive winner is picked by the identical key that picks the exploration winner. |
| Paper entry / already-hooked | `ari-core/ari/cli/projects.py` — `paper` command; `_bfts_paper = _runtime[3]` (line 149), `_rqgm_paper = getattr(_bfts_paper, "rqgm", None)` (line 163), `run_paper_candidate_escalation` (line 171), `generate_paper_section` (line 190) | The archive loop is driven by `PaperArchiveRuntime` (built in [01](01_paper_execution_mode.md)) **at this entry**, before `generate_paper_section` runs the linear stages on the winning `.tex`. `select_best_node(all_nodes)` (line 169) already computes the exploration winner the archive seeds from. |
| Seed tool | `ari-skill-paper/src/server.py:1092` — `write_paper_iterative(...)` → `{latex, sections, reviews, revision_counts}` | Produces one draft candidate from the winning node's `verified_context_json` / `science_data_json` / figures / refs. The archive calls it `K` times to seed `K` siblings. `skip_if_exists: full_paper.tex` in the linear stage (`config/workflow.yaml:207`) is bypassed — the archive writes per-candidate `.tex` under distinct paths. |
| Refine tool | `ari-skill-paper/src/server.py:2447` — `paper_refine(tex_path, suggested_revisions_json, merged_review_path, semantic_review_path, venue)` → `{latex, refined, anchors_preserved, applied_revisions, refine_passes, unaddressed_substitutions}` | The delta-refine expansion. Non-destructive contract: preserves every `% CLAIM:Cx:NCx` anchor (lines 2468–2478), returns the paper unchanged when there are no actionable revisions — safe to call in a bounded loop. |
| Reviewer tool (NOT the scorer) | `ari-skill-paper/src/server.py:2085` — `review_compiled_paper(...)`; text-only contract (`config/workflow.yaml:267` "evaluates paper text only") | Its **text-only** independence is why scoring needs no compile (§5.5 lazy compile). But the archive scorer is the **governed `paper_reviewer` role**, not this ungoverned skill tool — the skill only renders/compiles here. |
| Compile tool | `ari-skill-paper/src/server.py:447` — `compile_paper(tex_dir, main_file="main.tex")`; linear `render_paper` stage (`config/workflow.yaml:337`) | The single lazy compile of the best-belief draft; then the existing render/gate chain runs on it. |
| Node model | `ari-core/ari/orchestrator/node.py:87` — `Node`, `to_dict` (line 144); `metrics` / `has_real_data` / `ancestor_ids` / `artifacts` / `label` (`NodeLabel`, line 18) | Draft candidates are `Node`s: `metrics["_scientific_score"]` carries the reviewer score; `artifacts` carries the candidate `.tex` path; `ancestor_ids` records the `paper_root` lineage. Reusing `Node` keeps `should_prune` / `select_best_node` working unmodified. |
| Checkpoint registration | `ari-core/ari/paths.py:404` — `PathManager.META_FILES`; `ari-core/ari/orchestrator/node_report/builder.py:327` — `_INTERNAL_JSON_NAMES` | `rqgm_state.json` / `constitution.yaml` / `rqgm_transitions.jsonl` already registered (lines 437–442); `paper_archive_state.json` + `paper_draft_archive.jsonl` must be added so they are treated as checkpoint-root metadata (never copied into node work dirs) and classified internal (not a publishable data output). |
| Defaults home | `ari-core/ari/configs/defaults.yaml:15` — `rqgm:` block | `rqgm.paper.archive.{width, refine_rounds, max_expansions, depth, compile_threshold}` defaults live here (added by this task/[01](01_paper_execution_mode.md)), inert unless the effective paper mode is `rqgm_archive`, mirroring the "inert unless `ari.mode: ari_rqgm` and `rqgm.enabled: true` agree" comment at line 14. |
| Effective-mode gate | `ari-core/ari/rqgm/paper_mode.py` (new; [01](01_paper_execution_mode.md)) — `PaperMode`, `resolve_paper_mode` | The archive substrate is only constructed when `resolve_paper_mode(cfg) is PaperMode.RQGM_ARCHIVE`. This task imports it; it does not define it. |

## 5. Proposed design

### 5.1 Why a genuine tree over draft space — the load-bearing decision

The paper phase searches the **same way** the exploration phase searches: a
best-first tree, expanded one child at a time, pruned by hard cutoffs, ranked by a
governed score. That is not a convenience — it *is* the method. Co-evolution needs a
lineage it can attribute to an epoch, select over, prune, and erase; a lineage with
those properties is a tree, and the `Node` model already carries it
(`parent_id` / `depth` / `ancestor_ids`, `node.py:87`).

Concretely: one `paper_root` (depth 0 — the frozen paper-task = the winning
exploration lineage), `K = archive.width` **seed drafts** at depth 1 (distinct
framings / active writer prompts), and each draft expandable into **refined or
variant child drafts** at depth 2, 3, … Diversity enters at the width; improvement
accumulates along the depth. A `paper_refine` pass is a **child node**, not a JSONL
lineage column (§5.4, decision 4).

What the tree buys — and what a depth-1 star throws away:

- **Best-first improvement.** With refine passes as nodes, `select_best_to_expand`
  (§5.2) spends the next expansion on whichever draft in the *whole* frontier scores
  best: a strong seed can absorb a three-deep refine chain while a weak one is
  dropped after its first score. A star has no frontier to select over, so it must
  spend its refine budget uniformly, by construction.
- **Prunability.** `should_prune` only sees **nodes**. A refine result recorded as a
  lineage column cannot be pruned, cannot be retired as `_sterile`, and —
  decisively — cannot be excluded by the selective-erasure clause
  (`_valid_for_frontier`, `bfts.py:508`;
  [RQGM Architecture → Key invariants](../../concepts/rqgm_architecture.md#key-invariants), invariant 6):
  a refinement written under a retired prompt would keep scoring through the column
  of a node that survives. As nodes, the erased sub-lineage simply stops expanding.
- **Epoch attribution.** Each draft node carries its own `epoch_id` and prompt
  hashes (§6.1), so a boundary can re-rank or invalidate exactly the sub-lineage a
  retired prompt produced — the unit of attribution is the node, not a column.

What depth here does **not** buy is new evidence: every draft renders the same frozen
verified context (`verified_context.json` / `science_data.json`), which is exactly
what keeps the Layer-0 claim gate sound. So this tree searches **revisions and
framings**, not measurements. That is a description of the paper task, not an
argument for flattening it — the value of a search is that the frontier decides where
the next revision goes, and that value needs a frontier to exist.

**The `b^d` objection is factually wrong on this substrate.** `BFTS.should_prune`
(`bfts.py:481`) checks `current_total >= cfg.max_total_nodes` (line 501) **before**
`node.depth >= cfg.max_depth` (line 503): the total-node cap binds first and binds
at **any** depth. Cost is therefore `O(max_expansions)` regardless of
`archive.depth` — a tree cannot branch past a budget it has already spent. The
exploration phase relies on exactly this and runs a genuine `max_depth = 5` tree
(`ari-core/ari/config/__init__.py:1559`) bounded by `max_total_nodes = 50`, under
the same `SearchStrategy` Protocol. Bounding cost and flattening the topology were
never the same decision.

Decision: **`archive.depth = 3` (default) — the paper archive is a tree, and its
cost is bounded by `archive.max_expansions` (→ BFTS `max_total_nodes`), never by
degenerating the topology.** Depth 3 is a **sizing** choice — a seed plus a
two-deep refine chain is what `refine_rounds = 2` funds per lineage (§6.2) — not a
statement that depth is dangerous: raising it adds no cost the budget cap does not
already bound (§9 pins this), and the budget ladder is
[06](06_cost_control_and_budget.md)'s to tune.

"Archive" stays the name. RQGM's archive is the scored node **population**, and a
tree is an archive *with lineage*: `PaperArchiveStrategy`,
`paper_draft_archive.jsonl` and `rqgm.paper.archive.*` are unchanged — only the
topology claim is. The governance layer is unaffected either way, because it is
topology-agnostic — the paper phase reuses the kernel, epochs, registry/transition,
adversarial and budget machinery unchanged across the topology boundary
([RQGM Architecture → The paper-archive layer](../../concepts/rqgm_architecture.md#the-paper-archive-layer)).

### 5.2 `PaperArchiveStrategy` — mapping the draft tree onto `bfts.py`

`PaperArchiveStrategy` is a standalone `SearchStrategy` (implements all 7 methods),
constructed from the frozen `rqgm.paper.archive` knobs. It **reuses BFTS's
pruning/counting logic** and BFTS's deterministic frontier-ranking shape
(`_fallback_score` / `_select_fallback`, `bfts.py:313` / `:346`) but owns the
draft-tree `expand`/`select` — it does not subclass or import `BFTS` internals
(Protocol-satisfied structurally, like `GovernedSearchStrategy`).

```python
# planned: ari-core/ari/rqgm/paper_archive.py  (new; internal, NOT ari.public.*)
from collections import Counter
from ari.protocols.search import SearchStrategy   # structural conformance target
from ari.orchestrator.node import Node, NodeLabel

class PaperArchiveStrategy:                        # satisfies SearchStrategy
    """Best-first draft tree: one paper_root (depth 0), up to `width` seed drafts
    (depth 1), each expandable into up to `refine_rounds` refine/variant children
    down to `depth`. Reuses bfts.py's should_prune cutoffs; owns an LLM-free
    deterministic frontier selection. No co-evolution here (Tasks 03/04)."""

    def __init__(self, knobs, *, root_task):       # knobs = cfg.rqgm.paper.archive
        self.width = int(knobs.width)              # K, default 4  -> root branch factor
        self.depth = int(knobs.depth)              # default 3     -> max_depth
        self.refine_rounds = int(knobs.refine_rounds)    # default 2 -> draft branch factor
        self.max_expansions = int(knobs.max_expansions)  # default 12 PER EPOCH (§6.2)
        self._root = root_task                     # paper_root Node (§5.3)
        self._expansions = 0                       # per-epoch budget accounting
        self._fanout: dict[str, int] = {}          # parent_id -> children created
        self._framings: list[str] = []             # recent framing keys (diversity)

    def _fanout_cap(self, node: Node) -> int:
        # The root fans out into `width` framings; a draft fans out into
        # `refine_rounds` refinements/variants. Cost is capped by max_expansions
        # regardless (§5.1) — these only shape where the budget may land.
        return self.width if node.depth == 0 else self.refine_rounds

    # ---- reused BFTS logic (total/depth cutoff), specialized to the tree -----
    def should_prune(self, node: Node, *, current_total: int) -> bool:
        # BFTS.should_prune's clauses in BFTS's ORDER (bfts.py:481-514) — the TOTAL
        # cap (bfts.py:501) binds before the depth cap (bfts.py:503), which is
        # exactly why depth costs nothing (§5.1) — plus ONE archive-specific clause
        # (the fan-out cap; BFTS lets its run-loop retire chronic re-expansions via
        # expansion_count instead, bfts.py:258).
        if current_total >= 1 + self.max_expansions:   # per-epoch budget = max_total_nodes
            return True
        if node.depth >= self.depth:               # depth==3 -> refine chain ends
            return True
        if self._fanout.get(node.id, 0) >= self._fanout_cap(node):
            return True                            # this parent's fan-out is spent
        m = node.metrics or {}
        if m.get("_sterile") is True:
            return True
        if m.get("_valid_for_frontier", True) is False:   # erasure (Task 10 reuse)
            return True
        return False

    def select_best_to_expand(self, frontier, experiment_goal, memory) -> Node:
        # REAL best-first frontier selection — the thing that makes this a search.
        # bfts.py:512 is the LLM analog; this is its DETERMINISTIC sibling, shaped
        # like _select_fallback (bfts.py:346) / _fallback_score (bfts.py:313):
        #   1. Seeds first: the root outranks every draft until `width` framings
        #      exist — an unsampled framing beats a marginal refine of a sampled
        #      one, and that is what `width` buys (§5.1).
        #   2. Then rank every expandable DRAFT by the governed paper_reviewer
        #      composite in metrics["_scientific_score"] (04) + diversity_bonus.
        # No LLM: the ranking key is already a governed score, so asking a model to
        # re-rank it would only buy nondeterminism (P2) and cost. max() keeps the
        # FIRST maximal element, so ties resolve to creation order (P2).
        if not frontier:
            raise ValueError("No frontier nodes to select from")
        if self._fanout.get(self._root.id, 0) < self.width and self._root in frontier:
            return self._root
        return max(frontier, key=lambda n: (
            float((n.metrics or {}).get("_scientific_score") or 0.0)
            + self.diversity_bonus(n)))

    def select_next_node(self, candidates, experiment_goal, memory) -> Node:
        # DETERMINISTIC (P2): pick the next not-yet-run draft in creation order.
        # No LLM — draft candidates carry a fixed "produce/refine" direction, so
        # the semantic pick BFTS uses for experiments buys nothing here.
        return candidates[0]

    def expand(self, node: Node, *args, existing_children=None, **kwargs) -> list[Node]:
        # ONE child per call (bfts.py:643 invariant preserved). Creates a draft
        # placeholder Node; PaperDraftExecutor.run() does the real generation.
        if self._expansions >= self.max_expansions:
            return []                              # per-epoch budget spent
        idx = self._fanout.get(node.id, 0)
        if idx >= self._fanout_cap(node) or node.depth >= self.depth:
            return []                              # fan-out full / chain at max depth
        child = Node(
            id=f"draft_{idx}" if node.depth == 0 else f"{node.id}.r{idx + 1}",
            parent_id=node.id, depth=node.depth + 1,
            label=NodeLabel.DRAFT, ancestor_ids=list(node.ancestor_ids) + [node.id],
        )
        child.original_direction = "seed" if node.depth == 0 else "refine"
        node.children.append(child.id)
        self._fanout[node.id] = idx + 1
        self._expansions += 1
        return [child]

    def record_run(self, node: Node) -> None:
        # Diversity accounting, mirroring BFTS.record_run (bfts.py:262) but keyed on
        # the draft's FRAMING (writer_prompt_hash, §5.4.5) instead of NodeLabel:
        # every draft is NodeLabel.DRAFT, so the label carries no signal here.
        key = (node.metrics or {}).get("_framing_key") or ""
        if key:
            self._framings.append(key)
            self._framings = self._framings[-20:]  # same window as bfts.py:248

    def expansion_count(self, node_id: str) -> int:
        return self._fanout.get(node_id, 0)

    def diversity_bonus(self, node: Node) -> float:
        # REAL, and the same contract as bfts.py:285-310: +0.05 when this draft's
        # framing is at most half as frequent as the most common framing among
        # recently-run drafts, 0.0 otherwise. Deterministic (P2) — a pure function
        # of run history, no LLM, no clock. It rewards structurally divergent
        # framings, so a lineage that keeps refining one framing loses ties to an
        # under-sampled one; _scientific_score still dominates.
        if not self._framings:
            return 0.0
        key = (node.metrics or {}).get("_framing_key") or ""
        if not key:
            return 0.0
        counts = Counter(self._framings)
        return 0.05 if counts.get(key, 0) * 2 <= max(counts.values()) else 0.0
```

Lever-by-lever reuse of `bfts.py`:

| BFTS lever | `bfts.py` ref | Archive treatment |
|---|---|---|
| `should_prune` total cap | `bfts.py:501` (`current_total >= cfg.max_total_nodes`) | Reused as the per-epoch `max_expansions` budget cap (`1 + max_expansions`). **Checked first, before the depth cap** — the reason cost is `O(max_expansions)` at any depth (§5.1). |
| `should_prune` depth cap | `bfts.py:503` (`node.depth >= cfg.max_depth`) | Reused verbatim with `max_depth = archive.depth` (=3) → a refine chain ends at depth 3; it is a shape knob, not the cost bound. |
| erasure clause | `bfts.py:508` (`_valid_for_frontier`) | Kept — a draft erased by selective erasure ([RQGM Architecture → Key invariants](../../concepts/rqgm_architecture.md#key-invariants), invariant 6) stays excluded. Inert unless 03/04 write the key. |
| one-child-per-`expand` | `bfts.py:643` (`directions[:1]`) | Preserved: `expand()` yields ≤ 1 draft placeholder; the driver re-selects the frontier after every child, passing `existing_children` — the same idiom the exploration loop uses (`bfts_loop.py:328-340`). |
| `select_best_to_expand` | `bfts.py:512` (LLM pick), `bfts.py:346` `_select_fallback` (deterministic) | **Real best-first frontier selection** over draft nodes by `_scientific_score + diversity_bonus`, seeds-first until `width` framings exist. Reuses BFTS's *deterministic* ranking shape rather than its LLM pick: the key is already a governed score (04), so an LLM re-rank buys only nondeterminism (P2) and cost. |
| `select_next_node` | `bfts.py:409` (LLM pick) | **Overridden to be LLM-free**: `expand()` yields one child, and a draft node's direction is fixed (`seed` / `refine`), so the semantic pick buys nothing. |
| `diversity_bonus` / `record_run` | `bfts.py:285` / `bfts.py:262` | Reused **contract** (+0.05 for an under-sampled key, 20-run window), re-keyed from `NodeLabel` to the draft **framing key** (§5.4.5) — every draft is `NodeLabel.DRAFT`, so the label carries no signal here. |
| `_scientific_score` ranking | `verified_context.py:20` | Reused unchanged — both for frontier ranking (above) and for best-belief (§5.3, §5.5). |

### 5.3 The archive driver (mini-loop at the paper entry)

`PaperArchiveRuntime` (built by [01](01_paper_execution_mode.md) at
`projects.py`) owns a small archive-building loop that reuses the
`SearchStrategy` + `NodeExecutor` Protocols. It is **not** the exploration
`_run_loop`; it is a bounded driver that produces the winning `full_paper.tex`,
which is then handed to the existing linear stages ([07](07_claim_gate_handoff_and_evaluation.md)
owns the handoff boundary).

```python
# planned: ari-core/ari/rqgm/paper_runtime.py :: PaperArchiveRuntime.run_archive
def run_archive(self, best_node, all_nodes, experiment) -> Path:
    """One paper EPOCH = one archive round (Task 01 owns the boundary that
    follows it and re-enters this method under the adopted prompts)."""
    root  = self._make_paper_root(best_node, all_nodes)   # depth-0 task node
    strat = PaperArchiveStrategy(self.cfg.rqgm.paper.archive, root_task=root)
    execu = PaperDraftExecutor(self.mcp_paper, reviewer=self.paper_reviewer)   # 03/04
    archive: list[Node] = []
    frontier: list[Node] = [root]
    while frontier:
        # Best-first over the WHOLE frontier, not a fixed schedule — mirrors the
        # exploration loop's select -> prune -> expand order (bfts_loop.py:328-340).
        parent = strat.select_best_to_expand(frontier, experiment["goal"], self.memory)
        if strat.should_prune(parent, current_total=1 + len(archive)):
            frontier.remove(parent)                     # depth / budget / erasure
            continue
        children = strat.expand(parent, existing_children=archive)   # ≤ 1 per call
        if not children:                                # fan-out full or budget spent
            frontier.remove(parent)
            continue
        cand = strat.select_next_node(children, experiment["goal"], self.memory)
        cand = execu.run(cand, experiment)              # ONE skill call (§5.4)
        strat.record_run(cand)
        archive.append(cand)
        frontier.append(cand)                           # a refined draft is expandable
        self._append_archive_record(cand)               # paper_draft_archive.jsonl
    best = select_best_node(archive)                    # best-belief, reused verbatim
    return self._finalize_best(best)                    # lazy compile (§5.5)
```

`_make_paper_root` builds a synthetic depth-0 `Node` wrapping `best_node`
(`select_best_node(all_nodes)`, already computed at `projects.py:169`); it carries
the frozen paper-task inputs (paths to `verified_context.json`, `science_data.json`,
`figures_manifest.json`, `related_refs.json`) but is **not itself a draft** and is
never scored — which is why `select_best_to_expand` ranks it by the seeds-first
rule (§5.2) rather than by a `_scientific_score` it does not have.

### 5.4 `PaperDraftExecutor` — the draft NodeExecutor over `ari-skill-paper`

`PaperDraftExecutor` satisfies `NodeExecutor` (`run(node, experiment) -> Node`) and
wraps the paper subprocess as the "hands", exactly as coding skills are the hands
for exploration nodes. It executes **one node** — a seed at depth 1 or a refinement
of its parent draft at depth ≥ 2 — with exactly **one** generative skill call, and
writes the reviewer score onto `node.metrics["_scientific_score"]`. The refine
*loop* lives in the tree (the driver's frontier, §5.3), not inside the executor.

```python
# planned: ari-core/ari/rqgm/paper_draft_executor.py  (satisfies NodeExecutor)
class PaperDraftExecutor:
    def __init__(self, mcp_paper, *, reviewer):
        self.mcp = mcp_paper
        self.reviewer = reviewer          # governed paper_reviewer oracle (03/04)

    def run(self, node: Node, experiment: dict) -> Node:
        if node.original_direction == "seed":
            # SEED (depth 1) — write_paper_iterative into a per-node .tex path.
            # §5.4.5 assignment rule over the FROZEN active writer set: 03 owns the
            # population, this task owns only the assignment.
            i = self._seed_index(node)                     # creation order of this seed
            hashes = experiment["writer_prompt_hashes"]    # n >= 1, frozen this epoch
            framing = hashes[i % len(hashes)]              # -> _framing_key (§5.2)
            tex = self._tex_path(node)    # {ckpt}/archive/{node.id}/full_paper.tex
            self.mcp.call("write_paper_iterative",
                          verified_context_json=experiment["verified_context_json"],
                          science_data_json=experiment["science_data_json"],
                          figures_manifest_json=experiment["figures_manifest_json"],
                          refs_json=experiment["refs_json"],
                          nodes_json_path=experiment["nodes_json_path"],
                          # writer prompt variant + decode seed => candidate diversity
                          author_name=experiment.get("author_name", ""))
            anchors = True
        else:
            # REFINE (depth >= 2) — ONE paper_refine against the PARENT draft's .tex.
            # The parent is resolved from the archive, so the NodeExecutor signature
            # is untouched (read_paper_draft_archive, §7).
            parent = self._archive_record(node.parent_id)
            review = self.reviewer.review(parent["tex_path"])   # suggested_revisions
            out = self.mcp.call("paper_refine", tex_path=parent["tex_path"],
                                suggested_revisions_json=review.suggested_revisions_json)
            tex, anchors = out["latex_path"], out["anchors_preserved"]
            framing = parent["writer_prompt_hash"]         # a refinement keeps its framing

        score = self.reviewer.score(tex)                   # TEXT-only, no compile
        node.artifacts = [tex]
        node.has_real_data = True                          # verified-context grounded
        node.metrics = {**(node.metrics or {}),
                        "_scientific_score": score,        # frontier + best-belief key
                        "_framing_key": framing}           # diversity_bonus key (§5.2)
        self._record(node, kind=node.original_direction, refine_pass=node.depth - 1,
                     tex=tex, score=score, anchors_preserved=anchors)
        return node
```

Key substrate decisions:

1. **`write_paper_iterative` seeds; `paper_refine` refines — one call per node.**
   These are the only two generative skill calls, and a node makes exactly one of
   them, so the per-epoch node budget (`max_expansions`, §6.2) *is* the skill-call
   budget. `review_compiled_paper` is **not** the scorer (the governed
   `paper_reviewer` is), and `compile_paper` runs at most once (§5.5).
2. **The reviewer is an injected oracle.** `PaperDraftExecutor` depends on a
   `reviewer` object exposing `score(tex_path) -> float` and
   `review(tex_path) -> suggested_revisions`. **What** the score means, the prompt,
   its evolution, and the anchor utility are 03/04 — the substrate is testable with
   a stub scorer (§9, Risk **R2**).
3. **Delta refine, not rewrite.** `paper_refine`'s non-destructive contract
   (`server.py:2468`) keeps every `% CLAIM` anchor alive to the hard gate and
   returns the paper unchanged when there is nothing actionable — so a bounded
   `rounds`-pass loop cannot corrupt claim provenance.
4. **Refine passes ARE tree depth.** A `paper_refine` pass is a **child node** of
   the draft it refines (`parent_id` / `depth + 1` / `ancestor_ids`), not a lineage
   column of a depth-1 sibling — this is why `archive.depth = 3` while
   `refine_rounds = 2` (a seed plus a two-deep chain). Making them nodes is what
   puts them under `should_prune`, under the `_valid_for_frontier` erasure clause,
   and in front of `select_best_to_expand`, so the next refinement lands on the
   best draft in the *whole* tree rather than on a fixed per-candidate schedule
   (§5.1). The archive record (§6.1) is the **projection** of that edge, and it is
   where the per-epoch draft versioning of Q-49 is resolved (drafts are archive
   records with content hashes, not overwrites of a single `full_paper.tex`).
5. **Seed diversity is deterministic (P2).** Candidate `i` is assigned
   `(writer_prompt_hash = active_writer_prompts[i % n], decode_seed = base_seed + i)`,
   where the frozen active writer set comes from 03 (`n ≥ 1`; when `n == 1`, or under
   the degraded on-ramp, diversity is decode-seed only). The assignment is recorded
   in `paper_draft_archive.jsonl` for reproducibility; the prompt **population** is
   03's, the **assignment rule** is this task's. The assigned `writer_prompt_hash`
   is also the node's `_framing_key` — the key `diversity_bonus` counts over (§5.2)
   — and a refine child **inherits its parent's framing**, so deepening one lineage
   costs that framing its diversity bonus and the frontier tilts toward an
   under-sampled framing on the next tie.

   **The seed is SENT, not just recorded (recorded 2026-07-17).** `decode_seed` was computed
   (`paper_draft_executor.py`) and written into every archive record, but never passed to the
   generator: `write_paper_iterative` had no seed parameter at all. With `n == 1` by design
   (03:512) the writer-prompt lever is inert too, so the shipped default (`rounds: 2`, `width: 4`)
   produced **1 distinct `tex_sha256` across all 8 seeds** — R1's "K near-identical copies" collapse
   was the shipped behaviour, while every record advertised a distinct seed (1000, 1001, …) nothing
   honoured. A consumer auditing reproducibility or diagnosing diversity collapse was told each
   draft was decoded under its own seed; none was. Now: `write_paper_iterative` / `paper_refine`
   take `decode_seed: int = 0` and thread it into their litellm payloads (`if decode_seed: _kw["seed"]
   = int(decode_seed)`), and the executor passes the seed it records. A refine child decodes under
   its **parent's** seed, as it inherits its parent's framing.

   * **Linear byte-identity holds:** `decode_seed=0` ⇒ **no `seed` key in the payload** ⇒ payloads are
     byte-identical to before the parameter existed. Linear never passes it. This is the same
     additive on-ramp shape as `writer_prompt_override=""`, and it is the only acceptable one
     (pinned by a test asserting the default and an explicit `0` both send no `seed`).
   * **Cross-process boundary respected:** `ari-skill-paper` gains a plain scalar parameter. No
     `ari.rqgm` import, no governance crosses the boundary — the skill stays the hands.
   * **Caveat — what the seed does and does not buy:** litellm `seed` is **best-effort and
     provider-dependent**. It reliably delivers R1's *diversity* (distinct seeds ⇒ distinct samples,
     which is the mitigation §5.4.5/R1 actually names) but does **not** guarantee bit-exact
     reproducibility on every backend. The archive's determinism claims (§8) rest on the recorded
     content hashes, not on replaying a seed through a remote model.
   * **R1's collapse detector — LANDED (2026-07-17).** Because the seed is best-effort, a backend
     that ignores it collapses the archive to K copies of one draft **while every record still
     advertises a distinct `decode_seed`** — the failure R1 names, made invisible by the very field
     that is supposed to evidence diversity. `write_paper_draft_record` (`paper_archive.py`) now
     WARNs when an incoming `kind == "seed"` record's `tex_sha256` matches a seed already in the
     archive, naming both node ids, both seeds, and the shared hash. Observability only: it never
     raises and never blocks the write (a duplicate draft is legal — the point is that it is no
     longer *silent*). This closes R1's second half; the first half is the seed being sent at all,
     above.
   * **Residual — `_litellm_caller` takes no seed (recorded 2026-07-17).** The four *generation*
     payloads are threaded and gated on non-zero, so R1's draft-diversity requirement is met.
     `_litellm_caller` (`ari-skill-paper/src/server.py`) serves `review_compiled_paper`, not the
     draft-generation path, so its lack of a seed does not affect draft diversity — it would matter
     only for doc [07](07_claim_gate_handoff_and_evaluation.md) §5.5's pinned panel (`seed: 41`),
     whose runner is itself unlanded (07 §11.1). Deliberately left: threading a seed there now
     would be an unused parameter on an unbuilt path.

### 5.5 Lazy compile

In the linear pipeline the `render_paper` stage (`config/workflow.yaml:337`,
`compile_paper`) compiles `full_paper.tex → full_paper.pdf` once. Compiling every
archive candidate (`K + K·refine_rounds` `.tex` files) would be wasteful and is
unnecessary because scoring reads text only:

- **Scoring needs no compile.** `review_compiled_paper`'s independence contract
  already "evaluates paper text only" (`config/workflow.yaml:267`); the governed
  `paper_reviewer` scores the `.tex` source. So the whole archive is scored with
  **zero** compiles.
- **Exactly one compile, deferred to the winner.** After `select_best_node` picks
  the best-belief draft, `_finalize_best` compiles **only that draft**, and only if
  its score clears `rqgm.paper.archive.compile_threshold`:

```python
# planned: ari-core/ari/rqgm/paper_runtime.py :: PaperArchiveRuntime._finalize_best
def _finalize_best(self, best: Node) -> Path:
    tex = Path(best.artifacts[0])
    score = (best.metrics or {}).get("_scientific_score", 0.0)
    threshold = float(self.cfg.rqgm.paper.archive.compile_threshold)   # default 0.0
    self._mark_best_belief(best.id)                     # is_best_belief=True in jsonl
    if score >= threshold:
        self.mcp.call("compile_paper", tex_dir=str(tex.parent), main_file=tex.name)
        self._mark_compiled(best.id)
    # Copy the winner to the canonical path the existing stages consume.
    shutil.copyfile(tex, self.ckpt / "full_paper.tex")   # handoff surface (Task 07)
    return self.ckpt / "full_paper.tex"
```

Decision: **`compile_threshold` defaults to `0.0`** — the best-belief draft always
compiles, so the archive's compile count is exactly **1**, i.e. identical to the
linear pipeline's single `render_paper` compile. A positive threshold is available
for the degraded/cost-sensitive on-ramp (below-threshold winner → skip compile, let
the existing linear `render_paper` stage compile downstream — never more than one
compile either way). `compile_threshold` is a **new knob under the existing
`rqgm.paper.archive` block** introduced by this task; it does not rename or vary any
canonical name.

### 5.6 Degraded on-ramp (best-of-N, no co-evolution)

When `rqgm.paper.prompt_evolution.enabled=false` (the cheap on-ramp, default
`true`), there is **no** writer/reviewer co-evolution: all `K` seeds use the single
founding `paper_writer` prompt and the founding `paper_reviewer`, and the archive is
pure reviewed best-of-N. **The search substrate is byte-identical** — the same
`PaperArchiveStrategy` and `PaperDraftExecutor` run; only the active prompt set is
frozen-and-single (seed diversity degrades to decode-seed only, §5.4.5). This is why
the substrate is designed prompt-agnostic: the on-ramp is a configuration of the
prompt population (owned by 03/06), not a different search engine.

## 6. Data structures / schema changes

### 6.1 `paper_draft_archive.jsonl` (new checkpoint-root file)

The draft population: one JSON line per archive **node** (a seed, or a refine child
— §5.4 decision 4), append-only, byte-fixed (`ensure_ascii=False`, one compact
object per line). This is the archive that resolves Q-49's per-epoch
draft-versioning half — every draft is a content-hashed record, never an in-place
overwrite of `full_paper.tex`.

```json
{
  "schema_version": 1,
  "draft_id": "draft_0.r1",
  "node_id": "draft_0.r1",
  "kind": "refine",
  "parent_draft_id": "draft_0",
  "refine_pass": 1,
  "tex_path": "archive/draft_0/full_paper.r1.tex",
  "tex_sha256": "<hash of the .tex bytes; drafts are versioned, not overwritten>",
  "writer_prompt_hash": "<active paper_writer hash for this seed (from Task 03)>",
  "reviewer_prompt_hash": "<active paper_reviewer hash (from Task 03)>",
  "review_score": 0.71,
  "suggested_revisions_ref": "archive/draft_0/review.r1.json",
  "anchors_preserved": true,
  "decode_seed": 1001,
  "epoch_id": "epoch_000",
  "is_best_belief": false,
  "compiled": false,
  "created_at": "<iso8601, metadata only, never hashed>"
}
```

- `kind` ∈ `{seed, refine}` — `seed` at depth 1 (`parent_draft_id = null`,
  `refine_pass = 0`), `refine` at depth ≥ 2 with `parent_draft_id` = the parent
  draft node's id and `refine_pass = node.depth - 1`. Because every record **is** a
  node (§5.4 decision 4), `draft_id == node_id`; the `node_id` column is kept as the
  explicit `Node.id` cross-reference, and the lineage columns are a *projection* of
  the tree edge (`Node.parent_id` / `ancestor_ids`), never a substitute for it.
- `review_score` is the `paper_reviewer` composite (the same value written to
  `node.metrics["_scientific_score"]`); its **meaning/policy** is 04's, the **field**
  is this task's.
- `writer_prompt_hash` / `reviewer_prompt_hash` / `epoch_id` are **provenance only**
  here — 03 writes them, this schema reserves the columns so the archive is a
  complete audit of which frozen prompts produced each draft.
- `is_best_belief` / `compiled` are set by `_finalize_best` (§5.5) — exactly one
  record has `is_best_belief=true`; `compiled=true` implies it cleared
  `compile_threshold`.

### 6.2 `rqgm.paper.archive` config knobs (typed, in `defaults.yaml`)

```yaml
# ari-core/ari/configs/defaults.yaml  (under the existing rqgm: block, line 15).
# Inert unless the effective paper mode is rqgm_archive (Task 01).
rqgm:
  paper:
    archive:
      width: 4              # K seed drafts at depth 1 (root branch factor)
      refine_rounds: 2      # refine/variant children per draft (draft branch factor)
      max_expansions: 12    # PER-EPOCH node budget -> BFTS max_total_nodes (K + K*rounds)
      depth: 3              # draft-tree depth -> BFTS max_depth (§5.1)
      compile_threshold: 0.0  # min best-belief score to lazily compile (§5.5)
```

The defaults are **self-consistent per epoch**: `width + width·refine_rounds =
4 + 8 = 12 = max_expansions`, so one epoch's budget exactly funds one full archive
round (`K` seeds + `K·refine_rounds` refine expansions) with no starvation.

`max_expansions` is a **per-epoch** budget, because a paper epoch **is** one archive
round (`run_archive`, §5.3): at the default `rqgm.paper.epoch.rounds: 2`
([01](01_paper_execution_mode.md) owns the boundary and that knob) the run spends 12
expansions per round and **24 in total**, and the second round rebuilds the drafts
under the adopted writer/reviewer prompts. The identity above therefore stays exactly
true as a per-epoch statement.

The identity **sizes** the budget; it does not pin the **shape**. Where those 8
refine expansions land is the frontier's decision (§5.2): a strong seed may absorb a
depth-3 chain while a weak one is dropped after its seed. `depth: 3` costs nothing
beyond the `max_expansions` cap — `should_prune` checks the total cap before the
depth cap (`bfts.py:501-503`, §5.1), and §9 pins that the call ceiling is unchanged
when `depth` is raised. Budget-tuning rationale and the run-level (`E ×
max_expansions`) spend caps are [06](06_cost_control_and_budget.md).

### 6.3 Checkpoint registration

- `ari-core/ari/paths.py:404` — `META_FILES += {"paper_archive_state.json",
  "paper_draft_archive.jsonl"}` (alongside the already-present `rqgm_state.json` /
  `constitution.yaml`, lines 437–442), so neither is copied into node work dirs.
  The per-candidate `archive/{node_id}/*.tex` live under an `archive/` subtree (node
  work-dir-like), not at the checkpoint root.
- `ari-core/ari/orchestrator/node_report/builder.py:327` — `_INTERNAL_JSON_NAMES +=
  {"paper_archive_state.json"}` so provenance is internal, not a publishable data
  output. (`paper_draft_archive.jsonl` is `.jsonl`, already outside the JSON-output
  surface, but is META-registered.)
- `paper_archive_state.json` itself (mode provenance mirroring `rqgm_state.json`) is
  owned by [01](01_paper_execution_mode.md); this task only registers the filenames
  it writes into (`paper_draft_archive.jsonl`) and consumes the state file.

## 7. API / class changes

All new code lives in the internal `ari-core/ari/rqgm/` package (not exported via
`ari.public.*`; no public-API contract-snapshot churn — the mode costs no contract surface,
[Internal boundaries → RQGM mode boundary](../../reference/internal_boundaries.md#rqgm-mode-boundary-ari-rqgm)).

| Symbol | Location (planned) | Contract |
|---|---|---|
| `PaperArchiveStrategy` | `ari/rqgm/paper_archive.py` | Satisfies `ari.protocols.search.SearchStrategy` (all 7 methods, `@runtime_checkable`). Best-first draft **tree**: `width` seed drafts at depth 1, ≤ `refine_rounds` refine children per draft, `max_depth = archive.depth` (3); `should_prune` reuses BFTS's cutoffs in BFTS's order (total cap before depth cap, `bfts.py:501-503`); `expand` yields ≤ 1 draft placeholder per call; `select_best_to_expand` is a **real** deterministic best-first frontier selection by `_scientific_score + diversity_bonus` (seeds-first until `width` framings exist); `diversity_bonus` is **real** (framing-keyed, `bfts.py:285` contract). Owns no filesystem/prompt text. |
| `PaperDraftExecutor` | `ari/rqgm/paper_draft_executor.py` | Satisfies `ari.protocols.search.NodeExecutor` (`run(node, experiment) -> Node`). **One node, one generative call**: `write_paper_iterative` for a seed (depth 1), one `paper_refine` against the parent draft for a refine child (depth ≥ 2, parent resolved via `read_paper_draft_archive`); writes `node.metrics["_scientific_score"]` from the injected reviewer oracle and `_framing_key` for diversity; records each node to `paper_draft_archive.jsonl`. Never calls `compile_paper`. |
| `PaperArchiveRuntime.run_archive(best_node, all_nodes, experiment) -> Path` | `ari/rqgm/paper_runtime.py` ([01](01_paper_execution_mode.md) owns the class; this task owns the method) | Drives the bounded archive loop, returns the winning `full_paper.tex` path. Best-belief via `select_best_node`; lazy compile via `_finalize_best`. |
| `PaperArchiveRuntime._finalize_best(best) -> Path` | `ari/rqgm/paper_runtime.py` | Single lazy `compile_paper` gated by `compile_threshold`; marks `is_best_belief`/`compiled`; copies winner to `{ckpt}/full_paper.tex` (Task 07 handoff surface). |
| `write_paper_draft_record(ckpt, record)` / `read_paper_draft_archive(ckpt)` | `ari/rqgm/paper_archive.py` (+ append-only writer) | Absence-tolerant read (empty list when missing); best-effort append (never raises into the paper phase). |
| `RQGMPaperArchiveConfig` (typed subsection) | `ari/config/__init__.py` under `RQGMConfig` | Types `rqgm.paper.archive.{width, refine_rounds, max_expansions, depth, compile_threshold}` (extends the Task 01 `RQGMPaperArchiveConfig` skeleton, converting its `extra: allow` subsection per the parent-set Risk R3 policy). |

Changed (existing) code, all additive and gated on `PaperMode.RQGM_ARCHIVE`:

- `ari-core/ari/paths.py` — `META_FILES` += the two archive filenames (§6.3).
- `ari-core/ari/orchestrator/node_report/builder.py` — `_INTERNAL_JSON_NAMES` +=
  `paper_archive_state.json` (§6.3).
- `ari-core/ari/cli/projects.py` `paper` — inside the existing
  `if _rqgm_paper is not None:` block (line 164), when the effective paper mode is
  `rqgm_archive`, call `run_archive(...)` to produce `full_paper.tex` **before**
  `generate_paper_section` (line 190). No change to the return-tuple unpacking; the
  linear branch is untouched.
- No CLI command/flag changes; no `ari.public.*` changes; no MCP tool changes ⇒
  zero contract golden regeneration (deliberate budget decision, mirroring the
  parent set).

## 8. Migration / compatibility

Preserve-existing-behavior policy (normative):

1. **Linear default is identity.** With `paper.mode: linear` (default), or with the
   effective mode falling back to `linear` per [01](01_paper_execution_mode.md)'s
   interlock table, none of `PaperArchiveStrategy` / `PaperDraftExecutor` /
   `PaperArchiveRuntime.run_archive` is constructed or imported. `generate_paper_section`
   runs the exact existing `config/workflow.yaml` paper stages
   (`write_paper` → `link_paper_claims_draft` → `claim_evidence_hard_gate_draft` →
   `review_paper` → … → `finalize`) byte-for-byte. No `paper_draft_archive.jsonl`,
   no `paper_archive_state.json`, no `archive/` subtree — checkpoint contents are
   identical to today's, mirroring the `rqgm_state.json` absence-is-default P5
   convention.
2. **`bfts.py` is untouched.** `PaperArchiveStrategy` is a sibling `SearchStrategy`;
   the exploration `BFTS` class, its `should_prune`/`expand`/`select_*`, and the
   exploration `_run_loop` are unchanged. The archive borrows BFTS's cutoff **logic**
   by reimplementation, not by import, so a future `bfts.py` refactor cannot silently
   change archive behavior (guarded by the Protocol-conformance test, §9).
3. **The claim gate stays Layer-0.** The best-belief `.tex` is copied to the
   canonical `full_paper.tex` and handed to the **existing** claim stages unchanged;
   the deterministic hard gate is never kernel-wrapped and never evolves
   (global invariant; [07](07_claim_gate_handoff_and_evaluation.md) owns the exact
   boundary). This task never touches `ari-core/ari/pipeline/claim_gate/`.
4. **`ari-skill-paper` is not governed.** The subprocess is the draft executor's
   hands; it imports zero RQGM and keeps its own prompt copies for linear mode
   (`ari-skill-paper/src/prompts/`). The governed prompts live in ari-core (03).
5. **Additive and fail-open.** Archive-loop failures (a failed seed, a refine that
   returns unchanged, a reviewer-oracle error) log and degrade: a candidate that
   fails to seed is skipped; if the archive yields no scorable candidate, the runtime
   falls back to the linear single-draft path (the winner copy is a no-op and
   `generate_paper_section` writes `full_paper.tex` as today). No archive failure
   ever blocks the paper phase.
6. **Resume is content-hash safe.** An interrupted archive resumes from
   `paper_draft_archive.jsonl`: already-recorded nodes (matched by `tex_sha256`) are
   not regenerated. Because every record is a node (§6.1), the records **rebuild the
   tree**: `node_id` / `parent_draft_id` restore the edges, `review_score` and
   `writer_prompt_hash` restore `_scientific_score` / `_framing_key`, and the
   restored frontier hands `select_best_to_expand` the same state it had before the
   interrupt — so the resumed run continues best-first from where it stopped rather
   than from a positional cursor. Old checkpoints have no archive file and resume as
   linear (correct by construction).
7. **Config forward-compat.** `rqgm.paper.archive.*` parses today via `RQGMConfig`'s
   `extra: allow`; an old ari-core reading a new config silently ignores the block
   and runs linear — the safest failure direction.

## 9. Tests

Unit (new `ari-core/tests/test_paper_archive_search.py`, listed in
`ari-core/tests/README.md` for the readme-sync gate):

- **Topology**: `PaperArchiveStrategy` builds exactly `width` seed drafts at depth 1
  **before** any refine child (seeds-first), then expands refine children of the
  best-scoring draft down to `archive.depth` (a depth-3 node exists when one lineage
  keeps improving); `expand()` yields ≤ 1 child per call; `should_prune` retires a
  node at `depth >= archive.depth`, a parent whose fan-out cap is spent, and any
  node once `current_total >= 1 + max_expansions`; the `_valid_for_frontier=false`
  erasure clause retires an erased draft **and its refine children are never
  expanded** (the property a depth-1 star could not express).
- **Best-first frontier is real, not trivial**: given a hand-built frontier in which
  `draft_2` carries the max `_scientific_score`, `select_best_to_expand` returns
  `draft_2` — not the root, not `draft_0`; once `width` seeds exist the root is
  never returned again; two identical runs resolve ties identically (creation
  order). A regression assert that the method is **not** a constant function of the
  root.
- **`diversity_bonus` is real, not `0.0`**: it returns `0.05` for a draft whose
  `_framing_key` is at most half as frequent as the most common recently-run framing
  and `0.0` otherwise (the `bfts.py:285-310` contract), and it flips a
  `_scientific_score` tie in `select_best_to_expand` toward the under-sampled
  framing; a refine child inherits its parent's framing (§5.4.5).
- **Budget cap**: with `width=4, refine_rounds=2`, the executor issues ≤ 12
  generative skill calls **per epoch** (`write_paper_iterative` + `paper_refine`
  spies); the loop stops at `max_expansions`.
- **Cost is depth-independent (§5.1)**: the same config with `depth=5` issues the
  **same ≤ 12** calls and builds the same node count — pinning that the total cap
  (`bfts.py:501`) binds before the depth cap (`bfts.py:503`) and that no `b^d` term
  exists.
- **Best-belief reuse**: `select_best_node` picks the archive record with the max
  `metrics["_scientific_score"]`, preferring `has_real_data` — asserted against a
  hand-built archive (proves the exploration ranking key is reused verbatim).
- **Lazy compile**: `compile_paper` spy fires **exactly once** and only for the
  best-belief draft; with `compile_threshold` above the winner's score it fires
  **zero** times and the winner `.tex` still reaches the canonical path.
- **Archive schema**: `paper_draft_archive.jsonl` round-trip (write → read →
  absence-tolerant read); `tex_sha256` distinct per variant; `META_FILES` +
  `_INTERNAL_JSON_NAMES` registration asserted (pattern:
  `test_prompt_provenance.py::test_new_filenames_are_meta_files`).
- **Protocol conformance**: `isinstance(PaperArchiveStrategy(...), SearchStrategy)`
  and `isinstance(PaperDraftExecutor(...), NodeExecutor)` (`@runtime_checkable`),
  duck-typed, never `isinstance` of a concrete class.
- **Determinism (P2)**: two runs with the same seed/config produce identical
  candidate ordering, `decode_seed` assignment, and archive record order.

Regression (linear unchanged):

- `paper.mode: linear` → `generate_paper_section` executes the identical
  `config/workflow.yaml` stage sequence (stage-name spy); no `archive/` subtree, no
  `paper_draft_archive.jsonl` / `paper_archive_state.json`; `compile_paper` invoked
  by `render_paper` exactly as today; `sys.modules` contains no
  `ari.rqgm.paper_archive` / `paper_draft_executor` entry.
- Full existing ari-core suite passes untouched (CI `refactor-guards.yml`).
- Contract snapshots (`scripts/snapshot_contracts.py --surface cli/public --check`)
  stay green with no golden regeneration.

Smoke (`rqgm_archive` startup):

- Short archive (`width=2, refine_rounds=1, depth=3, max_expansions=4`, mocked
  `write_paper_iterative` / `paper_refine` / `compile_paper`, stub reviewer oracle)
  builds 2 seeds, then spends the remaining 2 expansions **best-first** on the
  frontier (a depth-3 chain on the better lineage when the stub keeps improving it;
  one refine child each when it does not), records 4 archive lines, selects the
  highest-scored draft, compiles once, and copies it to `{ckpt}/full_paper.tex`.
- Degraded on-ramp: with `rqgm.paper.prompt_evolution.enabled=false`, the identical
  substrate runs best-of-N (single writer/reviewer prompt hash across all records) —
  asserts the strategy/executor code path is unchanged.

Resume:

- Archive interrupted after 1 recorded seed → resume reads `paper_draft_archive.jsonl`,
  does **not** re-issue `write_paper_iterative` for the recorded seed (hash match),
  rebuilds the tree edges + `_scientific_score` / `_framing_key` from the records
  (§8.6), and completes the remaining nodes — producing the same node set as the
  uninterrupted run (P2).

CI placement: plain ari-core tests run by `refactor-guards.yml`; no new workflow.

## 10. Risks

- **R1 — Seed diversity collapse.** If the writer prompt and decode seed do not
  diversify, `K` candidates are near-identical and the archive degrades to `K`
  copies. *Mitigation*: deterministic `(writer_prompt_hash, decode_seed)` assignment
  (§5.4.5) plus a diversity check in `_append_archive_record` that logs when two
  seeds share a `tex_sha256`. Prompt-population diversity is [03](03_writer_reviewer_governed_roles.md)'s.
- **R2 — Reviewer-oracle coupling.** The executor scores via the governed
  `paper_reviewer` (03/04), so this task's substrate cannot be fully exercised until
  those land. *Mitigation*: the reviewer is an **injected interface**
  (`score`/`review`); all §9 unit/smoke tests run against a stub scorer, so the
  substrate is independently verifiable.
- **R3 — Double refine on handoff.** The archive already reviews/refines; the linear
  stages (`review_paper` → `paper_refine`) would refine again, doubling cost and
  possibly regressing the winner. *Mitigation*: routed to
  [07](07_claim_gate_handoff_and_evaluation.md) — the handoff enters the winner
  `.tex` at the compile/gate boundary and skips the linear write/review/refine
  stages when the archive produced the winner. This task only guarantees the winner
  `.tex` is claim-anchor-intact (via `paper_refine`'s preservation contract).
- **R4 — Lazy-compile threshold miscalibration.** A too-high `compile_threshold`
  yields a winner with no PDF. *Mitigation*: default `0.0` (always compile the
  best-belief); below-threshold winners still reach the canonical path and the
  existing `render_paper` stage compiles downstream — never zero PDFs, never > 1
  compile.
- **R5 — Budget starvation.** All `max_expansions` spent on seeds leaves no refine
  budget. *Mitigation*: the root's fan-out is capped at `width` (`_fanout_cap`,
  §5.2), so at most `K` of the per-epoch budget can ever go to seeds and the
  frontier spends the remainder on refine children; the default `12 = 4 + 8` is
  balanced (§6.2). Spend-cap tuning is [06](06_cost_control_and_budget.md).
- **R6 — Unbounded / mis-sized `max_expansions`.** The per-epoch budget — **not**
  the depth — is the only thing between the archive and unbounded spend:
  `should_prune`'s total cap (`bfts.py:501`) is what makes cost `O(max_expansions)`
  at any depth (§5.1), so an absent, zeroed, or per-epoch-raised `max_expansions`
  with no run-level ceiling is the real cost risk. *Mitigation*: the knob is
  required and typed (`RQGMPaperArchiveConfig`, §7); `should_prune` enforces
  `1 + max_expansions` as `max_total_nodes` on **every** expansion, so the cap
  cannot be bypassed by tuning `width`/`refine_rounds`/`depth`; the §9 budget test
  asserts the call ceiling holds **independently of `archive.depth`**; and the
  run-level ladder (`E × max_expansions` across `rqgm.paper.epoch.rounds`) is
  [06](06_cost_control_and_budget.md)'s to bound. Depth is not a risk — it is the
  method (§5.1).
- **R7 — BFTS-logic drift.** The archive reimplements `should_prune`'s cutoff logic;
  a future change to BFTS pruning semantics could diverge silently. *Mitigation*: the
  archive depends only on the `SearchStrategy` **Protocol**, not BFTS internals; the
  conformance + topology tests pin the archive's own cutoffs.

## 11. Completion criteria

This task is complete when all of the following hold:

1. **Archive topology fixed** — `PaperArchiveStrategy` is specified as a **best-first
   tree**: one `paper_root` (depth 0), `width` seed drafts (depth 1) and
   refine/variant children down to `archive.depth` (default 3), mapping onto
   `bfts.py` via `max_depth = archive.depth`, the one-child-per-`expand` invariant,
   and the total-count/`max_expansions` cutoff **that bounds cost at any depth**;
   with a real deterministic best-first frontier selection and a real
   framing-keyed `diversity_bonus` (§5.1, §5.2), reusing `bfts.py` logic without
   editing it.
2. **Draft executor fixed** — `PaperDraftExecutor` wraps `ari-skill-paper` with one
   generative call per node: `write_paper_iterative` for seeds, one `paper_refine`
   for a refine **child node** (refine passes are tree depth, not lineage columns),
   reviewer as injected scoring oracle, deterministic seed diversity + framing key
   (§5.4), and it never calls `compile_paper`.
3. **Best-belief selection fixed** — the winner is chosen by
   `verified_context.py:select_best_node` reused verbatim, keyed on
   `metrics["_scientific_score"]` (§5.4, §5.3).
4. **Draft archive schema fixed** — `paper_draft_archive.jsonl` fields, `kind` /
   lineage / `tex_sha256` versioning, and provenance columns are specified (§6.1),
   resolving the per-epoch draft-versioning half of Q-49 (drafts are archive records,
   not overwrites).
5. **Lazy compile fixed** — text-only scoring, single deferred `compile_paper` on the
   best-belief draft gated by `compile_threshold` (default 0.0 ⇒ exactly one compile,
   ≤ linear) (§5.5).
6. **Config + registration fixed** — `rqgm.paper.archive.{width, refine_rounds,
   max_expansions, depth, compile_threshold}` defaults (`depth: 3`) and their
   **per-epoch** self-consistency (`max_expansions` is per archive round);
   `paper_draft_archive.jsonl` registered in `META_FILES`, `paper_archive_state.json`
   in `_INTERNAL_JSON_NAMES` (§6.2, §6.3).
7. **Degraded on-ramp supported** — the same substrate serves best-of-N when
   `rqgm.paper.prompt_evolution.enabled=false`, with no code-path change (§5.6).
8. Downstream tasks consume this substrate without re-opening it: 03 plugs the
   writer/reviewer prompts into the executor's oracle, 04 defines the reviewer
   utility behind `reviewer.score`, 06 bounds `max_expansions`/compile cost, 07 owns
   the winner-`.tex` handoff (§3, R3).

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

- `PaperArchiveStrategy` and `PaperDraftExecutor` are implemented and satisfy the
  `SearchStrategy` / `NodeExecutor` Protocols (conformance test green).
- The `paper_draft_archive.jsonl` schema and the `rqgm.paper.archive` knobs are
  implemented, with `META_FILES` / `_INTERNAL_JSON_NAMES` registration.
- Lazy compile is implemented (exactly one compile of the best-belief draft; ≤ the
  linear compile count) and covered by tests.
- `paper.mode: linear` regression: the existing paper pipeline is byte-identical
  (no archive files, no `ari.rqgm.paper_archive` import, contract snapshots green).
- Both-mode smoke (linear regression + `rqgm_archive` startup + degraded on-ramp)
  and the resume test exist and pass.
- The draft-tree topology rationale (a tree bounded by `max_expansions`, not a star)
  and the lazy-compile / best-belief decisions are moved to the permanent paper-mode
  guide under `docs/`.

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

- [ ] `PaperArchiveStrategy` implemented (best-first draft tree, `bfts.py` cutoff
      reuse in `bfts.py`'s order, one-child-per-`expand`, real deterministic
      frontier selection + real framing-keyed `diversity_bonus`) and
      Protocol-conformant.
- [ ] `PaperDraftExecutor` implemented (`write_paper_iterative` seed +
      one `paper_refine` per refine **child node** + injected reviewer oracle;
      never compiles).
- [ ] Best-belief selection reuses `select_best_node` verbatim.
- [ ] `paper_draft_archive.jsonl` schema + `rqgm.paper.archive` knobs implemented;
      filenames registered in `META_FILES` / `_INTERNAL_JSON_NAMES`.
- [ ] Lazy compile implemented and gated by `compile_threshold`.
- [ ] Linear-mode byte-identity confirmed (no archive files/imports; snapshots green).
- [ ] Smoke (both modes + degraded on-ramp) and resume tests pass.
- [ ] Draft-tree topology (+ its `max_expansions` cost bound) and lazy-compile
      decisions published in the permanent paper-mode guide; the winner-`.tex`
      handoff explicitly handed to Task 07.
