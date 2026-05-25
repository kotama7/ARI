---
sources:
  - path: scripts/sc_paper_dogfood.py
    role: doc
  - path: ari-skill-paper-re
    role: implementation
  - path: ari-skill-replicate
    role: implementation
last_verified: 2026-05-25
---

# PaperBench クイックスタート

外部論文の登録から PaperBench audit スコア表示までを 5 分で通すチュートリアル。

## 前提条件

- ARI インストール済み (`pip install -e ari-core/`)。
- viz サーバ起動済み (`ari viz` または `python -m ari.viz.server`)。
- `.env` に LLM プロバイダ鍵が設定されている (`OPENAI_API_KEY` /
  `GEMINI_API_KEY` など)。
- SLURM ディスパッチを使う場合: `sbatch` が PATH 上にあり、
  [`docs/howto/multi_node_setup.md`](multi_node_setup.md) を準備済み。

## 1. 論文を取り込む

ダッシュボードの **📚 PaperBench** サイドバーから **📥 論文を取り込む**
を開き、フォームに記入 (arXiv ID / DOI / アップロード) して
**レジストリに保存**。寛容ライセンス (MIT, Apache-2.0, CC BY/SA, CC0)
として自動分類されると緑のバッジが表示される。

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
2. **ルーブリック** — 生成モデル (既定 `gemini-2.5-pro`、two_stage on)。
   [ルーブリック仕様](../../reference/rubric_schema.md) 参照。
3. **再現** — 再現モデルと時間上限。「実行プロファイル上書き」を展開すると
   SLURM 配置 (`--nodes`, `--gpus-per-task`, `--exclusive`, …) を上書き
   可能。ルーブリックに `execution_profile` がある場合は自動入力される。
4. **採点** — SimpleJudge モデルと `n_runs` (既定 1, PaperBench 論文 §4.1)。
5. **実行** — コスト見積もりを確認、*Dry run* で検証後 *すべて実行* で
   ジョブ投入。

## 3. 待機

ジョブ ID は論文ごとに 1 つ返る。Monitor 画面が
`GET /api/paperbench/run/<job_id>` を polling する。所要時間: CPU の
スモークなら 30 分前後、GPU の忠実再現なら数時間。

## 4. スコア確認

`completed` になると Results 画面でルーブリック木 + リーフごとの合否
+ ORS スコアが表示される。生 JSON は
`GET /api/paperbench/run/<job_id>/results`。

## 5. 監査レポート生成 (任意)

人間向け PDF/HTML レポートを生成する:

```bash
make -C report audit-report \
  CHECKPOINT=/var/tmp/ari/.../<checkpoint-id> \
  PAPER_ID=<paper_id> \
  AUDIT_LANGS="en ja zh"
```

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
ノードを持ち、葉の文体は「実装が X を行う」から「X は paper または AD で
特定可能か」に切り替わる。新 venue 追加は YAML 1 ファイルで完結する —
詳細は [`rubric_schema.md`](../../reference/rubric_schema.md#venue-conditioned-templates)
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
    --rubric-model gpt-5-mini --two-stage \
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

vendor image を使う場合は先に `scripts/build_pb_images.sh` で
`pb-env` / `pb-reproducer` をビルドしてから
`--rollout-container-image pb-env --reproduce-container-image pb-reproducer`
を渡す。

> **fail-loud 前提条件 (v0.8.0)**。
> 要求した sandbox / GPU リソースがホストで提供できない場合、エラーで
> 止まり host CPU に黙ってフォールバックしない:
> - `ARI_PHASE1_ALLOW_FALLBACK=1` — docker / apptainer / sbatch が
>   missing 時の legacy fallback を opt-in
> - `ARI_SLURM_ALLOW_NO_GRES=1` — GRES 未設定クラスタで `--gres` /
>   `--gpus-*` フラグを silent drop する legacy 挙動を opt-in
>
> 両方デフォルト OFF(actionable エラー発生)。

## HPC クラスタの sbatch ラッパー(例示)

ARI bridge はクラスタの module を自動 load しません — これは user の
責務(NERSC/OLCF/LLNL すべて「sbatch script 冒頭に `module load` を
書く」を推奨)。bridge は rollout 開始時に `module avail` を probe して
クラスタカタログを agent にデータとして渡し、 agent がどれを load するか
判断します。 確実性が欲しい場合は sbatch wrapper で **事前 load** を:

例(R-CCS ai-l40s — **あなたのクラスタの module / partition / GPU 仕様
に合わせて調整**):

```bash
#!/bin/bash
#SBATCH --partition=ai-l40s
#SBATCH --gres=gpu:L40S-44GB:1
#SBATCH --time=08:00:00
#SBATCH --output=workspace/checkpoints/<ts>_<slug>/sbatch.log
set -eu

# 必要 toolchain の module を事前 load(クラスタによって名前が異なる、
# `module avail` で確認)
module load system/ai-l40s   # クラスタ固有のエントリ module
module load nvhpc             # paper が CUDA / nvcc を必要なら
# module load openmpi         # paper が MPI を必要なら

cd /path/to/ARI
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/paper.pdf \
    --rubric-model gpt-5-mini --two-stage \
    --with-rollout --rollout-model gpt-5-mini \
        --rollout-time-limit-sec 14400 --rollout-sandbox local \
    --with-reproduction --reproduce-sandbox local \
        --reproduce-time-limit-sec 7200 \
    --judge-dryrun --judge-model gpt-5-mini \
    --out workspace/checkpoints/<ts>_<slug>
```

利点:python プロセス → Stage 1 agent subprocess → Stage 2
`bash submission/reproduce.sh` まで env 継承、nvcc 等が PATH に居続ける。

代替:事前 load しなくても bridge は動作(agent が
`module avail` カタログから自己発見)、ただし agent が忘れて
Python proxy で済ます失敗パターン(SC41406 v2 = 0.8%)あり。

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
