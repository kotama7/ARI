---
sources:
  - path: ari-skill-replicate/schemas/replication_rubric.schema.json
    role: schema
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/src/rubric_contract.py
    role: implementation
  - path: ari-skill-paper-re/src/_replicator_agent.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/contracts.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
last_verified: 2026-08-16
---

# `execution_profile` 参考

PaperBench 评分单 (`ari-skill-replicate/schemas/replication_rubric.schema.json`
— `schema_version: ari.replication-rubric/v2`、`version: "3"`) 中
`reproduce_contract` 下的 `execution_profile` 对象描述论文要求的
并行执行属性 (SLURM 分配形态、GPU 类型、内存、NUMA 绑定等)。
`ari-skill-paper-re` 读取它并把 allocation 字段编译为
`ari.hpc.job-request/v1`；复现代理在生成 `reproduce.sh` 时，会在提示词中原样
收到整个对象。

单 CPU 论文可省略 `execution_profile`。调度器始终使用带类型的 request、
干净环境、digest 与 handle 生命周期。

> **到底谁在做校验。** JSON-schema 校验位于 `ari-skill-replicate`
> (`generator.py` / `auditor.py`)，在评分单被生成或审计时运行。
> `ari-skill-paper-re` 的 `load_rubric` 只检查信封——版本协商、`rubric_sha256`、
> `paper_sha256`、TaskNode 形态——它**不会**对 `execution_profile` 跑 schema，
> 也不会注入 schema 的 `default:` 值。每个读取处都是
> `exec_profile.get(field, 0) or 0`（或 `... or ""`），因此不管下表「默认」列
> 写的是什么，省略的字段在运行时都表现为 `0` / `""` / `False`。真正会咬人的
> 一处：`accepts_reduced_scale` 的文档默认值是 `true`，但一旦省略，代理就永远
> 看不到缩小规模的指示。第二道闸门是带类型的 `ResourceRequestV1`，它拒绝形态
> 错误的**已编译**请求。

## 完整字段表

| 字段 | 类型 | SLURM 标志 | 默认 | 备注 |
|---|---|---|---|---|
| `kind` | enum | (仅 agent prompt) | — | `cpu_single` \| `gpu_single` \| `gpu_multi` \| `mpi` \| `mpi_gpu` |
| `paper_max_ranks` | int | — | — | 论文报告的最大 rank 数 |
| `paper_max_nodes` | int | — | — | 论文报告的最大节点数 |
| `min_ranks` | int | `--ntasks=N` | 1 | 部分得分允许的最小 rank 数。设置后它就是请求的 `--ntasks`，因此 `ntasks_per_node` 不得超过它 (带类型 request 会以 `tasks_per_node cannot exceed total tasks` 拒绝) |
| `min_nodes` | int | (仅 agent prompt) | 1 | `min_ranks` 的节点版本。没有任何解析代码读取它——`--nodes` 来自 `requested_nodes` |
| `result_aggregation` | enum | (仅 agent prompt) | `rank0_csv` | `rank0_csv` 是 schema 中唯一的枚举成员 |
| `metric_columns` | list[str] | — | `[]` | CSV 表头 (如 `["nodes","ranks","runtime_sec","gflops"]`) |
| `accepts_reduced_scale` | bool | — | `true` | 允许缩小规模再现 (true → CSV 添加 `paper_paper_scale_point` 列) |
| `requested_nodes` | int | `--nodes=N` | 0（缺省） | 提示。调用方参数优先。schema 要求 `minimum: 1`，因此应当省略该键而不是写 `0`；缺省值编译为 `--nodes=1` |
| `ntasks_per_node` | int | `--ntasks-per-node=N` | 0 | 0 → 该 directive 被整个省略。未给出 `ntasks` 时，总任务数按 `ntasks_per_node × nodes` 推导（否则为 1） |
| `requested_nodelist` | str | `--nodelist=...` | `""` | 指定节点 |
| `exclude_nodes` | str | `--exclude=...` | `""` | 排除节点 |
| `exclusive` | bool | `--exclusive` | `false` | 忠实性能复现必备 |
| `requested_gpus_per_task` | int | `--gpus-per-task=[<type>:]N` | 0 | 与 `requested_gpus_per_node` 互斥（schema `allOf` 与 `ResourceRequestV1`） |
| `requested_gpus_per_node` | int | `--gres=gpu:[<type>:]N` | 0 | 发出的是 `--gres` 而非 `--gpus-per-node`，且仅在 `requested_gpus_per_task` 为 0 时发出 |
| `gpu_type` | str | 带类型 GPU selector | `""` | 与恰好一个 GPU 数量字段组合；绝不静默删除请求——单独给出 `gpu_type` 会被提升为 `requested_gpus_per_node=1`，而不是被丢弃 |
| `memory_gb_per_node` | int | `--mem=<GB×1024>M` | 0 | 与 `memory_gb_per_cpu` 互斥 |
| `memory_gb_per_cpu` | int | `--mem-per-cpu=<GB×1024>M` | 0 | 与 `memory_gb_per_node` 互斥 |
| `constraint` | str | `--constraint=...` | `""` | 例: `"skylake"`, `"haswell|broadwell"` |
| `cpu_bind` | str | `reproduce.sh` 中的 `srun --cpu-bind` | `""` | job-step 设置，不是 sbatch directive——而且 `run_reproduce` 从不转发评分单里的值：它只传递自己的 `cpu_bind` 参数，SLURM 路径随后直接拒绝（`cpu_bind and mem_bind are srun job-step settings; place them explicitly in reproduce.sh`）。评分单中的值只会作为 EXECUTION PROFILE 转储的一部分抵达代理 |
| `mem_bind` | str | `reproduce.sh` 中的 `srun --mem-bind` | `""` | 与 `cpu_bind` 处理方式相同 |
| `hint` | enum | `--hint=...` | `""` | `""` \| `compute_bound` \| `memory_bound` \| `multithread` \| `nomultithread` |
| `module_loads` | list[str] | 干净 job prelude | `[]` | 显式加载并记录 provenance |
| `account` / `qos` / `reservation` | str | 各带类型 selector | `""` | 替代任意标志 |
| `extra_sbatch_args` | list[str] | 仅 deprecated reader | `[]` | 新生产者禁止；仅兼容转换四个限定字段 |

## 自动解析优先级

`ari-skill-paper-re.run_reproduce` 按以下顺序解析每个标志:

```
显式调用方参数  >  评分单 execution_profile  >  默认值
```

向导的「执行配置覆盖」表单因此能覆盖评分单。布尔字段
(`exclusive`) 取 OR — 任一来源启用即发出该标志。

该链条有两个例外:

- `cpu_bind` / `mem_bind` **只认调用方参数**。`run_reproduce` 从不为它们查阅
  `execution_profile`。
- `account` / `qos` / `reservation` / `hint` 多出第四级、也是最低的一级: 从已废弃的
  `extra_sbatch_args` 列表中解析出来的值。

`partition` 完全不属于 `execution_profile`，它单独解析（调用方参数 →
`$ARI_SLURM_PARTITION` → `$SLURM_PARTITION` →
`{checkpoint_dir}/launch_config.json` 的 `partition`）；`slurm` sandbox 若解析
不出分区则是硬错误，而不是回退。

## HPC 完整示例 (MPI + GPU)

TS-SpGEMM 扩展性 (4 节点 × 8 ranks × V100×1/task, 独占, 仅 Skylake)
忠实再现:

```jsonc
"reproduce_contract": {
  "script_path": "reproduce.sh",
  "max_runtime_sec": 7200,
  "expected_artifacts": ["submission/results/scaling.csv"],
  "execution_profile": {
    "kind": "mpi_gpu",
    "paper_max_ranks": 32,
    "paper_max_nodes": 4,
    "min_ranks": 32,
    "result_aggregation": "rank0_csv",
    "metric_columns": ["nodes","ranks","runtime_sec","gflops"],
    "accepts_reduced_scale": true,

    "requested_nodes": 4,
    "ntasks_per_node": 8,
    "exclusive": true,

    "requested_gpus_per_task": 1,
    "gpu_type": "v100",

    "memory_gb_per_node": 256,
    "constraint": "skylake",
    "cpu_bind": "cores",
    "hint": "nomultithread",

    "module_loads": ["cuda/12.4", "openmpi/4.1"],
    "account": "projX"
  }
}
```

通过stdin交给 `sbatch --parsable --export=NIL` 的生成脚本主要directive:

```
#SBATCH --partition=large
#SBATCH --nodes=4
#SBATCH --ntasks=32
#SBATCH --ntasks-per-node=8
#SBATCH --exclusive
#SBATCH --gpus-per-task=v100:1
#SBATCH --mem=262144M
#SBATCH --constraint=skylake
#SBATCH --hint=nomultithread
#SBATCH --account=projX
#SBATCH --export=NIL
```

以上只是本 profile 控制的那一部分。生成器另外总会发出 `--job-name`、`--time`、
`--chdir`、`--output`、`--error`，`--export=NIL` 则是无条件发出的。

`launcher` 默认为 `auto`，它只把单任务单节点的载荷包进 `srun`。上面这样的
32-rank 请求会被**直接**启动，因此 `reproduce.sh` 自己必须完成并行启动
(`srun -n $SLURM_NTASKS` 或 `mpirun -np $SLURM_NTASKS`) —— 这正是代理在 `mpi` /
`mpi_gpu` 类型下被要求写出的内容。

## 单 GPU 示例

```jsonc
"execution_profile": {
  "kind": "gpu_single",
  "paper_max_ranks": 1,
  "metric_columns": ["throughput_GB_s", "PSNR_dB"]
}
```

代理提示词会要求使用 CUDA / PyTorch CUDA / cupy;SLURM 分配回退至
分区默认。

## 单 CPU 示例

```jsonc
// 完全省略 execution_profile → 回退到传统单节点行为
"reproduce_contract": {
  "script_path": "reproduce.sh",
  "max_runtime_sec": 1800,
  "expected_artifacts": ["results.csv"]
}
```

## 相关

- [PaperBench 快速入门](../guides/paperbench/paperbench_quickstart.md)
- [多节点搭建](../guides/paperbench/multi_node_setup.md)
- [计算节点安全约定](../guides/paperbench/compute_node_safety.md)
- 实现: `ari-skill-paper-re/src/server.py:run_reproduce`
- Schema: `ari-skill-replicate/schemas/replication_rubric.schema.json`
