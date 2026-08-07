---
sources:
  - path: ari-core/tests
    role: test
  - path: pytest.ini
    role: config
  - path: scripts/docs
    role: test
  - path: scripts/check_dashboard_ux.py
    role: test
  - path: ari-core/ari/viz/frontend/src/i18n
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__
    role: test
  - path: .github/workflows
    role: config
last_verified: 2026-08-07
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
