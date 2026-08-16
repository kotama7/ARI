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

# ファイルフォーマットリファレンス

ARI のすべてのチェックポイントは自己記述的なディレクトリです。このページでは
ARI が読み書きする JSON / YAML / Markdown ファイルを、標準的なキー一覧および
それらを生成する実装へのポインタとともに一覧します。

JSON Schema として正式に仕様が定められているスキーマについては
`ari-core/ari/schemas/` を参照してください。

## `experiment.md`

プレーンな Markdown で、1 つの重要な規約があります。決定論的ヘルパー
`parse_metric_from_experiment_md`
（`ari-core/ari/pipeline/experiment_md.py:30`）が
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

マーカーより**上**の本文のみを編集してください。この追記は workflow.yaml の
`plan_promote` で制御されます（同梱の既定値は `index_only`。`full` はプラン
全体を書き、それ以外の値ではブロック自体が出力されません）。開始マーカーが
すでに存在する場合は追記をスキップするため、パイプラインのリトライで重複する
ことはありません。

## `idea.json`

`ari-skill-idea.generate_ideas` の**返り値そのもの**を、エージェントループ
（`ari-core/ari/agent/loop.py` の `generate_ideas` 結果ハンドラ）が
`{checkpoint}/idea.json` へそのまま書き出したもので、BFTS 実行のプランの
シードとなります。

トップレベルの形式（抜粋 — ツールはこれ以上のキーを返します）:

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

メトリクスの位置に注意してください。`primary_metric` / `higher_is_better` /
`metric_rationale` は**トップレベル**（型付き `research_contract` のレガシー
射影）であり、アイデアごとのキーではありません。`alternatives_considered`
というキーはコードのどこにも存在しません。型付き候補が却下されたアイデアは、
admitted 用のフィールドの代わりに `"contract_status": "rejected"` と
`rejection_reasons` を持ちます。

子は継承したエントリの `"_pinned": true` を設定して親の選択アイデアを固定します。
後続の `generate_ideas` 実行は上書きせずに新しいアイデアをその後に追加します。

## `evaluation_criteria.json`

`idea.json` と experiment.md から派生したパイプライン側キャッシュ。

```json
{
  "primary_metric": "GFlops/s",
  "higher_is_better": true,
  "metric_rationale": "...",
  "metric_unit": "...",
  "research_contract_digest": "sha256:..."
}
```

`ari-core/ari/pipeline/driver.py`（`WorkflowDriver.run` のプリフライト）が
書き込みますが、**ファイルがまだ存在しない場合のみ**であり、実行途中で更新
されることはありません。ソースは 4 つを順に試し、最初に当たったものが勝ち
ます: `idea.json` 内の型付き `research_contract`（`metric_unit` /
`research_contract_digest` もこれが埋めます）、ノードの `memory_snapshot` の
`EVALUATION_CRITERIA:` 行、`idea.json` のレガシーなトップレベル
`primary_metric` 系キー、そして experiment.md に対する
`parse_metric_from_experiment_md`。型付き契約のパース失敗は例外になりますが、
それ以外のソースの失敗は黙って空文字列に縮退します。読み出すのは
`ari-core/ari/pipeline/orchestrator.py`（`nodes_to_science_data` のランキング、
73 行目付近）です。

## `tree.json`

BFTS のライブ状態で、チェックポイントのフラッシュごとに書き換えられます —
書き込みは 1 秒あたり高々 1 回にスロットルされ
（`ari.checkpoint.save_tree_incremental`）、呼び出し側が `force=True` を渡した
場合のみ即時に書かれます（終端のノード遷移がそうします）。形式:

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

ここで読み手が驚く点が 2 つあります。`nodes` はノード ID をキーとするマップ
ではなく**リスト**です — `root_node_id` は存在せず、root は `parent_id` が
`null` のエントリです。そして `schema_version` もノードごとの `score` も
ありません: ランキングに使う量は `metrics` の中の `_scientific_score` です。
`Node.to_dict` はさらに型付きの科学的保証グループ
（`knowledge_skill_refs` … `repair_allowed_changes`）を、そのいずれかが非空の
ときにのみ追記するため、通常のノードではこれらのキーは不在です。

## `nodes_tree.json`

同じノードリストで、`ari-skill-transform`、`ari-skill-plot`、viz ダッシュボード、
EAR パイプラインが使用します。`tree.json` より詳細なビューでは**ありません** —
ノードの dict は同一の `Node.to_dict()` ペイロードです。差分は端の部分だけです:

| キー | 意味 |
|---|---|
| `experiment_goal` | トップレベル。BFTS ループは `experiment.md` の先頭 3000 文字を書き、パイプラインドライバは渡されたゴール文字列全体を書く |
| `nodes[].memory` | パイプラインドライバの書き込み（`ari-core/ari/pipeline/driver.py`）でのみ付加される。そのノードのメモリエントリを新しい順に、`ARI_TRANSFORM_MEMORY_MAX_ENTRIES`（既定 20）件で打ち切り、各 `text` を `ARI_TRANSFORM_MEMORY_MAX_CHARS`（既定 2000）文字で切り詰めたもの。BFTS ループ自身のフラッシュは `memory` キーを書かない |

読み取り側は 3 段の優先順位 `tree.json` → `nodes_tree.json` → 最も新しい
非空の `node_*/tree.json`（レガシーレイアウト）でツリーを解決するため、両方を
持つチェックポイントは `tree.json` から読まれます。

## `full_log.json`

各ノードの完了時に、そのノードの `work_dir` へ書き込まれる**フルの ReAct 記録**。
`node_report.json` と同様に `PathManager.META_FILES` に含まれるため、子の work_dir へ
**継承されません**（各ノードが自分の分を書く）。形式: `{node_id, parent_id, depth,
react_steps, max_react_steps, ended_by, trace_entries, tools[], messages[],
auxiliary_llm_calls[], trace_log[]}`。

- `tools` — モデルが実際に渡された OpenAI function-calling スキーマ（名前＋説明＋引数）＝**各ツールの使い方**。system プロンプトの `AVAILABLE TOOLS` 行は名前だけで、使い方スキーマは API の `tools=` 引数で別途渡されるため、このフィールドで確認できます。
- `messages` — **会話の全体**：system プロンプト、注入された handoff（該当アームでは親の
  `summary` / `full_log`）、タスク、そして全ての user / assistant / tool ターン（tool 呼出の
  名前＋引数、tool 結果を含む）。**入力プロンプトも出力も全て**入っており、tool トレースだけでは
  ありません。
- `auxiliary_llm_calls` — ReAct ループの後にこのノード*について*行われた、ツール無しの
  LLM 呼び出し。主に max steps 時に強制される Reflection 自己レビューです。
- `trace_log` — 素早く見るための簡潔な tool 呼出トレース（`→ tool(args)` / `← result`）。
  `trace_entries` はその長さ。

`steps` フィールドは存在せず、それを外したこと自体が要点です: かつての `steps` は
`len(trace_log)` — つまり**トレースエントリ数、1 イテレーションあたり 2 件**（呼出と
その結果）— であり、予算が記録されていませんでした。そのため 15 ステップの予算を
使い切ったノードが `steps: 30` と記録され、当時の既定値 80（現在は 20 に変更済み）に
対する 30 = 「まだ余裕がある」と読めてしまいました（実際には枯渇していた）。現在は両方の数を、それぞれの
意味の名前で保持します: `react_steps`（使用したイテレーション数）と
`max_react_steps`（予算）、そして `trace_entries` を別に持ちます。`ended_by` は
ノードが*どう*停止したかを示します（`finish_json` = エージェントが結論した、
`max_steps` = 予算切れ — このノードの `success` はエージェント自身の判断ではなく、
フレームワークが work_dir を採点した結果です）。

`trace_log` はツールを呼ばないモデル（例: 0.5b 床）では空（`trace_entries: 0`）ですが、
`messages` には送信された完全なプロンプトが常に入ります。

## `node_report.json`

`mark_success` / `mark_failed` 時にノードごとに書き込まれる自己レポート。
スキーマ: `ari-core/ari/schemas/node_report.schema.json`。
`generate_ear`、`nodes_to_science_data`、`bfts.expand` が参照します。

**必須キー**: `schema_version`（定数 `1`）、`node_id`、`depth`、`status`、
`files_changed`、`metrics`、`artifacts`。他は任意（下記の条件で出力）。

### コアフィールド（常時）

| フィールド | 型 | 意味 |
|---|---|---|
| `schema_version` | int(1) | スキーマ版 |
| `node_id` | string | このノードのID |
| `parent_id` | string \| null | 親ノードID（root は `null`） |
| `ancestor_ids` | string[] | root→親 の系列 |
| `depth` | int | 木の深さ（root=0） |
| `status` | string | `success` / `failed` 等 |
| `started_at` / `completed_at` | string | ISO8601 時刻 |
| `files_changed` | object | `{added, modified, deleted, inherited_unchanged}`、各 `{path, sha256}`。親比の差分（`added+modified+deleted==0` は sterile ＝ no-op ノード） |
| `what_was_done` | string | **エージェント自身の自然言語 自己報告**。結論できたノードのみ充填（tool を使えない弱モデルは空） |
| `metrics` | object | 評価器定義のスカラー測定値。共通スキーマはキー名や意味を規定しない。 |
| `measurement_valid` | bool | 評価器による客観的な有効判定。LLM が書く Reflection とは分離する。 |
| `evaluation_status` | string | 型付きの評価器判定。評価器が明示しなかった場合は `measurement_valid` から `valid` / `candidate_invalid` を既定値とする。`infrastructure_error` は科学的なゼロ**ではなく**、そのランを除外する |
| `evaluation_cases` | object | `{case名: {valid, measurements}}` 形式のケース別証拠。ケース名と JSON スカラーの測定名はハーネスが定義し、共通スキーマは問題固有の意味を持たない。 |
| `measurement_audit` | object | 評価器のみが書く監査レコード — `{effective_candidate_compile_flags, rejected_candidate_compile_flags, cases}`。永続化されるが、親→子の handoff テキストには決してレンダリングされない |
| `self_assessment` | object | `{headline, concerns}`。エージェント自身の LLM 自己レビュー（無ければ空）。 |
| `self_report_stage` | string | 採点後の自己レビューが `self_assessment` / `next_steps_hints` を置き換えるまでは `pre_evaluation`。これが無いと、評価器の結果を踏まえた自己報告と、採点前の当て推量とが区別できない |
| `migration_source` | string | ビルダが書いたレポートは `fresh`、それ以外はそのレポートを生んだマイグレーション名 |
| `compute_env` | object | メトリクス gaming の adversary が読む、組み立て済みのマシンビュー: `executor` / `cpu_info` / `mem_total_kb` / `compilers` / `hostname` に加え、`env_signature`、`parent_env_signature`、`env_signature_mismatch` |
| `next_steps_hints` | string[] | エージェント自身の自己レビューによる次の一手（LLM self-review）。エージェントが 1 つでも挙げていれば、評価器由来のリストを**置き換える**。フォールバックは評価器の中域(0.4-0.7)軸根拠であり、決定論採点（グレード軸なし）ではそのフォールバック自体が空になる。 |
| `build_command` / `run_command` | string | 運用足場（ビルド/実行コマンド） |
| `artifacts` | object[] | 生成物。`filename` + `role`（`data_output` / `log` / `binary` / `figure` / `unknown` の 5 値）は必須。ファイルを stat できた場合は `sha256` / `size` が付き、`inline: true` はディスク上にファイルを持たない捕捉済み stdout を表す（プロベナンス監査は幻の欠落成果物を報告せずスキップする）。エージェントが宣言した分に加え、ビルダが work_dir 直下のファイルのうち role が `data_output` / `log` / `figure` のものを自動捕捉する — 足場のソース、コンパイル済みバイナリ、ARI 内部 JSON は入らない。claim ゲートは測定ドキュメントの `artifact_digests` をこの `sha256` に突き合わせる |
| `evaluator_reason` | string | 決定論評価器の判定理由 |
| `trace_log_summary` | string | 軌跡の要約 |

型付きの科学的保証グループ（`knowledge_skill_refs`、
`instruction_identity_digest`、`capability_binding_lock_digest`、
`bound_tool_refs`、`assurance_status` / `assurance_tier`、ハーネスロックと
attestation のダイジェスト、`property_verdicts`、`frontier_class`、および
manuscript-repair 系の系譜フィールド）は
`ari-core/ari/orchestrator/node_report/scientific_assurance.py` が graft します。
スキーマ上は任意であり、互換経路では空のままです。

### 探索ラベル（常に記録される）

`label` / `raw_label` / `original_direction` は**常に記録される**。

かつて **`ARI_REPORT_MINIMAL=1`** でこれらを記録から抑制できたが、**このフラグは削除した**。
ラベルは記録用の飾りではなく、(1) system プロンプトの `NODE ROLE`、(2) 子の `Task:` 行、
(3) **ノード選択**（既定 `scientific_plus_diversity` の `diversity_bonus` が過少ラベルに +0.05）
の3経路で探索を**駆動する**。記録からだけ消しても影響は残り、証拠だけが消える —
実際に handoff study では、ラベルを「off にした」つもりの 4アーム実験で ABLATION 比率が
アーム間で 0/1/3/4 と偏り続け、node_report からは**発見できなかった**。

ラベルの影響を消したい場合は、記録を隠すのではなく**機能そのものを off** にする：
**`ARI_BFTS_NO_LABEL=1`**（上記3経路すべてを停止し、全ノードが同一の中立ロール／タスクを受け、
選択もラベルを参照しない）。この時もラベルは記録され続けるので、読み手は
「本当に不活性だったか」を**検証できる**。

| フィールド | 意味 |
|---|---|
| `label` | BFTS 探索役割 `draft` / `improve` / `debug` / `ablation` / `validation` / `other`。**不活性ではない** — `ARI_BFTS_NO_LABEL` で機能を止めない限り、上記 3 経路を駆動する。`ARI_BFTS_DETERMINISTIC_LABEL=1` では LLM 提案ではなく direction から決定論導出される |
| `raw_label` | プランナが提案したラベル文字列を**そのまま**保持する。LLM がラベルを返した場合は、それが正規 5 種のいずれかに綺麗に対応する場合でも保持される（提案 `"Improve"` は `label: "improve"` かつ `raw_label: "Improve"`）。`raw_label` を排他的にフォールバック先とするのはノードの*表示名*だけであり、そこでのみ `other` 限定である。ラベルが提案ではなく direction テキストから推論された場合は空で、`ARI_BFTS_DETERMINISTIC_LABEL=1` では強制的に空になる |
| `original_direction` | 親の expand がこの子に与えた方向テキスト |

### 任意フィールド②: 実行環境プロベナンス

`executor` / `hostname` / `slurm_job_id` / `slurm_partition` / `slurm_nodelist` /
`cpu_info` / `mem_total_kb` / `compilers` は、このノードが実際にどこで走ったかを
記録します。これらは**常に存在し**、run_env スキルが何も捕捉しなかった場合
（レガシーラン、ドライラン、評価のみ）は空の値を持ちます。無条件に出力するのは
意図的です: キーを省略すると「何も捕捉されなかった」と「このキーがフィールド追加
より前のものである」が区別できなくなり、マシンが不明な測定と、マシンを一度も
問わなかった測定とは区別できなければならないからです。

ここでのマシン識別情報の捕捉は意図的なものです。`node_report.json` は
`workspace/checkpoints/` 配下のラン成果物であって、リポジトリの内容ではありません
— 追跡対象のソース・テスト・ドキュメントにクラスタ名 / パーティション名 /
ホスト名を書かないという規則は変わりません。

上記の `compilers` は**モジュールをロードする前**のビューです: ARI プロセス内で
捕捉されたものであり、そのプロセスは何もロードしていません。`execution_env` は
実行したシェルが*自分自身*について書いた記録であり、ある測定がどのモジュールの
下で得られたのかを述べる唯一の場所です — これが無いと、モジュールをロードして
比較したかった当の 2 つのモジュール構成が、比較のためのレポートの上で同一に
見えてしまいます。

| キー | 意味 |
|---|---|
| `loaded_modules` | コマンド終了時点の `$LOADEDMODULES` を、その順序のまま分割したもの。順序には意味があり（後のモジュールが先のモジュールのパスを上書きしうる）、ソートも重複除去もしない。`[]` は「何もロードされていない状態でコマンドが走った」であり、キー自体が無い（シェル系ツールが 1 度も走らなかった）のとは区別される |
| `module_path` | コマンドから見えた `$MODULEPATH` |
| `path` | モジュールロード後の `$PATH` — ツール解決順序そのものなので、ARI がコンパイラ名を 1 つも名指ししなくても「どのバイナリを使ったのか」に答えられる |
| `recorded_at` | シェルがこの記録を書いた時刻 |

書き込みは `EXIT` トラップで行われるので、コマンドが失敗しても記録は残り
（失敗した測定の環境は、成功した測定の環境と同じくらい興味深いものです）、
コマンドの終了ステータスも保たれます。`_exec_env.json` は
`PathManager.META_FILES` に含まれます: これは 1 ノードの実行を記述するもので
あり、継承コピーができてしまうと、親のモジュールを、それをロードしていない子に
帰属させることになるからです。

`partitions_used` はこの視野を*このノード*から*実験全体*へ広げます。異種混在
クラスタにまたがって走ったランは、実際にどこで実行されたのかという単一の記録を
残さず、ノードをまたいだメトリクス比較をその背後のハードウェアと突き合わせて
検証できなくなるからです:

| キー | 意味 |
|---|---|
| `this_node` | このノード自身の割り当てのパーティション |
| `used` | そのランが触れた相異なるパーティションすべて。同じランの各兄弟ノードの `_run_env.json` から走査する — 設定値ではなく観測値 |
| `by_partition` | パーティションごとの `node_count` と、そこで観測された相異なる `nodelists` / `hostnames` |
| `catalog` | `heterogeneous_env.json` によるパーティションごとのプローブ — 各パーティションが*何であるか*。プローブされたがノードを 1 つも走らせなかったパーティションも含み、それが「X を使えたのに使わなかった」に答えられる理由である。`arch` / `cpu_model` / `threads` / `mem_total_kb` / `gpus` / `compilers` / `cache_measured` に圧縮される |
| `catalog_path` | 完全なカタログへのパス。生の `module avail` / `lscpu` ダンプはパーティションあたり約 30 KB になり、チェックポイント直下に既に 1 部あるので、各ノードのレポートに複写せず、そこを指すだけにする |

兄弟走査が実行されるのは、ノードの `work_dir` が本当に
`experiments/{run_id}/{node_id}` である場合だけです。そうでない場合、無関係な
ディレクトリのファイルをこの実験の一部として数えるのではなく、`used` は空の
ままになります。

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
  "self_assessment": {"headline": "内側ループをベクトル化、約1.2倍を計測。", "concerns": ["3形状のみ検証"]},
  "next_steps_hints": [],
  "build_command": "", "run_command": "CC ?= cc",
  "artifacts": [{"filename": "result", "role": "unknown"}],
  "evaluator_reason": "ok", "trace_log_summary": ""
}
```
（上例は `ARI_REPORT_MINIMAL` 抑制の削除**前**の出力なので label 系が不在。現在の node_report は
`label` / `raw_label` / `original_direction` を**常に**含む。機械情報が不在なのは run_env スキル
未使用のため＝必要時のみ populate される項目であり、抑制されているわけではない。）

## `results.json`

`tree.json` / `nodes_tree.json` を書くのと同じフラッシュがチェックポイント
直下に書きます。したがって実行完了時にだけ出る成果物ではありません:

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

ここには `experiment_goal` も `primary_metric` も `best_node` もありません —
「どのノードが勝ったか」はこのファイルには記録されず、必要になった時点で
`select_best_node` が再計算します（`verified_context.json` を参照）。

同じベース名がノードの work_dir の中では**別の意味**を持ちます: エージェントは
`ari-skill-coding.emit_results` 経由で `{ノードの work_dir}/results.json` を書き、
claim ゲートはそこから読み戻します。`results.json` が `PathManager.META_FILES` の
うち唯一 `NODE_VISIBLE_NAMES` によって `scope="node"` で claim を外されている
エントリなのは、このためです。

このノードごとの `results*.json` は自由形式の dict ではなく、型付きの測定
ドキュメントです:

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

プロベナンスはトップレベルの `_provenance` マップではなく、**測定ごとの
`provenance` 文字列**です: 測定された天井には `microbench` / `benchmark`、
検証残差には `correctness` / `reference`、それ以外には `declared` / `constant`。
その文字列を、ハードゲートが読む `{operand: source}` マップに変換するのは
`ari-skill-transform` です — ノードディレクトリ内のすべての `results*.json`
バリアントにまたがって和集合を取り、`science_data.json` 射影の
`configurations[]._provenance` として公開するので、既定以外のファイル名で
`emit_results` した場合でもエビデンスは表に出ます。ゲートはこれを使って、
測定された天井や正当性チェックが実際に実行されたことを確認します。

## `science_data.json`

`ari-skill-transform.nodes_to_science_data` が実行済みノードのエビデンスから
構築する、論文向けのサイエンスサーフェス。ディスク上ではフラットなオブジェクト
**ではなく**、3 つのセクションとダイジェスト群からなる型付きの
`ari.science-data/v1` ドキュメント
（`ari-core/ari/schemas/science_data_v1.schema.json`）です:

| キー | 意味 |
|---|---|
| `raw` | `configurations[]`（ノードごとの parameters / measurements / measurement_records / scores / environment / `provenance_labels`）、`measurement_status`、`node_report_status`、`tree_artifact`、`raw_digest` |
| `derived` | `claims`、`numeric_assertions`、`metric_summaries`、`summary_stats`、`anomalies`、`formula_registry_digest`、`derived_digest` |
| `interpretation` | 唯一の LLM 執筆セクション — `experiment_context`、`implementation_overview`、`evaluation_protocol`、およびそれ自身のモデル / プロンプトのプロベナンスと `interpretation_digest` |
| `metric_contract` | トップレベル。`metric_contract.json`（後述）から graft された idea 由来のメトリクス正当性契約。これにより、ゲートはユニバーサル不変条件レジストリだけでなく*宣言された*契約も強制します |
| `provenance` / `limitations` / `run_id` / `migration_status` | トップレベル。入力成果物、スキル / カタログのロック、そしてそのランが確立できなかったこと |
| `deterministic_digest` / `science_data_digest` | トップレベルの自己ダイジェスト。前者は `raw`+`derived`+契約を、後者はドキュメント全体をカバーします |

`derived` の内側:

| キー | 意味 |
|---|---|
| `claims` | ノードのエビデンスから決定論的に派生した候補クレーム。各クレームは実在する `node_id` + `metric_path` にアンカーされます。本文は論文ライターが `% CLAIM:Cx:NCx` アンカーを保持したまま書き換えるテンプレートのシードです。 |
| `numeric_assertions` | ハードゲートが再導出し、許容誤差内で論文に記載された数値と比較するオペランド/数式レコード。 |

**フラットな**サーフェス — トップレベルの `configurations[]` / `per_key_summary` /
`summary_stats` / `claims` / `numeric_assertions` と、内部用のアンダースコア
接頭辞 `_config_nodes` / `_anomalies`、および configuration ごとの
`_provenance` — は読み取り時の*射影*
（`ari.science_data_contract.science_data_projection`）であり、ハードゲート・
paper スキル・viz レイヤがそれぞれ自分で計算します。ファイルの中身そのもの
ではないため、生の JSON を読む消費側は射影を経由するか、型付きセクションを
直接指す必要があります。`_anomalous_metrics` はそのどちらにも残りません:
transform スキルは物理的にありえない値から論文ライターを遠ざけるために中間の
configuration ごとの dict にこれを刻みますが、`ScienceConfigurationV1` には
そのようなフィールドが無いため、ファイルにも射影にも到達しません — この
異常は `derived.anomalies` にのみ保存されます。

## `metric_contract.json`

`make_metric_spec`（ari-skill-evaluator）が出力し、`idea.json` / `tree.json`
の隣の `{checkpoint}/metric_contract.json` に書き込まれる idea 由来の
メトリクス正当性契約。`nodes_to_science_data` がこれを `science_data.json`
に graft します。永続化されるドキュメントは正準の
`ari.metric-gate-contract/v1` 射影
（`ari-core/ari/schemas/metric_gate_contract_v1.schema.json`）であり、契約を
フラットに並べるのではなく入れ子にします:

```json
{
  "schema_version": "ari.metric-gate-contract/v1",
  "source": "research-contract" | "human-admitted" | "legacy-migrated",
  "source_idea_digest": "sha256:...",
  "projection_digest": "sha256:...",
  "research_contract_digest": "sha256:...",   // source == research-contract のときのみ
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

ゲートの数式処理は依然として**フラットな**契約を消費するため、ゲートは評価の
前に変換します: `science_data["metric_contract"]` が
`schema_version: "ari.metric-gate-contract/v1"` を持つ場合、これはパースされ、
メモリ上で `MetricGateContractV1.gate_projection()` の結果に置き換えられます。
射影は `key` / `unit` / `direction` / `comparison_scope` / `formula` /
`formula_operands` / `tolerance` / `claims` / `correctness_required` /
`ceiling_must_be_measured` / `required_measured` / `invariants` /
`correctness` へと平坦化します。ここから 2 つのことが従います。
`ceiling_must_be_measured` は宣言されるものではなく*導出*されます
（`normalization_ceiling == "measured"`）。そして `ceiling_select` —
`contract.check_contract` が今も対応している、宣言型のレジーム条件式 — は
正準ドキュメントにフィールドを持たず射影にも現れないため、レガシーな
フラット契約の場合にしかゲートに届きません。

正準スキーマバージョンを認識することは、ゲートを**厳格エビデンス**モードに
切り替えることでもあり、このモードでは通常なら advisory 止まりの findings が
エラーになります。すべての式は制限付き AST であり
（`ari-core/ari/pipeline/claim_gate/formula_eval.py` を参照）、この機構は
roofline / GFLOP / キャッシュの意味論を一切知りません — 述語はすべて実験
ごとに宣言されます。

`correctness_required` / `ceiling_must_be_measured` はエージェントが破棄
できない idea 所有のフラグであり、ノードの `results.json` の測定プロベナンス
に付いた EVIDENCE タグ（測定ソースの天井、正当性ソースの残差）によって
満たされます。エージェントが宣言した名前では満たされません。突合は意図的に
寛容で、ゲートは部分文字列の語根を探します（measured 側は
`bench` / `measur` / `empiric` / `stream` / `baseline`、correctness 側は
`correct` / `verif` / `referenc` / `valid` / `gold` / `truth` / `oracle` /
`ground_truth`）。正直なランがタグを言い換えても過剰にブロックしないため
です。ソース: `ari-core/ari/pipeline/claim_gate/contract.py`。

このファイルは **mint-once** です: `_persist_metric_projection` は
`projection_digest` が異なる既存契約の上書きを拒否し、以降の
`make_metric_spec` 呼び出しは再抽出せず、永続化された契約をそのまま返します
（レスポンスに `contract_frozen: true` が付きます）— LLM の命名は参照的に
安定しないため、実行途中で再生成すると新しいエビデンス語彙が生成され、
旧名ですでに出力されたエビデンスが完全一致ゲートから見えなくなるためです。
admitted な idea 契約も人手レビュー済みの提案も無い場合、
`make_metric_spec` は何も mint せず、`contract_frozen: false` と
`admission_status: "human-review-required"` を返して
`propose_metric_contract` を指します。

## `verified_context.json`

ベストノードの root→best 系統にスコープされたアーティファクト裏付けの
クレーム。`ari-core/ari/pipeline/verified_context.py` が書き込み、
`write_paper` ステージが定量的クレームを検証済みでアーティファクトに
裏付けられた（理想的には再現された）結果に基づいて生成できるようにします。
型付き research-memory ストアに少なくとも 1 つの裏付けクレームがある場合に
**のみ**書き込まれます。ストアが空の場合はファイルが生成されず、論文ステージ
は以前とまったく同じ挙動になります。ベストノードの選択
（`select_best_node`）は消去済みノード
（`metrics._valid_for_frontier=False`）を除外します — すべての候補が消去
されていれば勝者なしとなりファイルは書かれません。以前に書かれた
`verified_context.json` は、`best_node_id` **または**（消去フィルタ後の）
`lineage` が新しい結果と一致しなくなった場合に、すでに消去された系統の上に
論文を接地させないよう削除されます。両方が一致し続ける場合は保持されるので、
メモリバックエンドの一過性の失敗でまだ有効な成果物が捨てられることはありません。

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
| `paper_claim_links` | アンカーをキーとするレコード（`anchor` / `claim_id` / `numeric_id` / `section` / `span_hash` / `line_range` / `figures` / `resolved`）。**アンカー**が refine/render を通じて生き残る安定キーであり、`span_hash` は文の変更を検出します。 |
| `numeric_mentions` | 論文中のすべての数値トークンを分類したもの（`result_claim` / `experimental_setting` / `citation_year` / `figure_table_ref` / `figure_evidence` / `ambiguous`）。セクション帰属と `requires_assertion` フラグを伴います。このフラグを立てるのは `result_claim` だけであり、`figure_evidence` は figures マニフェストが説明できる行の数値を後段で再分類するもので、フラグを**外し**ます。 |
| `writer_assertions` | ライターがアンカー行そのものにインライン記述した前方宣言（`metric=` / `formula=` / オペランド役割の `key=value` トークン）。`dropped_declarations` は宣言が採用され*なかった*アンカーをすべて記録し（最も多いのはインラインの `formula=` が無い場合、すなわち事前生成済みエビデンスへの前方参照）、`suspect_declarations` は採用されたが疑わしいものを記録します。どちらも、落とされた宣言が単に消えるのではなく見えるように保持されます。 |
| `figure_refs` | 論文中で実際に参照された図の id（図のバインディングはここに記録され、`science_data.json` は変更されません）。 |
| `unresolved_anchors` / `uncovered_numeric_candidates` | ハードゲートが参照する診断情報。 |
| `counts` | 固定のロールアップ（`anchors`、`resolved_anchors`、`writer_assertions`、`dropped_declarations`、`suspect_declarations`、`numeric_mentions`、`result_claim_mentions`、`uncovered_numeric_candidates`、`figure_refs`）。finalize は再導出せずこれを読みます。 |

このドキュメントは自己識別的かつ自己ダイジェスト付きです: `schema_version:
"ari.paper-claim-links/v1"`、`stage: "link_paper_claims"`、読み取った LaTeX に
対する `paper_digest`、そしてレコード全体に対する `claim_links_digest`。

## `evaluation/claim_evidence_hard_gate_{draft,final}.json`

`ari-skill-evaluator.claim_evidence_hard_gate` が書き込む決定論的な
claim/evidence ハードゲートのレポート（`phase` ごとに 1 つ: `draft`、続いて
`final`）。クレームの存在、数値の再計算、数値カバレッジ、図の存在、および宣言
された `metric_contract` を検証します。これは論文と記録された結果の間の
転記/導出の一貫性をチェックするものであり、結果そのものの真実性を
チェックするものでは**ありません**。

このレポートは型付きの `ari.gate-report/v1` ドキュメント
（`ari-core/ari/schemas/gate_report_v1.schema.json`）で、キーをソートして
ダイジェスト付きで書かれます:

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

改名に注意してください: ポリシーのフィールドは `policy` ではなく
`policy_mode` であり、findings のリストは `errors` / `warnings` ではなく
`blocking_findings` / `advisory_findings`（型付きの GateFindingV1）です。
モデルは自身の結果を相互検証します — `passed` のレポートは findings を 1 つも
持たなくてよく、`failed` のレポートは blocking finding を必ず持たねばならず、
`should_block` は `phase == "final"` かつ `policy_mode != "off"` かつ blocking
finding が 1 つ以上存在するのでない限り拒否されます。`metrics` は有限の数値
でなければならないため、ゼロ除算になる比率は `NaN` ではなく `0.0` / `1.0` と
して格納されます。

MCP ラッパーは `should_block`（strict ポリシー下の `phase: final` 時、または
ポリシーの `always_block_on` 集合に属する客観的虚偽の検出時にのみ設定される）
をパイプラインのハード失敗に変換し、finalize がスキップされます。ソース:
`ari-core/ari/pipeline/claim_gate/gate.py`。

## `evaluation/evidence_grounded_semantic_review.json`

`ari-skill-evaluator.evidence_grounded_semantic_review` が型付きの
`ari.semantic-review/v1` ドキュメント
（`ari-core/ari/schemas/semantic_review_v1.schema.json`）として書き込む、
非ブロッキングのエビデンス裏付けセマンティックレビュー。ハードゲートの
エビデンスに基づいて過剰主張 / 解釈の問題を検出し、`paper_refine` 向けの
`suggested_revisions` を出力します。

`status` は 3 つの結果を区別し、レビューがクリーンに完走したことを意味するのは
そのうち 1 つだけです: `ok`（実行して何も見つからなかった）、`revise`
（findings ないし revisions あり）、そして **`unavailable`** — 論文ファイルの
欠落、LLM エラー、応答に JSON オブジェクトが含まれなかった場合を含む
*あらゆる*失敗経路で使われる値です。`unavailable` を「問題なし」と読むのは
正反対であり、どの失敗だったかは併記される `note` が示します。パイプラインを
ブロックすることは決してありません: レビューは読み取ったハードゲートレポート
にダイジェストで束縛され（`hard_gate_report_digest`）、ツールは事後にその
ファイルを読み直してバイト列が変わっていれば例外を送出します。したがって
advisory なレビューがハードゲートの結果を変えることはできません。

出力ファイル名は `phase` を反映します: `initial` / `draft` はベースの
`evidence_grounded_semantic_review.json` を書き、それ以外の phase は独自の
サフィックスを付けます（`phase: post_refine` なら
`..._post_refine.json`）。サフィックス付きの実行は、`score_delta` /
`resolved_overclaim_count` を計算するためにベースファイルを `previous` として
読み戻します。

## `lineage_decisions.jsonl` (v0.7.0)

系統決定を記録する追記専用ログ。1 行に 1 つの JSON レコード。3 つの writer が
このファイルを共有し、`trigger` がそれらを区別します: `append_decision_log`
（`stagnation_rule` / `every_node` / `manual`）、`append_root_selection_log`
（`root_idea_selection`。`decision.action` は `root_swap` / `root_keep`）、
そして `ari_rqgm` の ProposalRouter（`proposal_router`。`decision` は
`event` / `generator` / `record_ids` を運ぶ）。停滞ルールの形式:

```json
{"ts": 1752143672.418, "ts_iso": "2026-07-10T10:34:32Z",
 "trigger": "stagnation_rule", "executed": true,
 "state": {"active_idea_index": 0, "budget_remaining": 2, "alternatives": []},
 "decision": {"action": "switch_to_idea", "target_idea_index": 3,
              "disable_generate_ideas": true, "rationale": "..."}}
```

決定値: `continue` / `switch_to_idea` / `fanout` / `terminate`。
ソース: `ari-core/ari/orchestrator/lineage_decision.py`。`decision` の値は
オブジェクトで、`LineageDecision.to_dict()` — すなわち `action` /
`target_idea_index` / `disable_generate_ideas` / `rationale` — です。
`state` は `_state_for_log` が組み立てる圧縮スナップショット
（`active_idea_title` / `active_idea_index` / `nodes_explored` /
`budget_remaining` / `best_axis_scores` / `recent_composite_scores` /
`alternatives` / `venue_constraints_present` / `ancestor_thread_present`）で、
長いコンテキストブロックは除去されています。トリガごとの詳細は任意の
`extra` オブジェクトが運びます。

`disable_generate_ideas` は**記録されるだけで不活性**です。
`switch_to_idea` / `fanout` のレコードにおいて、true 値に対して
`ari-core/ari/cli/lineage.py` が行うのは
`os.environ.setdefault("ARI_DISABLED_TOOLS_FOR_CHILD", "")` の呼び出し
だけ — しかも*親自身の*環境に対して、空文字を — です。
`ari-core/`・`ari-skill-*/`・`scripts/` のどこもこの変数を読み返さず、
`disabled_tools` は YAML からのみ設定されるため、子はランチャの
`os.environ.copy()` 経由でこの変数を受け継いだうえで無視します。
`continue` / `terminate` のレコードでは、このフィールドはそもそも
参照すらされません。

したがって子は常に `generate_ideas` を実行します。ランチャは子の
`idea.json` に継承されたエントリを `_pinned` 付きで書き込み、
`generate_ideas` はそのエントリを `ideas[0]` に保ったまま、新規生成
アイデアのうちタイトルが一致するものを落とし、残りをその後ろに追記
します。ピン留めは効いていますが、抑止は効いていません。

つまり `"disable_generate_ideas": true` の行は、judge が*要求した*こと
— 選ばれた代替案をそのまま実行せよ — の記録であって、子が実際に
行ったことの記録ではありません。決定論的な停滞ピボットはこの
フィールドを `true` にハードコードしているため、そこから生じる
ピボットは必ずこの値を持ちますが、そのいずれも子のアイデアプールが
凍結されたことを意味しません: その子の中で後続の lineage decision が
選ぶ代替案は、親のプールではなく子自身が新たにサンプリングしたもの
です。呼び出し箇所のコメントは意図（"child runs the inherited idea
verbatim, no resampling"）を述べているので、これは将来のために予約
されたフィールドではなく、配線が未完のまま残っているものです。

## `prompt_trace.jsonl` / `prompt_versions.json`

プロンプトの来歴です: 管理対象プロンプトの LLM 呼び出しごとに、どの
*テンプレート*が — そして呼び出し側でレンダリング済み文字列が得られた
場合はどの*レンダリング済みプロンプト*が — その呼び出しを生んだのかを
記録します。`prompt_trace.jsonl` が呼び出し単位の追記専用トレース、
`prompt_versions.json` がそのラン単位のロールアップです。どちらも
チェックポイント直下に書かれ、どちらも `PathManager.META_FILES` にある
ため、ノードの作業ディレクトリにコピーされることはありません;
`prompt_trace.jsonl` はさらに `_TRACE_FILES` に分類されています — これは
パス解決器が併せて理解するバケット化ランディレクトリレイアウトにおいて
`runs/<run_id>/traces/` の下に置かれるファイル群です。ソース:
`ari-core/ari/prompts/_provenance.py`; ロールアップの書き込みは
`ari.checkpoint.save_prompt_versions_json` に集約されます。

トレースは 1 行 1 JSON オブジェクトです。`prompt_name` と
`template_hash` が必須で常に計算可能なフィールドであり、それ以外は
すべて既定値を持つため、読み取り側を壊さずにレコード形状を拡張できます:

```json
{"timestamp": "2026-07-10T10:34:32Z", "prompt_name": "pipeline/keyword_librarian",
 "template_hash": "9f2c01ab34de", "rendered_prompt_hash": "34de9f2c01ab",
 "prompt_version": null, "prompt_registry_version": null,
 "model": "...", "node_id": "", "phase": "context_builder", "source": "core"}
```

ハッシュは `sha256(text)[:12]` — `FilesystemPromptLoader.load_versioned`
と同一の方式なので、テンプレート本文はここでもあちらでも、また異なる
マシン間でも同じ値になります。`timestamp` はメタデータで、ハッシュには
決して入りません。`rendered_prompt_hash` は呼び出し側がレンダリング済み
テキストを渡した場合にのみ入り、それ以外は `null` です; テンプレートを
読み込むだけで最終文字列をその場で組み立てない呼び出し箇所がいくつか
あるため、`null` は「未取得」であって「空のプロンプト」ではありません。

`prompt_version` / `prompt_registry_version` は**ほぼ常に `null` である
と観測されます**。これはプロンプトについての主張ではなく、呼び出し側の
凍結された性質です。これらを埋める writer はただ一つ、RQGM
PromptRegistry のスタンプ経路（`ari-core/ari/rqgm/registry.py`）で、
`prompt_version` に*レジストリのプロンプト ID*、
`prompt_registry_version` にレジストリバージョンを入れます。それ以外 —
エージェントループ、LLM 評価器、コンテキストビルダ、viz ウィザード
ツール、そして RQGM のガバナンス／プロンプト進化／提案の全呼び出し —
では両方とも `null` のままです。`null` は「未スタンプ」と読むべきで、
「バージョンの無いプロンプト」ではありません。`source` も同様に常に
`"core"` です: `record_prompt_use` がハードコードしており引数も持たない
ため、フィールドが予約している `"skill"` 値を出荷物は誰も出しません。

`prompt_versions.json` は `{prompt_name: {template_hash, prompt_version,
call_count}}` を初出順に並べたもので、`template_hash` と
`prompt_version` はその名前で*最初に*見たレコードから採られます — ラン
の途中でテンプレートが変わったプロンプトは最初のハッシュしか現れず、
真実は JSONL 側に残ります。BFTS ループがチェックポイントをフラッシュ
するたびに `build_prompt_versions_rollup` がトレースから再構築します
（スロットル付きの書き込み。終端のフラッシュは強制）。つまり導出物で
あって権威ではありません。このフラッシュが唯一の writer なので、BFTS
ループに入らないままプロンプト使用を記録したフェーズは、ロールアップの
無いトレースだけを残します。

どちらの writer も意図的にベストエフォートであり、成果物もそのように
読む必要があります。`record_prompt_use` はチェックポイントディレクトリ
が解決できないとき（ユニットテスト、起動前）は no-op になり、モジュール
ロックの下で追記し、**あらゆる**例外を握り潰します — 来歴の記録失敗が、
記録対象の LLM 呼び出しを壊すことは決してありません。ロールアップの
書き込みも同じ形で包まれています。したがってどちらかのファイルが無い
ことは「来歴が記録されていない」を意味するだけで、エラーではなく、
呼び出しが無かった証拠にもなりません。

## RQGM エポックガバナンスファイル（オプトイン `ari_rqgm` モード）

`ari.mode: ari_rqgm` **と** `rqgm.enabled: true` が一致するときにのみ
書かれます（[実行モード](../guides/execution_modes.md) 参照）。デフォルトの `simple_bfts`
チェックポイントにはすべて不在です; すべての読み取り側は不在を
「RQGM は一度も走っていない」として扱います。ソース:
`ari-core/ari/rqgm/store.py`; JSON Schema:
`ari-core/ari/schemas/{epoch_state,rqgm_registry,rqgm_transition_event,rqgm_defs}.schema.json`。

### `rqgm_transitions.jsonl`

エポック / レジストリのガバナンス状態の**真実源**。追記専用のハッシュ連鎖
JSONL で、1 行に自己完結したイベント 1 つ:

```json
{"schema_version": 2, "event_id": "evt_000042", "event_type": "prompt_status_change",
 "transaction_id": "transition_003_to_004",
 "payload": {"prompt_id": "reviewer_prompt_v4", "from_status": "shadow",
             "to_status": "probationary_active", "transition_id": "transition_003_to_004"},
 "event_hash": "baf0...64-hex-sha256...", "prev_event_hash": "91ac...64-hex-sha256...",
 "ts": 1751700000.0, "ts_iso": "2026-07-05T12:00:00Z"}
```

v2 の `event_hash` は、版、識別子、種類、取引識別子、正規化した内容、
直前ダイジェストを結合した完全 SHA-256 です。時刻は対象外のメタデータ
です。内容だけを 12 桁で結んだ旧版 v1 も読出せます。イベントタイプ:
`epoch_transaction_prepare`、`component_registered`、`prompt_registered`、
`component_status_change`、`prompt_status_change`、`epoch_close`、
`epoch_open`、`epoch_transaction_commit`、`emergency_quarantine`。
T16 の緊急隔離を含むレジストリのステータス変更は境界の
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

このリプレイ可能性は習慣ではなく契約です。`make_report`
（`ari-core/ari/rqgm/kernel_types.py`）は構築時に違反を
`(code, subject_ref, detail)` で整列させるため、同一入力は同一の
`kernel_report` 行に直列化されます。この性質は
`ari-core/tests/test_rqgm_kernel.py` が違反コードごとに固定しており、
各フィクスチャを別々のカーネルインスタンス上で 2 回駆動して正規化 JSON
を比較します。時計を読む検査はありません: どのカーネルモジュールも
`time` や `datetime` を import せず、エンベロープの `created_at` は
**存在**のみが検査され（`kernel_rules.ENVELOPE_FIELDS`）、その値が比較・
`detail` 文字列・ハッシュに入ることはありません。severity も呼び出し側が
選ぶことはなく、凍結された `kernel_rules.SEVERITY` マップで解決されます
— つまり判定の severity はコードだけの関数です。数値的な緩みは 1 つの
つまみだけ: 浮動小数点比較は `rqgm.kernel.float_tolerance`（既定 `1e-9`、
[設定](configuration.md) 参照）を通ります。そして「カーネルは LLM 判事
ではない」は主張ではなく強制されます — テストがすべての
`ari/rqgm/kernel*.py` と `transition_rules.py` を `litellm`、`openai`、
`anthropic`、`requests`、`httpx`、`aiohttp`、`socket` について grep し、
import として現れれば失敗します。対象ファイル集合そのものも厳密に
アサートされるため、新しい `kernel_*.py` がこのガードに加わらないまま
カーネルに加わることはできません。

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

`audit_epoch` は、コンポーネント / プロンプトレジストリ、フロンティア、
`tree.json`、ノード状態に対して **読み取り専用**です。レジストリには
読み取りアクセサ（`active_set` / `get`）経由でしか触れず、9 ステップの
パイプラインはレコードを永続化せず *返す* だけで、追記はファサードが
後から行います。推奨の適用も行いません: `governance_report` に基づいて
動くのは RegistryTransitionEngine（Task 09）だけの仕事であり、レポート
単体では状態は何も変わりません。書き込み集合は閉じています:

- `rqgm_audit.jsonl` — 常に: 上記のガバナンスレコードと最終的な
  `governance_report`。
- `prompt_trace.jsonl` — 共有のプロンプトレンダリング経路が出す通常の
  プロヴェナンスレコードで、対象はガバナンスの LLM 呼び出しのみ。これらの
  呼び出しが `prompt_versions.json` に届くのは間接的で、次に BFTS の
  チェックポイントフラッシュがトレースからロールアップを再構築したとき
  です（上の「`prompt_trace.jsonl` / `prompt_versions.json`」を参照）;
  `audit_epoch` 自身がロールアップを書くことはありません。決定論的な監査
  （LLM シーム未配線）はガバナンスプロンプトを一切レンダリングせず、
  ここにも何も追記しません。
- `rqgm_adversarial_cases.jsonl` と、そこから派生する
  `rqgm/adversarial_replay_pool.json` — ステップ 7 のリプレイプール
  更新で、プールが渡された場合のみ。承認 / 支持されたケースは真実で
  ある JSONL に **追記**され、そのうえでスナップショットがメモリ上の
  状態から書き直されます。つまりスナップショットは履歴のインプレース
  編集ではなく射影です: 上限付きの追い出しはケースの `status` を
  `evicted` にするだけで、JSONL は admit されたすべてのケース行を
  保持します。
- `rqgm_governance_cache.jsonl` — 候補評価の書き戻しで、Task 12 の
  ガバナンスキャッシュが配線されている場合のみ（後述の
  `rqgm_governance_cache.jsonl` を参照）。

`rqgm_audit.jsonl` は `PathManager.META_FILES`（継承やチェックポイント
コピーの経路がノード work_dir に持ち込まない）と、node_report の
`files_changed` ブロックリスト
（`ari-core/ari/orchestrator/node_report/builder.py`）の両方に登録されて
います。したがってガバナンスの書き込みが、ノードが生成したファイル変更
として表に出ることはありません。2 つの回帰テスト
（`ari-core/tests/test_rqgm_governance.py`）がこの線を守っています:
LLM もリプレイプールも無い `audit_epoch` は、チェックポイント
ディレクトリに登録済み監査ログ *だけ* を残し、既定の `simple_bfts` 実行は
`rqgm*` ファイルも `constitution.yaml` も一切書きません。

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
  invalidated/recompute/abandoned のノード id に加え、utility-policy
  退役時に保存済みの生の軸スコアを再重み付けした
  `policy_rescored_node_ids` を列挙します。消去は
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
  utility-policy 退役は別の経路です。同じ修復イベントが各ノードに保存
  された `_axis_scores` を `new_utility_policy` の下で再合成し、その
  ノードを `policy_rescored_node_ids` に列挙します。生の軸が利用できない
  ノードは fail-closed で無効化されます。

### `constitution.yaml`

憲法層の人間可読な声明で、`ari run` 開始時に同梱の
`ari-core/config/constitution.yaml` から一度だけコピーされます
（上書きされることはなく、`ari_rqgm` のみ; `simple_bfts` チェックポイント
には不在）。権威ある規則は凍結コード（`ari/rqgm/kernel_rules.py` +
`ari/rqgm/transition_rules.py`）であり、`constitution_hash` —
`sha256(canonical_json(<all rule tables>))[:12]` — でピン留めされます。
このハッシュは `meta.json` の任意の `constitution_hash` キーとしても
追加的に記録されます。

したがってチェックポイント上のコピーは **来歴マーカーであって制御面では
ありません**: これを編集しても挙動は何も変わりません。ARI のどのコードも
読み戻さず、このパスに触れるのは `ari.rqgm.state.copy_constitution_if_missing`
だけだからです（呼び出しはモードゲート下の `ari/cli/run.py` から。
[内部境界](internal_boundaries.md) の「RQGM モード境界 (`ari.rqgm`)」を参照）。
これは見落としではなく意図です: チェックポイントディレクトリはフラットで
どのスキルからも書き込めるため、そこに規則ファイルを置けば進化／改竄の
経路になってしまいます。だから規則テーブルはコード側に残しています。
このコピーは `PathManager.META_FILES` に登録されており、ノードの作業
ディレクトリには決して届きません。コピー処理は双方向にベストエフォート
です — 同梱 `constitution.yaml` を持たないパッケージングでは何もコピー
されず何も報告されません — したがってファイルが無いこと自体は
その実行が `simple_bfts` だった証拠にはなりません。

### `epoch_state.json`

現在開いている（または最後に閉じた）エポックの、導出された全体書き換え
スナップショット: 凍結されたアクティブコンポーネント集合、アクティブ
プロンプトハッシュ、utility policy、`registry_version`、決定論的な
`policy_settings` / `policy_fingerprint`、`execution_identity` /
`execution_fingerprint` を持ち、`epoch_fingerprint` が両方を合成する。
`created_at` は対象外で、外部版が不明なら `unresolved` と記録する。
使い捨てです — ロード時にイベントログのリプレイと突き合わせて
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

このロールアップは ARI が**他パッケージ向けに公開する**面でもあるため、
消費側の規則が 2 つあります。第一に `invalid_frontier_node_ids` は
ピン留めされたパッケージ間契約です — ari-core が書き、memory スキルが
読み、`ari-skill-memory/tests/test_erasure_annotation.py` が ari-core 側の
writer を grep するので、どちらかを改名すると消去認識が黙って死ぬのでは
なくテストが落ちます。第二に、そのパッケージ間リーダ
（`ari-skill-memory/src/ari_skill_memory/erasure.py`）は**縮退する**ことで
前方互換を保ちます: `SUPPORTED_SCHEMA_VERSION = 1` をピン留めしており、
`schema_version` が理解できる整数でないファイル — サポート版より大きい、
あるいは文字列 / 浮動小数 / 真偽値 — は、誤った消去ラベルを付ける危険を
冒すより「何も stale でない」として読まれます。これは不在・読み取り不能・
不正形式のファイルに対して返すのと同じ判定です。`schema_version` キーが
無い場合はサポート版とみなされます。

この非対称性は形式ではなくリーダ側の性質である点に注意してください:
ari-core 自身の `view_from_payload`（`ari-core/ari/rqgm/erasure_state.py`）
は `schema_version` を一切見ません — writer の不在耐性のある双子です —
そして JSON Schema は `schema_version` を `const: 1` と宣言しています。
縮退のはしごを実装しているのはパッケージ間リーダだけです。

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

## `.ari-manuscript/`（オプトインの Manuscript Complete）

`manuscript.mode: "off"` のときこの名前空間は存在しません。audit / enforce の
attempt は、不変でダイジェストに束縛された JSON ドキュメントを使います:

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
│   ├── authoring_binding.json        # authoring-ready 判定時、または audit モード
│   └── publication_decision.json     # 検証／ファイナライズ後
├── segments/*.json
├── repair-transactions/*.json
├── auto-rounds/*.json
└── attempts/<attempt-id>/publication_lock.json
                                        # 鮮度が確認された publishable 判定の後のみ
```

attempt の同一性はソーススナップショットとプロファイルのダイジェストから
導出されます。ソースが変われば、古い attempt を書き換えるのではなく新しい
attempt が生まれます。スキーマは `ari-core/ari/schemas/` 配下に
`manuscript_*_v1.schema.json` / `research_repair_*_v1.schema.json` という名前で
置かれています。系譜とステータスの完全な規則は
[Manuscript Complete 契約リファレンス](manuscript_complete_contracts.md)に
あります。

## `settings.json`

viz ダッシュボードが使用するチェックポイントごとの設定で、置き場所は
`PathManager.project_settings_path(checkpoint)` です。ダッシュボードが
`/api/settings` に POST する**フラットな**オブジェクトをそのまま書いたもので、
入れ子はありません:

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

`GET /api/settings` は `{**組み込みデフォルト, **保存値}` を返し、未知の保存
キーもそのまま通過するため、このファイルは完全なドキュメントではなく部分的な
上書きです。アクティブなチェックポイントが無い状態での保存は拒否されます
（HTTP 400）— 設定はプロジェクトスコープのみで、グローバルな
`~/.ari/settings.json` へのフォールバックはありません。レスポンス全体の
スキーマは `ari-core/ari/schemas/viz_settings.schema.json` です。

API キーはここには**決して保存されません** — `POST /api/settings` は書き込み前に
`api_key` / `llm_api_key` をペイロードから取り除き、プロバイダ用の変数
（`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GOOGLE_API_KEY`）を `.env` に
upsert します（所有者のみ 0600、アトミック書き込み）。起動時は `.env` を
チェックポイント → ARI ルート → ari-core → ホームの順に読み、最初に設定された
ものが勝ち、シェルの export がそれら全てに優先します。

publish / レジストリの設定は現時点ではここに置かれません: `ari ear publish` は
`$ARI_PUBLISH_SETTINGS` を、無ければ非推奨の `~/.ari/publish.yaml`（参照時に
警告します）を解決します。`{checkpoint}/settings.json` 内の `publish`
セクションは v1.0 での置き換えとして予告されているものであり、まだコードが
読む経路ではありません。

## `workflow.yaml`

`ari-core/ari/pipeline/yaml_loader.py` が参照するパイプライン定義。
ステージ一覧はトップレベルのキー **`pipeline:`** の下にあり（BFTS フェーズの
表示専用行は別の `bfts_pipeline:` リストです）、各エントリのキーは `name:` では
なく **`stage:`**、そして `inputs` / `outputs` はリストではなくマッピングです:

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

`load_pipeline` は `enabled != false` のステージだけを返し、
`load_disabled_stage_names` がその補集合を返すため、意図的に無効化された
ステージを指す `depends_on` がその消費側まで連鎖的にスキップさせることは
ありません。一部の行は表示専用で `tool: ''` を持ちます（たとえば evaluation は
ari-core のインプロセス BFTS 評価器が担っており、MCP ツールではありません）。

バンドル済みデフォルトは `ari-core/config/workflow.yaml` にあります
（`package_config_root()` が返すパッケージ設定ルート — `ari/` の兄弟である
`ari-core/config/`）。レガシーなファイル名 `pipeline.yaml` も引き続き
受け付けますが、同じディレクトリに `workflow.yaml` が無い場合に限ります。

## `memory_store.jsonl` / `memory_backup.v1.json.gz`

`ARI_CHECKPOINT_DIR` 配下に書き込まれるメモリバックエンドの成果物:

| ファイル | バックエンド | 備考 |
|---|---|---|
| `memory_store.jsonl` | `file` | レガシー v0.5 形式。`.jsonl` という名前に反して、行区切りではなく `add()` のたびに全体を書き直す**単一の JSON 配列**です — `FileMemoryClient` はファイル全体を `json.loads` します。エントリは `{content, metadata, ts}` |
| `memory_backup.v1.json.gz` | `letta` | ポータブルなスナップショット。gzip 圧縮した正準 JSON（キーソート済み、空白なし）1 ドキュメントであり、JSONL では**ありません**。終了時の `atexit` フック、および明示的な `ari memory backup` / `ari memory migrate` コマンドが書きます。ステージ境界のトリガはありません |
| `memory_access.jsonl` | any | 書き込み / 読み込みの追記専用テレメトリ |

バックアップドキュメント
（`ari-core/ari/schemas/memory_backup_v1.schema.json`）:
`{schema_version, records[], react_entries[], core_context, record_digests[],
record_order[], backup_digest}`。`records` は `record_digest` でソートされる
ためファイルはバイト安定であり、`record_order` は読み取った順序を保存します。
実行時エントリがバージョン付きの `memory_record` を持たないレコードは、
黙って格下げされるのではなくバックアップを中止させます。

スナップショットレコードの形式（`MemoryRecordV1`）:

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

ReAct トレースは `kind` ではなく**別のリスト**です: `react_entries[]` が
`MemoryReactEntryV1` レコード（`{content, metadata, ts, entry_digest}`）を、
ダイジェスト順に保持します。

## EAR バンドル (v0.7.0)

`{checkpoint}/ear/` が候補セット、`{checkpoint}/ear_published/` がバックエンドに
公開するキュレート済みサブセットです。信頼のアンカーは以下の構造です:

```
{checkpoint}/
├── ear_published/
│   ├── manifest.lock     # canonical JSON, per-file sha256 + bundle_sha256
│   └── ...               # curated artefacts
└── publish_record.json   # backend, ref, bundle_sha256, visibility, timestamp
```

`publish_record.json` は `ear_published/` の中ではなく**チェックポイント直下**に
あり、`ari ear publish` はキュレーション後にのみこれを書きます。フィールドは
`backend` / `ref` / `bundle_sha256` / `visibility` / `timestamp` / `dry_run` /
`extra` です。最初の publish は必ず `visibility: "staged"` であり、`public` へ
移すのは `ari ear promote` です。

キュレーションはインプレースではなく復旧可能です: 一時ディレクトリを作って
そこに `manifest.lock` を書き、2 回の `os.replace` で `ear_published/` と
入れ替え、最後のリネームに失敗した場合は以前のバンドルを復元します。

`manifest.lock` は `ari.ear-manifest/v2` ドキュメントです —
`{schema_version, version, checkpoint_id, created_at, publish{...}, files[],
excluded_count, bundle_sha256, policy_digest, evidence_index_digest,
evidence[], admission_status, lock_digest}`。`ari-core/ari/schemas/` に
対応する JSON Schema は**ありません**。そこにある `publish.schema.json` が
記述しているのは、キュレーション*ポリシー*である `publish.yaml`
（`include` / `exclude` / `max_file_mb` / `visibility` / `required` /
`auto_promote` / `license` / `backend`）であり、別のファイルです。
`bundle_sha256` は公開された論文に焼き込まれた `\codedigest{...}` マクロと
一致しなければなりません。

## 関連ドキュメント

- `docs/concepts/architecture.md`（チェックポイントディレクトリレイアウト）— 同じファイル
  のナラティブビュー。
- `ari-core/ari/schemas/` — `node_report`、型付きの measurement /
  science-data / gate-report / metric-gate 契約、RQGM ガバナンスレコード、
  および Manuscript Complete ドキュメントの正式な JSON スキーマ。
  （そこにある `publish.schema.json` は `publish.yaml` のキュレーション
  ポリシーであり、EAR の `manifest.lock` ではありません。）
- `ari-core/ari/pipeline/yaml_loader.py` — workflow.yaml パーサ。
- `docs/guides/experiment_file.md` — `experiment.md` の詳細ガイド。
