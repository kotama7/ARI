---
sources:
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/v1/errors.py
    role: implementation
  - path: ari-core/ari/viz/v1/events.py
    role: implementation
  - path: ari-core/ari/viz/v1/logs.py
    role: implementation
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/viz/v1/openapi.json
    role: schema
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_experiment.py
    role: implementation
  - path: ari-core/ari/viz/checkpoint_api.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/tests/test_gui_state_facade_freeze.py
    role: test
last_verified: 2026-07-30
---

# REST API リファレンス

viz ダッシュボードサーバー（`ari viz` → `ari-core/ari/viz/server.py`）は、
**並走する** 2 つの HTTP 面を公開します:

- **`/api/v1` — 正準のバージョン付き API。** `ari-core/ari/viz/v1/router.py` の
  宣言的ディスパッチ、型付き pydantic DTO、型付きエラーエンベロープ、そして
  コミット済みの OpenAPI 3.1 文書。新機能はすべてここに入ります。
- **レガシーの非バージョン API**（`/state`、`/api/*`）— レガシーのダッシュボード
  ページのためにバイト互換で維持される*凍結ファサード*です。参考のため下に文書化
  しますが、拡張しないでください。

どちらも `viz/routes.py` がディスパッチします; `/api/v1/` の分岐は
`v1/router.py:dispatch()` へ委譲し、それ以外の分岐は従来のハンドラを保ちます。

## 転送の基本

- ベース URL: `http://127.0.0.1:<port>`（既定ポートは `ari viz` が設定）。
- サーバーは既定で**ループバックのみ**（`127.0.0.1` + `::1`）にバインドします;
  `ARI_GUI_BIND` がリモートバインドへのオプトインです。
- CORS は **same-origin のエコーのみ** — リクエストの `Origin` は、サーバー自身の
  オリジンに一致するときにのみエコーされます。`ARI_GUI_CORS_ANY=1` が従来の
  `Access-Control-Allow-Origin: *` を復元します。
- 認証: **ループバックバインドでは無し**; 非ループバックバインドでは `/health*`
  接頭辞を除くすべてのリクエストが `Authorization: Bearer <ARI_GUI_TOKEN>` を
  要求します（[認証](#認証)を参照）。
- 特記がない限り、レスポンスボディはすべて JSON です。
- SPA の index と `/static/*` は `Content-Security-Policy`、
  `X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer` を持ちます
  （`ARI_GUI_CSP=0` で外れます）。API / JSON のレスポンスは意図的に無変更です。

上記すべてを制御する `ARI_GUI_*` 変数は
[環境変数 → GUI サーバー](environment_variables.md#gui-サーバー-ari_gui_)に
一覧があります。

---

## `/api/v1`（正準）

### バージョニングポリシー

| 観点 | 規則 |
|---|---|
| URL バージョン | `/api/v1`。破壊的変更は新しいパス接頭辞を意味し、`v1` の下で黙って変わることはありません。 |
| ペイロードバージョン | すべてのリソース DTO が `schema_version: 1`（`ari/viz/v1/dto.py` の `Literal[1]`）を持つため、消費側はボディだけから契約のリビジョンを検出できます。 |
| 変更ポリシー | **追加のみ**: 新しい任意フィールドはいつでも現れうる; 既存フィールドは `v1` の内側で削除も型変更もされません。クライアントは未知のキーを無視しなければなりません。 |
| 文書バージョン | OpenAPI 文書の `info.version`（現在 `1.0.0`、定数 `OPENAPI_INFO_VERSION`）; `GET /api/v1/diagnostics` が `openapi_version` として報告します。 |
| リゾルババージョン | 設定面は自身の*解決アルゴリズム*を別立てでバージョニングします: `GET /api/v1/config/schema`、`.../resolved-config`、ドラフトの resolve エンドポイントに載る `resolver_version: "legacy-compatible-1"`。 |
| エラーコード | コード語彙は凍結され、追加的にのみ拡張されます（`ari/viz/v1/errors.py` の `ERROR_CODES`）。 |

### 機械可読なソース

`ari-core/ari/viz/v1/openapi.json` がコミット済みの機械可読な契約です。ルート
テーブルと pydantic DTO のスキーマから**決定論的に生成**されます — ソート済み
キー、タイムスタンプなし、コミット SHA なし — ので、差分可能でドリフトが
ガードされます:

```bash
python -m ari.viz.v1.openapi            # verify committed == regenerated (default)
python -m ari.viz.v1.openapi --update   # regenerate ari/viz/v1/openapi.json
```

コミット済み文書がジェネレータからドリフトすると
`ari-core/tests/test_gui_v1_api.py` が失敗します。`openapi.json` を手で編集しては
いけません; `router.py` / `dto.py` を編集して再生成してください。

3 つのルートは v1 ルーターの JSON リクエスト / レスポンス操作ではないため、
意図的に `openapi.json` に**含まれません**: SSE ストリーム
`GET /api/v1/events/stream`（`routes.py` が直接配信）と、`/health/live` /
`/health/ready` プローブ（`/api/v1` 名前空間の外で `ari/viz/health.py` が配信）
です。下のエンドポイント表に記載しています。

### エラーエンベロープ

`/api/v1` のすべての失敗は同じ JSON の形です（`ari/viz/v1/errors.py`）:

```json
{
  "error": {
    "code": "not_found",
    "message": "unknown run: 20260726T101500_matmul",
    "details": null,
    "request_id": "req-4f2a91c7b0de",
    "retryable": false
  }
}
```

| フィールド | 意味 |
|---|---|
| `code` | 下の凍結コードのいずれか。分岐はこれで行い、`message` では決して行わないでください。 |
| `message` | 人間可読・英語・表示しても安全。スタックトレースを含むことはありません。 |
| `details` | 任意の構造化ペイロード（例: 検証では `{"errors": [...]}`、リビジョン衝突では `{"expected": n, "actual": m}`）。未使用時は `null`。 |
| `request_id` | ディスパッチごとに発行される `req-<12 hex>`。同じ id が**成功**レスポンスでもトップレベルの `request_id` としてエコーされるため、UI はバグ報告に引用できます。 |
| `retryable` | 再試行が現実的に成功しうる場合にのみ `true`（現在は `internal`）。 |

凍結されたコード語彙:

| `code` | HTTP | 発生条件 |
|---|:--:|---|
| `not_found` | 404 | 一致するルートが無い、または指定されたラン / プロジェクト / テンプレート / ドラフト / ノード / エポック / シークレットが存在しない。「このランは RQGM ランではない」にも使われます。 |
| `invalid_request` | 400 | 不正な JSON ボディ、オブジェクトでないボディ、不正な `If-Match`、範囲外の `cursor`/`limit`、または拒否された設定パッチ（問題のパスは `details.errors` に載ります）。 |
| `revision_conflict` | 409 | `If-Match` が保存済み文書のリビジョンと一致しない。`details` は `{expected, actual}` を運びます。 |
| `already_exists` | 409 | create-only の `POST` が既存文書に当たった — 現在は既に使われている `template_id` での `POST /api/v1/run-templates` のみ。 |
| `internal` | 500 | ハンドラの未処理例外。`retryable: true`; 例外の型 + メッセージは提示されますが、トレースバックは提示されません。 |

HTTP `401`（bearer トークンの不在 / 不正）と `428`（確認チャレンジの不在）は
v1 のエンベロープビルダの*外側*で生成されます — [認証](#認証)と
[確認チャレンジ](#確認チャレンジ)を参照してください。

### 楽観的並行制御（`If-Match` / リビジョン）

GUI の設定文書（プロジェクト設定、ランテンプレート、ランドラフト）は
`ari/viz/v1/store.py` により、文書ごとの整数 `revision`（`1` から始まり、成功した
書き込みごとに増加）とともに保存されます。このリビジョンが楽観的並行制御の
トークンです:

- すべての文書レスポンスボディが `revision` を持ちます（HTTP の `ETag` ヘッダは
  **ありません** — リビジョンは JSON ボディに載ります）。
- `PATCH` と `DELETE` はヘッダ `If-Match: "<revision>"` を要求します。引用符付きの
  ETag 形式（`"3"`）と裸の整数（`3`）の両方を受け付けます; 弱い検証子
  （`W/"3"`）は受け付けません — リビジョンは厳密です。
- 変更操作で `If-Match` が**不在**なら `400 invalid_request`（どの変更操作かを
  メッセージが名指しできるよう、ハンドラが必須性を強制します）; **不正な値**も
  `400 invalid_request` です。
- **古い**値は `details: {"expected": <yours>, "actual": <stored>}` を伴う
  `409 revision_conflict` です。再 `GET` し、より新しい文書の上に編集を適用し直して
  再試行してください。
- `revision 0` は「この文書はまだ存在してはならない」を意味します — create-only の
  書き込みを内部的に表現する方法です。
- 存在しないプロジェクト設定文書は空の値を持つ `revision: 0` として読まれるため、
  最初の `PATCH` は `If-Match: "0"` を送ります。
- 書き込みはアトミックかつ耐久的（同一ディレクトリの一時ファイル + `fsync` +
  `os.replace`、ファイル `0o600`、ディレクトリ `0o700`）なので、書き込み途中の
  クラッシュでも直前の文書はバイト単位で無傷のまま残ります。

`POST /api/v1/run-templates` は create-only で `If-Match` を取りません: 既存の id は
`409 already_exists` を返します。

### カーソル規約

3 つのコレクションは、追記専用のソースファイルへの**バイトオフセットカーソル**で
ページングされます。これによりファイルが伸びてもページングが安定します:

| エンドポイント | ソース成果物 | カーソルの単位 |
|---|---|---|
| `GET /api/v1/runs/{run_id}/logs` | `{ckpt}/ari.log` | 生のバイトオフセット |
| `GET /api/v1/runs/{run_id}/rqgm/transitions` | `{ckpt}/rqgm_transitions.jsonl` | コミット済みエントリのバイトオフセット |
| `GET /api/v1/runs/{run_id}/rqgm/audit` | `{ckpt}/rqgm_audit.jsonl` | 行のバイトオフセット |

3 つすべてに成り立つ規則:

- **欠落なし、重複なし。** ページはカーソル以降のレコードを選び、`next_cursor` として
  *配信しなかった*最初のバイトオフセットを返します（末尾に達したら `null`）。
  `next_cursor` を辿ることでファイルをちょうど一度だけ歩けます。
- **コミット済みのみの読み取り。** 終端の改行を伴わない末尾行は途切れた追記です:
  決して出力されず、カーソルはその先頭バイトに留まるので、改行が到着してから一度
  だけ配信されます。RQGM の遷移ログについては、対応する commit を持たない
  `epoch_transaction_prepare`（およびそれ以降のすべて）も同様に現在状態へ取り込まれ
  ません。
- **有界な処理。** `limit` の既定はログで 200（最大 1000）、RQGM のページで 20
  （最大 100）です; さらにログリーダはリクエストあたり最大 1 MiB しか走査しないため、
  5 MB のログ全体を読むリクエストは存在しません。
- **フィルタはカーソルを動かしません。** ログの `?grep=`（大文字小文字を無視する
  部分文字列）と監査ページの `?record_type=` / `?epoch=` は、走査したレコードのうち
  *返す*ものを選びます; カーソルは一致しないレコードの上も進むため、リクエストの
  間でフィルタが変わってもページ連鎖は整合したままです。
- **範囲外の値は丸められず拒否されます**: 負や非整数の `cursor`、範囲外の `limit` は
  `400 invalid_request` です。
- RQGM ページの `source_revision` は、パース済みソースファイルのバイト長（途切れた
  末尾を除く）です — 「ログは伸びたか？」を安価に確認できます。

`GET /api/v1/runs/{run_id}/rqgm/score-rewrites` も `cursor`/`limit` を取りますが、
そのカーソルは決定論的に join された書き換えリストへの**整数インデックス**です
（単一ファイルの走査ではなく 2 つのログをまたぐ join だからです）。

### リアルタイム: `GET /api/v1/events/stream`（SSE）

1 本の Server-Sent Events ストリームが**状態ではなく無効化**を運びます:
イベントを受けるとクライアントは名指しされたスナップショットリソースを取り直します。
権威あるデータは常に通常の GET から来ます。

クエリパラメータ: `run_id`（1 ランへのフィルタ）、`topics`（カンマ区切り）、
`last_event_id`（ヘッダを設定できないときの resume カーソル）、`token`
（リモートモードの認証）。

イベントペイロード:

```
id: 42
event: resource.changed
data: {"event_id":"42","run_id":"20260726T101500_matmul","topic":"tree",
       "revision":7,"occurred_at":"2026-07-26T10:20:31Z",
       "kind":"resource.changed",
       "resource":"/api/v1/runs/20260726T101500_matmul/tree","payload":{}}
```

| 観点 | 契約 |
|---|---|
| トピック | 公開語彙は `run` と `tree` に凍結されています（`events.TOPICS`）。`tree` は状態ウォッチャが publish します（レガシー WebSocket のブロードキャストを鏡写しにしたもの）; `run` はチェックポイント切り替え時と v1 起動後に publish されます。 |
| `resource` | 取り直すべき `/api/v1` スナップショット — `tree` には `.../tree`、`run` には `.../summary`（publisher が上書きすることもあります）。 |
| `revision` | `(topic, run_id)` ごとのカウンタなので、クライアントは 1 つのリソースについて無効化を取りこぼしたことを検出できます。 |
| `event_id` | プロセス寿命の単調増加整数。文字列としてシリアライズされ、SSE の `id:` フィールドとして出力されます。 |
| リプレイ | 接続時、サーバーは `Last-Event-ID` より大きい id を持つバッファ済みイベントをリプレイします（ヘッダが優先; `EventSource` がヘッダを設定できないため `?last_event_id=` がフォールバックです）。バッファは 1000 件のリングであり、追い出されたものは単に消えます。イベントが真実源でないからこそこれは安全です: 再接続時の取り直しが欠落を埋めます。 |
| ハートビート | アイドル 15 秒ごとに `: heartbeat` コメントを送り、プロキシに接続を落とさせません。ストリームは `: connected` + `retry: 5000`（ブラウザの再接続遅延）で始まります。 |
| 再接続 | ストリームの窓は 300 秒に有界です; 期限切れ時にサーバーは `: stream-timeout - reconnect` を書いて閉じ、クライアントは `Last-Event-ID` を持って再接続します。クライアント側の切断はストリームを静かに終わらせます。 |

### 認証

信頼モデルは設定ではなく**バインド**が決めます（`ari/viz/auth.py`）:

- **ローカルモード**（既定 — `ARI_GUI_BIND` 未設定でバインドはループバック）:
  認証は一切ありません。`ARI_GUI_TOKEN` がたまたまエクスポートされていても、
  リクエストの形は認証導入前のビルドと変わりません。
- **リモートモード**（`ARI_GUI_BIND` が非ループバックのホスト、ワイルドカードの
  `::` / `0.0.0.0` を含む、を指す）: `/health*` 接頭辞を除くすべての HTTP
  リクエストが `Authorization: Bearer <token>` を送る必要があります。不在 / 誤りは
  型付き JSON ボディと `WWW-Authenticate: Bearer` を伴う `401` です。比較は定数
  時間です。
- リモートバインド時に `ARI_GUI_TOKEN` が未設定なら、サーバーは起動時に 32 hex の
  トークンを**生成**し stderr へ一度だけ出力します — リモートバインドが黙って未認証に
  なることは決してありません。
- **SSE と WebSocket** は同じトークンを `token` **クエリパラメータ**として受け付け
  ます。`EventSource` と WS ハンドシェイクがヘッダを設定できないためです（記録された
  トレードオフ）。アクセスログは `token=` の値を redact するので、トークンが
  `viz_access.jsonl` へ到達することはありません。fetch で消費されるレガシーの
  `/api/logs` ストリームはヘッダを使います。
- Cookie を使わないので CSRF の面はありません。セッション、ログアウト、マルチ
  ユーザーはスコープ外です。
- `ARI_GUI_AUTH=0` はゲートを無効化します（自前で認証を終端する構成、例えば認証を
  行うリバースプロキシのための、文書化された脱出ハッチ）。

### 確認チャレンジ

破壊的なレガシー操作は、`POST /api/v1/challenges` が発行する**サーバー発行の単回
使用チャレンジ**を要求します:

| アクション | 束縛される対象 | 消費される先 |
|---|---|---|
| `delete-checkpoint` | 削除されるチェックポイントのパス | `POST /api/delete-checkpoint` |
| `stop-all` | `"*"` | `POST /api/stop` |
| `gpu-monitor-stop` | `"*"` | `action=stop` 付きの `POST /api/gpu-monitor` |

レスポンスは `{challenge_id: "chg-<12 hex>", action, target, expires_at,
ttl_seconds: 60}` です。破壊的エンドポイントは、ボディの `challenge_id` が未使用・
未期限切れで同じ action + target に束縛されているときにのみ実行されます; それ以外は
凍結ペイロード `{"ok": false, "error": "confirmation challenge required or invalid"}`
を伴う HTTP `428` を返し、何も行いません。TTL は単調クロックで測られ（壁時計の
ジャンプで延長できません）、ストアは有界なインメモリ deque（上限 100）です。
発行 / 消費 / 拒否は監査ログへ記録されます。`ARI_GUI_CHALLENGES=0` が直接実行を
復元します。

### エンドポイント表

`ari-core/ari/viz/v1/openapi.json`（36 パス / 41 操作）から生成し、読みやすさの
ためにグルーピングしています; 権威あるのは JSON 文書のほうです。

#### プロジェクトとラン

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/v1/projects` | プロジェクト一覧 — チェックポイント探索ベースを集約した 1 つの仮想 `default` プロジェクト。 |
| GET | `/api/v1/projects/{project_id}/runs` | 1 プロジェクト内のラン（チェックポイント）をサマリカードとして — 全チェックポイントルートを統合した 1 つのポートフォリオで、新しい順（mtime 降順）。 |
| GET | `/api/v1/runs/{run_id}` | ランの詳細: サマリに加えて成果物由来の詳細フィールドと capability マップ。 |
| GET | `/api/v1/runs/{run_id}/summary` | 1 ランのサマリカード用スカラ（status、ノード数、レビュースコア、ベストメトリクス、`has_paper`）。 |
| GET | `/api/v1/runs/{run_id}/tree` | BFTS ツリー — `tree_view` のノード一覧をバイト保存のまま透過。 |
| GET | `/api/v1/runs/{run_id}/idea` | `{ckpt}/idea.json`（アイデア / ギャップ分析 / 主要メトリクス）の純粋な読み取り; 不在は `present: false` であり、空データを捏造しません。 |
| GET | `/api/v1/runs/{run_id}/results` | 有界な結果読み取りモデル: 論文 / レビュー / ORS / EAR の存在フラグとスカラ — ファイルの中身は決して返しません。 |
| GET | `/api/v1/runs/{run_id}/ear` | EAR バンドルの一覧メタデータと curate / publish の系譜スカラ。 |
| GET | `/api/v1/runs/{run_id}/logs` | `{ckpt}/ari.log` に対する有界なカーソルページ 1 枚（`cursor`、`limit`、`grep`）。 |
| POST | `/api/v1/runs` | 冪等な起動: ドラフトを検証し、`run_id` を発行し、チェックポイントを実体化し、CLI を起動。 |

#### 設定コントロールプレーン

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/v1/config/schema` | 正準の設定フィールドレジストリ — メタデータのみで、実効値は決して含みません。 |
| GET | `/api/v1/config/catalogs/models` | サーバー側のプロバイダ / モデル候補と、各プロバイダの API キー env 名。 |
| GET | `/api/v1/runs/{run_id}/resolved-config` | 既存チェックポイントの事後解決マニフェスト（値 + 来歴 + ダイジェスト）。 |
| GET | `/api/v1/projects/{project_id}/config` | 既定プロジェクトの設定文書（`revision` + フラットな `values`）。 |
| PATCH | `/api/v1/projects/{project_id}/config` | 部分更新 `{values: {dotted.path: value}}` をマージ・検証・書き込み; `If-Match` 必須。 |
| GET | `/api/v1/run-templates` | ランテンプレート一覧（コードポイント順）。 |
| POST | `/api/v1/run-templates` | ランテンプレートを作成（create-only → `409 already_exists`）。 |
| GET | `/api/v1/run-templates/{template_id}` | ランテンプレートを 1 件読み取り。 |
| PATCH | `/api/v1/run-templates/{template_id}` | テンプレートへ値をマージ; `If-Match` 必須。 |
| DELETE | `/api/v1/run-templates/{template_id}` | テンプレートを削除; `If-Match` 必須。 |
| POST | `/api/v1/run-drafts` | ランドラフトを作成（サーバー生成の `draft-<12 hex>` id; 任意の `goal`）。 |
| GET | `/api/v1/run-drafts/{draft_id}` | ランドラフトを 1 件読み取り。 |
| PATCH | `/api/v1/run-drafts/{draft_id}` | ドラフトへ値をマージ（ゴールは保存されます）; `If-Match` 必須。 |
| POST | `/api/v1/run-drafts/{draft_id}/resolve-config` | このドラフトについて新規ランの解決連鎖全体をプレビュー（任意の `profile`）。来歴と警告付き。 |
| POST | `/api/v1/run-drafts/{draft_id}/validate` | 同じ解決実行から蒸留した `{valid, errors, warnings}`（ここではインターロック不一致は**エラー**です）。 |

#### シークレット

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/v1/secrets/status` | 許可リストのシークレット名に対する readiness 行（`configured` / `source_class` / `last_updated`）— 値のフィールドは存在しません。 |
| PUT | `/api/v1/secrets/{secret_id}` | 許可リストのシークレット 1 件への書き込み専用の代入; レスポンスは書き込み後の readiness 行であり、値ではありません。 |

#### RQGM ガバナンス（読み取り専用）

各ペイロードの意味論は[RQGM GUI 読み取りモデル](rqgm_gui_read_models.md)を
参照してください。

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/v1/runs/{run_id}/rqgm/capabilities` | このランが RQGM ランかどうか（成果物の存在）と、どの論文モードを使うか。 |
| GET | `/api/v1/runs/{run_id}/rqgm/overview` | 有界なガバナンス要約: 現在エポック、ポリシー / 憲法ハッシュ、レジストリ件数、整合性フラグ。 |
| GET | `/api/v1/runs/{run_id}/rqgm/registry` | コミット済み遷移 replay 由来の構成要素とプロンプト、および rollup 検証の結果。 |
| GET | `/api/v1/runs/{run_id}/rqgm/transitions` | コミット済み遷移ログへのバイトオフセットページ（`expand=1` で生イベントを返します）。 |
| GET | `/api/v1/runs/{run_id}/rqgm/audit` | 監査ログへのバイトオフセットページ。`record_type` / `epoch` でフィルタ可能。 |
| GET | `/api/v1/runs/{run_id}/rqgm/policies` | 登録済み utility ポリシーと、その write-once 本体および採用来歴。 |
| GET | `/api/v1/runs/{run_id}/rqgm/score-rewrites` | エポック境界のスコア書き換え: ポリシー supersession をその消去 / 再構築の帰結と join。 |
| GET | `/api/v1/runs/{run_id}/rqgm/nodes/{node_id}/lineage` | 1 ノードの 2 つのスコアチャネル（敵対的ペナルティ対エポックポリシー書き換え）。決して統合されません。 |
| GET | `/api/v1/runs/{run_id}/rqgm/epochs` | コミット済みエポックのタイムライン。エポックごとのポリシーハッシュと境界の件数付き。 |
| GET | `/api/v1/runs/{run_id}/rqgm/epochs/{epoch_id}` | 1 エポックの凍結スカラ、アクティブ集合、開始 / 終了トランザクション、ポリシー本体。 |
| GET | `/api/v1/runs/{run_id}/rqgm/evolution` | プロンプト / utility ポリシー / メタ候補の系譜。明示的な採用 join 付き。 |
| GET | `/api/v1/runs/{run_id}/rqgm/paper-archive` | 論文アーカイブモードのスカラ: エポック、ドラフト数、アンカー状態、自己選好統計、best-belief ドラフト。 |

#### 運用

| メソッド | パス | 用途 |
|---|---|---|
| POST | `/api/v1/challenges` | 1 つの危険な操作に対する単回使用の確認チャレンジを発行。 |
| GET | `/api/v1/diagnostics` | 有界な運用スカラ: SSE バスの統計、ウォッチャの生存、追跡プロセス数、バージョン。シークレットもパスもありません。 |

#### `openapi.json` に含まれないもの

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/v1/events/stream` | SSE の無効化ストリーム（[リアルタイム](#リアルタイム-get-apiv1eventsstreamsse)を参照）。 |
| GET | `/health/live` | 依存の無い liveness 定数 `{"status": "ok"}`。認証免除。 |
| GET | `/health/ready` | readiness: `ok` または `degraded` の `status` と `checks` オブジェクト（`http`、`websocket`、`watcher`、`event_bus`、`active_checkpoint`）。各チェックは独立に評価され、例外を投げたチェックは `false` として読まれます; 縮退した readiness は正直な `200` であり、このプローブが 500 を返すことはありません。認証免除。 |

`ARI_GUI_HEALTH=0` はこの 3 つの health / diagnostics の面をすべて外します
（`/health/*` は SPA レスポンスへ落ち、`/api/v1/diagnostics` は型付き 404 を
返します）。

---

## レガシーの非バージョン API（レガシーファサード — 凍結。MN ノートを参照）

> **凍結。** 以下の非バージョン面は、レガシーのダッシュボードページと既存の統合の
> ために維持されています。**拡張されません**: 新しいデータは run を明示する
> `/api/v1` エンドポイントから配信しなければなりません。特に `GET /state` は
> `ari-core/tests/test_gui_state_facade_freeze.py` がトップレベルのキー集合を厳密に
> ピン留めした凍結ファサードです（アクティブチェックポイント無しで 7 キー、完全に
> 内容のあるチェックポイントで 35 キー）— キーを足せば設計上そのテストが落ち、
> キーを削ればレガシーページが壊れます。

### レガシー面の挙動変更（MN ノート）

GUI リフレッシュのプログラムはいくつかのレガシー挙動を変更しました; それぞれが
番号付きのマイグレーションノート（MN-n）としてロールバックレバーとともに記録されて
います。この下の表が挙げるのは*ルート*であり、そちらは無変更です; ここに挙げるのは
動いた*意味論*です。

| MN | 影響を受けるレガシーエンドポイント | 変更 | ロールバック |
|---|---|---|---|
| MN-1 | `POST /api/workflow{,/flow,/skills,/disabled-tools}` | アクティブチェックポイントが無い場合、同梱の `workflow.yaml` を黙って書き換えることを拒否するようになりました: 現在は `400` を返し何も書きません。 | 差し戻しのみ |
| MN-2 | `GET /api/env-keys` | シークレットの値は redact され（`***configured***`）、`redacted: true` マーカーが加わりました; `POST /api/env-keys` は名前の許可リストを強制します（違反は `400`）。readiness は `GET /api/v1/secrets/status` へ移りました。 | 差し戻しのみ |
| MN-3 | `GET /api/workflow` と 4 つのワークフロー書き込み | 追加的な `revision`（配信バイト列の sha256[:12]）と、書き込み時の任意の `base_revision`; 古い書き込みは盲目的上書きの代わりに `409` で拒否されます。`base_revision` を省略する呼び出し側は last-write-wins のままです。 | 差し戻しのみ |
| MN-4 | すべて（バインド）、CORS を持つすべてのレスポンス | 既定でループバックバインド + same-origin CORS エコー。 | `ARI_GUI_BIND`、`ARI_GUI_CORS_ANY=1` |
| MN-5 | `GET /codefile`、`GET/POST /api/ollama/<path>` | `/codefile` は解決済み正準パスがアクティブチェックポイントまたはチェックポイント探索ベースの配下にあるファイルのみ配信します; Ollama プロキシは 5 パスの許可リストに制限され、ターゲットが明示的に設定されているか実効バックエンドが Ollama でない限り拒否します（`403`）。 | なし（セキュリティ修正） |
| MN-6 | `POST /api/delete-checkpoint`、`POST /api/stop`、`POST /api/gpu-monitor`（`action=stop`） | サーバー発行の `challenge_id` を要求; 無ければ `428` で副作用なし。 | `ARI_GUI_CHALLENGES=0` |
| MN-7 | `GET /`、SPA フォールバック、`GET /static/*` | CSP + `nosniff` + `Referrer-Policy` ヘッダ; CDN の `<script>` はバンドルから削除されました。 | `ARI_GUI_CSP=0` |
| MN-8 | リモートバインド時のすべて | bearer トークン認証（無ければ `401`）; SSE/WS は `?token=` を受け付けます。 | `ARI_GUI_AUTH=0` |
| MN-9 | `GET /health/live`、`GET /health/ready` | SPA HTML のフォールバックでしたが、現在は JSON プローブです（加えて新しい `GET /api/v1/diagnostics`）。 | `ARI_GUI_HEALTH=0` |
| MN-10 | `POST /api/launch` | **無変更** — 正準の冪等な起動は追加的な `POST /api/v1/runs` であり、両者は並走します。 | 該当なし |

### 規約（レガシー）

- エラーは非 2xx HTTP コードとともに `{"error": "<message>"}` として返されます
  （一部のハンドラは `{"ok": false, "error": ...}` を使います）。
- CORS プリフライト（`OPTIONS`）は `/api/*` に対し same-origin のリクエストにのみ
  応答します（MN-4）。

### 型付き契約（安定エンドポイント）

トラフィックの多い GET エンドポイントは、レスポンスの形が
`ari-core/ari/viz/frontend/src/types/index.ts` のフロントエンド TypeScript 型に
鏡写しにされ、`ari-core/tests/test_api_schema_contract.py` がガードしています
（常在キーを**部分集合**として表明するので、追加 / 任意フィールドは許容され、契約は
追加的です）。

| エンドポイント | プロデューサ | フロントエンド型 | 常在キー |
|---|---|---|---|
| `GET /state` | `services/state_service.build_app_state` | `AppState` | `running_pid`、`is_running`、`exit_code`、`running`、`pid`、`status_label`（残りはチェックポイント依存 → 型では任意）。`cost` はパース済みの `cost_summary.json` **オブジェクト**（`CostSummary`）であって数値ではありません。 |
| `GET /api/settings` | `api_settings._api_get_settings` | `Settings` | デフォルト辞書の全体（`llm_model`、`llm_provider`、`ollama_host`、`temperature`、…、ネストした `ors`）; 任意の保存済みキーも透過します（`{**defaults, **saved}`）。 |
| `GET /api/checkpoints` | `checkpoint_api._api_checkpoints` | `Checkpoint[]` | `id`、`path`、`status`、`node_count`、`review_score`、`best_metric`（常に `null`）、`mtime`; `best_scientific_score` は条件付きです。 |
| `GET /api/checkpoint/<id>/summary` | `checkpoint_api._api_checkpoint_summary` | `CheckpointSummary` | `id`、`path`（または `{error:"not found"}`）; すべてのレポート本体は条件付きです。`reproducibility_report` はパース済みの**オブジェクト**（レガシーランでは文字列）であり、常に文字列とは限りません。 |

契約は**寛容**です: 新しい任意フィールドは消費側を壊さずに追加できます; 既存
フィールドがマイグレーション中に削除されることはありません（リファクタリングの
グローバル規則を参照）。

### 動作例

最初に触れることの多いエンドポイントの最小限の `curl` リクエスト / レスポンス例です。
ダッシュボードが既定ポート `8765` で動いている前提です。

**ライブ状態を読む:**

```bash
curl http://localhost:8765/state
```

```json
{
  "checkpoint_id": "20260526T101500_matmul",
  "current_phase": "bfts",
  "node_count": 7,
  "nodes": [{ "id": "node-0", "status": "success", "metrics": {} }],
  "has_paper": false,
  "llm_model": "ollama_chat/qwen3:8b",
  "running_pid": 48213,
  "is_running": true,
  "exit_code": null,
  "status_label": "🟢 Running",
  "cost": { "total": 0.0 }
}
```

抜粋です。凍結ファサードはアクティブなチェックポイントが無い場合はちょうど 7 個、
完全に埋まったチェックポイントでは 35 個のトップレベルキーを出力します。`nodes` は
ツリーのノード一覧（件数サマリではありません）、`cost` はパース済みの
`cost_summary.json` オブジェクトです。

**実行を起動する:**

```bash
curl -X POST http://localhost:8765/api/launch \
  -H 'Content-Type: application/json' \
  -d '{"experiment_md": "# Goal\nImprove GFLOP/s of a dense matmul.\n",
       "profile": "laptop", "provider": "ollama", "model": "qwen3:8b",
       "max_nodes": 8, "max_depth": 3, "workers": 2}'
```

```json
{ "ok": true, "pid": 48213, "checkpoint_path": "workspace/checkpoints/20260526T101500_matmul" }
```

**チェックポイント一覧:**

```bash
curl http://localhost:8765/api/checkpoints
```

```json
[
  { "id": "20260526T101500_matmul", "path": "workspace/checkpoints/20260526T101500_matmul",
    "status": "running", "node_count": 7, "review_score": null,
    "best_metric": null, "mtime": 1779795300 },
  { "id": "20260520T090000_sort", "path": "workspace/checkpoints/20260520T090000_sort",
    "status": "completed", "node_count": 12, "review_score": 0.71,
    "best_metric": null, "mtime": 1779267600, "best_scientific_score": 0.83 }
]
```

一覧は全チェックポイント探索ベースを統合した 1 つのポートフォリオで、`mtime` 降順
（新しい順）です。`status` は `unknown` / `running` / `stopped` / `completed` の
いずれかです。

**エラー形式**（任意のレガシーエンドポイント、非 2xx）:

```json
{ "error": "no active checkpoint" }
```

### 状態 + ダッシュボード

| メソッド | パス | 用途 | ソース |
|---|---|---|---|
| GET | `/state` | ダッシュボードのライブビューが使用する現在の BFTS 状態スナップショット（**凍結キー集合**） | `routes.py` |
| GET | `/api/gpu-monitor` | GPU 使用率ポーリング | `routes.py` |
| GET | `/api/resource-metrics` | CPU / メモリ / ディスクメトリクス | `routes.py` |
| GET | `/api/logs` | アクティブな実行の最近のログ行 | `routes.py` |

### モデル + スキル

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/models` | LiteLLM + Ollama 経由で利用可能な LLM を探索 |
| GET | `/api/ollama-resources` | モデルに必要なメモリ / ディスク |
| GET | `/api/ollama/<...>` | ローカル Ollama デーモンへのプロキシ（許可リストのパスのみ — MN-5） |
| GET | `/api/skills` | 登録済みスキルとそのツール数を列挙 |
| GET | `/api/skill/<skill_name>` | スキルごとのメタデータ（ツール一覧、環境変数） |
| GET | `/api/tools` | 全スキルを横断した統合ツールカタログ |
| GET | `/api/scheduler/detect` | `local` / `slurm` / `apptainer` 自動検出 |
| GET | `/api/slurm/partitions` | SLURM パーティション一覧 |
| GET | `/api/container/info` | コンテナランタイムのプローブ |
| GET | `/api/container/images` | キャッシュ済み SIF / OCI イメージ |
| POST | `/api/container/pull` | `ARI_CONTAINER_IMAGE` が参照するイメージを取得 / ビルド |

### チェックポイントブラウジング

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/checkpoints` | チェックポイント探索ベース全体のチェックポイントを新しい順（`mtime` 降順）で一覧 |
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
| POST | `/api/delete-checkpoint` | チェックポイントを削除（対応する Letta エージェントも削除）— チャレンジが必要（MN-6） |
| POST | `/api/checkpoint/file/save` | チェックポイント内のファイルをインプレース編集 |
| POST | `/api/checkpoint/file/delete` | チェックポイントからファイルを削除 |
| POST | `/api/checkpoint/compile` | 論文草稿に対して `pdflatex` を実行 |

### 実行ライフサイクル

| メソッド | パス | 用途 |
|---|---|---|
| POST | `/api/launch` | 新しい BFTS 実行を開始（`ari run` をプログラム的に）— 無変更; 正準の経路は `POST /api/v1/runs` |
| POST | `/api/run-stage` | 単一のパイプラインステージを実行 |
| POST | `/api/stop` | アクティブな実行を停止 — チャレンジが必要（MN-6） |

### サブ実験 + lineage

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/sub-experiments` | すべてのサブ実験レコード |
| GET | `/api/sub-experiments/<run_id>` | 単一のサブ実験の詳細 |
| POST | `/api/sub-experiments/launch` | 親チェックポイントを継承する子実行を起動 |
| GET | `/api/lineage-decisions/<run_id>` | 停滞ルールが出力した決定（v0.7.0） |

### メモリバックエンド

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/memory/health` | Letta ヘルスプローブ |
| GET | `/api/memory/detect` | 実行中の Letta デプロイパスのインベントリ |
| POST | `/api/memory/start-local` | ローカル Letta サーバを起動 |
| POST | `/api/memory/stop-local` | ローカル Letta サーバを停止 |
| POST | `/api/memory/restart` | ローカル Letta サーバを再起動 |

### 設定 + ワークフロー

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/settings` | settings.json を読み取り |
| POST | `/api/settings` | settings.json に書き込み |
| GET | `/api/profiles` | 保存済みプロファイル一覧 |
| GET | `/api/env-keys` | ARI が認識している環境変数キー（値は redact — MN-2） |
| POST | `/api/env-keys` | 環境変数のキー / 値ペアを `.env` に永続化（名前の許可リスト — MN-2） |
| GET | `/api/workflow` | アクティブな workflow.yaml（+ `revision` — MN-3） |
| GET | `/api/workflow/default` | バンドル済みデフォルト |
| GET | `/api/workflow/flow` | DAG ノード / エッジとして可視化されたワークフロー |
| POST | `/api/workflow` | workflow.yaml を保存（任意の `base_revision` — MN-1/MN-3） |
| POST | `/api/workflow/flow` | DAG ビューを保存（任意の `base_revision` — MN-1/MN-3） |
| POST | `/api/workflow/skills` | 有効なスキルを切り替え（任意の `base_revision` — MN-1/MN-3） |
| POST | `/api/workflow/disabled-tools` | スキルごとのツールホワイトリスト / ブラックリスト（任意の `base_revision` — MN-1/MN-3） |

### ウィザード / 設定生成

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/experiment-detail` | ウィザードがパースした experiment.md |
| POST | `/api/config/generate` | ウィザードの回答から `ari.yaml` を生成 |
| POST | `/api/chat-goal` | LLM 補助による目標ナラティブの精錬 |
| POST | `/api/ssh/test` | SSH クラスタのログインをプローブ |

### アップロード + few-shot コーパス

| メソッド | パス | 用途 |
|---|---|---|
| POST | `/api/upload` | アクティブなチェックポイントへのマルチパートアップロード |
| POST | `/api/upload/delete` | アップロードされたファイルを削除 |
| GET | `/api/fewshot/<rubric_id>` | ルーブリックの few-shot 例 |
| POST | `/api/fewshot/<rubric_id>/sync` | 公開コーパスを取得 |
| POST | `/api/fewshot/<rubric_id>/upload` | 例を追加 |
| POST | `/api/fewshot/<rubric_id>/delete` | 例を削除 |
| GET | `/api/rubrics` | 利用可能な査読ルーブリック（`ARI_RUBRIC` で制御） |

### ノードレポート

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/nodes/<...>/report` | ノードごとの `node_report.json` |

### PaperBench (v0.7.2)

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/api/paperbench/papers` | 登録済み論文一覧（レジストリマニフェストからの `{"papers": [...]}`） |
| GET | `/api/paperbench/arxiv/<arxiv_id>` | 公開 arXiv Atom API へのメタデータ問い合わせ |
| GET | `/api/paperbench/papers/<paper_id>/license` | 1 論文の記録済みライセンス / 再配布方針 |
| POST | `/api/paperbench/papers/import` | 新しい論文をレジストリに登録 |
| POST | `/api/paperbench/papers/<paper_id>/metadata` | 既存マニフェストエントリにフィールドをマージ |
| POST | `/api/paperbench/papers/<paper_id>/delete` | マニフェストエントリと論文ディレクトリを削除（冪等） |
| POST | `/api/paperbench/cost-estimate` | 起動前のドライランコスト見積もり |
| POST | `/api/paperbench/run` | 指定した `paper_ids` の PaperBench ジョブを投入 |
| GET | `/api/paperbench/run/<job_id>` | ジョブ状態のスナップショット |
| GET | `/api/paperbench/run/<job_id>/logs` | 1 ジョブの SSE ログストリーム（`since=`、`Last-Event-ID`; 300 秒ウィンドウ、`: heartbeat`、終端は `event: done`） |
| GET | `/api/paperbench/run/<job_id>/results` | ジョブごとの結果ペイロード |
| GET, POST | `/api/paperbench/run/<job_id>/report` | 監査レポートの生成 / 取得（`languages`、`formats` — URL クエリまたは POST ボディ） |

ジョブ状態はインメモリテーブルですが、`{registry_root}/jobs/{job_id}.json` へ
アトミックにミラーされます（一時ファイル + `os.replace`、モード `0o600`）。
そのため viz サーバーを再起動しても過去のジョブを忘れなくなりました。再起動後、
GET 側のリーダーはそのレコードへ読み取り専用でフォールバックし、稼働中ステータス
（`queued` / `running`）のまま永続化されていたジョブは追加ステータス
`interrupted` として報告されます — ワーカーが再起動されることはありません。

### EAR + 公開 (v0.7.0)

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

### 静的ファイル + フロントエンド

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/static/<path>` | バンドル済み UI アセット（セキュリティヘッダ — MN-7） |
| GET | `/memory/<path>` | メモリインスペクタ静的ページ |
| GET | `/codefile?path=...` | ソースファイルビューア（正準パス境界 — MN-5） |

### このリファレンスの更新方法

`/api/v1` の場合: `ari/viz/v1/router.py` へルートを追加し、`openapi.json` を
再生成し（`python -m ari.viz.v1.openapi --update`）、上のエンドポイント表へ 1 行の
用途を反映してください。

レガシー面の場合: ルートテーブルは `ari-core/ari/viz/routes.py` のディスパッチ
チェーンです。新しいルートはここではなく `/api/v1` に属します。

### 関連ドキュメント

- `docs/ja/reference/rqgm_gui_read_models.md` — RQGM 読み取りモデルの意味論。
- `docs/ja/reference/configuration.md` — `/api/v1/config/*` の背後にある設定
  コントロールプレーン。
- `docs/ja/reference/environment_variables.md` — `ARI_GUI_*` スイッチ。
- `docs/ja/concepts/architecture.md` — viz パッケージの概要。
- `ari-core/ari/viz/__init__.py` — 現在のサブモジュールマップを含むモジュール
  レベルの docstring。
