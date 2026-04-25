# 配置参考

## workflow.yaml（权威开发者配置）

`workflow.yaml` 是整个 ARI 流水线的**唯一真实来源**。
将其放置在 `ari-core/config/workflow.yaml`。

在技能路径中使用 `{{ari_root}}` — 它会解析为 `$ARI_ROOT` 环境变量或项目根目录。

```yaml
llm:
  backend: openai          # ollama | openai | anthropic
  model: gpt-5.2           # Model identifier
  base_url: ""             # Leave empty for OpenAI; set for Ollama/vLLM

author_name: "Artificial Research Intelligence"

resources:
  cpus: 48                 # Default CPU count for reproducibility experiments
  timeout_minutes: 60      # Default job timeout
  executor: slurm          # Job executor: slurm / local / pbs / lsf

# BFTS 阶段（在树搜索期间按顺序执行）
bfts_pipeline:
  - stage: generate_idea
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
  - stage: select_and_run
    skill: hpc-skill
    phase: bfts
  - stage: evaluate
    skill: evaluator-skill
    tool: evaluate_node
    phase: bfts
  - stage: frontier_expand
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
    loop_back_to: select_and_run

# Post-BFTS 流水线阶段
pipeline:
  - stage: search_related_work
    skill: web-skill
    tool: collect_references_iterative
    skip_if_exists: '{{ckpt}}/related_refs.json'
    # ...
  - stage: transform_data
    skill: transform-skill
    tool: nodes_to_science_data
    inputs:
      nodes_json_path: '{{ckpt}}/nodes_tree.json'
      llm_model: '{{llm.model}}'
      llm_base_url: '{{llm.base_url}}'
    outputs:
      file: '{{ckpt}}/science_data.json'
    skip_if_exists: '{{ckpt}}/science_data.json'
  - stage: generate_figures
    skill: plot-skill
    tool: generate_figures_llm
    depends_on: [transform_data]
    # ...
  - stage: write_paper
    skill: paper-skill
    tool: write_paper_iterative
    depends_on: [search_related_work, generate_figures]
    # ...
  - stage: review_paper
    skill: paper-skill
    tool: review_compiled_paper
    depends_on: [write_paper]
    # ...
  - stage: reproducibility_check
    skill: paper-re-skill
    # 由 ari-core/ari/agent/react_driver.py 驱动，而非单个 tool。
    # paper-re 仅提供确定性的两端；ReAct 循环运行在 phase 列表包含
    # `reproduce` 的 MCP 技能之上。
    pre_tool: extract_repro_config
    post_tool: build_repro_report
    depends_on: [write_paper]
    react:
      agent_phase: reproduce
      max_steps: 40
      final_tool: report_metric
      # 将智能体隔离在 checkpoint 根目录之外；路径校验会拒绝引用
      # 沙箱之外文件的工具参数 (论文 .tex 作为 allow-list 放行)。
      sandbox: '{{checkpoint_dir}}/repro_sandbox'
      system_prompt: |
        You are a reproducibility engineer...
      user_prompt: |
        Target: reproduce {{pre.metric_name}} = {{pre.claimed_value}}
        ...

retrieval:
  backend: semantic_scholar    # semantic_scholar | alphaxiv | both
  alphaxiv_endpoint: https://api.alphaxiv.org/mcp/v1

# ── 论文审阅 (基于评审规范，AI Scientist v1/v2 兼容) ─────────────────
# 通过 CLI 标志（--rubric、--fewshot-mode、--num-reviews-ensemble、
# --num-reflections）或环境变量（ARI_RUBRIC、ARI_FEWSHOT_MODE、
# ARI_NUM_REVIEWS_ENSEMBLE、ARI_NUM_REFLECTIONS）覆盖。
# ari-core/config/reviewer_rubrics/ 中内置 16 种评审规范：
#   neurips（默认，v2 兼容）| iclr | icml | cvpr | acl | sc | osdi
#   | usenix_security | stoc | siggraph | chi | icra | nature
#   | journal_generic | workshop | generic_conference
# 加上内置的 `legacy` 回退（v0.5 schema）。新 venue 只需把 <id>.yaml
# 放进 reviewer_rubrics/ 即可，无需修改代码。
#
# Few-shot 语料库管理
# ------------------
# reviewer_rubrics/fewshot_examples/<rubric>/ 下的文件可通过 GUI
# (New Experiment 向导 → Paper Review → Few-shot 示例) 或
# scripts/fewshot/sync.py 管理。viz 服务器暴露的 REST 端点：
#   GET  /api/rubrics                           rubric 列表（向导用）
#   GET  /api/fewshot/<rubric>                  fewshot 示例列表
#   POST /api/fewshot/<rubric>/sync             从 manifest.yaml 拉取
#   POST /api/fewshot/<rubric>/upload           上传一个示例
#   POST /api/fewshot/<rubric>/<example>/delete 删除一个示例

memory:
  # v0.6.0: Letta 是唯一的生产后端。这里的值会在加载时被注入到
  # 技能子进程的环境变量中。智能体的聊天 LLM 句柄已固定为
  # `letta/letta-free`，因为 ari-skill-memory 只调用
  # archival_insert / archival_search 而从不发送聊天消息，
  # 因此该选择器没有运行时效果。
  backend: letta
  letta:
    base_url: http://localhost:8283
    collection_prefix: ari_
    embedding_config: letta-default

container:
  mode: auto                   # auto | docker | singularity | apptainer | none
  image: ""                    # 容器镜像名（空 = 不使用容器）
  pull: on_start               # always | on_start | never

skills:
  # `phase` 控制 ReAct 智能体在哪些 pipeline-phase 下能看到该技能的
  # MCP 工具。字符串仅加入一个 phase，数组可加入多个 phase。标注
  # `reproduce` 的技能会暴露给可复现性 ReAct(见上方 reproducibility_check
  # stage)。`memory-skill` / `transform-skill` / `evaluator-skill`
  # 被刻意排除在 reproduce 之外，以防止智能体访问 BFTS 阶段的产物。
  - name: web-skill
    path: "{{ari_root}}/ari-skill-web"
    phase: [paper, reproduce]
  - name: plot-skill
    path: "{{ari_root}}/ari-skill-plot"
    phase: paper
  - name: paper-skill
    path: "{{ari_root}}/ari-skill-paper"
    phase: paper
  - name: paper-re-skill
    path: "{{ari_root}}/ari-skill-paper-re"
    phase: paper
  - name: memory-skill
    path: "{{ari_root}}/ari-skill-memory"
    phase: bfts
  - name: evaluator-skill
    path: "{{ari_root}}/ari-skill-evaluator"
    phase: bfts
  - name: idea-skill
    path: "{{ari_root}}/ari-skill-idea"
    phase: none
  - name: hpc-skill
    path: "{{ari_root}}/ari-skill-hpc"
    phase: [bfts, reproduce]
  - name: coding-skill
    path: "{{ari_root}}/ari-skill-coding"
    phase: [bfts, reproduce]
  - name: transform-skill
    path: "{{ari_root}}/ari-skill-transform"
    phase: paper
  - name: benchmark-skill
    path: "{{ari_root}}/ari-skill-benchmark"
    phase: bfts
  - name: vlm-skill
    path: "{{ari_root}}/ari-skill-vlm"
    phase: [paper, reproduce]
```

## 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_MAX_NODES` | BFTS 最大探索节点数 | `50` |
| `ARI_PARALLEL` | 并发节点执行数 | `1` |
| `ARI_EXECUTOR` | 执行后端：`local`、`slurm`、`pbs`、`lsf` | `local` |
| `ARI_SLURM_PARTITION` | SLURM 分区名称 | （无） |
| `ARI_SLURM_CPUS` | 覆盖 SLURM 作业的 CPU 数 | （自动检测） |
| `SLURM_LOG_DIR` | SLURM 输出文件存放位置 | （无） |
| `OLLAMA_HOST` | Ollama 服务器地址 | `127.0.0.1:11434` |
| `OPENAI_API_KEY` | OpenAI API 密钥 | （无） |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | （无） |
| `ARI_RETRIEVAL_BACKEND` | 论文搜索后端: `semantic_scholar` / `alphaxiv` / `both` | `semantic_scholar` |
| `VLM_MODEL` | 图表审阅 VLM 模型 | `openai/gpt-4o` |
| `ARI_ORCHESTRATOR_PORT` | orchestrator 技能的 HTTP 端口 | `9890` |
| `LETTA_BASE_URL` | Letta 服务器端点 | `http://localhost:8283` |
| `LETTA_API_KEY` | Letta Cloud 必需 | （无） |
| `LETTA_EMBEDDING_CONFIG` | 归档内存使用的嵌入句柄（智能体的聊天 LLM 不被 ARI 调用，已固定为 `letta/letta-free`） | `letta-default` |
| `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA` | `auto` / `pip` / `docker` / `singularity` / `none` | `auto` |
| `ARI_MEMORY_LETTA_TIMEOUT_S` | 单次调用超时 | `10` |
| `ARI_MEMORY_LETTA_OVERFETCH` | 祖先后过滤的 over-fetch K 值 | `200` |
| `ARI_MEMORY_LETTA_DISABLE_SELF_EDIT` | 禁用 Letta self-edit (CoW 安全) | `true` |
| `ARI_MEMORY_ACCESS_LOG` | 启用 `{checkpoint}/memory_access.jsonl` | `on` |
| `ARI_MEMORY_AUTO_RESTORE` | `ari resume` 时自动恢复备份 | `true` |
| `ARI_RUBRIC` | 评审使用的 rubric_id（例 `neurips`、`sc`、`nature`） | `neurips` |
| `ARI_FEWSHOT_MODE` | `static` / `dynamic` | `static` |
| `ARI_NUM_REVIEWS_ENSEMBLE` | 独立审稿人数量 | `1` |
| `ARI_NUM_REFLECTIONS` | self-reflection 循环轮数 | `5` |

## 记忆后端 (Letta)

v0.6.0 用 [Letta](https://docs.letta.com) 替换了原本的确定性 JSONL 记忆
存储。Letta 可在以下四种模式下运行：

| 模式 | 要求 | 存储 | 备注 |
|------|------|------|------|
| Docker Compose | `docker` + `docker compose` | Postgres | 笔记本默认，支持 pre-filter |
| Singularity / Apptainer | `singularity` / `apptainer` | Postgres | HPC 默认，SLURM 感知的数据目录 |
| pip（无容器） | Python 3.10+ | SQLite | 祖先作用域回落到 over-fetch + post-filter |
| Letta Cloud | API key | 托管 | `LETTA_BASE_URL=https://api.letta.com` |

`ari setup` 自动检测最佳模式。也可通过 `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA`
强制指定。start/stop/health/backup/restore 由 `ari memory` 子命令处理 —
详情见 `docs/zh/cli_reference.md`。

一次性迁移 v0.5.x 检查点：

```bash
ari memory migrate --checkpoint /path/to/ckpt --react
```

## LLM 后端

### Ollama（本地，推荐用于离线 HPC）

```yaml
llm:
  backend: ollama
  model: qwen3:32b
  base_url: http://127.0.0.1:11434
```

### OpenAI

```yaml
llm:
  backend: openai
  model: gpt-4o
```

### Anthropic

```yaml
llm:
  backend: anthropic
  model: claude-sonnet-4-5
```

### 任何 OpenAI 兼容 API（vLLM、LM Studio 等）

```yaml
llm:
  backend: openai
  model: your-model-name
  base_url: http://your-server:8000/v1
```

---

## workflow.yaml 中的模板变量

`inputs:` 中的任何值都支持 `{{variable}}` 替换：

| 变量 | 值 |
|------|-----|
| `{{ckpt}}` | 检查点目录路径 |
| `{{ari_root}}` | ARI 项目根目录（`$ARI_ROOT` 或自动检测） |
| `{{llm.model}}` | `llm:` 部分中的 LLM 模型名称 |
| `{{llm.base_url}}` | `llm:` 部分中的 LLM 基础 URL |
| `{{resources.cpus}}` | `resources:` 部分中的 CPU 数量 |
| `{{resources.timeout_minutes}}` | `resources:` 部分中的超时时间 |
| `{{stages.<name>.outputs.file}}` | 已完成阶段的输出文件路径 |
| `{{author_name}}` | 顶层配置中的作者名称 |
| `{{vlm_feedback}}` | VLM 审阅反馈（在从 `vlm_review_figures` 回环时注入） |
| `{{paper_context}}` | 面向科研的实验摘要 |
| `{{keywords}}` | LLM 生成的搜索关键词 |

---

## skip_if_exists 验证

带有 `skip_if_exists` 的阶段在以下情况下会**重新运行**：
- 输出文件不存在
- 输出文件为空
- 输出文件是包含顶层 `"error"` 键的 JSON 文件

这可以防止损坏的输出悄无声息地阻塞下游阶段。

---

## BFTS 调优

通过环境变量控制 BFTS 行为：

```bash
export ARI_MAX_NODES=12      # Explore up to 12 nodes (small run)
export ARI_PARALLEL=4        # Run 4 nodes concurrently
export ARI_EXECUTOR=slurm    # Submit each node as a SLURM job
```

或在 `workflow.yaml` 的 `bfts:` 部分设置默认值（如果您的版本支持）。
