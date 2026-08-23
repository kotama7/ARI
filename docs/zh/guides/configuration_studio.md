---
sources:
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: ari-core/ari/config/resolver.py
    role: implementation
  - path: ari-core/ari/viz/v1/config_api.py
    role: implementation
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/viz/v1/secrets.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/v1/catalogs.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigBrowser/ConfigBrowserPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/ConfigStudioPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/LaunchPanel.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/ExecutionSection.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/modeIntents.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/SecretField.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/StudioPickers.tsx
    role: implementation
  - path: ari-core/tests/test_gui_config_resolver.py
    role: test
  - path: ari-core/tests/test_gui_v1_launch.py
    role: test
  - path: ari-core/tests/test_gui_v1_mode_selection.py
    role: test
  - path: ari-core/tests/test_gui_secret_readiness.py
    role: test
last_verified: 2026-08-17
---

# 配置工作室指南

两个页面共享同一份规范字段注册表：

- **Config**（`#/config?run=`）—— 只读。*这次运行实际使用了什么配置，每个值
  又来自哪里？*
- **Studio**（`#/studio`）—— 编辑扩展。*下一次运行应该使用什么？* 包括
  project 默认值、run 模板、run 草稿以及启动流程。

两者都是 v2 工作区，因此需要 `gui_v2` 能力（见[仪表盘指南](dashboard.md)）。
它们都无法编辑一个已在运行的 run：检查点的配置是被事后解释的，绝不会被改写。

## 字段注册表

两个页面上的一切，都由一份「已声明 `ARIConfig` 叶子的机器可读清单」与一份
手写元数据叠加层合并生成。当前是 **205 个叶子、元数据覆盖率 100 %** ——
注册表构建过程宁可抛出异常，也不会放行一个没有元数据的字段，因此新的配置
字段不可能在缺少 category、level、scope、sensitivity 与 mutability 的情况下
悄悄出现。

当前的分类：Governance（104）、Models（32）、Search (BFTS)（24）、
Proposal routing（14）、Manuscript completeness（10）、Scientific assurance（6）、
Infrastructure（5）、Evaluation（4）、Execution mode（4）、Skills（2）。

该注册表由 `GET /api/v1/config/schema` 提供。它**只携带元数据** —— 绝不包含
生效值 —— 而 `secret_reference` 字段根本不携带默认值。

## 检视生效配置（`#/config?run=`）

**带**着一个 run 打开该页面，你会得到该检查点的已解析清单；**不带** `?run=`
打开时，它会诚实地降级为一个 schema 浏览器，展示默认值（「No run selected ——
showing the configuration schema with default values」）。

每一行展示点分路径、生效值、一个**溯源来源**徽章、一个**可变性**徽章、
适用时的低置信度标记，以及任何 `applies_when` 备注。搜索框可按路径或分类
过滤，因此 205 个字段中的每一个都保持可被发现。解析器警告会在它们自己的
面板中逐字列出 —— 什么都不会被静默丢弃。

![单个运行的 Config 浏览器：解析器警告面板、字段计数旁的过滤框，以及按类别分组的表格，逐行列出点分路径、生效值、溯源来源徽章与可变性徽章；`llm.api_key` 一行显示为「secret (reference only)」](../../assets/images/zh/dashboard_config.png)

过滤框旁边的计数可能大于 205。已解析清单里那些注册表并不认识的叶子仍会被
展示，归到 **Other** 分组下 —— 一条清单路径绝不会仅仅因为缺少注册表元数据
就被丢弃。

清单本身来自 `GET /api/v1/runs/{run_id}/resolved-config`，由
`legacy-compatible-1` 解析器产生，它在不实际运行命令式 CLI 链的前提下重建
出该链本会产生的结果。

### 溯源徽章（既有检查点）

解析器按顺序重放这些层；徽章指明胜出的那一层：

| 徽章 | 层 | 置信度 |
|---|---|---|
| `default` | pydantic 模型默认值 | high |
| `workflow` | `{checkpoint}/workflow.yaml` | high |
| `launch_config` | `{checkpoint}/launch_config.json` | high |
| `env` | **当前**进程环境，仅限有文档记录的 `ARI_*` 变量 | **low** |
| `checkpoint_state` | `{checkpoint}/rqgm_state.json` 中持久化的模式 | high |

`env` 被有意标为**低置信度**：它反映的是*此刻*的环境，未必是该运行启动时
所处的环境。低置信度标记的意思是「这项归因是重建出来的，请把它当作一个
假设」。

新运行预览（供 Studio 启动流程使用）使用另一套更长的层栈，并有自己的徽章：
`default` → `workflow`（捆绑的）→ `profile` → `project` → `template` →
`draft` → `env`。

### 可变性徽章

| 徽章 | 含义 |
|---|---|
| `draft` | 只要该 run 仍是草稿就可自由编辑 |
| `new_run_only` | 一旦运行开始即固定；请为*下一次*运行修改它 |
| `resume_mutable` | 恢复既有运行时可以修改 |
| `read_only` | 在任何 scope 下配置 API 都绝不接受 |

启动之前，新运行预览会把每个非 `read_only` 字段报告为可变 ——
`new_run_only` 只有在运行存在之后才会生效。

### 浏览器中的 secret

`secret_reference` 行渲染为字面文本 **`secret (reference only)`**。这里没有值
可供揭示，也没有用于揭示的开关：后端把 secret 叶子完全排除在 `values`、
`provenance` 与清单摘要之外，只以「已配置/未配置」标志的形式呈现它们。
摘要是对脱敏后的规范值求 `sha256:`，因此既稳定又不泄漏。

`resolved_at` 由源文件的 mtime 推导，绝不使用 `now()`，因此对同一个未改变的
检查点重复 GET 的结果逐字节稳定。

## 在 Studio 中编辑（`#/studio`）

Studio 就是同一份注册表以表单形式渲染出来。控件由元数据推导，而不是逐字段
手写：`enum` → 下拉选择，`bool` → 开关，`int`/`float` → 数字输入框，`str` →
文本输入框，`secret_reference` → 只写的 secret 控件，复合类型（列表、字典、
嵌套模型）→ 一个明确**禁用**的输入框并展示原因（「复合字段 — 请通过
workflow.yaml 编辑（自定义编辑器待定）。」）。不可用的控件总是说明原因；
它们绝不会被静默隐藏。

![Studio：顶部的 scope 标签条、模板与草稿的创建控件、左侧类别列表，右侧由注册表生成的表单（下拉选择、文本输入框，以及带名称选择器、「configured (repo_env)」徽章和密码输入框的只写 secret 控件）；页脚是 Save changes、Discard edits、未保存编辑状态与文档 revision](../../assets/images/zh/dashboard_studio.png)

模型/provider 建议来自服务端目录（`GET /api/v1/config/catalogs/models`）——
前端里没有任何模型常量。

每个字段行还带一个状态徽章：`edited`（有未保存的本地更改）、`saved`（已存在
于所存储的文档中）或 `default`（没有存储任何值 —— 该字段穿透到下一层）。

### 控件是如何被选出来的

页面读取注册表条目，并在第一个匹配处停止：

1. `sensitivity` 为 `secret_reference` → 只写的 secret 控件；
2. 非空的 `enum` → 下拉选择；
3. 否则把 `value_type` 字符串按 `|` 切分并丢弃 `None`。若恰好只剩**一个**
   成员：`bool` → 开关，`int`/`float` → 数字输入框，`str` → 文本输入框；
4. 其余一律为复合 —— 切分后剩下多于一个成员，或者是 `list[…]` /
   `dict[…]` / 嵌套模型的注解。

也就是说 `sensitivity` 优先于 `enum`，而 `enum` 优先于类型。取值为 enum 的
secret 仍会得到 secret 控件；取值为整数的 enum 仍会得到下拉选择，而不是数字
输入框。

**已知缺口：不存在 `field path/pattern → custom editor` 注册表。**
本工作区的 GUI 计划要求过这样一个注册表，好让领域特定的字段通过自我声明、
而不是通过改动页面来取得更丰富的控件。该注册表从未被实现。两处*并非*由
`value_type` 推导出来的渲染，是编进页面里的结构性特例，而不是字段可以注册的
条目：

- `sensitivity: secret_reference` 选出 secret 控件。这一条以元数据为键，因此
  将来新增的 secret 叶子会自动继承它 —— 今天注册表里唯一的 secret 叶子是
  `llm.api_key`。
- `category` 为 `Execution mode` 的字段，或路径以 `rqgm.` 开头的字段，会在
  通用表格被构建之前就被分流进 Execution 区块（见下文 *执行模式：可选择；
  治理调优：仍仅限文件*）。

在控件渲染处被特判的字面路径恰好只有一个：拿到模型目录 datalist 的
`llm.model`。其余字段全部按上面的规则渲染。

这对新增配置字段的人意味着：你免费获得一个生成出来的控件，却没有地方去注册
一个更好的控件。schema 条目不携带任何逐字段的编辑器提示 —— 它的键是 `path`、
`value_type`、`default`、`enum`、`required`、`category`、`level`、`scope`、
`sensitivity`、`mutability`、`applies_when`、`notes`、`source` 与
`env_override` —— 因此今天要给某个路径配上专用编辑器，只能去改 Studio 页面
组件本身。这正是为什么每个复合叶子 —— `skills`、`resources`、
`evaluator.axis_weights`、`evaluator.custom_axes` —— 都被渲染成一个说明原因的
禁用输入框，而不是编辑器。值仍然会被展示，绝不会被隐藏；只是无法从这个界面
编辑。

### 三种 scope

scope 栏切换你正在编辑的文档；hash 会记录它：

| Scope | Hash | 文档 | 端点 |
|---|---|---|---|
| Project 默认值 | `#/studio` | 唯一的 `default` project 配置 | `GET/PATCH /api/v1/projects/default/config` |
| Run 模板 | `#/studio?template=<id>` | 一个可复用的具名模板 | `GET/POST /api/v1/run-templates`、`GET/PATCH/DELETE .../{id}` |
| Run 草稿 | `#/studio?draft=<id>` | 一次待启动的运行 | `POST /api/v1/run-drafts`、`GET/PATCH .../{id}` |

创建模板需要提供一个小写的 `template-id` 与一个显示名；创建草稿可以选择性地
*基于*某个模板，也可以选择性地带一个 **goal**（自由文本）。goal 是一个文档
字段，不是配置路径 —— 它绝不随 `values` 传递，而启动会把它物化为
`{checkpoint}/experiment.md`。

切换文档会丢弃未保存的编辑缓冲区并清除结果横幅，因此一个文档的编辑绝不会
泄漏到另一个文档。

### 文档存放在哪里

三类文档都存储在服务端的 `{workspace_root}/gui_store/` 下 —— 它是
`checkpoints/` 的同级目录：

```text
{workspace_root}/gui_store/
├── project_config.json
├── run_templates/{template_id}.json
├── run_drafts/{draft_id}.json
└── launches/{idempotency_key}.json
```

这是一个**仅供 GUI 使用的便利层**。不存在 `~/.ari` 全局目录，模板的寿命长于
检查点删除，而 CLI / `simple_bfts` 路径从不读取其中任何内容 —— 启动会像
一直以来那样把每个生效值物化进检查点。写入是原子的（同目录临时文件 +
`fsync` + `os.replace`），并使用仅属主可访问的权限（文件 `0600`，目录
`0700`）。

### If-Match 冲突

每个文档都携带一个整型 `revision`，而每次变更都必须回显它：

```http
PATCH /api/v1/projects/default/config
If-Match: "3"
Content-Type: application/json

{"values": {"bfts.max_total_nodes": 40}}
```

- **没有 `If-Match`** → `400 invalid_request`
  （*mutations require the `If-Match: "<revision>"` header*）。
- **过期的 `If-Match`** → `409 revision_conflict`。
- `If-Match: "0"` 表示「该文档必须尚不存在」（创建）。

在 UI 中，409 会弹出 **Revision conflict** 面板：

> This document changed on the server since it was loaded. Reload to get
> the latest revision — your unsaved edits are kept locally.  [Reload]

**该怎么做：** 点击 Reload。它会按当前修订号重新抓取该文档；你待处理的编辑
留在本地缓冲区中，因此既不会被静默丢弃，也不会被静默覆盖。重新应用你仍然
想要的编辑，再次保存即可。这是对旧版盲目覆盖式自动保存的有意替代 —— 服务器
拒绝让一次过期写入胜出。

### 逐路径的校验错误

PATCH 请求体的 `values` 映射是一个扁平的 `{"dotted.path": value}` 局部更新，在写入
任何东西之前都会先按注册表校验。拒绝以 `400` 返回，违规路径放在 `details.errors` 中，
UI 会把它渲染为 **Validation errors** 列表。`reason` 词汇表是闭合的：

| `reason` | 含义 |
|---|---|
| `unknown_path` | 不是注册表中的路径 |
| `invalid_type` | 类型错误（`expected` 携带注册表的 `value_type`） |
| `invalid_enum` | 不是允许的取值（`expected` 携带允许的集合） |
| `read_only` | 在任何 scope 下都被拒绝 |
| `secret_reference` | secret 绝不通过配置 API 传输 |
| `not_project_scope` | 一个 scope 不是 `project` 的 `new_run_only` 字段被 patch 进了 project 配置 |
| `mode_interlock_mismatch` | 下文的跨路径配对检查 —— 只写了模式意图的一半，缺少与之一致的孪生键 |

`new_run_only` 字段在模板与草稿中*确实*会被接受 —— 它们配置的是未来的运行。

## secret 如何工作

通过 GUI 时，secret **永远是只写的**。

- **只有就绪状态，绝无值。** `GET /api/v1/secrets/status` 针对一份固定的
  名称允许列表返回 `configured`（布尔值）、`source_class`（`project_env` =
  当前检查点的 `.env`，`repo_env` = `ARI/.env` 或 `ari-core/.env`，
  `user_env` = `~/.env`，`process_env` = 进程环境回退），以及
  `last_updated`（源文件的 mtime）。响应 DTO 没有值字段，因此把 secret 回显
  出去在结构上是不可能的。
- **允许列表**是从代码中枚举出来的，而不是臆造的：`OPENAI_API_KEY`、
  `ANTHROPIC_API_KEY`、`GOOGLE_API_KEY`、`GEMINI_API_KEY`、
  `SEMANTIC_SCHOLAR_API_KEY`、`LETTA_API_KEY`、`ZENODO_TOKEN`、
  `ARI_REGISTRY_TOKEN`。不在其中的名称会得到 404。
- **写入。** `PUT /api/v1/secrets/{secret_id}` 接收值并委托给经过加固的
  `.env` 写入器：原子的同目录临时文件 + `fsync` + `os.replace`、`0600`
  权限，外加一次实时的 `os.environ` 导出。响应是写入后的**就绪状态行**，
  绝不是值本身。
- **在表单中，** secret 控件展示一个名称选择器（默认取自模型目录中当前
  provider 的环境变量键）、一个 `configured` / `not configured` 徽章、一个
  密码输入框，以及一条常驻说明：*「Write-only: the value is sent to the
  server and can never be read back here.」* PUT 一旦完成，输入框立即被清空。

**值实际去了哪里。** 两个地方，这里值得说精确：

1. **仓库根目录的 `.env`**（`{ARI}/.env`）。那是一个*固定的*写入目标 ——
   写入器就地替换匹配的 `NAME=` 行，不存在时追加。它**不**遵循就绪
   状态链，也不会写进当前检查点。
2. **正在运行的服务器的 `os.environ`**，实时导出。

该值绝不会被写入 `project_config.json`、run 模板、run 草稿、已解析清单或
任何日志。

由于 GUI 启动从 `os.environ` 出发，而只让 `.env` 文件填补空缺，因此你刚设置
的 secret 会立即对下一次从 GUI 启动的运行生效。

需要知道的唯一不对称之处：**就绪状态读的是一条链，而写入只针对一个文件。**
这条链是当前检查点 `.env`（`project_env`）→ 仓库 `.env`（`repo_env`）→
`~/.env`（`user_env`）→ 进程环境（`process_env`）。所以，如果某个检查点本地
的 `.env` 已经定义了同名变量，即便你写入了新值，就绪状态仍会继续报告
`project_env` 为胜出来源。`source_class` 徽章告诉你的是胜出的*磁盘上*定义
位于何处 —— 而不是你上一次写入落到了哪里。如果这不是你想要的，请编辑或删除
检查点本地的那份定义，尤其是在 GUI 进程之外运行 CLI 之前。

## 启动流程

启动面板只在**草稿 scope** 下出现（`#/studio?draft=<id>`）。它的步骤条是
Goal → Review → Launch。

### 1. 解析并校验

**[Resolve & validate]** 会为该草稿发出两个调用（带可选的执行环境 profile
`laptop` / `hpc` / `cloud`）：

- `POST /api/v1/run-drafts/{draft_id}/resolve-config` —— 新运行的预览清单；
- `POST /api/v1/run-drafts/{draft_id}/validate` —— `{valid, errors, warnings}`。

随后面板渲染：**Changed vs defaults**（每一个溯源不是捆绑默认层的叶子，使用
与 Config 浏览器相同的徽章映射，因此两个接口面不会漂移）、可归因于草稿的
校验错误、逐字呈现的解析器警告、secret 就绪状态行，以及治理为只读的说明。

被拒绝的覆盖绝不会被静默丢弃。当某一层提供了 pydantic 拒绝的值时，解析器会
回退到最后一个有效层，用一条 `rejected_override` 解释注释该叶子的溯源，并
发出形如 *「`<layer>` override rejected for `<path>`: … —— keeping the
`<layer>` value」* 的警告。

`ari.mode` / `rqgm.enabled`（或 `paper.mode` / `rqgm.paper.enabled`）的互锁
不匹配在*解析器*内部走的是同一条路径 —— 告警并回退，清单展示**生效**模式 ——
但它不会停留在告警。`/validate` 会把那条残留告警转成 `interlock_mismatch`
错误，启动随即拒绝，而不是悄悄启动那次回退后的运行。这正是用来捕获 Studio
自身无法破坏的那种配对的机制：例如草稿请求 `ari_rqgm`，而服务器环境中带有
`ARI_RQGM_ENABLED=0`。

### 2. 不可变的复核

复核区块是一个只读摘要 —— 显示名、run id 意图（*在 accept 时由服务器签发，
绝不从检查点猜测*）、profile、**解析后的**执行模式与论文模式、被更改的字段数、
配置摘要 —— 藏在一个显式的勾选框之后：

> I reviewed this immutable summary — launch exactly this configuration.

勾选该框会铸造**恰好一个幂等键**（一个 `crypto.randomUUID()`），它就是「这次
批准」的单位。任何使该复核失效的操作 —— 编辑并保存草稿（修订号增加）、切换
草稿、更改 profile 或显示名 —— 都会同时清除批准与该键。一次新的批准就是一次
新的意图。

该摘要中的模式行取自预览清单的**解析后**取值，绝不是原始选择。当某个被请求的
模式未被采纳时，会有一个单独的 *「Requested mode was not applied」* 面板逐字
列出请求值、解析值以及解析器的告警 —— 因此绝不会在误以为某次运行受治理的情况
下把它启动起来。

只有当草稿校验干净、**且**草稿有 goal、**且**复核已确认时，**[Launch run]**
才会被启用。

### 3. 启动，以及它保证了什么

`POST /api/v1/runs`（携带 `{draft_id, display_name?, profile?,
idempotency_key?}`）严格按此顺序执行：

1. **幂等重放检查。** 磁盘上已存在的键会短路返回已记录的 `run_id` 并带
   `idempotent_replay: true` —— 什么都不会被拉起。
2. **校验优先。** 解析器预览 + 共享的草稿校验 + 两项仅启动时的检查。失败
   返回 `400` 与逐路径的 `details.errors` —— **并且不执行任何文件系统变更。**
   没有检查点目录、没有 `experiment.md`、没有需要清理的半成品运行。校验失败
   是真正的空操作。
3. **服务器铸造身份。** `run_id = <UTC YYYYMMDDHHMMSS>_<slug>-<6 hex>`。
   slug 仅用于显示且是确定性的 —— 在响应之前不会发生任何 LLM 调用或调度器
   探测。
4. **幂等占位。** 仅创建的 `gui_store/launches/{key}.json` 写入发生在**任何
   目录存在之前**，因此两个使用同一个键并发竞争的 POST 仍然只会拉起一个
   子进程。
5. **先物化，再拉起。** `experiment.md`（来自 goal）、`workflow.yaml`
   （对捆绑文件的写时复制种子 —— 并在选择了非默认模式时附加最小化的
   `ari:` / `rqgm:` / `paper:` 块）、`launch_config.json`、
   `resolved_config.json`（被解析的清单在启动时成为现实），以及
   `launch_events.jsonl`（`draft → validating → accepted → spawned`；拉起
   失败会记录 `failed` 并释放占位）。然后是 legacy 启动所使用的同一个
   `python3 -m ari.cli run …` 子进程，并固定 `ARI_CHECKPOINT_DIR`（仅当选择了
   非默认模式时才附带那四个 `ARI_*` 模式变量）。
6. **先响应，再跳转。** `{run_id, status_url, checkpoint_path, accepted,
   idempotent_replay}` —— 响应绝不等待子进程。UI 导航到规范的
   `#/overview?run=<run_id>`；它使用服务器签发的 id，绝不按 mtime 去猜最新的
   检查点。

一次启动**不会**切换全局活动检查点，这是有意的。

**双击安全。** 按钮在请求进行中会被禁用，而一个帧内 ref 守卫会拦截第二次
发送；启动失败后的重试复用**同一个**键，因此重试只可能是重放 —— 绝不会拉起
第二个运行。

legacy 的 `POST /api/launch` 未作变更，仍并行运行；legacy 向导（`#/new`）
仍在使用它。

## 执行模式：可选择；治理调优：仍仅限文件

自 **ADR-09** 起，Studio 的 *Execution* 分区不再是一个被整体禁用的分组。它提供
**恰好两个**控件 —— 每个正交意图一个 —— 其余一切保持只读：

| 控件 | 它写入的配置键 | 取值 |
|---|---|---|
| **Execution mode** | `ari.mode` **与** `rqgm.enabled` | `simple_bfts`（默认）/ `ari_rqgm` |
| **Paper mode** | `paper.mode` **与** `rqgm.paper.enabled` | `linear`（默认）/ `rqgm_archive` |

**每个控件都会写入其配对的两个键。** 模式与其互锁是一个意图，因此一次选择产生
一次同时携带两个键的 PATCH —— GUI 无法构造出那种会让运行时静默降级的半边文档。
若某个文档最终只有一半而没有另一半（手工构造的 API 调用，或只覆盖了模板配对中
一个键的草稿），服务器会在模板 create/PATCH、草稿 create/PATCH **以及**启动时以
带类型的 400 `mode_interlock_mismatch` 拒绝它。该检查作用于*合并后*的文档取值，
因此一次最终归于一致的两步编辑是可以的。

**仅限新建运行。** 两个叶子都是 `mutability: new_run_only` —— 该选择作用于你即将
启动的那次运行。恢复不受影响：被恢复的运行采用 `{checkpoint}/rqgm_state.json`
中记录的模式，它优先于配置与环境变量，且运行的模式在整个运行期间保持不变。
Studio 中没有任何东西可以改指一个已经存在的运行。

**project 作用域依然拒绝它们。** 这四个叶子是 `scope: run`，因此项目默认值文档
会以 `not_project_scope` 拒绝它们；在该作用域下这两个下拉被禁用并说明原因。请在
运行模板或运行草稿上选择模式。

**其余 104 个治理叶子保持只读。** `Execution mode` 分类与 `rqgm.*` 树中的其他每
一条路径（epoch、kernel、governance、adversarial、预算、论文归档调优）都渲染在
一个折叠的只读分组中 —— **连同其生效值** —— 这样你能准确看到将会生效的内容，
分组下附有这条说明：

> **RQGM governance parameters (read-only)** — Effective values shown for
> reference. Governance tuning parameters come from configuration files in
> this release — they are not editable from the GUI; edit `workflow.yaml` to
> change them. Selecting a mode above is not a governance mutation.

这道锁是端到端的，不是装饰性的：启动端点会从注册表重新计算锁定集合
（`Execution mode` 分类 ∪ `rqgm.*` **减去**那四个可选择的叶子 —— 今天是 104 条
路径），并以 `mode_locked` 为理由拒绝那些自身 `values` 携带其中任一条的草稿。
启动时的 `ARI_*` 环境变量转换同样在结构上排除了每一条被锁定的路径，因此从 run
模板继承来的值也无法抵达子进程。

**非默认的选择会对检查点做什么。** 启动会把最小化的 `ari:` / `rqgm:` / `paper:`
块写入该运行自身的 `workflow.yaml` 副本（绝不写入捆绑文件），*并且*把
`ARI_MODE`、`ARI_RQGM_ENABLED`、`ARI_PAPER_MODE`、`ARI_RQGM_PAPER_ENABLED`
导出给子进程，于是检查点自我描述，后续每个阶段都与环境一致。保持默认则
**什么都不写、什么都不导出**：一次 `simple_bfts` + `linear` 的启动与 ADR-09
之前逐字节相同，包括你显式重新选中默认取值的情形。

你仍然可以用 CLI 的方式来做，而那依旧是权威说明：

```yaml
# workflow.yaml
ari:
  mode: ari_rqgm      # master switch
rqgm:
  enabled: true       # redundant interlock — both keys must agree
```

或者在环境中设置 `ARI_MODE=ari_rqgm` / `ARI_RQGM_ENABLED=1`。完整语义 ——
互锁表、`mode_source`、resume 调和，以及独立的 `paper.mode` 轴 —— 见
[执行模式](execution_modes.md)。

## 另请参阅

- [仪表盘指南](dashboard.md) —— 启动服务器、工作区地图、深链。
- [执行模式](execution_modes.md) —— 启用 `ari_rqgm` 与论文模式。
- [RQGM 治理工作区](rqgm_gui.md) —— 阅读一次受治理的运行。
- [配置参考](../reference/configuration.md) —— 配置文件接口面。
- [环境变量](../reference/environment_variables.md)。
- [远程访问](remote_access.md) —— localhost 之外配置/secret 端点的认证。
