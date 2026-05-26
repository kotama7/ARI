---
sources:
  - path: start.sh
    role: doc
  - path: setup.sh
    role: doc
  - path: ari-core/ari/cli
    role: implementation
last_verified: 2026-05-26
---

# ARI 入门

ARI 是一个端到端的自主研究系统：给它一个纯文本的研究目标，它就会调研既有工作、形成假说、运行真实实验、撰写论文，并验证自身的可复现性。本页是你头一个小时的地图。

## 学习路径

请按顺序进行 —— 每一步都假定你已完成前一步。

1. **[快速入门](quickstart.md)** —— 安装 ARI、选择一个 AI 模型，并从 Web 仪表盘启动你的第一个实验。以操作为中心：哪个按钮做什么。
2. **[你的第一个实验，端到端](first_experiment_tutorial.md)** —— 对一个小型实验从目标到复现论文的叙述式走查，解释*为什么*每个阶段都存在。在仪表盘可用后阅读此文。
3. **[FAQ](faq.md)** —— 新手最先遇到的问题：模型选择、`8765` 端口、输出去向、GPU/SLURM 检测、"为什么我的子节点显示相同的数字？"。
4. **[术语表](../reference/glossary.md)** —— 反复出现的术语（BFTS、frontier、rubric、venue、EAR、ORS、CoW……）的一行定义，使概念文档读起来更顺畅。

## 然后按你的需要分支

| 如果你想…… | 前往 |
|---|---|
| 编写一份好的 `experiment.md` | [编写实验文件](../guides/experiment_file.md) |
| 在 SLURM/HPC 集群上运行 | [HPC 设置](../guides/hpc_setup.md) |
| 理解搜索如何工作 | [BFTS 算法](../concepts/bfts.md) · [架构](../concepts/architecture.md) |
| 复现或审计一篇已发表的论文 | [PaperBench 快速入门](../guides/paperbench/paperbench_quickstart.md) |
| 添加你自己的能力（技能） | [扩展指南](../guides/extension_guide.md) |
| 完全从 CLI 驱动一切 | [CLI 参考](../reference/cli_reference.md) |
| 修复出问题的东西 | [故障排除](../guides/troubleshooting.md) |

## 两件值得先了解的事

- **仪表盘运行在 `8765` 端口上。** 在仓库根目录用 `./start.sh` 启动每个服务并打开 <http://localhost:8765>；用 `./shutdown.sh` 停止。
- **每次运行都是自包含的。** 一次运行的所有状态都存于
  `workspace/checkpoints/<timestamp>_<slug>/` 之下 —— 不会向你的主目录写入任何东西，API 密钥来自 `.env`，绝不来自已保存的设置。

---

另请参阅：[快速入门](quickstart.md) · [FAQ](faq.md) ·
[术语表](../reference/glossary.md) · [文档索引](../../README.md)
