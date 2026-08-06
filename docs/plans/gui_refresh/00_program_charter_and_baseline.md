# 00 — Program Charter and Current-State Baseline

> Status: planned  
> Dependencies: none  
> Gate: G0 — Contract freeze

## Purpose

ARI GUI 全面刷新の境界、現状基準、互換契約、目標アーキテクチャを固定する。後続タスクが別々の「正しい GUI」を作らないための program charter とする。

## Scope

- `ari-core/ari/viz/` の backend、frontend、realtime、artifact access。
- Settings、Wizard、Workflow、Monitor、Tree、Ideas、Results、PaperBench、RQGM の画面体験。
- Pydantic/YAML/profile/environment/project/checkpoint に分散する設定解決。
- project、run、checkpoint、artifact、RQGM epoch/policy/transition の情報モデル。
- security、accessibility、i18n、performance、migration、documentation。

## Non-goals

- RQGM アルゴリズム自体や研究スコアの定義を GUI の都合で変更しない。
- checkpoint を database 必須形式へ一括変換しない。
- desktop app、mobile native app、multi-tenant SaaS を同時に構築しない。
- 全画面を一度に書き直して切り替える big-bang release は行わない。
- visual polish のためだけに既存 API や CLI の公開契約を破壊しない。

## Current-state findings

| Area | Current state | Structural problem |
|---|---|---|
| Routing | `App.tsx` の `PAGE_MAP`（hash router、router library なし）と Sidebar `NAV_ITEMS` が route/nav を別管理。未知 route は Home へ silent fallback | navigation、breadcrumb、feature flag が drift する |
| State | `AppContext` が remote data（`/state` 5 秒 polling、checkpoints、tree WS）と UI state を保持 | cache、abort、retry、run isolation がない |
| Run selection | server-global active checkpoint（`viz/state.py` の module globals）を共有。server 起動時は mtime 最新の checkpoint を自動復元 | multi-tab/multi-user で別 run の状態が混線する |
| Realtime | `/state` の 5 秒 polling と tree 専用 WebSocket（HTTP port+1、単一 channel、mtime watcher 1 秒駆動）。`GET /api/logs` と PaperBench job log は既に SSE | payload が肥大化し、RQGM/log/artifact を拡張しにくい。port+1 WS は proxy 経由で成立しない |
| Settings | component-local state と手組み flat POST。契約は非対称（POST は 24 key、GET は 27 key で key 集合も不一致） | config schema、既定値、表示項目が重複する |
| Launch | Wizard payload を env と workflow へ個別変換。`_status` を 200 body に埋める応答、enum 非通過値の logged-drop | source、validation、resume rules を説明できない |
| Config | Pydantic field defaults、workflow.yaml、profile（4 key のみ merge）、`ARI_*` env、project settings、checkpoint に分散。GUI settings は env 翻訳経由でのみ run へ届く | 実効値と由来がユーザーから見えない |
| RQGM | viz backend/frontend に RQGM の surface が一切ない（grep 0 件）。artifact は checkpoint に揃っている | epoch、registry、transition、score rewrite を追跡できない |
| Security | 全 interface bind（dual-stack）、認証・session・CSRF なし、CORS `*`、`GET /api/env-keys` が secret 平文と source path を返す | remote bind 時の認証、secret、dangerous operation 境界が不足 |
| Service seam | `services/` へ `/state` builder、file path guard、`.env` parse のみ抽出済み（contract snapshot tests が固定） | 残る business logic は `api_*.py` handler に密結合 |
| Quality | unit test、contract snapshot、`check_viz_api_schema`/`check_dashboard_ux` allowlist はあるが E2E、visual、a11y、performance gate が弱い | 全面刷新時の回帰を客観的に止められない |

既知の dead/stale seam も G0 で fixture/issue 化する: `api_wizard.py` の `WIZARD_ROUTES` は dispatcher に未配線の shim、`viz/__init__.py` docstring の「FastAPI/uvicorn」記述は誤り（実体は stdlib `http.server` + `websockets`）、`index.html` は npm の d3 に加えて CDN `<script>` を二重 load している。

## Existing touchpoints to preserve

- `ari-core/ari/viz/frontend/src/App.tsx`
- `ari-core/ari/viz/frontend/src/context/AppContext.tsx`
- `ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx`
- `ari-core/ari/viz/frontend/src/components/Wizard/WizardPage.tsx`
- `ari-core/ari/viz/api_experiment.py`
- `ari-core/ari/viz/api_settings.py`
- `ari-core/ari/viz/routes.py`
- `ari-core/ari/viz/server.py`
- `ari-core/ari/viz/state.py`
- `ari-core/ari/viz/state_sync.py`
- `ari-core/ari/viz/tree_view.py`
- `ari-core/ari/viz/services/`（部分抽出済み service seam）
- `ari-core/ari/schemas/viz_*.schema.json`（既存の viz payload 契約）
- `ari-core/ari/config/__init__.py`
- `ari-core/ari/configs/defaults.yaml`
- `ari-core/config/workflow.yaml`
- `scripts/snapshot_contracts.py` と `scripts/check_viz_api_schema.py`（allowlist 含む既存契約固定資産）

## Target domain model

```text
Installation
├── UserPreference
├── SecretReference
├── Project
│   ├── RunTemplate
│   ├── WorkflowDefinition
│   └── Run
│       ├── ResolvedConfigSnapshot
│       ├── Checkpoint
│       ├── Artifact
│       ├── ResearchState
│       └── GovernanceState
│           ├── Epoch
│           ├── PolicyVersion
│           ├── RegistryNode
│           ├── Transition
│           └── ScoreObservation
```

- 現行実装では project ≡ run ≡ checkpoint（`YYYYMMDDHHMMSS_<slug>` の directory 名がそのまま ID。7 つの search base を scan して発見）。`Project` と `Run` の分離は greenfield であり、初期実装は「暗黙の default project」への mapping から始めてよい（ADR 対象）。
- `Project` は再利用可能な設定と workflow の管理境界。
- `Run` は一回の実行と lifecycle の境界。URL/API で必ず `run_id` を明示する。sub-experiment lineage（`meta.json` の `parent_run_id`、`recursion_depth`、`inherit_idea_index`）は Run 間の関係として model 化する。
- `Checkpoint` は run の保存点であり、別 run を意味しない場合もある。
- `ResolvedConfigSnapshot` は launch/resume 時点の実効設定と provenance の不変記録。
- `ResearchState` は探索・生成・評価の進捗。
- `GovernanceState` は RQGM の制度状態。研究成功/失敗と独立に表現する。

## Target architecture

```text
React application shell
  ├── route registry and run context
  ├── feature workspaces
  ├── generated API client and query cache
  ├── realtime invalidation client
  └── shared design/visualization system
                 │
                 ▼
Versioned HTTP API + same-origin SSE
  ├── transport adapters
  ├── application services
  ├── config resolver and policy
  ├── read-model projectors
  └── process supervisor
                 │
                 ▼
Filesystem checkpoints, JSON/JSONL artifacts, workflow files, secret providers
```

既存 unversioned endpoint は compatibility facade とし、新旧双方が同じ application service を呼ぶ。filesystem artifact は当面 source of truth のまま維持し、GUI 用 index/read model は再構築可能な派生データとする。

## Priority classification

### P0 — Safety and identity

- global active checkpoint を run-scoped identity へ置換する。
- remote bind、CORS、authentication、dangerous operation、secret response を監査する。
- launch/resume の実効設定を不変 snapshot として説明可能にする。

### P1 — Truth and comprehension

- config の effective value、source、scope、適用時点を表示する。
- RQGM transition、policy change、score rewrite、frontier repair を因果順に表示する。
- research state と governance state を別の status model で扱う。

### P2 — Platform and maintainability

- route registry、feature slices、typed API、query cache、SSE、design system を導入する。
- Settings/Wizard/Workflow の重複 schema と local state を削減する。

### P3 — Product quality

- responsive、a11y、i18n、visual regression、performance budget、diagnostics を release gate にする。

## Success measures

- schema に登録された表示可能な config leaf の 100% が GUI 検索または「非表示理由」から到達できる。
- run detail の全 API と realtime event が明示的 `run_id` を持つ。
- secret の平文が frontend response、manifest、log、telemetry に 0 件である。
- RQGM の全 committed score rewrite が old/new policy、before/after、affected node、reason、source event へ辿れる。
- 旧 hash URL、旧 API、旧 checkpoint、`simple_bfts` の compatibility suite が切替期間中 green である。
- 主要 journey を mouse なしで完了でき、三言語 key parity と WCAG 2.2 AA の自動/手動 gate を通る。
- 固定 large-run fixture で JSONL 全読込や無制限 DOM render が発生しない。

## Compatibility register

| Contract | Migration rule |
|---|---|
| Hash routes | 旧 URL を redirect または compatibility route として保持 |
| Unversioned REST | `/api/v1` と並行運転し、削除は release policy に従う |
| Settings POST | 24-key payload（と 27-key GET の非対称 shape）を legacy adapter で固定 |
| 既存 SSE | `GET /api/logs` と PaperBench job-log SSE（`Last-Event-ID` 対応）の契約を新 event stream 統合まで維持 |
| Sub-experiments | `meta.json` disk-authoritative scan と lineage guard（max depth、`parent_terminated`）を維持 |
| Workflow YAML | unknown/additive key を失わず round-trip |
| Checkpoint | UI 利用のための必須 migration を要求しない |
| `simple_bfts` | 実行、artifact、resume の identity test を維持 |
| RQGM resume | checkpoint の mode と policy history を優先し、mid-run upgrade を禁止 |
| WebSocket | SSE 安定後まで tree update contract を維持 |
| i18n | 日本語・英語・中国語を同一変更で更新 |

## Decisions to record as ADRs

- Router と frontend server-state library の採用。
- `/api/v1` transport と OpenAPI client generation。
- SSE と legacy WebSocket の共存期間。
- config schema metadata の格納方式と versioning。
- secret provider と authentication mode。
- read-model index の保存場所、再構築、破損時 recovery。
- feature flag、rollback、legacy removal policy。

## Risks and controls

- **二重の正本**: resolver を先に共通化し、UI と CLI が同じ結果を使う。
- **長期二重実装**: 各 feature flag に owner、removal gate、期限を持たせる。
- **artifact 仕様の推測**: committed source artifact と明示 event だけから read model を生成する。
- **可視化の誤解**: status、score、penalty、policy comparability の表示規則を contract test 化する。
- **性能退行**: representative fixture と budget を G0 で固定する。
- **既存 user workflow の破壊**: telemetry と opt-in rollout を用い、最低 1 minor は rollback 可能にする。

## Deliverables

- current API/route/settings/checkpoint golden fixtures。
- target domain glossary と compatibility register。
- reference small/medium/large run fixture。
- ADR backlog と program risk register。
- G0 review record。

## Completion criteria

- 現行 contract fixtures が CI で再現可能である。
- domain entity、ID、ownership、source of truth が曖昧なく定義されている。
- P0 risk に owner と blocking gate が割り当てられている。
- 後続 plan が同じ compatibility register を参照している。

## Deletion criteria

- program 全体が G6 を通過し、baseline の内容を architecture/reference/migration docs へ移管済みである。

## Delete-after checklist

- [ ] golden fixtures の保守先が test suite に移った。
- [ ] glossary と architecture を恒久文書へ移した。
- [ ] compatibility register を release/migration docs へ移した。
- [ ] main merge と CI green を確認した。
- [ ] `INDEX.md` を更新した。

