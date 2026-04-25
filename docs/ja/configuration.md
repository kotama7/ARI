# 設定リファレンス

## workflow.yaml（正規の開発者設定）

`workflow.yaml` は ARI パイプライン全体の**唯一の信頼できる情報源**です。
`ari-core/config/workflow.yaml` に配置してください。

skill パスには `{{ari_root}}` を使用してください — これは `$ARI_ROOT` 環境変数またはプロジェクトルートに解決されます。

```yaml
llm:
  backend: openai          # ollama | openai | anthropic
  model: gpt-5.2           # モデル識別子
  base_url: ""             # OpenAI の場合は空、Ollama/vLLM の場合は設定

author_name: "Artificial Research Intelligence"

resources:
  cpus: 48                 # 再現性実験のデフォルト CPU 数
  timeout_minutes: 60      # デフォルトのジョブタイムアウト
  executor: slurm          # ジョブエグゼキュータ: slurm / local / pbs / lsf

# BFTS フェーズステージ（ツリー探索中に順次実行）
bfts_pipeline:
  - stage: generate_idea
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
  - stage: select_and_run
    skill: hpc-skill
    phase: bfts
  - stage: evaluate
    skill: evaluator-skill
    tool: evaluate_node
    phase: bfts
  - stage: frontier_expand
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
    loop_back_to: select_and_run

# Post-BFTS パイプラインステージ
pipeline:
  - stage: search_related_work
    skill: web-skill
    tool: collect_references_iterative
    skip_if_exists: '{{ckpt}}/related_refs.json'
    # ...
  - stage: transform_data
    skill: transform-skill
    tool: nodes_to_science_data
    inputs:
      nodes_json_path: '{{ckpt}}/nodes_tree.json'
      llm_model: '{{llm.model}}'
      llm_base_url: '{{llm.base_url}}'
    outputs:
      file: '{{ckpt}}/science_data.json'
    skip_if_exists: '{{ckpt}}/science_data.json'
  - stage: generate_figures
    skill: plot-skill
    tool: generate_figures_llm
    depends_on: [transform_data]
    # ...
  - stage: write_paper
    skill: paper-skill
    tool: write_paper_iterative
    depends_on: [search_related_work, generate_figures]
    # ...
  - stage: review_paper
    skill: paper-skill
    tool: review_compiled_paper
    depends_on: [write_paper]
    # ...
  - stage: reproducibility_check
    skill: paper-re-skill
    # ari-core/ari/agent/react_driver.py が駆動。単一 tool ではなく、
    # paper-re が決定論的な両端を担い、ReAct ループは phase リストに
    # `reproduce` を含む MCP スキルで動作します。
    pre_tool: extract_repro_config
    post_tool: build_repro_report
    depends_on: [write_paper]
    react:
      agent_phase: reproduce
      max_steps: 40
      final_tool: report_metric
      # エージェントを checkpoint ルートから隔離。パス検証によって
      # sandbox 外のファイルを参照するツール引数は拒否されます
      # (論文 .tex は allow-list 扱い)。
      sandbox: '{{checkpoint_dir}}/repro_sandbox'
      system_prompt: |
        You are a reproducibility engineer...
      user_prompt: |
        Target: reproduce {{pre.metric_name}} = {{pre.claimed_value}}
        ...

retrieval:
  backend: semantic_scholar    # semantic_scholar | alphaxiv | both
  alphaxiv_endpoint: https://api.alphaxiv.org/mcp/v1

# ── 論文査読 (ルーブリック駆動、AI Scientist v1/v2 互換) ─────────────
# CLI フラグ (--rubric、--fewshot-mode、--num-reviews-ensemble、
# --num-reflections) または環境変数 (ARI_RUBRIC、ARI_FEWSHOT_MODE、
# ARI_NUM_REVIEWS_ENSEMBLE、ARI_NUM_REFLECTIONS) で上書き可能。
# ari-core/config/reviewer_rubrics/ に同梱されている 16 種のルーブリック:
#   neurips (既定、v2 互換) | iclr | icml | cvpr | acl | sc | osdi
#   | usenix_security | stoc | siggraph | chi | icra | nature
#   | journal_generic | workshop | generic_conference
# 加えて内蔵の `legacy` フォールバック (v0.5 スキーマ)。新しい venue は
# <id>.yaml を reviewer_rubrics/ に追加するだけで対応 (コード変更不要)。
#
# Few-shot コーパス管理
# --------------------
# reviewer_rubrics/fewshot_examples/<rubric>/ 配下のファイルは GUI
# (New Experiment Wizard → Paper Review → Few-shot サンプル) または
# scripts/fewshot/sync.py から管理できます。viz サーバが公開する REST:
#   GET  /api/rubrics                           rubric 一覧 (Wizard 用)
#   GET  /api/fewshot/<rubric>                  fewshot 例の一覧
#   POST /api/fewshot/<rubric>/sync             manifest.yaml から取得
#   POST /api/fewshot/<rubric>/upload           1 件アップロード
#   POST /api/fewshot/<rubric>/<example>/delete 1 件削除

memory:
  # v0.6.0: Letta が唯一の本番バックエンドです。ここでの値はスキル
  # 子プロセスの環境変数として読み込み時に注入されます。エージェント
  # 用チャット LLM は `letta/letta-free` に固定されています
  # (ari-skill-memory は archival_insert / archival_search だけを
  # 呼び、チャットメッセージは送らないためピッカーは無効でした)。
  backend: letta
  letta:
    base_url: http://localhost:8283
    collection_prefix: ari_
    embedding_config: letta-default

container:
  mode: auto                   # auto | docker | singularity | apptainer | none
  image: ""                    # コンテナイメージ名（空 = コンテナ未使用）
  pull: on_start               # always | on_start | never

skills:
  # `phase` は ReAct エージェントがどの pipeline-phase でそのスキルの
  # MCP ツールを見られるかを制御します。単一文字列なら一つの phase
  # のみ、配列なら複数の phase にオプトインします。`reproduce` に
  # タグ付けされたスキルは再現性 ReAct (上の reproducibility_check
  # ステージ参照) に露出します。`memory-skill` / `transform-skill` /
  # `evaluator-skill` はエージェントが BFTS フェーズの成果物に
  # 到達できないよう、意図的に reproduce から除外しています。
  - name: web-skill
    path: "{{ari_root}}/ari-skill-web"
    phase: [paper, reproduce]
  - name: plot-skill
    path: "{{ari_root}}/ari-skill-plot"
    phase: paper
  - name: paper-skill
    path: "{{ari_root}}/ari-skill-paper"
    phase: paper
  - name: paper-re-skill
    path: "{{ari_root}}/ari-skill-paper-re"
    phase: paper
  - name: memory-skill
    path: "{{ari_root}}/ari-skill-memory"
    phase: bfts
  - name: evaluator-skill
    path: "{{ari_root}}/ari-skill-evaluator"
    phase: bfts
  - name: idea-skill
    path: "{{ari_root}}/ari-skill-idea"
    phase: none
  - name: hpc-skill
    path: "{{ari_root}}/ari-skill-hpc"
    phase: [bfts, reproduce]
  - name: coding-skill
    path: "{{ari_root}}/ari-skill-coding"
    phase: [bfts, reproduce]
  - name: transform-skill
    path: "{{ari_root}}/ari-skill-transform"
    phase: paper
  - name: benchmark-skill
    path: "{{ari_root}}/ari-skill-benchmark"
    phase: bfts
  - name: vlm-skill
    path: "{{ari_root}}/ari-skill-vlm"
    phase: [paper, reproduce]
```

## 環境変数

| 変数 | 説明 | デフォルト |
|----------|-------------|---------|
| `ARI_MAX_NODES` | BFTS で探索するノードの最大数 | `50` |
| `ARI_PARALLEL` | 同時実行ノード数 | `1` |
| `ARI_EXECUTOR` | 実行バックエンド: `local`, `slurm`, `pbs`, `lsf` | `local` |
| `ARI_SLURM_PARTITION` | SLURM パーティション名 | (なし) |
| `ARI_SLURM_CPUS` | SLURM ジョブの CPU 数オーバーライド | (自動検出) |
| `SLURM_LOG_DIR` | SLURM 出力ファイルの保存先 | (なし) |
| `OLLAMA_HOST` | Ollama サーバーアドレス | `127.0.0.1:11434` |
| `OPENAI_API_KEY` | OpenAI API キー | (なし) |
| `ANTHROPIC_API_KEY` | Anthropic API キー | (なし) |
| `ARI_RETRIEVAL_BACKEND` | 論文検索バックエンド: `semantic_scholar` / `alphaxiv` / `both` | `semantic_scholar` |
| `VLM_MODEL` | 図レビュー用 VLM モデル | `openai/gpt-4o` |
| `ARI_ORCHESTRATOR_PORT` | orchestrator スキルの HTTP ポート | `9890` |
| `LETTA_BASE_URL` | Letta サーバエンドポイント | `http://localhost:8283` |
| `LETTA_API_KEY` | Letta Cloud で必須 | (なし) |
| `LETTA_EMBEDDING_CONFIG` | アーカイバルメモリ用の埋め込みハンドル（エージェントのチャット LLM は ARI から呼び出さないため `letta/letta-free` に固定） | `letta-default` |
| `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA` | `auto` / `pip` / `docker` / `singularity` / `none` | `auto` |
| `ARI_MEMORY_LETTA_TIMEOUT_S` | 呼び出しごとのタイムアウト | `10` |
| `ARI_MEMORY_LETTA_OVERFETCH` | 祖先ポストフィルタ用のオーバーフェッチ K | `200` |
| `ARI_MEMORY_LETTA_DISABLE_SELF_EDIT` | Letta self-edit を無効化 (CoW セーフ) | `true` |
| `ARI_MEMORY_ACCESS_LOG` | `{checkpoint}/memory_access.jsonl` を有効化 | `on` |
| `ARI_MEMORY_AUTO_RESTORE` | `ari resume` 時にバックアップを自動復元 | `true` |
| `ARI_RUBRIC` | 査読 rubric_id (例: `neurips`、`sc`、`nature`) | `neurips` |
| `ARI_FEWSHOT_MODE` | `static` / `dynamic` | `static` |
| `ARI_NUM_REVIEWS_ENSEMBLE` | 独立査読者数 | `1` |
| `ARI_NUM_REFLECTIONS` | self-reflection ループ回数 | `5` |

## メモリバックエンド (Letta)

v0.6.0 で決定論的 JSONL メモリストアを [Letta](https://docs.letta.com)
へ置き換えました。Letta は次の 4 通りで動作します:

| モード | 要件 | ストア | 備考 |
|------|------|--------|------|
| Docker Compose | `docker` + `docker compose` | Postgres | ノートPC既定、pre-filter 対応 |
| Singularity / Apptainer | `singularity` / `apptainer` | Postgres | HPC 既定、SLURM 認識のデータ DIR |
| pip (コンテナレス) | Python 3.10+ | SQLite | ancestor スコープは over-fetch + post-filter にフォールバック |
| Letta Cloud | API キー | マネージド | `LETTA_BASE_URL=https://api.letta.com` |

`ari setup` が最適なモードを自動検出します。`ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA`
で強制指定も可能。start/stop/health/backup/restore は `ari memory` サブ
コマンドが扱います — 詳細は `docs/ja/cli_reference.md` を参照。

v0.5.x チェックポイントのワンショット移行:

```bash
ari memory migrate --checkpoint /path/to/ckpt --react
```

## LLM バックエンド

### Ollama（ローカル、オフライン HPC に推奨）

```yaml
llm:
  backend: ollama
  model: qwen3:32b
  base_url: http://127.0.0.1:11434
```

### OpenAI

```yaml
llm:
  backend: openai
  model: gpt-4o
```

### Anthropic

```yaml
llm:
  backend: anthropic
  model: claude-sonnet-4-5
```

### 任意の OpenAI 互換 API（vLLM、LM Studio など）

```yaml
llm:
  backend: openai
  model: your-model-name
  base_url: http://your-server:8000/v1
```

---

## workflow.yaml のテンプレート変数

`inputs:` 内の任意の値で `{{variable}}` 置換がサポートされています:

| 変数 | 値 |
|----------|-------|
| `{{ckpt}}` | チェックポイントディレクトリのパス |
| `{{ari_root}}` | ARI プロジェクトルート（`$ARI_ROOT` または自動検出） |
| `{{llm.model}}` | `llm:` セクションの LLM モデル名 |
| `{{llm.base_url}}` | `llm:` セクションの LLM ベース URL |
| `{{resources.cpus}}` | `resources:` セクションの CPU 数 |
| `{{resources.timeout_minutes}}` | `resources:` セクションのタイムアウト |
| `{{stages.<name>.outputs.file}}` | 完了したステージの出力ファイルパス |
| `{{author_name}}` | トップレベル設定の著者名 |
| `{{vlm_feedback}}` | VLM レビューフィードバック（`vlm_review_figures` からのループバック時に注入） |
| `{{paper_context}}` | 科学的に整形された実験サマリ |
| `{{keywords}}` | LLM 生成検索キーワード |

---

## skip_if_exists バリデーション

`skip_if_exists` が指定されたステージは、出力ファイルが以下の場合に**再実行**されます:
- 存在しない
- 空である
- トップレベルに `"error"` キーを含む JSON ファイルである

これにより、壊れた出力が下流のステージを暗黙的にブロックすることを防止します。

---

## BFTS チューニング

環境変数で BFTS の動作を制御します:

```bash
export ARI_MAX_NODES=12      # 最大 12 ノードを探索（小規模実行）
export ARI_PARALLEL=4        # 4 ノードを同時実行
export ARI_EXECUTOR=slurm    # 各ノードを SLURM ジョブとして投入
```

または `workflow.yaml` の `bfts:` セクションでデフォルト値を設定できます（バージョンがサポートしている場合）。
