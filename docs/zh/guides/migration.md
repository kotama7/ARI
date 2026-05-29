---
sources:
  - path: ari-core/ari/migrations/v05_to_v07
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
last_verified: 2026-05-25
---

# 迁移指南

ARI 的检查点格式经历了三个版本的演进。本指南介绍各升级路径。

| 源版本 | 目标版本 | 核心变更 |
|---|---|---|
| v0.5 | v0.6 | Letta 内存后端取代 JSONL |
| v0.6 | v0.7 | ORS / EAR registry / lineage decisions |
| v0.7 | v0.8（未来）| 重构后的检查点格式（`ari.public/` 边界）|
| v0.8 | v1.0（未来）| 移除旧版兼容层 |

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
   export LETTA_EMBEDDING_CONFIG=/path/to/embedding.json
   export ARI_MEMORY_BACKEND=letta
   ```
3. **迁移现有内存。** 对每个 v0.5 检查点执行：
   ```bash
   ARI_CHECKPOINT_DIR=/path/to/ckpt ari memory migrate
   ```
   迁移工具读取 `memory_store.jsonl`（以及旧版全局 JSONL，如有），
   写入 Letta 智能体，并将结果快照至 `memory_backup.jsonl.gz`。
4. **删除旧版 JSONL 文件。** 验证迁移成功后执行：
   ```bash
   rm /path/to/ckpt/memory_store.jsonl
   rm $HOME/.ari/global_memory.jsonl   # if it ever existed
   ```
5. **选择 rubric。** 从
   `ari-core/config/reviewer_rubrics/` 中选择一个 YAML 并导出：
   ```bash
   export ARI_RUBRIC=neurips2025
   ```
   后续的论文评审和 BFTS 评分将使用新的评审维度。

### 验证

- `ari memory health` 返回 `ok` 并报告智能体名称。
- 来自智能体循环的 `search_memory` 调用返回基于嵌入的排名结果。
- 仪表盘 `/api/memory/health` 端点返回 200。

## v0.6 → v0.7

### 变更内容

- **ORS（对象仓库规范）。** 可复现性链路从 `react_driver` 的
  临时复现方案迁移至 `ari-skill-replicate`（rubric 生成器）+
  `ari-skill-paper-re`（PaperBench SimpleJudge 评分器）。
- **EAR registry。** EAR bundle 可发布至自托管的 `ari-registry`
  服务器（除 local-tarball / Zenodo / GitHub release 外的新选项）。
- **Lineage decisions。** `stagnation_rule` 监控 BFTS 综合评分；
  触发时由 LLM 选择 `continue` / `switch_to_idea` / `fanout` /
  `terminate`。决策追加写入 `lineage_decisions.jsonl`。
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
   ari replicate generate-rubric <checkpoint>
   ari paper-re grade <checkpoint>
   ```

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

## 参见

- `docs/_archive/refactor_audit.md` —— 迁移债务的当前状态。
- `CHANGELOG.md` —— 各版本发布说明。
- `ari memory migrate --help` —— v0.5 → v0.6 迁移工具的 CLI 选项。
- `docs/guides/troubleshooting.md` —— 迁移失败时的处理方法。
