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
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/api_experiment.py
    role: implementation
  - path: ari-core/ari/viz/api_workflow.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Workflow/WorkflowPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Overview/OverviewPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Overview/LogsPanel.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/hooks/useDevMode.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Overview/__tests__/OverviewPage.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/components/Overview/__tests__/LogsPanel.test.tsx
    role: test
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
  - path: ari-core/ari/viz/frontend/src/styles/tokens.css
    role: implementation
  - path: ari-core/ari/viz/frontend/src/styles/motion.css
    role: implementation
  - path: ari-core/ari/viz/frontend/src/styles/components.css
    role: implementation
last_verified: 2026-08-16
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
并渲染在同一个 `Layout`（侧边栏、检查点选择器）内部。没有删除任何东西
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
  路由存在但没有导航条目。前两个由 PaperBench 注册页上的按钮打开；而
  `#/paperbench/results?job=<job_id>` 在应用内没有任何链接指向它，只能通过
  粘贴 URL 到达。
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
中心，因此一条运行或治理告警只在渲染它的那个页面上可见。命令面板被规定的检索
范围值得在它消失之前记下来 —— 一个输入框同时搜索路由、运行、工件与动作，并按
调用方被许可以及有能力看到的东西过滤 —— 因为这个过滤器有一半在这里本来就不可能
照规定建成。路由不携带权限谓词，而且只要服务器没有用户模型就不会需要 ——
bearer token 是全有或全无的，会话与多用户都不在范围内。能力门控只有一个标记：
注册表条目上的 `guiV2`，加上 `App.tsx` 中的 `V2_ONLY_ROUTES` 分发集合。

**没有哪个路由能说出自己的旗标名。** 刷新为一条路由记录规定的字段里，还有两个
从未被声明：一个 `capability` 谓词，和一个具名的 `featureFlag`。替这两者顶班的
是布尔值 `guiV2`，而它并不是某个路由自己挑的旗标名，而是对准同一个环境开关
`ARI_GUI_V2`（§9）的固定标记 —— 因此路由无法被逐个翻转。把开关关掉，被标记的
八条路由会一起解析到 Home，八个导航条目也一起消失，其中三个曾接管 legacy 位置
的会把位置还回去。尽管如此，分阶段推出仍是按切片进行的：
[GUI 切换运行手册](../guides/gui_cutover_runbook.md) 在「3. 分阶段推出」一节里
一次只推进一个工作区，而某个切片若需要退回，是靠拿走它的导航位置来回滚的
（§1）—— 但该手册「1. 手段」一节中的那根旗标手柄，是覆盖整个 v2 界面的这一个
开关。

缺席的 `capability` 字段还让注册表在这一个事实上失去了单一来源的性质。v2 门控的
成员身份被写了两遍：一次是注册表条目上的 `guiV2: true`，那是侧边栏用来过滤的
东西；另一次是这条路由的*路径*，写在 `App.tsx` 中手工维护的 `V2_ONLY_ROUTES`
集合里，那是分发所依赖的回退。冻结字面量测试固定了注册表侧被标记的八个 id，
而渲染整个 App 的那套测试以一次一个 hash 的方式检查了八条路径中五条的 Home
回退；没有任何东西去比对这两份清单。把第九条 v2 路由只加进其中一份，就会出现
导航条目消失而 URL 仍然活着（或者反过来）的情况，却没有任何测试会失败。

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

**这个 hash 有两个所有者，也有两个不同的解析器。** `App.tsx` 通过
`resolveRoute` 解析它：既去掉 `#/` 前缀*也*去掉查询串，并应用 legacy 别名。
`context/AppContext.tsx` 则持有它自己的 `currentPage`，由它自己的 `hashchange`
监听器初始化并更新，用的是一次两样都不做的裸前缀剥除。两者在一个朴素的 legacy
hash 上一致，而恰恰在刷新引入的那些 URL 上不一致：在
`#/tree2?run=R1&node=N7` 上，路由器分发的是 `tree2`，而上下文持有的是整串
`tree2?run=R1&node=N7`。

侧边栏据以渲染的正是后一个值。`Sidebar.tsx` 把一个导航条目的 hash 键与
`currentPage` 相比较，用来同时决定 `active` 类与 `aria-current`，因此点击之后
高亮是对的 —— 一次点击写入 `#/<key>` 并把 `currentPage` 设为那个裸键 ——
但只要某个工作区把自己的选择写回 hash（`TreeV2Page.tsx`、`ConfigStudioPage.tsx`
就会这么做），高亮就丢了；而对任何带着查询串抵达的深链，高亮从一开始就不存在。
于是刷新的完成标准 —— 服务端、URL、表单、偏好与短暂状态各自恰好只有一个所有者
且互不重复 —— 在导航状态上并不成立：一个 URL 有两个所有者，而第二个正是 §4
本来限定为远端数据的那个 legacy 上下文。

没有任何东西会抓到这次不一致，因为没有任何测试会对一个已挂载的外壳去改变
hash。挂载整个 `App` 的那两套测试 —— `src/__tests__/routeRenderBaseline.test.tsx`
与 `src/__tests__/shellA11yBaseline.test.tsx` —— 都是先给
`window.location.hash` 赋值，*然后*才渲染，而且始终是裸的 `#/<route>`，因此只有
首次绘制时的解析被覆盖到。没有任何东西去驱动浏览器的后退或前进，也没有任何测试
断言过 `aria-current`。后退／前进的覆盖曾在刷新的测试清单上，如今是一个已知缺口。

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

**去重预算成立的范围是 `/api/v1` 这一界面，而不是整个仪表盘。** 刷新为这套设计
附上了一个数值：同一查询键的在途重复读取为 0。在 `/api/v1` 上，这个数值是结构性
的而非测量出来的 —— 查询客户端会把同一个键的并发抓取合并为一次，因此挂载同一个
查询的两个组件只产生一个请求 —— 而它的宽度恰好就是这个界面，不会更宽。树中没有
任何东西去测量它。

legacy 那一半从来都在这个客户端之外发出自己的流量。`context/AppContext.tsx` 以
5 秒一次的 `setInterval`（`STATE_POLL_MS = 5000`）重新抓取 `/state` 与检查点
列表，而由于 `AppProvider` 位于路由器之上，这会持续整个会话；
`Monitor/MonitorPage.tsx` 则对 `/api/resource-metrics` 跑第二条独立的 5 秒周期，
只要该页面处于挂载状态就一直跑。两者都不经过查询客户端，彼此看不见对方，并且
在标签页被隐藏时都不会停下 —— 前端里没有任何东西监听 `visibilitychange`（§6），
因此退到后台的仪表盘会以全速继续跑这两条周期。暂停隐藏标签页的轮询、并把这些
读取迁移到流失效加快照查询上，曾被刷新规定过，但并未实现；它是一个已知缺口。
请按这个范围来读这份预算：对 `/api/v1` 的读取它依构造成立，而在那些轮询器消失
之前，它并不描述一个运行中的仪表盘整体 —— `AppContext` 的远程状态与它背后的
`/state` 外观，是 [GUI 切换运行手册](../guides/gui_cutover_runbook.md)
「6. legacy 移除」中移除顺序的第 2 项与第 3 项，而那份移除顺序根本没有点名
Monitor 的那条周期。

**运行隔离是在接缝处被证明的，而不是端到端。**
`hooks/__tests__/useRunEvents.test.tsx` 证明：一个运行的事件只让该运行的键与
运行列表失效；一条 `tree` 事件只触碰该运行的树键；离线轮询的滴答只留在被订阅
的范围内；卸载之后失效随之停止。`shared/realtime/__tests__/eventStream.test.ts`
则钉住了带过滤的流 URL、`Last-Event-ID` 游标、退避计划与连接状态机。没有任何
测试做的事情是：在两个运行上挂载两个工作区，并证明它们彼此不混。
[仪表盘指南](../guides/dashboard.md) 在「Run 显式的 URL 与深链」一节里告诉
运维者，用两个不同的 `?run=` 打开两个浏览器标签页是安全的；这个承诺依托的是
上面那套键的组成方式，加上服务端的 `run_id` 过滤（§6），而不是对两标签页这一
场景本身的测试 —— 那项测试曾出现在刷新的清单上，如今是一个已知缺口。

仅客户端的状态（哪个标签页打开着、过滤框中的文本、侧边栏宽度）*不在*这个
缓存里。分工是：服务端状态被缓存并被失效，视图状态是本地且短暂的，导航状态
在 URL 中（§3）。

**变更（mutation）从不乐观。** 没有任何页面把预测出来的结果写进缓存。写请求
被发出，服务器的回答 —— 一个新的 `revision`，或者 `409 revision_conflict`
—— 才是 UI 所采纳的东西，并且受影响的查询键会被失效，因此下一次渲染来自
重新抓取的快照。这正是为什么一次冲突的保存会给出明确的重新加载入口并把未保存
的编辑留在本地，而不是悄悄取胜；也正是为什么屏幕上不可能出现服务器从未接受过
的状态。

**刷新为这套键规定的组成部分里，唯独 revision 没有落地。** `v1Keys` 工厂
（`hooks/useV1.ts`）里的任何一个键都不带它。一个键由字面量 `'v1'`、一个标识符
或一个全局资源名、资源本身，以及任何用来收窄它的过滤条件构成 ——
`rqgmAudit(runId, recordType, epoch)` 与 `rqgmNodeLineage(runId, nodeId)` 就是
最后那种形状的例子 —— 词汇表就这么多。一份 `gui_store` 文档所携带的整型
`revision` 只在写入侧被使用，充当 `PATCH` 回送的 `If-Match` 值（§7）；一次写入
抵达缓存的方式是让受影响的键失效，而不是铸造一个新键。因此不存在按 revision
划分的缓存条目，也没有办法把同一份资源的两个 revision 并排持有，保存也不会带来
键的更替：下一次渲染来自同一个键的重新抓取。

**`AppContext` 的作用域被限定在 legacy。** 它只是 legacy 页面的远端数据存储
—— 5 秒一次的 `/state` 轮询、树 WebSocket 的镜像，以及进程级的活动检查点。
一个 v2 工作区不得 import 它：它通过 `useV1` 钩子读取 `/api/v1`，并从 `?run=`
取得自己的 run。这条规则是结构性强制的，而不是靠评审 —— `src/__tests__/`
下的一次源码扫描会加载 v2 组件目录中的每一个非测试文件，一旦发现 `AppContext`
的 import 说明符就失败。它只带一个被钉住的例外：IdeasV2 的研究目标卡片，它在
一次 run 同一性检查之后从 `/state` 读取该目标，因为目前还没有任何 run 作用域的
v1 端点提供它。缩小这份例外清单是受欢迎的；扩大它则是退化，因为只要还有 v2
页面依赖它，`AppContext` 就无法被删除。

**外壳的 legacy 那一半会解析领域工件。** 刷新同样要求外壳自身绝不这么做，可是
`AppProvider` 在 `App.tsx` 中被挂载在路由器与 `Layout` 之上，并对外发布
`nodesData: TreeNode[]` —— 该运行的节点列表：只要树 WebSocket 送来过任何东西
就取自它，否则取自 `/state` 负载里的 `nodes`。这条优先级规则就是住在路由器之上
的领域逻辑，而两个 legacy 页面（`Tree/TreePage.tsx`、`Monitor/MonitorPage.tsx`）
的节点也是从外壳拿的，而不是自己去抓。`Sidebar.tsx` 带着同一种耦合的缩小版：
`checkpointLabel()` 用 `^(\d{8})(\d{6})_(.+)$` 去匹配一个检查点 id 来拼出选择器
的标签，于是外壳把 §5 的 run id 约定硬编码了进去；它还直接从 `/state` 渲染该
运行的状态标签与运行中标志。一个 v2 工作区完全没有这些。因此这条不变量在新界面
上成立、在旧界面上失效，而让它处处为真的办法是移除 legacy，而不是改动外壳。

**持久化偏好没有存储层。** 语言（`ari_lang`，默认 `ja`）、开发者模式
（`ari_dev_mode`）与远程 bearer token（`ari_gui_token`）都直接落在
`localStorage` 上，各自藏在一个只管一个键的访问器背后 —— `i18n.storedLang()`、
`useDevMode.isDevMode()`、`client.getGuiToken()` —— 而 Settings 页面至今仍自己
从 `localStorage` 读 `ari_lang`。这三者之上没有偏好存储的抽象，没有这些键的
schema，也没有迁移路径，因此重命名或改变其类型是逐键的改动，没有一个能一次改完
的地方。刷新后的外壳曾规定过一个偏好层，但并未实现；请把这三个键名当作真正的
契约。

**表单草稿根本没有一个所有者层。** 前端的依赖里没有任何表单库
（`@tanstack/react-query`、`d3`、`pdfjs-dist`、`react`、`react-dom`、`reactflow`），
也没有共享的表单模块，因此每一个编辑界面都自己手搓草稿状态与冲突纪律。
`ConfigStudio/ConfigStudioPage.tsx` 是值得照抄的那一种：一个只承载被改动值、
叠在服务端文档之上的 `pending` 映射；把该文档的整型 `revision` 作为 `If-Match`
发出；并把 `revision_conflict` 呈现为一次明确的重新加载，同时保留未保存的编辑。
`Workflow/WorkflowPage.tsx` 走的是第二套纪律 —— `/api/workflow` 提供一个弱的内容
`revision`，写入时作为可选的 `base_revision` 回送，而服务器的拒绝是靠匹配被抛出的
legacy 传输错误的消息来识别的（§7）。`Settings/SettingsPage.tsx` 走的是第三套，
而且根本没有冲突路径：一个容器里放了三十七个 `useState` 钩子，刻意集中在那里，
好让它那份被冻结的保存负载不会漂移。它们不是同一套机制的变体；其中第一套与最后
一套，是覆盖 §1 所述那片相互重叠的配置界面的两个各自独立的表单所有者 ——
`ari-core/tests/test_gui_config_shadow_legacy.py` 对这片重叠是看管而不是消除。
刷新后的 GUI 曾规定过单一的表单状态所有者；它是一个已知缺口。

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

**还有两个实体，带版本的接口面从一开始就没有建模。** GUI 刷新的领域模型还列出了
run 之下的 `Artifact` 与 project 之下的 `WorkflowDefinition`；两者都曾被规定，
而都没有建成。各自缺口的形状决定了一个 v2 页面能提供什么。

*不存在 artifact 资源。* `ROUTES` 表里既没有 run 之下的 `artifacts` 集合，也没有
集合内可寻址的成员，已提交的 `openapi.json` 里没有任何一条路径提到 artifact。
`/api/v1` 提供的是一组名字固定的投影 —— `idea`、`results`、`ear`、`logs` 以及
RQGM 家族 —— 每一个都硬连线到它所知道的那些文件（§8）。其中唯一的*文件*列表接口
`GET /api/v1/runs/{run_id}/ear` 只遍历一棵子树 `{ckpt}/ear/`，逐条返回
`path` / `kind` / `size`，上限是前 500 条，超出部分置 `truncated: true`，而
`file_count` 仍然统计每一个文件。因此不存在「这次运行的文件 X」的稳定 id，没有任何
东西枚举一次运行实际写出了什么，而一种新的 artifact 类型也无法在不新增端点、不重新
生成契约的情况下浮现出来。浏览任意文件留在了以检查点为键的 legacy 接口面上 ——
`/api/checkpoint/<id>/files`、`/file`、`/file/raw`、`/filetree`、`/filecontent`
这一家族以及 `GET /codefile?path=`（见 [REST API 参考](../reference/rest_api.md)
的「检查点浏览」与「静态文件 + 前端」）。所以「artifact」保持的仍是
[术语表](../reference/glossary.md)在「状态与发表」下给出的磁盘层面含义：在某个节点
work_dir 内产生的、非元数据的文件。

*也不存在 workflow 文档。* 流水线定义就是一个普通文件 `{ckpt}/workflow.yaml`，
`/api/v1` 恰好以两种方式碰它，而且都不是把它当作资源：`POST /api/v1/runs` 以
写时复制方式从随包的 `config/workflow.yaml` 播种，并把本次启动的 mode 块合并进那份
副本；`GET /api/v1/runs/{run_id}/resolved-config` 背后的解析器把它当作 `workflow`
provenance 层来读，并把它的 mtime 计入 `resolved_at`。没有任何路由把它当文档来寻址：
它没有 id，不属于 `gui_store/` 的文档（§7），也不跨运行复用 —— 每个检查点都有自己
的一份副本。编辑它靠的仍是四个 legacy 写入 —— `POST /api/workflow`、
`/api/workflow/flow`、`/api/workflow/skills`、`/api/workflow/disabled-tools` ——
而它们的并发保护与文档存储的是两套机制：MN-3 的 `revision` 是所返回字节的
sha256 前缀，`base_revision`
是*可选的*，因此省略它的调用方仍然是 last-write-wins；而 `gui_store/` 的文档带一个
整型 `revision`，并拒绝任何不带 `If-Match` 到达的修改（见
[Configuration Studio](../guides/configuration_studio.md) 的「If-Match 冲突」）。

**一次 workflow 编辑的作用域只有一个检查点，而一次新的运行绝不会继承它。**
每一次 workflow 写入都落在*活动*检查点的那份副本上：`api_workflow.py` 在没有可用的
活动检查点时会直接拒绝写入，否则会在应用编辑之前以写时复制方式从随包文件播种出
`{ckpt}/workflow.yaml`，因此随包的默认文件绝不会被 GUI 改写。而两条启动路径随后都
只从那份*随包*文件为新检查点播种：`POST /api/v1/runs`（`ari/viz/v1/launch.py`）
把 `config/workflow.yaml` 复制进新检查点，并把本次启动的 mode 块合并进那份副本；
legacy 的向导启动 `POST /api/launch`（`ari/viz/api_experiment.py`）复制的是同一份
随包文件 —— 或者在它的某个阶段开关关闭时，写出一份变体：被关掉的 stage 置为
`enabled: false`，并从下游每一处 `depends_on` 中被剔除。两者都不会去读片刻之前还
处于活动状态的那个检查点，因此不存在任何路径能让一份被编辑过的副本成为播种源。
被编辑的副本只在*同一个*检查点再次运行时才被读回：BFTS 循环
（`ari/cli/bfts_loop.py`）与论文流水线（`ari/core.py`）都会把
`{ckpt}/workflow.yaml` 排在随包副本之前解析。

**已知缺口 —— 界面上没有任何东西说明这个作用域。** 刷新曾规定：一次保存要声明该
编辑将对哪一次运行生效。`Workflow/WorkflowPage.tsx` 在工具栏里渲染的只有所服务的
文件路径 —— 那是唯一的作用域线索 —— 除此之外什么也没有：没有说明编辑影响哪次运行，
保存时没有警告，也没有任何路由能把一条流水线应用到下一次运行。更进一步，两条启动
路径之间的差异同样没有被呈现：legacy 的向导启动会把进程级的活动检查点切换到新的
运行，于是编辑器悄悄改换了目标；而 `POST /api/v1/runs` 刻意不切换它，于是编辑器
仍然指着上一次运行。请把一次 workflow 编辑当作某一个检查点的属性，而不是一项设置。

最接近的可复用文档是 run 模板，而模板携带的是配置的 `values`，不是一条流水线。

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

**这四层是一种描述，不是包结构。** `ari/viz/` 之下没有 `transport/`、
`application/`、`domain/`、`infrastructure/` 或 `legacy/` 包，也没有任何意义上的
领域层：读模块与线缆之间什么都没有，一个检查点 `Path` 直接变成一个 pydantic DTO。
GUI 刷新规定的正是这样一次拆分 —— 包括把无版本的处理器移到一个适配器模块背后 ——
但它并未建成；legacy 处理器仍留在原处，由 `routes.py` 里的 `if`/`elif` 链从各自的
`api_*` 模块直接导入（见 [内部边界](../reference/internal_boundaries.md) 的
「GUI 的 HTTP 分发边界」）。

同一份提案里的进程 supervisor 也以同样的方式缺席。`POST /api/v1/runs` 用
`subprocess.Popen(..., start_new_session=True)` 拉起 CLI，并把句柄记进
`ari/viz/state.py` 中模块级全局的 `_running_procs` 映射，键是解析后的检查点路径 ——
与 legacy 启动处理器写入的是同一个映射。没有任何东西监督、重启或回收这些子进程。
一个条目只会机会性地离开这个映射：当 legacy 检查点列表下一次注意到子进程已退出时、
当同一个列表清理掉检查点目录已不存在的条目时，或者当一个检查点被删除时。这个映射
是进程本地的，因此服务器一重启就忘掉所有句柄；v1 读模型从不查询它，而是从文件
系统推导运行状态（见下），而 `/api/v1/diagnostics` 只公布它的长度，即
`process.tracked_runs`。请把这条接缝理解为由读模块自身的纪律和钉住它的测试维持的，
而不是由某个任何东西都能强制的包边界维持的。

这条接缝有三个性质值得明确写出来，因为它们很容易被侵蚀：

- **`GET` 无副作用。** 读模块有意从文件系统重新推导运行状态（pid 探测 →
  树精化 → 评审报告），而不是去查询或修剪服务器的进程跟踪状态 —— 较旧的
  处理器把修改该状态当作被读取的副作用。
- **写入既狭窄又显式。** GUI 自己的文档 —— project 默认值、run 模板、run
  草稿、启动幂等记录 —— 位于 `{workspace_root}/gui_store/` 而不是某个全局
  home 目录，使用原子写入以及一个与 `ETag` / `If-Match` 一一对应的整型
  `revision`。它们是一个便利层：启动会把每个生效值物化进检查点，因此 CLI
  永远不必读取 `gui_store/` 就能复现一次运行。
- **被铸造出来的时间戳来自文件系统，而不是时钟。** 服务器为一份读资源*推导*出来
  的时间字段，都是取自某个源文件 mtime 的 UTC ISO 8601 字符串，绝不是
  `datetime.now()`：run summary 上的 `mtime_utc` 是检查点目录的 mtime，run 模板或
  run 草稿上的 `updated_at` 是该文档文件的 mtime，解析后配置上的 `resolved_at` 是
  解析器那几个源文件里最新的 mtime（一个都不存在时退回检查点目录的 mtime）。正是
  这一点让对同一个未变动的 run 连续两次 GET 的结果，除了路由器为每次分发铸造的
  `request_id` 之外完全相同，因此两份抓取到的载荷之间的差异意味着「有东西变了」，
  而不是「时间过去了」——
  `ari-core/tests/test_gui_config_precedence_matrix.py` 用
  `test_resolved_at_mtime_stable_and_deterministic` 为解析器钉住了这一点，它先去掉
  `request_id`，再断言两次响应的其余部分相等。而从已提交工件里*照抄*出来的时间戳，保持的是
  那份工件自己的取值（一次 RQGM 转换的 `committed_at`、一条发布记录的
  `timestamp`）。只有在无文件可读的地方才会去读时钟：事件的 `occurred_at`（§6）
  与一次挑战的 `expires_at`。

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

**「按需」是字面意思：每次重算，从不缓存。** 每一次 `/api/v1` 的 GET 都会重新读取
它所投影的那些工件。`ari/viz/v1/` 之下任何地方都没有投影索引、没有 memoization、
也没有失效表 —— 这个包里唯一的缓存是 `launch.py` 中的幂等重放映射，它服务的是重复
的启动 POST，而不是读取。一个按文件 identity、大小、mtime 与内容摘要失效的持久化
读模型索引，曾被 GUI 刷新规定，但并未建成；线缆并不掩饰这一点，反而直说：
`GET /api/v1/diagnostics` 携带字面量字段 `cache: false`。真正把开销约束住的是逐端点
的纪律 —— 字节偏移游标、有上限的页大小，以及日志读取器每次请求最多 1 MiB 的扫描
窗口（见 [REST API 参考](../reference/rest_api.md) 的「游标约定」）—— 再加上 §4 的
客户端缓存，那才是同一份快照不会被抓取两次的地方。没有这类边界的端点，每次请求
都要付出全额开销；整份返回节点列表的 `GET /api/v1/runs/{run_id}/tree` 就是最清楚
的例子。

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
  做游标分页；唯一被整体读出的文件是 `/rqgm/policies` 与
  `/rqgm/epochs/{epoch_id}` 返回的受治理策略正文 —— 一旦其字节不再哈希为已注册的
  `prompt_hash`，正文就会被扣下，并作为 degraded 原因说明。

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
| `components/<Screen>/` | 每个页面一个目录，legacy 与 v2 并排存放（`Tree/` 与 `TreeV2/`、`Results/` 与 `ResultsV2/`），各自导出注册表所懒加载的页面组件；此外还有存放展示型原语的 `common/` 和存放侧边栏与包裹当前页面的页面框架的 `Layout/`。 |
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

**设计令牌是两层，不是三层。** 只有 `styles/tokens.css` 这一个文件*定义*自定义
属性。`motion.css` 在 `prefers-reduced-motion: reduce` 下把其中三个 ——
`--t-fast`、`--t-med`、`--t-slow` —— 重定义为零；`Layout/Sidebar.tsx` 内联写入的
`--sidebar-width` 是布局样式表读取的一个尺寸，而不是令牌。其余全部落在一个
`:root` 块里，分成两个具名层。**原语**层是原始刻度：色相（`--bg`、`--sidebar`、
`--card`、`--border`、`--text`、`--muted`、`--blue`、`--blue-light`、`--green`、
`--red`、`--yellow`、`--purple`，外加别名 `--primary`）、从 `--sp-1` 到 `--sp-8`
的间距档（4px 到 32px，没有 `--sp-7`）、圆角与焦点阴影、字号刻度和动效时长。
**语义**层为角色命名，并把每个角色解析到某个原语或原语的 `color-mix()` ——
此处不引入任何新色相：`--surface-canvas` / `--surface-raised` /
`--surface-overlay`、`--text-primary` / `--text-muted` / `--text-inverse`、
`--border-default` / `--border-focus` / `--focus-ring`、三个链接色、四个
`--status-*` 前景色及各自的 `-bg` 淡色（其中两个还有声明在原语旁边的 `-border`
淡色）、`--score-penalty`、五个 `--state-*` 节点得分色，以及十个 `--reg-*`
注册表生命周期色。

第三层，即**组件**层，曾被规定在这两层之上 —— 一个为某个组件的某一个角色命名的
令牌，例如主按钮的背景或被选中图节点的填充 —— 而它没有被建成。代码树里不存在
任何位于语义层之上的角色令牌；*名字*来自组件的唯一自定义属性是原语面色
`--sidebar`，它是最底层的原始值，而不是立在最顶层之上的角色。在组件层本该出现的
位置，取而代之的是 CSS 类直接消费语义令牌：`components.css` 为十个注册表状态各
定义一条 `.reg-badge--<status>` 规则，为五个节点得分状态各定义一条
`.nodestate-badge--<state>` 规则，都从对应的 `--reg-*` 或 `--state-*` 令牌取
`color`，而且两个类族有意互不相交。这确实交付了固定调色板的目的 —— 两套词汇谁
也借不到对方的颜色，正如
[研究状态与治理状态](research_and_governance_state.md) 的
「4. 注册表生命周期 vs 节点得分状态」一节所要求的 —— 但它是通过类名交付的，而
不是通过第三层令牌。

**已知缺口 —— 「语义层之上的东西不越过它去够原语颜色」这条规则没有被强制，代码
树也没有遵守。** 如上所述，`package.json` 没有 lint 步骤；没有任何测试、也没有
`scripts/quality/` 下的任何检查器读取样式表（打包体积闸门只称量 `.js` 分块），
因此没有任何东西能因违规而失败。对十三个原语颜色名的 `var(…)` 使用做统计：其中
458 处位于 `components/` 下 53 个非测试 `.tsx` 文件中，另有 140 处在样式表自身
（`components.css` 66、`widgets.css` 47、`layout.css` 21、`responsive.css` 6）
—— 而在同一批文件里，整个语义层的使用只有 113 处。v2 工作区是这道分野里较好的
一半，但也并不干净：`.tsx` 的使用中有 38 处在 v2 工作区、2 处在
`components/common/`，且它们无一例外都是 `--muted`、`--border`、`--bg` 或
`--red` —— 这四个各自都有本可胜任的语义等价物（`--text-muted`、
`--border-default`、`--surface-canvas`、`--status-danger`）。请把语义层读作增量式
且只被部分采用：正如上面的切分之于结构，它是颜色上应走的方向，而不是代码树已经
遵守的边界。

**已知缺口 —— 语义层不承载主题。** 它被写下来的目的，是成为 light、dark 或
高对比度变体切换时唯一需要改动的地方，让原语和组件都不必被触碰。仪表盘只出货
一个主题，`tokens.css` 在根上就把这点说明白了：它声明 `color-scheme: dark`，
正是为了让用户代理把 CSS 够不到的控件 —— 复选框与单选框字形、滚动条、
`<select>` 弹出框 —— 画成暗色，而不是在这些面上戳出亮色的洞，并用 `accent-color`
钉住选中态。前端任何地方都不存在 `prefers-color-scheme` 块，也没有主题开关，
因此第二套语义值从未被写出来。样式表真正尊重的唯一一项用户偏好，是 `motion.css`
里的 `prefers-reduced-motion: reduce`。

---

## 11. 披露层级：一个页面在你开口之前展示什么

仪表盘同时服务好几类读者 —— 启动第一次运行的人、读探索树的人、诊断卡住进程的人、
审计一次治理决策的人、读原始工件的人。刷新给出的答案是：按主题给出一个页面，让它
的*深度*可变，而不是按读者给出一个个应用。这个推论值得写下来，因为它正是整整一类
设计缺席的原因：没有任何页面是角色感知的，没有任何路由携带权限谓词（§2），产品里
也根本没有对读者的建模。深度是读者自己打开的东西，而绝不是被授予的东西。

深度用一架五级的梯子来描述，从 P1 到 P5。这些层级名不是装饰 —— 它们是源码在决定
一条信息该归属何处时所用的词汇，并且原样出现在组件注释与测试名里。

| 层级 | 内容 | 规定的默认可见性 |
|---|---|---|
| P1 | 运行状态、当前 phase、被阻塞的原因、下一步操作 | 始终可见 |
| P2 | 分数摘要、树、纪元、主要工件 | 始终可见 |
| P3 | 证据、一次转换的原因、config 差分、资源细节 | 一次交互之外 |
| P4 | 追踪、日志、逐节点谱系、原始事件的链接 | 一到两次交互之外 |
| P5 | 原始 JSON 与 YAML、内部 id、调试载荷 | 仅开发者模式 |

最后一列请读作意图。五级之中建成了三级，而代码树偏离这张表的地方，值得知道它偏向
哪一边。

**这架梯子实现在哪里。** 运行 Overview（`#/overview?run=`）是唯一明确按它建造的
页面，而其中存在的也只有 P1、P2 与 P4 三级。P1 是那组带标签的行 —— 生命周期徽章、
研究 phase、最后更新的新鲜度，以及对受治理的运行而言，一行单独的治理阶段行，承载
当前纪元与效用策略哈希 —— 其上方还有一块 blocker 面板，它在受治理运行的读模型报告
了 degraded 原因、或三个完整性标志（转换链、注册表快照、审计链）之一为假时出现。
P2 是三个计数器（已探索节点数、评审分数、最佳指标）以及通向树、config 浏览器、
（对受治理的运行）Governance 的工作区链接。P4 是可折叠的日志浏览器，也是最能说明
「惰性」在这里必须意味着什么的一级：面板折叠期间根本不会抓取任何东西，而它的测试
直接断言的正是这一点，而不是去检查标记是否被隐藏。一个先渲染再把内容藏起来的层级，
不算一个层级。

已建成的部分里有一处偏离：纪元与策略哈希在表中位于 P2，实际却渲染在 P1 的行块内 ——
因为对受治理的运行来说，它们属于「这次运行在哪里」，而不属于「它得分如何」。

**P3 从来没有作为一层被建成。** 没有任何页面有带标签的 P3 层级；这个层级名在源码里
只以 `P3+ land later` 这条注记出现（`components/Overview/OverviewPage.tsx` 及该目录的
`README.md`），没有任何东西被标为 P3。P3 所指的素材确实存在，但抵达它意味着去往另一个工作区，而不是就地
展开某个东西：Governance 纪元时间线标签页上已提交纪元的详情（封存的策略正文，以及
带原始来源偏移的开启与关闭边界事务）、config 浏览器里逐叶的 provenance、Studio 启动
面板中与默认值的有效配置差分、legacy Monitor 页面上的资源与进程细节。请把 P3 读作
对素材的描述，而不是关于点击几次就能到达的承诺。

**P5 就是开发者模式，而且只在 legacy 页面上。** 这个标志是
`localStorage['ari_dev_mode']`，经由一个 hook（`hooks/useDevMode.ts`）读取，而查询
它的界面全都是 legacy 的：Monitor 的各个区块及其 GPU 监控、legacy Results 的
`publish.yaml` 编辑器、向导的资源步骤、legacy Tree 的详情面板、拥有该开关的
Settings 页面，以及根错误边界的堆栈跟踪（§2）。没有任何 v2 工作区 import 这个
hook，因此在一个 v2 页面上根本没有可打开的 P5 层级。规范还把 P5 与一次权限检查配在
一起；那一半在这里不可能存在，因为 bearer token 是全有或全无的，而且没有任何东西
对用户建模（§2）。开发者模式只改变展示密度。它不是一条授权边界，它所展现的东西也
并没有对一个直接询问 API 的未认证调用方隐藏 —— 见
[仪表盘指南](../guides/dashboard.md) 的「legacy 页面，以及何时使用它们」。

**不存在全局的 run 上下文元素。** 规范要求 P1 常驻于*每一个* run 范围的页面：作为
一块持续存在的外壳，承载项目与 run 的身份、生命周期、phase 与新鲜度、执行模式与
论文模式、带 epoch 和策略哈希的治理能力、带告警计数的资源与成本汇总，以及连接
状态。这个元素并不存在。这是一处 known gap（已知缺口），而且并不均匀：P1 所列的
大部分内容确实出现在某个页面上，只是从不集中在一处，也不是每个页面都有。

外壳自身承载的，是导航之上那个 legacy 的活动检查点选择器 —— 检查点数量、绑定到
进程级活动检查点的 `<select>`，以及直接取自 `/state` 的状态标签与运行圆点
（§4）。没有任何 v2 工作区读取其中任何一项；维持这一点的是
`src/__tests__/appContextScope.test.ts` 的结构扫描，而 v2 改从 `?run=` 取得自己的
run。因此该选择器描述的是进程级选中的那个检查点，未必就是当前打开的工作区正在
展示的 run。

其余部分按页面散落。生命周期与研究 phase 只在 run Overview 上渲染。当前 epoch 与
utility 策略哈希，在受治理的 run 上渲染于 Overview 的治理行，也渲染在 Governance
工作区内 —— 那里同样是执行模式与论文模式唯一以词汇所要求的两枚独立标签形式出现的
地方，其值读自 RQGM 能力模型（§9）。run 身份是逐页面的：每个 run 范围的 v2 工作区
都会打印自己的 `?run=` 值。连接状态同样如此 —— run Overview、Tree 工作区、
Governance 与 Projects 组合页在事件流不处于 live 时各自升起自己的新鲜度横幅，
config 浏览器则在缓存数据之上重新取数失败时升起一条，而 Ideas 与 Results 工作区
不订阅任何流，也完全不展示新鲜度。

P1 清单上有两项根本没有 run 范围的落脚点。资源与成本汇总是一个 legacy 侧的数字：
`/state` 把解析后的 `cost_summary.json` 作为 `cost` 一并送出（见
[REST API 参考](../reference/rest_api.md) 的「类型化契约（稳定端点）」），legacy
Monitor 页面把它渲染在资源卡片旁边；而 `/api/v1` 之下没有任何地方提到 cost ——
因此即便外壳有位置可放，v2 工作区也没有数字可展示。最接近告警计数的，是 Projects
组合页上的「Needs attention」磁贴，它统计状态为 `failed`、`stopped` 或 `unknown`
的 run：这是组合层面的统计量，而不是单个 run 的徽标。P1 所承诺的「下一步操作」更
单薄 —— 只有空的 Projects 页面上的创建、导入、恢复三条链接，而这三条都通向启动
向导。一个被阻塞的 run 会列出它的 blocker，然后就停在那里。

请把「P1 始终可见」当作一种逐页面的意图：run Overview 满足了它，而其他页面都不是
照此建成的。

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
