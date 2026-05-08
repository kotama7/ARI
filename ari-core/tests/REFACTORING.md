# ari-core/tests/ リファクタリング計画(テスト汚染対処)

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../../REFACTORING.md](../../REFACTORING.md)
> 関連: [../../DEPRECATION_REMOVAL.md](../../DEPRECATION_REMOVAL.md) Tier D

## 0. 挙動保証契約

- 既存テストの **アサーション内容** を変えない(同じことを検証する)
- テスト実行時間を**有意に増加させない**(目安: ±10% 以内)
- pytest fixtures(`tmp_path`, `monkeypatch`)の使い方を統一
- `pytest ari-core/tests/ -q` の合格テスト数が変わらない(増えてもよい、減ってはならない)

## 1. 監査結果

### 1-1. 不正書き込みの懸念(コード検査必要)

| ファイル | 行 | 懸念 | 重要度 |
|---|---|---|---|
| `tests/test_ollama_gpu.py` | 25, 125, 150, 175, 190 | `_st._settings_path.write_text(...)` — `viz/state.py` のグローバル変数を書き換え | **高**(monkeypatch が無いと CI 環境を汚染) |
| `tests/test_letta_restart_live.py` | 43 | `Path.home() / ".ari" / "letta-pid"` を env フォールバックとして読む | **中**(live integration、ローカル環境に依存) |
| `tests/test_settings_roundtrip.py` | 8 | docstring に `~/.ari/settings.json` 言及 | 低(コメント修正のみ) |
| `tests/test_clone.py` | 190 | docstring に `~/.ari/registries.yaml` 言及 | 低 |
| `tests/test_paths.py` | 131 | コメントに `no global ~/.ari anymore` | 低(コメントは正しい現状) |

### 1-2. 適切に tmp_path / monkeypatch を使っているテスト(参考)
`tests/test_clone.py` の大半、`tests/test_viz_memory_api.py` の `ckpt.mkdir()` 等は tmp_path 配下なので問題なし。

## 2. 計画

### Step 1: `test_ollama_gpu.py` の monkeypatch 化(Phase DR4、最優先)

**現状を確認:** PR 着手時に `cat ari-core/tests/test_ollama_gpu.py` を読み、各 `_st._settings_path.write_text(...)` の周辺で `monkeypatch.setattr(_st, "_settings_path", tmp_path / "settings.json")` 等の明示的な切り替えがあるか確認する。

**ありそうなパターン:**

**Case A: monkeypatch あり(問題なし)**
```python
def test_xxx(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(_st, "_settings_path", settings)
    settings.write_text("{}")
    ...
```

**Case B: monkeypatch なし(問題)**
```python
def test_xxx():
    _st._settings_path.write_text(json.dumps({...}))  # ← グローバル変数を直接書き換え
    ...
```

**修正方針(Case B の場合):**
```python
def test_xxx(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(_st, "_settings_path", settings)
    settings.write_text(json.dumps({...}))
    ...
```

**確認手順:**
1. `tests/test_ollama_gpu.py` を Read で全文確認
2. 各テスト関数のシグネチャと書き込み行を対照
3. monkeypatch されていない箇所をリストアップ
4. fixtures を使うように修正

### Step 2: `test_letta_restart_live.py` の HOME 隔離(Phase DR4)

**現状(問題):**
```python
os.environ.get("ARI_LETTA_PIDFILE", str(Path.home() / ".ari" / "letta-pid"))
```
**Live integration テストとはいえ、CI 環境の `~/.ari/letta-pid` を勝手に読み書きするのは危険**。

**修正:**
```python
@pytest.fixture
def letta_pidfile(tmp_path, monkeypatch):
    pid = tmp_path / "letta-pid"
    monkeypatch.setenv("ARI_LETTA_PIDFILE", str(pid))
    return pid

def test_xxx(letta_pidfile):
    ...
```

**注意:** Live integration テストはモック不可なので、Letta server 起動に必要な設定(`LETTA_HOST` 等)はそのまま。
PID ファイルの所在のみ tmp_path に閉じ込める。

### Step 3: docstring・コメント修正(Phase DR4)

| ファイル | 修正 |
|---|---|
| `test_settings_roundtrip.py:8` | docstring を「現状: settings.json は project-scoped」に書き直す |
| `test_clone.py:190` | docstring の `~/.ari/registries.yaml` を「ARI_REGISTRIES_FILE env または `{cwd}/.ari/registries.yaml`」へ |
| `test_paths.py:131` | 既に正しい("no global ~/.ari anymore")— **修正不要** |

### Step 4: 共通 fixture の整備(Phase DR4)

`ari-core/tests/conftest.py`(または既存に追記):

```python
@pytest.fixture(autouse=True)
def isolated_user_home(monkeypatch, tmp_path):
    """Redirect ~ to a tmp dir for all tests, preventing accidental writes
    to the real $HOME/.ari directory.
    """
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    # Also patch Path.home() if it's cached anywhere
    return fake_home
```

**ただし注意:** `autouse=True` を全テストで強制すると `~/.ari/registries.yaml` を意図的にテストする integration test が落ちる可能性。慎重に検討:
- **オプション A**: `autouse=True` をデフォルトに、`@pytest.mark.allow_real_home` で個別に opt-out
- **オプション B**: opt-in (`@pytest.mark.isolated_home`)、ただし忘れやすい

**推奨**: オプション A(安全側)。

### Step 5: CI ガード(Phase DR4)

`.github/workflows/refactor-guards.yml` に [DEPRECATION_REMOVAL.md §8-2](../../DEPRECATION_REMOVAL.md):

```yaml
- name: Run tests with monitored HOME
  run: |
    export HOME=$RUNNER_TEMP/fake_home
    mkdir -p $HOME
    pytest ari-core/tests/ -q
    if [ -d "$HOME/.ari" ]; then
      echo "::error::Tests created $HOME/.ari/ — see ari-core/tests/REFACTORING.md"
      ls -la "$HOME/.ari"
      exit 1
    fi
```

### Step 6: 新規テスト追加(Phase DR0)

[DEPRECATION_REMOVAL.md §8-1](../../DEPRECATION_REMOVAL.md) で予告した
`tests/test_no_user_home_writes.py`:

```python
def test_no_writes_to_user_home(tmp_path, monkeypatch):
    """ari status / projects / show が ~/.ari/ に書き込まないことを保証。"""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    # 最小限のコマンド(LLM 不要)
    result = subprocess.run(
        ["ari", "projects", "--checkpoint-dir", str(checkpoint_fixture)],
        capture_output=True, env=os.environ.copy(),
    )
    assert result.returncode == 0

    ari_dir = fake_home / ".ari"
    if ari_dir.exists():
        offending = list(ari_dir.rglob("*"))
        pytest.fail(f"Unexpected writes to ~/.ari/: {offending}")
```

## 3. 順序

DR4 PR の中でも以下の順:

1. **Step 6**: 新規テスト追加(失敗状態を可視化)
2. **Step 1**: `test_ollama_gpu.py` 修正(高重要度)
3. **Step 2**: `test_letta_restart_live.py` 修正(中)
4. **Step 4**: 共通 fixture 整備(autouse 設計の決定)
5. **Step 3**: docstring 修正(低、最後でよい)
6. **Step 5**: CI ガード追加(全テスト緑になってから)

## 4. 挙動保証チェックリスト

- [ ] `pytest ari-core/tests/ -q` がグリーン(全件)
- [ ] `pytest ari-core/tests/test_ollama_gpu.py -v` がグリーン
- [ ] `pytest ari-core/tests/test_no_user_home_writes.py -v` がグリーン
- [ ] テスト実行後に `ls $HOME/.ari/ 2>&1` が "No such file" を返す(クリーンな環境で確認)
- [ ] CI ジョブのログに `~/.ari/` 作成メッセージがない
- [ ] テスト実行時間が DR 前後で ±10% 以内

## 5. スキル側テストへの波及(参考)

`ari-skill-memory/tests/test_letta_live_integration.py:216` も同様の問題:
```python
"ARI_LETTA_PIDFILE", os.path.expanduser("~/.ari/letta.pid"),
```

**本計画書の対象外**(スキル側で個別対応すべき)だが、`ari-skill-memory/REFACTORING.md` に同様の注意点を追加するか、スキル側監査を別 PR で実施することを推奨。

---

## 実装完了後の削除

**Phase DR4 の関連 PR がマージされ、§4 のチェックリストすべて合格した時点で本ファイルを削除する。**

恒久化する内容:
- §2 Step 4 共通 fixture → `ari-core/tests/conftest.py` に実装
- §2 Step 5 CI ガード → `.github/workflows/refactor-guards.yml`
- §2 Step 6 新規テスト → `tests/test_no_user_home_writes.py`
