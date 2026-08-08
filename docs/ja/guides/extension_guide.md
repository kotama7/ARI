---
sources:
  - path: ari-core/ari/public
    role: implementation
  - path: ari-core/ari/prompts
    role: prompt
  - path: ari-core/ari/configs
    role: config
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-07-30
---

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

<!-- min_expected_metric: 500 -->
```

2. 実行:

```bash
ari run your_experiment.md
```

以上です。ARI が目標を読み取り、仮説を提案し、自律的に探索します。
`--config` は任意です — 省略すると `ari run` が同梱の
`ari-core/config/workflow.yaml` を自動解決します。

### experiment.md によるドメインカスタマイズ

`from_experiment_text`（`ari/agent/workflow.py`）が実際にパースするのは以下だけ
です。残りは LLM がゴールとして読む散文です:

| セクション | 用途 | 影響 |
|---------|---------|--------|
| `## Research Goal` | 最適化対象 | LLM の仮説生成を駆動 |
| `## Required Workflow` | どのツールをどの順序で | `WorkflowHints.post_survey_hint`（「Follow this workflow from the experiment spec: …」）になる。`tool_sequence` はこのセクションではなく MCP が実際に公開しているツールから構築される |
| `## Provided Files`（`## 提供ファイル` / `## 提供文件` / `## Local Files` も可） | ローカル入力 | 絶対パスが各ノードの `work_dir` にコピーされる |
| `Partition: <name>` / `Max CPUs: <n>` | HPC 配置 | HPC 有効時のみ読まれる。無ければ `ARI_SLURM_PARTITION` / `ARI_SLURM_CPUS` か検出された up パーティションが埋める |
| 本文中の SLURM への言及（`slurm_submit`、`sbatch`、`srun` など） | 投入 / ポーリング / 読取ツールの三点セットを選ぶ | `slurm_submit` + `job_status` + `run_bash` に切り替わる。HPC プロファイルでは `ARI_SLURM_PARTITION` が設定されていればキーワード無しでも同じ |
| `<!-- min_expected_metric: N -->` | 許容最小値 | `WorkflowHints.min_expected_metric` にパースされ、抽出値がすべてこれ未満のノードは failed になる。**数字のみ** — 負の閾値はパースされない |

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
├── skill.yaml             ← 正準マニフェスト（必須・レビュー対象のソース）
├── mcp.json               ← skill.yaml からの派生物。手で編集しない
├── pyproject.toml         ← パッケージ設定
├── README.md              ← ツールの説明と使用例
└── REQUIREMENTS.md        ← 設計仕様
```

`skill.yaml` が正準マニフェストで、`mcp.json` は決定論的な派生物です:
マニフェストを変更したら `python3 scripts/sync_skill_metadata.py --write` で
再生成してください。`scripts/check_skill_manifests.py` は `skill.yaml` の欠落
(`manifest-missing`)、一致しなくなった `mcp.json`(`compat-metadata-drift`)、
`pyproject.toml` と食い違う `version`(`version-drift`)、`complete` でない
`environment_policy` を失敗させます。サーバーが公開するツールはすべて
`skill.yaml` に宣言する必要があります。

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

`ari-core/config/workflow.yaml` の `skills:` ブロックに記述します。`name` は
パイプラインステージが参照する登録スキル名（同梱エントリは `paper-skill` の
ように `<領域>-skill` 規約）で、完全一致が必要です — ステージのディスパッチは
`s.name == stage.skill` で `cfg.skills` を絞り込みます:

```yaml
skills:
  - name: your-skill
    path: /abs/path/to/ari-skill-yourskill
    description: このスキルの説明
    phase: bfts          # bfts | paper | reproduce、またはそのリスト
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
`ari-core/config/workflow.yaml` の `pipeline:` ブロックのみを編集します
（レガシーな `pipeline.yaml` というファイル名もフォールバックとして受理されます）。
コアコードの変更は不要です。

```yaml
pipeline:
  - stage: write_paper
    skill: paper-skill
    tool: write_paper_iterative
    depends_on: [transform_data]
    enabled: true
    phase: paper
    inputs:
      venue: arxiv

  - stage: my_new_stage            # ← ここに追加
    skill: your-skill              # `skills:` の name と一致させる
    tool: your_analysis_tool
    depends_on: [write_paper]
    enabled: true
    phase: paper
    inputs:
      custom_param: value
      nodes_json_path: '{{checkpoint_dir}}/nodes_tree.json'
    outputs:
      file: '{{checkpoint_dir}}/my_new_stage.json'

  - stage: ors_grade
    skill: paper-re-skill
    tool: grade_with_simplejudge
    depends_on: [ors_run_reproduce]
    enabled: true
    phase: paper
```

ステージのキー:
- `skill` / `tool` — 登録スキル名と呼び出す MCP ツール。
- `inputs:`（別名 `input:`）— ツールのキーワード引数。`{{var}}` テンプレート
  置換が効きます（`{{checkpoint_dir}}`、`{{run_id}}`、`{{ari_root}}` など）。
  `params:` は同じ呼び出し引数へマージされる別マッピングで、文字列値には同じ
  `{{var}}` 置換が効きます。ただし `params:` のキーはファイル読み込みの対象外
  で、同名の `inputs:` キーが優先されます。`<key>_from:` ショートハンドは
  チェックポイント相対のファイル名を解決した**うえで**その内容を読み込みます
  （`load_inputs:` も参照）。`args:` というキーはありません。
- `depends_on:` — オーケストレータはトポロジカルソートを行わずファイル順に
  ステージを実行するため、宣言順を依存順に保ってください。依存がスキップ
  されたステージもスキップされます（依存が明示的に `enabled: false` の場合を除く）。
- `phase:` — `bfts` / `paper` / `reproduce`。GUI グラフのグルーピングに使われます。
- `segment:` — `evidence` / `authoring` / `verification`。既定のフル実行では
  無視されますが、セグメント分割実行は有効なセグメントを持たない有効ステージが
  1 つでもあると開始を拒否するため、新しい `pipeline:` ステージにはこれを
  宣言しておく必要があります。
- `skip_if_exists:` — 解決済みパス。それが存在して空でなければ（`.json` の
  場合はさらにトップレベルの `error` キーが無ければ）ステージはスキップされます。
  `skip_if_inputs_unchanged:` はディスクと一致し続けている必要のあるサイドカー
  コントラクトを指し、入力が変わった後に再利用可能な出力が再利用されるのを防ぎます。
- `outputs.file` — ドライバがツールの戻り値を書き出す先。

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
  model: claude-sonnet-4-5

# 任意の OpenAI 互換 API（vLLM、LM Studio など）
llm:
  backend: openai
  model: your-model-name
  base_url: http://your-server:8000/v1
```

`tool_choice` という設定ノブはありません — `ari/llm/client.py` が自分で
（`required` / `auto` を）設定します。LLM がファンクション/ツール呼び出しを
サポートしていない場合は CLI シムバックエンド（`ARI_BACKEND=cli-shim`）を
経由してください。その OpenAI 互換サーバはテキストのツールプロトコルに
フォールバックします。加えて実験ワークフローで `## Required Workflow` を
使用してステップバイステップの実行をガイドしてください。

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
VENUES = [
    {"id": "neurips", "pages": 9},
    {"id": "icpp", "pages": 10},
    {"id": "sc", "pages": 12},
    {"id": "isc", "pages": 12},
    {"id": "arxiv", "pages": 0},     # 無制限
    {"id": "acm", "pages": 10},
    {"id": "your_venue", "pages": 8},  # ← 追加
]
```

### パイプラインでの使用

```yaml
- stage: write_paper
  skill: paper-skill
  tool: write_paper_iterative
  inputs:
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

`ari-core/config/default.yaml`（同梱の BFTS デフォルト）のノード単位タイム
アウトは `timeout_per_node: 7200`（2 時間）です。長時間の MPI ジョブ向けには
そこで引き上げる — または実行ごとに `ARI_TIMEOUT_NODE` で上書き:

```yaml
bfts:
  timeout_per_node: 14400   # 大規模 MPI ジョブ向けに 4 時間
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
        "idempotency_key": "my-unique-key",   # 必須
        "max_nodes": 10
    })
    run_id = result["run_id"]
```

`idempotency_key` は必須引数です: 同じキーは 2 本目のランを投入せず、記録済みの
ハンドルをリプレイします。

### HTTP 経由（CI/CD 向け）

オーケストレーターは `--transport` で選ぶ 2 つのトランスポートを持つ MCP サーバー
です: **stdio**（既定）と **streamable-http**（`http://{host}:{port}/mcp` の MCP。
host は `ARI_ORCHESTRATOR_HTTP_HOST` = `127.0.0.1`、port は
`ARI_ORCHESTRATOR_HTTP_PORT` = 9890）。独自パスを持つ REST/SSE API は存在せず、
HTTP でも**同じ MCP ツール面**を呼びます。`streamable-http` は
`ARI_ORCHESTRATOR_HTTP_TOKENS_FILE` が無ければ起動を拒否します — 認証の無い
ネットワーク制御は提供されません。

---

## 8. BFTS 選択戦略の変更

選択を担うのは `ari/orchestrator/bfts.py` の `BFTS.select_next_node` で、既定では
候補フロンティアに対する **LLM** の判断です。コードに手を入れる前に 2 つの seam が
あります:

- `bfts.deterministic_selector: true` は LLM を完全にバイパスし `_select_fallback`
  でランク付けします（LLM が選べなかったときに走るのと同じ経路）。優先順位は
  まず `has_real_data=True` のノード、次に `_fallback_score` の高い順です。
- `bfts.frontier_score` はそのフォールバックのスコア式を選びます:
  `scientific_plus_diversity`（既定）、`scientific_only`、`depth_penalized`
  （`depth_penalty_lambda * depth` を引く）、`ucb_like`（`ucb_c` でスケールした
  UCB1 風の項を足す）。

本当に新しい戦略 — たとえば多目的のパレート最適選択 — を入れるなら、同ファイルの
`_fallback_score` / `_select_fallback` を編集します:

```python
def _select_fallback(self, candidates: list[Node]) -> Node:
    """候補フロンティアに対するカスタム決定論的選択。"""
    real = [n for n in candidates if n.has_real_data]
    pool = real or candidates
    # 例: 多目的最適化のためのパレート最適選択
    return pareto_select(pool, objectives=["score", "energy"])
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
| ARI 内部ファイルをチェックポイント直下に basename 登録なしで書き出す | `PathManager.is_meta_file` が認識しないファイルは全ノードの `work_dir` にコピーされ、未登録の `.json` はさらに `node_report.json` に role `data_output` として記録される | basename を `PathManager.META_FILES`（`ari/paths.py`）に追加。内部 JSON の場合は `_INTERNAL_JSON_NAMES`（`ari/orchestrator/node_report/builder.py`）にも追加し、`test_new_filenames_are_meta_files` 形式のテスト（`ari-core/tests/test_prompt_provenance.py`）で両方を固定する |

---

## バージョニングと互換性

- すべての skill ツールインターフェースは `pyproject.toml` でバージョン管理
- ツールシグネチャの破壊的変更にはマイナーバージョンのバンプが必要
- `ari-core` は skill の実装ではなくインターフェースに依存（MCP による疎結合）
- ツールへの新しいオプションパラメータの追加は常に後方互換
