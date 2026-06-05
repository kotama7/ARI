# 詳細実装計画: ari-core — claim_evidence_hard_gate（決定論検証ステージ）

対象: Story2Proposal 統合 マスター計画の **Phase B ＋ B2(数値再計算) ＋ B3(policy)**。
親計画: `../Story2Proposal計画書.md`（統合マスター計画）。本書は **ari-core パイプライン担当分**。
ステータス: コード実装＋単体テスト完了（`tests/test_claim_evidence_hard_gate.py`、恒久仕様は `REQUIREMENTS.md` に反映済み）。§5 実機 e2e（write_paper→draft gate→…→refine→final gate→finalize の通し）は 2026-06-05 に実走完了（checkpoint `20260528180541_…CSR-form`、`numeric_coverage_rate=1.0` / `mismatch=0` / `reproducible=1.0`、`REQUIREMENTS.md` の Status に記録）。**strict(blocking) path も 2026-06-05 検証済み**（同 checkpoint、`write=False`：clean→`should_block=False`／reported 99.99 vs recomputed 20.91→`numeric_mismatch`→`should_block=True`、wrapper→`{"error"}`→finalize skip まで確認、`REQUIREMENTS.md` Status に記録、回帰テスト `test_s2p_tools.py`）。**§10 評価は意図的スキップ**（2026-06-05、`REQUIREMENTS.md` Status に記録）、ORS×gate 経験的比較も同種で対象外。本計画固有の受け入れ基準（実装＋実機 e2e＋strict）は充足済みだが、マスター方針「有効化判断確定後に全子計画を同一 PR で削除」に従い、**有効化判断＋最終クリーンアップまで本ファイルは保持**する。

> **削除要件（必読）**: 本ファイルは下記「受け入れ基準」を全て満たし、恒久仕様を
> `ari-core/REQUIREMENTS.md` に反映（fold）した時点で、完了を記録する同じ PR で削除する。
> 部分完了では削除しない。途中放棄する場合も放棄理由を REQUIREMENTS.md に1行残してから削除する。
> （リポジトリ慣習:「完了記録と同 PR で要件/計画ファイル削除」に準拠。）

---

## 0. このタスクの責務

新パイプラインステージ `claim_evidence_hard_gate` を実装する。**唯一の blocking gate**。
S2P の data fidelity を **execution data fidelity** に再定義した決定論検証。

## 1. 変更/新規ファイル

```text
ari-core/config/workflow.yaml            # claim_evidence_hard_gate ステージ追加 / finalize 依存
ari-core/ari/pipeline/（hard gate 実装）  # 実在性 / 数値再計算 / coverage / figure 実在
ari-core/ari/（numeric 再計算 utility）   # formula-level（共通化、semantic review からも参照可）
ari-core/ari/（claim_gate_policy loader）
ari-core/tests/
```

## 2. 実装内容（マスター §Phase B / B2 / B3）

- `claim_evidence_hard_gate` を **draft（write_paper 後）と final（refine 後）の2回**実行。
  `finalize_paper.depends_on` に **final gate** を追加（blocking はここのみ）。
- 決定論検証:
  - claim 実在性（supported_by の node_id / figure id が tree.json/node_report.json/figures_manifest.json に実在、artifact path 実在、executed node 接続）。
  - **numeric formula-level 再計算**（operands(node_id, metric_path) → results.json/node_report の scalar、formula 再導出、tolerance 照合、同一 environment 比較）。
  - **numeric coverage**（section 帰属は LaTeX `\section{}` / `\begin{abstract}` / `\appendix` を決定論 parse。requires_assertion=true の未登録数値を検出）。
  - figure 実在（figures_manifest 登録 / source_data・script 存在 / 未参照 figure）。
- B2: numeric 再計算 utility は formula-level（MVP）。**trial 集計は将来**（`ari-skill-coding`/`ari-skill-transform` の per-trial 保持前提、`aggregation` は記録のみ）。
- B3: `claim_gate_policy`（mode=strict|warn|off / target_sections / blocking.block_on）。MVP=warn、評価=strict。
- 出力 `claim_evidence_hard_gate_{draft|final}.json`。

> **検証境界（必読）**: 数値照合は「paper の数値 ↔ results.json の値」の**転記・導出の整合性**を検証するのみで、
> results.json の値そのものの真偽（results ↔ 現実）は検証しない。後者は ORS（再実行）が担う。

## 3. 依存

```text
前段: ari-skill-transform（claims/numeric_assertions）, ari-skill-paper（paper_claim_links）
後段: ari-skill-evaluator（semantic review が gate json を読む）, ari-core merge/finalize（別計画）
```

## 4. 受け入れ基準（完了条件）

```text
- errors / warnings を分離出力し、JSON 保存できる。
- strict 時、errors（numeric_mismatch / operand_unresolved / missing_evidence / uncovered_numeric[strict]）で finalize をブロック。
- numeric formula-level 再計算が node_id+metric_path で解決し tolerance 照合できる。
- numeric coverage が section 別 policy に従って未登録数値を検出できる。
- draft と final（refine 後）の両方で実行され、finalize は final gate に依存する。
```

## 5. 検証（実機）

```text
- compute node で write_paper→hard gate(draft)→…→refine→hard gate(final)→finalize を実走。
- 出力は workspace/checkpoints/<ts>_<slug>/evaluation/。テスト緑のみを完了条件にしない。
```
