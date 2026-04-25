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
    Experiment Artifact Repository を構築: コード、データ、ログ、再現性メタデータ
    出力: ear_manifest.json, ear/ ディレクトリ

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

  ステージ 7: reproducibility_check  (ari-skill-paper-re + react_driver)  [ステージ 5 の後]
    pre_tool  (paper-re.extract_repro_config)
        論文から主張値を抽出
        { metric_name, claimed_value, description, threads }
    react_driver  (ari-core/ari/agent/react_driver.py)
        phase=reproduce にオプトインされた MCP スキル (web / vlm / hpc / coding)
        のみを見る ReAct ループを駆動。memory-skill / transform-skill /
        evaluator-skill は意図的に除外され、エージェントは BFTS フェーズの
        成果物(nodes_tree.json、祖先メモリなど)にアクセスできません。
        サンドボックスは {{checkpoint_dir}}/repro_sandbox に制限。
    post_tool (paper-re.build_repro_report)
        実測値と主張値を比較し、判定と解釈を出力。
    出力: reproducibility_report.json { verdict, claimed, actual, tolerance_pct }
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
├── idea.json                   # 生成された仮説 (VirSci 出力)
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
`~/.ari/` は安全に削除できる:

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
| `ari-skill-transform` | `nodes_to_science_data` | BFTS ツリー → 科学データ（内部フィールド除去） | ✓ |
| `ari-skill-web` | `web_search`, `fetch_url`, `search_arxiv`, `search_semantic_scholar`, `collect_references_iterative` | Web 検索、arXiv、Semantic Scholar、反復的引用収集 | △ |
| `ari-skill-plot` | `generate_figures`, `generate_figures_llm` | 決定論的 + LLM 図表生成（図ごとに matplotlib プロットまたは SVG 図を `kind` フィールドで選択） | ✓ |
| `ari-skill-paper` | `list_venues`, `get_template`, `generate_section`, `compile_paper`, `check_format`, `review_section`, `revise_section`, `write_paper_iterative`, `review_compiled_paper`, `list_rubrics` | LaTeX 論文執筆、コンパイル、ルーブリック駆動査読 (AI Scientist v1/v2 互換)。`review_compiled_paper` は アンサンブル経路で N 名の独立査読者を実行し、N>1 のとき Area Chair メタ査読も内部で走る。 | ✓ |
| `ari-skill-paper-re` | `extract_repro_config`, `build_repro_report`, `extract_metric_from_output` | 再現性 ReAct の決定論的 pre/post エンドポイント (ループ本体は `ari-core/ari/agent/react_driver.py`) | ✓ |
| `ari-skill-benchmark` | `analyze_results`, `plot`, `statistical_test` | CSV/JSON/NPY 分析、プロット、scipy 統計（BFTS analyze ステージで使用） | ✗ |
| `ari-skill-vlm` | `review_figure`, `review_table` | VLM ベースの図表・テーブルレビュー（VLM レビューループを駆動） | ✓ |
| `ari-skill-coding` | `write_code`, `run_code`, `read_file`, `run_bash` | コード生成 + 実行 + ページネーション付きファイル読取 | ✗ |

**追加 skills**（利用可能、デフォルトワークフローには含まれない）:

| Skill | ツール | 役割 | LLM? |
|-------|-------|------|------|
| `ari-skill-orchestrator` | `run_experiment`, `get_status`, `list_runs`, `list_children`, `get_paper` | ARI を MCP サーバーとして公開、再帰的サブ実験、デュアル stdio+HTTP トランスポート | ✗ |

✗ = LLM なし、△ = 一部ツールのみ LLM、✓ = 主要ツールが LLM を使用。13 skills（12 デフォルト、1 追加）。

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

## パイプライン駆動 ReAct (react_driver)

BFTS 自身の ReAct ループ(`ari.agent.AgentLoop`、`Node` ツリーと密結合)とは別に、BFTS コンテキストを必要としない ReAct エージェント向けの軽量ドライバ `ari.agent.react_driver.run_react` が存在します。ステージが `react:` ブロックを宣言したときに `ari.pipeline._run_react_stage` から呼び出され、現在は `reproducibility_check` で使用されています。

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

`search_memory` のクエリ = ノード自身の `eval_summary` テキスト（ドメインキーワードではない）。
これにより、取得されるメモリが現在のノードの作業に意味的に関連していることが保証されます。

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
| 事前知識エントリ | relevance 上位 5 件 | `loop.py:532` |
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
