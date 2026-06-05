# 詳細実装計画: ari-skill-evaluator — evidence_grounded_semantic_review

対象: Story2Proposal 統合 マスター計画の **Phase D**。
親計画: `../Story2Proposal計画書.md`（統合マスター計画）。本書は **ari-skill-evaluator 担当分**。
ステータス: コード実装＋単体テスト完了（`tests/test_s2p_tools.py`、恒久仕様は `REQUIREMENTS.md` に反映済み）。§5 実機(compute node)検証が未実施のため、削除要件未充足 → 本ファイルは削除しない。

> **削除要件（必読）**: 本ファイルは下記「受け入れ基準」を全て満たし、恒久仕様を
> `ari-skill-evaluator/REQUIREMENTS.md`（無ければ新規作成）に反映（fold）した時点で、完了を記録する同じ PR で削除する。
> 部分完了では削除しない。途中放棄する場合も放棄理由を REQUIREMENTS.md に1行残してから削除する。
> （リポジトリ慣習:「完了記録と同 PR で要件/計画ファイル削除」に準拠。）

---

## 0. このタスクの責務

S2P の reasoning verification / visual coherence のうち **決定論で測れない意味的部分のみ**を、
execution provenance に接地して評価する **非ブロッキング**評価器を新規実装する。

## 1. 変更/新規ファイル

```text
ari-skill-evaluator/src/（evidence_grounded_semantic_review）
ari-core/config/workflow.yaml            # 非ブロッキングステージとして配線（merge_reviews 経由）
ari-skill-evaluator/tests/
```

## 2. 実装内容（マスター §Phase D）

- **review_paper を改造しない**（text-only reviewer independence contract 維持）。
- **dynamic-axes LLM evaluator には足さない**（operand が実験ノードで paper draft ではない）。
- 評価対象（意味のみ。数値・figure 実在は hard gate 済み）:
  - reasoning semantics（主張が evidence 範囲を超えないか / conclusion の過剰一般化 / limitation 反映）。
  - data interpretation semantics（解釈・因果・比較表現の妥当性）。
  - visual semantics（caption と本文・図傾向の意味整合、言い過ぎ）。
  - unregistered claim（非数値）検出 → blocking せず refine へ。
- **非ブロッキング**。`suggested_revisions` を出力し、paper_refine に渡す（配線は `../ari-core/PLAN_s2p_merge_refine.md`）。
- 指標: `semantic_review_detected_overclaim_count` / `resolved_overclaim_count` / `human_verified_overclaim_precision`（人手スポット）。

## 3. 依存

```text
前段: ari-skill-transform（claims）, ari-core hard gate（gate json を入力）
後段: ari-core merge_reviews / paper_refine（別計画）
```

## 4. 受け入れ基準（完了条件）

```text
- review_paper / dynamic-axes evaluator を変更していない。
- paper draft + claims + hard gate json から overclaim を検出し suggested_revisions を出力できる。
- 非ブロッキング（finalize を止めない）。
- detected / resolved / human-verified precision を集計できる。
```

## 5. 検証（実機）

```text
- compute node で hard gate 後に実走し、suggested_revisions と score を確認。
- 出力は workspace/checkpoints/<ts>_<slug>/evaluation/evidence_grounded_semantic_review.json。
```
