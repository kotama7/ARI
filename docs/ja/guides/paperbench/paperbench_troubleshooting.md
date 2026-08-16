---
sources:
  - path: ari-skill-paper-re
    role: implementation
  - path: ari-skill-replicate
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/PaperBench/PaperBenchWizard.tsx
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: report/scripts/paperbench_report.py
    role: implementation
last_verified: 2026-08-16
---

# PaperBench トラブルシューティング

頻出する障害モードとその対処。 監査実行パイプラインは
`generate_rubric → audit_rubric → build_reproduce_sh → run_reproduce →
grade_with_simplejudge` で、 障害は通常このいずれかのステージに属する。
`audit_rubric` は non-fatal — 監査が失敗してもログに残るだけで run は続く。

## ルーブリック生成

### Q. ルーブリックのリーフ数が 0 になる

ジェネレータが 3 回のリトライすべてで有効な JSON を生成できなかった。
worklog の最終失敗を確認。 典型的な原因:
- LLM レートリミット (数分後に再試行)
- 論文 PDF が空文字列に parse された — 再アップロード or
  事前に `pdftotext` で変換

### Q. grader load 時に `task_category` エラー

grader は `"Result Visualization"` 等の PaperBench 非標準カテゴリを
拒否する。 ジェネレータの `normalize_rubric_node` パスがこれらを
allow-list (`Code Development`, `Code Execution`, `Result Analysis`) に
クランプするはず。 持続するなら最新の `gemini-2.5-pro` ビルドで再生成 —
古いモデルほどドリフトが大きい。

## レプリケータ (BasicAgent)

### Q. エージェントが `reproduce.sh` を一切書かなかった

12 h ロールアウトが `submit` を呼ばずに時間切れになった。 考えられる
原因:
- モデル出力が truncated (`agent.log` で `TOOL OUTPUT TRUNCATED` を確認 —
  通常は無害)
- 論文テキストがモデルの context を超過; 小さい論文か
  `iterative_agent=true` を試す

### Q. GPU 論文に対して CPU コードを submit した

rubric の `execution_profile.kind` が空の可能性が高い。 確認:

```bash
jq '.reproduce_contract.execution_profile' rubric.json
```

再生成しても埋まるとは限らない: `skeleton.md` は、論文が並列 / 分散実行の
性質 (「N MPI ランクで評価した」「M GPU のデータ並列で学習した」など) を
明示していない限り **`execution_profile` フィールドごと省略せよ** と
ジェネレータに指示している。 シングルマシン論文 (シングル GPU を含む) では
プロファイル不在が意図した結果で、 `_format_hpc_appendix` はプロファイルが
空なら HPC ガイダンスを一切出力しない。 論文が実際に GPU / 並列構成を
記載していてジェネレータが取りこぼしたなら再生成する。 そうでなければ
ルーブリックにプロファイルを明示的に書く (`kind` は `cpu_single`、
`gpu_single`、 `gpu_multi`、 `mpi`、 `mpi_gpu` のいずれか)。

### Q. MPI 論文なのにエージェントが `srun` を使わなかった

`agent.log` の user message に `COMPUTE-NODE EXECUTION CONVENTIONS`
block があるか確認。 欠如している場合、 呼出側が `execution_profile`
を渡していない。 ワイヤリング検証 — このスキルは `ari_skill_paper_re`
パッケージではなくフラットなトップレベルモジュール (`_replicator_agent`、
`server` など) を提供するので、 import には `ari-skill-paper-re/src` を
`PYTHONPATH` に置く必要がある:

```bash
PYTHONPATH=ari-skill-paper-re/src python -c "
from _replicator_agent import _format_hpc_appendix
print(_format_hpc_appendix(
    expected_artifacts=['results.csv'],
    execution_profile={'kind': 'mpi_gpu', 'metric_columns': ['x']},
    cluster_shape={'SLURM_JOB_NUM_NODES':'4','SLURM_NTASKS':'32','GPU_LIST':'v100'}
))"
```

出力に `srun -n $SLURM_NTASKS` が含まれるはず。

## SLURM ディスパッチ (`run_reproduce`)

### Q. `sbatch: error: Invalid GRES gpu:v100:1`

選択partitionが型付きGPU要求を満たせない。`sinfo -o '%P %G'`で確認し、
対応partitionを選ぶかsiteのGRES設定を修正する。ARIは要求を削除してCPU実行しない。

### Q. sbatch は成功したが `reproduce.sh` がシングルノードでしか動かない

`reproduce.sh` は最初の allocated node に 1 rank として起動する。
エージェントプロンプトは `srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS`
fan-out を指示する — 実際に行が存在するか確認:

```bash
grep -E 'srun.*-N.*-n' repro_sandbox/reproduce.sh
```

ない場合は手動で追記 or 強力なモデルで再生成。

### Q. compute node で `mpirun: command not found`

OpenMPI が compute node 環境にロードされていない。 どちらか:
- ルーブリックの `reproduce_contract.execution_profile.module_loads` に
  `"openmpi/4.1"` (クラスタ名) を追加
- スクリプトを `srun` に切替 (PMI 統合; ほとんどの SLURM サイトで
  明示的 OpenMPI モジュールなしで動く)

### Q. ジョブは動くが rank > 0 で `repo_dir` のファイルが消えている

`repo_dir` がノードローカル FS 上。 ARI は警告するが、対処は
checkpoint を共有 mount (`$HOME`, `/work/...`, `/scratch/...`) に
移すこと。

### Q. `--mem=256G` がパーティション上限を超える

ルーブリックがサイト超過のメモリを指定。 ウィザード Step 3 で上書き
(`memory_gb_per_node = <あなたの上限>`)、 または rubric JSON で
`execution_profile.memory_gb_per_node` を直接編集する。

## 採点 (`grade_with_simplejudge`)

### Q. 採点レスポンスに `ors_score` がそもそも無い

`ors_score` / `raw_score` / `score_stddev` は、 grade report の status が
`failed` でないときにのみ現れる。 検証済みの再現に到達できなかった grader は
数値を publish しない: `grade_status: "failed"` を `error` / `errors` 付きで
返し、 保存されるレポートは `ors_score: null` を持つ。
`grade_with_simplejudge` は `status` が `succeeded` の `ReproductionRunV1`
を解決できない限り採点を拒否する。 よくある `errors` の値は
`no verified ReproductionRunV1 is available`、
`reproduction status is <state>; only succeeded runs are gradable`、
`judge returned invalid scores for leaves: ...`。

再現レコードはフラットな結果ファイルではなく再現 workspace の下にある:

```bash
ls repro_sandbox/                                  # reproduce.sh 存在?
jq . repro_sandbox/.ari-reproduction/latest.json   # pointer: status / run パス / executed workspace
jq '.attempts[-1].status, .attempts[-1].exit_code, .attempts[-1].expected_missing' \
   repro_sandbox/.ari-reproduction/<plan_digest>/run.json
```

grade report 自体は `grade_report_path` が指す grade root 配下の
`grade-report.json` に書き出される。

### Q. ネガティブコントロールが pass しない (boilerplate が >5%)

ルーブリックのリーフが緩すぎる — 汎用ボイラープレートにパターン
マッチしてしまう。 特定の log 出力 / artefact 内容を要求する
`task_category="Code Execution"` の claim を厳しくして再 audit。

## GUI / ウィザード

### Q. ウィザードが「論文がまだ登録されていません」のまま

`<workspace_root>/paper_registry/manifest.jsonl` の存在と非空を確認。
レジストリは `PathManager.paper_registry_root` 経由で workspace を
ルートに解決され、 `~/.ari` 配下のユーザ単位ディレクトリではない
(ARI は v0.5 以降グローバルなユーザ単位データディレクトリを持たない)。
`ARI_PAPER_REGISTRY_DIR` を設定しているならパスがそれに従う。

### Q. 起動ボタンが無効のまま

Step 1 (論文) で 1 件以上選択必要。 Launch ボタンも論文ステップの Next
ボタンも、 どちらも `selectedIds.size === 0` でガードされている。

### Q. コスト見積もりが `$0`

論文が 1 件も選択されていない。 ウィザードは
`llm_cost_usd × selectedIds.size` を表示するので、 選択が空なら Step 3 を
どう設定しても `$0.00` になる。

`time_limit_sec` は原因になり得ない: サーバ側の見積もりは
`time_limit_sec or 12*3600` を読むので `0` は 12 h の既定に戻り、
そもそも LLM コスト項は論文 1 件あたりの固定値 (rubric `$0.45` +
reproduce `$2.00` + judge `$0.10 × n_runs`) で time limit に依存しない —
依存するのは `wall_time_sec` だけ。 数値が出ないもう一つの経路は見積もり
リクエスト自体の拒否で、 未知の `rubric_config` キーがあると
`POST /api/paperbench/cost-estimate` は
`{"error": "unknown rubric_config fields: ..."}` を返しコストフィールドを
一切含めない。

## レポート生成

### Q. 監査レポートが `.tex` だけで PDF が出ない

`latexmk: command not found` というエラーは出ない — PDF ステップは
`shutil.which("latexmk")` でガードされており、 ツールが無ければ黙って
スキップされ、 コマンドは `.tex` ソースだけを書いて `ok` で終了する。
(`latexmk` が*ある*場合でも `check=False` で実行されるため、 LaTeX が
失敗すると `main.pdf` が残らないだけで例外は上がらない。)
PDF ターゲットには XeLaTeX が必要: `texlive-xetex`
(Debian/Ubuntu) または `mactex` (macOS) をインストールする。 意図的に
`.tex` のみを出力するには:

```bash
python -m report.scripts.paperbench_report paper \
    --checkpoint <ckpt> --paper-id <id> \
    --output-root report/audit/<id> \
    --formats tex   # PDF スキップ
```

### Q. ja/zh PDF で CJK 文字が箱表示

ja/zh ミラーは XeLaTeX + Noto CJK font 必須。 `report/setup_fonts.sh`
実行と `fc-list | grep -i 'noto.*cjk'` で確認。

## v0.8.0 アップデート: sandbox / GPU エラー

### Q. `"error": "sandbox runtime is unavailable: docker"`、`failure_kind: "sandbox-unavailable"`

caller が sandbox kind を明示した場合、`run_reproduce` はホストローカル
実行への暗黙の fallback を拒否する。例外は上がらない: 拒否は immutable な
失敗 attempt として記録され、`executed: false`、`error`、`failure_kind`
(`sandbox-unavailable`、SLURM 経路なら `scheduler-failure`) を持つ dict と
して返る。呼び出し側で `RuntimeError` を探しても見つからない。

チェックは launch 時の `shutil.which(<runtime>)` — 明示的な
`sandbox_kind=docker` に対して docker *daemon* が probe されることはない
(`auto` 解決のときだけ) ので、「runtime unavailable」は binary が `PATH`
に無いという意味。`apptainer` / `singularity` の binary 不在、`slurm` の
sbatch 不在 / partition 解決失敗 にも同じ fail-closed 規則が効く。

### Q. `"error": "reproduction plan rejected: ..."`

attempt が作られる前に plan が拒否されたので、何も実行されていない。
よくある原因は 3 つ:

1. `sandbox_kind=<container> requires an immutable container image` —
   `container_image` も `ARI_PHASE1_DOCKER_IMAGE` /
   `ARI_PHASE1_APPTAINER_IMAGE` も無い。
2. mutable な image 参照。Docker は完全な `sha256:<image-id>` か
   `name@sha256:<digest>`、remote Apptainer 参照は `@sha256:<digest>` 必須、
   ローカル SIF は symlink でない通常ファイルであること。
3. `sandbox_kind=... cannot prove network denial` — `network_policy` の
   既定は `deny` で、`local` / `slurm` はコンテナ namespace ではない。
   `network_policy="inherit"` を明示するか、管理者の attestation を
   `network_isolation_attested=True` で渡すか、コンテナで実行する。

### Q. GPU を要求したのに GPU 無しで返ってきた

silent downgrade は意図的に存在しない: ARI は型付き要求をそのまま投入する。
`gpus_per_task` は `#SBATCH --gpus-per-task=[<type>:]<n>`、`gpus_per_node`
は `#SBATCH --gres=gpu:[<type>:]<n>` として出力され、両者は排他的な分岐で、
両方指定すると submit 前に "mutually exclusive" で拒否される。scheduler が
GRES を拒否する場合は、site の GRES 設定を直すか、そのリソースを広告して
いる partition を選ぶ (`sinfo -o '%P %G'`)。

### Q. agent が Stage 1 を動かしたが Stage 3 で全 leaf が 0 点

2 つの原因 (v0.8.0 で両方対処済み):

1. **submission に `reproduce.log` が無い** — Stage 2 がスキップされ、
   upstream なら vendor SimpleJudge の safeguard 「`reproduce.sh` failed
   to modify or create any files. All result analysis tasks will be graded
   as 0」 が発火する状況。ARI は代わりに、再現レコードが無いことを理由に
   スコアを publish せず拒否する。Stage 2 を実行するか、code-only の
   study を明示的に選んだうえで検証済みの Stage 2 レコードを作ること。
2. **`paper_audit_mode` が誤って ON** — paper-audit mode は論文自体を
   採点。`code_only` と排他で、両方 True なら bridge が `ValueError`。

### Q. ソースをコミットしたのに `reproduce.sh` が `src/…: No such file or directory` で失敗する

エージェントがリポジトリを 1 階層深く構築してしまった。ARI のホスト側
sandbox は workspace を cwd として提示し、vendor の `/home/submission`
パスを相対 `submission/` に書き換える。そのためプロンプトを literal に
従ったエージェントは、自己完結リポジトリ (`reproduce.sh` + `src/`) を
`<workspace>/submission/` 配下に置いてしまう。 post-rollout 処理が
`reproduce.sh` だけを workspace root へ promote し、ソースから孤立させて
いた。Stage 2 はその孤立コピーを実行するため build が `src/…` を見つけ
られず、Code Execution / Result Analysis の全 leaf が 0 点になっていた。

v0.8.0 はこれを自動的に解決する: `reproduce_submission` と
`judge_submission` は、実リポジトリ (`reproduce.sh` が `.git` / ソースと
co-located) を保持する nested な `submission/` がある場合そこへ降りる。
これにより `reproduce.sh` の相対パスは、エージェント自身の
`cd submission && bash reproduce.sh` チェック時とまったく同様に解決される。
対応不要; 孤立した top-level コピーは無視される。旧来の失敗が見えるなら
v0.8.0 上にいるか確認すること。

### Q. エージェントの `apply_patch` / `applypatch` 編集が `command not found` で失敗する

gpt-5 / codex モデルは、ARI / vendor のどのプロンプトも指示していないのに
`apply_patch <<'PATCH' … PATCH` でファイルを編集しようとする習性がある。
vendor Docker image は `/bin/apply_patch` をインストールするが、ホスト側の
`LocalComputer` は image を build しないため、v0.8.0 以前はそうした呼び出し
が毎回失敗し、エージェントは `cat`-heredoc に fallback する前に tool-call
budget を浪費していた。

v0.8.0 は vendor のセットアップをミラーする: `LocalComputer` は vendor 自身
の `apply_patch.py` を包む wrapper を workspace の `bin/` ディレクトリに
(`apply_patch` と `applypatch` 両方の名前で) 配置し、各エージェントコマンド
が共有する shell PATH の先頭に prepend する。vendor モジュールが見つから
ない場合は gracefully に degrade する (PATH 変更なし、heredoc fallback)。
対応不要; これはホスト sandbox 限定 (Apptainer SIF は既に
`/bin/apply_patch` を持つ)。

## v0.8.0: HF_TOKEN / agent.env

### Q. 論文が gated dataset / model のため HF_TOKEN が必要

`setup.sh` の interactive prompt で登録するか、`.env` に追加:

```
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

`bridge.rollout_submission` が calling process env から自動転送する。
paper 別 credentials は `~/.ari/agent.env` に `KEY=VALUE` 形式で配置 —
bridge が `agent_env_path=None` 時に auto-discover。 `ARI_AGENT_ENV_PATH`
で path 上書き可。

## リトライ + executed-submission tarball

### Q. Python 3.11 / venv が無くて `reproduce.sh` が即失敗する

salvage wrapper は存在しない。`salvage_retries` と `retry_threshold_sec`
は `bridge.reproduce_submission` の引数では**ない** — submission の環境を
書き換えて再実行する vendor の
`reproduce_on_computer_with_salvaging` 経路に ARI 相当物は無く、
`test_reproduce_submission_signature_includes_tarball_not_unsafe_salvage`
がその引数の不在を assert している。`reproduce.sh` 自体 (または container
image) の中で環境を直したうえで、同じ plan で `reproduce_submission` を
もう一度呼ぶこと: `run_reproduce` はスクリプトを書き換えるのではなく、
immutable にリンクされた attempt を追記する。

### Q. executed submission の tarball はどこにあるか

既定では reproduce 呼び出しのたびに `submission_executed_<UTC>.tar.gz` が
生成されるが、置かれるのは*実行された* submission の隣 — すなわち
`.ari-reproduction` 配下の非公開 attempt ツリーの中であり、渡した
`submission_dir` の隣ではない。返却 dict の `executed_tarball` キーが
絶対パスで、`executed_tarball_digest` と `executed_tarball_size_bytes` が
併記される。出力先は `tarball_dir=` で上書き、`capture_tarball=False` で
抑止できる。capture の失敗が run を落とすことはない: ログに出したうえで
結果の `warnings` リストに追記されるので、`executed_tarball` キーが無く
`warnings` エントリがある形が探すべきシグネチャ。

## 関連

- [クイックスタート](paperbench_quickstart.md)
- [マルチノード設定](multi_node_setup.md)
- [計算ノード安全規約](compute_node_safety.md)
- [実行プロファイル仕様](../../reference/execution_profile.md)
- [PaperBench API + bridge contract](../../reference/api_paperbench.md)
- [環境変数](../../reference/environment_variables.md)
