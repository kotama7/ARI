---
sources:
  - path: ari-skill-replicate/schemas/replication_rubric.schema.json
    role: schema
  - path: ari-skill-replicate/src/generator.py
    role: implementation
  - path: ari-skill-replicate/src/auditor.py
    role: implementation
  - path: ari-skill-replicate/src/migration.py
    role: implementation
  - path: ari-skill-replicate/src/rubric_template.py
    role: implementation
last_verified: 2026-08-16
---

# 评分单 Schema 参考

正本: `ari-skill-replicate/schemas/replication_rubric.schema.json`
(JSON Schema Draft 2020-12, `ari.replication-rubric/v2`; PaperBench bridge
version 仍为 `3`)。

评分单 envelope 用 provenance、artifact-backed model call、repair ledger
与 `reproduce_contract` 包装 PaperBench `TaskNode` 树。审计不会修改 frozen
rubric，而是写入独立的 `ari.replication-rubric-audit/v2` artifact。

## Envelope

```jsonc
{
  "schema_version": "ari.replication-rubric/v2",
  "version":       "3",
  "paper_sha256":  "<64 hex>",                     // sha256(paper text utf-8)
  "rubric_sha256": "<64 hex>",                     // 排除自身,canonical-JSON 的 sha256
  "generator": {
    "model":         "gemini/gemini-2.5-pro",
    "provider":      "gemini",
    "model_revision": "<immutable revision>",
    "prompt_sha256": "<64 hex>",
    "generated_at":  "2026-05-13T...",
    "temperature":   0.0,
    "seed":          0,
    "strategy":      "hierarchical-v2",
    "quality_profile": "calibrated",
    "max_model_calls": 64,
    "subtree_concurrency": 4,
    "calls": [ ... ],
    "partial_failures": []
  },
  "repair_ledger": {"actions": [], "dropped_artifacts": []},
  "reproduce_contract": { ... },                   // 见下
  "rubric": { ... }                                // 根 TaskNode
}
```

## `reproduce_contract`

```jsonc
"reproduce_contract": {
  "script_path":      "reproduce.sh",              // const; Phase 1 入口
  "max_runtime_sec":  21600,                       // 60..43200
  "expected_artifacts": ["results.csv", "fig_1.pdf"],
  "execution_profile": { ... }                    // 可选; 见 execution_profile.md
}
```

详见 [`execution_profile.md`](execution_profile.md) 的 16+ 并行执行
字段。

## `TaskNode` (评分单树)

```jsonc
{
  "id":           "<uuid v4>",
  "requirements": "明确、可验证的 claim 文本 (最少 10 字符)",
  "weight":       1,
  "sub_tasks":    [...],                           // 空 ⇒ 叶节点
  "task_category":             "Code Development", // 仅 LEAF
  "finegrained_task_category": "Method Implementation", // 仅 LEAF
  "rationale_from_paper": {                        // 仅 LEAF
    "section": "§3.1",
    "quote":   "<论文逐字引用,最少 10 字符>"
  },
  "evidence_span": {"kind": "paper-span", "start_char": 10, "end_char": 40, ...},
  "verification": {"kind": "artifact", "relative_path": "results.json"}
}
```

叶节点字段还有另一种形式。`rationale_from_paper` 可以改为
`{"external_prerequisite": {"description", "source"}}`,对应的 `evidence_span`
则是 `{"kind": "external-prerequisite", "description", "source"}` —— schema 要求
每个叶节点要么绑定论文中的精确 evidence,要么绑定一个显式声明的 external
prerequisite。`verification` 还接受
`{"kind": "log-pattern", "relative_path": "reproduce.log", "pattern": "..."}` 与
`{"kind": "metric", "relative_path": "...", "metric": "...", "unit": "..."}`。

### 类别 (封闭词表)

`task_category` — 恰好是以下之一:
- `Code Development`
- `Code Execution`
- `Result Analysis`

`finegrained_task_category` — 恰好是以下之一:
- `Environment & Infrastructure Setup`
- `Dataset and Model Acquisition`
- `Data Processing & Preparation`
- `Method Implementation`
- `Experimental Setup`
- `Evaluation, Metrics & Benchmarking`
- `Logging, Analysis & Presentation`

这些镜像 PaperBench 的 `VALID_*_TASK_CATEGORIES` allow-list。生成器的
`normalize_rubric_node` 阶段在 freeze 前钳制任何漂移。

### 权重语义

加权求和把叶节点分数聚合到根:

```
score(node) = sum_over_children(w_i * score(child_i)) / sum_over_children(w_i)
```

叶节点 `score ∈ {0, 1}` (SimpleJudge 二元判定)。内部节点从不直接判分 —
`_collapse_single_child_chains` 把单子非叶节点折叠到子节点以避免简
权重 wrapper 节点的退化情况。

### 审计 findings

独立 audit artifact 中的 findings:

- `vague_qualifier` — "appropriate", "well-organized" 等
- `no_paper_evidence` — 引用在论文中不存在
- `duplicate` — 与另一叶节点语义等价
- `unverifiable` — 不可评分的 claim (主观、未来工作)

flag 标记叶 >20% 时审计员推荐重新生成。

## 验证

```python
import json, jsonschema
from pathlib import Path

schema = json.loads(
    Path("ari-skill-replicate/schemas/replication_rubric.schema.json").read_text()
)
validator = jsonschema.Draft202012Validator(schema)
rubric = json.loads(Path("rubric.json").read_text())
validator.validate(rubric)  # 违反 schema 时抛异常
```

## sha256 验证

```python
# ari-skill-replicate/src/manifest.py —— skill 内的模块是扁平的,
# skill 自身的代码也是这样 import 的 (见 src/migration.py)。
from manifest import verify
verify(rubric)   # rubric_sha256 与重计算匹配返回 True
```

`rubric_sha256` 仅排除自身；任何 post-freeze 修改都会导致 digest 不匹配。
V1 只能通过 lossless offline migration 转为 V2；`paper-re` 对未知版本、
篡改以及 paper digest 不匹配均 fail closed。

## venue 条件化模板 (Venue-conditioned templates)

`generate_rubric` 接受可选参数 `paperbench_rubric_id`, 选择
`ari-core/config/paperbench_rubrics/` 下的 YAML 模板。模板的
`prompt_overrides` 块通过 `{VENUE_HINT}` 占位符注入到 skeleton 和
subtree 提示词中, 与 `ari-skill-paper` 在 `reviewer_rubrics/` 中
用于 peer review 的 venue 模式同构。

### 搜索路径

第一个命中的目录被采用:

1. `$ARI_PAPERBENCH_RUBRIC_DIR` (环境变量 override)
2. `<cwd>/ari-core/config/paperbench_rubrics/`
3. `<cwd>/config/paperbench_rubrics/`
4. 仓库相对 fallback

### 模式

| `mode` | 行为 |
|---|---|
| `agent_benchmark` | 原始 PaperBench 范式。直接子节点按论文科学结构分解 (每个贡献/实验一个节点)。叶子评分 **submission 的再现性**。未指定模板时的默认。 |
| `paper_audit` | 直接子节点是 `top_level_axes` 中声明的**固定轴**。叶子评分 **论文文本 (+AD/AE)** 是否描述了再现所需的信息。代码执行不在评分范围内。用于再现性审计研究 (HPC_PaperBench / NeurIPS Checklist / Nature Reporting Summary)。 |

### YAML schema

```yaml
id: <slug>                # 与文件名 (去掉 .yaml) 一致的 slug
version: "2026"
venue: "<人类可读 venue 名>"
domain: "<HPC / ML / Wet-lab / ...>"
mode: <agent_benchmark | paper_audit>

# 当 mode = paper_audit 时必填、agent_benchmark 时忽略
top_level_axes:
  - id: <axis_slug>
    name: <人类可读名>
    weight: <正整数>
    description: <成为 rubric 树直接子节点 requirements 的一段文字>

prompt_overrides:
  system_hint: |
    <注入到 skeleton 提示词顶部的自由文本。 用于声明范式切换以及
     venue 特有的故障模式>
  leaf_style: |
    <注入到 subtree 提示词顶部的自由文本。 用于固定下游通道使用的
     叶子 YES/NO 句式>
```

所有模式都使用强制的 calibrated hierarchical strategy，以维持 `paper_audit` 的固定轴约束。

### 已自带的模板

| `id` | `mode` | 轴 |
|---|---|---|
| `generic` | `agent_benchmark` | (自由 — 按论文贡献分解) |
| `sc` | `paper_audit` | env_reconstructable, data_available, execution_specified, figures_consistent, scaling_consistent, conclusion_supported |
| `neurips` | `paper_audit` | claims_supported, experimental_setup, code_data_available, statistical_rigor, ethics_limitations, figures_consistent |
| `nature` | `paper_audit` | materials_traceable, protocol_specified, statistics_reported, data_availability, ethics_compliance |

### 添加新 venue

1. 复制 `generic.yaml` 或 `sc.yaml` 并重命名为 `<venue_id>.yaml`。
2. 设定 `mode`, 如为 `paper_audit` 则填入 `top_level_axes`, 并在
   `prompt_overrides.system_hint` 和 `prompt_overrides.leaf_style` 中
   呈现 venue 特有的故障模式。
3. **无需**代码改动 — 加载器会自动从搜索路径中拾取。

ARI 核心保持 domain-agnostic (P4 原则), venue 知识封闭于 YAML 中。

## 相关

- [执行配置参考](execution_profile.md)
- [PaperBench API 参考](api_paperbench.md)
- 技能实现: `ari-skill-replicate/src/generator.py`,
  `ari-skill-replicate/src/rubric_template.py`
- 模板目录: `ari-core/config/paperbench_rubrics/`
- 兄弟 venue 模式: `ari-core/config/reviewer_rubrics/` (peer review)
- PaperBench 兼容: `vendor/paperbench/project/paperbench/paperbench/rubric/tasks.py`
  (vendored 于 `ari-skill-paper-re/` 之下)
