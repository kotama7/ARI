---
sources:
  - path: ari-core/config/profiles
    role: config
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/evaluator/llm_evaluator.py
    role: implementation
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
last_verified: 2026-05-26
---

# Cookbook

针对最常用配置旋钮的复制粘贴式食谱。本文是详尽的
[配置参考](../reference/configuration.md)的 how-to 配套读物
—— 当某条食谱需要完整选项列表时，会链接到那里而非重复罗列。

> **覆盖项写在哪里。** 环境 profile 位于
> `ari-core/config/profiles/<name>.yaml`；run 级别的设置位于
> `workflow.yaml`。当你传入 `--profile <name>`（CLI）或在向导中选择它时，
> profile 会被合并到默认值之上。你可以在任一文件中加入 `evaluator:`
> 和 `bfts:` 块。

## 环境 profile：laptop / HPC / cloud

开箱即用三个 profile。用 `ari run experiment.md --profile hpc`
（或向导的 Resources 步骤）选择。

**`laptop`** —— 小型本地 run，无调度器：

```yaml
profile: laptop
hpc:
  enabled: false
  scheduler: none
bfts:
  max_total_nodes: 8
  parallel: 2
```

**`hpc`** —— SLURM/PBS/LSF 集群，自动检测分区：

```yaml
profile: hpc
hpc:
  enabled: true
  scheduler: auto
  partition: auto
  cpus_per_task: 8
  memory_gb: 32
  walltime: "04:00:00"
  max_concurrent_jobs: 4
bfts:
  max_total_nodes: 20
  parallel: 4
```

**`cloud`** —— 无调度器，但并行搜索更宽：

```yaml
profile: cloud
hpc:
  enabled: false
  scheduler: none
bfts:
  max_total_nodes: 16
  parallel: 4
```

**食谱 —— 制作你自己的 profile。** 在
`ari-core/config/profiles/` 中放一个新文件，例如 `bigjob.yaml`，并用
`--profile bigjob` 选择它：

```yaml
profile: bigjob
hpc:
  enabled: true
  scheduler: auto
  partition: gpu
  cpus_per_task: 32
  memory_gb: 128
  walltime: "12:00:00"
bfts:
  max_total_nodes: 40
  parallel: 8
```

分区检测与 SLURM 细节参见 [HPC 设置](hpc_setup.md)。

## 调优搜索与评估器

ARI 暴露四个相互独立的评估层；每个默认值都是 no-op，复刻经典行为。
完整语义见
[配置 → BFTS 评估层](../reference/configuration.md#bfts-evaluation-layers-configurable)；
下面的食谱是常见的组合。

**瓶颈评分 —— 仅当*每个*轴都好时才奖励节点：**

```yaml
evaluator:
  composite: weighted_min   # the score is the lowest axis; weights gate participation
```

**更多探索 —— UCB 式前沿排名**（当搜索不断重复扩展同一个高分节点时很有用）：

```yaml
bfts:
  frontier_score: ucb_like
  ucb_c: 1.0                # 0.0 reduces this back to the default strategy
```

**偏好更浅的节点 —— 在回退排名中惩罚深度：**

```yaml
bfts:
  frontier_score: depth_penalized
  depth_penalty_lambda: 0.1
```

**衡量自定义轴（例如 speedup）而非通用五轴：**

```yaml
evaluator:
  axis_mode: custom
  custom_axes: [correctness, speedup, reproducibility]
  # axis_weights below set the relative weight of each named axis
```

**精确复刻审计前 (pre-audit) 行为**（固定为标准五轴与调和平均）：

```yaml
evaluator:
  axis_mode: legacy
  composite: harmonic_mean
```

**换用你自己的选择 prompt**（Layer D）—— 指向 `ari-core/ari/prompts/`
下的某个模板（不含 `.md` 后缀）；它必须保留相同的占位符：

```yaml
bfts:
  select_prompt: orchestrator/my_select          # needs {experiment_goal} {memory_context} {candidates}
  expand_select_prompt: orchestrator/my_expand    # needs {experiment_goal} {candidates}
```

## PaperBench：复现 vs 审计

两种模式由同一套 rubric 机制驱动；差别在于你让它们指向什么。
端到端流程见 [PaperBench 快速入门](paperbench/paperbench_quickstart.md)，
每个旋钮见 [环境变量](../reference/environment_variables.md)。

**复现一篇论文**（从头运行其代码并评分）。当自动选择会挑错时，
显式固定 Phase 1 沙箱：

```bash
export ARI_PHASE1_SANDBOX=slurm        # or docker / apptainer / singularity / local
export ARI_SLURM_PARTITION=gpu          # required when the sandbox is slurm
```

**审计一篇论文**（判断论文*本身*是否描述得足以复现）—— 通过 rubric
选择一个审计会场模板：

```bash
export ARI_RUBRIC=sc                    # venue template: sc / neurips / nature
```

切换 `ARI_RUBRIC` 会同时改变 BFTS 的评分轴与已发布的评审标准
—— 参见 [术语表 → venue](../reference/glossary.md) 与
[架构 → Plan / Venue 契约](../concepts/architecture.md#plan--venue-contract-v070)。

---

另请参阅：[配置参考](../reference/configuration.md) ·
[HPC 设置](hpc_setup.md) · [PaperBench 快速入门](paperbench/paperbench_quickstart.md) ·
[术语表](../reference/glossary.md)
