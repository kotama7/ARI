# MCP 技能参考

技能是为 ARI 智能体提供工具的 MCP 服务器。工具尽可能保持确定性；使用 LLM 的工具会明确标注。共 14 个技能（9 个默认，5 个附加）。

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

#### `review_compiled_paper(tex_path, pdf_path, figures_manifest_json, paper_summary)`

基于 PDF 的整体论文审阅：文本提取、图表标题评估、结构化质量报告。

模型：`ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > `ollama_chat/qwen3:32b`。

---

## ari-skill-paper-re

通过 ReAct 智能体循环进行可复现性验证。**LLM：是**（ReAct）。

智能体读取生成的论文，提取实验配置，从头重新实现并运行实验，然后将结果与声称的指标进行比较。

### 工具

#### `extract_metric_from_output(output_text, metric_name)`

LLM 从原始输出文本中提取特定指标值。

#### `reproduce_from_paper(paper_path="", paper_text="", experiment_goal="", work_dir="", source_file="", executor="", cpus=64, timeout_minutes=15, tolerance_pct=5.0)`

完整的 ReAct 可复现性验证。内部使用子工具：`write_file`、`run_bash`、`read_file`、`report_metric`、`submit_job`（用于非本地执行器）。

支持的执行器：`local`、`slurm`、`pbs`、`lsf`。最大 ReAct 步数：40。

判定阈值：≥80% → REPRODUCED | 40-79% → PARTIAL | <40% → NOT_REPRODUCED

模型：`ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > `ollama_chat/qwen3:32b`。

---

## ari-skill-memory

祖先链作用域的节点记忆。防止跨分支污染。**LLM：否**（确定性关键词匹配）。

### 工具

#### `add_memory(node_id, text, metadata=None)`

存储标记了 `node_id` 的记忆条目。

#### `search_memory(query, ancestor_ids, limit=5)`

仅返回 `ancestor_ids`（祖先链）中列出的节点的条目。使用关键词匹配。

#### `get_node_memory(node_id)`

检索特定节点的所有记忆。

#### `clear_node_memory(node_id)`

删除特定节点的所有记忆。

存储位置：`~/.ari/memory_store.jsonl`（仅追加 JSONL，可通过 `ARI_MEMORY_PATH` 配置）

---

## ari-skill-orchestrator

将 ARI 作为 MCP 服务器暴露给外部智能体和 IDE。**LLM：否**（委托给 ARI CLI）。

### 工具

#### `run_experiment(experiment_md, max_nodes=10, model="qwen3:32b")`

异步启动 ARI 实验。返回 `run_id`。

#### `get_status(run_id)`

返回运行的进度和当前最佳指标。

#### `list_runs()`

列出所有过去的实验运行。

#### `get_paper(run_id)`

返回生成的论文（LaTeX）。

工作空间：`ARI_WORKSPACE` 环境变量（默认：`~/ARI`）。

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

2. 在 BFTS 配置 YAML 中注册：

```yaml
skills:
  - name: your-skill
    path: /path/to/ari-skill-yourskill
```

3. 在 `experiment.md` 的 `## Required Workflow` 中引用工具名称。

## ari-skill-transform

将 BFTS 内部表示转换为面向出版的科学数据格式。剥离所有内部字段（`node_id`、`label`、`depth`、`parent_id`），仅暴露科学内容（`configurations`、`experiment_context`）。**LLM：是**。

### 工具

#### `nodes_to_science_data(nodes_json_path, llm_model="", llm_base_url="")`

LLM 分析完整的 BFTS 树，提取硬件规格、方法论、关键发现和比较结果。

返回：`{configurations, per_key_summary, experiment_context, summary_stats}`。

模型：`llm_model` 参数 > `LLM_MODEL` 环境变量 > `gpt-4o-mini`。

**存在意义：** 确保 BFTS 内部术语不会泄漏到生成的论文或图表中。

---

## ari-skill-web

网络搜索和学术文献检索。**LLM：部分**（仅 `collect_references_iterative` 使用 LLM）。

### 工具

#### `web_search(query, n=5)`

DuckDuckGo 网络搜索。无需 API 密钥。确定性。

#### `fetch_url(url, max_chars=8000)`

通过 BeautifulSoup 获取并提取 URL 中的文本。确定性。

#### `search_arxiv(query, max_results=5)`

arXiv 论文搜索。确定性。

#### `search_semantic_scholar(query, limit=8, extra_queries=None)`

Semantic Scholar API，回退到 arXiv。确定性。

#### `collect_references_iterative(experiment_summary, keywords, max_rounds=20, min_papers=10)`

AI Scientist v2 风格的迭代式引用收集。LLM 生成搜索查询并在多轮中选择相关论文。

模型：`ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > `ollama_chat/qwen3:32b`。

---

## ari-skill-coding

代码生成和执行。**LLM：否**（确定性）。

### 工具

#### `write_code(filename, code, work_dir="/tmp/ari_work")`

将源文件写入工作目录。

#### `run_code(filename, work_dir="/tmp/ari_work", timeout=60)`

执行源文件（根据扩展名自动检测语言）。

#### `run_bash(command, work_dir="/tmp/ari_work", timeout=60)`

在工作目录中运行 bash 命令。

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

## ari-skill-review

同行评审解析和反驳生成。**LLM：是**。

### 工具

#### `parse_review(review_text)`

LLM 将自由文本评审解析为结构化形式：摘要、关注点（id/严重程度/文本）、问题、建议。

#### `generate_rebuttal(concerns, paper_context, experiment_results)`

LLM 生成 LaTeX 格式的逐点反驳。

#### `check_rebuttal(rebuttal, original_concerns)`

LLM 检查反驳完整性：覆盖率（0-1）、遗漏项、建议。

模型：`ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > `ollama/qwen3:8b`。

---

## ari-skill-vlm

视觉语言模型，用于图表和表格质量审查。**LLM：是**（VLM）。

### 工具

#### `review_figure(image_path, context="", criteria=None)`

VLM 审查实验图表。返回评分（0-1）、问题和建议。

#### `review_table(latex_or_path, context="")`

VLM 审查表格（LaTeX 源码或渲染图像）。返回评分、问题和建议。

模型：`VLM_MODEL` 环境变量 > `openai/gpt-4o`。
