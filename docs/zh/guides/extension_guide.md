---
sources:
  - path: ari-core/ari/public
    role: implementation
  - path: ari-core/ari/prompts
    role: prompt
  - path: ari-core/ari/configs
    role: config
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-16
---

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

<!-- min_expected_metric: 500 -->
```

2. 运行：

```bash
ari run your_experiment.md
```

就这样。ARI 会读取目标、提出假设并自主搜索。

### 通过 experiment.md 进行领域定制

下面这些才是 `from_experiment_text`（`ari/agent/workflow.py`）真正解析的部分，
其余内容只是 LLM 作为目标阅读的散文：

| 章节 | 用途 | 影响 |
|------|------|------|
| `## Research Goal` | 优化目标 | 驱动 LLM 假设生成 |
| `## Required Workflow` | 使用哪些工具、什么顺序 | 成为 `WorkflowHints.post_survey_hint`（"Follow this workflow from the experiment spec: …"）。`tool_sequence` 由 MCP 实际暴露的工具构建，而非来自本节 |
| `## Provided Files`（也可写 `## 提供ファイル` / `## 提供文件` / `## Local Files`） | 本地输入 | 其中的绝对路径会被复制进每个节点的 `work_dir` |
| `Partition: <name>` / `Max CPUs: <n>` | HPC 放置 | 仅在启用 HPC 时读取；否则由 `ARI_SLURM_PARTITION` / `ARI_SLURM_CPUS` 或探测到的 up 分区补齐 |
| 正文中出现的 SLURM 关键词（`slurm_submit`、`sbatch`、`srun` 等） | 选择提交 / 轮询 / 读取三件套 | 切换为 `slurm_submit` + `job_status` + `run_bash`；在 HPC profile 下，只要设置了 `ARI_SLURM_PARTITION`，没有关键词也一样 |
| `<!-- min_expected_metric: N -->` | 最低可接受值 | 解析进 `WorkflowHints.min_expected_metric`；提取值有**两个及以上**且全部低于它的节点会被标记为 failed（只提取到一个值时不触发该阈值判定）。**只支持数字** —— 负阈值不会被解析 |

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
├── skill.yaml             ← 规范清单（必需，属于被评审的源）
├── mcp.json               ← 由 skill.yaml 派生，禁止手改
├── pyproject.toml         ← 包配置
├── README.md              ← 工具描述和示例
└── REQUIREMENTS.md        ← 设计规格
```

`skill.yaml` 是规范清单，`mcp.json` 是确定性的派生产物：改动清单后用
`python3 scripts/sync_skill_metadata.py --write` 重新生成。
`scripts/check_skill_manifests.py` 会对缺失的 `skill.yaml`（`manifest-missing`）、
不再匹配的 `mcp.json`（`compat-metadata-drift`）、与 `pyproject.toml` 不一致的
`version`（`version-drift`）以及非 `complete` 的 `environment_policy` 报错。
服务器暴露的每个工具都必须在 `skill.yaml` 中声明。

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

在 `ari-core/config/workflow.yaml` 的 `skills:` 块中。`name` 是流水线阶段
引用的注册技能名（随包提供的条目采用 `<领域>-skill` 约定，例如
`paper-skill`），必须完全一致——阶段分发会用 `s.name == stage.skill`
过滤 `cfg.skills`：

```yaml
skills:
  - name: your-skill
    path: /abs/path/to/ari-skill-yourskill
    description: 该技能的说明
    phase: bfts          # bfts | paper | reproduce，或它们的列表
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
仅需编辑 `ari-core/config/workflow.yaml` 的 `pipeline:` 块（旧文件名
`pipeline.yaml` 仍作为回退被接受），无需修改核心代码。

```yaml
pipeline:
  - stage: write_paper
    skill: paper-skill
    tool: write_paper_iterative
    depends_on: [transform_data]
    enabled: true
    phase: paper
    inputs:
      venue: arxiv

  - stage: my_new_stage            # ← 在此添加
    skill: your-skill              # 必须与某个 `skills:` 条目的 name 一致
    tool: your_analysis_tool
    depends_on: [write_paper]
    enabled: true
    phase: paper
    inputs:
      custom_param: value
      nodes_json_path: '{{checkpoint_dir}}/nodes_tree.json'
    outputs:
      file: '{{checkpoint_dir}}/my_new_stage.json'

  - stage: ors_grade
    skill: paper-re-skill
    tool: grade_with_simplejudge
    depends_on: [ors_run_reproduce]
    enabled: true
    phase: paper
```

阶段的键：
- `skill` / `tool` —— 注册技能名与它调用的 MCP 工具。
- `inputs:`（别名 `input:`）—— 工具的关键字参数，支持 `{{var}}` 模板替换
  （`{{checkpoint_dir}}`、`{{run_id}}`、`{{ari_root}}` 等）。`params:` 是
  合并进同一组调用参数的另一个映射，其字符串值同样会做 `{{var}}` 替换，但
  `params:` 的键不会被读入文件内容，且同名的 `inputs:` 键优先。`<key>_from:`
  简写会解析检查点相对文件名**并**读入其内容（另见 `load_inputs:`）。不存在
  `args:` 键。
- `depends_on:` —— 编排器按文件顺序执行阶段，不做拓扑排序，因此请让声明顺序
  与依赖顺序一致；依赖被跳过的阶段也会被跳过（依赖被显式 `enabled: false`
  的情况除外）。
- `phase:` —— `bfts` / `paper` / `reproduce`；决定 GUI 图的分组。
- `segment:` —— `evidence` / `authoring` / `verification`。默认的完整运行会忽略
  它，但分段执行只要发现任何一个启用的阶段没有合法 segment 就拒绝开始，因此
  新增的 `pipeline:` 阶段必须声明它。
- `skip_if_exists:` —— 一个解析后的路径；当它存在且非空（`.json` 还需没有顶层
  `error` 键）时该阶段被跳过。`skip_if_inputs_unchanged:` 指向一个必须仍与磁盘
  一致的 sidecar 契约，从而避免输入已变更后仍复用旧输出。
- `outputs.file` —— 驱动器写入该工具返回值的位置。

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

不存在 `tool_choice` 配置旋钮——`ari/llm/client.py` 自行设置它
（`required` / `auto`）。如果 LLM 不支持函数/工具调用，请改走 CLI-shim
后端（`ARI_BACKEND=cli-shim`），其 OpenAI 兼容服务器会回退到文本工具协议；
同时让实验工作流使用 `## Required Workflow` 来引导逐步执行。

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
- stage: write_paper
  skill: paper-skill
  tool: write_paper_iterative
  inputs:
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

`ari-core/config/default.yaml`（随包提供的 BFTS 默认值）中每个节点的超时是
`timeout_per_node: 7200`（2 小时）。长时间的 MPI 作业可在此处调高——也可以用
`ARI_TIMEOUT_NODE` 按次运行覆盖：

```yaml
bfts:
  timeout_per_node: 14400   # 大型 MPI 作业 4 小时
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
        "idempotency_key": "my-unique-key",   # 必填
        "max_nodes": 10
    })
    run_id = result["run_id"]
```

`idempotency_key` 是必填参数：相同的键会重放已记录的句柄，而不会再提交一次运行。

### 通过 HTTP（面向 CI/CD）

orchestrator 是一个 MCP 服务器，用 `--transport` 选择两种传输：**stdio**（默认）
与 **streamable-http**（`http://{host}:{port}/mcp` 上的 MCP；host 为
`ARI_ORCHESTRATOR_HTTP_HOST` = `127.0.0.1`，port 为
`ARI_ORCHESTRATOR_HTTP_PORT` = 9890）。并不存在带自有路径的 REST/SSE API ——
走 HTTP 调用的仍然是**同一套 MCP 工具面**。若没有
`ARI_ORCHESTRATOR_HTTP_TOKENS_FILE`，`streamable-http` 会拒绝启动：不提供未经
认证的网络控制。

---

## 8. 更改 BFTS 选择策略

选择由 `ari/orchestrator/bfts.py` 中的 `BFTS.select_next_node` 负责，默认是对候选
前沿做一次 **LLM** 判断。在改代码之前，有两个现成的接缝：

- `bfts.deterministic_selector: true` 会完全绕过 LLM，改用 `_select_fallback`
  排序（LLM 选不出来时走的也是它）。它的优先级是：先取 `has_real_data=True`
  的节点，再按 `_fallback_score` 从高到低。
- `bfts.frontier_score` 决定该回退路径使用的打分公式：
  `scientific_plus_diversity`（默认）、`scientific_only`、`depth_penalized`
  （减去 `depth_penalty_lambda * depth`）、`ucb_like`（加上按 `ucb_c` 缩放的
  UCB1 风格项）。

若要引入真正新的策略 —— 例如多目标的帕累托最优选择 —— 需要修改同一文件中的
`_fallback_score` / `_select_fallback`：

```python
def _select_fallback(self, candidates: list[Node]) -> Node:
    """对候选前沿的自定义确定性选择。"""
    real = [n for n in candidates if n.has_real_data]
    pool = real or candidates
    # Example: Pareto-optimal selection for multi-objective
    return pareto_select(pool, objectives=["score", "energy"])
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
| 向 checkpoint 根目录写入新的 ARI 内部文件却不注册 basename | `PathManager.is_meta_file` 无法识别的文件会被复制到每个节点的 `work_dir`，未注册的 `.json` 还会以 role `data_output` 记入 `node_report.json` | 将 basename 加入 `PathManager.META_FILES`（`ari/paths.py`）；若是内部 JSON，还需加入 `_INTERNAL_JSON_NAMES`（`ari/orchestrator/node_report/builder.py`）；并用 `test_new_filenames_are_meta_files` 形式的测试（`ari-core/tests/test_prompt_provenance.py`）固定两者 |

---

## 版本控制和兼容性

- 所有技能工具接口通过 `pyproject.toml` 进行版本控制
- 工具签名的破坏性更改需要次版本号递增
- `ari-core` 依赖于技能接口而非实现（通过 MCP 松耦合）
- 向工具添加新的可选参数始终保持向后兼容
