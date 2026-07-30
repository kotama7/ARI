---
sources:
  - path: ari-core/ari/viz/frontend/src/app/routeRegistry.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/App.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Layout/Sidebar.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/app/queryClient.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/hooks/useV1.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/hooks/useRunEvents.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/shared/realtime/eventStream.ts
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/api_capabilities.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/v1/queries.py
    role: implementation
  - path: ari-core/ari/viz/v1/results.py
    role: implementation
  - path: ari-core/ari/viz/v1/rqgm.py
    role: implementation
  - path: ari-core/ari/viz/v1/events.py
    role: implementation
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/viz/v1/challenges.py
    role: implementation
  - path: ari-core/ari/viz/v1/openapi.json
    role: schema
  - path: ari-core/ari/viz/frontend/src/app/__tests__/routeRegistry.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/routeNavParity.test.tsx
    role: test
last_verified: 2026-07-30
---

# 仪表盘架构

ARI 仪表盘是一个由 `ari/viz/` 中的 Python HTTP 服务器提供的 React/TypeScript
单页应用。本页是*概念*视角：解释仪表盘为何长成这个样子的少数几个结构性决策
—— 一个外壳承载两代页面、一个注册表拥有路由、一个缓存拥有服务端状态、一条
横在 HTTP 与文件系统之间的接缝。

它有意不是一份端点清单，也不是一次逐次点击的导览：

- [仪表盘指南](../guides/dashboard.md) —— 运维者的导览：启动服务器、每个
  工作区回答什么、深链。
- [ARI 架构](architecture.md) —— 仪表盘所观察的研究系统（流水线、BFTS、
  检查点）。
- [研究状态与治理状态](research_and_governance_state.md) —— 仪表盘必须保持
  分开的那些状态词汇表。
- [REST API 参考](../reference/rest_api.md) —— 端点表。

---

## 整体图景

```text
     #/tree2?run=R1&node=N7       ← the URL is navigation truth
               │
               ▼
  ┌──────────────────────────── browser ─────────────────────────────┐
  │  route registry (app/routeRegistry.ts)                           │
  │    · path + legacy aliases  · nav slot  · guiV2 gate             │
  │               │                                                  │
  │               ├──▶ legacy screen  (#/tree, #/results, …)         │
  │               └──▶ v2 workspace   (#/tree2, #/results2, …)       │
  │                     │   both inside the SAME shell/Layout        │
  │                     ▼                                            │
  │  server-state cache (react-query)                                │
  │  key = ['v1', <runId | projectId>, <resource>]                   │
  └────────────┬─────────────────────────────────┬───────────────────┘
    HTTP GET   │                                 │  SSE = invalidations
               ▼                                 ▼
  ┌────────────────── transport: ari/viz/routes.py ──────────────────┐
  │  same-origin CORS · CSP / nosniff / Referrer-Policy ·            │
  │  bearer auth on non-loopback binds · challenges · logs           │
  └────────────┬─────────────────────────────────┬───────────────────┘
               ▼                                 ▼
     v1/router.py (ROUTES table)             v1/events.py (bus)
               │
               ▼
     pure read modules: queries.py · results.py · rqgm.py · logs.py
     (no viz.state writes · no os.environ writes · no ari.rqgm)
               │
               ▼
     {checkpoint}/  tree.json · review_report.json ·
                    rqgm_transitions.jsonl · ear/     ← the truth
```

下文的一切都是同一条规则的推论：**磁盘上已提交的工件是唯一的真相，而它们
之上的每一层都是可以被丢弃并重新计算的投影。**

---

## 1. 绞杀者形态：一个外壳，两代页面

仪表盘不是原地重建的。legacy 页面与新的 v2 工作区并排注册在同一个路由器中，
并渲染在同一个 `Layout`（侧边栏、页头、检查点选择器）内部。没有删除任何东西
来给新页面腾地方。

| 世代 | Hash 路由 |
|---|---|
| legacy 页面 | `#/home`、`#/experiments`、`#/monitor`、`#/tree`、`#/results`、`#/wizard`（`#/new`）、`#/idea`、`#/workflow`、`#/settings`、`#/paperbench*` |
| v2 工作区 | `#/projects`、`#/overview?run=`、`#/tree2?run=&node=`、`#/ideas2?run=`、`#/results2?run=`、`#/governance?run=`、`#/config?run=`、`#/studio` |

有三个机制让两代页面共存：

- **并行运行。** v2 工作区绝不会修改它对应的 legacy 页面。`#/tree` 与
  `#/tree2` 是覆盖同一批工件的不同组件；两者都保持可访问。
- **导航接管（`navReplaces`）。** 在 v2 外壳开启时，一个 v2 路由可以占据它
  对应 legacy 页面的*侧边栏位置* —— 它继承该位置的标签、顺序与图标，因此
  侧边栏看起来完全一样，只有点击所写入的 hash 变了。legacy 路由仍然保持
  注册，因此它的 URL 继续工作；书签绝不会失效。
- **单一紧急开关。** 在 v2 外壳关闭时，仅 v2 的路由会像未知 hash 一样解析到
  Home，侧边栏隐藏它们的条目。无需重新构建，也无需重新部署 —— 见 §7。

因此这次迁移没有需要排期的切换时刻。给一个工作区一个导航位置就是提升它；
把这个位置拿走就是回滚它。

---

## 2. 路由注册表是路由唯一存在的地方

`app/routeRegistry.ts` 持有一个 `ROUTE_REGISTRY` 数组。每个条目携带该路由的
`id`、它的 hash `path`、一个惰性 `load` thunk、可选的导航元数据
（`navLabelKey`、`navOrder`、`navIcon`、`navPath`）、`legacyAliases`，以及
迁移标记 `guiV2` / `navReplaces`。

两个消费者都是*推导出来*的，不是手工维护的：

- `App.tsx` 从注册表构建它的惰性组件映射与分发逻辑（`resolveRoute` 去掉
  `#/` 前缀与任何查询串，把空 hash 当作 `home`，并应用诸如 `new` → `wizard`
  之类的 legacy 别名）。
- `Sidebar.tsx` 从 `navItems()` 构建它的导航表，后者会把一个 `navReplaces`
  条目物化到其目标的位置上，并按 `navOrder` 排序；侧边栏随后把向导条目提取
  出来作为主操作，并把其余条目排进四个固定分组（portfolio / research /
  quality / system）。

两个冻结字面量测试固定了这个结果，因此一个路由不可能漂移成「存在于导航中却
不存在于路由器中」（或反过来）。由此推出的实用规则是：

- **Hash URL 是一份部署契约。** 它们是用户加进书签的东西，也是文档引用的
  东西；注册表保留历史写法（向导仍然导航到 `#/new`），而不是把它们整理掉。
- **「可访问但不列出」是可表达的。** `#/paperbench/import|run|results` 作为
  路由存在但没有导航条目 —— 它们从页面内部打开。
- **未知的 hash 回退到 Home**，而不是报错。

---

## 3. URL 就是导航真相

仪表盘是一个 hash 路由器，而*选择*位于 hash 查询串中：
`#/overview?run=<run_id>`、`#/tree2?run=<run_id>&node=<node_id>`。路由分发
忽略查询串，因此每个 v2 工作区拥有自己的参数 —— 它在挂载时读取它们，在
`hashchange` 时重新读取，并把变化后的选择写回 hash。

这在概念上为什么重要：一个工作区渲染出的内容仅仅是它 URL 的函数。这让每个
视图都可重新加载、可加书签、可分享 —— 「看运行 R1 的节点 N7」是一个链接，
而不是一串点击操作。

legacy 路径是促成这条规则的反面对照。从 legacy Experiments 的行进入 legacy
Results 页面，至今仍要经过一次*隐式*交接（一个 `sessionStorage` 键加上一个
裸的 `#/results` hash），而且 legacy 外壳还携带一个进程级的*活动检查点*。
这两者对 v2 工作区都不是有效输入：v2 路由是 run 显式的，正是这一点让两个
标签页中打开的两个运行互不干扰 —— v2 的行改为链接到
`#/results?run=<run_id>`，Results 页面把该参数视为权威，`sessionStorage`
键只作为老调用方的回退保留。

---

## 4. 服务端状态存放在按 run 建键的缓存中

所有 `/api/v1` 读取都经由一个 react-query 客户端。查询键的形状是
`['v1', <projectId | runId>, <resource>]` —— 标识符位于键的*内部*。

这一个决策换来三个性质：

- **两个运行绝不可能混淆。** run 作用域的条目是彼此独立的缓存条目，因此切换
  运行不会把上一个运行的数据渗进当前视图。
- **失效具有恰到好处的粒度。** 丢弃 `['v1', runId]` 只丢弃一个运行的服务端
  状态，别的什么都不影响；属于某个资源的过滤条件（审计日志的记录类型、
  纪元）同样位于键中，因此更改它会开启一条全新的分页链，而不是追加到一条
  陈旧的链上。
- **新鲜度策略只在一个地方。** 客户端默认值是 `staleTime` 5000 ms（与历史
  轮询节奏一致，因此在该窗口内的重新挂载直接读缓存）、重试一次，以及窗口
  获得焦点时不重新抓取 —— 一个本地仪表盘绝不能把焦点抖动变成对检查点扫描器
  的请求风暴。

仅客户端的状态（哪个标签页打开着、过滤框中的文本、侧边栏宽度）*不在*这个
缓存里。分工是：服务端状态被缓存并被失效，视图状态是本地且短暂的，导航状态
在 URL 中（§3）。

---

## 5. 实时是失效通知，不是事实来源

`GET /api/v1/events/stream` 是一条带服务端 `run_id` / 主题过滤的
Server-Sent Events 流。一个事件是一条小小的通知 ——
`{event_id, run_id, topic, revision, occurred_at, kind, resource, payload}`
—— 而消费者唯一的反应就是让匹配的缓存键失效并重新抓取 HTTP 快照。

任何东西都绝不会*基于*事件被渲染出来。其后果正是这样设计的理由：

- **重复与乱序都无害。** 由快照端点决定什么是真的；事件只决定*什么时候再问
  一次*。
- **流断开是一个新鲜度问题，绝不是一次状态变化。** 最后一份快照留在屏幕上，
  并带一个陈旧横幅。断连绝不会被呈现为「运行停止了」。
- **重连既廉价又有界。** 指数退避（1 秒 → 上限 30 秒）加上 `Last-Event-ID`
  游标；错误持续超过一分钟会把连接翻转为 `offline`，那是**唯一**会启用有界
  10 秒轮询回退的状态，且回退范围仅限该订阅自身的范围。
- **总线保持小巧。** 事件位于一个追加写入的内存环形缓冲区中，容量固定，配有
  心跳注释与有界的流窗口，因此空闲的代理或卡住的客户端不可能永久占住一个
  worker。

由于事件自带 `run_id`，运行 B 的事件绝不可能触碰运行 A 的缓存条目 —— 这与
§4 是同一条隔离性质，只不过是在缓存的写入侧强制的。

---

## 6. 后端接缝

服务器分为四层，每一层只被允许知道它下面那一层。

| 层 | 模块 | 职责 |
|---|---|---|
| 传输 | `ari/viz/routes.py`（外加 `auth.py`、`server.py`、`health.py`） | socket 层面的策略：同源 CORS 回显、SPA 与静态响应上的 `Content-Security-Policy` / `nosniff` / `Referrer-Policy`、绑定为非回环时的 bearer token 认证、访问日志、`/health/live` 与 `/health/ready`。 |
| API | `ari/viz/v1/router.py` | 一张 `(method, path template, handler)` 的声明式 `ROUTES` 表。每次分发铸造一个 `request_id` 并把它穿进成功载荷或类型化的错误信封；在 `PATCH`/`DELETE` 上强制 `If-Match` 乐观并发；同一张表还生成已提交的 `openapi.json`，因此契约不可能与分发器漂移。 |
| 读模型 | `queries.py`、`results.py`、`rqgm.py`、`logs.py`、`catalogs.py` | 从检查点目录到 DTO 的纯函数。不修改 `viz.state`、不写 `os.environ`、不写文件 —— 一次 GET 没有副作用。 |
| 真相 | `{checkpoint}/…`，加上存放仅 GUI 文档的 `{workspace_root}/gui_store/` | 已提交的工件。 |

这条接缝有两个性质值得明确写出来，因为它们很容易被侵蚀：

- **`GET` 无副作用。** 读模块有意从文件系统重新推导运行状态（pid 探测 →
  树精化 → 评审报告），而不是去查询或修剪服务器的进程跟踪状态 —— 较旧的
  处理器把修改该状态当作被读取的副作用。
- **写入既狭窄又显式。** GUI 自己的文档 —— project 默认值、run 模板、run
  草稿、启动幂等记录 —— 位于 `{workspace_root}/gui_store/` 而不是某个全局
  home 目录，使用原子写入以及一个与 `ETag` / `If-Match` 一一对应的整型
  `revision`。它们是一个便利层：启动会把每个生效值物化进检查点，因此 CLI
  永远不必读取 `gui_store/` 就能复现一次运行。

---

## 7. 读模型是可丢弃的投影

*读模型*是一份按需从已提交工件计算出来的有界投影。删掉所有读模型，不会丢失
任何信息；删掉一个工件，它就没了。这种不对称正是要点。

治理读模型是最严格的实例，它展示了「投影」在实践中意味着什么：

- **它不重新执行任何决策。** `ari/viz/v1/rqgm.py` 从不导入 `ari.rqgm`。它
  解析已提交的工件（`rqgm_state.json`、`rqgm_transitions.jsonl`、
  `rqgm_audit.jsonl`、`rqgm_registry.json`、节点 metric 哨兵字段……）并报告
  它们所说的内容。GUI 无法编造治理裁决，因为它从不运行产生裁决的那个内核。
- **只有已提交的记录。** 当前状态是*已提交*转换的重放。撕裂的 JSONL 末行会
  被忽略，而位于没有对应 commit 的 prepare 之后的事件永远不会被采纳。rollup
  快照被读取，只是为了校验重放与它一致。
- **降级，而非损坏。** 损坏或缺失的工件会得到带诚实标志的 HTTP 200：完整性
  是三态的（`true` 已校验 / `false` 已断裂 / `null` 来源缺失），并且有一份
  `degraded_reasons` 列表随载荷一同返回。缺失的来源绝不会被渲染为干净，也
  绝不会被渲染为零。
- **在构造上就是有界的。** 摘要携带计数而不内嵌条目列表；长日志按稳定偏移
  做游标分页；没有任何文件*内容*搭乘这些端点。

对于要扩展仪表盘的人，操作规则是：要改变 GUI 展示的内容，就改变投影 ——
绝不要改工件，也绝不要通过重新计算内核已经提交过的决策来实现。

---

## 8. 能力与紧急开关

仪表盘区分两种「这个不可用」，而它们都不是错误。

**服务器能力 —— 这个构建提供什么。** `GET /api/capabilities` 报告 `gui_v2`
标志（`ARI_GUI_V2`，默认开启）。前端在挂载时抓取它一次，并把*失败*的抓取
视为开启，因此 API 抖动绝不会把本地用户搁浅在回退外壳里。

**运行能力 —— 这个运行的工件支持什么。** 仅由工件存在性检测：一个运行有
治理，是因为 `rqgm_state.json` 存在；它处于归档论文模式，是因为
`paper_archive_state.json` 存在（二者是独立的轴）。没有治理的运行会得到一个
明确的「governance is not active for this run —— this is a capability state,
not an error」面板并说明原因，而不是一片空白页面或一个编造的零。

随刷新后的 GUI 引入的每一项有风险的行为，都配有一个环境变量紧急开关，因此
一次部署可以在不回退整个发行版的前提下撤销单个决策。它们全部记录在
`scripts/setup/setup_env.sh` 中：

| 变量 | 默认值 | 关闭它可恢复 |
|---|---|---|
| `ARI_GUI_V2` | 开启 | 仅 legacy 外壳（仅 v2 的路由回退到 Home） |
| `ARI_GUI_BIND` | 回环（`127.0.0.1` + `::1`） | 更宽的绑定，例如全接口的 `::` |
| `ARI_GUI_TOKEN` / `ARI_GUI_AUTH` | 在非回环绑定上强制认证 | 无认证的远程绑定（例如位于一个负责认证的代理之后） |
| `ARI_GUI_CORS_ANY` | 关闭（同源回显） | legacy 的 `Access-Control-Allow-Origin: *` 通配符 |
| `ARI_GUI_CSP` | 开启 | 不带 CSP / nosniff / Referrer-Policy 响应头的响应 |
| `ARI_GUI_CHALLENGES` | 开启 | 直接执行的破坏性端点，无需确认挑战 |
| `ARI_GUI_HEALTH` | 开启 | 健康探针引入之前的响应，且没有诊断端点 |

这些开关所守护的安全默认值值得写明一次：服务器仅绑定回环，因此默认的本地
使用体验不需要认证；非回环绑定通过要求 bearer token 而*安全失败*（若未配置
则在启动时生成并打印一次）；而三个破坏性操作（删除检查点、停止、停止 GPU
监控）需要服务器签发的一次性确认挑战，没有它就返回 `428`。

---

## 另请参阅

- [仪表盘指南](../guides/dashboard.md) —— 如何驾驭本页所解释的这些接口面。
- [ARI 架构](architecture.md) —— 仪表盘所观察的系统。
- [研究状态与治理状态](research_and_governance_state.md) —— 外壳所渲染的
  状态模型，以及它绝不能模糊的真实性规则。
- [Constitutional ARI-RQGM 架构](rqgm_architecture.md) —— 读模型所投影的
  那些已提交工件背后的治理内核。
- [REST API 参考](../reference/rest_api.md) 与
  [内部边界](../reference/internal_boundaries.md)。
