---
sources:
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/contracts.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/slurm.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/counters.py
    role: implementation
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-hpc/skill.yaml
    role: config
  - path: ari-skill-hpc/tests/test_server.py
    role: test
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
  - path: ari-skill-idea/src/server.py
    role: implementation
  - path: ari-skill-benchmark/src/server.py
    role: implementation
  - path: ari-skill-benchmark/mcp.json
    role: config
  - path: ari-skill-evaluator/src/server.py
    role: implementation
  - path: ari-skill-evaluator/mcp.json
    role: config
  - path: ari-skill-memory/src/server.py
    role: implementation
  - path: ari-skill-memory/mcp.json
    role: config
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/mcp.json
    role: config
  - path: ari-skill-paper/src/server.py
    role: implementation
  - path: ari-skill-paper/mcp.json
    role: config
  - path: ari-skill-plot/src/server.py
    role: implementation
  - path: ari-skill-plot/mcp.json
    role: config
  - path: ari-skill-replicate/src/server.py
    role: implementation
  - path: ari-skill-replicate/mcp.json
    role: config
  - path: ari-skill-transform/src/server.py
    role: implementation
  - path: ari-skill-transform/mcp.json
    role: config
  - path: ari-skill-vlm/src/server.py
    role: implementation
  - path: ari-skill-vlm/mcp.json
    role: config
  - path: ari-skill-web/src/server.py
    role: implementation
  - path: ari-skill-web/mcp.json
    role: config
  - path: ari-core/tests/fixtures/contracts/mcp_tools.json
    role: test
last_verified: 2026-08-17
---

# Capability Provider パッケージ（`ari-skill-*` は互換名）

歴史的に「Skills」と呼ばれてきたパッケージは、MCP で接続される実行可能な
**Capability Provider** です。Knowledge Skill ではありません。MCP は Provider の
transport / discovery protocol であり、ここに列挙する各ツールは Provider の原子的
operation です。ツールは可能な限り決定論的で、LLM を使う operation には明示的に
注記があります。ディスク上の `skill.yaml`、`SkillManifestV1`、`SKILLS.lock` は
Provider manifest と run snapshot の互換名のまま残ります。`provider.yaml` や
`PROVIDERS.lock` は並行して存在しません。

非実行の Knowledge Skill と独立した Harness は
[Knowledge、Capability、Scientific Assurance](knowledge_capability_assurance.md)
にまとめてあります。既定 OFF の `ari-skill-knowledge` / `ari-skill-harness` が公開
するのは read / query と非権威的な request operation だけで、どちらもカタログの
管理権限も固定解決の権限も与えません。この 2 つと `ari-skill-tool-registry` には
このページに narrative セクションがありません — ツール一覧は
[mcp_tools.md](mcp_tools.md)、registry のカタログ identity と provider adapter は
[tool_registry.md](tool_registry.md) にあります。

このページが扱うのは **14 パッケージ** — `ari-core/config/workflow.yaml` の
`skills:` が既定で登録する 13 と、外部クライアント向けに別プロセスで起動する
`ari-skill-orchestrator` です。v0.7.0 で PaperBench 形式の再現性フロー用に
`ari-skill-replicate` が追加されました。

各スキルの登録済みツール名は `mcp.json`（`skill.yaml` から生成）と
`src/server.py` の `@mcp.tool()` / `@server.list_tools()` が正であり、両者の一致は
`scripts/check_skill_manifests.py` が、スキルごとの一覧は
`ari-core/tests/fixtures/contracts/mcp_tools.json` のスナップショットが固定します。

## ari-skill-hpc

型付きの SLURM ライフサイクル、厳格な SSH transport、能力プローブ、digest で固定
したコンテナ。**LLM: No**（完全に決定論的）。

ツールは 10 個で、3 つの系統に分かれます。型付きの投入 2 つ（`job_submit` /
`container_submit`）と保持されているバッチスクリプトブリッジ（`slurm_submit`）、
同じハンドルセレクタを共有するライフサイクル操作 4 つ（`job_status` /
`job_result` / `job_logs` / `job_cancel`）、そしてプローブ 3 つ
（`probe_platform_capabilities` / `counter_support` / `measure_counters`）です。
コンテナを決めるのはツールの選択ではなく、リクエストが運ぶ digest 固定の
`ContainerRequestV1` です。`container_submit` はそのフィールドを必須にしただけの
同じ投入であり、まったく同じ入力スキーマを宣言する `job_submit` も、コンテナを
宣言したリクエストを受け付けて同一の経路で実行します（必須にしないだけです）。
イメージの build / pull / run コマンドはこのパッケージには存在しません。

### ツール

#### `job_submit(request)`

不変の `JobRequestV1` を 1 件投入し、冪等な `JobHandleV1` を即座に返します。引数は
リクエストを包んだ `request` ただ 1 つです（JSON Schema の参照をルートにまとめる
ための入れ物）。コマンドは argv 配列で渡し、ログインノードのシェルは一切経由しま
せん。バッチスクリプトを渡す経路はコアエージェント向けの互換ブリッジである下の
`slurm_submit` で、新しくプログラムから呼ぶ側は `job_submit` を使います。

`JobRequestV1` の必須項目は `request_id` / `job_name` / `work_dir`（実在する非
シンボリックリンクの絶対ディレクトリ）/ `argv` / `resources` で、`environment`、
`container`、`accelerator_allocation`、`inputs`、`outputs`、`metadata` は任意です。
`resources`（`ResourceRequestV1`）は `slurm_submit` と同じ `partition` /
`nodes=1` / `tasks=1` / `tasks_per_node=None` / `cpus_per_task=1` /
`walltime="01:00:00"` / `launcher="auto"` の形状に加えて、`memory_mb_per_node` /
`memory_mb_per_cpu` / `gpus_per_node` / `gpus_per_task` / `gpu_type` /
`nodelist` / `exclude_nodes` / `exclusive` / `constraint` / `hint` / `account` /
`qos` / `reservation` を宣言できます。

`environment`（`EnvironmentPolicyV1`）は `export_mode` を `NIL` に固定します。
ジョブから見えるのはここに明示した非機密のリテラルと `modules` だけで、名前が
credential らしい変数（`*_TOKEN` / `*_PASSWORD` / `*_API_KEY` など）はリクエスト
に埋め込まれるのではなく拒否されます。

投入は `sbatch --parsable --export=NIL` で行われ、リクエストは正規化 JSON の
sha256（`request_digest`）で同定されます。この digest は `sbatch` の前に ledger へ
記録されるので、同じリクエストを送り直しても 2 つ目のジョブは作られず既存のハンド
ルが返ります。投入結果が不明なまま transport が落ちた場合も claim は残るため、
リトライが重複投入になりません。

`inputs` の各ファイルは投入時点で宣言された sha256 とサイズに一致しなければならず、
ペイロードが走り出す前にノード上でもう一度照合されます。`outputs`
は `work_dir` の下に留まる必要があります（シンボリックリンクは拒否）。ジョブごとの
成果物は `{work_dir}/.ari-hpc/` の下、`request_digest` から `sha256:` を外した 16 進
を名前とするディレクトリ（ハンドルの `artifact_scope`）に置かれます。

```python
result = job_submit(request={
    "request_id": "bench_001",
    "job_name": "bench_test",
    "work_dir": "/abs/path/to/workdir",
    "argv": ["./bench", "--threads", "32"],
    "resources": {"partition": "your_partition", "cpus_per_task": 32},
})
# 戻り値: {"schema_version": "ari.hpc.job-handle/v1", "handle_id": "hpc-...",
#          "request_digest": "sha256:...", "job_id": "12345",
#          "state": "submitted", ...}
```

#### `container_submit(request)`

`job_submit` と同じライフサイクル、同じ引数スキーマですが、`request.container` の
宣言が必須です（無ければ validation エラー）。`ContainerRequestV1` は `runtime`
（`apptainer` 既定 / `singularity`）、`image`（絶対パスと `sha256:…` digest・
バイト数で固定した `ArtifactPinV1`）、`binds`（既定は読み取り専用、target の重複は
不可）、`gpu`（既定 `false`）、`network`（`host` 既定 / `none`）、`contain_all`
（既定 `true`）、`clean_environment`（既定 `true`）を取ります。イメージは digest で
固定されるので、中身が入れ替わったイメージは投入前の照合でも、ノード上の再照合でも
拒否されます。コンテナ実行では `inputs` も `work_dir` か宣言された bind の下に無け
ればなりません。`work_dir` 自身は、リクエストが明示していなければ読み書き可能な
bind として自動的に追加されます。

#### `slurm_submit(script, job_name, partition, nodes=1, tasks=1, tasks_per_node=None, cpus_per_task=1, launcher="auto", walltime="01:00:00", work_dir, modules=[])`

SLURM バッチジョブを投入します。

**ノードを複数確保しただけでは複数ノードを使ったことになりません。** バッチ
本体は最初のノードでのみ実行され、並列ステップを起動する何かがなければ残りは
遊んだままです。それを誰が起動するかを決めるのが `launcher` です。

| `launcher` | スクリプトの起動され方 | 使う場面 |
|---|---|---|
| `auto`（デフォルト） | 記述どおりそのまま | スクリプト自身が `srun` / `mpirun` を呼ぶ、または逐次実行 |
| `srun` | 宣言された `nodes` / `tasks` / `cpus_per_task`（宣言があれば `--ntasks-per-node` も）で `bash -c <script>` を `srun` 起動 | スクリプト自体が並列プログラム（MPI / SPMD） |
| `none` | 記述どおりそのまま | ペイロードにバッチステップを一切触らせない |

したがってここでは `auto` と `none` はノード上で同じものになります。bridge の
本体はスクリプトであり、包むのは `srun` だけです。`auto` による CPU 束縛は
typed な `job_submit` / `container_submit` 側の話で、そちらはペイロードが
`argv` であり、1 ノード 1 タスクの要求は `srun --ntasks=1 --cpus-per-task=N`
として起動されます。この束縛があるのは、バッチステップがノード全体の affinity
mask を継承するためです。そうしないとスレッド化されたペイロードがマシン全体へ
広がり、自分自身の逐次ベースラインに負けることさえあります。これは束縛されて
いない allocation ではなく遅い kernel として読めてしまいます。

`launcher="srun"` を自前の launcher と併用しては**いけません**。
`srun --ntasks=8 mpirun -np 8 ./x` は 64 ランクであり、下流の誰もそれを正しい
run と区別できません。`tasks > 1` から推論せず明示的に宣言させるのはこのため
です。2 種類のマルチタスク要求は scheduler からは区別できません。

起動モードと allocation の形状はどちらもリクエスト digest の一部なので、同じ
スクリプトでも形状や launcher が違えば最初の run への cache hit ではなく別の
ジョブになります。

```python
result = slurm_submit(
    script="""
#!/bin/bash
gcc -O3 -fopenmp -o ./bench ./bench.c
OMP_NUM_THREADS=32 ./bench
""",
    job_name="bench_test",
    partition="your_partition",
    cpus_per_task=32,
    work_dir="/abs/path/to/workdir"
)
# 戻り値: {"schema_version": "ari.hpc.job-handle/v1", "handle_id": "hpc-...",
#          "job_id": "12345", "state": "submitted", "status": "submitted",
#          "message": "Job 12345 submitted successfully",
#          "request_digest": "sha256:...", "submission_digest": "sha256:..."}
```

**注意事項:**
- `script` の中に書いた `#SBATCH` ディレクティブは効きません。生成されたヘッダーの
  直後に実行可能な行が続くため、`sbatch` は本体を読む前にディレクティブの解釈を
  打ち切ります。形状は引数（`nodes` / `tasks` / `cpus_per_task` / `walltime`）で
  宣言してください
- 投入が拒否された場合は例外ではなく
  `{"job_id": "", "status": "error", "message": ..., "partition": ...}` が返ります
- 本体は `set -euo pipefail`・`PATH=/usr/local/bin:/usr/bin:/bin`・
  `LANG` / `LC_ALL=C.UTF-8` の下で、`BASH_ENV ENV CDPATH GLOBIGNORE PYTHONHOME
  PYTHONPATH VIRTUAL_ENV` を unset した状態で走ります。投入元のシェルからは何も
  引き継がれないので、パスは絶対パスで書き、ツールチェインは `modules` 経由で
  取得してください

#### `job_status(handle_id)`

ARI のハンドルまたは生の SLURM ジョブ ID について、provider 中立な `JobStatusV1`
を返します。

`job_status` / `job_result` / `job_logs` / `job_cancel` はいずれも同じセレクタ
スキーマを取り、`handle_id`（`JobHandleV1` のハンドル ID、推奨）か `job_id`
（生の SLURM ジョブ ID、レガシー互換）のどちらか一方だけを要求します。この
「ちょうど一方」は schema の description に書かれ、サーバ側の `_selector` で
強制されます — トップレベルの `oneOf` には**していません**。OpenAI の
function-calling schema サブセットが `oneOf` を持つツールを拒否し、4 つとも
advertise 不能になったためです。どちらも渡さない呼び出しは拒否され、実装は
`handle_id` を先に読むので、両方渡した場合はハンドルが使われます。
既知のハンドルでも数字だけの SLURM ジョブ ID でもないセレクタは validation
エラーです。

状態は `sacct -j <id> --noheader --parsable2 --allocations
--format=JobID,State,ExitCode,Start,End,Reason` から読み、accounting にまだ記録が
無い場合は `squeue -j <id> --noheader --format=%T|%R` にフォールバックします。

```python
result = job_status(handle_id="hpc-...")
# 戻り値: {"schema_version": "ari.hpc.job-status/v1", "handle_id": "hpc-...",
#          "job_id": "12345", "state": "succeeded",
#          "scheduler_state": "COMPLETED", "exit_code": 0,
#          "start_time": ..., "end_time": ..., "reason": None}
```

`state` は正規化された provider 中立の値で、`submitted` / `running` /
`succeeded` / `failed` / `cancelled` / `unknown` のいずれかです。SLURM 自身の語は
`scheduler_state` に残ります。`PENDING` / `CONFIGURING` / `REQUEUED` /
`RESIZING` / `SPECIAL_EXIT` は `submitted` に、`RUNNING` / `COMPLETING` /
`SUSPENDED` / `STAGE_OUT` は `running` に、`COMPLETED` は `succeeded` に、
`CANCELLED`（`CANCELED` 綴りも）/ `DEADLINE` / `REVOKED` は `cancelled` に、
`BOOT_FAIL` / `FAILED` / `NODE_FAIL` / `OUT_OF_MEMORY` / `PREEMPTED` /
`TIMEOUT` は `failed` に正規化されます。scheduler がジョブについて何も答えない
場合は `state: "unknown"` / `scheduler_state: "UNKNOWN"` になります。これは
エラーではなく、証拠が無いことの記録です。

`ERROR` という状態はありません。呼び出しが失敗したときは
`{"error": {"kind": ..., "message": ..., "retryable": ...}}` というエラー封筒が
返り、`kind` は `validation` / `transport` / `scheduler` / `unknown` のいずれか
です。`message` は credential らしき文字列を伏せてから返されます。

#### `job_result(handle_id)`

終端状態に達したジョブから `JobResultV1` を収集し、宣言された inputs / outputs と
ログを再ハッシュします。セレクタは `job_status` と同じです。

対象のジョブは ARI 経由で投入されていて（ledger の記録とハンドルが要ります）、
かつ typed なリクエストを伴っている必要があります。`slurm_submit` ブリッジで
投入したジョブは status と logs は取れますが、typed な `JobResultV1` は返せません。
終端状態（`succeeded` / `failed` / `cancelled`）に達する前に呼ぶのは validation
エラーです。

宣言された `inputs` を sha256 とサイズで再検証し、`outputs` を実ファイルから再
ハッシュして `ArtifactPinV1` に固定し、ログと provenance（submission record、
実行環境の記録、module snapshot、コンテナランタイムのバージョン、exit code、
リクエストが宣言していれば exclusive allocation と accelerator inventory の
witness）を添えます。`required: true` の output が欠けている場合は例外ではなく
`error.kind = "artifact"` として結果に記録されます。`succeeded` 以外の終端状態で
終わったジョブは `error.kind = "execution"` を持ち、`NODE_FAIL` / `PREEMPTED` /
`REQUEUED` のときだけ `retryable` が立ちます。

返る `JobResultV1` は `request_digest` / `environment_digest` / `module_digest` に
加えて、該当する場合は `module_snapshot_digest` / `container_digest` /
`accelerator_allocation_digest` / `accelerator_inventory_digest` を持ち、残り全体を
封じる `result_digest` で締められます。同じ記録がハンドルの `artifact_scope` 直下の
`result-v1.json` にもアトミックに書き出されます。

#### `job_logs(handle_id)`

ARI 経由で投入したジョブの stdout / stderr を、境界付き・digest 付きで返します。
セレクタは `job_status` と同じで、こちらも ARI 経由で投入したジョブにしか使えま
せん。

```python
result = job_logs(handle_id="hpc-...")
# 戻り値: {"schema_version": "ari.hpc.job-logs/v1", "logs": [...]}
```

各エントリは `stream`（`stdout` / `stderr`）・`path`・`digest`・`size_bytes`・
`text`・`truncated` を持ちます。`text` は 1 MiB（1,048,576 バイト）で打ち切られ、
その場合 `truncated: true` になります。打ち切りが目に見えるので、途中までの出力が
完全な出力として通ることはありません。`digest` と `size_bytes` は、共有ファイル
システム上でログを直接読める場合はファイル全体に対する値です。共有でない transport
越しに読む場合はログもその transport を通って返るため、`digest` と `size_bytes` も
同じ 1 MiB の範囲を指します。ログはハンドルの `artifact_scope` にある
`slurm-{job_id}.out` / `.err` から読み、存在しないストリームは省かれます。通常の
ファイルかどうかの検査は共有ファイルシステム経路のものです。そちらではログを
`lstat` し、通常ファイルでないものやシンボリックリンクを安全でないとして拒否します。
共有でない transport では runner 越しにパスを読むため、この検査は行えません。

#### `job_cancel(handle_id)`

ARI または SLURM のジョブにキャンセルを要求します。セレクタは `job_status` と
同じです。

```python
result = job_cancel(handle_id="hpc-...")
# 戻り値: {"schema_version": "ari.hpc.job-cancel/v1", "handle_id": "hpc-...",
#          "job_id": "12345", "status": "cancel_requested"}
```

名前のとおり、これは `scancel` が要求を受け付けたという事実であって、ジョブが
止まったという事実ではありません。scheduler 自身の言い分は `job_status` を
ポーリングして確かめます（キャンセルされたジョブは `state: "cancelled"` と
読めます）。`scancel` 自体が拒否された場合は `kind: "scheduler"` のエラー封筒が
返ります。

#### `probe_platform_capabilities(checkpoint_dir, partition="", tools="")`

**計算パーティション上**でツールの有無（`command -v`）を調べ、結果を
`{checkpoint_dir}/platform_capabilities.json` にキャッシュします。`tools` は
カンマ区切りのリストで、既定は `ARI_PROBE_TOOLS`、それも無ければ
`perf,numactl,papi_avail,likwid-perfctr,valgrind` です。`partition` が空の場合は
`ARI_SLURM_PARTITION` にフォールバックします。

プローブが走った場合は `{"status": "probed", "partition": ..., "arch": ...,
"available": {"perf": true, ...}}` が返り、`available` は調べた各ツール名を真偽値に
対応づけます。プローブは走ったがキャッシュを書けなかった場合は同じレコードが
`{"status": "unsaved", "reason": ..., ...}` として返ります。有効な既存キャッシュが
あれば再プローブせず `{"status": "cached", ...}` を返します。設計上ベストエフォート
で、失敗（パーティション未指定、`srun` 不在、キュー待ちのタイムアウト）時は
`{"status": "skipped", "reason": ...}` を返して何も書きません。claims 抽出器は
このキャッシュを読み、プラットフォームに実在しないツールに依存する証拠を宣言
しないようにします。

#### `counter_support()`

このノードがハードウェアカウンタを許可するかを、プロファイラのバイナリを探すので
はなく実際に 1 つ開いて確かめます。引数はありません。`perf` が無くてもカウンタを
許すノードがあり、`perf` があっても拒むノードがあり、ベンダ製プロファイラの置き場
はサイト依存です。`perf_event_open` を直接呼べば、そのノードが走っているコンテナ
の中で実際に効く kernel のポリシーを観測できます。

```python
result = counter_support()
# 戻り値: {"schema_version": "ari.hpc.counter-support/v1", "architecture": "...",
#          "perf_event_paranoid": ..., "reviewed_events": [...],
#          "status": "ready", "detail": None}
```

`status` は、自己プローブが開けたときは `ready`、`EACCES` / `EPERM` で拒まれた
ときは `denied`、そのアーキテクチャに審査済みの `perf_event_open` システムコール
番号が無いか自己プローブがそれ以外の理由で失敗したときは `unsupported`、Linux
以外のホストでは `unavailable` になります。

#### `measure_counters(pid, window_ms=1000, events=["cycles", "instructions"])`

既に走っているプロセスの審査済みハードウェアイベントを、境界付きウィンドウで計数
します。これは実行ではなくプロファイリングで、プロセスを生成せず、何も書かず、
credential も要求しません。

- `pid` は必須で、実際に走っているプロセスを指す必要があります
- `window_ms` は 1〜60000（`MAX_WINDOW_MS`）、既定は 1000 です
- `events` は審査済み集合 `branch-instructions` / `branch-misses` /
  `cache-misses` / `cache-references` / `cycles` / `instructions` からの選択で、
  既定は `["cycles", "instructions"]` です。この集合の外にあるイベント名は素通し
  されずに拒否されるため、呼び出し側が任意の raw event encoding に到達すること
  はありません

カウンタは考えうる最小の権限（`exclude_kernel` / `exclude_hv`）で開かれるので、
拒否されたときに表れるのは過剰な要求ではなくポリシーそのものです。戻り値の
`excluded: ["kernel", "hypervisor"]` がそのことを記録します。

```python
result = measure_counters(pid=12345, window_ms=2000)
# 戻り値: {"schema_version": "ari.hpc.counter-measurement/v1", "status": "measured",
#          "support": {...}, "pid": 12345, "window_seconds": 2.000123,
#          "counters": {"cycles": ..., "instructions": ...},
#          "excluded": ["kernel", "hypervisor"]}
```

`counter_support()` が `ready` でない場合、または対象の pid でカウンタを開けなかっ
た場合は、`counters` が空のまま `status` に `denied` / `unavailable` /
`unsupported` が入り、`support` の記録がそのまま添えられます。

このツールは `skill.yaml` で `context_requirement: node` を宣言する唯一の HPC ツール
なので、入力スキーマに `ari_context` オブジェクトプロパティを持ちます。context 要件
を持つツールにはこの名前で認可済みのノードコンテキストが transport から注入される
ため、`additionalProperties: false` でありながらこれを宣言しないスキーマは、認可さ
れた呼び出しをすべて拒否してしまいます。proxy は `tools/list` からこのプロパティを
取り除き、`tools/call` では上書きするので、エージェントが渡す引数になることは
ありません。

---

## ari-skill-idea

文献調査とアイデア生成。**LLM: Yes**（generate_ideas は VirSci マルチエージェント討論を使用）。

### ツール

#### `survey(topic, max_papers=8, mode="record", snapshot_path="survey_snapshot_v1.json", provider="semantic-scholar")`

先行研究調査。決定論的（LLM なし）。provider は**チェーンではなく pin**
されます: `provider` が受け付けるのは `semantic-scholar` と
`virsci-snapshot` だけで、それ以外は raise します。したがって `record` /
`live` の呼び出しが障害中にバックエンドを切り替えることはなく、コーパスが
黙って別物になることもありません。`virsci-snapshot`（または
`mode="frozen"`）は凍結コーパスが無ければネットワークに退避せず
`FileNotFoundError` を、Semantic Scholar は HTTP エラー時に他 provider へ
退避せずそのまま raise します。**arXiv フォールバックはありません**。`mode`
は `record` / `live` / `replay` / `frozen` で、`replay` はネットワークに
一切アクセスせず、`snapshot_path` が指す checkpoint artifact が無い、または
digest が検証できない場合は失敗します。Semantic Scholar 経路では上位 3 件を
それぞれ最大 3 件の被引用論文で 1 ホップだけエンリッチし、保持されたレコード
間のエッジのみを残します。戻り値は `papers`（レガシー projection）、
`survey_snapshot`（`SurveySnapshotV1`）、`survey_snapshot_digest`、
`execution_mode` です。

```python
result = survey("OpenMP compiler optimization HPC benchmarks")
# 戻り値: {"papers": [{"title": "...", "abstract": "...", "url": "..."}]}
```

高レートリミットには `S2_API_KEY` 環境変数を設定します。`max_papers` は
15 が上限です。

このスキルの登録済み MCP ツールは `survey` / `generate_ideas` /
`mint_contract_for_proposal` の 3 つで、`mcp.json` もその 3 つだけを列挙します。
`_load_virsci_snapshot_papers` は `survey` が直接呼ぶただのヘルパーで、
エージェントから見えてはなりません。`tests/test_server.py` は
`mcp.list_tools()` 経由で `survey` / `generate_ideas` の登録と、このヘルパーが
ツールでないことをピン留めしています（`@mcp.tool()` デコレータの欠落・
付け間違いが過去に出荷されたためです）。

#### `generate_ideas(topic, papers, experiment_context="", n_ideas=3, n_agents=4, max_discussion_rounds=2, max_recursion_depth=0, survey_snapshot=None, survey_snapshot_ref="", seed=None, generation_mode="auto")`

VirSci マルチエージェント LLM 討論を使用して研究仮説を生成します。複数の AI ペルソナ（researcher、critic、expert、synthesizer）が研究課題について議論します。デフォルトの `simple_bfts` モードでは、BFTS 開始前に**一度だけ**呼び出されます（pre-BFTS のみ）。オプトインの `ari_rqgm` モードで `proposal_router.generators.virsci.enabled: true` のとき、コア側の `VirSciAdapter` が加えて、ProposalRouter のイベントトリガかつ予算上限付きのディスパッチを通じて `survey` + `generate_ideas` を呼びます — [VirSci 統合](../guides/virsci_integration.md)を参照。

モデル: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`。

文献入力は最初のモデル呼び出しの前に凍結されます。`survey` が返した
`SurveySnapshotV1` オブジェクトそのもの（`survey_snapshot`）、検証済み
snapshot への checkpoint 相対参照（`survey_snapshot_ref`。`ARI_CHECKPOINT_DIR`
が必要で、インラインの文献リストとの併用は raise）、あるいはレガシーな
インライン `papers` リストのいずれかを渡します。3 つとも空の場合は、他
provider へフォールバックせず pin された Semantic Scholar の record 操作を
1 回だけ行います。`seed` は generation lock に記録されます。
`generation_mode` は `auto` / `default` / `virsci` で、それ以外は raise し、
明示的な `virsci` は re-impl ループへ退避せず fail closed します。`n_ideas`
は 1–5、`n_agents` は 2–4、`max_discussion_rounds` は 0–3 に clamp され、
`max_recursion_depth` は再帰オーケストレーション用の予約（現状未使用）です。

#### VirSci-live (vendor-wrap) — opt-in の実エンジン

`generate_ideas` には同一のアイデア契約の背後に切替可能な 2 つのエンジンがあります。
デフォルト（**reimpl**、挙動は従来どおり）は軽量に再実装した討論ループを走らせます。
opt-in（**real_wrap**）は代わりに VirSci の *実際の* 機構 —
同梱（**無改変**）の `vendor/virsci` の `Platform.select_coauthors`（freshness な
チーム編成）+ `Team.generate_idea`（マルチエージェント討論）— を、**ライブ**の
Semantic Scholar スナップショット（コーパス + SPECTER2 コサイン検索インデックス
+ 著者プロファイル + 共著グラフ）の上で実行します。

- **デフォルト OFF** = 挙動はバイト単位で従来と同一。有効化は env
  `ARI_IDEA_VIRSCI_REAL=1`、CLI フラグ `--virsci-live`、または GUI 実験ウィザードの
  「VirSci live」トグル（Scope/Resources ステップ。`launch_config.json` に永続化）。
- **安全にデグレード。** 依存が無い場合（`virsci` pip extra 不在）や任意の実行時
  エラー時は reimpl ループにフォールバックします。`idea.json` 契約はどちらの経路でも同一です。
  さらに、ライブスナップショットの構築は **空の / 0 件の S2 取得で明示的に失敗** します
  （429 レート制限・ネットワーク障害・検索ヒット無し）。プレースホルダ著者付きの「成功した」
  0 件マニフェストを黙って書き出すと、VirSci がまったく接地されないまま走り `real_wrap` 成功として
  記録されてしまうため、そうはせず例外を送出し、`generate_ideas` が reimpl ループへ **可視的に**
  デグレードするようにします。`n_papers == 0` のキャッシュ済みマニフェストは汚染キャッシュとして扱われ、
  再利用されません（再構築されます）。トピックの `/paper/search` がスロットリングされた（S2 429）が
  survey が既に検証済みの paperId を持っている場合は、`/paper/batch`（id 指定なので狙いが定まり
  スロットリングされにくい）でシードコーパスを取得して復帰し、これを
  `virsci_snapshot/snapshot_manifest.json` の `seed_fallback` に記録します。
- **経路の報告。** `idea.json` に `virsci_integration_status` を記録: vendor エンジンが
  走ったときは `"real_wrap"`、reimpl ループを使ったときは（理由付きで）`"reimpl: …"`。
- **LLM:** 討論は phase ごとの Idea モデル（`ARI_MODEL_IDEA`）に従います。エンジン呼び出しは
  litellm 経由なので ARI の cost tracker が捕捉します。
- **スコープ:** 単一のライブスナップショットのみ — era 分割なし / paper-parity なし
  （これらは VirSci の遡及ベンチマーク用の成果物でありスコープ外）。freshness/diversity は
  S2 の著者プロファイル + 共著グラフに由来します。
- **依存:** `virsci` pip extra（faiss-cpu, transformers, torch, loguru, sqlalchemy）。
  SPECTER2 重みは実行時に取得。`SEMANTIC_SCHOLAR_API_KEY` / `S2_API_KEY`
  （`embedding.specter_v2` 用）と OpenAI 互換の LLM エンドポイント（ARI CLI シム）が必要。

環境変数（必須はトグルのみ、残りは調整可能 —
[環境変数](environment_variables.md)を参照）:

| 変数 | デフォルト | 用途 |
|---|---|---|
| `ARI_IDEA_VIRSCI_REAL` | 未設定 (off) | real vendor-wrap 経路の切替 |
| `ARI_IDEA_VIRSCI_K` | `7` | 討論ターン数（vendor `group_max_discuss_iteration`） |
| `ARI_IDEA_VIRSCI_TEAM_SIZE` | `3` | チーム最大人数（vendor `max_teammember`） |
| `ARI_IDEA_VIRSCI_N_AUTHORS` | `16` | `select_coauthors` の著者プール |
| `ARI_IDEA_VIRSCI_N_PAPERS` | `800` | SPECTER2 検索コーパスサイズ |
| `ARI_IDEA_VIRSCI_MAX_TEAMS` | `n_ideas` | `generate_idea` に投入するチーム数の上限 |
| `ARI_IDEA_VIRSCI_SPECTER2_MODEL` | `allenai/specter2_base` | ローカルのクエリ埋め込み器 |

`ari run` の CLI フラグ: `--virsci-live` / `--no-virsci-live`、`--virsci-k`、
`--virsci-team-size`、`--virsci-n-authors`、`--virsci-n-papers`。

#### `mint_contract_for_proposal(topic, proposal, survey_snapshot_ref="survey_snapshot_v1.json", experiment_context="")`

このスキルが**生成していない**提案に対して、型付きの Research Contract を mint
します。mint を生成から切り離してあるのは、`ari.mode: ari_rqgm` では proposal
router がルートの ideation を所有し、そのどの generator も契約を mint しない一方で、
KCA の admission には契約が必要だからです。title / description / hypothesis / plan は
提案側が与え、このステップが run の検証済み文献スナップショットから反証条件・
limitations・引用・metric contract を与えます。それらを捏造せず拒否するので、
`ARI_CHECKPOINT_DIR` が無い、スナップショットが利用できない、提案に title が無い
場合は `{"contract_status": "rejected", "reason": ...}` が返ります。成功時は
`typed_schema_version`、`contract_status: "admitted"`、`research_contract`、その
`research_contract_digest`、`idea_set_digest`、および `rejections` を返します。

---

## ari-skill-evaluator

メトリクス契約の materialize、決定論的な主張ゲート、証拠に基づくセマンティック
査読。**LLM: Split** — 契約に関わる 2 ツールは、*決める*ほうが決定論的で、
*推測する*ほうが自分の推測を admit できないように分離してあります。

### ツール

#### `make_metric_spec(experiment_text, checkpoint_dir="", proposal_json=None, reviewer="")`

不変の契約から MetricSpec を **決定論的に** materialize します。**LLM なし**。
実験 Markdown からは `metric_keyword` / `min_expected_metric` / `success metrics` を
パースして `parser_result` に入れますが、これは証拠であって契約ではありません。

契約の解決順序は次のとおりで、どれにも当たらなければ LLM に落ちるのではなく、
提案ツールの名前を添えて人間の審査を要求します。

1. アイデアが所有する型付き `ResearchContractV1`（`admission_status` が `admitted`
   でなければ拒否）→ `contract_source: "idea.research-contract/v1"`
2. `proposal_json` + 非空の `reviewer`（人間による admission）→
   `contract_source: "human-admitted-proposal/v1"`。`reviewer` が空なら
   `admission_status: "human-review-required"` を返して何も admit しません
3. 既に永続化された `{checkpoint}/metric_contract.json` → `persisted-canonical/v1`
   もしくは旧スキーマからの `legacy-migration-reader/v1`
4. どれも無い場合 → `metric_contract: null`、
   `admission_status: "human-review-required"`、
   `proposal_tool: "propose_metric_contract"`

```python
result = make_metric_spec(open("experiment.md").read())
# 戻り値（契約が解決した場合）: {
#   "metric_keyword": "MFLOPS",
#   "metric_unit": ..., "metric_direction": ...,
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "...",
#   "metric_contract": {...}, "metric_contract_digest": "sha256:...",
#   "contract_frozen": True, "contract_source": "...",
#   "admission_status": "admitted"
# }
```

`parser_result` はどの経路でも併記されるので、テキストが何と言ったかと契約が何を
admit したかを読み手が区別できます。契約が凍結された経路の `expected_metrics` は
契約自身の `name` とその `required_evidence` を重複除去したもので、2 度目の抽出では
ありません。`expected_params` は**どの経路でも `[]`** です。
`transform-skill::nodes_to_science_data` に届く型付きの `params` / `measurements`
分割は `coding-skill::emit_results`（D 契約）に由来します。

構築された **run レベル `metric_contract`** は
`{checkpoint}/metric_contract.json`（`idea.json` / `tree.json` の隣）に永続化されます。
永続化は mint-once で、既にそこにある投影と `projection_digest` が異なる投影を書こう
とすると、上書きではなく raise します。契約はアイデアが所有する `metric_contract` と
その `falsification_conditions`（各条件が `required_evidence` を伴う claim になります）、
および `correctness_required` / `ceiling_must_be_measured` の要件フラグから組み立てられる
ので、エージェントが claim や要件を削ってチェックを回避することはできません。
これは `transform-skill::nodes_to_science_data` が読み戻して
`science_data.metric_contract` に graft し、決定論的なハードゲートが強制します。

#### `propose_metric_contract(idea_json=None, checkpoint_dir="", model="", model_revision="")`

明示的に要求されたときだけ走る LLM 提案ステップ。**LLM: Yes**。`idea_json`
（dict / JSON 文字列 / ファイルパス）が無ければ `{checkpoint}/idea.json` を読み、
アイデアが既に型付き契約を所有している場合は拒否します。出力は
`MetricContractProposalV1` で、`requires_human_review: true` と
source idea / evidence / prompt の digest、model、model revision を伴い、
`{checkpoint}/metric_contract_proposal.json` に永続化されます。この文書はそれ自体では
契約になりません — `make_metric_spec` に `reviewer` 付きで渡して初めて admit されます。

モデル: `model` 引数 > `ARI_MODEL_METRIC_PROPOSAL` env > `ARI_LLM_MODEL` env > `gpt-4o-mini`。

#### `claim_evidence_hard_gate(checkpoint_dir, paper_path, science_data_json="", paper_claim_links_path="", figures_manifest_json="", policy=None, phase="draft")`

決定論的な claim/evidence ハードゲート（実行データの忠実性）。**LLM なし**。science_data の claim が実行済みノードを参照していることを検証し、`results.json` から `numeric_assertions` を再計算して論文に記載された数値が許容誤差内かをチェックし、セクションポリシーに従って未カバーの結果数値を検出し、図の存在を確認します。ari-core の `run_hard_gate`（`ari.public.claim_gate`）の薄い MCP ラッパです。strict モードでは、ブロッキングエラーが存在するとき `final` フェーズは `{"error": ...}` を返すため、ステージランナーが例外を送出し `finalize_paper` がスキップされます。`draft` フェーズおよび warn/off モードでは決してブロックしません。`evaluation/claim_evidence_hard_gate_{phase}.json` に書き出します。

#### `evidence_grounded_semantic_review(checkpoint_dir, paper_path, science_data_json="", hard_gate_path="", paper_claim_links_path="", phase="initial", model="", model_revision="")`

非ブロッキングの、証拠に基づくセマンティック査読。**LLM: Yes**。LLM がハードゲートの証拠に接地して over-claiming / 解釈の問題 / 未登録の強い主張を検出します。独立したテキスト査読器には一切触れず、数値の再チェックも行いません。`paper_refine` が消費する `suggested_revisions` とスコアを出力します。`evaluation/evidence_grounded_semantic_review.json` に書き出します。決してブロックしません。必須引数は `checkpoint_dir` と `paper_path` のみです。`model` はこの呼び出しの査読モデルを pin します（未指定なら `ARI_MODEL_SEMANTIC_REVIEW` > `ARI_LLM_MODEL` > `gpt-4o-mini`）。`model_revision` はどの revision が走ったかを記録します。両者は prompt / evidence / hard-gate の digest とともにレポートへ書き込まれ、査読を厳密なモデル identity に帰属させます。

---

## ari-skill-paper

LaTeX 論文生成、コンパイル、査読（post-BFTS のみ）。**LLM: Yes**。

### ツール

#### `list_venues()`

利用可能な投稿先設定を返します。

対応投稿先: `neurips`（9 ページ）、`icpp`（10 ページ）、`sc`（12 ページ）、`isc`（12 ページ）、`arxiv`（無制限）、`acm`（10 ページ）。

#### `get_template(venue)`

投稿先の LaTeX テンプレートを返します。

#### `compile_paper(tex_dir, main_file="main.tex", figures_manifest_path="")`

LaTeX プロジェクトを PDF にコンパイルします。`tex_dir` を閉じた `WorkspaceRefV1`
として開き、`refs.bib` があれば bib パスとして渡し、`figures_manifest_path` を
与えた場合は `FigureBatchV1` として検証してからコンパイルに渡します（不正な
マニフェストは例外ではなく `{"success": false, "log": "invalid FigureBatchV1: …"}`）。
コンパイル記録は `.ari-paper/compile/final.json` に書き出され、戻り値は
`{success, pdf_path, log, compile}` です。ディレクトリや main ファイルが無い場合も
raise ではなく、理由を `log` に入れた `success: False` が返ります。

#### `check_format(venue, pdf_path)`

投稿先の要件に対して論文フォーマットを検証します（ページ数など）。未知の `venue`
は有効な一覧を添えて raise します。ページ数が判定できなかった場合はスキップせず
「上限が検証されなかった」という issue を立てるため、未検証が `ok: true` として
通ることはありません。

#### `write_paper_iterative(workspace_root, science_data_path, figures_manifest_path, references_path, ear_manifest_path, rubric_id, experiment_summary="", context="", verified_context_path="", venue="arxiv", max_revision_rounds=2, author_name="", writer_prompt_override="", decode_seed=0)`

論文執筆の主要なパイプラインツール。**LLM: Yes**。入力はすべて閉じた
`workspace_root` の下の成果物（native `ScienceDataV1` / `FigureBatchV1` /
記録済み retrieval 結果 / EAR 生成結果 / 任意の verified context）で、
セクション単位のツールは存在しません。venue テンプレートの `FILL_*_START …
FILL_*_END` ブロックを 1 回の LLM 呼び出しで埋め、bibliography を取得
スナップショットが admit した範囲で構築し、図の環境は `FigureBatchV1` が
所有する snippet で復元してから、AI Scientist v2 形式の reflection ラウンドを
`max(1, max_revision_rounds)` 回まわします（各ラウンドで実際にコンパイルし、
コンパイルエラー・BibTeX の状態・使われていない図・対応ファイルの無い図参照・
chktex の出力を同じメッセージ履歴へ戻して、モデルが `I am done` と答えるまで
続けます）。reflection ラウンドは必ず 1 回以上走り、`max_revision_rounds=0` でも
スキップされません。
`writer_prompt_override` と `decode_seed` は後付けの seam で、その既定値は
推奨設定ではなく凍結された互換契約です。`""` と `0` は引数が存在しなかった
時点のツールをバイト単位で再現しなければなりません（`paper_refine` も同じ
2 引数・同じ既定値を取ります）。

`writer_prompt_override=""` は同梱の `paper_writer.md` を読み込みます。非空の
値は reflection の system プロンプトをそれで**置き換え**ます。最初の
テンプレート充填呼び出しはどちらの場合も自前の `fill_in_writer` プロンプトを
使うため、override が届くのは reflection ループだけです。これはガバナンスでは
なく素の指示文字列で、`tests/test_writer_prompt_override.py` が、既定の
reflection プロンプトが読み込んだ `paper_writer.md` + 言語指示そのものである
こと、非空の override ではその呼び出しに `paper_writer.md` の本文が残らない
こと、そしてスキルの import が `ari.rqgm` モジュールを一切引き込まないことを
検査します。

`decode_seed=0` は payload に `seed` キーを一切載せず、linear（無 seed）の挙動を
保ちます。非 0 のときは初回の執筆呼び出しと各 reflection 呼び出しの両方で
litellm に渡されるため、draft を*集団*として生成する呼び出し側は K 個のコピー
ではなく異なるサンプルを得ます。litellm の `seed` は best-effort かつ
プロバイダ依存なので、得られるのは多様性でありビット単位の再生では
ありません。この引数が存在する理由は逆向きの失敗です。
`tests/test_server.py::test_a_non_zero_decode_seed_reaches_the_payload` の
回帰メモが記録するとおり、payload が一度も運ばなかった seed を記録していた
呼び出し側が「8 個の seed を 1 つの draft に潰した」のでした。記録された seed は
payload に届いて初めて意味を持ちます。このツールの seed 配線を検査するスキル
テストは無く、payload の assertion は後述の `paper_refine` 側にあります。

戻り値は `latex` / `sections` / `reviews` / `revision_counts` / `bib` /
`key_list` と draft の `paper_build` です（`sections` / `reviews` /
`revision_counts` は下流互換のために置かれた空の dict）。

#### `finalize_paper_build(workspace_root, draft_build_path, tex_path, bib_path, pdf_path, compile_record_path, figures_manifest_path, claim_links_path, hard_gate_path, text_review_path, visual_review_path, semantic_review_path, refinement_call_path="", visual_passing_score=0.7, output_path="paper_build.json")`

論文フェーズの最終段。`write_paper_iterative` が返した draft の `PaperBuildV1` を
不変の最終記録に変えます。**決定論的、LLM なし**。すべてのパスは閉じた
`workspace_root` の内側で解決され、draft が宣言した成果物 — その入力、記録された
各 revision の TeX と bibliography、記録された各モデル呼び出し — は、新しいものを
読む前にすべて digest で再検証されます。そのうえで最終の tex / bib / PDF を
ハッシュし、コンパイル記録を解析し、claim リンク文書が `link_paper_claims` 段の
`ari.paper-claim-links/v1` であることを要求します。

finalize は形式ではなく判断です。`blocking_reasons` には失敗が積み上がります —
最終 revision が正準の図 ID を落とした / 数式の内容を変えた、ハードゲートが無効化
されていた / ブロッキングな所見を報告した、未解決の claim アンカーがある、未カバーの
数値結果への言及がある、コンパイルが完走しなかった、PDF の digest がコンパイル記録と
異なる、視覚査読に失敗ターゲットがある / スコアが `visual_passing_score` を下回る。
理由が 1 つでもあれば status は `finalized` ではなく `blocked`（コンパイル理由が
含まれるときは `compile-error`）になり、MCP ツールは理由を連ねた例外を送出します。
記録はどちらの場合も書き出されるので、ブロックされたビルドは失われるのではなく
監査可能なまま残ります。

#### `review_compiled_paper(rubric_id, tex_path="", pdf_path="", figures_manifest_json="", experiment_summary="", vlm_findings_json="", num_reflections=None, num_fs_examples=None, num_reviews_ensemble=None)`

**AI Scientist v1/v2 互換** のルーブリック駆動論文査読 (Nature / arXiv:2408.06292
Appendix A.4 準拠)。`ari-core/config/reviewer_rubrics/<rubric_id>.yaml` を
読み込み、`score_dimensions` / `text_sections` / `decision` スキーマから
プロンプトを動的生成。VLM の図ごとの所見 (score / issues / suggestions) を
査読者ノートとしてプロンプトに注入し、Few-shot 例を先頭に付加、Self-reflection
ループで自己批判・改訂を行い、ルーブリック準拠の JSON で出力。

同梱ルーブリック (`ari-core/config/reviewer_rubrics/` に 23 個の YAML):

| 系統 | rubric_id |
|---|---|
| ML カンファレンス | `neurips` (既定、v2 互換) / `iclr` / `icml` / `cvpr` / `acl` |
| システム / HPC | `sc` / `osdi` / `usenix_security` |
| 理論 / グラフィックス | `stoc` / `siggraph` |
| HCI / ロボティクス | `chi` / `icra` |
| 経済学 / 人文系ジャーナル | `aer` / `qje` / `econometrica` / `apsr` / `ahr` / `pmla` / `philreview` |
| ジャーナル / 汎用 | `nature` / `journal_generic` / `workshop` / `generic_conference` |

`reviewer_rubrics/` に YAML を 1 枚追加するだけで新しい venue を拡張可能
(コード変更不要)。各ルーブリックは `score_dimensions` / `text_sections` /
`decision` ルール、実行パラメータ、P2 決定論用の SHA256 ハッシュを宣言します。

ルーブリック解決: `rubric_id` は第 1 引数かつ必須で、環境変数フォールバックも
既定 venue も内蔵 `legacy` フォールバックもありません — `resolve_rubric` は空の
`rubric_id` を「`rubric_id` is required; migrate legacy ARI_RUBRIC/default config
to an explicit workflow input」として拒否します。どの YAML を読むかだけが
探索対象で、`ARI_RUBRIC_DIR` → `./ari-core/config/reviewer_rubrics/` →
`./config/reviewer_rubrics/` → リポジトリルート配下の同ディレクトリの順に
最初に見つかったものが使われます。したがって、ある論文をどの rubric が採点したかは
常にその呼び出しに記録されます。

このチェーンに依存していた旧 launch / workflow ドキュメントはオフラインで変換します。
`src/rubric_migration.py::migrate_legacy_rubric_selection` が `paper_rubric` →
`rubric_id` → `ARI_RUBRIC` → v1 以前の既定 `neurips` の順にたどり、結果を検証して、
明示的な `paper_rubric` フィールドと、どの `source` が値を与えたかを記す記録
（`ari.paper-rubric-migration/v1`）を返します。ランタイムのフォールバックではなく、
一度きりの移行ヘルパです。

#### 著者 / 査読者の対称な venue 条件付け

`prompt_overrides` は 2 つの並行フィールドを持ちます:

- `system_hint` — `review_engine` がピアレビューのプロンプトに注入します
  (既存の挙動)。
- `author_hint` — `write_paper_iterative` が論文執筆側の system プロンプトに
  `VENUE RUBRIC AUTHOR GUIDANCE … END VENUE RUBRIC AUTHOR GUIDANCE` ブロックと
  して注入します。査読者が何を見るかを執筆側に伝え、その signal を出しやすい
  形で論文を書かせます。

`author_hint` が空の rubric ではこのブロックそのものが省かれ、執筆プロンプトに
残る venue signal は `Target venue: X.` の一行だけになります。同梱 23 rubric の
うち校正済みの `author_hint` を持つのは現在 9 つ — `sc` / `neurips` と、経済学・
人文系ジャーナル 7 つ（`aer` / `qje` / `econometrica` / `apsr` / `ahr` / `pmla` /
`philreview`）です。残りの venue は空のままコード変更なしで順次埋められます。

Nature Ablation 由来の既定値:

- `num_reflections: 5` — +2% balanced accuracy
- `num_fs_examples: 1` — +2% accuracy (ICLR reviewer guidelines の 1-shot)
- `num_reviews_ensemble: 1` — アンサンブルは精度ではなく分散のみ改善
- `temperature: 0.75`

モデル: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`。

**アンサンブル + Area Chair メタ査読 (内蔵):** `review_compiled_paper` は
アンサンブル経路経由で N 名の独立査読者エージェント（温度ジッタ付き、AI
Scientist v1 best-config 方式）を実行します。N>1 のときは Area Chair
メタ査読も内部で走り、`ensemble_reviews: [...]` と `meta_review: {...}` が
出力に同梱されます。N の解決順: 明示引数 > `ARI_NUM_REVIEWS_ENSEMBLE` env >
`rubric.params.num_reviews_ensemble` (既定 1)。N=1 は単一査読と等価です。

#### `list_rubrics()`

利用可能なルーブリックの一覧 (id, venue, domain, version, SHA256 hash, path)
を返します。viz API `/api/rubrics` と New Experiment Wizard のドロップダウン
で使用されます。

#### `inject_code_availability(tex_path, ref="", sha256="", doi="", license_id="", checkpoint_dir="")` — v0.7.0

`finalize_paper` ステージで実行されます。`ear_published/manifest.lock` と `publish_record.json` から `ref` / `bundle_sha256` / `doi` を自動ロードし、機械可読な `\codeavailability{}` / `\codedigest{}` / `\coderef{}` マクロと人間可読な Code Availability セクションを `full_paper.tex` に注入します。digest が信頼の起点となり、読者は registry を信頼することなく `ari clone <ref> --expect-sha256 <baked-digest>` で検証可能です。キュレート済みバンドルが無ければ静かにスキップ（v0.6.0 checkpoint の互換維持）。

#### `merge_reviews(review_report_path, vlm_review_path="", hard_gate_path="", semantic_review_path="")` — v0.7.0

`review_report.json`（テキスト査読）と `vlm_review.json`（VLM 図表レビュー）を構造的にマージするポストホック処理。完全に決定論的、LLM なし。`vlm_figure_review` と `_review_composition` メタデータを付与して GUI / CLI の両出力を出典付きで表示できるようにします。上流ステージは独立性（AI Scientist v2 の `perform_review` 契約）を保ち、ここで初めて統合されます。

必須は `review_report_path` のみで、残る 3 つは任意です（v0.6.0 の 2 引数呼び出しはそのまま動きます）。テキスト査読と VLM 査読は `independent_reviews` の下に置かれ、変更されません。`hard_gate_path`（`claim_evidence_hard_gate`）と `semantic_review_path`（`evidence_grounded_semantic_review`）は `evidence_grounded_reviews` として別枠で報告され、この 2 つから `paper_refine` が消費する統合 `suggested_revisions` リストが生成されます — 省略するとそのリストには何も載りません。

#### `link_paper_claims(tex_path="", science_data_json="", figures_manifest_json="", output_path="")` — v0.9.0

`% CLAIM:Cx:NCx` アンカーを science_data の claim と照合し、claim ハードゲートが消費する `paper_claim_links.json`（anchors / writer_assertions / numeric_mentions / figure_refs / unresolved_anchors / uncovered_numeric_candidates）を構築します。**決定論的、LLM なし**。transform ステージの `science_data.json` は決して変更されず、図のバインディングはここで記録されます。`write_paper`（draft）の後、および `paper_refine`（final）の後に再度実行します。失敗時は有効な空の結果にデグレードする（error のみにはならない）ため、finalize チェーンを連鎖的にスキップさせることはありません。

#### `paper_refine(tex_path="", suggested_revisions_json="", merged_review_path="", semantic_review_path="", venue="arxiv", writer_prompt_override="", decode_seed=0)` — v0.9.0

`suggested_revisions`（`evidence_grounded_semantic_review` / マージ済み査読由来）を適用する、アンカー保持の修正パス。**LLM: Yes**。明示的な `replace "X" with "Y"` 置換をまず決定論的に適用し、残りは境界付きのマルチパス LLM の検索/置換で処理します。draft 内に存在するすべての `% CLAIM` アンカーは生き残らなければなりません（アンカーを落とす編集は拒否され、ネットでアンカーが減った場合は元の論文を保持します）。math-safe なアンダースコアのエスケープは `\( … \)` / `\[ … \]` および数式環境をスキップします。修正後の LaTeX は `latex` の下に返されます（draft は `full_paper.draft.tex` として保存されます）。`refine_passes` に実行された LLM パス数（最大 3）が、old span が残っている明示置換は `unaddressed_substitutions` に報告されます。

追加の 2 引数は、未設定なら既定経路をバイト単位で変えません。その既定値は
チューニング用の摘みではなく凍結された互換契約です。`writer_prompt_override`
は素の指示文字列で、非空のときは同梱の `global_coherence.md` プロンプトの
**前に連結**され、渡された paper-writer テキストが refine を先導します。ここに
非対称性があります — 同じ引数名が `write_paper_iterative` では同梱プロンプトを
*置き換える*のに対し、こちらでは前置きするだけです。`decode_seed` は `0` の
あいだ payload に載らず、非ゼロにすると refine がその draft の seed の下で
サンプリングされ、refine が親の decode identity を継承します。

スキルテストが実際に固定しているのはこの 2 つの seam です。
`tests/test_server.py` は payload 側を両方向から検査します — `0` のときは捕捉した
`litellm.acompletion` 呼び出しのどれにも `seed` キーが無く messages は引数を
省略した場合と同一であること、非 0 のときは捕捉したすべての呼び出しがちょうど
その seed を運ぶこと。記録された seed が「モデルの見なかった seed」になるのを
止める assertion です。`tests/test_writer_prompt_override.py` はプロンプト側を
検査し、既定の system プロンプトが前置き無しの `global_coherence.md` + 言語指示
そのものであること、非空の override では
`override + "\n\n" + global_coherence + 言語指示` になることを assert します。

##### Few-shot コーパス管理

`ari-core/config/reviewer_rubrics/fewshot_examples/<rubric>/` 配下のファイルは、**New Experiment Wizard → Paper Review → Few-shot サンプル** サブパネル (GUI)、または `scripts/fewshot/sync.py` (CLI) から管理できます。

GUI 操作:

- **Auto-sync**: サーバ側で `scripts/fewshot/sync.py --venue <rubric>` を実行し、`manifest.yaml` 記載のエントリを取得。デフォルトで AI Scientist v2 の 3 本 (`132_automated_relational` / `2_carpe_diem` / `attention`) を Apache-2.0 の `SakanaAI/AI-Scientist-v2` リポジトリから pull。
- **Upload**: rubric スキーマに沿った JSON + 任意の `.txt` 抜粋 + 任意の PDF (base64) を受け付け、`_source: "GUI upload (rubric=<id>)"` を自動付与。
- **Delete**: 指定 example の全拡張子を削除。

REST エンドポイント:

- `GET  /api/fewshot/<rubric>`
- `POST /api/fewshot/<rubric>/sync`
- `POST /api/fewshot/<rubric>/upload`
- `POST /api/fewshot/<rubric>/<example>/delete`

すべて `reviewer_rubrics/` に存在しない rubric は拒否し、`../` / スラッシュは入力から除去します。

---

## ari-skill-paper-re

PaperBench (arXiv:2504.01848) **SimpleJudge** を用いた再現性採点。**LLM: Yes**（採点は upstream `SimpleJudge` 内の LLM 呼び出し。ARI 側はこのスキルで追加の LLM 呼び出しを行いません）。

v0.7.0 で v0.6.0 の LLM 駆動判定パスは、PaperBench をコアとする決定的なエンドツーエンドのチェーンに置き換えられました:

```
ors_generate_rubric  (replicate-skill)    → ors_rubric.json + ors_rubric.meta.json
ors_audit_rubric     (replicate-skill)    → 独立した監査ドキュメント; ors_rubric.json は書き換えない
ear_publish          (transform-skill)    → bundle.tar.gz + publish_record.json (local-tarball デフォルト)
ors_seed_sandbox     (paper-re-skill)     → repro_sandbox/{reproduce.sh, code/...}
                                              (決定論的; fetch_code_bundle ← publish_record.json)
ors_build_reproduce  (paper-re-skill)     → repro_sandbox/{reproduce.sh, source files}
                                              (LLM フォールバック; seed 済なら skip)
ors_run_reproduce    (paper-re-skill)     → ors_phase1.json   (Phase 1: reproduce.sh をサンドボックスで実行)
ors_grade            (paper-re-skill)     → ors_grade.json    (Phase 2: SimpleJudge で葉ノード採点)
```

`ors_audit_rubric` は、以降のすべての採点が依拠するルーブリック自体を検査します。
各葉に `vague_qualifier` / `no_paper_evidence` / `duplicate`（決定論的）と
`unverifiable`（葉ごとに LLM 1 回）のフラグを付け、20% 超の葉にフラグが付くと
`regen_recommended` を返します。frozen なルーブリックは **書き換えません** —
所見は別ドキュメント `ari.replication-rubric-audit/v2`（既定パスは
`<rubric_path>.audit.json`）に出力され、そこで rubric と paper の digest を
束ねるので両者が乖離できません。ゲートではなくシグナルであり、採点はどちらでも
進みます。`ARI_MODEL_RUBRIC_AUDIT` で生成側と別モデルを指定できます。

EAR が ON の実行は `ors_seed_sandbox` 経由（決定論的）で reproduce.sh を取得します。LLM `ors_build_reproduce` は reproduce.sh が既存の場合スキップするので、EAR が OFF の実行（論文のみ再現）でのみ発火します。

**v0.7.2 の HPC 追加。** `build_reproduce_sh` と `run_reproduce` はどちらも任意の
`reproduce_contract.execution_profile` ブロック（[リファレンス](execution_profile.md)）
を消費します。

- エージェントのプロンプトに `EXECUTION PROFILE` の JSON ブロックと、
  `SLURM_JOB_NUM_NODES` / `SLURM_NTASKS` / `nvidia-smi` から取った実時点の
  `CLUSTER SHAPE` スナップショット、さらに `COMPUTE-NODE EXECUTION CONVENTIONS`
  のフッタ（共有 FS、srun 優先、conda の activate、マルチノードのファンアウト、
  timeout での包み方）が加わります。付録の全文は
  `ari-skill-paper-re/src/_replicator_agent.py::_format_hpc_appendix` にあります。
- `kind ∈ {mpi, mpi_gpu}` のときは MPI 集約のスケルトン
  （`prompts/mpi_aggregate_skel.py`）が `submission/mpi_aggregate.py` へ自動コピー
  されます。
- `run_reproduce` は allocation の形状を生のフラグではなく型付き引数で受け取ります
  — `nodes` / `ntasks` / `ntasks_per_node` / `nodelist` / `exclude_nodes` /
  `exclusive` / `gpus_per_task` / `gpus_per_node` / `gpu_type` /
  `memory_gb_per_node` / `memory_gb_per_cpu` / `constraint` / `hint` / `account` /
  `qos` / `reservation` / `module_loads`。いずれも既定のままなら
  `execution_profile` から自動解決されます。`cpu_bind` / `mem_bind` は srun の
  job-step 設定なので、`reproduce.sh` に書くよう指示して拒否されます。旧来の
  `extra_sbatch_args` という抜け道は変換可能な 4 つの接頭辞（`--account=` /
  `--qos=` / `--reservation=` / `--hint=`）にまで縮退し、それ以外は型付き
  フィールドを指し示して raise します。

PaperBench は `ari-skill-paper-re/vendor/paperbench` に同梱。メイン採点 completer は LiteLLM (`_litellm_completer.py`) を経由するので、任意のプロバイダ（`gpt-5-mini` / `anthropic/claude-...` / `gemini/...` / `ollama/...`）が使えます。スコアパース用の structured completer 2 本も同じ `judge_model` から作られ、`response_format`（`ParsedJudgeResponseInt` / `ParsedJudgeResponseFloat`）だけがメインの completer と異なります。

### ツール

#### `fetch_code_bundle(ref="", sha256="", dest="", checkpoint_dir="", overwrite=False)`

キュレート済み EAR バンドルを `ari.clone` 経由で再現性サンドボックスへ事前展開します。決定論的、LLM なし。バンドルの指定方法は 2 つ:

- **直接 ref**: `ref="file:///path/to/bundle.tar.gz"` / `ref="ari://0ccabb16…"` /
  `ref="gh:owner/repo"` / `ref="https://…"`。
- **publish_record.json からの自動読込**（v0.7.0+）: `checkpoint_dir={checkpoint}`
  を渡すと `{checkpoint_dir}/publish_record.json`（`ari ear publish` が書き出す
  ファイル）から ref + sha256 を読みます。`inject_code_availability` と同じ規約です。

`dest/reproduce.sh` が既にあるときは `populated=False, skipped_reason=...` を返して
スキップし（`ear` seed や先行バンドルの後ろに合成できます）、空でない dest は
`overwrite=True` でない限り上書きを拒否します。

#### `build_reproduce_sh(paper_path="", paper_text="", rubric_path="", output_dir="", model="", time_limit_sec=43200, iterative_agent=False, max_steps=0, sandbox_kind="auto", container_image="", overwrite=False)`

**v0.7.0+ で追加された LLM 駆動の replicator**。`fetch_code_bundle` の兄弟ツール。論文（とルーブリックの `expected_artifacts`）を読み、自己完結の `reproduce.sh` + ソースファイル一式を `output_dir` に書き出します。実体は PaperBench の `BasicAgent` / `IterativeAgent` ReAct rollout (`_replicator_agent.run_replicator_agent`) で、単発の JSON 生成呼び出しではありません。`output_dir/reproduce.sh` 既存時はスキップ。モデル: `model` 引数 > `ARI_MODEL_REPLICATOR` > `ARI_LLM_MODEL` > `gpt-5-mini`。OpenAI Responses 形式の id（`/` を含まない `gpt-` / `o1-` / `o3-` / `o4-` / `o5-`）は PaperBench 純正の Responses completer を、それ以外は LiteLLM を通るので任意プロバイダ対応です。エージェントが書いたものは submission ツリーから `output_dir` へ 1 ファイルずつ昇格されますが、絶対パス、`..` や `.git` を含む要素、シンボリックリンクの要素、どちらのツリーの外へ解決されるものは、コピーされずに拒否されます。

`sandbox_kind` は `auto` / `local` / `apptainer` / `slurm` で、エージェントの rollout 自体をどこで走らせるかを選びます。`container_image` を解釈するのは `apptainer` rollout だけで、値は不変のローカル SIF か digest pin されたリモート URI です（引数が空なら `ARI_PHASE1_APPTAINER_IMAGE` を参照）。`local` / `slurm` は無視します。レガシーの `apptainer_image` 引数は**ありません**。シグネチャから削除済みでスキル内のどこにも登場しないため、ここでイメージを指定する手段は `container_image` だけです。

#### `run_reproduce(rubric_path, repo_dir, sandbox_kind="", container_image="", timeout_global_sec=0, network_policy="deny", network_isolation_attested=False, partition="", cpus=0, walltime="", …SLURM flags)`

**Phase 1**。`repo_dir/reproduce.sh` をサンドボックスで実行し、`reproduce.log` と成果物リストを取得。ルーブリック envelope の `expected_artifacts` と突き合わせ、未生成の成果物を `missing` として返します。

サンドボックス優先順位（`auto` の場合）: `slurm`（sbatch + `ARI_SLURM_PARTITION` あり、BFTS と同じパーティション）→ `docker`（デーモン利用可かつ HPC 上ではない時）→ `apptainer` → `singularity` → `local`。コンテナサンドボックスに既定イメージはありません。`container_image`、なければ `docker` は `ARI_PHASE1_DOCKER_IMAGE`、`apptainer` / `singularity` は `ARI_PHASE1_APPTAINER_IMAGE` から、digest で pin された不変イメージを必ず与える必要があり、空なら既定へフォールバックせず拒否されます。**SLURM dispatch** は独自の `sbatch` ではなく型付きスケジューラライフサイクルへの handoff です。実行リクエストは `ResourceRequestV1` を持つ `JobRequestV1` になり、`ari-skill-hpc` と同じ `SlurmScheduler`（台帳は `{repo_dir}/../.ari-hpc/paper-re-jobs-v1.json`）へ submit されて終端状態まで poll され、検証済みのスケジューラログが `reproduce.log` に書き出されます。戻り値には `handle_id` / `job_id` / `request_digest` / `handoff_digest` / `execution_identity` / `unmapped_policies` が含まれ、タイムアウトを超えたジョブは cancel され `timed_out: true` として報告されます。partition は 引数 > `ARI_SLURM_PARTITION` > `{checkpoint_dir}/launch_config.json`、`cpus` は 引数 > `ARI_SLURM_CPUS`（既定 `8`）、`walltime` は 引数 > `ARI_SLURM_WALLTIME` > timeout から導出した `HH:MM:SS` の順で解決されます。

**ネットワークは既定で遮断**されます。`network_policy` は `deny` で、隔離されていない基盤を使う場合のみ `network_policy="inherit"` として明示的に admit する必要があります。`network_isolation_attested` は、その隔離が仮定ではなく attest されたことを記録します。ソースツリーは read-only でスナップショットされ、実行はプライベートな attempt tree で行われるため、同一の成功プランは冪等に replay され、失敗プランには紐付いた retry attempt が追加されます。

#### `grade_with_simplejudge(rubric_path, repo_dir, paper_path="", paper_text="", judge_model="", n_runs=0, skip_negative_control=False, code_only=False)`

**Phase 2**。メイン採点 completer と structured score-parser はいずれも LiteLLM 経由で同じ `judge_model` を使います。`n_runs`（引数、なければ `ARI_JUDGE_N_RUNS`、なければ 1。範囲 1–100）回を PaperBench の重み付き葉集約で平均化します。加えて 1 回だけ**負例コントロール**（空 repo + 自明な `reproduce.sh`）を走らせ、ルーブリックが「何もしていないこと」に報酬を与えないことを確かめます — 2 つのコントロールがどちらも 5%（0.05）未満のときだけ `passed=true` です。

戻り値: `{ors_score, raw_score, leaf_grades, judge_model, n_runs, rubric_sha256, elapsed_sec, negative_control: {empty, boilerplate, passed}}`。

モデル: `judge_model` 引数 > `ARI_MODEL_JUDGE` > `ARI_LLM_MODEL` > `gpt-5-mini`。LiteLLM 認識可能な任意の model id が動作（PaperBench 純正の `CONTEXT_WINDOW_LENGTHS` 制約を回避）。

---

## ari-skill-replicate

v0.7.0 で追加された PaperBench 形式の **オートルーブリック生成器・監査器**。論文を読み、frozen ルーブリック（`replication_rubric.schema.json`、provenance メタデータ付きの PaperBench `TaskNode` ツリー）を出力します。**LLM: Yes**。

`ari-skill-paper-re.grade_with_simplejudge` と組み合わせて、v0.6.0 の `react_driver` ベースの再現性チェックを置き換える ORS フローを構成します。

### ツール

#### `generate_rubric(paper_path="", paper_text="", output_path="", target_leaf_count=0, model="", temperature=0.0, seed=0, paperbench_rubric_id="", max_model_calls=64, subtree_concurrency=4, provider="", model_revision="")`

PaperBench 互換のルーブリックを生成。`target_leaf_count=0` の場合は論文長から自動算定（~1葉 / 75語、[50, 400] にクランプ）。

生成は常に階層的です。単一コール経路は廃止され、frozen な envelope には `strategy: "hierarchical-v2"` / `quality_profile: "calibrated"` が無条件で記録されます。①スケルトンパス（`prompts/skeleton.md`）でルート + 直接子（contribution/experiment ごとに1ノード）と各子の葉数バジェットを決定 → ②サブツリーパス（`prompts/subtree.md`）を `subtree_concurrency` 並列で走らせ、各直接子のサブツリーを再帰的に展開。マージ後、スキーマの `minLength=10` を満たさない葉（quote / requirements が短すぎる葉）は自動で除去され、論文の厳密な span にも明示された external prerequisite にも束縛できない葉も同様に除去されます。`max_model_calls` が実行全体の上限で、プロンプトと応答の組はすべて `.ari-rubric/` に保持され `generator.calls` に列挙されます。

`paperbench_rubric_id`（未リリース）は
`ari-core/config/paperbench_rubrics/<id>.yaml` から venue 条件付けテンプレートを
選択します。空文字列 = 同梱プロンプトをそのまま使用（後方互換）。非空の値では
その YAML を読み込み、`{VENUE_HINT}` プレースホルダ経由で
`prompt_overrides.system_hint` / `prompt_overrides.leaf_style` を
skeleton + subtree のプロンプトに注入します。これは `ari-skill-paper` がピア
レビューで既に使っている `reviewer_rubrics/` の venue パターンと同型であり、
同じ `venue → YAML → prompt` の流れがルーブリック生成器でも使えるようになりました。
同梱テンプレート: `generic`（後方互換）、`sc`（HPC 論文監査、6 軸）、
`neurips`（ML 再現性、6 軸）、`nature`（ウェットラボ、5 軸）。YAML スキーマは
[`docs/reference/rubric_schema.md`](rubric_schema.md#venue-別テンプレート-venue-conditioned-templates)
を参照。

#### `audit_rubric(rubric_path, paper_path="", paper_text="", auditor_model="", output_path="", max_model_calls=400)`

独立した監査パス。問題のある葉を `vague_qualifier` / `no_paper_evidence` / `duplicate` / `unverifiable` でフラグ付けし、20% 超なら再生成を推奨します。

frozen なルーブリックは決して書き換えません。所見は別ドキュメント `ari.replication-rubric-audit/v2` に入り、`output_path`（空なら `<rubric_path>.audit.json`）へ書き出されます。監査の前に、ルーブリック自身の digest、与えられた論文テキストに対する `paper_sha256`、生成側の provenance artifact をすべて再検証します。監査側の model/provider/revision が生成側と一致する場合は `independence_status: "not-independent"` を記録します。

#### `suggest_target_leaf_count(paper_path="", paper_text="")`

論文長から自動算定した目標葉数と単語数（`{target, word_count}`）を返します。
**決定論的、LLM なし**。GUI Wizard の "Target leaves" 欄の事前埋めに利用。
`paper_text` が空なら `paper_path` を読み、どちらからもテキストが取れない場合は
`{"error": ..., "target": 0}` を返します。

### v0.7.2 — `reproduce_contract.execution_profile`

論文が並列実行の性質 (MPI ランク数、GPU 種別、専有、メモリ、NUMA バインド)
を明示している場合、skeleton + subtree のプロンプトは生成器に
`reproduce_contract.execution_profile` を埋めるよう指示するようになりました。
Schema: [`docs/reference/execution_profile.md`](execution_profile.md)。
このフィールドは任意で後方互換です — 単一 CPU の論文では書かれません。

### 環境変数

| 変数 | デフォルト | 用途 |
|---|---|---|
| `ARI_MODEL_RUBRIC_GEN` | `gemini/gemini-2.5-pro` | 生成 LLM |
| `ARI_MODEL_RUBRIC_AUDIT` | `anthropic/claude-opus-4-7` | 監査 LLM（生成器とは独立） |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | (未設定) | 目標葉数の上書き。`0` / 未設定で論文長から自動。GUI Wizard の "Target leaves" 欄。 |
| `ARI_RUBRIC_GEN_TEMPERATURE` | (未設定) | 生成器 temperature の上書き。GUI Wizard の "Temperature" 欄。 |

この 2 つは generator が走る前に `server.py` の `_resolve_env_overrides` で解決され、
**環境変数が設定されていればそれが勝ちます**（未設定のときだけ kwarg の値が使われる）。
`workflow.yaml` の `ors_generate_rubric` ステージはこの 2 項目を明示しないため、
GUI Wizard の値が常に実行時の値になります。

---

## ari-skill-memory

祖先スコープのノードメモリ（v0.6.0 より [Letta](https://docs.letta.com) バックエンド）。ブランチ間汚染を防止し、ReAct エージェントのトレースも同じ Letta エージェントに格納します。**LLM: △**（埋め込みベースの検索。P2 緩和の詳細は `docs/concepts/PHILOSOPHY.md`）。

### ツール

#### `add_memory(node_id, text, metadata=None)`

`node_id` でタグ付けされたエントリを保存します。**Copy-on-Write**: `node_id` が署名付き call context のノードと一致しない書き込みは拒否されます。

#### `search_memory(query, ancestor_ids, limit=5)`

`ancestor_ids` に含まれるノードのエントリのみを **Letta の `passages.search` (embedding ベースの semantic search) ランク順** で返します。兄弟・子ノードは一切返しません。

実装メモ (Letta 0.16.7 で 2026-05-04 検証): SDK の `passages.list(search=q)` は意図的に **使いません**。当該 SDK は `GET /archival-memory?search=q` に変換され、サーバ側で **SQL substring match** (`WHERE LOWER(text) LIKE LOWER(%q%)`) — semantic search ではありません。`"Validate the loopline performance model"` のような長い自然文クエリは `RESULT SUMMARY metrics=[...]` のような構造化エントリに部分文字列でヒットしないため、本番で 84 件の有効 passage がありながら 0 件しか返らない問題が観測されました。本スキルは代わりに `passages.search` (`GET /archival-memory/search`、`embed_query=True`) を `top_k = max(letta_overfetch, limit*40)` で叩き、ランクされた結果を `ancestor_ids` / `ari_checkpoint` / `kind == "node_scope"` でローカル post-filter します。`add_memory` 挿入時に支払っている embedding コストが retrieval で正しく消費される形になり、子は `eval_summary` クエリに対して **意味的に最も関連するエントリ** を先頭から受け取ります。

#### `get_node_memory(node_id)`

特定ノードの全エントリを時系列で取得（スコアなし）。

ノードごとの clear は、デバッグ用も含めて存在しません。このスキルの 13 ツールの
どれもエントリを削除しません。書き込みは append-only かつ CoW ガード付きで、
`tests/test_cow.py::test_destructive_clear_is_not_publicly_exposed` が
（`assert not hasattr(server, "clear_node_memory")` で）その不在を直接検査します。
ノードの footprint を縮めたいときは元のエントリを消すのではなく、
`consolidate_node_memory` で統合された型付きエントリを足します。

ARI の governance がノードを論理的に
消去した場合も、`search_memory` / `get_node_memory` はそのエントリを黙って
落とさず、`erased` / `erasure_event_id` / `erasure_note` のラベルを付けて
返します（ラベル付けはバックエンド側で行われるため、この MCP 面だけでなく
インプロセスの読み手も同じ表示を見ます）。消去が取り下げるのは判断の standing
であって、実験が測定した事実そのものではないためです。ただし論文の接地済み
claim リストなど、メモリを判断へ **押し込む** 経路では labelled ではなく
ハード除外されます。

#### `get_experiment_context()`

Letta のコアメモリからシードされた実験ファクト（`experiment_goal`、`primary_metric`、`hardware_spec` など）を返します。シードは最初のノードで `generate_ideas` が完了したタイミング（`primary_metric` が確定する時点）で 1 回だけ実行されるため、それ以前は `{}` を返します。以降は何度呼び出しても安全（60 秒のインプロセスキャッシュ付き）。

#### 型付き検証可能リサーチメモリのツール

型付きエントリ（Phase 1）は構造化された来歴を持ち、論文 / 図ステージが再現可能なアーティファクトに claim を接地できるようにします。呼び出し元は loop / pipeline フックであり、LLM のプルではありません。すべての書き込みツールは **Copy-on-Write ガード** 付きです: `node_id` は、ari-core の MCPClient が呼び出しへ注入する署名付き call context のノードと一致しなければならず、子は祖先のエントリを変更できません。

#### `add_experiment_result(node_id, text, metric_ptr=None, artifact_refs=None, node_report_ref=None)`

型付き `experiment_result` を記録します（CoW: 自ノードのみ）。

#### `add_failure_case(node_id, text, artifact_refs=None, node_report_ref=None)`

型付き `failure_case` を記録します（CoW: 自ノードのみ）。

#### `add_procedure_memory(node_id, text, node_report_ref=None)`

再利用可能な手順を記録します（CoW: 自ノードのみ）。

#### `add_reflection(node_id, text, confidence=None, node_report_ref=None)`

リフレクションを記録します（CoW: 自ノードのみ）。論文の主張には使用できません。

#### `add_reproducibility_event(node_id, target_memory_id, status, artifact_refs=None, text=None)`

既存エントリに対して追記専用の再現性ステータスイベントを追加します（CoW: 自ノードのみ）。

#### `search_research_memory(query, ancestor_ids, kinds=None, require_artifacts=False, limit=5)`

`kind` / アーティファクトの有無でフィルタした祖先スコープの型付き検索。兄弟・子ノードは一切返しません。

#### `get_verified_context(ancestor_ids, purpose="paper", limit=None)`

論文 / 図の利用向けの、アーティファクトに裏付けられた再現性対応コンテキスト。

#### `audit_memory(experiments_root, run_id=None)`

チェックポイントについて、記録された来歴（sha256）をディスク上と照合検証します。`{summary, results}` を返します。

#### `consolidate_node_memory(node_id, node_report, work_dir, run_id=None)`

ノード終了時に `node_report` から型付きメモリ（`experiment_result` / `failure_case` / `reflection`）を導出して、型付きライタ経由で書き込みます（CoW: 自ノードのみ）。呼び出し元は ari-core のノード終了フックです。

ストレージ: チェックポイントごとに Letta エージェント（`ari_node_*` と `ari_react_*` の 2 コレクション）。`{ARI_CHECKPOINT_DIR}/memory_backup.v1.json.gz` にポータブルスナップショット、`{ARI_CHECKPOINT_DIR}/memory_access.jsonl` に write/read テレメトリ。v0.5.x の JSONL ストア（チェックポイントスコープの `memory_store.jsonl` と、かつて `$HOME/.ari/` 配下にあったレガシーグローバル JSONL）は v0.6.0 で削除。移行は `ari memory migrate --react`。クロス実験の「グローバルメモリ」は廃止。

---

## ari-skill-orchestrator

ARI を外部エージェントや IDE 向けの MCP サーバーとして公開します。再帰的なサブ実験をサポート。**LLM: No**（ARI CLI に委譲）。

デュアルトランスポート: **stdio**（既定。Claude Desktop / 他 MCP クライアント向け）+
**streamable-http**（`--transport streamable-http`、`ARI_ORCHESTRATOR_HTTP_HOST` /
`ARI_ORCHESTRATOR_HTTP_PORT`、デフォルト `127.0.0.1:9890`、パスは `/mcp`）。
HTTP は `ARI_ORCHESTRATOR_HTTP_TOKENS_FILE` が無いと起動を拒否します — 認証の
無いネットワーク制御は許しません。

どのツールも呼び出し元の principal に対して認可されるため、下の 12 ツールは
汎用のリモート制御面ではなく、投入 1 / キャンセル 1 / 読み取り 10 です。

12 ツールはいずれも例外を投げず、失敗は
`{"error": {"code": ..., "message": ...}}` の封筒で返します。`code` は
`invalid_request` / `forbidden` / `not_found` / `idempotency_conflict` /
`quota_exceeded` / `artifact_policy` / `authentication_failed` /
`orchestrator_error` / `internal_error` のいずれかです。state machine、
quota、artifact admission の規範は
[Orchestrator control plane](orchestrator.md) にあります。

### ツール

#### `run_experiment(experiment_md, idempotency_key, parent_run_id="", max_recursion_depth=None, max_nodes=10, max_total_nodes=100, max_descendant_runs=32, estimated_cost_usd=0.0, max_cost_usd=100.0, cpus=1, timeout_minutes=60, model="", llm_backend="", executor="", retrieval_backend="")`

quota で拘束された ARI 実行を 1 件冪等に投入し、永続ハンドル（`RunHandleV1`）を
返します。`idempotency_key` は必須で、同じ `(principal_id, idempotency_key)` の
再送は request digest が一致すれば既存ハンドルを返し、異なれば失敗します。
`parent_run_id` が空なら `ARI_PARENT_RUN_ID`、`max_recursion_depth` が `None`
なら `ARI_MAX_RECURSION_DEPTH`（未設定時は 3）を継承します。`model` /
`llm_backend` / `executor` / `retrieval_backend` は空のとき `ARI_MODEL` /
`ARI_BACKEND` / `ARI_EXECUTOR` / `ARI_RETRIEVAL_BACKEND` にフォールバックします。

quota ブロックはリクエストの一部で、再帰は 3 つの軸で同時に縛られます — この run の
`max_nodes`、ツリー全体の `max_total_nodes`、サブツリーが派生できる run 数の
`max_descendant_runs` — さらにその上に `max_cost_usd` が乗ります。したがって子 run
が引数を省くだけで親の予算から逃れることはできません。このツールに credential 引数は
**ありません**。API キーも base URL も受け取りません。

#### `get_status(run_id)`

`RunStatusV1` — 永続 state、タイムスタンプ、上限付きのノード進捗、系統ごとの
予算消費を返します。

#### `get_result(run_id)`

`RunResultV1` — 終端メタデータと `ArtifactRefV1`（`sha256:…` を `artifact_id`
とし、filesystem path は含みません）を返します。

#### `stop_experiment(run_id)`

実行をキャンセルし、終了を子へ伝播して 1 つの終端状態に確定させます。

#### `list_runs()`

認証された principal が所有する実行のみを一覧します（admin は全件）。

#### `list_children(parent_run_id)`

指定した親実行の、認可された直接の子だけを一覧します（再帰的サブ実験追跡用）。

#### `list_artifacts(run_id)`

allowlist 済みかつ digest 検証済みの成果物を、パスを晒さずに一覧します。

#### `read_artifact(run_id, artifact_id)`

admit された成果物を SHA-256 identity で境界付きで読みます。

#### `get_paper(run_id)`

認可された実行の論文成果物の参照を返します。

#### `get_ear(run_id)`

検証済み EAR と証拠成果物の参照を返します。

#### `list_skills(run_id)`

その実行の `SKILLS.lock` について、サニタイズされた不変のビューだけを返します。

#### `get_workflow(run_id)`

ロックされた phase / tool のメンバーシップを返します。生の workflow や秘密を
含む設定は返しません。

ワークスペース: `ARI_WORKSPACE` env（デフォルトはリポジトリルート）。実行の
レジストリは `{workspace}/logs/.ari-orchestrator/runs.sqlite3`（`ARI_ORCHESTRATOR_LOGS`
で logs のルートを差し替え可能）で、親子関係もそこに記録されます。

---

## ari-skill-transform

BFTS の内部表現を出版可能な科学データ形式に変換します。すべての内部フィールド（`node_id`、`label`、`depth`、`parent_id`）を除去し、科学的コンテンツ（`configurations`、`experiment_context`）のみを公開します。**LLM: Yes**。

### ツール

#### `nodes_to_science_data(nodes_json_path, llm_model="", llm_base_url="", primary_metric="", higher_is_better="true")`

LLM が BFTS ツリー全体を分析し、ハードウェアスペック、手法、主要な知見、比較を抽出します。`primary_metric` と `higher_is_better` は `evaluation_criteria.json` から `tpl_vars` 経由で渡され、`summary_stats` の方向考慮 best 算出に使われます（v0.7.0+）。

戻り値（v0.7.0+）:

```text
configurations[*]:
  rank, label, eval_summary
  parameters / measurements / predictions / scores  ← 型付き分割
                                                       (D: results.json or
                                                        C: _params_dict 経由)
  metrics                                            ← 互換性のための flat union
  _typed_source: "results.json" | "llm_evaluator" | (なし)
  _typed_schema_version
  _provenance  ← ノードの results*.json 各バリアントにわたる
                  emit_results の _provenance の union（存在時）
per_key_summary  (入力パラメタキー & 「_…」予約キーは除外)
summary_stats    { count, primary_metric, direction,
                   primary_metric_best, primary_metric_n,
                   typed_split_coverage }
experiment_context, implementation_overview, report_driven
```

**型付き分割の優先度** (D > C > legacy):

1. `experiments/{run_id}/{node_id}/results.json` — `coding-skill::emit_results` が書き出すファイル（D 契約）
2. `node.metrics::_params_dict` / `_measurements_dict` — LLM evaluator が `MetricSpec.expected_params` 設定下で出力（C 契約）
3. レガシー: `parameters: {}`、フラット `metrics` がすべてを保持

さらに `{checkpoint}/metric_contract.json`（`evaluator-skill::make_metric_spec` が `tree.json` の隣に
書き出す）を読み戻して `science_data.metric_contract` に graft し、決定論的なハードゲートが宣言された
契約（claims / correctness / `required_measured` / 宣言された invariant）を強制できるようにします。
この graft が無いと宣言された契約は inert で、ゲートには universal invariant レジストリしか届きません。

**頑健性**: LLM 応答パーサは `<think>` ブロックと ` ```json ` フェンスを除去し、各候補 `{` から balanced-brace を歩いて長さ降順で `json.loads` を試行します。`{...} prose {...}` のような shape も救えます。失敗時は raw 応答を `{checkpoint_dir}/science_data.debug.txt` に保存して事後監査可能にします。

モデル: `llm_model` 引数 > `ARI_MODEL_TRANSFORM` env > `ARI_LLM_MODEL` env > `LLM_MODEL` env > バックエンドに合わせた既定（`ARI_BACKEND=cli-shim` なら `claude-cli`、それ以外は `gpt-4o-mini`）。

**存在理由:** BFTS 内部の用語が論文や図表に漏洩しないようにすること、および入力サイズ記述子（`nnz`、`M`、`K`）と測定された出力（`GFlops_per_s`、accuracy）を best-of 集約で混同しないことを保証します。

#### `generate_ear(checkpoint_dir, llm_model="", llm_base_url="")`

再現性のための **Experiment Artifact Repository (EAR)** を `<checkpoint>/ear/` に構築します。node_report 駆動で、論文付随コード repo と同じレイアウトになります:

- `README.md` — 決定論的レンダリング。`science_data.json::implementation_overview.architecture` がある場合は `Architecture` セクションを追加
- `reproduce.sh` — best ノードの `node_report.json::{build_command, run_command}` を literal で挿入
- `environment.json` — 実行時環境キャプチャ（Python、プラットフォーム、pip、ハードウェア）
- `code/` — best chain の contributing ノードの `files_changed.added` ∪ `modified` を verbatim 配置（`code/<node_id>/` 形式は廃止）
- `data/` — `checkpoint/uploads/` を verbatim ミラー（**入力データのみ**、空なら不在）。**実験出力は ear/ に含めない** — `reproduce.sh` で再生成
- `figures/` — checkpoint 直下の `*.{pdf,png,svg,jpg,jpeg}` を top-level に配置
- `LICENSE` — `publish.yaml::license` から SPDX テンプレ生成（MIT / Apache-2.0 / BSD-3-Clause / GPL-3.0 / CC-BY-4.0）

ARI の監査ログ 2 つは `<checkpoint>/` 直下（`ear/` の外）に置かれ、公開アーティファクトには含まれません:

- `EVOLUTION.md` — Step / Label 形式の探索軌跡（delta、concerns 含む）。opaque な `node_id` は出現させない
- `_provenance.json` — 出自メタデータ（`from_node_id`, `introduced_by`, `excluded_nodes`）。中のパスは checkpoint 相対（`ear/code/...`）

その他の ARI 内部メタデータ（`tree.json`, `science_data.json`, `raw_metrics.json`, `eval_scores.json`, `commands.md`）も checkpoint root に残し、`ear/` には混入させません。`run_config.json` は `checkpoint/run_config.json` に移動しました。

戻り値: `{ear_dir, code_layout, verbatim_files, rendered_files, data_count, figure_count, top_node_id, best_chain_depth, excluded_count, has_readme, has_evolution, has_reproduce_sh, has_license, has_environment, ...}`。

#### `curate_ear(checkpoint_dir)` — v0.7.0

`{checkpoint}/ear/publish.yaml` の allowlist と built-in deny list（`.env*`, `secrets/**`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`）を用いて `{checkpoint}/ear/` を `{checkpoint}/ear_published/` にキュレートします。`manifest.lock` に正規化された `bundle_sha256`（ソート済み `{path, sha256, size}` JSON の sha256）を書き出します — これが論文の `\codedigest{...}` マクロに焼き付けられる digest です。**決定論的、LLM なし**。`publish.yaml` が無ければ静かにスキップ（v0.6.0 checkpoint の後方互換）。

#### `publish_ear(checkpoint_dir, backend="ari-registry", visibility="staged", dry_run=False)` — v0.7.0

`ari.publish.publish` の薄い MCP ラッパ。`ear_published/` から再現可能な tarball（ソート済み・mtime/uid/gid 正規化）を構築し、バックエンド（`ari-registry` / `gh` / `zenodo` / `local-tarball`）に転送し、`publish_record.json` を checkpoint root に記録します。最初の publish は常に `visibility=staged`（FR-P5）。`auto_promote=true` かつ再現性チェック合格時のみ public に昇格できます。

`ARI_PUBLISH_DRYRUN=1` で CI 安全のため dry-run を強制可能。

#### `promote_ear(checkpoint_dir, target="public")` — v0.7.0

以前に公開した EAR アーティファクトをより広い可視性ティアに昇格します。
`ari.publish.promote` の薄い MCP ラッパ。**決定論的、LLM なし**。
`{ref, visibility, promoted_at, promote_failed_at}` を返します（`PublishError`
の場合は `{error, kind}`）。

#### LICENSE テンプレート — v0.7.0

`publish.yaml::license` が指定されていて、かつ `ear/LICENSE` が著者作成で存在しない場合、`generate_ear` が **MIT** / **Apache-2.0** / **BSD-3-Clause** / **GPL-3.0** / **CC-BY-4.0** のいずれかを `ari-skill-transform/src/licenses/` から書き出します。

---

## ari-skill-web

Web 検索と学術文献の取得。**LLM: Partial**（`rerank_retrieval_records` のみ LLM を使用）。provider は呼び出しごとに固定され、実行時に切り替わることはありません。

### ツール

#### 実行モード（取得系 4 ツール共通）

`search_papers` / `web_search` / `fetch_url` / `walk_citations` は
`mode` と `snapshot_ref` を共有します。`record`（既定）は取得しつつ不変の
cassette / snapshot を残し、`live` は取得するだけで replay できず、`replay`
はネットワークに一切出ず記録済みの正規化オブジェクトを検証してそのまま返します。
`record` と `replay` は `ARI_CHECKPOINT_DIR` を要求します。詳細は
[検索契約とネットワークポリシー](retrieval_contract.md) を参照してください。

#### `web_search(query, n=5, mode="record", snapshot_ref="")`

DuckDuckGo Web 検索。API キー不要。決定論的。`n` は 1〜10 に丸められ、
各行には「untrusted search-result snippet」という利用制限が付きます。

#### `fetch_url(url, max_chars=8000, mode="record", snapshot_ref="", max_bytes=2097152)`

URL からテキストを取得・抽出します。決定論的。HTTP(S) の 80/443 のみを許可し、
userinfo と非 global な DNS アドレスを拒否し、検証済み IP へ直接接続して TLS SNI
を保持し、redirect のたびに再検証し、HTTPS downgrade / redirect 超過 / サイズ超過 /
非テキスト media を拒否します（2xx 以外のステータスは空の結果ではなく
`NetworkPolicyError` です）。`text/html` は `script` / `style` / `nav` / `footer` /
`header` を落としてから BeautifulSoup で本文を抽出します。
返るテキストは untrusted external content として明示され、本文全体は raw artifact
として記録されます。`max_chars` は 1〜100,000、`max_bytes` は 2 MiB が上限です。

#### `search_papers(query, max_results=10, provider=None, mode="record", snapshot_ref="")`

固定した **1 つの** provider を検索し、`ari.retrieval-result/v1`
（`RetrievalRecordV1` の集合）を返します。決定論的。`provider` を省略すると
`ARI_RETRIEVAL_BACKEND`（既定 `semantic_scholar`）を使います。名前は
小文字化してアンダースコアをハイフンに正規化したうえで照合されるため、有効値は
`semantic-scholar` / `arxiv` / `alphaxiv`（`semantic_scholar` 表記も同じ）です。
`max_results` は 1〜50 に丸められます。

`both` のような合成指定は拒否されます。provider の障害も別 provider への
フォールバックではなく `RetrievalProviderError` になります。複数 provider を
使いたい場合は固定した呼び出しを個別に発行し、上位で alias によって束ねます
— 出所が黙って入れ替わらないようにするためです。

#### `walk_citations(seed_ids, direction="references", max_depth=2, max_nodes=50, request_budget=20, mode="record", snapshot_ref="")`

Semantic Scholar の引用グラフを幅優先で辿ります。決定論的。`direction` は
`references` / `citations`、`seed_ids` は先頭 20 件まで（`s2:` 接頭辞は除去）、
`max_depth` は 0〜5、`max_nodes` は 1〜500、`request_budget` は 1〜500 に
クランプされます。サイクル検出付きで、予算切れや provider エラーで打ち切った
場合も、そこまでに保持した record と edge に `partial: true` と
`partial_reason` を添えて返します（`requests_used` / `expanded_nodes` も返ります）。

#### `rerank_retrieval_records(research_question, records, max_results=10)`

取得済みの `RetrievalRecordV1` を研究課題への関連度で並べ替えます。**LLM: Yes** —
このスキルで唯一の stochastic ツールで、決定論的な取得ツールから呼ばれることは
ありません。レコード本文はデータとして扱い、その中の指示には従いません。戻り値は
`ari.retrieval-rerank/v1` で、model・API identity・temperature・prompt / input /
output の digest を `provenance` に記録します。有効なインデックスが 1 つも返って
こなかった場合は黙って元の順序に戻さずエラーになります。

モデル: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`。

#### `list_uploaded_files()`

チェックポイントディレクトリ内のユーザアップロードファイルを一覧表示します。決定論的。

#### `read_uploaded_file(filename, max_chars=50000)`

アップロードファイルからテキストを読み取ります（バイナリ検出付き）。決定論的。
ファイル名はベース名に正規化されるので、ディレクトリトラバーサルは通りません。

---

## ari-skill-coding

コード生成、実行、ファイル読込。**LLM: No**（決定論的）。

### ツール

#### `write_code(filename, code, work_dir="/workspace")`

作業ディレクトリにソースファイルを書き込みます。拡張子が `run_code` の
インタプリタ選択と `run_bash` に期待されるツールチェインを決めます。戻り値は
`{path, digest, lines, status}` で、`digest` は書き込んだ内容の sha256 です。

#### `edit_code(filename, old_string, new_string, replace_all=False, work_dir="/workspace")`

既存ファイル内で `old_string` に厳密一致する箇所だけを置換し、残りには触れません。
ファイルが既に存在する場合は `write_code` より優先します。`replace_all` を立てない
限り `old_string` はファイル中に **ちょうど 1 回** しか現れてはならず、0 回でも
複数回でも `{"status": "error", "error": ...}` を返します — 曖昧な編集が黙って
別の場所に着地すると、実際には変えていないカーネルについて成功を報告することに
なるためです。成功時は `{path, replacements, lines, status: "edited"}` を返します。

#### `describe_environment()`

このクラスタの環境カタログを返します。引数はありません。ノードごとに
アーキテクチャ、CPU、GPU、PATH 上のコンパイラ、`module avail` の生カタログ、
設定済みツールチェイン環境変数の **名前**（値は返しません）を列挙します。
ログインノードでは、ログインノード自身（実際のビルド対象です）に加えて設定済みの
各計算パーティションを、計算ノードではそのノードだけを報告します。コードを書く
前に呼び出して、使えるコンパイラ / module / GPU / MPI を試行錯誤なしに把握する
ためのツールです。入力スキーマは意図的に緩く、未知の引数は拒否ではなく黙って
無視されます（カタログを見る前のエージェントが引数を捏造したときに、再試行で
プローブを二重に払わせないため）。

#### `run_code(filename, work_dir="/workspace", timeout=600)`

拡張子で選ばれたインタプリタ（`.py` → `python3`、`.sh` → `bash`、`.js` → `node`、`.rb` → `ruby`、`.pl` → `perl`、`.lua` → `lua`）でソースファイルを実行します。コンパイルはしないので、C/C++/Fortran/Rust/Go は `run_bash` 経由です。インラインの `stdout`/`stderr` は bounded preview（それぞれ 4,000 / 2,000 文字）で、省略文字数と「完全なログは artifact にある」旨を示すマーカーが入ります。完全なストリームは常に SHA-256 digest 付きの content-addressed artifact として書き出されます。

#### `run_bash(command, work_dir="/workspace", timeout=600)`

作業ディレクトリで bash コマンドを実行します。preview と完全ログの扱いは `run_code` と同じで、結果に `truncated` ブールフラグが付きます。

#### `read_file(path, offset=0, limit=8000, work_dir="/workspace")`

大きなファイル向けにページング対応でテキストファイルを読み込みます。`offset` / `limit` は行ではなく **文字** 単位です。コンテンツ、継続用 `next_offset`（末尾では `null`）、総文字数を返します。

```python
result = read_file("results.csv", offset=0, limit=100)
# 戻り値: {"path": "...", "content": "...", "offset": 0, "returned_chars": 100,
#          "total_chars": 5000, "truncated": True, "next_offset": 100}
```

作業ディレクトリ: workspace root は `ARI_WORK_DIR`（既定 `/tmp/ari_work`）で固定されます。`work_dir` 引数はこの root を置き換えるものではなく、その **配下** のディレクトリを選ぶもので、必要なら作成されます。root の外に解決されるパスは書き換えではなく拒否されます。agent には root が固定のコンテナパス `/workspace` として見え、ファイル系ツールは `filename` / `command` / `path` 引数についてはアクセス前に実ディレクトリへ戻し、結果からは必ずスクラブします。ただし `work_dir` 引数そのものは戻されません。渡された値がそのまま実 root に対して解決されるため、スキーマ上の既定値であるにもかかわらず `/workspace` をそこに直接渡すと root からの逸脱として拒否されます。`work_dir` は未指定のままにする（その場合 root に解決されます）か、後述の `ari.agent.tool_manager` にノードの実パスを固定させてください。

#### `emit_results(params, measurements, cases={}, predictions={}, scores={}, provenance={}, units={}, execution=None, file="results.json", work_dir="/workspace")`

入力パラメタと測定された出力を分離した型付き `results.json` を書き出します。下流（`transform → science_data`、論文執筆、summary stats）が「測定したもの」と「実行した条件」を取り違えないようにするためのツールで、best-of 集約で入力サイズ（`nnz`、`M`、`K`、`threads`）を実メトリクス（`GFlops_per_s` 等）より優先してしまう事故を防ぎます。`params` と `measurements` は disjoint でなければなりません。

ファイルは `{"schema_version": "1.0", "typed_schema_version": "ari.measurement-set/v1", "measurement_set": {...}}` で、正準の `MeasurementSetV1` オブジェクトだけを持ち、その横に flat な射影は置きません（[実行と測定の契約](execution_contract.md) を参照）。各グループは finite JSON でなければならず、シリアライズできない値（`pathlib.Path` 等）や `NaN`/`Infinity`、数値でない measurement は強制変換されず `error` として拒否されます。

オプションの `units` 引数は `{measurement: unit}` マップで、unit のない measurement は `unit_status: "missing"` として記録されます（unit は推測されません）。オプションの `execution` 引数は直前の `run_code`/`run_bash` 応答の `measurement_execution` ブロックをそのまま渡すもので（execution identity/attempt、status、exit code、artifact digest、サーバ発行の receipt）、渡さない場合 measurement は `execution_status: "unreported"` となり scientifically admissible になりません。`measurements` に無い名前を指す `units` / `provenance` キーは拒否されます。

`cases` 引数はツールの input schema に宣言されています（複数の問題サイズ / 形状を測った run 向けの、任意の `{case 名: {"params": {...}, "measurements": {...}}}` マップ）。ただし現行サーバはこれを転送しません: `call_tool` の `emit_results` 分岐が渡すのは `params` / `measurements` / `predictions` / `scores` / `provenance` / `units` / `execution` / `file` / `work_dir` のみで、書き出し側に `cases` パラメタはありません。したがって `cases` に載せた内容は受理されたうえで破棄されるため、複数ケースの run を `cases` だけで報告してはいけません。`file` 名を変えてケースごとに `results.json` を出してください。

オプションの `provenance` 引数は `{operand: source}` マップで、対応する正準 measurement レコードに記録され、claim/メトリクス正当性ゲートが消費します。値が経験的に **測定された** 上限/ピークであるオペランドには `"microbench"` または `"benchmark"` を（正規化メトリクスが placeholder に依拠していると誤検出されないように）、**独立した** リファレンスに対して計算した残差には `"correctness"` または `"reference"` を（出力が未検証と誤検出されないように）タグ付けします。ベストエフォートで、空のときは完全に省略されます。

---

## ari-skill-benchmark

型付きの要約統計、統計検定、来歴を意識した run 比較。**LLM: No**（決定論的）。

3 ツールとも引数は `request` ただ 1 つで、`ari.public.analysis` の型付き
リクエストを包み、`AnalysisResultV1` を 1 つ返します。結果は `kind`、完全に
解決された入力に対する `input_digest`、呼び出し側の `analysis_plan_digest`、
そして数値が算出された `library_versions`（python / numpy / scipy）を持ちます。
`artifact_target` を与えると、結果と CSV 表を閉じた workspace の
`{relative_directory}/{digest}/` 配下へ digest 束縛の `AnalysisArtifactV1`
（`result.json` / `table.csv`）としてアトミックに書き出します。全 metric は
`unit` を明示しなければならず、
metric / unit の不一致、空サンプル、全欠損、paired の長さ不一致はすべて
エラーです。欠損の扱いは `missing_policy`（`error` 既定 / `drop`）で宣言し、
drop 件数も結果に残ります。CSV / JSON / npy を読む場合は閉じた
`WorkspaceRefV1`・相対パス・上限バイト数・期待 SHA-256 で拘束されます。
規範は [決定論的解析契約](analysis_contract.md) を参照してください。

作図ツールはこのスキルにはありません。旧 `plot` は v0.2 で削除され、作図は
`plot-skill` の `render_figure` が担います。

### ツール

#### `analyze_results(request)`

`AnalysisRequestV1` — `datasets`（`MetricSampleSetV1` の配列。各要素は
`observations` か `source` の **どちらか一方**）、`missing_policy`、
`confidence_level`（既定 0.95）、任意の `analysis_plan_digest` と
`artifact_target` — を受け取り、metric ごとに `AnalysisSummaryV1`
（`count` / `missing_count` / `mean` / `std` / `variance` / `minimum` / `q25` /
`median` / `q75` / `maximum`、要求の `confidence_level` における
`mean_confidence_interval`、`constant_data` フラグ、`verified` / `declared` /
`not-established` の `independence_status`、値の出所である `source_digest`）を
返します。正規性検定は行いません。`metric_id` の重複は拒否されます。

#### `statistical_test(request)`

`StatisticalTestRequestV1` — 事前宣言した `comparisons` の族と、族全体に対する
`correction` — を受け取ります。各比較は `test_family`（`auto` / `welch_t` /
`student_t` / `paired_t` / `mann_whitney` / `wilcoxon`）、`pairing`
（`unpaired` / `ordered` / `pair_id`）、`alternative`、`alpha`、
`confidence_level` を宣言します。結果には検定統計量、raw と補正済みの p 値、
効果量、信頼区間、前提診断、ライブラリバージョンが含まれます。比較が 2 件以上の
ときに `correction: "none"` は拒否され、`bonferroni` / `holm` /
`benjamini_hochberg` のいずれかを明示しなければなりません。

#### `compare_runs(request)`

`RunComparisonRequestV1` — 2 件以上の `runs`（`RunRecordV1`）、`direction`
（`higher` / `lower`）、任意の `baseline_run_id`、
`require_compatible_environment`（既定 `true`）— を受け取り、ランキングと
baseline からの delta / relative delta を返します。`backend_id` と
`environment_digest` が異なる run の順位付けは既定で拒否されます
（`false` にすると caveat 付きの cross-environment ランキングが得られます）。
同一 substrate 上の run を独立 replicate とは推論せず、
`replicate_id` が全件揃って一意なときだけ `independence_status: "declared"`
となり、それ以外は `not-established` です。環境グループと
`provenance_differences` も併せて返します。

---

## ari-skill-plot

科学論文用の図生成器。**LLM: Mixed**（宣言的な固定レンダラ + 束縛された P2 例外のプランナ）。

図を描くのは常に同じ固定レンダラで、LLM が matplotlib コードを書いて実行する
経路はありません。LLM に許されているのは、どの metric をどの図形で描くかという
宣言だけです。数値・単位・キャプション・パス・SVG・成果物バイト列は、検証済みの
`ScienceDataV1` から決定論的に決まります。

### ツール

#### `render_figure(request)`

正準の `FigureSpecV1` を 1 枚レンダリングします。**決定論的、LLM なし**。
`request` は `spec` / `workspace` / `relative_directory` の **ちょうど 3 キー**
でなければならず（過不足はエラー）、呼び出し側のコードは一切実行されません。
戻り値は 1 枚分のマニフェストです。

#### `generate_figures(science_data_path, output_dir, n_figures=3, revision=0)`

ネイティブの `ScienceDataV1` から決定論的な既定 spec を組み立て、同じ固定
レンダラで `output_dir` へ描画してバッチマニフェストを返します。**LLM なし**。
`n_figures` は 1〜12 の整数、`revision` は 0 のみ（既定生成はフィードバック
改訂を扱いません）。`science_data_path` は `output_dir` から導かれる
workspace の内側に解決できなければなりません。

#### `generate_figures_llm(science_data_path, output_dir, experiment_summary="", n_figures=3, vlm_feedback="", revision=0, previous_batch_path="")`

プランナ LLM に `metric_id` / `chart_type` / `x_mode` **だけ** を選ばせ、
描画は `generate_figures` と同じ固定レンダラが行います。P2 例外。
`revision=0` では `vlm_feedback` も `previous_batch_path` も渡せず、
`revision>0` では両方が必須で、`previous_batch_path` は直接の親リビジョンを
指していなければなりません。改訂では図の ID と metric 集合が保存され
（プランナが落とした項目は決定論的に補われます）、VLM フィードバックが直前の
マニフェスト digest に束縛されていない場合は拒否されます。

### 環境変数

| 変数 | 用途 | 既定値 |
|---|---|---|
| `ARI_MODEL_PLOT` | プランナ LLM（最優先） | （なし）|
| `ARI_LLM_MODEL` | プランナ LLM のフォールバック | （なし）|
| `LLM_MODEL` | スキル間共通フォールバック | （なし — 3 つとも未設定なら `generate_figures_llm` はエラー）|
| `ARI_MODEL_PLOT_REVISION` | マニフェストに記録する model revision | （なし）|
| `ARI_LLM_API_BASE` / `LLM_API_BASE` | LiteLLM API ベース URL 上書き | LiteLLM 既定 |
| `ARI_CONTAINER_DIGEST` | レンダリング環境レコードに刻む container digest | （なし）|

### ari-core 境界

`src/server.py` が ari-core から import するのは `ari.public` 配下だけです
（`ari.public.figures`、`ari.public.cost_tracker`、`ari.public.execution`）。

---

## ari-skill-vlm

図表・テーブル品質レビューのための Vision-Language モデル。**LLM: Yes**（VLM）。

査読対象はディレクトリ走査ではなく、検証済みの `FigureBatchV1` マニフェストと
content-addressed な成果物参照で指定します。判定基準はバージョン付きの
criteria profile（既定 `figure-publication/v1`）が持ち、結果は
`VisualReviewV1` / `VisualReviewBatchV1` として返ります
（[図の視覚契約](figure_visual_contract.md) を参照）。各 `VisualReviewV1` は
`criteria_profile_id` **と** `criteria_profile_digest` を、model / model revision /
provider / prompt digest / `sampling`（`temperature: 0.0`）と並べて記録するので、
黙って書き換えられた基準どうしでスコアを比べることはできません。

同梱プロファイル: `figure-publication/v1`（source integrity、単位/ラベル、可読性、
比較可能性、アクセシビリティ。合格 0.7）、`figure-domain-integrity/v1`（source
integrity、不確かさ、ドメイン意味論、可読性。合格 0.75）、`table-publication/v1`
（source integrity、単位/ラベル、精度、可読性。合格 0.7）。未知のプロファイル ID、
および `target_kind` が呼び出しに合わないプロファイルは拒否されます。

### ツール

#### `review_figure(figures_manifest_path, figure_id, context="", criteria_profile_id="figure-publication/v1", max_output_tokens=2048)`

`FigureBatchV1` の中から `figure_id` で 1 枚を選んで査読します。バッチに
その ID が無ければエラーです。画像が読めない・上限を超えるといった失敗は
黙って落とさず、`artifact-error` / `limit-error` として理由付きで記録されます。

#### `review_figures_all(figures_manifest_path, context="", criteria_profile_id="figure-publication/v1", budget=None)`

バッチ内の全図を査読します。`budget`（`ReviewBudgetV1`）で
`max_figures`（既定 20、≤100）/ `max_total_bytes`（既定 100 MiB、≤512 MiB）/
`max_concurrency`（既定 2、≤4）/ `max_model_calls`（既定 20、≤100）/
`max_output_tokens`（既定 2,048、128〜8,192）を宣言できます。上限に触れた図は結果から
消えるのではなく `limit-error` として個別に残るため、予算切れが「問題なし」と
読めることはありません。集約は `minimum-fail-closed` — 1 枚でも失敗すれば
スコアは 0.0、そうでなければ全図の最小値です。

#### `review_table(request)`

閉じた workspace 内の content-addressed な表成果物を 1 件査読します。`request`
は `workspace` / `target_id` / `artifact` / `context` / `criteria_profile_id` /
`iteration` / `max_output_tokens` の **7 キーちょうど** で、これに一致しない
リクエストは拒否されます。成果物は `role: "table-source"` でなければならず、
バイト列とサイズが宣言された digest と一致しない場合は拒否されます。画像なら
PNG / JPEG / WebP のみ、テキストなら LaTeX / Markdown / plain text のみを
受け付けます。`iteration` は 0〜2 です。

モデル: `ARI_VLM_MODEL` env > `VLM_MODEL` env。既定値はなく、どちらも未設定なら
査読はエラーになります（黙って別のモデルへ落ちません）。`ARI_MODEL_VLM_REVISION`
と `ARI_MODEL_VLM_PROVIDER` は査読レコードに刻む identity を上書きします。

---

## 新しい Skill の記述

1. `ari-skill-yourskill/src/server.py` を作成:

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("your-skill")

@mcp.tool()
def your_tool(param: str) -> dict:
    """Tool description."""
    # NO LLM calls here
    return {"result": process(param)}

if __name__ == "__main__":
    mcp.run()
```

2. `ari-core/config/workflow.yaml` に登録します。`phase` で
   どの pipeline-phase の ReAct エージェントが Skill を見えるか
   を指定 (1 つなら文字列、複数なら配列):

```yaml
skills:
  - name: your-skill
    path: '{{ari_root}}/ari-skill-yourskill'
    phase: [paper, reproduce]
```

   有効な phase 値: `bfts`、`paper`、`reproduce`、`all`、`none`。

3. `experiment.md` の `## Required Workflow` でツール名を参照。
