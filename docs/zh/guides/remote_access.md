---
sources:
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/websocket.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/v1/challenges.py
    role: implementation
  - path: ari-core/ari/viz/v1/queries.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/services/api/client.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/shared/realtime/eventStream.ts
    role: implementation
  - path: ari-core/tests/test_gui_remote_auth.py
    role: test
  - path: ari-core/tests/test_gui_bind_cors.py
    role: test
  - path: ari-core/tests/test_gui_csp_headers.py
    role: test
  - path: ari-core/tests/test_gui_health_diagnostics.py
    role: test
  - path: ari-core/tests/test_gui_confirmation_challenges.py
    role: test
  - path: scripts/setup/setup_env.sh
    role: config
last_verified: 2026-08-08
---

# 远程访问与运维指南

关于「把 ARI 仪表盘跑在它被显示的那台笔记本之外」的一切：默认的信任姿态、
如何有意识地把它开放出去，以及运维者需要的端点。

一句话版本：**仪表盘默认是一个单操作者本地工具，任何偏离这一点的步骤都是
显式选择加入。**

## 默认姿态：仅回环

在没有设置任何 GUI 环境变量时：

- HTTP 服务器同时绑定 `127.0.0.1` **与** `::1`（两个回环地址族，因此无论你的
  发行版把 `localhost` 解析为 IPv4 还是 IPv6 都能用）；
- 位于 **HTTP 端口 + 1** 的 WebSocket 服务器以同样方式绑定；
- **没有认证** —— 回环绑定加同源 CORS *就是*保护；
- 局域网上的另一台主机根本连不上。

这是有意的策略，而不是一个等着被放宽的默认值：早先的构建绑定所有接口、没有
认证，并且无条件返回 `Access-Control-Allow-Origin: *`，这把每一个端点 ——
包括删除、停止与 secret 写入 —— 都暴露给了整个集群网络。

如果你只是需要从另一台机器访问仪表盘，请优先使用 **SSH 隧道**（见下文）。
隧道保持回环姿态不变，也不需要 token。

### 这一姿态未覆盖的部分

从另一侧来说：回环默认值，以及下文描述的远程模式，都是**主机之间**的边界。
两者都不是权限系统，而它们止步于何处值得直说。

**两种模式都没有授权层。** 本地模式根本没有凭据 —— 回环绑定下 `resolve_token`
不返回任何东西，因此请求门放行一切。于是，本机上任何能向该端口打开套接字的进程
都握有整个 API：通过 `POST /api/env-keys` 写入 secret、覆写 checkpoint 内的文件、
重启 memory 后端，以及 —— 在给自己签发下文所述的授权之后 —— 删除 checkpoint 或
停止每一个实验进程。回环绑定隔开的是主机，而不是共用同一台主机的用户或作业。

远程模式加了一个凭据，然后就到此为止。bearer token 是单一的全能值：它不指名任何
人，无法按项目或按 run 限定范围，除了与它自身之外不与任何东西比对。目前也还没有
一个可以挂载权限检查的边界 —— `/api/v1` 面只暴露一个虚拟的 `default` 项目，对其他
任何项目 id 都返回 404 信封。会话、登出、按会话吊销都不存在；吊销访问权意味着修改
`ARI_GUI_TOKEN` 并重启服务器，而这会一次性吊销所有人的。这是决定而非疏漏：
[GUI-ADR-13](../../adr/gui/GUI-ADR-13-remote-bearer-token.md) 把会话、登出、吊销与
多用户永久推迟到未来的多租户记录，并在其 consequences 中写明：这个单一的全能 token
不应被就地扩展。

**确认挑战是防事故的控制，不是访问控制。** 能调用
`POST /api/delete-checkpoint` 的人同样能调用 `POST /api/v1/challenges` 并签发它所
要求的授权 —— 签发不需要请求已经携带之外的任何凭据。两步流程买到的是：由**服务器**
指名目标，而客户端必须把那个一次性授权原样回送。这正是能拦住过期标签页、被重放的
脚本，或指向错误路径的批量操作的东西。它不是第二因子。词汇表也是有意窄的 ——
`delete-checkpoint`、`stop-all`、`gpu-monitor-stop`，仅此而已。保存、删除或上传
checkpoint 内的文件（`POST /api/checkpoint/file/save`、
`POST /api/checkpoint/file/delete`、`POST /api/checkpoint/{id}/file/upload`）以及
重启 memory 后端（`POST /api/memory/restart`）都是一请求即执行。

**`viz_access.jsonl` 是请求日志，不是审计轨迹。** 它的字段就是下文*访问日志*
列出的六个，其中 `client` 是对端的网络地址 —— 因此没有任何一行指名某个人，而在
回环默认下每一行指向的都是同一个回环地址。对事后重建更麻烦的是：没有活动
checkpoint 时根本不写任何东西，而这一状态并不会阻止那些本该被记录的写入。
`POST /api/env-keys` 编辑的是项目的 `.env` 文件，完全不碰 checkpoint，因此在没有
选中 checkpoint 时写下的 secret 不会留下任何一行。没有行，并不能证明什么都没发生。

以上都不会让仪表盘对「它本来是什么」而言变得不安全：一个单操作者的研究工具，由
它所展示的那些 run 的主人来运行。但这确实意味着，「放到 token 后面再把 URL 分享
出去」不是一种受支持的多用户部署，并且每一个拥有访问权的人都握有全部操作者权限。

## GUI 环境变量

它们全部已在 `scripts/setup/setup_env.sh` 中预置（默认注释掉）。

| 变量 | 默认值 | 效果 |
|---|---|---|
| `ARI_GUI_V2` | 开启 | `0`/`false` 回退到 legacy 外壳 |
| `ARI_GUI_BIND` | 未设置 → 回环 | 选择加入某个绑定地址（见下文） |
| `ARI_GUI_TOKEN` | 未设置 | 远程模式所需的 bearer token |
| `ARI_GUI_AUTH` | 开启 | `0`/`false` 关闭远程 token 闸门 |
| `ARI_GUI_CORS_ANY` | 关闭 | `1` 恢复 legacy 的 `ACAO: *` 通配符 |
| `ARI_GUI_CSP` | 开启 | `0` 去掉 CSP + nosniff + Referrer-Policy |
| `ARI_GUI_CHALLENGES` | 开启 | `0` 关闭确认挑战 |
| `ARI_GUI_HEALTH` | 开启 | `0` 关闭健康/诊断接口面 |

除 `ARI_GUI_TOKEN` 之外，每一个都是有意设置的回滚手段，并作为 kill-switch
register 与其实现代码放在一起记录：六个安全开关记在 ADR-07 register 中，
`ARI_GUI_V2` 记在 gui_refresh 的 rollout-flag policy（owner / default /
rollback / removal gate）中。把其中任何一个关掉，都只是恢复某个曾经发布过的
行为，不会解锁任何新东西。`ARI_GUI_TOKEN` 不是开关，而是 token
本身的取值 —— 不设置它并不会恢复什么，而是让服务器自行生成一个（见下文）。

## 选择加入非回环绑定

```bash
export ARI_GUI_BIND=0.0.0.0     # IPv4 wildcard
# export ARI_GUI_BIND='::'      # all interfaces, dual stack (the pre-hardening bind)
# export ARI_GUI_BIND=10.0.0.7  # exactly one interface
python -m ari.viz.server --port 8765
```

解析规则：未设置或为空 → `["127.0.0.1", "::1"]`；**任何**显式取值 → 就绑定
那一个主机。WebSocket 服务器遵循同样的策略。

非回环取值会把服务器切换到**远程模式**，而远程模式是需要认证的。
`localhost`、`::1` 以及任何 `127.x.y.z` 都算回环；其余一切 —— 包括通配符
—— 都算远程。

## 远程模式下的 token 认证

在远程模式下，**除 `/health` 前缀外的每个 HTTP 请求**都必须出示 token，
WebSocket 握手同样如此。该闸门运行在 `do_GET` / `do_POST` / `do_PUT` /
`do_PATCH` / `do_DELETE` 的最顶端，早于任何分发或请求体读取。

### 获取 token

要么固定一个：

```bash
export ARI_GUI_TOKEN="$(python -c 'import secrets;print(secrets.token_hex(16))')"
```

……要么不带 token 启动，让服务器自己生成。这是**安全失败**的：远程绑定绝不会
以无认证状态启动。生成的 token 会向 stderr 打印**一次**，并且永不写入日志
文件：

```text
  ============================================================
  ARI GUI is bound to a non-loopback address and ARI_GUI_TOKEN
  is not set. A random access token was generated for this run
  (MN-8, ADR-13). It is printed here ONCE and never logged:

      ARI_GUI_TOKEN=<32 hex chars>

  Every request must send 'Authorization: Bearer <token>'
  (SSE/WebSocket: '?token=<token>'). Set ARI_GUI_TOKEN to pin
  a stable token across restarts.
  ============================================================
```

如果你希望 token 在重启后仍然有效，请显式设置 `ARI_GUI_TOKEN`（否则每次
重启都会铸造一个新的，每个浏览器都得重新写入）。

### 浏览器如何提供它

目前还没有登录页面。前端从 `localStorage` 的 `ari_gui_token` 键读取 token；
请在页面自身的 origin 下，通过浏览器控制台写入一次：

```js
localStorage.setItem('ari_gui_token', '<token>');  // then reload
```

此后客户端会给每次 `fetch` 附上 `Authorization: Bearer <token>`，并给两个
无法设置请求头的传输附上 `?token=<token>`。在回环默认配置下不会设置该键，
因此请求形状保持不变。

### 为什么 SSE 与 WebSocket 使用查询参数

浏览器的 `EventSource` 与 `WebSocket` API 无法设置请求头。因此二者也接受把
token 作为 **`token` 查询参数**：

```text
GET /api/v1/events/stream?run_id=…&topics=run,tree&token=<token>
ws://host:8766/?token=<token>
```

这是一个被接受并记录在案的权衡。缓解措施是：访问日志
（`{checkpoint}/viz_access.jsonl`）在写入前会把任何 `token=` 查询值改写为
`***`，因此 token 在两种形式下都不会进入日志文件。由 fetch 消费的 legacy
`/api/logs` 流使用请求头，因为它的消费者*可以*设置请求头。

### 失败行为

缺失或错误的 token 会得到 `401`，带类型化的 JSON 响应体与
`WWW-Authenticate: Bearer`；比较是常量时间的（`hmac.compare_digest`）；
连接会被关闭，以免未读取的响应体让 keep-alive 失去同步。WebSocket 握手在
升级之前就会以同样的 401 形状被拒绝。

### 供脚本与 curl 使用

```bash
curl -H "Authorization: Bearer $ARI_GUI_TOKEN" http://host:8765/api/v1/projects
curl -N "http://host:8765/api/v1/events/stream?token=$ARI_GUI_TOKEN"
```

### 没有 cookie，因此没有 CSRF

认证只使用 bearer token。没有任何东西依赖 cookie，因此不存在跨站请求伪造面，
也没有 CSRF token 需要管理。会话、登出与多用户访问被有意推迟 —— 今天它是一个
单操作者研究工具，而整个矩阵（本地 / 远程 / token / 紧急开关）在
`ari-core/tests/test_gui_remote_auth.py` 中有单元测试覆盖。

### `ARI_GUI_AUTH` 逃生舱

`ARI_GUI_AUTH=0` 关闭远程闸门，恢复较旧的无认证远程绑定。仅当 GUI 前面已有
东西负责认证时才使用它 —— 例如一个负责认证的反向代理。回环绑定无论如何都是
无认证的；该开关在那里没有效果。

## CORS

响应**仅限同源**。只有当请求的 `Origin` 指向本服务器时 —— 与请求的 `Host`
头一致，或者是服务器端口上的回环形式 `localhost` / `127.0.0.1` / `[::1]`
之一 —— 它才会被回显到 `Access-Control-Allow-Origin`（并附 `Vary: Origin`）。
跨源请求**根本不会**得到 ACAO 头，因此浏览器拒绝把响应交给页面。

预检（`OPTIONS`）对不被允许的 origin 仍然返回 `204`，只是不带任何
`Access-Control-*` 头。被允许的 origin 还会额外收到
`Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS`、
`Access-Control-Allow-Headers: Content-Type, X-Filename, If-Match,
Last-Event-ID`，以及 24 小时的 `Access-Control-Max-Age`。

这在实践中意味着：

- **隧道与保留 Host 的代理没问题** —— 页面 origin 等于服务器看到的 `Host`。
- **`:5173` 上的 Vite 开发服务器没问题** —— 它的代理以同源方式转发 `/api`、
  `/state` 与 `/ws`。
- **把页面与 API 从不同 origin 提供的门户就不行**，除非设置
  `ARI_GUI_CORS_ANY=1` 恢复 legacy 通配符。请优先修正拓扑；通配符是最后
  手段。

有两个端点 —— `GET /state` 与 `GET /api/gpu-monitor` —— 历史上就不带 ACAO，
现在仍然如此。

## 浏览器安全响应头（CSP）

SPA 首页与每个 `/static/` 响应都带上：

```text
Content-Security-Policy: default-src 'self'; script-src 'self';
  style-src 'self' 'unsafe-inline'; img-src 'self' data:;
  connect-src 'self' ws://<host>:<port+1> wss://<host>:<port+1>;
  frame-src 'self'; frame-ancestors 'none'
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
```

在把它部署到代理之后前，有几点值得知道：

- 打包产物是完全自包含的 —— 不存在需要放行的 CDN `<script>`。离线主机直接
  受益。
- `connect-src` **显式**指明了树的 WebSocket，其取值由请求的 `Host` 头推导，
  因为该实时流监听 HTTP 端口 + 1，而 `'self'` 只覆盖页面自身的端口。
  **如果你的代理重映射了 WebSocket 端口，浏览器会拦截它**，仪表盘随之降级为
  轮询。这正是 `ARI_GUI_CSP=0` 存在的那一种拓扑。
- `frame-ancestors 'none'` 意味着仪表盘无法被嵌入到别的站点的 iframe 中。
  `frame-src 'self'` 保证同源 PDF iframe 继续工作。
- `style-src 'unsafe-inline'` 是一处被接受的残留（React 的内联 `style={}`
  属性无处不在）；收紧它是被跟踪中的工作。
- API/JSON 响应有意不带 CSP。

## 破坏性操作的确认挑战

有三个操作拒绝仅凭客户端确认就执行：删除检查点、停止全部进程，以及停止 GPU
监控。服务器签发一个短时有效、**绑定到一个动作与一个目标**的授权，而破坏性
端点要求把它回传。

```bash
# 1. ask for a challenge
curl -X POST http://localhost:8765/api/v1/challenges \
     -H 'Content-Type: application/json' \
     -d '{"action":"delete-checkpoint","target":"/path/to/checkpoints/2026…"}'
# -> {"challenge_id":"chg-0a1b2c3d4e5f","action":…,"target":…,
#     "expires_at":"…Z","ttl_seconds":60}

# 2. echo it back with the destructive call
curl -X POST http://localhost:8765/api/delete-checkpoint \
     -H 'Content-Type: application/json' \
     -d '{"path":"/path/to/checkpoints/2026…","challenge_id":"chg-0a1b2c3d4e5f"}'
```

| 动作 | 目标 | 在哪里被强制 |
|---|---|---|
| `delete-checkpoint` | 检查点路径 | `POST /api/delete-checkpoint` |
| `stop-all` | `"*"` | `POST /api/stop` |
| `gpu-monitor-stop` | `"*"` | 带 `action=stop` 的 `POST /api/gpu-monitor` |

特性：

- **一次性使用**，60 秒 TTL 且基于单调时钟计量（挂钟跳变无法延长授权），
  存储是有界的内存结构（上限 100，最旧的被挤出；重启会清空全部 —— 客户端
  再要一个即可）；
- 缺失、未知、已过期、已使用或绑定错误的挑战都会得到 HTTP **428**，带冻结
  响应体 `{"ok": false, "error": "confirmation challenge required or
  invalid"}`，并且**不执行任何破坏性工作**。所有失败情形的消息完全相同，
  因此它无法被当作探测预言机使用；
- 签发、消费与拒绝都会作为 `challenge_*` 事件记入当前检查点的
  `viz_access.jsonl`，与它们所授权的请求行交错排列；
- 在 GUI 中这一切是不可见的：你看到的仍是一个确认对话框，但它现在展示的是
  **服务器**回显的确切目标 —— 一份你可以在同意之前核对的影响预览。

那些为旧的一步式端点写好脚本的自动化，要么改用两步流程，要么设置
`ARI_GUI_CHALLENGES=0`。在该紧急开关下签发端点仍然可用，因此两步式客户端在
两种情况下都能工作。

## SSH 隧道（推荐，也是经过验证的路径）

让服务器留在回环上，转发端口即可。服务器的姿态没有任何变化，因此不涉及
token。

```bash
# on the workstation
ssh -N -L 8765:localhost:8765 -L 8766:localhost:8766 user@remote-host
# then open http://localhost:8765/
```

请转发**两个**端口：`8765` 用于 HTTP，`8766`（HTTP + 1）用于树的 WebSocket。
如果你只转发 HTTP 端口，一切照常工作 —— 只是 WebSocket 连不上，仪表盘
回落到轮询。

如果计算节点前面还有集群登录节点，请把跳板串起来：

```bash
ssh -N -J user@login.cluster -L 8765:localhost:8765 -L 8766:localhost:8766 user@compute-node
```

这正是回环默认值所围绕设计的拓扑，也是 CORS 策略被验证过的组合
（`ari-core/tests/test_gui_bind_cors.py` 覆盖了包含回环别名在内的同源矩阵）。

## HPC 反向代理（指引，**未**经端到端验证）

> 下面的配方是未经测试的指引。它是根据服务器有文档记录的响应头与绑定策略
> 写成的，而不是来自一次可用的集群部署。在依赖它之前，请先在你自己的环境中
> 验证。

如果集群门户必须通过反向代理提供仪表盘，以下是由已实现行为推导出的约束：

1. **保留 `Host` 头。** 同源 CORS 检查与 CSP 的 `connect-src` 都由它推导。
   改写 `Host` 的代理会让浏览器拦截页面自己的 API 调用。
2. **把仪表盘部署在 origin 根路径上。** hash 路由（`#/…`）在任何路径之后都
   没问题，但静态资源从 `/static/dist/` 提供，而 SPA 回退会应答未知路径 ——
   子路径挂载不是服务器会替你改写的东西。
3. **不要重映射 WebSocket 端口。** 浏览器把它推导为页面端口 + 1，而 CSP
   恰好只允许那个端口。如果你必须重映射，请预期 WebSocket 会被 CSP 拦截，
   然后要么接受轮询回退，要么为该部署设置 `ARI_GUI_CSP=0`。
4. **不要缓冲 SSE。** `GET /api/v1/events/stream` 是一条长连接流，带 15 秒
   心跳注释与有界的 300 秒窗口；一个会缓冲的代理会把实时更新变成什么都没有。
   请关闭响应缓冲，并把读超时设得高于心跳间隔。
5. **决定认证放在哪里。** 要么在代理处终结认证，并在只有代理才能到达的绑定
   上设置 `ARI_GUI_AUTH=0`；要么保留 token 闸门，让代理原样透传
   `Authorization`。不要两者都不做。
6. **绑定得尽可能窄** —— `ARI_GUI_BIND=127.0.0.1` 配合同主机上的代理，严格
   优于通配符绑定。
7. **`frame-ancestors 'none'`** 意味着门户无法用 iframe 嵌入仪表盘；请改为
   链接过去。

## 面向运维者的健康与诊断

三个只读接口面。`/health` 前缀**免除** token 闸门（存活探针必须在没有凭据
的情况下工作）；`/api/v1/diagnostics` 则不免除 —— 在远程模式下它和其他一切
一样需要 bearer token。

### `GET /health/live`

一个无依赖的常量。只要 HTTP 处理器还能作答，进程就是存活的。

```json
{"status": "ok"}
```

### `GET /health/ready`

```json
{"status": "degraded",
 "checks": {"http": true, "websocket": true, "watcher": false,
            "event_bus": true, "active_checkpoint": true}}
```

每项检查独立求值，崩溃的检查读作 `false`。**就绪探针永不返回 500** ——
`degraded` 是一个诚实的 200，因此一个坏掉的子系统是可观察的，而不是一个
异常。这些检查是：`http`（在已分发的请求内部恒为真）、`websocket`（WS
服务器已启动）、`watcher`（检查点轮询线程存活）、`event_bus`（SSE 总线可
导入且可发布）、`active_checkpoint`（已选中一个且它在磁盘上仍然存在）。

### `GET /api/v1/diagnostics`

只有有界的标量 —— 计数、时长与版本：

```json
{"schema_version": 1,
 "sse": {"subscribers": 2, "buffer_len": 137, "last_event_id": 4021},
 "watcher": {"alive": true, "last_scan_age_s": 0.9},
 "process": {"tracked_runs": 1},
 "cache": false,
 "openapi_version": "…"}
```

无 secret，无文件系统路径 —— `tracked_runs` 是一个**计数**，绝不是它背后的
检查点路径键。`cache: false` 明确声明不存在缓存子系统，而不是省略该字段。
每个子采集器在失败时都降级为它的零值形状，因为诊断必须恰恰在出问题的时候
仍然可读。

典型的运维循环：

```bash
curl -s localhost:8765/health/live
curl -s localhost:8765/health/ready | python -m json.tool
curl -s -H "Authorization: Bearer $ARI_GUI_TOKEN" \
     http://host:8765/api/v1/diagnostics | python -m json.tool
```

解读提示：`watcher.alive=false`，或 `last_scan_age_s` 无上限地增长，意味着
检查点监视器卡住了 —— 即使运行仍在继续，树也不再更新。在没有打开任何浏览器
标签页的情况下 `sse.subscribers` 很高，提示某个会缓冲的代理泄漏了流。

`ARI_GUI_HEALTH=0` 恢复原有的线上行为：`/health/*` 穿透到 SPA 响应，
`/api/v1/diagnostics` 返回类型化的 404 信封。

## 访问日志

在某个检查点处于活动状态期间，请求会以 JSON 行追加到
`{checkpoint}/viz_access.jsonl` —— `ts`、`method`、`path`、`status`、
`duration_ms`、`client` —— 其中任何 `token=` 查询值都会被脱敏为 `***`。
没有活动检查点时不写入任何内容。确认挑战事件（`challenge_issued`、
`challenge_consumed`、`challenge_refused`）落在同一个文件里，因此一个破坏性
请求与授权它的那份授权会紧挨在一起。

## 速查：挑一种姿态

| 你想要 | 这样做 | 认证 |
|---|---|---|
| 本地使用 | 什么都不做 | 无 |
| 从你的笔记本查看 | `ssh -L 8765:localhost:8765 -L 8766:localhost:8766 …` | 无 |
| 直接局域网访问 | `ARI_GUI_BIND=0.0.0.0`（+ `ARI_GUI_TOKEN`） | bearer token，必需 |
| 位于负责认证的代理之后 | 收窄的 `ARI_GUI_BIND` + `ARI_GUI_AUTH=0` | 由代理负责 |
| 跨源门户 | 同上 + `ARI_GUI_CORS_ANY=1` | 由代理负责 |

## 另请参阅

- [仪表盘指南](dashboard.md) —— 启动服务器、端口、工作区地图。
- [配置工作室](configuration_studio.md) —— secret 如何被写入（且绝不回读）。
- [HPC 设置](hpc_setup.md) —— 在 SLURM 集群上运行 ARI 本身。
- [故障排查](troubleshooting.md) —— 常见运行时故障。
- [环境变量](../reference/environment_variables.md)。
- [REST API 参考](../reference/rest_api.md)。
