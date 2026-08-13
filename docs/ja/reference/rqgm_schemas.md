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
`ari.schemas.load(name)` によりベース名でロードできます。これらのレコードは
デフォルトの `simple_bfts` チェックポイントには一切存在しません — すべての
読み取り側は不在を「RQGM は一度も走っていない」として扱います。

これらのスキーマは**リファレンス契約であって、ランタイムのバリデータでは
ありません。** `ari/rqgm/` 配下のどのコードもこれらを開きません:
`jsonschema` は `ari-core` の依存関係ではなく、RQGM のどの書き込み側も
永続化の前にレコードを `.schema.json` と突き合わせて検査しません。
レコードクラスはスキーマファイルを*ミラーする*ただの dataclass です
（`ari/rqgm/proposals/records.py` と `ari/rqgm/adversarial/records.py` の
モジュール docstring はまさにその語を使っています）。背後に Pydantic モデルは
無く、同梱スキーマが生成された `model_json_schema()` と一致することを主張する
スナップショットテストもありません。Pydantic の `model_validate` は
`ari/rqgm/` 内でも*使われています*が、それは別途ゲートされた
Knowledge/Capability/Assurance の admission、harness、capability-binding、
manuscript の各ドキュメント（および評価ハーネス自身の `ARIConfig` オーバレイ、
`ari/rqgm/evaluation/smoke.py`）に対してだけであり、`rqgm_record_base`
エンベロープや本ページがインベントリするレコードに対しては使われません。

書き込み時にカーネルが実際に強制するのはエンベロープ + 形状の検査、
`ConstitutionalKernel.validate_record_schema`（`ari/rqgm/kernel.py`）です:
`kernel_rules.ENVELOPE_FIELDS` の 8 フィールドが存在すること、
`record_id` / `status` / `role` は存在する場合に空でないこと、そして
`proposal_record` ではさらに proposal summary のフィールド予算検査が走ること。
違反は、governance レコード型である `epoch_transition` / `governance_report`
については `CK-SCH-G01`（block）として、それ以外のすべてのレコード型に
ついては `CK-SCH-N01`（warn）として、予算超過は `CK-SCH-N02`（warn）として
現れます。したがって以下に文書化する各フィールドの型・フォーマット・閉じた
列挙は、書き込み側とテストスイートによって保たれています —
`ari-core/tests/test_rqgm_*.py` のいくつかのモジュールが実レコードをこれらの
スキーマファイルに対して検証します。ただし `jsonschema` は
`pytest.importorskip` 経由で取得しており、無ければスキップされます — 永続化
時点の検証によって保たれているのではありません。

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

## 憲法違反コード

カーネルの検出結果はすべて安定な `CK-<FAMILY>-<NNN>` コードを持ち、その
重大度は呼び出し側の選択ではなく憲法の一部です。重大度はコードごとに
`ari.rqgm.kernel_rules.SEVERITY` で固定され（Knowledge/Capability/Harness
系列は `ari/rqgm/kca_kernel_rules.py` から併合）、**すべての** `Violation`
生成がこの 1 つの表を経由して解決し（`ari/rqgm/kernel.py` の `_v`、
`ari/rqgm/kernel_kca_common.py` の `violation` — 未知のコードは `KeyError`
であり、既定値で重大度が埋まることはありません）、`constitution_hash` の
内側に入ります。したがって重大度を書き換えるとピンが変わります。コードは
実装された時点で凍結され、番号が振り直されることはありません。

| 系列 | 所有する検査 | 重大度 |
|---|---|---|
| `CK-SCH-G01` | `validate_record_schema` — ガバナンスレコード種別（`epoch_transition`、`governance_report`）でのエンベロープ / 形状違反 | block |
| `CK-SCH-N01`、`CK-SCH-N02` | `validate_record_schema` — その他のレコード種別での同じ違反; 提案サマリのフィールド予算超過 | warn |
| `CK-HSH-001`、`CK-HSH-002`、`CK-HSH-003` | `validate_hashes` — レコードの `prompt_hash` とロールの登録済み active ハッシュの不一致; `artifact_hashes` と再計算 sha256 の不一致; 解決できない成果物または `source_ref` | warn |
| `CK-HSH-010` | `validate_hashes` — **active** な台帳エントリ自身の `prompt_sha256[:12]` が登録済み `prompt_hash` と食い違う | block |
| `CK-ACC-001`、`CK-ACC-002` | `validate_capability` — `CAPABILITY_MATRIX` に無い、または Task 11 のメタ操作フラグで拒否; 退役プロンプト本文へのアクセス（全ロールで読めません） | block |
| `CK-EPO-001` | `validate_epoch_invariance` — `prompt_hash` がそのエポックの凍結 active set の外にあるレコード | warn |
| `CK-EPO-002` | `validate_epoch_invariance` — エポック途中の非緊急のステータス変更イベント | block |
| `CK-REG-001`…`CK-REG-007` | `validate_transition` — T1–T21 表に無い辺、境界限定の辺をエポック途中で打刻、宣言された `rule_id` が表と矛盾、`produced_by` が RegistryTransitionEngine でない、必要な裏付け参照の欠落、緊急遷移の形状不正、`from_status` が台帳と矛盾 | block |
| `CK-REG-101` | `validate_authority_non_expansion` — 現職より広い権限を宣言する候補（不変条件 18） | block |
| `CK-ROL-001`、`CK-ROL-002`、`CK-ROL-003` | `validate_role_separation` — 弾劾動議の著者が Auditor でない、証拠バンドルが EvidenceClerk でない、同一ロールによる告発 | warn |
| `CK-ROL-901` | `validate_role_separation` / `validate_capability` — RegistryTransitionEngine 以外による台帳書き込みまたは候補の活性化（不変条件 10） | block |
| `CK-ERA-001`…`CK-ERA-006` | `validate_selective_erasure` — stale / frontier 無効 / 退役プロンプト由来のレコードがフロンティアに存在、退役プロンプト依存レコードが stale 化されていない、物理削除（不変条件 13）、`prompt_trace.jsonl` の行が未対応の退役ハッシュを持つ | block |
| `CK-AUD-001`、`CK-AUD-002`、`CK-AUD-003` | `validate_audit_log_integrity` — 連番の後退、チェックポイント済み前半部の改変、ハッシュ鎖の断裂 | block |
| `CK-CLN-001`、`CK-CLN-002` | `validate_clean_room_bundle` / `validate_contamination_free` | block |
| `CK-CTX-001` | `validate_context_scope` — 描画されたロールビューがフィールドホワイトリストを超過 | warn |
| `CK-UTL-001`…`CK-UTL-008` | `validate_utility_policy` — `CK-UTL-006`（エポックの生きた軸集合の外にある軸キー）**のみ** warn、他はすべて block | block / warn |
| `CK-KNW-001`…`015`、`CK-CAP-001`…`018`、`CK-HAR-001`…`020` | `validate_knowledge_integrity` / `validate_capability_binding_integrity` / `validate_harness_integrity` | block |

`severity: block` は、強制経路がその判定を参照する場所で状態変更を拒否
できる**資格**を与えるものであり、すべての文脈がそれに従うという意味でも、
強制モードがすべての文脈に届くという意味でもありません。
[`rqgm.kernel.enforcement`](configuration.md#execution-mode-and-rqgm-governance-opt-in)
を尊重する地点はヘルパ `ari.rqgm.kernel.should_block` を経由します
（`ari/rqgm/runtime.py`、`transition_engine.py`、`frontier_repair.py`、および
`kernel.py` の capability ゲート付き MCP ラッパ）。`audit_only` ではこの
ヘルパがすべてのレポートで false を返しますが、記録された重大度自体は
書き換えないため、監査証跡は真実のまま残ります。一方、`report.blocking` を
直接読む地点は強制モードの影響を受けません: クリーンルームの生成前後
スクリーン（`ari/rqgm/clean_room.py`）、メタ候補の受理ゲート
（`ari/rqgm/meta_evolution.py`）、ガバナンス自己監査のエスカレーション
（`ari/rqgm/governance/_self_audit.py`）。意図的に warn 専用の文脈は
どちらのモードでも warn 専用のままです: ノードごとのフック
（`per_node_warn_check`）はスキーマ検査とハッシュ検査を例外を投げずに実行し、
`validate_context_scope` はノード実行をブロックしません。

1 つだけ `enforcement` から独立した経路があります。`transition_engine.EMERGENCY_TRIGGER_CODES`
に含まれるコード（`CK-HSH-010`、`CK-EPO-002`、`CK-AUD-001/002/003`、
`CK-ACC-001/002`、`CK-ROL-901`）を持つ block 重大度の違反は、モードに関わらず
MCP ラッパから T16 緊急隔離経路へ渡されます: `audit_only` が下げるのは
ブロッキングであって憲法上の事実ではなく、緊急遷移自体もコミット前に
カーネル検証を受けます。ただしこの経路が隔離できるのは**登録済み
コンポーネント**だけです。対象コンポーネントは violation から取り、
無ければ行為者のロールをエポック凍結された `active_components` に照らして
解決します。どちらでも id が得られない場合は escalation がログに
残るだけで遷移は組み立てられません。

## 共有エンベロープ (`rqgm_defs.schema.json`)

**目的:** すべての RQGM レコードスキーマが参照する正準の共有 `$defs` —
`rqgm_record_base` エンベロープ、閉じたステータス / ロール / ティア語彙、
id / ハッシュ形式。**所有モジュール:** `ari/rqgm/events.py`（語彙の Python
ミラー）。`epoch_state.schema.json`、`rqgm_registry.schema.json`、
`rqgm_transition_event.schema.json` に埋め込まれたこれら `$defs` のコピーは、
`ari-core/tests/test_rqgm_state_store.py` によってこのファイルへピン留め
されています — バイト単位ではなく、パース済み JSON をエントリ単位で比較する
形で。同テストはステータス / ロール / ティア列挙と event_type 列挙も
`ari.rqgm.events` の語彙にピン留めします。

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
  同一）; ガバナンスアクター（プロンプト変異による後継経路を持たない一方、
  他のコンポーネントと同様に制裁・retire・ban の対象）: `auditor`、
  `evidence_clerk`、`governance_judge`; 固定（来歴のために登録、憲法上
  不変）: `constitutional_kernel`、`knowledge_binder`、
  `capability_binder`、`harness_resolver`、`fixed_verifier`、`audit_log`。
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

同梱スキーマは `schema_version` を `1 | 2` にピン留めしています。一方
`ari/rqgm/state.py` は、Knowledge/Capability/Assurance の identity 付きで
エポックを凍結した場合に **v3** ペイロード（`scientific_identity` ブロックの
追加と、`execution_identity` 内の `scientific_assurance` コピー）を生成します
（`KCA_EPOCH_STATE_SCHEMA_VERSION`）。その形はここで宣言されていないため、
v3 スナップショットは同梱スキーマでは検証を通りません。すべて off の
エポックは v2 のままバイト同一です。

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
| `prompts[]` | プロンプトエントリ: テキストはソース参照（`kind` は閉じた集合 — 同梱テンプレートは `committed_template`、進化済みプロンプトは `checkpoint_file`、governed な utility-policy 本体は `policy`）、`prompt_hash`（`hash12`）**と**完全な `prompt_sha256` の両方; `spec_ref` は v1 では `null` |

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

### 動議パイプラインのレコード

レポート本体に加えて、`audit_epoch` は 4 種のレコードを
`rqgm_audit.jsonl` に追記する。いずれも上記の共有エンベロープを持つ。
**この 4 種には独立したスキーマファイルが存在しない** —
形状は `ari/rqgm/governance/_records.py` の frozen dataclass が定義し、
監査自身の self-audit ステップがカーネル経由で再検証する
（エンベロープは `validate_record_schema`、著者は
`validate_role_separation`、CK-ROL-001/002/003）。

**`evidence_bundle`** — 唯一の正当な著者は EvidenceClerk であり
（`build_evidence_bundle` は他の著者に対して `GovernanceRuleError` を送出する）、
閾値でフラグされた対象ごとに 1 束、`prompt_hash` は常に `null`
（clerk は決定論的でプロンプトを持たないため）。clerk の候補 ref は対象を名指しするレコード —
validated attack、utility record、raw attack、および K/C/A 由来の来歴型 —
に加えて、対象についての同一ロールの `comparison_observation` である。
ただし後者は**手がかり**としてのみ入る: 観測自身の `source_refs` が
独立検証のために取り込まれ、観測の ref 自体も列挙されるので、その除外は
黙って落とされるのではなく記録される。

`items[]` の各要素は `{kind, ref, content_hash}` で、`content_hash` は
`payload_hash(record)` — 本ページの他と同じ `hash12` 方式であり、第 2 の
ハッシュ方式は存在しない。`kind` は閉じた `record_type → kind` マップから
決まる:

| 許容される `record_type` | bundle の `kind` |
|---|---|
| `validated_attack` | `validated_attack` |
| `utility_record` | `utility_record` |
| `judgment_record` | `judgment_record` |
| `review_record` | `review_record` |
| `node_report` | `execution_provenance` |
| `harness_attestation` | `fixed_verifier_result` |
| `knowledge_skill_use` | `instruction_provenance` |
| `capability_binding` | `execution_authority` |

それ以外はすべて不適格である。あらゆる却下は `excluded_items[]` に
`{ref, reason}` として記録されるので、bundle は運んだものと同じくらい
明確に、拒んだものを述べる。判定は固定順で走り、最初に一致した理由が
記録される:

| 順 | 理由 | 意味 |
|---|---|---|
| 1 | `unresolvable_ref` | その ref がエポックのレコードスライスで解決しない。同時に `verification.all_refs_resolved` が `false` に反転する |
| 2 | `unadjudicated_raw_attack` | その ref が `raw_attack` である。raw attack は決して証拠にならず、証拠になるのはそこからジャッジが著した `validated_attack` だけである（不変条件 8-9） |
| 3 | `same_role_source` | その項目の著者ロールが対象のロールと等しい。同一ロールの出力は観測であって告発ではない — 対象についての `comparison_observation` や、対象自身の review record を除外するのがこれである |
| 4 | `inadmissible_record_type` | レコード型が上記マップの外 |
| 5 | K/C/A 整合性の理由群 | 自身の検査に落ちた来歴添付: アーティファクト水準（`missing_artifact_reference`、`invalid_artifact_reference`、`unsafe_artifact_reference`、`unresolvable_artifact_reference`、`artifact_digest_mismatch`）に加え、attestation / knowledge use / capability binding それぞれの型別検査。全集合は `_evidence.py` にある |

組み立ては代替ではなく除外を行う: 決して埋め合わせず、決して送出しない。
`verification` は `{checked_by: "evidence_audit_checker",
all_refs_resolved}` である。埋め合わせない以上、空の bundle は訴追を
支えられない — フラグされた対象でも `items` が空なら動議は生まれず、
`self_audit.findings` に `no_admissible_evidence` が 1 件残る。

**同一ロールの観測は予約済みで、まだ生成されない。** 設計上、あるコンポーネント
が同一ロールの同輩と食い違う場合 — たとえばあるレビュアが、自分を置き換え
うるレビュアと異なる採点をノードに与えた場合 — のためにガバナンスの
`comparison_observation` が予約されている。このレコードは
`subject_component_id` と `subject_role` を名指しし、そのビルダは
`admissible_as_evidence: false` を無条件に設定する: それは観測であって告発
ではない。上で clerk が実装している「手がかりであって証拠ではない」規則が
これであり、観測自身の `source_refs` を辿って一次アーティファクトを独立に
検証する一方、観測の ref 自体は `excluded_items` に載る（著者ロールが対象の
ロールと等しいときは理由 `same_role_source`、それ以外は
`inadmissible_record_type`）ので、除外は黙って起きるのではなく記録される。

**この経路は現状不活性である。** レコード型、その構築時不変条件、証拠組み立て
での手がかり追跡、subject ごとの信頼性集約はいずれも実装済みだが、**出荷され
ているコンポーネントでガバナンスの `comparison_observation` を
`rqgm_audit.jsonl` に発行するものは存在しない** — ビルダに製品コードの
呼び出し元が無い。したがってレポートの `observations` 配列は、出荷されるどの
実行でも空である。実行が示す挙動ではなく、予約された設計として扱うこと。
対照的に、一般の同一ロール除外は生きている: レコード型を問わず、著者ロールが
対象のロールと等しい候補すべてに適用される。

型名は無関係な別の形状と共有されている。プロンプト進化のシャドウ段は、候補と
現職の出力ハッシュおよび乖離要約からなる独自の `comparison_observation` を
`prompt_evolution.jsonl` に書き、これは後述の
`rqgm_prompt_evolution.schema.json` に記載されている。両者は `record_type`
ではなく、ファイルとフィールドで区別される。

**`impeachment_motion`** — 唯一の正当な著者は Auditor であり、したがって
Reviewer v4 がこの経路で Reviewer v3 に到達することはそもそもできない。
`target_component_id`、`target_role`、`charge`、`evidence_bundle_id`、
`bond_units`、`requested_action` を追加し、`source_refs` は bundle id
のみである。`requested_action` はレポートの推奨語彙の厳密な**部分集合** —
`demote` \| `warn` \| `quarantine` \| `retire` — であり、動議は決して昇格
させない。この集合の外の値は構築時に拒否され、`target_role: auditor`
（Auditor は自ロールを弾劾しない）も同様に拒否される。

**`governance_defense`** — Defender が動議ごとに 1 件を著し、`motion_id`、
`defense_text`、`procedural_default` を持つ。フォールバック経路では
`prompt_hash` は `null` となり、本文は下表に引用した固定の手続的既定文になる。

**`impeachment_outcome`** — GovernanceJudge が裁定済み動議ごとに 1 件を
著す。Task 09 の transition engine がレポート全体を解析せずに結果を消費
できるよう、独立レコードとして存在する。レポートの `adjudications[]`
エントリを写しつつ、そのエントリが参照するだけの情報を保持する:
`rationale` 本文（レポート側は `rationale_ref` を持ち、その値が本レコードの
id）と、決定論的ボードがジャッジの判定を上書きしたときに立つ
`clamped_by_board` である。`outcome` は閉じた集合 `upheld` \|
`partially_upheld` \| `dismissed` \| `inconclusive`。

**保証金台帳。** 濫訴の抑止は LLM を介さずに行われる。提起された動議ごとに
`rqgm.governance.bond_units_per_motion` が、
`max_motions_per_epoch × bond_units_per_motion` というエポック単位の訴追
予算に対して預けられる。清算は裁定結果の純関数である: `upheld` と
`partially_upheld` は単位を返還し、`dismissed` は没収し、`inconclusive` は
預けたままにする — 返還も没収もされない。コード上はこれを「次エポックへ
持ち越す」と述べているが、**持ち越しの機構は出荷されていない**: ステップ 1 は
現エポックのレコードスライスしか読まないので、未解決の動議が読み直される
ことはなく、次エポックは新たな信頼性分類から動議を導き直す。予算が尽きたら、
閾値が何と言おうとそのエポックではそれ以上の動議は提起されない。誤読しやすい性質が
2 つある。`remaining_budget` が数えるのは*提起*が消費した分だけなので、返還は
そのエポック内の提起余力を回復しない。また台帳は `audit_epoch` ごとに新規
構築されるので、境界のたびにリセットされる: エポックをまたいで罰を蓄積しない
以上、エポックごとに濫訴を続ける訴追者への抑止は弱い。結果はレポートの
`bond_accounting` ブロック — `posted`、`refunded`、`forfeited`、
`remaining_budget` — になる。これらは通貨ではなく割当カウンタであり、
コンポーネント間で価値が移動することはない。

**`self_audit` ブロック。** ステップ 8 は、他の全員に当てる物差しで司法自身を
監査する。そしてここでは orchestrator ではなく**カーネル**が最後の言葉を持つ。
pipeline がたった今生成した `evidence_bundle`、`impeachment_motion`、
`governance_defense`、`impeachment_outcome` のすべてが
`ConstitutionalKernel.validate_record_schema` と `validate_role_separation`
に差し戻される。レコードビルダ自身の拒否は早期の最適化にすぎず、保証はこの
再実行の側にある。バグを含む、あるいは進化したガバナンスコンポーネントが違反
レコードをレポートに紛れ込ませることはできない。ブロックの内容:

| キー | 内容 |
|---|---|
| `checked_components` | 検査したガバナンス主体をソートしたもの: auditor、evidence clerk、defender、governance judge |
| `kernel_violations_found` | 再検証で得た違反件数 |
| `findings` | 監査中に立った決定論的な所見。追加されうる種類はちょうど 4 つ: `same_role_prosecution_skipped`、`no_admissible_evidence`、`motion_refused`（訴追）と `judge_clamped_by_board`（裁定） |
| `escalations` | **ブロッキング**なカーネルレポートの各違反について `{code}:{subject_ref}`。**出荷される実行では常に空:** 再検証が回すのは、生成された 4 種のレコードに対する `validate_record_schema` と `validate_role_separation` だけであり、それらの型に対して両検査が立てられるのは `warn` のコードのみである（`CK-SCH-N01`、`CK-ROL-001` / `CK-ROL-002` / `CK-ROL-003`）。ブロッキングの `CK-SCH-G01` は `epoch_transition` か `governance_report` を、`CK-ROL-901` は `epoch_transition` か `registry_write` を必要とするが、そのいずれも自己監査には渡されない — レポート自身も同様である（ステップ 9 がステップ 8 の後に組み立てる） |
| `ban_recommendations` | 汚染クラスのエスカレーション — `CK-AUD-001`（監査ログ追記専用違反）、`CK-AUD-002`（監査ログ先頭の改竄）、`CK-AUD-003`（監査ログのハッシュ鎖の断絶）、`CK-ACC-002`（引退プロンプト本文へのアクセス）、`CK-ROL-901`（レジストリ書き手権限の偽装） — あるいは `contamination` / `clean_room_lineage_failure` の所見が巻き込む*はずの*主体。**予約された設計であって、実行が示す挙動ではない:** `escalations` は常に空であり（上記）、汚染系のどちらの種類もパイプラインが追加する 4 つの所見に含まれないため、このキーはどの境界でも `[]` のまま出荷される。T19 の両端はどちらも出荷されている — `_ban_recommendations` がこのキーを書き、RegistryTransitionEngine の `_ban_targets` がそれを読む — 欠けているのは、そこに入れる汚染シグナルを上流で生む生成者だけである。禁止が適用されるのは、その上で実際に retired のコンポーネントに対してのみである |
| `stats` | `auditor_motion_precision`、`judge_board_clamp_count`、`defender_substantive_rate`。動議が 1 件も提起されなかったとき、2 つの比率は `null` になる — 決して補完されない |

`governance_report.schema.json` が宣言しているのは最初の 4 キーだけで、
`ban_recommendations` と `stats` は追加的であり、未宣言のプロパティとして
運ばれる。カーネルが利用できないか、再検証自体が送出した場合、ブロックは
縮退し `degradation_reasons` に `self_audit_degraded` が加わる。

### 監査の決定論予算

監査の LLM 継ぎ目はちょうど 3 か所である — ステップ 4（訴追）、ステップ 5
（弁護）、ステップ 6（裁定）がそれぞれ省略可能なレンダラを取る。他の
ステップにモデルは一切入らず、エポックの監査ログスライスと凍結レジストリ
だけで走る。いずれの継ぎ目でも先に規則が決め、モデルは境界域でのみ問われる。

**訴追は規則優先、LLM は次点。** `classify_target`
（`ari/rqgm/governance/_prosecution.py`）は ReliabilityMonitor のエントリを
1 件読み、3 つの答えのいずれかを返す。`ATTACK_THRESHOLD`（2）件以上の
validated attack が束ねられているか、信頼性スコアが `RELIABILITY_FLOOR`
（0.4）未満なら、そのコンポーネントは**無条件に提起対象**となる。
validated attack がちょうど 1 件、またはスコアが
`[RELIABILITY_FLOOR, RELIABILITY_FLOOR + BORDERLINE_MARGIN)` すなわち
`[0.4, 0.5)` に入るときが**境界域**であり、このときに限って LLM Auditor の
プロンプトが走る。それ以外は放置される。3 つの閾値はいずれもモジュール定数で、
カーネルの規則表と同じくコードに固定されている。設定可能なのは
`rqgm.governance` 配下の予算だけである。境界域で auditor の応答が得られない、
あるいは解析できない場合は何も提起されない — 現職推定であり、
`LineageDecision.fallback_continue` と同じ形である。

決して訴追されない対象が 2 種ある:

- **`tier: fixed` のコンポーネント。** tier 検査は分類器の最初の文であり、
  閾値を 1 つも読む前に「訴えなし」を返す。したがって固定コンポーネントは、
  いくつの攻撃に名指しされても訴追不能である。固定された手続は制度上の現職
  ではなく憲法上の機構であり、その整合性の指摘は該当アーティファクトを停止・
  修復するのであって、弾劾の競争には入らない。
- **ロールが `auditor` の対象。** 唯一の Auditor は自ロールに対して提起でき
  ないため、その対象はスキップされ、黙って落とされる代わりに
  `self_audit.findings` に `same_role_prosecution_skipped` として記録される。

`audit_epoch` はステップの失敗で中断することがない。9 ステップのそれぞれが
全域的な決定論フォールバックを持ち、それを取ると `degraded` が `true` に
反転し、`degradation_reasons` にトークンが 1 つ追加される。

| ステップ | 失敗時 |
|---|---|
| 1 観測収集 | そのエポックのレコードスライスが空になるので、ステップ 2-6 は扱う対象を持たない |
| 2 信頼性評価 | 信頼性エントリなし。ステップ失敗とは独立に、そのエポックに何も著さなかったコンポーネントは `reliability_score: null` と `insufficient_data: true` を得る — スコアは決して捏造されず、そのコンポーネントは validated attack の件数を通じて訴追可能なままである |
| 3 証拠組み立て | bundle なし、したがって動議なし。項目単位の失敗はこの行に到達しない: 組み立ては送出せず、除外する（上記） |
| 4 訴追判断 | 動議なし。**境界域**の分類で auditor 呼び出しが利用不可または解析不能なときも何も提起されない（現職推定）。閾値を明確に超えた分類は規則ベースで、LLM を一切必要としない |
| 5 弁護生成 | 弁護は固定の手続的既定文 *"no substantive defense generated; incumbent presumption applies"* となり、`procedural_default: true` が立つ |
| 6 裁定 | ジャッジが利用不可または解析不能なら `dismissed`、すなわち現職に有利に倒れる（このフォールバックにも後述のボードによるクランプが適用される）。ボード採点の失敗は `inconclusive` となり、その保証金は返還も没収もされず預けられたまま — 動議は決着させられるのではなく未解決のまま残る。governance judge 自身を対象とする動議は忌避され、outcome レコードを生まない。並行する候補評価の失敗は `candidate_evaluations` を空にする |
| 7 リプレイプール更新 | プール更新はスキップされ、フラグされる |
| 8 ガバナンス自己監査 | カーネル再検証がスキップされる: `kernel_violations_found` は 0 のままで、エスカレーションも上がらない。ステップ全体が失敗した場合、ブロックは `checked_components` と `stats` が空のスタブに退避する |
| 9 レポート生成 | 送出しうる**唯一の**ステップ。呼び出し側の fail-open catch（`ari/rqgm/runtime.py`）がログを残してレポートなしで返る。ファサードは pipeline の復帰後にのみ監査レコードを追記するため、そのエポックはガバナンスレコードを 1 件も残さず、実行は継続する |

スキーマ上 `degradation_reasons` は単なる文字列配列である — 語彙を強制する
のは enum ではなく発行側である。出荷されている pipeline はこれら以外の形を
発行しない:

| トークン | 発行される条件 |
|---|---|
| `step_failed:observe`、`step_failed:assess_reliability`、`step_failed:assemble_evidence`、`step_failed:prosecute`、`step_failed:defend`、`step_failed:adjudicate`、`step_failed:evaluate_candidates`、`step_failed:update_replay_pool` | 該当ステップが送出し、上表のフォールバックを取った |
| `auditor_llm_fallback:{component_id}` | 境界域の対象に対する auditor 呼び出しが利用不可または解析不能だった |
| `defender_llm_fallback:{motion_id}` | 弁護が手続的既定にフォールバックした |
| `judge_llm_fallback:{motion_id}` | 使えるジャッジ標本が得られず、動議は却下された |
| `board_failure:{motion_id}` | ボード採点が送出し、動議が `inconclusive` になった |
| `self_adjudication_recused:{judge_component_id}` | 動議が governance judge を対象としたため、外部裁定に委ねて未解決のまま残された |
| `replay_pool_update_skipped` | 追加すべき upheld ケースがあったが、プールが `append_case` を公開していない |
| `llm_budget_exhausted` | [`max_llm_calls_per_audit`](configuration.md#execution-mode-and-rqgm-governance-opt-in) の上限に達した、または Task 12 の予算マネージャが呼び出しを拒否した |
| `self_audit_degraded` | 自己監査のカーネル再検証が利用不可、または送出した |

`step_failed:produce_report` というトークンは存在しない: ステップ 9 は縮退
しない唯一のステップである。

`llm=None` のとき監査はこれら規則のみの経路で完全に走り、同じ入力に対する
2 回の実行は `created_at` を除去すればバイト同一のレコードを生む。

**ジャッジは LLM が正常に働いていても拘束される。** ReplayBoard と
AnchorBoard のスコアは GovernanceJudge が裁定する前に計算され、評決は
それらに拘束される — ノードの `results.json` の measurements が、切り詰め
られた artifact テキストに対する LLM の読みを上書きするのと同じ優先関係
である。ボードスコアは対象について蓄積されたケース結果の平均であり、用い
るケースは case id 順で最大 `rqgm.replay.max_cases_per_epoch` 件。動議が
retirement を俎上に載せる場合（`retire` を要求する、またはすでに
quarantine 状態のコンポーネントを対象とする場合）、上限は
`rqgm.replay.max_cases_for_retirement` に上がり、Task 12 の予算マネージャ
が存在すればさらに引き下げうる。一致するケースが 1 件もなければボード
スコアは `null` — *利用不可*であって、捏造された数値ではない。

続いて評決は、現職に対する*利用可能な*ボードスコアの平均と突き合わされる。
2 つの閾値は `ari/rqgm/governance/_adjudication.py` のモジュール定数であり、
設定ではなくコードに固定されている:

| 現職のボード平均 | ボードが拒む評決 | クランプ先 |
|---|---|---|
| ≥ 0.8 (`BOARD_HIGH`) | `dismissed` 以外のすべて | `dismissed` |
| ≤ 0.2 (`BOARD_LOW`) | `dismissed` | `partially_upheld` |

どちらのボードも利用できないときは拘束が働かず、評決はそのまま残る。
クランプは上表のステップ 6 フォールバックの後、最後に適用されるので、
フォールバックも拘束される: ジャッジ不在による `dismissed` も、対象の
スコアが ≤ 0.2 なら `partially_upheld` になる。クランプは
`impeachment_outcome` レコードに `clamped_by_board: true` を立て、
`self_audit.findings` に `judge_clamped_by_board` の finding を追加し、
`self_audit.stats.judge_board_clamp_count` に計上する — 現職側または挑戦
側へ系統的に偏るジャッジは、静かに効いてしまうのではなく監査上に現れる。

候補プロンプトは同じボードで採点され、ジャッジは**一切**関与しない:
利用可能なボードスコアの最小値が 0.6 (`CANDIDATE_PASS_THRESHOLD`) 以上
なら `pass`、そうでなければ `fail`、どちらのボードもスコアを出せなければ
`inconclusive` となる。`rqgm.replay.use_cached_results`（既定で有効）の
とき、配線されている Task 12 のガバナンスキャッシュがプールの蓄積ケース
結果より先に参照され、そこから書き戻される。
`candidate_evaluations[].cached` が報告するのはこの設定であって、
キャッシュが存在したか、個々の参照がヒットしたかではない。

`rqgm.governance.jury_panel_enabled` を有効にすると、ジャッジは 3 回
サンプルされ多数決で決まる。同数のときは `dismissed` >
`partially_upheld` > `upheld` という固定順で現職側に倒れる。既定は
`false` で、1 標本で決まる。

失敗ではなく構造によって制約されるレポートフィールドが 2 つあり、いずれも
縮退トークンを立てない。

**AnchorBoard には held-out コーパスが要り、それを供給するのは paper
フェーズだけである。** 両ボードは `audit_epoch` に渡されたプールから
ケースを読む: ReplayBoard は `pool.cases`、AnchorBoard は
`pool.anchor_cases` である。探索実行が渡すプールである
`AdversarialReplayPool` は `anchor_cases` 属性を定義していないので、その
経路で AnchorBoard はスコアではなく*利用不可*を報告する: `anchor_score` は
すべての裁定・候補評価で `null`、`budget_usage.anchor_cases_used` は 0 の
ままで、ジャッジ判定をクランプしうる現職側のボード平均も候補の合格判定も
ReplayBoard だけで決まる。held-out アンカー集合が監査に届くのは
paper-archive フェーズだけで、そこではそれを担ぐプール形状のアダプタ
（`ari/rqgm/paper_anchor.py`）に差し替えられる — そのコーパス自体も既定では
無効である（後述の `paper_anchor_corpus.jsonl` の項を参照）。`null` の
アンカースコアは「held-out コーパスが無かった」と読むべきで、低スコアと
読んではならない。

**`replay_pool_updates.retired` は不活性である。** 実際に埋まるのは `added`
だけで、その中身はこのエポックの validated attack が採録されたリプレイ
ケースと、`upheld` / `partially_upheld` になった動議の背後にある validated
attack の ref である。`retired` 配列は空で初期化され、そこへ追記するコードは
存在しない: ケースの引退はプール内部の操作であり（`evict_to_cap` は
スナップショット上でケースを `evicted` に印付けるだけで、JSONL は採録された
全行を保持する）、監査はそれをここに露出しない。*引退したプロンプト*に由来
する陳腐化はフロンティア修復（Task 10）が扱い、このフィールドでは報告され
ない。

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
| `validated_attack` | `vat_%06d` / `judge` | `case_type`、`raw_attack_id`、`judgment_id`、`validated`、`verdict`、`severity`、`expected_behavior`（ケースタイプ依存の `ロール → 期待される振る舞い` マップ）。`valid` / `partially_valid` 判定に対して**のみ**存在（裁定必須、不変条件 9）。説明責任バインディングを保持 — 下記参照 |

#### `validated_attack` の説明責任バインディング

ロールは**観測される**もの、コンポーネントは**拘束される**もの、そして
バインディングは**裁定の後にのみ**鋳造される。`validated_attack` の 2 つの
ターゲット様フィールドは同義語ではない:

| フィールド | 値空間 | 読み手 |
|---|---|---|
| `affected_components` | ロール名（`["reviewer"]`）— 誰が関与しているかという複数形の観測。ロールは攻撃が正直に知りうる唯一のものであり、ロールを制裁するものは何もない。（この名前はロールを保持する。改名すれば保存済みの全レコードを書き換えることになるため、そのまま維持している） | RQGM viz の read model（`RqgmValidatedAttackV1.affected_components`）。FailureSummary は**読まない** — その `affected_roles` は下記 `expected_behavior` のキーである |
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

**`affected_roles` はどこから来るか** — 名前に反して `affected_components`
からではありません。`build_failure_summary`
（`ari/rqgm/adversarial/records.py`）は `affected_roles` を
`tuple(sorted(validated.expected_behavior))` に設定します: すなわち第 3 の
ロール様フィールド `expected_behavior`（`AdversarialRound._expected_behavior`
がレコードに刻む `ロール → 期待される振る舞い` マップ）のソート済み**キー**
です。このマップは**ケースタイプ依存**で、7 つの探索タイプはすべて
`reviewer` / `generator` / `judge` をキーとするモジュールレベルの汎用
テンプレートを取り（したがってレコードはバイト同一のまま）、
`paper_self_preference` だけが独自の 2 キー `paper_reviewer` と
`paper_writer` を供給します。両方のバインディングが解決される paper ケース
では、2 つのフィールドは構造上ずれます: ラウンドは解決可能なロールごとに 1 件
のレコードを書き、各レコードは `affected_components` に自身の単一ロールだけを
名指ししますが、両レコードは同じ 2 キーの `expected_behavior` を保持する —
よって両方の FailureSummary が両ロールを報告します。一方を意図して他方を読む
のは同義語の取り違えではなく、実際の誤りです。

### `rqgm_utility_record.schema.json`

**目的:** governed-utility の監査レコード 1 件; 敵対的ペナルティチャネルが
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
| `cases[]` | AdversarialReplayCase: `case_id`（`adv_case_%05d`）、`case_type`（同梱スキーマの探索用 7 タイプ。paper runtime は後述するフェーズ外 inert の 8 番目を追加）、`validated_attack_id`、`severity`、`admitted_epoch` / `last_confirmed_epoch`、`status` は `active` \| `evicted`（eviction は論理のみ）、`replay_view`（完全な資料 — `artifact_refs`、3 つのレコード id、そしてレコードの `expected_behavior` マップを値でコピー; ロール `clean_room_generator` には拒否）と `abstract_view`（汚染安全な FailureSummary — `case_type`、`failure_pattern`、`violated_expectation`、`affected_roles`; 生の攻撃 / 防御テキストなし） |

2 つのビューは同じロール情報を分割して持ちます。
`replay_view.expected_behavior` は ValidatedAttackRecord から値で取った
`ロール → 期待される振る舞い` マップであり、`abstract_view.affected_roles` は
そのマップのソート済みキー集合そのもの（それ以上ではない）です（
本ページの「`validated_attack` の説明責任バインディング」節
を参照）。マップがケースタイプ依存であるため、リプレイされるケースが名指しする
ロールはその `case_type` に依存します: 7 つの探索タイプは汎用の
`reviewer` / `generator` / `judge` テンプレートを共有し、paper フェーズの
`paper_self_preference` ケースは `paper_reviewer` と `paper_writer` を名指し
します。同梱スキーマでは `abstract_view` が `additionalProperties: false` —
汚染境界はコンプレッサの規律だけでなく宣言された形として強制されます — 一方
`replay_view` にはその制約がなく、代わりに capability で制御されます
（ロール `clean_room_generator` には拒否）。

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
| `evolvable` / `epoch_introduced` | 進化の適格性 + 来歴。v1 で進化させないテンプレートの登録規則: 専用ロールを新設せず、Task 02 の閉じたロール語彙のうち**最も近い**ロールの下に `evolvable=False` で登録します。ロールキーを増やすと `active_prompt_hashes` が変わり、ひいては `registry_version` が変わるのに、機能上の利得がないためです。現在 6 行がここに属します — `generator` の下に `agent/system`、`pipeline/keyword_librarian`、`viz/wizard_chat_goal`、`viz/wizard_generate_config`、`router` の下に raw ロードの `orchestrator/root_idea_selector`、`reviewer` の下に `governance/auditor`（最後の 1 件は、`auditor` が**コンポーネント**としては登録可能なロールである（`auditor_v1` は founding）にもかかわらず同じ先例に従う — 弾劾可能性はコンポーネントに由来し、プロンプトのロールに由来しないため）。ロール内の行順は意味を持ちます: レジストリの「最後のアクティブが勝つ」ロールアップのため、進化する primary が**最後**に来る必要があり、これらはいずれも自ロールの primary より前に置かれます。なお `evolvable=False` は別の理由でも使われます — 3 つの `rqgm/proposal_*` テンプレートは説明責任のために governed であり、ロールの代替ではありません |
| `spec` | 振る舞い契約: `role_instruction`、`constitutional_constraints[]`、`input_contract.required_fields[]`、`output_schema`、任意の `rubric` / `calibration_policy` / `budget_policy`。`output_schema` はちょうど 1 つのキー `__reply__` を応答の**種別**（`bare_index` \| `json_array` \| `json_object` \| `freeform`; 不在なら `json_object`）に予約します; それ以外のキーはすべて必須 JSON フィールド名で、値は型名（`list`、`dict`、`string` / `str`、`float`、`int`、`bool`）です。消費者は `check_output_against_schema`（`ari/rqgm/prompt_evolution.py`）で、必須フィールドのループでは `__reply__` をスキップします。この予約はコード側にのみ存在します: 同梱スキーマは `output_schema` を必須オブジェクトとして宣言するだけで、`__reply__` については何も述べません |

**クセ（凍結）: 2 件の founding spec は `required_fields` を空で記録する。**
`input_contract.required_fields[]` は通常、テンプレートから抽出した
プレースホルダ集合（ソート済み）です。コミット済みテンプレートのうち 2 件は
例外で、`orchestrator/lineage_decision` と
`orchestrator/root_idea_selector` は `RAW_LOADED_KEYS`
（`ari/rqgm/prompt_spec.py`）に列挙され、その founding spec は代わりに `[]`
を記録します。これは契約上の選択ではありません。どちらの本体も
（`ari/orchestrator/lineage_decision.py` と
`ari/orchestrator/root_idea_selector.py` の `_load_system_prompt_versioned`
で）そのままシステムプロンプトとして読み込まれ、`.format` されることは
決してないため、「reply ONLY with JSON: `{…}`」の行にあるリテラルの JSON
波括弧が疑似プレースホルダとして登録されてしまいます: 抽出器は `"action"` と
`"chosen_index"` を報告します — 引用符付きの JSON キーであって入力名ではありません。それらを
必須入力として記録することは何も記録しないより悪いので、founding テーブルは
何も記録しません。これはテストで固定された観測上の例外
（`ari-core/tests/test_rqgm_prompt_spec.py`）であって、真似すべきパターンでは
ありません: 入力を取らない新しいテンプレートは、抑制エントリを増やすのでは
なくプレースホルダを持たないようにすべきです。

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
ハッシュされない）、`exploration_mode`、`seed_node_id`、`switch_journal[]`、
さらに呼び出し側が評価条件を pin したときに限り `evaluation_condition_id`。
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

各行はさらに `created_at` と Manuscript Complete の `manuscript_*` ブロックを
持ちます: ドラフトと同時に書かれるバインディング項（`manuscript_bound`、
`manuscript_mode`、`manuscript_attempt_id`、`manuscript_input_fingerprint` /
`manuscript_binding_digest` / `manuscript_profile_digest` /
`manuscript_context_digest` / `manuscript_readiness_digest` /
`manuscript_brief_bundle_digest` の pin、`manuscript_section_brief_digests`、
`manuscript_allowed_evidence_ids` / `manuscript_contextual_negative_ids` /
`manuscript_forbidden_evidence_ids` のリスト、`manuscript_required_disclosures`
と `manuscript_omission_count`）と、その後に
`record_paper_draft_manuscript_evaluation` が付ける決定的な診断
（`manuscript_candidate_status`、`manuscript_hard_disqualified` と
`manuscript_hard_disqualification_reasons`、
`manuscript_candidate_artifact_sha256`、`manuscript_candidate_gate_digest` /
`manuscript_candidate_gate_status`、および
`manuscript_contextual_negative_evidence_mentions` /
`manuscript_forbidden_evidence_mentions` /
`manuscript_missing_required_disclosures` の所見）。この付与だけは
best-effort **ではありません**: 対象レコードのみを last-record-wins で書き直し、
ファイルを読み直して値が round-trip しなければ raise します — enforce モードの
適格判定がこれらに依存するためです。既定の `manuscript.mode: "off"` では
ブロックは空 / false の既定値であり、`manuscript_hard_disqualified` の行は
stale な行と同じくフロンティアから除外されます。

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
`max_bootstrap_label_fraction` の上限は、コーパス**と** held-out 部分集合の
双方に対して機械強制されます。上限を超えるとコーパス全体が拒否され、
raise せずアンカーなしの on-ramp に縮退します。**デフォルト OFF**（`anchor.enabled: false`）:
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

**コーパスはどこから来るか。** この統計は専用のコーパスを持ちません:
`reviewer_anchor_cases(pool)` — レビュアのアンカーユーティリティが使うのと同じ
`paper_anchor_corpus.jsonl` プール — を、ラベル次元を 1 つだけ追加して、
すなわち上述の各ケースの `authorship`（`human` \| `ai`）フィールドとともに
読みます。したがって AI/人間の split はアンカーコーパスの性質です。split を
持たないコーパスでは `margin` は `0.0` となり、母集団シグナルは沈黙しますが、
アドバーサリは残る 2 つの過剰受理シグナル — クレームゲートの指摘、または
ground truth が `reject` のアンカーケースを現職が受理したという直接の
ケース単位の不一致 — で依然として訴追します。コーパスがまったく無い場合
（`anchor.enabled` が `false` である既定）は、見つけるべき過剰受理ケースが
存在せず、ラウンド自体が発火しません。

ノブは `rqgm.paper.self_preference.*` で、実効 `rqgm_archive` paper モードの
下でのみ意味を持ちます: `enabled: true`; `sample_size: 8`（エポックあたりに
採点する held-out ケース数。決定論的に `case_id` 順の先頭 N 件。同じ数が
過剰受理サブセットにも 2 度目に適用されるため、攻撃されるケース数の上限にも
なります — さらに共有のエポック単位アドバーサリ呼び出し上限が掛かります）;
`accept_threshold: 0.6`（レビュアが「accept した」と見なす閾値。ガバナンスの
`CANDIDATE_PASS_THRESHOLD` — こちらも `0.6` — を写したもの）は
過剰受理の事前シグナル用に攻撃バンドルへ運ばれるだけで、マージン計算自体は
これを**使わず**レビュアの `accept_recommendation` を二値化します;
`margin: 0.1`（決定論的な事前シグナルを発火させる AI 対人間の差）。1 つの
ノブは**宣言されているが未配線**です: `corpus_path: ""` は「`""` はアンカー
コーパスを再利用し、パスを与えると専用の authorship セットで上書きする」と
説明されており、`""` 側の挙動はコードのとおりですが、
`rqgm.paper.self_preference.corpus_path` を読むコードは存在せず、ここにパスを
設定しても現状は何の効果もありません。ローダが解決するコーパスパスは
`rqgm.paper.anchor.corpus_path` だけです。

**8 番目のアドバーサリタイプ。** `paper_self_preference` は Python
`ADVERSARY_TYPES` タプル（`ari/rqgm/adversarial/records.py`; 書き込みパスの
妥当性チェック `validate_raw_attack` が使用）の 8 番目のメンバで、paper
フェーズ用に追加され、それ以外では inert です; 同梱の
`rqgm_attack_records.schema.json` の `adversary_type` / `case_type` enum は
7 つの**探索**タイプを文書化します。`paper_self_preference` ケースは
`paper_reviewer` ロールを関与させ、Layer-0 クレームゲートが不誠実と確認した
ドラフトではさらに `paper_writer` も関与させます。どちらも paper モード下では
登録済みの現職（`paper_reviewer_v1` /
`paper_writer_v1`）を**持つ**ため、Task-15 の `target_component_id`
バインディングが発火し、validated-attack → 弾劾チェーンが本番で動きます;
paper フェーズ以外では両ロールとも `""` に解決され、探索はバイト同一の
ままです。

## チェックポイントファイルインベントリ

ファイルごとの完全な挙動（生成条件、真実 vs スナップショット、resume の
意味論）は
[ファイルフォーマットリファレンス](file_formats.md#rqgm-epoch-governance-files-opt-in-ari_rqgm-mode)
に文書化されています; この表はファイルとスキーマ・所有者の対応のみを示し
ます。以下の固定名ファイルはすべて `PathManager.META_FILES` に登録され、
そのうち JSONL は paper-archive の 2 つ（`paper_draft_archive.jsonl`、
`paper_anchor_corpus.jsonl`）を除いて `ari/paths.py` のトレースファイル
集合にも入ります。また `proposals/` と `rqgm_prompts/` ディレクトリは
ノードレポートのディレクトリブロックリスト
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
