# 詳細実装計画: ari-core — hypothesis 台帳の要否判定（調査タスク）

対象: Story2Proposal 統合 マスター計画の **Phase C**。
親計画: `../Story2Proposal計画書.md`（統合マスター計画）。本書は **ari-core 担当分（調査）**。
ステータス: 調査完了・結論を `REQUIREMENTS.md` に反映済み（lineage + idea.json + node lineage で MVP は再構成可、新設不要。単一 tree 内の多 idea fan-out の per-node `idea_index` のみ将来課題）。§5 の実 checkpoint lineage 確認が未実施のため、削除要件未充足 → 本ファイルは削除しない。

> **削除要件（必読）**: 本ファイルは下記「結論」を出し、それを `ari-core/REQUIREMENTS.md` に反映
> （代替可なら「hypothesis 台帳は lineage で代替・新設不要」を1行、不足なら最小 `hypotheses[]` 仕様）した時点で、
> 完了を記録する同じ PR で削除する。「不要」結論の場合でも必ず1行残してから削除する。部分調査では削除しない。
> （リポジトリ慣習:「完了記録と同 PR で要件/計画ファイル削除」に準拠。）

---

## 0. このタスクの責務

hypothesis traceability を新規実装すべきか、既存 `lineage_decisions.jsonl` / `active_idea` 履歴で代替できるかを判定する。
**最初から台帳を新設しない**。代替可否を先に評価する調査タスク。

## 1. 調査/変更対象

```text
ari-core/ari/orchestrator/lineage_decision.py   # active_idea 履歴の粒度確認
ari-skill-transform/（science_data.json claims）  # claims[] と active_idea の接続可否
（不足時のみ）science_data.json に最小 hypotheses[] 追加
```

## 2. 手順（マスター §Phase C）

```text
1. lineage_decisions.jsonl に active_idea の履歴が十分残るか確認する。
2. science_data.json の claims[] と active_idea を接続できるか確認する。
3. hypothesis → experiment → result → claim の chain が復元可能か確認する。
4. 不足があれば最小の hypotheses[] を science_data.json に追加する。
```

## 3. 依存

```text
前段: ari-skill-transform（claims[]）が存在すると接続検証が容易（必須ではない）
後段: なし
```

## 4. 受け入れ基準（完了条件 = 結論を出すこと）

```text
- 「lineage で代替可（新設不要）」または「最小 hypotheses[] を追加（仕様明記）」のいずれかの結論を出す。
- 結論を ari-core/REQUIREMENTS.md に反映する（不要結論でも1行残す）。
```

## 5. 検証

```text
- 実 checkpoint の lineage_decisions.jsonl を読み、chain 復元可否を実データで判定する。
```
