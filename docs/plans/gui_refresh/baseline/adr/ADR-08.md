# ADR-08: 暗黙 default project の checkpoint search base への mapping

> Status: accepted（2026-07-23）  
> Owner: GUI refresh program（task 04/05）  
> Decision-by gate: G2（adr_backlog.md）

## Context

plan 00:87。Project/Run 分離は greenfield であり、現状の GUI は複数の checkpoint search base を scan した結果を暗黙の単一 project として扱っている。`/api/v1` の resource 設計（task 04）には project 概念が必要だが、real の multi-project persistence（作成・命名・permission）は Configuration control plane（task 05）の Project scope 実装まで確定できない。ID 安定性と「file を書かない」制約（filesystem が source of truth、plan 00:117）が判断軸。

## Decision

| 項目 | 決定 |
|---|---|
| v1 表現 | `/api/v1` は **単一の virtual project `{project_id: "default"}`** を公開する |
| 集約規則 | virtual project は既存の checkpoint search base 群の scan 結果を集約する。**file は一切書かない** |
| Run list | default project の run list == 現行の checkpoint scan 結果（新しい列挙 semantics を発明しない） |
| ID | run ID は checkpoint-dir-name based を維持する（既存 fixture/契約と互換） |
| 将来 | real の multi-project persistence は task 05 の Project scope 着地時に **本 ADR の revision** として確定する（本決定はそれを妨げない最小形） |

## Consequences

- `/api/v1` の URL 構造は初日から project-scoped（`/projects/default/...`）にでき、multi-project 導入時に breaking change を避けられる。
- persistence を持たないため、search base の増減はそのまま default project の内容変化として現れる（決定論的、P2 適合）。
- 複数 base 間で dir 名が衝突した場合の disambiguation は revision 時の課題として明示的に残す（現行 GUI と同等の挙動を維持）。

## Supersedes / 参照

- Supersedes: なし（初回決定）。multi-project 着地時に revision 予定。
- 参照: plan 00:87,117、task 04（`/api/v1` resource 設計）、task 05（Project scope）、adr_backlog.md ADR-08。
