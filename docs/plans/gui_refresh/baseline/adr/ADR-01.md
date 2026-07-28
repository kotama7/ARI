# ADR-01: Router と frontend server-state library の採用

> Status: accepted（2026-07-23）  
> Owner: GUI refresh program（task 03）  
> Decision-by gate: G2（adr_backlog.md）

## Context

plan 00:170 / plan 03。既存 frontend は hand-rolled hash router を使い、Wave 1 で `src/app/routeRegistry.ts` 駆動の route registry（13 routes frozen、10-entry nav parity test 付き）へ整理済み。server-state（fetch の dedup、abort、retry、stale-time、cache invalidation）は plan 03 §State ownership が query cache library の選定を要求している。判断軸は (1) 新規 dependency の最小化（INDEX change control、CI-pin 履歴）、(2) bundle budget（plan 09）、(3) 車輪の再発明の禁止。

## Decision

| 領域 | 決定 |
|---|---|
| Router | **hand-rolled hash router を維持**。`src/app/routeRegistry.ts` を単一の正本とし、react-router は採用しない。Wave 1 で出荷済み・parity test 済みであり、置換の便益がない |
| Server-state | **@tanstack/react-query v5 を採用**（Wave 2b 導入）。dedup/abort/retry/stale-time を plan 03 §State ownership の規則どおりに担わせる |

react-query 相当を hand-rolling する案は、cache invalidation・in-flight dedup・abort 伝播の再発明にあたるため棄却。~13 KiB gzip は bundle budget（g0_review_record.md baseline + plan 09 ratchet）に収まる。

## Consequences

- 新規 runtime dependency は @tanstack/react-query v5 の 1 件のみ。migration note と bundle ratchet 更新を伴う（INDEX change control）。
- route 追加は routeRegistry 経由のみ。nav parity / route render baseline test が変更を検出する。
- server-state の手書き fetch hook は Wave 2b 以降 query cache へ順次移管し、二重 cache を残さない。

## Supersedes / 参照

- Supersedes: なし（初回決定）。
- 参照: plan 00:170、plan 03 §State ownership、g0_review_record.md（bundle baseline / Wave 1 exit record）、adr_backlog.md ADR-01。
