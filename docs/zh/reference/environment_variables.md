---
sources:
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: scripts/setup/setup_env.sh
    role: config
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-skill-tool-registry/src/server.py
    role: implementation
last_verified: 2026-07-29
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
| `ARI_MODEL_PAPER` | 论文写作与修订模型 | 回退至 `ARI_LLM_MODEL` |
| `ARI_MODEL_RUBRIC` | 独立rubric评审与固定论文面板模型 | 回退至 `ARI_LLM_MODEL` |
| `ARI_PANEL_SEED` | 为固定评审面板的每次 rubric 调用记录的请求 seed | 未设置；能否控制采样取决于提供方和后端 |
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

### Claude Code 后端（`ARI_CLAUDE_CODE_*`）

仅在 `ARI_BACKEND=claude_code` / `llm.backend: claude_code` 时读取 —— 参见
[claude_code_provider.md](./claude_code_provider.md)。

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_CLAUDE_CODE_MODE` | `strict_reproducibility`（每次调用启动全新 `claude -p`）或 `low_overhead`（常驻 Agent SDK worker，每个请求全新 query） | `strict_reproducibility` |
| `ARI_CLAUDE_CODE_MODEL` | 模型覆盖，仅当解析后的后端为 `claude_code` 时生效 | `llm.model` |
| `ARI_CLAUDE_CODE_MAX_TURNS` | 每次调用的 `--max-turns`（>1 需要 `allow_multi_turn`） | `1` |
| `ARI_CLAUDE_CODE_TIMEOUT_SEC` | 每次调用的子进程/SDK 超时 | `300` |
| `ARI_CLAUDE_CODE_RECORD_PROVENANCE` | 将每次调用的工件持久化到 `{checkpoint}/claude_code/{call_id}/`（`1`/`0`） | `1` |
| `ARI_CLAUDE_CODE_BIN` | Claude Code 可执行文件 | `claude` |
| `ANTHROPIC_AUTH_TOKEN` | `ANTHROPIC_API_KEY` 的令牌认证替代；二者任一存在即可启用 hermetic 的 `--bare` 配置 | （无） |

### Idea 技能 — VirSci-live

`generate_ideas` 的可选 vendor 封装路径。默认关闭时保持当前行为（轻量级的重新实现
讨论循环）。开启后，`generate_ideas` 会在实时 Semantic Scholar 快照上运行 VirSci
真实的多智能体机制；缺少依赖 / 出现任何运行时错误时会降级到重新实现循环。讨论 LLM
遵循 `ARI_MODEL_IDEA`。

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_IDEA_VIRSCI_REAL` | 切换真实的 vendor 封装路径（`1`/true）。未设置 ⇒ 当前的重新实现行为 | （未设置 / 关闭） |
| `ARI_IDEA_VIRSCI_K` | 讨论轮数（vendor `group_max_discuss_iteration`） | `7` |
| `ARI_IDEA_VIRSCI_TEAM_SIZE` | 团队成员数上限（vendor `max_teammember`） | `3` |
| `ARI_IDEA_VIRSCI_N_AUTHORS` | `select_coauthors` 的作者池大小 | `16` |
| `ARI_IDEA_VIRSCI_N_PAPERS` | SPECTER2 检索语料库大小 | `800` |
| `ARI_IDEA_VIRSCI_MAX_TEAMS` | 通过 `generate_idea` 的团队数上限 | `=n_ideas` |
| `ARI_IDEA_VIRSCI_SPECTER2_MODEL` | 本地查询嵌入模型 | `allenai/specter2_base` |

### BFTS 探索

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_MAX_NODES` | BFTS 节点硬性上限 | （由 workflow 控制） |
| `ARI_MAX_DEPTH` | 树深度硬性上限 | （由 workflow 控制） |
| `ARI_MAX_REACT` | 每节点 ReAct 迭代上限 | （由 workflow 控制） |
| `ARI_PARALLEL` | 并发节点执行器数 | `1` |
| `ARI_TIMEOUT_NODE` | 每节点挂墙时间上限（秒） | （无） |
| `ARI_BFTS_ALLOW_WEB` | 可选：在**探索期间**向 BFTS 节点智能体暴露 `web-skill`（web_search / fetch_url / arXiv / Semantic Scholar）。默认关闭以保持搜索循环可重现（P5）；开启后，ARI 会记录不可重现轨迹标记（`bfts_web_provenance.json`）。`idea-skill` 的 `survey` 无论如何都会进行有界的文献检索。`1`/`true`/`yes`/`on` 启用 | `false` |
| `ARI_RECURSION_DEPTH` | 嵌套 ARI 运行中的当前深度（自动设置） | （自动） |
| `ARI_MAX_RECURSION_DEPTH` | orchestrator 递归上限 | `3` |
| `ARI_PARENT_RUN_ID` | 递归时父运行 id（自动设置） | （自动） |
| `ARI_DISABLED_TOOLS_FOR_CHILD` | 子运行裁剪的工具集 | （无） |
| `ARI_REACT_MEMORY_SEARCH_LIMIT` | `search_memory` `top_k` 上限 | （技能默认值） |

### 执行模式（RQGM）

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_MODE` | 执行模式覆盖：`simple_bfts` \| `ari_rqgm`（覆盖 workflow.yaml 中的 `ari.mode`；无效值警告并忽略）。RQGM 激活还需要 `ARI_RQGM_ENABLED` 联锁 —— 任何不一致都回退到 `simple_bfts`。`export_resolved_config_to_skill_env` 会将其 `setdefault` 为技能子进程的*生效*模式（v1 中没有任何技能读取它）。在 `ari resume` 时，`rqgm_state.json` 中持久化的模式优先于此变量。见 `docs/guides/execution_modes.md` | `simple_bfts` |
| `ARI_RQGM_ENABLED` | RQGM 主联锁覆盖：`0`/`1`/`true`/`false`（覆盖 workflow.yaml 中的 `rqgm.enabled`）。此变量与 `ARI_MODE=ari_rqgm` 必须同时一致，治理运行时才会被构造 | `false` |
| `ARI_PAPER_AGENT_AS_JUDGE` | agent-as-judge 草稿评分覆盖：`0`/`1`/`true`/`false`（覆盖 `rqgm.paper.reviewer.agent_as_judge.enabled`；无效值警告并忽略）。由 `apply_paper_env_overrides` 应用，采用与 `ARI_PAPER_MODE` / `ARI_RQGM_PAPER_ENABLED` 相同的「先校验后赋值」策略。关闭 ⇒ 使用确定性的、不调用 LLM 的会议评分表评分器，草稿评分路径上不会出现实时 LLM 调用（P2）。开启 ⇒ 由真实 `LLMClient` 支撑的审稿人按*同一套*会议评分表的维度为每份存档草稿打分，权重取自当前 ACTIVE 的受治理 `paper_reviewer` 提示的侧重点，并且可以读取确定性读取器无法读取的维度（`novelty`、`significance`）。当 LLM 出错、回复无法解析、或回复覆盖的评分表维度权重过少时，会开放式回退到确定性评分表。仅在生效的 `rqgm_archive` 论文模式（`ARI_PAPER_MODE=rqgm_archive` + `ARI_RQGM_PAPER_ENABLED=1`）下才有意义 | （未设置 ⇒ 关闭） |

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
| `ARI_MEMORY_CONSOLIDATE` | 类型化记忆整合 + 为论文论断提供基于工件支撑的 `verified_context.json`。**默认开启**；设为 `0`/`false`/`no`/`off` 以禁用 |
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

### 论断–证据门

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_CLAIM_GATE_MODE` | 论断–证据 / 指标正确性门的评估开关。`off` 从不阻断；`warn` 报告错误 / 警告但从不阻断 finalize；`strict` 在存在阻断性错误时阻断最终门 | `warn`（`off` / `warn` / `strict`） |
| `ARI_COMPARISON_SCOPE` | 控制跨环境比较被视为透明性警告（`any`）还是阻断性错误（`same_environment`，用于单一架构优化研究） | `any`（`any` / `same_environment`） |

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

### Federated tool registry 技能

技能开关与目录是两道彼此独立的门：启用 `ari-skill-tool-registry` 不会启用任何
叶子工具，因为只有出现在所选 lock 中的 source 才能执行。

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_TOOL_REGISTRY_LOCK` | broker 在进程启动时加载的、经评审的 `CATALOG.lock`。ARI 自身的 Provider 目录加载器读取同一个变量，因此两者不会对 composite provision 所描述的叶子工具产生分歧。已物化的目录包含绝对本地路径，无法放入仓库，该覆盖项是到达它的唯一方式 | 与技能一同打包的 `CATALOG.lock`；它是可移植的默认值，而已填充的目录属于机器特定证据，因此按设计签入时为空 |
| `ARI_TOOL_REGISTRY_INDEX` | 与该 lock 对应的派生目录索引 | 已解析 lock 同目录下的 `catalog.index.json`；该文件不存在时从 lock 重新构建 |

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
| `ARI_AGENT_ENV_PATH` | vendor 风格 `agent.env` 文件（每行一个 `KEY=VALUE`）的默认路径，当 `bridge.rollout_submission` 的 `agent_env_path` 参数未设置时自动加载。此变量也为空时回退到 `~/.ari/agent.env`。该 vendored 的 PaperBench-replicate 凭据查找（`ari-skill-paper-re/src/_paperbench_bridge.py`）与 v0.5.0 移除的 ARI 自身 `$HOME/.ari/` 运行存储不同，因此该回退仍然有效。用于向 Stage 1 智能体暴露论文特定凭据（例如 `HF_TOKEN`）。 |
| `HF_TOKEN` | Hugging Face Hub token。在调用进程中设置时，`bridge.rollout_submission` 会自动将其转发到智能体环境中（vendor `nano/eval.py:172-179` 知名凭据模式）。任何 Stage 1 展开会调用 `huggingface-cli login` 的 PaperBench 论文都需要此 token。 |
| `ARI_JUDGE_N_RUNS` | 向导 / 调用者传入 `0` 时 SimpleJudge 调用的默认 `n_runs`。PaperBench 论文 §4.1 单次默认值为 1。 |
| `ARI_MODEL_JUDGE` | 默认 judge 模型 id（LiteLLM 路由）。 |
| `ARI_MODEL_REPLICATOR` | 默认 Stage 1 展开模型 id。 |

### GUI 服务器（`ARI_GUI_*`）

八个开关支配 `ari viz` 仪表盘外壳、它的网络暴露方式以及它的运维接口面。
八个变量全部由 `scripts/setup/setup_env.sh` 声明（默认注释掉），并且全部是
**回滚手段**：不设置它们即得到当前默认行为，设置它们则可在不重新部署的
前提下恢复某个有文档记录的旧行为。

| 变量 | 默认值（未设置） | 设置后的效果 | 回滚语义 |
|---|---|---|---|
| `ARI_GUI_V2` | 开启（`1`） | `0` / `false` 回退到 legacy 仪表盘外壳。 | v2 外壳的紧急开关；移除关卡为 G6。 |
| `ARI_GUI_BIND` | 仅回环（`127.0.0.1` + `::1`） | 一个绑定地址：`::` = legacy 的全接口双栈，`0.0.0.0` = IPv4 通配符，或单个地址。 | 恢复历史上的全接口绑定。任何非回环值都会把服务器切换到**远程模式**（见 `ARI_GUI_TOKEN`）。 |
| `ARI_GUI_CORS_ANY` | 关闭 —— 仅同源回显 | `1` 恢复 legacy 的 `Access-Control-Allow-Origin: *` 通配符。 | 只有跨源隧道/门户拓扑才需要；`:5173` 上的 Vite 开发代理**不**需要它。 |
| `ARI_GUI_CHALLENGES` | 开启 —— 需要挑战 | `0` 关闭 delete-checkpoint / stop / gpu-monitor-stop 上服务器签发的确认挑战，恢复直接执行。 | 开启时，这些端点在没有有效 `challenge_id` 时返回 `428`；无论哪种情况签发端点都保持可用。 |
| `ARI_GUI_CSP` | 开启 —— 发送响应头 | `0` 会从 GUI 首页/静态响应中去掉 `Content-Security-Policy`、`X-Content-Type-Options` 与 `Referrer-Policy`。 | 仅当某种代理拓扑重映射了 WebSocket 端口而策略把它拦下时才需要（此时 GUI 会降级为轮询）。 |
| `ARI_GUI_TOKEN` | 未设置 | 远程模式所需的 bearer token：除 `/health*` 前缀外的每个请求都必须发送 `Authorization: Bearer <token>`；SSE 与 WebSocket 接受 `?token=` 形式。 | **在远程绑定下**不设置是安全失败而非开放：服务器在启动时生成一个随机 32 位十六进制 token，并向 stderr 打印一次。在回环默认配置下从不需要它。 |
| `ARI_GUI_AUTH` | 开启（在远程模式下） | `0` 关闭远程 token 闸门，恢复无认证的远程绑定。 | 这是为自行终结认证的可信网络准备的、有文档记录的逃生舱（例如一个负责认证的反向代理）。回环绑定无论如何都是无认证的。 |
| `ARI_GUI_HEALTH` | 开启 | `0` 关闭运维可见性接口面：`GET /health/live` 与 `/health/ready` 回落到 SPA 响应，`GET /api/v1/diagnostics` 返回类型化的 404。 | 为那些绝不能看到新 JSON 的探针抓取拓扑，恢复引入探针之前的精确线上行为。 |

完整的信任模型见 [REST API → 认证](rest_api.md#认证)，挑战协议见
[REST API → 确认挑战](rest_api.md#确认挑战)。

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
