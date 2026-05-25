---
sources:
  - path: ari-skill-hpc
    role: implementation
  - path: containers
    role: config
last_verified: 2026-05-25
---

# HPC セットアップガイド

このガイドは ARI を SLURM クラスタで動かす方法、Apptainer /
Singularity / Docker 内へのデプロイ、共有 Letta サービスへのメモリ
バックエンド接続を扱います。クラスタ固有の名前（パーティション、
ログインノード、パス）は実環境のものに置き換えてください。

## 1. 環境

ARI は通常の Python アプリです — `setup.sh` で 1 度インストールし、
ログインノードまたは sbatch ラッパから駆動します。任意のクラスタで
必須の env var:

| 変数 | 用途 |
|---|---|
| `ARI_CHECKPOINT_DIR` | アクティブチェックポイントルート（全入出力をスコープ）|
| `ARI_LLM_MODEL` | LiteLLM モデル ID（例 `ollama/qwen3:32b`、`openai/gpt-4o`）|
| `ARI_LLM_API_BASE` | 任意 — LLM エンドポイントを LiteLLM デフォルトから変える場合 |
| `OLLAMA_HOST` / `OLLAMA_MODELS` | LLM がローカル Ollama の場合は必須 |

> v0.5.0 でグローバル `$HOME/.ari/` ディレクトリは廃止されました。
> 全ステートファイルは `ARI_CHECKPOINT_DIR` 配下、または明示的な env
> var に格納されます。env var はシェル rc ではなく **sbatch ラッパ
> 内** で設定してください（サブ実験で上書き可能にするため）。

## 2. 利用可能なパーティション（テンプレート）

| パーティション | ハードウェア | 用途 |
|-----------|----------|------|
| `your_cpu_partition` | CPU ノード | BFTS 探索、ベースラインベンチ |
| `your-gpu-partition` | NVIDIA L40S | エージェントループ用 LLM 推論 |
| `your-h200-partition` | NVIDIA H200 | 大規模モデル推論、論文レビュー |
| `your_gpu_partition` | GPU ノード | GPU バウンドな実験 |

`sbatch` の `--partition=` で選択。ARI のサブジョブは
`SLURM_DEFAULT_PARTITION` を尊重します。

## 3. クラスタでの ARI 実行

### BFTS 実行を投入

```bash
sbatch ~/ARI/scripts/run_ari.sh
```

### モニタリング

```bash
squeue -u $USER
tail -f $ARI_CHECKPOINT_DIR/ari.log
```

### 結果の確認

```bash
# 完了した実行の最良メトリクス
python - <<'PY'
import json, os
r = json.load(open(f"{os.environ['ARI_CHECKPOINT_DIR']}/results.json"))
for nid, n in r["nodes"].items():
    if n.get("has_real_data"):
        print(nid[:12], n["metrics"])
PY
```

## 4. SLURM スクリプトテンプレート

```bash
#!/bin/bash
#SBATCH --job-name=ari-experiment
#SBATCH --partition=your_partition
#SBATCH --nodes=1
#SBATCH --cpus-per-task=64
#SBATCH --time=04:00:00
#SBATCH --output=/abs/path/logs/ari_%j.out
#SBATCH --error=/abs/path/logs/ari_%j.err

# チェックポイントスコープ — 全ステートファイルがここに行く
export ARI_CHECKPOINT_DIR=/abs/path/checkpoints/$(date +%Y%m%d_%H%M%S)

# ローカル LLM (GPU ノードで Ollama) — リモート LLM の場合は本ブロックを省略
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS=/home/youruser/.ollama/models
export OLLAMA_CONTEXT_LENGTH=8192
export OLLAMA_NUM_PARALLEL=2
/home/youruser/local/ollama/bin/ollama serve &
OLLAMA_PID=$!
for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:11434/api/tags > /dev/null 2>&1 && break
  sleep 2
done

# ARI が hpc skill 経由で投入するサブジョブが継承するデフォルト
export SLURM_DEFAULT_PARTITION=your_partition
export SLURM_DEFAULT_WORK_DIR=/path/to/ari/

# 任意: 特定のレビュアールブリックを選択
export ARI_RUBRIC=neurips2025

cd /path/to/ari/ari-core
/home/youruser/miniconda3/bin/ari run /abs/path/to/experiment.md

kill $OLLAMA_PID 2>/dev/null || true
```

## 5. コンテナデプロイ（v0.7+）

ログインノード上で直接ツールを動かせない環境向けに 3 つのレシピを
同梱。どれも等価なので、サイトがサポートするものを選択してください。

### Apptainer / Singularity

`scripts/registry/start_singularity.sh` がレファレンスランチャ。
エージェントループにも同レシピが使えます:

```bash
apptainer build ari.sif containers/ari.def
apptainer exec --bind /scratch:/scratch ari.sif \
    ari run /abs/path/to/experiment.md
```

`ari-skill-coding` と `ari-skill-hpc` は
`ARI_CONTAINER_IMAGE=/path/to/ari.sif` と
`ARI_CONTAINER_MODE=singularity` を尊重し、ユーザコード自体を SIF
でラップします — 再現可能ベンチに有用です。

### docker-compose（単一ホスト）

`scripts/registry/docker-compose.yml` が registry の本番レシピ。
フルスタックの類似物も存在します:

```bash
docker compose -f containers/ari/docker-compose.yml up -d
```

### Pip（開発用、コンテナなし）

```bash
./setup.sh                # virtualenv 作成 + ari-core インストール
ari run experiment.md     # ホスト python を直接使用
```

## 6. Letta メモリバックエンドのデプロイ

`ari-skill-memory` は v0.6+ から Letta バックエンドがデフォルト。
スキルは `LETTA_HOST` / `LETTA_PORT`（既定 `127.0.0.1:8283`）経由で
Letta サービスと通信します。3 つのデプロイパス:

| パス | 選択基準 |
|---|---|
| Apptainer SIF（`containers/letta.sif`）| Docker が使えない HPC |
| docker-compose（`containers/letta/docker-compose.yml`）| 開発機・単一ノード本番 |
| Pip（`pip install letta && letta server`）| スモークテスト。共有クラスタ非推奨 |

デプロイ手段に関わらず必要な env var:

| 変数 | 用途 |
|---|---|
| `LETTA_HOST` / `LETTA_PORT` | Letta API のリッスン先 |
| `LETTA_EMBEDDING_CONFIG` | 埋め込み設定 JSON のパス（必須）|
| `OPENAI_API_KEY` 等 | 埋め込みモデルが要するもの |

各 ARI チェックポイントは独自の Letta エージェントを所有
（コレクション `ari_node_<ckpt_hash>` + `ari_react_<ckpt_hash>`）。
`ari ckpt delete` でチェックポイントを削除すると Letta エージェント
も同時に削除されます — 削除パスは `ari-skill-memory/README.md`
を参照。

## 7. SLURM 重要制約

| ルール | 詳細 |
|------|------|
| コンパイラ | `gcc` のみ使用。`mpicc` / `icc` / `aocc` は多くのクラスタで `exit_code=127` |
| CPU 制限 | `--cpus-per-task` はパーティションのノードあたり CPU 数を尊重 |
| パス展開 | `#SBATCH` 行で `~` を使わない — 常に絶対パス |
| stdout リダイレクト | ジョブスクリプト内で stdout をリダイレクトしない — SLURM が `--output` で取得 |
| アカウントヘッダー | 多くの環境で `--account` / `-A` は拒否 — サイトが要求する場合のみ追加 |
| 出力ファイル名 | スキルが期待するパターンに合わせる（例 `slurm_job_{JOBID}.out`）|

## 8. Ollama モデル推奨

| モデル | 最適な用途 |
|-------|------|
| `qwen3:32b` | デフォルト — ローカルハードウェアで最高のツール呼び出し品質 |
| `qwen3:8b` | 高速、低品質、スモークテスト向け |
| `deepseek-r1:32b` | 推論重視タスク（lineage 決定、論文レビュー）|
| `gpt-oss:20b` / `gpt-oss:120b` | OpenAI 互換代替 |
| `qwen2.5vl:32b` | 視覚タスク（`ari-skill-vlm` の図表レビュー）|

## 関連

- `docs/configuration.md` — ARI が尊重する全 env var
- `docs/architecture.md` — ランタイム・メモリ・レイヤ構造
- `ari-skill-hpc/README.md` — SLURM ツールリファレンス（local + SSH）
- `ari-skill-memory/README.md` — バックエンド選択 + Letta デプロイレシピ
