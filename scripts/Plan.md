# Plan — 実験ハーネス・run/analyze スクリプト・provenance・コストゲート

Status: 実装計画（未実装）。Origin: 2026-06 handoff study 設計。
親計画: [`../ari-core/MASTER_PLAN_handoff_impl.md`](../ari-core/MASTER_PLAN_handoff_impl.md)、研究計画 [`../ari-core/PLAN_artifact_summary_handoff.md`](../ari-core/PLAN_artifact_summary_handoff.md) §8 Stage 4-5 / §11。

## 依存関係（他 Plan.md）
- 上流依存（チェーン末端＝下記すべてが land 済を前提）:
  - [`../ari-core/ari/evaluator/Plan.md`](../ari-core/ari/evaluator/Plan.md)（B2）
  - [`../ari-core/ari/config/Plan.md`](../ari-core/ari/config/Plan.md)（G1）
  - [`../ari-core/ari/agent/Plan.md`](../ari-core/ari/agent/Plan.md)（B1/B3/G4）
  - [`../ari-core/ari/orchestrator/Plan.md`](../ari-core/ari/orchestrator/Plan.md)（G3/G9a）
  - [`../ari-core/ari/cli/Plan.md`](../ari-core/ari/cli/Plan.md)（G5/G7/G12）
  - [`../ari-core/ari/llm/Plan.md`](../ari-core/ari/llm/Plan.md)（seed/digest/provenance）

## 削除要件
run/analyze スクリプト・tracked ハーネス・スクラブ・instrumentation が main に land し、実機で end-to-end（run→trace→analyze→図表）が回り、MASTER 完了ログに記録された時点で本 Plan.md を削除する。

## 実装項目
1. **tracked ハーネス**: `.gitignore:31-37`（`*.c`/`benchmarks/`/`experiments/` 等を repo 全体で無視）を**個別 `!` 否定**で例外化し、固定 baseline/candidate kernel・Makefile・seeded matrix generator（families＋SuiteSparse SHA256 pin）・README（Contents 同期）を tracked 化。`git check-ignore -v <path>` で各 fixture が tracked であることを確認。
2. **`run_handoff_ablation.py`**: arm × model_size × seed を固定予算で sweep。`ARI_HANDOFF_MODE` / `ARI_FREEZE_CONTRACT` / `ARI_EVALUATOR` / deterministic selector flag / `memory_off` / model+digest+seed を設定。出力は `workspace/checkpoints/<ts>_<slug>/`（リポジトリ規約、$HOME 直下・/tmp 禁止）。
3. **`analyze_handoff_ablation.py`**: `tree.json` / `cost_trace.jsonl` / `node_report.json` / evaluator 出力（＋新設 `handoff_trace.jsonl`）を集計。**`search_trace.jsonl` は存在しないので使わない**。run 単位 cluster bootstrap、parity は TOST、**注入トークンを per-node prompt_tokens と分離計測**、図表。
4. **instrumentation**: `handoff_trace.jsonl`（per-node 注入トークン/チャネル別）、summary 忠実性（導出 known_failures vs evaluator failure_signature）、provenance（[`../ari-core/ari/llm/Plan.md`](../ari-core/ari/llm/Plan.md) と連結）。
5. **機械情報スクラブ（収集時）**: `node_report` 等に実在する hostname/partition 系（`ari-core/ari/schemas/node_report.schema.json` / `builder.py`）を**収集時にスクラブ**＋commit 前 grep ゲート。tracked artifact・図・commit message に機械情報を一切入れない（リポジトリ最優先規約）。
6. **cost go/no-go ゲート**: `cost_tracker` の `estimated_cost_usd` を集計し per-cell/全体の予算ゲート。ローカル主体・frontier アームのみ予算管理。

## 検証ゲート（実機）
`git check-ignore -v` で全 fixture が tracked。スクラブ後 trace に機械情報ゼロ（grep）。run→analyze が end-to-end で図表生成。
