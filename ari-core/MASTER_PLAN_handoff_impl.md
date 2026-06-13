# MASTER PLAN — Artifact/History Handoff 統制研究の実装マスター

Status: 実装マスター計画（未実装）。Origin: 2026-06 設計議論＋コードベース監査＋関連研究調査。
研究計画（why/what）: [`PLAN_artifact_summary_handoff.md`](PLAN_artifact_summary_handoff.md)。本書は how/order（依存 DAG・クリティカルパス・削除要件・subtask 索引）。

## 削除要件
配下の全 subtask Plan.md が削除要件を満たして削除され（全 subtask が main に land＋実機検証）、結果が論文ドラフトまたは後継 PLAN に転記された時点で本マスターと研究計画を削除する。

## 原則
1. 測定は evaluator が独占所有（agent は固定シグネチャ kernel のみ提供）。
2. 評価契約は実験者が固定し全アーム・全モデルで同一（B3）。
3. 各 handoff チャネルは per-arm で明示 gate。
4. 機械情報（host/partition/port/path）は tracked artifact・commit に一切入れない（最優先規約）。

## Subtask 索引と依存 DAG
| subtask | Plan.md | 主担当 | 上流依存 |
|---|---|---|---|
| B2 deterministic evaluator＋測定器 | [`ari/evaluator/Plan.md`](ari/evaluator/Plan.md) | evaluator | （根） |
| G1 HandoffConfig | [`ari/config/Plan.md`](ari/config/Plan.md) | config | （根） |
| ローカル決定性(seed/digest) | [`ari/llm/Plan.md`](ari/llm/Plan.md) | llm | （根） |
| B1 memory gate / B3 契約凍結 / G4 注入 | [`ari/agent/Plan.md`](ari/agent/Plan.md) | agent | config, evaluator, orchestrator |
| G3 node_summary_view / G9a selector | [`ari/orchestrator/Plan.md`](ari/orchestrator/Plan.md) | orchestrator | config, evaluator |
| G5 copy / G7 sterile / G12 timeout・overflow | [`ari/cli/Plan.md`](ari/cli/Plan.md) | cli | config |
| ハーネス / run・analyze / scrub / cost | [`../scripts/Plan.md`](../scripts/Plan.md) | scripts | 上記すべて |

依存の要点: **B2 → B3 → B1 が背骨**。B2 で採点固定 → B3 で契約外生化（しないと B2 が `agent/loop.py:1190` で上書きされる）→ B1 で memory 第3経路を gate（しないと全アームが state 共有）。

## クリティカルパス（ビルド順）
- **Stage 0（コード前）**: タスク確定（SpMV/SpMM、既存 fixture は全 SpMM）／事前登録 doc 凍結（ε・C／`_scientific_score` 正規化／invalid floor／N／failure codebook／単一 primary 対比／H-B・H-C・H-D の向き／model 水準）／seed kernel 固定／pilot 予約（qwen3:8b validity floor・最大サイズ infra 適合）。
- **Stage 1**: B2＋測定器（evaluator）／B3 契約凍結（agent）／G1 HandoffConfig（config）／ローカル決定性（llm）。
- **Stage 2**: B1 memory gate／G4 注入（agent）／G3 node_summary_view（orchestrator）／G5・G7・G12（cli）／side-channel 凍結。
- **Stage 3**: G9a deterministic selector（orchestrator）。
- **Stage 4**: tracked ハーネス／run・analyze スクリプト／instrumentation／収集時スクラブ／cost ゲート（scripts）。
- **Stage 5**: 推論（run 単位 cluster bootstrap・TOST・多重性・log 効果量・RQ-D 交差検定）・図表。

## MVP カット（Phase A／workshop 級）
Stage 0 全部 ＋ Stage 1 全部 ＋ Stage 2 の B1・G3・G4・G5・G7 ＋ Stage 3 G9a ＋ Stage 4 の tracked ハーネス・run/analyze・scrub・instrumentation 最小。
これで **3 アーム（code_only / code_plus_summary / code_plus_full_log）×1 タスク×ローカル large×deterministic selector** を、契約固定・memory off・選択決定・valid 定義ありで回せる。落としてよい: linear search、memory topology ノブ、capability 勾配（RQ-D）、aide_journal、dosage、overflow 精緻化。

## 完了ログ（land 時に追記）
- [ ] B2 / 測定器 — land __ / 実機 gate __
- [ ] G1 HandoffConfig — land __ / gate __
- [ ] ローカル決定性 — land __ / gate __
- [ ] B1 / B3 / G4 — land __ / 実機 gate __
- [ ] G3 / G9a — land __ / 実機 gate __
- [ ] G5 / G7 / G12 — land __ / 実機 gate __
- [ ] ハーネス / scripts / scrub — land __ / 実機 gate __
