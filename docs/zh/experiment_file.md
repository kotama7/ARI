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
(`ari-core/ari/pipeline/experiment_md.py:31`) 解析，作为
`evaluation_criteria.json:primary_metric` 的兜底来源；正文随后被
LLM 驱动的 `generate_ideas` 用于补全计划其余部分。

## 识别的章节

ARI 不强制要求特定章节结构（按纯 Markdown 读取）。但下列标题是惯例，
其中部分会被确定性辅助函数解析：

### `Metrics:` 行（必需）

```markdown
Metrics: GB/s, GFlops/s
```

提取首个 token（这里是 `GB/s`），在 idea 尚未确定 primary_metric
时作为兜底值写入 `evaluation_criteria.json`。包含 "metric" 或
"metrics" 的纯文本同样工作。

### `## Research Goal`（可选，推荐）

一段意图陈述。LLM 在 `generate_ideas` 中按字面读取；此处含糊会传播
到含糊的假设。

### `## Required Workflow`（可选）

如果想约束工具调用顺序，使用编号列表。多数情况下让智能体自行决定，
跳过本节。

### `## Hardware Limits` / `## Rules`（可选）

以项目符号列出硬约束。智能体作为系统上下文读取。

### `## SLURM Script Template`（可选）

LLM 可以修改的基线脚本。仅当基准启动协议不寻常时有用。

### 魔法注释（由辅助函数解析）

| 注释 | 用途 |
|------|------|
| `<!-- min_expected_metric: N -->` | 评审使用的软下限 |
| `<!-- metric_keyword: NAME -->`   | 指标提取器的提示 |

## v0.6 / v0.7 新增内容

### Rubric / venue 选择（v0.6）

`experiment.md` 是 **plan**；**venue** 在
`ari-core/config/reviewer_rubrics/<id>.yaml`，由 `ARI_RUBRIC` 环境
变量选取。Rubric 同时提供 BFTS 评分维度与已发布评审标准。详见
`docs/architecture.md#plan--venue-contract-v070`。

### VirSci 自动追加块（v0.6）

`generate_ideas` 运行后，pipeline 会向检查点的 `experiment.md`
回写一段带标记块：

```markdown
<!-- AUTO-APPENDED BY VirSci (idea.json) — DO NOT EDIT -->
## Selected idea
...
## Plan §-tags
...
## Alternatives considered
...
<!-- END AUTO-APPENDED -->
```

此块幂等（每次 promote 重写，绝不重复）。仅编辑标记之 **上方** 的
正文。

### 谱系决策记录（v0.7）

`stagnation_rule` 监视 BFTS 复合评分轨迹，触发后由 LLM 评判选取
`continue` / `switch_to_idea` / `fanout` / `terminate` 之一，决策
追加到 `{ckpt}/lineage_decisions.jsonl`。无需手动编辑
`experiment.md`。

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
`docs/architecture.md#publication-lifecycle-v070`。

## `experiment.md` 的存放位置

ARI 按以下顺序查找：

1. 活动检查点根目录：`$ARI_CHECKPOINT_DIR/experiment.md`
2. `ari run experiment.md` 的参数（首次启动时复制到检查点中）

不存在全局默认或 `$HOME/.ari/` 查找路径 — v0.5.0 的重构使所有
输入文件都限定在检查点作用域内。

## 参见

- `docs/architecture.md#plan--venue-contract-v070` — 完整两文件契约
- `docs/architecture.md#publication-lifecycle-v070` — `experiment.md` 周边产物
- `docs/skills.md` — 各 skill 消费 `experiment.md` 的哪些章节
