---
sources:
  - path: ari-core/ari/viz/api_capabilities.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/app/routeRegistry.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/context/AppContext.tsx
    role: implementation
  - path: ari-core/tests/test_gui_state_facade_freeze.py
    role: test
  - path: ari-core/tests/test_gui_config_shadow_legacy.py
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/appContextScope.test.ts
    role: test
  - path: ari-core/tests/test_setup_env.py
    role: test
  - path: scripts/check_viz_api_schema.py
    role: test
  - path: scripts/check_dashboard_ux.py
    role: test
  - path: scripts/check_bundle_budget.py
    role: test
  - path: scripts/snapshot_contracts.py
    role: test
  - path: scripts/setup/setup_env.sh
    role: config
last_verified: 2026-08-07
---

# GUI 切换运行手册

仪表盘刷新把 v2 工作区**并排放在** legacy 页面旁边发布：两者在同一个打包
产物中，两者都可访问，而由单个环境变量决定浏览器拿到哪套外壳。本运行手册
是这套安排的运维一半 —— 如何把 v2 提升为默认、过程中要盯什么、如何回去，
以及在删除任何 legacy 代码之前必须成立的条件。

关于行为变更本身（以前能用而现在会拒绝的东西，以及原因），见
[迁移指南 → GUI 刷新](migration.md#gui-刷新v2-仪表盘)。

**范围说明。** ARI 不发布任何遥测管道。下文的每个「信号」都是运维者从本地
接口面读到的东西 —— `/api/v1/diagnostics`、`/health/ready`、检查点的
`viz_access.jsonl` 与 `launch_events.jsonl`、服务器的 stderr，或者浏览器
开发者工具的网络面板。请把这次推出当作一次有人盯着的自食其狗粮，而不是一次
带监控的金丝雀发布。

## 1. 手段

所有手段都是在 `ari viz <checkpoint>` 启动时读取的环境变量。设置变量、重启
服务器；无需重新构建，也无需重新部署。它们连同其理由一起声明在
`scripts/setup/setup_env.sh` 中。

| 手段 | 默认值 | 翻转后的确切效果 |
|---|---|---|
| `ARI_GUI_V2` | 开启（除 `0`/`false` 之外的任何值） | `GET /api/capabilities` 报告 `gui_v2: false`；SPA 隐藏仅 v2 的导航条目，仅 v2 的路由回退到 Home。legacy 路由、legacy hash URL 以及每一个 `/api/*` 端点都不受影响。一次*失败*的能力查询被视为 `gui_v2: true`，因此 API 抖动绝不会把仪表盘搁浅在回退外壳里。 |
| `ARI_GUI_BIND` | 未设置 → `127.0.0.1` + `::1` | 任何显式取值都只绑定那一个主机：`'::'` 恢复刷新前的全接口双栈绑定，`'0.0.0.0'` 为 IPv4 通配符。非回环取值还会同时启用 `ARI_GUI_TOKEN` 闸门。 |
| `ARI_GUI_CORS_ANY` | 关闭 | `1` 在每一个以前携带该头的响应上恢复 `Access-Control-Allow-Origin: *`，取代同源回显。 |
| `ARI_GUI_CHALLENGES` | 开启 | `0` 让 `POST /api/delete-checkpoint`、`POST /api/stop` 与带 `action=stop` 的 `POST /api/gpu-monitor` 无需服务器签发的 `challenge_id` 即可执行。`POST /api/v1/challenges` 端点保留，因此两步式客户端继续工作。 |
| `ARI_GUI_CSP` | 开启 | `0` 停止在 SPA 首页与 `/static/` 上发送 `Content-Security-Policy`、`X-Content-Type-Options` 与 `Referrer-Policy`。正当用法是那种重映射了 WebSocket 端口的反向代理，否则 CSP 的 `connect-src` 会拦截树实时流。 |
| `ARI_GUI_TOKEN` | 未设置 | 在非回环绑定下，这是 `/health*` 之外每个请求都必须出示的 bearer token。在远程绑定下未设置时，服务器会在启动时生成一个 32 位十六进制 token 并向 stderr 打印一次 —— 不存在无认证的远程启动。 |
| `ARI_GUI_AUTH` | 开启 | `0` 彻底关闭远程 token 闸门（唯一合理的理由是前面有一个负责认证的反向代理）。 |
| `ARI_GUI_HEALTH` | 开启 | `0` 让 `/health/live` 与 `/health/ready` 回到 SPA HTML 回退，并让 `GET /api/v1/diagnostics` 返回类型化的 404。 |

**只有 `ARI_GUI_V2` 是推出标志。** 另外七个是安全紧急开关，每一个都会精确
地重新打开它当初所关闭的那一项风险。不要把它们固化进部署 profile 去「让
某个东西能用」；请在事故中使用它们、记录原因，然后再把它们撤掉。组合策略：
受支持的矩阵是*默认配置*，加上一次一个手段，再加上有文档记录的远程模式
组合（`ARI_GUI_BIND` + `ARI_GUI_TOKEN`）。其他任何组合都未经测试。

## 2. 切换前检查清单

每一行都是硬性关卡。请在干净的工作树上、使用固定版本的工具链运行它们 ——
一个红色基线会让整个演练失去意义，因为你再也分不清一次切换回归与一个既有
失败。

| 关卡 | 命令 | 通过条件 |
|---|---|---|
| 前端类型 | `cd ari-core/ari/viz/frontend && npm ci && npm run typecheck` | 退出码 0 |
| 前端单元 / a11y / 契约测试套件 | `cd ari-core/ari/viz/frontend && npm test` | 退出码 0 —— 包含路由/导航一致性、外壳 a11y 基线、Settings 契约、外部脚本守卫、workflow revision、Studio 启动，以及危险操作等套件 |
| 生产构建 | `cd ari-core/ari/viz/frontend && npm run build` | 退出码 0，产物位于 `ari-core/ari/viz/static/dist/` |
| 打包体积预算 | `python scripts/check_bundle_budget.py --fail-on-regression` | 退出码 0，无净新增违规（构建之后运行） |
| 后端 + viz 测试 | `python -m pytest ari-core/tests -q` | 退出码 0 |
| 安全回归套件 | `python -m pytest ari-core/tests -q -k "gui_bind_cors or gui_path_proxy_hardening or gui_confirmation_challenges or gui_csp_headers or gui_remote_auth or gui_secret_readiness or gui_workflow_write_guard"` | 退出码 0 —— 这些是 MN-2/4/5/6/7/8 的拒绝行为 |
| legacy 外观冻结 | `python -m pytest ari-core/tests/test_gui_state_facade_freeze.py -q` | 退出码 0 —— `/state` 既没增长也没缩减 |
| 配置/启动影子一致性 | `python -m pytest ari-core/tests/test_gui_config_shadow_legacy.py -q` | 退出码 0 —— legacy Settings 保存+启动与新解析器逐叶子一致，只允许显式列入白名单的分歧 |
| 契约快照 | `python scripts/snapshot_contracts.py --surface all --check` | 退出码 0 —— `viz` 接口面固定了 REST 清单与响应键 |
| OpenAPI 新鲜度 | `python -m ari.viz.v1.openapi`（在 `ari-core/` 下） | 退出码 0 —— 已提交的 `ari/viz/v1/openapi.json` 与路由器一致 |
| REST schema 漂移 | `python scripts/check_viz_api_schema.py --fail-on-regression` | 退出码 0，相对冻结允许列表无净新增漂移 |
| 仪表盘 UX 检查器 | `python scripts/check_dashboard_ux.py --fail-on-regression` | 退出码 0，允许列表未增长 |
| 文档关卡 | `python scripts/check_docs_source_sync.py`、`python scripts/docs/check_doc_sources.py`、`python scripts/readme_sync.py --check`、`python -m pytest scripts/tests/ -q` | 全部退出码 0 |

然后在运行中的服务器上（回环默认配置）验证安全姿态：

```bash
ari viz /path/to/checkpoint --port 8765 &

curl -s http://127.0.0.1:8765/health/live                 # {"status":"ok"}
curl -s http://127.0.0.1:8765/health/ready                # status ok|degraded, five checks
curl -si http://127.0.0.1:8765/ | grep -i 'content-security-policy\|nosniff\|referrer-policy'
curl -si -X POST http://127.0.0.1:8765/api/stop -d '{}'   # 428, no process touched
curl -s 'http://127.0.0.1:8765/codefile?path=/etc/passwd' # 404
ss -ltnp | grep 8765                                      # bound to 127.0.0.1 / ::1 only
```

目前**没有**被机器强制的关卡，因此必须人工签字确认：

- **浏览器性能指标**（LCP/INP/CLS、路由交互延迟）。jsdom 测试装置无法测量
  布局、绘制或输入时序，而共享 CI runner 的噪声太大，撑不起一个通过/失败
  预算。打包体积*确实*被强制（`check_bundle_budget.py`）；浏览器那一半是在
  一台固定机器上的人工 profile，并记录进发布证据。
- **跨浏览器关键路径。** 这些套件是 vitest/jsdom；本仓库中唯一的 Playwright
  运行是文档截图采集（`npm run capture:screenshots`，仅 headless Chromium），
  它不做任何断言。关键路径（Settings、新建运行、启动、恢复、监控、树/结果、
  workflow、RQGM、安全）在把某项改为默认开启之前需人工走一遍。

## 3. 分阶段推出

请让每一个剩余切片走完这三个阶段。「切片」是一个路由或一个工作区，而不是
整套外壳 —— 标志策略被有意设计为按切片粒度，这样出问题时回滚的是一个页面，
而不是整个仪表盘。

**阶段 1 —— 自食其狗粮。** 只限维护者，在他们自己的检查点上，标志开启。
请使用带真实工件的真实运行，而不是 fixture。要盯的是：对同一个运行，v2
工作区显示的数字与 legacy 页面是否一致？第二个标签页中的第二个运行是否
保持隔离？当该切片自己的测试全绿且没有任何 legacy/v2 分歧未解决时退出该
阶段。

**阶段 2 —— 选择加入。** v2 路由可访问且有文档，legacy 路由保留其导航条目，
由用户自行选择。要盯的是：人们实际打开的是哪一个，以及是否有人在任务中途
退回 legacy。当该切片已在大型检查点、损坏/不完整检查点以及旧的（刷新前）
检查点上被实际使用过时退出该阶段。

**阶段 3 —— 默认开启。** v2 路由通过路由注册表的 `navReplaces` 接管 legacy
导航位置，因此侧边栏条目看起来完全一样，只有它写入的 hash 变了。**legacy
URL 在两种模式下都继续工作** —— 这就是一致性不变式，也正是它让 §5 的回滚
可以瞬间完成。当该切片在带有回滚手段的情况下默认开启地跑满至少一个小版本
之后退出该阶段。

该计划目前的进展：`ARI_GUI_V2` 以**默认开启**发布；Projects、Overview、
Governance、ConfigBrowser 与 Studio 拥有各自的导航条目；TreeV2、IdeasV2 与
ResultsV2 已通过 `navReplaces` 接管了 Tree、Idea 与 Results 位置；
Settings、Wizard、Monitor、Workflow、Home、Experiments 与 PaperBench 仍是
带有 legacy 导航条目的 legacy 页面。Settings → Studio 与 Wizard → Studio
启动是仍需走完阶段 1–3 的切片。

任何阶段中都要盯的信号（全部本地读取）：

| 信号 | 在哪里读 |
|---|---|
| 路由成功/错误、schema 不匹配、适配器不匹配 | 浏览器开发者工具网络面板；类型化的 `/api/v1` 错误信封携带一个 `request_id`，它也会出现在 `viz_access.jsonl` 中 |
| 配置校验失败类别、保存冲突率 | 草稿的 `validate` 响应（`details.errors` 路径）与 workflow 409 冲突横幅 |
| 启动 accepted / started / failed、幂等键碰撞 | `{checkpoint}/launch_events.jsonl`（`draft → validating → accepted → spawned` / `failed`）与 `{workspace_root}/gui_store/launches/` |
| SSE 重连 / 回退、投影器滞后、陈旧视图 | `GET /api/v1/diagnostics`（`sse.subscribers`、`sse.buffer_len`、`watcher.last_scan_age_s`）与 `GET /health/ready`（`degraded` 并点名失败的检查） |
| legacy 路由 / legacy API 的回退使用量 | `viz_access.jsonl` 中的请求路径 —— 某切片默认开启之后仍出现的 legacy `/api/*` 与 `/state` 访问 |
| 打包体积 | `python scripts/check_bundle_budget.py`（按 chunk 的 gzip 大小对比类别预算） |
| 浏览器性能分位数 | 在固定参考机器上的人工 profile（不由 CI 强制） |

## 4. 停止与回滚条件

一旦出现下列任一情况，就停止推出 —— 或者回滚一个已经默认开启的切片。本清单
就是发布关卡；在推出继续进行的同时，不要把其中任何一行软化成一张后续工单。

- **跨运行数据混淆、secret 暴露，或未授权变更。** 这三者中的任何一个都是
  立即全面停止，而不是切片回滚：转到 §5.3。
- **配置或启动的影子不匹配超出阈值。** legacy 的保存+启动路径与新解析器必须
  逐叶子一致，只允许显式列入白名单的分歧；出现新的分歧就停止推出。
- **得分谱系与源事件不一致。** 治理读模型不重新推导任何东西 —— 如果所展示的
  谱系与 `rqgm_transitions.jsonl` / `rqgm_audit.jsonl` 不符，那么该视图就是
  错的，必须停止。
- **旧检查点或 `simple_bfts` 身份回归。** 刷新前的检查点必须原样打开，而
  `simple_bfts` 运行必须与刷新前的 ARI 保持逐字节一致。
- **关键路径、a11y 或性能硬关卡失败。** §2 中的任何红色关卡，包括那些人工
  签字的。

## 5. 分层回滚流程

请回滚能修复症状的*最窄*那一层。只有 §5.3 需要动到一个正在进行的实验。

### 5.1 标志层（数秒，无需重新构建）

```bash
export ARI_GUI_V2=0
# restart: ari viz /path/to/checkpoint --port 8765
```

随后 `GET /api/capabilities` 报告 `gui_v2: false`；侧边栏去掉 v2 条目，
仅 v2 的路由回退到 Home，而 legacy 页面回到它们自己的位置。每一个 legacy
hash URL 与每一个 `/api/*` 端点原本就在工作，因此别的什么都不会改变。由 v2
写下的草稿、模板与 `resolved_config.json` 留在磁盘上，只是不再被 legacy
页面读取。

### 5.2 打包产物层（数分钟）

如果问题出在构建产物而不是标志上，请恢复上一版已发布的
`ari-core/ari/viz/static/dist/` 目录树（SPA 首页与 `/static/` 直接由它提供）
并重启。如果你需要从一个已知良好的提交重新切出它，请在
`ari-core/ari/viz/frontend` 下用 `npm ci && npm run build` 重新构建。请把
上一版打包产物至少保留一个小版本 —— 那段保留期*就是*回滚窗口。

### 5.3 安全手段（事故路径）

当触发原因是暴露而非 UI 缺陷时使用这些。按顺序：

1. **重新绑定到回环。** 取消设置 `ARI_GUI_BIND`（以及 `ARI_GUI_CORS_ANY`）
   并重启。此后服务器只监听 `127.0.0.1` + `::1`，并且只为自身 origin 回显
   CORS。再通过 SSH 本地转发访问它。
2. **吊销 token。** 更改或取消设置 `ARI_GUI_TOKEN` 并重启：之前签发的每个
   token 立即失效（未设置该变量的远程绑定会铸造一个新的，并向 stderr 打印
   一次）。请告知运维者清除浏览器 `localStorage` 中的 `ari_gui_token` 键。
   由于访问日志把 `token=` 脱敏为 `***`，旧 token 无法从
   `viz_access.jsonl` 中恢复。
3. **停止进程。** `POST /api/stop` 需要来自 `POST /api/v1/challenges` 的
   挑战（`action: "stop-all"`、`target: "*"`）；两步式正是要点所在，因此
   这里不要去动 `ARI_GUI_CHALLENGES=0`。另外，请在带外停止 `ari viz` 进程
   本身 —— 由 GUI 启动的运行是独立的 `python3 -m ari.cli run` 子进程，它们
   会在服务器之后继续存活，因此若事故需要，请显式停止它们。
4. 在放任何人回来之前，**重新跑一遍 §2 的姿态检查**。

### 5.4 数据安全

没有什么需要撤销。这次刷新写下的一切都是增量新增的 ——
`{checkpoint}/resolved_config.json`、`{checkpoint}/launch_events.jsonl`、
`{workspace_root}/gui_store/`（草稿、模板、启动占位）—— 而更旧的 ARI 会
全部忽略它们。没有任何检查点被原地改写，因此回滚永远不需要降级迁移。请在
一次回滚演练中确认：一个正在运行的运行、一份打开的草稿、已保存的设置、一份
被编辑过的 workflow，以及 RQGM 各视图，在标志翻转后全都安然无恙。

## 6. legacy 移除

**标志卫生。** 推出标志是一张时间表，而不是一个安身之所，而本节就是这张
时间表的终点。`ARI_GUI_V2` 是该计划唯一的推出标志（§1）；只要它还活着，
每一个被替代页面的新旧两代就都装在同一个打包里 —— 双份的缺陷面、双份的
测试面，以及任何报告里都挥之不去的「用户当时看到的是哪一个？」的歧义。
因此，一个推出标志在被引入时就要把它的退役条件定下来 —— 一个具名 owner、
回滚手段，以及承诺让它消失的关卡或版本 —— 并把这些声明在读取该标志的模块
的 docstring 里。`ARI_GUI_V2` 在 `ari-core/ari/viz/api_capabilities.py` 中
正是这么做的：owner、默认值、回滚手段、移除关卡。它的期限是一道关卡，而不是
一个日期；该模块与 `docs/reference/environment_variables.md` 把这道关卡称为
`G6`，它指的就是 legacy 移除 —— 也就是本节。没有任何推出标志能比它活得更久：
当下面这张表走完时，标志会随它所守护的外壳一起被删除；而一个已经满足了关卡
却仍在发布中的标志，是一个待分诊的缺陷，而不是一个配置项。以上这些都没有被
机器检查。被自动化的只有更窄的一部分：第一方 Python 读取的每一个环境变量都
必须声明在 `scripts/setup/setup_env.sh` 中
（`ari-core/tests/test_setup_env.py::test_setup_env_covers_all_source_env_vars`），
它强制一个新标志必须可见，但对它的 owner 或期限只字不提。§1 中的七个安全
紧急开关是另一种工具、遵循另一条规则 —— 仅在事故中使用 —— 下面的内容并不
安排它们的移除。

移除是一个与「默认开启」分开的决策，而且是单向的。在**所有**下列条件成立
之前，下面的任何东西都不得被删除：

- 替代它的 v2 切片已在带有回滚手段的情况下默认开启地跑满至少一个小版本，
  且回滚演练通过；
- 使用证据表明该 legacy 接口面已无人使用（在观察窗口内，`viz_access.jsonl`
  中没有针对被替代页面的 legacy 路由或 legacy `/api/*` 访问）；
- §7 的兼容性矩阵已重新跑过并全绿；
- 该移除（或一次显式的保留决定）已记录为 ADR，而任何公共 API 的移除都遵循
  `CONTRIBUTING.md` 与 `docs/about/release_policy.md` 中的弃用计划 ——
  如果它是一次破坏性移除，就要放进主版本发布。

请按以下顺序移除。该顺序是一条依赖链：每一项的消费者都必须先于它消失。

| # | 移除项 | 绑定的关卡 |
|---|---|---|
| 1 | **legacy 页面** —— Settings、Wizard、Tree、Idea、Results 与 Workflow 页面，一次一个 | 替代它的工作区自身的能力 / a11y / 性能关卡全绿，并且在同一次变更中重新冻结路由–导航一致性测试与仪表盘 UX 检查器的隐藏路由允许列表 |
| 2 | **AppContext 远程状态** —— `context/AppContext.tsx`，即 5 秒一次的 `/state` 轮询、树 WebSocket 镜像与全局活动检查点 | 上面每个 legacy 页面都已消失，且结构守卫 `src/__tests__/appContextScope.test.ts` 在**没有**任何例外条目的情况下通过（它唯一有文档记录的例外，即 IdeasV2 的研究目标卡片，必须先改为从 `/api/v1` 取数） |
| 3 | **`/state` 外观** —— `routes.py` 中的 `/state` 分支与 `services/state_service.build_app_state` | AppContext 已消失；`test_gui_state_facade_freeze.py` 在同一次变更中退役（它存在的全部目的就是在这次删除*之前*禁止其增长），并重新生成 `viz` 契约快照 |
| 4 | **端口 +1 的 WebSocket** —— `ws_serve` 服务器、`websocket.py` 与 `hooks/useWebSocket.ts` | 每一个实时消费者都改读 `GET /api/v1/events/stream`；只有到那时才可以从 CSP 的 `connect-src` 中去掉 `ws://`/`wss://` 来源，因为那条放行规则完全是为这个 socket 而存在的 |
| 5 | **重复的常量与 CSS** —— legacy 路由/导航字面量与重复的设计 token | 路由注册表是路由、导航与别名的唯一来源（一致性测试全绿），且没有任何 legacy 页面导入这些重复项 |

每次移除之后，请重新生成契约快照
（`python scripts/snapshot_contracts.py --surface viz --update`）并重跑完整的
§2 检查清单。一次需要让允许列表*增长*的移除，就是还没准备好。

## 7. 兼容性矩阵

在 §6 的任何移除之前重跑这个矩阵，并把结果记录进发布证据。它与该计划用作
切换关卡的矩阵是同一个：

- 全新安装 × 升级；
- legacy UI × v2 UI，各自对 legacy `/api/*` 与规范 `/api/v1`；
- `simple_bfts` × RQGM 探索开/关 × 论文模式开/关；
- 新运行 × 恢复 × 克隆；
- laptop × HPC profile × cloud profile；
- 本地回环 × SSH 隧道 × HPC 反向代理；
- 小 × 中 × 大 × 损坏的检查点；
- 英文 × 日文 × 中文。

## 另请参阅

- [迁移指南 → GUI 刷新](migration.md#gui-刷新v2-仪表盘) —— 每一项用户可见
  变更的前后对比及其回滚手段。
- [HPC 设置指南](hpc_setup.md) —— 隧道与远程操作。
- [故障排查](troubleshooting.md) —— 运行时故障及其修复。
- `scripts/setup/setup_env.sh` —— 已声明的 `ARI_GUI_*` 手段及其理由，形式与
  安装脚本写入 `.env` 的内容一致。
