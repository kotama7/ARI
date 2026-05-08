# ari-core リファクタリング計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../REFACTORING.md](../REFACTORING.md)

## 0. 挙動保証契約

[マスター計画 §2](../REFACTORING.md) の契約を厳守する。特に本計画は以下を絶対に変えない:

- `ari` CLI の全コマンド体系・引数・既定値
- `pipeline.run_pipeline()` `core.build_runtime()` の公開シグネチャ
- `tree.json` `results.json` `nodes_tree.json` `node_report.json` の読み書きスキーマ
- `workflow.yaml` の解釈(stage 名・loop_back セマンティクス・テンプレート展開)
- 環境変数の名前・既定値・フォールバック順
- LLM コスト計上 (`cost_tracker`) のキー・形式

## 1. 対象範囲

このリポジトリ(`ari-core/`)配下のうち以下に手を入れる。サブディレクトリは別計画書を参照。

| 対象 | 行数 | 種別 | 計画書 |
|---|---|---|---|
| `ari/cli.py` | 1,962 | 分割 | 本書 §3 |
| `ari/pipeline.py` | 1,641 | 分割(パッケージ化) | 本書 §4 |
| `ari/core.py` | 245 | リファイン(分割なし) | 本書 §5 |
| 新設: `ari/checkpoint.py` | — | 共有モジュール新設 | 本書 §6 |
| 新設: `ari/config/finder.py` | — | 共有モジュール新設 | 本書 §6 |
| 新設: `ari/public/` | — | 公開 API 切り出し | 本書 §7 |
| 新設: `ari/migrations/v05_to_v07/` | — | 移行債務隔離 | 本書 §8 |
| `ari/agent/` | 2,440 | 別計画書 | [ari/agent/REFACTORING.md](ari/agent/REFACTORING.md) |
| `ari/viz/` | 6,104 | 別計画書 | [ari/viz/REFACTORING.md](ari/viz/REFACTORING.md) |
| `ari/orchestrator/` | 2,622 | 別計画書 | [ari/orchestrator/REFACTORING.md](ari/orchestrator/REFACTORING.md) |

**変更しない領域**: `ari/llm/` `ari/mcp/` `ari/memory/` `ari/evaluator/` `ari/clone/` `ari/publish/` `ari/registry/` `ari/schemas/` `ari/cli_ear.py` `ari/lineage.py` `ari/env_detect.py` `ari/pidfile.py` `ari/memory_cli.py`

## 2. ディレクトリ責務マップ(現状ドキュメント化)

リファクタ後も維持する責務境界:

| ディレクトリ | 責務 |
|---|---|
| `ari/agent/` | ReAct ループ、環境キャプチャ、ワークフローヒント生成 |
| `ari/llm/` | litellm の薄いラッパ |
| `ari/mcp/` | MCP プロトコルクライアント、stdio スキルサーバ寿命管理 |
| `ari/memory/` | メモリバックエンド抽象(Letta / File / Local) |
| `ari/evaluator/` | LLM 評価器と動的軸生成 |
| `ari/orchestrator/` | BFTS、lineage decision、ノードモデル |
| `ari/clone/` | EAR バンドルダウンロード |
| `ari/publish/` | EAR バンドル公開 |
| `ari/registry/` | FastAPI 製アーティファクトサーバ |
| `ari/viz/` | HTTP/WebSocket サーバ + REST API 群 |
| `ari/schemas/` | JSON スキーマ |

トップレベル `.py`:

| ファイル | 責務 |
|---|---|
| `ari/cli.py` | Typer CLI ディスパッチャ(分割対象) |
| `ari/cli_ear.py` | EAR キュレーション CLI |
| `ari/core.py` | ランタイムビルダー |
| `ari/pipeline.py` | YAML 駆動パイプラインエンジン(分割対象) |
| `ari/lineage.py` | チェックポイント祖先ナビゲーション |
| `ari/config.py` | Pydantic Config モデル |
| `ari/paths.py` | `PathManager`(中央パス解決) |
| `ari/container.py` | Docker/Singularity ランタイム |
| `ari/env_detect.py` | スケジューラ検出 |
| `ari/cost_tracker.py` | LLM コスト計上 |
| `ari/pidfile.py` | PID ファイル管理 |
| `ari/memory_cli.py` | メモリバックエンド管理 CLI |

## 3. `cli.py` 分割計画 (Phase 3, PR-3A)

現状: 1,962 行・25 トップレベルシンボル。

### 分割マッピング

| 新ファイル | 由来行 | 含めるシンボル |
|---|---|---|
| `ari/cli/__init__.py` | — | `app = typer.Typer()` のみを残し、各サブコマンドモジュールを import する薄い entry |
| `ari/cli/lineage.py` | L37–250 | `_load_lineage_decision_config` / `_mark_parent_terminated` / `_execute_lineage_decision` / `_build_idea_ctx_for_expand` |
| `ari/cli/bfts_loop.py` | L439–1100 | `_save_tree_incremental` / `_run_loop` |
| `ari/cli/run.py` | L375–1483 | `_resolve_cfg` / `_setup_logging` / `_apply_profile` / `run` / `resume` |
| `ari/cli/projects.py` | L1485–1873 | `paper` / `status` / `list_projects` / `show_project` |
| `ari/cli/commands.py` | L325–365, L1640–1962 | `cmd_clone` / `_safe_backup` / `delete_project` / `skills_list` / `viz` / `settings_cmd` |
| `ari/cli/migrate.py` | L251–324 | `cmd_migrate_node_reports`(後に Phase 5 で migrations へ移動) |

### 手順
1. `ari/cli/` ディレクトリと `__init__.py` を作成
2. **`ari/cli.py` を残したまま**新規ファイルへ関数定義をコピー
3. 旧 `cli.py` の関数本体を新規ファイルから import に置換、Typer デコレータは新規側に移す
4. 全コマンドの `--help` 出力を分割前後で比較(差分ゼロを確認)
5. `ari/cli.py` を削除し、`ari/cli/__init__.py` で `app` を再エクスポート
6. `pyproject.toml` / `setup.py` / `setup.cfg` の `entry_points` が `ari.cli:app` を指している場合、そのまま動くことを確認

### 重要な注意
- Typer の `@app.command()` デコレータは関数定義のあるモジュールで呼ぶ。`ari/cli/run.py` で `run` 関数定義 + デコレータを書き、`ari/cli/__init__.py` で `from ari.cli import run as _, resume as _, ...` のように import するだけで Typer に登録される。
- `_run_loop` は BFTS 並列ノード実行の中核。**コピー時にネスト関数のクロージャ参照を絶対に変えない**。

## 4. `pipeline.py` 分割計画 (Phase 3, PR-3C)

現状: 1,641 行。`ari/pipeline.py` を `ari/pipeline/` パッケージへ展開する。

### 分割マッピング

| 新ファイル | 由来行 | 含めるシンボル |
|---|---|---|
| `ari/pipeline/__init__.py` | — | `from .orchestrator import run_pipeline` 等の再エクスポート |
| `ari/pipeline/experiment_md.py` | L24–185 | `parse_metric_from_experiment_md` / `_extract_plan_sections` / `_build_auto_append_block` / `_promote_plan_to_experiment_md` |
| `ari/pipeline/yaml_loader.py` | L186–266 | `load_pipeline` / `load_disabled_stage_names` / `load_workflow` / `_resolve_templates` |
| `ari/pipeline/stage_control.py` | L267–325 | `_should_loop_back` / `_format_vlm_feedback` |
| `ari/pipeline/context_builder.py` | L326–460 | `build_best_nodes_context` / `_extract_keywords_from_nodes` |
| `ari/pipeline/stage_runner.py` | L461–892 | `_call_with_retry` / `_run_react_stage` / `_run_stage_subprocess` |
| `ari/pipeline/orchestrator.py` | L893–1641 | `build_scientific_data` / `run_pipeline` |

### 公開シンボルの後方互換
- `from ari.pipeline import run_pipeline, load_workflow, load_pipeline, build_best_nodes_context, _extract_plan_sections` がリファクタ後も動くこと(これらは `cli.py` `core.py` 等から import されている)
- `ari/pipeline/__init__.py` ですべて再エクスポート

### 手順
1. `ari/pipeline.py` を `ari/pipeline/__init__.py` にリネーム
2. 各クラスタ別ファイルを作成し、関数定義を移動
3. `__init__.py` を「import + 再エクスポートのみ」に縮小
4. `pytest -q ari-core/tests/test_pipeline.py` がグリーン
5. CLI 経由のスモーク: `ari paper <既存checkpoint>` が同じ paper を生成

## 5. `core.py` のリファイン (Phase 1 with PR-1A)

現状: 245 行。**分割しない**。だが env 直読みを `PathManager.from_env()` 経由に統一する。

### 変更点
- 既存の `os.environ.get("ARI_CHECKPOINT_DIR")` 等を `PathManager` に集約(§9 参照)
- 公開関数 `build_runtime()` `generate_paper_section()` のシグネチャは不変

## 6. 共有モジュール新設 (Phase 2)

### 6-1. `ari/checkpoint.py` (PR-2B)

**目的**: tree.json / nodes_tree.json / results.json の I/O が `cli.py:439–467` `cli.py:1690–1729` `viz/api_state.py:38–80` の 3 箇所で別実装されている重複を解消。

**公開関数**:
```python
def save_tree_json(checkpoint_dir: Path, tree: dict) -> None: ...
def load_tree_json(checkpoint_dir: Path) -> dict: ...
def save_nodes_tree_json(checkpoint_dir: Path, nodes: dict) -> None: ...
def load_nodes_tree_json(checkpoint_dir: Path) -> dict: ...
def save_results_json(checkpoint_dir: Path, results: dict) -> None: ...
def save_tree_incremental(checkpoint_dir: Path, tree: dict, throttle_sec: float = 0.5) -> None: ...
```

**保証**:
- ファイルパス・JSON スキーマ・throttle 挙動を完全に維持
- 既存 checkpoint との読み書き互換

### 6-2. `ari/config/finder.py` (PR-2A)

**目的**: workflow.yaml 探索が `cli.py:375–390 _resolve_cfg` `pipeline.py:221–239 load_workflow` `viz/server.py:107–150 _build_experiment_detail_config` の 3 箇所で別実装されている重複を解消。

**公開関数**:
```python
def find_workflow_yaml(checkpoint_dir: Path | None = None) -> Path | None:
    """探索順: checkpoint_dir → cwd → ari パッケージ同梱"""

def load_workflow_config(workflow_path: Path) -> dict:
    """workflow.yaml をパースし、テンプレート未展開の dict を返す"""

def find_profile_yaml(profile_name: str, checkpoint_dir: Path | None = None) -> Path | None: ...
```

**保証**:
- 探索順序を 3 箇所の現行実装と完全一致させる(優先順を変えない)
- 見つからなかった場合の例外型・メッセージを既存と同じ

## 7. 公開 API `ari/public/` 切り出し (Phase 4)

### 目的
スキル側が `ari-core` 内部に依存している実態(2 件・LOW):
- `ari-skill-coding/tests/test_server.py:102` → `import ari.container`
- `ari-skill-plot/src/server.py:28` → `from ari import cost_tracker`

これを「公開契約」として明示する。`ari/public/` は薄い再エクスポート層。

### 構成

```
ari/public/
├── __init__.py          # 公開シンボルの一覧コメントのみ
├── container.py         # from ari.container import ContainerConfig, run_shell_in_container, ...
├── cost_tracker.py      # from ari.cost_tracker import bootstrap_skill, record, ...
├── paths.py             # from ari.paths import PathManager
├── llm.py               # from ari.llm.client import LLMClient(将来統一に備えた export)
└── config_schema.py     # from ari.config import ARIConfig, LLMConfig, ...
```

### スキル側の移行
- [ari-skill-coding/REFACTORING.md](../ari-skill-coding/REFACTORING.md) を参照
- [ari-skill-plot/REFACTORING.md](../ari-skill-plot/REFACTORING.md) を参照

### 境界 CI
`ari-core/tests/test_public_api_boundary.py` を新設し、`ari-skill-*/` 配下の `from ari.X` import を AST で grep し、`ari.public.*` 以外を import していたらテスト失敗とする。

## 8. 移行債務隔離 `ari/migrations/v05_to_v07/` (Phase 5)

### 目的
v0.5 → v0.6 → v0.7 のバックワード互換コードが本流コードに混在している(48 箇所、上位 5 件):

| 由来 | 内容 |
|---|---|
| `cli.py:246–305` | `cmd_migrate_node_reports`(node_report 形式の移行) |
| `cli.py:1135–1352` 内のバックフィル | `backfill_node_reports`(初回読み込み時) |
| `memory/auto_migrate.py` | v0.5 メモリ JSONL → Letta 移行 |
| `evaluator/llm_evaluator.py:586–589` | legacy 5-axis スコアフォールバック |
| `orchestrator/node_report.py:650` | `reconstruct_report_from_legacy` |

### 移動先

```
ari/migrations/v05_to_v07/
├── __init__.py
├── node_reports.py     # cli.py L246–305 + node_report.py L650 を統合
├── memory.py            # memory/auto_migrate.py を移動
└── legacy_axes.py       # llm_evaluator.py L586–589 を関数として抽出
```

### 重要
- **削除ではなく隔離**。本流コードは `ari.migrations.v05_to_v07` を呼ぶ薄い shim を残す。
- v0.8 リリースノートで「v1.0 で削除予定」と予告。
- 既存 v0.5 / v0.6 / v0.7 チェックポイントが**読めなくなってはならない**。

## 9. 状態管理の単一化 (Phase 1)

### 課題
`ARI_CHECKPOINT_DIR` の env 直読みが 31 箇所に分散。挙動の同期がとれていない。

### PR-1A: `PathManager.from_env()` を唯一の env 入口に
`ari/paths.py` に以下を追加:
```python
@classmethod
def from_env(cls) -> "PathManager":
    """ARI_CHECKPOINT_DIR / ARI_MEMORY_PATH などを一括解釈"""
```

### PR-1B: 既存 env 直読みの置き換え
最小修正対象(段階的に):
- `ari/memory_cli.py:36`
- `ari/cost_tracker.py:197`
- `ari/lineage.py:56`
- `ari/viz/api_experiment.py:622`

### 受け入れ基準
- `grep -rn "os.environ\[.ARI_CHECKPOINT_DIR.\]\|os.environ.get(.ARI_CHECKPOINT_DIR" ari-core/ari/` のヒットが `paths.py` の `from_env` 内のみ
- 既存テストすべてグリーン
- 環境変数を未設定で `ari` を起動した際のエラーメッセージが既存と同じ

## 10. 挙動保証チェックリスト

各 PR で以下を実施・PR 本文に証跡を貼る:

- [ ] `ari --help` の差分が空
- [ ] `ari run --help` `ari resume --help` `ari paper --help` `ari viz --help` `ari status --help` `ari projects --help` `ari skills-list --help` `ari settings --help` の差分が空
- [ ] `ari paper <既存 v0.7 checkpoint>` が同じ paper を出す(diff で検証)
- [ ] `ari viz <既存 v0.7 checkpoint> --port 18765` を起動し、`/api/state` `/api/checkpoints` `/api/experiments` の JSON キー集合が変更前と一致
- [ ] `pytest ari-core/tests/ -q` がグリーン
- [ ] `git ls-files 'ari-core/ari/**.py' | xargs python -c "import ast,sys; [ast.parse(open(f).read()) for f in sys.argv[1:]]"` が成功(構文エラーなし)
- [ ] 公開シンボル(`ari/__init__.py` `ari/cli/__init__.py` `ari/pipeline/__init__.py`)の `__all__` または import 一覧の集合が、リファクタ前のトップレベル定義集合と一致

## 11-A. 廃止機能・不正パス対処(マスター §13 適用、Phase DR0〜DR4)

[DEPRECATION_REMOVAL.md](../DEPRECATION_REMOVAL.md) の方針を本書スコープに展開:

### 対象拡大(従来「変更不要」からの昇格)

| 領域 | サブ計画書 | Tier |
|---|---|---|
| `ari/memory/`, `ari/memory_cli.py` | [ari/memory/REFACTORING.md](ari/memory/REFACTORING.md) | A + B + C |
| `ari/publish/` | [ari/publish/REFACTORING.md](ari/publish/REFACTORING.md) | B |
| `ari/clone/` | [ari/clone/REFACTORING.md](ari/clone/REFACTORING.md) | B |
| `ari/registry/` | [ari/registry/REFACTORING.md](ari/registry/REFACTORING.md) | B |
| `ari/viz/api_publish.py` | [ari/viz/REFACTORING.md §3-5](ari/viz/REFACTORING.md) | B |
| `tests/` | [tests/REFACTORING.md](tests/REFACTORING.md) | D |

### 共通ヘルパ新設(Phase DR0)

`ari/_deprecation.py` を新設([DEPRECATION_REMOVAL.md §6](../DEPRECATION_REMOVAL.md)):
- `warn_deprecated_path(path, replacement, removal_version)`
- `warn_deprecated_env(name, replacement, removal_version)`
- `warn_deprecated_field(model, field, replacement, removal_version)`

### Phase 5(移行債務隔離)との連動

§8 の `ari/migrations/v05_to_v07/` は Tier C(後方互換のため隔離)を担う。
Phase DR3 の中で隔離移動を完了させる(Phase 5 と DR3 を同 PR にしてもよい)。

具体的に隔離する対象([§8](#8-移行債務隔離-arimigrationsv05_to_v07-phase-5)で既述):
- `cli.py:246–305 backfill_node_reports`
- `cli.py:1274–1275, 1436–1437 maybe_auto_migrate` 呼び出し
- `memory/auto_migrate.py` 全体
- `evaluator/llm_evaluator.py:586–589` legacy 5-axis
- `orchestrator/node_report.py:650 reconstruct_report_from_legacy`

## 11. Protocol 抽象化レイヤ `ari/protocols/`(マスター §11-3 適用)

### 目的
コア間の依存を**具象クラス → Protocol** に置き換え、疎結合(マスター §11-2)を強制する。
新規ディレクトリ `ari-core/ari/protocols/` を導入し、以下を定義する。

### 構成

```
ari-core/ari/protocols/
├── __init__.py         # Protocol 群の公開 import
├── llm.py              # LLMClient Protocol
├── mcp.py              # MCPClient Protocol
├── memory.py           # MemoryClient Protocol(既存 ABC を Protocol として再エクスポート)
├── node_store.py       # NodeStore Protocol(tree.json I/O 抽象)
├── prompt_loader.py    # PromptLoader Protocol
├── config_loader.py    # ConfigLoader Protocol
├── evaluator.py        # Evaluator Protocol
└── stage_runner.py     # StageRunner Protocol(pipeline 実行戦略)
```

### 各 Protocol の定義方針

| Protocol | 既存の具象 | Protocol 化の意図 |
|---|---|---|
| `LLMClient` | `ari/llm/client.py:LLMClient` | テスト用モック・他バックエンド差し替えを容易に |
| `MCPClient` | `ari/mcp/client.py:MCPClient` | スキル呼び出しの抽象化、テスト容易性 |
| `MemoryClient` | 既に ABC | 再エクスポートのみ(API 不変) |
| `NodeStore` | (新規)`ari/checkpoint.py` の関数群を IF 化 | tree.json I/O のテスト用 in-memory 実装が可能に |
| `PromptLoader` | (新規) | [PROMPTS_AND_CONFIG.md §2-2](../PROMPTS_AND_CONFIG.md) |
| `ConfigLoader` | (新規) | [PROMPTS_AND_CONFIG.md §2-3](../PROMPTS_AND_CONFIG.md) |
| `Evaluator` | `ari/evaluator/llm_evaluator.py:LLMEvaluator` | 評価戦略の差し替え([ari/evaluator/REFACTORING.md](ari/evaluator/REFACTORING.md)) |
| `StageRunner` | `pipeline.py:_run_react_stage / _run_stage_subprocess` | パイプライン実行戦略の差し替え |

### 移行手順(各 Protocol 共通)

1. `ari/protocols/X.py` に Protocol 定義を追加(既存具象から最小公開 IF を抽出)
2. 既存具象クラスが Protocol を満たすことを mypy/pyright で検証(構造的部分型)
3. 利用側の型ヒントを Protocol 型に変更(`AgentLoop(llm: LLMClient, ...)` → `AgentLoop(llm: protocols.LLMClient, ...)`)
4. 利用側の import を `from ari.protocols import LLMClient` に置き換え
5. `core.build_runtime()` で Protocol 型として依存を注入(具象クラスは Composition Root のみで参照)

### 受け入れ基準(本セクション)

- [ ] `ari/protocols/` 配下の Protocol すべてに対して、既存具象が `assert_type` または mypy で互換と判定される
- [ ] `agent/loop.py` `pipeline.py` `core.py` の主要依存が Protocol 型注釈に移行
- [ ] テスト用モック実装(in-memory `NodeStore`、ダミー `LLMClient`)が `ari-core/tests/` 配下に少なくとも 1 つ存在
- [ ] `from ari.protocols import LLMClient, MCPClient, MemoryClient, NodeStore, PromptLoader, ConfigLoader, Evaluator, StageRunner` が成功

### 公開 API との関係

[§7 `ari/public/`](#7-公開-api-aripublic-切り出し-phase-4) で「スキル向け公開 API」を定義する。
`ari/protocols/` は**コア内部の疎結合**のための仕組みで、両者は別物:
- `ari/public/`: スキル開発者向けの「壊さない」コントラクト
- `ari/protocols/`: コア内部の依存方向を制御する型レイヤ

ただし `PromptLoader` `ConfigLoader` のように **両方の利用者がいる** Protocol は、`ari/public/` から re-export する。

---

## 実装完了後の削除

**Phase 0〜6 の全 PR + Phase PC0〜PC8 がマージされた時点で本ファイルを削除する。** マスター計画 [../REFACTORING.md](../REFACTORING.md) と同じタイミング。

恒久化する内容(削除前に転記する先):
- §2 ディレクトリ責務マップ → `docs/architecture.md`
- §6 共有モジュールの公開関数 → docstring
- §7 `ari/public/` の境界 → `docs/extension_guide.md`
- §10 挙動保証チェックリストの一部 → `CONTRIBUTING.md`
- §11 Protocol 一覧と意図 → `docs/architecture.md` の「コア内部の型レイヤ」章 + `CONTRIBUTING.md` の「新規依存を増やすときは Protocol を経由する」規律
