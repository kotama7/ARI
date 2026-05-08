# ari/registry/ リファクタリング計画(廃止パス対処)

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../../../REFACTORING.md](../../../REFACTORING.md)
> 関連: [../../../DEPRECATION_REMOVAL.md](../../../DEPRECATION_REMOVAL.md) Tier B

## 0. 挙動保証契約

- FastAPI 製レジストリサーバの **REST エンドポイント・スキーマを変えない**(`/artifact/*` 等)
- token 認証ロジック、SHA256 検証を変えない
- `FilesystemStorage` のレイアウトを変えない
- `ari registry serve` `ari registry issue` `ari registry revoke` `ari registry list-tokens` の CLI を変えない

## 1. 範囲拡大の理由

[ari-core/REFACTORING.md §1](../../REFACTORING.md) では本ディレクトリは「変更不要」だった。
しかし [DEPRECATION_REMOVAL.md](../../../DEPRECATION_REMOVAL.md) の監査で 2 件の `~/.ari/` 参照が発見されたため、**変更スコープに昇格**:

| # | ファイル | 行 | 内容 |
|---|---|---|---|
| 1 | `registry/app.py` | 29 | `data_dir = Path(... or os.environ.get("ARI_REGISTRY_DATA") or Path.home() / ".ari" / "registry-data")` |
| 2 | `registry/cli.py` | 20 | `Path(os.environ.get("ARI_REGISTRY_DATA") or Path.home() / ".ari" / "registry-data")` |

両方とも **Tier B**(警告 → v1.0 削除)。

## 2. 計画

### Step 1: 共通フォールバック関数の新設(Phase DR2)

`app.py` と `cli.py` で **同一のフォールバックロジックが重複**している。

`registry/_data_dir.py`(または `registry/__init__.py` 内)に共通関数:

```python
def resolve_data_dir(explicit: Path | None = None) -> Path:
    """Resolve registry data dir.

    Priority:
        1. explicit (function arg)
        2. ARI_REGISTRY_DATA env var
        3. ~/.ari/registry-data (DEPRECATED, removed in v1.0)
    """
    if explicit is not None:
        return Path(explicit)
    if env := os.environ.get("ARI_REGISTRY_DATA"):
        return Path(env)

    legacy = Path.home() / ".ari" / "registry-data"
    from ari._deprecation import warn_deprecated_path
    warn_deprecated_path(
        legacy,
        replacement="ARI_REGISTRY_DATA environment variable",
    )
    return legacy
```

### Step 2: 呼び出し元の置換(Phase DR2 / DR3)

**`registry/app.py:29`(現状):**
```python
data_dir = Path(
    data_dir or os.environ.get("ARI_REGISTRY_DATA") or Path.home() / ".ari" / "registry-data"
)
```

**修正:**
```python
from ari.registry import resolve_data_dir

data_dir = resolve_data_dir(data_dir)
```

**`registry/cli.py:20`(現状):**
```python
return Path(os.environ.get("ARI_REGISTRY_DATA") or Path.home() / ".ari" / "registry-data")
```

**修正:**
```python
from . import resolve_data_dir

return resolve_data_dir()
```

### Step 3: DR5 = v1.0 で legacy フォールバック削除

**v1.0 で:**
```python
def resolve_data_dir(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    if env := os.environ.get("ARI_REGISTRY_DATA"):
        return Path(env)
    raise EnvironmentError(
        "ARI_REGISTRY_DATA must be set when running 'ari registry'. "
        "See docs/howto/migration.md for v0.7 → v1.0 migration."
    )
```

### Step 4: SQLite token DB の所在(関連の確認)

`registry/auth.py` で token DB を sqlite ファイルとして保持している場合、その所在も確認すること。
**もし `~/.ari/registry-tokens.db` のような所在ならば、本書 §2 と同じパターンで対処**。
監査結果を本書に追記:

- [ ] `registry/auth.py` を読み、`~/.ari/` への書き込みがないか確認(初回着手時)

## 3. 触らない範囲

- FastAPI ルート定義 `/artifact/{...}` 等
- `FilesystemStorage` のレイアウト(`<data_dir>/{owner}/{slug}/{version}/...`)
- token ハッシュ実装
- CLI フラグ・引数

## 4. 挙動保証チェックリスト

- [ ] `pytest ari-core/tests/test_registry*.py -q` がグリーン(あれば)
- [ ] `ari registry serve --port 18890` が `ARI_REGISTRY_DATA` 設定時に正しいディレクトリで起動
- [ ] `~/.ari/registry-data/` を持つ環境で警告付きで起動
- [ ] `~/.ari/registry-data/` も `ARI_REGISTRY_DATA` も無い環境で警告付きでフォールバック先を作成
- [ ] FastAPI 起動後に `curl http://localhost:18890/artifact/...` の応答が DR 前後で同一
- [ ] `grep -rn "~/.ari" ari-core/ari/registry/ --include="*.py"` のヒットが `_deprecation` 経由のみ

## 5. ドキュメンテーション計画との連動

[docs/registry.md](../../../docs/registry.md) を更新し、`ARI_REGISTRY_DATA` を**正規パス**として案内、`~/.ari/registry-data` を「v1.0 で削除予定の旧パス」として明記。

---

## 実装完了後の削除

**DR2〜DR3 の関連 PR がマージされ、§4 のチェックリスト合格時点で本ファイルを削除する。**

恒久化する内容:
- §2 共通フォールバック関数 → 実コード
- §4 環境変数の優先順位 → `docs/registry.md` の「パス解決」節
