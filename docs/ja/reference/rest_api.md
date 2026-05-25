---
sources:
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_experiment.py
    role: implementation
last_verified: 2026-05-25
---

# REST API リファレンス

viz ダッシュボードサーバ（`ari viz` → `ari-core/ari/viz/server.py`）は
バンドルされた Web UI から使用され、外部統合からもアクセス可能な
JSON HTTP API を公開しています。エンドポイントは `viz/routes.py` によって
ドメインごとのハンドラモジュール（Phase 3B で分割された `viz/api_*.py`、
`viz/checkpoint_api.py`、`viz/file_api.py` など）にディスパッチされます。

すべてのエンドポイントはデフォルトで認証なしです — `ari viz` は
`127.0.0.1` にバインドし、ローカルユーザ向けに設計されています。
外部に公開する場合は nginx / oauth2-proxy でラップしてください。

## 規約

- ベース URL: `http://127.0.0.1:<port>`（デフォルトポートは `ari viz` で設定）。
- 特記がない限り、レスポンスボディはすべて JSON。
- エラーは非 2xx HTTP コードとともに `{"error": "<message>"}` として返されます。
- CORS プリフライト（`OPTIONS`）は `/api/*` に対して許可されています。

## 状態 + ダッシュボード

| メソッド | パス | 用途 | ソース |
|---|---|---|---|
| GET | `/state` | ダッシュボードのライブビューが使用する現在の BFTS 状態スナップショット | `routes.py:211` |
| GET | `/api/gpu-monitor` | GPU 使用率ポーリング | `routes.py:654` |
| GET | `/api/resource-metrics` | CPU / メモリ / ディスクメトリクス | `routes.py:886` |
| GET | `/api/logs` | アクティブな実行の最近のログ行 | `routes.py:903` |

## モデル + スキル

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/models` | LiteLLM + Ollama 経由で利用可能な LLM を探索 |
| GET | `/api/ollama-resources` | モデルに必要なメモリ / ディスク |
| GET | `/api/ollama/<...>` | ローカル Ollama デーモンへのプロキシ |
| GET | `/api/skills` | 登録済みスキルとそのツール数を列挙 |
| GET | `/api/skill/<skill_name>` | スキルごとのメタデータ（ツール一覧、環境変数） |
| GET | `/api/tools` | 全スキルを横断した統合ツールカタログ |
| GET | `/api/scheduler/detect` | `local` / `slurm` / `apptainer` 自動検出 |
| GET | `/api/slurm/partitions` | SLURM パーティション一覧 |
| GET | `/api/container/info` | コンテナランタイムのプローブ |
| GET | `/api/container/images` | キャッシュ済み SIF / OCI イメージ |
| POST | `/api/container/pull` | `ARI_CONTAINER_IMAGE` が参照するイメージを取得 / ビルド |

## チェックポイントブラウジング

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/checkpoints` | `ARI_CHECKPOINT_DIR` 親配下のすべてのチェックポイントを一覧 |
| GET | `/api/checkpoint/<id>/summary` | 実行サマリ（目標、ノード数、ステータス、上位メトリクス） |
| GET | `/api/checkpoint/<id>/memory` | Letta メモリの内容 |
| GET | `/api/checkpoint/<id>/memory_access` | メモリ書き込み / 読み取りのテレメトリ |
| GET | `/api/checkpoint/<id>/files` | サイズ + タイプ付きのファイル一覧 |
| GET | `/api/checkpoint/<id>/file?path=...` | 生ファイルコンテンツ（テキストまたは base64） |
| GET | `/api/checkpoint/<id>/file/raw` | 同上、代替ルート |
| GET | `/api/checkpoint/<id>/filetree` | 階層ツリービュー |
| GET | `/api/checkpoint/<id>/filecontent` | 複数ファイルの一括読み取り |
| GET | `/api/active-checkpoint` | 現在選択されているチェックポイント |
| POST | `/api/switch-checkpoint` | アクティブなチェックポイントを変更 |
| POST | `/api/delete-checkpoint` | チェックポイントを削除（対応する Letta エージェントも削除） |
| POST | `/api/checkpoint/file/save` | チェックポイント内のファイルをインプレース編集 |
| POST | `/api/checkpoint/file/delete` | チェックポイントからファイルを削除 |
| POST | `/api/checkpoint/compile` | 論文草稿に対して `pdflatex` を実行 |

## 実行ライフサイクル

| メソッド | パス | 用途 |
|---|---|---|
| POST | `/api/launch` | 新しい BFTS 実行を開始（`ari run` をプログラム的に） |
| POST | `/api/run-stage` | 単一のパイプラインステージを実行 |
| POST | `/api/stop` | アクティブな実行を停止 |

## サブ実験 + lineage

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/sub-experiments` | すべてのサブ実験レコード |
| GET | `/api/sub-experiments/<run_id>` | 単一のサブ実験の詳細 |
| POST | `/api/sub-experiments/launch` | 親チェックポイントを継承する子実行を起動 |
| GET | `/api/lineage-decisions/<run_id>` | 停滞ルールが出力した決定（v0.7.0） |

## メモリバックエンド

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/memory/health` | Letta ヘルスプローブ |
| GET | `/api/memory/detect` | 実行中の Letta デプロイパスのインベントリ |
| POST | `/api/memory/start-local` | ローカル Letta サーバを起動 |
| POST | `/api/memory/stop-local` | ローカル Letta サーバを停止 |
| POST | `/api/memory/restart` | ローカル Letta サーバを再起動 |

## 設定 + ワークフロー

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/settings` | settings.json を読み取り |
| POST | `/api/settings` | settings.json に書き込み |
| GET | `/api/profiles` | 保存済みプロファイル一覧 |
| GET | `/api/env-keys` | ARI が認識している環境変数キー（値なし） |
| POST | `/api/env-keys` | 環境変数のキー / 値ペアを `.env` に永続化 |
| GET | `/api/workflow` | アクティブな workflow.yaml |
| GET | `/api/workflow/default` | バンドル済みデフォルト |
| GET | `/api/workflow/flow` | DAG ノード / エッジとして可視化されたワークフロー |
| POST | `/api/workflow` | workflow.yaml を保存 |
| POST | `/api/workflow/flow` | DAG ビューを保存 |
| POST | `/api/workflow/skills` | 有効なスキルを切り替え |
| POST | `/api/workflow/disabled-tools` | スキルごとのツールホワイトリスト / ブラックリスト |

## ウィザード / 設定生成

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/experiment-detail` | ウィザードがパースした experiment.md |
| POST | `/api/config/generate` | ウィザードの回答から `ari.yaml` を生成 |
| POST | `/api/chat-goal` | LLM 補助による目標ナラティブの精錬 |
| POST | `/api/ssh/test` | SSH クラスタのログインをプローブ |

## アップロード + few-shot コーパス

| メソッド | パス | 用途 |
|---|---|---|
| POST | `/api/upload` | アクティブなチェックポイントへのマルチパートアップロード |
| POST | `/api/upload/delete` | アップロードされたファイルを削除 |
| GET | `/api/fewshot/<rubric_id>` | ルーブリックの few-shot 例 |
| POST | `/api/fewshot/<rubric_id>/sync` | 公開コーパスを取得 |
| POST | `/api/fewshot/<rubric_id>/upload` | 例を追加 |
| POST | `/api/fewshot/<rubric_id>/delete` | 例を削除 |
| GET | `/api/rubrics` | 利用可能な査読ルーブリック（`ARI_RUBRIC` で制御） |

## ノードレポート

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/nodes/<...>/report` | ノードごとの `node_report.json` |

## EAR + 公開 (v0.7.0)

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/ear/<run_id>` | 実行の EAR バンドルメタデータ |
| GET | `/api/ear/<run_id>/publish-yaml` | 生成された publish.yaml プレビュー |
| POST | `/api/ear/<run_id>/curate` | キュレートステップを実行 |
| POST | `/api/ear/<run_id>/publish-yaml` | publish.yaml を保存 |
| POST | `/api/ear/clone-verify` | ハッシュでリモートバンドルを検証 |
| GET | `/api/publish/settings` | バックエンド設定 |
| POST | `/api/publish/settings` | バックエンド設定を更新 |
| GET | `/api/publish/<run_id>/preview` | 公開前ペイロードのプレビュー |
| GET | `/api/publish/<run_id>/record` | `publish_record.json` を読み取り |
| POST | `/api/publish/<run_id>/promote` | `staged` → `unlisted` / `public` に昇格 |
| POST | `/api/publish/<run_id>` | 設定済みバックエンドにプッシュ |

## 静的ファイル + フロントエンド

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/static/<path>` | バンドル済み UI アセット |
| GET | `/memory/<path>` | メモリインスペクタ静的ページ |
| GET | `/codefile?path=...` | ソースファイルビューア |

## このリファレンスの更新方法

ルートテーブルは `ari-core/ari/viz/routes.py` のディスパッチチェーンです
— ルートを追加した場合はここにも反映してください。
将来的な改善として、同じ理由でマスタープランが提案している OpenAPI
生成を使ってこのページを自動生成することが考えられます。

## 関連ドキュメント

- `docs/architecture.md` — viz パッケージの概要。
- `ari-core/ari/viz/__init__.py` — 現在のサブモジュールマップを含む
  モジュールレベルの docstring。
