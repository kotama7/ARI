---
sources:
  - path: ari-core/ari/public
    role: implementation
  - path: ari-core/tests/test_public_api_boundary.py
    role: test
last_verified: 2026-05-25
---

# `ari.public` — スキル向け安定 API

`ari.public` は `ari-skill-*` パッケージが依存できる**唯一**のモジュール
サーフェスです。それ以外はすべて内部実装であり、予告なく変更される可能性があります。
このパッケージはコアが自由にリファクタリングできるよう、対応する
`ari.<module>` プライベート実装への薄い再エクスポート層として機能し、
スキル向けのコントラクトを維持します。v0.7.1（v0.7+ リファクタの Phase 4）で
導入され、`ari-core/tests/test_public_api_boundary.py` によって強制されています。

## サブモジュール

| サブモジュール | 再エクスポートする内容 | 使用しているスキル |
|---|---|---|
| `ari.public.config_schema` | Pydantic 設定モデル（`ARIConfig`、`LLMConfig` など） | 型付き設定が必要な呼び出し元 |
| `ari.public.container` | コンテナランタイムヘルパー（`ContainerConfig`、`run_in_container` など） | `ari-skill-coding`（テスト） |
| `ari.public.cost_tracker` | LLM コスト記録（`bootstrap_skill`、`record` など） | `ari-skill-plot`（LLM 呼び出しコスト） |
| `ari.public.llm` | `LLMClient`（コスト統合付き LiteLLM ラッパー） | ARI のラッパーを使いたい呼び出し元 |
| `ari.public.paths` | `PathManager`（チェックポイントパスリゾルバ） | スコープ付きパスが必要な呼び出し元 |

## `ari.public.config_schema`

`ari.config` から Pydantic モデルを再エクスポートします:

```python
from ari.public.config_schema import (
    ARIConfig,
    BFTSConfig,
    CheckpointConfig,
    EvaluatorConfig,
    LLMConfig,
    LoggingConfig,
    SkillConfig,
)

cfg = ARIConfig.model_validate(yaml.safe_load(open("ari.yaml")))
```

エクスポートされる名前は `ari/config.py` のシンボルと 1 対 1 対応しています。
現在のフィールド形式はそのファイルを参照してください。ソース:
`ari-core/ari/public/config_schema.py`。

## `ari.public.container`

`ari.container` からコンテナランタイムを再エクスポートします:

| シンボル | 用途 |
|---|---|
| `ContainerConfig` | データクラス: `mode`、`image`、`bind_paths`、`gpu` など |
| `detect_runtime()` | `which` の検索結果に基づいて `"singularity"` / `"apptainer"` / `"docker"` / `"none"` を返す |
| `config_from_env()` | `ARI_CONTAINER_*` 環境変数から `ContainerConfig` を構築（未設定の場合は `None`） |
| `pull_image(cfg)` | `cfg` が参照するイメージを取得 / ビルド |
| `run_in_container(cfg, cmd, ...)` | コンテナ内でプロセスを実行し、終了コード + キャプチャストリームを返す |
| `run_shell_in_container(cfg, script, ...)` | 同上。ただし bash スクリプト文字列を受け付ける |
| `list_images()` | アクティブなランタイムで利用可能なイメージの一覧 |
| `get_container_info()` | ランタイム + イメージのヘルスを含む診断辞書 |

ソース: `ari-core/ari/container.py` → `ari-core/ari/public/container.py`。

## `ari.public.cost_tracker`

`ari.cost_tracker` から LLM コストトラッカーを再エクスポートします:

| シンボル | 用途 |
|---|---|
| `CostTracker` | `cost_log.jsonl` に書き込むアグリゲータインスタンス |
| `CallRecord` | 呼び出しごとのデータクラス（`model`、`prompt_tokens`、`completion_tokens`、`cost_usd`、`metadata`） |
| `init(log_dir)` | `log_dir` をルートにグローバルトラッカーを初期化 |
| `init_from_env()` | `ARI_CHECKPOINT_DIR` を使って自動的に初期化（ほとんどの呼び出し元はこちらを使用） |
| `bootstrap_skill(skill_name, phase=None)` | スキル向けの便利なラッパー — 初期化して各レコードにタグ付け |
| `record(**kwargs)` | 手動で `CallRecord` を追加（LiteLLM コールバック経由でない場合に使用） |
| `set_default_metadata(**kwargs)` | 後続のすべてのレコードに追加メタデータをタグ付け |
| `get()` | 現在のトラッカーを取得（なければ `None`） |

スキルは通常、起動時に `bootstrap_skill` のみ必要です。残りは LiteLLM
コールバックが処理します。ソース:
`ari-core/ari/cost_tracker.py` → `ari-core/ari/public/cost_tracker.py`。

## `ari.public.llm`

`ari.llm.client` から `LLMClient` を再エクスポートします:

```python
from ari.public.llm import LLMClient

client = LLMClient(model="ollama/qwen3:32b")
resp = await client.complete([{"role": "user", "content": "..."}])
```

LiteLLM を直接呼び出すのではなく、こちらを使用してください — `LLMClient` は
ARI のコストトラッカーとメタデータタグ付けを透過的に処理します。ソース:
`ari-core/ari/llm/client.py` → `ari-core/ari/public/llm.py`。

## `ari.public.paths`

`ari.paths` から `PathManager` を再エクスポートします:

```python
from ari.public.paths import PathManager

paths = PathManager.from_env()        # honours ARI_CHECKPOINT_DIR
nodes_json = paths.checkpoint / "nodes_tree.json"
```

`PathManager` は中央リゾルバです — スキルから `ARI_CHECKPOINT_DIR` を
直接読み取らないでください。ソース: `ari-core/ari/paths.py` →
`ari-core/ari/public/paths.py`。

## 安定性の保証

- **MAJOR（SemVer）** — シンボル、シグネチャ、動作が変更される可能性があります。
- **MINOR** — 新しいシンボルの追加；既存のものは後方互換な方法で拡張
  （新しいオプション kwargs は許可）。
- **PATCH** — バグ修正のみ。

`from ari.public import <X>` ではなく `from ari import <X>` で直接インポートすると
このコントラクトが迂回されます — スキル作者は `ari/public/__init__.py` と
照合してインポートを確認し、内部インポートの境界をパブリックレイヤー経由に
移行してください。

## 関連ドキュメント

- `ari-core/ari/public/__init__.py` — 標準的なサブモジュール一覧を含む
  モジュールレベルの docstring。
- `docs/extension_guide.md` — `ari.public` のみに依存する新しいスキルの
  書き方。
- `CONTRIBUTING.md::Software-engineering discipline §3` — パブリック API
  ルール（スキルは `ari.public.*` のみを参照可能）。
- `docs/refactor_audit.md`（§4）— 過去の Phase 4 インベントリ。
