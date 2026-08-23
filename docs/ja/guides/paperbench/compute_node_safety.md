---
sources:
  - path: ari-skill-paper-re/src/prompts/replicator.md
    role: prompt
  - path: ari-skill-paper-re/src/_replicator_agent.py
    role: implementation
last_verified: 2026-08-08
---

# 計算ノード安全規約 (L1–L7)

`reproduce.sh` は SLURM allocation 内の compute node で実行され、
エージェントが生成した login node 上ではない。 以下 7 規約 (L1–L7)
は compute node で完走するために必要。

PaperBench レプリケータエージェントは、`_format_hpc_appendix`
(`ari-skill-paper-re/src/_replicator_agent.py`) が vendor 版 PaperBench の
instruction に付加する ARI 側 appendix の
`COMPUTE-NODE EXECUTION CONVENTIONS` block 経由でこれらを指示される。
この block は appendix 内の他の HPC 系 block (`EXECUTION PROFILE`,
`CLUSTER SHAPE`, `CONVENTIONS`) と同様、rubric の
`reproduce_contract.execution_profile` が非空のときだけ出力されるため、
非 HPC 論文のエージェントは受け取らない。`expected_artifacts` だけが
ある場合、appendix は `EXPECTED_ARTIFACTS` block のみに縮退する。
`ari-skill-paper-re/src/prompts/replicator.md` は同じ block のより詳しい
mirror を持つが、実行時に読み込まれることはない
(本ドキュメントは reproduce.sh を手 audit するための reference)。

## L1 — 共有 FS

`reproduce.sh` の全てのパスは **全 allocated node** から解決可能で
あること。

- ✅ `$HOME`, `/work/...`, `/scratch/...`, `/lustre/...`, `/nfs/...`
- ❌ `/tmp`, `/var/tmp`, `/local`, container-local mount のみのパス

ARI は filesystem を probe しない。checkpoint dir がノードローカル FS で
あっても検知せず、警告も出ない — rank 1+ が rank 0 のファイルを見えず
silent fail する。共有かどうかは観測ではなく *宣言* で、`SLURM_MODE=remote`
は `SLURM_SHARED_FILESYSTEM` (既定 `true`) を読み、local mode は無条件に
`true` とみなす (`ari-skill-hpc/ari_skill_hpc/slurm.py`)。`false` と宣言した
場合は警告ではなく *拒否* で、typed outputs と fixed-wrapper terminal
evidence の双方が raise する。

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

先に `which mpirun` でテストする。 エージェントプロンプトは
レプリケータに `mpirun` が PATH にある前提を置かず、使う前に確認する
よう指示する。

## L3 — GPU resource検証

ARIはGPU count/typeを一つの型付きscheduler requestへ変換し、削除しない。
launch前に`sinfo -o '%P %G'`を確認する。partitionが満たせなければsubmitを
失敗させ、cluster設定を直すか対応partitionを選ぶ。

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
ない。 エージェントプロンプトの "Multi-node fan-out" 節がレプリケータ
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
