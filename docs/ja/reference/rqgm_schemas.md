---
sources:
  - path: ari-core/ari/schemas
    role: schema
  - path: ari-core/ari/rqgm
    role: implementation
  - path: ari-core/ari/checkpoint.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/tests/test_rqgm_state_store.py
    role: test
last_verified: 2026-07-28
---

# RQGM スキーマリファレンス

オプトインの `ari_rqgm` 実行モードが永続化するすべてのレコードの正式な
JSON Schema です。すべて `ari-core/ari/schemas/` 以下に同梱され、
`ari.schemas.load(name)` によりベース名でロードされます。これらのレコードは
デフォルトの `simple_bfts` チェックポイントには一切存在しません — すべての
読み取り側は不在を「RQGM は一度も走っていない」として扱います。

このページが文書化するのは**レコードの形**（目的、所有モジュール、主要
フィールド、id / ハッシュの規律）です。これらのレコードが入るチェックポイント
**ファイル** — 生成条件、真実源と導出スナップショットの関係、resume の
意味論 — は[ファイルフォーマットリファレンス](file_formats.md)を参照して
ください; ページ末尾の[インベントリテーブル](#checkpoint-file-inventory)が
各ファイルをスキーマへ対応付けます。設定キーは
[設定 → 実行モードと RQGM](configuration.md#execution-mode-and-rqgm-governance-opt-in)、
モードの意味論は[実行モード](../guides/execution_modes.md)を参照してください。

## Id とハッシュの規律

すべての RQGM の id とハッシュ形式は 1 つのモジュールが所有します:
`ari-core/ari/rqgm/events.py`（RQGM Task 02）。すべてのハッシュ計算は設計
原則 P2（決定論）に従います: 壁時計、git SHA、ホスト名、絶対パスがハッシュに
入ることは決してありません。

- **`canonical_json(payload)`** — すべての RQGM ハッシュが計算される単一の
  正準 JSON 形: ソート済みキー、空白なし、`ensure_ascii=False`
  （テストでバイト単位にピン留め）。
- **`hash12`** — `sha256(text)[:12]`。`ari.prompts._provenance.hash12`
  （まさに `FilesystemPromptLoader.load_versioned` のプロンプト来歴
  スキーム; 第二のスキームは存在しません）をそのまま再利用。
  スキーマパターン: `^[0-9a-f]{12}$`。
- **`sha256_hex`** — 完全な 64 桁 hex ダイジェスト。完全なハッシュが重要な
  箇所で使用（`prompt_sha256` / `full_sha256`、`inputs_sha256`、
  ガバナンスキャッシュのコンテンツハッシュ）。
- **`payload_hash(payload)`** = `hash12(canonical_json(payload))` —
  指示文、効用規則、台帳、および旧版の出来事で使う短い内容識別子。
- **出来事形式 v2 のダイジェスト** — 正規化した
  `{schema_version, event_id, event_type, transaction_id, payload,
  prev_event_hash}` 全体の SHA-256。再生の意味を変える全項目を結び、
  時刻だけは対象外とする。
- **期の識別**（`ari/rqgm/state.py`）—
  `policy_fingerprint` は稼働制度と解決済み統治設定、
  `execution_fingerprint` は宣言済みモデル、復号、道具、環境、データ
  標本を要約し、`epoch_fingerprint` が両者を合成します。`created_at`、
  `status`、総合指紋自身を除くため、open→closed で凍結内容は変わりません。

Id 形式（すべてゼロ埋め、チェックポイントごとのカウンタ）:

| 形式 | 生成元 | 例 |
|---|---|---|
| `epoch_%03d` | エポックカウンタ。`epoch_000` から開始 | `epoch_004` |
| `transition_%03d_to_%03d` | エポック境界の遷移 id | `transition_003_to_004` |
| `evt_%06d` | イベントログの行カウンタ。`evt_000000` から開始 | `evt_000042` |
| `{role}_v{N}` | コンポーネント id | `reviewer_v3` |
| `{role}_prompt_v{N}` | プロンプト id | `reviewer_prompt_v4` |
| `epochstate_{epoch_id}` | `epoch_state.json` のレコード id | `epochstate_epoch_004` |
| `prop_%06d` | ProposalRecord | `prop_000031` |
| `atk_` / `def_` / `jdg_` / `vat_` / `utl_%06d` | 敵対ループのレコード | `atk_000007` |
| `adv_case_%05d` | AdversarialReplayCase | `adv_case_00003` |
| `pcand_` / `pval_` / `cobs_%05d` | プロンプト進化のレコード | `pcand_00002` |
| `upc_%06d` | UtilityPolicyCandidate（Task 14） | `upc_000004` |
| `erase_` / `rebuild_%05d` | 消去 / 再構築イベント | `erase_00007` |
| `meta_out_` + hash12 | MetaAgentOutputRecord | `meta_out_a1b2c3d4e5f6` |
| 16 桁 hex の `cache_key` | ガバナンスキャッシュ（下記参照） | `a3f19c02b7d4e881` |

## 共有エンベロープ (`rqgm_defs.schema.json`)

**目的:** すべての RQGM レコードスキーマが参照する正準の共有 `$defs` —
`rqgm_record_base` エンベロープ、閉じたステータス / ロール / ティア語彙、
id / ハッシュ形式。**所有モジュール:** `ari/rqgm/events.py`（語彙の Python
ミラー）。他のスキーマファイルに埋め込まれたこれら `$defs` のコピーは、
`ari-core/tests/test_rqgm_state_store.py` によってこのファイルとバイト等価に
ピン留めされています。

すべてのガバナンスレコードは 8 個の必須 `rqgm_record_base` フィールドを
持ちます（ここに**一度だけ**記載します; 以下の各スキーマの表はレコード固有の
フィールドのみを列挙します）:

| エンベロープフィールド | 意味 |
|---|---|
| `record_id` | 型付きのゼロ埋め id（上記の形式） |
| `epoch_id` | レコードが生成された `epoch_%03d` |
| `component_id` | 生成コンポーネント（`{role}_v{N}` または固定エンジン名） |
| `prompt_hash` | 生成プロンプトの `hash12`; カーネル / エンジン作のレコードでは `null` |
| `role` | 下記の閉じたロール語彙のいずれか |
| `created_at` | ISO タイムスタンプ — メタデータのみ、決してハッシュされない |
| `source_refs` | 入力へのチェックポイント相対参照 |
| `status` | レコード固有のステータス語彙 |

閉じた語彙:

- **ステータスライフサイクル**（プロンプトとコンポーネントで共有; 合法な
  遷移は `ari/rqgm/transition_rules.py` の T1–T21 テーブル）:
  `candidate → validated → shadow → probationary_active → active`、次いで
  `active → warning | probation | quarantine`、そして
  `quarantine → retired → banned`。`active` と `probationary_active` が
  エポックごとの凍結されたアクティブ集合を構成します。
- **ロール** — 進化可能: `generator`、`reviewer`、`adversary`、`defender`、
  `judge`、`router`、`prompt_mutator`、`clean_room_generator`、
  `replay_selector`、`failure_summary_compressor`、`policy_mutator` と
  `utility_policy`（RQGM Task 14 — governed なスコアとその提案者）、
  `paper_writer` と `paper_reviewer`（paper-archive; 実効的な
  `rqgm_archive` paper モードでのみ登録されるため、探索ブートはバイト
  同一）; 固定（来歴のために登録、憲法上不変）: `constitutional_kernel`、
  `fixed_verifier`、`audit_log`。
- **ティア**: `fixed`、`institutional`、`meta`。

## 状態とイベントログのスキーマ (Task 02)

### `rqgm_transition_event.schema.json`

**目的:** `rqgm_transitions.jsonl` の — そして独立したファイル単位チェーンを
持つ `rqgm_audit.jsonl` の — ハッシュ連鎖・append-only な行エンベロープ。
**所有モジュール:** `ari/rqgm/events.py`（`TransitionEvent` /
`finalize_event`）; 永続化は `ari/rqgm/store.py`。

| フィールド | 備考 |
|---|---|
| `schema_version` | 新規出来事は `2`。旧版 `1` も読出し可能 |
| `event_id` | `evt_%06d`。チェックポイント単位で単調増加 |
| `event_type` | 閉集合: `epoch_transaction_prepare`、`component_registered`、`prompt_registered`、`component_status_change`、`prompt_status_change`、`epoch_close`、`epoch_open`、`epoch_transaction_commit`、`emergency_quarantine` |
| `transaction_id` | 境界取引への所属。独立した期開始・監査出来事だけ空 |
| `payload` | 出来事の内容 |
| `event_hash` | v2 は出来事全体の SHA-256。v1 は内容だけの 12 桁ハッシュ |
| `prev_event_hash` | v2 のダイジェストに含む。最初の行では `""` |
| `ts` / `ts_iso` | エンベロープメタデータ。ハッシュの外側 (P2) |

### `epoch_state.schema.json`

**目的:** 現在開いている（または最後に閉じた）エポックの導出された
`epoch_state.json` ロールアップ。`rqgm_transitions.jsonl` が真実源であり、
スナップショットは使い捨てで、不一致時にはリプレイから再構築されます。
**所有モジュール:** `ari/rqgm/state.py`（`EpochState`、
`epoch_state_payload`、`epoch_fingerprint`）; 永続化は
`ari.checkpoint.save_epoch_state_json` 経由。

| フィールド | 備考 |
|---|---|
| `record_id` | `epochstate_epoch_%03d` |
| `epoch_id` / `epoch_seq` / `previous_epoch_id` / `opened_by_transition_id` | エポックチェーン上の位置 |
| `status` | `open` \| `closed` |
| `run_id` / `node_count_at_open` | ランへのリンク + 境界の帳簿 |
| `active_components` / `active_prompt_hashes` / `utility_policy` | エポックごとの凍結集合（freeze 時にコピー; グローバル不変条件 1–3）。`utility_policy` は **governed なスコア本体** — `composite`、`axis_weights`、`frontier_score`、`depth_penalty_lambda`、`ucb_c` に封印済みの `utility_policy_hash` を加えたもの — で、`ari/rqgm/state.py:capture_utility_policy` が採用済みポリシーから取得する（エポック 0 / `simple_bfts` では cfg にフォールバック）。[governed ユーティリティ進化スキーマ](#governed-utility-evolution-schema-task-14)を参照 |
| `registry_version` | freeze 時点のレジストリの `hash12` |
| `policy_settings` / `policy_fingerprint` | 憲法、しきい値、予算、統治設定と、その12桁要約値 |
| `execution_identity` / `execution_fingerprint` | 宣言済みモデル・接続先・温度、探索・評価設定、技能、無効道具、モデル・道具・環境・データの固定値。不明な固定値は `unresolved`、`complete: false` |
| `epoch_fingerprint` | 政策と実行識別を合成した12桁要約値。`created_at`、`status`、自身を除く |
| `created_at` | メタデータ; フィンガープリントから除外 |

### `rqgm_registry.schema.json`

**目的:** ComponentRegistry + PromptRegistry を 1 ファイルにまとめた導出
`rqgm_registry.json` ロールアップ。両者がディスク上でトランザクショナルに
一貫し続けるためです; 真実はイベントログです。**所有モジュール:**
`ari/rqgm/registry.py`（クラス `GovernedPromptRegistry`; オンディスク名は
`PromptRegistry` のまま）; 永続化は `ari.checkpoint.save_rqgm_registry_json`
経由。

| フィールド | 備考 |
|---|---|
| `registry_version` | `hash12` |
| `as_of_event_hash` | 最後に fold されたイベントの `event_hash`（空のときは `""`） |
| `components[]` | コンポーネントエントリ（status、role、tier; メタティアのエントリは `rqgm_meta` capability フラグを追加） |
| `prompts[]` | プロンプトエントリ: テキストはソース参照（現在は `committed_template` キー; 進化済みプロンプトは `checkpoint_file`）、`prompt_hash`（`hash12`）**と**完全な `prompt_sha256` の両方; `spec_ref` は v1 では `null` |

## 提案スキーマ (Task 03)

### `proposal_record.schema.json`

**目的:** `proposals/proposal_records.jsonl` の 1 行 — append-only な提案の
真実（「すべて保存し、BFTS にはサマリだけ渡す」）。**所有モジュール:**
`ari/rqgm/proposals/records.py`（dataclass 群）+
`ari/rqgm/proposals/store.py`（永続化、dedup、`idea.json` プロジェクション）。

| フィールド | 備考 |
|---|---|
| `record_id` | `prop_%06d` |
| `epoch_id` | `simple_bfts` の record-only モードでは `null` |
| `role` | const `generator` |
| `generator` | `cheap` \| `mutation` \| `attack_driven` \| `prior_art` \| `virsci` \| `legacy_idea_json` |
| `prompt_hash` | レガシーインポートでは `null` |
| `status` | `candidate` \| `selected` \| `expanded` \| `superseded` |
| `stale` / `valid_for_frontier` | 論理のみのフラグ; 読み取り時の意味論は frontier repair（Task 10）が所有し、保存済み行は決して書き換えられない |
| `source_refs` | エンベロープの文字列配列から逸脱: オブジェクト（`node_id`、`parent_node_id`、`parent_proposal_id`、`dispatch_head`、...） |
| `summary` | インラインの有界 `ProposalSummaryView` — BFTS が見る唯一の形 |
| `archive_refs` | `proposals/archive/<record_id>/` へのチェックポイント相対参照（`raw_output`、`transcript`、`discussion_log`、`retrieval_snapshot`、`generator_config`、...）。決してコピーではない |
| `idea_projection` | 維持される `idea.json` 互換プロジェクションのための `{projected, idea_index}` 帳簿 |

### `proposal_summary_view.schema.json`

**目的:** 有界の提案サマリ — BFTS が消費してよい**唯一の**提案表現;
完全な VirSci トランスクリプトはアーカイブ専用で、ハードな文字数予算には
収まりません。**所有モジュール:** `ari/rqgm/proposals/records.py`。必須
フィールド: `proposal_record_id`、`title`、`short_description`、
`hypothesis`、`experiment_plan[]`、`success_metric`、`novelty_risks[]`、
`expected_artifacts[]`、`dissent_summary`、`scores`。`schema_version` は
それを包む ProposalRecord 側にあります; 進化は追加のみです。

## ガバナンススキーマ (Task 05)

### `governance_report.schema.json`

**目的:** `GovernanceOrchestrator.audit_epoch` の単一の戻り型で、
`governance_report` レコードとして `rqgm_audit.jsonl` に追記されます —
あるエポックの最新レポートは、その `epoch_id` を持つ*最後の*行です。
**所有モジュール:** `ari/rqgm/governance/`（`_records.py` ビルダ、
`_pipeline.py` オーケストレーション）。

| フィールド | 備考 |
|---|---|
| `component_id` / `role` | const `governance_orchestrator` / `governance` |
| `status` | const 相当の enum `final` |
| `governance_level` / `degraded` / `degradation_reasons` | 監査の予算 / 縮退の姿勢 |
| `reliability` / `observations` / `evidence_bundles` | コンポーネント別の信頼性入力（evidence bundle は EvidenceClerk 作） |
| `impeachment_motions` / `defenses` / `adjudications` | 動議パイプライン（動議は Auditor 限定; 同一ロールの告発は拒否） |
| `candidate_evaluations` | RegistryTransitionEngine に供給されるリプレイ / アンカーのスコア |
| `replay_pool_updates` / `self_audit` / `bond_accounting` / `budget_usage` | 境界の帳簿 |
| `recommendations[]` | `action` は閉じた集合 `promote_candidate` \| `promote` \| `demote` \| `warn` \| `quarantine` \| `retire` \| `no_action`。Task 09 が消費 |

## 敵対ループスキーマ (Task 06)

### `rqgm_attack_records.schema.json`

**目的:** `rqgm_adversarial_cases.jsonl`（および、ガバナンス証拠として
監査ログ）に多重化される 4 つの攻撃ループレコード形。**所有モジュール:**
`ari/rqgm/adversarial/records.py`（形 + 構成的予防のビルダ）、
`ari/rqgm/adversarial/round.py`（ノード単位のラウンド）。

| レコード (`record_type`) | Id / ロール | 固有フィールド |
|---|---|---|
| `raw_attack` | `atk_%06d` / `adversary` | `adversary_type`（同梱スキーマの enum は閉じた 7 タイプの**探索**集合: `overclaim`、`metric_gaming`、`prior_art`、`reproducibility`、`evidence_gap`、`cost_explosion`、`prompt_injection`; paper フェーズは 8 番目の `paper_self_preference` を追加 — [paper-archive スキーマ](#paper-archive-schemas-paper-rqgm_archive-mode)を参照）; `target_artifact.type`（閉じた集合: `proposal`、`experiment_plan`、`node_report`、`metric_result`、`paper_claim`、`novelty_claim`、`citation_claim`、`reproducibility_claim` — 決してコンポーネントではない）; `attack_claim`; `attack_evidence_refs`（1 個以上必須）; `severity_claimed`。監査資料のみ — 生の攻撃はスコアに決して触れない（不変条件 8） |
| `defender_response` | `def_%06d` / `defender` | `raw_attack_id`; `stance` は `rebut` \| `concede` \| `propose_fix` |
| `judgment_record` | `jdg_%06d` / `judge` | `raw_attack_id`; `verdict` は `valid` \| `partially_valid` \| `invalid`; ジャッジが割り当てる `severity`（`low`–`critical`）; `defense_status`。`invalid` でも常に書かれる |
| `validated_attack` | `vat_%06d` / `judge` | `case_type`、`raw_attack_id`、`judgment_id`、`validated`、`verdict`、`severity`。`valid` / `partially_valid` 判定に対して**のみ**存在（裁定必須、不変条件 9）。説明責任バインディングを保持 — 下記参照 |

#### `validated_attack` の説明責任バインディング

ロールは**観測される**もの、コンポーネントは**拘束される**もの、そして
バインディングは**裁定の後にのみ**鋳造される。`validated_attack` の 2 つの
ターゲット様フィールドは同義語ではない:

| フィールド | 値空間 | 読み手 |
|---|---|---|
| `affected_components` | ロール名（`["reviewer"]`）— 誰が関与しているかという複数形の観測。ロールは攻撃が正直に知りうる唯一のものであり、ロールを制裁するものは何もない。（この名前はロールを保持する。改名すれば保存済みの全レコードを書き換えることになるため、そのまま維持している） |  FailureSummary の `affected_roles` |
| `target_component_id` | レジストリで解決可能な**単一の**コンポーネント id（`"reviewer_v3"`）— その攻撃が無効化した判断を下した現職 | `ReliabilityMonitor.validated_attack_involvement`、`EvidenceClerk` のターゲット選択 ⇒ 弾劾チェーン全体 |

`target_component_id` は**任意であり、存在するか不在かのいずれかで、決して
「存在して空」にはならない**（`minLength: 1`）: 空のターゲットはターゲット
ではなく、誰も名指ししないレコードは何も語らない — したがって誰も拘束しない
レコードはバインディング導入前とバイト同一であり、マイグレーションを要しない。
これはレコード構築時に、関与ロールから**エポックで凍結された**アクティブ
コンポーネント集合に対して解決される。ライブなレジストリ読み取りは決して
行わない（境界での採用後にライブ読み取りを行うと、前任者の欠陥で後継者を
弾劾してしまう）。また著者に対しても決して拘束しない: 自らのジャッジを拘束
するレコードは拒否される（ロール分離 — 同一レコードで裁定しかつ制裁される
アクターは存在し得ない）。

これはアーティファクト限定ターゲティングを弱めない。アドバーサリは依然として
アーティファクトのみを攻撃する。バインディングは裁定後のジャッジ著作レコード
上にのみ存在する。アドバーサリは観測し、観測を説明責任あるものにするのは
ジャッジの判定である。

探索（`ari_rqgm`）側では、研究 `generator` は設立時の登録コンポーネントです。
ノードには生成コンポーネント、プロンプトハッシュ、エポックを一度だけ付与
します。7 つのアドバーサリタイプは、その来歴がエポック凍結済み現職と一致
する場合だけ `generator_v1` へ結びます。古い記録、欠落、不一致は対象なし
とし、前任の成果物で後継を制裁しません。

### `rqgm_utility_record.schema.json`

**目的:** governed-utility の監査レコード 1 件; §5.4 のペナルティチャネルが
v1 における唯一の発行者で、frontier repair（Task 10）が消去後に再計算済み
レコードを再発行します。**所有モジュール:**
`ari/rqgm/adversarial/records.py`（発行）+ `ari/rqgm/frontier_repair.py`
（再計算）。

| フィールド | 備考 |
|---|---|
| `record_id` | `utl_%06d` |
| `role` | const `utility_policy` |
| `node_id` / `base_score` / `penalty` / `final_score` | ノードごとのペナルティ算術 |
| `input_refs` | `penalty > 0` は `input_refs.validated_attack_ids` に 1 個以上の id を**要求**（カーネルチェック — 生の攻撃は決してスコアしない） |
| `utility_policy_hash` / `frozen_policy` | エポック凍結されたポリシー。元の重みでの再計算を可能にするため**値で**埋め込み |
| `supersedes` / `recomputed_in_epoch` | Task-10 の再計算レコードでのみ設定; 置き換えられたレコードはディスク上に stale なまま残る |

これらのフィールドは stale な採点済み証拠を消去した後の再計算を表します。
utility-policy 退役は別の Task-10 経路を通り、各ノードに保存された
`_axis_scores` を新ポリシーの下で再合成し、ノードを外側の
`SelectiveErasureEvent.policy_rescored_node_ids` に記録します。生の軸が
欠けるノードは fail-closed で無効化されます。

### `rqgm_replay_pool.schema.json`

**目的:** AdversarialReplayPool の導出されたバイト固定の
`rqgm/adversarial_replay_pool.json` スナップショット;
`rqgm_adversarial_cases.jsonl` が真実源のままで、ロード時にクラッシュ末尾を
埋めます。**所有モジュール:** `ari/rqgm/adversarial/pool.py`; 永続化は
`ari.checkpoint.save_adversarial_pool_json` 経由。

| フィールド | 備考 |
|---|---|
| `case_seq` | 単調増加のケースカウンタ |
| `cases[]` | AdversarialReplayCase: `case_id`（`adv_case_%05d`）、`case_type`（同梱スキーマの探索用 7 タイプ。paper runtime は後述するフェーズ外 inert の 8 番目を追加）、`validated_attack_id`、`severity`、`admitted_epoch` / `last_confirmed_epoch`、`status` は `active` \| `evicted`（eviction は論理のみ）、`replay_view`（完全な資料 — ロール `clean_room_generator` には拒否）と `abstract_view`（汚染安全な FailureSummary — 生の攻撃 / 防御テキストなし） |

## プロンプト進化スキーマ (Task 07)

### `rqgm_prompt_spec.schema.json`

**目的:** バージョン付きで不変なプロンプトアイデンティティ（PromptSpec）
1 件 — テンプレートバイトへのいかなる変更も**新しい** `prompt_id` +
`prompt_hash` を発行します; アクティブなプロンプトテキストが in-place で
変更されることは決してありません。**所有モジュール:**
`ari/rqgm/prompt_spec.py`; インスタンスは `prompt_evolution.jsonl` の候補に
埋め込まれ、`prompt_specs.json` にロールアップされます。

| フィールド | 備考 |
|---|---|
| `prompt_id` / `role` / `version` / `status` | アイデンティティ + ライフサイクル上の位置 |
| `generation_mode` | `founding` \| `mutation` \| `clean_room` |
| `parent_prompt_id` | 系譜（founding プロンプトでは `null`） |
| `template_ref` | `{kind: package \| checkpoint \| policy, key\|path}` — バイトの所在（コミット済みテンプレート、進化した本体 `rqgm_prompts/<prompt_id>.md`、または `path` で参照される Task-14 の governed ユーティリティポリシー本体） |
| `prompt_hash` / `full_sha256` | テンプレートバイトの `hash12` + 完全 sha256（まさに `FilesystemPromptLoader.load_versioned` のスキーム） |
| `evolvable` / `epoch_introduced` | 進化の適格性 + 来歴 |
| `spec` | 振る舞い契約: `role_instruction`、`constitutional_constraints[]`、`input_contract.required_fields[]`、`output_schema`、任意の `rubric` / `calibration_policy` / `budget_policy` |

### `rqgm_prompt_evolution.schema.json`

**目的:** `prompt_evolution.jsonl` に多重化される 3 つのレコード形。
`probationary_active` / `active` への採用は RegistryTransitionEngine の
エポック境界トランザクションを通じて**のみ**起こります — このファイルを
通じては決して起こりません。**所有モジュール:**
`ari/rqgm/prompt_records.py`（形 + 永続化）、
`ari/rqgm/prompt_evolution.py`（パイプライン）。

| レコード (`record_type`) | Id | 固有フィールド |
|---|---|---|
| `prompt_candidate` | `pcand_%05d` | `candidate_id`、`generation_mode`（`mutation` \| `clean_room`）、`mutation_kind`（`freeform_mutation`、`threshold_tuning`、`schema_tightening`、`specialization`、`distillation`）、`source_prompt_id`、`failure_summary_refs`、`rationale`、完全に埋め込まれた `prompt_spec`。常に `status: candidate` で生まれる — 即時有効化なし |
| `prompt_candidate_validation` | `pval_%05d` | `candidate_id`、`stage`（単調なはしご `static_validation → constitutional_validation → schema_dry_run → replay_evaluation → anchor_evaluation → shadow` — レコードチェーンによりステージスキップは検出可能）、`passed`、`evaluated_by`、`case_results`、`metrics` |
| `comparison_observation` | `cobs_%05d` | `candidate_id`、`incumbent_id`、`input_context_hash`、`node_id`、`candidate_output_hash` / `incumbent_output_hash`、`divergence`。ハッシュと乖離サマリのみ — shadow の出力テキストがこのファイル、ノードメトリクス、フロンティアに到達することは決してない |

## クリーンルームスキーマ (Task 08)

### `clean_room_request.schema.json`

**目的:** CleanRoomGenerationRequest 1 件。RegistryTransitionEngine の
RetirementEvent（`EpochTransition.clean_room_requests`）から生成され、
保留中の要求が resume を生き延びるよう `rqgm_cleanroom.jsonl` へ永続化
されます。**所有モジュール:** `ari/rqgm/clean_room.py`（要求 +
パイプライン; スクリーンポリシーは `ari/rqgm/clean_room_rules.py`）。

| フィールド | 備考 |
|---|---|
| `component_id` / `trigger` | const `registry_transition_engine` / `retirement_event`; `prompt_hash` は `null` |
| `retirement_event_id` / `target_role` | どの退役か、どのロールを再生成するか（閉じたロール enum） |
| `status` | `pending` \| `generating` \| `generated` \| `rejected_contaminated` \| `failed` \| `superseded` |
| `allowed_inputs` | 5 つの禁止入力フラグは **const-false** — いずれかを `true` に設定した要求はスキーマ違反かつカーネルブロック |
| `requirements` / `replay_case_ids` / `budget_policy` | 再生成の要件; リプレイケースは評価時のみ |

### `clean_room_bundle.schema.json`

**目的:** CleanRoomPromptGenerator に渡される、実体化された**閉じた**入力
集合（`additionalProperties: false` — バンドルは、コミット済みの
`rqgm/clean_room_generator` メタプロンプトを除くジェネレータコンテキストの
全体です）。**所有モジュール:** `ari/rqgm/clean_room.py`。

| フィールド | 備考 |
|---|---|
| `bundle_id` / `request_id` | 要求へのリンク |
| `bundle_hash` | 他のすべてのフィールドの正準 JSON 上の `hash12` |
| `role_spec` / `output_schema` / `constitutional_constraints` | 再生成されるプロンプトが満たすべきもの |
| `abstract_failure_summary` | 汚染安全な失敗サマリ（abstract view のみ） |
| `replay_requirements` / `cost_budget` | 受け入れ要件 + 予算 |

## 遷移スキーマ (Task 09)

### `epoch_transition.schema.json`

**目的:** RegistryTransitionEngine の境界解決 1 回の単一の出力レコードで、
`epoch_transition` レコードとして `rqgm_audit.jsonl` に監査されます。
すべてのステータス変更は `ari/rqgm/transition_rules.py` の固定 T1–T21
`rule_id` 行（T1–T19 のベーステーブル + ロールスコープの T20 / T21
supersession 行）をピン留めします; 設定可能なのは `rqgm.transition.*` の
数値しきい値のみです。**所有モジュール:** `ari/rqgm/transition_engine.py` —
レジストリステータスの唯一の書き込み手（`produced_by` は const
`registry_transition_engine`、カーネル CK-REG-004）。

| フィールド | 備考 |
|---|---|
| `epoch_transition_id` | `transition_%03d_to_%03d` |
| `status` | `pending` \| `committed` \| `aborted` \| `rejected` \| `failed` — 中止 / カーネルブロックされた遷移はログされるがレジストリ変更は**一切**適用されない |
| `emergency` | `true` は隔離と次期開始を一つの強制緊急境界で行う T16 形 |
| `inputs` | 凍結された境界入力（GovernanceReport + 候補評価 + レジストリハッシュ）の `inputs_sha256` コンテンツハッシュを含み、コミットされたすべての変更が決定論的にリプレイできる |
| `adoptions` / `sanctions` / `retirements` / `bans` | ステータス変更リスト。それぞれ `rule_id` をピン留め |
| `clean_room_requests` | Task 08 へ渡される再生成要求 |
| `next_active_components` / `fallbacks` | 次エポックの凍結アクティブ集合 + 空席なしフォールバック |
| `kernel_validation`（+ 任意の `kernel_violation`） | トランザクションに対するカーネル判定 |

## フロンティア修復スキーマ (Task 10)

### `selective_erasure_event.schema.json`

**目的:** FrontierRepairEngine が退役した `prompt_hash` の依存閉包を stale
にするときに（Task 02 の監査エンベロープの内側で）`rqgm_audit.jsonl` に
追記される SelectiveErasureEvent 1 件。消去は論理のみです（不変条件 13）:
列挙された id は `rqgm_erasure_state.json` でフラグされ、決して書き換え・
削除されません。**所有モジュール:** `ari/rqgm/frontier_repair.py`。

| フィールド | 備考 |
|---|---|
| `record_id` | `erase_%05d` |
| `component_id` / `role` / `prompt_hash` | const `frontier_repair_engine` / `kernel` / `null`（カーネル作） |
| `status` | `applied` \| `conservative` \| `halted_expansion`（fail-closed の縮退はしご） |
| `retired_prompt_hashes` / `retired_component_ids` | 退役したもの |
| `direct_stale_record_ids` / `transitive_stale_record_ids` | 依存閉包 |
| `invalidated_node_ids` / `recompute_node_ids` / `abandoned_pending_node_ids` | stale な依存閉包に対するノードの処遇 |
| `policy_rescored_node_ids` | 任意かつ追加的な #77 フィールド。新しい utility policy の下で保存済み `_axis_scores` から再重み付けされ、無効化を免れたノードの一覧 |
| `trace_stats` | BFS トレーサ統計（`rqgm.frontier_repair.max_trace_depth` が探索を上限） |

### `frontier_rebuild_event.schema.json`

**目的:** エンジンがフロンティアを宣言的に再計算した後（適格性 + 勝った子が
消去された親の Rule-A 復帰）に `rqgm_audit.jsonl` へ追記される
FrontierRebuildEvent 1 件。**所有モジュール:**
`ari/rqgm/frontier_repair.py`。

| フィールド | 備考 |
|---|---|
| `record_id` | `rebuild_%05d` |
| `component_id` / `role` / `prompt_hash` | const `frontier_repair_engine` / `kernel` / `null` |
| `status` | `applied` \| `conservative`（カーネル検証失敗後、フラグ付きノードを除外）\| `halted_expansion`（ランは drain-only に縮退） |
| `frontier_before` / `frontier_after` | ノード id リスト |
| `removed_node_ids` / `reinstated_node_ids` / `recomputed_utility_node_ids` | 差分 |
| `kernel_validation` | `passed` \| `failed` |

### `erasure_state.schema.json`

**目的:** 導出され再構築可能な `rqgm_erasure_state.json` の staleness
ロールアップ — `rqgm_audit.jsonl` のすべての消去 / 再構築イベントから fold
できます。staleness は読み取り時です: レコードが stale であるのは、その
`record_id` が `stale_record_ids` にあるとき、かつそのときに限ります;
ファイルの不在は「何も stale でない、すべて有効」を意味します。
**所有モジュール:** `ari/rqgm/erasure_state.py`; 書き込みは
`ari.checkpoint.save_erasure_state_json` に集約。

| フィールド | 備考 |
|---|---|
| `retired_prompt_hashes` | `hash12 → {retirement_event_id, retired_in_epoch}` |
| `stale_record_ids` | `record_id → 消去イベント id` |
| `invalid_frontier_node_ids` | `node_id → 消去イベント id` |
| `last_erasure_event_id` / `last_rebuild_event_id` | fold カーソル |

## メタ進化スキーマ (Task 11)

### `rqgm_meta.schema.json`

**目的:** メタティアの `$defs` — ComponentRegistry の `tier` + capability
フラグ拡張、`rqgm_meta_outputs.jsonl` の MetaAgentOutputRecord 行の形、
そして RegistryTransitionEngine が消費する MetaCandidateEvaluation
レコード。**所有モジュール:** `ari/rqgm/meta_rules.py`（決定論的な Python
ミラー — `capability_entry_failures` — はスキーマと一致していなければ
ならない）+ `ari/rqgm/meta_evolution.py`。

| 定義 | 主要フィールド |
|---|---|
| `capability_flags` | ブール capability マトリクス（`can_modify_registry`、`can_activate_candidates`、`can_read_retired_prompt_text`、`can_file_impeachment`、`can_author_evidence_bundle`、`can_emit_candidates`、`can_emit_replay_recommendation`、`can_emit_failure_summary`）+ `allowed_targets` / `forbidden_targets` / `max_outputs_per_epoch`。フラグのデフォルトは false; hard-denied フラグは `tier: meta` で const-false |
| `meta_component_entry` | `component_id`、`role`、`tier`、`status`、`prompt_hash`、`capabilities` |
| `meta_agent_output_record` | `record_id` は `meta_out_` + hash12; `status` は `recorded` \| `denied`; `output_kind` は閉じた集合 `prompt_candidate` \| `clean_room_candidate` \| `replay_case_recommendation` \| `failure_summary`; `target_role`; `shadow` / `sandboxed` フラグ; `input_bundle_hash` / `output_payload_hash` |
| `meta_candidate_evaluation` | `candidate_component_id` vs `incumbent_component_id`、`sandbox` / `shadow` の結果、`downstream_fate`、`authority_non_expansion_check` は `pass` \| `fail` |

## ガバナンスキャッシュスキーマ (Task 12)

### `rqgm_governance_cache.schema.json`

**目的:** append-only な `rqgm_governance_cache.jsonl` ガバナンス結果
キャッシュの 1 行。**所有モジュール:** `ari/rqgm/governance_cache.py`;
`ari/rqgm/governance/_adjudication.py`（エポック境界の候補評価）と
`rqgm.replay.use_cached_results` のリプレイ検索が消費します。

| フィールド | 備考 |
|---|---|
| `cache_key` | `sha256(artifact_hash ␟ prompt_hash ␟ role ␟ epoch_id ␟ input_context_hash ␟ output_schema_hash)[:16]`（`␟` = `\x1f`）; 16 桁 hex |
| `artifact_hash` / `input_context_hash` / `output_schema_hash` | 正準 JSON 上の完全 sha256 |
| `result_ref` / `score` | 基となるレコードへのポインタ + キャッシュされたスコア |
| `created_at` | 来歴のみ — **決して**キーの一部ではない (P2) |

エントリが in-place で無効化されることはありません: 退役したプロンプトの
エントリは、その `prompt_hash` が検索に二度と現れないためアドレス不能に
なるだけです（不変条件 13）。予算カウンタとガバナンスレベルの割り当ては
ここには保存されません — それらは `budget_consumed` / `budget_degraded` /
`governance_level` 行として `rqgm_audit.jsonl` に乗ります
（`ari/rqgm/budget.py`）。

## governed ユーティリティ進化スキーマ (Task 14)

### `rqgm_utility_policy_candidate.schema.json`

**目的:** 提案された後継**ユーティリティポリシー**1 件 — governed なスコア
自体が、境界で書き換え可能な進化オブジェクトになりました（RQGM Task 14）。
`utility_policy_candidate` は `prompt_candidate` を鏡写しにし、**同じ**
`prompt_evolution.jsonl` ログに乗ります — 新しいストアはありません。その
エンベロープの著者はポリシーではなく `policy_mutator` です: 候補はコンポーネント
**による**提案なので、`component_id` / `prompt_hash` は提案者を名指しし、
提案されるポリシーは `policy`（値で）+ `policy_hash` に乗ります。
**所有モジュール:** `ari/rqgm/utility_evolution.py`
（`UtilityPolicyCandidate`、`PolicyMutator`）; 境界で鋳造され
`ari/rqgm/prompt_records.record_prompt_evolution_event` 経由で追記されます。

| フィールド | 備考 |
|---|---|
| `record_id` | `upc_%06d` |
| `role` | const `policy_mutator` — **著者**のロール; **ターゲット**ロール（`utility_policy`）は `record_type` から含意される |
| `candidate_id` | 鋳造された候補アイデンティティ; intake 時にはプロンプトレジストリの `prompt_id` にもなる |
| `mutation_kind` | 閉じた集合 `axis_reweighting` \| `composite_swap` \| `frontier_score_swap` \| `exploration_tuning` \| `freeform_policy_proposal` |
| `policy` | ポリシー本体: `composite`、`axis_weights`（軸ごとの重みマップ）、`frontier_score`、`depth_penalty_lambda`、`ucb_c`。本体は `utility_policy_hash` を決して含まない — ハッシュは本体*の*ものである |
| `policy_hash` | `hash12(canonical_json(policy))` — 1 つの値、3 つの名前: `policy_hash` **は** intake エントリの `prompt_hash` **であり** 採用時に候補が凍結する `utility_policy_hash` **である** |
| `parent_prompt_id` / `rationale` / `source_refs` | 系譜 + 抽象証拠のみ — `rationale` / `source_refs` は生の攻撃テキストを決して運ばない |

合法性（閉じた値空間 + 軸重みの境界）はこのスキーマでは表現されません:
それは `ari.rqgm.kernel_rules.UTILITY_POLICY_RULES` の凍結コードにあり、
`constitution_hash` の内側で、候補がノードをスコアできるようになる前に
CK-UTL-001..008 が強制します。採用は RegistryTransitionEngine の境界
トランザクションを通じて**のみ**起こります — ロール非依存の T1→T6 スパイン、
加えて Task-14 の supersession エッジ **T20**
`superseded_by_adopted_successor`（`ari/rqgm/transition_rules.py`; 唯一の
`active → retired` エッジで、`utility_policy` のみにカーネルガードされる） —
このレコードを通じてではありません。進化したポリシー本体は
`rqgm_prompts/<candidate_id>.json` に write-once で書かれ（ソース参照、決して
インライン化しない）、採用されたポリシーが
`ari/rqgm/state.py:capture_utility_policy` が `epoch_state.json` に凍結する
ものです。

## Paper-archive スキーマ（paper `rqgm_archive` モード）

paper-archive の paper モード（`paper.mode: rqgm_archive`、`rqgm.paper.enabled`
でゲート）は 4 つのチェックポイントファイルを永続化します。`rqgm_state.json`
や評価ハーネス成果物と同様、**いずれも正式な JSON スキーマを持ちません** —
各形は Python モジュールが所有し、値で運ばれます — そして 4 つすべてが
デフォルトの `linear` paper ラン（linear パスでは `ari.rqgm` モジュールを
一切ロードしない）には存在しません。

### `paper_archive_state.json` — paper フェーズのモード来歴

paper フェーズ開始時に write-once。形は `ari/rqgm/paper_runtime.py`
（`build_paper_run_start_state`）が所有: `schema_version`、`paper_mode`
（`linear` \| `rqgm_archive`）、`rqgm_paper_enabled`、`mode_source`
（∈ `config` \| `env` \| `resume`）、`created_at`（メタデータのみ、決して
ハッシュされない）、`exploration_mode`、`seed_node_id`、`switch_journal[]`。
永続化されたモードが再呼び出し時に勝ちます — resume が paper モードを黙って
切り替えることはありません。書き込み手:
`ari.checkpoint.save_paper_archive_state_json`。

### `paper_draft_archive.jsonl` — スコア付きドラフト母集団

append-only、バイト固定、best-effort（レコード書き込み失敗が paper フェーズを
壊すことは決してない; 不在ファイルは空として読まれる — linear ランはアーカイブ
を残さない）。形は `ari/rqgm/paper_archive.py` /
`ari/rqgm/paper_draft_executor.py` が所有: 1 行 1 ドラフトノード —
`schema_version`、`draft_id` / `node_id`、`kind`（`seed` \| `refine`）、
`parent_draft_id`、`refine_pass`、`tex_path`、`tex_sha256`、
`writer_prompt_hash`（framing / `diversity_bonus` のキー）、
`reviewer_prompt_hash`、`review_score`（governed な `paper_reviewer` の
composite — フロンティア + best-belief のランキングキー）、
`suggested_revisions_ref`、`anchors_preserved`、`decode_seed`、`epoch_id`、
そして読み取り時フラグ `is_best_belief` / `compiled`（`mark_paper_draft_flags`
が in-place で更新）。

### `paper_anchor_corpus.jsonl` — 読み取り専用の accept/reject アンカー

`paper_reviewer` ユーティリティをアンカーする APReS 等価の held-out コーパス。
形は `ari/rqgm/paper_anchor.py`（`PaperAnchorCase`）が所有: `case_id`、
`record_type`、`ground_truth_label`（`accept` \| `reject`）、`label_source`
（`human_curated` \| `gate_bootstrap`）、`manuscript_sha256` /
`manuscript_ref` / `manuscript_text`、`venue`、`authorship`
（`human` \| `ai`）、`split`（`train` \| `held_out`、ロード時に決定論的に
割り当て）、`origin_epoch_id`、`expected_behavior`、`results`。curation /
bootstrap ツールが**一度だけ**書きます — governed なロールが書くことは
**決してありません**（アンカーは固定の ground truth であり、進化する
アーティファクトではない）。`gate_bootstrap` ラベルに対する
`max_bootstrap_label_fraction` の上限は機械強制です（held-out split なしに
縮退し、決して raise しない）。**デフォルト OFF**（`anchor.enabled: false`）:
縮退した on-ramp はコーパスを残さないため、デフォルトの `rqgm_archive` ランは
curated コーパスが供給されるまで reviewed best-of-N です。

### `rqgm/paper_self_preference_stat.json` — 自己選好統計

8 番目のアドバーサリが `attack_evidence_ref` として引用する、エポックごとの
決定論的な AI 対人間の自己選好マージン。`{ckpt}/rqgm/` スナップショット
ディレクトリの下に best-effort で書かれます（paper フェーズに raise することは
決してない）。形は `ari/rqgm/paper_self_preference.py`
（`compute_self_preference_margin`）が所有: `record_type`、`schema_version`、
`epoch_id`、`sample_ids[]`、`per_case_scores`、`ai_mean`、`human_mean`、
`margin` — `mean(reviewer accepts | authorship == ai) − mean(… | authorship
== human)`、**コーパスが AI/人間の split を持たないとき `0.0`**（コーパス
不在 / AI のみの縮退。決してエラーではない）。

**8 番目のアドバーサリタイプ。** `paper_self_preference` は Python
`ADVERSARY_TYPES` タプル（`ari/rqgm/adversarial/records.py`; 書き込みパスの
妥当性チェック `validate_raw_attack` が使用）の 8 番目のメンバで、paper
フェーズ用に追加され、それ以外では inert です; 同梱の
`rqgm_attack_records.schema.json` の `adversary_type` / `case_type` enum は
7 つの**探索**タイプを文書化します。`paper_self_preference` ケースは
`paper_reviewer` ロールを関与させ、これは — 7 つの `generator` と異なり —
登録済みの現職（paper モード下の `paper_reviewer_v1`）を**持つ**ため、Task-15
の `target_component_id` バインディングが発火し、validated-attack → 弾劾
チェーンが本番で動きます; paper フェーズ以外ではロールは `""` に解決され、
探索はバイト同一のままです。

## チェックポイントファイルインベントリ

ファイルごとの完全な挙動（生成条件、真実 vs スナップショット、resume の
意味論）は
[ファイルフォーマットリファレンス](file_formats.md#rqgm-epoch-governance-files-opt-in-ari_rqgm-mode)
に文書化されています; この表はファイルとスキーマ・所有者の対応のみを示し
ます。以下のすべてのファイルは名前で `PathManager.META_FILES` に登録され
（JSONL の真実群は加えてトレースファイル集合にも）、`proposals/` と
`rqgm_prompts/` ディレクトリはノードレポートのディレクトリブロックリスト
（`ari/orchestrator/node_report/builder.py`）に載っているため、いずれも
ノードの `files_changed` に現れることはありません。

| チェックポイントパス | 種別 | スキーマ | 書き込み手 |
|---|---|---|---|
| `rqgm_state.json` | モード来歴スナップショット (write-once) | なし — 形は `ari/rqgm/state.py` が所有（`schema_version`、`mode`、`rqgm_enabled`、`mode_source` ∈ `config\|env\|resume`、`created_at`、`switch_journal[]`） | `ari.checkpoint.save_rqgm_state_json` |
| `constitution.yaml` | 人間可読な声明。`ari-core/config/constitution.yaml` から copy-once | なし — 権威ある規則は `constitution_hash` でピン留めされた凍結コード | `ari/rqgm/state.py`（`copy_constitution_if_missing`） |
| `rqgm_transitions.jsonl` | append-only の真実（ハッシュ連鎖） | `rqgm_transition_event` | `ari/rqgm/store.py` |
| `rqgm_audit.jsonl` | append-only の監査ログ（独立チェーン） | エンベロープは `rqgm_transition_event`; レコードペイロード: `governance_report`（+ 動議パイプラインのレコード）、カーネルレポート、`epoch_transition`（+ 退役 / クリーンルーム要求レコード）、`selective_erasure_event`、`frontier_rebuild_event`、再計算された `rqgm_utility_record`、予算行 | ガバナンス / 遷移 / 修復の各エンジン（ストア経由） |
| `epoch_state.json` | 導出スナップショット | `epoch_state` | `ari.checkpoint.save_epoch_state_json` |
| `rqgm_registry.json` | 導出スナップショット | `rqgm_registry` | `ari.checkpoint.save_rqgm_registry_json` |
| `proposals/proposal_records.jsonl` | append-only の真実 | `proposal_record`（`proposal_summary_view` を埋め込み） | `ari/rqgm/proposals/store.py` |
| `proposals/proposal_index.json` | 導出ロールアップ | なし（導出） | `ari/rqgm/proposals/store.py` |
| `rqgm_adversarial_cases.jsonl` | append-only の真実 | `rqgm_attack_records` + `rqgm_utility_record` + リプレイケース行 | `ari/rqgm/adversarial/pool.py` |
| `rqgm/adversarial_replay_pool.json` | 導出スナップショット | `rqgm_replay_pool` | `ari.checkpoint.save_adversarial_pool_json` |
| `prompt_evolution.jsonl` | append-only の真実 | `rqgm_prompt_evolution`（`rqgm_prompt_spec` を埋め込み）+ `rqgm_utility_policy_candidate`（Task 14 が同じログに乗る） | `ari/rqgm/prompt_records.py` |
| `prompt_specs.json` | 導出ロールアップ | `rqgm_prompt_spec` のロールアップ | `ari.checkpoint.save_prompt_specs_json` |
| `rqgm_prompts/<prompt_id>.{md,json}` | write-once の進化済みバイト（`.md` はプロンプトテンプレート; `.json` は Task-14 のポリシー本体） | なし — バイトは `prompt_hash` でピン留め | `ari/rqgm/prompt_loader.py` |
| `rqgm_cleanroom.jsonl` | append-only の真実 | `clean_room_request` + `clean_room_bundle` | `ari/rqgm/clean_room.py` |
| `rqgm_erasure_state.json` | 導出スナップショット | `erasure_state` | `ari.checkpoint.save_erasure_state_json` |
| `rqgm_meta_outputs.jsonl` | append-only の真実 | `rqgm_meta`（`meta_agent_output_record`） | `ari/rqgm/meta_evolution.py` |
| `rqgm_governance_cache.jsonl` | append-only のキャッシュ | `rqgm_governance_cache` | `ari/rqgm/governance_cache.py` |
| `rqgm_eval_metrics.json` / `rqgm_injection_provenance.json` | 評価ハーネス成果物（ハーネスが起動したランのみ） | なし — 形は `ari/rqgm/evaluation/{metrics,injection}.py` が所有 | 評価ハーネス |
| `paper_archive_state.json` | paper フェーズのモード来歴スナップショット (write-once) | なし — 形は `ari/rqgm/paper_runtime.py` が所有 | `ari.checkpoint.save_paper_archive_state_json` |
| `paper_draft_archive.jsonl` | append-only のドラフト母集団 (best-effort) | なし — 形は `ari/rqgm/paper_archive.py` が所有 | `ari/rqgm/paper_draft_executor.py` |
| `paper_anchor_corpus.jsonl` | 読み取り専用のアンカーコーパス (write-once) | なし — 形は `ari/rqgm/paper_anchor.py` が所有 | curation / bootstrap ツール |
| `rqgm/paper_self_preference_stat.json` | 導出されたエポックごとの統計 (best-effort) | なし — 形は `ari/rqgm/paper_self_preference.py` が所有 | `ari/rqgm/paper_self_preference.py` |

## 関連

- [ファイルフォーマットリファレンス](file_formats.md) — これらのスキーマが
  検証するチェックポイントファイル。
- [設定リファレンス](configuration.md#execution-mode-and-rqgm-governance-opt-in)
  — `ari.mode`、`rqgm.*`、`proposal_router.*` ブロック。
- [実行モード](../guides/execution_modes.md) — モードの有効化と憲法
  カーネル。
- [RQGM 評価](../guides/rqgm_evaluation.md) — `rqgm_eval_metrics.json` を
  消費するアブレーションハーネス。
- `ari-core/ari/schemas/README.md` — 同梱される全スキーマの 1 行
  インデックス。
