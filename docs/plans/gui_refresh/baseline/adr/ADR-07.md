# ADR-07: Feature flag、rollback、legacy removal policy

> Status: accepted（2026-07-23）  
> Owner: GUI refresh program（task 10）  
> Decision-by gate: G2（初回 flag 導入前、adr_backlog.md）

## Context

plan 00:176 / plan 10 §Feature flag policy。flag は route/vertical slice 単位で owner・default・metrics・rollback・removal gate を持ち、恒久的な二重 architecture として残さない（plan 10:23,103-109）。Wave 1 で最初の flag（`ARI_GUI_V2`）と server capability endpoint が出荷されたため、policy の確定が必要になった。

## Decision

| 規則 | 内容 |
|---|---|
| 配信 | flag の値は server capability endpoint `GET /api/capabilities`（Wave 1 出荷済み）経由で frontend へ配信する。frontend 独自の flag 正本は持たない |
| 形式 | flag は **env-var kill-switch**。off 判定は exact-literal（`'0'`, `'false'`）のみ。それ以外の値・未設定は default に従う |
| Fail-open | read-only UI に対する flag は **fail-open**（capability 取得失敗時に表示を止めない）。write 系操作には fail-open を適用しない |
| 宣言 | 各 flag は定義 module の docstring に owner / default / rollback lever / removal gate を必ず宣言する |
| 寿命 | **G6 を越えて生存する flag はゼロ**（INDEX change control。RR-PR-2 の control） |

## Consequences

- flag 追加は capability endpoint への追記 + docstring 宣言 + removal gate 割当が揃って初めて許可される。
- rollback は「env var を off-literal に設定して再起動」に統一され、支援手順が flag ごとに分岐しない。
- G6 gate review は残存 flag の棚卸しを exit 条件に含める（flag combination explosion の防止、plan 10:109 の support matrix）。

## Supersedes / 参照

- Supersedes: なし（初回決定）。
- 参照: plan 00:176、plan 10:23,53,103-109,186、risk_register.md RR-PR-2、g0_review_record.md（Wave 1 exit record: `/api/capabilities` + `ARI_GUI_V2`）、adr_backlog.md ADR-07。
