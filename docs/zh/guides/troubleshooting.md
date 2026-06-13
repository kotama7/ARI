---
sources:
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/cost_tracker.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/backends/letta_backend.py
    role: implementation
last_verified: 2026-06-10
---

# 故障排查

常见运行时故障及其解决方法。每个章节给出症状（通常是精确的错误
字符串）、原因和修复措施。

## 启动失败

### `ARI_CHECKPOINT_DIR is not set`

**原因：** v0.5+ 中所有状态文件都作用域于检查点，因此该环境变量
为必需项。

**修复：**

```bash
export ARI_CHECKPOINT_DIR=/abs/path/to/checkpoints/$(date +%Y%m%d_%H%M%S)
mkdir -p "$ARI_CHECKPOINT_DIR"
ari run /abs/path/to/experiment.md
```

如果通过 `sbatch` 启动，请在作业脚本中设置此变量，而非在 shell rc
文件中 —— 以便子实验可以覆盖它。

### `DeprecationWarning: $HOME/.ari/...`

**原因：** 触碰了旧版回退路径。v1.0 将在此处硬失败；v0.5–v0.8 发出
警告。

**修复：** 设置显式环境变量。对照表如下：

| 旧版路径 | 新环境变量 |
|---|---|
| `$HOME/.ari/registries.yaml` | `ARI_REGISTRIES_FILE` |
| `$HOME/.ari/registry-data` | `ARI_REGISTRY_DATA` |
| `$HOME/.ari/letta-pid` | `ARI_LETTA_PIDFILE` |

### `ImportError: cannot import name '<X>' from 'ari'`

**原因：** 某个 skill 正在访问 ARI 在 Phase 4 重构中已迁移的内部模块。

**修复：** 将导入切换为 `ari.public.<X>`（参见
`docs/reference/public_api.md`）。如果该符号尚未公开暴露，请提交
issue 并说明使用场景。

## SLURM 问题

### 作业卡在 `PENDING` 状态

**原因（按可能性排序）：**

1. 分区已满或正在维护。
2. 请求的墙钟时间 / CPU / GPU 超过分区限制。
3. 账户剩余配额不足。

**诊断：**

```bash
sinfo -p $SLURM_PARTITION       # Look at AVAIL / STATE
squeue -u $USER                  # Check NODELIST(REASON) column
sacct -j <jobid> --format=Reason # Sometimes more verbose
```

若 `Reason` 为 `Resources` 或 `Priority`，说明正在排队；若为
`PartitionConfig` 或 `QOSMaxJobsPerUserLimit`，说明请求被拒绝。

### 构建步骤返回 `exit_code=127`

**原因：** 几乎总是缺少编译器。HPC skill 限制使用 `gcc`；
在大多数集群上 `mpicc` / `icc` / `aocc` 不在默认 PATH 中。

**修复：** 将 `mpicc` 替换为 `gcc -fopenmp`（如需要则显式链接 OpenMPI）。
在 experiment.md 的 `Hardware Limits` 章节中声明该约束。

### `--account` 被拒绝

**原因：** 大多数集群配置拒绝 `#SBATCH --account=` / `-A` 头部，
除非站点启用了 Slurm 记账功能。

**修复：** 删除该头部。ARI 的 `slurm_submit` 已不再添加该选项；
如果仍然出现，请检查 `experiment.md` 中的 `SLURM Script Template` 章节。

## 内存后端（Letta）

### 调用 Letta 时出现 `connection refused`

**原因：** 没有运行中的 Letta 服务器，或 `LETTA_BASE_URL` 指向了
错误的端点。

**修复：**

```bash
curl -fsS http://127.0.0.1:8283/healthz   # Should return 200

# If it fails, restart per docs/guides/hpc_setup.md#6
docker compose -f containers/letta/docker-compose.yml up -d
# or
apptainer run containers/letta.sif &
```

仪表盘的 `/api/memory/health` 路由使用相同的探针，因此如果 UI 显示
"Letta unhealthy"，说明集群上没有运行中的 Letta 服务。

### `LETTA_EMBEDDING_CONFIG is required`

**原因：** Letta 需要嵌入模型配置来构建归档集合。

**修复：** 将 `LETTA_EMBEDDING_CONFIG` 指向描述嵌入端点的 JSON 文件。
兼容 OpenAI 的示例：

```json
{
  "embedding_endpoint_type": "openai",
  "embedding_model": "text-embedding-3-small",
  "embedding_dim": 1536,
  "embedding_endpoint": "https://api.openai.com/v1"
}
```

### `archival memory search returned 0 results`

**原因：** 很可能是数据路径不匹配。`search_memory` 使用基于嵌入排名
的 `passages.search`（`embed_query=True`）；如果回退到
`passages.list(search=q)`，SQL `LIKE` 匹配器对长自然语言查询会静默
返回 0 条结果。

**修复：** 通过调用 `/api/memory/detect` 确认当前后端。如果修改过
该 skill，请确保使用的是 `passages.search` 路由（参见
`ari-skill-memory/src/ari_skill_memory/backends/letta_backend.py`）。

## LLM 费用 / 配额

### `litellm.exceptions.RateLimitError`

**原因：** 提供商速率限制。

**修复：** ARI 将每次 LLM 调用记录于
`$ARI_CHECKPOINT_DIR/cost_log.jsonl`。检查每分钟调用频率；若超过
提供商配额，请降低 `ARI_PARALLEL` 或将 BFTS 评判器切换至更廉价/
本地模型（`ARI_MODEL_JUDGE=ollama/qwen3:32b`）。

### 意外的费用激增

**诊断：**

```bash
python - <<'PY'
import json, collections
costs = collections.Counter()
with open(f"{__import__('os').environ['ARI_CHECKPOINT_DIR']}/cost_log.jsonl") as fh:
    for line in fh:
        rec = json.loads(line)
        costs[rec["metadata"].get("skill", "?")] += rec["cost_usd"]
for skill, c in costs.most_common():
    print(f"{c:7.3f}  {skill}")
PY
```

最大开销通常来自 BFTS 评判器（`ari-skill-evaluator`）或
rubric 评审（`ari-skill-paper`）。使用 `ARI_MODEL_EVAL` /
`ARI_MODEL_JUDGE` 为其设置模型上限。

## VLM（图表 / 表格评审）

### `VLM model returned no caption`

**原因：** VLM 不支持视觉功能，或图像编码有误。

**修复：**

```bash
# Verify the model.
echo "$VLM_MODEL"   # should be something like openai/gpt-4o, ollama/qwen2.5vl:32b
# Verify the image.
file $ARI_CHECKPOINT_DIR/figures/fig1.png   # should report PNG
```

如果模型仅支持文本（如 `gpt-3.5-turbo`），请切换至支持视觉的模型。

## 容器 / 沙箱

### `singularity exec: command not found`

**原因：** 主机上未安装 Apptainer / Singularity。

**修复：** 要么安装它（Apptainer 是 Singularity 的官方继任者），
要么取消设置 `ARI_CONTAINER_IMAGE` 以回退到宿主机执行。

### `RLIMIT_NPROC: resource temporarily unavailable`

**原因：** coding 沙箱将 fork() 上限设为 `ARI_MAX_CHILD_PROCS`
（默认 1024），某个子进程突破了该限制。

**修复：** 要么精简导致问题的命令（如果评分提示词含糊，智能体
常会陷入 fork bomb 循环），要么提高 `ARI_MAX_CHILD_PROCS`。
默认值已故意设得较为宽松 —— 触达上限通常意味着真实的 bug，
而非预算不足。

## 仪表盘 / viz

### `Cannot connect to ari viz`

**诊断：** `ari viz` 默认绑定到 `127.0.0.1`。如果通过 SSH 连接到
远程主机，需要转发端口。

**修复：**

```bash
# From your laptop:
ssh -L 8000:127.0.0.1:8000 user@remote-host
# Then on the remote:
ari viz --port 8000
```

### 前端显示陈旧状态

**原因：** 后端重启后 WebSocket 重连尚处于等待中。

**修复：** 刷新浏览器。仪表盘在连接时会重新拉取 `/state`。

## 下一步排查方向

- `$ARI_CHECKPOINT_DIR/ari.log` —— 应用日志。
- `$ARI_CHECKPOINT_DIR/cost_log.jsonl` —— LLM 费用记录。
- `$ARI_CHECKPOINT_DIR/lineage_decisions.jsonl` —— stagnation
  决策（v0.7+）。
- `docs/reference/file_formats.md` —— 检查点中每个文件的含义。
- `docs/_archive/refactor_audit.md` —— 已知的迁移债务。

## 另请参阅

[FAQ](../getting-started/faq.md) · [快速入门](../getting-started/quickstart.md) · [PaperBench 故障排查](paperbench/paperbench_troubleshooting.md)
