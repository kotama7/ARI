---
sources:
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/v1/errors.py
    role: implementation
  - path: ari-core/ari/viz/v1/events.py
    role: implementation
  - path: ari-core/ari/viz/v1/logs.py
    role: implementation
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/viz/v1/openapi.json
    role: schema
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_experiment.py
    role: implementation
  - path: ari-core/ari/viz/checkpoint_api.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/ari/viz/api_workflow.py
    role: implementation
  - path: ari-core/ari/viz/api_orchestrator.py
    role: implementation
  - path: ari-core/ari/viz/ui_helpers.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Workflow/WorkflowPage.tsx
    role: implementation
  - path: ari-core/tests/test_gui_state_facade_freeze.py
    role: test
  - path: ari-core/tests/test_workflow_editor.py
    role: test
  - path: ari-core/tests/test_orchestrator.py
    role: test
  - path: ari-core/tests/test_gui_baseline_settings_contract.py
    role: test
  - path: ari-core/ari/viz/frontend/src/components/Monitor/__tests__/MonitorPage.test.tsx
    role: test
last_verified: 2026-08-16
---

# REST API 参考

viz 仪表盘服务器（`ari viz` → `ari-core/ari/viz/server.py`）**并行**暴露两个
HTTP 接口面：

- **`/api/v1` —— 规范的带版本 API。** 在
  `ari-core/ari/viz/v1/router.py` 中以声明式方式分发，使用带类型的 pydantic
  DTO、带类型的错误信封，以及一份已提交的 OpenAPI 3.1 文档。所有新功能都
  落在这里。
- **无版本的 legacy API**（`/state`、`/api/*`）—— 一个为 legacy 仪表盘页面
  保持字节级兼容的**冻结外观（frozen facade）**。下文仅作参考记录；请不要
  再扩展它。

两者都由 `viz/routes.py` 分发；`/api/v1/` 分支委托给
`v1/router.py:dispatch()`，其余每个分支都保留其历史处理器。

## 传输基础

- Base URL：`http://127.0.0.1:<port>`（端口由 `ari viz` 设置默认值）。
- 服务器默认**仅绑定回环地址**（`127.0.0.1` + `::1`）；`ARI_GUI_BIND` 用于
  显式选择远程绑定。
- CORS **仅做同源回显** —— 只有当请求的 `Origin` 与服务器自身的 origin 一致
  时才会被回显。`ARI_GUI_CORS_ANY=1` 可恢复历史上的
  `Access-Control-Allow-Origin: *`。
- 认证：**回环绑定时完全不需要**；在非回环绑定下，除 `/health*` 前缀外的
  每个请求都必须携带 `Authorization: Bearer <ARI_GUI_TOKEN>`（见
  [认证](#认证)）。
- 除非另有说明，所有响应体均为 JSON。
- SPA 首页与 `/static/*` 会带上 `Content-Security-Policy`、
  `X-Content-Type-Options: nosniff` 与 `Referrer-Policy: no-referrer`
  （`ARI_GUI_CSP=0` 会去掉它们）。API / JSON 响应有意保持不变。

支配上述所有行为的 `ARI_GUI_*` 变量列在
[环境变量 → GUI 服务器](environment_variables.md#gui-服务器-ari-gui)。

---

## `/api/v1`（规范接口）

### 版本策略

| 方面 | 规则 |
|---|---|
| URL 版本 | `/api/v1`。破坏性变更意味着一个新的路径前缀，绝不会在 `v1` 之下悄悄改变。 |
| 载荷版本 | 每个资源 DTO 都携带 `schema_version: 1`（`ari/viz/v1/dto.py` 中的 `Literal[1]`），因此消费者仅凭响应体就能判断契约修订版本。 |
| 变更策略 | **只增不改**：新的可选字段可能随时出现；`v1` 内既有字段既不会被删除也不会被改变类型。客户端必须忽略未知键。 |
| 文档版本 | OpenAPI 文档中的 `info.version`（当前为 `1.0.0`，常量 `OPENAPI_INFO_VERSION`）；`GET /api/v1/diagnostics` 将其作为 `openapi_version` 报告。 |
| 解析器版本 | 配置接口面对其*解析算法*单独版本化：`GET /api/v1/config/schema`、`.../resolved-config` 与草稿 resolve 端点上的 `resolver_version: "legacy-compatible-1"`。 |
| 错误码 | 错误码词汇表是冻结的，只以增量方式扩展（`ari/viz/v1/errors.py` 中的 `ERROR_CODES`）。 |

### 机器可读来源

`ari-core/ari/viz/v1/openapi.json` 是已提交的机器可读契约。它由路由表加上
pydantic DTO schema **确定性生成** —— 键已排序、无时间戳、无 commit SHA ——
因此可 diff 且有漂移防护：

```bash
python -m ari.viz.v1.openapi            # verify committed == regenerated (default)
python -m ari.viz.v1.openapi --update   # regenerate ari/viz/v1/openapi.json
```

当已提交的文档与生成器产生漂移时，`ari-core/tests/test_gui_v1_api.py` 会失败。
永远不要手工编辑 `openapi.json`；请编辑 `router.py` / `dto.py` 后重新生成。

有三个路由**故意不**出现在 `openapi.json` 中，因为它们不是 v1 路由器的
JSON 请求/响应操作：SSE 流 `GET /api/v1/events/stream`（由 `routes.py` 直接
提供）以及 `/health/live` / `/health/ready` 探针（由 `ari/viz/health.py` 在
`/api/v1` 命名空间之外提供）。它们记录在下文的端点表中。

### 错误信封

每个 `/api/v1` 失败都是同一种 JSON 形状（`ari/viz/v1/errors.py`）：

```json
{
  "error": {
    "code": "not_found",
    "message": "unknown run: 20260726T101500_matmul",
    "details": null,
    "request_id": "req-4f2a91c7b0de",
    "retryable": false
  }
}
```

| 字段 | 含义 |
|---|---|
| `code` | 下列冻结错误码之一。请基于它做分支，绝不要基于 `message`。 |
| `message` | 人类可读的英文文本，可安全展示。绝不包含堆栈跟踪。 |
| `details` | 可选的结构化载荷（例如校验用的 `{"errors": [...]}`，修订冲突用的 `{"expected": n, "actual": m}`）。未使用时为 `null`。 |
| `request_id` | `req-<12 hex>`，每次分发生成一个。**成功**响应也会在顶层回显同一个 `request_id`，因此 UI 可以在缺陷报告中引用它。 |
| `retryable` | 仅在重试有可能成功时为 `true`（目前只有 `internal`）。 |

冻结的错误码词汇表：

| `code` | HTTP | 触发条件 |
|---|:--:|---|
| `not_found` | 404 | 没有匹配的路由，或所寻址的 run / project / template / draft / node / epoch / secret 不存在。也用于「该 run 不是 RQGM run」。 |
| `invalid_request` | 400 | JSON 请求体格式错误、请求体不是对象、`If-Match` 格式错误、`cursor`/`limit` 超出范围，或配置 patch 被拒绝（违规路径随 `details.errors` 返回）。 |
| `revision_conflict` | 409 | `If-Match` 与已存储的文档修订号不符。`details` 携带 `{expected, actual}`。 |
| `already_exists` | 409 | 仅用于创建的 `POST` 命中了已存在的文档 —— 目前只有 `POST /api/v1/run-templates` 使用了已被占用的 `template_id`。 |
| `internal` | 500 | 处理器出现未捕获异常。`retryable: true`；会暴露异常类型 + 消息，但不暴露 traceback。 |

HTTP `401`（缺失/无效的 bearer token）与 `428`（缺失确认挑战）产生于 v1
信封构造器*之外* —— 见[认证](#认证)与[确认挑战](#确认挑战)。

### 乐观并发（`If-Match` / 修订号）

GUI 配置文档（project 配置、run 模板、run 草稿）由 `ari/viz/v1/store.py`
存储，每个文档带一个整型 `revision`，从 `1` 开始，每次成功写入后递增。该
修订号就是乐观并发令牌：

- 每个文档响应体都携带 `revision`（**没有** HTTP `ETag` 头 —— 修订号随
  JSON 响应体传递）。
- `PATCH` 与 `DELETE` 要求 `If-Match: "<revision>"` 头。带引号的 ETag 形式
  （`"3"`）与裸整数（`3`）都被接受；弱验证器（`W/"3"`）不被接受 —— 修订号
  是精确匹配的。
- 变更操作**缺失** `If-Match` 返回 `400 invalid_request`（由处理器强制要求，
  以便消息能指明是哪个变更操作）；**格式错误**的值同样是
  `400 invalid_request`。
- **过期**的值返回 `409 revision_conflict`，并带
  `details: {"expected": <yours>, "actual": <stored>}`。请重新 `GET`，将你的
  编辑重新应用到更新后的文档上，再重试。
- `revision 0` 表示「该文档必须尚不存在」—— 内部就是这样表达仅创建写入的。
- 不存在的 project 配置文档读出来是 `revision: 0` 加空值集合；因此对应的
  第一次 `PATCH` 应发送 `If-Match: "0"`。
- 写入是原子且持久的（同目录临时文件 + `fsync` + `os.replace`，文件权限
  `0o600`，目录 `0o700`），因此写入中途崩溃会保留前一版文档的字节完整性。

`POST /api/v1/run-templates` 仅用于创建，不接受 `If-Match`：已存在的 id 会
得到 `409 already_exists`。

### 游标约定

有三个集合使用指向其追加写入源文件的**字节偏移游标**分页，这使得分页在
文件增长期间依然稳定：

| 端点 | 源工件 | 游标单位 |
|---|---|---|
| `GET /api/v1/runs/{run_id}/logs` | `{ckpt}/ari.log` | 原始字节偏移 |
| `GET /api/v1/runs/{run_id}/rqgm/transitions` | `{ckpt}/rqgm_transitions.jsonl` | 已提交条目的字节偏移 |
| `GET /api/v1/runs/{run_id}/rqgm/audit` | `{ckpt}/rqgm_audit.jsonl` | 一行的字节偏移 |

三者共同遵守的规则：

- **无空洞、无重复。** 一页选取位于游标处及其之后的记录，并返回
  `next_cursor` = 它*未*提供的第一个字节偏移（到达末尾时为 `null`）。
  沿着 `next_cursor` 走恰好遍历文件一次。
- **只读已提交内容。** 末尾缺少换行符的行是一次撕裂的追加：它绝不会被
  发出，游标会停在它的第一个字节处，这样一旦换行符落盘该行就会被提供一次。
  对于 RQGM 转换日志，没有对应 commit 的 `epoch_transaction_prepare`
  （以及它之后的所有内容）同样不会被采纳进当前状态。
- **有界的工作量。** 日志的 `limit` 默认 200（上限 1000），RQGM 页面为
  20（上限 100）；日志读取器另外限制每个请求最多扫描 1 MiB，因此任何请求
  都不会读完整个 5 MB 日志。
- **过滤器绝不移动游标。** 日志上的 `?grep=`（大小写不敏感子串）与审计页面
  上的 `?record_type=` / `?epoch=` 只决定被扫描到的记录中哪些被*返回*；
  游标同样会跨过不匹配的记录，因此即使过滤条件在两次请求之间发生变化，
  分页链依然保持一致。
- **超出范围的值会被拒绝**，而不是被截断：负数/非整数的 `cursor`，或超出
  范围的 `limit`，都会得到 `400 invalid_request`。
- RQGM 页面上的 `source_revision` 是源文件已解析的字节长度（排除撕裂的
  尾部）—— 一个廉价的「日志是否增长了？」检查。

`GET /api/v1/runs/{run_id}/rqgm/score-rewrites` 同样接受 `cursor`/`limit`，
但它的游标是指向确定性合并后的改写列表的**整数下标**（它是跨两个日志的
连接，而非单文件扫描）。

**这四个端点就是分页接口面的全部 —— 树不在其中。**
`GET /api/v1/runs/{run_id}/tree` 既不接受 `cursor` 也不接受 `limit`；它唯一的
参数就是路径中的 `run_id`，在 `ROUTES` 表和 `openapi.json` 中都是如此。
`queries.get_run_tree` 把检查点交给 `tree_view` 适配器，并把找到的每个节点放进
一个 `TreeV1` 响应体一次性返回；该响应体携带的 `revision` 是解析出的树文件的
`st_mtime_ns` —— 一个变更检测器，而不是分页令牌。因此一个有一万个节点的 run
每次抓取都会传输一万个节点；又因为实时事件是失效通知而不是数据（见下文
*实时：`GET /api/v1/events/stream`（SSE）*），只要树查询处于挂载状态，一条
`tree` 事件就意味着一次完整的重新抓取。服务器端没有任何东西为此设界：v2 树界面
的深度受限默认视图与窗口化侧表
（`ari-core/ari/viz/frontend/src/components/TreeV2/treeLod.ts`）减少的是*渲染*量，
而不是传输量。**对树的游标分页由 GUI 刷新计划规定过，但并未实现** —— 这是一个
已知缺口。在它被补上之前，请按 run 而不是按请求来估算这个端点的开销。

### 实时：`GET /api/v1/events/stream`（SSE）

单一的 Server-Sent Events 流只承载**失效通知，而非状态**：收到任何事件后，
客户端重新抓取被点名的快照资源。权威数据始终来自一次普通的 GET。

查询参数：`run_id`（过滤到单个 run）、`topics`（逗号分隔）、
`last_event_id`（无法设置请求头时的续传游标）、`token`（远程模式认证）。

事件载荷：

```
id: 42
event: resource.changed
data: {"event_id":"42","run_id":"20260726T101500_matmul","topic":"tree",
       "revision":7,"occurred_at":"2026-07-26T10:20:31Z",
       "kind":"resource.changed",
       "resource":"/api/v1/runs/20260726T101500_matmul/tree","payload":{}}
```

| 方面 | 契约 |
|---|---|
| 主题（topic） | 已发布的词汇表冻结为 `run` 与 `tree`（`events.TOPICS`）。`tree` 由状态监视器发布（镜像 legacy WebSocket 广播）；`run` 在检查点切换以及一次 v1 启动之后发布。 |
| `resource` | 需要重新抓取的 `/api/v1` 快照 —— `tree` 对应 `.../tree`，`run` 对应 `.../summary`（发布方可以覆盖它）。 |
| `revision` | 按 `(topic, run_id)` 维护的计数器，客户端可据此发现自己漏掉了某个资源的一次失效通知。 |
| `event_id` | 进程生命周期内单调递增的整数，序列化为字符串，作为 SSE 的 `id:` 字段发出。 |
| 重放 | 连接时服务器会重放缓冲区中 id 大于 `Last-Event-ID` 的事件（请求头优先；`?last_event_id=` 是回退方案，因为 `EventSource` 无法设置请求头）。缓冲区是一个 1000 事件的环形队列 —— 被挤出去的事件就是没了，而这之所以安全，恰恰是因为事件不是事实来源：重连后的重新抓取会覆盖这个空档。 |
| 心跳 | 空闲每 15 秒发送一条 `: heartbeat` 注释，以免代理断开连接。流开启时发送 `: connected` + `retry: 5000`（浏览器的重连延迟）。 |
| 重连 | 流窗口上限为 300 秒；到期时服务器写入 `: stream-timeout - reconnect` 并关闭，客户端携带其 `Last-Event-ID` 重连。客户端主动断开则静默结束流。 |

**不存在事件历史资源。** 这条流是 `/api/v1` 拥有的唯一事件接口面 —— 它由 `routes.py`
中自己的分支提供，而 `ROUTES` 表里没有任何按 run 划分的事件路径。**按 run 的事件历史
（`GET /api/v1/runs/{run_id}/events`）由 GUI 刷新计划规定过，但并未实现** —— 这是一个
已知缺口。被 1000 条事件的环形缓冲挤出去的内容，以及当前服务器进程启动之前发布的
全部内容，都已丢失；这之所以可以接受，仅仅因为事件是失效通知，重连后的重新抓取会
覆盖这个空档。

按 run 持久化的唯一生命周期记录是 `{ckpt}/launch_events.jsonl`，由 v1 启动追加写入
（`draft` → `validating` → `accepted` → `spawned`，若 spawn 本身抛错则为 `failed`）。
没有任何端点提供它，因此只能直接从磁盘读取 —— 这正是
[GUI 切换运行手册](../guides/gui_cutover_runbook.md)的*3. 分阶段推出*把它列为待观察
信号之一的原因。

**阶段（stage）转换同样不是事件。** 向总线发布的调用点共有三处 —— 状态监视器
（`tree`）、检查点切换（`run`）以及 v1 启动（`run`，`payload.lifecycle` 为
`spawned`）—— 没有任何东西发出按阶段划分的 `started` / `completed` / `failed` 事件。
上面那个生命周期文件也止于 `spawned`：此后服务器与被启动的 CLI 都不会再向它追加。
因此 spawn 之后 run 的状态是在每次读取时从工件重新推导出来的
（`ari/viz/v1/queries.py` 中的 `_run_summary_from_dir`），分三层 —— pid 探测，然后是
树中节点的状态，然后是可解析的 `review_report.json` —— 取值为 `unknown` / `running` /
`stopped` / `completed` 之一。进程已经死亡、但树里仍有节点标记为 `running` 的 run，会
被读成 `stopped`。这是从工件做出的推断，而不是被上报的结果：不要把 `status` 当作
生命周期事件日志来读。

### 认证

信任模型由**绑定方式**决定，而非由某个设置项决定（`ari/viz/auth.py`）：

- **本地模式**（默认 —— `ARI_GUI_BIND` 未设置，因此绑定为回环）：完全不做
  认证。即使碰巧导出了 `ARI_GUI_TOKEN`，请求形状也与引入认证之前的构建
  完全一致。
- **远程模式**（`ARI_GUI_BIND` 指定了非回环主机，包括通配符 `::` /
  `0.0.0.0`）：除 `/health*` 前缀外的每个 HTTP 请求都必须发送
  `Authorization: Bearer <token>`。缺失/错误 → `401`，带有类型化的 JSON
  响应体与 `WWW-Authenticate: Bearer`。比较是常量时间的。
- 如果在远程绑定时未设置 `ARI_GUI_TOKEN`，服务器会在启动时**生成**一个
  32 位十六进制 token，并向 stderr 打印一次 —— 远程绑定绝不会静默地处于
  无认证状态。
- **SSE 与 WebSocket** 接受同一个 token 作为 `token` **查询参数**，因为
  `EventSource` 与 WS 握手无法设置请求头（这是被记录在案的权衡）。访问日志
  会脱敏任何 `token=` 值，因此 token 不会进入 `viz_access.jsonl`。由 fetch
  消费的 legacy `/api/logs` 流使用请求头。
- 不使用 cookie，因此没有 CSRF 面。会话、登出与多用户不在范围内。
- `ARI_GUI_AUTH=0` 关闭该闸门（为自行终结认证的拓扑准备的、有文档记录的
  逃生舱，例如一个负责认证的反向代理）。

### 确认挑战

破坏性的 legacy 操作需要一个由 `POST /api/v1/challenges` 铸造的
**服务器签发、一次性使用的挑战**：

| 动作 | 绑定目标 | 由谁消费 |
|---|---|---|
| `delete-checkpoint` | 被删除的检查点路径 | `POST /api/delete-checkpoint` |
| `stop-all` | `"*"` | `POST /api/stop` |
| `gpu-monitor-stop` | `"*"` | 带 `action=stop` 的 `POST /api/gpu-monitor` |

响应是 `{challenge_id: "chg-<12 hex>", action, target, expires_at,
ttl_seconds: 60}`。仅当请求体中的 `challenge_id` 未被使用、未过期且绑定到
相同的 action+target 时，破坏性端点才会执行；否则它返回 HTTP `428` 与冻结
载荷 `{"ok": false, "error": "confirmation challenge required or invalid"}`，
且不执行任何操作。TTL 基于单调时钟计量（挂钟跳变无法延长它），存储是一个
有界的内存 deque（上限 100）。签发/消费/拒绝都会记入审计日志。
`ARI_GUI_CHALLENGES=0` 可恢复直接执行。

### 端点表

由 `ari-core/ari/viz/v1/openapi.json` 生成（36 个路径 / 41 个操作），按阅读
需要分组；该 JSON 文档仍是权威来源。

#### Project 与 run

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/projects` | 列出 project —— 一个聚合各检查点搜索基路径的虚拟 `default` project。 |
| GET | `/api/v1/projects/{project_id}/runs` | 某个 project 中的 run（检查点），以摘要卡片形式返回 —— 跨所有检查点根目录合并为一个组合，按新到旧（mtime 降序）。 |
| GET | `/api/v1/runs/{run_id}` | Run 详情：摘要加上由工件推导出的详情字段与一份能力映射。 |
| GET | `/api/v1/runs/{run_id}/summary` | 单个 run 的摘要卡片标量（状态、节点数、评审分数、最优指标、`has_paper`）。 |
| GET | `/api/v1/runs/{run_id}/tree` | BFTS 树 —— `tree_view` 节点列表按字节原样透传。 |
| GET | `/api/v1/runs/{run_id}/idea` | 纯读取 `{ckpt}/idea.json`（想法 / 空白分析 / 主指标）；不存在时为 `present: false`，绝不伪造空值。 |
| GET | `/api/v1/runs/{run_id}/results` | 有界的结果读模型：论文 / 评审 / ORS / EAR 的存在标志与标量 —— 绝不返回文件内容。 |
| GET | `/api/v1/runs/{run_id}/ear` | EAR bundle 清单元数据，加上策展/发布谱系标量。 |
| GET | `/api/v1/runs/{run_id}/logs` | 对 `{ckpt}/ari.log` 的一页有界游标读取（`cursor`、`limit`、`grep`）。 |
| POST | `/api/v1/runs` | 幂等启动：校验草稿、铸造 `run_id`、物化检查点、拉起 CLI。 |

#### 配置控制平面

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/config/schema` | 规范的配置字段注册表 —— 仅元数据，绝不包含生效值。 |
| GET | `/api/v1/config/catalogs/models` | 服务端的 provider/model 建议，以及每个 provider 的 API key 环境变量名。 |
| GET | `/api/v1/runs/{run_id}/resolved-config` | 既有检查点的事后解析清单（值 + 溯源 + 摘要）。 |
| GET | `/api/v1/projects/{project_id}/config` | 默认 project 的配置文档（`revision` + 扁平 `values`）。 |
| PATCH | `/api/v1/projects/{project_id}/config` | 合并-校验-写入一份局部 `{values: {dotted.path: value}}`；必须带 `If-Match`。 |
| GET | `/api/v1/run-templates` | 列出 run 模板（按码点排序）。 |
| POST | `/api/v1/run-templates` | 创建 run 模板（仅创建 → `409 already_exists`）。 |
| GET | `/api/v1/run-templates/{template_id}` | 读取单个 run 模板。 |
| PATCH | `/api/v1/run-templates/{template_id}` | 将值合并进模板；必须带 `If-Match`。 |
| DELETE | `/api/v1/run-templates/{template_id}` | 删除模板；必须带 `If-Match`。 |
| POST | `/api/v1/run-drafts` | 创建 run 草稿（服务端生成 `draft-<12 hex>` id；可选 `goal`）。 |
| GET | `/api/v1/run-drafts/{draft_id}` | 读取单个 run 草稿。 |
| PATCH | `/api/v1/run-drafts/{draft_id}` | 将值合并进草稿（goal 被保留）；必须带 `If-Match`。 |
| POST | `/api/v1/run-drafts/{draft_id}/resolve-config` | 预览该草稿完整的新 run 解析链（可选 `profile`），带溯源与警告。 |
| POST | `/api/v1/run-drafts/{draft_id}/validate` | 从同一次解析中提炼出的 `{valid, errors, warnings}`（互锁不匹配在这里是 **error**）。 |

#### Secret

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/secrets/status` | 允许列表内 secret 名称的就绪状态行（`configured` / `source_class` / `last_updated`）—— 不存在值字段。 |
| PUT | `/api/v1/secrets/{secret_id}` | 只写地设置一个允许列表内的 secret；响应是写入后的就绪状态行，绝不是值本身。 |

#### RQGM 治理（只读）

各载荷的语义见 [RQGM GUI 读模型](rqgm_gui_read_models.md)。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/runs/{run_id}/rqgm/capabilities` | 该 run 是否为 RQGM run（依据工件存在性）以及它使用哪种论文模式。 |
| GET | `/api/v1/runs/{run_id}/rqgm/overview` | 有界的治理摘要：当前纪元、策略/宪法哈希、注册表计数、完整性标志。 |
| GET | `/api/v1/runs/{run_id}/rqgm/registry` | 由已提交转换重放得到的组件与提示词，加上 rollup 校验结果。 |
| GET | `/api/v1/runs/{run_id}/rqgm/transitions` | 对已提交转换日志的字节偏移分页（`expand=1` 返回原始事件）。 |
| GET | `/api/v1/runs/{run_id}/rqgm/audit` | 对审计日志的字节偏移分页，可按 `record_type` / `epoch` 过滤。 |
| GET | `/api/v1/runs/{run_id}/rqgm/policies` | 已注册的效用策略及其一次性写入的正文与采纳溯源。 |
| GET | `/api/v1/runs/{run_id}/rqgm/score-rewrites` | 纪元边界的得分改写：策略取代与其擦除/重建后果的连接结果。 |
| GET | `/api/v1/runs/{run_id}/rqgm/nodes/{node_id}/lineage` | 单个节点的两条得分通道（对抗惩罚 vs 纪元策略改写），永不合并。 |
| GET | `/api/v1/runs/{run_id}/rqgm/epochs` | 已提交的纪元时间线，含每纪元的策略哈希与边界计数。 |
| GET | `/api/v1/runs/{run_id}/rqgm/epochs/{epoch_id}` | 单个纪元的冻结标量、活跃集合、开启/关闭事务与策略正文。 |
| GET | `/api/v1/runs/{run_id}/rqgm/evolution` | 提示词 / 效用策略 / 元候选的谱系，含显式的采纳连接。 |
| GET | `/api/v1/runs/{run_id}/rqgm/paper-archive` | 论文归档模式标量：纪元、草稿数、锚点状态、自偏好统计量、最佳信念草稿。 |

#### 运维

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/challenges` | 为一个危险操作铸造一次性确认挑战。 |
| GET | `/api/v1/diagnostics` | 有界的运维标量：SSE 总线统计、监视器存活状态、被跟踪进程数、版本号。无 secret，无路径。 |

#### 不在 `openapi.json` 中

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/events/stream` | SSE 失效流（见[实时](#实时-get-api-v1-events-stream-sse)）。 |
| GET | `/health/live` | 无依赖的存活常量 `{"status": "ok"}`。免认证。 |
| GET | `/health/ready` | 就绪状态：`status` 为 `ok` 或 `degraded`，加上一个 `checks` 对象（`http`、`websocket`、`watcher`、`event_bus`、`active_checkpoint`）。每项检查独立求值，崩溃的检查读作 `false`；降级的就绪状态是一个诚实的 `200` —— 该探针永不返回 500。免认证。 |

`ARI_GUI_HEALTH=0` 会移除全部三个健康/诊断接口面（`/health/*` 回落到 SPA
响应，`/api/v1/diagnostics` 返回类型化的 404）。

---

## 无版本的 legacy API（legacy 外观 —— 已冻结，见 MN 注记）

> **已冻结。** 下面的无版本接口面是为 legacy 仪表盘页面与既有集成保留的。
> 它**不会**被扩展：新数据必须由一个 run 显式的 `/api/v1` 端点提供。该规则写下之后
> 仍有一条路由落在这个面上 —— `GET /api/checkpoint/<id>/kca`（2026-08-05）——
> 因此它没有 OpenAPI 条目、没有类型化的错误信封、也没有 `schema_version: 1` 的
> DTO；下文按其现状记录，而非作为先例。特别是
> `GET /state`，它是一个冻结外观，其顶层键集合被
> `ari-core/tests/test_gui_state_facade_freeze.py` 精确固定（无活动检查点时
> 7 个键，检查点完全填充时 35 个键）—— 向其中添加键会按设计导致该测试失败，
> 而删除一个键会破坏 legacy 页面。

### legacy 接口面上的行为变更（MN 注记）

GUI 刷新计划改变了少数几处 legacy 行为；每一处都以编号迁移注记（MN-n）
记录，并附带其回滚手段。下文更靠后的表格列出的是*路由*，那些没有变化；
这里列出的是发生位移的*语义*。

| MN | 受影响的 legacy 端点 | 变更 | 回滚 |
|---|---|---|---|
| MN-1 | `POST /api/workflow{,/flow,/skills,/disabled-tools}` | 在没有活动检查点时，它们拒绝静默改写捆绑的 `workflow.yaml`：现在返回 `400` 且不写入任何内容。 | 只能 revert |
| MN-2 | `GET /api/env-keys` | secret 值被脱敏（`***configured***`）并添加 `redacted: true` 标记；`POST /api/env-keys` 强制名称允许列表（否则 `400`）。就绪状态迁移到 `GET /api/v1/secrets/status`。 | 只能 revert |
| MN-3 | `GET /api/workflow` + 四个 workflow 写入端点 | 增量添加 `revision`（所提供字节的 sha256[:12]）与写入时可选的 `base_revision`；过期写入会被 `409` 拒绝，而不再盲目覆盖。省略 `base_revision` 的调用方仍是最后写入者获胜。 | 只能 revert |
| MN-4 | 全部（绑定）、所有带 CORS 的响应 | 默认回环绑定 + 同源 CORS 回显。 | `ARI_GUI_BIND`、`ARI_GUI_CORS_ANY=1` |
| MN-5 | `GET /codefile`、`GET/POST /api/ollama/<path>` | `/codefile` 只提供解析后规范路径位于活动检查点或某个检查点搜索基路径之下的文件；Ollama 代理被限制在 5 条路径的允许列表内，且除非显式配置了目标或生效后端就是 Ollama，否则拒绝（`403`）。 | 无（安全修复） |
| MN-6 | `POST /api/delete-checkpoint`、`POST /api/stop`、`POST /api/gpu-monitor`（`action=stop`） | 需要服务器签发的 `challenge_id`；否则返回 `428` 且无副作用。 | `ARI_GUI_CHALLENGES=0` |
| MN-7 | `GET /`、SPA 回退、`GET /static/*` | CSP + `nosniff` + `Referrer-Policy` 响应头；打包产物中移除了 CDN `<script>`。 | `ARI_GUI_CSP=0` |
| MN-8 | 全部，在远程绑定下 | Bearer token 认证（缺失则 `401`）；SSE/WS 接受 `?token=`。 | `ARI_GUI_AUTH=0` |
| MN-9 | `GET /health/live`、`GET /health/ready` | 原先是 SPA HTML 回退；现在是 JSON 探针（外加新的 `GET /api/v1/diagnostics`）。 | `ARI_GUI_HEALTH=0` |
| MN-10 | `POST /api/launch` | **未变更** —— 规范的幂等启动是增量新增的 `POST /api/v1/runs`；两者并行运行。 | 不适用 |

### 约定（legacy）

- 错误以 `{"error": "<message>"}` 格式返回（部分处理器使用
  `{"ok": false, "error": ...}`）。它是否以非 2xx HTTP 状态码抵达客户端，取决于
  分发分支 —— 见下面的 `_status` 约定。
- CORS 预检（`OPTIONS`）在 `/api/*` 上只对同源请求作答（MN-4）。

**`_status` 弹出约定 —— legacy，且逐分支适用。** legacy 处理器只是返回 dict 的
普通函数，自身无法设置 HTTP 状态码。约定是把状态码放在响应体*内部*，形如
`{"ok": false, "error": ..., "_status": 400}`，再由 `ari-core/ari/viz/routes.py`
中的分发分支用 `self._json(r, status=r.pop("_status", 200))` 取出 —— 这一次调用
既设置线上状态码，又把这个私有键从响应体中移除。该取出动作是逐分支选择性启用的：
多数分支并不这么做，而只要其处理器从不设置 `_status`，这就是无害的。确实会取出的
legacy 分支是 `POST /api/launch`、`/api/run-stage`、`/api/sub-experiments/launch`、
`/api/upload`、`/api/env-keys`、`/api/publish/<run_id>`、`/api/gpu-monitor`、
`/api/stop`、`/api/delete-checkpoint` 以及四个 `/api/workflow*` 写入端点，外加所有
`/api/v1/` 分支。

**怪癖 —— `POST /api/settings` 会设置 `_status`，但它的分支不取出。** 它的分发是
裸的 `self._json(_api_save_settings(body))`，而 `_json` 默认 `status=200`。因此
被拒绝的保存会返回 **HTTP 200，`_status: 400` 仍留在 JSON 响应体里**（该处理器的
两处拒绝都是这样 —— 见「设置 + workflow」一节）。在 `ari/viz/` 下会设置 `_status`
的处理器中，只有它所在的分支不 pop。线上状态码也没有任何东西钉住：契约测试直接
调用处理器，因此它钉住的是 dict，而不是响应状态码。

所以 legacy 客户端必须依据响应体（`ok` / `error`）分支，而不能只看状态行。这是被
冻结外观的遗留产物，不是可以效仿的模式 —— `/api/v1` 会配合类型化的「错误信封」
（见本页上文）返回真实的状态码。

### 类型化契约（稳定端点）

流量最高的几个 GET 端点，其响应形状在
`ari-core/ari/viz/frontend/src/types/index.ts` 中有对应的前端 TypeScript
类型镜像，并由 `ari-core/tests/test_api_schema_contract.py` 守护（以**子集**
方式断言必然存在的键 —— 允许额外/可选字段，因此契约是增量式的）。`GET /state`
是例外：该测试套件没有 `/state` 用例，其键集合改由
`ari-core/tests/test_gui_state_facade_freeze.py` 以精确的冻结字面量（而非子集）钉住。

| 端点 | 生产者 | 前端类型 | 必然存在的键 |
|---|---|---|---|
| `GET /state` | `services/state_service.build_app_state` | `AppState` | `running_pid`、`is_running`、`exit_code`、`running`、`pid`、`status_label`、`llm_model` —— 冻结门面始终输出的 7 个键（其余受检查点门控 → 在类型中为可选）。`cost` 是解析后的 `cost_summary.json` **对象**（`CostSummary`），不是数字。 |
| `GET /api/settings` | `api_settings._api_get_settings` | `Settings` | 完整的默认值字典（`llm_model`、`llm_provider`、`ollama_host`、`temperature`、……，以及嵌套的 `ors`）；任意已保存的键也会透传（`{**defaults, **saved}`）。 |
| `GET /api/checkpoints` | `checkpoint_api._api_checkpoints` | `Checkpoint[]` | `id`、`path`、`status`、`node_count`、`review_score`、`best_metric`（始终为 `null`）、`mtime`；`best_scientific_score` 是有条件的。 |
| `GET /api/checkpoint/<id>/summary` | `checkpoint_api._api_checkpoint_summary` | `CheckpointSummary` | `id`、`path`（或 `{error:"not found"}`）；所有报告正文都是有条件的。`reproducibility_report` 是解析后的**对象**（legacy 运行：字符串），并非总是字符串。 |

契约是**宽松的**：可以添加新的可选字段而不破坏消费者；既有字段在迁移过程中
绝不会被删除（见重构全局规则）。

### 实战示例

最常先用到的端点的最小 `curl` 请求/响应示例。示例假设仪表盘运行在默认端口
`8765`。

**读取实时状态：**

```bash
curl http://localhost:8765/state
```

```json
{
  "checkpoint_id": "20260526T101500_matmul",
  "current_phase": "bfts",
  "node_count": 7,
  "nodes": [{ "id": "node-0", "status": "success", "metrics": {} }],
  "has_paper": false,
  "llm_model": "ollama_chat/qwen3:8b",
  "running_pid": 48213,
  "is_running": true,
  "exit_code": null,
  "status_label": "🟢 Running",
  "cost": { "total": 0.0 }
}
```

这是节选：冻结门面在没有活动检查点时恰好输出 7 个顶层键，检查点完全填充时输出
35 个。`nodes` 是树节点列表（不是计数汇总），`cost` 是解析后的
`cost_summary.json` 对象。

**启动一次运行：**

```bash
curl -X POST http://localhost:8765/api/launch \
  -H 'Content-Type: application/json' \
  -d '{"experiment_md": "# Goal\nImprove GFLOP/s of a dense matmul.\n",
       "profile": "laptop", "provider": "ollama", "model": "qwen3:8b",
       "max_nodes": 8, "max_depth": 3, "workers": 2}'
```

```json
{ "ok": true, "pid": 48213, "checkpoint_path": "workspace/checkpoints/20260526T101500_matmul" }
```

**列出检查点：**

```bash
curl http://localhost:8765/api/checkpoints
```

```json
[
  { "id": "20260526T101500_matmul", "path": "workspace/checkpoints/20260526T101500_matmul",
    "status": "running", "node_count": 7, "review_score": null,
    "best_metric": null, "mtime": 1779795300 },
  { "id": "20260520T090000_sort", "path": "workspace/checkpoints/20260520T090000_sort",
    "status": "completed", "node_count": 12, "review_score": 0.71,
    "best_metric": null, "mtime": 1779267600, "best_scientific_score": 0.83 }
]
```

该列表是跨所有检查点搜索基路径合并的一个组合，按 `mtime` 降序（新到旧）排列。
`status` 取值为 `unknown` / `running` / `stopped` / `completed` 之一。

**错误格式**（任意 legacy 端点，非 2xx）：

```json
{ "error": "no active checkpoint" }
```

### 状态 + 仪表盘

| 方法 | 路径 | 用途 | 来源 |
|---|---|---|---|
| GET | `/state` | 仪表盘实时视图使用的当前 BFTS 状态快照（**键集合已冻结**） | `routes.py` |
| GET | `/api/gpu-monitor` | GPU 利用率轮询 | `routes.py` |
| GET | `/api/resource-metrics` | CPU / 内存 / 磁盘指标 | `routes.py` |
| GET | `/api/logs` | 当前运行的最近日志行 | `routes.py` |

**`GET /state` 不是一次纯读取。** `services/state_service.build_app_state` 一开头就会
在被跟踪的启动进程已经退出时，清掉服务器缓存的实验文本
（`state._last_experiment_md`）—— 也就是说，读取这个端点会改写一个模块全局变量，
而该变量由 legacy 的 `POST /api/launch` 处理器设置、并被之后的 `/state` 响应读回 ——
而且它每次调用都会重新遍历检查点：加载树、用 glob 判断工件是否存在、检测阶段、
读取 `cost_trace.jsonl` 的尾部。legacy 外壳只要处于挂载状态，就会以固定的五秒间隔
无条件轮询它（`ari-core/ari/viz/frontend/src/context/AppContext.tsx` 中的
`STATE_POLL_MS`）。这两点都不是要在原地修掉的缺陷：这次变异是从该函数被抽取出来之前的内联 `/state`
构建器逐字保留下来的，而且两者都已排定删除 —— 轮询是
[GUI 切换运行手册](../guides/gui_cutover_runbook.md)的*6. legacy 移除*中的移除项 2，
`build_app_state` 本身则是移除项 3。把它们记在这里，是因为它们正是 `/api/v1`
被设计成「不这么做」的那件事：v1 的读取模块不去查询或修剪服务器的进程跟踪状态，
而是从文件系统重新推导 run 的状态 —— 这就是
[仪表盘架构](../concepts/gui_architecture.md)的*7. 后端接缝*里那条「`GET` 无副作用」
的性质。

**`GET /api/resource-metrics` —— 载荷形状。** `_collect_resource_metrics()`
（`ari-core/ari/viz/ui_helpers.py`）遍历 `/proc`，统计服务器自身 uid 所拥有的进程，
返回八个键：`process_count`、`memory_rss_mb`、`cpu_load_1m`、`cpu_load_5m`、
`cpu_load_15m`、`cpu_count`、`experiment_pid`（除非被启动的实验进程仍存活，否则为
`null`）以及 `timestamp`（UTC ISO-8601）。每个采样步骤各自带 `except`，因此失败降级的
是*取值*而不是丢键 —— 负载均值回落到 `0.0`，读不到的进程被跳过；现状的采集器始终
输出全部八个键。

**尽管如此，客户端仍必须把每个数值字段都当作可选。** 部分载荷曾经拖垮了整个
Monitor 路由：旧页面无条件调用 `.toFixed()`，于是 `{"process_count": 3}` 这样的
响应体抛出 `resourceMetrics.memory_rss_mb.toFixed is not a function`。修复在客户端，
由 `ari-core/ari/viz/frontend/src/components/Monitor/__tests__/MonitorPage.test.tsx`
钉住：该测试给真实页面喂入正是这个响应体，并断言存在的字段照常渲染，而缺失的字段
渲染为占位符 `—`。在编写新的消费方之前有两点值得知道。回归说明把这类响应体归因于
采样器预热、抓取错误或较旧的服务器 —— 而不是上述采集器的任何分支。另外
`ari-core/ari/viz/frontend/src/types/index.ts` 中的 `ResourceMetrics` 接口仍将八个
字段全部声明为**必填**，因此可选性存在于页面的运行时守卫（`isFiniteNumber`）里，
而不在类型里：TypeScript 消费方在这里得不到编译器帮助，必须先守卫再格式化。

### 模型 + 技能

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/models` | 发现通过 LiteLLM + Ollama 可用的 LLM |
| GET | `/api/ollama-resources` | 模型所需的内存 / 磁盘 |
| GET | `/api/ollama/<...>` | 代理到本地 Ollama 守护进程（仅允许列表内路径 —— MN-5） |
| GET | `/api/skills` | 枚举已注册的技能 + 其工具数量 |
| GET | `/api/skill/<skill_name>` | 每个技能的元数据（工具列表、环境变量） |
| GET | `/api/scheduler/detect` | `local` / `slurm` / `apptainer` 自动检测 |
| GET | `/api/slurm/partitions` | SLURM 分区列表 |
| GET | `/api/container/info` | 容器运行时探测 |
| GET | `/api/container/images` | 已缓存的 SIF / OCI 镜像 |
| POST | `/api/container/pull` | 拉取 / 构建 `ARI_CONTAINER_IMAGE` 引用的镜像 |

### 检查点浏览

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/checkpoints` | 列出所有检查点搜索基路径下的检查点，按新到旧（`mtime` 降序） |
| GET | `/api/checkpoint/<id>/summary` | 运行摘要（目标、节点数、状态、最优指标） |
| GET | `/api/checkpoint/<id>/kca` | 对检查点已提交的 admission 文档做只读的 Knowledge / Provider / Assurance 分域投影（`schema_version: "ari.viz-kca/v1"`；没有 `run_admission.json` 的运行返回 `present: false`；无法读取的输入不会导致失败，而是出现在 `degraded_reasons` 中） |
| GET | `/api/checkpoint/<id>/memory` | Letta 记忆内容 |
| GET | `/api/checkpoint/<id>/memory_access` | 记忆写入/读取遥测数据 |
| GET | `/api/checkpoint/<id>/files` | 含大小 + 类型的文件列表 |
| GET | `/api/checkpoint/<id>/file?path=...` | 原始文件内容（文本或 base64） |
| GET | `/api/checkpoint/<id>/file/raw` | 同上，备用路由 |
| GET | `/api/checkpoint/<id>/filetree` | 层级树形视图 |
| GET | `/api/checkpoint/<id>/filecontent` | 多文件批量读取 |
| GET | `/api/active-checkpoint` | 当前选中的检查点 |
| POST | `/api/switch-checkpoint` | 切换当前检查点 |
| POST | `/api/delete-checkpoint` | 删除检查点（同时删除对应的 Letta 智能体）—— 需要挑战（MN-6） |
| POST | `/api/checkpoint/file/save` | 原地编辑检查点中的文件 |
| POST | `/api/checkpoint/file/delete` | 从检查点删除文件 |
| POST | `/api/checkpoint/compile` | 对论文草稿运行 `pdflatex` |

### 运行生命周期

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/launch` | 启动新的 BFTS 运行（以编程方式调用 `ari run`）—— 未变更；规范路径是 `POST /api/v1/runs` |
| POST | `/api/run-stage` | 运行单个流水线阶段 |
| POST | `/api/stop` | 停止当前运行 —— 需要挑战（MN-6） |

### 子实验 + 谱系

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/sub-experiments` | 所有子实验记录 |
| GET | `/api/sub-experiments/<run_id>` | 单个子实验详情 |
| POST | `/api/sub-experiments/launch` | 从父检查点继承启动子运行 |
| GET | `/api/lineage-decisions/<run_id>` | 停滞规则生成的决策（v0.7.0） |

#### 子实验列表与启动守卫

`GET /api/sub-experiments` **以磁盘为准**：每次调用都会重新扫描编排器的子实验
检查点根目录（`api_orchestrator._logs_root()`，可用 `ARI_ORCHESTRATOR_LOGS`
覆盖）下一层的 `<checkpoint>/meta.json`，
并用扫描结果*替换*服务器的内存记录集合 —— 因此被删除的检查点会从列表中消失，
而不会作为过期缓存条目残留
（`ari-core/tests/test_orchestrator.py::test_gui_list_sub_experiments_prunes_deleted`）。
每条记录是该检查点的 `meta.json` 加上附加的 `checkpoint_dir`，按
`(created_at, run_id)` 倒序（最新在前）排列。`GET /api/sub-experiments/<run_id>`
先读磁盘，读不到再回退到内存缓存；未知 id 返回 HTTP `200` 的
`{"error": "..."}`，而不是 `404`。

`POST /api/sub-experiments/launch` 在两种谱系情形下拒绝启动子运行。两者都以
HTTP `200` 返回 `{"ok": false, "error": ...}` —— legacy 分发器只有在处理器设置了
`_status` 时才覆盖状态码，而这两个守卫都不设置。

| 条件 | 原因 | 响应中一并回显 |
|---|---|---|
| `recursion_depth >= max_recursion_depth` | 为递归自启动设定上限；`max_recursion_depth` 默认为 `3`（`api_orchestrator.DEFAULT_MAX_RECURSION_DEPTH`），可按请求覆盖 | `recursion_depth`、`max_recursion_depth`、`parent_run_id` |
| 父检查点的 `meta.json` 带有 `parent_terminated` | 上游的 lineage decision 已经终结了该谱系 —— 当选定动作为 `terminate` 时由 `ari-core/ari/cli/lineage.py` 写入该标记；没有这道闸门，过期的后台调用方会在谱系被宣告耗尽之后继续派生子运行 | `parent_run_id`、`parent_terminated_rationale`（截断到 300 字符） |

深度检查先执行，因此同时超出深度*并且*父谱系已终结的请求会被报告为深度拒绝。
terminate 检查刻意是尽力而为的：`parent_run_id` 无法解析，或父 `meta.json`
缺失、不可读时，启动会继续进行，而不会因读取错误而失败关闭。

`inherit_idea_index` 还有自己的拒绝条件（缺少 `parent_run_id`、父运行无法解析、
父 `idea.json` 缺失或格式错误、索引非整数或越界）。它只读取父运行的 `idea.json`
目录 —— 从不读取父运行的 `plan.md` —— 因此继承而来的子运行仍可转向。

### 记忆后端

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/memory/health` | Letta 健康探测 |
| GET | `/api/memory/detect` | 运行中的 Letta 部署路径清单 |
| POST | `/api/memory/start-local` | 启动本地 Letta 服务器 |
| POST | `/api/memory/stop-local` | 停止本地 Letta 服务器 |
| POST | `/api/memory/restart` | 重启本地 Letta 服务器 |

### 设置 + workflow

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/settings` | 读取 settings.json |
| POST | `/api/settings` | 写入 settings.json |
| GET | `/api/profiles` | 已保存的配置文件列表 |
| GET | `/api/env-keys` | ARI 已知的环境变量键名（值已脱敏 —— MN-2） |
| POST | `/api/env-keys` | 将环境变量键/值对持久化到 `.env`（名称允许列表 —— MN-2） |
| GET | `/api/workflow` | 当前 workflow.yaml（+ `revision` —— MN-3） |
| GET | `/api/workflow/default` | 捆绑的默认值 |
| GET | `/api/workflow/flow` | Workflow 可视化为 DAG 节点 / 边 |
| POST | `/api/workflow` | 保存 workflow.yaml（可选 `base_revision` —— MN-1/MN-3） |
| POST | `/api/workflow/flow` | 保存 DAG 视图（可选 `base_revision` —— MN-1/MN-3） |
| POST | `/api/workflow/skills` | 切换启用的技能（可选 `base_revision` —— MN-1/MN-3） |
| POST | `/api/workflow/disabled-tools` | 每技能工具白名单 / 黑名单（可选 `base_revision` —— MN-1/MN-3） |

这四个写入端点都只编辑**活动检查点**的 `{ckpt}/workflow.yaml`；捆绑的
`config/workflow.yaml` 永远不会被 GUI 写入（MN-1）。当检查点尚无副本时，
`/api/workflow/flow`、`/api/workflow/skills` 与 `/api/workflow/disabled-tools`
会先把捆绑文件复制进检查点（`ari-core/ari/viz/api_workflow.py` 中的
`_checkpoint_workflow_path`）。`POST /api/workflow` 不使用该辅助函数：它用调用方
从 `GET /api/workflow` 回传的 `path` 作为首次写入的种子；若该字段缺失或不可读，
它写出的检查点副本将只包含 `pipeline`。

**workflow 写入会保留什么。** 每次写入都会载入其种子来源的整个 YAML 映射，只修改
其中一节，再以 `sort_keys=False` 重新序列化整个映射。因此 GUI 未建模的顶层键会在一次编辑
往返后保持其值与原有键序不变 —— 包括捆绑的 `config/workflow.yaml` 中未类型化的
`extra="allow"` 小节（`memory:`、`lineage_decision:`、`claim_gate_policy:`、
`container:`）；`ari-core/ari/config/field_registry.py` 将它们前置声明为目前尚无
带类型 pydantic 叶子的块。只有
`POST /api/workflow/flow` 还会在*阶段*粒度上合并：`_merge_stages` 仅覆盖 DAG
编辑器携带的十个字段（`stage`、`skill`、`tool`、`description`、`depends_on`、
`enabled`、`phase`、`loop_back_to`、`pre_tool`、`post_tool`），每个阶段的其余部分
—— `inputs`、`outputs`、`skip_if_exists`、`react:` 块 —— 仍取自磁盘；提交的 flow
中缺失的阶段会被丢弃，新增的阶段则原样追加。`POST /api/workflow` 会用提交的内容
整体替换 `pipeline` 列表，因此调用方未发送的按阶段字段**不会**被合并回来。

**workflow 写入不会保留什么：注释与排版。** 文件是从已解析的映射重新输出的，
因此注释、空行分组、引号与流式风格（`[a, b]`、`{a: 1}`）会在第一次 GUI 保存时
被规范化掉，标量会以其规范形式重写（`yes` → `true`、`"x"` → `x`），YAML 锚点会
以生成的名称（`&id001`）重新输出。捆绑的 `config/workflow.yaml` 因为无人写入，
其注释得以保留。

**workflow 写入不会检查什么。** 越过写入守卫（MN-1）与可选的修订守卫（MN-3）之后，
这四个写入几乎什么都不检查。`POST /api/workflow` 只要求请求体里有非空的
`pipeline`；`POST /api/workflow/flow` 只要求非空的 `flow`；`POST /api/workflow/skills`
只要求至少一个条目同时带 `name` 与 `phase`；`POST /api/workflow/disabled-tools`
只要求 `disabled_tools` 是一个列表。写入前没有任何代码去看阶段图。

**已知缺口 —— workflow 编辑器没有校验层。** GUI 刷新计划为 workflow 保存指定了
五项检查：未知的 `phase`、`depends_on` 成环、`depends_on` 指向不存在的阶段、被
`enabled: false` 关掉的必需上游，以及引用了无法解析的配置键的阶段。**这五项一项
都没有实现** —— 在连线的两侧都是已知缺口。`ari-core/ari/viz/api_workflow.py` 与
`ari-core/ari/viz/api_settings.py` 里都没有校验器，而编辑器的保存状态标记
（`ari-core/ari/viz/frontend/src/components/Workflow/WorkflowPage.tsx`）只有
`idle`、`dirty`、`saving`、`saved` 和 `conflict` —— 根本没有可供渲染的 `invalid`
状态。在 POST 之前，有三个后果值得知道：

- **代码不认识的 `phase` 会悄悄变成 post-BFTS 阶段。** `workflow_yaml_to_flow` 与
  `flow_to_workflow_yaml` 按与字符串 `"bfts"` 的精确相等来划分阶段；其他任何取值
  —— 包括拼写错误、大小写不同以及空字符串 —— 都会进入 `pipeline:` 列表。因此把一个
  `phase` 拼错的阶段从 DAG 视图保存下去，会把它从 `bfts_pipeline:` 挪进
  `pipeline:`，而写入照样报告成功。这两个列表由运行时的不同部分读取 —— 见配置参考的
  「workflow.yaml（权威开发者配置）」一节（[configuration.md](configuration.md)）。
- **`depends_on` 成环在写入时会被接受，并可能弄坏下一次读取。**
  `flow_to_workflow_yaml` 直接从提交的边构建 `depends_on` —— 只有 `data.condition`
  为 `loop` 的边会被分流到 `loop_back_to` —— 所以环会被原样持久化。下一次
  `GET /api/workflow/flow` 用 `_compute_levels` 重新推导泳道布局，而它是一个不保存
  已访问集合的递归深度遍历；当环的两端位于同一条泳道时，产生的 `RecursionError`
  会被处理函数那个笼统的 `except Exception` 捕获，并作为
  `{"ok": false, "error": …}` 返回。于是编辑器打不开自己刚写下的文件，而错误文本
  说的是递归上限而不是环。两端分属不同泳道的环则能挺过这次读取，因为
  `_compute_levels` 会丢弃指向所遍历列表之外阶段的依赖。
- **指向不存在阶段的 `depends_on` 同样不会被拒绝。** 此时
  `GET /api/workflow/flow` 会返回一条边，其 `source` 是同一响应中没有任何节点携带的
  节点 ID。

至于*运行时*拿到一个无法满足的图会做什么 —— 阶段不做拓扑排序、按文件顺序执行，
依赖被跳过的阶段也会被跳过，而被显式设为 `enabled: false` 的依赖反而算作已解决
—— 见[扩展指南](../guides/extension_guide.md)的「3. 添加 Post-BFTS 流水线阶段」。

**没有活动检查点时的 `POST /api/settings`（冻结的 legacy 行为）。** 设置是按项目
作用域的。当 `_st._settings_path` 为 `None` 时无处可持久化，于是
`_api_save_settings`（`ari-core/ari/viz/api_settings.py`）用恰好这个 dict 拒绝：

```json
{ "ok": false,
  "error": "No active project. Create or select a checkpoint before saving settings.",
  "_status": 400 }
```

`ari-core/tests/test_gui_baseline_settings_contract.py` 连同消息字符串逐字符断言了
它，因此这是冻结的契约，不是可以改写的措辞。在真实 HTTP 上，这个 `_status` 到不了
状态行 —— 本页「约定（legacy）」一节点名的正是这条路由，拒绝会以携带上述 dict 的
`200` 送达。**读取不会被拒绝：** 当没有活动检查点（以及已保存文件无法解析）时，
`_api_get_settings` 返回内置默认值，因此 `GET /api/settings` 总会作答。读取回退，
只有写入拒绝 —— 这是 MN-1 在设置侧的对应物，MN-1 覆盖的是四个 workflow 写入。

**怪癖 —— 被拒绝的保存其实已经把 API key 写掉了。** 在 `_api_save_settings` 中，
`.env` 的 upsert 跑在检查点判定*之前*。`api_key` / `llm_api_key` 字段会从请求体中
被 pop 出来（因此绝不会写进 `settings.json`），并且只有通过三道 legacy 过滤器时
才会转交给 `_upsert_env_key`；这三道过滤器**都会静默丢弃 key，不报任何错**：值必须
至少 20 个字符，不得包含子串 `test`，且请求的 `llm_provider`（为空时取
`llm_backend`）必须能映射到已知的环境变量名（`openai` → `OPENAI_API_KEY`，
`anthropic` / `claude_code` / `claude-code` → `ANTHROPIC_API_KEY`，`gemini` →
`GOOGLE_API_KEY`）。一个确实通过了这三道过滤器、且没有活动检查点的请求，会收到上面
那个拒绝（响应体内的 `_status: 400`），**同时**它早已把 `NAME=value` 写入了
ARI 根目录的 `.env`
（`_st._env_write_path`，不加引号的形式，原子替换，权限 `0o600`），并在运行中的服务器
进程里设置了 `os.environ[NAME]`。调用方被告知什么都没保存，而机密已经落盘并被注入
到活动进程中。这个顺序由同一个契约测试钉住，因此它是被冻结的行为而非有意的设计：
应把该端点的拒绝理解为「`settings.json` 没有被写入」，绝不能理解为「什么都没发生」。
同一对端点的键集合与「死键」怪癖记录在配置参考的「legacy Settings 键：实际接线情况」
一节（[configuration.md](configuration.md)）。

### 向导 / 配置生成

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/experiment-detail` | 向导解析的 experiment.md |
| POST | `/api/config/generate` | 根据向导回答生成 `ari.yaml` |
| POST | `/api/chat-goal` | LLM 辅助的目标叙述精炼 |
| POST | `/api/ssh/test` | 探测 SSH 集群登录 |

### 上传 + few-shot 语料库

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/upload` | 多部分上传到当前检查点 |
| POST | `/api/upload/delete` | 删除已上传的文件 |
| GET | `/api/fewshot/<rubric_id>` | 某规范的 few-shot 示例 |
| POST | `/api/fewshot/<rubric_id>/sync` | 拉取已发布的语料库 |
| POST | `/api/fewshot/<rubric_id>/upload` | 添加示例 |
| POST | `/api/fewshot/<rubric_id>/delete` | 删除示例 |
| GET | `/api/rubrics` | 可用的评审规范（由 `ARI_RUBRIC` 驱动） |

### 节点报告

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/nodes/<...>/report` | 每节点的 `node_report.json` |

### PaperBench（v0.7.2）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/paperbench/papers` | 已登记的论文（来自注册表清单的 `{"papers": [...]}`） |
| GET | `/api/paperbench/arxiv/<arxiv_id>` | 向公开 arXiv Atom API 探测元数据 |
| GET | `/api/paperbench/papers/<paper_id>/license` | 单篇论文已记录的许可 / 再分发策略 |
| POST | `/api/paperbench/papers/import` | 将一篇新论文登记进注册表 |
| POST | `/api/paperbench/papers/<paper_id>/metadata` | 将字段合并进已有清单条目 |
| POST | `/api/paperbench/papers/<paper_id>/delete` | 删除清单条目与论文目录（幂等） |
| POST | `/api/paperbench/cost-estimate` | 对拟议运行做 dry-run 成本估算 |
| POST | `/api/paperbench/run` | 为给定的 `paper_ids` 排入 PaperBench 作业 |
| GET | `/api/paperbench/run/<job_id>` | 作业状态快照 |
| GET | `/api/paperbench/run/<job_id>/logs` | 单个作业的 SSE 日志流（`since=`、`Last-Event-ID`；300 秒窗口、`: heartbeat`、终止帧 `event: done`） |
| GET | `/api/paperbench/run/<job_id>/results` | 单个作业的结果载荷 |
| GET, POST | `/api/paperbench/run/<job_id>/report` | 触发 / 获取审计报告（`languages`、`formats` —— URL 查询或 POST 请求体） |

作业状态保存在内存表中，同时原子镜像到 `{registry_root}/jobs/{job_id}.json`
（临时文件 + `os.replace`，权限 `0o600`），因此 viz 服务器重启后不再遗忘历史作业。
重启后 GET 读取方会以只读方式回落到该记录；以活动状态（`queued` / `running`）
持久化的作业会以追加状态 `interrupted` 报告 —— 工作线程绝不会被重新拉起。

### EAR + 发布（v0.7.0）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/ear/<run_id>` | 某次运行的 EAR bundle 元数据 |
| GET | `/api/ear/<run_id>/publish-yaml` | 生成的 publish.yaml 预览 |
| POST | `/api/ear/<run_id>/curate` | 运行策展步骤 |
| POST | `/api/ear/<run_id>/publish-yaml` | 保存 publish.yaml |
| POST | `/api/ear/clone-verify` | 按哈希校验远程 bundle |
| GET | `/api/publish/settings` | 后端配置 |
| POST | `/api/publish/settings` | 更新后端配置 |
| GET | `/api/publish/<run_id>/preview` | 发布前有效载荷预览 |
| GET | `/api/publish/<run_id>/record` | 读取 `publish_record.json` |
| POST | `/api/publish/<run_id>/promote` | 将 `staged` 提升为 `unlisted` / `public` |
| POST | `/api/publish/<run_id>` | 推送到已配置的后端 |

### 静态文件 + 前端

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/static/<path>` | 捆绑的 UI 资源（安全响应头 —— MN-7） |
| GET | `/memory/<path>` | 记忆检查器静态页面 |
| GET | `/codefile?path=...` | 源文件查看器（规范路径边界 —— MN-5） |

### 更新本参考文档

对于 `/api/v1`：将路由添加到 `ari/viz/v1/router.py`，重新生成
`openapi.json`（`python -m ari.viz.v1.openapi --update`），然后把一行用途
说明镜像到上面的端点表中。

对于 legacy 接口面：路由表就是 `ari-core/ari/viz/routes.py` 中的分发链。
新路由属于 `/api/v1`，不属于这里。

### 另请参阅

- `docs/reference/rqgm_gui_read_models.md` —— RQGM 读模型的语义。
- `docs/reference/configuration.md` —— `/api/v1/config/*` 背后的配置控制平面。
- `docs/reference/environment_variables.md` —— `ARI_GUI_*` 开关。
- `docs/concepts/architecture.md` —— viz 包概览。
- `ari-core/ari/viz/__init__.py` —— 包含当前子模块映射的模块级文档字符串。
