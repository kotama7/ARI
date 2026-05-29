---
sources:
  - path: ari-skill-paper-re/src/prompts/replicator.md
    role: prompt
  - path: ari-skill-paper-re/src/_replicator_agent.py
    role: implementation
last_verified: 2026-05-25
---

# 計算ノード安全規約 (L1–L7)

`reproduce.sh` は SLURM allocation 内の compute node で実行され、
エージェントが生成した login node 上ではない。 以下 7 規約 (L1–L7)
は compute node で完走するために必要。

PaperBench レプリケータエージェントは
`ari-skill-paper-re/src/prompts/replicator.md` の
`COMPUTE-NODE EXECUTION CONVENTIONS` block 経由でこれらを指示される
(本ドキュメントは reproduce.sh を手 audit するための reference)。

## L1 — 共有 FS

`reproduce.sh` の全てのパスは **全 allocated node** から解決可能で
あること。

- ✅ `$HOME`, `/work/...`, `/scratch/...`, `/lustre/...`, `/nfs/...`
- ❌ `/tmp`, `/var/tmp`, `/local`, container-local mount のみのパス

ARI は checkpoint dir がノードローカル FS の場合に警告するが、 run
は止めない — rank 1+ が rank 0 のファイルを見えず silent fail する。

## L2 — MPI 起動: `mpirun` より `srun` を優先

```bash
# 推奨 (SLURM PMI/PMIx 統合経由; OpenMPI/MPICH を別途インストール
# しなくても動く):
srun -n $SLURM_NTASKS ./my_program

# 許容できる fallback (OpenMPI/MPICH モジュールが load されている時のみ):
mpirun -np $SLURM_NTASKS ./my_program

# 最終手段の Python fallback (srun/mpirun どちらも PATH に無い時):
pip install --user mpi4py
python -c "from mpi4py import MPI; ..."
```

先に `which srun mpirun` でテストする。 エージェントプロンプトは
レプリケータにこのチェックを emit するよう指示する。

## L3 — GRES プローブ

rubric の `execution_profile.gpu_type` が設定されている場合、 ARI は
`sbatch` に `--gres=gpu:<type>:N` を加える前に `sinfo -o '%G'` を確認
する。 GRES 未設定 (`(null)`) なら flag を落とし、 警告を log。
`--gpus-per-task` は残る。

対話的に確認:

```python
from ari_skill_paper_re.server import _slurm_has_gres
_slurm_has_gres()    # True / False
```

## L4 — Conda / virtualenv activation

`#!/usr/bin/env bash` は **どの** Python 環境も自動的には activate
しない。 reproduce.sh に特定 env が必要なら冒頭で:

```bash
# Option A: source ~/.bashrc (クラスタのデフォルト Python env)
source ~/.bashrc

# Option B: 明示的 conda activate
source ~/miniconda3/etc/profile.d/conda.sh
conda activate ari-repro

# Option C: /usr/bin/python3 + user-site インストールに任せる
pip install --user numpy matplotlib mpi4py
```

エージェントプロンプトはレプリケータに上記いずれかを選ばせる。

## L5 — モジュールロード

サイト固有のモジュール (CUDA, OpenMPI, コンパイラ, mathlib) は login
node ではなく `reproduce.sh` 内でロードする必要がある。 rubric の
`execution_profile.module_loads` で指定:

```jsonc
"module_loads": ["cuda/12.4", "openmpi/4.1", "gcc/11.3"]
```

エージェントは次を emit:

```bash
module load cuda/12.4 openmpi/4.1 gcc/11.3
```

ARI はモジュール名を検証しない — クラスタの `module avail` が authoritative。

## L6 — マルチノード fan-out

`reproduce.sh` は **最初の allocated node 上の 1 rank として起動**
する。 全ノードを使うにはスクリプトが fan-out する必要がある:

```bash
srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS ./my_program
```

これがないと `sbatch --nodes=4` 成功でもスクリプトは 1 node しか使わ
ない。 エージェントプロンプトの "MULTI-NODE FAN-OUT" 節がレプリケータ
に念押しする。

## L7 — Timeout 包み

SLURM `--time` はハードウォールクロック (時間超過で SIGTERM)。 部分的
結果安全のため長時間ステップを `timeout` で囲む:

```bash
timeout 1800 python long_step.py    # 30 分上限
timeout 600  ./bench                # 10 分ベンチマーク上限
```

これにより遅いステップが allocation 全部を食わない。 エージェント
プロンプトは推奨するが強制はしない。

## 生成済 reproduce.sh の検証

実行前のチェックリスト:

```bash
# 1. ノードローカルパス無し
grep -E '/(tmp|var/tmp|local)/' repro_sandbox/reproduce.sh && echo BAD

# 2. srun OR mpirun (生 ./program ではなく)
grep -E 'srun|mpirun' repro_sandbox/reproduce.sh || echo MISSING_FANOUT

# 3. execution_profile が要求した場合のモジュールロード
grep -E '^module load' repro_sandbox/reproduce.sh

# 4. 長時間ステップの timeout
grep -E 'timeout' repro_sandbox/reproduce.sh
```

## 関連

- [マルチノード設定](multi_node_setup.md)
- [実行プロファイル仕様](../../reference/execution_profile.md)
- [トラブルシューティング](paperbench_troubleshooting.md)
