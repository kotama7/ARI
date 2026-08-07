---
sources:
  - path: ari-core/tests
    role: test
  - path: ari-core/tests/fixtures/gui_refresh
    role: test
  - path: pytest.ini
    role: config
  - path: scripts/docs
    role: test
  - path: scripts/check_dashboard_ux.py
    role: test
  - path: scripts/check_bundle_budget.py
    role: test
  - path: scripts/quality/check_bundle_budget.yaml
    role: config
  - path: ari-core/ari/viz/frontend/src/i18n
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__
    role: test
  - path: .github/workflows
    role: config
last_verified: 2026-08-08
---

# ARI コードのテスト方法

このガイドでは `ari-core` と `ari-skill-*` パッケージのテスト規約を説明します:
テストの配置場所、期待されるフィクスチャ、決定性保証の維持方法を扱います。

## リポジトリレイアウト

```
ari-core/tests/                 — コアの回帰テスト
ari-skill-<name>/tests/         — スキルローカルのテスト
ari-skill-<name>/conftest.py    — スキルレベルのフィクスチャ
pytest.ini                      — リポジトリ全体の設定
```

リポジトリルートの `pytest.ini` は、素の `pytest` が走査する `testpaths` を
定めます: `ari-core/tests` と `workspace/harnesses`（後者は workspace の無い
チェックアウトでは存在せず、pytest はそれを許容します）。`ari-skill-*` の
スイートは意図的に `testpaths` に**入れていません** — 各スキルが独自の
`src/server.py` を持つため、2 つを同一プロセスで import すると曖昧になります。
パッケージ単位で実行するか、フルスイートは `bash scripts/run_all_tests.sh`
（パスごとに 1 つの pytest プロセス）を使ってください。

## スイートの実行

```bash
pytest -q                                        # 既定の testpaths のみ
bash scripts/run_all_tests.sh                    # フルスイート（パス毎に別プロセス）
pytest ari-skill-memory/tests -q                 # スキル 1 つ
pytest ari-core/tests/test_react_driver.py -q    # one file
pytest ari-core/tests/test_react_driver.py::test_runs_for_two_nodes  # one case
pytest -k 'memory and not letta' -q              # by keyword
```

## ari-core の規約

### 必ず書き込みを分離する

ARI はかつて `$HOME/.ari/` に書き込んでいました。v0.5.0 でそのパスは削除されました。
ガードレールテスト `ari-core/tests/test_no_user_home_writes.py` は、
テストが再びそこにファイルを作成しないことを保証します。ファイルシステムに触れる
新しいテストを書く場合:

- `monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))` を使用する。
- 補助ディレクトリには `tmp_path` を使用する。
- 本番コードで `Path.home()` を直接呼び出さない。テストで必要な場合は
  理由を文書化し、監査リストに追加する。

### エージェントループのスモークテスト

`ari-core/tests/test_react_driver.py` は 3 つの決定論的な
「エージェントが 2 ノードを通過する」テストを実行します:

1. **ハッピーパス** — 2 ノード、実際の LLM スタブ、各トランジションで BFTS ステートを検証。
2. **ツール失敗からの回復** — coding スキルがエラーを返す。エージェントは
   固定シードで再試行する。
3. **メモリ書き込みの分離** — 兄弟ノードは互いに独立したメモリストアを参照する。

新しいエージェントレベルの機能を追加するときは、このトリプレットを踏襲してください。

### 決定性保証 (P2)

「同じシード、同じツリー」という不変条件は
`ari-core/tests/test_no_user_home_writes.py` で間接的に検証されています
(実行間でグローバルステートが変化しないことを検証) が、
スキルごとのスイート (`ari-skill-memory/tests/test_isolation.py`、
`ari-skill-memory/tests/test_cow.py`) でも検証されています。

決定性の回帰が混入した場合:

1. 期待するツリーシェイプを固定する回帰テストを最初に書く。
2. 変更セットを二分探索する。ほとんどの場合、`dict` の順序依存または
   `id(...)` に依存するハッシュが原因です。
3. 該当ドメインのスイート (memory、BFTS など) にテストを追加する。

### 合成チェックポイントフィクスチャ

GUI と `/api/v1` のリーダーテストはチェックポイントを同梱しません — 生成します。
`ari-core/tests/fixtures/gui_refresh/` には純 Python のファクトリが 2 つあります:

- `run_fixture_factory.py` — `make_run_checkpoint(dest, nodes=N, seed=S)` が
  実行チェックポイント (`tree.json`、`nodes_tree.json`、`results.json`、
  `experiment.md`、`idea.json`、`meta.json`、`cost_trace.jsonl`) を本物の
  `ari.checkpoint.save_*_json` ヘルパー経由で書き出すため、JSON の整形が
  本番ライターとバイト単位で一致します。オプションの `paper` / `review` /
  `ors` / `ear` の結果レイヤーはすべて既定で OFF です。
- `rqgm_fixture_factory.py` — `make_rqgm_checkpoint(dest, nodes=10, epochs=2,
  ...)` はまずベースファクトリを呼び、その上に決定論的な RQGM ガバナンス
  サーフェス (ハッシュチェーンされた transition / audit ログ、registry の
  ロールアップ、prompt 本体、node metrics のセンチネル) を重ねます。ハッシュ
  とステートのヘルパーは再実装せず本物の `ari.rqgm` から import しています。

使う際に効いてくる性質が 3 つあります。

**何もコミットしません。** どちらのファクトリも呼び出し側が渡したディレクトリ
(全消費側で `tmp_path`) に生成するため、古くなっていくフィクスチャデータが
リポジトリに残りません。

**決定性 (P2)。** すべての値は固定リテラルか、シードから `hashlib` で導出した
ものです。`random` は一度も import されず、タイムスタンプは
`datetime.now()` ではなくリテラル `2026-07-23T00:00:00Z` への固定演算です。
同じ `(nodes, seed)` はバイト同一のファイルを生み、
`ari-core/tests/test_gui_baseline_run_fixtures.py` がそれを直接検証しています。

**破損モードが堅牢性の入力です。** `corrupt=` はまず完全に妥当なチェックポイント
を書き、その後ちょうど 1 箇所だけを壊すので、テストは一度に 1 つの失敗形状だけを
切り出せます: `"truncated_jsonl"` は `cost_trace.jsonl` の最終行を途中で切り、
`"invalid_json"` は `tree.json` の末尾を削り、`"partial_write"` は
`nodes_tree.json` を妥当なまま残して `tree.json` を削除します。RQGM ファクトリは
独自の 3 つ — `"broken_chain"`、`"truncated_transitions"`、`"registry_mismatch"`
— を持ちます。どちらも未知のモードは `ValueError` で拒否します。

サイズ階層は命名の慣習であって契約ではありません。ファクトリの docstring と
`ari-core/tests/fixtures/gui_refresh/README.md` は `nodes=10` / `1000` /
`10000` を small / medium / large と呼び、small 階層を「every reader must load
it (すべてのリーダーがロードしなければならない)」と述べていますが、それを強制
する仕組みはありません。`nodes` は `nodes >= 1` の検査が 1 つあるだけの素の
整数パラメータで、3 階層を実際に使うのは
`test_gui_baseline_run_fixtures.py` だけ (しかも決定性ケースには `nodes=50` を
使います)。リーダー側のスイートはアサーションに必要な数を渡すだけで、
他の `test_gui_*` 各ファイルでは `nodes=2` から `nodes=10` の範囲です。階層名は
それらのテストを読むときの略語として扱い、従うべきルールとしては読まないで
ください。なお `test_gui_baseline_run_fixtures.py` では large 階層は生成される
だけで再ロードされません。skip を掛けるための `slow` マーカーをリポジトリが
定義していないためです。

消費側はパッケージを import せず
`importlib.util.spec_from_file_location` でファイルパスからファクトリを読み込む
ため、小さなローダーヘルパーが各消費ファイルの冒頭に繰り返し置かれています。

## スキルレベルの規約

### MCP サーバーテスト

各スキルには `test_server.py` が付属しており:

1. MCP サーバーをインプロセスで起動する (サブプロセスなし)。
2. `list_tools()` を呼び出し、ツールリストが `mcp.json` と一致することを検証する。
3. 各ツールをフィクスチャ入力で呼び出し、レスポンスの形状を検証する。

`mcp.testing` ヘルパーを使用してください (ハーネスはスキルによって異なります —
リファレンスとして `ari-skill-memory/tests/conftest.py` を参照)。

### LLM モック

LLM を呼び出すスキル (`evaluator`、`paper`、`paper-re`、`idea`、
`replicate`、`transform`、`plot/_llm`、`vlm`) は、ユニットテストで
LLM をモックしなければなりません。LiteLLM の `respx` アダプターまたは
`pytest-mock` を使って `litellm.completion` を固定レスポンスに置き換えてください。

リファレンス例は `ari-skill-paper-re/tests/test_litellm_completer.py` です。

### 依存状態フィクスチャ

スキルが `ARI_CHECKPOINT_DIR` スタイルの環境を必要とする場合、
フィクスチャで設定してください:

```python
@pytest.fixture
def ckpt(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    return tmp_path
```

モジュールインポート時に `ARI_CHECKPOINT_DIR` を設定しないでください —
値はテストにスコープされなければなりません。

## PR 時にテストされる内容

`main` への各 PR を複数の GitHub Actions ワークフローがゲートします。

**テスト** — `refactor-guards` ワークフローが実行するもの:

- `pytest ari-core/tests -q`
- `pytest ari-skill-coding/tests -q`
- `pytest ari-skill-memory/tests -q`
- ... スキルごとのスイート

また `tests/test_no_user_home_writes.py` と
`tests/test_public_api_boundary.py` (フェーズ 4、スキルが `ari.public.*` からのみ
インポートしていることを保証) も実行します。

**ドキュメント・構造** — 3 つのワークフローがドキュメント群の同期を保ちます:

- `readme-sync` — 各ディレクトリの `## Contents` 索引が配下のファイルを
  列挙していること (`scripts/readme_sync.py --check`)。
- `docs-sync` — 全ツリー不変条件、すべてハードゲート: 宣言された `sources:`
  パスが実在すること (`check_doc_sources.py`)、`docs/i18n/landing.{en,ja,zh}.js`
  のキー集合が一致すること (`check_i18n_js.py`)、ルート `README.{md,ja,zh}` の
  見出し構造が一致すること (`check_readme_parity.py`)、`report/{en,ja,zh}` が
  構造的に並行であること (`report/scripts/check_i18n.py`、Gate 6)。翻訳鮮度
  (`check_translation_freshness.py`) と docs 内リンク (`check_doc_links.py`) は
  advisory (非ブロッキング) ステップとして実行します。
- `docs-change-coupling` — 差分ベース: `report/{en,ja,zh}` の言語ペアファイル
  (章・`strings.tex`・`main.tex`) を 1 言語で編集したら、同じ PR で他 2 言語にも
  反映すること (`check_report_cochange.py`、ハード)。また doc の `sources:` に
  挙げたソースが変更されたら、その doc の `last_verified` を更新すべきこと
  (`check_ref_coupling.py`、advisory)。

各 doc ゲートはリポジトリルートからローカル実行できます。例:
`python scripts/docs/check_i18n_js.py`。

**ダッシュボードの翻訳** — ダッシュボード UI は独自の 3 言語辞書
`ari-core/ari/viz/frontend/src/i18n/{en,ja,zh}.ts` を持ちますが、上記のどの
ワークフローもこれを対象にしていません: `check_i18n_js.py` が読むのは
`docs/i18n/landing.{en,ja,zh}.js` のみで、そのキーパターンはシングルクォート
されたキーしか一致しないため、キーが裸の識別子である辞書は解析できません。
ルール自体は docs 側と同じです — 3 ロケールは**同一のキー集合**を宣言し、
同一ファイル内でキーを重複させてはなりません。したがって新しい UI 文字列は
同じ変更で 3 つすべてに追加する必要があります。あるロケールにあって別の
ロケールに無いキーは英語の文字列にフォールバックし、`en` にも無ければ
キー名がそのまま表示されます (`src/i18n/index.ts` の `t()`)。値は意図的に
比較しません: 固有名詞は 3 言語で同一の表記になり得るためです。

これを担保するチェックは 2 つあり、**どちらもワークフローに組み込まれて
いません** — ダッシュボードの文字列に触れたら自分で実行してください:

- `python scripts/check_dashboard_ux.py --fail-on-regression` — 3 つの `.ts`
  ファイルに対するキー集合の一致検査と重複検出で、同スクリプトの他の
  ダッシュボード UX 検査と同梱されています。`scripts/quality/check_dashboard_ux.allow.yaml`
  に凍結されていない findings が 1 つでもあれば exit 1 になります。この
  許可リストに i18n エントリは 1 件も無いため、一致が壊れれば最初の実行で
  失敗します。フラグを付けない場合はレポートを出力して exit 0 です。
- `ari-core/ari/viz/frontend` から
  `npx vitest run src/i18n/__tests__/parity.test.tsx` — import した実際の辞書に
  対して同じ不変条件を検証します。`KNOWN_DRIFT` 許可リストは現在空です。
  重複キーの検査は Python 側より弱く、TypeScript のオブジェクトリテラルは
  テストが読む時点で重複キーを既に畳み込んでいるためです。

現在のツリーではどちらも green です: 3 つの辞書は重複なしで同一のキー集合を
保持しています。

**ダッシュボードのアクセシビリティ** — ダッシュボードは **WCAG の適合レベルを
一切宣言していません**。この docs 群にも frontend のテスト群にも適合目標は
存在せず、ここに書かれている内容を適合の主張として読んではいけません。存在
するのは
`ari-core/ari/viz/frontend/src/__tests__/shellA11yBaseline.test.tsx` にある
凍結ベースラインの集合です。上記の i18n チェックと同様、これも**どのワーク
フローにも組み込まれていません** — frontend のスイートを実行するワークフローは
そもそも存在しません (CI にある Node のステップは VitePress の docs サイトを
ビルドするものだけです)。代わりに、手動で実施する cutover 前チェックリストの
ハード行になっています (`npm test`、
`docs/guides/gui_cutover_runbook.md` §2)。このファイルだけを実行するには
`ari-core/ari/viz/frontend` から:

```bash
npx vitest run src/__tests__/shellA11yBaseline.test.tsx
```

このファイルが固定しているのは 3 点です:

- **既に成立している正の不変条件。** `navigation` ランドマークがちょうど 1 つ、
  サイドバーの各エントリ (`gui_v2` 有効時は 15 個) が `tabindex="0"` を持つ
  ネイティブ button であること、4 つの nav グループが `aria-labelledby` で
  名前付けされていること、モバイルのハンバーガーが
  `aria-label`/`aria-controls`/`aria-expanded` を持つこと、アクティブ
  プロジェクトの `combobox` がアクセシブルな名前を持つこと。
- **`#/home` で描画したシェルに対する axe-core の violation id ベースライン。**
  現在は空リストです。アサーションは完全一致なので、新しい violation が出れば
  失敗し、*さらに* 原因を修正した後にベースラインへ id を残したままでも失敗
  します。jsdom は描画しないため `color-contrast` ルールはそこで**無効化**されて
  います — このリポジトリには色コントラストを計算する自動チェックはありません。
- **テストの `ROUTE_MARKERS` にある 18 ルートに対する `<h1>` 個数ベースライン。**
  うち 4 つは非準拠と分かった上で固定されています: `#/paperbench`、`#/workflow`、
  `#/settings` はページタイトルが `<h2>` で `<h1>` が無く、`#/idea` は見出し要素
  自体がありません。残り 14 は `<h1>` をちょうど 1 つ描画します。ここも完全一致
  なので、あるルートを修正したら同じ変更で凍結リテラルを縮める必要があります。

何もカバーしていないもの: 主要な journey をマウス無しで完了できることを end-to-end
で検証するアサーションは無く、スクリーンリーダーのチェックもありません。キーボードで
*到達できる* ことが検証されているのはサイドバー (上記のフォーカス可能な
ネイティブ button) までで、実際にキーボードで *操作する* ことが検証されているのは
`#/tree2` のテーブル
(`src/components/TreeV2/__tests__/TreeV2LargeTree.test.tsx` が roving tabindex 上で
<kbd>↓</kbd>/<kbd>→</kbd>/<kbd>Enter</kbd> を歩きます。キー対応表は
`docs/guides/dashboard.md`) だけです。モーション低減は全体で尊重されています —
`src/styles/motion.css` が `prefers-reduced-motion: reduce` の下でモーション
トークンを 0 にします — が、これはスタイルシートの性質であってテストの性質では
ありません。

WCAG 2.2 AA のゲートは、自動・手動のいずれであれ、ダッシュボード刷新の目標で
あって、このスイートが確立している性質ではありません。green な実行を AA 適合の
証拠として読まないでください。

**SPA のバンドル重量** — `scripts/check_bundle_budget.py` はダッシュボードの
ビルドを一連の gzip 予算に収めますが、これも**どのワークフローにも組み込まれて
いません**。ここでの理由は構造的です: frontend をビルドするワークフローが存在
せず、`ari-core/ari/viz/static/dist/` はコミットされず生成される成果物なので、
チェッカーが計測するディレクトリが runner 上に存在しません。
`scripts/quality/generate_quality_report.yaml` には登録*されて*いますが、この
ファイルを読む集約スクリプトは `contracts.yml` 内で `--target` モードで動きます
— 他ジョブがアップロードした JSON アーティファクトをマージするだけでチェッカー
は一切実行しません — そのため bundle budget はそこでは `unavailable` として現れ
ます。ビルドの後に自分で実行してください。手動で実施する cutover 前チェック
リストの 1 行です (`docs/guides/gui_cutover_runbook.md` §2):

```bash
cd ari-core/ari/viz/frontend && npm run build   # the checker never builds
python scripts/check_bundle_budget.py --fail-on-regression
```

`ari-core/ari/viz/static/dist/assets/*.js` の各ファイルをインプロセスで gzip し
(level 6、`mtime=0` なので同じビルドに対する再実行は同一の数値を報告します)、
各 chunk をそのクラス予算 (単位は KiB の gzip サイズ) と比較します:

| クラス | 対象 | 予算 |
|---|---|---|
| `entry` | `dist/index.html` が参照する `<script type="module">` の chunk | 100 |
| `route` | 遅延ロードされるルート chunk (`<Name>Page-<hash>.js` で判定) | 150、ただし `SettingsPage` と `WizardPage` は 50 に絞る |
| `shared` | その他すべての `.js` chunk — vendor 分割、ロケール辞書、共有コンポーネント | 150 |
| `total` | 全 `.js` chunk の gzip サイズの合計 | 600 |

`shared` の上限は意図的に保守的な上位集合です: 個別に予算が定められていたのは
route chunk だけで、同じ数値をそれ以外にも広げることで、分割を誤った vendor
バンドルが route クラスの外に隠れられないようにしています。`total` は目標値では
なくラチェットの天井で、chunk ごとの予算では見えない唯一の失敗モード — 多数の
chunk に重複した依存や、予算未満の新規 chunk が大量に増える事象 — のために存在
します。

ブラウザ側の指標 (LCP・INP・CLS) は意図的にゲートして**いません**: jsdom は描画
せず、共有 runner は pass/fail 予算には騒がしすぎるためです。したがってバンドル
の green な実行は体感性能について何も述べていません。その半分は固定マシン上の
手動プロファイルで、リリースのエビデンスに記録します。

終了コードの規約は `scripts/quality` ファミリーの他と同じです。素の実行はレポート
を出力して exit 0。`--fail-on-regression` は
`scripts/quality/check_bundle_budget.allow.yaml` に凍結されていない findings が
1 つでもあれば exit 1 になりますが、このファイルは存在しません — 凍結が必要に
なった予算がこれまで無く、allow ファイルが無ければ許可リストは空なので、予算
超過の chunk は最初の実行で失敗します。`dist/assets` が無い場合は exit 2 です。
ビルドの不在は予算の回帰ではなく環境の問題だからです。

予算そのものは `scripts/quality/check_bundle_budget.yaml` にあります — dist の
パス、route chunk の正規表現、4 つのクラス予算、そしてルートごとの上書きです。
すべてのキーは省略可能で、チェッカーはコード内の既定値として同じ値を持っている
ため、この YAML の存在意義は「予算の変更をコード編集ではなくレビュー可能な 1 行
の diff にする」ことだけです。調整はスクリプトではなくこちらで行ってください。

## 回帰テストの書き方

パターン:

1. `assert <observed> == <expected>` で失敗するテストとしてバグを捉える。
2. まずテスト単体を先にランドする (red コミット)。
3. その上に修正をランドする。

これにより「期待していたこと」と「どう修正したか」が `git log` で分離され、
修正の後続リライトにも耐えられます。

## 関連

- `pytest.ini` — リポジトリ全体の設定。
- `docs/concepts/architecture.md` — ランタイムアーキテクチャ (適切なテストレイヤーを選ぶ際に役立ちます)。
- `docs/reference/public_api.md` — 境界テストはこのサーフェスに対してインポートを確認します。
