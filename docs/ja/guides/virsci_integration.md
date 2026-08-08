---
sources:
  - path: ari-core/ari/rqgm/proposals/virsci_adapter.py
    role: implementation
  - path: ari-core/ari/rqgm/proposals/router.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/configs/defaults.yaml
    role: config
  - path: ari-skill-idea/src/server.py
    role: implementation
  - path: ari-core/tests/test_rqgm_virsci_adapter.py
    role: test
last_verified: 2026-07-30
---

# VirSci 統合

VirSci（マルチエージェントの科学協働アイデアジェネレータ）は、2 つの独立した
面を通じて ARI に到達します。どちらもデフォルトでは有効ではなく、互いを必要と
しません:

1. **`ari-skill-idea` MCP スキル**（両実行モード）— `workflow.yaml` の
   `generate_idea` ステージが、BFTS 開始前に一度だけスキルの
   `generate_ideas` ツールを呼びます。スキルは 1 つの出力契約の背後に 2 つの
   エンジンを持ちます: デフォルトの軽量な **reimpl** 議論ループと、vendored
   された VirSci 機構を実行するオプトインの **real_wrap** エンジン
   （`ARI_IDEA_VIRSCI_REAL=1`）です。
   [MCP スキルリファレンス → ari-skill-idea](../reference/skills.md)を参照。
2. **RQGM の `VirSciAdapter`**（`ari_rqgm` モードのみ）— `ProposalRouter`
   （`ari/rqgm/proposals/router.py`）の背後にあるオプションの高コスト熟議型
   ジェネレータ。本ガイドはこちらの面を扱います。

アダプタ（`ari/rqgm/proposals/virsci_adapter.py`）は **MCP-only の
ノーマライザ**です: アイデアスキルの `survey` と `generate_ideas` ツールを
MCP 経由で呼び、`ari-skill-idea` からは何もインポートしません。重い依存
（torch/faiss/agentscope）はスキルプロセスの内側に留まるため、スキルの
縮退ティアは無傷に保たれ、「VirSci がインストールされていなくてもテストが
パスする」ことが構造的に成立します。

## 設定

このジェネレータは `proposal_router.generators` ブロックの 1 エントリです
（`ari.config.VirSciGeneratorConfig`; デフォルトは
`ari-core/ari/configs/defaults.yaml` にミラーされ、パリティは
`ari-core/tests/test_rqgm_proposals.py` でピン留めされています）:

```yaml
proposal_router:
  summary_budget_chars: 6000
  generators:
    virsci:
      enabled: false            # opt-in; never enabled by default
      mode: event_triggered     # v1 supports only `event_triggered`
      max_calls_per_epoch: 2    # hard per-epoch cap on adapter invocations
      trigger_on: [initial_exploration, frontier_stagnation,
                   major_pivot, paper_candidate]
```

- **`enabled`**（デフォルト `false`）— アダプタのマスタースイッチ。
  [`enabled: false` のときの保証](#guarantees-when-enabled-false)を参照。
- **`mode`** — 呼び出しモード; v1 で受理される唯一の値は
  `event_triggered` です（ポーリングモードやノード単位モードはありません）。
- **`max_calls_per_epoch`** — エポックごとの呼び出し予算。予算の計上は
  レコードではなく**ディスパッチヘッド**を数えます: VirSci 呼び出し 1 回は
  複数の `ProposalRecord` を生みますが予算は 1 単位しか消費しません
  （`ProposalStore.count_for_epoch`）。カウントは保存済みレコードから
  導出されるため resume をまたいで決定論的であり、完全に重複排除された
  リトライ（MCP の 3 リトライポリシー）は何も追記せず予算も消費しません。
- **`trigger_on`** — アダプタへルーティングされうるルータのトリガ
  イベント。イベントをこのリストから外すと、そのイベントに対して VirSci
  は利用不能になります。

`proposal_router.*` は実効モードが `ari_rqgm` のときにのみ消費されます
（唯一の例外 `record_only` は VirSci と無関係です —
[RQGM 移行](rqgm_migration.md)を参照）。`simple_bfts` の下では、既存の
スキル側レバー — `workflow.yaml` の `generate_idea` ステージと
`ARI_IDEA_VIRSCI_REAL` — が引き続き唯一の VirSci 制御です。

## イベントトリガのルーティングと予算

ルーティングは純粋なポリシー関数 `ari.rqgm.proposals.router.route`
（決定論的、I/O なし、乱数なし — P2）です: トリガイベントに対し、固定の
優先順序の中で予算が残っている最初の*有効な*ジェネレータが勝ちます。
v1 の優先テーブル:

| トリガイベント | 優先順序 |
|---|---|
| `initial_exploration` | `virsci` → `prior_art` → `cheap` |
| `frontier_stagnation` | `virsci` → `mutation` → `cheap` |
| `major_pivot` | `virsci` → `prior_art` → `cheap` |
| `paper_candidate` | `prior_art` → `mutation` → `cheap` |

したがって VirSci が有効で予算が残っている場合、アダプタは
`initial_exploration`、`frontier_stagnation`、`major_pivot` の第一候補に
なります; 固定の `paper_candidate` の順序は、`trigger_on` が何であれ VirSci
を決して選びません。予算が尽きれば次のジェネレータへフォールスルーし、
ドラフトをゼロ件返したジェネレータは 1 ティア下の上限なし `cheap`
フォールバックへ縮退します — ルータの失敗で BFTS ループが死ぬことは
ありません。

v1 のランループ配線: ループはルートのアイデア生成時に
`initial_exploration` をディスパッチし（`generate_root_proposals`。
エージェント起点のルート `generate_ideas` 呼び出しを置き換えます）、展開
方向を観察として記録します。`ProposalRouter.on_event` が他のトリガ
イベントの再アイデア生成面です; ラン途中のイベントは同じ予算の下で候補
レコードを追記しますが、v1 では `ideas[0]` のディレクティブを決して動かし
ません — 再アイデア生成の結果を昇格させることはガバナンスの決定です。

アダプタ自身は MCP 経由で `survey`（トピック → 論文リスト; 失敗時は空
リストへ縮退）を呼び、続いて `generate_ideas` を呼び、
`generate_ideas` ペイロードをアイデアごとに 1 つの `ProposalDraft` へ正規化
します — 読むのはレガシーな 9 つのトップレベルキー
（`virsci_adapter.GENERATE_IDEAS_KEYS`）のみで、これは現在スキルが返す
キー集合の部分集合です。`generate_ideas` の失敗はドラフトゼロ件へ縮退します; ストアでの
コンテンツキー dedup により、このパス全体がリトライの下で冪等です。

## アーカイブ vs サマリ

VirSci の出力は書き込み時に分割されます（「すべて保存し、サマリを見せる」）:

- **チェックポイント以下にアーカイブ** — 完全な `generate_ideas` ペイロード
  （生のアイデアリスト、`gap_analysis`、ジェネレータ設定）は
  `{checkpoint}/proposals/archive/<record_id>/`（`raw_output.json`、
  `generator_config.json`）へ行きます。スキルのオンディスクな
  トランスクリプト成果物 — `{checkpoint}/virsci_logs/virsci_stdout.log` と
  `{checkpoint}/virsci_snapshot/` — はレコードの `archive_refs` で
  *参照*され、決してコピーされません。
- **BFTS が見るもの** — 有界の `ProposalSummaryView` のみ（フィールドごと
  のハードな文字数予算; レンダリングされる expand コンテキストは
  `proposal_router.summary_budget_chars`、デフォルト 6000 で上限されます —
  RQGM 以前の `_build_idea_ctx_for_expand` チャネルとのパリティ）。
  トランスクリプトや議論の内容がサマリフィールドやレンダリング済み
  コンテキストへ入ることは決してありません;
  `test_rqgm_virsci_adapter.py::test_transcript_content_never_reaches_expand_context`
  でピン留めされています。

共有される付加情報は加えて `idea.json` プロジェクションのトップレベル
キーにも乗り、RQGM 以前の `idea.json` 契約を保ちます:
`ProposalRouter._projection_meta` がアーカイブ済みペイロードを読み直し、
レガシーな 5 キー（`gap_analysis`、`papers_analyzed`、`n_agents`、
`discussion_rounds`、`virsci_integration_status`）と、スキルが現在返す
typed contract 系の 10 キー（`typed_schema_version`、`contract_status`、
`survey_snapshot`、`survey_snapshot_digest`、`survey_snapshot_ref`、
`idea_set`、`idea_set_digest`、`research_contract`、
`research_contract_digest`、`rejected_candidates`）のうち、存在するものを
コピーします。

## `enabled: false` のときの保証

デフォルトの `enabled: false` **かつ** typed contract 系のポスチャが
デフォルト（`knowledge.mode: off`、`capability_binding.mode: legacy`、
`assurance.mode: off`）のとき
（すべて `ari-core/tests/test_rqgm_virsci_adapter.py` でピン留め）:

- **アダプタは決して構築されません。** `ProposalRouter._build_generators`
  は、フラグが true かつ MCP クライアントが存在するときにのみ
  `VirSciAdapter` をインスタンス化します
  （`test_mode_virsci_matrix_config_and_boot`）。
- **アダプタモジュールは決してインポートされません。** インポートはその
  条件分岐の内側にあり、モジュールにインポート副作用はありません
  （`test_virsci_disabled_adapter_module_never_imported`）。
- **VirSci ランタイムは決して必要になりません。** アダプタは
  `ari-skill-idea` からも、いかなる VirSci 依存からも何もインポートしません
  （`test_adapter_imports_nothing_from_the_idea_skill`）; テストモジュールは
  一貫して偽の MCP クライアントを使います — VirSci のインストールなし、
  vendored サブモジュールなし、実 LLM 呼び出しなし。
- **評価ハーネスが不在を強制します。** B3（VirSci-off）アブレーション条件
  では、VirSci のプロンプトやトランスクリプトファイルが見えたランを
  `virsci_absence_violations` が fail させます —
  [RQGM 評価](rqgm_evaluation.md)を参照。

これらの保証はデフォルトのポスチャに限られます。`knowledge.mode`、
`capability_binding.mode`、`assurance.mode` のいずれかをデフォルトから
外すと `ProposalRouter._typed_contract_required()` が true になり、ルータは
（MCP クライアントが存在する限り）アダプタを構築し、
`generators.virsci.enabled` が何であれ `virsci` を有効として扱います。

## モード × VirSci の 4 通りの組み合わせ

`proposal_router.generators.virsci.enabled` は `ari.mode` と直交します:
モード解決は `proposal_router.*` を決して読まず、VirSci ゲートは
`ari.mode` を決して読みません。4 通りの組み合わせすべてが有効な設定で
あり、正常にブートします（`test_mode_virsci_matrix_config_and_boot`）:

| `ari.mode` | `virsci.enabled` | 挙動 |
|---|---|---|
| `simple_bfts` | `false` | デフォルト。`proposal_router.*` は不活性; スキル側レバー（`generate_idea` ステージ、`ARI_IDEA_VIRSCI_REAL`）が唯一の VirSci 制御 |
| `simple_bfts` | `true` | 有効な設定だが不活性: `simple_bfts` ではルータが構築されないため、フラグに効果はない。スキル側レバーが引き続き権威 |
| `ari_rqgm` | `false` | typed contract 系のポスチャがデフォルトなら、ルータは `cheap`/`mutation`/`prior_art` のみで走る。VirSci ランタイム、vendored パス、プロンプト、スナップショットコーパスには一切触れない |
| `ari_rqgm` | `true` | `VirSciAdapter` がルーティングテーブルに加わる; エポックごとのキャップの下で `survey` + `generate_ideas` への MCP 呼び出し |

## vendored サブモジュールとスキル

`ari-skill-idea/vendor/virsci` は、**未編集の**アップストリーム VirSci
ソースを保持する git サブモジュールです。vendored された VirSci 機構
（Semantic Scholar スナップショット上の `select_coauthors` /
`generate_idea` 経路）を走らせるのは、スキルのオプトイン `real_wrap`
エンジン（`ARI_IDEA_VIRSCI_REAL=1`）のみです。デフォルトの reimpl
エンジンが借りるのは vendored された議論プロンプトのテンプレート
（`sci_platform/utils/prompt.py`、スキル import 時に読み込み）だけで、
サブモジュールが未チェックアウトならインラインのプロンプトに退避します
— つまりどちらでも走ります; `ari-core` は決してそれをインポートしません。
実際にどちらのエンジンが走ったかは
`generate_ideas` ペイロードの `virsci_integration_status` キーで報告されます
（`"real_wrap"` vs 理由付きの `"reimpl: …"`）— RQGM アダプタは両ステータス
を同一に正規化します。

RQGM 統合は MCP-only なので、`ari-core` はサブモジュールに決して触れません。
これは二重にピン留めされています: アダプタモジュールはスキルもいかなる
VirSci ランタイムもインポートせず
（`test_rqgm_virsci_adapter.py::test_adapter_imports_nothing_from_the_idea_skill`）、
いかなる adversarial モジュールも VirSci をインポートしません
（`test_rqgm_adversarial.py::test_adversarial_package_never_imports_virsci`）。
RQGM のテストモジュールは全面的に偽の MCP クライアントに対して走ります —
サブモジュールが一度もチェックアウトされず、`virsci` pip extra が一度も
インストールされていないマシンでもパスします。

関連: [実行モード](execution_modes.md) ·
[RQGM 移行](rqgm_migration.md) ·
[RQGM 評価](rqgm_evaluation.md) ·
[MCP ツールリファレンス](../reference/mcp_tools.md) ·
[環境変数](../reference/environment_variables.md)
