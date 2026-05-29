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

# ファイルフォーマットリファレンス

ARI のすべてのチェックポイントは自己記述的なディレクトリです。このページでは
ARI が読み書きする JSON / YAML / Markdown ファイルを、標準的なキー一覧および
それらを生成する実装へのポインタとともに一覧します。

JSON Schema として正式に仕様が定められているスキーマについては
`ari-core/ari/schemas/` を参照してください。

## `experiment.md`

プレーンな Markdown で、1 つの重要な規約があります。決定論的ヘルパー
`parse_metric_from_experiment_md`
（`ari-core/ari/pipeline/experiment_md.py:31`）が
フォールバックの `primary_metric` として抽出する
`Metrics: <token>, <token>, ...` 行です。完全なガイドは
`docs/guides/experiment_file.md` を参照してください。

`generate_ideas` 実行後、パイプラインは以下の区切りで囲まれた冪等なブロックを
追記します:

```markdown
<!-- AUTO-APPENDED BY VirSci (idea.json) — DO NOT EDIT -->
...
<!-- END AUTO-APPENDED -->
```

マーカーより**上**の本文のみを編集してください。

## `idea.json`

`ari-skill-idea.generate_ideas` の出力。`{checkpoint}/idea.json` に配置され、
BFTS 実行のプランのシードとなります。

トップレベルの形式:

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

子は継承したエントリの `"_pinned": true` を設定して親の選択アイデアを固定します。
後続の `generate_ideas` 実行は上書きせずに新しいアイデアをその後に追加します。

## `evaluation_criteria.json`

`idea.json` と experiment.md から派生したパイプライン側キャッシュ。

```json
{
  "primary_metric": "GFlops/s",
  "higher_is_better": true,
  "metric_rationale": "..."
}
```

ソース: `ari-core/ari/pipeline/orchestrator.py`（ローダーは 98 行目付近、
フォールバックパスは 170 行目付近）。

## `tree.json`

ノード遷移ごとに書き換えられる BFTS のライブ状態。形式:

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

`tree.json` は*サマリ*であり、ノードごとの詳細は `nodes_tree.json` に格納されます。

## `nodes_tree.json`

`ari-skill-transform`、`ari-skill-plot`、viz ダッシュボード、EAR パイプラインが
使用するノードごとの完全な詳細。形式は `tree.json` と一致しますが、各ノードには
さらに以下が含まれます:

| キー | 意味 |
|---|---|
| `eval_summary` | LLM ジャッジの自然言語による評決 |
| `metrics_with_metadata` | メトリクスごとの信頼度 + エクストラクタコード |
| `has_real_data` | 評価器が実測定を確認した場合に `true` |
| `trace_log` | `{role, content}` レコードのリスト（LLM + ツールメッセージ） |
| `work_dir` | ノードごとの作業ディレクトリ（チェックポイントルートからの相対パス） |
| `artifacts` | ノードが生成したファイル（sha256 付き） |

## `node_report.json`

`mark_success` / `mark_failed` 時にノードごとに書き込まれる自己レポート。
スキーマ: `ari-core/ari/schemas/node_report.schema.json`。

必須キー: `schema_version`（定数 `1`）、`node_id`、`label`、
`depth`、`status`、`files_changed`、`metrics`、`artifacts`。

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

`generate_ear`、`nodes_to_science_data`、および `bfts.expand` がこのファイルを
参照します。

## `results.json`

実行完了時に出力される最終集計結果。

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

## `lineage_decisions.jsonl` (v0.7.0)

停滞ルールの決定を記録する追記専用ログ。1 行に 1 つの JSON レコード:

```json
{"node_id": "...", "decision": "switch_to_idea", "rationale": "...", "ts": "..."}
{"node_id": "...", "decision": "fanout",        "rationale": "...", "ts": "..."}
```

決定値: `continue` / `switch_to_idea` / `fanout` / `terminate`。
ソース: `ari-core/ari/orchestrator/lineage_decision.py`。

## `settings.json`

viz ダッシュボードが使用するチェックポイントごとの設定。

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

API キーはここには**保存されません** — `.env` ファイルに格納されます
（検索順: チェックポイント → ARI ルート → ari-core → ホーム）。

## `workflow.yaml`

`ari-core/ari/pipeline/yaml_loader.py` が参照するパイプライン定義。
各ステージは呼び出すスキル + ツールと入出力を指定します。

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

バンドル済みデフォルトは `ari-core/ari/configs/workflow.default.yaml` に
あります。

## `memory_store.jsonl` / `memory_backup.jsonl.gz`

`ARI_CHECKPOINT_DIR` 配下に書き込まれるメモリバックエンドの成果物:

| ファイル | バックエンド | 備考 |
|---|---|---|
| `memory_store.jsonl` | `file` | レガシー v0.5 形式、行区切り JSON エントリ |
| `memory_backup.jsonl.gz` | `letta` | ポータブルなスナップショット（ステージ境界 + 終了時に自動生成） |
| `memory_access.jsonl` | any | 書き込み / 読み込みの追記専用テレメトリ |

スナップショットレコードの形式:

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

## EAR バンドル (v0.7.0)

`{checkpoint}/ear/` が候補セット、`{checkpoint}/ear_published/` がバックエンドに
公開するキュレート済みサブセットです。信頼のアンカーは以下の構造です:

```
ear_published/
├── manifest.lock         # canonical JSON, files-only sha256 + bundle_sha256
├── publish_record.json   # backend, ref, sha256, visibility
└── ...                   # curated artefacts
```

`manifest.lock` スキーマ: `ari-core/ari/schemas/publish.schema.json`。
`bundle_sha256` は公開された論文に焼き込まれた `\codedigest{...}` マクロと
一致しなければなりません。

## 関連ドキュメント

- `docs/concepts/architecture.md`（チェックポイントディレクトリレイアウト）— 同じファイル
  のナラティブビュー。
- `ari-core/ari/schemas/` — `node_report` と publish マニフェストの正式な
  JSON スキーマ。
- `ari-core/ari/pipeline/yaml_loader.py` — workflow.yaml パーサ。
- `docs/guides/experiment_file.md` — `experiment.md` の詳細ガイド。
