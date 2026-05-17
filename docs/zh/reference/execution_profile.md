# `execution_profile` 参考

PaperBench 评分单 (`ari-skill-replicate/schemas/replication_rubric.schema.json`,
v3) 中 `reproduce_contract` 下的 `execution_profile` 对象描述论文要求的
并行执行属性 (SLURM 分配形态、GPU 类型、内存、NUMA 绑定等)。
`ari-skill-paper-re` 的 Phase 2 sbatch 调度器会读取它,用以补全调用方
未提供的参数并生成相应的 SLURM 标志。

对于传统单 CPU 论文,可完全省略 `execution_profile` —— 所有调用方参数
默认为 0/""/False/None,sbatch 命令会回退到 v0.7.2 之前的 4 标志形式。

## 完整字段表

| 字段 | 类型 | SLURM 标志 | 默认 | 备注 |
|---|---|---|---|---|
| `kind` | enum | (仅 agent prompt) | — | `cpu_single` \| `gpu_single` \| `gpu_multi` \| `mpi` \| `mpi_gpu` |
| `paper_max_ranks` | int | — | — | 论文报告的最大 rank 数 |
| `paper_max_nodes` | int | — | — | 论文报告的最大节点数 |
| `min_ranks` | int | `--ntasks=N` | 1 | 部分得分允许的最小 rank 数 |
| `min_nodes` | int | — | 1 | 节点版本 |
| `result_aggregation` | enum | — | `rank0_csv` | v0.7.2 仅支持 `rank0_csv` |
| `metric_columns` | list[str] | — | `[]` | CSV 表头 (如 `["nodes","ranks","runtime_sec","gflops"]`) |
| `accepts_reduced_scale` | bool | — | `true` | 允许缩小规模再现 (true → CSV 添加 `paper_paper_scale_point` 列) |
| `requested_nodes` | int | `--nodes=N` | 0 | 提示。调用方参数优先 |
| `ntasks_per_node` | int | `--ntasks-per-node=N` | 0 | 0 → 交给 SLURM |
| `requested_nodelist` | str | `--nodelist=...` | `""` | 指定节点 |
| `exclude_nodes` | str | `--exclude=...` | `""` | 排除节点 |
| `exclusive` | bool | `--exclusive` | `false` | 忠实性能复现必备 |
| `requested_gpus_per_task` | int | `--gpus-per-task=N` | 0 | |
| `requested_gpus_per_node` | int | `--gpus-per-node=N` | 0 | |
| `gpu_type` | str | `--gres=gpu:<type>:N` | `""` | 与 gpus_per_task 组合;`sinfo` 报告无 GRES 时自动剥离 |
| `memory_gb_per_node` | int | `--mem=NG` | 0 | |
| `memory_gb_per_cpu` | int | `--mem-per-cpu=NG` | 0 | |
| `constraint` | str | `--constraint=...` | `""` | 例: `"skylake"`, `"haswell|broadwell"` |
| `cpu_bind` | str | `--cpu-bind=...` | `""` | 例: `"cores"`, `"sockets"`, `"rank"` |
| `mem_bind` | str | `--mem-bind=...` | `""` | 例: `"local"`, `"nearest"` |
| `hint` | str | `--hint=...` | `""` | 例: `"nomultithread"` |
| `module_loads` | list[str] | (reproduce.sh 开头) | `[]` | 代理执行的 `module load` 列表 |
| `extra_sbatch_args` | list[str] | (拼接) | `[]` | 上述无法表达的标志的逃生口 (如 `["--account=projX"]`) |

## 自动解析优先级

`ari-skill-paper-re.run_reproduce` 按以下顺序解析每个标志:

```
显式调用方参数  >  评分单 execution_profile  >  默认值
```

向导的「执行配置覆盖」表单因此能覆盖评分单。布尔字段
(`exclusive`) 取 OR — 任一来源启用即发出该标志。

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
    "min_ranks": 4,
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
    "extra_sbatch_args": ["--account=projX"]
  }
}
```

实际 sbatch 命令:

```
sbatch --wait \
  --partition large \
  --nodes 4 --ntasks 32 --ntasks-per-node 8 \
  --exclusive \
  --gpus-per-task 1 --gres=gpu:v100:1 \
  --mem=256G --cpus-per-task 8 \
  --constraint=skylake --cpu-bind=cores --hint=nomultithread \
  --account=projX \
  --time 02:00:00 \
  reproduce.sh
```

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

- [PaperBench 快速入门](../howto/paperbench_quickstart.md)
- [多节点搭建](../howto/multi_node_setup.md)
- [计算节点安全约定](../howto/compute_node_safety.md)
- 实现: `ari-skill-paper-re/src/server.py:run_reproduce`
- Schema: `ari-skill-replicate/schemas/replication_rubric.schema.json`
