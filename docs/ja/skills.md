# MCP Skills リファレンス

Skills は ARI エージェントにツールを提供する MCP サーバーです。ツールは可能な限り決定論的であり、LLM を使用するツールは明示的に注記されています。全 15 skill（デフォルト 14、追加 1）。

## ari-skill-hpc

SLURM と Singularity による HPC ジョブ管理。**LLM: No**（完全に決定論的）。

### ツール

#### `slurm_submit(script, job_name, partition, nodes=1, walltime="01:00:00", work_dir)`

SLURM バッチジョブを投入します。

```python
result = slurm_submit(
    script="""
#!/bin/bash
#SBATCH --cpus-per-task=32
compiler -o ./bench ./bench.c
NTHREADS=32 ./bench
""",
    job_name="bench_test",
    partition="your_partition",
    work_dir="/abs/path/to/workdir"
)
# 戻り値: {"job_id": "12345", "status": "submitted"}
```

**注意事項:**
- `--account` と `-A` ヘッダーは暗黙的に除去されます（このクラスターでは無効）
- 空の `job_id` は即座に ERROR を返します
- スクリプト内のパスに `~` を使用しないでください（SBATCH では展開されません）

#### `job_status(job_id)`

SLURM ジョブのステータスをポーリングします。

```python
result = job_status("12345")
# 戻り値: {"status": "COMPLETED", "exit_code": 0, "stdout": "score: 284172"}
# ステータス値: PENDING, RUNNING, COMPLETED, FAILED, ERROR
```

#### `job_cancel(job_id)`

実行中または待機中の SLURM ジョブをキャンセルします。

#### `run_bash(command)`

ログインノード上で bash コマンドを実行します。

```python
result = run_bash("cat /path/to/slurm_job_12345.out")
# 戻り値: {"stdout": "...", "exit_code": 0}
```

#### `singularity_build(definition_file, output_path, partition)`

定義ファイルから Singularity コンテナをビルドします。

#### `singularity_run(image_path, command, work_dir, partition, nodes=1, walltime="01:00:00")`

Singularity コンテナを SLURM ジョブとして実行します。

#### `singularity_pull(source, output_path, partition)`

リモートレジストリから Singularity イメージを取得します。

#### `singularity_build_fakeroot(definition_content, output_path, partition, walltime)`

fakeroot モードで Singularity コンテナをビルドします。

#### `singularity_run_gpu(image_path, command, work_dir, partition, gres="gpu:1", cpus_per_task=8, walltime="01:00:00", bind_paths=[])`

GPU アクセス付き（`--nv` フラグ）で Singularity コンテナを実行します。

---

## ari-skill-idea

文献調査とアイデア生成。**LLM: Yes**（generate_ideas は VirSci マルチエージェント討論を使用）。

### ツール

#### `survey(topic, max_papers=8)`

Semantic Scholar で関連論文を検索します。決定論的（LLM なし）。

```python
result = survey("OpenMP compiler optimization HPC benchmarks")
# 戻り値: {"papers": [{"title": "...", "abstract": "...", "url": "..."}]}
```

高レートリミットには `S2_API_KEY` 環境変数が必要です。

#### `generate_ideas(topic, papers, experiment_context="", n_ideas=3, n_agents=4, max_discussion_rounds=2, max_recursion_depth=0)`

VirSci マルチエージェント LLM 討論を使用して研究仮説を生成します。複数の AI ペルソナ（researcher、critic、expert、synthesizer）が研究課題について議論します。BFTS 開始前に**一度だけ**呼び出されます（pre-BFTS のみ）。

モデル: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`。

---

## ari-skill-evaluator

実験ファイルからのメトリクス仕様抽出。**LLM: Conditional**（テキスト内に metric_keyword が見つからない場合のみフォールバック）。

### ツール

#### `make_metric_spec(experiment_text)`

実験 Markdown をパースして評価基準を抽出します。テキスト内に `metric_keyword` と `min_expected_metric` がある場合は決定論的、見つからない場合は LLM にフォールバックします。

```python
result = make_metric_spec(open("experiment.md").read())
# 戻り値: {
#   "metric_keyword": "MFLOPS",
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "..."
# }
```

モデル（フォールバック）: `ARI_MODEL` env > `gpt-4o-mini`。

---

## ari-skill-paper

LaTeX 論文生成、コンパイル、査読（post-BFTS のみ）。**LLM: Yes**。

### ツール

#### `list_venues()`

利用可能な投稿先設定を返します。

対応投稿先: `neurips`（9 ページ）、`icpp`（10 ページ）、`sc`（12 ページ）、`isc`（12 ページ）、`arxiv`（無制限）、`acm`（10 ページ）。

#### `get_template(venue)`

投稿先の LaTeX テンプレートを返します。

#### `generate_section(section, context, venue="arxiv", refs_json="", nodes_json_path="")`

LLM を使用して LaTeX セクションを生成します。セクションの種類: `introduction`, `related_work`, `method`, `experiment`, `conclusion`。

#### `compile_paper(tex_dir, main_file="main.tex")`

pdflatex コンパイルを実行します。成功ステータスとエラーメッセージを返します。

#### `check_format(venue, pdf_path)`

投稿先の要件に対して論文フォーマットを検証します（ページ数など）。

#### `review_section(latex, context, venue="arxiv")`

LaTeX セクションを査読します。強み、弱み、提案を返します。

#### `revise_section(section, latex, feedback)`

査読フィードバックに基づいて LaTeX セクションを修正します。

#### `write_paper_iterative(experiment_summary, context, nodes_json_path, refs_json, figures_manifest_json, output_dir, max_revisions=2, venue="arxiv")`

反復的な下書き → 査読 → 修正ループによる完全な論文生成。主要なパイプラインツール。

#### `review_compiled_paper(tex_path, pdf_path, figures_manifest_json, paper_summary)`

PDF ベースの包括的論文査読: テキスト抽出、図表キャプション評価、構造化品質レポート。

モデル: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`。

---

## ari-skill-paper-re

ReAct エージェントループによる再現性検証。**LLM: Yes（ReAct）**。

エージェントが生成された論文を読み取り、実験構成を抽出し、実験をゼロから再実装・実行し、主張されたメトリクスと結果を比較します。

### ツール

#### `extract_metric_from_output(output_text, metric_name)`

LLM が生の出力テキストから特定のメトリクス値を抽出します。

#### `reproduce_from_paper(paper_path="", paper_text="", experiment_goal="", work_dir="", source_file="", executor="", cpus=64, timeout_minutes=15, tolerance_pct=5.0)`

完全な ReAct 再現性検証。内部サブツール: `write_file`, `run_bash`, `read_file`, `report_metric`, `submit_job`（非ローカル実行時）。

対応エグゼキュータ: `local`, `slurm`, `pbs`, `lsf`。最大 ReAct ステップ: 40。

判定閾値: 80%以上 → REPRODUCED | 40-79% → PARTIAL | 40%未満 → NOT_REPRODUCED

モデル: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`。

---

## ari-skill-memory

祖先スコープのノードメモリ。ブランチ間の汚染を防止します。**LLM: No**（決定論的キーワードマッチング）。

### ツール

#### `add_memory(node_id, text, metadata=None)`

`node_id` でタグ付けされたメモリエントリを保存します。

#### `search_memory(query, ancestor_ids, limit=5)`

`ancestor_ids`（祖先チェーン）に含まれるノードのエントリのみを返します。キーワードマッチングを使用します。

#### `get_node_memory(node_id)`

特定ノードの全メモリを取得します。

#### `clear_node_memory(node_id)`

特定ノードの全メモリを削除します。

ストレージ: 実験ごとに `{ARI_CHECKPOINT_DIR}/memory_store.jsonl`（追記専用 JSONL、`ARI_MEMORY_PATH` で上書き可）

---

## ari-skill-orchestrator

ARI を外部エージェントや IDE 向けの MCP サーバーとして公開します。再帰的なサブ実験をサポート。**LLM: No**（ARI CLI に委譲）。

デュアルトランスポート: **stdio**（Claude Desktop / 他 MCP クライアント向け）+ **HTTP**（REST + SSE、`ARI_ORCHESTRATOR_PORT`、デフォルト 9890）。

### ツール

#### `run_experiment(experiment_md, max_nodes=10, model="qwen3:32b", parent_run_id="", recursion_depth=0, max_recursion_depth=0)`

ARI 実験を非同期で起動します。`run_id` を返します。`parent_run_id` を指定すると、その実験は親の子として追跡されます（再帰的サブ実験ワークフロー用）。

#### `get_status(run_id)`

実行の進捗、現在の最良メトリクス、再帰メタデータを返します。

#### `list_runs()`

過去の全実験実行を一覧表示します。

#### `list_children(run_id)`

親実験の子実行一覧を返します（再帰的サブ実験追跡用）。

#### `get_paper(run_id)`

生成された論文（LaTeX）を返します。

ワークスペース: `ARI_WORKSPACE` env（デフォルト: `~/ARI`）。親子関係は各チェックポイントの `meta.json` に保存されます。

---

## ari-skill-figure-router

図種別の分類と生成ルーティング。**LLM: Yes**。

要求された図を最適なレンダリングバックエンド（SVG / matplotlib / LaTeX）に分類してルーティングします。`phase: all` でデフォルトスキルとして登録されています。

---

## 新しい Skill の記述

1. `ari-skill-yourskill/src/server.py` を作成:

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("your-skill")

@mcp.tool()
def your_tool(param: str) -> dict:
    """Tool description."""
    # NO LLM calls here
    return {"result": process(param)}

if __name__ == "__main__":
    mcp.run()
```

2. BFTS 設定 YAML に登録:

```yaml
skills:
  - name: your-skill
    path: /path/to/ari-skill-yourskill
```

3. `experiment.md` の `## Required Workflow` でツール名を参照。

## ari-skill-transform

BFTS の内部表現を出版可能な科学データ形式に変換します。すべての内部フィールド（`node_id`、`label`、`depth`、`parent_id`）を除去し、科学的コンテンツ（`configurations`、`experiment_context`）のみを公開します。**LLM: Yes**。

### ツール

#### `nodes_to_science_data(nodes_json_path, llm_model="", llm_base_url="")`

LLM が BFTS ツリー全体を分析し、ハードウェアスペック、手法、主要な知見、比較を抽出します。

戻り値: `{configurations, per_key_summary, experiment_context, summary_stats}`。

モデル: `llm_model` 引数 > `LLM_MODEL` env > `gpt-4o-mini`。

**存在理由:** BFTS 内部の用語が生成される論文や図表に漏洩しないようにします。

#### `generate_ear(checkpoint_dir, llm_model="", llm_base_url="")`

再現性のための **Experiment Artifact Repository (EAR)** を `<checkpoint>/ear/` に構築します。内容:

- `README.md` と `RESULTS.md`（可能な場合は LLM 生成、それ以外は決定論的フォールバック）
- `code/<node_id>/` — 各ノードの実験ディレクトリからコピーされたソースファイル
- `data/raw_metrics.json`、`data/science_data.json`、`data/figures/`
- `logs/bfts_tree.json`、`logs/eval_scores.json`
- `reproducibility/environment.json`（Python バージョン、プラットフォーム、pip パッケージ、ハードウェア）
- `reproducibility/run_config.json`、`reproducibility/commands.md`

戻り値: `{ear_dir, manifest}` — 生成されたファイルのパス。

---

## ari-skill-web

検索バックエンドが切替可能な Web 検索と学術文献の取得。**LLM: Partial**（`collect_references_iterative` のみ LLM を使用）。

### ツール

#### `web_search(query, n=5)`

DuckDuckGo Web 検索。API キー不要。決定論的。

#### `fetch_url(url, max_chars=8000)`

BeautifulSoup 経由で URL からテキストを取得・抽出します。決定論的。

#### `search_arxiv(query, max_results=5)`

arXiv 論文検索。決定論的。

#### `search_semantic_scholar(query, limit=8, extra_queries=None)`

Semantic Scholar API（arXiv へのフォールバック付き）。決定論的。

#### `search_papers(query, limit=8)`

設定された検索バックエンド（`ARI_RETRIEVAL_BACKEND`）にディスパッチします:
- `"semantic_scholar"`（デフォルト）— Semantic Scholar API
- `"alphaxiv"` — HTTP 経由の MCP JSON-RPC で AlphaXiv
- `"both"` — 並列実行＋重複排除

#### `set_retrieval_backend(backend)`

実行時に検索バックエンドを動的に切り替えます。有効値: `"semantic_scholar"`、`"alphaxiv"`、`"both"`。

#### `collect_references_iterative(experiment_summary, keywords, max_rounds=20, min_papers=10)`

AI Scientist v2 スタイルの反復的引用収集。LLM が検索クエリを生成し、複数ラウンドにわたって関連論文を選択します。

モデル: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`。

#### `list_uploaded_files()`

チェックポイントディレクトリ内のユーザアップロードファイルを一覧表示します。決定論的。

#### `read_uploaded_file(filename, max_chars=8000)`

アップロードファイルからテキストを読み取ります（バイナリ検出付き）。決定論的。

---

## ari-skill-coding

コード生成、実行、ファイル読込。**LLM: No**（決定論的）。

### ツール

#### `write_code(filename, code, work_dir="/tmp/ari_work")`

作業ディレクトリにソースファイルを書き込みます。

#### `run_code(filename, work_dir="/tmp/ari_work", timeout=60)`

ソースファイルを実行します（拡張子から言語を自動検出）。出力は省略文字数とファイル出力推奨ヒント付きのマーカー付きで切り詰められます。

#### `run_bash(command, work_dir="/tmp/ari_work", timeout=60)`

作業ディレクトリで bash コマンドを実行します。結果に `truncated` ブールフラグ付きで出力切り詰めを行います。

#### `read_file(filepath, offset=0, limit=2000, work_dir="/tmp/ari_work")`

大きなファイル向けにページング対応でテキストファイルを読み込みます。コンテンツ、継続用 `next_offset`、総行数を返します。

```python
result = read_file("results.csv", offset=0, limit=100)
# 戻り値: {"content": "...", "next_offset": 100, "total_lines": 5000}
```

作業ディレクトリ: `work_dir` 引数 > `ARI_WORK_DIR` env > `/tmp/ari_work`。

---

## ari-skill-benchmark

パフォーマンス分析、プロット、統計検定。**LLM: No**（決定論的）。

### ツール

#### `analyze_results(result_path, metrics)`

CSV、JSON、NPY 結果ファイルを読み込み分析します。要約統計量を返します。

#### `plot(data, plot_type, output_path, title="", xlabel="", ylabel="")`

matplotlib 図表を生成します。プロットタイプ: `bar`, `line`, `scatter`, `heatmap`。

#### `statistical_test(data_a, data_b, test)`

scipy 統計検定を実行します: `ttest`, `mannwhitney`, `wilcoxon`。

---

## ari-skill-review

査読パースとリバッタル生成。**LLM: Yes**。

### ツール

#### `parse_review(review_text)`

LLM がフリーテキストの査読を構造化形式にパースします: summary、concerns（id/severity/text）、questions、suggestions。

#### `generate_rebuttal(concerns, paper_context, experiment_results)`

LLM がポイントごとのリバッタルを LaTeX 形式で生成します。

#### `check_rebuttal(rebuttal, original_concerns)`

LLM がリバッタルの完全性を検査します: coverage（0-1）、missing items、suggestions。

モデル: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama/qwen3:8b`。

---

## ari-skill-vlm

図表・テーブル品質レビューのための Vision-Language モデル。**LLM: Yes**（VLM）。

### ツール

#### `review_figure(image_path, context="", criteria=None)`

VLM が実験図表をレビューします。スコア（0-1）、問題点、提案を返します。

#### `review_table(latex_or_path, context="")`

VLM がテーブル（LaTeX ソースまたはレンダリング画像）をレビューします。スコア、問題点、提案を返します。

モデル: `VLM_MODEL` env > `openai/gpt-4o`。
