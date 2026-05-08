# ARI アーキテクチャ

## ARI の機能

ARI はエンドツーエンドの自律研究システムです。平文の研究目標を与えると、以下を行います:

1. **調査** - 先行研究の調査（学術データベース）
2. **生成** - マルチエージェント討論による研究仮説の生成（VirSci）
3. **探索** - Branch-and-Frontier Tree Search (BFTS) による最適な実験構成の探索
4. **実行** - 実際のハードウェア上での実験実行（ラップトップ、SLURM、PBS、LSF）
5. **評価** - 各実験の査読評価（LLM が科学的品質スコアを付与）
6. **分析** - 完全な実験ツリーの分析: ハードウェア情報、手法、アブレーション結果の抽出
7. **図表生成** - 出版品質の図表生成（LLM がデータから matplotlib コードを記述）
8. **論文執筆** - 引用付き完全な LaTeX 論文の執筆
9. **査読** - LLM が査読者として論文を審査
10. **再現性検証** - 論文テキストのみから実験を再実行し再現性を検証

ドメイン知識はハードコードされていません。同じパイプラインが HPC ベンチマーク、ML ハイパーパラメータチューニング、化学最適化、その他あらゆる測定可能な現象に対して動作します。

---

## システム概要

```
┌────────────────────────────────────────────────────────────────┐
│                         User Interface                         │
│                   experiment.md  /  CLI  /  API                │
└────────────────────────────────┬───────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────┐
│                          ari-core                              │
│                                                                │
│  ┌─────────────────┐   ┌─────────────────┐                    │
│  │  BFTS           │   │  ReAct Loop     │                    │
│  │  (tree search)  │──▶│  (per node)     │                    │
│  └─────────────────┘   └────────┬────────┘                    │
│                                 │                              │
│  ┌──────────────────────────────▼──────────────────────────┐  │
│  │            MCP Client (async tool dispatcher)           │  │
│  └──────────────────────────────┬──────────────────────────┘  │
└─────────────────────────────────┼──────────────────────────────┘
                                  │ MCP protocol (stdio/HTTP)
     ┌────────────────────────────┼──────────────────────────────┐
     │                            │                              │
┌────▼──────────┐  ┌─────────────▼──────┐  ┌───────────────────▼──┐
│ari-skill-hpc  │  │ari-skill-idea      │  │ari-skill-evaluator   │
│ slurm_submit  │  │ survey             │  │ make_metric_spec     │
│ job_status    │  │ generate_ideas     │  │ (scientific_score)   │
│ run_bash      │  │ (VirSci MCP)       │  │                      │
└───────────────┘  └────────────────────┘  └──────────────────────┘

Post-BFTS Pipeline (workflow.yaml):
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ari-skill-       │  │ari-skill-plot    │  │ari-skill-paper   │
│transform        │  │ generate_figures │  │ write_paper      │
│ nodes_to_       │  │ _llm (LLM writes │  │ review_compiled  │
│ science_data    │  │  matplotlib)     │  │ reproduce_from   │
│ (LLM analysis)  │  │                  │  │  _paper          │
└─────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## 完全なデータフロー

```
experiment.md
  (研究目標のみ — 最低3行)
    │
    ▼
[ari-skill-idea: survey]
  arXiv / Semantic Scholar キーワード検索
  戻り値: 関連論文の要旨
    │
    ▼
[ari-skill-idea: generate_ideas]  ← VirSci マルチエージェント討論
  複数のAIペルソナが研究課題について議論
  出力: hypothesis, primary_metric, evaluation_criteria
    │
    ▼
BFTS ルートノード作成
    │
    ▼ (各ノードについて繰り返し、最大 ARI_MAX_NODES、ARI_PARALLEL 同時実行)
┌──────────────────────────────────────────────────────────────────┐
│  ReAct Loop (ari/agent/loop.py)                                  │
│                                                                  │
│  1. LLM が MCP レジストリからツールを選択                           │
│  2. ツールを実行 (run_bash / slurm_submit / job_status / ...)     │
│  3. SLURM ジョブの場合: COMPLETED まで自動ポーリング（ステップ予算なし）│
│  4. LLM が stdout を読み → 実験コードを生成 → 投入                  │
│  5. LLM が出力からメトリクスを抽出 → JSON を返却                    │
│                                                                  │
│  メモリ: 結果サマリーを祖先チェーンメモリに保存                      │
│  子ノード: 祖先メモリから過去の結果を検索                            │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
[LLMEvaluator] (ari/evaluator/llm_evaluator.py)
  入力:  ノードの成果物（stdout、ログ、スクリプト）
  出力: {
    has_real_data: bool,
    metrics: {key: value, ...},       ← 抽出された数値
    scientific_score: float 0.0-1.0,  ← LLM 査読品質スコア
    comparison_found: bool             ← 既存手法との比較あり？
  }
  _scientific_score は metrics に格納 → BFTS ランキングを駆動
    │
    ▼
BFTS expand() (ari/orchestrator/bfts.py)
  - _scientific_score でノードをランク付け
  - スコアを子提案 LLM に渡す
  - LLM が展開呼び出しごとに 1 つの子方向を提案（改善 / アブレーション / 検証 / ドラフト / デバッグ / その他）
  - ドメインヒントなし — LLM が「改善」の意味を決定
  - v0.7.0: 親に node_report.json があるとき、プロンプトに delta_vs_parent /
    self_assessment.concerns / next_steps_hints と files added/modified を
    追加。sibling dedup は filter_nodes(for_synthesis) で絞り込み、各 sibling の
    files_changed.added を併記して同じファイルを書く direction を
    物理的に避けられるようにする。

ノード自己レポート (v0.7.0)
  ari-core/ari/orchestrator/node_report.py が mark_success / mark_failed 時に
  node_report.json を生成。記録内容:
    - files_changed (added / modified / deleted / inherited_unchanged)
      — 親と子の work_dir の sha256 diff から導出
    - original_direction (bfts.expand が child 作成時に保存、evaluator は上書き不可)
    - self_assessment.{succeeded, headline, concerns} — evaluator の axis_rationales
      から導出 (axis_score < 0.4 → concerns、0.4..0.7 → next_steps_hints、
      ≥0.7 → 採用しない)
    - build_command / run_command — work_dir 内の run_job.sh / Makefile を grep
    - artifacts[].role — 拡張子から決定論的に分類 (data_output / log / binary /
      figure / unknown)
    - migration_source ("fresh" or "auto")
  PathManager.META_FILES に node_report.json を追加してあるので、親→子の物理
  work_dir コピーで親レポートを子が継承することはない。

共通選別ヘルパー (v0.7.0)
  ari-core/ari/orchestrator/node_selection.py:
    - filter_nodes: 「このノードを下流に渡すか」の単一の判定実装。3 criteria
      (for_synthesis / for_code / for_narrative)。always_include_node_ids で
      best ノードは常に通す。50% 超 skip で warning。
    - select_source_files_for_publication: file I/O ゼロのファイル単位選別。
      deepest contributor wins。transform_data と generate_ear で同じ selection を
      共有 (FR-SS-5 contract test で固定)。
    - load_selected_sources(size_budget): file I/O 担当。transform は 16KB cap、
      generate_ear は cap なし。
    │
    ▼ (ARI_MAX_NODES 到達後)
nodes_tree.json  (全ノード: メトリクス、成果物、メモリ、親子リンク)
    │
    ▼
[workflow.yaml Post-BFTS パイプライン]

  ステージ 1: transform_data  (ari-skill-transform)
    全ツリーの BFS 走査（ルート → リーフ）
    LLM が全ノードの成果物を読み取り（stdout、ログ、生成コード）
    LLM が抽出: ハードウェアスペック、手法、主要な知見、比較
    出力: science_data.json  { configurations, experiment_context, per_key_summary }

  ステージ 2: search_related_work  (ari-skill-web)  [ステージ 1 と並列]
    LLM 生成キーワード → 切替可能な検索バックエンド (Semantic Scholar / AlphaXiv / both)
    出力: related_refs.json

  ステージ 3: generate_figures  (ari-skill-plot)  [ステージ 1 の後]
    入力: 完全な science_data.json（experiment_context を含む）+ {{vlm_feedback}}
    LLM が完全な matplotlib コードを記述 → 実行 → PDF 図表を保存
    図表の種類はデータから自律的に選択（事前指定なし）
    出力: figures_manifest.json

  ステージ 3b: vlm_review_figures  (ari-skill-vlm)  [ステージ 3 の後]
    VLM が代表図 (fig_1.png) を視覚的にレビュー
    スコア < 0.7: VLM フィードバックと共に generate_figures へループバック（最大 2 反復）
    出力: vlm_figure_review.json

  ステージ 4: generate_ear  (ari-skill-transform)  [ステージ 1 の後]
    node_report 駆動の決定論的 ear/ 構築。
      - code/ = best chain の contributing ノードの files_changed.added/modified の union (verbatim)
      - data/ = checkpoint/uploads/ の verbatim ミラー (入力のみ、実験出力は含めない)
      - figures/ = checkpoint 直下の *.{pdf,png,svg,jpg,jpeg} を top-level に
      - README.md / reproduce.sh — node_reports から決定論レンダリング
      - LICENSE — publish.yaml::license の SPDX テンプレから生成 (MIT / Apache-2.0 / BSD-3-Clause / GPL-3.0 / CC-BY-4.0)
    EVOLUTION.md と _provenance.json は ARI 監査ログとして checkpoint 直下
    （ear/ の外）に書き出され、公開アーティファクトには含まれない。
    transform_data と generate_ear は同じ select_source_files_for_publication を
    共有するため、LLM が見るソースバイトと ear/code/ にパブリッシュされるバイトは
    完全一致する。ARI 内部メタデータ (tree.json, science_data.json, raw_metrics.json
    等) は ear/ にコピーされない。
    出力: ear_manifest.json, ear/ ディレクトリ, checkpoint/EVOLUTION.md,
          checkpoint/_provenance.json

  ステージ 5: write_paper  (ari-skill-paper)  [ステージ 2, 3, 4 の後]
    paper_context = experiment_context + best_nodes_metrics
    反復的セクション執筆: 下書き → LLM 査読 → 修正（最大 2 ラウンド）
    Semantic Scholar の結果から BibTeX 引用
    出力: full_paper.tex, refs.bib

  ステージ 6: review_paper  (ari-skill-paper)  [ステージ 5 の後]
    ルーブリック駆動の査読。N 名の独立した査読者エージェントを実行
    (N は ARI_NUM_REVIEWS_ENSEMBLE / rubric 既定値で制御、N=1 は単一査読)。
    N>1 のときは Area Chair メタ査読も走り、スコアを集約。
    出力: review_report.json { score, verdict, citation_ok, feedback,
          ensemble_reviews[] (N>1), meta_review{} (N>1) }

  ステージ 7: ear_curate  (ari-skill-transform: curate_ear)  [ステージ 4 の後、v0.7.0]
    {checkpoint}/ear/publish.yaml の allowlist と built-in deny list
    (.env*, secrets/**, *.pem, *.key, id_rsa, id_ed25519) を適用し、
    {checkpoint}/ear_published/ + manifest.lock を構築。bundle_sha256
    は正規化された {path,sha256,size} JSON の sha256 で、マシン間で
    決定的に再現可能。publish.yaml が無ければ静かにスキップ。

  ステージ 8: finalize_paper  (ari-skill-paper: inject_code_availability)  [ステージ 5+7 の後、v0.7.0]
    ear_published/manifest.lock + publish_record.json から ref / sha /
    doi を自動ロードし、機械可読な \codeavailability{} / \codedigest{}
    / \coderef{} マクロと人間可読な Code Availability セクションを
    full_paper.tex に注入。digest が信頼の起点となり、読者は registry
    を信頼することなく `ari clone <ref> --expect-sha256 <baked-digest>`
    で検証可能。

  ステージ 9: ear_publish  (ari-skill-transform: publish_ear)  [ステージ 7 の後、任意]
    ear_published/ から再現可能な tarball を構築し、backend
    (ari-registry / local-tarball / gh / zenodo) に転送。最初は常に
    visibility=staged (FR-P5)。デフォルトは無効、workflow.yaml で
    `enabled: true` にするかワーカーに publish=true を渡してオプトイン。
    出力: publish_record.json

  ステージ 10: review_paper / merge_reviews  (ari-skill-paper)  [ステージ 5+3b の後]
    review_paper は論文テキストのみを評価 (VLM 成果や figure manifest は
    渡さず、AI Scientist v2 の perform_review 契約に揃える)。
    merge_reviews は review_report.json と vlm_review.json を構造的に
    合成 (LLM 不使用)。
    出力: review_report.json (vlm_figure_review が後付けで添付される)

  ステージ 11: ors_generate_rubric  (ari-skill-replicate)  [v0.7.0]
    最終論文から PaperBench 形式 (TaskNode ツリー) のオートルーブリックを
    生成。task_category と finegrained_task_category は PaperBench の閉じた
    語彙に固定 (LLM が外したら decided 正規化で補正)。JSON 出力時は迷い
    LaTeX backslash escape をサニタイズ。
    出力: ors_rubric.json + ors_rubric.meta.json

  ステージ 12: ear_publish  (ari-skill-transform)  [v0.7.0, デフォルト有効]
    ear_published/ をバンドルにパッケージし publish_record.json を生成。
    既定 backend は local-tarball (依存ゼロ)。外部公開なら ari-registry /
    zenodo / gh も利用可能。
    出力: bundle.tar.gz + publish_record.json

  ステージ 13: ors_seed_sandbox  (ari-skill-paper-re: fetch_code_bundle)  [v0.7.0]
    キュレート済み EAR バンドルから repro_sandbox/ への決定論的種まき。
    publish_record.json から ref + sha256 を自動読込 (LLM 不使用)。EAR が
    OFF の時は publish_record.json が無いので no-op し、次の LLM フォール
    バックに任せる。
    出力: ors_seed.json

  ステージ 14: ors_build_reproduce  (ari-skill-paper-re: build_reproduce_sh)  [v0.7.0]
    LLM 駆動の replicator: 論文とルーブリックの expected_artifacts を読み、
    自己完結の reproduce.sh + ソースファイルをサンドボックスに書き出す。
    reproduce.sh が既存なら skip (ors_seed_sandbox の後ろに置けば EAR ON
    では発火しない)。LiteLLM 経由で provider neutral。
    出力: ors_replicator.json + repro_sandbox/{reproduce.sh, source...}

  ステージ 15: ors_run_reproduce  (ari-skill-paper-re: run_reproduce)  [v0.7.0]
    Phase 1。reproduce.sh をサンドボックスで実行:
      slurm (sbatch + ARI_SLURM_PARTITION = BFTS と同じ partition)
      → docker (デーモン利用可かつ HPC 外) → apptainer → singularity →
      local。ARI_PHASE1_SANDBOX で上書き可。
    SLURM 経路は sbatch --wait + spool relocation 対策 wrapper。
    出力: ors_phase1.json { executed, exit_code, log_path,
                              artifacts, missing, sandbox_kind,
                              [partition, cpus, walltime] }

  ステージ 16: ors_grade  (ari-skill-paper-re: grade_with_simplejudge)  [v0.7.0]
    Phase 2。メイン採点 completer を LiteLLM 経由化 (任意 provider 対応)、
    structured score-parser は gpt-4o-2024-08-06 のまま。N 回 (デフォルト 3)、
    重み付き葉スコア集約 + 負例コントロール。
    出力: ors_grade.json { ors_score, raw_score, leaf_grades,
                           judge_model, n_runs, rubric_sha256,
                           negative_control: {empty, boilerplate, passed} }
```

---

## ファイル構造

### チェックポイントディレクトリのレイアウト

各 ARI 実行は `{workspace}/checkpoints/{run_id}/` 以下にチェックポイントディレクトリを生成する。
`run_id` は `YYYYMMDDHHMMSS_<slug>` の形式。ディレクトリ構築は `ari/paths.py` の `PathManager`
が単一の真実の源泉 (single source of truth)。

```
checkpoints/{run_id}/
├── experiment.md               # 入力: 研究目標 (起動時にコピー)
├── launch_config.json          # Wizard/CLI 起動パラメータ
├── meta.json                   # サブ実験メタデータ (親/再帰深度)
├── workflow.yaml               # 起動時点のパイプライン設定スナップショット
├── .ari_pid                    # 生存検知用 PID ファイル
├── tree.json                   # 完全な BFTS ツリー (BFTS 中に書き込み)
├── nodes_tree.json             # 軽量ツリーエクスポート (パイプライン入力)
├── results.json                # ノード毎の artifact・metrics サマリ
├── idea.json                   # 生成された仮説 (VirSci 出力)。inherit_idea_index 起動時は親 ideas[N] が pinned で seed される (v0.7.0)
├── lineage_decisions.jsonl     # lineage decisions LLM judge ログ (発火した decision を 1 record/line; v0.7.0)
├── evaluation_criteria.json    # 主要指標と方向
├── cost_trace.jsonl            # LLM 呼び出し毎のコスト/トークンログ
├── cost_summary.json           # 集約コストサマリ
├── ari.log                     # 構造化 JSON ログ
├── ari_run_*.log               # GUI 起動時の stdout/stderr ログ
├── .pipeline_started           # マーカー: post-BFTS パイプライン開始済み
├── science_data.json           # Transform-skill 出力
├── related_refs.json           # 文献検索結果
├── figures_manifest.json       # 生成図メタデータ
├── fig_*.{pdf,png,eps,svg}     # 生成された図
├── vlm_review.json             # VLM 図レビュー出力
├── full_paper.tex              # 生成された LaTeX 論文
├── refs.bib                    # BibTeX 参照
├── full_paper.pdf              # コンパイル済み PDF
├── full_paper.bbl              # 文献リスト出力
├── review_report.json          # LLM 査読出力 (N>1 のとき ensemble_reviews[] と meta_review{} を同梱)
├── reproducibility_report.json # 再現性検証
├── uploads/                    # ユーザアップロードファイル (ノード work_dir へコピー)
├── paper/                      # LaTeX 編集用ワークスペース
│   ├── full_paper.tex
│   ├── full_paper.pdf
│   ├── refs.bib
│   └── figures/
├── ear/                        # 実験 Artifact Repository
│   ├── README.md
│   ├── RESULTS.md
│   └── <artifacts>
└── repro/                      # 再現性実行ワークスペース
    ├── run/
    ├── reproducibility_report.json
    └── repro_output.log
```

### ノード作業ディレクトリ

ノード毎の作業ディレクトリは `checkpoints/` と兄弟ディレクトリとして作成される:

```
{workspace}/experiments/{slug}/{node_id}/
```

ノード実行時、`_run_loop` は以下のユーザファイルを各ノードの work_dir にコピーする:
- **Provided files**: `experiment.md` の `## Provided Files` (`## 提供ファイル` / `## 提供文件`) にリストされたパス
- **チェックポイント直下**: チェックポイント直下の非 meta ファイル
- **uploads サブディレクトリ**: `checkpoint/uploads/` 内の非 meta ファイル

`PathManager.META_FILES` がノード work_dir に絶対にコピーしてはいけないファイルを定義
(`experiment.md`, `tree.json`, `nodes_tree.json`, `launch_config.json`, `meta.json`,
`results.json`, `idea.json`, `cost_trace.jsonl`, `cost_summary.json`, `workflow.yaml`,
`ari.log`, `evaluation_criteria.json`, `.ari_pid`, `.pipeline_started`)。
拡張子が `.log` のファイルも meta 扱い。

### tree.json と nodes_tree.json

いずれも BFTS ノードツリーを含むが、ライフサイクルの異なるタイミングで書き込まれる:

| ファイル          | 書き込み元                                            | フェーズ          | スキーマ                                              |
|-------------------|-------------------------------------------------------|-------------------|-------------------------------------------------------|
| `tree.json`       | `cli.py` の `_save_checkpoint()`                      | BFTS 中          | `{run_id, experiment_file, created_at, nodes}`        |
| `nodes_tree.json` | `_save_checkpoint()` + `generate_paper_section()`     | BFTS + post-BFTS | `{experiment_goal, nodes}` (軽量)                    |

**読み取り側の規約**: 全ての読み取りは `tree.json` を優先し、`nodes_tree.json` にフォールバック
しなければならない。これにより BFTS 中の最新データを保ちつつ、`nodes_tree.json` を前提とする
パイプラインステージとの互換性も維持する。

### プロジェクト単位の状態 (チェックポイントごと)

ARI はグローバルな設定ディレクトリを持たない。設定ファイルとエージェントメモリは
すべてアクティブなチェックポイント配下に保存されるため、実験ごとに状態が分離され、
`~/.ari/` は安全に削除できる
（`~/.ari/` は **v0.5.0 で廃止** — 詳細は `docs/refactor_audit.md`）:

```
checkpoints/{run_id}/
├── settings.json        # GUI 設定 (LLM モデル、プロバイダ、HPC デフォルト)
├── memory_backup.jsonl.gz   # Letta スナップショット (ステージ境界＋終了時に自動)
├── memory_access.jsonl       # write/read テレメトリ
└── ...                  # tree.json / launch_config.json / uploads / ari.log
```

API キーは **絶対に** `settings.json` には保存されない。`.env` ファイル
(探索順: checkpoint → ARI root → ari-core → home) または起動時に注入された環境変数から読み取る。

---

## モジュールリファレンス

### ari-core

| モジュール | 説明 |
|--------|-------------|
| `ari/orchestrator/bfts.py` | Branch-and-Frontier Tree Search — ノードの展開、選択、枝刈り; `_scientific_score` でランク付け |
| `ari/orchestrator/node.py` | Node データクラス — id, parent_id, depth, label, metrics, artifacts, memory |
| `ari/agent/loop.py` | ReAct エージェントループ — ノードごとの LLM + ツール呼び出し; SLURM ジョブの自動ポーリング; 祖先メモリの注入 |
| `ari/agent/workflow.py` | WorkflowHints — 実験テキストから自動抽出（ツールシーケンス、メトリクスキーワード、パーティション） |
| `ari/pipeline.py` | Post-BFTS パイプラインドライバー — テンプレート解決、ステージ実行、出力の接続 |
| `ari/evaluator/llm_evaluator.py` | メトリクス抽出 + 査読スコアリング（`scientific_score`、`comparison_found`） |
| `ari/memory/file_client.py` | ファイルベースのメモリクライアント（祖先チェーンスコープ） |
| `ari/mcp/client.py` | 非同期 MCP クライアント — スレッドセーフ、並列実行用の新しいイベントループ |
| `ari/llm/client.py` | litellm 経由の LLM ルーティング（Ollama、OpenAI、Anthropic、任意の OpenAI 互換） |
| `ari/config.py` | 設定データクラス（BFTSConfig、LLMConfig、PipelineConfig） |
| `ari/core.py` | トップレベルのランタイムビルダー — 全コンポーネントの接続 |
| `ari/cli.py` | CLI: `ari run`, `ari paper`, `ari status` |

### Skills (MCP サーバー)

**デフォルト skills**（`workflow.yaml` に登録済み）:

| Skill | ツール | 役割 | LLM? |
|-------|-------|------|------|
| `ari-skill-hpc` | `slurm_submit`, `job_status`, `job_cancel`, `run_bash`, `singularity_build`, `singularity_run`, `singularity_pull`, `singularity_build_fakeroot`, `singularity_run_gpu` | HPC ジョブ管理 + Singularity コンテナ | ✗ |
| `ari-skill-memory` | `add_memory`, `search_memory`, `get_node_memory`, `clear_node_memory`, `get_experiment_context` | 祖先スコープのノードメモリ（Letta バックエンド） | △ |
| `ari-skill-idea` | `survey`, `generate_ideas` | 文献検索（Semantic Scholar）+ VirSci マルチエージェント仮説生成 | ✓ |
| `ari-skill-evaluator` | `make_metric_spec` | 実験ファイルからのメトリクス仕様抽出 | △ |
| `ari-skill-transform` | `nodes_to_science_data`, `generate_ear`, `curate_ear`, `publish_ear` | BFTS ツリー → 科学データ + EAR + curate/publish ライフサイクル (v0.7.0) | ✓ |
| `ari-skill-web` | `web_search`, `fetch_url`, `search_arxiv`, `search_semantic_scholar`, `collect_references_iterative` | Web 検索、arXiv、Semantic Scholar、反復的引用収集 | △ |
| `ari-skill-plot` | `generate_figures`, `generate_figures_llm` | 決定論的 + LLM 図表生成（図ごとに matplotlib プロットまたは SVG 図を `kind` フィールドで選択） | ✓ |
| `ari-skill-paper` | `list_venues`, `get_template`, `generate_section`, `compile_paper`, `check_format`, `review_section`, `revise_section`, `write_paper_iterative`, `review_compiled_paper`, `list_rubrics`, `inject_code_availability`, `merge_reviews` | LaTeX 論文執筆、コンパイル、ルーブリック駆動査読 (AI Scientist v1/v2 互換)。v0.7.0: `inject_code_availability` で `\codeavailability{}` / `\codedigest{}` / `\coderef{}` マクロ注入、`merge_reviews` で text-review + VLM-review JSON を後付け合成。 | ✓ |
| `ari-skill-paper-re` | `fetch_code_bundle`, `run_reproduce`, `grade_with_simplejudge` | PaperBench 形式の再現性 (v0.7.0)。`ari.clone` でサンドボックス事前展開、Phase 1 サンドボックス runner、Phase 2 PaperBench SimpleJudge 採点。PaperBench は `vendor/paperbench` に同梱。 | ✓ |
| `ari-skill-replicate` | `generate_rubric`, `audit_rubric` | PaperBench 形式のオートルーブリック生成器・監査器 (v0.7.0)。ORS 再現性フローを駆動。 | ✓ |
| `ari-skill-benchmark` | `analyze_results`, `plot`, `statistical_test` | CSV/JSON/NPY 分析、プロット、scipy 統計（BFTS analyze ステージで使用） | ✗ |
| `ari-skill-vlm` | `review_figure`, `review_table` | VLM ベースの図表・テーブルレビュー（VLM レビューループを駆動） | ✓ |
| `ari-skill-coding` | `write_code`, `run_code`, `read_file`, `run_bash` | コード生成 + 実行 + ページネーション付きファイル読取 | ✗ |

**追加 skills**（利用可能、デフォルトワークフローには含まれない）:

| Skill | ツール | 役割 | LLM? |
|-------|-------|------|------|
| `ari-skill-orchestrator` | `run_experiment`, `get_status`, `list_runs`, `list_children`, `get_paper` | ARI を MCP サーバーとして公開、再帰的サブ実験、デュアル stdio+HTTP トランスポート | ✗ |

✗ = LLM なし、△ = 一部ツールのみ LLM、✓ = 主要ツールが LLM を使用。**全 14 skills**（13 デフォルト、1 追加）— v0.7.0 で `ari-skill-replicate` を追加。

---

## BFTS アルゴリズム

ARI は 2 プール設計による真の最良優先木探索を実装しています:

- **`pending`**: 実行待ちのノード（親から既に展開済み）
- **`frontier`**: 完了済みだが未展開のノード

```python
def bfts(experiment, config):
    root = Node(experiment, depth=0)
    pending = [root]      # 実行待ちノード
    frontier = []         # 展開待ちの完了済みノード
    all_nodes = [root]

    while len(all_nodes) < config.max_total_nodes:

        # --- BFTS ステップ 1: 最良のフロンティアノードを展開 ---
        # LLM が全完了ノードのメトリクスを読み、最も有望なノードを
        # 展開対象として選択（一度に全てではない）
        while frontier and len(pending) < max_parallel:
            best = llm_select_best_to_expand(frontier)  # _scientific_score に基づく
            frontier.remove(best)
            children = llm_propose_directions(best)     # 改善/アブレーション/検証
            pending.extend(children)
            all_nodes.extend(children)

        # --- BFTS ステップ 2: pending ノードのバッチを実行 ---
        batch = llm_select_next_nodes(pending, max_parallel)
        results = parallel_run(batch)

        for node in results:
            memory.write(node.eval_summary)   # 祖先チェーンメモリに保存
            if node.status == SUCCESS:
                frontier.append(node)         # 選択時に展開
            else:
                frontier.append(node)         # 失敗 → "debug" 子ノードで展開

    return max(all_nodes, key=lambda n: n.metrics.get("_scientific_score", 0))
```

主要な特性:
- **遅延展開**: 完了ノードは LLM が選択するまで展開されない — 低スコアのノードは無期限に待機する可能性がある
- **リトライなし**: 失敗ノードは `expand()` を通じて `debug` 子ノードを生成し、再実行はしない
- **厳密な予算**: `len(all_nodes) < max_total_nodes` で超過を防止
- **`generate_ideas` は一度だけ呼出**: ルートノード以降はループ防止のため抑制

### ノードラベル

| ラベル | 意味 |
|-------|---------|
| `draft` | ゼロからの新規実装 |
| `improve` | 親のパラメータまたはアルゴリズムの調整 |
| `debug` | 親の失敗の修正 |
| `ablation` | 一つのコンポーネントを除去してその影響を測定 |
| `validation` | 異なる条件で親を再実行 |

---

## Plan / Venue 契約 (v0.7.0+)

ARI の run を駆動する 2 種類のドキュメントを区別します:

- **plan.md (≒ checkpoint `experiment.md`、auto-promote 後)** —
  この run の **評価指標** (何を測るか、どんなベースラインと比較するか、
  どんな ablation を回すか)。run 固有。**source of truth は
  `idea.json[0].experiment_plan`**。
- **venue.md (≒ `ari-core/config/reviewer_rubrics/<id>.yaml`)** —
  **判断基準** (どの次元で採点するか、`score_dimensions` /
  `system_hint` / `decision`)。venue ごとに固定。

この 2 ファイル契約が Phase 1 / Phase 3 / lineage decisions を駆動します:

```
generate_ideas (idea-skill)
        │
        ▼ 書き出し
{ckpt}/idea.json    ← 機械可読 plan source
        │
        ├─ Phase 1: pipeline.py が {ckpt}/experiment.md に
        │   レンダリング可能ブロック (Selected idea + Plan §タイトル
        │   + Alternatives) を auto-append
        │
        ├─ Phase 3: LLMEvaluator が動的軸を構築
        │   = generic 5 + rubric.score_dimensions + plan §タグ keyword
        │   judge LLM が各 BFTS ノードを全軸で採点
        │
        └─ lineage decision (default stagnation_rule):
            BFTS hook が composite stagnation を検知して
            decide_lineage_action を呼ぶ。LLM が
            continue / switch_to_idea / fanout / terminate を選択。
            switch / fanout は Phase 2.5 の synthetic-seed launch path
            を経由 — 子 idea.json に選定 idea が `_pinned: True` で
            事前 seed され、子の generate_ideas が pinned の後ろに
            新 idea を append (上書きしない)。
```

`ARI_RUBRIC` がどの venue ファイルを読むかを決めます。切り替えると
BFTS のスコアリング軸 (Phase 3) と論文 review の評価基準が同時に変化
します — **同じ rubric が両方を駆動**します。

### サブ実験での継承

| チャネル | 継承 | 仕組み |
|---|---|---|
| `venue.md` (rubric) | する | `ARI_RUBRIC` env を伝搬 |
| `memory` | する | ancestor-scoped read (既存の `ari-skill-memory`) |
| `idea.json` (catalog) | する (read-only) | `ari/lineage.py` が `meta.json:parent_run_id` を walk; VirSci は ancestor タイトルを agent prompt に注入 |
| `plan.md` (directive) | しない (default) | 子は自分で書く |

`pipeline.py` の directive 経路は **自 ckpt の idea.json のみ** を読みます
— lineage walk は **catalog 経路** で、VirSci と sub-experiment launcher
が明示的に呼ぶときだけ動きます。これにより子は自由に pivot できます。

### work_dir 継承 — 出力アーティファクト ブラックリスト (v0.7.0 / Phase 7)

BFTS が子ノードを expand する際、子の `work_dir` は親をコピーして seed されます。フィルタなしだと子は親の `results.csv` / `slurm-*.out` / `run.log` をバイト単位で再利用できてしまい、run-`20260504120448` の post-mortem では 9 子全員が単一の SLURM job 結果を再報告していました — 結果ファイルが既に存在するため ReAct agent が「実験は完了済み」と判定したためです。

`ari-core/ari/cli.py` の `_OUTPUT_BLACKLIST` は親 → 子コピー時に **明示的に skip** するパターンを列挙しています:

| 継承する | ブラックリスト |
|---|---|
| ソース / スクリプト / config (`*.cpp`, `*.py`, `*.sh`, `*.yaml`, `Makefile`, ...) | `results.csv`, `results_*.csv`, `*_results.csv`, `metrics.csv`, `result.csv` |
| コンパイル済みバイナリ (`a.out`, 拡張子無し ELF) | `*.metrics.json`, `metrics.json` |
| `data/`, `inputs/` 配下のデータ | `run.log`, `run_*.log`, `*.run.log` |
| ネスト ソースディレクトリ (例: `src/lib.cpp`) | `slurm-*.out`, `slurm-*.err`, `stdout.txt`, `stderr.txt`, `out.txt`, `err.txt`, `node_report.json` |

実行後、`compute_files_changed(parent, child)` が sha256 diff から `{added, modified, deleted, inherited_unchanged}` を返します。`added=0 ∧ modified=0 ∧ deleted=0` の場合 loop はその子を **sterile** と判定し (`metrics["_sterile"]=True`、`_scientific_score=0.0`、`has_real_data=False`)、BFTS は非 sterile 兄弟を優先し、全ての子が sterile なら parent-terminate cascade が継承チェーンを刈り取ります。子 agent の最初の user message にも mandatory-new-artifacts 指示 (「この work_dir で **新しい** result/log/metric を生成すること; 継承ファイルに依存しない」) が入り、prompt 側からも実験実行を促します。

---

## 公開ライフサイクル (v0.7.0)

ARI v0.7.0 は EAR を「checkpoint をまるごと ear/ に放り込む」方式から、**digest 固定の公開チェーン** に進化させました。著者は小さな `ear/publish.yaml` を書くだけで、digest 計算と転送は ari-core が引き受けます。digest は論文に焼き付けられ (`\codedigest{...}`)、registry が無くなっても任意の場所で検証可能です。

```
generate_ear ──▶ {checkpoint}/ear/                 (著者のフルレポ)
                  + ear/publish.yaml               (allowlist + license/visibility)
        │
        ▼ ear_curate (transform-skill)
        ▼
{checkpoint}/ear_published/  +  manifest.lock      ({path,sha256,size} 正規化 JSON の sha256)
        │
        ▼ ear_publish (transform-skill, 任意)
        ▼
backend.publish ──▶ ari-registry / gh / zenodo / local-tarball
        │
        ▼ publish_record.json を書き出す
        │
        ▼ finalize_paper (paper-skill: inject_code_availability)
        ▼
full_paper.tex に \codeavailability{} \codedigest{} \coderef{}
        │
        ▼ ari clone <ref> --expect-sha256 <baked digest>
        ▼
読者の手元: バンドルバイトを digest 検証、コード実行は無し
```

### `ari clone` resolvers

| Scheme | 解決先 | 備考 |
|--------|--------|------|
| `file://<path>` | ローカルファイル/ディレクトリ | オフライン・ミラー |
| `https://<url>` / `http://<url>` | tarball ダウンロード | 任意の HTTPS ホスト |
| `ari://<id>` | ari-registry クライアント | `~/.ari/registries.yaml` から endpoint/token *(`~/.ari/` は **v0.5.0 で廃止**; `$ARI_REGISTRIES_FILE` または `{checkpoint}/.ari/registries.yaml` を推奨)* |
| `gh:<user>/<repo>` | GitHub repo / release | API + tarball |
| `doi:<doi>` | Zenodo deposition | DOI → ファイル一覧 → bundle |

### `ari registry` (任意のセルフホスト)

`ari/registry/` の最小 FastAPI サーバ。SQLite トークンストア、`${ARI_REGISTRY_DATA}/artifacts/<id>/{bundle.tar.gz, manifest.lock, meta.json}` のコンテンツアドレス保存。可視性は単調で `staged` → `unlisted` / `public` のみ (降格は拒否)。デプロイは uvicorn (laptop) / docker-compose (production) / Apptainer (HPC)。詳細は [docs/registry.md](registry.md)。

### 再現性サンドボックス補強

- **`_run_env.json`** — `ari/agent/run_env.py` が work_dir ごとに hostname / SLURM job/partition/nodelist / CPU model/threads/MHz/arch / mem_total / コンパイラバージョンを *実行プロセス内で* 書き出し、SLURM ジョブ (エージェントとは別ノードで動く) でも正確なハードウェア情報を残します。`node_report` ビルダは reports にこのデータを付与し、論文・再現性ステージは「sx40 partition、hostname X、Intel Xeon …で実行」のような事実を blank artefact から推測することなく取り戻せます。
- **Git shim** (`ari/agent/shims/git.sh`) — 再現性サンドボックスに `PATH=<sandbox>/.shims:<orig_path>` で組み込まれます。論文の `code_availability_ref` に一致する URL の `git clone` だけをインターセプトし、それ以外は本物の git に素通し。すべての clone 試行を `<sandbox>/repro_clone_log.jsonl` に記録します。`ARI_REPRO_CLONE_POLICY=passthrough|deny|warn` で動作切替。

---

## パイプライン駆動 ReAct (react_driver)

BFTS 自身の ReAct ループ(`ari.agent.AgentLoop`、`Node` ツリーと密結合)とは別に、BFTS コンテキストを必要としない ReAct エージェント向けの軽量ドライバ `ari.agent.react_driver.run_react` が存在します。ステージが `react:` ブロックを宣言したときに `ari.pipeline._run_react_stage` から呼び出されます。

**v0.7.0**: `reproducibility_check` ステージは `react_driver` を使わなくなりました。PaperBench 形式のフロー (`ors_generate_rubric` → `ors_run_reproduce` → `ors_grade`) が決定的な Phase 1 サンドボックス runner + Phase 2 SimpleJudge 採点 (`ari-skill-paper-re`) でこれを置き換えています。`react_driver` 自体は将来の `react:` 宣言ステージ向けにコードベースに残っていますが、デフォルトの `workflow.yaml` には接続されていません。

```
pipeline.py ──▶ pre_tool (MCP)  → 主張値 config
             ─▶ react_driver.run_react
                   ├─ phase フィルタ: MCPClient.list_tools(phase="reproduce")
                   ├─ 全ツール呼び出しの引数を sandbox 検証
                   └─ エージェントが `final_tool` を呼んだら終了
             ─▶ post_tool (MCP) → 判定 + 解釈
```

主な性質:

- **Phase ホワイトリスト**: `workflow.yaml` の `skills[].phase` は単一文字列または配列。ステージの `react.agent_phase` 値が phase リストに含まれるスキルだけがエージェントに見える。デフォルト `workflow.yaml` では `web-skill` / `vlm-skill` / `hpc-skill` / `coding-skill` が `reproduce` にオプトイン。`memory-skill` / `transform-skill` / `evaluator-skill` は意図的に除外され、エージェントは BFTS の状態(`nodes_tree.json`、祖先メモリ、science data)を観測できない。
- **サンドボックス**: `react.sandbox` はディレクトリ(既定 `{{checkpoint_dir}}/repro_sandbox/`)。ツール呼び出しの引数は絶対パスと `..` トラバーサルを走査され、sandbox 外 (論文 `.tex` の allow-list を除く) は MCP 到達前に `sandbox violation` として拒否される。MCP サーバー起動前に `ARI_WORK_DIR` を sandbox にセットするため、`coding-skill.run_bash` も自然に sandbox で cwd される。
- **終了条件**: エージェントは `react.final_tool`(既定 `report_metric`)を呼んでループを終える。その呼び出しは MCP には転送されずドライバが捕捉し、引数が post_tool に渡る `actual_value` / `actual_unit` / `actual_notes` となる。

この分離により、`reproduce_from_paper` スタイルのステージにおける「論文テキストのみを読む」制約が、スキル Python 内ではなく YAML から監査可能になります。

---

## メモリアーキテクチャ

各ノードは自身の祖先チェーンからのみ読み取ります:

```
root ──▶ memory["root"]
  ├─ node_A ──▶ memory["node_A"]
  │    ├─ node_A1  (読み取り: root + node_A)
  │    └─ node_A2  (読み取り: root + node_A、node_A1 は含まない)
  └─ node_B  (読み取り: root のみ、node_A ブランチは含まない)
```

`search_memory` は `query = node.eval_summary` で呼ばれます。Letta 0.16.7 のサーバ上で本スキルは `passages.search` (`GET /archival-memory/search`、`embed_query=True`) を `top_k = max(letta_overfetch, limit*40)` で叩き、ランクされた結果を `ancestor_ids` / `ari_checkpoint` / `kind == "node_scope"` でローカル post-filter します。サーバが返す **embedding ランク順がそのまま保持** されるので、子は自身のクエリに対して意味的に最も関連するエントリを先頭から受け取ります。意図的に避けた `passages.list(search=q)` ルートは SQL substring filter (`LOWER(text) LIKE LOWER(%q%)`) であり、`RESULT SUMMARY metrics=[...]` のような構造化エントリに対する長い自然文クエリは無音で 0 件を返します — 詳細は `ari-skill-memory/src/ari_skill_memory/backends/letta_backend.py` の live verification を参照。

### v0.6.0: Letta バックエンド

両レイヤはチェックポイントごとに 1 つの Letta エージェントに同居します:

- `ari_node_<ckpt_hash>` — 上記の祖先スコープメタデータフィルタを持つノードスコープの archival コレクション。
- `ari_react_<ckpt_hash>` — チェックポイント単位のフラットな ReAct トレース（`LettaMemoryClient`、祖先フィルタなし）。

エージェントはコアメモリブロック（`persona` + `human` + `ari_context`）に、最初のノードの `generate_ideas` が完了したタイミング（`primary_metric` が確定する時点）で実験目的・主要メトリック・ハードウェア仕様を seed します。スキルは `get_experiment_context()` で検索コストを払わずに読めますが、seed が走るまでは `{}` を返します。

**Copy-on-Write**: 書き込み側ツールは `node_id` ≠ `$ARI_CURRENT_NODE_ID` を reject するので、祖先エントリは兄弟ノード間でバイト安定です。同じ理由で Letta の self-edit パスはデフォルト無効化されています。

**ポータビリティ**: 各チェックポイントは `memory_backup.jsonl.gz` スナップショットを携行し、`ari resume` 時に対象 Letta が空であれば自動 restore されます。これにより `cp -r checkpoints/foo /elsewhere/` + `ari resume` が動き続けます。

---

## ノードごとのプロンプト構築

すべての BFTS ノードは `ari/agent/loop.py:370` の `AgentLoop.run(node, experiment)` という単一エントリポイントから実行されます。同じループが root ノードと子ノードの両方を処理し、構築されるプロンプトは `node.depth` と祖先から継承された状態によってのみ分岐します。本セクションは *エージェントがノード開始時に実際に何を見るか* の正典です。ここを変更する場合は慎重なレビューが必要です。

### `AgentLoop.run` への入力

呼び出しごとに 2 つの引数が渡ります:

1. **`node: Node`** — `BFTS.expand` (`ari/orchestrator/bfts.py:431-441`) で生成。プロンプトに影響するフィールド:
   - `id`、`depth`、`label`（`draft|improve|debug|ablation|validation|other`）、`raw_label`
   - `ancestor_ids` — root から親まで（親含む）の厳格な CoW チェーン。`search_memory` のフィルタに使われる。
   - `eval_summary` — 拡張直後の子ノードでは LLM が提案した方向性（1 文）を保持。実行後は評価器のサマリで上書きされる。
   - `memory_snapshot` — 親のスナップショットのコピー。現状プロンプトビルダーは未使用だが `tree.json` には永続化される。
2. **`experiment: dict`** — スケジューラがノードごとに組み立てる:
   - `goal` — `experiment.md` 全文（実験全体共通、全ノードで同一）
   - `work_dir` — `PathManager` が作成するノード専用ディレクトリ
   - `slurm_partition`、`slurm_max_cpus` — SLURM 有効時に `env_detect` から取得

### システムプロンプト — `ari/agent/loop.py:41-58`

```
You are a research agent. You MUST use tools to execute experiments. ...

AVAILABLE TOOLS:
{tool_desc}                ← アクティブなフェーズの MCP ツール一覧

RULES:
- Your FIRST action must be a tool call ...
- If `make_metric_spec` is available and this is a new experiment ...
- NEVER fabricate numeric values ...
- When all experiments are done, return JSON {...}
- Do NOT call gap_analysis or generate_hypothesis
- Ensure your experiment is reproducible: ...
{memory_rules}{extra}
```

`{extra}` ブロック（L448-453 で構築）は以下を追加します:

| サブブロック | 出所 | 備考 |
|-------------|------|------|
| `NODE ROLE: {label_hint}` | `node.label.system_hint()` | BFTS ラベルから引かれる 1 文の振る舞いキュー |
| `EXPERIMENT ENVIRONMENT` | L433-442 | `work_dir` + 既存ファイル + SLURM partition/CPUs + コンテナイメージ（`ARI_CONTAINER_IMAGE`） |
| `RESOURCE BUDGET` | L443-447 | `max_react_steps`、`timeout_per_node // 60` 分 |
| `extra_system_prompt` | `WorkflowHints.extra_system_prompt` | `from_experiment_text` / pipeline 設定が任意で設定するエスケープハッチ |

`{memory_rules}` ブロック（L454-456）は `add_memory` ツールが実際に利用可能なときのみ追加され、アクティブなノード ID をインライン展開して LLM が誤って別スコープに書けないようにします:

```
- When available, save decisive intermediate findings with
  add_memory(node_id="<このノードの id>", text=..., metadata=...)
- Use search_memory(query=..., ancestor_ids=[...], limit=5) ...
```

### ツールカタログ（`tool_desc`）

L389 の `tools = self._available_tools_openai(suppress=..., phase="bfts")` が `phase="bfts"` で MCP が公開する全ツールを列挙し、`_suppress_tools` に入っているものを除外します。可変な suppression セットは `AgentLoop` インスタンスに乗り、ループ進行に応じて更新されます:

- 最初の `generate_ideas` 成功呼び出しの後、`self._suppress_tools = {"generate_ideas"}`（L873-874）が設定され、後続ノードはアイデアを再生成しません。
- `survey` は子ノードに対して **suppress されません**。下記「User message #1 — 子ノード」の通り、文章でのみ非推奨化されています。子が指示を無視すれば `survey()` を呼べてしまいます。

`_PINNED_TOOLS = {"survey", "generate_ideas", "make_metric_spec"}`（L613）はメッセージウィンドウのトリマーが必ず保持するツール結果を表します。チャット履歴が圧縮されても、これらの結果は全 ReAct ラウンドで生き残ります。

### User message #1 — root ノード（`node.depth == 0`）

`loop.py:501-511`:

```
Experiment goal:
{goal_text(1500 文字に切り詰め)}

Node: {node.id} depth={node.depth}

START NOW: call {first_tool}() immediately. Do NOT output any text or
plan — your first response must be a {first_tool}() tool call.

IMPORTANT: After make_metric_spec, call survey() to search related
literature. The survey results will be used to generate citations in
the paper. Without survey, the paper will have no references.
```

`first_tool` は `WorkflowHints.tool_sequence[0]`。`enrich_hints_from_mcp` が、対応スキルが存在するときに `make_metric_spec` → `survey` → `generate_ideas` → executor の順をデフォルトにします。

### User message #1 — 子ノード（`node.depth > 0`）

`loop.py:477-500`:

```
Experiment goal:
{goal_text(1500 文字に切り詰め)}

Node: {node.id} depth={node.depth} task={node.label}

Task: {label-specific one-line description from _label_desc}
The parent node already completed the survey and established a research
direction. Prior results are provided below. Implement and run your
specific experiment, then return JSON with measurements.

Workflow:
{WorkflowHints.post_survey_hint}        ← 例: slurm_submit / run_bash 手順
```

`_label_desc`（L479-485）はノード単位プロンプトでラベル意味論が顔を出す唯一の場所です:

| Label | 1 行タスク |
|-------|-----------|
| `improve` | Improve performance or accuracy beyond what the parent achieved. |
| `ablation` | Ablation study: remove or vary one component from the parent approach. |
| `validation` | Validate the parent result under different conditions or parameters. |
| `debug` | The parent experiment had issues. Diagnose and fix them. |
| `draft` | Try a new implementation approach for the same goal. |
| *(other / unknown)* | Extend or vary the parent experiment. |

`node.eval_summary`（BFTS の expander LLM が提案した子固有の方向性）は **このプロンプトには直接書かれません**。子が見るのはラベルの汎用タスク文だけで、提案された方向性は下記の事前知識メモリ検索を介して間接的にエージェントへ届きます。

### User message #2 — 事前知識（子ノードのみ）

`loop.py:522-549`。`node.depth > 0` かつ `node.ancestor_ids` が空でない場合、ループは:

```python
search_memory(
    query        = (node.eval_summary or self.experiment_goal or "experiment result")[:200],
    ancestor_ids = node.ancestor_ids,
    limit        = 5,
)
```

を呼び、user メッセージを 1 つ追加します:

```
[Prior knowledge from ancestor nodes (N entries):]
{join(entry.text for entry in results)[:800]}
```

3 つの上限がハードコードされています:

| 上限 | 値 | 場所 |
|-----|-----|------|
| クエリ長 | 200 文字 | L528 |
| エントリ数 | 5 | L532 |
| 連結後コンテンツ | 800 文字 | L545 |

失敗（メモリバックエンド停止、結果が壊れている等）は `logger.debug` レベルで握り潰され、ノードは実行を継続します。

レガシーな `search_global_memory` 注入ブロック（L551-574）は v0.6.0 ではデッドコードです。グローバルメモリツールは削除されており（`CHANGELOG.md` v0.6.0 §3）、条件分岐は発火しません。

### 切り詰めの早見表

| 項目 | 上限 | コード |
|-----|-----|-------|
| `goal_text` | 1500 文字 | `loop.py:469-474` |
| Survey 結果メモリエントリ | 先頭 5 論文、各 abstract 200 文字 | `loop.py:830-833` |
| 事前知識クエリ | 200 文字 | `loop.py:528` |
| 事前知識エントリ | Letta `passages.search` 埋め込みランクで上位 5 件 | `loop.py:532` (Memory Architecture 節を参照) |
| 事前知識連結 | 800 文字 | `loop.py:545` |

### 意図的に **注入されていない** 情報

以下は到達可能ですがプロンプトには自動追加されません。エージェントが必要なら自分でツール呼び出しする必要があります:

- **`get_experiment_context()` のペイロード**（`experiment_goal`、`primary_metric`、`hardware_spec`、`metric_rationale`、`higher_is_better`）。最初の `generate_ideas` 後に seed されますが、MCP ツール経由でのみ取得可能で、いかなるプロンプトブロックにも貼り付けられません。
- **子ノードの `node.eval_summary` 方向性テキスト**。Node オブジェクトに永続化され、BFTS 拡張・評価からは見えますが、子エージェントの user prompt には現れません。
- **`memory_snapshot`**。親から子 Node へ持ち越されますが、プロンプトビルダーは消費しません。将来用途のため予約。
- **兄弟ノードの metrics**。子提案時の `BFTS.expand`（つまり *expander LLM*）には見えますが、その子の *実行エージェント* には見えません。

### CoW ブリッジ — メモリスキルとの同期維持

LLM へのラウンドトリップが始まる直前、`loop.py:378-381` で:

```python
self.mcp.call_tool("_set_current_node", {"node_id": node.id})
```

を発行します。これは `ari-skill-memory` が公開する内部ツールで、プールされたスキルサブプロセス内の `$ARI_CURRENT_NODE_ID` を更新し、後続の `add_memory(node_id=...)` 呼び出しがアクティブノードに対して CoW 検証されるようにします。エージェントはこのツールを見ません ── `_INTERNAL_MCP_TOOLS` で `tool_desc` から除外されています。

### Soft 強制 vs Hard 強制

エージェントが従っているように見える「ルール」のいくつかはコードで厳密に強制されますが、他はプロンプト文だけで制御されています。エージェントの予期しない挙動をデバッグする際にどちらか知っておくと役立ちます:

| ルール | 強制方法 |
|-------|---------|
| 他ノードのメモリに書けない | **Hard** — バックエンドが `node_id` ≠ `$ARI_CURRENT_NODE_ID` を reject |
| 兄弟メモリを読めない | **Hard** — `search_memory` が `ancestor_ids` でフィルタ |
| `generate_ideas` は最大 1 回 | **Hard** — 初回後 `_suppress_tools` で除外 |
| 子は `survey` を呼ぶべきでない | **Soft** — 文章のみ（"parent already completed the survey"）。ツールは `tool_desc` に残る |
| 子は計画ではなく実装すべき | **Soft** — 文章のみ。システムプロンプトの `RULES` ブロックに依存 |
| リソースバジェット | **Soft hint** をプロンプトで + ループ内に **hard** な timeout / step cap |

---

## 設計上の不変条件

ARI のプロダクションコードには**ドメイン知識がゼロ**です。すべてのドメイン判断は実行時に LLM に委譲されます。

| 判断 | 誰が決定するか |
|----------|-------------|
| どのメトリクスが重要か | LLM エバリュエーター |
| 何と比較するか | LLM エバリュエーター（`comparison_found`） |
| どの実験を実行するか | ReAct エージェント（LLM） |
| 使用されたハードウェア | Transform skill LLM（成果物から lscpu 等を読み取り） |
| どの図表を描くか | Plot skill LLM |
| ツリーから何を抽出するか | Transform skill LLM |
| ノードのランク付け方法 | LLM が付与する `_scientific_score` |
| 引用キーワードの選定 | ノードサマリーから LLM が生成 |
| 環境/セットアップ情報を収集するかどうか | ReAct エージェント LLM（システムプロンプトの再現性原則に従う） |

---

## ARI の拡張

新しい機能を追加するには、新しい MCP skill を作成します:

```bash
mkdir ari-skill-myskill/src
# server.py を FastMCP ツールで実装
# workflow.yaml の skills セクションに登録
```

```yaml
# workflow.yaml
skills:
  - name: myskill
    path: "{{ari_root}}/ari-skill-myskill"

pipeline:
  - stage: my_stage
    skill: myskill
    tool: my_tool
    inputs:
      data: "{{ckpt}}/science_data.json"
```

`ari-core` の変更は不要です。
