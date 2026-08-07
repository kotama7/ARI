# G0 Review Record

> Status: active working doc  
> Created: 2026-07-23  
> Owner: GUI refresh program  
> 移管先: docs/reference|concepts at G6

## 目的

Wave 0（G0 — Contract freeze）の検証結果を記録する。plan 10 の「Baseline observation」（2026-07-22 時点: frontend `43 passed / 2 failed / 2 todo`、typecheck 11 error、backend `398 passed / 1 failed / 8 skipped`）を分類・解消した後の green baseline を、契約 freeze の起点として固定する。

## 検証環境

- 日付: 2026-07-23
- branch: RQGM worktree（uncommitted 変更を含む）
- 対象: `ari-core/ari/viz/frontend`（npm toolchain）、`ari-core/tests` の viz 関連 subset

## Frontend hard gate — green 達成

| Gate | Before | After | Fix |
|---|---|---|---|
| `npm run typecheck` (tsc) | 11 errors | **0** | tsconfig include に `vitest.setup.ts` を追加（jest-dom/vitest の type augmentation を有効化） |
| `npm test` | 43 passed / 2 failed / 2 todo | **45 passed / 0 failed / 2 todo** | PaperBench tests の曖昧な `getByDisplayValue` を label-based query へ置換。`pbGet` の assertion を `{method:'GET'}` に更新。`global` → `globalThis` |
| `npm run build` | — | **green** | — |

**全修正は test-side only、component 変更ゼロ。** つまり plan 10 の分類でいう「uncommitted worktree による drift」ではなく test 資産側の defect であり、既存 frontend の runtime 挙動は baseline としてそのまま freeze できる。

### Bundle baseline（`npm run build` 出力）

| Chunk | Size | gzip |
|---|---|---|
| index | 199.77 kB | 69.91 kB |
| WorkflowPage | 128.13 kB | 39.53 kB |
| ResultsPage | 63.39 kB | 17.00 kB |

plan 09 の performance budget（route chunk ≤ baseline+10% during migration、最終 ≤ 150 KiB gzip 等）は本表を基準に ratchet する。

## Backend baseline

- viz 関連 subset: **929 passed / 7 skipped / 1 xfailed**（22.95s）。
- full-suite run: **4008 passed / 16 skipped / 2 xfailed**（190.80s、2026-07-23、`python -m pytest tests/ -q --ignore=tests/skills`、Python toolchain は現 worktree 固定。green baseline 成立）。

## G0 fixtures — 既存契約固定資産の採用

新規に golden fixture を発明せず、以下の既存資産を G0 fixture として採用する。

| 資産 | 役割 |
|---|---|
| `tests/fixtures/contracts/viz_endpoints.json`（+ `cli_tree` / `public_api` / `mcp_tools`） | API method/path/契約 snapshot |
| `scripts/snapshot_contracts.py` | snapshot 再生成の正本 |
| `scripts/check_viz_api_schema.py` allowlist | 72 行。既知 drift F6a（FE が `POST /api/paperbench/run/{id}/report` を呼ぶが backend に POST branch なし）を含む frozen baseline |
| `scripts/check_dashboard_ux.py` allowlist | dashboard UX baseline（増加禁止・減少のみ） |
| frontend `SettingsContract.test.tsx` | Settings 24-key POST 契約 |
| i18n parity test | 三言語 key parity |

## Known mismatch classification

plan 10 Wave 0 の要求（互換対象か修正対象かの分類）に対する確定表。

| Mismatch | 分類 | 処置 |
|---|---|---|
| F6a: FE `POST /api/paperbench/run/{id}/report` に backend POST branch なし | **解消 (Wave 4a)** | routes.py do_POST に `/report` branch を追加し既存 `_api_run_report`（契約は「POST body or URL query」）へ委譲。GET variant は parity 用に存続、allowlist の F6a entry は削除済み |
| Settings GET/POST 非対称（24-key POST / 27-key GET） | **互換対象（legacy contract として freeze）** | 新 fixture `test_gui_baseline_settings_contract.py` で固定 |
| `_status` を 200 body に埋める応答 | **互換対象** | legacy endpoint のみ freeze。`/api/v1` では再現しない |
| `settings.json` whole-file replace + `letta_api_key` 平文 + api-key「20 文字以上」heuristic | **frozen defects** | fixture 化するが canonical API では再現禁止 |
| `temperature` / `container_pull` dead keys、retrieval 装飾のみ | **互換対象（frozen）** | 文書化し、schema registry では「未適用」と明示 |
| workflow editor が active checkpoint 不在時に同梱 `workflow.yaml` を無警告で書換 | **P0 修正対象** | Wave 2 序盤に guard を入れて先行修正（risk register RR-P0-1 参照） |
| Settings SLURM card は wizard の seed のみ | **互換対象（freeze）** | — |

## G0 exit 判定

| Exit 条件（plan 10 Wave 0） | 状態 |
|---|---|
| current route/Settings/API golden fixture 化 | 済（既存資産採用、上表） |
| known mismatch の分類 | 済（上表） |
| green baseline | frontend 済 / backend subset 済 / **full-suite 済（4008P/16S/2xf、2026-07-23）** |
| P0 security issue の解消または blocking issue 化 | risk register にて blocking gate 割当済（解消は Wave 2/3） |
| ADR 承認 | adr_backlog.md にて open 管理中（各 ADR は decision-by gate で確定） |

**G0 判定: 通過（2026-07-23）。** 契約 fixture は CI 収集対象の pytest（40 tests green）として再現可能、green baseline は両側成立、P0 は owner/blocking gate 付きで登録済み。ADR は backlog 管理とし、各 gate 到達時に個別確定する（G0 exit を block しない）。「主要画面の fixture」のうち visual/screenshot baseline は plan 10 の Wave 1 exit（route/visual/a11y/i18n baseline 固定）に割当てられているため、本 record では component-level DOM fixture（既存 frontend tests）までを G0 範囲とする。

## Wave 1 exit record（2026-07-23）

Wave 1（design tokens / route registry / capabilities / baseline 固定）の検証済み deliverable と exit 判定。

### Deliverables（検証済み）

| 領域 | 内容 |
|---|---|
| Design tokens | semantic token layer + `motion.css`（`prefers-reduced-motion` 対応）。既存 style への additive 変更のみ |
| 劣化表示 component | `DegradedState` / `StaleDataBanner` + i18n 6 keys × 3 辞書（EN/JA/ZH parity 維持） |
| Route registry | `src/app/routeRegistry.ts`（**13 routes frozen**、10-entry nav parity）。`App.tsx` / `Sidebar` が registry を消費し、dead な重複 table は削除済み |
| Capabilities | `GET /api/capabilities` + `ARI_GUI_V2` kill-switch（default ON）+ 空の `V2_ONLY_ROUTES` gate（ADR-07 の実装起点） |
| a11y ratchet | axe-core baseline を frozen で固定: violation `['region','select-name']` + h1 なし 4 routes（task 02 の remediation list として登録） |
| Route render baseline | nav 10 routes 全てに対する render baseline test |

### Final gates

| Gate | 結果 |
|---|---|
| `npm run typecheck` (tsc) | **0 errors** |
| `npm test` | **75 passed / 2 todo** |
| `npm run build` | green |
| main bundle | **70.52 KiB gzip**（G0 baseline 69.91 比 **+0.61**、budget +2 以内） |
| backend contract tests | green（**22 passed**、新規 capabilities test を含む） |
| `viz_endpoints.json` | additive に再生成（`+/api/capabilities` のみ） |

### 補足

- pixel-level visual regression（Playwright）は plan 10 の hard-gate list に従い **Wave 4/5 へ意図的に deferral**。Wave 1 の visual baseline は DOM/a11y ratchet（route render baseline + axe-core frozen baseline）が担う。
- route baseline 作成中に MonitorPage の partial payload crash を発見（risk register **RR-D-1** に登録。Wave 1 exit は block しない）。

**Wave 1 exit 判定: 通過（2026-07-23）。**

## Wave 2 exit record（2026-07-23）

Wave 2a（API platform）+ 2b（frontend platform / SSE / vertical slice）の検証済み deliverable と exit 判定。

### Deliverables（検証済み）

| 領域 | 内容 |
|---|---|
| RR-P0-1 是正 | workflow 書込み 4 endpoint の共有 guard（no-checkpoint → 400、副作用ゼロ）+ **copy-on-write seeding**（copy 欠落時は同梱から seed して copy のみ編集。同梱 workflow.yaml は GUI から書込み不能）。16 tests + MN-1 |
| `/api/v1` platform | `ari/viz/v1/`: 宣言的 router、typed error envelope（`code/message/details/request_id/retryable`）、pydantic DTO（`schema_version:1`）、read-only 5 endpoint、決定論的 OpenAPI 3.1 + drift guard、GET 副作用ゼロ保証 |
| SSE | `GET /api/v1/events/stream`（event bus ring buffer 1000、`Last-Event-ID` replay、15s heartbeat、run_id/topic filter）。watcher/switch-checkpoint に lazy hook（simple_bfts 経路は v1 を import しない） |
| Frontend platform | @tanstack/react-query 5.101.4（ADR-01）、openapi-typescript 7.13.0 生成型 + byte-equality drift test、typed v1 client（error envelope 正規化）、run/project ID を含む query key |
| Projects slice | 初の v2 workspace（`#/projects`、`V2_ONLY_ROUTES` + guiV2 nav gating、semantic tokens/common components のみで構成、RQGM capability chip、legacy handoff は TODO 付き暫定） |
| Realtime client | EventSource wrapper（backoff 1s→30s、`Last-Event-ID`、offline 時のみ bounded 10s polling fallback）+ query invalidation（run 単位隔離）+ StaleDataBanner 採用 |
| env 契約 | `ARI_GUI_V2` を `scripts/setup/setup_env.sh` に記載（env 同期テスト green） |

### Final gates

| Gate | 結果 |
|---|---|
| backend full suite | **4097 passed / 16 skipped / 2 xfailed**（gui_refresh 起因の失敗 0） |
| `npm run typecheck` | 0 errors |
| `npm test` | **97 passed / 2 todo** |
| `npm run build` | green。main **79.82 KiB gzip**（react-query 採用 +9.3、ADR-01 想定内。plan 09 最終 budget 100 KiB 以下を維持） |
| checkers | `check_viz_api_schema` exit 0（known 23 / new 0）、`snapshot_contracts --check` 同期、directory policy green |

### plan 10 Wave 2 exit 条件

- two-run isolation: **TESTED**（query key 隔離 + ProjectsPage 二 run テスト + event 隔離テスト）
- SSE reconnect: **TESTED**（`Last-Event-ID` resume、backoff、fallback）
- legacy rollback: `ARI_GUI_V2` kill-switch で v2 route/nav が消え、legacy 画面は無変更のまま動作（gui_v2-off テストで gating 検証）

### 補足

- 検証中に検出した無関係の失敗 1 件: `ari/public/claim_gate.py` の意図的 re-export（`FORMULAS`/`required_roles`、RQGM branch 作業）に対し `public_api.json` snapshot が未再生成 → 所定手順（`snapshot_contracts.py --surface public --update`）で解消。gui_refresh の変更は `ari/public/` に触れていない。

**Wave 2 exit 判定: 通過（2026-07-23）。**

## Wave 3a exit record（2026-07-23）

Wave 3a（configuration control plane 前半: field registry / config schema API / resolver / secret readiness）の検証済み deliverable と exit 判定。

### Deliverables（検証済み）

| 領域 | 内容 |
|---|---|
| Field registry | `ari/config/field_registry.py`（`walk_config_leaves` + `FIELD_META` overlay + `build_field_registry` + `get_uncovered`）。ARIConfig の **144/144 leaf をカバー（100%）**、coverage invariant は runtime の `LookupError` で強制（新 leaf 追加時に meta 未整備なら即失敗）。`ENV_OVERRIDES` は `apply_*_env_overrides` から転記した **20 の `ARI_*` family** を対応付け |
| Config schema API | `GET /api/v1/config/schema` → `{schema_version: 1, resolver_version: "legacy-compatible-1", fields: [144]}`。唯一の `secret_reference` field（`llm.api_key`）は `default` を `None` に強制した metadata-only（value/default channel を構造的に閉鎖） |
| Resolver | `ari/config/resolver.py`（`RESOLVER_VERSION = "legacy-compatible-1"`）+ `GET /api/v1/runs/{run_id}/resolved-config`: per-leaf **provenance**（`source`/`mutable`/`confidence`）+ manifest **digest** + warnings。`secret_reference` leaf は values/provenance/digest 入力から完全除外。**golden parity guard**（`test_golden_parity_with_legacy_chain`）が実 legacy chain（config.yaml → workflow.yaml → env）との一致を固定 |
| Secret readiness API（RR-P0-2 是正） | `GET /api/v1/secrets/status`（`ari/viz/v1/secrets.py`、SECRET_NAMES allowlist 8 name）→ `{name, configured, source_class ∈ project_env\|repo_env\|user_env\|process_env\|null, last_updated}`。`SecretV1` DTO に value field なし（**leak が構造的に不可能**） |
| Legacy env-keys 閉鎖 | `GET /api/env-keys` を value redaction（非空 → `***configured***`、空 → `''`、top-level `redacted: true`）の shape 互換 adapter 化。`POST /api/env-keys` は name allowlist `^[A-Z][A-Z0-9_]{0,63}$` fullmatch + 制御文字 reject → 400 no-write |
| Frontend | `fetchSecretsStatus()`（typed、`services/api/settings.ts`）。`StepResources` dev-mode Auto-read は readiness message（`configured (source_class) — leave blank to use it` / `not configured — enter manually`）のみ表示し、**field prefill を廃止**（`setApiKey` 経路撤去、MN-2 の UX 移行） |
| ガバナンス文書 | **ADR-11 accepted**（`adr/ADR-11.md`）、risk register **RR-P0-2 closed（Wave 3a）**、migration note **MN-2** 起票。negative test: `tests/test_gui_secret_readiness.py`（fake `sk-` value が serialized payload に不在であることを直接 assert） |

### Final gates

| Gate | 結果 |
|---|---|
| backend full suite | **4164 passed / 16 skipped / 2 xfailed**（failed 0）。初回 run の `test_dashboard_html` 2 fail は並行 `npm run build` の `static/dist` 書換え干渉と特定（単独再走 + クリーン full 再走で green） |
| 対象 3 suite | `test_gui_secret_readiness.py` + `test_gui_config_field_registry.py` + `test_gui_config_resolver.py` = **62 passed** |
| `npm run typecheck` | 0 errors |
| `npm test` | **97 passed / 2 todo** |
| `npm run build` | green |
| `python -m ari.viz.v1.openapi --check` | in sync |
| checkers | `snapshot_contracts --check` 同期（public/cli/mcp/viz）、`check_viz_api_schema` exit 0（new 0）、directory policy green、`check_import_boundaries` exit 0（known のみ） |

### plan 10 Wave 3 exit 条件との対応

- config coverage 100%: **達成**（144/144 + runtime invariant）
- secret leakage 0: **達成**（readiness API + redaction + 構造的 no-value DTO + negative test）
- precedence parity: **resolver 側は達成**（golden parity guard）。ただし precedence matrix golden tests の全面展開は 3b
- **G3 は open のまま**。Wave 3b 残 scope: project/template PATCH API、durable run draft、Configuration Studio UI、precedence matrix golden tests

**Wave 3a exit 判定: 通過（2026-07-23）。G3 gate は Wave 3b 完了まで open。**

## Wave 3b exit record / G3 判定（2026-07-23）

### Deliverables（検証済み）

| 領域 | 内容 |
|---|---|
| Document store | `gui_store/`（workspace-scoped、atomic write + revision 楽観ロック、0o600/0o700、ADR-12）。35 tests。CLI は一切読まない |
| Config CRUD API | project config GET/PATCH、run-templates CRUD、run-drafts（If-Match 必須、`revision_conflict`/`already_exists` frozen envelope、`validate_patch` の 6 分類 closed vocabulary）。10 endpoint、55 tests |
| Resolver preview | `resolve_new_run_config`（defaults→workflow→profile 実 4-key merge 忠実→project→template→draft→env、rejected_override 説明付き、interlock warn+fallback parity）+ draft `resolve-config`/`validate` endpoint |
| Precedence goldens | `test_gui_config_precedence_matrix.py` **34 tests**（各層単独/隣接優先/profile 非 merge 警告/型 reject 保持/interlock/resume 不変） |
| Legacy shadow diff | `test_gui_config_shadow_legacy.py` **28 tests** — legacy 24-key save+launch chain vs canonical resolver の per-leaf 等価（既知乖離は明示 allowlist、G0 表参照） |
| Config browser | 読み取り専用 `#/config?run=`（v2 route、category 群/検索/provenance・confidence・mutability バッジ/warnings/secret は reference 表示のみ）+ Projects からの Config link |
| RR-P0-4 完全是正 | Wave 3a の allowlist/redaction に加え、`.env` upsert を atomic + 0o600 化（`TestUpsertEnvKeyHardening` 2 tests） |

### Final gates（Wave 3b verify 実測 + hardening 後の再実行）

| Gate | 結果 |
|---|---|
| backend full suite | **4334 passed / 16 skipped / 2 xfailed**（hardening 後の対象 suite 再実行 125+23 passed） |
| frontend | typecheck 0 / **102 passed + 2 todo** / build green、main **80.61 KiB gzip**（budget 100 以内） |
| checkers | viz api schema / snapshot（public,cli,mcp,viz）/ directory policy / import boundaries / openapi --check 全 green |
| G3 evidence 群 | precedence 34 + shadow 28 + CRUD 55 + store 35 + legacy Settings 19 + resolver/registry/secret 62 = **233 passed** |

### G3 gate-review disposition（4 open 項目の処置）

verify agent が指摘した G3-bound open 4 件を次のとおり処置した:

1. **ADR-04**: accepted（in-code registry + 二軸 versioning の正式化。clerical backfill） 
2. **ADR-05**: provider 部分 accepted（.env chain + readiness + hardened POST。canonical `PUT /secrets/{id}` と `catalogs/models` は **Wave 4 の Configuration Studio へ明示割当**）。auth は open のまま G5 
3. **RR-P0-4**: closed（allowlist/制御文字/redaction/atomic/0o600 の全項是正。heuristic は frozen defect として別管理） 
4. **RR-PR-1**: accepted（control 改訂: 三重テストで等価性 pin。CLI 統合は target resolver version bump へ繰り延べ — plan 05 の段階設計と整合）

### plan 10 Wave 3 exit 条件

- config coverage 100%: **達成**（144/144 + runtime invariant）
- secret leakage 0: **達成**（RR-P0-2/RR-P0-4 closed + negative tests）
- precedence parity: **達成**（golden parity + precedence matrix + shadow diff）
- legacy Settings adapter: **green**（19 tests）

**G3 判定: 通過（2026-07-23）。** Studio UI 編集・Wizard 置換・raw YAML editor・`PUT /secrets/{id}`・`catalogs/models` は plan 10 の Wave 4 scope として割当済み。

## Wave 4a exit record（2026-07-24）

### Deliverables（検証済み）

| 領域 | 内容 |
|---|---|
| RQGM fixture 工場 | `rqgm_fixture_factory.py` — schema-valid かつ hash-chained な合成 RQGM checkpoint（founding 登録 + epoch boundary + T6/T20 + erasure/rebuild + 4-record 対審 chain + UtilityRecord + node sentinels）。実装の `EpochState`/`seal_utility_policy`/`apply_registry_event` を直接使い replay 一致を保証。21 tests、corrupt 3 modes |
| RQGM read models | `viz/v1/rqgm.py`（**`ari.rqgm` を import しない** pure reader、hash12 契約は parity test で pin）。8 read-only endpoint: capabilities / overview / registry / transitions / audit / nodes/{id}/lineage / score-rewrites / policies。committed-only、byte-offset cursor、破損は 500 でなく integrity flags + degraded_reasons。29 tests |
| 二チャネル score lineage | penalty channel（sentinel + `UtilityRecord`、raw attack は構造的に score を持てない `kind:'raw'`）と policy channel（`_utility_policy_hash` stamp + erasure/rebuild refs）を DTO レベルで分離 |
| Governance workspace | `#/governance?run=`（v2、5 tabs: Overview/Registry/Accountability/Score Lineage/Audit、tablist a11y、registry 10 状態は専用 token で node score 5 状態と色彙分離、policy hash 跨ぎの連続系列を facet で禁止、inert chain の capability note）。i18n ~140 keys × 3 |
| F6a 解消 | `POST /api/paperbench/run/{id}/report` branch 追加（同一 handler 委譲、GET 存続）。allowlist から F6a 削除、G0 表更新 |
| i18n gate 適合 | Governance コメント内の CJK 引用 7 箇所を英語化（既存 `test_react_components_no_hardcoded_cjk` gate 適合） |

### Final gates（CJK 修正後の再実行）

| Gate | 結果 |
|---|---|
| backend full suite | **4399 passed / 16 skipped / 2 xfailed**（208.69s） |
| frontend | typecheck 0 / **112 passed + 2 todo**（21 files）/ build green、main **85.84 KiB gzip**（budget 100 以内） |
| checkers | viz api schema（F6a 消滅、new 0）/ snapshot 4 surface 同期 / directory policy / import boundaries / openapi --check 全 green |

### 発見した上流（RQGM 実装側）の schema 齟齬 — gui_refresh の scope 外、要修正

- `epoch_transition.schema.json` の `rule_id` pattern `^T([1-9]|1[0-9])$` が **T20/T21 を弾く**（Task 14/15 で追加された edge が schema に未反映）
- `rqgm_attack_records.schema.json` の `adversary_type` enum に **`paper_self_preference` が無い**（8 番目の adversary が未反映）

（risk register RR-D-2 として登録。fixture はこの 2 点を回避して構築済み）

**Wave 4a exit 判定: 通過（2026-07-24）。** 残 Wave 4 scope: Configuration Studio/Wizard 置換（governance step は ADR-09 回答待ち）、Monitor/Tree/Ideas/Results/Workflow 移行、Epoch Timeline/Evolution/Paper Archive tabs、run-explicit URL。G4 は open。

## Wave 4b exit record（2026-07-24）

Wave 4b（task 07 Overview workspace + task 08 RQGM read model 完結）の検証済み deliverable と exit 判定。

### Deliverables（検証済み）

| 領域 | 内容 |
|---|---|
| Run Overview workspace（task 07） | `#/overview?run=`（v2、`gui_v2` capability gate、read-only）。plan 07 の P1/P2 disclosure layer のみ実装: P1 = lifecycle badge / research phase（idle→starting→bfts→paper→review の frozen vocabulary）/ last-update freshness / blocker surface（RQGM run では plan-08 overview read model の degraded・integrity flag を昇格）。P2 = run summary DTO の StatBoxes + workspace deep links（Tree / `#/config?run=` / RQGM 時 `#/governance?run=`）。research phase と governance stage は**別行表示で不融合**。realtime は `useRunEvents`（topics `run`+`tree`）、stream 断は `StaleDataBanner` であり「run stopped」とは表示しない。route registry は **17 routes**（`overview` 追加） |
| RR-D-1 是正 | `MonitorPage.tsx` の resource-metrics 全数値 field を defensive access 化（`isFiniteNumber` guard + placeholder。crash 修正のみで挙動変更なし）。negative test `Monitor/__tests__/MonitorPage.test.tsx`（partial payload regression）。mock-level workaround は撤去 — `routeRenderBaseline` / `shellA11yBaseline` の resource-metrics mock は意図的に partial payload を返す。risk register **RR-D-1 closed（Wave 4b）** |
| RQGM read model 完結（task 08） | 残 3 family を viz/v1 に実装（server-only、GET-only、**`ari.rqgm` 非 import を維持**）: `/api/v1/runs/{run_id}/rqgm/epochs`・`.../epochs/{epoch_id}`・`.../evolution`・`.../paper-archive` の **4 route** + **11 DTO**。`rqgm.py` は 1335 → **1927 行**（Wave 4a の `_load_transitions`/`_load_audit`/`_scan_jsonl`/`_policy_body` を再利用） |
| Truth rules（epochs） | epoch は committed replay のみから導出。各 epoch 行が自分の `utility_policy_hash` を持つ（FE は naive な cross-epoch 比較を拒否できる）。open epoch は `transition_counts=None`、`fallbacks` は実 `epoch_transition` audit record が配列を供給しない限り None（**欠落 source を 0 として描画しない**） |
| Truth rules（evolution） | `adopted` は proposed hash を committed registry replay に join した場合のみ導出（`adopted_via` が transition を引用）。raw candidate / validated candidate（`validation_record_count`）/ adopted policy は構造的に分離。meta outputs は `adopted=None`（inert provenance） |
| Truth rules（paper-archive） | bounded scalar + 明示 absent flag: archive file 不在 → `draft_count=None`、frozen `paper_utility_policy` 不在 → `anchor.enabled=None`、state 不在 → `paper_mode="linear"` **かつ** `state_present=false` |
| Governance tab set 完結 | `#/governance?run=` は **8 tabs**（Wave 4a の 5 + Epoch Timeline / Evolution / Paper Archive）。task 08 の tab scope はこれで完了 |
| Fixture 工場拡張 | `rqgm_fixture_factory.py` に `with_evolution`（default True）/ `with_paper`（default False）。`prompt_evolution.jsonl`（未登録 raw candidate + 実 `UtilityPolicyCandidate` + validation record）、`rqgm_meta_outputs.jsonl`（content-derived `meta_out_<hash12>`、production parity）、paper 層は `paper_archive_state.json`（sealed hash12 + 実 `corpus_digest`）+ `paper_draft_archive.jsonl`（4 records、`is_best_belief` は厳密に 1、`tex_sha256` は各 `tex_path` の bytes と一致） |
| OpenAPI / 生成型 | 4 paths + 11 schemas 追加（`--update` 後 `--check` green）。`v1types.gen.ts` 再生成（CJK 0） |

### Final gates（本 record 作成時の再実測）

| Gate | 結果 |
|---|---|
| backend full suite | **4418 passed / 16 skipped / 2 xfailed**（208.37s、failed 0） |
| RQGM GUI suites | `test_gui_rqgm_fixtures.py` 28 + `test_gui_v1_rqgm.py` 41 = **69 passed** |
| `npm run typecheck` | 0 errors |
| `npm test` | **128 passed + 2 todo**（23 files） |
| `npm run build` | green。main **93.55 KiB gzip**（4a 比 +7.71、budget 100 以内） |
| checkers | `check_viz_api_schema` exit 0（new 0、known のみ）/ `snapshot_contracts --check` 4 surface 同期 / directory policy green / `check_import_boundaries` exit 0（known のみ）/ `python -m ari.viz.v1.openapi --check` in sync |
| CJK gate | `test_i18n_consistency.py` **9 passed** |

**Wave 4b exit 判定: 通過（2026-07-24）。** task 08 の Governance tab set は 8 tabs で完結、RR-D-1 は closed。残 Wave 4 scope: Configuration Studio/Wizard 置換（governance step は ADR-09 回答待ち）、Tree/Ideas/Results/Workflow 移行、PaperBench durable jobs、run-explicit URL 完全化。G4 は open。

## Wave 4c exit record（2026-07-24）

Wave 4c（PaperBench durable jobs + `GET /api/v1/runs/{run_id}/idea` + Tree/Ideas v2 workspace 移行）の検証済み deliverable と exit 判定。

### Deliverables（検証済み）

| 領域 | 内容 |
|---|---|
| Durable PaperBench jobs | `api_paperbench.py` — `_JOBS` の全 mutation（`_new_job` での生成、`_set_job_field` の stage/progress/completion/failure 更新）を `{paper_registry_root}/jobs/{job_id}.json` に atomic に mirror（tmp + `os.replace`、file `0o600` / dir `0o700`、best-effort で in-memory hot path は決して壊さない）。restart 後の GET reader は memory 不在時に disk へ fallback し、persisted な queued/running record を **additive status `"interrupted"`** として報告（read-only rehydration — worker 再 spawn なし・write-back なし、job-id 文法 `^[A-Za-z0-9_-]{1,64}$` で traversal 遮断）。保存先は papers/<pid>/runs/<job_id> sandbox と同居する `{paper_registry_root}/jobs`（gui_store は ADR-12 の user-config 専用 — `_jobs_dir` docstring に根拠明記） |
| Run idea read model | `GET /api/v1/runs/{run_id}/idea` — `RunIdeaV1` DTO + `queries.get_run_idea`（`idea.json` の pure read）。legacy IdeaPage が `/state` から読む key（`ideas` passthrough / `gap_analysis` / `primary_metric` / `metric_rationale`）を mirror。file 不在 → `present=false` + None default（**空文字列を捏造しない** — legacy は `""` を返す）、malformed → 200 + `degraded_reasons`、unknown run → typed 404。router / openapi / snapshot / allowlist note / `gen:v1types` まで配線済み |
| TreeV2 workspace | `#/tree2?run=&node=`（route id `tree_v2`）。typed `useRunTreeV1` 上の run-explicit tree。legacy D3 `TreeVisualization` は **import 再利用（fork しない）**。`?node=` の shareable URL selection、右 inspector（frozen status/label vocabulary、`_scientific_score` + RQGM sentinels `_pre_penalty_score`/`_validated_attack_penalty`/`_utility_policy_hash` chip/`_stale`、node report、Governance/Config deep link）、realtime は topic `tree` + `StaleDataBanner`（stream 断 ≠ run stopped） |
| IdeasV2 workspace | `#/ideas2?run=`（route id `ideas_v2`）。idea endpoint + tree endpoint（共有 `treeNodes` coercion）で legacy `#/idea` と情報 parity（research goal は `state.checkpoint_id === ?run=` の run-identity gate 付き）。absent（`EmptyState`）と corruption（`DegradedState`）を**混同しない**。best hypothesis と各 node から `#/tree2` へ deep link |
| navReplaces 機構 | `routeRegistry.ts` に `navReplaces` field 追加: `gui_v2` capability on の間、v2 route が対象 route の sidebar slot を乗っ取り navLabelKey を継承（`tree_v2`→`tree`、`ideas_v2`→`idea`）。legacy `#/tree` `#/idea` は両モードで**登録・到達可能なまま無変更**（parity invariant）。route registry は **19 routes**（4b の 17 + 2） |

### 宣言済み deviations

- `routes.py` の SSE terminal-status tuple に `"interrupted"` を追加（additive。dead-job stream の 5 分 heartbeat stall を防止）
- `append_job_log` 単独は persistence trigger にしない（per-line 書換は job あたり ~2000 回。record の logs は最終 status mutation 時点 — docstring に明記）
- scripts/tests の viz LOC tripwire を **14336 → 14554** に理由付きで更新（tripwire 自身の指示に従う）
- `check_viz_api_schema` allowlist note は既存 `GET /api/v1/{id}` エントリの note 拡張のみ（新規 id なし。dashboard-UX allowlist は無変更）

### Final gates（本 record 作成時の再実測）

| Gate | 結果 |
|---|---|
| backend full suite | **4431 passed / 16 skipped / 2 xfailed**（209.83s、failed 0。4b 比 +13 = durable-jobs 8 + idea 5） |
| scripts/tests | **94 passed**（LOC tripwire 更新込み） |
| `npm run typecheck` | 0 errors |
| `npm test` | **158 passed + 2 todo**（25 files。TreeV2Page 11 / IdeasV2Page 11 を含む） |
| `npm run build` | green。main **98.26 KiB gzip**（4b 比 +4.71、budget 100 以内） |
| checkers | `check_viz_api_schema` exit 0（new 0、known のみ）/ `snapshot_contracts --check` 4 surface 同期 / `check_dashboard_ux` green（known のみ）/ directory policy green / `check_import_boundaries` exit 0（known のみ）/ `python -m ari.viz.v1.openapi --check` in sync |
| CJK gate | `test_i18n_consistency.py` **9 passed** |

**Wave 4c exit 判定: 通過（2026-07-24）。** simple_bfts・legacy `#/tree` `#/idea`・RQGM read-only は無変更のまま。残 Wave 4 scope: Results/EAR 移行、Workflow Studio、Configuration Studio/Wizard 置換（governance step は ADR-09 回答待ち）、PaperBench wizard slice。G4 は open。

## Wave 4d exit record（2026-07-24）

Wave 4d（bundle diet + Results/EAR v2 workspace + Workflow revision guard + Configuration Studio slice）の検証済み deliverable と exit 判定。

### Deliverables（検証済み）

| 領域 | 内容 |
|---|---|
| Bundle diet（plan 09） | i18n 辞書の**全 per-locale lazy 化**。main chunk **98.26 → 60.46 KiB gzip**（diet 単独 −37.8、plan 09 目標 −8 を大幅超過。4d の新 page 追加後の最終値は **60.70**）。dict は lazy chunk（最終値 en 12.65 / ja 15.19 / zh 14.16 KiB gzip）となり、default-ja startup = main + ja + en fallback = **88.54 KiB gzip**。`App.tsx` の新 `I18nProvider` ready-gate が shell render 前に active locale + en fallback を並列 fetch し、**`t()` は同期のまま**。`i18n/index.ts` は dynamic import loader + module cache（`ensureLocale`/`registerDicts`/`isLocaleReady`/`storedLang`）、`setLanguage` は cache 済なら同期・未 cache なら load-then-flip。`ari_lang` localStorage・default `'ja'`・flat key→string 契約は不変、dict file 自体は無変更。テストは `vitest.setup.ts` の `registerDicts` preload で全同期実行 |
| Results/EAR v2 read models（task 07） | `ari/viz/v1/results.py` — 2 つの v1 read model。`GET /api/v1/runs/{run_id}/results` → `RunResultsV1`（paper: root と `paper/` を独立 probe した pdf/tex presence。review: report presence + overall/abstract/body score の legacy `score`\|`scores.*` fallback chain + decision/confidence/rubric_id + `score_dimensions` 由来 dimensions。ORS: chain presence + per-stage flags（rubric/replicator/seed/phase1/grade）+ verdict/summary/ors_score/raw_score/passed\|total_leaves/judge_model。EAR: present/curated=manifest.lock/published=publish_record.json/visibility + visibility_source/dry_run/promoted_at）。`GET /api/v1/runs/{run_id}/ear` → `RunEarV1`（bounded `ear/` listing: path/kind/size、**cap 500 + truncated flag**、file_count は全数。publish_yaml presence、curated manifest digest scalar 群、publish-record scalar 群）。pure read・honest absence（presence ≠ readability、parse failure → 200 + `degraded_reasons`、500 にしない）。ORS verdict は `ari.viz.ear._synth_repro_report_from_ors` を call-time import で **read-only 再利用**（`ear.py` 無変更） |
| ResultsV2 workspace（task 07） | `#/results2`（route id `results_v2`、`gui_v2` gate、read-only）。navReplaces で legacy `#/results` の sidebar slot を継承。legacy ResultsPage（full editor/PDF workspace と全 EAR mutation）は**両モードで無変更・到達可能**（parity invariant）。route registry は **21 routes**（4c の 19 + `studio` + `results_v2`） |
| Workflow revision guard（task 07、**MN-3**） | 2 秒 blind-overwrite autosave の廃止。`GET /api/workflow` に additive `revision`（配信 bytes の sha256[:12]）、4 write endpoint（`POST /api/workflow{,/flow,/skills,/disabled-tools}`）は OPTIONAL `base_revision` を受け stale なら **HTTP 409** + frozen payload で**何も書かない**（CoW seed も走らない）。`base_revision` 無しの legacy caller は従来 last-write-wins（additive opt-in）。WorkflowPage は save state machine（Unsaved/Saving/Saved/Conflict chip）+ conflict banner + 明示 Reload（未保存 local 編集破棄を明記、silent 再適用なし）。実装: `api_workflow.py`/`api_settings.py`/`services/api/workflow.ts`/`WorkflowPage.tsx`。migration note **MN-3** に告知済み |
| Configuration Studio slice（task 06、**ADR-05 完結**） | `#/studio`（route id `studio`、`gui_v2` gate）の `ConfigStudioPage` — read-only ConfigBrowser（Wave 3b）の編集拡張。`GET /api/v1/config/schema` の field registry が全 control を駆動（field list の hardcode なし。enum→select / bool→switch / int/float→number / str→text / secret_reference→SecretField / composite→disabled+理由）。PROJECT scope は `GET/PATCH /api/v1/projects/default/config`（If-Match 楽観並行、409→reload banner、400→`ValidationSummary`）、TEMPLATE/DRAFT scope は `?template=`/`?draft=`。**ADR-05 decision 4 の割当てを実装完了**: `PUT /api/v1/secrets/{secret_id}`（`viz/v1/secrets.py`、write-only、`SECRET_NAMES` allowlist 404/制御文字 400、hardened `_upsert_env_key` へ委譲、応答は readiness 行のみ — 値は構造的に返せない）+ `GET /api/v1/config/catalogs/models`（`viz/v1/catalogs.py`、`PROVIDER_ENV_KEYS ⊆ SECRET_NAMES`）。ADR-05 backlog row の provider 部分は完全 accepted（auth mode は decision 5 のとおり G5） |
| Governance step は未実装（**ADR-09 回答待ち**） | Studio の governance step（RQGM mode 選択）は本 slice で**意図的に未実装**: 「Execution mode」category と全 `rqgm.*` field は locked/disabled group + ADR-09-pending note として render（test が pin）。legacy `#/settings` は両モードで無変更・並行稼働 |

### 宣言済み deviations

- i18n parity test は dict を `../en|ja|zh` から直接 import（barrel 経由の re-export は dict を main へ再 inline するため。static default export は不変）
- `i18n/index.ts` から en/ja/zh named re-export を削除（唯一の consumer が parity test だった）
- backend `test_i18n_consistency.py` の 2 assertion が旧 static-import 文面を hardcode していたため dynamic-loader 形も受けるよう更新（invariant は維持、file 9/9 green）
- ORS verdict 合成は `ear.py` を修正せず `_synth_repro_report_from_ors` を call-time import で read-only 再利用
- legacy `POST /api/env-keys` の完全 facade 化（allowlist 限定 canonical PUT への契約変更）は task 06 の launch/cutover slice へ繰り延べ（ADR-05 追記に記録。両 write 経路は同一 `_upsert_env_key` writer を共有し分岐しない）

### Final gates（本 record 作成時の再実測）

| Gate | 結果 |
|---|---|
| backend full suite | **4481 passed / 16 skipped / 2 xfailed**（209.60s、failed 0。4c 比 +50 = results/EAR 15 + workflow revision 12 + secret PUT/catalogs 23） |
| scripts/tests | **94 passed** |
| `npm run typecheck` | 0 errors |
| `npm test` | **186 passed + 2 todo**（28 files。ResultsV2Page / WorkflowPage.revision / ConfigStudioPage の 3 file を追加） |
| `npm run build` | green。main **60.70 KiB gzip**（4c 比 **−37.56**、pre-diet 98.26 の 62%。budget 100 以内。default-ja startup 88.54） |
| checkers | `check_viz_api_schema` exit 0（new 0、known のみ）/ `snapshot_contracts --check` 4 surface 同期 / `check_dashboard_ux` green（known のみ）/ directory policy green / `check_import_boundaries` exit 0（known のみ）/ `python -m ari.viz.v1.openapi --check` in sync |
| CJK gate | `test_i18n_consistency.py` **9 passed** |

**Wave 4d exit 判定: 通過（2026-07-24）。** simple_bfts・legacy `#/results` `#/settings`・RQGM read-only は無変更のまま。MN-3 告知済み、ADR-05 は provider 部分完全 accepted、Studio governance step は ADR-09 回答待ちの locked group として明示。残 G4 scope: PaperBench wizard slice の polish、Wizard/launch 置換（task 06 後続 slice、immutable launch summary を含む）、plan 07 残 depth（large-tree LOD / keyboard tree navigation）。その後 G4 review。

## Wave 5a exit record（2026-07-24）

Wave 5a（task 09 P0 security hardening: bind+CORS / path+proxy 境界 / confirmation challenges / browser security headers = **MN-4..7**）の検証済み deliverable と exit 判定。

### Deliverables（検証済み）

| 領域 | 内容 |
|---|---|
| Bind + CORS（**MN-4**、RR-P0-3 partial） | HTTP/WS server の **loopback 既定 bind**: 純関数 `resolve_bind_hosts`（server.py）が `ARI_GUI_BIND` 未設定時 `127.0.0.1`+`::1` の両 loopback family を bind（localhost→::1 解決の distro も従来どおり）、`'::'`=旧 all-interfaces dual-stack / `'0.0.0.0'`=IPv4 wildcard / 単一 address override。WebSocket server（port+1）も同一 policy（IPv4-only OSError fallback 付き）。CORS は無条件 `ACAO:*` を **same-origin echo** に置換: `_origin_allowed`（routes.py、pure）が request `Origin` の host[:port] を `Host` header 一致 or loopback 形（`localhost`/`127.0.0.1`/`[::1]`:server port）でのみ許可し、echo + `Vary: Origin`、不一致は ACAO 省略（preflight は bare 204）。適用面: `_json` 全 JSON 応答・OPTIONS preflight（許可時は PUT/PATCH/DELETE + If-Match も広告）・SSE 3 系統（`/api/logs`、paperbench job logs、`/api/v1/events/stream`）・手動 binary 応答（`/memory/`、`/codefile`、paper.pdf/tex、file/raw）・`/api/ollama` proxy。歴史的 ACAO-less の `/state`・`GET /api/gpu-monitor` は不変。**Vite dev proxy 検証済み**（server-side 転送で backend に cross-origin Origin が届かないため wildcard 不要、dual-loopback bind でも解決可）。kill-switch `ARI_GUI_CORS_ANY=1`、ADR-07 docstring 宣言（server.py/routes.py） |
| Path 境界 + proxy gate（**MN-5**、RR-P0-5/RR-P0-7 close） | `GET /codefile` の緩い「`*/checkpoints/*` を含むだけ」判定を撤去し、pure `_codefile_resolve` が **resolved canonical path（symlink 解決済み）が active checkpoint dir または `checkpoint_finder._checkpoint_search_bases` の resolve 済み prefix 配下の regular file** の場合のみ配信（`..` は解決前拒否、symlink escape は resolve 比較で拒否、directory/missing 404。20MB cap・content-type 体系不変）。`/api/ollama/<path>` は **5-path allowlist**（`/api/tags`・`/api/show`・`/api/generate`・`/api/chat`・`/api/ps`）+ target gate（settings `ollama_host` / env `OLLAMA_HOST` の明示設定、または backend=`ollama` のみ localhost:11434 既定を維持）で、それ以外は **upstream 接続を開かず 403**（`_ollama_proxy_refusal`）。traversal 修正に kill-switch は**設けない**（純 security fix） |
| Confirmation challenges（**MN-6**、RR-P0-6/RR-P0-9 close） | 新設 `POST /api/v1/challenges`（`v1/challenges.py`）が action+target に bind した single-use grant `chg-<12hex>`（**60s monotonic TTL**・deque cap 100・`viz_access.jsonl` へ `challenge_*` 監査）を発行。`POST /api/delete-checkpoint`（path binding）・`POST /api/stop`（`stop-all`+`"*"`）・`POST /api/gpu-monitor` `action=stop` は有効な `challenge_id` 無しでは frozen `{ok:false}` + **HTTP 428** で拒否し破壊的処理を一切実行しない。frontend は two-step 化（challenge 取得 → server echo の target を impact preview 表示 → `challenge_id` 添付）、`gpuMonitorAction` の `confirmed: true` ハードコード撤去。kill-switch `ARI_GUI_CHALLENGES=0`。router/dto/openapi/`gen:v1types` 配線済み（endpoint 追加は本 1 件のみ） |
| Browser security headers + CDN 除去（**MN-7**、RR-P0-10 close） | `index.html` の CDN d3 `<script>` を削除し bundle 一本化（`window.d3` 利用 0 を grep 検証、再侵入 guard `indexHtmlNoExternalScripts.test.ts` 5 件）。SPA index + `/static/` に純関数 `_csp_policy` 由来の **CSP**（`default-src 'self'` 基調、connect-src に Host header 由来の ws/wss port+1 明示、`frame-ancestors 'none'`）+ `X-Content-Type-Options: nosniff` + `Referrer-Policy: no-referrer`（API/JSON 応答は対象外）。`dangerouslySetInnerHTML` は inventory 1 箇所（StepScope の local numeric summary）を JSX 化し **SPA から全廃**（sanitizer 依存の新規追加なし）。kill-switch `ARI_GUI_CSP=0`。残余: `style-src 'unsafe-inline'`（React inline style 全域のため許容、tracking 継続） |
| Ops/docs 同期 | migration notes **MN-4..7** 追記。`scripts/setup/setup_env.sh` に新 env 4 変数（`ARI_GUI_BIND`/`ARI_GUI_CORS_ANY`/`ARI_GUI_CHALLENGES`/`ARI_GUI_CSP`、各 kill-switch 注記付き）。`ari-core/tests/README.md` に新 test 4 file の行。viz LOC tripwire **15399 → 16143** を 4 段階（15595/15731/16043/16143 = MN-4/5/6/7）の理由付きで更新 |

### 宣言済み deviations

- CORS same-origin 化は task が名指しした 3 surface（`_json`/preflight/SSE）を超えて手動 binary 応答 + ollama proxy にも適用（「無条件 ACAO:* の置換」という趣旨に沿う宣言済み拡張）。`/state` と `GET /api/gpu-monitor` は指示どおり歴史的 ACAO-less のまま
- `/codefile` traversal 修正は rollback 手段を意図的に提供しない（MN-5 に明記。ollama gate の実質 rollback は target の明示設定そのもの）
- 既存 test の追随更新: `test_server.py` の OPTIONS 2 test を same-origin 方針へ、`test_ollama_gpu.py` の localhost 既定 test を backend=`ollama` 条件へ（invariant の更新であり削除ではない）
- `devModeAndDangerousOps.test.tsx` の dangerous-ops `it.todo` 1 件を MN-6 two-step の実 test へ変換（残 todo は ARIA-tabs invariant の 1 件のみ）

### Final gates（本 record 作成時の再実測）

| Gate | 結果 |
|---|---|
| backend full suite | **4603 passed / 16 skipped / 2 xfailed**（216.24s、failed 0。4d 比 +122 = 新規 security 4 file **115** + 既存 file の Wave 5a 追随分） |
| 新規 security negative tests（単独再実行） | `test_gui_bind_cors` **36** / `test_gui_path_proxy_hardening` **36** / `test_gui_confirmation_challenges` **26** / `test_gui_csp_headers` **17** = **115 passed** |
| scripts/tests | **94 passed**（LOC tripwire 16143 更新込み） |
| `npm run typecheck` | 0 errors |
| `npm test` | **191 passed + 1 todo**（29 files。`indexHtmlNoExternalScripts` 5 件追加 + dangerous-ops two-step 化） |
| `npm run build` | green。main **60.72 KiB gzip**（4d 比 +0.02、budget 100 以内） |
| checkers | 5 checker とも **exit 0 を明示確認**（`check_viz_api_schema` new 0 known のみ / `snapshot_contracts --check` 4 surface 同期 / `check_dashboard_ux` known のみ / directory policy green / `check_import_boundaries` known のみ）+ `python -m ari.viz.v1.openapi --check` in sync |
| env/CJK gate | `test_setup_env.py` + `test_i18n_consistency.py` **20 passed**（新 env 4 変数の宣言 test 含む） |

### Risk register 反映

- **closed（Wave 5a）**: RR-P0-5（codefile 境界）、RR-P0-6（rmtree/pkill challenge）、RR-P0-7（ollama reverse proxy）、RR-P0-9（client-side-only confirmation）、RR-P0-10（CDN d3 / unsafe HTML / CSP 不在）。
- **RR-P0-3 は partial**: bind+CORS sub-scope は是正済み（MN-4）だが authentication/session/CSRF sub-scope が未解決のため、row は **close せず annotate のみ**（open のまま。auth は ADR-05 decision 5 の G5 判断）。

### 残 G5 scope（task 09）

1. **auth/session 判断**（ADR-05 decision 5 の auth mode = RR-P0-3 の残余 sub-scope。loopback 既定 + opt-in remote を踏まえ、remote bind 時の認証要件を決定する）
2. **Performance budgets の formalization** — 判断: **CI-provable now** = bundle weight budget（`npm run build` 出力から headless に測定可能。現状は exit record への手動転記で、scripts checker 化に技術的障害はない）および静的 security invariant（CSP header test・CDN 再侵入 guard は既に CI 化済み）。**deferred（理由付き）** = LCP/INP 等の browser metric — jsdom の vitest では測定不能で real browser harness（Lighthouse/Playwright trace）が必要であり、共有 runner 上の headless 計測は分散が大きく pass/fail budget が flaky になるため、deployment profile smoke での手動計測記録（または専用 harness 導入）まで defer する
3. **Recovery/diagnostics endpoints**（`/health/live` | `/health/ready`）
4. **Deployment profile smoke docs**（loopback / SSH tunnel / `ARI_GUI_BIND` opt-in remote の各 profile 手順 + 4 kill-switch の matrix）

**Wave 5a exit 判定: 通過（2026-07-24）。** endpoint 追加は `POST /api/v1/challenges` のみ、削除なし。simple_bfts・legacy 画面・RQGM read-only は無変更のまま。全変更が env-only rollback（MN-4: `ARI_GUI_BIND='::'`+`ARI_GUI_CORS_ANY=1`、MN-6: `ARI_GUI_CHALLENGES=0`、MN-7: `ARI_GUI_CSP=0`）を持つ — 例外は `/codefile` traversal 修正（意図的に rollback なし）。G5 は残 scope 4 項目のため open。INDEX statuses は変更していない。

## Wave 5b exit record / G5 判定（2026-07-26）

Wave 5b（task 09 残 G5 scope の完遂: remote token auth **MN-8/ADR-13** + operational visibility **MN-9** + performance budget CI enforcement + ops/docs 同期）の検証済み deliverable と、task 09 の G5 line-by-line 判定。

### Deliverables（検証済み）

| 領域 | 内容 |
|---|---|
| Remote token auth（**MN-8**、**ADR-13** accepted、RR-P0-3 **close**） | remote bind（`ARI_GUI_BIND` 非 loopback）時のみ、`/health`・`/health/*` を除く全 HTTP request + WS handshake に `Authorization: Bearer <ARI_GUI_TOKEN>` を要求。新設 `ari/viz/auth.py`（純関数 `is_remote_bind`/`resolve_token`/`check_authorization`（`hmac.compare_digest`）/`redact_token_in_path` + token cache + ADR-07 register `ARI_GUI_AUTH=0`）、`routes.py` は 5 method handler 先頭の単一 `_auth_gate`（dispatch/body read 前。401 typed JSON + `WWW-Authenticate: Bearer`、token は応答にも log にも出ない — `viz_access.jsonl` は `token=***` redaction）、`websocket.py` の `_ws_process_request` handshake gate、`server.py` の起動時 `init_auth` + 未設定時 random 32-hex 生成 + stderr 一回 banner（**fail-secure — 無認証 remote 起動の経路なし**）。`EventSource` 消費 SSE と WS は query `token` 受理（tradeoff は ADR-13 に記録）。frontend は localStorage `ari_gui_token` 由来の `Authorization`/`token=` 付与（`client.ts`/`eventStream.ts`/`useWebSocket.ts`/`ResultsView.tsx`/`MonitorPage.tsx`）。**loopback 既定は無認証のまま byte-identical**（token 未設定時の request shape 不変）。CSRF は cookie 不使用のため surface なし（ADR-13）。session/multi-user は将来の multi-tenant ADR へ恒久 deferral |
| Operational visibility（**MN-9**、plan 09 §Operational visibility） | 新設 `ari/viz/health.py`: `GET /health/live`（依存ゼロ定数 probe）、`GET /health/ready`（http/websocket/watcher/event_bus/active_checkpoint の独立 check、例外は degrade — **readiness が 500 を返す経路なし**）、`GET /api/v1/diagnostics`（bounded scalars のみ: SSE subscribers/buffer/last_event_id、watcher alive/last_scan_age_s、tracked_runs 件数。**secret・filesystem path leakage ゼロ**）。`state_sync.py` watcher heartbeat、`events.py` subscriber counter、DTO/router/openapi 配線。kill-switch `ARI_GUI_HEALTH=0`。`/health/*` は auth 免除（probe 用）、diagnostics は remote mode で token 必須 |
| Performance budget CI enforcement（RR-PR-5 **partial**） | 新設 `scripts/check_bundle_budget.py` + `scripts/quality/check_bundle_budget.yaml`（entry ≤100 / route ≤150 / Settings・Wizard ≤50 / shared ≤150 / total ≤600 KiB gzip。決定的 gzip level 6、finding id は hash 非依存）+ `scripts/tests/test_check_bundle_budget.py`（fake-dist unit + real-dist smoke）+ quality report 登録。実測: entry 59.4 / total 261.0 KiB gzip、全 budget green。**browser metrics（LCP/INP/CLS）は G6 dogfood へ deferral** — jsdom で測定不能 + 共有 runner の headless 計測は flaky という理由と、固定環境 Lighthouse/Playwright の具体計測 protocol を `performance_budgets.md` に記録（server p95 系は plan 09 自身の「無条件の CI wall-clock 値にしない」に従い profile smoke の手動計測） |
| Ops/docs 同期 | `setup_env.sh` に `ARI_GUI_TOKEN`/`ARI_GUI_AUTH`/`ARI_GUI_HEALTH`（GUI env は計 8 変数の kill-switch matrix コメント）。`migration_notes.md` MN-8/MN-9（before/after/rollback）。`risk_register.md` RR-P0-3 close（bind+CORS 5a + auth 5b + CSRF non-surface の内訳付き）・RR-PR-5 partial 更新。`adr_backlog.md` ADR-13 行 + ADR-05 行の decision 5 解消注記。`performance_budgets.md` 新設。`tests/README.md` 追記。viz LOC tripwire **16143 → 16520 →（他 wave 挿入を挟み）16544 → 16921** を理由付きで更新 |

### Final gates（本 record 作成時の再実測、2026-07-26）

| Gate | 結果 |
|---|---|
| backend full suite | **4676 passed / 16 skipped / 2 xfailed**（216.16s、failed 0） |
| 新規 test（単独再実行） | `test_gui_remote_auth.py` **52** / `test_gui_health_diagnostics.py` **18** = **70 passed** |
| scripts/tests | **104 passed**（bundle budget checker tests +10 と LOC tripwire 16921 込み） |
| `npm run typecheck` | 0 errors |
| `npm test` | **191 passed + 1 todo**（29 files） |
| `npm run build` | green。main **60.86 KiB gzip**（Vite 表示系列。checker 系列では 59.4 — budget 100 以内） |
| `check_bundle_budget.py` | **exit 0、findings 0**（46 chunks、total 261.0 / 600 KiB gzip） |
| checkers | `check_viz_api_schema` exit 0（new 0、known のみ）/ `snapshot_contracts --check` 4 surface 同期 / `check_dashboard_ux` green（known のみ）/ directory policy green / `check_import_boundaries` exit 0（known のみ）/ `python -m ari.viz.v1.openapi --check` in sync |
| env/CJK gate | `test_setup_env.py` + `test_i18n_consistency.py` **20 passed** |

### G5 判定 — plan 09 §Completion criteria の逐条評価

| 基準 | 判定 | 根拠 / 残余 |
|---|---|---|
| default bind loopback、remote は authenticated/same-origin protected | **達成** | MN-4（loopback 既定 + same-origin CORS echo、36 tests）+ MN-8（remote Bearer token、fail-secure 生成、52 tests）。CSRF は cookie 不使用で構造的に非成立（ADR-13）。RR-P0-3 closed |
| secret value の browser response/log/storage/export 出現 0 件 | **達成** | RR-P0-2（Wave 3a readiness API + redaction）・RR-P0-4（Wave 3b allowlist + atomic 0o600）closed。Wave 5b: token は応答/ログ非出現（`token=***` redaction）、diagnostics は bounded scalars で secret/path ゼロ。注記: `ari_gui_token`（localStorage）は operator が自ら設定する client 側 credential であり server からの leakage ではない（ADR-13 記録済み tradeoff） |
| project/run/filesystem/process boundary が request-scoped で negative test を通る | **達成（条件付き）** | filesystem: RR-P0-5 closed（canonical resolve、traversal/symlink negative tests）。proxy: RR-P0-7 closed。process 破壊操作: challenge が action+target に bind。v1 API は project/run ID 明示（global invariant）。**残余: RR-P0-8（`viz/state.py` module-global active selection/process/settings state）は open** — owner tasks 03/04・blocking gate G2 で当 gate の blocking row ではないが、legacy 面の read/write が global active checkpoint に依存する状態は本基準の完全達成を妨げるため明記する |
| dangerous operation が server-issued challenge と audit を持つ | **達成** | Wave 5a MN-6（RR-P0-6/RR-P0-9 closed。single-use 60s challenge + `viz_access.jsonl` 監査 + two-step frontend、replay/expired/wrong-target negative tests） |
| performance budget と large-run fixture が CI/release gate で green | **達成（条件付き）** | bundle budget（entry/route/overrides/shared/total）は `check_bundle_budget.py` で CI enforce・全 green。静的 security invariant は Wave 5a で CI 化済み。**残余: LCP/INP/CLS は G6 dogfood へ理由付き deferral**（jsdom 測定不能 + 共有 runner flaky。固定環境計測 protocol は `performance_budgets.md`）。server p95 / 10k-node fixture 計測は plan 09 の明示方針（「無条件の CI wall-clock 値にしない」）に従い profile smoke の手動計測（G6 と併走）。RR-PR-5 は partial のまま open（G6 close 判定） |
| degraded/recovery 状態を GUI と operator guide から確認できる | **達成（条件付き）** | `/health/live`・`/health/ready`（per-subsystem degraded 表示、500 経路なし）+ `/api/v1/diagnostics`（MN-9、18 tests）。GUI 側は v1 read model の `degraded_reasons` + `DegradedState`/`StaleDataBanner` が degraded を正直表示。operator 手順は MN-8/MN-9 の user-impact 行 + `setup_env.sh` kill-switch matrix + ADR-13。**残余: deployment profile smoke 文書の一本化（loopback / SSH tunnel / opt-in remote + kill-switch matrix の統合 runbook）と recovery runbook の恒久文書化は G6（plan 10 docs 移管。plan 09 Deletion criteria の割当てどおり）** |

INDEX G5 exit condition（security、performance、a11y、i18n、recovery の budget 達成）の补遺 — **a11y**: axe frozen ratchet（violation `['region','select-name']`）+ per-route h1 baseline は shrink-only で CI 維持（v2 slice は全 route compliant で出荷）。**残余: legacy 4 route（paperbench/idea/workflow/settings）の h1 欠落 + shell landmark 2 violation は task 02 remediation list として open**（v2 移行で解消する設計。G5 は ratchet 維持を budget として判定）。**i18n**: 3-locale parity tests + CJK gate green（20 passed）。

### 残余一覧（条件付き通過の明記事項）

1. **RR-P0-8**（module-global active selection、tasks 03/04、gate G2）— open。legacy 面の request-scoped 化は shell/API 移行の完了条件。
2. **Browser metrics（LCP/INP/CLS）+ server p95/large-run fixture 計測** — G6 dogfood の固定環境計測へ deferral（RR-PR-5 open-partial、protocol 記録済み）。
3. **task 02 a11y remediation**（axe `region`/`select-name` + legacy 4 route の h1）— frozen ratchet で管理、v2 移行で解消。
4. **Deployment profile smoke（fixture + 統合 runbook）と recovery runbook の恒久化** — G6/plan 10 の docs 移管 scope（現状は MN-4..9 + setup_env.sh に分散記載）。
5. **Settings 画面の token 入力 UI** — ADR-13 consequences の follow-up backlog（現状は localStorage 手動設定を文書化）。
6. **Bookkeeping**: RR-P0-1 行が status 上 open のまま（是正自体は Wave 2a 完了・ADR-10 accepted・MN-1 告知済み。row への close 転記が未実施 — owner 07/09 の登録事務）。

**Wave 5b exit / G5 判定: 通過（条件付き残余を明記）（2026-07-26）。** G5 を blocking gate とする risk register 行（RR-P0-3/5/6/7/9/10）は全て closed。RR-PR-5 のみ G5-blocking で open-partial だが、未達部分は測定手段の不在（jsdom）に起因する理由付き G6 deferral であり、CI-provable な全 budget は enforce 済み — 明示 accepted として扱う。endpoint 追加は `GET /health/live`・`GET /health/ready`・`GET /api/v1/diagnostics` の 3 件のみ、削除なし。simple_bfts・legacy 画面・RQGM read-only・loopback 既定は無変更。全 Wave 5b 変更が env-only rollback（MN-8: `ARI_GUI_AUTH=0`、MN-9: `ARI_GUI_HEALTH=0`）を持つ。INDEX: task 09 を `implemented` へ更新（`verified` への昇格は G6 での residual 解消確認後）。

## Wave 4e exit record / G4 判定（2026-07-26）

Wave 4e（canonical idempotent launch **MN-10** `POST /api/v1/runs` + Configuration Studio launch flow UI **MN-11**）の検証済み deliverable と、G4（Vertical slices）の line-by-line 判定。

### Deliverables（検証済み）

| 領域 | 内容 |
|---|---|
| Canonical launch backend（tasks 04/06、**MN-10**） | 新設 **`POST /api/v1/runs`** `{draft_id, display_name?, profile?, idempotency_key?}`（`ari/viz/v1/launch.py`、499 行）。**validation-first**: ADR-12 GuiStore から draft load（未知 → typed 404）→ plan-05 resolver preview + 共有 draft validation（`config_api._draft_validation_errors` を抽出し `/validate` と同一実装）→ launch 固有 check 2 つ = goal 欠落（400 `missing_goal`）と governance/mode field の draft 内存在（400 `mode_locked` — `Execution mode` category + `rqgm.*` prefix、ConfigStudio lock と同一集合、ADR-09 pending）。**拒否時 filesystem mutation ゼロ**（tested）。run identity は validation 後に server 発行: `run_id = <UTC YYYYMMDDHHMMSS>_<slug>-<uuid4 6hex>`（deterministic `PathManager.slugify` — accepted 前の LLM slug 生成・`sinfo` scheduler probe を accept path から排除。timestamp+slug は legacy dir 慣行を維持し CLI dir 採用・checkpoint finder 互換）。**materialize before spawn**: `experiment.md`（draft goal）/ bundled `workflow.yaml` CoW seed / legacy 互換 `launch_config.json`（+additive `draft_id`/`resolved_config_digest`/`display_name`）/ **`resolved_config.json`** = plan-05 manifest の REAL 化（minted run_id 充填、digest は resolve-config preview と byte 一致 — tested）/ `launch_events.jsonl` lifecycle（`draft→validating→accepted→spawned` monotonic event_id、spawn 失敗時 `failed` + recovery 記録）。spawn は legacy と同一 CLI subprocess（`python3 -m ari.cli run {ckpt}/experiment.md [--profile]`、`ARI_CHECKPOINT_DIR` pin、env = os.environ + `load_dotenv_files` + GUI 層値は documented `field_registry.ENV_OVERRIDES` family のみ translate — locked mode path は template 経由でも構造的除外）。**idempotency**: `gui_store/launches/{key}.json` の create-only claim が spawn 前 — 並行 duplicate でも subprocess は 1 つ、duplicate POST は同一 `run_id` + `idempotent_replay: true` で何も spawn しない。global active checkpoint は**切り替えない**（plan 04 invariant）。**25 backend tests**（Popen mock — spawn なしで全 protocol 検証） |
| Studio launch flow UI（task 06、**MN-11**） | `#/studio?draft=` に `ConfigStudio/LaunchPanel.tsx`: stepper **goal → review → launch**（plan 06 の 9-state machine を本 slice に narrowing — 宣言済み）。[Resolve & validate] = resolve-config + validate → effective-config diff vs defaults（ConfigBrowser badge/table 再利用）/ draft 帰責 validation error（共有 ValidationSummary）/ resolver warning / secret readiness（値は構造的に非表示）/ ADR-09 locked-governance note。**immutable review summary**（display name、「run_id は server-issued at accept」明記、profile、changed-fields count、digest）+ 明示 confirm checkbox — approval 毎に idempotency key を 1 回だけ mint（`crypto.randomUUID`）。[Launch] は valid+goal+confirm 揃うまで・in-flight 中 disabled、double-click/retry は同一 key replay → spawn 1 つ。success は server 発行 `run_id` で **`#/overview?run=` canonical redirect**（mtime/latest-checkpoint polling なし）。typed error envelope（`missing_goal`/`mode_locked` 含む per-path errors）表示。**4 frontend tests**（`ConfigStudioLaunch.test.tsx`） |
| Legacy parity | `POST /api/launch`・`api_experiment.py` は **byte-identical に無変更**（working-tree diff 0 を確認 — frozen source-inspection contract 維持）。simple_bfts・legacy Wizard/Settings 無変更。endpoint 追加は `POST /api/v1/runs` の 1 件のみ、削除なし |
| 配線 | `v1/{router,dto,openapi}.py` + `openapi.json` + `gen:v1types`、`store.py`（`KIND_LAUNCH`/`launches/` additive）、`config_api.py`（`POST /run-drafts` optional `goal` 受理 + `_draft_validation_errors` 抽出）、`services/api/v1.ts`（`resolveDraftConfigV1`/`validateRunDraftV1`/`launchRunV1`）、snapshot contracts / `viz_endpoints.json`、migration notes **MN-10/MN-11**、i18n 3 言語 ×32 key |

### 宣言済み deviations

- launch lifecycle の記録先は run-scoped `launch_events.jsonl`（`viz_access.jsonl` は active checkpoint の HTTP access log であり、run の記録は run と共に残す — docstring に根拠明記）
- accepted 前の LLM slug 生成・`sinfo` probe は accept path から削除（plan 06 §Launch protocol の指示どおり bounded preparation 化。legacy `POST /api/launch` は両 slow path とも従来挙動のまま並行稼働）

### Final gates（本 record 作成時の再実測、2026-07-26）

| Gate | 結果 |
|---|---|
| backend full suite | **4701 passed / 16 skipped / 2 xfailed**（218.31s、failed 0。5b 比 +25 = `test_gui_v1_launch.py` 25） |
| 個別再実行 | `test_gui_v1_launch.py` **25** / `test_gui_config_shadow_legacy.py` **28** / `test_gui_v1_rqgm.py` **41** passed |
| scripts/tests | **104 passed** |
| `npm run typecheck` | 0 errors |
| `npm test` | **195 passed + 1 todo**（30 files。`ConfigStudioLaunch` 4 追加） |
| `npm run build` | green。main **60.88 KiB gzip**（budget 100 以内） |
| `check_bundle_budget.py` | exit 0、全 budget green |
| checkers | `check_viz_api_schema` exit 0（new 0、known のみ）/ `snapshot_contracts --check` 4 surface 同期 / `check_dashboard_ux` green（known のみ）/ directory policy green / `check_import_boundaries` exit 0（known のみ）/ `python -m ari.viz.v1.openapi --check` in sync |
| env/CJK gate | `test_setup_env.py` + `test_i18n_consistency.py` **20 passed** |

### G4 判定 — INDEX G4 exit「Config、Research、RQGM の各 workspace が run ID 明示で end-to-end 動作」

| Workspace | 判定 | 根拠 / 残余 |
|---|---|---|
| Config | **達成** | `#/studio?draft=` の schema-driven 編集（PROJECT/TEMPLATE/DRAFT scope、If-Match 楽観並行）→ resolve/validate → immutable review → `POST /api/v1/runs` → server 発行 `run_id` → `#/overview?run=` canonical redirect。全経路が draft ID / run ID 明示で global active checkpoint に依存しない。launch は idempotent（double-click negative test） |
| Research | **達成（条件付き）** | `#/overview?run=`・`#/tree2?run=&node=`・`#/ideas2?run=`・`#/results2?run=` が typed v1 API + run-explicit URL で end-to-end 動作（navReplaces で legacy slot 継承、legacy 画面は両モード到達可能な parity invariant 維持）。残余は plan 07 の depth（下記逐条 bullet 4 — LOD/keyboard/log-artifact cursor）であり end-to-end 動作自体は成立 |
| RQGM | **達成** | `#/governance?run=` の 8 read-only tabs（Overview/Registry/Accountability/Score Lineage/Audit/Epoch Timeline/Evolution/Paper Archive）+ realtime `StaleDataBanner`。committed-only replay、run-explicit、mutation endpoint なし |

**ADR-09（governance step / RQGM mode の GUI 選択）は USER 判断で open** — launch flow から構造的に除外済み（`mode_locked` 400 + `ENV_OVERRIDES` 除外 + Studio locked group）で、開いたままでも安全不変。**user-gated deferral として記録し、G4 判定の対象外**（failure ではない）。

### plan 06 Completion criteria の逐条評価 → **implemented**

| 基準 | 判定 | 根拠 / 残余 |
|---|---|---|
| 全 config field 検索可能 + source/scope/applies-when 説明 | 達成 | ConfigBrowser の path/category search + resolver provenance/scope（Wave 3b）、Studio は field registry 駆動で hardcode なし |
| Settings と Wizard が同じ schema/resolver/catalog | 達成（新面） | Studio の設定編集と launch flow は同一 `/api/v1/config/schema` + plan-05 resolver + server model catalog を共有。legacy Settings/Wizard は strangler 並行稼働のまま — 撤去は cutover（G6）scope |
| durable draft + guarded state machine が refresh/concurrency に耐える | 達成（narrowing 明記） | server-side revision draft（If-Match 409）+ guarded stepper + idempotent launch。plan の 9-state 全幅（scope/workflow/models_and_resources step 分割）は未展開 — 残余 |
| launch は backend `run_id`、latest-checkpoint 推測なし | **達成** | MN-10/MN-11。canonical redirect は server 応答の `run_id` のみ使用（tested） |
| active/resumed run の immutable setting を UI/backend 両方で変更不可 | 達成（条件付き） | backend: `mode_locked` 400 + `reconcile_resume_mode`（persisted 優先）+ env 構造的除外。UI: locked group。ただし Studio の resume/clone flow 自体が未実装（resume は legacy 経路のみ — 残余） |
| legacy 24-key adapter + shadow diff が migration gate を通る | 達成 | `test_gui_config_shadow_legacy.py` 28 passed |

### plan 07 Completion criteria の逐条評価 → **in_progress のまま**

| 基準 | 判定 | 根拠 / 残余 |
|---|---|---|
| 全 workspace が canonical run ID + typed API | 大半達成 | Overview/Tree/Ideas/Results ✓。Projects portfolio v2 と artifact/log explorer v2 は未着手（legacy 面のまま） |
| 責務不重複 + deep-link 接続 | 達成 | navReplaces + `?run=`/`?node=` deep link、Tree↔Ideas↔Results↔Governance 相互リンク |
| research/benchmark/governance status 不混同 | 達成 | 分離表示（Wave 4b）+ PaperBench durable jobs（Wave 4c） |
| large tree/log/artifact が bounded query/render | **未達** | tree LOD/viewport culling/virtualized side table/keyboard navigation 未実装、log cursor explorer 未実装（bounded なのは EAR listing cap 500 のみ） |
| workflow edit の revision conflict 検出 + active run snapshot 不変 | 達成（条件付き） | MN-3 revision guard（409 + frozen payload）。「この編集はどの run に効くか」の保存時明示（二重 file 意味論の解消）は未完 |
| capability parity / 意図的変更の migration note 記録 | 達成 | MN-3 + 各 wave record の parity invariant 記載 |

bullet 4 が測定手段の問題ではなく実体未実装のため、**07 は `implemented` に昇格しない**。G4-tail は残余一覧 1 に明記。

### plan 08 Completion criteria の逐条評価 → **implemented**

| 基準 | 判定 | 根拠 |
|---|---|---|
| committed transition を Overview→raw source まで追跡可能 | 達成 | 8 endpoint + byte-offset cursor + source link（Wave 4a/4b、41 tests） |
| score rewrite が old/new policy・before/after・reason・affected node・source event を持つ | 達成 | 二チャネル score lineage DTO（penalty/policy 分離） |
| score history 非上書き + policy hash 跨ぎの誤連続なし | 達成 | facet 分離を presentation contract test で pin（`GovernancePage.test.tsx` 14 tests: channel-2 faceting、epoch faceting） |
| research/governance・raw/validated・stale/removed の state 分離（UI/API/test） | 達成 | truth rules は backend 41 + fixture factory 28 + frontend 14 で test 化済み（raw attack は構造的に score 不能な `kind:'raw'`、inert chain は capability note） |
| RQGM disabled/legacy/degraded 時に推測で正常表示しない | 達成 | capabilities state + `degraded_reasons`（破損は 500 でなく integrity flags）、missing source は None（0 と描かない） |
| v1 workspace read-only、direct governance mutation endpoint なし | 達成 | GET-only、`ari.rqgm` 非 import の pure reader |

補足: §Configuration integration の「Overview 内 inline RQGM config snapshot」は `#/config?run=` deep-link（run-scoped resolver 表示）で代替 — completion criteria 外として記録。

### 残余一覧（条件付き通過の明記事項）

1. **plan 07 G4-tail**（owner: task 07、Wave 6 割当）— large-tree LOD/viewport culling/virtualized table/keyboard navigation、PaperBench wizard polish、artifact/log cursor explorer、workflow 保存先 run の保存時明示、Projects portfolio v2。
2. **plan 06 tail**（owner: task 06）— governance step は **ADR-09 user-gated deferral**（USER 回答で解錠 — 実装は locked group 解除 + launch `mode_locked` 撤廃 + governance step 追加）、resume/clone Studio slice、draft state machine の全幅展開、legacy Settings/Wizard 撤去（G6 cutover scope）。
3. **G2-tail（tasks 03/04、Wave 6 prep として明示割当）** — (a) AppContext reduction（owner 03: 残 page-local fetch/context の v1 read-model 化）、(b) legacy `/state` freeze（owner 04: aggregate endpoint の凍結と v1 read model への完全移行）、(c) **RR-P0-8**（owner 03/04: `viz/state.py` module-global active selection/process/settings state の request-scoped 化）。G2 は並行稼働時点で通過済みだが、この tail が解消するまで 03/04 は `in_progress` のまま。
4. G5/G6 既知残余は Wave 5b record の残余一覧のとおり（本 wave での変更なし）。

**Wave 4e exit / G4 判定: 通過（条件付き残余を明記）（2026-07-26）。** INDEX G4 exit condition（Config、Research、RQGM の各 workspace が run ID 明示で end-to-end 動作）は 3 workspace とも成立。endpoint 追加は `POST /api/v1/runs` の 1 件のみ、削除なし。simple_bfts・legacy launch/Wizard/Settings・RQGM read-only は無変更。ADR-09 は user-gated open（launch flow から構造的除外済み — 判定対象外）。INDEX: task **06/08 を `implemented`** へ更新（`verified` 昇格は residual 解消 + G6 確認後）、**07 は bullet-4 未達のため `in_progress` のまま**（G4-tail を残余一覧 1 に明記）。

## Wave 6a exit record（2026-07-26）

Wave 6a（task 07 G4-tail の large-tree/log 実体化 + tasks 03/04 G2-tail の freeze/guard + RR-P0-8 処置）の検証済み deliverable と exit 判定。

### Deliverables（検証済み）

| 領域 | 内容 |
|---|---|
| TreeV2 large-tree LOD（task 07 G4-tail） | 深さ filtering は再利用中の legacy D3 `TreeVisualization` に**渡す前**に完結: 新 pure module `treeLod.ts` の `computeVisibleRows` が iterative DFS で「全 ancestor が展開済みの node のみ emit」の単一 visible set を算出し、canvas と side table が同一集合を共有（visible set 内の parent link は常に intact）。LOD 規則: >500 nodes（`LOD_NODE_THRESHOLD`）で structural depth ≤ 3（`LOD_DEPTH_LIMIT`、parent link から導出 — `node.depth` field 非依存）+ 選択 node の ancestor path + その children を default 表示。visible < total の間は必ず「Showing {N} of {M} nodes (depth-limited)」banner + [Expand all]（silent truncation なし）、oversized tree の全展開時は「Showing all M nodes」+ [Restore depth limit] を明示。legacy `#/tree`・`components/Tree/*` は無変更（git status に entry ゼロ） |
| TreeV2 virtualized table + keyboard（task 07 G4-tail） | `TreeTablePanel.tsx`: scrollTop-sliced windowing（新規依存なし、ROW_H 28、overscan 6）。roving tabindex、ArrowUp/Down 移動、ArrowLeft/Right で subtree collapse/expand（per-node override が LOD default に優先）、Enter 選択。aria は role=tree > role=group > role=treeitem + aria-level/aria-expanded/aria-selected。selection 同期は canvas click / table click / Enter の全てが `?node=` hash を書く — URL が single source of truth を維持。500-LOC tripwire 回避のため inspector を `TreeV2Inspector.tsx` へ verbatim 抽出、sentinel 抽出は `treeNodes.ts` へ（`TreeV2Page` が `toTreeNodes`/`sentinelsOf`/`ScoreSentinels` を re-export し歴史的 test surface を維持）。i18n 5 keys × 3 locale。実測（synthetic 10k 3-ary fixture）: default visible **40/10000**、deep-selection（level 9）**58/10000**、keyboard expand 1 回後 43/10000。DOM treeitem 数は mid-list scroll 中含め **28–34**（<100 assert）。`computeVisibleRows` 10k nodes = **4.3–6.2 ms**（LOD path）/ 11.6 ms（expand-all）vs 緩い <200 ms assertion。file size: TreeV2Page 347 / TreeTablePanel 235 / TreeV2Inspector 213 / treeLod 138 / 新 test 341 LOC — 全て 500 warn tier 未満（LOC tripwire 更新不要） |
| Log cursor explorer（task 07 G4-tail、plan 07 §Artifacts, logs, and diagnostics） | 新設 `GET /api/v1/runs/{run_id}/logs?cursor=&limit=&grep=`（`ari/viz/v1/logs.py`、pure read、`viz.state` 非依存）。**cursor = raw byte offset**、`grep` filter は返却行のみ選別し消費 byte は選別しない（filter 変更を跨いでも page chain が gap/duplicate しない）、**committed-only**（末尾の `\n` 無し行は emit せず `next_cursor` をその先頭 byte に park）、**bounded**（1 request の scan は `SCAN_WINDOW_BYTES` 1 MiB まで — whole-file 再読込経路なし）、honest absence（log 未生成 run は 200 `present=false`、unknown run のみ typed 404）。**17 backend tests**。frontend は Overview の `LogsPanel.tsx`: collapsed 中は fetch ゼロ、[Load more] は `next_cursor` から append（重複なし）、follow mode は run event 毎に次 cursor page、grep 適用は chain を cursor 0 から再開、honest-absence note、follow 中の stream 断のみ in-panel stale banner。**6 tests** |
| legacy `/state` freeze（task 04 G2-tail） | `/state` aggregate は **FROZEN facade** — `services/state_service.py` header 宣言 + `tests/test_gui_state_facade_freeze.py`（**3 tests**）が frozen top-level key set を固定し、additive growth も fail させる。新規 read は v1 read model へのみ追加可能 |
| AppContext scoping guard（task 03 G2-tail） | `frontend/src/__tests__/appContextScope.test.ts`（**3 tests**）が v2 dirs（Projects/Overview/TreeV2/IdeasV2/ResultsV2/Governance/ConfigBrowser/ConfigStudio）を AppContext-free に構造固定。pinned 例外は IdeasV2 research-goal card の run-identity-gated read の 1 箇所のみ |
| RR-P0-8 処置 | risk register row を **accepted (G2 tail) — 残余は G6 legacy removal で消滅** に更新。evidence 3 点: (1) canonical/v2 面は完全 run-explicit（v1 API の data boundary は path `run_id`、canonical launch は global active checkpoint を切替えない）、(2) module-global `_st` の read/write は凍結済み legacy facade の背後にのみ残存（/state freeze + AppContext guard が凍結を test で固定）、(3) globals 自体の物理削除は plan 03 §Migration sequence step 7 / plan 04 §Compatibility and migration step 7（G6 legacy removal gate）に紐付け |

### Final gates（本 record 作成時の再実測、2026-07-27）

| Gate | 結果 |
|---|---|
| backend full suite | **4721 passed / 16 skipped / 2 xfailed**（220.33s、failed 0） |
| 新規 suite（単独再実行） | `test_gui_v1_logs.py` **17** / `test_gui_state_facade_freeze.py` **3** = 20 passed |
| scripts/tests | **104 passed** |
| `npm run typecheck` | 0 errors |
| `npm test` | **212 passed + 1 todo**（33 files。TreeV2 19（うち `TreeV2LargeTree` 8 新規）/ `LogsPanel` 6 / `appContextScope` 3。`__tests__/README.md` 新設） |
| `npm run build` | green。main **60.87 KiB gzip**（budget 100 以内） |
| checkers | 8 checker + snapshot の **exit 0 を個別に明示確認**（pipe 越しの `$?` ではなく checker 単体の RC を捕捉）: `check_viz_api_schema`（new 0、known のみ）/ `snapshot_contracts --check`（public,cli,mcp,viz 4 surface 同期）/ `check_bundle_budget`（`--fail-on-regression` 併せて RC 0）/ `check_dashboard_ux --fail-on-regression`（known のみ）/ `check_directory_policy` / `check_import_boundaries`（known のみ）/ `check_prompts` / `check_dead_code --check` + `python -m ari.viz.v1.openapi --check` in sync |
| CJK gate | `test_i18n_consistency.py` **9 passed** |

**Wave 6a exit 判定: 通過（2026-07-26）。** endpoint 追加は `GET /api/v1/runs/{run_id}/logs` の 1 件のみ、削除なし。simple_bfts・legacy 画面・RQGM read-only は無変更。

## G1 判定

G1 exit condition（INDEX: 情報設計、用語、design tokens、アクセシビリティ基準を承認）の formal 判定（retroactive、2026-07-27 record）。G1 は明示 record を欠いたまま後続 wave が積み上がっていたため、実装済み evidence に基づき遡及判定する。

| 基準 | 判定 | evidence |
|---|---|---|
| 情報設計（plan 01） | 達成 | plan 01/02 は 2026-07-23 に実装と突き合わせて refine 済み（INDEX「Verified against implementation」）。route registry（現 21 routes）+ navReplaces が IA を単一 source として実装反映、workspace 責務分離 + deep-link 接続は Wave 4e G4 判定で逐条確認済み |
| 用語 | 達成 | `baseline/glossary.md` を正典に、frozen vocabulary を test で enforce: research phase（idle→starting→bfts→paper→review）、TreeV2 inspector の status/label vocabulary、research/governance status 不融合（presentation contract test）、registry 10 状態 vs node score 5 状態の token 分離 |
| design tokens | 達成 | semantic token layer + `motion.css`（reduced-motion）は Wave 1 出荷。全 v2 workspace（Projects/Overview/TreeV2/IdeasV2/ResultsV2/Governance/ConfigBrowser/ConfigStudio）が semantic tokens/common components のみで構成（各 wave record に記載） |
| アクセシビリティ基準 | 達成 | axe-core frozen ratchet（violation `['region','select-name']`）+ per-route h1 baseline を shrink-only CI gate 化（Wave 1）。i18n 3-locale parity + CJK gate は CI gate。keyboard/SR は v2 slice の実装 gate（Governance tablist、TreeV2 aria tree + roving tabindex） |

**G1 判定: 通過（retroactive、2026-07-27）。** tasks 01/02 の status は `implemented` のまま維持（`verified` 昇格は task 02 remediation list — legacy 4 route の h1 + shell landmark 2 violation — の解消と G6 文書移管後）。

## G2 判定

G2 exit condition（INDEX: 新 shell と `/api/v1` を旧画面・旧 endpoint と並行稼働）の formal 判定（2026-07-27）。並行稼働自体は Wave 2 完了時点で成立していたが、G2-tail（AppContext reduction / legacy `/state` freeze / RR-P0-8）を残して formal 判定を保留していた。Wave 6a で tail が解消したため判定する。

| 基準 | 判定 | evidence |
|---|---|---|
| 新 shell 並行稼働 | 達成 | registry shell は Wave 1 から（13 → 現 21 routes）。`ARI_GUI_V2` kill-switch + `V2_ONLY_ROUTES` + navReplaces で route 単位切替、legacy 画面は両モード到達可能（parity invariant、gui_v2-off gating test） |
| `/api/v1` 並行稼働 | 達成 | router table **41 routes** + SSE `/api/v1/events/stream` = **42 endpoints** が Wave 2a 以降 legacy API と並行稼働。typed error envelope、決定論的 OpenAPI 3.1 + drift guard、生成型 byte-equality、GET 副作用ゼロ保証 |
| parity suites | green | shadow legacy config 28 / legacy Settings 19 / SettingsContract / routeNavParity / snapshot 4 surface — 全 green（Wave 6a gate 実測に含む） |
| G2-tail | 解消 | `/state` FROZEN facade（3 tests、additive growth fail）、AppContext scoping guard（3 tests、pinned 例外 1）、RR-P0-8 **accepted (G2 tail)**（module-global の物理削除は G6 legacy removal gate に紐付け） |

**G2 判定: 通過（2026-07-27）。** INDEX: tasks 03/04 を `implemented` へ更新（下記逐条）。

### plan 03 Completion criteria の逐条評価 → **implemented**

| 基準 | 判定 | 根拠 / 残余 |
|---|---|---|
| route/nav/breadcrumb が単一 registry から生成 | 達成 | `routeRegistry.ts`（21 routes、navReplaces、nav parity test） |
| 全 run-scoped query/event が run_id 隔離 | 達成 | react-query key に run/project ID、event invalidation の run 単位隔離（two-run isolation test、Wave 2b） |
| server/URL/form/preference/ephemeral state の owner 不重複 | 達成 | v2 は typed v1 read model + `?run=`/`?node=`/`?draft=` URL state に一本化。AppContext は legacy-scoped 宣言 + 構造 guard（Wave 6a） |
| 旧/新 page の route 単位 feature flag 切替 | 達成 | `ARI_GUI_V2` + `V2_ONLY_ROUTES` + navReplaces（gui_v2-off test） |
| old hash URL contract suite green | 達成 | legacy route 到達性 + render baseline を pin（routeNavParity / routeRenderBaseline）、legacy 画面無変更 |

残余（deferred-with-gate）: legacy AppContext/module-global の物理削除は plan 03 の **Deletion criteria**（G6 legacy removal）に割当済み — completion criteria には掛からない。

### plan 04 Completion criteria の逐条評価 → **implemented**

| 基準 | 判定 | 根拠 / 残余 |
|---|---|---|
| 新画面の全 endpoint が `/api/v1` + explicit run ID | 達成 | appContextScope guard が構造的に pin（例外は IdeasV2 research-goal card の run-identity-gated read 1 箇所 — guard test に明示 pin） |
| typed error/status + OpenAPI client の frontend CI 検証 | 達成 | typed error envelope 正規化 client + `v1TypesDrift` byte-equality + `openapi --check` |
| 10k event/large tree fixture の cursor query（全ファイル再読込なし） | 達成（Wave 6a で閉鎖） | logs = byte-offset cursor + 1 MiB scan window（17 tests）、RQGM read model = byte-offset cursor（Wave 4a）、SSE = ring buffer 1000 + `Last-Event-ID` replay、tree 10k fixture = bounded render（TreeV2 LOD、DOM <100） |
| SSE 切断時に stale を停止/失敗と誤表示しない | 達成 | `StaleDataBanner` 方針を全 v2 workspace で維持（「stream 断 ≠ run stopped」、LogsPanel も同型） |
| legacy API/WS parity + rollback 実証 | 達成 | legacy endpoint 無変更 + kill-switch rollback（Wave 2 exit で実証）、`/state` は FROZEN facade として非破壊凍結 |

残余（deferred-with-gate）: legacy facade（`/state` ほか）の削除と global active checkpoint の data boundary からの物理除去は plan 04 の **Deletion criteria**（G6）に割当済み。

### plan 07 Completion criteria 再判定 → **implemented**

Wave 4e 時点の未達 bullet 4 と条件付き bullet 1/5 を Wave 6a 後に再判定:

| 基準 | 判定 | 根拠 / 残余 |
|---|---|---|
| large tree/log/artifact が bounded query/render | **達成（Wave 6a で閉鎖）** | tree: LOD + virtualized table + keyboard（10k fixture、DOM <100、4.3–6.2 ms）。log: cursor explorer（byte-offset、1 MiB scan window、committed-only）。artifact: EAR bounded listing cap 500 + truncated flag（Wave 4d） |
| 全 workspace が canonical run ID + typed API | 達成 | Projects/Overview/Tree/Ideas/Results ✓（ProjectsPage は Wave 2b から v1 API + run-explicit query key）。log/artifact も v1 read model 化完了 |
| workflow edit の revision conflict 検出 + active run snapshot 不変 | 達成 | MN-3 revision guard（409 + frozen payload、何も書かない）+ CoW guard（同梱 workflow.yaml は GUI 書込み不能）— criteria の文言は両方 test 済み |
| （他 3 bullet） | 達成 | Wave 4e の逐条評価から変更なし |

**07 status 判定: `implemented` へ昇格。** 残余は completion criteria の文言外の polish であり、`verified` 昇格前の解消項目として明示する: (a) **Projects portfolio polish** — ProjectsPage の legacy handoff が TODO 付き暫定のまま（機能 parity は成立、体験 polish 未了）、(b) **workflow 保存先 run の保存時明示** — 二重 file 意味論の安全側は CoW guard + MN-3 で解消済みで、残るは「この保存はどの checkpoint copy に効くか」の UI 表示、(c) **PaperBench wizard polish**（Wave 4e 残余一覧から変更の記録なし）。いずれも安全性・契約・bounded 性の gate に掛からないため status を block しない（判定根拠）。

判定根拠の補強（残余が *Completion* ではなく *Deletion* criteria に属することの確認）: plan 03 Deletion criteria は「legacy router/AppContext remote state が削除済み」、plan 04 は「legacy facade の削除条件を満たしている」、plan 07 は「legacy fetching/**handoff**/page route が removal criteria を満たしている」と明記する。すなわち AppContext pinned 例外・`/state` facade・module-global・ProjectsPage の sessionStorage handoff はいずれも各 plan 自身が **G6 削除ゲート**へ割当てた項目であり、Completion criteria の未達ではない。この文言確認をもって 03/04/07 の `implemented` 昇格は plan 準拠と判定する。

### INDEX 反映と最終独立検証（2026-07-27）

INDEX 反映: task **03 / 04 / 07 を `in_progress` → `implemented`**、header `Updated` を G1/G2 通過に更新、残余追跡 bullet の G2-tail と task 07 G4-tail を「解消（残 polish 3 件を明示）」へ書換え。01/02 は `implemented` 据置き（G1 通過だが task 02 remediation + G6 文書移管が `verified` 条件）。

最終独立検証: 本 record の gate 数値は、記録時とは別 pass で全 gate を再実行して一致を確認済み — backend **4721 passed / 16 skipped / 2 xfailed**、scripts/tests **104 passed**、`npm run typecheck` 0 errors、`npm test` **212 passed + 1 todo（33 files）**、`npm run build` main **60.87 KiB gzip**、checker 8 件 + `openapi --check` の RC 0、`test_i18n_consistency` **9 passed**。deliverable 側も実地確認: legacy `components/Tree/*` は git status entry **0**（無変更）、route registry **21 routes**、v1 OpenAPI **41 operations / 36 paths**（+ SSE `/api/v1/events/stream` は openapi 非掲載 = 計 42 endpoint）、TreeV2 の LOC（TreeV2Page 347 / TreeTablePanel 235 / TreeV2Inspector 213 / treeLod 138 / TreeV2LargeTree.test 341）は記載値と一致。

## Wave 6b exit record（2026-07-27）

Wave 6b（task 10 = Migration, testing, release, and docs のうち **恒久文書への移管**）の検証済み deliverable と exit 判定。本 record の全数値は、移管作業とは別 pass で再実行した実測値であり、各 claim は task summary ではなく一次資料（`ari/viz/v1/*`、`ari/config/{field_registry,resolver}.py`、`ari/viz/{auth,health,routes,server}.py`、`ari/rqgm/*`、`frontend/src/app/routeRegistry.ts`、`scripts/setup/setup_env.sh`、committed `openapi.json`）に突き合わせて確認した。

### 移管された文書（family 別、EN + ja + zh の 3 言語すべて）

新規 8 page × 3 言語 = **24 file**（EN 合計 2,775 行）:

| Family | Page | EN / ja / zh 行数 | 移管元（plan） |
|---|---|---|---|
| concepts | `gui_architecture.md` — Dashboard Architecture（route registry、state ownership、SSE=invalidation 契約、5000 ms staleTime / 10 s polling fallback） | 358 / 357 / 324 | 03, 04 |
| concepts | `research_and_governance_state.md` — 4 つの state machine（run lifecycle / research phase / governance stage / node score state）と stale・invalidated・removed・deleted の区別 | 284 / 279 / 249 | 08 |
| guides | `dashboard.md` — 起動、port（8765 / WS 8766）、capability flag、workspace map、nav 表（navOrder 順）、deep link | 348 / 340 / 315 | 01, 03 |
| guides | `configuration_studio.md` — field registry、provenance/mutability badge、3 scope、If-Match、secret write-only、launch flow | 417 / 393 / 370 | 05, 06 |
| guides | `remote_access.md` — bind policy、token 認証、CORS、CSP、confirmation challenge、SSH tunnel、HPC reverse proxy（**未検証 guidance と明記**）、health/diagnostics | 458 / 445 / 418 | 09 |
| guides | `rqgm_gui.md` — RQGM governance workspace の読み方 | 354 / 335 / 315 | 08 |
| guides | `gui_cutover_runbook.md` — lever 表、pre-cutover checklist、staged rollout、stop/rollback、legacy removal 順序、compatibility matrix | 311 / 300 / 283 | 10 |
| reference | `rqgm_gui_read_models.md` — artifact → endpoint map、integrity flag、degraded 意味論、2 つの status 語彙 | 245 / 241 / 225 | 08 |

既存 page の更新（EN / ja / zh、`+行/-行`）:

| Page | EN | ja | zh | 内容 |
|---|---|---|---|---|
| `reference/rest_api.md` | +445/-56 | +460/-55 | +436/-43 | `## /api/v1 (canonical)` を新設。versioning、typed envelope（5-code 語彙）、`If-Match`、cursor 規約、SSE 契約、auth、challenge、**41 operation の endpoint 表**（committed `openapi.json` から生成）。legacy 節は "frozen facade" として原文保持 + MN-1…MN-10 表 |
| `reference/configuration.md` | +575/-8 | +619/-3 | +596/-3 | `## Configuration control plane` を新設。144-leaf / 100 % coverage、`ENV_OVERRIDES` 20 行、2 本の解決 chain、`resolved_config.json`、`gui_store/`、legacy Settings の 24-POST vs 27-GET 非対称 |
| `reference/environment_variables.md` | +38/-1 | +37/-1 | +36/-1 | `### GUI server (ARI_GUI_*)` 8 変数（既定値・効果・rollback lever としての位置づけ） |
| `guides/migration.md` | +368/-1 | +347/-1 | +316/-1 | `## GUI refresh (v2 dashboard)` — before/after と各 rollback lever |
| `getting-started/quickstart.md` | +18/0 | +18/0 | +26/0 | v2 workspace への導線 |

Runbook: `docs/guides/gui_cutover_runbook.md`（+ ja/zh）。§1 lever 表（`ARI_GUI_V2` のみ rollout flag、残り 7 は security kill-switch）、§2 pre-cutover checklist（13 の hard gate + 手動 sign-off 2 件を「機械強制されない」と明示）、§3 staged rollout（dogfood → opt-in → default-on）、§4 stop/rollback 条件、§5 layer 別 rollback（flag 秒 / bundle 分 / security incident path）、§6 legacy removal の依存順 5 段（各段に tied gate）、§7 compatibility matrix。

CHANGELOG: `CHANGELOG.md` Unreleased 節に **GUI refresh の 6 bullet**（v2 dashboard 並行稼働 / `/api/v1` 36 paths / configuration control plane / Configuration Studio + idempotent launch / RQGM governance workspace read-only / security posture と env kill-switch）。末尾に **Honest limits** を明記: mode 選択は config/env のみ（draft は 400 `mode_locked`）、legacy 画面・`/state`・port+1 WebSocket は cutover gate まで残置、performance budget は bundle 半分のみ CI 強制（browser metric は手動 profile）。

### 三言語 parity（機械検証）

`docs/{reference,guides,concepts,getting-started}` で作成／更新された EN 33 page について ja/zh counterpart と heading 構造を照合。**heading 数一致 33/33、heading level 列の構造一致も 0 mismatch**（fenced code block 内の `#` は除外）。ja/zh counterpart を持たないのは `concepts/README.md` / `guides/README.md` / `reference/README.md` の 3 index のみで、これは既存慣行（`docs/ja/**` `docs/zh/**` に README を置かない）どおりであり gap ではない。

本 wave で検出・修正した parity 欠落（いずれも trunk から持ち越しで、zh 側だけが本 branch で解消され ja が取り残されていたもの）:

- `docs/ja/reference/configuration.md`: `## 設定の優先順位（実測された挙動）` 節が丸ごと欠落 → 追加。
- `docs/ja/concepts/architecture.md`: `## 階層アーキテクチャ（v0.7+ リファクタリング）` 節が欠落 → 追加。
- `docs/ja/reference/skills.md`: `#### 著者 / 査読者の対称な venue 条件付け`、`### v0.7.2 — reproduce_contract.execution_profile` の 2 節が欠落 → 追加。加えて `generate_rubric` の signature が旧版（`paperbench_rubric_id=""` 欠落）だったため `ari-skill-replicate/src/server.py:95-105` に合わせて更新し、対応する本文段落を追加。

### 内容 spot-check（prose を信用せず一次資料に突き合わせ）

3 page を選び、各 5 件以上の具体 claim を code に照合。**不一致 0**。

| Page | 照合した claim | 一次資料 |
|---|---|---|
| `guides/remote_access.md` | (1) bind 既定 `["127.0.0.1", "::1"]` / 明示値はその 1 host のみ、(2) 生成 token banner の文言（`(MN-8, ADR-13). It is printed here ONCE and never logged:`）、(3) CORS の allow-headers `Content-Type, X-Filename, If-Match, Last-Event-ID` と `Max-Age 86400`、(4) challenge の TTL 60 s / cap 100 / monotonic / 428 body 文言 / 3 action、(5) `/health/ready` の 5 check 名と `degraded` は 200、(6) localStorage key `ari_gui_token`、(7) `ARI_GUI_*` 8 変数が setup_env.sh に既定どおり存在 | `ari/viz/auth.py`、`ari/viz/server.py:255-273`、`ari/viz/routes.py:410-430`、`ari/viz/v1/challenges.py`、`ari/viz/health.py`、`frontend/src/services/api/client.ts:36`、`scripts/setup/setup_env.sh:544-551` |
| `guides/configuration_studio.md` | (1) **144 leaf / uncovered 0**、(2) category 分布 Governance 96 / Search (BFTS) 14 / Proposal routing 14 / Models 5 / Infrastructure 5 / Evaluation 4 / Execution mode 4 / Skills 2、(3) secret allowlist 8 名、(4) `validate_patch` の閉じた reason 語彙 6 種 + launch の `mode_locked`、(5) `run_id = <UTC %Y%m%d%H%M%S>_<slug>-<uuid4 6hex>`、(6) `gui_store/` layout と `0o600`/`0o700` | `build_field_registry()` を実行して実測、`ari/viz/v1/secrets.py:54-61`、`ari/config/field_registry.py:640-740`、`ari/viz/v1/launch.py:274,448-452`、`ari/viz/v1/store.py:5-12,86-87` |
| `guides/gui_cutover_runbook.md` | (1) `navReplaces` が tree/results/idea slot を奪う実装、(2) `GET /api/capabilities` の `gui_v2` 導出と fetch 失敗時 fail-open、(3) `appContextScope.test.ts` の pinned 例外がちょうど 1 件（`IdeasV2Page.tsx`）、(4) `--fail-on-regression` が bundle/viz-schema/dashboard-ux checker に実在、(5) `python -m ari.viz.v1.openapi` は `--check` が既定で RC 0、(6) `snapshot_contracts.py --surface all --check`、(7) `migration.md#gui-refresh-v2-dashboard` anchor 実在 | `routeRegistry.ts:115-193`、`ari/viz/api_capabilities.py:33-35`、`frontend/src/__tests__/appContextScope.test.ts:52`、各 checker の argparse、`ari/viz/v1/openapi.py:9-10,469-474`、`docs/guides/migration.md:196` |

加えて `reference/rest_api.md` の endpoint 表を committed `openapi.json` と機械照合: **41 operation / 36 path が過不足なく掲載**、openapi 非掲載の 3 route（`GET /api/v1/events/stream`、`/health/live`、`/health/ready`）も「意図的に非掲載」として明記済み。`reference/rqgm_gui_read_models.md` の status 語彙 10 種は `ari/rqgm/events.py:STATUS_VALUES` と順序まで一致、active set 2 種も `ACTIVE_STATUSES` と一致。

spot-check で見つかった事実誤りは 1 件のみで、その場で修正した: `docs/reference/configuration.md` の blockquote が削除済みの `refactoring/notes/08_config_precedence.md` を参照していた（trunk からの持ち越し）。「中央 loader は GUI 経路にのみ実在する `ari.config.resolver`（`legacy-compatible-1`）であり、chain を事後再構成するだけで CLI の解決は変わらない」という現状記述に書き換え、ja/zh にも同一内容を反映。

### Gate 実測（2026-07-27、移管後）

| Gate | 結果 |
|---|---|
| `pytest ari-core/tests`（`--ignore=tests/skills`） | **4723 passed / 16 skipped / 2 xfailed / failed 0**（216.83 s） |
| `pytest scripts/tests` | **104 passed**（45.17 s） |
| `check_docs_source_sync.py` | RC **0** — "no net-new trunk-state staleness (43 known/allowlisted)" |
| `scripts/docs/check_doc_sources.py` | RC **0** — 230 docs / 0 error / 0 warning（`sources` 未宣言 6 件は README index、coverage 非強制） |
| `scripts/docs/` 他 checker | `check_site_i18n` / `check_translation_freshness` / `check_ref_coupling` / `check_readme_parity` / `check_report_cochange` / `check_i18n_js` すべて RC **0** |
| `npm run typecheck` | 0 errors |
| `npm test` | **212 passed + 1 todo**（33 files） |
| `npm run build` | RC 0、main **60.87 KiB gzip** |
| checker 群 | `check_viz_api_schema`（`--fail-on-regression` 併せ RC 0、new 0 / known 23）/ `snapshot_contracts --check`（4 surface）/ `check_bundle_budget`（`--fail-on-regression` 併せ RC 0）/ `check_dashboard_ux --fail-on-regression` / `check_directory_policy` / `check_import_boundaries` / `check_prompts` / `check_dead_code --check` / `python -m ari.viz.v1.openapi --check` — **すべて RC 0** |
| CJK gate | `test_i18n_consistency.py` **9 passed** |

本 wave で修正した gate 逸脱 1 件: `tests/test_setup_env.py::test_setup_env_covers_all_source_env_vars` が `ARI_CLI_SHIM_CODEX_REASONING`（`ari/llm/cli_server.py:120` で参照、本 branch の未 commit 作業で導入）の宣言欠落で fail していた。`scripts/setup/setup_env.sh` の CLI shim ブロックに同形式の宣言行を追加して解消（上記 4723 passed はこの修正後の値）。

**green ではない gate（本 wave の deliverable 外、内訳を明示）:**

- `python scripts/readme_sync.py --check` → RC 1、**21 README が drift**。内訳は `ari-core/ari/{README,cli,config,prompts,protocols,schemas,viz,viz/frontend/src/**}`、`ari-core/{config,tests}`、`ari-skill-paper/tests`、`report/shared/**`、`scripts/` — すなわち RQGM package・`ari/viz/v1/`・`prompts/{rqgm,governance}/`・`scripts/rqgm_eval/` など**先行 wave が追加した実装ファイル**の未掲載であり、**`docs/` 配下の drift は 0**（本 wave が触れた family はすべて clean）。`readme-sync.yml` は `continue-on-error` なしの **hard gate** なので、これは main への merge 前に `python scripts/readme_sync.py --write` + 説明文の手当てが必要な**既知の残作業**である（本 wave では mass-fix しない方針で据置き）。
- `python scripts/docs/check_doc_links.py` → RC 1、**12 件**。すべて `docs/{,ja/,zh/}index.md` の `report/*.pdf`（site assemble 時に生成される path）と site-absolute な `/ARI/` で、当該行は本 branch で**未変更**（`docs/report/` は git 管理下に存在したことがない）。CI では `docs-sync.yml` の "Markdown link integrity (advisory)" として `continue-on-error: true` で運用されている **advisory** であり、blocker ではない。

VitePress の sidebar は `docs/.vitepress/config.ts` の fs-driven 生成なので、新規 8 page は config 変更なしで 3 言語すべての sidebar に載る（config は無変更）。

### G6 readiness — この worktree の外にあるもの

本 wave は G6 exit condition（「既定 UI 切替、最低 1 minor の rollback 期間、恒久文書移管を完了」）のうち **恒久文書移管のみ**を満たす。残る 4 要素は release process 側の事実であって、worktree 内の作業やテスト結果からは**原理的に導けない**:

| # | 残項目 | なぜ worktree で判定できないか | 満たされたと言える条件 |
|---|---|---|---|
| (a) | **main への merge** | 本 wave の成果は branch `RQGM` の未 commit 変更として存在するだけで、main には 1 行も入っていない。delete-after checklist の「実装・テスト・migration が main に merge 済み」は未達。merge 前に上記 `readme_sync --check` の hard gate 解消が必要 | main に merge され、CI の全 job（readme-sync を含む）が green |
| (b) | **default-on rollout と観測期間** | `ARI_GUI_V2` は既に default-on で ship されるが、runbook §3 の stage 1→3 は「実際に人が使った結果」を exit 条件にしている。Settings → Studio、Wizard → Studio launch の 2 slice は stage 1–3 未通過。ARI は telemetry pipeline を持たないため、観測は operator が `viz_access.jsonl` / `launch_events.jsonl` / `/api/v1/diagnostics` を読む**教師付き dogfood**でしかありえず、コード上の証拠にはならない | runbook §3 の各 stage exit を実運用で満たし、release evidence に記録した |
| (c) | **最低 1 minor の rollback 期間** | 「rollback lever を残したまま default-on で 1 minor release 経過」は暦と release 履歴の事実であり、worktree のどのファイルにも書かれていない。現時点で Unreleased 節にいるため、期間は**開始すらしていない** | default-on の minor が release され、次の minor まで rollback lever（`ARI_GUI_V2` と前 bundle の保持）が有効だった |
| (d) | **telemetry 後の legacy 削除** | runbook §6 は「観測期間中に legacy route / legacy `/api/*` の hit が無い」ことを削除条件にしている。legacy 画面・`/state` facade・port+1 WebSocket・AppContext remote state はすべて現存し、削除順の各段に tied gate が紐付いたままである。RR-P0-8、plan 03/04/07 の Deletion criteria、task 06 の legacy Settings/Wizard 撤去も同じ gate に載る | §6 の 5 段を順に削除し、各段で snapshot 再生成 + §2 checklist 再実行が green |

したがって **G6 は worktree からは「通過」と判定できない**。task 10 の status は `planned` → `implemented`（文書移管という deliverable は完成し検証済み）に留め、`verified` 昇格は (a)–(d) が release process 側で満たされた後とする。同じ理由で INDEX の **Delete-after checklist は現時点では満たせない**: 「各 task が `verified`」「main に merge 済み」「rollback 期間が終了し legacy usage telemetry がゼロ」の 3 項目が (a)–(d) に直接依存するため、`docs/plans/gui_refresh/` の削除は G6 通過後にのみ実施できる。移管先文書（上表）は既に恒久ドキュメント側に存在するので、削除時に情報が失われないことだけは本 wave で担保した。

**Wave 6b exit 判定: 通過（2026-07-27）。** 実装コードの変更は `scripts/setup/setup_env.sh` への env 変数宣言 1 行のみ（gate 修復）。endpoint・DTO・frontend・checkpoint 形式はいずれも無変更。

### readme_sync closeout（2026-07-27）

上記「green ではない gate」の `readme_sync --check` 21 README drift のうち、**gui_refresh 所有分をすべて解消**した（編集は README のみ、commit なし）。再実測は RC 1 / **12 README・275 entry**で、残存は**全て RQGM branch 作業の所有**（gui_refresh 所有分 = 0）。

**完全に閉じた README（21 → 12、9 file）**

| README | 追加 entry | 内容 |
|---|---|---|
| `ari-core/ari/viz/README.md` | 21 | `api_capabilities.py` / `auth.py` / `health.py` と `v1/` ＋ その 16 children |
| `ari-core/ari/config/README.md` | 2 | `field_registry.py` / `resolver.py` |
| `ari-core/ari/viz/frontend/src/**`（7 file） | 140（HEAD 比） | `src/` 76・`components/` 51・`services/` 4・`components/common/` 3・`hooks/` 3・`components/Workflow/` 2・`styles/` 1 |

**gui_refresh 分のみ閉じた README（RQGM 分は残置）**

| README | 追加 entry | 内容 |
|---|---|---|
| `ari-core/ari/README.md` | 22 | 親 README への inline copy: `config/{field_registry,resolver}.py`、`viz/{api_capabilities,auth,health}.py`、`viz/v1/` ＋ 16 children |
| `ari-core/tests/README.md` | 27 | `test_gui_*.py` 27 本。これらは `## Contents` ではなく **`## Architecture-boundary guards` の xfail ratchet 箇条書きの途中に誤挿入**されており（`test_lineage_does_not_import_viz` の bullet を 2 分割していた）、`split_readme` の tail 側に落ちて parser から不可視 → drift として残存していた。Contents へ alphabetical に移設し、分断された bullet を復元 |
| `scripts/README.md` | 0 | entry 追加なし（`check_bundle_budget.py` 等 3 件は先行 wave で掲載済）。sibling alphabetical に反していた 2 bullet を移動したのみ |

**残存 drift の所有者内訳（12 README / 275 entry、gui_refresh = 0）**

| README | entry | 所有 | 代表 entry（未掲載） |
|---|---|---|---|
| `ari-core/ari/README.md` | 92 | RQGM | `rqgm/kernel.py`（rqgm/** 66・schemas/** 21・prompts/** 4・`protocols/mcp.py` 1） |
| `ari-core/tests/README.md` | 90 | RQGM 89 / 他 1 | `test_rqgm_kernel.py`（snapshots/prompts/** 51・`test_rqgm_*`/`test_paper_*` 38）＋ `test_delegated_cli_terminal.py`（cli-shim 委譲実行修正の所有） |
| `ari-core/ari/schemas/README.md` | 21 | RQGM | `rqgm_defs.schema.json` |
| `report/shared/README.md` | 19 | RQGM | `appendix/prompts/rqgm/defender.md` |
| `report/shared/appendix/README.md` | 19 | RQGM | `prompts/rqgm/defender.md` |
| `report/shared/appendix/prompts/README.md` | 19 | RQGM | `rqgm/defender.md` |
| `scripts/README.md` | 7 | RQGM | `rqgm_eval/run_ablation.py` |
| `ari-core/ari/prompts/README.md` | 4 | RQGM | `rqgm/` |
| `ari-core/ari/cli/README.md` | 1 | RQGM | `paper_dispatch.py`（`docs/plans/ari_rqgm_paper/03`） |
| `ari-core/ari/protocols/README.md` | 1 | RQGM | `mcp.py`（docstring 冒頭が "RQGM Task 11 §5.7" を明示） |
| `ari-core/config/README.md` | 1 | RQGM | `constitution.yaml` |
| `ari-skill-paper/tests/README.md` | 1 | RQGM | `test_writer_prompt_override.py` |

残作業のコマンドと所有: **`python scripts/readme_sync.py --write` を実行し、生成された `TODO` を手書きの説明文に差し替える。所有は RQGM branch 作業**（gui_refresh の deliverable ではない）。

**closeout 後の gate 再実測（2026-07-27）**: `pytest ari-core/tests`（`--ignore=tests/skills`）**4723 passed / 16 skipped / 2 xfailed**（217.63 s）、`pytest scripts/tests` **104 passed**（45.84 s）、`npm run typecheck` 0 errors、`npm test` **212 passed + 1 todo**（33 files）、`check_directory_policy.py` RC **0**、`check_docs_source_sync.py` RC **0**。closeout の時間帯に変更された非 README ファイルは **0**（`find -newermt` で確認。同日 06:2x の `scripts/setup/setup_env.sh` / `ari/pipeline/integrity.py` 等は closeout 前の別作業）。

### Documentation screenshots + v2 control polish（2026-07-27）

Wave 6b の恒久文書には **旧 screenshot がそのまま残っていた**。移管作業は prose を一次資料に突き合わせたが、**画像は突き合わせ対象に入っていなかった**ため、文章だけが v2 を説明し画像は v1 を映すという状態で exit していた。本 closeout はその欠落を塞ぐ。

**なぜ旧 set が無効だったか。** v2 workspace の投入で **sidebar が 10 entry → 15 entry** に変わった。sidebar は全 route の全 screenshot に必ず写り込む shell 要素なので、これは「一部の画面が古い」ではなく **旧 8 枚 × 3 locale = 24 枚すべてが同時に無効**になったことを意味する。個別 route の中身が変わっていない画面（例: Settings）でも、左半分が実物と違う以上は読者を誤導する。半端な更新はさらに悪い（どのページが最新か読者に判別できない）ため、**全 locale を一度に撮り直す**方針を採った。この不変条件は `frontend/scripts/README.md` に恒久記述として残してある。

**撮影して初めて見えた未整形 control。** 旧 set では v2 workspace が 1 枚も写っていなかったため、**bare `<button>` / 手書き class の control が誰にも見えていなかった**。新 capture を目視した結果、8 つの v2 component dir に **16 個**（ConfigStudio 12 / TreeV2 3 / Governance 1）が残っていた。これを共有 primitive へ寄せて解消:

| primitive | 位置 | 役割 |
|---|---|---|
| `common/TabStrip.tsx`（新規） | Governance 8-tab、Studio scope bar | v2 の tablist 外観を 1 本化。Governance の既存実装を verbatim 抽出（`role=tablist/tab`、`aria-selected/aria-controls`、`${idPrefix}-tab-<id>` / `-panel-<id>` id 規約）。Governance は `idPrefix="gov"` で描画するので **DOM id は byte 単位で不変**（`GovernancePage.test.tsx` の `aria-labelledby === 'gov-tab-overview'` は無改変で通過） |
| `common/NavRail.tsx`（新規） | Studio category rail | 実 `<nav><ul><li>` の縦 slice nav。item は `role=button` を維持（Studio test が `getByRole('button', {name:'Evaluation'})` 等で引くため必須）、選択は `aria-current`、pending-edit Badge は in-button accessory として accessible name を不変に保つ |
| `common/Button`（既存） | 各 action | Save changes / Discard edits / Reload after conflict / Create template / Create draft / Set secret / Resolve & validate / Launch run / Expand all / Restore / Inspector Close |

`styles/components.css` は `.gov-tabs`/`.gov-tab` → `.tab-strip`/`.tab-strip-tab` に改名（**旧 class 名は doc・test・script のどこからも参照されていない**ことを確認済み。参照されていたのは id のみで、その id は不変）し、`:disabled`/hover state と `.nav-rail*` block を追加。値はすべて semantic token（`--border-default` / `--text-muted` / `--text-primary` / `--primary` / `--focus-ring` / `--sp-*` / `--radius-*` / `--fs-sm` / `--t-fast`）で、tint は `color-mix`。**追加された hex literal は 0**（`git diff` の `+` 行に対する機械検査）。

検証時点の実測: 上記 8 dir の `__tests__` 外に残る literal `<button` は **0**。残る 2 件は TreeV2 の test file 内 mock のみで、no-test-change 制約どおり未改変。**なお "before 16" は git から再構成できない** — 8 dir のうち 7 dir は HEAD に 1 file も存在しない未 commit 作業（`git ls-files` で確認）であり、16 は実装 pass の計測値をそのまま記載している。本 record が独立に検証したのは after 側（= 0）である。handler・request 形状・hash navigation 規則・disabled 条件・test 期待値はいずれも無変更。

**新 capture tooling。** `ari-core/ari/viz/frontend/scripts/capture_screenshots.mjs` を新設し、`npm run capture:screenshots`（`package.json` scripts）＋ `playwright ^1.62.0`（devDependency）で駆動する。実 headless Chromium を稼働中の `ari.viz.server` に当て、`(locale, route)` ごとに 1 PNG を `docs/assets/images/<locale>/` へ書き出す。locale は **初回 paint 前**に `addInitScript` で `localStorage.ari_lang` を注入する（i18n provider が bootstrap 中に読み、そこで初めて lazy dictionary chunk を解決するため、後から設定しても間に合わない）。待機 selector は route-render baseline test が pin している **locale 中立な DOM id**（`#page-tree2` 等）を使う（heading は locale 依存で使えない）。Developer Mode は明示的に off にして、通常 operator が見る画面を撮る。viewport 1440×900 / `deviceScaleFactor: 1`。

**静かに capture を壊す headless 前提条件。** これが本作業で最も危険な罠だった。**font が無くても capture は "成功" し、tofu 箱の画像を書き出して exit 0 を返す** — 失敗しないので CI も人も気付かない。必要なのは (1) `npx playwright install chromium`、(2) `libatk-1.0` / `libgbm` / `libXdamage` 等（root 無し host では `LD_LIBRARY_PATH` を conda prefix 等に向ける。不足は `ldd <chrome-headless-shell> | grep "not found"` で判る）、(3) **fonts**: `~/.local/share/fonts` へ **Noto Sans CJK**（無いと ja/zh の capture が全面 tofu）と **Noto Color Emoji**（sidebar icon が emoji）を置き `fc-cache -f`。`fc-match "sans:lang=ja"` で確認したうえで、**必ず ja の画像を 1 枚開いて目視する**こと。この手順は `frontend/scripts/README.md` の "Headless prerequisites" に恒久化した。

**45 枚 set。** 15 route × 3 locale = **45 PNG**、全数が PNG magic 正常・1440×900・非空（機械検査）。3 locale の file 名集合は完全一致。旧 set は 8 枚 × 3 = 24 枚だったので **枚数は 1.9 倍、しかし総量は軽くなった**:

| locale | 旧（8 枚） | 新（15 枚） | 差 |
|---|---|---|---|
| en | 3,045,195 B（2.90 MiB） | 1,951,755 B（1.86 MiB） | −1,093,440 B |
| ja | 2,980,045 B（2.84 MiB） | 1,963,846 B（1.87 MiB） | −1,016,199 B |
| zh | 2,978,269 B（2.84 MiB） | 1,874,106 B（1.79 MiB） | −1,104,163 B |
| **合計** | **9,003,509 B（8.59 MiB）** | **5,789,707 B（5.52 MiB）** | **−3,213,802 B（−3.06 MiB、0.643×）** |

1 枚あたり平均 375,146 B → 128,660 B。旧 set が重かったのは主に `dashboard_ideas.png`（1 枚で ~1.06 MiB）で、viewport 固定と Developer Mode off により解消した。**repo は軽くなった。**

**画像を embed している doc page**（EN / ja / zh の 3 系統とも同一構成、locale ごと 18 embed / 13 unique）:

| Page | embed 数（locale あたり） |
|---|---|
| `getting-started/quickstart.md` | 10 |
| `guides/dashboard.md` | 5 |
| `guides/configuration_studio.md` | 2 |
| `guides/rqgm_gui.md` | 1 |

撮影 15 種のうち **embed 済みは 13 種**。`dashboard_experiments.png` と `dashboard_paperbench.png` の 2 種（× 3 locale = 6 枚）は set の完全性のために撮影してあるが現時点で参照する page が無い、という状態を明示しておく。Governance の 1 枚は **fixture checkpoint**（`20260727120000_rqgm_governance_demo`、`run_id: fixture_12n`）を撮ったもので、`simple_bfts` run では当該 route が capability-state 画面を出すため実 run では撮れない。hash・epoch 番号・各 count はすべてその prop に属し読者の環境とは一致しない旨を 3 言語の `rqgm_gui.md` に明記した。**prop checkpoint は撮影後に削除済み**（`rqgm_state.json` の存在と 2026-07-27 生成を確認したうえで削除。利用者の実 checkpoint `20260507051857_We_propose_an_implementation_of_CSR-form` は無傷であることを削除後の listing で確認）。

**Gate 実測（2026-07-27、本 closeout 後。すべて redirect + `echo $?` の実 exit code、pipe 経由の計測はしていない）**

| Gate | 結果 |
|---|---|
| `pytest ari-core/tests` | RC **0** — **4759 passed / 16 skipped / 2 xfailed / failed 0**（226.76 s） |
| `pytest scripts/tests` | RC **1** — **102 passed / 2 failed**（下記、本作業の範囲外） |
| `npm run typecheck` | RC **0** — 0 errors |
| `npm test` | RC **0** — **221 passed + 1 todo**（34 files） |
| `npm run build` | RC **0** — main **60.93 KiB gzip** |
| `check_dashboard_ux.py --fail-on-regression` | RC **0** |
| `check_directory_policy.py` | RC **0** |
| `check_import_boundaries.py` | RC **0** |
| `check_bundle_budget.py` | RC **0** |
| `check_viz_api_schema.py` | RC **0** |
| `snapshot_contracts.py --surface mcp --check` | RC **0** |
| `python -m ari.viz.v1.openapi --check` | RC **0** — "openapi.json in sync" |
| `check_docs_source_sync.py` | RC **0** |
| `scripts/docs/check_doc_sources.py` | RC **0** |
| `test_i18n_consistency.py` | RC **0** — **9 passed** |

**green ではない gate 1 件（本 closeout の deliverable 外）**: `scripts/tests/test_check_prompts.py` の 2 test（`test_repo_smoke_reproduces_census_and_unique_ids` / `test_repo_smoke_seeded_allowlist_has_zero_new`）が `new == 1` で fail する。原因は **screenshot でも control polish でもなく、`ari-skill-paper/src/server.py` の inline prompt と allowlist の行番号 drift**。allowlist `scripts/quality/check_prompts.allow.yaml` は当該 prompt を `#L1415` として既知登録しているが、実ファイル上の現在位置は **1420**（+5 行）で、line-key 方式のため *NEW* と判定される。当該 prompt block 自体は HEAD（line 1296）と **byte 単位で同一**であり、`git diff` の hunk も 1420 前後には一切掛かっていない（直近の hunk は new-line 1219 で終わり、次は 1662 から）。allowlist の mtime は 2026-07-26 18:36、`server.py` の mtime は 2026-07-27 10:31 で、**後者が先行 subtask により更新されたのに allowlist が再同期されていない**という時系列。clean HEAD worktree では同 test は **7 passed** で green。所有は RQGM branch の paper skill 作業であり、`docs/` にも `frontend/` にも触れない本 closeout の範囲外なので**意図的に手を付けていない**（allowlist header 自身が "Do NOT hand-edit findings away" と定めており、他 subtask の allowlist を無断で書き換えない）。解消は `ari-skill-paper` 側の担当が line 番号を 1415 → 1420 に再同期するだけで済む。

本 closeout の変更範囲: `docs/assets/images/{en,ja,zh}/**`（45 PNG）、embed 側 doc 12 file、`frontend/scripts/{capture_screenshots.mjs,README.md}`、`frontend/package.json`（script + devDependency）、`frontend/src/components/common/{TabStrip,NavRail}.tsx` と `common/index.ts`、`frontend/src/styles/components.css`、および ConfigStudio / TreeV2 / Governance の control 置換。**endpoint・DTO・checkpoint 形式・test はいずれも無変更。**

## ADR-09 実装記録（2026-07-27）

**ADR-09（accepted 2026-07-27）= 「GUI に RQGM トグルを置かない」という v1 決定の supersede**。task 06 の residual であった "governance step — ADR-09 user-gated deferral" を **deferred ではなく delivered** として閉じる。本 record の全数値は実装作業とは別 pass で再実測したものであり、各 claim は task summary ではなく一次資料（`ari/config/field_registry.py`、`ari/config/resolver.py`、`ari/viz/v1/{config_api,launch,router,dto}.py`、`frontend/src/components/ConfigStudio/*`、実サーバーへの HTTP smoke）に突き合わせて確認した。

### 決定と、開いたもの／意図的に閉じたままのもの

開いたのは **ちょうど 4 leaf**。しかも「1 leaf ずつ 4 個」ではなく、**2 つの直交する paired intent** である:

| Intent | mode leaf | interlock twin | active 値 | default（fallback）値 |
|---|---|---|---|---|
| 実行モード | `ari.mode` | `rqgm.enabled` | `ari_rqgm` + `true` | `simple_bfts` + `false` |
| ペーパーモード | `paper.mode` | `rqgm.paper.enabled` | `rqgm_archive` + `true` | `linear` + `false` |

pair 定数の**単一の源**は `field_registry.MODE_INTERLOCK_PAIRS`（`config/resolver.INTERLOCK_PAIRS` は従来の重複リテラルをやめ、この alias になった）。`MODE_SELECTION_PATHS` はその union（4 path）。frontend 側は `ConfigStudio/modeIntents.ts` が同じ形を mirror する。

**意図的に file-only のまま残したもの**: 残り **96** の `rqgm.*` governance/tuning leaf（epoch・kernel・governance・adversarial・budget・paper-archive tuning）。これらは Studio では**実効値つきの read-only 表示**（`ConfigBrowser/ConfigReadOnlyTable` を共有）に留まり、launch では従来どおり 400 `mode_locked` で拒否する。カーブアウトは**減算的**に構成した — `locked_launch_paths()` = registry 由来集合（`Execution mode` ∪ `rqgm.*`）**マイナス** `MODE_SELECTION_PATHS` — ので、書き込み面をこれ以上広げるには**その 1 集合を編集する以外に方法がない**。実測: registry 144 leaf / `Execution mode` 4 / `rqgm.*` 非 mode 96 / locked **100 → 96**。

「モードを選ぶことは governance mutation ではない」という線引きも保った: `/api/v1/runs/{run_id}/rqgm/*` は**全 route が GET のまま**（非 GET 0 件を機械確認）、Governance workspace は read-only、registry/transition の直接編集経路は存在しない。INDEX §Global invariants の read-only-governance invariant は**弱まっていない**。

### half-set pair の拒否 — 新しい閉じた reason 1 種

`PATCH_REASONS` は閉じた語彙のまま **6 → 7** に増え、`mode_interlock_mismatch` が加わった（`validate_patch` の docstring と `dto.DraftValidationErrorV1`、`docs/reference/configuration.md` の 3 言語に反映）。判定は `field_registry.validate_mode_interlocks(values)`: pair のどちらかの key が現れたら**両方が現れ、かつ一致していなければならない**。error は 1 pair につき 1 件、**mode path を key** にし、`expected` に 2 つの整合な選択肢を逐語で載せる。

決定的に重要な点として、この検査は **merged document values** に対して走り、raw patch には走らない（`config_api._validate_mode_pairs(effective)`）。したがって**「2 手に分けた編集でも、終端が整合していれば受理される」**。適用点は run-template create/PATCH、run-draft create/PATCH、および launch。launch では `_resolve_draft_manifest` が新たに返す `run_scope_values`（template+draft の merge。project scope は mode path を `not_project_scope` で弾くため effective に到達しえず、除外して正しい）を `_draft_validation_errors` に渡し、既に `mode_interlock_mismatch` として報告した pair については resolver 由来の `interlock_mismatch` を**抑止**する — 1 つの欠陥は 1 回だけ報告する。`POST /run-drafts/{id}/validate` の意味論は**据置き**（既存 API 契約どおり `interlock_mismatch`）。

### materialization — 非既定の選択は「両方」書く。既定は「何も」書かない

非既定の選択は 2 通りに実体化する:

1. **per-checkpoint `workflow.yaml` コピー**へ最小の `ari:` / `rqgm:` / `paper:` ブロックを merge（`_merge_mode_blocks`）。**同梱ファイルには決して書かない**（caller が先に CoW seed 済み）。top-level key が未在なら**テキスト追記**なので、コメントを含む既存の全バイトが残る。既在の場合のみ load→deep-merge→dump の round trip に落ち、未知 key は保つ。
2. **env**（`_mode_env`）: `ARI_MODE` / `ARI_RQGM_ENABLED` / `ARI_PAPER_MODE` / `ARI_RQGM_PAPER_ENABLED` — 文書化済みの `ENV_OVERRIDES` 名そのもの（spawn 先 CLI の `apply_rqgm_env_overrides` / `apply_paper_env_overrides` が読む名前）。

「両方、さもなくばどちらも」にした理由は ADR-09 §Alternatives のとおり: env だけだとチェックポイントが自己記述的でなくなり、後段（`{ckpt}/workflow.yaml` を読む paper pipeline）が探索フェーズと食い違いうる。

**既定パスが byte-identical であることの機構**: export も merge も **value-gated であって provenance-gated ではない**（`_mode_selection(manifest)`）。4 つの mode leaf は汎用 provenance walk（`_env_overrides_from_manifest`）から**構造的に除外**してある。ゆえに「何も選ばない draft」と「`simple_bfts` + `linear` を明示的に選び直した draft」は**どちらも** `{}` に解決し、ブロックは書かれず env も出ない。

**resume は無変更**: `{ckpt}/rqgm_state.json` が引き続き勝つ（`reconcile_resume_mode`、downgrade-only）。GUI のどの経路もこのファイルを書かない。

### 表示規則 — requested ではなく resolved を出す

launch review が示すのは **resolve-config manifest から読んだ解決後のモード**であって、draft の生の選択ではない（`LaunchPanel.tsx` の `modeReview`）。runtime resolver が warn-and-fall-back したとき（例: env 層が document 上は整合している pair を壊した）、review は `requested → resolved` を目立つ alert として描き、**resolver の警告を逐語で**添える。「不採用の要求」は 2 経路で検出する: (a) mode が fell back した（resolver が leaf を書き換え、要求を `rejected_override` に残す）、(b) interlock だけが立っていて master switch が伴わない（警告のみで書き換えなし）。黙ってフォールバック run を開始することはない。

provenance/preview 側は**コード変更不要**だった: resolver は既に mode leaf を `draft`/`template` provenance で見せ、解決値を載せた warn+fallback 警告を出す。`resolved_config.json`（launch 時に書かれる）と `/resolve-config` の双方がこれを運ぶ。再導出せず**テストで固定**した。

### 三言語文書

| Page | 内容 |
|---|---|
| `guides/execution_modes.md` | `## Selecting the mode from the GUI` を新設。§Limitations (v1) の「no GUI toggle」主張を撤回（`--mode` CLI flag が無い件は**据置き**）。supersede 範囲を「新規 run に限る」と明示 |
| `guides/configuration_studio.md` / `guides/rqgm_gui.md` / `guides/dashboard.md` / `reference/configuration.md` | ロックが mode 選択まで覆うと書いていた箇所を更新。`PATCH_REASONS` 7 種を反映 |
| `guides/migration.md` | **MN-12**（before/after/why/rollback）を新設。MN-10 の「GUI からの mode 選択は未決」記述に *(Superseded by MN-12)* 注記。MN-11 の review 要約に解決済みモードを追加。rollback lever 節に「MN-12 にレバーは無いが必要も無い」を追記 |

**本 verification pass で検出・修正した parity 欠落**: `docs/{ja,zh}/guides/migration.md` が **MN-12 節を丸ごと欠いていた**（EN のみ更新済み）。併せて同 2 file の (a) MN-10 の陳腐化した「未決の判断」記述、(b) MN-11 review 要約の解決済みモード、(c) rollback lever 節の MN-12 文が欠けていた。4 点とも ja/zh に反映し、MN heading の 3 言語一致（MN-1…MN-12）と `ADR-09` 言及数 1/1/1 を機械確認した。

### END-TO-END smoke（実サーバー、unit test だけを信用しない）

`ari.viz.server` を空き port（34007 / 34009）で**実起動**し、隔離 workspace（`ARI_ROOT` を scratch に向け、`gui_store/` と `checkpoints/` を新規生成）に対して HTTP を叩いた。LLM 駆動の subprocess を起こさないため、`PATH` 先頭に `python3` の stub を置いて `python3 -m ari.cli run ...` を捕捉し、**argv と export された env を記録して exit 0** させた（launch 経路 `_materialize` → `_merge_mode_blocks` → `_build_proc_env` は**本物が走る**）。**58 assertion（52 call site、うち 2 site が 4 ケース loop）全通過、failure 0**。

| # | 検証 | 実測結果 |
|---|---|---|
| A | 既定（`simple_bfts`+`linear`）を**明示的に選び直した** draft で launch | checkpoint の `workflow.yaml` が同梱 seed と **byte-identical**、`ari:`/`rqgm:`/`paper:` ブロック 0、mode env **0 個**（`ARI_CHECKPOINT_DIR` のみ）、`rqgm_state.json` 未生成 |
| B | draft 作成（goal のみ）→ PATCH で `ari.mode=ari_rqgm` + `rqgm.enabled=true` → resolve-config → validate → launch | PATCH 200。manifest は `ari.mode='ari_rqgm'` / `rqgm.enabled=True`、**provenance 双方とも `draft`**、`paper.mode` は `default` の `linear` のまま、warnings `[]`、digest `sha256:e7f2ec…`。validate `valid:true` / errors `[]` |
| B | launch 後の materialization | `workflow.yaml` は seed と差分あり、かつ**先頭が seed 全バイトのまま**（追記であることの証明）＋ ADR-09 banner コメント。`ari.mode: ari_rqgm` / `rqgm.enabled: true` を搭載、`paper:` ブロックは**無し**。env は `ARI_MODE=ari_rqgm` `ARI_RQGM_ENABLED=1` のみ（paper 系は出ない）。`resolved_config.json` は draft provenance と minted `run_id` を保持 |
| B | 冪等 replay | 同一 `idempotency_key` の再 POST は**同じ `run_id`** を `idempotent_replay:true` で返し、**spawn 0**（stub 記録数が増えない） |
| C | paper mode の直交性 | `paper.mode: rqgm_archive` / `rqgm.paper.enabled: true` を `workflow.yaml` に搭載、env は `ARI_PAPER_MODE=rqgm_archive` `ARI_RQGM_PAPER_ENABLED=1` のみ。**実行モード側の env は出ない** |
| D | 不整合 / half-set pair（4 形 + PATCH 1 形） | すべて **400 `mode_interlock_mismatch`**。error は mode path を key にし、`expected` に 2 つの整合な選択肢。既に整合していた draft を PATCH で**壊す**操作も 400 |
| E | カーブアウトが 4 leaf ちょうどであること | 非 mode の `rqgm.epoch.nodes_per_epoch` を持つ draft は作成でき（scope 違反ではない）、**launch で 400 `mode_locked`**（メッセージが ADR-09 のカーブアウト範囲を名指しする）かつ **spawn 0**。project scope への mode path PATCH は従来どおり `not_project_scope` |
| F | template が intent を運ぶ | pair を持つ template にリンクした draft は manifest で `ari_rqgm` / **provenance `template`** に解決し、launch で `workflow.yaml` と env の両方に実体化 |

サーバー停止後、**両 log に traceback / exception / error 行は 0**（内容は websockets の DeprecationWarning 2 行のみ）。port 34007 / 34009 とも解放を確認。

### simple_bfts invariant の証明

該当テストは **`ari-core/tests/test_gui_v1_mode_selection.py::TestDefaultPathUnchanged`** で、実在し green:

```
tests/test_gui_v1_mode_selection.py::TestDefaultPathUnchanged::test_baseline_and_explicit_defaults_are_indistinguishable PASSED [ 50%]
tests/test_gui_v1_mode_selection.py::TestDefaultPathUnchanged::test_default_path_writes_no_rqgm_state PASSED [100%]
============================== 2 passed in 0.67s ===============================
```

前者は「ADR-09 以前の draft（mode leaf を持てなかった）」と「4 key すべてを既定値で明示する ADR-09 GUI」の 2 launch を比較し、(1) `workflow.yaml` が同梱 seed と byte-identical、(2) mode env 双方 0、(3) 生成 artifact 集合が同一、(4) manifest の values / digest / warnings が同一、(5) **差分は 4 mode leaf の provenance 層（`default` vs `draft`）だけ**、(6) `launch_config.json` が draft identity を除いて同一 — の 6 点を固定する。後者は GUI が `rqgm_state.json` を書かないこと（P5 absence-is-default）を固定する。

### Gate 実測（2026-07-27）

| Gate | 結果 |
|---|---|
| `pytest ari-core/tests`（`--ignore=tests/skills`） | RC **0** — **4758 passed / 16 skipped / 2 xfailed**（224.54 s）。Wave 6b の 4723 から **+35** = mode selection 34 + `test_governance_fields_stay_locked_after_adr09` 1 |
| `pytest scripts/tests` | RC **0** — **104 passed**（45.60 s） |
| `npm run typecheck` | RC **0** — 0 errors |
| `npm test` | RC **0** — **221 passed + 1 todo**（34 files）。Wave 6b の 212+1 / 33 files から **+9 test / +1 file** = `ConfigStudioExecutionMode.test.tsx`（単体で 9 passed） |
| `npm run build` | RC **0** — main **60.90 KiB gzip** |
| `check_viz_api_schema` | RC **0**（`--fail-on-regression` 併せ RC 0） |
| `snapshot_contracts --check` | RC **0** — "contract snapshots in sync: public, cli, mcp, viz" |
| `check_bundle_budget` | RC **0**（`--fail-on-regression` 併せ RC 0） |
| `check_dashboard_ux --fail-on-regression` | RC **0** |
| `check_directory_policy` | RC **0** — errors 0 / new 0 |
| `check_import_boundaries` | RC **0** — new 0 |
| `python -m ari.viz.v1.openapi --check` | RC **0** — "openapi.json in sync" |
| `check_docs_source_sync` | RC **0** — "no net-new trunk-state staleness (43 known/allowlisted)" |
| `scripts/docs/check_doc_sources.py` | RC **0** — 231 docs / 0 error / 0 warning |
| 補助 checker | `check_prompts` / `check_dead_code --check` / `check_ref_coupling` / `check_i18n_js` / `check_readme_parity` / `check_report_cochange` / `check_site_i18n` / `check_translation_freshness` すべて RC **0**。CJK gate `test_i18n_consistency.py` **9 passed** |

**readme_sync — gui 所有の新規 drift は 0**: `readme_sync.py --check` は RC 1 だが、内訳は **12 README / 275 entry** で、Wave 6b closeout 時点の「RQGM 所有の残余」と**件数・README 別内訳ともに完全一致**する（92 `ari-core/ari` / 90 `ari-core/tests` / 21 `ari/schemas` / 19×3 `report/shared/**` / 7 `scripts` / 4 `ari/prompts` / 1×4 `ari/cli`・`ari/protocols`・`ari-core/config`・`ari-skill-paper/tests`）。drift entry に **gui / viz / frontend / config_api / field_registry / resolver / launch 形のものは 1 件も無い**。ADR-09 が触れた側は既に掲載済みであることも個別に確認した（`ari-core/tests/README.md` の `test_gui_v1_mode_selection.py`、`ari/config/README.md` の `field_registry.py` / `resolver.py`、`ari/viz/README.md` の `v1/`）。残作業の所有は従来どおり RQGM branch。

**advisory（本 record の deliverable 外）**: `scripts/docs/check_doc_links.py` RC 1 / 12 件は Wave 6b と同一の `docs/{,ja/,zh/}index.md` の `report/*.pdf`（site assemble 時生成）と site-absolute `/ARI/`。当該行は main にも存在し本 branch で未変更（`git show main:docs/index.md` で確認）。CI では `continue-on-error: true` の advisory。

### ADR-09 実装記録 判定: 通過（2026-07-27）

task 06 residual の "governance step — ADR-09 user-gated deferral" は **delivered**。INDEX の残余追跡もこれを反映済み（deferral ではなく delivered として記載）。checkpoint 形式の変更は無く（非既定 run の `workflow.yaml` コピー内追加ブロックのみで、旧 ARI はこれを無視する）、resume 意味論も無変更。kill-switch は導入していない — 「off」とは既定の選択のままにすることであり、それは byte-identical な launch を生む。
