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
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-skill-paper-re/src/server.py
    role: implementation
last_verified: 2026-08-16
---

# Cookbook

针对最常用配置旋钮的复制粘贴式食谱。本文是详尽的
[配置参考](../reference/configuration.md)的 how-to 配套读物
—— 当某条食谱需要完整选项列表时，会链接到那里而非重复罗列。

> **覆盖项写在哪里。** 环境 profile 位于
> `ari-core/config/profiles/<name>.yaml`；run 级别的设置位于
> `workflow.yaml`。当你传入 `--profile <name>`（CLI）或在向导中选择它时，
> profile 会被合并到默认值之上。`evaluator:` 和 `bfts:` 块写在
> `workflow.yaml` 里。
>
> **`--profile` 只合并四个键，不多不少。** 尽管其 docstring 这么写，
> `_apply_profile`（`ari-core/ari/cli/run.py`）并不是深度合并：它只读取
> `bfts.max_total_nodes`、`bfts.max_parallel_nodes`（或其历史拼法
> `parallel`）、`hpc.enabled` 和 `hpc.scheduler`。profile YAML 中的其他每一个键
> —— `partition`、`cpus_per_task`、`memory_gb`、`walltime`、
> `max_concurrent_jobs`，以及任何 `evaluator:` 块 —— 都会被从文件里读出来，
> 然后被静默丢弃。请把它们改写到 `workflow.yaml`（`resources:`、
> `evaluator:`、`bfts:`）或环境变量（`ARI_SLURM_PARTITION`）中。

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

**`hpc`** —— 启用调度器（`scheduler:` 下面的那些键只是记录在文件里，
并不会被合并；分区实际来自 `ARI_SLURM_PARTITION`、实验文件中的
`Partition:` 行，或 `sinfo` 报告的第一个 `up` 分区）：

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
`--profile bigjob` 选择它。只写那四个会被合并的键 —— 在这里写的其他内容都会被
忽略；而一个解析不到对应文件的 profile 名只会记录一条警告并继续运行：

```yaml
profile: bigjob
hpc:
  enabled: true
  scheduler: auto
bfts:
  max_total_nodes: 40
  parallel: 8
```

规模相关的旋钮属于 `workflow.yaml` 的 `resources:` 块，其自身的键名是
`cpus` / `memory_gb` / `gpus` / `walltime` / `partition` —— 或者写在环境变量里
（`ARI_SLURM_PARTITION`）。

分区检测与 SLURM 细节参见 [HPC 设置](hpc_setup.md)。

## 调优搜索与评估器

ARI 暴露四个相互独立的评估层；每个默认值都是 no-op，复刻经典行为。
完整语义见
[配置 → BFTS 评估层](../reference/configuration.md#bfts-评估层-可通过配置切换)；
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

**衡量自定义轴（例如 speedup）而非 rubric 推导出的轴**
（`axis_mode` 默认为 `dynamic`，即从当前 rubric 构建轴）。`custom_axes` 是
`{name, description, weight}` 记录的列表——纯字符串列表会在配置加载时被拒绝：

```yaml
evaluator:
  axis_mode: custom
  custom_axes:
    - name: correctness
      description: "结果是否在容差范围内与参考实现一致"
      weight: 0.4
    - name: speedup
      description: "相对基线的墙钟加速比（1.0 = 无变化）"
      weight: 0.4
    - name: reproducibility
      description: "能否依据记录的产物重跑该次运行"
      weight: 0.2
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

`ARI_RUBRIC`（默认 `neurips`）选择 `ari-core/config/reviewer_rubrics/` 下的
rubric YAML，BFTS 的评分轴由它派生。已发布的评审标准是**另一个旋钮**：
`review_paper` 阶段把 rubric 作为显式的工作流输入接收，即 `workflow.yaml` 中的
`paper_rubric`（默认 `generic_conference`）。若希望搜索与评审依据同一个 venue
来判定，请同时设置两者 —— 参见 [术语表 → venue](../reference/glossary.md) 与
[架构 → Plan / Venue 契约](../concepts/architecture.md#plan-venue-契约-v0-7-0)。

---

另请参阅：[配置参考](../reference/configuration.md) ·
[HPC 设置](hpc_setup.md) · [PaperBench 快速入门](paperbench/paperbench_quickstart.md) ·
[术语表](../reference/glossary.md)
