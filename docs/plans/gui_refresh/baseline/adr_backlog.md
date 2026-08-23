# ADR Backlog

> Status: active working doc  
> Created: 2026-07-23  
> Owner: GUI refresh program  
> 移管先: docs/reference|concepts at G6

plan 00 §「Decisions to record as ADRs」の 7 件に、2026-07-23 の実装突き合わせで発見した 4 件を加えた backlog。decision-by gate は「この gate の exit 判定までに ADR が accepted であること」を意味する。

| ID | Title | Status | Decision-by gate | Notes |
|---|---|---|---|---|
| ADR-01 | Router と frontend server-state library の採用 | **accepted**（[ADR-01](../../../adr/gui/GUI-ADR-01-router-and-server-state.md)） | G2 | plan 00:170。task 03。hash router 維持 + @tanstack/react-query v5 採用（Wave 2b） |
| ADR-02 | `/api/v1` transport と OpenAPI client generation | **accepted**（[ADR-02](../../../adr/gui/GUI-ADR-02-api-v1-transport.md)） | G2 | plan 00:171。task 04。stdlib server 維持 + 宣言的 v1 router + pydantic v2 DTO + 決定論的 OpenAPI 3.1 生成。unversioned endpoint は compatibility facade として並行運転 |
| ADR-03 | SSE と legacy WebSocket の共存期間 | **accepted**（[ADR-03](../../../adr/gui/GUI-ADR-03-sse-websocket-coexistence.md)） | G2 | plan 00:172。task 04。SSE は Wave 2b、WS 撤去は G6 telemetry-gated。port+1 WS は proxy 非対応（plan 00:34） |
| ADR-04 | config schema metadata の格納方式と versioning | accepted（[ADR-04](../../../adr/gui/GUI-ADR-04-config-metadata-registry.md)） | G3 | in-code registry（`field_registry.py`）+ `schema_version`/`resolver_version` 二軸分離。Wave 3a 実装の正式化 |
| ADR-05 | secret provider と authentication mode | accepted（[ADR-05](../../../adr/gui/GUI-ADR-05-secret-provider.md)。auth は decision 5 で ADR-05 範囲外 → G5） | G3（provider）/ G5（auth） | provider = .env chain + readiness API（ADR-11）+ hardened legacy POST。canonical `PUT /secrets/{id}` と `catalogs/models` は Wave 4d で実装済み（2026-07-24 追記）。auth mode（decision 5 の残置分）は **ADR-13 で決定済み**（Wave 5b） |
| ADR-06 | read-model index の保存場所、再構築、破損時 recovery | open | G2 | plan 00:175。task 04/08。filesystem artifact が source of truth のまま、index は再構築可能な派生データ（plan 00:117） |
| ADR-07 | feature flag、rollback、legacy removal policy | **accepted**（[ADR-07](../../../adr/gui/GUI-ADR-07-feature-flag-policy.md)） | G2（初回 flag 導入前） | plan 00:176。task 10。`/api/capabilities` 配信の env-var kill-switch、flag は G6 を越えない |
| ADR-08 | 暗黙 default project の checkpoint search base への mapping | **accepted**（[ADR-08](../../../adr/gui/GUI-ADR-08-default-project.md)） | G2 | 検証で追加。plan 00:87。単一 virtual project `default`（file 書込なし、checkpoint-dir-name ID）。multi-project は将来 revision |
| ADR-09 | 「v1 は RQGM の GUI toggle なし」決定の supersede | **accepted**（[ADR-09](../../../adr/gui/GUI-ADR-09-mode-selection.md)） | G4 | 検証で追加。plan 05:176。`docs/guides/execution_modes.md` の明示決定を、**NEW run に限り** GUI からの mode 選択を許すことで supersede（`--mode` CLI flag なしは維持、resume/mid-run 変更は引き続き禁止）。orthogonal な 2 intent のみ開放（`ari.mode`+`rqgm.enabled` / `paper.mode`+`rqgm.paper.enabled`）— 1 control が pair の両 key を書き、half-set は 400 `mode_interlock_mismatch`。残る 96 の governance/tuning leaf は `mode_locked` のまま read-only 表示。default（`simple_bfts`+`linear`）は byte-identical。task 06/08。`resolve_effective_mode` の warn+fallback 意味論の GUI 表示規則（plan 05:173）= 解決後 mode の表示 + `requested → resolved` + warning 逐語。実装: `field_registry.MODE_INTERLOCK_PAIRS`・`viz/v1/launch.py`・`ConfigStudio/ExecutionSection.tsx`、MN-12 |
| ADR-10 | 同梱 `workflow.yaml` write guard の意味論 | **accepted**（[ADR-10](../../../adr/gui/GUI-ADR-10-workflow-write-guard.md)） | G2 | 検証で追加。plan 07:96、plan 09:39。active checkpoint 不在時は 400 reject（Wave 2a 実装済み、tests + MN-1）。task 07/09。risk register RR-P0-1 の是正手段 |
| ADR-11 | 平文 `GET /api/env-keys` を置換する secret readiness API | **accepted**（[ADR-11](../../../adr/gui/GUI-ADR-11-secret-readiness-api.md)） | G3 | 検証で追加。plan 05:187、plan 09:34。`GET /api/v1/secrets/status`（allowlist 済み name の `configured/source_class/last_updated` のみ）を新設し、旧 GET は deprecation 期間なしで即時 value redaction（shape 互換 adapter として存続、`redacted: true` marker）。POST は name allowlist を追加。task 05/09。risk register RR-P0-2 の是正手段（Wave 3a で closed、MN-2） |
| ADR-12 | GUI config document store の保存場所（`{workspace_root}/gui_store/`） | **accepted**（[ADR-12](../../../adr/gui/GUI-ADR-12-config-store-location.md)） | G3 | 実装突き合わせで追加。plan 05:88（Configuration scopes の保存場所は ADR で決める）。project default / run template / run draft を `{workspace_root}/gui_store/`（`checkpoints/` の sibling）に保存。revision→ETag/If-Match 写像、atomic write + owner-only mode、CLI は一切読まない（launch は従来どおり checkpoint へ materialize）。task 05。Wave 3b 実装済み（`ari/viz/v1/store.py`） |
| ADR-13 | remote-mode bearer-token authentication（`ARI_GUI_TOKEN`） | **accepted**（[ADR-13](../../../adr/gui/GUI-ADR-13-remote-bearer-token.md)） | G5 | ADR-05 decision 5 の残置分（auth mode）を決定。local（loopback bind）は無認証のまま不変、remote bind は `/health/*` を除く全 request に Bearer token を要求（未設定なら起動時生成 + stderr 一回表示の fail-secure）。SSE/WS は query `token`（EventSource が header を持てない tradeoff を記録）。cookie 不使用 = CSRF surface なし。session/multi-user は将来の multi-tenant ADR へ恒久 deferral。kill-switch `ARI_GUI_AUTH=0`。task 09。Wave 5b 実装済み（`ari/viz/auth.py`、MN-8、RR-P0-3 close） |

## 運用

- accepted な ADR は恒久置場 `docs/adr/gui/` に移管済み（2026-08-09）。本 backlog は decision-by gate と status の一覧として残り、決定本文は移管先が正本。
- 各 wave の gate review では、その gate を decision-by とする ADR が全て accepted であることを exit 条件に含める（g0_review_record.md 参照）。
- 新規 dependency、API、artifact、checkpoint field を伴う変更は ADR と migration note を必須とする（INDEX.md change control）。
