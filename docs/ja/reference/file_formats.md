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

`ari-skill-coding.emit_results` が書き込むノードごとの `results*.json`
ファイルには、オプションの `_provenance` キーが付与されることがあります。
これは報告された各値の出所を示す `{operand: source}` マップで、測定された
天井には `microbench` / `benchmark`、検証残差には `correctness` /
`reference`、それ以外には `declared` / `constant` のタグが付きます。空の場合
このキーは省略されます。claim-evidence ハードゲートはこれを
（`science_data.json` の `configurations[]._provenance` 経由で）読み取り、
測定された天井や正当性チェックが実際に実行されたことを確認します。

## `science_data.json`

`ari-skill-transform.nodes_to_science_data` が実行済みノードのエビデンスから
構築する、論文向けのサイエンスサーフェス。`configurations[]` /
`experiment_context` / `summary_stats` に加えて、claim-evidence ハードゲートが
検証する Research Contract の基盤を保持します:

| キー | 意味 |
|---|---|
| `claims` | ノードのエビデンスから決定論的に派生した候補クレーム。各クレームは実在する `node_id` + `metric_path` にアンカーされます。本文は論文ライターが `% CLAIM:Cx:NCx` アンカーを保持したまま書き換えるテンプレートのシードです。 |
| `numeric_assertions` | ハードゲートが再導出し、許容誤差内で論文に記載された数値と比較するオペランド/数式レコード。 |
| `metric_contract` | `metric_contract.json`（後述）から graft された idea 由来のメトリクス正当性契約。これにより、ゲートはユニバーサル不変条件レジストリだけでなく*宣言された*契約も強制します。 |

`_config_nodes`、`_anomalies`、`_anomalous_metrics` は内部用
（アンダースコア接頭辞）の注釈であり、論文向けのサーフェスには含まれません。

## `metric_contract.json`

`make_metric_spec`（ari-skill-evaluator）が出力し、`idea.json` / `tree.json`
の隣の `{checkpoint}/metric_contract.json` に書き込まれる idea 由来の
メトリクス正当性契約。`nodes_to_science_data` がこれを `science_data.json`
に graft します。すべての式は制限付き AST です
（`ari-core/ari/pipeline/claim_gate/formula_eval.py` を参照）。

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

`correctness_required` / `ceiling_must_be_measured` はエージェントが破棄
できない idea 所有のフラグであり、`results.json._provenance` 内のエビデンス
タグ（測定ソースの天井、正当性ソースの残差）によって満たされます。
エージェントが宣言した名前では満たされません。ソース:
`ari-core/ari/pipeline/claim_gate/contract.py`。

このファイルは **mint-once** です: claims を含む契約が最初に書き込まれた後は
不変です。以降の `make_metric_spec` 呼び出しは再抽出せず、永続化された契約を
そのまま返します（レスポンスに `contract_frozen: true` が付きます）— LLM の
命名は参照的に安定しないため、実行途中で再生成すると新しいエビデンス語彙が
生成され、旧名ですでに出力されたエビデンスが完全一致ゲートから見えなくなる
ためです。scaffold のみ（`claims` なし）の契約は凍結されません。

## `verified_context.json`

ベストノードの root→best 系統にスコープされたアーティファクト裏付けの
クレーム。`ari-core/ari/pipeline/verified_context.py` が書き込み、
`write_paper` ステージが定量的クレームを検証済みでアーティファクトに
裏付けられた（理想的には再現された）結果に基づいて生成できるようにします。
型付き research-memory ストアに少なくとも 1 つの裏付けクレームがある場合に
**のみ**書き込まれます。ストアが空の場合はファイルが生成されず、論文ステージ
は以前とまったく同じ挙動になります。

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

論文の `% CLAIM:Cx:NCx` アンカーを `science_data.json` のクレームレジストリ
に対して決定論的に（LLM なしで）突合した結果。
`ari-skill-paper.link_paper_claims` が `write_paper`（draft）後、および
`paper_refine`（final）後に生成します。

| キー | 意味 |
|---|---|
| `paper_claim_links` | アンカーをキーとするレコード（`claim_id` / `numeric_id` / `section` / `span_hash` / `line_range` / figures）。**アンカー**が refine/render を通じて生き残る安定キーであり、`span_hash` は文の変更を検出します。 |
| `numeric_mentions` | 論文中のすべての数値トークンを分類したもの（`result_claim` / `experimental_setting` / `citation_year` / `figure_table_ref` / `ambiguous`）。セクション帰属と `requires_assertion` フラグを伴います。 |
| `figure_refs` | 論文中で実際に参照された図の id（図のバインディングはここに記録され、`science_data.json` は変更されません）。 |
| `unresolved_anchors` / `uncovered_numeric_candidates` | ハードゲートが参照する診断情報。 |

## `evaluation/claim_evidence_hard_gate_{draft,final}.json`

`ari-skill-evaluator.claim_evidence_hard_gate` が書き込む決定論的な
claim/evidence ハードゲートのレポート（`phase` ごとに 1 つ: `draft`、続いて
`final`）。クレームの存在、数値の再計算、数値カバレッジ、図の存在、および宣言
された `metric_contract` を検証します。これは論文と記録された結果の間の
転記/導出の一貫性をチェックするものであり、結果そのものの真実性を
チェックするものでは**ありません**。

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

MCP ラッパーは `should_block`（strict ポリシー下の `phase: final` 時、または
客観的虚偽の検出時にのみ設定される）をパイプラインのハード失敗に変換し、
finalize がスキップされます。ソース:
`ari-core/ari/pipeline/claim_gate/gate.py`。

## `evaluation/evidence_grounded_semantic_review.json`

`ari-skill-evaluator.evidence_grounded_semantic_review` が書き込む、
非ブロッキングのエビデンス裏付けセマンティックレビュー。ハードゲートの
エビデンスに基づいて過剰主張 / 解釈の問題を検出し、`paper_refine` 向けの
`suggested_revisions` を出力します。パイプラインをブロックすることはなく、
エラー時には空の（`status: "ok"`）レビューを返します。refine 後のパスは
これと並んで `evidence_grounded_semantic_review_post_refine.json` のバリアント
を書き込みます。

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
