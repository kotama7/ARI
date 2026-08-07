---
sources:
  - path: ari-skill-benchmark/mcp.json
    role: config
  - path: ari-skill-benchmark/src/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-evaluator/mcp.json
    role: config
  - path: ari-skill-evaluator/src/server.py
    role: implementation
  - path: ari-skill-harness/mcp.json
    role: config
  - path: ari-skill-harness/src/server.py
    role: implementation
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-idea/mcp.json
    role: config
  - path: ari-skill-idea/src/server.py
    role: implementation
  - path: ari-skill-knowledge/mcp.json
    role: config
  - path: ari-skill-knowledge/src/server.py
    role: implementation
  - path: ari-skill-memory/mcp.json
    role: config
  - path: ari-skill-memory/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/mcp.json
    role: config
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-paper/mcp.json
    role: config
  - path: ari-skill-paper/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-plot/mcp.json
    role: config
  - path: ari-skill-plot/src/server.py
    role: implementation
  - path: ari-skill-replicate/mcp.json
    role: config
  - path: ari-skill-replicate/src/server.py
    role: implementation
  - path: ari-skill-tool-registry/mcp.json
    role: config
  - path: ari-skill-tool-registry/src/server.py
    role: implementation
  - path: ari-skill-transform/mcp.json
    role: config
  - path: ari-skill-transform/src/server.py
    role: implementation
  - path: ari-skill-vlm/mcp.json
    role: config
  - path: ari-skill-vlm/src/server.py
    role: implementation
  - path: ari-skill-web/mcp.json
    role: config
  - path: ari-skill-web/src/server.py
    role: implementation
  - path: ari-core/tests/fixtures/contracts/mcp_tools.json
    role: test
last_verified: 2026-07-30
---

# MCP ツールリファレンス

ARI には `ari-skill-*` パッケージごとに 1 つ、17 の MCP サーバが同梱されています。
このうち 13 は `ari-core/config/workflow.yaml` の `skills:` が既定で登録し、
`ari-skill-orchestrator` は外部クライアント向けに別プロセスとして起動します。
残る `ari-skill-knowledge` / `ari-skill-harness` は admission 済みカタログに対する
読み取り系サーフェス、`ari-skill-tool-registry` は大規模な MCP collection の
ブローカで、いずれも既定の `skills:` には載りません（tool-registry の 5 操作は
本ページ末尾に、カタログ identity と provider adapter は
[tool_registry.md](tool_registry.md) にあります）。

このページはエージェントが呼び出せるすべてのツールのフラットなカタログです。
各スキルの詳細は個別の `README.md` を参照してください。セクション
[skills.md](skills.md) では責務ごとにグループ分けされています。

`mcp.json`（各スキルの `pyproject.toml` の隣に配置）はツール*名前*を運び、
`skill.yaml` から `scripts/sync_skill_metadata.py --write` が生成します。
`@mcp.tool()` で装飾された関数（または `@server.list_tools()` のエントリ）が
引数と戻り値の形式を定義します。3 者がずれると
`scripts/check_skill_manifests.py` が失敗し、スキルごとのツール名一覧は
`ari-core/tests/fixtures/contracts/mcp_tools.json` にスナップショットとして
固定されています。

"LLM" 列は **P2 例外** のツールを示します — LLM を呼び出すため
バイト単位での決定論性がありません。

## ari-skill-benchmark — 統計 + run 比較（決定論的）

3 ツールとも引数は `request` ただ 1 つで、`ari.public.analysis` の型付き
リクエスト（`AnalysisRequestV1` / `StatisticalTestRequestV1` /
`RunComparisonRequestV1`）を包みます。全 metric が `unit` の明示を要求されます。

| ツール | 用途 | LLM |
|---|---|:---:|
| `analyze_results` | unit 付きサンプル集合の要約統計（信頼区間、正規性診断、欠損数、解決済み input digest） | ✗ |
| `statistical_test` | 事前宣言した比較族の検定（`welch_t` / `student_t` / `paired_t` / `mann_whitney` / `wilcoxon` / `auto`）。効果量と補正済み p 値を返し、2 件以上の比較では `bonferroni` / `holm` / `benjamini_hochberg` の明示が必須 | ✗ |
| `compare_runs` | スカラー run のランキングと環境 / provenance の互換性報告。`require_compatible_environment=true`（既定）は環境の異なる run の順位付けを拒否し、同一 backend/environment を独立 replicate とは推論せず共有 substrate として記録 | ✗ |

旧 `plot` は v0.2 で削除されました。作図は `plot-skill` の `render_figure` が
source / data / spec / environment / PNG・PDF digest を持つマニフェストとして
生成します（[決定論的解析契約](analysis_contract.md) を参照）。

## ari-skill-coding — コードの作成 + 実行

`mcp.json` は `skill.yaml` から生成されたツール*名*を運び、完全なスキーマは
`src/server.py` の `@server.list_tools()` から提供されます。

| ツール | 用途 | LLM |
|---|---|:---:|
| `write_code` | ノードの work_dir にファイルを書き込む | ✗ |
| `edit_code` | 既存ファイル内の厳密一致した断片だけを置換し、残りには触れない。ファイルが既にある場合は `write_code` より優先します：`old_string` は `replace_all` を立てない限り**ちょうど 1 回**しか一致してはならず、曖昧な編集は黙って別の場所を書き換えるのではなく失敗します | ✗ |
| `run_code` | タイムアウト + キャプチャ付きでスクリプトを実行 | ✗ |
| `run_bash` | アドホックな bash コマンド | ✗ |
| `describe_environment` | このクラスタの環境カタログ（アーキテクチャ、CPU、GPU、PATH 上のコンパイラ、`module avail` の生カタログ、設定済みツールチェイン環境変数の**名前**）を返す。ログインノードではログインノード自身に加えて設定された各計算パーティションを、計算ノードではそのノードのみを報告。引数なし | ✗ |
| `emit_results` | 評価器向けに `metrics` + `has_real_data` を出力（オプションの `provenance` 引数 → `_provenance` キーとしてそのまま書き込まれ、各値がどのように測定されたかをタグ付けし、claim-evidence ゲートで使用）。レスポンスの `contract_warnings` には、出力したキーが要求エビデンス名と字句的に類似する場合、提案のみの「POSSIBLE name matches」ヒントが含まれることがあります — あくまで助言であり、自動バインドは行われず、ゲートがこれを参照することもありません | ✗ |
| `read_file` | エージェントが以前に書いたファイルを読み込む | ✗ |

## ari-skill-evaluator — メトリクス契約 + 主張ゲート

| ツール | 用途 | LLM |
|---|---|:---:|
| `make_metric_spec` | 不変の `ResearchContractV1` または人間が admit した提案から MetricSpec を決定論的に materialize；実行レベルの `metric_contract` も出力 → `{checkpoint}/metric_contract.json`。mint-once: claims を含む契約がすでに永続化されている場合、呼び出しは再抽出せず、その契約を `contract_frozen: true` 付きでそのまま返します（scoring guide などノードごとの spec フィールドは呼び出しごとに計算）。契約が 1 つも無い場合は LLM に落ちるのではなく `admission_status: "human-review-required"` と `proposal_tool: "propose_metric_contract"` を返します | ✗ |
| `propose_metric_contract` | 明示的に要求されたときだけ走る LLM 提案ステップ。出力は `MetricContractProposalV1`（`requires_human_review: true`）で `{checkpoint}/metric_contract_proposal.json` に永続化され、それ自体では決して admit されません。アイデアが所有する型付き契約がある場合は拒否されます | ✓ |
| `claim_evidence_hard_gate` | 決定論的な主張/証拠ハードゲート（実行データの忠実性）；strict モードでは final フェーズで finalize をブロック | ✗ |
| `evidence_grounded_semantic_review` | 非ブロッキングの証拠に基づくセマンティック査読；`paper_refine` 向けに `suggested_revisions` を出力 | ✓ |

## ari-skill-hpc — SLURM + Singularity

`mcp.json` はツール*名*のみを記載し、`skill.yaml` から生成されます。完全な
スキーマは `ari_skill_hpc/server.py` の `@server.list_tools()` から提供されます。

| ツール | 用途 | LLM |
|---|---|:---:|
| `job_submit` | 不変の `JobRequestV1` を投入し、冪等な `JobHandleV1` を即座に返す；コマンドは argv 配列で、ログインノードのシェルは一切使わない | ✗ |
| `container_submit` | 同じライフサイクル。ただしリクエストに digest 固定された Apptainer/Singularity のコンテナ宣言が必須 | ✗ |
| `job_status` | ARI ハンドルまたは生の SLURM ID に対する provider 非依存の `JobStatusV1`（squeue + sacct 検索） | ✗ |
| `job_result` | 終端状態の `JobResultV1` を収集し、宣言された入力 / 出力 / ログを再ハッシュ | ✗ |
| `job_logs` | ARI ジョブハンドルの stdout / stderr を境界付き・digest 付きで返す | ✗ |
| `job_cancel` | ARI または SLURM のジョブのキャンセルを要求 | ✗ |
| `slurm_submit` | コアエージェントのバッチスクリプト用互換ブリッジ：パーティション / 時間 / ノード数 / タスク数 / CPU 数 / modules と明示的な `launcher` を指定して sbatch。新しいプログラム的呼び出しは `job_submit` を使う | ✗ |
| `probe_platform_capabilities` | **計算パーティション上**でツールの有無（`command -v`）を調べ、`{checkpoint}/platform_capabilities.json` にキャッシュ；ベストエフォート（失敗時は skipped を返し何も書かない） | ✗ |
| `counter_support` | このノードがハードウェアカウンタを許可するかを、プロファイラのバイナリを探すのではなく実際に 1 つ開いて確かめて報告 | ✗ |
| `measure_counters` | 既存プロセスの審査済みハードウェアイベントを境界付きウィンドウで計数；プロセスを生成せず、何も書かない | ✗ |

`launcher` はスクリプトを allocation 内でどう起動するかを表し、`tasks > 1` から
推論するのではなく明示的に宣言します。`auto`（デフォルト）は 1 ノード 1 タスクの
ペイロードを `srun --ntasks=1` で束縛し、それより大きい形状はそのまま起動して
並列起動をスクリプト側に委ねます。`srun` は宣言された
`nodes` / `tasks` / `cpus_per_task` でスクリプト自体を起動し、MPI / SPMD
バイナリはこれを必要とします。`none` は決してラップしません。起動モードは
リクエスト digest の一部です。引数の全一覧は
[skills.md](skills.md#ari-skill-hpc) を参照してください。

`measure_counters` は `context_requirement: node` を宣言しているため、その入力
スキーマは `ari_context` オブジェクトプロパティを宣言します。transport は
context 要件を持つツールに対してこの名前で認可済み call context を注入するので、
`additionalProperties: false` でありながらこれを宣言しないスキーマは、認可された
呼び出しをすべて拒否します。proxy は `tools/list` からこのプロパティを取り除く
ため、エージェントが渡す引数になることはありません。

## ari-skill-idea — 文献調査 + アイデア生成

| ツール | 用途 | LLM |
|---|---|:---:|
| `survey` | 固定した **1 つ** の provider（`semantic-scholar` 既定 / `virsci-snapshot`）に対する先行研究調査。`record` / `live` はバックエンドを切り替えず、`replay` はネットワークに一切アクセスせず、未対応の provider は代替されずに拒否される | ✗ |
| `generate_ideas` | LLM が調査 + コンテキストからランク付きアイデア候補を生成 | ✓ |

この 2 つがこのスキルの唯一の登録ツールです —
`_load_virsci_snapshot_papers` は `survey` が直接呼ぶただのヘルパーであり
エージェントからは決して見えません。`ari-skill-idea/tests/test_server.py` が
`mcp.list_tools()` 経由でこの両方をピン留めしています。provider 間の
フォールバックはありません: `virsci-snapshot` の survey はコーパスが無ければ
`FileNotFoundError` を、Semantic Scholar の survey は HTTP エラーをそのまま
raise します。障害時に得られるのは黙って別物になったコーパスではなく拒否です。
両者は RQGM の `VirSciAdapter` の背後にある MCP 面でも
あります: オプトインの `ari_rqgm` モードで
`proposal_router.generators.virsci.enabled: true` のとき、コア側の
ProposalRouter はアイデア生成イベントを、エポックごとの呼び出し予算の下で
`survey` + `generate_ideas` へルーティングします —
[VirSci 統合](../guides/virsci_integration.md)を参照。

`generate_ideas` は単一の安定した出力契約の背後に 2 つのエンジンを持ちます。
デフォルトは軽量な再実装ディスカッションループです。オプトインの実 VirSci
vendor-wrap エンジン（`ARI_IDEA_VIRSCI_REAL=1`）は、ライブ Semantic Scholar
スナップショット上で VirSci 本来のマルチエージェント機構を実行し、依存関係の
欠落 / 実行時エラーが発生した場合は再実装ループにデグレードします。`idea.json`
契約はどちらの経路でも同一で、辿った経路は `virsci_integration_status`
（`real_wrap` または `reimpl: ...`）で報告されます。

## ari-skill-memory — 祖先スコープのノードメモリ

このスキルは `src/server.py` の FastMCP `@mcp.tool()` デコレータを使用します。
`mcp.json` は同じ 13 ツールを名前で列挙し、`scripts/check_skill_manifests.py`
が両者の一致を検査します。

| ツール | 用途 | LLM |
|---|---|:---:|
| `add_memory` | 現在のノードのメモリにエントリを追加 | ✗ |
| `search_memory` | 現在のノード + 祖先をまたいだ埋め込みランク検索 | ✗（サーバサイド埋め込み） |
| `get_node_memory` | 現在のノードのすべてのエントリ | ✗ |
| `get_experiment_context` | Letta コアメモリから安定した実験レベルの事実を取得 | ✗ |
| `add_experiment_result` | 型付き experiment_result を記録（CoW：自ノードのみ） | ✗ |
| `add_failure_case` | 型付き failure_case を記録（CoW：自ノードのみ） | ✗ |
| `add_procedure_memory` | 再利用可能な手順を記録（CoW：自ノードのみ） | ✗ |
| `add_reflection` | リフレクションを記録（CoW：自ノードのみ；論文の主張には使用不可） | ✗ |
| `add_reproducibility_event` | 追記専用の再現性ステータスイベントを追加（CoW：自ノードのみ） | ✗ |
| `search_research_memory` | 種類 / 成果物の有無でフィルタした祖先スコープの型付き検索 | ✗ |
| `get_verified_context` | 論文 / 図の利用向けの成果物に裏付けられた再現性対応コンテキスト | ✗ |
| `audit_memory` | 記録された来歴（sha256）をチェックポイントのディスク上と照合検証 | ✗ |
| `consolidate_node_memory` | ノード終了時に node_report から型付きメモリを導出 + 書き込み（CoW：自ノード） | ✗ |

このスキルは設計ドキュメントで「LLM 呼び出しなし」と明示しています —
`ari-skill-memory/README.md` を参照してください。エントリを削除するツールは
ありません。ARI の governance がノードを論理的に消去した場合も、記録は残った
まま `erased` / `erasure_event_id` / `erasure_note` のラベルが付いて返ります
（黙って落とされることはありません）。

## ari-skill-orchestrator — 再帰的 ARI ランナー

12 ツールすべてがエラーを例外ではなく `{"error": {"code", "message"}}` の
封筒で返し、`code` は `invalid_request` / `forbidden` / `not_found` /
`idempotency_conflict` / `quota_exceeded` / `artifact_policy` /
`authentication_failed` / `orchestrator_error` / `internal_error` の
いずれかです。契約の詳細は
[Orchestrator control plane](orchestrator.md) を参照してください。

| ツール | 用途 | LLM |
|---|---|:---:|
| `run_experiment` | quota で拘束された ARI 実行を冪等に投入し、永続ハンドルを返す（`idempotency_key` 必須） | ✗ |
| `get_status` | 実行の永続 state と上限付きの進捗 | ✗ |
| `get_result` | 終端メタデータと digest でアドレスされた成果物 | ✗ |
| `stop_experiment` | 実行をキャンセルし、終了を伝播して 1 つの終端状態に確定 | ✗ |
| `list_runs` | 認証された principal が所有する実行のみを列挙（admin は全件） | ✗ |
| `list_children` | 指定した親実行の、認可された直接の子を列挙 | ✗ |
| `list_artifacts` | allowlist 済み・digest 検証済みの成果物を、パスを晒さずに列挙 | ✗ |
| `read_artifact` | admit された成果物を SHA-256 identity で境界付きで読む | ✗ |
| `get_paper` | 実行の論文成果物の参照 | ✗ |
| `get_ear` | 検証済み EAR と証拠成果物の参照 | ✗ |
| `list_skills` | run に紐づく `SKILLS.lock` のサニタイズ済みビュー | ✗ |
| `get_workflow` | ロックされた phase / tool メンバーシップ（生の workflow や秘密設定は返さない） | ✗ |

## ari-skill-paper — LaTeX 論文執筆

| ツール | 用途 | LLM |
|---|---|:---:|
| `list_venues` | 利用可能な LaTeX テンプレート（ACM / NeurIPS / SC / ICPP / ISC / arXiv） | ✗ |
| `get_template` | venue のテンプレートを取得 | ✗ |
| `compile_paper` | LaTeX プロジェクトを PDF にコンパイルし、`.ari-paper/compile/final.json` に記録を残す | ✗ |
| `check_format` | venue のフォーマット要件（ページ数など）に対する PDF 検証。ページ数が判定不能な場合も `ok: false` として記録し、未検証を合格と読ませない | ✗ |
| `write_paper_iterative` | 論文全体の執筆 / 査読 / 修正ループをエンドツーエンドで駆動。セクション単位のツールは存在せず、テンプレートの `FILL_*` ブロックを 1 回の LLM 呼び出しで埋める | ✓ |
| `finalize_paper_build` | 論文の証拠・査読・コンパイル記録・claim リンク・最終成果物を 1 つの `PaperBuildV1` に固定。`finalized` にならなければ blocking 理由を添えて例外を送出 | ✗ |
| `review_compiled_paper` | コンパイル済み PDF に対する最終パス査読（図は VLM に委譲） | ✓ |
| `link_paper_claims` | `% CLAIM:Cx:NCx` アンカーを science_data の主張と照合し、`paper_claim_links` を構築（決定論的） | ✗ |
| `paper_refine` | `% CLAIM:Cx:NCx` アンカーを保持しつつ提案された修正を適用（決定論的置換 + 境界付き LLM の検索/置換） | ✓ |
| `list_rubrics` | 利用可能な査読ルーブリック | ✗ |
| `inject_code_availability` | v0.7.0 — 論文に `\codedigest{...}` ブロックを追記 | ✗ |
| `merge_reviews` | v0.7.0 — ルーブリック査読 + VLM 査読の JSON を統合 | ✗ |

## ari-skill-paper-re — PaperBench 再現性 (v0.7.0)

| ツール | 用途 | LLM |
|---|---|:---:|
| `fetch_code_bundle` | ref + sha256 でコードバンドルを取得して検証 | ✗ |
| `build_reproduce_sh` | Stage 1 — vendor BasicAgent / IterativeAgent ロールアウトが `reproduce.sh` を書く | ✓ |
| `run_reproduce` | Stage 2 — `local` / `docker` / `apptainer` / `singularity` / `slurm` サンドボックスで `reproduce.sh` を実行 | ✗ |
| `grade_with_simplejudge` | Stage 3 — LLM がルーブリックの葉に対して実行済みサブミッションをグレーディング | ✓ |

### v0.8.0 新フィールド（Stage 1）

| ツール | 新しい引数 |
|---|---|
| `build_reproduce_sh` | `container_image`（レガシーの `apptainer_image` を置き換え。旧名はシグネチャから削除済み） |

### v0.8.0 新フィールド（Stage 2）

| ツール | 新しい引数 |
|---|---|
| `run_reproduce` | `container_image`（docker / apptainer / singularity サンドボックスで有効；エイリアス `pb-env` / `pb-reproducer` は `scripts/build_pb_images.sh` でビルドされた vendor の `image:latest` タグに解決） |

フェイルラウド前提条件: docker デーモン / apptainer バイナリ /
sbatch / パーティションが欠落している場合、ローカル CPU への黙った
フォールバックではなく `RuntimeError` を発生させます。レガシーフォールバックに
戻すには `ARI_PHASE1_ALLOW_FALLBACK=1`、GRES フラグの黙った削除に戻すには
`ARI_SLURM_ALLOW_NO_GRES=1` を設定してください。
[environment_variables.md](environment_variables.md#paperbench-reproduction-phase-stage-2) を参照。
型付き（`gpu_type` / `--gres=gpu:TYPE:N`）と型なし
（`--gpus-per-task`）の GPU リクエストの混在は自動的に型付き形式に
正規化されます — SLURM 24.05 は混在形式を拒否します。

### v0.8.0 新フィールド（Stage 3）

| ツール | 新しい引数 |
|---|---|
| `grade_with_simplejudge` | `code_only`（ルーブリックを Code Development 葉のみに限定。vendor の `paperbench/grade.py:109-112` を踏襲。`reproduce.log` が存在しない場合に自動有効化され、Stage 1 のみの実行が系統的にゼロにならないようにする） |

3 つのステージすべてを単一の呼び出し語彙でチェーンするインプロセス Python
サーフェスについては、
[`api_paperbench.md` § Bridge contract](api_paperbench.md#bridge-contract-in-process-python-surface)
を参照してください。

## ari-skill-plot — 図生成

| ツール | 用途 | LLM |
|---|---|:---:|
| `render_figure` | 正準の `FigureSpecV1` を 1 枚レンダリングする固定レンダラ。引数は `spec` / `workspace` / `relative_directory` のちょうど 3 つで、呼び出し側のコードは実行されない | ✗ |
| `generate_figures` | ネイティブの `ScienceDataV1` から決定論的な既定 spec を生成し、同じ固定レンダラで描画（`revision=0` のみ） | ✗ |
| `generate_figures_llm` | LLM が選べるのは `metric_id` / `chart_type` / `x_mode` だけで、数値・単位・キャプション・パス・成果物バイト列は検証済みの科学レコードから決定論的に決まる。`revision>0` は VLM フィードバックと直前のバッチの両方を要求 | ✓ |

## ari-skill-replicate — ルーブリック自動生成 (v0.7.0)

| ツール | 用途 | LLM |
|---|---|:---:|
| `generate_rubric` | 二段階（スケルトン + サブツリー）PaperBench ルーブリック合成 | ✓ |
| `audit_rubric` | LLM が曖昧 / 検証不可能 / 重複した基準の葉を監査 | ✓ |
| `suggest_target_leaf_count` | 論文長から目標葉数と単語数を算定して返す（GUI Wizard の "Target leaves" 欄の事前埋め用） | ✗ |

### `generate_rubric` — venue 条件付きテンプレート（未リリース）

`generate_rubric` はオプションの `paperbench_rubric_id` 引数を受け付け、
`ari-core/config/paperbench_rubrics/<id>.yaml` から venue 条件付き
テンプレートを選択します。`ari-skill-paper` のピアレビューパスがすでに使用している
`reviewer_rubrics/` の venue パターンを踏襲しています。

| 引数 | 型 | デフォルト | 効果 |
|---|---|---|---|
| `paperbench_rubric_id` | `str` | `""` | 空 = バンドル済みプロンプトをそのまま使用（後方互換）。それ以外の場合は YAML テンプレートをロードし、`prompt_overrides.system_hint` / `prompt_overrides.leaf_style` をスケルトン + サブツリープロンプトに注入。 |

同梱テンプレート:

| `id` | `mode` | トップレベル構造 |
|---|---|---|
| `generic` | `agent_benchmark` | 科学的貢献ごとに分解（現在のデフォルト動作）。 |
| `sc` | `paper_audit` | HPC 論文用の 6 固定監査軸（環境 / データ / 実行 / 図 / スケーリング / 結論）。 |
| `neurips` | `paper_audit` | NeurIPS 再現性チェックリストに基づく 6 軸（主張 / セットアップ / コード+データ / 統計 / 倫理 / 図）。 |
| `nature` | `paper_audit` | 実験系論文用の 5 軸（材料 / プロトコル / 統計 / データ / 倫理）。 |

`paper_audit` モードは `two_stage=True` が必要です。単一パスパスで
`paper_audit` テンプレートがリクエストされた場合、ジェネレータはエラーを返します
（単一パスプロンプトは固定軸制約を満たせないため）。YAML スキーマと
オーサリングガイドは [`rubric_schema.md`](rubric_schema.md#venue-conditioned-templates)
を参照してください。

## ari-skill-transform — ツリー走査 + EAR パイプライン

`mcp.json` は `skill.yaml` から生成された 5 ツールの名前を運び、引数と戻り値は
`src/server.py` の `@mcp.tool()` デコレータが定義します。

| ツール | 用途 | LLM |
|---|---|:---:|
| `nodes_to_science_data` | BFTS ツリーを走査して方法論 + 知見を抽出 | ✓ |
| `generate_ear` | BFTS 成果物から `{checkpoint}/ear/` をビルド | ✗ |
| `curate_ear` | `ear/` → `ear_published/` + manifest.lock に昇格 | ✗ |
| `publish_ear` | `local-tarball` / `ari-registry` / `zenodo` / `gh` にプッシュ | ✗ |
| `promote_ear` | `staged` → `unlisted` / `public` に昇格 | ✗ |

## ari-skill-vlm — 図 / 表の査読（VLM）

査読対象はディレクトリ走査ではなく、検証済みの `FigureBatchV1` マニフェストと
content-addressed な成果物参照で指定します。

| ツール | 用途 | LLM |
|---|---|:---:|
| `review_figure` | `FigureBatchV1` から `figure_id` で 1 枚を選んで査読 | ✓（ビジョン） |
| `review_figures_all` | バッチ内の全図を査読。図数 / 総バイト数 / モデル呼び出し数 / 並列度の予算を宣言でき、上限に触れた図は握り潰されず `limit-error` として個別に記録される。集約は `minimum-fail-closed`（1 枚でも失敗すればスコアは 0.0） | ✓（ビジョン） |
| `review_table` | 閉じた workspace 内の content-addressed な表成果物を 1 件査読。引数は閉じたスキーマの `request` 1 つ | ✓（ビジョン） |

## ari-skill-web — 検索 + 取得

決定論的な取得ツールは LLM を呼びません。`rerank_retrieval_records` だけが
独立した stochastic ツールです。`search_papers` / `web_search` / `fetch_url` /
`walk_citations` は `record`（既定）/ `live` / `replay` の実行モードを共有し、
`record` と `replay` は `ARI_CHECKPOINT_DIR` を要求します
（[検索契約とネットワークポリシー](retrieval_contract.md) を参照）。

| ツール | 用途 | LLM |
|---|---|:---:|
| `web_search` | DuckDuckGo（API キー不要）。`n` は 1〜10 に丸められる | ✗ |
| `fetch_url` | URL → 読み取り可能なテキスト。検証済み IP へ固定接続し、redirect ごとに再検証、HTTPS downgrade / サイズ超過を拒否し、返す本文は untrusted external data と明示する | ✗ |
| `search_papers` | 固定した 1 つの provider（`semantic-scholar` 既定 / `arxiv` / `alphaxiv`）を検索し `RetrievalRecordV1` を返す。provider 障害は別 provider へのフォールバックではなく明示エラーになり、`both` のような合成指定は拒否される | ✗ |
| `walk_citations` | Semantic Scholar の引用グラフを depth / node / request の予算とサイクル検出付きで辿る。上限到達時は保持済み record と `partial_reason` を返す | ✗ |
| `rerank_retrieval_records` | 取得済み `RetrievalRecordV1` を研究課題に対して LLM が並べ替える。model / API identity / temperature / prompt・input・output digest を provenance として記録 | ✓ |
| `list_uploaded_files` | チェックポイントの `uploads/` にあるユーザアップロードファイルを一覧 | ✗ |
| `read_uploaded_file` | アップロードファイルをテキストとして読む（バイナリ検出付き） | ✗ |

## ari-skill-knowledge — Knowledge の読み取り専用サーフェス

非実行の手続き知識に対する問い合わせと、権威を持たない要求だけを公開します。
Knowledge Skill の登録・昇格・失効・lock の書き換え・有効化はできません。

| ツール | 用途 | 権威 |
|---|---|:---:|
| `search_knowledge_skills` | 凍結されたカタログ射影を検索（結果はツール権限を与えない） | なし |
| `describe_knowledge_skill` | content-addressed な Knowledge Skill を 1 件、untrusted な instruction data として記述 | なし |
| `list_active_knowledge_skills` | この実行の epoch Knowledge lock を読む | なし |
| `request_knowledge_skill` | 次 epoch 向けの選択提案を作る（admit できるのは固定の Knowledge Binder のみ） | なし |

## ari-skill-harness — Assurance の読み取り専用サーフェス

Harness の探索、証拠の読み取り、補助検証の要求だけを公開します。Harness
Resolver でも Fixed Verifier でもなく、エージェントのツール選択が権威ある
スイートを選んだりロック済み検証を実行したりすることはできません。

| ツール | 用途 | 権威 |
|---|---|:---:|
| `search_harnesses` | 凍結された Harness カタログ射影を検索（Harness は選択されない） | なし |
| `describe_harness` | Harness 1 件と宣言された assurance scope を記述 | なし |
| `request_auxiliary_verification` | 追加的な検証要件を提案（固定の解決は内部に留まる） | なし |
| `read_attestation` | 完全な SHA-256 で不変の Attestation を 1 件読む | なし |
| `list_verification_requirements` | 不変の Verification Contract から要件を読む | なし |

どちらのパッケージも登録・昇格・失効・lock 書き換え・許容誤差 / オラクルの
差し替え・`force_pass` を公開しません。カタログ管理は人間が認証する CLI / PR
ワークフローです。詳細は
[Knowledge, Capability, and Scientific Assurance](knowledge_capability_assurance.md)
を参照してください。

## ari-skill-tool-registry — 大規模 MCP collection へのブローカ

上流 collection 全体を 5 つの federation 操作が代表するため、数千の leaf を
持つ collection でもエージェントが消費するツールスロットは数千ではなく 5 つ
です。leaf provider のスキーマが `tools/list` に露出することはありません。

| ツール | 用途 | LLM |
|---|---|:---:|
| `discover` | 不変の federated カタログを `lexical` / `exact` / `diverse` の strategy で検索。返るのは上限付きサマリと不透明な `tool_ref` で、`top_k` は最大 25、次ページは `constraints.cursor` で辿る。何も実行しない | ✗ |
| `describe` | 厳密に 1 つの `tool_ref` について descriptor の `section`（`summary` 既定 / `schema` / `provenance` / `admission` / `limitations` / `all`）をページングして読む。provider のテキストとスキーマは untrusted data として扱われる | ✗ |
| `invoke` | admit 済みの leaf 1 つを不変の `tool_ref` で `live`（既定）/ `record` / `replay` モード実行する。裸の名前や非修飾名は拒否される | ✗ |
| `get_status` | 非同期の registry `handle` を、その不変 descriptor に束縛された lifecycle 操作でポーリングする | ✗ |
| `get_result` | 非同期の registry `handle` について正規化された最終結果を取得する | ✗ |

`invoke` / `get_status` / `get_result` は run スコープの context requirement を
宣言するため、input schema に `ari_context` を持ちます — 上記
`measure_counters` と同じ注入規則で、transport が埋めるのでエージェントが渡す
引数ではありません。カタログの identity、admission レベル、provider adapter に
ついては [Federated Scientific Tool Registry](tool_registry.md) を参照して
ください。

## 関連ドキュメント

- `docs/ja/reference/skills.md` — 各スキルのナラティブな説明（責務、環境変数、例）。
- `docs/ja/reference/tool_registry.md` — `ari-skill-tool-registry` の 5 操作。
- `docs/ja/reference/knowledge_capability_assurance.md` — 3 層の identity、admission、lock、拡張ゲート。
- `docs/ja/reference/environment_variables.md` — 環境変数ごとのリファレンス。
- 各スキルの `mcp.json` — 標準的なツール名一覧。
- 各スキルの `src/server.py` の `@mcp.tool()` / `@server.list_tools()` — 標準的な引数シグネチャ。
- `ari-core/tests/fixtures/contracts/mcp_tools.json` — スキルごとのツール名を固定した契約スナップショット。
