---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: start.sh
    role: doc
  - path: ari-core/config/default.yaml
    role: config
last_verified: 2026-08-16
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
`8765` です。リポジトリ直下で `./start.sh` を実行するとサービスが 4 つ起動します —
Letta が `8283`、registry が `8290`、GUI が `8765`、CLI shim が `8900` — その後
<http://localhost:8765> を開いてください。`./start.sh status` でヘルスチェックでき、停止は
`./shutdown.sh` です。ライブのツリー更新用 WebSocket は `8766`（ポート + 1）にあります。

**ページが読み込まれない / サービスが起動しなかった。**
`./start.sh` を再実行してください（呼び出すたびに 4 つのサービスすべてを再起動します）。
そして `./start.sh status` を確認してください。`shutdown.sh` は、以前の Letta 実行で
apptainer の孤児となった postgres/redis も回収します。

## 実験の実行

**出力はどこに行く?**
自己完結型のチェックポイントディレクトリ
`workspace/checkpoints/<timestamp>_<slug>/`（タイムスタンプ形式は
`YYYYMMDDHHMMSS_<slug>`）に入ります。論文、図表、ツリー、EAR、再現性レポートはすべて
そこに置かれます。ただし 2 つだけそこに入りません: 各ノードの作業ディレクトリは
`checkpoints/` の兄弟である `workspace/experiments/<run_id>/<node_id>/` に書き込まれ、
`./start.sh` が起動するサービスは PID とログのファイルを `~/.ari/` に置きます。

**最初の実行はどのくらいの規模にすべき?**
小さく: 深さ 3 でノード 5〜10 個、並列ワーカー 2〜4 個。後からいつでも拡大できます。
探索を大きくすると LLM 呼び出しと計算のコストが増えます。

**子ノードがすべて親と同じ数値を報告する — これはバグ?**
いいえ、ガードレールが正しく機能しています。子の `work_dir` は親をコピーして初期化されますが、
実験の *出力*（`results.csv`、`results.json`、`slurm-*.out`、`metrics.json`、
`run.log` / `run_*.log`、`*_output.txt`、…）はブラックリストにあり、継承され **ません** —
ログのパターンは一律の `*.log` ではなく、これらの具体的な名前である点に注意してください。
子が何も変えなかった場合、ARI はその子を **sterile** とマークします。sterile はスコアを
ゼロにするものでは *ありません*: 測定されたスコア、`has_real_data`、`evaluation_status` は
そのまま残り、そのノードが失うのは再展開されることと、親を退役させる権利です。
実行が固定問題（`ARI_PROBLEM`）を指定している場合、sterile 判定は work_dir 全体の差分では
なく、その問題が宣言する `score_inputs` のハッシュで決まります — work_dir 全体の規則は
実際にはほとんど発火しません。これが頻発する場合、エージェントが実際には実験を再実行して
いません — ノードの MCP Trace タブを確認してください。
[アーキテクチャ → work_dir 継承](../concepts/architecture.md#work_dir-inheritance--output-artifact-blacklist-v070--phase-7)
と [用語集 → sterile](../reference/glossary.md)を参照。

**実験が失敗した — ARI はリトライする?**
いいえ。BFTS は失敗ノードを再実行しません。その代わり、失敗を診断して修正するために
`debug` 子ノードを展開します。失敗したノードの Trace タブを開いて、何が起きたかを確認してください。

## GPU、SLURM、コンテナ

**クラスターで実行するには?**
Settings で SLURM パーティションを設定するか（または CLI で `ari settings --partition` —
`ari run` 自体に `--partition` はなく、`--profile hpc` を取ります）、`hpc` プロファイルを
使ってください。Settings で **Detect** をクリックするとパーティションを自動検出でき、
`/api/scheduler/detect` でスケジューラ（SLURM/PBS/LSF/SGE/Kubernetes）を自動検出できます。
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
はい。各チェックポイントは `memory_backup.v1.json.gz` を持っているので、
`cp -r workspace/checkpoints/<run> /elsewhere/` の後に `ari resume` を実行すればメモリが
復元されます — ただし復元されるのは、移動先の Letta が空で、かつ
`ARI_MEMORY_AUTO_RESTORE` が `false` に設定されていない場合に限られます。

---

関連: [トラブルシューティング](../guides/troubleshooting.md) ·
[クイックスタート](quickstart.md) · [用語集](../reference/glossary.md)
