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

技能是为 ARI 智能体提供工具的 MCP 服务器。工具尽可能保持确定性；使用 LLM 的工具会明确标注。本页覆盖 **14 个技能**——`ari-core/config/workflow.yaml` 的 `skills:` 默认注册的 13 个，加上作为独立进程为外部客户端启动的 `ari-skill-orchestrator`。不在默认 `skills:` 列表中的 `ari-skill-knowledge` / `ari-skill-harness` / `ari-skill-tool-registry` 请参见 [mcp_tools.md](mcp_tools.md) 与 [tool_registry.md](tool_registry.md)。v0.7.0 新增 `ari-skill-replicate`，用于 PaperBench 形式的可复现性流程。

## ari-skill-hpc

typed 的 SLURM 生命周期、严格的 SSH transport、能力探测，以及 digest 钉定的容器。
**LLM：否**（完全确定性）。

十个工具分三组：两个 typed 提交器（`job_submit`、`container_submit`）与保留下来的
批处理脚本兼容桥（`slurm_submit`）；四个共用同一份句柄选择器的生命周期操作
（`job_status`、`job_result`、`job_logs`、`job_cancel`）；以及三个探测器
（`probe_platform_capabilities`、`counter_support`、`measure_counters`）。是否以容器
运行由请求所携带的 digest 钉定 `ContainerRequestV1` 决定，而不取决于选用哪个工具：
`container_submit` 只是把该字段设为必填的同一次提交，而声明了完全相同输入 schema 的
`job_submit` 同样接受带容器声明的请求并走完全相同的路径执行，只是不强制要求。本包
不提供任何镜像的构建、拉取或运行命令。

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
`slurm_submit` 同名的 `launcher`（`auto` / `srun` / `none`，默认 `auto`）；
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
| `auto`（默认） | 完全按写法原样启动 | 脚本自己调用 `srun` / `mpirun`，或本身是串行的 |
| `srun` | 按声明的 `nodes` / `tasks` / `cpus_per_task`（若已声明还包括 `--ntasks-per-node`）以 `srun` 启动 `bash -c <script>` | 脚本本身就是并行程序（MPI / SPMD） |
| `none` | 完全按写法原样启动 | 负载必须看到未经改动的批处理步骤 |

因此在这里 `auto` 与 `none` 抵达节点的方式完全一致：bridge 的主体是一段脚本，
只有 `srun` 会对它加包装。`auto` 所做的 CPU 绑定属于 typed 的 `job_submit` /
`container_submit` 路径——那里的负载是 `argv`，单节点单任务的请求会以
`srun --ntasks=1 --cpus-per-task=N` 启动。之所以要这样绑定，是因为批处理步骤会
继承整个节点的 affinity mask：否则多线程负载会散布到整台机器上，甚至可能输给
它自己的串行基线，读起来像是 kernel 慢，而不是 allocation 未绑定。

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
遗留兼容）二选一。“恰好一个”写在 schema 的 description 里，由服务端的 `_selector`
强制执行，**并非**顶层 `oneOf`：OpenAI 的 function-calling schema 子集会拒绝带
`oneOf` 的工具，那会让这四个工具都无法被 advertise。两个都不给会被拒绝；实现优先读
`handle_id`，所以两个都给时按句柄解析。
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

#### `survey(topic, max_papers=8, mode="record", snapshot_path="survey_snapshot_v1.json", provider="semantic-scholar")`

先前工作调研。确定性（无 LLM）。provider 是**钉住的，不是链式回退的**：
`provider` 只接受 `semantic-scholar` 和 `virsci-snapshot`，其它取值一律
raise，因此 `record` / `live` 调用不会在故障中途切换后端，语料库也不会悄悄
变成另一份。`virsci-snapshot`（或 `mode="frozen"`）在冻结语料库缺失时抛出
`FileNotFoundError`，不会退回网络；Semantic Scholar 遇到 HTTP 错误时直接
抛出，不会退到别的 provider。**没有 arXiv 回退**。`mode` 为 `record` /
`live` / `replay` / `frozen`，其中 `replay` 完全不访问网络，且当
`snapshot_path` 指向的 checkpoint artifact 缺失或摘要校验不通过时失败。
Semantic Scholar 路径只对前 3 条结果各取至多 3 篇被引论文做一跳扩充，并且
只保留留存记录之间的边。返回 `papers`（旧版投影）、`survey_snapshot`
（`SurveySnapshotV1`）、`survey_snapshot_digest` 和 `execution_mode`。

```python
result = survey("OpenMP compiler optimization HPC benchmarks")
# Returns: {"papers": [{"title": "...", "abstract": "...", "url": "..."}]}
```

设置 `S2_API_KEY` 可获得更高的 Semantic Scholar 速率限制。`max_papers`
上限为 15。

该技能已注册的 MCP 工具是 `survey`、`generate_ideas` 与
`mint_contract_for_proposal` 三个 —— `mcp.json` 也恰好只列这三个；
`_load_virsci_snapshot_papers` 只是 `survey` 直接调用的普通辅助函数，绝不
能对 agent 可见。`tests/test_server.py` 通过 `mcp.list_tools()` 钉住
`survey` / `generate_ideas` 的注册以及该辅助函数不是工具这一点
（`@mcp.tool()` 装饰器丢失/错位的问题曾经上线过）。

#### `generate_ideas(topic, papers, experiment_context="", n_ideas=3, n_agents=4, max_discussion_rounds=2, max_recursion_depth=0, survey_snapshot=None, survey_snapshot_ref="", seed=None, generation_mode="auto")`

使用 VirSci 多智能体 LLM 讨论生成研究假设。多个 AI 角色（研究者、批评者、专家、综合者）就研究问题进行辩论。在默认的 `simple_bfts` 模式下，仅在 BFTS 启动前调用**一次**（仅限 pre-BFTS）。在可选启用的 `ari_rqgm` 模式下且 `proposal_router.generators.virsci.enabled: true` 时，core 侧的 `VirSciAdapter` 会额外通过 ProposalRouter 的事件触发、预算封顶的调度调用 `survey` + `generate_ideas` —— 见 [VirSci 集成](../guides/virsci_integration.md)。

模型：`ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > `ollama_chat/qwen3:32b`。

文献输入在第一次模型调用之前就被冻结。可以传入 `survey` 返回的那份
`SurveySnapshotV1` 对象本身（`survey_snapshot`）、指向已验证快照的
checkpoint 相对引用（`survey_snapshot_ref`，需要 `ARI_CHECKPOINT_DIR`，且不
可与内联文献同时给出，否则 raise），或旧版的内联 `papers` 列表。三者都为空
时，只会执行一次钉住的 Semantic Scholar record 操作，不会回退到别的
provider。`seed` 记录进 generation lock。`generation_mode` 为 `auto` /
`default` / `virsci`，其它取值 raise，且显式的 `virsci` 是 fail closed，不会
降级回再实现循环。`n_ideas` 被夹到 1–5，`n_agents` 夹到 2–4，
`max_discussion_rounds` 夹到 0–3，`max_recursion_depth` 是为递归编排预留的
（目前未使用）。

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

指标契约的物化，以及声明 / 证据门。**LLM：部分**（`propose_metric_contract` 与
`evidence_grounded_semantic_review` 调用 LLM；`make_metric_spec` 与
`claim_evidence_hard_gate` 完全确定性）。

### 工具

#### `make_metric_spec(experiment_text, checkpoint_dir="", proposal_json=None, reviewer="")`

确定性地把**一份**不可变契约物化成 MetricSpec。**无 LLM**。解析顺序：

1. 想法所有的 `ResearchContractV1`（`idea.json`）——其 `metric_contract` 的
   `admission_status` 不是 `admitted` 时直接报错；
2. 传入的 `proposal_json`——只有同时给出 `reviewer` 才会被准入并写下准入决定，
   否则原样返回 `admission_status: "human-review-required"`；
3. 已持久化的 `{checkpoint}/metric_contract.json`（旧 schema 走迁移读取器）。

三者都没有时，工具只把确定性 parser 的结果作为**证据**返回，并附
`metric_contract: null` / `contract_frozen: false` /
`proposal_tool: "propose_metric_contract"` —— parser 的输出永远不会被自动提升为
科学契约。

```python
result = make_metric_spec(open("experiment.md").read(), checkpoint_dir=ckpt)
# Returns: {
#   "metric_keyword": "MFLOPS",
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "...",
#   "metric_contract": {...}, "metric_contract_digest": "...",
#   "contract_frozen": True, "contract_source": "idea.research-contract/v1",
#   "admission_status": "admitted"
# }
```

契约由想法所有，因此智能体无法删除某个 claim 或要求来规避检查；投影会持久化到
`{checkpoint}/metric_contract.json`（位于 `idea.json` / `tree.json` 旁边），由
`transform-skill::nodes_to_science_data` 读回并 graft 到
`science_data.metric_contract`，再由确定性的硬门强制执行。

#### `propose_metric_contract(idea_json=None, checkpoint_dir="", model="", model_revision="")`

显式的 LLM 提案步骤——把「猜一份契约」这件事从 `make_metric_spec` 里分了出来，
使它绝不会在物化路径上悄悄发生。**LLM：是**。读取 `idea_json`（省略时取
`{checkpoint_dir}/idea.json`），产出一份带
`source_idea_digest` / `evidence_digest` / `prompt_digest` / `confidence` 的
`MetricContractProposalV1`，写到 `{checkpoint}/metric_contract_proposal.json`。

输出**始终**带 `requires_human_review: true`：它必须再经 `make_metric_spec` 携
`reviewer` 准入才能成为契约。想法已经拥有 typed 契约
（`typed_schema_version: "ari.research-contract/v1"`）时调用会被拒绝。

模型：`model` 参数 > `ARI_MODEL_METRIC_PROPOSAL` 环境变量 > `ARI_LLM_MODEL` 环境变量 >
`gpt-4o-mini`。

#### `claim_evidence_hard_gate(checkpoint_dir, paper_path, science_data_json="", paper_claim_links_path="", figures_manifest_json="", policy=None, phase="draft")`

确定性的声明/证据硬门（执行数据保真度）。**无 LLM**。验证 science_data 声明所引用的节点确已执行，从 `results.json` 重新计算 `numeric_assertions` 并在容差内核对论文报告的数值，按章节策略检测未覆盖的结果数值，并检查图表是否存在。它是 ari-core `run_hard_gate`（`ari.public.claim_gate`）之上的 MCP 薄包装。在 strict 模式下，当存在阻塞性错误时 `final` 阶段返回 `{"error": ...}`，使阶段运行器抛出异常并跳过 `finalize_paper`；`draft` 阶段以及 warn/off 模式从不阻塞。写出 `evaluation/claim_evidence_hard_gate_{phase}.json`。

#### `evidence_grounded_semantic_review(checkpoint_dir, paper_path, science_data_json="", hard_gate_path="", paper_claim_links_path="", phase="initial", model="", model_revision="")`

非阻塞的、以证据为基础的语义评审。**LLM：是**。LLM 基于硬门证据检测过度声明 / 解释性问题 / 未注册的强声明，而**不**触碰独立的文本审稿人；它不重新核对数值。输出供 `paper_refine` 消费的 `suggested_revisions` 以及评分。写出 `evaluation/evidence_grounded_semantic_review.json`。从不阻塞。必填参数只有 `checkpoint_dir` 和 `paper_path`。`model` 为本次调用钉住评审模型（未指定时为 `ARI_MODEL_SEMANTIC_REVIEW` > `ARI_LLM_MODEL` > `gpt-4o-mini`），`model_revision` 记录跑的是哪个 revision；两者连同 prompt / evidence / 硬门摘要一起写进报告，使每次评审都可归属到确切的模型 identity。

---

## ari-skill-paper

LaTeX 论文生成、编译和审阅（仅限 Post-BFTS）。**LLM：是**。

### 工具

#### `list_venues()`

返回可用的场所配置。

支持的场所：`neurips`（9 页）、`icpp`（10 页）、`sc`（12 页）、`isc`（12 页）、`arxiv`（无限制）、`acm`（10 页）。

#### `get_template(venue)`

返回指定场所的 LaTeX 模板。

#### `compile_paper(tex_dir, main_file="main.tex", figures_manifest_path="")`

运行 pdflatex 编译。返回成功状态和错误信息。

#### `check_format(venue, pdf_path)`

根据场所要求验证论文格式（页数等）。

#### `finalize_paper_build(workspace_root, draft_build_path, tex_path, bib_path, pdf_path, compile_record_path, figures_manifest_path, claim_links_path, hard_gate_path, text_review_path, visual_review_path, semantic_review_path, refinement_call_path="", visual_passing_score=0.7, output_path="paper_build.json")`

fail-closed 地把一次论文 build 封口。**确定性、无 LLM**。它把确切的证据——
tex / bib / pdf、编译记录、图表清单、claim 链接、claim 硬门，以及文本 / 视觉 /
语义三份评审——锁进一份 `PaperBuildV1` 并写到 `output_path`。所有输入都是封闭
workspace 下的相对路径。

产物照常记录，但 `status` 不是 `finalized` 时调用**抛错**，并把
`blocking_reasons` 带回来：finalize 是一道结论性的门，而不是一次汇总。

#### `write_paper_iterative(workspace_root, science_data_path, figures_manifest_path, references_path, ear_manifest_path, rubric_id, experiment_summary="", context="", verified_context_path="", venue="arxiv", max_revision_rounds=2, author_name="", writer_prompt_override="", decode_seed=0)`

完整论文生成。主要流水线工具，全部输入都以封闭 workspace 下的产物路径给出。
先由一次 LLM 调用填满模板里所有 `FILL_*_START … FILL_*_END` 占位块，再进行
`max_revision_rounds` 轮保留对话历史的反思（自我批评）修订，每轮之后编译。
起草、评审与改写都是本工具**内部**的步骤，没有对应的单章节 MCP 工具；成稿后的
修订走 `paper_refine`，成稿后的评审走 `review_compiled_paper`。

`writer_prompt_override` 与 `decode_seed` 是后加的接缝，它们的默认值是冻结的
兼容契约，而不是推荐配置：`""` 与 `0` 必须逐字节复现这两个参数存在之前的工具行为
（`paper_refine` 取同一对参数、同样的默认值）。

`writer_prompt_override=""` 加载内置的 `paper_writer.md`；非空值会把反思阶段的
system 提示词**整个替换**掉。首次填充模板的调用无论如何都使用它自己的
`fill_in_writer` 提示词，因此 override 只到达反思循环。它是一段纯指令字符串而非
治理机制 —— `tests/test_writer_prompt_override.py` 断言：默认的反思提示词恰好是
加载到的 `paper_writer.md` 加语言指令；非空 override 下该次调用里不再残留
`paper_writer.md` 的正文；以及 import 这个技能不会拖进任何 `ari.rqgm` 模块。

`decode_seed=0` 完全不向 payload 写入 `seed` 键，保持 linear（无 seed）行为。非 0
时它会被传给 litellm——首次写作调用和每一轮反思调用都会带上——使需要生成一**批**
草稿的调用方拿到不同样本而不是 K 份副本；litellm 的 `seed` 是尽力而为且依赖供应商
的，它给的是多样性，不是 bit-exact 重放。这个参数之所以存在，是因为反方向的失败：
按 `tests/test_server.py::test_a_non_zero_decode_seed_reaches_the_payload` 的回归
注记，调用方记录了一个 payload 从未携带的 seed，正是这一点「让 8 个 seed 塌成了
1 份草稿」。被记录的 seed 只有真正进入 payload 才有意义。本工具的 seed 走线没有
对应的技能测试；payload 层面的断言在下文的 `paper_refine` 上。

#### `review_compiled_paper(rubric_id, tex_path="", pdf_path="", figures_manifest_json="", experiment_summary="", vlm_findings_json="", num_reflections=None, num_fs_examples=None, num_reviews_ensemble=None)`

**AI Scientist v1/v2 兼容** 的基于评审规范的论文审阅（遵循 Nature /
arXiv:2408.06292 附录 A.4）。从 `ari-core/config/reviewer_rubrics/<rubric_id>.yaml`
加载评审规范，根据 `score_dimensions` / `text_sections` / `decision` 动态生成
提示。VLM 的逐图反馈（分数 / 问题 / 建议）作为审稿人备注注入，并附加
Few-shot 示例，经 Self-reflection 循环自我批评修订后输出符合评审规范的 JSON。

已内置评审规范（`ari-core/config/reviewer_rubrics/` 下 23 个 YAML）：

| 类别 | rubric_id |
|---|---|
| ML 会议 | `neurips`（默认，v2 兼容）/ `iclr` / `icml` / `cvpr` / `acl` |
| 系统 / HPC | `sc` / `osdi` / `usenix_security` |
| 理论 / 图形学 | `stoc` / `siggraph` |
| HCI / 机器人 | `chi` / `icra` |
| 经济学 / 人文期刊 | `aer` / `qje` / `econometrica` / `apsr` / `ahr` / `pmla` / `philreview` |
| 期刊 / 通用 | `nature` / `journal_generic` / `workshop` / `generic_conference` |

在 `reviewer_rubrics/` 目录放一份 YAML 即可扩展新的会议，无需修改代码。
每个评审规范声明 `score_dimensions` / `text_sections` / `decision` 规则、
执行参数及用于 P2 确定性的 SHA256 哈希。

评审规范解析：`rubric_id` 是第一个且必填的参数，没有环境变量回退、没有默认
venue、也没有内置 `legacy` 回退——`resolve_rubric` 对空值直接拒绝
（`rubric_id is required; migrate legacy ARI_RUBRIC/default config to an
explicit workflow input`）。被搜索的只是「读哪个 YAML」：依次为
`ARI_RUBRIC_DIR` → `./ari-core/config/reviewer_rubrics/` →
`./config/reviewer_rubrics/` → 仓库根下的同名目录，先命中者胜。因此某篇论文
是被哪份评审规范打分的，永远记录在发起该调用的那次调用里。

#### 对称的作者 / 审稿人 venue 条件化（未发布）

`prompt_overrides` 携带两个平行字段：

- `system_hint` —— 由 `review_engine` 注入同行评审提示词（既有行为）。
- `author_hint` —— 由 `write_paper_iterative` 作为
  `VENUE RUBRIC AUTHOR GUIDANCE: … END VENUE RUBRIC AUTHOR GUIDANCE`
  块注入论文起草的 system 提示词。告诉起草者审稿人会关注什么，从而在
  写作阶段就让这些信号易于呈现。

`author_hint` 为空时该块整块省略，提示词只保留 `Target venue: X.` 这一句
弱提示。SC 与 NeurIPS 附带经校准的 `author_hint` 块；其余 venue 为空，
可在不改代码的情况下逐步补齐。

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

#### `merge_reviews(review_report_path, vlm_review_path="", hard_gate_path="", semantic_review_path="")` — v0.7.0

将 `review_report.json`（文本评审）与 `vlm_review.json`（VLM 图表评审）做事后结构合并。完全确定性、无 LLM。附加 `vlm_figure_review` 与 `_review_composition` 元数据，使 GUI / CLI 能附带来源标注同时显示两类输出。上游阶段保持独立（与 AI Scientist v2 `perform_review` 契约一致），在此处方完成对账。

必填的只有 `review_report_path`，其余三个都是可选的（v0.6.0 的两参数调用仍然可用）。文本评审与 VLM 评审留在 `independent_reviews` 之下，且不被修改。`hard_gate_path`（`claim_evidence_hard_gate`）与 `semantic_review_path`（`evidence_grounded_semantic_review`）另行归入 `evidence_grounded_reviews`，并由这两者共同生成供 `paper_refine` 消费的统一 `suggested_revisions` 列表——省略它们，这份列表就没有内容可载。

#### `link_paper_claims(tex_path="", science_data_json="", figures_manifest_json="", output_path="")` — v0.9.0

将 `% CLAIM:Cx:NCx` 锚点与 science_data 声明对账，并构建供 claim 硬门消费的
`paper_claim_links.json`（anchors / writer_assertions / numeric_mentions /
figure_refs / unresolved_anchors / uncovered_numeric_candidates）。**确定性、无 LLM**。
transform 阶段的 `science_data.json` 从不被改动；图表绑定记录在此。在 `write_paper`（草稿）之后运行一次，
并在 `paper_refine`（终稿）之后再运行一次。失败时降级为一份合法的空结果（绝不仅输出 error），
因此它不会级联跳过 finalize 链。

#### `paper_refine(tex_path="", suggested_revisions_json="", merged_review_path="", semantic_review_path="", venue="arxiv", writer_prompt_override="", decode_seed=0)` — v0.9.0

保留锚点的修订流程，应用（来自 `evidence_grounded_semantic_review` / 合并评审的）
`suggested_revisions`。**LLM：是**。显式的 `replace "X" with "Y"` 替换先确定性地应用，
随后由有界的多趟 LLM 查找/替换处理其余部分；草稿中存在的每一个 `% CLAIM` 锚点都必须存活
（丢弃锚点的编辑会被拒绝，且当锚点净损失时保留原始论文）。数学安全的下划线转义会跳过
`\( … \)` / `\[ … \]` 与数学环境。精修后的 LaTeX 在 `latex` 下返回（草稿保留为 `full_paper.draft.tex`）。
`refine_passes` 报告实际跑了几趟 LLM（至多 3 趟），旧文本仍然出现的显式替换会归入
`unaddressed_substitutions`。

新增的两个参数在不设置时让默认路径逐字节保持不变，且这两个默认值是冻结的兼容契约，
不是调参旋钮。`writer_prompt_override` 是一段纯指令字符串，非空时会被**前置拼接**到
内置的 `global_coherence.md` 提示词之前，让传入的 paper-writer 文本领起这次精修 ——
注意这里的不对称：同一个参数名在 `write_paper_iterative` 里是*替换*内置提示词，在
这里只是前缀。`decode_seed` 为 `0` 时不进入 payload，非零时该次精修在其草稿的 seed
下采样，从而继承父级的 decode identity。

技能测试真正钉住的就是这两条接缝。`tests/test_server.py` 从两个方向覆盖 payload 一半：
为 `0` 时，捕获到的每一次 `litellm.acompletion` 调用都不带 `seed` 键，且 messages 与
完全省略该参数时完全一致；为非 0 时，捕获到的每一次调用都恰好带着那个 seed —— 正是
这条断言阻止「被记录下来、模型却从未见过」的 seed。
`tests/test_writer_prompt_override.py` 覆盖提示词一半：默认 system 提示词恰好是不带
前缀的 `global_coherence.md` 加语言指令，非空 override 则产生
`override + "\n\n" + global_coherence + 语言指令`。

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

PaperBench 以 git submodule 形式同捆于 `ari-skill-paper-re/vendor/paperbench`。主要逐叶评分 completer 通过 LiteLLM (`_litellm_completer.py`) 路由，因此任意供应商可用（`gpt-5-mini` / `anthropic/claude-...` / `gemini/...` / `ollama/...`）；两个分数解析用 structured completer 也由同一个 `judge_model` 构建，与主 completer 的差别仅在于携带 `response_format`（`ParsedJudgeResponseInt` / `ParsedJudgeResponseFloat`）。

### 工具

#### `fetch_code_bundle(ref="", sha256="", dest="", checkpoint_dir="", overwrite=False)`

确定性地填充沙箱（无 LLM）。**v0.7.0+**: 传入 `checkpoint_dir` 可从 `{checkpoint_dir}/publish_record.json` 自动读取 ref + sha256（即 `ari ear publish` 写入的文件）。当 `dest/reproduce.sh` 已存在时返回 `populated=False, skipped_reason=...` 并跳过。

#### `build_reproduce_sh(paper_path="", paper_text="", rubric_path="", output_dir="", model="", time_limit_sec=43200, iterative_agent=False, max_steps=0, sandbox_kind="auto", container_image="", overwrite=False)`

**v0.7.0+ 新增的 LLM 驱动 replicator**。`fetch_code_bundle` 的兄弟工具。读取论文（与 rubric 的 `expected_artifacts`）并将自包含的 `reproduce.sh` + 源文件写入 `output_dir`。其实体是 PaperBench 的 `BasicAgent` / `IterativeAgent` ReAct rollout（`_replicator_agent.run_replicator_agent`），而不是一次性产出 JSON 的调用。当 `output_dir/reproduce.sh` 已存在时跳过。模型：`model` 参数 > `ARI_MODEL_REPLICATOR` > `ARI_LLM_MODEL` > `gpt-5-mini`；OpenAI Responses 形式的 id（不含 `/` 的 `gpt-` / `o1-` / `o3-` / `o4-` / `o5-`）走 PaperBench 自带的 Responses completer，其余一律经 LiteLLM 路由，任意供应商可用。

`sandbox_kind` 为 `auto` / `local` / `apptainer` / `slurm`，决定 agent rollout 本身在哪里跑。`container_image` 只被 `apptainer` rollout 采用，取值是不可变的本地 SIF 或摘要钉住的远端 URI（参数为空时读 `ARI_PHASE1_APPTAINER_IMAGE`）；`local` / `slurm` 会忽略它。**不存在**旧版的 `apptainer_image` 参数：该名字已从签名中删除，且在整个技能里再无出现，所以这里指定镜像的唯一方式就是 `container_image`。

#### `run_reproduce(rubric_path, repo_dir, sandbox_kind="", container_image="", timeout_global_sec=0, network_policy="deny", network_isolation_attested=False, partition="", cpus=0, walltime="", …SLURM flags)`

**Phase 1**。在沙箱中执行 `repo_dir/reproduce.sh`，捕获 `reproduce.log` 与产物列表，并对照 rubric envelope 的 `expected_artifacts` 检查缺失项 `missing`。

沙箱优先级（默认 `auto`）：`slurm`（sbatch + `ARI_SLURM_PARTITION` 存在，BFTS 同分区）→ `docker`（守护可用且非 HPC 时）→ `apptainer` → `singularity` → `local`。容器沙箱没有默认镜像：必须给出一个摘要钉住的不可变镜像 —— `container_image`，否则 `docker` 读 `ARI_PHASE1_DOCKER_IMAGE`、`apptainer` / `singularity` 读 `ARI_PHASE1_APPTAINER_IMAGE`；为空时会被拒绝而不是回落到默认值。**SLURM dispatch** 不再是自己的 `sbatch`，而是交接给类型化的调度器生命周期：执行请求变成一个带 `ResourceRequestV1` 的 `JobRequestV1`，提交给 `ari-skill-hpc` 所用的同一个 `SlurmScheduler`（账本在 `{repo_dir}/../.ari-hpc/paper-re-jobs-v1.json`）并轮询至终态，随后把已验证的调度器日志落到 `reproduce.log`。返回值携带 `handle_id` / `job_id` / `request_digest` / `handoff_digest` / `execution_identity` / `unmapped_policies`；超时的作业会被取消并以 `timed_out: true` 报告。partition 按 参数 > `ARI_SLURM_PARTITION` > `{checkpoint_dir}/launch_config.json` 解析，`cpus` 按 参数 > `ARI_SLURM_CPUS`（默认 `8`），`walltime` 按 参数 > `ARI_SLURM_WALLTIME` > 由超时推导出的 `HH:MM:SS`。

**网络默认关闭**：`network_policy` 为 `deny`，只有在使用未隔离的基底时才需要以 `network_policy="inherit"` 显式准入；`network_isolation_attested` 记录该隔离是被证实的而非假定的。源码树以只读方式快照，执行发生在私有的 attempt 树中，因此同一份成功计划会幂等重放，失败计划则获得一次带链接的 retry attempt。

#### `grade_with_simplejudge(rubric_path, repo_dir, paper_path="", paper_text="", judge_model="", n_runs=0, skip_negative_control=False, code_only=False)`

**Phase 2**。主评分 completer 与 structured score-parser 都经 LiteLLM 使用同一个 `judge_model`。`n_runs`（参数，否则 `ARI_JUDGE_N_RUNS`，否则 1；范围 1–100）次按 PaperBench 加权叶节点聚合取均值，附负样本对照。

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
[`docs/reference/rubric_schema.md`](rubric_schema.md#venue-条件化模板-venue-conditioned-templates)。

#### `audit_rubric(rubric_path, paper_path="", paper_text="", auditor_model="", output_path="", max_model_calls=400)`

独立审计步骤。将问题叶节点标记为 `vague_qualifier` / `no_paper_evidence` / `duplicate` / `unverifiable`；超过 20% 时建议重新生成。

冻结后的 rubric 绝不会被改写：结论进入一份独立的 `ari.replication-rubric-audit/v2` 文档，写到 `output_path`，为空时则写在 rubric 旁边的 `<rubric_path>.audit.json`。审计开始前会重新校验 rubric 自身的 digest、它的 `paper_sha256` 与传入论文文本是否一致，以及生成方的 provenance artifact。当审计方的 model/provider/revision 身份与生成方相同时，报告记录 `independence_status: "not-independent"`。

#### `suggest_target_leaf_count(paper_path="", paper_text="")`

返回根据论文长度自动估算的目标叶数与词数（`{target, word_count}`）。两者都为空
时返回 `{"error": ..., "target": 0}`。供 GUI Wizard "Target leaves" 字段预填使用。

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

`server.py` 按 "显式 kwarg → 环境变量 → 默认值" 的顺序解析。`workflow.yaml` 的 `ors_generate_rubric` 阶段未显式传递这两个参数，因此 GUI Wizard 的值始终生效。

---

## ari-skill-memory

祖先作用域的节点记忆（v0.6.0 起由 [Letta](https://docs.letta.com) 支持）。防止跨分支污染，ReAct 轨迹也存放在同一个 Letta 代理中。**LLM：△**（基于嵌入的检索。P2 放宽详见 `docs/concepts/PHILOSOPHY.md`）。

### 工具

#### `add_memory(node_id, text, metadata=None)`

存储标记了 `node_id` 的条目。**Copy-on-Write**：若 `node_id` 与签名 call context 中的节点不一致，则拒绝写入。

#### `search_memory(query, ancestor_ids, limit=5)`

按 **Letta `passages.search`（基于 embedding 的语义搜索）排序**，仅返回 `ancestor_ids` 中节点的条目。兄弟/子节点永远不会返回。

实现说明（对 Letta 0.16.7 在 2026-05-04 验证）：本技能刻意 **不使用** SDK 的 `passages.list(search=q)`。该 SDK 路径在服务端为 `GET /archival-memory?search=q`，是 SQL **子串匹配**（`WHERE LOWER(text) LIKE LOWER(%q%)`），并非语义搜索。像 `"Validate the loopline performance model"` 这类自然语言查询不会与 `RESULT SUMMARY metrics=[...]` 这类结构化条目子串匹配，因此生产中即便有 84 条有效 passage，`search_memory` 也只返回 0 条。本技能改为调用 `passages.search`（`GET /archival-memory/search`，`embed_query=True`），以 `top_k = max(letta_overfetch, limit*40)` 拉取，再在本地按 `ancestor_ids` / `ari_checkpoint` / `kind == "node_scope"` 做 post-filter。`add_memory` 插入时已支付的 embedding 成本现在能在检索中真正被使用；子节点会按其 `eval_summary` 查询的 **语义相关度** 顺序看到祖先条目。

#### `get_node_memory(node_id)`

按时间顺序返回特定节点的所有条目（无评分）。

#### `get_experiment_context()`

返回 Letta 核心记忆中种入的稳定事实（`experiment_goal`、`primary_metric`、`hardware_spec` 等）。种入仅在首个节点的 `generate_ideas` 完成时（即 `primary_metric` 被确定的时刻）执行一次，在此之前调用会返回 `{}`。之后可安全反复调用（带 60 秒进程内缓存）。

#### 类型化的可验证研究记忆工具

类型化条目（Phase 1）携带结构化来源信息，使论文 / 图表阶段能够将声明接地到可复现的产物上。
调用方是 loop/pipeline 钩子，而非 LLM 拉取。每个写入工具都受 **Copy-on-Write 保护**：`node_id`
必须等于 ari-core MCPClient 注入调用的签名 call context 中的节点，
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

存储：每个检查点拥有一个 Letta 代理（两个集合 `ari_node_*` 与 `ari_react_*`）。可移植快照位于 `{ARI_CHECKPOINT_DIR}/memory_backup.v1.json.gz`，写/读遥测位于 `{ARI_CHECKPOINT_DIR}/memory_access.jsonl`。v0.5.x 的 JSONL 存储（检查点级 `memory_store.jsonl` 以及曾经位于 `$HOME/.ari/` 下的遗留全局 JSONL）已在 v0.6.0 移除；使用 `ari memory migrate --react` 迁移。跨实验“全局记忆”已弃用。

---

## ari-skill-orchestrator

将 ARI 作为 MCP 服务器暴露给外部智能体和 IDE，支持递归子实验。**LLM：否**（委托给 ARI CLI）。

双传输：`--transport stdio`（默认，用于 Claude Desktop / 其他 MCP 客户端）与
`--transport streamable-http`（MCP Streamable HTTP，路径 `/mcp`；
`ARI_ORCHESTRATOR_HTTP_HOST` 默认 `127.0.0.1`、`ARI_ORCHESTRATOR_HTTP_PORT`
默认 9890）。

### 工具

#### `run_experiment(experiment_md, idempotency_key, parent_run_id="", max_recursion_depth=None, max_nodes=10, max_total_nodes=100, max_descendant_runs=32, estimated_cost_usd=0.0, max_cost_usd=100.0, cpus=1, timeout_minutes=60, model="", llm_backend="", executor="", retrieval_backend="")`

幂等地提交一次受配额约束的 ARI 运行，返回其持久句柄。`idempotency_key` 是必填的：
同一个 key 重复提交拿回同一次运行，而不是第二次投入。当设置 `parent_run_id`
（或继承 `ARI_PARENT_RUN_ID`）时，该实验将作为父实验的子项被追踪（用于递归子实验
工作流）；`max_recursion_depth` 省略时取 `ARI_MAX_RECURSION_DEPTH`，再没有则是 3。
`model` / `llm_backend` / `executor` / `retrieval_backend` 为空时分别回落到
`ARI_MODEL` / `ARI_BACKEND` / `ARI_EXECUTOR` / `ARI_RETRIEVAL_BACKEND`。

#### `get_status(run_id)`

返回运行确切的持久状态与有界的科研进度。

#### `get_result(run_id)`

返回终态元数据与按 digest 寻址的产物。

#### `stop_experiment(run_id)`

取消一次运行、向下传播终止，并落定唯一的终态。

#### `list_runs()`

只列出认证 principal 拥有的运行（admin 可列全部）。

#### `list_children(parent_run_id)`

返回该父运行 ID 的已授权直接子代（用于递归子实验追踪）。

#### `list_artifacts(run_id)`

列出在 allowlist 内、经 digest 校验的产物，不暴露任何路径。

#### `read_artifact(run_id, artifact_id)`

按确切的 SHA-256 身份读取一份已准入的有界产物。

#### `get_paper(run_id)`

返回该运行的论文产物引用。

#### `get_ear(run_id)`

返回该运行经校验的 EAR 与证据产物引用。

#### `list_skills(run_id)`

返回该运行经净化的、不可变的 `SKILLS.lock` 视图。

#### `get_workflow(run_id)`

返回锁定的 phase / 工具成员关系，不含原始 workflow 与机密配置。

工作空间：`ARI_WORKSPACE` 环境变量（默认：解析后的仓库根目录）。父子关系保存在每个检查点的 `meta.json` 中。

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

模型：`llm_model` 参数 > `ARI_MODEL_TRANSFORM` 环境变量 > `ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > 与后端匹配的默认值（`ARI_BACKEND=cli-shim` 时为 `claude-cli`，否则为 `gpt-4o-mini`）。

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

钉定 provider 的网络搜索与学术文献检索，全部带 record / replay 快照。
**LLM：部分**（仅 `rerank_retrieval_records` 使用 LLM）。

每次检索都产出内容寻址的快照：`mode="record"`（默认）在
`ARI_CHECKPOINT_DIR` 下留下快照并返回 `snapshot_ref`，`"live"` 不落盘，
`"replay"` 不做任何网络访问、按 `snapshot_ref` 重放。provider 一旦钉定就绝不会
在中途被换掉——某个 provider 故障时调用会显式失败，而不是悄悄变成另一份语料。

### 工具

#### `web_search(query, n=5, mode="record", snapshot_ref="")`

DuckDuckGo 网络搜索。无需 API 密钥。`n` 上限为 10。

#### `fetch_url(url, max_chars=8000, mode="record", snapshot_ref="", max_bytes=2097152)`

通过 BeautifulSoup 获取并提取 URL 中的文本（先剥掉 `script` / `style` / `nav` /
`footer` / `header`），并施加 pinned-IP 的 SSRF 与重定向管控。

#### `search_papers(query, max_results=10, provider=None, mode="record", snapshot_ref="")`

检索**一个**钉定的学术 provider 并返回 `RetrievalRecordV1`。`provider` 为空时取
`ARI_RETRIEVAL_BACKEND`（默认 `semantic_scholar`），有效值为
`semantic-scholar` / `arxiv` / `alphaxiv`（`_` 与 `-` 等价）。`max_results` 被夹在
1…50。

复合选择被显式拒绝：`"both"` 会报错并提示「发两次钉定的 `search_papers` 调用，
再按 alias 合并」——并行去重会让记录说不清它到底来自哪个 provider。

#### `walk_citations(seed_ids, direction="references", max_depth=2, max_nodes=50, request_budget=20, mode="record", snapshot_ref="")`

从种子 paper id 出发遍历 Semantic Scholar 引用图，带环检测。`direction` 取
`references` 或 `citations`；种子最多 20 个，`max_depth` 夹在 0…5、`max_nodes`
夹在 1…500、`request_budget` 夹在 1…500。预算耗尽或 provider 报错时返回
`partial: true` 与 `requests_used`，而不是一份看起来完整的图。

#### `rerank_retrieval_records(research_question, records, max_results=10)`

显式的随机性重排：LLM 按研究问题对已检索到的 `RetrievalRecordV1` 重新排序。
确定性检索路径绝不调用它。返回值记录 `model` / `api_base_identity` /
`prompt_digest` / `input_digest` / `output_digest`，因此这一步的影响是可审计的。

模型：`ARI_LLM_MODEL` 环境变量 > `LLM_MODEL` 环境变量 > `ollama_chat/qwen3:32b`。

#### `list_uploaded_files()`

列出检查点目录中用户上传的文件。确定性。

#### `read_uploaded_file(filename, max_chars=50000)`

从上传文件读取文本内容（带二进制检测）。确定性。

---

## ari-skill-coding

代码生成、执行和文件读取。**LLM：否**（确定性）。

### 工具

#### `describe_environment()`

返回本集群的环境目录，让智能体不必靠试错去摸索工具链。**无参数**——它的输入
schema 刻意不设 `additionalProperties: false`，多传的键会被丢弃而不是让调用失败
（调用它的时刻，智能体正好还不知道该填什么）。

逐节点给出：架构、CPU、GPU、PATH 上的编译器、原始 `module avail` 目录，以及已设置
的工具链环境变量的**名字**（值绝不外泄，需要时自己 echo）。在登录节点上会同时报告
登录节点本身（它也是一个真实的构建目标）和每个已配置的计算分区；在计算节点上只报告
该节点。

#### `write_code(filename, code, work_dir="/workspace")`

将源文件写入工作目录。

#### `edit_code(filename, old_string, new_string, replace_all=False, work_dir="/workspace")`

在已存在的文件中替换一段精确文本，其余部分原样保留。文件已经存在时优先于
`write_code`：把整个 kernel 重新发一遍既费 token，又有丢掉本来能跑的代码的风险。

`old_string` 必须逐字节匹配（含缩进），并且除非设置 `replace_all`，必须**恰好**
出现一次——0 次或多次都返回 `{"status": "error", ...}`。落错地方的编辑比失败的
编辑更糟：智能体会就一个其实没改过的 kernel 报告成功。成功时返回
`{path, replacements, lines, status: "edited"}`。

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

工作目录：workspace 根目录由 `ARI_WORK_DIR`（默认 `/tmp/ari_work`）固定。`work_dir` 参数并不替换该根目录，而是选定其**下**的一个目录并按需创建；解析后落在根目录之外的路径会被拒绝而不是被改写。智能体看到的根目录是固定的容器路径 `/workspace`，文件类工具会在真正访问前把 `filename`、`command`、`path` 这几个参数中的该路径映射回真实目录，并从每个结果中抹掉真实路径。但 `work_dir` 参数本身**不会**被映射回去：它按原样对真实根目录解析，因此即便 `/workspace` 是该参数在 schema 中声明的默认值，直接把它传给 `work_dir` 也会因逸出根目录而被拒绝。请让 `work_dir` 保持未设置（此时解析为根目录），或交由下文的 `ari.agent.tool_manager` 钉定该节点的真实路径。

#### `emit_results(params, measurements, cases={}, predictions={}, scores={}, provenance={}, units={}, execution=None, file="results.json", work_dir="/workspace")`

写出一份将输入参数与测量输出分离的类型化 `results.json`，使下游（`transform → science_data`、论文撰写、summary stats）不会把「测量到的量」与「运行所用的条件」混淆，避免 best-of 归约把输入尺寸（`nnz`、`M`、`K`、`threads`）误选为真实指标（如 `GFlops_per_s`）。`params` 与 `measurements` 必须 disjoint。

文件形如 `{"schema_version": "1.0", "typed_schema_version": "ari.measurement-set/v1", "measurement_set": {...}}`，只包含规范的 `MeasurementSetV1` 对象，旁边不再写平铺投影（见[执行与测量契约](execution_contract.md)）。每个分组都必须是 finite JSON：不可序列化的值（如 `pathlib.Path`）、`NaN`/`Infinity`、以及非数值的 measurement 都会被拒绝并返回 `error`，而不是被强制转换。

可选的 `units` 参数是 `{measurement: unit}` 映射；未声明单位的 measurement 记为 `unit_status: "missing"`，单位从不推断。可选的 `execution` 参数是从上一次 `run_code`/`run_bash` 响应中原样复制的 `measurement_execution` 块（execution identity/attempt、status、exit code、artifact digest 以及服务端签发的 receipt）；不提供时 measurement 会被标记为 `execution_status: "unreported"`，并且不具备 scientifically admissible 资格。`units` 或 `provenance` 中出现 `measurements` 里没有的名字会被拒绝。

`cases` 参数确实声明在工具的 input schema 里（面向测了多个问题规模 / 形状的 run，是可选的 `{case 名: {"params": {...}, "measurements": {...}}}` 映射），但当前服务端并不转发它：`call_tool` 的 `emit_results` 分支只传 `params` / `measurements` / `predictions` / `scores` / `provenance` / `units` / `execution` / `file` / `work_dir`，写入函数也没有 `cases` 形参。因此放进 `cases` 的内容会被接受后丢弃，多形状的 run 不能只靠 `cases` 上报；请换用不同的 `file` 名，为每个 case 各出一份 `results.json`。

可选的 `provenance` 参数是一个 `{operand: source}` 映射，记录在对应的规范 measurement 记录上，由 claim/指标正确性门消费。当某个操作数的值是经验**测量**得到的上限/峰值时，标注 `"microbench"` 或 `"benchmark"`（以免归一化指标被判定为依赖占位值）；当它是相对于**独立**参考计算出的残差时，标注 `"correctness"` 或 `"reference"`（以免输出被判定为未经验证）。尽力而为，为空时完全省略。

---

## ari-skill-benchmark

结果汇总、统计检验与运行比较。**LLM：否**（确定性）。

三个工具都只接受一个 typed 的 `request` 对象，并把结果身份写进 `input_digest`
（其正规化输入的 sha256）；请求带 `artifact_target` 时，还会向封闭 workspace 的
`{relative_directory}/{digest}/` 下原子写出 `result.json` 与 `table.csv` 两份产物。
数值样本要么以 `observations` 内联给出，要么以 `source` 指向封闭 workspace 里一份
digest 绑定的 CSV / JSON / NPY 列（`expected_digest` 必填）——两者必居其一。

绘图不在本技能内：确定性渲染由 `ari-skill-plot` 承担。

### 工具

#### `analyze_results(request)`

按 `AnalysisRequestV1` 汇总带单位的 typed 样本。每个 dataset（`MetricSampleSetV1`）
必须声明 `metric_id` 与 `unit`，同一请求内 `metric_id` 不得重复。`missing_policy`
取 `error`（默认）或 `drop`，`confidence_level` 默认 `0.95`。每个 metric 返回
count / missing_count / mean / std / variance / min / q25 / median / q75 / max、
`mean_confidence_interval`、`constant_data`、`independence_status` 与
`source_digest`。

#### `statistical_test(request)`

按 `StatisticalTestRequestV1` 运行**预先声明**的检验族。每个比较给出
`comparison_id` / `group_a` / `group_b`，`test_family` 取 `auto`（默认）/ `welch_t` /
`student_t` / `paired_t` / `mann_whitney` / `wilcoxon`，`pairing` 取 `unpaired` /
`ordered` / `pair_id`，另有 `alternative` / `alpha` / `confidence_level`。两组的
`metric_id` 与 `unit` 必须一致。

`correction` 取 `none`（默认）/ `bonferroni` / `holm` / `benjamini_hochberg`：
比较多于一个时 `none` 会被拒绝——多重性策略必须显式声明，而不是事后再挑一个。
返回统计量、原始与校正后的 p 值、效应量及其置信区间。

#### `compare_runs(request)`

按 `RunComparisonRequestV1` 对标量 run 排名。至少 2 个 run，`metric_id` 与 `unit`
必须一致，`direction` 取 `higher` / `lower`；`baseline_run_id` 省略时取第一个 run。

默认 `require_compatible_environment=true`：`backend_id` + `environment_digest` 的
组合不止一种时直接拒绝，要跨环境排名就必须显式关掉它并接受 caveat。返回相对
baseline 的 `delta` / `relative_delta`、环境分组（同一 substrate 上的 run 标注
`shared_substrate`，且 `independence_inference: "not-permitted"`），以及
`independence_status`——只有每个 run 都带互不相同的 `replicate_id` 时才是
`declared`。

---

## ari-skill-plot

科学论文图表生成器。渲染器只有一个：所有路径最终都落到同一个固定的
`FigureSpecV1` 渲染器上，**任何调用方（包括 LLM）提供的绘图代码都不会被执行**。
三个工具的区别只在于 spec 从哪里来——直接给出、确定性推导，还是由 LLM 在被准入的
字段范围内挑选。**LLM：混合**（确定性 + P2 例外）。

### 工具

#### `render_figure(request)`

渲染一份规范的 `FigureSpecV1`。`request` 必须**恰好**是 `spec` / `workspace` /
`relative_directory` 三个键，多一个少一个都被拒绝。返回该图的 manifest。

#### `generate_figures(science_data_path, output_dir, n_figures=3, revision=0)`

从原生 `ScienceDataV1` 推导出确定性的默认 spec 并逐一渲染，返回一份
`FigureBatchV1`。只支持 `revision=0`：确定性默认生成没有「第二版」。

#### `generate_figures_llm(science_data_path, output_dir, experiment_summary="", n_figures=3, vlm_feedback="", revision=0, previous_batch_path="")`

让 LLM 挑选 spec，然后交给同一个固定渲染器。模型**只能**产出 `metric_id`、
`chart_type` 与 `x_mode` 三个字段；数值、单位、caption、路径、代码、SVG 与产物
字节全部由经校验的科学记录确定性地选出或生成。P2 例外。

`revision=0` 时不接受 `vlm_feedback`，`revision>0` 时则必须带上一份评审文档；
反馈还必须绑定上一版的 `manifest_digest`，且不得改动稳定的 `figure_id`——
「按反馈改图」因此不能悄悄变成「换一张图」。

规划器模型：`ARI_MODEL_PLOT` > `ARI_LLM_MODEL` > `LLM_MODEL`（都没有则报错）；
`temperature` 固定为 0。

### 环境变量

| 变量 | 用途 | 默认 |
|---|---|---|
| `ARI_MODEL_PLOT` | `generate_figures_llm` 的 spec 规划模型 | （无）|
| `ARI_MODEL_PLOT_REVISION` | 记进 manifest 的规划模型 revision | （无）|
| `ARI_LLM_MODEL` | 未设 `ARI_MODEL_PLOT` 时的回退 | （无 — 两者都缺则报错）|
| `LLM_MODEL` | 跨技能回退 | （无）|
| `ARI_LLM_API_BASE` / `LLM_API_BASE` | LiteLLM API base 覆盖 | LiteLLM 默认 |
| `ARI_CONTAINER_DIGEST` | 记进图表环境记录的容器 digest | （无）|

### ari-core 边界

`src/server.py` 通过 `from ari.public import cost_tracker` 取用 cost tracker（公共边界）。

---

## ari-skill-vlm

视觉语言模型，用于图表和表格质量审查。**LLM：是**（VLM）。评审对象都必须来自
已校验的产物：图表按 `figure_id` 从 `FigureBatchV1` 中选出，表格则是封闭 workspace
下按内容寻址的产物——本技能不接受随手给出的图片路径。

评审规范由 `criteria_profile_id` 选定（图表默认 `figure-publication/v1`），并随
评审结果一并记录。

### 工具

#### `review_figure(figures_manifest_path, figure_id, context="", criteria_profile_id="figure-publication/v1", max_output_tokens=2048)`

从已校验的 `FigureBatchV1` 中按 `figure_id` 选出一张图评审；batch 里没有这个 id
时直接报错。返回一份 `VisualReviewV1`（评分、问题与建议，并绑定该图的
`manifest_digest`）。

#### `review_figures_all(figures_manifest_path, context="", criteria_profile_id="figure-publication/v1", budget=None)`

评审该 batch 中的每一张图，逐图保留失败与原始证据——一张图取不到产物不会让整批
评审消失，它会以失败状态留在结果里。`budget`（`ReviewBudgetV1`）可调
`max_figures`（默认 20）/ `max_total_bytes`（默认 100 MiB）/ `max_concurrency`
（默认 2）/ `max_model_calls`（默认 20）/ `max_output_tokens`（默认 2048），
超出上限的图记为 `limit-error`。

#### `review_table(request)`

评审一份内容寻址的表格产物。`request` 必须**恰好**是 `workspace` / `target_id` /
`artifact` / `context` / `criteria_profile_id` / `iteration` / `max_output_tokens`
七个键（`iteration` 取 0…2），多一个少一个都被拒绝。

模型：`ARI_VLM_MODEL` 环境变量 > `VLM_MODEL` 环境变量（两者都缺则报错）；
`ARI_MODEL_VLM_REVISION` / `ARI_MODEL_VLM_PROVIDER` 会一并记进评审的 provenance。

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
