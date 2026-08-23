---
sources:
  - path: start.sh
    role: doc
  - path: setup.sh
    role: doc
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
last_verified: 2026-08-16
---

# ARI をはじめよう

ARI はエンドツーエンドの自律研究システムです。プレーンテキストの研究目標を与えると、
先行研究を調査し、仮説を立て、実際の実験を実行し、論文を書き、そして自身の再現性を
検証します。このページは、最初の 1 時間のための地図です。

## 学習の道筋

順番に進めてください — 各ステップは前のステップを前提としています。

1. **[クイックスタート](quickstart.md)** — ARI をインストールし、AI モデルを選び、
   Web ダッシュボードから最初の実験を起動します。操作中心の内容で、どのボタンが何をするかを扱います。
2. **[最初の実験を、はじめから終わりまで](first_experiment_tutorial.md)** — 1 つの小さな実験を
   目標から再現済み論文まで物語形式でたどり、各ステージが *なぜ* 存在するのかを解説します。
   ダッシュボードが動くようになったら一度読んでみてください。
3. **[FAQ](faq.md)** — 初心者が最初にぶつかる質問: モデルの選択、`8765` ポート、
   出力先、GPU/SLURM の検出、「なぜ子ノードが同じ数値を表示するのか?」など。
4. **[用語集](../reference/glossary.md)** — 概念ドキュメントをスムーズに読み進められるよう、
   繰り返し登場する用語（BFTS、frontier、rubric、venue、EAR、ORS、CoW、…）を 1 行で定義します。

## 必要に応じて分岐する

| やりたいこと | 参照先 |
|---|---|
| 良い `experiment.md` を書きたい | [実験ファイルの書き方](../guides/experiment_file.md) |
| SLURM/HPC クラスターで実行したい | [HPC セットアップ](../guides/hpc_setup.md) |
| 探索の仕組みを理解したい | [BFTS アルゴリズム](../concepts/bfts.md) · [アーキテクチャ](../concepts/architecture.md) |
| 公開済み論文を再現・監査したい | [PaperBench クイックスタート](../guides/paperbench/paperbench_quickstart.md) |
| 独自の機能（スキル）を追加したい | [拡張ガイド](../guides/extension_guide.md) |
| すべてを CLI から操作したい | [CLI リファレンス](../reference/cli_reference.md) |
| 壊れたものを直したい | [トラブルシューティング](../guides/troubleshooting.md) |

## 最初に知っておくとよい 2 つのこと

- **ダッシュボードはポート `8765` で動作します。** リポジトリ直下で `./start.sh` を実行して
  すべてのサービスを起動し、<http://localhost:8765> を開いてください。停止は `./shutdown.sh` です。
- **成果物は自己完結していますが、作業領域はそうではありません。** 論文、図表、ツリー、EAR、
  各種レポートはすべて `workspace/checkpoints/<timestamp>_<slug>/` に置かれ、API キーは保存設定
  からではなく `.env` から取得されます。ただし 2 つだけ別の場所にあります: 各ノードの作業
  ディレクトリは `workspace/experiments/<run_id>/<node_id>/`（`checkpoints/` の兄弟ディレクトリ）
  にあり、`./start.sh` が起動するサービスは PID とログのファイルを `~/.ari/` 配下に置きます。

---

関連: [クイックスタート](quickstart.md) · [FAQ](faq.md) ·
[用語集](../reference/glossary.md) · [ドキュメント目次](../../README.md)
