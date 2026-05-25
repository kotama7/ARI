---
sources:
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-hpc/src/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
last_verified: 2026-05-25
---

# MCP ツールリファレンス

ARI には 14 の MCP サーバが付属しています（`ari-skill-*` パッケージごとに 1 つ）。
このページはエージェントが呼び出せるすべてのツールのフラットなカタログです。
各スキルの詳細は個別の `README.md` を参照してください。セクション
[skills.md](skills.md) では責務ごとにグループ分けされています。

`mcp.json`（各スキルの `pyproject.toml` の隣に配置）がツール*名前*の信頼できる
情報源です。`@mcp.tool()` で装飾された関数（または古いスキルの
`@server.list_tools()` エントリ）が引数と戻り値の形式を定義します。

"LLM" 列は **P2 例外** のツールを示します — LLM を呼び出すため
バイト単位での決定論性がありません。

## ari-skill-benchmark — 統計 + プロット（決定論的）

| ツール | 用途 | LLM |
|---|---|:---:|
| `analyze_results` | CSV / JSON / npy からのサマリ統計 | ✗ |
| `plot` | 固定スキーマからの決定論的 matplotlib 図 | ✗ |
| `statistical_test` | 仮説検定（t 検定、Mann-Whitney など） | ✗ |

## ari-skill-coding — コードの作成 + 実行

`mcp.json` にはツールが記載されていません。実際のツール一覧は
`src/server.py` の `@server.list_tools()` から提供されます。

| ツール | 用途 | LLM |
|---|---|:---:|
| `write_code` | ノードの work_dir にファイルを書き込む | ✗ |
| `run_code` | タイムアウト + キャプチャ付きでスクリプトを実行 | ✗ |
| `run_bash` | アドホックな bash コマンド | ✗ |
| `emit_results` | 評価器向けに `metrics` + `has_real_data` を出力 | ✗ |
| `read_file` | エージェントが以前に書いたファイルを読み込む | ✗ |

## ari-skill-evaluator — LLM メトリクス抽出

| ツール | 用途 | LLM |
|---|---|:---:|
| `make_metric_spec` | LLM が `experiment.md` からメトリクス定義を抽出 | ✓ |
| （内部）`evaluate` | スペックに対してノード成果物をスコアリング | ✓ |

## ari-skill-hpc — SLURM + Singularity

`mcp.json` は空のリストです。ツールは `src/server.py` の `@server.list_tools()`
から提供されます。

| ツール | 用途 | LLM |
|---|---|:---:|
| `slurm_submit` | パーティション / 時間 / CPU 数 / ノード数 / GPU 数を明示して sbatch | ✗ |
| `job_status` | squeue + sacct 検索 | ✗ |
| `job_cancel` | 実行中のジョブを scancel | ✗ |
| `run_bash` | ダイレクトな bash コマンド（ローカルまたは SSH 経由） | ✗ |
| `singularity_build` | 定義ファイルから SIF をビルド | ✗ |
| `singularity_run` | SIF 内でコマンドを実行 | ✗ |
| `singularity_pull` | リモート URI から SIF を取得 | ✗ |
| `singularity_build_fakeroot` | Fakeroot ビルド（特権デーモン不要） | ✗ |
| `singularity_run_gpu` | `singularity_run` の GPU バリアント | ✗ |

## ari-skill-idea — 文献調査 + アイデア生成

| ツール | 用途 | LLM |
|---|---|:---:|
| `survey` | arXiv + Semantic Scholar 検索；純粋な HTTP | ✗ |
| `generate_ideas` | LLM が調査 + コンテキストからランク付きアイデア候補を生成 | ✓ |

## ari-skill-memory — 祖先スコープのノードメモリ

| ツール | 用途 | LLM |
|---|---|:---:|
| `add_memory` | 現在のノードのメモリにエントリを追加 | ✗ |
| `search_memory` | 現在のノード + 祖先をまたいだ埋め込みランク検索 | ✗（サーバサイド埋め込み） |
| `get_node_memory` | 現在のノードのすべてのエントリ | ✗ |
| `clear_node_memory` | 現在のノードのエントリを削除（CoW；祖先は変更なし） | ✗ |

このスキルは設計ドキュメントで「LLM 呼び出しなし」と明示しています —
`ari-skill-memory/README.md` を参照してください。

## ari-skill-orchestrator — 再帰的 ARI ランナー

| ツール | 用途 | LLM |
|---|---|:---:|
| `run_experiment` | 子 ARI 実行を起動 | ✗ |
| `get_status` | 子実行のステータス | ✗ |
| `list_runs` | 既知のすべての実行 | ✗ |
| `get_paper` | 実行の生成 LaTeX / PDF | ✗ |

## ari-skill-paper — LaTeX 論文執筆

| ツール | 用途 | LLM |
|---|---|:---:|
| `list_venues` | 利用可能な LaTeX テンプレート（ACM / NeurIPS / SC / ICPP / arXiv） | ✗ |
| `get_template` | venue のテンプレートを取得 | ✗ |
| `generate_section` | LLM がセクション（序論、手法など）を執筆 | ✓ |
| `compile_paper` | pdflatex コンパイル | ✗ |
| `check_format` | LaTeX フォーマット検証 | ✗ |
| `review_section` | LLM がルーブリックで 1 セクションを査読 | ✓ |
| `revise_section` | LLM が査読フィードバックを使って書き直し | ✓ |
| `write_paper_iterative` | 生成 / 査読 / 修正ループをエンドツーエンドで駆動 | ✓ |
| `review_compiled_paper` | コンパイル済み PDF に対する最終パス査読（図は VLM に委譲） | ✓ |
| `list_rubrics` | 利用可能な査読ルーブリック | ✗ |
| `inject_code_availability` | v0.7.0 — 論文に `\codedigest{...}` ブロックを追記 | ✗ |
| `merge_reviews` | v0.7.0 — ルーブリック査読 + VLM 査読の JSON を統合 | ✗ |

## ari-skill-paper-re — PaperBench 再現性 (v0.7.0)

| ツール | 用途 | LLM |
|---|---|:---:|
| `fetch_code_bundle` | ref + sha256 でコードバンドルを取得して検証 | ✗ |
| `build_reproduce_sh` | Stage 1 — vendor BasicAgent / IterativeAgent ロールアウトが `reproduce.sh` を書く | ✓ |
| `run_reproduce` | Stage 2 — `local` / `docker` / `apptainer` / `singularity` / `slurm` サンドボックスで `reproduce.sh` を実行 | ✗ |
| `grade_with_simplejudge` | Stage 3 — LLM がルーブリックの葉に対して実行済みサブミッションをグレーディング | ✓ |

### v0.8.0 新フィールド（Stage 1）

| ツール | 新しい引数 |
|---|---|
| `build_reproduce_sh` | `container_image`（レガシーの `apptainer_image` を置き換え / 上位互換；後方互換のため両方受け付け） |

### v0.8.0 新フィールド（Stage 2）

| ツール | 新しい引数 |
|---|---|
| `run_reproduce` | `container_image`（docker / apptainer / singularity サンドボックスで有効；エイリアス `pb-env` / `pb-reproducer` は `scripts/build_pb_images.sh` でビルドされた vendor の `image:latest` タグに解決） |

フェイルラウド前提条件: docker デーモン / apptainer バイナリ /
sbatch / パーティションが欠落している場合、ローカル CPU への黙った
フォールバックではなく `RuntimeError` を発生させます。レガシーフォールバックに
戻すには `ARI_PHASE1_ALLOW_FALLBACK=1`、GRES フラグの黙った削除に戻すには
`ARI_SLURM_ALLOW_NO_GRES=1` を設定してください。
[environment_variables.md](environment_variables.md#paperbench-reproduction-phase-stage-2) を参照。
型付き（`gpu_type` / `--gres=gpu:TYPE:N`）と型なし
（`--gpus-per-task`）の GPU リクエストの混在は自動的に型付き形式に
正規化されます — SLURM 24.05 は混在形式を拒否します。

### v0.8.0 新フィールド（Stage 3）

| ツール | 新しい引数 |
|---|---|
| `grade_with_simplejudge` | `code_only`（ルーブリックを Code Development 葉のみに限定。vendor の `paperbench/grade.py:109-112` を踏襲。`reproduce.log` が存在しない場合に自動有効化され、Stage 1 のみの実行が系統的にゼロにならないようにする） |

3 つのステージすべてを単一の呼び出し語彙でチェーンするインプロセス Python
サーフェスについては、
[`api_paperbench.md` § Bridge contract](api_paperbench.md#bridge-contract-in-process-python-surface)
を参照してください。

## ari-skill-plot — 図生成

| ツール | 用途 | LLM |
|---|---|:---:|
| `generate_figures` | `nodes_tree.json` から決定論的 matplotlib 図を生成 | ✗ |
| `generate_figures_llm` | LLM が matplotlib コードを書いて実行 | ✓ |

## ari-skill-replicate — ルーブリック自動生成 (v0.7.0)

| ツール | 用途 | LLM |
|---|---|:---:|
| `generate_rubric` | 二段階（スケルトン + サブツリー）PaperBench ルーブリック合成 | ✓ |
| `audit_rubric` | LLM が曖昧 / 検証不可能 / 重複した基準の葉を監査 | ✓ |

### `generate_rubric` — venue 条件付きテンプレート（未リリース）

`generate_rubric` はオプションの `paperbench_rubric_id` 引数を受け付け、
`ari-core/config/paperbench_rubrics/<id>.yaml` から venue 条件付き
テンプレートを選択します。`ari-skill-paper` のピアレビューパスがすでに使用している
`reviewer_rubrics/` の venue パターンを踏襲しています。

| 引数 | 型 | デフォルト | 効果 |
|---|---|---|---|
| `paperbench_rubric_id` | `str` | `""` | 空 = バンドル済みプロンプトをそのまま使用（後方互換）。それ以外の場合は YAML テンプレートをロードし、`prompt_overrides.system_hint` / `prompt_overrides.leaf_style` をスケルトン + サブツリープロンプトに注入。 |

同梱テンプレート:

| `id` | `mode` | トップレベル構造 |
|---|---|---|
| `generic` | `agent_benchmark` | 科学的貢献ごとに分解（現在のデフォルト動作）。 |
| `sc` | `paper_audit` | HPC 論文用の 6 固定監査軸（環境 / データ / 実行 / 図 / スケーリング / 結論）。 |
| `neurips` | `paper_audit` | NeurIPS 再現性チェックリストに基づく 6 軸（主張 / セットアップ / コード+データ / 統計 / 倫理 / 図）。 |
| `nature` | `paper_audit` | 実験系論文用の 5 軸（材料 / プロトコル / 統計 / データ / 倫理）。 |

`paper_audit` モードは `two_stage=True` が必要です。単一パスパスで
`paper_audit` テンプレートがリクエストされた場合、ジェネレータはエラーを返します
（単一パスプロンプトは固定軸制約を満たせないため）。YAML スキーマと
オーサリングガイドは [`rubric_schema.md`](rubric_schema.md#venue-conditioned-templates)
を参照してください。

## ari-skill-transform — ツリー走査 + EAR パイプライン

`mcp.json` にはツールが記載されていません（ファイルは内部専用）。
`src/server.py` の `@mcp.tool()` デコレータが正式です。

| ツール | 用途 | LLM |
|---|---|:---:|
| `nodes_to_science_data` | BFTS ツリーを走査して方法論 + 知見を抽出 | ✓ |
| `generate_ear` | BFTS 成果物から `{checkpoint}/ear/` をビルド | ✗ |
| `curate_ear` | `ear/` → `ear_published/` + manifest.lock に昇格 | ✗ |
| `publish_ear` | `local-tarball` / `ari-registry` / `zenodo` / `gh` にプッシュ | ✗ |
| `promote_ear` | `staged` → `unlisted` / `public` に昇格 | ✗ |

## ari-skill-vlm — 図 / 表の査読（VLM）

`mcp.json` にはツールが記載されていません。スキルは内部の査読ヘルパーのみを公開
します。

| ツール | 用途 | LLM |
|---|---|:---:|
| `review_figure` | VLM が画像 + キャプションを読んで批評を返す | ✓（ビジョン） |
| `review_table` | VLM がテーブルを査読 | ✓（ビジョン） |
| `review_paper_figures` | 論文ディレクトリ内のすべての図をバッチ査読 | ✓（ビジョン） |

## ari-skill-web — 検索 + 取得

| ツール | 用途 | LLM |
|---|---|:---:|
| `web_search` | DuckDuckGo（API キー不要） | ✗ |
| `fetch_url` | URL → 読み取り可能なテキスト | ✗ |
| `search_arxiv` | arXiv API | ✗ |
| `search_semantic_scholar` | Semantic Scholar API | ✗ |
| `collect_references_iterative` | シード論文から引用グラフを辿る | ✗ |

## 関連ドキュメント

- `docs/skills.md` — 各スキルのナラティブな説明（責務、環境変数、例）。
- `docs/reference/environment_variables.md` — 環境変数ごとのリファレンス。
- 各スキルの `mcp.json` — 標準的なツール名一覧。
- 各スキルの `src/server.py` の `@mcp.tool()` / `@server.list_tools()` — 標準的な引数シグネチャ。
