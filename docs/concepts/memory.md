---
sources:
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
  - path: ari-skill-memory
    role: implementation
last_verified: 2026-05-25
---

# Memory Architecture

Each node reads only from its ancestor chain:

```
root ──▶ memory["root"]
  ├─ node_A ──▶ memory["node_A"]
  │    ├─ node_A1  (reads: root + node_A)
  │    └─ node_A2  (reads: root + node_A, NOT node_A1)
  └─ node_B  (reads: root only, NOT node_A branch)
```

`search_memory` is invoked with `query = node.eval_summary` (a one-
sentence direction text). On Letta 0.16.7 the skill calls
`passages.search` (`GET /archival-memory/search`, `embed_query=True`)
with `top_k = max(letta_overfetch, limit*40)`, then post-filters the
ranked window by `ancestor_ids`, `ari_checkpoint`, and
`kind == "node_scope"` locally. The embedding-rank order returned by
the server is preserved — children see entries most relevant to
their query first. The deliberately-skipped sibling endpoint
`passages.list(search=q)` is **not** semantic — it routes to a SQL
substring filter (`LOWER(text) LIKE LOWER(%q%)`) which silently
returns 0 against long natural-language queries on structured
passages like `RESULT SUMMARY metrics=[...]`. See
`ari-skill-memory/src/ari_skill_memory/backends/letta_backend.py`
for the live verification.

### v0.6.0: backed by Letta

Both layers live in the same per-checkpoint Letta agent:

- `ari_node_<ckpt_hash>` — node-scope archival collection with the
  ancestor-scope metadata filter above.
- `ari_react_<ckpt_hash>` — flat per-checkpoint ReAct trace
  (`LettaMemoryClient`, not ancestor-filtered).

The agent also seeds a core-memory block (`persona` + `human` +
`ari_context`) with experiment goal, primary metric, and hardware spec
once the first node's `generate_ideas` completes (the point at which
`primary_metric` is known). Skills can read it via
`get_experiment_context()` without paying for a search; the call
returns `{}` until that seed runs.

**Copy-on-Write**: write-side tools reject `node_id` ≠
`$ARI_CURRENT_NODE_ID` so ancestor entries are byte-stable across
siblings; Letta self-edit is disabled by default for the same reason.

**Portability**: each checkpoint carries a
`memory_backup.jsonl.gz` snapshot that is restored automatically on
`ari resume` when the target Letta is empty — keeping
`cp -r checkpoints/foo /elsewhere/` + `ari resume` working.

---
