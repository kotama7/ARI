# ADR-02: `/api/v1` transport と OpenAPI client generation

> Status: accepted（2026-07-23）  
> Owner: GUI refresh program（task 04）  
> Decision-by gate: G2（adr_backlog.md）

## Context

plan 00:171 / plan 04。`/api/v1` の transport 選定では FastAPI/uvicorn 採用も検討対象だったが、plan 04:67 は「既存 server 配備（stdlib `ThreadingHTTPServer`）と static bundle 配信は当面維持する」と定めており、CI-pin 履歴（unbounded pin による CI 側最新版導入でローカル緑 ≠ CI 緑となる既知の罠）から新規 web framework dependency は増やしたくない。pydantic v2 は既に core dependency である。unversioned endpoint は compatibility facade として並行運転する。

## Decision

| 要素 | 決定 |
|---|---|
| Transport | **既存 stdlib `ThreadingHTTPServer` の上に構築**。FastAPI/uvicorn は採用しない |
| Routing | in-repo の宣言的 v1 router（path template による route table）を実装する |
| Error contract | typed error envelope `{code, message, details, request_id, retryable}` を全 v1 endpoint に適用する |
| DTO | **pydantic v2 model**（既存 core dep。新規 dependency ゼロ） |
| OpenAPI | route table + pydantic schema から script が **OpenAPI 3.1 JSON を決定論的に生成**し、repo に commit、snapshot test で固定する |
| TS client | **openapi-typescript**（devDependency、build-time only）で TS 型を生成する。runtime dependency は増えない |

## Consequences

- 新規 runtime dependency ゼロで versioned API・typed error・OpenAPI が揃う。devDependency は openapi-typescript の 1 件。
- OpenAPI 生成は決定論的（P2）であり、route/schema の drift は snapshot test で hard-gate 化される（plan 04 §Testing、plan 10 backend hard gates）。
- 宣言的 router は in-repo 資産として保守する必要がある（framework の routing/validation 機能は使えない）。middleware 相当は router 層に閉じ込める。
- unversioned endpoint は facade として維持し、`/api/v1` へは段階的に移行する（legacy contract は G0 fixture で frozen）。

## Supersedes / 参照

- Supersedes: なし（初回決定）。`viz/__init__.py` docstring の FastAPI 記述は誤りとして訂正対象（plan 04:67）。
- 参照: plan 00:171、plan 04:14,67,160,168、reference_ci_and_contract_snapshots（CI-pin 履歴）、adr_backlog.md ADR-02。
