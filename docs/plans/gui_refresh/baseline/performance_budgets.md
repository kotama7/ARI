# Performance Budgets — enforcement record

> Status: active working doc  
> Created: 2026-07-26  
> Owner: GUI refresh program (task 09)  
> 移管先: docs/reference|concepts at G6

## 目的

plan 09「Performance budgets」（09_security_performance_and_operations.md:98）の hard budget を、**いま CI で機械的に enforce できるもの**と**理由付きで defer するもの**に分割し、その enforcement 状態と実測値を記録する（Wave 5a exit record「残 G5 scope」項目 2 の formalization 判断の実装）。risk register **RR-PR-5**（性能退行）の control の実体はこの文書が指す checker/test 群である。

## Hard budgets（plan 09）と enforcement 状態

| Budget（plan 09 表） | 値 | 状態 | 実体 |
|---|---|---|---|
| Main JS chunk | ≤ 100 KiB gzip | **CI enforce（Wave 5b）** | `scripts/check_bundle_budget.py`（entry class） |
| Individual route chunk | 最終 ≤ 150 KiB gzip | **CI enforce（Wave 5b）** | 同上（route class。migration 中の baseline+10% ratchet は budget 縮小で運用） |
| Settings/Wizard route chunk | ≤ 50 KiB gzip each | **CI enforce（Wave 5b）** | 同上（`route_overrides`） |
| （追加）total JS | ≤ 600 KiB gzip | **CI enforce（Wave 5b）** | 同上（aggregate。導出根拠は下記） |
| In-flight duplicate reads | 0 for same query key | **構造的保証（v2 面）** | `@tanstack/react-query` の query-key 単位 dedup（`useV1` hooks）。legacy `AppContext` の `/state` polling と MonitorPage の 5s poll は残存 — plan 03/07 の移行 scope（RR-P0-8 系） |
| hidden tab polling → SSE | — | **部分達成** | `shared/realtime/eventStream.ts`（SSE + poll fallback）+ `useRunEvents`。legacy polling の全廃は plan 03 の shell 移行完了時 |
| Production LCP | ≤ 2.5 s | **deferred → G6 dogfood** | 下記「Browser metrics の deferral」 |
| Production INP | ≤ 200 ms | **deferred → G6 dogfood** | 同上 |
| CLS | ≤ 0.1 | **deferred → G6 dogfood** | 同上 |
| Settings GET/PATCH p95 | ≤ 200 ms on reference fixture | **manual（profile smoke）** | plan 09 の明示方針どおり「無条件の CI wall-clock 値にしない」— deployment profile smoke（G5/G6）で固定環境計測 |
| Legacy `/state` p95 / payload | ≤ 250 ms / ≤ 2 MiB on 10k-node fixture | **manual（profile smoke）** | 同上 |
| Launch accepted p95 | ≤ 1 s excluding background start | **manual（profile smoke）** | 同上 |

静的 security invariant（CSP header・CDN 再侵入 guard）は Wave 5a で既に CI 化済み（`test_gui_csp_headers.py` / `indexHtmlNoExternalScripts.test.ts`）。

## CI enforcement の実体（Wave 5b 新設）

- **`scripts/check_bundle_budget.py`** — built dist（`ari-core/ari/viz/static/dist/assets/*.js`）を in-process gzip（level 6 = Vite reporter と同一 zlib 既定、`mtime=0` で決定的）で計測し、entry（`index.html` の module script 参照から同定）/ route（`<Name>Page-<hash>.js`）/ shared（その他）/ total の各 budget と比較する。finding id は content hash 非依存（`bundle:<class>:<stem>`）で rebuild を跨いで安定。checker family の envelope / `--fail-on-regression` / allowlist 規約に準拠（allowlist は現在空 — 全 budget green のため file 未設置）。
- budget 値は `scripts/quality/check_bundle_budget.yaml`（1 行 diff で ratchet 可能）。
- **`scripts/tests/test_check_bundle_budget.py`** — fake-dist unit（over/within/override/aggregate/決定性）+ real-dist smoke（build 不在時は明示 message で skip。plan-09 budget を実 build に対して assert）。
- `scripts/quality/generate_quality_report.yaml` に登録済み（dist 未 build 時は `unavailable` として graceful degradation）。

### shared class と total budget の導出根拠

- plan 09 が個別 budget を持つのは route chunk のみだが、**shared chunk にも同じ 150 KiB cap を適用**する（保守的 superset。現在最大の shared は zoom ≈ 15.6 KiB。mis-split した vendor bundle が route class の外に隠れる failure mode を塞ぐ）。
- **total 600 KiB gzip** は 2026-07-26 実測 ~261 KiB の約 2.3 倍。per-chunk budget では見えない「多数 chunk への依存重複」「小 chunk の増殖」を捉える aggregate ceiling として、G4–G6 の機能増（Workflow Studio / Config Studio / Governance 系 view）の headroom を残しつつ設定。target ではなく ratchet 上限であり、G6 で表面完成後に締め直す。

## 実測値（2026-07-26、現 build、gzip level 6 / KiB = 1024 bytes）

| 項目 | 実測 | budget | 余裕 |
|---|---|---|---|
| main entry `index-*.js` | **59.4 KiB**（60,819 B。Vite 表示系列では 60.8 kB — Wave 5a record の 60.72 と同系列） | 100 | 41% |
| 最大 route `WorkflowPage` | **39.1 KiB** | 150 | 74% |
| `SettingsPage` | **6.7 KiB** | 50 | 87% |
| `WizardPage` | **13.7 KiB** | 50 | 73% |
| 最大 shared `zoom` | **15.6 KiB** | 150 | 90% |
| total JS（46 chunks） | **261.0 KiB**（267,294 B） | 600 | 57% |

検証 run: `python scripts/check_bundle_budget.py --fail-on-regression` → **exit 0、findings 0**。

## Browser metrics（LCP / INP / CLS）の deferral — 理由と計測計画

**理由（Wave 5a exit record 判断の詳細化）**: LCP/INP/CLS は real browser の rendering/input pipeline でしか定義されない。現 CI の frontend harness は jsdom（vitest）で layout も paint も input timing も持たず**測定自体が不可能**。また共有 runner 上の headless 計測は分散が大きく、hard budget を pass/fail にすると flaky gate になる — plan 09 自身が「budget は環境を固定して ratchet し、無条件の CI wall-clock 値にしない」と規定しており、browser harness を固定環境で持つまで CI gate 化しない。

**計測計画（G6 cutover dogfood で実施）**:

1. 固定環境: 同一 machine class・loopback・代表 10k-node fixture checkpoint を active にして `ari viz` を起動（`npm run build` 済み dist を配信する production 相当経路）。
2. LCP/CLS: `npx --yes lighthouse http://127.0.0.1:<port>/ --preset=desktop --only-categories=performance --output=json --output-path=perf_run<n>.json` を 3 run、median を採用。対象 route は home / tree / settings / workflow の 4 面。
3. INP: Playwright（chromium）で `web-vitals` attribution build を page に inject し、代表操作 script（route 遷移・tree node 選択・Settings 編集・dangerous-op dialog）実行後の INP 値を採取。3 run median。
4. 記録先: g0_review_record.md の G6 dogfood exit record に表として転記し、budget 超過は G6 blocker として risk register に行を立てる。恒久化（docs/reference への budget 表移管 + 再計測手順）は plan 09 Deletion criteria に従う。
5. 将来 CI 化する場合は専用 self-hosted runner での Lighthouse CI（assertion 付き `lighthouserc`）を別 ADR で判断する — 共有 runner では導入しない。

## RR-PR-5 との対応

risk_register.md RR-PR-5（性能退行）は本 Wave で **partial enforcement** へ更新（row は open 維持）: bundle weight budget は `check_bundle_budget.py` が CI enforce、browser metrics は上記計画で G6 dogfood へ deferral。G6 で browser 計測記録が揃った時点で close 判定する。

## Deletion criteria

- budget 表・計測 protocol・ratchet 運用が docs/reference|concepts の恒久文書へ移管され、G6 dogfood の browser 計測記録が exit record に転記済みであること。
