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
last_verified: 2026-06-10
---

# 文件格式参考

每个 ARI 检查点都是一个自描述目录。本页归录了 ARI 读写的 JSON / YAML / Markdown 文件，列出规范键列表，并指向生成它们的实现。

正式以 JSON Schema 规定的 schema 请参见 `ari-core/ari/schemas/`。

## `experiment.md`

纯 Markdown 文件，有一个关键约定：一行 `Metrics: <token>, <token>, ...`，由确定性辅助函数 `parse_metric_from_experiment_md`（`ari-core/ari/pipeline/experiment_md.py:31`）提取为回退 `primary_metric`。完整指南请参见 `docs/guides/experiment_file.md`。

`generate_ideas` 运行后，流水线会附加一个幂等块，以下列方式分隔：

```markdown
<!-- AUTO-APPENDED BY VirSci (idea.json) — DO NOT EDIT -->
...
<!-- END AUTO-APPENDED -->
```

仅在标记**上方**编辑正文内容。

## `idea.json`

`ari-skill-idea.generate_ideas` 的输出。位于 `{checkpoint}/idea.json`，为 BFTS 运行的计划提供种子。

顶层结构：

```json
{
  "ideas": [
    {
      "title": "...",
      "experiment_plan": "Markdown-formatted plan with §-tags",
      "primary_metric": "GFlops/s",
      "alternatives_considered": ["..."],
      "_pinned": false
    }
  ]
}
```

子节点通过将继承条目中的 `"_pinned"` 设置为 `true` 来锁定父节点的选定 idea；后续 `generate_ideas` 运行会在其后追加新 idea 而不覆盖原有内容。

## `evaluation_criteria.json`

流水线侧缓存，派生自 `idea.json` + experiment.md。

```json
{
  "primary_metric": "GFlops/s",
  "higher_is_better": true,
  "metric_rationale": "..."
}
```

来源：`ari-core/ari/pipeline/orchestrator.py`（加载器在第 98 行左右，回退路径在第 170 行左右）。

## `tree.json`

实时 BFTS 状态，每次节点转换时重写。结构：

```json
{
  "schema_version": 1,
  "root_node_id": "...",
  "nodes": {
    "<node_id>": {
      "id": "...",
      "parent_id": "...",
      "depth": 2,
      "status": "running" | "completed" | "errored" | "pending",
      "label": "draft" | "improve" | "debug" | "ablation" | "validation" | "other",
      "metrics": {"GFlops/s": 312.4, ...},
      "score": 0.74,
      "children": ["<node_id>", ...]
    }
  }
}
```

`tree.json` 是一份*摘要*；每节点的详细信息位于 `nodes_tree.json`。

## `nodes_tree.json`

`ari-skill-transform`、`ari-skill-plot`、viz 仪表盘和 EAR 流水线所使用的完整每节点详情。结构与 `tree.json` 一致，但每个节点还包含：

| 键 | 含义 |
|---|---|
| `eval_summary` | LLM judge 的自然语言裁决 |
| `metrics_with_metadata` | 每个指标的置信度 + 提取代码 |
| `has_real_data` | 评估器确认为真实测量值时为 `true` |
| `trace_log` | `{role, content}` 记录列表（LLM + 工具消息） |
| `work_dir` | 每节点工作目录（相对于检查点根目录） |
| `artifacts` | 节点生成的文件，含 sha256 |

## `full_log.json`

每个节点完成时写入其 `work_dir` 的**完整 ReAct 记录**。与 `node_report.json` 一样位于
`PathManager.META_FILES` 中，因此**不会被继承**到子节点 work_dir（每个节点写自己的）。
结构：`{node_id, parent_id, depth, steps, tools[], messages[], trace_log[]}`。

- `tools` — 模型实际获得的 OpenAI function-calling 模式（名称+描述+参数）＝**每个工具的用法**。system 提示词的 `AVAILABLE TOOLS` 行只列名称，用法模式通过 API 的 `tools=` 参数带外传递，因此在此字段可见。
- `messages` — **完整对话**：system 提示词、注入的 handoff（相关臂中的父 `summary` / `full_log`）、
  任务，以及所有 user / assistant / tool 轮次（含工具调用名称+参数、工具结果）。这是完整的
  **输入提示词与输出**，而不仅是工具轨迹。
- `trace_log` — 便于快速浏览的简洁工具调用轨迹（`→ tool(args)` / `← result`）；`steps` 为其长度。

对不调用工具的模型（如 0.5b 底线）`trace_log` 为空（`steps: 0`），但 `messages` 始终包含所发送的完整提示词。

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
| `delta_vs_parent` | string | **相对父的确定性、已验证的变化**（`files vs parent: +N/~M/-K; valid_geomean_speedup=X`）——始终为真值锚点 |
| `metrics` | object | 评估器测量（`valid_geomean_speedup`、`_scientific_score`、`speedup_*`、空操作时 `_sterile:true` 等） |
| `self_assessment` | object | `{succeeded, headline, concerns}`。`succeeded`=确定性 has_real_data；`headline`+`concerns`=智能体自身的 LLM 自我评审（无则为空）。 |
| `next_steps_hints` | string[] | 智能体自我评审得出的下一步（LLM self-review）。确定性评分下为唯一来源（无分级维度）；使用 rubric/judge 评分时回退到评估器中段(0.4-0.7)维度理由。智能体未提供时为空。 |
| `build_command` / `run_command` | string | 运行脚手架（构建/运行命令） |
| `artifacts` | object[] | 产物 `[{filename, role}]` |
| `evaluator_reason` | string | 确定性评估器的判定理由 |
| `trace_log_summary` | string | 执行轨迹摘要 |

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
| `label` | BFTS 探索角色：`draft` / `improve` / `debug` / `ablation` / `validation` / `other`。惰性（不参与打分或选择）。`ARI_BFTS_DETERMINISTIC_LABEL=1` 时从 direction 确定性推导 |
| `raw_label` | 仅当 `label==other` 时保留（LLM 原始提议标签）；规范五种时为空 |
| `original_direction` | 父的 expand 分配给该子节点的方向文本 |

### 可选组 2：运行环境溯源（按需填充）

`executor` / `hostname` / `slurm_job_id` / `slurm_partition` / `slurm_nodelist` /
`cpu_info` / `mem_total_kb` / `compilers` **仅当 run_env 技能实际捕获到非空数据时**
才输出该键（为空则省略）。不从环境的调度器变量自动捕获，因此技能未使用时机器信息
完全缺失（不写入交付物），使用时则完整出现。

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
  "delta_vs_parent": "files vs parent: +0/~1/-0; valid_geomean_speedup=1.340",
  "metrics": {"valid_geomean_speedup": 1.34, "_scientific_score": 0.05, "speedup_512x512x512": 1.33},
  "self_assessment": {"succeeded": true, "headline": "向量化内层循环，实测约1.2倍。", "concerns": ["仅测试了3种形状"]},
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

运行完成时生成的最终聚合结果。

```json
{
  "run_id": "...",
  "experiment_goal": "...",
  "primary_metric": "GFlops/s",
  "best_node": {"id": "...", "metrics": {...}, "score": 0.91},
  "nodes": {
    "<node_id>": {"metrics": {...}, "has_real_data": true, ...}
  }
}
```

`ari-skill-coding.emit_results` 写入的每节点 `results*.json` 文件还可能携带一个可选的 `_provenance` 键——一个标记每个上报值来源的 `{operand: source}` 映射（测得的天花板用 `microbench` / `benchmark`，校验残差用 `correctness` / `reference`，其余用 `declared` / `constant`）。为空时省略该键。claim-evidence 硬门（经由 `science_data.json` 的 `configurations[]._provenance`）读取它，以确认确实运行了测得的天花板或正确性检查。

## `science_data.json`

由 `ari-skill-transform.nodes_to_science_data` 从已执行节点的证据构建的面向论文的科学数据面。除 `configurations[]` / `experiment_context` / `summary_stats` 外，它还保存 claim-evidence 硬门验证的 Research Contract 基底：

| 键 | 含义 |
|---|---|
| `claims` | 从节点证据确定性派生的候选声明；每条声明锚定到真实的 `node_id` + `metric_path`。正文是论文撰写器在保留 `% CLAIM:Cx:NCx` 锚点的同时重写的模板种子。 |
| `numeric_assertions` | 硬门重新推导并在容差内与论文上报数值比较的操作数/公式记录。 |
| `metric_contract` | 从 `metric_contract.json`（见下文）graft 而来的 idea 所有的指标正确性契约，使硬门强制执行*声明的*契约，而不仅是通用不变式注册表。 |

`_config_nodes`、`_anomalies`、`_anomalous_metrics` 是内部（下划线前缀）注释，不属于面向论文的数据面。

## `metric_contract.json`

由 `make_metric_spec`（ari-skill-evaluator）生成、写入 `idea.json` / `tree.json` 旁的 `{checkpoint}/metric_contract.json` 的 idea 所有的指标正确性契约，以便 `nodes_to_science_data` 将其 graft 到 `science_data.json`。所有表达式均为受限 AST（参见 `ari-core/ari/pipeline/claim_gate/formula_eval.py`）。

```json
{
  "key": "<metric the paper reports>",
  "formula": "geomean(gflops_byK / ceiling_byK)",
  "ceiling_select": "cache_bw if effective_bw > dram_peak_bw else dram_peak_bw",
  "invariants": ["value <= 1", "model_sec <= sec"],
  "correctness": {"expr": "max_abs_err < 1e-4", "requires": ["max_abs_err"]},
  "required_measured": ["dram_peak_bw", "cache_bw", "ceiling_byK"],
  "claims": [{"claim": "...", "required_evidence": ["thp_on_tput", "thp_off_tput"]}],
  "correctness_required": true,
  "ceiling_must_be_measured": true,
  "tolerance": {"absolute": 0.0, "relative": 0.02}
}
```

`correctness_required` / `ceiling_must_be_measured` 是 agent 无法丢弃的 idea 所有标志；它们由 `results.json._provenance` 中的证据标签（测得来源的天花板、正确性来源的残差）满足，而非由 agent 声明的名称满足。来源：`ari-core/ari/pipeline/claim_gate/contract.py`。

## `verified_context.json`

限定到最佳节点 root→best 谱系的、由产物支撑的声明，由 `ari-core/ari/pipeline/verified_context.py` 写入，使 `write_paper` 阶段能够将其定量声明落地于经验证、由产物支撑（理想情况下已复现）的结果。**仅**当类型化 research-memory 存储中至少有一条有支撑的声明时才写入——存储为空时不留下文件，论文阶段的行为与之前完全一致。

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
| `paper_claim_links` | 以锚点为键的记录（`claim_id` / `numeric_id` / `section` / `span_hash` / `line_range` / figures）。**锚点**是在 refine/render 中保持稳定的键，`span_hash` 检测句子变更。 |
| `numeric_mentions` | 论文中每个数值 token 的分类（`result_claim` / `experimental_setting` / `citation_year` / `figure_table_ref` / `ambiguous`），含章节归属和 `requires_assertion` 标志。 |
| `figure_refs` | 论文中实际引用的图 id（图绑定记录于此，`science_data.json` 永不被修改）。 |
| `unresolved_anchors` / `uncovered_numeric_candidates` | 硬门消费的诊断信息。 |

## `evaluation/claim_evidence_hard_gate_{draft,final}.json`

由 `ari-skill-evaluator.claim_evidence_hard_gate` 写入的确定性 claim/evidence 硬门报告（每个 `phase` 一份：`draft`，随后 `final`）。它验证声明存在性、数值重算、数值覆盖、图存在性以及声明的 `metric_contract`——它检查论文与已记录结果之间的转录/推导一致性，**而非**结果本身的真实性。

```json
{
  "gate": "claim_evidence_hard_gate",
  "phase": "final",
  "policy": "strict" | "warn",
  "status": "...",
  "should_block": true,
  "errors": [...],
  "warnings": [...],
  "metrics": {"total_claims": 0, "grounded_claims": 0, ...}
}
```

MCP 包装器将 `should_block`（仅在 strict 策略下的 `phase: final`，或在客观虚假发现时设置）转换为流水线硬失败，从而跳过 finalize。来源：`ari-core/ari/pipeline/claim_gate/gate.py`。

## `evaluation/evidence_grounded_semantic_review.json`

由 `ari-skill-evaluator.evidence_grounded_semantic_review` 写入的非阻塞、由证据支撑的语义评审。它基于硬门证据检测过度声称 / 解释问题，并为 `paper_refine` 输出 `suggested_revisions`。绝不阻塞流水线；出错时返回空的（`status: "ok"`）评审。refine 后的过程会在其旁写入 `evidence_grounded_semantic_review_post_refine.json` 变体。

## `lineage_decisions.jsonl`（v0.7.0）

停滞规则决策的仅追加日志。每行一条 JSON 记录：

```json
{"node_id": "...", "decision": "switch_to_idea", "rationale": "...", "ts": "..."}
{"node_id": "...", "decision": "fanout",        "rationale": "...", "ts": "..."}
```

决策类型：`continue` / `switch_to_idea` / `fanout` / `terminate`。来源：`ari-core/ari/orchestrator/lineage_decision.py`。

## `settings.json`

viz 仪表盘使用的每检查点设置。

```json
{
  "model": "ollama/qwen3:32b",
  "provider": "ollama",
  "hpc": {"partition": "your_partition", "cpus": 64},
  "registries": [
    {"name": "default", "url": "http://127.0.0.1:8290", "token_env": "ARI_REGISTRY_TOKEN"}
  ]
}
```

API 密钥**绝不**存储在此处 — 它们存放在 `.env` 文件中（搜索顺序：checkpoint → ARI root → ari-core → home）。

## `workflow.yaml`

由 `ari-core/ari/pipeline/yaml_loader.py` 解析的流水线定义。每个阶段指定要调用的技能 + 工具以及输入/输出。

```yaml
stages:
  - name: idea_generation
    skill: idea
    tool: generate_ideas
    inputs:
      - experiment.md
    outputs:
      - idea.json
  - name: bfts
    skill: orchestrator
    ...
```

捆绑的默认值位于 `ari-core/ari/configs/workflow.default.yaml`。

## `memory_store.jsonl` / `memory_backup.jsonl.gz`

写入 `ARI_CHECKPOINT_DIR` 下的记忆后端产物：

| 文件 | 后端 | 备注 |
|---|---|---|
| `memory_store.jsonl` | `file` | 旧版 v0.5 格式，行分隔 JSON 条目 |
| `memory_backup.jsonl.gz` | `letta` | 可移植快照（在阶段边界 + 退出时自动写入） |
| `memory_access.jsonl` | 任意 | 写入/读取操作的仅追加遥测数据 |

快照记录结构：

```json
{
  "node_id": "...",
  "ancestor_ids": ["..."],
  "kind": "node_scope" | "react_trace",
  "text": "...",
  "metadata": {...},
  "ts": "..."
}
```

## EAR bundle（v0.7.0）

`{checkpoint}/ear/` 是候选集；`{checkpoint}/ear_published/` 是已策展并发布到后端的子集。信任锚点为：

```
ear_published/
├── manifest.lock         # canonical JSON, files-only sha256 + bundle_sha256
├── publish_record.json   # backend, ref, sha256, visibility
└── ...                   # curated artefacts
```

`manifest.lock` schema：`ari-core/ari/schemas/publish.schema.json`。`bundle_sha256` 必须等于烧入已发布论文的 `\codedigest{...}` 宏。

## 另请参阅

- `docs/concepts/architecture.md`（检查点目录布局）— 相同文件的叙述视图。
- `ari-core/ari/schemas/` — `node_report` 和发布 manifest 的正式 JSON Schema。
- `ari-core/ari/pipeline/yaml_loader.py` — workflow.yaml 解析器。
- `docs/guides/experiment_file.md` — 详细的 `experiment.md` 指南。
