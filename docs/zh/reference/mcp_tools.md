---
sources:
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-idea/src/server.py
    role: implementation
last_verified: 2026-07-30
---

# MCP 工具参考

ARI 附带 17 个 MCP 服务器（每个 `ari-skill-*` 包各一个）。其中 13 个由 `ari-core/config/workflow.yaml` 的 `skills:` 默认注册，`ari-skill-orchestrator` 作为独立进程为外部客户端启动，其余 `ari-skill-knowledge` / `ari-skill-harness` / `ari-skill-tool-registry` 不在默认 `skills:` 列表中。本页是智能体可调用的所有工具的平铺目录。每个技能的深入介绍位于其各自的 `README.md`；[skills.md](skills.md) 按职责对它们进行分组。

`mcp.json`（位于各技能的 `pyproject.toml` 旁边）是工具*名称*的权威来源，它由 `scripts/sync_skill_metadata.py --write` 从 `skill.yaml` 生成；被 `@mcp.tool()` 装饰的函数（或旧版技能的 `@server.list_tools()` 中的条目）定义了参数和返回结构。三者必须一致——`scripts/check_skill_manifests.py` 会在漂移时失败。

"LLM" 列标记了**P2 例外**工具 — 它们会调用 LLM，因此不是字节确定性的。

## ari-skill-benchmark — 统计 + 运行比较（确定性）

| 工具 | 用途 | LLM |
|---|---|:---:|
| `analyze_results` | 按 `AnalysisRequestV1` 汇总带单位的 typed 样本（inline observations 或不可变 source），给出摘要统计、置信区间与独立性状态 | ✗ |
| `statistical_test` | 按 `StatisticalTestRequestV1` 运行预先声明的检验族（`auto` / `welch_t` / `student_t` / `paired_t` / `mann_whitney` / `wilcoxon`），附效应量与多重比较校正（`none` / `bonferroni` / `holm` / `benjamini_hochberg`；多于一个比较时必须显式声明校正） | ✗ |
| `compare_runs` | 按 `RunComparisonRequestV1` 对标量 run 排名，并报告环境 / provenance 的可比性与独立性状态 | ✗ |

绘图不在本技能内：固定 schema 的确定性渲染由 `ari-skill-plot` 的 `render_figure` /
`generate_figures` 承担。

## ari-skill-coding — 编写 + 运行代码

`mcp.json` 记录工具*名称*，由 `skill.yaml` 生成；完整 schema 仍来自 `src/server.py`
中的 `@server.list_tools()`。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `write_code` | 向节点 work_dir 写入文件 | ✗ |
| `edit_code` | 在已存在的文件中替换一段精确文本，其余部分原样保留。文件已存在时优先于 `write_code`：除非设置 `replace_all`，`old_string` 必须**恰好**匹配一次，因此有歧义的编辑会失败，而不是悄悄改错地方 | ✗ |
| `run_code` | 执行脚本（含超时 + 捕获） | ✗ |
| `run_bash` | 临时 bash 命令 | ✗ |
| `describe_environment` | 返回本集群的环境目录（架构、CPU、GPU、PATH 上的编译器、原始 `module avail`，以及已设置的工具链环境变量的**名字**）。在登录节点上还会逐个报告已配置的计算分区，在计算节点上只报告该节点。无参数 | ✗ |
| `emit_results` | 向评估器提交 `metrics` + `has_real_data`（可选 `provenance` 参数 → 原样写入 `_provenance` 键，标记每个值是如何测量的，供 claim-evidence 门使用） | ✗ |
| `read_file` | 读取智能体之前写入的文件 | ✗ |

## ari-skill-evaluator — 指标契约 + 声明门

| 工具 | 用途 | LLM |
|---|---|:---:|
| `make_metric_spec` | 确定性地把一份不可变契约物化为 MetricSpec：优先取 idea 拥有的 `ResearchContractV1`，其次是经人工准入（`reviewer`）的 proposal，再次是已持久化的 `metric_contract.json`；都没有时只返回 parser 证据并标记 `admission_status: "human-review-required"`。同时写出 `{checkpoint}/metric_contract.json` | ✗ |
| `propose_metric_contract` | 显式的 LLM 提案步骤：从 `idea.json`（或传入的 idea 证据）提出一份 `MetricContractProposalV1` → `{checkpoint}/metric_contract_proposal.json`。输出永远 `requires_human_review`，且不能取代 idea 拥有的 typed 契约 | ✓ |
| `claim_evidence_hard_gate` | 确定性的声明/证据硬门（执行数据保真度）；strict 模式下在 final 阶段阻止 finalize | ✗ |
| `evidence_grounded_semantic_review` | 非阻塞的、以证据为基础的语义评审；为 `paper_refine` 输出 `suggested_revisions` | ✓ |

## ari-skill-hpc — SLURM + Singularity

`mcp.json` 只记录工具*名称*，由 `skill.yaml` 生成；完整 schema 来自
`ari_skill_hpc/server.py` 中的 `@server.list_tools()`。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `job_submit` | 提交不可变的 `JobRequestV1` 并立即返回幂等的 `JobHandleV1`；命令为 argv 数组，绝不使用登录节点的 shell | ✗ |
| `container_submit` | 相同的生命周期，但请求必须带有 digest 钉定的 Apptainer/Singularity 容器声明 | ✗ |
| `job_status` | 针对 ARI 句柄或原始 SLURM ID 的 provider 中立 `JobStatusV1`（squeue + sacct 查询） | ✗ |
| `job_result` | 收集终态 `JobResultV1`，并重新哈希声明的输入 / 输出 / 日志 | ✗ |
| `job_logs` | 返回 ARI 作业句柄的有界、带 digest 的 stdout / stderr | ✗ |
| `job_cancel` | 请求取消 ARI 或 SLURM 作业 | ✗ |
| `slurm_submit` | core 智能体批处理脚本工作流的兼容桥：带有显式分区 / 时间 / 节点 / 任务 / CPU / modules 以及显式 `launcher` 的 sbatch。新的程序化调用方应使用 `job_submit` | ✗ |
| `probe_platform_capabilities` | 在**计算分区上**探测工具可用性（`command -v`）并缓存到 `{checkpoint}/platform_capabilities.json`；尽力而为（任何失败都报告为 skipped 且不写入） | ✗ |
| `counter_support` | 报告该节点是否授予硬件计数器 —— 通过实际打开一个计数器来确定，而不是查找 profiler 二进制文件 | ✗ |
| `measure_counters` | 在有界窗口内对已有进程计数经审查的硬件事件；不创建进程，也不写入任何内容 | ✗ |

`launcher` 说明脚本在分配内如何启动，它是显式声明的，而不是从 `tasks > 1`
推断出来的：`auto`（默认）用 `srun --ntasks=1` 绑定单任务单节点的负载，更大的
形状则直接启动，把并行启动留给脚本自己；`srun` 按声明的
`nodes` / `tasks` / `cpus_per_task` 启动脚本本身，这正是 MPI / SPMD 二进制所
需要的；`none` 从不包装。启动模式是请求 digest 的一部分。完整参数列表见
[skills.md](skills.md#ari-skill-hpc)。

`measure_counters` 声明了 `context_requirement: node`，因此其输入 schema 声明了
一个 `ari_context` 对象属性。transport 会为任何带 context 要求的工具以该名称注入
已授权的 call context；若 schema 设置 `additionalProperties: false` 却不声明它，
就会拒绝每一次已授权的调用。proxy 会在 `tools/list` 中重新去掉该属性，因此它绝不
会成为智能体需要提供的参数。

## ari-skill-idea — 文献调研 + 创意生成

| 工具 | 用途 | LLM |
|---|---|:---:|
| `survey` | 针对**单个**钉住 provider（`semantic-scholar` 默认 / `virsci-snapshot`）的先前工作调研。`record` / `live` 不切换后端，`replay` 完全不访问网络，未支持的 provider 会被拒绝而不是被替换 | ✗ |
| `generate_ideas` | LLM 根据调研 + 上下文生成排序的 idea 候选 | ✓ |

这两个是该技能仅有的已注册工具——`_load_virsci_snapshot_papers` 只是
`survey` 直接调用的普通辅助函数，绝不对 agent 可见；
`ari-skill-idea/tests/test_server.py` 通过 `mcp.list_tools()` 同时钉住
这两点。provider 之间没有回退：`virsci-snapshot` 的调研在语料库缺失时抛出
`FileNotFoundError`，Semantic Scholar 的调研遇到 HTTP 错误时直接抛出——故障
时得到的是一次拒绝，而不是悄悄变成另一份语料库。
它们也是 RQGM `VirSciAdapter` 背后的 MCP 表面：在可选启用的
`ari_rqgm` 模式下且 `proposal_router.generators.virsci.enabled: true`
时，core 侧的 ProposalRouter 会在每纪元调用预算内把构思事件路由到
`survey` + `generate_ideas` —— 见
[VirSci 集成](../guides/virsci_integration.md)。

`generate_ideas` 在单一稳定的输出合约背后有两个引擎。默认是轻量的重新实现的
讨论循环；可选启用的真实 VirSci vendor-wrap 引擎（`ARI_IDEA_VIRSCI_REAL=1`）
在实时 Semantic Scholar 快照上运行 VirSci 本身的多智能体机制，在依赖缺失/任何
运行时错误时降级为重新实现的循环。两条路径的 `idea.json` 合约完全相同；所走的
路径在 `virsci_integration_status`（`real_wrap` 或 `reimpl: ...`）中报告。

## ari-skill-memory — 祖先作用域节点记忆

该技能使用 `src/server.py` 中的 FastMCP `@mcp.tool()` 装饰器；`mcp.json` 由
`skill.yaml` 生成，与下面被装饰的 13 个函数一一对应。本技能不暴露任何删除条目的
工具。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `add_memory` | 向当前节点的记忆追加条目 | ✗ |
| `search_memory` | 跨当前节点 + 祖先的嵌入排序搜索 | ✗（服务端嵌入） |
| `get_node_memory` | 当前节点的所有条目 | ✗ |
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
| `run_experiment` | 幂等地提交一次受配额约束的子 ARI 运行（需要 `idempotency_key`），返回其持久句柄 | ✗ |
| `get_status` | 子运行的确切持久状态与有界的科研进度 | ✗ |
| `get_result` | 终态元数据与按 digest 寻址的产物 | ✗ |
| `stop_experiment` | 取消运行、向下传播终止，并落定唯一的终态 | ✗ |
| `list_runs` | 只列出认证 principal 拥有的运行（admin 可列全部） | ✗ |
| `list_children` | 某个父运行 ID 的已授权直接子代 | ✗ |
| `list_artifacts` | 列出在 allowlist 内、经 digest 校验的产物，不暴露路径 | ✗ |
| `read_artifact` | 按确切的 SHA-256 身份读取一份已准入的有界产物 | ✗ |
| `get_paper` | 某次运行的论文产物引用 | ✗ |
| `get_ear` | 某次运行经校验的 EAR 与证据产物引用 | ✗ |
| `list_skills` | 该运行经净化的、不可变的 `SKILLS.lock` 视图 | ✗ |
| `get_workflow` | 锁定的 phase / 工具成员关系（不含原始 workflow 与机密配置） | ✗ |

## ari-skill-paper — LaTeX 论文撰写

| 工具 | 用途 | LLM |
|---|---|:---:|
| `list_venues` | 可用 LaTeX 模板（ACM / NeurIPS / SC / ICPP / arXiv） | ✗ |
| `get_template` | 获取某 venue 的模板 | ✗ |
| `compile_paper` | pdflatex 编译 | ✗ |
| `check_format` | LaTeX 格式验证 | ✗ |
| `write_paper_iterative` | 端到端驱动整篇论文的 起草 → 反思修订 → 编译 循环；章节级的撰写、评审与改写都是本工具内部的步骤，不再是单独的 MCP 工具 | ✓ |
| `review_compiled_paper` | 对已编译 PDF 进行最终的 rubric 评审（图表委托 VLM） | ✓ |
| `finalize_paper_build` | 确定性地封口一次论文 build：把 tex / bib / pdf / 编译记录 / 图表清单 / claim 链接 / 硬门 / 三类评审锁进一份 `PaperBuildV1`；未达 `finalized` 时以 blocking_reasons 报错 | ✗ |
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
| `build_reproduce_sh` | `container_image`（替代旧版 `apptainer_image`，后者已从签名中删除——`container_image` 是唯一的镜像参数，且只被 `apptainer` rollout 采用） |

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
| `render_figure` | 渲染一份规范的 `FigureSpecV1`，不执行调用方提供的任何代码 | ✗ |
| `generate_figures` | 从原生 `ScienceDataV1` 生成确定性的默认 spec 并渲染 | ✗ |
| `generate_figures_llm` | 让 LLM 只挑选被准入的字段（`metric_id` / `chart_type` / `x_mode`），数值、单位、caption、路径与产物字节仍由固定渲染器确定性产出 | ✓ |

## ari-skill-replicate — 规范自动生成（v0.7.0）

| 工具 | 用途 | LLM |
|---|---|:---:|
| `generate_rubric` | 两阶段（骨架 + 子树）PaperBench 规范合成 | ✓ |
| `audit_rubric` | LLM 审核叶节点中模糊/不可验证/重复的标准 | ✓ |
| `suggest_target_leaf_count` | 按论文长度估算目标叶数与词数（供 GUI Wizard "Target leaves" 字段预填） | ✗ |

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

`mcp.json` 由 `skill.yaml` 生成并列出下面五个名字；参数与返回结构以 `src/server.py`
中的 `@mcp.tool()` 装饰器为准。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `nodes_to_science_data` | 遍历 BFTS 树，提取方法论 + 发现 | ✓ |
| `generate_ear` | 从 BFTS 产物构建 `{checkpoint}/ear/` | ✗ |
| `curate_ear` | 将 `ear/` 提升为 `ear_published/` + manifest.lock | ✗ |
| `publish_ear` | 推送到 `local-tarball` / `ari-registry` / `zenodo` / `gh` | ✗ |
| `promote_ear` | `staged` → `unlisted` / `public` | ✗ |

## ari-skill-vlm — 图表 / 表格评审（VLM）

`mcp.json` 由 `skill.yaml` 生成并列出下面三个名字。评审对象都必须来自已校验的
产物：图表按 `figure_id` 从 `FigureBatchV1` 中选出，表格则是封闭 workspace 下按
内容寻址的产物。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `review_figure` | 按 `figure_id` 从已校验的 `FigureBatchV1` 中选出一张图评审 | ✓（视觉） |
| `review_figures_all` | 批量评审该 batch 中的每一张图，逐图保留失败与原始证据（受 `budget` 的并发 / 图数 / token 上限约束） | ✓（视觉） |
| `review_table` | 按封闭 schema 评审一份内容寻址的表格产物 | ✓（视觉） |

## ari-skill-web — 搜索 + 获取

| 工具 | 用途 | LLM |
|---|---|:---:|
| `web_search` | DuckDuckGo（无需 API 密钥），走与检索工具相同的 record / replay 契约 | ✗ |
| `fetch_url` | URL → 可读文本，经 pinned-IP 的 SSRF 与重定向管控 | ✗ |
| `search_papers` | 检索**一个**钉定的学术 provider（`semantic-scholar` / `arxiv` / `alphaxiv`，由 `provider` 参数或 `ARI_RETRIEVAL_BACKEND` 选定）并返回 `RetrievalRecordV1`。`record` / `live` 绝不在中途换 provider，`replay` 不做任何网络访问且需要先前 record 返回的 `snapshot_ref`；复合选择（`both`）被显式拒绝——请发两次钉定调用再按 alias 合并 | ✗ |
| `walk_citations` | 从种子 paper id 出发、带环检测与请求预算上限的 Semantic Scholar 引用图遍历（`direction` 取 `references` / `citations`） | ✗ |
| `rerank_retrieval_records` | 显式的随机性重排：LLM 按研究问题对已检索的记录重新排序（确定性检索路径绝不调用它），并记录 model / prompt digest / 输入输出 digest | ✓ |
| `list_uploaded_files` | 列出检查点 `uploads/` 下用户上传的文件 | ✗ |
| `read_uploaded_file` | 按文件名读取上传文件的文本内容（带二进制检测） | ✗ |

## ari-skill-knowledge — 只读的 Knowledge 表面

这个沿用旧命名的包是一个 Capability Provider，只对 ARI Knowledge Skill
Registry 暴露查询和不具权威的请求。它无法注册、晋升、吊销 Knowledge Skill，
也无法改写 lock 或激活某个 Knowledge Skill；固定的 `knowledge_binder_v1`
仍然是唯一权威。

| 工具 | 用途 | 具权威 |
|---|---|:---:|
| `search_knowledge_skills` | 检索非可执行的过程性知识；结果不授予任何工具权限 | 否 |
| `describe_knowledge_skill` | 按 `skill_id` 把一个内容寻址的 Knowledge Skill 描述为 untrusted 的指令数据 | 否 |
| `list_active_knowledge_skills` | 读取本次运行不可变的 active epoch Knowledge lock | 否 |
| `request_knowledge_skill` | 生成面向下一个 epoch 的选择请求，只有固定的 Knowledge Binder 可以准入 | 否 |

## ari-skill-harness — 只读的 Assurance 表面

该包只暴露 Harness 的检索、证据读取与辅助验证请求。它既不是 Harness
Resolver 也不是 Fixed Verifier，agent 的工具选择既选不出权威套件，也执行不了
已锁定的验证运行。

| 工具 | 用途 | 具权威 |
|---|---|:---:|
| `search_harnesses` | 检索独立验证定义；不会因此选中任何 Harness | 否 |
| `describe_harness` | 按 `harness_id` 描述一个 Harness 及其声明的 assurance scope | 否 |
| `request_auxiliary_verification` | 提出附加性的属性验证请求；固定的解析过程仍留在内部 | 否 |
| `read_attestation` | 按完整 SHA-256 读取一份不可变、绑定目标的 Attestation | 否 |
| `list_verification_requirements` | 从不可变的 Verification Contract 读取要求 | 否 |

这两个包都不暴露注册、晋升、吊销、lock 改写、容差 / 预言机替换或
`force_pass`。目录管理是需要人工认证的 CLI / PR 流程。

## ari-skill-tool-registry — 大型 MCP collection 的经纪表面

五个联邦操作代表整个上游 collection，因此哪怕 collection 有数千个 leaf，
agent 付出的也只是五个工具位而非数千个。leaf provider 的 schema 绝不会经由
`tools/list` 暴露。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `discover` | 以 `lexical` / `exact` / `diverse` 策略检索不可变的联邦目录。返回有界摘要与不透明的 `tool_ref`，`top_k` 上限 25，翻页通过 `constraints.cursor`；它不执行任何候选 | ✗ |
| `describe` | 对恰好一个 `tool_ref` 分页读取描述符的某个 `section`（`summary` 默认 / `schema` / `provenance` / `admission` / `limitations` / `all`）。provider 的文本与 schema 均按 untrusted 数据处理 | ✗ |
| `invoke` | 以不可变的 `tool_ref` 在 `live`（默认）/ `record` / `replay` 模式调用一个已准入的 leaf；裸名或非限定名会被拒绝 | ✗ |
| `get_status` | 用绑定在不可变描述符中的生命周期操作轮询异步的 registry `handle` | ✗ |
| `get_result` | 取回异步 registry `handle` 的最终规范化结果 | ✗ |

`invoke` / `get_status` / `get_result` 声明了 run 作用域的 context 要求，因此
它们的输入 schema 声明了 `ari_context`——与上文 `measure_counters` 相同的注入
规则，由 transport 填入，并非 agent 需要提供的参数。目录 identity、准入级别与
provider adapter 参见 [tool_registry.md](tool_registry.md)。

## 另请参阅

- `docs/zh/reference/skills.md` — 每个技能的叙述说明（职责、环境变量、示例）。
- `docs/zh/reference/tool_registry.md` — `ari-skill-tool-registry` 五个操作的目录 identity、准入与 provider adapter。
- `docs/zh/reference/knowledge_capability_assurance.md` — 三层 identity、准入、lock 与扩展门。
- `docs/zh/reference/environment_variables.md` — 逐变量环境变量参考。
- 各技能的 `mcp.json` — 规范工具名称列表。
- 各技能 `src/server.py` 中的 `@mcp.tool()` / `@server.list_tools()` — 规范参数签名。
