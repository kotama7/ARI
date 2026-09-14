---
sources:
  - path: ari-core/ari/pipeline/experiment_md.py
    role: implementation
  - path: ari-skill-evaluator
    role: implementation
  - path: ari-core/ari/agent/workflow.py
    role: implementation
  - path: ari-core/ari/agent/guidance.py
    role: implementation
  - path: ari-core/ari/orchestrator/lineage_decision.py
    role: implementation
  - path: ari-core/ari/lineage.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-skill-paper/src/rubric.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-16
---

# 编写 experiment.md

`experiment.md` 是描述 ARI 应执行什么的 Markdown 文件。每个检查点
根目录都会放一个 — 它是某次 run 的领域知识唯一来源（无需改代码即可
驱动新实验）。

## 最小示例

```markdown
我们提出一种 CSR 格式稀疏-稠密矩阵乘法 (SpMM)，
即使右端矩阵尺寸变化也能保持高性能。
基于理论算力与内存带宽建立 roofline 模型，并与实测对比。

Metrics: GB/s, GFlops/s
```

仅此而已。**`Metrics:`** 一行由确定性辅助函数
`parse_metric_from_experiment_md`
(`ari-core/ari/pipeline/experiment_md.py:30`) 解析，作为
`evaluation_criteria.json:primary_metric` 的兜底来源；正文随后被
LLM 驱动的 `generate_ideas` 用于补全计划其余部分。

上面的示例也可直接当作**冒烟测试**：保存为 `experiment.md` 后执行
`ari run experiment.md`，可以在还没正式定下研究目标前，一次性
验证 CLI、`.env` 读取与记忆后端是否端到端可用。

## 识别的章节

ARI 不强制要求特定章节结构（按纯 Markdown 读取）。但下列标题是惯例，
其中部分会被确定性辅助函数解析：

### `Metrics:` 行（可选，推荐）

```markdown
Metrics: GB/s, GFlops/s
```

提取首个 token（这里是 `GB/s`），在 idea 尚未确定 primary_metric
时作为兜底值写入 `evaluation_criteria.json`。它不是强制的：没有这一行
时函数返回 `""`，run 照常继续。该行必须以 `Metric` 或 `Metrics`
（不区分大小写）**开头**，后接 `:` 或 `-` —— 埋在散文句子中间的同一个词
不会匹配。

### `## Success Metrics` 章节（可选）

```markdown
## Success Metrics
- gflops_per_second: sustained throughput
- l2_hit_rate: cache behaviour
```

evaluator skill 的 `_parse_success_metrics` 会在解析行内 `Metrics:`
之**前**读取本节，并取走每一条 `- name:` 项作为声明的指标；因此
`## Success Metrics` 章节是**覆盖**而非补充 `Metrics:` 行。

### `## Research Goal`（可选，推荐）

一段意图陈述。LLM 在 `generate_ideas` 中按字面读取；此处含糊会传播
到含糊的假设。

### `## Required Workflow`（可选）

如果想约束工具调用顺序，使用编号列表。多数情况下让智能体自行决定，
跳过本节。

### `## Hardware Limits` / `## Rules`（可选）

以项目符号列出硬约束。没有任何辅助函数解析这些**标题** —— 它们与文件其余
部分一样，作为散文进入 LLM。真正被**确定性**解析的，是 `ari/agent/workflow.py`
在文档任意位置（且仅在启用 HPC 时）识别的两个独立模式：

```markdown
Partition: <partition-name>
Max CPUs: 64
```

`Partition:` 设置 `hints.slurm_partition`（否则取 `ARI_SLURM_PARTITION`，
再否则取 `sinfo` 报告的第一个 `up` 分区）；`Max CPUs:` 设置展示给 LLM 的
CPU 上限（否则取 `ARI_SLURM_CPUS`）。

### `## Provided Files` / `## Local Files`（可选）

每行一个路径或以项目符号列出，在批次开始时按 basename 复制到**每个**节点的
work dir 中。`## 提供ファイル`、`## 提供文件` 以及裸的 `## Files` 都被接受为
别名；一行只有在包含路径分隔符时才算数，且行尾的 `# 注释` 会被剥除。有两处
静默跳过：basename 属于检查点元文件（例如 `results.json`）的文件绝不复制，
已存在的目标文件也绝不覆盖。

### `## SLURM Script Template`（可选）

LLM 可以修改的基线脚本。仅当基准启动协议不寻常时有用。与 `## Rules` 一样，
没有任何确定性辅助函数读取它 —— 它只是给 LLM 的上下文。

### 魔法注释（由辅助函数解析）

| 注释 | 用途 |
|------|------|
| `<!-- min_expected_metric: N -->` | 智能体循环中的**硬**下限，而非评审提示：当提取到多于一个数值且 `max(values) < N` 时，`guidance.py` 会调用 `node.mark_failed()`。注意解析方式 —— `ari/agent/workflow.py` 匹配的是 `([\d]+)`，因此 `2.5` 会被读成 `2`，而 evaluator skill 自己的解析器接受小数 |
| `<!-- metric_keyword: NAME -->`   | 指标提取器的提示；在既没有 `Metrics:` 行也没有 `## Success Metrics` 章节时，它还是 `expected_metrics` 的兜底来源 |

## v0.6 / v0.7 新增内容

### Rubric / venue 选择（v0.6）

`experiment.md` 是 **plan**；**venue** 在
`ari-core/config/reviewer_rubrics/<id>.yaml`，由 `ARI_RUBRIC` 环境
变量选取（默认 `neurips`）。该 rubric 提供 BFTS 评判所依据的维度。
**已发布的评审**则是另一个旋钮：`review_paper` 的 `rubric_id` 取自
`workflow.yaml` 中的 `paper_rubric`（默认 `generic_conference`），且从不
读取 `ARI_RUBRIC` —— 因此只改 `ARI_RUBRIC` 会让评审仍停留在通用 rubric 上；
要让搜索与评审依据同一个 venue 判定，请同时设置两者。完整的两文件契约详见
`docs/concepts/architecture.md#plan--venue-contract-v070`。

### VirSci 自动追加块（v0.6）

`generate_ideas` 运行后，pipeline 会向检查点的 `experiment.md`
回写一段带标记块：

```markdown
<!-- AUTO-APPENDED BY VirSci (idea.json) — DO NOT EDIT -->
## Selected research idea
...
## Plan sections (full text in idea.json)
...
## Alternatives considered (not pursued in this run)
...
<!-- END AUTO-APPENDED -->
```

中间那个标题取决于 `workflow.yaml:plan_promote`（默认 `index_only`，即上例
所示）；`full` 会输出 `## Detailed experiment plan` 并内联各 § 正文，`off`
则什么都不写。

此块只写入**一次**：当 `AUTO-APPENDED` 标记已存在时
`_promote_plan_to_experiment_md` 会立即返回，因此之后的 promote **不会**刷新
过时的块 —— 若想让它重新生成，请删除该标记。仅编辑标记之 **上方** 的正文；
begin/end 标记之间的内容归自动追加辅助函数所有。

### 谱系决策记录（v0.7）

`stagnation_rule` 监视 BFTS 复合评分轨迹。一旦停滞被 CONFIRMED，
ARI 首先 **确定性地** 转向 `idea.json` 中最强的 **未使用** 候补
想法（`switch_to_idea`，并列时取较小索引，并附带
`disable_generate_ideas`）——从而让候补想法真正得到尝试，而非
未经使用就被丢弃。LLM 评判（`continue` / `switch_to_idea` /
`fanout` / `terminate`）仅在无可用确定性转向时（预算耗尽、达到
递归上限、或没有剩余的未使用候补）作为 **回退** 被咨询。决策
（每次触发一条记录）追加到 `{ckpt}/lineage_decisions.jsonl`。
无需手动编辑 `experiment.md`——候补想法目录位于 `idea.json`，
谱系遍历读取 `meta.json:parent_run_id`。

### 子实验继承（v0.7）

| 通道 | 方向 | 机制 |
|---|---|---|
| `venue.md` (rubric) | 继承 | `ARI_RUBRIC` env var |
| `memory` | 继承 | 祖先作用域读取（`ari-skill-memory`）|
| `idea.json` (catalog) | 继承（只读） | `ari/lineage.py` 顺着 `meta.json:parent_run_id` 走 |
| `plan.md` / `experiment.md` (directive) | **不继承** | 子自行编写 |

子节点可自由转向；继承的只有 catalog 与 rubric。

### ORS 元数据（v0.7）

再现性流程（`ari-skill-replicate` + `ari-skill-paper-re`）不需要
`experiment.md` 中新增字段。改在检查点目录累积新 artifact
（`ors_rubric.json`、`ors_grade.json`、`repro_sandbox/`）。详见
`docs/concepts/publication-lifecycle.md#publication-lifecycle-v070`。

## `experiment.md` 的存放位置

ARI 按以下顺序查找：

1. 活动检查点根目录：`$ARI_CHECKPOINT_DIR/experiment.md` —— resume 时优先使用，
   因为 `tree.json` 中记录的路径可能已过时。
2. `ari run experiment.md` 的参数（首次启动时复制到检查点中）。它是**必填**的
   位置参数：当该路径不是文件时 `ari run` 会以 1 退出，因此全新的 run 绝不会
   回退到 (1)。

不存在全局默认或 `$HOME/.ari/` 查找路径 — v0.5.0 的重构使所有
输入文件都限定在检查点作用域内。

## 参见

- `docs/concepts/architecture.md#plan--venue-contract-v070` — 完整两文件契约
- `docs/concepts/publication-lifecycle.md#publication-lifecycle-v070` — `experiment.md` 周边产物
- `docs/reference/skills.md` — 各 skill 消费 `experiment.md` 的哪些章节
