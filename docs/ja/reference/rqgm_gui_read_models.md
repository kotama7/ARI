---
sources:
  - path: ari-core/ari/viz/v1/rqgm.py
    role: implementation
  - path: ari-core/ari/viz/v1/dto.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/tests/test_gui_v1_rqgm.py
    role: test
last_verified: 2026-07-27
---

# RQGM GUI 読み取りモデル

12 本の `GET /api/v1/runs/{run_id}/rqgm/*` エンドポイントは、チェックポイント
にコミット済みの RQGM 成果物に対する**オフラインの射影器**です。このページは
各ペイロードが何を意味し、どの成果物から来ており、証拠が裏づけないガバナンス
主張を UI が描画できないよう API がどの真実規則を強制するかを文書化します。

これらの成果物が含む*レコードの形*（スキーマ、id 形式、ハッシュ規律）は
[RQGM スキーマリファレンス](rqgm_schemas.md)を参照してください。転送層の関心事
（エラーエンベロープ、カーソル、認証）は
[REST API → `/api/v1`](rest_api.md#apiv1正準)、ガバナンス機構そのものは
[RQGM アーキテクチャ](../concepts/rqgm_architecture.md)を参照してください。

## 基本規則

読み取り側（`ari-core/ari/viz/v1/rqgm.py`）は 4 つの制約に縛られており、
それがこのページのすべてのペイロードの形を決めています:

1. **`ari.rqgm` を決してインポートしない。** 読み取りモデルはコミット済みの
   チェックポイント成果物を直接パースし、カーネルやスコアポリシーの判断を
   一切再実行しません。再現される唯一の RQGM 演算はスキーマ版付きのイベント
   ダイジェスト契約です: 旧 schema-v1 レコードはペイロードのみの短縮ハッシュ
   `hash12(canonical_json(payload))` を、schema-v2 レコードはリプレイに影響
   する封筒フィールド全体（`schema_version` / `event_id` / `event_type` /
   `transaction_id` / `payload` / `prev_event_hash`）に対する完全な SHA-256 を
   使います。viz → governance のインポート辺が禁止されているため意図的に
   二重実装されています。本番ヘルパとのパリティは
   `ari-core/tests/test_gui_v1_rqgm.py` でピン留めされています。
2. **コミット済みレコードのみ。** JSONL 末尾の部分行（追記の途切れ）は黙って
   無視され、対応する commit を持たない `epoch_transaction_prepare` 以降の
   遷移イベントは現在状態へ決して取り込まれません — `ari.rqgm.store.committed_events`
   の鏡像です。「対応する」の判定は `transaction_id` によります: 異なる
   トランザクション id を持つ commit（や途中のイベント）は、保留中の
   トランザクションを閉じることも、それに合流することもありません。
3. **壊れるのではなく縮退する。** ハッシュチェーンの破損や陳腐化した rollup は
   整合性フラグを反転させ `degraded_reasons` を追加します; 成果物が壊れていても
   500 ではなく HTTP 200 と正直なフラグを返します。存在しないソースは `None`
   であり、クリーンやゼロとして表示されることはありません。
4. **読み取り専用。** ファイル書き込み、`viz.state` への接触、`os.environ` の
   変更はいずれも行わず、**変更用エンドポイントは存在しません** — GUI は
   ガバナンス操作を実行できず、観測できるだけです。

## capability ゲーティング

`GET .../rqgm/capabilities` は、非 RQGM ランに対しても応答する唯一の RQGM
エンドポイントです。capability の検出は成果物の存在のみに基づきます:

| シグナル | 導出元 |
|---|---|
| `enabled` | `{ckpt}/rqgm_state.json` が存在し、**かつ** `rqgm_enabled` を記録している（既定値は `mode == "ari_rqgm"`）。ファイル不在 ⇒ 理由 `"simple_bfts run"` 付きの `enabled: false`。 |
| `mode` / `mode_source` | `rqgm_state.json` に永続化された `mode` とその来歴。 |
| `paper_mode` | `{ckpt}/paper_archive_state.json` の存在。実行モードと論文モードは**独立した軸**であり、4 通りの組み合わせすべてが有効です。 |
| `reasons` | capability がオフ / 読めない理由 — 空の成功主張には決してなりません。 |

残り 11 本のエンドポイントは、`rqgm_state.json` を持たないランに対して型付きの
`404 not_found` エンベロープ（message: "not an RQGM run … simple_bfts run"）を
返します。これは未知の run id に対する `404` とは区別されます。

## 成果物 → エンドポイント対応

決定的な区別は**真実ログ対スナップショット**です: 追記専用でハッシュ連鎖した
ログが真実源であり、rollup / スナップショットファイルはそれを*検証するためだけ*
に読まれます — 決して現在状態にはなりません。

| エンドポイント | 真実源（状態はここから来る） | スナップショット（検証 / 来歴のみ） |
|---|---|---|
| `…/capabilities` | — | `rqgm_state.json`、`paper_archive_state.json`（存在 + 永続化モード） |
| `…/overview` | `rqgm_transitions.jsonl`（コミット済み replay）、`rqgm_audit.jsonl`（チェーン） | `rqgm_registry.json`（rollup チェック）、`epoch_state.json`（クロスチェック）、`meta.json`（`constitution_hash`） |
| `…/registry` | `rqgm_transitions.jsonl` の replay | `rqgm_registry.json`（`as_of_event_hash` の比較のみ） |
| `…/transitions` | `rqgm_transitions.jsonl` | — |
| `…/audit` | `rqgm_audit.jsonl` | — |
| `…/policies` | `rqgm_transitions.jsonl` の replay（`utility_policy` ロールのプロンプト） | プロンプトの `source.path` が参照する登録済みポリシー本体ファイル（配信前にハッシュ検証される） |
| `…/score-rewrites` | `rqgm_transitions.jsonl`（T20 の supersession）を `rqgm_audit.jsonl`（`SelectiveErasureEvent` / `FrontierRebuildEvent`）と join | — |
| `…/nodes/{node_id}/lineage` | `rqgm_adversarial_cases.jsonl`、`rqgm_audit.jsonl`、およびツリービュー経由のノードの `metrics` センチネル | — |
| `…/epochs`、`…/epochs/{epoch_id}` | `rqgm_transitions.jsonl`（`epoch_open` ペイロード + 境界のクローズエントリ）、`rqgm_audit.jsonl`（`fallbacks` 用の `epoch_transition` レコード） | `epoch_state.json` は状態としては**使われない** |
| `…/evolution` | `prompt_evolution.jsonl`、`rqgm_meta_outputs.jsonl`、および採用 join 用のレジストリ replay | — |
| `…/paper-archive` | `paper_draft_archive.jsonl`、`paper_anchor_corpus.jsonl`、`rqgm/paper_self_preference_stat.json`、`full_paper.tex`（存在） | `paper_archive_state.json`（永続化モード + 凍結された論文ポリシー） |

体得しておく価値のある帰結が 2 つあります:

- `rqgm_registry.json` は**rollup** であり、レジストリそのものではありません。
  `…/registry` はコミット済み遷移を replay して構成要素とプロンプトを再構築し、
  rollup は `verified` / `rollup_as_of_event_hash` / `replay_tail_event_hash`
  を通じてのみ報告します。
- `epoch_state.json` が `current_epoch` を設定することは決してありません。
  `…/overview` は最後にコミットされた `epoch_open` から現在エポックを導出し、
  スナップショットが食い違う場合は縮退理由（"snapshot ahead of the truth log"）
  を追加します。

## 整合性フラグと縮退の意味論

`…/overview` は 3 つの**三値**フラグを持ち、`…/transitions` と `…/audit` は
該当するものを `chain_ok` として再掲します:

| フラグ | `true` | `false` | `null` |
|---|---|---|---|
| `transitions_chain_ok` | `rqgm_transitions.jsonl` の全行が検証を通る: `event_hash` がその行の宣言したイベント封筒を覆い（ペイロードのみを覆うのは旧 schema-v1 行だけ）、`prev_event_hash` が連鎖する（先頭行は `""` から）。 | ハッシュ不一致またはチェーン断絶を検出。走査は継続するのでデータは提供されるが、フラグが立つ。 | ファイルが存在しない。 |
| `registry_verified` | `rqgm_registry.json` の `as_of_event_hash` がコミット済み遷移の末尾と一致する。 | rollup が陳腐化している、またはログより先行している。 | rollup が存在しない / 読めない、または比較対象の遷移末尾が無い。 |
| `audit_chain_ok` | `rqgm_audit.jsonl` が独立したチェーンとして検証を通る。 | 断絶を検出。 | ファイルが存在しない。 |

`null` は一級の回答です: **存在しないソースがクリーンとして描画されることは
決してありません。** フラグと並んで `degraded_reasons` は人間可読な文字列の
有界リスト（ソースあたり最大 3 件）で、問題のイベント id とバイトオフセットを
挙げます。例: `"rqgm_transitions.jsonl: hash chain broken at evt_000117 (byte 40213)"`。
読み取り側がリクエストを失敗させずに出す他の理由: パースできない終端済み JSONL
行（スキップ）、閉じたレジストリ語彙の外にある status 値（一覧と件数から除外）、
バイト列が登録済み `prompt_hash` に一致しなくなったポリシー本体（`body: null`
— 拒否され、黙って配信されることはない）、`constitution_hash` を持たない
`meta.json`。

## 2 つの語彙、2 つの状態機械

レジストリのライフサイクル status とノードのスコア状態は**別々の状態機械で
あり、1 つのフィールドや 1 つの凡例に混在させてはなりません**。DTO がこれを
構造的に強制します: 2 つのリテラル型が別物なので、レジストリ status が入る
べき場所にノードスコア状態を載せたペイロードは存在し得ません。

**レジストリ構成要素 / プロンプトのライフサイクル — 10 値**
（`ari.rqgm.events.STATUS_VALUES` そのまま、凍結契約）:

| Status | 読み取りモデルでの意味 |
|---|---|
| `candidate` | 登録済みだが未検証。 |
| `validated` | 検証を通過したが未稼働。 |
| `shadow` | 比較のためアクティブ構成要素と並走。 |
| `probationary_active` | 保護観察下で稼働。**アクティブ**として数えられる。 |
| `active` | 稼働中。**アクティブ**として数えられる。 |
| `warning` | 制裁姿勢。 |
| `probation` | 制裁姿勢。 |
| `quarantine` | 制裁姿勢（`emergency_quarantine` の対象でもある）。 |
| `retired` | 運用から撤退。 |
| `banned` | 恒久的に排除。 |

`active` と `probationary_active` が、`active_components` /
`active_prompt_hashes` が用いる凍結されたアクティブ集合を成します
（ロール → id/ハッシュ。決定論的な replay 順で最後の登録が勝ちます）。

**ノードのスコア状態 — 5 値**（`NodeScoreStateV1`）:

| 状態 | 主張の根拠 |
|---|---|
| `computed` | そのノードの `UtilityRecord`、または陳腐化センチネルを持たないノードメトリクス。 |
| `recomputed` | `recomputed_in_epoch` を持つ `UtilityRecord`、または消去イベントの `recompute_node_ids` に現れるノード。 |
| `stale` | ノードメトリクスが無効化理由なしに `_stale` を持つ。 |
| `invalidated` | `_stale_reason == "utility_invalidated"`、または `SelectiveErasureEvent` の `invalidated_node_ids` に列挙されたノード。 |
| `removed` | フロンティアからの論理的除去のために予約。現在の読み取り側はこれを**主張しません**: そのノードを挙げる `FrontierRebuildEvent` は `values`（`frontier_removed` / `frontier_reinstated` / `recomputed_utility`）に事実として報告され、`state: null` のままです。フロンティアイベントはスコア状態の主張ではないからです。 |

`stale` / `invalidated` / `removed` は**論理**状態です: いずれもノードが物理
削除されたことを意味せず、「Deleted」はどれに対しても妥当なラベルではありません。
物理削除はさらに別の状態であり、これらのペイロードは記述しません。

## 2 つのスコア書き換えチャネル

ノードのスコアは構造的に異なる 2 つの理由で動きます。API は**どの消費者も
誤って 1 本の系列に統合できない別々のリスト**として保持します
（`…/nodes/{node_id}/lineage` は `penalty_channel` と `policy_channel` を
並置して返します）。

### チャネル 1 — 敵対的ペナルティ（エポック内部、ノードスコープ）

| 観点 | 内容 |
|---|---|
| 証拠 | `rqgm_adversarial_cases.jsonl` 内の `UtilityRecord`（`utl_*`）行、およびノードの `_pre_penalty_score` / `_validated_attack_penalty` メトリクスセンチネル。 |
| 提示される値 | `base_score`、`penalty`、`final_score`、`supersedes`、`recomputed_in_epoch` — そのまま透過し、再計算はしません。 |
| 帰属 | レコードの `input_refs` からの `validated_attack_ids`。 |
| スコープ | 1 エポック内、1 ノードについて。 |

生攻撃と検証済みペナルティの区別は慣習ではなく型で強制されます: 生の敵対的
主張（`atk_*`）は `RqgmRawAttackV1` としてしか表現できず、この型は**スコア・
ペナルティ・確信度のフィールドを一切持ちません** — その `severity_claimed` は
攻撃者の主張です。ペナルティを駆動できるのは裁定済みの `validated_attack`
（`vat_*`）のみであり、しかもその id を参照する `UtilityRecord` 経由に限られます。
したがって攻撃が 0 件のランは capability の状態として報告され、健全性の証拠と
されることは決してありません。

### チャネル 2 — エポックの utility ポリシー書き換え（境界、ラン全体）

| 観点 | 内容 |
|---|---|
| トリガ | 1 つの `utility_policy` ロールのプロンプトを retire し別のものを採用する、コミット済みの T20 遷移 — すなわちエポック境界で `utility_policy_hash` が変わること。 |
| 帰結 | 監査ログ内の `SelectiveErasureEvent`（`erase_*`）と `FrontierRebuildEvent`（`rebuild_*`）レコード。 |
| ノード集合 | `invalidated_node_ids`、`recompute_node_ids`、`frontier_removed_node_ids`、`frontier_reinstated_node_ids` — **実イベントのフィールドからコピーされ**、読み取り側が再計算することは決してありません。 |
| ノード側の証拠 | `_utility_policy_hash`、`_scientific_score`、`_stale`、`_stale_reason`、`_valid_for_frontier`、`_erasure_event_id` の各メトリクスセンチネル。 |

`…/score-rewrites` はこのチャネルのラン単位ビューです: 各エントリは supersession
遷移（`from_policy_hash` → `to_policy_hash`）をその消去 / 再構築の帰結と join し、
使用した `source_event_ids` をすべて列挙します。join に組み込まれた正直さの規則:

- 採用遷移へ join **できなかった**消去 / 再構築も、それ自身のエントリとして
  現れます — 遷移を伴わない書き換えはそのまま示され、隠されません;
- 1 つの境界が複数の `utility_policy` プロンプトを retire / 採用する場合、
  どれが「その」ポリシーかを推測せず、`from_policy_hash` / `to_policy_hash` は
  縮退理由付きで `null` のままになります;
- ページカーソルは決定論的な join 済みリストへの整数インデックス（遷移順、
  続いて join されなかった監査イベントをファイル順）です — 2 つのログをまたぐ
  join であるため、バイトオフセットではありません。

## API が強制する提示の真実規則

これらの規則は読み取り側と DTO に実装されているため、ペイロードをそのまま
描画するだけのクライアントが規則を破ることはできません。

| 規則 | 強制の方法 |
|---|---|
| スコアはポリシー同一性なしに表示されない。 | すべての `RqgmScoreObservationV1` が `policy_hash` を持ち、各エポック行が自身の `utility_policy_hash` を持つため、異なるハッシュ下のスコアが 1 本の連続系列になることはありません。 |
| 生攻撃はスコアを持たない。 | `RqgmRawAttackV1` に数値フィールドが無い — 型がそれを不可能にします。 |
| ガバナンス状態 ≠ 研究状態。 | RQGM ペイロードはガバナンスのみを記述します; ラン / 研究の状態は `…/summary` にあります。 |
| 開いているエポックは活動ゼロではない。 | まだ開いている最新エポックでは `transition_counts` が `None` になり、配列を持つ `epoch_transition` 監査レコードが無いときは `fallbacks` が `None` になります。 |
| 採用は join であって自己申告ではない。 | `…/evolution` では、候補の提案ハッシュがコミット済み replay でアクティブ集合に到達した同一ロールのプロンプトと一致した場合にのみ `adopted` が導出され、`adopted_via` がその遷移を挙げます。メタエージェントの出力は不活性な来歴であり、その `adopted` は `None` です。 |
| 検証の証拠 ≠ 採用。 | `validation_record_count` / `validation_passed_count` は `prompt_candidate_validation` レコードを数えるもので、`adopted` とは別に報告されます。 |
| ポリシー本体は、バイト列のハッシュが今も正しいときのみ配信される。 | 保存ファイルが登録済み `prompt_hash` と一致しなくなった場合、`…/policies` は `body: null` と縮退理由を返します（write-once 規則のストレージ側の顔）。 |
| 論文の勝者はレビューによる選択である。 | `…/paper-archive` は `is_best_belief` のドラフトを `winner` として報告します。これはガバナンスの勝者でも研究結果でもありません; `materialized` は `full_paper.tex` の存在です。 |
| 不在は不在として報告される。 | 存在フラグ（`evolution_present`、`meta_outputs_present`、`state_present`、`archive_present`、`stat_present`、`corpus_present`）が任意ソースごとに付随し、成果物が無いとき件数は `0` ではなく `None` のままです。凍結された論文ポリシーが無いときアンカーの `enabled` は `None` です。 |
| ペイロードは有界に保たれる。 | overview はリストを埋め込みません; 監査エントリは配列を `<key>_count` に要約し長い文字列を切り詰め、生ペイロードは `?expand=1` でのみ得られます; 遷移エントリは件数を持ち、生イベントは `?expand=1` でのみ得られます。 |

## ページング

`…/transitions` と `…/audit` は JSONL ソースへのバイトオフセットカーソルを
用い、欠落なし / 重複なしの保証とコミット済みのみの読み取りを備えます;
`…/score-rewrites` はインデックスカーソルを用います。2 つのログページの
`source_revision` は、パース済みソースのバイト長（途切れた末尾を除く）です。
共有カーソル契約は
[REST API → カーソル規約](rest_api.md#カーソル規約)に一度だけ
文書化されています。

## 関連

- [RQGM スキーマリファレンス](rqgm_schemas.md) — レコードの形、id 形式、
  ハッシュ規律、チェックポイントファイルのインベントリ。
- [ファイルフォーマットリファレンス](file_formats.md) — これらの読み取り
  モデルがパースするチェックポイントファイル。
- [REST API リファレンス](rest_api.md) — 転送層の契約。
- [実行モード](../guides/execution_modes.md) — そもそもいつランが RQGM
  ランになるのか。
