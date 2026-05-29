---
sources:
  - path: ari-skill-paper-re/src/server.py
    role: implementation
last_verified: 2026-05-25
---

# PaperBench マルチノード設定

ARI は標準でシングルノード sandbox (local / apptainer / docker) を
提供する。 マルチノード MPI 再現を追加するには 3 つのサイト前提が必要:

1. **`sbatch` が PATH 上にあること**
2. **GRES (generic resources) 設定済**: rubric が `gpu_type` を要求する
   場合のみ必要。`sinfo -o '%G'` で確認 — `(null)` は GRES 未設定
3. **共有ファイルシステム** (NFS / Lustre / GPFS) が全ノードに同パスで
   マウントされていること。ARI は checkpoint dir がノードローカルに
   見える場合に警告を出す

## サイト検証

```bash
# 1. sbatch あるか
which sbatch && echo OK

# 2. GRES 設定済か
sinfo -h -o '%G' | head    # expect: gpu:v100:4 等; "(null)" は GRES 無し

# 3. 共有 FS 上か — $HOME は本当の share に乗っているか
df -hT $HOME               # nfs / lustre / nfs4 / fuse.lustre を確認

# 4. MPI が利用可能か
which srun mpirun          # srun が好ましい (PMI/PMIx 統合)
module avail openmpi 2>&1 | head
```

ARI の安全プローブ:
- `_is_shared_fs()` — checkpoint dir が `/tmp`, `/var/tmp`, あるいは
  他の非共有 root にある場合に警告
- `_slurm_has_gres()` — `sinfo` が GRES 未設定を報告する場合、
  `--gres=gpu:<type>:N` を silent に落とし、 `--gpus-per-task` は維持。
  これにより submission が拒絶されない

## パーティション選択

`ari-skill-paper-re` サーバは SLURM パーティションを次の順で解決する:
明示的 caller 引数 → `ARI_SLURM_PARTITION` env →
checkpoint `launch_config.json`。どれを設定してもウィザードの既定
パーティションが切り替わる。

```bash
export ARI_SLURM_PARTITION=large
```

## 例: sx40 (シングルノード, 4×V100)

`sx40` は CRA の partition で `4× V100-SXM2-16GB` を 1 ノードに提供
(GRES 未設定)。 設定例:

```jsonc
"execution_profile": {
  "kind": "gpu_single",
  "paper_max_ranks": 1,
  "requested_gpus_per_task": 1
  // gpu_type 省略 — GRES 無し; sinfo プローブが強制
}
```

## 例: R-CCS Cloud (Web UI, 手動)

R-CCS Cloud Jupyter は SLURM allocation を web notebook 経由で公開する。
ARI run は notebook 内から直接 `sbatch` できないため:

1. Notebook から `python -m ari.viz.server --host 0.0.0.0`
2. 別のターミナルセッション (同じ allocation 内) で
   `ari run experiment.md` を実行。 checkpoint dir は共有
   `/work/...` を指定
3. ウィザードの *再現* step で `sandbox_kind=slurm` と
   `nodes=<allocation>` を設定

## モジュールロード

rubric が `module_loads: ["cuda/12.4","openmpi/4.1"]` を持つ場合、
エージェントは `reproduce.sh` の先頭で `module load cuda/12.4
openmpi/4.1` を発行するよう促される。 ARI はモジュール名を検証しない —
あなたのクラスタの `module avail` が authoritative。

## 失敗モードと回復

| 症状 | 原因 | 対処 |
|---|---|---|
| `sbatch: error: Invalid GRES gpu:v100:1` | GRES 未設定 | `gpu_type` を空に; `--gpus-per-task` のみ使用 |
| compute node で `mpirun: command not found` | OpenMPI が未ロード | `module_loads` に `"openmpi/4.1"` 追加、 OR `srun` に切替 (エージェントプロンプトが優先する) |
| 全 rank がノード 1 に集中 | reproduce.sh に `srun` 無し | エージェントプロンプトの "MULTI-NODE FAN-OUT" block が `srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS` を指示するが、 実際の reproduce.sh にその行があるか確認 |
| rank > 0 でファイル `Permission denied` | `repo_dir` が `/tmp` 上 | checkpoint を `$HOME` または `/work/...` に移す; run log の共有 FS 警告を確認 |

## 関連

- [実行プロファイル仕様](../../reference/execution_profile.md)
- [計算ノード安全規約](compute_node_safety.md)
- [`hpc_setup.md`](../hpc_setup.md) — ARI HPC 設定の基本
