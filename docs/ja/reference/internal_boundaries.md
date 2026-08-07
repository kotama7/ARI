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
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_wizard.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/rqgm/runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/governance/__init__.py
    role: implementation
  - path: ari-core/ari/manuscript/snapshot.py
    role: implementation
  - path: ari-core/ari/manuscript/coordinator.py
    role: implementation
  - path: scripts/snapshot_contracts.py
    role: implementation
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
  - path: ari-core/tests/test_rqgm_mode.py
    role: test
  - path: ari-core/tests/test_rqgm_governance.py
    role: test
  - path: ari-core/tests/test_contract_snapshots.py
    role: test
last_verified: 2026-08-07
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
   ルーティングされるようにします。そのシグネチャと戻り値は**凍結**されて
   います: オブジェクトを構築するのではなくモデル id を*変換*するため、
   `ari._factory.BaseRegistry` の文字列ディスパッチャ統一からは意図的に
   外されました（`routing.py` の定義直上にある決定ノートを参照）。
3. **`ari.cost_tracker._install_litellm_metadata_injector()`** は
   `litellm.completion`/`acompletion` を**プロセス全体**にわたって
   モンキーパッチし、(a) デフォルトのコストメタデータ（skill / phase / node、
   および `ari_rqgm` がエポックを開いた後は `epoch`）を
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
| `ari/container.py` | コンテナ実行: `detect_runtime`、`run_in_container`（Popen ＋ `start_new_session=True` ＋ `ari.execution.build_minimal_environment`）、`container_shell_argv` / `run_shell_in_container`（`network="inherit"` または `"deny"` のスイッチ付き）、`pull_image`。`_run_shell_sandboxed` は現在は互換アダプタにすぎず、`ExecutionRequestV1` を構築して `ari.execution.execute_local` を呼びます。サポート外のモードはホストへフォールバックせず `ValueError` を送出します。`ari.public.container` で再エクスポートされます。 |
| `ari/execution.py` | コンテナ実行が委譲するプロセスプリミティブ: `execute_local`（`_preexec` 内の `os.setsid` ＋ `RLIMIT_CPU`/`RLIMIT_AS`/`RLIMIT_NPROC`/`RLIMIT_FSIZE`、タイムアウト時にグループ SIGTERM→SIGKILL）と `build_minimal_environment`（親環境のコピーではなく明示的な環境）。`ARI_MAX_CHILD_PROCS` は `ExecutionLimitsV1.max_processes` としてここに届きます。 |
| `ari/env_detect.py` | スケジューラ / ランタイムのプローブ: `detect_scheduler`（`sinfo`/`qstat`/`bhosts`/`qhost`/`kubectl`）、`detect_container`（apptainer/singularity/docker に対する `shutil.which`）、`get_slurm_partitions`（`sinfo --noheader`）—— 読み取り専用、ベストエフォート、ハードコードされたクラスタ知識を持ちません。 |
| `ari/mcp/connection.py` | `SkillConnection` —— MCP SDK の `stdio_client`（生のスポーンではなくラッパー）経由でスキルの stdio サーバを 1 つスポーンします。`ari/mcp/client.py:MCPClient` はそれらの接続に対するプール、ディスカバリ、ディスパッチを担います。 |
| `ari-skill-hpc/ari_skill_hpc/scheduler.py` | 標準的な SLURM の submit/status/cancel（`SlurmScheduler`。駆動は `LocalCommandRunner` ＝ `asyncio.create_subprocess_exec`、または `RemoteCommandRunner` ＝ paramiko）。投入は常に `sbatch --parsable --export=NIL` です。`ari_skill_hpc/slurm.py` は、環境から構成された 1 つのスケジューラを保持する `SlurmClient` を提供し続けます。 |

これらのオーナーへ統合していくべき既知の重複（誤った挙動ではないが、ドリフトの
リスク）: `viz/api_memory.py` はコンテナランタイムのディスパッチを再導出して
います。`ari-skill-paper-re` はもうそのどちらも再実装しておらず、投入は
`ari_skill_hpc.SlurmScheduler` を、ローカル実行は
`ari.execution.execute_local` を通ります。

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
| **post-BFTS パイプライン**（transform / figures / paper / review / ORS 再現 / publish） | `core.generate_paper_section` → `pipeline.orchestrator.run_pipeline`（`pipeline/driver.py:WorkflowDriver.run` への薄いラッパー）—— `pipeline[]` 上を走る単一の線形カーソルループ。すべてのサブフェーズは連続したステージです。 |

`run.py` は `.pipeline_started` をクリアし、`WorkflowDriver.run` はパイプライン
開始時にそれをタッチします（GUI のフェーズ検出）。BFTS サニティゲートは post-BFTS
パイプラインを早期に中断できます（`ARI_FORCE_PAPER` が上書きします）。
`react:` 以外のステージは `stage_runner._run_stage_subprocess` 経由で実行され、
これは Python スクリプト文字列を構築して
`subprocess.run([sys.executable, "-c", ...])` を行います —— 各非 react ステージは
子プロセス内で自前の `MCPClient` を構築する直接フォークです。

### 並行性のハザード（ここでのどんな変更でも保つこと）

1. **初回接続時点の環境変数タイミング。** MCP サーバはもう `os.environ` を
   継承しません。`mcp/child_environment.py:build_child_environment` が
   fail-closed な許可リスト —— `SAFE_INHERITED_ENV_NAMES`（`PATH`、`LANG`、
   `LC_ALL`、`LC_CTYPE`、`TZ`、`TMPDIR`、CA バンドル系の名前）に加えて、
   スキルの `skill.yaml` が `required_env` / `optional_env` に宣言したもの ——
   を解決し、`SkillConnection` がその結果を `_server_parameters` にキャッシュ
   します。つまり親環境は初回接続時に一度だけ読まれます。したがってタイミングの
   不変条件は変わりません: `ARI_WORK_DIR`（coding / hpc スキルが `optional_env`
   に宣言）はその初回接続**より前に**設定されていなければならず、さもないと
   work-dir のピン留めが静かに壊れます。再現サンドボックス変数（`ARI_REAL_GIT`、
   `ARI_REPRO_*`）はどのスキルマニフェストにも宣言されていないため、react /
   stage-runner のサブプロセス経路にしか届かず、スキルサーバには届きません。
2. **並列ワーカー下での共有プロセス状態。** 1 つの `AgentLoop` インスタンスと
   1 つの `MCPClient` をすべてのノードスレッドが共有します。`_run_loop` は
   同時実行数を `max_workers = min(cfg.bfts.max_parallel_nodes, 4)` に制限し、
   その上限はプールサイズではなく `threading.Semaphore` が担います（プールは
   `max_workers + 8`。スケジューラジョブを待つノードが待機に入り、パーミットを
   返せるようにするためです）。ノード同一性はプロセスグローバルな状態には
   一切載りません。安全なパスは明示的な `ToolCallContextV1` であり、
   `AgentLoop._node_tool_context` がノードごとに 1 度構築し、
   `_execute_tool_calls` を通して渡し、`SkillConnection.authorize_args` が
   接続ごとに署名して `ari_context` ツール引数へ載せます。`work_dir` も同じ
   理由で明示的に渡されます —— 環境変数の参照は `max_parallel_nodes > 1` で
   競合するためです。
3. **共有チェックポイントツリーへの書き込み。** **git worktree は存在しません**:
   並行するコミッタはすべて、1 つの共有された `agent._progress_cb` →
   `_save_tree_incremental` を介して同一の `tree.json` / `nodes_tree.json` /
   `results.json` に書き込みます。スレッド安全性＋スロットルは
   `ari.checkpoint.save_tree_incremental` にあります（ロック＋mtime
   スロットル）。ノードごとの work-dir は
   `PathManager.node_work_dir(run_id, node_id)` によって分離されます。

## RQGM モード境界 (`ari.rqgm`)

オプトインの `ari_rqgm` モード（[実行モード](../guides/execution_modes.md)を
参照）は、もう 1 つの内部境界を追加します: **`ari.rqgm` パッケージは
デフォルトのランからは不可視でなければなりません**。

**強制される規則。** デフォルトの `simple_bfts` パスはいかなる `ari.rqgm`
モジュールもインポートしません。コア側のすべてのインポート箇所は遅延で
あり、インポートが起こる前に*生の*設定フラグでゲートされます:

- `ari.core.build_runtime` — `ari.mode == "ari_rqgm"` または `rqgm.enabled`
  が設定されているときにのみ `ari.rqgm.mode` / `ari.rqgm.runtime` を
  インポートし、`resolve_effective_mode(cfg)` が `ari_rqgm` のときにのみ
  戦略をラップします。同じ分岐の内側で `_install_capability_gate` が
  `ari.rqgm.kernel` / `ari.rqgm.store` / `ari.rqgm.tool_policy` を
  インポートし、`MCPClient` を `CapabilityGatedMCPClient` でラップして
  返します（fail-open: インストールに失敗した場合は警告を出し、ゲート無しの
  クライアントをそのまま返します）。
- `ari/cli/run.py` — このモードの下でのみ `ari.rqgm.state` をインポートし、
  起動時に `rqgm_state.json` を書き `constitution.yaml` をコピーします
  （resume 時は `reconcile_resume_mode`: 永続化されたモードが勝ち、ランが
  途中でアップグレードされることは決してありません）。
- `ari/cli/bfts_loop.py` — オプトインの `proposal_router.record_only: true`
  デュアルライトが設定されたときにのみ提案ストアをインポートします
  （デフォルトの `false` では決してインポートせず、`ari_rqgm` ではルータが
  ネイティブに記録するためそこでもインポートはスキップされます）。
- `ari/cli/paper_dispatch.py` — `rqgm_archive` の paper モードのときにのみ
  `ari.rqgm.paper_runtime` / `ari.rqgm.paper_judge` をインポートします;
  resume 側のインポートはさらに `paper_archive_state.json` の存在で
  ゲートされるため、線形のチェックポイントでは何もインポートされません。
  モード文字列自体はインポート不要の
  `ari.config._effective_paper_mode_str` から得ます。
- `ari.config._effective_mode_str` は有効化テーブルを**インポートなしで**
  ミラーするため、設定処理自体が `ari.rqgm` をロードすることはありません。

**ラップする、決して置き換えない。** `ari_rqgm` の下で `build_runtime` は
`GovernedSearchStrategy`（`ari/rqgm/runtime.py`）を返します。これは 7 つの
`SearchStrategy` メソッドすべてを、手を加えられていない本物の
`ari.orchestrator.bfts.BFTS` インスタンスへ委譲します; コントローラは
`getattr(bfts, "rqgm", None)` で発見できるため、6-tuple の戻り形は保たれ
ます。`ari.protocols` が RQGM のクラスに言及するのは docstring の中だけ
です — Protocol は構造的（`runtime_checkable`）なので、`ari.protocols` を
インポートしても `ari.rqgm` からは何も引き込まれません。

**`rqgm` は予約された属性名です。** ガバナンスランタイムを発見する
サポートされた手段は `getattr(bfts, "rqgm", None)` だけであり、この読み取りが
duck-typed なのは意図的です —— `GovernedSearchStrategy` の docstring 自身が
「検出は duck-typed な属性の有無で行い、この具象クラスの `isinstance` では
決して行わない」と規定しています。ラッパーは内部的でバージョン管理されない
ため、`isinstance(bfts, GovernedSearchStrategy)` で分岐してよい利用者は
おらず、現時点でそうしている箇所もありません。同じ `getattr` プローブは
`cli/bfts_loop.py`、`cli/run.py`、`cli/projects.py`、
`cli/manuscript_repair_runtime.py`、そして `core.py` に繰り返し現れるため、
この名前はランの `SearchStrategy` として受け渡される**あらゆる**オブジェクト
上で予約されています: 戦略オブジェクトに無関係な `rqgm` 属性を付けないで
ください。将来のコンポーネントがより豊かな発見手段を必要とするなら、
2 つ目のマジック属性ではなく型付きのアクセサを追加してください。

**強制。**
`ari-core/tests/test_rqgm_mode.py::test_build_runtime_default_is_identity`
はデフォルトのランタイムを構築し、(a) `sys.modules` に `ari.rqgm*`
エントリが無いこと、(b) 戦略が `.rqgm` 属性を持たない素の
`ari.orchestrator.bfts` オブジェクトであること、(c) チェックポイントに
`rqgm_state.json` / `constitution.yaml` が無いことをアサートします。
スキル側では、`ari.rqgm` は `ari.public.*` を通じて再エクスポートされず、
`scripts/quality/check_import_boundaries.allow.yaml` は `ari.rqgm` の例外を
一切持ちません — いかなるスキルもそれをインポートできません。

**約束はガバナンスのファサードだけです。** パッケージの 1 段内側、
エポック境界の監査にも同じ規律が適用されます。`ari.rqgm.governance` が
エクスポートする名前はちょうど 2 つ —— `GovernanceOrchestrator` と
`GovernanceReport` —— であり、
`ari-core/tests/test_rqgm_governance.py::test_facade_exports_only_the_two_public_names`
が `__all__` をその 2 つに固定しています。監査を構成するものはすべて、
同パッケージのアンダースコア始まりの非公開モジュールにあります:
信頼性モニタ（`_reliability.py`）、証拠クラークとその許容性チェッカ
（`_evidence.py`）、監査官／訴追役とその保証金会計（`_prosecution.py`）、
弁護役（`_defense.py`）、ボード群とガバナンス裁定者（`_adjudication.py`）、
セルフ監査（`_self_audit.py`）、加えて 9 ステップのパイプライン本体
（`_pipeline.py`）とレコードのデータクラス（`_records.py`。ここから
ファサードへ引き上げられるのは `GovernanceReport` だけです）。それ以外は
何ひとつ再エクスポートされず、`ari.public.*` にも追加されず、CLI フラグも
持たず、MCP ツールとしても公開されません。ツリー内でテスト以外の唯一の
呼び出し箇所は `RQGMRuntime.run_epoch_audit`（`ari/rqgm/runtime.py`）で
あり、そこでオーケストレータを遅延構築し、エポック境界ごとに
`audit_epoch` を 1 度呼びます。

この狭さは意図的です。粒度の細かいアクター名は概念上の語彙であって
インターフェースではありません: それらを 10 個以上公開すれば、まだ動いて
いるシグネチャが凍結されたコントラクトスナップショット面
（`ari-core/tests/fixtures/contracts/public_api.json`）に固定され、以後の
リファクタリングがすべて golden-file の差分になります。ファサードを
1 クラス・1 公開メソッド・1 戻り型に保つことで、内部のアクターは自由に
作り替えられる一方、唯一の呼び出し箇所と、遷移エンジンが消費する
`GovernanceReport` は安定したままでいられます。

**このモードは契約サーフェスを消費しません。** 有効化は設定と環境変数
だけで行われます: RQGM は `ari` の CLI コマンドもフラグも追加せず、
`ari.public.*` を通じてシンボルを 1 つもエクスポートしません。したがって
凍結されたスナップショットはどちらも再生成を必要としません ——
`ari-core/tests/fixtures/contracts/cli_tree.json` と `public_api.json`
（`scripts/snapshot_contracts.py` が構築・検証し、
`ari-core/tests/test_contract_snapshots.py` がゲートする）には `rqgm` の
エントリが 1 つもありません。これは見落としではなく意図的な予算上の決定
です: `--mode` フラグを設ければ実行モードが凍結された CLI ツリーに移動し、
以後のモード関連の変更がすべて golden ファイルの差分になってしまいます。
新しいモードのサーフェスは設定側に留めてください —— 上のラッパーを型では
なく属性で発見しているのも同じ理由です。

### 原稿コンパイラ境界 (`ari.manuscript`)

同じ一方向の規律が原稿コンパイラにも適用されます。矢印の向きが逆なので
節を分けて述べます: `ari.manuscript` は RQGM が依存**される**側であり、
その逆は決してありません。

**`ari.manuscript` 配下のどのモジュールも `ari.rqgm` をインポートしません。**
このパッケージが他の `ari` パッケージに対して行うインポートは、関数
ローカルな遅延インポートが 2 つだけです ——
`ari.assurance.models.HarnessAttestationV1`（`manuscript/snapshot.py`。
ノードのハーネス添付証明をパースするため）と
`ari.paper_contract.parse_paper_build`（`manuscript/runtime.py`）——
そしてそのどちらも `ari.rqgm` には到達しません: `ari/paper_contract.py` は
`ari` のモジュールを 1 つもインポートせず、`ari/assurance/**` には `rqgm`
への言及が 1 つもありません。`ari.manuscript` の内側でこの名前が現れるのは
データとしてだけです —— `manuscript/contracts.py` の
`Literal["simple_bfts", "ari_rqgm"]` および
`Literal["linear", "rqgm_archive"]` というコントラクトのフィールド、
`snapshot.py` / `coordinator.py` でそれらへ正規化される文字列、そして
`manuscript/authority.py:_AUTHORITY_FILES` にある
`rqgm/kca/admission-v1/` 配下の 4 つのチェックポイント相対パスです。

**では RQGM の状態はどうやってコンパイラへ届くのか。** チャネルは 3 つで、
どれも RQGM の型を名指ししません:

| チャネル | 形 |
|---------|-----|
| モード | 素の `str` キーワード引数 —— `compile_manuscript(..., exploration_mode="simple_bfts", paper_mode="linear")` が `build_exploration_snapshot(..., exploration_mode=...)` へ転送され、コントラクトに載る前に 2 つのリテラルのいずれかへ正規化されます。どちらのシグネチャにも RQGM のプロバイダオブジェクトや型付き RQGM ブロックはありません。`manuscript/runtime.py:prepare_runtime_manuscript` が両者を `ARI_MANUSCRIPT_EXPLORATION_MODE` / `ARI_MANUSCRIPT_PAPER_MODE` から埋めます。 |
| ノード状態 | 呼び出し側がすでに持っているノードオブジェクトからの duck-typed な読み取り。`snapshot._get(value, name, default)` はマッピングなら `value.get(...)`、それ以外なら `getattr(...)` なので、`attestation_refs`・`verified_target_digest`・`metrics` は名前で引かれ、それらを持たない `simple_bfts` のノードは単にデフォルトを返します。 |
| 証拠 | チェックポイント相対パスから読むファイル。オブジェクトとして渡されることはありません。`snapshot._attestation_artifacts` はノードの `attestation_refs` が指す相対パスをダイジェストし `HarnessAttestationV1` として検証します（status は `present` / `missing` / `invalid`）。`authority.capture_repair_authority` は固定の `_AUTHORITY_FILES` 一覧をダイジェストするだけでパースはしません（status は `present` / `absent` / `unsafe_symlink`）。いずれも、パスが無い場合や symlink を含む場合は例外ではなく status として記録されます。 |

**逆向きの辺は許可され、実際に使われています。**
`ari.rqgm.paper_runtime` はアーカイブ入力を再検査するために
`ari.manuscript.digest.path_has_symlink_component` をインポートし、
`ari/cli/paper_dispatch.py` が両者を駆動する層です —— そこでは
`ari.rqgm.paper_runtime` / `ari.rqgm.paper_judge` と
`ari.manuscript.runtime` / `ari.manuscript.coordinator` が並んで遅延
インポートされます。両方を同時に必要とする糊コードの手本は
`ari/cli/manuscript_repair_runtime.py` です: `ari.manuscript.*` は直接
インポートする一方、ガバナンスランタイムへは上で述べた予約済みの
`getattr(bfts, "rqgm", None)` プローブ経由でしか触れません。つまり RQGM は
原稿コントラクトに依存してよく、原稿コントラクトが RQGM に依存することは
決して許されません。これによって 1 つのコンパイラが 2 つの探索モードと
2 つの paper モードの双方を、実装をもう 1 本持たずに扱えます —— 違いは
並行するコードパスへ分岐させるのではなく、フィールドの値（`paper_mode`、
および `coordinator.py` がそこから導出する `backend_version` 文字列）として
記録されます。コンパイラが必要とする RQGM 側の概念は、インポートではなく
上の 3 チャネルのいずれかで届かなければならない、というのもそのためです。

**この向きを強制するものは何もありません。** テストも品質ゲートの規則も
ありません: `scripts/quality/check_import_boundaries.yaml` が制約するのは
skill→core と core→skill の辺だけで、core 内部のパッケージ対は 1 つも
名指ししていません。隣接する*強制されている*規則は別物です ——
`ari-core/tests/test_manuscript_complete.py::test_default_cli_import_does_not_load_manuscript_domain`
は `ari.cli` のインポートが `ari.manuscript*` モジュールを 1 つも
ロードしないことをアサートします。これはコンパイラをデフォルトの
インポート経路から外し続けますが、コンパイラが何をインポートしてよいかに
ついては何も述べていません。誰かがチェックを追加するまで、
`ari.rqgm` をインポートしないという規則はレビュー上の義務として
扱ってください。

## GUI の HTTP ディスパッチ境界

viz サーバが HTTP リクエストをディスパッチする場所はちょうど 2 か所です（その
周辺のレイヤリングについては
[ダッシュボードアーキテクチャ](../concepts/gui_architecture.md) を
参照してください）。レガシーな `/api/…` サーフェスは
`ari/viz/routes.py` の `BaseHTTPRequestHandler` サブクラス内にある
`self.path` に対する `if`/`elif` チェーンで、各ハンドラをそれぞれの
`api_*` モジュールから直接インポートしています。`/api/v1/…` は
`ari/viz/v1/router.py` の宣言的な `ROUTES` テーブルへ委譲されます。

**`ari/viz/api_wizard.py: WIZARD_ROUTES` は 3 つ目ではありません。**
このモジュールは 6 つの wizard ハンドラを短い名前で再エクスポートし、
4 エントリの `{path: (method, callable)}` 辞書を組み立てていますが、
ツリー内にこのモジュールをインポートしているものは本番コードにも
テストにも存在せず、どのディスパッチャもこの辞書を参照しません。
wizard に手を入れる人にとっての帰結は 2 つあります。`WIZARD_ROUTES` に
エントリを追加してもルートは生まれません。そしてこの辞書は wizard の
コントラクトではありません —— 実際すでにドリフトしており、4 つのパスの
うち `/api/generate-config` はサーバ上に存在しません（ディスパッチャが
応答するのは `/api/config/generate` です）。REST スキーマチェッカは
モジュールレベルの `ROUTES` / `WIZARD_ROUTES` マップを解析できますが
(`scripts/check_viz_api_schema.py: parse_declarative_routes`)、その経路は
既定で無効です —— `scripts/quality/check_viz_api_schema.yaml` の
`use_declarative_routes: false` —— まさにこのマップが stale だからであり、
チェッカは代わりに `if`/`elif` チェーンからルートを抽出します。
リポジトリ直下の `DEPRECATION_REMOVAL.md` の台帳はこのシンボルを削除候補
として記録しています。削除されるまでは、どの wizard エンドポイントが
存在するかを述べているのは上記 2 つのディスパッチャだけだと考えてください。
