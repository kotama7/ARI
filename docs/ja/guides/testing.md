---
sources:
  - path: ari-core/tests
    role: test
  - path: pytest.ini
    role: config
  - path: scripts/docs
    role: test
  - path: .github/workflows
    role: config
last_verified: 2026-06-04
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

リポジトリルートの `pytest.ini` によって、どこからでも `pytest` を実行すると
すべてのテストディレクトリを走査します。

## スイートの実行

```bash
pytest -q                                        # everything
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
  パスが実在すること (`check_doc_sources.py`)、`docs/i18n/{en,ja,zh}.js` の
  キー集合が一致すること (`check_i18n_js.py`)、ルート `README.{md,ja,zh}` の
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
