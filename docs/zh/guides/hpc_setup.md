---
sources:
  - path: ari-skill-hpc
    role: implementation
  - path: containers
    role: config
  - path: scripts/letta
    role: config
  - path: scripts/registry
    role: config
  - path: ari-core/ari/cli/commands.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/pipeline/driver.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/config.py
    role: implementation
last_verified: 2026-08-16
---

# HPC 配置指南

本指南涵盖在 SLURM 集群上运行 ARI、让 ARI 的工具针对 Apptainer /
Singularity / Docker sandbox 运行（仓库里并没有 ARI 自身的镜像
recipe）、以及将记忆后端指向共享 Letta 服务。请将集群相关名称（分区、
登录节点、路径）替换为您环境中的实际值。

## 1. 环境

ARI 是普通 Python 应用 — 用 `setup.sh` 安装一次，然后通过登录节点
或 sbatch 包装脚本驱动。在任意集群上必须的 env var：

| 变量 | 用途 |
|---|---|
| `ARI_CHECKPOINT_DIR` | 活动检查点根目录（所有输入输出按此作用域）|
| `ARI_MODEL` | LiteLLM 模型 ID（如 `ollama/qwen3:32b`、`openai/gpt-4o`）。`ARI_LLM_MODEL` 作为别名同样被认可，但两者同时设置时以 `ARI_MODEL` 为准 |
| `ARI_LLM_API_BASE` | 可选 — 当 LLM 端点非 LiteLLM 默认时设置 |
| `OLLAMA_HOST` / `OLLAMA_MODELS` | LLM 为本地 Ollama 时必需 |

> v0.5.0 移除的是作为*状态*根目录的全局 `$HOME/.ari/` — 所有状态文件
> 现位于 `ARI_CHECKPOINT_DIR` 之下，或某个明确的 env var 指向的位置。
> 但仍保留了三个只读的遗留*配置*回退，文件存在时依然会生效:
> `~/.ari/registries.yaml`、`~/.ari/publish.yaml`、`~/.ari/registry-data`。
> 每一个被采用时都会发出 `DeprecationWarning`；请把它们迁到 checkpoint
> 或对应的 env var 下。
> 请在外层 ARI 进程的包装脚本中设置其 env var **而不是 shell rc 文件**。
> 规范的 HPC 子作业**不会**继承该父进程环境: 每个 `JobRequestV1` 显式
> 声明经审阅的非机密变量与 module。凭据需要领域特定的 staged artifact 或
> 凭据提供方；调度器绝不在计算节点上 source `.env`。

## 2. 可用分区（模板）

| 分区 | 硬件 | 用途 |
|------|------|------|
| `your_cpu_partition` | CPU 节点 | BFTS 探索、基线基准测试 |
| `your-gpu-partition` | NVIDIA L40S | 智能体循环 LLM 推理 |
| `your-h200-partition` | NVIDIA H200 | 大模型推理、论文评审 |
| `your_gpu_partition` | GPU 节点 | GPU 受限实验 |

通过 `sbatch` 的 `--partition=` 选择。对子作业，hpc skill 解析分区的
顺序是: 显式调用方参数 → `SLURM_DEFAULT_PARTITION` →
`ARI_SLURM_PARTITION`；解析工作目录的顺序是: 显式参数 →
`SLURM_DEFAULT_WORK_DIR` → `ARI_WORK_DIR` → 当前目录。

## 3. 在集群上运行 ARI

### 提交 BFTS 运行

仓库本身不附带提交用的包装脚本 — 请按 §4 的模板自行编写并提交:

```bash
sbatch /abs/path/to/your/run_ari.sh
```

### 监控

```bash
squeue -u $USER
tail -f $ARI_CHECKPOINT_DIR/ari.log
```

### 查看结果

checkpoint 级别的树是 `nodes_tree.json`
（`{"experiment_goal": …, "nodes": [ … ]}` — `nodes` 是**列表**而非映射）。
`results.json` 是位于
`{workspace}/experiments/{run_id}/{node_id}/` 下的每节点文件，不是
checkpoint 级别的汇总。

```bash
# 已完成运行的最佳指标
python - <<'PY'
import json, os
r = json.load(open(f"{os.environ['ARI_CHECKPOINT_DIR']}/nodes_tree.json"))
for n in r["nodes"]:
    if n.get("has_real_data"):
        print(n["id"][:12], n["metrics"])
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

# 可选：选择一个特定的评审 rubric — 取值是 ari-core/config/reviewer_rubrics/
# 下某个文件的主干名（neurips、icml、iclr、cvpr、acl、osdi、nature、
# generic_conference…）。默认: neurips。未知 id **不会**报错: 会静默回退到
# neurips.yaml。
export ARI_RUBRIC=neurips

cd /path/to/ari/ari-core
/home/youruser/miniconda3/bin/ari run /abs/path/to/experiment.md

kill $OLLAMA_PID 2>/dev/null || true
```

## 5. 容器部署（v0.7+）

**ARI 自身没有打包好的镜像 recipe** — 既没有 `containers/ari.def`，也没有
`containers/ari/docker-compose.yml`。`containers/` 目录放的是用作*构建与
运行 sandbox* 的预建 `.sif` 镜像（工具链镜像、python 镜像、某个工具专用
镜像），而不是 ARI 运行时。`scripts/registry/` 里才是真实存在的两份
recipe，它们打包的是 **registry 服务**，不是智能体循环。

### Apptainer / Singularity

`scripts/registry/start_singularity.sh` 在禁用 docker/podman 的集群上把
registry 构建并运行在一个 SIF 内（`$ARI_REGISTRY_SIF`，默认
`$HOME/.ari/ari-registry.sif`）。要把 ARI 自己的工作放进 sandbox，请让
skill 指向一个预建镜像，而不是去构建 ARI 镜像：

`ari-skill-coding` 遵守
`ARI_CONTAINER_IMAGE=/abs/path/to/image.sif` 与 `ARI_CONTAINER_MODE`
（`auto` — 默认 — `docker`、`singularity` 或 `apptainer`），用于短小的
交互式命令。
`ari-skill-hpc` 使用 `container_submit`: 其 `JobRequestV1` 携带精确的
SIF SHA-256/大小 pin、typed 只读/读写 bind、clean-environment 标志、
GPU 声明、资源与声明的输出。容器专用的公开别名已被移除；所有调用方都
使用这套 typed 生命周期。

### docker-compose（单主机）

`scripts/registry/docker-compose.yml` 是 registry 的生产方案
（nginx ↔ uvicorn ↔ sqlite）；它以只读方式挂载仓库，而不是构建 ARI
镜像：

```bash
cd scripts/registry
ARI_REGISTRY_TOKEN_USER=admin docker compose up -d
```

### Pip（开发用，无容器）

```bash
./setup.sh                # 创建 virtualenv 并安装 ari-core
ari run experiment.md     # 直接使用宿主 python
```

## 6. Letta 记忆后端部署

`ari-skill-memory` 自 v0.6 起默认使用 Letta 后端。skill 通过
`LETTA_BASE_URL`（默认 `http://localhost:8283`）与 Letta 服务
通信。3 种部署路径：

| 路径 | 适用场景 |
|---|---|
| Apptainer SIF（`scripts/letta/start_singularity.sh`，镜像 `scripts/letta/letta.sif`）| 无 Docker 的 HPC |
| docker-compose（`scripts/letta/docker-compose.yml` — Letta + 具备 pgvector 能力的 Postgres）| 开发工作站、单节点生产 |
| Pip（`scripts/letta/start_pip.sh` — 专用 venv + SQLite）| 烟雾测试；不建议用于共享集群 |

三者都由 `ari memory start-local` / `ari memory stop-local` 驱动。

无论哪种部署方式都需要的 env var：

| 变量 | 用途 |
|---|---|
| `LETTA_BASE_URL` | Letta API 基础 URL |
| `LETTA_API_KEY` | Letta Cloud 的凭据；本地未认证服务可省略 |
| `LETTA_EMBEDDING_CONFIG` | 嵌入配置选择器；默认 `letta-default` |

每个 ARI 检查点拥有独立的 Letta 代理（集合 `ari_node_<ckpt_hash>`
+ `ari_react_<ckpt_hash>`）。用 `ari delete <checkpoint>`（不存在
`ari ckpt` 子命令组）删除检查点时会先清理对应的 Letta 命名空间 — 但这个
清理是 best-effort: 失败只记日志，本地 `rmtree` 照样进行，于是留下一个
孤儿 Letta 代理。用 `ari memory prune-local` 清扫它们。删除路径见
`ari-skill-memory/README.md`。

`ARI_MEMORY_BACKEND` 选择后端，且只接受 `letta`（默认）或 `in_memory`；
`in_memory` 还额外要求 checkpoint 内存在 `.ari-test-memory-backend`
标记文件，因此无法被生产运行选中。

## 7. SLURM 关键约束

| 规则 | 详情 |
|------|------|
| 工具链 | 在 `environment.modules` 中声明站点确切的 module/工具链；不要假设某个编译器可以跨集群移植 |
| CPU/GPU 限制 | typed 请求必须遵守分区限制；调度器的拒绝会原样返回，不会静默改动资源 |
| 路径 | `work_dir`、输入、输出、镜像、bind、known-hosts 与凭据都使用不含穿越的显式绝对路径 |
| 环境 | 规范作业使用 `sbatch --export=NIL`；父进程 PATH、virtualenv、API key、`.env` 与 shell rc 文件都不会被继承 |
| Account/QoS | 仅当目标站点要求时才添加 `account` 或 `qos`；它们是经校验的惰性标识符，并留存在 provenance 中 |
| 输出 | 在 `work_dir` 之下声明输出路径；终态收集会拒绝缺失、symlink、超大或漂移的 artifact |
| 重试 | 把 `ARI_HPC_LEDGER_PATH` 放在持久的共享存储上。未设置时依次回退到 `{ARI_CHECKPOINT_DIR}/hpc-jobs-v1.json`、`{ARI_WORK_DIR}/.ari/hpc-jobs-v1.json`，最后是系统临时目录下的按 uid 分的目录 — 最后这一档是节点本地的，会让该防护失效。状态不确定的提交会被有意阻塞，而不是重复提交 |

## 8. Ollama 模型推荐

| 模型 | 最佳用途 |
|------|------|
| `qwen3:32b` | 默认 — 本地硬件最佳工具调用质量 |
| `qwen3:8b` | 更快、质量略低，适合烟雾测试 |
| `deepseek-r1:32b` | 推理密集型任务（lineage 决策、论文评审）|
| `gpt-oss:20b` / `gpt-oss:120b` | OpenAI 兼容替代 |
| `qwen2.5vl:32b` | 视觉任务（`ari-skill-vlm` 图表评审）|

## 参见

- `docs/reference/configuration.md` — ARI 遵循的所有 env var
- `docs/concepts/architecture.md` — 运行时架构、记忆布局、分层结构
- `ari-skill-hpc/README.md` — SLURM 工具参考（local + SSH 模式）
- `ari-skill-memory/README.md` — 后端选择 + Letta 部署方案
