---
sources:
  - path: ari-core/ari/public
    role: implementation
  - path: ari-core/tests/test_public_api_boundary.py
    role: test
  - path: ari-core/ari/result.py
    role: implementation
  - path: ari-core/ari/call_context.py
    role: implementation
  - path: ari-core/ari/skill_lock.py
    role: implementation
  - path: ari-core/ari/skill_manifest.py
    role: implementation
last_verified: 2026-08-02
---

# `ari.public` — 面向技能的稳定 API

`ari.public` 是 `ari-skill-*` 包**唯一**可以依赖的模块接口。其外部的所有内容均为内部实现，可能在不通知的情况下发生变更。该包是对应 `ari.<module>` 私有实现之上的薄重导出层，使核心可以自由重构，同时保持面向技能的合约不变。它在 v0.7.1（v0.7+ 重构的第 4 阶段）中引入，并由 `ari-core/tests/test_public_api_boundary.py` 强制执行。

## 子模块

| 子模块 | 重导出内容 | 使用它的技能 |
|---|---|---|
| `ari.public.clone` | 经 digest 验证的 EAR bundle 获取与安全解包（`clone`、`CloneResult`、`CloneError`） | reproduction / bundle consumer 技能 |
| `ari.public.config_schema` | Pydantic 配置模型（`ARIConfig`、`LLMConfig` 等） | 需要类型化设置的调用方 |
| `ari.public.container` | 容器运行时辅助函数（`ContainerConfig`、`run_in_container` 等） | `ari-skill-coding`（测试） |
| `ari.public.execution` | 封闭 workspace、有界 execution/result、完整日志 artifact、`MeasurementSetV1` | 执行 producer 与测量 consumer 技能 |
| `ari.public.evaluation` | 不可变指标准入、`GateReportV1`、语义评审及保守迁移读取器 | idea、transform、evaluator、paper及离线读取器 |
| `ari.public.cost_tracker` | LLM 成本记录（`bootstrap_skill`、`record` 等） | `ari-skill-plot`（LLM 调用成本） |
| `ari.public.llm` | `LLMClient`（带成本集成的 LiteLLM 封装） | 偏好使用 ARI 封装的调用方 |
| `ari.public.paths` | `PathManager`（检查点路径解析器） | 需要作用域路径的调用方 |
| `ari.public.node_selection` | 确定性的 downstream node/source 选择 | `ari-skill-transform` |
| `ari.public.publish` | staged EAR publish/promote 契约 | `ari-skill-transform` |
| `ari.public.run_env` | run 环境捕获与 shell export 辅助函数 | sandbox / executor 技能 |
| `ari.public.call_context` | `RunContextV1`、`NodeContextV1`、签名 tool-context 验证辅助函数 | 控制平面与 context-aware 技能 |
| `ari.public.result` | `ResultEnvelopeV1`、内容寻址工件引用、类型化错误、调用来源 | 技能适配器与联邦 dispatch 调用方 |
| `ari.public.skill_lock` | `SkillsLockV1`、锁定 provider/tool 记录、原子 create-or-verify | run launcher、federation adapter、replay 工具 |
| `ari.public.skill_manifest` | 版本化技能清单模型、loader、digest 与安全 entrypoint resolver | 内置 / 联邦 MCP 技能 |
| `ari.public.claim_gate` | 确定性硬门入口、evaluation契约及概念→不变量注册表 | `ari-skill-evaluator`、`ari-skill-transform` |
| `ari.public.verified_context` | 已验证上下文辅助函数（`render_grounded_block`、`write_verified_context`、`build_verified_context`） | `ari-skill-paper` |

## `ari.public.config_schema`

从 `ari.config` 重导出 Pydantic 模型：

```python
from ari.public.config_schema import (
    ARIConfig,
    BFTSConfig,
    CheckpointConfig,
    EvaluatorConfig,
    LLMConfig,
    LoggingConfig,
    SkillConfig,
)

cfg = ARIConfig.model_validate(yaml.safe_load(open("ari.yaml")))
```

导出的名称与 `ari/config.py` 符号一一对应；当前字段结构请参阅该文件。来源：`ari-core/ari/public/config_schema.py`。

## `ari.public.container`

从 `ari.container` 重导出容器运行时：

| 符号 | 用途 |
|---|---|
| `ContainerConfig` | 数据类：`mode`、`image`、`bind_paths`、`gpu` 等 |
| `detect_runtime()` | 基于 `which` 查找返回 `"singularity"` / `"apptainer"` / `"docker"` / `"none"` |
| `config_from_env()` | 从 `ARI_CONTAINER_*` 环境变量构建 `ContainerConfig`（未设置时返回 `None`） |
| `pull_image(cfg)` | 拉取 / 构建 `cfg` 引用的镜像 |
| `run_in_container(cfg, cmd, ...)` | 在容器内运行进程，返回退出码 + 捕获的流 |
| `run_shell_in_container(cfg, script, ...)` | 同上，但接受 bash 脚本字符串 |
| `list_images()` | 当前运行时中可用镜像的清单 |
| `get_container_info()` | 包含运行时 + 镜像健康状态的诊断字典 |

来源：`ari-core/ari/container.py` → `ari-core/ari/public/container.py`。

## `ari.public.cost_tracker`

从 `ari.cost_tracker` 重导出 LLM 成本追踪器：

| 符号 | 用途 |
|---|---|
| `CostTracker` | 写入 `cost_log.jsonl` 的聚合器实例 |
| `CallRecord` | 每次调用的数据类（`model`、`prompt_tokens`、`completion_tokens`、`cost_usd`、`metadata`） |
| `init(log_dir)` | 初始化以 `log_dir` 为根目录的全局追踪器 |
| `init_from_env()` | 自动使用 `ARI_CHECKPOINT_DIR` 进行初始化（大多数调用方使用此方式） |
| `bootstrap_skill(skill_name, phase=None)` | 技能便捷封装 — 初始化并标记每条记录 |
| `record(**kwargs)` | 追加手动 `CallRecord`（不通过 LiteLLM 回调时使用） |
| `set_default_metadata(**kwargs)` | 为后续所有记录附加额外元数据标签 |
| `get()` | 获取当前追踪器（或 `None`） |

技能通常只需在启动时调用 `bootstrap_skill`；其余由 LiteLLM 回调处理。来源：`ari-core/ari/cost_tracker.py` → `ari-core/ari/public/cost_tracker.py`。

## `ari.public.llm`

从 `ari.llm.client` 重导出 `LLMClient`：

```python
from ari.public.llm import LLMClient

client = LLMClient(model="ollama/qwen3:32b")
resp = await client.complete([{"role": "user", "content": "..."}])
```

请优先使用此方式而非直接调用 LiteLLM — `LLMClient` 会透传 ARI 的成本追踪器和元数据标签。来源：`ari-core/ari/llm/client.py` → `ari-core/ari/public/llm.py`。

## `ari.public.paths`

从 `ari.paths` 重导出 `PathManager`：

```python
from ari.public.paths import PathManager

paths = PathManager.from_env()        # honours ARI_CHECKPOINT_DIR
nodes_json = paths.checkpoint / "nodes_tree.json"
```

`PathManager` 是核心解析器 — 技能中绝不要直接读取 `ARI_CHECKPOINT_DIR`。来源：`ari-core/ari/paths.py` → `ari-core/ari/public/paths.py`。

## `ari.public.skill_manifest`

`skill.yaml` 是规范 package contract。consumer 通过公共 API 读取它，而不是直接
解析 YAML 或扫描 `server.py`：

```python
from ari.public.skill_manifest import load_skill_manifest, manifest_digest

manifest = load_skill_manifest("ari-skill-coding/skill.yaml")
tool = manifest.tool("run_code")
identity = manifest_digest(manifest)
```

`SkillManifestV1` 验证 package identity、package-relative Python stdio entrypoint、
完整的普通环境声明、互不重叠的 credential scope、唯一 tool 名、
capability reference、phase、side effect、determinism、timeout class、permission 与
result schema。`TimeoutBudgetV1` 显式声明并限制调用方控制的 timeout 参数；
`timeout_class=async` 的 tool 必须通过 `AsyncLifecycleV1` 声明 status/result/cancel
semantic capability，未解析或有歧义的引用会使 manifest validation 失败。
内置 production 技能必须使用 `environment_policy=complete`。
每个已解析 tool 还以 `none` / `run` / `node` 声明 `context_requirement`；
调用方未提供对应结构化上下文时，dispatch 会 fail closed。公开 runtime loader
始终拒绝未版本化的 legacy manifest。离线迁移可使用内部只读转换器
`ari.migrations.skill_manifest.load_legacy_skill_manifest()`；转换结果默认禁用，
不会被隐式 admission。

## `ari.public.call_context` 与 `ari.public.result`

新 dispatch 代码使用类型化 result contract；历史字典 API 作为无损兼容投影保留：

```python
from ari.public.call_context import ToolCallContextV1

tool = client.list_tools()[0]
envelope = client.call_tool_envelope(
    tool["tool_ref"],
    {"query": "example"},
    context=ToolCallContextV1.for_node(
        run_id="run-1",
        node_id="node-1",
        parent_node_id="root",
        ancestor_node_ids=["root"],
        phase="bfts",
    ),
)
```

`RunContextV1` 将 logical run 绑定到 `run_scope_digest`；`NodeContextV1` 将 self、
parent 以及 root 到 parent 的有序 chain 绑定到 `lineage_digest`。
`MCPClient` 将它转换为 tool-bound、per-connection HMAC capability，技能通过
`verify_tool_context` 验证。签名密钥由 transport 拥有，不属于公共数据 contract。
规范 schema 为 `ari-core/ari/schemas/call_context_v1.schema.json`。

`ResultEnvelopeV1` 记录 status、structured content、类型化 error、不可变
`tool_ref`、run/node/phase context、selection reason、timing 与 SHA-256 response digest。
credential 只记录 scope ID，不记录值。超过 4,000 字符的 raw content 会被
外置到内容寻址工件，`materialize_content(store)` 验证 digest 与 byte size 后恢复。

异步 submit 会附加 `AsyncToolHandleV1`，其中 lifecycle endpoint 是从已审查 manifest
capability 解析出的不可变 `tool_ref`。序列化后的 handle 可直接传给
`MCPClient.get_async_status()`、`get_async_result()`、`cancel_async()` 或
`wait_for_async()`，无需 bare-name lookup。规范 schema 为
`ari-core/ari/schemas/async_tool_handle_v1.schema.json`。

## `ari.public.skill_lock`

`SKILLS.lock` 是 live MCP handshake 后创建的确定性 checkpoint-level snapshot。
`SkillsLockV1` 将 canonical manifest 与精确的 live input/output schema 及逐 phase
admitted `tool_ref` 集合绑定。`write_or_verify_skills_lock()` 原子创建首个 snapshot，
此后要求 byte-equivalent semantics。drift 和 corruption 分别以
`SkillLockMismatchError` / `SkillLockCorruptError` 报告。`LockedCredentialScopeV1`
只记录 scope identity 与已声明/存在的环境名，不包含 credential 值。

## `ari.public.claim_gate`

从 `ari.pipeline.claim_gate` 重导出确定性主张-证据硬门控及其概念→不变量注册表：

| 符号 | 用途 |
|---|---|
| `run_hard_gate` | 门控入口点 —— 阻止其证据未通过确定性检查的主张 |
| `classify_concept` | 将概念映射到其通用不变量族 |
| `scan_science_data` | 对照已注册的不变量扫描科学数据 |
| `CONCEPT_INVARIANTS` | 领域通用的概念→不变量注册表（单一可信来源） |

```python
from ari.public.claim_gate import run_hard_gate
```

`ari-skill-evaluator` 和 `ari-skill-transform` 通过这个稳定的公共接口到达门控，而非私有的 `ari.pipeline.claim_gate` 路径，因此两个技能复用门控所阻断的**同一套**通用不变量逻辑 —— 不存在重复的领域计算。来源：`ari-core/ari/pipeline/claim_gate/` → `ari-core/ari/public/claim_gate.py`。

## `ari.public.verified_context`

从 `ari.pipeline.verified_context` 重导出已验证上下文辅助函数：

| 符号 | 用途 |
|---|---|
| `render_grounded_block` | 渲染一个有依据的（由引用支撑的）上下文块 |
| `write_verified_context` | 为构建该制品的调用方写出已验证上下文制品 |
| `build_verified_context` | 构建已验证上下文结构 |

```python
from ari.public.verified_context import render_grounded_block
```

`ari-skill-paper` 通过这个稳定的公共接口到达这些辅助函数，而非私有的 `ari.pipeline.verified_context` 路径。来源：`ari-core/ari/pipeline/verified_context.py` → `ari-core/ari/public/verified_context.py`。

## 综合示例 —— 一个最小技能

一个只使用 `ari.public.*` 的技能：引导成本追踪、解析检查点作用域的路径，并发起一次带成本追踪的 LLM 调用。

```python
from ari.public import cost_tracker
from ari.public.paths import PathManager
from ari.public.llm import LLMClient

# 1. 为该技能发起的每次 LLM 调用打标签（读取 ARI_CHECKPOINT_DIR）。
cost_tracker.bootstrap_skill("ari-skill-example", phase="bfts")

# 2. 通过 PathManager 解析路径 —— 切勿直接读取 ARI_CHECKPOINT_DIR。
paths = PathManager.from_env()
nodes_json = paths.checkpoint / "nodes_tree.json"

# 3. LLM 调用走 ARI 的封装，因此成本会被自动记录。
client = LLMClient(model="ollama/qwen3:32b")
resp = await client.complete([{"role": "user", "content": "Summarise: ..."}])
```

该调用的 token 数与美元成本会带着技能名和阶段标签写入检查点的 `cost_trace.jsonl` —— 无需手动调用 `record()`。

## 稳定性保证

- **MAJOR（SemVer）** — 符号、签名和行为可能发生破坏性变更。
- **MINOR** — 新增符号；现有符号以向后兼容的方式扩展（允许新增可选 kwargs）。
- **PATCH** — 仅修复 bug。

通过 `from ari import <X>` 直接导入（而非 `from ari.public import <X>`）会绕过此合约 — 技能作者应对照 `ari/public/__init__.py` 检查其导入，并将内部导入边界移至公共层。

## 另请参阅

- `ari-core/ari/public/__init__.py` — 包含规范子模块列表的模块级文档字符串。
- `docs/guides/extension_guide.md` — 如何编写仅依赖 `ari.public` 的新技能。
- `CONTRIBUTING.md::Software-engineering discipline §3` — 公共 API 规则（技能只能访问 `ari.public.*`）。
- `docs/_archive/refactor_audit.md`（§4）— 第 4 阶段的历史清单。
