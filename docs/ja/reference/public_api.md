---
sources:
  - path: ari-core/ari/public
    role: implementation
  - path: ari-core/tests/test_public_api_boundary.py
    role: test
  - path: ari-core/ari/result.py
    role: implementation
  - path: ari-core/ari/call_context.py
    role: implementation
  - path: ari-core/ari/skill_lock.py
    role: implementation
  - path: ari-core/ari/skill_manifest.py
    role: implementation
last_verified: 2026-08-02
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
| `ari.public.clone` | digest 検証付き EAR bundle の取得と安全な展開（`clone`、`CloneResult`、`CloneError`） | reproduction / bundle consumer Skill |
| `ari.public.config_schema` | Pydantic 設定モデル（`ARIConfig`、`LLMConfig` など） | 型付き設定が必要な呼び出し元 |
| `ari.public.container` | コンテナランタイムヘルパー（`ContainerConfig`、`run_in_container` など） | `ari-skill-coding`（テスト） |
| `ari.public.execution` | 閉じた workspace、bounded execution/result、完全 log artifact、`MeasurementSetV1` | 実行 producer と測定 consumer Skill |
| `ari.public.cost_tracker` | LLM コスト記録（`bootstrap_skill`、`record` など） | `ari-skill-plot`（LLM 呼び出しコスト） |
| `ari.public.llm` | `LLMClient`（コスト統合付き LiteLLM ラッパー） | ARI のラッパーを使いたい呼び出し元 |
| `ari.public.paths` | `PathManager`（チェックポイントパスリゾルバ） | スコープ付きパスが必要な呼び出し元 |
| `ari.public.node_selection` | 決定論的な downstream node/source 選択 | `ari-skill-transform` |
| `ari.public.publish` | staged EAR publish/promote 契約 | `ari-skill-transform` |
| `ari.public.run_env` | run 環境の capture と shell export ヘルパー | sandbox / executor Skill |
| `ari.public.call_context` | `RunContextV1`、`NodeContextV1`、署名付き tool-context 検証ヘルパー | control plane と context-aware Skill |
| `ari.public.result` | `ResultEnvelopeV1`、content-addressed artifact reference、型付き error、呼び出し provenance | Skill adapter と federated dispatch 呼び出し元 |
| `ari.public.skill_lock` | `SkillsLockV1`、ロック済み provider/tool record、atomic create-or-verify | run launcher、federation adapter、replay tool |
| `ari.public.skill_manifest` | versioned Skill manifest model、loader、digest、safe entrypoint resolver | 組み込み / federated MCP Skill |
| `ari.public.claim_gate` | 決定論的な主張-証拠ハードゲート（`run_hard_gate`）＋ 概念→不変条件レジストリ（`classify_concept`、`scan_science_data`、`CONCEPT_INVARIANTS`） | `ari-skill-evaluator`、`ari-skill-transform` |
| `ari.public.verified_context` | 検証済みコンテキストヘルパー（`render_grounded_block`、`write_verified_context`、`build_verified_context`） | `ari-skill-paper` |

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

## `ari.public.skill_manifest`

`skill.yaml` は canonical package contract です。consumer は YAML を直接 parse
したり `server.py` を scrape したりせず、public API から読み込みます:

```python
from ari.public.skill_manifest import load_skill_manifest, manifest_digest

manifest = load_skill_manifest("ari-skill-coding/skill.yaml")
tool = manifest.tool("run_code")
identity = manifest_digest(manifest)
```

`SkillManifestV1` は package identity、package-relative Python stdio entrypoint、
網羅的な通常環境宣言、重複しない credential scope、一意な tool 名、
capability reference、phase、side effect、determinism、timeout class、permission、
result schema を検証します。
`TimeoutBudgetV1` は caller が制御する timeout 引数を明示し、上限を固定します。
`timeout_class=async` の tool は `AsyncLifecycleV1` で status/result/cancel の
semantic capability を宣言しなければならず、未解決または曖昧な参照は manifest
validation で拒否されます。

組み込み production Skill では
`environment_policy=complete` が必須です。解決済みの各 tool は
`context_requirement` を `none` / `run` / `node` で宣言し、構造化コンテキストが
なければ dispatch は fail closed します。公開 runtime loader は未versionedの
legacy manifestを常に拒否します。オフライン移行では内部のread-only
`ari.migrations.skill_manifest.load_legacy_skill_manifest()`を利用できますが、
変換結果はdefault-offであり、暗黙にadmissionされません。

## `ari.public.call_context` と `ari.public.result`

新しい dispatch コードは型付き result contract を使います。従来の辞書 API は
情報を失わない compatibility projection として残ります:

```python
from ari.public.call_context import ToolCallContextV1

tool = client.list_tools()[0]
envelope = client.call_tool_envelope(
    tool["tool_ref"],
    {"query": "example"},
    context=ToolCallContextV1.for_node(
        run_id="run-1",
        node_id="node-1",
        parent_node_id="root",
        ancestor_node_ids=["root"],
        phase="bfts",
    ),
)
```

`RunContextV1` は logical run を `run_scope_digest` に、`NodeContextV1` は
self、parent、root から parent までの順序付き chain を `lineage_digest` に
束縛します。`MCPClient` はこれを tool-bound、per-connection HMAC capability に
変換し、Skill は `verify_tool_context` で検証します。署名鍵は transport が
所有し、public data contract には入りません。規範 schema は
`ari-core/ari/schemas/call_context_v1.schema.json` です。

`ResultEnvelopeV1` は status、structured content、型付き error、不変の
`tool_ref`、run/node/phase context、selection reason、timing、SHA-256 response digest を
記録します。credential は値ではなく scope ID だけを記録します。
4,000 文字を超える raw content は content address の artifact に退避され、
`materialize_content(store)` が digest と byte size を検証して復元します。

非同期 submit は、review 済み manifest capability から解決した immutable
`tool_ref` endpoint を持つ `AsyncToolHandleV1` を追加します。bare name を再検索せず
`MCPClient.get_async_status()`、`get_async_result()`、`cancel_async()`、
`wait_for_async()` に serialize 済み handle を渡せます。規範 schema は
`ari-core/ari/schemas/async_tool_handle_v1.schema.json` です。

## `ari.public.skill_lock`

`SKILLS.lock` は live MCP handshake 後に作成される決定論的な checkpoint-level
snapshot です。`SkillsLockV1` は canonical manifest を正確な live input/output
schema と phase ごとの admitted `tool_ref` 集合に束縛します。
`write_or_verify_skills_lock()` は最初の snapshot を atomic に作成し、以後は
byte-equivalent な semantics を要求します。drift と corruption は
`SkillLockMismatchError` / `SkillLockCorruptError` として区別されます。
`LockedCredentialScopeV1` には scope identity と宣言/存在する環境名だけが
記録され、credential 値は含まれません。

## `ari.public.claim_gate`

`ari.pipeline.claim_gate` から決定論的な主張-証拠ハードゲートと、その
概念→不変条件レジストリを再エクスポートします:

| シンボル | 用途 |
|---|---|
| `run_hard_gate` | ゲートのエントリポイント — 証拠が決定論的チェックに合格しない主張をブロックする |
| `classify_concept` | 概念をその普遍的不変条件のファミリにマッピングする |
| `scan_science_data` | 登録された不変条件に照らしてサイエンスデータをスキャンする |
| `CONCEPT_INVARIANTS` | ドメイン一般の概念→不変条件レジストリ（単一の信頼できる情報源） |

```python
from ari.public.claim_gate import run_hard_gate
```

`ari-skill-evaluator` と `ari-skill-transform` は、プライベートな
`ari.pipeline.claim_gate` パスではなく、この安定したパブリックサーフェス
経由でゲートに到達します。これにより両スキルは、ゲートがブロックに使うのと
**同じ**普遍的不変条件ロジックを再利用できます — ドメイン計算の重複は
ありません。ソース: `ari-core/ari/pipeline/claim_gate/` →
`ari-core/ari/public/claim_gate.py`。

## `ari.public.verified_context`

`ari.pipeline.verified_context` から検証済みコンテキストヘルパーを
再エクスポートします:

| シンボル | 用途 |
|---|---|
| `render_grounded_block` | グラウンディングされた（引用に裏付けられた）コンテキストブロックをレンダリングする |
| `write_verified_context` | アーティファクトを構築する呼び出し元向けに検証済みコンテキストのアーティファクトを書き出す |
| `build_verified_context` | 検証済みコンテキストの構造を構築する |

```python
from ari.public.verified_context import render_grounded_block
```

`ari-skill-paper` は、プライベートな `ari.pipeline.verified_context` パス
ではなく、この安定したパブリックサーフェス経由でこれらのヘルパーに
到達します。ソース: `ari-core/ari/pipeline/verified_context.py` →
`ari-core/ari/public/verified_context.py`。

## まとめ — 最小限のスキル

`ari.public.*` だけを使うスキルの例: コスト追跡をブートストラップし、
チェックポイントスコープのパスを解決し、コスト追跡付きの LLM 呼び出しを行います。

```python
from ari.public import cost_tracker
from ari.public.paths import PathManager
from ari.public.llm import LLMClient

# 1. このスキルが行う全 LLM 呼び出しにタグ付け（ARI_CHECKPOINT_DIR を読む）。
cost_tracker.bootstrap_skill("ari-skill-example", phase="bfts")

# 2. パスは PathManager 経由で解決 — ARI_CHECKPOINT_DIR を直接読まない。
paths = PathManager.from_env()
nodes_json = paths.checkpoint / "nodes_tree.json"

# 3. LLM 呼び出しは ARI のラッパー経由なので、コストは自動的に記録される。
client = LLMClient(model="ollama/qwen3:32b")
resp = await client.complete([{"role": "user", "content": "Summarise: ..."}])
```

呼び出しのトークン数と USD コストは、スキル名とフェーズのタグ付きで
チェックポイントの `cost_trace.jsonl` に記録されます — 手動の `record()` は不要です。

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
- `docs/guides/extension_guide.md` — `ari.public` のみに依存する新しいスキルの
  書き方。
- `CONTRIBUTING.md::Software-engineering discipline §3` — パブリック API
  ルール（スキルは `ari.public.*` のみを参照可能）。
- `docs/_archive/refactor_audit.md`（§4）— 過去の Phase 4 インベントリ。
