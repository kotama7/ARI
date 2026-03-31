# HPC セットアップガイド

## 環境

- **クラスター**: お使いの HPC クラスター（`your-cluster-login-node`）
- **SSH エイリアス**: `ssh your-cluster`
- **Python**: `~/miniconda3/bin/python3` (3.13)
- **Ollama**: `~/local/ollama/bin/ollama`
- **ARI ルート**: `~/ARI/`

## 利用可能なパーティション

| パーティション | ハードウェア | 最大 CPU 数 | 用途 |
|-----------|----------|----------|----------|
| `your_cpu_partition` | CPU ノード | 可変 | CPU 実験 |
| `your-gpu-partition` | NVIDIA L40S GPU | -- | LLM 推論、GPU 実験 |
| `your-h200-partition` | NVIDIA H200 GPU | -- | 大規模モデル推論 |
| `your_gpu_partition` | GPU ノード | -- | GPU 実験 |

## HPC での ARI 実行

### BFTS 実行の投入

```bash
sbatch ~/ARI/logs/your_job_script.sh
```

### モニタリング

```bash
squeue -u $USER
tail -f ~/ARI/logs/ari_run_<JOBID>.out
```

### 結果の確認

```bash
# 完了した実行からの最良スコア
python3 -c "
import json
r = json.load(open('~/ARI/logs/ckpt_<run_id>/results.json'))
for nid, n in r['nodes'].items():
    if n.get('has_real_data'):
        print(nid[:12], n['metrics'])
"
```

## ARI 用 SLURM スクリプトテンプレート

```bash
#!/bin/bash
#SBATCH --job-name=ari-experiment
#SBATCH --partition=your_partition
#SBATCH --nodes=1
#SBATCH --cpus-per-task=64
#SBATCH --time=04:00:00
#SBATCH --output=/abs/path/logs/ari_%j.out
#SBATCH --error=/abs/path/logs/ari_%j.err

# Ollama の起動
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

# サブジョブ用 SLURM デフォルトの設定
export SLURM_DEFAULT_PARTITION=your_partition
export SLURM_DEFAULT_WORK_DIR=/path/to/ari/

# ARI の実行
cd /path/to/ari/ari-core
/home/youruser/miniconda3/bin/ari run \
    /abs/path/to/experiment.md \
    --config /tmp/ari_config.yaml

kill $OLLAMA_PID 2>/dev/null || true
```

## 重要な制約

| ルール | 詳細 |
|------|--------|
| コンパイラ | デフォルトの compiler のみ使用 |
| CPU 制限 | `--cpus-per-task` をパーティション制限内に設定 |
| パス展開 | SBATCH スクリプト内で `~` を使用しない — 常に絶対パスを使用 |
| stdout リダイレクト | ジョブスクリプト内で stdout をリダイレクトしない — SLURM が `--output` で取得 |
| アカウントヘッダー | `--account` と `-A` はこのクラスターでは無効 — 絶対に追加しない |
| 出力ファイル名 | パターンに従う: `slurm_job_{JOBID}.out` |

## 利用可能な Ollama モデル

| モデル | 最適な用途 |
|-------|---------|
| `qwen3:32b` | デフォルト — 最高のツール呼び出し品質 |
| `qwen3:8b` | 高速、低品質 |
| `deepseek-r1:32b` | 推論重視のタスク |
| `gpt-oss:20b` / `gpt-oss:120b` | OpenAI 互換の代替 |
| `qwen2.5vl:32b` | 視覚タスク（図表/テーブル） |
