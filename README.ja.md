<div align="center">
  <img src="docs/logo.png" alt="ARI Logo" width="200"/>

  # ARI — Artificial Research Intelligence

  **ユニバーサルな研究自動化システム。ノートPCからスーパーコンピュータまで。ローカルモデルからクラウドAPIまで。初学者から熟練研究者まで。計算実験から物理世界まで。**

  [![Tests](https://img.shields.io/badge/tests-1200%2B-brightgreen)](./ari-core)
  [![Version](https://img.shields.io/badge/version-v0.6.0-orange)](https://github.com/kotama7/ARI/releases)
  [![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
  [![MCP](https://img.shields.io/badge/protocol-MCP-purple)](https://modelcontextprotocol.io)
  [![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)
  [![Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/SbMzNtYkq)

  **言語:** [English](README.md) · **日本語** · [中文](README.zh.md)
</div>

---

## ビジョン

研究の自動化は、スーパーコンピュータも、クラウド予算も、エンジニアチームも必要としないはずです。

ARI は一つの原則に基づいて設計されています：**ゴールを Markdown で記述するだけ — 残りは ARI が処理する。**

- ノートPCとローカルLLMを持つ学生は、初めての自律実験を10分で実行できます。
- HPCクラスタにアクセスできる研究者は、50ノード並列の仮説探索を一晩で実行できます。
- チームは MCP スキルを1つ追加するだけで、ARI を実験ハードウェア・ロボティクス・IoTセンサーの制御に拡張できます — コア部分には一切手を加えずに。

システムは5つの軸でスケールします：

| 軸 | 最小構成 | フル構成 |
|------|---------|------|
| **計算** | ノートPC（ローカルプロセス） | スパコン（SLURM クラスタ） |
| **LLM** | ローカル Ollama (qwen3:8b) | 商用 API (GPT-5, Claude) |
| **実験仕様** | 3行の `.md` | 詳細な SLURM スクリプト + ルール |
| **ドメイン** | 計算ベンチマーク | 物理世界（ロボット・センサー・実験室） |
| **習熟度** | 初学者（ゴールのみ） | 熟練者（全パラメータ制御） |

---

## 動作を見る

<p align="center">
  <video src="https://github.com/kotama7/ARI/raw/main/docs/movie/ja/ari_dashboard_demo.mp4" controls width="720" muted playsinline>
    お使いのブラウザはインライン動画再生に対応していません。<a href="docs/movie/ja/ari_dashboard_demo.mp4">こちらからダウンロード</a>してください。
  </video>
</p>

🎬 **ダッシュボードのデモ動画** — ARI Web ダッシュボードの完全ウォークスルー。[English](docs/movie/en/ari_dashboard_demo.mp4) · [中文](docs/movie/zh/ari_dashboard_demo.mp4) も利用可能。

📄 **[サンプル成果物 (PDF)](docs/sample_paper.pdf)** — ARI が完全自律で生成した実物の論文。図表・引用・再現性検証レポートを含みます。主な数値は [実証された結果](#実証された結果) を参照してください。

<details>
<summary><b>📖 クリックで論文を展開（全 11 ページをスクロールで閲覧）</b></summary>

<p align="center">
  <img src="docs/images/sample_paper/page-01.png" alt="サンプル論文 — 1 ページ目" width="720"/>
  <img src="docs/images/sample_paper/page-02.png" alt="サンプル論文 — 2 ページ目" width="720"/>
  <img src="docs/images/sample_paper/page-03.png" alt="サンプル論文 — 3 ページ目" width="720"/>
  <img src="docs/images/sample_paper/page-04.png" alt="サンプル論文 — 4 ページ目" width="720"/>
  <img src="docs/images/sample_paper/page-05.png" alt="サンプル論文 — 5 ページ目" width="720"/>
  <img src="docs/images/sample_paper/page-06.png" alt="サンプル論文 — 6 ページ目" width="720"/>
  <img src="docs/images/sample_paper/page-07.png" alt="サンプル論文 — 7 ページ目" width="720"/>
  <img src="docs/images/sample_paper/page-08.png" alt="サンプル論文 — 8 ページ目" width="720"/>
  <img src="docs/images/sample_paper/page-09.png" alt="サンプル論文 — 9 ページ目" width="720"/>
  <img src="docs/images/sample_paper/page-10.png" alt="サンプル論文 — 10 ページ目" width="720"/>
  <img src="docs/images/sample_paper/page-11.png" alt="サンプル論文 — 11 ページ目" width="720"/>
</p>

</details>

---

## ARI が行うこと

```
experiment.md  ──►  ARI Core  ──►  結果 + 論文 + 再現性レポート
                       │
          ┌────────────┼──────────────────────────────┐
          │            │                              │
     BFTS Engine    ReAct Loop            Post-BFTS Pipeline
   (最良優先         (ノード毎エージェント) (workflow.yaml 駆動)
    木探索)              │
                    MCP Skill Servers
                    (プラグインシステム — 任意の機能を追加可能)
```

1. **ゴールを記述する。** 実験ファイルを書きます。ARI がそれを読み、仮説を生成し、実験を実行し、結果を報告します。
2. **仮説空間を BFTS で探索。** 最良優先木探索（BFTS）が探索を導きます — 全探索ではなく、エビデンス駆動です。
3. **決定論的ツール、推論する LLM。** MCP スキルは純粋関数です。LLM が推論し、スキルが実行します。
4. **論文から証明まで。** ARI は論文を執筆し、*さらに* 再現性チェックで自身の主張を検証します。

---

## 物理世界への拡張を見据えた設計

ARI の MCP プラグインアーキテクチャは、計算を超えて成長できるよう意図的に設計されています：

```
現在（計算）:
  ari-skill-hpc        → SLURM ジョブ投入
  ari-skill-evaluator  → stdout からのメトリクス抽出
  ari-skill-paper      → LaTeX 論文執筆
  ari-skill-vlm        → VLM による図/表の品質レビュー
  ari-skill-web        → プラガブル検索（Semantic Scholar + AlphaXiv）

将来（物理世界）:
  ari-skill-robot      → ROS2 MCP ブリッジ経由のロボットアーム制御
  ari-skill-sensor     → 温度・圧力センサー読み取り
  ari-skill-labware    → ピペット制御・プレートリーダー統合
  ari-skill-camera     → コンピュータビジョンによる実験観測
```

これらを追加するのに **ari-core への変更は不要** です。`@mcp.tool()` 関数を持つ `server.py` を書き、`workflow.yaml` に登録するだけで完了です。

---

## クイックスタート

```bash
# 1. インストール
git clone https://github.com/kotama7/ARI && cd ARI
bash setup.sh

# 2. AI モデルの設定（いずれかを選択）
ollama pull qwen3:8b                          # 無料・ローカル
export ARI_BACKEND=openai OPENAI_API_KEY=sk-… # またはクラウド API

# 3. ダッシュボードを起動
ari viz ./checkpoints/ --port 8765
# http://localhost:8765 を開く → 実験ウィザードで実験を作成・起動
```

CLI から直接実行することもできます：
```bash
ari run experiment.md                 # 実験を実行
ari run experiment.md --profile hpc   # SLURM クラスタで実行
```

ダッシュボードの詳細は **[docs/ja/quickstart.md](docs/ja/quickstart.md)** を、CLI コマンドは **[docs/ja/cli_reference.md](docs/ja/cli_reference.md)** を参照してください。

---

## 実験ファイル — 2 つのレベル

**初学者（3 行）:**
```markdown
# 行列積最適化
## Research Goal
このマシンでの DGEMM の GFLOPS を最大化する。
```

**熟練者（フルコントロール）:**
```markdown
# タンパク質フォールディング力場スイープ
## Research Goal
AMBER 力場バリアント間のエネルギースコアを最小化する。
## SLURM Script Template
```bash
#!/bin/bash
#SBATCH --nodes=4 --ntasks-per-node=32 --time=02:00:00
module load gromacs/2024
gmx mdrun -v -deffnm simulation -ntmpi 32
```
## Rules
- HARD LIMIT: 128 MPI タスクを超えない
- slurm_submit では常に work_dir=/abs/path を使用
<!-- min_expected_metric: 50000 -->
```
```

---

## Web ダッシュボード（メインインターフェイス）

ビジュアルな実験管理のための 10 ページ構成 React/TypeScript SPA。起動方法：

```bash
ari viz ./checkpoints/ --port 8765   # http://localhost:8765
```

| ページ | 機能 |
|------|----------|
| **Home** | クイックアクション、最近の実験、システムステータス |
| **New Experiment** | 4 ステップウィザード: チャット/記述/アップロードでゴール設定 → スコープ（深さ・ノード数・ワーカー・再帰深度）→ リソース（LLM・HPC・コンテナ・**Paper Review** ルーブリック / few-shot 管理 / アンサンブル数 / リフレクション回数）→ 起動 |
| **Experiments** | 全チェックポイントプロジェクトの一覧/削除/再開、ステータスとレビュースコア表示 |
| **Monitor** | リアルタイムフェーズステッパー（Idle → Idea → BFTS → Paper → Review）、ライブログ配信（SSE）、コスト追跡 |
| **Tree** | インタラクティブな BFTS ノードツリー。任意のノードをクリックしてメトリクス・ツール呼び出しトレース・生成コード・出力を確認 |
| **Results** | Overleaf 風 LaTeX エディタ（編集/コンパイル/プレビュー）、論文 PDF ビューア、レビューレポート、再現性結果、EAR ブラウザ |
| **Ideas** | VirSci 生成の仮説、新規性/実現可能性スコア、ギャップ分析 |
| **Workflow** | React Flow ビジュアル DAG エディタ（ドラッグ・接続・有効/無効・スキル割り当て、`BFTS / Paper / Reproduce` の phase トグル付き） |
| **Settings** | LLM プロバイダ/モデル、API キー、SLURM、コンテナランタイム、VLM レビューモデル、検索バックエンド、Ollama ホスト、**Memory (Letta)** バックエンド |
| **Sub-Experiments** | 再帰的サブ実験ツリーと親子追跡（orchestrator スキル経由） |

WebSocket（ツリー変更）と SSE（ログ配信）でリアルタイム更新。全データはプロジェクト単位で分離されます。

### Dashboard API

ダッシュボードはプログラムからも使える REST + WebSocket API を公開しています：

| エンドポイント | メソッド | 用途 |
|----------|--------|---------|
| `/state` | GET | 実験の全状態（フェーズ、ノード、設定、コスト） |
| `/api/launch` | POST | フル設定で新規実験を起動 |
| `/api/run-stage` | POST | 特定ステージ実行（resume / paper / review） |
| `/api/checkpoints` | GET | 全チェックポイントプロジェクト一覧 |
| `/api/settings` | GET/POST | LLM・SLURM・コンテナ・API キー設定の読み書き |
| `/api/workflow` | GET/POST | workflow.yaml パイプラインの読み書き |
| `/api/workflow/flow` | GET/POST | ワークフローの React Flow グラフ表現 |
| `/api/chat-goal` | POST | 実験ゴール磨き上げのマルチターン LLM チャット |
| `/api/upload` | POST | experiment.md またはデータファイルをアップロード |
| `/api/upload/delete` | POST | アップロードファイルの削除 |
| `/api/stop` | POST | 実行中実験を安全に停止 |
| `/api/logs` | GET (SSE) | ライブログとコストデータのストリーミング |
| `/api/checkpoint/{id}/files` | GET | 論文ディレクトリのファイル一覧 |
| `/api/checkpoint/{id}/file` | GET/POST | 論文ファイルの読み書き |
| `/api/checkpoint/compile` | POST | LaTeX コンパイルの実行 |
| `/api/checkpoint/{id}/filetree` | GET | チェックポイントのディレクトリツリー全体 |
| `/api/ear/{run_id}` | GET | 実験アーティファクトリポジトリの内容 |
| `/api/sub-experiments` | GET/POST | 再帰的サブ実験の一覧/起動 |
| `/api/rubrics` | GET | 同梱レビュールーブリック一覧（Wizard ドロップダウン用） |
| `/api/fewshot/<rubric>` | GET | ルーブリックごとの few-shot サンプル一覧 |
| `/api/fewshot/<rubric>/{sync,upload,delete}` | POST | manifest からの取得・1 件アップロード・1 件削除 |
| `/api/memory/{health,detect,start-local,stop-local,restart}` | GET/POST | Letta バックエンド管理 |
| `/api/checkpoint/{id}/memory_access` | GET | ノードごとの write/read プロビナンスログ |
| `/memory/<node_id>` | GET | ノードメモリ（ツール呼び出しトレース）の取得 |
| `ws://host:{port+1}/ws` | WebSocket | リアルタイムツリー更新の購読 |

---

## CLI コマンド

ダッシュボードの全機能はコマンドラインからも利用可能です：

| コマンド | 説明 |
|---------|-------------|
| `ari run <experiment.md>` | 新しい実験を実行（BFTS + 論文パイプライン） |
| `ari resume <checkpoint_dir>` | チェックポイントから再開 |
| `ari paper <checkpoint_dir>` | 論文パイプラインのみ実行（BFTS スキップ） |
| `ari status <checkpoint_dir>` | ノードツリーとサマリーを表示 |
| `ari projects` | 全実験ランの一覧 |
| `ari show <checkpoint>` | 詳細結果（ツリー + レビューレポート） |
| `ari delete <checkpoint>` | チェックポイントを削除 |
| `ari settings` | 設定を表示/変更（モデル、パーティションなど） |
| `ari skills-list` | 利用可能な MCP ツール一覧 |
| `ari memory <subcmd>` | Letta メモリの管理（`migrate` / `backup` / `restore` / `start-local` / `stop-local` / `prune-local` / `compact-access` / `health`） |
| `ari viz <checkpoint_dir>` | Web ダッシュボードを起動 |

### 出力ファイル

実行完了後、出力は `./checkpoints/<run_id>/` に保存されます：

| ファイル | 説明 |
|------|-------------|
| `tree.json` | BFTS ノードツリー全体（全ノード、メトリクス、親子リンク） |
| `results.json` | ノード毎のアーティファクト、メトリクス、ステータス |
| `idea.json` | VirSci 生成仮説とギャップ分析 |
| `science_data.json` | 科学向けデータ（内部 BFTS 用語なし） |
| `full_paper.tex` / `.pdf` | 生成された LaTeX 論文とコンパイル済 PDF |
| `review_report.json` | ルーブリック駆動の査読（AI Scientist v1/v2 互換）。既定は単一査読者で、`ARI_NUM_REVIEWS_ENSEMBLE>1` のとき `ensemble_reviews[]` と Area Chair `meta_review{}` を同梱 |
| `reproducibility_report.json` | 独立した再現性検証（サンドボックス化された `react_driver` が phase: reproduce の MCP スキルで動作） |
| `figures_manifest.json` | 生成された図のパスとキャプション |
| `ear/` | 実験アーティファクトリポジトリ（コード、データ、ログ、再現性メタデータ） |
| `cost_trace.jsonl` | 呼び出し毎の LLM コスト追跡 |
| `experiments/<slug>/<node_id>/` | ノード毎の作業ディレクトリと生成コード |

---


## アーキテクチャ

### スキル（MCP プラグインサーバー）

合計 13 スキル。12 個は `workflow.yaml` でデフォルト登録され、残り 1 個（orchestrator）は設定に追加することで有効化できます。

v0.6.0 では 2 つのスキルを廃止しました。`ari-skill-figure-router` は `ari-skill-plot` に統合され（matplotlib プロットと SVG アーキテクチャ図を単一スキルで扱い、同じ VLM レビューループで両方を駆動）、`ari-skill-review`（リバッタル生成）は削除されました — ルーブリック駆動の査読スコアが最終的な品質シグナルであり、自前論文へのリバッタルは情報量を追加しないためです。

| スキル | 役割 | LLM? | デフォルト |
|---|---|---|---|
| `ari-skill-hpc` | SLURM 投入 / ポーリング / Singularity / bash | ✗ | ✓ |
| `ari-skill-evaluator` | 実験ファイルからのメトリクス抽出 | △ | ✓ |
| `ari-skill-idea` | arXiv サーベイ + VirSci 仮説生成 | ✓ | ✓ |
| `ari-skill-web` | DuckDuckGo, arXiv, Semantic Scholar / AlphaXiv, 反復引用収集, アップロードファイルアクセス | △ | ✓ |
| `ari-skill-memory` | 祖先スコープのノードメモリ（v0.6.0 以降は Letta バックエンド） | △ | ✓ |
| `ari-skill-transform` | BFTS ツリー → 科学向けデータ + EAR 生成 | ✓ | ✓ |
| `ari-skill-plot` | 統合図生成（matplotlib プロット + SVG 図を図単位で切り替え、VLM ループ対応） | ✓ | ✓ |
| `ari-skill-paper` | LaTeX 執筆 + BibTeX + ルーブリック駆動レビュー（単一 or N 名アンサンブル + Area Chair メタ） | ✓ | ✓ |
| `ari-skill-paper-re` | ReAct 再現性検証 | ✓ | ✓ |
| `ari-skill-benchmark` | CSV/JSON 分析、プロット、統計検定 | ✗ | ✓ |
| `ari-skill-vlm` | Vision-Language モデルによる図/表レビュー | ✓ | ✓ |
| `ari-skill-coding` | コード生成 + 実行 + ファイル読取 + bash | ✗ | ✓ |
| `ari-skill-orchestrator` | ARI を MCP サーバとして公開、再帰的サブ実験、stdio+HTTP デュアル転送 | ✗ | — |

✗ = LLM 不使用、△ = 一部ツールで LLM 使用、✓ = 主要ツールが LLM 使用。

### 設計原則

| # | 原則 | 意味 |
|---|-----------|---------|
| P1 | ドメイン非依存コア | `ari-core` には実験固有の知識がゼロ |
| P2 | 可能な限り決定論的 | MCP ツールはデフォルトで決定論的、LLM 使用ツールは明示的に注釈。*v0.6.0 で `ari-skill-memory` のみ緩和 — Letta の埋め込み検索を使用* |
| P3 | 多目的メトリクス | ハードコードされたスカラースコアなし |
| P4 | 依存性注入 | 実験の切り替え = `.md` の編集のみ |
| P5 | 再現性ファースト | 論文ではクラスタ名ではなくスペックでハードウェアを記述。*Letta バックエンドでは BFTS 探索順が再実行時に変わり得るが、数値結果は再現可能。* `docs/PHILOSOPHY.md` 参照 |

---

## 実証された結果

ARI はマルチコア CPU 上の **CSR SpMM**（スパース行列と密行列の積）について、設計・実装・実行・論文執筆までを完全自律で end-to-end に行いました。手法・アルゴリズム・図表・参考文献を含む完全な論文は [`docs/sample_paper.pdf`](docs/sample_paper.pdf) で公開されています。

> **Stoch-Loopline: Burstiness- and Tail-Latency-Aware Loopline Modeling for Robust Multi-Core CPU CSR SpMM Scaling**

| 構成 | GFLOP/s | 実効帯域幅 |
|---|---|---|
| K ブロック化 CSR SpMM（ピークスループット） | 23.82 | 58.30 GB/s |
| 検証スイープ（ピーク、*N* = 16、32 スレッド） | **26.22** | **65.55 GB/s** |
| 最大計測帯域幅（ルートスイープ） | 17.17 | **105.18 GB/s** |
| ソフトウェアプリフェッチによる改善（幅平均） | **+3.53** | **+8.18 GB/s** |

**ハードウェア:** `fx700` マルチコア CPU ノード、OpenMP、32 スレッド。合成 CSR 行列は最大 *M* = *K* = 200,000（約 3.2M 非ゼロ要素）、行長分布は uniform と Zipf、密幅 *N* ∈ {4, 8, 16, 32, 64, 128}。

**ARI が自律的に生み出したもの:** Stoch-Loopline モデル化の枠組み、2 種類の CSR×dense カーネル実装（行並列 gather と rows-in-flight）と明示的なアンロール/ウィンドウつまみ、K ブロック化 / N タイリング + パッキング / scalar / no-AVX のアブレーション、実験スイープ、図表、参考文献、再現性検証 — すべて人間の介入なしに生成されました。

---

## ライセンス

MIT。[LICENSE](./LICENSE) を参照してください。
