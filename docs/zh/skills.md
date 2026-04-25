# MCP 技能参考

技能是为 ARI 智能体提供工具的 MCP 服务器。工具尽可能保持确定性；使用 LLM 的工具会明确标注。共 13 个技能（12 个默认，1 个附加）。

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

可复现性验证辅助。**LLM：是**（两次一次性 LLM 调用，技能内部不再包含循环）。

自 v0.6.0 起，ReAct 循环位于 `ari-core/ari/agent/react_driver.py`。当 stage 声明 `react:` 块时，由 `ari.pipeline._run_react_stage` 驱动循环。本技能仅保留可复现流程的两个确定性端点：

```
pre_tool (extract_repro_config)  →  react_driver  →  post_tool (build_repro_report)
          一次 LLM                    受 MCP 白名单           一次 LLM
          (paper-re)                  约束的 ReAct            (paper-re)
```

ReAct 循环只能看到 `workflow.yaml` 中 `skills[].phase` 列表包含 `reproduce` 的 MCP 工具（默认：`web-skill` / `vlm-skill` / `hpc-skill` / `coding-skill`）。`memory-skill` / `transform-skill` / `evaluator-skill` 被刻意排除，因此智能体无法访问 BFTS 阶段的产物（`nodes_tree.json`、祖先记忆等）。

### 工具

#### `extract_repro_config(paper_path="", paper_text="")`

一次性 LLM 调用。读取论文文本（或 `paper_path`，`.pdf` 通过 `pdftotext` 转换），抽取作者在摘要/结论中宣传的值及其邻近的精确实验参数，返回 `{metric_name, claimed_value, description, threads}`。

#### `build_repro_report(claimed_config, actual_value, actual_unit="", actual_notes="", tolerance_pct=5.0)`

一次性 LLM 调用，生成 2-3 句判定说明。在 `react_driver` 完成后由流水线调用。`actual_value` 是 ReAct 智能体通过 `report_metric` 上报的值（若智能体未能得到可靠测量则为 `None`）。

判定阈值：在 `tolerance_pct` 内 → REPRODUCED | 20% 内 → PARTIAL | 其它 → NOT_REPRODUCED | `actual_value is None` → UNVERIFIABLE。

#### `extract_metric_from_output(output_text, metric_name)`

供 ReAct 智能体从原始基准输出中解析数值指标的辅助工具（LLM 抽取 + regex 回退）。pre/post 流水线端点不会调用它。

模型：`ARI_MODEL_PAPER` > `ARI_LLM_MODEL` > `LLM_MODEL` > `ollama_chat/qwen3:32b`。

---

## ari-skill-memory

祖先作用域的节点记忆（v0.6.0 起由 [Letta](https://docs.letta.com) 支持）。防止跨分支污染，ReAct 轨迹也存放在同一个 Letta 代理中。**LLM：△**（基于嵌入的检索。P2 放宽详见 `docs/PHILOSOPHY.md`）。

### 工具

#### `add_memory(node_id, text, metadata=None)`

存储标记了 `node_id` 的条目。**Copy-on-Write**：若 `node_id` 与 `$ARI_CURRENT_NODE_ID` 不一致，则拒绝写入。

#### `search_memory(query, ancestor_ids, limit=5)`

仅按 Letta 相关度分数（`score` ∈ [0, 1]）返回 `ancestor_ids` 中的节点条目。兄弟/子节点永远不会返回。

#### `get_node_memory(node_id)`

按时间顺序返回特定节点的所有条目（无评分）。

#### `clear_node_memory(node_id)`

仅用于调试的单节点清除。与 `add_memory` 使用相同的 CoW 规则。

#### `get_experiment_context()`

返回 Letta 核心记忆中种入的稳定事实（`experiment_goal`、`primary_metric`、`hardware_spec` 等）。种入仅在首个节点的 `generate_ideas` 完成时（即 `primary_metric` 被确定的时刻）执行一次，在此之前调用会返回 `{}`。之后可安全反复调用（带 60 秒进程内缓存）。

存储：每个检查点拥有一个 Letta 代理（两个集合 `ari_node_*` 与 `ari_react_*`）。可移植快照位于 `{ARI_CHECKPOINT_DIR}/memory_backup.jsonl.gz`，写/读遥测位于 `{ARI_CHECKPOINT_DIR}/memory_access.jsonl`。v0.5.x 的 JSONL（`memory_store.jsonl`、`~/.ari/global_memory.jsonl`）已移除；使用 `ari memory migrate --react` 迁移。跨实验“全局记忆”已弃用。

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

#### `nodes_to_science_data(nodes_json_path, llm_model="", llm_base_url="")`

LLM 分析完整的 BFTS 树，提取硬件规格、方法论、关键发现和比较结果。

返回：`{configurations, per_key_summary, experiment_context, summary_stats}`。

模型：`llm_model` 参数 > `LLM_MODEL` 环境变量 > `gpt-4o-mini`。

**存在意义：** 确保 BFTS 内部术语不会泄漏到生成的论文或图表中。

#### `generate_ear(checkpoint_dir, llm_model="", llm_base_url="")`

在 `<checkpoint>/ear/` 下构建用于可重现性的 **Experiment Artifact Repository (EAR)**。内容：

- `README.md` 与 `RESULTS.md`（条件允许时由 LLM 生成，否则使用确定性回退）
- `code/<node_id>/` — 从每个节点的实验目录复制的源文件
- `data/raw_metrics.json`、`data/science_data.json`、`data/figures/`
- `logs/bfts_tree.json`、`logs/eval_scores.json`
- `reproducibility/environment.json`（Python 版本、平台、pip 包、硬件）
- `reproducibility/run_config.json`、`reproducibility/commands.md`

返回：`{ear_dir, manifest}` — 所有生成文件的路径。

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
