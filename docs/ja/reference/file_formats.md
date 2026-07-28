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
last_verified: 2026-07-10
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

## RQGM エポックガバナンスファイル（オプトイン `ari_rqgm` モード）

`ari.mode: ari_rqgm` **と** `rqgm.enabled: true` が一致するときにのみ
書かれます（docs/plans/ari_rqgm Task 02）。デフォルトの `simple_bfts`
チェックポイントにはすべて不在です; すべての読み取り側は不在を
「RQGM は一度も走っていない」として扱います。ソース:
`ari-core/ari/rqgm/store.py`; JSON Schema:
`ari-core/ari/schemas/{epoch_state,rqgm_registry,rqgm_transition_event,rqgm_defs}.schema.json`。

### `rqgm_transitions.jsonl`

エポック / レジストリのガバナンス状態の**真実源**。追記専用のハッシュ連鎖
JSONL で、1 行に自己完結したイベント 1 つ:

```json
{"schema_version": 1, "event_id": "evt_000042", "event_type": "prompt_status_change",
 "payload": {"prompt_id": "reviewer_prompt_v4", "from_status": "shadow",
             "to_status": "probationary_active", "transition_id": "transition_003_to_004"},
 "event_hash": "112233445566", "prev_event_hash": "77aa88bb99cc",
 "ts": 1751700000.0, "ts_iso": "2026-07-05T12:00:00Z"}
```

`event_hash = sha256(canonical_json(payload))[:12]`（プロンプト来歴と同一の
`hash12` スキーム — 第二のスキームはありません）; `prev_event_hash` は
前の行へ連鎖します（最初の行では `""`）。タイムスタンプはハッシュ対象
ペイロードの外のメタデータです。イベントタイプ（閉じた v1 集合）:
`epoch_transaction_prepare`、`component_registered`、`prompt_registered`、
`component_status_change`、`prompt_status_change`、`epoch_close`、
`epoch_open`、`epoch_transaction_commit`、`emergency_quarantine`（唯一の
エポック途中変更）。レジストリのステータス変更はエポック境界の
prepare/commit トランザクションを通じて**のみ**受け入れられます; ロード時、
対応する commit の無い prepare 以降のイベントは無視されます
（クラッシュリカバリ）。

ステータス変更のペイロードは RegistryTransitionEngine（RQGM Task 09、
`ari-core/ari/rqgm/transition_engine.py` — 唯一のレジストリステータス
書き込み手）が供給します: 各ペイロードは `transition_id`、固定の T1-T21
`rule_id`（`ari/rqgm/transition_rules.py`; トポロジは凍結コードで、設定
可能なのは `rqgm.transition.*` の数値しきい値のみ）、`from_status` /
`to_status`、`evidence_refs`、`produced_by: registry_transition_engine`
（カーネル CK-REG-004）、そして凍結された境界入力（GovernanceReport +
候補評価 + レジストリハッシュ）の `inputs_sha256` コンテンツハッシュを
運びます。これにより、コミットされたすべての変更は決定論的にリプレイ
できます。

### `rqgm_audit.jsonl`

RQGM の **ImmutableAuditLog**: 同じ追記専用ハッシュ連鎖の行エンベロープで、
独立したファイル単位チェーンを持ちます。書き込まれるガバナンスレコード
ペイロードは GovernanceOrchestrator（RQGM Task 05）が所有し、チェーン
完全性の検証は ConstitutionalKernel（Task 04）の責務です。カーネル判定は
`kernel_report` エントリとして追記されます:
`{"context": ..., "constitution_hash": ..., "blocking": ...,
"violations": [{"code": "CK-…", "check": ..., "severity": ...,
"subject_ref": ..., "rule_id": ..., "detail": ...}]}` — すべての判定は
リプレイ可能です。

各エポック境界で GovernanceOrchestrator の `audit_epoch` はレコードを
ここに追記します（すべて共通の `rqgm_record_base` エンベロープを運び
ます）: `evidence_bundle`（作者は EvidenceClerk のみ）、
`impeachment_motion`（作者は Auditor のみ; 同一ロールの告発は構成的に
拒まれ、カーネルにも却下される）、`governance_defense`、
`impeachment_outcome`、そして最終的な `governance_report`（スキーマ:
`ari-core/ari/schemas/governance_report.schema.json`;
`recommendations[].action` は Task 09 が消費する閉じた集合
`promote_candidate | promote | demote | warn | quarantine | retire |
no_action`）。あるエポックの最新レポートは、その `epoch_id` を持つ
最後の `governance_report` 行です（クラッシュした監査の再実行は新しい
レコード id を追記し、以前の部分レコードは履歴として残ります）。
ガバナンスのスナップショットファイルは存在しません; JSONL が真実です。

RegistryTransitionEngine（RQGM Task 09）は加えて、すべての境界解決を
`epoch_transition` レコードとしてここに監査します（スキーマ:
`ari-core/ari/schemas/epoch_transition.schema.json`; `status` は
`pending | committed | aborted | rejected | failed` のいずれか —
中止 / カーネルブロックされた遷移はログされますがレジストリ変更は
**一切**適用されません）。さらに、コミットされた退役ごと（T17、および
ロールスコープの T20 `utility_policy` supersession）に `retirement_event`
レコードを、コミットされた T17 退役ごとに
`clean_room_generation_request` レコードを書きます（Task 08/10 が消費）。

FrontierRepairEngine（RQGM Task 10、
`ari-core/ari/rqgm/frontier_repair.py`）は、退役を伴うコミット済み遷移の
たびに、さらに 3 つの行タイプを追記します:

- `selective_erasure` — SelectiveErasureEvent 1 件（スキーマ:
  `ari-core/ari/schemas/selective_erasure_event.schema.json`）:
  カーネル作（`prompt_hash` は null、`component_id` は
  `frontier_repair_engine`）で、退役したハッシュ / コンポーネント、
  直接 + 推移的な stale レコード id、そして
  invalidated/recompute/abandoned のノード id を列挙します。消去は
  **論理のみ**です（不変条件 13）: 列挙されたレコードは
  `rqgm_erasure_state.json` でフラグされ、決して書き換え・削除され
  ません。
- `frontier_rebuild` — FrontierRebuildEvent 1 件（スキーマ:
  `ari-core/ari/schemas/frontier_rebuild_event.schema.json`）:
  `frontier_before/after`、removed/reinstated のノード id（勝った子が
  消去された親の Rule-A 復帰）、再計算されたノード id、
  `kernel_validation`。両イベントの `status` は
  `applied | conservative | halted_expansion`（§5.6 の fail-closed
  縮退はしご）です。
- `utility_record` — 生き残った採点済み証拠を残した
  reviewer/adversary/defender/judge の消去ごとに、**再計算された**
  UtilityRecord 1 件（スキーマ:
  `ari-core/ari/schemas/rqgm_utility_record.schema.json` に
  `supersedes: <stale record_id>` と `recomputed_in_epoch` を追加）:
  元のエポックの凍結された重みの下で生き残った入力から再計算され、
  決して再スケールされません — 置き換えられたレコードはディスク上に
  stale なまま残ります。

### `constitution.yaml`

憲法層の人間可読な声明で、`ari run` 開始時に同梱の
`ari-core/config/constitution.yaml` から一度だけコピーされます
（上書きされることはなく、`ari_rqgm` のみ; `simple_bfts` チェックポイント
には不在）。権威ある規則は凍結コード（`ari/rqgm/kernel_rules.py` +
`ari/rqgm/transition_rules.py`）であり、`constitution_hash` —
`sha256(canonical_json(<all rule tables>))[:12]` — でピン留めされます。
このハッシュは `meta.json` の任意の `constitution_hash` キーとしても
追加的に記録されます。

### `epoch_state.json`

現在開いている（または最後に閉じた）エポックの、導出された全体書き換え
スナップショット: 凍結されたアクティブコンポーネント集合、アクティブ
プロンプトハッシュ、utility policy、`registry_version`、決定論的な
`epoch_fingerprint`（`created_at` はメタデータで、フィンガープリントから
除外）。使い捨てです — ロード時にイベントログのリプレイと突き合わせて
検証され、不一致なら再構築されます。

### `rqgm_registry.json`

ComponentRegistry + PromptRegistry を 1 ファイルにまとめた、導出された
全体書き換えスナップショット（`registry_version`、`as_of_event_hash`、
`components[]`、`prompts[]`）。プロンプトエントリはテキストをソースで
参照し（`committed_template` ローダキー、`checkpoint_file` は `rqgm_prompts/`
配下の write-once な進化済み本体、`policy` は Task 14 の統治された utility-policy
本体で `path` 参照）、`prompt_hash`（`sha256[:12]`）と完全な
`prompt_sha256` の両方を運びます。ステータスライフサイクル（プロンプト
とコンポーネントで共有）:
`candidate → validated → shadow → probationary_active → active`、
`active → warning | probation | quarantine`、
`quarantine → retired → banned` — 変更は遷移イベント経由のみ。

### `proposals/`（RQGM Task 03）

チェックポイントスコープの提案ストア — 「すべて保存し、BFTS にはサマリ
だけ渡す」。`ari_rqgm` の ProposalRouter、または明示的にオプトインした
`proposal_router.record_only` デュアルライトによってのみ作られます;
デフォルトの `simple_bfts` ランは `proposals/` ディレクトリを**作りません**。
ソース: `ari-core/ari/rqgm/proposals/store.py`; JSON Schema:
`ari-core/ari/schemas/{proposal_record,proposal_summary_view}.schema.json`。

```
proposals/
  proposal_records.jsonl       # append-only truth (one ProposalRecord per line)
  proposal_index.json          # derived rollup: record_id → status/generator/epoch
  archive/<record_id>/…        # raw outputs, transcripts refs, generator configs
```

`proposal_records.jsonl` の各行は必須の RQGM レコードフィールド
（`record_id` は `prop_%06d`、`epoch_id` — record-only モードでは `null`、
`component_id`、`role: "generator"`、`prompt_hash` — 標準の
`sha256[:12]`、レガシーインポートでは `null`、`created_at`、
`source_refs`、`status: candidate|selected|expanded|superseded`）に加え、
`generator`
（`cheap|mutation|attack_driven|prior_art|virsci|legacy_idea_json`）、
インラインの有界 `summary`（ProposalSummaryView; BFTS が見る唯一の形）、
`archive_refs`（チェックポイント相対の参照であり、決してコピーでは
ない）、そして論理のみの `stale` / `valid_for_frontier` フラグ
（読み取り時の意味論は RQGM Task 10 が所有; 保存済み JSONL は決して
書き換えられない）を運びます。レコードはコンテンツキー
（generator + source_refs + summary）で重複排除されるため、リトライ
された MCP 呼び出しが行を重複させることはありません。`ari_rqgm` では、
`idea.json` はこれらのレコードに対するストア維持の互換プロジェクション
です（ピン留めされたアイデアが先頭に残り、`_pinned` /
`_inherited_from` / `_root_choice` マーカーは逐語的に保持され、
`ideas[i]._proposal_record_id` がレコードへリンクバックします）。

### `rqgm_adversarial_cases.jsonl`（RQGM Task 06）

敵対的進化ループの追記専用の真実（1 行 1 JSON、ロックガード、決して
raise しない — `lineage_decisions.jsonl` の姿勢）。`ari_rqgm` の敵対
ラウンドが走ったときにのみ作られます; すべての `simple_bfts`
チェックポイントには不在です。ソース:
`ari-core/ari/rqgm/adversarial/pool.py`; JSON Schema:
`ari-core/ari/schemas/{rqgm_attack_records,
rqgm_utility_record,rqgm_replay_pool}.schema.json`。行タイプは、ノード
ごとの §5.3 の順序 raw → defense → judgment → validated → utility で:

- `rqgm_adversarial_round` — ノードごとの冪等性マーカー（`node_id`、
  `epoch_id`）: ラウンドはノードあたり高々 1 回走り、resume-safe です。
- `raw_attack` — adversary の攻撃 1 件（`atk_%06d`、ロール
  `adversary`）。**閉じた成果物集合**（`proposal | experiment_plan |
  node_report | metric_result | paper_claim | novelty_claim |
  citation_claim | reproducibility_claim`）を標的とし — 決して
  コンポーネントではなく — 1 個以上の `attack_evidence_refs` を引用
  しなければなりません。監査資料**のみ**: 生の攻撃はいかなるスコアにも
  決して触れません（不変条件 8）。
- `defender_response` — 攻撃ごとの `rebut | concede | propose_fix`
  （`def_%06d`、ロール `defender`）。
- `judgment_record` — ArtifactJudge の判定
  `valid | partially_valid | invalid` とジャッジ割り当ての severity
  （`jdg_%06d`、ロール `judge`）; `invalid` でも常に書かれます。
- `validated_attack` — `valid | partially_valid` 判定に対して**のみ**
  存在します（`vat_%06d`; 裁定必須、不変条件 9）。
- `utility_record` — §5.4 ペナルティチャネルの監査レコード
  （`utl_%06d`、ロール `utility_policy`）: `base_score` / `penalty` /
  `final_score`、値で埋め込まれたエポック凍結のポリシー重み、そして
  `input_refs.validated_attack_ids`（`penalty > 0` のとき常に非空）。
- `adversarial_replay_case` — エポック境界で受け入れられた
  AdversarialReplayCase 1 件（`adv_case_%05d`）: `replay_view`
  （完全な資料; ロール `clean_room_generator` には拒否）+
  `abstract_view`（汚染安全な FailureSummary — 生の攻撃 / 防御テキスト
  なし）。

ペナルティを受けたノードは加えて追加的な `Node.metrics` キー
`_pre_penalty_score` と `_validated_attack_penalty` を運びます;
`_scientific_score` は書き換えられます（sterile ゲートの先例）—
シャドウされることはありません。

### `rqgm/adversarial_replay_pool.json`（RQGM Task 06）

AdversarialReplayPool の導出されたバイト固定スナップショット
（`schema_version`、`case_seq`、`cases[]`）で、GovernanceOrchestrator の
ステップ 7 によってエポック境界で書き直されます;
`rqgm_adversarial_cases.jsonl` が真実源のままで、ロード時にクラッシュ
末尾を埋めます。eviction は論理のみです（`status: "evicted"`; JSONL から
は何も除去されません）。

### `prompt_evolution.jsonl`（RQGM Task 07）

プロンプト進化の追記専用の真実（`prompt_trace.jsonl` をモデルにした
fail-open な書き込み手）。`ari_rqgm` のプロンプト進化パイプラインが
走ったときにのみ作られます; すべての `simple_bfts` チェックポイントには
不在です。ソース: `ari-core/ari/rqgm/prompt_evolution.py`; JSON Schema:
`ari-core/ari/schemas/rqgm_prompt_evolution.schema.json`。行タイプ:

- `prompt_candidate` — PromptMutator / クリーンルームの出力 1 件
  （`pcand_%05d`）で、完全に埋め込まれた PromptSpec
  （`ari-core/ari/schemas/rqgm_prompt_spec.schema.json`）を運びます;
  常に `status: "candidate"` で生まれます — 即時有効化なし。
- `prompt_candidate_validation` — ライフサイクルステージの実行 1 件
  （`pval_%05d`; ステージは `static_validation →
  constitutional_validation → schema_dry_run → replay_evaluation →
  anchor_evaluation → shadow` で単調 — レコードチェーンによりステージ
  スキップは検出可能）。
- `comparison_observation` — shadow 並走サンプル 1 件（`cobs_%05d`）:
  入出力の**ハッシュ**と乖離サマリのみ — shadow の出力テキストがこの
  ファイル、ノードメトリクス、フロンティアに到達することは決して
  ありません（観察のみ）。

`probationary_active`/`active` への採用は `rqgm_transitions.jsonl` に
おける RegistryTransitionEngine のエポック境界トランザクション
（Task 09）を通じて**のみ**起こります — このファイルを通じては決して
起こりません。

### `prompt_specs.json`（RQGM Task 07）

プロンプト進化のレジストリビューの導出ロールアップ
（`schema_version`、`specs{candidate_id → prompt_spec, stages_passed,
rejected}`）で、エポック境界とラン終了時にベストエフォートで書き直され
ます（`prompt_versions.json` パターン）; `prompt_evolution.jsonl` が
真実源のままです。

### `rqgm_prompts/`（RQGM Task 07）

チェックポイントスコープの進化済みテンプレート本文で、進化済み
プロンプトごとに write-once の `<prompt_id>.md` が 1 つあります
（異なる内容の書き直しは拒否されます — アクティブなプロンプトテキストが
in-place で変更されることは決してなく、変更は新しい `prompt_id` を発行
します）。バイトは `prompt_hash = sha256(text)[:12]` でピン留めされます —
まさに `FilesystemPromptLoader.load_versioned` のスキームです。Gate 10 の
カーブアウト: レポート付録がカバーするのはコミット済みの
`ari-core/ari/prompts/**` テンプレートちょうどです; 実行時に進化した
プロンプトは、代わりにこのディレクトリと `prompt_trace.jsonl` の来歴
フィールド（`prompt_version`、`prompt_registry_version`）でカバーされ
ます。`rqgm_prompts/` の不在 == 完全にコミット済みのプロンプト軌跡
（`bfts_web_provenance.json` の P5 パターンをプロンプトに適用したもの）。

### `rqgm_cleanroom.jsonl`（RQGM Task 08）

クリーンルーム再生成の追記専用の真実（`prompt_evolution.jsonl` を
モデルにした fail-open な書き込み手）。退役が
`EpochTransition.clean_room_requests` を生んだときにのみ作られます;
すべての `simple_bfts` チェックポイントには不在です。ソース:
`ari-core/ari/rqgm/clean_room.py`; JSON Schema:
`ari-core/ari/schemas/clean_room_request.schema.json`（要求）と
`ari-core/ari/schemas/clean_room_bundle.schema.json`（閉じた入力
バンドル）。イベント種別（`event` フィールド）:

- `request_created` — 完全な `CleanRoomGenerationRequest` 1 件（5 つの
  禁止入力フラグは const-false; 要求はこのファイルから resume 時に
  リプレイされます — 保留中のものは
  `rqgm.prompt_evolution.max_clean_room_generations_per_epoch` 予算の
  下で次のエポック境界に再試行されます）。
- `bundle_assembled` — `bundle_id` + `bundle_hash`（正準バンドル
  ペイロード上の hash12; バンドルは、コミット済みの
  `rqgm/clean_room_generator.md` メタプロンプトを除くジェネレータ
  コンテキストの**全体**です）。
- `generation_attempted` — `rendered_prompt_hash` 付きのワンショット
  補完マーカー（監査: LLM に到達したのは正確にメタプロンプト + 正準
  バンドル JSON であること）。
- `clean_room_violation` / `candidate_rejected_contaminated` — カーネル
  CK-CLN-001/CK-CLN-002 のスクリーン検出; 汚染された候補が Task 07 の
  ライフサイクルに入ることは決してありません（受け入れ時点でブロック、
  ランに対しては fail-open）。
- `candidate_registered` — `status: "candidate"` での
  `prompt_evolution.jsonl` への引き渡し（決して即時 active には
  ならない）。
- `request_status` — 要求のステータス遷移
  （`pending|generating|generated|rejected_contaminated|failed|superseded`）。
- `fallback_to_baseline` — 空席なし規則: アクティブなプロンプトも
  受け入れ可能な候補も無いロールは、コミット済みのベースライン
  テンプレートへ戻ります。

### `rqgm_erasure_state.json`（RQGM Task 10）

選択的消去の staleness の、導出された全体書き換えスナップショットで、
`rqgm_audit.jsonl` のすべての `selective_erasure` / `frontier_rebuild`
イベントを fold して再構築できます（`prompt_trace` → `prompt_versions`
の「JSONL が真実、スナップショットは導出」の先例）。修復が走ったとき
にのみ作られます; すべての `simple_bfts` チェックポイントと、退役の
無いランには不在です。ソース: `ari-core/ari/rqgm/erasure_state.py`
（書き込みは `ari.checkpoint.save_erasure_state_json` に集約;
`indent=2, ensure_ascii=False`）; JSON Schema:
`ari-core/ari/schemas/erasure_state.schema.json`。
`PathManager.META_FILES` と node_report の `files_changed` ブロック
リストに登録されています。

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

staleness は**読み取り時**です: レコードが stale であるのは、その
`record_id` が `stale_record_ids` にあるとき、かつそのときに限ります —
保存済み JSONL 行は決して書き換えられず（不変条件 13）、このファイルの
不在は「何も stale でない、すべて有効」を意味します（Task-10 以前の
チェックポイントは有効なまま）。消去 / 無効化されたノードは加えて、
`tree.json` を通じて永続化される追加的な `Node.metrics` センチネル
`_stale`、`_valid_for_frontier`、`_stale_reason`
（`generator_retired | utility_invalidated | trace_depth_exceeded` —
診断のみ）、`_erasure_event_id` を運びます; これらは `simple_bfts` へ
モードを戻した後も消去されたノードを除外し続けます（汚染はモード切替に
よって清浄にはなりません）。

### `rqgm_governance_cache.jsonl`（RQGM Task 12）

ガバナンス結果キャッシュ: 追記専用 JSONL で、キャッシュされたガバナンス
評価ごとに 1 レコード。ソース: `ari-core/ari/rqgm/governance_cache.py`;
JSON Schema: `ari-core/ari/schemas/rqgm_governance_cache.schema.json`。
`PathManager.META_FILES` / `_TRACE_FILES` と node_report の
`files_changed` ブロックリストに登録されています。不在 == 空の
キャッシュであり、決してエラーではありません; すべての `simple_bfts`
チェックポイントには不在です。

```json
{"schema_version": 1, "cache_key": "a3f19c02b7d4e881", "role": "judge",
 "epoch_id": "epoch_004", "prompt_hash": "9f2c01ab34de",
 "artifact_hash": "sha256:…", "input_context_hash": "sha256:…",
 "output_schema_hash": "sha256:…", "result_ref": "judgment_00042",
 "score": 0.8, "created_at": "2026-07-05T00:00:00Z"}
```

`cache_key = sha256(artifact_hash ␟ prompt_hash ␟ role ␟ epoch_id ␟
input_context_hash ␟ output_schema_hash)[:16]`（`␟` = `\x1f`）; 2 つの
コンテンツハッシュは正準 JSON 上の完全 sha256 です。`created_at` は
来歴のみ — 決してキーの一部ではありません (P2)。リプレイ検索
（`rqgm.replay.use_cached_results`）はキーをケースの**起源**エポック id
と候補自身の `prompt_hash` で計算します — 唯一許可されたエポック横断
ヒットです; エポック境界の候補評価はまずこのキャッシュを参照し、プール
由来のケースごとの `score` 値を書き戻します
（`ari-core/ari/rqgm/governance/_adjudication.py`）。エントリが in-place
で無効化されることはありません: 退役したプロンプトのエントリは、その
`prompt_hash` が検索に二度と現れないためアドレス不能になるだけです
（不変条件 13）。予算消費とガバナンスレベルの割り当てはここには保存
されません — それらは `budget_consumed` / `budget_degraded` /
`governance_level` 行として `rqgm_audit.jsonl` に乗り（ソース:
`ari-core/ari/rqgm/budget.py`）、エポックごとの予算カウンタが
`ari resume` を生き延びる仕組みでもあります。

### `rqgm_eval_metrics.json` / `rqgm_injection_provenance.json`（RQGM Task 13）

評価ハーネスの成果物で、`scripts/rqgm_eval/run_ablation.py` ハーネスが
自ら起動したランで**のみ**書かれます（どちらのモードでも、通常の
チェックポイントには不在）。ソース:
`ari-core/ari/rqgm/evaluation/{metrics,injection}.py`。どちらも
`PathManager.META_FILES` と node_report の `files_changed` ブロック
リストに登録されています。

- `rqgm_eval_metrics.json` — `compute_metric_report` による 13 個の
  事後メトリクス（永続化された成果物上の純粋関数; LLM なし、導出値に
  壁時計なし — メトリクス 13 はメタデータのみで、決してハッシュされ
  ない）。エンベロープ: `schema_version`、`computed_by_version`、
  `condition_id`、`run_id`、`seed`、`config_digest`（`workflow.yaml` の
  sha256-12）、`injection_ids`、そして計画 §5.4 の固定キー順の
  `metrics{key → {value, numerator, denominator, evidence_refs,
  applicable[, detail]}}`。データソースの欠落は `applicable: false` を
  生み、決してエラーになりません。
- `rqgm_injection_provenance.json` — 永続的な合成軌跡マーカー
  （`bfts_web_provenance.json` の先例）: `schema_version`、
  `injection_ids`（隔離された `eval_*` 名前空間。`adv_*` / `anchor_*`
  ケースと交わらない）、`specs_digest`（id ソート済み正準スペック
  リスト上の hash12）、`harness_version`。このファイルを持つ
  チェックポイントは注入された評価ランであり、実ランと決して混同
  されてはなりません。

キャンペーンレベルの出力（`ablation_report.{json,md}`、展開済み条件
設定）はチェックポイントの外、`workspace/rqgm_eval/<eval_id>/` 以下に
置かれます — `docs/guides/rqgm_evaluation.md` を参照。

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
