---
sources:
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/contracts.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/slurm.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/counters.py
    role: implementation
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-hpc/skill.yaml
    role: config
  - path: ari-skill-hpc/tests/test_server.py
    role: test
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
  - path: ari-skill-idea/src/server.py
    role: implementation
last_verified: 2026-07-30
---

# MCP 技能参考

技能是为 ARI 智能体提供工具的 MCP 服务器。工具尽可能保持确定性；使用 LLM 的工具会明确标注。**共 14 个技能**（13 个默认，1 个附加）。v0.7.0 新增 `ari-skill-replicate`，用于 PaperBench 形式的可复现性流程。

## ari-skill-hpc

typed 的 SLURM 生命周期、严格的 SSH transport、能力探测，以及 digest 钉定的容器。
**LLM：否**（完全确定性）。

十个工具分三组：两个 typed 提交器（`job_submit`、`container_submit`）与保留下来的
批处理脚本兼容桥（`slurm_submit`）；四个共用同一份句柄选择器的生命周期操作
（`job_status`、`job_result`、`job_logs`、`job_cancel`）；以及三个探测器
（`probe_platform_capabilities`、`counter_support`、`measure_counters`）。容器只经
`container_submit` 及其携带的 digest 钉定 `ContainerRequestV1` 抵达——本包不提供
任何镜像的构建、拉取或运行命令。

### 工具

#### `job_submit(request)`

提交一份不可变的 `JobRequestV1`，并立即返回幂等的 `JobHandleV1`。命令是 `argv`
数组，绝不经过登录节点的 shell。工具只接受一个 `request` 对象——`JobSubmitArgumentsV1`
这层包装的存在，是为了把 JSON Schema 的全部 `$ref` 都收在输入 schema 的根上。
必填项为 `request_id` / `job_name` / `work_dir`（已存在、且不是符号链接的绝对目录）/
`argv` / `resources`，可选项为 `environment` / `container` /
`accelerator_allocation` / `inputs` / `outputs` / `metadata`。

`resources`（`ResourceRequestV1`）声明 `partition`、`nodes=1`、`tasks=1`、
`tasks_per_node=None`、`cpus_per_task=1`、`walltime="01:00:00"`，以及与
`slurm_submit` 同一套语义的 `launcher`（`auto` / `srun` / `none`，默认 `auto`）；
`memory_mb_per_node` / `memory_mb_per_cpu` / `gpus_per_node` / `gpus_per_task` /
`gpu_type` / `nodelist` / `exclude_nodes` / `exclusive` / `constraint` / `hint` /
`account` / `qos` / `reservation` 也在这里给出。

`environment`（`EnvironmentPolicyV1`）的 `export_mode` 固定为 `NIL`：作业环境
只包含此处显式列出的非机密字面量与 `modules`，名字看起来像凭据的变量
（`*_TOKEN`、`*_PASSWORD`、`*_API_KEY` 等）会被直接拒绝，无法藏进作业请求里。

提交按请求 digest 幂等。请求由 `request_digest`（其正规化 JSON 的 sha256）标识，
而这个 digest 在 `sbatch` 之前就已记进持久 ledger：同一份 `JobRequestV1` 再次提交
拿回的是既有的 `JobHandleV1`，而不是第二个作业；transport 在结果未知时断掉，占位
也照样留着，重试因此不会变成重复投入。`sbatch` 始终以 `--parsable --export=NIL`
调用。

`inputs` 的每一份 pin 都必须在提交时对上声明的 sha256 与字节数，并在负载启动前于
节点上再核对一次；声明的 `outputs` 必须落在 `work_dir` 之下，符号链接一律拒绝。
每个作业的产物放在 `{work_dir}/.ari-hpc/{去掉 sha256: 前缀的 request_digest}/`
下，这就是句柄的 `artifact_scope`。

core 智能体的批处理脚本工作流仍走下面的 `slurm_submit` 兼容桥；新的程序化
调用方应使用 `job_submit`。

```python
result = job_submit(request={
    "request_id": "bench_001",
    "job_name": "bench_test",
    "work_dir": "/abs/path/to/workdir",
    "argv": ["./bench", "--threads", "32"],
    "resources": {"partition": "your_partition", "cpus_per_task": 32},
})
# Returns: {"schema_version": "ari.hpc.job-handle/v1", "handle_id": "hpc-...",
#           "request_digest": "sha256:...", "job_id": "12345",
#           "state": "submitted", ...}
```

#### `container_submit(request)`

与 `job_submit` 完全相同的生命周期、完全相同的参数 schema，但请求必须自带
`container` 声明，缺了就以 validation 错误拒绝提交。容器（`ContainerRequestV1`）的
`runtime` 为 `apptainer`（默认）或 `singularity`，`image` 是一份 `ArtifactPinV1`
——即 digest 钉定的镜像（绝对路径 + `sha256:…` + 字节数）。默认 `contain_all` 与
`clean_environment` 为 `true`、`network` 为 `host`、`gpu` 为 `false`；`binds` 默认
只读，且 target 不得重复。

镜像按 digest 钉定，因此字节被换掉的镜像在作业开跑前会被核对拒绝，上了节点还会
再核对一次。声明了容器时，`inputs` 的每一份 pin 还必须落在 `work_dir` 或某个已声明
的 bind 之下；`work_dir` 本身若未被请求声明，会以读写方式 bind 挂载进去。

#### `slurm_submit(script, job_name, partition, nodes=1, tasks=1, tasks_per_node=None, cpus_per_task=1, launcher="auto", walltime="01:00:00", work_dir, modules=[])`

提交 SLURM 批处理作业。

**仅仅申请多个节点，本身并不会用到多个节点。** 批处理主体只在第一个节点上运行；
除非有什么东西启动并行步骤，其余节点都处于空闲。由谁来启动，由 `launcher` 决定：

| `launcher` | 脚本的启动方式 | 适用场景 |
|---|---|---|
| `auto`（默认） | 形状为单节点单任务时绑定到其 CPU 启动，否则直接启动 | 脚本自己调用 `srun` / `mpirun`，或本身是串行的 |
| `srun` | 按声明的 `nodes` / `tasks` / `cpus_per_task` 以 `srun` 启动 | 脚本本身就是并行程序（MPI / SPMD） |
| `none` | 完全按写法原样启动 | 负载必须看到未经改动的批处理步骤 |

`auto` 之所以绑定单任务情形，是因为批处理步骤会继承整个节点的 affinity mask：
否则多线程负载会散布到整台机器上，甚至可能输给它自己的串行基线，读起来像是
kernel 慢，而不是 allocation 未绑定。

**不要**把 `launcher="srun"` 与你自己的 launcher 叠加：
`srun --ntasks=8 mpirun -np 8 ./x` 是六十四个 rank，而下游没有任何环节能把它与
一次正确的 run 区分开。这正是该选择必须显式声明、而不是从 `tasks > 1` 推断的
原因——这两类多任务请求对 scheduler 来说无法区分。

启动模式与 allocation 形状都属于请求 digest，因此同一个脚本在不同形状或不同
launcher 下提交是另一个作业，而不是对第一次提交的 cache hit。

```python
result = slurm_submit(
    script="""
#!/bin/bash
gcc -O3 -fopenmp -o ./bench ./bench.c
OMP_NUM_THREADS=32 ./bench
""",
    job_name="bench_test",
    partition="your_partition",
    cpus_per_task=32,
    work_dir="/abs/path/to/workdir"
)
# Returns: {"schema_version": "ari.hpc.job-handle/v1", "handle_id": "hpc-...",
#           "job_id": "12345", "state": "submitted", "status": "submitted",
#           "message": "Job 12345 submitted successfully",
#           "request_digest": "sha256:...", "submission_digest": "sha256:..."}
```

**注意事项：**
- 写在 `script` 里的 `#SBATCH` 指示行不起作用。生成的头部之后紧接着就是可执行
  内容，`sbatch` 在读到脚本主体之前就已停止解析指示行——形状要用参数
  （`nodes`、`tasks`、`cpus_per_task`、`walltime`）来声明
- 被拒绝的提交不会抛异常，而是返回
  `{"job_id": "", "status": "error", "message": ..., "partition": ...}`
- 脚本主体在 `set -euo pipefail` 下运行，`PATH=/usr/local/bin:/usr/bin:/bin`、
  `LANG` / `LC_ALL=C.UTF-8`，并 unset 掉 `BASH_ENV ENV CDPATH GLOBIGNORE
  PYTHONHOME PYTHONPATH VIRTUAL_ENV`：提交端 shell 的任何东西都不会被继承，
  所以请写绝对路径，并通过 `modules` 取用工具链

#### `job_status(handle_id)`

对一个 ARI 句柄或一个原始 SLURM 作业 ID，返回与供应商无关的 `JobStatusV1`。

`job_status` / `job_result` / `job_logs` / `job_cancel` 共用同一份选择器 schema：
`handle_id`（`JobHandleV1` 的句柄 ID，首选）与 `job_id`（原始 SLURM 作业 ID，
遗留兼容）二选一。它是 `oneOf`，两个都给或都不给都会被拒绝；实现优先读 `handle_id`。
既不是已知句柄、也不是纯数字 SLURM ID 的选择器是 validation 错误。

状态取自 `sacct -j <id> --noheader --parsable2 --allocations
--format=JobID,State,ExitCode,Start,End,Reason`；accounting 尚无记录时回退到
`squeue -j <id> --noheader --format=%T|%R`。

```python
result = job_status(handle_id="hpc-...")
# Returns: {"schema_version": "ari.hpc.job-status/v1", "handle_id": "hpc-...",
#           "job_id": "12345", "state": "succeeded",
#           "scheduler_state": "COMPLETED", "exit_code": 0,
#           "start_time": ..., "end_time": ..., "reason": None}
```

`state` 是归一化后、与供应商无关的值——`submitted` / `running` / `succeeded` /
`failed` / `cancelled` / `unknown` 之一——而 `scheduler_state` 保留 SLURM 自己的
措辞。`PENDING` / `CONFIGURING` / `REQUEUED` / `RESIZING` / `SPECIAL_EXIT` 归一
为 `submitted`；`RUNNING` / `COMPLETING` / `SUSPENDED` / `STAGE_OUT` 归一为
`running`；`COMPLETED` 归一为 `succeeded`；`CANCELLED`（两种拼法）/ `DEADLINE` /
`REVOKED` 归一为 `cancelled`；`BOOT_FAIL` / `FAILED` / `NODE_FAIL` /
`OUT_OF_MEMORY` / `PREEMPTED` / `TIMEOUT` 归一为 `failed`。scheduler 不肯作答的
作业读作 `state: "unknown"`、`scheduler_state: "UNKNOWN"`——那是被记录下来的
「没有证据」，不是错误。

没有 `ERROR` 这个状态。调用失败返回的是错误信封
`{"error": {"kind": ..., "message": ..., "retryable": ...}}`，其中 `kind` 取
`validation` / `transport` / `scheduler` / `unknown`；message 在离开工具前会先被
清洗掉形似凭据的文本。

#### `job_result(handle_id)`

收集终态的 `JobResultV1`：重新哈希声明的 inputs / outputs 与日志，并把结果原子
写入 `{artifact_scope}/result-v1.json`。选择器与 `job_status` 相同。

作业必须是经 ARI 投入的（要有 ledger 记录和句柄），并且带 typed 请求：
`slurm_submit` 兼容桥投入的作业能取到 status 与 logs，但取不到 typed 的
`JobResultV1`。在作业进入终态（`succeeded` / `failed` / `cancelled`）之前调用是
validation 错误。

声明的每一份 input 按其 pin 重新验证，声明的每一份 output 从磁盘上的实际文件重新
哈希成 `ArtifactPinV1`，日志与 provenance pin 一并附上——submission record、执行
环境快照、module 清单、容器 runtime 版本、退出码，以及请求声明了独占分配时的
exclusive-allocation 与 accelerator-inventory 见证。缺少 `required: true` 的 output
不是异常，而是以 `error.kind = "artifact"` 落进结果里。以任何非 `succeeded` 终态
结束的作业得到 `error.kind = "execution"`，其中 `NODE_FAIL` / `PREEMPTED` /
`REQUEUED` 标记为 `retryable`。

返回值带 `request_digest` / `environment_digest` / `module_digest`，以及存在时的
`module_snapshot_digest` / `container_digest` / `accelerator_allocation_digest` /
`accelerator_inventory_digest`，最后由覆盖其余部分的 `result_digest` 把整份结果
封口。

#### `job_logs(handle_id)`

读取 ARI 作业句柄的有界、带 digest 的 stdout / stderr。选择器与 `job_status`
相同，同样只对经 ARI 投入的作业可用。

```python
result = job_logs(handle_id="hpc-...")
# Returns: {"schema_version": "ari.hpc.job-logs/v1", "logs": [...]}
```

每条日志给出 `stream`（`stdout` / `stderr`）/ `path` / `digest` / `size_bytes` /
`text` / `truncated`。`text` 在 1 MiB（1,048,576 字节）处打住并置
`truncated: true`——截断是看得见的，不会被当成完整输出。`digest` 与 `size_bytes`
在共享文件系统上直接读取日志时是对整个文件而言的；若走的是非共享的 transport，
日志经该 transport 取回，`digest` 与 `size_bytes` 便也只覆盖同样这 1 MiB。
日志从句柄 `artifact_scope` 下的 `slurm-{job_id}.out` / `.err` 读取；
没有对应文件的那一路直接略去，而共享文件系统上日志必须是普通文件，符号链接会被
拒绝。

#### `job_cancel(handle_id)`

请求取消一个 ARI 或 SLURM 作业。选择器与 `job_status` 相同，内部执行
`scancel <job_id>`。

```python
result = job_cancel(handle_id="hpc-...")
# Returns: {"schema_version": "ari.hpc.job-cancel/v1", "handle_id": "hpc-...",
#           "job_id": "12345", "status": "cancel_requested"}
```

名字是精确的：返回的是 `scancel` 受理了这个请求，而不是作业已经停下。作业本身的
情况要靠轮询 `job_status` 去看——被取消的作业读作 `state: "cancelled"`。`scancel`
自身被拒绝时，调用返回 `kind: "scheduler"` 的错误信封。

#### `probe_platform_capabilities(checkpoint_dir, partition="", tools="")`

在**计算分区上**探测工具可用性（`command -v`），并将结果缓存到
`{checkpoint_dir}/platform_capabilities.json`。`tools` 是逗号分隔的清单，默认取
`ARI_PROBE_TOOLS`，再没有则是 `perf,numactl,papi_avail,likwid-perfctr,valgrind`；
`partition` 为空时回退到 `ARI_SLURM_PARTITION`。

真正跑完的探测返回 `{"status": "probed", "partition": ..., "arch": ...,
"available": {"perf": true, ...}}`，其中 `available` 把每个被探测的名字映到一个
布尔值。探测跑了但缓存写不下去时，同一份记录以
`{"status": "unsaved", "reason": ..., ...}` 返回；已有有效缓存则直接返回
`{"status": "cached", ...}`，不再重新探测。设计上尽力而为：任何失败（无分区、
缺少 `srun`、排队超时）都返回 `{"status": "skipped", "reason": ...}` 且不写任何
文件。claims 抽取器会读取该缓存，从而不会声明依赖平台上确实缺失的工具的证据。

#### `counter_support()`

报告本节点是否授予硬件计数器——靠真的打开一个来确定，而不是去找 profiler
二进制文件。无参数。`perf` 在某些允许计数的节点上并不存在，在某些拒绝计数的
节点上反而装着，厂商 profiler 的路径又依站点而异；只有打开计数器，才能观察到
真正会生效的 kernel 策略，而且是在该节点实际运行的容器内部观察到的。

```python
result = counter_support()
# Returns: {"schema_version": "ari.hpc.counter-support/v1", "architecture": "...",
#           "perf_event_paranoid": ..., "reviewed_events": [...],
#           "status": "ready", "detail": None}
```

`status` 取 `ready`；自探测被 `EACCES` 或 `EPERM` 拒绝时取 `denied`；该架构没有
经审查的 `perf_event_open` 调用号、或自探测因其他原因失败时取 `unsupported`；
非 Linux 主机上取 `unavailable`。

#### `measure_counters(pid, window_ms=1000, events=["cycles", "instructions"])`

在有界窗口内，对一个**已经在运行的**进程计数经审查的硬件事件。这是 profiling
而不是执行：不创建进程、不写任何文件、也不索取凭据。

- `pid` 必填，必须指向一个在跑的进程。
- `window_ms` 取 1 … 60000（`MAX_WINDOW_MS`），默认 1000。
- `events` 只能取经审查集合中的名字：`branch-instructions`、`branch-misses`、
  `cache-misses`、`cache-references`、`cycles`、`instructions`。集合之外的一律
  拒绝，调用方无法借此触达任意 raw event 编码。默认
  `["cycles", "instructions"]`。

计数器以最小权限打开（`exclude_kernel` + `exclude_hv`），因此被拒绝时反映的是
策略本身，而不是一个过宽的请求；返回值里的 `excluded: ["kernel", "hypervisor"]`
把这一点记下来。

```python
result = measure_counters(pid=12345, window_ms=2000)
# Returns: {"schema_version": "ari.hpc.counter-measurement/v1", "status": "measured",
#           "support": {...}, "pid": 12345, "window_seconds": 2.000123,
#           "counters": {"cycles": ..., "instructions": ...},
#           "excluded": ["kernel", "hypervisor"]}
```

`counter_support()` 不是 `ready`，或者对目标 pid 打不开计数器时，`counters` 为空，
`status` 带回 `denied` / `unavailable` / `unsupported`，并附上那份 support 记录。

这是唯一在 `skill.yaml` 中声明 `context_requirement: node` 的 HPC 工具，因此它的
输入 schema 必须声明一个 `ari_context` 对象属性：transport 会以这个名字为任何带
context 要求的工具注入已授权的节点 context，而该 schema 又设了
`additionalProperties: false`——不声明它，就会拒绝掉每一次已授权的调用。proxy 会
在 `tools/list` 里把这个属性剥掉，并在 `tools/call` 时改写它，所以它绝不会是智能体
自己传的参数。

---

## ari-skill-idea

文献调研和想法生成。**LLM：是**（generate_ideas 使用 VirSci 多智能体讨论）。

### 工具

#### `survey(topic, max_papers=8)`

先前工作调研。确定性（无 LLM）。按顺序尝试以下来源：idea 阶段已为本次
run 的主题构建好的冻结 `virsci_snapshot` 语料库；然后是实时 Semantic
Scholar 查询（先 HTTP，再用 `semanticscholar` 客户端重试）；最后是
**arXiv 回退**——这样无 key 或被限流的 S2 就不会悄悄抹掉先前工作的支撑。
随后会用被引论文对靠前的结果做 2 跳扩充。任何降级（包括最终 0 篇）都会
在 stderr 上报告。

```python
result = survey("OpenMP compiler optimization HPC benchmarks")
# Returns: {"papers": [{"title": "...", "abstract": "...", "url": "..."}]}
```

设置 `S2_API_KEY` 可获得更高的 Semantic Scholar 速率限制。`max_papers`
上限为 15。

`survey` 和 `generate_ideas` 是该技能**仅有的**已注册 MCP 工具；
`_load_virsci_snapshot_papers` 只是 `survey` 直接调用的普通辅助函数，绝不
能对 agent 可见。`tests/test_server.py` 通过 `mcp.list_tools()` 同时钉住
这两点（`@mcp.tool()` 装饰器丢失/错位的问题曾经上线过）。

#### `generate_ideas(topic, papers, experiment_context="", n_ideas=3, n_agents=4, max_discussion_rounds=2, max_recursion_depth=0)`

使用 VirSci 多智能体 LLM 讨论生成研究假设。多个 AI 角色（研究者、批评者、专家、综合者）就研究问题进行辩论。在默认的 `simple_bfts` 模式下，仅在 BFTS 启动前调用**一次**（仅限 pre-BFTS）。在可选启用的 `ari_rqgm` 模式下且 `proposal_router.generators.virsci.enabled: true` 时，core 侧的 `VirSciAdapter` 会额外通过 ProposalRouter 的事件触发、预算封顶的调度调用 `survey` + `generate_ideas` —— 见 [VirSci 集成](../guides/virsci_integration.md)。

模型：`ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > `ollama_chat/qwen3:32b`。

#### VirSci-live (vendor-wrap) — 可选的真实引擎

`generate_ideas` 在同一份想法契约背后有两个可互换的引擎。默认（**reimpl**，行为不变）
运行轻量级的再实现讨论循环。可选（**real_wrap**）则改为运行 VirSci 的*真实*机制 ——
来自同捆且**未改动**的 `vendor/virsci` 的 `Platform.select_coauthors`（freshness 团队组建）
+ `Team.generate_idea`（多智能体讨论）—— 并以一份**实时**的 Semantic Scholar 快照
（语料 + SPECTER2 余弦检索索引 + 作者画像 + 合著者图）为基底。

- **默认关闭** = 行为与之前逐字节一致。启用方式：环境变量 `ARI_IDEA_VIRSCI_REAL=1`、
  CLI 标志 `--virsci-live`，或 GUI 实验向导的 "VirSci live" 开关（Scope/Resources 步骤；
  持久化到 `launch_config.json`）。
- **安全降级。** 当依赖缺失（`virsci` pip extra 不存在）或发生任何运行时错误时，
  技能回退到 reimpl 循环。两条路径的 `idea.json` 契约完全一致。此外，实时快照构建现在会
  **在空的 / 0 篇论文的 S2 拉取时显式失败**（429 限流、网络故障或无搜索命中）：与其静默写入一份
  带占位作者的「成功」0 篇清单——那会让 VirSci 在完全无接地的情况下运行却被记为 `real_wrap` 成功
  ——它会抛出异常，使 `generate_ideas` **可见地** 降级到 reimpl 循环。`n_papers == 0` 的已缓存清单
  被视为被污染的缓存，绝不复用（会重建）。当主题 `/paper/search` 被限流（S2 429）但 survey 已经
  审定过 paperId 时，构建会通过 `/paper/batch`（按 id 检索，更有针对性且更不易被限流）拉取一份种子
  语料来恢复，并将其记录到 `virsci_snapshot/snapshot_manifest.json` 的 `seed_fallback` 字段。
- **路径报告。** `idea.json` 记录 `virsci_integration_status`：vendor 引擎运行时为
  `"real_wrap"`，使用 reimpl 循环时为（附带原因的）`"reimpl: …"`。
- **LLM：** 讨论遵循按 phase 的 Idea 模型（`ARI_MODEL_IDEA`）；引擎调用经由 litellm 路由，
  因此 ARI 的 cost tracker 会捕获它们。
- **范围：** 单一实时快照 —— 无 era 拆分 / 无 paper-parity（这些是 VirSci 回溯式基准的产物，
  不在范围内）。freshness/diversity 来自 S2 作者画像 + 合著者图。
- **依赖：** `virsci` pip extra（faiss-cpu、transformers、torch、loguru、sqlalchemy）；
  SPECTER2 权重在运行时获取；需要 `SEMANTIC_SCHOLAR_API_KEY` / `S2_API_KEY`
  （用于 `embedding.specter_v2`）以及一个 OpenAI 兼容的 LLM 端点（ARI CLI 垫片）。

环境变量（仅开关为必需，其余可调 —— 见
[环境变量](environment_variables.md)）：

| 变量 | 默认值 | 用途 |
|---|---|---|
| `ARI_IDEA_VIRSCI_REAL` | 未设置 (off) | 切换 real vendor-wrap 路径 |
| `ARI_IDEA_VIRSCI_K` | `7` | 讨论轮数（vendor `group_max_discuss_iteration`） |
| `ARI_IDEA_VIRSCI_TEAM_SIZE` | `3` | 团队最大成员数（vendor `max_teammember`） |
| `ARI_IDEA_VIRSCI_N_AUTHORS` | `16` | `select_coauthors` 的作者池 |
| `ARI_IDEA_VIRSCI_N_PAPERS` | `800` | SPECTER2 检索语料规模 |
| `ARI_IDEA_VIRSCI_MAX_TEAMS` | `n_ideas` | 投入 `generate_idea` 的团队数上限 |
| `ARI_IDEA_VIRSCI_SPECTER2_MODEL` | `allenai/specter2_base` | 本地查询嵌入器 |

`ari run` 上的 CLI 标志：`--virsci-live` / `--no-virsci-live`、`--virsci-k`、
`--virsci-team-size`、`--virsci-n-authors`、`--virsci-n-papers`。

---

## ari-skill-evaluator

从实验文件中提取指标规格。**LLM：条件性**（仅在文本中未找到 metric_keyword 时回退使用 LLM）。

### 工具

#### `make_metric_spec(experiment_text)`

解析实验 Markdown 以提取评估标准。当文本中包含 `metric_keyword` 和 `min_expected_metric` 时为确定性操作；未找到时回退使用 LLM。

```python
result = make_metric_spec(open("experiment.md").read())
# Returns: {
#   "metric_keyword": "MFLOPS",
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "..."
# }
```

`make_metric_spec` 还会从想法的 `primary_metric`、其结构化的 `falsifiable_claims`，以及
`correctness_required` / `ceiling_must_be_measured` 要求标志，构建一份 **想法所有的 run 级
`metric_contract`**，并持久化到 `{checkpoint}/metric_contract.json`（位于 `idea.json` / `tree.json`
旁边）。该契约由想法所有，因此智能体无法删除某个 claim 或要求来规避检查；它由
`transform-skill::nodes_to_science_data` 读回并 graft 到 `science_data.metric_contract`，再由确定性的
硬门强制执行。

模型（回退）：`ARI_MODEL` 环境变量 > `gpt-4o-mini`。

#### `claim_evidence_hard_gate(checkpoint_dir, paper_path, science_data_json="", paper_claim_links_path="", figures_manifest_json="", policy=None, phase="draft")`

确定性的声明/证据硬门（执行数据保真度）。**无 LLM**。验证 science_data 声明所引用的节点确已执行，从 `results.json` 重新计算 `numeric_assertions` 并在容差内核对论文报告的数值，按章节策略检测未覆盖的结果数值，并检查图表是否存在。它是 ari-core `run_hard_gate`（`ari.public.claim_gate`）之上的 MCP 薄包装。在 strict 模式下，当存在阻塞性错误时 `final` 阶段返回 `{"error": ...}`，使阶段运行器抛出异常并跳过 `finalize_paper`；`draft` 阶段以及 warn/off 模式从不阻塞。写出 `evaluation/claim_evidence_hard_gate_{phase}.json`。

#### `evidence_grounded_semantic_review(checkpoint_dir, paper_path, science_data_json="", hard_gate_path="", paper_claim_links_path="", phase="initial")`

非阻塞的、以证据为基础的语义评审。**LLM：是**。LLM 基于硬门证据检测过度声明 / 解释性问题 / 未注册的强声明，而**不**触碰独立的文本审稿人；它不重新核对数值。输出供 `paper_refine` 消费的 `suggested_revisions` 以及评分。写出 `evaluation/evidence_grounded_semantic_review.json`。从不阻塞。

---

## ari-skill-paper

LaTeX 论文生成、编译和审阅（仅限 Post-BFTS）。**LLM：是**。

### 工具

#### `list_venues()`

返回可用的场所配置。

支持的场所：`neurips`（9 页）、`icpp`（10 页）、`sc`（12 页）、`isc`（12 页）、`arxiv`（无限制）、`acm`（10 页）。

#### `get_template(venue)`

返回指定场所的 LaTeX 模板。

#### `generate_section(section, context, venue="arxiv", nodes_json_path="", refs_json="")`

使用 LLM 生成 LaTeX 章节。章节类型：`introduction`、`related_work`、`method`、`experiment`、`conclusion`。

#### `compile_paper(tex_dir, main_file="main.tex")`

运行 pdflatex 编译。返回成功状态和错误信息。

#### `check_format(venue, pdf_path)`

根据场所要求验证论文格式（页数等）。

#### `review_section(latex, context, venue="arxiv")`

审阅 LaTeX 章节。返回优点、缺点和建议。

#### `revise_section(section, latex, feedback, context, venue="arxiv")`

根据审阅反馈修改 LaTeX 章节。

#### `write_paper_iterative(experiment_summary="", context="", nodes_json_path="", refs_json="", figures_manifest_json="", science_data_json="", venue="arxiv", max_revision_rounds=2, author_name="")`

完整论文生成，包含迭代式草稿 -> 审阅 -> 修改循环。主要流水线工具。

#### `review_compiled_paper(tex_path, pdf_path, figures_manifest_json, experiment_summary, rubric_id="", vlm_findings_json="", num_reflections=None, num_fs_examples=None, num_reviews_ensemble=None)`

**AI Scientist v1/v2 兼容** 的基于评审规范的论文审阅（遵循 Nature /
arXiv:2408.06292 附录 A.4）。从 `ari-core/config/reviewer_rubrics/<rubric_id>.yaml`
加载评审规范，根据 `score_dimensions` / `text_sections` / `decision` 动态生成
提示。VLM 的逐图反馈（分数 / 问题 / 建议）作为审稿人备注注入，并附加
Few-shot 示例，经 Self-reflection 循环自我批评修订后输出符合评审规范的 JSON。

已内置评审规范（`ari-core/config/reviewer_rubrics/` 下 16 个 YAML）：

| 类别 | rubric_id |
|---|---|
| ML 会议 | `neurips`（默认，v2 兼容）/ `iclr` / `icml` / `cvpr` / `acl` |
| 系统 / HPC | `sc` / `osdi` / `usenix_security` |
| 理论 / 图形学 | `stoc` / `siggraph` |
| HCI / 机器人 | `chi` / `icra` |
| 期刊 / 通用 | `nature` / `journal_generic` / `workshop` / `generic_conference` |

在 `reviewer_rubrics/` 目录放一份 YAML 即可扩展新的会议，无需修改代码。
每个评审规范声明 `score_dimensions` / `text_sections` / `decision` 规则、
执行参数及用于 P2 确定性的 SHA256 哈希。

解析顺序：显式 `rubric_id` 参数 → `ARI_RUBRIC` 环境变量 → `neurips` →
内置 `legacy` 回退（v0.5 schema，当 `rubric_id` 与 YAML 都解析不到时使用）。

#### 对称的作者 / 审稿人 venue 条件化（未发布）

`prompt_overrides` 携带两个平行字段：

- `system_hint` —— 由 `review_engine` 注入同行评审提示词（既有行为）。
- `author_hint` —— 由 `generate_section` 作为专门的 `══ VENUE-SPECIFIC
  AUTHOR GUIDANCE ══` 块注入论文起草提示词。告诉起草者审稿人会关注
  什么，从而在写作阶段就让这些信号易于呈现。

`author_hint` 为空时保留旧的弱追加行为（仅 `Target venue: X. Page
limit: N pages.`）。SC 与 NeurIPS 附带经校准的 `author_hint` 块；其余
venue 为空，可在不改代码的情况下逐步补齐。

Nature Ablation 默认值：

- `num_reflections: 5` — +2% 平衡精度
- `num_fs_examples: 1` — +2% 精度（ICLR 审稿指南 1-shot）
- `num_reviews_ensemble: 1` — 集成只降方差不提升精度
- `temperature: 0.75`

模型：`ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > `ollama_chat/qwen3:32b`。

**集成 + Area Chair 元审稿（内置）：** `review_compiled_paper` 通过集成路径
运行 N 个独立审稿人代理（带温度抖动，AI Scientist v1 best-config 风格）。
当 N>1 时，还会在内部运行 Area Chair 元审稿，并将 `ensemble_reviews: [...]`
和 `meta_review: {...}` 附加到输出。N 的解析顺序：显式参数 >
`ARI_NUM_REVIEWS_ENSEMBLE` 环境变量 > `rubric.params.num_reviews_ensemble`
（默认 1）。N=1 等价于单审稿人。

#### `list_rubrics()`

返回可用 rubric 的列表（id、venue、domain、version、SHA256 hash、path）。
viz API `/api/rubrics` 和 New Experiment 向导下拉菜单会用到。

#### `inject_code_availability(tex_path, ref="", sha256="", doi="", license_id="", checkpoint_dir="")` — v0.7.0

作为 `finalize_paper` 阶段运行。从 `ear_published/manifest.lock` 与 `publish_record.json` 自动加载 `ref` / `bundle_sha256` / `doi`，并将机器可读的 `\codeavailability{}` / `\codedigest{}` / `\coderef{}` 宏与人类可读的 Code Availability 章节注入 `full_paper.tex`。digest 是信任锚点，读者无需信任 registry 即可 `ari clone <ref> --expect-sha256 <baked-digest>` 进行验证。如果未策展 bundle 则静默跳过（保持 v0.6.0 checkpoint 兼容）。

#### `merge_reviews(review_report_path, vlm_review_path="")` — v0.7.0

将 `review_report.json`（文本评审）与 `vlm_review.json`（VLM 图表评审）做事后结构合并。完全确定性、无 LLM。附加 `vlm_figure_review` 与 `_review_composition` 元数据，使 GUI / CLI 能附带来源标注同时显示两类输出。上游阶段保持独立（与 AI Scientist v2 `perform_review` 契约一致），在此处方完成对账。

#### `link_paper_claims(tex_path="", science_data_json="", figures_manifest_json="", output_path="")` — v0.9.0

将 `% CLAIM:Cx:NCx` 锚点与 science_data 声明对账，并构建供 claim 硬门消费的
`paper_claim_links.json`（anchors / writer_assertions / numeric_mentions /
figure_refs / unresolved_anchors / uncovered_numeric_candidates）。**确定性、无 LLM**。
transform 阶段的 `science_data.json` 从不被改动；图表绑定记录在此。在 `write_paper`（草稿）之后运行一次，
并在 `paper_refine`（终稿）之后再运行一次。失败时降级为一份合法的空结果（绝不仅输出 error），
因此它不会级联跳过 finalize 链。

#### `paper_refine(tex_path="", suggested_revisions_json="", merged_review_path="", semantic_review_path="", venue="arxiv")` — v0.9.0

保留锚点的修订流程，应用（来自 `evidence_grounded_semantic_review` / 合并评审的）
`suggested_revisions`。**LLM：是**。显式的 `replace "X" with "Y"` 替换先确定性地应用，
随后由有界的多趟 LLM 查找/替换处理其余部分；草稿中存在的每一个 `% CLAIM` 锚点都必须存活
（丢弃锚点的编辑会被拒绝，且当锚点净损失时保留原始论文）。数学安全的下划线转义会跳过
`\( … \)` / `\[ … \]` 与数学环境。精修后的 LaTeX 在 `latex` 下返回（草稿保留为 `full_paper.draft.tex`）。

##### Few-shot 语料库管理

`ari-core/config/reviewer_rubrics/fewshot_examples/<rubric>/` 下的文件可通过**New Experiment 向导 → Paper Review → Few-shot 示例** 子面板 (GUI) 或 `scripts/fewshot/sync.py` (CLI) 管理。

GUI 操作:

- **Auto-sync**: 服务器端运行 `scripts/fewshot/sync.py --venue <rubric>` 拉取 `manifest.yaml` 中声明的条目。默认包含 AI Scientist v2 的三个示例 (`132_automated_relational` / `2_carpe_diem` / `attention`)，从 Apache-2.0 许可的 `SakanaAI/AI-Scientist-v2` 仓库下载。
- **Upload**: 接受符合 rubric schema 的 JSON + 可选 `.txt` 摘录 + 可选 PDF (base64)，自动标注 `_source: "GUI upload (rubric=<id>)"`。
- **Delete**: 删除示例的所有扩展名文件。

REST 端点:

- `GET  /api/fewshot/<rubric>`
- `POST /api/fewshot/<rubric>/sync`
- `POST /api/fewshot/<rubric>/upload`
- `POST /api/fewshot/<rubric>/<example>/delete`

所有端点都会拒绝 `reviewer_rubrics/` 中不存在的 rubric，并从输入中剥离 `../` / 斜杠字符。

---

## ari-skill-paper-re

基于 PaperBench (arXiv:2504.01848) **SimpleJudge** 的可复现性评分。**LLM：是**（评分由 upstream `SimpleJudge` 内部的 LLM 调用完成；ARI 在本技能中不增加额外的 LLM 调用）。

v0.7.0 将 v0.6.0 的 LLM 驱动判定路径替换为以 PaperBench 为评分内核的确定性端到端链：

```
ors_generate_rubric  (replicate-skill)    → ors_rubric.json + ors_rubric.meta.json
ors_audit_rubric     (replicate-skill)    → 一份独立的审计文档；ors_rubric.json 不会被改写
ear_publish          (transform-skill)    → bundle.tar.gz + publish_record.json (默认 local-tarball)
ors_seed_sandbox     (paper-re-skill)     → repro_sandbox/{reproduce.sh, code/...}
                                              (确定性；fetch_code_bundle ← publish_record.json)
ors_build_reproduce  (paper-re-skill)     → repro_sandbox/{reproduce.sh, source files}
                                              (LLM 回退；如已 seed 则跳过)
ors_run_reproduce    (paper-re-skill)     → ors_phase1.json   (Phase 1：在沙箱中执行 reproduce.sh)
ors_grade            (paper-re-skill)     → ors_grade.json    (Phase 2：用 SimpleJudge 对 rubric 叶节点评分)
```

`ors_audit_rubric` 检查下游一切评分所依据的 rubric 本身：为每个叶节点标记
`vague_qualifier` / `no_paper_evidence` / `duplicate`（确定性）与
`unverifiable`（每叶一次 LLM 调用），并在超过 20% 叶节点被标记时返回
`regen_recommended`。冻结后的 rubric **不会**被改写——结论写入一份独立的
`ari.replication-rubric-audit/v2` 文档（默认路径 `<rubric_path>.audit.json`），
其中绑定了 rubric 与 paper 的 digest，使两者无法各自漂移。它是信号而非闸门——
评分照常进行。可用 `ARI_MODEL_RUBRIC_AUDIT` 指向与生成方不同的模型。

EAR 开启的运行通过 `ors_seed_sandbox`（确定性）获取 reproduce.sh；LLM `ors_build_reproduce` 在 reproduce.sh 已存在时跳过，所以仅在 EAR 关闭（论文唯一复现）时触发。

PaperBench 以 git submodule 形式同捆于 `ari-skill-paper-re/vendor/paperbench`。主要逐叶评分 completer 通过 LiteLLM (`_litellm_completer.py`) 路由，因此任意供应商可用（`gpt-5-mini` / `anthropic/claude-...` / `gemini/...` / `ollama/...`）；分数解析的 structured completer 仍使用 `gpt-4o-2024-08-06`（在 PaperBench 允许列表内）。

### 工具

#### `fetch_code_bundle(ref="", sha256="", dest="", checkpoint_dir="", overwrite=False)`

确定性地填充沙箱（无 LLM）。**v0.7.0+**: 传入 `checkpoint_dir` 可从 `{checkpoint_dir}/publish_record.json` 自动读取 ref + sha256（即 `ari ear publish` 写入的文件）。当 `dest/reproduce.sh` 已存在时返回 `populated=False, skipped_reason=...` 并跳过。

#### `build_reproduce_sh(paper_path="", paper_text="", rubric_path="", output_dir="", model="", time_limit_sec=43200, iterative_agent=False, max_steps=0, sandbox_kind="auto", container_image="", apptainer_image="", overwrite=False)`

**v0.7.0+ 新增的 LLM 驱动 replicator**。`fetch_code_bundle` 的兄弟工具。读取论文（与 rubric 的 `expected_artifacts`）并将自包含的 `reproduce.sh` + 源文件写入 `output_dir`。通过 LiteLLM 路由，任意供应商可用。当 `output_dir/reproduce.sh` 已存在时跳过。模型：`model` 参数 > `ARI_MODEL_REPLICATE` > `ARI_LLM_MODEL` > `claude-opus-4-7`。

#### `run_reproduce(rubric_path, repo_dir, sandbox_kind="", container_image="", timeout_global_sec=0, partition="", cpus=0, walltime="", …SLURM flags)`

**Phase 1**。在沙箱中执行 `repo_dir/reproduce.sh`，捕获 `reproduce.log` 与产物列表，并对照 rubric envelope 的 `expected_artifacts` 检查缺失项 `missing`。

沙箱优先级（默认 `auto`）：`slurm`（sbatch + `ARI_SLURM_PARTITION` 存在，BFTS 同分区）→ `docker`（守护可用且非 HPC 时）→ `apptainer` → `singularity` → `local`。**SLURM dispatch** 在 v0.7.0 已从 v0.5.0 恢复：使用 `sbatch --wait` 同步执行，并生成 spool relocation 包装器以保护 `$0` 相对 cd。

#### `grade_with_simplejudge(rubric_path, repo_dir, paper_path="", paper_text="", judge_model="", n_runs=0, skip_negative_control=False, code_only=False)`

**Phase 2**。主评分 completer 通过 LiteLLM 运行 + 直连 OpenAI 的 structured score-parser。`n_runs`（默认 3）次按 PaperBench 加权叶节点聚合取均值，附负样本对照。

返回值：`{ors_score, raw_score, leaf_grades, judge_model, n_runs, rubric_sha256, elapsed_sec, negative_control: {empty, boilerplate, passed}}`。

模型：`judge_model` 参数 > `ARI_MODEL_JUDGE` > `ARI_LLM_MODEL` > `gpt-5-mini`。任意 LiteLLM 可识别的 model id 均可（绕过 PaperBench 原生 `CONTEXT_WINDOW_LENGTHS` 约束）。

---

## ari-skill-replicate

v0.7.0 引入的 PaperBench 形式 **自动 rubric 生成与审计**。读取论文并输出 frozen rubric（`replication_rubric.schema.json`，带 provenance 元数据的 PaperBench `TaskNode` 树）。**LLM：是**。

与 `ari-skill-paper-re.grade_with_simplejudge` 共同构成取代 v0.6.0 `react_driver` 可复现性检查的 ORS 流水线。

### 工具

#### `generate_rubric(paper_path="", paper_text="", output_path="", target_leaf_count=0, model="", temperature=0.0, seed=0, paperbench_rubric_id="", max_model_calls=64, subtree_concurrency=4, provider="", model_revision="")`

生成 PaperBench 兼容的 rubric。当 `target_leaf_count=0` 时按论文长度自动估算叶节点数（约 1 叶 / 75 词，限制在 [50, 400]）。

生成始终是分层的：单次调用路径已被移除，冻结后的 envelope 无条件记录 `strategy: "hierarchical-v2"` / `quality_profile: "calibrated"`。①骨架阶段（`prompts/skeleton.md`）定义根 + 直接子节点（每项贡献/实验一个）并分配各子树叶数预算 → ②子树阶段（`prompts/subtree.md`）以 `subtree_concurrency` 的并发度对每个直接子节点递归展开其子树。合并后，违反 schema `minLength=10` 的叶（`quote` / `requirements` 过短）会被自动剪除，无法绑定到论文精确 span 或显式 external prerequisite 的叶同样会被剪除。`max_model_calls` 限定整次运行的调用上限，每一对提示词/响应都保留在 `.ari-rubric/` 下并列入 `generator.calls`。

`paperbench_rubric_id`（未发布）从
`ari-core/config/paperbench_rubrics/<id>.yaml` 中选择一个 venue 条件化
模板。空字符串 = 原样使用捆绑提示词（向后兼容）。非空值会加载该
YAML，并通过 `{VENUE_HINT}` 占位符把 `prompt_overrides.system_hint` /
`prompt_overrides.leaf_style` 注入骨架 + 子树提示词。这与
`ari-skill-paper` 在同行评审中已使用的 `reviewer_rubrics/` venue 模式
一致，因此同样的 `venue → YAML → prompt` 流程现在也适用于 rubric
生成器。附带模板：`generic`（向后兼容）、`sc`（HPC 论文审计，6 轴）、
`neurips`（ML 可复现性，6 轴）、`nature`（湿实验，5 轴）。YAML schema 见
[`docs/reference/rubric_schema.md`](rubric_schema.md#venue-conditioned-templates)。

#### `audit_rubric(rubric_path, paper_path="", paper_text="", auditor_model="", output_path="", max_model_calls=400)`

独立审计步骤。将问题叶节点标记为 `vague_qualifier` / `no_paper_evidence` / `duplicate` / `unverifiable`；超过 20% 时建议重新生成。

冻结后的 rubric 绝不会被改写：结论进入一份独立的 `ari.replication-rubric-audit/v2` 文档，写到 `output_path`，为空时则写在 rubric 旁边的 `<rubric_path>.audit.json`。审计开始前会重新校验 rubric 自身的 digest、它的 `paper_sha256` 与传入论文文本是否一致，以及生成方的 provenance artifact。当审计方的 model/provider/revision 身份与生成方相同时，报告记录 `independence_status: "not-independent"`。

#### `suggest_target_leaf_count(paper_path, paper_text)`

返回根据论文长度自动估算的目标叶数与词数。供 GUI Wizard "Target leaves" 字段预填使用。

### v0.7.2 — `reproduce_contract.execution_profile`

当论文指明并行执行属性（MPI rank 数、GPU 型号、独占性、内存、NUMA
绑定）时，骨架 + 子树提示词现在会指示生成器填充
`reproduce_contract.execution_profile`。Schema：
[`docs/reference/execution_profile.md`](execution_profile.md)。
该字段可选且向后兼容 —— 单 CPU 论文不写该字段。

### 环境变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `ARI_MODEL_RUBRIC_GEN` | `gemini/gemini-2.5-pro` | 生成 LLM |
| `ARI_MODEL_RUBRIC_AUDIT` | `anthropic/claude-opus-4-7` | 审计 LLM（与生成器独立） |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | (未设置) | 覆盖目标叶数。`0` / 未设置时按论文长度自动。GUI Wizard "Target leaves" 字段。 |
| `ARI_RUBRIC_GEN_TEMPERATURE` | (未设置) | 覆盖生成器 temperature。GUI Wizard "Temperature" 字段。 |
| `ARI_RUBRIC_GEN_TWO_STAGE` | (未设置) | 强制开/关两阶段生成（`1`/`true`/`on` vs `0`/`false`/`off`）。未设置时使用 kwarg 默认（当前 `True`）。GUI Wizard "两阶段生成" 切换。 |

`server.py` 按 "显式 kwarg → 环境变量 → 默认值" 的顺序解析。`workflow.yaml` 的 `ors_generate_rubric` 阶段未显式传递这三个参数，因此 GUI Wizard 的值始终生效。

---

## ari-skill-memory

祖先作用域的节点记忆（v0.6.0 起由 [Letta](https://docs.letta.com) 支持）。防止跨分支污染，ReAct 轨迹也存放在同一个 Letta 代理中。**LLM：△**（基于嵌入的检索。P2 放宽详见 `docs/concepts/PHILOSOPHY.md`）。

### 工具

#### `add_memory(node_id, text, metadata=None)`

存储标记了 `node_id` 的条目。**Copy-on-Write**：若 `node_id` 与 `$ARI_CURRENT_NODE_ID` 不一致，则拒绝写入。

#### `search_memory(query, ancestor_ids, limit=5)`

按 **Letta `passages.search`（基于 embedding 的语义搜索）排序**，仅返回 `ancestor_ids` 中节点的条目。兄弟/子节点永远不会返回。

实现说明（对 Letta 0.16.7 在 2026-05-04 验证）：本技能刻意 **不使用** SDK 的 `passages.list(search=q)`。该 SDK 路径在服务端为 `GET /archival-memory?search=q`，是 SQL **子串匹配**（`WHERE LOWER(text) LIKE LOWER(%q%)`），并非语义搜索。像 `"Validate the loopline performance model"` 这类自然语言查询不会与 `RESULT SUMMARY metrics=[...]` 这类结构化条目子串匹配，因此生产中即便有 84 条有效 passage，`search_memory` 也只返回 0 条。本技能改为调用 `passages.search`（`GET /archival-memory/search`，`embed_query=True`），以 `top_k = max(letta_overfetch, limit*40)` 拉取，再在本地按 `ancestor_ids` / `ari_checkpoint` / `kind == "node_scope"` 做 post-filter。`add_memory` 插入时已支付的 embedding 成本现在能在检索中真正被使用；子节点会按其 `eval_summary` 查询的 **语义相关度** 顺序看到祖先条目。

#### `get_node_memory(node_id)`

按时间顺序返回特定节点的所有条目（无评分）。

#### `clear_node_memory(node_id)`

仅用于调试的单节点清除。与 `add_memory` 使用相同的 CoW 规则。

#### `get_experiment_context()`

返回 Letta 核心记忆中种入的稳定事实（`experiment_goal`、`primary_metric`、`hardware_spec` 等）。种入仅在首个节点的 `generate_ideas` 完成时（即 `primary_metric` 被确定的时刻）执行一次，在此之前调用会返回 `{}`。之后可安全反复调用（带 60 秒进程内缓存）。

#### 类型化的可验证研究记忆工具

类型化条目（Phase 1）携带结构化来源信息，使论文 / 图表阶段能够将声明接地到可复现的产物上。
调用方是 loop/pipeline 钩子，而非 LLM 拉取。每个写入工具都受 **Copy-on-Write 保护**：`node_id`
必须等于 `$ARI_CURRENT_NODE_ID`（ari-core MCPClient 通过 `_set_current_node` 桥接路由写入），
因此子节点无法改动祖先的条目。

#### `add_experiment_result(node_id, text, metric_ptr=None, artifact_refs=None, node_report_ref=None)`

记录一条类型化的 `experiment_result`（CoW：仅自身节点）。

#### `add_failure_case(node_id, text, artifact_refs=None, node_report_ref=None)`

记录一条类型化的 `failure_case`（CoW：仅自身节点）。

#### `add_procedure_memory(node_id, text, node_report_ref=None)`

记录一条可复用的流程（CoW：仅自身节点）。

#### `add_reflection(node_id, text, confidence=None, node_report_ref=None)`

记录一条反思（CoW：仅自身节点）。不可用于论文声明。

#### `add_reproducibility_event(node_id, target_memory_id, status, artifact_refs=None, text=None)`

针对一条已有条目追加一个仅追加的可复现性状态事件（CoW：仅自身节点）。

#### `search_research_memory(query, ancestor_ids, kinds=None, require_artifacts=False, limit=5)`

祖先作用域的类型化搜索，按 `kind` / 产物有无过滤。兄弟与子节点永远不会返回。

#### `get_verified_context(ancestor_ids, purpose="paper", limit=None)`

供论文 / 图表使用的、产物支撑且可复现性感知的上下文。

#### `audit_memory(experiments_root, run_id=None)`

将记录的来源（sha256）与检查点磁盘上的内容核对验证。返回 `{summary, results}`。

#### `consolidate_node_memory(node_id, node_report, work_dir, run_id=None)`

在节点结束时通过类型化写入器从 `node_report` 导出并写入类型化记忆（`experiment_result` /
`failure_case` / `reflection`）（CoW：仅自身节点）。调用方是 ari-core 的节点结束钩子。

存储：每个检查点拥有一个 Letta 代理（两个集合 `ari_node_*` 与 `ari_react_*`）。可移植快照位于 `{ARI_CHECKPOINT_DIR}/memory_backup.jsonl.gz`，写/读遥测位于 `{ARI_CHECKPOINT_DIR}/memory_access.jsonl`。v0.5.x 的 JSONL 存储（检查点级 `memory_store.jsonl` 以及曾经位于 `$HOME/.ari/` 下的遗留全局 JSONL）已在 v0.5.0 移除；使用 `ari memory migrate --react` 迁移。跨实验“全局记忆”已弃用。

---

## ari-skill-orchestrator

将 ARI 作为 MCP 服务器暴露给外部智能体和 IDE，支持递归子实验。**LLM：否**（委托给 ARI CLI）。

双传输：**stdio**（用于 Claude Desktop / 其他 MCP 客户端）+ **HTTP**（REST + SSE，`ARI_ORCHESTRATOR_PORT`，默认 9890）。

### 工具

#### `run_experiment(experiment_md, max_nodes=10, model="", max_recursion_depth=3, parent_run_id="", llm_backend="", llm_api_key="", llm_base_url="", executor="", cpus=0, timeout_minutes=0, retrieval_backend="")`

异步启动 ARI 实验。返回 `run_id`。当设置 `parent_run_id` 时，该实验将作为父实验的子项被追踪（用于递归子实验工作流）。

#### `get_status(run_id)`

返回运行的进度、当前最佳指标和递归元数据。

#### `list_runs()`

列出所有过去的实验运行。

#### `list_children(run_id)`

返回父实验的子运行列表（用于递归子实验追踪）。

#### `get_paper(run_id)`

返回生成的论文（LaTeX）。

工作空间：`ARI_WORKSPACE` 环境变量（默认：`~/ARI`）。父子关系保存在每个检查点的 `meta.json` 中。

---

## ari-skill-transform

将 BFTS 内部表示转换为面向出版的科学数据格式。剥离所有内部字段（`node_id`、`label`、`depth`、`parent_id`），仅暴露科学内容（`configurations`、`experiment_context`）。**LLM：是**。

### 工具

#### `nodes_to_science_data(nodes_json_path, llm_model="", llm_base_url="", primary_metric="", higher_is_better="true")`

LLM 分析完整的 BFTS 树，提取硬件规格、方法论、关键发现和比较结果。`primary_metric` 和 `higher_is_better` 由 pipeline 从 `evaluation_criteria.json` 通过 `tpl_vars` 传入，用于 `summary_stats` 的方向感知归约（v0.7.0+）。

返回（v0.7.0+）：

```text
configurations[*]:
  rank, label, eval_summary
  parameters / measurements / predictions / scores  ← 类型化分离
                                                       (D: results.json 或
                                                        C: _params_dict)
  metrics                                            ← 兼容性 flat union
  _typed_source: "results.json" | "llm_evaluator" | (无)
  _provenance  ← 该节点 results*.json 各变体中
                  emit_results 的 _provenance 的并集（存在时）
per_key_summary  (输入参数键 & 「_…」保留键被排除)
summary_stats    { count, primary_metric, direction,
                   primary_metric_best, primary_metric_n,
                   typed_split_coverage }
experiment_context, implementation_overview, report_driven
```

**类型化分离的来源优先级**（D > C > legacy）：

1. `experiments/{run_id}/{node_id}/results.json` — 由 `coding-skill::emit_results` 写入（D 契约）
2. `node.metrics::_params_dict` / `_measurements_dict` — LLM evaluator 在 `MetricSpec.expected_params` 设置下输出（C 契约）
3. 旧路径：`parameters: {}`，扁平 `metrics` 容纳所有内容

它还会读回 `{checkpoint}/metric_contract.json`（由 `evaluator-skill::make_metric_spec` 写在 `tree.json`
旁边）并将其 graft 到 `science_data.metric_contract`，以便确定性的硬门强制执行声明的契约（claims /
correctness / `required_measured` / 声明的 invariant）——若没有此 graft，声明的契约就是 inert 的，
只有 universal invariant 注册表能到达硬门。

**鲁棒性**：LLM 响应解析器剥离 `<think>` 块和 ` ```json ` 围栏，然后从每个候选 `{` 走匹配大括号，按长度降序尝试 `json.loads`。可以救援 `{...} prose {...}` 类型的形状。失败时将原始响应保存到 `{checkpoint_dir}/science_data.debug.txt` 以便事后审计。

模型：`llm_model` 参数 > `LLM_MODEL` 环境变量 > `gpt-4o-mini`。

**存在意义：** 确保 BFTS 内部术语不会泄漏到生成的论文或图表中，并保证输入尺寸描述符（`nnz`、`M`、`K`）不会在 best-of 归约中与测量输出（`GFlops_per_s`、accuracy）混淆。

#### `generate_ear(checkpoint_dir, llm_model="", llm_base_url="")`

在 `<checkpoint>/ear/` 下构建用于可重现性的 **Experiment Artifact Repository (EAR)**。采用 node_report 驱动的布局，与论文配套代码仓库一致：

- `README.md` — 确定性渲染；当 `science_data.json::implementation_overview.architecture` 存在时附带 `Architecture` 段
- `reproduce.sh` — 直接插入 best 节点 `node_report.json::{build_command, run_command}` 的 literal
- `environment.json` — 捕获的运行时环境（Python、平台、pip、硬件）
- `code/` — best 链中 contributing 节点的 `files_changed.added` ∪ `modified` 联合 verbatim 放置（不再有 `code/<node_id>/`）
- `data/` — `checkpoint/uploads/` 的 verbatim 镜像（**仅输入数据**，空则不存在）。**实验输出不打包**——由 `reproduce.sh` 再生成
- `figures/` — checkpoint 根下的 `*.{pdf,png,svg,jpg,jpeg}` 直接置于顶层
- `LICENSE` — 由 `publish.yaml::license` 生成（MIT / Apache-2.0 / BSD-3-Clause / GPL-3.0 / CC-BY-4.0）

两份 ARI 审计日志放在 `<checkpoint>/` 根目录下（位于 `ear/` 之外，因此**不会**被打包进发布产物）：

- `EVOLUTION.md` — Step / Label 形式的搜索轨迹（含 delta 与 concerns）；不出现 `node_id` 等不透明内部标识
- `_provenance.json` — 来源元数据（`from_node_id`、`introduced_by`、`excluded_nodes`）；其内部路径相对于 checkpoint（`ear/code/...`）

其他 ARI 内部元数据（`tree.json`、`science_data.json`、`raw_metrics.json`、`eval_scores.json`、`commands.md`）同样保留在 checkpoint 根目录，不进入 `ear/`。`run_config.json` 移至 `checkpoint/run_config.json`。

返回：`{ear_dir, code_layout, verbatim_files, rendered_files, data_count, figure_count, top_node_id, best_chain_depth, excluded_count, has_readme, has_evolution, has_reproduce_sh, has_license, has_environment, ...}`。

#### `curate_ear(checkpoint_dir)` — v0.7.0

依据 `{checkpoint}/ear/publish.yaml` 的 allowlist 与内置 deny list（`.env*`、`secrets/**`、`*.pem`、`*.key`、`id_rsa`、`id_ed25519`），将 `{checkpoint}/ear/` 策展为 `{checkpoint}/ear_published/`。在 `manifest.lock` 中写入正规化的 `bundle_sha256`（按 `{path, sha256, size}` 排序后 JSON 的 sha256），这就是论文 `\codedigest{...}` 宏所要烧录的 digest。**确定性、无 LLM**。`publish.yaml` 缺失时静默跳过（保持 v0.6.0 checkpoint 后向兼容）。

#### `publish_ear(checkpoint_dir, backend="ari-registry", visibility="staged", dry_run=False)` — v0.7.0

`ari.publish.publish` 的 MCP 薄包装。从 `ear_published/` 构建可复现 tarball（条目排序、mtime/uid/gid 归一化），交由后端（`ari-registry` / `gh` / `zenodo` / `local-tarball`）发布，并将 `publish_record.json` 写入 checkpoint 根目录。首发布始终为 `visibility=staged`（FR-P5）；只有 `auto_promote=true` 且可复现性检查通过时才能晋升为 public。

`ARI_PUBLISH_DRYRUN=1` 强制 dry-run（CI 安全开关）。

#### `promote_ear(checkpoint_dir, target="public")` — v0.7.0

将先前已发布的 EAR 产物晋升到更宽的可见性层级。`ari.publish.promote` 的 MCP 薄包装。
**确定性、无 LLM**。返回 `{ref, visibility, promoted_at, promote_failed_at}`（或在
`PublishError` 时返回 `{error, kind}`）。

#### LICENSE 模板 — v0.7.0

当 `publish.yaml::license` 已设定且作者未自带 `ear/LICENSE` 时，`generate_ear` 会从 `ari-skill-transform/src/licenses/` 写入 **MIT** / **Apache-2.0** / **BSD-3-Clause** / **GPL-3.0** / **CC-BY-4.0** 之一。

---

## ari-skill-web

可插拔检索后端的网络搜索和学术文献检索。**LLM：部分**（仅 `collect_references_iterative` 使用 LLM）。

### 工具

#### `web_search(query, n=5)`

DuckDuckGo 网络搜索。无需 API 密钥。确定性。

#### `fetch_url(url, max_chars=8000)`

通过 BeautifulSoup 获取并提取 URL 中的文本。确定性。

#### `search_arxiv(query, max_results=5)`

arXiv 论文搜索。确定性。

#### `search_semantic_scholar(query, limit=8, extra_queries=None)`

Semantic Scholar API，回退到 arXiv。确定性。

#### `search_papers(query, max_results=10)`

调度到所配置的检索后端（`ARI_RETRIEVAL_BACKEND`）：
- `"semantic_scholar"`（默认）— Semantic Scholar API
- `"alphaxiv"` — 通过 HTTP 上的 MCP JSON-RPC 调用 AlphaXiv
- `"both"` — 并行执行并去重

#### `set_retrieval_backend(backend)`

在运行时动态切换检索后端。有效值：`"semantic_scholar"`、`"alphaxiv"`、`"both"`。

#### `collect_references_iterative(experiment_summary, keywords, max_rounds=20, min_papers=10)`

AI Scientist v2 风格的迭代式引用收集。LLM 生成搜索查询并在多轮中选择相关论文。

模型：`ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > `ollama_chat/qwen3:32b`。

#### `list_uploaded_files()`

列出检查点目录中用户上传的文件。确定性。

#### `read_uploaded_file(filename, max_chars=50000)`

从上传文件读取文本内容（带二进制检测）。确定性。

---

## ari-skill-coding

代码生成、执行和文件读取。**LLM：否**（确定性）。

### 工具

#### `write_code(filename, code, work_dir="/workspace")`

将源文件写入工作目录。

#### `run_code(filename, work_dir="/workspace", timeout=600)`

用扩展名选定的解释器执行源文件（`.py` → `python3`、`.sh` → `bash`、`.js` → `node`、`.rb` → `ruby`、`.pl` → `perl`、`.lua` → `lua`）。它**不**编译，因此 C/C++/Fortran/Rust/Go 需走 `run_bash`。内联的 `stdout`/`stderr` 是有界预览（分别 4,000 与 2,000 字符），截断标记会给出省略的字符数并说明完整日志是一个 artifact；完整字节流始终以带 SHA-256 digest 的 content-addressed artifact 写出。

#### `run_bash(command, work_dir="/workspace", timeout=600)`

在工作目录中运行 bash 命令。预览与完整日志的处理同 `run_code`，结果中带有 `truncated` 布尔标志。

#### `read_file(path, offset=0, limit=8000, work_dir="/workspace")`

针对大文件支持分页读取文本。`offset` 与 `limit` 是**字符**偏移而非行号。返回内容、用于继续的 `next_offset`（读到末尾为 `null`）与总字符数。

```python
result = read_file("results.csv", offset=0, limit=100)
# 返回值: {"path": "...", "content": "...", "offset": 0, "returned_chars": 100,
#          "total_chars": 5000, "truncated": True, "next_offset": 100}
```

工作目录：workspace 根目录由 `ARI_WORK_DIR`（默认 `/tmp/ari_work`）固定。`work_dir` 参数并不替换该根目录，而是选定其**下**的一个目录并按需创建；解析后落在根目录之外的路径会被拒绝而不是被改写。智能体看到的根目录是固定的容器路径 `/workspace`，文件类工具在真正访问前把它映射回真实目录，并从每个结果中抹掉真实路径。

#### `emit_results(params, measurements, predictions={}, scores={}, provenance={}, units={}, execution=None, file="results.json", work_dir="/workspace")`

写出一份将输入参数与测量输出分离的类型化 `results.json`，使下游（`transform → science_data`、论文撰写、summary stats）不会把「测量到的量」与「运行所用的条件」混淆，避免 best-of 归约把输入尺寸（`nnz`、`M`、`K`、`threads`）误选为真实指标（如 `GFlops_per_s`）。`params` 与 `measurements` 必须 disjoint。

文件形如 `{"schema_version": "1.0", "typed_schema_version": "ari.measurement-set/v1", "measurement_set": {...}}`，只包含规范的 `MeasurementSetV1` 对象，旁边不再写平铺投影（见[执行与测量契约](execution_contract.md)）。每个分组都必须是 finite JSON：不可序列化的值（如 `pathlib.Path`）、`NaN`/`Infinity`、以及非数值的 measurement 都会被拒绝并返回 `error`，而不是被强制转换。

可选的 `units` 参数是 `{measurement: unit}` 映射；未声明单位的 measurement 记为 `unit_status: "missing"`，单位从不推断。可选的 `execution` 参数是从上一次 `run_code`/`run_bash` 响应中原样复制的 `measurement_execution` 块（execution identity/attempt、status、exit code、artifact digest 以及服务端签发的 receipt）；不提供时 measurement 会被标记为 `execution_status: "unreported"`，并且不具备 scientifically admissible 资格。`units` 或 `provenance` 中出现 `measurements` 里没有的名字会被拒绝。

可选的 `provenance` 参数是一个 `{operand: source}` 映射，记录在对应的规范 measurement 记录上，由 claim/指标正确性门消费。当某个操作数的值是经验**测量**得到的上限/峰值时，标注 `"microbench"` 或 `"benchmark"`（以免归一化指标被判定为依赖占位值）；当它是相对于**独立**参考计算出的残差时，标注 `"correctness"` 或 `"reference"`（以免输出被判定为未经验证）。尽力而为，为空时完全省略。

---

## ari-skill-benchmark

性能分析、绘图和统计检验。**LLM：否**（确定性）。

### 工具

#### `analyze_results(result_path, metrics)`

加载并分析 CSV、JSON 或 NPY 结果文件。返回汇总统计信息。

#### `plot(data, plot_type, output_path, title="", xlabel="", ylabel="")`

生成 matplotlib 图表。图表类型：`bar`、`line`、`scatter`、`heatmap`。

#### `statistical_test(data_a, data_b, test)`

运行 scipy 统计检验：`ttest`、`mannwhitney`、`wilcoxon`。

---

## ari-skill-plot

科学论文图表生成器。两种模式：**确定性模式**（`generate_figures`，P2-safe 的 matplotlib + 固定 schema）与 **LLM 模式**（`generate_figures_llm`，AI-Scientist-v2 风格让 LLM 写代码并执行，可选 VLM 添加图注）。**LLM：混合**（确定性 + P2 例外）。

### 工具

#### `generate_figures(nodes_json_path, output_dir, figures=None, science_data_path="", vlm_captions=True, experiment_context="")`

从 `nodes_tree.json` 渲染规范化对比图到 `output_dir`。返回每个生成图的清单（含 caption 与源节点 id）。给定 matplotlib 版本下字节确定。

#### `generate_figures_llm(nodes_json_path, output_dir, experiment_summary="", context="", n_figures=3, science_data_path="", vlm_feedback="")`

LLM 检视数据形状与自然语言 `intent`，编写 matplotlib 代码，在与确定性模式相同的 `_run_plot_code` 沙箱中执行，并（可选地）调用 VLM 为生成的图添加 caption。P2 例外。

`kind="plot"` 的系统提示现在会强制一条 **LAYOUT** 规则（调用 `fig.tight_layout()` 并以 `bbox_inches='tight'` 保存、把图例放在坐标轴之外、旋转过长的刻度标签；文字重叠或被截断的图会被 **REJECTED**）以及一条 **COMPARABILITY** 规则（不要在没有明确坐标轴或注释的情况下，把不同尺度/不同区间测得的值并置）。这些是给编写图表的 LLM 的提示级指引，不会新增机械式门。

### 环境变量

| 变量 | 用途 | 默认 |
|---|---|---|
| `VLM_MODEL` | 用于图注生成的 Vision LLM | `openai/gpt-4o` |
| `ARI_LLM_MODEL` | `_llm` 模式中编写 matplotlib 代码的 LLM | （无 — `_llm` 必需）|
| `LLM_MODEL` | 跨技能回退 | （无）|
| `ARI_LLM_API_BASE` | LiteLLM API base 覆盖 | LiteLLM 默认 |
| `OPENAI_API_KEY` | 使用 OpenAI 系模型时所需 | （无）|

### ari-core 边界

`src/server.py` 中 `from ari import cost_tracker`；Phase 4 重构将其迁移到 `ari.public.cost_tracker`。

---

## ari-skill-vlm

视觉语言模型，用于图表和表格质量审查。**LLM：是**（VLM）。

### 工具

#### `review_figure(image_path, context="", criteria=None)`

VLM 审查实验图表。返回评分（0-1）、问题和建议。

#### `review_table(latex_or_path, context="")`

VLM 审查表格（LaTeX 源码或渲染图像）。返回评分、问题和建议。

模型：`VLM_MODEL` 环境变量 > `openai/gpt-4o`。

---

## 编写新技能

1. 创建 `ari-skill-yourskill/src/server.py`：

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("your-skill")

@mcp.tool()
def your_tool(param: str) -> dict:
    """Tool description."""
    # NO LLM calls here
    return {"result": process(param)}

if __name__ == "__main__":
    mcp.run()
```

2. 在 `ari-core/config/workflow.yaml` 中注册。`phase` 控制
   各 pipeline-phase 的 ReAct 智能体是否能看到该技能（单个 phase
   写字符串，多个 phase 写数组）：

```yaml
skills:
  - name: your-skill
    path: '{{ari_root}}/ari-skill-yourskill'
    phase: [paper, reproduce]
```

   有效 phase 值：`bfts`、`paper`、`reproduce`、`all`、`none`。

3. 在 `experiment.md` 的 `## Required Workflow` 中引用工具名称。
