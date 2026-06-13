---
sources:
  - path: ari-core/ari/public
    role: implementation
  - path: ari-core/tests/test_public_api_boundary.py
    role: test
last_verified: 2026-06-10
---

# `ari.public` — 面向技能的稳定 API

`ari.public` 是 `ari-skill-*` 包**唯一**可以依赖的模块接口。其外部的所有内容均为内部实现，可能在不通知的情况下发生变更。该包是对应 `ari.<module>` 私有实现之上的薄重导出层，使核心可以自由重构，同时保持面向技能的合约不变。它在 v0.7.1（v0.7+ 重构的第 4 阶段）中引入，并由 `ari-core/tests/test_public_api_boundary.py` 强制执行。

## 子模块

| 子模块 | 重导出内容 | 使用它的技能 |
|---|---|---|
| `ari.public.config_schema` | Pydantic 配置模型（`ARIConfig`、`LLMConfig` 等） | 需要类型化设置的调用方 |
| `ari.public.container` | 容器运行时辅助函数（`ContainerConfig`、`run_in_container` 等） | `ari-skill-coding`（测试） |
| `ari.public.cost_tracker` | LLM 成本记录（`bootstrap_skill`、`record` 等） | `ari-skill-plot`（LLM 调用成本） |
| `ari.public.llm` | `LLMClient`（带成本集成的 LiteLLM 封装） | 偏好使用 ARI 封装的调用方 |
| `ari.public.paths` | `PathManager`（检查点路径解析器） | 需要作用域路径的调用方 |
| `ari.public.claim_gate` | 确定性主张-证据硬门控（`run_hard_gate`）＋ 概念→不变量注册表（`classify_concept`、`scan_science_data`、`CONCEPT_INVARIANTS`） | `ari-skill-evaluator`、`ari-skill-transform` |
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
