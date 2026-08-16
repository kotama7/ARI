---
sources:
  - path: CHANGELOG.md
    role: doc
  - path: CONTRIBUTING.md
    role: doc
  - path: DEPRECATION_REMOVAL.md
    role: doc
  - path: ari-core/pyproject.toml
    role: config
  - path: .github/workflows/refactor-guards.yml
    role: config
  - path: .github/workflows/docs-sync.yml
    role: config
  - path: scripts/docs
    role: implementation
last_verified: 2026-08-17
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

权威台账是仓库根目录的 `DEPRECATION_REMOVAL.md`（分层、DR1–DR5 各阶段，以及
获得认可的**五**个 Tier-B `~/.ari/` 回退点 —— 下表中的两个，加上
`~/.ari/publish.yaml`、`~/.ari/letta-venv/` 以及第二个 `registries.yaml` 读取方）；
`CONTRIBUTING.md::Deprecation process` 则是给作者看的简短操作说明。
目前正在进行中的示例：

| 条目 | 公告时间 | 警告起始版本 | 计划移除版本 |
|---|---|---|---|
| `$HOME/.ari/registries.yaml` 回退 | v0.5.0 | v0.7.1 | v1.0 |
| `$HOME/.ari/registry-data` 回退 | v0.5.0 | v0.7.1 | v1.0 |
| 旧版 v0.5 JSONL 内存存储 | v0.5.0 | v0.5.0 | v1.0 |
| `~/.ari/memory.json` 默认参数 | v0.7.0 | v0.7.1（已移除） | v1.0 |
| `ari/migrations/v05_to_v07/` 兼容层 | v0.7.0 | v0.7.0 | v1.0 |

全部五个 Tier-B 回退、`ari.migrations.v05_to_v07` 包以及 `legacy_reconstruct`
兼容层将在 DR5 / v1.0 一并移除，届时 `ARI_LETTA_VENV` 成为必填项。

## 发布检查清单

发布新版本时：

1. 更新 `CHANGELOG.md`，添加新的版本章节。将条目分组归类至
   **Added** / **Changed** / **Fixed** / **Deprecated** /
   **Removed** / **Security**。
2. 更新 `ari-core/pyproject.toml` 和各
   `ari-skill-*/pyproject.toml` 中的版本号。这是**软件包版本**，
   由它派生的取值会自动跟随（`scripts/snapshot_contracts.py` 中的
   `_read_ari_core_version()` 会把它写入四份 contract golden 的
   `_meta.ari_core_version`）。

   随后，需要明确决定本次发布是否同时移动**对外版本 pin** —— 即项目
   对读者宣称的版本号。它是另一个独立的寄存器，拥有自己的唯一来源
   （`docs/version.json`，由 `docs/i18n/version.js` 在页面加载时拉取），
   并由另外六个文件复述，这些文件必须在同一次提交中一起移动：

   - `README.md`、`README.ja.md`、`README.zh.md` —— shields.io 的
     `version-vX.Y.Z` 徽章。
   - `report/en/main.tex`、`report/ja/main.tex`、`report/zh/main.tex` ——
     `\date{vX.Y.Z, ...}` 行。

   移动 pin 还意味着重新构建三个 `report/<lang>/main.pdf` 并重新运行
   `scripts/docs/sync_report_pdf.sh`（它会同时写入 `docs/assets/report/`
   与 `docs/public/report/` **两个**目标）。PDF 是生成物：只改 `\date`
   而不重新构建 LaTeX，会让所有已发布的 PDF 仍显示旧版本号。

   移动 pin 还意味着在三个 README 中为新版本号新增一节发布说明
   （`## What's new in vX.Y.Z`，在 `README.ja.md` / `README.zh.md`
   中为对应译名）—— v0.8.1 与 v0.9.0 都是这样发布的。
   `check_readme_parity.py` 比较标题结构，因此会强制三种语言同时新增，
   但**没有任何门控**检查这一节是否存在，所以这份清单是该要求唯一的
   落脚处。徽章宣称一个 README 并未记录的版本，本身就是一个缺陷。

   **允许只提升软件包版本**而保持 pin 不动：一次保持 contract 不变、
   对用户不可见的发布没有可宣称的内容。v0.9.1（2026-07-05）正是这种情况
   （见 `CHANGELOG.md` 中对应条目），因此在 `ari-core` 为 `0.9.1` 时
   pin 仍为 `v0.9.0`。也就是说，pin 可以**落后于**软件包版本，但绝不可
   **领先于**它——那等于宣称一个从未打包过的版本。
   `python scripts/docs/check_site_i18n.py` 会同时检查这两点：上述七个
   文件彼此一致，且 pin 没有超过 `ari-core/pyproject.toml`。
3. 运行完整测试套件 + `refactor-guards`、`docs-sync`、`docs-change-coupling`
   CI 工作流。
4. 运行文档检查门控。CI（`docs-sync.yml`、`refactor-guards.yml`）实际阻断的是：
   - `refactor-guards.yml` 会在 `ari-core/ari/**.py` 中出现**新增**的、且不在其
     allow-list 内的 `~/.ari/` 行时失败（allow-list 包含弃用辅助模块、
     `migrations/`，以及那些先发出警告再回退的兼容点），也会在 pytest 运行创建了
     `$HOME/.ari/` 目录时失败。并不存在对 `docs/` 的仓库级 `grep`：文档中许多
     `~/.ari/` 的提及是合理的（vendored PaperBench 的 `agent.env` 查找、`start.sh`
     的 PID 文件、以及这些 Tier-B 回退本身）。
   - 每个已记录的环境变量都映射到真实的源码引用。
   - 每个已记录的 MCP 工具都存在于 skill 的 `mcp.json` 中。
   - `python scripts/docs/check_doc_sources.py` 退出码为 0
     （每个声明的 `sources:` 路径都存在）。更严格的 `--require-all`
     ——它还要求*每个* live doc 都声明 `sources:`——属于分阶段推进，**今天并不通过**：
     各目录下的 `README.md` 都没有 front matter。
   - `python scripts/docs/check_doc_links.py --html-only` 退出码为 0。完整的
     Markdown 链接检查（不带参数的 `check_doc_links.py`）在 CI 中仅作参考、不阻断。
   - `python scripts/docs/check_i18n_js.py` 退出码为 0
     （landing 面的 `docs/i18n/landing.{en,ja,zh}.js` 声明完全一致的键集；文档站
     迁移到 VitePress 时，旧的 `docs.{en,ja,zh}.js` 查看器词典已被删除）。
   - `python scripts/docs/check_readme_parity.py` 退出码为 0
     （根 `README.{md,ja,zh}` 的标题结构一致）。
   - `python scripts/docs/check_site_i18n.py`，以及 report 的三语结构对齐／
     report-PDF 同步等步骤退出码为 0。
   - 仅作参考（非阻断）：`python scripts/docs/check_translation_freshness.py`
     （没有 `ja`/`zh` 翻译的 `last_verified` 早于其英文源 —— 参见[源可追溯性](../../README.md#source-traceability)）。
     加 `--strict` 会变为阻断；在只更新了英文文档之后，它必然失败。
5. 打标签：`git tag v0.X.Y && git push origin v0.X.Y`。
6. 在 GitHub 上发布 release，附上 changelog 摘录。
7. 发布 bundle：`ari ear publish`（针对需要随版本发布的制品）。

## 兼容性窗口

- **MINOR** 版本保持前向兼容：在上一个 minor 版本上生成的检查点
  必须在新的 minor 版本上继续可用。
- **MAJOR** 版本可能需要一次性迁移步骤。迁移步骤记录于
  `docs/guides/migration.md`，通过 `ari migrate ...` 执行。
- Skill 独立版本控制，且其编号**不**跟随 `ari-core`：面对 `ari-core` 0.9.1，
  随附的各 skill 版本从 `0.1.0`（`ari-skill-harness`、`ari-skill-knowledge`）
  到 `2.0.0`（`ari-skill-orchestrator`）不等。代码中没有任何地方强制
  skill↔core 的版本配对，因此某个 skill 的版本说明的是它自身 API 的状态，
  而不是它需要哪个 core。请按协调发布来搭配，而不是按数字对齐。

## 参见

- `CHANGELOG.md` —— 各版本发布说明。
- `CONTRIBUTING.md::Deprecation process` —— 完整弃用计划。
- `docs/guides/migration.md` —— 各版本迁移方案。
- `docs/reference/public_api.md` —— 本策略所保护的公共表面。
