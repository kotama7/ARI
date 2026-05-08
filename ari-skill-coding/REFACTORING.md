# ari-skill-coding リファクタリング計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../REFACTORING.md](../REFACTORING.md)

## 0. 挙動保証契約

[マスター計画 §2](../REFACTORING.md) の契約を厳守する。本スキルは**コードの変更なし**(import パスのみ変更):

- MCP ツール名・引数・戻り値スキーマを変えない
- スキルが書き込むファイル(`ARI_WORK_DIR`)のレイアウトを変えない
- 環境変数 `ARI_MAX_CHILD_PROCS` `ARI_WORK_DIR` `ARI_CONTAINER_IMAGE` `ARI_CONTAINER_MODE` の名前・既定値を変えない
- 既存の MCP プロトコル経由の挙動(CLI 経由の skill サーバ起動を含む)を変えない

## 1. 現状

このスキルは `ari-core` 内部 (`ari.container`) を 1 箇所で参照している:

| ファイル | 行 | import 文 |
|---|---|---|
| `tests/test_server.py` | 102 | `import ari.container`(リグレッションテストでコンテナ実行機能を検証) |

これは「skill が core 内部に依存している」境界違反だが、**重要な動作を担うため違反を放置せず、公開 API として正規化する**。

## 2. 計画 (Phase 4, PR-4)

[ari-core/REFACTORING.md §7](../ari-core/REFACTORING.md) で `ari/public/container.py` が新設された後に実施する。

### 変更内容

`tests/test_server.py:102` の import 文を変更:

```diff
- import ari.container
+ from ari.public import container as ari_container
```

または

```diff
- import ari.container
+ from ari.public.container import ContainerConfig, run_shell_in_container, ...
```

**実装側のコード変更はゼロ**。テストの import パスのみ。

### タイミング

- **前提**: PR-4(`ari/public/` 新設)が `ari-core` 側で先行マージされていること
- **依存**: なし
- **後続**: PR-4 と同 PR、または PR-4 直後の追従 PR で実施

## 3. 挙動保証チェックリスト

- [ ] `pytest ari-skill-coding/tests/ -q` がグリーン
- [ ] テストが従来と同じ機能(コンテナ実行ラップ)を検証していることを目視確認
- [ ] スキルサーバ起動: `python -m ari_skill_coding.server` 相当の起動が成功(MCP プロトコルでのハンドシェイク)
- [ ] `mcp.json` の内容が変更前と完全一致
- [ ] パッケージの依存関係(requirements / pyproject)が変更されていない

## 4. 将来の選択肢

`ari/public/container.py` が定着したら、本ファイル(REFACTORING.md)に書いた boundary CI(`ari-core/tests/test_public_api_boundary.py`、マスター §7)が、本スキルでも `ari.public.*` 以外の `ari.X` import を許さないようになる。これにより、将来同じ境界違反が再発しない。

---

## 実装完了後の削除

**PR-4 がマージされ、§3 のチェックリストすべてに合格した時点で本ファイルを削除する。**

恒久化する内容(削除前に転記):
- §1 の boundary 違反の事実 → `ari-core/tests/test_public_api_boundary.py` のコメント
- §2 の import 移行手順 → 不要(削除して問題ない)
