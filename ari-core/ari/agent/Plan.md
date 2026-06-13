# Plan — B1 memory gate ／ B3 契約凍結 ／ G4 agent 面注入 ／ ローカル決定性(loop側)

Status: 実装計画（未実装）。Origin: 2026-06 handoff study 設計。
親計画: [`../../MASTER_PLAN_handoff_impl.md`](../../MASTER_PLAN_handoff_impl.md)、研究計画 [`../../PLAN_artifact_summary_handoff.md`](../../PLAN_artifact_summary_handoff.md) §0.2(B1/B3) / §8 Stage 1-2。

## 依存関係（他 Plan.md）
- 上流依存:
  - [`config/Plan.md`](../config/Plan.md)（G1 HandoffConfig）— gate/注入の全トグルを読む。
  - [`evaluator/Plan.md`](../evaluator/Plan.md)（B2）— **B3 の前提**（契約を凍結しても採点が壊れないのは固定 evaluator があるから）。
  - [`orchestrator/Plan.md`](../orchestrator/Plan.md)（G3 `node_summary_view`）— G4 が注入する view の生成元。
- 下流: [`cli/Plan.md`](../cli/Plan.md)（copy/sterile）、[`../../scripts/Plan.md`](../../scripts/Plan.md)。

## 削除要件
B1（memory per-arm gate）・B3（契約外生化）・G4（agent 面注入）・seed/thinking 統制が main に land し、**実機**で「code_only の子プロンプトに operational state ゼロ」「契約が run/model 間で不変」を確認、MASTER 完了ログに記録された時点で本 Plan.md を削除する。

## 実装項目
1. **B1 memory gate**: monolithic `loop.py:164-355` の `build_working_context_messages` を **Tier-1a/1b/1c/2 の per-arm 独立 emit に分割**し `handoff.memory_off` で gate。ガード `loop.py:292` より上で無条件発火する Tier-1a(`193-216`)/1c(`218-290`) を必ず gate、**`_PINNED_USER_MARKERS`(`766-775`) の pin 対象も消す**（消さないと window 圧縮を生存）。`search_global_memory`(`650-672`)・auto-save(`920-930`) も対象に含める。
2. **B3 契約外生化**: `ARI_FREEZE_CONTRACT` で `loop.py:1162-1196` の make_metric_spec 自己決定変異（`self.evaluator.metric_spec=` / `metric_extractor`）を封じ、`loop.py:1207-1219` の per-run 契約 obligation 生成も停止。固定 `metric_contract.json` を pin（or 無し）。`make_metric_spec` は core/pinned ツール（`workflow.py:172`,`loop.py:719`）なので survey/idea off では消えない＝明示無効化必須。Tier-1c が残る場合は**固定契約のみ**注入。
3. **G4 agent 面注入**: `handoff.inject_agent_block`/`log_mode` に応じ、子初回 user message（`loop.py:587-608`）に `node_summary_view`/log を `build_working_context_messages` 経由で append（`loop.py:640-647`）。log は **copy 除外前に親 work_dir から読む**。
4. **ローカル決定性(loop側)**: qwen3 thinking-mode（`loop.py` 系）を全アーム一貫に（client 側は [`../llm/Plan.md`](../llm/Plan.md)）。

## 検証ゲート（実機）
`code_only` の子プロンプトをダンプ → Tier-1a/1c/1b/2・契約 narrative が**ゼロ**。`code_plus_summary`/`code_plus_full_log` は view/log が子に届く。`ARI_FREEZE_CONTRACT` 下で同一 input の契約・採点 spec が run/model 間で不変。
