---
sources:
  - path: ari-skill-memory
    role: implementation
  - path: ari-core/ari/pipeline/verified_context.py
    role: implementation
  - path: ari-core/ari/config
    role: config
last_verified: 2026-06-04
---

# ARI 可验证研究记忆

如何组织 ARI 的记忆，使实验结果、失败和流程做到**有类型、以制品接地、可验证** ——
而不仅仅是自由文本的自然语言日志。本文是其持久的设计记录（产出它的工作计划书已退役）；
关于 ancestor-scoped 的检索基线，另见 [memory.md](memory.md)。

## 为什么

ancestor-scoped 的 Letta 记忆（memory.md）提供分支隔离，但存储的多为自由文本。
研究自动化系统还需要：

- 追踪一个结果依赖于哪个日志 / 代码 / 输出文件；
- 复用失败案例、修复和性能证据；
- 绝不把未接地的主张当作论文论断；
- 区分已复现的结果与未验证的结果。

可验证研究记忆在 Letta（作为低层归档／检索后端保留）**之上**增加一个有类型、
以证据接地的层，而不让 Letta 成为知识的拥有者。

## 原则

1. **记忆是索引，而非证据** —— 记忆指向证据（制品／指标／命令／日志），其本身不是主张。
2. **单一真实来源 = `node_report.json`** —— 溯源信息（指标、带 sha256 的制品、build/run
   命令、files_changed、硬件、concerns/hints）存放于此。有类型的记忆只携带一个
   `node_report_ref` 指针加一段可检索的 `text`，并不复制 node_report 的字段。
3. **分支隔离** —— 节点只读取其祖先的记忆（绝不读兄弟节点／其他检查点）。
4. **Copy-on-Write、仅追加** —— 节点只写自己的 `node_id`；过往条目保持逐字节稳定。
   状态变化（如可复现性）以新事件追加，绝不就地修改。
5. **有类型** —— 每个条目都有一个 `kind`（observation, experiment_result,
   failure_case, procedure, reflection, artifact_summary, paper_claim,
   reproducibility_event）。
6. **以制品接地的生成** —— 论文／图表的主张只依赖有制品支撑（最好已复现）的记忆；
   未接地的 reflection 可辅助探索，但绝不进入论文正文。
7. **可复现性感知** —— 可复现性状态是仅追加事件，在读取时按目标折叠为最新值。
8. **由循环编排** —— 记忆的读写由确定性的循环／流水线钩子完成。LLM 不会主动拉取记忆
   （实测：智能体从不调用 recall 工具；recall 是启动时一次性的预置种子）。智能体自身的
   `add_memory` 是可选的，从不依赖它。
9. **Letta 是低层后端** —— 仅负责归档插入／语义检索／按检查点的集合；什么／如何／何处／
   接地／验证均由 ARI 拥有。

## 架构

```
node end ─▶ consolidate_node_memory  (node_report → typed experiment_result /
            (bfts_loop hook)           failure_case / reflection, with provenance)
                  ▼
          typed research-memory store (Letta archival, ancestor-scoped, CoW)
                  ▼
paper pipeline ─▶ write_verified_context (best node's root→best lineage)
                  → {checkpoint}/verified_context.json
                  ▼
write_paper ─▶ reads the path directly, render_grounded_block → system prompt
              → quantitative claims grounded only on verified, artifact-backed
                (rerun_passed first) results.
```

- **Working context（Phase 0）**：在节点开始时，循环确定性地注入实验核心
  （goal/metric/hardware）＋祖先的 `result_summary` 结论（取代旧的聚合截断式语义
  转储）。这是 *继承* 路径，与下方的可验证层相互独立。
- **有类型索引／verified context**：上述的可验证层，由 `consolidation_enabled()`
  （默认 ON）门控。

## 组件

- `ari-skill-memory`：`schemas.py`（有类型记录）、`provenance.py`（来自 node_report 的
  sha256 引用）、`audit.py`（claim↔artifact 完整性）、`writer.py` / `retriever.py`
  （有类型写入＋按 kind/scope/artifact 过滤的读取＋可复现性折叠）、`consolidation.py`
  （node_report → specs）、`context_builder.py`（verified context）。以 MCP 工具
  （`add_experiment_result`, `search_research_memory`, `get_verified_context`,
  `consolidate_node_memory`, `audit_memory`, …）暴露，全部由钩子调用。
- `ari-core`：`pipeline/verified_context.py`（best-node lineage 作用域＋grounded-block
  渲染）、`bfts_loop` 的节点结束 consolidation 钩子，以及 write_paper 处的消费。

## 门控与开销

`ARI_MEMORY_CONSOLIDATE`（默认 **ON**；以 `0`/`false`/`no`/`off` 禁用，单一真实来源为
`ari.config.consolidation_enabled`）同时控制节点结束的 consolidation 与论文的
verified-context 构建。开销：在已有的 `result_summary` 之上，每个节点约 1～2 次有类型
写入（各自做 embedding）；实测为线性且可接受。

## 验证（真实环境）

- Phase 0 的 working-context 注入：在真实 BFTS 运行中验证（实验核心＋完整的祖先
  `result_summary`、兄弟隔离）。
- Consolidation：真实环境验证 —— 节点结束钩子写入了带溯源的 `experiment_result`
  （6 个 sha256 制品引用＋node_report_ref），并为失败节点写入 `failure_case`，
  且未破坏循环。
- Verified context → 论文接地：在真实数据上端到端验证，并经由论文流水线接线验证
  （`verified_context_json` 以路径而非通过 `load_inputs` 传入，因此 write_paper 阶段／
  claim 阶段的拓扑不受扰动）。

## 有意的非目标

- **BFTS 规划器的有类型注入**（把祖先的 failure_case/procedure 喂给 `expand()` 以避免
  重复失败）已对照证据门控进行评估并**有意未实现** —— 一次真实运行实测失败复发率为 0%
  （见 `ari-core/REQUIREMENTS.md`）。仅当未来运行显示高复发率时才重新评估。
- Letta 自我编辑、跨实验的全局记忆、学习型记忆策略 —— 不在范围内。
