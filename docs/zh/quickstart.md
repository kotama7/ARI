# ARI 快速入门指南

本指南将带你完成 ARI 的安装、AI 模型的选择，以及使用 **Web 仪表盘** 运行你的第一个实验。无需编程经验。

如需使用 CLI（命令行），请参阅 [CLI 参考](cli_reference.md)。

> **安装前先预览**
>
> - 🎬 **仪表板演示视频** — [`movie/zh/ari_dashboard_demo.mp4`](../movie/zh/ari_dashboard_demo.mp4) 完整展示 Web UI 的实际操作。
> - 📄 **示例输出论文** — [`sample_paper.pdf`](../sample_paper.pdf) 是 ARI 实际运行生成的论文，包含图表、引用和可复现性验证报告。

---

## 准备工作

| 需求 | 详情 |
|------|------|
| **操作系统** | Linux 或 macOS（Windows 请使用 WSL2） |
| **Python** | 3.10 或更高版本 |
| **Git** | 用于克隆代码仓库 |
| **Web 浏览器** | Chrome、Firefox、Safari 或 Edge |

可选（但推荐）：

| 工具 | 用途 |
|------|------|
| **conda / miniconda** | 更便捷地安装 LaTeX 和 PDF 工具（无需 sudo） |
| **Ollama** | 在本地免费运行 AI 模型 — 无需 API 密钥，无需付费 |
| **LaTeX** | 仅在需要 ARI 生成 PDF 论文时使用 |

---

## 第 1 步：安装 ARI

打开终端并运行：

```bash
git clone https://github.com/kotama7/ARI.git
cd ARI
bash setup.sh
```

安装脚本会自动检测你的操作系统并安装所有必要的依赖。支持 Linux、macOS 和 WSL2 — 无论是否有 conda 和 sudo 均可使用。

安装完成后，你将看到 **"Setup Complete"** 以及后续操作说明。

---

## 第 2 步：选择 AI 模型

ARI 需要一个 AI 模型（LLM）来进行思考、规划和运行实验。请从以下选项中选择：

### 选项 A：Ollama — 免费，在本地运行（推荐）

无需注册账户，无需 API 密钥，无需付费。所有计算都在本地完成。

```bash
# 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh     # Linux
# brew install ollama                              # macOS

# 下载模型
ollama pull qwen3:8b

# 启动服务器（保持此终端窗口打开）
ollama serve
```

设置环境变量（打开一个新终端）：

```bash
export ARI_BACKEND=ollama
export ARI_MODEL=qwen3:8b
```

> **如何选择模型大小？**
>
> | 模型 | 所需内存 | 质量 |
> |------|----------|------|
> | `qwen3:8b` | 16 GB | 良好 — 非常适合入门 |
> | `qwen3:14b` | 32 GB | 更好 |
> | `qwen3:32b` | 64 GB | 最佳 |

### 选项 B：OpenAI API（云端，付费）

```bash
export ARI_BACKEND=openai
export ARI_MODEL=openai/gpt-4o
export OPENAI_API_KEY=sk-...     # 从 https://platform.openai.com/api-keys 获取
```

### 选项 C：Anthropic API（云端，付费）

```bash
export ARI_BACKEND=claude
export ARI_MODEL=anthropic/claude-sonnet-4-5
export ANTHROPIC_API_KEY=sk-ant-...  # 从 https://console.anthropic.com/ 获取
```

> **提示：** 将 `export` 语句添加到 `~/.bashrc` 或 `~/.zshrc` 中以使其永久生效。

---

## 第 3 步：启动仪表盘

启动 ARI Web 仪表盘：

```bash
ari viz ./checkpoints/ --port 8765
```

打开浏览器，访问：**http://localhost:8765**

你将看到 ARI 主界面：

![ARI 主页](images/zh/dashboard_home.png)

左侧边栏提供了所有仪表盘页面的导航：

| 页面 | 描述 |
|------|------|
| **Home** | 概览页面，包含快捷操作和最近的实验 |
| **Experiments** | 所有过去实验运行的列表 |
| **Monitor** | 实时管线进度，带 D3 树形可视化 |
| **Tree** | 完整的 BFTS 实验树 — 点击节点查看详情 |
| **Results** | 查看生成的论文、评审和可重现性报告 |
| **New Experiment** | 创建并启动新实验的向导 |
| **Ideas** | VirSci 生成的研究假说 |
| **Workflow** | 编辑 BFTS 后管线配置 |
| **Settings** | 配置 LLM、API 密钥、SLURM 和语言 |

---

## 第 4 步：创建你的第一个实验（向导）

点击侧边栏中的 **"New Experiment"**（或主页上的蓝色 **"New Experiment"** 按钮）。

![实验向导](images/zh/dashboard_wizard.png)

向导将引导你完成 4 个步骤：

### 步骤 1/4 — 选择模式

| 模式 | 适用场景 |
|------|----------|
| **Chat** | 适合初学者。用自然语言描述你的需求，AI 将帮助你将其细化为正式的实验。 |
| **Write MD** | 直接用 Markdown 编写或粘贴你的实验描述。 |
| **Upload** | 从你的电脑上传已有的 `experiment.md` 文件。 |

**推荐初学者使用 Chat 模式。** 只需输入你想优化或研究的内容，例如：

> "我想找到在我的笔记本电脑上运行实验的最快方法"

AI 会提出澄清性问题，并自动生成实验文件。

### 步骤 2/4 — 范围

配置实验的规模：

| 设置 | 控制内容 | 首次运行建议值 |
|------|----------|----------------|
| **Max Depth** | 搜索树的最大深度 | 3 |
| **Max Nodes** | 运行的总实验数 | 5–10 |
| **Max ReAct Steps** | 每个实验的推理步数 | 80（默认值） |
| **Timeout** | 每个实验的超时时间（秒） | 7200（默认值） |
| **Parallel Workers** | 同时运行的实验数 | 2–4 |

> **提示：** 首次运行建议从小规模开始（5–10 个节点，深度 3）。之后可以随时增加。

### 步骤 3/4 — 资源

选择你的 LLM 提供商和模型：

- **OpenAI / Anthropic / Ollama / Custom** — 从下拉菜单中选择
- 对于 Ollama，可以输入任意模型名称（例如 `qwen3:8b`）
- 如果在集群上运行，可配置 SLURM/HPC 设置

### 步骤 4/4 — 启动

检查你的设置并点击 **Launch**。ARI 将：

1. 搜索相关学术论文
2. 通过 VirSci 多智能体讨论生成研究假说
3. 使用 Best-First Tree Search（BFTS）运行实验
4. 用 LLM 同行评审评估结果
5. 撰写带有图表和引用的 LaTeX 论文
6. 独立验证可重现性

---

## 第 5 步：监控实验

启动后，**Monitor** 页面会显示实时进度：

![监控页面](images/zh/dashboard_monitor.png)

- **管线阶段** 显示在顶部（Idea → BFTS → Paper → Review）
- **节点树** 以颜色编码显示实验进度
- **日志** 实时输出

### 实验树

点击侧边栏中的 **Tree** 查看完整的交互式实验树：

![树视图](images/zh/dashboard_tree.png)

- **绿色** 节点 = 成功
- **红色** 节点 = 失败
- **蓝色** 节点 = 运行中
- **灰色** 节点 = 等待中

点击任意节点查看详情：

| 标签页 | 显示内容 |
|--------|----------|
| **Overview** | 状态、指标、执行时间、评估摘要 |
| **Trace** | AI 智能体执行的每一个工具调用（逐步详情） |
| **Code** | 该实验生成的源代码 |
| **Output** | 任务标准输出、基准测试结果 |

---

## 第 6 步：查看结果

实验完成后，前往 **Results** 页面：

![结果页面](images/zh/dashboard_results.png)

在这里你可以：

- 阅读生成的论文（LaTeX / PDF）
- 查看自动同行评审的评分和反馈
- 检查可重现性验证报告
- 下载所有产物

输出文件保存在 `./checkpoints/<run_id>/` 中：

| 文件 | 描述 |
|------|------|
| `full_paper.tex / .pdf` | 完整生成的论文 |
| `review_report.json` | 同行评审评分和反馈 |
| `reproducibility_report.json` | 独立的可重现性验证 |
| `tree.json` | 包含所有指标的完整实验树 |
| `science_data.json` | 清洗后的数据（无内部术语） |
| `figures_manifest.json` | 生成的图表 |
| `experiments/` | 各节点的源代码和输出 |

---

## 第 7 步：配置设置

打开 **Settings** 页面自定义 ARI：

![设置页面](images/zh/dashboard_settings.png)

### 仪表盘语言

通过顶部的语言下拉菜单切换仪表盘语言（英文、日文、中文）。

### LLM 后端

- 选择你的提供商（OpenAI、Anthropic、Ollama、Custom）
- 设置默认模型和温度参数
- 输入你的 API 密钥（本地存储，在界面中以掩码显示）

### 论文搜索

- 可选择设置 Semantic Scholar API 密钥以获取更高的请求限额

### SLURM / HPC

- 设置默认分区、CPU 数量和集群任务的内存
- 点击 **Detect** 自动检测集群的可用分区

### 按阶段模型覆盖

为不同的管线阶段使用不同的模型（例如，用较便宜的模型进行创意生成，用更好的模型撰写论文）。

---

## 其他仪表盘页面

### Ideas 页面

![Ideas 页面](images/zh/dashboard_ideas.png)

查看 VirSci 生成的研究假说，包含新颖性和可行性评分。可查看实验配置、研究目标和 BFTS 节点评估。

### Workflow 编辑器

![Workflow 页面](images/zh/dashboard_workflow.png)

编辑 BFTS 后管线阶段（数据转换 → 生成图表 → 撰写论文 → 评审 → 可重现性检查）。更改将保存为 `workflow.yaml`。

---

## 仪表盘架构与 API

仪表盘是一个由 Python asyncio HTTP 服务器提供服务的 React/TypeScript SPA（使用 Vite 构建）。它由两个组件组成：

- **HTTP 服务器** (`ari/viz/server.py`): REST API + SSE 日志流（在主端口上）
- **WebSocket 服务器**: 实时树更新（端口+1，例如仪表盘在 8765 时为 8766）

### API 端点

所有端点可通过 `http://localhost:<port>/` 访问。

#### State & Monitoring

| 端点 | 方法 | 描述 |
|------|------|------|
| `/state` | GET | 完整的应用状态：当前阶段（idle/idea/bfts/paper/review）、节点数、实验配置、成本数据、LLM 模型信息 |
| `/api/logs` | GET (SSE) | 来自 `ari.log` 和 `cost_trace.jsonl` 的实时日志 Server-Sent Events 流 |
| `/memory/<node_id>` | GET | 节点的内存存储条目（工具调用追踪、指标、父链） |
| `/codefile?path=<path>` | GET | 读取检查点目录中的文件（限制在检查点范围内，最大 2MB） |

#### Experiment Management

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/launch` | POST | 启动新实验。请求体：`{experiment_md, profile, model, provider, max_nodes, max_depth, max_react, timeout_min, workers, partition, ...}`。返回：`{ok, pid, checkpoint_path}` |
| `/api/run-stage` | POST | 运行指定阶段：`{stage: "resume"/"paper"/"review"}` |
| `/api/stop` | POST | 优雅地停止运行中的实验（SIGTERM → SIGKILL 回退） |
| `/api/checkpoints` | GET | 列出所有检查点目录及其状态、节点数、评审分数 |
| `/api/checkpoint/<id>/summary` | GET | 详细摘要：树数据、评审、科学数据、论文文本 |
| `/api/checkpoint/<id>/paper.pdf` | GET | 下载生成的 PDF |
| `/api/checkpoint/<id>/paper.tex` | GET | 下载生成的 LaTeX |
| `/api/active-checkpoint` | GET | 当前活跃的检查点路径 |
| `/api/switch-checkpoint` | POST | 切换活跃检查点：`{path}` |
| `/api/delete-checkpoint` | POST | 删除检查点及关联日志：`{path}` |
| `/api/upload` | POST | 上传文件到活跃检查点（二进制请求体，`X-Filename` 头） |

#### Configuration

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/settings` | GET | 当前设置：LLM 提供商/模型、Ollama 主机、SLURM 配置、MCP 技能 |
| `/api/settings` | POST | 将设置保存到 `~/.ari/settings.json` 和 `.env`。请求体：`{llm_model, llm_provider, ollama_host, slurm_partition, ...}` |
| `/api/env-keys` | GET | 来自 `.env` 文件的所有 API 密钥及来源信息 |
| `/api/env-keys` | POST | 保存单个 API 密钥：`{key, value}` |
| `/api/profiles` | GET | 可用的环境配置文件（laptop, hpc, cloud） |
| `/api/models` | GET | 可用的 LLM 提供商和模型 |
| `/api/workflow` | GET | 包含管线阶段和技能元数据的完整 workflow.yaml |
| `/api/workflow` | POST | 保存修改后的 workflow.yaml：`{path, pipeline}` |
| `/api/skills` | GET | 列出可用的 MCP 技能及其描述 |
| `/api/skill/<name>` | GET | 技能详情：README、SKILL.md、server.py 源码 |

#### Wizard & Tools

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/chat-goal` | POST | 用于实验目标细化的多轮 LLM 对话：`{messages, context_md}` |
| `/api/config/generate` | POST | 从自然语言目标生成 experiment.md：`{goal}` |
| `/api/ssh/test` | POST | 测试 SSH 连接：`{ssh_host, ssh_port, ssh_user, ssh_key, ssh_path}` |
| `/api/scheduler/detect` | GET | 自动检测计算环境（SLURM, PBS, LSF, Kubernetes） |
| `/api/slurm/partitions` | GET | 可用的 SLURM 分区 |
| `/api/ollama-resources` | GET | GPU 信息（nvidia-smi）、可用的 Ollama 模型 |
| `/api/gpu-monitor` | GET/POST | 启动/停止 GPU 监控守护进程 |

#### WebSocket

| 端点 | 描述 |
|------|------|
| `ws://localhost:<port+1>/ws` | 订阅实时树更新。消息格式：`{type: "update", data: tree.json, timestamp}` |

### 安全性

- API 密钥仅存储在 `.env` 文件中，不会存储在 `settings.json` 中
- 文件访问（`/codefile`）限制在检查点目录范围内
- 每个实验在独立的进程组中运行以实现隔离

---

## CLI 替代方案

仪表盘的所有操作也可以通过命令行完成：

### 运行实验

```bash
# 基本运行（自动检测配置）
ari run experiment.md

# 使用环境配置文件
ari run experiment.md --profile hpc

# 使用自定义配置
ari run experiment.md --config ari-core/config/workflow.yaml

# 恢复中断的运行
ari resume ./checkpoints/20260328_matrix_opt/

# 仅运行论文管线（实验已完成）
ari paper ./checkpoints/20260328_matrix_opt/
```

### 监控与结果

```bash
# 显示节点树和状态
ari status ./checkpoints/20260328_matrix_opt/

# 列出所有项目
ari projects

# 显示详细结果（树 + 评审）
ari show 20260328_matrix_opt

# 列出可用工具
ari skills-list
```

### 配置

```bash
# 查看当前设置
ari settings

# 更改模型
ari settings --model openai/gpt-4o

# 设置 SLURM 选项
ari settings --partition gpu --cpus 64 --mem 128
```

### 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_BACKEND` | LLM 后端：`ollama` / `openai` / `anthropic` | `ollama` |
| `ARI_MODEL` | 模型名称（例如 `qwen3:8b`、`openai/gpt-4o`） | `qwen3:8b` |
| `OPENAI_API_KEY` | OpenAI API 密钥 | -- |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | -- |
| `OLLAMA_HOST` | Ollama 服务器 URL | `http://localhost:11434` |
| `ARI_MAX_NODES` | 最大实验总数 | `50` |
| `ARI_PARALLEL` | 并行实验数 | `4` |
| `ARI_MAX_REACT` | 每个节点的最大 ReAct 步数 | `80` |
| `ARI_TIMEOUT_NODE` | 每个节点的超时时间（秒） | `7200` |

---

## 故障排除

### 安装问题

| 问题 | 解决方案 |
|------|----------|
| `ari: command not found` | 将 `~/.local/bin` 添加到你的 PATH：`export PATH="$HOME/.local/bin:$PATH"` |
| 安装脚本失败 | 检查 Python 版本：`python3 --version`（必须为 3.10+） |
| 权限被拒绝 | 不要使用 `sudo`，以普通用户运行即可。 |

### AI 模型问题

| 问题 | 解决方案 |
|------|----------|
| Ollama 连接被拒绝 | 确保 `ollama serve` 在另一个终端中正在运行 |
| `LLM Provider NOT provided` | 使用提供商前缀：`openai/gpt-4o`，而非仅 `gpt-4o` |
| 速度慢或超时 | 使用较小的模型（`qwen3:8b`）或在 Settings 中增加超时时间 |

### 实验问题

| 问题 | 解决方案 |
|------|----------|
| 所有节点都失败了 | 打开 Tree 视图，点击失败的节点，查看 Trace 标签页 |
| 没有结果 | 检查 Monitor 页面 — 实验可能仍在运行中 |
| 运行被中断 | 前往 Experiments 页面，找到该运行，点击 Resume |

### 论文生成问题

| 问题 | 解决方案 |
|------|----------|
| 未生成 PDF | 安装 LaTeX：`conda install -c conda-forge texlive-core` |
| `No paper text available` | 安装：`pip install pymupdf pdfminer.six` |

---

## 快速上手秘诀

```bash
# 1. 安装
git clone https://github.com/kotama7/ARI.git && cd ARI && bash setup.sh

# 2. 设置 AI（免费，本地运行）
ollama pull qwen3:8b && ollama serve &
export ARI_BACKEND=ollama ARI_MODEL=qwen3:8b

# 3. 启动仪表盘
ari viz ./checkpoints/ --port 8765
# 打开 http://localhost:8765 并使用向导创建你的实验！
```

---

## 下一步

- **CLI 用法：** 参阅 [CLI 参考](cli_reference.md) 了解命令行操作
- **实验文件：** 参阅 [编写实验文件](experiment_file.md) 了解高级语法
- **HPC 集群：** 参阅 [HPC 设置指南](hpc_setup.md) 了解 SLURM 配置
- **扩展 ARI：** 参阅 [扩展指南](extension_guide.md) 了解如何添加新技能
