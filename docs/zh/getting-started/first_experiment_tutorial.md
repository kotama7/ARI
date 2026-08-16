---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/agent/loop.py
    role: implementation
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-core/ari/pipeline/claim_gate/policy.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-16
---

# 你的第一个实验，端到端

[快速入门](quickstart.md) 展示了*该按哪些按钮*。本教程将一个小型实验完整地走查一遍 —— 目标 → 假说 → 搜索 →
论文 → 复现 —— 并解释*为什么*每个阶段都存在。读完后你将认得 ARI 在检查点中留下的每一个文件，并知道当你想深入了解时该打开哪份文档。

我们刻意使用一个简单、与领域无关的目标，使机制保持清晰：**让一个稠密矩阵乘法例程在本机上更快。** ARI 并未为此专门优化 —— 同一条管线适用于任何可测量的目标；领域选择全部由 LLM 在运行时做出。

> **开始之前：** 完成 [快速入门](quickstart.md)，使仪表盘在 <http://localhost:8765> 上运行且已配置好一个模型。

## 1. 陈述目标（`experiment.md`）

实验文件就是纯 Markdown。最低限度是几行研究目标 —— 无需代码：

```markdown
# Goal
Improve the throughput (GFLOP/s) of a dense single-precision matrix
multiplication on the available hardware. Compare against a naive triple loop.
```

这就够了。你可以稍后添加 `## Provided Files` 或约束条件（参见
[编写实验文件](../guides/experiment_file.md)），但具体细节由 ARI 自己填补。

## 2. 启动

在仪表盘中，使用 **New Experiment** → 让首次运行保持小规模（深度 3、
5–10 个节点、2–4 个 worker）。或从 CLI：

```bash
ari run experiment.md
```

一个检查点目录会出现在 `workspace/checkpoints/<timestamp>_<slug>/`。下面的一切都会落到那里。

## 3. 调研与假说（根节点）

第一个节点按顺序完成立项工作：

1. **`generate_ideas`** —— 一场 VirSci 多代理审议就该问题展开辩论并写出
   `idea.json`：一个假说、主要指标，以及一份实验计划。它在整个运行中只运行**一次**，
   并**设定**主要指标（这里是 GFLOP/s）及其方向（越高越好）。
2. **`make_metric_spec`** —— *从*该 idea 的 `primary_metric` 导出具体的成功指标（而非凭空猜测）。
3. **`survey`** —— 搜索文献，使最终的论文能够引用真实的参考文献。

打开 **想法** 页面阅读它的提议。

## 4. 搜索（BFTS）

现在 ARI 开始探索。它不是一个线性脚本 —— 它是一个
[最佳优先树搜索](../concepts/bfts.md)：

- 每个**节点**是一次具体的尝试，由一个 [ReAct 代理](../concepts/architecture.md#节点级提示构建)
  运行，它编写代码、提交它（本地或通过 SLURM）、读取输出并提取指标。
- 已完成的节点进入**前沿 (frontier)**。ARI 反复挑选最有希望的那个并**扩展**它，得到一个被标记为 `improve`、
  `ablation`、`validation`、`debug` 或 `draft` 的单一子节点。
- 一个同行评审 LLM（即 **`LLMEvaluator`**）为每个节点的
  `_scientific_score` 评分，而该分数驱动接下来哪个节点被扩展。

在 **运行监控** 和 **研究树** 页面上实时观看。要查看逐节点的详情面板 ——
Overview、MCP Trace（每一次工具调用）、Code、Memory、Access 与 Report —— 请打开
legacy 树页面 `#/tree`；这里没有 Output 标签页，节点的文件改从文件浏览器中查看。

有两种行为会让新手感到意外 —— 二者都是有意为之：

- **失败的节点不会被重试。** ARI 会改为扩展一个 `debug` 子节点，使修复被记录为一个新节点。
- **什么都没改变的子节点会被标记为 _sterile（不育）_，并且不再被扩展。**
  输出文件不会从父节点继承，因此子节点必须真正重新运行实验。当本次运行指名了一个
  pin 定的 problem（`ARI_PROBLEM`）时，该 problem 声明了 `score_inputs`，不育性就由
  精确哈希这些文件来判定，而不是对整个 work_dir 做差分 —— 整目录那条规则实际上几乎从不触发，
  因为每个节点都会重写诸如 `results.json` 之类的记账文件。
  不育节点保留已测得的分数与评估状态；它失去的是被扩展的资格，以及让父节点退役的资格。
  （参见 [FAQ](faq.md) 和 [术语表 → sterile](../reference/glossary.md)。）

搜索在你的节点/深度预算处停止。完整的树会保存为
`tree.json` / `nodes_tree.json`。

## 5. 从树到论文（BFTS 后管线）

当搜索结束时，一条由 `workflow.yaml` 驱动的管线将树变成一篇论文（参见 [发表生命周期](../concepts/publication-lifecycle.md)）：

1. **audit_node_provenance** 对 node_report 记录了 sha256 的每个节点产物重新哈希，并与磁盘上的实体比对——正好在节点输出不再是"实验结果"、而开始成为"论文证据"的那个边界上。它按产物报告 verified / mismatch / missing / unhashed 到 `node_provenance_audit.json`。这是信号，不是门。
2. **transform_data** 读取整棵树，并将硬件、方法论和发现提取到 `science_data.json`。
3. **generate_ear** 组装可复现性包 `ear/`（代码、输入数据、图表、`reproduce.sh`、LICENSE —— 但不含实验输出）。它运行在论文写作*之前*而非之后：`write_paper` 依赖它，因为这个包正是论文所指向的证据。
4. **generate_figures** 只让 LLM 选择每张图“展示什么”（指标、图表类型、x 轴），随后由固定渲染器依据 `science_data.json` 确定性地绘制。接着 **VLM** 评审**每一张**图，聚合分取各图的最小值，因此只要有一张弱图就会让该阶段循环回去重新生成（阈值 0.7，最多 2 次额外轮次）。
5. **write_paper** 起草 LaTeX、修订它，并从调研结果中拉取 BibTeX → `full_paper.tex` / `.pdf`。
6. **review_paper** 针对所选的 venue rubric 运行一个或多个评审代理（当评审多于一个时，会有一个 Area Chair 元评审进行汇总）。

默认情况下，管线现在还会运行一个 **claim-evidence 验证回路**：一个确定性硬门重新推导所报告的数值，一个不阻断的 evidence-grounded 语义评审依据这些证据检查行文，随后一次保持锚点的修订与重新渲染闭合该回路。它默认以 **warn** 模式运行，但这并不等于“仅报告”：warn 仍会因 objective-integrity 层（`always_block_on` —— 不变量违反、correctness 失败或未覆盖、占位分母、重算不一致、未绑定或摘要不符的产物……）而阻断最终门，因为这些发现是确定性为假的，而非评审口味问题。其余发现只被报告，直到你设置 `ARI_CLAIM_GATE_MODE=strict`（或 `claim_gate_policy.mode: strict`）才会阻断；strict 还会额外阻断已配置的 `block_on` 发现以及 strict 小节中未覆盖的结果数值。`mode: off` 从不阻断，draft 阶段的报告在两种模式下也都不阻断。详情参见[发表生命周期](../concepts/publication-lifecycle.md)。

从侧边栏的 **论文与结果** 入口阅读全部内容。该入口打开的是 run 显式的**只读**摘要
（`#/results2?run=<run_id>`）—— 评审分数、可复现性链、发布谱系。类 Overleaf 的编辑器和
EAR 浏览器（以及所有 EAR 变更操作）位于它链接出去的 legacy 页面 `#/results` 上。

## 6. 验证它可复现（ORS）

最后，ARI 会像一位独立的审稿人那样检查自己的工作
（[ORS](../guides/paperbench/paperbench_quickstart.md)）：

- **Phase 0** 从最终论文生成 PaperBench rubric，然后在任何评分发生之前**审计这份 rubric 本身**：为每个叶节点标记 `vague_qualifier` / `no_paper_evidence` / `duplicate` / `unverifiable`，并把这些标记写回 `ors_rubric.json`（摘要在 `ors_rubric.audit.json`）。评分仍照常进行——这是质量信号，好让读者看到哪些标准并不可靠。
- **Phase 1** 在沙箱中运行 `reproduce.sh`（如有则用 SLURM，否则用
  docker / apptainer / local）并检查预期的产物是否出现。
- **Phase 2** 针对该 rubric 对结果评分，其中包括一项 **negative control（阴性对照）**（一个空仓库必须得分接近零），使得无所作为无法赢得评分。

裁决结果在 `ors_grade.json` 中（评分状态、逐叶得分与 negative control 结果），Phase 1 的结果则在 `ors_phase1.json`。

## 7. 你现在拥有什么

在 `workspace/checkpoints/<timestamp>_<slug>/` 中：

| 文件 | 它是什么 |
|---|---|
| `idea.json` | 来自 VirSci 的假说 + 计划 |
| `tree.json` / `nodes_tree.json` | 带指标的完整搜索树 |
| `science_data.json` | 清洗后的、面向科学的数据 |
| `full_paper.tex` / `.pdf` | 生成的论文 |
| `review_report.json` | 同行评审分数与反馈 |
| `ear/` | 可复现性包 |
| `ors_grade.json` | ORS 裁决 |

## 接下来去哪里

- 让目标文件做更多事：[编写实验文件](../guides/experiment_file.md)
- 深入理解搜索：[BFTS 算法](../concepts/bfts.md)
- 大规模运行：[HPC 设置](../guides/hpc_setup.md)
- 复现别人的论文：[PaperBench 快速入门](../guides/paperbench/paperbench_quickstart.md)

---

另请参阅：[快速入门](quickstart.md) · [FAQ](faq.md) ·
[术语表](../reference/glossary.md) · [架构](../concepts/architecture.md)
