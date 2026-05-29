---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-core/ari/cli_ear.py
    role: implementation
last_verified: 2026-05-25
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
| `ari status` | 显示实验树和摘要 | Monitor / Tree 页面 |
| `ari viz` | 启动 Web 仪表盘 | -- |
| `ari projects` | 列出所有过去的实验 | Experiments 页面 |
| `ari show` | 显示某次运行的详细结果 | Results 页面 |
| `ari delete` | 删除检查点 | Experiments 页面 → Delete 按钮 |
| `ari settings` | 查看或修改配置 | Settings 页面 |
| `ari skills-list` | 列出可用工具 | Settings → MCP Skills |
| `ari memory ...` | 管理 Letta 记忆后端 | Settings → Memory (Letta) |
| `ari ear <subcmd>` | EAR 策展/发布/晋升生命周期 (v0.7.0) | — |
| `ari clone <ref>` | 拉取策展过的 EAR bundle (file/https/ari/gh/doi)，按 digest 校验 (v0.7.0) | — |
| `ari registry <subcmd>` | 自托管 EAR registry：`serve` / `token issue\|revoke\|list` (v0.7.0) | — |
| `ari migrate node-reports <checkpoint>` | 为旧 (v0.6.0) checkpoint 补齐 `node_report.json` | — |

---

## ari run

从实验 Markdown 文件运行新实验。

```bash
ari run <experiment.md> [--config <config.yaml>] [--profile <profile>]
```

| 参数 | 是否必需 | 描述 |
|------|----------|------|
| `experiment.md` | 是 | 实验 Markdown 文件的路径 |
| `--config` | 否 | 自定义配置 YAML（省略则自动生成） |
| `--profile` | 否 | 环境配置文件：`laptop`、`hpc` 或 `cloud` |

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
```

**运行流程：**

1. ARI 生成一个唯一的项目名称（由 LLM 生成的标题）
2. 创建检查点目录：`./checkpoints/<run_id>/`
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
ari resume ./checkpoints/20260328_matrix_opt/
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

# 内置评审规范 (16 种): neurips (默认，v2 兼容)、iclr、icml、cvpr、acl、
#   sc、chi、osdi、stoc、icra、siggraph、nature、usenix_security、
#   journal_generic、workshop、generic_conference。另外内置 `legacy`
#   回退 (v0.5 schema)。
#   将 <id>.yaml 放入 ari-core/config/reviewer_rubrics/ 即可扩展任何会议。
```

**示例 — v2 兼容默认 (NeurIPS 形式、1-shot、5 reflections):**

```bash
ari paper ./checkpoints/20260328_matrix_opt/
```

**示例 — Supercomputing (SC) 评审规范 + 5 名集成 + 元审稿:**

```bash
ari paper ./checkpoints/20260328_matrix_opt/ \
          --rubric sc --num-reviews-ensemble 5
```

论文管线运行: 数据转换、图表生成、论文撰写、VLM 图审阅、**基于评审规范
的论文审阅** (rubric 形式 + reflection + 可选集成 + Area Chair 元审稿)、
可重现性检查 (`ari/agent/react_driver.py` 驱动的 ReAct 智能体)。

CLI 标志亦可通过环境变量设置: `ARI_RUBRIC`、`ARI_FEWSHOT_MODE`、
`ARI_NUM_REVIEWS_ENSEMBLE`、`ARI_NUM_REFLECTIONS`。

---

## ari status

显示实验树和摘要统计信息。

```bash
ari status <checkpoint_dir>
```

**示例：**

```bash
ari status ./checkpoints/20260328_matrix_opt/

# 输出：
# ── Experiment Tree ──
# root (success) score=153736
# ├── improve_1 (success) score=180200
# │   ├── ablation_1 (success) score=120000
# │   └── validation_1 (success) score=178500
# └── draft_2 (failed)
#
# Summary: 4 success, 1 failed, 0 running, 0 pending
```

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
ari viz ./checkpoints/ --port 8765

# 监控特定运行
ari viz ./checkpoints/20260328_matrix_opt/ --port 9878
```

在浏览器中打开 `http://localhost:<port>`。仪表盘的使用方法请参阅 [快速入门指南](../getting-started/quickstart.md)。

---

## ari projects

列出所有过去的实验运行。

```bash
ari projects [--checkpoints <dir>]
```

**示例：**

```bash
ari projects

# 输出：
# ID                              Nodes  Status    Best Score  Modified
# 20260328_matrix_opt             28     complete  153736      2h ago
# 20260327_sorting_benchmark      12     complete  0.95        1d ago
# 20260326_benchmark_test          5      failed    --          2d ago
```

---

## ari show

显示特定实验的详细结果。

```bash
ari show <checkpoint> [--checkpoints-dir <dir>]
```

显示实验树、评审报告摘要和产物列表。

---

## ari delete

删除检查点目录。

```bash
ari delete <checkpoint> [--yes]
```

| 标志 | 描述 |
|------|------|
| `-y` / `--yes` | 跳过确认提示 |

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
ari ear curate ./checkpoints/run_20260504_xy/

# 2. 查看通过 allow/deny 规则的内容
ari ear status ./checkpoints/run_20260504_xy/
# bundle_sha256: 0ccabb16...
# files:         42
# visibility:    staged

# 3. 以 staged 推送到 registry
ari ear publish ./checkpoints/run_20260504_xy/ --backend ari-registry

# 4. 评审 + 可复现性检查通过后晋升为 public
ari ear promote ./checkpoints/run_20260504_xy/ --target public
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
| `migrate` | 一次性把 v0.5.x 的 `memory_store.jsonl`（带 `--react` 时还包括 `memory.json`）导入到该检查点的 Letta 集合。原文件被重命名为 `*.migrated-<ts>` |
| `backup` | 把 Letta 中的记忆快照到 `{ckpt}/memory_backup.jsonl.gz`（gzip 压缩 JSONL）。在管线阶段边界与关闭时自动写入 |
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
| `ARI_BACKEND` | LLM 后端（`ollama` / `openai` / `anthropic` / `claude`） | `ollama` |
| `ARI_MODEL` | 模型名称 | `qwen3:8b` |
| `OPENAI_API_KEY` | OpenAI API 密钥 | — |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | — |
| `OLLAMA_HOST` | Ollama 服务器 URL | `http://localhost:11434` |
| `LLM_API_BASE` | 通用 API 基础 URL（回退） | — |

### BFTS 配置

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_MAX_NODES` | 最大实验总数 | 50 |
| `ARI_MAX_DEPTH` | 最大树深度 | 5 |
| `ARI_PARALLEL` | 并行实验数 | 4 |
| `ARI_MAX_REACT` | 每个节点的最大 ReAct 步数 | 80 |
| `ARI_TIMEOUT_NODE` | 每个节点的超时时间（秒） | 7200 |

### HPC 配置

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_EXECUTOR` | 执行后端（`local` / `slurm` / `pbs` / `lsf`） | `local` |
| `ARI_SLURM_PARTITION` | SLURM 分区名称 | — |
| `ARI_SLURM_CPUS` | 覆盖 SLURM 作业的 CPU 数 | (自动检测) |

### 检索与 VLM

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_RETRIEVAL_BACKEND` | 论文搜索: `semantic_scholar` / `alphaxiv` / `both` | `semantic_scholar` |
| `VLM_MODEL` | 图表审阅 VLM 模型 | `openai/gpt-4o` |
| `ARI_ORCHESTRATOR_PORT` | orchestrator 技能的 HTTP 端口 | `9890` |

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
| `ARI_MEMORY_BACKUP_INTERVAL_S` | 运行期间机会性备份间隔（0 = 关闭） | `0` |

### 论文评审 (Rubric)

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_RUBRIC` | 评审使用的 rubric_id（如 `neurips`、`sc`、`nature`、`generic_conference`） | `neurips` |
| `ARI_FEWSHOT_MODE` | `static`（内置示例）/ `dynamic`（从 OpenReview 等动态获取） | `static` |
| `ARI_NUM_REVIEWS_ENSEMBLE` | 独立审稿人数量（N>1 时启用 Area Chair 元审稿） | `1` |
| `ARI_NUM_REFLECTIONS` | self-reflection 循环轮数 | `5` |

### 按阶段模型覆盖

| 变量 | 阶段 |
|------|------|
| `ARI_MODEL_IDEA` | 创意生成 |
| `ARI_MODEL_BFTS` | BFTS 实验 |
| `ARI_MODEL_PAPER` | 论文撰写 |

### .env 文件

ARI 会自动加载 `.env` 文件（按以下顺序检查）：

1. `<checkpoint_dir>/.env`（最高优先级）
2. `<project_root>/.env`
3. `<project_root>/ari-core/.env`
4. `~/.env`（最低优先级）

格式：`KEY=VALUE`（以 `#` 开头的行为注释，将被忽略）。

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

### 支持的引用方案 (按 PR 渐进发布)

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
--no-extract            仅下载 tarball, 不解压。
--registry <name>       将 ari:// 解析限定到 registries.yaml 的某个 registry。
                        请设置 $ARI_REGISTRIES_FILE，或将文件放在
                        $ARI_CHECKPOINT_DIR/.ari/registries.yaml 下。
                        遗留的 $HOME/.ari/registries.yaml 已在 v0.5.0 移除，
                        会发出 DeprecationWarning（v1.0 中删除回退）。
--token <env-or-value>  bearer token (先查环境变量, 否则字面量)。
```

### 校验模型

1. 解析器把 artifact 物化到临时目录
2. 协调器解压到 sibling 临时目录
3. 重算每个文件的 sha256, 与 manifest.lock 对比
4. 从规范化的 files-only manifest 重算 bundle digest, 与
   `manifest.lock.bundle_sha256` 对比
5. 若指定了 `--expect-sha256`, 必须等于重算 digest, 否则硬失败
6. 全部通过后才 rename 到 dest。失败不会留下半成品 (atomic)

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
# 1. 安装服务端依赖（默认安装跳过以保持精简）
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
| 端点 | `POST /artifact`、`GET\|HEAD /artifact/<id>`、`GET /artifact/<id>/manifest.lock`、`POST /artifact/<id>/promote`、`DELETE /artifact/<id>`、`/healthz`、`/version` |
| 认证 | bearer token（sqlite 哈希存储），upload/delete/promote 需所有者 token |
| 可见性 | `staged`（仅所有者） → `unlisted`（仅知道 id 的人） / `public`（开放）。降级被拒。 |
| Artifact id | `sha256(bundle.tar.gz)[:16]`，内容寻址 |
| 存储 | `${ARI_REGISTRY_DATA}/artifacts/<id>/{bundle.tar.gz, manifest.lock, meta.json}` |

部署模式（详见 [docs/reference/registry.md](registry.md)）：

- `scripts/registry/start_local.sh` — uvicorn + sqlite，单进程。Laptop / dev。
- `scripts/registry/docker-compose.yml` — nginx + uvicorn + sqlite-on-volume。Production。
- `scripts/registry/start_singularity.sh` — Apptainer / Singularity SIF。HPC。

客户端 `registries.yaml` 的位置（按优先级）：`$ARI_REGISTRIES_FILE` 显式覆盖、
`$ARI_CHECKPOINT_DIR/.ari/registries.yaml`、或 `./.ari/registries.yaml`。
$HOME/.ari/registries.yaml 自 v0.5.0 起已废弃，回退在 v1.0 移除：

```yaml
registries:
  - name: default
    url: http://127.0.0.1:8290
    token: $ARI_REGISTRY_TOKEN
```

随后 `export ARI_REGISTRY_TOKEN=ari_<颁发的值>`，便可使用 `ari clone ari://<id>` 或 `ari ear publish --backend ari-registry`。
