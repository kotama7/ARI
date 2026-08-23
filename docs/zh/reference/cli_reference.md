---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-core/ari/cli_ear.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/clone
    role: implementation
  - path: ari-core/ari/registry
    role: implementation
  - path: ari-core/ari/publish
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/config/reviewer_rubrics
    role: config
  - path: ari-core/ari/pipeline/driver.py
    role: implementation
  - path: ari-skill-paper/src
    role: implementation
  - path: ari-skill-idea/src/server.py
    role: implementation
  - path: ari-skill-vlm/src/review.py
    role: implementation
  - path: ari-skill-web/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/config.py
    role: implementation
  - path: scripts/setup/install_deps.sh
    role: implementation
last_verified: 2026-08-16
---

# ARI CLI 参考

ARI 命令行操作的完整参考。CLI 为基于终端的工作流提供与 [Web 仪表盘](../getting-started/quickstart.md)相同的功能。

---

## 命令概览

| 命令 | 描述 | 仪表盘等效操作 |
|------|------|----------------|
| `ari run` | 运行新实验 | New Experiment 向导 → Launch |
| `ari resume` | 恢复中断的实验 | Experiments 页面 → Resume 按钮 |
| `ari paper` | 仅生成论文（跳过实验） | `POST /api/run-stage {stage: "paper"}` |
| `ari manuscript <subcmd>` | 对 Manuscript Complete attempt 进行 compile / 检查 / repair / lock | — |
| `ari status` | 显示实验树和摘要 | Monitor / Tree 页面 |
| `ari viz` | 启动 Web 仪表盘 | -- |
| `ari projects` | 列出所有过去的实验 | Experiments 页面 |
| `ari show` | 显示某次运行的详细结果 | Results 页面 |
| `ari delete` | 删除检查点 | Experiments 页面 → Delete 按钮 |
| `ari settings` | 查看或修改配置 | Settings 页面 |
| `ari skills-list` | 列出可用工具 | Settings → MCP Skills |
| `ari knowledge <subcmd>` | 查看不可执行的 Knowledge Skill（`search` / `show` / `import` / `validate-manifest` / `validate-registration`，另有 `lock` 与 `use`） | — |
| `ari provider <subcmd>` | 查看可执行的 Capability Provider（`search` / `show` / `probe` / `validate-manifest`，另有 `lock` 与 `bindings`） | — |
| `ari harness <subcmd>` | 查看 Harness 与保证证据（`search` / `show` / `resolve` / `verify` / `validate-manifest` / `validate-registration`，另有 `lock`、`attestation`、`suite`） | — |
| `ari memory ...` | 管理 Letta 记忆后端 | Settings → Memory (Letta) |
| `ari ear <subcmd>` | EAR 策展/发布/晋升生命周期 (v0.7.0) | — |
| `ari clone <ref>` | 拉取策展过的 EAR bundle (file/https/ari/gh/doi)，按 digest 校验 (v0.7.0) | — |
| `ari registry <subcmd>` | 自托管 EAR registry：`serve` / `token issue\|revoke\|list` (v0.7.0) | — |
| `ari migrate node-reports <checkpoint>` | 为旧 (v0.6.0) checkpoint 补齐 `node_report.json` | — |
| `ari doctor claude-code` | `claude_code` LLM 后端健康检查（可执行文件/策略/flag；`--live` 执行一次真实调用） | — |

> **执行模式。**可选启用的 `ari_rqgm` 模式在 v1 中**不新增任何 CLI
> 标志** —— 它完全通过配置启用（workflow.yaml 中的
> `ari.mode: ari_rqgm` + `rqgm.enabled: true`）或 `ARI_MODE` /
> `ARI_RQGM_ENABLED` 环境变量覆盖。上表中的每个命令在默认的
> `simple_bfts` 模式下行为完全相同。见
> [执行模式](../guides/execution_modes.md)。

## `ari manuscript` — 完备性与 publication 操作

这组命令是可选启用的 exploration-to-authoring 编译器的机器可读操作面。它不会在
默认的 `manuscript.mode: "off"` 路径上运行。

```bash
ari manuscript compile CHECKPOINT [--mode audit|enforce] \
  [--profile generic_empirical_v1] [--repair-policy disabled|explicit|auto] \
  [--config WORKFLOW]
ari manuscript status CHECKPOINT [--fail-if-blocked]
ari manuscript inspect CHECKPOINT [--requirement ID] [--lane LANE] [--node ID]
ari manuscript plan-repair CHECKPOINT [--config WORKFLOW]
ari manuscript repair CHECKPOINT [--request REQUEST_ID]... [--config WORKFLOW]
ari manuscript explain-publication CHECKPOINT
ari manuscript lock-publication CHECKPOINT
```

`plan-repair` 对外部系统而言是只读的。`repair` 先把被 admit 的 request 与预算
持久化，再走常规的 bounded research runtime；`ari paper` 从不启动 research
repair。`--mode` 默认为 `audit`；除非同时给出 `--mode enforce`，否则
`--repair-policy auto` 会被拒绝。`--request` 可重复指定，**省略它即选中 plan 中
的每一个 request**——未知的 id 会以 `unknown request IDs: ...` 被拒绝。
`lock-publication` 只有在 decision 是 fresh 且 publishable、并绑定到确切的最终
构建与 PDF 时才会成功。参见[操作员运行手册](../guides/manuscript_complete_operations.md)。

---

## ari run

从实验 Markdown 文件运行新实验。

```bash
ari run <experiment.md> [--config <config.yaml>] [--profile <profile>] \
                        [--virsci-live/--no-virsci-live] \
                        [--virsci-k N] [--virsci-team-size N] \
                        [--virsci-n-authors N] [--virsci-n-papers N] \
                        [--kca-audit/--no-kca-audit] [--task-tag TAG]...
```

| 参数 | 是否必需 | 描述 |
|------|----------|------|
| `experiment.md` | 是 | 实验 Markdown 文件的路径 |
| `--config` | 否 | 自定义配置 YAML（省略则自动生成） |
| `--profile` | 否 | 环境配置文件：`laptop`、`hpc` 或 `cloud` |
| `--virsci-live` / `--no-virsci-live` | 否 | 创意技能：在实时 Semantic Scholar 快照上运行 VirSci 真正的多智能体引擎（vendor-wrap），而非重新实现的讨论循环。设置 `ARI_IDEA_VIRSCI_REAL`。默认关闭。 |
| `--virsci-k` | 否 | VirSci-live 讨论轮数（vendor `group_max_discuss_iteration`）。设置 `ARI_IDEA_VIRSCI_K`。默认 7。 |
| `--virsci-team-size` | 否 | VirSci-live 每个团队最大成员数。设置 `ARI_IDEA_VIRSCI_TEAM_SIZE`。默认 3。 |
| `--virsci-n-authors` | 否 | VirSci-live 用于 `select_coauthors` 的作者池大小。设置 `ARI_IDEA_VIRSCI_N_AUTHORS`。默认 16。 |
| `--virsci-n-papers` | 否 | VirSci-live SPECTER2 检索语料库大小。设置 `ARI_IDEA_VIRSCI_N_PAPERS`。默认 800。 |
| `--kca-audit` / `--no-kca-audit` | 否 | 把 Knowledge、capability-binding 与 assurance 置为 `audit` 模式，并暴露它们的查询 Skill。同时在 `assurance.tolerance_policy` 未设置时将其默认为 `hpc-floating-point/v1`。默认关闭。 |
| `--task-tag` | 否 | 确定性的 Knowledge/Harness 任务标签；多个标签可重复指定。标签会被转小写、去空白并去重，随后记录在该检查点 `workflow.yaml` 的 `resolved_launch.task_tags` 下。 |

这些标志设置创意技能读取的 `ARI_IDEA_VIRSCI_*` 环境变量契约（见下方
[创意生成 (VirSci-live)](#创意生成-virsci-live)）。当 `--virsci-live` 开启时，
假说生成会在实时 Semantic Scholar 快照上运行 VirSci 真正的 `select_coauthors`
+ `generate_idea` 机制；当依赖缺失或发生任何运行时错误时，将以完全相同的
`idea.json` 契约降级到重新实现的循环。

**示例：**

```bash
# 基本运行（自动检测配置）
ari run experiment.md

# 使用环境配置文件
ari run experiment.md --profile laptop

# 使用自定义配置
ari run experiment.md --config ari-core/config/workflow.yaml

# 使用环境变量覆盖
ARI_MAX_NODES=10 ARI_PARALLEL=2 ari run experiment.md

# 在创意生成中使用 VirSci 真正的多智能体引擎（vendor-wrap）
ari run experiment.md --virsci-live --virsci-k 7 --virsci-team-size 3
```

**运行流程：**

1. ARI 生成一个唯一的项目名称（由 LLM 生成的标题）
2. 创建检查点目录：`./workspace/checkpoints/<run_id>/`
3. 在 arXiv 和 Semantic Scholar 上搜索相关论文
4. 通过 VirSci 多智能体讨论生成假说
5. 运行 Best-First Tree Search（BFTS）实验
6. 用 LLM 同行评审评估结果
7. 撰写带有图表和引用的 LaTeX 论文
8. 独立验证可重现性

---

## ari resume

从检查点恢复中断的实验。

```bash
ari resume <checkpoint_dir> [--config <config.yaml>]
```

**示例：**

```bash
ari resume ./workspace/checkpoints/20260328_matrix_opt/
```

加载已保存的树，识别待运行/失败的节点，并从中断处继续运行。

---

## ari paper

仅生成论文，不运行实验。适用于实验已完成的情况。

```bash
ari paper <checkpoint_dir> [--experiment <experiment.md>] [--config <config.yaml>] \
                           [--rubric <rubric_id>] \
                           [--fewshot-mode static|dynamic] \
                           [--num-reviews-ensemble N] \
                           [--num-reflections N]

# 内置评审规范 (23 种): neurips、iclr、icml、cvpr、acl、sc、chi、osdi、
#   stoc、icra、siggraph、nature、usenix_security、aer、econometrica、
#   qje、apsr、ahr、philreview、pmla、journal_generic、workshop、
#   generic_conference。
#   将 <id>.yaml 放入 ari-core/config/reviewer_rubrics/ 即可扩展任何会议。
```

**示例 — 打包默认值 (`generic_conference` 形式):**

```bash
ari paper ./workspace/checkpoints/20260328_matrix_opt/
```

**示例 — Supercomputing (SC) 评审规范 + 5 名集成 + 元审稿:**

```bash
ari paper ./workspace/checkpoints/20260328_matrix_opt/ \
          --rubric sc --num-reviews-ensemble 5
```

> **`--rubric` 到不了论文审稿人手里。** 该标志（以及 `ARI_RUBRIC`）选择的是
> ARI 自身评估器据以推导评分轴、并由谱系决策继承的评审规范（默认
> `neurips`）。`write_paper` 与 `review_paper` 阶段的 `rubric_id` 另有来源：
> workflow 顶层的 `paper_rubric:` 键——打包的
> `ari-core/config/workflow.yaml` 中为 `generic_conference`。论文技能刻意
> 拒绝读取 `ARI_RUBRIC`、也不猜默认值（`resolve_rubric` 会抛出 `rubric_id is
> required`），因此更换审稿会议意味着修改 workflow YAML 中的 `paper_rubric`。

论文管线运行: 数据转换、图表生成、论文撰写、claim-evidence 闸门、VLM 图审阅、
**基于评审规范的论文审阅** (rubric 形式 + reflection + 可选集成 + Area Chair
元审稿)、refine/render 与 finalize，以及 ORS 可复现性轨道
(`ors_generate_rubric` → `ors_audit_rubric` → `ors_seed_sandbox` →
`ors_build_reproduce` → `ors_run_reproduce` → `ors_grade`，由 `paper-re-skill`
与 `replicate-skill` 提供)。

CLI 标志亦可通过环境变量设置: `ARI_RUBRIC`、`ARI_FEWSHOT_MODE`、
`ARI_NUM_REVIEWS_ENSEMBLE`、`ARI_NUM_REFLECTIONS`。其中只有
`ARI_NUM_REVIEWS_ENSEMBLE` 与 `ARI_NUM_REFLECTIONS` 会被审稿人读取
(`review_compiled_paper` 对两者均按 参数 > 环境变量 > 评审规范默认值 解析)。
`--fewshot-mode` 目前是空转的: 它会校验取值并导出 `ARI_FEWSHOT_MODE`，但没有
任何代码读取该变量——`fewshot_mode` 仅来自评审规范 YAML 的 `params` 块。

---

## ari status

显示实验树和摘要统计信息。

```bash
ari status <checkpoint_dir>
```

**示例：**

```bash
ari status ./workspace/checkpoints/20260328_matrix_opt/

# 输出：
# Run: 20260328_matrix_opt
# └── root d=0 success
#     ├── improve_1 d=1 success
#     │   ├── ablation_1 d=2 success
#     │   └── validation_1 d=2 success
#     └── draft_2 d=1 failed
#
#         Summary
# ┏━━━━━━━━━┳━━━━━━━┓
# ┃ Status  ┃ Count ┃
# ┡━━━━━━━━━╇━━━━━━━┩
# │ failed  │     1 │
# │ success │     4 │
# └─────────┴───────┘
```

节点行只带 id、深度和状态——`ari status` **不打印分数**；每节点的 score 字段
已废弃，且该命令没有获得替代品。

---

## ari viz

启动 Web 仪表盘进行可视化实验管理。

```bash
ari viz <checkpoint_dir> [--port <port>]
```

| 参数 | 默认值 | 描述 |
|------|--------|------|
| `checkpoint_dir` | （必需） | 要监控的检查点目录 |
| `--port` | 8765 | 服务端口 |

**示例：**

```bash
# 启动仪表盘
ari viz ./workspace/checkpoints/ --port 8765

# 监控特定运行
ari viz ./workspace/checkpoints/20260328_matrix_opt/ --port 9878
```

在浏览器中打开 `http://localhost:<port>`。仪表盘的使用方法请参阅 [快速入门指南](../getting-started/quickstart.md)。

---

## ari projects

列出所有过去的实验运行。

```bash
ari projects [--checkpoints <dir>]
```

`--checkpoints` 默认为 `./checkpoints`，**而不是** `ari run` 实际写入的
`workspace/checkpoints/` 目录树——在仓库根目录下直接执行 `ari projects` 会报
`Directory not found: checkpoints` 并以 1 退出。请显式指定真实的根目录。

**示例：**

```bash
ari projects --checkpoints ./workspace/checkpoints

# 输出：
#                       ARI Projects
# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━┓
# ┃ ID                         ┃ Nodes ┃ Status  ┃ Score ┃ Modified    ┃
# ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━┩
# │ 20260328_matrix_opt        │    28 │ done    │ 8.40  │ 03/28 14:02 │
# │ 20260327_sorting_benchmark │    12 │ running │ —     │ 03/27 09:15 │
# │ 20260326_sample_experiment │     0 │ empty   │ —     │ 03/26 22:41 │
# └────────────────────────────┴───────┴─────────┴───────┴─────────────┘
```

Status 由 `tree.json`（或 `nodes_tree.json`）推导，取值为
`running` / `done` / `empty` / `corrupt` 之一——它不是成功/失败的判定。
Score 取 `review_report.json` 中的 `scientific_score`（否则 `score`），保留两位
小数；没有评审报告时显示 `—`。

---

## ari show

显示特定实验的详细结果。

```bash
ari show <checkpoint> [--checkpoints-dir <dir>]
```

显示实验树、评审报告摘要和产物列表。`<checkpoint>` 先当作路径使用；只有当该
路径不存在时，才会相对 `--checkpoints-dir`（默认 `./checkpoints`）解析。

---

## ari delete

删除检查点目录。

```bash
ari delete <checkpoint> [--checkpoints-dir <dir>] [--yes]
```

| 标志 | 描述 |
|------|------|
| `--checkpoints-dir` | 仅当 `<checkpoint>` 本身不是已存在的路径时用作基准目录。默认 `./checkpoints` |
| `-y` / `--yes` | 跳过确认提示 |

在删除目录之前，`ari delete` 会清除该检查点的 Letta 记忆命名空间。这一步是
best-effort：失败只记为 warning，本地 `rmtree` 照常进行，留下的孤立 Letta
条目可由 `ari memory prune-local` 后续清理。

---

## ari settings

查看或修改 ARI 配置。

```bash
ari settings [--config <config.yaml>] [options]
```

| 选项 | 描述 |
|------|------|
| `--model <name>` | 设置 LLM 模型名称 |
| `--api-key <key>` | 设置 API 密钥 |
| `--partition <name>` | 设置 SLURM 分区 |
| `--cpus <count>` | 设置 CPU 数量 |
| `--mem <GB>` | 设置内存大小（GB） |

`--config` 默认为 `./config.yaml`，该文件不存在时命令以 1 退出——它不会回退到
打包的 workflow。`--partition`、`--cpus` 与 `--mem` 写入带类型的 `resources:`
块（分别为 `partition` / `cpus` / `mem_gb`）；从 experiment.md 头部解析出的
每次运行的 `slurm_partition` / `slurm_max_cpus` 提示是另一回事，不会被这里的
设置覆盖。

**示例：**

```bash
# 查看当前设置
ari settings

# 更改模型
ari settings --model gpt-4o

# 设置多个选项
ari settings --model qwen3:32b --partition gpu --cpus 64 --mem 128
```

---

## ari migrate node-reports

v0.7.0（task2.md）引入了记录在 `experiments/{run_id}/{node_id}/` 中的
每节点 `node_report.json` 基底。既有 checkpoint 没有这些报告，因此
下游消费者（`generate_ear`、`nodes_to_science_data`、`bfts.expand`、
GUI 的 Tree Report 标签页）会回退到旧的启发式。对每个旧 checkpoint
运行一次本命令即可尽力回填报告：

```bash
ari migrate node-reports /path/to/checkpoint
ari migrate node-reports /path/to/checkpoint --overwrite   # 同时重写已存在的报告
```

无法推断的字段（`original_direction`、`next_steps_hints`）置为 null。

---

## ari doctor claude-code

对 `claude_code` LLM 后端做健康检查（参见
[claude_code_provider.md](./claude_code_provider.md)）：claude 可执行文件与版本、
对解析后配置做 fail-loud 校验、打印 strict 模式下将要执行的确切命令，以及一份静态的
flag 支持报告（`--max-turns` / `--system-prompt-file` 是受支持但隐藏的 flag，
`claude --help` 并不列出它们）。

```bash
ari doctor claude-code           # 仅离线检查
ari doctor claude-code --live    # + 一次真实的 hermetic 调用并做 schema 校验（会消耗 token）
```

---

## ari ear — v0.7.0

针对单个 checkpoint 进行 **Experiment Artifact Repository** 的策展、发布、晋升生命周期管理。策展是确定性的（无 LLM）；发布把策展过的 tarball 送到后端，得到可验证的 ref。

```bash
ari ear curate   <checkpoint> [--show-files] [--json]
ari ear status   <checkpoint>
ari ear publish  <checkpoint> [--backend ari-registry|local-tarball|gh|zenodo] \
                              [--visibility staged] [--dry-run]
ari ear promote  <checkpoint> [--target public|unlisted]
```

| 子命令 | 行为 |
|--------|------|
| `curate` | 应用 `ear/publish.yaml` allowlist 与内置 deny list (`.env*`、`secrets/**`、`*.pem`、`*.key`、`id_rsa`、`id_ed25519`)，写出 `{checkpoint}/ear_published/` + `manifest.lock`（含确定性 `bundle_sha256`）。`publish.yaml` 缺失则静默跳过。 |
| `status` | 显示策展 manifest 摘要 + 可能存在的 `publish_record.json`。 |
| `publish` | 从 `ear_published/` 构建可复现 tarball，送到 backend。首次发布始终 `visibility=staged` (FR-P5)。`ARI_PUBLISH_DRYRUN=1` 强制 `--dry-run`。 |
| `promote` | staged → `public`/`unlisted` 升级。降级被拒。 |

后端：`ari-registry`（自托管）、`local-tarball`（无服务器）、`gh`（GitHub release）、`zenodo`（DOI 注册）。

**端到端示例**：

```bash
# 1. 论文流水线之后由作者策展 bundle
ari ear curate ./workspace/checkpoints/run_20260504_xy/

# 2. 查看通过 allow/deny 规则的内容
ari ear status ./workspace/checkpoints/run_20260504_xy/
# bundle_sha256: 0ccabb16...
# files:         42
# visibility:    staged

# 3. 以 staged 推送到 registry
ari ear publish ./workspace/checkpoints/run_20260504_xy/ --backend ari-registry

# 4. 评审 + 可复现性检查通过后晋升为 public
ari ear promote ./workspace/checkpoints/run_20260504_xy/ --target public
```

`bundle_sha256` 在 `finalize_paper` 阶段被烧入论文的 `\codedigest{...}` 宏。任何持有论文的人，即使 registry 已下线，也能通过 digest 校验任意未来的 bundle 副本。

---

## ari memory

v0.6.0 新增的 Letta 记忆后端管理命令。每个子命令通过 `--checkpoint <path>`
或 `ARI_CHECKPOINT_DIR` 环境变量解析目标检查点。

```bash
ari memory <subcommand> [options]
```

| 子命令 | 描述 |
|--------|------|
| `health` | ping 后端，显示延迟、命名空间哈希、服务器版本 |
| `migrate` | 一次性把 v0.5.x 的 `memory_store.jsonl`（带 `--react` 时还包括 `memory.json`）导入到该检查点的 Letta 集合。原文件被重命名为 `*.migrated-<ts>`。`--dry-run` 只计数不导入 |
| `backup` | 把 Letta 中的记忆快照到 `{ckpt}/memory_backup.v1.json.gz` —— 一个 gzip 压缩、绑定 digest 的 JSON 文档，而非 JSONL。`ari run` 用 `atexit` 注册它，因此只在进程退出时写入一次；`ARI_HANDOFF_MEMORY_OFF=1` 会抑制该自动写入（显式执行该命令仍然有效） |
| `restore` | `backup` 的逆操作。`--on-conflict=skip\|overwrite\|merge`（默认 `skip`）。`ari resume` 时若 Letta 为空则自动调用 |
| `start-local` | 启动本地 Letta 服务器：`--path=auto\|docker\|singularity\|pip` |
| `stop-local` | 停止 docker/singularity/pip Letta（best-effort） |
| `prune-local` | 删除本地 Letta 状态（volumes / venv / `~/.letta`）。需要 `--yes` |
| `compact-access` | 把已轮转的 `memory_access.<ts>.jsonl` 汇总到 `memory_access.summary.json` 并删除原文件 |

**示例：**

```bash
# 检查当前检查点 Letta 是否可达
ARI_CHECKPOINT_DIR=/path/to/ckpt ari memory health

# 升级 v0.5.x 检查点
ari memory migrate --checkpoint /path/to/ckpt --react

# 便携归档
ari memory backup  --checkpoint /path/to/ckpt
rsync -a /path/to/ckpt/ other-host:/home/user/ckpt/
ssh other-host "ari memory restore --checkpoint /home/user/ckpt"

# 若 ari setup 未启动 Letta
ari memory start-local --path=docker
```

---

## ari skills-list

列出所有可用的 MCP 工具及其描述。

```bash
ari skills-list [--config <config.yaml>]
```

---

## 环境变量

### 核心配置

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_BACKEND` | LLM 后端。会被路由的标识符：`ollama`、`openai`、`anthropic` / `claude`、`claude_code` / `claude-code`、`cli-shim` / `cli_shim`；其余取值原样（不加前缀）交给 LiteLLM | `ollama` |
| `ARI_MODEL` | 模型名称 | `qwen3:8b` |
| `OPENAI_API_KEY` | OpenAI API 密钥 | — |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | — |
| `OLLAMA_HOST` | Ollama 服务器 URL | `http://localhost:11434` |
| `LLM_API_BASE` | 通用 API 基础 URL（回退） | — |
| `ARI_MODE` | 执行模式覆盖：`simple_bfts` / `ari_rqgm`（见[执行模式](../guides/execution_modes.md)） | `simple_bfts` |
| `ARI_RQGM_ENABLED` | RQGM 安全联锁覆盖（`0`/`1`/`true`/`false`；须与 `ARI_MODE=ari_rqgm` 一致） | 关 |

### BFTS 配置

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_MAX_NODES` | 最大实验总数 | 50 |
| `ARI_MAX_DEPTH` | 最大树深度 | 5 |
| `ARI_PARALLEL` | 并行实验数 | 4 |
| `ARI_MAX_REACT` | 每个节点的最大 ReAct 步数 | 20 |
| `ARI_TIMEOUT_NODE` | 每个节点的超时时间（秒） | 7200 |

### HPC 配置

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_EXECUTOR` | 执行后端提示。只有 orchestrator 技能会用到它：用于填充子实验的 `executor` 字段，并在非空时重新导出到子运行的环境中。契约是自由格式字符串（≤128 字符），没有枚举校验，`ari-core` 中没有任何代码读取它 | —（未设置） |
| `ARI_SLURM_PARTITION` | SLURM 分区名称 | — |
| `ARI_SLURM_CPUS` | 覆盖 SLURM 作业的 CPU 数 | （`auto_config` 中未设置；PaperBench 复现路径回退为 `8`） |
| `ARI_SLURM_MEM_GB` | 记录到 `resources` 的内存（GB） | — |
| `ARI_SLURM_GPUS` | 记录到 `resources` 的 GPU 数 | — |
| `ARI_SLURM_WALLTIME` | 记录到 `resources` 的 walltime | — |

### 检索与 VLM

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_RETRIEVAL_BACKEND` | 论文搜索的默认提供方: `semantic_scholar`（别名 `semantic-scholar`）/ `arxiv` / `alphaxiv`。`both` 会被**拒绝**——请发两次固定提供方的 `search_papers` 调用再按别名合并 | `semantic_scholar` |
| `ARI_VLM_MODEL` | 图表审阅 VLM 模型。回退到 `VLM_MODEL`；两者都未设置时 VLM 审阅抛出 `ARI_VLM_MODEL must select a visual review model` | —（无默认值） |
| `ARI_ORCHESTRATOR_HTTP_PORT` | orchestrator 技能的 HTTP 端口（必须能解析为 1–65535 的整数）。主机由 `ARI_ORCHESTRATOR_HTTP_HOST` 指定，默认 `127.0.0.1` | `9890` |

### 记忆 (Letta)

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `LETTA_BASE_URL` | Letta 服务器端点 | `http://localhost:8283` |
| `LETTA_API_KEY` | Letta Cloud 必需 | — |
| `LETTA_EMBEDDING_CONFIG` | 归档内存的嵌入句柄（聊天 LLM 不被 ARI 调用，已固定） | `letta-default` |
| `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA` | `auto` / `pip` / `docker` / `singularity` / `none` | `auto` |
| `ARI_MEMORY_LETTA_TIMEOUT_S` | 单次调用超时 | `10` |
| `ARI_MEMORY_LETTA_OVERFETCH` | 祖先后过滤的 over-fetch K 值 | `200` |
| `ARI_MEMORY_LETTA_DISABLE_SELF_EDIT` | 禁用 Letta self-edit (CoW 安全) | `true` |
| `ARI_MEMORY_ACCESS_LOG` | 写入 `{checkpoint}/memory_access.jsonl` | `on` |
| `ARI_MEMORY_ACCESS_LOG_MAX_MB` | 轮转阈值 | `100` |
| `ARI_MEMORY_AUTO_RESTORE` | `ari resume` 时自动恢复备份 | `true` |

### 按阶段模型覆盖

按 `ARI_MODEL_<PHASE>` 读取；未设置或为空时该阶段沿用全局 `cfg.llm.model`。

| 变量 | 阶段 |
|------|------|
| `ARI_MODEL_IDEA` | 创意生成 |
| `ARI_MODEL_CODING` | AgentLoop / ReAct（进程内编码智能体） |
| `ARI_MODEL_BFTS` | BFTS 实验 |
| `ARI_MODEL_EVAL` | 评估器 / 判定 |
| `ARI_MODEL_PAPER` | 论文撰写 |

### 创意生成 (VirSci-live)

创意生成的可选 vendor-wrap 路径。当 `ARI_IDEA_VIRSCI_REAL` 开启时，创意技能
会在实时 Semantic Scholar 快照上运行 VirSci 真正的多智能体机制
（`select_coauthors` + `generate_idea`）；默认关闭则行为不变。`ari run` 的
`--virsci-live` / `--virsci-k` / `--virsci-team-size` / `--virsci-n-authors`
/ `--virsci-n-papers` 标志会设置这些变量。议论 LLM 遵循按阶段的
`ARI_MODEL_IDEA` 模型。需要 `virsci` pip extra；缺失或发生任何运行时错误时，
技能会以完全相同的 `idea.json` 契约降级到重新实现的循环。

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_IDEA_VIRSCI_REAL` | 切换 real vendor-wrap 路径 | (未设置/关闭) |
| `ARI_IDEA_VIRSCI_K` | 讨论轮数（vendor `group_max_discuss_iteration`） | 7 |
| `ARI_IDEA_VIRSCI_TEAM_SIZE` | 最大团队成员数（vendor `max_teammember`） | 3 |
| `ARI_IDEA_VIRSCI_N_AUTHORS` | `select_coauthors` 的作者池 | 16 |
| `ARI_IDEA_VIRSCI_N_PAPERS` | SPECTER2 检索语料库大小 | 800 |
| `ARI_IDEA_VIRSCI_MAX_TEAMS` | 经 `generate_idea` 驱动的团队数上限 | =`n_ideas` |
| `ARI_IDEA_VIRSCI_SPECTER2_MODEL` | 本地查询嵌入器 | `allenai/specter2_base` |

### .env 文件

ARI 会自动加载 `.env` 文件（按以下顺序检查）：

1. `$ARI_CHECKPOINT_DIR/.env` —— 仅在该变量已设置时（最高优先级）
2. `<project_root>/.env` —— `$ARI_ROOT` 已设置时取其值，否则取仓库根目录
3. `<project_root>/ari-core/.env`
4. `~/.env`（最低优先级）

格式：`KEY=VALUE`（以 `#` 开头的行为注释，将被忽略）。

每个文件都以 `override=False` 加载，因此在 shell 中已导出的变量胜过**全部四个**
文件；而在这些文件之间，最先设置某个键的文件获胜。

---

## 在 HPC（SLURM）上运行

```bash
# 设置执行器
export ARI_EXECUTOR=slurm
export ARI_SLURM_PARTITION=your_partition

# 提交为 SLURM 作业
sbatch << 'EOF'
#!/bin/bash
#SBATCH --job-name=ari
#SBATCH --partition=your_partition
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --time=04:00:00
#SBATCH --output=ari_%j.out

# 如果在 GPU 节点上使用 Ollama：
ollama serve &
sleep 10

export ARI_BACKEND=ollama
export ARI_MODEL=qwen3:32b

cd /path/to/ARI
ari run /path/to/experiment.md --profile hpc
EOF
```

**重要规则：**

- 始终使用绝对路径（不要使用 `~` 或相对路径）
- 不要在 SLURM 脚本中重定向 stdout（SLURM 通过 `--output` 自动捕获）
- 除非你的集群要求，否则不要添加 `--account` 或 `-A` 标志

---

## `ari clone <ref> [<dest>]` — v0.7.0+

获取 + 验证 + 解压 精选的 EAR 包 (不执行代码)。
为复现论文的读者提供「一行安装」入口。

### 支持的引用方案

| 方案 | 解析器 |
|---|---|
| `file://<path>` | 本地文件/目录 |
| `https://<url>` | tarball 下载 |
| `ari://<id>` | ari-registry |
| `gh:<user>/<repo>` | GitHub |
| `doi:<doi>` | Zenodo |

### 标志

```
--expect-sha256 <hex>   强制 bundle digest 检验, 不匹配时硬失败。
                        在 --no-extract 下被忽略（见下）。
--no-extract            仅下载 tarball, 不解压。这同时跳过**全部** digest
                        校验——digest 只能从解压出的文件重算，因此报告的
                        bundle_sha256 为空，--expect-sha256 也永远不会被比对。
--registry <name>       将 ari:// 解析限定到 registries.yaml 的某个 registry。
                        请设置 $ARI_REGISTRIES_FILE，或将文件放在
                        ./.ari/registries.yaml。遗留的
                        $HOME/.ari/registries.yaml 已在 v0.5.0 移除，
                        会发出 DeprecationWarning（v1.0 中删除回退）。
                        名称匹配不到任何 registry 时命令以
                        "no ari-registry configured" 失败。
--token <env-or-value>  bearer token (先查环境变量, 否则字面量)。
```

### 校验模型

1. 解析器把 artifact（tarball 或目录）物化到临时目录
2. 协调器解压到 sibling 临时目录（`_stage`），拒绝绝对路径、`..` 逃逸以及
   指向该目录之外的链接
3. 重算每个文件的 sha256, 与 manifest.lock 对比；manifest 列出但 bundle 中
   缺失的文件是硬失败
4. 从规范化 manifest（`{version, files:[{path, sha256, size}]}`，`version: 2`
   时每个文件还含 `role`）重算 bundle digest, 与
   `manifest.lock.bundle_sha256` 对比——但仅当 manifest 确实声明了它时；
   没有 `bundle_sha256` 是被接受的
5. 若指定了 `--expect-sha256`, 必须等于重算 digest, 否则硬失败
6. 全部通过后才 rename 到 dest。失败不会留下半成品 (atomic)。`dest` 必须不存在
   或为空

第 2–5 步只在启用解压时执行；`--no-extract` 只复制原始 artifact，不做任何校验。

### 示例

```bash
# 第 1 步：作者策展 bundle。
ari ear curate <checkpoint>

# 第 2 步：读者带 digest 校验地获取。
ari clone file:///path/to/bundle.tar.gz ./reproduce \
  --expect-sha256 0ccabb16f05c0d3476f2f074fbd229469f11295cf928959526fc93f370c76edf
```

烧入论文的 digest（`\codedigest{...}`）与
`manifest.lock.bundle_sha256` 是同一个值。读者在运行时无需信任
registry；论文本身就是信任锚。

---

## `ari registry` — v0.7.0+

托管策展过的 EAR bundle 的最小 HTTP registry。是 `ari ear publish` 与 `ari clone` 中 `ari://` 解析器的默认后端。可选——`local-tarball` 无需服务器，学术永久性建议 Zenodo / GitHub release。

```bash
ari registry serve   [--host 0.0.0.0] [--port 8290] [--data-dir <dir>]
ari registry token issue  <user>          # 明文仅显示一次
ari registry token revoke <token-id>
ari registry token list
```

启动步骤：

```bash
# 1. 服务端依赖已列在 requirements.txt / lockfile 中，普通的 ./setup.sh
#    就会安装它们。--with-registry 现在只是提示性的。
./setup.sh --with-registry        # 或 pip install fastapi uvicorn[standard] python-multipart

# 2. 指定数据目录并启动（默认端口 8290）
#    注意：v0.5.0 起 $HOME/.ari/registry-data 不再作为默认值。
#    请显式设置 $ARI_REGISTRY_DATA（v1.0 中将移除回退）。
export ARI_REGISTRY_DATA="$PWD/.ari_registry"
./scripts/registry/start_local.sh

# 3. 为用户颁发 token
ari registry token issue alice
# 明文仅显示一次——请妥善保管
```

| 项 | 内容 |
|---|---|
| 端点 | `POST /artifact`、`GET\|HEAD /artifact/<id>`、`GET /artifact/<id>/manifest.lock`、`POST /artifact/<id>/promote?target=...`、`DELETE /artifact/<id>`、`/healthz`、`/version` |
| 认证 | bearer token（sqlite 哈希存储），upload/delete/promote 需所有者 token。`HEAD /artifact/<id>` 与 `GET /artifact/<id>/manifest.lock` **不需要**任何 token——只要知道 id，任何人都能读到 staged bundle 的 digest、长度、可见性以及完整文件清单 |
| 可见性 | `staged`（仅所有者） → `unlisted`（仅知道 id 的人） / `public`（开放）。降级被拒。 |
| Artifact id | `sha256(bundle.tar.gz)[:16]`，内容寻址 |
| 存储 | `${ARI_REGISTRY_DATA}/artifacts/<id>/{bundle.tar.gz, manifest.lock, meta.json}` |

部署模式（详见 [docs/reference/registry.md](registry.md)）：

- `scripts/registry/start_local.sh` — uvicorn + sqlite，单进程。Laptop / dev。
- `scripts/registry/docker-compose.yml` — nginx + uvicorn + sqlite-on-volume。Production。
- `scripts/registry/start_singularity.sh` — Apptainer / Singularity SIF。HPC。

配置客户端的方式是把 `registries.yaml` 写到 `$ARI_REGISTRIES_FILE` 或
`./.ari/registries.yaml`；遗留的 `$HOME/.ari/registries.yaml` 会发出
DeprecationWarning，并在 v1.0 移除。解析器 docstring 里提到的、位于检查点下的
`.ari/registries.yaml` 目前**不可达**——`ari clone` 和 `ari-registry` 发布后端
都不会把检查点传给该查找，所以想让它生效请用 `$ARI_REGISTRIES_FILE` 指向它：

```yaml
registries:
  - name: default
    url: http://127.0.0.1:8290
    token: $ARI_REGISTRY_TOKEN
```

随后 `export ARI_REGISTRY_TOKEN=ari_<颁发的值>`，便可使用 `ari clone ari://<id>`
（或用 `ari clone ari://<registry-name>/<id>` 固定某一条目）或
`ari ear publish --backend ari-registry`。若任何位置都没有 `registries.yaml`，
两者都会回退到由 `$ARI_REGISTRY_URL` + `$ARI_REGISTRY_TOKEN` 构成的单个 registry。
