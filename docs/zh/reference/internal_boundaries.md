---
sources:
  - path: ari-core/ari/llm/routing.py
    role: implementation
  - path: ari-core/ari/cost_tracker.py
    role: implementation
  - path: ari-core/ari/llm/client.py
    role: implementation
  - path: ari-core/ari/container.py
    role: implementation
  - path: ari-core/ari/mcp/client.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/ari/pipeline/orchestrator.py
    role: implementation
  - path: ari-core/ari/viz/state.py
    role: implementation
last_verified: 2026-06-10
---

# 内部边界

ARI 如何与三件它无法用纯 Python 完成的事情对话：**LLM 提供方**、**操作系统 / 调度器 / 容器**，以及**两个编排引擎**。这是面向贡献者的参考：边界位于何处、获许可的调用形态是什么，以及此处的任何改动都必须保持的并发隐患。（关于跨包的稳定接口，参见 [public_api.md](public_api.md)；关于配置优先级，参见 [configuration.md](configuration.md)；关于磁盘布局，参见 [glossary.md](glossary.md) 和 [架构](../concepts/architecture.md)。）

## LLM 边界

ARI 的 LLM 边界**并非**"一切都必须调用 `LLMClient`"。它是一个三部分的模式，而直接调用 `litellm.{completion,acompletion}` 才是**获许可的**形态：

1. **`litellm`** 是提供方抽象层 —— 模块直接以模型 id 调用 `litellm.completion` / `acompletion`。
2. **`ari.llm.routing.resolve_litellm_model(model, backend)`** 是唯一的模型规范化辅助函数。它应用提供方前缀（包括 CLI 垫片的 `openai/claude-cli` 规则），使一个裸模型名能正确路由。
3. **`ari.cost_tracker._install_litellm_metadata_injector()`** 在**整个进程范围**对 `litellm.completion`/`acompletion` 进行猴子补丁，以 (a) 合并默认成本元数据（skill / phase / node），并 (b) 在每次调用上应用 `_apply_ari_routing`（`resolve_litellm_model` ＋ CLI 垫片的 `api_base` 补全）。一旦安装完成，*每一次* litellm 直接调用 —— 无论来自哪个模块或技能 —— 都会在同一个点上透明地获得 ARI 路由 ＋ 成本捕获。

`ari.llm.client.LLMClient` 是 ReAct 智能体循环所用的、对 `litellm.completion` 的**便捷封装**；它**不是**强制性的瓶颈点，代码库刻意没有将一切都汇集到它这里。

注入器通过 `cost_tracker.set_default_metadata` / `init_from_env` 安装，这两者经由每个技能 `server.py` 顶部的 `bootstrap_skill("<name>")` 到达。

**需要保持的脆弱性：** CLI 垫片路由和成本捕获依赖于注入器在一个进程中的**第一次 litellm 调用之前**被安装。技能通过 `bootstrap_skill` 在导入时保证这一点。核心 CLI / 流水线模块（`evaluator`、`orchestrator/lineage_decision`、`root_idea_selector`、`pipeline/context_builder`）直接调用 litellm 并自行传入 `api_base`/model，因此即便没有全局注入器它们也能正确路由 —— 但若注入器缺失，它们会漏掉成本捕获。`pipeline/context_builder` 是唯一一个进行自己的环境变量解析而非使用 `resolve_litellm_model` 的流水线包直接调用（一个已知的低价值接缝）。

## 执行边界（操作系统 / 调度器 / 容器）

获许可的执行模块 —— 对执行行为的改动应归于此处：

| 模块 | 负责 |
|--------|------|
| `ari/container.py` | 容器执行：`detect_runtime`、`build_run_cmd`、`run_in_container`（Popen ＋ `_sandbox_preexec` ＝ `os.setsid` 新建进程组 ＋ 经由 `ARI_MAX_CHILD_PROCS` 的可选 `RLIMIT_NPROC`）、`_run_with_timeout`（对进程组 SIGTERM→SIGKILL）、`pull_image`、`exec_in_container`。由 `ari.public.container` 重导出。 |
| `ari/env_detect.py` | 调度器 / 运行时探测（`sinfo`、`qstat`、`docker info`、`lscpu`）—— 只读、尽力而为、不含硬编码的集群知识。 |
| `ari/mcp/client.py` | 经由 MCP SDK 的 `stdio_client`（一个封装，而非裸 spawn）派生技能的 stdio 服务器。 |
| `ari-skill-hpc/src/slurm.py` | 规范的 SLURM submit/status/cancel（`SlurmClient`：`_run_local` 为 asyncio 子进程，`_run_remote` 为 paramiko），含 `ARI_SBATCH_EXPORT_MODE` 的净环境逻辑。 |

应向这些归属者整合的已知重复（并非错误行为，但有漂移风险）：`viz/api_memory.py` 重新推导了容器运行时分派；`ari-skill-paper-re/src/server.py` 重新实现了 `sbatch`/`apptainer exec`，且已经偏离了 `slurm.py`（它硬编码了 `--export ALL`）；其本地回退缺少 `setsid`/`killpg`，因此一次挂起的复现可能产生孤儿进程。

**`ari.viz.state` 的进程句柄耦合。** `ari/viz/state.py` 将活动的操作系统句柄作为模块全局变量（以 `_st` 导入）持有：`_last_proc`（最近一次实验的 Popen；由 `api_process._api_stop` 通过 `os.killpg(os.getpgid(pid))` 拆除）、`_running_procs`（checkpoint-path→Popen 映射，由两条启动路径写入），以及 `_gpu_monitor_proc`（其逻辑位于 `api_process.py`；服务器会跨重启回收一个陈旧的监视器）。这是"避免通过全局可变状态产生隐藏耦合"这一告诫的典范例子 —— 只在有意为之时才触碰它的生命周期。

## 两个编排引擎

运行时是**两个不同的引擎**，而非一条线性流水线 —— `workflow.yaml` 声明了阶段标签（`bfts`、`paper`），但拆分横跨于：

| 阶段 | 驱动 |
|-------|--------|
| **BFTS** | `cli/bfts_loop.py:_run_loop` —— 一个硬编码的 `while pending or frontier` 循环（generate_idea → select_and_run → evaluate → frontier_expand）。`bfts_pipeline[]` 仅为启用/禁用标志而被读取。 |
| **post-BFTS 流水线**（transform / figures / paper / review / ORS 复现 / publish） | `core.generate_paper_section` → `pipeline.orchestrator.run_pipeline` —— 一个在 `pipeline[]` 上运行的单一线性游标循环；所有子阶段都是连续的阶段。 |

`run.py` 清除 `.pipeline_started`；`orchestrator` 在流水线启动时触碰它（GUI 阶段检测）。一个 BFTS 健全性门控可以提前中止 post-BFTS 流水线（`ARI_FORCE_PAPER` 会覆盖之）。非 `react:` 阶段经由 `stage_runner._run_stage_subprocess` 运行，它构建一个 Python 脚本字符串并执行 `subprocess.run([sys.executable, "-c", ...])` —— 每个非 react 阶段都是一次直接 fork，在子进程中构建它自己的 `MCPClient`。

### 并发隐患（此处的任何改动都需保持）

1. **fork 时刻的环境变量时序。** MCP 服务器在 spawn 时对 `os.environ` 拍快照。`ARI_WORK_DIR` 和沙箱变量（`ARI_REAL_GIT`、`ARI_REPRO_*`、`PATH`）必须在 `MCPClient` spawn **之前**设置；推迟 MCP 构建或重排环境设置顺序会悄无声息地破坏沙箱化 / work-dir 钉定。
2. **并行工作者下共享进程的全局环境竞态。** 至多 4 个 `AgentLoop` 线程共享同一个进程和同一个 `MCPClient`。内存的写时复制以进程全局的 `ARI_CURRENT_NODE_ID` 为键；唯一安全的写入路径是 `mcp.call_tool(name, args, cow_node_id=node_id)`（它在 `MCPClient._cow_lock` 下将 set-node＋write 这对操作串行化）。每次运行单一的 `_set_current_node` 在 `max_parallel_nodes > 1` 时是不安全的。
3. **对共享检查点树的写入。** **不存在 git worktree**：并发的提交者都经由同一个共享的 `agent._progress_cb` → `_save_tree_incremental` 写入同一份 `tree.json` / `nodes_tree.json` / `results.json`；线程安全 ＋ 限流位于 `ari.checkpoint.save_tree_incremental`（锁 ＋ mtime 限流）。每个节点的 work-dir 由 `PathManager.node_work_dir(run_id, node_id)` 隔离。
