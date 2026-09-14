# 01 — Information Architecture and User Journeys

> Status: planned  
> Dependencies: 00  
> Gate: G1 — Experience contract

## Purpose

画面を既存 component 単位ではなく、ユーザーが研究を開始し、実行を追跡し、成果と RQGM の判断を説明する journey 単位へ再編する。

## Scope

- navigation hierarchy、route taxonomy、breadcrumb、global context bar。
- 初心者、研究者、HPC 運用者、監査者、開発者の主要 journey。
- progressive disclosure、用語、empty/loading/error/degraded state。
- RQGM 有無、running/completed/resumed、legacy checkpoint の conditional navigation。

## Non-goals

- component の視覚仕様や token 詳細は task 02 で定義する。
- router 実装、query state、API は task 03/04 で定義する。
- RQGM の各 chart と DTO は task 08 で定義する。

## Personas and jobs

| Persona | Primary job | Required depth |
|---|---|---|
| 初回利用者 | project を作り、安全な既定値で run を開始する | P1–P2 |
| 研究者 | 仮説、探索木、評価、成果、再現条件を理解する | P1–P4 |
| HPC 運用者 | resource、queue、process、log、failure を診断する | P1–P5 |
| RQGM 監査者 | policy、transition、score rewrite、根拠 artifact を追う | P1–P5 |
| 開発者 | raw artifact、API、event、config source を調査する | P1–P5 |

同じ画面で深度を変え、persona ごとに別アプリを作らない。

## Navigation model

```text
Projects
├── Home
├── Experiments / Runs
└── New Run

Research (run context)
├── Overview / Live Monitor
├── Search Tree
├── Ideas and Claims
└── Evidence and Results (EAR / publish lineage を含む)

Governance (RQGM run only)
├── Overview
├── Epochs
├── Institution / Registry
├── Accountability
├── Score Lineage
├── Evolution and Repair
└── Paper Archive

Configure
├── Configuration Studio
├── Workflow Studio
├── Run Templates
├── Evaluation Assets (rubrics / few-shot)
└── Installation and Secrets

Operations
├── Processes and Resources (GPU monitor を含む)
├── Services (Letta memory、container、SSH)
├── Logs and Artifacts
└── Diagnostics and Danger

PaperBench (cross-run benchmark surface)
├── Paper Registry / Import
├── Benchmark Runs
└── Benchmark Results
```

`Governance` は RQGM capability がある run でのみ主 navigation に出す。capability は `{checkpoint}/rqgm_state.json` の存在と `mode` で判定する（不在 = pure `simple_bfts`）。非 RQGM run では route を消すのではなく、理由と activation 条件を説明する capability state を返す。PaperBench は run-scoped でない独立 benchmark surface（paper registry + job）として維持し、Research の Results と混同しない。sub-experiment lineage（parent run → child run、継承 idea）は Projects の run list と run Overview の両方から辿れるようにする。

## Route model

| Canonical route | Responsibility | Legacy behavior |
|---|---|---|
| `#/projects` | project portfolio | old `#/home` から redirect |
| `#/projects/:projectId/runs` | run list、comparison、sub-experiment lineage | `#/experiments`（checkpoint 一覧 + lineage 列）を adapter |
| `#/runs/:runId/overview` | state、phase、cost、next action | `#/monitor` と `#/home` の情報を整理 |
| `#/runs/:runId/tree` | search tree と causal selection | `#/tree` を mount 可能 |
| `#/runs/:runId/ideas` | idea/claim/evidence relation | `#/idea` を mount 可能 |
| `#/runs/:runId/results` | outputs、metrics、EAR/publish lineage | `#/results` を mount 可能 |
| `#/runs/:runId/governance/*` | RQGM workspace | new capability（legacy 対応物なし） |
| `#/new` | draft 作成と launch | `#/new → #/wizard` alias を維持 |
| `#/workflows/:workflowId` | versioned workflow editing | `#/workflow` を mount 可能 |
| `#/settings/*` | preferences、installation、secrets | `#/settings` adapter を維持 |
| `#/operations` | process、resource、diagnostics | GPU monitor、memory health、diagnostics を集約 |
| `#/paperbench/*` | paper registry、benchmark run、results | 既存 `#/paperbench{,/import,/run,/results?job=}` を維持 |

現行 router は未知 hash を Home へ silent fallback させる。新 route registry では未知 route と missing context を明示的な resolution screen にする。

URL を navigation state の正本にし、選択中 run、tab、filter、node/transition selection を可能な範囲で deep-link 化する。

## Global shell context

全 run-scoped screen で以下を常時表示する。

- project と run identity。
- run lifecycle: draft、queued、running、paused、completed、failed、cancelled。
- current research phase と最終更新時刻。
- exploration 側の execution mode（`ari.mode` ∈ `simple_bfts`/`ari_rqgm`）と paper mode（`paper.mode` ∈ `linear`/`rqgm_archive`）。二軸は直交（2×2 すべて有効）で、曖昧な `mode` 一語を使わない。
- RQGM capability、current epoch、current policy hash。
- resource/cost summary と alert count。
- connection state: live、reconnecting、snapshot-only、offline。

global shell は詳細 score や raw log を抱えず、現在地と異常の入口だけを提供する。

## Progressive disclosure

| Level | Content | Default visibility |
|---|---|---|
| P1 | run state、current phase、blocked reason、next action | 常時 |
| P2 | score summary、tree、epoch、主要 artifact | 常時 |
| P3 | evidence、transition reason、config diff、resource details | 1 click |
| P4 | trace、log、per-node lineage、raw event link | 1–2 clicks |
| P5 | raw JSON/YAML、internal IDs、debug payload | Developer Mode + permission |

Developer Mode は表示密度を変えるだけで、authorization boundary として扱わない。

## Core user journeys

### Create and launch a run

1. project を選択または作成する。
2. run template、workflow、execution environment を選ぶ。
3. schema-driven form で変更する。
4. validation、cost/resource impact、RQGM interlock を確認する。
5. effective config diff と secret readiness を確認する。
6. immutable launch summary を承認して起動する。
7. new `run_id` の Overview へ遷移する。

### Resume a run

1. checkpoint と snapshot digest を確認する。
2. immutable、resume-mutable、ignored override を区別する。
3. execution/paper mode は checkpoint 値（`rqgm_state.json` の `mode`、`mode_source`、`switch_journal`）を read-only 表示する。resume 時は persisted mode が config/env より優先される（downgrade-only）。
4. 許可された resource override だけを適用する。
5. resume lineage を新 event として残す。

### Explain a score rewrite

1. Score Lineage で node、epoch、policy hash を選ぶ。
2. base score、validated penalty、final score、rank を確認する。
3. old/new policy parameter diff と transition reason を確認する。
4. recomputed、invalidated、removed、frontier changed を区別する。
5. kernel verdict、audit event、source artifact へ deep-link する。
6. 異なる policy 間の値が直接比較不可なら UI が警告し、facet 表示する。

### Diagnose a stalled run

1. Overview で research phase と governance stage を別々に確認する。
2. event freshness、process、queue、resource、latest artifact を確認する。
3. filtered logs と failure envelope を開く。
4. recovery action の影響範囲を確認する。
5. destructive action は server-issued confirmation challenge を経る。

### Reproduce a result

1. result から evidence、node、workflow revision へ遡る。
2. resolved config snapshot と source provenance を確認する。
3. secret は reference/readiness のみ確認する。
4. compatible run template として clone する。
5. changed fields と non-reproducible dependencies を launch 前に表示する。

## Terminology contract

| Avoid | Use | Reason |
|---|---|---|
| Mode | Execution environment / Execution mode (`ari.mode`) / Paper mode (`paper.mode`) | 意味の衝突を解消 |
| Success | Research completed / Governance accepted | 異なる状態を分離 |
| Attack score | Raw attack / Validated penalty | penalty 適用条件を明示 |
| Deleted | Stale / Invalidated / Removed | logical state と物理削除を分離 |
| Current score | Score under policy `<hash>` | policy 依存性を明示 |
| Settings | Preferences / Template / Effective config / Secret | scope を明示 |

glossary には GUI label ↔ config key ↔ 既存 docs 用語の三者対応を含める。特に `docs/guides/execution_modes.md` は `ari.mode` を「execution mode」と呼ぶため、GUI が「Execution environment（local/HPC/cloud）」を別概念として導入する際は両者の区別を明文化し、docs 側と同一 glossary を共有する。registry component の lifecycle 状態（candidate/…/active/retired/banned）と tree node の score 状態（stale/invalidated/removed）も別語彙として扱う。

## Empty and degraded states

- no project、no run、no artifact、RQGM disabled、legacy checkpoint、index rebuilding を別 state とする。
- SSE 切断時は「run stopped」と推測せず、last known snapshot と freshness を表示する。
- artifact parse failure は run failure と混同せず、対象 file と recovery を表示する。
- governance stage 不明時は推測した stage を表示せず `unknown` と source freshness を示す。

## Validation

- 各 persona の task analysis と clickable prototype review。
- legacy route deep-link と browser back/forward の journey test。
- RQGM なし/あり、running/completed/resumed、legacy/corrupt checkpoint の state matrix。
- navigation 名称、heading、breadcrumb の三言語 review。
- keyboard-only と screen-reader landmark walkthrough。

## Completion criteria

- 全 canonical route に owner、responsibility、required context、capability rule がある。
- 主要 4 journey が prototype で迷わず完了できる。
- `mode`、`score`、`success`、`deleted` の曖昧語が glossary に従う。
- old route の redirect/mount 方針が compatibility register に反映されている。

## Deletion criteria

- route、navigation、glossary、journey が product/architecture docs と automated tests に移管済みである。

## Delete-after checklist

- [ ] route reference と user guide を恒久文書へ移した。
- [ ] journey を E2E test 名へ対応付けた。
- [ ] 用語を i18n glossary へ移した。
- [ ] main merge と CI green を確認した。
- [ ] `INDEX.md` を更新した。

