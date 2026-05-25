---
sources:
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
  - path: ari-skill-memory
    role: implementation
last_verified: 2026-05-25
---

# 记忆架构

每个节点仅从其祖先链中读取：

```
root ──▶ memory["root"]
  ├─ node_A ──▶ memory["node_A"]
  │    ├─ node_A1  (读取：root + node_A)
  │    └─ node_A2  (读取：root + node_A，不读取 node_A1)
  └─ node_B  (仅读取 root，不读取 node_A 分支)
```

`search_memory` 以 `query = node.eval_summary` 调用。在 Letta 0.16.7 上，本技能调用 `passages.search`（`GET /archival-memory/search`，`embed_query=True`），以 `top_k = max(letta_overfetch, limit*40)` 拉取，再按 `ancestor_ids` / `ari_checkpoint` / `kind == "node_scope"` 做本地 post-filter。**服务端返回的 embedding 排序得以保留**，子节点按其查询的语义相关度从高到低看到祖先条目。被刻意避开的 `passages.list(search=q)` 路由实际上是 SQL substring filter（`LOWER(text) LIKE LOWER(%q%)`），长的自然语言查询无法与 `RESULT SUMMARY metrics=[...]` 这类结构化条目子串匹配，会静默返回 0 条 —— 详见 `ari-skill-memory/src/ari_skill_memory/backends/letta_backend.py` 的 live verification。

### v0.6.0：基于 Letta

两个层级共存于每个检查点的同一个 Letta 代理中：

- `ari_node_<ckpt_hash>` — 节点作用域的 archival 集合，使用上述祖先作用域元数据过滤器。
- `ari_react_<ckpt_hash>` — 每个检查点的扁平 ReAct 轨迹（`LettaMemoryClient`，不做祖先过滤）。

代理还会向核心记忆块（`persona` + `human` + `ari_context`）种入实验目标、主要指标和硬件规格 ── 时机为首个节点的 `generate_ideas` 完成时（即 `primary_metric` 被确定的时刻）。技能可通过 `get_experiment_context()` 读取，无需付出搜索成本；在 seed 执行之前调用会返回 `{}`。

**Copy-on-Write**：写端工具拒绝 `node_id` ≠ `$ARI_CURRENT_NODE_ID` 的写入，因此祖先条目在兄弟节点之间保持字节稳定；出于同样的原因，Letta 自编辑默认禁用。

**可移植性**：每个检查点都携带 `memory_backup.jsonl.gz` 快照，在 `ari resume` 时若目标 Letta 为空将自动恢复 ── 让 `cp -r checkpoints/foo /elsewhere/` + `ari resume` 持续可用。

---
