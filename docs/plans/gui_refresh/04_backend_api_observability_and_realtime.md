# 04 — Backend API, Observability, and Realtime

> Status: planned  
> Dependencies: 00  
> Gate: G2 — Platform seam

## Purpose

filesystem/checkpoint を source of truth として維持しながら、run-scoped の versioned API、再構築可能な read model、同一 origin realtime stream を提供する。GUI が巨大 `/state`、global active checkpoint、tree 専用 WebSocket に依存する状態を解消する。

## Scope

- backend transport/application/domain/infrastructure seam。
- `/api/v1`、OpenAPI、typed error、request correlation。
- project/run/checkpoint を明示する resource API。
- artifact projector、cursor pagination、cache/index recovery。
- same-origin SSE と legacy WebSocket/polling の移行。
- process supervisor と launch lifecycle event。

## Non-goals

- filesystem artifact を primary database へ移行しない。
- bidirectional collaboration protocol は導入しない。
- RQGM の domain-specific DTO 詳細は task 08 で定義する。
- public API の legacy endpoint をこの task だけで削除しない。

## Existing problems

- module-global active checkpoint/settings/process/staging（`viz/state.py`）が request boundary を兼ねている。
- `/state` が recursive file discovery と JSON/YAML read を polling ごとに行い（`services/state_service.build_app_state`）、しかも GET なのに process state を mutate する（proc 終了検出時の `_last_experiment_md` reset）。
- WebSocket は HTTP port + 1、単一 channel・単一 message type（`{"type":"update"}`）の tree update 専用 read-only push で、1 秒間隔の mtime watcher が駆動する。proxy/HPC portal と相性が悪い。
- 一方で SSE は既に 2 系統ある: `GET /api/logs`（active run の log stream）と `GET /api/paperbench/run/{job_id}/logs`（`Last-Event-ID` resume、5 分 window）。新 realtime はこの pattern の一般化とする。
- route dispatch は `routes.py` の手書き if/elif 連鎖で、HTTP 200 内の `_status`（launch/run-stage/sub-experiments で `r.pop("_status", 200)`）など契約が混在する。
- frontend と backend の route/DTO drift を build 時に止められない（既知の drift F6a: FE が `POST /api/paperbench/run/{id}/report` を送るが backend に POST branch がない。`check_viz_api_schema` allowlist に記録済み）。
- launch accepted 前に slug generation、scheduler probe、filesystem mutation が同期実行される。
- parallel launch を一意に識別せず、server 起動時は「mtime が最新の checkpoint」を自動復元し、log 対応付けも mtime 近接で行う。
- PaperBench job state は in-memory `_JOBS` dict（uuid4）のみで、server 再起動で消失する。

## Target backend structure

```text
ari/viz/
├── transport/http/
│   ├── routers/
│   ├── dto/
│   ├── errors.py
│   └── sse.py
├── application/
│   ├── run_commands.py
│   ├── run_queries.py
│   ├── config_service.py
│   └── artifact_queries.py
├── domain/
│   ├── project.py
│   ├── run.py
│   ├── workflow.py
│   └── events.py
├── infrastructure/
│   ├── filesystem_repositories.py
│   ├── read_models/
│   ├── watcher.py
│   └── process_supervisor.py
└── legacy/
    └── unversioned_route_adapters.py
```

最初に既存 `api_*.py` から pure application service/repository interface を抽出し、その後 transport を置換する。抽出は既に部分着手されている（`viz/services/` に `/state` builder、`FileService` の path guard/size limit、`.env` parse が抽出済みで、contract snapshot tests が固定している。`services/__init__.py` に deferred 項目が明記されている）。greenfield で作り直さず、この seam を延長する。`api_state.py` は既に re-export facade である点も利用する。既存 server 配備（stdlib `ThreadingHTTPServer`。`viz/__init__.py` docstring の FastAPI 記述は誤り）と static bundle 配信は当面維持する。

## API principles

- canonical endpoint は `/api/v1` 配下に置く。
- run-scoped resource は path に `run_id` を含め、global selection を authorization/data boundary に使わない。
- DTO は `schema_version` を持ち、additive change を基本とする。
- error envelope は `code`、`message`、`details`、`request_id`、`retryable` を持つ。
- GET は side effect を持たず、mutation は正規 HTTP status を返す。
- PATCH/PUT は revision または ETag で lost update を検出する。
- retriable mutation は idempotency key を受け付ける。
- timestamps は UTC ISO 8601、duration は明示 unit、ID は安定 opaque ID とする。

## Proposed resource surface

```text
GET    /api/v1/projects
GET    /api/v1/projects/{project_id}/runs
POST   /api/v1/projects/{project_id}/run-drafts
POST   /api/v1/run-drafts/{draft_id}/validate
POST   /api/v1/runs                         # idempotent launch
GET    /api/v1/runs/{run_id}
GET    /api/v1/runs/{run_id}/summary
GET    /api/v1/runs/{run_id}/tree
GET    /api/v1/runs/{run_id}/artifacts
GET    /api/v1/runs/{run_id}/artifacts/{artifact_id}
GET    /api/v1/runs/{run_id}/events
GET    /api/v1/events/stream?run_id=...&topics=...
GET    /api/v1/config/schema
POST   /api/v1/run-drafts/{draft_id}/resolve-config
GET    /api/v1/runs/{run_id}/resolved-config
```

RQGM endpoint は `/api/v1/runs/{run_id}/rqgm/...` に置く。legacy endpoint は同じ application service を呼ぶ facade とし、旧 payload/status behavior を adapter の contract test で固定する。

`/api/v1/projects` は現行実装に対応物がない（checkpoint ≡ run で project 概念が存在しない）。初期実装は checkpoint search bases の scan を単一の暗黙 default project に mapping し、project 実体化の是非と保存場所は ADR で決める。sub-experiment lineage（`GET /api/sub-experiments`）は run 間 relation として `/api/v1` に取り込む。

## Run identity and lifecycle

- launch request 受理時に collision-resistant `run_id` を先に発行する。
- slug/timestamp path は表示名であり identity としない。
- validation/preparation と subprocess spawn を別 command に分離する。
- accepted response は 1 秒以内を目標に `run_id`、status URL、checkpoint path/intent を返す。
- 同一 idempotency key の二重 click/retry は subprocess を一つだけ作る。
- lifecycle は `draft → validating → queued → starting → running → terminal` を event 化する。
- failure 時は partial filesystem mutation と cleanup/recovery action を記録する。

## Read-model architecture

- artifact repository は canonical path と PathManager boundary を検証する。
- projector は artifact type ごとに parser、schema version、source revision を持つ。
- read model は削除して再構築可能であり、canonical artifact を上書きしない。
- JSONL は byte offset/event ID cursor と bounded page size を使う。
- partial trailing line は committed event として公開せず、次回再試行する。
- corrupt record は run 全体を落とさず、diagnostic event と対象 offset を返す。
- index は file identity、size、mtime、content digest の必要部分で invalidation する。
- unknown/additive artifact field は保持し、古い reader が捨てない。

## Realtime event contract

```json
{
  "event_id": "opaque-monotonic-id",
  "run_id": "run-id",
  "topic": "rqgm.transition",
  "revision": 42,
  "occurred_at": "2026-07-22T00:00:00Z",
  "kind": "resource.changed",
  "resource": "/api/v1/runs/run-id/rqgm/transitions",
  "payload": {"transition_id": "..."}
}
```

- event は notification/invalidation であり、完全な source of truth ではない。
- client は reconnect 時に `Last-Event-ID` と snapshot refetch を使う。
- topic は `run`、`tree`、`logs`、`artifacts`、`config`、`rqgm` を起点とする。
- lifecycle/stage は `started`、`completed`、`degraded`、`failed` を明示し、artifact 更新時刻から推測しない。
- RQGM transition は commit 済み event のみ publish する。
- legacy tree WebSocket は SSE parity が確認されるまで二重運転する。

## Caching and polling policy

- resource metrics は低頻度 query、logs/tree/RQGM transition は SSE + cursor query とする。
- hidden tab は background polling を停止または大幅に低減する。
- request deduplication と ETag/If-None-Match を適用する。
- `/state` は legacy facade として凍結し、新 feature を追加して肥大化させない。
- workflow/skill discovery は mtime-aware index または起動時 cache を用いる。
- cache hit/miss、projector lag、SSE reconnect、payload size を diagnostics へ公開する。

## Compatibility and migration

1. current route/body/response/status fixture を保存する。既存資産（`scripts/snapshot_contracts.py`、`tests/test_contract_snapshots.py`、`ari/schemas/viz_*.schema.json`、`check_viz_api_schema` の allowlist baseline）を起点に不足分だけ追加する。
2. repository/service seam を抽出し、legacy handler を接続する。
3. `/api/v1` read-only resource と OpenAPI を追加する。
4. frontend generated client を一つの vertical slice で導入する。
5. SSE を追加し、poll/WebSocket と shadow comparison する。
6. run-explicit mutation と process supervisor を導入する。
7. usage telemetry と rollback window 後に legacy watcher/global selection dependency を削除する。

## Testing

- OpenAPI schema snapshot と generated client compile test。
- legacy/current fixture と canonical DTO の adapter golden test。
- two run/two tab/concurrent request isolation test。
- malformed JSON、unknown field、wrong type/range、zero/null、HTTP status test。
- partial/corrupt/truncated JSONL、rotation、rebuild、cursor no-gap/no-duplicate test。
- SSE reconnect、duplicate event、out-of-order invalidation、fallback polling test。
- idempotent double launch、spawn failure、cleanup、collision test。
- live ephemeral server integration。LLM、scheduler、subprocess、network は deterministic fake を使う。

## Completion criteria

- 新画面の全 endpoint が `/api/v1` と explicit run ID を使う。
- typed error/status と OpenAPI client が frontend CI で検証される。
- 10k event/large tree fixture で全ファイル再読込せず cursor query できる。
- SSE 切断時も stale state を停止/失敗と誤表示しない。
- legacy API/WebSocket の parity と rollback が実証される。

## Deletion criteria

- API/realtime/read-model contract を reference docs へ移し、legacy facade の削除条件を満たしている。

## Delete-after checklist

- [ ] OpenAPI と event schema を恒久 reference へ移した。
- [ ] legacy API/WS usage が removal threshold を満たした。
- [ ] global active checkpoint を data boundary から除去した。
- [ ] main merge と CI green を確認した。
- [ ] `INDEX.md` を更新した。
