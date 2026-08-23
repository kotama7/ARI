---
sources:
  - path: ari-core/pyproject.toml
    role: config
  - path: setup.sh
    role: doc
  - path: scripts/setup/detect_env.sh
    role: config
  - path: scripts/setup/install_letta.sh
    role: config
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
  - path: ari-core/ari/llm/routing.py
    role: implementation
  - path: ari-core/ari/llm/client.py
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
last_verified: 2026-08-16
---

# 兼容性与支持

ARI 在哪些环境上运行。关于版本相关的*策略*（SemVer、支持窗口、
弃用），参见[发布与版本策略](release_policy.md)。

## Python

| | 版本 |
|---|---|
| 包元数据 | **Python ≥ 3.9**（`ari-core/pyproject.toml` 中的 `requires-python`） |
| `setup.sh` 实际接受的 | **Python ≥ 3.10** —— `scripts/setup/detect_env.sh` 对更旧的版本发出警告，并在没有任何解释器达到 3.10 时 `exit 1` |

两者并不一致：`pip install` 会接受 3.9，而安装脚本不会。请把 **3.10**
当作真正的下限 —— 若干依赖（`mcp>=1.1`）要求它。

`setup.sh` 会检查解释器、在仓库根目录创建 `.venv`，并安装其余组件。
请以普通用户身份运行它 —— 切勿使用 `sudo`。

## 操作系统

| 操作系统 | 状态 |
|---|---|
| Linux | 支持 |
| macOS | 支持 |
| Windows | 通过 WSL2 |

## 记忆后端（Letta）

自 v0.6.0 起，ARI 的记忆由 [Letta](https://docs.letta.com)（前身为 MemGPT）
提供支持。`setup.sh` 会引导其启动，并自动检测最佳部署方式：
Docker → Singularity/Apptainer → pip（用 `SKIP_LETTA_SETUP=1` 可跳过）。
当设置了 `SLURM_CLUSTER_NAME` 或 `SLURM_JOB_ID` 时，即使 Docker 守护进程可用也会
被直接跳过，因此在作业分配内部执行 setup 会落到 Singularity/Apptainer 上。

其实时行为针对 **Letta 0.16.7** 进行了验证（参见[记忆架构](../concepts/memory.md)中的
实现说明）。可用 `ari memory health` 检查正在运行的后端。每个检查点还会携带一份
`memory_backup.v1.json.gz` 快照，因此即便跨 Letta 版本，运行也能保持可移植。

## LLM 后端

模型路由经由 LiteLLM，因此任何兼容 OpenAI 的提供商均可使用。
通过 `ARI_BACKEND` / `ARI_MODEL` 选择。你不必自己写出提供商前缀：
`resolve_litellm_model` 会从 `ARI_BACKEND` 推导它（`ollama` → `ollama_chat/…`、
`claude`/`anthropic` → `anthropic/…`、`cli-shim` → `openai/…`，而 `openai`
以及任何未知值 → 原样不变）；已经带有已知前缀的 model id 会被原样透传。

| 后端 | `ARI_BACKEND` | 备注 |
|---|---|---|
| Ollama | `ollama` | 本地、免费、无需 API 密钥（入门默认） |
| OpenAI | `openai` | 云端、付费；`OPENAI_API_KEY` |
| Anthropic | `claude` | 云端、付费；`ANTHROPIC_API_KEY` |
| Claude Code CLI | `claude_code` | 智能体循环上**不**经 LiteLLM 路由 —— `LLMClient` 直接分派到 `ari/llm/claude_code/`，且该路径不支持工具调用（显式报错失败）。直接解析 `ARI_BACKEND` 的 MCP 技能仍走普通 Anthropic API，需要 `ANTHROPIC_API_KEY`。 |
| 任意兼容 OpenAI 的接口 | （自定义） | 经由 LiteLLM 路由 |

支持按阶段覆盖模型（例如用更便宜的模型做想法生成，用更强的模型做论文写作）
—— 参见[配置](../reference/configuration.md)和
[环境变量](../reference/environment_variables.md)。

## Skill 与 core

Skill 独立于 `ari-core` 进行版本控制，且其编号并不跟随 core：`ari-core` 目前是
`0.9.1`，而随附的各 skill 版本跨越 `0.1.0` 到 `2.0.0`。没有任何代码强制某个
skill↔core 的版本配对，因此请按协调发布来搭配，而不是按数字对齐。
参见[发布策略 → 兼容性窗口](release_policy.md#兼容性窗口)。

---

另见：[发布策略](release_policy.md) · [关于](index.md) ·
[快速开始](../getting-started/quickstart.md) ·
[环境变量](../reference/environment_variables.md)
