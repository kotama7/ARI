# ARI CLI 参考

ARI 命令行操作的完整参考。CLI 为基于终端的工作流提供与 [Web 仪表盘](quickstart.md)相同的功能。

---

## 命令概览

| 命令 | 描述 | 仪表盘等效操作 |
|------|------|----------------|
| `ari run` | 运行新实验 | New Experiment 向导 → Launch |
| `ari resume` | 恢复中断的实验 | Experiments 页面 → Resume 按钮 |
| `ari paper` | 仅生成论文（跳过实验） | `POST /api/run-stage {stage: "paper"}` |
| `ari status` | 显示实验树和摘要 | Monitor / Tree 页面 |
| `ari viz` | 启动 Web 仪表盘 | -- |
| `ari projects` | 列出所有过去的实验 | Experiments 页面 |
| `ari show` | 显示某次运行的详细结果 | Results 页面 |
| `ari delete` | 删除检查点 | Experiments 页面 → Delete 按钮 |
| `ari settings` | 查看或修改配置 | Settings 页面 |
| `ari skills-list` | 列出可用工具 | Settings → MCP Skills |

---

## ari run

从实验 Markdown 文件运行新实验。

```bash
ari run <experiment.md> [--config <config.yaml>] [--profile <profile>]
```

| 参数 | 是否必需 | 描述 |
|------|----------|------|
| `experiment.md` | 是 | 实验 Markdown 文件的路径 |
| `--config` | 否 | 自定义配置 YAML（省略则自动生成） |
| `--profile` | 否 | 环境配置文件：`laptop`、`hpc` 或 `cloud` |

**示例：**

```bash
# 基本运行（自动检测配置）
ari run experiment.md

# 使用环境配置文件
ari run experiment.md --profile laptop

# 使用自定义配置
ari run experiment.md --config ari-core/config/workflow.yaml

# 使用环境变量覆盖
ARI_MAX_NODES=10 ARI_PARALLEL=2 ari run experiment.md
```

**运行流程：**

1. ARI 生成一个唯一的项目名称（由 LLM 生成的标题）
2. 创建检查点目录：`./checkpoints/<run_id>/`
3. 在 arXiv 和 Semantic Scholar 上搜索相关论文
4. 通过 VirSci 多智能体讨论生成假说
5. 运行 Best-First Tree Search（BFTS）实验
6. 用 LLM 同行评审评估结果
7. 撰写带有图表和引用的 LaTeX 论文
8. 独立验证可重现性

---

## ari resume

从检查点恢复中断的实验。

```bash
ari resume <checkpoint_dir> [--config <config.yaml>]
```

**示例：**

```bash
ari resume ./checkpoints/20260328_matrix_opt/
```

加载已保存的树，识别待运行/失败的节点，并从中断处继续运行。

---

## ari paper

仅生成论文，不运行实验。适用于实验已完成的情况。

```bash
ari paper <checkpoint_dir> [--experiment <experiment.md>] [--config <config.yaml>]
```

**示例：**

```bash
ari paper ./checkpoints/20260328_matrix_opt/
```

运行 BFTS 后管线：数据转换、图表生成、论文撰写、评审和可重现性检查。

---

## ari status

显示实验树和摘要统计信息。

```bash
ari status <checkpoint_dir>
```

**示例：**

```bash
ari status ./checkpoints/20260328_matrix_opt/

# 输出：
# ── Experiment Tree ──
# root (success) score=153736
# ├── improve_1 (success) score=180200
# │   ├── ablation_1 (success) score=120000
# │   └── validation_1 (success) score=178500
# └── draft_2 (failed)
#
# Summary: 4 success, 1 failed, 0 running, 0 pending
```

---

## ari viz

启动 Web 仪表盘进行可视化实验管理。

```bash
ari viz <checkpoint_dir> [--port <port>]
```

| 参数 | 默认值 | 描述 |
|------|--------|------|
| `checkpoint_dir` | （必需） | 要监控的检查点目录 |
| `--port` | 8765 | 服务端口 |

**示例：**

```bash
# 启动仪表盘
ari viz ./checkpoints/ --port 8765

# 监控特定运行
ari viz ./checkpoints/20260328_matrix_opt/ --port 9878
```

在浏览器中打开 `http://localhost:<port>`。仪表盘的使用方法请参阅 [快速入门指南](quickstart.md)。

---

## ari projects

列出所有过去的实验运行。

```bash
ari projects [--checkpoints <dir>]
```

**示例：**

```bash
ari projects

# 输出：
# ID                              Nodes  Status    Best Score  Modified
# 20260328_matrix_opt             28     complete  153736      2h ago
# 20260327_sorting_benchmark      12     complete  0.95        1d ago
# 20260326_benchmark_test          5      failed    --          2d ago
```

---

## ari show

显示特定实验的详细结果。

```bash
ari show <checkpoint> [--checkpoints-dir <dir>]
```

显示实验树、评审报告摘要和产物列表。

---

## ari delete

删除检查点目录。

```bash
ari delete <checkpoint> [--yes]
```

| 标志 | 描述 |
|------|------|
| `-y` / `--yes` | 跳过确认提示 |

---

## ari settings

查看或修改 ARI 配置。

```bash
ari settings [--config <config.yaml>] [options]
```

| 选项 | 描述 |
|------|------|
| `--model <name>` | 设置 LLM 模型名称 |
| `--api-key <key>` | 设置 API 密钥 |
| `--partition <name>` | 设置 SLURM 分区 |
| `--cpus <count>` | 设置 CPU 数量 |
| `--mem <GB>` | 设置内存大小（GB） |

**示例：**

```bash
# 查看当前设置
ari settings

# 更改模型
ari settings --model gpt-4o

# 设置多个选项
ari settings --model qwen3:32b --partition gpu --cpus 64 --mem 128
```

---

## ari skills-list

列出所有可用的 MCP 工具及其描述。

```bash
ari skills-list [--config <config.yaml>]
```

---

## 环境变量

### 核心配置

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_BACKEND` | LLM 后端（`ollama` / `openai` / `anthropic` / `claude`） | `ollama` |
| `ARI_MODEL` | 模型名称 | `qwen3:8b` |
| `OPENAI_API_KEY` | OpenAI API 密钥 | — |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | — |
| `OLLAMA_HOST` | Ollama 服务器 URL | `http://localhost:11434` |
| `LLM_API_BASE` | 通用 API 基础 URL（回退） | — |

### BFTS 配置

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_MAX_NODES` | 最大实验总数 | 50 |
| `ARI_MAX_DEPTH` | 最大树深度 | 5 |
| `ARI_PARALLEL` | 并行实验数 | 4 |
| `ARI_MAX_REACT` | 每个节点的最大 ReAct 步数 | 80 |
| `ARI_TIMEOUT_NODE` | 每个节点的超时时间（秒） | 7200 |

### HPC 配置

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_EXECUTOR` | 执行后端（`local` / `slurm` / `pbs` / `lsf`） | `local` |
| `ARI_SLURM_PARTITION` | SLURM 分区名称 | — |

### 按阶段模型覆盖

| 变量 | 阶段 |
|------|------|
| `ARI_MODEL_IDEA` | 创意生成 |
| `ARI_MODEL_BFTS` | BFTS 实验 |
| `ARI_MODEL_PAPER` | 论文撰写 |
| `ARI_MODEL_REVIEW` | 论文评审 |

### .env 文件

ARI 会自动加载 `.env` 文件（按以下顺序检查）：

1. `<checkpoint_dir>/.env`（最高优先级）
2. `<project_root>/.env`
3. `<project_root>/ari-core/.env`
4. `~/.env`（最低优先级）

格式：`KEY=VALUE`（以 `#` 开头的行为注释，将被忽略）。

---

## 在 HPC（SLURM）上运行

```bash
# 设置执行器
export ARI_EXECUTOR=slurm
export ARI_SLURM_PARTITION=your_partition

# 提交为 SLURM 作业
sbatch << 'EOF'
#!/bin/bash
#SBATCH --job-name=ari
#SBATCH --partition=your_partition
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --time=04:00:00
#SBATCH --output=ari_%j.out

# 如果在 GPU 节点上使用 Ollama：
ollama serve &
sleep 10

export ARI_BACKEND=ollama
export ARI_MODEL=qwen3:32b

cd /path/to/ARI
ari run /path/to/experiment.md --profile hpc
EOF
```

**重要规则：**

- 始终使用绝对路径（不要使用 `~` 或相对路径）
- 不要在 SLURM 脚本中重定向 stdout（SLURM 通过 `--output` 自动捕获）
- 除非你的集群要求，否则不要添加 `--account` 或 `-A` 标志
