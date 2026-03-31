# MCP 技能参考

技能是为 ARI 智能体提供确定性工具的 MCP 服务器。
任何技能都不允许包含 LLM 调用（Post-BFTS 阶段除外：论文生成和审阅）。

## ari-skill-hpc

通过 SLURM 和 Singularity 进行 HPC 作业管理。

### 工具

#### `slurm_submit(script, job_name, partition, nodes=1, walltime="01:00:00", work_dir="")`

提交 SLURM 批处理作业。

```python
result = slurm_submit(
    script="""
#!/bin/bash
#SBATCH --cpus-per-task=32
./compile.sh ./bench.c
NTHREADS=32 ./bench
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
# Returns: {"status": "COMPLETED", "exit_code": 0, "stdout": "score: 284172"}
# 状态值：PENDING、RUNNING、COMPLETED、FAILED、ERROR
```

#### `run_bash(command)`

在登录节点上运行只读 bash 命令。

```python
result = run_bash("cat /path/to/slurm_job_12345.out")
# Returns: {"stdout": "...", "exit_code": 0}
```

#### `singularity_run_gpu(image_path, command, partition, gres="gpu:1")`

使用 GPU 访问运行 Singularity 容器（`--nv` 标志）。

---

## ari-skill-idea

文献调研和想法生成。

### 工具

#### `survey(topic, max_papers=5)`

搜索 arXiv 和 Semantic Scholar。完全确定性（无 LLM）。

```python
result = survey("parallel framework optimization benchmarks")
# Returns: {"papers": [{"title": "...", "abstract": "...", "url": "..."}]}
```

#### `make_metric_spec(experiment_text)`

解析实验 Markdown 以提取评估标准。确定性操作。

```python
result = make_metric_spec(open("experiment.md").read())
# Returns: {
#   "metric_keyword": "score",
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "..."
# }
```

#### `generate_ideas(topic, papers, experiment_context="", n_ideas=3)`

使用 LLM 生成研究假设。仅在 BFTS 启动前调用**一次**（仅限 pre-BFTS）。

---

## ari-skill-evaluator

从实验产物中提取指标。

### 工具

#### `evaluate(artifacts, goal, metric_spec)`

从原始产物文本中提取指标。返回 `has_real_data` 和 `metrics` 字典。
无标量分数 — 仅多目标评估。

#### `make_artifact_extractor(metric_keyword)`

返回用于从输出文本中提取特定指标的 Python 代码。

---

## ari-skill-paper

LaTeX 论文生成和审阅（仅限 Post-BFTS）。

### 工具

#### `generate_section(section, context, venue="arxiv", nodes_json_path="")`

使用 LLM 生成 LaTeX 章节。搜索 `nodes_tree.json` 获取证据。

章节类型：`introduction`、`related_work`、`method`、`experiment`、`conclusion`

```python
result = generate_section(
    section="experiment",
    context="Best result: 284172 score with optimization flags, 32 threads",
    venue="arxiv",
    nodes_json_path="/path/to/nodes_tree.json"
)
```

#### `review_section(latex, context, venue="arxiv")`

审阅 LaTeX 章节。返回优点、缺点和建议。

---

## ari-skill-paper-re

可复现性验证。完全确定性（无 LLM）。

### 工具

#### `extract_claims(paper_text, max_claims=50)`

使用正则表达式模式从论文中提取数值声明。

#### `compare_with_results(claims, actual_metrics, tolerance_pct=10.0)`

在容差范围内将声明与实测指标进行比较。

#### `reproducibility_report(paper_text, actual_metrics, paper_title="", tolerance_pct=10.0)`

生成完整的可复现性报告。

判定阈值：≥80% → REPRODUCED | 40-79% → PARTIAL | <40% → NOT_REPRODUCED

---

## ari-skill-memory

祖先链作用域的节点记忆。防止跨分支污染。

### 工具

#### `add_memory(node_id, text, metadata=None)`
#### `search_memory(query, ancestor_ids, limit=5)`

仅返回 `ancestor_ids`（祖先链）中列出的节点的条目。

#### `get_node_memory(node_id)`
#### `clear_node_memory(node_id)`

存储位置：`~/.ari/memory_store.jsonl`（仅追加 JSONL）

---

## ari-skill-orchestrator

将 ARI 作为 MCP 服务器暴露给外部智能体和 IDE。

### 工具

#### `run_experiment(experiment_md, max_nodes=10, model="qwen3:32b")`

异步提交实验。返回 `run_id`。

#### `get_status(run_id)`

返回运行的进度和当前最佳指标。

#### `get_paper(run_id)`

返回生成的 `experiment_section.tex`。

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

将 BFTS 内部表示转换为面向出版的科学数据格式。剥离所有内部字段，仅暴露科学内容。

**工具：**
- 返回仅包含指标的排名配置

**存在意义：** 确保 BFTS 内部术语不会泄漏到生成的论文或图表中。

---

## ari-skill-web

网络搜索和学术文献检索。

**工具：**
- 通用网络搜索
- arXiv 论文搜索
- Semantic Scholar 引用检索
