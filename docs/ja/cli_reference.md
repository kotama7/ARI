# ARI CLI リファレンス

ARI のコマンドライン操作の完全なリファレンスです。CLI は [Web ダッシュボード](quickstart.md)と同等の機能をターミナルベースのワークフロー向けに提供します。

---

## コマンド一覧

| コマンド | 説明 | ダッシュボード相当 |
|---------|------|-------------------|
| `ari run` | 新しい実験を実行 | New Experiment ウィザード → Launch |
| `ari resume` | 中断された実験を再開 | Experiments ページ → Resume ボタン |
| `ari paper` | 論文のみ生成（実験をスキップ） | `POST /api/run-stage {stage: "paper"}` |
| `ari status` | 実験ツリーとサマリーを表示 | Monitor / Tree ページ |
| `ari viz` | Web ダッシュボードを起動 | -- |
| `ari projects` | 過去のすべての実験を一覧表示 | Experiments ページ |
| `ari show` | 実行結果の詳細を表示 | Results ページ |
| `ari delete` | チェックポイントを削除 | Experiments ページ → Delete ボタン |
| `ari settings` | 設定の表示または変更 | Settings ページ |
| `ari skills-list` | 利用可能なツールを一覧表示 | Settings → MCP Skills |

---

## ari run

実験 Markdown ファイルから新しい実験を実行します。

```bash
ari run <experiment.md> [--config <config.yaml>] [--profile <profile>]
```

| 引数 | 必須 | 説明 |
|------|------|------|
| `experiment.md` | はい | 実験 Markdown ファイルへのパス |
| `--config` | いいえ | カスタム設定 YAML（省略時は自動生成） |
| `--profile` | いいえ | 環境プロファイル: `laptop`、`hpc`、または `cloud` |

**使用例：**

```bash
# 基本的な実行（設定を自動検出）
ari run experiment.md

# 環境プロファイルを指定
ari run experiment.md --profile laptop

# カスタム設定を指定
ari run experiment.md --config ari-core/config/workflow.yaml

# 環境変数でオーバーライド
ARI_MAX_NODES=10 ARI_PARALLEL=2 ari run experiment.md
```

**実行される処理：**

1. ARI がユニークなプロジェクト名を生成（LLM が生成するタイトル）
2. チェックポイントディレクトリを作成: `./checkpoints/<run_id>/`
3. arXiv と Semantic Scholar で関連論文を検索
4. VirSci マルチエージェント議論で仮説を生成
5. Best-First Tree Search（BFTS）で実験を実行
6. LLM ピアレビューで結果を評価
7. 図表と引用を含む LaTeX 論文を執筆
8. 再現性を独立して検証

---

## ari resume

チェックポイントから中断された実験を再開します。

```bash
ari resume <checkpoint_dir> [--config <config.yaml>]
```

**使用例：**

```bash
ari resume ./checkpoints/20260328_matrix_opt/
```

保存されたツリーを読み込み、保留中または失敗したノードを特定し、停止した箇所から再開します。

---

## ari paper

実験を実行せずに論文のみを生成します。実験がすでに完了している場合に便利です。

```bash
ari paper <checkpoint_dir> [--experiment <experiment.md>] [--config <config.yaml>]
```

**使用例：**

```bash
ari paper ./checkpoints/20260328_matrix_opt/
```

BFTS 後のパイプラインを実行します：データ変換、図表生成、論文執筆、レビュー、再現性チェック。

---

## ari status

実験ツリーとサマリー統計を表示します。

```bash
ari status <checkpoint_dir>
```

**使用例：**

```bash
ari status ./checkpoints/20260328_matrix_opt/

# 出力:
# ── Experiment Tree ──
# root (success) score=153736
# ├── improve_1 (success) score=180200
# │   ├── ablation_1 (success) score=120000
# │   └── validation_1 (success) score=178500
# └── draft_2 (failed)
#
# Summary: 4 success, 1 failed, 0 running, 0 pending
```

---

## ari viz

ビジュアル実験管理のための Web ダッシュボードを起動します。

```bash
ari viz <checkpoint_dir> [--port <port>]
```

| 引数 | デフォルト | 説明 |
|------|-----------|------|
| `checkpoint_dir` | （必須） | 監視するチェックポイントディレクトリ |
| `--port` | 8765 | サーバーのポート番号 |

**使用例：**

```bash
# ダッシュボードの起動
ari viz ./checkpoints/ --port 8765

# 特定の実行を監視
ari viz ./checkpoints/20260328_matrix_opt/ --port 9878
```

ブラウザで `http://localhost:<port>` を開いてください。ダッシュボードの使い方は[クイックスタートガイド](quickstart.md)を参照してください。

---

## ari projects

過去のすべての実験を一覧表示します。

```bash
ari projects [--checkpoints <dir>]
```

**使用例：**

```bash
ari projects

# 出力:
# ID                              Nodes  Status    Best Score  Modified
# 20260328_matrix_opt             28     complete  153736      2h ago
# 20260327_sorting_benchmark      12     complete  0.95        1d ago
# 20260326_benchmark_test         5      failed    --          2d ago
```

---

## ari show

特定の実験の詳細な結果を表示します。

```bash
ari show <checkpoint> [--checkpoints-dir <dir>]
```

実験ツリー、レビューレポートの概要、および成果物の一覧を表示します。

---

## ari delete

チェックポイントディレクトリを削除します。

```bash
ari delete <checkpoint> [--yes]
```

| フラグ | 説明 |
|--------|------|
| `-y` / `--yes` | 確認プロンプトをスキップ |

---

## ari settings

ARI の設定を表示または変更します。

```bash
ari settings [--config <config.yaml>] [options]
```

| オプション | 説明 |
|-----------|------|
| `--model <name>` | LLM モデル名を設定 |
| `--api-key <key>` | API キーを設定 |
| `--partition <name>` | SLURM パーティション名を設定 |
| `--cpus <count>` | CPU 数を設定 |
| `--mem <GB>` | メモリを GB 単位で設定 |

**使用例：**

```bash
# 現在の設定を表示
ari settings

# モデルを変更
ari settings --model gpt-4o

# 複数のオプションを設定
ari settings --model qwen3:32b --partition gpu --cpus 64 --mem 128
```

---

## ari skills-list

利用可能なすべての MCP ツールとその説明を一覧表示します。

```bash
ari skills-list [--config <config.yaml>]
```

---

## 環境変数

### コア設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ARI_BACKEND` | LLM バックエンド（`ollama` / `openai` / `anthropic` / `claude`） | `ollama` |
| `ARI_MODEL` | モデル名 | `qwen3:8b` |
| `OPENAI_API_KEY` | OpenAI API キー | -- |
| `ANTHROPIC_API_KEY` | Anthropic API キー | -- |
| `OLLAMA_HOST` | Ollama サーバーの URL | `http://localhost:11434` |
| `LLM_API_BASE` | 汎用 API ベース URL（フォールバック） | -- |

### BFTS 設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ARI_MAX_NODES` | 実験の最大総数 | 50 |
| `ARI_MAX_DEPTH` | ツリーの最大深さ | 5 |
| `ARI_PARALLEL` | 同時実行の実験数 | 4 |
| `ARI_MAX_REACT` | ノードごとの最大 ReAct ステップ数 | 80 |
| `ARI_TIMEOUT_NODE` | ノードごとのタイムアウト（秒） | 7200 |

### HPC 設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ARI_EXECUTOR` | 実行バックエンド（`local` / `slurm` / `pbs` / `lsf`） | `local` |
| `ARI_SLURM_PARTITION` | SLURM パーティション名 | -- |

### フェーズごとのモデルオーバーライド

| 変数 | フェーズ |
|------|---------|
| `ARI_MODEL_IDEA` | アイデア生成 |
| `ARI_MODEL_BFTS` | BFTS 実験 |
| `ARI_MODEL_PAPER` | 論文執筆 |
| `ARI_MODEL_REVIEW` | 論文レビュー |

### .env ファイル

ARI は `.env` ファイルを自動的に読み込みます（以下の順序で確認）：

1. `<checkpoint_dir>/.env`（最優先）
2. `<project_root>/.env`
3. `<project_root>/ari-core/.env`
4. `~/.env`（最低優先）

形式: `KEY=VALUE`（`#` で始まる行は無視されます）。

---

## HPC（SLURM）での実行

```bash
# エグゼキューターを設定
export ARI_EXECUTOR=slurm
export ARI_SLURM_PARTITION=your_partition

# SLURM ジョブとして投入
sbatch << 'EOF'
#!/bin/bash
#SBATCH --job-name=ari
#SBATCH --partition=your_partition
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --time=04:00:00
#SBATCH --output=ari_%j.out

# GPU ノードで Ollama を使用する場合:
ollama serve &
sleep 10

export ARI_BACKEND=ollama
export ARI_MODEL=qwen3:32b

cd /path/to/ARI
ari run /path/to/experiment.md --profile hpc
EOF
```

**重要なルール：**

- 常に絶対パスを使用してください（`~` や相対パスは使わない）
- SLURM スクリプト内で標準出力をリダイレクトしないでください（SLURM が `--output` で自動キャプチャします）
- クラスターで必要とされない限り、`--account` や `-A` フラグを追加しないでください
