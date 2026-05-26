---
sources:
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/cost_tracker.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/backends/letta_backend.py
    role: implementation
last_verified: 2026-05-26
---

# トラブルシューティング

よくある実行時障害とその修正方法です。各セクションに症状 (多くの場合は
正確なエラー文字列)、原因、対処法を記載します。

## 起動時の失敗

### `ARI_CHECKPOINT_DIR is not set`

**原因:** v0.5 以降、すべてのステートファイルはチェックポイントにスコープされるため、
この環境変数は必須です。

**修正:**

```bash
export ARI_CHECKPOINT_DIR=/abs/path/to/checkpoints/$(date +%Y%m%d_%H%M%S)
mkdir -p "$ARI_CHECKPOINT_DIR"
ari run /abs/path/to/experiment.md
```

`sbatch` から起動する場合は、シェル rc ファイルではなくジョブスクリプト内で
設定してください — サブ実験でオーバーライドできるようにするためです。

### `DeprecationWarning: $HOME/.ari/...`

**原因:** レガシーフォールバックパスが参照されています。v1.0 ではハードエラーに
なります。v0.5–v0.8 では警告を出します。

**修正:** 明示的な環境変数を設定してください。対応表:

| レガシーパス | 新しい環境変数 |
|---|---|
| `$HOME/.ari/registries.yaml` | `ARI_REGISTRIES_FILE` |
| `$HOME/.ari/registry-data` | `ARI_REGISTRY_DATA` |
| `$HOME/.ari/letta-pid` | `ARI_LETTA_PIDFILE` |

### `ImportError: cannot import name '<X>' from 'ari'`

**原因:** スキルがフェーズ 4 リファクタリングで移動した ARI 内部に
アクセスしようとしています。

**修正:** インポートを `ari.public.<X>` に切り替えてください
(`docs/reference/public_api.md` を参照)。シンボルがまだ公開されていない場合は、
ユースケースを添えて Issue を報告してください。

## SLURM の問題

### ジョブが `PENDING` のまま

**原因 (可能性の高い順):**

1. パーティションが満杯またはメンテナンス中。
2. 要求した wall-time / CPU 数 / GPU 数がパーティションの上限を超えている。
3. アカウントの残りアロケーションがない。

**診断:**

```bash
sinfo -p $SLURM_PARTITION       # Look at AVAIL / STATE
squeue -u $USER                  # Check NODELIST(REASON) column
sacct -j <jobid> --format=Reason # Sometimes more verbose
```

`Reason` が `Resources` または `Priority` ならキュー待ち。
`PartitionConfig` または `QOSMaxJobsPerUserLimit` ならリクエストが拒否されています。

### ビルドステップで `exit_code=127`

**原因:** ほぼ確実にコンパイラの欠如です。HPC スキルは `gcc` のみを許可しており、
`mpicc` / `icc` / `aocc` はほとんどのクラスタのデフォルト PATH にありません。

**修正:** `mpicc` を `gcc -fopenmp` に置き換えてください (必要であれば
OpenMPI を明示的にリンク)。制約を事前に宣言するために experiment.md の
`Hardware Limits` セクションを更新してください。

### `--account` が拒否される

**原因:** ほとんどのクラスタでは、サイトが Slurm アカウンティングを有効にしていない限り
`#SBATCH --account=` / `-A` ヘッダーを拒否します。

**修正:** ヘッダーを削除してください。ARI の `slurm_submit` はもはや追加しません。
もし見かけた場合は、`experiment.md` の `SLURM Script Template` セクションを
確認してください。

## メモリバックエンド (Letta)

### Letta 呼び出し時に `connection refused`

**原因:** Letta サーバーが起動していないか、`LETTA_BASE_URL` が誤ったエンドポイントを
指しています。

**修正:**

```bash
curl -fsS http://127.0.0.1:8283/healthz   # Should return 200

# If it fails, restart per docs/guides/hpc_setup.md#6
docker compose -f containers/letta/docker-compose.yml up -d
# or
apptainer run containers/letta.sif &
```

ダッシュボードの `/api/memory/health` ルートは同じプローブですので、
UI が "Letta unhealthy" と表示している場合はクラスタで Letta サービスが
起動していません。

### `LETTA_EMBEDDING_CONFIG is required`

**原因:** Letta はアーカイブコレクションを構築するために埋め込みモデル設定が必要です。

**修正:** 埋め込みエンドポイントを記述した JSON ファイルを `LETTA_EMBEDDING_CONFIG`
に指定してください。OpenAI 互換の例:

```json
{
  "embedding_endpoint_type": "openai",
  "embedding_model": "text-embedding-3-small",
  "embedding_dim": 1536,
  "embedding_endpoint": "https://api.openai.com/v1"
}
```

### `archival memory search returned 0 results`

**原因:** データパスの不一致の可能性が高いです。`search_memory` は
埋め込みランクの `passages.search` (`embed_query=True`) を使用します。
`passages.list(search=q)` にフォールバックした場合、SQL の `LIKE` マッチャーは
自然言語の長いクエリに対してサイレントに 0 件を返します。

**修正:** `/api/memory/detect` を呼び出してアクティブなバックエンドを確認してください。
スキルにパッチを当てた場合は、`passages.search` ルートを使用していることを
確認してください (`ari-skill-memory/src/ari_skill_memory/backends/letta_backend.py`
を参照)。

## LLM コスト / クォータ

### `litellm.exceptions.RateLimitError`

**原因:** プロバイダーのレート制限。

**修正:** ARI はすべての LLM 呼び出しを
`$ARI_CHECKPOINT_DIR/cost_log.jsonl` に記録します。1 分あたりの呼び出し率を
確認し、プロバイダーのクォータを超えている場合は `ARI_PARALLEL` を下げるか、
BFTS ジャッジをより安価な / ローカルモデルに移行してください
(`ARI_MODEL_JUDGE=ollama/qwen3:32b`)。

### 予期しないコストの急増

**診断:**

```bash
python - <<'PY'
import json, collections
costs = collections.Counter()
with open(f"{__import__('os').environ['ARI_CHECKPOINT_DIR']}/cost_log.jsonl") as fh:
    for line in fh:
        rec = json.loads(line)
        costs[rec["metadata"].get("skill", "?")] += rec["cost_usd"]
for skill, c in costs.most_common():
    print(f"{c:7.3f}  {skill}")
PY
```

最も費用がかかるのは通常 BFTS ジャッジ (`ari-skill-evaluator`) または
ルーブリックレビュー (`ari-skill-paper`) です。`ARI_MODEL_EVAL` /
`ARI_MODEL_JUDGE` でモデルを制限してください。

## VLM (図 / テーブルレビュー)

### `VLM model returned no caption`

**原因:** VLM がビジョン対応でないか、画像のエンコードに失敗しています。

**修正:**

```bash
# Verify the model.
echo "$VLM_MODEL"   # should be something like openai/gpt-4o, ollama/qwen2.5vl:32b
# Verify the image.
file $ARI_CHECKPOINT_DIR/figures/fig1.png   # should report PNG
```

モデルがテキストのみ (例: `gpt-3.5-turbo`) の場合は、ビジョン対応モデルに
切り替えてください。

## コンテナ / サンドボックス

### `singularity exec: command not found`

**原因:** ホストに Apptainer / Singularity がインストールされていません。

**修正:** インストールするか (Apptainer は Singularity の正式な後継です)、
`ARI_CONTAINER_IMAGE` を解除してホスト実行にフォールバックしてください。

### `RLIMIT_NPROC: resource temporarily unavailable`

**原因:** coding サンドボックスが `ARI_MAX_CHILD_PROCS` (デフォルト 1024) で
fork() を制限しており、子プロセスがその上限を超えました。

**修正:** 問題のコマンドを削減するか (採点プロンプトが曖昧だとエージェントが
フォークボムに陥ることがあります)、`ARI_MAX_CHILD_PROCS` を増やしてください。
デフォルト値は意図的に余裕を持たせているため、上限に達した場合は予算不足ではなく
実際のバグが原因であることがほとんどです。

## ダッシュボード / viz

### `Cannot connect to ari viz`

**診断:** `ari viz` はデフォルトで `127.0.0.1` にバインドします。リモートホストに
SSH 接続している場合は、ポートのフォワーディングが必要です。

**修正:**

```bash
# From your laptop:
ssh -L 8000:127.0.0.1:8000 user@remote-host
# Then on the remote:
ari viz --port 8000
```

### フロントエンドが古いステートを表示する

**原因:** バックエンドの再起動後に WebSocket の再接続が保留中です。

**修正:** ブラウザをリフレッシュしてください。ダッシュボードは接続時に `/state`
を再取得します。

## 次に確認する場所

- `$ARI_CHECKPOINT_DIR/ari.log` — アプリケーションログ。
- `$ARI_CHECKPOINT_DIR/cost_log.jsonl` — LLM コストの履歴。
- `$ARI_CHECKPOINT_DIR/lineage_decisions.jsonl` — 停滞判断の記録 (v0.7+)。
- `docs/reference/file_formats.md` — チェックポイント内の各ファイルの意味。
- `docs/_archive/refactor_audit.md` — 既知のマイグレーション負債。

## 関連

[FAQ](../getting-started/faq.md) · [クイックスタート](../getting-started/quickstart.md) · [PaperBench トラブルシューティング](paperbench/paperbench_troubleshooting.md)
