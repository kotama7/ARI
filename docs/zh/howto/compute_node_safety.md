# 计算节点安全约定 (L1–L7)

`reproduce.sh` 在 SLURM allocation 内一个全新的计算节点上运行,
而不是代理生成它的登录节点。以下约定 (L1–L7) 确保脚本能在计算节点
真正跑完。

PaperBench 复现代理通过 `ari-skill-paper-re/src/prompts/replicator.md`
中的 `COMPUTE-NODE EXECUTION CONVENTIONS` 区块被指示这些约定 (这里
也复述一份,以便你手动审查生成的 reproduce.sh)。

## L1 — 共享文件系统

`reproduce.sh` 中所有路径必须在 **每个** allocated 节点上都可解析。

- ✅ `$HOME`, `/work/...`, `/scratch/...`, `/lustre/...`, `/nfs/...`
- ❌ `/tmp`, `/var/tmp`, `/local`, 仅容器本地挂载的路径

ARI 在 checkpoint 位于节点本地 FS 时警告,但不会拒绝运行 — 多节点时
rank 1+ 看不到 rank 0 的文件会导致静默失败。

## L2 — MPI 调用: `mpirun` 之上优先 `srun`

```bash
# 优先 (使用 SLURM 的 PMI/PMIx 集成; 不需要单独安装的 OpenMPI/MPICH):
srun -n $SLURM_NTASKS ./my_program

# 可接受的回退 (仅当 OpenMPI/MPICH 作为模块加载时):
mpirun -np $SLURM_NTASKS ./my_program

# 最后手段的 Python 回退 (srun / mpirun 都不在 PATH 上时):
pip install --user mpi4py
python -c "from mpi4py import MPI; ..."
```

先用 `which srun mpirun` 测试。代理 prompt 指示复现器发出此检查。

## L3 — GRES 探测

当 rubric 的 `execution_profile.gpu_type` 设置时,ARI 在向 `sbatch`
添加 `--gres=gpu:<type>:N` 前检查 `sinfo -o '%G'`。如果未配置 GRES
(`(null)`),标志会被剥离,记录警告 — `--gpus-per-task` 存留。

交互式验证:

```python
from ari_skill_paper_re.server import _slurm_has_gres
_slurm_has_gres()    # True / False
```

## L4 — Conda / virtualenv 激活

`#!/usr/bin/env bash` 不会**自动**激活任何 Python 环境。如果你的
`reproduce.sh` 需要特定 env,前置:

```bash
# 选项 A: source ~/.bashrc (集群默认 Python env)
source ~/.bashrc

# 选项 B: 显式 conda activate
source ~/miniconda3/etc/profile.d/conda.sh
conda activate ari-repro

# 选项 C: 依赖 /usr/bin/python3 + user-site 安装
pip install --user numpy matplotlib mpi4py
```

代理 prompt 推动复现器从这些里选一个。

## L5 — 模块加载

站点特定模块 (CUDA, OpenMPI, 编译器, mathlibs) 必须在 `reproduce.sh`
内加载,而不是仅在登录节点。用 rubric 的
`execution_profile.module_loads` 指定:

```jsonc
"module_loads": ["cuda/12.4", "openmpi/4.1", "gcc/11.3"]
```

代理然后发出:

```bash
module load cuda/12.4 openmpi/4.1 gcc/11.3
```

`reproduce.sh` 顶部。ARI 不验证模块名 — 你集群的 `module avail` 是
authoritative。

## L6 — 多节点 fan-out

`reproduce.sh` 作为**第一个 allocated 节点上的一个 rank** 启动。
要使用每个 allocated 节点,脚本必须 fan out:

```bash
srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS ./my_program
```

没有这个,脚本只用 1 个节点,即使 `sbatch --nodes=4` 成功。代理 prompt
有专门的 "MULTI-NODE FAN-OUT" 区块提醒复现器。

## L7 — Timeout 包装

SLURM `--time` 强制硬墙钟,超时 SIGTERM。为了部分结果安全,把长阶段
用 `timeout` 包装:

```bash
timeout 1800 python long_step.py    # 30 分钟每步上限
timeout 600  ./bench                # 10 分钟基准测试上限
```

这确保一个慢步骤不会吃掉整个 allocation。代理 prompt 鼓励但不强制。

## 验证生成的 reproduce.sh

启动前的快速清单:

```bash
# 1. 无节点本地路径
grep -E '/(tmp|var/tmp|local)/' repro_sandbox/reproduce.sh && echo BAD

# 2. srun 或 mpirun (而非赤裸 ./program)
grep -E 'srun|mpirun' repro_sandbox/reproduce.sh || echo MISSING_FANOUT

# 3. execution_profile 要求时的模块加载
grep -E '^module load' repro_sandbox/reproduce.sh

# 4. 长步骤的 timeout 包装
grep -E 'timeout' repro_sandbox/reproduce.sh
```

## 相关

- [多节点搭建](multi_node_setup.md)
- [执行配置参考](../reference/execution_profile.md)
- [故障排查](paperbench_troubleshooting.md)
