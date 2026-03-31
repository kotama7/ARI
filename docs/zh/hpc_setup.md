# HPC 环境配置指南

## 环境

- **集群**：您的 HPC 集群（`your-cluster-login-node`）
- **SSH 别名**：`ssh your-cluster`
- **Python**：`~/miniconda3/bin/python3`（3.13）
- **Ollama**：`~/local/ollama/bin/ollama`
- **ARI 根目录**：`~/ARI/`

## 可用分区

| 分区 | 硬件 | 最大 CPU 数 | 用途 |
|------|------|-------------|------|
| `your_cpu_partition` | CPU 节点 | 视情况而定 | CPU 实验 |
| `your-gpu-partition` | NVIDIA L40S GPU | — | LLM 推理、GPU 实验 |
| `your-h200-partition` | NVIDIA H200 GPU | — | 大模型推理 |
| `your_gpu_partition` | GPU 节点 | — | GPU 实验 |

## 在 HPC 上运行 ARI

### 提交 BFTS 运行

```bash
sbatch ~/ARI/logs/your_job_script.sh
```

### 监控

```bash
squeue -u $USER
tail -f ~/ARI/logs/ari_run_<JOBID>.out
```

### 查看结果

```bash
# 从已完成运行中获取最佳 score
python3 -c "
import json
r = json.load(open('~/ARI/logs/ckpt_<run_id>/results.json'))
for nid, n in r['nodes'].items():
    if n.get('has_real_data'):
        print(nid[:12], n['metrics'])
"
```

## ARI 的 SLURM 脚本模板

```bash
#!/bin/bash
#SBATCH --job-name=ari-experiment
#SBATCH --partition=your_partition
#SBATCH --nodes=1
#SBATCH --cpus-per-task=64
#SBATCH --time=04:00:00
#SBATCH --output=/abs/path/logs/ari_%j.out
#SBATCH --error=/abs/path/logs/ari_%j.err

# 启动 Ollama
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

# 设置子作业的 SLURM 默认值
export SLURM_DEFAULT_PARTITION=your_partition
export SLURM_DEFAULT_WORK_DIR=/path/to/ari/

# 运行 ARI
cd /path/to/ari/ari-core
/home/youruser/miniconda3/bin/ari run \
    /abs/path/to/experiment.md \
    --config /tmp/ari_config.yaml

kill $OLLAMA_PID 2>/dev/null || true
```

## 关键约束

| 规则 | 详情 |
|------|------|
| 编译器 | 仅使用系统编译器 |
| CPU 限制 | `--cpus-per-task` 不超过分区限制 |
| 路径展开 | SBATCH 脚本中不要使用 `~` — 始终使用绝对路径 |
| 标准输出重定向 | 不要在作业脚本中重定向标准输出 — SLURM 通过 `--output` 自动捕获 |
| 账户头信息 | `--account` 和 `-A` 在此集群上无效 — 不要添加 |
| 输出文件名 | 必须遵循模式：`slurm_job_{JOBID}.out` |

## 可用的 Ollama 模型

| 模型 | 最佳用途 |
|------|----------|
| `qwen3:32b` | 默认 — 最佳工具调用质量 |
| `qwen3:8b` | 更快速，质量略低 |
| `deepseek-r1:32b` | 推理密集型任务 |
| `gpt-oss:20b` / `gpt-oss:120b` | OpenAI 兼容替代方案 |
| `qwen2.5vl:32b` | 视觉任务（图表/表格） |
