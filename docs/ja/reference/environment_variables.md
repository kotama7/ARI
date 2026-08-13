---
sources:
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: scripts/setup/setup_env.sh
    role: config
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-skill-tool-registry/src/server.py
    role: implementation
  - path: ari-core/ari/rqgm/state.py
    role: implementation
  - path: ari-core/ari/assurance/executors.py
    role: implementation
last_verified: 2026-08-08
---

# 環境変数リファレンス

ARI は 150 を超える環境変数を参照します。ここではそれらを一覧で確認できるよう
まとめています。ほとんどは適切なデフォルト値を持っていますが、**Required?** 列は
新規チェックアウト状態では動作しないものを示しています。

`docs/reference/configuration.md` は同じ内容をチュートリアル形式で説明しています。
このページはアルファベット順の逆引きリファレンスです。

> v0.5.0 でグローバルの `$HOME/.ari/` ディレクトリが削除されました。
> このリファレンスで「必須設定」と記載している箇所については、レガシーの
> フォールバックが `DeprecationWarning` を出力し、v1.0 で削除されます。

## コア (`ARI_*`)

### チェックポイント + パス

| 変数 | 用途 | デフォルト | Required? |
|---|---|---|:---:|
| `ARI_CHECKPOINT_DIR` | アクティブなチェックポイントルート | (なし — 必須設定) | ✓ |
| `ARI_WORKSPACE` | 新規実行の親ディレクトリ（orchestrator スキルが使用） | (なし) | ✓ (`ari-skill-orchestrator` 用) |
| `ARI_WORK_DIR` | ノードごとの作業ディレクトリルート（`ari-skill-coding`） | `/tmp/ari_work` | – |
| `ARI_LOG_DIR` | アプリケーションログディレクトリ | `$ARI_CHECKPOINT_DIR` | – |
| `ARI_ROOT` | ARI ソースツールルート（テストで使用） | (自動検出) | – |
| `ARI_SOURCE_FILE` | 入力 experiment.md パスの上書き | (なし) | – |

`ARI_CHECKPOINT_DIR` には、表では表せない書き込み側の**慣習**があります。現在の
プロセスを特定の run に固定するコードは、変数を自分で代入するのではなく
`PathManager.set_checkpoint_dir_env` を呼ぶことが期待されています（これは
`RuntimePathResolver.set_checkpoint_dir_env` に委譲され、`ari-core/ari/paths.py`
の中で `os.environ["ARI_CHECKPOINT_DIR"]` に代入する唯一の関数です）。run pin の
所有者を 1 箇所に保つためです。ただしこれは保証ではなく慣習として読んでください。

- **強制する仕組みはありません。** 書き込み側が変数へ直接代入しても失敗する
  テスト・lint ルール・import 境界チェックは存在しません。このヘルパは pipeline
  driver、Letta クライアント、`ari memory`、`ari viz` の 3 モジュール、CLI の
  2 つのエントリポイントで使われています。
- **既知の迂回が 1 件あります。** `ari-core/ari/agent/loop.py` は、ノードの tool
  context を組み立てる前に `os.environ["ARI_CHECKPOINT_DIR"]` へ直接代入します。
  したがってヘルパの docstring にある「すべての書き込みを PathManager 経由に保つ」
  という記述は、コードが実際に達成していることを過大に述べています。この一文は
  事実ではなく意図として扱ってください。
- **子プロセス用の env 辞書はこの規則の対象外です。** GUI の launch、orchestrator、
  experiment の各経路はサブプロセスへ渡す `proc_env` マッピングにこのキーを設定
  しますが、このプロセスの環境は変更しないため迂回には当たりません。

### LLM モデル選択

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_LLM_MODEL` | デフォルト LiteLLM モデル ID | (なし) |
| `ARI_LLM_API_BASE` | LiteLLM API ベース上書き | LiteLLM デフォルト |
| `ARI_MODEL` | スキル横断フォールバックモデル ID | (`ARI_LLM_MODEL` にフォールスルー) |
| `ARI_MODEL_EVAL` | LLM 評価器のモデル | `ARI_MODEL` にフォールスルー |
| `ARI_MODEL_PAPER` | 論文執筆・改稿モデル | `ARI_LLM_MODEL` にフォールスルー |
| `ARI_MODEL_RUBRIC` | 独立rubric査読・固定論文パネルのモデル | `ARI_LLM_MODEL` にフォールスルー |
| `ARI_PANEL_SEED` | 固定査読パネルの各評価呼出しに記録する要求シード | 未設定。標本化を制御できるかは提供元・実行基盤に依存 |
| `ARI_MODEL_JUDGE` | BFTS ジャッジのモデル | `ARI_MODEL` にフォールスルー |
| `ARI_MODEL_LINEAGE` | 停滞 / lineage 決定のモデル (v0.7.0) | `ARI_MODEL` にフォールスルー |
| `ARI_MODEL_ROOT_SELECT` | シードアイデアを選ぶモデル | `ARI_MODEL` にフォールスルー |
| `ARI_MODEL_IDEA` | `generate_ideas` のモデル | `ARI_MODEL` にフォールスルー |
| `ARI_MODEL_REPLICATE` | レプリケータ高レベル推論のモデル (v0.7.0) | `ARI_MODEL` にフォールスルー |
| `ARI_MODEL_REPLICATOR` | `ari-skill-paper-re.build_reproduce_sh` が使用するモデル | フォールスルー |
| `ARI_MODEL_RUBRIC_GEN` | `ari-skill-replicate.generate_rubric` のモデル | フォールスルー |
| `ARI_MODEL_RUBRIC_AUDIT` | `ari-skill-replicate.audit_rubric` のモデル | フォールスルー |
| `LLM_MODEL` | スキル横断フォールバック（`ari-skill-transform`、`ari-skill-plot` が使用） | (なし) |
| `LLM_API_BASE` | `LLM_MODEL` 用 API ベース | (なし) |

### Claude Code バックエンド（`ARI_CLAUDE_CODE_*`）

`ARI_BACKEND=claude_code` / `llm.backend: claude_code` のときのみ読まれる —
[claude_code_provider.md](./claude_code_provider.md) 参照。

| 変数 | 目的 | デフォルト |
|---|---|---|
| `ARI_CLAUDE_CODE_MODE` | `strict_reproducibility`（呼び出しごとに fresh な `claude -p`）または `low_overhead`（常駐 Agent SDK ワーカー、リクエストごとに fresh query） | `strict_reproducibility` |
| `ARI_CLAUDE_CODE_MODEL` | モデル上書き。解決後のバックエンドが `claude_code` のときのみ適用 | `llm.model` |
| `ARI_CLAUDE_CODE_MAX_TURNS` | 呼び出しごとの `--max-turns`（>1 は `allow_multi_turn` が必要） | `1` |
| `ARI_CLAUDE_CODE_TIMEOUT_SEC` | 呼び出しごとの subprocess/SDK タイムアウト | `300` |
| `ARI_CLAUDE_CODE_RECORD_PROVENANCE` | 呼び出しごとの成果物を `{checkpoint}/claude_code/{call_id}/` に保存（`1`/`0`） | `1` |
| `ARI_CLAUDE_CODE_BIN` | Claude Code バイナリ | `claude` |
| `ANTHROPIC_AUTH_TOKEN` | `ANTHROPIC_API_KEY` の代替トークン認証。どちらかがあれば hermetic な `--bare` プロファイルが有効になる | (なし) |

### Idea スキル — VirSci-live

`generate_ideas` のオプトイン vendor ラップ経路。デフォルト無効では現在の動作
（軽量な再実装ディスカッションループ）を維持します。有効にすると `generate_ideas` は
ライブの Semantic Scholar スナップショット上で VirSci の本物のマルチエージェント機構を
実行します。依存欠落 / 任意のランタイムエラー時は再実装ループにデグレードします。
ディスカッション LLM は `ARI_MODEL_IDEA` に従います。

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_IDEA_VIRSCI_REAL` | 本物の vendor ラップ経路の切り替え（`1`/true）。未設定 ⇒ 現在の再実装動作 | (未設定 / 無効) |
| `ARI_IDEA_VIRSCI_K` | ディスカッションのターン数（vendor `group_max_discuss_iteration`） | `7` |
| `ARI_IDEA_VIRSCI_TEAM_SIZE` | チームメンバー数の上限（vendor `max_teammember`） | `3` |
| `ARI_IDEA_VIRSCI_N_AUTHORS` | `select_coauthors` の著者プールサイズ | `16` |
| `ARI_IDEA_VIRSCI_N_PAPERS` | SPECTER2 検索コーパスサイズ | `800` |
| `ARI_IDEA_VIRSCI_MAX_TEAMS` | `generate_idea` に通すチーム数の上限 | `=n_ideas` |
| `ARI_IDEA_VIRSCI_SPECTER2_MODEL` | ローカルのクエリ埋め込みモデル | `allenai/specter2_base` |

### BFTS 探索

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_MAX_NODES` | BFTS ノードの上限 | (workflow 制御) |
| `ARI_MAX_DEPTH` | ツリー深さの上限 | (workflow 制御) |
| `ARI_MAX_REACT` | ノードごとの ReAct 反復上限 | (workflow 制御) |
| `ARI_PARALLEL` | 並行ノード実行数 | `4` |
| `ARI_TIMEOUT_NODE` | ノードごとのウォールタイム上限（秒） | (なし) |
| `ARI_BFTS_ALLOW_WEB` | オプトイン：BFTS ノードエージェントに**探索中**の `web-skill`（web_search / fetch_url / arXiv / Semantic Scholar）を公開。デフォルト無効では探索ループの再現性（P5）を維持；有効にすると ARI は非再現トラジェクトリのマーカ（`bfts_web_provenance.json`）を記録します。`idea-skill` の `survey` は、これとは無関係に常に範囲限定の文献検索を行います。`1`/`true`/`yes`/`on` で有効化 | `false` |
| `ARI_RECURSION_DEPTH` | ネストされた ARI 実行の現在深さ（自動設定） | (自動) |
| `ARI_MAX_RECURSION_DEPTH` | orchestrator 再帰の上限 | `3` |
| `ARI_PARENT_RUN_ID` | 再帰時の親 run ID（自動設定） | (自動) |
| `ARI_DISABLED_TOOLS_FOR_CHILD` | 子実行で削減するツールセット | (なし) |
| `ARI_REACT_MEMORY_SEARCH_LIMIT` | `search_memory` の `top_k` 上限 | (スキルデフォルト) |

### 実行モード (RQGM)

探索（`ARI_MODE`）と論文フェーズ（`ARI_PAPER_MODE`）という 2 つの独立した軸は、
それぞれ**二重キーのインターロック**の背後にあります。モード変数とその
`*_ENABLED` の相方が*両方とも*統治経路を選んでいなければ、その軸は既定値
（`simple_bfts` / `linear`）にフォールバックします。片方だけでは何も有効に
なりません。`scripts/setup/setup_env.sh` は以下の変数すべてを、生成される `.env`
にコメントアウトされたテンプレート行として（そのキーがまだ存在しない場合にのみ）
追記し、インターロックをコメントに明記します（「both must agree or ARI falls back
to `simple_bfts`」/「…or the paper phase falls back to `linear`」）。

| 変数 | 目的 | デフォルト |
|---|---|---|
| `ARI_MODE` | 実行モードのオーバーライド: `simple_bfts` \| `ari_rqgm`（workflow.yaml の `ari.mode` をオーバーライド; 不正な値は警告の上で無視される）。RQGM の有効化には加えて `ARI_RQGM_ENABLED` インターロックが必要 — 不一致はすべて `simple_bfts` にフォールバックする。`export_resolved_config_to_skill_env` はスキルサブプロセス向けにこれを*実効*モードで `setdefault` する（v1 でこれを読むスキルは無い）。`ari resume` では `rqgm_state.json` に永続化されたモードがこの変数に優先する。`docs/guides/execution_modes.md` を参照 | `simple_bfts` |
| `ARI_RQGM_ENABLED` | RQGM マスターインターロックのオーバーライド: `0`/`1`/`true`/`false`（workflow.yaml の `rqgm.enabled` をオーバーライド）。ガバナンスランタイムが構築されるには、これ**と** `ARI_MODE=ari_rqgm` の両方が一致している必要がある | `false` |
| `ARI_PAPER_MODE` | 論文フェーズのモードオーバーライド: `linear` \| `rqgm_archive`（workflow.yaml の `paper.mode` をオーバーライド; 不正な値は警告の上で無視される）。`ARI_MODE` とは直交しており、探索軸と論文軸は独立に設定する。アーカイブの有効化には加えて `ARI_RQGM_PAPER_ENABLED` インターロックが必要で、不一致はすべて `linear` にフォールバックする。`apply_paper_env_overrides` が適用するが、論文コマンドはこれを**明示的に**呼ぶ必要がある: 論文エントリの config ローダは env オーバーライドを一切適用しないため、この変数は `ari run` / `ari resume` のオーバーライドブロックに便乗できない。[実行モード](../guides/execution_modes.md)の「論文実行軸: `paper.mode`」を参照 | `linear` |
| `ARI_RQGM_PAPER_ENABLED` | 論文アーカイブのインターロックオーバーライド: `0`/`1`/`true`/`false`（workflow.yaml の `rqgm.paper.enabled` をオーバーライド; 不正な値は警告の上で無視される）。ドラフトアーカイブが有効になるには、これ**と** `ARI_PAPER_MODE=rqgm_archive` の両方が一致している必要がある | `false` |
| `ARI_PAPER_AGENT_AS_JUDGE` | agent-as-judge によるドラフト採点のオーバーライド: `0`/`1`/`true`/`false`（`rqgm.paper.reviewer.agent_as_judge.enabled` をオーバーライド; 不正な値は警告の上で無視される）。`ARI_PAPER_MODE` / `ARI_RQGM_PAPER_ENABLED` と同じ「代入前に検証する」方針で `apply_paper_env_overrides` が適用する。無効 ⇒ 決定論的で LLM を使わない会議ルーブリック採点器が使われ、ドラフト採点経路にライブ LLM 呼び出しは載らない（P2）。有効 ⇒ 実際の `LLMClient` を用いた査読者が各アーカイブドラフトを*同じ*会議ルーブリックの軸で採点し、その重みは ACTIVE な統治対象 `paper_reviewer` プロンプトの強調に従う。決定論的リーダでは読めない軸（`novelty`、`significance`）も読める。LLM エラー、解析不能な応答、ルーブリックの軸重みを十分に覆わない応答では決定論的ルーブリックへフェイルオープンする。実効的な `rqgm_archive` 論文モード（`ARI_PAPER_MODE=rqgm_archive` + `ARI_RQGM_PAPER_ENABLED=1`）でのみ意味を持つ | (未設定 ⇒ 無効) |

以下の 4 つはスイッチではありません。RQGM エポックの実行アイデンティティをより
具体的にするための、任意の配備側の申告です。`capture_execution_identity` はエポック
開始時にそれぞれを読み、未設定または空白の値をリテラル文字列 `unresolved` として
記録し、4 つすべてが解決されない限り `execution_identity.complete` を `false` の
ままにします。ARI は可変のプロバイダエイリアスを固定された実装だとは主張しません。
与えられた値が真実かどうかを検証する仕組みはなく、この pin は測定ではなく申告です。
`docs/reference/configuration.md` にも同じ 4 つが、pin する対象と対応づけて
掲載されています。

| 変数 | pin する対象 | デフォルト |
|---|---|---|
| `ARI_MODEL_REVISION` | 提供元 / モデルの厳密な版 | (未設定 ⇒ `unresolved` として記録) |
| `ARI_TOOL_BUNDLE_REVISION` | 変更不能なツール一式の版 | (未設定 ⇒ `unresolved` として記録) |
| `ARI_ENVIRONMENT_DIGEST` | コンテナまたは環境のダイジェスト | (未設定 ⇒ `unresolved` として記録) |
| `ARI_DATA_SNAPSHOT_DIGEST` | 変更不能な外部データスナップショットのダイジェスト | (未設定 ⇒ `unresolved` として記録) |

`ARI_HARNESS_CONTAINER_ROOT` は同じ `setup_env.sh` のブロックで宣言されますが、
モード選択ではなく Harness の実行基盤に属します。

| 変数 | 目的 | デフォルト |
|---|---|---|
| `ARI_HARNESS_CONTAINER_ROOT` | **論理的な** Harness コンテナ参照（`apptainer:<name>.sif` または `singularity:<name>.sif`）を解決する絶対ルート。検証済みエントリが論理形式を持つのは、公開されるマニフェストにサイト固有のパスを含めないためであり、その結果として具体的なディレクトリは環境からしか与えられない。未設定 ⇒ 論理参照は `HarnessSubstrateError` で拒否される。素のパス参照は互換入力としてそのまま通り、この変数を参照しない。ルートは絶対パスかつ実在するディレクトリで、シンボリックリンクであってはならない。解決後のイメージはそのルート直下にある通常ファイル（シンボリックリンク不可）でなければならず、ルート外へ解決されるものは拒否される | (なし — 論理参照を使う場合のみ必要) |

### バックエンド + エグゼキュータ

| 変数 | 用途 |
|---|---|
| `ARI_BACKEND` | エージェントランタイムのバックエンドセレクタ |
| `ARI_EXECUTOR` | エグゼキュータバックエンド（sync / async） |
| `ARI_CONTAINER_IMAGE` | サンドボックス実行用 SIF / OCI イメージ |
| `ARI_CONTAINER_MODE` | コンテナランタイム: `auto`（デフォルト — 実行環境を検出し、SLURM ジョブ内では Singularity / Apptainer を優先） / `docker` / `singularity` / `apptainer` / `none`。未対応の値はホスト実行へフォールバックせず例外になる |
| `ARI_CONTAINERS_DIR` | コンテナイメージキャッシュルート |
| `ARI_MAX_CHILD_PROCS` | コーディングサンドボックス内の RLIMIT_NPROC 上限。オプトイン方式で、未設定なら追加の上限は掛からない。RLIMIT_NPROC は子孫プロセスではなく real uid の全タスクを数えるため、固定上限はユーザが既にその数のスレッドを持っているだけで `fork` を EAGAIN で失敗させていた |
| `ARI_LOG_LEVEL` | Python `logging` レベル（`INFO` / `DEBUG` / ...） |

### メモリバックエンド

| 変数 | 用途 |
|---|---|
| `ARI_MEMORY_BACKEND` | `letta`（デフォルト）または `in_memory`（Letta 不要；ローカルスモークテスト用の一時 RAM バックエンド） |
| `ARI_MEMORY_AUTO_RESTORE` | resume 時に `memory_backup.jsonl.gz` から自動復元 |
| `ARI_MEMORY_ACCESS_LOG` | `on`（デフォルト） / `off` — memory サーバが `memory_access.jsonl` を記録するか。パス自体は設定不可で、ローテーションサイズは `ARI_MEMORY_ACCESS_LOG_MAX_MB`（デフォルト `100`） |
| `ARI_MEMORY_CONSOLIDATE` | 型付きメモリの統合 + 論文クレーム向けのアーティファクト裏付け済み `verified_context.json`。**デフォルト有効**；`0`/`false`/`no`/`off` で無効化 |
| `ARI_CONTEXT_AUTHORITY_KEY` | core が各スキルのサブプロセスへエクスポートする接続ごとの HMAC キー（`SkillConnection._server_params`）。メモリサーバはバックエンドに触れる前に、署名済み `ari_context` 引数をこのキーで検証します。core が注入し結果からは redact されるため、運用者が設定するものではありません |
| `ARI_LETTA_VENV` | バンドル済み Letta サーバの仮想環境パス |

現在のノード ID は環境変数**ではありません**。したがって環境側に偽の値を置いても
メモリ書き込みの宛先を変えることはできません。`AgentLoop._node_tool_context` が
ノードごとに 1 つの `ToolCallContextV1` を構築し、`SkillConnection.authorize_args` が
それを署名して `ari_context` ツール引数へ注入します。Copy-on-Write ガード
（`ari-skill-memory/src/server.py` の `_require_self`）は、要求された `node_id` を
その署名済みコンテキストの `node_context.node_id` と突き合わせます。
[内部境界](internal_boundaries.md) および
[用語集 → CoW](glossary.md) を参照。

### 査読ルーブリック + 論文査読

| 変数 | 用途 |
|---|---|
| `ARI_RUBRIC` | アクティブにする `reviewer_rubrics/<id>.yaml` を選択 |
| `ARI_RUBRIC_DIR` | ルーブリックディレクトリの上書き |
| `ARI_STRICT_DYNAMIC` | `ari-skill-paper` の dynamic 軸生成を強制 |
| `ARI_NUM_REFLECTIONS` | `review_compiled_paper` のリフレクションラウンド数 |
| `ARI_NUM_REVIEWS_ENSEMBLE` | ルーブリック査読のアンサンブルサイズ |
| `ARI_JUDGE_N_RUNS` | `grade_with_simplejudge` の SimpleJudge 再実行数 |

### クレーム–エビデンスゲート

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_CLAIM_GATE_MODE` | クレーム–エビデンス / 指標正当性ゲートの評価スイッチ。`off` は決してブロックしない；`warn` はエラー / 警告を報告するが finalize をブロックしない；`strict` はブロッキングエラーがある場合に最終ゲートをブロック | `warn`（`off` / `warn` / `strict`） |
| `ARI_COMPARISON_SCOPE` | クロス環境比較を透明性警告として扱うか（`any`）、ブロッキングエラーとして扱うか（`same_environment`、単一アーキテクチャ最適化研究向け）を制御 | `any`（`any` / `same_environment`） |

### ルーブリック自動生成 (v0.7.0)

| 変数 | 用途 |
|---|---|
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | `generate_rubric` の目標葉数 |
| `ARI_RUBRIC_GEN_TEMPERATURE` | LLM temperature 上書き |
| `ARI_PAPERBENCH_RUBRIC_DIR` | venue 条件付き PaperBench ルーブリックテンプレートの検索ルート上書き（未リリース — `docs/reference/rubric_schema.md#venue-conditioned-templates` 参照） |

### PaperBench 再現性 (v0.7.0)

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_PAPERBENCH_PATH` | レビュー済み vendor PaperBench project ルートの上書き。symlink でなく、かつ Git identity が明示の `ARI_PAPERBENCH_COMMIT` 申告と一致する場合のみ受理される — 申告が無ければ上書きは拒否される | `ari-skill-paper-re/vendor/paperbench/project` |
| `ARI_PAPERBENCH_COMMIT` | `ARI_PAPERBENCH_PATH` 上書きが申告する commit。ツリーの実際の Git identity と照合される | (なし — `ARI_PAPERBENCH_PATH` と併用必須) |
| `ARI_REPLICATOR_TIME_LIMIT_SEC` | `run_reproduce` のウォールタイム上限 | `43200`（12 時間） |
| `ARI_REPLICATOR_ITERATIVE` | 反復型レプリケータエージェントを使用 | – |
| `ARI_REPLICATOR_MAX_STEPS` | 反復型が有効なときの反復上限 | – |

### Orchestrator スキル

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_ORCHESTRATOR_HTTP_PORT` | MCP サーバポート（`streamable-http` トランスポート） | `9890` |
| `ARI_ORCHESTRATOR_HTTP_HOST` | MCP サーバの bind ホスト。空文字は不可 | `127.0.0.1` |
| `ARI_ORCHESTRATOR_LOGS` | ログディレクトリ | `$ARI_WORKSPACE/logs` |
| `ARI_ORCHESTRATOR_DRY_RUN` | 実際の `ari run` をスキップ（スモークテスト用）。有効化は `1` | – |

### Transform スキル

| 変数 | 用途 |
|---|---|
| `ARI_TRANSFORM_MEMORY_MAX_CHARS` | 呼び出しごとの合計メモリ予算 |
| `ARI_TRANSFORM_MEMORY_MAX_ENTRIES` | 呼び出しごとのエントリ上限 |

### Web / 検索スキル

| 変数 | 用途 |
|---|---|
| `ARI_RETRIEVAL_BACKEND` | `semantic_scholar` / `arxiv` / `alphaxiv` |

### Federated tool registry スキル

Skill フラグとカタログは独立した 2 つのゲートです。`ari-skill-tool-registry`
を有効化してもリーフは 1 つも有効になりません。選択された lock に存在する
source だけが実行できるためです。

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_TOOL_REGISTRY_LOCK` | ブローカーがプロセス起動時に読み込む、レビュー済みの `CATALOG.lock`。ARI 側の Provider カタログローダーも同じ変数を読むため、composite provision が指すリーフが両者でずれることはない。マテリアライズ済みカタログは絶対パスを含みリポジトリには置けないので、この上書きが唯一の到達手段 | スキルに同梱された `CATALOG.lock`。これは可搬なデフォルトであり、内容の入ったカタログはマシン固有のエビデンスなので、設計上そのまま空でチェックインされている |
| `ARI_TOOL_REGISTRY_INDEX` | その lock に対応する派生インデックス | 解決された lock と同じディレクトリの `catalog.index.json`。ファイルが無い場合は lock から再構築 |

### 公開 + レジストリ + clone

| 変数 | 用途 |
|---|---|
| `ARI_PUBLISH_DRYRUN` | `--dry-run` を強制（CI 安全用、v0.7.0） |
| `ARI_PUBLISH_SETTINGS` | 公開設定 JSON へのパス |
| `ARI_REGISTRY_DATA` | `ari registry serve` 用の sqlite + artifact ルート（必須設定） |
| `ARI_REGISTRY_TOKEN` | `ari clone ari://...` および `ari ear publish --backend ari-registry` 用 bearer token |
| `ARI_REGISTRY_URL` | レジストリエンドポイントの上書き |
| `ARI_REGISTRY_NAME` | 複数登録時のデフォルトレジストリ名 |
| `ARI_REGISTRIES_FILE` | `registries.yaml` の場所を上書き（未指定時はアクティブなチェックポイント配下を参照） |
| `ARI_LOCAL_TARBALL_OUT` | `local-tarball` 公開バックエンドの出力パス |
| `ARI_GH_REPO` | `gh` バックエンド向けの GitHub リポジトリ |
| `ARI_GH_MODE` | `gh` バックエンドのモード: `commit`（デフォルト — bundle/manifest/README をリポジトリへ push）または `releases`（タグ付き release を作成し tarball を添付） |
| `ARI_CLONE_HTTP_TIMEOUT` | `ari clone` の HTTP タイムアウト |

### SLURM デフォルト

| 変数 | 用途 |
|---|---|
| `ARI_SLURM_PARTITION` | デフォルトパーティション |
| `ARI_SLURM_CPUS` | デフォルト `--cpus-per-task` |
| `ARI_SLURM_GPUS` | デフォルト `--gres=gpu:N` |
| `ARI_SLURM_MEM_GB` | デフォルトメモリリクエスト |
| `ARI_SLURM_WALLTIME` | デフォルト `--time` |
| `ARI_SLURM_ALLOW_NO_GRES` | **現在この名前を読むコードは存在せず、設定しても何も変わりません。** かつては GPU 用 GRES が設定されていないクラスタで `--gres` / `--gpus-*` を黙って削除する opt-in で、`scripts/setup/setup_env.sh` は今もコメントアウト状態で書き出します。GRES 無しの扱いは現在 `ari/capability_binding/environment.py` 側で決まります: GRES 会計を伴わずに観測されたデバイスは feature `gpu-observed-on-slurm-node`／allocation mode `observation-only-no-gres` として記録されるだけで、GRES が観測されたか exclusive-node-inventory の pin が一致しない限り schedulable な `gpu` リソースにはなりません。したがって CPU へ黙って落ちるのではなく binding が成立しません。 |

### PaperBench 再現フェーズ（Stage 2）

| 変数 | 用途 |
|---|---|
| `ARI_PHASE1_SANDBOX` | `auto` / `local` / `docker` / `apptainer` / `singularity` / `slurm`。`server.run_reproduce` および `bridge.reproduce_submission` が使用するサンドボックスランナーを強制。 |
| `ARI_PHASE1_DOCKER_IMAGE` | `sandbox_kind=docker` で明示的な `container_image` が指定されていない場合のデフォルト docker イメージ。組み込みのデフォルトは無く、未設定ならイメージは空のままで、勝手に補われず run が拒否される。 |
| `ARI_PHASE1_APPTAINER_IMAGE` | `sandbox_kind=apptainer`/`singularity` で明示的な `container_image` が指定されていない場合のデフォルト SIF / docker URI。 |
| `ARI_PAPERBENCH_PATH` | vendor 化された PaperBench project ルートのパス上書き（デフォルト: `ari-skill-paper-re/vendor/paperbench/project`。内側の `project/paperbench` を指す値は `project` へ正規化される）。`ARI_PAPERBENCH_COMMIT` が必須 — 上記参照。 |
| `ARI_REPLICATOR_TIME_LIMIT_SEC` | 呼び出し元が `0` を渡したときのデフォルト Stage 1 エージェントロールアウト時間予算。 |
| `ARI_REPLICATOR_ITERATIVE` | `1` ⇒ Stage 1 ロールアウトのデフォルトを IterativeAgent バリアントに変更。 |
| `ARI_REPLICATOR_MAX_STEPS` | デフォルト Stage 1 ステップ上限。 |
| `ARI_AGENT_ENV_PATH` | `bridge.rollout_submission` が `agent_env_path` 引数未指定時に自動ロードする vendor スタイルの `agent.env` ファイル（1行1 `KEY=VALUE`）のデフォルトパス。これも空の場合は `~/.ari/agent.env` にフォールバック。この vendored な PaperBench-replicate の認証情報探索（`ari-skill-paper-re/src/_paperbench_bridge.py`）は、v0.5.0 で削除された ARI 独自の `$HOME/.ari/` 実行ストレージとは別物であり、フォールバックは現在も有効です。Stage 1 エージェントへ論文固有の認証情報（例: `HF_TOKEN`）を渡すために使用。 |
| `HF_TOKEN` | Hugging Face Hub トークン。呼び出しプロセスに設定されている場合、`bridge.rollout_submission` がエージェントの環境に自動で転送（vendor `nano/eval.py:172-179` の well-known-credential パターン）。Stage 1 ロールアウトで `huggingface-cli login` を呼び出す PaperBench 論文では必須。 |
| `ARI_JUDGE_N_RUNS` | ウィザード / 呼び出し元が `0` を渡したときの SimpleJudge 呼び出しのデフォルト `n_runs`。PaperBench 論文 §4.1 のシングルパスデフォルトは 1。 |
| `ARI_MODEL_JUDGE` | デフォルトジャッジモデル ID（LiteLLM ルーティング）。 |
| `ARI_MODEL_REPLICATOR` | デフォルト Stage 1 ロールアウトモデル ID。 |

### GUI サーバー (`ARI_GUI_*`)

8 つのスイッチが `ari viz` ダッシュボードのシェル、そのネットワーク露出、運用面を
制御します。8 つすべてが `scripts/setup/setup_env.sh` に（コメントアウトで）宣言
されており、すべてが**ロールバックレバー**です: 解除すれば現在の既定値になり、設定
すれば再デプロイ無しに文書化された以前の挙動へ戻ります。

| 変数 | デフォルト（未設定時） | 設定時の効果 | ロールバックの意味論 |
|---|---|---|---|
| `ARI_GUI_V2` | オン (`1`) | `0` / `false` でレガシーのダッシュボードシェルへ戻す。 | v2 シェルのキルスイッチ; 撤去ゲートは G6。 |
| `ARI_GUI_BIND` | ループバックのみ (`127.0.0.1` + `::1`) | バインドアドレス: `::` = レガシーの全インタフェースデュアルスタック、`0.0.0.0` = IPv4 ワイルドカード、または単一アドレス。 | 従来の全インタフェースバインドを復元。非ループバックの値はサーバーを**リモートモード**へ切り替える（`ARI_GUI_TOKEN` を参照）。 |
| `ARI_GUI_CORS_ANY` | オフ — same-origin のエコーのみ | `1` でレガシーの `Access-Control-Allow-Origin: *` ワイルドカードを復元。 | クロスオリジンのトンネル / ポータル構成でのみ必要; `:5173` の Vite 開発プロキシには**不要**。 |
| `ARI_GUI_CHALLENGES` | オン — チャレンジ必須 | `0` で delete-checkpoint / stop / gpu-monitor-stop のサーバー発行確認チャレンジを無効化し、直接実行へ戻す。 | オンのとき、これらのエンドポイントは有効な `challenge_id` なしに `428` を返す; 発行側エンドポイントはどちらでも利用可能。 |
| `ARI_GUI_CSP` | オン — ヘッダを送出 | `0` で GUI の index / 静的レスポンスから `Content-Security-Policy`、`X-Content-Type-Options`、`Referrer-Policy` を外す。 | プロキシ構成が WebSocket ポートをリマップし、ポリシーがそれをブロックする場合にのみ必要（そのとき GUI はポーリングへ縮退する）。 |
| `ARI_GUI_TOKEN` | 未設定 | リモートモードが要求する bearer トークン: `/health*` 接頭辞を除くすべてのリクエストが `Authorization: Bearer <token>` を送る必要がある; SSE と WebSocket は `?token=` として受け付ける。 | **リモートバインド時に**未設定であることは開放ではなくフェイルセキュアです: サーバーが起動時にランダムな 32 hex のトークンを生成し、stderr へ一度だけ出力する。ループバック既定では決して必要ない。 |
| `ARI_GUI_AUTH` | オン（リモートモード時） | `0` でリモートのトークンゲートを無効化し、未認証のリモートバインドへ戻す。 | 自前で認証を終端する信頼済みネットワーク（例: 認証を行うリバースプロキシ）のための文書化された脱出ハッチ。ループバックバインドはいずれにせよ未認証。 |
| `ARI_GUI_HEALTH` | オン | `0` で運用可視化の面を無効化: `GET /health/live` と `/health/ready` は SPA レスポンスへ落ち、`GET /api/v1/diagnostics` は型付き 404 を返す。 | 新しい JSON を見てはならないプローブ収集構成のために、プローブ導入前のワイヤ挙動を厳密に復元する。 |

完全な信頼モデルは
[REST API → 認証](rest_api.md#認証)を、チャレンジのプロトコルは
[REST API → 確認チャレンジ](rest_api.md#確認チャレンジ)を参照してください。

## SLURM (`SLURM_*`)

| 変数 | 用途 |
|---|---|
| `SLURM_MODE` | `local`（デフォルト）/ `ssh` |
| `SLURM_SSH_HOST` | リモート SLURM モード用 SSH ホスト |
| `SLURM_SSH_USER` | SSH ユーザ（デフォルトは現在のユーザ） |
| `SLURM_SSH_PORT` | SSH ポート（デフォルト `22`） |
| `SLURM_SSH_KEY` | 秘密鍵パス |
| `SLURM_SSH_PASSWORD` | 任意のパスワード（鍵方式を推奨） |
| `SLURM_DEFAULT_PARTITION` | ARI が起動するサブジョブのデフォルトパーティション |
| `SLURM_PARTITION` | ジョブごとのパーティション上書き |
| `SLURM_VALID_PARTITIONS` | カンマ区切りの許可リスト |
| `SLURM_LOG_DIR` | `*.out` / `*.err` の書き込み先 |
| `SLURM_CLUSTER_NAME` | ダッシュボードに表示される名前 |
| `SLURM_JOB_ID` / `SLURM_JOB_NODELIST` / `SLURM_JOB_PARTITION` | ARI がジョブ内で実行される場合に SLURM が設定 |

## Letta (`LETTA_*`)

| 変数 | 用途 |
|---|---|
| `LETTA_BASE_URL` | Letta API ベース（デフォルト `http://localhost:8283`） |
| `LETTA_API_KEY` | Letta が認証を要求する場合の API キー |
| `LETTA_EMBEDDING_CONFIG` | 埋め込み設定 JSON へのパス（必須） |

## Ollama / OpenAI (`OLLAMA_*` / `OPENAI_*`)

| 変数 | 用途 |
|---|---|
| `OLLAMA_HOST` | Ollama のアドレス。backend が `ollama` のとき ARI は Ollama の api_base として読む（デフォルト `http://localhost:11434`） |
| `OLLAMA_BASE_URL` | LiteLLM 側ベース URL |
| `OPENAI_API_KEY` | OpenAI / OpenAI 互換 API キー |

## VLM

| 変数 | 用途 | デフォルト |
|---|---|---|
| `ARI_VLM_MODEL` | 図 / 表の査読用ビジョン LLM。`VLM_MODEL` より優先 | (なし) |
| `VLM_MODEL` | `ARI_VLM_MODEL` 未設定時に読まれるフォールバックのビジョン LLM id。組み込みデフォルトは無く、どちらも未設定ならビジュアルレビューはモデルを勝手に選ばず拒否する | (なし) |

## 関連ドキュメント

- `docs/reference/configuration.md` — 同じ環境変数をユースケース別にまとめたナラティブガイド。
- `ari-core/ari/config/__init__.py` — `ARI_*` グループのほとんどを扱う Pydantic 設定モデル。
- 各スキルの `README.md` — そのスキル固有の環境変数。
