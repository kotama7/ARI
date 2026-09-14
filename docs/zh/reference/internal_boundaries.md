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
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_wizard.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/rqgm/runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/context_views.py
    role: implementation
  - path: ari-core/ari/rqgm/governance/__init__.py
    role: implementation
  - path: ari-core/ari/manuscript/snapshot.py
    role: implementation
  - path: ari-core/ari/manuscript/coordinator.py
    role: implementation
  - path: ari-skill-paper-re/src/_compute/computer.py
    role: implementation
  - path: scripts/snapshot_contracts.py
    role: implementation
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
  - path: ari-core/tests/test_manuscript_assurance_boundary.py
    role: test
  - path: ari-core/tests/test_rqgm_mode.py
    role: test
  - path: ari-core/tests/test_rqgm_governance.py
    role: test
  - path: ari-core/tests/test_contract_snapshots.py
    role: test
last_verified: 2026-08-17
---

# 内部边界

ARI 如何与三件它无法用纯 Python 完成的事情对话：**LLM 提供方**、**操作系统 / 调度器 / 容器**，以及**两个编排引擎**。这是面向贡献者的参考：边界位于何处、获许可的调用形态是什么，以及此处的任何改动都必须保持的并发隐患。（关于跨包的稳定接口，参见 [public_api.md](public_api.md)；关于配置优先级，参见 [configuration.md](configuration.md)；关于磁盘布局，参见 [glossary.md](glossary.md) 和 [架构](../concepts/architecture.md)。）

## LLM 边界

ARI 的 LLM 边界**并非**"一切都必须调用 `LLMClient`"。它是一个三部分的模式，而直接调用 `litellm.{completion,acompletion}` 才是**获许可的**形态：

1. **`litellm`** 是提供方抽象层 —— 模块直接以模型 id 调用 `litellm.completion` / `acompletion`。
2. **`ari.llm.routing.resolve_litellm_model(model, backend)`** 是唯一的模型规范化辅助函数。它应用提供方前缀（包括 CLI 垫片的 `openai/claude-cli` 规则），使一个裸模型名能正确路由。它的签名与返回值是**冻结的**：它*变换*一个模型 id 而不是构造对象，因此被有意保留在 `ari._factory.BaseRegistry` 字符串分发器统一化之外（见 `routing.py` 中其定义上方的决策注记）。
3. **`ari.cost_tracker._install_litellm_metadata_injector()`** 在**整个进程范围**对 `litellm.completion`/`acompletion` 进行猴子补丁，以 (a) 合并默认成本元数据（来自 `bootstrap_skill` 的 skill / phase，以及 `ari_rqgm` 打开纪元后的 `epoch`；`node_id` 不是进程级默认值 —— 它乘的是调用方自己的 `metadata=`，例如 `LLMClient.set_context`），并 (b) 在每次调用上应用 `_apply_ari_routing`（`resolve_litellm_model` ＋ CLI 垫片的 `api_base` 补全）。一旦安装完成，*每一次* litellm 直接调用 —— 无论来自哪个模块或技能 —— 都会在同一个点上透明地获得 ARI 路由 ＋ 成本捕获。

`ari.llm.client.LLMClient` 是 ReAct 智能体循环所用的、对 `litellm.completion` 的**便捷封装**；它**不是**强制性的瓶颈点，代码库刻意没有将一切都汇集到它这里。

注入器通过 `cost_tracker.set_default_metadata` / `init_from_env` 安装，这两者经由每个**会调用 LLM 的**技能 `server.py` 顶部的 `bootstrap_skill("<name>")` 到达 —— 从不导入 `litellm` 的技能（benchmark、coding、harness、hpc、knowledge、memory、orchestrator、tool-registry）并不安装它。

**需要保持的脆弱性：** CLI 垫片路由和成本*归属*依赖于注入器在一个进程中的**第一次 litellm 调用之前**被安装（记录本身乘的是 `cost_tracker.init` 与注入器一并注册的 success/failure 回调，因此单靠 `set_default_metadata` 只能得到路由而没有捕获）。会调用 LLM 的技能通过 `bootstrap_skill` 在导入时同时保证这两者。核心 CLI / 流水线模块（`evaluator`、`orchestrator/lineage_decision`、`root_idea_selector`、`pipeline/context_builder`）直接调用 litellm 并自行传入 `api_base`/model，因此即便没有全局注入器它们也能正确路由 —— 但若注入器缺失，它们会漏掉成本捕获。`pipeline/context_builder` 是唯一一个进行自己的环境变量解析而非使用 `resolve_litellm_model` 的流水线包直接调用（一个已知的低价值接缝）。

## 执行边界（操作系统 / 调度器 / 容器）

获许可的执行模块 —— 对执行行为的改动应归于此处：

| 模块 | 负责 |
|--------|------|
| `ari/container.py` | 容器执行：`detect_runtime`、`run_in_container`（Popen ＋ `start_new_session=True` ＋ `ari.execution.build_minimal_environment`）、`container_shell_argv` / `run_shell_in_container`（带 `network="inherit"` 或 `"deny"` 开关）、`pull_image`。`_run_shell_sandboxed` 现在只是一个兼容适配器：它构造 `ExecutionRequestV1` 并调用 `ari.execution.execute_local`。不受支持的模式会抛出 `ValueError`，而不是回退到宿主机。由 `ari.public.container` 重导出。 |
| `ari/execution.py` | 容器执行所委托的进程原语：`execute_local`（`_preexec` 中的 `os.setsid` 以及 `RLIMIT_CPU`/`RLIMIT_AS`/`RLIMIT_NPROC`/`RLIMIT_FSIZE`，超时时对进程组 SIGTERM→SIGKILL）与 `build_minimal_environment`（显式环境，绝不复制父环境）。`ARI_MAX_CHILD_PROCS` 以 `ExecutionLimitsV1.max_processes` 的形式抵达此处。 |
| `ari/env_detect.py` | 调度器 / 运行时探测：`detect_scheduler`（`sinfo`/`qstat`/`bhosts`/`qhost`/`kubectl`）、`detect_container`（对 apptainer/singularity/docker 的 `shutil.which`）、`get_slurm_partitions`（`sinfo --noheader`）—— 只读、尽力而为、不含硬编码的集群知识。 |
| `ari/mcp/connection.py` | `SkillConnection` —— 经由 MCP SDK 的 `stdio_client`（一个封装，而非裸 spawn）派生一个技能的 stdio 服务器。`ari/mcp/client.py:MCPClient` 负责这些连接之上的池化、发现与分派。 |
| `ari-skill-hpc/ari_skill_hpc/scheduler.py` | 规范的 SLURM submit/status/cancel（`SlurmScheduler`，由 `LocalCommandRunner` ＝ `asyncio.create_subprocess_exec` 或 `RemoteCommandRunner` ＝ paramiko 驱动）；提交一律为 `sbatch --parsable --export=NIL`。`ari_skill_hpc/slurm.py` 仍以 `SlurmClient` 的形式持有一个按环境配置的调度器。 |

应向这些归属者整合的已知重复（并非错误行为，但有漂移风险）：`viz/api_memory.py` 重新推导了容器运行时分派。`ari-skill-paper-re` 的 **reproduce 路径**已整合了三种 substrate 中的两种 —— 它经由 `ari_skill_hpc.SlurmScheduler`（`src/server.py`）提交，并经由 `ari.execution.execute_local`（`src/sandbox.py`）运行本地尝试。唯有容器尝试仍是它自己的一份：`sandbox.py:_external_command` 自行拼装 `docker run` / `apptainer exec` 的 argv，`execute_container_attempt` 以 `asyncio.create_subprocess_exec(..., start_new_session=True)` 分派，而不走 `ari.container`。此外它的 **PaperBench agent computer**（`src/_compute/computer.py`）又是这两半各自的另一份实现：`ApptainerComputer.send_shell_command` 自行拼装 `apptainer exec` 的 argv，`LocalComputer.send_shell_command` 自行拼装裸的 `bash --noprofile --norc -c` argv，两者都走该模块自带的 `_run_subprocess`（`asyncio.create_subprocess_exec(..., start_new_session=True)` 加上 `killpg` 的 SIGTERM→SIGKILL 进程组拆除），而不是走 `ari.execution`；该模块从 core 引入的只有 `ari.public.execution.WorkspaceRefV1`。容器那一半已经相对 `container_shell_argv` 发生漂移：技能侧发出 `--cleanenv --containall --no-home`，配 `--bind {work_dir}:/work:rw --pwd /work` 且没有 `--writable-tmpfs`；core 侧发出 `--cleanenv --containall --writable-tmpfs`，配裸的 `--bind <workdir>`。这是生产代码而非死接缝（`src/server.py` → `_replicator_agent.run_replicator_agent` → `_compute.make_computer`），因此在审计容器执行或本地执行的重复时，正是应当阅读的那个文件。

**`ari.viz.state` 的进程句柄耦合。** `ari/viz/state.py` 将活动的操作系统句柄作为模块全局变量（以 `_st` 导入）持有：`_last_proc`（最近一次实验的 Popen；由 `api_process._api_stop` 通过 `os.killpg(os.getpgid(pid))` 拆除）、`_running_procs`（checkpoint-path→Popen 映射，由三个处理器写入 —— `api_experiment.py` 的 `/api/launch` 与 `/api/run-stage`，以及 `viz/v1/launch.py` 中的 `/api/v1` 启动路径），以及 `_gpu_monitor_proc`（其逻辑位于 `api_process.py`；服务器会跨重启回收一个陈旧的监视器）。这是"避免通过全局可变状态产生隐藏耦合"这一告诫的典范例子 —— 只在有意为之时才触碰它的生命周期。

## 两个编排引擎

运行时是**两个不同的引擎**，而非一条线性流水线 —— `workflow.yaml` 声明了阶段标签（`bfts`、`paper`），但拆分横跨于：

| 阶段 | 驱动 |
|-------|--------|
| **BFTS** | `cli/bfts_loop.py:_run_loop` —— 一个硬编码的 `while pending or frontier` 循环（generate_idea → select_and_run → evaluate → frontier_expand）。`bfts_pipeline[]` 仅为启用/禁用标志而被读取。 |
| **post-BFTS 流水线**（transform / figures / paper / review / ORS 复现 / publish） | `core.generate_paper_section` → `pipeline.orchestrator.run_pipeline`（对 `pipeline/driver.py:WorkflowDriver.run` 的薄封装）—— 一个在 `pipeline[]` 上运行的单一线性游标循环；所有子阶段都是连续的阶段。 |

`run.py` 清除 `.pipeline_started`；`WorkflowDriver.run` 在流水线启动时触碰它（GUI 阶段检测）。一个 BFTS 健全性门控可以提前中止 post-BFTS 流水线（`ARI_FORCE_PAPER` 会覆盖之）。非 `react:` 阶段经由 `stage_runner._run_stage_subprocess` 运行，它构建一个 Python 脚本字符串并执行 `subprocess.run([sys.executable, "-c", ...])` —— 每个非 react 阶段都是一次直接 fork，在子进程中构建它自己的 `MCPClient`。

### 并发隐患（此处的任何改动都需保持）

1. **首次连接时刻的环境变量时序。** MCP 服务器已不再继承 `os.environ`。`mcp/child_environment.py:build_child_environment` 解析出一份 fail-closed 的允许清单 —— `SAFE_INHERITED_ENV_NAMES`（`PATH`、`LANG`、`LC_ALL`、`LC_CTYPE`、`TZ`、`TMPDIR` 以及 CA 证书包相关名称）加上该技能 `skill.yaml` 在 `required_env` / `optional_env` 中声明的名称 —— 而 `SkillConnection` 会把结果缓存在 `_server_parameters` 中，因此父环境只在首次连接时被读取一次。时序上的不变式因而未变：`ARI_WORK_DIR`（由 coding 与 hpc 技能声明为 `optional_env`）必须在该次首次连接**之前**设置，否则 work-dir 钉定会悄无声息地失效。复现沙箱变量（`ARI_REAL_GIT`、`ARI_REPRO_*`）没有任何技能清单声明它们，因此它们只抵达 react / stage-runner 的子进程路径，绝不会到达技能服务器。
2. **并行工作者下的共享进程状态。** 所有节点线程共享同一个 `AgentLoop` 实例和同一个 `MCPClient`；`_run_loop` 将并发上限设为 `max_workers = max(1, min(cfg.bfts.max_parallel_nodes, 4))`，该上限由 `threading.Semaphore` 而非线程池大小强制执行（池大小为 `max_workers + 8`，好让一个正在等待调度器作业的节点驻留并交还其许可）。节点身份绝不承载于进程全局状态：安全路径是显式的 `ToolCallContextV1` —— 由 `AgentLoop._node_tool_context` 为每个节点构造一次，经 `_execute_tool_calls` 传递，并由 `SkillConnection.authorize_args` 按连接签名后写入 `ari_context` 工具参数。`work_dir` 出于同样的理由被显式传递 —— 在 `max_parallel_nodes > 1` 时读取环境变量会发生竞态。
3. **对共享检查点树的写入。** **不存在 git worktree**：并发的提交者都经由同一个共享的 `agent._progress_cb` → `_save_tree_incremental` 写入同一份 `tree.json` / `nodes_tree.json` / `results.json`；线程安全 ＋ 限流位于 `ari.checkpoint.save_tree_incremental`（锁 ＋ 基于 `time.monotonic()` 的最小间隔限流，默认 1.0 秒，`force=True` 可绕过）。每个节点的 work-dir 由 `PathManager.node_work_dir(run_id, node_id)` 隔离。

## RQGM 模式边界（`ari.rqgm`）

可选启用的 `ari_rqgm` 模式（见
[执行模式](../guides/execution_modes.md)）增加了又一条内部边界：
**`ari.rqgm` 包必须对默认运行不可见**。

**被强制的规则。**默认的 `simple_bfts` 路径从不导入任何
`ari.rqgm` 模块。core 侧的每个导入点都是惰性的，并在导入发生之前
以*原始*配置标志做门控：

- `ari.core.build_runtime` —— 仅当 `ari.mode == "ari_rqgm"` 或
  `rqgm.enabled` 被设置时才导入 `ari.rqgm.mode` /
  `ari.rqgm.runtime`，且仅当 `resolve_effective_mode(cfg)` 为
  `ari_rqgm` 时才包装策略。在同一分支内部，
  `_install_capability_gate` 导入 `ari.rqgm.kernel` /
  `ari.rqgm.store` / `ari.rqgm.tool_policy`，并返回被
  `CapabilityGatedMCPClient` 包装的 `MCPClient`（fail-open：安装
  失败会记录警告并交回未被门控的客户端）。
- `ari/cli/run.py` —— 仅在该模式下导入 `ari.rqgm.state`，用于在
  启动时写入 `rqgm_state.json` 并复制 `constitution.yaml`（以及
  resume 时的 `reconcile_resume_mode`：持久化的模式优先；运行
  绝不能在中途被升级）。
- `ari/cli/bfts_loop.py` —— 仅当设置了可选启用的
  `proposal_router.record_only: true` 双写时才导入提案存储
  （默认 `false` 从不导入；在 `ari_rqgm` 中路由器原生记录，因此
  该导入在那里同样被跳过）。
- `ari/cli/paper_dispatch.py` —— 仅为 `rqgm_archive` 这一 paper
  模式导入 `ari.rqgm.paper_runtime` / `ari.rqgm.paper_judge`；
  resume 一侧的导入还额外以 `paper_archive_state.json` 是否存在
  做门控，因此线性检查点不会导入任何东西。模式字符串本身来自
  免导入的 `ari.config._effective_paper_mode_str`。
- `ari.config._effective_mode_str` 以**免导入**方式镜像激活表，
  因此配置处理本身永远不会加载 `ari.rqgm`。

**包装，绝不替换。**在 `ari_rqgm` 下，`build_runtime` 返回一个
`GovernedSearchStrategy`（`ari/rqgm/runtime.py`），它把全部七个
`SearchStrategy` 方法委托给未被触碰的真实
`ari.orchestrator.bfts.BFTS` 实例；控制器可通过
`getattr(bfts, "rqgm", None)` 发现，因此六元组返回形状得以保留。
`ari.protocols` 只在 docstring 中提及 RQGM 类名 —— 这些 Protocol
是结构性的（`runtime_checkable`），因此导入 `ari.protocols` 不会
从 `ari.rqgm` 拉入任何东西。

**`rqgm` 是一个被保留的属性名。**发现治理运行时的唯一受支持方式就是
`getattr(bfts, "rqgm", None)`，而这次读取是刻意采用鸭子类型的 ——
`GovernedSearchStrategy` 的 docstring 本身就规定："检测依据的是鸭子类型的
属性存在性，绝不是对这个具体类做 `isinstance`"。该包装器是内部的、未做版本
管理的，因此任何消费方都不得依据
`isinstance(bfts, GovernedSearchStrategy)` 分支；目前也没有任何地方这样做。
同一个 `getattr` 探测重复出现在 `cli/bfts_loop.py`、`cli/run.py`、
`cli/projects.py`、`cli/manuscript_repair_runtime.py` 以及 `core.py` 中，
因此这个名字在**任何**作为本次运行的 `SearchStrategy` 被传递的对象上都是
保留的：不要给某个策略对象附加无关的 `rqgm` 属性；若将来的组件需要更丰富的
发现方式，请添加一个带类型的访问器，而不是第二个魔法属性。

**强制手段。**
`ari-core/tests/test_rqgm_mode.py::test_build_runtime_default_is_identity`
构建一个默认运行时并断言：(a) `sys.modules` 中没有任何
`ari.rqgm*` 条目，(b) 策略就是普通的 `ari.orchestrator.bfts` 对象
且没有 `.rqgm` 属性，(c) 检查点中没有 `rqgm_state.json` /
`constitution.yaml`。在技能一侧，`ari.rqgm` 不通过 `ari.public.*`
再导出，且 `scripts/quality/check_import_boundaries.allow.yaml`
不含任何 `ari.rqgm` 例外 —— 任何技能都不得导入它。

**唯一的承诺是治理门面。**在包内再往下一层，纪元边界的审计遵循同一条
纪律。`ari.rqgm.governance` 恰好导出两个名字 —— `GovernanceOrchestrator`
与 `GovernanceReport` —— 并由
`ari-core/tests/test_rqgm_governance.py::test_facade_exports_only_the_two_public_names`
把 `__all__` 钉定为这一对。构成该审计的一切都位于同一个包内以下划线
开头的私有模块中：可靠性监视器（`_reliability.py`）、证据书记员及其
可采性检查器（`_evidence.py`）、审计官／起诉方及其保证金记账
（`_prosecution.py`）、辩护方（`_defense.py`）、各评分板与治理裁判
（`_adjudication.py`）、自审计（`_self_audit.py`），以及九步流水线本身
（`_pipeline.py`）和记录数据类（`_records.py`，其中只有
`GovernanceReport` 被提升到门面）。除此之外的一切都不被再导出、都不
加入 `ari.public.*`、都不获得 CLI 标志，也都不作为 MCP 工具暴露。树中
除测试外唯一的调用点是 `RQGMRuntime.run_epoch_audit`
（`ari/rqgm/runtime.py`），它惰性构造该编排器，并在每个纪元边界调用
一次 `audit_epoch`。

这种狭窄是刻意的。细粒度的角色名是一套概念词汇，而不是接口：把十几个
这样的名字公开出去，会把仍在变动的签名冻结进被冻结的契约快照接口
（`ari-core/tests/fixtures/contracts/public_api.json`），此后每一次重构
都会变成一次 golden 文件差分。把门面维持在一个类、一个公开方法、一个
返回类型，内部角色就能被自由重塑，而唯一的调用点以及转换引擎所消费的
`GovernanceReport` 则保持稳定。

**该模式不消耗任何契约接口。**启用只经由配置与环境变量：RQGM 不新增
任何 `ari` CLI 命令或标志，也不通过 `ari.public.*` 导出任何符号，因此
两份被冻结的快照都无需为它重新生成 ——
`ari-core/tests/fixtures/contracts/cli_tree.json` 与 `public_api.json`
（由 `scripts/snapshot_contracts.py` 构建并校验，由
`ari-core/tests/test_contract_snapshots.py` 把关）中根本没有任何 `rqgm`
条目。这是一个刻意的预算决定，而非疏忽：一个 `--mode` 标志会把执行模式
挪进被冻结的 CLI 树，使此后每一次与模式相关的改动都变成一次 golden 文件
差分。请把新的模式接口留在配置一侧 —— 上文的包装器之所以按属性而非按
类型来发现，出于的也是同一个理由。

### 治理上下文视图（`ari.rqgm.context_views`）

包内部还有一条规则，而它最容易被当成一种通用模式 —— 其实并不是：
**每个治理角色拿到的是一份封顶的、按角色定制的投影 —— 一个*视图* ——
而绝不是归档本身。** `ari/rqgm/context_views.py` 中的构造函数都是纯的
（无 LLM、无 I/O）且逐字节确定的，因此一个视图只是其输入的函数，不依赖
任何其它东西。

**BFTS 这一行是承重的**，并且它同时被写在三处。`CK-CTX-001` 这个码及其
严重度见
[RQGM schema → 宪法违规码](rqgm_schemas.md#宪法违规码)；视图自身的字段
清单见
[`proposal_summary_view.schema.json`](rqgm_schemas.md#proposal-summary-view-schema-json)。

| 层 | 机制 | 它拦得住什么吗？ |
|---|---|---|
| 构造期 | `build_bfts_summary_context` 只接受 `ProposalSummaryView`，对其它一切 —— `ProposalRecord`，乃至该 summary 自己的 `to_dict()` —— 都抛出 `TypeError` | 是；只有这一层会抛出。 |
| 检查期 | `ConstitutionalKernel.validate_context_scope(role, view)` 从视图的键集合中减去该角色的白名单，并对剩余部分报告 `CK-CTX-001` | 否 —— 只是 warn-and-flag，从不阻断节点执行。 |
| 测试期 | `ari-core/tests/test_rqgm_context_views.py::test_no_archive_field_reaches_the_rendered_expand_context` 渲染一个带有全部 `ARCHIVE_ONLY_FIELDS` 名称的 fixture `ProposalRecord`，并断言这些名称与哨兵串都不会残留在渲染结果里 | 只在 CI 中。 |

**白名单只有一份，并被钉进宪法。** `PROPOSAL_SUMMARY_FIELDS` 不是内核表的
副本 —— 它就是 `kernel_rules.CONTEXT_VIEW_WHITELISTS["generator"]`（BFTS
搭在 `generator` 角色上），而
`test_rqgm_context_views.py::test_whitelist_constant_is_the_kernel_table_entry`
钉定了 `is` 同一性，因此不会出现第二份可以漂移的列表。该表以
`context_view_whitelists` 之名被序列化进
`kernel_rules._canonical_rules_payload()`，从而搭上 `constitution_hash()`：
新增或放宽一行都是一次显式的重新钉定，与转换表所受的待遇相同。

**在依赖这套分层之前，请先读清顺序。** 在 `ari-core/ari` 内，唯一的非测试
调用点是 `RQGMRuntime.render_expand_context`（`ari/rqgm/runtime.py`），它
在调用方传入 `idea_context` 关键字参数时由 `GovernedSearchStrategy.expand`
到达。那里**先**跑检查期这一层（`_flag_bfts_view_scope` —— 一条日志警告
外加向 immutable audit log 追加的 `kernel_report` 行，整个钩子以 fail-open
包裹），**后**才是类型闸门。真正挡住泄漏的是类型闸门：越界的视图是一个
普通 `dict`，`build_bfts_summary_context` 抛出，`render_expand_context`
外层的 `try` 把它吞掉并返回 `""`，调用方于是保留自己的 `idea.json`
上下文。内核那一层只记录事实，并不阻止它。另外要注意，构造函数**内部**的
`_enforce_scope("generator", …)` 调用发生在类型闸门之后，作用于
`ProposalSummaryView.to_dict()`，而后者的键集合恰好就是白名单里的那十个
名字 —— 所以在 BFTS 这一行上，这次内部调用永远不可能产生违规。它是双保险，
而不是真正会触发的那道检查。

**根本上被内核检查的角色只有三个。** `CONTEXT_VIEW_WHITELISTS` 只有
`generator`、`paper_writer` 与 `paper_reviewer` 三行；`validate_context_scope`
按角色查表，查不到就返回一份干净的报告，因此其余角色按设计就是不受检查的
（`test_a_role_without_a_whitelist_is_unchecked` 钉定了这一点）。于是
Judge、adversary、reviewer 与 governance 的视图只能依赖两种更弱的机制，
而这份"弱"值得说准确：

- **构造性排除** —— 构造函数根本没有接收禁止材料的参数
  （`build_reviewer_context` 无从被塞入另一位 reviewer 的输出；
  `build_judge_context` 只拿到 attack、defense 与 bundle，也从不持有注册表
  句柄）。这是实打实的，但它是签名的性质，而非一次检查。
- **`_scrub` 的按键删除** —— `JUDGE_EXCLUDED_KEYS`（`frontier_scores`、
  `frontier_rank`、`scientific_score`、`_scientific_score`、`utility`、
  `utility_score`）与 `GOVERNANCE_EXCLUDED_KEYS`（`prompt_text`、
  `prompt_body`、`template`、`template_text`、`body`）会被**按键名**递归
  删除，且每个字符串都被截断到 `_FIELD_CAP`（4000）字符。按键名删除的强度
  恰好等于那份名字清单：同一个值若挂在清单未列出的键下，就会原封不动地
  留下来。

**这个模块的大部分没有生产调用点 —— 请把它读作"声明"，而不是"观测"。**
在 `ari-core/ari` 内，拥有非测试调用点的构造函数只有
`build_bfts_summary_context`。`build_reviewer_context`、
`build_adversary_context`、`build_judge_context`、
`build_governance_context` 与 `build_paper_writer_context` 都没有；执行它们
的只有 `test_rqgm_context_views.py`（以及仅就 `build_paper_writer_context`
而言的 `test_rqgm_paper_candidate.py`）。而 `CHARTER_BLOCK_CAP = 1200` 更是
一个消费者都没有 —— 它的测试只断言这个数值以及它 ≤
`ari.agent.loop._IDEA_FIELD_CAP`。该模块 = BFTS 这一行 + 一组已备好但未接线
的投影；不要把其余那些当作"一次运行实际做了什么"来引用。

**paper-reviewer 的视图是在别处组装的，那是一处变通，不是设计。**
`ari/rqgm/paper_judge.py:_paper_reviewer_string_view` 自行组装 paper-reviewer
视图 —— 在同样那四个白名单键下放四个封顶字符串 —— 原因是
`context_views._plain` 只保留映射以及带 `to_dict` 的对象，于是一个裸字符串
会被投影成 `{}`；模块注释记录了：把归档里的字符串输入送进
`build_paper_reviewer_context` 曾把草稿正文悄悄丢掉。它导入
`PAPER_REVIEWER_FIELDS` 以保持键集合诚实，但用一句裸 `assert` 来钉定，
而不是调用内核，因此在跑着的 paper-reviewer 路径上不会产生任何属于它自己的
`CK-CTX-001` 报告。

**若要新增一个受治角色**，请往 `CONTEXT_VIEW_WHITELISTS` 里加一行（并接受
`constitution_hash` 的重新钉定），并从构造函数里调用 `_enforce_scope`；
`test_rqgm_context_views.py::test_every_whitelisted_builder_runs_the_check`
会检查那三个带白名单的构造函数的源码里确实有这一次调用。没有白名单行的
角色，其构造函数无论擦洗多少东西，都仍然是不受检查的。

### 稿件编译器边界（`ari.manuscript`）

同一条单向纪律也管着稿件编译器；之所以单列一节，是因为箭头方向相反：
`ari.manuscript` 是 RQGM 所**依赖**的那一侧，反过来绝不成立。

**`ari.manuscript` 下没有任何模块导入 `ari.rqgm`。** 该包对其他 `ari` 包发出的
导入只有两处惰性的、函数内的导入 ——
`ari.assurance.models.HarnessAttestationV1`（`manuscript/snapshot.py`，用于
解析节点的 harness 证明）与 `ari.paper_contract.parse_paper_build`
（`manuscript/runtime.py`）—— 而这两者都不会抵达 `ari.rqgm`：
`ari/paper_contract.py` 根本不导入任何 `ari` 模块，`ari/assurance/**` 中也
没有任何 `rqgm` 的引用。在 `ari.manuscript` 内部，这个名字只以数据形式出现
—— `manuscript/contracts.py` 中的 `Literal["simple_bfts", "ari_rqgm"]` 与
`Literal["linear", "rqgm_archive"]` 两个契约字段，`snapshot.py` /
`coordinator.py` 中它们被归一化成的字符串，以及
`manuscript/authority.py:_AUTHORITY_FILES` 里 `rqgm/kca/admission-v1/` 下的
四条检查点相对路径。

**那么 RQGM 状态是怎样抵达编译器的。** 共三条通道，没有一条点名 RQGM 类型：

| 通道 | 形态 |
|------|------|
| 模式 | 普通的 `str` 关键字参数 —— `compile_manuscript(..., exploration_mode="simple_bfts", paper_mode="linear")` 转发给 `build_exploration_snapshot(..., exploration_mode=...)`，并在落到契约之前被归一化为两个字面量之一。两个签名里都没有 RQGM 提供者对象，也没有带类型的 RQGM 块；`manuscript/runtime.py:prepare_runtime_manuscript` 从 `ARI_MANUSCRIPT_EXPLORATION_MODE` / `ARI_MANUSCRIPT_PAPER_MODE` 填入两者。 |
| 节点状态 | 对调用方本就持有的节点对象做鸭子类型读取。`snapshot._get(value, name, default)` 对映射是 `value.get(...)`，否则是 `getattr(...)`，因此 `attestation_refs`、`verified_target_digest` 与 `metrics` 都按名字查找；不带这些字段的 `simple_bfts` 节点直接得到默认值。 |
| 证据 | 从检查点相对路径读取的文件，绝不以对象形式交接。`snapshot._attestation_artifacts` 对节点 `attestation_refs` 所指的相对路径取摘要，并按 `HarnessAttestationV1` 校验（status 为 `present` / `stale` / `missing` / `invalid` —— `stale` 指能够解析且 `node_id` 匹配、但 `target_digest` 与该节点的 `verified_target_digest` 不一致的证明：证据仍然可见，而该节点无法 certify 发表；它既不像 `invalid` 那样可丢弃，也不像 `present` 那样可发表，该行为由 `test_manuscript_assurance_boundary.py::test_stale_target_attestation_remains_visible_but_cannot_publish` 钉住）；`authority.capture_repair_authority` 只对固定的 `_AUTHORITY_FILES` 清单取摘要而不解析（status 为 `present` / `absent` / `unsafe_symlink`）。两者遇到路径缺失或含符号链接时，都是记录一个 status，而不是抛出异常。 |

**反向的边是被允许且实际使用的。** `ari.rqgm.paper_runtime` 导入
`ari.manuscript.digest.path_has_symlink_component` 来复查归档输入，而
`ari/cli/paper_dispatch.py` 就是同时驱动两侧的那一层 —— 它把
`ari.rqgm.paper_runtime` / `ari.rqgm.paper_judge` 与
`ari.manuscript.runtime` / `ari.manuscript.coordinator` 并排惰性导入。需要
同时用到两侧的胶水代码，样板是 `ari/cli/manuscript_repair_runtime.py`：它
直接导入 `ari.manuscript.*`，但只经由上文那个被保留的
`getattr(bfts, "rqgm", None)` 探测去触及治理运行时。也就是说，RQGM 可以
依赖稿件契约；稿件契约永远不得依赖 RQGM。正是这一点让同一个编译器无需第二
套实现就能服务两种探索模式与两种 paper 模式 —— 差别是以字段取值记录的
（`paper_mode`，以及 `coordinator.py` 由它导出的 `backend_version` 字符串），
而不是分叉成一条并行代码路径；这也是为什么编译器需要的某个 RQGM 概念必须
经由上述三条通道之一抵达，而不能以导入的方式抵达。

**没有任何东西强制这个方向。** 既没有测试，也没有质量门规则：
`scripts/quality/check_import_boundaries.yaml` 约束 skill→core 与
core→skill 两类边，其唯一一个 core 内部的开关
（`forbid_core_to_viz_from_cli`，默认关闭）也只覆盖
`ari/cli/**` → `ari.viz.*`。与之相邻的、*确实*被强制
的是另一条规则 ——
`ari-core/tests/test_manuscript_complete.py::test_default_cli_import_does_not_load_manuscript_domain`
断言导入 `ari.cli` 不会加载任何 `ari.manuscript*` 模块；它让编译器留在默认
导入路径之外，但对编译器可以导入什么只字未提。在有人补上检查之前，请把
"不导入 `ari.rqgm`" 当作一条评审义务来对待。

## GUI 的 HTTP 分发边界

viz 服务器分发一个 HTTP 请求的地方恰好只有两处（关于它们周围的分层，参见
[仪表盘架构](../concepts/gui_architecture.md)）：遗留的 `/api/…` 接口是
`ari/viz/routes.py` 中 `BaseHTTPRequestHandler` 子类里针对 `self.path` 的
`if`/`elif` 链，它把每个处理函数直接从各自的 `api_*` 模块导入；
`/api/v1/…` 则被委派给 `ari/viz/v1/router.py` 中声明式的 `ROUTES` 表。

**`ari/viz/api_wizard.py: WIZARD_ROUTES` 并不是第三处。** 该模块以短名字
重导出六个 wizard 处理函数，然后构建了一个四条目的
`{path: (method, callable)}` 字典 —— 但树内没有任何东西导入这个模块，
无论生产代码还是测试，也没有任何分发器查阅这个字典。对改动 wizard 的人
有两个后果：往 `WIZARD_ROUTES` 里加一条并不会生成一条路由；这个字典也不是
wizard 的契约 —— 它其实已经漂移了，四条路径中的 `/api/generate-config`
在服务器上根本不存在（分发器应答的是 `/api/config/generate`）。REST 模式
检查器能够解析模块级的 `ROUTES` / `WIZARD_ROUTES` 映射
（`scripts/check_viz_api_schema.py: parse_declarative_routes`），但该路径
默认关闭 —— `scripts/quality/check_viz_api_schema.yaml` 中的
`use_declarative_routes: false` —— 正是因为这个映射已经陈旧，所以检查器改从
`if`/`elif` 链中提取路由。仓库根部的 `DEPRECATION_REMOVAL.md` 台账把这个
符号记为删除候选；在它被删除之前，请把上述两个分发器当作关于"哪些 wizard
端点存在"的唯一陈述。
