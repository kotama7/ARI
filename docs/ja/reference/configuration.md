---
sources:
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/configs
    role: config
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/ari/viz/state.py
    role: implementation
  - path: ari-core/ari/viz/v1/secrets.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/rqgm/budget.py
    role: implementation
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: ari-core/ari/config/resolver.py
    role: implementation
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/viz/v1/config_api.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/cli/lineage.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/tests/test_gui_baseline_settings_contract.py
    role: test
  - path: ari-core/tests/test_gui_config_shadow_legacy.py
    role: test
  - path: ari-core/tests/test_gui_v1_mode_selection.py
    role: test
last_verified: 2026-08-08
---

# 設定リファレンス

## 設定の優先順位（実測された挙動）

ARI の設定は複数の入口から入ってきます。**優先順位のチェーンは 2 本**あり、
ある設定値が最終的に何に解決されるかは*誰が問い合わせているか*に依存します。

- **ランタイム (core/CLI)** — エージェントループとパイプラインが実際に使う値。
  `ari.config.load_config()`（YAML が無い場合は `auto_config()`）が構築します:
  **`ARI_*` 環境変数 > workflow.yaml / config YAML > Pydantic フィールド
  デフォルト**。環境変数が常に勝つのは、`_apply_*_env_overrides` 群が
  （プロファイルのマージ後に）*最後に*走るためです。`auto_config()` は
  ファイルが無い場合のフォールバック（環境変数がハードコード値に優先）。
  プロファイル (`--profile laptop|hpc|cloud`) は YAML と環境変数の間で
  適用されますが、ディープマージでは**ありません** — `_apply_profile`
  (`ari/cli/run.py`) がコピーするのはちょうど 4 キーだけで、プロファイル
  ファイル内のそれ以外のキーは黙って無視されます（後述の*解決モデル*にある
  「プロファイルのマージは 4 キーだけ」の注意点を参照）。
- **GUI 設定パネル** — `/api/settings` が表示する値。`_api_get_settings()` が
  構築します: **保存済み `settings.json`（truthy な場合）> `ARI_*` 環境変数 >
  `workflow.yaml` > ハードコードのデフォルト**。ただし falsy 再充填の癖が
  あります（保存済みだが空の `llm_model`/`llm_provider` は `workflow.yaml`
  からのみ再充填され、環境変数の層は落ちます）。

**橋渡し**: GUI の `/api/launch` は選択内容を引数として CLI に渡すことは
**しません** — サブプロセスの `ARI_*` 環境変数に書き込み、**かつ**
`{checkpoint}/launch_config.json` にスナップショットします。CLI はその後、
上記のランタイムチェーンで解決します。`launch_config.json` がディスクから
読み直されるのは `/api/run-stage` とダッシュボード表示状態の再構成のときだけで、
`ari.config` が再パースすることは*ありません*。

| 設定 | 勝ち順（高い順） | 決定箇所 |
|---------|-------------------------------|-----------|
| `llm_model`（ランタイム） | `ARI_MODEL` > `ARI_LLM_MODEL` > YAML `llm.model` > `qwen3:8b` | `config/__init__.py:_apply_llm_env_overrides` |
| `llm_model`（GUI 表示） | メモリ上の `_launch_llm_model` > `launch_config.json` > `settings.json` > `workflow.yaml` > `''` | `viz/routes.py`、`viz/ui_helpers.py` |
| `llm_model`（Settings マージ） | 保存済み `settings.json`（truthy な場合）> `ARI_LLM_MODEL` > `workflow.yaml` > `''` | `viz/api_settings.py:_api_get_settings` |
| `llm_provider`/`backend`（ランタイム） | `ARI_BACKEND` > YAML `llm.backend` > `ollama` | `config/__init__.py:_apply_llm_env_overrides` |
| 論文 `language` | `ARI_PAPER_LANGUAGE` 環境変数**のみ**（GUI 起動時に設定される。手動で CLI を回した場合は `launch_config.json` から再導出され*ません*） | `ari-skill-paper` が環境変数を読む; `viz/api_experiment.py` が設定する |
| GUI ポート | `ARI_GUI_PORT`（`start.sh` 経由）> `--port`（argparse デフォルト **8765**）> `state.py` の `9886` プレースホルダ | `start.sh`、`viz/server.py:main` |
| SLURM パーティション | 明示的なツール `partition` kwarg（sinfo 検証済み）> `SLURM_DEFAULT_PARTITION` > sinfo の先頭。kwarg 自体は experiment.md の `Partition:` > `ARI_SLURM_PARTITION` > sinfo から選ばれる | `ari-skill-hpc/slurm.py`、`ari/agent/workflow.py` |
| checkpoint ディレクトリ | `ARI_CHECKPOINT_DIR` > YAML `checkpoint.dir` > `workspace/checkpoints/{run_id}` | `config/__init__.py:_apply_checkpoint_env_overrides`、`PathManager` |
| workspace ルート | `ARI_CHECKPOINT_DIR`（そこから復元: 最も外側の `checkpoints/` 祖先の親。該当する祖先が無ければ checkpoint 自身の親）> 明示的な `workspace_root` 引数 > `{ARI_ROOT}/workspace` > `{repo_root}/workspace`（`{repo_root}/ari-core` がディレクトリのときのみ）> 解決済みのカレントディレクトリ | `paths.py:RuntimePathResolver.resolve_workspace_root` |
| `bfts_pipeline[].enabled` | `{checkpoint}/workflow.yaml` > パッケージ同梱の `ari-core/config/workflow.yaml` > `true` | `cli/bfts_loop.py`（生 YAML 読み） |
| `lineage_decision.*` | 有効な rubric の `lineage_thresholds`（`ARI_RUBRIC`。4 つのしきい値キーのみで `mode` は対象外）> パッケージ同梱の `ari-core/config/workflow.yaml` > `./config/workflow.yaml`（プロセスの cwd）> 呼び出し側のデフォルト | `cli/lineage.py:_load_lineage_decision_config` |
| `root_idea_selection.enabled` | パッケージ同梱の `ari-core/config/workflow.yaml` **のみ** > `false` | `cli/bfts_loop.py`（生 YAML 読み） |

**「workspace ルートとは何か」の所有者は 1 つだけです。** 上表の 5 段の
ラダーは `RuntimePathResolver.resolve_workspace_root()`
（`ari-core/ari/paths.py`）という単一の関数にしか存在せず、本番の呼び出し元は
すでに 4 箇所あります: `ARI_CHECKPOINT_DIR` が未設定のときの `auto_config()`
（`ari/config/__init__.py`）、`workspace_harness_root()`
（`ari/harness_registry.py`。自前の `ARI_WORKSPACE` ショートサーキットの後）、
GUI 文書ストア（`ari/viz/v1/store.py`）、そして
`{workspace_root}/checkpoints/{run_id}` を発行する v1 起動パス
（`ari/viz/v1/launch.py`）です。コードを開いたときに読み飛ばすべき点が 2 つ:
このメソッドの docstring はいまだに自らを*additive* と述べ、オプトインは
「005 に先送り」と書いていますが、これは古い記述です（上記 4 箇所がその
オプトインです）。また [環境変数](environment_variables.md) は
*チェックポイント + パス* の節で `ARI_ROOT` を「テストで使用」と
位置づけていますが、これは過小評価です。`ARI_ROOT` は
このラダーの第 3 段であり、`ARI_CHECKPOINT_DIR` が未設定なら実運用のランが
どこに落ちるかを決めます。一方で*変わっていない*こと: `PathManager()` の
素のコンストラクタは今もカレントディレクトリを既定とし、このラダーを
参照しません。

**falsy と欠損の違い:** core 側の環境変数オーバーライドのガード（`if _m:` など）は
空の環境変数を欠損として扱います（YAML／デフォルトを保持。`base_url` だけは
明示的に `!= ""` を使う）。GUI のマージ `{**defaults, **saved}` は「存在するが空」の
保存済みキーを勝たせ、その後 `llm_model`/`llm_provider` だけを `workflow.yaml`
から強制的に再充填します。

**2 つの `workflow.yaml` ブロックはパッケージ同梱のコピーからしか読まれません
（アンチパターン）。** `lineage_decision` と `root_idea_selection` は
`ARIConfig` の宣言済みフィールドではないため、`load_config` の
`{k: v for k, v in raw.items() if k in ARIConfig.model_fields}` フィルタで
捨てられ、それぞれ専用のリーダが生の YAML から読み直しています。そしてこの
2 つのリーダは、*どの* `workflow.yaml` を読むかについて他と揃っていません。
`bfts_pipeline` は checkpoint 優先で読まれます — `{checkpoint}/workflow.yaml`
を先に見て、パッケージ同梱のコピーはフォールバックにすぎません。一方
`_load_lineage_decision_config`（`ari/cli/lineage.py`）はパッケージ同梱の
`ari-core/config/workflow.yaml` を読み、そのファイルが存在しないときにだけ
プロセスの作業ディレクトリ基準の `./config/workflow.yaml` にフォールバック
します。`root_idea_selection` ブロックに至ってはパッケージ同梱のコピーしか
読みません。checkpoint 優先の読みとパッケージのみの読みが、同じ
`ari/cli/bfts_loop.py` の中に同居しています。帰結: どちらのブロックも
`{checkpoint}/workflow.yaml` に書いても効かず、`--config` で渡しても効きません
（型付きローダは捨て、どちらのリーダもそのパスを見ないため）。実行ごとに
これらを変えるにはパッケージ同梱の `workflow.yaml` を編集してください。
`lineage_decision` の 4 つのしきい値キーについては、有効な rubric の
`lineage_thresholds` オーバーレイが会場ごとに調整するための正規の手段です。
これは設計された階層ではなく既知の不整合であり、新しいリーダはこの
パッケージのみのパターンを踏襲すべきではありません。

**未知のトップレベルキーは警告なしに捨てられます。** `load_config` は
`ARIConfig` を構築する際、宣言済みの pydantic フィールドに一致するトップ
レベル YAML キーだけを使います — `ari/config/__init__.py` の
`{k: v for k, v in raw.items() if k in ARIConfig.model_fields}` フィルタです。
`ARIConfig` は `extra="allow"` を設定していますが、ここでは何も救いません。
フィルタが構築の*前*に走るからです。宣言されていないブロックでも効くものが
あるのは、専用のリーダが型付き設定を経由せず生の YAML を読み直している
ためです — `memory` は `_apply_memory_section`、`container` は
`ari/cli/run.py`、`lineage_decision` は
`ari/cli/lineage.py:_load_lineage_decision_config`、加えて `bfts_pipeline`、
`pipeline`、`claim_gate_policy`。リゾルバがそうしたリーダを現在認めて
いるトップレベルキーを列挙したものが
`ari.config.resolver.KNOWN_NON_CONFIG_TOP_KEYS` ですが、これは導出された
一覧ではなく手で維持されている一覧であり、**網羅していません**。この
一覧が勘定に入れていない汎用の消費者がもう 1 つあります: パイプライン
ドライバ (`ari/pipeline/driver.py`) が生の `workflow.yaml` を読み直し、
トップレベルのスカラーをすべてステージテンプレートの名前空間に流し込み
ます（トップレベルの dict も `pipeline`/`skills`/`stages` を除きドット記法
用に露出します）。したがって宣言されていないトップレベルキーは
`ARIConfig` からは落ちても、ステージの `inputs:` 内では `{{key}}` として
依然到達可能です。バンドル版の
`ari-core/config/workflow.yaml` はまさにこれに依存していて、
`paper_venue: arxiv` と `paper_rubric: generic_conference` は
`ARIConfig.model_fields` にも `KNOWN_NON_CONFIG_TOP_KEYS` にも無いのに
生きています — `write_paper` が `rubric_id: '{{paper_rubric}}'` と
`venue: '{{paper_venue}}'` を取り、`review_compiled_paper` も再度
`rubric_id` を取ります。`paper_rubric` はレビュー用 rubric を選ぶ設定で
あり、`write_paper_iterative` にはその環境変数フォールバックも推測既定値も
無いので、死んだ設定どころかその逆です。*どこからもテンプレート参照され
ない*トップレベルキーは完全に破棄され、その際に何もログされません。
`ari.config` の中に
**近似綴りの検出（「もしかして」チェック）は存在しません**。したがって
`rqgm:` を `rqmg:` と綴り間違えると、エラーは一切出ないまま、その実行は
黙ってデフォルトのままになります。これを部分的に補うものが 2 つありますが、
どちらもロード時の CLI 上ではありません:

- **リゾルバはペイロード内で警告します。** `_apply_workflow_layer`
  (`ari/config/resolver.py`) は、`ARIConfig.model_fields` と
  `KNOWN_NON_CONFIG_TOP_KEYS` のいずれにも属さないキーごとに
  `workflow.yaml top-level key '…' is not an ARIConfig field — load_config
  silently drops it (no reader consumes it)` を追加します。これは
  `GET /api/v1/runs/{run_id}/resolved-config`（checkpoint 内の
  `workflow.yaml` のコピーを読む）と新規実行プレビュー（バンドル版を読む）の
  `warnings` 配列を通じて届きます。綴りの提案ではなく単なる列挙であり、
  `ari.viz.v1` の外からリゾルバを呼ぶものは無いので、手動で回した CLI が
  これを見ることはありません。なお `(no reader consumes it)` という文面は
  検証済みの主張として読まないでください: バンドル版 `workflow.yaml` に
  対してこの警告が出るのは `paper_venue` と `paper_rubric` の 2 件だけで、
  そのどちらも実際には消費されています。この警告が示すのはキーが
  `ARIConfig` に届かなかったことであって、そのキーが無効であることでは
  ありません。
- **不在は checkpoint 側で観測できます。** `{checkpoint}/rqgm_state.json` は
  `ari.mode: ari_rqgm` と `rqgm.enabled: true` の両方が成り立つときだけ
  書かれる（`ari/cli/run.py`）ので、ファイルが無いことはその実行が
  `simple_bfts` だったことを意味します。デフォルト以外の実行モードが実際に
  効いたかどうかは、エラーが出ないことではなく、このファイルで確認して
  ください。

同じフィルタが、後方互換の方向を安全にしています。ある `ari-core` ビルドが
フィールドとして宣言していないブロックは、致命的エラーではなく無視される
だけなので、新しい YAML を古い core に載せてもロード失敗にはならず、その
core のデフォルトに縮退します。

> ⚠ この優先順位は**今日の観測結果としてそのまま記述**したものであり、変更した
> ものではありません。統合に先立ち、順序はテスト（`test_config.py`、
> `test_default_provider.py`、`test_launch_config.py`、`test_settings_*`）で
> ロックされています。かつて後続作業として提案されていた中央集約ローダは、
> GUI 経路にのみ実在します — `ari.config.resolver`（`legacy-compatible-1`、
> 次節で説明）。これはこのチェーンを事後的に**再構成**するものであって置き換え
> ではなく、CLI は今も上記のとおりに解決します。

## 設定コントロールプレーン (`/api/v1/config/*`)

GUI の設定面は、機械的に検査される 3 つの部品の上に構築されています:

1. **フィールドレジストリ** — 宣言済みのすべての設定葉についての正準メタデータ
   インベントリ（`ari-core/ari/config/field_registry.py`）;
2. **リゾルバ** — 解決コンテキストごとに 1 つの関数があり、各実効値がどこから来たか
   を説明します（`ari-core/ari/config/resolver.py`）;
3. **文書ストア** — GUI 専用のプロジェクト設定 / ランテンプレート / ランドラフト
   （`ari-core/ari/viz/v1/store.py`）。

3 つとも実行時に対しては読み取り専用です: `ARIConfig` を変更せず、`os.environ` へ
書き込まず、CLI / `simple_bfts` の経路はそれらを一切読みません。これらは UI が設定を
*説明*できるように存在するものであり、ランが実際に使う値は従来どおり実行時の優先
順位連鎖を通って届きます。

### フィールドレジストリ（正準のフィールドメタデータ）

`GET /api/v1/config/schema` がレジストリを配信します — **メタデータのみで、実効値は
決して含みません**。各エントリは 1 つの `ARIConfig` の葉を記述します:

| キー | 意味 |
|---|---|
| `path` | ドット区切りの葉のパス（`bfts.max_total_nodes`）。安定した同一性です。 |
| `value_type` | 描画された pydantic の注釈（`int`、`str \| None`、`list[SkillConfig]`、`dict[str, float]` など）。`Literal` はそのメンバの型（`str`）として描画され、メンバは `enum` に入ります。 |
| `default` | pydantic のデフォルト（またはデフォルトファクトリの値）。`secret_reference` の葉では強制的に `null` になります。 |
| `enum` | 注釈が閉じた集合であるときの `Literal` メンバ、そうでなければ `null`。 |
| `required` | このフィールドにデフォルトが無いかどうか。 |
| `category` | UI のグルーピング: Models、Skills、Search (BFTS)、Infrastructure、Evaluation、Execution mode、Governance、Proposal routing。 |
| `level` | `basic` / `advanced` / `expert` — 段階的開示。 |
| `scope` | `preference` / `installation` / `project` / `template` / `run` — どの文書がこの値を所有してよいか。 |
| `sensitivity` | `public` / `internal` / `secret_reference`。 |
| `mutability` | `draft` / `new_run_only` / `resume_mutable` / `read_only`。 |
| `applies_when` | 依存関係の述語（`bfts.frontier_score=depth_penalized`）または `null`。 |
| `notes` | 手書きの注意（例: 「yaml_only: GUI フィールドも `ARI_*` フックも無い」）。 |
| `source` | `pydantic` — 走査対象は宣言済みモデルフィールドのみです。 |
| `env_override` | この葉を上書きする `ARI_*` 変数、または `null`。 |

**被覆率の不変条件。** レジストリは現在**204 葉・メタデータ被覆率 100 %** です:
`build_field_registry()` は、走査した葉に `FIELD_META` の接頭辞または厳密な
エントリが無い場合 `LookupError` を送出するため、新しい設定フィールドがスキーマ
メタデータ無しに出荷されることはできません。現在の分布: Governance 104 /
Models 32 / Search (BFTS) 24 / Proposal routing 14 /
Manuscript completeness 10 / Infrastructure 5 / Scientific assurance 5 /
Evaluation 4 / Execution mode 4 / Skills 2; expert 150、advanced 18、basic 36;
`public` 203 + `secret_reference` 1（`llm.api_key`）; `new_run_only` 146 +
`draft` 58; 20 葉が `env_override` を持ちます。

意図的な忠実度の限界（黙ってではなく文書化されています）:

- 走査されるのは**宣言済みの pydantic フィールド**のみです。`extra="allow"` の
  YAML ブロック（`hpc`、`container`、`memory`、`letta`、`claim_gate_policy`、
  `lineage_decision` など）はモデルフィールドを持たないため葉もありません;
  それらの `FIELD_META` 接頭辞は、型付けされる日のために先行宣言されています。
- リスト / 辞書のフィールド（`skills`、`resources`、`evaluator.axis_weights`、
  `evaluator.custom_axes`）は**単一の複合葉**です — 要素のパスはインデックス依存で
  あり、安定した同一性にならないからです。
- このモジュールは純粋です: ファイルシステム、時計、環境の読み取り、LLM のいずれも
  ありません。2 回のビルドはバイト単位で同一です（P2）。

同じレジストリが書き込み検証も駆動します。`PATCH` のボディは
`{"values": {"dotted.path": value}}` であり、`validate_patch` が検査します。その閉じた
拒否語彙は `unknown_path`、`secret_reference`、`read_only`、`not_project_scope`、
`invalid_enum`、`invalid_type`、加えてパス横断の `mode_interlock_mismatch` です。
シークレットと `read_only` のフィールドはすべての対象で拒否されます;
`new_run_only` のフィールドはテンプレート / ドラフトでは正当（将来のランを設定
するため）ですが、scope が `project` でない限りプロジェクト設定では拒否されます。

**モードの葉とインターロック規則。** 4 つの `Execution mode` の葉
（`ari.mode`、`rqgm.enabled`、`paper.mode`、`rqgm.paper.enabled`）は
`scope: run`、`mutability: new_run_only` であり、**2 つの組**を成します —
`field_registry.py` の `MODE_INTERLOCK_PAIRS` がその単一の源であり、
`resolver.INTERLOCK_PAIRS` はそのエイリアスです。組は 1 つの意図です: 片側だけが
現れて一致する相方を欠く文書は `mode_interlock_mismatch` で拒否されます
（`validate_mode_interlocks`。評価対象は生のパッチではなくマージ後の文書の値です）。
ADR-09 以降、GUI クライアントが書けるモード / ガバナンスの葉はこの 4 つだけで、
しかも新規ランに限られます; `Execution mode` カテゴリと `rqgm.*` ツリーの残り
104 パスはファイル専用のままで、`POST /api/v1/runs` が `mode_locked` で拒否します
（`viz/v1/launch.py:locked_launch_paths`）。
それらの `applies_when` メタデータは `path=value` のゲートではなくペアリングの
*注記*（"paired with `rqgm.enabled` (one intent — set both)"）を持ちます。
どちらか片方をもう片方でゲートすると、インターロック自体が自己ゲートに
なってしまうからです。

`env_override` の列は `ari/config/__init__.py` の `apply_*_env_overrides`
ファミリを逐語で書き写したものです:

| 設定の葉 | 環境変数 |
|---|---|
| `llm.model` | `ARI_MODEL`（別名 `ARI_LLM_MODEL`） |
| `llm.backend` | `ARI_BACKEND` |
| `llm.base_url` | `ARI_LLM_API_BASE` |
| `checkpoint.dir` | `ARI_CHECKPOINT_DIR` |
| `logging.dir` | `ARI_LOG_DIR` |
| `logging.level` | `ARI_LOG_LEVEL`（auto-config / YAML 無しの経路のみ） |
| `bfts.max_total_nodes` | `ARI_MAX_NODES` |
| `bfts.max_depth` | `ARI_MAX_DEPTH` |
| `bfts.max_react_steps` | `ARI_MAX_REACT` |
| `bfts.max_parallel_nodes` | `ARI_PARALLEL` |
| `bfts.timeout_per_node` | `ARI_TIMEOUT_NODE` |
| `bfts.frontier_score` | `ARI_FRONTIER_SCORE` |
| `bfts.allow_web` | `ARI_BFTS_ALLOW_WEB` |
| `evaluator.composite` | `ARI_COMPOSITE` |
| `evaluator.axis_mode` | `ARI_AXIS_MODE` |
| `ari.mode` | `ARI_MODE` |
| `rqgm.enabled` | `ARI_RQGM_ENABLED` |
| `paper.mode` | `ARI_PAPER_MODE` |
| `rqgm.paper.enabled` | `ARI_RQGM_PAPER_ENABLED` |
| `rqgm.paper.reviewer.agent_as_judge.enabled` | `ARI_PAPER_AGENT_AS_JUDGE` |

### 解決モデル

どちらの解決モードも `resolver_version: "legacy-compatible-1"` を報告します —
これはアルゴリズムの同一性であり、ペイロードの `schema_version` とは別にバージョン
管理されます。初代のリゾルバは、現在の命令的な優先順位を改善するのではなく意図的に
*再現*します。

**A) 既存チェックポイント**（`GET /api/v1/runs/{run_id}/resolved-config`）—
`load_config` を再実行せずにランを事後説明します:

| # | 層 | `source` | 確信度 |
|:--:|---|---|---|
| 1 | pydantic のデフォルト | `default` | 高 |
| 2 | `{ckpt}/workflow.yaml`（モデルフィールドのキー） | `workflow` | 高 |
| 3 | `{ckpt}/launch_config.json` のノブ | `launch_config` | 高 |
| 4 | **現在の**環境。文書化された `ARI_*` のみ | `env` | **低** |
| 5 | `{ckpt}/rqgm_state.json` に永続化されたモード | `checkpoint_state` | 高、`mutable: false` |

層 4 が低確信度なのは意図的です: 読まれている環境は*今の*サーバーの環境であり、
ランが起動された環境とは限りません。層 5 が不変なのは、ランの実行モードが起動時に
固定されるためです（resume の突き合わせはダウングレードのみ）。

**B) 新規ラン**（`POST /api/v1/run-drafts/{draft_id}/resolve-config`）—
まだ存在しないランをプレビューします:

| # | 層 | `source` |
|:--:|---|---|
| 1 | pydantic のデフォルト | `default` |
| 2 | **同梱の** `config/workflow.yaml` | `workflow` |
| 3 | 選択された実行プロファイル（`--profile laptop\|hpc\|cloud`） | `profile` |
| 4 | プロジェクト設定文書 | `project` |
| 5 | ランテンプレート文書 | `template` |
| 6 | ランドラフト文書 | `draft` |
| 7 | 文書化された `ARI_*` の env オーバーライド | `env`（確信度は低） |

続いて 2 つの締めのステップ:

- **検証済み実効値** — マージされた値が `ARIConfig` として構築されます; pydantic が
  拒否する値は最後の*妥当な*層の値へ戻され、`rejected_override` の来歴エントリと
  警告が注記されます。拒否 / 無視されたオーバーライドは説明として返され、黙って
  捨てられることはありません。
- **インターロックの解決** — `ari.mode` + `rqgm.enabled` と `paper.mode` +
  `rqgm.paper.enabled` は一致していなければなりません。実行時は不一致を*警告 +
  フォールバック*（`simple_bfts` / `linear`）として解決し、マニフェストには**実効**
  モードが表示されます。ドラフト検証
  （`POST /api/v1/run-drafts/{draft_id}/validate`）はより厳格です: そこでは不一致が
  `interlock_mismatch` の**エラー**になるため、GUI は不整合な意図の起動を拒否します。

> **プロファイルのマージは 4 キーだけ、という注意点。** `--profile` はプロファイル
> YAML をディープマージ*しません*。`_apply_profile`（`ari/cli/run.py`）がマージする
> のはちょうど 4 キーです: `bfts.max_total_nodes`、`bfts.max_parallel_nodes`
> （歴史的な綴り `bfts.parallel` は `max_parallel_nodes` が無いときのみ受理）、
> `hpc.enabled` → `resources.hpc_enabled`、`hpc.scheduler` →
> `resources.scheduler`。リゾルバはこれを厳密に再現し、**無視したその他すべての
> プロファイルキー**を列挙する警告を出すので、効果の無いプロファイルのノブが不可視に
> ならず可視になります。プロファイルはチェックポイントのどこにも記録されません —
> 既存のランについては、その効果は `launch_config.json` / env を通じてしか観測でき
> ません。

その他の意図的なギャップも、黙った差異ではなく警告として提示されます:
`skills` の自動探索と `allow_web` のフェーズ書き換えは実行時のみのものです;
チェックポイントの `settings.json` はオーバーレイの層ではありません（ランへ届くのは
起動時の env 変換を通じてのみであり、それは `launch_config` と `env` の層が既に
表現しています）。

### 来歴と確信度

解決されたすべての葉が来歴エントリを持ちます:

| フィールド | 意味 |
|---|---|
| `source` | 勝った層。既存チェックポイントの語彙: `default`、`workflow`、`launch_config`、`env`、`checkpoint_state`。新規ランの語彙: `default`、`workflow`、`profile`、`project`、`template`、`draft`、`env`。 |
| `mutable` | 値をまだ変更できるかどうか。新規ランのプレビューでは `read_only` 以外のすべてのフィールドが可変です（起動前は `new_run_only` の窓も開いています）; 既存チェックポイントでは永続化されたモードが `mutable: false` です。 |
| `confidence` | ソース成果物が存在したときは `high`; 環境オーバーレイ（および再構成された層）は `low` — 起動時の環境は、読まれている環境と異なりうるためです。 |
| `rejected_override` | 新規ランのみ: ある層の値が検証で拒否され前の層の値が保たれたときの `{source, value, reason, expected}`。 |

`source_stack` は実際に参加した層を列挙します。文書化された非対称性に注意して
ください: 既存チェックポイントのスタックは常に `env` を含みます（オーバーレイは
常に評価されるため）が、新規ランのスタックは存在した層のみを列挙します。

### `resolved_config.json`（起動マニフェスト）

`POST /api/v1/runs` は、プレビューされたマニフェストを
`{ckpt}/resolved_config.json` としてチェックポイントへ実体化します —
「解決済みマニフェストが起動時に実体になる」。これは追加的であり、レガシーの表示
経路のために `launch_config.json` も引き続き書かれます。

```json
{
  "schema_version": 1,
  "resolver_version": "legacy-compatible-1",
  "run_id": "20260726T101500_matmul-9f3a12",
  "resolved_at": "2026-07-26T10:15:00Z",
  "digest": "sha256:1f0c…",
  "source_stack": ["default", "workflow", "profile", "draft"],
  "values":   { "bfts": { "max_total_nodes": 24 }, "...": "..." },
  "provenance": { "bfts.max_total_nodes": { "source": "draft", "mutable": true, "confidence": "high" } },
  "secret_references": { "llm.api_key": { "provider": "env", "configured": true } },
  "warnings": ["profile 'hpc': ignored non-merged keys …"]
}
```

知っておく価値のある規則:

- **シークレットは構造的に除外されます。** レジストリの sensitivity が
  `secret_reference` である葉は、`values`、`provenance`、ダイジェストの入力に決して
  現れません; `{provider, configured}` を持つ `secret_references` エントリとしてのみ
  提示されます — 漏れる先の値フィールドが存在しません。
- **`digest` = `values` のみの正準 JSON に対する `sha256:`**
  （`sort_keys=True`、空白なし、`ensure_ascii=False`）。シークレットは既に除外されて
  いるので、ダイジェストは redact 済み文書に対して計算され、文書化された `ARI_*`
  ファミリ外の環境ノイズがそれを動かすことはありません。同一の設定はどのマシンでも
  同一のダイジェストを生みます。
- **リゾルバの内部に時計はありません。** `resolved_at` は呼び出し側がソースファイルの
  mtime から埋めるもので、`now()` ではないため、繰り返しの GET はバイト単位で安定
  です。

### GUI 文書ストア (`gui_store/`)

GUI 専用の設定文書は、グローバルなホームディレクトリではなくチェックポイントの隣に
住みます:

```
{workspace_root}/gui_store/
├── project_config.json              # the single default project's config
├── run_templates/{template_id}.json
├── run_drafts/{draft_id}.json
└── launches/{idempotency_key}.json  # idempotent-launch records
```

| 性質 | 契約 |
|---|---|
| エンベロープ | `{"schema_version": 1, "kind": ..., "revision": n, "body": {...}}` を決定論的にシリアライズ（`sort_keys`、2 スペースインデント、末尾改行）。 |
| `revision` | 文書ごとの整数で 1 から始まり、書き込みごとに増加します; HTTP API の `If-Match` トークンです（`0` は「まだ存在してはならない」の意味）。 |
| 耐久性 | 同一ディレクトリの一時ファイル + `fsync` + `os.replace`（+ ベストエフォートのディレクトリ fsync）: 書き込み途中のクラッシュでも直前の文書はバイト単位で無傷です。 |
| 権限 | ファイル `0o600`、ストアのディレクトリ `0o700`。 |
| ID | 呼び出し側が与え、`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` に対して検証されます — `/` も `.` も無いので、パストラバーサルは構造的に不可能です。ドラフト id はサーバーが生成します（`draft-<12 hex>`）。 |
| ルート | `RuntimePathResolver.resolve_workspace_root()` — すべてのワークスペース消費側が使うのと同じポリシー（`ARI_CHECKPOINT_DIR` が勝ちます）。 |

**CLI が `gui_store/` を読むことは決してありません。** これは GUI の便宜層です:
テンプレートはそれが生んだランより長生きし、起動はすべての実効値を従来どおり
チェックポイントへ実体化します。`ari.viz.v1` の外にある `ari/` のどのコードも
このストアをインポートしません。

### レガシー Settings のキー: 実際に配線されているもの

レガシーの `GET/POST /api/settings` 面は、癖も含めて凍結されています（正確な
キー集合・デフォルト値・保存パスの挙動は
`ari-core/tests/test_gui_baseline_settings_contract.py` がピン留めしています）。
以下はすべて**実測された凍結挙動**です。テストが依存しており運用者がつまずく
ので記録していますが、真似すべき設計ではありません。Settings ページを読むときに
効いてくる点が 6 つあります:

**1. GET と POST のキー集合が一致していません。** `GET /api/settings` はちょうど
**27** のトップレベルキーを返します（26 のスカラ / リスト + 10 のサブキーを持つ
ネストした `ors` オブジェクト）; Save ボタンはちょうど **24** のフラットなキーを
POST し、`POST` は*ファイル全体の置換*です（ボディに無いキーは `settings.json` から
消えます）。共有されるキーは 16 です:

| POST ボディのみ (8) | GET レスポンスのみ (11) |
|---|---|
| `llm_backend`、`llm_base_url`、`ssh_host`、`ssh_port`、`ssh_user`、`ssh_path`、`ssh_key`、`slurm_partitions` | `llm_provider`、`ollama_host`、`mcp_skills`、`slurm_gpus`、`vlm_review_enabled`、`vlm_review_max_iter`、`vlm_review_threshold`、`letta_deployment`、`letta_deployment_image`、`letta_deployment_venv`、`ors` |

帰結: プロバイダは `llm_backend` として書かれ `llm_provider` として読み戻されます。
これが、保存値が falsy のときに GET のマージが `llm_provider`（および `llm_model`）を
`workflow.yaml` から強制し直す理由 — いわゆる「falsy 再強制の癖」です。

**2. 一部のキーは装飾です。** 永続化され描画されますが、どの実行時もそれを読みません:

| Settings のキー | 状態 | 詳細 |
|---|---|---|
| `temperature` | **死んでいる** | 起動環境へエクスポートされず `ARI_*` フックも存在しません; ランは pydantic の `llm.temperature` デフォルトのままです。（正準の設定 API は `llm.temperature` の葉を*適用します* — 2 つの経路がここで異なるのは凍結の設計によるものです。） |
| `container_pull` | **両経路で死んでいる** | env へエクスポートされず、正準の設定葉も存在しません。 |
| `retrieval_backend` | **`workflow.yaml` では装飾** | 値は起動時に `ARI_RETRIEVAL_BACKEND` としてエクスポート*されます*が、`retrieval` は型付き葉を持たないトップレベルの未型付けワークフローキーです — レジストリはそれを先行宣言するだけです。 |
| `slurm_partition` / `slurm_cpus` / `slurm_memory_gb` / `slurm_walltime` | **シードのみ** | SLURM カードの値は起動環境へ届きません。`slurm_cpus` / `slurm_memory_gb` / `slurm_walltime` はウィザードの HPC ステップを事前入力します; 実際に使われるのはウィザード自身の値です。 |
| `slurm_partitions` | **UI ローカル** | Settings ページのマルチセレクトの状態です; ウィザードのパーティション一覧は `GET /api/slurm/partitions` の検出から来ます。 |
| `container_mode` / `container_image` / `vlm_review_model` / `letta_*` | **env のみ** | `ARI_CONTAINER_MODE` / `ARI_CONTAINER_IMAGE` / `VLM_MODEL` / `LETTA_*` としてエクスポートされますが、対応するワークフローブロックは未型付けの `extra="allow"` セクションなので、フィールドレジストリにはまだ型付き葉がありません。 |
| `letta_api_key` | **凍結された欠陥** | `settings.json` へ平文のまま永続化されます。正準の設定 API は `values` 内のシークレットを拒否します; 代わりに `PUT /api/v1/secrets/{secret_id}` を使ってください。 |

**3. 凍結されているのはキー名だけでなくデフォルト*値*もです。**
`_api_get_settings`（`ari/viz/api_settings.py`）はリテラルの `defaults` dict を
1 つ組み立てており、`test_frozen_default_values` がその中身をピン留めしています。
これらは「何も再導出しないピン留めされたリテラル」として読んでください —
チューニング済みの推奨値ではなく、これを見て何かを決める実行時も存在しません。

トップレベル 20 スロットと `ors` サブキー 5 つは純粋な定数です:

| キー | 凍結値 |
|---|---|
| `llm_api_key` | `""` |
| `semantic_scholar_key` | `""` |
| `temperature` | `1.0` |
| `slurm_partition` | `""` |
| `slurm_cpus` | `null` |
| `slurm_memory_gb` | `null` |
| `slurm_gpus` | `0` |
| `slurm_walltime` | `"04:00:00"` |
| `mcp_skills` | `[]` |
| `container_mode` | `"auto"` |
| `container_image` | `""` |
| `container_pull` | `"on_start"` |
| `vlm_review_enabled` | `true` |
| `vlm_review_model` | `"openai/gpt-4o"` |
| `vlm_review_max_iter` | `3` |
| `vlm_review_threshold` | `0.7` |
| `letta_deployment` | `"auto"` |
| `letta_deployment_image` | `""` |
| `letta_deployment_venv` | `""` |
| `letta_api_key` | `""` |
| `ors.rubric_gen_temperature` | `0.0` |
| `ors.rubric_gen_target_leaves` | `0` |
| `ors.rubric_gen_two_stage` | `true` |
| `ors.judge_n_runs` | `3` |
| `ors.phase1_max_runtime_sec` | `21600` |

残るトップレベル 6 スロットと `ors` サブキー 5 つは**環境変数が先**であり、
凍結されているのはフォールバックだけです。定数として引用しないでください:

| キー | 先に読む変数 | その変数が未設定のときの値 |
|---|---|---|
| `ollama_host` | `OLLAMA_HOST` | `"http://localhost:11434"` |
| `retrieval_backend` | `ARI_RETRIEVAL_BACKEND` | `"semantic_scholar"` |
| `letta_base_url` | `LETTA_BASE_URL` | `"http://localhost:8283"` |
| `letta_embedding_config` | `LETTA_EMBEDDING_CONFIG` | `"letta-default"` |
| `ors.replicator_model` | `ARI_MODEL_REPLICATE` | `"claude-opus-4-7"` |
| `ors.rubric_gen_model` | `ARI_MODEL_RUBRIC_GEN` | `"gemini-2.5-pro"` |
| `ors.rubric_audit_model` | `ARI_MODEL_RUBRIC_AUDIT` | `"claude-opus-4-7"` |
| `ors.judge_model` | `ARI_MODEL_JUDGE` | `"gpt-4o-2024-11-20"` |
| `ors.phase1_sandbox_kind` | `ARI_PHASE1_SANDBOX` | `"auto"` |
| `llm_model` | `ARI_LLM_MODEL` | パッケージ同梱 `workflow.yaml` の `llm.model`、無ければ `""` |
| `llm_provider` | `ARI_BACKEND` | パッケージ同梱 `workflow.yaml` の `llm.backend`、無ければ `""` |

表に載せられない細部が 2 つあります。`os.environ.get(VAR, リテラル)` 形式の
9 スロットは変数が**存在しない**ときにのみフォールバックします — 空文字列に
設定された変数は `""` を返し、リテラルにはなりません。`llm_model` /
`llm_provider` は `os.environ.get(VAR, "") or …` なので、この 2 つだけは空でも
フォールバックします。契約テストが凍結リテラルを観測できるのは、`_clean_env`
フィクスチャが 11 個の変数を先に削除しているからにすぎません。開発者のシェル上
ではペイロードは違うものになります。

**4. `api_key` は `settings.json` に到達しません — `.env` ファイルと稼働中の
サーバプロセスに書かれます。** `POST /api/settings` はボディから `api_key`
（次に `llm_api_key`）を pop し、さらに両方を無条件で pop し直すので、どちらも
永続化されることはありません。値が下記 5 の妥当性ガードを通過し、*かつ*
プロバイダが環境変数名にマップされる場合にのみ
`_upsert_env_key(name, key, quote=False)` が走ります。このヘルパは:

- 対象ファイルの中で strip 後に `NAME=` で始まる行を**すべて**書き換え、
  1 つも無ければ行を追加します。（ヘルパ自身の docstring は「最初の行」と
  書いていますが、ループに早期脱出は無いので、`NAME` の重複エントリを既に
  含むファイルではそのすべてが書き換わります。）;
- アトミックに書きます — 同一ディレクトリの `mkstemp`、`fchmod 0o600`、
  `fsync`、`os.replace`、最後にベストエフォートの `chmod 0o600`;
- **引用符なし**の `NAME=value` 形式で描画します。`NAME="value"`
  （`quote=True`）を書くのは env キーエディタと
  `PUT /api/v1/secrets/{secret_id}` で、同じヘルパを通ります。ヘルパの
  docstring には、2 つの呼び出し元は歴史的にこの引用符だけが違っており、
  統一することは挙動変更にあたる、と記録されています;
- そして最後に**稼働中のサーバプロセス**で `os.environ[name] = value` を
  設定します。設定の保存はファイルだけでなくライブの環境も書き換えます。

書き込み先はモジュールグローバルの `ari.viz.state._env_write_path` で、import
時に ARI リポジトリルートの `.env` に一度だけ束縛されます。
`set_active_checkpoint` が再束縛するのは `_checkpoint_dir` と `_settings_path`
だけで `_env_write_path` は触らず、`ari/` 配下にこれを再代入するコードは
ありません — つまりこれは選択中の checkpoint の `.env` ではなく**リポジトリ
ルート**の `.env` です。（契約テストが checkpoint ローカルの `.env` を書くように
見えるのは、フィクスチャがこのグローバルを monkeypatch しているからです。）
正準ルートも同じファイルに到達します:
[Configuration Studio](../guides/configuration_studio.md) の
*シークレットの扱い* を参照してください。

**5. 癖 — API キーが黙って捨てられる 3 つの経路。** `.env` 分岐全体が
`if _raw_key and "test" not in _raw_key and len(_raw_key) >= 20:` という 1 行の
条件にぶら下がっており、その後にインライン dict でのプロバイダ検索が続きます。
`else` 分岐もログ行もレスポンス上のフィールドも存在しないため、以下のいずれの
ケースでも書き込みは丸ごとスキップされ、アクティブな checkpoint があれば
ハンドラはそのまま `{"ok": true}` を返します。運用者には保存成功と伝えつつ、
資格情報は捨てられています。

| 捨てられる条件 | 詳細 |
|---|---|
| キーが 20 文字未満 | `20` は条件式に直書きされたマジックナンバーです — 名前付き定数も設定ノブもメッセージもありません。 |
| キーのどこかに `test` が含まれる | キー全体に対する大文字小文字を区別する部分文字列判定で、長さチェックより先に評価されます。たまたまその 4 文字を含む本物の資格情報は、プレースホルダとまったく同じように捨てられます。一方 `TEST` はマッチしません。 |
| プロバイダがマップに無い | マップは `openai` → `OPENAI_API_KEY`、`anthropic` / `claude_code` / `claude-code` → `ANTHROPIC_API_KEY`、`gemini` → `GOOGLE_API_KEY` です。5 つの綴りで 3 つの変数。`.get(provider, "")` はそれ以外（`ollama`、vLLM、その他すべての OpenAI 互換 `base_url` バックエンド）に対して `""` を返し、書き込みはスキップされます。 |

これら 3 つはテストがピン留めしている長さと部分文字列のヒューリスティクスです。
バリデーションでもシークレット検出でもないので、そのように説明しないで
ください。さらにこのマップがこのルートの到達範囲そのものです:
`GEMINI_API_KEY`、`SEMANTIC_SCHOLAR_API_KEY`、`LETTA_API_KEY`、`ZENODO_TOKEN`、
`ARI_REGISTRY_TOKEN` はいずれも v1 シークレット許可リスト
（`ari/viz/v1/secrets.py`）にありますが、ここからは 1 つも到達できません。

癖 1 の帰結がこの経路に効いてきます。プロバイダ名は
`data.get("llm_provider", "") or data.get("llm_backend", "")` として読まれ、
フロントエンドの 24 キーの Save ボディには `llm_backend` があって
`llm_provider` はありません — つまり実際の Settings ページからの保存はすべて
*フォールバック*側の腕でプロバイダを解決しています。GUI からキーを設定できる
のはこのフォールバックのおかげであり、両キーが無いか falsy ならプロバイダは
`""` となり、`""` にマップされてキーは捨てられます。

**6. 癖 — 拒否された保存は no-op ではありません。** `_api_save_settings` の
実行順は、ボディのパース → `retrieval_backend` ガード → API キーの pop と
`.env` upsert → アクティブ checkpoint チェック → `settings.json` 書き込み、
です。したがって 2 つの拒否は残すものが違います:

| 拒否（どちらも `_status` 400） | 副作用 |
|---|---|
| `{"ok": false, "error": "retrieval_backend must select one pinned provider"}` — ボディに `semantic_scholar`、`arxiv`、`alphaxiv` のいずれでもない `retrieval_backend` が含まれている（キー自体が無い場合は通過します） | ありません。キーを読む前に return します。 |
| `{"ok": false, "error": "No active project. Create or select a checkpoint before saving settings."}` — `state._settings_path` が `None` | キーは**すでに** `.env` に書かれ `os.environ` にエクスポート済みです。`_env_write_path` は `_settings_path` とは別の状態なので、checkpoint 未選択でも書き込み可能なままです。 |

覚えておくべきは 2 行目です。このエンドポイントの 400 は「何も起きなかった」を
意味しません — どちらにせよシークレットはディスク上とプロセス内にあります。
現状のまま凍結されており、ハンドラの順序変更は挙動変更にあたります。

24 の POST キー、レガシー起動時の env エクスポート、正準の設定葉の三者の重なり —
上記のすべての乖離を含めて — は
`ari-core/tests/test_gui_config_shadow_legacy.py` が逐語的に表明しています。

## workflow.yaml（正規の開発者設定）

`workflow.yaml` は ARI パイプライン全体の**唯一の信頼できる情報源**です。
`ari-core/config/workflow.yaml` に配置してください。

skill パスには `{{ari_root}}` を使用してください — これは `$ARI_ROOT` 環境変数またはプロジェクトルートに解決されます。

```yaml
llm:
  backend: openai          # ollama | openai | anthropic
  model: gpt-5.2           # モデル識別子
  base_url: ""             # OpenAI の場合は空、Ollama/vLLM の場合は設定

author_name: "Autonomous Research Infrastructure"

resources:
  cpus: 48                 # 再現性実験のデフォルト CPU 数
  timeout_minutes: 60      # デフォルトのジョブタイムアウト
  executor: slurm          # ジョブエグゼキュータ: slurm / local / pbs / lsf

# BFTS フェーズステージ（ツリー探索中に順次実行）
bfts_pipeline:
  - stage: generate_idea
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
  - stage: select_and_run
    skill: hpc-skill
    phase: bfts
  - stage: evaluate
    skill: evaluator-skill
    tool: ''                   # 表示専用の行: 評価は MCP ツールではなく
                               # ari-core のインプロセス LLMEvaluator が担当
    phase: bfts
  - stage: frontier_expand
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
    loop_back_to: select_and_run

# Post-BFTS パイプラインステージ
pipeline:
  - stage: search_related_work
    skill: web-skill
    tool: search_papers
    params:
      provider: semantic-scholar
      max_results: 15
      mode: record
    skip_if_exists: '{{ckpt}}/related_refs.json'
    # ...
  - stage: transform_data
    skill: transform-skill
    tool: nodes_to_science_data
    inputs:
      nodes_json_path: '{{ckpt}}/nodes_tree.json'
      llm_model: '{{llm.model}}'
      llm_base_url: '{{llm.base_url}}'
    outputs:
      file: '{{ckpt}}/science_data.json'
    skip_if_exists: '{{ckpt}}/science_data.json'
  - stage: generate_figures
    skill: plot-skill
    tool: generate_figures_llm
    depends_on: [transform_data]
    # ...
  - stage: write_paper
    skill: paper-skill
    tool: write_paper_iterative
    depends_on: [search_related_work, generate_figures]
    # ...
  - stage: review_paper
    skill: paper-skill
    tool: review_compiled_paper
    depends_on: [write_paper]
    # ...
  # ─── EAR キュレーション/公開/最終化 (v0.7.0) ───
  - stage: ear_curate
    skill: transform-skill
    tool: curate_ear
    depends_on: [generate_ear]
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'
    outputs:
      file: '{{checkpoint_dir}}/ear_curate.status.json'
  - stage: finalize_paper
    skill: paper-skill
    tool: inject_code_availability
    depends_on: [write_paper, ear_curate]
    # ear_published/manifest.lock と publish_record.json から ref/sha/doi
    # を自動ロードし、\codeavailability/\codedigest/\coderef マクロを
    # full_paper.tex に注入。バンドル無しなら静かにスキップ。
  - stage: ear_publish
    skill: transform-skill
    tool: publish_ear
    depends_on: [ear_curate]
    enabled: false           # opt-in。true にするか publish=true を渡す
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'
      backend: ari-registry
      visibility: staged
      dry_run: false
    outputs:
      file: '{{checkpoint_dir}}/publish_record.json'
  - stage: merge_reviews
    skill: paper-skill
    tool: merge_reviews
    depends_on: [review_paper, vlm_review_figures]
    # text + VLM 査読出力の構造合成 (LLM 不使用)。

  # ─── ORS オートルーブリック再現性 (PaperBench, v0.7.0) ───
  # 旧 `reproducibility_check` を置き換える。
  # node 成果物を記録済み sha256 と突合してから論文の証拠に昇格させる。
  # {{run_id}}/{{experiments_root}} は driver が checkpoint_dir から解決する
  # (tree.json がディレクトリ名より優先)。
  - stage: audit_node_provenance
    skill: memory-skill
    tool: audit_memory
    depends_on: []
    inputs:
      experiments_root: '{{experiments_root}}'
      run_id: '{{run_id}}'
  - stage: ors_generate_rubric
    skill: replicate-skill
    tool: generate_rubric
    depends_on: [write_paper]
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      output_path: '{{checkpoint_dir}}/ors_rubric.json'
      target_leaf_count: 0     # 0 = 論文長から自動算定
  - stage: ors_audit_rubric    # 採点が依拠するルーブリック自体の品質監査
    skill: replicate-skill
    tool: audit_rubric
    depends_on: [ors_generate_rubric]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'   # フラグを付けてその場で書き換え
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
  - stage: ear_publish          # v0.7.0+: デフォルト有効、local-tarball
    skill: transform-skill
    tool: publish_ear
    depends_on: [ear_curate]
    enabled: true
    inputs:
      backend: local-tarball    # 依存ゼロ。チェックポイント横に bundle.tar.gz
      visibility: staged
  - stage: ors_seed_sandbox     # v0.7.0+: EAR バンドルから決定論的に種をまく
    skill: paper-re-skill
    tool: fetch_code_bundle
    depends_on: [ear_publish]
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'    # publish_record.json から ref 自動読込
      dest: '{{checkpoint_dir}}/repro_sandbox'
  - stage: ors_build_reproduce  # v0.7.0+: LLM フォールバック (上で seed 済なら skip)
    skill: paper-re-skill
    tool: build_reproduce_sh
    depends_on: [ors_audit_rubric, ors_seed_sandbox, finalize_paper]
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      output_dir: '{{checkpoint_dir}}/repro_sandbox'
      overwrite: false
  - stage: ors_run_reproduce
    skill: paper-re-skill
    tool: run_reproduce        # Phase 1 (reproduce.sh をサンドボックス実行)
    depends_on: [ors_audit_rubric, ors_build_reproduce]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      repo_dir: '{{checkpoint_dir}}/repro_sandbox'
      sandbox_kind: ''         # auto: slurm → docker → apptainer → singularity → local
      timeout_global_sec: 0    # 0 = rubric.reproduce_contract.max_runtime_sec
      partition: ''            # 空 → ARI_SLURM_PARTITION → launch_config.json
      cpus: 0                  # 空 → ARI_SLURM_CPUS (default 8)
      walltime: ''             # 空 → ARI_SLURM_WALLTIME → timeout から算出
  - stage: ors_grade
    skill: paper-re-skill
    tool: grade_with_simplejudge   # Phase 2 (PaperBench SimpleJudge via LiteLLM)
    depends_on: [ors_run_reproduce]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      repo_dir: '{{checkpoint_dir}}/repro_sandbox'
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      n_runs: 3
      judge_model: gpt-5-mini  # LiteLLM 認識可能な任意のモデル ID

retrieval:
  backend: semantic_scholar    # semantic_scholar | alphaxiv | both
  alphaxiv_endpoint: https://api.alphaxiv.org/mcp/v1

# ── 論文査読 (ルーブリック駆動、AI Scientist v1/v2 互換) ─────────────
# CLI フラグ (--rubric、--fewshot-mode、--num-reviews-ensemble、
# --num-reflections) または環境変数 (ARI_RUBRIC、ARI_FEWSHOT_MODE、
# ARI_NUM_REVIEWS_ENSEMBLE、ARI_NUM_REFLECTIONS) で上書き可能。
# ari-core/config/reviewer_rubrics/ に同梱されている 23 個の YAML ルーブリック:
#   neurips (既定、v2 互換) | iclr | icml | cvpr | acl | sc | osdi
#   | usenix_security | stoc | siggraph | chi | icra | nature
#   | journal_generic | workshop | generic_conference
#   | aer | ahr | apsr | econometrica | philreview | pmla | qje
# 加えて内蔵の `legacy` フォールバック (v0.5 スキーマ)。新しい venue は
# <id>.yaml を reviewer_rubrics/ に追加するだけで対応 (コード変更不要)。
#
# Few-shot コーパス管理
# --------------------
# reviewer_rubrics/fewshot_examples/<rubric>/ 配下のファイルは GUI
# (New Experiment Wizard → Paper Review → Few-shot サンプル) または
# scripts/fewshot/sync.py から管理できます。viz サーバが公開する REST:
#   GET  /api/rubrics                           rubric 一覧 (Wizard 用)
#   GET  /api/fewshot/<rubric>                  fewshot 例の一覧
#   POST /api/fewshot/<rubric>/sync             manifest.yaml から取得
#   POST /api/fewshot/<rubric>/upload           1 件アップロード
#   POST /api/fewshot/<rubric>/<example>/delete 1 件削除

memory:
  # v0.6.0: Letta が唯一の本番バックエンドです。ここでの値はスキル
  # 子プロセスの環境変数として読み込み時に注入されます。エージェント
  # 用チャット LLM は `letta/letta-free` に固定されています
  # (ari-skill-memory は archival_insert / archival_search だけを
  # 呼び、チャットメッセージは送らないためピッカーは無効でした)。
  backend: letta
  letta:
    base_url: http://localhost:8283
    collection_prefix: ari_
    embedding_config: letta-default

container:
  mode: auto                   # auto | docker | singularity | apptainer | none
  image: ""                    # コンテナイメージ名（空 = コンテナ未使用）
  pull: on_start               # always | on_start | never

skills:
  # `phase` は ReAct エージェントがどの pipeline-phase でそのスキルの
  # MCP ツールを見られるかを制御します。単一文字列なら一つの phase
  # のみ、配列なら複数の phase にオプトインします。`reproduce` に
  # タグ付けされたスキルは再現性 ReAct (上の reproducibility_check
  # ステージ参照) に露出します。`memory-skill` / `transform-skill` /
  # `evaluator-skill` はエージェントが BFTS フェーズの成果物に
  # 到達できないよう、意図的に reproduce から除外しています。
  - name: web-skill
    path: "{{ari_root}}/ari-skill-web"
    phase: [paper, reproduce]
  - name: plot-skill
    path: "{{ari_root}}/ari-skill-plot"
    phase: paper
  - name: paper-skill
    path: "{{ari_root}}/ari-skill-paper"
    phase: paper
  - name: paper-re-skill
    path: "{{ari_root}}/ari-skill-paper-re"
    phase: paper
  - name: memory-skill
    path: "{{ari_root}}/ari-skill-memory"
    phase: bfts
  - name: evaluator-skill
    path: "{{ari_root}}/ari-skill-evaluator"
    phase: bfts
  - name: idea-skill
    path: "{{ari_root}}/ari-skill-idea"
    phase: bfts
  - name: hpc-skill
    path: "{{ari_root}}/ari-skill-hpc"
    phase: [bfts, reproduce]
  - name: coding-skill
    path: "{{ari_root}}/ari-skill-coding"
    phase: [bfts, reproduce]
  - name: transform-skill
    path: "{{ari_root}}/ari-skill-transform"
    phase: paper
  - name: benchmark-skill
    path: "{{ari_root}}/ari-skill-benchmark"
    phase: bfts
  - name: vlm-skill
    path: "{{ari_root}}/ari-skill-vlm"
    phase: [paper, reproduce]
  # v0.7.0: PaperBench 形式オートルーブリック生成器・監査器
  - name: replicate-skill
    path: "{{ari_root}}/ari-skill-replicate"
    phase: paper
```

## 環境変数

| 変数 | 説明 | デフォルト |
|----------|-------------|---------|
| `ARI_MAX_NODES` | BFTS で探索するノードの最大数 | `50` |
| `ARI_PARALLEL` | 同時実行ノード数 | `1` |
| `ARI_EXECUTOR` | 実行バックエンド: `local`, `slurm`, `pbs`, `lsf` | `local` |
| `ARI_SLURM_PARTITION` | SLURM パーティション名 | (なし) |
| `ARI_SLURM_CPUS` | SLURM ジョブの CPU 数オーバーライド | (自動検出) |
| `SLURM_LOG_DIR` | SLURM 出力ファイルの保存先 | (なし) |
| `OLLAMA_HOST` | Ollama サーバーアドレス | `127.0.0.1:11434` |
| `OPENAI_API_KEY` | OpenAI API キー | (なし) |
| `ANTHROPIC_API_KEY` | Anthropic API キー | (なし) |
| `ARI_RETRIEVAL_BACKEND` | 論文検索バックエンド: `semantic_scholar` / `alphaxiv` / `both` | `semantic_scholar` |
| `VLM_MODEL` | 図レビュー用 VLM モデル | `openai/gpt-4o` |
| `ARI_ORCHESTRATOR_PORT` | orchestrator スキルの HTTP ポート | `9890` |
| `LETTA_BASE_URL` | Letta サーバエンドポイント | `http://localhost:8283` |
| `LETTA_API_KEY` | Letta Cloud で必須 | (なし) |
| `LETTA_EMBEDDING_CONFIG` | アーカイバルメモリ用の埋め込みハンドル（エージェントのチャット LLM は ARI から呼び出さないため `letta/letta-free` に固定） | `letta-default` |
| `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA` | `auto` / `pip` / `docker` / `singularity` / `none` | `auto` |
| `ARI_MEMORY_LETTA_TIMEOUT_S` | 呼び出しごとのタイムアウト | `10` |
| `ARI_MEMORY_LETTA_OVERFETCH` | 祖先ポストフィルタ用のオーバーフェッチ K | `200` |
| `ARI_MEMORY_LETTA_DISABLE_SELF_EDIT` | Letta self-edit を無効化 (CoW セーフ) | `true` |
| `ARI_MEMORY_ACCESS_LOG` | `{checkpoint}/memory_access.jsonl` を有効化 | `on` |
| `ARI_MEMORY_AUTO_RESTORE` | `ari resume` 時にバックアップを自動復元 | `true` |
| `ARI_RUBRIC` | BFTS の動的軸評価器 (Phase 3) と lineage 判定しきい値が読む rubric_id (例: `neurips`、`sc`、`nature`)。論文査読はこれを読まず、`review_paper` は `workflow.yaml` のトップレベル `paper_rubric` から明示的な `rubric_id` を受け取る (`resolve_rubric` は空の id を環境変数へフォールバックせず拒否) | `neurips` |
| `ARI_FEWSHOT_MODE` | `static` / `dynamic` | `static` |
| `ARI_NUM_REVIEWS_ENSEMBLE` | 独立査読者数 | `1` |
| `ARI_NUM_REFLECTIONS` | self-reflection ループ回数 | `5` |
| `ARI_MODEL_RUBRIC_GEN` | `replicate-skill.generate_rubric` の生成 LLM (v0.7.0) | `gemini/gemini-2.5-pro` |
| `ARI_MODEL_RUBRIC_AUDIT` | `audit_rubric` の監査 LLM (生成器とは独立) | `anthropic/claude-opus-4-7` |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | `generate_rubric` の目標葉数の上書き。`0` / 未設定で論文長から自動 (~1葉/75語、[50,400] にクランプ)。GUI Wizard の "Target leaves" 欄。 | (未設定) |
| `ARI_RUBRIC_GEN_TEMPERATURE` | 生成器 temperature の上書き。GUI Wizard の "Temperature" 欄。 | (未設定) |
| `ARI_RUBRIC_GEN_TWO_STAGE` | 二段階生成（スケルトン + 並列サブツリー）の強制 ON/OFF (`1`/`true`/`on` vs `0`/`false`/`off`)。単一コール比で葉数約 4 倍・深さ +1〜2 層、API トークン消費約 5 倍。未設定時は kwarg デフォルト（現状 ON）。GUI Wizard の "二段階生成" トグル。 | (未設定、既定 ON) |
| `ARI_MODEL_REPLICATE` | `build_reproduce_sh` (論文 → reproduce.sh, v0.7.0) のリプリケータ LLM | `claude-opus-4-7` |
| `ARI_MODEL_JUDGE` | `grade_with_simplejudge` (PaperBench Phase 2, v0.7.0; LiteLLM 経由でプロバイダ自由) の判定 LLM | `gpt-5-mini` |
| `ARI_MODEL_LINEAGE` | `decide_lineage_action` の判定 LLM (lineage decision, v0.7.0)。未指定時は `ARI_MODEL_EVAL` → `ARI_MODEL` → `ARI_LLM_MODEL` → `gpt-4o-mini` の順にフォールバック | (auto) |
| `ARI_MODEL_ROOT_SELECT` | VirSci プールから `ideas[0]` を選び直す LLM (lineage decision, v0.7.0)。フォールバック順は `ARI_MODEL_LINEAGE` と同じ | (auto) |
| `ARI_PHASE1_SANDBOX` | Phase 1 サンドボックス: `auto` / `slurm` / `docker` / `apptainer` / `singularity` / `local` | `auto` |
| `ARI_SLURM_WALLTIME` | SLURM Phase 1 の `--time` HH:MM:SS (v0.7.0, 復元)。空ならルーブリックの `max_runtime_sec` から算出。 | (auto) |
| `ARI_PHASE1_DOCKER_IMAGE` | docker サンドボックスのコンテナイメージ | `ubuntu:24.04` |
| `ARI_PHASE1_APPTAINER_IMAGE` / `ARI_PHASE1_SINGULARITY_IMAGE` | Apptainer/Singularity サンドボックスのイメージ | `docker://ubuntu:24.04` |
| `ARI_PUBLISH_DRYRUN` | `ari ear publish --dry-run` を強制 (CI 安全, v0.7.0) | (off) |
| `ARI_REGISTRY_DATA` | `ari registry serve` の sqlite + artifact 保管 root | (なし — 明示設定が必須。v0.5.0 以前の `$HOME/.ari/registry-data` フォールバックは DeprecationWarning を出し、v1.0 で削除) |
| `ARI_REGISTRY_TOKEN` | `ari clone ari://...` / `ari ear publish --backend ari-registry` 用 bearer token | (なし) |
| `ARI_REPRO_CLONE_POLICY` | 再現性サンドボックス git shim ポリシー: `passthrough` / `deny` / `warn` | `passthrough` |

## メモリバックエンド (Letta)

v0.6.0 で決定論的 JSONL メモリストアを [Letta](https://docs.letta.com)
へ置き換えました。Letta は次の 4 通りで動作します:

| モード | 要件 | ストア | 備考 |
|------|------|--------|------|
| Docker Compose | `docker` + `docker compose` | Postgres | ノートPC既定、pre-filter 対応 |
| Singularity / Apptainer | `singularity` / `apptainer` | Postgres | HPC 既定、SLURM 認識のデータ DIR |
| pip (コンテナレス) | Python 3.10+ | SQLite | ancestor スコープは over-fetch + post-filter にフォールバック |
| Letta Cloud | API キー | マネージド | `LETTA_BASE_URL=https://api.letta.com` |

`ari setup` が最適なモードを自動検出します。`ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA`
で強制指定も可能。start/stop/health/backup/restore は `ari memory` サブ
コマンドが扱います — 詳細は `docs/ja/reference/cli_reference.md` を参照。

v0.5.x チェックポイントのワンショット移行:

```bash
ari memory migrate --checkpoint /path/to/ckpt --react
```

## LLM バックエンド

### Ollama（ローカル、オフライン HPC に推奨）

```yaml
llm:
  backend: ollama
  model: qwen3:32b
  base_url: http://127.0.0.1:11434
```

### OpenAI

```yaml
llm:
  backend: openai
  model: gpt-4o
```

### Anthropic

```yaml
llm:
  backend: anthropic
  model: claude-sonnet-4-5
```

### Claude Code（claude_code）

ローカルの Claude Code をステートレスな LLM API として利用する
（ツール・MCP・メモリ・セッション再利用は一切なし）。詳細:
[claude_code_provider.md](./claude_code_provider.md)。

```yaml
llm:
  backend: claude_code
  model: claude-sonnet-5
  claude_code:
    mode: strict_reproducibility   # または low_overhead（Agent SDK ワーカー）
    max_turns: 1
    timeout_sec: 300
    record_provenance: true
    # bare: true                   # 既定は auto: ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN があるときのみ true
    # structured_output_transport: prompt   # または native（--json-schema）
```

環境変数オーバーライド: `ARI_CLAUDE_CODE_MODE`、`ARI_CLAUDE_CODE_MODEL`、
`ARI_CLAUDE_CODE_MAX_TURNS`、`ARI_CLAUDE_CODE_TIMEOUT_SEC`、
`ARI_CLAUDE_CODE_RECORD_PROVENANCE`、`ARI_CLAUDE_CODE_BIN`。ヘルスチェック:
`ari doctor claude-code [--live]`。注意: このバックエンドでも MCP スキルは
Claude Code を経由しない — スキルの直接 litellm 呼び出しは素の Anthropic API
（`ANTHROPIC_API_KEY` が必要）にルーティングされる。また ReAct エージェント
フェーズにはツール呼び出し可能なバックエンドが必要（`tools=` を渡すと
fail-loud）。

### 任意の OpenAI 互換 API（vLLM、LM Studio など）

```yaml
llm:
  backend: openai
  model: your-model-name
  base_url: http://your-server:8000/v1
```

---

## workflow.yaml のテンプレート変数

`inputs:` 内の任意の値で `{{variable}}` 置換がサポートされています:

| 変数 | 値 |
|----------|-------|
| `{{ckpt}}` | チェックポイントディレクトリのパス |
| `{{checkpoint_dir}}` | `{{ckpt}}` と同じ値（両方束縛済み。多くのステージはこちらの綴りを使う） |
| `{{run_id}}` | 実行 ID。`{checkpoint_dir}/tree.json` があればそこから読み、無ければディレクトリ名。`ari resume` は改名先へ `checkpoint.dir` を張り替えるため、両者は食い違いうる |
| `{{experiments_root}}` | `{workspace_root}/experiments` — ノード作業ツリー。`checkpoints/` の兄弟であり `ari.paths.PathManager` が解決する。ノードディレクトリは `{{experiments_root}}/{{run_id}}/<node_id>/` |
| `{{ari_root}}` | ARI プロジェクトルート（`$ARI_ROOT` または自動検出） |
| `{{llm.model}}` | `llm:` セクションの LLM モデル名 |
| `{{llm.base_url}}` | `llm:` セクションの LLM ベース URL |
| `{{resources.cpus}}` | `resources:` セクションの CPU 数 |
| `{{resources.timeout_minutes}}` | `resources:` セクションのタイムアウト |
| `{{stages.<name>.outputs.file}}` | 完了したステージの出力ファイルパス |
| `{{author_name}}` | トップレベル設定の著者名 |
| `{{vlm_feedback}}` | VLM レビューフィードバック（`vlm_review_figures` からのループバック時に注入） |
| `{{paper_context}}` | 科学的に整形された実験サマリ |
| `{{keywords}}` | LLM 生成検索キーワード |

---

## skip_if_exists バリデーション

`skip_if_exists` が指定されたステージは、出力ファイルが以下の場合に**再実行**されます:
- 存在しない
- 空である
- トップレベルに `"error"` キーを含む JSON ファイルである

これにより、壊れた出力が下流のステージを暗黙的にブロックすることを防止します。

---

## Plan Promote (v0.7.0+)

`plan_promote` は VirSci の experiment plan を **チェックポイント内**の
`experiment.md` にどう展開するかを制御します。CLI で渡したユーザの
ソース `experiment.md` は **改変されません** — チェックポイント側のコピー
にだけ HTML コメントマーカで囲んだ自動追記ブロックが付きます (再実行で
重複しない idempotent)。

```yaml
plan_promote: index_only          # full | index_only | off
```

| Mode | 追加内容 | 典型サイズ |
|---|---|---|
| `full` | 選定 idea + plan §タグ本文 + Alternatives | ~5 KB |
| `index_only` (default) | 選定 idea + plan §タグタイトル + Alternatives | ~1.5 KB |
| `off` | (追記なし) | 0 |

Phase 3 の評価器と BFTS expand idea_ctx は **idea.json の生 plan** を読むので、
`full` か `index_only` かは主に **人間と paper-skill が experiment.md で何を
読むか** だけの違いです。

## Lineage Decision (v0.7.0+)

BFTS が停滞したとき、LLM judge が「探索継続 / 代替案へ切替 / 並列展開 /
終了」のいずれかを判断します。LLM の出力は 4 アクションに制限され、
代替案 pool 内の index でのみ有効、エラー時は無条件に `continue` に
degrade するため BFTS ループはこの hook で詰まりません。

```yaml
lineage_decision:
  mode: stagnation_rule           # off | stagnation_rule | every_node
  stagnation_window: 5            # composite score の window
  stagnation_threshold: 0.05      # max-min < threshold で停滞
  min_nodes_before_decision: 3    # 序盤での発火を抑制
  rate_limit_per_run: 5           # 1 run あたりの escalation 上限
```

| Mode | トリガ | コスト |
|---|---|---|
| `off` | 発火しない | 0 |
| `stagnation_rule` (default) | 連続 `stagnation_window` ノードで composite が flat | 0–`rate_limit_per_run` LLM call |
| `every_node` | 各 BFTS step 後 (LLM が timing 自体も判断) | 1 LLM call/node |

発火した全 decision (continue 含む) は `{checkpoint}/lineage_decisions.jsonl`
に追記され、後から「どこで停滞 / 切替 / 終了したか」が完全に再現できます。
`root_idea_selection` も同じファイルに別 `trigger` で記録されます。

## Root Idea Selection (v0.7.0+)

VirSci が `idea.json` を書いた直後、LLM が venue rubric と ancestor
research thread を見て「`ideas[0]` を据え置きにするか、`ideas[N]` に
入れ替えるか」を判定します。Default は `ideas[0]` (= VirSci スコア順)
維持、LLM 出力が pool 範囲外なら同じく `ideas[0]` にフォールバック。
起動時 1 LLM call、ノード単位の追加コストはなし。

```yaml
root_idea_selection:
  enabled: true                   # v0.7.0+ default
```

決定は `lineage_decisions.jsonl` に
`{trigger: "root_idea_selection", action: "root_swap" | "root_keep"}`
で記録され、`idea.json` の `_root_choice` にも provenance として
保存されます。子 (recursion) は `_inherited_from` または `_root_choice`
を検出して再選択を skip します。

## Claim Gate Policy (v0.7.0+)

`claim_gate_policy` は claim–evidence hard gate（Story2Proposal Phase
B3）を制御するトップレベルブロックです。gate ステージは毎回の論文
ビルドで実行され `{{claim_gate_policy}}` で配線されます。ブロックは
`ari-core/ari/pipeline/claim_gate/policy.py` が読み込みます。

```yaml
claim_gate_policy:
  mode: warn                  # off | warn | strict
  comparison_scope: any       # any | same_environment
  numeric_coverage:
    target_sections:
      strict: [abstract, results, conclusion]
      warn: [introduction, discussion, limitations]
      excluded: [related_work, references, appendix, equations]
  numeric_match:
    default_tolerance: {absolute: 0.0, relative: 0.02}
  blocking:
    block_on: [numeric_mismatch, operand_unresolved, missing_evidence]
```

`mode` がブロッキングを制御します（環境変数 `ARI_CLAIM_GATE_MODE` で
上書き）:

| Mode | 動作 |
|---|---|
| `off` | 決してブロックしない。 |
| `warn`（既定） | エラー/警告を報告するが `finalize_paper` をブロックしない。 |
| `strict` | `block_on` エラーが存在すると**最終** gate がブロックし（`finalize_paper` を skip）、strict セクション内の未カバーの結果数値もブロッキングになる。draft gate は決してブロックしない。 |

`comparison_scope` は注入される研究意図です（環境変数
`ARI_COMPARISON_SCOPE` で上書き）:

| Scope | クロス環境比較 |
|---|---|
| `any`（既定） | 透明性のための**警告**。クロス環境比較自体が貢献となるクロスアーキテクチャ研究向け。 |
| `same_environment` | **ブロッキング**エラー。単一アーキテクチャの最適化研究向け。 |

`numeric_coverage.target_sections` は、gate の重大度ごとに数値クレームを
検査する論文セクション（`strict`/`warn`）と無視するセクション
（`excluded`）を列挙します。`numeric_match.default_tolerance` は、
クレームごとの tolerance が無い場合に適用される照合許容差です
（`absolute: 0.0`、`relative: 0.02`＝2%）。`blocking.block_on` は
`strict` で最終 gate をブロックする finding type のリストです:
`numeric_mismatch`、`operand_unresolved`、`missing_evidence`。

> 別系統の**客観的虚偽**の finding type
> （`invariant_violation`、`correctness_failed`、`correctness_uncovered`、
> `placeholder_denominator`、`recompute_mismatch`、`claim_evidence_missing`、
> `ceiling_unmeasured`）は `mode` に**かかわらず**最終論文をブロックします。
> これらの既定値は `policy.py` の `blocking.always_block_on` にあり、
> `workflow.yaml` には設定されていません。

## BFTS チューニング

環境変数で BFTS の動作を制御します:

```bash
export ARI_MAX_NODES=12      # 最大 12 ノードを探索（小規模実行）
export ARI_PARALLEL=4        # 4 ノードを同時実行
export ARI_EXECUTOR=slurm    # 各ノードを SLURM ジョブとして投入
```

または `workflow.yaml` の `bfts:` セクションでデフォルト値を設定できます（バージョンがサポートしている場合）。

---

## BFTS の評価層 (設定で切替可能)

BFTS の評価は 4 層から構成され、それぞれを `default.yaml`
(またはユーザー YAML) から独立に選択できます。各デフォルト値は
従来の挙動を再現するため、未編集の config は no-op です。

```yaml
bfts:
  frontier_score: scientific_plus_diversity   # フォールバック選択時のスコア戦略
  depth_penalty_lambda: 0.05                  # frontier_score=depth_penalized 用
  ucb_c: 0.5                                  # frontier_score=ucb_like 用
  select_prompt: orchestrator/bfts_select               # select_next_node の LLM プロンプト
  expand_select_prompt: orchestrator/bfts_expand_select # select_best_to_expand の LLM プロンプト

evaluator:
  composite: harmonic_mean   # 各軸スコアを _scientific_score に集約する式
  axis_mode: dynamic         # judge LLM に渡す軸セット
  custom_axes: []            # axis_mode=custom のときだけ参照
  axis_weights: { ... }      # 既存。軸ごとの重み上書き
```

### Layer A — `evaluator.composite`

各軸スコアを集約して `_scientific_score` を作る式を選びます
(`ari/evaluator/llm_evaluator.py`)。`_scientific_score` はノードの
ランキング、lineage decision、レポートのベスト選定すべての
基準値です。

| 値 | 挙動 |
|---|---|
| `harmonic_mean`（デフォルト） | 重み付き調和平均。1 つでも弱い軸があると強く減点。従来の挙動。 |
| `arithmetic_mean` | 重み付き算術平均。軸同士が線形にトレードする寛容な式。 |
| `weighted_min` | 最も低い軸の値を返すボトルネック式。重みは「軸を参加させるか否か」のゲートとして働き、スコアの倍率にはなりません。 |
| `geometric_mean` | 重み付き幾何平均。調和と算術の中間で、弱い軸を程々に罰します。 |

### Layer B — `bfts.frontier_score`

LLM 選択が失敗したときの**決定論的**フォールバックスコア
(`ari/orchestrator/bfts.py` の `_select_fallback`) の戦略です。
LLM 選択そのものはこの設定の影響を受けません。

| 値 | 計算式 |
|---|---|
| `scientific_plus_diversity`（デフォルト） | `_scientific_score + diversity_bonus` |
| `scientific_only` | `_scientific_score`（diversity の同点処理なし） |
| `depth_penalized` | `_scientific_score + diversity_bonus − λ·depth` (`λ = bfts.depth_penalty_lambda`) |
| `ucb_like` | `_scientific_score + diversity_bonus + c · √(log N / (visits + 1))` (`c = bfts.ucb_c`、`visits` は当該ノードの展開回数、`N = total_visits + frontier_size`) |

`depth_penalty_lambda = 0.0` は `depth_penalized` を、`ucb_c = 0.0` は
`ucb_like` を、それぞれデフォルト戦略に縮退させます。

### Layer C — `evaluator.axis_mode`

judge LLM に提示する軸セットを切り替えます。

| 値 | 軸の出どころ |
|---|---|
| `dynamic`（デフォルト） | 汎用 5 軸フロア + 有効な rubric (`ARI_RUBRIC`) 由来 + `idea.json` のプランから抽出されたキーワード軸。`idea.json` の mtime 変化で自動再構築。 |
| `legacy` | 5 軸固定 (`measurement_validity`, `comparative_rigor`, `novelty`, `reproducibility`, `clarity_of_contribution`)。rubric / plan は読みません。 |
| `custom` | `evaluator.custom_axes` を額面通り使用。 |

`custom_axes` は `{name, description, weight}` のリストです。
`description` は judge LLM への入力として使われるため、軸の意味が
判別できる文を書いてください。

```yaml
evaluator:
  axis_mode: custom
  custom_axes:
    - name: speedup
      description: "Wall-clock speedup vs. baseline (1.0 = no change)."
      weight: 0.5
    - name: accuracy
      description: "Numerical accuracy preserved within tolerance."
      weight: 0.5
```

`axis_mode=custom` のとき、`axis_weights` の既定キー名は
自動では custom 軸に置換されません。`axis_weights` で重みを上書き
したい場合は、新しい軸名で再記述してください。

### Layer D — `bfts.select_prompt` / `bfts.expand_select_prompt`

`FilesystemPromptLoader` のキー (拡張子なし、`ari-core/ari/prompts/`
からの相対パス) を指定します。デフォルトは同梱のテンプレートです。

ユーザー定義テンプレートには、BFTS の formatter が使う
placeholder を必ず含めてください:

- `select_prompt`: `{experiment_goal}`, `{memory_context}`, `{candidates}` — LLM は 0-based の整数インデックスのみ返答。
- `expand_select_prompt`: `{experiment_goal}`, `{candidates}` — 同上。

指定キーのファイルが存在しない場合、`FilesystemPromptLoader` は
fail-fast で例外を投げます (黙ったフォールバックはしません)。

### 簡単なレシピ

- **寛容な評価 + UCB 探索:**
  ```yaml
  evaluator: { composite: arithmetic_mean }
  bfts: { frontier_score: ucb_like, ucb_c: 1.0 }
  ```
- **ボトルネック評価 (どの軸もよくないと publish しない):**
  ```yaml
  evaluator: { composite: weighted_min }
  ```
- **judge を 5 軸固定に戻す (レガシー再現):**
  ```yaml
  evaluator: { axis_mode: legacy }
  ```

---

## 実行モードと RQGM ガバナンス（オプトイン）

ARI には 2 つの実行モードがあります。`simple_bfts` がデフォルトであり、
変更はありません — `ari:` / `rqgm:` ブロックの無い設定（つまり RQGM 以前の
すべての設定）は従来とまったく同じに振る舞い、`ari.rqgm` モジュールを
決してロードしません。`ari_rqgm` は Constitutional ARI-RQGM のエポック
ガバナンスへのオプトインです。意味論は
[実行モード](../guides/execution_modes.md)を、永続化されるレコードは
[RQGM スキーマリファレンス](rqgm_schemas.md)を参照してください。

以下のすべての `rqgm.*` / `proposal_router.*` デフォルトは
`ari-core/ari/configs/defaults.yaml` にあり、
`ari-core/ari/config/__init__.py` の型付き Pydantic モデルをミラーします
（両者のパリティは `ari-core/tests/test_rqgm_*.py` スイートでピン留め）。
各ブロックはモードがアクティブでない限り構造的に不活性です; 未知の
後方バージョンキーは警告なしにパースされます（`extra: allow`）。

### 有効化: `ari.mode` + `rqgm.enabled`

```yaml
ari:
  mode: simple_bfts     # simple_bfts | ari_rqgm  (master switch)
rqgm:
  enabled: false        # redundant safety interlock
```

両方のキーが一致していなければなりません; 不一致は警告とともに
`simple_bfts` へ fail-safe します
（`ari.rqgm.mode.resolve_effective_mode`）。環境変数オーバーライド
（プロファイルの後に適用されるため、明示的な env の選択が YAML に勝ち
ます）: `ARI_MODE` ∈ {`simple_bfts`, `ari_rqgm`} および
`ARI_RQGM_ENABLED` ∈ {`0`,`1`,`true`,`false`}; 不正な値は警告の上で無視
されます。`--mode` CLI フラグは存在せず、プロファイル（`--profile`）は
RQGM キーをマージしません。ダッシュボードの Configuration Studio はこの組
（および `paper.mode` の組）を**新規**ランについて設定できます — 1 つの
コントロールが両方のキーを書きます — が、既に存在するランのモードを変更
できる面は存在せず、残りの `rqgm.*` パラメータは設定ファイル専用のままです
（ADR-09。[実行モード](../guides/execution_modes.md)を参照）。

実行指紋を厳密にするため、四つの任意の環境固定値を使える。どれかが
未設定なら期には `unresolved` と記録し、`execution_identity.complete`
は `false` になる。変化しうる提供者側の別名を再現可能とは扱わない。

| 環境変数 | 固定する識別 |
|---|---|
| `ARI_MODEL_REVISION` | 提供者・モデル重み・配備の厳密な版 |
| `ARI_TOOL_BUNDLE_REVISION` | 変更不能な道具一式の版 |
| `ARI_ENVIRONMENT_DIGEST` | コンテナまたは解決済み環境の要約値 |
| `ARI_DATA_SNAPSHOT_DIGEST` | 変更不能な外部データ標本 |

### `rqgm.epoch` — エポック境界のサイズ

| キー | デフォルト | 意味 |
|---|---|---|
| `boundary` | `node_count` | 境界トリガの種類; v1 がサポートするのは `node_count` のみ |
| `nodes_per_epoch` | `10` | 境界トランザクションが発火する新規 BFTS ノード数; `<= 0` は自動境界を無効化する（ランは `epoch_000` に留まる） |

### `rqgm.kernel` — ConstitutionalKernel の姿勢

数値トレランスと姿勢のみです — 規則テーブルは凍結されたコード
（`ari/rqgm/kernel_rules.py` + `ari/rqgm/transition_rules.py`）であり、
決して設定にはなりません。

| キー | デフォルト | 意味 |
|---|---|---|
| `enforcement` | `standard` | `standard` はブロッキングマトリクスを適用; `audit_only` はすべてのコンテキストを warn-and-log に格下げする（段階的ロールアウト / アブレーション）。読み取りはラン開始時 / エポック境界のみ |
| `audit_chain` | `auto` | チェーン検証の姿勢; v1: `auto` のみ（チェーンフィールドがある場合に限りハッシュチェーンを検証） |
| `float_tolerance` | `1.0e-9` | カーネルチェックが使う単一の浮動小数比較トレランス |

### `rqgm.governance` — GovernanceOrchestrator の予算と姿勢

| キー | デフォルト | 意味 |
|---|---|---|
| `enabled` | `true` | `ari_rqgm` 内でのエポック境界ガバナンス監査の on/off（アブレーションの段はガバナンスを off にして `ari_rqgm` を走らせる） |
| `default_level` | `1` | レポートに刻印されるエポックごとのデフォルトガバナンスレベル |
| `full_governance_only_on_top_k` | `3` | 完全な adversary/defender/judge の注意は top-k ノードのみ |
| `judge_on_disputed_only` | `true` | ノードごとの adversarial ラウンド**専用**。予算ゲートが Defender 呼び出しを拒否したとき、反論されなかった攻撃はノードごとの `ArtifactJudge` に到達せず、ログ上の観測として失効する（`ari/rqgm/adversarial/round.py`）。エポック境界の `GovernanceJudge` はゲートし**ない** — `audit_epoch` の裁定ステップはこのキーを読まない |
| `impeachment_only_at_epoch_boundary` | `true` | 宣言のみ — **このキーを読むコードパスは存在しない**。動議が `audit_epoch` の内側でのみ提出されるのは、そこがファサード唯一の動議入口だからであり、スイッチではなく構造上の性質。`false` にしてもエポック途中の動議は有効にならない |
| `max_llm_calls_per_audit` | `12` | `audit_epoch` ごとのハードキャップ; 超えると各ステップは決定論的フォールバックへ縮退 |
| `max_defender_calls_per_epoch` | `12` | エポックごとの Defender LLM 呼び出しキャップ（adversary のキャップは `rqgm.adversarial.max_adversary_calls_per_epoch` のみに存在） |
| `max_judge_calls_per_epoch` | `8` | エポックごとの Judge LLM 呼び出しキャップ |
| `low_confidence_threshold` | `0.4` | reviewer の確信度がこれ未満のノードは disputed とマークされる |
| `novelty_claim_threshold` | `0.8` | novelty 軸がこれ以上（または novelty リスクが非空）なら contested ティアをトリガ |
| `max_motions_per_epoch` | `2` | エポックごとの弾劾動議のハードキャップ |
| `bond_units_per_motion` | `1` | 動議枠単位を表す旧フィールド名。認容時は枠へ戻し、棄却時は消費する。価値の移転はない |
| `jury_panel_enabled` | `false` | JuryPanel（マルチサンプルのジャッジ集約）; v1 では off |
| `fail_mode` | `open` | v1: `open` のみ — no-action レポートへ縮退し、ランループを決してブロックしない |

### `rqgm.replay` — リプレイ / アンカーケースのサイズ

| キー | デフォルト | 意味 |
|---|---|---|
| `max_cases_per_epoch` | `8` | 監査ごと・対象ごとに採点されるリプレイ / アンカーケースの上限 |
| `max_cases_for_retirement` | `12` | 動議が RetirementEvent を検討に載せたときの引き上げられた上限 |
| `use_cached_results` | `true` | キャッシュ済みケース結果（`rqgm_governance_cache.jsonl`）を優先する; ボードはキャッシュ結果を所与として決定論的 |

### `rqgm.transition` — RegistryTransitionEngine のしきい値

しきい値は遷移層で**唯一**チューニング可能な部分です; T1–T21 テーブルの
トポロジは固定コード（`ari/rqgm/transition_rules.py`）です。

| キー | デフォルト | 意味 |
|---|---|---|
| `replay_pass_threshold` | `0.8` | T3: validated な候補が shadow に入るための最小リプレイボードスコア |
| `replay_min_cases` | `4` | T3: スコアの背後にある最小リプレイケース数。実行済みリプレイケースが構造上存在せず、それを明示的に宣言するロール（`transition_engine.NO_REPLAY_BASIS_ROLES` — `utility_policy` / `paper_writer` / `paper_reviewer`）では免除され、免除は遷移の notes に記録される。振る舞い系の探索ロールは常にこの下限に従う |
| `shadow_pass_threshold` | `0.7` | T6: 仮採用のための最小 shadow 一致率; 十分なサンプルがあってこれを下回れば T5 の却下 |
| `shadow_min_samples` | `5` | T6: 採用 / 却下が判定可能になるまでの最小ライブ shadow 比較数。同じく宣言済みの `NO_REPLAY_BASIS_ROLES` では免除される。受動的な `utility_policy` ドキュメントは shadow 実行されず、paper 系ロールにも shadow 配信経路がないため、その shadow 段階は「数が足りない」のではなく構造上空虚である（plan 14 §5.5）。報告された `shadow_score` は依然として `shadow_pass_threshold` を満たす必要があり、免除されるのは件数のみ |
| `shadow_max_epochs` | `2` | T4: 十分なサンプルが無いまま shadow に留まれるエポック数（有界リトライまで） |
| `shadow_retry_limit` | `1` | T4: 有界の shadow リトライ; 超えると候補は T5 の却下を受ける |
| `probation_min_epochs` | `1` | T7/T14: active への昇格前に務めるべきクリーンな完全エポック数 |
| `warning_escalation_count` | `2` | T10: probation へエスカレートするまでの連続 warning エポック数 |
| `warning_memory_epochs` | `3` | T13: warning 入り後、probation へエスカレートする再発ウィンドウ |
| `retirement_replay_min_cases` | `8` | T17: 退役がコミットされる前の最小 ReplayBoard ケースカバレッジ（`<= rqgm.replay.max_cases_for_retirement`） |
| `candidate_max_age_epochs` | `3` | T2: 候補が失効前に検証を待てるエポック数 |
| `max_adoptions_per_role_per_boundary` | `1` | T6: エポック境界ごと・ロールごとの採用キャップ |

### `rqgm.adversarial` — attack→defense→adjudication ループ

| キー | デフォルト | 意味 |
|---|---|---|
| `enabled` | `true` | 敵対ラウンドを完了ノードごとに走らせるかどうか |
| `types` | 全 8 種 | 有効な adversary タイプ（閉じた集合）: 探索用 7 種 `overclaim`、`metric_gaming`、`prior_art`、`reproducibility`、`evidence_gap`、`cost_explosion`、`prompt_injection` に `paper_self_preference` を加えたもの。8 番目は paper-archive フェーズ以外では動作しない |
| `max_attacks_per_node` | `3` | ラウンドごとの生攻撃のハードキャップ |
| `max_adversary_calls_per_epoch` | `24` | adversary LLM 呼び出しのエポックごとのハードキャップ（このキャップの唯一のスキーマ上の置き場所） |
| `sample_mod` | `5` | 決定論的な 1-in-N ノードサンプリング（`hash(node_id+epoch_id) mod N == 0`; P2-safe）。`<= 0` はサンプリング無効 |
| `jump_threshold` | `0.25` | ラウンドをトリガする親からのスコアジャンプ |
| `full_governance_only_on_top_k` | `3` | ラウンドをトリガするフロンティア top-K メンバーシップ |
| `penalty.cap` | `0.5` | 合算された validated-attack ペナルティのノードごとハードキャップ（ペナルティがスコアを上げることは決してない） |
| `penalty.severity_weights` | `low: 0.05`、`medium: 0.15`、`high: 0.3`、`critical: 0.5` | ジャッジ割り当ての severity → 重み。固定の verdict 係数（valid = 1.0、partially_valid = 0.5）を乗算 |
| `pool.max_cases` | `64` | 有界の AdversarialReplayPool サイズ（eviction は論理のみ） |
| `pool.min_severity` | `medium` | ジャッジ割り当て severity のプール受け入れ下限 |
| `pool.min_per_type` | `2` | adversary タイプのカバレッジがキャップを生き延びるための、タイプごとの eviction 下限 |

### `rqgm.shadow` — shadow ライブ評価サンプリング

shadow の出力は観察のみです: BFTS のスコア、フロンティア、メモリには
決して到達しません。

| キー | デフォルト | 意味 |
|---|---|---|
| `enabled` | `true` | shadow ライブ評価の on/off（off == shadow 予算ゼロ） |
| `sample_rate` | `0.2` | 候補ごとに shadow サンプリングされるライブ呼び出しの割合（決定論的ハッシュサンプリング） |
| `max_shadow_calls_per_epoch` | `10` | エポックごとの shadow 並走呼び出しのハードキャップ |

### `rqgm.prompt_evolution` — 候補キャップ

| キー | デフォルト | 意味 |
|---|---|---|
| `enabled` | `true` | `ari_rqgm` 内でのプロンプト進化の on/off（ガバナンスあり・プロンプト凍結のアブレーションをサポート） |
| `max_candidates_per_role_per_epoch` | `1` | エポックごと・ロールごとの新規プロンプト候補のキャップ |
| `max_total_candidates_per_epoch` | `4` | 全ロール合計での、エポックごとの新規プロンプト候補のキャップ |
| `max_clean_room_generations_per_epoch` | `1` | エポックごとのクリーンルーム再生成のキャップ（クリーンルームパイプラインが消費） |
| `mutation_kinds` | 全 5 種 | 有効な PromptMutator ファミリ: `freeform_mutation`、`threshold_tuning`、`schema_tightening`、`specialization`、`distillation` |

### `rqgm.utility_evolution` — スコア自身の統治された書き換え

エポック境界では utility 関数そのものが統治対象オブジェクトです。書き換えは
`PolicyMutator` → `CandidateValidationPipeline` → `RegistryTransitionEngine`
→ `ConstitutionalKernel` の経路でしか起こらず、その場で書き換えられることは
ありません。

**数値と語彙のノブのみです。** 合法性ルール — 閉じた値空間と軸重みの上下限 —
は `ari.rqgm.kernel_rules.UTILITY_POLICY_RULES` の凍結されたコードであり、
`constitution_hash` の*内側*にあります。調整可能な重み上限は調整可能な憲法に
なってしまいます。ここに置かれていそうで意図的に置かれていない予算が 2 つ
あります。それぞれ既にスキーマ上の住所を 1 つ持っているからです: 候補キャップは
`rqgm.prompt_evolution.max_candidates_*` に、採用キャップは
`rqgm.transition.max_adoptions_per_role_per_boundary` に乗ります。

| キー | デフォルト | 意味 |
|---|---|---|
| `enabled` | `true` | `ari_rqgm` 内での統治された utility 進化の on/off。`false` は書き換え導入前のスコアリング挙動を正確に再現します — 候補は 1 つも生成されず、何も置き換わらず、`utility_policy_hash` はラン全体で一定です（アブレーション用の段）。founding で登録される `utility_policy_v1` / `policy_mutator_v1` コンポーネントの登録を取り消すわけでは**ありません**。 |
| `mutation_kinds` | `axis_reweighting`、`composite_swap`、`frontier_score_swap`、`exploration_tuning` | 有効な `PolicyMutator` ファミリ。既定の 4 つはいずれも境界の証拠に対する純粋な算術で、LLM も時計も乱数も使いません。したがって既定の書き換えストリームは決定論的です。`freeform_policy_proposal` は LLM を参照するオプトインで、有効化すると候補ストリームのバイト再現性を失います（再現不能な*提案*であっても、未検証の policy になることはできません — カーネルはどちらの場合も検証します）。 |
| `min_epochs_between_rewrites` | `1` | 採用される書き換え 2 回の間の最小エポック数。修復コストを抑えます: 書き換えは旧ポリシー下で採点された全ノードを無効化し、早い境界ではそれが木全体になりえます。 |

### `rqgm.clean_room` — クリーンルーム再生成の姿勢

スクリーンの*ポリシー*はコード（`ari/rqgm/clean_room_rules.py`）です;
ここに置かれるのは数値ノブのみです。エポックごとの生成予算は
`rqgm.prompt_evolution.max_clean_room_generations_per_epoch` に乗ります。

| キー | デフォルト | 意味 |
|---|---|---|
| `generation_backend` | `one_shot` | v1 唯一のバックエンド: ツール / ファイルシステム無しの単一 LLM 補完（ツール付きループは退役プロンプトのテキストを読みうる） |
| `contamination_screen.shingle_k` | `8` | 決定論的汚染スクリーンの word-shingle 長 |
| `contamination_screen.fail_on_any_hit` | `true` | 禁止コーパスとの k-shingle 重複が 1 つでも残れば候補の受け入れをブロック |
| `generator_prompt_key` | `rqgm/clean_room_generator` | CleanRoomPromptGenerator のコミット済みメタプロンプトキー |

### `rqgm.frontier_repair` — 選択的消去 / フロンティア再構築

コミットされた EpochTransition が退役を伴うときにのみ走ります。

| キー | デフォルト | 意味 |
|---|---|---|
| `enabled` | `true` | 退役のある境界で修復を走らせるかどうか |
| `max_trace_depth` | `8` | 依存閉包トレーサの BFS 上限; 超えたコンシューマは保守的に一括処理（invalidate）される |
| `recompute_utilities` | `true` | stale な採点済み証拠について、元のエポックの凍結重みの下で生き残った入力から utility を再計算する; `false` は代わりにノードを無効化する。utility-policy 退役では別途、保存済み `_axis_scores` を新しいポリシーで再採点するため、このスイッチで policy rewrite は無効にならない |
| `abandon_stale_pending` | `true` | 提案レコードが実行前に stale になった保留中の子を放棄する |

### `rqgm.meta_evolution` — メタティアの予算とスイッチ

権限マトリクス自体は凍結コード（`ari/rqgm/meta_rules.py`）であり、決して
設定にはなりません。

| キー | デフォルト | 意味 |
|---|---|---|
| `enabled` | `true` | メタ進化ステップの on/off（無効時はコーディネータが監査 1 行を残して no-op） |
| `evolving_roles` | `prompt_mutator`、`clean_room_generator`、`replay_selector`、`failure_summary_compressor` | v1 の進化するメタロール; コード変更なしで層を凍結するには `[]` へ縮小可能 |
| `max_meta_candidates_per_epoch` | `1` | メタロール合計での、エポックごとのメタ候補キャップ |
| `sandbox.max_cases` | `6` | サンドボックス評価ごとにリプレイされる過去のメタタスクバンドル数 |
| `sandbox.use_cached_results` | `true` | コンテンツキーのサンドボックス結果を再利用する |
| `shadow.min_epochs_before_probation` | `2` | メタ候補が `probationary_active` の前に shadow で過ごす最低エポック数（制度層の下限より厳しい） |
| `metric_spec_weight_cap` | `true` | 憲法上のキャップ: ノード起点の MetricSpec 軸重みは、エポック凍結された重みレジームを優先して抑制される（`simple_bfts` では無視） |

### `rqgm.budgets` — エポックごとのガバナンス支出キャップ

受動的な `cost_tracker` レコードに対して読み取られます; `0` は無制限
（帰属のみ — 不活性なデフォルト）を意味します。枯渇が劣化させるのは
ガバナンスであり、ノード実行では決してありません; 固定層は構造上その
対象外です。

| キー | デフォルト | 意味 |
|---|---|---|
| `max_governance_cost_usd_per_epoch` | `0` | ガバナンスフェーズの LLM 支出に対するエポックごとの USD キャップ |
| `max_governance_tokens_per_epoch` | `0` | ガバナンスフェーズの LLM 支出に対するエポックごとのトークンキャップ |
| `on_exhausted` | `degrade` | `degrade` はノードの実効ガバナンスレベルに上限をかける; `skip` は単一のアクションを落とす。クラッシュは決してしない |

**予算対象のアクション種別。** 上記 3 キーはこのブロックが所有する唯一の
ノブですが、`GovernanceBudgetManager` が数えているのはそれだけではありません。
提出されるガバナンスアクションはいずれも 10 種の*アクション種別*
（`ari/rqgm/budget.py` の `ACTION_KINDS`）のどれかを持ち、それぞれ独自の
エポックごとカウンタを持ちます。各種別のキャップはそのノブを所有する
ブロックから読まれ、別名は存在しません。語彙は閉じています:

| アクション種別 | エポックごとのキャップの出どころ | デフォルト |
|---|---|---|
| `adversary_call` | `rqgm.adversarial.max_adversary_calls_per_epoch` | `24` |
| `defender_call` | `rqgm.governance.max_defender_calls_per_epoch` | `12` |
| `judge_call` | `rqgm.governance.max_judge_calls_per_epoch` | `8` |
| `shadow_call` | `rqgm.shadow.max_shadow_calls_per_epoch`。`rqgm.shadow.enabled` が false なら `0` | `10` |
| `replay_case` | `rqgm.replay.max_cases_per_epoch`。RetirementEvent が検討中なら `rqgm.replay.max_cases_for_retirement` | `8` / `12` |
| `virsci_call` | `proposal_router.generators.virsci.max_calls_per_epoch`。当該ジェネレータが無効なら `0`、値が `<= 0` なら無制限 | `2` |
| `prompt_candidate` | `rqgm.prompt_evolution.max_candidates_per_role_per_epoch`（ロール単位で計数）。加えて全ロール合計の第 2 の天井として `max_total_candidates_per_epoch` | `1` / `4` |
| `clean_room_generation` | `rqgm.prompt_evolution.max_clean_room_generations_per_epoch` | `1` |
| `governance_llm_call` | `rqgm.governance.max_llm_calls_per_audit` | `12` |
| `paper_anchor_scoring` | `rqgm.paper.anchor.sample_size`。`rqgm.paper.anchor.enabled` が false なら `0` | `8` |

レベル 0 の固定チェックはアクションを提出せず、構造上その対象外です。
カウンタのキーは `(epoch_id, kind)`（ロール単位の `prompt_candidate` は
`(epoch_id, kind:role)`）で、構築時に `budget_consumed` の監査行から
再構成されるため、キャップは `ari resume` をまたいで生き残ります。キャップが
無い場合は無制限を意味し、チェック内部の失敗は警告をログして**フェイル
オープン**します（ランをブロックしません）。`paper_anchor_scoring` は
paper-archive フェーズが元の 9 種に追加した唯一の種別です。そのキャップの
背後にあるコストモデルは下の `rqgm.paper.anchor` の節にあります。

### `rqgm.eval` — 評価ハーネスの姿勢

すべてのデフォルトは off です: `scripts/rqgm_eval` ハーネスが自身の起動
するランで有効化しない限り、scripted な評価ダブルは拒否され、注入は
決して適用されません。[RQGM 評価](../guides/rqgm_evaluation.md)を参照。

| キー | デフォルト | 意味 |
|---|---|---|
| `enabled` | `false` | 評価ハーネスのマスターインターロック。デフォルトで有効化されることは決してない |
| `scripted_components` | `{}` | `role -> double_name` の差し替え（ハーネス専用） |
| `injection_specs` | `[]` | アクティブな `eval_*` 注入 id; `rqgm_injection_provenance.json` に記録される |
| `paper_ablation.condition_id` | `""` | RQGM元論文に合わせた評価専用条件（`P0_hgm_h_fixed_critic`～`P4_constitutional_rqgm`）。空、または `eval.enabled: false` なら通常挙動を保つ。`paper.mode` ではない |

### `rqgm.paper` — paper-archive 共進化

`rqgm.paper.*` ブロックは全体として、**実効 paper モードが `rqgm_archive`
でない限り不活性**です（`paper.mode: rqgm_archive` と
`rqgm.paper.enabled: true` の両方が一致していること）。`ari.mode` とは直交で、
上の探索側 `rqgm.*` ノブを覆い隠すことは決してありません — 名前が似ていても
2 つの層はスキーマ上の住所が別です。意味論はコンセプト側にあります:
[RQGM アーキテクチャ](../concepts/rqgm_architecture.md) の
*paper-archive レイヤ*。

| キー | デフォルト | 意味 |
|---|---|---|
| `enabled` | `false` | `rqgm.enabled` を写した冗長な安全インターロック |
| `archive.width` | `4` | 深さ 1 のシードドラフト数 — ルートの分岐数 |
| `archive.refine_rounds` | `2` | ドラフトごとの refine 子ノード数 — ドラフトの分岐数 |
| `archive.max_expansions` | `12` | エポックごとのノード予算。archive が BFTS の `max_total_nodes` として使う*実効*キャップは `min(width × (1 + refine_rounds), max_expansions)` で、既定値では両項が一致します（4 × 3 = 12）。この上限が、自前の予算アクション種別を持たない paper アクタを構造的に制限します |
| `archive.depth` | `3` | ドラフト木の深さ。archive の BFTS `max_depth` として使われます。木を深くしても同じノード予算が配り直されるだけで、増えることはありません |
| `archive.compile_threshold` | `0.0` | 勝者を遅延コンパイルするために必要な best-belief スコアの下限 |
| `epoch.rounds` | `2` | paper フェーズあたりの archive ラウンド数。1 ラウンド = 1 paper エポック。この安価な既定値では reviewer の採用完了は意図的に買えません: その道のりは candidate → validated → shadow → probationary_active であり、先にロールの空きが必要なので概ね 5 境界かかります。`2` では既定のランでもループ・adversary・弾劾は動きますが、アクティブな reviewer ハッシュが変わるところは観測できません。採用を観測させたいランでは引き上げてください |
| `self_preference.enabled` | `true` | self-preference adversary。`rqgm_archive` paper モード下でのみ意味を持ちます |
| `self_preference.corpus_path` | `""` | `""` は anchor コーパスとその著者ラベルを再利用します |
| `self_preference.sample_size` | `8` | エポックごとに採点する held-out 論文数（anchor のサンプルを写したもの） |
| `self_preference.accept_threshold` | `0.6` | reviewer の「accepted」カットオフ |
| `self_preference.margin` | `0.1` | 事前シグナルを発火させる AI 対 人間の平均スコア差 |
| `prompt_evolution.enabled` | `true` | archive 内での reviewer / writer 共進化。`false` にすると共進化なしのレビュー済みドラフト best-of-N に縮退します |

### `rqgm.paper.anchor` — held-out な accept/reject 一致度

`paper_reviewer` のグラウンドトゥルース・アンカー: `train` / `held_out` に
分割された読み取り専用の accept/reject コーパスで、その形は
[RQGM スキーマリファレンス](rqgm_schemas.md) の
*`paper_anchor_corpus.jsonl` — 読み取り専用の accept/reject アンカー* に
記載されています。既定は off で、これは縮退したオンランプです: コーパスは
読まれず、`anchor_evaluation` ステージはゼロカバレッジのパスを取り、reviewer
候補は anchor でゲートされません。`paper_writer` にもアンカーはありますが、
そちらは Layer-0 の claim-evidence ゲートでありキュレーション済みコーパスを
必要としません — ただし writer の忠実性ケースはこのプールに着地するため、
`enabled: false` は writer 側の制裁もゲートします。

| キー | デフォルト | 意味 |
|---|---|---|
| `enabled` | `false` | anchor コーパス採点の on/off。`paper_anchor_scoring` 予算のスイッチでもあり、無効ならキャップは `0` — `shadow_call` / `virsci_call` と同じ「無効ならゼロ」の規則です |
| `corpus_path` | `""` | accept/reject コーパスのパス（checkpoint 相対または絶対） |
| `sample_size` | `8` | held-out 一致度のサンプルサイズであり、**同時に** `paper_anchor_scoring` のエポックごとキャップです。reviewer 候補は `sample_size` 件の held-out 論文に対して採点されることで anchor 一致度の utility を得るため、ガバナンスコストは O(候補数 × `sample_size`) になります。だからこのキャップは別途チューニングされた数値ではなくサンプルサイズそのものです。チューニング済み定数ではなくコストモデルとして読んでください |
| `max_bootstrap_label_fraction` | `0.5` | `label_source=gate_bootstrap` のケースが占めうる割合の機械的な上限で、コーパス*および* held-out 部分集合の両方で検査されます。違反するとコーパスは拒否され — ロードは何も返さずランはオンランプに落ちます — ランに例外が飛ぶことはありません。`0.0` は人手ラベルのみ、`1.0` は完全に自己ラベル付けされたアンカーも受け入れます（フィンガープリントされます） |

知っておくべき不整合が 1 つあります。`enabled` の型付きデフォルトは `false`
（`RQGMPaperAnchorConfig`）ですが、予算マネージャが anchor ブロックのオブジェクト
自体を*見つけられなかった*ときのフォールバックは `true` です。このフォールバックが
効くのは `anchor` ブロックを持たない設定に対してだけで、同梱デフォルトから
組み立てられた設定は常に `enabled: false` を提示します。

### `rqgm.paper.reviewer.agent_as_judge` — agent-as-judge によるドラフト採点

実効 paper モードが `rqgm_archive`（`paper.mode: rqgm_archive` と
`rqgm.paper.enabled: true` の両方が一致）のときに**のみ**読まれます;
これは `ari.mode` とは直交します。デフォルトは off で、その場合アーカイブ
のドラフト採点器は決定論的で LLM を使わない venue ルーブリックのままとなり、
ドラフト採点経路にライブ LLM 呼び出しは載りません（P2）。on にすると
共有の paper ディスパッチ（`ari/cli/paper_dispatch.py`; `ari paper` /
`ari run` / `ari resume` が使用）が `LLMClient` ベースのレビュアスコアラ
（`ari/rqgm/paper_judge.py`）を注入します。これは**同じ** venue ルーブリック
軸で各ドラフトを採点しますが、その重みは**アクティブ**な統治対象
`paper_reviewer` プロンプトの強調に従います — 決定論的リーダには読めない軸
（`novelty` / `significance`）を読める唯一の経路です。フェイルオープン: LLM
エラー、パース不能な応答、あるいはルーブリック総軸重みの 50% 未満しか
カバーしない応答は、捏造した定数ではなく決定論的ルーブリックスコアに
縮退します（非有限な軸値は選択に伝播させず破棄されます）。judge スコアと
フォールバックスコアはどの消費者から見ても同じ float なので、同じディスパッチ
がランごとの judged / degraded 件数を `ari.log` にログします。

| キー | デフォルト | 意味 |
|---|---|---|
| `enabled` | `false` | agent-as-judge によるドラフト採点の on/off。`ARI_PAPER_AGENT_AS_JUDGE` ∈ {`0`,`1`,`true`,`false`} で上書きされる; 不正な値は警告の上で無視される |
| `max_tokens` | `1024` | judge 応答長の上限（コスト制御）; `LLMClient.complete(max_tokens=...)` に渡される |

### `proposal_router` — 提案生成のルーティング

実効モードが `ari_rqgm` のとき**のみ**消費されます — 例外は
`record_only` で、これは `simple_bfts` でも尊重されます（record-only
デュアルライト、アブレーション B1）。`generators.virsci.enabled` は
意図的に `simple_bfts` では読まれません: そこでは既存の VirSci レバー
（`bfts_pipeline.generate_idea.enabled` / `ARI_IDEA_VIRSCI_REAL`）が
引き続き権威であり、モード解決は `proposal_router.*` を決して読みません
（VirSci は `ari.mode` と直交します）。

| キー | デフォルト | 意味 |
|---|---|---|
| `record_only` | `false` | `simple_bfts` で、エージェントループの `idea.json` 出力を追加で `proposals/proposal_records.jsonl` に `legacy_idea_json` レコードとしてインポートする。挙動変更ゼロ; ロールバック = フラグの削除 |
| `summary_budget_chars` | `6000` | レンダリングされる ProposalSummaryView expand コンテキストの総文字数予算 |

`proposal_router.generators.*` 以下のジェネレータごとのエントリは 2 つの
キーを共有します: `enabled`（ルータがそこへルーティングしてよいか）と
`max_calls_per_epoch`（`0` = 無制限）:

| ジェネレータ | `enabled` | `max_calls_per_epoch` | 備考 |
|---|---|---|---|
| `cheap` | `true` | `0`（無制限） | ワンショットの LLM 提案ジェネレータ; 決定論的なルーティングフォールバック |
| `mutation` | `true` | `2` | 既存 ProposalRecord のひとつの面を変異させる |
| `attack_driven` | `false` | `0` | ValidatedAttackRecord を消費; デフォルトでは無効かつルーティングテーブルに不在 |
| `prior_art` | `true` | `1` | 提案を調査 / 関連文献に対して差別化する; 先行研究ソースが無ければ skipped に縮退 |
| `virsci` | `false` | `2` | オプトインの高コスト熟議型 VirSciAdapter; デフォルトで有効になることは決してない。追加キー: `mode: event_triggered`（v1 唯一のモード）と `trigger_on: [initial_exploration, frontier_stagnation, major_pivot, paper_candidate]` |

---

## EAR キュレーション (`ear/publish.yaml`) — v0.7.0+

キュレーションは `{checkpoint}/ear/` のうち何を公開対象にするかを著者が
allowlist で制御し、`{checkpoint}/ear_published/` + `manifest.lock`
に出力する仕組みです。ari-core 側には **built-in deny list** が組み込まれ
ており、`include` よりも常に強く効きます (機密ファイルの誤公開防止)。

### スキーマ (`ari-core/ari/schemas/publish.schema.json`)

```yaml
# 例: <checkpoint>/ear/publish.yaml
include:                     # ear/ からの相対 glob (allowlist)
  - "README.md"
  - "LICENSE"
  - "reproduce.sh"
  - "code/**"                # contributing chain の verbatim ソース
  - "data/**"                # アップロード入力のみ。実験出力は含めない
  - "figures/**"             # top-level の figures
  - "environment.json"
# 注: EVOLUTION.md と _provenance.json は ear/ の外（checkpoint root）に置かれる
# ARI 監査ログで、公開バンドルの対象外です。
exclude: []                  # ユーザ指定の除外 (include の後に適用)
max_file_mb: 100             # この値を超える allowlist 該当ファイルは明示的にエラー
visibility: staged           # staged|public|unlisted|private-token|embargoed-until:YYYY-MM-DD
required: false              # true のとき publish 失敗は paper pipeline を hard-fail させる
auto_promote: false          # true のとき再現性通過後に staged→public を自動 promote
license: MIT                 # SPDX id。同じ id から ear/LICENSE が生成される
backend: ari-registry        # ari-registry|gh|zenodo|s3|local-tarball (CLI --backend が優先)
```

v0.6.0 旧パス (`code/<node_id>/**`, `data/raw_metrics.json`, `logs/**`, `reproducibility/**`) は v0.7.0 の `generate_ear` では生成されません。古い `publish.yaml` からは削除してください。詳細は `docs/reference/skills.md` を参照。

### Built-in deny パターン

`include` に該当しても **常に** 除外:

```
.env, .env.*, **/.env, **/.env.*
**/secrets/**, secrets/**
**/*.pem, **/*.key
**/id_rsa, **/id_ed25519
```

除外ファイルのパスは `manifest.lock` に記録されません (件数のみ)。
manifest 自体から機密ファイル名が漏れない設計です。

### 動作

- `publish.yaml` が **無い** とき、`ear_curate` ステージは静かに skip され、
  論文の Code Availability 節も省略されます (v0.6.0 チェックポイントと完全後方互換)。
- **bundle digest** (`manifest.lock` の `bundle_sha256`) はソート済みファイル
  レコード (path + size + sha256) の正規化 JSON の sha256 で、マシン間で再現可能。
  論文に焼き込まれる「永続的真実」となる値です。
- キュレーションは **atomic**: `max_file_mb` 超過などで hard-fail した場合でも、
  直前の正常な `ear_published/` は破壊されません。

### CLI

```bash
# Curate
ari ear curate <checkpoint>            # 整形出力
ari ear curate <checkpoint> --json     # 機械可読
ari ear status <checkpoint>            # manifest サマリ表示

# Publish & promote
ari ear publish <checkpoint> --backend ari-registry --visibility staged
ari ear promote <checkpoint> --target public
```

### Pipeline 統合

`workflow.yaml` の paper パイプラインに `ear_curate` ステージが
`generate_ear` と `generate_figures` の間に挿入されます。transform
skill の `curate_ear` MCP ツールを呼び、`publish.yaml` 不在時は no-op。
