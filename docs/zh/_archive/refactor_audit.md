# 重构审计（Phase 0）

> 历史清单快照，原文保留自 v0.7.1 重构开始时。下方表格中所有
> "计划"单元格的工作均已完成 —— 当前运行架构见 `docs/architecture.md`
>（分层架构章节）和 `CONTRIBUTING.md`（软件工程规范 §1–5）。
> 本文件仅作存档参考；请勿将其当作仍在进行中的工作来编辑。

## 1. 大型模块（Phase 3 拆分目标）

| 文件 | 行数 | 计划 |
|---|---:|---|
| `ari-core/ari/cli.py` | 1,962 | Phase 3A —— 拆分为 `ari/cli/{lineage,bfts_loop,run,projects,commands,migrate}.py` |
| `ari-core/ari/pipeline.py` | 1,641 | Phase 3C —— 拆分为 `ari/pipeline/{experiment_md,yaml_loader,stage_control,context_builder,stage_runner,orchestrator}.py` |
| `ari-core/ari/viz/server.py` | 1,489 | Phase 3B —— 拆分为 `viz/{websocket,ui_helpers,routes}.py` |
| `ari-core/ari/agent/loop.py` | 1,459 | Phase 3D —— 提取 `agent/{message_utils,tool_manager,guidance}.py` |
| `ari-core/ari/viz/api_state.py` | 1,434 | Phase 3B —— 拆分为 `viz/{checkpoint_finder,state_sync,checkpoint_api,ear,file_api,checkpoint_lifecycle,node_work_api}.py` |
| `ari-core/ari/orchestrator/node_report.py` | 706 | Phase 3E —— 拆分为 `node_report/{builder,legacy_reconstruct}.py` |

合计：**8,691 行**，分布于六个文件。

## 2. `ARI_CHECKPOINT_DIR` 直接环境变量读取（Phase 1 目标）

31 处出现，分散于 cli/pipeline/agent/orchestrator/viz/memory 中。
Phase 1（PR-1A + PR-1B）完成后，所有读取均改为通过
`PathManager.from_env()`：

```text
ari-core/ari/config.py:153,244
ari-core/ari/orchestrator/bfts.py:27,58
ari-core/ari/lineage.py:56
ari-core/ari/cost_tracker.py:197
ari-core/ari/cli.py:1203,1445,1898
ari-core/ari/pipeline.py:786,791,829,976
ari-core/ari/memory_cli.py:36,46
ari-core/ari/memory/letta_client.py:25
ari-core/ari/memory/auto_migrate.py:51
ari-core/ari/viz/api_experiment.py:622
ari-core/ari/viz/api_memory.py:38
ari-core/ari/viz/api_orchestrator.py:284
ari-core/ari/viz/api_state.py:1389
ari-core/ari/viz/server.py:383
```

（仅限读取位置；向 MCP 子进程环境同步的写操作保持
``os.environ[...] = ...`` 形式 —— 这不是 Phase 1 的目标。）

## 3. 跨文件重复

| 关注点 | 实现位置 |
|---|---|
| `workflow.yaml` 查找逻辑 | `cli.py:_resolve_cfg`、`pipeline.py:load_workflow`、`viz/server.py:_build_experiment_detail_config` |
| 检查点 tree.json 读写 | `cli.py:_save_tree_incremental`、`cli.py`（删除路径）、`viz/api_state.py:_load_nodes_tree` |

Phase 2 将各自合并为一个模块：
- `ari/config/finder.py`（PR-2A）
- `ari/checkpoint.py`（PR-2B）

## 4. Skill → core 内部导入边界违规

| 调用方 | 导入内容 |
|---|---|
| `ari-skill-coding/tests/test_server.py:102` | `import ari.container` |
| `ari-skill-plot/src/server.py:28` | `from ari import cost_tracker` |

Phase 4 将两者都通过 `ari/public/` 路由，并新增
`tests/test_public_api_boundary.py` 以防回归。

## 5. 代码中的 `~/.ari/` 旧路径（DEPRECATION_REMOVAL.md §1-1）

13 处出现，分散于 publish/clone/registry/memory/viz_api_publish：

| 文件:行号 | 级别 | 操作 |
|---|:---:|---|
| `ari/memory/file_client.py:25` | A | DR1 —— 删除默认参数 |
| `ari/memory_cli.py:111` | C | DR3 / Phase 5 —— 移至 `migrations/v05_to_v07/memory.py` |
| `ari/memory_cli.py:306` | B | DR2 → 警告，DR5 → 要求显式 env |
| `ari/memory/auto_migrate.py:43` | C | 移至迁移模块（Phase 5） |
| `ari/publish/backends/ari_registry.py:29,98` | B | DR2 警告 + 检查点作用域查找 |
| `ari/clone/resolvers/ari.py:29,78` | B | 同 publish（共享辅助函数） |
| `ari/registry/app.py:29` | B | DR2 + `resolve_data_dir()` 辅助函数 |
| `ari/registry/cli.py:20` | B | 同 `app.py` |
| `ari/viz/api_publish.py:24` | B | 将模块级 Path.home() 移入函数内 |
| `ari/core.py:91`（文档字符串） | doc | Phase 6 |
| `ari/paths.py:113`（文档字符串） | doc | Phase 6 |

## 6. 文档中的 `~/.ari/` 旧路径（Phase 6）

`grep -rln "~/\.ari" docs/` → 16 个文件（en + ja + zh）。Phase 0 在
每处出现位置添加 `[DEPRECATED since v0.5.0]` 横幅；Phase 6 完成
将其重写为 `$ARI_CHECKPOINT_DIR/...` 形式。

## 7. 待隔离的迁移债务（Phase 5）

| 来源 | 描述 |
|---|---|
| `cli.py:246–305 cmd_migrate_node_reports` | v0.5 → v0.7 node_report 迁移工具 |
| `cli.py:1135–1352 backfill_node_reports`（调用处） | 旧版按需回填 |
| `memory/auto_migrate.py` | v0.5 全局 JSONL → 检查点内存 |
| `evaluator/llm_evaluator.py:586–589` | 旧版 5 轴回退 |
| `orchestrator/node_report.py:650 reconstruct_report_from_legacy` | 旧树 → node_report 重建工具 |

所有内容移至 `ari/migrations/v05_to_v07/`，原导入路径保留薄兼容层。

## 8. 提示词/配置外部化（PROMPTS_AND_CONFIG.md §1）

8 个提示词 + 1 个价格表 + 1 个默认值表，目标为 Phase PC0–PC8：

| 文件:行号 | 目标位置 |
|---|---|
| `agent/loop.py:41 SYSTEM_PROMPT` | `ari/prompts/agent/system.md` |
| `orchestrator/lineage_decision.py:239` | `ari/prompts/orchestrator/lineage_decision.md` |
| `orchestrator/root_idea_selector.py:57` | `ari/prompts/orchestrator/root_idea_selector.md` |
| `orchestrator/bfts.py:215,296,481` | `ari/prompts/orchestrator/bfts_*.md` |
| `pipeline.py:430` | `ari/prompts/pipeline/keyword_librarian.md` |
| `evaluator/llm_evaluator.py:165,324` | `ari/prompts/evaluator/{extract_metrics,peer_review}.md` |
| `cost_tracker.py:16–33` 价格字典 | `ari/configs/model_prices.yaml` |
| `config.py` 默认值 | `ari/configs/defaults.yaml` |

## 9. 测试端审计（DEPRECATION_REMOVAL.md §1-3）

| 文件:行号 | 问题 | 操作 |
|---|---|---|
| `tests/test_ollama_gpu.py:25,125,150,175,190` | `_st._settings_path.write_text(...)` | DR4 —— 确认每次调用都在 `monkeypatch.setattr` 内部 |
| `tests/test_letta_restart_live.py:43` | 读取 `Path.home() / ".ari" / "letta-pid"` | DR4 —— `monkeypatch.setenv("ARI_LETTA_PIDFILE", ...)` fixture |
| `tests/test_settings_roundtrip.py:8` | 文档字符串中提及 `~/.ari/settings.json` | Phase 6 —— 编辑注释 |
| `tests/test_clone.py:190` | 文档字符串 | Phase 6 |
| `tests/test_paths.py:131` | 注释（"no global ~/.ari anymore"） | 保持现状 |

## 10. 子计划映射（历史记录）

下列重构子计划均为一次性规划文件；每份文件在其范围落地后通过
`[plan-deletion]` commit 删除。使用
`git log --oneline --diff-filter=D --follow -- <path>` 可检索历史记录。

| 计划（已删除） | 负责人 |
|---|---|
| `REFACTORING.md`（根目录） | Master |
| `ari-core/REFACTORING.md` | cli/pipeline/core 拆分 + 共享模块 |
| `ari-core/ari/agent/REFACTORING.md` | agent/loop.py 拆分 + 测试 |
| `ari-core/ari/viz/REFACTORING.md` | viz server/api_state 拆分 |
| `ari-core/ari/orchestrator/REFACTORING.md` | node_report 拆分 + 旧版隔离 |
| `ari-core/ari/evaluator/REFACTORING.md` | 提示词提取 + Evaluator Protocol |
| `ari-core/ari/memory/REFACTORING.md` | A/B/C 级别清理 |
| `ari-core/ari/publish/REFACTORING.md` | B 级别清理 |
| `ari-core/ari/clone/REFACTORING.md` | B 级别清理（与 publish 共享辅助函数） |
| `ari-core/ari/registry/REFACTORING.md` | B 级别清理（`resolve_data_dir`） |
| `ari-core/tests/REFACTORING.md` | D 级别测试隔离 |
| `ari-skill-coding/REFACTORING.md` | `ari.public.container` 迁移 |
| `ari-skill-plot/REFACTORING.md` | `ari.public.cost_tracker` 迁移 |
| `PROMPTS_AND_CONFIG.md` | 提示词/配置外部化总计划 |
| `DEPRECATION_REMOVAL.md` | 级别分类 + DR0–DR5 阶段 |

## 11. 文档审计（Phase D0 —— DOCUMENTATION_PLAN.md）

快照于 2026-05-09 对照主文档 `DOCUMENTATION_PLAN.md` 及其 16 份子计划
生成。计划中指出的部分缺失项已完成；下表对计划与实际情况进行对照。

### 11-1. 文档中的 `~/.ari/` 残留（DOCUMENTATION_PLAN.md §2-1）

`grep -rn '~/\.ari' docs/` 命中 17 个文件（16 个产品文档 + 本审计文件）。
§9 质量门控要求 `docs/` 下命中数为零，因此每处引用都必须改写为
v0.5.0+ 作用域形式：

| 旧版路径 | 新版写法 |
|---|---|
| `~/.ari/registries.yaml` | `$ARI_CHECKPOINT_DIR/.ari/registries.yaml`（或 `$ARI_REGISTRIES_FILE`） |
| `~/.ari/registry-data` | `$ARI_REGISTRY_DATA`（无全局默认值） |
| `~/.ari/settings.json` | `$ARI_CHECKPOINT_DIR/settings.json` |
| `~/.ari/global_memory.jsonl` | `$ARI_CHECKPOINT_DIR/memory_store.jsonl`（file 后端）或 Letta 存储 |
| `~/.ari/letta-pid` | `$ARI_LETTA_PIDFILE` |

需要改写的文件（均保留*弃用注释*，但不再引用字面量 `~/.ari/...` 路径）：

```
docs/architecture.md       docs/ja/architecture.md       docs/zh/architecture.md
docs/cli_reference.md      docs/ja/cli_reference.md      docs/zh/cli_reference.md
docs/configuration.md      docs/ja/configuration.md      docs/zh/configuration.md
docs/registry.md           docs/ja/registry.md           docs/zh/registry.md
docs/skills.md             docs/ja/skills.md             docs/zh/skills.md
```

（`docs/refactor_audit.md` 和 `docs/DOCUMENTATION_PLAN.md` 保留 ——
它们的内容本身就是关于旧版状态的。§9 的 grep 仅针对产品文档。）

### 11-2. 与主计划 §2 的对照

| 计划声明 | 实际情况（5月9日） | 操作 |
|---|---|---|
| `architecture.md` 缺少 v0.6/v0.7 内容 | 已包含 §"Publication Lifecycle (v0.7.0)"、§"Plan / Venue contract (v0.7.0+)"、§"work_dir inheritance (v0.7.0 / Phase 7)"、§"v0.6.0: backed by Letta"、§"Layered architecture (v0.7+ refactor)" | **已完成 —— 无需重写。** 仅从 §"Module Reference" 添加新参考文档的交叉链接。 |
| `skills.md` 缺少 `ari-skill-replicate` 和 `ari-skill-paper-re` | 已在 L273（`paper-re`）和 L430（`replicate`）包含完整工具表及 v0.7.0 标记 | **已完成。** 验证 ja/zh 是否同步。 |
| `experiment_file.md`、`extension_guide.md`、`hpc_setup.md`、`PHILOSOPHY.md` 停留在 4月17日 | `extension_guide.md`（5月8日）、`PHILOSOPHY.md`（5月8日）已更新。仅 `experiment_file.md` 和 `hpc_setup.md` 仍为 4月17日。 | 更新**两**个文档，而非四个。 |
| `ari-skill-coding/`、`plot/`、`transform/` 缺少 README | 已确认。 | 新建。 |
| `ari/public/` 尚未建立 | 已存在，含 5 个模块（`config_schema.py`、`container.py`、`cost_tracker.py`、`llm.py`、`paths.py`）。 | Phase 4 在代码层面**已完成**；Phase D2 仅需撰写参考文档。 |
| `ari-core/ari/<subdir>/__init__.py` 大多为空 | 空：`agent`、`llm`、`mcp`、`memory`、`orchestrator`。单行注释：`viz`。其他有文档字符串。 | 需填充 5 个子目录。 |

### 11-3. 待撰写的文档增量（按优先级排序）

| # | 条目 | 类型 | 阶段 | 负责文档 |
|---|---|:---:|:---:|---|
| 1 | 对 15 个产品文档（en + ja + zh）进行 `~/.ari/` 清理 | 机械性 | D1-2-1 | `cli_reference.md`、`configuration.md`、`registry.md`、`skills.md`、`architecture.md` × 3 语言 |
| 2 | 验证 `skills.md` 的 ja/zh 版与 en 版在 replicate + paper-re 章节上的同步情况 | 同步 | D1-2-2 | `docs/{ja,zh}/skills.md` |
| 3 | 为 v0.6（rubric、ORS 元数据）和 v0.7（experiment.md 中的 lineage decisions）刷新 `experiment_file.md` | 内容 | D1-2-4 | `docs/{,ja/,zh/}experiment_file.md` |
| 4 | 刷新 `hpc_setup.md`，添加容器部署 + Letta 后端部署内容 | 内容 | D1-2-4 | `docs/{,ja/,zh/}hpc_setup.md` |
| 5 | 为 5 个空子目录填写 `__init__.py` 文档字符串 + 重写 `viz` | 代码文档 | D2 | `ari/{agent,llm,mcp,memory,orchestrator,viz}/__init__.py` |
| 6 | 为 `ari-skill-coding/`、`plot/`、`transform/` 新建 README | 代码文档 | D2 | 新文件 |
| 7 | `docs/reference/public_api.md`，覆盖 `ari.public.*` | 参考 | D2/D3 | 新文件 |
| 8 | `docs/reference/rest_api.md`，覆盖 `viz/routes.py` + 同级 `viz/api_*.py` | 参考 | D3 | 新文件 |
| 9 | `docs/reference/mcp_tools.md`，汇总 14 个 skill 的 `mcp.json` | 参考 | D3 | 新文件 |
| 10 | `docs/reference/environment_variables.md` | 参考 | D3 | 新文件 |
| 11 | `docs/reference/file_formats.md`（`tree.json`、`nodes_tree.json`、`node_report.json`、`settings.json`、`workflow.yaml`、`experiment.md`） | 参考 | D3 | 新文件 |
| 12 | `docs/howto/testing.md` | 操作方法 | D4 | 新文件 |
| 13 | `docs/howto/migration.md`（v0.5 → v0.6 → v0.7） | 操作方法 | D4 | 新文件 |
| 14 | `docs/howto/troubleshooting.md` | 操作方法 | D4 | 新文件 |
| 15 | `docs/release_policy.md`（SemVer、支持窗口） | 操作方法 | D5 | 新文件 |
| 16 | 条目 1、3、4、12–15 的 ja/zh 同步 | 国际化 | D5 | 翻译 |

### 11-4. 向前延续的验收门控

§9 主计划的门控条件在此重申，供每个 PR 自查：

- `grep -rn '~/\.ari/' docs/`（排除 `docs/DOCUMENTATION_PLAN.md` 和
  `docs/refactor_audit.md`）返回零结果。
- 每个已记录的 CLI 标志、环境变量、REST 端点、MCP 工具名称均可通过
  `grep -rn` 在对应源码树中找到真实符号。
- ja 和 zh 与 en 在*旧版*文档的章节结构上保持一致（新参考文档以
  en 优先；ja/zh 允许滞后）。
- Markdown 链接检查（`grep -nE '\]\([^)]*\)' docs/**/*.md` 后进行
  手动或脚本化核查）未发现损坏的仓库内链接。
