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
  # ─── EAR 策展/发布/最终化 (v0.7.0) ───
  - stage: ear_curate
    skill: transform-skill
    tool: curate_ear
    depends_on: [generate_ear]
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'
    outputs:
      file: '{{checkpoint_dir}}/ear_curate.status.json'
  - stage: finalize_paper
    skill: paper-skill
    tool: inject_code_availability
    depends_on: [write_paper, ear_curate]
    # 从 ear_published/manifest.lock 与 publish_record.json 自动加载
    # ref/sha/doi，将 \codeavailability/\codedigest/\coderef 宏注入
    # full_paper.tex；若无策展过的 bundle 则静默跳过。
  - stage: ear_publish
    skill: transform-skill
    tool: publish_ear
    depends_on: [ear_curate]
    enabled: false           # 默认禁用；置 true 或传 publish=true
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'
      backend: ari-registry
      visibility: staged
      dry_run: false
    outputs:
      file: '{{checkpoint_dir}}/publish_record.json'
  - stage: merge_reviews
    skill: paper-skill
    tool: merge_reviews
    depends_on: [review_paper, vlm_review_figures]
    # 文本与 VLM 评审结果的事后结构合并（无 LLM）。

  # ─── ORS 自动 rubric 可复现性（PaperBench, v0.7.0）───
  # 取代旧的 `reproducibility_check`。
  - stage: ors_generate_rubric
    skill: replicate-skill
    tool: generate_rubric
    depends_on: [write_paper]
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      output_path: '{{checkpoint_dir}}/ors_rubric.json'
      target_leaf_count: 0     # 0 = 按论文长度自动估算
  - stage: ear_publish          # v0.7.0+：默认启用，使用 local-tarball
    skill: transform-skill
    tool: publish_ear
    depends_on: [ear_curate]
    enabled: true
    inputs:
      backend: local-tarball    # 零依赖；在 checkpoint 旁生成 bundle.tar.gz
      visibility: staged
  - stage: ors_seed_sandbox     # v0.7.0+：从 EAR bundle 确定性播种到沙箱
    skill: paper-re-skill
    tool: fetch_code_bundle
    depends_on: [ear_publish]
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'    # 从 publish_record.json 自动读取 ref
      dest: '{{checkpoint_dir}}/repro_sandbox'
  - stage: ors_build_reproduce  # v0.7.0+：LLM 回退（如已 seed 则跳过）
    skill: paper-re-skill
    tool: build_reproduce_sh
    depends_on: [ors_generate_rubric, ors_seed_sandbox, finalize_paper]
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      output_dir: '{{checkpoint_dir}}/repro_sandbox'
      overwrite: false
  - stage: ors_run_reproduce
    skill: paper-re-skill
    tool: run_reproduce        # Phase 1（在沙箱中执行 reproduce.sh）
    depends_on: [ors_generate_rubric, ors_build_reproduce]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      repo_dir: '{{checkpoint_dir}}/repro_sandbox'
      sandbox_kind: ''         # auto: slurm → docker → apptainer → singularity → local
      timeout_global_sec: 0    # 0 = 使用 rubric.reproduce_contract.max_runtime_sec
      partition: ''            # 留空 → ARI_SLURM_PARTITION → launch_config.json
      cpus: 0                  # 留空 → ARI_SLURM_CPUS（默认 8）
      walltime: ''             # 留空 → ARI_SLURM_WALLTIME → 由 timeout 推导
  - stage: ors_grade
    skill: paper-re-skill
    tool: grade_with_simplejudge   # Phase 2（PaperBench SimpleJudge via LiteLLM）
    depends_on: [ors_run_reproduce]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      repo_dir: '{{checkpoint_dir}}/repro_sandbox'
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      n_runs: 3
      judge_model: gpt-5-mini  # 任意 LiteLLM 可识别的模型 ID

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
  # v0.7.0：PaperBench 形式自动 rubric 生成与审计
  - name: replicate-skill
    path: "{{ari_root}}/ari-skill-replicate"
    phase: paper
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
| `ARI_MODEL_RUBRIC_GEN` | `replicate-skill.generate_rubric` 的生成 LLM (v0.7.0) | `gemini/gemini-2.5-pro` |
| `ARI_MODEL_RUBRIC_AUDIT` | `audit_rubric` 的审计 LLM（与生成器独立） | `anthropic/claude-opus-4-7` |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | 覆盖 `generate_rubric` 的目标叶数。`0` / 未设置时按论文长度自动（约 1 叶 / 75 词，限制在 [50, 400]）。GUI Wizard "Target leaves" 字段。 | (未设置) |
| `ARI_RUBRIC_GEN_TEMPERATURE` | 覆盖生成器 temperature。GUI Wizard "Temperature" 字段。 | (未设置) |
| `ARI_RUBRIC_GEN_TWO_STAGE` | 强制开/关两阶段生成（骨架 + 并行子树），`1`/`true`/`on` vs `0`/`false`/`off`。相比单次调用：叶数约 4 倍、深度增加 1–2 层，API token 消耗约 5 倍。未设置时使用 kwarg 默认（当前 ON）。GUI Wizard "两阶段生成" 切换。 | (未设置，默认 ON) |
| `ARI_MODEL_REPLICATE` | `build_reproduce_sh`（论文 → reproduce.sh，v0.7.0）的复现器 LLM | `claude-opus-4-7` |
| `ARI_MODEL_JUDGE` | `grade_with_simplejudge`（PaperBench Phase 2, v0.7.0；LiteLLM 路由，任意提供方均可）的裁判 LLM | `gpt-5-mini` |
| `ARI_MODEL_LINEAGE` | `decide_lineage_action` 的判定 LLM（lineage decision, v0.7.0）。未设置时按 `ARI_MODEL_EVAL` → `ARI_MODEL` → `ARI_LLM_MODEL` → `gpt-4o-mini` 顺序回退 | (auto) |
| `ARI_MODEL_ROOT_SELECT` | 从 VirSci 池中重选 `ideas[0]` 的 LLM（lineage decision, v0.7.0）。回退顺序与 `ARI_MODEL_LINEAGE` 相同 | (auto) |
| `ARI_PHASE1_SANDBOX` | Phase 1 沙箱：`auto` / `slurm` / `docker` / `apptainer` / `singularity` / `local` | `auto` |
| `ARI_SLURM_WALLTIME` | SLURM Phase 1 沙箱的 `--time` HH:MM:SS（v0.7.0, 已恢复）。留空则从 rubric 的 `max_runtime_sec` 推导。 | (auto) |
| `ARI_PHASE1_DOCKER_IMAGE` | docker 沙箱镜像 | `ubuntu:24.04` |
| `ARI_PHASE1_APPTAINER_IMAGE` / `ARI_PHASE1_SINGULARITY_IMAGE` | Apptainer/Singularity 沙箱镜像 | `docker://ubuntu:24.04` |
| `ARI_PUBLISH_DRYRUN` | 强制 `ari ear publish --dry-run`（CI 安全开关, v0.7.0） | (off) |
| `ARI_REGISTRY_DATA` | `ari registry serve` 的 sqlite + artifact 存储根目录 | `~/.ari/registry-data` |
| `ARI_REGISTRY_TOKEN` | 用于 `ari clone ari://...` / `ari ear publish --backend ari-registry` 的 bearer token | (无) |
| `ARI_REPRO_CLONE_POLICY` | 可复现性沙箱 git shim 策略：`passthrough` / `deny` / `warn` | `passthrough` |

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

## Plan Promote (v0.7.0+)

`plan_promote` 控制 VirSci 的 experiment plan 如何展开到检查点的
`experiment.md`。CLI 传入的用户源 `experiment.md` **不会被修改** —
只有检查点内的副本会被以 HTML 注释为边界自动追加块（重复运行幂等）。

```yaml
plan_promote: index_only          # full | index_only | off
```

| Mode | 内容 | 典型大小 |
|---|---|---|
| `full` | 选定 idea + plan §标题正文 + Alternatives | ~5 KB |
| `index_only` (default) | 选定 idea + plan §标题 + Alternatives | ~1.5 KB |
| `off` | 不追加 | 0 |

Phase 3 评估器和 BFTS expand idea_ctx 都从 `idea.json` 读取**原始** plan，
所以 `full` / `index_only` 主要是 experiment.md 中**人和 paper-skill 看到
什么**的差异。

## Lineage Decision (v0.7.0+)

BFTS 停滞时 LLM judge 决定继续 / 切换备选 idea / 并行 fanout / 终止。
LLM 输出限定为 4 个动作，target index 必须在备选池内，任何错误都
silently 降级为 `continue`，BFTS 循环不会因此 hook 卡住。

```yaml
lineage_decision:
  mode: stagnation_rule           # off | stagnation_rule | every_node
  stagnation_window: 5
  stagnation_threshold: 0.02
  min_nodes_before_decision: 3
  rate_limit_per_run: 5
```

| Mode | 触发 | 成本 |
|---|---|---|
| `off` | 不触发 | 0 |
| `stagnation_rule` (default) | 连续 `stagnation_window` 节点 composite 平稳 | 每 run 0–`rate_limit_per_run` 次 LLM 调用 |
| `every_node` | 每个 BFTS step（LLM 也决定时机） | 每 node 1 次 LLM 调用 |

每次触发的 decision（含 `continue`）追加到 `{checkpoint}/lineage_decisions.jsonl`，
事后可完整复盘「何时停滞、何时切换、何时终止」。`root_idea_selection`
也写入同一文件（不同 `trigger`）。

## Root Idea Selection (v0.7.0+)

VirSci 写完 `idea.json` 后，LLM 根据 venue rubric 与 ancestor research
thread 决定 `ideas[0]` 保持还是换为 `ideas[N]`。Default 保留 VirSci
的分数顺序（`ideas[0]`）；LLM 输出超出范围时同样回退到 `ideas[0]`。
启动时 1 次 LLM 调用，无 per-node 成本。

```yaml
root_idea_selection:
  enabled: true                   # v0.7.0+ default
```

决定记录到 `lineage_decisions.jsonl`（`trigger: "root_idea_selection"`），
并在 `idea.json` 中以 `_root_choice` 持久化。子（recursion）检测到
`_inherited_from` / `_root_choice` 即跳过重选。

## BFTS 调优

通过环境变量控制 BFTS 行为：

```bash
export ARI_MAX_NODES=12      # Explore up to 12 nodes (small run)
export ARI_PARALLEL=4        # Run 4 nodes concurrently
export ARI_EXECUTOR=slurm    # Submit each node as a SLURM job
```

或在 `workflow.yaml` 的 `bfts:` 部分设置默认值（如果您的版本支持）。

---

## EAR 精选 (`ear/publish.yaml`) — v0.7.0+

精选机制让作者通过 allowlist 控制 `{checkpoint}/ear/` 中哪些子集进入
可发布的 bundle (`{checkpoint}/ear_published/` + `manifest.lock`)。
ari-core 内置的 **deny list** 始终强于 `include`,
防止意外公开机密文件。

### Schema (`ari-core/ari/schemas/publish.schema.json`)

```yaml
# 示例：<checkpoint>/ear/publish.yaml
include:                     # 相对 ear/ 的 glob (allowlist)
  - "README.md"
  - "LICENSE"
  - "reproduce.sh"
  - "code/**"                # contributing 链的 verbatim 源文件
  - "data/**"                # 仅上传输入数据；不打包实验输出
  - "figures/**"             # 顶层 figures
  - "environment.json"
# 注：EVOLUTION.md 和 _provenance.json 是位于 ear/ 外（checkpoint 根目录）
# 的 ARI 审计日志，不会被收入发布 bundle。
exclude: []                  # 用户指定排除 (在 include 之后应用)
max_file_mb: 100             # 超过此大小的 allowlist 文件会显式失败
visibility: staged           # staged|public|unlisted|private-token|embargoed-until:YYYY-MM-DD
required: false
auto_promote: false
license: MIT                 # SPDX；ear/LICENSE 据此从模板生成
backend: ari-registry
```

v0.6.0 旧路径（`code/<node_id>/**`、`data/raw_metrics.json`、`logs/**`、`reproducibility/**`）在 v0.7.0 中不再产生；请从旧的 `publish.yaml` 中移除。

### 内置 deny 模式

以下模式 **始终** 排除,即便 `include` 命中:

```
.env, .env.*, **/.env, **/.env.*
**/secrets/**, secrets/**
**/*.pem, **/*.key
**/id_rsa, **/id_ed25519
```

`manifest.lock` 仅记录被排除的数量,不记录路径。

### 行为

- `publish.yaml` **不存在** 时,`ear_curate` 阶段静默跳过,
  论文 Code Availability 段落省略 (与 v0.6.0 检查点完全向后兼容)。
- **bundle digest** (`manifest.lock` 中的 `bundle_sha256`) 是
  按路径排序的文件记录 (path + size + sha256) 的规范 JSON 的 sha256,
  跨机器可复现, 是写入论文的永久真实值。
- 精选是 **原子的**: `max_file_mb` 超限等硬失败时,
  之前正常的 `ear_published/` 不会被破坏。

### CLI

```bash
ari ear curate <checkpoint>            # 友好输出
ari ear curate <checkpoint> --json     # 机器可读
ari ear status <checkpoint>            # 显示 manifest 摘要

ari ear publish <checkpoint> --backend ari-registry --visibility staged
ari ear promote <checkpoint> --target public
```

### Pipeline 集成

`workflow.yaml` 在 paper 管线中,`ear_curate` 阶段插入到 `generate_ear`
与 `generate_figures` 之间, 调用 transform skill 的 `curate_ear`
MCP 工具; `publish.yaml` 不存在时为 no-op。
