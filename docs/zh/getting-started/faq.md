---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/config/default.yaml
    role: config
last_verified: 2026-06-10
---

# FAQ

新手最先遇到的问题。关于从损坏的运行中逐步恢复，参见
[故障排除](../guides/troubleshooting.md)；关于术语定义，参见
[术语表](../reference/glossary.md)。

## 设置与模型

**我应该从哪个 AI 模型开始？**
若要进行无账户、无成本的首次运行，请使用 Ollama 配 `qwen3:8b`（需要
约 16 GB 内存）。若要更高质量，请使用云端模型，如 `openai/gpt-4o` 或
`anthropic/claude-sonnet-4-5`。务必包含提供商前缀 ——
`openai/gpt-4o`，而非 `gpt-4o`。参见 [快速入门 → 选择你的 AI 模型](quickstart.md#step-2-choose-your-ai-model)。

**安装后出现 `ari: command not found`。**
将用户 bin 目录添加到你的 PATH：`export PATH="$HOME/.local/bin:$PATH"`。
不要用 `sudo` 运行 `setup.sh` —— 以你的普通用户身份运行它。

**Ollama "connection refused"。**
在你启动 ARI 之前，必须在另一个终端中运行 `ollama serve`。

## 仪表盘

**仪表盘在哪个端口上？**
`8765`。在仓库根目录用 `./start.sh`（Letta + registry + GUI）启动一切并打开 <http://localhost:8765>。`./start.sh status` 进行健康检查；用
`./shutdown.sh` 停止。用于实时树更新的 WebSocket 在 `8766`
（端口 + 1）上。

**页面无法加载 / 某个服务没有起来。**
重新运行 `./start.sh`（每次调用它都会重启全部三个服务）并检查
`./start.sh status`。`shutdown.sh` 还会回收上一次 Letta 运行中由 apptainer 留下的
postgres/redis 孤儿进程。

## 运行实验

**输出去往哪里？**
进入一个自包含的检查点目录，
`workspace/checkpoints/<timestamp>_<slug>/`（时间戳形式为
`YYYYMMDDHHMMSS_<slug>`）。论文、图表、树、EAR 和可复现性报告都存于那里。不会向你的主目录写入任何东西。

**我的首次运行应该多大？**
小一点：深度 3、5–10 个节点、2–4 个并行 worker。你随时可以扩大规模。更大的搜索会消耗更多 LLM 调用和算力。

**我的子节点都报告与父节点相同的数字 —— 这是 bug 吗？**
不是，这是一项防护措施在尽职。子节点的 `work_dir` 通过复制父节点的目录来初始化，但实验*输出*（`results.csv`、`slurm-*.out`、
`metrics.json`、`*.log`……）在黑名单中，**不会**被继承。如果子节点在没有产生任何新增/变更文件的情况下结束，ARI 会将其标记为
**sterile（不育）**（分数 `0.0`）并剪枝，而非把继承来的结果记到它名下。如果你经常看到这种情况，说明代理并没有真正重新运行实验 ——
请查看该节点的 Trace 标签页。参见
[架构 → work_dir 继承](../concepts/architecture.md#work_dir-inheritance--output-artifact-blacklist-v070--phase-7)
以及 [术语表 → sterile](../reference/glossary.md)。

**实验失败了 —— ARI 会重试吗？**
不会。BFTS 从不重新执行失败的节点；它会扩展一个 `debug` 子节点来诊断并修复失败。打开失败节点的 Trace 标签页查看发生了什么。

## GPU、SLURM 与容器

**我如何在集群上运行？**
在 Settings 中设置 SLURM 分区（或在 CLI 上用 `--partition`），并使用
`hpc` profile。在 Settings 中点击 **Detect** 自动检测分区，或用
`/api/scheduler/detect` 自动检测调度器（SLURM/PBS/LSF/Kubernetes）。
参见 [HPC 设置](../guides/hpc_setup.md)。

**GPU 没有被使用。**
检查 `nvidia-smi` 是否可用、你的 SLURM 请求是否申请了 GPU，以及你的容器运行时是否被检测到（Settings → **Detect Runtime**）。对于 PaperBench
复现，缺失 GPU/沙箱现在会高调失败，而非静默回退到 CPU —— 参见 [PaperBench GUI → 高调失败的前置条件](../guides/paperbench/paperbench_gui.md)。

## 密钥、论文与可复现性

**我的 API 密钥存储在哪里？**
仅存储在 `.env` 文件中 —— 绝不在 `settings.json` 中。搜索顺序为
checkpoint → ARI 根目录 → `ari-core` → 主目录，或在启动时注入的环境变量。

**没有生成 PDF。**
安装 LaTeX（`conda install -c conda-forge texlive-core`）和 PDF 文本工具（`pip install pymupdf pdfminer.six`）。

**我能把一个已完成的运行迁移到另一台机器吗？**
可以。每个检查点都携带一个 `memory_backup.jsonl.gz`，因此
`cp -r workspace/checkpoints/<run> /elsewhere/` 后跟 `ari resume`
会自动将内存恢复到一个空的 Letta 中。

---

另请参阅：[故障排除](../guides/troubleshooting.md) ·
[快速入门](quickstart.md) · [术语表](../reference/glossary.md)
