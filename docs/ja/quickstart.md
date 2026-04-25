# ARI クイックスタートガイド

このガイドでは、ARI のインストール、AI モデルの選択、**Web ダッシュボード**を使った最初の実験の実行方法を順を追って説明します。プログラミングの経験は不要です。

CLI（コマンドライン）での使い方については、[CLI リファレンス](cli_reference.md)を参照してください。

> **インストール前にプレビュー**
>
> - 🎬 **ダッシュボードのデモ動画** — [`movie/ja/ari_dashboard_demo.mp4`](../movie/ja/ari_dashboard_demo.mp4) で Web UI の動作を一通り確認できます。
> - 📄 **サンプル成果物（論文）** — [`sample_paper.pdf`](../sample_paper.pdf) は ARI が実際に生成した論文です。図表・引用・再現性検証レポートまで含まれています。

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

v0.6.0 では、セットアップスクリプトが **[Letta](https://docs.letta.com)** (`ari-skill-memory` のバックエンド) も併せて立ち上げます。Docker → Singularity/Apptainer → pip の順に最適な配置を自動選択します。CI やコンテナビルド時など Letta のブートストラップをスキップしたい場合は `SKIP_LETTA_SETUP=1` を、対話プロンプトを抑制したい場合は `ARI_NONINTERACTIVE=1` を `bash setup.sh` 実行前にエクスポートしてください。

セットアップが完了すると、**「Setup Complete」** と次のステップの案内が表示されます。Letta の疎通確認は後から `ari memory health` で行えます。

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
| **Results** | Overleaf 風 LaTeX エディタ、論文 PDF ビューア、レビューレポート、EAR ブラウザ |
| **New Experiment** | 新しい実験を作成・起動するウィザード |
| **Ideas** | VirSci が生成した研究仮説 |
| **Workflow** | BFTS 後のパイプライン用 React Flow ビジュアル DAG エディタ |
| **Settings** | LLM、API キー、SLURM、コンテナ、VLM、検索バックエンドの設定 |
| **Sub-Experiments** | 再帰的なサブ実験ツリー（orchestrator スキル経由） |

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

**Paper Review (v0.6.0+)** — 生成された論文の査読方法を選択します:

- **Rubric** — 同梱の 16 種類から選択 (`neurips` 既定 / v2 互換、`iclr`、`icml`、`cvpr`、`acl`、`sc`、`osdi`、`usenix_security`、`stoc`、`siggraph`、`chi`、`icra`、`nature`、`journal_generic`、`workshop`、`generic_conference`)。`ari-core/config/reviewer_rubrics/` に独自 YAML を追加すれば任意の venue に対応できます。
- **Few-shot mode** — `static` (同梱例使用) / `dynamic` (Phase 2 OpenReview 取得; 査読クローズドの venue では static にフォールバック)。
- **Reviewer ensemble (N)** — 独立査読者数。N>1 の場合は Area Chair メタ査読も自動で走ります。
- **Reflection rounds** — 査読者ごとの self-reflection 回数 (Nature Ablation 既定 5)。
- **Few-shot examples** — manifest からの自動同期、独自 JSON+PDF サンプルのアップロード、不要な例の削除をウィザードから直接行えます。

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

- **論文の編集** — 内蔵の Overleaf 風 LaTeX エディタで `.tex` / `.bib` を編集、コンパイル、PDF をインラインでプレビュー
- 自動ピアレビューのスコアとフィードバックの確認
- Experiment Artifact Repository (EAR) ブラウザ（コード、データ、再現性メタデータ）
- 再現性検証レポートの確認
- すべての成果物のダウンロード

出力ファイルは `./checkpoints/<run_id>/` に保存されます：

| ファイル | 説明 |
|---------|------|
| `full_paper.tex / .pdf` | 生成された完全な論文 |
| `review_report.json` | ピアレビューのスコアとフィードバック（N>1 のときアンサンブル査読とメタ査読を同梱） |
| `reproducibility_report.json` | 独立した再現性検証 |
| `tree.json` | すべてのメトリクスを含む完全な実験ツリー |
| `science_data.json` | クリーンなデータ（内部用語なし） |
| `figures_manifest.json` | 生成された図表 |
| `ear/` | Experiment Artifact Repository（コード、データ、ログ、再現性メタデータ） |
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

### コンテナランタイム

- コンテナモードを選択：auto、Docker、Singularity、Apptainer、none
- コンテナイメージとプルポリシー（always / on_start / never）を設定
- **Detect Runtime** で利用可能なコンテナランタイムを自動検出

### VLM 図レビュー

- 図品質レビュー用の VLM モデル（デフォルト: `openai/gpt-4o`）を設定
- レビューしきい値と最大反復回数を設定

### 検索バックエンド

- 論文検索バックエンドを選択：Semantic Scholar（デフォルト）、AlphaXiv、または both（並列）

### フェーズごとのモデルオーバーライド

パイプラインのフェーズごとに異なるモデルを使用できます（例: アイデア生成にはより安価なモデル、論文執筆にはより高性能なモデル）。

---

## その他のダッシュボードページ

### Ideas ページ

![Ideas ページ](images/ja/dashboard_ideas.png)

VirSci が生成した研究仮説を、新規性と実現可能性のスコアとともに確認できます。実験設定、研究目標、BFTS ノードの評価も表示されます。

### Workflow エディター

![Workflow ページ](images/ja/dashboard_workflow.png)

BFTS 後のパイプライン用 React Flow ビジュアル DAG エディタ。ノードのドラッグ、エッジの描画、ステージの有効/無効化、スキル割当が可能です。スイムレーンレイアウトで BFTS と Paper のフェーズを分離。変更は `workflow.yaml` として保存されます。

---

## ダッシュボードのアーキテクチャと API

ダッシュボードは Python asyncio HTTP サーバーによって配信される React/TypeScript SPA（Vite でビルド）です。以下の 2 つのコンポーネントで構成されています：

- **HTTP サーバー** (`ari/viz/server.py`): REST API + SSE ログストリーミング（メインポート上）
- **WebSocket サーバー**: リアルタイムのツリー更新（ポート+1、例: ダッシュボードが 8765 の場合は 8766）

### API エンドポイント

すべてのエンドポイントは `http://localhost:<port>/` でアクセスできます。

#### State & Monitoring

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/state` | GET | アプリケーションの完全な状態: 現在のフェーズ（idle/idea/bfts/paper/review）、ノード数、実験設定、コストデータ、LLM モデル情報 |
| `/api/logs` | GET (SSE) | `ari.log` と `cost_trace.jsonl` からのリアルタイムログの Server-Sent Events ストリーム |
| `/memory/<node_id>` | GET | ノードのメモリストアエントリ（ツール呼び出しトレース、メトリクス、親チェーン） |
| `/codefile?path=<path>` | GET | チェックポイントディレクトリ内のファイルを読み取り（チェックポイント範囲内に制限、最大 2MB） |

#### Experiment Management

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/api/launch` | POST | 新しい実験を起動。ボディ: `{experiment_md, profile, model, provider, max_nodes, max_depth, max_react, timeout_min, workers, partition, ...}`。レスポンス: `{ok, pid, checkpoint_path}` |
| `/api/run-stage` | POST | 特定のステージを実行: `{stage: "resume"/"paper"/"review"}` |
| `/api/stop` | POST | 実行中の実験をグレースフルに停止（SIGTERM → SIGKILL フォールバック） |
| `/api/checkpoints` | GET | すべてのチェックポイントディレクトリをステータス、ノード数、レビュースコアとともに一覧表示 |
| `/api/checkpoint/<id>/summary` | GET | 詳細なサマリー: ツリーデータ、レビュー、サイエンスデータ、論文テキスト |
| `/api/checkpoint/<id>/paper.pdf` | GET | 生成された PDF をダウンロード |
| `/api/checkpoint/<id>/paper.tex` | GET | 生成された LaTeX をダウンロード |
| `/api/active-checkpoint` | GET | 現在のアクティブなチェックポイントパス |
| `/api/switch-checkpoint` | POST | アクティブなチェックポイントを切り替え: `{path}` |
| `/api/delete-checkpoint` | POST | チェックポイントと関連ログを削除: `{path}` |
| `/api/upload` | POST | アクティブなチェックポイントにファイルをアップロード（バイナリボディ、`X-Filename` ヘッダー） |

#### Configuration

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/api/settings` | GET | 現在の設定: LLM プロバイダー/モデル、Ollama ホスト、SLURM 設定、MCP スキル |
| `/api/settings` | POST | 設定を `{checkpoint}/settings.json` と `.env` に保存（アクティブなプロジェクトが必要）。ボディ: `{llm_model, llm_provider, ollama_host, slurm_partition, ...}` |
| `/api/env-keys` | GET | `.env` ファイルからのすべての API キーとソース情報 |
| `/api/env-keys` | POST | 単一の API キーを保存: `{key, value}` |
| `/api/profiles` | GET | 利用可能な環境プロファイル（laptop, hpc, cloud） |
| `/api/models` | GET | 利用可能な LLM プロバイダーとモデル |
| `/api/workflow` | GET | パイプラインステージとスキルメタデータを含む完全な workflow.yaml |
| `/api/workflow` | POST | 変更された workflow.yaml を保存: `{path, pipeline}` |
| `/api/skills` | GET | 利用可能な MCP スキルを説明付きで一覧表示 |
| `/api/skill/<name>` | GET | スキルの詳細: README、SKILL.md、server.py ソース |

#### Wizard & Tools

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/api/chat-goal` | POST | 実験目標の精緻化のためのマルチターン LLM チャット: `{messages, context_md}` |
| `/api/config/generate` | POST | 自然言語の目標から experiment.md を生成: `{goal}` |
| `/api/ssh/test` | POST | SSH 接続テスト: `{ssh_host, ssh_port, ssh_user, ssh_key, ssh_path}` |
| `/api/scheduler/detect` | GET | コンピューティング環境を自動検出（SLURM, PBS, LSF, Kubernetes） |
| `/api/slurm/partitions` | GET | 利用可能な SLURM パーティション |
| `/api/ollama-resources` | GET | GPU 情報（nvidia-smi）、利用可能な Ollama モデル |
| `/api/gpu-monitor` | GET/POST | GPU モニターデーモンの開始/停止 |

#### WebSocket

| エンドポイント | 説明 |
|---------------|------|
| `ws://localhost:<port+1>/ws` | リアルタイムのツリー更新をサブスクライブ。メッセージ: `{type: "update", data: tree.json, timestamp}` |

### セキュリティ

- API キーは `.env` ファイルにのみ保存され、`settings.json` には保存されません
- ファイルアクセス（`/codefile`）はチェックポイントディレクトリに制限されています
- 各実験は分離のために独自のプロセスグループで実行されます

---

## CLI による代替操作

ダッシュボードのすべての操作はコマンドラインからも実行できます：

### 実験の実行

```bash
# 基本的な実行（設定を自動検出）
ari run experiment.md

# 環境プロファイルを指定
ari run experiment.md --profile hpc

# カスタム設定を指定
ari run experiment.md --config ari-core/config/workflow.yaml

# 中断された実行を再開
ari resume ./checkpoints/20260328_matrix_opt/

# 論文パイプラインのみ実行（実験は完了済み）
ari paper ./checkpoints/20260328_matrix_opt/
```

### モニタリングと結果

```bash
# ノードツリーとステータスを表示
ari status ./checkpoints/20260328_matrix_opt/

# すべてのプロジェクトを一覧表示
ari projects

# 詳細な結果を表示（ツリー + レビュー）
ari show 20260328_matrix_opt

# 利用可能なツールを一覧表示
ari skills-list
```

### 設定

```bash
# 現在の設定を表示
ari settings

# モデルを変更
ari settings --model openai/gpt-4o

# SLURM オプションを設定
ari settings --partition gpu --cpus 64 --mem 128
```

### 環境変数

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ARI_BACKEND` | LLM バックエンド: `ollama` / `openai` / `anthropic` | `ollama` |
| `ARI_MODEL` | モデル名（例: `qwen3:8b`, `openai/gpt-4o`） | `qwen3:8b` |
| `OPENAI_API_KEY` | OpenAI API キー | -- |
| `ANTHROPIC_API_KEY` | Anthropic API キー | -- |
| `OLLAMA_HOST` | Ollama サーバーの URL | `http://localhost:11434` |
| `ARI_MAX_NODES` | 実験の最大総数 | `50` |
| `ARI_PARALLEL` | 同時実行の実験数 | `4` |
| `ARI_MAX_REACT` | ノードごとの最大 ReAct ステップ数 | `80` |
| `ARI_TIMEOUT_NODE` | ノードごとのタイムアウト（秒） | `7200` |

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
