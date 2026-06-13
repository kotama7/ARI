# Plan — memory backend 側: RQ-C surface/topology ＋ retrieved-text ロギング

Status: 実装計画（未実装、Phase C 主体）。Origin: 2026-06 handoff study 設計。
親計画: [`../ari-core/MASTER_PLAN_handoff_impl.md`](../ari-core/MASTER_PLAN_handoff_impl.md)、研究計画 [`../ari-core/PLAN_artifact_summary_handoff.md`](../ari-core/PLAN_artifact_summary_handoff.md) §3（SURFACE/TOPOLOGY）/ §5 RQ-C / §8 Stage 4。

## 位置づけ
RQ-A/B（MVP）の memory **gate**（注入の on/off）は loop 側 [`../ari-core/ari/agent/Plan.md`](../ari-core/ari/agent/Plan.md)（B1）が担当する。本書は **memory backend 側**＝RQ-C の「同一 content を push か pull か（surface）」「any-ancestor reach（topology）」を**統制可能にし検証する**ための backend 改修で、**Phase C 主体・MVP では不要**。

## 依存関係（他 Plan.md）
- 上流依存:
  - [`../ari-core/ari/agent/Plan.md`](../ari-core/ari/agent/Plan.md)（B1 gate / G4 注入）— pure-PULL は loop 側で push ブロックを抑制して初めて成立。
  - [`../ari-core/ari/orchestrator/Plan.md`](../ari-core/ari/orchestrator/Plan.md)（G3）— surface 比較で「同一 content」を固定するため、view 生成と整合。
- 下流: [`../scripts/Plan.md`](../scripts/Plan.md)（analyze が surface 検証ログを読む）。

## 削除要件
retrieved-text ロギングと pure-PULL／topology の per-arm 制御が main に land し、実機で「push と pull で同一 content が届いたことを検証できる」「parent-only / full-ancestor の reach を arm で切替えられる」を確認、MASTER 完了ログに記録された時点で本 Plan.md を削除する。RQ-C を実施しない判断なら、その旨を MASTER に記録して削除。

## 実装項目（`src/ari_skill_memory/`）
1. **retrieved-text ロギング**: `access_log.py` の `build_read_event` は現状 entry_id / score（または type）のみ記録し**取得テキストを残さない**（write preview は約 200 字 cap）。read イベントに**取得テキスト**を記録し、「push 面と pull 面で同一 content が子に届いた」ことを事後検証可能にする。両 backend（`backends/in_memory.py`、`backends/letta_backend.py`）の read 経路に対応。
2. **pure-PULL の成立条件（backend 側）**: backend は既に `search_memory` を提供。loop 側（B1）で Tier-1b/2 の in-prompt push を抑制した上で、agent 駆動 PULL が安定動作することを担保（ancestor-scope は `backends/in_memory.py:101-106` で既にサーバ側強制）。
3. **topology ノブ**: reach は `ancestor_ids` 引数で決まる（`backends/in_memory.py:103` `allowed=set(ancestor_ids)`）。parent-only=`[parent_id]` / full=全祖先 / none=`[]` を arm で切替えられることを確認・必要なら明示 API 化（backend 改修は最小）。

## 検証ゲート（実機）
content を固定して push-only / pull-only / both を切替え、read ログから「同一 content が両 surface で配送された」ことを確認。`ancestor_ids` で parent-only と full-ancestor の reach 差が出ることを確認。
