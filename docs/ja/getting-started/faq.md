---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/config/default.yaml
    role: config
last_verified: 2026-05-26
---

# FAQ

初心者が最初にぶつかる質問です。壊れた実行からの段階的な復旧については
[トラブルシューティング](../guides/troubleshooting.md)を、用語の定義については
[用語集](../reference/glossary.md)を参照してください。

## セットアップとモデル

**最初はどの AI モデルから始めるべき?**
アカウントもコストもなしで初回実行するなら、Ollama で `qwen3:8b` を使ってください
（約 16 GB の RAM が必要）。より高品質を求めるなら、`openai/gpt-4o` や
`anthropic/claude-sonnet-4-5` などのクラウドモデルを使います。常にプロバイダー接頭辞を
含めてください — `gpt-4o` ではなく `openai/gpt-4o` です。
[クイックスタート → AI モデルの選択](quickstart.md#step-2-choose-your-ai-model)を参照。

**インストール後に `ari: command not found` となる。**
ユーザーの bin ディレクトリを PATH に追加してください: `export PATH="$HOME/.local/bin:$PATH"`。
`setup.sh` を `sudo` で実行しないでください — 通常のユーザーとして実行してください。

**Ollama の「connection refused」。**
ARI を起動する前に、別のターミナルで `ollama serve` が実行されている必要があります。

## ダッシュボード

**ダッシュボードのポートは?**
`8765` です。リポジトリ直下で `./start.sh`（Letta + registry + GUI）を実行してすべてを起動し、
<http://localhost:8765> を開いてください。`./start.sh status` でヘルスチェックでき、停止は
`./shutdown.sh` です。ライブのツリー更新用 WebSocket は `8766`（ポート + 1）にあります。

**ページが読み込まれない / サービスが起動しなかった。**
`./start.sh` を再実行してください（呼び出すたびに 3 つのサービスすべてを再起動します）。
そして `./start.sh status` を確認してください。`shutdown.sh` は、以前の Letta 実行で
apptainer の孤児となった postgres/redis も回収します。

## 実験の実行

**出力はどこに行く?**
自己完結型のチェックポイントディレクトリ
`workspace/checkpoints/<timestamp>_<slug>/`（タイムスタンプ形式は
`YYYYMMDDHHMMSS_<slug>`）に入ります。論文、図表、ツリー、EAR、再現性レポートはすべて
そこに置かれます。ホームディレクトリには何も書き込まれません。

**最初の実行はどのくらいの規模にすべき?**
小さく: 深さ 3 でノード 5〜10 個、並列ワーカー 2〜4 個。後からいつでも拡大できます。
探索を大きくすると LLM 呼び出しと計算のコストが増えます。

**子ノードがすべて親と同じ数値を報告する — これはバグ?**
いいえ、ガードレールが正しく機能しています。子の `work_dir` は親をコピーして初期化されますが、
実験の *出力*（`results.csv`、`slurm-*.out`、`metrics.json`、`*.log`、…）はブラックリストに
あり、継承され **ません**。子が新規・変更ファイルを 1 つも生成せずに終わった場合、ARI は
継承された結果に得点を与える代わりに、その子を **sterile**（スコア `0.0`）とマークして剪定します。
これが頻発する場合、エージェントが実際には実験を再実行していません — ノードの Trace タブを
確認してください。
[アーキテクチャ → work_dir 継承](../concepts/architecture.md#work_dir-inheritance--output-artifact-blacklist-v070--phase-7)
と [用語集 → sterile](../reference/glossary.md)を参照。

**実験が失敗した — ARI はリトライする?**
いいえ。BFTS は失敗ノードを再実行しません。その代わり、失敗を診断して修正するために
`debug` 子ノードを展開します。失敗したノードの Trace タブを開いて、何が起きたかを確認してください。

## GPU、SLURM、コンテナ

**クラスターで実行するには?**
Settings で SLURM パーティションを設定するか（または CLI で `--partition`）、`hpc` プロファイルを
使ってください。Settings で **Detect** をクリックするとパーティションを自動検出でき、
`/api/scheduler/detect` でスケジューラ（SLURM/PBS/LSF/Kubernetes）を自動検出できます。
[HPC セットアップ](../guides/hpc_setup.md)を参照。

**GPU が使われていない。**
`nvidia-smi` が動作すること、SLURM リクエストが GPU を要求していること、コンテナランタイムが
検出されていること（Settings → **Detect Runtime**）を確認してください。PaperBench の再現では、
GPU/サンドボックスが欠けている場合、無言で CPU にフォールバックするのではなく明示的に失敗
するようになりました — [PaperBench GUI → fail-loud 前提条件](../guides/paperbench/paperbench_gui.md)を参照。

## キー、論文、再現性

**API キーはどこに保存される?**
`.env` ファイルにのみ保存され、`settings.json` には決して保存されません。探索順序は
checkpoint → ARI ルート → `ari-core` → home、または起動時に注入される環境変数です。

**PDF が生成されなかった。**
LaTeX（`conda install -c conda-forge texlive-core`）と PDF テキストツール
（`pip install pymupdf pdfminer.six`）をインストールしてください。

**完了した実行を別のマシンに移せる?**
はい。各チェックポイントは `memory_backup.jsonl.gz` を持っているので、
`cp -r workspace/checkpoints/<run> /elsewhere/` の後に `ari resume` を実行すれば、
メモリが空の Letta に自動的に復元されます。

---

関連: [トラブルシューティング](../guides/troubleshooting.md) ·
[クイックスタート](quickstart.md) · [用語集](../reference/glossary.md)
