---
sources:
  - path: ari-core/tests
    role: test
  - path: ari-core/tests/fixtures/gui_refresh
    role: test
  - path: pytest.ini
    role: config
  - path: scripts/docs
    role: test
  - path: scripts/check_dashboard_ux.py
    role: test
  - path: scripts/check_bundle_budget.py
    role: test
  - path: scripts/quality/check_bundle_budget.yaml
    role: config
  - path: ari-core/ari/viz/frontend/src/i18n
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__
    role: test
  - path: ari-core/ari/viz/frontend/vitest.config.ts
    role: config
  - path: ari-core/ari/viz/frontend/package.json
    role: config
  - path: .github/workflows
    role: config
last_verified: 2026-08-17
---

# ARI コードのテスト方法

このガイドでは `ari-core` と `ari-skill-*` パッケージのテスト規約を説明します:
テストの配置場所、期待されるフィクスチャ、決定性保証の維持方法を扱います。

## リポジトリレイアウト

```
ari-core/tests/                    — コアの回帰テスト
ari-skill-<name>/tests/            — スキルローカルのテスト
ari-skill-<name>/tests/conftest.py — スキルレベルのフィクスチャ（17 スキル中
                                     13。harness と knowledge は tests/ 自体を
                                     持たず、idea と paper-re は tests/ はあるが
                                     conftest が無い。benchmark と plot は
                                     パッケージルートに 2 つ目を置いている）
pytest.ini                         — リポジトリ全体の設定
```

リポジトリルートの `pytest.ini` は、素の `pytest` が走査する `testpaths` を
定めます: `ari-core/tests` と `workspace/harnesses`（後者は workspace の無い
チェックアウトでは存在せず、pytest はそれを許容します）。`ari-skill-*` の
スイートは意図的に `testpaths` に**入れていません** — 各スキルが独自の
`src/server.py` を持つため、2 つを同一プロセスで import すると曖昧になります。
パッケージ単位で実行するか、フルスイートは `bash scripts/run_all_tests.sh`
（パスごとに 1 つの pytest プロセス）を使ってください。

## スイートの実行

```bash
pytest -q                                        # 既定の testpaths のみ
bash scripts/run_all_tests.sh                    # フルスイート（パス毎に別プロセス）
pytest ari-skill-memory/tests -q                 # スキル 1 つ
pytest ari-core/tests/test_react_driver.py -q    # ファイル 1 つ
pytest ari-core/tests/test_react_driver.py::TestRunReact  # クラス 1 つ
pytest ari-core/tests/test_gui_v1_api.py::test_projects_happy_path  # ケース 1 つ
pytest -k 'memory and not letta' -q              # キーワード指定
```

## ari-core の規約

### 必ず書き込みを分離する

ARI はかつて `$HOME/.ari/` に書き込んでいました。v0.5.0 でそのパスは削除され、
2 つのガードがそれを維持しています。`ari-core/tests/test_no_user_home_writes.py`
が持つテストは `test_module_imports_do_not_write_user_home` 1 本だけで、
固定リストの 8 モジュール（`ari.config`、`ari.paths`、`ari.cost_tracker`、
`ari.lineage`、`ari.memory.client`、`ari.memory.local_client`、
`ari.publish.backends.ari_registry`、`ari.clone.resolvers.ari`）を偽の `HOME`
の下で import し、import 時点で `$HOME/.ari/` が作られないことだけを検証します。
スイート全体のガードは `refactor-guards` workflow で、`HOME` を差し替えて
`ari-core/tests` 全体を実行し、終了後に `$HOME/.ari/` が存在すれば job を落とします
— 「どのテストもそこにファイルを作らない」を仮定でなく強制しているのはこちらです。
ファイルシステムに触れる新しいテストを書く場合:

- `monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))` を使用する。
- 補助ディレクトリには `tmp_path` を使用する。
- 本番コードで `Path.home()` を直接呼び出さない。テストで必要な場合は
  理由を文書化し、監査リストに追加する。

### エージェントループのスモークテスト

`ari-core/tests/test_react_driver.py` は `ari.agent.react_driver` を、
`LLMClient` と `MCPClient` をスタブに差し替えた状態でカバーします。実 LLM も
MCP サーバも使いません。ノード間を通す統合実行ではなく unit ファイルで、
純関数を固定するヘルパクラスが 3 つ（`TestValidatePaths` —
`_validate_paths_in_args` に対する 11 ケース、サンドボックス脱出と traversal の
規則。`TestBuildWindow` — 会話ウィンドウの切り詰め。`TestFinalToolDef`）、
そして `TestRunReact` が `run_react` を 4 通りで駆動します — final tool 呼び出しに
よる完了、サンドボックス違反による dispatch 阻止、final tool が呼ばれないままの
max-steps 終了、ログファイルの永続化。

新しいエージェントレベルの機能を追加するときも同じ形に従ってください:
クライアントをスタブ化し、ループの観測可能な遷移を検証し、ネットワークと
サブプロセス呼び出しをファイルに持ち込まないこと。

### 決定性保証 (P2)

「同じシード、同じツリー」を実行全体で端から端まで検証しているものは、この
リポジトリには存在しません。固定されているのはもっと狭い範囲で、名前で把握して
おく価値があります:
`ari-core/tests/test_gui_baseline_run_fixtures.py::test_same_seed_is_byte_identical`
が同じ `(nodes, seed)` から 2 つのチェックポイントを生成してバイト単位で比較し
（否定側が `test_different_seed_changes_content`）、memory スイートが決定論的な
ツリーの前提となる分離性を固定します —
`ari-skill-memory/tests/test_checkpoint_isolation.py`（2 つのチェックポイントが
互いを見ない）と `ari-skill-memory/tests/test_ancestor_scope.py`（3 本の兄弟
ブランチ間で汚染が起きない）。

決定性の回帰が混入した場合:

1. 期待するツリーシェイプを固定する回帰テストを最初に書く。
2. 変更セットを二分探索する。ほとんどの場合、`dict` の順序依存または
   `id(...)` に依存するハッシュが原因です。
3. 該当ドメインのスイート (memory、BFTS など) にテストを追加する。

### 合成チェックポイントフィクスチャ

GUI と `/api/v1` のリーダーテストはチェックポイントを同梱しません — 生成します。
`ari-core/tests/fixtures/gui_refresh/` には純 Python のファクトリが 2 つあります:

- `run_fixture_factory.py` — `make_run_checkpoint(dest, nodes=N, seed=S)` が
  実行チェックポイントを書き出します。`tree.json`、`nodes_tree.json`、
  `results.json` は本物の `ari.checkpoint.save_tree_json` /
  `save_nodes_tree_json` / `save_results_json` を経由するため、整形が本番
  ライターとバイト単位で一致します。`experiment.md`、`idea.json`、
  `meta.json`、`cost_trace.jsonl` は対応する `save_*_json` ヘルパーが存在
  しないため直接書き出されます。オプションの `paper` / `review` /
  `ors` / `ear` の結果レイヤーはすべて既定で OFF です。
- `rqgm_fixture_factory.py` — `make_rqgm_checkpoint(dest, nodes=10, epochs=2,
  ...)` はまずベースファクトリを呼び、その上に決定論的な RQGM ガバナンス
  サーフェス (ハッシュチェーンされた transition / audit ログ、registry の
  ロールアップ、prompt 本体、node metrics のセンチネル) を重ねます。ハッシュ
  とステートのヘルパーは再実装せず本物の `ari.rqgm` から import しています。

使う際に効いてくる性質が 3 つあります。

**何もコミットしません。** どちらのファクトリも呼び出し側が渡したディレクトリ
(全消費側で `tmp_path`) に生成するため、古くなっていくフィクスチャデータが
リポジトリに残りません。

**決定性 (P2)。** すべての値は固定リテラルか、シードから `hashlib` で導出した
ものです。`random` は一度も import されず、タイムスタンプは
`datetime.now()` ではなくリテラル `2026-07-23T00:00:00Z` への固定演算です。
同じ `(nodes, seed)` はバイト同一のファイルを生み、
`ari-core/tests/test_gui_baseline_run_fixtures.py` がそれを直接検証しています。

**破損モードが堅牢性の入力です。** `corrupt=` はまず完全に妥当なチェックポイント
を書き、その後ちょうど 1 箇所だけを壊すので、テストは一度に 1 つの失敗形状だけを
切り出せます: `"truncated_jsonl"` は `cost_trace.jsonl` の最終行を途中で切り、
`"invalid_json"` は `tree.json` の末尾を削り、`"partial_write"` は
`nodes_tree.json` を妥当なまま残して `tree.json` を削除します。RQGM ファクトリは
独自の 3 つ — `"broken_chain"`、`"truncated_transitions"`、`"registry_mismatch"`
— を持ちます。どちらも未知のモードは `ValueError` で拒否します。

サイズ階層は命名の慣習であって契約ではありません。ファクトリの docstring と
`ari-core/tests/fixtures/gui_refresh/README.md` は `nodes=10` / `1000` /
`10000` を small / medium / large と呼び、small 階層を「every reader must load
it (すべてのリーダーがロードしなければならない)」と述べていますが、それを強制
する仕組みはありません。`nodes` は `nodes >= 1` の検査が 1 つあるだけの素の
整数パラメータで、3 階層を実際に使うのは
`test_gui_baseline_run_fixtures.py` だけ (しかも決定性ケースには `nodes=50` を
使います)。リーダー側のスイートはアサーションに必要な数を渡すだけで、
他の `test_gui_*` 各ファイルでは `nodes=2` から `nodes=10` の範囲です。階層名は
それらのテストを読むときの略語として扱い、従うべきルールとしては読まないで
ください。なお `test_gui_baseline_run_fixtures.py` では large 階層は生成される
だけで再ロードされません。skip を掛けるための `slow` マーカーをリポジトリが
定義していないためです。

消費側はパッケージを import せず
`importlib.util.spec_from_file_location` でファイルパスからファクトリを読み込む
ため、小さなローダーヘルパーが各消費ファイルの冒頭に繰り返し置かれています。

## スキルレベルの規約

### MCP サーバーテスト

17 個の `ari-skill-*` パッケージのうち 10 個が `tests/test_server.py` を持ちます
(benchmark、coding、evaluator、hpc、idea、paper、tool-registry、transform、
vlm、web)。残りはサーフェスのファイル名が異なるか、そもそも持ちません —
`ari-skill-orchestrator/tests/test_mcp_surface.py` は名前が違うだけの同種の
ファイルです。10 個のうち 9 個は、サーバーモジュールをインプロセスで import し、
ツール関数をフィクスチャ入力で直接呼び、レスポンスの形状を検証します。多くは
`from src.server import …` で辿りますが、パッケージ化済みのスキルは
インストール済みモジュール (`ari_skill_hpc.server`) を import し、
`ari-skill-coding` は `importlib.util.spec_from_file_location` でパスからも
読み込みます。例外は `ari-skill-tool-registry` の 1 つだけで、これは意図的です:
サーフェスがブローカーであるため、その `tests/test_server.py` は `src/server.py`
を実際の stdio 子プロセスとして起動し (`PythonStdioLauncherV1` +
`StdioMCPAdapter`、実体は `ari-skill-tool-registry/src/providers.py`:514 の
`stdio_client`)、MCP セッション越しに駆動します。10 個の外側では、名前が違う
だけの同種ファイルも同じことをします: `ari-skill-orchestrator/tests/test_mcp_surface.py`
は `src/server.py` を子プロセスとして 2 回起動します — 1 回は `streamable-http`
経由 (`subprocess.Popen`、:188)、もう 1 回は stdio 経由 (`stdio_client`、:282)。
サブプロセスが起きるのはこの 2 スイートだけです。

この層が原則として workflow のゲートに委ねていることが 2 つあります。
ツールリストと `skill.yaml` の一致、および生成された `mcp.json` のドリフト検査は、
後述の「PR 時にテストされる内容」にある `contracts` workflow の
`scripts/check_skill_manifests.py` の仕事です。ただしスキル側でも自分で固定して
いるスイートがちょうど 1 つあるので、green なスキルスイートをこれらのカバーと
読まないでください — `ari-skill-orchestrator/tests/test_mcp_surface.py`:38-43 が、
ランタイムのツール名・`skill.yaml` の `tools:`・`mcp.json` の `tools`・そして
12 個のリテラル `EXPECTED` 集合がすべて同一であることを検証しています。
そして共通の MCP テストハーネスは存在しません: `mcp.testing` というモジュールは
無く (`mcp` パッケージが持つのは `cli` / `client` / `os` / `server` / `shared` /
`types`)、リポジトリ内にそれを import するコードもありません。各スイートが独自の
フィクスチャを組みます — `ari-skill-memory/tests/conftest.py` がその型の読みやすい
リファレンスです (`tmp_path` スコープの `ARI_CHECKPOINT_DIR`、backend フィクスチャ、
署名付き call-context の発行、fake Letta クライアント)。

`list_tools()` を実際に呼ぶスイートは複数あり、何と突き合わせるかはそれぞれ
異なります。`ari-skill-coding` は `outputSchema` を持つ 5 ツールのスキーマを
検証し (`tests/test_server.py`:715-723)、`ari-skill-hpc`
(`tests/test_server.py`:40-46) と `ari-skill-idea` (`TestMcpToolRegistration`)
は特定のツール名が登録されている (hpc は登録されていない) ことを検証し、
`ari-skill-tool-registry` は稼働中のブローカー面が公開 6 操作ちょうどであること
を検証し (`tests/test_server.py`:48-50)、`ari-skill-transform` は登録済みの名前を
読みます (`tests/test_metric_contract_seam.py`:22)。いずれも期待値はテスト内の
リテラルで、マニフェストと照合するのは `ari-skill-orchestrator` だけです。

### LLM モック

LLM を呼び出すスキル (`evaluator`、`paper`、`paper-re`、`idea`、
`replicate`、`transform`、`plot` — 呼び出し元は `litellm.acompletion` を持つ
`src/planning.py` です — そして `vlm`) は、ユニットテストで
LLM をモックしなければなりません。

リファレンス例は `ari-skill-paper-re/tests/test_litellm_completer.py` で、その
手法は HTTP 傍受ではなくモジュール注入です: `_install_fake_litellm` が
`types.ModuleType("litellm")` にスタブの `acompletion` を持たせ、
`monkeypatch.setitem(sys.modules, "litellm", fake)` で差し替えるため、
ネットワークには一切出ず、completer が転送した kwargs をそのまま検証できます。
`respx` は実際の HTTP クライアント自体がテスト対象のときに使われており
(`ari-skill-memory/tests/test_letta_http_regression.py`)、`pytest-mock` も同じ
目的で CI にインストールされています。

### 依存状態フィクスチャ

スキルが `ARI_CHECKPOINT_DIR` スタイルの環境を必要とする場合、
フィクスチャで設定してください:

```python
@pytest.fixture
def ckpt(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    return tmp_path
```

モジュールインポート時に `ARI_CHECKPOINT_DIR` を設定しないでください —
値はテストにスコープされなければなりません。

## PR 時にテストされる内容

`main` への各 PR を複数の GitHub Actions ワークフローがゲートします。

**テスト** — Python のスイートは 2 つのワークフローに分かれており、互いのパスを
実行することはありません。

- `refactor-guards` は `pytest ari-core/tests/ -q` を 1 回だけ、`HOME` を作業用
  ディレクトリに差し替え、`--ignore` で 4 ファイルを除外して実行します
  (`test_letta_restart_live.py`、`test_letta_start_scripts.py`、
  `test_ollama_gpu.py`、`test_dashboard_html.py` — 最後の 1 つはどの job も
  生成しない Vite ビルドを要求するため)。`test_no_user_home_writes.py` と
  `test_public_api_boundary.py` (フェーズ 4、スキルが `ari.public.*` からのみ
  インポートしていることを保証) はこの 1 回の呼び出しに含まれて走るだけで、
  独立したステップではありません。その後 `$HOME/.ari/` が存在すれば job を落とし、
  もう 1 つの job が PR の diff から許可リスト外の新しい `~/.ari` 参照を探します。
  さらに 5 つの job (import boundaries、directory policy、complexity、ruff lint、
  dead code) はすべて**アドバイザリ**です。全部に `continue-on-error: true` が
  付き、ruff lint (素の `ruff check ari-core`) 以外は `--warning-only` も渡すため、
  findings が PR を赤くすることはありません。
  `refactoring` ブランチでも走る 2 つのワークフローのうちの 1 つです
  (ファイル内のコメントは今も「唯一」と書いていますが、後から `skill-tests` が
  同じトリガーで追加されました)。
- `skill-tests` は 7 つのスキルスイートを、パスごとに 1 プロセスで実行します
  (`paper`、`evaluator`、`web`、`plot`、`memory`、`transform`、`replicate`)。
  `-p no:randomly` 付きです。`ari-skill-coding` は**含まれておらず**、
  `ari-skill-paper-re` は `git+chz` で PaperBench を vendor するため意図的に
  除外されています。プロセス分割の理由は `pytest.ini` がスキルを `testpaths` に
  入れない理由と同じです。

**ダッシュボードフロントエンド** — `dashboard-frontend` ワークフローは
`ari-core/ari/viz/frontend` を対象とするハードゲート (`continue-on-error` なし)
で、`npm ci` → `npm run typecheck` (`tsc --noEmit`) → `npm test` (`vitest run`)
を実行します。`npm run build` と Playwright のスクリーンショット取得は意図的に
実行しません。`npm test` はスイート全体を走らせるため
`src/__tests__/v1TypesDrift.test.ts` も含まれ、これは
`ari/viz/v1/openapi.json` からメモリ上で `src/services/api/v1types.gen.ts` を
再生成してバイト一致を検証します。つまり `npm run gen:v1types` を回さずに
OpenAPI 文書を編集すると、ここで落ちます。

**ドキュメント・構造** — 3 つのワークフローがドキュメント群の同期を保ちます:

- `readme-sync` — 各ディレクトリの `## Contents` 索引が配下のファイルを
  列挙していること (`scripts/readme_sync.py --check`)。
- `docs-sync` — 全ツリー不変条件。ハードゲートは 6 つ: 宣言された `sources:`
  パスが実在すること (`check_doc_sources.py`)、`docs/i18n/landing.{en,ja,zh}.js`
  のキー集合が一致すること (`check_i18n_js.py`)、HTML サイトの i18n 整合性と
  公開バージョンピン (`check_site_i18n.py`)、手書きの `docs/*.html` 内の
  `href`/`src` がすべて解決すること (`check_doc_links.py --html-only`)、
  ルート `README.{md,ja,zh}` の見出し構造が一致すること
  (`check_readme_parity.py`)、`report/{en,ja,zh}` が構造的に並行であること
  (`report/scripts/check_i18n.py`、Gate 6)。続いて advisory (非ブロッキング) が
  3 つ: 翻訳鮮度 (`check_translation_freshness.py`)、Markdown リンク整合性
  (`check_doc_links.py` — リンクの両半分を検査するので、壊れたファイル数と
  壊れた*アンカー*数を別々に報告します)、そしてトランク状態の陳腐化
  (`check_docs_source_sync.py --warning-only`)。最後の 1 つが他では見えない唯一の
  次元をカバーします — `main` に既に入っているソースの最新コミットが、それを
  宣言する doc の `last_verified` より新しい、という状態です。その凍結ベースライン
  は空なので (`scripts/check_docs_source_sync.allow.yaml`:34、
  `known-offenders: []`)、報告される findings はすべて新規です。もう 1 つの job
  が report PDF の同期 (`sync_report_pdf.sh --check`) と VitePress サイトの
  ビルドを行います。
- `docs-change-coupling` — 差分ベース: `report/{en,ja,zh}` の言語ペアファイル
  (章・`strings.tex`・`main.tex`) を 1 言語で編集したら、同じ PR で他 2 言語にも
  反映すること (`check_report_cochange.py`、ハード)。また doc の `sources:` に
  挙げたソースが変更されたら、その doc の `last_verified` を更新すべきこと
  (`check_ref_coupling.py`、advisory)。

各 doc ゲートはリポジトリルートからローカル実行できます。例:
`python scripts/docs/check_i18n_js.py`。

**ダッシュボードの翻訳** — ダッシュボード UI は独自の 3 言語辞書
`ari-core/ari/viz/frontend/src/i18n/{en,ja,zh}.ts` を持ちますが、docs 側の
ゲートはここまで届きません: `check_i18n_js.py` が読むのは
`docs/i18n/landing.{en,ja,zh}.js` のみ (`SURFACES` タプルの要素は 1 つ) で、
キーパターン `^\s*'([^']+)'\s*:` はシングルクォートされたキーしか一致しない
ため、キーが裸の識別子である辞書は解析できません。
ルール自体は docs 側と同じです — 3 ロケールは**同一のキー集合**を宣言し、
同一ファイル内でキーを重複させてはなりません。したがって新しい UI 文字列は
同じ変更で 3 つすべてに追加する必要があります。あるロケールにあって別の
ロケールに無いキーは英語の文字列にフォールバックし、`en` にも無ければ
キー名がそのまま表示されます (`src/i18n/index.ts` の `t()`)。値は意図的に
比較しません: 固有名詞は 3 言語で同一の表記になり得るためです。

これを担保するチェックは 2 つあり、CI で走るのはそのうち 1 つだけです:

- `python scripts/check_dashboard_ux.py --fail-on-regression` — 3 つの `.ts`
  ファイルに対するキー集合の一致検査と重複検出で、同スクリプトの他の
  ダッシュボード UX 検査と同梱されています。**これを呼ぶワークフローは
  存在しない**ため、ダッシュボードの文字列に触れたら自分で実行してください。
  `scripts/quality/check_dashboard_ux.allow.yaml`
  に凍結されていない findings が 1 つでもあれば exit 1 になります。この
  許可リストに i18n エントリは 1 件も無いため、一致が壊れれば最初の実行で
  失敗します。フラグを付けない場合はレポートを出力して exit 0 です。
- `ari-core/ari/viz/frontend` から
  `npx vitest run src/i18n/__tests__/parity.test.tsx` — import した実際の辞書に
  対して同じ不変条件を検証します。`KNOWN_DRIFT` 許可リストは現在空です。
  こちらは**ゲートされています**: `dashboard-frontend` ワークフローの
  `npm test` ステップが Vitest スイート全体を走らせ、このファイルも含まれます。
  重複キーの検査は Python 側より弱く、TypeScript のオブジェクトリテラルは
  テストが読む時点で重複キーを既に畳み込んでいるためです。

現在のツリーではどちらも green です: 3 つの辞書は重複なしで同一のキー集合を
保持しています。

**ダッシュボードのアクセシビリティ** — ダッシュボードは **WCAG の適合レベルを
一切宣言していません**。この docs 群にも frontend のテスト群にも適合目標は
存在せず、ここに書かれている内容を適合の主張として読んではいけません。存在
するのは
`ari-core/ari/viz/frontend/src/__tests__/shellA11yBaseline.test.tsx` にある
凍結ベースラインの集合です。これは `dashboard-frontend` ワークフローの
`npm test` ステップの一部として CI で実行され、同時に手動で実施する cutover 前
チェックリストの 1 行でもあります (`docs/guides/gui_cutover_runbook.md` §2)。
このファイルだけを実行するには `ari-core/ari/viz/frontend` から:

```bash
npx vitest run src/__tests__/shellA11yBaseline.test.tsx
```

このファイルが固定しているのは 3 点です:

- **既に成立している正の不変条件。** `navigation` ランドマークがちょうど 1 つ、
  サイドバーの各エントリ (`gui_v2` 有効時は 15 個) が `tabindex="0"` を持つ
  ネイティブ button であること、4 つの nav グループが `aria-labelledby` で
  名前付けされていること、モバイルのハンバーガーが
  `aria-label`/`aria-controls`/`aria-expanded` を持つこと、アクティブ
  プロジェクトの `combobox` がアクセシブルな名前を持つこと。
- **`#/home` で描画したシェルに対する axe-core の violation id ベースライン。**
  現在は空リストです。アサーションは完全一致なので、新しい violation が出れば
  失敗し、*さらに* 原因を修正した後にベースラインへ id を残したままでも失敗
  します。jsdom は描画しないため `color-contrast` ルールはそこで**無効化**されて
  います — このリポジトリには色コントラストを計算する自動チェックはありません。
- **テストの `ROUTE_MARKERS` にある 18 ルートに対する `<h1>` 個数ベースライン。**
  うち 4 つは非準拠と分かった上で固定されています: `#/paperbench`、`#/workflow`、
  `#/settings` はページタイトルが `<h2>` で `<h1>` が無く、`#/idea` は見出し要素
  自体がありません。残り 14 は `<h1>` をちょうど 1 つ描画します。ここも完全一致
  なので、あるルートを修正したら同じ変更で凍結リテラルを縮める必要があります。

何もカバーしていないもの: 主要な journey をマウス無しで完了できることを end-to-end
で検証するアサーションは無く、スクリーンリーダーのチェックもありません。キーボードで
*到達できる* ことが検証されているのはサイドバー (上記のフォーカス可能な
ネイティブ button) までで、実際にキーボードで *操作する* ことが検証されているのは
`#/tree2` のテーブル
(`src/components/TreeV2/__tests__/TreeV2LargeTree.test.tsx` が roving tabindex 上で
<kbd>↓</kbd>/<kbd>→</kbd>/<kbd>Enter</kbd> を歩きます。キー対応表は
`docs/guides/dashboard.md`) だけです。モーション低減は全体で尊重されています —
`src/styles/motion.css` が `prefers-reduced-motion: reduce` の下でモーション
トークンを 0 にします — が、これはスタイルシートの性質であってテストの性質では
ありません。

WCAG 2.2 AA のゲートは、自動・手動のいずれであれ、ダッシュボード刷新の目標で
あって、このスイートが確立している性質ではありません。green な実行を AA 適合の
証拠として読まないでください。

**SPA のバンドル重量** — `scripts/check_bundle_budget.py` はダッシュボードの
ビルドを一連の gzip 予算に収めますが、これも**どのワークフローにも組み込まれて
いません**。ここでの理由は構造的です: frontend をビルドするワークフローが存在
せず、`ari-core/ari/viz/static/dist/` はコミットされず生成される成果物なので、
チェッカーが計測するディレクトリが runner 上に存在しません。
`scripts/quality/generate_quality_report.yaml` には登録*されて*いますが、この
ファイルを読む集約スクリプトは `contracts.yml` 内で `--target` モードで動きます
— 他ジョブがアップロードした JSON アーティファクトをマージするだけでチェッカー
は一切実行しません — そのため bundle budget はそこでは `unavailable` として現れ
ます。ビルドの後に自分で実行してください。手動で実施する cutover 前チェック
リストの 1 行です (`docs/guides/gui_cutover_runbook.md` §2):

```bash
cd ari-core/ari/viz/frontend && npm run build   # the checker never builds
python scripts/check_bundle_budget.py --fail-on-regression
```

`ari-core/ari/viz/static/dist/assets/*.js` の各ファイルをインプロセスで gzip し
(level 6、`mtime=0` なので同じビルドに対する再実行は同一の数値を報告します)、
各 chunk をそのクラス予算 (単位は KiB の gzip サイズ) と比較します:

| クラス | 対象 | 予算 |
|---|---|---|
| `entry` | `dist/index.html` が参照する `<script type="module">` の chunk | 100 |
| `route` | 遅延ロードされるルート chunk (`<Name>Page-<hash>.js` で判定) | 150、ただし `SettingsPage` と `WizardPage` は 50 に絞る |
| `shared` | その他すべての `.js` chunk — vendor 分割、ロケール辞書、共有コンポーネント | 150 |
| `total` | 全 `.js` chunk の gzip サイズの合計 | 600 |

`shared` の上限は意図的に保守的な上位集合です: 個別に予算が定められていたのは
route chunk だけで、同じ数値をそれ以外にも広げることで、分割を誤った vendor
バンドルが route クラスの外に隠れられないようにしています。`total` は目標値では
なくラチェットの天井で、chunk ごとの予算では見えない唯一の失敗モード — 多数の
chunk に重複した依存や、予算未満の新規 chunk が大量に増える事象 — のために存在
します。

ブラウザ側の指標 (LCP・INP・CLS) は意図的にゲートして**いません**: jsdom は描画
せず、共有 runner は pass/fail 予算には騒がしすぎるためです。したがってバンドル
の green な実行は体感性能について何も述べていません。その半分は固定マシン上の
手動プロファイルで、リリースのエビデンスに記録します。

終了コードの規約は `scripts/quality` ファミリーの他と同じです。素の実行はレポート
を出力して exit 0。`--fail-on-regression` は
`scripts/quality/check_bundle_budget.allow.yaml` に凍結されていない findings が
1 つでもあれば exit 1 になりますが、このファイルは存在しません — 凍結が必要に
なった予算がこれまで無く、allow ファイルが無ければ許可リストは空なので、予算
超過の chunk は最初の実行で失敗します。`dist/assets` が無い場合は exit 2 です。
ビルドの不在は予算の回帰ではなく環境の問題だからです。

予算そのものは `scripts/quality/check_bundle_budget.yaml` にあります — dist の
パス、route chunk の正規表現、4 つのクラス予算、そしてルートごとの上書きです。
すべてのキーは省略可能で、チェッカーはコード内の既定値として同じ値を持っている
ため、この YAML の存在意義は「予算の変更をコード編集ではなくレビュー可能な 1 行
の diff にする」ことだけです。調整はスクリプトではなくこちらで行ってください。

**テストカバレッジ — 既知のギャップ (known gap)。** このリポジトリには、
コードベースのどちらの側についても「スイートが実際にどれだけ実行しているか」を
計測する仕組みがありません。`ari-core/ari/viz/frontend/vitest.config.ts` に
`coverage` ブロックはなく、`package.json` の `test` は素の `vitest run` で、
カバレッジ用のスクリプトも devDependencies 内のカバレッジプロバイダも
ありません — `@vitest/coverage-v8` は `package-lock.json` に vitest 自身の
optional な peer dependency として現れるだけなので、`vitest run --coverage` は
まずそれを導入しないと動きません。Python 側も同様に未計測です:
`pytest.ini` は `--cov` を設定しておらず、ARI のどのパッケージも `pytest-cov` に
依存していません。どちらについても、カバレッジのベースラインが記録されたことは
一度もありません。

ダッシュボード刷新の際に目標として 2 つの数値が設定されましたが、実装されません
でした。ここではポリシーとしてではなく**既知のギャップ (known gap)** として
記録します。green なスイートはそのどちらの証拠でもありません: 純ロジック層の
frontend について line/branch カバレッジ 90%、そして全体のカバレッジは最初の
計測でベースラインを取り、そこから 80% に向けてラチェットし、低下は回帰として
扱う、というものです。

どちらの数値も、意味を持つ前に 2 つのことを片付ける必要があります。第 1 に、
90% の目標が挙げた層 — reducer、serializer、API wrapper、config resolver
adapter — は、このコードには部分的にしか対応しません。`src/services/api/` は
API wrapper の層として実在します。しかし frontend に reducer は 1 つもなく
(`reducer` は大文字小文字を問わず `src/` 配下のどこにも現れません)、serializer
モジュールもなく (`src/` 配下で `serializ` に一致するのは
`services/api/client.ts` と `hooks/useRunEvents.ts` のコメント 2 箇所だけです)、
config resolver は Python です — `ari-core/ari/config/resolver.py` で、frontend
の adapter 経由ではなく HTTP 越しに到達します。第 2 に、ラチェットには保存された
ベースラインと、それに突き合わせる何かが要ります。`dashboard-frontend`
ワークフローによって frontend のスイートには走る場所ができましたが、実行するのは
`npm test` であって `npm test -- --coverage` ではなく、ベースラインファイルは
どちらの半分にもコミットされていません — 場所はできても、計測はまだありません。

## 回帰テストの書き方

パターン:

1. `assert <observed> == <expected>` で失敗するテストとしてバグを捉える。
2. まずテスト単体を先にランドする (red コミット)。
3. その上に修正をランドする。

これにより「期待していたこと」と「どう修正したか」が `git log` で分離され、
修正の後続リライトにも耐えられます。

## 関連

- `pytest.ini` — リポジトリ全体の設定。
- `docs/concepts/architecture.md` — ランタイムアーキテクチャ (適切なテストレイヤーを選ぶ際に役立ちます)。
- `docs/reference/public_api.md` — 境界テストはこのサーフェスに対してインポートを確認します。
