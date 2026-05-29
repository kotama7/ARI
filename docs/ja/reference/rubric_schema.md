---
sources:
  - path: ari-skill-replicate/schemas/replication_rubric.schema.json
    role: schema
  - path: ari-skill-replicate/src/generator.py
    role: implementation
  - path: ari-skill-replicate/src/rubric_template.py
    role: implementation
last_verified: 2026-05-25
---

# ルーブリック Schema リファレンス

正本: `ari-skill-replicate/schemas/replication_rubric.schema.json`
(JSON Schema Draft 2020-12, version `3`)。

ルーブリック envelope は PaperBench `TaskNode` ツリーを provenance
メタデータ (paper sha256, generator model, optional audit signature)
と `reproduce_contract` (レプリケータエージェントプロンプトと
Phase 2 sbatch ディスパッチャ双方を駆動) でラップする。

## Envelope

```jsonc
{
  "version":       "3",
  "paper_sha256":  "<64 hex>",                     // sha256(paper text utf-8)
  "rubric_sha256": "<64 hex>",                     // 自己除外、 canonical-JSON の sha256
  "generator": {
    "model":         "gemini/gemini-2.5-pro",
    "prompt_sha256": "<64 hex>",
    "generated_at":  "2026-05-13T...",
    "temperature":   0.0,
    "seed":          0,
    "snapshot":      { ... }                       // 任意
  },
  "audit": {                                       // 任意; ari-skill-replicate.audit_rubric が書き込む
    "auditor_model": "anthropic/claude-opus-4-7",
    "audited_at":    "2026-05-13T...",
    "flags_count":   3
  },
  "reproduce_contract": { ... },                   // 下記参照
  "rubric": { ... }                                // root TaskNode
}
```

## `reproduce_contract`

```jsonc
"reproduce_contract": {
  "script_path":      "reproduce.sh",              // const; Phase 1 entry
  "max_runtime_sec":  21600,                       // 60..43200
  "expected_artifacts": ["results.csv", "fig_1.pdf"],
  "execution_profile": { ... }                    // 任意; execution_profile.md 参照
}
```

[`execution_profile.md`](execution_profile.md) に 16+ 並列実行
フィールドの詳細記載。

## `TaskNode` (ルーブリックツリー)

```jsonc
{
  "id":           "<uuid v4>",
  "requirements": "明確で検証可能な claim テキスト (最小 10 文字)",
  "weight":       1,
  "sub_tasks":    [...],                           // 空 ⇒ leaf
  "task_category":             "Code Development", // LEAF のみ
  "finegrained_task_category": "Method Implementation", // LEAF のみ
  "rationale_from_paper": {                        // LEAF のみ
    "section": "§3.1",
    "quote":   "<paper 本文からの逐字引用、 最小 10 文字>"
  },
  "flags": ["unverifiable"]                        // 任意
}
```

### カテゴリ (閉じた語彙)

`task_category` — 必ず以下のいずれか:
- `Code Development`
- `Code Execution`
- `Result Analysis`

`finegrained_task_category` — 必ず以下のいずれか:
- `Environment & Infrastructure Setup`
- `Dataset and Model Acquisition`
- `Data Processing & Preparation`
- `Method Implementation`
- `Experimental Setup`
- `Evaluation, Metrics & Benchmarking`
- `Logging, Analysis & Presentation`

これらは PaperBench の `VALID_*_TASK_CATEGORIES` allow-list を
ミラーする。 ジェネレータの `normalize_rubric_node` パスが freeze 前に
ドリフトをクランプする。

### ウェイトセマンティクス

ウェイト付き和が leaf スコアを root まで集約する:

```
score(node) = sum_over_children(w_i * score(child_i)) / sum_over_children(w_i)
```

Leaf は `score ∈ {0, 1}` (SimpleJudge 二値判定)。 内部ノードは直接採点
されない — `_collapse_single_child_chains` が縮退する単一子ラッパー
ノードを子に折りたたみ、 ウェイトのみの degenerate node を回避する。

### Flags

`ari-skill-replicate.audit_rubric` 由来の監査アノテーション:

- `vague_qualifier` — "appropriate", "well-organized" 等
- `no_paper_evidence` — quote が paper に存在しない
- `duplicate` — 別 leaf と意味的に等価
- `unverifiable` — 採点不可能な claim (主観的、 将来の課題)

flagged leaf が >20% の場合、 監査者は再生成を推奨する。

## 検証

```python
import json, jsonschema
from pathlib import Path

schema = json.loads(
    Path("ari-skill-replicate/schemas/replication_rubric.schema.json").read_text()
)
validator = jsonschema.Draft202012Validator(schema)
rubric = json.loads(Path("rubric.json").read_text())
validator.validate(rubric)  # スキーマ違反で例外
```

## sha256 検証

```python
from ari_skill_replicate.manifest import verify
verify(rubric)   # rubric_sha256 が再計算と一致なら True
```

`rubric_sha256` は自分自身と post-freeze の `audit` フィールドを除外する
ため、 監査アノテーション追加で provenance が無効化されない。

## venue 別テンプレート (Venue-conditioned templates)

`generate_rubric` は任意引数 `paperbench_rubric_id` を受け取り、
`ari-core/config/paperbench_rubrics/` 配下の YAML テンプレートを選択
できる。テンプレートの `prompt_overrides` ブロックは skeleton/subtree
プロンプトの `{VENUE_HINT}` プレースホルダに注入される。これは
`ari-skill-paper` の peer-review が `reviewer_rubrics/` で使っている
venue パターンと完全に同型。

### 検索パス

最初に見つかったものが採用される:

1. `$ARI_PAPERBENCH_RUBRIC_DIR` (環境変数 override)
2. `<cwd>/ari-core/config/paperbench_rubrics/`
3. `<cwd>/config/paperbench_rubrics/`
4. リポジトリ相対 fallback

### モード

| `mode` | 挙動 |
|---|---|
| `agent_benchmark` | 既存 PaperBench 枠組み。直下ノードは論文の科学構造で分解 (貢献/実験ごとに 1 ノード)。葉は **submission の再現性** を採点。テンプレート未指定時の既定。 |
| `paper_audit` | 直下ノードは `top_level_axes` で宣言された**固定軸**。葉は **paper 本文 (+AD/AE)** が再現に必要な情報を記述しているかを採点。コード実行はスコープ外。再現性監査研究 (HPC_PaperBench / NeurIPS Checklist / Nature Reporting Summary) 用。 |

### YAML スキーマ

```yaml
id: <slug>                # ファイル名 (.yaml 抜き) と一致するスラグ
version: "2026"
venue: "<人間可読 venue 名>"
domain: "<HPC / ML / Wet-lab / ...>"
mode: <agent_benchmark | paper_audit>

# mode = paper_audit のとき必須、agent_benchmark のとき無視
top_level_axes:
  - id: <axis_slug>
    name: <人間可読名>
    weight: <正の整数>
    description: <ルブリック木の直下ノード requirements になる 1 段落>

prompt_overrides:
  system_hint: |
    <skeleton プロンプト冒頭に注入される自由文。 枠組み変更と
     venue 固有の故障モードを明示する>
  leaf_style: |
    <subtree プロンプト冒頭に注入される自由文。 下流パスが葉に
     使う YES/NO 文体を pin する>
```

`paper_audit` モードは `two_stage=True` を要求する (single-pass では
固定軸制約を遵守できないため、組み合わせ要求はエラー)。

### 同梱テンプレート

| `id` | `mode` | 軸 |
|---|---|---|
| `generic` | `agent_benchmark` | (自由 — 貢献ごとに分解) |
| `sc` | `paper_audit` | env_reconstructable, data_available, execution_specified, figures_consistent, scaling_consistent, conclusion_supported |
| `neurips` | `paper_audit` | claims_supported, experimental_setup, code_data_available, statistical_rigor, ethics_limitations, figures_consistent |
| `nature` | `paper_audit` | materials_traceable, protocol_specified, statistics_reported, data_availability, ethics_compliance |

### 新 venue の追加

1. `generic.yaml` か `sc.yaml` をコピーし `<venue_id>.yaml` にリネーム。
2. `mode` を設定、`paper_audit` なら `top_level_axes` を埋め、
   `prompt_overrides.system_hint` と `prompt_overrides.leaf_style` で
   venue 固有の故障モードを明示する。
3. コード変更は**不要** — ローダが検索パスから自動で拾う。

ARI コアは domain-agnostic (P4 原則) を保ち、 venue 知識は YAML に閉じる。

## 関連

- [実行プロファイル仕様](execution_profile.md)
- [PaperBench API リファレンス](api_paperbench.md)
- スキル実装: `ari-skill-replicate/src/generator.py`,
  `ari-skill-replicate/src/rubric_template.py`
- テンプレートディレクトリ: `ari-core/config/paperbench_rubrics/`
- 兄弟 venue パターン: `ari-core/config/reviewer_rubrics/` (peer review)
- PaperBench 親和: `paperbench/nano/tasks.py` (vendor)
