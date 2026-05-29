---
sources:
  - path: ari-skill-replicate/schemas/replication_rubric.schema.json
    role: schema
  - path: ari-skill-paper-re/src/server.py
    role: implementation
last_verified: 2026-05-25
---

# `execution_profile` 仕様

PaperBench ルーブリック (`ari-skill-replicate/schemas/replication_rubric.schema.json`,
v3) の `reproduce_contract` 配下にある `execution_profile` オブジェクトは、
論文が要求する並列実行属性 (SLURM 配置、GPU 種、メモリ、NUMA バインド等)
を表現する。`ari-skill-paper-re` の Phase 2 sbatch 発行器が読み取り、
呼出側引数で未指定のフィールドを補完して該当 SLURM フラグを発行する。

シングル CPU 論文では `execution_profile` を省略してよい — 全フィールドが
0/""/False/None を既定値とするため、sbatch 呼出は v0.7.2 以前の 4 フラグ
形式に縮退する。

## フィールド一覧

| フィールド | 型 | SLURM フラグ | 既定値 | 備考 |
|---|---|---|---|---|
| `kind` | enum | (エージェントプロンプトのみ) | — | `cpu_single` \| `gpu_single` \| `gpu_multi` \| `mpi` \| `mpi_gpu` |
| `paper_max_ranks` | int | — | — | 論文が報告した最大ランク数 |
| `paper_max_nodes` | int | — | — | 論文が報告した最大ノード数 |
| `min_ranks` | int | `--ntasks=N` | 1 | 部分点を許容する最小ランク数 |
| `min_nodes` | int | — | 1 | ノード版 |
| `result_aggregation` | enum | — | `rank0_csv` | v0.7.2 は `rank0_csv` のみ |
| `metric_columns` | list[str] | — | `[]` | CSV ヘッダ (例: `["nodes","ranks","runtime_sec","gflops"]`) |
| `accepts_reduced_scale` | bool | — | `true` | 縮小再現可否 (true → CSV に `paper_paper_scale_point` 列を追加) |
| `requested_nodes` | int | `--nodes=N` | 0 | ヒント。呼出側引数が優先 |
| `ntasks_per_node` | int | `--ntasks-per-node=N` | 0 | 0 → SLURM 任せ |
| `requested_nodelist` | str | `--nodelist=...` | `""` | ノード指定 |
| `exclude_nodes` | str | `--exclude=...` | `""` | 除外ノード |
| `exclusive` | bool | `--exclusive` | `false` | 性能再現の忠実度に必須 |
| `requested_gpus_per_task` | int | `--gpus-per-task=N` | 0 | |
| `requested_gpus_per_node` | int | `--gpus-per-node=N` | 0 | |
| `gpu_type` | str | `--gres=gpu:<type>:N` | `""` | gpus_per_task と組合せ。`sinfo` で GRES 未設定の場合は自動で省略 |
| `memory_gb_per_node` | int | `--mem=NG` | 0 | |
| `memory_gb_per_cpu` | int | `--mem-per-cpu=NG` | 0 | |
| `constraint` | str | `--constraint=...` | `""` | 例: `"skylake"`, `"haswell|broadwell"` |
| `cpu_bind` | str | `--cpu-bind=...` | `""` | 例: `"cores"`, `"sockets"`, `"rank"` |
| `mem_bind` | str | `--mem-bind=...` | `""` | 例: `"local"`, `"nearest"` |
| `hint` | str | `--hint=...` | `""` | 例: `"nomultithread"` |
| `module_loads` | list[str] | (reproduce.sh 冒頭) | `[]` | エージェントが `module load` する一覧 |
| `extra_sbatch_args` | list[str] | (連結) | `[]` | 上記で表せないフラグの escape hatch (例: `["--account=projX"]`) |

## 自動解決の優先順位

`ari-skill-paper-re.run_reproduce` は各フラグを次のように解決する:

```
明示的な呼出側引数  >  ルーブリックの execution_profile  >  既定値
```

ウィザードの「実行プロファイル上書き」フォームがルーブリックを上書き
できるのはこの順序のため。bool フィールド (`exclusive`) は OR 結合のため、
どちらか有効ならフラグが発行される。

## HPC フル例 (MPI + GPU)

TS-SpGEMM スケーリング (4 ノード × 8 ランク × V100×1 task, exclusive,
Skylake 限定) の忠実再現:

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

発行される sbatch:

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

## シングル GPU 例

```jsonc
"execution_profile": {
  "kind": "gpu_single",
  "paper_max_ranks": 1,
  "metric_columns": ["throughput_GB_s", "PSNR_dB"]
}
```

エージェントのプロンプトは CUDA / PyTorch CUDA / cupy 利用を促す。
SLURM 配置はパーティション既定値に戻る。

## シングル CPU 例

```jsonc
// execution_profile を完全に省略 → 従来のシングルノード挙動
"reproduce_contract": {
  "script_path": "reproduce.sh",
  "max_runtime_sec": 1800,
  "expected_artifacts": ["results.csv"]
}
```

## 関連

- [PaperBench クイックスタート](../guides/paperbench/paperbench_quickstart.md)
- [マルチノード設定](../guides/paperbench/multi_node_setup.md)
- [計算ノード安全規約](../guides/paperbench/compute_node_safety.md)
- スキル実装: `ari-skill-paper-re/src/server.py:run_reproduce`
- Schema: `ari-skill-replicate/schemas/replication_rubric.schema.json`
