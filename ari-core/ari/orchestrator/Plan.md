# Plan — G3 node_summary_view ／ G9a deterministic selector

Status: 実装計画（未実装）。Origin: 2026-06 handoff study 設計。
親計画: [`../../MASTER_PLAN_handoff_impl.md`](../../MASTER_PLAN_handoff_impl.md)、研究計画 [`../../PLAN_artifact_summary_handoff.md`](../../PLAN_artifact_summary_handoff.md) §3 / §8 Stage 2-3。

## 依存関係（他 Plan.md）
- 上流依存:
  - [`../config/Plan.md`](../config/Plan.md)（G1）— `summary_fields_enabled` / `summary_form` を読む。
  - [`../evaluator/Plan.md`](../evaluator/Plan.md)（B2）— **G9a の前提**（`_scientific_score` が無いと fallback selector が全 0.0 に縮退）。
- 下流: [`../agent/Plan.md`](../agent/Plan.md)（G4 が `node_summary_view` を注入）、[`../../scripts/Plan.md`](../../scripts/Plan.md)。

## 削除要件
`node_summary_view`（field 別＋FORM 変種）と `bfts_score_only` が main に land し、実機で「field トグルが view に反映」「同一 input で選択が再現」を確認、MASTER 完了ログに記録された時点で本 Plan.md を削除する。

## 実装項目
1. **`node_summary_view.py`（新規, 本 dir）**: `node_report.json`（`node_report/builder.py:551-586`）から field 選択可能な view を生成。source=`delta_vs_parent`/`files_changed`/`self_assessment.concerns`/`next_steps_hints`/`metrics._scientific_score`。**`known_failures` は native field 非存在 → failed-node の evaluator_reason / concerns から導出**。FORM 変種: extractive / rolling（祖先要約の有界畳み込み）/ failure_only / masked / truncated。
   ※ 既存 `bfts.py:64-108` `_format_parent_report_block` は **planner プロンプト結合・field 非選択**のため流用不可（新規）。
2. **G9a `bfts_score_only`**: `bfts.py:418-575` の LLM 一次選択を flag で bypass し、常に `_select_fallback`(`bfts.py:356-369`, `frontier_score=scientific_only`)を一次選択に。これで selector 由来分散を除去。

## 検証ゲート（実機）
`summary_fields_enabled` から1 field 落とすと view から当該 field が消える。`bfts_score_only` 下で同一 input の選択が決定的に再現。
