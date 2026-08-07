# ADR-03: SSE と legacy WebSocket の共存期間

> Status: accepted（2026-07-23）  
> Owner: GUI refresh program（task 04）  
> Decision-by gate: G2（adr_backlog.md）

## Context

plan 00:172 / plan 04。legacy tree WebSocket は HTTP port+1・単一 channel・単一 message type（`{"type":"update"}`）で、proxy/HPC portal と相性が悪い（plan 04:31）。一方 SSE は既に 2 系統が同一 origin で稼働しており（`GET /api/logs`、`GET /api/paperbench/run/{job_id}/logs` の `Last-Event-ID` resume 付き、plan 04:32）、新 realtime はこの pattern の一般化とする方針が確定している。plan 04:145 は「legacy tree WebSocket は SSE parity が確認されるまで二重運転する」を要求する。

## Decision

| 項目 | 決定 |
|---|---|
| 新 stream | `GET /api/v1/events/stream`（SSE）を **Wave 2b** で導入する。同一 origin・同一 port（`/api/logs` で実証済みの pattern） |
| 共存 | legacy port+1 tree WebSocket は **並行運転を継続**する |
| parity 測定 | SSE の shadow-parity 測定は **Wave 5** で実施する（plan 04:162 shadow comparison） |
| 撤去 | WS の removal は **G6 で telemetry-gated**（parity 実測なしに撤去しない） |
| Fallback | frontend は撤去まで WS を fallback として保持する |

## Consequences

- 移行期間中は tree update が二重配信される。SSE 側の reconnect/duplicate/out-of-order は plan 04:173 の test 群で担保する。
- port+1 依存は G6 まで残るため、proxy 環境の制約解消は removal 後となる。
- removal は telemetry（WS fallback 発火率）を根拠とし、feature flag policy（ADR-07）の removal gate 規則に従う。

## Supersedes / 参照

- Supersedes: なし（初回決定）。
- 参照: plan 00:172、plan 04:31-32,145,162,173,183、ADR-07（removal gate）、adr_backlog.md ADR-03。
