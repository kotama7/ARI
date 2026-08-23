---
sources:
  - path: ari-core/ari/migrations/v05_to_v07
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-core/ari/viz/api_workflow.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/ari/viz/v1/secrets.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_ollama.py
    role: implementation
  - path: ari-core/ari/viz/v1/challenges.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/LaunchPanel.tsx
    role: implementation
  - path: scripts/setup/setup_env.sh
    role: config
last_verified: 2026-08-16
---

# マイグレーションガイド

ARI のチェックポイントフォーマットは 3 回のリリースを経て進化してきました。
このガイドではアップグレードパスを説明します。

| 移行元 | 移行先 | 主な変更点 |
|---|---|---|
| v0.5 | v0.6 | Letta メモリバックエンドが JSONL を置き換え |
| v0.6 | v0.7 | ORS / EAR レジストリ / lineage decisions |
| v0.7 | v0.8 (予定) | リファクタリングされたチェックポイントフォーマット (`ari.public/` 境界) |
| v0.8 | v1.0 (予定) | レガシー互換シムの削除 |

オプトインの `ari_rqgm` 実行モードの有効化は、チェックポイントフォーマットの
マイグレーションでは**ありません**: `simple_bfts` がデフォルトのままであり、
既存のチェックポイントは変更なしに動き続け、切り替えは設定のみ
（`ari.mode` + `rqgm.enabled`）です。
[RQGM 移行ガイド](rqgm_migration.md)と[実行モード](execution_modes.md)を
参照してください。

**GUI リフレッシュ**もチェックポイントフォーマットのマイグレーションではありません
— チェックポイントは書き換えられず、ダウングレードも不要です — が、依存している
かもしれないダッシュボードの挙動は変わります。その変更点は下の
[GUI リフレッシュ（v2 ダッシュボード）](#gui-リフレッシュ-v2-ダッシュボード)に
まとめてあります。

## v0.5 → v0.6

### 変更内容

- **メモリバックエンド。** チェックポイントごとの `memory_store.jsonl` と
  グローバル `$HOME/.ari/global_memory.jsonl` (実験横断) は廃止されました。
  デフォルトバックエンドは Letta になりました (チェックポイントごとのエージェントで、
  アーカイブコレクション `ari_node_*` および `ari_react_*` を使用)。
- **`$HOME/.ari/` の削除。** v0.5.0 でグローバル設定ディレクトリはすでに削除済み。
  v0.6 では新しいレイアウトが唯一の書き込み可能サーフェスになります。
- **ルーブリックシステム。** `ari-skill-paper` が `ARI_RUBRIC` で選択する
  YAML ルーブリックを採用しました。

### 手順

1. **Letta サービスを起動する。** `docs/guides/hpc_setup.md#6-letta-memory-backend-deployment`
   のデプロイパス (Apptainer SIF、docker-compose、または pip) から 1 つ選択します:
2. **必要な環境変数を設定する。**
   ```bash
   export LETTA_BASE_URL=http://127.0.0.1:8283
   export LETTA_EMBEDDING_CONFIG=openai/text-embedding-3-small
   export ARI_MEMORY_BACKEND=letta
   ```
   `LETTA_EMBEDDING_CONFIG` はファイルパスではなく embedding の *handle* で、
   既定値は `letta-default` です。
3. **既存のメモリを移行する。** v0.5 の各チェックポイントで:
   ```bash
   ARI_CHECKPOINT_DIR=/path/to/ckpt ari memory migrate
   ```
   マイグレーターは `memory_store.jsonl` (`--react` を付けると `memory.json`
   も) を読み込み、エントリを content-addressed な v1 レコードとして設定済み
   バックエンドに取り込み、結果を `memory_backup.v1.json.gz` にスナップショット
   保存します。レガシーグローバル JSONL は存在すれば報告されますが、意図的に
   取り込まれません。
4. **レガシー JSONL を削除する。** 取り込んだソースはマイグレーターが
   `<name>.migrated-<ナノ秒>` にリネームするため、手で消す必要があるのは
   グローバルファイルだけです:
   ```bash
   rm $HOME/.ari/global_memory.jsonl   # if it ever existed
   ```
5. **ルーブリックを選択する。** `ari-core/config/reviewer_rubrics/` から
   YAML を選択してエクスポートします:
   ```bash
   export ARI_RUBRIC=neurips
   ```
   以降の論文レビューと BFTS スコアリングが新しい軸を使用します。

### 確認

- `ari memory health` がバックエンドの health 辞書を表示する — `ok: true` に
  加えて `backend` / `latency_ms` / `server_version` と checkpoint の
  `namespace`。
- エージェントループからの `search_memory` 呼び出しが埋め込みランクの結果を返す。
- ダッシュボードの `/api/memory/health` エンドポイントが 200 を返す。

## v0.6 → v0.7

### 変更内容

- **ORS (Object Repository Spec)。** 再現性チェーンが `react_driver` のアドホックな
  複製から `ari-skill-replicate` (ルーブリック生成) と `ari-skill-paper-re`
  (PaperBench SimpleJudge 採点) に移行しました。
- **EAR レジストリ。** EAR バンドルをセルフホスト型 `ari-registry` サーバに公開
  できるようになりました (local-tarball / Zenodo / GitHub release に加えて)。
- **Lineage decisions。** `stagnation_rule` が BFTS の複合スコアを監視します。
  停滞が CONFIRMED になると、ARI はまず **決定論的に** 最も有望な **未使用** の
  次点アイデアへピボットします (`switch_to_idea`)。LLM ジャッジ
  (`continue` / `switch_to_idea` / `fanout` / `terminate`) は、決定論的ピボットが
  使えない場合 (予算枯渇、再帰上限到達、未使用の代替案が残っていない) の
  **フォールバック** としてのみ参照されます。決定は
  `lineage_decisions.jsonl` に追記されます。
- **work_dir ブラックリスト。** 子ノードの `work_dir` は結果ファイル
  (`results.csv`、`slurm-*.out` など) を継承しなくなりました。
  既存のチェックポイントは引き続き動作しますが、継承に依存していた子実行は
  再実行が必要です。

### 手順

1. **ルーブリックディレクトリを設定する。**
   `ari-core/config/reviewer_rubrics/` に使用したいルーブリックがあることを
   確認します。`ARI_RUBRIC` でアクティブなものを選択します。
2. **(任意) `ari registry serve` を起動する。** `ari://` 経由でバンドルを
   公開したい場合のみ必要です。先に `ARI_REGISTRY_DATA` を設定してください。
   クライアント側の設定は `ARI_REGISTRIES_FILE` と `ARI_REGISTRY_TOKEN` です。
3. **結果継承に依存していたサブ実験を再実行する。**
   ブラックリストにより、子ノードが `results.csv` / `slurm-*.out` /
   `node_report.json` をコピーしなくなりました。コード、コンパイル済みバイナリ、
   入力ファイルは引き続き継承されます。
4. **(任意) 再現性フローを組み込む。** 論文が準備できたら実行します:
   ```bash
   ari ear curate <checkpoint>
   ari ear publish <checkpoint> --backend ari-registry
   ari paper <checkpoint>
   ```
   `ari replicate` / `ari paper-re` というサブコマンドは存在しません。ORS の連鎖
   (`ors_generate_rubric` → `ors_audit_rubric` → `ors_seed_sandbox` →
   `ors_build_reproduce` → `ors_run_reproduce` → `ors_grade`) は
   `workflow.yaml` の pipeline stage であり、`ari paper`（および
   `ari run` / `ari resume`）が MCP skill 経由で駆動します。

### 確認

- stagnation rule が初めて発火したときに `lineage_decisions.jsonl` が作成される。
- `ari ear publish` 後に `manifest.lock` と `publish_record.json` が現れる。

## v0.7 → v0.8 (予定)

### 想定される変更

- スキルは `ari.public.*` からのみインポート可能になります。
  `tests/test_public_api_boundary.py` ガードレールはすでに存在します。
  v0.8 では非推奨シムを削除します。
- `ari/migrations/v05_to_v07/` のハウスキーピングヘルパーが `ari run` に
  混在している状態から、専用の CLI サーフェス (`ari migrate ...`) に移動します。

### 事前対応手順

- カスタムスキルで直接 `from ari import <internal>` しているインポートを確認します。
  `python -m ari.dev.public_audit` (計画中) でリストアップできます。
  現状は `grep -rn 'from ari import\|from ari\.' my-skill/src/` で代替できます。
- 内部インポートが見つかった場合は、対応する `ari.public.*` モジュールに
  切り替えます (`docs/reference/public_api.md` を参照)。

## v0.8 → v1.0 (予定)

非推奨化プログラム (`CONTRIBUTING.md::Deprecation process`、
`docs/about/release_policy.md`) では以下を予定しています:

- `DeprecationWarning` を発行中のすべての `$HOME/.ari/...` ファイルシステム
  フォールバックの削除。
- `ari/migrations/v05_to_v07/` の削除 (アップグレード前の移行を強制)。
- レガシー `node_report` 再構築ヘルパーの削除。

v1.0 までに移行していない場合、ARI は本ガイドへのポインタとともに
ハードエラーで起動を拒否します。

## GUI リフレッシュ（v2 ダッシュボード）

ダッシュボードのリフレッシュは、v2 ワークスペース、`/api/v1`、設定コントロール
プレーン、そして堅牢化された HTTP 面を追加します。レガシー画面、レガシーのハッシュ
URL、レガシーの `/api/*` エンドポイントは並行して動作し続けるため、マイグレーションの
大半は不可視です。以下に挙げるのは**利用者から見える挙動変更**の完全な一覧 —
以前は成功していたのに今は拒否されるもの、以前はデータを返していたのに今は
プレースホルダを返すものです。

ここでチェックポイントを書き換えるものは 1 つもありません。新しい成果物
（`resolved_config.json`、`launch_events.jsonl`、`{workspace_root}/gui_store/`）は
すべて追加的であり、古い ARI はそれらを無視するため、ダウングレードにデータ
マイグレーションが必要になることはありません。

### ロールバックレバー一覧

各レバーはサーバー起動時に読まれる環境変数です: 設定して `ari viz` を再起動する
だけで、再ビルドは不要です。いずれも、その変更が閉じたリスクを再び開くものなので、
既定値ではなくインシデント用の道具として扱ってください。段階的カットオーバーと
これらのレバーの撤去計画は[GUI カットオーバーランブック](gui_cutover_runbook.md)に
あります。

| レバー | 復元されるもの |
|---|---|
| `ARI_GUI_BIND='::'` | リフレッシュ前の全インタフェースバインド |
| `ARI_GUI_CORS_ANY=1` | リフレッシュ前の `Access-Control-Allow-Origin: *` |
| `ARI_GUI_CHALLENGES=0` | サーバーチャレンジ無しの破壊的エンドポイント |
| `ARI_GUI_CSP=0` | CSP / nosniff / referrer ヘッダの無いレスポンス |
| `ARI_GUI_AUTH=0` | 未認証のリモートバインド |
| `ARI_GUI_HEALTH=0` | `/health/*` を SPA HTML に、diagnostics を 404 に |
| `ARI_GUI_V2=0` | レガシーシェル（v2 のナビエントリとルートを隠す） |

4 つの変更には env レバーが**ありません** — 復帰手段のない純粋な修正です
（MN-1、MN-2、MN-3、および MN-5 の `/codefile` 側）。これらについてはコミットを
差し戻す以外の選択肢はありません。MN-12（GUI からのモード選択）にもレバーは
ありませんが、必要ありません: その「オフ」状態とは単に既定の選択のままにする
ことであり、それはバイト単位で同一のランを起動します。

### ワークフロー編集にはアクティブなプロジェクトが必要（MN-1）

- **以前** — アクティブなチェックポイントが未選択のとき、`POST /api/workflow`、
  `/api/workflow/flow`、`/api/workflow/skills`、`/api/workflow/disabled-tools` は
  同梱の `ari-core/config/workflow.yaml` を黙って書き換えて「成功」と答え、以降の
  すべての CLI / GUI ランの既定パイプラインを警告なしに変更していました。
- **以後** — アクティブなチェックポイントが無いとき、この 4 つのエンドポイントは
  **400** を返し何も書きません: `{"ok": false, "error": "No active project. Select a
  checkpoint before editing the workflow (the bundled default
  workflow.yaml is read-only from the GUI)."}`。チェックポイントを選択していれば、
  チェックポイントごとの copy-on-write コピーに対して従来どおり編集できます。
  `GET /api/workflow` は変更なしです — フォールバックとして同梱既定値を読むのは
  正当だからです。
- **理由** — GUI の編集が、他のランが継承する出荷済み設定を変更してはなりません。
  この書き込みガードは 4 ハンドラで共有されているため、将来の書き込みエンドポイントも
  自動的に継承します。
- **ロールバック** — なし。先にランを選択（または作成）してください; env レバーも、
  取り消すべきデータマイグレーションもありません。

### シークレットは返らない。auto-fill は readiness へ置き換え（MN-2）

- **以前** — `GET /api/env-keys` は、名前に `API_KEY`、`SECRET`、`TOKEN` を含む
  すべての環境変数の**平文**の値を、その出所ファイルとともに返していました。
  ウィザードの開発者モード「Auto-read」はその値で API キー欄を事前入力していました。
- **以後** — 3 点変わりました:
  1. `GET /api/env-keys` は redact されます。空でない値は `***configured***` になり、
     空の値は `""` のまま、`source` マップは変更なしで、トップレベルの
     `"redacted": true` マーカーによりクライアントが新契約を検出できます。
  2. 新しい `GET /api/v1/secrets/status` は、シークレット名の許可リストについて
     `{name, configured, source_class, last_updated}` のみを返します — レスポンスに
     値のフィールドはそもそも存在しません。
  3. `POST /api/env-keys` は従来どおり書き込みますが、`^[A-Z][A-Z0-9_]{0,63}$` に
     合致しないキー名（あるいは改行 / 制御文字を含むもの）は **400** で拒否されます。
- **理由** — 資格情報を配る HTTP 面は、クライアントが何をしようと資格情報の漏洩です。
  UI が必要としていたのは readiness（設定されているか、どの種類のソースからか）
  だけでした。
- **ロールバック** — なし。「Auto-read」は欄を埋める代わりに
  `configured (source_class)` または `not configured` を表示します; 欄を空のままに
  すれば起動時に `.env` の値が使われます。手でキーを入力することと、Settings ページ
  からキーを保存することは変わりません。

### ワークフローの自動保存は上書きせず衝突を検出（MN-3）

- **以前** — ワークフローエディタは編集の 2 秒後に、ディスク上の内容を読まずに
  POST して自動保存していました。別タブ、別ユーザー、あるいは外部プロセスによる
  変更は黙って破壊されていました。
- **以後** — `GET /api/workflow` が `revision`（配信した `workflow.yaml` バイト列の
  sha256 接頭辞）を返します。4 つの書き込みエンドポイントは任意の `base_revision` を
  受け取り、それが古い場合は **409** と
  `{"ok": false, "error": "workflow changed on disk since you loaded it
  (revision mismatch); reload before saving"}` を返して何も書きません（copy-on-write
  のシードすら書きません）。成功時は新しい `revision` がレスポンスで返ります。
  エディタは保存のたびに `base_revision` を送り、同じ 2 秒周期を保ち、明示的な状態
  チップ — Unsaved changes / Saving / Saved / Conflict — を表示します。衝突時は保存を
  完全に止め、明示的な **Reload** を待ちます。Reload はディスクを読み直し、未保存の
  ローカル編集を破棄します（バナーがそう述べます）。
- **理由** — 他人の編集を破壊しながら成功を報告する保存は、失敗する保存より悪い
  ものです。
- **ロールバック** — GUI についてはなし。`base_revision` を省略する API クライアントは
  従来の last-write-wins の挙動のままなので、ワイヤ上は追加的な変更です。

### 既定でループバックバインドと same-origin CORS（MN-4）

- **以前** — HTTP サーバーとポート + 1 の WebSocket サーバーは**全インタフェース**に
  バインドしていたため、LAN やクラスタネットワーク上の何もかもが認証なしですべての
  エンドポイントへ到達できました。JSON レスポンス、OPTIONS プリフライト、SSE
  ストリーム、手書きのバイナリレスポンス（`/memory/`、`/codefile`、論文 PDF/TeX、
  生ファイル）、ollama プロキシがいずれも `Access-Control-Allow-Origin: *` を返して
  いたので、任意の Web ページがそれらを読めました。
- **以後** — バインドの既定は**ループバックのみ**（`127.0.0.1` と `::1` なので、
  ディストリビューションが `localhost` をどちらのファミリへ解決しても動きます）。
  CORS はリクエストの `Origin` がサーバー自身のオリジンに一致するとき
  （`Host` ヘッダ一致、またはサーバーポート上の `localhost` / `127.0.0.1` /
  `[::1]` 形式）にのみエコーし、`Vary: Origin` を付けます; 一致しないオリジンには
  `Access-Control-Allow-Origin` ヘッダがまったく付かず、そこからのプリフライトは
  素の 204 になります。`/state` と `GET /api/gpu-monitor` は従来どおりヘッダ無しの
  ままです。
- **理由** — 未認証の全インタフェースバインドとワイルドカード CORS ポリシーの
  組み合わせは、クラスタネットワーク全体に対するリモートコントロール面です。
- **ロールバック** — `ARI_GUI_BIND='::'` が旧来のデュアルスタックワイルドカード
  バインドを復元します（IPv4 のみなら `'0.0.0.0'`、単一アドレスも可）;
  `ARI_GUI_CORS_ANY=1` がワイルドカードヘッダを復元します。両方合わせれば旧挙動を
  再現できます。`http://localhost:8765` でのローカル利用、SSH トンネル、Vite 開発
  プロキシにはどちらも不要です。別ホストから `http://<server-ip>:8765` を開くには
  `ARI_GUI_BIND` が必要になりました。

### `/codefile` のパス境界と ollama プロキシの許可リスト（MN-5）

- **以前** — `GET /codefile?path=` は、アクティブなチェックポイント配下にあるか、
  **あるいは**文字列のどこかに `checkpoints` という要素を含むだけの任意の絶対パスを
  配信していたため、`/tmp/fake/checkpoints/x` のような細工されたパス — あるいは木の
  外を指すシンボリックリンク — で任意のファイルが読めました。
  `GET|POST /api/ollama/<path>` は ollama ホストが未設定でも**任意の**パスを暗黙の
  `http://localhost:11434` へ中継しており、ローカル HTTP サービスへの汎用リレーに
  なっていました。
- **以後** — `/codefile` は、解決済みの正準パス（シンボリックリンクを辿った後）が
  アクティブなチェックポイントディレクトリ配下、または解決済みチェックポイント探索
  ベースのいずれか配下にある通常ファイルであるときのみ配信します。`..` セグメントは
  解決前に拒否され、シンボリックリンクによる脱出は接頭辞比較で拒否され、ディレクトリや
  存在しないファイルは従来どおり 404 です; 20 MB の上限、コンテンツタイプ、
  ステータスコードは変更ありません。ollama プロキシは、パスが `/api/tags`、
  `/api/show`、`/api/generate`、`/api/chat`、`/api/ps` のいずれかであり、**かつ**
  ターゲットが明示的に設定されている（設定の `ollama_host` または `OLLAMA_HOST`）か、
  実効 LLM バックエンドが `ollama` であるときのみ転送します — `localhost:11434` の
  既定が今も適用されるのは最後の場合だけです。それ以外は上流への接続を開かずに
  **403** を返します。
- **理由** — 「パスに checkpoints という語が含まれる」は境界ではなく、localhost への
  無制限プロキシは踏み台です。
- **ロールバック** — `/codefile` の修正には設計上ロールバックレバーが**ありません**。
  プロキシについては、サポートされる「ロールバック」はターゲットを設定すること
  （`ollama_host` または `OLLAMA_HOST`）です; 許可リスト外のパスの中継は復元
  できません。既定のチェックポイント配置下の成果物と、ollama バックエンド上の
  ollama プロキシは従来どおり動作します。

### 破壊的操作にはサーバー発行のチャレンジが必要（MN-6）

- **以前** — 確認はクライアント側だけでした。`POST /api/delete-checkpoint` は
  POST されたパスを `rmtree` し、`POST /api/stop` は追跡中の全プロセスを kill し
  （`pkill` を含む）、`action=stop` 付きの `POST /api/gpu-monitor` は直接実行され —
  いずれもブラウザのダイアログ以上のものは背後にありませんでした。GPU モニタの
  `confirmed: true` は API 層でハードコードされていました。
- **以後** — `{action, target}` 付きの `POST /api/v1/challenges`（アクション:
  `delete-checkpoint`、`stop-all`、`gpu-monitor-stop`）が単回使用の許可
  `{challenge_id: "chg-<12hex>", action, target, expires_at, ttl_seconds: 60}` を
  発行します。TTL は単調クロックで測られるので壁時計のジャンプで延長できず、発行 /
  消費 / 拒否はアクティブチェックポイントの `viz_access.jsonl` へ `challenge_*`
  イベントとして記録されます。3 つの破壊的エンドポイントは、ボディが未使用・未期限
  切れで同じアクション**かつ**同じ対象に束縛された `challenge_id` を運ぶときのみ
  実行されます; それ以外は
  `{"ok": false, "error": "confirmation challenge required or invalid"}` を伴う
  **428** であり、破壊的な処理は一切行われません。GUI 上ではこれは不可視で、確認
  ダイアログにサーバーがエコーバックした対象が表示される点と、以前は確認が無かった
  **Stop** が確認を求めるようになった点だけが違います。
- **理由** — 迷い込んだリクエストと `rmtree` の間に立つのがクライアントだけ、という
  状態であってはなりません。
- **ロールバック** — `ARI_GUI_CHALLENGES=0` が 3 つのエンドポイントを直接実行へ
  戻します（チャレンジエンドポイントは残るので 2 段階クライアントは動き続けます）。
  旧エンドポイントを `curl` で呼んでいた自動化は、先にチャレンジを取得するか、この
  変数を設定する必要があります。

### CSP、CDN スクリプトの排除、静的レスポンスの堅牢化（MN-7）

- **以前** — `frontend/index.html` は、npm バンドルに既に入っているコピーに加えて
  `cdn.jsdelivr.net` から d3 を読み込んでおり（`window.d3` は誰も使っていません）、
  SPA の index も `/static/` レスポンスも `Content-Security-Policy`、
  `X-Content-Type-Options`、`Referrer-Policy` を持っていませんでした。ウィザードには
  `dangerouslySetInnerHTML` が 1 箇所残っていました。
- **以後** — CDN の `<script>` は削除され（d3 はバンドル同梱）、SPA の index と
  `/static/` レスポンスは `Content-Security-Policy`（`default-src 'self'`、
  `script-src 'self'`、`style-src 'self' 'unsafe-inline'`、`img-src 'self' data:`、
  `connect-src 'self'` にポート + 1 のツリーストリーム用 `ws://`/`wss://` オリジンを
  加えたもの、`frame-src 'self'`、`frame-ancestors 'none'`）、
  `X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer` を送ります。
  API / JSON レスポンスは影響を受けません。`dangerouslySetInnerHTML` は SPA から
  完全に消えました。
- **理由** — サプライチェーン依存を 1 つ減らし、侵害されたバンドルが到達しうる範囲を
  境界付けるためです。
- **ロールバック** — `ARI_GUI_CSP=0` が 3 つのヘッダの送出を止めます。計画に入れて
  おく価値のある帰結が 2 つあります: ダッシュボードを他サイトの iframe に埋め込む
  ことはできなくなり（`frame-ancestors 'none'`）、WebSocket のポートをリマップする
  リバースプロキシでは WebSocket がブロックされてツリービューがポーリングへ縮退します
  — このトポロジがレバーを使う唯一の正当な理由です。オフラインインストールは
  厳密に有利になります: 失敗しうる CDN 取得がもう残っていません。

### リモートバインドには bearer トークンが必要（MN-8）

- **以前** — リモートバインドを選ぶと、削除・プロセス制御・シークレット書き込みを
  含むすべてのエンドポイントと、ポート + 1 の WebSocket が**認証なし**で晒され
  ました。MN-4 は既定値を直しましたが、資格情報を追加してはいませんでした。
- **以後** — バインドが非ループバックのとき、`/health` および `/health/*` を除く
  すべての HTTP リクエストが `Authorization: Bearer <ARI_GUI_TOKEN>` を運ぶ必要が
  あります。不在または誤ったトークンは `WWW-Authenticate: Bearer` と型付き JSON
  ボディを伴う **401** です; 比較は定数時間です。リモートバインドで
  `ARI_GUI_TOKEN` が未設定の場合、サーバーは起動時にランダムな 32 hex のトークンを
  生成し stderr へ一度だけ出力します — リモートバインドが未認証で起動するコードパス
  は存在しません。`EventSource` と `WebSocket` はヘッダを設定できないため、SSE
  ストリームと WebSocket のハンドシェイクは同じトークンを `token=` クエリパラメータ
  としても受け付けます; アクセスログは `token=` を `***` へ redact するので、
  トークンが `viz_access.jsonl` へ到達することはありません。フロントエンドは
  `localStorage` のキー `ari_gui_token` を読みます。**ループバック既定はバイト単位で
  変更されておらず、未認証のままです。**
- **理由** — 資格情報の無いリモートバインドは、手順が増えただけのリモートシェルです。
- **ロールバック** — `ARI_GUI_AUTH=0` がゲートを無効化します（まっとうな用途は前段に
  認証するリバースプロキシを置く場合です）。リモート利用では、`ARI_GUI_TOKEN` を
  自分で設定するか stderr から生成トークンを回収し、ブラウザで一度
  `localStorage.setItem('ari_gui_token', '<token>')` を実行してください;
  `curl` には `-H 'Authorization: Bearer <token>'` が必要です。Settings UI 上の
  トークン入力欄は今後の課題です。

### ヘルスプローブと有界な diagnostics（MN-9）

- **以前** — `/health/live` と `/health/ready` にハンドラが無く、SPA の HTML へ
  落ちていました。これはプローブには無意味です。diagnostics エンドポイントも無く、
  SSE の購読者数、ウォッチャの生存、追跡プロセス数を外から観測する方法もありません
  でした。
- **以後** — `GET /health/live` は依存チェック無しの定数 `{"status": "ok"}` を返します
  （ハンドラが応答したならプロセスは生きています）。`GET /health/ready` は
  `{"status": "ok"|"degraded", "checks": {http, websocket, watcher, event_bus,
  active_checkpoint}}` を返します; 各チェックは独立に評価され、例外はそのチェックを
  `false` へ縮退させるため、readiness が 500 を返すことはありません — `degraded` は
  正直な 200 です。`GET /api/v1/diagnostics` は有界なスカラのみを返します:
  `sse {subscribers, buffer_len, last_event_id}`、
  `watcher {alive, last_scan_age_s}`、`process {tracked_runs}`（パスではなく件数）、
  `cache: false`（キャッシュサブシステムはまだ存在しません）、加えて
  `schema_version` と `openapi_version`。シークレットもファイルシステムのパスも
  ありません。
- **理由** — 運用者は liveness と readiness を分けて必要とし、漏洩しえないメトリクス
  面を必要とします。
- **ロールバック** — `ARI_GUI_HEALTH=0` が変更前の挙動を復元します（`/health/*` は
  SPA HTML、diagnostics は型付き 404）。通常の GUI 利用はどちらでも影響を受けません;
  React アプリはこれらのエンドポイントを呼びません。認証の非対称性に注意してください:
  `/health/*` は MN-8 のトークンゲートから免除されますが、`/api/v1/diagnostics` は
  免除されません。

### 正準の冪等な起動（MN-10）

- **以前** — 起動は `POST /api/launch` のみを通り、応答*前*に LLM による slug 生成、
  `sinfo` によるスケジューラ問い合わせ、ファイルシステム変更を実行していました;
  ランには一意な同一性がなく（タイムスタンプ + slug なので並行起動が衝突しえました）;
  ダブルクリックは 2 つ目のサブプロセスを起動し; レスポンスに `run_id` はありません
  でした。
- **以後** — 正準のエンドポイントは `{draft_id, display_name?, profile?,
  idempotency_key?}` を取る `POST /api/v1/runs` です:
  - **検証優先** — 未知のドラフトは型付き 404、検証失敗は `details.errors` を伴う
    型付き 400 であり、失敗したリクエストはディスク上を**一切**変更しません;
  - **同一性はサーバーが発行** — `run_id = <UTC YYYYMMDDHHMMSS>_<slug>-<uuid4 6hex>`
    で、slug は表示名またはゴールの最初の行から決定論的に導出されます（受理前に
    LLM 呼び出しもスケジューラ問い合わせもありません）;
  - **実体化してから起動** — `experiment.md`、`workflow.yaml`（同梱既定から
    copy-on-write でシード）、`launch_config.json`、`resolved_config.json`、そして
    `launch_events.jsonl` のライフサイクル
    （`draft → validating → accepted → spawned`、または `failed`）、その後に従来と
    同じ `python3 -m ari.cli run` サブプロセス;
  - **冪等性** — `idempotency_key` が起動*前*に
    `{workspace_root}/gui_store/launches/{key}.json` を create-only で主張するため、
    重複した POST は同じ `run_id` を `idempotent_replay: true` とともに返し、何も
    起動しません;
  - グローバルなアクティブチェックポイントは起動によって切り替えられ**ません**。
  起動固有の拒否が 2 つあります: ゴールの無いドラフトは 400 `missing_goal`、
  `ari.mode` または任意の `rqgm.*` フィールドを含むドラフトは 400 `mode_locked` です
  — GUI からのガバナンス / 実行モードの選択は当時まだ未決の判断でした。
  *（MN-12 により置き換え: 4 つのモード葉は新規ランに対して受理されるように
  なりました; 残る 104 の `rqgm.*` パスは今も `mode_locked` で拒否します。）*
- **理由** — 何かが書かれる前にランは同一性を必要とし、ダブルクリックが実験を
  分岐させてはなりません。
- **ロールバック** — 不要です。`POST /api/launch` は変更されず並行して動作し、新しい
  ファイルはすべて追加的で、データマイグレーションは関与しません。

### Configuration Studio からの起動（MN-11）

- **以前** — 上記の起動プロトコルは API 専用でした。GUI から起動する唯一の方法は
  レガシーウィザードであり、Studio のドラフトは編集専用でした。
- **以後** — `#/studio?draft=<id>` に goal → review → launch のステッパーを持つ起動
  パネルが加わります。**Resolve & validate** はドラフトの `resolve-config` と
  `validate` エンドポイントを呼び、値がデフォルト層由来でないすべての葉について実効
  設定のデフォルトとの差分、ドラフトに帰属する検証エラー、リゾルバの警告、シークレット
  の readiness 行（値は構造的に存在しません）、そしてガバナンスロックの注記を表示
  します。不変のレビュー要約 — 表示名、プロファイル、解決済みの実行モードと
  ペーパーモード（MN-12）、変更フィールド数、設定ダイジェスト、および `run_id` は
  accept 時にサーバーが発行するという明示的な注記 —
  は確認チェックボックスでゲートされ、承認ごとにちょうど 1 つの冪等性キーを発行
  します。**Launch** は `/api/v1/runs` へ POST し、サーバー発行の id を使って
  `#/overview?run=<run_id>` へリダイレクトします（mtime や最新チェックポイントの
  推測はありません）; ダブルクリックや再試行は同じキーを replay するので、起動される
  ランは 1 つだけです。失敗は `missing_goal` や `mode_locked` を含む型付きエラー
  エンベロープとして描画されます。
- **理由** — レビュー段階は運用者がまだ「いいえ」と言える場所なので、ドラフトの意図
  ではなく解決済みの設定を見せる必要があります。
- **ロールバック** — 不要です; このパネルは追加的なフロントエンドのみです。レガシー
  ウィザードは完全に使えるままで、MN-10 のバックエンドはそれと独立しています。

### 実行モードとペーパーモードは新規ランで選択可能（MN-12）

- **以前** — `Execution mode` カテゴリのすべてのフィールドとすべての `rqgm.*`
  パス（現時点で 108 パス）が GUI から締め出されていました: Studio では 1 つの無効化された
  グループ、`POST /api/v1/runs` からは 400 `mode_locked`。`ari_rqgm` や
  `rqgm_archive` を選ぶには `workflow.yaml` の連動する 2 つのキーを手で編集する
  必要がありました。
- **以後** — ちょうど 4 つの葉が、2 つの直交する対の意図として開きます:
  `ari.mode` + `rqgm.enabled` と `paper.mode` + `rqgm.paper.enabled`。1 つの
  Studio コントロールが対の**両方**のキーを書くため、UI で片側だけの対を作ることは
  できません; それ以外の場所では型付き 400 `mode_interlock_mismatch` となり
  （テンプレートとドラフトの create/PATCH、および起動）、マージ後のドキュメント値に
  対して評価されます。既定でない選択は二重に実体化されます — 最小限の
  `ari:`/`rqgm:`/`paper:` ブロックがそのランの `workflow.yaml` コピー（同梱ファイル
  では決してありません）へマージされ、加えて文書化された `ARI_MODE` /
  `ARI_RQGM_ENABLED` / `ARI_PAPER_MODE` / `ARI_RQGM_PAPER_ENABLED` 環境変数が
  設定されます。起動レビューは**解決済み**のモードを表示し、尊重されなかった要求は
  フォールバックのランを黙って開始するのではなく `requested → resolved` として
  リゾルバの警告をそのまま添えて示されます。残る 104 の `rqgm.*` ガバナンス /
  チューニングパラメータは設定ファイル専用のままで — 実効値とともに読み取り専用で
  可視、起動時は依然 400 `mode_locked` — RQGM API 面も読み取り専用のままです。
  **レジュームは影響を受けません**: `{checkpoint}/rqgm_state.json` に永続化された
  モードが今も勝ち — どちらの向きにも勝つため、ランのモードはその生涯を通じて
  固定です — GUI のどの経路もそのファイルを書きません。
- **理由** — GUI は提供されている起動面でありながら、自分が開始しようとしている
  ランの最も重大な性質を述べることができませんでした。一方で一律のロックは
  「どのアルゴリズムが走るか」と「敵対予算がいくらか」を同じ判断として扱って
  いました（ADR-09）。
- **ロールバック** — env レバーはなく、また必要もありません: 既定の選択
  （`simple_bfts` + `linear`）のままにすれば、既定を明示的に選び直した場合も含め、
  バイト単位で同一の起動になります。`ARI_GUI_V2=0` は v2 Studio 全体を取り除き、
  レガシーウィザードは今も既定で起動します。コミットの差し戻しにデータ
  マイグレーションは不要です — 新しい成果物はランごとの `workflow.yaml` コピー内の
  追加的なブロックだけであり、古い ARI はそれを無視します。

## 関連

- [GUI カットオーバーランブック](gui_cutover_runbook.md) — v2 ダッシュボードを既定に
  すること、段階的展開、レガシー撤去の順序。
- [RQGM 移行ガイド](rqgm_migration.md) — オプトインの `ari_rqgm` モードの
  有効化（設定のみ; フォーマット変更なし）。
- `CHANGELOG.md` — リリースごとのノート。
- `ari memory migrate --help` — v0.5 → v0.6 マイグレーターの CLI オプション。
- `docs/guides/troubleshooting.md` — マイグレーション失敗時の対処法。
