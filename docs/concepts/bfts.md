---
sources:
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-05-26
---

# BFTS Algorithm

ARI implements true Best-First Tree Search with a two-pool design:

- **`pending`**: nodes ready to run (already expanded from a parent)
- **`frontier`**: completed nodes not yet expanded

The two pools and the transitions between them (the dotted self-loop is the
*persistent frontier* — a completed node stays available for re-expansion):

```mermaid
stateDiagram-v2
    direction LR
    [*] --> pending: root created / expand() adds one child
    pending --> running: select_next_nodes (≤ ARI_PARALLEL per batch)
    running --> frontier: completed (success OR failure)
    frontier --> frontier: persistent — stays re-expandable
    frontier --> pending: select best (score + diversity bonus) → expand one child
    frontier --> retired: Rule A (child outscores parent) OR Rule B (max_expansions_per_node reached)
    pending --> pruned: should_prune (total ≥ max_total_nodes / depth ≥ max_depth / _sterile)
    retired --> [*]
    pruned --> [*]
```

A failed node is **not** retried: it still enters the frontier and is expanded
into a `debug` child (the `frontier → pending` edge), so recovery happens as a
new node rather than a re-execution.

```python
def bfts(experiment, config):
    root = Node(experiment, depth=0)
    pending = [root]      # nodes ready to execute
    frontier = []         # completed nodes awaiting expansion
    all_nodes = [root]

    while len(all_nodes) < config.max_total_nodes:

        # --- BFTS STEP 1: expand the best frontier node ---
        # LLM reads metrics of all completed nodes and selects
        # the most promising one to expand (one child per call)
        while frontier and len(pending) < max_parallel:
            best = llm_select_best_to_expand(frontier)  # by _scientific_score + diversity_bonus
            # Frontier nodes stay available for re-expansion
            child = llm_propose_one_direction(best, existing_children=best.children)
            pending.append(child)
            all_nodes.append(child)

        # --- BFTS STEP 2: run a batch of pending nodes ---
        batch = llm_select_next_nodes(pending, max_parallel)
        record_run(batch)  # track label diversity
        results = parallel_run(batch)

        for node in results:
            memory.write(node.eval_summary)   # save to ancestor-chain memory
            frontier.append(node)             # will expand when selected

    return max(all_nodes, key=lambda n: n.metrics.get("_scientific_score", 0))
```

Key properties:
- **Single-child expansion**: `expand()` generates exactly one child per call with rich context (sibling scores, ancestor chain, tree diversity metrics, existing children) to avoid duplicates. The prompt also surfaces the current depth/`max_depth` and the remaining node budget so the planner can pace itself (v0.7.2, I-4).
- **Persistent frontier**: completed nodes stay in frontier after expansion, available for re-expansion with `_touched_this_round` / `_failed_this_round` tracking. A frontier node is **retired** when either (Rule A) its child outscores it on `_scientific_score`, or (Rule B) it has been expanded `max_expansions_per_node` times (v0.7.2, B-6).
- **`should_prune` predicate**: hard cutoffs only — `current_total >= max_total_nodes` (B-1), `depth >= max_depth` (B-2, previously dead config), or `metrics._sterile is True` (B-4). LLM judgement happens elsewhere.
- **Diversity bonus**: `+0.05` for underrepresented labels (last 20 runs tracked) when `my_count * 2 ≤ max_count` (I-2); applied in *both* selector fallbacks (I-3 / L-3) and in `select_next_node` LLM prompts.
- **Score calibration**: evaluator injects recent score history into prompts to prevent score collapse (all scores clustering around the same value)
- **No retry**: failed nodes produce `debug` children via `expand()`, not re-executions. ARI does not maintain a `retry_count` field for selection purposes (B-3).
- **Strict budget**: `len(all_nodes) < max_total_nodes` prevents overshoot. The live count is the single source of truth — there is no separate `BFTS.total_nodes` counter (B-1).
- **`record_run` after completion**: the run-loop calls `bfts.record_run(result)` after `future.result()` returns (success or failure), so the diversity bonus reflects nodes that actually executed (I-7).
- **`generate_ideas` called once**: suppressed after root node to prevent looping

### Node Labels

| Label | Meaning |
|-------|---------|
| `draft` | New implementation from scratch |
| `improve` | Tune parent's parameters or algorithm |
| `debug` | Fix parent's failure |
| `ablation` | Remove one component to measure its impact |
| `validation` | Re-run parent with different conditions |
| *(custom)* | Unknown labels fall back to `other`; `raw_label` preserves the original string |

---
