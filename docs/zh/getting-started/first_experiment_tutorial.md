---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/agent/loop.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-05-26
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

1. **`make_metric_spec`** —— 从你的目标中钉定主要指标（这里是 GFLOP/s，越高越好）。
2. **`survey`** —— 搜索文献，使最终的论文能够引用真实的参考文献。
3. **`generate_ideas`** —— 一场 VirSci 多代理审议就该问题展开辩论并写出
   `idea.json`：一个假说、主要指标，以及一份实验计划。它在整个运行中只运行**一次**。

打开 **Ideas** 页面阅读它的提议。

## 4. 搜索（BFTS）

现在 ARI 开始探索。它不是一个线性脚本 —— 它是一个
[最佳优先树搜索](../concepts/bfts.md)：

- 每个**节点**是一次具体的尝试，由一个 [ReAct 代理](../concepts/architecture.md#per-node-prompt-composition)
  运行，它编写代码、提交它（本地或通过 SLURM）、读取输出并提取指标。
- 已完成的节点进入**前沿 (frontier)**。ARI 反复挑选最有希望的那个并**扩展**它，得到一个被标记为 `improve`、
  `ablation`、`validation`、`debug` 或 `draft` 的单一子节点。
- 一个同行评审 LLM（即 **`LLMEvaluator`**）为每个节点的
  `_scientific_score` 评分，而该分数驱动接下来哪个节点被扩展。

在 **Monitor** 和 **Tree** 页面上实时观看。点击任意节点查看其
Overview、Trace（每一次工具调用）、Code 和 Output 标签页。

有两种行为会让新手感到意外 —— 二者都是有意为之：

- **失败的节点不会被重试。** ARI 会改为扩展一个 `debug` 子节点，使修复被记录为一个新节点。
- **不产生任何新文件的子节点会被标记为 _sterile（不育）_ 并被剪枝。** 输出文件不会从父节点继承，因此子节点必须真正重新运行实验才能赢得分数。（参见 [FAQ](faq.md) 和
  [术语表 → sterile](../reference/glossary.md)。）

搜索在你的节点/深度预算处停止。完整的树会保存为
`tree.json` / `nodes_tree.json`。

## 5. 从树到论文（BFTS 后管线）

当搜索结束时，一条由 `workflow.yaml` 驱动的管线将树变成一篇论文（参见 [发表生命周期](../concepts/publication-lifecycle.md)）：

1. **transform_data** 读取整棵树，并将硬件、方法论和发现提取到 `science_data.json`。
2. **generate_figures** 编写绘图代码；随后一个 **VLM** 评审主图，若得分低则循环回去重做。
3. **write_paper** 起草 LaTeX、修订它，并从调研结果中拉取 BibTeX → `full_paper.tex` / `.pdf`。
4. **review_paper** 针对所选的 venue rubric 运行一个或多个评审代理（当评审多于一个时，会有一个 Area Chair 元评审进行汇总）。
5. **generate_ear** 组装可复现性包 `ear/`（代码、输入数据、图表、`reproduce.sh`、LICENSE —— 但不含实验输出）。

在 **Results** 页面上阅读全部内容：类 Overleaf 的编辑器、评审分数，以及 EAR 浏览器。

## 6. 验证它可复现（ORS）

最后，ARI 会像一位独立的审稿人那样检查自己的工作
（[ORS](../guides/paperbench/paperbench_quickstart.md)）：

- **Phase 1** 在沙箱中运行 `reproduce.sh`（如有则用 SLURM，否则用
  docker / apptainer / local）并检查预期的产物是否出现。
- **Phase 2** 针对一份自动生成的 PaperBench rubric 对结果评分，其中包括一项 **negative control（阴性对照）**（一个空仓库必须得分接近零），使得无所作为无法赢得评分。

裁决结果在 `reproducibility_report.json` 中。

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
| `reproducibility_report.json` | ORS 裁决 |

## 接下来去哪里

- 让目标文件做更多事：[编写实验文件](../guides/experiment_file.md)
- 深入理解搜索：[BFTS 算法](../concepts/bfts.md)
- 大规模运行：[HPC 设置](../guides/hpc_setup.md)
- 复现别人的论文：[PaperBench 快速入门](../guides/paperbench/paperbench_quickstart.md)

---

另请参阅：[快速入门](quickstart.md) · [FAQ](faq.md) ·
[术语表](../reference/glossary.md) · [架构](../concepts/architecture.md)
