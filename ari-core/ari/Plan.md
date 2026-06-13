# Plan — root ファイル横断: core.py evaluator dispatch ／ cost_tracker.py provenance

Status: 実装計画（未実装）。Origin: 2026-06 handoff study 設計。
親計画: [`../MASTER_PLAN_handoff_impl.md`](../MASTER_PLAN_handoff_impl.md)、研究計画 [`PLAN_artifact_summary_handoff.md`](PLAN_artifact_summary_handoff.md) §6.2 / §8 Stage 1 / §11。
対象は `ari-core/ari/` **直下のファイル**（サブパッケージに属さない横断的改修）。

## 依存関係（他 Plan.md）
- 上流依存:
  - [`evaluator/Plan.md`](evaluator/Plan.md)（B2）— dispatch が**選ぶ**対象（deterministic evaluator クラス）はそちらで定義。
  - [`agent/Plan.md`](agent/Plan.md)（B3）— make_metric_spec 自己決定の封じ込めは loop 側。本書は build 時 spec 構築（`core.py`）との整合のみ扱う。
  - [`llm/Plan.md`](llm/Plan.md)— provenance に載せる seed/digest/temperature の出所。
- 下流: [`../../scripts/Plan.md`](../../scripts/Plan.md)（analyze が provenance を読む）。

## 削除要件
core.py の evaluator dispatch と cost_tracker.py の provenance 拡張が main に land し、実機で「`ARI_EVALUATOR` で deterministic evaluator に切替わる」「per-call で seed/digest/temp が trace に残る」を確認、MASTER 完了ログに記録された時点で本 Plan.md を削除する。

## 実装項目
1. **`core.py` evaluator dispatch**: `core.py:195` は現状 `LLMEvaluator(...)` ハードコード（`axis_mode` dispatch `core.py:155-182` は軸のみ）。`ARI_EVALUATOR`（or `cfg.evaluator.kind`）で [`evaluator/Plan.md`](evaluator/Plan.md) の deterministic evaluator に差し替え可能化。B3（[`agent/Plan.md`](agent/Plan.md)）で make_metric_spec の自己決定を封じた上で、build 時 spec（`core.py:62,151` `_make_metric_spec`）は固定/generic のまま evaluator が採点を所有する形に整合させる。
2. **`cost_tracker.py` provenance 拡張**: per-call 記録（現状 model 名・token 数等）に **resolved model digest / seed / temperature** を追加（値の供給は [`llm/Plan.md`](llm/Plan.md)）。capability 勾配（研究計画 RQ-D）と再現性（§11）はこの provenance で識別・検証する。

## 検証ゲート（実機）
`ARI_EVALUATOR` 切替で deterministic evaluator が使われること、`cost_trace` 各行に digest/seed/temperature が入ること、同一 (digest, seed) で再現性が立つことを確認。
