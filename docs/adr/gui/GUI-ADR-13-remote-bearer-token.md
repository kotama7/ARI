# GUI-ADR-13 (ADR-13): remote-mode bearer-token authentication

Decision: the authentication mode is defined by the bind alone. Local mode —
`ARI_GUI_BIND` unset or blank, which `server.resolve_bind_hosts` resolves to
`["127.0.0.1", "::1"]` — stays unauthenticated; the loopback bind plus
same-origin CORS is the local protection, and an exported `ARI_GUI_TOKEN` is
inert there. Remote mode — `ARI_GUI_BIND` naming a non-loopback host, including
the wildcards `::` and `0.0.0.0` — requires `Authorization: Bearer
<ARI_GUI_TOKEN>` on every HTTP request outside the `/health` and `/health/*`
prefix, enforced by one gate at the top of `do_GET`/`do_POST`/`do_PUT`/
`do_PATCH`/`do_DELETE` before any dispatch or body read (`auth.gate_request`
via `routes._Handler._auth_gate`, marked MN-8 in the code). `do_OPTIONS` is
exempt: a CORS preflight carries no credentials. A remote bind with no
`ARI_GUI_TOKEN` is fail-secure rather than open — the server generates a random
32-hex token at startup and prints it once to stderr
(`server._print_generated_token_banner`); no path starts a remote bind
unauthenticated. Refusals are 401 with typed JSON `{"error": {"code":
"unauthorized", ...}}` plus `WWW-Authenticate: Bearer`; comparison is
`hmac.compare_digest`; the token appears in no response and in no log —
`auth.redact_token_in_path` rewrites `token=` values to `***` before
`viz_access.jsonl` records the path. Because `EventSource` and the browser
WebSocket API cannot set headers, the same token is also accepted as the
`token` query parameter, which is how `/api/v1/events/stream`, the paperbench
run-log stream and the WS handshake (`websocket._ws_process_request`) are
authenticated; the fetch-consumed legacy `/api/logs` stream sends the header.
No cookie is used anywhere, so CSRF has no surface. `ARI_GUI_AUTH=0|false` is
the ADR-07-style kill-switch (registered in the `ari/viz/auth.py` docstring)
and has no removal gate — fail-secure remote auth is permanent policy.

Rejected alternatives: a session cookie plus CSRF token, because a cookie
creates the CSRF surface and drags in its whole defence set (anti-CSRF token,
SameSite, hardened Origin checks), while a bearer token the browser never
auto-sends cannot form CSRF at all. WebSocket subprotocol or first-message
authentication, because first-message cannot refuse before the connection
exists and subprotocol abuse breaks client-library compatibility; a query
parameter with log redaction is simpler and directly testable. Refusing to
start on a remote bind without a token, because generation stays on the safe
side under batch launch, where wiring the environment is awkward, and the
operator recovers the token from the stderr banner. The wider option — a full
multi-tenant IAM — was ruled out by the program's own non-goal of not building
enterprise IAM in the first release; this is a single-operator research tool.

Consequences: the query form puts the token in a URL. Referrer leakage is
blocked by the `Referrer-Policy: no-referrer` header `routes.py` sends, and log
exposure by the redaction above, but browser-history exposure is accepted for a
single-operator token whose revocation is an environment change plus a restart.
Existing remote-bind users must set a token or `ARI_GUI_AUTH=0`; the loopback
default is unchanged, and with no token configured the frontend emits
byte-identical requests. The frontend reads `localStorage` key `ari_gui_token`
in `ari/viz/frontend/src/services/api/client.ts` (`getGuiToken`, `authHeaders`,
`withTokenParam`); there is still no Settings UI for entering it, so priming it
by hand remains the documented step and the UI remains follow-up. Sessions,
logout, revocation and multi-user are permanently deferred to a future
multi-tenant ADR, which would supersede this one — the single all-powerful
token is not to be extended in place.

Supersedes: ADR-05 decision 5, which left the authentication mode (local
same-origin policy versus remote session) open for a later gate, is closed by
this record; ADR-05's secret-provider decision is untouched. The plan's
shared/remote-mode requirement for session timeout, logout, revocation and an
audit actor is superseded by the deferral above. This also closes the
authentication/session/CSRF part of the P0 risk that paired an all-interface
bind with a complete absence of authentication, session and CSRF protection;
CSRF closes as "no cookies, therefore no surface".

Divergence from the code as written: the record lists `''` among the
`ARI_GUI_BIND` values that select remote mode, but blank is indistinguishable
from unset in `resolve_bind_hosts`, which returns the loopback default, so a
blank `ARI_GUI_BIND` yields local mode. Only the pure helper `is_remote_bind`
treats a literal empty host as remote, and the resolver never hands it one.
Second, the record scopes the `token` query parameter to SSE and the WS
handshake; `auth.gate_request` in fact accepts it on every request and method,
and the SSE/WS scoping is a frontend convention, not a server restriction.

Permanent documentation: `docs/guides/remote_access.md`, sections "Token
authentication in remote mode", "Why SSE and WebSocket use a query parameter",
"No cookies, therefore no CSRF", "The `ARI_GUI_AUTH` escape hatch" and "Access
log". Owning tests: `ari-core/tests/test_gui_remote_auth.py`, notably
`test_resolve_token_local_mode_is_no_auth_even_with_token`,
`test_remote_get_without_token_is_401_typed_body`,
`test_remote_generated_token_is_enforced`,
`test_kill_switch_restores_unauthenticated_remote`,
`test_legacy_logs_stream_uses_bearer_header`,
`test_ws_handshake_remote_accepts_query_token` and
`test_access_log_redacts_query_token`.
