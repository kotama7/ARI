---
sources:
  - path: ari-skill-benchmark/src/server.py
    role: implementation
  - path: ari-skill-benchmark/mcp.json
    role: config
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-evaluator/src/server.py
    role: implementation
  - path: ari-skill-evaluator/mcp.json
    role: config
  - path: ari-skill-harness/src/server.py
    role: implementation
  - path: ari-skill-harness/mcp.json
    role: config
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-idea/src/server.py
    role: implementation
  - path: ari-skill-idea/mcp.json
    role: config
  - path: ari-skill-knowledge/src/server.py
    role: implementation
  - path: ari-skill-knowledge/mcp.json
    role: config
  - path: ari-skill-memory/src/server.py
    role: implementation
  - path: ari-skill-memory/mcp.json
    role: config
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
  - path: ari-skill-paper/src/server.py
    role: implementation
  - path: ari-skill-paper/mcp.json
    role: config
  - path: ari-skill-plot/src/server.py
    role: implementation
  - path: ari-skill-plot/mcp.json
    role: config
  - path: ari-skill-replicate/src/server.py
    role: implementation
  - path: ari-skill-replicate/mcp.json
    role: config
  - path: ari-skill-tool-registry/src/server.py
    role: implementation
  - path: ari-skill-tool-registry/mcp.json
    role: config
  - path: ari-skill-transform/src/server.py
    role: implementation
  - path: ari-skill-transform/mcp.json
    role: config
  - path: ari-skill-vlm/src/server.py
    role: implementation
  - path: ari-skill-vlm/mcp.json
    role: config
  - path: ari-skill-web/src/server.py
    role: implementation
  - path: ari-skill-web/mcp.json
    role: config
  - path: ari-core/tests/fixtures/contracts/mcp_tools.json
    role: test
last_verified: 2026-08-17
---

# MCP ツールリファレンス

ARI には `ari-skill-*` パッケージごとに 1 つ、17 の MCP サーバが同梱されています。
このうち 13 は `ari-core/config/workflow.yaml` の `skills:` が既定で登録し、
`ari-skill-orchestrator` は外部クライアント向けに別プロセスとして起動します。
残る `ari-skill-knowledge` / `ari-skill-harness` は admission 済みカタログに対する
読み取り系サーフェス、`ari-skill-tool-registry` は大規模な MCP collection の
ブローカで、いずれも既定の `skills:` には載りません（tool-registry の 6 操作は
本ページ末尾に、カタログ identity と provider adapter は
[tool_registry.md](tool_registry.md) にあります）。

これらの `ari-skill-*` パッケージは実行可能な **Capability Provider** であり、
Knowledge Skill ではありません。MCP はその転送 / ディスカバリのプロトコルです。
非実行の手続き知識、capability binding、独立検証はいずれも別の契約であり、
[Knowledge, Capability, and Scientific Assurance](knowledge_capability_assurance.md)
にあります。

このページはエージェントが呼び出せるすべてのツールのフラットなカタログです。
各スキルの詳細は個別の `README.md` を参照してください。セクション
[skills.md](skills.md) では責務ごとにグループ分けされています。

v1 の Provider パッケージでは、ツールの identity / スキーマについてロックされた
出所は `skill.yaml` とライブの `tools/list` です。`mcp.json`（各スキルの
`pyproject.toml` の隣に配置）はレガシーな、パッケージローカルの互換メタデータ
であり、`skill.yaml` から `scripts/sync_skill_metadata.py --write` が生成する
読み取り専用ビュー（`ari.skill_manifest.legacy_mcp_document`）としてツール*名前*
だけを運びます。`@mcp.tool()` で装飾された関数（または `@server.list_tools()` の
エントリ）が引数と戻り値の形式を定義します。3 者がずれると
`scripts/check_skill_manifests.py` が失敗し、スキルごとのツール名一覧は
`ari-core/tests/fixtures/contracts/mcp_tools.json` にスナップショットとして
固定されています。

"LLM" 列は **P2 例外** のツールを示します — LLM を呼び出すため
バイト単位での決定論性がありません。

## ari-skill-benchmark — 統計 + run 比較（決定論的）

3 ツールとも引数は `request` ただ 1 つで、`ari.public.analysis` の型付き
リクエスト（`AnalysisRequestV1` / `StatisticalTestRequestV1` /
`RunComparisonRequestV1`）を包み、いずれも `AnalysisResultV1` を返します。
全 metric が `unit` の明示を要求されます。

| ツール | 用途 | LLM |
|---|---|:---:|
| `analyze_results` | unit 付き `MetricSampleSetV1` データセットの要約統計（信頼区間、正規性診断、欠損数、解決済み input digest）。観測値はインラインでも、閉じた workspace 内の digest 拘束された CSV / JSON / npy の 1 列でもよい | ✗ |
| `statistical_test` | 事前宣言した比較族の検定（`auto` / `welch_t` / `student_t` / `paired_t` / `mann_whitney` / `wilcoxon`）。効果量と補正済み p 値を返し、比較が 2 件以上のときは `correction` が `none` のままだと拒否される（`bonferroni` / `holm` / `benjamini_hochberg` のいずれかの明示が必須） | ✗ |
| `compare_runs` | スカラーの `RunRecordV1` を baseline に対してランク付けし、環境の互換性・provenance の差分・replicate 独立性が `declared` か `not-established` かを報告。`require_compatible_environment=true`（既定）は環境の異なる run の順位付けを拒否し、同一 backend/environment は独立 replicate とは推論せず共有 substrate として記録する | ✗ |

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
| `emit_results` | `params` と `measurements` を分離した型付き `results.json`（`MeasurementSetV1`）を書き出す（オプションの `provenance` 引数 → 各 measurement record に記録され、claim-evidence ゲートには `_provenance` マップとして届く）。レスポンスの `contract_warnings` には、出力したキーが要求エビデンス名と字句的に類似する場合、提案のみの「POSSIBLE name matches」ヒントが含まれることがあります — あくまで助言であり、自動バインドは行われず、ゲートがこれを参照することもありません | ✗ |
| `read_file` | エージェントが以前に書いたファイルを読み込む | ✗ |

## ari-skill-evaluator — メトリクス契約 + 主張ゲート

| ツール | 用途 | LLM |
|---|---|:---:|
| `make_metric_spec` | 不変で idea が所有する `ResearchContractV1`、または名前付きの `reviewer` が admit した提案から、実行レベルのメトリクス契約を materialize し、その projection を `{checkpoint}/metric_contract.json` に永続化します。mint-once: すでに永続化された projection の `projection_digest` が新しいものと異なる場合、それは上書きではなく拒否です。どちらも与えられず正準の `metric_contract.json` がすでに存在する場合は、再抽出せずそれを `contract_frozen: true` で返します（scoring guide などノードごとの spec フィールドは呼び出しごとに計算）。admit された契約が 1 つも無い場合でも `experiment.md` のパーサ出力は返りますが、あくまで証拠としてであり、`contract_frozen: false` / `admission_status: "human-review-required"` / `proposal_tool: "propose_metric_contract"` が付きます | ✗ |
| `propose_metric_contract` | 明示的に要求されたときだけ走る LLM 提案ステップ。アイデア（`idea_json`、または `{checkpoint}/idea.json`）を読み、`MetricContractProposalV1`（`requires_human_review: true`）を `{checkpoint}/metric_contract_proposal.json` に出力します。自らの出力を admit することは決してなく、すでに型付きの `ari.research-contract/v1` 契約を持つアイデアは拒否します | ✓ |
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
| `probe_platform_capabilities` | **計算パーティション上**でツールの有無（`command -v`）を調べ、`{checkpoint}/platform_capabilities.json` にキャッシュ；ベストエフォート（プローブ失敗時は skipped を返し何も書かない） | ✗ |
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
| `mint_contract_for_proposal` | このスキルが生成していない proposal に対して typed な `ari.research-contract/v1` を mint する — RQGM proposal router の候補が KCA admission に到達する経路。捏造せず拒否する: `ARI_CHECKPOINT_DIR` 未設定、survey スナップショット取得不可、タイトルの無い proposal はいずれも `contract_status: "rejected"` を返す | ✓ |

`_load_virsci_snapshot_papers` は `survey` が直接呼ぶただのヘルパーであり
エージェントからは決して見えません。`ari-skill-idea/tests/test_server.py` は
`mcp.list_tools()` 経由で `survey` と `generate_ideas` が登録されていること、
およびこのヘルパーが登録されていないことをピン留めしています。
`mint_contract_for_proposal` は他の 2 つと同様 `skill.yaml` にも `mcp.json`
にも宣言されているため、`scripts/check_skill_manifests.py` はこのパッケージに
ついて `tool-drift` を報告しません。provider 間の
フォールバックはありません: `virsci-snapshot` の survey はコーパスが無ければ
`FileNotFoundError` を、Semantic Scholar の survey は HTTP エラーをそのまま
raise します。障害時に得られるのは黙って別物になったコーパスではなく拒否です。
`survey` と `generate_ideas` は RQGM の `VirSciAdapter` の背後にある MCP 面でも
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

ここのツールは LLM を呼びません。ただし `ari-skill-memory/README.md` の
§ Determinism (P2) が記録しているとおり、v0.5.x の「LLM 呼び出しなし・完全に
決定的」という宣言は v0.6.0 で緩和されています：Letta の embedding search は
バージョン間で bit-reproducible ではないため、代わりに保存された `text` の
バイト列が CoW で保護されます。

破壊的な clear はありません。エージェントから見える操作でエントリが落とされる
ことはなく、`ari-skill-memory/tests/test_cow.py` がその不在を
（`assert not hasattr(server, "clear_node_memory")`）固定しています。ノードの
メモリを減らしたいときは `consolidate_node_memory` で統合済みの型付きエントリを
書いてください —— これはノードの `node_report` から導出され、それ自体も現在の
ノードへ CoW で拘束されています。ARI の governance がノードを論理的に消去した
場合も、記録は残ったまま `erased` / `erasure_event_id` / `erasure_note` の
ラベルが付いて返ります（黙って落とされることはありません）。

## ari-skill-orchestrator — 再帰的 ARI ランナー

すべてのツールが呼び出し元の principal に対して認可され、読み取り系ツールが
返すのはファイルシステムのパスではなく digest でアドレスされた参照です。
12 ツールすべてがエラーを例外ではなく `{"error": {"code", "message"}}` の
封筒で返し、`code` は `invalid_request` / `forbidden` / `not_found` /
`idempotency_conflict` / `quota_exceeded` / `artifact_policy` /
`authentication_failed` / `orchestrator_error` / `internal_error` の
いずれかです。契約の詳細は
[Orchestrator control plane](orchestrator.md) を参照してください。

| ツール | 用途 | LLM |
|---|---|:---:|
| `run_experiment` | 明示的な `idempotency_key` と quota ブロック（`max_nodes` / `max_total_nodes` / `max_descendant_runs` / `max_cost_usd` / `timeout_minutes`）の下で子の ARI 実行を冪等に投入し、永続ハンドルを返す | ✗ |
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
| `write_paper_iterative` | venue テンプレートの `FILL_*` ブロックを 1 回の呼び出しで埋め、続いて同じメッセージ履歴の上で `max(1, max_revision_rounds)` 回のリフレクションラウンドを回す（0 や負値を指定してもリフレクションは飛ばされず 1 回走る）。セクション単位のツールは存在せず、起草も改稿もこのツールの内部ステージ。戻り値は `latex` / `sections` / `reviews` / `revision_counts` / `paper_build` | ✓ |
| `finalize_paper_build` | 正確な証拠一式 —— tex / bib / PDF / コンパイル記録 / 図マニフェスト / claim リンク / ハードゲート / テキスト・ビジュアル・セマンティックの各査読 —— を 1 つの `PaperBuildV1` として `output_path` に固定。build が `finalized` にならない場合は `blocking_reasons` を列挙して例外を送出 | ✗ |
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
| `build_reproduce_sh` | `container_image`（レガシーの `apptainer_image` を置き換え。旧名はシグネチャから削除済みで、`container_image` が唯一のイメージ引数。値を解釈するのは `apptainer` ロールアウトだけで、`local` / `slurm` では無視される） |

### v0.8.0 新フィールド（Stage 2）

| ツール | 新しい引数 |
|---|---|
| `run_reproduce` | `container_image`（docker / apptainer / singularity サンドボックスでは必須、それ以外では拒否）。v1.0 が受け付けるのは不変な参照のみ：ローカルの非シンボリックリンク SIF、完全な `sha256:<image-id>`、または `name@sha256:<digest>` URI — 可変な `pb-env` / `pb-reproducer` の `:latest` エイリアスは削除されました |

フェイルラウド前提条件: `sandbox_kind=slurm` で `sbatch` が PATH に
無い場合、あるいは引数・`ARI_SLURM_PARTITION`・`launch_config.json` の
いずれからもパーティションを解決できない場合は、ローカル実行への黙った
フォールバックではなく `RuntimeError` を発生させます。コンテナサンドボックスで
ランタイムのバイナリが無い場合、または `container_image` が空か可変な場合は
`ReproductionContractError` を発生させます。v1.0 で host-local フォールバックは
削除されたため、元に戻すスイッチはありません。
[environment_variables.md](environment_variables.md#paperbench-再現フェーズ-stage-2) を参照。
GPU リクエストも 2 つの形を混ぜられません：per-node と per-task の GPU 数は
排他です。ただし数量を伴わない `gpu_type` はこの面では拒否されません — SLURM
実行経路が resource request を組み立てる前に per-node 1 GPU を補うため、
「`gpu_type` には明示的な GPU 数が必要」という下位のルールは
`run_reproduce` 経由では発火しません。

### v0.8.0 新フィールド（Stage 3）

| ツール | 新しい引数 |
|---|---|
| `grade_with_simplejudge` | `code_only`（ルーブリックを Code Development 葉のみに限定。vendor の `paperbench/grade.py:109-112` を踏襲）。既定は `False` で、勝手に有効化されることはありません — `reproduce.log` が無いときに自動で立っていた暗黙の `code_only` 採点は v1.0 で削除されました |

3 つのステージすべてを単一の呼び出し語彙でチェーンするインプロセス Python
サーフェスについては、
[`api_paperbench.md` § Bridge contract](api_paperbench.md#bridge-契約-in-process-python-インターフェース)
を参照してください。

## ari-skill-plot — 図生成

| ツール | 用途 | LLM |
|---|---|:---:|
| `render_figure` | 正準の `FigureSpecV1` を 1 枚レンダリングする固定レンダラ。引数は `spec` / `workspace` / `relative_directory` のちょうど 3 つで、呼び出し側のコードは実行されない | ✗ |
| `generate_figures` | ネイティブの `ScienceDataV1` から決定論的な既定 spec を生成し、同じ固定レンダラで描画。`revision` は `0` でなければならない —— 決定論的な経路にフィードバックラウンドは無い | ✗ |
| `generate_figures_llm` | LLM が選べるのは `metric_id` / `chart_type` / `x_mode` だけで、数値・単位・キャプション・パス・成果物バイト列は検証済みの科学レコードから同じ固定レンダラを通って決まる。`revision > 0` は `vlm_feedback` ドキュメントと、それが束縛する `previous_batch_path` の両方を要求する | ✓ |

## ari-skill-replicate — ルーブリック自動生成 (v0.7.0)

| ツール | 用途 | LLM |
|---|---|:---:|
| `generate_rubric` | 二段階（スケルトン + サブツリー）PaperBench ルーブリック合成 | ✓ |
| `audit_rubric` | LLM が曖昧 / 検証不可能 / 重複した基準の葉を監査 | ✓ |
| `suggest_target_leaf_count` | `{target, word_count}` を返す —— `generate_rubric` がその論文に対して自動計算する葉数なので、呼び出し側は当て推量せず事前に埋められる（GUI Wizard の "Target leaves" 欄の事前埋め用） | ✗ |

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

`paper_audit` テンプレートは空でない `top_level_axes` を宣言する必要があり、
宣言していないものの読み込みは拒否されます。単一パスの経路は存在しないため
選択の余地はなく、生成は常に skeleton + subtree の 2 段階です。`system_hint` は
skeleton パス、`leaf_style` は subtree パスに差し込まれます。YAML スキーマと
オーサリングガイドは [`rubric_schema.md`](rubric_schema.md#venue-別テンプレート-venue-conditioned-templates)
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
content-addressed な成果物参照で指定します。判定基準のプロファイルはバージョン
付きです（既定は `figure-publication/v1`）。

| ツール | 用途 | LLM |
|---|---|:---:|
| `review_figure` | `FigureBatchV1` から `figure_id` で 1 枚を選んで査読。バッチが持たない ID は拒否される | ✓（ビジョン） |
| `review_figures_all` | バッチ内の全図を `ReviewBudgetV1`（`max_figures` / `max_total_bytes` / `max_concurrency` / `max_model_calls` / `max_output_tokens`）の下で査読。上限に触れた図や成果物不正の図は握り潰されず `limit-error` / `artifact-error` として個別に記録される。集約は `minimum-fail-closed`（1 件でも失敗すればバッチの `score` は 0.0、全件完了なら各図の最小値） | ✓（ビジョン） |
| `review_table` | 閉じた workspace 内の content-addressed な表成果物を 1 件査読。`request` のスキーマは厳密で、`workspace` / `target_id` / `artifact` / `context` / `criteria_profile_id` / `iteration`（0〜2）/ `max_output_tokens` ちょうど。未対応の media type は例外ではなく `artifact-error` の査読として返る | ✓（ビジョン） |

## ari-skill-web — 検索 + 取得

取得は provider ごとに 1 ツールではなく、1 つの契約です。決定論的な取得ツールは
LLM を呼びません。`rerank_retrieval_records` だけが独立した stochastic ツール
です。`search_papers` / `web_search` / `fetch_url` / `walk_citations` は
`mode` を共有します —— `record`（既定。取得してスナップショットを残す）/
`live`（取得するがスナップショットを残さない）/ `replay`（ネットワークに一切
アクセスせず、直前の record が返したチェックポイント相対の `snapshot_ref` を
要求する）—— そして `RetrievalRecordV1` の行を返します。`record` と `replay` は
`ARI_CHECKPOINT_DIR` を要求します
（[検索契約とネットワークポリシー](retrieval_contract.md) を参照）。

| ツール | 用途 | LLM |
|---|---|:---:|
| `web_search` | DuckDuckGo（API キー不要）。`n` は 1〜10 に丸められる | ✗ |
| `fetch_url` | URL → 読み取り可能なテキスト。検証済み IP へ固定接続し、redirect ごとに再検証、HTTPS downgrade / サイズ超過を拒否し、返す本文は untrusted external data と明示する | ✗ |
| `search_papers` | 固定した **1 つ** の学術 provider —— `semantic-scholar`（既定）/ `arxiv` / `alphaxiv` —— を `provider` 引数または `ARI_RETRIEVAL_BACKEND` から選んで検索し `RetrievalRecordV1` を返す。provider ごとのツールも合成ツールも存在せず、`provider="both"` は拒否され、固定した 2 回の呼び出しを発行して alias でマージするよう指示される | ✗ |
| `walk_citations` | Semantic Scholar の引用グラフをサイクル検出付きで辿る。`direction` は `references` または `citations`、上限は `max_depth`（≤5）/ `max_nodes`（≤500）/ `request_budget`。上限到達時は保持済み record と `partial_reason` を返す | ✗ |
| `rerank_retrieval_records` | 取得済み `RetrievalRecordV1` を研究課題に対して LLM が並べ替える。model / API identity / temperature / prompt・input・output digest を provenance として記録 | ✓ |
| `list_uploaded_files` | チェックポイントの `uploads/` 配下を `{name, size_bytes}` で一覧 | ✗ |
| `read_uploaded_file` | アップロードファイルをテキストとして読む（バイナリ検出付き） | ✗ |

取得バックエンドは呼び出しごと、または環境変数で選ばれます。プロセス全体の
バックエンドを書き換えるツールは存在しないため、並行する 2 つの呼び出し元が
互いの provider を変えてしまうことはありません
（`ari-core/tests/test_retrieval_backend.py::test_mutable_retrieval_backend_tool_is_removed`
がその不在を固定しています）。

## ari-skill-knowledge — Knowledge の読み取り専用サーフェス

互換のために旧名を保っているこのパッケージは Capability Provider であり、
ARI Knowledge Skill Registry に対する問い合わせと、権威を持たない要求だけを
公開します。Knowledge Skill の登録・昇格・失効・lock の書き換え・有効化は
できません。固定の `knowledge_binder_v1` が権威であり続けます。

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

上流 collection 全体を 6 つの federation 操作が代表するため、数千の leaf を
持つ collection でもエージェントが消費するツールスロットは数千ではなく 6 つ
です。leaf provider のスキーマが `tools/list` に露出することはありません。

| ツール | 用途 | LLM |
|---|---|:---:|
| `discover` | 不変の federated カタログを `lexical` / `exact` / `diverse` の strategy で検索。返るのは上限付きサマリと不透明な `tool_ref` で、`top_k` は最大 25、次ページは `constraints.cursor` で辿る。何も実行しない | ✗ |
| `describe` | 厳密に 1 つの `tool_ref` について descriptor の `section`（`summary` 既定 / `schema` / `provenance` / `admission` / `limitations` / `all`）をページングして読む。provider のテキストとスキーマは untrusted data として扱われる | ✗ |
| `invoke` | admit 済みの leaf 1 つを不変の `tool_ref` で `live`（既定）/ `record` / `replay` モード実行する。裸の名前や非修飾名は拒否される | ✗ |
| `invoke_scheduled` | スケジューラへジョブを投入する leaf に対する同じ操作。Provider の副作用クラスはその権限に従うため、共有サーフェスにスケジューラ権限を持たせると、そこを通る全 leaf の権限エンベロープが上がってしまう。だから面を分けている | ✗ |
| `get_status` | 非同期の registry `handle` を、その不変 descriptor に束縛された lifecycle 操作でポーリングする | ✗ |
| `get_result` | 非同期の registry `handle` について正規化された最終結果を取得する | ✗ |

`invoke` / `invoke_scheduled` / `get_status` / `get_result` は run スコープの
context requirement を宣言するため、input schema に `ari_context` を持ちます —
上記 `measure_counters` と同じ注入規則で、transport が埋めるのでエージェントが
渡す引数ではありません。なおこのパッケージの `mcp.json` は skill.yaml から
再生成済みで、`invoke_scheduled` を含む 6 つの名前をすべて載せているため、
`scripts/check_skill_manifests.py` は
`compat-metadata-drift` を報告しません。カタログの identity、admission レベル、provider adapter に
ついては [Federated Scientific Tool Registry](tool_registry.md) を参照して
ください。

## 関連ドキュメント

- `docs/ja/reference/skills.md` — 各スキルのナラティブな説明（責務、環境変数、例）。
- `docs/ja/reference/tool_registry.md` — `ari-skill-tool-registry` の 6 操作。
- `docs/ja/reference/knowledge_capability_assurance.md` — 3 層の identity、admission、lock、拡張ゲート。
- `docs/ja/reference/environment_variables.md` — 環境変数ごとのリファレンス。
- 各スキルの `mcp.json` — 標準的なツール名一覧。
- 各スキルの `src/server.py` の `@mcp.tool()` / `@server.list_tools()` — 標準的な引数シグネチャ。
- `ari-core/tests/fixtures/contracts/mcp_tools.json` — スキルごとのツール名を固定した契約スナップショット。
