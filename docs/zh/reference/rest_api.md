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
  - path: ari-core/tests/test_gui_state_facade_freeze.py
    role: test
last_verified: 2026-07-27
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
[环境变量 → GUI 服务器](environment_variables.md#gui-服务器ari_gui_)。

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
| GET | `/api/v1/projects/{project_id}/runs` | 某个 project 中的 run（检查点），以摘要卡片形式返回。 |
| GET | `/api/v1/runs/{run_id}` | Run 详情：摘要加上由工件推导出的详情字段与一份能力映射。 |
| GET | `/api/v1/runs/{run_id}/summary` | 单个 run 的摘要卡片标量（状态、节点数、评审分数、最优指标）。 |
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
| GET | `/api/v1/events/stream` | SSE 失效流（见[实时](#实时get-apiv1eventsstreamsse)）。 |
| GET | `/health/live` | 无依赖的存活常量 `{"status": "ok"}`。免认证。 |
| GET | `/health/ready` | 就绪状态：`status` 为 `ok` 或 `degraded`，加上一个 `checks` 对象（`http`、`websocket`、`watcher`、`event_bus`、`active_checkpoint`）。每项检查独立求值，崩溃的检查读作 `false`；降级的就绪状态是一个诚实的 `200` —— 该探针永不返回 500。免认证。 |

`ARI_GUI_HEALTH=0` 会移除全部三个健康/诊断接口面（`/health/*` 回落到 SPA
响应，`/api/v1/diagnostics` 返回类型化的 404）。

---

## 无版本的 legacy API（legacy 外观 —— 已冻结，见 MN 注记）

> **已冻结。** 下面的无版本接口面是为 legacy 仪表盘页面与既有集成保留的。
> 它**不会**被扩展：新数据必须由一个 run 显式的 `/api/v1` 端点提供。特别是
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

- 错误以 `{"error": "<message>"}` 格式返回，附带非 2xx HTTP 状态码（部分
  处理器使用 `{"ok": false, "error": ...}`）。
- CORS 预检（`OPTIONS`）在 `/api/*` 上只对同源请求作答（MN-4）。

### 类型化契约（稳定端点）

流量最高的几个 GET 端点，其响应形状在
`ari-core/ari/viz/frontend/src/types/index.ts` 中有对应的前端 TypeScript
类型镜像，并由 `ari-core/tests/test_api_schema_contract.py` 守护（以**子集**
方式断言必然存在的键 —— 允许额外/可选字段，因此契约是增量式的）。

| 端点 | 生产者 | 前端类型 | 必然存在的键 |
|---|---|---|---|
| `GET /state` | `services/state_service.build_app_state` | `AppState` | `running_pid`、`is_running`、`exit_code`、`running`、`pid`、`status_label`（其余受检查点门控 → 在类型中为可选）。`cost` 是解析后的 `cost_summary.json` **对象**（`CostSummary`），不是数字。 |
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
  "phase": "bfts",
  "nodes": { "total": 7, "completed": 5, "running": 2, "failed": 0 },
  "model": { "provider": "ollama", "model": "qwen3:8b" },
  "cost": { "usd": 0.0, "tokens": 0 }
}
```

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
  { "id": "20260526T101500_matmul", "status": "running", "nodes": 7, "review_score": null },
  { "id": "20260520T090000_sort",   "status": "done",    "nodes": 12, "review_score": 0.71 }
]
```

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

### 模型 + 技能

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/models` | 发现通过 LiteLLM + Ollama 可用的 LLM |
| GET | `/api/ollama-resources` | 模型所需的内存 / 磁盘 |
| GET | `/api/ollama/<...>` | 代理到本地 Ollama 守护进程（仅允许列表内路径 —— MN-5） |
| GET | `/api/skills` | 枚举已注册的技能 + 其工具数量 |
| GET | `/api/skill/<skill_name>` | 每个技能的元数据（工具列表、环境变量） |
| GET | `/api/tools` | 跨所有技能的合并工具目录 |
| GET | `/api/scheduler/detect` | `local` / `slurm` / `apptainer` 自动检测 |
| GET | `/api/slurm/partitions` | SLURM 分区列表 |
| GET | `/api/container/info` | 容器运行时探测 |
| GET | `/api/container/images` | 已缓存的 SIF / OCI 镜像 |
| POST | `/api/container/pull` | 拉取 / 构建 `ARI_CONTAINER_IMAGE` 引用的镜像 |

### 检查点浏览

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/checkpoints` | 列出 `ARI_CHECKPOINT_DIR` 父目录下的所有检查点 |
| GET | `/api/checkpoint/<id>/summary` | 运行摘要（目标、节点数、状态、最优指标） |
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
