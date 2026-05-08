# ari/memory/ リファクタリング計画(廃止パス対処)

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../../../REFACTORING.md](../../../REFACTORING.md)
> 関連: [../../../DEPRECATION_REMOVAL.md](../../../DEPRECATION_REMOVAL.md) Tier A/B/C/D

## 0. 挙動保証契約

[マスター計画 §2](../../../REFACTORING.md) を厳守:

- `MemoryClient` 抽象クラスとサブクラス(`LettaMemoryClient` `FileMemoryClient` `LocalMemoryClient`)の公開シグネチャを変えない
- `MemoryClient.add()` `search()` `get_node()` `clear_node()` のメソッド契約を変えない
- v0.5 形式 `~/.ari/global_memory.jsonl` を持つユーザの自動移行(`auto_migrate.maybe_auto_migrate`)は**動作を変えない**
- 既存 v0.6 / v0.7 メモリ store の読み書きスキーマを変えない

## 1. 範囲拡大の理由

[ari-core/REFACTORING.md §1](../../REFACTORING.md) では本ディレクトリは「変更不要」だった。
しかし [DEPRECATION_REMOVAL.md §1-1](../../../DEPRECATION_REMOVAL.md) の監査で 4 件の `~/.ari/` 直接参照が発見されたため、**変更スコープに昇格**:

| # | ファイル | 行 | 内容 | Tier |
|---|---|---|---|---|
| 1 | `memory/file_client.py` | 25 | デフォルト引数 `path: str = "~/.ari/memory.json"` | A(即削除) |
| 2 | `memory_cli.py` | 111 | `global_path = Path.home() / ".ari" / "global_memory.jsonl"`(検出専用) | C(隔離) |
| 3 | `memory_cli.py` | 306 | `Path.home() / ".ari/letta-venv"` env フォールバック | B(警告→削除) |
| 4 | `memory/auto_migrate.py` | 43 | `Path.home() / ".ari" / "global_memory.jsonl"`(移行ソース) | C(隔離、触らない) |

## 2. 計画

### Step 1: Tier A — `memory/file_client.py:25` のデフォルト引数削除(Phase DR1)

**現状(問題):**
```python
class FileMemoryClient(MemoryClient):
    def __init__(self, path: str = "~/.ari/memory.json") -> None:
        ...
```
v0.5.0 でグローバル `~/.ari/` は廃止されたが、デフォルト引数として残存。`FileMemoryClient()` で
`~/.ari/memory.json` が黙って作られる潜在バグ。

**修正:**
```python
class FileMemoryClient(MemoryClient):
    def __init__(self, path: str | Path) -> None:
        """File-based memory store. `path` must be explicitly provided
        (typically {checkpoint}/memory_store.jsonl).
        """
        ...
```
デフォルト引数を**完全削除**して必須化する。これは Tier A(即削除)。

**呼び出し側調査:** PR 着手時に `grep -rn "FileMemoryClient(" ari-core/ ari-skill-*/`
で全呼び出しを洗い、明示パスを渡すよう修正。

### Step 2: Tier B — `memory_cli.py:306` の Letta venv フォールバック(Phase DR2/DR3)

**現状(問題):**
```python
venv = Path(os.environ.get("ARI_LETTA_VENV", str(Path.home() / ".ari/letta-venv")))
```
`ARI_LETTA_VENV` 未設定時に `~/.ari/letta-venv/` を作りに行く。

**段階的修正:**

**DR2(警告のみ):**
```python
env_value = os.environ.get("ARI_LETTA_VENV")
if env_value is None:
    fallback = Path.home() / ".ari/letta-venv"
    from ari._deprecation import warn_deprecated_path
    warn_deprecated_path(
        fallback,
        replacement="ARI_LETTA_VENV environment variable (will be required in v1.0)",
    )
    venv = fallback
else:
    venv = Path(env_value)
```

**DR5 = v1.0(削除):**
```python
env_value = os.environ.get("ARI_LETTA_VENV")
if env_value is None:
    raise EnvironmentError(
        "ARI_LETTA_VENV must be set. See docs/howto/migration.md for v0.7→v1.0 migration."
    )
venv = Path(env_value)
```

### Step 3: Tier C — `memory_cli.py:111` の global_memory 検出(Phase 5 と整合)

`memory_cli.py:111` の `global_path = Path.home() / ".ari" / "global_memory.jsonl"` は、
**memory CLI の旧データ削除/バックアップコマンド**で参照される(v0.5 ユーザ救済)。

**対処:**
- リファクタ計画 [Phase 5](../../REFACTORING.md) で `ari/migrations/v05_to_v07/memory.py` に移動済みになる予定
- 本ステップでは:
  - パス参照を `from ari.migrations.v05_to_v07.memory import LEGACY_GLOBAL_PATH` に置換
  - `memory_cli.py:111` のハードコードを削除
- 動作は変えない(`ari memory backup` 等のコマンドが旧グローバルファイルも対象とする挙動を維持)

### Step 4: Tier C — `auto_migrate.py:43`(触らない、文書化のみ)

`auto_migrate.py:43` の `Path.home() / ".ari" / "global_memory.jsonl"` は **v0.5→v0.6 移行のソース**であり、
**触らない**。`migrations/v05_to_v07/memory.py` に移動する Phase 5 PR でファイル自体を移動。

ただしモジュール docstring に以下を追記:
```python
"""v0.5 → v0.6 memory format migration.

This module is the ONLY legitimate accessor of `~/.ari/global_memory.jsonl`.
All other code in ARI must avoid `~/.ari/` paths
(see DEPRECATION_REMOVAL.md tier A/B).
"""
```

## 3. 触らない範囲

- `memory/client.py` — ABC 定義
- `memory/letta_client.py` — Letta 統合
- `memory/local_client.py` — テスト用 in-memory
- `MemoryClient` 抽象 API
- `auto_migrate` の動作(Phase 5 で隔離するが、本書の範囲では動作変更しない)

## 4. 挙動保証チェックリスト

各 PR で:

- [ ] `pytest ari-core/tests/test_memory*.py -q` がグリーン
- [ ] `pytest ari-skill-memory/tests/ -q` がグリーン(15 テスト)
- [ ] `FileMemoryClient(path)` の呼び出しが ari-core / ari-skill-* 内ですべて明示パス渡し(`grep` で 0 件確認)
- [ ] DR2 完了後: `ARI_LETTA_VENV` 未設定で `ari memory start-local` を実行すると `DeprecationWarning` が出る
- [ ] **既存 v0.5 ユーザシナリオ**: `~/.ari/global_memory.jsonl` を含む home dir を持つマシンで `ari run` を実行し、自動移行が DR 前後で同じ結果を出す
- [ ] **既存 Letta venv ユーザ**: `~/.ari/letta-venv/` を持つマシンで DR2 段階では警告付きで動作、DR5 段階では明確なエラー

## 5. 注意事項

- `MemoryClient` を実装する外部の独自バックエンドが将来現れた場合、Path.home() を使わない契約を `docs/extension_guide.md` に明記
- v0.5 から v0.7 までずっと「`~/.ari/` 廃止」と宣言しながらコードに残ったのは、リリース判断と実装が乖離していた証拠 → Phase 6 で `CHANGELOG.md` の過去記述に「実装的に完全削除されたのは v0.x.x」と追記すべきか、本計画レビュー時に決定

---

## 実装完了後の削除

**DR1〜DR3 の関連 PR + Phase 5 PR がマージされた時点で本ファイルを削除する。**

恒久化する内容:
- §1 file_client のデフォルト引数廃止 → 実コードに反映済
- §2 Letta venv パス変更 → `docs/howto/migration.md` の v0.7→v1.0 章
- §4 auto_migrate docstring → 実コードに反映済
