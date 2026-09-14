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
  - path: ari-core/ari/rqgm/state.py
    role: implementation
  - path: ari-core/ari/assurance/executors.py
    role: implementation
  - path: ari-core/ari/harness_registry.py
    role: implementation
  - path: ari-core/ari/evaluator/deterministic_evaluator.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/ari/cli/commands.py
    role: implementation
  - path: ari-core/ari/agent/loop.py
    role: implementation
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
last_verified: 2026-08-16
---

# 环境变量参考

ARI 支持 160 多个环境变量，在此汇总以便查阅。大多数变量有合理的默认值；**Required?** 列标记了全新检出时不可缺少的变量。

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
| `ARI_ROOT` | ARI 源代码树根目录 —— 不只用于测试，生产路径中 `ari.mcp.connection`（skill 启动）与 `ari.config` 也会读取 | （由包位置自动检测） | – |
| `ARI_SOURCE_FILE` | 覆盖输入 experiment.md 路径 | （无） | – |

`ARI_CHECKPOINT_DIR` 还带有一条表格无法表达的写入侧**约定**。把当前进程钉到某次
运行的代码，应当调用 `PathManager.set_checkpoint_dir_env`（它委托给
`RuntimePathResolver.set_checkpoint_dir_env`，即 `ari-core/ari/paths.py` 中唯一
对 `os.environ["ARI_CHECKPOINT_DIR"]` 赋值的函数），而不是自行赋值，从而让这个
运行 pin 只有一个所有者。请把它读作约定，而非保证：

- **没有任何强制手段。** 当写入方直接给该变量赋值时，不会有任何测试、lint 规则或
  导入边界检查失败。该 helper 目前被 pipeline driver、Letta 客户端、`ari memory`、
  `ari viz` 的三个模块以及两个 CLI 入口点采用。
- **存在一处已知的绕过。** `ari-core/ari/agent/loop.py` 在构建节点的 tool context
  之前直接给 `os.environ["ARI_CHECKPOINT_DIR"]` 赋值，因此该 helper docstring 中
  「让每个写入方都经由 PathManager」的说法夸大了代码实际做到的事情。请把那句话
  当作意图，而不是事实。
- **子进程的 env 字典不在此规则范围内。** GUI launch、orchestrator 与 experiment
  三条路径是在交给子进程的 `proc_env` 映射上设置该键，并不修改当前进程的环境，
  因此不算绕过。

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
| `ARI_MODEL_JUDGE` | PaperBench SimpleJudge（`grade_with_simplejudge`）使用的模型 | 回退至 `ARI_LLM_MODEL`，再回退至 `gpt-5-mini` |
| `ARI_MODEL_LINEAGE` | 停滞/沿袭决策使用的模型（v0.7.0） | 回退至 `ARI_MODEL` |
| `ARI_MODEL_ROOT_SELECT` | 选取种子 idea 使用的模型 | 回退至 `ARI_MODEL` |
| `ARI_MODEL_IDEA` | `generate_ideas` 使用的模型 | 回退至 `ARI_MODEL` |
| `ARI_MODEL_REPLICATE` | **运行时无效**。该名称已改为 `ARI_MODEL_REPLICATOR`；仅存的读取方是旧版 Settings 卡片，用于填充所显示的 `ors.replicator_model` 默认值。复现器本身读取的是 `ARI_MODEL_REPLICATOR` | （Settings 默认值 `claude-opus-4-7`） |
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
| `ARI_PARALLEL` | 并发节点执行器数 | `4` |
| `ARI_TIMEOUT_NODE` | 每节点挂墙时间上限（秒） | `7200`（2 小时） |
| `ARI_BFTS_ALLOW_WEB` | 可选：在**探索期间**向 BFTS 节点智能体暴露 `web-skill`（web_search / fetch_url / arXiv / Semantic Scholar）。默认关闭以保持搜索循环可重现（P5）；开启后，ARI 会记录不可重现轨迹标记（`bfts_web_provenance.json`）。`idea-skill` 的 `survey` 无论如何都会进行有界的文献检索。`1`/`true`/`yes`/`on` 启用 | `false` |
| `ARI_RECURSION_DEPTH` | 嵌套 ARI 运行中的当前深度（自动设置） | （自动） |
| `ARI_MAX_RECURSION_DEPTH` | orchestrator 递归上限 | `3` |
| `ARI_PARENT_RUN_ID` | 递归时父运行 id（自动设置） | （自动） |
| `ARI_DISABLED_TOOLS_FOR_CHILD` | **惰性 —— 已预留，无读取方。** `ari/cli/lineage.py` 只为 lineage 子运行设置空字符串，树中没有任何代码回读它，因此不会裁剪任何工具。`disabled_tools` 仅从 YAML 填充。请勿依赖它。 | （无） |
| `ARI_REACT_MEMORY_SEARCH_LIMIT` | `search_memory` `top_k` 上限 | （技能默认值） |
| `ARI_NODE_EXEC_BUDGET_S` | 由该节点全部 `run_bash` / `run_code` 调用共享的每节点挂墙时间预算。单次调用受它自己的超时约束，但此前没有任何东西约束这些调用的**总和**，于是一个节点可能把整个每节点超时全耗在 shell 调用上，最后被杀掉且完全没有留下报告。预算用尽后调用会被拒绝，且任何单次调用都不得超出剩余额度。`0` 表示禁用 | `1800` |
| `ARI_NODE_COMPUTE_BUDGET_NS` | 面向**调度器**工作的每节点预算，单位是**节点秒**（`nodes` × 挂墙时间）—— 也就是调度器分配资源所用的单位。`ARI_NODE_EXEC_BUDGET_S` 计的是 `run_bash`/`run_code`，那是单台机器上的时间；而提交作业此前完全不计费，于是一个节点可能在半小时本地 shell 之后被拒绝，而一个一千节点、两小时的作业却分文不计。计费发生在**提交**时、按**预留**计，而不是在完成时按实际耗时计：一个事后才知道成本的预算什么也拒绝不了，而且无论作业的活何时干完，调度器都一直占着整份预留。超预算的提交会在到达调度器**之前**被拒绝，因为已排队的预留无论后续发生什么都会被占住。`slurm_submit`、`job_submit` 与 `container_submit` 一视同仁。无论是否设置了预算，预留都会以 `resource_measurement_basis: declared-reservation` 写入成本轨迹，因此「这次搜索用掉了多少集群资源」两种情况下都答得出来。未设置 / `0` = 不设限 | （未设置 ⇒ 不设限） |
| `ARI_V2_SUPPRESS_TOOLS` | 在**搜索循环**中隐藏 `describe_environment` / `run_code` / `emit_results`（它们对其他所有阶段、以及 ARI 的其他使用者仍然可用）。每隐藏一次调用，就把一步还给「真正去改 kernel」，在 20 步预算下这并非小事。设计为可选启用，因为它不是一次局部裁剪：`system.md` 把*完成*的条件挂在 `emit_results` 上，所以启用它同时也会改写那句话 —— 否则智能体将面对一个自己无法满足的停止条件 —— 并且一次运行被评分所经由的证据路径也会随之改变。论文复现路径恰恰需要这几个工具，因此不明确要求就什么都不隐藏 | （未设置 ⇒ 提供全部工具） |

### 任务 + 问题的选择

决定一次运行以什么为评分对象。`ARI_PROBLEM` 指名一个**被 pin 住的问题**，这是受
支持的路径；`ARI_TASK` 走的是较早的原型 harness 注册表，只有在没有 pin 住问题时
才会被用于评分。

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_PROBLEM` | 本次运行据以测量的、被 pin 住的问题。设置后，评估经由 `assurance_measure` 进行，每个节点的 `work_dir` 都从该问题声明的 `score_inputs` 播种 —— 于是没有任何未被追踪的目录树能决定这个数字。播种绝不覆盖：子节点的 `work_dir` 是父节点的副本，而父节点的候选本身*就是* handoff | （未设置 ⇒ 走 `ARI_TASK` 路径） |
| `ARI_TASK` | 原型 harness 注册表使用的任务名。**设置了但无法识别**的任务会报错，而不是回落到 `spmm`：测的是另一个基准却按被请求的那个来报告，正是该注册表存在的目的所要杜绝的。同时提供 handoff 运行目录名中的 task 部分，与 `ARI_PROBLEM` 无关 | `spmm`（命名时为 `task`） |
| `ARI_HARNESS` | 当一个任务有多个 harness 可用时选哪一个。注册表**拒绝替你选择**：把排序在前的那个悄悄绑定上去，会让分数取决于目录名，并且把这个数字归属给任务而不是产生它的 harness。同名时，注册在 workspace 下的 harness 胜过随包发布的那个，且该选择会记入 provenance | （无） |
| `ARI_SEED` | 让本地模型的运行可复现的固定采样 seed（`llm.seed`）；非整数取值被忽略而不是抛错。同时作为 handoff 运行目录名中的 seed 部分 —— 正是它化解了跨 arm、跨 seed 在同一秒生成的 run id 冲突 | （未设置 ⇒ 后端默认；命名时为 `0`） |

### 父→子 handoff（`ARI_HANDOFF_*`）

由 `apply_handoff_env_overrides` 在 profile 覆盖**之后**应用，因此显式选择胜出。
`ARI_HANDOFF_MODE` 会重建 `HandoffConfig`，使 mode→通道的解析重新跑一遍；下面
各个单独开关随后可为消融实验覆盖单条通道。对应的配置项位于 `handoff:` 块下。

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_HANDOFF_MODE` | 选择 arm，例如 `disabled` / `code_only` / `summary_only` / `code_plus_summary` / `code_plus_full_log` / `evidence_only` / `evidence_plus_reflection`。同时按 `ARI_TASK` / `ARI_SEED` 把运行目录命名为 `<task>_<mode>_seed<seed>`，让目录名讲清楚「继承了什么」，而不是在所有 arm 上重复同一个目标 slug。无法识别的取值只是在 **arm 选择**上被忽略；命名分支只要取值非空就照常生效，于是拼错的 mode 会在以该拼写命名的目录下跑配置解析出的那个 arm | （配置） |
| `ARI_HANDOFF_COPY_WORKDIR` | 子节点是否继承父节点的 work_dir（工件 / 代码通道） | （由 mode 决定） |
| `ARI_HANDOFF_AGENT_BLOCK` | 把父节点的操作性摘要注入子节点的智能体提示 | （由 mode 决定） |
| `ARI_HANDOFF_PLANNER_BLOCK` | 把父节点的摘要注入规划器提示。它在两处被读取，且真值判定不同：配置侧的覆盖只接受 `1`/`true`/`yes`/`on`，而注入侧把除 `0`/`false`/`no`/`off` 之外的任何取值都当作开。因此这四种拼写以外的取值，在配置侧读作关、在写入该块的地方读作开。请使用这四种之一 | （由 mode 决定） |
| `ARI_HANDOFF_MEMORY_OFF` | 抑制事实上的记忆通道，使某个 arm 除了它显式的 handoff 通道之外拿不到任何操作状态。退出时的备份仅在字面值 `1` 时跳过；`true`/`yes`/`on` 虽然关掉了通道，checkpoint 里仍会留下一份记忆备份 | （由 mode 决定） |
| `ARI_HANDOFF_LOG_MODE` | `none` / `full` / `truncated` / `masked` —— 父节点的执行日志传递多少 | （由 mode 决定） |
| `ARI_HANDOFF_LOG_LIMIT` | 注入的父节点日志的字符数上限 | `48000` |
| `ARI_HANDOFF_SUMMARY_FORM` | `extractive` / `rolling` / `failure_only` / `evidence` / `evidence_reflection` | （由 mode 决定） |
| `ARI_HANDOFF_SUMMARY_FIELDS` | 摘要字段的逗号分隔白名单（字段丢弃消融） | （全部） |
| `ARI_HANDOFF_PAIRED_MODES` | 在一次调用内成对运行的 arm，逗号分隔 | （无） |

### 执行模式（RQGM）

探索（`ARI_MODE`）与论文阶段（`ARI_PAPER_MODE`）是两个彼此独立的轴，各自都位于
一道**双钥联锁**之后：模式变量与其 `*_ENABLED` 搭档必须*同时*选择受治理路径，
否则该轴回退到自身默认值（`simple_bfts` / `linear`）。只有其中一把钥匙不会启用
任何东西。`scripts/setup/setup_env.sh` 会把下列全部变量以注释掉的模板行追加到
生成的 `.env` 中（仅在该键尚不存在时追加），并在注释里写明该联锁（「both must
agree or ARI falls back to `simple_bfts`」/「…or the paper phase falls back to
`linear`」）。

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_MODE` | 执行模式覆盖：`simple_bfts` \| `ari_rqgm`（覆盖 workflow.yaml 中的 `ari.mode`；无效值警告并忽略）。RQGM 激活还需要 `ARI_RQGM_ENABLED` 联锁 —— 任何不一致都回退到 `simple_bfts`。`export_resolved_config_to_skill_env` 会将其 `setdefault` 为技能子进程的*生效*模式（v1 中没有任何技能读取它）。在 `ari resume` 时，`rqgm_state.json` 中持久化的模式优先于此变量。见 `docs/guides/execution_modes.md` | `simple_bfts` |
| `ARI_RQGM_ENABLED` | RQGM 主联锁覆盖：`0`/`1`/`true`/`false`（覆盖 workflow.yaml 中的 `rqgm.enabled`）。此变量与 `ARI_MODE=ari_rqgm` 必须同时一致，治理运行时才会被构造 | `false` |
| `ARI_PAPER_MODE` | 论文阶段模式覆盖：`linear` \| `rqgm_archive`（覆盖 workflow.yaml 中的 `paper.mode`；无效值警告并忽略）。与 `ARI_MODE` 正交 —— 探索轴与论文轴各自独立设置。启用存档还需要 `ARI_RQGM_PAPER_ENABLED` 联锁；任何不一致都回退到 `linear`。由 `apply_paper_env_overrides` 应用，但论文命令必须**显式**调用它：论文入口的 config 加载器不施加任何 env 覆盖，因此该变量无法搭 `ari run` / `ari resume` 覆盖块的便车。参见[执行模式](../guides/execution_modes.md)的「论文执行轴：`paper.mode`」一节 | `linear` |
| `ARI_RQGM_PAPER_ENABLED` | 论文存档联锁覆盖：`0`/`1`/`true`/`false`（覆盖 workflow.yaml 中的 `rqgm.paper.enabled`；无效值警告并忽略）。此变量与 `ARI_PAPER_MODE=rqgm_archive` 必须同时一致，草稿存档才会激活 | `false` |
| `ARI_PAPER_AGENT_AS_JUDGE` | agent-as-judge 草稿评分覆盖：`0`/`1`/`true`/`false`（覆盖 `rqgm.paper.reviewer.agent_as_judge.enabled`；无效值警告并忽略）。由 `apply_paper_env_overrides` 应用，采用与 `ARI_PAPER_MODE` / `ARI_RQGM_PAPER_ENABLED` 相同的「先校验后赋值」策略。关闭 ⇒ 使用确定性的、不调用 LLM 的会议评分表评分器，草稿评分路径上不会出现实时 LLM 调用（P2）。开启 ⇒ 由真实 `LLMClient` 支撑的审稿人按*同一套*会议评分表的维度为每份存档草稿打分，权重取自当前 ACTIVE 的受治理 `paper_reviewer` 提示的侧重点，并且可以读取确定性读取器无法读取的维度（`novelty`、`significance`）。当 LLM 出错、回复无法解析、或回复覆盖的评分表维度权重过少时，会开放式回退到确定性评分表。仅在生效的 `rqgm_archive` 论文模式（`ARI_PAPER_MODE=rqgm_archive` + `ARI_RQGM_PAPER_ENABLED=1`）下才有意义 | （未设置 ⇒ 关闭） |

下面四个变量不是开关，而是可选的部署侧声明，用于让一个 RQGM epoch 的执行身份
更加具体。`capture_execution_identity` 在 epoch 开启时逐一读取它们，把未设置或
空白的值记录为字面字符串 `unresolved`，并且只要四者未全部解析，就让
`execution_identity.complete` 保持 `false` —— ARI 不会声称一个可变的提供方别名
就是固定的实现。没有任何机制验证所填的值是否属实；该 pin 是声明，不是测量。
`docs/reference/configuration.md` 也列出了同样这四个变量及其各自所钉的身份。

| 变量 | 所钉的身份 | 默认值 |
|---|---|---|
| `ARI_MODEL_REVISION` | 提供方 / 模型的精确修订 | （未设置 ⇒ 记录为 `unresolved`） |
| `ARI_TOOL_BUNDLE_REVISION` | 不可变工具包修订 | （未设置 ⇒ 记录为 `unresolved`） |
| `ARI_ENVIRONMENT_DIGEST` | 容器或环境摘要 | （未设置 ⇒ 记录为 `unresolved`） |
| `ARI_DATA_SNAPSHOT_DIGEST` | 不可变外部数据快照摘要 | （未设置 ⇒ 记录为 `unresolved`） |

`ARI_HARNESS_CONTAINER_ROOT` 在 `setup_env.sh` 的同一个块中声明，但它属于
Harness 运行基座，而不属于模式选择：

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_HARNESS_CONTAINER_ROOT` | 解析**逻辑** Harness 容器引用（`apptainer:<name>.sif` 或 `singularity:<name>.sif`）所用的绝对根目录。已验证条目之所以采用逻辑形式，正是为了让发布出去的 manifest 不含站点路径，于是具体目录只能来自环境。未设置 ⇒ 逻辑引用会以 `HarnessSubstrateError` 被拒绝；普通路径引用作为兼容输入原样通过，且完全不读取该变量。该根必须是绝对路径、真实目录且不是符号链接；解析后的镜像必须是直接位于该根下的常规文件（不能是符号链接），任何解析到根之外的情况都会被拒绝 | （无 —— 仅在使用逻辑引用时需要） |

### Manuscript Complete

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_MANUSCRIPT_MODE` | 新一次 attempt 的姿态：`off` \| `audit` \| `enforce`。它与研究模式、论文模式彼此独立；resume 无法改写已经持久化的 attempt binding。 | `off` |
| `ARI_MANUSCRIPT_REPAIR_POLICY` | repair 姿态：`disabled` \| `explicit` \| `auto`。除非生效的 manuscript 模式是 `enforce`，否则 `auto` 无效。 | `disabled` |

其余的 `ARI_MANUSCRIPT_*_PATH`、预算、拓扑与 effective-policy 变量，是由论文
dispatcher 装入的私有、限定作用域的传递值。运维人员应当通过 `workflow.yaml`
配置它们，而不要直接 export。参见
[Manuscript Complete 操作员运行手册](../guides/manuscript_complete_operations.md)。

### 后端 + 执行器

| 变量 | 用途 |
|---|---|
| `ARI_BACKEND` | 智能体运行时的后端选择器 |
| `ARI_EXECUTOR` | 执行器后端（sync / async） |
| `ARI_CONTAINER_IMAGE` | 沙箱执行用的 SIF / OCI 镜像 |
| `ARI_CONTAINER_MODE` | 容器运行时：`auto`（默认 —— 探测可用运行时，在 SLURM 作业内优先 Singularity / Apptainer） / `docker` / `singularity` / `apptainer` / `none`。不支持的取值会直接报错，而不会回退到宿主机执行 |
| `ARI_CONTAINERS_DIR` | 容器镜像缓存根目录 |
| `ARI_MAX_CHILD_PROCS` | coding 沙箱内的 RLIMIT_NPROC 上限。选择性启用：未设置即不额外设限。RLIMIT_NPROC 按 real uid 统计该用户的全部任务，而非仅本进程的后代，因此固定上限会在用户已有那么多线程时直接让 `fork` 以 EAGAIN 失败 |
| `ARI_LOG_LEVEL` | Python `logging` 级别（`INFO` / `DEBUG` / ...） |

### 记忆后端

| 变量 | 用途 |
|---|---|
| `ARI_MEMORY_BACKEND` | `letta`（默认）或 `in_memory`（无需 Letta；仅用于本地冒烟测试的短暂内存后端） |
| `ARI_MEMORY_AUTO_RESTORE` | 恢复时自动从 `memory_backup.jsonl.gz` 还原 |
| `ARI_MEMORY_ACCESS_LOG` | `on`（默认） / `off` —— memory 服务是否记录 `memory_access.jsonl`。路径本身不可配置；轮转大小由 `ARI_MEMORY_ACCESS_LOG_MAX_MB`（默认 `100`）决定 |
| `ARI_MEMORY_CONSOLIDATE` | 类型化记忆整合 + 为论文论断提供基于工件支撑的 `verified_context.json`。**默认开启**；设为 `0`/`false`/`no`/`off` 以禁用 |
| `ARI_CONTEXT_AUTHORITY_KEY` | core 为每条技能连接导出到技能子进程的 HMAC 密钥（`SkillConnection._server_params`）；记忆服务器在触及后端之前用它验证签名后的 `ari_context` 参数。由 core 注入并在结果中被脱敏，运维人员不应设置 |
| `ARI_LETTA_VENV` | 捆绑 Letta 服务器的虚拟环境路径 |

当前节点 ID **不是**环境变量，因此在环境中伪造该值无法改变记忆写入的目标。
`AgentLoop._node_tool_context` 为每个节点构建一个 `ToolCallContextV1`，
`SkillConnection.authorize_args` 将其签名后注入 `ari_context` 工具参数，
写时复制（CoW）保护（`ari-skill-memory/src/server.py` 中的 `_require_self`）
则把请求的 `node_id` 与该签名上下文的 `node_context.node_id` 做比对。参见
[内部边界](internal_boundaries.md) 与
[术语表 → CoW](glossary.md)。

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
| `ARI_PAPERBENCH_RUBRIC_DIR` | 覆盖 venue 条件化 PaperBench 规范模板的搜索根（未发布 — 见 `docs/reference/rubric_schema.md#venue-conditioned-templates`） |

### PaperBench 可重现性（v0.7.0）

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_PAPERBENCH_PATH` | 覆盖已评审的 vendor PaperBench project 根目录。仅当它不是 symlink、且其 Git identity 与显式的 `ARI_PAPERBENCH_COMMIT` 声明相符时才被接受 —— 没有该声明则覆盖被拒绝 | `ari-skill-paper-re/vendor/paperbench/project` |
| `ARI_PAPERBENCH_COMMIT` | `ARI_PAPERBENCH_PATH` 覆盖所声明的 commit，会与该树真实的 Git identity 校验 | （无 —— 与 `ARI_PAPERBENCH_PATH` 同时必填） |
| `ARI_REPLICATOR_TIME_LIMIT_SEC` | `run_reproduce` 的挂墙时间上限 | `43200`（12 小时） |
| `ARI_REPLICATOR_ITERATIVE` | 使用迭代式复现器智能体 | – |
| `ARI_REPLICATOR_MAX_STEPS` | 迭代开启时的迭代上限 | – |

### Orchestrator 技能

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_ORCHESTRATOR_HTTP_PORT` | MCP 服务器端口（`streamable-http` 传输） | `9890` |
| `ARI_ORCHESTRATOR_HTTP_HOST` | MCP 服务器的 bind 主机；不可为空 | `127.0.0.1` |
| `ARI_ORCHESTRATOR_LOGS` | 日志目录 | `$ARI_WORKSPACE/logs` |
| `ARI_ORCHESTRATOR_DRY_RUN` | 跳过真实的 `ari run`（冒烟测试）；置 `1` 启用 | – |

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
| `ARI_GH_MODE` | `gh` 后端的模式：`commit`（默认 —— 把 bundle/manifest/README 推入仓库）或 `releases`（创建带 tag 的 release 并附上 tarball） |
| `ARI_CLONE_HTTP_TIMEOUT` | `ari clone` 的 HTTP 超时 |

### SLURM 默认值

| 变量 | 用途 |
|---|---|
| `ARI_SLURM_PARTITION` | 默认分区 |
| `ARI_HPC_ALLOWED_NODES` | 站点策略：ARI 唯一可以把工作放上去的节点集合，采用 SLURM hostlist 语法（`cn01,cn02`、`cn[01-04]`）。未设置 = 不加限制，请求原样通过。设置后会在调度器边界上强制执行，因此对 `job_submit`、`container_submit` 与 `slurm_submit` 一视同仁：**没有**指名任何节点的请求会被约束到这个集合之内 —— 没有 nodelist 时调度器可以在分区里任选节点，而这正是该策略要防止的 —— 而指名了集合之外任何节点的请求会在提交前被拒绝。约束是在计算请求摘要（request digest）**之前**施加的，因此「作业可以在哪里运行」属于其 claim identity 的一部分，被恢复的运行也无法继承在更宽松策略下作出的 claim。无法被精确展开的 nodelist 会被拒绝，而不是被放行。它保存在环境变量而非被跟踪的文件里，因为节点名属于站点身份 |
| `ARI_SLURM_CPUS` | 默认 `--cpus-per-task` |
| `ARI_SLURM_GPUS` | 默认 `--gres=gpu:N` |
| `ARI_SLURM_MEM_GB` | 默认内存请求 |
| `ARI_SLURM_WALLTIME` | 默认 `--time` |
| `ARI_SLURM_ALLOW_NO_GRES` | **当前没有任何代码读取该名称，设置它不会产生任何效果。** 它曾是一个 opt-in：当集群未为 GPU 配置 GRES 时静默丢弃 `--gres` / `--gpus-*`；`scripts/setup/setup_env.sh` 仍以注释形式预写该行。无 GRES 的情形现在改由 `ari/capability_binding/environment.py` 决定：未伴随 GRES 记账而被观测到的设备只会记录为 feature `gpu-observed-on-slurm-node`、allocation mode `observation-only-no-gres`，除非观测到 GRES 或 exclusive-node-inventory 的 pin 匹配，否则它不是可调度的 `gpu` 资源——因此请求会绑定失败，而不是悄无声息地退回 CPU。 |

### PaperBench 复现阶段（Stage 2）

| 变量 | 用途 |
|---|---|
| `ARI_PHASE1_SANDBOX` | `auto` / `local` / `docker` / `apptainer` / `singularity` / `slurm`。强制指定 `server.run_reproduce` 和 `bridge.reproduce_submission` 使用的沙箱运行器。 |
| `ARI_PHASE1_DOCKER_IMAGE` | `sandbox_kind=docker` 且未显式提供 `container_image` 时的默认 docker 镜像。没有内置默认值：未设置则镜像为空，run 会被拒绝而不是被悄悄补上一个。 |
| `ARI_PHASE1_APPTAINER_IMAGE` | `sandbox_kind=apptainer`/`singularity` 且未显式提供 `container_image` 时的默认 SIF / docker URI。 |
| `ARI_PAPERBENCH_PATH` | 覆盖 vendored PaperBench 的 project 根目录（默认：`ari-skill-paper-re/vendor/paperbench/project`；指向内层 `project/paperbench` 的取值会被归一化到 `project`）。需要 `ARI_PAPERBENCH_COMMIT` —— 见上。 |
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
| `SLURM_SSH_USER` | SSH 用户 —— remote 模式下**必填**，不会回退到当前用户，空值会被拒绝 |
| `SLURM_SSH_PORT` | SSH 端口（默认 `22`） |
| `SLURM_SSH_KEY` | 私钥路径 |
| `SLURM_SSH_PASSWORD` | 可选密码（推荐使用密钥） |
| `SLURM_DEFAULT_PARTITION` | ARI 提交子作业的默认分区 |
| `SLURM_PARTITION` | paper-re 沙箱运行器（`_resolve_partition`）在 `ARI_SLURM_PARTITION` 之后查询的回退分区；没有其他读取方 |
| `SLURM_VALID_PARTITIONS` | **无效 —— 无读取方。** `scripts/setup/setup_env.sh` 仅以注释形式预置，树中没有任何位置读回它。节点级策略是 `ARI_HPC_ALLOWED_NODES` |
| `SLURM_LOG_DIR` | **无效 —— 无读取方。** 由 `setup_env.sh` 预置并转发给 skill 子进程，但 sbatch 脚本的 `--output` / `--error` 写入作业的 artifact scope，而非此处 |
| `SLURM_CLUSTER_NAME` | 由 SLURM 自身设置；ARI 仅将它（与 `SLURM_JOB_ID` 一起）用作「是否在集群上」的存在探测 |
| `SLURM_JOB_ID` / `SLURM_JOB_NODELIST` / `SLURM_JOB_PARTITION` | ARI 在作业内运行时由 SLURM 本身设置 |

## Letta (`LETTA_*`)

| 变量 | 用途 |
|---|---|
| `LETTA_BASE_URL` | Letta API base（默认 `http://localhost:8283`） |
| `LETTA_API_KEY` | Letta 需要认证时的 API 密钥 |
| `LETTA_EMBEDDING_CONFIG` | 传给 Letta 的嵌入模型**句柄**（例如 `letta-default`）—— 是句柄名而非文件路径，也不是必需项（未设置时取 `letta-default`） |

## Ollama / OpenAI (`OLLAMA_*` / `OPENAI_*`)

| 变量 | 用途 |
|---|---|
| `OLLAMA_HOST` | Ollama 地址；当 backend 为 `ollama` 时 ARI 将其读作 Ollama 的 api_base（默认 `http://localhost:11434`） |
| `OLLAMA_BASE_URL` | LiteLLM 侧的 base URL |
| `OPENAI_API_KEY` | OpenAI / OpenAI 兼容 API 密钥 |

## VLM

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ARI_VLM_MODEL` | 图表 / 表格审阅用的视觉 LLM；优先于 `VLM_MODEL` | （无） |
| `VLM_MODEL` | `ARI_VLM_MODEL` 未设置时读取的回退视觉 LLM id。没有内置默认值：两者都未设置时，视觉审阅会拒绝执行而不是自行挑一个模型 | （无） |

## 另请参阅

- `docs/reference/configuration.md` — 按用途分组的相同环境变量叙述导览。
- `ari-core/ari/config/__init__.py` — 使用大部分 `ARI_*` 变量的 Pydantic 设置模型。
- 每个技能的 `README.md` — 该技能特有的环境变量。
