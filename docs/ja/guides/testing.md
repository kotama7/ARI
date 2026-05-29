---
sources:
  - path: ari-core/tests
    role: test
  - path: pytest.ini
    role: config
last_verified: 2026-05-25
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

`refactor-guards` GitHub Actions ワークフローが実行するもの:

- `pytest ari-core/tests -q`
- `pytest ari-skill-coding/tests -q`
- `pytest ari-skill-memory/tests -q`
- ... スキルごとのスイート

また `tests/test_no_user_home_writes.py` と
`tests/test_public_api_boundary.py` (フェーズ 4、スキルが `ari.public.*` からのみ
インポートしていることを保証) も実行します。

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
