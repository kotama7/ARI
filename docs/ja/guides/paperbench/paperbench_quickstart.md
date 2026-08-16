---
sources:
  - path: scripts/sc_paper_dogfood.py
    role: doc
  - path: scripts/build_pb_images.sh
    role: doc
  - path: ari-skill-paper-re
    role: implementation
  - path: ari-skill-replicate
    role: implementation
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/PaperBench
    role: implementation
  - path: ari-core/config/paperbench_rubrics
    role: config
  - path: report/Makefile
    role: config
last_verified: 2026-08-16
---

# PaperBench クイックスタート

外部論文の登録から PaperBench audit スコア表示までを 5 分で通すチュートリアル。

## 前提条件

- ARI インストール済み (`pip install -e ari-core/`)。
- viz サーバ起動済み (`ari viz` または `python -m ari.viz.server`)。
- `.env` に LLM プロバイダ鍵が設定されている (`OPENAI_API_KEY` /
  `GEMINI_API_KEY` など)。
- SLURM ディスパッチを使う場合: `sbatch` が PATH 上にあり、
  [`docs/guides/paperbench/multi_node_setup.md`](multi_node_setup.md) を準備済み。

## 1. 論文を取り込む

ダッシュボードの **📚 PaperBench** サイドバーから **📥 論文を取り込む**
を開き、フォームに記入 (arXiv ID / DOI / アップロード) して
**レジストリに保存**。ライセンス入力欄の下に出るバッジはクライアント側の
楽観的な正規表現判定で、緑になるのは `MIT` / `Apache*` / `BSD*` /
`arXiv*` / 素の `CC BY` のみ。`CC0` と `CC BY-SA` はサーバ側が usable と
分類するのにフォーム上は ⚠ になる。サーバの判定はレジストリ一覧の行に
表示される。

CLI 等価:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "arxiv",
    "source": "2404.14193",
    "title": "LLAMP: assessing latency tolerance",
    "license": "CC BY 4.0",
    "authors": ["Alice", "Bob"]
  }'
```

## 2. PaperBench ウィザード起動

レジストリ画面で論文をチェックし、**🚀 PaperBench を実行**。5 step:

1. **論文選択**。
2. **ルーブリック** — 生成モデル (既定 `gemini/gemini-2.5-pro`、
   calibrated `hierarchical-v2` 戦略 — 戦略は選択できない)。
   [ルーブリック仕様](../../reference/rubric_schema.md) 参照。
3. **再現** — 再現モデルと時間上限。「実行プロファイル上書き」を展開すると
   グリッドが実際に描画する SLURM 配置フィールド (`--nodes`, `--ntasks`,
   `--ntasks-per-node`, `--gpus-per-task`, `gpu_type`,
   `memory_gb_per_node`, `--exclusive`, `--constraint`, `--hint`,
   `--nodelist`) を上書きできる。`account` / `qos` / `reservation` に
   専用フィールドはない — グリッド内の自由記述欄 `extra_sbatch_args` が
   受け付けるのは `--account=` / `--qos=` / `--reservation=` /
   `--hint=` のエントリだけで、skill がこれらを型付きフィールドに変換する。
   それ以外のフラグは拒否される。ウィザードのフィールドは常に `0` / `""`
   から始まり pre-fill はない。ルーブリックの `execution_profile` は
   サーバ側の `run_reproduce` でマージされ、非ゼロのウィザード値が
   ルーブリックのヒントに優先する。
4. **採点** — SimpleJudge モデルと `n_runs` (既定 1, PaperBench 論文 §4.1)。
5. **実行** — コスト見積もりを確認、*Dry run* で検証後 *すべて実行* で
   ジョブ投入。

## 3. 待機

ジョブ ID は論文ごとに 1 つ返る。`#/paperbench/results?job=<job_id>` を
開くと、Results 画面が `GET /api/paperbench/run/<job_id>` を 1 回だけ
読んでステータスを取得し、以降は
`GET /api/paperbench/run/<job_id>/logs` の Server-Sent Events で
`completed` / `failed` / `interrupted` に達するまでジョブを追跡する。
所要時間: CPU のスモークなら 30 分前後、GPU の忠実再現なら数時間。

> viz サーバ再起動で worker が道連れに死んだジョブはステータス
> `interrupted` で報告され、再起動されることはない — ウィザードから
> 実行し直す。

## 4. スコア確認

`completed` になると Results 画面でルーブリック木 + リーフごとの合否
+ ORS スコアが表示される。生 JSON は
`GET /api/paperbench/run/<job_id>/results`。

## 5. 監査レポート生成 (任意)

人間向けのレポートを生成する。`AUDIT_FORMATS` の既定は `pdf` のみ
なので HTML が欲しければ明示的に指定する。`AUDIT_LANGS` の既定は `en`、
`AUDIT_OUTPUT` の既定は `audit/$(PAPER_ID)`:

```bash
make -C report audit-report \
  CHECKPOINT=/var/tmp/ari/.../<checkpoint-id> \
  PAPER_ID=<paper_id> \
  AUDIT_LANGS="en ja zh" \
  AUDIT_FORMATS="pdf html"
```

同じレンダラは GUI からは `POST /api/paperbench/run/<job_id>/report`
で呼べる。この経路の既定は `["pdf", "html", "md"]` で、出力は
`{registry_root}/reports/<job_id>/` 配下に書かれる。

Python API は [`report/scripts/paperbench_report.py`](../../../../report/scripts/paperbench_report.py)。

## 6. (応用) venue 別のルブリック枠組み切り替え

`generate_rubric` は既定で従来の PaperBench 枠組み (直下ノード = 貢献ごと
の分解、葉 = submission 出力の採点) を使う。**論文監査** (paper が再現可能性
を十分に記述しているか?) を行いたい場合は `paperbench_rubric_id` で venue 別
テンプレートを選択する。同梱 ID:

- `generic` — 後方互換の既定
- `sc` — HPC 6 軸 (環境 / データ / 実行 / 図表 / scaling / 結論)
- `neurips` — NeurIPS Reproducibility Checklist 軸
- `nature` — wet-lab Reporting Summary 軸

CLI ドッグフード (GUI 不要、SLURM 不要、`generate_rubric_async` を
`scripts/sc_paper_dogfood.py` から直接呼ぶ):

```bash
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/sc24_paper.pdf \
    --rubric-template sc \
    --rubric-model gpt-5-mini \
    --target-leaves 30
```

出力 `rubric.json` は `sc.yaml` の `top_level_axes` に対応した 6 個の直下
ノードを持つ**はず**であり、葉の文体も「実装が X を行う」から「X は paper
または AD で特定可能か」に切り替わる**はず**である。ただしどちらも
プロンプト指示だけで担保されている (`build_skeleton_venue_hint` が
「DO NOT ADD, REMOVE, RENAME, OR REORDER」という規範ブロックを出す) —
直下ノードがドリフトしたルーブリックを弾く validator は無いので、
スクリプト出力の `[rubric.summary] direct_children=` を確認すること。
新 venue 追加は YAML 1 ファイルで完結する —
詳細は [`rubric_schema.md`](../../reference/rubric_schema.md#venue-別テンプレート-venue-conditioned-templates)
を参照。

## 7. (上級) 完全な 3-stage プロトコルを CLI で実行 (v0.8.0)

dogfood スクリプトは PaperBench の Stage 1 → 2 → 3 を bridge surface
(`ari-skill-paper-re/src/_paperbench_bridge.py`) 経由で駆動する。

- **Stage 1** (`rollout_submission`) — vendor BasicAgent / IterativeAgent
  が `reproduce.sh` を書く
- **Stage 2** (`reproduce_submission`) — 選択した sandbox で実行、
  `reproduce.log` と `submission_executed_<UTC>.tar.gz` を採取
- **Stage 3** (`judge_submission`) — executed submission を採点

```bash
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/paper.pdf \
    --rubric-model gpt-5-mini \
    --with-rollout \
        --rollout-model gpt-5-mini \
        --rollout-time-limit-sec 14400 \
        --rollout-sandbox local \
    --with-reproduction \
        --reproduce-sandbox slurm \
        --reproduce-partition <PARTITION> \
        --reproduce-gpus-per-task 1 \
        --reproduce-time-limit-sec 7200 \
    --judge-dryrun --judge-model gpt-5-mini \
    --out $HOME/.ari_pb_<run_id>
```

`--paper-audit-mode`(および `sc.yaml` 等 `paper_audit` テンプレート)
とは**排他** — paper_audit は論文自体を採点、`--with-reproduction` は
実行された submission を採点。両立しない。

vendor image は `scripts/build_pb_images.sh` でビルドする。同スクリプトが
表示する完全な Docker image ID を Stage 2 に渡す。Stage 1 の Apptainer
rollout では `apptainer pull pb-env.sif docker-daemon://pb-env:latest` で
SIF 化し、その絶対パスを渡す。mutable tag 自体は渡さない。

> **fail-loud 前提条件 (v0.8.0)**。
> 要求した sandbox / GPU リソースがホストで提供できない場合、エラーで
> 止まり host CPU に黙ってフォールバックしない。legacy fallback は削除済み。
>
> GPU/resource要求にsilent drop overrideはない。cluster設定を修正するか
> 対応partitionを選ぶ。ただし caller が観測するのは送出された例外ではない
> — `run_reproduce` が例外を捕捉して失敗 attempt を記録し、
> `{"executed": false, "error": …, "failure_kind": …}` を返す。
> `failure_kind` は `"sandbox-unavailable"` (container runtime 不在) か
> `"scheduler-failure"` (`sbatch` 不在、partition が解決できない) になる。
>
> network deny はデフォルト ON であり、非隔離
> local/SLURM は管理者 attestation または明示的 `network_policy=inherit`
> を必要とする。ウィザードはそのどちらの引数も送らないため、GUI から
> 起動した `local` / `slurm` の再現は plan 時点で
> *"sandbox_kind=… cannot prove network denial"* で拒否される。この 2 つの
> 引数に触れるには `run_reproduce` MCP ツールか
> `_paperbench_bridge.reproduce_submission` の入口を使う。

## HPC クラスタの sbatch ラッパー(例示)

ARI bridge はクラスタの module を自動 load しません — これは user の
責務(NERSC/OLCF/LLNL すべて「sbatch script 冒頭に `module load` を
書く」を推奨)。bridge は rollout 開始時に `module spider` と
`module avail` を probe し(読み取りのみ — `module load` は決して行わない)、
クラスタカタログを agent にデータとして渡し、 agent がどれを load するか
判断します。 カタログを完全にしたい場合は sbatch wrapper で **事前 load** を:

例(2 段エントリ方式の Env Modules サイト — **あなたのクラスタの module /
partition / GPU 仕様に合わせて調整**):

```bash
#!/bin/bash
#SBATCH --partition=<partition>
#SBATCH --gres=gpu:L40S-44GB:1
#SBATCH --time=08:00:00
#SBATCH --output=workspace/checkpoints/<ts>_<slug>/sbatch.log
set -eu

# 必要 toolchain の module を事前 load(クラスタによって名前が異なる、
# `module avail` で確認)
module load <site-entry-module>  # クラスタ固有のエントリ module
module load nvhpc             # paper が CUDA / nvcc を必要なら
# module load openmpi         # paper が MPI を必要なら

cd /path/to/ARI
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/paper.pdf \
    --rubric-model gpt-5-mini \
    --with-rollout --rollout-model gpt-5-mini \
        --rollout-time-limit-sec 14400 --rollout-sandbox local \
    --with-reproduction --reproduce-sandbox local \
        --reproduce-time-limit-sec 7200 \
    --judge-dryrun --judge-model gpt-5-mini \
    --out workspace/checkpoints/<ts>_<slug>
```

利点:python プロセスは load 済み env を継承する(PATH に nvcc 等が入る)。
bridge の module probe (`_probe_module_avail`, `_detect_runtime_env`) は
その env を継承する素の `subprocess.run` なので、agent に見せるカタログと
`nvcc_path` / `module_path` の事実が事前 load を反映する。

得られ**ない**もの — この env は agent にも採点対象スクリプトにも届かない:

- Stage 1 の agent shell は継承ではなく scrub される。
  `_compute/computer.py:_agent_environment` が固定 dict
  (`PATH=/usr/local/bin:/usr/bin:/bin`、`HOME=<work_dir>/.ari_home`) を
  組み立て、`LocalComputer.send_shell_command` は
  `bash --noprofile --norc -c` で実行する。よって事前 load した nvcc は
  agent の PATH に見えず、agent 自身が module init を source しない限り
  `module` はそのシェルで定義済みコマンドですらない。
- Stage 2 の `reproduce.sh` も scrub される。`execute_local_attempt` は
  `ari.execution.build_minimal_environment()` の下で実行し、`PATH` は
  `/usr/local/bin:/usr/bin:/bin` にリセット、`HOME=/nonexistent`、親から
  引き継ぐのは `LANG` / `LC_ALL` / `SSL_CERT_DIR` / `SSL_CERT_FILE` のみ。
  SLURM 経路は `#SBATCH --export=NIL` で投入するので同じ話になる。
  自前の `module load` チェーンを持たない `reproduce.sh` は、wrapper で
  何を load していようと採点時に失敗する。

代替:事前 load しなくても bridge は動作する(agent が `module spider` /
`module avail` カタログから自己発見)。ただし決定性は下がる — カタログは
拡張されていない `MODULEPATH` が露出する範囲でしかなく、2 段エントリ方式の
サイトでは tier-2 module は bridge の読み取り専用 `module show` 展開経由で
しか見えない。agent が自分のシェルでそれを load し損ね、CUDA 論文を
Python proxy で済ませる失敗も起こりうる。

agent は **reproduce.sh 冒頭にも** `module load <NAME>` を書くべき
(vendor PaperBench eval は Docker で module 不在、portability のため)。
これは bridge の env-truth + paper-kind addendum で agent に明示指示済。

## 次のステップ

- [ルブリックスキーマ + venue テンプレート](../../reference/rubric_schema.md)
- [実行プロファイル仕様](../../reference/execution_profile.md)
- [マルチノード設定](multi_node_setup.md)
- [計算ノード安全規約](compute_node_safety.md)
- [トラブルシューティング](paperbench_troubleshooting.md)
- [PaperBench bridge API](../../reference/api_paperbench.md)
- [環境変数](../../reference/environment_variables.md)
