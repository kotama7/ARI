---
sources:
  - path: ari-skill-hpc
    role: implementation
  - path: containers
    role: config
  - path: scripts/letta
    role: config
  - path: scripts/registry
    role: config
  - path: ari-core/ari/cli/commands.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/pipeline/driver.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/config.py
    role: implementation
last_verified: 2026-08-16
---

# HPC セットアップガイド

このガイドは ARI を SLURM クラスタで動かす方法、ARI のツールを
Apptainer / Singularity / Docker のサンドボックスに対して走らせる方法
（ARI 自体のイメージレシピはリポジトリに存在しません）、共有 Letta
サービスへのメモリバックエンド接続を扱います。クラスタ固有の名前
（パーティション、ログインノード、パス）は実環境のものに置き換えて
ください。

## 1. 環境

ARI は通常の Python アプリです — `setup.sh` で 1 度インストールし、
ログインノードまたは sbatch ラッパから駆動します。任意のクラスタで
必須の env var:

| 変数 | 用途 |
|---|---|
| `ARI_CHECKPOINT_DIR` | アクティブチェックポイントルート（全入出力をスコープ）|
| `ARI_MODEL` | LiteLLM モデル ID（例 `ollama/qwen3:32b`、`openai/gpt-4o`）。`ARI_LLM_MODEL` は別名として尊重されるが、両方あれば `ARI_MODEL` が勝つ |
| `ARI_LLM_API_BASE` | 任意 — LLM エンドポイントを LiteLLM デフォルトから変える場合 |
| `OLLAMA_HOST` / `OLLAMA_MODELS` | LLM がローカル Ollama の場合は必須 |

> v0.5.0 でグローバル `$HOME/.ari/` ディレクトリは *ステート* のルート
> としては廃止されました — 全ステートファイルは `ARI_CHECKPOINT_DIR`
> 配下、または明示的な env var に格納されます。ただし読み取り専用の
> レガシー *設定* フォールバックが 3 つ残っており、ファイルが実在すれば
> 今も発火します: `~/.ari/registries.yaml`、`~/.ari/publish.yaml`、
> `~/.ari/registry-data`。参照された場合はそれぞれ `DeprecationWarning`
> を出すので、checkpoint 配下か対応する env var に移してください。
> 外側の ARI プロセスの env var はシェル rc ではなく **そのラッパ内** で
> 設定してください。canonical な HPC サブジョブはその親環境を継承
> **しません**: 各 `JobRequestV1` がレビュー済みの非秘密変数と module を
> 明示的に宣言します。資格情報はドメイン固有の staged artifact か
> credential provider が必要で、スケジューラが計算ノードで `.env` を
> source することはありません。

## 2. 利用可能なパーティション（テンプレート）

| パーティション | ハードウェア | 用途 |
|-----------|----------|------|
| `your_cpu_partition` | CPU ノード | BFTS 探索、ベースラインベンチ |
| `your-gpu-partition` | NVIDIA L40S | エージェントループ用 LLM 推論 |
| `your-h200-partition` | NVIDIA H200 | 大規模モデル推論、論文レビュー |
| `your_gpu_partition` | GPU ノード | GPU バウンドな実験 |

`sbatch` ラッパの `--partition=` で選択。サブジョブについては hpc skill が
パーティションを 明示的 caller 引数 → `SLURM_DEFAULT_PARTITION` →
`ARI_SLURM_PARTITION` の順で、work dir を 明示的引数 →
`SLURM_DEFAULT_WORK_DIR` → `ARI_WORK_DIR` → cwd の順で解決します。

## 3. クラスタでの ARI 実行

### BFTS 実行を投入

投入用ラッパはリポジトリに同梱されていません — §4 のテンプレートから
自分で書き、それを投入してください:

```bash
sbatch /abs/path/to/your/run_ari.sh
```

### モニタリング

```bash
squeue -u $USER
tail -f $ARI_CHECKPOINT_DIR/ari.log
```

### 結果の確認

checkpoint レベルのツリーは `nodes_tree.json`
（`{"experiment_goal": …, "nodes": [ … ]}` — mapping ではなく **list**）。
`results.json` は checkpoint レベルの要約ではなく、
`{workspace}/experiments/{run_id}/{node_id}/` 配下のノード単位のファイルです。

```bash
# 完了した実行の最良メトリクス
python - <<'PY'
import json, os
r = json.load(open(f"{os.environ['ARI_CHECKPOINT_DIR']}/nodes_tree.json"))
for n in r["nodes"]:
    if n.get("has_real_data"):
        print(n["id"][:12], n["metrics"])
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

# ARI が hpc skill 経由で投入するサブジョブが既定値として参照する変数
export SLURM_DEFAULT_PARTITION=your_partition
export SLURM_DEFAULT_WORK_DIR=/path/to/ari/
export ARI_HPC_LEDGER_PATH=/abs/path/checkpoints/hpc-jobs-v1.json

# 任意: 特定のレビュアールブリックを選択 — 値は
# ari-core/config/reviewer_rubrics/ 配下のファイル名 stem
# (neurips, icml, iclr, cvpr, acl, osdi, nature, generic_conference, …)。
# 既定は neurips。未知の id はエラーにならず、黙って neurips.yaml に
# フォールバックする。
export ARI_RUBRIC=neurips

cd /path/to/ari/ari-core
/home/youruser/miniconda3/bin/ari run /abs/path/to/experiment.md

kill $OLLAMA_PID 2>/dev/null || true
```

### リモートスケジューラ制御

remote モードは、オペレータ既定の SSH config、SSH agent、ユーザ鍵、初回
接続時に提示された host key のいずれも信頼しません。専用の known-hosts
ファイルと資格情報を用意してください:

```bash
export SLURM_MODE=remote
export SLURM_SSH_HOST=login.cluster.example
export SLURM_SSH_USER=ari-submit
export SLURM_SSH_KNOWN_HOSTS=/etc/ari/cluster_known_hosts
export SLURM_SSH_KEY=/run/secrets/ari_cluster_key
export SLURM_SHARED_FILESYSTEM=true
```

host key の不一致、known-hosts エントリの欠落、安全でない鍵ファイルや
symlink の鍵ファイルは、いずれも fail closed になります。型付きの結果収集は
現状、MCP ホストと計算ホストの双方で同一の絶対パスにマウントされた
ファイルシステムを要求します。

## 5. コンテナデプロイ（v0.7+）

**ARI 自体をパッケージするイメージレシピはありません** — `containers/ari.def`
も `containers/ari/docker-compose.yml` も存在しません。`containers/`
ディレクトリが持つのは、ビルドや実行の *サンドボックス* として使うビルド済み
`.sif` イメージ（ツールチェーンイメージ、python イメージ、ツール固有
イメージ）であり、ARI ランタイムではありません。実在するレシピは
`scripts/registry/` の 2 つで、これらがパッケージするのは **registry
サービス** であってエージェントループではありません。

### Apptainer / Singularity

`scripts/registry/start_singularity.sh` は docker/podman を禁止している
クラスタ向けに、registry を SIF（`$ARI_REGISTRY_SIF`、既定
`$HOME/.ari/ari-registry.sif`）内でビルドして起動します。ARI 自身の作業を
サンドボックス化したい場合は、ARI イメージをビルドするのではなく、
スキルにビルド済みイメージを指し示します:

`ari-skill-coding` は短い対話コマンドについて
`ARI_CONTAINER_IMAGE=/abs/path/to/image.sif` と `ARI_CONTAINER_MODE`
（`auto` — 既定 — / `docker` / `singularity` / `apptainer`）を尊重します。
`ari-skill-hpc` は `container_submit` を使い、その `JobRequestV1` が SIF の
厳密な SHA-256 / サイズ pin、型付きの read-only / read-write bind、
clean-environment フラグ、GPU 宣言、リソース、宣言済み出力を運びます。
コンテナ固有の public alias は削除され、全 caller がこの型付き
ライフサイクルを使います。

### docker-compose（単一ホスト）

`scripts/registry/docker-compose.yml` が registry の本番レシピ
（nginx ↔ uvicorn ↔ sqlite）。ARI イメージをビルドするのではなく、
リポジトリを read-only でマウントします:

```bash
cd scripts/registry
ARI_REGISTRY_TOKEN_USER=admin docker compose up -d
```

### Pip（開発用、コンテナなし）

```bash
./setup.sh                # virtualenv 作成 + ari-core インストール
ari run experiment.md     # ホスト python を直接使用
```

## 6. Letta メモリバックエンドのデプロイ

`ari-skill-memory` は v0.6+ から Letta バックエンドがデフォルト。
スキルは `LETTA_BASE_URL`（既定 `http://localhost:8283`）経由で
Letta サービスと通信します。3 つのデプロイパス:

| パス | 選択基準 |
|---|---|
| Apptainer SIF（`scripts/letta/start_singularity.sh`、イメージ `scripts/letta/letta.sif`）| Docker が使えない HPC |
| docker-compose（`scripts/letta/docker-compose.yml` — Letta + pgvector 対応 Postgres）| 開発機・単一ノード本番 |
| Pip（`scripts/letta/start_pip.sh` — 専用 venv + SQLite）| スモークテスト。共有クラスタ非推奨 |

3 つとも `ari memory start-local` / `ari memory stop-local` で駆動します。

デプロイ手段に関わらず必要な env var:

| 変数 | 用途 |
|---|---|
| `LETTA_BASE_URL` | Letta API のベース URL |
| `LETTA_API_KEY` | Letta Cloud 用の資格情報。認証なしのローカルサービスでは省略 |
| `LETTA_EMBEDDING_CONFIG` | 埋め込み設定のセレクタ。既定は `letta-default` |

各 ARI チェックポイントは独自の Letta エージェントを所有
（コレクション `ari_node_<ckpt_hash>` + `ari_react_<ckpt_hash>`）。
`ari delete <checkpoint>`（`ari ckpt` というサブグループは存在しません）で
チェックポイントを削除すると、対応する Letta ネームスペースが先に purge
されます — ただし purge は best-effort で、失敗してもログに残るだけで
ローカルの `rmtree` はそのまま進み、孤児の Letta エージェントが残ります。
それらは `ari memory prune-local` で掃除します。削除パスは
`ari-skill-memory/README.md` を参照。

`ARI_MEMORY_BACKEND` はバックエンドを選択し、受け付ける値は `letta`（既定）
と `in_memory` だけです。`in_memory` は checkpoint 内の
`.ari-test-memory-backend` マーカーファイルを追加で要求するため、本番実行で
選択することはできません。

## 7. SLURM 重要制約

| ルール | 詳細 |
|------|------|
| ツールチェーン | サイトの module / toolchain を `environment.modules` に厳密に宣言する。あるコンパイラがクラスタ間で可搬だと仮定しない |
| CPU/GPU 制限 | 型付き要求はパーティションの上限を尊重しなければならない。スケジューラの拒否はそのまま返され、リソースが黙って書き換えられることはない |
| パス | `work_dir`、入力、出力、イメージ、bind、known-hosts、資格情報は traversal の無い明示的な絶対パスを使う |
| 環境 | canonical なジョブは `sbatch --export=NIL` を使う。親の PATH、virtualenv、API キー、`.env`、シェル rc は継承されない |
| Account/QoS | `account` / `qos` はサイトが要求する場合にのみ付ける。これらは検証される不活性な識別子で、provenance に保持される |
| 出力 | 出力パスは `work_dir` 配下に宣言する。終了時の収集は、存在しない・symlink・サイズ超過・digest ドリフトした artifact を拒否する |
| リトライ | `ARI_HPC_LEDGER_PATH` は永続的な共有ストレージに置く。未設定の場合は `{ARI_CHECKPOINT_DIR}/hpc-jobs-v1.json` → `{ARI_WORK_DIR}/.ari/hpc-jobs-v1.json` → システム一時ディレクトリ配下の uid 別ディレクトリ、の順にフォールバックし、最後のものはノードローカルなのでこのガードを無効化する。不確定な submit は重複させずに意図的にブロックされる |

## 8. Ollama モデル推奨

| モデル | 最適な用途 |
|-------|------|
| `qwen3:32b` | デフォルト — ローカルハードウェアで最高のツール呼び出し品質 |
| `qwen3:8b` | 高速、低品質、スモークテスト向け |
| `deepseek-r1:32b` | 推論重視タスク（lineage 決定、論文レビュー）|
| `gpt-oss:20b` / `gpt-oss:120b` | OpenAI 互換代替 |
| `qwen2.5vl:32b` | 視覚タスク（`ari-skill-vlm` の図表レビュー）|

## 関連

- `docs/reference/configuration.md` — ARI が尊重する全 env var
- `docs/concepts/architecture.md` — ランタイム・メモリ・レイヤ構造
- `ari-skill-hpc/README.md` — SLURM ツールリファレンス（local + SSH）
- `ari-skill-memory/README.md` — バックエンド選択 + Letta デプロイレシピ
