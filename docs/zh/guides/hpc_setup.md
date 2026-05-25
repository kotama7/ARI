---
sources:
  - path: ari-skill-hpc
    role: implementation
  - path: containers
    role: config
last_verified: 2026-05-25
---

# HPC 配置指南

本指南涵盖在 SLURM 集群上运行 ARI、在 Apptainer / Singularity /
Docker 内部署 ARI、以及将记忆后端指向共享 Letta 服务。请将集群相关
名称（分区、登录节点、路径）替换为您环境中的实际值。

## 1. 环境

ARI 是普通 Python 应用 — 用 `setup.sh` 安装一次，然后通过登录节点
或 sbatch 包装脚本驱动。在任意集群上必须的 env var：

| 变量 | 用途 |
|---|---|
| `ARI_CHECKPOINT_DIR` | 活动检查点根目录（所有输入输出按此作用域）|
| `ARI_LLM_MODEL` | LiteLLM 模型 ID（如 `ollama/qwen3:32b`、`openai/gpt-4o`）|
| `ARI_LLM_API_BASE` | 可选 — 当 LLM 端点非 LiteLLM 默认时设置 |
| `OLLAMA_HOST` / `OLLAMA_MODELS` | LLM 为本地 Ollama 时必需 |

> v0.5.0 已移除全局 `$HOME/.ari/` 目录。所有状态文件位于
> `ARI_CHECKPOINT_DIR` 之下，或某个明确的 env var 指向的位置。
> 请在 sbatch 包装脚本中设置 env var **而不是 shell rc 文件**
> （以便子实验可以覆盖）。

## 2. 可用分区（模板）

| 分区 | 硬件 | 用途 |
|------|------|------|
| `your_cpu_partition` | CPU 节点 | BFTS 探索、基线基准测试 |
| `your-gpu-partition` | NVIDIA L40S | 智能体循环 LLM 推理 |
| `your-h200-partition` | NVIDIA H200 | 大模型推理、论文评审 |
| `your_gpu_partition` | GPU 节点 | GPU 受限实验 |

通过 `sbatch` 的 `--partition=` 选择。ARI 子作业会读取
`SLURM_DEFAULT_PARTITION`。

## 3. 在集群上运行 ARI

### 提交 BFTS 运行

```bash
sbatch ~/ARI/scripts/run_ari.sh
```

### 监控

```bash
squeue -u $USER
tail -f $ARI_CHECKPOINT_DIR/ari.log
```

### 查看结果

```bash
# 已完成运行的最佳指标
python - <<'PY'
import json, os
r = json.load(open(f"{os.environ['ARI_CHECKPOINT_DIR']}/results.json"))
for nid, n in r["nodes"].items():
    if n.get("has_real_data"):
        print(nid[:12], n["metrics"])
PY
```

## 4. SLURM 脚本模板

```bash
#!/bin/bash
#SBATCH --job-name=ari-experiment
#SBATCH --partition=your_partition
#SBATCH --nodes=1
#SBATCH --cpus-per-task=64
#SBATCH --time=04:00:00
#SBATCH --output=/abs/path/logs/ari_%j.out
#SBATCH --error=/abs/path/logs/ari_%j.err

# 检查点作用域 — 所有状态文件都进入此目录
export ARI_CHECKPOINT_DIR=/abs/path/checkpoints/$(date +%Y%m%d_%H%M%S)

# 本地 LLM (GPU 节点上的 Ollama) — 使用远程 LLM 时跳过此块
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS=/home/youruser/.ollama/models
export OLLAMA_CONTEXT_LENGTH=8192
export OLLAMA_NUM_PARALLEL=2
/home/youruser/local/ollama/bin/ollama serve &
OLLAMA_PID=$!
for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:11434/api/tags > /dev/null 2>&1 && break
  sleep 2
done

# ARI 通过 hpc skill 提交的子作业继承的默认值
export SLURM_DEFAULT_PARTITION=your_partition
export SLURM_DEFAULT_WORK_DIR=/path/to/ari/

# 可选：选择一个特定的评审 rubric
export ARI_RUBRIC=neurips2025

cd /path/to/ari/ari-core
/home/youruser/miniconda3/bin/ari run /abs/path/to/experiment.md

kill $OLLAMA_PID 2>/dev/null || true
```

## 5. 容器部署（v0.7+）

为禁止在登录节点上直接运行工具的环境提供 3 种部署方案。它们等价 —
选择您站点支持的即可。

### Apptainer / Singularity

`scripts/registry/start_singularity.sh` 是参考启动脚本；同样的方案
也适用于智能体循环：

```bash
apptainer build ari.sif containers/ari.def
apptainer exec --bind /scratch:/scratch ari.sif \
    ari run /abs/path/to/experiment.md
```

`ari-skill-coding` 和 `ari-skill-hpc` 遵守
`ARI_CONTAINER_IMAGE=/path/to/ari.sif` 与
`ARI_CONTAINER_MODE=singularity`，将用户代码本身包装到 SIF 内 —
便于可复现基准。

### docker-compose（单主机）

`scripts/registry/docker-compose.yml` 是 registry 的生产方案；
全栈也有类似配置：

```bash
docker compose -f containers/ari/docker-compose.yml up -d
```

### Pip（开发用，无容器）

```bash
./setup.sh                # 创建 virtualenv 并安装 ari-core
ari run experiment.md     # 直接使用宿主 python
```

## 6. Letta 记忆后端部署

`ari-skill-memory` 自 v0.6 起默认使用 Letta 后端。skill 通过
`LETTA_HOST` / `LETTA_PORT`（默认 `127.0.0.1:8283`）与 Letta 服务
通信。3 种部署路径：

| 路径 | 适用场景 |
|---|---|
| Apptainer SIF（`containers/letta.sif`）| 无 Docker 的 HPC |
| docker-compose（`containers/letta/docker-compose.yml`）| 开发工作站、单节点生产 |
| Pip（`pip install letta && letta server`）| 烟雾测试；不建议用于共享集群 |

无论哪种部署方式都需要的 env var：

| 变量 | 用途 |
|---|---|
| `LETTA_HOST` / `LETTA_PORT` | Letta API 监听位置 |
| `LETTA_EMBEDDING_CONFIG` | 嵌入配置 JSON 路径（必需）|
| `OPENAI_API_KEY` 等 | 嵌入模型所需 |

每个 ARI 检查点拥有独立的 Letta 代理（集合 `ari_node_<ckpt_hash>`
+ `ari_react_<ckpt_hash>`）。`ari ckpt delete` 删除检查点时会自动
删除对应的 Letta 代理 — 删除路径见 `ari-skill-memory/README.md`。

## 7. SLURM 关键约束

| 规则 | 详情 |
|------|------|
| 编译器 | 仅 `gcc`。多数集群上 `mpicc` / `icc` / `aocc` 会返回 `exit_code=127` |
| CPU 限制 | `--cpus-per-task` 必须不超过分区每节点 CPU 数 |
| 路径展开 | `#SBATCH` 行不要使用 `~` — 始终使用绝对路径 |
| 标准输出重定向 | 不要在作业脚本中重定向 stdout — SLURM 通过 `--output` 捕获 |
| 账户头信息 | 多数集群配置拒绝 `--account` / `-A` — 仅当站点要求时添加 |
| 输出文件名 | 匹配 skill 期望的模式（如 `slurm_job_{JOBID}.out`）|

## 8. Ollama 模型推荐

| 模型 | 最佳用途 |
|------|------|
| `qwen3:32b` | 默认 — 本地硬件最佳工具调用质量 |
| `qwen3:8b` | 更快、质量略低，适合烟雾测试 |
| `deepseek-r1:32b` | 推理密集型任务（lineage 决策、论文评审）|
| `gpt-oss:20b` / `gpt-oss:120b` | OpenAI 兼容替代 |
| `qwen2.5vl:32b` | 视觉任务（`ari-skill-vlm` 图表评审）|

## 参见

- `docs/configuration.md` — ARI 遵循的所有 env var
- `docs/architecture.md` — 运行时架构、记忆布局、分层结构
- `ari-skill-hpc/README.md` — SLURM 工具参考（local + SSH 模式）
- `ari-skill-memory/README.md` — 后端选择 + Letta 部署方案
