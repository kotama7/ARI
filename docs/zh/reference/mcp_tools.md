---
sources:
  - path: ari-skill-benchmark/src/server.py
    role: implementation
  - path: ari-skill-benchmark/mcp.json
    role: config
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-evaluator/src/server.py
    role: implementation
  - path: ari-skill-evaluator/mcp.json
    role: config
  - path: ari-skill-harness/src/server.py
    role: implementation
  - path: ari-skill-harness/mcp.json
    role: config
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-idea/src/server.py
    role: implementation
  - path: ari-skill-idea/mcp.json
    role: config
  - path: ari-skill-knowledge/src/server.py
    role: implementation
  - path: ari-skill-knowledge/mcp.json
    role: config
  - path: ari-skill-memory/src/server.py
    role: implementation
  - path: ari-skill-memory/mcp.json
    role: config
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
  - path: ari-skill-paper/src/server.py
    role: implementation
  - path: ari-skill-paper/mcp.json
    role: config
  - path: ari-skill-plot/src/server.py
    role: implementation
  - path: ari-skill-plot/mcp.json
    role: config
  - path: ari-skill-replicate/src/server.py
    role: implementation
  - path: ari-skill-replicate/mcp.json
    role: config
  - path: ari-skill-tool-registry/src/server.py
    role: implementation
  - path: ari-skill-tool-registry/mcp.json
    role: config
  - path: ari-skill-transform/src/server.py
    role: implementation
  - path: ari-skill-transform/mcp.json
    role: config
  - path: ari-skill-vlm/src/server.py
    role: implementation
  - path: ari-skill-vlm/mcp.json
    role: config
  - path: ari-skill-web/src/server.py
    role: implementation
  - path: ari-skill-web/mcp.json
    role: config
  - path: ari-core/tests/fixtures/contracts/mcp_tools.json
    role: test
last_verified: 2026-08-17
---

# MCP 工具参考

ARI 附带 17 个 MCP 服务器（每个 `ari-skill-*` 包各一个）。其中 13 个由 `ari-core/config/workflow.yaml` 的 `skills:` 默认注册，`ari-skill-orchestrator` 作为独立进程为外部客户端启动，其余 `ari-skill-knowledge` / `ari-skill-harness` / `ari-skill-tool-registry` 不在默认 `skills:` 列表中。本页是智能体可调用的所有工具的平铺目录。每个技能的深入介绍位于其各自的 `README.md`；[skills.md](skills.md) 按职责对它们进行分组。

这些 `ari-skill-*` 包是可执行的 **Capability Provider**，而不是 Knowledge Skill；MCP 只是它们的传输 / 发现协议。不可执行的过程性知识、capability binding 与独立验证是各自独立的契约，见 [Knowledge, Capability, and Scientific Assurance](knowledge_capability_assurance.md)。

对 v1 Provider 包而言，工具 identity / schema 的锁定出处是 `skill.yaml` 加上实时的 `tools/list`。`mcp.json`（位于各技能的 `pyproject.toml` 旁边）是遗留的、包内局部的兼容元数据：它由 `scripts/sync_skill_metadata.py --write` 从 `skill.yaml` 生成，是一份只读视图（`ari.skill_manifest.legacy_mcp_document`），只携带工具*名称*。被 `@mcp.tool()` 装饰的函数（或旧版技能的 `@server.list_tools()` 中的条目）定义了参数和返回结构。三者必须一致——`scripts/check_skill_manifests.py` 会在漂移时失败；每个技能的工具名清单被快照钉定在 `ari-core/tests/fixtures/contracts/mcp_tools.json`。

"LLM" 列标记了**P2 例外**工具 — 它们会调用 LLM，因此不是字节确定性的。

## ari-skill-benchmark — 统计 + 运行比较（确定性）

三个工具都只接受一个 `request` 对象，并都返回 `AnalysisResultV1`。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `analyze_results` | 按 `AnalysisRequestV1` 汇总带单位的 `MetricSampleSetV1` 数据集（inline observations，或封闭 workspace 中一列按 digest 绑定的 CSV / JSON / npy），给出摘要统计、置信区间与独立性状态 | ✗ |
| `statistical_test` | 按 `StatisticalTestRequestV1` 运行预先声明的检验族（`auto` / `welch_t` / `student_t` / `paired_t` / `mann_whitney` / `wilcoxon`），附效应量与多重比较校正（`none` / `bonferroni` / `holm` / `benjamini_hochberg`；比较多于一个而 `correction` 仍为 `none` 时会被拒绝） | ✗ |
| `compare_runs` | 按 `RunComparisonRequestV1` 把标量 `RunRecordV1` 与 baseline 比较排名，并报告环境可比性、provenance 差异，以及 replicate 独立性是 `declared` 还是 `not-established`。`require_compatible_environment=true`（默认）拒绝为环境不同的 run 排名，相同 backend/environment 只记为共享 substrate，不推断为独立 replicate | ✗ |

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
| `emit_results` | 写出一份把 `params` 与 `measurements` 分开的类型化 `results.json`（`MeasurementSetV1`）（可选 `provenance` 参数 → 记录在每条 measurement record 上，并以 `_provenance` 映射的形式送达 claim-evidence 门）。当输出的某个键在字面上像某个必需证据名时，响应的 `contract_warnings` 可能带上仅供参考的 "POSSIBLE name matches" 提示 —— 纯属建议：不会自动绑定，门也从不消费它们 | ✗ |
| `read_file` | 读取智能体之前写入的文件 | ✗ |

## ari-skill-evaluator — 指标契约 + 声明门

| 工具 | 用途 | LLM |
|---|---|:---:|
| `make_metric_spec` | 从不可变的、idea 拥有的 `ResearchContractV1`，或从一位具名 `reviewer` 已准入的 proposal，物化出运行级的指标契约，并把该 projection 持久化到 `{checkpoint}/metric_contract.json`。mint-once：若已持久化的 projection 其 `projection_digest` 与新的不同，那是一次拒绝，而不是覆盖。两者都没有而正规的 `metric_contract.json` 已存在时，不再重新抽取，直接以 `contract_frozen: true` 返回它。没有任何已准入契约时，调用仍返回 `experiment.md` 的 parser 输出，但只作为证据 —— `contract_frozen: false` / `admission_status: "human-review-required"` / `proposal_tool: "propose_metric_contract"` | ✗ |
| `propose_metric_contract` | 显式请求的 LLM 提案步骤：读取 idea（`idea_json`，或 `{checkpoint}/idea.json`），产出一份 `requires_human_review: true` 的 `MetricContractProposalV1` → `{checkpoint}/metric_contract_proposal.json`。它从不准入自己的输出，并且会拒绝已经带有类型化 `ari.research-contract/v1` 契约的 idea | ✓ |
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
| `probe_platform_capabilities` | 在**计算分区上**探测工具可用性（`command -v`）并缓存到 `{checkpoint}/platform_capabilities.json`；尽力而为（任何探测失败都报告为 skipped 且不写入） | ✗ |
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
| `mint_contract_for_proposal` | 为并非本技能生成的 proposal 铸造类型化的 `ari.research-contract/v1`——RQGM proposal router 的候选据此抵达 KCA 准入。宁可拒绝也不臆造：未设置 `ARI_CHECKPOINT_DIR`、调研快照不可用、或 proposal 没有标题，都会返回 `contract_status: "rejected"` | ✓ |

`_load_virsci_snapshot_papers` 只是
`survey` 直接调用的普通辅助函数，绝不对 agent 可见；
`ari-skill-idea/tests/test_server.py` 通过 `mcp.list_tools()` 钉住
`survey` 与 `generate_ideas` 已注册、且该辅助函数未注册这两点。
`mint_contract_for_proposal` 与另外两个一样，`skill.yaml` 与 `mcp.json` 都已
写入，因此 `scripts/check_skill_manifests.py` 不会把该包报为
`tool-drift`。provider 之间没有回退：`virsci-snapshot` 的调研在语料库缺失时抛出
`FileNotFoundError`，Semantic Scholar 的调研遇到 HTTP 错误时直接抛出——故障
时得到的是一次拒绝，而不是悄悄变成另一份语料库。
`survey` 与 `generate_ideas` 也是 RQGM `VirSciAdapter` 背后的 MCP 表面：在可选启用的
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

这里的工具都不调用 LLM。不过 `ari-skill-memory/README.md` 的 § Determinism (P2)
记录了：v0.5.x 的"无 LLM 调用、完全确定性"声明在 v0.6.0 已被放宽 —— Letta 的
embedding search 在版本之间不是 bit-reproducible，因此改为对存储的 `text`
字节做 CoW 保护。

不存在破坏性的 clear。没有任何 agent 可见的操作会丢弃条目，
`ari-skill-memory/tests/test_cow.py` 用
`assert not hasattr(server, "clear_node_memory")` 钉住了这一缺席。要缩减某个节点
的记忆，请用 `consolidate_node_memory` 写一条汇总后的类型化条目 —— 它由该节点的
`node_report` 导出，本身也被 CoW 约束在当前节点上。当 ARI 的 governance 逻辑
擦除某个节点时，记录仍会返回，只是带上 `erased` / `erasure_event_id` /
`erasure_note` 标签，绝不会被悄悄丢掉。

## ari-skill-orchestrator — 递归 ARI 运行器

每个工具都针对调用方 principal 做授权；读取类工具返回的是按 digest 寻址的引用，
而不是文件系统路径。十二个工具都以 `{"error": {"code", "message"}}` 信封而不是
异常来返回错误，`code` 取 `invalid_request` / `forbidden` / `not_found` /
`idempotency_conflict` / `quota_exceeded` / `artifact_policy` /
`authentication_failed` / `orchestrator_error` / `internal_error` 之一。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `run_experiment` | 在显式的 `idempotency_key` 与配额块（`max_nodes` / `max_total_nodes` / `max_descendant_runs` / `max_cost_usd` / `timeout_minutes`）下幂等地提交一次子 ARI 运行，返回其持久句柄 | ✗ |
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
| `list_venues` | 可用 LaTeX 模板（ACM / NeurIPS / SC / ICPP / ISC / arXiv） | ✗ |
| `get_template` | 获取某 venue 的模板 | ✗ |
| `compile_paper` | 把 LaTeX 工程编译为 PDF，并在 `.ari-paper/compile/final.json` 留下编译记录 | ✗ |
| `check_format` | 按 venue 的排版要求（页数等）验证 PDF。页数无法判定时同样记为 `ok: false`，不把"未验证"读成通过 | ✗ |
| `write_paper_iterative` | 一次调用填满整份 venue 模板的 `FILL_*` 块，随后在同一段消息历史上跑 `max(1, max_revision_rounds)` 轮反思（设为 0 或负数也不会跳过反思，仍跑 1 轮）。没有章节级的工具：起草与改写都是本工具内部的阶段；返回 `latex` / `sections` / `reviews` / `revision_counts` / `paper_build` | ✓ |
| `review_compiled_paper` | 对已编译 PDF 进行最终的 rubric 评审（图表委托 VLM） | ✓ |
| `finalize_paper_build` | 把确切的证据集 —— tex / bib / PDF / 编译记录 / 图表清单 / claim 链接 / 硬门 / 文本·视觉·语义三类评审 —— 锁进 `output_path` 处的一份 `PaperBuildV1`；build 未达 `finalized` 时报错并列出 `blocking_reasons` | ✗ |
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
| `run_reproduce` | `container_image`（docker / apptainer / singularity 沙箱必填，其余沙箱则拒收）。v1.0 只接受不可变引用：本地的非符号链接 SIF、完整的 `sha256:<image-id>`，或以 `name@sha256:<digest>` 固定的 URI —— 可变的 `pb-env` / `pb-reproducer` `:latest` 别名已被删除 |

高声失败的前置条件：`sandbox_kind=slurm` 而 `sbatch` 不在 PATH 上，或无法从参数、`ARI_SLURM_PARTITION`、`launch_config.json` 中解析出分区时，抛出 `RuntimeError`，而不是静默回退到本地执行；容器沙箱缺少运行时二进制文件，或 `container_image` 为空或可变时，抛出 `ReproductionContractError`。v1.0 已删除 host-local 回退，因此没有恢复开关。详见 [environment_variables.md](environment_variables.md#paperbench-复现阶段-stage-2)。GPU 请求同样不能混用两种形式：per-node 与 per-task 的 GPU 数互斥。但缺少数量的 `gpu_type` 在本表面上不会被拒绝——SLURM 执行路径在构造资源请求之前会补上 per-node 1 个 GPU，因此底层「`gpu_type` 需要显式 GPU 数量」的规则经由 `run_reproduce` 永远不会触发。

### v0.8.0 新增字段（Stage 3）

| 工具 | 新增参数 |
|---|---|
| `grade_with_simplejudge` | `code_only`（将 rubric 裁剪为仅 Code Development 叶节点，镜像 vendor `paperbench/grade.py:109-112`）。默认为 `False`，且不会被自动打开 —— 过去在缺少 `reproduce.log` 时自行启用的隐式 `code_only` 评分已在 v1.0 删除 |

关于以单一调用词汇将全部三个阶段串联起来的进程内 Python 接口，请参阅 [`api_paperbench.md` § Bridge 合约](api_paperbench.md#bridge-契约-in-process-python-接口)。

## ari-skill-plot — 图表生成

| 工具 | 用途 | LLM |
|---|---|:---:|
| `render_figure` | 把一份规范的 `FigureSpecV1` 渲染进封闭 workspace 并返回其 manifest。请求对象恰好是 `spec` + `workspace` + `relative_directory`，不执行调用方提供的任何代码 | ✗ |
| `generate_figures` | 从原生 `ScienceDataV1` 生成确定性的默认 spec 并渲染。`revision` 必须为 `0` —— 确定性路径没有反馈轮 | ✗ |
| `generate_figures_llm` | 让 LLM 只挑选 `metric_id` / `chart_type` / `x_mode`，数值、单位、caption、路径与产物字节都经由同一个固定渲染器从已校验的科学记录产出。`revision > 0` 同时要求一份 `vlm_feedback` 文档和它所绑定的 `previous_batch_path` | ✓ |

## ari-skill-replicate — 规范自动生成（v0.7.0）

| 工具 | 用途 | LLM |
|---|---|:---:|
| `generate_rubric` | 两阶段（骨架 + 子树）PaperBench 规范合成 | ✓ |
| `audit_rubric` | LLM 审核叶节点中模糊/不可验证/重复的标准 | ✓ |
| `suggest_target_leaf_count` | 返回 `{target, word_count}` —— 即 `generate_rubric` 对该论文会自动算出的叶数，好让调用方预填而不是猜（供 GUI Wizard "Target leaves" 字段预填） | ✗ |

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

`paper_audit` 模板必须声明非空的 `top_level_axes`，否则加载会被拒绝。这里没有单次路径可供选择——生成始终是 skeleton + subtree 的两阶段流程，其中 `system_hint` 注入 skeleton 阶段，`leaf_style` 注入 subtree 阶段。YAML schema 和撰写指南请参见 [`rubric_schema.md`](rubric_schema.md#venue-条件化模板-venue-conditioned-templates)。

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
内容寻址的产物，绝不是一条松散路径；判据 profile 带版本（默认
`figure-publication/v1`）。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `review_figure` | 按 `figure_id` 从已校验的 `FigureBatchV1` 中选出一张图评审；batch 里没有的 ID 会被拒绝 | ✓（视觉） |
| `review_figures_all` | 在 `ReviewBudgetV1`（`max_figures` / `max_total_bytes` / `max_concurrency` / `max_model_calls` / `max_output_tokens`）下评审该 batch 中的每一张图；失败的图不会抛出，而是各自留成 `limit-error` / `artifact-error` 评审并保留原始证据。但批次聚合是 `minimum-fail-closed` —— 只要有一条失败，批次 `score` 就是 `0.0`；全部完成时取各图分数的最小值 | ✓（视觉） |
| `review_table` | 在封闭 workspace 下评审一份内容寻址的表格产物。请求 schema 是精确的 —— `workspace`、`target_id`、`artifact`、`context`、`criteria_profile_id`、`iteration`（0–2）、`max_output_tokens` —— 不受支持的 media type 会以 `artifact-error` 评审的形式返回 | ✓（视觉） |

## ari-skill-web — 搜索 + 获取

检索是一份契约，而不是每个 provider 一个工具。每个联网工具都接受 `mode` ——
`record`（默认；抓取并留快照）、`live`（抓取但不留快照）、`replay`（完全不访问
网络，需要先前一次 record 返回的、相对检查点的 `snapshot_ref`）—— 并返回
`RetrievalRecordV1` 行。`record` 与 `replay` 都要求 `ARI_CHECKPOINT_DIR`。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `web_search` | DuckDuckGo（无需 API 密钥），`n` 被夹到 1–10 | ✗ |
| `fetch_url` | URL → 可读文本，经 pinned-IP 的 SSRF 与重定向管控 | ✗ |
| `search_papers` | 检索**一个**钉定的学术 provider（`semantic-scholar` 默认 / `arxiv` / `alphaxiv`，由 `provider` 参数或 `ARI_RETRIEVAL_BACKEND` 选定）并返回 `RetrievalRecordV1`。`record` / `live` 绝不在中途换 provider，`replay` 不做任何网络访问且需要先前 record 返回的 `snapshot_ref`；既没有按 provider 分立的工具，也没有复合工具：`provider="both"` 被显式拒绝，并提示改为发两次钉定调用再按 alias 合并 | ✗ |
| `walk_citations` | 从种子 paper id 出发、带环检测的 Semantic Scholar 引用图遍历，`direction` 取 `references` 或 `citations`，上限为 `max_depth`（≤5）、`max_nodes`（≤500）与 `request_budget` | ✗ |
| `rerank_retrieval_records` | 显式的随机性重排：LLM 按研究问题对已检索的 `RetrievalRecordV1` 行重新排序（确定性检索路径绝不调用它），结果携带产生该顺序的 model、prompt digest、输入 digest 与输出 digest | ✓ |
| `list_uploaded_files` | 以 `{name, size_bytes}` 列出检查点 `uploads/` 下用户上传的文件 | ✗ |
| `read_uploaded_file` | 按文件名读取上传文件的文本内容（带二进制检测） | ✗ |

检索后端按调用或按环境变量选择；没有任何工具会为整个进程改写它，因此两个并发的
调用方不会互相改掉对方的 provider（`ari-core/tests/test_retrieval_backend.py::test_mutable_retrieval_backend_tool_is_removed`
钉住了这一缺席）。

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
`force_pass`。目录管理是需要人工认证的 CLI / PR 流程。详见
[Knowledge, Capability, and Scientific Assurance](knowledge_capability_assurance.md)。

## ari-skill-tool-registry — 大型 MCP collection 的经纪表面

六个联邦操作代表整个上游 collection，因此哪怕 collection 有数千个 leaf，
agent 付出的也只是六个工具位而非数千个。leaf provider 的 schema 绝不会经由
`tools/list` 暴露。

| 工具 | 用途 | LLM |
|---|---|:---:|
| `discover` | 以 `lexical` / `exact` / `diverse` 策略检索不可变的联邦目录。返回有界摘要与不透明的 `tool_ref`，`top_k` 上限 25，翻页通过 `constraints.cursor`；它不执行任何候选 | ✗ |
| `describe` | 对恰好一个 `tool_ref` 分页读取描述符的某个 `section`（`summary` 默认 / `schema` / `provenance` / `admission` / `limitations` / `all`）。provider 的文本与 schema 均按 untrusted 数据处理 | ✗ |
| `invoke` | 以不可变的 `tool_ref` 在 `live`（默认）/ `record` / `replay` 模式调用一个已准入的 leaf；裸名或非限定名会被拒绝 | ✗ |
| `invoke_scheduled` | 对向调度器提交作业的 leaf 执行同一操作。之所以单列一个表面：Provider 的副作用等级跟随其权限，若把调度器权限挂在共享表面上，经该表面派发的每个 leaf 权限包络都会被抬高 | ✗ |
| `get_status` | 用绑定在不可变描述符中的生命周期操作轮询异步的 registry `handle` | ✗ |
| `get_result` | 取回异步 registry `handle` 的最终规范化结果 | ✗ |

`invoke` / `invoke_scheduled` / `get_status` / `get_result` 声明了 run 作用域的
context 要求，因此它们的输入 schema 声明了 `ari_context`——与上文
`measure_counters` 相同的注入规则，由 transport 填入，并非 agent 需要提供的
参数。此外，本包的 `mcp.json` 已从 skill.yaml 重新生成，六个名字（含
`invoke_scheduled`）全部列出，因此 `scripts/check_skill_manifests.py` 不会报
`compat-metadata-drift`。目录 identity、准入级别与
provider adapter 参见 [tool_registry.md](tool_registry.md)。

## 另请参阅

- `docs/zh/reference/skills.md` — 每个技能的叙述说明（职责、环境变量、示例）。
- `docs/zh/reference/tool_registry.md` — `ari-skill-tool-registry` 六个操作的目录 identity、准入与 provider adapter。
- `docs/zh/reference/knowledge_capability_assurance.md` — 三层 identity、准入、lock 与扩展门。
- `docs/zh/reference/environment_variables.md` — 逐变量环境变量参考。
- 各技能的 `mcp.json` — 规范工具名称列表。
- 各技能 `src/server.py` 中的 `@mcp.tool()` / `@server.list_tools()` — 规范参数签名。
