# 扩展指南

本文档描述了如何为新的用例、领域和功能扩展 ARI。
ARI 的设计目标是在添加新实验、技能或流水线阶段时实现零核心代码修改。

---

## 1. 添加新的实验领域

最常见的扩展方式。**无需修改任何代码**。

### 步骤

1. 编写 `your_experiment.md`：

```markdown
# Protein Folding Optimization

## Research Goal
Minimize energy score of protein folding simulation using different force field parameters.

## Required Workflow
1. Call `survey` to find related literature
2. Submit a SLURM job with `slurm_submit`
3. Poll until completion with `job_status`
4. Read results with `run_bash`

<!-- min_expected_metric: -500 -->
<!-- metric_keyword: energy_score -->
```

2. 运行：

```bash
ari run your_experiment.md --config config/bfts.yaml
```

就这样。ARI 会读取目标、提出假设并自主搜索。

### 通过 experiment.md 进行领域定制

| 章节 | 用途 | 影响 |
|------|------|------|
| `## Research Goal` | 优化目标 | 驱动 LLM 假设生成 |
| `## Required Workflow` | 使用哪些工具、什么顺序 | 设置 WorkflowHints 中的 `tool_sequence` |
| `## Hardware Limits` | 硬性约束 | 作为系统提示注入每个智能体步骤 |
| `## SLURM Script Template` | 实验的起始点 | LLM 为每个假设修改此脚本 |
| `<!-- metric_keyword: X -->` | 要提取的指标 | 被评估器和 evaluator-skill 使用 |
| `<!-- min_expected_metric: N -->` | 最低可接受值 | 触发验证检查 |

---

## 2. 添加新的 MCP 技能

无需修改 ari-core 即可为智能体添加新功能（新工具）。

### 技能结构

```
ari-skill-yourskill/
├── src/
│   └── server.py          ← FastMCP 服务器（必需）
├── tests/
│   └── test_server.py     ← 测试（至少 3 个）
├── pyproject.toml         ← 包配置
├── README.md              ← 工具描述和示例
└── REQUIREMENTS.md        ← 设计规格
```

### 服务器模板

```python
# src/server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("your-skill")

@mcp.tool()
def your_tool(param: str, option: int = 10) -> dict:
    """
    Clear description that appears in the LLM's tool list.

    Args:
        param: What this parameter does
        option: What this option controls (default: 10)

    Returns:
        result: The computed output
    """
    # RULE: No LLM calls here. Pure function.
    processed = pure_computation(param, option)
    return {"result": processed}

if __name__ == "__main__":
    mcp.run()
```

### 注册

在 BFTS 配置 YAML 中：

```yaml
skills:
  - name: your-skill
    path: /abs/path/to/ari-skill-yourskill
```

在 `experiment.md` 中：

```markdown
## Required Workflow
1. Call `your_tool` with the experiment parameters
```

### 技能设计检查清单

- [ ] 工具函数内无 LLM 调用（P2）
- [ ] 返回具有清晰键名的 `dict`
- [ ] 工具文档字符串清楚说明输入、输出和副作用
- [ ] 至少 3 个测试，覆盖正常、边界和错误情况
- [ ] README.md 包含使用示例
- [ ] REQUIREMENTS.md 包含设计规格

---

## 3. 添加 Post-BFTS 流水线阶段

在 BFTS 搜索完成后添加自动化后处理。
仅需编辑 `config/pipeline.yaml`，无需修改核心代码。

```yaml
pipeline:
  - stage: generate_paper
    skill: ari-skill-paper
    tool: generate_section
    enabled: true
    args:
      venue: arxiv

  - stage: review
    skill: ari-skill-paper
    tool: review_section
    enabled: true

  - stage: my_new_stage            # ← 在此添加
    skill: ari-skill-yourskill
    tool: your_analysis_tool
    enabled: true
    args:
      custom_param: value

  - stage: reproducibility_check
    skill: ari-skill-paper-re
    tool: reproducibility_report
    enabled: true
```

每个阶段接收：
- `best_node`：BFTS 中得分最高的节点
- `all_nodes`：所有已探索的节点
- `nodes_json_path`：`nodes_tree.json` 的路径
- YAML 中指定的任何 `args`

---

## 4. 支持新的 LLM 后端

通过 litellm 支持。大多数情况下只需修改配置。

```yaml
# OpenAI
llm:
  backend: openai
  model: gpt-4o

# Anthropic
llm:
  backend: anthropic
  model: claude-sonnet-4-5

# 任何 OpenAI 兼容 API（vLLM、LM Studio 等）
llm:
  backend: openai
  model: your-model-name
  base_url: http://your-server:8000/v1
```

如果 LLM 不支持函数/工具调用，请在 `config/bfts.yaml` 中设置 `tool_choice="none"`，
并确保实验工作流使用 `## Required Workflow` 来引导逐步执行。

---

## 5. 为论文生成添加新的发表场所

论文生成通过模板支持多种学术发表场所。

### 添加模板

```
ari-skill-paper/templates/
├── arxiv/
│   └── main.tex          ← 已存在
├── neurips/
│   └── main.tex          ← 已存在
└── your_venue/
    └── main.tex          ← 在此添加
```

### 在场所列表中注册

在 `ari-skill-paper/src/server.py` 中，添加到 `VENUES`：

```python
VENUES = [
    {"id": "neurips", "pages": 9},
    {"id": "icpp", "pages": 10},
    {"id": "sc", "pages": 12},
    {"id": "isc", "pages": 12},
    {"id": "arxiv", "pages": 0},     # unlimited
    {"id": "acm", "pages": 10},
    {"id": "your_venue", "pages": 8},  # ← 添加
]
```

### 在流水线中使用

```yaml
- stage: generate_paper
  skill: ari-skill-paper
  tool: generate_section
  args:
    venue: your_venue   # ← 在此指定
```

---

## 6. 添加多节点/分布式实验

用于需要同时使用多个计算节点的实验。

在 `experiment.md` 中：

```markdown
## SLURM Script Template
```bash
#!/bin/bash
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=32
#SBATCH --cpus-per-task=2

mpirun -np 128 ./my_parallel_program
```
```

在 `config/bfts.yaml` 中增加超时时间：

```yaml
bfts:
  timeout_per_node: 3600   # 大型 MPI 作业 1 小时
```

---

## 7. 将 ARI 暴露给外部系统

使用 `ari-skill-orchestrator` 从其他智能体、IDE 或脚本触发 ARI。

### 从 Claude Desktop 使用

```json
{
  "mcpServers": {
    "ari": {
      "command": "python",
      "args": ["/path/to/ari-skill-orchestrator/src/server.py"]
    }
  }
}
```

然后在 Claude Desktop 中：
> "运行一个实验并报告最佳 score"

### 从另一个智能体使用

```python
from mcp import ClientSession
async with ClientSession(...) as session:
    result = await session.call_tool("run_experiment", {
        "experiment_md": open("experiment.md").read(),
        "max_nodes": 10
    })
    run_id = result["run_id"]
```

### 作为 REST API（通过 orchestrator）

orchestrator MCP 服务器可以通过 HTTP 网关代理，用于 CI/CD 集成。

---

## 8. 更改 BFTS 选择策略

当前策略选择 `has_real_data=True` 且指标值最高的节点。
要更改此策略，请修改 `ari/orchestrator/bfts.py`：

```python
def _select_best_node(self, nodes: list[Node]) -> Node:
    """
    Custom selection strategy.
    Default: highest metric among nodes with real data.
    """
    candidates = [n for n in nodes if n.has_real_data]
    if not candidates:
        return nodes[0]

    # Example: Pareto-optimal selection for multi-objective
    return pareto_select(candidates, objectives=["score", "energy"])
```

---

## 扩展反模式

| 反模式 | 为什么是错误的 | 正确做法 |
|--------|----------------|----------|
| 在 `ari-core` 中添加领域逻辑 | 违反 P1（通用核心） | 放在 `experiment.md` 中 |
| 在技能工具内调用 LLM | 违反 P2（确定性工具） | 仅在 Post-BFTS 流水线中调用 |
| 从评估器返回标量分数 | 违反 P3（多目标） | 返回完整的 `metrics` 字典 |
| 在技能中硬编码模型名称 | 违反 P4（依赖注入） | 通过配置或工具参数传递 |
| 在 SBATCH 中使用相对路径 | 在计算节点上导致路径错误 | 始终使用绝对路径 |

---

## 版本控制和兼容性

- 所有技能工具接口通过 `pyproject.toml` 进行版本控制
- 工具签名的破坏性更改需要次版本号递增
- `ari-core` 依赖于技能接口而非实现（通过 MCP 松耦合）
- 向工具添加新的可选参数始终保持向后兼容
