---
sources:
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-tool-registry/src/server.py
    role: implementation
last_verified: 2026-08-02
---

# MCP ツールリファレンス

ARI には 15 の MCP サーバが付属しています（`ari-skill-*` パッケージごとに 1 つ）。
このページはエージェントが呼び出せるすべてのツールのフラットなカタログです。
各スキルの詳細は個別の `README.md` を参照してください。セクション
[skills.md](skills.md) では責務ごとにグループ分けされています。

`mcp.json`（各スキルの `pyproject.toml` の隣に配置）がツール*名前*の信頼できる
情報源です。`@mcp.tool()` で装飾された関数（または古いスキルの
`@server.list_tools()` エントリ）が引数と戻り値の形式を定義します。

"LLM" 列は **P2 例外** のツールを示します — LLM を呼び出すため
バイト単位での決定論性がありません。

## ari-skill-benchmark — 型付き統計（決定論的）

| ツール | 用途 | LLM |
|---|---|:---:|
| `analyze_results` | inline または digest-bound CSV / JSON / npy の unit 付き要約 | ✗ |
| `statistical_test` | effect size、CI、assumption、多重比較補正付き推論 | ✗ |
| `compare_runs` | environment/provenance-aware な scalar run ranking | ✗ |

## ari-skill-coding — コードの作成 + 実行

`skill.yaml` が canonical tool contract で、`mcp.json` はそこから生成されます。

| ツール | 用途 | LLM |
|---|---|:---:|
| `write_code` | atomic かつ traversal/symlink-safe な workspace write と source digest | ✗ |
| `run_code` | digest-bound immutable script snapshot、bounded execution、完全 log artifact | ✗ |
| `run_bash` | local/container identity 付きの明示 shell execution と完全 log artifact | ✗ |
| `emit_results` | 有限値、unit、provenance、検証済みexecution attempt/receipt、再hash済みartifact digest を持つ canonical `ari.measurement-set/v1` を出力 | ✗ |
| `read_file` | symlink-safe な bounded/paginated workspace read | ✗ |

## ari-skill-evaluator — LLM メトリクス抽出

| ツール | 用途 | LLM |
|---|---|:---:|
| `make_metric_spec` | LLM が `experiment.md` からメトリクス定義を抽出；実行レベルの `metric_contract` も出力 → `{checkpoint}/metric_contract.json`。mint-once: claims を含む契約がすでに永続化されている場合、呼び出しは再抽出せず、その契約を `contract_frozen: true` 付きでそのまま返します（scoring guide などノードごとの spec フィールドは呼び出しごとに計算） | ✓ |
| `claim_evidence_hard_gate` | 決定論的な主張/証拠ハードゲート（実行データの忠実性）；strict モードでは final フェーズで finalize をブロック | ✗ |
| `evidence_grounded_semantic_review` | 非ブロッキングの証拠に基づくセマンティック査読；`paper_refine` 向けに `suggested_revisions` を出力 | ✓ |

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

`generate_ideas` は単一の安定した出力契約の背後に 2 つのエンジンを持ちます。
デフォルトは軽量な再実装ディスカッションループです。オプトインの実 VirSci
vendor-wrap エンジン（`ARI_IDEA_VIRSCI_REAL=1`）は、ライブ Semantic Scholar
スナップショット上で VirSci 本来のマルチエージェント機構を実行し、依存関係の
欠落 / 実行時エラーが発生した場合は再実装ループにデグレードします。`idea.json`
契約はどちらの経路でも同一で、辿った経路は `virsci_integration_status`
（`real_wrap` または `reimpl: ...`）で報告されます。

## ari-skill-memory — 祖先スコープのノードメモリ

このスキルは `src/server.py` の FastMCP `@mcp.tool()` デコレータを使用します。
静的な `mcp.json` は古く（ノードスコープの 4 ツールのみ記載）なっていますが、
以下のデコレートされた関数はすべて実行時に公開**されます**。

| ツール | 用途 | LLM |
|---|---|:---:|
| `add_memory` | 現在のノードのメモリにエントリを追加 | ✗ |
| `search_memory` | 現在のノード + 祖先をまたいだ埋め込みランク検索 | ✗（サーバサイド埋め込み） |
| `get_node_memory` | 現在のノードのすべてのエントリ | ✗ |
| `get_experiment_context` | Letta コアメモリから安定した実験レベルの事実を取得 | ✗ |
| `add_experiment_result` | 型付き experiment_result を記録（CoW：自ノードのみ） | ✗ |
| `add_failure_case` | 型付き failure_case を記録（CoW：自ノードのみ） | ✗ |
| `add_procedure_memory` | 再利用可能な手順を記録（CoW：自ノードのみ） | ✗ |
| `add_reflection` | リフレクションを記録（CoW：自ノードのみ；論文の主張には使用不可） | ✗ |
| `add_reproducibility_event` | 追記専用の再現性ステータスイベントを追加（CoW：自ノードのみ） | ✗ |
| `search_research_memory` | 種類 / 成果物の有無でフィルタした祖先スコープの型付き検索 | ✗ |
| `get_verified_context` | 論文 / 図の利用向けの成果物に裏付けられた再現性対応コンテキスト | ✗ |
| `audit_memory` | 記録された来歴（sha256）をチェックポイントのディスク上と照合検証 | ✗ |
| `consolidate_node_memory` | ノード終了時に node_report から型付きメモリを導出 + 書き込み（CoW：自ノード） | ✗ |

このスキルは設計ドキュメントで「LLM 呼び出しなし」と明示しています —
`ari-skill-memory/README.md` を参照してください。record は append-only で、公開
surface に node/record 単位の削除操作はありません。詳細は
[研究メモリ契約](memory_contract.md) を参照してください。

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
| `compile_paper` | 固定コマンド・資源制限・完全ログ付き LaTeX コンパイル | ✗ |
| `check_format` | LaTeX フォーマット検証 | ✗ |
| `write_paper_iterative` | native evidence から `PaperBuildV1` 証跡付きで全文を執筆 | ✓ |
| `review_compiled_paper` | 明示 rubric による独立テキスト査読と raw response 保存 | ✓ |
| `link_paper_claims` | `% CLAIM:Cx:NCx` アンカーを science_data の主張と照合し、`paper_claim_links` を構築（決定論的） | ✗ |
| `paper_refine` | `% CLAIM:Cx:NCx` アンカーを保持しつつ提案された修正を適用（決定論的置換 + 境界付き LLM の検索/置換） | ✓ |
| `list_rubrics` | 利用可能な査読ルーブリック | ✗ |
| `inject_code_availability` | v0.7.0 — 論文に `\codedigest{...}` ブロックを追記 | ✗ |
| `merge_reviews` | 独立／evidence-grounded 査読を変更せず構造的に合成 | ✗ |
| `finalize_paper_build` | evidence binding を再計算し TeX/BibTeX/PDF を fail-closed で固定 | ✗ |

旧 per-section tool は削除済みです。移行仕様は英語版の
[Paper build contract](../../reference/paper_build_contract.md) を参照してください。

## ari-skill-paper-re — PaperBench 再現性 (v1.0.0)

| ツール | 用途 | LLM |
|---|---|:---:|
| `fetch_code_bundle` | ref + sha256 でコードバンドルを取得して検証 | ✗ |
| `build_reproduce_sh` | Stage 1 — vendor BasicAgent / IterativeAgent ロールアウトが `reproduce.sh` を書く | ✓ |
| `run_reproduce` | Stage 2 — `local` / `docker` / `apptainer` / `singularity` / `slurm` サンドボックスで `reproduce.sh` を実行 | ✗ |
| `grade_with_simplejudge` | Stage 3 — LLM がルーブリックの葉に対して実行済みサブミッションをグレーディング | ✓ |

### v0.8.0 新フィールド（Stage 1）

| ツール | 新しい引数 |
|---|---|
| `build_reproduce_sh` | `container_image`（immutable image の単一フィールド。deprecated `apptainer_image` alias は v1.0 で削除） |

### v0.8.0 新フィールド（Stage 2）

| ツール | 新しい引数 |
|---|---|
| `run_reproduce` | `container_image`（immutable なローカル SIF、完全な Docker `sha256:<image-id>`、または digest 固定 remote reference。mutable tag と alias は拒否） |

フェイルラウド前提条件: docker デーモン / apptainer バイナリ /
sbatch / パーティションが欠落している場合、ローカル CPU への黙った
フォールバックではなく `RuntimeError` を発生させます。レガシーフォールバックに
host-local fallback は存在しません。型付きGPU要求は
黙って削除されず、矛盾・非対応resourceは実行前に失敗します。
[environment_variables.md](environment_variables.md#paperbench-reproduction-phase-stage-2) を参照。
SLURM経路は共通`JobRequestV1` submit/status/log/cancel lifecycleと
`--export=NIL` clean environmentを使います。

### v0.8.0 新フィールド（Stage 3）

| ツール | 新しい引数 |
|---|---|
| `grade_with_simplejudge` | `code_only`（verified reproduction のルーブリックを Code Development 葉のみに限定する明示的 scope。reproduction record がなければ score なしで失敗） |

3 つのステージすべてを単一の呼び出し語彙でチェーンするインプロセス Python
サーフェスについては、
[`api_paperbench.md` § Bridge contract](api_paperbench.md#bridge-contract-in-process-python-surface)
を参照してください。

## ari-skill-plot — 図生成

| ツール | 用途 | LLM |
|---|---|:---:|
| `render_figure` | source/spec/environment/artifact digest を持つ閉じた決定論的 renderer | ✗ |
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

## ari-skill-tool-registry — 科学ツール連合（デフォルトOFF）

| ツール | 用途 | LLM |
|---|---|:---:|
| `discover` | immutable catalogをbounded paginationで検索 | ✗ |
| `describe` | schema、provenance、admission、limitationをpage取得 | ✗ |
| `invoke` | exactなadmitted `tool_ref`をlive/record/replayで実行 | ✗ |
| `get_status` | descriptorに束縛されたasync handleをpoll | ✗ |
| `get_result` | async最終結果を取得・正規化 | ✗ |

source syncと科学的制約は [tool_registry.md](tool_registry.md) を参照してください。

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
| `search_papers` | 一つの固定provider、型付きrecord/live/replay結果 | ✗ |
| `web_search` | snapshot契約下のDuckDuckGo検索 | ✗ |
| `fetch_url` | SSRF制御URL → untrusted text | ✗ |
| `walk_citations` | partial provenance付きbounded citation graph | ✗ |
| `rerank_retrieval_records` | 明示的typed-record reranker | ✓ |
| `search_arxiv` | deprecated arXiv alias | ✗ |
| `search_semantic_scholar` | deprecated Semantic Scholar alias | ✗ |
| `collect_references_iterative` | deprecated stochastic検索・選択loop | ✓ |
| `set_retrieval_backend` | deprecated pinned-provider selector | ✗ |
| `list_uploaded_files` | checkpoint upload一覧 | ✗ |
| `read_uploaded_file` | traversal/output制限付きupload読込 | ✗ |

[検索契約とnetwork policy](retrieval_contract.md)を参照してください。

## 関連ドキュメント

- `docs/reference/skills.md` — 各スキルのナラティブな説明（責務、環境変数、例）。
- `docs/reference/environment_variables.md` — 環境変数ごとのリファレンス。
- 各スキルの `mcp.json` — 標準的なツール名一覧。
- 各スキルの `src/server.py` の `@mcp.tool()` / `@server.list_tools()` — 標準的な引数シグネチャ。
