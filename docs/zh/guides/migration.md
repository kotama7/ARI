---
sources:
  - path: ari-core/ari/migrations/v05_to_v07
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-core/ari/viz/api_workflow.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/ari/viz/v1/secrets.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_ollama.py
    role: implementation
  - path: ari-core/ari/viz/v1/challenges.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/LaunchPanel.tsx
    role: implementation
  - path: scripts/setup/setup_env.sh
    role: config
last_verified: 2026-08-16
---

# 迁移指南

ARI 的检查点格式经历了三个版本的演进。本指南介绍各升级路径。

| 源版本 | 目标版本 | 核心变更 |
|---|---|---|
| v0.5 | v0.6 | Letta 内存后端取代 JSONL |
| v0.6 | v0.7 | ORS / EAR registry / lineage decisions |
| v0.7 | v0.8（未来）| 重构后的检查点格式（`ari.public/` 边界）|
| v0.8 | v1.0（未来）| 移除旧版兼容层 |

启用可选的 `ari_rqgm` 执行模式**不是**一次检查点格式迁移：
`simple_bfts` 仍是默认模式，现有检查点原样继续工作，切换仅通过
配置完成（`ari.mode` + `rqgm.enabled`）。参见
[RQGM 迁移指南](rqgm_migration.md)与[执行模式](execution_modes.md)。

**GUI 刷新**同样不是一次检查点格式迁移 —— 没有任何检查点被改写，也不需要
降级迁移 —— 但它确实改变了一些你可能依赖的仪表盘行为。这些变更汇总在下文的
[GUI 刷新（v2 仪表盘）](#gui-刷新v2-仪表盘)中。

## v0.5 → v0.6

### 变更内容

- **内存后端。** `memory_store.jsonl`（每个检查点）和全局
  `$HOME/.ari/global_memory.jsonl`（跨实验）已退役。默认后端
  现为 Letta（每个检查点的独立智能体，归档集合名为
  `ari_node_*` 和 `ari_react_*`）。
- **`$HOME/.ari/` 已移除。** v0.5.0 已删除全局配置目录；
  v0.6 将新布局确立为唯一可写路径。
- **Rubric 系统。** `ari-skill-paper` 采用由 `ARI_RUBRIC`
  选择的 YAML rubric。

### 操作步骤

1. **启动 Letta 服务。** 从
   `docs/guides/hpc_setup.md#6-letta-memory-backend-deployment` 中选择
   一种部署方案：Apptainer SIF、docker-compose 或 pip。
2. **设置必要的环境变量。**
   ```bash
   export LETTA_BASE_URL=http://127.0.0.1:8283
   export LETTA_EMBEDDING_CONFIG=openai/text-embedding-3-small
   export ARI_MEMORY_BACKEND=letta
   ```
   `LETTA_EMBEDDING_CONFIG` 是 embedding *handle*，而非文件路径；
   默认值为 `letta-default`。
3. **迁移现有内存。** 对每个 v0.5 检查点执行：
   ```bash
   ARI_CHECKPOINT_DIR=/path/to/ckpt ari memory migrate
   ```
   迁移工具读取 `memory_store.jsonl`（加 `--react` 时同时读取
   `memory.json`），将条目以 content-addressed 的 v1 记录导入所配置的
   后端，并将结果快照至 `memory_backup.v1.json.gz`。旧版全局 JSONL
   若存在会被报告，但刻意**不**导入。
4. **删除旧版 JSONL 文件。** 迁移工具会把它消费过的每个源文件重命名为
   `<name>.migrated-<纳秒>`，因此只剩全局文件需要手动删除：
   ```bash
   rm $HOME/.ari/global_memory.jsonl   # if it ever existed
   ```
5. **选择 rubric。** 从
   `ari-core/config/reviewer_rubrics/` 中选择一个 YAML 并导出：
   ```bash
   export ARI_RUBRIC=neurips
   ```
   后续的论文评审和 BFTS 评分将使用新的评审维度。

### 验证

- `ari memory health` 打印后端的 health 字典 —— `ok: true` 以及 `backend`、
  `latency_ms`、`server_version` 和 checkpoint 的 `namespace`。
- 来自智能体循环的 `search_memory` 调用返回基于嵌入的排名结果。
- 仪表盘 `/api/memory/health` 端点返回 200。

## v0.6 → v0.7

### 变更内容

- **ORS（对象仓库规范）。** 可复现性链路从 `react_driver` 的
  临时复现方案迁移至 `ari-skill-replicate`（rubric 生成器）+
  `ari-skill-paper-re`（PaperBench SimpleJudge 评分器）。
- **EAR registry。** EAR bundle 可发布至自托管的 `ari-registry`
  服务器（除 local-tarball / Zenodo / GitHub release 外的新选项）。
- **Lineage decisions。** `stagnation_rule` 监控 BFTS 综合评分。
  确认停滞（CONFIRMED）后，ARI 首先**确定性地**转向 `idea.json` 中
  评分最高的**未使用**次选想法（`switch_to_idea`）。LLM 评判
  （`continue` / `switch_to_idea` / `fanout` / `terminate`）仅在无可用的
  确定性转向时（预算耗尽、达到递归上限，或没有剩余的未使用候选）
  作为**回退**才被调用。决策追加写入 `lineage_decisions.jsonl`。
- **work_dir 黑名单。** 子节点 `work_dir` 不再继承结果文件
  （`results.csv`、`slurm-*.out` 等）。现有检查点继续可用，但
  依赖继承的子实验需重新运行。

### 操作步骤

1. **配置 rubric 目录。** 确保
   `ari-core/config/reviewer_rubrics/` 包含所需 rubric。
   `ARI_RUBRIC` 选择当前生效的 rubric。
2. **（可选）启动 `ari registry serve`。** 仅在需要通过 `ari://`
   发布 bundle 时才需要。请先设置 `ARI_REGISTRY_DATA`；
   `ARI_REGISTRIES_FILE` 和 `ARI_REGISTRY_TOKEN` 配置客户端。
3. **重新运行依赖结果继承的子实验。** 黑名单确保子实验不再复制
   `results.csv` / `slurm-*.out` / `node_report.json`。代码、
   编译后的二进制文件和输入文件仍会继承。
4. **（可选）接入可复现性流程。** 论文就绪后执行：
   ```bash
   ari ear curate <checkpoint>
   ari ear publish <checkpoint> --backend ari-registry
   ari paper <checkpoint>
   ```
   并不存在 `ari replicate` / `ari paper-re` 子命令：ORS 链
   (`ors_generate_rubric` → `ors_audit_rubric` → `ors_seed_sandbox` →
   `ors_build_reproduce` → `ors_run_reproduce` → `ors_grade`) 是
   `workflow.yaml` 中的 pipeline stage，由 `ari paper`（以及 `ari run` /
   `ari resume`）通过 MCP skill 驱动。

### 验证

- `lineage_decisions.jsonl` 在 stagnation rule 首次触发时创建。
- `manifest.lock` 和 `publish_record.json` 在 `ari ear publish`
  执行后出现。

## v0.7 → v0.8（未来）

### 预期变更

- Skill 只能从 `ari.public.*` 导入。`tests/test_public_api_boundary.py`
  防护已就位；v0.8 将移除弃用兼容层。
- `ari/migrations/v05_to_v07/` 的辅助工具将移至专属 CLI 接口
  （`ari migrate ...`），不再混杂于 `ari run` 中。

### 预防性步骤

- 检查所有自定义 skill 中是否存在 `from ari import <internal>`
  直接导入。`python -m ari.dev.public_audit`（计划中）可列出这些导入；
  目前可用
  `grep -rn 'from ari import\|from ari\.' my-skill/src/` 代替。
- 找到内部导入后，切换至对应的 `ari.public.*` 模块（参见
  `docs/reference/public_api.md`）。

## v0.8 → v1.0（未来）

弃用计划（`CONTRIBUTING.md::Deprecation process`、
`docs/about/release_policy.md`）安排了以下移除项：

- 移除所有 `$HOME/.ari/...` 文件系统回退（当前会发出
  `DeprecationWarning`）。
- 移除 `ari/migrations/v05_to_v07/`（强制用户在升级前完成迁移）。
- 移除旧版 `node_report` 重建辅助函数。

如果在 v1.0 发布前未完成迁移，ARI 将拒绝启动并给出硬错误，
指引至本指南。

## GUI 刷新（v2 仪表盘）

仪表盘刷新新增了 v2 工作区、`/api/v1`、配置控制平面，以及一个经过加固的
HTTP 接口面。legacy 页面、legacy hash URL 与 legacy `/api/*` 端点都并行
继续工作，因此这次迁移的大部分是不可见的。下文是**用户可见行为变更**的
完整清单 —— 那些以前会成功而现在会拒绝、或者以前返回数据而现在返回占位内容
的地方。

这里没有任何东西会改写检查点。每一个新工件
（`resolved_config.json`、`launch_events.jsonl`、
`{workspace_root}/gui_store/`）都是增量新增的，并且会被更旧的 ARI 忽略，
因此降级永远不需要数据迁移。

### 回滚手段速览

每个手段都是一个在服务器启动时读取的环境变量：设置它、重启 `ari viz`，
无需重新构建。它们中的每一个都会重新打开对应变更所关闭的风险，因此请把它们
当作事故处置工具，而不是默认配置。这些手段的分阶段切换与移除计划见
[GUI 切换运行手册](gui_cutover_runbook.md)。

| 手段 | 恢复为 |
|---|---|
| `ARI_GUI_BIND='::'` | 刷新前的全接口绑定 |
| `ARI_GUI_CORS_ANY=1` | 刷新前的 `Access-Control-Allow-Origin: *` |
| `ARI_GUI_CHALLENGES=0` | 无需服务器挑战的破坏性端点 |
| `ARI_GUI_CSP=0` | 不带 CSP / nosniff / referrer 响应头的响应 |
| `ARI_GUI_AUTH=0` | 无认证的远程绑定 |
| `ARI_GUI_HEALTH=0` | `/health/*` 返回 SPA HTML，诊断端点返回 404 |
| `ARI_GUI_V2=0` | legacy 外壳（隐藏 v2 导航条目与路由） |

有四项变更**没有**环境变量手段 —— 它们是纯粹的修复，没有受支持的回头路
（MN-1、MN-2、MN-3，以及 MN-5 中 `/codefile` 的那一半）。对这些变更而言，
revert 该提交是唯一选项。MN-12（GUI 模式选择）同样没有手段，但也不需要：
它的「关闭」状态就是保持默认选择，而那会启动一次逐字节相同的运行。

### 编辑 workflow 需要一个活动的 project（MN-1）

- **之前** —— 在没有选中活动检查点时，`POST /api/workflow`、
  `/api/workflow/flow`、`/api/workflow/skills` 与
  `/api/workflow/disabled-tools` 会静默改写捆绑的
  `ari-core/config/workflow.yaml` 并返回「成功」，在毫无警告的情况下改变了
  之后每一次 CLI 与 GUI 运行的默认流水线。
- **之后** —— 在没有活动检查点时，这四个端点返回 **400** 且不写入任何内容：
  `{"ok": false, "error": "No active project. Select a checkpoint before
  editing the workflow (the bundled default workflow.yaml is read-only from
  the GUI)."}`。在选中检查点后，编辑与以前完全一样，针对的是每检查点的
  写时复制副本。`GET /api/workflow` 未变更 —— 把捆绑默认值作为回退来读取
  是合理的。
- **原因** —— 一次 GUI 编辑绝不应改变其他运行所继承的、随发行版分发的配置。
  该写入守卫被四个处理器共享，因此未来的写入端点会自动继承它。
- **回滚** —— 无。请先选择（或创建）一个运行；既没有环境变量手段，也没有
  需要撤销的数据迁移。

### secret 绝不返回；就绪状态取代自动填充（MN-2）

- **之前** —— `GET /api/env-keys` 会返回名称中含有 `API_KEY`、`SECRET` 或
  `TOKEN` 的每一个环境变量的**明文**值，连同它们各自来自哪个文件。向导的
  开发者模式「Auto-read」用这些值预填 API key 字段。
- **之后** —— 三件事：
  1. `GET /api/env-keys` 被脱敏。非空值变成 `***configured***`，空值保持
     `""`，`source` 映射不变，而顶层的 `"redacted": true` 标记让客户端能
     检测到新契约。
  2. 新的 `GET /api/v1/secrets/status` 对一份 secret 名称允许列表只返回
     `{name, configured, source_class, last_updated}` —— 该响应根本没有值
     字段。
  3. `POST /api/env-keys` 仍像以前那样写入，但键名不符合
     `^[A-Z][A-Z0-9_]{0,63}$`（或含有换行/控制字符）时会被 **400** 拒绝。
- **原因** —— 一个会交出凭据的 HTTP 接口面就是凭据泄漏，无论客户端拿它做
  什么。就绪状态（「它是否已配置，来自哪一类来源」）才是 UI 真正需要的全部。
- **回滚** —— 无。「Auto-read」现在展示 `configured (source_class)` 或
  `not configured`，而不再填充该字段；把字段留空，启动时就会使用来自 `.env`
  的值。手工输入 key 以及从 Settings 页面保存 key 的行为未变。

### workflow 自动保存改为检测冲突而非覆盖（MN-3）

- **之前** —— workflow 编辑器在编辑两秒后自动保存，直接 POST 覆盖磁盘上的
  任何内容，而不先读取它。在另一个标签页、由另一个用户或由外部进程所做的
  更改会被静默摧毁。
- **之后** —— `GET /api/workflow` 返回一个 `revision`（所提供
  `workflow.yaml` 字节的 sha256 前缀）。四个写入端点接受可选的
  `base_revision`；当它过期时，它们返回 **409** 与
  `{"ok": false, "error": "workflow changed on disk since you loaded it
  (revision mismatch); reload before saving"}` 并且不写入任何内容（连写时
  复制种子也不写）。成功时，新的 `revision` 会随响应返回。编辑器在每次保存
  时都发送 `base_revision`，保持同样的两秒节奏，并展示一个明确的状态 chip
  —— Unsaved changes / Saving / Saved / Conflict。发生冲突时它完全停止保存，
  等待一次显式的 **Reload**，该操作会重新读取磁盘并丢弃未保存的本地编辑
  （横幅会如实说明）。
- **原因** —— 一次「报告成功却摧毁了别人编辑」的保存，比一次失败的保存更糟。
- **回滚** —— 对 GUI 而言没有。省略 `base_revision` 的 API 客户端保持旧的
  最后写入者获胜行为，因此该变更在协议层面是增量式的。

### 默认回环绑定与同源 CORS（MN-4）

- **之前** —— HTTP 服务器与端口 +1 的 WebSocket 服务器绑定**所有接口**，
  因此局域网或集群网络上的任何东西都能在没有认证的情况下访问每一个端点。
  JSON 响应、OPTIONS 预检、SSE 流、手工构造的二进制响应（`/memory/`、
  `/codefile`、论文 PDF/TeX、原始文件）以及 ollama 代理，全都返回
  `Access-Control-Allow-Origin: *`，因此任何网页都能读取它们。
- **之后** —— 绑定默认值是**仅回环**（`127.0.0.1` 加 `::1`，因此无论你的
  发行版把 `localhost` 解析到哪个地址族都能用）。只有当请求的 `Origin` 与
  服务器自身 origin 匹配时（`Host` 头匹配，或服务器端口上的 `localhost` /
  `127.0.0.1` / `[::1]` 形式）CORS 才回显它，并添加 `Vary: Origin`；不匹配
  的 origin 根本得不到 `Access-Control-Allow-Origin` 头，来自它的预检只会
  得到一个裸的 204。`/state` 与 `GET /api/gpu-monitor` 与以前完全一样，
  仍然不带这些头。
- **原因** —— 无认证的全接口绑定加上通配符 CORS 策略，等于给整个集群网络
  开了一个远程控制面。
- **回滚** —— `ARI_GUI_BIND='::'` 恢复旧的双栈通配符绑定（仅 IPv4 用
  `'0.0.0.0'`，或指定单个地址）；`ARI_GUI_CORS_ANY=1` 恢复通配符响应头。
  两者一起使用可复现旧行为。通过 `http://localhost:8765` 的本地使用、SSH
  隧道或 Vite 开发代理，两者都不需要。从另一台主机打开
  `http://<server-ip>:8765` 现在需要 `ARI_GUI_BIND`。

### `/codefile` 路径边界与 ollama 代理允许列表（MN-5）

- **之前** —— `GET /codefile?path=` 会提供任何绝对路径，只要它位于活动
  检查点之下**或者**字符串中任意位置仅仅含有一个 `checkpoints` 组件，因此
  像 `/tmp/fake/checkpoints/x` 这样精心构造的路径 —— 或一个指向树外的符号
  链接 —— 就能读取任意文件。`GET|POST /api/ollama/<path>` 即便在没有配置
  任何 ollama 主机时，也会把**任何**路径中继到隐含的
  `http://localhost:11434`，这使它成为通向本地 HTTP 服务的通用中继。
- **之后** —— 只有当文件解析后的规范路径（跟随符号链接）是一个位于活动
  检查点目录之下或某个已解析检查点搜索基路径之下的常规文件时，`/codefile`
  才提供它。`..` 片段在解析前就被拒绝，符号链接逃逸被前缀比较拒绝，而目录
  或不存在的文件仍像以前一样是 404；20 MB 上限、内容类型与状态码均未变更。
  ollama 代理只有在路径属于 `/api/tags`、`/api/show`、`/api/generate`、
  `/api/chat`、`/api/ps` 之一**并且**目标被显式配置（settings 中的
  `ollama_host` 或 `OLLAMA_HOST`）或生效的 LLM 后端就是 `ollama` 时才转发
  —— 只有在最后这种情况下 `localhost:11434` 默认值才仍然适用。否则它返回
  **403**，且不会打开任何上游连接。
- **原因** —— 「路径里含有 checkpoints 这个词」不是一条边界，而一个开放式的
  localhost 代理是一个跳板。
- **回滚** —— `/codefile` 的修复按设计**没有**回滚手段。对代理而言，受支持
  的「回滚」是把目标配置好（`ollama_host` 或 `OLLAMA_HOST`）；中继非允许
  列表内的路径无法恢复。位于默认检查点位置下的工件，以及在 ollama 后端上的
  ollama 代理，行为与以前完全一致。

### 破坏性操作需要服务器签发的挑战（MN-6）

- **之前** —— 确认只在客户端进行。`POST /api/delete-checkpoint` 会对提交的
  路径执行 `rmtree`，`POST /api/stop` 会杀掉每一个被跟踪的进程（包括一次
  `pkill`），而带 `action=stop` 的 `POST /api/gpu-monitor` 会直接执行 ——
  它们背后不过是一个浏览器对话框。GPU 监控的 `confirmed: true` 在 API 层被
  硬编码。
- **之后** —— `POST /api/v1/challenges` 携带 `{action, target}`（动作：
  `delete-checkpoint`、`stop-all`、`gpu-monitor-stop`）签发一次性授权
  `{challenge_id: "chg-<12hex>", action, target, expires_at,
  ttl_seconds: 60}`。TTL 基于单调时钟计量，因此挂钟跳变无法延长它，而签发 /
  消费 / 拒绝都作为 `challenge_*` 事件记入活动检查点的
  `viz_access.jsonl`。只有当请求体携带的 `challenge_id` 未被使用、未过期、
  且绑定到相同的 action **与** target 时，这三个破坏性端点才会执行；其他
  任何情况都是 **428** 加
  `{"ok": false, "error": "confirmation challenge required or invalid"}`，
  并且完全不做任何破坏性工作。在 GUI 中这一切是不可见的，只有两点不同：
  确认对话框现在展示服务器回显的目标，而 **Stop** 现在会请求确认（以前
  不会）。
- **原因** —— 客户端不能是横在一个误发请求与 `rmtree` 之间的唯一屏障。
- **回滚** —— `ARI_GUI_CHALLENGES=0` 把这三个端点恢复为直接执行（挑战端点
  保留，因此两步式客户端继续工作）。用 `curl` 调用旧端点的自动化，要么先
  获取一个挑战，要么设置该变量。

### CSP、去掉 CDN 脚本与加固的静态响应（MN-7）

- **之前** —— `frontend/index.html` 除了 npm 打包产物中已有的副本之外，还从
  `cdn.jsdelivr.net` 加载 d3（没有任何代码使用 `window.d3`），而 SPA 首页与
  `/static/` 响应都不带 `Content-Security-Policy`、
  `X-Content-Type-Options` 或 `Referrer-Policy`。向导中还残留一处
  `dangerouslySetInnerHTML`。
- **之后** —— CDN `<script>` 已移除（d3 随打包产物发布），SPA 首页与
  `/static/` 响应发送 `Content-Security-Policy`（`default-src 'self'`、
  `script-src 'self'`、`style-src 'self' 'unsafe-inline'`、
  `img-src 'self' data:`、`connect-src 'self'` 加上端口 +1 上树实时流的
  `ws://`/`wss://` origin、`frame-src 'self'`、`frame-ancestors 'none'`）、
  `X-Content-Type-Options: nosniff` 与 `Referrer-Policy: no-referrer`。
  API 与 JSON 响应不受影响。`dangerouslySetInnerHTML` 已从 SPA 中彻底移除。
- **原因** —— 少一个供应链依赖，加上一条限定被攻陷的打包产物所能触及范围的
  策略。
- **回滚** —— `ARI_GUI_CSP=0` 停止发送这三个响应头。有两个后果值得提前规划：
  把仪表盘嵌入到别的站点的 iframe 中不再可行（`frame-ancestors 'none'`），
  以及重映射了 WebSocket 端口的反向代理会看到 WebSocket 被拦截、树视图降级
  为轮询 —— 那种拓扑正是使用该手段的唯一正当理由。离线安装严格受益：不再有
  会失败的 CDN 抓取。

### 远程绑定需要 bearer token（MN-8）

- **之前** —— 选择加入远程绑定会把每一个端点 —— 包括删除、进程控制与
  secret 写入 —— 连同端口 +1 的 WebSocket 一起暴露出去，且**没有认证**。
  MN-4 修好了默认值；它并没有添加凭据。
- **之后** —— 当绑定为非回环时，除 `/health` 与 `/health/*` 外的每个 HTTP
  请求都必须携带 `Authorization: Bearer <ARI_GUI_TOKEN>`。缺失或错误的
  token 得到 **401**，带 `WWW-Authenticate: Bearer` 与类型化的 JSON 响应体；
  比较是常量时间的。如果在远程绑定下未设置 `ARI_GUI_TOKEN`，服务器会在启动
  时生成一个随机 32 位十六进制 token 并向 stderr 打印一次 —— 不存在任何以
  无认证方式启动远程绑定的代码路径。由于 `EventSource` 与 `WebSocket` 无法
  设置请求头，SSE 流与 WebSocket 握手也接受同一个 token 作为 `token=` 查询
  参数；访问日志把 `token=` 脱敏为 `***`，因此该 token 绝不会进入
  `viz_access.jsonl`。前端读取 `localStorage` 的 `ari_gui_token` 键。
  **回环默认配置逐字节未变，并且仍然是无认证的。**
- **原因** —— 没有凭据的远程绑定就是一个多绕了几步的远程 shell。
- **回滚** —— `ARI_GUI_AUTH=0` 关闭该闸门（合理用法是前面有一个负责认证的
  反向代理）。要远程使用，要么自己设置 `ARI_GUI_TOKEN`，要么从 stderr 收集
  生成的 token，然后在浏览器中执行一次
  `localStorage.setItem('ari_gui_token', '<token>')`；`curl` 需要
  `-H 'Authorization: Bearer <token>'`。在 Settings UI 中提供 token 输入框
  仍是后续工作。

### 健康探针与有界诊断（MN-9）

- **之前** —— `/health/live` 与 `/health/ready` 没有处理器，会穿透到 SPA 的
  HTML，而这对探针毫无用处。既没有诊断端点，也无法从外部观察 SSE 订阅者、
  监视器存活状态或被跟踪的进程数。
- **之后** —— `GET /health/live` 返回常量 `{"status": "ok"}`，不做任何依赖
  检查（处理器只要能应答，进程就是存活的）。`GET /health/ready` 返回
  `{"status": "ok"|"degraded", "checks": {http, websocket, watcher,
  event_bus, active_checkpoint}}`；每项检查独立求值，异常会把该检查降级为
  `false`，因此就绪探针永不返回 500 —— `degraded` 是一个诚实的 200。
  `GET /api/v1/diagnostics` 只返回有界标量：
  `sse {subscribers, buffer_len, last_event_id}`、
  `watcher {alive, last_scan_age_s}`、`process {tracked_runs}`（一个计数，
  不是路径）、`cache: false`（缓存子系统尚不存在），外加 `schema_version`
  与 `openapi_version`。没有 secret，也没有文件系统路径。
- **原因** —— 运维者需要把存活与就绪分开，也需要一个不会泄漏的指标接口面。
- **回滚** —— `ARI_GUI_HEALTH=0` 恢复变更前的行为（`/health/*` 返回 SPA
  HTML，诊断端点返回类型化的 404）。无论哪种情况，正常的 GUI 使用都不受
  影响；React 应用不调用这些端点。请注意认证的不对称：`/health/*` 免除
  MN-8 的 token 闸门，`/api/v1/diagnostics` 不免除。

### 规范的幂等启动（MN-10）

- **之前** —— 启动只经由 `POST /api/launch`，它会在*响应之前*执行 LLM slug
  生成、一次 `sinfo` 调度器探测以及文件系统变更；运行没有唯一身份（时间戳
  加 slug，因此并行启动可能碰撞）；双击会拉起第二个子进程；而且响应中不带
  `run_id`。
- **之后** —— 规范端点是 `POST /api/v1/runs`，携带
  `{draft_id, display_name?, profile?, idempotency_key?}`：
  - **校验优先** —— 未知草稿返回类型化的 404，校验失败返回类型化的 400 并
    带 `details.errors`，而失败的请求在磁盘上**什么都不改**；
  - **由服务器签发身份** ——
    `run_id = <UTC YYYYMMDDHHMMSS>_<slug>-<uuid4 6hex>`，slug 由显示名或
    goal 的第一行确定性推导（在接受之前不做 LLM 调用，也不做调度器探测）；
  - **先物化，再拉起** —— `experiment.md`、`workflow.yaml`（以写时复制方式
    从捆绑默认值播种）、`launch_config.json`、`resolved_config.json`，以及
    一份 `launch_events.jsonl` 生命周期
    （`draft → validating → accepted → spawned`，或 `failed`），然后是与
    以前相同的 `python3 -m ari.cli run` 子进程；
  - **幂等性** —— `idempotency_key` 会在拉起*之前*以仅创建方式占用
    `{workspace_root}/gui_store/launches/{key}.json`，因此重复的 POST 会
    返回同一个 `run_id` 并带 `idempotent_replay: true`，且不拉起任何东西；
  - 一次启动**不会**切换全局活动检查点。
  另有两条仅启动时的拒绝规则：没有 goal 的草稿返回 400 `missing_goal`，
  而含有 `ari.mode` 或任何 `rqgm.*` 字段的草稿返回 400 `mode_locked` ——
  在当时，从 GUI 选择治理/执行模式仍是一个悬而未决的决策。
  *（已被 MN-12 取代：四个模式叶子现在对新运行是被接受的；其余 104 条
  `rqgm.*` 路径仍然以 `mode_locked` 拒绝。）*
- **原因** —— 一次运行在任何东西被写下之前就需要一个身份，而一次双击不应
  分叉出一个实验。
- **回滚** —— 无需回滚。`POST /api/launch` 未变更且并行运行，每个新文件都是
  增量新增的，也不涉及任何数据迁移。

### 从配置工作室启动（MN-11）

- **之前** —— 上述启动协议只有 API。从 GUI 启动的唯一方式是 legacy 向导，
  而 Studio 草稿只能编辑。
- **之后** —— `#/studio?draft=<id>` 获得一个带 goal → review → launch 步骤条
  的启动面板。**Resolve & validate** 调用该草稿的 `resolve-config` 与
  `validate` 端点，并展示：针对每一个取值并非来自默认层的叶子，生效配置与
  默认值的差异；可归因于该草稿的校验错误；解析器警告；secret 就绪状态行
  （值在结构上不存在）；以及治理锁定说明。不可变的复核摘要 —— 显示名、
  profile、已解析的执行模式与论文模式（MN-12）、被更改的字段数、配置摘要，
  以及一条明确说明 `run_id` 由服务器在
  accept 时签发的备注 —— 由一个确认勾选框门控，每次批准恰好铸造一个幂等键。
  **Launch** 会 POST `/api/v1/runs` 并使用服务器签发的 id 跳转到
  `#/overview?run=<run_id>`，不做任何 mtime 或「最新检查点」的猜测；双击或
  重试会重放同一个键，因此只会拉起一个运行。失败会渲染类型化的错误信封，
  包括 `missing_goal` 与 `mode_locked`。
- **原因** —— 复核这一步是运维者仍然可以说「不」的地方，因此它必须展示已解析
  的配置，而不是草稿的意图。
- **回滚** —— 无需回滚；该面板是纯前端的增量新增。legacy 向导仍完全可用，
  而 MN-10 的后端与它彼此独立。

### 执行模式与论文模式对新运行可选（MN-12）

- **之前** —— `Execution mode` 类别中的每一个字段以及每一条 `rqgm.*` 路径
  （目前共 108 条）都被挡在 GUI 之外：在 Studio 中是一个被禁用的分组，从
  `POST /api/v1/runs` 则返回 400 `mode_locked`。要选择 `ari_rqgm` 或
  `rqgm_archive`，就得手工编辑 `workflow.yaml` 中两个相互联锁的键。
- **之后** —— 恰好四个叶子开放，构成两组正交的成对意图：
  `ari.mode` + `rqgm.enabled` 与 `paper.mode` + `rqgm.paper.enabled`。一个
  Studio 控件会同时写入其配对的**两个**键，因此在 UI 中无法构造出只设一半的
  配对；在其他任何地方它都是类型化的 400 `mode_interlock_mismatch`
  （模板与草稿的 create/PATCH，以及启动），并在合并后的文档取值上求值。
  非默认的选择会被实体化两次 —— 最小的 `ari:`/`rqgm:`/`paper:` 块被合并进
  该运行自己的 `workflow.yaml` 副本（绝不会写随包分发的那份文件），外加
  文档化的 `ARI_MODE` / `ARI_RQGM_ENABLED` / `ARI_PAPER_MODE` /
  `ARI_RQGM_PAPER_ENABLED` 环境变量。启动复核展示的是**已解析**的模式；
  未被采纳的请求会以 `requested → resolved` 的形式、连同解析器的原文警告
  一起呈现，而不是悄悄地启动回退运行。其余 104 条 `rqgm.*` 治理与调参参数
  仍然只能通过配置文件设置 —— 以只读方式连同其生效值可见，启动时依旧返回
  400 `mode_locked` —— RQGM 的 API 面也仍然是只读的。**恢复运行不受影响**：
  持久化在 `{checkpoint}/rqgm_state.json` 中的模式依然胜出 —— 朝任一方向都
  胜出，因此一次运行的模式在其整个生命周期内固定不变 —— 且没有任何 GUI
  路径会写这个文件。
- **原因** —— GUI 是被提供出来的启动界面，却无法陈述它正要开启的这次运行
  最为关键的性质；与此同时，一刀切的锁定把「跑哪个算法」和「对抗预算是
  多少」当成了同一个决策（ADR-09）。
- **回滚** —— 没有环境变量手段，也不需要：保持默认选择
  （`simple_bfts` + `linear`）就会得到逐字节相同的启动，即便是显式地重新
  选中默认值也一样。`ARI_GUI_V2=0` 会移除整个 v2 Studio，而 legacy 向导
  仍按默认启动。revert 该提交不需要任何数据迁移 —— 唯一的新产物是每次运行
  各自 `workflow.yaml` 副本中的增量块，旧版 ARI 会忽略它们。

## 参见

- [GUI 切换运行手册](gui_cutover_runbook.md) —— 把 v2 仪表盘设为默认、
  分阶段推出，以及 legacy 移除顺序。
- [RQGM 迁移指南](rqgm_migration.md) —— 开启可选的 `ari_rqgm` 模式
  （仅配置；无格式变更）。
- `CHANGELOG.md` —— 各版本发布说明。
- `ari memory migrate --help` —— v0.5 → v0.6 迁移工具的 CLI 选项。
- `docs/guides/troubleshooting.md` —— 迁移失败时的处理方法。
