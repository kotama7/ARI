---
sources:
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/cost_tracker.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/backends/letta_backend.py
    role: implementation
last_verified: 2026-08-22
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

**原因:** レガシーフォールバックパスが参照されています。v0.5 以降のすべての
リリースが置き換え先を示す `DeprecationWarning` を出し
(`ari/_deprecation.py`、`removal_version="v1.0"`)、v1.0 でフォールバック自体が
削除されます。

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

**原因:** コマンドが `PATH` にありません。`slurm_submit` の script bridge は
`#SBATCH --export=NIL` で投入したうえで `PATH=/usr/local/bin:/usr/bin:/bin` を
設定するため、到達できるのはベースのシステムツールチェーン (通常は `gcc`) だけです。
サイトが environment module 経由で提供するコンパイラ (`mpicc` / `icc` / `aocc`)
はここに入っていません。

**修正:** そのツールチェーンが入っている module を load してください。bridge は
本体の実行前にノード上で module システム自身の init
(`/etc/profile.d/modules.sh`、`/etc/profile.d/lmod.sh`、
`$MODULESHOME/init/bash`) を source するので、スクリプト内に書いた
`module load` は機能します。ツールに `modules=` を渡した場合は先に
`module --force purge` が入り、module システムが無い環境では `86` で終了します。
それ以外の場合は `mpicc` を `gcc -fopenmp` に置き換え (必要であれば OpenMPI を
明示的にリンク)、experiment.md の `Hardware Limits` セクションに制約を
宣言してください。

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
docker compose -f scripts/letta/docker-compose.yml up -d
# or
scripts/letta/start_singularity.sh
```

ダッシュボードの `/api/memory/health` ルートは同じプローブですので、
UI が "Letta unhealthy" と表示している場合はクラスタで Letta サービスが
起動していません。

### `Letta agent embedding mismatch`

**原因:** `LETTA_EMBEDDING_CONFIG` は設定ファイルのパスではなく embedding の
*handle* であり、しかも Letta はエージェントの `embedding_config` を作成時点で
凍結します。チェックポイントのエージェントが別の handle — 多くはホスト版の
`letta/letta-free` → `embeddings.memgpt.ai` エンドポイント（上流が落ちると空
ボディの 522 を返します）— で作成されていた場合、env var の値によらず凍結済みの
handle が使われ続け、`add_memory` は不透明な 400 で失敗します。

**修正:** handle を設定したうえで、チェックポイントのエージェントを purge し、
次の `add_memory` でその handle により再作成させてください
（`LettaBackend.purge_checkpoint`。既存の archival passages は削除されます）:

```bash
export LETTA_EMBEDDING_CONFIG=openai/text-embedding-3-small
```

未設定の場合は `letta-default` が既定値です。ARI は空値・`letta-default`・
`letta/letta-free` を同じもの（「明示的な選択なし」）として扱うため、不安定な
MemGPT ホスト側エンドポイントでもバックエンドは警告を出すだけです。上記の
ハードエラーは、エージェントが凍結した handle とは*異なる* handle を明示的に
要求した場合にのみ送出されます。`letta-default` がサーバ側で何に展開されるかは
Letta 自身の決定であり、ARI の関与するところではありません。

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
`$ARI_CHECKPOINT_DIR/cost_trace.jsonl` に記録します。1 分あたりの呼び出し率を
確認し、プロバイダーのクォータを超えている場合は `ARI_PARALLEL` を下げるか、
BFTS ジャッジをより安価な / ローカルモデルに移行してください
(`ARI_MODEL_JUDGE=ollama/qwen3:32b`)。

### 予期しないコストの急増

**診断:**

```bash
python - <<'PY'
import json, collections
costs = collections.Counter()
with open(f"{__import__('os').environ['ARI_CHECKPOINT_DIR']}/cost_trace.jsonl") as fh:
    for line in fh:
        rec = json.loads(line)
        costs[rec.get("skill") or "?"] += rec["estimated_cost_usd"]
for skill, c in costs.most_common():
    print(f"{c:7.3f}  {skill}")
PY
```

各行はフラットな `CallRecord` (`timestamp`, `node_id`, `phase`, `skill`,
`model`, `*_tokens`, `estimated_cost_usd`, …) で、ネストした `metadata`
オブジェクトはありません。追加フィールド `epoch` は `ari_rqgm` 実行時のみ
書き込まれるため、デフォルト実行では存在しません。

`ari_rqgm` 実行でも、このフィールドが押されるのは ARI **コア**プロセスから
発行された呼び出しだけです。`RQGMRuntime` はエポック開始時に
`cost_tracker.set_default_metadata(epoch=...)` で設定しますが、この既定値は
設定したプロセス自身のメモリ上にしか存在しません。各 MCP スキルサーバーは
別プロセスであり、その `bootstrap_skill(...)` が登録するのは `skill`
(と場合により `phase`) のみで、エポックをプロセス境界の向こうへ運ぶ環境変数も
ありません。したがってスキルが発行した呼び出しは `epoch` なしで記録されます。
`cost_trace.jsonl` を `epoch` で集計して得られるのはコアプロセスの費用であり、
実行全体の費用ではありません。全体を見るには `skill` で集計してください。
スキル呼び出しをエポックへ正確に帰属させるには MCP 越しの呼び出し単位の
メタデータ配管が必要ですが、ARI はそれを行っていません。

最も費用がかかるのは通常 BFTS ジャッジ (`ari-skill-evaluator`) または
ルーブリックレビュー (`ari-skill-paper`) です。`ARI_MODEL_EVAL` /
`ARI_MODEL_JUDGE` でモデルを制限してください。

### すべての呼び出しが `$0.00` で記録される

**原因:** 価格表 (`ari/configs/model_prices.yaml`) を読み込めていません。
追記行の書式崩れか、スキル venv に PyYAML が無いのが典型です。表が空だと
すべての呼び出しが 0 と見積もられます。

**診断:** `cost_summary.json` がこれを明示します。

```bash
python - <<'PY'
import json, os
s = json.load(open(f"{os.environ['ARI_CHECKPOINT_DIR']}/cost_summary.json"))
print("pricing_table_unavailable:", s["pricing_table_unavailable"])
print("dropped_records:", s["dropped_records"], "/ call_count:", s["call_count"])
PY
```

`pricing_table_unavailable: true` は表の読み込み失敗を意味します
(ローダーも `model_prices table unavailable` を警告出力します)。
`dropped_records` が 0 でない場合、`call_count` は**過小カウント**です
— その件数だけ使用量はあったのに記録が例外で失敗しており、各件は
`cost record dropped` としてログに残ります。

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

**原因:** `ARI_MAX_CHILD_PROCS` が設定されているため、coding サンドボックスが
`RLIMIT_NPROC` で fork() を制限しており、子プロセスがその上限を超えました。
**デフォルトの上限はありません** — 未設定なら `ari.container` も coding skill も
一切の上限を課しません。

**修正:** 問題のコマンドを削減するか (採点プロンプトが曖昧だとエージェントが
フォークボムに陥ることがあります)、`ARI_MAX_CHILD_PROCS` を増やしてください。
`RLIMIT_NPROC` はプロセスツリー単位ではなく real uid 単位で適用される点に注意して
ください。その uid がホスト上のどこかで既に持っている task をすべて数えるため、
小さい値を明示すると、ほかに何もしていないビルドでも `EAGAIN` になります。
多くの場合は設定を解除するのが正解です。

## ダッシュボード / viz

### `Cannot connect to ari viz`

**診断:** `ari viz` はデフォルトで `127.0.0.1` にバインドします。リモートホストに
SSH 接続している場合は、ポートのフォワーディングが必要です。

**修正:**

```bash
# 手元のマシンから — WebSocket は port+1 を使うので両方フォワードします:
ssh -L 8765:127.0.0.1:8765 -L 8766:127.0.0.1:8766 user@remote-host
# リモート側で (checkpoint ディレクトリは必須引数。--port の既定値は 8765):
ari viz /abs/path/to/checkpoints/<run_id>
```

### フロントエンドが古いステートを表示する

**原因:** バックエンドの再起動後に WebSocket の再接続が保留中です。

**修正:** ブラウザをリフレッシュしてください。ダッシュボードは接続時に `/state`
を再取得します。

## 次に確認する場所

- `$ARI_CHECKPOINT_DIR/ari.log` — アプリケーションログ。
- `$ARI_CHECKPOINT_DIR/cost_trace.jsonl` — LLM コストの履歴
  (集計は `cost_summary.json`)。
- `$ARI_CHECKPOINT_DIR/lineage_decisions.jsonl` — 停滞判断の記録 (v0.7+)。
- `docs/reference/file_formats.md` — チェックポイント内の各ファイルの意味。
- `docs/guides/migration.md` — バージョン間のマイグレーション手順
  (v0.5 → v0.6 以降) と GUI リフレッシュのノート。

## 関連

[FAQ](../getting-started/faq.md) · [クイックスタート](../getting-started/quickstart.md) · [PaperBench トラブルシューティング](paperbench/paperbench_troubleshooting.md)
