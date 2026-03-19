# ARI QuickStart Guide

## Overview

ARI（Artificial Research Intelligence）は、実験 → 論文執筆 → 再現性検証を自動化するパイプラインです。
MCPスキル（Web検索・図生成・論文執筆・再現性検証）を組み合わせて動作します。

---

## 1. 必要な依存関係のインストール

### Python 依存（pip）— 全環境共通

```bash
pip install litellm mcp fastmcp pymupdf pdfminer.six networkx seaborn
```

### PDF テキスト抽出ツール（`review_compiled_paper` で使用）

ARI は PDF からテキストを抽出するために以下を順番に試みます：

#### 方法 A：conda でインストール（**推奨・sudo不要**）

```bash
conda install -c conda-forge poppler
```

インストール後 `pdftotext` が使用可能になります：

```bash
which pdftotext   # → $CONDA_PREFIX/bin/pdftotext
```

> sudo権限がない環境（例: 共有HPCクラスター）では
> システムパッケージ (`dnf install poppler-utils`) は使用できません。
> conda 経由でインストールしてください。

#### 方法 B：pip のみ（conda 不要）

sudo も conda も不要。ARI は pymupdf / pdfminer を自動 fallback として使います：

```bash
pip install pymupdf pdfminer.six
```

#### PDF 抽出エンジンの優先順位

| 優先 | エンジン | インストール |
|------|----------|------|
| 1 | `pymupdf (fitz)` | `pip install pymupdf` |
| 2 | `pdfminer.six` | `pip install pdfminer.six` |
| 3 | `pdftotext` | `conda install -c conda-forge poppler` |

---

## 2. LaTeX 環境のセットアップ

```bash
# conda（sudo不要・推奨）
conda install -c conda-forge texlive-core chktex

# またはシステムパッケージ（sudo必要）
sudo dnf install texlive texlive-latex   # RHEL/CentOS/Rocky
sudo apt install texlive-full            # Ubuntu/Debian
```

TeX Live をユーザーローカルにインストールした場合:

```bash
export PDFLATEX_PATH=$HOME/.local/bin/pdflatex
```

---

## 3. 設定ファイル（`ari-core/config/workflow.yaml`）

```yaml
# ── 論文設定 ──────────────────────────────────────
# 著者名（デフォルト: Artificial Research Intelligence）
author_name: Artificial Research Intelligence

# 実験コンテキスト（技術仕様のみ・組織名・クラスター名を含めないこと）
paper_context: |
  実験の技術仕様をここに記述してください。
  例：ハードウェア、コンパイラ、測定値など。
  組織名・サーバー名・内部識別子は含めないこと。
```

---

## 4. 環境変数（SLURM スクリプト / .bashrc）

```bash
# LLM モデル設定
# OpenAI 経由（新しいモデルは openai/ プレフィックスが必要）
export ARI_LLM_MODEL=openai/gpt-5.2

# Ollama ローカルモデル（プレフィックス不要）
# export ARI_LLM_MODEL=qwen3:32b

# OpenAI API キー（OpenAI モデル使用時）
export OPENAI_API_KEY=sk-...

# Ollama（ローカルLLM使用時）
export OLLAMA_HOST=127.0.0.1:11434
export LLM_API_BASE=http://127.0.0.1:11434

# ARI が OpenAI を使う場合は LLM_API_BASE を空にする
export ARI_LLM_API_BASE=

# LaTeX パス（ユーザーローカルインストールの場合）
export PDFLATEX_PATH=$HOME/.local/bin/pdflatex

# ARI ルートディレクトリ
export ARI_ROOT=/path/to/ari
```

---

## 5. 初回実行

```bash
# パイプライン実行（チェックポイント再利用可能）
cd ~/ARI
python3 run_pipeline.py <checkpoint_dir> ari-core/config/workflow.yaml

# SLURM
sbatch your_pipeline_job.sh

# 結果確認
ls ~/ARI/logs/<checkpoint_dir>/
#   full_paper.tex           論文 LaTeX ソース
#   full_paper.pdf           コンパイル済み PDF
#   review_report.json       レビュースコア・指摘事項
#   reproducibility_report.json  再現性検証結果
```

---

## 6. トラブルシューティング

| エラー | 原因 | 対処 |
|--------|------|------|
| `bad escape \X at position 0` | 正規表現パターン内の無効なエスケープ | raw string `r'\\...'` を使用 |
| `LLM Provider NOT provided` | litellm が新しいモデル名を未認識 | `openai/gpt-5.2` のようにプレフィックスを付ける |
| `No paper text available` | PDF抽出ツール未インストール | `conda install -c conda-forge poppler` または `pip install pymupdf` |
| `Missing $` in LaTeX | LLM が数式を `$` で囲んでいない | リフレクションループが自動修正（最大5ラウンド） |
| `??` (undefined ref) | `\ref{}` ラベル不一致 | 同上（リフレクションループ） |
| traceback が SLURM ログに出ない | MCP サーバーが stdio サブプロセス | `~/ARI/logs/ari_wpi_traceback.txt` を確認 |

---

## 7. スキル一覧

| スキル | 主要ツール | 説明 |
|--------|-----------|------|
| `paper-skill` | `write_paper_iterative`, `review_compiled_paper` | LaTeX論文生成・レビュー（最大5ラウンド自動修正） |
| `web-skill` | `web_search`, `search_arxiv`, `search_semantic_scholar` | 関連論文検索 |
| `plot-skill` | `generate_figures`, `generate_figures_llm` | matplotlib/seaborn 図生成 |
| `paper-re-skill` | `reproduce_from_paper`, `extract_metric_from_output` | 再現性検証 |
| `idea-skill` | `survey`, `generate_ideas` | アイデア生成 |

## 8. 実験モニタ（Experiment Monitor）

実験の進行をリアルタイムで可視化できます：

```bash
ari viz --checkpoint logs/<ckpt_dir> --port 9878
```

ブラウザで `http://localhost:9878` を開くと：

- **実験ツリー** — BFTSノードが木構造で表示されます（成功🟢 / 失敗🔴 / 実行中🔵 / 待機⚪）
- **ノード詳細** — ノードをクリックすると4タブのパネルが開きます
  - **Overview** — ステータス・メトリクス・評価サマリ
  - **Trace** — エージェントが実行したMCPツール呼び出しの全履歴
  - **Code** — 生成されたソースコード
  - **Output** — ジョブの標準出力・ベンチマーク結果
- **ベストスコア** — 画面下部に現在の最高メトリクス値を常時表示

複数実験を並行モニタする場合はポートを変えてください（例: `--port 9879`）。
