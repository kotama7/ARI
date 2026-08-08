---
sources:
  - path: ari-core/ari/rqgm/mode.py
    role: implementation
  - path: ari-core/ari/rqgm/state.py
    role: implementation
  - path: ari-core/ari/rqgm/proposals/records.py
    role: implementation
  - path: ari-core/ari/rqgm/proposals/store.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_mode.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_anchor.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/tests/test_rqgm_mode.py
    role: test
  - path: ari-core/tests/test_rqgm_proposals.py
    role: test
  - path: ari-core/tests/test_paper_mode.py
    role: test
last_verified: 2026-07-30
---

# 既存プロジェクトでの `ari_rqgm` 採用

既存の ARI プロジェクトをオプトインの `ari_rqgm` ガバナンスモードへ移行する —
そして戻す — 方法です。モードの意味論そのもの（有効化キー、インターロック
テーブル、カーネル）は[実行モード](execution_modes.md)を、チェックポイント
フォーマットの*リリース*間の移行は[移行ガイド](migration.md)を参照して
ください。このページは同一リリース内でのモード切替を扱います。

## ステップ 0: 移行するものは無い

RQGM 以前の設定はそのまま動き続けます。`simple_bfts` がデフォルトであり、
`ari:`/`rqgm:` ブロックの無い `workflow.yaml`（つまり RQGM 以前のすべての
設定）は RQGM オブジェクトを構築せず、`ari.rqgm` モジュールをインポート
せず、新しいチェックポイントファイルも書きません — デフォルトの
チェックポイントは RQGM 以前の ARI とバイト単位で同一に保たれます。
`simple_bfts` に留まるために必要な設定編集、チェックポイント変換、再実行は
ありません。

互換性の方向は 2 つあります:

- **古いチェックポイント、新しい ari-core**: チェックポイントには
  `rqgm_state.json` がありません; `ari resume` は不在を `simple_bfts` として
  扱います。
- **新しい設定、古い ari-core**: 古い ari-core 上にデプロイされた `rqgm:`
  ブロックは黙って無視されます（最も安全な失敗方向）。

## 任意のステージ 1: record-only デュアルライト (B1)

モードを切り替える前に、挙動変更ゼロで提案レコードストアを試すことが
できます:

```yaml
proposal_router:
  record_only: true    # honored in simple_bfts; default false
```

`record_only` は `simple_bfts` 下で唯一尊重される `proposal_router.*`
キーです。これを設定すると、エージェントループの `idea.json` 出力が追加で
`{checkpoint}/proposals/proposal_records.jsonl` に `legacy_idea_json`
レコードとしてインポートされます（`ideas[0]` — 現在のディレクティブ — は
`selected`、残りは `candidate`; `simple_bfts` にはエポックが無いため
`epoch_id: null`）。`idea.json` 自体は書き換え**られず**、コンシューマの
変更もなく、コンテンツキーによる dedup が繰り返しのインポートを冪等に
します。これが[評価はしご](rqgm_evaluation.md)の B1 段です。ロールバック =
フラグの削除; 残されたレコードは不活性です
（`test_rqgm_proposals.py::test_simple_bfts_record_only_dual_writes`）。

## 新規ランを `ari_rqgm` へ切り替える

```yaml
# workflow.yaml (or --config)
ari:
  mode: ari_rqgm
rqgm:
  enabled: true
```

または、ラン単位かつ GUI 互換の `ARI_MODE=ari_rqgm ARI_RQGM_ENABLED=1`。
両方のキーが一致している必要があります
（[インターロックテーブル](execution_modes.md#turning-rqgm-on)）。

実効モードは**ラン開始時に一度だけ**解決され、最初のノードが走る前に
`{checkpoint}/rqgm_state.json` へ永続化されます。このファイルがランの
モード来歴です; その不在は純粋な `simple_bfts` ランを意味します。

**resume は決してアップグレードしません。** `ari resume` は
`ari.rqgm.state.reconcile_resume_mode` を通じて、チェックポイント優先で
突き合わせます:

- `rqgm_state.json` の**無い**チェックポイントは `simple_bfts` として開始
  されたのであり、`simple_bfts` のままです — resume 時に
  `ari.mode: ari_rqgm`（または環境変数）を要求すると警告がログされ、要求は
  無視されます; `simple_bfts` ループには合法なラン途中アップグレード
  ポイントが存在しません。
- `rqgm_state.json` の**ある**チェックポイント: 永続化されたモードが
  パッケージ設定と env に優先します。不一致は警告を生みますが、ラン途中の
  モード反転は決して起こしません。

したがって既存プロジェクトのアップグレードは、**新しいラン**（または
`ARI_MODE=ari_rqgm` で開始した子ラン）を起動することを意味します —
通常は既存の `inherit_idea_index` / ピン留め `idea.json` 機構で前のランの
方向性を継承し、RQGM はそれをルートのアイデア生成時に `legacy_idea_json`
レコードとしてインポートします。

## `idea.json` ↔ ProposalRecord の互換性

RQGM は `idea.json` を置き換えません; 提案レコードストア
（`ari/rqgm/proposals/store.py`）の**プロジェクション**へと格下げします:

- **9 キー契約は保持されます。** 投影されるドキュメントは、既存のすべての
  コンシューマが読むトップレベルキーを常に保ちます: `gap_analysis`、
  `ideas`、`primary_metric`、`higher_is_better`、`metric_rationale`、
  `papers_analyzed`、`n_agents`、`discussion_rounds`、
  `virsci_integration_status`（`ari.rqgm.proposals.store.IDEA_JSON_KEYS`;
  `test_rqgm_proposals.py::test_projection_nine_key_contract_and_plan_parse`
  でピン留め）。
- **単一の書き込み手。** `ari_rqgm` ではストアが `idea.json` の唯一の
  書き込み手であり、常に単一の関数（`build_idea_projection`）を通じて
  レコードから導出します。`_pinned` / `_inherited_from` / `_root_choice`
  のワンショットマーカーは書き換えをまたいで逐語的に保持されるため、
  ラン間継承とルート選択は動き続けます。
- **トレーサビリティ。** 投影された各 `ideas[i]` エントリはアンダースコア
  キー `_proposal_record_id` を持ち、`proposals/proposal_records.jsonl` へ
  リンクバックします（`_pinned` / `_inherited_from` と同じ規約）。
- **型付きハンドオフはタイトル一致で通過します。** 選ばれたジェネレータが
  型付き research-contract ドキュメントを出力していた場合、プロジェクションは
  その 10 個の typed-handoff キー — `typed_schema_version`、
  `contract_status`、`survey_snapshot`（`_digest`/`_ref`）、`idea_set`
  （`_digest`）、`research_contract`（`_digest`）、`rejected_candidates` —
  も併せて運びます。つまり上の 9 キーは下限であって上限ではありません。
  コピーはコントラクトの `title` がディレクティブ `ideas[0].title` と一致
  するときに**のみ**行われるため、型付きブロックが `idea.json` の指す方向とは
  別の方向を記述してしまうことはありません。
- **逆写像。** 既存の `idea.json` の内容（ピン留めされたシード、または上の
  ステージ 1 デュアルライト）は、レガシーチャネルに乗り続けられる程度に
  損失なくインポートされます: `summary_from_idea` は、レガシーパスが使うの
  と同じ `_extract_plan_sections` パーサで、結合された `experiment_plan` を
  有界のステップへ分割し直します。

## 新しいチェックポイントファイル

`ari_rqgm` ランは以下を追加します。新しいチェックポイントルート直下の
ファイル名は `PathManager.META_FILES`（`ari/paths.py`）に登録されるため、
ARI はそれらをランメタデータとして分類し — ノード作業ディレクトリへ決して
コピーせず — `proposals/` サブツリーはさらにノードファイルレポートから
ブロックリストされます（`test_rqgm_proposals.py::test_proposal_filenames_registered` /
`test_proposals_never_in_files_changed` でピン留め）。サブディレクトリの中身
（`proposals/archive/`、`rqgm_prompts/`、`rqgm/kca/admission-v1/`）は名前登録
されていませんが、その必要もありません — このコピーはチェックポイント
ルート直下のファイルしか走査しないためです。**`simple_bfts` ランは
これらを一切書きません** — 唯一の例外は `proposals/` で、上の `record_only`
にオプトインした場合に限り `simple_bfts` でも現れます。

| パス（`{checkpoint}/` 以下） | 内容 |
|---|---|
| `rqgm_state.json` | モード来歴: mode、interlock、`mode_source`、switch journal。不在 == 純粋な `simple_bfts` ラン |
| `constitution.yaml` | copy-once、非進化の人間可読な憲法声明 |
| `rqgm_transitions.jsonl`、`rqgm_audit.jsonl` | append-only のイベントログ真実 + ガバナンス監査ログ |
| `epoch_state.json`、`rqgm_registry.json` | 導出スナップショット: 現在のエポック凍結とコンポーネント / プロンプトレジストリ |
| `proposals/`（`proposal_records.jsonl`、`proposal_index.json`、`archive/…`） | 提案レコードの真実 + 導出インデックス + 生出力アーカイブ |
| `rqgm_adversarial_cases.jsonl`、`rqgm/adversarial_replay_pool.json` | 敵対ループレコードの真実 + 導出されたリプレイプールスナップショット |
| `prompt_evolution.jsonl`、`prompt_specs.json`、`rqgm_prompts/` | プロンプト進化レコードの真実、PromptSpec ロールアップ、進化済みテンプレート本文 |
| `rqgm_cleanroom.jsonl` | クリーンルーム再生成の要求 / スクリーン / フォールバックイベント |
| `rqgm_erasure_state.json` | 選択的消去による stale/invalid 集合の導出ロールアップ |
| `rqgm_meta_outputs.jsonl` | メタエージェント出力レコード |
| `rqgm_governance_cache.jsonl` | ガバナンス結果キャッシュ |
| `rqgm/kca/admission-v1/`（`run_admission.json` とピン留めされたコントラクト / カタログ / ロック一式） | Knowledge–Capability–Assurance のラン受理ベースライン。`knowledge` / `capability_binding` / `assurance` の各モードがレガシー不活性な既定値（`off` / `legacy` / `off`）から外れたときだけ書かれる。ディレクトリの rename で公開されるため、中断された受理が「権威ある状態」と誤認される部分集合を残すことはない |
| `rqgm_eval_metrics.json`、`rqgm_injection_provenance.json` | 評価ハーネス専用 — 通常のランでは決して書かれない |

## ロールバック

戻すことは、次のランを `simple_bfts` として開始すること（または `ari_rqgm`
ランにエポック境界で自らダウングレードさせること — 唯一のラン内切替で、
ダウングレードのみ）を意味します。ロールバックを安全にする性質が 2 つ
あります:

- **レコードは不活性です。** `simple_bfts` のコードは `proposals/` や
  いかなる `rqgm_*` ファイルも決して読まないため、古いチェックポイントに
  残った RQGM 成果物はクリーンアップ不要で、何も変えません。不在ゲートは
  構造的です: `ari.core.build_runtime` 内の遅延インポートが唯一のスイッチ
  であり、機能ごとのフラグではありません。
- **かつて消去されたノードは除外されたままです。** 選択的消去は論理のみ —
  何も削除されません; staleness は監査ログ、`rqgm_erasure_state.json`
  ロールアップ、および `tree.json` を通じて永続化される追加的な
  `Node.metrics` センチネル（`_stale`、`_valid_for_frontier`、…）に
  存在します。`BFTS.should_prune` と `verified_context.select_best_node` は
  `metrics['_valid_for_frontier'] is False` を**無条件に**読むため、
  `ari_rqgm` 下で消去されたノードはモードを戻した後も枝刈りされ、
  ベストノード選択からも除外されたままです —
  汚染はモード切替によって清浄にはなりません。このセンチネルキーを書くのは
  RQGM の機構（`ari_rqgm` の `FrontierRepairEngine`、`RQGMRuntime` の KCA
  整合性チェック — こちらはノードに `assurance_status: tampered` /
  `frontier_class: uncertified_frontier` も付けます —、または `rqgm_archive`
  の paper ランタイム）だけなので、RQGM を一度も走らせて
  いないチェックポイントではこの節は不活性なデッドコードです
  （`_sterile` パターン）。

## `paper.mode` の採用

論文執筆フェーズ（`ari paper`）は独自のオプトイン軸 `paper.mode:
linear | rqgm_archive` を持ち、`ari.rqgm.paper_mode.resolve_paper_mode` で
解決され、**`ari.mode` から独立**しています — 探索に触れずに論文アーカイブを
採用することも、古典的な linear 論文ライタでエポックガバナンスを走らせる
こともできます。`linear`（デフォルト）は現行の論文パイプラインとバイト単位で
同一です; `{checkpoint}/paper_archive_state.json` が存在しないことは純粋な
linear 論文ランを意味します。両方のキーを一致させてアーカイブを有効化します:

```yaml
# workflow.yaml
paper:
  mode: rqgm_archive
rqgm:
  paper:
    enabled: true
```

またはラン単位で `ARI_PAPER_MODE=rqgm_archive ARI_RQGM_PAPER_ENABLED=1`
（`ari paper` コマンドが `apply_paper_env_overrides` 経由で適用します）。
[インターロックテーブル](execution_modes.md#turning-the-paper-archive-on)を
参照してください。モードは `paper_archive_state.json` へ write-once で
永続化され、`ari paper` の再起動はチェックポイント優先で突き合わせます
（`reconcile_paper_resume_mode`）— 永続化された論文モードが設定と env に
優先し、これは探索の `rqgm_state.json` と全く同じです。

### デフォルトは縮退した on-ramp

`rqgm_archive` を有効にしても、完全な共進化ループがすぐに得られるわけでは
**ありません**。2 つのノブがそれをゲートしており、どちらも保守的に始まります:

- **アンカーはデフォルトでオフ**（`rqgm.paper.anchor.enabled: false`）です。
  アンカーが無いとレビュアは信頼を得るためのグラウンドトゥルースを持たない
  ため、デフォルトの `rqgm_archive` は **reviewed best-of-N**（単一の凍結
  レビュアが採点する best-first ドラフトアーカイブ）です。レビュアを共進化
  させるには、curated な APReS 相当の accept/reject コーパスを供給して有効化
  します:

  ```yaml
  rqgm:
    paper:
      anchor:
        enabled: true
        corpus_path: paper_anchor_corpus.jsonl   # チェックポイントからの相対パス
  ```

  各コーパスケースは `label_source`（`human_curated` | `gate_bootstrap`）を
  宣言する必要があります; 機械的に強制される `max_bootstrap_label_fraction`
  上限（デフォルト 0.5、コーパス全体**と**保留部分集合に適用）は、自己生成
  された `gate_bootstrap` ラベルに寄りすぎたコーパスを拒否します。違反時 —
  あるいは欠落 / 空 / 汚染されたコーパス — ではローダは「アンカーゲートなし」
  へ縮退し、**決して例外を投げません**
  （`ari/rqgm/paper_anchor.py:load_anchor_corpus`）。アンカーしないことは、
  自己ラベルにアンカーするより厳密に安全です。

- **デフォルトのエポック数は意図的に安価**（`rqgm.paper.epoch.rounds: 2`）
  です。2 ラウンドでは境界と（常に甘いレビュアの下では）弾劾動議は発火
  しますが、`candidate → validated → shadow → probationary_active` の登攀には
  ロールの空きと約 5 境界が必要なため、**完全なレビュア採用は完了しません**
  — アクティブレビュアハッシュは変わりません。完了した採用を目撃する必要が
  あるランは `rounds` を上げます（共進化 PROOF は 8 を駆動します）。

最も安価な姿勢は `rqgm.paper.prompt_evolution.enabled: false` で、候補生成を
完全に抑制します: ロールは設立時の v1 プロンプトに固定され、現行相当の
コストで reviewed best-of-N が得られます。

### 新しい論文アーカイブのチェックポイントファイル

実効 `rqgm_archive` の論文ランは `{checkpoint}/` 以下に以下を追加します:

| パス | 内容 |
|---|---|
| `paper_archive_state.json` | 論文モード来歴: 論文モード、interlock、`mode_source`、探索モード、シードノード。シードは**最初の**起動時の値を記録し、後続の起動が別のシードを算出した場合は上書きせず `seed_journal` に `seed_changed` エントリを追記します（`journal_seed_change`）。不在 == linear 論文フェーズ |
| `paper_draft_archive.jsonl` | 採点済みドラフト集団（ドラフトノードごとに 1 レコード: framing、レビュアスコア、tex ハッシュ、best-belief/compiled フラグ） |
| `paper_anchor_corpus.jsonl` | accept/reject アンカーコーパス。供給した場合のみ（読み取り専用; ガバナンス下のロールが著すことはない） |
| `rqgm/paper_self_preference_stat.json` | `paper_self_preference` アドバーサリが pre-signal として引用する、決定論的な AI 対 human の self-preference マージン |

`linear` の論文ランはこれらを一切書きません。共進化はさらに、探索と同じ
`rqgm_transitions.jsonl` / `rqgm_registry.json` / `prompt_evolution.jsonl`
ファイルに乗ります — 論文ロールは同じ内部 RQGM ランタイムを通じてガバナンス
されるためです。

### 論文アーカイブのロールバック

次の `ari paper` で `paper.mode: linear` を設定（または `rqgm.paper.enabled`
を外す）します; linear パイプラインはバイト単位で同一で、残った `paper_*`
ファイルは不活性です — `linear` のコードはそれらを決して読みません。

### 正直な限界

- **両方のプロンプトが共進化します — ただしライタは退行したときだけ。**
  `paper_writer` プロンプトは、Layer-0 の claim-evidence ゲートの決定論的な
  忠実性にアンカーされ、通常の sanction → ロール開放 → T6 のパスを通じて
  共進化します。ただしライタの後継は、現職がその忠実性で退行するまで
  `shadow` に留まります: 優れた挑戦者だけでは忠実な現職を置き換えません。
  ライタの*ドラフト*勝者は引き続きエポックローカルです（エポック内で凍結
  された reviewer が順位付け）。
- **ライタへの制裁はレビュアのラウンドに相乗りします。** ライタをターゲット
  とする validated attack は `paper_self_preference` ラウンドが発行し、その
  ラウンドは過剰受理のアンカーケースがあるときにのみ発火します; 専用の
  ライタ adversary タイプは別の判断です。
- アンカーはデフォルトでオフであり — ライタの忠実性ケースもアンカープールへ
  landed されるため、これはライタにも効きます — デフォルトの `rounds: 2` は
  採用を完了しません（上記）。最初の `rqgm_archive` 採用は段階的ロールアウトで
  あって、フラグ 1 つの切替ではありません。

## 制限事項 (v1)

[実行モード → 制限事項](execution_modes.md#limitations-v1)と同じです:
プロファイル（`--profile`）は RQGM キーをマージせず、`--mode` CLI フラグは
ありません。論文軸もこれを共有します: `--paper-mode` フラグはなく、
プロファイルは `rqgm.paper.*` をマージしません。ダッシュボードは**新規**ラン
についてのみ両方のモード組を選択できます（[実行モード → GUI からモードを
選択する](execution_modes.md#gui-からモードを選択する)）; このページのそれ
以外の `rqgm.*` パラメータは設定ファイル専用であり、既に開始したランの
モードを変更できるサーフェスは存在しません。

関連: [実行モード](execution_modes.md) ·
[VirSci 統合](virsci_integration.md) ·
[RQGM 評価](rqgm_evaluation.md) ·
[ファイルフォーマットリファレンス](../reference/file_formats.md)
