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

# PaperBench マルチノード設定

ARI は標準でシングルノード sandbox (local / apptainer / docker) を
提供する。 マルチノード MPI 再現を追加するには 3 つのサイト前提が必要:

1. **`sbatch` が PATH 上にあること**
2. **GRES (generic resources) 設定済**: rubric が `gpu_type` を要求する
   場合のみ必要。`sinfo -o '%G'` で確認 — `(null)` は GRES 未設定
3. **共有ファイルシステム** (NFS / Lustre / GPFS) が全ノードに同パスで
   マウントされていること。ARI 側にこれを検査する仕組みは無い —
   `repo_dir` がノードローカルでも警告は出ない。唯一の防御は助言的なもので、
   replicator プロンプトが agent に「`reproduce.sh` の全パスは割り当てられた
   全ノードで解決すること」「`/tmp` や `/var/tmp` は決して使わないこと」を
   指示している

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

ARIはpathとresource syntaxを検証するが、mountの共有性やpartitionの能力は
証明できない。compute nodeから見えるfilesystemを使い、事前に`sinfo`を確認する。
resource要求はそのままsubmitされ、黙って削除されない。

## パーティション選択

`ari-skill-paper-re` サーバは SLURM パーティションを次の順で解決する:
明示的 caller 引数 → `ARI_SLURM_PARTITION` env → `SLURM_PARTITION` env →
`launch_config.json` (`repo_dir` の隣、すなわち
`{repo_dir}/../launch_config.json` → `{repo_dir}/launch_config.json` の順に
探す)。どれを設定してもウィザードの既定パーティションが切り替わる。
どれも解決しない場合、`sandbox_kind=slurm` の再現はフォールバックせずに
*"no partition could be resolved"* で失敗する。

`ARI_SLURM_PARTITION` は二役を担う: `sandbox_kind=auto` が `slurm` に
解決されるのは `sbatch` が PATH 上にあり **かつ** `ARI_SLURM_PARTITION` が
設定されているときだけである。`SLURM_PARTITION` と `launch_config.json` は
`auto` 経路を有効にしない。

```bash
export ARI_SLURM_PARTITION=<your-partition>
```

## 例: 匿名の GRES 未設定 GPU partition

物理 GPU はあるがスケジューラの GRES が設定されていないサイトでは、SLURM は
GPU を確実に予約できない。GRES 有効な partition を選ぶか、サイト管理者に
設定を依頼すること。要求を暗黙に CPU へ読み替えてはならない。

```jsonc
"execution_profile": {
  "kind": "gpu_single",
  "paper_max_ranks": 1,
  "requested_gpus_per_task": 1,
  "gpu_type": "v100"
}
```

`run_reproduce` はこのブロックから `requested_gpus_per_task`、
`requested_gpus_per_node`、`gpu_type` を読むが、`--ntasks` は
`paper_max_ranks` ではなく `min_ranks` から取る — `paper_max_ranks` は
agent が読む rubric 側の規模記述であり、スケジューラのフィールドではない。
count が全く無い `gpu_type` は `--gres=gpu:<type>:1` になる。

## 例: notebook 経由の allocation (Web UI, 手動)

login shell ではなくホスト型 Jupyter notebook 経由で SLURM allocation を
公開するサイトがある。ARI run は notebook 内から直接 `sbatch` できないため:

1. Notebook から `ARI_GUI_BIND=0.0.0.0 python -m ari.viz.server`。
   `--host` フラグは存在しない — サーバが取るのは `--checkpoint` と
   `--port` (既定 `8765`) だけで、`ARI_GUI_BIND` で指定しない限り
   loopback (`127.0.0.1` + `::1`) にバインドする (デュアルスタックの
   ワイルドカードは `::`)
2. 別のターミナルセッション (同じ allocation 内) で
   `ari run experiment.md` を実行。 checkpoint dir は共有
   `/work/...` を指定
3. ウィザードの *再現* step で **サンドボックス** の選択を `slurm` に、
   `nodes` を allocation のノード数に設定

## モジュールロード

rubric が `module_loads: ["cuda/12.4","openmpi/4.1"]` を持つ場合、独立に
2 つのことが起こる:

- エージェントは `reproduce.sh` の先頭で `module load cuda/12.4
  openmpi/4.1` を発行するよう促される。
- `sandbox_kind=slurm` の場合、このリストは `JobRequestV1` にも宣言され、
  生成されるバッチスクリプトが module init を source し、
  **`module --force purge`** を実行してから、ペイロードの前に各エントリを
  順に `module load` する。意外なのは purge で、ノード側 (やあなたの sbatch
  ラッパ) が load していたものはまず捨てられる — したがって宣言リストは
  完全でなければならない。module システム自体が無いノードでは、
  module 無しで走らずに `86` で終了する。

ARI はモジュール名を検証しない —
あなたのクラスタの `module avail` が authoritative。

## 失敗モードと回復

| 症状 | 原因 | 対処 |
|---|---|---|
| `sbatch: error: Invalid GRES gpu:v100:1` | GRES 未設定 | `gpu_type` を空に; `--gpus-per-task` のみ使用 |
| compute node で `mpirun: command not found` | OpenMPI が未ロード | `module_loads` に `"openmpi/4.1"` 追加、 OR `srun` に切替 (エージェントプロンプトが優先する) |
| 全 rank がノード 1 に集中 | reproduce.sh に `srun` 無し | replicator プロンプトの "Multi-node fan-out" block が `srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS` を指示するが、 実際の reproduce.sh にその行があるか確認 |
| rank > 0 でファイル `Permission denied` | `repo_dir` が `/tmp` 上 | checkpoint を `$HOME` または `/work/...` に移す。共有 FS 警告をログに出す仕組みは無く、rank 0 だけ成功する失敗が最初のシグナルになる |
| `exit 86` と "requested environment modules are unavailable" | rubric が `module_loads` を宣言したが計算ノードに module システムが無い | `module_loads` を外すか、Lmod / Environment Modules を持つノードの partition を狙う |
| `cpu_bind and mem_bind are srun job-step settings` | `sandbox_kind=slurm` に対してこれらのフィールドを設定した | ウィザードでは空にし、binding は `reproduce.sh` に書く |

## 関連

- [実行プロファイル仕様](../../reference/execution_profile.md)
- [計算ノード安全規約](compute_node_safety.md)
- [`hpc_setup.md`](../hpc_setup.md) — ARI HPC 設定の基本
