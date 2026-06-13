---
sources:
  - path: ari-core/ari/orchestrator
    role: implementation
  - path: ari-core/ari/agent/loop.py
    role: implementation
  - path: ari-core/ari/pipeline
    role: implementation
  - path: ari-core/ari/evaluator/llm_evaluator.py
    role: implementation
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-06-10
---

# ARI 架构

## ARI 做什么

ARI 是一个端到端的自主研究系统。给定一个纯文本研究目标，它会：

1. **调研**先前的工作（学术数据库）
2. **生成**研究假设，通过多智能体讨论（VirSci）
3. **搜索**最佳实验配置，使用最佳优先树搜索（BFTS）
4. **执行**真实实验，在您的硬件上运行（笔记本电脑、SLURM、PBS、LSF）
5. **评估**每个实验，以同行评审者的角色（LLM 分配科学质量评分）
6. **分析**完整的实验树：提取硬件上下文、方法论、消融实验发现
7. **生成**出版级质量的图表（LLM 根据数据编写 matplotlib 代码）
8. **撰写**完整的 LaTeX 论文及引用
9. **审阅**论文，LLM 充当审稿人
10. **验证**可复现性：仅根据论文文本重新运行实验

系统不包含硬编码的领域知识。同一流水线适用于 HPC 基准测试、ML 超参数调优、化学优化或任何可测量的现象。

---

## 流水线一览

端到端流程 —— 想法生成、BFTS 探索循环、由 `workflow.yaml` 驱动的
post-BFTS 流水线（write_paper 之后现在默认接一条 Story2Proposal 的
claim-evidence 尾链），以及与 PaperBench 兼容的 ORS 可复现性检查 ——
汇成一张枢纽图。每个分组都链接到深入讲解它的章节或文档。

```mermaid
flowchart TB
    exp["experiment.md<br/>(研究目标，至少 3 行)"]
    exp --> survey["survey —— 先行研究调查"]
    survey --> ideas["generate_ideas<br/>VirSci → 假设 + primary_metric"]
    ideas --> bfts

    subgraph bfts["BFTS —— 最佳优先树搜索"]
        direction LR
        expand["expand（一个子节点）"] --> run["ReAct 节点运行<br/>（在你的硬件上跑真实实验）"]
        run --> eval["LLMEvaluator<br/>_scientific_score"]
        eval --> expand
    end

    bfts --> tree["nodes_tree.json"]

    subgraph post["post-BFTS 流水线（workflow.yaml）"]
        direction TB
        transform["transform_data → science_data.json"]
        figures["generate_figures → VLM 评审"]
        paper["write_paper → review_paper<br/>（集成 + Area Chair 元评审）"]
        claimtail["claim-evidence 尾链（Story2Proposal）:<br/>link_paper_claims → claim_evidence_hard_gate<br/>→ evidence_grounded_semantic_review → merge_reviews<br/>→ paper_refine → render_paper → finalize_paper"]
        ear["generate_ear → curate → publish（EAR）"]
        transform --> figures
        transform --> ear
        figures --> paper
        ear --> paper
        paper --> claimtail
    end

    tree --> post

    subgraph ors["ORS 可复现性 —— 兼容 PaperBench，两个阶段"]
        direction LR
        rubric["ors_generate_rubric"] --> p1["Phase 1 run_reproduce<br/>slurm / docker / apptainer / local"]
        p1 --> p2["Phase 2 grade_with_simplejudge<br/>+ 负例对照"]
    end

    post --> ors
```

| 分组 | 作用 | 进一步阅读 |
|------|------|-----------|
| survey / generate_ideas | 文献检索 + VirSci 确定假设与主指标 | [完整数据流](#完整数据流) |
| BFTS | 对实验配置进行最佳优先树搜索 | [BFTS 算法](bfts.md) |
| ReAct 节点运行 | 运行真实实验的逐节点代理循环 | [节点级提示构建](#节点级提示构建) |
| LLMEvaluator | 驱动排序的同行评审打分 | [配置 → BFTS 评估层](../reference/configuration.md#bfts-评估层-可通过配置切换) |
| 记忆 | 在节点间传递的祖先作用域知识 | [记忆架构](memory.md) |
| post-BFTS 流水线 | 数据 → 作图 → 写作 → 评审 → EAR | [出版生命周期](publication-lifecycle.md) |
| ORS 可复现性 | 从论文从零复现并打分 | [PaperBench 快速开始](../guides/paperbench/paperbench_quickstart.md) |

---

## 系统概览

```
┌────────────────────────────────────────────────────────────────┐
│                         User Interface                         │
│                   experiment.md  /  CLI  /  API                │
└────────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────────┐
│                          ari-core                              │
│                                                                │
│  ┌─────────────────┐   ┌─────────────────┐                    │
│  │  BFTS           │   │  ReAct Loop     │                    │
│  │  (tree search)  │──▶│  (per node)     │                    │
│  └─────────────────┘   └────────┬────────┘                    │
│                                 │                              │
│  ┌──────────────────────────────▼──────────────────────────┐  │
│  │            MCP Client (async tool dispatcher)           │  │
│  └──────────────────────────────┬──────────────────────────┘  │
└─────────────────────────────────┼──────────────────────────────┘
                                  │ MCP protocol (stdio/HTTP)
     ┌────────────────────────────┼──────────────────────────────┐
     │                            │                              │
┌────▼──────────┐  ┌─────────────▼──────┐  ┌───────────────────▼──┐
│ari-skill-hpc  │  │ari-skill-idea      │  │ari-skill-evaluator   │
│ slurm_submit  │  │ survey             │  │ make_metric_spec     │
│ job_status    │  │ generate_ideas     │  │ (scientific_score)   │
│ run_bash      │  │ (VirSci MCP)       │  │                      │
└───────────────┘  └────────────────────┘  └──────────────────────┘

Post-BFTS Pipeline (workflow.yaml):
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ari-skill-       │  │ari-skill-plot    │  │ari-skill-paper   │
│transform        │  │ generate_figures │  │ write_paper      │
│ nodes_to_       │  │ _llm (LLM writes │  │ review_compiled  │
│ science_data    │  │  matplotlib)     │  │ reproduce_from   │
│ (LLM analysis)  │  │                  │  │  _paper          │
└─────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## 完整数据流

```
experiment.md
  (仅包含研究目标 — 最少 3 行)
    │
    ▼
[ari-skill-idea: survey]
  arXiv / Semantic Scholar 关键词搜索
  返回：相关论文摘要
    │
    ▼
[ari-skill-idea: generate_ideas]  ← VirSci 多智能体讨论
  多个 AI 角色就研究问题进行辩论
  输出：hypothesis、primary_metric、evaluation_criteria
    │
    ▼
BFTS 根节点创建
    │
    ▼ (对每个节点重复，最多 ARI_MAX_NODES 个，ARI_PARALLEL 个并发)
┌──────────────────────────────────────────────────────────────────┐
│  ReAct Loop (ari/agent/loop.py)                                  │
│                                                                  │
│  1. LLM 从 MCP 注册表中选择工具                                    │
│  2. 工具执行（run_bash / slurm_submit / job_status / ...）         │
│  3. 如果是 SLURM 作业：自动轮询直到 COMPLETED（无步骤预算限制）       │
│  4. LLM 读取 stdout → 生成实验代码 → 提交                          │
│  5. LLM 从输出中提取指标 → 返回 JSON                               │
│                                                                  │
│  记忆：结果摘要保存到祖先链记忆中                                    │
│  子节点：搜索祖先记忆以获取先前结果                                  │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
[LLMEvaluator] (ari/evaluator/llm_evaluator.py)
  输入：节点产物（stdout、日志、脚本）
  输出：{
    has_real_data: bool,
    metrics: {key: value, ...},       ← 提取的数值
    scientific_score: float 0.0-1.0,  ← LLM 同行评审质量分
    comparison_found: bool             ← 是否与现有方法进行了比较？
  }
  _scientific_score 存储在 metrics 中 → 驱动 BFTS 排名
  AUTHORITATIVE measurements：节点的 results.json（位于 ARI_WORK_DIR 下）是
    ground truth。其 `measurements` 被直接合并，并对 LLM 从截断产物文本
    （str(artifacts)[:2000]）中的提取拥有 PRECEDENCE（优先权）；其中存在的
    任何数值也会将 has_real_data 置为 True。这能找回截断重读会遗漏的真实数值。
  metric_contract producer obligation：当 make_metric_spec 输出了
    metric_contract 脚手架（concept-classified 指标）时，代理会在
    make_metric_spec 时刻收到一条领域中立的义务 —— 验证正确性、对任何
    ceiling 进行 MEASURE（绝不硬编码）、emit provenance、填写 contract ——
    随后由 FINAL claim-evidence hard gate 强制执行。
    │
    ▼
BFTS expand() (ari/orchestrator/bfts.py)
  - 按 _scientific_score 对节点排名
  - 将分数传递给子节点提议 LLM
  - LLM 每次扩展调用提议 1 个子方向（改进 / 消融 / 验证 / 草稿 / 调试 / 其他）
  - 无领域提示 — LLM 决定"改进"的含义
  - v0.7.0：当父节点存在 node_report.json 时，提示词中加入 delta_vs_parent /
    self_assessment.concerns / next_steps_hints 与 files added/modified；同辈
    去重通过 filter_nodes(for_synthesis) 过滤后，连带列出每个 sibling 的
    files_changed.added，避免提议会写相同文件的方向。

每节点自报告 (v0.7.0)
  ari-core/ari/orchestrator/node_report.py 在 mark_success / mark_failed 时
  生成 node_report.json，记录：
    - files_changed (added / modified / deleted / inherited_unchanged) —
      由父子 work_dir 的 sha256 diff 推导
    - original_direction (bfts.expand 在创建子节点时保存，evaluator 不会覆写)
    - self_assessment.{succeeded, headline, concerns} — 根据 evaluator
      的 axis_rationales 派生（axis_score < 0.4 → concerns，0.4..0.7 →
      next_steps_hints，≥0.7 → 不暴露）
    - build_command / run_command — 从 work_dir 中的 run_job.sh / Makefile grep
    - artifacts[].role — 按扩展名确定性分类
    - migration_source ("fresh" 或 "auto")
  PathManager.META_FILES 包含 node_report.json，确保父→子物理 work_dir 复制
  不会让子节点继承父节点的报告。

公共选择助手 (v0.7.0)
  ari-core/ari/orchestrator/node_selection.py:
    - filter_nodes：「该节点是否传给下游」的单一实现，3 种 criteria
      (for_synthesis / for_code / for_narrative)；always_include_node_ids 让
      best 节点必通过；丢弃成功节点 >50% 时输出 warning。
    - select_source_files_for_publication：纯元数据文件级选择（无 I/O）；
      transform_data 与 generate_ear 共享同一 selection（FR-SS-5 契约测试固化）。
    - load_selected_sources(size_budget)：负责文件 I/O；transform 用 16KB cap，
      generate_ear 不限。
    │
    ▼ (达到 ARI_MAX_NODES 后)
nodes_tree.json  (所有节点：指标、产物、记忆、父子关系)
    │
    ▼
[workflow.yaml Post-BFTS 流水线]

  阶段 1：transform_data  (ari-skill-transform)
    对完整树进行 BFS 遍历（根 → 叶）
    LLM 读取所有节点产物（stdout、日志、生成的代码）
    LLM 提取：硬件规格、方法论、关键发现、比较结果
    输出：science_data.json  { configurations, experiment_context, per_key_summary }

  阶段 2：search_related_work  (ari-skill-web)  [与阶段 1 并行]
    LLM 生成的关键词 → 可插拔检索后端 (Semantic Scholar / AlphaXiv / both)
    输出：related_refs.json

  阶段 3：generate_figures  (ari-skill-plot)  [在阶段 1 之后]
    输入：完整的 science_data.json（包含 experiment_context）+ {{vlm_feedback}}
    LLM 编写完整的 matplotlib 代码 → 执行 → 保存为 PDF 图表
    图表类型由 LLM 根据数据自主选择（非预设）
    输出：figures_manifest.json

  阶段 3b：vlm_review_figures  (ari-skill-vlm)  [在阶段 3 之后]
    VLM 视觉审阅主图 (fig_1.png)
    若得分 < 0.7：携带 VLM 反馈回环到 generate_figures（最多 2 次迭代）
    输出：vlm_figure_review.json

  阶段 4：generate_ear  (ari-skill-transform)  [在阶段 1 之后]
    以 node_report 驱动的确定性 ear/ 构建。
      - code/ = best 链中 contributing 节点的 files_changed.added/modified 的 union（verbatim）
      - data/ = checkpoint/uploads/ 的 verbatim 镜像（仅输入；实验输出不打包）
      - figures/ = checkpoint 根下 *.{pdf,png,svg,jpg,jpeg} 置于顶层
      - README.md / reproduce.sh — 由 node_reports 确定性渲染
      - LICENSE — 由 publish.yaml::license SPDX 模板生成（MIT / Apache-2.0 / BSD-3-Clause / GPL-3.0 / CC-BY-4.0）
    EVOLUTION.md 和 _provenance.json 作为 ARI 审计日志写入 checkpoint 根目录
    （ear/ 之外），不会被打包进发布产物。
    transform_data 与 generate_ear 共享同一 select_source_files_for_publication，
    确保 LLM 看到的源字节与 ear/code/ 发布的字节完全一致。ARI 内部元数据
    （tree.json、science_data.json、raw_metrics.json 等）不会进入 ear/。
    输出：ear_manifest.json、ear/ 目录、checkpoint/EVOLUTION.md、
          checkpoint/_provenance.json

  阶段 5：write_paper  (ari-skill-paper)  [在阶段 2、3、4 之后]
    paper_context = experiment_context + best_nodes_metrics
    迭代式章节撰写：草稿 → LLM 审阅 → 修改（最多 2 轮）
    BibTeX 引用来自 Semantic Scholar 结果
    write_paper 还会读取 verified_context.json（由 ari/pipeline/verified_context.py
      构建——作用域限定到 best 节点的 root→best lineage 的 artifact-grounded
      claim），用于支撑其定量 claim。
    输出：full_paper.tex、refs.bib

  Story2Proposal claim-evidence 尾链  [现为默认，在 write_paper 之后]
    write_paper 之后接一条确定性的 claim/evidence 链（S2P）。
    默认拓扑为：
      link_paper_claims_draft       (核对 %CLAIM 锚点 → paper_claim_links.json)
        → claim_evidence_hard_gate_draft   (草稿 hard gate，非阻塞)
        → review_paper              (仅文本评审——下方阶段 6)
        → evidence_grounded_semantic_review
        → merge_reviews             (下方阶段 10；串入 gate + semantic review)
        → paper_refine              (应用 suggested_revisions，保留 %CLAIM 锚点)
        → render_paper              (重新编译 refined .tex → PDF；非阻塞)
        → link_paper_claims_final
        → evidence_grounded_semantic_review_post_refine
        → claim_evidence_hard_gate_final   (FINAL gate；strict 模式下阻塞 finalize)
        → finalize_paper            (下方阶段 8)
    由 workflow.yaml 顶层 claim_gate_policy 块控制
      (默认 mode: warn —— FINAL gate 非阻塞；mode: strict 在 FINAL gate
      处阻塞 finalize_paper)。解析优先级最终落到
      env ARI_CLAIM_GATE_MODE (off | warn | strict) 与 ARI_COMPARISON_SCOPE。
    繁重的 gate 逻辑位于新的 ari/pipeline/claim_gate/ 包
      (contract / gate / policy / numeric / latex / invariants / resolve)，
      evaluator-skill 暴露调用它的瘦 MCP 工具
      (claim_evidence_hard_gate, evidence_grounded_semantic_review)。
      gate 的深层语义见 publication-lifecycle.md。

  阶段 6：review_paper  (ari-skill-paper)  [在阶段 5 之后]
    规范驱动审稿。运行 N 个独立审稿人代理
    (N 由 ARI_NUM_REVIEWS_ENSEMBLE / rubric 默认值控制；N=1 为单审稿人)。
    N>1 时还会运行 Area Chair 元审稿以聚合评分。
    输出：review_report.json { score, verdict, citation_ok, feedback,
          ensemble_reviews[] (N>1), meta_review{} (N>1) }

  阶段 7：ear_curate  (ari-skill-transform: curate_ear)  [在阶段 4 之后, v0.7.0]
    依据 {checkpoint}/ear/publish.yaml 的 allowlist 与内置 deny list
    (.env*, secrets/**, *.pem, *.key, id_rsa, id_ed25519) 构建
    {checkpoint}/ear_published/ + manifest.lock；bundle_sha256 是
    正规化 {path,sha256,size} JSON 的 sha256，跨机器确定。
    publish.yaml 缺失时静默跳过。

  阶段 8：finalize_paper  (ari-skill-paper: inject_code_availability)  [在阶段 5+7 之后, v0.7.0]
    从 ear_published/manifest.lock + publish_record.json 自动加载
    ref / sha / doi，将机器可读的 \codeavailability{} / \codedigest{}
    / \coderef{} 宏与人类可读的 Code Availability 章节注入
    full_paper.tex。digest 是信任锚点，读者无需信任 registry，即可用
    `ari clone <ref> --expect-sha256 <baked-digest>` 进行验证。

  阶段 9：ear_publish  (ari-skill-transform: publish_ear)  [在阶段 7 之后, 可选]
    从 ear_published/ 构建可复现 tarball，并发布到 backend
    (ari-registry / local-tarball / gh / zenodo)。首发布始终
    visibility=staged (FR-P5)。默认禁用，可通过 workflow.yaml 中
    `enabled: true` 或运行参数 publish=true 启用。
    输出：publish_record.json

  阶段 10：review_paper / merge_reviews  (ari-skill-paper)  [在阶段 5+3b 之后]
    review_paper 仅评审论文文本 (不传入 VLM 输出与 figure manifest，
    与 AI Scientist v2 perform_review 契约一致)；merge_reviews
    将 review_report.json 与 vlm_review.json 做结构合并 (无 LLM)。
    输出：review_report.json (附 vlm_figure_review)

  阶段 11：ors_generate_rubric  (ari-skill-replicate)  [在阶段 5 之后, v0.7.0]
    从最终论文自动生成 PaperBench 形式 (TaskNode 树) rubric。
    task_category 与 finegrained_task_category 锁定到 PaperBench 封闭
    词汇 (LLM 越界由确定性归一化器纠正)；JSON 输出时清洗游离 LaTeX
    backslash escape。
    输出：ors_rubric.json + ors_rubric.meta.json

  阶段 12：ors_seed_sandbox  (ari-skill-paper-re: fetch_code_bundle)  [v0.7.0]
    从策展过的 EAR bundle 确定性播种到 repro_sandbox/ (无 LLM)。
    从 publish_record.json 自动加载 ref + sha256 (本字段由 ear_publish 写入)。
    EAR 关闭时 publish_record.json 不存在，本阶段 no-op，让下一阶段的
    LLM 回退接管。
    输出：ors_seed.json

  阶段 13：ors_build_reproduce  (ari-skill-paper-re: build_reproduce_sh)  [v0.7.0]
    LLM 驱动 replicator：读取论文 + rubric 的 expected_artifacts，
    将自包含 reproduce.sh + 源文件写入沙箱。reproduce.sh 已存在则跳过
    (放在 ors_seed_sandbox 之后即可在 EAR 开启时不触发)。LiteLLM 路由，
    供应商无关 (gpt-5-mini / anthropic/claude-... / gemini/... / ollama/...)。
    输出：ors_replicator.json + repro_sandbox/{reproduce.sh, source...}

  阶段 14：ors_run_reproduce  (ari-skill-paper-re: run_reproduce)  [在阶段 13 之后, v0.7.0]
    Phase 1。在沙箱中执行 reproduce.sh：
      slurm (sbatch + ARI_SLURM_PARTITION 存在 = BFTS 同 partition)
      → docker (守护可用且非 HPC) → apptainer → singularity → local。
      可用 ARI_PHASE1_SANDBOX 覆盖。
    SLURM 路径使用 sbatch --wait 与 spool relocation 包装器
    (.slurm_wrap.sh，通过绝对路径 exec reproduce.sh 以保护 $0 相对 cd)。
    捕获 reproduce.log，并对照 rubric 中的 expected_artifacts。
    输出：ors_phase1.json { executed, exit_code, log_path,
                             artifacts, missing, sandbox_kind,
                             [partition, cpus, walltime] }

  阶段 15：ors_grade  (ari-skill-paper-re: grade_with_simplejudge)  [在阶段 14 之后, v0.7.0]
    Phase 2。主评分 completer 通过 LiteLLM 路由 (任意供应商；绕过
    PaperBench 原生 CONTEXT_WINDOW_LENGTHS 约束)，structured score-parser
    仍使用 gpt-4o-2024-08-06。N 次 (默认 3) 加权聚合 + negative control
    (两者均需 < 5%)。
    输出：ors_grade.json { ors_score, raw_score, leaf_grades,
                          judge_model, n_runs, rubric_sha256,
                          negative_control: {empty, boilerplate, passed} }
```

---

## 文件结构

### 检查点目录布局

每次 ARI 运行都会在 `{workspace}/checkpoints/{run_id}/` 下生成检查点目录。
`run_id` 格式为 `YYYYMMDDHHMMSS_<slug>`。`ari/paths.py` 中的 `PathManager`
是目录构造的唯一真实来源。

```
checkpoints/{run_id}/
├── experiment.md               # 输入: 研究目标 (启动时复制)
├── launch_config.json          # 向导/CLI 启动参数
├── meta.json                   # 子实验元数据 (父/递归深度)
├── workflow.yaml               # 启动时流水线配置的快照
├── .ari_pid                    # 用于存活检测的 PID 文件
├── tree.json                   # 完整 BFTS 树 (BFTS 阶段写入)
├── nodes_tree.json             # 轻量树导出 (流水线输入)
├── results.json                # 每节点 artifact + metrics 摘要
├── idea.json                   # 生成的假设 (VirSci 输出)
├── evaluation_criteria.json    # 主要指标 + 方向
├── cost_trace.jsonl            # 每次 LLM 调用的成本/token 日志
├── cost_summary.json           # 成本汇总
├── ari.log                     # 结构化 JSON 日志
├── ari_run_*.log               # GUI 启动时的 stdout/stderr 日志
├── .pipeline_started           # 标记: post-BFTS 流水线已开始
├── science_data.json           # Transform-skill 输出
├── related_refs.json           # 文献搜索结果
├── figures_manifest.json       # 生成的图片元数据
├── fig_*.{pdf,png,eps,svg}     # 生成的图片
├── vlm_review.json             # VLM 图片审查输出
├── full_paper.tex              # 生成的 LaTeX 论文
├── refs.bib                    # BibTeX 引用
├── full_paper.pdf              # 编译后的 PDF
├── full_paper.bbl              # 参考文献输出
├── review_report.json          # LLM 同行评审输出 (N>1 时内联 ensemble_reviews[] 和 meta_review{})
├── reproducibility_report.json # 可复现性验证
├── uploads/                    # 用户上传的文件 (复制到节点 work_dir)
├── paper/                      # LaTeX 编辑工作区 (类 Overleaf)
│   ├── full_paper.tex
│   ├── full_paper.pdf
│   ├── refs.bib
│   └── figures/
├── ear/                        # 实验 Artifact Repository
│   ├── README.md
│   ├── RESULTS.md
│   └── <artifacts>
└── repro/                      # 可复现性运行工作区
    ├── run/
    ├── reproducibility_report.json
    └── repro_output.log
```

### 节点工作目录

每节点的工作目录作为 `checkpoints/` 的兄弟目录创建:

```
{workspace}/experiments/{slug}/{node_id}/
```

在节点执行时，`_run_loop` 将以下用户文件复制到每个节点的 work_dir:
- **Provided files**: `experiment.md` 中 `## Provided Files` (`## 提供ファイル` / `## 提供文件`) 下列出的路径
- **检查点根**: 检查点目录中的非 meta 文件
- **uploads 子目录**: `checkpoint/uploads/` 中的非 meta 文件

`PathManager.META_FILES` 定义了绝不能复制到节点 work_dir 的文件
(`experiment.md`, `tree.json`, `nodes_tree.json`, `launch_config.json`, `meta.json`,
`results.json`, `idea.json`, `cost_trace.jsonl`, `cost_summary.json`, `workflow.yaml`,
`ari.log`, `evaluation_criteria.json`, `.ari_pid`, `.pipeline_started`)。
扩展名为 `.log` 的文件也视为 meta。

### tree.json 和 nodes_tree.json

两个文件都包含 BFTS 节点树，但在生命周期的不同阶段写入:

| 文件              | 写入方                                                | 阶段             | 模式                                                  |
|-------------------|-------------------------------------------------------|------------------|-------------------------------------------------------|
| `tree.json`       | `cli.py` 中的 `_save_checkpoint()`                    | BFTS 阶段        | `{run_id, experiment_file, created_at, nodes}`        |
| `nodes_tree.json` | `_save_checkpoint()` + `generate_paper_section()`     | BFTS + post-BFTS | `{experiment_goal, nodes}` (轻量)                     |

**读取方约定**: 所有读取方必须优先使用 `tree.json` 并回退到 `nodes_tree.json`。
这可确保 BFTS 期间获得最新数据，同时保持与预期 `nodes_tree.json` 的流水线阶段的兼容性。

### 项目级状态 (每个检查点)

ARI 不再维护全局配置目录。所有设置文件和代理记忆都存储在活动检查点目录下，
因此每个实验拥有独立状态。v0.5.0 已经移除全局 `$HOME/.ari/` 目录；
仅存的几个文件系统回退会发出 `DeprecationWarning`，并在 v1.0 中彻底移除
（详见 `docs/_archive/refactor_audit.md` 与 `docs/guides/migration.md`）:

```
checkpoints/{run_id}/
├── settings.json        # GUI 设置 (LLM 模型、提供者、HPC 默认值)
├── memory_backup.jsonl.gz   # Letta 快照（流水线阶段结束和退出时自动）
├── memory_access.jsonl       # 写/读遥测
└── ...                  # tree.json / launch_config.json / uploads / ari.log
```

API 密钥 **绝不** 存储在 `settings.json` 中。它们从 `.env` 文件
(搜索顺序: checkpoint → ARI root → ari-core → home) 或启动时注入的环境变量中读取。

---

## 模块参考

### ari-core

| 模块 | 描述 |
|------|------|
| `ari/orchestrator/bfts.py` | 最佳优先树搜索 — 节点扩展、选择、剪枝；回退排名策略可通过 `BFTSConfig.frontier_score` (`scientific_plus_diversity` / `scientific_only` / `depth_penalized` / `ucb_like`) **配置** — 详见 [Configuration → BFTS 评估层](../reference/configuration.md#bfts-评估层-可通过配置切换) |
| `ari/orchestrator/node.py` | Node 数据类 — id、parent_id、depth、label、metrics、artifacts、memory |
| `ari/agent/loop.py` | ReAct 智能体循环 — 每个节点的 LLM + 工具调用；自动轮询 SLURM 作业；注入祖先记忆 |
| `ari/agent/workflow.py` | WorkflowHints — 从实验文本自动提取（工具序列、指标关键词、分区） |
| `ari/pipeline.py` | Post-BFTS 流水线驱动器 — 模板解析、阶段执行、输出连接 |
| `ari/evaluator/llm_evaluator.py` | 指标提取 + 同行评审评分（`scientific_score`、`comparison_found`）。合成公式 (`harmonic_mean` / `arithmetic_mean` / `weighted_min` / `geometric_mean`) 与轴集 (`legacy` / `dynamic` / `custom`) 可通过 `EvaluatorConfig` **配置** — 详见 [Configuration → BFTS 评估层](../reference/configuration.md#bfts-评估层-可通过配置切换) |
| `ari/memory/file_client.py` | 基于文件的记忆客户端（祖先链作用域） |
| `ari/mcp/client.py` | 异步 MCP 客户端 — 线程安全，为并行执行创建新的事件循环 |
| `ari/llm/client.py` | 通过 litellm 进行 LLM 路由（Ollama、OpenAI、Anthropic、任何 OpenAI 兼容接口） |
| `ari/config.py` | 配置数据类（BFTSConfig、LLMConfig、PipelineConfig） |
| `ari/core.py` | 顶层运行时构建器 — 连接所有组件 |
| `ari/cli.py` | CLI：`ari run`、`ari paper`、`ari status` |

### 技能（MCP 服务器）

**默认技能**（在 `workflow.yaml` 中注册）：

| 技能 | 工具 | 角色 | LLM? |
|------|------|------|------|
| `ari-skill-hpc` | `slurm_submit`、`job_status`、`job_cancel`、`singularity_build`、`singularity_run`、`singularity_pull`、`singularity_build_fakeroot`、`singularity_run_gpu` | HPC 作业管理 + Singularity 容器 | ✗ |
| `ari-skill-memory` | `add_memory`、`search_memory`、`get_node_memory`、`clear_node_memory`、`get_experiment_context` | 祖先作用域的节点记忆（Letta 后端） | △ |
| `ari-skill-idea` | `survey`、`generate_ideas` | 文献搜索（Semantic Scholar）+ VirSci 多智能体假设生成 | ✓ |
| `ari-skill-evaluator` | `make_metric_spec` | 从实验文件提取指标规格 | △ |
| `ari-skill-transform` | `nodes_to_science_data`、`generate_ear`、`curate_ear`、`publish_ear` | BFTS 树 → 科学数据 + EAR + curate/publish 生命周期 (v0.7.0) | ✓ |
| `ari-skill-web` | `web_search`、`fetch_url`、`search_arxiv`、`search_semantic_scholar`、`collect_references_iterative` | 网络搜索、arXiv、Semantic Scholar、迭代式引用收集 | △ |
| `ari-skill-plot` | `generate_figures`、`generate_figures_llm` | 确定性 + LLM 图表生成（按图通过 `kind` 字段选择 matplotlib 绘图或 SVG 图） | ✓ |
| `ari-skill-paper` | `list_venues`、`get_template`、`generate_section`、`compile_paper`、`check_format`、`review_section`、`revise_section`、`write_paper_iterative`、`review_compiled_paper`、`list_rubrics`、`inject_code_availability`、`merge_reviews` | LaTeX 论文撰写、编译、基于评审规范的同行评审 (兼容 AI Scientist v1/v2)。v0.7.0：`inject_code_availability` 注入 `\codeavailability{}` / `\codedigest{}` / `\coderef{}` 宏；`merge_reviews` 事后合并文本评审与 VLM 评审 JSON。 | ✓ |
| `ari-skill-paper-re` | `fetch_code_bundle`、`run_reproduce`、`grade_with_simplejudge` | PaperBench 形式可复现性 (v0.7.0)：通过 `ari.clone` 预填沙箱、Phase 1 沙箱 runner、Phase 2 PaperBench SimpleJudge 评分。PaperBench 同捆于 `vendor/paperbench`。 | ✓ |
| `ari-skill-replicate` | `generate_rubric`、`audit_rubric` | PaperBench 形式自动 rubric 生成与审计 (v0.7.0)。驱动 ORS 可复现性流。 | ✓ |
| `ari-skill-benchmark` | `analyze_results`、`plot`、`statistical_test` | CSV/JSON/NPY 分析、绘图、scipy 统计（BFTS analyze 阶段使用） | ✗ |
| `ari-skill-vlm` | `review_figure`、`review_table` | VLM 驱动的图表/表格审查（驱动 VLM 审查循环） | ✓ |
| `ari-skill-coding` | `write_code`、`run_code`、`read_file`、`run_bash` | 代码生成 + 执行 + 分页文件读取 | ✗ |

**附加技能**（可用，不在默认工作流中）：

| 技能 | 工具 | 角色 | LLM? |
|------|------|------|------|
| `ari-skill-orchestrator` | `run_experiment`、`get_status`、`list_runs`、`list_children`、`get_paper` | 将 ARI 作为 MCP 服务器暴露，递归子实验，双 stdio+HTTP 传输 | ✗ |

✗ = 无 LLM、△ = 仅部分工具使用 LLM、✓ = 主要工具使用 LLM。**共 14 个技能**（13 默认，1 附加）— v0.7.0 新增 `ari-skill-replicate`。

---

## Plan / Venue 契约 (v0.7.0+)

ARI 区分两类塑造运行的文档：

- **plan.md（≒ checkpoint `experiment.md`，promote 之后）** —— 该运行的
  *评估细节*：要测量哪些指标、与哪些基线比较、运行哪些消融。运行特定。
  真实来源（source of truth）：`idea.json[0].experiment_plan`。
- **venue.md（≒ `ari-core/config/reviewer_rubrics/<id>.yaml`）** ——
  *判定标准*：对哪些维度打分以及如何打分（`score_dimensions`、
  `system_hint`、`decision`）。venue 规范性。

这一双文件契约驱动 Phase 1、Phase 3 与谱系决策（lineage decisions）：

```
generate_ideas (idea-skill)
        │
        ▼  写入
{ckpt}/idea.json   ← 机器可读的 plan source
        │
        ├─ Phase 1: pipeline.py 向 {ckpt}/experiment.md 自动追加一个
        │   可渲染块（Selected idea + Plan §标题 +
        │   Alternatives considered）
        │
        ├─ Phase 3: LLMEvaluator 构建动态轴
        │   = generic 5 + rubric.score_dimensions + plan §-tag 关键词
        │   judge LLM 针对该集合为每个 BFTS 节点打分。
        │
        └─ 谱系决策（默认 stagnation_rule）：
            在 CONFIRMED（已确认）停滞时（composite 分数保持平坦），BFTS
            hook 首先调用 deterministic_stagnation_pivot() —— 它切换
            （switch_to_idea）到最强的 UNUSED（未使用）次选想法
            （tie-break：index 较小者）并设置
            disable_generate_ideas=True。LLM judge
            decide_lineage_action（continue / switch_to_idea / fanout /
            terminate）仅是 FALLBACK（回退），仅当 pivot 返回 None 时才会
            到达：预算耗尽、达到递归上限，或没有剩余的未使用替代。switch
            与 fanout 复用 Phase 2.5 的 synthetic-seed 启动路径；子节点的
            idea.json 会预先 seed 选定的替代并将其 pin 住（`_pinned:
            True`），子节点的 generate_ideas 在 pinned 之后追加其新想法而
            不覆盖。
```

`ARI_RUBRIC` 选择读取哪个 venue 文件。切换它会同时改变 BFTS 的打分轴
（Phase 3）与所发表评审的标准 —— **同一个 rubric 同时驱动二者**。

### 子实验的继承

每个子运行沿以下通道从其父继承：

| 通道 | 方向 | 机制 |
|---|---|---|
| `venue.md`（rubric） | 继承 | `ARI_RUBRIC` env 传播 |
| `memory` | 继承 | 祖先作用域读取（既有的 `ari-skill-memory`） |
| `idea.json`（catalog） | 继承（只读） | `ari/lineage.py` 沿 `meta.json:parent_run_id` 遍历；VirSci 将祖先标题注入到代理提示中 |
| `plan.md`（directive） | 默认 NOT 继承 | 子节点自己撰写 |

关键在于，`pipeline.py` 中的 directive 路径只读取当前 checkpoint 的
`idea.json` —— 谱系遍历是 *catalog* 路径，由 VirSci 和子实验启动器显式
调用。这让子节点可以自由 pivot。

### work_dir 继承 —— 输出产物黑名单 (v0.7.0 / Phase 7)

当 BFTS 扩展一个子节点时，子节点的 `work_dir` 通过复制父节点的
`work_dir` 来 seed。若不进一步过滤，会让子节点逐字节复用父节点的
`results.csv` / `slurm-*.out` / `run.log`；在 run-`20260504120448` 的
事后复盘中，所有 9 个子节点都因结果文件已在磁盘上、代理把实验当成已完成，
而报告了来自单个 SLURM 作业的相同数值。

`ari-core/ari/cli.py` 中的 `_OUTPUT_BLACKLIST` 显式列举了在父 → 子复制
期间被跳过的模式：

| 继承 | 黑名单 |
|---|---|
| 源码 / 脚本 / 配置（`*.cpp`、`*.py`、`*.sh`、`*.yaml`、`Makefile`、...） | `results.csv`、`results_*.csv`、`*_results.csv`、`metrics.csv`、`result.csv` |
| 编译后的二进制（`a.out`、无扩展名的 ELF 输出） | `*.metrics.json`、`metrics.json` |
| `data/`、`inputs/` 下的数据文件 | `run.log`、`run_*.log`、`*.run.log` |
| 嵌套源目录下的任何内容（如 `src/lib.cpp`） | `slurm-*.out`、`slurm-*.err`、`stdout.txt`、`stderr.txt`、`out.txt`、`err.txt` |
|  | `node_report.json`（每个节点重建自己的） |

执行后，`compute_files_changed(parent, child)` 基于 sha256 diff 返回
`{added, modified, deleted, inherited_unchanged}`。当
`added=0 ∧ modified=0 ∧ deleted=0` 时，循环将该子节点标记为
**sterile（不育）**（`metrics["_sterile"]=True`、`_scientific_score=0.0`、
`has_real_data=False`）；随后 BFTS 偏好任何非 sterile 的兄弟，而当每个子
节点都 sterile 时，parent-terminate 级联会剪掉该链。子代理的第一条 user
message 还会收到一条强制产生新产物的指令（“在此 work_dir 中产生 **新的**
result/log/metric 产物；不要依赖继承的文件”），因此行为良好的代理在文字与
指标两方面都有动机去真正运行实验。

---

## 流水线驱动的 ReAct (react_driver)

BFTS 自带的 ReAct 循环(`ari.agent.AgentLoop`，与 `Node` 树紧耦合)之外，还有一个轻量 ReAct 驱动 `ari.agent.react_driver.run_react`，面向无需 BFTS 上下文的 ReAct 智能体。当 stage 声明 `react:` 块时，由 `ari.pipeline._run_react_stage` 调用。

**v0.7.0**: `reproducibility_check` 不再使用 `react_driver`。PaperBench 形式流（`ors_generate_rubric` → `ors_run_reproduce` → `ors_grade`）以确定性 Phase 1 沙箱 runner + Phase 2 SimpleJudge 评分（`ari-skill-paper-re`）取代之。`react_driver` 仍保留在代码中以便将来通过 `react:` 块接入新的 stage，但默认 `workflow.yaml` 不再连接它。

```
pipeline.py ──▶ pre_tool (MCP)  → 声称的配置
             ─▶ react_driver.run_react
                   ├─ phase 过滤：MCPClient.list_tools(phase="reproduce")
                   ├─ 对每个工具调用的参数执行沙箱校验
                   └─ 智能体调用 `final_tool` 即终止
             ─▶ post_tool (MCP) → 裁决 + 解释
```

关键特性：

- **Phase 白名单**：`workflow.yaml` 中 `skills[].phase` 可以是单个字符串或数组。只有 phase 列表包含 stage `react.agent_phase` 的技能才能被智能体看到。默认 `workflow.yaml` 将 `web-skill` / `vlm-skill` / `hpc-skill` / `coding-skill` 加入 `reproduce`；`memory-skill` / `transform-skill` / `evaluator-skill` 被刻意排除，智能体无法观测 BFTS 状态(`nodes_tree.json`、祖先记忆、science data)。
- **沙箱**：`react.sandbox` 指向一个目录(默认 `{{checkpoint_dir}}/repro_sandbox/`)。工具参数会被扫描绝对路径和 `..` 穿越，沙箱外的路径(论文 `.tex` 的 allow-list 除外)会在抵达 MCP 之前被拒绝并返回 `sandbox violation`。MCP 服务器 fork 之前会将 `ARI_WORK_DIR` 设置为沙箱目录，所以 `coding-skill.run_bash` 的默认 cwd 也会在沙箱内。
- **终止条件**：智能体调用 `react.final_tool`(默认 `report_metric`)结束循环。该调用不会转发给 MCP，而是被驱动捕获，其参数成为传递给 stage `post_tool` 的 `actual_value` / `actual_unit` / `actual_notes`。

这一分离使 `reproduce_from_paper` 式 stage 的"仅读论文文本"约束能从 YAML 审计，而不是埋在技能 Python 里。

---

## 节点级提示构建

每个 BFTS 节点都通过 `ari/agent/loop.py:370` 中的 `AgentLoop.run(node, experiment)` 这一单一入口执行。同一循环既处理根节点也处理子节点；它构建的提示仅根据 `node.depth` 和从祖先继承的状态分支。本节是 *代理在节点开始时实际看到什么* 的权威来源。在此处更改需要谨慎审查。

### `AgentLoop.run` 的输入

每次调用接收两个参数：

1. **`node: Node`** — 由 `BFTS.expand`（`ari/orchestrator/bfts.py:431-441`）创建。影响提示的字段：
   - `id`、`depth`、`label`（`draft|improve|debug|ablation|validation|other`）、`raw_label`
   - `ancestor_ids` — 从根到父节点（含父节点）的严格 CoW 链，用作 `search_memory` 过滤器。
   - `eval_summary` — 对于刚扩展的子节点，此字段保存 LLM 提议的方向（一句话）。执行后该字段会被评估器摘要覆盖。
   - `memory_snapshot` — 父节点快照的副本；当前提示构建器未使用，但会持久化到 `tree.json`。
2. **`experiment: dict`** — 调度器按节点组装：
   - `goal` — 整个 `experiment.md` 文本（运行级别，所有节点相同）
   - `work_dir` — `PathManager` 创建的节点专属目录
   - `slurm_partition`、`slurm_max_cpus` — SLURM 启用时由 `env_detect` 填充

### 系统提示 — `ari/agent/loop.py:41-58`

```
You are a research agent. You MUST use tools to execute experiments. ...

AVAILABLE TOOLS:
{tool_desc}                ← 当前阶段枚举的 MCP 工具

RULES:
- Your FIRST action must be a tool call ...
- If `make_metric_spec` is available and this is a new experiment ...
- NEVER fabricate numeric values ...
- When all experiments are done, return JSON {...}
- Do NOT call gap_analysis or generate_hypothesis
- Ensure your experiment is reproducible: ...
{memory_rules}{extra}
```

`{extra}` 块（在 L448-453 构建）追加：

| 子块 | 来源 | 备注 |
|------|------|------|
| `NODE ROLE: {label_hint}` | `node.label.system_hint()` | 由 BFTS 标签衍生的一句话行为提示 |
| `EXPERIMENT ENVIRONMENT` | L433-442 | `work_dir` + 已有文件 + SLURM partition/CPUs + 容器镜像（`ARI_CONTAINER_IMAGE`） |
| `RESOURCE BUDGET` | L443-447 | `max_react_steps`、`timeout_per_node // 60` 分钟 |
| `extra_system_prompt` | `WorkflowHints.extra_system_prompt` | 由 `from_experiment_text` / 流水线配置可选设置的逃生口 |

`{memory_rules}` 块（L454-456）仅在代理实际拥有 `add_memory` 工具时附加，并将活跃节点 id 内联到提示中，使 LLM 无法意外写入其他作用域：

```
- When available, save decisive intermediate findings with
  add_memory(node_id="<本节点的 id>", text=..., metadata=...)
- Use search_memory(query=..., ancestor_ids=[...], limit=5) ...
```

### 工具目录（`tool_desc`）

L389 的 `tools = self._available_tools_openai(suppress=..., phase="bfts")` 枚举 MCP 为 `phase="bfts"` 暴露的所有工具，然后丢弃 `_suppress_tools` 中的任何工具。可变的 suppression 集合存在于 `AgentLoop` 实例上，并随运行进展更新：

- 第一次成功的 `generate_ideas` 调用之后，循环设置 `self._suppress_tools = {"generate_ideas"}`（L873-874），后续节点不再重新生成 idea。
- `survey` 对子节点 **不被 suppress**；仅在文字中被劝阻（见下文「User message #1 — 子节点」）。忽略文字劝阻的子仍然可以调用 `survey()`。

`_PINNED_TOOLS = {"survey", "generate_ideas", "make_metric_spec"}`（L613）标记消息窗口修剪器必须保留的工具结果；即使聊天历史被压缩，它们的内容也会在每个 ReAct 轮次存活。

### User message #1 — 根节点（`node.depth == 0`）

`loop.py:501-511`:

```
Experiment goal:
{goal_text(截断到 1500 字符)}

Node: {node.id} depth={node.depth}

START NOW: call {first_tool}() immediately. Do NOT output any text or
plan — your first response must be a {first_tool}() tool call.

WORKFLOW ORDER: (1) generate_ideas() sets the research direction and
primary_metric; (2) make_metric_spec() derives the success metrics from
that primary_metric (NOT from a guessed list); (3) survey() gathers related
literature. The survey results are used to generate citations — without
survey, the paper will have no references.
```

`first_tool` 是 `WorkflowHints.tool_sequence[0]`，现在默认为 `generate_ideas`；当对应技能存在时，`enrich_hints_from_mcp` 将 setup 工具排序为 `generate_ideas` → `make_metric_spec` → `survey` → executor（idea 的 `primary_metric` 即成功标准，因此 `make_metric_spec` 必须跟在 idea 之后派生，而不是猜测一份列表）。

### User message #1 — 子节点（`node.depth > 0`）

`loop.py:477-500`:

```
Experiment goal:
{goal_text(截断到 1500 字符)}

Node: {node.id} depth={node.depth} task={node.label}

Task: {label-specific one-line description from _label_desc}
The parent node already completed the survey and established a research
direction. Prior results are provided below. Implement and run your
specific experiment, then return JSON with measurements.

Workflow:
{WorkflowHints.post_survey_hint}        ← 例如：slurm_submit / run_bash 步骤
```

`_label_desc`（L479-485）是节点级提示中标签语义出现的唯一位置：

| Label | 一行任务 |
|-------|---------|
| `improve` | Improve performance or accuracy beyond what the parent achieved. |
| `ablation` | Ablation study: remove or vary one component from the parent approach. |
| `validation` | Validate the parent result under different conditions or parameters. |
| `debug` | The parent experiment had issues. Diagnose and fix them. |
| `draft` | Try a new implementation approach for the same goal. |
| *(other / unknown)* | Extend or vary the parent experiment. |

注意 `node.eval_summary`（BFTS 扩展器 LLM 为该子节点提议的具体方向）**不会逐字写入此提示**。子节点只看到通用标签任务；提议的方向通过下方的先验知识记忆搜索间接传达给代理。

### User message #2 — 工作上下文注入（每个节点）

旧的仅子节点 `search_memory` 转储（一条 `[Prior knowledge from ancestor nodes …]` 消息，截断到聚合 800 字符）已被模块级的 `build_working_context_messages()`（`loop.py:108-224`）**取代**，并由 `AgentLoop.run` 对 **每个** 节点调用。它是只读的 —— 从不写记忆 —— 并组装至多三个带上限的层级：

- **Tier 1a —— 实验核心（每个节点）。** 调用 `get_experiment_context` 并注入一个 `[Experiment context (stable across all nodes):]` 块，携带 `primary_metric`、`higher_is_better`、`metric_rationale`、`hardware_spec`，**外加** 一个 `selected_idea` 摘要。它对根节点和每个后代都适用，因此从不重跑 `generate_ideas` 的节点也能继承设计意图（计划的机制 + 目标工作负载），而不仅仅是指标。
- **Tier 1b —— 祖先核心（仅子节点）。** 对每个祖先调用 `get_node_memory(node_id=aid)`，只保留 `metadata.type == "result_summary"` 的条目，输出一个 `[Established conclusions from ancestor nodes (N):]` 块。这是确定性的、完整的逐祖先交接：每条结论 **按条目** 截断（而非聚合裁剪），并受树深度约束因此整条注入。顺序遵循 `ancestor_ids`（根 → 父）。
- **Tier 2 —— 细节补充（仅子节点）。** 通过 `search_memory(query=…, ancestor_ids=…, limit=5)` 做一次小的语义召回，对 Tier 1b 去重，呈现为 `[Related prior findings from ancestors (N):]`。`eval_summary` 仅用作搜索查询（截断到约 200 字符）。

失败（记忆后端宕机、结果格式异常等）在 `logger.debug` 级别被吞掉，节点仍然运行。

遗留的 `search_global_memory` 注入块（`loop.py:517-540`）在 v0.6.0 中是死代码；全局记忆工具已被移除（`CHANGELOG.md` v0.6.0 §3），条件分支永不触发。

### 截断速查表

| 项目 | 上限 | 代码 |
|------|-----|------|
| `goal_text` | 1500 字符 | `loop.py:434-438` |
| Survey 结果记忆条目 | 前 5 篇论文，每篇 abstract 200 字符 | `loop.py:794-799` |
| Tier 1a —— 实验核心字段 | `_CORE_FIELD_CAP = 400` 字符／字段 | `loop.py:94` |
| Tier 1a —— `selected_idea` 摘要 | `_IDEA_FIELD_CAP = 1500` 字符 | `loop.py:95` |
| Tier 1b —— 逐祖先 `result_summary` | `_ANCESTOR_SUMMARY_CAP = 600` 字符／条目（非聚合裁剪） | `loop.py:98` |
| Tier 2 —— 补充查询 | 200 字符 | `loop.py:201` |
| Tier 2 —— 补充条目 | 按 Letta `passages.search` 嵌入排序前 5 条 | `loop.py:202-206`（见 Memory Architecture 节）|
| Tier 2 —— 逐补充条目 | `_SUPPLEMENT_CAP = 400` 字符／条目 | `loop.py:99` |

### 故意 **不注入** 的信息

以下信息可达但绝不会自动添加到提示中；如果代理需要，必须自己调用相关工具：

- **子节点的 `node.eval_summary` 方向文本的逐字注入**。持久化在 Node 对象上，BFTS 扩展/评估可见，但绝不会逐字粘贴到子代理的 user prompt 中。（如上面「User message #2」所述，它 *会* 被读作 Tier 2 补充的 `search_memory` 查询 —— 但只是作为查询，不会作为文本呈现。）
- **`memory_snapshot`**。从父节点带入子 Node，但提示构建器不消费；保留供未来使用。
- **兄弟节点 metrics**。提议子节点时 `BFTS.expand`（即 *扩展器 LLM*）可见，但该子节点的 *执行代理* 看不到。

注意 `get_experiment_context()` 载荷（`primary_metric`、`higher_is_better`、`metric_rationale`、`hardware_spec`）**已不再** 在此列表中 —— 它现在作为上述工作上下文注入的 Tier 1a 对每个节点自动注入。

### CoW 桥接 — 与记忆技能保持同步

在 LLM 往返开始之前，`loop.py:378-381` 发出：

```python
self.mcp.call_tool("_set_current_node", {"node_id": node.id})
```

这是 `ari-skill-memory` 暴露的内部工具；它更新池化技能子进程内的 `$ARI_CURRENT_NODE_ID`，使任何后续 `add_memory(node_id=...)` 调用可以针对活跃节点进行 CoW 验证。代理永远看不到此工具 ── 它被 `_INTERNAL_MCP_TOOLS` 从 `tool_desc` 中过滤。

### Soft 强制 vs Hard 强制

代理看似遵守的某些「规则」在代码中被严格强制，其他则仅由提示文字控制。在调试代理意外行为时，知道哪个属于哪种很重要：

| 规则 | 强制方式 |
|-----|---------|
| 不能为其他节点写记忆 | **Hard** — 后端拒绝 `node_id` ≠ `$ARI_CURRENT_NODE_ID` |
| 不能读取兄弟记忆 | **Hard** — `search_memory` 按 `ancestor_ids` 过滤 |
| `generate_ideas` 最多调用一次 | **Hard** — 首次后 `_suppress_tools` 排除 |
| 子节点不应调用 `survey` | **Soft** — 仅文字（"parent already completed the survey"）；工具仍在 `tool_desc` 中 |
| 子节点应实现而非计划 | **Soft** — 仅文字；依赖系统提示的 `RULES` 块 |
| 资源预算 | 提示中的 **Soft 提示** + 循环中的 **Hard** timeout / step cap |

---

## 设计不变量

ARI 的生产代码包含**零领域知识**。所有领域决策都在运行时委托给 LLM。

| 决策 | 由谁决定 |
|------|----------|
| 哪些指标重要 | LLM 评估器 |
| 与什么进行比较 | LLM 评估器（`comparison_found`） |
| 运行什么实验 | ReAct 智能体（LLM） |
| 使用了什么硬件 | Transform 技能 LLM（从产物中读取 lscpu 等信息） |
| 绘制什么图表 | Plot 技能 LLM |
| 从树中提取什么 | Transform 技能 LLM |
| 如何对节点排名 | LLM 分配的 `_scientific_score` |
| 使用什么引用关键词 | LLM 从节点摘要中生成 |
| 是否收集环境/设置信息 | ReAct 智能体 LLM（由系统提示中的可复现性原则引导） |

---

## 扩展 ARI

要添加新功能，请创建一个新的 MCP 技能：

```bash
mkdir ari-skill-myskill/src
# Implement server.py with FastMCP tools
# Register in workflow.yaml skills section
```

```yaml
# workflow.yaml
skills:
  - name: myskill
    path: "{{ari_root}}/ari-skill-myskill"

pipeline:
  - stage: my_stage
    skill: myskill
    tool: my_tool
    inputs:
      data: "{{ckpt}}/science_data.json"
```

无需修改 `ari-core`。
