---
sources:
  - path: CHANGELOG.md
    role: doc
  - path: CONTRIBUTING.md
    role: doc
  - path: ari-core/pyproject.toml
    role: config
last_verified: 2026-05-26
---

# 发布与版本策略

## 语义化版本解释

ARI 遵循 [语义化版本 2.0](https://semver.org/spec/v2.0.0.html)。

| 升级类型 | 变更内容 | 示例 |
|---|---|---|
| **MAJOR**（1.0 → 2.0）| 对**公共**接口的不向后兼容变更 | `ari.public.*` 符号被移除、MCP 工具语义变更、检查点格式破坏性变更 |
| **MINOR**（0.6 → 0.7）| 向后兼容的功能新增 | 新增 `ari.public.*` 符号、新增 MCP 工具、新增 `ari` 子命令、新增带安全默认值的环境变量 |
| **PATCH**（0.7.0 → 0.7.1）| 缺陷修复、文档更新、不影响 API 表面的内部重构 | LLM 提示词调整（不改变工具 I/O）、仪表盘 CSS、依赖版本升级 |

**公共表面**（SemVer 适用范围）：

- CLI（`ari ...`）—— 每个已记录的子命令和标志。
- `ari.public.*` Python 导入。
- 每个 skill 的 `mcp.json` 工具列表、名称及请求/响应结构。
- viz REST API（`/api/` 下的所有内容）。
- 已记录的检查点文件（`tree.json`、`nodes_tree.json`、
  `node_report.json`、`settings.json`、`workflow.yaml`、
  `experiment.md`、`manifest.lock`、`publish_record.json`、
  `lineage_decisions.jsonl`）。
- 已记录的环境变量（列于
  `docs/reference/environment_variables.md`）。

**不属于**公共表面：

- `ari.public.*` 以外的模块。
- 仅供内部使用的辅助函数（以 `_` 开头的名称）。
- 测试 fixture 和 `vendor/` 快照（PaperBench、VirSci 等）。
- `ari/prompts/` 下的提示词字符串（受 Phase PC 约束，但不受
  SemVer 保护 —— 只要工具 I/O 契约不变，可在任何 minor 版本中修改）。

## 支持策略

| 分支 | 状态 | 向后移植内容 |
|---|---|---|
| `main`（最新 minor） | 积极维护 | 功能 + 缺陷修复 |
| 上一个 minor | 在下一个 minor 发布后维护 **6 个月** | 仅安全 + 严重缺陷修复 |
| 更早的 minor | 已停止支持 | 无 |

当前状态记录在 `CHANGELOG.md` 及
[GitHub releases](https://github.com/) 页面。

## 弃用与移除

*弃用*是关于某个公共符号或行为将被移除的通知。我们遵循以下生命周期：

1. **公告** —— 发布说明 + `CHANGELOG.md` 标记该变更。
2. **警告** —— 运行时至少在一个 minor 版本中发出 `DeprecationWarning`。
3. **移除** —— 下一个 MAJOR 版本去掉警告并删除相关代码。

目前正在进行中的示例（完整计划见
`CONTRIBUTING.md::Deprecation process`）：

| 条目 | 公告时间 | 警告起始版本 | 计划移除版本 |
|---|---|---|---|
| `$HOME/.ari/registries.yaml` 回退 | v0.5.0 | v0.7.1 | v1.0 |
| `$HOME/.ari/registry-data` 回退 | v0.5.0 | v0.7.1 | v1.0 |
| 旧版 v0.5 JSONL 内存存储 | v0.5.0 | v0.5.0 | v1.0 |
| `~/.ari/memory.json` 默认参数 | v0.7.0 | v0.7.1（已移除） | v1.0 |
| `ari/migrations/v05_to_v07/` 兼容层 | v0.7.0 | v0.7.0 | v1.0 |

## 发布检查清单

发布新版本时：

1. 更新 `CHANGELOG.md`，添加新的版本章节。将条目分组归类至
   **Added** / **Changed** / **Fixed** / **Deprecated** /
   **Removed** / **Security**。
2. 更新 `ari-core/pyproject.toml` 和各
   `ari-skill-*/pyproject.toml` 中的版本号。
3. 运行完整测试套件 + refactor-guards CI 工作流。
4. 运行文档检查门控：
   - `grep -rn '~/\.ari/' docs/`（排除 `refactor_audit.md`）返回零结果。
   - 每个已记录的环境变量都映射到真实的源码引用。
   - 每个已记录的 MCP 工具都存在于 skill 的 `mcp.json` 中。
   - `python scripts/docs/check_doc_sources.py --require-all` 退出码为 0
     （每个 live doc 声明的 `sources:` 路径都存在）。
   - `python scripts/docs/check_doc_links.py` 退出码为 0
     （docs 内链接 / HTML href 没有失效）。
   - `python scripts/docs/check_translation_freshness.py --strict` 退出码为 0
     （没有 `ja`/`zh` 翻译的 `last_verified` 早于其英文源 —— 参见[源可追溯性](../../README.md#source-traceability)）。
     不加 `--strict` 时为仅警告的非阻塞报告。
5. 打标签：`git tag v0.X.Y && git push origin v0.X.Y`。
6. 在 GitHub 上发布 release，附上 changelog 摘录。
7. 发布 bundle：`ari ear publish`（针对需要随版本发布的制品）。

## 兼容性窗口

- **MINOR** 版本保持前向兼容：在上一个 minor 版本上生成的检查点
  必须在新的 minor 版本上继续可用。
- **MAJOR** 版本可能需要一次性迁移步骤。迁移步骤记录于
  `docs/guides/migration.md`，通过 `ari migrate ...` 执行。
- Skill 独立版本控制。处于 `0.7.x` 的 skill 应能与任意 `0.7.y` 的
  `ari-core` 兼容（同一 minor 内兼容）。跨 minor 版本时，需协调发布。

## 参见

- `CHANGELOG.md` —— 各版本发布说明。
- `CONTRIBUTING.md::Deprecation process` —— 完整弃用计划。
- `docs/guides/migration.md` —— 各版本迁移方案。
- `docs/reference/public_api.md` —— 本策略所保护的公共表面。
