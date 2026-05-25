---
sources:
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-05-25
---

# BFTS 算法

ARI 实现了真正的最佳优先树搜索，采用双池设计：

- **`pending`**：准备运行的节点（已从父节点扩展）
- **`frontier`**：已完成但尚未扩展的节点

```python
def bfts(experiment, config):
    root = Node(experiment, depth=0)
    pending = [root]      # nodes ready to execute
    frontier = []         # completed nodes awaiting expansion
    all_nodes = [root]

    while len(all_nodes) < config.max_total_nodes:

        # --- BFTS STEP 1: expand the best frontier node ---
        # LLM reads metrics of all completed nodes and selects
        # the most promising one to expand (not all at once)
        while frontier and len(pending) < max_parallel:
            best = llm_select_best_to_expand(frontier)  # by _scientific_score
            frontier.remove(best)
            children = llm_propose_directions(best)     # improve/ablation/validation
            pending.extend(children)
            all_nodes.extend(children)

        # --- BFTS STEP 2: run a batch of pending nodes ---
        batch = llm_select_next_nodes(pending, max_parallel)
        results = parallel_run(batch)

        for node in results:
            memory.write(node.eval_summary)   # save to ancestor-chain memory
            if node.status == SUCCESS:
                frontier.append(node)         # will expand when selected
            else:
                frontier.append(node)         # failed → expand with "debug" children

    return max(all_nodes, key=lambda n: n.metrics.get("_scientific_score", 0))
```

关键特性：
- **惰性扩展**：已完成的节点不会立即扩展，而是等到 LLM 选择它 — 低分节点可能无限期等待
- **不重试**：失败的节点通过 `expand()` 产生 `debug` 子节点，而非重新执行
- **严格预算**：`len(all_nodes) < max_total_nodes` 防止超额
- **`generate_ideas` 仅调用一次**：在根节点之后被抑制以防止循环

### 节点标签

| 标签 | 含义 |
|------|------|
| `draft` | 从头开始的新实现 |
| `improve` | 调优父节点的参数或算法 |
| `debug` | 修复父节点的失败 |
| `ablation` | 移除一个组件以衡量其影响 |
| `validation` | 在不同条件下重新运行父节点 |

---
