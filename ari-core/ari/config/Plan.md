# Plan — G1: HandoffConfig ＋ env override ＋ 配線

Status: 実装計画（未実装）。Origin: 2026-06 handoff study 設計。
親計画: [`../../MASTER_PLAN_handoff_impl.md`](../../MASTER_PLAN_handoff_impl.md)、研究計画 [`../../PLAN_artifact_summary_handoff.md`](../../PLAN_artifact_summary_handoff.md) §8.1。

## 依存関係（他 Plan.md）
- 上流依存: なし（Stage 1 の根）。
- 下流（本 subtask の単一情報源を読む）:
  - [`../agent/Plan.md`](../agent/Plan.md) — B1 memory gate / G4 agent 注入 / B3。
  - [`../orchestrator/Plan.md`](../orchestrator/Plan.md) — G3 field トグル。
  - [`../cli/Plan.md`](../cli/Plan.md) — G5 copy トグル / G7 / G12。

## 削除要件
HandoffConfig・`apply_handoff_env_overrides`・呼出配線が main に land し、7 モードが env から再現選択でき、MASTER の完了ログに記録された時点で本 Plan.md を削除する。

## 実装項目
1. **`HandoffConfig`（pydantic, `__init__.py:66-139` の `BFTSConfig` 兄弟）**: `mode`(7値)/`copy_workdir`/`inject_agent_block`/`inject_planner_block`/`log_mode`(none|full|truncated|masked)/`log_truncate_chars`/`summary_form`(extractive|rolling|failure_only)/`summary_fields_enabled: list[str]`/`memory_off`。
2. **`resolve_mode()`**: 7 モード名 → 上記 bool 集合の写像（`ARI_HANDOFF_MODE` 1 値で run が完全特定）。
3. **`apply_handoff_env_overrides(cfg)`**: `__init__.py:440-471` の `apply_bfts_env_overrides` を模倣。Literal の env ホワイトリスト検証も踏襲。**同じ呼出箇所から必ず呼ぶ**（定義だけで未配線にしない）。
4. **配線**: `ARIConfig`（`__init__.py:281` は `extra:allow`）に `handoff:` を追加 → `../core.py:83` で `cfg.handoff` を読む。

## 検証ゲート
`ARI_HANDOFF_MODE=code_only|code_plus_summary|code_plus_full_log` の3値で、解決された bool 集合がログに正しく出ることを確認（[`../agent/Plan.md`](../agent/Plan.md) の gate と連結）。
