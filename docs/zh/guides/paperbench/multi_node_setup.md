---
sources:
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/src/prompts/replicator.md
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
last_verified: 2026-08-16
---

# PaperBench 多节点搭建

ARI 默认提供单节点沙箱 (local / apptainer / docker)。要添加多节点
MPI 再现,需要 3 个站点前提:

1. **`sbatch` 在 PATH 上**
2. **GRES (generic resources) 已配置**: 仅当 rubric 要求 `gpu_type`
   时才需要。`sinfo -o '%G'` 验证 — `(null)` 表示未配置 GRES
3. **共享文件系统** (NFS / Lustre / GPFS) 以相同路径挂载在所有节点。
   ARI 里没有任何东西检查这一点 — 不存在针对 `repo_dir` 的「节点本地」
   警告。唯一的防线是建议性的: replicator prompt 告诉 agent,
   `reproduce.sh` 里的每个路径都必须在每个被分配的节点上可解析,并且
   绝不使用 `/tmp` 或 `/var/tmp`

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

ARI验证path与resource syntax，但无法证明mount共享性或partition能力。
使用compute node可见的filesystem并在launch前检查`sinfo`。resource请求按原样
提交，绝不静默删除。

## 选择正确的分区

`ari-skill-paper-re` 服务器按以下顺序解析 SLURM 分区: 显式调用方
参数 → `ARI_SLURM_PARTITION` env → `SLURM_PARTITION` env →
`launch_config.json` (依次在 `{repo_dir}/../launch_config.json`、
`{repo_dir}/launch_config.json` 查找)。任一设置都会切换向导的默认分区。
若全部都解析不出,`sandbox_kind=slurm` 的再现会以
*"no partition could be resolved"* 失败,而不是回退。

`ARI_SLURM_PARTITION` 还兼任第二个职责: 只有当 `sbatch` 在 PATH 上
**且** `ARI_SLURM_PARTITION` 已设置时,`sandbox_kind=auto` 才会解析为
`slurm`。`SLURM_PARTITION` 与 `launch_config.json` 不会启用 `auto` 这条
路径。

```bash
export ARI_SLURM_PARTITION=<your-partition>
```

## 示例：匿名的未配置 GRES 的 GPU 分区

若某站点暴露了物理 GPU 却没有配置调度器 GRES,SLURM 就无法可靠地预约
它们。请选择启用了 GRES 的分区,或请站点管理员配置;不要把请求隐式
转成 CPU。

```jsonc
"execution_profile": {
  "kind": "gpu_single",
  "paper_max_ranks": 1,
  "requested_gpus_per_task": 1,
  "gpu_type": "v100"
}
```

`run_reproduce` 从这个块里读取 `requested_gpus_per_task`、
`requested_gpus_per_node` 与 `gpu_type`,但 `--ntasks` 取自 `min_ranks`
而不是 `paper_max_ranks` — 后者是给 agent 看的、评分单一侧的规模陈述,
不是调度器字段。完全不带数量的 `gpu_type` 会变成
`--gres=gpu:<type>:1`。

## 示例: 经由 notebook 的 allocation (Web UI, 手动)

有些站点不提供 login shell,而是通过托管的 Jupyter notebook 暴露 SLURM
allocation。ARI run 无法从 notebook 内直接 `sbatch`,所以:

1. 从 notebook 运行 `ARI_GUI_BIND=0.0.0.0 python -m ari.viz.server`。
   没有 `--host` 参数 — 服务器只接受 `--checkpoint` 与 `--port`
   (默认 `8765`),并且除非 `ARI_GUI_BIND` 另有指定,否则只绑定回环
   (`127.0.0.1` + `::1`;`::` 表示双栈通配)
2. 在另一个终端会话 (同一 allocation 内) 运行
   `ari run experiment.md`。把 experiment 指向共享 `/work/...` 上的
   checkpoint dir
3. 向导的 *再现* 步骤把 **Sandbox** 下拉设为 `slurm`,把 `nodes` 设为
   allocation 的节点数

## 模块加载

当 rubric 携带 `module_loads: ["cuda/12.4","openmpi/4.1"]` 时,会发生
两件互相独立的事:

- 代理被指示在 `reproduce.sh` 顶部发出
  `module load cuda/12.4 openmpi/4.1` 行。
- 对 `sandbox_kind=slurm`,该列表还会声明在 `JobRequestV1` 上,生成的
  批处理脚本会 source module init、执行 **`module --force purge`**,再
  按顺序 `module load` 每个条目,然后才跑 payload。purge 是意外之处:
  节点 (或你的 sbatch 包装脚本) 此前加载的一切会先被丢弃,因此声明的
  列表必须完整。完全没有 module 系统的节点会以 `86` 退出,而不是
  在没有 module 的情况下继续跑。

ARI 不验证模块名 — 你集群的 `module avail` 是 authoritative。

## 失败模式与恢复

| 症状 | 原因 | 修复 |
|---|---|---|
| `sbatch: error: Invalid GRES gpu:v100:1` | 未配置 GRES | 把 `gpu_type` 留空;只依赖 `--gpus-per-task` |
| 计算节点 `mpirun: command not found` | compute node 上未加载 OpenMPI | 把 `"openmpi/4.1"` (或集群名) 加到 `module_loads`,或改用 `srun` (代理 prompt 优先) |
| 全部 rank 都落在节点 1 | reproduce.sh 没有 `srun` fan-out | replicator prompt 的 "Multi-node fan-out" 区块指示 `srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS`; 检查生成的 reproduce.sh 是否有该行 |
| rank > 0 时打开文件 `Permission denied` | `repo_dir` 在 `/tmp` 上 | 把 checkpoint 移到 `$HOME` 或 `/work/...`。没有任何东西会记录共享 FS 警告;只有 rank 0 成功这一现象就是你能拿到的第一个信号 |
| `exit 86` 并伴随 "requested environment modules are unavailable" | rubric 声明了 `module_loads`,但计算节点没有 module 系统 | 去掉 `module_loads`,或改用节点带 Lmod / Environment Modules 的分区 |
| `cpu_bind and mem_bind are srun job-step settings` | 在 `sandbox_kind=slurm` 下设置了这两个字段 | 在向导里清空它们,把绑定写进 `reproduce.sh` |

## 相关

- [执行配置参考](../../reference/execution_profile.md)
- [计算节点安全约定](compute_node_safety.md)
- [`hpc_setup.md`](../hpc_setup.md) — ARI HPC 配置基础
