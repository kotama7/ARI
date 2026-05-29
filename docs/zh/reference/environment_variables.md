---
sources:
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
last_verified: 2026-05-25
---

# 环境变量参考

ARI 支持约 90 个环境变量，在此汇总以便查阅。大多数变量有合理的默认值；**Required?** 列标记了全新检出时不可缺少的变量。

`docs/reference/configuration.md` 以教程形式介绍相同内容；本页为按字母顺序排列的查阅参考。

> v0.5.0 删除了全局 `$HOME/.ari/` 目录。本参考中标注"必须设置"的变量，其旧版回退会发出 `DeprecationWarning`，并在 v1.0 中移除。

## 核心 (`ARI_*`)

### 检查点 + 路径

| 变量 | 用途 | 默认值 | 必需？ |
|---|---|---|:---:|
| `ARI_CHECKPOINT_DIR` | 当前检查点根目录 | （无 — 必须设置） | ✓ |
| `ARI_WORKSPACE` | 新运行的父目录（供 orchestrator skill 使用） | （无） | ✓ 对于 `ari-skill-orchestrator` |
| `ARI_WORK_DIR` | 每节点工作目录根（`ari-skill-coding`） | `/tmp/ari_work` | – |
| `ARI_LOG_DIR` | 应用日志目录 | `$ARI_CHECKPOINT_DIR` | – |
| `ARI_ROOT` | ARI 源代码树根目录（测试时使用） | （自动检测） | – |
| `ARI_SOURCE_FILE` | 覆盖输入 experiment.md 路径 | （无） | – |

### LLM 模型选择

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_LLM_MODEL` | 默认 LiteLLM 模型 id | （无） |
| `ARI_LLM_API_BASE` | LiteLLM API base 覆盖 | LiteLLM 默认值 |
| `ARI_MODEL` | 跨技能回退模型 id | （回退至 `ARI_LLM_MODEL`） |
| `ARI_MODEL_EVAL` | LLM 评估器使用的模型 | 回退至 `ARI_MODEL` |
| `ARI_MODEL_JUDGE` | BFTS judge 使用的模型 | 回退至 `ARI_MODEL` |
| `ARI_MODEL_LINEAGE` | 停滞/沿袭决策使用的模型（v0.7.0） | 回退至 `ARI_MODEL` |
| `ARI_MODEL_ROOT_SELECT` | 选取种子 idea 使用的模型 | 回退至 `ARI_MODEL` |
| `ARI_MODEL_IDEA` | `generate_ideas` 使用的模型 | 回退至 `ARI_MODEL` |
| `ARI_MODEL_REPLICATE` | 复现器高层推理使用的模型（v0.7.0） | 回退至 `ARI_MODEL` |
| `ARI_MODEL_REPLICATOR` | `ari-skill-paper-re.build_reproduce_sh` 使用的模型 | 回退 |
| `ARI_MODEL_RUBRIC_GEN` | `ari-skill-replicate.generate_rubric` 使用的模型 | 回退 |
| `ARI_MODEL_RUBRIC_AUDIT` | `ari-skill-replicate.audit_rubric` 使用的模型 | 回退 |
| `LLM_MODEL` | 跨技能回退（`ari-skill-transform`、`ari-skill-plot` 使用） | （无） |
| `LLM_API_BASE` | `LLM_MODEL` 的 API base | （无） |

### BFTS 探索

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_MAX_NODES` | BFTS 节点硬性上限 | （由 workflow 控制） |
| `ARI_MAX_DEPTH` | 树深度硬性上限 | （由 workflow 控制） |
| `ARI_MAX_REACT` | 每节点 ReAct 迭代上限 | （由 workflow 控制） |
| `ARI_PARALLEL` | 并发节点执行器数 | `1` |
| `ARI_TIMEOUT_NODE` | 每节点挂墙时间上限（秒） | （无） |
| `ARI_RECURSION_DEPTH` | 嵌套 ARI 运行中的当前深度（自动设置） | （自动） |
| `ARI_MAX_RECURSION_DEPTH` | orchestrator 递归上限 | `3` |
| `ARI_PARENT_RUN_ID` | 递归时父运行 id（自动设置） | （自动） |
| `ARI_DISABLED_TOOLS_FOR_CHILD` | 子运行裁剪的工具集 | （无） |
| `ARI_REACT_MEMORY_SEARCH_LIMIT` | `search_memory` `top_k` 上限 | （技能默认值） |

### 后端 + 执行器

| 变量 | 用途 |
|---|---|
| `ARI_BACKEND` | 智能体运行时的后端选择器 |
| `ARI_EXECUTOR` | 执行器后端（sync / async） |
| `ARI_CONTAINER_IMAGE` | 沙箱执行用的 SIF / OCI 镜像 |
| `ARI_CONTAINER_MODE` | `exec` / `shell`（singularity 调用方式） |
| `ARI_CONTAINERS_DIR` | 容器镜像缓存根目录 |
| `ARI_MAX_CHILD_PROCS` | coding 沙箱内的 RLIMIT_NPROC 上限（默认 1024） |
| `ARI_LOG_LEVEL` | Python `logging` 级别（`INFO` / `DEBUG` / ...） |

### 记忆后端

| 变量 | 用途 |
|---|---|
| `ARI_MEMORY_BACKEND` | `letta`（默认）或 `in_memory`（无需 Letta；仅用于本地冒烟测试的短暂内存后端） |
| `ARI_MEMORY_AUTO_RESTORE` | 恢复时自动从 `memory_backup.jsonl.gz` 还原 |
| `ARI_MEMORY_ACCESS_LOG` | `memory_access.jsonl` 路径 |
| `ARI_CURRENT_NODE_ID` | 由智能体循环设置；技能读取但不设置 |
| `ARI_LETTA_VENV` | 捆绑 Letta 服务器的虚拟环境路径 |

### 评审规范 + 论文评审

| 变量 | 用途 |
|---|---|
| `ARI_RUBRIC` | 选择激活的 `reviewer_rubrics/<id>.yaml` |
| `ARI_RUBRIC_DIR` | 覆盖规范目录 |
| `ARI_STRICT_DYNAMIC` | 为 `ari-skill-paper` 强制动态轴生成 |
| `ARI_NUM_REFLECTIONS` | `review_compiled_paper` 中的反思轮数 |
| `ARI_NUM_REVIEWS_ENSEMBLE` | 规范评审的集成数量 |
| `ARI_JUDGE_N_RUNS` | `grade_with_simplejudge` 的 SimpleJudge 重运行次数 |

### 规范自动生成（v0.7.0）

| 变量 | 用途 |
|---|---|
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | `generate_rubric` 的目标叶节点数 |
| `ARI_RUBRIC_GEN_TEMPERATURE` | LLM temperature 覆盖 |
| `ARI_RUBRIC_GEN_TWO_STAGE` | 使用两阶段骨架 + 子树合成 |
| `ARI_PAPERBENCH_RUBRIC_DIR` | 覆盖 venue 条件化 PaperBench 规范模板的搜索根（未发布 — 见 `docs/reference/rubric_schema.md#venue-conditioned-templates`） |

### PaperBench 可重现性（v0.7.0）

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_PAPERBENCH_PATH` | 覆盖捆绑的 `vendor/paperbench/` 路径 | `vendor/paperbench/` |
| `ARI_REPLICATOR_TIME_LIMIT_SEC` | `run_reproduce` 的挂墙时间上限 | `43200`（12 小时） |
| `ARI_REPLICATOR_ITERATIVE` | 使用迭代式复现器智能体 | – |
| `ARI_REPLICATOR_MAX_STEPS` | 迭代开启时的迭代上限 | – |

### Orchestrator 技能

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_ORCHESTRATOR_PORT` | MCP 服务器端口 | `9890` |
| `ARI_ORCHESTRATOR_LOGS` | 日志目录 | `$ARI_WORKSPACE/orchestrator_logs` |
| `ARI_ORCHESTRATOR_DRY_RUN` | 跳过真实的 `ari run`（冒烟测试） | – |
| `ARI_ORCHESTRATOR_SSE_ONESHOT` | 单次 SSE 响应模式 | – |
| `ARI_ORCHESTRATOR_SSE_TIMEOUT` | SSE 超时（秒） | – |

### Transform 技能

| 变量 | 用途 |
|---|---|
| `ARI_TRANSFORM_MEMORY_MAX_CHARS` | 每次调用的总内存预算 |
| `ARI_TRANSFORM_MEMORY_MAX_ENTRIES` | 每次调用的条目上限 |

### Web / 检索技能

| 变量 | 用途 |
|---|---|
| `ARI_RETRIEVAL_BACKEND` | `semantic_scholar` / `arxiv` / `alphaxiv` |

### 发布 + registry + clone

| 变量 | 用途 |
|---|---|
| `ARI_PUBLISH_DRYRUN` | 强制 `--dry-run`（CI 安全开关，v0.7.0） |
| `ARI_PUBLISH_SETTINGS` | 发布设置 JSON 路径 |
| `ARI_REGISTRY_DATA` | `ari registry serve` 的 sqlite + artifact 根目录（必须设置） |
| `ARI_REGISTRY_TOKEN` | `ari clone ari://...` 和 `ari ear publish --backend ari-registry` 的 bearer token |
| `ARI_REGISTRY_URL` | 覆盖 registry 端点 |
| `ARI_REGISTRY_NAME` | 列出多个 registry 时的默认 registry 名称 |
| `ARI_REGISTRIES_FILE` | 覆盖 `registries.yaml` 位置（否则在当前检查点下查找） |
| `ARI_LOCAL_TARBALL_OUT` | `local-tarball` 发布后端的输出路径 |
| `ARI_GH_REPO` | `gh` 后端的 GitHub 仓库目标 |
| `ARI_GH_MODE` | `gh` 后端的 `release` / `repo` 模式 |
| `ARI_CLONE_HTTP_TIMEOUT` | `ari clone` 的 HTTP 超时 |

### SLURM 默认值

| 变量 | 用途 |
|---|---|
| `ARI_SLURM_PARTITION` | 默认分区 |
| `ARI_SLURM_CPUS` | 默认 `--cpus-per-task` |
| `ARI_SLURM_GPUS` | 默认 `--gres=gpu:N` |
| `ARI_SLURM_MEM_GB` | 默认内存请求 |
| `ARI_SLURM_WALLTIME` | 默认 `--time` |
| `ARI_SLURM_ALLOW_NO_GRES` | `1` ⇒ 当集群未为 GPU 配置 GRES 时，静默丢弃 `--gres` / `--gpus-*` 标志（旧版 v0.7.2 行为）。默认（未设置）⇒ 抛出带有可操作信息的 `RuntimeError`，防止 GPU 请求悄无声息地在 CPU 上运行。 |

### PaperBench 复现阶段（Stage 2）

| 变量 | 用途 |
|---|---|
| `ARI_PHASE1_SANDBOX` | `auto` / `local` / `docker` / `apptainer` / `singularity` / `slurm`。强制指定 `server.run_reproduce` 和 `bridge.reproduce_submission` 使用的沙箱运行器。 |
| `ARI_PHASE1_DOCKER_IMAGE` | `sandbox_kind=docker` 且未显式提供 `container_image` 时的默认 docker 镜像。默认为 `ubuntu:24.04`。 |
| `ARI_PHASE1_APPTAINER_IMAGE` | `sandbox_kind=apptainer`/`singularity` 且未显式提供 `container_image` 时的默认 SIF / docker URI。 |
| `ARI_PHASE1_SINGULARITY_IMAGE` | `ARI_PHASE1_APPTAINER_IMAGE` 的旧版别名。 |
| `ARI_PHASE1_ALLOW_FALLBACK` | `1` ⇒ 当请求的沙箱工具缺失（docker daemon / apptainer / sbatch / partition）时，仅发出警告并回退到本地执行（旧版 v0.7.2 行为）。默认（未设置）⇒ 抛出 `RuntimeError`，防止用户的隔离意图被悄无声息地绕过。 |
| `ARI_PAPERBENCH_PATH` | 覆盖 vendored PaperBench 源代码树路径（默认：`ari-skill-paper-re/vendor/paperbench/project/paperbench`）。 |
| `ARI_REPLICATOR_TIME_LIMIT_SEC` | 调用者传入 `0` 时默认的 Stage 1 智能体展开时间预算。 |
| `ARI_REPLICATOR_ITERATIVE` | `1` ⇒ Stage 1 展开默认使用 IterativeAgent 变体。 |
| `ARI_REPLICATOR_MAX_STEPS` | 默认 Stage 1 步数上限。 |
| `ARI_AGENT_ENV_PATH` | vendor 风格 `agent.env` 文件（每行一个 `KEY=VALUE`）的默认路径，当 `bridge.rollout_submission` 的 `agent_env_path` 参数未设置时自动加载。此变量也为空时回退到 `~/.ari/agent.env`。用于向 Stage 1 智能体暴露论文特定凭据（例如 `HF_TOKEN`）。 |
| `HF_TOKEN` | Hugging Face Hub token。在调用进程中设置时，`bridge.rollout_submission` 会自动将其转发到智能体环境中（vendor `nano/eval.py:172-179` 知名凭据模式）。任何 Stage 1 展开会调用 `huggingface-cli login` 的 PaperBench 论文都需要此 token。 |
| `ARI_JUDGE_N_RUNS` | 向导 / 调用者传入 `0` 时 SimpleJudge 调用的默认 `n_runs`。PaperBench 论文 §4.1 单次默认值为 1。 |
| `ARI_MODEL_JUDGE` | 默认 judge 模型 id（LiteLLM 路由）。 |
| `ARI_MODEL_REPLICATOR` | 默认 Stage 1 展开模型 id。 |

## SLURM (`SLURM_*`)

| 变量 | 用途 |
|---|---|
| `SLURM_MODE` | `local`（默认）/ `ssh` |
| `SLURM_SSH_HOST` | 远程 SLURM 模式的 SSH 主机 |
| `SLURM_SSH_USER` | SSH 用户（默认为当前用户） |
| `SLURM_SSH_PORT` | SSH 端口（默认 `22`） |
| `SLURM_SSH_KEY` | 私钥路径 |
| `SLURM_SSH_PASSWORD` | 可选密码（推荐使用密钥） |
| `SLURM_DEFAULT_PARTITION` | ARI 提交子作业的默认分区 |
| `SLURM_PARTITION` | 单作业分区覆盖 |
| `SLURM_VALID_PARTITIONS` | 逗号分隔的允许列表 |
| `SLURM_LOG_DIR` | `*.out` / `*.err` 的写入位置 |
| `SLURM_CLUSTER_NAME` | 仪表盘中显示的集群名称 |
| `SLURM_JOB_ID` / `SLURM_JOB_NODELIST` / `SLURM_JOB_PARTITION` | ARI 在作业内运行时由 SLURM 本身设置 |

## Letta (`LETTA_*`)

| 变量 | 用途 |
|---|---|
| `LETTA_BASE_URL` | Letta API base（默认 `http://127.0.0.1:8283`） |
| `LETTA_API_KEY` | Letta 需要认证时的 API 密钥 |
| `LETTA_EMBEDDING_CONFIG` | 嵌入配置 JSON 路径（必需） |

## Ollama / OpenAI (`OLLAMA_*` / `OPENAI_*`)

| 变量 | 用途 |
|---|---|
| `OLLAMA_HOST` | Ollama 监听地址（默认 `127.0.0.1:11434`） |
| `OLLAMA_BASE_URL` | LiteLLM 侧的 base URL |
| `OPENAI_API_KEY` | OpenAI / OpenAI 兼容 API 密钥 |

## VLM

| 变量 | 用途 | 默认值 |
|---|---|---|
| `VLM_MODEL` | 图表 / 表格审阅用的视觉 LLM | `openai/gpt-4o` |

## 另请参阅

- `docs/reference/configuration.md` — 按用途分组的相同环境变量叙述导览。
- `ari-core/ari/config.py` — 使用大部分 `ARI_*` 变量的 Pydantic 设置模型。
- 每个技能的 `README.md` — 该技能特有的环境变量。
