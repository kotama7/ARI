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
  - LLM が 2-3 の子方向を提案（改善 / アブレーション / 検証）
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
    LLM 生成キーワード → Semantic Scholar API
    出力: related_refs.json

  ステージ 3: generate_figures  (ari-skill-plot)  [ステージ 1 の後]
    入力: 完全な science_data.json（experiment_context を含む）
    LLM が完全な matplotlib コードを記述 → 実行 → PDF 図表を保存
    図表の種類はデータから自律的に選択（事前指定なし）
    出力: figures_manifest.json

  ステージ 4: write_paper  (ari-skill-paper)  [ステージ 2, 3 の後]
    paper_context = experiment_context + best_nodes_metrics
    反復的セクション執筆: 下書き → LLM 査読 → 修正（最大 2 ラウンド）
    Semantic Scholar の結果から BibTeX 引用
    出力: full_paper.tex, refs.bib

  ステージ 5: review_paper  (ari-skill-paper)  [ステージ 4 の後]
    PDF → pdftotext → LLM 総合査読
    出力: review_report.json { score, verdict, citation_ok, feedback }

  ステージ 6: reproducibility_check  (ari-skill-paper-re)  [ステージ 4 の後]
    論文を読み取り → 構成を抽出 → HPC ジョブを実行 → 主張値と実測値を比較
    出力: reproducibility_report.json { verdict, claimed, actual, tolerance_pct }
```

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

| Skill | ツール | 役割 |
|-------|-------|------|
| `ari-skill-hpc` | `run_bash`, `slurm_submit`, `job_status`, `read_output` | コード実行 / HPC ジョブ管理 |
| `ari-skill-memory` | `add_memory`, `search_memory`, `get_node_memory` | 祖先チェーン実験メモリ |
| `ari-skill-idea` | `survey`, `generate_ideas`, `make_metric_spec` | 文献調査 + 仮説生成（VirSci） |
| `ari-skill-evaluator` | `make_metric_spec` | メトリクス仕様生成（ドメイン非依存） |
| `ari-skill-transform` | `nodes_to_science_data` | LLM による全ツリー分析 → science_data.json |
| `ari-skill-web` | `search_semantic_scholar` | 学術文献検索 |
| `ari-skill-plot` | `generate_figures_llm` | LLM が matplotlib を記述 → PDF 図表 |
| `ari-skill-paper` | `write_paper_iterative`, `review_compiled_paper` | LaTeX 論文執筆 + 査読 |
| `ari-skill-paper-re` | `reproduce_from_paper` | 再現性検証エージェント |

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
