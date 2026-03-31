# ARI クイックスタートガイド

このガイドでは、ARI のインストール、AI モデルの選択、**Web ダッシュボード**を使った最初の実験の実行方法を順を追って説明します。プログラミングの経験は不要です。

CLI（コマンドライン）での使い方については、[CLI リファレンス](cli_reference.md)を参照してください。

---

## 必要なもの

| 要件 | 詳細 |
|------|------|
| **OS** | Linux または macOS（Windows の場合は WSL2 を使用） |
| **Python** | 3.10 以降 |
| **Git** | リポジトリのクローンに使用 |
| **Web ブラウザ** | Chrome、Firefox、Safari、または Edge |

オプション（推奨）：

| ツール | 理由 |
|--------|------|
| **conda / miniconda** | LaTeX や PDF ツールのインストールが容易（sudo 不要） |
| **Ollama** | AI モデルをローカルで無料実行 — API キーもコストも不要 |
| **LaTeX** | ARI で PDF 論文を生成する場合のみ必要 |

---

## ステップ 1: ARI のインストール

ターミナルを開いて以下を実行してください：

```bash
git clone https://github.com/kotama7/ARI.git
cd ARI
bash setup.sh
```

セットアップスクリプトは OS を自動検出し、必要なものをすべてインストールします。Linux、macOS、WSL2 で動作し、conda や sudo の有無を問いません。

セットアップが完了すると、**「Setup Complete」** と次のステップの案内が表示されます。

---

## ステップ 2: AI モデルの選択

ARI は思考・計画・実験の実行に AI モデル（LLM）を必要とします。以下のいずれかを選択してください：

### オプション A: Ollama — 無料、ローカル実行（推奨）

アカウント不要。API キー不要。費用不要。すべてローカルで実行されます。

```bash
# Ollama のインストール
curl -fsSL https://ollama.com/install.sh | sh     # Linux
# brew install ollama                              # macOS

# モデルのダウンロード
ollama pull qwen3:8b

# サーバーの起動（このターミナルは開いたままにしてください）
ollama serve
```

環境変数の設定（新しいターミナルを開いてください）：

```bash
export ARI_BACKEND=ollama
export ARI_MODEL=qwen3:8b
```

> **モデルサイズの選び方**
>
> | モデル | 必要メモリ | 品質 |
> |--------|-----------|------|
> | `qwen3:8b` | 16 GB | 良い — 入門に最適 |
> | `qwen3:14b` | 32 GB | より良い |
> | `qwen3:32b` | 64 GB | 最良 |

### オプション B: OpenAI API（クラウド、有料）

```bash
export ARI_BACKEND=openai
export ARI_MODEL=openai/gpt-4o
export OPENAI_API_KEY=sk-...     # https://platform.openai.com/api-keys から取得
```

### オプション C: Anthropic API（クラウド、有料）

```bash
export ARI_BACKEND=claude
export ARI_MODEL=anthropic/claude-sonnet-4-5
export ANTHROPIC_API_KEY=sk-ant-...  # https://console.anthropic.com/ から取得
```

> **ヒント:** `export` 行を `~/.bashrc` や `~/.zshrc` に追加すると、設定が永続化されます。

---

## ステップ 3: ダッシュボードの起動

ARI Web ダッシュボードを起動します：

```bash
ari viz ./checkpoints/ --port 8765
```

ブラウザを開いて以下にアクセスしてください: **http://localhost:8765**

ARI のホーム画面が表示されます：

![ARI ホーム](images/ja/dashboard_home.png)

左側のサイドバーからすべてのダッシュボードページにアクセスできます：

| ページ | 説明 |
|--------|------|
| **Home** | クイックアクションと最近の実験の概要 |
| **Experiments** | 過去のすべての実験一覧 |
| **Monitor** | D3 ツリー可視化によるリアルタイムのパイプライン進捗 |
| **Tree** | BFTS 実験ツリーの全体表示 — ノードをクリックして詳細を確認 |
| **Results** | 生成された論文、レビュー、再現性レポートの閲覧 |
| **New Experiment** | 新しい実験を作成・起動するウィザード |
| **Ideas** | VirSci が生成した研究仮説 |
| **Workflow** | BFTS 後のパイプライン設定の編集 |
| **Settings** | LLM、API キー、SLURM、言語の設定 |

---

## ステップ 4: 最初の実験を作成する（ウィザード）

サイドバーの **「New Experiment」** をクリックしてください（またはホームページの青い **「New Experiment」** ボタン）。

![実験ウィザード](images/ja/dashboard_wizard.png)

ウィザードは 4 つのステップで進みます：

### ステップ 1/4 — モードの選択

| モード | 用途 |
|--------|------|
| **Chat** | 初心者向け。自然言語でやりたいことを記述すると、AI が質問しながら適切な実験に仕上げてくれます。 |
| **Write MD** | 実験の説明を Markdown で直接記述またはペーストします。 |
| **Upload** | 既存の `experiment.md` ファイルをアップロードします。 |

**初心者には Chat モードがおすすめです。** 最適化したい内容や調査したい内容を入力するだけです。例えば：

> 「ノートパソコンで実験のスコアを最大化する方法を見つけたい」

AI が確認の質問をして、実験ファイルを自動生成します。

### ステップ 2/4 — スコープ

実験の規模を設定します：

| 設定 | 制御対象 | 初回実行の推奨値 |
|------|---------|-----------------|
| **Max Depth** | 探索ツリーの深さ | 3 |
| **Max Nodes** | 実行する実験の総数 | 5〜10 |
| **Max ReAct Steps** | 実験ごとの推論ステップ数 | 80（デフォルト） |
| **Timeout** | 実験ごとのタイムアウト（秒） | 7200（デフォルト） |
| **Parallel Workers** | 同時実行する実験数 | 2〜4 |

> **ヒント:** 最初は小さく（ノード 5〜10、深さ 3）始めましょう。後からいつでも増やせます。

### ステップ 3/4 — リソース

LLM プロバイダーとモデルを選択します：

- **OpenAI / Anthropic / Ollama / Custom** — ドロップダウンから選択
- Ollama の場合は任意のモデル名を入力できます（例: `qwen3:8b`）
- クラスターで実行する場合は SLURM/HPC の設定を行います

### ステップ 4/4 — 起動

設定を確認して **Launch** をクリックします。ARI は以下を実行します：

1. 関連する学術論文を検索
2. 研究仮説を生成（VirSci マルチエージェント議論）
3. Best-First Tree Search で実験を実行
4. LLM ピアレビューで結果を評価
5. 図表と引用を含む LaTeX 論文を執筆
6. 再現性を独立して検証

---

## ステップ 5: 実験のモニタリング

実験を起動すると、**Monitor** ページにリアルタイムの進捗が表示されます：

![Monitor ページ](images/ja/dashboard_monitor.png)

- **パイプラインステージ** が上部に表示されます（Idea → BFTS → Paper → Review）
- **ノードツリー** で実験の進捗が色分けされたステータスで表示されます
- **ログ** がリアルタイムでストリーミングされます

### 実験ツリー

サイドバーの **Tree** をクリックすると、完全なインタラクティブ実験ツリーが表示されます：

![ツリービュー](images/ja/dashboard_tree.png)

- **緑** のノード = 成功
- **赤** のノード = 失敗
- **青** のノード = 実行中
- **灰色** のノード = 待機中

ノードをクリックすると詳細が表示されます：

| タブ | 表示内容 |
|------|---------|
| **Overview** | ステータス、メトリクス、実行時間、評価の概要 |
| **Trace** | AI エージェントが行ったすべてのツール呼び出し（ステップごと） |
| **Code** | この実験で生成されたソースコード |
| **Output** | ジョブの標準出力、ベンチマーク結果 |

---

## ステップ 6: 結果の確認

実験が完了したら、**Results** ページに移動します：

![Results ページ](images/ja/dashboard_results.png)

ここでは以下のことができます：

- 生成された論文の閲覧（LaTeX / PDF）
- 自動ピアレビューのスコアとフィードバックの確認
- 再現性検証レポートの確認
- すべての成果物のダウンロード

出力ファイルは `./checkpoints/<run_id>/` に保存されます：

| ファイル | 説明 |
|---------|------|
| `full_paper.tex / .pdf` | 生成された完全な論文 |
| `review_report.json` | ピアレビューのスコアとフィードバック |
| `reproducibility_report.json` | 独立した再現性検証 |
| `tree.json` | すべてのメトリクスを含む完全な実験ツリー |
| `science_data.json` | クリーンなデータ（内部用語なし） |
| `figures_manifest.json` | 生成された図表 |
| `experiments/` | ノードごとのソースコードと出力 |

---

## ステップ 7: 設定のカスタマイズ

**Settings** ページを開いて ARI をカスタマイズします：

![Settings ページ](images/ja/dashboard_settings.png)

### ダッシュボード言語

上部の言語ドロップダウンからダッシュボードの言語（英語、日本語、中国語）を変更できます。

### LLM バックエンド

- プロバイダーの選択（OpenAI、Anthropic、Ollama、Custom）
- デフォルトのモデルとテンパレチャーの設定
- API キーの入力（ローカルに保存、UI 上ではマスク表示）

### 論文検索

- より高いレート制限のため、必要に応じて Semantic Scholar API キーを設定

### SLURM / HPC

- クラスタージョブのデフォルトのパーティション、CPU 数、メモリを設定
- **Detect** をクリックすると、クラスターで利用可能なパーティションを自動検出

### フェーズごとのモデルオーバーライド

パイプラインのフェーズごとに異なるモデルを使用できます（例: アイデア生成にはより安価なモデル、論文執筆にはより高性能なモデル）。

---

## その他のダッシュボードページ

### Ideas ページ

![Ideas ページ](images/ja/dashboard_ideas.png)

VirSci が生成した研究仮説を、新規性と実現可能性のスコアとともに確認できます。実験設定、研究目標、BFTS ノードの評価も表示されます。

### Workflow エディター

![Workflow ページ](images/ja/dashboard_workflow.png)

BFTS 後のパイプラインステージ（データ変換 → 図表生成 → 論文執筆 → レビュー → 再現性チェック）を編集できます。変更は `workflow.yaml` として保存されます。

---

## トラブルシューティング

### インストール

| 問題 | 解決策 |
|------|--------|
| `ari: command not found` | `~/.local/bin` を PATH に追加: `export PATH="$HOME/.local/bin:$PATH"` |
| セットアップスクリプトが失敗する | Python のバージョンを確認: `python3 --version`（3.10 以上が必要） |
| 権限エラー | `sudo` を使わないでください。通常のユーザーで実行してください。 |

### AI モデル

| 問題 | 解決策 |
|------|--------|
| Ollama 接続が拒否される | 別のターミナルで `ollama serve` が実行中か確認してください |
| `LLM Provider NOT provided` | プロバイダー接頭辞を使用: `gpt-4o` ではなく `openai/gpt-4o` |
| 遅い、またはタイムアウト | より小さいモデル（`qwen3:8b`）を使用するか、Settings でタイムアウトを延長 |

### 実験

| 問題 | 解決策 |
|------|--------|
| すべてのノードが失敗した | Tree ビューを開き、失敗したノードをクリックして Trace タブを確認 |
| 結果が表示されない | Monitor ページを確認 — 実験がまだ実行中の可能性があります |
| 実行が中断された | Experiments ページで該当の実行を見つけ、Resume をクリック |

### 論文生成

| 問題 | 解決策 |
|------|--------|
| PDF が生成されない | LaTeX をインストール: `conda install -c conda-forge texlive-core` |
| `No paper text available` | インストール: `pip install pymupdf pdfminer.six` |

---

## クイックスタートレシピ

```bash
# 1. インストール
git clone https://github.com/kotama7/ARI.git && cd ARI && bash setup.sh

# 2. AI のセットアップ（無料、ローカル）
ollama pull qwen3:8b && ollama serve &
export ARI_BACKEND=ollama ARI_MODEL=qwen3:8b

# 3. ダッシュボードの起動
ari viz ./checkpoints/ --port 8765
# http://localhost:8765 を開いて、ウィザードで実験を作成しましょう！
```

---

## 次のステップ

- **CLI の使い方:** コマンドライン操作については [CLI リファレンス](cli_reference.md) を参照
- **実験ファイル:** 高度な記法については [実験ファイルの書き方](experiment_file.md) を参照
- **HPC クラスター:** SLURM の設定については [HPC セットアップガイド](hpc_setup.md) を参照
- **ARI の拡張:** 新しいスキルの追加については [拡張ガイド](extension_guide.md) を参照
