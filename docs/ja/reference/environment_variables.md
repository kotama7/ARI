---
sources:
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
last_verified: 2026-05-25
---

# 環境変数リファレンス

ARI は約 90 の環境変数を参照します。ここではそれらを一覧で確認できるよう
まとめています。ほとんどは適切なデフォルト値を持っていますが、**Required?** 列は
新規チェックアウト状態では動作しないものを示しています。

`docs/reference/configuration.md` は同じ内容をチュートリアル形式で説明しています。
このページはアルファベット順の逆引きリファレンスです。

> v0.5.0 でグローバルの `$HOME/.ari/` ディレクトリが削除されました。
> このリファレンスで「必須設定」と記載している箇所については、レガシーの
> フォールバックが `DeprecationWarning` を出力し、v1.0 で削除されます。

## コア (`ARI_*`)

### チェックポイント + パス

| 変数 | 用途 | デフォルト | Required? |
|---|---|---|:---:|
| `ARI_CHECKPOINT_DIR` | アクティブなチェックポイントルート | (なし — 必須設定) | ✓ |
| `ARI_WORKSPACE` | 新規実行の親ディレクトリ（orchestrator スキルが使用） | (なし) | ✓ (`ari-skill-orchestrator` 用) |
| `ARI_WORK_DIR` | ノードごとの作業ディレクトリルート（`ari-skill-coding`） | `/tmp/ari_work` | – |
| `ARI_LOG_DIR` | アプリケーションログディレクトリ | `$ARI_CHECKPOINT_DIR` | – |
| `ARI_ROOT` | ARI ソースツールルート（テストで使用） | (自動検出) | – |
| `ARI_SOURCE_FILE` | 入力 experiment.md パスの上書き | (なし) | – |

### LLM モデル選択

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_LLM_MODEL` | デフォルト LiteLLM モデル ID | (なし) |
| `ARI_LLM_API_BASE` | LiteLLM API ベース上書き | LiteLLM デフォルト |
| `ARI_MODEL` | スキル横断フォールバックモデル ID | (`ARI_LLM_MODEL` にフォールスルー) |
| `ARI_MODEL_EVAL` | LLM 評価器のモデル | `ARI_MODEL` にフォールスルー |
| `ARI_MODEL_JUDGE` | BFTS ジャッジのモデル | `ARI_MODEL` にフォールスルー |
| `ARI_MODEL_LINEAGE` | 停滞 / lineage 決定のモデル (v0.7.0) | `ARI_MODEL` にフォールスルー |
| `ARI_MODEL_ROOT_SELECT` | シードアイデアを選ぶモデル | `ARI_MODEL` にフォールスルー |
| `ARI_MODEL_IDEA` | `generate_ideas` のモデル | `ARI_MODEL` にフォールスルー |
| `ARI_MODEL_REPLICATE` | レプリケータ高レベル推論のモデル (v0.7.0) | `ARI_MODEL` にフォールスルー |
| `ARI_MODEL_REPLICATOR` | `ari-skill-paper-re.build_reproduce_sh` が使用するモデル | フォールスルー |
| `ARI_MODEL_RUBRIC_GEN` | `ari-skill-replicate.generate_rubric` のモデル | フォールスルー |
| `ARI_MODEL_RUBRIC_AUDIT` | `ari-skill-replicate.audit_rubric` のモデル | フォールスルー |
| `LLM_MODEL` | スキル横断フォールバック（`ari-skill-transform`、`ari-skill-plot` が使用） | (なし) |
| `LLM_API_BASE` | `LLM_MODEL` 用 API ベース | (なし) |

### Idea スキル — VirSci-live

`generate_ideas` のオプトイン vendor ラップ経路。デフォルト無効では現在の動作
（軽量な再実装ディスカッションループ）を維持します。有効にすると `generate_ideas` は
ライブの Semantic Scholar スナップショット上で VirSci の本物のマルチエージェント機構を
実行します。依存欠落 / 任意のランタイムエラー時は再実装ループにデグレードします。
ディスカッション LLM は `ARI_MODEL_IDEA` に従います。

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_IDEA_VIRSCI_REAL` | 本物の vendor ラップ経路の切り替え（`1`/true）。未設定 ⇒ 現在の再実装動作 | (未設定 / 無効) |
| `ARI_IDEA_VIRSCI_K` | ディスカッションのターン数（vendor `group_max_discuss_iteration`） | `7` |
| `ARI_IDEA_VIRSCI_TEAM_SIZE` | チームメンバー数の上限（vendor `max_teammember`） | `3` |
| `ARI_IDEA_VIRSCI_N_AUTHORS` | `select_coauthors` の著者プールサイズ | `16` |
| `ARI_IDEA_VIRSCI_N_PAPERS` | SPECTER2 検索コーパスサイズ | `800` |
| `ARI_IDEA_VIRSCI_MAX_TEAMS` | `generate_idea` に通すチーム数の上限 | `=n_ideas` |
| `ARI_IDEA_VIRSCI_SPECTER2_MODEL` | ローカルのクエリ埋め込みモデル | `allenai/specter2_base` |

### BFTS 探索

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_MAX_NODES` | BFTS ノードの上限 | (workflow 制御) |
| `ARI_MAX_DEPTH` | ツリー深さの上限 | (workflow 制御) |
| `ARI_MAX_REACT` | ノードごとの ReAct 反復上限 | (workflow 制御) |
| `ARI_PARALLEL` | 並行ノード実行数 | `1` |
| `ARI_TIMEOUT_NODE` | ノードごとのウォールタイム上限（秒） | (なし) |
| `ARI_RECURSION_DEPTH` | ネストされた ARI 実行の現在深さ（自動設定） | (自動) |
| `ARI_MAX_RECURSION_DEPTH` | orchestrator 再帰の上限 | `3` |
| `ARI_PARENT_RUN_ID` | 再帰時の親 run ID（自動設定） | (自動) |
| `ARI_DISABLED_TOOLS_FOR_CHILD` | 子実行で削減するツールセット | (なし) |
| `ARI_REACT_MEMORY_SEARCH_LIMIT` | `search_memory` の `top_k` 上限 | (スキルデフォルト) |

### バックエンド + エグゼキュータ

| 変数 | 用途 |
|---|---|
| `ARI_BACKEND` | エージェントランタイムのバックエンドセレクタ |
| `ARI_EXECUTOR` | エグゼキュータバックエンド（sync / async） |
| `ARI_CONTAINER_IMAGE` | サンドボックス実行用 SIF / OCI イメージ |
| `ARI_CONTAINER_MODE` | `exec` / `shell`（singularity 呼び出しスタイル） |
| `ARI_CONTAINERS_DIR` | コンテナイメージキャッシュルート |
| `ARI_MAX_CHILD_PROCS` | コーディングサンドボックス内の RLIMIT_NPROC 上限（デフォルト 1024） |
| `ARI_LOG_LEVEL` | Python `logging` レベル（`INFO` / `DEBUG` / ...） |

### メモリバックエンド

| 変数 | 用途 |
|---|---|
| `ARI_MEMORY_BACKEND` | `letta`（デフォルト）または `in_memory`（Letta 不要；ローカルスモークテスト用の一時 RAM バックエンド） |
| `ARI_MEMORY_AUTO_RESTORE` | resume 時に `memory_backup.jsonl.gz` から自動復元 |
| `ARI_MEMORY_ACCESS_LOG` | `memory_access.jsonl` へのパス |
| `ARI_CURRENT_NODE_ID` | エージェントループが設定；スキルは読み取るのみで設定しない |
| `ARI_LETTA_VENV` | バンドル済み Letta サーバの仮想環境パス |

### 査読ルーブリック + 論文査読

| 変数 | 用途 |
|---|---|
| `ARI_RUBRIC` | アクティブにする `reviewer_rubrics/<id>.yaml` を選択 |
| `ARI_RUBRIC_DIR` | ルーブリックディレクトリの上書き |
| `ARI_STRICT_DYNAMIC` | `ari-skill-paper` の dynamic 軸生成を強制 |
| `ARI_NUM_REFLECTIONS` | `review_compiled_paper` のリフレクションラウンド数 |
| `ARI_NUM_REVIEWS_ENSEMBLE` | ルーブリック査読のアンサンブルサイズ |
| `ARI_JUDGE_N_RUNS` | `grade_with_simplejudge` の SimpleJudge 再実行数 |

### ルーブリック自動生成 (v0.7.0)

| 変数 | 用途 |
|---|---|
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | `generate_rubric` の目標葉数 |
| `ARI_RUBRIC_GEN_TEMPERATURE` | LLM temperature 上書き |
| `ARI_RUBRIC_GEN_TWO_STAGE` | 二段階スケルトン + サブツリー合成を使用 |
| `ARI_PAPERBENCH_RUBRIC_DIR` | venue 条件付き PaperBench ルーブリックテンプレートの検索ルート上書き（未リリース — `docs/reference/rubric_schema.md#venue-conditioned-templates` 参照） |

### PaperBench 再現性 (v0.7.0)

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_PAPERBENCH_PATH` | バンドル済み `vendor/paperbench/` パスの上書き | `vendor/paperbench/` |
| `ARI_REPLICATOR_TIME_LIMIT_SEC` | `run_reproduce` のウォールタイム上限 | `43200`（12 時間） |
| `ARI_REPLICATOR_ITERATIVE` | 反復型レプリケータエージェントを使用 | – |
| `ARI_REPLICATOR_MAX_STEPS` | 反復型が有効なときの反復上限 | – |

### Orchestrator スキル

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_ORCHESTRATOR_PORT` | MCP サーバポート | `9890` |
| `ARI_ORCHESTRATOR_LOGS` | ログディレクトリ | `$ARI_WORKSPACE/orchestrator_logs` |
| `ARI_ORCHESTRATOR_DRY_RUN` | 実際の `ari run` をスキップ（スモークテスト用） | – |
| `ARI_ORCHESTRATOR_SSE_ONESHOT` | ワンショット SSE レスポンスモード | – |
| `ARI_ORCHESTRATOR_SSE_TIMEOUT` | SSE タイムアウト（秒） | – |

### Transform スキル

| 変数 | 用途 |
|---|---|
| `ARI_TRANSFORM_MEMORY_MAX_CHARS` | 呼び出しごとの合計メモリ予算 |
| `ARI_TRANSFORM_MEMORY_MAX_ENTRIES` | 呼び出しごとのエントリ上限 |

### Web / 検索スキル

| 変数 | 用途 |
|---|---|
| `ARI_RETRIEVAL_BACKEND` | `semantic_scholar` / `arxiv` / `alphaxiv` |

### 公開 + レジストリ + clone

| 変数 | 用途 |
|---|---|
| `ARI_PUBLISH_DRYRUN` | `--dry-run` を強制（CI 安全用、v0.7.0） |
| `ARI_PUBLISH_SETTINGS` | 公開設定 JSON へのパス |
| `ARI_REGISTRY_DATA` | `ari registry serve` 用の sqlite + artifact ルート（必須設定） |
| `ARI_REGISTRY_TOKEN` | `ari clone ari://...` および `ari ear publish --backend ari-registry` 用 bearer token |
| `ARI_REGISTRY_URL` | レジストリエンドポイントの上書き |
| `ARI_REGISTRY_NAME` | 複数登録時のデフォルトレジストリ名 |
| `ARI_REGISTRIES_FILE` | `registries.yaml` の場所を上書き（未指定時はアクティブなチェックポイント配下を参照） |
| `ARI_LOCAL_TARBALL_OUT` | `local-tarball` 公開バックエンドの出力パス |
| `ARI_GH_REPO` | `gh` バックエンド向けの GitHub リポジトリ |
| `ARI_GH_MODE` | `gh` バックエンドの `release` / `repo` モード |
| `ARI_CLONE_HTTP_TIMEOUT` | `ari clone` の HTTP タイムアウト |

### SLURM デフォルト

| 変数 | 用途 |
|---|---|
| `ARI_SLURM_PARTITION` | デフォルトパーティション |
| `ARI_SLURM_CPUS` | デフォルト `--cpus-per-task` |
| `ARI_SLURM_GPUS` | デフォルト `--gres=gpu:N` |
| `ARI_SLURM_MEM_GB` | デフォルトメモリリクエスト |
| `ARI_SLURM_WALLTIME` | デフォルト `--time` |
| `ARI_SLURM_ALLOW_NO_GRES` | `1` ⇒ クラスタに GPU 用 GRES が設定されていない場合、`--gres` / `--gpus-*` フラグを黙って削除（レガシー v0.7.2 の動作）。デフォルト（未設定）⇒ GPU リクエストが黙って CPU で実行されないよう、対処可能なメッセージ付きで `RuntimeError` を発生。 |

### PaperBench 再現フェーズ（Stage 2）

| 変数 | 用途 |
|---|---|
| `ARI_PHASE1_SANDBOX` | `auto` / `local` / `docker` / `apptainer` / `singularity` / `slurm`。`server.run_reproduce` および `bridge.reproduce_submission` が使用するサンドボックスランナーを強制。 |
| `ARI_PHASE1_DOCKER_IMAGE` | `sandbox_kind=docker` で明示的な `container_image` が指定されていない場合のデフォルト docker イメージ。デフォルトは `ubuntu:24.04`。 |
| `ARI_PHASE1_APPTAINER_IMAGE` | `sandbox_kind=apptainer`/`singularity` で明示的な `container_image` が指定されていない場合のデフォルト SIF / docker URI。 |
| `ARI_PHASE1_SINGULARITY_IMAGE` | `ARI_PHASE1_APPTAINER_IMAGE` のレガシーエイリアス。 |
| `ARI_PHASE1_ALLOW_FALLBACK` | `1` ⇒ 要求されたサンドボックスツール（docker デーモン / apptainer / sbatch / パーティション）が欠落している場合、警告のみでホストローカル実行にフォールバック（レガシー v0.7.2 の動作）。デフォルト（未設定）⇒ ユーザの隔離意図が黙って迂回されないよう `RuntimeError` を発生。 |
| `ARI_PAPERBENCH_PATH` | vendor 化された PaperBench ソースツリーのパス上書き（デフォルト: `ari-skill-paper-re/vendor/paperbench/project/paperbench`）。 |
| `ARI_REPLICATOR_TIME_LIMIT_SEC` | 呼び出し元が `0` を渡したときのデフォルト Stage 1 エージェントロールアウト時間予算。 |
| `ARI_REPLICATOR_ITERATIVE` | `1` ⇒ Stage 1 ロールアウトのデフォルトを IterativeAgent バリアントに変更。 |
| `ARI_REPLICATOR_MAX_STEPS` | デフォルト Stage 1 ステップ上限。 |
| `ARI_AGENT_ENV_PATH` | `bridge.rollout_submission` が `agent_env_path` 引数未指定時に自動ロードする vendor スタイルの `agent.env` ファイル（1行1 `KEY=VALUE`）のデフォルトパス。これも空の場合は `~/.ari/agent.env` にフォールバック。Stage 1 エージェントへ論文固有の認証情報（例: `HF_TOKEN`）を渡すために使用。 |
| `HF_TOKEN` | Hugging Face Hub トークン。呼び出しプロセスに設定されている場合、`bridge.rollout_submission` がエージェントの環境に自動で転送（vendor `nano/eval.py:172-179` の well-known-credential パターン）。Stage 1 ロールアウトで `huggingface-cli login` を呼び出す PaperBench 論文では必須。 |
| `ARI_JUDGE_N_RUNS` | ウィザード / 呼び出し元が `0` を渡したときの SimpleJudge 呼び出しのデフォルト `n_runs`。PaperBench 論文 §4.1 のシングルパスデフォルトは 1。 |
| `ARI_MODEL_JUDGE` | デフォルトジャッジモデル ID（LiteLLM ルーティング）。 |
| `ARI_MODEL_REPLICATOR` | デフォルト Stage 1 ロールアウトモデル ID。 |

## SLURM (`SLURM_*`)

| 変数 | 用途 |
|---|---|
| `SLURM_MODE` | `local`（デフォルト）/ `ssh` |
| `SLURM_SSH_HOST` | リモート SLURM モード用 SSH ホスト |
| `SLURM_SSH_USER` | SSH ユーザ（デフォルトは現在のユーザ） |
| `SLURM_SSH_PORT` | SSH ポート（デフォルト `22`） |
| `SLURM_SSH_KEY` | 秘密鍵パス |
| `SLURM_SSH_PASSWORD` | 任意のパスワード（鍵方式を推奨） |
| `SLURM_DEFAULT_PARTITION` | ARI が起動するサブジョブのデフォルトパーティション |
| `SLURM_PARTITION` | ジョブごとのパーティション上書き |
| `SLURM_VALID_PARTITIONS` | カンマ区切りの許可リスト |
| `SLURM_LOG_DIR` | `*.out` / `*.err` の書き込み先 |
| `SLURM_CLUSTER_NAME` | ダッシュボードに表示される名前 |
| `SLURM_JOB_ID` / `SLURM_JOB_NODELIST` / `SLURM_JOB_PARTITION` | ARI がジョブ内で実行される場合に SLURM が設定 |

## Letta (`LETTA_*`)

| 変数 | 用途 |
|---|---|
| `LETTA_BASE_URL` | Letta API ベース（デフォルト `http://127.0.0.1:8283`） |
| `LETTA_API_KEY` | Letta が認証を要求する場合の API キー |
| `LETTA_EMBEDDING_CONFIG` | 埋め込み設定 JSON へのパス（必須） |

## Ollama / OpenAI (`OLLAMA_*` / `OPENAI_*`)

| 変数 | 用途 |
|---|---|
| `OLLAMA_HOST` | Ollama リッスンアドレス（デフォルト `127.0.0.1:11434`） |
| `OLLAMA_BASE_URL` | LiteLLM 側ベース URL |
| `OPENAI_API_KEY` | OpenAI / OpenAI 互換 API キー |

## VLM

| 変数 | 用途 | デフォルト |
|---|---|---|
| `VLM_MODEL` | 図 / 表の査読用ビジョン LLM | `openai/gpt-4o` |

## 関連ドキュメント

- `docs/reference/configuration.md` — 同じ環境変数をユースケース別にまとめたナラティブガイド。
- `ari-core/ari/config.py` — `ARI_*` グループのほとんどを扱う Pydantic 設定モデル。
- 各スキルの `README.md` — そのスキル固有の環境変数。
