---
sources:
  - path: ari-skill-paper-re
    role: implementation
  - path: ari-skill-replicate
    role: implementation
last_verified: 2026-05-25
---

# PaperBench トラブルシューティング

頻出する障害モードとその対処。 監査実行パイプラインは
`rubric_path → build_reproduce_sh → run_reproduce → grade_with_simplejudge`
で、 障害は通常この 4 ステージのいずれかに属する。

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

空ならルーブリックを再生成 (v0.7.2 の `skeleton.md` プロンプトは
論文の experimental-setup セクションから `execution_profile` を埋める
よう LLM に指示する)。

### Q. MPI 論文なのにエージェントが `srun` を使わなかった

`agent.log` の user message に `COMPUTE-NODE EXECUTION CONVENTIONS`
block があるか確認。 欠如している場合、 呼出側が `execution_profile`
を渡していない。 ワイヤリング検証:

```bash
python -c "
from ari_skill_paper_re._replicator_agent import _format_hpc_appendix
print(_format_hpc_appendix(
    expected_artifacts=['results.csv'],
    execution_profile={'kind': 'mpi_gpu', 'metric_columns': ['x']},
    cluster_shape={'SLURM_JOB_NUM_NODES':'4','SLURM_NTASKS':'32','GPU_LIST':'v100'}
))"
```

出力に `srun -n $SLURM_NTASKS` が含まれるはず。

## SLURM ディスパッチ (`run_reproduce`)

### Q. `sbatch: error: Invalid GRES gpu:v100:1`

クラスタが GRES 未設定。 v0.7.2 は `_slurm_has_gres()` 経由で
flag を自動的に落とす — エラーが残るなら旧ビルド、 または `sinfo`
が PATH に無い。 ワークアラウンド: ウィザード Step 3 の *実行
プロファイル上書き* で `gpu_type` を空にする。

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
- ルーブリックの `module_loads` に `"openmpi/4.1"` (クラスタ名) を追加
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

### Q. `ors_score` がぴったり `0.0` になる

grader が `reproduce.sh` または expected artefacts をどれも見つけられ
なかった。 確認:

```bash
ls repro_sandbox/                  # reproduce.sh 存在?
jq '.executed, .exit_code' repro_result.json   # クリーンに走った?
jq '.missing' repro_result.json    # expected_artifacts の不足?
```

よくある原因: エージェントが workspace root ではなく
`submission/reproduce.sh` を書いた。 v0.7+ は自動 promote するが、
旧ビルドなら手動で cp。

### Q. ネガティブコントロールが pass しない (boilerplate が >5%)

ルーブリックのリーフが緩すぎる — 汎用ボイラープレートにパターン
マッチしてしまう。 特定の log 出力 / artefact 内容を要求する
`task_category="Code Execution"` の claim を厳しくして再 audit。

## GUI / ウィザード

### Q. ウィザードが「論文がまだ登録されていません」のまま

`~/.ari/paper_registry/manifest.jsonl` の存在と非空を確認。
`ARI_PAPER_REGISTRY_DIR` を設定しているならパスがそれに従う。

### Q. 起動ボタンが無効のまま

Step 1 (論文) で 1 件以上選択必要。 `selected_count >= 1` まで無効。

### Q. コスト見積もりが `$0`

Step 3 (再現) で `time_limit_sec` を設定していない。 既定 12 h;
0 は再現の wall-time 項を消す。

## レポート生成

### Q. `latexmk: command not found`

監査レポート PDF 出力には XeLaTeX 必要。 `texlive-xetex`
(Debian/Ubuntu) または `mactex` (macOS) インストール、 あるいは PDF
スキップして `.tex` ソースのみ出力:

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

### Q. `RuntimeError: sandbox_kind=docker requested but docker daemon is not reachable`

docker daemon が起動していないか到達不能。bridge / `run_reproduce` は
silent fallback を拒否する。docker を起動するか、`sandbox_kind` を
別の値 (`local` / `apptainer` / `slurm`) に変えるか、または legacy
fallback を opt-in する: `export ARI_PHASE1_ALLOW_FALLBACK=1`。
`sandbox_kind=apptainer` の binary 不在、`sandbox_kind=slurm` の sbatch
不在 / partition 解決失敗 にも同じ対処。

### Q. `RuntimeError: GPU resources requested ... but cluster has no GRES configured`

クラスタの SLURM に GPU GRES 設定が無いが、caller が `gpus_per_task` /
`gpu_type` を指定。bridge は拒否する (36 h queue 待った後 all-CPU 実行
は最悪の failure mode)。 解決策:

1. SLURM の GRES 設定を直す
2. GRES 設定済 partition を選ぶ (`sinfo -o '%P %G'` で確認)
3. silent drop を opt-in: `export ARI_SLURM_ALLOW_NO_GRES=1`

### Q. agent が Stage 1 を動かしたが Stage 3 で全 leaf が 0 点

2 つの原因 (v0.8.0 で両方対処済み):

1. **`reproduce.log` 不在** — Stage 2 がスキップされ vendor SimpleJudge
   の safeguard 「`reproduce.sh` failed to modify or create any files.
   All result analysis tasks will be graded as 0」 が発火。v0.8.0 で
   judge が `code_only=True` を自動有効化し rubric を Code Development
   葉のみに pruning する。
2. **`paper_audit_mode` が誤って ON** — paper-audit mode は論文自体を
   採点。`code_only` と排他で、両方 True なら bridge が `ValueError`。

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

## v0.8.0: salvage retries + executed-submission tarball

`bridge.reproduce_submission(salvage_retries=N, retry_threshold_sec=60)`
で early-failure (exit≠0 かつ elapsed<threshold) 時に Python 3.11 + venv
prelude 付き salvage wrapper で N 回 retry。総 wall-clock budget は
attempts 跨いで honor。

毎回 `submission_executed_<UTC>.tar.gz` が `submission_dir` 隣に生成。
返却 dict の `executed_tarball` キーが絶対パス。`capture_tarball=False`
で抑止、`tarball_dir=` で出力先上書き。

## 関連

- [クイックスタート](paperbench_quickstart.md)
- [マルチノード設定](multi_node_setup.md)
- [計算ノード安全規約](compute_node_safety.md)
- [実行プロファイル仕様](../../reference/execution_profile.md)
- [PaperBench API + bridge contract](../../reference/api_paperbench.md)
- [環境変数](../../reference/environment_variables.md)
