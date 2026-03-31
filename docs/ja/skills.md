# MCP Skills リファレンス

Skills は ARI エージェントに決定論的ツールを提供する MCP サーバーです。
skill 内で LLM を呼び出すことはできません（post-BFTS ステージの論文生成と査読を除く）。

## ari-skill-hpc

SLURM と Singularity による HPC ジョブ管理。

### ツール

#### `slurm_submit(script, job_name, partition, nodes=1, walltime="01:00:00", work_dir="")`

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

#### `run_bash(command)`

ログインノード上で読み取り専用の bash コマンドを実行します。

```python
result = run_bash("cat /path/to/slurm_job_12345.out")
# 戻り値: {"stdout": "...", "exit_code": 0}
```

#### `singularity_run_gpu(image_path, command, partition, gres="gpu:1")`

GPU アクセス付き（`--nv` フラグ）で Singularity コンテナを実行します。

---

## ari-skill-idea

文献調査とアイデア生成。

### ツール

#### `survey(topic, max_papers=5)`

arXiv と Semantic Scholar を検索します。完全に決定論的（LLM なし）。

```python
result = survey("parallel optimization benchmarks")
# 戻り値: {"papers": [{"title": "...", "abstract": "...", "url": "..."}]}
```

#### `make_metric_spec(experiment_text)`

実験 Markdown をパースして評価基準を抽出します。決定論的。

```python
result = make_metric_spec(open("experiment.md").read())
# 戻り値: {
#   "metric_keyword": "score",
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "..."
# }
```

#### `generate_ideas(topic, papers, experiment_context="", n_ideas=3)`

LLM を使用して研究仮説を生成します。BFTS 開始前に**一度だけ**呼び出されます（pre-BFTS のみ）。

---

## ari-skill-evaluator

実験成果物からのメトリクス抽出。

### ツール

#### `evaluate(artifacts, goal, metric_spec)`

生の成果物テキストからメトリクスを抽出します。`has_real_data` と `metrics` dict を返します。
スカラースコアなし — 多目的評価のみ。

#### `make_artifact_extractor(metric_keyword)`

出力テキストから特定のメトリクスを抽出するための Python コードを返します。

---

## ari-skill-paper

LaTeX 論文生成と査読（post-BFTS のみ）。

### ツール

#### `generate_section(section, context, venue="arxiv", nodes_json_path="")`

LLM を使用して LaTeX セクションを生成します。`nodes_tree.json` からエビデンスを検索します。

セクションの種類: `introduction`, `related_work`, `method`, `experiment`, `conclusion`

```python
result = generate_section(
    section="experiment",
    context="Best result: score 284172 with optimized configuration, 32 workers",
    venue="arxiv",
    nodes_json_path="/path/to/nodes_tree.json"
)
```

#### `review_section(latex, context, venue="arxiv")`

LaTeX セクションを査読します。強み、弱み、提案を返します。

---

## ari-skill-paper-re

再現性検証。完全に決定論的（LLM なし）。

### ツール

#### `extract_claims(paper_text, max_claims=50)`

正規表現パターンを使用して論文から数値的主張を抽出します。

#### `compare_with_results(claims, actual_metrics, tolerance_pct=10.0)`

許容範囲内で主張と計測メトリクスを比較します。

#### `reproducibility_report(paper_text, actual_metrics, paper_title="", tolerance_pct=10.0)`

完全な再現性レポートを生成します。

判定閾値: 80%以上 → REPRODUCED | 40-79% → PARTIAL | 40%未満 → NOT_REPRODUCED

---

## ari-skill-memory

祖先スコープのノードメモリ。ブランチ間の汚染を防止します。

### ツール

#### `add_memory(node_id, text, metadata=None)`
#### `search_memory(query, ancestor_ids, limit=5)`

`ancestor_ids`（祖先チェーン）に含まれるノードのエントリのみを返します。

#### `get_node_memory(node_id)`
#### `clear_node_memory(node_id)`

ストレージ: `~/.ari/memory_store.jsonl`（追記専用 JSONL）

---

## ari-skill-orchestrator

ARI を外部エージェントや IDE 向けの MCP サーバーとして公開します。

### ツール

#### `run_experiment(experiment_md, max_nodes=10, model="qwen3:32b")`

実験を非同期で投入します。`run_id` を返します。

#### `get_status(run_id)`

実行の進捗と現在の最良メトリクスを返します。

#### `get_paper(run_id)`

生成された `experiment_section.tex` を返します。

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

BFTS の内部表現を出版可能な科学データ形式に変換します。すべての内部フィールドを除去し、科学的コンテンツのみを公開します。

**ツール:**
- ランク付けされた構成とメトリクスのみを返す

**存在理由:** BFTS 内部の用語が生成される論文や図表に漏洩しないようにします。

---

## ari-skill-web

Web 検索と学術文献の取得。

**ツール:**
- 一般的な Web 検索
- arXiv 論文検索
- Semantic Scholar 引用検索
