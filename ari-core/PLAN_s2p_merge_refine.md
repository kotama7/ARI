# 詳細実装計画: ari-core — merge_reviews 分離と paper_refine 配線（generate–evaluate–adapt）

対象: Story2Proposal 統合 マスター計画の **Phase E ＋ generate–evaluate–adapt ループ配線**。
親計画: `../Story2Proposal計画書.md`（統合マスター計画）。本書は **ari-core パイプライン担当分**。
ステータス: コード実装完了。`config/workflow.yaml` のトポロジは**検証済み依存順に back-port 済み**（finalize→final gate 依存、`merge_reviews` へ hard_gate/semantic パス、依存順整列）。**2026-06-05、S2P 9ステージを既定 ON（warn mode）に有効化**（gate は報告のみ・非ブロック。strict は `claim_gate_policy.mode`／`ARI_CLAIM_GATE_MODE` で随時。e2e は全24ツール列を検証）。恒久仕様は `REQUIREMENTS.md` に反映済み。§5 実機 e2e（…→merge→refine→render→最終gate→finalize の通し）は 2026-06-05 実走完了（`REQUIREMENTS.md` の Status に記録、login node・`warn` mode）、**strict(blocking) path も検証済み**（同 Status）。**§10 評価は意図的スキップ**（同 Status に記録）、ORS×gate 経験的比較も同種で対象外。**残るは最終クリーンアップのみ**で、マスター方針に従い同一クリーンアップ PR まで本ファイルは保持する。

> **削除要件（必読）**: 本ファイルは下記「受け入れ基準」を全て満たし、恒久仕様を
> `ari-core/REQUIREMENTS.md` に反映（fold）した時点で、完了を記録する同じ PR で削除する。
> 部分完了では削除しない。途中放棄する場合も放棄理由を REQUIREMENTS.md に1行残してから削除する。
> （リポジトリ慣習:「完了記録と同 PR で要件/計画ファイル削除」に準拠。）

---

## 0. このタスクの責務

S2P の generate–evaluate–adapt loop を ARI に配線する。`merge_reviews` を independent / evidence-grounded に分離し、
`paper_refine` に修正提案を渡して再評価ループを成立させる。

## 1. 変更/新規ファイル

```text
ari-core/config/workflow.yaml            # merge_reviews 出力構造 / paper_refine 配線 / finalize 依存
ari-core/ari/pipeline/（merge / refine 連携）
ari-core/tests/
```

## 2. 実装内容（マスター §Phase E, §5 topology）

- `merge_reviews` 出力を分離:
  - `independent_reviews`（review_paper / vlm_review_figures）
  - `evidence_grounded_reviews`（claim_evidence_hard_gate / evidence_grounded_semantic_review）
- `paper_refine` に `suggested_revisions` を渡す（両カテゴリを渡してよいがレポート上は分離）。
- **`paper_refine` の編集方式（S2P refiner 忠実・差分出力）**:
  - S2P の refiner（eq.5 `(M',C)=A_ref({D_i},C)`）は **グローバル整合役割**（cross-section の整合・冗長圧縮・用語統一・visual 参照の調整）であり、**全文の書き直しではなく「整える」限定タスク**。
  - 従って `paper_refine` は全文を入力で参照（グローバル文脈）しつつ、**出力は全文 LaTeX ではなくターゲット差分**＝`[{"find": <一意な逐語スパン>, "replace": <改訂スパン>}]` の JSON 配列とする。
  - 適用は決定論的かつ安全側: (i) `find` が文書内で**一意**なものだけ適用（曖昧・不在は skip、推測しない）、(ii) 編集スパン内の `% CLAIM:Cx:NCx` anchor は `replace` が**逐語保持**するもののみ適用（anchor を落とす編集は skip）。適用ゼロ／anchor 喪失時は **draft へ revert**（`refined=False`）。
  - **理由（設計判断）**: 全文再生成（`max_tokens` 全文・"complete revised LaTeX"）は CLI シム経由で生成量過多となり、リトライ多重化と相まって TimeoutError ループ→finalize スキップを招いた。差分出力で生成量を変更スパンに限定し解消する。局所的・的を絞った改稿は本来 S2P でも writer ループ側（per-section）の役割であり、refiner は全体整合に徹する。
- **`render_paper`（S2P renderer A_rend, eq.6 `M=A_rend(M',C)`）を追加**:
  - paper_refine の直後に `compile_paper`（pdflatex→bibtex→pdflatex×2）で **refine 後 `full_paper.tex` → `full_paper.pdf` を再コンパイル**。これが無いと配布 PDF が write_paper の draft（refine 前）のまま stale になる（S2P は render を refiner の後段に置く）。
  - **`paper_refine` のみに依存**し hard gate ではゲートしない（refine 成功時は常に最新 PDF を出す）。
  - **非ブロッキング**: 何も render_paper に依存させない＋ latexmk 失敗は前の PDF を残すだけ（.tex を gate/finalize の真実源とする方針を維持、finalize チェインを壊さない）。
- refine 後に **evidence_grounded_semantic_review を rerun**（score_delta 測定）し、**claim_evidence_hard_gate(final) を再実行**。
- `finalize_paper` を **最終 hard gate に依存**させる（refine 前 draft の gate では finalize しない）。
- `review_paper` の独立性契約は維持（evidence を混ぜない）。

## 3. 依存

```text
前段: ari-core hard gate（PLAN_s2p_hard_gate.md）, ari-skill-evaluator（PLAN_s2p_semantic_review.md）
後段: なし（finalize_paper / ear_publish / ors_* は既存）
```

## 4. 受け入れ基準（完了条件）

```text
- merge_reviews が independent / evidence_grounded を分離出力する。
- paper_refine が suggested_revisions を反映し、refine 後に semantic review と hard gate(final) が再実行される。
- **paper_refine は差分（find/replace JSON）で編集し、全文再生成しない**（出力量が変更スパン限定＝タイムアウトしない）。一意でない find と anchor を落とす編集は適用されず、anchor 喪失/no-op 時は draft へ revert する。
- **render_paper が refine 後に PDF を再コンパイルし、配布 PDF が refine を反映する**（stale でない）。non-blocking で finalize チェインを壊さない。
- finalize_paper が最終 hard gate に依存し、stale gate では finalize されない。
- review_paper / vlm_review_figures を改造していない。
```

## 5. 検証（実機）

```text
- compute node で write_paper→gate→review→merge→refine→最終gate→finalize を通す。
- 出力は workspace/checkpoints/<ts>_<slug>/。テスト緑のみを完了条件にしない。
```
