---
sources:
  - path: ari-core/ari/llm/routing.py
    role: implementation
  - path: ari-core/ari/cost_tracker.py
    role: implementation
  - path: ari-core/ari/llm/client.py
    role: implementation
  - path: ari-core/ari/container.py
    role: implementation
  - path: ari-core/ari/mcp/client.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/ari/pipeline/orchestrator.py
    role: implementation
  - path: ari-core/ari/viz/state.py
    role: implementation
last_verified: 2026-06-10
---

# 内部境界

ARI が純粋な Python では実現できない 3 つの対象 —— **LLM プロバイダ**、
**OS / スケジューラ / コンテナ**、そして **2 つのオーケストレーション
エンジン** —— とどうやり取りするか。これはコントリビュータ向けのリファレンス
です。境界がどこにあるか、許可された呼び出しの形は何か、そしてここを変更する
際に必ず保たねばならない並行性のハザードを示します。（パッケージをまたぐ
安定サーフェスについては [public_api.md](public_api.md)、設定の優先順位に
ついては [configuration.md](configuration.md)、ディスク上のレイアウトに
ついては [glossary.md](glossary.md) と [アーキテクチャ](../concepts/architecture.md)
を参照してください。）

## LLM 境界

ARI の LLM 境界は「すべてが `LLMClient` を呼ばなければならない」という意味では
**ありません**。これは 3 部構成のパターンであり、`litellm.{completion,acompletion}`
を直接呼び出すことが**許可された**形です:

1. **`litellm`** はプロバイダ抽象化レイヤーです —— モジュールはモデル ID を
   指定して `litellm.completion` / `acompletion` を直接呼び出します。
2. **`ari.llm.routing.resolve_litellm_model(model, backend)`** は唯一の
   モデル正規化ヘルパーです。プロバイダプレフィックス（CLI シムの
   `openai/claude-cli` ルールを含む）を適用し、素のモデル名が正しく
   ルーティングされるようにします。
3. **`ari.cost_tracker._install_litellm_metadata_injector()`** は
   `litellm.completion`/`acompletion` を**プロセス全体**にわたって
   モンキーパッチし、(a) デフォルトのコストメタデータ（skill / phase / node）を
   マージし、(b) 毎回の呼び出しに `_apply_ari_routing`（`resolve_litellm_model`
   ＋ CLI シムの `api_base` 補完）を適用します。一度インストールされれば、
   どのモジュールやスキルからのものであっても、*すべての* litellm 直接呼び出しが
   1 か所で透過的に ARI ルーティング＋コストキャプチャを受けます。

`ari.llm.client.LLMClient` は ReAct エージェントループが使う
`litellm.completion` 上の**便利なラッパー**です。これは必須のチョークポイント
**ではなく**、コードベースは意図的にすべてをここに集約していません。

インジェクタは `cost_tracker.set_default_metadata` / `init_from_env` 経由で
インストールされ、これらは各スキルの `server.py` 冒頭にある
`bootstrap_skill("<name>")` を通じて到達されます。

**保つべき脆弱性:** CLI シムのルーティングとコストキャプチャは、プロセス内で
**最初の litellm 呼び出しより前に**インジェクタがインストールされていることに
依存します。スキルは `bootstrap_skill` によりインポート時にこれを保証します。
コアの CLI / パイプラインモジュール（`evaluator`、
`orchestrator/lineage_decision`、`root_idea_selector`、
`pipeline/context_builder`）は litellm を直接呼び出し、`api_base`/model を
自前で渡すため、グローバルインジェクタがなくても正しくルーティングされます ——
ただしインジェクタが不在ならコストキャプチャを取りこぼします。
`pipeline/context_builder` は、`resolve_litellm_model` ではなく独自の環境変数
解決を行う唯一のパイプラインパッケージ直接呼び出しです（既知の低価値な継ぎ目）。

## 実行境界（OS / スケジューラ / コンテナ）

許可された実行モジュール —— 実行挙動の変更はここに属します:

| モジュール | 担当 |
|--------|------|
| `ari/container.py` | コンテナ実行: `detect_runtime`、`build_run_cmd`、`run_in_container`（Popen ＋ `_sandbox_preexec` ＝ `os.setsid` による新しいプロセスグループ ＋ `ARI_MAX_CHILD_PROCS` 経由の任意の `RLIMIT_NPROC`）、`_run_with_timeout`（グループ SIGTERM→SIGKILL）、`pull_image`、`exec_in_container`。`ari.public.container` で再エクスポートされます。 |
| `ari/env_detect.py` | スケジューラ / ランタイムのプローブ（`sinfo`、`qstat`、`docker info`、`lscpu`）—— 読み取り専用、ベストエフォート、ハードコードされたクラスタ知識を持ちません。 |
| `ari/mcp/client.py` | MCP SDK の `stdio_client`（生のスポーンではなくラッパー）経由でスキルの stdio サーバをスポーンします。 |
| `ari-skill-hpc/src/slurm.py` | 標準的な SLURM の submit/status/cancel（`SlurmClient`: `_run_local` は asyncio サブプロセス、`_run_remote` は paramiko）、`ARI_SBATCH_EXPORT_MODE` のクリーン環境ロジックを含みます。 |

これらのオーナーへ統合していくべき既知の重複（誤った挙動ではないが、ドリフトの
リスク）: `viz/api_memory.py` はコンテナランタイムのディスパッチを再導出して
います。`ari-skill-paper-re/src/server.py` は `sbatch`/`apptainer exec` を
再実装しており、すでに `slurm.py` から乖離しています（`--export ALL` を
ハードコードしている）。そのローカルフォールバックには `setsid`/`killpg` が
ないため、ハングした再現実験が孤児プロセスを生む可能性があります。

**`ari.viz.state` のプロセスハンドル結合。** `ari/viz/state.py` は、ライブの
OS ハンドルをモジュールグローバル（`_st` としてインポートされる）として
保持します: `_last_proc`（直近の実験の Popen。`api_process._api_stop` が
`os.killpg(os.getpgid(pid))` で破棄する）、`_running_procs`
（checkpoint-path→Popen のマップ。2 つのローンチパスが書き込む）、そして
`_gpu_monitor_proc`（そのロジックは `api_process.py` にある。サーバは再起動を
またいで残留モニタを回収する）。これは「グローバルな可変状態を通じた隠れた
結合を避ける」という戒めの典型例です —— そのライフサイクルには意図を持って
のみ手を触れてください。

## 2 つのオーケストレーションエンジン

ランタイムは 1 本の線形パイプラインではなく、**2 つの異なるエンジン**です ——
`workflow.yaml` はフェーズタグ（`bfts`、`paper`）を宣言しますが、分割は
次のように横断します:

| フェーズ | ドライバ |
|-------|--------|
| **BFTS** | `cli/bfts_loop.py:_run_loop` —— ハードコードされた `while pending or frontier` ループ（generate_idea → select_and_run → evaluate → frontier_expand）。`bfts_pipeline[]` は有効/無効フラグのためにのみ読まれます。 |
| **post-BFTS パイプライン**（transform / figures / paper / review / ORS 再現 / publish） | `core.generate_paper_section` → `pipeline.orchestrator.run_pipeline` —— `pipeline[]` 上を走る単一の線形カーソルループ。すべてのサブフェーズは連続したステージです。 |

`run.py` は `.pipeline_started` をクリアし、`orchestrator` はパイプライン開始時に
それをタッチします（GUI のフェーズ検出）。BFTS サニティゲートは post-BFTS
パイプラインを早期に中断できます（`ARI_FORCE_PAPER` が上書きします）。
`react:` 以外のステージは `stage_runner._run_stage_subprocess` 経由で実行され、
これは Python スクリプト文字列を構築して
`subprocess.run([sys.executable, "-c", ...])` を行います —— 各非 react ステージは
子プロセス内で自前の `MCPClient` を構築する直接フォークです。

### 並行性のハザード（ここでのどんな変更でも保つこと）

1. **fork 時点の環境変数タイミング。** MCP サーバはスポーン時に `os.environ` を
   スナップショットします。`ARI_WORK_DIR` とサンドボックス変数（`ARI_REAL_GIT`、
   `ARI_REPRO_*`、`PATH`）は `MCPClient` のスポーン**より前に**設定されている
   必要があります。MCP 構築を遅延させたり環境セットアップの順序を入れ替えたり
   すると、サンドボックス化 / work-dir のピン留めが静かに壊れます。
2. **並列ワーカー下での共有プロセスのグローバル環境レース。** 最大 4 つの
   `AgentLoop` スレッドが 1 つのプロセスと 1 つの `MCPClient` を共有します。
   メモリの copy-on-write はプロセスグローバルな `ARI_CURRENT_NODE_ID` をキーに
   します。唯一安全な書き込みパスは
   `mcp.call_tool(name, args, cow_node_id=node_id)` です（set-node＋write の対を
   `MCPClient._cow_lock` 下で直列化します）。実行ごとの単一の
   `_set_current_node` は `max_parallel_nodes > 1` では安全ではありません。
3. **共有チェックポイントツリーへの書き込み。** **git worktree は存在しません**:
   並行するコミッタはすべて、1 つの共有された `agent._progress_cb` →
   `_save_tree_incremental` を介して同一の `tree.json` / `nodes_tree.json` /
   `results.json` に書き込みます。スレッド安全性＋スロットルは
   `ari.checkpoint.save_tree_incremental` にあります（ロック＋mtime
   スロットル）。ノードごとの work-dir は
   `PathManager.node_work_dir(run_id, node_id)` によって分離されます。
