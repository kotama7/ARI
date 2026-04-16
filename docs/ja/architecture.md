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
    PDF → pdftotext → LLM 総合査読
    出力: review_report.json { score, verdict, citation_ok, feedback }

  ステージ 7: respond_to_review  (ari-skill-review)  [ステージ 6 の後]
    レビュー懸念をパース → 逐次反論を生成
    出力: rebuttal.json

  ステージ 8: reproducibility_check  (ari-skill-paper-re)  [ステージ 5 の後]
    論文を読み取り → 構成を抽出 → HPC ジョブを実行 → 主張値と実測値を比較
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
├── review_report.json          # LLM 査読出力
├── rebuttal.json               # 逐次反論
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
├── memory.json          # FileMemoryClient ストア (祖先チェーン)
├── memory_store.jsonl   # ari-skill-memory MCP サーバのエントリ
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
| `ari-skill-memory` | `add_memory`, `search_memory`, `get_node_memory`, `clear_node_memory` | 祖先チェーン実験メモリ（JSONL） | ✗ |
| `ari-skill-idea` | `survey`, `generate_ideas` | 文献検索（Semantic Scholar）+ VirSci マルチエージェント仮説生成 | ✓ |
| `ari-skill-evaluator` | `make_metric_spec` | 実験ファイルからのメトリクス仕様抽出 | △ |
| `ari-skill-transform` | `nodes_to_science_data` | BFTS ツリー → 科学データ（内部フィールド除去） | ✓ |
| `ari-skill-web` | `web_search`, `fetch_url`, `search_arxiv`, `search_semantic_scholar`, `collect_references_iterative` | Web 検索、arXiv、Semantic Scholar、反復的引用収集 | △ |
| `ari-skill-plot` | `generate_figures`, `generate_figures_llm` | 決定論的 + LLM ベースの matplotlib 図表生成 | ✓ |
| `ari-skill-paper` | `list_venues`, `get_template`, `generate_section`, `compile_paper`, `check_format`, `review_section`, `revise_section`, `write_paper_iterative`, `review_compiled_paper` | LaTeX 論文執筆、コンパイル、査読 | ✓ |
| `ari-skill-paper-re` | `extract_metric_from_output`, `reproduce_from_paper` | ReAct 再現性検証エージェント | ✓ |
| `ari-skill-figure-router` | （図表タイプ分類） | 図表タイプ分類と生成ルーティング（SVG/matplotlib/LaTeX） | ✓ |
| `ari-skill-benchmark` | `analyze_results`, `plot`, `statistical_test` | CSV/JSON/NPY 分析、プロット、scipy 統計（BFTS analyze ステージで使用） | ✗ |
| `ari-skill-review` | `parse_review`, `generate_rebuttal`, `check_rebuttal` | 査読パース + リバッタル生成 | ✓ |
| `ari-skill-vlm` | `review_figure`, `review_table` | VLM ベースの図表・テーブルレビュー（VLM レビューループを駆動） | ✓ |
| `ari-skill-coding` | `write_code`, `run_code`, `read_file`, `run_bash` | コード生成 + 実行 + ページネーション付きファイル読取 | ✗ |

**追加 skills**（利用可能、デフォルトワークフローには含まれない）:

| Skill | ツール | 役割 | LLM? |
|-------|-------|------|------|
| `ari-skill-orchestrator` | `run_experiment`, `get_status`, `list_runs`, `list_children`, `get_paper` | ARI を MCP サーバーとして公開、再帰的サブ実験、デュアル stdio+HTTP トランスポート | ✗ |

✗ = LLM なし、△ = 一部ツールのみ LLM、✓ = 主要ツールが LLM を使用。15 skills（14 デフォルト、1 追加）。

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
