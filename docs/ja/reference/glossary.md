---
sources:
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-core/ari/evaluator/llm_evaluator.py
    role: implementation
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/config/reviewer_rubrics
    role: config
  - path: ari-skill-replicate
    role: implementation
  - path: ari-skill-paper-re
    role: implementation
last_verified: 2026-05-26
---

# 用語集

ARI ドキュメント全体で繰り返し登場する用語を短く定義し、それぞれを詳しく解説する
ドキュメントへ案内します。用語は、属するサブシステムごとにまとめています。

## 探索とオーケストレーション

**BFTS (Best-First Tree Search)**
ARI の実験探索ループ。実験設定の木を探索し、常に最も有望な完了ノードを最初に展開します。
`ari/orchestrator/bfts.py` に実装されています。[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**pending**
BFTS の 2 つのプールの一方: 親から展開済みで実行可能な状態だが、まだ実行されていない
ノード群。[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**frontier**
BFTS のもう一方のプール: 展開待ちの完了済みノード群。フロンティアは *永続的* です —
ノードは子を生成した後も再展開可能なまま残り続け、退役するまで利用可能です。
[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**retire（フロンティアノードを退役させる）**
完了ノードをそれ以降の展開対象から外すこと。ノードは **ルール A**
（子が `_scientific_score` で親を上回る）または **ルール B**（`max_expansions_per_node`
回展開済みになった）のいずれかで退役します。[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**node label（ノードラベル）**
BFTS ノードが親に対して果たす役割: `draft`、`improve`、`debug`、
`ablation`、`validation`、`other`。未知のラベルは `other` に丸められ、
`raw_label` が原文の文字列を保持します。[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**diversity bonus（多様性ボーナス）**
探索が単一の戦略に収束しないよう、過少表現のノードラベル（直近 20 実行を追跡）に
与えられる `+0.05` のスコア補正。
[BFTS アルゴリズム](../concepts/bfts.md)を参照。

**sterile（不毛なノード）**
実行後の `work_dir` が親とバイト単位で同一になった子ノード
（sha256 差分で `added = modified = deleted = 0`）。`_sterile = True` とマークされ、
スコア `0.0` で剪定されます — これは、子が何も実行せずに親の結果を「継承」してしまうのを
防ぐ仕組みです。
[アーキテクチャ → work_dir 継承](../concepts/architecture.md#work_dir-inheritance--output-artifact-blacklist-v070--phase-7)を参照。

**should_prune**
BFTS の硬い打ち切り述語: `current_total ≥ max_total_nodes`、
`depth ≥ max_depth`、または `_sterile is True` のときに剪定します。
ここに LLM の判断は入りません。[BFTS アルゴリズム](../concepts/bfts.md)を参照。

## 評価

**scientific_score / `_scientific_score`**
`LLMEvaluator` が各ノードに付与する査読品質スコア（0.0〜1.0）。
`metrics["_scientific_score"]` に格納され、BFTS のランキング、系統（lineage）の判断、
ベストノードの選択を駆動します。
[設定 → BFTS Evaluation Layers](configuration.md#bfts-evaluation-layers-configurable)を参照。

**composite formula（合成式）**
各軸のスコアを 1 つのスカラーに集約する方法: `harmonic_mean`（既定）、
`arithmetic_mean`、`weighted_min`、`geometric_mean`。
`evaluator.composite` で設定できます。
[設定 → BFTS Evaluation Layers](configuration.md#bfts-evaluation-layers-configurable)を参照。

**plan（プラン）**
実行の *評価の具体内容* — どのメトリクスを測るか、どのベースラインと比較するか、
どのアブレーションを走らせるか。`idea.json[0].experiment_plan` を出所とします。
既定ではサブ実験に継承されません（子は自前で書くため、方向転換の自由を保てます）。
[アーキテクチャ → Plan / Venue 契約](../concepts/architecture.md#plan--venue-contract-v070)を参照。

**venue（ベニュー）**
実行の *判定基準* — どの次元を、どのように採点するか。ベニューは `ARI_RUBRIC` で選択される
`ari-core/config/reviewer_rubrics/<id>.yaml` ファイルです。
ベニューを切り替えると、BFTS の採点軸と、公開される査読の基準が同時に変わります。
[アーキテクチャ → Plan / Venue 契約](../concepts/architecture.md#plan--venue-contract-v070)を参照。

**rubric（ルーブリック）**
採点の仕様。ARI ではこの語を 2 つの文脈で使います: 論文査読向けの **reviewer rubric**
（上記のベニュー YAML）と、再現性採点向けの **ORS rubric**（PaperBench の `TaskNode` 木）です。
[ルーブリックスキーマ](rubric_schema.md)を参照。

**lineage decision（系統判断）**
合成スコアが停滞したとき、BFTS のフックが LLM に
`continue` / `switch_to_idea` / `fanout` / `terminate` を選ばせます。
[アーキテクチャ → Plan / Venue 契約](../concepts/architecture.md#plan--venue-contract-v070)を参照。

## メモリ

**ancestor scope（祖先スコープ）**
ノードは自身の祖先チェーン（root → 親）からのみメモリを読み取れ、兄弟からは決して
読み取れないというルール。`search_memory` のメタデータフィルタで強制されます。
[メモリアーキテクチャ](../concepts/memory.md)を参照。

**CoW (Copy-on-Write)**
兄弟間で祖先メモリをバイト単位で安定に保つための書き込みガード:
書き込み側のツールは、アクティブな `$ARI_CURRENT_NODE_ID` 以外の `node_id` をすべて拒否します。
[メモリアーキテクチャ](../concepts/memory.md)を参照。

**Letta**
v0.6.0 以降で使われているメモリバックエンド（旧 MemGPT）。各チェックポイントに専用の
エージェントが割り当てられ、2 つのコレクションを保持します: `ari_node_<hash>`（祖先スコープの
アーカイブ）と `ari_react_<hash>`（フラットな ReAct トレース）。
[メモリアーキテクチャ](../concepts/memory.md)を参照。

## エージェントとスキル

**ReAct loop（ReAct ループ）**
LLM の推論と MCP ツール呼び出しを交互に行って 1 つの実験を実行する、ノードごとの
エージェントループ（`ari/agent/loop.py`）。
[アーキテクチャ → ノードごとのプロンプト構成](../concepts/architecture.md#per-node-prompt-composition)を参照。

**MCP skill（MCP スキル）**
Model Context Protocol サーバーとしてパッケージ化された機能（例: `ari-skill-hpc`）。
スキルは `ari.public.*` からのみ import できます。全部で 14 個あります（既定 13 個 + 追加 1 個）。
[MCP スキル](skills.md)を参照。

**VirSci**
研究目標を仮説と主要メトリクスへと変換するマルチエージェント討議。ルートノードで
`generate_ideas` を通じて一度だけ実行されます。
[アーキテクチャ](../concepts/architecture.md#full-data-flow)を参照。

## 状態と公開

**checkpoint（チェックポイント）**
1 回の実行に対応する自己完結型ディレクトリ `{workspace}/checkpoints/{run_id}/`。
`run_id` は `YYYYMMDDHHMMSS_<slug>` 形式です。すべての状態はここに置かれ、`PathManager`
（`ari/paths.py`）が唯一の真実源です。API キーはここには決して保存されません —
`.env` または環境から取得されます。
[アーキテクチャ → ファイル構造](../concepts/architecture.md#file-structure)を参照。

**EAR (Experiment Artifact Repository)**
論文に同梱される、決定論的にビルドされる `ear/` バンドル（コード、入力データ、図表、README、
`reproduce.sh`、LICENSE）。実験の *出力* は意図的にバンドルされません。
[公開ライフサイクル](../concepts/publication-lifecycle.md)を参照。

## 再現性 (ORS / PaperBench)

**ORS**
ARI の再現性チェック — 論文を再実行して採点する、決定論的で PaperBench 互換の 2 フェーズ
フロー。v0.7.0 で旧来の LLM 判定経路を置き換えました。
[PaperBench クイックスタート](../guides/paperbench/paperbench_quickstart.md)を参照。

**TaskNode**
PaperBench 形式のルーブリック木におけるノード。論文から生成される ORS ルーブリックは、
重みと閉じた `task_category` 語彙を持つ `TaskNode` の木です。
[ルーブリックスキーマ](rubric_schema.md)を参照。

**Phase 1 / Phase 2**
ORS の 2 つのフェーズ: **Phase 1**（`run_reproduce`）はサンドボックス内で `reproduce.sh` を
実行します（`slurm` → `docker` → `apptainer` → `singularity` → `local`）。**Phase 2**
（`grade_with_simplejudge`）はルーブリックの葉に対して PaperBench SimpleJudge を実行します。
[PaperBench API](api_paperbench.md)を参照。

**negative control（陰性対照）**
ORS のガードレール: 空のリポジトリ + 自明な `reproduce.sh` は 5% 未満のスコアにならなければ
ならず、ルーブリックが「何もしていないこと」に報酬を与えないことを証明します。
[PaperBench API](api_paperbench.md)を参照。

**bridge stage（ブリッジステージ）**
v0.8.0 PaperBench ブリッジにおける 3 つのベンダープロトコルのエントリポイントの 1 つ:
`rollout_submission`（エージェントが提出物を生成）、`reproduce_submission`
（それを実行）、`judge_submission`（採点）。
[PaperBench API](api_paperbench.md)を参照。

**paper-audit mode（論文監査モード）**
ORS ルーブリックの仕組みを逆向きに用い（v0.7.2）、ベニューテンプレート
（`sc` / `neurips` / `nature`）に基づいて、論文 *自体* が再現可能なほど十分に
記述されているかを監査するモード。[ルーブリックスキーマ](rubric_schema.md)を参照。

---

関連: [アーキテクチャ](../concepts/architecture.md) ·
[BFTS アルゴリズム](../concepts/bfts.md) ·
[メモリアーキテクチャ](../concepts/memory.md) ·
[設定](configuration.md)
