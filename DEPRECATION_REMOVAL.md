# ARI 廃止機能・不正パス削除計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [REFACTORING.md](REFACTORING.md) §13 から本書を参照。

## 0. 設計目的

ARI v0.5.0 のリリースノートでは「`~/.ari/` グローバル状態を廃止」と宣言されたが、**実コードには 13 箇所の `~/.ari/` 直接参照が残存**している。同時に v0.5→v0.7 の移行債務、廃止予定 env エイリアス、廃止予定 CLI フィールド等が本流に混在している。

本計画は以下を体系的に対処する:
1. **不正パス参照の根絶**: `~/.ari/` への書き込み・読み込みフォールバックの削除またはチェックポイントスコープへの置換
2. **廃止機能の隔離・削除**: 真に削除可能なものは削除、互換のため残すものは `ari/migrations/v05_to_v07/` へ隔離(リファクタ計画 Phase 5 と整合)
3. **テストの不正書き込み防止**: tmp_path 未使用のテストを修正、CI で `~/.ari/` への書き込み検出を導入

## 1. 監査結果(file:line)

### 1-1. `~/.ari/` パスへのアクティブ書き込み・参照(13 箇所)

| # | ファイル | 行 | 種別 | 既定動作 |
|---|---|---|---|---|
| 1 | `ari/memory/file_client.py` | 25 | **デフォルト引数** `path: str = "~/.ari/memory.json"` | 呼び出し側が path を渡さないと `~/.ari/` を作る |
| 2 | `ari/memory_cli.py` | 111 | `global_path = Path.home() / ".ari" / "global_memory.jsonl"` | 旧 global memory ファイルの参照(削除コマンド経路) |
| 3 | `ari/memory_cli.py` | 306 | `Path.home() / ".ari/letta-venv"` env フォールバック | Letta venv が `~/.ari/` 配下に作られる |
| 4 | `ari/memory/auto_migrate.py` | 43 | `Path.home() / ".ari" / "global_memory.jsonl"` | v0.5→v0.6 移行ソース(**合法 — 触らない**) |
| 5 | `ari/publish/backends/ari_registry.py` | 29 | `Path.home() / ".ari" / "registries.yaml"` 候補パス | 環境設定なしでも `~/.ari/` を読みに行く |
| 6 | `ari/publish/backends/ari_registry.py` | 98 | エラーメッセージで `~/.ari/registries.yaml` を案内 | ユーザを誤誘導 |
| 7 | `ari/clone/resolvers/ari.py` | 29 | `Path.home() / ".ari" / "registries.yaml"` 候補パス | 同上 |
| 8 | `ari/clone/resolvers/ari.py` | 78 | エラーメッセージで `~/.ari/registries.yaml` を案内 | 同上 |
| 9 | `ari/registry/app.py` | 29 | `Path.home() / ".ari" / "registry-data"` env フォールバック | レジストリサーバが `~/.ari/` に書き込む |
| 10 | `ari/registry/cli.py` | 20 | `Path.home() / ".ari" / "registry-data"` env フォールバック | 同上 |
| 11 | `ari/viz/api_publish.py` | 24 | `_SETTINGS_PATH = Path(... or Path.home() / ".ari" / "publish.yaml")` | ダッシュボードからの publish 設定が `~/.ari/` に書き込まれる |
| 12 | `ari/core.py` | 91 | docstring に `~/.ari` 言及 | コメント — 修正 |
| 13 | `ari/paths.py` | 113, 各種 | docstring に `~/.ari` 言及 | コメント — 修正 |

### 1-2. 廃止機能(本流コード混在、48 occurrences のうち critical 件)

| 由来 | 性質 | 対処 |
|---|---|---|
| `cli.py:246–305 backfill_node_reports` | v0.7 初回起動時の node_report.json 自動作成 | **隔離**(Phase 5: `ari/migrations/v05_to_v07/`) |
| `cli.py:1274–1275, 1436–1437 maybe_auto_migrate` 呼び出し | run / resume 時の v0.5 → v0.6 メモリ移行 | **隔離**(Phase 5) |
| `cli.py:1617 score = ""` | score field deprecated | **削除予告** → 警告 → v1.0 削除 |
| `viz/api_experiment.py:397 ARI_MODEL_REPLICATOR` alias | env 名の旧エイリアス | **DeprecationWarning** → v1.0 削除 |
| `viz/api_state.py:649, 660, 1086, 1101` legacy 系 | 旧サマリ/orphan 処理 | **保持**(古い checkpoint 互換のため) |
| `pipeline.py:1223` legacy criteria 経路 | 旧 criteria ファイル不在時のフォールバック | **保持**(後方互換) |
| `evaluator/llm_evaluator.py:586–589` legacy 5-axis | 旧軸スコアフォールバック | **隔離**(Phase 5) |
| `orchestrator/node_report.py:650 reconstruct_report_from_legacy` | 旧 tree.json から node_report 再構築 | **隔離**(Phase 5) |

### 1-3. テストの汚染箇所

| ファイル | 行 | 懸念 |
|---|---|---|
| `tests/test_ollama_gpu.py` | 25, 125, 150, 175, 190 | `_st._settings_path.write_text(...)` — monkeypatch を経由しているか要監査 |
| `tests/test_letta_restart_live.py` | 43 | `Path.home() / ".ari" / "letta-pid"` を env フォールバックとして読む(live integration テスト、ローカル環境を汚染) |
| `ari-skill-memory/tests/test_letta_live_integration.py` | 216 | `os.path.expanduser("~/.ari/letta.pid")` — 同上 |
| `tests/test_settings_roundtrip.py` | 8 | コメントに `~/.ari/settings.json` 言及(コメントのみ、修正のみ) |
| `tests/test_clone.py` | 190 | docstring に `~/.ari/registries.yaml` 言及(コメントのみ) |
| `tests/test_paths.py` | 131 | コメント |

## 2. Tier 分類(対処方針)

| Tier | 性質 | 対処 | 例 |
|---|---|---|---|
| **A** | 真に不要 | **即削除** | `memory/file_client.py:25` の `~/.ari/memory.json` デフォルト引数(v0.5 で廃止と宣言済み) |
| **B** | フォールバックとして機能中、ユーザ依存リスクあり | **DeprecationWarning → 1 マイナーバージョン後に削除** | `publish/backends/ari_registry.py:29` `clone/resolvers/ari.py:29` `registry/{app,cli}.py` `viz/api_publish.py:24` |
| **C** | 後方互換のため必須(古い checkpoint が読める必要) | **削除せず隔離**(リファクタ計画 Phase 5 で `ari/migrations/v05_to_v07/` へ) | `auto_migrate.py` `reconstruct_report_from_legacy` `backfill_node_reports` |
| **D** | テスト固有の不正書き込み | **tmp_path / monkeypatch で修正、CI で再発防止** | `test_ollama_gpu.py` `test_letta_restart_live.py` |

## 3. ファイル別対処計画

詳細はサブ計画書を参照:

| 対象領域 | サブ計画書 | 対処 Tier |
|---|---|---|
| `ari/memory/`, `ari/memory_cli.py` | [ari-core/ari/memory/REFACTORING.md](ari-core/ari/memory/REFACTORING.md) | A + B + C |
| `ari/publish/` | [ari-core/ari/publish/REFACTORING.md](ari-core/ari/publish/REFACTORING.md) | B |
| `ari/clone/` | [ari-core/ari/clone/REFACTORING.md](ari-core/ari/clone/REFACTORING.md) | B |
| `ari/registry/` | [ari-core/ari/registry/REFACTORING.md](ari-core/ari/registry/REFACTORING.md) | B |
| `ari/viz/api_publish.py` | [ari-core/ari/viz/REFACTORING.md](ari-core/ari/viz/REFACTORING.md) Step 3(本書で追加) | B |
| `ari/cli.py` の deprecated 機能 | [ari-core/REFACTORING.md](ari-core/REFACTORING.md) Phase 5 | C(隔離) |
| テスト | [ari-core/tests/REFACTORING.md](ari-core/tests/REFACTORING.md) | D |

## 4. 挙動保証契約

[REFACTORING.md §2](REFACTORING.md) と並ぶ厳格契約:

### 4-1. 削除・隔離フェーズ中(Phase DR0〜DR3)
- **既存 `~/.ari/` 配下にファイルを持つユーザは引き続き動く**(警告は出るが動作する)
- **`ari run` / `ari resume` / `ari paper` の出力が DR フェーズ前後で完全一致**(モック LLM、固定 seed)
- v0.5 / v0.6 / v0.7 で作成した既存チェックポイントが読める

### 4-2. 削除後(Phase DR4 = v1.0)
- v1.0 以降は `~/.ari/` フォールバックを完全に削除
- 古いユーザは v0.7→v1.0 マイグレーションガイド([docs/howto/migration.md](docs/howto/migration.md))に従って移行
- v0.5 以前の checkpoint は `ari migrate` コマンド経由でしか開けない(自動移行は終了)

## 5. Phase DR 計画(リファクタリング Phase と並走)

| Phase | 内容 | 互換破壊 | PR |
|---|---|---|---|
| **DR0** | 監査の確定(本書の §1 を `docs/refactor_audit.md` に転記)+ DeprecationWarning ヘルパ実装 | なし | 1 |
| **DR1** | Tier A 即削除: `memory/file_client.py:25` の `~/.ari/memory.json` デフォルト引数を**必須引数化**(または `raise ValueError`) | **微小**(明示パス必須化) | 1 |
| **DR2** | Tier B に DeprecationWarning 追加: `~/.ari/` フォールバックを使ったときに警告 | なし(警告のみ) | 1 |
| **DR3** | Tier B のフォールバック先を **チェックポイントスコープ** に置換: `~/.ari/registries.yaml` → `{checkpoint}/.ari/registries.yaml` 等 | なし(`~/.ari/` も読みに行くが警告) | 2〜3 |
| **DR4** | テスト修正(Tier D): tmp_path / monkeypatch 不徹底箇所の修正 + CI で `~/.ari/` 書き込み検出 | なし | 1 |
| **DR5(将来 v1.0)** | Tier B フォールバックの**完全削除** + v0.5 互換 `auto_migrate` の削除 | **互換破壊**(v1.0 に予約)| 別リリース |

DR0〜DR4 は本リファクタの範囲。DR5 は v1.0 リリース PR で実施。

## 6. DeprecationWarning 共通ヘルパ

`ari/_deprecation.py`(新設):

```python
import warnings
from pathlib import Path

def warn_deprecated_path(path: Path, replacement: str, removal_version: str = "v1.0") -> None:
    """Emit a DeprecationWarning when an `~/.ari/`-style path is touched.

    Args:
        path: The deprecated path being accessed.
        replacement: Human-readable description of the new location.
        removal_version: Version when this fallback will be removed.
    """
    warnings.warn(
        f"Path {path} is deprecated and will be removed in {removal_version}. "
        f"Use {replacement} instead.",
        DeprecationWarning,
        stacklevel=3,
    )

def warn_deprecated_env(name: str, replacement: str, removal_version: str = "v1.0") -> None:
    """Emit a DeprecationWarning for a deprecated environment variable."""
    ...

def warn_deprecated_field(model: str, field: str, replacement: str, removal_version: str = "v1.0") -> None:
    """Emit a DeprecationWarning for a deprecated config/CLI field."""
    ...
```

各 Tier B 箇所では:
```python
# 例: publish/backends/ari_registry.py
fallback_path = Path.home() / ".ari" / "registries.yaml"
if fallback_path.exists():
    from ari._deprecation import warn_deprecated_path
    warn_deprecated_path(fallback_path, "{checkpoint}/settings.json registries section")
    # ... 既存の読み込みロジック
```

## 7. v1.0 削除予告対象(CHANGELOG に明記)

DR5 で削除予定として `CHANGELOG.md` に予告すべき項目:

- `~/.ari/registries.yaml` フォールバック → `{checkpoint}/settings.json` の `registries` セクションへ統一
- `~/.ari/registry-data` フォールバック → `{checkpoint}/.ari_registry/` へ
- `~/.ari/publish.yaml` フォールバック → `{checkpoint}/settings.json` の `publish` セクションへ
- `~/.ari/global_memory.jsonl` 自動移行 → `ari migrate memory <ckpt>` コマンド経由のみに
- `~/.ari/letta-venv` env フォールバック → `ARI_LETTA_VENV` 必須化
- `ARI_MODEL_REPLICATOR` env エイリアス → `ARI_MODEL_REPLICATOR_LEGACY` (削除予定) または完全削除
- `score` フィールド(`cli.py:1617`)→ 完全削除
- `auto_migrate` の自動呼び出し → 明示的 `ari migrate` コマンドへ

## 8. テスト戦略

### 8-1. 回帰テスト(DR0 で新設)

`ari-core/tests/test_no_user_home_writes.py`:
```python
def test_no_writes_to_user_home(monkeypatch, tmp_path):
    """ari run / resume / paper が ~/.ari/ に書き込まないことを保証。"""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    # 最小限の dry-run を実行
    subprocess.run(["ari", "status", str(checkpoint_fixture)], check=True)

    # ~/.ari が作られていないこと
    assert not (fake_home / ".ari").exists(), \
        f"unexpected write to ~/.ari/: {list((fake_home / '.ari').rglob('*'))}"
```

### 8-2. CI ガード(DR4 で導入)

`.github/workflows/refactor-guards.yml` に:
```yaml
- name: Check no new ~/.ari references
  run: |
    NEW=$(git diff origin/main HEAD -- 'ari-core/ari/**.py' | grep -c '+.*Path\.home.*\.ari\|+.*~/\.ari' || true)
    if [ "$NEW" -gt 0 ]; then
      echo "::error::New ~/.ari/ references introduced"
      exit 1
    fi
```

### 8-3. 個別テスト修正
[ari-core/tests/REFACTORING.md](ari-core/tests/REFACTORING.md) を参照。

## 9. 受け入れ基準

DR0〜DR4 完了時点:

- [ ] `grep -rn "Path.home().*\.ari\|os.path.expanduser.*\.ari" ari-core/ari/ --include="*.py" | grep -v "auto_migrate\|migrations/" | wc -l` が **0**(migrations モジュール除く)
- [ ] `grep -rn "~/.ari" ari-core/ari/ --include="*.py" | grep -v "DeprecationWarning\|migrations/\|# .*~/\.ari" | wc -l` が **0**
- [ ] `pytest ari-core/tests/ -q` がグリーン
- [ ] `pytest ari-core/tests/test_no_user_home_writes.py -v` がグリーン
- [ ] 既存 v0.7 checkpoint で `ari paper` が DR 前後で同じ paper を出す
- [ ] `~/.ari/registries.yaml` を持つユーザが警告を見つつ動作する(integration test)
- [ ] CHANGELOG に v1.0 削除予告セクションが追加されている

## 10. リスク

| リスク | 緩和策 |
|---|---|
| `~/.ari/registries.yaml` を実運用しているユーザの挙動破壊 | DR2 で警告のみ、DR3 で `{checkpoint}` も読むが `~/.ari/` も読み続ける、DR5 = v1.0 で削除 |
| Letta venv のパス変更で既存インストール再構築 | `ARI_LETTA_VENV` env 必須化と移行ガイド([docs/howto/migration.md](docs/howto/migration.md))明示 |
| `auto_migrate` を呼ばない構成で v0.5 checkpoint が読めなくなる | C tier として隔離のみ。明示的 `ari migrate` コマンドで呼び出し可 |
| テスト修正中に CI が無関係に red になる | DR4 を独立 PR にして、機能修正と切り分け |
| ARI_MODEL_REPLICATOR 廃止予告で外部スクリプトが壊れる | 警告期間 1 マイナーバージョン、CHANGELOG で周知 |

---

## 実装完了後の削除

**Phase DR0〜DR4 の全 PR がマージされ、§9 受け入れ基準すべて通過した時点で本ファイルおよび関連サブ計画書を削除する。** マスター計画 [REFACTORING.md](REFACTORING.md) の deletion バッチに含めること。

恒久化する内容:
- §1 監査結果 → `docs/refactor_audit.md` に転記済み
- §2 Tier 分類方針 → `CONTRIBUTING.md` の「廃止予告 → 警告 → 削除」プロセスとして恒久化
- §6 DeprecationWarning ヘルパ → 実コード(`ari/_deprecation.py`)が代替
- §7 v1.0 削除予告対象 → `CHANGELOG.md` 内
- §8-2 CI ガード → `.github/workflows/refactor-guards.yml` が代替
