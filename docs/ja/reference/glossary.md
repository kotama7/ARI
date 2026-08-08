---
sources:
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-core/ari/evaluator/llm_evaluator.py
    role: implementation
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/config/reviewer_rubrics
    role: config
  - path: ari-skill-replicate
    role: implementation
  - path: ari-skill-paper-re
    role: implementation
  - path: ari-core/ari/pipeline/claim_gate
    role: implementation
  - path: ari-core/ari/pipeline/verified_context.py
    role: implementation
  - path: ari-skill-memory
    role: implementation
  - path: ari-core/ari/rqgm
    role: implementation
last_verified: 2026-08-08
---

# 用語集

ARI ドキュメント全体で繰り返し登場する用語を短く定義し、それぞれを詳しく解説する
ドキュメントへ案内します。用語は、属するサブシステムごとにまとめています。

## 探索とオーケストレーション

**BFTS (Best-First Tree Search)**
ARI の実験探索ループ。実験設定の木を探索し、常に最も有望な完了ノードを最初に展開します。
`ari/orchestrator/bfts.py` に実装されています。[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**pending**
BFTS の 2 つのプールの一方: 親から展開済みで実行可能な状態だが、まだ実行されていない
ノード群。[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**frontier**
BFTS のもう一方のプール: 展開待ちの完了済みノード群。フロンティアは *永続的* です —
ノードは子を生成した後も再展開可能なまま残り続け、退役するまで利用可能です。
[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**retire（フロンティアノードを退役させる）**
完了ノードをそれ以降の展開対象から外すこと。ノードは **ルール A**
（子が `_scientific_score` で親を上回る）または **ルール B**（`max_expansions_per_node`
回展開済みになった）のいずれかで退役します。[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**node label（ノードラベル）**
BFTS ノードが親に対して果たす役割: `draft`、`improve`、`debug`、
`ablation`、`validation`、`other`。未知のラベルは `other` に丸められ、
`raw_label` が原文の文字列を保持します。[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**diversity bonus（多様性ボーナス）**
探索が単一の戦略に収束しないよう、過少表現のノードラベル（直近 20 実行を追跡）に
与えられる `+0.05` のスコア補正。
[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**sterile（不毛なノード）**
実行後に親に対して何も変更しなかった子ノード。pin された problem が `score_inputs` を
宣言している場合は、そのファイル群だけの sha256 を比較して不毛性を判定します。宣言が
なければ `work_dir` 全体の差分（`added = modified = deleted = 0`。親の `work_dir` を
コピーしない構成では `added = modified = 0`）にフォールバックします。いずれの経路でも
`_sterile = True` とマークされて剪定され、不毛な子が親を退役させることはありません。
`work_dir` 全体の経路ではさらに `_scientific_score` が `0.0`、`has_real_data` が
`False` にクランプされますが、`score_inputs` の経路では測定済みスコア・
`has_real_data`・`evaluation_status` はそのまま保持されます。これは、子が何も実行せずに
親の結果を「継承」してしまうのを防ぐ仕組みです。
[アーキテクチャ → work_dir 継承](../concepts/architecture.md#work_dir-inheritance--output-artifact-blacklist-v070--phase-7)を参照。

**should_prune**
BFTS の硬い打ち切り述語: `current_total ≥ max_total_nodes`、
`depth ≥ max_depth`、`_sterile is True`、または `_valid_for_frontier is False`
（RQGM 選択的消去）のときに剪定します。
ここに LLM の判断は入りません。[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**computed-evidence claim（計算由来エビデンスのクレーム）**
要求エビデンスを直接の測定ではなく、既存の測定値から *計算して* 得る必要がある
契約クレーム（パラメータフィッティング、ホールドアウト検証、モデルベース選択など）。
元の測定値をすでに保持しているノードを展開することでのみ到達できます —
**lineage chaining** を参照。

**lineage chaining（系統チェイニング）**
computed-evidence claim を到達可能にする BFTS の仕組み: 展開選択ヒントが契約
エビデンスを最も多く保持するノードを名指しし、*そのノード* の展開を推奨します
（子は親の `work_dir` を継承します）。また、継承した `work_dir` に系統の測定値が
すでに存在する子ノードには、存在するファイルと契約名を列挙した INHERITED DATA
ノートが固定義務（pinned obligation）に付きます。流れるのは名前とファイルのみで、
値や兄弟ノードの結論は決して流れません（fault containment を維持）。
[BFTS アルゴリズム](../concepts/bfts.md)を参照。

## 評価

**scientific_score / `_scientific_score`**
`LLMEvaluator` が各ノードに付与する査読品質スコア（0.0〜1.0）。
`metrics["_scientific_score"]` に格納され、BFTS のランキング、系統（lineage）の判断、
ベストノードの選択を駆動します。
[設定 → BFTS Evaluation Layers](configuration.md#bfts-evaluation-layers-configurable)を参照。

**composite formula（合成式）**
各軸のスコアを 1 つのスカラーに集約する方法: `harmonic_mean`（既定）、
`arithmetic_mean`、`weighted_min`、`geometric_mean`。
`evaluator.composite` で設定できます。
[設定 → BFTS Evaluation Layers](configuration.md#bfts-evaluation-layers-configurable)を参照。

**plan（プラン）**
実行の *評価の具体内容* — どのメトリクスを測るか、どのベースラインと比較するか、
どのアブレーションを走らせるか。`idea.json[0].experiment_plan` を出所とします。
既定ではサブ実験に継承されません（子は自前で書くため、方向転換の自由を保てます）。
[アーキテクチャ → Plan / Venue 契約](../concepts/architecture.md#plan--venue-contract-v070)を参照。

**venue（ベニュー）**
実行の *判定基準* — どの次元を、どのように採点するか。ベニューは
`ari-core/config/reviewer_rubrics/<id>.yaml` ファイルです。選択子は 2 つあり、
互いに独立しています: BFTS の採点軸には `ARI_RUBRIC`（既定 `neurips`）、
論文査読には `workflow.yaml` のトップレベル `paper_rubric` キー（既定
`generic_conference`）で、こちらは review ステージへ明示的な `rubric_id`
として渡されます。1 つのベニューで採点と査読の両方を駆動したい場合は、
両方に同じ id を設定してください。
[アーキテクチャ → Plan / Venue 契約](../concepts/architecture.md#plan--venue-contract-v070)を参照。

**rubric（ルーブリック）**
採点の仕様。ARI ではこの語を 2 つの文脈で使います: 論文査読向けの **reviewer rubric**
（上記のベニュー YAML）と、再現性採点向けの **ORS rubric**（PaperBench の `TaskNode` 木）です。
[ルーブリックスキーマ](rubric_schema.md)を参照。

**lineage decision（系統判断）**
合成スコアが停滞したとき、BFTS のフックはまず決定論的に、最も有望な *未使用* の次点
アイデアへ `switch_to_idea` で方向転換します — 次点アイデアを未使用のまま死蔵させず、
実際に試させるためです。LLM ジャッジ（`continue` / `switch_to_idea` / `fanout` /
`terminate` のいずれかを選びます）は、フォールバックとしてのみ参照されます — 予算が
枯渇したとき、再帰上限に達したとき、または未使用の代替が残っていないときです。
[アーキテクチャ → Plan / Venue 契約](../concepts/architecture.md#plan--venue-contract-v070)を参照。

**claim-evidence gate（主張・根拠ゲート）**
決定論的で LLM を使わないゲート（`claim_evidence_hard_gate`）。論文で報告された各数値を
記録済みの結果から許容誤差内で再導出し、数値カバレッジ・オペランド解決・図の存在を
チェックします。既定では `warn` モードで有効で、これは objective-integrity の
`always_block_on` ティア（invariant 違反、correctness の失敗・未カバー、
ceiling が未計測、recompute が再現しない、cross-run または未束縛の evidence）
のみを FINAL フェーズでブロックします。設定済みの `block_on` 所見と strict
セクションの未カバー数値も追加でブロックするには
`claim_gate_policy.mode: strict`（または `ARI_CLAIM_GATE_MODE=strict`）を
設定します。draft フェーズのレポートは決してブロックしません。
`comparison_scope` が `any`（既定）の場合、
環境をまたいだ比較は透明性のための警告として扱われ、`same_environment` の場合は
ブロッキングエラーになります。[設定](configuration.md)を参照。

**mint-once（契約凍結）**
実行レベルの `metric_contract.json` は一度だけ書き込まれるというルール: idea 所有の
Research Contract を解決した最初の `make_metric_spec` 呼び出し（あるいは人間がレビュー
した `propose_metric_contract` の提案を admit した呼び出し）が projection を永続化し、
以降の呼び出しは再抽出せずそのファイルを読み戻して返します（`contract_frozen: true`）。
`projection_digest` が永続化済みのものと異なる再 mint は上書きではなく拒否されます。
LLM の命名は参照的に安定しないため、実行途中の再生成はエビデンス語彙を変えてしまい、
すでに出力済みのエビデンスが完全一致ゲートから見えなくなります。admit された契約が
存在しない場合は何も凍結されず、応答は `contract_frozen: false` /
`admission_status: human-review-required` となり、パーサ出力はエビデンス扱いに
とどまります。[ファイル形式](file_formats.md#metric_contractjson)を参照。

## メモリ

**ancestor scope（祖先スコープ）**
ノードは自身の祖先チェーン（root → 親）からのみメモリを読み取れ、兄弟からは決して
読み取れないというルール。`search_memory` は転送層で署名された系統の外にある id を
拒否し、さらにバックエンドが `node_id ∈ ancestor_ids` のメタデータでフィルタします。
[メモリアーキテクチャ](../concepts/memory.md)を参照。

**CoW (Copy-on-Write)**
兄弟間で祖先メモリをバイト単位で安定に保つための書き込みガード:
書き込み側のツールは、呼び出しに付随する署名済み `NodeContextV1` の self ノード以外の
`node_id` をすべて拒否します。環境変数 `$ARI_CURRENT_NODE_ID` は権限を持ちません。
[メモリアーキテクチャ](../concepts/memory.md)を参照。

**Letta**
v0.6.0 以降で使われているメモリバックエンド（旧 MemGPT）。各チェックポイントに専用の
エージェントが割り当てられ、2 つのコレクションを保持します: `ari_node_<hash>`（祖先スコープの
アーカイブ）と `ari_react_<hash>`（フラットな ReAct トレース）。
[メモリアーキテクチャ](../concepts/memory.md)を参照。

**verified context / verifiable research memory（検証済みコンテキスト / 検証可能な研究メモリ）**
Letta の上に構築される、型付きで sha256 来歴付きのレイヤー。ノード終了時に
`node_report.json` が型付き・来歴付きのレコード（`experiment_result` / `failure_case` /
`reflection`）へ統合されます。続いて論文パイプラインが、成果物に裏付けられた
`verified_context.json`（ベストノードの root→best 系統にスコープされる）を導出し、
実際に測定された内容に論文の主張を接地させます。`ARI_MEMORY_CONSOLIDATE` により既定で
有効です。[検証可能な研究メモリ](../concepts/verifiable_research_memory.md)を参照。

## エージェントとスキル

**ReAct loop（ReAct ループ）**
LLM の推論と MCP ツール呼び出しを交互に行って 1 つの実験を実行する、ノードごとの
エージェントループ（`ari/agent/loop.py`）。
[アーキテクチャ → ノードごとのプロンプト構成](../concepts/architecture.md#per-node-prompt-composition)を参照。

**MCP skill（MCP スキル）**
Model Context Protocol サーバーとしてパッケージ化された機能（例: `ari-skill-hpc`）。
スキルは `ari.public.*` からのみ import できます。`ari-skill-*` パッケージは 17 個あり、
同梱の `workflow.yaml` はそのうち 13 個を明示的に列挙しています。
[MCP スキル](skills.md)を参照。

**VirSci**
研究目標を仮説と主要メトリクスへと変換するマルチエージェント討議。ルートノードで
`generate_ideas` を通じて一度だけ実行されます。
[アーキテクチャ](../concepts/architecture.md#full-data-flow)を参照。

## RQGM（オプトインの憲法ガバナンス）

オプトインの `ari_rqgm` 実行モードに固有の用語です。デフォルトのランには
どれも当てはまりません。[実行モード](../guides/execution_modes.md)と
[RQGM 評価](../guides/rqgm_evaluation.md)を参照。

**simple_bfts / ari_rqgm（実行モード）**
`ari.mode` の 2 つの値。`simple_bfts`（デフォルト）は現行の ARI そのままで、
変更はありません — RQGM オブジェクトを構築せず、`ari.rqgm` モジュールを
インポートしません。`ari_rqgm` はエポックガバナンスへのオプトインで、加えて
`rqgm.enabled: true` インターロックを必要とします; 不一致は警告とともに
`simple_bfts` へ fail-safe します（`ari/rqgm/mode.py`）。
[実行モード](../guides/execution_modes.md)を参照。

**epoch（エポック）**
`ari_rqgm` ランのガバナンス時間区分。境界トランザクションは新規 BFTS ノード
`rqgm.epoch.nodes_per_epoch` 個ごとに発火します（デフォルト 10; `<= 0` は
ランを `epoch_000` に留めます）。ガバナンス、レジストリ遷移、リプレイプール
への受け入れはこれらの境界でのみ起こります。

**EpochState**
アクティブなプロンプト / コンポーネント集合と utility policy の、エポック
ごとの不変な凍結（`ari/rqgm/state.py`、`epoch_state.json` へスナップ
ショット）。エポックの間は凍結されたままで、壁時計フィールド抜きで
フィンガープリントされるため、後のレジストリ変更が閉じたエポックに漏れる
ことは決してありません。

**ConstitutionalKernel**
進化しない Layer-0 チェッカ（`ari/rqgm/kernel.py`）: バイト安定な
`KernelReport` 判定を返し、何も書かない、純粋で決定論的なバリデータです。
severity はコード（`kernel_rules.py`）に凍結され、決して設定できません;
設定に置かれるのは姿勢（`rqgm.kernel.enforcement`: `standard` /
`audit_only`）と浮動小数トレランスのみです。

**GovernanceOrchestrator**
エポック境界ガバナンスの単一のエントリポイント（`ari/rqgm/governance/`）:
閉じようとしているエポックに対する証拠収集、追及、弁護、裁定で、
ConstitutionalKernel によって自己監査されます。予算と姿勢は
`rqgm.governance` / `rqgm.replay` にあります。

**RegistryTransitionEngine**
レジストリステータスの唯一の書き込み手（`ari/rqgm/transition_engine.py`）。
ガバナンスの結果を、RQGM ストアを通じて永続化されるコミット済み
`EpochTransition`（有効化 / 退役）へ変えます; 他のいかなるコンポーネントも
プロンプトやコンポーネントのステータスを変更できません。

**FrontierRepairEngine**
退役を伴う遷移の後、エポック境界で走ります
（`ari/rqgm/frontier_repair.py`）: 退役した `prompt_hash` に実質的に依存
するレコードをトレースし、stale とマークし（論理のみ — 何も削除されない）、
生き残ったものを再計算し、BFTS フロンティアを決定論的に再構築します。

**ProposalRecord / ProposalSummaryView**
`ProposalRecord` はアーカイブされる提案 1 件です（append-only な
`{checkpoint}/proposals/proposal_records.jsonl`）; `ProposalSummaryView` は
そこから導出される有界のサマリ — BFTS が見る**唯一の**形です
（`ari/rqgm/proposals/records.py`）。`ProposalRouter` は
`proposal_router.*` の予算の下でジェネレータレジストリへ生成を
ディスパッチします; VirSci ジェネレータはオプトインで、デフォルトでは off
です。

**PromptSpec**
バージョン付きのプロンプトアイデンティティ 1 件（`ari/rqgm/prompt_spec.py`）。
不変です: あらゆる変更は新しい `prompt_id` + `prompt_hash` であり、編集では
ありません。進化済みテンプレート本文は `{checkpoint}/rqgm_prompts/` 以下に
write-once で保存されます。

**ValidatedAttackRecord**
裁定を生き延びた敵対的発見 — 判定 `valid` / `partially_valid` に対してのみ
存在し（`ari/rqgm/adversarial/records.py`）、リプレイプールに受け入れ可能な
唯一の攻撃形です。

**AdversarialReplayPool**
裁定済み失敗ケースのキュレートされたプール
（`ari/rqgm/adversarial/pool.py`）で、
`{checkpoint}/rqgm/adversarial_replay_pool.json` へスナップショットされ
ます; append-only な真実は `rqgm_adversarial_cases.jsonl` です。受け入れは
エポック境界でのみ起こります; サイズは `rqgm.adversarial.pool.*` にあり
ます。

**selective erasure（選択的消去）**
退役したプロンプトが生んだ — またはそれに実質的に依存する — レコードの、
論理のみの無効化。物理的な削除や書き換えは何も起こりません: staleness は
`SelectiveErasureEvent` / `FrontierRebuildEvent` の監査ログ行と、導出された
`rqgm_erasure_state.json` ロールアップに存在し、読み取り側が読み取り時に
`stale` を導出します。

**clean-room regeneration（クリーンルーム再生成）**
退役ロールの置換プロンプトを、退役プロンプトのテキストへアクセスせずに
起草すること（`ari/rqgm/clean_room.py`、`CleanRoomCoordinator`）。候補の
受け入れに対しては fail-closed、ランに対しては fail-open です: 違反があれば
ロールはコミット済みのベースラインテンプレートへ戻り、ループは継続します。

**meta tier（メタティア）**
3 つのレジストリティア（`fixed` / `institutional` / `meta`）の最上位。
メタティアのガバナンスコンポーネントは進化できますが、その権限は拡大でき
ません: capability フラグは deny-by-default で、`ari/rqgm/meta_rules.py` の
凍結された権限テーブルに対してチェックされます。

## 状態と公開

**checkpoint（チェックポイント）**
1 回の実行に対応する自己完結型ディレクトリ `{workspace}/checkpoints/{run_id}/`。
`run_id` は `YYYYMMDDHHMMSS_<slug>` 形式です。すべての状態はここに置かれ、`PathManager`
（`ari/paths.py`）が唯一の真実源です。API キーはここには決して保存されません —
`.env` または環境から取得されます。
完全なレイアウトは[アーキテクチャ → ファイル構造](../concepts/architecture.md#file-structure)を、
ファイルごとのスキーマは[ファイルフォーマット](file_formats.md)を参照して
ください。`ari_rqgm` ランは加えて RQGM 状態ファイル（`rqgm_state.json`、
`rqgm_registry.json`、`rqgm_audit.jsonl`、`proposals/`、`rqgm_prompts/`、
…）を書きます — デフォルトのランにはすべて不在です。

**EAR (Experiment Artifact Repository)**
論文に同梱される、決定論的にビルドされる `ear/` バンドル（コード、入力データ、図表、README、
`reproduce.sh`、LICENSE）。実験の *出力* は意図的にバンドルされません。
[公開ライフサイクル](../concepts/publication-lifecycle.md)を参照。

## 再現性 (ORS / PaperBench)

**ORS**
ARI の再現性チェック — 論文を再実行して採点する、決定論的で PaperBench 互換の 2 フェーズ
フロー。v0.7.0 で旧来の LLM 判定経路を置き換えました。
[PaperBench クイックスタート](../guides/paperbench/paperbench_quickstart.md)を参照。

**TaskNode**
PaperBench 形式のルーブリック木におけるノード。論文から生成される ORS ルーブリックは、
重みと閉じた `task_category` 語彙を持つ `TaskNode` の木です。
[ルーブリックスキーマ](rubric_schema.md)を参照。

**Phase 1 / Phase 2**
ORS の 2 つのフェーズ: **Phase 1**（`run_reproduce`）はサンドボックス内で `reproduce.sh` を
実行します（`slurm` → `docker` → `apptainer` → `singularity` → `local`）。**Phase 2**
（`grade_with_simplejudge`）はルーブリックの葉に対して PaperBench SimpleJudge を実行します。
[PaperBench API](api_paperbench.md)を参照。

**negative control（陰性対照）**
ORS のガードレール: 空のリポジトリ + 自明な `reproduce.sh` は 5% 未満のスコアにならなければ
ならず、ルーブリックが「何もしていないこと」に報酬を与えないことを証明します。
[PaperBench API](api_paperbench.md)を参照。

**bridge stage（ブリッジステージ）**
v0.8.0 PaperBench ブリッジにおける 3 つのベンダープロトコルのエントリポイントの 1 つ:
`rollout_submission`（エージェントが提出物を生成）、`reproduce_submission`
（それを実行）、`judge_submission`（採点）。
[PaperBench API](api_paperbench.md)を参照。

**paper-audit mode（論文監査モード）**
ORS ルーブリックの仕組みを逆向きに用い（v0.7.2）、ベニューテンプレート
（`sc` / `neurips` / `nature`）に基づいて、論文 *自体* が再現可能なほど十分に
記述されているかを監査するモード。[ルーブリックスキーマ](rubric_schema.md)を参照。

---

関連: [アーキテクチャ](../concepts/architecture.md) ·
[BFTS アルゴリズム](../concepts/bfts.md) ·
[メモリアーキテクチャ](../concepts/memory.md) ·
[実行モード](../guides/execution_modes.md) ·
[設定](configuration.md)
