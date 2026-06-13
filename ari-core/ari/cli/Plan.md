# Plan — G5 copy トグル ／ G7 sterile-gate 対称化 ／ G12 timeout・overflow

Status: 実装計画（未実装）。Origin: 2026-06 handoff study 設計。
親計画: [`../../MASTER_PLAN_handoff_impl.md`](../../MASTER_PLAN_handoff_impl.md)、研究計画 [`../../PLAN_artifact_summary_handoff.md`](../../PLAN_artifact_summary_handoff.md) §0.2 / §8 Stage 2。

## 依存関係（他 Plan.md）
- 上流依存:
  - [`../config/Plan.md`](../config/Plan.md)（G1/配線）— `copy_workdir` 等を `agent.handoff` 経由で読む。
- 関連: [`../agent/Plan.md`](../agent/Plan.md)（配線の対側）。
- 下流: [`../../scripts/Plan.md`](../../scripts/Plan.md)。

## 削除要件
G5・G7・G12 が main に land し、実機で「copy on/off がアームで効く」「sterile 判定がアーム不変」「per-node 予算が強制 or 明示除外」を確認、MASTER 完了ログに記録された時点で本 Plan.md を削除する。

## 実装項目（すべて `bfts_loop.py`）
1. **G5 copy トグル**: 親→子 work_dir copy（`bfts_loop.py:414-445`）を `getattr(agent,"handoff",None).copy_workdir` で gate（既定 True で現状維持）。`_OUTPUT_BLACKLIST` はそのまま。
2. **G7 sterile-gate 対称化**: `compute_files_changed(parent,child)`（`bfts_loop.py:631-656`）は無条件で score を 0 clamp。copy-OFF アームでは子 dir 空 → 全ファイル「deleted」→ sterile 判定が反転する。**copy-OFF では空 baseline 基準**（子が自分で書いた added/modified のみ数え、幽霊 deleted を無視）にし、アーム間で「no-op」の意味を一定化。
3. **G12 timeout / overflow**: dead code の TimeoutError 分岐（`bfts_loop.py:532-541`、`as_completed` 後で発火不能）を、(a) 実 wall-clock kill（子をキャンセル可能プロセスで）に直すか、(b) 統制変数から明示除外し `max_react_steps` を唯一予算とする。いずれか事前登録。あわせて **full_log overflow カウンタ**と「overflow 時の full_log 定義」を導入（窓圧縮 `agent/loop.py:725` で full_log が黙って truncated 化するのを明示）。

## 検証ゲート（実機）
`copy_workdir=False` アームで親 code が子に来ない。do-nothing 子が copy-ON/OFF 両アームで同じ「sterile」判定。per-node 予算が全アーム同一で強制（or 明示除外を文書化）。
