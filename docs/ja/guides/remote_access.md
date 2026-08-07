---
sources:
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/websocket.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/v1/challenges.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/services/api/client.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/shared/realtime/eventStream.ts
    role: implementation
  - path: ari-core/tests/test_gui_remote_auth.py
    role: test
  - path: ari-core/tests/test_gui_bind_cors.py
    role: test
  - path: ari-core/tests/test_gui_csp_headers.py
    role: test
  - path: ari-core/tests/test_gui_health_diagnostics.py
    role: test
  - path: ari-core/tests/test_gui_confirmation_challenges.py
    role: test
  - path: scripts/setup/setup_env.sh
    role: config
last_verified: 2026-07-27
---

# リモートアクセスと運用ガイド

ARI ダッシュボードを、表示しているノートパソコン以外の場所で動かすことに関する
すべて: 既定の信頼姿勢、意図的に開放する方法、運用者に必要なエンドポイント。

要約すると: **ダッシュボードは既定では単一運用者向けのローカルツールであり、
そこから離れるすべての一歩は明示的なオプトインです。**

## 既定の姿勢: ループバックのみ

GUI 関連の環境変数を何も設定しない場合:

- HTTP サーバーは `127.0.0.1` **と** `::1` にバインドします（両方のループバック
  ファミリなので、ディストリビューションが `localhost` を IPv4 と IPv6 のどちらへ
  解決しても動きます）;
- **HTTP ポート + 1** の WebSocket サーバーも同じようにバインドします;
- **認証はありません** — ループバックバインドと same-origin CORS *こそ*が防御です;
- LAN 上の別ホストはそもそも接続できません。

これは緩和されるのを待つ既定値ではなく、意図的なポリシーです: 以前のビルドは全
インタフェースに認証なしでバインドし、無条件の `Access-Control-Allow-Origin: *` を
返していたため、削除・停止・シークレット書き込みを含むすべてのエンドポイントを
クラスタネットワーク全体へ晒していました。

別マシンからダッシュボードを見たいだけなら、**SSH トンネル**（後述）を推奨します。
トンネリングはループバック姿勢を保ったままで、トークンも不要です。

## GUI 環境変数

すべて `scripts/setup/setup_env.sh` にコメントアウト状態で先行記載されています。

| 変数 | 既定 | 効果 |
|---|---|---|
| `ARI_GUI_V2` | オン | `0`/`false` でレガシーシェルへ戻す |
| `ARI_GUI_BIND` | 未設定 → ループバック | バインドアドレスのオプトイン（後述） |
| `ARI_GUI_TOKEN` | 未設定 | リモートモードで必要な bearer トークン |
| `ARI_GUI_AUTH` | オン | `0`/`false` でリモートのトークンゲートを無効化 |
| `ARI_GUI_CORS_ANY` | オフ | `1` でレガシーの `ACAO: *` ワイルドカードを復元 |
| `ARI_GUI_CSP` | オン | `0` で CSP + nosniff + Referrer-Policy を外す |
| `ARI_GUI_CHALLENGES` | オン | `0` で確認チャレンジを無効化 |
| `ARI_GUI_HEALTH` | オン | `0` で health/diagnostics の面を無効化 |

いずれも意図的なロールバックレバーであり、実装の隣に文書化されています。どれをオフに
しても、以前に出荷されていた挙動へ戻るだけです — 新しい何かが解放されることは
ありません。

## 非ループバックバインドへのオプトイン

```bash
export ARI_GUI_BIND=0.0.0.0     # IPv4 wildcard
# export ARI_GUI_BIND='::'      # all interfaces, dual stack (the pre-hardening bind)
# export ARI_GUI_BIND=10.0.0.7  # exactly one interface
python -m ari.viz.server --port 8765
```

解決規則: 未設定または空 → `["127.0.0.1", "::1"]`; **任意の**明示値 → そのホスト 1 つ
だけにバインド。WebSocket サーバーも同じポリシーに従います。

非ループバックの値はサーバーを**リモートモード**へ切り替え、リモートモードは認証
されます。`localhost`、`::1`、任意の `127.x.y.z` はループバック扱いです; それ以外は
ワイルドカードを含めてすべてリモートです。

## リモートモードでのトークン認証

リモートモードでは、**`/health` 接頭辞を除くすべての HTTP リクエスト**がトークンを
提示する必要があり、WebSocket のハンドシェイクも同様です。ゲートは
`do_GET` / `do_POST` / `do_PUT` / `do_PATCH` / `do_DELETE` の最上部、ディスパッチや
ボディ読み取りの前に走ります。

### トークンを用意する

固定する場合:

```bash
export ARI_GUI_TOKEN="$(python -c 'import secrets;print(secrets.token_hex(16))')"
```

…あるいは設定せずに起動してサーバーに生成させます。これは**フェイルセキュア**です:
リモートバインドが未認証で起動することはありません。生成されたトークンは stderr へ
**一度だけ**出力され、ログファイルへは決して書かれません:

```text
  ============================================================
  ARI GUI is bound to a non-loopback address and ARI_GUI_TOKEN
  is not set. A random access token was generated for this run
  (MN-8, ADR-13). It is printed here ONCE and never logged:

      ARI_GUI_TOKEN=<32 hex chars>

  Every request must send 'Authorization: Bearer <token>'
  (SSE/WebSocket: '?token=<token>'). Set ARI_GUI_TOKEN to pin
  a stable token across restarts.
  ============================================================
```

再起動をまたいでトークンを保ちたい場合は `ARI_GUI_TOKEN` を明示的に設定してください
（さもないと再起動のたびに新しいトークンが発行され、すべてのブラウザで設定し直す
必要があります）。

### ブラウザがトークンを渡す方法

ログイン画面はまだありません。フロントエンドは `localStorage` のキー
`ari_gui_token` からトークンを読みます; ページ自身のオリジンでブラウザコンソールから
一度だけ設定してください:

```js
localStorage.setItem('ari_gui_token', '<token>');  // then reload
```

以降クライアントはすべての `fetch` に `Authorization: Bearer <token>` を付け、
ヘッダを設定できない 2 つのトランスポートには `?token=<token>` を付加します。
ループバック既定ではキーが未設定なので、リクエストの形は変わりません。

### SSE と WebSocket がクエリパラメータを使う理由

ブラウザの `EventSource` と `WebSocket` の API はリクエストヘッダを設定できません。
そのため両者はトークンを **`token` クエリパラメータ**としても受け付けます:

```text
GET /api/v1/events/stream?run_id=…&topics=run,tree&token=<token>
ws://host:8766/?token=<token>
```

これは受容され記録されたトレードオフです。緩和策として、アクセスログ
（`{checkpoint}/viz_access.jsonl`）は書き込み前に `token=` のクエリ値を `***` へ
書き換えるため、どちらの形式でもトークンがログファイルへ到達することはありません。
fetch で消費されるレガシーの `/api/logs` ストリームは、消費側がヘッダを設定*できる*
のでヘッダを使います。

### 失敗時の挙動

トークンが無い / 誤っている場合は、型付き JSON ボディと `WWW-Authenticate: Bearer` を
伴う `401` になります; 比較は定数時間（`hmac.compare_digest`）です; 未読のボディが
keep-alive を同期外れにしないよう接続は閉じられます。WebSocket のハンドシェイクは
アップグレード前に同じ 401 の形で拒否されます。

### スクリプトと curl

```bash
curl -H "Authorization: Bearer $ARI_GUI_TOKEN" http://host:8765/api/v1/projects
curl -N "http://host:8765/api/v1/events/stream?token=$ARI_GUI_TOKEN"
```

### Cookie が無いので CSRF も無い

認証は bearer トークンのみです。Cookie に乗るものが何も無いので、クロスサイト
リクエストフォージェリの面も、管理すべき CSRF トークンも存在しません。セッション、
ログアウト、マルチユーザーアクセスは意図的に先送りされています — 今日これは単一
運用者向けの研究ツールであり、マトリクス全体（ローカル / リモート / トークン /
キルスイッチ）は `ari-core/tests/test_gui_remote_auth.py` でユニットテストされて
います。

### `ARI_GUI_AUTH` の脱出ハッチ

`ARI_GUI_AUTH=0` はリモートゲートを無効化し、旧来の未認証リモートバインドを復元
します。GUI の前段で既に認証が行われている場合 — たとえば認証を行うリバース
プロキシ — にのみ使ってください。ループバックバインドはいずれにせよ未認証であり、
このスイッチはそこでは効果を持ちません。

## CORS

レスポンスは**same-origin のみ**です。リクエストの `Origin` が
`Access-Control-Allow-Origin`（および `Vary: Origin`）としてエコーバックされるのは、
それがこのサーバーを指しているとき — リクエストの `Host` ヘッダに一致するか、
サーバーポート上のループバック表記 `localhost` / `127.0.0.1` / `[::1]` のいずれか —
に限られます。クロスオリジンのリクエストには ACAO ヘッダが**まったく**付かないので、
ブラウザはレスポンスをページへ渡すことを拒否します。

プリフライト（`OPTIONS`）は許可されないオリジンにも `204` を返しますが、
`Access-Control-*` ヘッダは一切付きません。許可されたオリジンにはさらに
`Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS`、
`Access-Control-Allow-Headers: Content-Type, X-Filename, If-Match, Last-Event-ID`、
そして 24 時間の `Access-Control-Max-Age` が付きます。

実務上の意味:

- **トンネルおよび Host を保持するプロキシは問題ありません** — ページのオリジンが
  サーバーの見る `Host` と一致します。
- **`:5173` の Vite 開発サーバーは問題ありません** — そのプロキシが `/api`、
  `/state`、`/ws` を same-origin で転送します。
- **API とは別オリジンからページを配信するポータルは問題があり**、
  `ARI_GUI_CORS_ANY=1`（レガシーのワイルドカードを復元）が必要になります。トポロジ
  を直すほうを優先してください; ワイルドカードは最後の手段です。

2 つのエンドポイント — `GET /state` と `GET /api/gpu-monitor` — は歴史的に ACAO を
持たず、今もそのままです。

## ブラウザセキュリティヘッダ（CSP）

SPA の index とすべての `/static/` レスポンスには次が付きます:

```text
Content-Security-Policy: default-src 'self'; script-src 'self';
  style-src 'self' 'unsafe-inline'; img-src 'self' data:;
  connect-src 'self' ws://<host>:<port+1> wss://<host>:<port+1>;
  frame-src 'self'; frame-ancestors 'none'
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
```

プロキシ配下へデプロイする前に知っておくべき点:

- バンドルは完全に自己完結しています — 許可すべき CDN の `<script>` はありません。
  オフラインホストが直接恩恵を受けます。
- `connect-src` はツリー用 WebSocket を**明示的に**挙げ、リクエストの `Host`
  ヘッダから導出します。ストリームが HTTP ポート + 1 で待ち受けるのに対し `'self'` は
  ページ自身のポートしか覆わないからです。**プロキシが WebSocket のポートをリマップ
  すると、ブラウザがそれをブロックし**、ダッシュボードはポーリングへ縮退します。
  `ARI_GUI_CSP=0` はまさにそのトポロジのために存在します。
- `frame-ancestors 'none'` は、ダッシュボードを他サイトの iframe に埋め込めないことを
  意味します。`frame-src 'self'` は same-origin の PDF iframe を動作させ続けます。
- `style-src 'unsafe-inline'` は受容された残存事項です（React のインライン
  `style={}` 属性が広範に使われているため）; 厳格化は追跡中の作業です。
- API / JSON のレスポンスには意図的に CSP を付けません。

## 破壊的操作の確認チャレンジ

3 つの操作は、クライアント側の確認だけでは発火しません: チェックポイントの削除、
全プロセスの停止、GPU モニタの停止。サーバーは**1 つのアクションと 1 つの対象に
束縛された**短命の許可を発行し、破壊的エンドポイントはそれを返すことを要求します。

```bash
# 1. ask for a challenge
curl -X POST http://localhost:8765/api/v1/challenges \
     -H 'Content-Type: application/json' \
     -d '{"action":"delete-checkpoint","target":"/path/to/checkpoints/2026…"}'
# -> {"challenge_id":"chg-0a1b2c3d4e5f","action":…,"target":…,
#     "expires_at":"…Z","ttl_seconds":60}

# 2. echo it back with the destructive call
curl -X POST http://localhost:8765/api/delete-checkpoint \
     -H 'Content-Type: application/json' \
     -d '{"path":"/path/to/checkpoints/2026…","challenge_id":"chg-0a1b2c3d4e5f"}'
```

| アクション | 対象 | 強制される先 |
|---|---|---|
| `delete-checkpoint` | チェックポイントのパス | `POST /api/delete-checkpoint` |
| `stop-all` | `"*"` | `POST /api/stop` |
| `gpu-monitor-stop` | `"*"` | `action=stop` 付きの `POST /api/gpu-monitor` |

性質:

- **単回使用**、単調クロックで測る 60 秒 TTL（壁時計のジャンプで許可を延長できません）、
  有界なインメモリストア（上限 100、古いものから追い出し。再起動ですべて消えます —
  クライアントは単に再度要求します）;
- 不在・未知・期限切れ・使用済み・束縛不一致のチャレンジは HTTP **428** と凍結
  ボディ `{"ok": false, "error": "confirmation challenge required or invalid"}` を
  受け取り、**破壊的な処理は一切行われません**。オラクルとして使われないよう、
  メッセージはどの失敗でも同一です;
- 発行・消費・拒否は `challenge_*` イベントとしてアクティブチェックポイントの
  `viz_access.jsonl` へ監査ログされ、それが認可したリクエスト行と交互に並びます;
- GUI 上ではこれは不可視です: 見えるのは 1 つの確認ダイアログのままですが、そこには
  **サーバー**がエコーバックした正確な対象が表示されます — 同意する前に検証できる
  影響プレビューです。

旧来の単発エンドポイントをスクリプト化していた自動化は、2 段階フローを採用するか
`ARI_GUI_CHALLENGES=0` を設定する必要があります。キルスイッチ下でも発行は利用可能な
ままなので、2 段階のクライアントはどちらでも動きます。

## SSH トンネル（推奨、かつ検証済みの経路）

サーバーをループバックに置いたままポートを転送します。サーバーの姿勢は何も変わらない
ので、トークンは関与しません。

```bash
# on the workstation
ssh -N -L 8765:localhost:8765 -L 8766:localhost:8766 user@remote-host
# then open http://localhost:8765/
```

**両方**のポートを転送してください: HTTP 用の `8765` と、ツリー WebSocket 用の
`8766`（HTTP + 1）。HTTP ポートだけを転送しても全体は動きます — WebSocket が接続に
失敗するだけで、レガシーページはポーリングへフォールバックします。

計算ノードの手前にクラスタのログインノードがある場合は、ホップを連鎖させます:

```bash
ssh -N -J user@login.cluster -L 8765:localhost:8765 -L 8766:localhost:8766 user@compute-node
```

これはループバック既定が想定して設計されたトポロジであり、CORS ポリシーが検証されて
いる組み合わせです（`ari-core/tests/test_gui_bind_cors.py` がループバックの別名を
含む same-origin マトリクスを覆っています）。

## HPC リバースプロキシ（ガイダンス。エンドツーエンドでは**未検証**）

> 以下のレシピは未検証のガイダンスです。実際に動作するクラスタ配備ではなく、サーバー
> の文書化されたヘッダ / バインドポリシーから書かれています。依存する前にご自身の
> 環境で検証してください。

クラスタのポータルがリバースプロキシ越しにダッシュボードを配信する必要がある場合、
実装済みの挙動から従う制約は次のとおりです:

1. **`Host` ヘッダを保持すること。** same-origin CORS チェックと CSP の
   `connect-src` はどちらもこれから導出されます。`Host` を書き換えるプロキシは、
   ブラウザに自分自身の API 呼び出しをブロックさせます。
2. **ダッシュボードをオリジンのルートで配信すること。** ハッシュルーティング
   （`#/…`）はどのパスの背後でも問題ありませんが、静的アセットは `/static/dist/` から
   配信され、SPA フォールバックが未知のパスに応答します — サブパスマウントを
   サーバーが書き換えてくれるわけではありません。
3. **WebSocket のポートをリマップしないこと。** ブラウザはそれをページのポート + 1
   として導出し、CSP はまさにそれを許可します。どうしてもリマップする場合は
   WebSocket が CSP でブロックされることを想定し、ポーリングフォールバックを受け入れる
   か、その配備で `ARI_GUI_CSP=0` を設定してください。
4. **SSE をバッファリングしないこと。** `GET /api/v1/events/stream` は 15 秒の
   ハートビートコメントと有界な 300 秒の窓を持つ長寿命ストリームです; バッファリング
   するプロキシはライブ更新を無に変えます。レスポンスバッファリングを無効化し、
   読み取りタイムアウトをハートビート間隔より長く設定してください。
5. **認証をどこに置くか決めること。** プロキシで認証を終端し、プロキシだけが到達
   できるバインドで `ARI_GUI_AUTH=0` にするか、トークンゲートを保ったままプロキシに
   `Authorization` をそのまま通させるか、どちらかにしてください。どちらもやらない、は
   駄目です。
6. **できるだけ狭くバインドすること** — プロキシを同一ホストに置いた
   `ARI_GUI_BIND=127.0.0.1` はワイルドカードバインドより厳密に優れています。
7. **`frame-ancestors 'none'`** はポータルがダッシュボードを iframe に入れられない
   ことを意味します; 代わりにリンクを張ってください。

## 運用者向けの health と diagnostics

読み取り専用の面が 3 つあります。`/health` 接頭辞はトークンゲートから**免除**されて
います（liveness プローブは資格情報なしで動く必要があるため）; `/api/v1/diagnostics`
は免除されず、リモートモードでは他と同様に bearer トークンが必要です。

### `GET /health/live`

依存の無い定数です。HTTP ハンドラが応答できるなら、プロセスは生きています。

```json
{"status": "ok"}
```

### `GET /health/ready`

```json
{"status": "degraded",
 "checks": {"http": true, "websocket": true, "watcher": false,
            "event_bus": true, "active_checkpoint": true}}
```

各チェックは独立に評価され、例外を投げたチェックは `false` として読まれます。
**readiness が 500 を返すことはありません** — `degraded` は正直な 200 であり、壊れた
サブシステムは例外になる代わりに観測可能になります。チェックの内訳: `http`
（ディスパッチされたリクエストの内側では恒真）、`websocket`（WS サーバーが起動済み）、
`watcher`（チェックポイントのポーリングスレッドが生存）、`event_bus`（SSE バスが
インポート可能で publish 可能）、`active_checkpoint`（1 つ選択されており、ディスク上に
まだ存在する）。

### `GET /api/v1/diagnostics`

有界なスカラのみ — 件数、経過時間、バージョン:

```json
{"schema_version": 1,
 "sse": {"subscribers": 2, "buffer_len": 137, "last_event_id": 4021},
 "watcher": {"alive": true, "last_scan_age_s": 0.9},
 "process": {"tracked_runs": 1},
 "cache": false,
 "openapi_version": "…"}
```

シークレットもファイルシステムのパスもありません — `tracked_runs` は**件数**であり、
その背後のチェックポイントパスのキーではありません。`cache: false` はフィールドを
省略するのではなく、キャッシュサブシステムが存在しないことを明示します。すべての
サブコレクタは失敗時にゼロ形へ縮退します。物事が壊れているときこそ diagnostics は
読めなければならないからです。

典型的な運用者のループ:

```bash
curl -s localhost:8765/health/live
curl -s localhost:8765/health/ready | python -m json.tool
curl -s -H "Authorization: Bearer $ARI_GUI_TOKEN" \
     http://host:8765/api/v1/diagnostics | python -m json.tool
```

解釈のヒント: `watcher.alive=false` や、際限なく増える `last_scan_age_s` は、
チェックポイントウォッチャが固まっていることを意味します — ランは続いているのに
ツリーの更新が止まります。ブラウザタブを開いていないのに `sse.subscribers` が高い
場合は、バッファリングするプロキシによるストリームのリークが疑われます。

`ARI_GUI_HEALTH=0` は従来のワイヤ挙動を復元します: `/health/*` は SPA レスポンスへ
落ち、`/api/v1/diagnostics` は型付きの 404 エンベロープを返します。

## アクセスログ

チェックポイントがアクティブな間、リクエストは JSON 行として
`{checkpoint}/viz_access.jsonl` へ追記されます — `ts`、`method`、`path`、`status`、
`duration_ms`、`client` — で、`token=` のクエリ値は `***` へ redact されます。
アクティブなチェックポイントが無いときは何も書かれません。確認チャレンジのイベント
（`challenge_issued`、`challenge_consumed`、`challenge_refused`）も同じファイルへ
入るので、破壊的リクエストとそれを認可した許可が隣り合って並びます。

## クイックリファレンス: 姿勢を選ぶ

| やりたいこと | やること | 認証 |
|---|---|---|
| ローカル利用 | 何もしない | なし |
| 手元のノートパソコンから見る | `ssh -L 8765:localhost:8765 -L 8766:localhost:8766 …` | なし |
| LAN から直接アクセス | `ARI_GUI_BIND=0.0.0.0`（+ `ARI_GUI_TOKEN`） | bearer トークン（必須） |
| 認証するプロキシの背後 | 狭い `ARI_GUI_BIND` + `ARI_GUI_AUTH=0` | プロキシ側 |
| クロスオリジンのポータル | 上記 + `ARI_GUI_CORS_ANY=1` | プロキシ側 |

## 関連

- [ダッシュボードガイド](dashboard.md) — サーバーの起動、ポート、ワークスペースの地図。
- [Configuration Studio](configuration_studio.md) — シークレットの書き込み方
  （読み戻しは不可）。
- [HPC セットアップ](hpc_setup.md) — SLURM クラスタで ARI 自体を動かす。
- [トラブルシューティング](troubleshooting.md) — よくある実行時の失敗。
- [環境変数](../reference/environment_variables.md)。
- [REST API リファレンス](../reference/rest_api.md)。
