# ADR-13: Remote-mode bearer-token authentication（ARI_GUI_TOKEN）

> Status: accepted（2026-07-26）  
> Owner: GUI refresh program（task 09）  
> Decision-by gate: G5（ADR-05 decision 5 の残置分。adr_backlog.md）

## Context

ADR-05 decision 5 は authentication mode（local same-origin policy / remote session）を G5 判断として残置した（plan 09 §Deployment trust modes）。Wave 5a で RR-P0-3 の bind+CORS sub-scope は是正済み（MN-4: loopback 既定 bind + same-origin CORS）だが、`ARI_GUI_BIND` で remote bind を opt-in した瞬間に全 endpoint が**無認証**で LAN/cluster に露出する状態は残っていた。ARI は single-operator の research tool であり（plan 09 Non-goals: 「full multi-tenant enterprise IAM を最初の release で構築しない」）、判断軸は (1) 既定の loopback 体験を一切変えない（INVARIANT）、(2) remote bind を fail-secure にする（無認証で立ち上がる経路を残さない）、(3) stdlib HTTP server + port+1 WebSocket + SSE という既存 transport で成立する最小機構。

## Decision

| 項目 | 決定 |
|---|---|
| Local mode（既定） | bind が loopback のみに解決される場合（`ARI_GUI_BIND` 未設定/blank）は**無認証のまま不変**。MN-4 の loopback bind + same-origin CORS が local の保護である。`ARI_GUI_TOKEN` を export していても local mode では作動しない（mode は bind だけで定義） |
| Remote mode | `ARI_GUI_BIND` が非 loopback（`'::'`/`'0.0.0.0'`/`''`/LAN address）の場合、`/health`・`/health/*` prefix を除く**全 HTTP request** が `Authorization: Bearer <ARI_GUI_TOKEN>` を要求する。gate は `do_GET/do_POST/do_PUT/do_PATCH/do_DELETE` 先頭の単一検査（dispatch/body read 前。`ari/viz/auth.py` + `routes.py _auth_gate`）。`do_OPTIONS`（CORS preflight は credential を運べない）は対象外 |
| Fail-secure 生成 | remote bind で `ARI_GUI_TOKEN` 未設定なら、server が起動時に random 32-hex token を生成し **stderr へ一度だけ** banner 表示して使用する（`server.py _print_generated_token_banner`）。remote bind が黙って無認証で立ち上がる経路は存在しない |
| 拒否応答 | 401 + typed JSON body `{"error": {"code": "unauthorized", "message": ...}}` + `WWW-Authenticate: Bearer`。比較は定数時間（`hmac.compare_digest`）。token は応答にも log にも現れない |
| SSE / WebSocket | browser の `EventSource` と WebSocket API は header を設定できないため、`EventSource` 消費の SSE（`/api/v1/events/stream`、paperbench job logs）と WS handshake（`process_request`）は同じ token を **query parameter `token`** でも受理する（fetch 消費の legacy `/api/logs` stream は header 認証 — 消費側の `MonitorPage` が header を送れるため query form は追加しない）。**受容した tradeoff**: query string は URL に現れるため、(a) access log は `token=` 値を `***` に redaction（`auth.redact_token_in_path` → `viz_access.jsonl`）、(b) Referrer 漏洩は MN-7 の `Referrer-Policy: no-referrer` が遮断、(c) browser history 上の露出は single-operator token（revoke = env 変更 + 再起動）として受容 |
| Frontend | `services/api/client.ts` が localStorage `ari_gui_token`（operator が手動設定）を読み、全 request に `Authorization` を付与、SSE/WS URL には `token=` を付与（`getGuiToken`/`authHeaders`/`withTokenParam`）。token 未設定（loopback 既定）では request shape は byte-identical。Settings 画面への token 入力 UI は follow-up（本 ADR の scope 外） |
| CSRF / session | cookie を一切使わないため CSRF surface は存在しない。session/logout/revocation/multi-user は**恒久的に将来の multi-tenant ADR へ deferral**（single-operator research tool。plan 09 の session timeout 系要求はこの deferral で supersede） |
| Kill-switch | `ARI_GUI_AUTH=0|false` で remote gate を無効化（ADR-07 register は `ari/viz/auth.py` docstring。既に認証を終端する reverse proxy 配下等の rollback lever。removal gate なし — fail-secure 自体は恒久 policy） |

## Alternatives considered

- **Session cookie + CSRF token** — rejected: cookie を導入すると CSRF surface が生まれ、その防御一式（anti-CSRF token、SameSite、origin 検証の強化）が必要になる。Bearer token は browser が自動送信しないため CSRF が構造的に成立しない。
- **WS/SSE の subprotocol / first-message 認証** — rejected: handshake 前に接続を拒否できず（first-message 方式）、または client library の互換を壊す（subprotocol 悪用）。query param + log redaction の方が単純で検証可能。
- **remote bind 時の起動拒否（token 必須化）** — rejected: fail-secure 生成の方が HPC batch 起動（env 配線が難しい）でも安全側で動き、operator は stderr の banner から token を回収できる。

## Consequences

- RR-P0-3 の残 sub-scope（authentication/session/CSRF）が close される（risk_register 更新。CSRF は「cookie 不使用により surface なし」として close）。
- ADR-05 decision 5 の open 事項は本 ADR で決定済みとなる（adr_backlog の ADR-05 行を更新）。
- 挙動変更は MN-8 として告知（remote bind の既存利用者は token 設定または `ARI_GUI_AUTH=0` が必要。loopback 既定は不変）。
- multi-user/session 管理を将来導入する場合は本 ADR を supersede する multi-tenant ADR を起こす（token 単一・全権限という現行モデルの拡張はしない）。
- Settings 画面の token 診断/入力 UI は follow-up backlog（現状は `localStorage.setItem('ari_gui_token', ...)` を deployment doc に記載）。

## Supersedes / 参照

- Supersedes: ADR-05 decision 5 の「open のまま G5 で決定」を解消（ADR-05 本体の provider 決定は不変）。
- 参照: plan 09 §Deployment trust modes・§Operational visibility（access log）、ADR-05、ADR-07（kill-switch 形式）、MN-4（bind+CORS）、MN-7（Referrer-Policy）、MN-8、risk_register.md RR-P0-3、実装: `ari-core/ari/viz/auth.py`・`routes.py`・`websocket.py`・`server.py`・`frontend/src/services/api/client.ts`、tests: `ari-core/tests/test_gui_remote_auth.py`。
