# MCP 技能参考

技能是为 ARI 智能体提供工具的 MCP 服务器。工具尽可能保持确定性；使用 LLM 的工具会明确标注。**共 14 个技能**（13 个默认，1 个附加）。v0.7.0 新增 `ari-skill-replicate`，用于 PaperBench 形式的可复现性流程。

## ari-skill-hpc

通过 SLURM 和 Singularity 进行 HPC 作业管理。**LLM：否**（完全确定性）。

### 工具

#### `slurm_submit(script, job_name, partition, nodes=1, walltime="01:00:00", work_dir)`

提交 SLURM 批处理作业。

```python
result = slurm_submit(
    script="""
#!/bin/bash
#SBATCH --cpus-per-task=32
gcc -O3 -fopenmp -o ./bench ./bench.c
OMP_NUM_THREADS=32 ./bench
""",
    job_name="bench_test",
    partition="your_partition",
    work_dir="/abs/path/to/workdir"
)
# Returns: {"job_id": "12345", "status": "submitted"}
```

**注意事项：**
- `--account` 和 `-A` 头信息会被静默移除（在此集群上无效）
- 空的 `job_id` 会立即返回错误
- 脚本中不要使用 `~`（在 SBATCH 中不会展开）

#### `job_status(job_id)`

轮询 SLURM 作业状态。

```python
result = job_status("12345")
# Returns: {"status": "COMPLETED", "exit_code": 0, "stdout": "MFLOPS: 284172"}
# 状态值：PENDING、RUNNING、COMPLETED、FAILED、ERROR
```

#### `job_cancel(job_id)`

取消正在运行或等待的 SLURM 作业。

#### `run_bash(command)`

在登录节点上运行只读 bash 命令。

```python
result = run_bash("cat /path/to/slurm_job_12345.out")
# Returns: {"stdout": "...", "exit_code": 0}
```

#### `singularity_build(definition_file, output_path, partition)`

从定义文件构建 Singularity 容器。

#### `singularity_run(image_path, command, work_dir, partition, nodes=1, walltime="01:00:00")`

作为 SLURM 作业运行 Singularity 容器。

#### `singularity_pull(source, output_path, partition)`

从远程仓库拉取 Singularity 镜像。

#### `singularity_build_fakeroot(definition_content, output_path, partition, walltime)`

使用 fakeroot 模式构建 Singularity 容器。

#### `singularity_run_gpu(image_path, command, work_dir, partition, gres="gpu:1", cpus_per_task=8, walltime="01:00:00", bind_paths=[])`

使用 GPU 访问运行 Singularity 容器（`--nv` 标志）。

---

## ari-skill-idea

文献调研和想法生成。**LLM：是**（generate_ideas 使用 VirSci 多智能体讨论）。

### 工具

#### `survey(topic, max_papers=8)`

搜索 Semantic Scholar 获取相关论文。确定性（无 LLM）。

```python
result = survey("OpenMP compiler optimization HPC benchmarks")
# Returns: {"papers": [{"title": "...", "abstract": "...", "url": "..."}]}
```

需要 `S2_API_KEY` 环境变量以获得更高的 Semantic Scholar 速率限制。

#### `generate_ideas(topic, papers, experiment_context="", n_ideas=3, n_agents=4, max_discussion_rounds=2, max_recursion_depth=0)`

使用 VirSci 多智能体 LLM 讨论生成研究假设。多个 AI 角色（研究者、批评者、专家、综合者）就研究问题进行辩论。仅在 BFTS 启动前调用**一次**（仅限 pre-BFTS）。

模型：`ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > `ollama_chat/qwen3:32b`。

---

## ari-skill-evaluator

从实验文件中提取指标规格。**LLM：条件性**（仅在文本中未找到 metric_keyword 时回退使用 LLM）。

### 工具

#### `make_metric_spec(experiment_text)`

解析实验 Markdown 以提取评估标准。当文本中包含 `metric_keyword` 和 `min_expected_metric` 时为确定性操作；未找到时回退使用 LLM。

```python
result = make_metric_spec(open("experiment.md").read())
# Returns: {
#   "metric_keyword": "MFLOPS",
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "..."
# }
```

模型（回退）：`ARI_MODEL` 环境变量 > `gpt-4o-mini`。

---

## ari-skill-paper

LaTeX 论文生成、编译和审阅（仅限 Post-BFTS）。**LLM：是**。

### 工具

#### `list_venues()`

返回可用的场所配置。

支持的场所：`neurips`（9 页）、`icpp`（10 页）、`sc`（12 页）、`isc`（12 页）、`arxiv`（无限制）、`acm`（10 页）。

#### `get_template(venue)`

返回指定场所的 LaTeX 模板。

#### `generate_section(section, context, venue="arxiv", refs_json="", nodes_json_path="")`

使用 LLM 生成 LaTeX 章节。章节类型：`introduction`、`related_work`、`method`、`experiment`、`conclusion`。

#### `compile_paper(tex_dir, main_file="main.tex")`

运行 pdflatex 编译。返回成功状态和错误信息。

#### `check_format(venue, pdf_path)`

根据场所要求验证论文格式（页数等）。

#### `review_section(latex, context, venue="arxiv")`

审阅 LaTeX 章节。返回优点、缺点和建议。

#### `revise_section(section, latex, feedback)`

根据审阅反馈修改 LaTeX 章节。

#### `write_paper_iterative(experiment_summary, context, nodes_json_path, refs_json, figures_manifest_json, output_dir, max_revisions=2, venue="arxiv")`

完整论文生成，包含迭代式草稿 -> 审阅 -> 修改循环。主要流水线工具。

#### `review_compiled_paper(tex_path, pdf_path, figures_manifest_json, experiment_summary, rubric_id="", vlm_findings_json="", num_reflections=None, num_fs_examples=None)`

**AI Scientist v1/v2 兼容** 的基于评审规范的论文审阅（遵循 Nature /
arXiv:2408.06292 附录 A.4）。从 `ari-core/config/reviewer_rubrics/<rubric_id>.yaml`
加载评审规范，根据 `score_dimensions` / `text_sections` / `decision` 动态生成
提示。VLM 的逐图反馈（分数 / 问题 / 建议）作为审稿人备注注入，并附加
Few-shot 示例，经 Self-reflection 循环自我批评修订后输出符合评审规范的 JSON。

已内置评审规范（`ari-core/config/reviewer_rubrics/` 下 16 个 YAML）：

| 类别 | rubric_id |
|---|---|
| ML 会议 | `neurips`（默认，v2 兼容）/ `iclr` / `icml` / `cvpr` / `acl` |
| 系统 / HPC | `sc` / `osdi` / `usenix_security` |
| 理论 / 图形学 | `stoc` / `siggraph` |
| HCI / 机器人 | `chi` / `icra` |
| 期刊 / 通用 | `nature` / `journal_generic` / `workshop` / `generic_conference` |

在 `reviewer_rubrics/` 目录放一份 YAML 即可扩展新的会议，无需修改代码。
每个评审规范声明 `score_dimensions` / `text_sections` / `decision` 规则、
执行参数及用于 P2 确定性的 SHA256 哈希。

解析顺序：显式 `rubric_id` 参数 → `ARI_RUBRIC` 环境变量 → `neurips` →
内置 `legacy` 回退（v0.5 schema，当 `rubric_id` 与 YAML 都解析不到时使用）。

Nature Ablation 默认值：

- `num_reflections: 5` — +2% 平衡精度
- `num_fs_examples: 1` — +2% 精度（ICLR 审稿指南 1-shot）
- `num_reviews_ensemble: 1` — 集成只降方差不提升精度
- `temperature: 0.75`

模型：`ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > `ollama_chat/qwen3:32b`。

**集成 + Area Chair 元审稿（内置）：** `review_compiled_paper` 通过集成路径
运行 N 个独立审稿人代理（带温度抖动，AI Scientist v1 best-config 风格）。
当 N>1 时，还会在内部运行 Area Chair 元审稿，并将 `ensemble_reviews: [...]`
和 `meta_review: {...}` 附加到输出。N 的解析顺序：显式参数 >
`ARI_NUM_REVIEWS_ENSEMBLE` 环境变量 > `rubric.params.num_reviews_ensemble`
（默认 1）。N=1 等价于单审稿人。

#### `list_rubrics()`

返回可用 rubric 的列表（id、venue、domain、version、SHA256 hash、path）。
viz API `/api/rubrics` 和 New Experiment 向导下拉菜单会用到。

#### `inject_code_availability(tex_path, checkpoint_dir)` — v0.7.0

作为 `finalize_paper` 阶段运行。从 `ear_published/manifest.lock` 与 `publish_record.json` 自动加载 `ref` / `bundle_sha256` / `doi`，并将机器可读的 `\codeavailability{}` / `\codedigest{}` / `\coderef{}` 宏与人类可读的 Code Availability 章节注入 `full_paper.tex`。digest 是信任锚点，读者无需信任 registry 即可 `ari clone <ref> --expect-sha256 <baked-digest>` 进行验证。如果未策展 bundle 则静默跳过（保持 v0.6.0 checkpoint 兼容）。

#### `merge_reviews(review_report_path, vlm_review_path)` — v0.7.0

将 `review_report.json`（文本评审）与 `vlm_review.json`（VLM 图表评审）做事后结构合并。完全确定性、无 LLM。附加 `vlm_figure_review` 与 `_review_composition` 元数据，使 GUI / CLI 能附带来源标注同时显示两类输出。上游阶段保持独立（与 AI Scientist v2 `perform_review` 契约一致），在此处方完成对账。

##### Few-shot 语料库管理

`ari-core/config/reviewer_rubrics/fewshot_examples/<rubric>/` 下的文件可通过**New Experiment 向导 → Paper Review → Few-shot 示例** 子面板 (GUI) 或 `scripts/fewshot/sync.py` (CLI) 管理。

GUI 操作:

- **Auto-sync**: 服务器端运行 `scripts/fewshot/sync.py --venue <rubric>` 拉取 `manifest.yaml` 中声明的条目。默认包含 AI Scientist v2 的三个示例 (`132_automated_relational` / `2_carpe_diem` / `attention`)，从 Apache-2.0 许可的 `SakanaAI/AI-Scientist-v2` 仓库下载。
- **Upload**: 接受符合 rubric schema 的 JSON + 可选 `.txt` 摘录 + 可选 PDF (base64)，自动标注 `_source: "GUI upload (rubric=<id>)"`。
- **Delete**: 删除示例的所有扩展名文件。

REST 端点:

- `GET  /api/fewshot/<rubric>`
- `POST /api/fewshot/<rubric>/sync`
- `POST /api/fewshot/<rubric>/upload`
- `POST /api/fewshot/<rubric>/<example>/delete`

所有端点都会拒绝 `reviewer_rubrics/` 中不存在的 rubric，并从输入中剥离 `../` / 斜杠字符。

---

## ari-skill-paper-re

基于 PaperBench (arXiv:2504.01848) **SimpleJudge** 的可复现性评分。**LLM：是**（评分由 upstream `SimpleJudge` 内部的 LLM 调用完成；ARI 在本技能中不增加额外的 LLM 调用）。

v0.7.0 将 v0.6.0 的 LLM 驱动判定路径替换为以 PaperBench 为评分内核的确定性端到端链：

```
ors_generate_rubric  (replicate-skill)    → ors_rubric.json + ors_rubric.meta.json
ear_publish          (transform-skill)    → bundle.tar.gz + publish_record.json (默认 local-tarball)
ors_seed_sandbox     (paper-re-skill)     → repro_sandbox/{reproduce.sh, code/...}
                                              (确定性；fetch_code_bundle ← publish_record.json)
ors_build_reproduce  (paper-re-skill)     → repro_sandbox/{reproduce.sh, source files}
                                              (LLM 回退；如已 seed 则跳过)
ors_run_reproduce    (paper-re-skill)     → ors_phase1.json   (Phase 1：在沙箱中执行 reproduce.sh)
ors_grade            (paper-re-skill)     → ors_grade.json    (Phase 2：用 SimpleJudge 对 rubric 叶节点评分)
```

EAR 开启的运行通过 `ors_seed_sandbox`（确定性）获取 reproduce.sh；LLM `ors_build_reproduce` 在 reproduce.sh 已存在时跳过，所以仅在 EAR 关闭（论文唯一复现）时触发。

PaperBench 以 git submodule 形式同捆于 `ari-skill-paper-re/vendor/paperbench`。主要逐叶评分 completer 通过 LiteLLM (`_litellm_completer.py`) 路由，因此任意供应商可用（`gpt-5-mini` / `anthropic/claude-...` / `gemini/...` / `ollama/...`）；分数解析的 structured completer 仍使用 `gpt-4o-2024-08-06`（在 PaperBench 允许列表内）。

### 工具

#### `fetch_code_bundle(ref="", sha256="", dest, checkpoint_dir="", overwrite=False)`

确定性地填充沙箱（无 LLM）。**v0.7.0+**: 传入 `checkpoint_dir` 可从 `{checkpoint_dir}/publish_record.json` 自动读取 ref + sha256（即 `ari ear publish` 写入的文件）。当 `dest/reproduce.sh` 已存在时返回 `populated=False, skipped_reason=...` 并跳过。

#### `build_reproduce_sh(paper_path, paper_text, rubric_path, output_dir, model="", overwrite=False)`

**v0.7.0+ 新增的 LLM 驱动 replicator**。`fetch_code_bundle` 的兄弟工具。读取论文（与 rubric 的 `expected_artifacts`）并将自包含的 `reproduce.sh` + 源文件写入 `output_dir`。通过 LiteLLM 路由，任意供应商可用。当 `output_dir/reproduce.sh` 已存在时跳过。模型：`model` 参数 > `ARI_MODEL_REPLICATE` > `ARI_LLM_MODEL` > `claude-opus-4-7`。

#### `run_reproduce(rubric_path, repo_dir, sandbox_kind="", timeout_global_sec=0, partition="", cpus=0, walltime="")`

**Phase 1**。在沙箱中执行 `repo_dir/reproduce.sh`，捕获 `reproduce.log` 与产物列表，并对照 rubric envelope 的 `expected_artifacts` 检查缺失项 `missing`。

沙箱优先级（默认 `auto`）：`slurm`（sbatch + `ARI_SLURM_PARTITION` 存在，BFTS 同分区）→ `docker`（守护可用且非 HPC 时）→ `apptainer` → `singularity` → `local`。**SLURM dispatch** 在 v0.7.0 已从 v0.5.0 恢复：使用 `sbatch --wait` 同步执行，并生成 spool relocation 包装器以保护 `$0` 相对 cd。

#### `grade_with_simplejudge(rubric_path, repo_dir, paper_path="", paper_text="", judge_model="", n_runs=3, skip_negative_control=False)`

**Phase 2**。主评分 completer 通过 LiteLLM 运行 + 直连 OpenAI 的 structured score-parser。`n_runs`（默认 3）次按 PaperBench 加权叶节点聚合取均值，附负样本对照。

返回值：`{ors_score, raw_score, leaf_grades, judge_model, n_runs, rubric_sha256, elapsed_sec, negative_control: {empty, boilerplate, passed}}`。

模型：`judge_model` 参数 > `ARI_MODEL_JUDGE` > `ARI_LLM_MODEL` > `gpt-5-mini`。任意 LiteLLM 可识别的 model id 均可（绕过 PaperBench 原生 `CONTEXT_WINDOW_LENGTHS` 约束）。

---

## ari-skill-replicate

v0.7.0 引入的 PaperBench 形式 **自动 rubric 生成与审计**。读取论文并输出 frozen rubric（`replication_rubric.schema.json`，带 provenance 元数据的 PaperBench `TaskNode` 树）。**LLM：是**。

与 `ari-skill-paper-re.grade_with_simplejudge` 共同构成取代 v0.6.0 `react_driver` 可复现性检查的 ORS 流水线。

### 工具

#### `generate_rubric(paper_path, paper_text, output_path, target_leaf_count=0, model="", temperature=0.0, seed=0, two_stage=True)`

生成 PaperBench 兼容的 rubric。当 `target_leaf_count=0` 时按论文长度自动估算叶节点数（约 1 叶 / 75 词，限制在 [50, 400]）。

`two_stage=True`（默认）使用 **两阶段生成**: ①骨架阶段定义根 + 直接子节点（每项贡献/实验一个）并分配各子树叶数预算 → ②子树阶段对每个直接子节点并行运行，递归展开 4–6 层。合并后，违反 schema `minLength=10` 的叶（`quote` / `requirements` 过短）会被自动剪除。在 PaperBench 参考论文上的实测：相比单次调用 **叶数约 4 倍、深度增加 1–2 层**，API token 消耗约 5 倍。`two_stage=False` 可回退到单次调用（`prompts/adversarial_reviewer.md`）。

#### `audit_rubric(rubric_path, paper_path, paper_text, auditor_model="")`

独立审计步骤。将问题叶节点标记为 `vague_qualifier` / `no_paper_evidence` / `duplicate` / `unverifiable`；超过 20% 时建议重新生成。

#### `suggest_target_leaf_count(paper_path, paper_text)`

返回根据论文长度自动估算的目标叶数与词数。供 GUI Wizard "Target leaves" 字段预填使用。

### 环境变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `ARI_MODEL_RUBRIC_GEN` | `gemini/gemini-2.5-pro` | 生成 LLM |
| `ARI_MODEL_RUBRIC_AUDIT` | `anthropic/claude-opus-4-7` | 审计 LLM（与生成器独立） |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | (未设置) | 覆盖目标叶数。`0` / 未设置时按论文长度自动。GUI Wizard "Target leaves" 字段。 |
| `ARI_RUBRIC_GEN_TEMPERATURE` | (未设置) | 覆盖生成器 temperature。GUI Wizard "Temperature" 字段。 |
| `ARI_RUBRIC_GEN_TWO_STAGE` | (未设置) | 强制开/关两阶段生成（`1`/`true`/`on` vs `0`/`false`/`off`）。未设置时使用 kwarg 默认（当前 `True`）。GUI Wizard "两阶段生成" 切换。 |

`server.py` 按 "显式 kwarg → 环境变量 → 默认值" 的顺序解析。`workflow.yaml` 的 `ors_generate_rubric` 阶段未显式传递这三个参数，因此 GUI Wizard 的值始终生效。

---

## ari-skill-memory

祖先作用域的节点记忆（v0.6.0 起由 [Letta](https://docs.letta.com) 支持）。防止跨分支污染，ReAct 轨迹也存放在同一个 Letta 代理中。**LLM：△**（基于嵌入的检索。P2 放宽详见 `docs/PHILOSOPHY.md`）。

### 工具

#### `add_memory(node_id, text, metadata=None)`

存储标记了 `node_id` 的条目。**Copy-on-Write**：若 `node_id` 与 `$ARI_CURRENT_NODE_ID` 不一致，则拒绝写入。

#### `search_memory(query, ancestor_ids, limit=5)`

按 **Letta `passages.search`（基于 embedding 的语义搜索）排序**，仅返回 `ancestor_ids` 中节点的条目。兄弟/子节点永远不会返回。

实现说明（对 Letta 0.16.7 在 2026-05-04 验证）：本技能刻意 **不使用** SDK 的 `passages.list(search=q)`。该 SDK 路径在服务端为 `GET /archival-memory?search=q`，是 SQL **子串匹配**（`WHERE LOWER(text) LIKE LOWER(%q%)`），并非语义搜索。像 `"Validate the loopline performance model"` 这类自然语言查询不会与 `RESULT SUMMARY metrics=[...]` 这类结构化条目子串匹配，因此生产中即便有 84 条有效 passage，`search_memory` 也只返回 0 条。本技能改为调用 `passages.search`（`GET /archival-memory/search`，`embed_query=True`），以 `top_k = max(letta_overfetch, limit*40)` 拉取，再在本地按 `ancestor_ids` / `ari_checkpoint` / `kind == "node_scope"` 做 post-filter。`add_memory` 插入时已支付的 embedding 成本现在能在检索中真正被使用；子节点会按其 `eval_summary` 查询的 **语义相关度** 顺序看到祖先条目。

#### `get_node_memory(node_id)`

按时间顺序返回特定节点的所有条目（无评分）。

#### `clear_node_memory(node_id)`

仅用于调试的单节点清除。与 `add_memory` 使用相同的 CoW 规则。

#### `get_experiment_context()`

返回 Letta 核心记忆中种入的稳定事实（`experiment_goal`、`primary_metric`、`hardware_spec` 等）。种入仅在首个节点的 `generate_ideas` 完成时（即 `primary_metric` 被确定的时刻）执行一次，在此之前调用会返回 `{}`。之后可安全反复调用（带 60 秒进程内缓存）。

存储：每个检查点拥有一个 Letta 代理（两个集合 `ari_node_*` 与 `ari_react_*`）。可移植快照位于 `{ARI_CHECKPOINT_DIR}/memory_backup.jsonl.gz`，写/读遥测位于 `{ARI_CHECKPOINT_DIR}/memory_access.jsonl`。v0.5.x 的 JSONL 存储（检查点级 `memory_store.jsonl` 以及曾经位于 `$HOME/.ari/` 下的遗留全局 JSONL）已在 v0.5.0 移除；使用 `ari memory migrate --react` 迁移。跨实验“全局记忆”已弃用。

---

## ari-skill-orchestrator

将 ARI 作为 MCP 服务器暴露给外部智能体和 IDE，支持递归子实验。**LLM：否**（委托给 ARI CLI）。

双传输：**stdio**（用于 Claude Desktop / 其他 MCP 客户端）+ **HTTP**（REST + SSE，`ARI_ORCHESTRATOR_PORT`，默认 9890）。

### 工具

#### `run_experiment(experiment_md, max_nodes=10, model="qwen3:32b", parent_run_id="", recursion_depth=0, max_recursion_depth=0)`

异步启动 ARI 实验。返回 `run_id`。当设置 `parent_run_id` 时，该实验将作为父实验的子项被追踪（用于递归子实验工作流）。

#### `get_status(run_id)`

返回运行的进度、当前最佳指标和递归元数据。

#### `list_runs()`

列出所有过去的实验运行。

#### `list_children(run_id)`

返回父实验的子运行列表（用于递归子实验追踪）。

#### `get_paper(run_id)`

返回生成的论文（LaTeX）。

工作空间：`ARI_WORKSPACE` 环境变量（默认：`~/ARI`）。父子关系保存在每个检查点的 `meta.json` 中。

---

## ari-skill-transform

将 BFTS 内部表示转换为面向出版的科学数据格式。剥离所有内部字段（`node_id`、`label`、`depth`、`parent_id`），仅暴露科学内容（`configurations`、`experiment_context`）。**LLM：是**。

### 工具

#### `nodes_to_science_data(nodes_json_path, llm_model="", llm_base_url="", primary_metric="", higher_is_better="true")`

LLM 分析完整的 BFTS 树，提取硬件规格、方法论、关键发现和比较结果。`primary_metric` 和 `higher_is_better` 由 pipeline 从 `evaluation_criteria.json` 通过 `tpl_vars` 传入，用于 `summary_stats` 的方向感知归约（v0.7.0+）。

返回（v0.7.0+）：

```text
configurations[*]:
  rank, label, eval_summary
  parameters / measurements / predictions / scores  ← 类型化分离
                                                       (D: results.json 或
                                                        C: _params_dict)
  metrics                                            ← 兼容性 flat union
  _typed_source: "results.json" | "llm_evaluator" | (无)
per_key_summary  (输入参数键 & 「_…」保留键被排除)
summary_stats    { count, primary_metric, direction,
                   primary_metric_best, primary_metric_n,
                   typed_split_coverage }
experiment_context, implementation_overview, report_driven
```

**类型化分离的来源优先级**（D > C > legacy）：

1. `experiments/{run_id}/{node_id}/results.json` — 由 `coding-skill::emit_results` 写入（D 契约）
2. `node.metrics::_params_dict` / `_measurements_dict` — LLM evaluator 在 `MetricSpec.expected_params` 设置下输出（C 契约）
3. 旧路径：`parameters: {}`，扁平 `metrics` 容纳所有内容

**鲁棒性**：LLM 响应解析器剥离 `<think>` 块和 ` ```json ` 围栏，然后从每个候选 `{` 走匹配大括号，按长度降序尝试 `json.loads`。可以救援 `{...} prose {...}` 类型的形状。失败时将原始响应保存到 `{checkpoint_dir}/science_data.debug.txt` 以便事后审计。

模型：`llm_model` 参数 > `LLM_MODEL` 环境变量 > `gpt-4o-mini`。

**存在意义：** 确保 BFTS 内部术语不会泄漏到生成的论文或图表中，并保证输入尺寸描述符（`nnz`、`M`、`K`）不会在 best-of 归约中与测量输出（`GFlops_per_s`、accuracy）混淆。

#### `generate_ear(checkpoint_dir, llm_model="", llm_base_url="")`

在 `<checkpoint>/ear/` 下构建用于可重现性的 **Experiment Artifact Repository (EAR)**。采用 node_report 驱动的布局，与论文配套代码仓库一致：

- `README.md` — 确定性渲染；当 `science_data.json::implementation_overview.architecture` 存在时附带 `Architecture` 段
- `reproduce.sh` — 直接插入 best 节点 `node_report.json::{build_command, run_command}` 的 literal
- `environment.json` — 捕获的运行时环境（Python、平台、pip、硬件）
- `code/` — best 链中 contributing 节点的 `files_changed.added` ∪ `modified` 联合 verbatim 放置（不再有 `code/<node_id>/`）
- `data/` — `checkpoint/uploads/` 的 verbatim 镜像（**仅输入数据**，空则不存在）。**实验输出不打包**——由 `reproduce.sh` 再生成
- `figures/` — checkpoint 根下的 `*.{pdf,png,svg,jpg,jpeg}` 直接置于顶层
- `LICENSE` — 由 `publish.yaml::license` 生成（MIT / Apache-2.0 / BSD-3-Clause / GPL-3.0 / CC-BY-4.0）

两份 ARI 审计日志放在 `<checkpoint>/` 根目录下（位于 `ear/` 之外，因此**不会**被打包进发布产物）：

- `EVOLUTION.md` — Step / Label 形式的搜索轨迹（含 delta 与 concerns）；不出现 `node_id` 等不透明内部标识
- `_provenance.json` — 来源元数据（`from_node_id`、`introduced_by`、`excluded_nodes`）；其内部路径相对于 checkpoint（`ear/code/...`）

其他 ARI 内部元数据（`tree.json`、`science_data.json`、`raw_metrics.json`、`eval_scores.json`、`commands.md`）同样保留在 checkpoint 根目录，不进入 `ear/`。`run_config.json` 移至 `checkpoint/run_config.json`。

返回：`{ear_dir, code_layout, verbatim_files, rendered_files, data_count, figure_count, top_node_id, best_chain_depth, excluded_count, has_readme, has_evolution, has_reproduce_sh, has_license, has_environment, ...}`。

#### `curate_ear(checkpoint_dir)` — v0.7.0

依据 `{checkpoint}/ear/publish.yaml` 的 allowlist 与内置 deny list（`.env*`、`secrets/**`、`*.pem`、`*.key`、`id_rsa`、`id_ed25519`），将 `{checkpoint}/ear/` 策展为 `{checkpoint}/ear_published/`。在 `manifest.lock` 中写入正规化的 `bundle_sha256`（按 `{path, sha256, size}` 排序后 JSON 的 sha256），这就是论文 `\codedigest{...}` 宏所要烧录的 digest。**确定性、无 LLM**。`publish.yaml` 缺失时静默跳过（保持 v0.6.0 checkpoint 后向兼容）。

#### `publish_ear(checkpoint_dir, backend="ari-registry", visibility="staged", dry_run=False)` — v0.7.0

`ari.publish.publish` 的 MCP 薄包装。从 `ear_published/` 构建可复现 tarball（条目排序、mtime/uid/gid 归一化），交由后端（`ari-registry` / `gh` / `zenodo` / `local-tarball`）发布，并将 `publish_record.json` 写入 checkpoint 根目录。首发布始终为 `visibility=staged`（FR-P5）；只有 `auto_promote=true` 且可复现性检查通过时才能晋升为 public。

`ARI_PUBLISH_DRYRUN=1` 强制 dry-run（CI 安全开关）。

#### LICENSE 模板 — v0.7.0

当 `publish.yaml::license` 已设定且作者未自带 `ear/LICENSE` 时，`generate_ear` 会从 `ari-skill-transform/src/licenses/` 写入 **MIT** / **Apache-2.0** / **BSD-3-Clause** / **GPL-3.0** / **CC-BY-4.0** 之一。

---

## ari-skill-web

可插拔检索后端的网络搜索和学术文献检索。**LLM：部分**（仅 `collect_references_iterative` 使用 LLM）。

### 工具

#### `web_search(query, n=5)`

DuckDuckGo 网络搜索。无需 API 密钥。确定性。

#### `fetch_url(url, max_chars=8000)`

通过 BeautifulSoup 获取并提取 URL 中的文本。确定性。

#### `search_arxiv(query, max_results=5)`

arXiv 论文搜索。确定性。

#### `search_semantic_scholar(query, limit=8, extra_queries=None)`

Semantic Scholar API，回退到 arXiv。确定性。

#### `search_papers(query, limit=8)`

调度到所配置的检索后端（`ARI_RETRIEVAL_BACKEND`）：
- `"semantic_scholar"`（默认）— Semantic Scholar API
- `"alphaxiv"` — 通过 HTTP 上的 MCP JSON-RPC 调用 AlphaXiv
- `"both"` — 并行执行并去重

#### `set_retrieval_backend(backend)`

在运行时动态切换检索后端。有效值：`"semantic_scholar"`、`"alphaxiv"`、`"both"`。

#### `collect_references_iterative(experiment_summary, keywords, max_rounds=20, min_papers=10)`

AI Scientist v2 风格的迭代式引用收集。LLM 生成搜索查询并在多轮中选择相关论文。

模型：`ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > `ollama_chat/qwen3:32b`。

#### `list_uploaded_files()`

列出检查点目录中用户上传的文件。确定性。

#### `read_uploaded_file(filename, max_chars=8000)`

从上传文件读取文本内容（带二进制检测）。确定性。

---

## ari-skill-coding

代码生成、执行和文件读取。**LLM：否**（确定性）。

### 工具

#### `write_code(filename, code, work_dir="/tmp/ari_work")`

将源文件写入工作目录。

#### `run_code(filename, work_dir="/tmp/ari_work", timeout=60)`

执行源文件（根据扩展名自动检测语言）。输出会被截断，并附带显示省略字符数和重定向至文件的提示标记。

#### `run_bash(command, work_dir="/tmp/ari_work", timeout=60)`

在工作目录中运行 bash 命令。结果中带有 `truncated` 布尔标志的输出截断。

#### `read_file(filepath, offset=0, limit=2000, work_dir="/tmp/ari_work")`

针对大文件支持分页读取文本。返回内容、用于继续的 `next_offset` 与总行数。

```python
result = read_file("results.csv", offset=0, limit=100)
# 返回值: {"content": "...", "next_offset": 100, "total_lines": 5000}
```

工作目录：`work_dir` 参数 > `ARI_WORK_DIR` 环境变量 > `/tmp/ari_work`。

---

## ari-skill-benchmark

性能分析、绘图和统计检验。**LLM：否**（确定性）。

### 工具

#### `analyze_results(result_path, metrics)`

加载并分析 CSV、JSON 或 NPY 结果文件。返回汇总统计信息。

#### `plot(data, plot_type, output_path, title="", xlabel="", ylabel="")`

生成 matplotlib 图表。图表类型：`bar`、`line`、`scatter`、`heatmap`。

#### `statistical_test(data_a, data_b, test)`

运行 scipy 统计检验：`ttest`、`mannwhitney`、`wilcoxon`。

---

## ari-skill-plot

科学论文图表生成器。两种模式：**确定性模式**（`generate_figures`，P2-safe 的 matplotlib + 固定 schema）与 **LLM 模式**（`generate_figures_llm`，AI-Scientist-v2 风格让 LLM 写代码并执行，可选 VLM 添加图注）。**LLM：混合**（确定性 + P2 例外）。

### 工具

#### `generate_figures(nodes_json_path, output_dir, figure_spec)`

从 `nodes_tree.json` 渲染规范化对比图到 `output_dir`。返回每个生成图的清单（含 caption 与源节点 id）。给定 matplotlib 版本下字节确定。

#### `generate_figures_llm(nodes_json_path, intent, output_dir)`

LLM 检视数据形状与自然语言 `intent`，编写 matplotlib 代码，在与确定性模式相同的 `_run_plot_code` 沙箱中执行，并（可选地）调用 VLM 为生成的图添加 caption。P2 例外。

### 环境变量

| 变量 | 用途 | 默认 |
|---|---|---|
| `VLM_MODEL` | 用于图注生成的 Vision LLM | `openai/gpt-4o` |
| `ARI_LLM_MODEL` | `_llm` 模式中编写 matplotlib 代码的 LLM | （无 — `_llm` 必需）|
| `LLM_MODEL` | 跨技能回退 | （无）|
| `ARI_LLM_API_BASE` | LiteLLM API base 覆盖 | LiteLLM 默认 |
| `OPENAI_API_KEY` | 使用 OpenAI 系模型时所需 | （无）|

### ari-core 边界

`src/server.py` 中 `from ari import cost_tracker`；Phase 4 重构将其迁移到 `ari.public.cost_tracker`。

---

## ari-skill-vlm

视觉语言模型，用于图表和表格质量审查。**LLM：是**（VLM）。

### 工具

#### `review_figure(image_path, context="", criteria=None)`

VLM 审查实验图表。返回评分（0-1）、问题和建议。

#### `review_table(latex_or_path, context="")`

VLM 审查表格（LaTeX 源码或渲染图像）。返回评分、问题和建议。

模型：`VLM_MODEL` 环境变量 > `openai/gpt-4o`。

---

## 编写新技能

1. 创建 `ari-skill-yourskill/src/server.py`：

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("your-skill")

@mcp.tool()
def your_tool(param: str) -> dict:
    """Tool description."""
    # NO LLM calls here
    return {"result": process(param)}

if __name__ == "__main__":
    mcp.run()
```

2. 在 `ari-core/config/workflow.yaml` 中注册。`phase` 控制
   各 pipeline-phase 的 ReAct 智能体是否能看到该技能（单个 phase
   写字符串，多个 phase 写数组）：

```yaml
skills:
  - name: your-skill
    path: '{{ari_root}}/ari-skill-yourskill'
    phase: [paper, reproduce]
```

   有效 phase 值：`bfts`、`paper`、`reproduce`、`all`、`none`。

3. 在 `experiment.md` 的 `## Required Workflow` 中引用工具名称。
