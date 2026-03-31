# 编写实验文件

实验文件是 Markdown 文档，完整描述 ARI 应该做什么。
无需修改代码 — 所有领域知识都在此文件中。

## 最小示例

```markdown
# My Experiment

## Research Goal
Maximize the score of a benchmark using different optimization strategies.

## Required Workflow
1. Survey prior work on benchmark optimization
2. Submit a SLURM job to compile and run the benchmark
3. Poll until the job completes
4. Read the output and report score

<!-- min_expected_metric: 1000 -->
<!-- metric_keyword: score -->
```

## 完整参考

### 章节：Research Goal

描述实验试图达成的目标。LLM 读取此内容以理解领域并提出假设。

```markdown
## Research Goal
Maximize score of a benchmark on your HPC cluster.
Explore optimization flags and thread counts (1, 32, 64).
```

### 章节：Required Workflow

告诉智能体应该调用哪些工具以及调用顺序。

```markdown
## Required Workflow
1. Call `survey` to find related literature
2. Call `slurm_submit` with a SLURM script
3. Call `job_status` to wait for completion
4. Call `run_bash` to read the output file
5. Return JSON with measured values
```

### 章节：Hardware Limits

不可违反的硬性约束。

```markdown
## Hardware Limits
- Partition: your_partition
- Max CPUs: 64 (--cpus-per-task must be ≤ 64)
- Compiler: system compiler only
```

### 魔法注释（元数据）

这些注释由 `make_metric_spec` 自动解析：

| 注释 | 用途 |
|------|------|
| `<!-- min_expected_metric: N -->` | 最小可接受的指标值 |
| `<!-- metric_keyword: NAME -->` | 要提取的指标名称（例如 score） |

### 章节：SLURM Script Template

提供一个可工作的基线脚本。LLM 将修改它以测试假设。

```markdown
## SLURM Script Template
\`\`\`bash
#!/bin/bash
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --time=00:30:00

./compile.sh ./benchmark.c
export NTHREADS=32
./benchmark
\`\`\`
```

### 章节：Rules

对智能体的具体约束。使用硬性限制来指定 LLM 绝对不能违反的内容。

```markdown
## Rules
- Always use work_dir=/abs/path/to/workdir in slurm_submit
- NEVER redirect stdout in the script (SLURM captures it automatically)
- Output file: slurm_job_{JOBID}.out
```

## 完整示例

请参阅仓库中的示例实验文件以获取完整的可工作示例。
