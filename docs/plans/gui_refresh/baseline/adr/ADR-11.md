# ADR-11: 平文 `GET /api/env-keys` を置換する secret readiness API

> Status: accepted（2026-07-23）  
> Owner: GUI refresh program（task 05/09）  
> Decision-by gate: G3（adr_backlog.md）

## Context

plan 09:34 / plan 05:187 / risk register **RR-P0-2**。`GET /api/env-keys` は名前に `API_KEY`/`SECRET`/`TOKEN` を含む全 env 値を**平文**で source file path とともに返していた（検証済み）。plan 09 §Secret policy は「API は secret value を返さず `configured`、provider、source class、last updated のみ返す」「secret key name は schema allowlist に限定する」「newline/control character を拒否する」を要求する。backlog では readiness API の shape と、旧 endpoint の閉鎖手順（deprecation 期間、legacy adapter の有無）が未決だった。

## Decision

| 項目 | 決定 |
|---|---|
| Readiness API | **`GET /api/v1/secrets/status`** を新設。`{schema_version: 1, secrets: [{name, configured, source_class, last_updated}]}`。value field は DTO（`SecretV1`）に**構造的に存在しない** |
| Name allowlist | 応答は module 定数 `ari.viz.v1.secrets.SECRET_NAMES` の固定順のみ: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`, `LETTA_API_KEY`, `ZENODO_TOKEN`, `ARI_REGISTRY_TOKEN`（すべて既存 code から列挙。追加は additive change） |
| `source_class` 語彙 | `project_env`（active checkpoint `.env`）/ `repo_env`（`ARI/.env`・`ari-core/.env`）/ `user_env`（`~/.env`）/ `process_env`（`os.environ` fallback）/ `null`（未設定）。判定は legacy harvest と共有の `_env_chain()`（first-occurrence-wins）で、両 endpoint が食い違えない構造にする |
| `last_updated` | 勝った `.env` file の mtime（UTC ISO 8601）。`process_env` と未設定は `null` |
| 旧 GET の閉鎖手順 | **deprecation 期間なしで即時 value 閉鎖**（P0 修正、互換 freeze 対象外）。endpoint 自体は shape 互換 adapter として存続: 非空 value は `***configured***`、空は `""`、`source` map は不変、top-level `redacted: true` marker を追加。撤去時期は unversioned API 全体の facade 方針（ADR-02）に従う |
| POST（write path） | `POST /api/env-keys` の write 挙動は不変。name allowlist を追加: `^[A-Z][A-Z0-9_]{0,63}$` に fullmatch しない、または newline/control character を含む名前は **400 で拒否**（file 書込なし）。RR-P0-4 の完全是正（atomicity、permission、oversized value）は G5 スコープに残す |
| Frontend | Wizard StepResources の developer-mode「Auto-read」は value prefill を廃止し、readiness 表示（configured / not-configured + source_class）へ置換。settings POST の api-key 書込 flow は不変 |
| 実装時期 | **Wave 3a で実装済み**。negative test（`ari-core/tests/test_gui_secret_readiness.py`）と migration note **MN-2** を伴う |

## Consequences

- RR-P0-2 の是正手段が確定し、secret value を HTTP で読む経路は閉鎖された（risk register の該当行を closed に更新済み）。value-leak guard は serialized payload に対する negative test で固定する。
- GUI から secret value を読み戻す UX（dev-mode の field prefill）は成立しなくなる。「configured なら空欄のまま launch すれば .env の値が使われる」案内へ移行する（MN-2）。
- readiness の name 追加は allowlist 定数の拡張のみで済む additive change。値を返す field の追加は本 ADR への supersede を要する。
- 挙動変更（従来は平文を返していた）のため MN-2 で告知する。互換 freeze はしない（G0 分類で P0 修正対象）。

## Supersedes / 参照

- Supersedes: なし（初回決定）。
- 参照: plan 05:187、plan 09:34 + §Secret policy、risk_register.md RR-P0-2（closed, Wave 3a）、migration note MN-2、adr_backlog.md ADR-11、実装: `ari-core/ari/viz/v1/secrets.py`・`ari-core/ari/viz/api_settings.py`、tests: `ari-core/tests/test_gui_secret_readiness.py`。
