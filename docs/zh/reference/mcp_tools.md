---
sources:
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-hpc/src/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
last_verified: 2026-06-10
---

# MCP 工具参考

ARI 附带 14 个 MCP 服务器（每个 `ari-skill-*` 包各一个）。本页是智能体可调用的所有工具的平铺目录。每个技能的深入介绍位于其各自的 `README.md`；[skills.md](skills.md) 按职责对它们进行分组。

`mcp.json`（位于各技能的 `pyproject.toml` 旁边）是工具*名称*的权威来源；被 `@mcp.tool()` 装饰的函数（或旧版技能的 `@server.list_tools()` 中的条目）定义了参数和返回结构。

"LLM" 列标记了**P2 例外**工具 — 它们会调用 LLM，因此不是字节确定性的。

## ari-skill-benchmark — 统计 + 绘图（确定性）

| 工具 | 用途 | LLM |
|---|---|:---:|
| `analyze_results` | 从 CSV / JSON / npy 计算摘要统计 | ✗ |
| `plot` | 从固定 schema 生成确定性 matplotlib 图表 | ✗ |
| `statistical_test` | 假设检验（t 检验、Mann-Whitney 等） | ✗ |

## ari-skill-coding — 编写 + 运行代码

`mcp.json` 未列出工具；实际工具列表来自 `src/server.py` 中的 `@server.list_tools()`。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `write_code` | 向节点 work_dir 写入文件 | ✗ |
| `run_code` | 执行脚本（含超时 + 捕获） | ✗ |
| `run_bash` | 临时 bash 命令 | ✗ |
| `emit_results` | 向评估器提交 `metrics` + `has_real_data`（可选 `provenance` 参数 → 原样写入 `_provenance` 键，标记每个值是如何测量的，供 claim-evidence 门使用） | ✗ |
| `read_file` | 读取智能体之前写入的文件 | ✗ |

## ari-skill-evaluator — LLM 指标提取

| 工具 | 用途 | LLM |
|---|---|:---:|
| `make_metric_spec` | LLM 从 `experiment.md` 提取指标定义；同时输出运行级 `metric_contract` → `{checkpoint}/metric_contract.json` | ✓ |
| `claim_evidence_hard_gate` | 确定性的声明/证据硬门（执行数据保真度）；strict 模式下在 final 阶段阻止 finalize | ✗ |
| `evidence_grounded_semantic_review` | 非阻塞的、以证据为基础的语义评审；为 `paper_refine` 输出 `suggested_revisions` | ✓ |

## ari-skill-hpc — SLURM + Singularity

`mcp.json` 为空列表；工具来自 `src/server.py` 中的 `@server.list_tools()`。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `slurm_submit` | 带有显式分区 / 时间 / CPU / 节点 / GPU 的 sbatch | ✗ |
| `job_status` | squeue + sacct 查询 | ✗ |
| `job_cancel` | 取消运行中的作业（scancel） | ✗ |
| `run_bash` | 直接 bash 命令（本地或通过 SSH） | ✗ |
| `singularity_build` | 从定义文件构建 SIF | ✗ |
| `singularity_run` | 在 SIF 内运行命令 | ✗ |
| `singularity_pull` | 从远程 URI 拉取 SIF | ✗ |
| `singularity_build_fakeroot` | Fakeroot 构建（无需特权守护进程） | ✗ |
| `singularity_run_gpu` | `singularity_run` 的 GPU 变体 | ✗ |

## ari-skill-idea — 文献调研 + 创意生成

| 工具 | 用途 | LLM |
|---|---|:---:|
| `survey` | arXiv + Semantic Scholar 搜索；纯 HTTP | ✗ |
| `generate_ideas` | LLM 根据调研 + 上下文生成排序的 idea 候选 | ✓ |

`generate_ideas` 在单一稳定的输出合约背后有两个引擎。默认是轻量的重新实现的
讨论循环；可选启用的真实 VirSci vendor-wrap 引擎（`ARI_IDEA_VIRSCI_REAL=1`）
在实时 Semantic Scholar 快照上运行 VirSci 本身的多智能体机制，在依赖缺失/任何
运行时错误时降级为重新实现的循环。两条路径的 `idea.json` 合约完全相同；所走的
路径在 `virsci_integration_status`（`real_wrap` 或 `reimpl: ...`）中报告。

## ari-skill-memory — 祖先作用域节点记忆

该技能使用 `src/server.py` 中的 FastMCP `@mcp.tool()` 装饰器；其静态 `mcp.json`
已过时（仅列出四个节点作用域工具），但下面所有被装饰的函数在运行时**都会**被暴露。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `add_memory` | 向当前节点的记忆追加条目 | ✗ |
| `search_memory` | 跨当前节点 + 祖先的嵌入排序搜索 | ✗（服务端嵌入） |
| `get_node_memory` | 当前节点的所有条目 | ✗ |
| `clear_node_memory` | 删除当前节点的条目（CoW；祖先不受影响） | ✗ |
| `get_experiment_context` | 从 Letta 核心记忆获取稳定的实验级事实 | ✗ |
| `add_experiment_result` | 记录类型化的 experiment_result（CoW：仅自身节点） | ✗ |
| `add_failure_case` | 记录类型化的 failure_case（CoW：仅自身节点） | ✗ |
| `add_procedure_memory` | 记录可复用的流程（CoW：仅自身节点） | ✗ |
| `add_reflection` | 记录反思（CoW：仅自身节点；不可用于论文声明） | ✗ |
| `add_reproducibility_event` | 追加仅追加的可重现性状态事件（CoW：仅自身节点） | ✗ |
| `search_research_memory` | 按种类 / 产物有无过滤的祖先作用域类型化搜索 | ✗ |
| `get_verified_context` | 供论文 / 图表使用的产物支撑、可重现性感知的上下文 | ✗ |
| `audit_memory` | 将记录的来源（sha256）与检查点磁盘上的内容核对验证 | ✗ |
| `consolidate_node_memory` | 在节点结束时从 node_report 导出 + 写入类型化记忆（CoW：自身节点） | ✗ |

该技能在其设计文档中明确声明"无 LLM 调用" — 见 `ari-skill-memory/README.md`。

## ari-skill-orchestrator — 递归 ARI 运行器

| 工具 | 用途 | LLM |
|---|---|:---:|
| `run_experiment` | 启动子 ARI 运行 | ✗ |
| `get_status` | 子运行状态 | ✗ |
| `list_runs` | 所有已知运行 | ✗ |
| `get_paper` | 某次运行生成的 LaTeX / PDF | ✗ |

## ari-skill-paper — LaTeX 论文撰写

| 工具 | 用途 | LLM |
|---|---|:---:|
| `list_venues` | 可用 LaTeX 模板（ACM / NeurIPS / SC / ICPP / arXiv） | ✗ |
| `get_template` | 获取某 venue 的模板 | ✗ |
| `generate_section` | LLM 撰写一个章节（引言、方法等） | ✓ |
| `compile_paper` | pdflatex 编译 | ✗ |
| `check_format` | LaTeX 格式验证 | ✗ |
| `review_section` | LLM 对某章节进行规范评审 | ✓ |
| `revise_section` | LLM 根据评审反馈重写 | ✓ |
| `write_paper_iterative` | 端到端驱动生成 / 评审 / 修改循环 | ✓ |
| `review_compiled_paper` | 对已编译 PDF 进行最终评审（图表委托 VLM） | ✓ |
| `link_paper_claims` | 将 `% CLAIM:Cx:NCx` 锚点与 science_data 声明核对，构建 `paper_claim_links`（确定性） | ✗ |
| `paper_refine` | 在保留 `% CLAIM:Cx:NCx` 锚点的前提下应用建议的修订（确定性替换 + 有界 LLM 查找/替换） | ✓ |
| `list_rubrics` | 可用的评审规范 | ✗ |
| `inject_code_availability` | v0.7.0 — 向论文追加 `\codedigest{...}` 块 | ✗ |
| `merge_reviews` | v0.7.0 — 合并规范评审 + VLM 评审 JSON | ✗ |

## ari-skill-paper-re — PaperBench 可重现性（v0.7.0）

| 工具 | 用途 | LLM |
|---|---|:---:|
| `fetch_code_bundle` | 按 ref + sha256 获取并校验代码 bundle | ✗ |
| `build_reproduce_sh` | Stage 1 — vendor BasicAgent / IterativeAgent 展开，写入 `reproduce.sh` | ✓ |
| `run_reproduce` | Stage 2 — 在 `local` / `docker` / `apptainer` / `singularity` / `slurm` 沙箱中执行 `reproduce.sh` | ✗ |
| `grade_with_simplejudge` | Stage 3 — LLM 根据 rubric 叶节点对已执行提交评分 | ✓ |

### v0.8.0 新增字段（Stage 1）

| 工具 | 新增参数 |
|---|---|
| `build_reproduce_sh` | `container_image`（替代/取代旧版 `apptainer_image`；两者均向后兼容） |

### v0.8.0 新增字段（Stage 2）

| 工具 | 新增参数 |
|---|---|
| `run_reproduce` | `container_image`（被 docker / apptainer / singularity 沙箱使用；别名 `pb-env` / `pb-reproducer` 解析为 `scripts/build_pb_images.sh` 构建的 vendor `image:latest` 标签） |

高声失败的前置条件：缺失 docker daemon / apptainer 二进制文件 / sbatch / 分区时抛出 `RuntimeError`，而不是静默回退到本地 CPU。可通过 `ARI_PHASE1_ALLOW_FALLBACK=1` 恢复旧版回退行为；通过 `ARI_SLURM_ALLOW_NO_GRES=1` 恢复静默丢弃 GRES 标志的行为。详见 [environment_variables.md](environment_variables.md#paperbench-reproduction-phase-stage-2)。混合使用有类型（`gpu_type` / `--gres=gpu:TYPE:N`）和无类型（`--gpus-per-task`）GPU 请求时自动规范化为有类型形式 — SLURM 24.05 拒绝混合形式。

### v0.8.0 新增字段（Stage 3）

| 工具 | 新增参数 |
|---|---|
| `grade_with_simplejudge` | `code_only`（将 rubric 裁剪为仅 Code Development 叶节点，镜像 vendor `paperbench/grade.py:109-112`；当不存在 `reproduce.log` 时自动启用，防止仅 Stage 1 运行被系统性评零） |

关于以单一调用词汇将全部三个阶段串联起来的进程内 Python 接口，请参阅 [`api_paperbench.md` § Bridge 合约](api_paperbench.md#bridge-contract-in-process-python-surface)。

## ari-skill-plot — 图表生成

| 工具 | 用途 | LLM |
|---|---|:---:|
| `generate_figures` | 从 `nodes_tree.json` 生成确定性 matplotlib 图表 | ✗ |
| `generate_figures_llm` | LLM 编写 matplotlib 代码后运行 | ✓ |

## ari-skill-replicate — 规范自动生成（v0.7.0）

| 工具 | 用途 | LLM |
|---|---|:---:|
| `generate_rubric` | 两阶段（骨架 + 子树）PaperBench 规范合成 | ✓ |
| `audit_rubric` | LLM 审核叶节点中模糊/不可验证/重复的标准 | ✓ |

### `generate_rubric` — venue 条件化模板（未发布）

`generate_rubric` 接受可选参数 `paperbench_rubric_id`，从 `ari-core/config/paperbench_rubrics/<id>.yaml` 中选择 venue 条件化模板。镜像 `ari-skill-paper` 同行评审路径中已使用的 `reviewer_rubrics/` venue 模式。

| 参数 | 类型 | 默认值 | 效果 |
|---|---|---|---|
| `paperbench_rubric_id` | `str` | `""` | 空 = 原样使用捆绑提示（向后兼容）。否则加载 YAML 模板，并将 `prompt_overrides.system_hint` / `prompt_overrides.leaf_style` 注入骨架 + 子树提示。 |

内置模板：

| `id` | `mode` | 顶层结构 |
|---|---|---|
| `generic` | `agent_benchmark` | 按科学贡献分解（当前默认行为）。 |
| `sc` | `paper_audit` | HPC 论文的六个固定审核轴（环境 / 数据 / 执行 / 图表 / 扩展 / 结论）。 |
| `neurips` | `paper_audit` | 按 NeurIPS 可重现性检查表的六个轴（声明 / 设置 / 代码+数据 / 统计 / 伦理 / 图表）。 |
| `nature` | `paper_audit` | 湿实验室论文的五个轴（材料 / 方案 / 统计 / 数据 / 伦理）。 |

`paper_audit` 模式需要 `two_stage=True`；若使用 `paper_audit` 模板请求单次路径，生成器会返回错误（单次提示无法满足固定轴约束）。YAML schema 和撰写指南请参见 [`rubric_schema.md`](rubric_schema.md#venue-conditioned-templates)。

## ari-skill-transform — 树遍历 + EAR 流水线

`mcp.json` 未列出工具（该文件仅供内部使用）；`src/server.py` 中的 `@mcp.tool()` 装饰器是权威来源。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `nodes_to_science_data` | 遍历 BFTS 树，提取方法论 + 发现 | ✓ |
| `generate_ear` | 从 BFTS 产物构建 `{checkpoint}/ear/` | ✗ |
| `curate_ear` | 将 `ear/` 提升为 `ear_published/` + manifest.lock | ✗ |
| `publish_ear` | 推送到 `local-tarball` / `ari-registry` / `zenodo` / `gh` | ✗ |
| `promote_ear` | `staged` → `unlisted` / `public` | ✗ |

## ari-skill-vlm — 图表 / 表格评审（VLM）

`mcp.json` 未列出工具；该技能仅暴露内部评审辅助函数。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `review_figure` | VLM 读取图像 + 标题，返回评审意见 | ✓（视觉） |
| `review_table` | VLM 评审表格 | ✓（视觉） |
| `review_paper_figures` | 批量评审论文目录中的所有图表 | ✓（视觉） |

## ari-skill-web — 搜索 + 获取

| 工具 | 用途 | LLM |
|---|---|:---:|
| `web_search` | DuckDuckGo（无需 API 密钥） | ✗ |
| `fetch_url` | URL → 可读文本 | ✗ |
| `search_arxiv` | arXiv API | ✗ |
| `search_semantic_scholar` | Semantic Scholar API | ✗ |
| `collect_references_iterative` | 从种子论文遍历引用图 | ✗ |

## 另请参阅

- `docs/reference/skills.md` — 每个技能的叙述说明（职责、环境变量、示例）。
- `docs/reference/environment_variables.md` — 逐变量环境变量参考。
- 各技能的 `mcp.json` — 规范工具名称列表。
- 各技能 `src/server.py` 中的 `@mcp.tool()` / `@server.list_tools()` — 规范参数签名。
