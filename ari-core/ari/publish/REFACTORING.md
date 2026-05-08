# ari/publish/ リファクタリング計画(廃止パス対処)

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../../../REFACTORING.md](../../../REFACTORING.md)
> 関連: [../../../DEPRECATION_REMOVAL.md](../../../DEPRECATION_REMOVAL.md) Tier B

## 0. 挙動保証契約

[マスター計画 §2](../../../REFACTORING.md) を厳守:

- `publish()` `promote()` の公開シグネチャを変えない
- 4 バックエンド(`local_tarball` `ari_registry` `zenodo` `gh`)の公開関数を変えない
- バックエンド選択ロジック(URL スキーム判定)を変えない
- 公開アーティファクトのファイル形式・SHA256 検証を変えない

## 1. 範囲拡大の理由

[ari-core/REFACTORING.md §1](../../REFACTORING.md) では本ディレクトリは「変更不要」だった。
しかし [DEPRECATION_REMOVAL.md](../../../DEPRECATION_REMOVAL.md) の監査で 2 件の `~/.ari/` 参照が発見されたため、**変更スコープに昇格**:

| # | ファイル | 行 | 内容 |
|---|---|---|---|
| 1 | `publish/backends/ari_registry.py` | 29 | `Path.home() / ".ari" / "registries.yaml"` 候補パス |
| 2 | `publish/backends/ari_registry.py` | 98 | エラーメッセージで `~/.ari/registries.yaml` を案内 |

両方とも **Tier B**(DeprecationWarning → 1 マイナーバージョン後に削除)。

## 2. 計画

### Step 1: 候補パス探索の段階的縮小(Phase DR2/DR3)

**現状(問題):**
```python
def _candidates() -> list[Path]:
    p: list[Path] = []
    if v := os.environ.get("ARI_REGISTRIES_FILE"):
        p.append(Path(v))
    p.append(Path.cwd() / ".ari" / "registries.yaml")
    p.append(Path.home() / ".ari" / "registries.yaml")  # ← deprecated
    return p
```

**DR2(警告のみ):**
```python
def _candidates(checkpoint_dir: Path | None = None) -> list[Path]:
    p: list[Path] = []
    if v := os.environ.get("ARI_REGISTRIES_FILE"):
        p.append(Path(v))
    if checkpoint_dir is not None:
        p.append(checkpoint_dir / ".ari" / "registries.yaml")  # ← 新: project-scoped
    p.append(Path.cwd() / ".ari" / "registries.yaml")

    legacy = Path.home() / ".ari" / "registries.yaml"
    if legacy.exists():
        from ari._deprecation import warn_deprecated_path
        warn_deprecated_path(
            legacy,
            replacement=f"{checkpoint_dir}/.ari/registries.yaml or ARI_REGISTRIES_FILE env",
        )
        p.append(legacy)
    return p
```

**DR5 = v1.0(削除):**
- 上記の `legacy` 探索ブロックを完全削除
- v1.0 リリースで `~/.ari/registries.yaml` を持つユーザは `ARI_REGISTRIES_FILE` 必須

### Step 2: エラーメッセージの修正(Phase DR2)

`publish/backends/ari_registry.py:98`

**現状(問題):**
```python
raise CloneError(
    "no ari-registry configured. Set ARI_REGISTRY_URL or write ~/.ari/registries.yaml"
)
```

**修正:**
```python
raise CloneError(
    "no ari-registry configured. Set ARI_REGISTRY_URL, "
    "or write registries.yaml in your checkpoint or working directory "
    "(see docs/registry.md for format). "
    "Note: ~/.ari/ paths are deprecated and will be removed in v1.0."
)
```

ユーザを **新しい場所** に誘導する。`~/.ari/` を「使うな」と明示。

### Step 3: API シグネチャ拡張(Phase DR3)

`_candidates` が **`checkpoint_dir`** を受け取るように拡張(後方互換のためデフォルト None)。
`publish()` `promote()` の呼び出し側で `checkpoint_dir` を渡すように追加。

**重要:** **公開シグネチャは変えない**。`_candidates` は内部関数(prefix `_`)、`publish()` は既存引数に
オプショナル追加のみ。

```python
def publish(
    *,
    checkpoint_dir: Path | None = None,  # ← 追加(オプショナル)
    target: str = ...,
    ...
) -> PublishRecord:
    ...
```

### Step 4: zenodo / gh / local_tarball 監査(Phase DR2)

`publish/backends/{zenodo,gh,local_tarball}.py` を監査し、`~/.ari/` 参照がないことを確認。
監査結果を `docs/refactor_audit.md` に追記(新規参照ゼロを期待)。

## 3. 触らない範囲

- 4 バックエンド(`local_tarball`, `ari_registry`, `zenodo`, `gh`)の公開関数のシグネチャ
- アーティファクト構造(README.md, RESULTS.md, code/, publish.yaml, sha256.txt)
- バックエンド選択ロジック(`publish/__init__.py:_load_backend`)

## 4. 挙動保証チェックリスト

PR-DR2/DR3 の merge 前に必ず実施:

- [ ] `pytest ari-core/tests/test_publish*.py -q` がグリーン(あれば)
- [ ] `pytest ari-core/tests/test_clone.py -q` がグリーン(registries.yaml 探索を間接利用)
- [ ] **既存ユーザシナリオ**: `~/.ari/registries.yaml` を持つ環境で `ari publish ...` が DR2 段階では警告付きで動作
- [ ] **新規ユーザシナリオ**: `{checkpoint}/.ari/registries.yaml` または `ARI_REGISTRIES_FILE` のみで動作
- [ ] エラーメッセージが新表記("write registries.yaml in your checkpoint...")で表示
- [ ] `grep -rn "~/.ari" ari-core/ari/publish/ --include="*.py"` のヒットが `_deprecation` 経由のみ

## 5. 注意事項

- `publish/__init__.py` 内では新規の `~/.ari/` 参照を作らない
- `_load_backend()` のロード判定で URL スキーム以外の判定を加えない(疎結合維持)

---

## 実装完了後の削除

**DR2〜DR3 の関連 PR がマージされ、§4 のチェックリストすべて合格した時点で本ファイルを削除する。** v1.0 で DR5 が完了したらマスター計画と合わせて削除。

恒久化する内容:
- §2 Step 1〜2 の方針 → `docs/registry.md` の「設定ファイルの所在」節
- §2 Step 3 の API 拡張 → 実コード docstring に反映
