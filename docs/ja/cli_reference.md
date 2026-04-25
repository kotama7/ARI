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
| `ari memory ...` | Letta メモリバックエンドを管理 | Settings → Memory (Letta) |

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
ari paper <checkpoint_dir> [--experiment <experiment.md>] [--config <config.yaml>] \
                           [--rubric <rubric_id>] \
                           [--fewshot-mode static|dynamic] \
                           [--num-reviews-ensemble N] \
                           [--num-reflections N]

# 同梱ルーブリック (16 種): neurips (既定、v2 互換)、iclr、icml、cvpr、acl、
#   sc、chi、osdi、stoc、icra、siggraph、nature、usenix_security、
#   journal_generic、workshop、generic_conference。加えて内蔵の `legacy`
#   フォールバック (v0.5 スキーマ) も利用可能。
#   ari-core/config/reviewer_rubrics/ に <id>.yaml を追加するだけで
#   新しい venue に対応できます。
```

**使用例 — v2 互換の既定 (NeurIPS 形式、1-shot、5 reflection):**

```bash
ari paper ./checkpoints/20260328_matrix_opt/
```

**使用例 — Supercomputing (SC) ルーブリックで 5 名アンサンブル + メタ査読:**

```bash
ari paper ./checkpoints/20260328_matrix_opt/ \
          --rubric sc --num-reviews-ensemble 5
```

論文パイプラインは: データ変換、図生成、論文執筆、VLM 図査読、**ルーブリック
駆動の論文査読** (rubric 形式 + reflection + オプションのアンサンブル + Area
Chair メタ査読)、再現性チェック (`ari/agent/react_driver.py` 駆動の ReAct
エージェント) を実行します。

CLI フラグは環境変数でも設定可能: `ARI_RUBRIC`、`ARI_FEWSHOT_MODE`、
`ARI_NUM_REVIEWS_ENSEMBLE`、`ARI_NUM_REFLECTIONS`。

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

## ari memory

v0.6.0 で追加された Letta メモリバックエンド管理用のコマンド群。各
サブコマンドは `--checkpoint <path>` または `ARI_CHECKPOINT_DIR` 環境変数
から対象チェックポイントを解決します。

```bash
ari memory <subcommand> [options]
```

| サブコマンド | 説明 |
|------------|------|
| `health` | バックエンドへ ping、レイテンシ、namespace ハッシュ、サーバーバージョンを表示 |
| `migrate` | v0.5.x の `memory_store.jsonl` (および `--react` 付与時は `memory.json`) を Letta コレクションへ一括取り込み。元ファイルは `*.migrated-<ts>` にリネーム |
| `backup` | Letta 上のメモリを `{ckpt}/memory_backup.jsonl.gz` (gzipped JSONL) にスナップショット保存。パイプライン段の境界とシャットダウン時に自動実行 |
| `restore` | `backup` の逆。`--on-conflict=skip\|overwrite\|merge` (既定 `skip`)。`ari resume` 時に Letta が空なら自動実行 |
| `start-local` | ローカル Letta サーバを起動: `--path=auto\|docker\|singularity\|pip` |
| `stop-local` | docker/singularity/pip Letta を停止 (best-effort) |
| `prune-local` | ローカル Letta の状態 (volumes / venv / `~/.letta`) を削除。`--yes` 必須 |
| `compact-access` | ローテーション済みの `memory_access.<ts>.jsonl` を `memory_access.summary.json` に集約し原ファイルを削除 |

**使用例:**

```bash
# 現在のチェックポイントで Letta 到達性をチェック
ARI_CHECKPOINT_DIR=/path/to/ckpt ari memory health

# v0.5.x チェックポイントをアップグレード
ari memory migrate --checkpoint /path/to/ckpt --react

# ポータブルなアーカイブ
ari memory backup  --checkpoint /path/to/ckpt
rsync -a /path/to/ckpt/ other-host:/home/user/ckpt/
ssh other-host "ari memory restore --checkpoint /home/user/ckpt"

# `ari setup` で Letta が起動しなかった場合
ari memory start-local --path=docker
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
| `ARI_SLURM_CPUS` | SLURM ジョブの CPU 数オーバーライド | (自動検出) |

### 検索・VLM

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ARI_RETRIEVAL_BACKEND` | 論文検索: `semantic_scholar` / `alphaxiv` / `both` | `semantic_scholar` |
| `VLM_MODEL` | 図レビュー用 VLM モデル | `openai/gpt-4o` |
| `ARI_ORCHESTRATOR_PORT` | orchestrator スキルの HTTP ポート | `9890` |

### メモリ (Letta)

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `LETTA_BASE_URL` | Letta サーバエンドポイント | `http://localhost:8283` |
| `LETTA_API_KEY` | Letta Cloud で必須 | -- |
| `LETTA_EMBEDDING_CONFIG` | アーカイバルメモリ用の埋め込みハンドル（チャット LLM は ARI から呼び出さないため固定） | `letta-default` |
| `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA` | `auto` / `pip` / `docker` / `singularity` / `none` | `auto` |
| `ARI_MEMORY_LETTA_TIMEOUT_S` | 呼び出しごとのタイムアウト | `10` |
| `ARI_MEMORY_LETTA_OVERFETCH` | 祖先ポストフィルタ用のオーバーフェッチ K | `200` |
| `ARI_MEMORY_LETTA_DISABLE_SELF_EDIT` | Letta self-edit を無効化 (CoW セーフ) | `true` |
| `ARI_MEMORY_ACCESS_LOG` | `{checkpoint}/memory_access.jsonl` への書き込み | `on` |
| `ARI_MEMORY_ACCESS_LOG_MAX_MB` | ローテーション閾値 | `100` |
| `ARI_MEMORY_AUTO_RESTORE` | `ari resume` 時にバックアップを自動復元 | `true` |
| `ARI_MEMORY_BACKUP_INTERVAL_S` | 実行中の機会的バックアップ (0 = OFF) | `0` |

### 論文査読 (ルーブリック)

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ARI_RUBRIC` | 査読に使う rubric_id (例: `neurips`、`sc`、`nature`、`generic_conference`) | `neurips` |
| `ARI_FEWSHOT_MODE` | `static` (内蔵 examples) / `dynamic` (OpenReview 等から取得) | `static` |
| `ARI_NUM_REVIEWS_ENSEMBLE` | 独立査読者数 (N>1 で Area Chair メタ査読も実行) | `1` |
| `ARI_NUM_REFLECTIONS` | self-reflection ループ回数 | `5` |

### フェーズごとのモデルオーバーライド

| 変数 | フェーズ |
|------|---------|
| `ARI_MODEL_IDEA` | アイデア生成 |
| `ARI_MODEL_BFTS` | BFTS 実験 |
| `ARI_MODEL_PAPER` | 論文執筆 |

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
