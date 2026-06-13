---
sources:
  - path: ari-skill-memory
    role: implementation
  - path: ari-core/ari/pipeline/verified_context.py
    role: implementation
  - path: ari-core/ari/config
    role: config
last_verified: 2026-06-04
---

# ARI 検証可能リサーチメモリ

ARI のメモリを、実験結果・失敗・手順が **型付きで、成果物に接地し、検証可能**で
あるように構成する方法 — 自由記述の自然言語ログにとどめない。本書はその恒久的な
設計記録です（これを生んだ作業計画書は撤去済み）。ancestor-scoped な検索
ベースラインについては [memory.md](memory.md) も参照。

## なぜ

ancestor-scoped な Letta メモリ（memory.md）はブランチ分離を与えますが、保存内容は
ほぼ自由記述テキストです。リサーチ自動化システムには加えて次が必要です:

- 結果がどのログ / コード / 出力ファイルに依拠しているかを追跡する;
- 失敗ケース・修正・性能エビデンスを再利用する;
- 接地のない主張を論文の主張として決して使わない;
- 再現済みの結果と未検証の結果を区別する。

検証可能リサーチメモリは、Letta（低レベルのアーカイブ／検索バックエンドとして維持）
の **上に** 型付き・エビデンス接地の層を追加し、Letta を知識の所有者にはしません。

## 原則

1. **メモリはインデックスであってエビデンスではない** — メモリはエビデンス
   （成果物／メトリクス／コマンド／ログ）を指し示すものであり、主張そのものではない。
2. **単一の真実源 = `node_report.json`** — プロビナンス（メトリクス、sha256 付き
   成果物、build/run コマンド、files_changed、ハードウェア、concerns/hints）はそこに
   存在する。型付きメモリは `node_report_ref` ポインタと検索可能な `text` を持つだけで、
   node_report のフィールドをコピーしない。
3. **ブランチ分離** — ノードは自分の祖先のメモリのみを読む（兄弟／他チェックポイントは
   読まない）。
4. **Copy-on-Write・追記専用** — ノードは自分の `node_id` だけに書き込み、過去の
   エントリはバイト単位で不変のまま。状態変化（例: 再現性）は新しいイベントとして
   追記され、その場での編集は行わない。
5. **型付き** — すべてのエントリは `kind` を持つ（observation, experiment_result,
   failure_case, procedure, reflection, artifact_summary, paper_claim,
   reproducibility_event）。
6. **成果物接地の生成** — 論文／図の主張は成果物に裏付けられた（理想的には再現済みの）
   メモリにのみ依拠する。接地のない reflection は探索の助けにはなりうるが、論文本文には
   決して使わない。
7. **再現性を意識** — 再現性ステータスは追記専用イベントであり、読み取り時にターゲット
   ごとの最新値へ畳み込まれる。
8. **ループが統御** — メモリの読み書きは決定的なループ／パイプラインのフックが行う。
   LLM が能動的にメモリを引き出すことはない（実測: エージェントは recall ツールを一切
   呼ばず、recall は起動時の一度きりの事前シード）。エージェント自身の `add_memory` は
   オプションであり、依存しない。
9. **Letta は低レベルバックエンド** — アーカイブ挿入／セマンティック検索／
   チェックポイント単位のコレクションのみ。何を／どう／どこに／接地／検証するかは
   ARI が所有する。

## アーキテクチャ

```
node end ─▶ consolidate_node_memory  (node_report → typed experiment_result /
            (bfts_loop hook)           failure_case / reflection, with provenance)
                  ▼
          typed research-memory store (Letta archival, ancestor-scoped, CoW)
                  ▼
paper pipeline ─▶ write_verified_context (best node's root→best lineage)
                  → {checkpoint}/verified_context.json
                  ▼
write_paper ─▶ reads the path directly, render_grounded_block → system prompt
              → quantitative claims grounded only on verified, artifact-backed
                (rerun_passed first) results.
```

- **Working context（Phase 0）**: ノード開始時にループが実験コア（goal/metric/
  hardware）＋祖先の `result_summary` の結論を決定的に注入する（旧来の集約・切り詰め
  セマンティックダンプを置き換え）。これは *継承* パスであり、下記の検証可能層とは独立。
- **型付きインデックス／verified context**: 上記の検証可能層。`consolidation_enabled()`
  （デフォルト ON）でゲートされる。

## コンポーネント

- `ari-skill-memory`: `schemas.py`（型付きレコード）、`provenance.py`（node_report
  からの sha256 参照）、`audit.py`（claim↔artifact 整合性）、`writer.py` /
  `retriever.py`（型付き書き込み＋kind/scope/artifact フィルタ読み取り＋再現性
  畳み込み）、`consolidation.py`（node_report → specs）、`context_builder.py`
  （verified context）。MCP ツール（`add_experiment_result`,
  `search_research_memory`, `get_verified_context`, `consolidate_node_memory`,
  `audit_memory`, …）として公開され、すべてフックから呼ばれる。
- `ari-core`: `pipeline/verified_context.py`（best-node lineage スコープ＋
  grounded-block レンダリング）、`bfts_loop` のノード終了時 consolidation フック、
  および write_paper での消費。

## ゲーティングとコスト

`ARI_MEMORY_CONSOLIDATE`（デフォルト **ON**；`0`/`false`/`no`/`off` で無効化、単一の
真実源は `ari.config.consolidation_enabled`）が、ノード終了時の consolidation と論文の
verified-context 構築の両方を制御する。コスト: 既存の `result_summary` に加えて
ノードあたり約 1〜2 件の型付き書き込み（各々 embedding する）。実測で線形であり
許容範囲。

## 検証（実機）

- Phase 0 の working-context 注入: 実機 BFTS 実行で検証（実験コア＋祖先
  `result_summary` 全体、兄弟分離）。
- Consolidation: 実機で検証 — ノード終了フックがプロビナンス付き `experiment_result`
  （sha256 成果物参照 6 件＋node_report_ref）を書き、失敗ノードには `failure_case` を
  書いた。ループを壊すことなく動作。
- Verified context → 論文接地: 実データでエンドツーエンド検証し、paper パイプライン
  配線経由でも検証（`verified_context_json` は `load_inputs` ではなくパスとして渡される
  ため、write_paper ステージ／claim ステージのトポロジは乱されない）。

## 意図的な非目標

- **BFTS プランナーへの型付きインジェクション**（失敗の再発を避けるため祖先の
  failure_case/procedure を `expand()` に供給する）は、エビデンスゲートに照らして評価し
  **意図的に作らなかった** — 実機実行で失敗再発率 0% を実測した
  （`ari-core/REQUIREMENTS.md` 参照）。将来の実行で高い再発が見られた場合にのみ
  再評価する。
- Letta の自己編集、実験横断のグローバルメモリ、学習型メモリポリシー — スコープ外。
