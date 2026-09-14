---
sources:
  - path: ari-core/ari/schemas
    role: schema
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/checkpoint.py
    role: implementation
  - path: ari-core/ari/pipeline/verified_context.py
    role: implementation
  - path: ari-core/ari/pipeline/claim_gate
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/ari/orchestrator/node.py
    role: implementation
  - path: ari-core/ari/orchestrator/node_report
    role: implementation
  - path: ari-core/ari/orchestrator/lineage_decision.py
    role: implementation
  - path: ari-core/ari/pipeline/driver.py
    role: implementation
  - path: ari-core/ari/pipeline/orchestrator.py
    role: implementation
  - path: ari-core/ari/pipeline/experiment_md.py
    role: implementation
  - path: ari-core/ari/claim_gate_contract.py
    role: implementation
  - path: ari-core/ari/science_data_contract.py
    role: implementation
  - path: ari-core/ari/agent/run_env.py
    role: implementation
  - path: ari-core/ari/prompts/_provenance.py
    role: implementation
  - path: ari-core/ari/rqgm
    role: implementation
  - path: ari-core/ari/manuscript
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-core/ari/memory/file_client.py
    role: implementation
  - path: ari-core/ari/publish/__init__.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-transform/src
    role: implementation
  - path: ari-skill-evaluator/src/server.py
    role: implementation
  - path: ari-skill-paper/src/claim_links.py
    role: implementation
  - path: ari-skill-idea/src/server.py
    role: implementation
last_verified: 2026-08-16
---

# 文件格式参考

每个 ARI 检查点都是一个自描述目录。本页归录了 ARI 读写的 JSON / YAML / Markdown 文件，列出规范键列表，并指向生成它们的实现。

正式以 JSON Schema 规定的 schema 请参见 `ari-core/ari/schemas/`。

## `experiment.md`

纯 Markdown 文件，有一个关键约定：一行 `Metrics: <token>, <token>, ...`，由确定性辅助函数 `parse_metric_from_experiment_md`（`ari-core/ari/pipeline/experiment_md.py:30`）提取为回退 `primary_metric`。完整指南请参见 `docs/guides/experiment_file.md`。

`generate_ideas` 运行后，流水线会附加一个幂等块，以下列方式分隔：

```markdown
<!-- AUTO-APPENDED BY VirSci (idea.json) — DO NOT EDIT -->
...
<!-- END AUTO-APPENDED -->
```

仅在标记**上方**编辑正文内容。该追加受 workflow.yaml 的 `plan_promote` 门控（捆绑默认值
`index_only`；`full` 会写入完整计划，其他任何值都完全抑制该块），并且只要起始标记已经存在
就跳过，因此流水线重试绝不会重复追加。

## `idea.json`

`ari-skill-idea.generate_ideas` 的**完整返回值**，由智能体循环
（`ari-core/ari/agent/loop.py` 中 `generate_ideas` 的结果处理器）原样写入
`{checkpoint}/idea.json`，为 BFTS 运行的计划提供种子。在 `ari_rqgm` 模式下改由提案存储
单独写入，并把 `idea.json` 维护为其记录的投影（见下文 `proposals/`）。

顶层结构（节选——该工具返回的键比这里更多）：

```json
{
  "gap_analysis": "...",
  "ideas": [
    {
      "title": "...",
      "description": "...",
      "experiment_plan": "Markdown-formatted plan with §-tags",
      "novelty": "...", "feasibility": "...",
      "novelty_score": 8, "feasibility_score": 7, "overall_score": 7.75,
      "contract_status": "admitted",
      "candidate_id": "...", "hypothesis": "...",
      "falsification_conditions": ["..."],
      "falsifiable_claims": [{"claim": "...", "required_evidence": ["..."]}],
      "citations": ["..."], "limitations": ["..."],
      "_pinned": false
    }
  ],
  "primary_metric": "GFlops/s",
  "higher_is_better": true,
  "metric_rationale": "...",
  "typed_schema_version": "ari.research-contract/v1",
  "contract_status": "admitted",
  "idea_set": {...}, "idea_set_digest": "...",
  "research_contract": {...}, "research_contract_digest": "...",
  "survey_snapshot": {...}, "survey_snapshot_digest": "...",
  "rejected_candidates": [...]
}
```

注意指标所在的位置：`primary_metric` / `higher_is_better` / `metric_rationale` 位于
**顶层**（类型化 `research_contract` 的遗留投影），而不在每条 idea 内。类型化候选被拒绝的
idea 携带 `"contract_status": "rejected"` 加 `rejection_reasons`，而不是被接纳时的那组字段。

子节点通过将继承条目中的 `"_pinned"` 设置为 `true` 来锁定父节点的选定 idea；后续
`generate_ideas` 运行会把被钉选的条目保持在最前，丢弃新生成的、标题与被钉选条目相同的
idea（忽略大小写、归一化空白），并把其余的追加在其后。

## `evaluation_criteria.json`

流水线侧缓存，派生自 `idea.json` + experiment.md。

```json
{
  "primary_metric": "GFlops/s",
  "higher_is_better": true,
  "metric_rationale": "...",
  "metric_unit": "...",
  "research_contract_digest": "sha256:..."
}
```

由 `ari-core/ari/pipeline/driver.py`（`WorkflowDriver.run` 的预检）写入，且**仅当该文件尚不存在时**
才写——运行途中绝不刷新。按顺序尝试四个来源，先命中者胜出：`idea.json` 中的类型化
`research_contract`（同时填充 `metric_unit` / `research_contract_digest`）、某个节点
`memory_snapshot` 中的 `EVALUATION_CRITERIA:` 行、`idea.json` 的遗留顶层 `primary_metric` 系列键，
最后是对 experiment.md 运行 `parse_metric_from_experiment_md`。类型化契约解析失败会抛出异常；
其余来源失败则静默降级为空字符串。读取方是
`ari-core/ari/pipeline/orchestrator.py`（`nodes_to_science_data` 的排名，第 73 行左右）。

## `tree.json`

实时 BFTS 状态，在每次检查点刷写时重写——受节流限制，最多每秒一次写入
（`ari.checkpoint.save_tree_incremental`），除非调用方传入 `force=True`（终止性的节点转换即如此）。
结构：

```json
{
  "run_id": "...",
  "experiment_file": "...",
  "experiment_file_sha256": "<sha256[:16]>",
  "experiment_file_len": 4211,
  "created_at": "2026-07-10T10:34:32+00:00",
  "nodes": [
    {
      "id": "...",
      "parent_id": "...",
      "depth": 2,
      "status": "pending" | "running" | "success" | "failed" | "abandoned",
      "retry_count": 0,
      "children": ["<node_id>", ...],
      "created_at": "...", "completed_at": "...",
      "artifacts": [...],
      "metrics": {"GFlops/s": 312.4, ...},
      "has_real_data": true,
      "evaluation_cases": {...},
      "evaluation_status": "valid",
      "eval_summary": "...",
      "label": "draft" | "improve" | "debug" | "ablation" | "validation" | "other",
      "raw_label": "", "name": "",
      "error_log": null,
      "ancestor_ids": ["..."],
      "trace_log": ["→ tool(args)", "← result", ...],
      "original_direction": "...",
      "producer_component_id": "", "producer_prompt_hash": "", "producer_epoch_id": "",
      "node_report_path": "..."
    }
  ]
}
```

这里有两处出乎读者意料。`nodes` 是一个**列表**，而不是以节点 id 为键的映射——`root_node_id`
并不存在，根节点是 `parent_id` 为 `null` 的那一项。以及既没有 `schema_version`，也没有每节点的
`score`：用于排名的量在 `metrics` 内部，名为 `_scientific_score`。此外，只有当类型化科学保证组
（`knowledge_skill_refs` … `repair_allowed_changes`）中至少有一个字段非空时，`Node.to_dict`
才会追加该组，因此普通节点上这些键是缺失的。

## `nodes_tree.json`

同一份节点列表，由 `ari-skill-transform`、`ari-skill-plot`、viz 仪表盘和 EAR 流水线消费。
它**并不是**比 `tree.json` 更丰富的视图——节点字典就是同一份 `Node.to_dict()` 载荷。
差异只在边缘：

| 键 | 含义 |
|---|---|
| `experiment_goal` | 顶层。BFTS 循环写入 `experiment.md` 的前 3000 个字符；流水线驱动器写入传给它的完整目标字符串 |
| `nodes[].memory` | **仅**由流水线驱动器的写入添加（`ari-core/ari/pipeline/driver.py`）：该节点的记忆条目，最新在前，条数上限为 `ARI_TRANSFORM_MEMORY_MAX_ENTRIES`（默认 20），每条 `text` 在 `ARI_TRANSFORM_MEMORY_MAX_CHARS`（默认 2000）处截断。BFTS 循环自己的刷写不写 `memory` 键 |

读取方按 3 级优先级解析树：`tree.json` → `nodes_tree.json` → 最新的非空
`node_*/tree.json`（遗留布局），因此两者兼有的检查点会从 `tree.json` 读取。

## `full_log.json`

每个节点完成时写入其 `work_dir` 的**完整 ReAct 记录**。与 `node_report.json` 一样位于
`PathManager.META_FILES` 中，因此**不会被继承**到子节点 work_dir（每个节点写自己的）。
结构：`{node_id, parent_id, depth, react_steps, max_react_steps, ended_by,
trace_entries, tools[], messages[], auxiliary_llm_calls[], trace_log[]}`。

- `tools` — 模型实际获得的 OpenAI function-calling 模式（名称+描述+参数）＝**每个工具的用法**。system 提示词的 `AVAILABLE TOOLS` 行只列名称，用法模式通过 API 的 `tools=` 参数带外传递，因此在此字段可见。
- `messages` — **完整对话**：system 提示词、注入的 handoff（相关臂中的父 `summary` / `full_log`）、
  任务，以及所有 user / assistant / tool 轮次（含工具调用名称+参数、工具结果）。这是完整的
  **输入提示词与输出**，而不仅是工具轨迹。
- `auxiliary_llm_calls` — ReAct 循环结束后*关于*该节点发起的、不带工具的 LLM 调用，主要是
  达到步数上限时被强制执行的 Reflection 自我评审。
- `trace_log` — 便于快速浏览的简洁工具调用轨迹（`→ tool(args)` / `← result`）；`trace_entries` 为其长度。

不存在 `steps` 字段，而删除它正是重点：`steps` 曾经等于 `len(trace_log)` ——即**轨迹条目数，
也就是每次迭代 2 条**（调用及其结果）——且不记录预算，于是一个把 15 步预算全部烧光的节点
记下的是 `steps: 30`，读起来像是 30/80 —— 80 是当时的默认值，现已改为 20 —— 即「还剩很多」，而它实际上已经耗尽。
现在两个计数都被保留并按其真实含义命名：`react_steps`（已用迭代数）对 `max_react_steps`
（预算），以及单独的 `trace_entries`。`ended_by` 说明节点是*怎么*停下来的（`finish_json` =
智能体自己得出结论；`max_steps` = 步数耗尽——这类节点上的 `success` 是框架给它 work_dir 的
评分，而不是智能体自己的判断）。

对不调用工具的模型（如 0.5b 底线）`trace_log` 为空（`trace_entries: 0`），但 `messages` 始终包含所发送的完整提示词。

## `node_report.json`

在 `mark_success` / `mark_failed` 时写入的每节点自报告。
Schema：`ari-core/ari/schemas/node_report.schema.json`。
由 `generate_ear`、`nodes_to_science_data`、`bfts.expand` 读取。

**必需键**：`schema_version`（常量 `1`）、`node_id`、`depth`、`status`、
`files_changed`、`metrics`、`artifacts`。其余为可选（按下述条件输出）。

### 核心字段（始终存在）

| 字段 | 类型 | 含义 |
|---|---|---|
| `schema_version` | int(1) | Schema 版本 |
| `node_id` | string | 本节点 id |
| `parent_id` | string \| null | 父节点 id（root 为 `null`） |
| `ancestor_ids` | string[] | root→父 的链 |
| `depth` | int | 树深度（root=0） |
| `status` | string | `success` / `failed` 等 |
| `started_at` / `completed_at` | string | ISO8601 时间戳 |
| `files_changed` | object | `{added, modified, deleted, inherited_unchanged}`，各 `{path, sha256}`。相对父的差异（`added+modified+deleted==0` 即 *sterile* / 空操作节点） |
| `what_was_done` | string | **智能体自身的自然语言自报告**。仅在节点得出结论时填充（无法使用工具的弱模型为空） |
| `metrics` | object | 评估器定义的标量测量。共享 schema 不规定键名或语义。 |
| `measurement_valid` | bool | 评估器给出的客观有效性判定，与 LLM 生成的反思分离。 |
| `evaluation_status` | string | 类型化的评估器结论。评估器未指定时，由 `measurement_valid` 默认为 `valid` / `candidate_invalid`。`infrastructure_error` **不是**科学意义上的零分，它把该次运行排除在外 |
| `evaluation_cases` | object | `{case名: {valid, measurements}}` 形式的逐案例证据。案例名和 JSON 标量测量键由 harness 定义；共享 schema 不赋予任务特定语义。 |
| `measurement_audit` | object | 仅评估器可写的审计记录——`{effective_candidate_compile_flags, rejected_candidate_compile_flags, cases}`。会被持久化，但绝不渲染进父→子的交接文本 |
| `self_assessment` | object | `{headline, concerns}`，来自智能体自身的 LLM 自我评审（无则为空）。 |
| `self_report_stage` | string | 在评分后的自我评审替换掉 `self_assessment` / `next_steps_hints` 之前为 `pre_evaluation`。没有它，一份由评估器信息驱动的自报告，与智能体在被评分之前的猜测无法区分 |
| `migration_source` | string | 构建器新写出的报告为 `fresh`，否则记录产生它的那次迁移 |
| `compute_env` | object | 指标作弊对抗者读取的那份组装后的机器视图：`executor` / `cpu_info` / `mem_total_kb` / `compilers` / `hostname`，外加 `env_signature`、`parent_env_signature` 与 `env_signature_mismatch` |
| `next_steps_hints` | string[] | 智能体自我评审得出的下一步（LLM self-review）。只要智能体给出了非空列表，它就**取代**由评估器派生的那份；评估器中段(0.4-0.7)维度理由是回退项，而在确定性评分下（无分级维度）这个回退项本身就是空的。 |
| `build_command` / `run_command` | string | 运行脚手架（构建/运行命令） |
| `artifacts` | object[] | 产出的产物。`filename` + `role`（`data_output` / `log` / `binary` / `figure` / `unknown`）为必填；只要能 stat 到文件就补上 `sha256` / `size`，而 `inline: true` 标记的是被捕获的 stdout 片段（磁盘上没有对应文件，溯源审计会跳过它们，而不是报告一个并不存在的缺失产物）。除智能体声明的以外，构建器还会自动捕获 work_dir 顶层中 role 为 `data_output` / `log` / `figure` 的文件——因此脚手架源码、编译产物和 ARI 内部 JSON 都被排除在外。硬门用这些 `sha256` 值绑定测量文档的 `artifact_digests` |
| `evaluator_reason` | string | 确定性评估器的判定理由 |
| `trace_log_summary` | string | 执行轨迹摘要 |

类型化科学保证组（`knowledge_skill_refs`、`instruction_identity_digest`、
`capability_binding_lock_digest`、`bound_tool_refs`、`assurance_status` / `assurance_tier`、
harness 锁与证明摘要、`property_verdicts`、`frontier_class`，以及稿件修复谱系字段）由
`ari-core/ari/orchestrator/node_report/scientific_assurance.py` graft 上去。它在 schema 中
声明为可选，在兼容路径上保持为空。

### 探索标签（始终记录）

`label` / `raw_label` / `original_direction` **始终被记录**。

曾有 **`ARI_REPORT_MINIMAL=1`** 可将其从记录中抑制，**该标志已被删除**。标签并非装饰，
它在三处**驱动**搜索：(1) system 提示中的 `NODE ROLE`；(2) 子节点的 `Task:` 行；
(3) **节点选择**（默认 `scientific_plus_diversity` 下，`diversity_bonus` 为出现过少的标签 +0.05）。
仅从记录中隐藏会保留其影响、只删除证据 —— 在 handoff 研究中，一次自以为“已关闭标签”的
4 臂实验里，ABLATION 占比在各臂间仍为 0/1/3/4，而这**无法从 node_report 中发现**。

若要消除标签的影响，应关闭**功能本身**而非隐藏记录：**`ARI_BFTS_NO_LABEL=1`**
（停止上述三处；所有节点获得相同的中立角色/任务，选择也不参考标签）。此时标签仍会被记录，
因此读者可以**验证**它确实是惰性的。

| 字段 | 含义 |
|---|---|
| `label` | BFTS 探索角色：`draft` / `improve` / `debug` / `ablation` / `validation` / `other`。**并非惰性**——除非 `ARI_BFTS_NO_LABEL` 关闭该功能，它会驱动上述三处。`ARI_BFTS_DETERMINISTIC_LABEL=1` 时改为从 direction 确定性推导，而不是由 LLM 提议 |
| `raw_label` | 规划器提议的标签字符串**原文**，只要 LLM 返回了标签就保留——包括它能干净地映射到规范五种之一的情况（提议 `"Improve"` 得到 `label: "improve"`、`raw_label: "Improve"`）。只有节点的*显示名称*才是仅在 `other` 时回退到 `raw_label`。标签是从 direction 文本推断而非由 LLM 提议时为空，`ARI_BFTS_DETERMINISTIC_LABEL=1` 也会强制其为空 |
| `original_direction` | 父的 expand 分配给该子节点的方向文本 |

### 可选组 2：运行环境溯源

`executor` / `hostname` / `slurm_job_id` / `slurm_partition` / `slurm_nodelist` /
`cpu_info` / `mem_total_kb` / `compilers` 记录该节点实际在哪里运行。它们**始终存在**，
run_env 技能什么都没捕获到时（遗留运行、dry run、仅评估）携带空值。无条件输出是刻意的：
省略键会让「什么都没有被捕获」与「这个键早于该字段存在」无法区分，而一份不知道机器的测量，
必须与一份从未询问过机器的测量区分开。

这里是**有意**采集机器身份的。`node_report.json` 是 `workspace/checkpoints/` 下的运行产物，
不是仓库内容——禁止把集群/分区/主机名写进被跟踪的源码、测试和文档的规则并未改变。

上面的 `compilers` 是**加载 module 之前**的视图：它是在 ARI 进程内采集的，而该进程从未加载过
任何东西。`execution_env` 则是执行的 shell 关于*它自己*写下的记录，也是唯一说明某次测量由哪些
module 产生的地方——没有它，两套 module 配置（加载 module 本就是为了比较它们）在这份用于比较
的报告里看起来完全一样。

| 键 | 含义 |
|---|---|
| `loaded_modules` | 命令结束时的 `$LOADEDMODULES`，按原顺序切分。顺序是有意义的：靠后的 module 可以覆盖靠前 module 的路径，因此既不排序也不去重。`[]` 表示命令是在什么都没加载的情况下运行的，这与该键根本不存在（没有任何 shell 工具运行过）是两回事 |
| `module_path` | 命令所看到的 `$MODULEPATH` |
| `path` | 加载 module 之后的 `$PATH`——完整的工具解析顺序，因此即便 ARI 从不指名任何一个编译器，“这次用的是哪个二进制”依然可以回答 |
| `recorded_at` | shell 写下该记录的时刻 |

它由 `EXIT` trap 写出，因此命令失败时记录仍然留存（一次失败测量的环境与一次成功测量的同样值得
关注），且命令的退出状态被保留。`_exec_env.json` 位于 `PathManager.META_FILES` 中：它描述的是
单个节点的执行，因此一份继承来的副本会把父节点的 module 归到一个从未加载过它们的子节点头上。

`partitions_used` 把这一视角从*本节点*扩展到*整个实验*：一次散布在异构集群上的运行，否则不会
留下任何一份关于它究竟在哪里执行过的单一记录，跨节点的指标比较也就无法与其背后的硬件对照
检查：

| 键 | 含义 |
|---|---|
| `this_node` | 本节点自身分配所在的分区 |
| `used` | 该次运行触及过的所有不同分区，从同一次运行中每个兄弟节点的 `_run_env.json` 扫描得到——是观测值，而非配置值 |
| `by_partition` | 每个分区的 `node_count`，以及在其上观测到的各不相同的 `nodelists` / `hostnames` |
| `catalog` | 来自 `heterogeneous_env.json` 的逐分区探测——每个分区*是什么*。其中也包含被探测过、却从未运行过任何节点的分区，这正是“我们本可以用 X 却没有用”得以回答的原因。压缩为 `arch` / `cpu_model` / `threads` / `mem_total_kb` / `gpus` / `compilers` / `cache_measured` |
| `catalog_path` | 指向完整目录的路径。原始的 `module avail` / `lscpu` 转储每个分区约 30 KB，且在检查点根目录下已经有一份，因此只做指向，而不复制进每个节点的报告 |

只有当该节点的 `work_dir` 确实是 `experiments/{run_id}/{node_id}` 时，兄弟扫描才会运行；否则
`used` 保持为空，而不会把某个无关目录下的文件算作本实验的一部分。

```json
{
  "schema_version": 1,
  "node_id": "node_a1b2c3d4",
  "parent_id": "node_...root",
  "ancestor_ids": ["node_...root"],
  "depth": 1,
  "status": "success",
  "started_at": "2026-07-10T10:34:32Z",
  "completed_at": "2026-07-10T10:35:24Z",
  "files_changed": {"added": [], "modified": [{"path": "candidate_gemm.c", "sha256": "..."}], "deleted": [], "inherited_unchanged": []},
  "what_was_done": "Parallelized the outer loop with OpenMP and reordered to ikj for cache locality.",
  "metrics": {"_scientific_score": 1.34},
  "measurement_valid": true,
  "evaluation_cases": {
    "case_a": {
      "valid": true,
      "measurements": {"throughput": 123.4, "error": 1e-12}
    }
  },
  "self_assessment": {"headline": "向量化内层循环，实测约1.2倍。", "concerns": ["仅测试了3种形状"]},
  "next_steps_hints": [],
  "build_command": "", "run_command": "CC ?= cc",
  "artifacts": [{"filename": "result", "role": "unknown"}],
  "evaluator_reason": "ok", "trace_log_summary": ""
}
```
（上例是删除 `ARI_REPORT_MINIMAL` 抑制**之前**的输出，故标签组缺失。当前的 node_report **始终**
包含 `label` / `raw_label` / `original_direction`。机器信息缺失是因为未使用 run_env 技能——该字段
按需填充，并非被抑制。）

## `results.json`

由写 `tree.json` / `nodes_tree.json` 的同一次刷写在检查点根目录写出，因此它并不是只在运行
完成时才产生的产物：

```json
{
  "run_id": "...",
  "nodes": {
    "<node_id>": {
      "artifacts": [...],
      "metrics": {...},
      "has_real_data": true,
      "eval_summary": "...",
      "status": "success",
      "error_log": null
    }
  }
}
```

这里没有 `experiment_goal`、没有 `primary_metric`、也没有 `best_node`——「哪个节点胜出」并不
记录在本文件中，而是由 `select_best_node` 按需重新计算（见 `verified_context.json`）。

同一个文件名在节点 work_dir 内含义**不同**：智能体通过 `ari-skill-coding.emit_results` 写出
`{节点 work_dir}/results.json`，硬门也是从那里读回它。这正是为什么 `results.json` 是
`PathManager.META_FILES` 中唯一被 `NODE_VISIBLE_NAMES` 在 `scope="node"` 下解除认领的条目。

这些每节点的 `results*.json` 是类型化的测量文档，而不是自由格式的字典：

```json
{
  "schema_version": "1.0",
  "typed_schema_version": "ari.measurement-set/v1",
  "measurement_set": {
    "schema_version": "ari.measurement-set/v1",
    "parameters": {...},
    "measurements": [
      {"metric_id": "gflops", "value": 312.4, "unit": "GFlops/s",
       "unit_status": "declared", "provenance": "benchmark",
       "parameters": {...}, "artifact_digests": ["sha256:…"],
       "execution_identity": "...", "execution_attempt_id": "...",
       "execution_status": "completed", "exit_code": 0}
    ],
    "predictions": {...}, "scores": {...},
    "artifact_digests": ["sha256:…"]
  }
}
```

溯源是**每条测量上的 `provenance` 字符串**，而不是顶层的 `_provenance` 映射：测得的天花板用
`microbench` / `benchmark`，校验残差用 `correctness` / `reference`，其余用 `declared` /
`constant`。把这些字符串变成硬门所读的 `{operand: source}` 映射的是 `ari-skill-transform`
——它在节点目录中把每个 `results*.json` 变体的这些字符串取并集，并作为
`science_data.json` 投影里的 `configurations[]._provenance` 发布，因此非默认文件名的
`emit_results` 输出也照样能把证据浮上来。硬门用它确认确实运行了测得的天花板或正确性检查。

## `science_data.json`

由 `ari-skill-transform.nodes_to_science_data` 从已执行节点的证据构建的面向论文的科学数据面。
在磁盘上它是类型化的 `ari.science-data/v1` 文档
（`ari-core/ari/schemas/science_data_v1.schema.json`），由三个分区加若干摘要组成，
**而不是**一个扁平对象：

| 键 | 含义 |
|---|---|
| `raw` | `configurations[]`（每节点的 parameters / measurements / measurement_records / scores / environment / `provenance_labels`）、`measurement_status`、`node_report_status`、`tree_artifact`、`raw_digest` |
| `derived` | `claims`、`numeric_assertions`、`metric_summaries`、`summary_stats`、`anomalies`、`formula_registry_digest`、`derived_digest` |
| `interpretation` | 唯一由 LLM 撰写的分区——`experiment_context`、`implementation_overview`、`evaluation_protocol`，外加它自己的模型/提示词溯源与 `interpretation_digest` |
| `metric_contract` | 顶层。从 `metric_contract.json`（见下文）graft 而来的 idea 所有的指标正确性契约，使硬门强制执行*声明的*契约，而不仅是通用不变式注册表 |
| `provenance` / `limitations` / `run_id` / `migration_status` | 顶层。输入产物、skills/catalog 锁，以及本次运行未能确立的内容 |
| `deterministic_digest` / `science_data_digest` | 顶层自摘要：前者覆盖 `raw`+`derived`+契约，后者覆盖整份文档 |

`derived` 内部：

| 键 | 含义 |
|---|---|
| `claims` | 从节点证据确定性派生的候选声明；每条声明锚定到真实的 `node_id` + `metric_path`。正文是论文撰写器在保留 `% CLAIM:Cx:NCx` 锚点的同时重写的模板种子。 |
| `numeric_assertions` | 硬门重新推导并在容差内与论文上报数值比较的操作数/公式记录。 |

那个**扁平**面——顶层的 `configurations[]` / `per_key_summary` / `summary_stats` / `claims` /
`numeric_assertions`，加上内部的下划线前缀 `_config_nodes` / `_anomalies` 以及每个配置上的
`_provenance`——是读取时的*投影*（`ari.science_data_contract.science_data_projection`），
由硬门、paper 技能和 viz 层各自计算。它并不是文件里的内容，因此直接读原始 JSON 的消费方
必须走投影或直接寻址类型化分区。`_anomalous_metrics` 两边都到不了：transform 技能把它盖在
自己中间态的每配置字典上，用来引导论文撰写器避开物理上不可能的数值，而
`ScienceConfigurationV1` 没有这个字段，所以它既进不了文件也进不了投影——异常只保留在
`derived.anomalies` 中。

## `metric_contract.json`

由 `make_metric_spec`（ari-skill-evaluator）生成、写入 `idea.json` / `tree.json` 旁的
`{checkpoint}/metric_contract.json` 的 idea 所有的指标正确性契约，以便 `nodes_to_science_data`
将其 graft 到 `science_data.json`。持久化的文档是规范的 `ari.metric-gate-contract/v1` 投影
（`ari-core/ari/schemas/metric_gate_contract_v1.schema.json`），它把契约**嵌套**起来，
而不是摊平：

```json
{
  "schema_version": "ari.metric-gate-contract/v1",
  "source": "research-contract" | "human-admitted" | "legacy-migrated",
  "source_idea_digest": "sha256:...",
  "projection_digest": "sha256:...",
  "research_contract_digest": "sha256:...",   // 仅当 source == research-contract
  "metric_contract": {
    "schema_version": "ari.metric-contract/v1",
    "contract_digest": "sha256:...",
    "name": "<metric the paper reports>",
    "unit": "...", "direction": "higher",
    "comparison_scope": "same-environment",
    "rationale": "...",
    "required_evidence": ["thp_on_tput", "thp_off_tput"],
    "required_measured": ["dram_peak_bw", "cache_bw", "ceiling_byK"],
    "formula": "geomean(gflops_byK / ceiling_byK)",
    "operands": {"gflops_byK": "...", "ceiling_byK": "..."},
    "invariants": ["value <= 1", "model_sec <= sec"],
    "correctness": {"expr": "max_abs_err < 1e-4", "requires": ["max_abs_err"]},
    "correctness_required": true,
    "normalization_ceiling": "measured",
    "tolerance": {"absolute": 0.0, "relative": 0.02},
    "formula_provenance": {...},
    "confidence": 0.9,
    "admission_status": "admitted"
  },
  "claims": [{"claim": "...", "required_evidence": ["thp_on_tput", "thp_off_tput"]}]
}
```

硬门的数学部分消费的仍然是**扁平**契约，所以硬门在求值前先做转换：当
`science_data["metric_contract"]` 携带 `schema_version: "ari.metric-gate-contract/v1"` 时，
它会被解析，并在内存中由 `MetricGateContractV1.gate_projection()` 替换为扁平形式——
`key` / `unit` / `direction` / `comparison_scope` / `formula` / `formula_operands` /
`tolerance` / `claims` / `correctness_required` / `ceiling_must_be_measured` /
`required_measured` / `invariants` / `correctness`。由此得出两点。`ceiling_must_be_measured`
是*派生*的（`normalization_ceiling == "measured"`），而不是被声明的。而 `ceiling_select`
——`contract.check_contract` 仍然支持的那个声明式区间条件——在规范文档中没有对应字段，
在投影里也没有条目，因此它只会通过遗留的扁平契约到达硬门。

识别出规范 schema 版本也正是让硬门切换到**严格证据**模式的开关，在该模式下本来只作为
建议的发现会变成错误。所有表达式均为受限 AST（参见
`ari-core/ari/pipeline/claim_gate/formula_eval.py`），并且这套机制不懂任何 roofline /
GFLOP / cache 语义——每一条谓词都由实验自行声明。

`correctness_required` / `ceiling_must_be_measured` 是 agent 无法丢弃的 idea 所有标志；
它们由节点 `results.json` 测量溯源中的 EVIDENCE 标签（测得来源的天花板、正确性来源的残差）
满足，而绝不由 agent 声明的名称满足。匹配刻意是宽容的——硬门查找子串词根
（测得类：`bench` / `measur` / `empiric` / `stream` / `baseline`；正确性类：`correct` /
`verif` / `referenc` / `valid` / `gold` / `truth` / `oracle` / `ground_truth`），
使得一次如实但换了说法的运行不会被过度阻断。来源：
`ari-core/ari/pipeline/claim_gate/contract.py`。

该文件是**一次铸造**的：`_persist_metric_projection` 拒绝覆盖 `projection_digest` 不同的
既有契约，而后续的 `make_metric_spec` 调用会原样返回已持久化的契约（响应携带
`contract_frozen: true`）而不重新抽取——LLM 的命名不具备指称稳定性，运行途中重新生成会
铸造出一套新的证据词汇表，让已按旧名称输出的证据对精确匹配的硬门隐形。当既没有被接纳的
idea 契约、也没有经人工评审的提案时，`make_metric_spec` 什么都不铸造：它返回
`contract_frozen: false` 与 `admission_status: "human-review-required"`，并指向
`propose_metric_contract`。

## `verified_context.json`

限定到最佳节点 root→best 谱系的、由产物支撑的声明，由 `ari-core/ari/pipeline/verified_context.py` 写入，使 `write_paper` 阶段能够将其定量声明落地于经验证、由产物支撑（理想情况下已复现）的结果。**仅**当类型化 research-memory 存储中至少有一条有支撑的声明时才写入——存储为空时不留下文件，论文阶段的行为与之前完全一致。最佳节点选择（`select_best_node`）会排除被擦除的节点（`metrics._valid_for_frontier=False`）——若所有候选都已被擦除则无获胜者、不写文件；此前写下的 `verified_context.json` 只要 `best_node_id` **或**（经擦除过滤的）`lineage` 与新结果不再一致，就会被删除，以免继续把论文落地在一条已被擦除的谱系上；两者都仍然一致时则保留，这样记忆后端的一次瞬时故障不会丢弃一份仍然有效的产物。

```json
{
  "best_node_id": "...",
  "lineage": ["<root_id>", "...", "<best_id>"],
  "claims": [...],
  "limitations": [...],
  "usable_for_claims": [
    {"text": "...", "repro_status": "rerun_passed" | "unverified",
     "artifact_refs": [{"path": "...", "sha256": "..."}]}
  ]
}
```

## `paper_claim_links.json`

对论文的 `% CLAIM:Cx:NCx` 锚点与 `science_data.json` 声明注册表的确定性（无 LLM）对账结果，由 `ari-skill-paper.link_paper_claims` 在 `write_paper`（draft）后以及 `paper_refine`（final）后生成。

| 键 | 含义 |
|---|---|
| `paper_claim_links` | 以锚点为键的记录（`anchor` / `claim_id` / `numeric_id` / `section` / `span_hash` / `line_range` / `figures` / `resolved`）。**锚点**是在 refine/render 中保持稳定的键，`span_hash` 检测句子变更。 |
| `numeric_mentions` | 论文中每个数值 token 的分类（`result_claim` / `experimental_setting` / `citation_year` / `figure_table_ref` / `figure_evidence` / `ambiguous`），含章节归属和 `requires_assertion` 标志。只有 `result_claim` 会置起该标志；`figure_evidence` 是一次后处理重分类，针对的是图清单已经涵盖的那些行上的数字，并且会**清除**该标志。 |
| `writer_assertions` | 撰写器直接内联在锚点所在行上的前向声明（`metric=` / `formula=` / 操作数角色的 `key=value` token）。`dropped_declarations` 记录每一个声明未被采纳的锚点——最常见的原因是「没有内联的 `formula=`」，即对预先生成证据的前向引用——`suspect_declarations` 记录被采纳但可疑的那些。两者都保留下来，好让被丢弃的声明是可见的，而不是仅仅消失。 |
| `figure_refs` | 论文中实际引用的图 id（图绑定记录于此，`science_data.json` 永不被修改）。 |
| `unresolved_anchors` / `uncovered_numeric_candidates` | 硬门消费的诊断信息。 |
| `counts` | 固定的汇总（`anchors`、`resolved_anchors`、`writer_assertions`、`dropped_declarations`、`suspect_declarations`、`numeric_mentions`、`result_claim_mentions`、`uncovered_numeric_candidates`、`figure_refs`），finalize 直接读取而不重新推导。 |

该文档自我标识并自我摘要：`schema_version: "ari.paper-claim-links/v1"`、
`stage: "link_paper_claims"`、对所读 LaTeX 计算的 `paper_digest`，以及对整条记录计算的
`claim_links_digest`。

## `evaluation/claim_evidence_hard_gate_{draft,final}.json`

由 `ari-skill-evaluator.claim_evidence_hard_gate` 写入的确定性 claim/evidence 硬门报告（每个 `phase` 一份：`draft`，随后 `final`）。它验证声明存在性、数值重算、数值覆盖、图存在性以及声明的 `metric_contract`——它检查论文与已记录结果之间的转录/推导一致性，**而非**结果本身的真实性。

该报告是类型化的 `ari.gate-report/v1` 文档
（`ari-core/ari/schemas/gate_report_v1.schema.json`），按键排序写出并与摘要绑定：

```json
{
  "schema_version": "ari.gate-report/v1",
  "report_digest": "sha256:...",
  "gate": "claim_evidence_hard_gate",
  "source_run_id": "...",
  "phase": "draft" | "final",
  "policy_mode": "off" | "warn" | "strict",
  "comparison_scope": "any" | "same_environment",
  "status": "passed" | "warn" | "failed",
  "should_block": true,
  "policy_digest": "sha256:...",
  "evidence_digest": "sha256:...",
  "formula_provenance": {"registry_digest": "sha256:...", "formulas_used": [],
                         "metric_contract_digest": null, "unit_conversions": []},
  "blocking_findings": [{"schema_version": "ari.gate-finding/v1",
                         "severity": "blocking", "type": "numeric_mismatch",
                         "message": "...", "claim_id": null, "numeric_id": null,
                         "node_id": null, "artifact_path": null, "details": {}}],
  "advisory_findings": [...],
  "metrics": {"total_claims": 0, "grounded_claims": 0, ...}
}
```

注意这些改名：策略字段是 `policy_mode`（不再是 `policy`），发现列表是 `blocking_findings` /
`advisory_findings`（不再是 `errors` / `warnings`）。模型会交叉校验自身的结论——`passed` 的
报告不得携带任何发现，`failed` 的报告必须携带至少一条阻断性发现，而 `should_block` 除非同时
满足 `phase == "final"`、`policy_mode != "off"` 且存在至少一条阻断性发现，否则会被直接拒绝。
`metrics` 必须是有限数，因此除零得到的比率被存成 `0.0` / `1.0`，绝不是 `NaN`。

MCP 包装器将 `should_block`（仅在 strict 策略下的 `phase: final`，或在策略 `always_block_on`
集合中的客观虚假发现上设置）转换为流水线硬失败，从而跳过 finalize。来源：`ari-core/ari/pipeline/claim_gate/gate.py`。

## `evaluation/evidence_grounded_semantic_review.json`

由 `ari-skill-evaluator.evidence_grounded_semantic_review` 写入的非阻塞、由证据支撑的语义评审，
形式为类型化的 `ari.semantic-review/v1` 文档
（`ari-core/ari/schemas/semantic_review_v1.schema.json`）。它基于硬门证据检测过度声称 /
解释问题，并为 `paper_refine` 输出 `suggested_revisions`。

`status` 区分三种结果，其中只有一种表示评审干净地跑完了：`ok`（跑完，未发现问题）、
`revise`（有发现和/或修订建议），以及 **`unavailable`** —— 这是*每一条*失败路径都会用的值，
包括论文文件缺失、LLM 出错，以及回复中不含 JSON 对象。把 `unavailable` 读成「没有问题」
恰好读反了；伴随的 `note` 会说明是哪一种失败。绝不阻塞流水线：该评审与它读取的硬门报告
按摘要绑定（`hard_gate_report_digest`），并且该工具事后会重新读取那份文件，若其字节发生变化
就抛出异常，因此一次仅供参考的评审无法改动硬门结果。

输出文件名带上 `phase`：`initial` / `draft` 写入基础文件
`evidence_grounded_semantic_review.json`，其他任何 phase 都追加自己的后缀
（`phase: post_refine` 得到 `..._post_refine.json`）。带后缀的运行会把基础文件读回作为
`previous`，用于计算 `score_delta` / `resolved_overclaim_count`。

## `lineage_decisions.jsonl`（v0.7.0）

谱系决策的仅追加日志。每行一条 JSON 记录。三个写入方共用这个文件，由 `trigger` 区分：
`append_decision_log`（`stagnation_rule` / `every_node` / `manual`）、
`append_root_selection_log`（`root_idea_selection`，其 `decision.action` 为 `root_swap` /
`root_keep`），以及 `ari_rqgm` 的 ProposalRouter（`proposal_router`，其 `decision` 携带
`event` / `generator` / `record_ids`）。停滞形式如下：

```json
{"ts": 1752143672.418, "ts_iso": "2026-07-10T10:34:32Z",
 "trigger": "stagnation_rule", "executed": true,
 "state": {"active_idea_index": 0, "budget_remaining": 2, "alternatives": []},
 "decision": {"action": "switch_to_idea", "target_idea_index": 3,
              "disable_generate_ideas": true, "rationale": "..."}}
```

决策类型：`continue` / `switch_to_idea` / `fanout` / `terminate`。来源：`ari-core/ari/orchestrator/lineage_decision.py`。`decision` 的值是一个对象，即 `LineageDecision.to_dict()` —— `action` / `target_idea_index` / `disable_generate_ideas` / `rationale`；`state` 是 `_state_for_log` 构建的紧凑快照（`active_idea_title` / `active_idea_index` /
`nodes_explored` / `budget_remaining` / `best_axis_scores` / `recent_composite_scores` /
`alternatives` / `venue_constraints_present` / `ancestor_thread_present`），其中较长的
上下文块已被剥离。可选的 `extra` 对象携带各触发方式各自的细节。

`disable_generate_ideas` **只被记录，但不起作用**。在 `switch_to_idea` / `fanout` 记录上，`ari-core/ari/cli/lineage.py` 对该字段为真时所做的全部动作，只是调用 `os.environ.setdefault("ARI_DISABLED_TOOLS_FOR_CHILD", "")` —— 而且是设在*父运行自己的*环境上，值为空字符串。树中 `ari-core/`、`ari-skill-*/` 与 `scripts/` 都没有任何代码回读该变量，`disabled_tools` 仅从 YAML 填充，因此子运行通过启动器的 `os.environ.copy()` 继承了这个变量却将其忽略。在 `continue` / `terminate` 记录上，该字段甚至根本不会被读取。

因此子运行始终会执行 `generate_ideas`。启动器在子运行的 `idea.json` 中写入标记为 `_pinned` 的继承条目，`generate_ideas` 将该条目保留在 `ideas[0]`，丢弃新生成的、标题与之相同的想法，并把其余的追加在其后。钉选生效了，抑制并没有。

所以，带有 `"disable_generate_ideas": true` 的行记录的是评判者*要求*的事情 —— 原样运行所选的备选方案 —— 而不是子运行实际做了什么。确定性停滞转向（deterministic stagnation pivot）把该字段硬编码为 `true`，因此它产生的每一次转向都带着这个值，但它们都不意味着某个子运行的想法池被冻结：该子运行内后续 lineage decision 可选的备选方案，是子运行自己新采样的结果，而非父运行的池子。调用处的注释写明了本意（"child runs the inherited idea verbatim, no resampling"），所以这是一处未接完的接线，而不是为将来预留的字段。

## `prompt_trace.jsonl` / `prompt_versions.json`

提示词溯源：记录每次受管提示词的 LLM 调用是由哪个*模板* —— 以及在调用处能拿到
已渲染字符串时，由哪个*已渲染提示词* —— 产生的。`prompt_trace.jsonl` 是按调用
的仅追加轨迹，`prompt_versions.json` 是它的运行级汇总。两者都写在检查点根目录，
都在 `PathManager.META_FILES` 中，因此绝不会被复制进节点工作目录；
`prompt_trace.jsonl` 还被归入 `_TRACE_FILES` —— 即在路径解析器同样能理解的分桶
运行目录布局下位于 `runs/<run_id>/traces/` 之下的那组文件。来源：
`ari-core/ari/prompts/_provenance.py`；汇总的写入统一经
`ari.checkpoint.save_prompt_versions_json`。

轨迹每行一个 JSON 对象。`prompt_name` 与 `template_hash` 是必填且总能计算出的
字段，其余字段都带默认值，因此记录形状可以在不破坏读取方的前提下扩展：

```json
{"timestamp": "2026-07-10T10:34:32Z", "prompt_name": "pipeline/keyword_librarian",
 "template_hash": "9f2c01ab34de", "rendered_prompt_hash": "34de9f2c01ab",
 "prompt_version": null, "prompt_registry_version": null,
 "model": "...", "node_id": "", "phase": "context_builder", "source": "core"}
```

哈希是 `sha256(text)[:12]` —— 与 `FilesystemPromptLoader.load_versioned` 完全
相同的方案，所以同一份模板正文在这里、在那里、在不同机器上都得到相同的值。
`timestamp` 是元数据，绝不进入任何哈希。`rendered_prompt_hash` 只有在调用处传入
了已渲染文本时才有值，否则为 `null`；有几个调用处只加载模板而不在当地拼出最终
字符串，所以 `null` 表示「未采集」，而不是「空提示词」。

`prompt_version` / `prompt_registry_version` **被观察到几乎总是 `null`**，这是
调用处被冻结的性质，而不是关于提示词本身的论断。填充它们的写入方只有一个：RQGM
PromptRegistry 的打戳路径（`ari-core/ari/rqgm/registry.py`），它把
`prompt_version` 设为*注册表提示词 ID*、`prompt_registry_version` 设为注册表版本。
其余一切 —— 智能体循环、LLM 评估器、上下文构建器、viz 向导工具，以及 RQGM 的
治理／提示词进化／提案的全部调用 —— 两者都保持 `null`。应把 `null` 读作
「未打戳」，而不是「无版本的提示词」。`source` 同样恒为 `"core"`：
`record_prompt_use` 将其硬编码且不接受对应参数，所以该字段预留的 `"skill"` 值
没有任何随发行版出货的写入方会写出。

`prompt_versions.json` 是按首次出现顺序排列的 `{prompt_name: {template_hash,
prompt_version, call_count}}`，其中 `template_hash` 与 `prompt_version` 取自该
名字*第一条*出现的记录 —— 运行中途换过模板的提示词在这里只会显示第一个哈希，
真相仍在 JSONL 一侧。每当 BFTS 循环刷写检查点时，`build_prompt_versions_rollup`
就从轨迹重建它（带节流的写入；终止性刷写为强制），所以它是派生物而非权威。这次
刷写是它唯一的写入方，因此一个记录了提示词使用却没有进入 BFTS 循环的阶段，只会
留下有轨迹而无汇总的结果。

两个写入方都刻意是 best-effort 的，产物也必须这样读。`record_prompt_use` 在解析
不出检查点目录时（单元测试、启动前）为 no-op，在模块锁下追加，并吞掉**每一个**
异常，这样溯源记录失败绝不会弄坏它正在记录的那次 LLM 调用；汇总写入也以同样方式
包裹。所以两个文件中任何一个缺失只意味着「未记录溯源」—— 既不是错误，也不能证明
某次调用没有发生。

## RQGM 纪元治理文件（可选启用的 `ari_rqgm` 模式）

仅当 `ari.mode: ari_rqgm` **且** `rqgm.enabled: true` 一致时才写入
（参见[执行模式](../guides/execution_modes.md)）。在所有默认 `simple_bfts` 检查点上
均不存在；每个读取方都把缺失视为「RQGM 从未运行」。来源：
`ari-core/ari/rqgm/store.py`；JSON Schema：
`ari-core/ari/schemas/{epoch_state,rqgm_registry,rqgm_transition_event,rqgm_defs}.schema.json`。

### `rqgm_transitions.jsonl`

纪元/注册表治理状态的**真相源**。追加式、哈希链式的 JSONL；每行
一个自包含事件：

```json
{"schema_version": 2, "event_id": "evt_000042", "event_type": "prompt_status_change",
 "transaction_id": "transition_003_to_004",
 "payload": {"prompt_id": "reviewer_prompt_v4", "from_status": "shadow",
             "to_status": "probationary_active", "transition_id": "transition_003_to_004"},
 "event_hash": "baf0...64-hex-sha256...", "prev_event_hash": "91ac...64-hex-sha256...",
 "ts": 1751700000.0, "ts_iso": "2026-07-05T12:00:00Z"}
```

v2 的 `event_hash` 是对模式版本、事件标识、事件类型、事务标识、
规范载荷和前驱摘要计算的完整 SHA-256。时间戳是摘要外的元数据。
旧版 v1 仅载荷的 12 位事件仍可读取。事件类型：
`epoch_transaction_prepare`、
`component_registered`、`prompt_registered`、
`component_status_change`、`prompt_status_change`、`epoch_close`、
`epoch_open`、`epoch_transaction_commit`、`emergency_quarantine`。
包括 T16 紧急隔离在内的注册表状态变更**只**通过纪元边界的
prepare/commit 事务被接受；加载时，位于一个没有匹配 commit 的
prepare 之后的事件被忽略（崩溃恢复）。

状态变更载荷由 RegistryTransitionEngine 提供（RQGM Task 09，
`ari-core/ari/rqgm/transition_engine.py` —— 唯一的注册表状态写入
方）：每条都携带 `transition_id`、一个固定的 T1-T21 `rule_id`
（`ari/rqgm/transition_rules.py`；拓扑是冻结代码，仅
`rqgm.transition.*` 数值阈值可配置）、`from_status` /
`to_status`、`evidence_refs`、
`produced_by: registry_transition_engine`（内核 CK-REG-004），
以及冻结边界输入（GovernanceReport + 候选评估 + 注册表哈希）的
`inputs_sha256` 内容哈希，使每次已提交变更都可确定性重放。

### `rqgm_audit.jsonl`

RQGM 的 **ImmutableAuditLog**：同样的追加式哈希链式行信封，带独立
的按文件链。写入其中的治理记录载荷由 GovernanceOrchestrator 拥有
（RQGM Task 05）；链完整性校验属于 ConstitutionalKernel
（Task 04）。内核裁定以 `kernel_report` 条目追加：
`{"context": ..., "constitution_hash": ..., "blocking": ...,
"violations": [{"code": "CK-…", "check": ..., "severity": ...,
"subject_ref": ..., "rule_id": ..., "detail": ...}]}` —— 每次裁定
均可重放。

这种可重放性是契约，不是习惯。`make_report`
（`ari-core/ari/rqgm/kernel_types.py`）在构造时按
`(code, subject_ref, detail)` 对违规排序，因此相同输入总是序列化为
相同的 `kernel_report` 行；该性质由 `ari-core/tests/test_rqgm_kernel.py`
按违规码逐一钉住：它在两个独立的内核实例上把每个夹具各驱动一次，
再比较规范 JSON。没有任何检查读取时钟：所有内核模块都不 import
`time` 或 `datetime`，信封中的 `created_at` 只检查**是否存在**
（`kernel_rules.ENVELOPE_FIELDS`）——它的值绝不进入比较、`detail`
字符串或哈希。严重度同样不由调用方选择，而是通过冻结的
`kernel_rules.SEVERITY` 映射解析——裁定的严重度仅是其代码的函数。
数值上的松弛只有一个旋钮：浮点比较走 `rqgm.kernel.float_tolerance`
（默认 `1e-9`，见[配置](configuration.md)）。而「内核不是 LLM 法官」
是被强制而非被宣称的——一个测试对全部 `ari/rqgm/kernel*.py` 以及
`transition_rules.py` grep `litellm`、`openai`、`anthropic`、
`requests`、`httpx`、`aiohttp`、`socket`，只要其中之一作为 import
出现就失败；它还精确断言被覆盖的文件集合，因此新的 `kernel_*.py`
无法在不加入该守卫的情况下加入内核。

在每个纪元边界，GovernanceOrchestrator 的 `audit_epoch` 把它的
记录追加到这里（全部携带共同的 `rqgm_record_base` 信封）：
`evidence_bundle`（仅 EvidenceClerk 可撰写）、`impeachment_motion`
（仅 Auditor 可撰写；同角色指控在构造上即被拒绝并被内核否决）、
`governance_defense`、`impeachment_outcome`，以及最终的
`governance_report`（schema：
`ari-core/ari/schemas/governance_report.schema.json`；
`recommendations[].action` 是封闭集合 `promote_candidate | promote |
demote | warn | quarantine | retire | no_action`，由 Task 09
消费）。一个纪元的最新报告是带该 `epoch_id` 的「最后」一条
`governance_report` 行（审计崩溃后的重跑会追加新的记录 id；之前的
部分记录作为历史保留）。不存在治理快照文件；JSONL 就是真相。

`audit_epoch` 对组件/提示词注册表、前沿、`tree.json` 与节点状态是
**只读**的。它只通过读取访问器（`active_set` / `get`）接触注册表，
九步流水线只*返回*记录而不落盘，追加由外观层随后完成。它也不施加
任何建议：依据 `governance_report` 采取行动只属于
RegistryTransitionEngine（Task 09），因此报告本身不改变任何状态。
它的写入集合是封闭的：

- `rqgm_audit.jsonl` —— 始终：上述治理记录加上最终的
  `governance_report`。
- `prompt_trace.jsonl` —— 共享提示词渲染路径产出的普通溯源记录，仅覆盖
  治理的 LLM 调用。这些调用只会间接进入 `prompt_versions.json`：要等到
  BFTS 检查点刷写下一次从轨迹重建该汇总时（参见上文
  「`prompt_trace.jsonl` / `prompt_versions.json`」）；`audit_epoch` 自身
  从不写这份汇总。确定性审计（未接入 LLM 接缝）不渲染任何治理提示词，
  也不会在这里追加任何内容。
- `rqgm_adversarial_cases.jsonl` 以及由其派生的
  `rqgm/adversarial_replay_pool.json` —— 第 7 步的重放池更新，仅在
  传入池时发生。被接纳/被支持的案例**追加**到作为真相的 JSONL，
  随后快照由内存状态重写；因此快照是投影，而不是对历史的原地
  修改：有界淘汰只把案例的 `status` 翻转为 `evicted`，JSONL 保留
  曾经接纳过的每一行案例。
- `rqgm_governance_cache.jsonl` —— 候选评估的回写，仅在接入
  Task 12 治理缓存时发生（见下文
  `rqgm_governance_cache.jsonl`）。

`rqgm_audit.jsonl` 同时登记在 `PathManager.META_FILES`（因此没有任何
继承或检查点拷贝路径会把它带进节点 work_dir）与 node_report 的
`files_changed` 屏蔽列表
（`ari-core/ari/orchestrator/node_report/builder.py`）中，所以治理写入
绝不会以「节点产出的文件变更」形式浮现。两个回归测试
（`ari-core/tests/test_rqgm_governance.py`）守住这条线：没有 LLM、
没有重放池的 `audit_epoch` 在检查点目录中只留下已登记的审计日志，
而默认的 `simple_bfts` 运行完全不写 `rqgm*` 文件，也不写
`constitution.yaml`。

RegistryTransitionEngine（RQGM Task 09）还会把每次边界决议作为
`epoch_transition` 记录审计到这里（schema：
`ari-core/ari/schemas/epoch_transition.schema.json`；`status` 为
`pending | committed | aborted | rejected | failed` 之一 ——
被中止/被内核阻断的转换会被记录但**不**施加任何注册表变更），
并在每次已提交的退役上（T17，以及角色范围的 T20 `utility_policy`
取代）追加 `retirement_event` 记录，在每次已提交的 T17 退役上追加
`clean_room_generation_request` 记录（由 Task 08/10 消费）。

FrontierRepairEngine（RQGM Task 10，
`ari-core/ari/rqgm/frontier_repair.py`）在每次带退役的已提交转换
上追加另外三种行：

- `selective_erasure` —— 一条 `SelectiveErasureEvent`（schema：
  `ari-core/ari/schemas/selective_erasure_event.schema.json`）：
  内核所写（`prompt_hash` 为 null，`component_id` 为
  `frontier_repair_engine`），列出已退役的哈希/组件、直接 + 传递
  的过期记录 id，以及被无效化/重算/放弃的节点 id；效用策略退役时，
  还会在 `policy_rescored_node_ids` 中列出由已存原始轴分数重新加权的
  节点。擦除是**仅
  逻辑的**（不变量 13）：所列记录在 `rqgm_erasure_state.json` 中
  被打标，绝不重写或删除。
- `frontier_rebuild` —— 一条 `FrontierRebuildEvent`（schema：
  `ari-core/ari/schemas/frontier_rebuild_event.schema.json`）：
  `frontier_before/after`、被移除/被复位的节点 id（对获胜子节点
  被擦除的父节点的规则 A 复位）、被重算的节点 id，以及
  `kernel_validation`。两种事件的 `status` 均为
  `applied | conservative | halted_expansion`（§5.6 的
  fail-closed 降级阶梯）。
- `utility_record` —— 每当 reviewer/adversary/defender/judge 的
  擦除留下幸存的已评分证据时，一条**重算的** UtilityRecord
  （schema：`ari-core/ari/schemas/rqgm_utility_record.schema.json`
  外加 `supersedes: <stale record_id>` 和
  `recomputed_in_epoch`）：在「原始」纪元的冻结权重下由幸存输入
  重算，绝不重新缩放 —— 被取代的记录留在磁盘上，标记为过期。
  效用策略退役走另一条路径：同一修复事件在 `new_utility_policy`
  下重新组合每个节点保存的 `_axis_scores`，并把节点列进
  `policy_rescored_node_ids`。缺少原始轴的节点以 fail-closed 方式
  被无效化。

### `constitution.yaml`

宪法层的人类可读声明，在 `ari run` 启动时从打包的
`ari-core/config/constitution.yaml` 复制「一次」（绝不覆盖，仅
`ari_rqgm`；在 `simple_bfts` 检查点上不存在）。权威规则是冻结代码
（`ari/rqgm/kernel_rules.py` + `ari/rqgm/transition_rules.py`），
由 `constitution_hash` —— `sha256(canonical_json(<全部规则表>))[:12]`
—— 钉住，该哈希还以可选的 `constitution_hash` 键增量式地记录进
`meta.json`。

因此检查点里的这份副本是**溯源标记，而不是控制面**：编辑它不会改变任何行为，
因为 ARI 没有任何代码回读它 —— 触碰该路径的只有
`ari.rqgm.state.copy_constitution_if_missing`（由 `ari/cli/run.py` 在模式门控下
调用；参见[内部边界](internal_boundaries.md)的「RQGM 模式边界（`ari.rqgm`）」）。
这是刻意为之而非疏漏：检查点目录是扁平的，任何 skill 都能往里写，规则文件放在
那里就会成为一条进化／篡改通道，所以规则表留在代码中。该副本注册在
`PathManager.META_FILES`，绝不会进入节点工作目录。复制在两个方向上都是
best-effort —— 未打包 `constitution.yaml` 的发行版既不复制也不报错 —— 所以文件
不存在本身并不能证明该次运行是 `simple_bfts`。

### `epoch_state.json`

当前打开（或最近关闭）纪元的派生整写快照：冻结的活跃组件集合、
活跃提示词哈希、效用策略、`registry_version`，以及确定性的
`policy_settings` / `policy_fingerprint` 与 `execution_identity` /
`execution_fingerprint`；复合 `epoch_fingerprint` 绑定两类声明身份。
`created_at` 被排除，外部修订缺失时存为 `unresolved`。可
丢弃 —— 加载时对照事件日志重放校验，不匹配则重建。

### `rqgm_registry.json`

把 ComponentRegistry + PromptRegistry 合入一个文件的派生整写快照
（`registry_version`、`as_of_event_hash`、`components[]`、
`prompts[]`）。提示词条目按来源引用其文本（`committed_template`
加载键；`checkpoint_file` 为 `rqgm_prompts/` 下一次写入的
进化提示词本体；`policy` 为 Task 14 的受治 utility-policy 本体，按 `path` 引用），并
同时携带 `prompt_hash`（`sha256[:12]`）与完整的 `prompt_sha256`。
状态生命周期（提示词与组件共享）：
`candidate → validated → shadow → probationary_active → active`、
`active → warning | probation | quarantine`、
`quarantine → retired → banned` —— 变更只经由转换事件。

### `proposals/`（RQGM Task 03）

检查点范围的提案存储 —— 「存储全部；只把摘要交给 BFTS」。只由
`ari_rqgm` 的 ProposalRouter 或显式选择启用的
`proposal_router.record_only` 双写创建；默认的 `simple_bfts` 运行
**不**创建任何 `proposals/` 目录。来源：
`ari-core/ari/rqgm/proposals/store.py`；JSON Schema：
`ari-core/ari/schemas/{proposal_record,proposal_summary_view}.schema.json`。

```
proposals/
  proposal_records.jsonl       # append-only truth (one ProposalRecord per line)
  proposal_index.json          # derived rollup: record_id → status/generator/epoch
  archive/<record_id>/…        # raw outputs, transcripts refs, generator configs
```

`proposal_records.jsonl` 的每一行都携带必备的 RQGM 记录字段
（`record_id` `prop_%06d`、`epoch_id` —— 仅记录模式下为 `null`、
`component_id`、`role: "generator"`、`prompt_hash` —— 标准的
`sha256[:12]`，遗留导入为 `null`、`created_at`、`source_refs`、
`status: candidate|selected|expanded|superseded`），外加
`generator`
（`cheap|mutation|attack_driven|prior_art|virsci|legacy_idea_json`）、
内联的有界 `summary`（ProposalSummaryView；BFTS 所见的「唯一」
形状）、`archive_refs`（检查点相对引用，绝不复制），以及仅逻辑的
`stale` / `valid_for_frontier` 标志（读取时语义由 RQGM Task 10
拥有；已存 JSONL 绝不重写）。记录按内容键（generator +
source_refs + summary）去重，因此被重试的 MCP 调用绝不产生重复
行。在 `ari_rqgm` 中，`idea.json` 是该存储对这些记录维护的兼容性
投影（固定的想法保持在前；`_pinned` / `_inherited_from` /
`_root_choice` 标记逐字保留；`ideas[i]._proposal_record_id` 链接
回记录）。

### `rqgm_adversarial_cases.jsonl`（RQGM Task 06）

对抗进化循环的追加式真相（每行一个 JSON，带锁保护，绝不抛出 ——
`lineage_decisions.jsonl` 的姿态）。仅当 `ari_rqgm` 的对抗回合
运行时才创建；在所有 `simple_bfts` 检查点上均不存在。来源：
`ari-core/ari/rqgm/adversarial/pool.py`；JSON Schema：
`ari-core/ari/schemas/{rqgm_attack_records,
rqgm_utility_record,rqgm_replay_pool}.schema.json`。行类型，按每
节点 §5.3 的顺序 raw → defense → judgment → validated → utility：

- `rqgm_adversarial_round` —— 每节点的幂等标记（`node_id`、
  `epoch_id`）：回合每节点至多运行一次，resume 安全。
- `raw_attack` —— 一次对抗者攻击（`atk_%06d`，角色
  `adversary`）。目标是一个**封闭的工件集合**（`proposal |
  experiment_plan | node_report | metric_result | paper_claim |
  novelty_claim | citation_claim | reproducibility_claim`）——
  绝不是组件 —— 且必须引用 ≥ 1 个 `attack_evidence_refs`。仅为
  审计材料：原始攻击从不触碰任何分数（不变量 8）。
- `defender_response` —— 对每次攻击的 `rebut | concede |
  propose_fix`（`def_%06d`，角色 `defender`）。
- `judgment_record` —— ArtifactJudge 的裁定
  `valid | partially_valid | invalid`，附裁判指定的严重度
  （`jdg_%06d`，角色 `judge`）；总是写入，即使为 `invalid`。
- `validated_attack` —— **仅**对 `valid | partially_valid` 裁定
  存在（`vat_%06d`；必须经过裁决，不变量 9）。
- `utility_record` —— §5.4 惩罚通道的审计记录（`utl_%06d`，角色
  `utility_policy`）：`base_score` / `penalty` / `final_score`、
  按值内嵌的纪元冻结策略权重，以及
  `input_refs.validated_attack_ids`（只要 `penalty > 0` 即非
  空）。
- `adversarial_replay_case` —— 在纪元边界被准入的一条
  AdversarialReplayCase（`adv_case_%05d`）：`replay_view`（完整
  材料；对角色 `clean_room_generator` 拒绝）+ `abstract_view`
  （污染安全的 FailureSummary —— 不含原始攻防文本）。

被惩罚的节点还携带增量的 `Node.metrics` 键
`_pre_penalty_score` 和 `_validated_attack_penalty`；
`_scientific_score` 被重写（sterile-gate 先例），绝不被遮蔽。

### `rqgm/adversarial_replay_pool.json`（RQGM Task 06）

AdversarialReplayPool 的派生字节固定快照（`schema_version`、
`case_seq`、`cases[]`），由 GovernanceOrchestrator 的第 7 步在
纪元边界重写；`rqgm_adversarial_cases.jsonl` 仍是真相源，并在
加载时补齐任何崩溃尾部。逐出是仅逻辑的（`status: "evicted"`；
JSONL 中不移除任何内容）。

### `prompt_evolution.jsonl`（RQGM Task 07）

提示词进化的追加式真相（以 `prompt_trace.jsonl` 为范本的
fail-open 写入器）。仅当 `ari_rqgm` 的提示词进化流水线运行时才
创建；在所有 `simple_bfts` 检查点上均不存在。来源：
`ari-core/ari/rqgm/prompt_evolution.py`；JSON Schema：
`ari-core/ari/schemas/rqgm_prompt_evolution.schema.json`。行类型：

- `prompt_candidate` —— 一个 PromptMutator/洁净室输出
  （`pcand_%05d`），携带完整内嵌的 PromptSpec
  （`ari-core/ari/schemas/rqgm_prompt_spec.schema.json`）；总是以
  `status: "candidate"` 出生 —— 没有即时激活。
- `prompt_candidate_validation` —— 一次生命周期阶段执行
  （`pval_%05d`；阶段 `static_validation → constitutional_validation →
  schema_dry_run → replay_evaluation → anchor_evaluation → shadow`，
  单调 —— 记录链使跳过阶段可被检测）。
- `comparison_observation` —— 一个 shadow 并排样本
  （`cobs_%05d`）：只有输入/输出**哈希**和分歧摘要 —— shadow
  输出文本从不触达本文件、节点指标或前沿（仅观察）。

进入 `probationary_active`/`active` 的采纳**只**通过
RegistryTransitionEngine 在 `rqgm_transitions.jsonl` 中的纪元边界
事务发生（Task 09），绝不通过本文件。

### `prompt_specs.json`（RQGM Task 07）

提示词进化注册表视图的派生汇总
（`schema_version`、`specs{candidate_id → prompt_spec,
stages_passed, rejected}`），在纪元边界和运行结束时尽力重写
（`prompt_versions.json` 模式）；`prompt_evolution.jsonl` 仍是
真相源。

### `rqgm_prompts/`（RQGM Task 07）

检查点范围的进化模板正文，每个进化提示词一个一次写入的
`<prompt_id>.md`（不同内容的重写会被拒绝 —— 活跃提示词文本永不
原地修改；变更即铸造新的 `prompt_id`）。字节由
`prompt_hash = sha256(text)[:12]` 钉住 —— 与
`FilesystemPromptLoader.load_versioned` 完全相同的方案。Gate 10
的例外条款：报告附录恰好覆盖已提交的 `ari-core/ari/prompts/**`
模板；运行时进化的提示词改由本目录加上 `prompt_trace.jsonl` 的
溯源字段（`prompt_version`、`prompt_registry_version`）覆盖。
`rqgm_prompts/` 的缺失 == 完全由已提交提示词构成的轨迹
（`bfts_web_provenance.json` 的 P5 模式应用于提示词）。

### `rqgm_cleanroom.jsonl`（RQGM Task 08）

洁净室再生成的追加式真相（以 `prompt_evolution.jsonl` 为范本的
fail-open 写入器）。仅当某次退役产生
`EpochTransition.clean_room_requests` 时才创建；在所有
`simple_bfts` 检查点上均不存在。来源：
`ari-core/ari/rqgm/clean_room.py`；JSON Schema：
`ari-core/ari/schemas/clean_room_request.schema.json`（请求）和
`ari-core/ari/schemas/clean_room_bundle.schema.json`（封闭输入
bundle）。事件种类（`event` 字段）：

- `request_created` —— 一条完整的 `CleanRoomGenerationRequest`
  （五个禁止输入标志为 const-false；请求在 resume 时从本文件
  重放 —— pending 的请求在下一个纪元边界、在
  `rqgm.prompt_evolution.max_clean_room_generations_per_epoch`
  预算下重试）。
- `bundle_assembled` —— `bundle_id` + `bundle_hash`（对规范
  bundle 载荷的 hash12；除已提交的
  `rqgm/clean_room_generator.md` 元提示词外，该 bundle 就是
  生成器的「全部」上下文）。
- `generation_attempted` —— 单次补全标记，带
  `rendered_prompt_hash`（审计：恰好是元提示词 + 规范 bundle
  JSON 到达了 LLM）。
- `clean_room_violation` / `candidate_rejected_contaminated` ——
  内核 CK-CLN-001/CK-CLN-002 筛查发现；被污染的候选绝不进入
  Task 07 生命周期（准入处阻断，对运行 fail-open）。
- `candidate_registered` —— 以 `status: "candidate"` 交接进
  `prompt_evolution.jsonl`（绝不即时激活）。
- `request_status` —— 请求状态转换
  （`pending|generating|generated|rejected_contaminated|failed|superseded`）。
- `fallback_to_baseline` —— 无空缺规则：没有活跃提示词也没有可
  准入候选的角色回退到其已提交的基线模板。

### `rqgm_erasure_state.json`（RQGM Task 10）

选择性擦除过期状态的派生整写快照，可通过折叠
`rqgm_audit.jsonl` 中的每个 `selective_erasure` /
`frontier_rebuild` 事件重建（`prompt_trace` → `prompt_versions`
的「JSONL 是真相、快照是派生」先例）。仅当修复运行过才创建；在
所有 `simple_bfts` 检查点和没有退役的运行上均不存在。来源：
`ari-core/ari/rqgm/erasure_state.py`（写入统一经
`ari.checkpoint.save_erasure_state_json`；`indent=2,
ensure_ascii=False`）；JSON Schema：
`ari-core/ari/schemas/erasure_state.schema.json`。注册在
`PathManager.META_FILES` 和 node_report 的 `files_changed`
黑名单中。

```json
{
  "schema_version": 1,
  "retired_prompt_hashes": {"a1b2c3d4e5f6": {"retirement_event_id": "retire_00042",
                                              "retired_in_epoch": "epoch_004"}},
  "stale_record_ids": {"review_00311": "erase_00007"},
  "invalid_frontier_node_ids": {"node_031": "erase_00007"},
  "last_erasure_event_id": "erase_00007",
  "last_rebuild_event_id": "rebuild_00007"
}
```

过期状态是**读取时**判定的：一条记录过期当且仅当其 `record_id`
在 `stale_record_ids` 中 —— 已存 JSONL 行绝不重写（不变量 13），
且本文件缺失意味着「无过期，全部有效」（Task-10 之前的检查点
保持有效）。被擦除/无效化的节点还携带增量的 `Node.metrics` 哨兵
键 `_stale`、`_valid_for_frontier`、`_stale_reason`
（`generator_retired | utility_invalidated |
trace_depth_exceeded` —— 仅诊断用）和 `_erasure_event_id`，通过
`tree.json` 持久化；即使切回 `simple_bfts` 模式，它们也让被擦除
的节点保持被排除（污染不会因为切换模式而变干净）。

这份汇总同时也是 ARI **向其他包发布**的表面，因此消费侧另有两条规则。
其一，`invalid_frontier_node_ids` 是被钉住的跨包契约 —— ari-core 写、
memory skill 读，`ari-skill-memory/tests/test_erasure_annotation.py` 会 grep
ari-core 侧的写入方，所以任何一侧改名都会让测试失败，而不是悄悄让擦除感知
失效。其二，那个跨包读取方
（`ari-skill-memory/src/ari_skill_memory/erasure.py`）以**降级**的方式保持
向前兼容：它钉住 `SUPPORTED_SCHEMA_VERSION = 1`，凡是 `schema_version` 不是
它能理解的整数的文件 —— 高于支持版本，或是字符串 / 浮点 / 布尔 —— 都会被读
成「无任何过期」，而不去冒打上错误擦除标签的风险；这与它对缺失、不可读或
格式错误文件给出的判定相同。缺少 `schema_version` 键时按支持版本处理。

请注意这种不对称是读取方的性质而非格式的性质：ari-core 自己的
`view_from_payload`（`ari-core/ari/rqgm/erasure_state.py`）根本不检查
`schema_version` —— 它是写入方的容缺孪生 —— 而 JSON Schema 把
`schema_version` 声明为 `const: 1`。只有跨包读取方实现了这条降级阶梯。

### `rqgm_governance_cache.jsonl`（RQGM Task 12）

治理结果缓存：追加式 JSONL，每条缓存的治理评估一条记录。来源：
`ari-core/ari/rqgm/governance_cache.py`；JSON Schema：
`ari-core/ari/schemas/rqgm_governance_cache.schema.json`。注册在
`PathManager.META_FILES` / `_TRACE_FILES` 和 node_report 的
`files_changed` 黑名单中。缺失 == 空缓存，绝不是错误；在所有
`simple_bfts` 检查点上均不存在。

```json
{"schema_version": 1, "cache_key": "a3f19c02b7d4e881", "role": "judge",
 "epoch_id": "epoch_004", "prompt_hash": "9f2c01ab34de",
 "artifact_hash": "sha256:…", "input_context_hash": "sha256:…",
 "output_schema_hash": "sha256:…", "result_ref": "judgment_00042",
 "score": 0.8, "created_at": "2026-07-05T00:00:00Z"}
```

`cache_key = sha256(artifact_hash ␟ prompt_hash ␟ role ␟ epoch_id ␟
input_context_hash ␟ output_schema_hash)[:16]`（`␟` = `\x1f`）；
两个内容哈希是对规范 JSON 的完整 sha256。`created_at` 仅为溯源
—— 绝不参与键（P2）。重放查询
（`rqgm.replay.use_cached_results`）用案例的**来源**纪元 id 和
候选自己的 `prompt_hash` 计算键 —— 唯一被许可的跨纪元命中；纪元
边界的候选评估先查询此缓存，并把由池派生的逐案例 `score` 写回
（`ari-core/ari/rqgm/governance/_adjudication.py`）。条目从不
原地失效：已退役提示词的条目只是不再可被寻址，因为其
`prompt_hash` 不会再出现在查询中（不变量 13）。预算消耗与治理
级别分配「不」存放在这里 —— 它们以 `budget_consumed` /
`budget_degraded` / `governance_level` 行的形式记入
`rqgm_audit.jsonl`（来源：`ari-core/ari/rqgm/budget.py`），每纪元
预算计数器也因此在 `ari resume` 后幸存。

### `rqgm_eval_metrics.json` / `rqgm_injection_provenance.json`（RQGM Task 13）

评估工具链工件，「只」写在由
`scripts/rqgm_eval/run_ablation.py` 工具链自己启动的运行上
（两种模式下的所有正常检查点上均不存在）。来源：
`ari-core/ari/rqgm/evaluation/{metrics,injection}.py`。两者都
注册在 `PathManager.META_FILES` 和 node_report 的
`files_changed` 黑名单中。

- `rqgm_eval_metrics.json` —— `compute_metric_report` 的十三个
  事后指标（对持久化工件的纯函数；无 LLM，派生值中无挂钟 ——
  指标 13 仅为元数据，从不哈希）。信封：`schema_version`、
  `computed_by_version`、`condition_id`、`run_id`、`seed`、
  `config_digest`（`workflow.yaml` 的 sha256-12）、
  `injection_ids`，以及按固定的计划 §5.4 键顺序排列的
  `metrics{key → {value, numerator, denominator, evidence_refs,
  applicable[, detail]}}`。数据源缺失时产出
  `applicable: false`，绝不是错误。
- `rqgm_injection_provenance.json` —— 持久的合成轨迹标记
  （`bfts_web_provenance.json` 先例）：`schema_version`、
  `injection_ids`（保留的 `eval_*` 命名空间，与 `adv_*` /
  `anchor_*` 案例不相交）、`specs_digest`（对按 id 排序的规范
  规格列表的 hash12）、`harness_version`。任何携带此文件的检查
  点都是被注入的评估运行，绝不能被误认为真实运行。

活动级输出（`ablation_report.{json,md}`、展开后的条件配置）位于
检查点之外的 `workspace/rqgm_eval/<eval_id>/` 下 —— 见
`docs/guides/rqgm_evaluation.md`。

## `.ari-manuscript/`（可选启用的 Manuscript Complete）

当 `manuscript.mode: "off"` 时该命名空间不存在。audit 与 enforce 的 attempt 使用不可变、
以 digest 绑定的 JSON 文档：

```text
.ari-manuscript/
├── state.json
├── transitions.jsonl
├── attempts/<attempt-id>/
│   ├── source_snapshot.json
│   ├── requirement_profile.json
│   ├── context.json
│   ├── omission_manifest.json
│   ├── readiness.json
│   ├── section_briefs.json
│   ├── authoring_binding.json        # authoring-ready 结论时，或 audit 模式下
│   └── publication_decision.json     # 验证／定稿之后
├── segments/*.json
├── repair-transactions/*.json
├── auto-rounds/*.json
└── attempts/<attempt-id>/publication_lock.json
                                        # 仅在一次新鲜的 publishable 结论之后
```

attempt 的身份由源快照与 profile 的 digest 推导而来；源发生变更会产生一个新的 attempt，
而不是改写旧的。Schema 位于 `ari-core/ari/schemas/` 下，命名为
`manuscript_*_v1.schema.json` 与 `research_repair_*_v1.schema.json`。完整的谱系与状态
规则见 [Manuscript Complete 契约参考](manuscript_complete_contracts.md)。

## `settings.json`

viz 仪表盘使用的每检查点设置，位于 `PathManager.project_settings_path(checkpoint)`。
它就是仪表盘 POST 给 `/api/settings` 的那个**扁平**对象，被原样写入——没有任何嵌套：

```json
{
  "llm_provider": "ollama",
  "llm_model": "qwen3:32b",
  "ollama_host": "http://127.0.0.1:11434",
  "temperature": 0.7,
  "retrieval_backend": "semantic-scholar",
  "slurm_partition": "your_partition",
  "slurm_cpus": 64,
  "slurm_walltime": "01:00:00",
  "container_mode": "off",
  "model_idea": "...", "model_bfts": "...", "model_coding": "..."
}
```

`GET /api/settings` 返回 `{**内置默认值, **已保存值}`，未知的已保存键会原样透传，因此该文件
是一份部分覆盖而不是完整文档。没有活动检查点时保存会被拒绝（HTTP 400）：设置只按项目作用域
存在，也没有全局的 `~/.ari/settings.json` 回退。完整的响应 schema 是
`ari-core/ari/schemas/viz_settings.schema.json`。

API 密钥**绝不**存储在此处——`POST /api/settings` 会在写入前把 `api_key` / `llm_api_key`
从载荷中弹出，转而把对应提供方的变量（`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、
`GOOGLE_API_KEY`）以仅属主可读（0600）的方式原子地 upsert 进 `.env`。启动时按
checkpoint → ARI root → ari-core → home 的顺序读取 `.env` 文件，先设置者胜出，
而 shell 导出的变量高于全部这些。

发布/注册表配置目前**不**在这里：`ari ear publish` 解析 `$ARI_PUBLISH_SETTINGS`，否则用
已废弃的 `~/.ari/publish.yaml`（被使用时会告警）。把 `publish` 段放进
`{checkpoint}/settings.json` 是已宣布的 v1.0 替代方案，而不是代码今天会读的路径。

## `workflow.yaml`

由 `ari-core/ari/pipeline/yaml_loader.py` 解析的流水线定义。阶段列表位于顶层键
**`pipeline:`** 之下（BFTS 阶段的展示用行是另一个 `bfts_pipeline:` 列表），每一项以
**`stage:`** 而非 `name:` 为键，且 `inputs` / `outputs` 是映射而不是列表：

```yaml
pipeline:
- stage: search_related_work
  segment: evidence
  skill: web-skill
  tool: search_papers
  description: Recorded deterministic literature retrieval -> related_refs.json
  depends_on: []
  enabled: true
  phase: paper
  inputs:
    query: '{{keywords}}'
  params:
    provider: semantic-scholar
    max_results: 15
  outputs:
    file: '{{checkpoint_dir}}/related_refs.json'
  skip_if_exists: '{{checkpoint_dir}}/related_refs.json'
```

`load_pipeline` 只返回 `enabled != false` 的阶段；`load_disabled_stage_names` 返回其补集，
这样指向一个被有意禁用阶段的 `depends_on` 不会连带跳过它的消费者。有些行仅供展示，
携带 `tool: ''`（例如 evaluation 由 ari-core 进程内的 BFTS 评估器拥有，并不是 MCP 工具）。

捆绑的默认值位于 `ari-core/config/workflow.yaml`（由 `package_config_root()` 返回的包配置
根目录——`ari-core/config/`，是 `ari/` 的同级目录）。遗留文件名 `pipeline.yaml` 仍被接受，
但仅当同一目录下没有 `workflow.yaml` 时。

## `memory_store.jsonl` / `memory_backup.v1.json.gz`

写入 `ARI_CHECKPOINT_DIR` 下的记忆后端产物：

| 文件 | 后端 | 备注 |
|---|---|---|
| `memory_store.jsonl` | `file` | 旧版 v0.5 格式。尽管名字里带 `.jsonl`，它其实是**一个 JSON 数组**，每次 `add()` 都整体重写，并非行分隔——`FileMemoryClient` 用 `json.loads` 读入整个文件。条目为 `{content, metadata, ts}` |
| `memory_backup.v1.json.gz` | `letta` | 可移植快照：gzip 压缩的规范 JSON（键有序、无空白），**一个**文档而**不是** JSONL。由退出时的 `atexit` 钩子以及显式的 `ari memory backup` / `ari memory migrate` 命令写入；没有阶段边界触发 |
| `memory_access.jsonl` | 任意 | 写入/读取操作的仅追加遥测数据 |

备份文档（`ari-core/ari/schemas/memory_backup_v1.schema.json`）：
`{schema_version, records[], react_entries[], core_context, record_digests[],
record_order[], backup_digest}`。`records` 按 `record_digest` 排序，因此文件是字节稳定的；
`record_order` 保留它们被读入时的顺序。运行时条目不带版本化 `memory_record` 的记录会让备份
中止，而不是被悄悄降级。

快照记录结构（`MemoryRecordV1`）：

```json
{
  "schema_version": "...",
  "record_id": "...",
  "record_digest": "sha256:...",
  "kind": "observation" | "experiment_result" | "failure_case" | "procedure"
        | "reflection" | "artifact_summary" | "paper_claim" | "reproducibility_event",
  "text": "...",
  "source_node_id": "...",
  "source_run_id": "...",
  "ancestor_node_ids": ["..."],
  "attributes": {...},
  "confidence": 0.8,
  "artifact_refs": [{"relative_path": "...", "digest": "...", "role": "...",
                     "size_bytes": 0, "integrity_status": "..."}],
  "metric_ptr": {"name": "...", "value": 0.0, "unit": "..."},
  "node_report_ref": {"run_id": "...", "node_id": "...", "digest": "..."},
  "repro_status": "unverified" | "rerun_passed" | "rerun_failed" | "paper_only_reproduced",
  "repro_target_id": null,
  "created_by_tool_ref": "..."
}
```

ReAct 轨迹是**单独的**一个列表，而不是一种 `kind`：`react_entries[]` 保存
`MemoryReactEntryV1` 记录（`{content, metadata, ts, entry_digest}`），按摘要排序。

## EAR bundle（v0.7.0）

`{checkpoint}/ear/` 是候选集；`{checkpoint}/ear_published/` 是已策展并发布到后端的子集。信任锚点为：

```
{checkpoint}/
├── ear_published/
│   ├── manifest.lock     # canonical JSON, per-file sha256 + bundle_sha256
│   └── ...               # curated artefacts
└── publish_record.json   # backend, ref, bundle_sha256, visibility, timestamp
```

`publish_record.json` 位于**检查点根目录**，而不在 `ear_published/` 内部，且 `ari ear publish`
只在策展完成之后才写它；其字段为 `backend` / `ref` / `bundle_sha256` / `visibility` /
`timestamp` / `dry_run` / `extra`。首次发布一律是 `visibility: "staged"`——把它移到 `public`
的是 `ari ear promote`。

策展是可恢复的，而不是原地进行：它先建一个临时目录，把 `manifest.lock` 写进去，再用两次
`os.replace` 把它换到 `ear_published/` 之上；若最后一次改名失败，则恢复之前的 bundle。

`manifest.lock` 是一份 `ari.ear-manifest/v2` 文档——`{schema_version, version,
checkpoint_id, created_at, publish{...}, files[], excluded_count, bundle_sha256,
policy_digest, evidence_index_digest, evidence[], admission_status, lock_digest}`。
它在 `ari-core/ari/schemas/` 中**没有** JSON Schema；那里的 `publish.schema.json` 描述的是
`publish.yaml`，即策展*策略*（`include` / `exclude` / `max_file_mb` / `visibility` /
`required` / `auto_promote` / `license` / `backend`），是另外一个文件。`bundle_sha256`
必须等于烧入已发布论文的 `\codedigest{...}` 宏。

## 另请参阅

- `docs/concepts/architecture.md`（检查点目录布局）— 相同文件的叙述视图。
- `ari-core/ari/schemas/` — `node_report`、类型化的 measurement / science-data /
  gate-report / metric-gate 契约、RQGM 治理记录，以及 Manuscript Complete 文档的正式
  JSON Schema。（那里的 `publish.schema.json` 是 `publish.yaml` 的策展策略，而不是 EAR 的
  `manifest.lock`。）
- `ari-core/ari/pipeline/yaml_loader.py` — workflow.yaml 解析器。
- `docs/guides/experiment_file.md` — 详细的 `experiment.md` 指南。
