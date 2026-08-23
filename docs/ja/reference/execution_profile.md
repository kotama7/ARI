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

# `execution_profile` 仕様

PaperBench ルーブリック (`ari-skill-replicate/schemas/replication_rubric.schema.json`
— `schema_version: ari.replication-rubric/v2`、`version: "3"`) の
`reproduce_contract` 配下にある `execution_profile` オブジェクトは、
論文が要求する並列実行属性 (SLURM 配置、GPU 種、メモリ、NUMA バインド等)
を表現する。`ari-skill-paper-re` がこれを読み、allocationフィールドを
`ari.hpc.job-request/v1`へ変換する。replicatorエージェントは`reproduce.sh`を
生成するとき、このオブジェクト全体をプロンプト中にそのまま受け取る。

シングルCPU論文では `execution_profile` を省略してよい。schedulerは常に
型付きrequest、clean environment、digest、handle lifecycleを使用する。

> **実際に検証しているのは誰か。** JSON schema 検証は `ari-skill-replicate`
> (`generator.py` / `auditor.py`) 側にあり、ルーブリックを生成・監査する
> ときに走る。`ari-skill-paper-re` の `load_rubric` が見るのはエンベロープ
> (バージョン折衝、`rubric_sha256`、`paper_sha256`、TaskNode の形) だけで、
> `execution_profile` に schema を適用せず、schema の `default:` 値も注入
> **しない**。読み出しはすべて `exec_profile.get(field, 0) or 0`
> (または `... or ""`) なので、下表の既定値欄が何であれ、省略した
> フィールドは実行時には `0` / `""` / `False` として振る舞う。これが効いて
> くる箇所が 1 つある: `accepts_reduced_scale` は既定 `true` と文書化されて
> いるが、省略するとエージェントは縮小スケールの指示を一切受け取らない。
> 2 つ目のゲートは型付きの `ResourceRequestV1` で、**変換後** の形が不正な
> ときに拒否する。

## フィールド一覧

| フィールド | 型 | SLURM フラグ | 既定値 | 備考 |
|---|---|---|---|---|
| `kind` | enum | (エージェントプロンプトのみ) | — | `cpu_single` \| `gpu_single` \| `gpu_multi` \| `mpi` \| `mpi_gpu` |
| `paper_max_ranks` | int | — | — | 論文が報告した最大ランク数 |
| `paper_max_nodes` | int | — | — | 論文が報告した最大ノード数 |
| `min_ranks` | int | `--ntasks=N` | 1 | 部分点を許容する最小ランク数。設定時はそのまま要求`--ntasks`になるため、`ntasks_per_node`がこれを超えてはならない (型付きrequestが`tasks_per_node cannot exceed total tasks`で拒否する) |
| `min_nodes` | int | (エージェントプロンプトのみ) | 1 | ノード版。解決コードはこれを読まない — `--nodes` は `requested_nodes` から決まる |
| `result_aggregation` | enum | (エージェントプロンプトのみ) | `rank0_csv` | schema の enum メンバーは `rank0_csv` だけ |
| `metric_columns` | list[str] | — | `[]` | CSV ヘッダ (例: `["nodes","ranks","runtime_sec","gflops"]`) |
| `accepts_reduced_scale` | bool | — | `true` | 縮小再現可否 (true → CSV に `paper_paper_scale_point` 列を追加) |
| `requested_nodes` | int | `--nodes=N` | 0 (未指定) | ヒント。呼出側引数が優先。schema が `minimum: 1` を要求するため `0` と書かずキー自体を省くこと。未指定は `--nodes=1` に変換される |
| `ntasks_per_node` | int | `--ntasks-per-node=N` | 0 | 0 → directive 自体を出力しない。`ntasks` が無いとき総タスク数は `ntasks_per_node × nodes` (無ければ 1) として導出される |
| `requested_nodelist` | str | `--nodelist=...` | `""` | ノード指定 |
| `exclude_nodes` | str | `--exclude=...` | `""` | 除外ノード |
| `exclusive` | bool | `--exclusive` | `false` | 性能再現の忠実度に必須 |
| `requested_gpus_per_task` | int | `--gpus-per-task=[<type>:]N` | 0 | `requested_gpus_per_node` と排他 (schema の `allOf` と `ResourceRequestV1`) |
| `requested_gpus_per_node` | int | `--gres=gpu:[<type>:]N` | 0 | `--gpus-per-node` ではなく `--gres` として、かつ `requested_gpus_per_task` が 0 のときだけ出力される |
| `gpu_type` | str | 型付きGPU selector | `""` | GPU countの一方と組合せ、要求を黙って削除しない — `gpu_type` 単独指定は破棄されず `requested_gpus_per_node=1` に昇格される |
| `memory_gb_per_node` | int | `--mem=<GB×1024>M` | 0 | `memory_gb_per_cpu` と排他 |
| `memory_gb_per_cpu` | int | `--mem-per-cpu=<GB×1024>M` | 0 | `memory_gb_per_node` と排他 |
| `constraint` | str | `--constraint=...` | `""` | 例: `"skylake"`, `"haswell|broadwell"` |
| `cpu_bind` | str | `reproduce.sh`内の`srun --cpu-bind` | `""` | job-step設定。sbatch directiveではない — かつ `run_reproduce` はルーブリックの値を転送しない: 転送するのは自身の `cpu_bind` 引数だけで、SLURM 経路はそれを `cpu_bind and mem_bind are srun job-step settings; place them explicitly in reproduce.sh` で即拒否する。ルーブリックの値は EXECUTION PROFILE ダンプの一部としてのみエージェントに届く |
| `mem_bind` | str | `reproduce.sh`内の`srun --mem-bind` | `""` | `cpu_bind` と同じ扱い |
| `hint` | enum | `--hint=...` | `""` | `""` \| `compute_bound` \| `memory_bound` \| `multithread` \| `nomultithread` |
| `module_loads` | list[str] | clean job prelude | `[]` | 明示loadしprovenanceに記録 |
| `account` / `qos` / `reservation` | str | 各型付きselector | `""` | 任意フラグの代替 |
| `extra_sbatch_args` | list[str] | deprecated readerのみ | `[]` | 新規生成禁止。限定4フィールドだけ互換変換 |

## 自動解決の優先順位

`ari-skill-paper-re.run_reproduce` は各フラグを次のように解決する:

```
明示的な呼出側引数  >  ルーブリックの execution_profile  >  既定値
```

ウィザードの「実行プロファイル上書き」フォームがルーブリックを上書き
できるのはこの順序のため。bool フィールド (`exclusive`) は OR 結合のため、
どちらか有効ならフラグが発行される。

この連鎖には例外が 2 つある:

- `cpu_bind` / `mem_bind` は **呼出側専用**。`run_reproduce` はこれらを
  `execution_profile` から一切参照しない。
- `account` / `qos` / `reservation` / `hint` には最下位の第 4 段があり、
  deprecated な `extra_sbatch_args` から解析された値が使われる。

`partition` はそもそも `execution_profile` の一部ではなく、別系統で解決される
(呼出側引数 → `$ARI_SLURM_PARTITION` → `$SLURM_PARTITION` →
`{checkpoint_dir}/launch_config.json` の `partition`)。`slurm` サンドボックスで
partition が解決できない場合はフォールバックせず hard error になる。

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

`sbatch --parsable --export=NIL`へstdinで渡す生成scriptの主要directive:

```
#SBATCH --partition=large
#SBATCH --nodes=4
#SBATCH --ntasks=32
#SBATCH --ntasks-per-node=8
#SBATCH --exclusive
#SBATCH --gpus-per-task=v100:1
#SBATCH --mem=262144M
#SBATCH --cpus-per-task=8
#SBATCH --constraint=skylake
#SBATCH --hint=nomultithread
#SBATCH --account=projX
#SBATCH --export=NIL
```

このプロファイルが制御するのはここまでの部分集合である。ジェネレータは常に
`--job-name`、`--time`、`--chdir`、`--output`、`--error` も出力し、
`--export=NIL` は無条件である。

`launcher` の既定は `auto` で、`srun` に包むのはシングルタスク・シングル
ノードのペイロードだけである。上記のような 32 ランク要求は **直接** 起動
されるため、並列起動 (`srun -n $SLURM_NTASKS` または
`mpirun -np $SLURM_NTASKS`) は `reproduce.sh` 自身が行わなければならない —
`mpi` / `mpi_gpu` の kind でエージェントがそう書くよう指示されているのは
まさにこのためである。

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
