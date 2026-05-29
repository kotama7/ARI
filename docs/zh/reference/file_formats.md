---
sources:
  - path: ari-core/ari/schemas
    role: schema
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/checkpoint.py
    role: implementation
last_verified: 2026-05-25
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

## `node_report.json`

在 `mark_success` / `mark_failed` 时写入的每节点自报告。Schema：`ari-core/ari/schemas/node_report.schema.json`。

必需键：`schema_version`（常量 `1`）、`node_id`、`label`、`depth`、`status`、`files_changed`、`metrics`、`artifacts`。

```json
{
  "schema_version": 1,
  "node_id": "...",
  "parent_id": "...",
  "ancestor_ids": ["..."],
  "label": "improve",
  "depth": 2,
  "status": "completed",
  "started_at": "2026-05-08T11:30:00Z",
  "completed_at": "2026-05-08T11:42:00Z",
  "files_changed": {
    "added":    [{"path": "src/main.cpp", "sha256": "..."}],
    "modified": [{"path": "Makefile",     "sha256": "..."}],
    "deleted":  [],
    "inherited_unchanged": []
  },
  "metrics": {"GFlops/s": 312.4},
  "artifacts": [{"path": "results.csv", "sha256": "..."}]
}
```

`generate_ear`、`nodes_to_science_data` 和 `bfts.expand` 会读取此文件。

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
