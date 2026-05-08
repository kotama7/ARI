# ari/clone/ リファクタリング計画(廃止パス対処)

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../../../REFACTORING.md](../../../REFACTORING.md)
> 関連: [../../../DEPRECATION_REMOVAL.md](../../../DEPRECATION_REMOVAL.md) Tier B

## 0. 挙動保証契約

[マスター計画 §2](../../../REFACTORING.md) を厳守:

- `clone()` の公開シグネチャを変えない
- 5 リゾルバ(`file://` `https://` `ari://` `gh:` `doi:`)の URL スキーム判定を変えない
- SHA256 検証ロジックを変えない
- アーティファクト展開先のレイアウトを変えない

## 1. 範囲拡大の理由

[ari-core/REFACTORING.md §1](../../REFACTORING.md) では本ディレクトリは「変更不要」だった。
しかし [DEPRECATION_REMOVAL.md](../../../DEPRECATION_REMOVAL.md) の監査で 2 件の `~/.ari/` 参照が発見されたため、**変更スコープに昇格**:

| # | ファイル | 行 | 内容 |
|---|---|---|---|
| 1 | `clone/resolvers/ari.py` | 29 | `Path.home() / ".ari" / "registries.yaml"` 候補パス |
| 2 | `clone/resolvers/ari.py` | 78 | エラーメッセージで `~/.ari/registries.yaml` を案内 |

両方とも **Tier B**(警告 → v1.0 削除)。`publish/backends/ari_registry.py` の同じパターンと **同期して**修正する(共通ヘルパに統合できれば理想)。

## 2. 計画

### Step 1: 候補パス探索の共通化(Phase DR3、publish と同 PR が望ましい)

`clone/resolvers/ari.py:29` と `publish/backends/ari_registry.py:29` で **同じ探索ロジックの重複実装**になっている。

**新設:** `ari/clone/_registry_lookup.py`(または共有先 `ari/registry/lookup.py`)
```python
def find_registries_yaml(checkpoint_dir: Path | None = None) -> list[Path]:
    """Search candidates in priority order. Emits DeprecationWarning
    for ~/.ari/registries.yaml until v1.0.
    """
    candidates: list[Path] = []
    if env := os.environ.get("ARI_REGISTRIES_FILE"):
        candidates.append(Path(env))
    if checkpoint_dir is not None:
        candidates.append(checkpoint_dir / ".ari" / "registries.yaml")
    candidates.append(Path.cwd() / ".ari" / "registries.yaml")

    legacy = Path.home() / ".ari" / "registries.yaml"
    if legacy.exists():
        from ari._deprecation import warn_deprecated_path
        warn_deprecated_path(
            legacy,
            replacement=f"{checkpoint_dir}/.ari/registries.yaml or ARI_REGISTRIES_FILE env",
        )
        candidates.append(legacy)

    return candidates
```

`clone/resolvers/ari.py` と `publish/backends/ari_registry.py` の両方が **同じ関数** を呼ぶようにリファクタ。

### Step 2: エラーメッセージの修正(Phase DR2)

`clone/resolvers/ari.py:78`

**現状(問題):**
```python
raise CloneError(
    "no ari-registry configured. Set ARI_REGISTRY_URL or write ~/.ari/registries.yaml"
)
```

**修正:** [publish/REFACTORING.md Step 2](../publish/REFACTORING.md) と同文を使う(共通エラーメッセージヘルパ:
```python
def _no_registry_error_msg() -> str:
    return (
        "no ari-registry configured. Set ARI_REGISTRY_URL, "
        "or write registries.yaml in your checkpoint or working directory "
        "(see docs/registry.md for format). "
        "Note: ~/.ari/ paths are deprecated and will be removed in v1.0."
    )
```

### Step 3: clone()` への checkpoint_dir パラメータ追加(後方互換でオプショナル)

`clone()` の呼び出し元(`cli.py:cmd_clone`)から `checkpoint_dir` を伝播し、新規候補パス
(`{checkpoint}/.ari/registries.yaml`)を有効にする。

**公開 API:**
```python
def clone(
    src: str,
    dest: Path,
    *,
    checkpoint_dir: Path | None = None,  # ← 追加(オプショナル)
    registry: str | None = None,
    ...
) -> CloneResult:
    ...
```

## 3. 触らない範囲

- 5 リゾルバ(`file.py` `https.py` `ari.py` の URL 解析部分 `gh.py` `doi.py`)の URL スキーム判定
- `clone()` の戻り値型 `CloneResult`、例外型 `CloneError`
- SHA256 検証
- アーティファクト展開先レイアウト
- リゾルバレジストリ機構(`resolvers/__init__.py` の `resolve()` 関数)

## 4. 挙動保証チェックリスト

- [ ] `pytest ari-core/tests/test_clone.py -q` がグリーン
- [ ] `ari clone <src>` が `~/.ari/registries.yaml` を持つ環境で警告付きで動作
- [ ] `ari clone <src>` が `{checkpoint}/.ari/registries.yaml` のみで動作
- [ ] エラーメッセージが新表記
- [ ] `grep -rn "~/.ari" ari-core/ari/clone/ --include="*.py"` のヒットが `_deprecation` 経由 + コメント以外で 0
- [ ] `publish/backends/ari_registry.py` と探索ロジックが共通関数経由になっている

## 5. publish との整合

publish 側 [publish/REFACTORING.md](../publish/REFACTORING.md) と **同じ PR で同時にリファクタ** することを強く推奨。
別 PR にすると、共通化の意図が伝わりづらく、レビュー時に重複実装の修正漏れが出る。

---

## 実装完了後の削除

**DR2〜DR3 の関連 PR がマージされた時点で本ファイルを削除する。**

恒久化する内容:
- §2 Step 1 共通ヘルパ → 実コード(`ari/clone/_registry_lookup.py` または `ari/registry/lookup.py`)
- §2 Step 2 エラーメッセージ → 実コード
