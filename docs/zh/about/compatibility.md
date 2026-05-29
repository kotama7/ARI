---
sources:
  - path: ari-core/pyproject.toml
    role: config
  - path: setup.sh
    role: doc
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
last_verified: 2026-05-26
---

# 兼容性与支持

ARI 在哪些环境上运行。关于版本相关的*策略*（SemVer、支持窗口、
弃用），参见[发布与版本策略](release_policy.md)。

## Python

| | 版本 |
|---|---|
| 硬性要求 | **Python ≥ 3.9**（`ari-core/pyproject.toml` 中的 `requires-python`） |
| 推荐 | **3.10+**（[快速开始](../getting-started/quickstart.md)以 3.10 或更高为目标） |

`setup.sh` 会检查解释器并安装其余组件。请以普通用户身份运行它 ——
切勿使用 `sudo`。

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

其实时行为针对 **Letta 0.16.7** 进行了验证（参见[记忆架构](../concepts/memory.md)中的
实现说明）。可用 `ari memory health` 检查正在运行的后端。每个检查点还会携带一份
`memory_backup.jsonl.gz` 快照，因此即便跨 Letta 版本，运行也能保持可移植。

## LLM 后端

模型路由经由 LiteLLM，因此任何兼容 OpenAI 的提供商均可使用。
通过 `ARI_BACKEND` / `ARI_MODEL` 选择（始终带上提供商前缀，例如
`openai/gpt-4o`）。

| 后端 | `ARI_BACKEND` | 备注 |
|---|---|---|
| Ollama | `ollama` | 本地、免费、无需 API 密钥（入门默认） |
| OpenAI | `openai` | 云端、付费；`OPENAI_API_KEY` |
| Anthropic | `claude` | 云端、付费；`ANTHROPIC_API_KEY` |
| 任意兼容 OpenAI 的接口 | （自定义） | 经由 LiteLLM 路由 |

支持按阶段覆盖模型（例如用更便宜的模型做想法生成，用更强的模型做论文写作）
—— 参见[配置](../reference/configuration.md)和
[环境变量](../reference/environment_variables.md)。

## Skill 与 core

Skill 独立于 `ari-core` 进行版本控制。处于 `0.7.x` 的 skill 可与任意
`ari-core` `0.7.y` 兼容（同一 minor 内兼容）；跨 minor 版本时，需协调发布。
参见[发布策略 → 兼容性窗口](release_policy.md#compatibility-windows)。

---

另见：[发布策略](release_policy.md) · [关于](index.md) ·
[快速开始](../getting-started/quickstart.md) ·
[环境变量](../reference/environment_variables.md)
