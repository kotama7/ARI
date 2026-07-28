# 03 — Application Shell, Routing, and Frontend State

> Status: planned  
> Dependencies: 01, 02  
> Gate: G2 — Platform seam

## Purpose

route、navigation、run context、server state、form state、UI state を分離し、旧画面を mount しながら feature 単位で刷新できる frontend platform を作る。

## Scope

- single route registry と hash URL compatibility。
- application providers、error boundaries、lazy loading、capability gating。
- project/run context と cross-run isolation。
- server state query cache、form state、URL state、local UI state の責務分離。
- typed/generated API client と realtime invalidation integration。
- frontend directory structure、feature ownership、test seams。

## Non-goals

- backend endpoint の domain 実装は task 04。
- config resolver と schema は task 05。
- 個別 workspace の domain visualization は task 07/08。

## Existing problems

- `App.tsx` の `PAGE_MAP` と `Sidebar.tsx` の `NAV_ITEMS` が route/nav を二重定義し、未知 hash は Home へ silent fallback する。
- `AppContext` が checkpoint、`/state` の 5 秒 polling、tree WebSocket（port+1）、navigation concern を混在させる。
- `useApi` に request deduplication、cache、abort、retry、run-scoped query key がない。
- page 間の受け渡しが sessionStorage（`ari_selected_checkpoint`: Experiments→Results、`ari_tree_nodes`: Experiments→Tree）や global active checkpoint に依存する。
- frontend API error contract が二系統ある: `get/post` は非 2xx で throw、PaperBench の `pbGet/pbPost` は throw せず `{error}` body を返す（文書化済みの wire 契約）。
- durable preference は `localStorage`（`ari_lang`、`ari_dev_mode`）に直接依存し、preference store の抽象がない。

## Target structure

```text
src/
├── app/
│   ├── providers/
│   ├── router/
│   ├── routeRegistry.ts
│   └── shell/
├── pages/                 # route composition only
├── features/
│   ├── projects/
│   ├── launch/
│   ├── monitor/
│   ├── tree/
│   ├── results/          # EAR/publish lineage を含む
│   ├── paperbench/
│   ├── workflow/
│   ├── configuration/
│   └── rqgm/
├── entities/
│   ├── project/
│   ├── run/
│   ├── checkpoint/
│   ├── artifact/
│   └── workflow/
└── shared/
    ├── api/
    ├── realtime/
    ├── ui/
    ├── visualization/
    └── i18n/
```

feature は別 feature の internal module を import せず、entity/shared contract または page composition を介する。

## Route registry

各 route record は最低限次を持つ。

```ts
type RouteDefinition = {
  id: string
  path: string
  component: LazyComponent
  nav?: NavMetadata
  breadcrumb: BreadcrumbFactory
  requiredContext: Array<'project' | 'run' | 'workflow'>
  capability?: CapabilityPredicate
  permission?: Permission
  featureFlag?: string
  legacyAliases?: string[]
}
```

- router、sidebar、breadcrumb、command palette、route parity test を registry から生成する。
- `createHashRouter` 等で現在の `#/...` deployment contract を維持する。
- invalid/missing run は silently global selection へ戻さず、明示的 resolution screen を出す。
- selected node、epoch、transition、tab、filter は shareable URL query にする。

## State ownership

| State kind | Owner | Examples |
|---|---|---|
| Server state | query cache | run summary、tree、events、settings schema |
| Navigation state | URL/router | run ID、tab、selection、filter |
| Form draft | form library/feature | run draft、config edit、workflow edit |
| Durable preference | browser preference store | locale、theme、density |
| Realtime connection | shared realtime client | SSE cursor、topic status |
| Ephemeral UI | local component/small context | open panel、hover、temporary selection |

- query key は `projectId/runId/resource/revision/params` を含める。
- run switch 時に previous run の delta を current UI へ適用しない。
- mutation は optimistic update を既定にせず、server revision/ETag を確認する。
- `AppContext` は remote data store から shell-level UI concern のみに縮小し、最後に削除可否を判断する。

## API client contract

- `/api/v1` OpenAPI から DTO/client を生成する。
- error は `code`、`message`、`details`、`request_id` に正規化する。
- abort、timeout、retryability、idempotency を method metadata で扱う。
- legacy client は旧 throw/non-throw behavior を adapter 内に閉じ込める。
- runtime schema mismatch は generic crash ではなく compatibility error として表示する。

## Realtime integration

- SSE event は source of truth ではなく query invalidation または小さな delta とする。
- connection restore 時は `Last-Event-ID` と snapshot refetch を組み合わせる。
- SSE 不可時だけ bounded polling fallback を使う。
- event topic subscription は active route/run に連動し、background tab の負荷を制御する。
- stale time と freshness label を entity ごとに定義する。

## Application shell

- project/run selector、context bar、primary navigation、global alerts、connection state を提供する。
- route-level error boundary と retry/recovery action を提供する。
- command palette は route、run、artifact、action を permission/capability に従って検索する。
- notification center は transient toast では失われる run/governance alert を保持する。
- shell 自体は domain artifact を直接 parse しない。

## Migration sequence

1. route/nav parity golden test を固定する。
2. route registry と hash router を導入し、全旧 page をそのまま mount する。
3. shell provider と run-explicit URL を導入し、legacy active checkpoint adapter を残す。
4. generated client と query cache を read-only endpoint から導入する。
5. realtime client と connection state を導入する。
6. feature ごとに AppContext dependency を query/URL/form state へ移す。
7. usage scan と rollback window 後に duplicate router、legacy remote state を削除する。

## Testing

- route registry から nav/breadcrumb/alias を生成する contract test。
- browser back/forward、deep-link、missing context、capability gating test。
- two-tab/two-run event isolation test。
- request abort、retry、stale、schema mismatch、SSE reconnect test。
- legacy route screenshot と behavior parity test。
- lazy chunk load failure と route error-boundary test。

## Completion criteria

- route/nav/breadcrumb が一つの registry から生成される。
- 全 run-scoped query と event が `run_id` で隔離される。
- server、URL、form、preference、ephemeral state の owner が重複しない。
- 旧 page と新 page を route 単位で feature flag 切替できる。
- old hash URL の contract suite が green である。

## Deletion criteria

- frontend architecture、routing/state conventions が恒久 developer docs に移管され、legacy router/AppContext remote state が削除済みである。

## Delete-after checklist

- [ ] generated route/API conventions を developer docs へ移した。
- [ ] legacy aliases の support policy を release docs へ移した。
- [ ] duplicate route/nav/AppContext code を削除した。
- [ ] main merge と CI green を確認した。
- [ ] `INDEX.md` を更新した。

