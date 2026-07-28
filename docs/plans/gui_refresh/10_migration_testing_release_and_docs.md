# 10 — Migration, Testing, Release, and Documentation

> Status: planned  
> Dependencies: 01–09  
> Gate: G6 — Cutover

## Purpose

全面刷新を検証可能な小さな vertical slice に分割し、旧 GUI/API/checkpoint を維持したまま段階的に既定化する。contract、security、performance、a11y、i18n、rollback を hard gate とし、実装完了だけで release 完了としない。

## Scope

- baseline restoration と compatibility fixture。
- feature flag、shadow read/write、canary、default-on、legacy removal。
- frontend/backend/contract/E2E/a11y/visual/security/performance test。
- CI hardening、coverage ratchet、release telemetry、rollback drill。
- data/config/checkpoint migration と documentation transfer。

## Non-goals

- red baseline のまま新 UI の失敗を許容しない。
- legacy behavior の既知不具合をすべて互換対象にはしない。
- feature flag を恒久的な二重 architecture として残さない。
- checkpoint の in-place destructive migration を要求しない。

## Baseline observation

2026-07-22 の現 worktree 調査では、frontend test は `43 passed / 2 failed / 2 todo`、typecheck は既存 11 error、関連 backend test は `398 passed / 1 failed / 8 skipped` だった。これは release baseline ではなく、G0 前に次へ分類する観測値である。

- target branch 自体の defect。
- uncommitted worktree による drift。
- intentional contract change。
- flaky/environment-dependent failure。

刷新の回帰と既存 failure を混同しないため、G0 は clean target branch と固定 toolchain で green baseline を作るまで通過させない。

## Migration waves

### Wave 0 — Baseline and ADR

- current route/nav、Settings 契約（24-key POST / 27-key GET）、API method/path/body/status を golden fixture 化する。既存資産を起点にする: `scripts/snapshot_contracts.py` + `tests/test_contract_snapshots.py`、`ari/schemas/viz_*.schema.json`、`SettingsContract.test.tsx`、`check_viz_api_schema` / `check_dashboard_ux` の allowlist baseline。
- `settings.json`、workflow YAML、launch config、old checkpoint、RQGM artifact（`ari/schemas/` の rqgm/proposal/governance schema 群）の version fixture を作る。
- Generate/Chat/Upload/Launch の known request/response mismatch（少なくとも F6a: `POST /api/paperbench/run/{id}/report` の FE→BE drift）を互換対象か修正対象か分類する。
- large run、large tree、10k event、corrupt/partial artifact fixture を固定する。
- P0 security issue と existing red tests を解消または blocking issue 化する。

**Exit:** G0 contract freeze、green baseline、ADR 承認。

### Wave 1 — Shell and design foundation

- semantic tokens、common async states、route registry、hash router、new shell を導入する。
- old page を新 shell 内にそのまま mount する。
- `ARI_GUI_V2` 相当の server capability/feature flag で旧 bundle/shell へ戻せるようにする。
- route、visual、a11y、i18n baseline を固定する。

**Exit:** old URL/API のまま新 shell で主要 journey が動作。

### Wave 2 — API and state platform

- application/repository seam、`/api/v1`、OpenAPI client、run-explicit query を導入する。
- query cache、typed error、correlation、SSE を read-only resource から導入する。
- legacy poll/WebSocket と shadow parity を測る。
- Projects/Overview を最初の end-to-end vertical slice とする。

**Exit:** two-run isolation、SSE reconnect、legacy rollback が実証済み。

### Wave 3 — Configuration control plane

- schema registry、resolver、provenance、secret provider、atomic persistence を導入する。
- legacy Settings adapter と canonical API を並行運転する。
- read-only effective config → project/template edit → durable run draft の順に広げる。
- legacy payload/env mapping と shadow serialization diff を測る。

**Exit:** config coverage 100%、secret leakage 0、precedence parity、G3 通過。

### Wave 4 — Product vertical slices

- Configuration Studio/Wizard、Monitor、Tree、Ideas、Results/PaperBench、Workflow を順次移行する。
- RQGM は tables/source trace から開始し、Registry、Score Lineage、Evolution を追加する。
- route 単位で dogfood → opt-in canary → cohort default-on とする。
- user-visible behavior change は migration note と in-product notice を伴う。

**Exit:** 各 workspace の capability/a11y/performance gate と G4 通過。

### Wave 5 — Hardening and default-on

- security threat model、remote mode、dangerous operation、path/secret tests を hard gate 化する。
- large fixture、bundle、network simulation、recovery drill を実行する。
- 新 UI を既定化し、旧 UI へ即時 rollback 可能な状態を最低 1 minor 維持する。
- schema/read mismatch、launch mismatch、legacy fallback、error rate を観測する。

**Exit:** G5、2 release window の安定性、rollback drill 成功。

### Wave 6 — Legacy removal and documentation transfer

- usage telemetry が removal threshold を満たした route/endpoint/adapter だけを削除する。
- AppContext remote state、manual router、old WebSocket、duplicate constants/CSS、legacy Settings/Wizard を削除する。
- public API removal は release policy に従い、必要なら major release へ送る。
- plan の知識を reference/guides/getting-started/concepts へ移管する。

**Exit:** G6、plan delete-after checklist 完了。

## Feature flag policy

- flag は route/vertical slice 単位で、owner、default、metrics、rollback、removal gate を持つ。
- old/new が同じ canonical storage を読めるようにし、data downgrade を rollback 条件にしない。
- shadow mode は secret を除外し、side effect を発生させない。
- emergency rollback は deploy 不要で旧 shell/route へ戻せる。
- flag combination explosion を避け、program wave に沿った support matrix を固定する。

## Frontend hard gates

```text
npm ci
npm run typecheck
npm test
npm run build
```

- path-based CI で frontend 変更時に上記を必須化する。
- reducer、serializer、API wrapper、config resolver adapter は line/branch coverage 90% 以上。
- 全体 coverage は初期 baseline を取得し、80% を目標に ratchet して低下を禁止する。
- Playwright は Chromium/Firefox で critical journey を実行する。
- axe critical/serious 0、keyboard journey、focus restore、ARIA tabs/dialog を検証する。
- EN/JA/ZH parity と desktop/mobile visual regression を必須化する。
- production bundle budget と Lighthouse profile を release gate にする。

## Backend and contract hard gates

- core pytest と viz-specific pytest を明示的に両方実行する。
- all-skill test は別 process runner として release candidate で実行する。
- ephemeral live server で Settings/Generate/Chat/Upload/Launch/RQGM API を検証する。
- malformed JSON、wrong type/range、unknown field、0/null、concurrency、rollback を含める。
- `scripts/check_viz_api_schema.py --fail-on-regression` は known allowlist（現状 F6a を含む frozen baseline）をゼロへ ratchet して hard gate 化する。
- dashboard UX checker（`scripts/check_dashboard_ux.py`）を CI 接続し、allowlist は増加禁止・減少のみ許可する。
- OpenAPI、file schema、event schema、env mapping、legacy adapter の golden diff を検査する。
- test は外部 network を使わず、LLM/scheduler/subprocess を deterministic fake にする。

## Critical E2E matrix

| Journey | Variants |
|---|---|
| Settings | load/save/reload、validation、conflict、offline、secret readiness |
| New run | generate、upload、back/forward、refresh、invalid、launch success/failure |
| Launch | double click、retry、parallel run、unique ID、canonical redirect |
| Resume | legacy/new checkpoint、mutable/immutable override、clone instead |
| Monitor | live、SSE reconnect、SSE blocked fallback、stale、terminal |
| Tree/results | large data、deep link、evidence lineage、export |
| Workflow | valid/invalid、autosave conflict、offline、active snapshot |
| RQGM | no capability、epoch change、score rewrite、policy split、corrupt log |
| Security | unauth remote、cross-origin、path escape、secret leak、challenge replay |

## Compatibility matrix

- fresh install × upgrade。
- old/new UI × legacy/canonical API。
- `simple_bfts` × RQGM exploration on/off × paper mode on/off。
- new run × resume × clone。
- laptop × HPC profile × cloud profile。
- local loopback × SSH tunnel × HPC reverse proxy。
- small/medium/large/corrupt checkpoint。
- 日本語 × 英語 × 中国語。

## Release telemetry and stop conditions

最低限、privacy-safe な aggregate として以下を観測する。

- route success/error、schema mismatch、adapter mismatch。
- config validation failure category と conflict rate。
- launch accepted/started/failed、idempotency collision。
- SSE reconnect/fallback、projector lag、stale view。
- legacy route/API fallback usage。
- performance budget percentile と bundle size。

次の場合は rollout を停止または rollback する。

- cross-run data mix、secret exposure、unauthorized mutation。
- config/launch shadow mismatch が threshold を超える。
- score lineage が source event と一致しない。
- old checkpoint または `simple_bfts` identity regression。
- critical journey/a11y/performance hard gate failure。

## Rollback plan

- 旧 static bundle と legacy route adapter を最低 1 minor 保持する。
- feature flag で shell/workspace 単位に戻す。
- canonical write は legacy reader が読める export/backup を維持する。
- additive artifact/read-model は無視可能で、checkpoint downgrade を要求しない。
- rollback drill で running run、draft、settings、workflow、RQGM view の data loss がないことを確認する。
- security incident は flag rollback だけでなく remote bind/session revoke/process stop 手順を持つ。

## Documentation transfer

- Tutorial: `docs/getting-started/quickstart.md`。
- How-to: Dashboard、Configuration Studio、RQGM GUI、HPC/remote operation guide。
- Concepts: application architecture、configuration resolution、research/governance state model。
- Reference: `docs/reference/configuration.md`、`docs/reference/rest_api.md`、RQGM artifact/event/schema。
- Migration: `docs/guides/migration.md` と release notes。
- English/Japanese/Chinese を同一変更で更新し、`last_verified` を同期する。

## Completion criteria

- target branch の frontend/backend/contract test が hard CI で green である。
- 全 compatibility/security/a11y/performance gate が release artifact に記録される。
- default-on 後の観測期間と rollback drill を完了する。
- legacy removal が usage と release policy に基づいて行われる。
- 恒久文書と三言語 guide が実装に同期している。

## Deletion criteria

- G6 完了、rollback window 終了、legacy removal/retention decision 完了、全知識の恒久文書移管後に削除する。

## Delete-after checklist

- [ ] 全 task が `verified` である。
- [ ] default-on と最低 1 minor の rollback window を完了した。
- [ ] release/security/performance evidence を保存した。
- [ ] legacy removal または明示 retention ADR を完了した。
- [ ] 三言語の恒久文書と migration note を公開した。
- [ ] main merge と CI green を確認した。
- [ ] `INDEX.md` を更新した。
