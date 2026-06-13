# Plan — ローカルモデル決定性: seed plumb ／ digest pin ／ thinking-mode 統制

Status: 実装計画（未実装）。Origin: 2026-06 handoff study 設計。
親計画: [`../../MASTER_PLAN_handoff_impl.md`](../../MASTER_PLAN_handoff_impl.md)、研究計画 [`../../PLAN_artifact_summary_handoff.md`](../../PLAN_artifact_summary_handoff.md) §6.3 / §7 / §8 Stage 1。

## 依存関係（他 Plan.md）
- 上流依存: なし（Stage 1 の根、独立）。
- 下流（再現性・統計が本 subtask に依存）: [`../../scripts/Plan.md`](../../scripts/Plan.md)（分析の paired/seed 設計）、研究計画 §7。

## 削除要件
seed plumb・digest pin・thinking-mode 統制・per-call provenance 記録が main に land し、実機で「同一 seed/digest で再現性が成立（GPU 非 bit 決定性は n で吸収）」を確認、MASTER 完了ログに記録された時点で本 Plan.md を削除する。

## 背景（検証済の現状）
- ローカル backend が既定（`config/__init__.py:581-582`、`ARI_BACKEND=ollama`、既定 `qwen3:8b`、`qwen3:32b` も使用）。
- temperature はローカルに渡る（`client.py:131`、drop は gpt-5* のみ `client.py:130`）。
- **seed は `litellm.completion`（`client.py:180`）に未 plumb**。qwen3 thinking-mode 抑制あり（`client.py:141`）。

## 実装項目（主に `client.py`）
1. **seed plumb**: `client.py:180/230` の completion kwargs に `seed` を追加（ollama/litellm が pass-through）。
2. **digest pin**: モデルはタグでなく digest 固定で参照（タグは中身が動く）。
3. **thinking-mode 統制**: qwen3 thinking を全アーム一貫に（`client.py:141`）。
4. **provenance**: `cost_tracker.py` の per-call 記録に **resolved model digest / seed / temperature** を追加（現状 model 名のみ）。capability 勾配（small/large、研究計画 RQ-D）はこの provenance で識別。

## 検証ゲート（実機）
同一 (seed, digest, temperature, prompt) で複数回実行し、出力分散が API backend より大幅に小さいこと、provenance が trace に正しく残ることを確認。
