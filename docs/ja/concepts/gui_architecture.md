---
sources:
  - path: ari-core/ari/viz/frontend/src/app/routeRegistry.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/App.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Layout/Sidebar.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/app/queryClient.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/hooks/useV1.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/hooks/useRunEvents.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/shared/realtime/eventStream.ts
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/api_capabilities.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/v1/queries.py
    role: implementation
  - path: ari-core/ari/viz/v1/results.py
    role: implementation
  - path: ari-core/ari/viz/v1/rqgm.py
    role: implementation
  - path: ari-core/ari/viz/v1/events.py
    role: implementation
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/viz/v1/challenges.py
    role: implementation
  - path: ari-core/ari/viz/v1/openapi.json
    role: schema
  - path: ari-core/ari/viz/frontend/src/app/__tests__/routeRegistry.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/routeNavParity.test.tsx
    role: test
last_verified: 2026-07-30
---

# ダッシュボードアーキテクチャ

ARI のダッシュボードは、`ari/viz/` の Python HTTP サーバーが配信する
React/TypeScript のシングルページアプリです。このページは*概念*ビューです:
ダッシュボードが今の形になっている理由を説明する、ごく少数の構造的決定 —
2 世代の画面を 1 つのシェルが載せること、ルートを 1 つのレジストリが所有すること、
サーバー状態を 1 つのキャッシュが所有すること、HTTP とファイルシステムの間に
1 つのシームがあること。

エンドポイント一覧でもクリック手順ツアーでもないのは意図的です:

- [ダッシュボードガイド](../guides/dashboard.md) — 運用者向けツアー: サーバーの
  起動、各ワークスペースが答えること、ディープリンク。
- [ARI アーキテクチャ](architecture.md) — ダッシュボードが観測する研究システム
  （パイプライン、BFTS、チェックポイント）。
- [研究状態とガバナンス状態](research_and_governance_state.md) — ダッシュボードが
  分離しておく必要のある状態語彙。
- [REST API リファレンス](../reference/rest_api.md) — エンドポイント表。

---

## 全体像

```text
     #/tree2?run=R1&node=N7       ← the URL is navigation truth
               │
               ▼
  ┌──────────────────────────── browser ─────────────────────────────┐
  │  route registry (app/routeRegistry.ts)                           │
  │    · path + legacy aliases  · nav slot  · guiV2 gate             │
  │               │                                                  │
  │               ├──▶ legacy screen  (#/tree, #/results, …)         │
  │               └──▶ v2 workspace   (#/tree2, #/results2, …)       │
  │                     │   both inside the SAME shell/Layout        │
  │                     ▼                                            │
  │  server-state cache (react-query)                                │
  │  key = ['v1', <runId | projectId>, <resource>]                   │
  └────────────┬─────────────────────────────────┬───────────────────┘
    HTTP GET   │                                 │  SSE = invalidations
               ▼                                 ▼
  ┌────────────────── transport: ari/viz/routes.py ──────────────────┐
  │  same-origin CORS · CSP / nosniff / Referrer-Policy ·            │
  │  bearer auth on non-loopback binds · challenges · logs           │
  └────────────┬─────────────────────────────────┬───────────────────┘
               ▼                                 ▼
     v1/router.py (ROUTES table)             v1/events.py (bus)
               │
               ▼
     pure read modules: queries.py · results.py · rqgm.py · logs.py
     (no viz.state writes · no os.environ writes · no ari.rqgm)
               │
               ▼
     {checkpoint}/  tree.json · review_report.json ·
                    rqgm_transitions.jsonl · ear/     ← the truth
```

以下のすべては 1 つの規則の帰結です: **ディスク上のコミット済み成果物だけが
真実であり、その上のどの層も捨てて再計算できる射影にすぎない。**

---

## 1. ストラングラー構造: 1 つのシェル、2 世代の画面

ダッシュボードはその場で作り直されたわけではありません。レガシー画面と新しい
v2 ワークスペースは同じルーターに並んで登録され、同じ `Layout`（サイドバー、
ヘッダー、チェックポイントピッカー）の中で描画されます。新しい画面のために
何かが削除されたことはありません。

| 世代 | ハッシュルート |
|---|---|
| レガシー画面 | `#/home`、`#/experiments`、`#/monitor`、`#/tree`、`#/results`、`#/wizard`（`#/new`）、`#/idea`、`#/workflow`、`#/settings`、`#/paperbench*` |
| v2 ワークスペース | `#/projects`、`#/overview?run=`、`#/tree2?run=&node=`、`#/ideas2?run=`、`#/results2?run=`、`#/governance?run=`、`#/config?run=`、`#/studio` |

2 世代の共存を可能にしている仕組みは 3 つです:

- **並走。** v2 ワークスペースが対応するレガシー画面を編集することはありません。
  `#/tree` と `#/tree2` は同じ成果物に対する別コンポーネントであり、どちらも
  到達可能なままです。
- **ナビの引き継ぎ（`navReplaces`）。** v2 シェルが有効な間、v2 ルートは対応する
  レガシールートの*サイドバースロット*を占有できます — そのスロットのラベル、
  順序、アイコンを継承するので、サイドバーの見た目は同一で、クリックが書き込む
  ハッシュだけが変わります。レガシールートは登録されたままなので URL は動作し
  続け、ブックマークが壊れることはありません。
- **単一のキルスイッチ。** v2 シェルをオフにすると、v2 専用ルートは未知のハッシュ
  とまったく同じように Home へ解決され、サイドバーはそのエントリを隠します。
  再ビルドも再デプロイも不要です — §7 を参照。

したがってこの移行には、スケジュールすべきカットオーバーの瞬間がありません。
ワークスペースはナビスロットを与えることで昇格し、スロットを取り上げることで
ロールバックされます。

---

## 2. ルートが存在する場所はルートレジストリだけ

`app/routeRegistry.ts` は 1 つの `ROUTE_REGISTRY` 配列を保持します。各エントリは
ルートの `id`、ハッシュ `path`、遅延 `load` サンク、任意のナビメタデータ
（`navLabelKey`、`navOrder`、`navIcon`、`navPath`）、`legacyAliases`、そして移行
マーカー `guiV2` / `navReplaces` を持ちます。

2 つの消費側はいずれも手で保守されるのではなく*導出*されます:

- `App.tsx` は遅延コンポーネントマップとディスパッチをレジストリから構築します
  （`resolveRoute` は `#/` 接頭辞とクエリ文字列を剥がし、空ハッシュを `home` と
  みなし、`new` → `wizard` のようなレガシーエイリアスを適用します）。
- `Sidebar.tsx` は `navItems()` からナビ表を構築し、`navReplaces` エントリを
  ターゲットのスロットへ実体化して `navOrder` でソートします。サイドバーは
  さらにウィザードのエントリをプライマリアクションとして抜き出し、残りを
  4 つの固定グループ（portfolio / research / quality / system）に並べます。

2 つの凍結リテラルテストが結果をピン留めしているため、ナビには存在するのに
ルーターには存在しない（またはその逆の）ルートへドリフトすることはできません。
ここから落ちてくる実務規則:

- **ハッシュ URL はデプロイ契約です。** ユーザーがブックマークし、ドキュメントが
  引用するものなので、レジストリは歴史的な綴りを整理せず保存します（ウィザードは
  今も `#/new` へ遷移します）。
- **到達可能だが非掲載、を表現できます。** `#/paperbench/import|run|results` は
  ナビエントリを持たないルートとして存在し、ページ内部から開かれます。
- **未知のハッシュはエラーではなく Home へフォールバックします。**

---

## 3. URL がナビゲーションの真実

ダッシュボードはハッシュルーターであり、*選択*はハッシュのクエリ文字列に住みます:
`#/overview?run=<run_id>`、`#/tree2?run=<run_id>&node=<node_id>`。ルートの
ディスパッチはクエリ文字列を無視するので、各 v2 ワークスペースが自分の
パラメータを所有します — マウント時に読み、`hashchange` で読み直し、選択の変更を
ハッシュへ書き戻します。

概念的に重要な理由: ワークスペースの描画内容はその URL だけの関数である、という
ことです。これによりあらゆるビューがリロード可能・ブックマーク可能・共有可能に
なります — 「ラン R1 のノード N7 を見て」はクリック手順ではなくリンクです。

レガシー経路がこの規則の動機となる対比です。レガシー Experiments の行から
レガシー Results ページへ至る経路は今も*暗黙の*受け渡し（`sessionStorage` の
キー + 裸の `#/results` ハッシュ）を通り、レガシーシェルはさらにプロセス全体の
*アクティブチェックポイント*を持ちます。どちらも v2 ワークスペースの妥当な入力
ではありません: v2 ルートは run を明示するからこそ、2 つのタブで 2 つのランを
開いても互いを踏まないのです — v2 の行は代わりに `#/results?run=<run_id>` へ
リンクし、Results ページはそのパラメータを権威として扱い、`sessionStorage` の
キーは古い呼び出し元向けのフォールバックとしてのみ残しています。

---

## 4. サーバー状態はランをキーとするキャッシュに住む

`/api/v1` のすべての読み取りは 1 つの react-query クライアントを通ります。クエリ
キーの形は `['v1', <projectId | runId>, <resource>]` — 識別子はキーの*内側*に
あります。

この 1 つの決定が 3 つの性質を買います:

- **2 つのランが混ざることは決してありません。** ラン単位のエントリは別々の
  キャッシュエントリなので、ランを切り替えても前のランのデータが現在のビューへ
  滲むことはありません。
- **無効化の粒度がちょうど正しくなります。** `['v1', runId]` を落とせば 1 ランの
  サーバー状態だけが落ちます; リソースに属するフィルタ（監査ログのレコード種別、
  エポック）もキーに入るので、それを変えると陳腐化したページ連鎖へ追記するのでは
  なく新しいページ連鎖が始まります。
- **鮮度ポリシーが 1 箇所に集まります。** クライアントの既定は `staleTime`
  5000 ms（従来のポーリング周期に合わせてあるので、その窓の内側での再マウントは
  キャッシュを返します）、リトライ 1 回、ウィンドウフォーカス時の再取得なし —
  ローカルダッシュボードがフォーカスのばたつきをチェックポイントスキャナへの
  リクエスト嵐に変えてはなりません。

クライアント専用の状態（どのタブが開いているか、フィルタ欄のテキスト、サイドバー
幅）はこのキャッシュに*入りません*。分担はこうです: サーバー状態はキャッシュされ
無効化され、ビュー状態はローカルで刹那的、ナビゲーション状態は URL にある（§3）。

---

## 5. リアルタイムは無効化であって真実源ではない

`GET /api/v1/events/stream` はサーバー側で `run_id` / トピックをフィルタする
Server-Sent Events ストリームです。イベントは小さな通知
（`{event_id, run_id, topic, revision, occurred_at, kind, resource, payload}`）
であり、消費側の唯一の反応は一致するキャッシュキーを無効化して HTTP スナップ
ショットを再取得することです。

イベント*から*描画されるものは一切ありません。この設計の理由はその帰結にあります:

- **重複と順序入れ替えは無害です。** 何が真かを決めるのはスナップショット
  エンドポイントであり、イベントは*いつ聞き直すか*を決めるだけです。
- **ストリームの切断は鮮度の問題であって、状態変化では決してありません。**
  最後のスナップショットが陳腐化バナー付きで画面に残ります。切断が「ランが
  停止した」として提示されることはありません。
- **再接続は安価で有界です。** 指数バックオフ（1 秒 → 上限 30 秒）と
  `Last-Event-ID` カーソル; エラーが 1 分を超えて続くと接続は `offline` へ
  移り、これがサブスクリプション自身のスコープに対する有界な 10 秒ポーリング
  フォールバックを有効にする*唯一の*状態です。
- **バスは小さく保たれます。** イベントは固定上限を持つ追記専用のインメモリ
  リングバッファに住み、ハートビートコメントと有界なストリーム窓により、
  アイドルなプロキシや固まったクライアントがワーカーを永久に占有できないように
  なっています。

イベントは自身の `run_id` を持つので、ラン B のイベントがラン A のキャッシュ
エントリに触れることはありません — §4 と同じ隔離性が、キャッシュの書き込み側でも
強制されています。

---

## 6. バックエンドのシーム

サーバーは 4 層であり、各層は 1 つ下の層についてだけ知ることが許されます。

| 層 | モジュール | 責務 |
|---|---|---|
| 転送 | `ari/viz/routes.py`（+ `auth.py`、`server.py`、`health.py`） | ソケットレベルのポリシー: same-origin CORS のエコー、SPA / 静的レスポンスへの `Content-Security-Policy` / `nosniff` / `Referrer-Policy`、非ループバックバインド時の bearer トークン認証、アクセスログ、`/health/live` と `/health/ready`。 |
| API | `ari/viz/v1/router.py` | `(method, path template, handler)` の宣言的な `ROUTES` テーブル 1 枚。ディスパッチごとに `request_id` を発行し、成功ペイロードまたは型付きエラーエンベロープへ通します; `PATCH`/`DELETE` で `If-Match` の楽観的並行制御を強制します; 同じテーブルがコミット済みの `openapi.json` を生成するため、契約がディスパッチャからドリフトすることはありません。 |
| 読み取りモデル | `queries.py`、`results.py`、`rqgm.py`、`logs.py`、`catalogs.py` | チェックポイントディレクトリから DTO への純粋関数。`viz.state` の変更なし、`os.environ` への書き込みなし、ファイル書き込みなし — GET に副作用はありません。 |
| 真実 | `{checkpoint}/…`、および GUI 専用文書のための `{workspace_root}/gui_store/` | コミット済み成果物。 |

このシームの 2 つの性質は侵食されやすいので明示しておく価値があります:

- **`GET` は副作用フリーです。** 読み取りモジュールは、読まれた副作用として状態を
  変更する旧ハンドラのようにサーバーのプロセス追跡状態を参照・剪定するのではなく、
  意図的にファイルシステムからラン状態を再導出します（pid プローブ → ツリーによる
  精緻化 → レビューレポート）。
- **書き込みは狭く明示的です。** GUI 自身の文書 — プロジェクト既定値、ラン
  テンプレート、ランドラフト、起動の冪等性レコード — はグローバルなホーム
  ディレクトリではなく `{workspace_root}/gui_store/` に住み、アトミック書き込みと、
  `ETag` / `If-Match` へ 1:1 対応する整数 `revision` を持ちます。これらは便宜層
  です: 起動時にすべての実効値がチェックポイントへ実体化されるため、CLI がランを
  再現するために `gui_store/` を読む必要は決してありません。

---

## 7. 読み取りモデルは使い捨ての射影

*読み取りモデル*とは、コミット済み成果物から要求時に計算される有界な射影です。
読み取りモデルをすべて削除しても情報は失われませんが、成果物を削除すればそれは
失われます。この非対称性こそが要点です。

ガバナンス読み取りモデルは最も厳格な実例であり、「射影」が実務上何を意味するかを
示します:

- **どの判断も再実行しません。** `ari/viz/v1/rqgm.py` は `ari.rqgm` を決して
  インポートしません。コミット済み成果物（`rqgm_state.json`、
  `rqgm_transitions.jsonl`、`rqgm_audit.jsonl`、`rqgm_registry.json`、ノード
  メトリクスのセンチネル…）をパースし、それらが言っていることを報告します。GUI が
  ガバナンスの評決を捏造できないのは、評決を生むカーネルを一度も実行しないから
  です。
- **コミット済みレコードのみ。** 現在状態は*コミット済み*遷移の replay です。
  途切れた末尾の JSONL 行は無視され、対応する commit を持たない prepare 以降の
  イベントは決して採用されません。rollup スナップショットは、replay と一致するか
  検証するためだけに読まれます。
- **壊れるのではなく縮退する。** 成果物が壊れていても存在しなくても HTTP 200 と
  正直なフラグを返します: 整合性は三値（`true` 検証済み / `false` 破損 / `null`
  ソース不在）で、`degraded_reasons` リストがペイロードに同行します。存在しない
  ソースがクリーンとして描画されることも、ゼロとして描画されることもありません。
- **構造上有界です。** 要約は埋め込みエントリ一覧ではなく件数を持ち、長いログは
  安定オフセット上のカーソルでページングされ、ファイルの*中身*がこれらの
  エンドポイントに乗ることはありません。

ダッシュボードを拡張する人への運用規則はこうです: GUI の表示を変えたいなら射影を
変えること — 成果物を変えてはならず、カーネルが既にコミットした判断を再計算しても
なりません。

---

## 8. capability とキルスイッチ

ダッシュボードは「これは利用できません」を 2 種類に区別し、どちらもエラーでは
ありません。

**サーバー capability — このビルドが提供するもの。** `GET /api/capabilities` が
`gui_v2` フラグ（`ARI_GUI_V2`、既定オン）を報告します。フロントエンドはマウント時
に一度取得し、取得の*失敗*をオンとして扱うため、API の一時的な不調でローカル
ユーザーがフォールバックシェルに取り残されることはありません。

**ラン capability — このランの成果物が支えるもの。** 成果物の存在のみから検出
されます: `rqgm_state.json` があるからランはガバナンス下であり、
`paper_archive_state.json` があるからアーカイブ論文モードです（両者は独立した軸）。
ガバナンスの無いランには、空画面や捏造されたゼロではなく、理由を挙げた
「このランではガバナンスが有効でない — これは capability の状態であってエラーでは
ない」というパネルが表示されます。

刷新された GUI で導入されたリスクのある挙動にはすべて環境変数のキルスイッチが
付属しており、リリースを巻き戻さずに 1 つの決定だけを戻せます。すべて
`scripts/setup/setup_env.sh` に文書化されています:

| 変数 | 既定 | オフにすると戻るもの |
|---|---|---|
| `ARI_GUI_V2` | オン | レガシーシェルのみ（v2 専用ルートは Home へフォールバック） |
| `ARI_GUI_BIND` | ループバック（`127.0.0.1` + `::1`） | より広いバインド。例: 全インタフェースの `::` |
| `ARI_GUI_TOKEN` / `ARI_GUI_AUTH` | 非ループバックバインドでは認証を強制 | 未認証のリモートバインド（例: 認証を行うプロキシの背後） |
| `ARI_GUI_CORS_ANY` | オフ（same-origin エコー） | レガシーの `Access-Control-Allow-Origin: *` ワイルドカード |
| `ARI_GUI_CSP` | オン | CSP / nosniff / Referrer-Policy ヘッダの無いレスポンス |
| `ARI_GUI_CHALLENGES` | オン | 確認チャレンジ無しの直接的な破壊的エンドポイント |
| `ARI_GUI_HEALTH` | オン | ヘルスプローブ導入前のレスポンス（diagnostics エンドポイント無し） |

これらのスイッチが守るセキュリティ既定値は一度述べておく価値があります: サーバー
はループバックのみにバインドするので、既定のローカル体験に認証は不要です; 非
ループバックバインドは bearer トークンを要求することで*フェイルセキュア*します
（未設定なら起動時に生成され一度だけ表示されます）; そして 3 つの破壊的操作
（チェックポイント削除、停止、GPU モニタ停止）はサーバー発行の単回使用確認
チャレンジを要求し、無い場合は `428` を返します。

---

## 関連

- [ダッシュボードガイド](../guides/dashboard.md) — このページが説明する面を
  実際に操作する方法。
- [ARI アーキテクチャ](architecture.md) — ダッシュボードが観測するシステム。
- [研究状態とガバナンス状態](research_and_governance_state.md) — シェルが描画する
  状態モデルと、ぼかしてはならない真実規則。
- [Constitutional ARI-RQGM アーキテクチャ](rqgm_architecture.md) — コミット済み
  成果物を読み取りモデルが射影する対象であるガバナンスカーネル。
- [REST API リファレンス](../reference/rest_api.md) および
  [内部境界](../reference/internal_boundaries.md)。
