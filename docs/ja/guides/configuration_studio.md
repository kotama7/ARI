---
sources:
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: ari-core/ari/config/resolver.py
    role: implementation
  - path: ari-core/ari/viz/v1/config_api.py
    role: implementation
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/viz/v1/secrets.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/v1/catalogs.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigBrowser/ConfigBrowserPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/ConfigStudioPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/LaunchPanel.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/ExecutionSection.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/modeIntents.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/SecretField.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/StudioPickers.tsx
    role: implementation
  - path: ari-core/tests/test_gui_config_resolver.py
    role: test
  - path: ari-core/tests/test_gui_v1_launch.py
    role: test
  - path: ari-core/tests/test_gui_v1_mode_selection.py
    role: test
  - path: ari-core/tests/test_gui_secret_readiness.py
    role: test
last_verified: 2026-07-27
---

# Configuration Studio ガイド

2 つの画面が 1 つの正準フィールドレジストリを共有します:

- **Config**（`#/config?run=`）— 読み取り専用。*このランは実際にどの設定を使い、
  各値はどこから来たのか？*
- **Studio**（`#/studio`）— 編集用の拡張。*次のランは何を使うべきか？*
  プロジェクト既定値、ランテンプレート、ランドラフト、起動フロー。

どちらも v2 ワークスペースなので `gui_v2` capability が必要です
（[ダッシュボードガイド](dashboard.md)を参照）。どちらも既に走っているランを
編集することはできません: チェックポイントの設定は事後的に説明されるだけで、
書き換えられることはありません。

## フィールドレジストリ

両画面のすべては、宣言済み `ARIConfig` の葉の機械可読なインベントリに、手書きの
メタデータオーバーレイをマージしたもの 1 つから生成されます。現在それは
**145 葉、メタデータ被覆率 100 %** です — レジストリのビルドは、メタデータの無い
フィールドを出荷するのではなく例外を送出するため、新しい設定フィールドが
category・level・scope・sensitivity・mutability 無しに黙って現れることはできません。

現在のカテゴリ: Governance (97)、Proposal routing (14)、Search (BFTS) (14)、
Infrastructure (5)、Models (5)、Evaluation (4)、Execution mode (4)、Skills (2)。

レジストリは `GET /api/v1/config/schema` が配信します。運ぶのは**メタデータのみ**
であり実効値は決して含まれず、`secret_reference` フィールドはデフォルト値すら
持ちません。

## 実効設定を調べる（`#/config?run=`）

ランを**指定して**開くとそのチェックポイントの解決済みマニフェストが得られます;
`?run=` **無しで**開くと、正直にスキーマブラウザ（デフォルト値の表示）へ縮退します
（「ランが選択されていません — デフォルト値付きの設定スキーマを表示しています」）。

各行はドット区切りパス、実効値、**来歴ソース**バッジ、**可変性**バッジ、該当時の
低確信度マーカー、そして `applies_when` の注記を表示します。検索ボックスがパスや
カテゴリで絞り込むので、145 フィールドすべてが発見可能なままです。リゾルバの警告は
専用パネルに逐語で列挙されます — 黙って捨てられるものはありません。

![1 ランの Config ブラウザ: リゾルバ警告パネル、フィールド件数の隣のフィルタボックス、カテゴリごとのテーブル（ドット区切りパス、実効値、来歴ソースバッジ、可変性バッジ）。`llm.api_key` 行は「secret (reference only)」と表示される](../../assets/images/ja/dashboard_config.png)

フィルタボックス横のカウンタは 145 より大きくなることがあります。解決済み
マニフェストが持つ葉のうちレジストリが知らないものも、**Other** にまとめて
表示されるためです — レジストリのメタデータが無いというだけでマニフェストの
パスが捨てられることはありません。

マニフェスト自体は `GET /api/v1/runs/{run_id}/resolved-config` から来て、
`legacy-compatible-1` リゾルバが生成します。これは命令的な CLI 連鎖が生んだであろう
ものを、実際には実行せずに再構成します。

### 来歴バッジ（既存チェックポイント）

リゾルバは以下の層をこの順で replay し、バッジは勝った層を示します:

| バッジ | 層 | 確信度 |
|---|---|---|
| `default` | pydantic モデルのデフォルト | 高 |
| `workflow` | `{checkpoint}/workflow.yaml` | 高 |
| `launch_config` | `{checkpoint}/launch_config.json` | 高 |
| `env` | **現在の**プロセス環境。文書化された `ARI_*` 変数のみ | **低** |
| `checkpoint_state` | `{checkpoint}/rqgm_state.json` に永続化されたモード | 高 |

`env` が**低確信度**とされるのは意図的です: それは*今*の環境を反映するもので、
ランが起動された時点の環境とは限りません。低確信度マーカーは「この帰属は再構成
されたものであり、仮説として扱え」という意味です。

新規ラン用のプレビュー（Studio の起動フローが使用）は、独自のバッジを持つ別の
より長いスタックを使います: `default` → `workflow`（同梱） → `profile` →
`project` → `template` → `draft` → `env`。

### 可変性バッジ

| バッジ | 意味 |
|---|---|
| `draft` | ランがまだドラフトである間は自由に編集可能 |
| `new_run_only` | ラン開始後は固定。*次の*ランのために変更する |
| `resume_mutable` | 既存ランの resume 時に変更してよい |
| `read_only` | どのスコープでも設定 API から受け付けない |

起動前は、新規ランプレビューが `read_only` 以外のすべてのフィールドを可変と報告
します — `new_run_only` が効くのはランが存在してからです。

### ブラウザ上のシークレット

`secret_reference` の行は **`secret (reference only)`** というリテラルテキストを
描画します。開示する値も、開示するトグルも存在しません: バックエンドはシークレット
の葉を `values`、`provenance`、マニフェストのダイジェストから完全に除外し、
設定済み / 未設定のフラグとしてのみ提示します。ダイジェストは redact 済みの正準値に
対する `sha256:` なので、安定でありリークもしません。

`resolved_at` は `now()` ではなくソースファイルの mtime から導出されるため、変更の
無い同一チェックポイントを何度 GET してもバイト単位で安定です。

## Studio での編集（`#/studio`）

Studio は同じレジストリをフォームとして描画したものです。コントロールはフィールド
ごとの手書きではなくメタデータから導出されます: `enum` → セレクト、`bool` →
スイッチ、`int`/`float` → 数値入力、`str` → テキスト入力、`secret_reference` →
書き込み専用シークレットコントロール、複合型（リスト、辞書、ネストしたモデル）→
理由を表示した明示的に**無効化された**入力（「複合フィールド — `workflow.yaml`
で編集してください」）。利用できないコントロールは常に理由を述べ、黙って隠される
ことはありません。

![Studio: 上部のスコープタブストリップ、テンプレートとドラフトの作成コントロール、左のカテゴリ一覧、右に生成されたフォーム（セレクト、テキスト入力、名前ピッカーと「configured (repo_env)」バッジとパスワード欄を備えた書き込み専用シークレットコントロール）。フッタには Save changes / Discard edits、未保存編集の状態、文書のリビジョンが並ぶ](../../assets/images/ja/dashboard_studio.png)

モデル / プロバイダの候補はサーバーのカタログ
（`GET /api/v1/config/catalogs/models`）から来ます — フロントエンドにモデルの定数は
ありません。

各フィールド行はステータスバッジも持ちます: `edited`（未保存のローカル変更）、
`saved`（保存済み文書に存在）、`default`（何も保存されていない — 下の層へ落ちる）。

### 3 つのスコープ

スコープバーが編集対象の文書を切り替え、ハッシュがそれを記録します:

| スコープ | ハッシュ | 文書 | エンドポイント |
|---|---|---|---|
| プロジェクト既定値 | `#/studio` | 単一の `default` プロジェクト設定 | `GET/PATCH /api/v1/projects/default/config` |
| ランテンプレート | `#/studio?template=<id>` | 再利用可能な名前付きテンプレート | `GET/POST /api/v1/run-templates`、`GET/PATCH/DELETE .../{id}` |
| ランドラフト | `#/studio?draft=<id>` | 保留中の 1 ラン | `POST /api/v1/run-drafts`、`GET/PATCH .../{id}` |

テンプレートは小文字の `template-id` と表示名を与えて作成します; ドラフトは任意で
テンプレート*から*、任意で**ゴール**（自由テキスト）付きで作成します。ゴールは
文書のフィールドであって設定パスではありません — `values` に乗ることはなく、起動時
に `{checkpoint}/experiment.md` として実体化されます。

文書を切り替えると未保存の編集バッファは破棄され結果バナーもクリアされるので、
ある文書の編集が別の文書へ漏れることはありません。

### 文書の保存場所

3 種類すべてがサーバー側の `{workspace_root}/gui_store/` — `checkpoints/` の兄弟 —
の下に保存されます:

```text
{workspace_root}/gui_store/
├── project_config.json
├── run_templates/{template_id}.json
├── run_drafts/{draft_id}.json
└── launches/{idempotency_key}.json
```

これは**GUI 専用の便宜層**です。`~/.ari` のようなグローバルディレクトリは存在せず、
テンプレートはチェックポイント削除後も残り、CLI / `simple_bfts` の経路はこれを一切
読みません — 起動時にすべての実効値が従来どおりチェックポイントへ実体化されます。
書き込みはアトミック（同一ディレクトリの一時ファイル + `fsync` + `os.replace`）で、
所有者のみの権限（ファイル `0600`、ディレクトリ `0700`）です。

### If-Match の衝突

すべての文書は整数の `revision` を持ち、すべての変更操作はそれをエコーする必要が
あります:

```http
PATCH /api/v1/projects/default/config
If-Match: "3"
Content-Type: application/json

{"values": {"bfts.max_total_nodes": 40}}
```

- **`If-Match` 無し** → `400 invalid_request`
  （*mutations require the `If-Match: "<revision>"` header*）。
- **古い `If-Match`** → `409 revision_conflict`。
- `If-Match: "0"` は「この文書はまだ存在してはならない」（作成）を意味します。

UI では 409 が**リビジョン衝突**パネルを出します:

> この文書は読み込み後にサーバー上で変更されました。Reload で最新リビジョンを
> 取得してください — 未保存の編集はローカルに保持されます。  [Reload]

**取るべき行動:** Reload をクリックします。文書を現在のリビジョンで取り直し、
保留中の編集はローカルバッファに残るため、黙って破棄されることも黙って上書き
されることもありません。まだ必要な編集を再適用して保存し直してください。これは
旧来の盲目的上書きオートセーブに対する意図的な置き換えです — サーバーは古い書き込み
を勝たせません。

### パス単位の検証エラー

PATCH のボディはフラットな `{"dotted.path": value}` の部分更新であり、何かが書かれる
前にレジストリに対して検証されます。拒否は `400` として返り、問題のパスが
`details.errors` に入り、UI は**検証エラー**一覧として描画します。`reason` の語彙は
閉じています:

| `reason` | 意味 |
|---|---|
| `unknown_path` | レジストリのパスではない |
| `invalid_type` | 型が違う（`expected` にレジストリの `value_type` が入る） |
| `invalid_enum` | 許可された値でない（`expected` に許可集合が入る） |
| `read_only` | すべてのスコープで拒否 |
| `secret_reference` | シークレットは設定 API を決して通らない |
| `not_project_scope` | scope が `project` でない `new_run_only` フィールドをプロジェクト設定へパッチした |

`new_run_only` フィールドはテンプレートとドラフトでは*受け付けられます* — 将来の
ランを設定するものだからです。

## シークレットの扱い

シークレットは GUI を通じて**常に書き込み専用**です。

- **値ではなく readiness。** `GET /api/v1/secrets/status` は固定の許可リストに載る
  名前について、`configured`（bool）、`source_class`（`project_env` = アクティブ
  チェックポイントの `.env`、`repo_env` = `ARI/.env` または `ari-core/.env`、
  `user_env` = `~/.env`、`process_env` = プロセス環境のフォールバック）、および
  `last_updated`（ソースファイルの mtime）を返します。レスポンス DTO に値の
  フィールドが無いので、シークレットをエコーバックすることは構造的に不可能です。
- **許可リスト**はコードから列挙されたもので、でっち上げではありません:
  `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GOOGLE_API_KEY`、`GEMINI_API_KEY`、
  `SEMANTIC_SCHOLAR_API_KEY`、`LETTA_API_KEY`、`ZENODO_TOKEN`、
  `ARI_REGISTRY_TOKEN`。これ以外の名前は 404 です。
- **書き込み。** `PUT /api/v1/secrets/{secret_id}` は値を受け取り、堅牢化された
  `.env` ライタへ委譲します: 同一ディレクトリのアトミックな一時ファイル + `fsync`
  + `os.replace`、`0600` 権限、加えてライブの `os.environ` エクスポート。レスポンス
  は書き込み後の **readiness 行**であり、値ではありません。
- **フォーム上では**、シークレットコントロールが名前ピッカー（既定はモデルカタログ
  由来のアクティブなプロバイダの env キー）、`configured` / `not configured` バッジ、
  パスワード入力、そして常設の注記
  *「書き込み専用: 値はサーバーへ送られ、ここから読み戻すことはできません。」*
  を表示します。PUT が解決した瞬間に入力はクリアされます。

**値が実際に行く先。** 2 箇所であり、正確に述べる価値があります:

1. **リポジトリルートの `.env`**（`{ARI}/.env`）。これは*固定の*書き込み先です —
   ライタは最初に一致する `NAME=` 行をその場で置換し、無ければ追記します。
   readiness の連鎖には**従わず**、アクティブチェックポイントへは書きません。
2. **稼働中サーバーの `os.environ`**（ライブでエクスポート）。

値が `project_config.json`、ランテンプレート、ランドラフト、解決済みマニフェスト、
あるいは何らかのログへ書き込まれることは決してありません。

GUI からの起動は `os.environ` から始まり、`.env` ファイルは空欄を埋めることしか
できないため、いま設定したシークレットは GUI から起動する次のランに直ちに効きます。

知っておくべき唯一の非対称性: **readiness は連鎖を読み、書き込みは 1 ファイルを
狙う**という点です。連鎖はアクティブチェックポイントの `.env`（`project_env`）→
リポジトリの `.env`（`repo_env`）→ `~/.env`（`user_env`）→ プロセス環境
（`process_env`）です。したがってチェックポイントローカルの `.env` が同じ名前を
既に定義していると、新しい値を書いた後も readiness は勝者のソースとして
`project_env` を報告し続けます。`source_class` バッジが教えるのは勝っている
*ディスク上の*定義の場所であって、直近の書き込みが着地した場所ではありません。
それが望ましくないなら、特に GUI プロセスの外で CLI を走らせる前に、チェック
ポイントローカルの定義を編集または削除してください。

## 起動フロー

起動パネルは**ドラフトスコープ**でのみ表示されます（`#/studio?draft=<id>`）。
ステッパーは Goal → Review → Launch です。

### 1. 解決と検証

**[Resolve & validate]** はドラフトに対して両方の呼び出しを発行します（任意の実行
プロファイル `laptop` / `hpc` / `cloud` 付き）:

- `POST /api/v1/run-drafts/{draft_id}/resolve-config` — 新規ランプレビューの
  マニフェスト;
- `POST /api/v1/run-drafts/{draft_id}/validate` — `{valid, errors, warnings}`。

パネルはその後、**デフォルトからの変更点**（来歴が同梱デフォルト層でないすべての葉。
Config ブラウザと同一のバッジマップを使うため 2 つの面が乖離しません）、ドラフトに
帰属する検証エラー、リゾルバの警告（逐語）、シークレットの readiness 行、そして
ガバナンスが読み取り専用である旨の注記を描画します。

拒否されたオーバーライドが黙って捨てられることはありません。ある層が pydantic の
拒む値を供給した場合、リゾルバは最後の妥当な層へ戻り、その葉の来歴へ
`rejected_override` の説明を注記し、
*「`<layer>` override rejected for `<path>`: … — keeping the `<layer>` value」*
の形の警告を出します。

`ari.mode` / `rqgm.enabled`（または `paper.mode` / `rqgm.paper.enabled`）の
インターロック不一致は、*リゾルバ*の中では同じ経路をたどります — 警告して
フォールバックし、マニフェストには**実効**モードが表示されます — が、警告の
ままでは終わりません。`/validate` はその残存警告を `interlock_mismatch` エラーへ
変え、起動はフォールバックしたランを黙って始めるのではなく拒否します。これが、
Studio 自身では壊せない組を捕まえる仕組みです: 例えばドラフトが `ari_rqgm` を
要求している一方で、サーバーの環境が `ARI_RQGM_ENABLED=0` を持っている場合です。

### 2. 不変のレビュー

レビューブロックは読み取り専用の要約 — 表示名、run id の意図（*accept 時にサーバー
が発行するものであり、チェックポイントから推測しません*）、プロファイル、
**解決後の**実行モードと論文モード、変更フィールド数、設定ダイジェスト — であり、
明示的なチェックボックスの背後にあります:

> I reviewed this immutable summary — launch exactly this configuration.

チェックを入れると**ちょうど 1 つの冪等性キー**（`crypto.randomUUID()`）が発行され、
これが「この承認」の単位になります。レビューを無効化するもの — ドラフトの編集と
保存（リビジョン更新）、ドラフトの切り替え、プロファイルや表示名の変更 — はすべて
承認とキーの両方をクリアします。新しい承認は新しい意図です。

この要約に並ぶモードの行は、プレビューマニフェスト由来の**解決後**の値であり、
生の選択内容ではありません。要求したモードが採用されなかった場合は、別途
*「Requested mode was not applied」*のパネルが、要求値・解決値・リゾルバの警告を
逐語で示します — ガバナンス下でないランをガバナンス下だと思い込んだまま起動して
しまうことは決してありません。

**[Launch run]** は、ドラフトが検証をクリーンに通り、**かつ**ドラフトにゴールがあり、
**かつ**レビューが確認済みのときにのみ有効になります。

### 3. 起動と、その保証

`POST /api/v1/runs`（`{draft_id, display_name?, profile?, idempotency_key?}`）は
厳密にこの順で実行されます:

1. **冪等な replay チェック。** 既にディスク上にあるキーは、記録済みの `run_id` と
   `idempotent_replay: true` へショートサーキットします — 何も起動されません。
2. **検証優先。** リゾルバのプレビュー + 共有のドラフト検証 + 起動時のみの 2 つの
   チェック。失敗はパス単位の `details.errors` を伴う `400` を返し、**ファイル
   システムの変更を一切行いません。** チェックポイントディレクトリも
   `experiment.md` も、片付けるべき中途半端なランも作られません。検証失敗は本当に
   no-op です。
3. **サーバー発行の同一性。** `run_id = <UTC YYYYMMDDHHMMSS>_<slug>-<6 hex>`。
   slug は表示専用かつ決定論的です — レスポンス前に LLM 呼び出しもスケジューラへの
   問い合わせも起きません。
4. **冪等性の主張。** create-only の `gui_store/launches/{key}.json` の書き込みは
   **どのディレクトリが存在するよりも前に**行われるため、同じキーで競合する 2 つの
   POST でも起動されるサブプロセスはちょうど 1 つです。
5. **実体化してから起動。** `experiment.md`（ゴールから）、`workflow.yaml`（同梱
   ファイルの copy-on-write シード。加えて、デフォルト以外のモードが選択された
   場合は最小限の `ari:` / `rqgm:` / `paper:` ブロック）、`launch_config.json`、
   `resolved_config.json`（解決済みマニフェストが起動時に実体になる）、
   `launch_events.jsonl`
   （`draft → validating → accepted → spawned`; 起動失敗は `failed` を記録し主張を
   解放します）。その後、レガシー起動と同じ `python3 -m ari.cli run …` サブプロセス
   を `ARI_CHECKPOINT_DIR` 固定で起動します（そして 4 つの `ARI_*` モード変数は、
   デフォルト以外のモードが選択された場合にのみ渡されます）。
6. **レスポンス、そしてリダイレクト。** `{run_id, status_url, checkpoint_path,
   accepted, idempotent_replay}` — レスポンスはサブプロセスを待ちません。UI は正準の
   `#/overview?run=<run_id>` へ遷移します; サーバー発行の id を使い、mtime で最新の
   チェックポイントを推測することはありません。

グローバルなアクティブチェックポイントは、起動によって**意図的に切り替えられません**。

**ダブルクリック安全性。** ボタンは送信中は無効化され、フレーム内の ref ガードが
2 回目の送信をブロックします; 起動失敗後の再試行は**同じ**キーを再利用するため、
再試行は replay になるだけで 2 つ目のランを起動することはあり得ません。

レガシーの `POST /api/launch` は変更されておらず今も並走しています; レガシー
ウィザード（`#/new`）は今もそれを使います。

## 実行モードは選択可能、ガバナンスのチューニングは今も設定ファイル専用

**ADR-09** 以降、Studio の *Execution* セクションはもはや 1 つの無効化グループでは
ありません。直交する意図ごとに 1 つずつ、**ちょうど 2 つ**のコントロールを提供し、
それ以外はすべて読み取り専用のままにします:

| コントロール | 書き込む設定キー | 値 |
|---|---|---|
| **Execution mode** | `ari.mode` **と** `rqgm.enabled` | `simple_bfts`（デフォルト）/ `ari_rqgm` |
| **Paper mode** | `paper.mode` **と** `rqgm.paper.enabled` | `linear`（デフォルト）/ `rqgm_archive` |

**各コントロールは組の両方のキーを書きます。** モードとそのインターロックは 1 つの
意図なので、1 回の選択は両方のキーを載せた 1 回の PATCH になります — ランタイムが
黙って縮退するような片側だけの文書を GUI が構成することはできません。もし文書が
片側だけを持ち相方を欠く状態になったら（手作りの API 呼び出しや、テンプレートの
組の片方のキーだけを上書きしたドラフトなど）、サーバーはテンプレートの
create/PATCH、ドラフトの create/PATCH、**そして**起動時に、型付きの 400
`mode_interlock_mismatch` で拒否します。この検査は*マージ後*の文書の値に対して
走るため、最終的に整合する 2 段階の編集は問題ありません。

**新規ラン専用。** どちらの葉も `mutability: new_run_only` です — 選択はこれから
起動しようとしているランに適用されます。resume には手を触れません: 再開されたラン
は `{checkpoint}/rqgm_state.json` に記録されたモードを取り、それが設定と env に
優先します（ダウングレードのみ）。Studio の中に、既に存在するランを狙い直せる
ものは何もありません。

**プロジェクトスコープは今もそれらを拒否します。** この 4 葉は `scope: run` なので、
プロジェクト既定値の文書は `not_project_scope` でそれらを拒否します; そのスコープ
では 2 つのセレクトが無効化され、理由が表示されます。モードはランテンプレートか
ランドラフトで選んでください。

**残る 97 のガバナンス葉は読み取り専用のままです。** `Execution mode` カテゴリと
`rqgm.*` ツリーのその他すべてのパス（epoch、kernel、governance、adversarial、
予算、論文アーカイブのチューニング）は、折りたたまれた読み取り専用グループに
**実効値付きで**描画され — 何が適用されるかを正確に見られます — 次の注記が
添えられます:

> **RQGM governance parameters (read-only)** — Effective values shown for
> reference. Governance tuning parameters come from configuration files in
> this release — they are not editable from the GUI; edit `workflow.yaml` to
> change them. Selecting a mode above is not a governance mutation.

このロックは装飾ではなくエンドツーエンドです: 起動エンドポイントはロック集合を
レジストリから再計算し（`Execution mode` カテゴリ ∪ `rqgm.*` から選択可能な 4 葉を
**引いたもの** — 現在 97 パス）、自身の `values` にそれらのパスを持つドラフトを
理由 `mode_locked` で拒否します。起動時の `ARI_*` 環境変数への変換もロックされた
パスをすべて構造的に除外するため、ランテンプレートから継承された値がサブプロセス
へ到達することもできません。

**デフォルト以外の選択がチェックポイントに与える影響。** 起動は最小限の
`ari:` / `rqgm:` / `paper:` ブロックをそのラン自身の `workflow.yaml` コピーへ
書き込み（同梱ファイルには決して書きません）、*さらに* `ARI_MODE`、
`ARI_RQGM_ENABLED`、`ARI_PAPER_MODE`、`ARI_RQGM_PAPER_ENABLED` をサブプロセスへ
エクスポートします。こうしてチェックポイントは自己記述的になり、以降のあらゆる
フェーズが環境と一致します。デフォルトのままにすれば書き込みもエクスポートも
**一切ありません**: `simple_bfts` + `linear` の起動は ADR-09 以前とバイト単位で
同一であり、デフォルト値を明示的に選び直した場合も同様です。

CLI 流のやり方も引き続き可能であり、そちらが正準の説明のままです:

```yaml
# workflow.yaml
ari:
  mode: ari_rqgm      # master switch
rqgm:
  enabled: true       # redundant interlock — both keys must agree
```

あるいは環境変数の `ARI_MODE=ari_rqgm` / `ARI_RQGM_ENABLED=1`。完全な意味論 —
インターロック表、`mode_source`、resume の突き合わせ、独立した `paper.mode` 軸 —
は[実行モード](execution_modes.md)にあります。

## 関連

- [ダッシュボードガイド](dashboard.md) — サーバーの起動、ワークスペースの地図、
  ディープリンク。
- [実行モード](execution_modes.md) — `ari_rqgm` と論文モードの有効化。
- [RQGM ガバナンスワークスペース](rqgm_gui.md) — ガバナンス下のランを読む。
- [設定リファレンス](../reference/configuration.md) — 設定ファイルの面。
- [環境変数](../reference/environment_variables.md)。
- [リモートアクセス](remote_access.md) — localhost を超える設定 / シークレット
  エンドポイントの認証。
