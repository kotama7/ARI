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
  - path: ari-core/ari/viz/services/__init__.py
    role: implementation
  - path: ari-core/tests/test_gui_config_shadow_legacy.py
    role: test
  - path: ari-core/tests/test_gui_state_facade_freeze.py
    role: test
last_verified: 2026-08-07
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
  Home，侧边栏隐藏它们的条目。无需重新构建，也无需重新部署 —— 见 §9。

因此这次迁移没有需要排期的切换时刻。给一个工作区一个导航位置就是提升它；
把这个位置拿走就是回滚它。

这个形态**不是**什么 —— 而这正是最容易的误读 —— 它不是一层薄薄的 legacy
facade 架在一个共享的应用服务之上。`ari/viz/services/` 里只有三个模块
（`state_service`、`file_service`、`launch_service`），而 `/api/v1` 从中调用
的只有 `launch_service.load_dotenv_files`。除了几个共享的辅助函数 ——
检查点目录解析、检查点搜索基路径、pid 探测、逐字节保真的树适配器、`.env`
链读取、访问日志写入 —— legacy 处理器与 v1 read 模块大体上是覆盖同一批工件
的两套独立实现。但凡是 legacy 侧的函数已经是唯一真实来源的地方，v1 模块都是
刻意复用它而不是 fork 它：`catalogs.py` 原样再供 legacy 的 `/api/models` 负载
（`checkpoint_api._api_models`），只多加一个字段 —— 该 provider 的 API key
环境变量名；`results.py` 以只读方式调用 `ear._synth_repro_report_from_ors`
来填充 ORS 的 verdict、分数与叶子计数，因此两个 Results 界面不可能给出不同的
verdict；`secrets.py` 的写入则经由 `api_settings._upsert_env_key`。正是这些
复用点让两侧保持同步，而它们同样是 legacy 移除必须拆解的东西：删掉 legacy 的
`/api/models` 处理器或 `ear.py` 会弄坏 `/api/v1` 的读模型（§7）。

配置抵达一次运行同样有两条路径：legacy 的「保存设置 + 启动」链把选定的键映射成
派生 CLI 的环境变量，而 `/api/v1` 的配置端点走的是权威解析器。两者
并非处处一致，其差异就是[配置](../reference/configuration.md)中列举的那些
dead 与 env-only 的 Settings 键。

因此，两侧的一致是靠测试维持的，而不是靠结构。
`ari-core/tests/test_gui_config_shadow_legacy.py` 把 legacy 启动的有效配置与
权威解析器的结果逐叶做差分，只有被明确 allowlist 列出的行才允许分歧 —— 若某
个已列出的行悄悄不再分歧，它同样会失败。
`ari-core/tests/test_gui_state_facade_freeze.py` 固定了被冻结的 `/state`
负载的顶层键集合，新增与删除都会被拒绝。对要改动行为的人来说，实际后果是：
预期要改两处，并且预期这两个测试套件就是在你只改了一处时告诉你的东西。

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
- **未知的 hash 回退到 Home**，而不是报错。这条回退在一种情形下是承重的，在
  另一种情形下是已知缺陷。对紧急开关而言它是刻意的：在 v2 外壳关闭时，仅 v2
  的路由必须像未知 hash 一样解析，legacy 界面才保持完整（见*能力与紧急开关*
  一节）。而对一次真正的拼写错误而言它是缺陷 —— 用户到达 Home 却得不到任何
  解释，一个明确的「这个路由不存在」的处置页面至今仍是待办（在 `App.tsx` 中
  标为 `TODO`）。*缺少 run* 的那一半已经按设想实现：不带 `?run=` 打开的 v2
  工作区会显示明确的提示，而不是悄悄采用某个全局选择。

**注册表不携带什么。** `RouteDefinition` 声明了两个无人读取的字段：
`breadcrumbKey` 与 `requiredContext`。仪表盘中任何地方都没有面包屑组件，也没有
路由级的必需上下文守卫 —— 取而代之的是每个 v2 工作区自己给出「未选择 run」的
提示。GUI 刷新所规定的另外两个外壳界面同样没有建成：没有命令面板，也没有通知
中心，因此一条运行或治理告警只在渲染它的那个页面上可见。路由也不携带权限
谓词，而且只要服务器没有用户模型就不会需要 —— bearer token 是全有或全无的，
会话与多用户都不在范围内。能力门控只有一个标记：注册表条目上的 `guiV2`，加上
`App.tsx` 中的 `V2_ONLY_ROUTES` 分发集合。

**只有一个错误边界，位于根部。** 仪表盘只有一个 React 错误边界，在 `main.tsx`
中，位于路由器之外、`Layout` 之外。一次路由内部的渲染失败 —— 包括一个加载失败
的惰性 chunk，因为 `App.tsx` 里的 `Suspense` 只提供了 fallback 而没有边界 ——
因此会把整个外壳（连同侧边栏）替换成「ARI Dashboard Error」页面；只有开发者
模式才显示堆栈，唯一的恢复手段是重新加载页面。带自身重试操作的路由级边界曾被
规定，但并未实现，也没有针对 chunk 加载失败的测试。

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

这个键的名字值得钉住，因为它是一份跨页面的契约，而不是某个页面的私有存储：
`ari_selected_checkpoint`。legacy Experiments 的行在导航到 `#/results` 之前
写入它；v2 的 Projects 行在给出显式 `#/results?run=<run_id>` 链接的同时仍然
写入它；Results 页面*只*在 hash 不带 `?run=` 时读取它，并且两种情况下都会清除
它。另一个键 `ari_tree_nodes` 由 legacy Experiments 页面在导航到 `#/tree`
之前写入，却没有任何地方读取 —— Tree 页面的节点来自共享的 legacy 上下文。它是
死状态；删除这次写入属于 legacy 页面移除的一部分，而不是一次行为变更。

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
  的请求风暴。这一个默认值同时也是*全部*策略：没有任何查询覆盖它，因此一次
  几乎静态的 schema 读取被完全当作一棵活的树来对待，而新鲜度横幅报告的是最后
  一份快照的时间，而不是每个资源各自的年龄。按实体划分的 stale time 与按实体
  划分的新鲜度标签曾被规定，但并未实现。

仅客户端的状态（哪个标签页打开着、过滤框中的文本、侧边栏宽度）*不在*这个
缓存里。分工是：服务端状态被缓存并被失效，视图状态是本地且短暂的，导航状态
在 URL 中（§3）。

**变更（mutation）从不乐观。** 没有任何页面把预测出来的结果写进缓存。写请求
被发出，服务器的回答 —— 一个新的 `revision`，或者 `409 revision_conflict`
—— 才是 UI 所采纳的东西，并且受影响的查询键会被失效，因此下一次渲染来自
重新抓取的快照。这正是为什么一次冲突的保存会给出明确的重新加载入口并把未保存
的编辑留在本地，而不是悄悄取胜；也正是为什么屏幕上不可能出现服务器从未接受过
的状态。

**`AppContext` 的作用域被限定在 legacy。** 它只是 legacy 页面的远端数据存储
—— 5 秒一次的 `/state` 轮询、树 WebSocket 的镜像，以及进程级的活动检查点。
一个 v2 工作区不得 import 它：它通过 `useV1` 钩子读取 `/api/v1`，并从 `?run=`
取得自己的 run。这条规则是结构性强制的，而不是靠评审 —— `src/__tests__/`
下的一次源码扫描会加载 v2 组件目录中的每一个非测试文件，一旦发现 `AppContext`
的 import 说明符就失败。它只带一个被钉住的例外：IdeasV2 的研究目标卡片，它在
一次 run 同一性检查之后从 `/state` 读取该目标，因为目前还没有任何 run 作用域的
v1 端点提供它。缩小这份例外清单是受欢迎的；扩大它则是退化，因为只要还有 v2
页面依赖它，`AppContext` 就无法被删除。

**持久化偏好没有存储层。** 语言（`ari_lang`，默认 `ja`）、开发者模式
（`ari_dev_mode`）与远程 bearer token（`ari_gui_token`）都直接落在
`localStorage` 上，各自藏在一个只管一个键的访问器背后 —— `i18n.storedLang()`、
`useDevMode.isDevMode()`、`client.getGuiToken()` —— 而 Settings 页面至今仍自己
从 `localStorage` 读 `ari_lang`。这三者之上没有偏好存储的抽象，没有这些键的
schema，也没有迁移路径，因此重命名或改变其类型是逐键的改动，没有一个能一次改完
的地方。刷新后的外壳曾规定过一个偏好层，但并未实现；请把这三个键名当作真正的
契约。

---

## 5. 实体模型只有一层

v1 接口面的形状是 `project → run` 的层级，但只有下面那一层是真实存在的。
`GET /api/v1/projects` 恰好只返回一个项目 —— 虚拟的 `default`：它的
`checkpoint_roots` 是实际存在的检查点搜索基目录，它的运行列表是跨这些基目录的
一次检查点目录扫描（名称过滤与跳过集合与 legacy 列表相同）。
`GET /api/v1/projects/{project_id}/runs` 对 `default` 以外的任何 id 返回带类型的
`404`，而 Projects 工作区直接取 `projects[0]`，不再多看一眼。

有三个后果必须纳入设计考虑：

- **不存在项目生命周期。** `ROUTES` 表里没有项目的创建、重命名或删除。以项目
  为对象的端点另外只有 `/api/v1/projects/{project_id}/config` 的 `GET` /
  `PATCH`，两者都拒绝 `default` 以外的 id；它们读写的是唯一的单例文档
  `gui_store/project_config.json`。
- **运行没有按项目划分。** 每个 run 作用域的端点都是 `/api/v1/runs/{run_id}/…`，
  不带项目路径段，因此出现在 URL 或缓存键（§4）中的 `project_id` 从不缩小任何
  范围。应把 `default` 读作一个让这些形状保持稳定的固定占位符，绝不能读作运行
  之间彼此隔离的证据。
- **一次运行*就是*一个检查点。** `run_id` 字面上就是检查点目录名
  （`YYYYMMDDHHMMSS_<slug>`）。检查点并未被建模为一次运行可以拥有多个的保存点，
  也没有任何 v1 端点或 DTO 表达运行之间的谱系 —— `meta.json` 记录了
  `parent_run_id`，但 `/api/v1` 之下没有任何东西读取它。

字段注册表还提到了项目*之上*的层级，而它们同样不存在。它的 `scope` 词汇表是
`preference` / `installation` / `project` / `template` / `run`（见
[配置](../reference/configuration.md)），但五个之中只有三个真正被赋值：今天注册
表构建出的叶子，除了唯一一个 `installation` 叶子 `llm.api_key` 之外，全都是
`run` 或 `project`；而由于该叶子是 `secret_reference`，它的值住在
`/api/v1/secrets/*` 背后的 `.env` 链中，绝不会进入任何 GUI 文档。文档存储本来
也无处安放 preference 或 installation：它只持有 `project_config.json`、
`run_templates/`、`run_drafts/` 和 `launches/`，别无其他（§7）。

把真正的项目（拥有可复用配置）、运行（拥有生命周期）和检查点（拥有保存点）分开，
是预留的设计而非已实现的行为。代码树中没有任何东西实现它，因此不要把客户端写成
它已经存在的样子。

---

## 6. 实时是失效通知，不是事实来源

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

**一个所有者，两个诚实的例外。** `/api/v1` 之上的实时只有一个所有者：
`shared/realtime/eventStream.ts`。页面只调用
`subscribe(runId, topics, callbacks)` —— 通常经由 `useRunEvents` 钩子 ——
而不会自己构造 `EventSource`，因此退避计划、`last_event_id` 游标、三态连接
状态机以及离线轮询的滴答都只存在一次，也只被测试一次。有两条通道位于这份
所有权之外，并且早于它：HTTP 端口 + 1 上的 legacy 树 WebSocket，以及
PaperBench 的作业日志查看器 —— 它在作业进行中对 PaperBench 的日志流自己打开
一个 `EventSource`。两者都是移除的候选，而不是可以效仿的模式。

**订阅跟随已挂载的路由及其 run。** 一个页面只在自己的生命周期内订阅，而
`run_id` / `topics` 的过滤发生在服务端，因此页面绝不会为自己不会渲染的事件
付费。但没有任何机制去节流一个隐藏的标签页：客户端不监听 `visibilitychange`，
因此一个退到后台的标签页仍然保持流打开、仍然按退避重连、仍然让它 10 秒的
离线轮询继续滴答。后台标签页的负载控制曾被规定，但并未实现；若干个陈旧的
标签页会各自持有一条流。

---

## 7. 后端接缝

服务器分为四层，每一层只被允许知道它下面那一层。

这条接缝之下没有任何 Web 框架。传输层就是 Python 标准库：`server.py` 为每个
host 绑定一个 `ThreadingHTTPServer`（回环默认会同时请求两个地址族，并容忍其中
一个不可用；第一个之后的每个 server 都在守护线程上跑 `serve_forever()`），
请求由 `routes.py` 中唯一的那个 `BaseHTTPRequestHandler` 子类处理 —— 遗留面
通过针对请求路径的显式 `if`/`elif` 链分发，`/api/v1/` 之下的一切交给声明式的
`ROUTES` 表
（只有 `/api/v1/events/stream` 在前一个分支就被截走，因为分发器返回的是
dict，而 SSE 必须写一条长命的流）。只有树 WebSocket 走 asyncio：`_main` 是
唯一的 asyncio 入口，它在守护线程上启动文件监视器与 HTTP 服务器之后，只托管
HTTP 端口 + 1 上的 `websockets` 服务器。由此产生的两个后果贯穿本节其余部分。
API 层之所以自己拥有路由、错误信封和 OpenAPI 生成，是因为没有框架可以继承 ——
它们是在这里被造出来的，而不是被配置出来的。而一条连接只要还开着，就会占用
一个工作线程：处理器设置 `protocol_version = "HTTP/1.1"`，是为了让短轮询复用
同一条连接，而不至于把浏览器按源计数的连接池抽干；与此同时，长命的流式端点
回应 `Connection: close`，以免一直占着一个 keep-alive 名额。因此，处理器里的
阻塞操作代价是一个线程，而不是一个协程。

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

**这条接缝的浏览器一侧有三种传输 regime，而且是刻意不统一的。**
`services/api/client.ts` 暴露三对包装器，一次调用用哪一对，本身就是契约的
一部分。六个之中有五个共享同一个 `request` 原语；第六个 `v1Send` 刻意自己
构造 `RequestInit` —— 因为这个原语的选项形状本身就是被冻结的 legacy wire
契约的一部分，所以 v1 的写入传输（包括 `If-Match` 头）是放在 `request` 旁边，
而不是并进它里面：

- `get` / `post` 在任何非 2xx 上抛出
  `Error('<METHOD> <path> failed: <status>')`。legacy 的 `useApi` 钩子及其
  调用方依赖这次抛出。
- `pbGet` / `pbPost` 绝不抛出。PaperBench 的处理器以 HTTP 200 加一个
  `{error: …}` body 作答，因此应用层错误是从 body 到达的，由调用方就地处理。
- `v1Get` / `v1Send` 无论状态码如何都以解析后的 body resolve，因为 `/api/v1`
  返回的是真实的非 2xx 状态码，而它们的 body *正是*那份类型化的错误信封 ——
  一个会抛出的客户端恰好会丢掉 UI 所需要的那份载荷。随后
  `services/api/v1.ts` 把每一种失败（类型化信封、网络错误、无法解析的 body）
  归一化成一个被抛出的 `ApiErrorV1`
  `{code, message, details, request_id, retryable}`。

这份不对称是被保留下来而不是被整理掉的：前两种 regime 由一个冻结行为的测试
钉住，统一它们会悄悄改变每一个 legacy 调用方所看到的东西。新代码使用
`/api/v1` 这一种 regime。

这个客户端有两处缺口值得点名，因为它们的缺席很容易被误当成一种策略：

- **没有客户端侧的 abort，也没有 timeout。** 共享的 `request` 原语与 `v1Send`
  都既不传 `AbortSignal`，也不设置期限，因此一个挂起的请求会一直挂到浏览器放弃为止，
  而离开一个页面并不会取消它仍在飞行中的 fetch。重试策略就是 react-query 的
  默认值（重试一次）加上错误信封上由服务器声明的 `retryable` 标志 —— 后者调用
  方可以查看，但没有任何东西会自动消费它。幂等性是按端点而不是按方法元数据
  处理的：只有启动运行携带 `idempotency_key`，且每次评审批准只铸造一个，因此
  一次双击或一次重试重放的是同一次运行，而不会再生出第二次。按方法划分的
  abort / timeout / retry / 幂等性元数据曾被规定，但并未建成。
- **schema 漂移是在构建时被捕获的，而不是在运行时。** 生成的 DTO 模块
  `services/api/v1types.gen.ts` 由 `ari/viz/v1/openapi.json` 生成，并由一个
  漂移测试逐字节比对，因此一次没有重新生成的契约变更会让 CI 失败，永远不会
  发布出去。运行时则没有任何兼容性检查：与生成 DTO 不匹配的响应不会被检测到，
  而一个根本无法解析的 body 会被归一化为 `code: 'internal'` 且
  `retryable: true` —— 与一次传输抖动无法区分。一个专门的「这个 bundle 与这个
  服务器不匹配」的兼容性错误曾被规定，但并未实现，因此 bundle 与服务器的不匹配
  会表现为一个普通的 internal 错误，或者表现为某个字段缺失而渲染成空白。

---

## 8. 读模型是可丢弃的投影

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

## 9. 能力与紧急开关

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

## 10. 前端代码放在哪里

前端按*页面*分组，而它之上唯一的组合层就是路由注册表。
`ari-core/ari/viz/frontend/src/` 之下是：

| 目录 | 存放什么 |
|---|---|
| `app/` | 不属于任何页面的外壳接线：路由注册表（§2）与 react-query 客户端（§4）。 |
| `components/<Screen>/` | 每个页面一个目录，legacy 与 v2 并排存放（`Tree/` 与 `TreeV2/`、`Results/` 与 `ResultsV2/`），各自导出注册表所懒加载的页面组件；此外还有存放展示型原语的 `common/` 和存放侧边栏与页头的 `Layout/`。 |
| `context/` | legacy 的 `AppContext` —— `/state` 轮询与进程级的活动检查点。 |
| `hooks/` | 跨页面的 hook：`useV1`、`useRunEvents`、`useApi`、`useWebSocket`、`useDevMode`。 |
| `services/api/` | 一个传输内核（`client.ts`）加上每个端点族一个模块，由 `services/api.ts` 这层 barrel 重新导出，因此旧的 import 路径依然可解析。 |
| `shared/` | 跨切面的平台代码 —— 目前只有 `realtime/`，即 SSE 客户端。 |
| `i18n/`、`styles/`、`types/` | 三语言字符串表、CSS 令牌与布局样式表、共享 DTO 类型。 |
| `__tests__/` | 不属于任何页面的全应用守卫套件：路由↔导航一致性、整个 App 的路由渲染、外壳可访问性、开发者模式门控、生成类型漂移。 |

没有 `pages/` 层。注册表条目的 `load` thunk 直接 import 页面组件，因此路由组合
*本身*就是那条注册表条目。

**feature / entity 切分被规定过，但没有建成。** GUI 刷新要求进一步拆出
`features/` 与 `entities/` 目录，并规定一个 feature 不得 import 另一个 feature 的
内部模块，而必须经由 entity 或 shared 契约、或者经由组合它们的 page。这些都
不存在：没有 `features/`、
`entities/` 或 `pages/` 目录，而且在复用更省事的地方，代码树早已跨越了页面边界
—— `ConfigStudio` import 了 `ConfigBrowser` 的只读 config 表格（这是有意为之，
好让两个 config 界面不会漂移），`Monitor` 与 `TreeV2` 也都 import 了 legacy 的
`Tree` 可视化。

也没有任何东西强制分层边界。前端 `package.json` 既没有 lint 步骤也没有 lint
依赖，因此代码树中唯一的结构性 import 守卫是一个测试 ——
`src/__tests__/appContextScope.test.ts`，它扫描 v2 页面目录下每个非测试文件里的
`AppContext` import 说明符，一旦出现超出唯一钉住例外的情况就失败。该守卫守护的
是 legacy 移除闸门，而不是 feature / entity 边界；没有任何扫描去约束页面之间的
import。

请把这套切分读作行进方向，而不是代码树已经遵守的结构。今天真正被遵守的是那条
更浅的放置规则：展示型原语放进 `components/common/`，跨切面的平台代码放进
`shared/`，外壳接线放进 `app/` —— 而一个页面目录只拥有它自己的页面。

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
