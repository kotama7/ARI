---
sources:
  - path: CONTRIBUTING.md
    role: doc
  - path: CHANGELOG.md
    role: doc
last_verified: 2026-05-26
---

# 关于 ARI

项目元信息 —— 管理整个项目的策略与参考资料，而非任何单一功能。

## 策略与参考

| 文档 | 涵盖内容 |
|---|---|
| [发布与版本策略](release_policy.md) | SemVer 解释、公共表面、支持窗口、弃用生命周期，以及发布检查清单（含文档门控）。 |
| [兼容性与支持](compatibility.md) | 受支持的 Python、Letta 记忆后端，以及 LLM 后端。 |
| [贡献指南](../../../CONTRIBUTING.md) | 软件工程规范、分层架构、公共 API 规则，以及弃用流程。 |
| [更新日志](../../../CHANGELOG.md) | 各版本发布说明（Added / Changed / Fixed / Deprecated / Removed / Security）。 |
| [安全策略](../../../SECURITY.md) | 如何报告漏洞，以及哪些版本会收到修复。 |

## 许可

ARI 不附带单一的仓库级许可证文件；许可是**按已发布制品**进行的。当你发布一个实验制品仓库
（EAR）时，其 `ear/publish.yaml` 会声明一个 SPDX `license`（MIT / Apache-2.0 /
BSD-3-Clause / GPL-3.0 / CC-BY-4.0），并由 `generate_ear` 将匹配的
`LICENSE` 文件写入 bundle。参见
[配置 → EAR 策展](../reference/configuration.md#ear-curation-earpublishyaml--v070)。

---

另见：[文档索引](../../README.md) ·
[发布策略](release_policy.md) · [兼容性](compatibility.md)
