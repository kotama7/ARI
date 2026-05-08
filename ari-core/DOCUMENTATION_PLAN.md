# ari-core ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

`ari-core/` 配下のコードレベルドキュメント:
- 各サブディレクトリの `__init__.py` モジュール docstring
- 公開シンボル(クラス・関数)の docstring
- `ari/public/`(リファクタ計画 Phase 4 で新設)の API リファレンス
- Pydantic Config モデル(`ari/config.py`)のフィールド docstring

実装挙動は変更しない。docstring と型ヒントのみ。

## 1. 現状(監査結果)

### 1-1. `__init__.py` docstring の状態

| ファイル | 状態 |
|---|---|
| `ari/__init__.py` | バージョン定義のみ(要監査) |
| `ari/agent/__init__.py` | **空** |
| `ari/llm/__init__.py` | **空** |
| `ari/mcp/__init__.py` | **空** |
| `ari/memory/__init__.py` | **空** |
| `ari/orchestrator/__init__.py` | **空** |
| `ari/viz/__init__.py` | `"""ARI viz package."""` のみ |
| `ari/evaluator/__init__.py` | 要監査 |
| `ari/clone/__init__.py` | 要監査 |
| `ari/publish/__init__.py` | 要監査 |
| `ari/registry/__init__.py` | 要監査 |
| `ari/schemas/__init__.py` | 要監査 |

### 1-2. その他コードレベルギャップ

- 公開クラスの一部(例: `LLMClient` `MCPClient` `MemoryClient` `Node` `BFTS`)は docstring があるが、**フィールド/メソッド単位での docstring が断片的**
- `ari/config.py` の Pydantic モデル(`ARIConfig` `LLMConfig` `SkillConfig` `BFTSConfig` `CheckpointConfig` 他)は **フィールド docstring がほぼ無い**
- `ari/public/` は未存在(リファクタ計画 Phase 4 で新設)
- リファレンス用のシンボル一覧(Sphinx/MkDocs 等の自動生成)が未整備

## 2. Phase D2-A: 各サブディレクトリの `__init__.py` docstring

各 `__init__.py` に以下のテンプレートで責務を明記する:

```python
"""ari.<package_name> — <one-line responsibility>.

<2-4 sentences explaining the package's role within ARI.>

Public symbols:
- <symbol>: <one-line description>
- <symbol>: <one-line description>

See also:
- docs/architecture.md (XX section)
- ari-core/REFACTORING.md (refactoring history if relevant)
"""
```

各サブディレクトリの記述内容(リファクタ計画 [ari-core/REFACTORING.md §2](REFACTORING.md) と整合):

| パッケージ | 責務(1 行) | 主な公開シンボル |
|---|---|---|
| `ari.agent` | ReAct ループ・環境キャプチャ・ワークフローヒント生成 | `AgentLoop`, `WorkflowHints`, `run_react`, `capture_env` |
| `ari.llm` | litellm の薄いラッパ | `LLMClient`, `LLMMessage`, `LLMResponse` |
| `ari.mcp` | MCP プロトコルクライアント、stdio スキルサーバ寿命管理 | `MCPClient` |
| `ari.memory` | メモリバックエンド抽象(Letta / File / Local)+ v0.5→v0.6 自動移行 | `MemoryClient`, `LettaMemoryClient`, `FileMemoryClient`, `LocalMemoryClient`, `maybe_auto_migrate` |
| `ari.evaluator` | LLM 評価器と動的軸生成 | `LLMEvaluator`, `MetricSpec`, `AxisDef`, `rubric_to_axes`, `plan_to_axes` |
| `ari.orchestrator` | BFTS、lineage decision、ノードモデル、スケジューラ | `Node`, `NodeStatus`, `NodeLabel`, `BFTS`, `Scheduler`, `LineageDecision`, `LineageState` |
| `ari.clone` | EAR バンドルダウンロード(file/https/ari/gh/doi リゾルバ) | `clone`, `CloneError`, `CloneResult` |
| `ari.publish` | EAR バンドル公開(local/registry/zenodo/gh バックエンド) | `publish`, `promote`, `PublishRecord`, `PublishError` |
| `ari.registry` | FastAPI 製アーティファクトサーバ | `build_app`, `FilesystemStorage`, `StorageError` |
| `ari.viz` | HTTP/WebSocket サーバと REST API 群(ダッシュボード) | `serve`, `main` |
| `ari.schemas` | JSON スキーマローダ | `load`, `schema_path` |

## 3. Phase D2-B: トップレベル `.py` の docstring

各ファイルの先頭にモジュール docstring を追加:

| ファイル | 責務 |
|---|---|
| `ari/cli.py`(分割後は `ari/cli/__init__.py`) | Typer CLI ディスパッチャ |
| `ari/cli_ear.py` | EAR キュレーション CLI |
| `ari/core.py` | ランタイムビルダー(エージェント・LLM・MCP・memory を一括組立) |
| `ari/pipeline.py`(分割後は `ari/pipeline/__init__.py`) | YAML 駆動パイプラインエンジン |
| `ari/lineage.py` | チェックポイント祖先ナビゲーション |
| `ari/config.py` | Pydantic Config モデル群 |
| `ari/paths.py` | `PathManager`(中央パス解決) |
| `ari/container.py` | Docker/Singularity ランタイム |
| `ari/env_detect.py` | スケジューラ検出(SLURM 等) |
| `ari/cost_tracker.py` | LLM コスト計上(litellm callback) |
| `ari/pidfile.py` | PID ファイル管理 |
| `ari/memory_cli.py` | メモリバックエンド管理 CLI |

## 4. Phase D2-C: Pydantic Config フィールド docstring

`ari/config.py` の各フィールドに `Field(..., description=...)` を追加:

```python
class LLMConfig(BaseModel):
    model: str = Field(
        ...,
        description="LiteLLM 形式のモデル識別子(例: openai/gpt-4o, ollama/llama3:70b)。"
                    "未指定時は ARI_LLM_MODEL 環境変数から取得。"
    )
    api_base: str | None = Field(
        None,
        description="LLM API のベース URL。Ollama や独自エンドポイントを使う場合に設定。"
                    "未指定時は ARI_LLM_API_BASE 環境変数または LiteLLM の既定値。"
    )
    ...
```

対象モデル:
- `ARIConfig`
- `LLMConfig`
- `SkillConfig`
- `BFTSConfig`
- `CheckpointConfig`
- `EvaluatorConfig`
- `LoggingConfig`
- `ContainerConfig`(`ari/container.py` 内)

各フィールドの説明は `docs/configuration.md` および `docs/reference/environment_variables.md`(新規、[docs/DOCUMENTATION_PLAN.md §3-3](../docs/DOCUMENTATION_PLAN.md))の記述と一致させる。

## 5. Phase D2-D: `ari/public/` API リファレンス

リファクタ計画 [ari-core/REFACTORING.md §7](REFACTORING.md) で `ari/public/` が新設される。本計画ではそのリファレンスドキュメントを `docs/reference/public_api.md`(新規)として作成。

### 5-1. ファイル構成

```markdown
# ari.public — Stable API for skills

This module is the **only** API surface that ari-skill-* may depend on.
Anything outside ari.public may change without notice.

## ari.public.container

### `class ContainerConfig`
...

### `def run_shell_in_container(...)`
...

## ari.public.cost_tracker

### `def bootstrap_skill(...)`
...
...
```

### 5-2. 各シンボルの記述項目

- シグネチャ
- パラメータ(型・説明・既定値)
- 戻り値
- 例外
- 使用例(MCP スキルからの呼び出し)
- 安定性保証(SemVer の MAJOR で変わるかどうか)
- ソース箇所(`ari/container.py:NN` への file:line リンク)

## 6. Phase D2-E: 不足 README の補完(該当スキルのドキュメンテーション計画から参照)

[ari-skill-coding/DOCUMENTATION_PLAN.md](../ari-skill-coding/DOCUMENTATION_PLAN.md) [ari-skill-plot/DOCUMENTATION_PLAN.md](../ari-skill-plot/DOCUMENTATION_PLAN.md) [ari-skill-transform/DOCUMENTATION_PLAN.md](../ari-skill-transform/DOCUMENTATION_PLAN.md) の責務だが、`ari/public/` の利用例として ari-core 側からも参照する必要があるため本書から相互リンクを張る。

## 7. リファクタリング計画との整合

| ari-core/DOCUMENTATION_PLAN | 連動するリファクタ Phase |
|---|---|
| §2 サブディレクトリ docstring | リファクタ Phase 1〜3 と並行可(分割中も docstring は安定) |
| §3 トップレベル docstring | `cli.py` `pipeline.py` 分割後はパッケージ `__init__.py` に書く |
| §4 Pydantic フィールド docstring | リファクタ Phase 1 (PathManager 集約) と整合 |
| §5 `ari.public` API リファレンス | リファクタ Phase 4 完了後に書く(それ以前は未存在) |

## 8. 挙動保証

- docstring 追加・更新は実装挙動に影響しない
- Pydantic の `Field(..., description=...)` 追加は **既定値・型・バリデーションを変えない**
- `__init__.py` への docstring 追加は import 順序・公開シンボルを変えない
- `ari/public/` の新設はリファクタ計画 Phase 4 の責務(本計画は文書化のみ)

## 9. 受け入れ基準

- [ ] `python -c "import ari.agent; print(ari.agent.__doc__)"` が空でない
- [ ] 同様に `ari.llm` `ari.mcp` `ari.memory` `ari.evaluator` `ari.orchestrator` `ari.clone` `ari.publish` `ari.registry` `ari.viz` `ari.schemas` すべて
- [ ] `python -c "from ari.config import LLMConfig; print(LLMConfig.model_json_schema())"` の各フィールドに `description` が含まれる
- [ ] `docs/reference/public_api.md` が存在し、`ari/public/` の全シンボルをカバー
- [ ] `pytest ari-core/tests/ -q` がグリーン(docstring 追加で何も壊れない)

---

## 実装完了後の削除

**Phase D2 の全 PR がマージされ、§9 の受け入れ基準すべてに合格した時点で本ファイルを削除する。** マスター計画 [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md) と同じタイミング。

恒久化する内容:
- §2 サブディレクトリ責務マップ → 実 docstring が代替
- §4 Pydantic フィールド説明 → 実コード内 `Field` description が代替
- §5 公開 API 仕様 → `docs/reference/public_api.md` が代替
