---
sources:
  - path: ari-core/ari/viz/api_capabilities.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/app/routeRegistry.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/context/AppContext.tsx
    role: implementation
  - path: ari-core/tests/test_gui_state_facade_freeze.py
    role: test
  - path: ari-core/tests/test_gui_config_shadow_legacy.py
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/appContextScope.test.ts
    role: test
  - path: ari-core/tests/test_setup_env.py
    role: test
  - path: scripts/check_viz_api_schema.py
    role: test
  - path: scripts/check_dashboard_ux.py
    role: test
  - path: scripts/check_bundle_budget.py
    role: test
  - path: scripts/snapshot_contracts.py
    role: test
  - path: scripts/setup/setup_env.sh
    role: config
last_verified: 2026-08-07
---

# GUI カットオーバーランブック

ダッシュボードのリフレッシュは、v2 ワークスペースをレガシー画面の**隣に**出荷します:
両方が同じバンドルに入っており、両方が到達可能で、環境変数 1 つがブラウザに届く
クロームを決めます。このランブックはその取り決めの運用側の半分です — v2 を既定へ
昇格させる方法、その間に何を見るか、どう戻すか、そしてレガシーコードを削除する前に
何が真でなければならないか。

挙動変更そのもの（以前は動いていて今は拒否されるものと、その理由）については
[マイグレーションガイド → GUI リフレッシュ](migration.md#gui-リフレッシュv2-ダッシュボード)
を参照してください。

**スコープに関する注記。** ARI はテレメトリのパイプラインを持ちません。以下の
「シグナル」はすべて、運用者がローカルの面から読むものです — `/api/v1/diagnostics`、
`/health/ready`、チェックポイントの `viz_access.jsonl` と `launch_events.jsonl`、
サーバーの stderr、ブラウザ devtools のネットワークパネル。この展開は計測付きの
カナリアではなく、監督下のドッグフーディングとして扱ってください。

## 1. レバー

すべてのレバーは `ari viz <checkpoint>` の起動時に読まれる環境変数です。変数を設定し
サーバーを再起動するだけで、再ビルドも再デプロイもありません。根拠とともに
`scripts/setup/setup_env.sh` に宣言されています。

| レバー | 既定 | 反転時の正確な効果 |
|---|---|---|
| `ARI_GUI_V2` | オン（`0`/`false` 以外の任意の値） | `GET /api/capabilities` が `gui_v2: false` を報告します; SPA は v2 専用のナビエントリを隠し、v2 専用ルートは Home へフォールバックします。レガシールート、レガシーのハッシュ URL、すべての `/api/*` エンドポイントは無変更です。capabilities の取得が*失敗*した場合は `gui_v2: true` として扱われるため、API の一時的な不調がダッシュボードをフォールバックシェルに閉じ込めることはありません。 |
| `ARI_GUI_BIND` | 未設定 → `127.0.0.1` + `::1` | 明示値はそのホストだけにバインドします: `'::'` はリフレッシュ前の全インタフェースデュアルスタックバインド、`'0.0.0.0'` は IPv4 ワイルドカードを復元します。非ループバックの値は `ARI_GUI_TOKEN` ゲートも起動します。 |
| `ARI_GUI_CORS_ANY` | オフ | `1` は、same-origin のエコーの代わりに、以前それを持っていたすべてのレスポンスへ `Access-Control-Allow-Origin: *` を復元します。 |
| `ARI_GUI_CHALLENGES` | オン | `0` は `POST /api/delete-checkpoint`、`POST /api/stop`、`action=stop` の `POST /api/gpu-monitor` を、サーバー発行の `challenge_id` 無しで実行させます。`POST /api/v1/challenges` エンドポイントは残るので、2 段階クライアントは動き続けます。 |
| `ARI_GUI_CSP` | オン | `0` は SPA の index と `/static/` への `Content-Security-Policy`、`X-Content-Type-Options`、`Referrer-Policy` の送出を止めます。正当な用途は WebSocket ポートをリマップするリバースプロキシで、そうしないと CSP の `connect-src` がツリーストリームをブロックする場合です。 |
| `ARI_GUI_TOKEN` | 未設定 | 非ループバックバインドでは、`/health*` 以外のすべてのリクエストが提示しなければならない bearer トークンです。リモートバインドで未設定の場合、サーバーは起動時に 32 hex のトークンを生成し stderr へ一度だけ出力します — 未認証のリモート起動は存在しません。 |
| `ARI_GUI_AUTH` | オン | `0` はリモートのトークンゲートを完全に無効化します（前段に認証するリバースプロキシがある場合だけが妥当な理由です）。 |
| `ARI_GUI_HEALTH` | オン | `0` は `/health/live` と `/health/ready` を SPA の HTML フォールバックへ戻し、`GET /api/v1/diagnostics` に型付き 404 を返させます。 |

**展開フラグは `ARI_GUI_V2` だけです。** 他の 7 つはセキュリティのキルスイッチで
あり、それぞれが対応する変更の閉じたリスクをちょうど再び開きます。「何かを動かす
ため」にデプロイのプロファイルへ焼き込まないでください; インシデントに使い、理由を
記録し、外してください。組み合わせのポリシー: サポートされるマトリクスは*既定値*、
それに一度に 1 レバー、加えて文書化されたリモートモードの組
（`ARI_GUI_BIND` + `ARI_GUI_TOKEN`）です。それ以外は未検証です。

## 2. カットオーバー前チェックリスト

各行はハードゲートです。ツールチェーンを固定したクリーンなワークツリーで実行して
ください — ベースラインが赤いとこの作業全体が無意味になります。カットオーバーによる
退行と既存の失敗を区別できなくなるからです。

| ゲート | コマンド | 合格条件 |
|---|---|---|
| フロントエンドの型 | `cd ari-core/ari/viz/frontend && npm ci && npm run typecheck` | exit 0 |
| フロントエンドの unit / a11y / contract スイート | `cd ari-core/ari/viz/frontend && npm test` | exit 0 — ルート / ナビのパリティ、シェルの a11y ベースライン、Settings 契約、外部スクリプトガード、ワークフローのリビジョン、Studio の起動、危険操作の各スイートを含む |
| プロダクションビルド | `cd ari-core/ari/viz/frontend && npm run build` | exit 0、出力は `ari-core/ari/viz/static/dist/` |
| バンドル予算 | `python scripts/check_bundle_budget.py --fail-on-regression` | exit 0、純増の違反なし（ビルド後に実行） |
| バックエンド + viz テスト | `python -m pytest ari-core/tests -q` | exit 0 |
| セキュリティ退行スイート | `python -m pytest ari-core/tests -q -k "gui_bind_cors or gui_path_proxy_hardening or gui_confirmation_challenges or gui_csp_headers or gui_remote_auth or gui_secret_readiness or gui_workflow_write_guard"` | exit 0 — MN-2/4/5/6/7/8 の拒否がこれです |
| レガシーファサードの凍結 | `python -m pytest ari-core/tests/test_gui_state_facade_freeze.py -q` | exit 0 — `/state` が増えても減ってもいない |
| 設定 / 起動のシャドウパリティ | `python -m pytest ari-core/tests/test_gui_config_shadow_legacy.py -q` | exit 0 — レガシー Settings の保存 + 起動と新リゾルバが葉ごとに一致し、明示的に許可リスト化された乖離のみ |
| 契約スナップショット | `python scripts/snapshot_contracts.py --surface all --check` | exit 0 — `viz` 面が REST のインベントリとレスポンスキーをピン留め |
| OpenAPI の鮮度 | `python -m ari.viz.v1.openapi`（`ari-core/` から） | exit 0 — コミット済み `ari/viz/v1/openapi.json` がルーターと一致 |
| REST スキーマのドリフト | `python scripts/check_viz_api_schema.py --fail-on-regression` | exit 0、凍結許可リストに対する純増ドリフトなし |
| ダッシュボード UX チェッカ | `python scripts/check_dashboard_ux.py --fail-on-regression` | exit 0、許可リストが増えていない |
| ドキュメントゲート | `python scripts/check_docs_source_sync.py`、`python scripts/docs/check_doc_sources.py`、`python scripts/readme_sync.py --check`、`python -m pytest scripts/tests/ -q` | すべて exit 0 |

続いて、稼働中のサーバー（ループバック既定）でセキュリティ姿勢を証明します:

```bash
ari viz /path/to/checkpoint --port 8765 &

curl -s http://127.0.0.1:8765/health/live                 # {"status":"ok"}
curl -s http://127.0.0.1:8765/health/ready                # status ok|degraded, five checks
curl -si http://127.0.0.1:8765/ | grep -i 'content-security-policy\|nosniff\|referrer-policy'
curl -si -X POST http://127.0.0.1:8765/api/stop -d '{}'   # 428, no process touched
curl -s 'http://127.0.0.1:8765/codefile?path=/etc/passwd' # 404
ss -ltnp | grep 8765                                      # bound to 127.0.0.1 / ::1 only
```

今日の時点で機械的に強制**されていない**ゲートは、手作業でサインオフする必要が
あります:

- **ブラウザの性能指標**（LCP/INP/CLS、ルートのインタラクションレイテンシ）。
  jsdom のテストハーネスではレイアウト・ペイント・入力タイミングを測れず、共有 CI
  ランナーは合否予算にはノイズが多すぎます。バンドル重量*は*強制されています
  （`check_bundle_budget.py`）; ブラウザ側の半分は固定マシン上での手動プロファイル
  であり、リリースの証跡に記録します。
- **クロスブラウザのクリティカルジャーニー。** スイートは vitest/jsdom であり、
  このリポジトリにある Playwright の実行はドキュメント用スクリーンショット取得
  （`npm run capture:screenshots`、ヘッドレス Chromium のみ）だけで、何もアサート
  しません。クリティカルジャーニー（Settings、新規ラン、起動、resume、モニタ、
  ツリー / 結果、ワークフロー、RQGM、セキュリティ）は既定オン化の前に手で歩きます。

## 3. 段階的展開

残るすべてのスライスをこの 3 段階に通します。「スライス」はシェル全体ではなく 1 つの
ルートまたはワークスペースです — フラグのポリシーが意図的にスライス単位なのは、問題が
ダッシュボード全体ではなく 1 画面だけをロールバックさせるためです。

**ステージ 1 — ドッグフード。** メンテナのみが自分のチェックポイントで、フラグを
オンにして使います。フィクスチャではなく本物の成果物を持つ本物のランを使ってください。
見るべき点: 同じランについて v2 ワークスペースはレガシー画面と同じ数値を示すか？
2 つ目のタブの 2 つ目のランは隔離されたままか？ そのスライス自身のテストが緑で、
レガシー / v2 の食い違いが未解決でなくなったら終了です。

**ステージ 2 — オプトイン。** v2 ルートは到達可能で文書化され、レガシールートは
ナビエントリを保ち、利用者が選びます。見るべき点: 実際にどちらを開くか、作業の途中で
フォールバックする人がいるか。大きなチェックポイント、壊れた / 部分的なチェック
ポイント、古い（リフレッシュ前の）チェックポイントで演習したら終了です。

**ステージ 3 — 既定オン。** v2 ルートがルートレジストリの `navReplaces` を通じて
レガシーのナビスロットを引き継ぐので、サイドバーのエントリは同一に見え、書き込まれる
ハッシュだけが変わります。**レガシー URL はどちらのモードでも動き続けます** —
それがパリティの不変条件であり、§5 のロールバックを即座にするものです。ロールバック
レバーを利用可能な状態で少なくとも 1 つのマイナーリリースにわたり既定オンで走ったら
終了です。

現在のプログラムの位置: `ARI_GUI_V2` は**既定オン**で出荷されています; Projects、
Overview、Governance、ConfigBrowser、Studio は独自のナビエントリを持ちます;
TreeV2、IdeasV2、ResultsV2 は `navReplaces` により Tree、Idea、Results のスロットを
引き継ぎました; Settings、Wizard、Monitor、Workflow、Home、Experiments、PaperBench は
今もレガシー画面とレガシーのナビエントリのままです。Settings → Studio と
Wizard → Studio の起動が、まだステージ 1–3 を歩く必要のあるスライスです。

どのステージでも見るべきシグナル（すべてローカルで読めます）:

| シグナル | 読む場所 |
|---|---|
| ルートの成功 / エラー、スキーマ不一致、アダプタ不一致 | ブラウザ devtools のネットワークパネル; 型付き `/api/v1` エラーエンベロープは `viz_access.jsonl` にも現れる `request_id` を持つ |
| 設定検証の失敗カテゴリ、保存衝突率 | ドラフトの `validate` レスポンス（`details.errors` のパス）とワークフローの 409 衝突バナー |
| 起動の受理 / 開始 / 失敗、冪等性の衝突 | `{checkpoint}/launch_events.jsonl`（`draft → validating → accepted → spawned` / `failed`）と `{workspace_root}/gui_store/launches/` |
| SSE の再接続 / フォールバック、射影の遅れ、陳腐化したビュー | `GET /api/v1/diagnostics`（`sse.subscribers`、`sse.buffer_len`、`watcher.last_scan_age_s`）と `GET /health/ready`（失敗したチェック名を挙げる `degraded`） |
| レガシールート / レガシー API のフォールバック利用 | `viz_access.jsonl` のリクエストパス — スライスが既定オンになった後のレガシー `/api/*` と `/state` へのヒット |
| バンドルサイズ | `python scripts/check_bundle_budget.py`（チャンクごとの gzip 対クラス予算） |
| ブラウザ性能のパーセンタイル | 固定の参照マシン上での手動プロファイル（CI 強制ではない） |

## 4. 停止とロールバックの条件

以下のいずれかが起きたら展開を止める — あるいは既に既定オンのスライスをロールバック
してください。この一覧はリリースゲートです; 展開を続けながら 1 行をフォローアップ
チケットへ緩めてはなりません。

- **ラン間のデータ混在、シークレットの露出、未認可の変更。** いずれもスライスの
  ロールバックではなく即時の全面停止です: §5.3 へ進んでください。
- **設定または起動のシャドウ不一致が閾値を超える。** レガシーの保存 + 起動経路と
  新リゾルバは葉ごとに一致しなければならず、明示的に許可リスト化された乖離のみが
  許されます; 新たな乖離は展開を止めます。
- **スコア系譜がソースイベントと食い違う。** ガバナンス読み取りモデルは何も再導出
  しません — 表示された系譜が `rqgm_transitions.jsonl` / `rqgm_audit.jsonl` と
  一致しないなら、そのビューが誤りであり停止します。
- **古いチェックポイントまたは `simple_bfts` の同一性の退行。** リフレッシュ前の
  チェックポイントは変わらず開けなければならず、`simple_bfts` ランはリフレッシュ前の
  ARI とバイト単位で同一のままでなければなりません。
- **クリティカルジャーニー、a11y、性能のハードゲート失敗。** §2 の赤いゲートは
  すべて（手動サインオフのものも含む）。

## 5. 層ごとのロールバック手順

症状を直す**最も狭い**層をロールバックしてください。稼働中の実験に触れる必要が
あるのは §5.3 だけです。

### 5.1 フラグ層（数秒、再ビルド不要）

```bash
export ARI_GUI_V2=0
# restart: ari viz /path/to/checkpoint --port 8765
```

`GET /api/capabilities` は `gui_v2: false` を報告するようになり、サイドバーは v2
エントリを落とし、v2 専用ルートは Home へフォールバックし、レガシー画面が自分の
スロットへ戻ります。すべてのレガシーハッシュ URL とすべての `/api/*` エンドポイントは
元から動いていたので、他は何も変わりません。v2 が書いたドラフト、テンプレート、
`resolved_config.json` はディスク上に残り、単にレガシー画面が読まないだけです。

### 5.2 バンドル層（数分）

問題がフラグではなくビルド済みアセットにある場合は、以前リリースした
`ari-core/ari/viz/static/dist/` ツリーを復元して（SPA の index と `/static/` はそこ
から直接配信されます）再起動してください。既知の良好なコミットから切り直す必要が
あれば、`ari-core/ari/viz/frontend` で `npm ci && npm run build` を実行します。以前の
バンドルは少なくとも 1 マイナーリリースの間保持してください — その保持期間*こそが*
ロールバックの窓です。

### 5.3 セキュリティレバー（インシデント経路）

トリガが UI の欠陥ではなく露出である場合に使います。順に:

1. **ループバックへ再バインド。** `ARI_GUI_BIND`（および `ARI_GUI_CORS_ANY`）を解除
   して再起動します。サーバーは `127.0.0.1` + `::1` のみで待ち受け、自身のオリジンに
   対してのみ CORS をエコーします。SSH のローカルフォワードで再度到達してください。
2. **トークンを失効させる。** `ARI_GUI_TOKEN` を変更または解除して再起動します:
   以前発行されたトークンはすべて直ちに動かなくなります（変数未設定のリモート
   バインドは新しいトークンを発行し stderr へ一度出力します）。運用者にはブラウザの
   `localStorage` キー `ari_gui_token` をクリアするよう伝えてください。アクセスログは
   `token=` を `***` へ redact するため、古いトークンを `viz_access.jsonl` から
   復元することはできません。
3. **プロセスを停止する。** `POST /api/stop` には `POST /api/v1/challenges` からの
   チャレンジ（`action: "stop-all"`、`target: "*"`）が必要です; 2 段階であること自体
   が要点なので、ここで `ARI_GUI_CHALLENGES=0` に手を伸ばさないでください。帯域外で
   `ari viz` プロセス自体も停止してください — GUI から起動されたランは別個の
   `python3 -m ari.cli run` サブプロセスでありサーバーより長生きするので、インシデントが
   求めるなら明示的に停止してください。
4. 誰かを戻す前に **§2 の姿勢チェックを再実行**してください。

### 5.4 データの安全性

取り消すべきものはありません。リフレッシュが書くものはすべて追加的で
（`{checkpoint}/resolved_config.json`、`{checkpoint}/launch_events.jsonl`、
`{workspace_root}/gui_store/`（ドラフト、テンプレート、起動の主張））、古い ARI は
それらをすべて無視します。チェックポイントがその場で書き換えられることは無いので、
ロールバックにダウングレード用マイグレーションが必要になることはありません。
ロールバック演習では、実行中のラン、開いているドラフト、保存済み設定、編集済み
ワークフロー、RQGM ビューがすべてフラグ反転を生き延びることを確認してください。

## 6. レガシーの撤去

**フラグの衛生。** 展開フラグは予定表であって安住の地ではなく、この節がその予定表の
終点です。`ARI_GUI_V2` はこのプログラム唯一の展開フラグ（§1）であり、それが生きて
いる間、置き換え対象の画面は新旧両世代が同じバンドルに載ります — バグ面が二重、
テスト面が二重、そして「利用者はどちらを見ていたのか？」という曖昧さがあらゆる報告に
残ります。したがって展開フラグは、退役の条件を先に固めたうえで導入します — 名前の
ある owner、ロールバックレバー、そして撤去を約束するゲートまたはリリース — そして
それらをフラグを読む module の docstring に宣言します。`ARI_GUI_V2` は
`ari-core/ari/viz/api_capabilities.py` でそれを行っています: owner、既定、
ロールバックレバー、撤去ゲート。その期限は日付ではなくゲートです; 同 module と
`docs/reference/environment_variables.md` はそのゲートを `G6` と呼びますが、これは
レガシーの撤去 — つまりこの節のことです。それを越えて生き残る展開フラグはありません:
下の表を終えたとき、フラグは守っていたシェルと一緒に削除され、ゲートを満たしたのに
まだ出荷され続けているフラグは、設定項目ではなく分類すべき欠陥です。ここまでは機械
検査されていません。自動化されているのはもっと狭い部分だけです: ファーストパーティの
Python が読むすべての環境変数は `scripts/setup/setup_env.sh` に宣言されている必要が
あり（`ari-core/tests/test_setup_env.py::test_setup_env_covers_all_source_env_vars`）、
これは新しいフラグを可視にすることを強制しますが、その owner や期限については何も
言いません。§1 の 7 つのセキュリティキルスイッチは別のルールに従う別の道具であり
— インシデント用途のみ — 以下はそれらの撤去を予定していません。

撤去は既定オンとは別の判断であり、一方向です。以下のすべてが成り立つまで、何も削除
してはなりません:

- 置き換える v2 スライスが、ロールバックレバーを利用可能な状態で少なくとも 1 つの
  マイナーリリースにわたり既定オンであり、ロールバック演習に合格していること;
- 利用実績がレガシー面の未使用を示していること（観測期間中の `viz_access.jsonl` に、
  置き換えられた画面のレガシールートやレガシー `/api/*` へのヒットが無いこと）;
- §7 の互換性マトリクスを再実行して緑であること;
- 撤去（または明示的な保持）が ADR として記録され、公開 API の撤去は
  `CONTRIBUTING.md` と `docs/about/release_policy.md` の非推奨化プログラムに従うこと
  — 破壊的な撤去ならメジャーリリース行きです。

この順序で撤去してください。順序は依存の連鎖です: 各項目の消費側が先に消えている
必要があります。

| # | 撤去対象 | 紐づくゲート |
|---|---|---|
| 1 | **レガシーページ** — Settings、Wizard、Tree、Idea、Results、Workflow の各画面を 1 つずつ | 置き換えるワークスペース自身の capability / a11y / 性能ゲートが緑であり、ルート–ナビのパリティテストとダッシュボード UX チェッカの隠しルート許可リストが同じ変更で再凍結されていること |
| 2 | **AppContext のリモート状態** — `context/AppContext.tsx`、すなわち 5 秒周期の `/state` ポーリング、ツリー WebSocket のミラー、グローバルなアクティブチェックポイント | 上記のレガシーページがすべて消えており、構造ガード `src/__tests__/appContextScope.test.ts` が例外エントリ**ゼロ**で通ること（文書化された唯一の例外である IdeasV2 の研究ゴールカードは、先に `/api/v1` から取り直す必要があります） |
| 3 | **`/state` ファサード** — `routes.py` の `/state` 分岐と `services/state_service.build_app_state` | AppContext が消えていること; `test_gui_state_facade_freeze.py` は同じ変更で退役させ（その存在意義はこの削除*まで*の増加を禁じることです）、`viz` の契約スナップショットを再生成すること |
| 4 | **ポート + 1 の WebSocket** — `ws_serve` サーバー、`websocket.py`、`hooks/useWebSocket.ts` | すべてのリアルタイム消費側が代わりに `GET /api/v1/events/stream` を読むこと; そのときはじめて CSP の `connect-src` から `ws://`/`wss://` のソースを落とせます。この許可はこのソケットのためだけに存在するからです |
| 5 | **重複した定数と CSS** — レガシーのルート / ナビのリテラルと重複したデザイントークン | ルートレジストリがルート、ナビ、エイリアスの単一のソースであること（パリティテストが緑）、およびレガシーページが重複物をインポートしていないこと |

各撤去の後に契約スナップショットを再生成し
（`python scripts/snapshot_contracts.py --surface viz --update`）、§2 のチェックリスト
全体を再実行してください。許可リストを*増やす*必要がある撤去は、まだ準備できて
いません。

## 7. 互換性マトリクス

§6 のいかなる撤去の前にもこのマトリクスを再実行し、結果をリリースの証跡に記録して
ください。プログラムがカットオーバーゲートとして使うのと同じマトリクスです:

- 新規インストール × アップグレード;
- レガシー UI × v2 UI、それぞれレガシー `/api/*` と正準 `/api/v1` に対して;
- `simple_bfts` × RQGM 探索のオン / オフ × 論文モードのオン / オフ;
- 新規ラン × resume × クローン;
- laptop × HPC プロファイル × cloud プロファイル;
- ローカルループバック × SSH トンネル × HPC リバースプロキシ;
- 小 × 中 × 大 × 壊れたチェックポイント;
- 英語 × 日本語 × 中国語。

## 関連

- [マイグレーションガイド → GUI リフレッシュ](migration.md#gui-リフレッシュv2-ダッシュボード)
  — 利用者から見えるすべての変更の前後と、そのロールバックレバー。
- [HPC セットアップガイド](hpc_setup.md) — トンネリングとリモート運用。
- [トラブルシューティング](troubleshooting.md) — 実行時の失敗とその対処。
- `scripts/setup/setup_env.sh` — セットアップスクリプトが `.env` へ書き込む形で、
  根拠とともに宣言された `ARI_GUI_*` レバー。
