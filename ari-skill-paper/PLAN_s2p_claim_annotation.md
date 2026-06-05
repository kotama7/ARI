# 詳細実装計画: ari-skill-paper — claim-id 注釈と後処理検証（paper_claim_links）

対象: Story2Proposal 統合 マスター計画の **Phase A2(writer/後処理側)**。
親計画: `../Story2Proposal計画書.md`（統合マスター計画）。本書は **ari-skill-paper 担当分**。
ステータス: コード実装＋単体テスト完了（`tests/test_claim_links.py`、恒久仕様は `REQUIREMENTS.md` に反映済み）。§5 実機(compute node)検証が未実施のため、削除要件未充足 → 本ファイルは削除しない。

> **削除要件（必読）**: 本ファイルは下記「受け入れ基準」を全て満たし、恒久仕様を
> `ari-skill-paper/REQUIREMENTS.md` に反映（fold）した時点で、完了を記録する同じ PR で削除する。
> 部分完了では削除しない。途中放棄する場合も放棄理由を REQUIREMENTS.md に1行残してから削除する。
> （リポジトリ慣習:「完了記録と同 PR で要件/計画ファイル削除」に準拠。）

---

## 0. このタスクの責務

`write_paper_iterative`（`ari-skill-paper/src/server.py`）が science_data.json の claims を参照して本文を書き、
数値 claim に anchor を付け、直後の後処理で `paper_claim_links` を確定する。**`review_paper` は改造しない**（独立査読契約維持）。

## 1. 変更/新規ファイル

```text
ari-skill-paper/src/server.py            # claims_registry 注入 + % CLAIM 注釈指示
ari-skill-paper/src/（後処理検証 module） # paper_claim_links 確定 / numeric_mentions 分類 / figure late-bind
ari-skill-paper/tests/
```

## 2. 実装内容（マスター §Phase A2）

- `write_paper` に `claims_registry`（science_data.json の claims）を prompt へ明示注入。
- system prompt に「数値 claim 行頭に `% CLAIM:Cx:NCx` anchor を付与せよ」を追加。
- **claim-id 後処理検証**（write_paper 直後、hard gate 前段。refine 後にも再実行）:
  - anchor ↔ claims[] 整合（実在 id か）。
  - 数値トークン抽出 → 分類（result_claim / experimental_setting / citation_year / figure_table_ref）→ numeric_assertions 対応付け。
  - `paper_claim_links`（anchor / span_hash / line_range）確定。**anchor が安定キー**、span_hash は文変化検出、line_range は補助。
  - **figure 束縛はここで paper_claim_links に記録**（figures_manifest 存在時）。**transform 段の science_data.json は事後改変しない**。
- `paper_refine` に「`% CLAIM` anchor を保持せよ」を明示。anchor は最終 hard gate 完了まで保持。
  camera-ready からの除去は venue policy に従い、除去時も `paper_claim_links.json` を provenance artifact として保存。

## 3. 依存

```text
前段: ari-skill-transform（claims[] / numeric_assertions[]）
後段: ari-core（hard gate が paper_claim_links を入力）、paper_refine
注: figure 束縛は generate_figures 後（figures_manifest.json 存在後）に行う late-bind
```

## 4. 受け入れ基準（完了条件）

```text
- write_paper が claims を参照し、数値 claim に % CLAIM anchor を付与できる。
- 後処理が paper_claim_links を確定でき、未登録数値（assertion 不在）を検出できる。
- figure 束縛が paper_claim_links に記録され、science_data.json は改変されない。
- paper_refine が anchor を保持する（最終 hard gate で anchor が消えない）。
```

## 5. 検証（実機）

```text
- compute node で transform_data→write_paper→後処理 を実走し paper_claim_links を確認。
- 出力は workspace/checkpoints/<ts>_<slug>/。テスト緑のみを完了条件にしない。
```
