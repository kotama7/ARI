# ADR-10: 同梱 `workflow.yaml` write guard の意味論

> Status: accepted（2026-07-23）  
> Owner: GUI refresh program（task 07/09）  
> Decision-by gate: G2（adr_backlog.md）

## Context

plan 07:96 / plan 09:39 / risk register **RR-P0-1**。active checkpoint 不在時の `POST /api/workflow{,/flow,/skills,/disabled-tools}` が同梱 `ari-core/config/workflow.yaml` を黙って書き換え、以後の全 CLI/GUI run の既定 pipeline を無警告で変更する（検証済み）。backlog では reject / 明示 opt-in / draft への redirect の 3 案が候補だった。

## Decision

| 項目 | 決定 |
|---|---|
| Guard 挙動 | active checkpoint 不在時、GUI の workflow **write endpoint は拒否する（400、side effect なし）**。opt-in や draft redirect は採用しない |
| 同梱 file | 同梱 `workflow.yaml` は **GUI からは read-only** とする（CLI/手動編集は本 ADR の範囲外） |
| Checkpoint copy | per-checkpoint copy への write は従来どおり可能（run-scoped 編集は維持） |
| Labeling | 「この編集はどの run に効くか」の保存時明示は Workflow Studio（**Wave 4**、task 07）で導入する。guard はそれを待たず先行する |
| 実装時期 | **Wave 2a で実装済み**。negative test と migration note **MN-1** を伴う |

## Consequences

- RR-P0-1 の是正手段が確定し、silent rewrite 経路は閉鎖された（close には是正 commit と negative test への link を risk register に記録する）。
- active checkpoint がない状態で workflow を編集したい user は、先に run/checkpoint を作る必要がある。GUI は 400 応答の error envelope でその旨を案内する。
- 挙動変更（従来は黙って書換に成功していた）のため MN-1 で告知する。互換 freeze はしない（G0 分類で P0 修正対象）。

## Supersedes / 参照

- Supersedes: なし（初回決定）。
- 参照: plan 07:96、plan 09:39、risk_register.md RR-P0-1、g0_review_record.md Known mismatch classification（P0 修正対象行）、migration note MN-1、adr_backlog.md ADR-10。
