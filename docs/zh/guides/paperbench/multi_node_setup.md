---
sources:
  - path: ari-skill-paper-re/src/server.py
    role: implementation
last_verified: 2026-05-25
---

# PaperBench 多节点搭建

ARI 默认提供单节点沙箱 (local / apptainer / docker)。要添加多节点
MPI 再现,需要 3 个站点前提:

1. **`sbatch` 在 PATH 上**
2. **GRES (generic resources) 已配置**: 仅当 rubric 要求 `gpu_type`
   时才需要。`sinfo -o '%G'` 验证 — `(null)` 表示未配置 GRES
3. **共享文件系统** (NFS / Lustre / GPFS) 以相同路径挂载在所有节点。
   ARI 在 checkpoint dir 看起来是节点本地时发出警告

## 站点验证

```bash
# 1. sbatch 在 PATH 上?
which sbatch && echo OK

# 2. GRES 已配置?
sinfo -h -o '%G' | head    # 期望: gpu:v100:4 等;"(null)" = 无 GRES

# 3. 共享 FS — $HOME 真的位于共享上?
df -hT $HOME               # 查看 nfs / lustre / nfs4 / fuse.lustre

# 4. MPI 可用?
which srun mpirun          # 优先 srun (PMI/PMIx 集成)
module avail openmpi 2>&1 | head
```

ARI 的安全探测:
- `_is_shared_fs()` — checkpoint 目录看起来是节点本地时警告
- `_slurm_has_gres()` — `sinfo` 报告无 GRES 时静默剥离
  `--gres=gpu:<type>:N` 标志,但保留 `--gpus-per-task`,使提交不被
  拒绝

## 选择正确的分区

`ari-skill-paper-re` 服务器按以下顺序解析 SLURM 分区: 显式调用方
参数 → `ARI_SLURM_PARTITION` env → checkpoint
`launch_config.json`。任一设置都会切换向导的默认分区。

```bash
export ARI_SLURM_PARTITION=large
```

## 示例: sx40 (单节点, 4×V100)

`sx40` 是 CRA 分区,每节点暴露 `4× V100-SXM2-16GB`,未配置 GRES。
使用:

```jsonc
"execution_profile": {
  "kind": "gpu_single",
  "paper_max_ranks": 1,
  "requested_gpus_per_task": 1
  // gpu_type 省略 — 无 GRES; sinfo 探测强制执行
}
```

## 示例: R-CCS Cloud (Web UI, 手动)

R-CCS Cloud Jupyter 通过 web notebook 暴露 SLURM allocation。ARI run
无法从 notebook 内直接 `sbatch`,所以:

1. 从 notebook 运行 `python -m ari.viz.server --host 0.0.0.0`
2. 在另一个终端会话 (同一 allocation 内) 运行
   `ari run experiment.md`。把 experiment 指向共享 `/work/...` 上的
   checkpoint dir
3. 向导的 *再现* 步骤设 `sandbox_kind=slurm` 和 `nodes=<allocation>`

## 模块加载

当 rubric 携带 `module_loads: ["cuda/12.4","openmpi/4.1"]` 时,代理
被指示在 `reproduce.sh` 顶部发出 `module load cuda/12.4 openmpi/4.1`
行。ARI 不验证模块名 — 你集群的 `module avail` 是 authoritative。

## 失败模式与恢复

| 症状 | 原因 | 修复 |
|---|---|---|
| `sbatch: error: Invalid GRES gpu:v100:1` | 未配置 GRES | 把 `gpu_type` 留空;只依赖 `--gpus-per-task` |
| 计算节点 `mpirun: command not found` | compute node 上未加载 OpenMPI | 把 `"openmpi/4.1"` (或集群名) 加到 `module_loads`,或改用 `srun` (代理 prompt 优先) |
| 全部 rank 都落在节点 1 | reproduce.sh 没有 `srun` fan-out | 代理 prompt 的 "MULTI-NODE FAN-OUT" 区块指示 `srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS`; 检查生成的 reproduce.sh 是否有该行 |
| rank > 0 时打开文件 `Permission denied` | `repo_dir` 在 `/tmp` 上 | 把 checkpoint 移到 `$HOME` 或 `/work/...`; 查看 run log 中的共享 FS 警告 |

## 相关

- [执行配置参考](../../reference/execution_profile.md)
- [计算节点安全约定](compute_node_safety.md)
- [`hpc_setup.md`](../hpc_setup.md) — ARI HPC 配置基础
