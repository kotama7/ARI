# 09 — Security, Performance, and Operations

> Status: planned  
> Dependencies: 02, 03, 04, 05  
> Gate: G5 — Production readiness

## Purpose

local research tool としての使いやすさを維持しながら、remote/HPC 経由で公開された場合の trust boundary、secret、filesystem、dangerous operation、concurrency を明確化する。同時に large run でも観測可能な performance budget と recovery/diagnostics を release gate にする。

## Scope

- bind/authentication/session/origin/CSRF/CORS policy。
- authorization、project/run boundary、dangerous operation confirmation。
- secret storage、redaction、file permission、key allowlist。
- filesystem canonicalization、symlink/path boundary、artifact access。
- CSP/XSS、安全な Markdown/rendering、dependency review。
- request/process/config audit、correlation、health、recovery。
- frontend/backend/realtime/bundle performance budgets。
- local、SSH tunnel、HPC reverse proxy の deployment profiles。

## Non-goals

- full multi-tenant enterprise IAM を最初の release で構築しない。
- Developer Mode や hidden button を authorization として扱わない。
- performance のために audit/source fidelity を失わない。
- remote mode の危険性を documentation だけで代替しない。

## P0 current risks to close

実装で確認済みの具体面を対象にする。

- 全 interface bind（dual-stack `""`）、authentication/session/CSRF の完全な不在、`Access-Control-Allow-Origin: *`（`/state` と `/api/gpu-monitor` だけが歴史的に ACAO を返さない）の組合せ。
- `GET /api/env-keys` が名前に `API_KEY`/`SECRET`/`TOKEN` を含む全 env 値を**平文**で、source file path とともに返す。
- `POST /api/env-keys` による arbitrary key/value の `.env` upsert（name allowlist、atomicity、permission、redaction 不足）。
- `GET /codefile?path=` が絶対 path を受け、境界が「active checkpoint 配下 or 任意の `*/checkpoints/*`」と緩い。
- `POST /api/delete-checkpoint` が body の path を rmtree する（server-side challenge なし）。`POST /api/stop` は pkill を含む。
- `GET/POST /api/ollama/<path>` の reverse proxy（設定された ollama_host への中継）。
- active checkpoint が無い状態での `POST /api/workflow{,/flow,/skills,/disabled-tools}` が**同梱の `ari-core/config/workflow.yaml` を黙って書き換える**（以後の全 CLI/GUI run の既定 pipeline を無警告で変更。checkpoint guard なし、検証済み）。
- filesystem path を global active project/checkpoint として採用する境界。module-global process/settings/staging（`viz/state.py`）による cross-tab/cross-project race。
- destructive operation の確認が client-side のみ（固定 `confirmed: true` や window.confirm 相当。server-issued challenge なし）。
- untrusted/generated content の unsafe HTML rendering、および `index.html` の CDN d3 `<script>`（supply chain / CSP 違反源。task 02 と共有）。

## Deployment trust modes

### Local mode — default

- loopback bind を既定とする。
- browser session と short-lived anti-CSRF token を使用するか、strict same-origin local policy を ADR で確定する。
- remote bind option を明示しない限り LAN へ公開しない。

### Shared/remote mode — explicit opt-in

- authenticated session、Origin validation、CSRF protection、same-origin CORS。
- TLS は reverse proxy termination を含む supported topology を文書化する。
- project/run permission と dangerous action permission を server-side 検証する。
- session timeout、logout、revocation、audit actor を持つ。

HPC portal/SSH tunnel/reverse proxy で同一 origin HTTP + SSE が成立する smoke fixture を用意する。

## Secret policy

- API は secret value を返さず `configured`、provider、source class、last updated のみ返す。
- secret key name は schema allowlist に限定する。
- newline/control character、path、oversized value を拒否する。
- write は owner-only mode、lock、temp file、fsync、atomic replace を使う。
- project save failure 前に installation secret だけ mutation しない transaction boundary を設ける。
- logs、errors、request traces、browser storage、bundle、manifest、export を redaction scan する。
- test connection の result も credential/URL query/header を redaction する。
- secret rotation と missing/revoked state を run readiness に反映する。

## Project, run, and filesystem isolation

- request path の project/run ID から repository root を解決し、client path を root として採用しない。
- resolved canonical path が PathManager 管理 root 配下か検証する。
- `..`、absolute path、symlink escape、race during replace を negative test する。
- global active selection は navigation convenience のみに限定し、read/write boundary に使わない。
- process supervisor は run ID、owner/session、PID、command digest を記録する。
- upload/staging は request/run scoped temporary directory と quota を使う。

## Dangerous operations

- delete、stop、restart、force resume、raw file write は risk level を持つ。
- server が short-lived confirmation challenge を発行し、対象 ID/action/revision と bind する。
- UI は impact preview、対象名、irreversible state、alternative を表示する。
- idempotency と audit event を必須にする。
- permission 不足時は control を隠すだけでなく server が拒否する。
- bulk operation は dry-run と explicit item count を持つ。

## Content and browser security

- generated Markdown/HTML は allowlist sanitizer を通す。
- `dangerouslySetInnerHTML` usage を inventory 化し、trusted renderer に集約する。
- CSP、frame policy、MIME sniffing、referrer policy を deployment profile ごとに設定する。
- API response を DOM HTML として直接挿入しない。
- dependency lockfile、vulnerability scan、license policy を release gate に含める。

## Performance budgets

G0 fixture で hardware/network 条件を固定し、以下を初期 hard budget とする。

| Surface | Budget |
|---|---|
| Production LCP | ≤ 2.5 s |
| Production INP | ≤ 200 ms |
| CLS | ≤ 0.1 |
| Main JS chunk | ≤ 100 KiB gzip after migration stabilization |
| Individual route chunk | baseline + 10% during migration、最終 ≤ 150 KiB gzip |
| Settings/Wizard route chunk | ≤ 50 KiB gzip each |
| Settings GET/PATCH p95 | ≤ 200 ms on reference fixture |
| Legacy `/state` p95 | ≤ 250 ms、payload ≤ 2 MiB on agreed 10k-node fixture |
| Launch accepted response p95 | ≤ 1 s excluding background start |
| In-flight duplicate reads | 0 for same query key |

budget は環境を固定して ratchet し、無条件の CI wall-clock 値にしない。remote SSH/high-latency/SSE-blocked simulation を別 profile で測る。

## Performance architecture

- route-level code splitting を維持し、heavy visualization/editor を遅延 load する。
- query cache、request dedup、AbortController、ETag、bounded retry を使う。
- hidden tab polling を停止し、SSE invalidation + snapshot query へ移す。
- tree/table/log/event は virtualization、LOD、cursor pagination を使う。
- workflow/skill scan は mtime cache/index を使う。
- projector work は request path で全 artifact を毎回再構築しない。
- Web Worker/worker thread 導入は profiling で main/request thread bottleneck を確認後に行う。

## Operational visibility

- `/health/live`、`/health/ready`、projector/realtime/process health を分離する。
- request ID、run ID、event correlation ID を log/error UI で共有する。既存の per-checkpoint access log（`viz_access.jsonl`）を request audit の起点として拡張する。
- SSE connection、projector lag、cache hit、queue depth、artifact parse errors を diagnostics に出す。
- raw metrics に secret/path leakage を含めない。
- index corruption は rebuild、read-only fallback、source artifact link を提供する。
- process orphan、stale lock、partial launch、partial config write の recovery command を定義する。

## Testing

- unauthenticated remote request、cross-origin mutation、CSRF、session expiry test。
- secret endpoint/readback/redaction/file mode/newline injection test。
- path traversal、absolute path、symlink escape、cross-project access test。
- confirmation challenge replay/wrong target/expired revision test。
- XSS payload、unsafe Markdown、CSP smoke test。
- same query dedup、hidden tab、abort、SSE fallback、large fixture benchmark。
- double launch、parallel save、process isolation、recovery test。
- local/SSH tunnel/HPC proxy deployment smoke test。

## Completion criteria

- default bind が loopback で、remote mode は authenticated/same-origin protected である。
- secret value の browser response/log/storage/export 出現が 0 件である。
- project/run/filesystem/process boundary が request-scoped で negative test を通る。
- dangerous operation が server-issued challenge と audit を持つ。
- performance budget と large-run fixture が CI/release gate で green である。
- degraded/recovery 状態を GUI と operator guide から確認できる。

## Deletion criteria

- security model、deployment、performance budget、recovery runbook を恒久文書へ移し、P0 legacy surface が削除済みである。

## Delete-after checklist

- [ ] security/deployment/recovery docs を公開した。
- [ ] threat model と performance dashboard の保守先を移した。
- [ ] legacy unsafe endpoint/global boundary を削除した。
- [ ] main merge と CI green を確認した。
- [ ] `INDEX.md` を更新した。

