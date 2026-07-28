# ADR-12: GUI config document store の保存場所（`{workspace_root}/gui_store/`）

> Status: accepted（2026-07-23）  
> Owner: GUI refresh program（task 05）  
> Decision-by gate: G3（adr_backlog.md）

## Context

plan 05 §Configuration scopes は Project default / Run template / Run draft の各 scope を要求するが、現行実装の scope は実質二値（machine/env と per-checkpoint）で、durable な server-side 保存場所が存在しない（plan 05:88 は「導入時は保存場所と ownership を ADR で決める」と明記）。project は ADR-08 の virtual `default` 単一 project。v0.5.0 原則により `~/.ari` 等の global dir は廃止済みで、checkpoint 削除で template まで消える per-run 保存も不適。判断軸は (1) workspace-scoped で global dir を復活させない、(2) template/default は run より長命、(3) 既存 CLI / simple_bfts 経路と checkpoint 成果物を一切変えない additive 導入。

## Decision

| 項目 | 決定 |
|---|---|
| 保存場所 | **`{workspace_root}/gui_store/`**（`checkpoints/` の sibling）。`project_config.json`（ADR-08 の単一 default project の config document）、`run_templates/{template_id}.json`、`run_drafts/{draft_id}.json` |
| workspace_root 解決 | `ari.paths.RuntimePathResolver.resolve_workspace_root()`（`ARI_CHECKPOINT_DIR` 優先）— 他の workspace 消費者と同一 policy |
| Document envelope | `{"schema_version": 1, "kind": "<kind>", "revision": n, "body": {...}}` を決定論的 serialize（sort_keys、2-space indent、trailing newline）。kind は `project_config` / `run_template` / `run_draft` |
| Revision / ETag 対応 | `revision` は per-document 整数（初回 1、write 毎に +1）。HTTP 層では `ETag: "<revision>"` として返し、`If-Match: "<k>"` → `write(expected_revision=k)` に写像する。不一致は `RevisionConflict` → **409 Conflict**（typed error envelope）。`If-Match: "0"` は create-only。`If-Match` なしの write は unconditional（last-write-wins） |
| Write discipline | atomic write（same-dir temp file + fsync + `os.replace` + best-effort dir fsync）、file mode `0o600`、dir mode `0o700` — plan 09 §Secret policy の write discipline と同一（config であって secret ではないが同じ規律を適用） |
| ID | `template_id` / `draft_id` は **caller 供給の決定論的 ID**。`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` に fullmatch しない ID は reject（`/` も `.` も不可 — traversal を構造的に排除、plan 09 §isolation） |
| CLI との関係 | **CLI / simple_bfts 経路は `gui_store/` を一切読まない**（GUI-only convenience layer）。launch は従来どおり全ての effective 値を checkpoint（`launch_config.json` 等）へ materialize する。既存 checkpoint 成果物・resume 意味論は不変 |
| 実装 | `ari-core/ari/viz/v1/store.py`（Wave 3b）。route/DTO 公開は後続 stage（本 ADR は storage layer のみ） |

## Alternatives considered

- **`{ckpt}/` per-run 保存** — rejected: template / project default は run より長命で、checkpoint 削除（GUI の delete 導線）で消えてはならない。
- **repo `config/` 配下** — rejected: user data であって repo data ではない（同梱 `workflow.yaml` は ADR-10 で write-guard 済み。repo tree への user 書込は directory policy とも衝突）。
- **`~/.ari` global dir** — rejected: v0.5.0 原則（global dir 廃止、`rm -rf ~/.ari` で何も失われない）に反する。

## Consequences

- Configuration scopes（plan 05）の greenfield 三 scope に保存場所と ownership が確定し、後続の template/draft CRUD API は本 store の revision/ETag 意味論をそのまま公開できる。
- `gui_store/` は runtime 生成の workspace 配下 dir であり、repo tree には現れない — `check_directory_policy.py` Rule B は repo/top-level の storage-family 名（`checkpoint(s)`/`run(s)` 等）のみを policing し `gui_store` は family 外のため、checker 登録は不要（検証済み）。
- checkpoint 削除と store は独立: draft は launch 後も呼び出し側が明示 delete するまで残る（cleanup 方針は CRUD API stage の課題として残す）。
- multi-project 化（ADR-08 revision）の際は `project_config.json` の singleton 前提を本 ADR の revision で拡張する（`projects/{project_id}.json` 等）。

## Supersedes / 参照

- Supersedes: なし（初回決定）。
- 参照: plan 05:74-101 §Configuration scopes（特に :88）、plan 09 §Secret policy（write discipline）・§Project, run, and filesystem isolation、ADR-08（virtual default project）、ADR-10（同梱 workflow.yaml write guard）、adr_backlog.md ADR-12、実装: `ari-core/ari/viz/v1/store.py`、tests: `ari-core/tests/test_gui_v1_store.py`。
