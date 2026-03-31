# 拡張ガイド

このドキュメントでは、新しいユースケース、ドメイン、および機能に対して ARI を拡張する方法を説明します。
ARI は、新しい実験、skill、またはパイプラインステージを追加する際にコアコードの変更がゼロになるよう設計されています。

---

## 1. 新しい実験ドメインの追加

最も一般的な拡張です。**コードの変更は不要**です。

### 手順

1. `your_experiment.md` を記述します:

```markdown
# Protein Folding Optimization

## Research Goal
Minimize energy score of protein folding simulation using different force field parameters.

## Required Workflow
1. Call `survey` to find related literature
2. Submit a SLURM job with `slurm_submit`
3. Poll until completion with `job_status`
4. Read results with `run_bash`

<!-- min_expected_metric: -500 -->
<!-- metric_keyword: energy_score -->
```

2. 実行:

```bash
ari run your_experiment.md --config config/bfts.yaml
```

以上です。ARI が目標を読み取り、仮説を提案し、自律的に探索します。

### experiment.md によるドメインカスタマイズ

| セクション | 用途 | 影響 |
|---------|---------|--------|
| `## Research Goal` | 最適化対象 | LLM の仮説生成を駆動 |
| `## Required Workflow` | どのツールをどの順序で | WorkflowHints の `tool_sequence` を設定 |
| `## Hardware Limits` | ハード制約 | 各エージェントステップにシステムヒントとして注入 |
| `## SLURM Script Template` | 実験の開始点 | LLM が各仮説に合わせて修正 |
| `<!-- metric_keyword: X -->` | 抽出するメトリクス | エバリュエーターと evaluator-skill が使用 |
| `<!-- min_expected_metric: N -->` | 許容最小値 | バリデーションチェックをトリガー |

---

## 2. 新しい MCP Skill の追加

ari-core に手を加えずにエージェントに新しい機能（ツール）を追加します。

### Skill の構造

```
ari-skill-yourskill/
├── src/
│   └── server.py          ← FastMCP サーバー（必須）
├── tests/
│   └── test_server.py     ← テスト（最低 3 つ）
├── pyproject.toml         ← パッケージ設定
├── README.md              ← ツールの説明と使用例
└── REQUIREMENTS.md        ← 設計仕様
```

### サーバーテンプレート

```python
# src/server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("your-skill")

@mcp.tool()
def your_tool(param: str, option: int = 10) -> dict:
    """
    Clear description that appears in the LLM's tool list.

    Args:
        param: What this parameter does
        option: What this option controls (default: 10)

    Returns:
        result: The computed output
    """
    # RULE: No LLM calls here. Pure function.
    processed = pure_computation(param, option)
    return {"result": processed}

if __name__ == "__main__":
    mcp.run()
```

### 登録

BFTS 設定 YAML に記述します:

```yaml
skills:
  - name: your-skill
    path: /abs/path/to/ari-skill-yourskill
```

`experiment.md` に記述します:

```markdown
## Required Workflow
1. Call `your_tool` with the experiment parameters
```

### Skill 設計チェックリスト

- [ ] ツール関数内で LLM を呼び出さない（P2）
- [ ] 明確なキーを持つ `dict` を返す
- [ ] ツールの docstring が入力、出力、副作用を明確に説明している
- [ ] 正常系、エッジケース、エラーケースをカバーするテストが最低 3 つある
- [ ] 使用例付きの README.md がある
- [ ] 設計仕様の REQUIREMENTS.md がある

---

## 3. Post-BFTS パイプラインステージの追加

BFTS 探索完了後の自動後処理を追加します。
`config/pipeline.yaml` のみを編集します。コアコードの変更は不要です。

```yaml
pipeline:
  - stage: generate_paper
    skill: ari-skill-paper
    tool: generate_section
    enabled: true
    args:
      venue: arxiv

  - stage: review
    skill: ari-skill-paper
    tool: review_section
    enabled: true

  - stage: my_new_stage            # ← ここに追加
    skill: ari-skill-yourskill
    tool: your_analysis_tool
    enabled: true
    args:
      custom_param: value

  - stage: reproducibility_check
    skill: ari-skill-paper-re
    tool: reproducibility_report
    enabled: true
```

各ステージは以下を受け取ります:
- `best_node`: BFTS で最高スコアを獲得したノード
- `all_nodes`: 探索された全ノード
- `nodes_json_path`: `nodes_tree.json` へのパス
- YAML で指定された `args`

---

## 4. 新しい LLM バックエンドのサポート

litellm 経由でサポートされます。ほとんどの場合、設定の変更のみで対応できます。

```yaml
# OpenAI
llm:
  backend: openai
  model: gpt-4o

# Anthropic
llm:
  backend: anthropic
  model: claude-3-5-sonnet-20241022

# 任意の OpenAI 互換 API（vLLM、LM Studio など）
llm:
  backend: openai
  model: your-model-name
  base_url: http://your-server:8000/v1
```

LLM がファンクション/ツール呼び出しをサポートしていない場合は、`config/bfts.yaml` で `tool_choice="none"` を設定し、実験ワークフローで `## Required Workflow` を使用してステップバイステップの実行をガイドしてください。

---

## 5. 論文生成の新しい投稿先の追加

論文生成はテンプレートを通じて複数の学術投稿先をサポートしています。

### テンプレートの追加

```
ari-skill-paper/templates/
├── arxiv/
│   └── main.tex          ← 既存
├── neurips/
│   └── main.tex          ← 既存
└── your_venue/
    └── main.tex          ← ここに追加
```

### 投稿先リストへの登録

`ari-skill-paper/src/server.py` の `VENUES` に追加します:

```python
VENUES = {
    "arxiv": {"page_limit": None, "template": "arxiv/main.tex"},
    "neurips": {"page_limit": 9, "template": "neurips/main.tex"},
    "your_venue": {"page_limit": 8, "template": "your_venue/main.tex"},  # ← 追加
}
```

### パイプラインでの使用

```yaml
- stage: generate_paper
  skill: ari-skill-paper
  tool: generate_section
  args:
    venue: your_venue   # ← ここで指定
```

---

## 6. マルチノード / 分散実験の追加

複数の計算ノードを同時に必要とする実験向けです。

`experiment.md` に記述:

```markdown
## SLURM Script Template
```bash
#!/bin/bash
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=32
#SBATCH --cpus-per-task=2

mpirun -np 128 ./my_parallel_program
```
```

`config/bfts.yaml` でタイムアウトを増加:

```yaml
bfts:
  timeout_per_node: 3600   # 大規模 MPI ジョブ向けに 1 時間
```

---

## 7. ARI を外部システムに公開

`ari-skill-orchestrator` を使用して、他のエージェント、IDE、またはスクリプトから ARI をトリガーできます。

### Claude Desktop から

```json
{
  "mcpServers": {
    "ari": {
      "command": "python",
      "args": ["/path/to/ari-skill-orchestrator/src/server.py"]
    }
  }
}
```

Claude Desktop での使用例:
> "Run a benchmark and report the best score"

### 別のエージェントから

```python
from mcp import ClientSession
async with ClientSession(...) as session:
    result = await session.call_tool("run_experiment", {
        "experiment_md": open("experiment.md").read(),
        "max_nodes": 10
    })
    run_id = result["run_id"]
```

### REST API として（オーケストレーター経由）

オーケストレーター MCP サーバーは、CI/CD 統合のために HTTP ゲートウェイ経由でプロキシできます。

---

## 8. BFTS 選択戦略の変更

現在の戦略は `has_real_data=True` で最も高いメトリクス値を持つノードを選択します。
これを変更するには、`ari/orchestrator/bfts.py` を修正します:

```python
def _select_best_node(self, nodes: list[Node]) -> Node:
    """
    カスタム選択戦略。
    デフォルト: 実データを持つノードの中で最高メトリクス。
    """
    candidates = [n for n in nodes if n.has_real_data]
    if not candidates:
        return nodes[0]

    # 例: 多目的最適化のためのパレート最適選択
    return pareto_select(candidates, objectives=["score", "energy"])
```

---

## 拡張のアンチパターン

| アンチパターン | 問題点 | 正しいアプローチ |
|---|---|---|
| ドメインロジックを `ari-core` に追加 | P1（汎用コア）に違反 | `experiment.md` に記述 |
| skill ツール内で LLM を呼び出す | P2（決定論的ツール）に違反 | post-BFTS パイプラインでのみ呼び出す |
| エバリュエーターからスカラースコアを返す | P3（多目的）に違反 | 完全な `metrics` dict を返す |
| skill 内にモデル名をハードコード | P4（DI）に違反 | 設定またはツール引数で渡す |
| SBATCH で相対パスを使用 | 計算ノードでパスエラー発生 | 常に絶対パスを使用 |

---

## バージョニングと互換性

- すべての skill ツールインターフェースは `pyproject.toml` でバージョン管理
- ツールシグネチャの破壊的変更にはマイナーバージョンのバンプが必要
- `ari-core` は skill の実装ではなくインターフェースに依存（MCP による疎結合）
- ツールへの新しいオプションパラメータの追加は常に後方互換
