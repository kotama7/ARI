# ari/viz/ リファクタリング計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../../../REFACTORING.md](../../../REFACTORING.md)

## 0. 挙動保証契約

[マスター計画 §2](../../../REFACTORING.md) の契約を厳守する。本ディレクトリは React SPA フロントエンドの API を提供するため、**REST/WebSocket 互換が最重要**:

- 全 REST エンドポイント(`/api/*`)のパス・メソッド・リクエスト/レスポンス JSON スキーマを変えない
- WebSocket メッセージのキー集合・形式・送出タイミングを変えない
- `ari viz` コマンドの引数・既定ポート・既定アドレスを変えない
- access.log の形式を変えない
- 静的アセット (`/static/*`, `/`, `/logo`) の配信パスとキャッシュヘッダを変えない
- CORS preflight 応答ヘッダを変えない

## 1. 現状

| ファイル | 行数 | 責務 |
|---|---|---|
| `server.py` | 1,489 | HTTP/WebSocket サーバ、ルーティング、ハンドラ統合(分割対象) |
| `api_state.py` | 1,434 | 状態 API、checkpoint 探索、tree.json broadcast(分割対象) |
| `api_experiment.py` | 770 | 実験ログ・メトリクス・ノードデータ API |
| `api_settings.py` | 547 | workflow/skill 設定変更 API |
| `api_workflow.py` | 462 | workflow.yaml シリアライズ API |
| `api_orchestrator.py` | 321 | BFTS ツリー表示・lineage decision API |
| `api_tools.py` | 266 | MCP ツール一覧 API |
| `api_memory.py` | 226 | メモリヘルス API |
| `api_fewshot.py` | 221 | few-shot 例管理 API |
| `api_publish.py` | 163 | 公開バックエンド・成果物アップロード API |
| `api_ollama.py` | 90 | Ollama リソース情報 API |
| `state.py` | 79 | グローバル状態管理 |
| `api_wizard.py` | 35 | オンボーディングウィザード API |

**合計: 6,104 行**

## 2. 計画

### Step 1: `viz/server.py` の分割 (Phase 3, PR-3B 前半)

#### 分割マッピング

| 新ファイル | 由来行 | 含めるシンボル |
|---|---|---|
| `viz/websocket.py` | L48–64 | `_ws_handler` |
| `viz/ui_helpers.py` | L78–229 | `_extract_goal_from_md` / `_build_experiment_detail_config` / `_collect_resource_metrics` |
| `viz/routes.py` | L325–1390 | `_Handler.do_GET` / `_Handler.do_POST` のルーティング部 — dict ベースルータに整形 |
| `viz/server.py`(残置) | L230–249, L1393–1489 | `_DualStackServer` / `_Handler` 骨格(routes.py を呼ぶ) / `_init_logging` / `main` |

#### `routes.py` の構造提案

```python
# routes.py
GET_ROUTES: dict[str | re.Pattern, Callable] = {
    "/api/state": api_state._api_state,
    "/api/checkpoints": api_state._api_checkpoints,
    re.compile(r"^/api/checkpoints/(?P<ckpt>[^/]+)/summary$"): api_state._api_checkpoint_summary,
    # ...
}

POST_ROUTES: dict[...] = { ... }

def dispatch_get(handler, path: str) -> bool: ...
def dispatch_post(handler, path: str) -> bool: ...
```

旧 `do_GET` `do_POST` の if-elif チェーンと**同じ判定順序**で書く。dict 順序が Python 3.7+ で挿入順になることを利用。

### Step 2: `viz/api_state.py` の分割 (Phase 3, PR-3B 後半)

#### 分割マッピング

| 新ファイル | 由来行 | 含めるシンボル |
|---|---|---|
| `viz/checkpoint_finder.py` | L18–35, L223–231 | `_checkpoint_search_bases` / `_check_pid_alive` / `_resolve_checkpoint_dir` |
| `viz/state_sync.py` | L38–98, L1188–1249 | `_load_nodes_tree` / `_broadcast` / `_do_broadcast` / `_watcher_thread` |
| `viz/checkpoint_api.py` | L106–222, L629–742, L823–850 | `_api_models` / `_api_checkpoints` / `_api_checkpoint_summary` / `_api_lineage_decisions` |
| `viz/ear.py` | L232–628 | `_api_ear` / `_api_node_report` / `_api_ear_clone_verify` / `_api_ear_curate` / `_api_ear_publish_yaml_get/set` / `_synth_repro_report_from_ors` |
| `viz/file_api.py` | L743–1019 | `_ensure_paper_dir` / `_api_checkpoint_files` / `_api_checkpoint_file_read/save/upload/delete` / `_resolve_paper_file` / `_api_checkpoint_compile` |
| `viz/checkpoint_lifecycle.py` | L1020–1187 | `_api_delete_checkpoint` / `_api_switch_checkpoint` |
| `viz/node_work_api.py` | L1250–1434 | `_resolve_node_work_dir` / `_api_checkpoint_filetree` / `_api_checkpoint_filecontent` / `_api_checkpoint_memory` |

#### 後方互換
旧 `viz/api_state.py` を維持するため、`api_state.py` を **再エクスポートのみのファサード** に縮小:
```python
# api_state.py（縮小後）
from .checkpoint_finder import _resolve_checkpoint_dir, ...
from .state_sync import _load_nodes_tree, _broadcast, ...
from .checkpoint_api import _api_models, _api_checkpoints, ...
# ...以下すべて再エクスポート
```

`server.py`(または新 `routes.py`)が `from . import api_state` と書いている既存コードを破壊しない。

### Step 3: 共有モジュール `ari/checkpoint.py` への接続 (Phase 2 で先行実施)

[ari-core/REFACTORING.md §6-1](../../REFACTORING.md) で新設される `ari/checkpoint.py` を、`viz/state_sync.py:_load_nodes_tree` から呼ぶ形に変更。これにより、CLI 側の書き込みと viz 側の読み込みが同じスキーマ実装を共有する。

## 3. 重要な注意

### 3-1. `do_GET` `do_POST` の判定順序を絶対に変えない
- 既存の if-elif チェーンには **`startswith()` 判定** と **完全一致判定** が混在しており、順序を変えると挙動が変わる。
- 例: `/api/checkpoints/abc/files/foo.json` は `_api_checkpoint_file_read` にマッチすべきで、`_api_checkpoint_files` にマッチしてはならない。
- dict ルータ化する際は、**より具体的なパターン(正規表現)を先に**置く。

### 3-2. WebSocket ブロードキャストのタイミング
- `_watcher_thread` のポーリング間隔(現在ハードコード値)を変えない
- `_broadcast` の async 呼び出し方式(`asyncio.run_coroutine_threadsafe`)を変えない

### 3-3. グローバル状態 (`state.py`)
- `_st` モジュール変数経由で `_checkpoint_dir` 等を共有する設計を**維持**(本リファクタでは触らない)
- 将来は依存性注入に置き換えるべきだが、本 PR の範囲外

### 3-4. ファイルアップロード (`_api_checkpoint_file_upload`)
- multipart parsing のロジックを移動するときに、boundary 文字列の処理・改行(`\r\n`)処理を絶対に変えない

### 3-5. `viz/api_publish.py:24` の `~/.ari/publish.yaml` フォールバック(Tier B、Phase DR2/DR3)

[DEPRECATION_REMOVAL.md §1-1 #11](../../../DEPRECATION_REMOVAL.md) の対処。

**現状(問題):**
```python
_SETTINGS_PATH = Path(
    os.environ.get("ARI_PUBLISH_SETTINGS")
    or Path.home() / ".ari" / "publish.yaml"
)
```
モジュールロード時にホームディレクトリ解決が実行され、`~/.ari/` を作りに行く。

**修正(DR2 段階):**
```python
def _resolve_settings_path() -> Path:
    if env := os.environ.get("ARI_PUBLISH_SETTINGS"):
        return Path(env)
    legacy = Path.home() / ".ari" / "publish.yaml"
    if legacy.exists():
        from ari._deprecation import warn_deprecated_path
        warn_deprecated_path(
            legacy,
            replacement="ARI_PUBLISH_SETTINGS env or {checkpoint}/settings.json publish section",
        )
    return legacy

# モジュールロード時に決定するのをやめ、関数内で都度解決する(またはキャッシュ)
```

**注意:**
- モジュールロード時に Path.home() を呼ばない設計に変える(`_SETTINGS_PATH` 定数を関数化)
- 現在この設定がモジュール変数の前提のコードがあれば書き換える
- v1.0(DR5)で legacy パスは完全削除し、`ARI_PUBLISH_SETTINGS` または checkpoint scoped 設定のみに

**挙動保証:**
- `~/.ari/publish.yaml` を持つ既存ユーザは警告付きで動作
- モジュールインポート時の副作用がなくなる(テスト容易性向上)

## 4. 挙動保証チェックリスト

PR-3B の merge 前に必ず実施:

- [ ] サーバ起動: `ari viz <既存 v0.7 checkpoint> --port 18765` がエラーなく起動
- [ ] **REST 互換テスト**: 以下の代表エンドポイントを `curl` で叩き、JSON キー集合が分割前後で完全一致
  - `GET /api/state`
  - `GET /api/models`
  - `GET /api/checkpoints`
  - `GET /api/checkpoints/<id>/summary`
  - `GET /api/checkpoints/<id>/files`
  - `GET /api/checkpoints/<id>/ear`
  - `GET /api/checkpoints/<id>/lineage_decisions`
  - `GET /api/tools`
  - `GET /api/memory/health`
  - `GET /api/settings`
  - `GET /api/workflow`
- [ ] **WebSocket 互換テスト**: `wscat` または小さい test client で接続し、初回送信メッセージのキー集合が一致
- [ ] **POST テスト**: `POST /api/settings` `POST /api/launch` の最小ペイロードが分割前後で同じ応答
- [ ] **ファイルアップロード**: `POST /api/checkpoints/<id>/files/upload` で 1 KB のテキストファイルがアップロードでき、内容が一致
- [ ] React SPA(既存ビルド成果物)が再ビルドなしで動作 — トップページ表示・チェックポイント切替・tree 表示・logs 表示
- [ ] `pytest ari-core/tests/test_viz*.py -q` があれば全グリーン
- [ ] `do_GET` `do_POST` の判定順序が分割前後で一致(routes.py の dict 順序を分割前の if-elif と照合した PR コメントを残す)

## 5. 段階分け(PR-3B を更に分けることを許容)

`server.py` 分割と `api_state.py` 分割は同 PR でも別 PR でも良い。**判断基準**:
- 別 PR にするほうが安全(レビューがしやすい、回帰範囲を絞れる)
- 同 PR にするのは、共通の `checkpoint_finder.py` を両方が import する場合のみ

推奨は **2 PR に分割**:
- PR-3B-1: `viz/server.py` 分割(routes.py まで)
- PR-3B-2: `viz/api_state.py` 分割

---

## 実装完了後の削除

**PR-3B-1 / PR-3B-2 がマージされ、§4 のチェックリストすべてに合格した時点で本ファイルを削除する。**

恒久化する内容(削除前に転記):
- §1 ファイル責務表 → `docs/architecture.md` の Viz 章
- §3-1 ルーティング判定順序の制約 → `viz/routes.py` の docstring
