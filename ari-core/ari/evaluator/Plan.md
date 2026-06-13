# Plan — B2: deterministic evaluator ＋ 測定器ユニット

Status: 実装計画（未実装）。Origin: 2026-06 handoff study 設計。
親計画: [`../../MASTER_PLAN_handoff_impl.md`](../../MASTER_PLAN_handoff_impl.md)、研究計画 [`../../PLAN_artifact_summary_handoff.md`](../../PLAN_artifact_summary_handoff.md) §6.2 / §8 Stage 1。

## 依存関係（他 Plan.md）
- 上流依存: なし（Stage 1 の根）。
- 下流（本 subtask を前提にする）:
  - [`../orchestrator/Plan.md`](../orchestrator/Plan.md) — G9a は `_scientific_score` を必要とする。
  - [`../agent/Plan.md`](../agent/Plan.md) — B3（契約凍結）は本 evaluator が固定採点を持つことを前提。
  - [`../../scripts/Plan.md`](../../scripts/Plan.md) — analyze は evaluator 出力を集計。

## 削除要件
本 subtask（`deterministic_evaluator.py` ＋ `core.py` の evaluator dispatch ＋ 測定器ユニット）が main に land し、**実機 compute node** で検証ゲートを通過し、MASTER の完了ログに記録された時点で本 Plan.md を削除する。

## 実装項目
1. **`deterministic_evaluator.py`（新規, 本 dir）**: `ari/protocols/evaluator.py` の `Evaluator` Protocol に準拠し、**`evaluate_sync(goal, artifacts, summary, node_id=None, node_label=None)` を必ず実装**（loop は `agent/loop.py:1454/1532/1600` で sync 版を呼ぶ）。戻り値 `{"metrics": {"_scientific_score": s∈[0,1], …}, "has_real_data": bool, "reason": str}`。`node.metrics = eval_result["metrics"]`（`agent/loop.py:1461`）経由で BFTS 選択（`orchestrator/bfts.py:336`）に効くため、**`metrics._scientific_score` を [0,1] 正規化して必ず格納**。
2. **測定器ユニット（evaluator が独占所有）**: 参照解 oracle（fp64 / 補償加算）、行ごと ε（`C·γ_{nnz}·Σ|A||x|`）、timing（W warmup＋R reps median＋分散、core pin、freq 固定、OMP 明示、NUMA）、checksum 固定 baseline（candidate と同一フラグ）、anti-gaming（matrix/timing/baseline/correctness を独占、correctness 用 x は call 時供給）。
3. **dispatch（`../core.py:195`）**: 現状 `LLMEvaluator(...)` ハードコード。`ARI_EVALUATOR` で差し替え可能に（`../core.py:155-182` の `axis_mode` dispatch を模倣）。

## 検証ゲート（実機）
固定タスクで `code+summary` を1本実行し、(i) valid node>0、(ii) selector が**非ゼロ** `_scientific_score` を消費、(iii) LLMEvaluator 非経由で採点が完走、を確認。
