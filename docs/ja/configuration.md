# 設定リファレンス

## workflow.yaml（正規の開発者設定）

`workflow.yaml` は ARI パイプライン全体の**唯一の信頼できる情報源**です。
`ari-core/config/workflow.yaml` に配置してください。

skill パスには `{{ari_root}}` を使用してください — これは `$ARI_ROOT` 環境変数またはプロジェクトルートに解決されます。

```yaml
llm:
  backend: openai          # ollama | openai | anthropic
  model: gpt-4o            # モデル識別子
  base_url: ""             # OpenAI の場合は空、Ollama/vLLM の場合は設定

author_name: "Artificial Research Intelligence"

resources:
  cpus: 32                 # 再現性実験のデフォルト CPU 数
  timeout_minutes: 15      # デフォルトのジョブタイムアウト

pipeline:
  - stage: transform_data
    skill: transform-skill
    tool: nodes_to_science_data
    inputs:
      nodes_json_path: '{{ckpt}}/nodes_tree.json'
      llm_model: '{{llm.model}}'
      llm_base_url: '{{llm.base_url}}'
    outputs:
      file: '{{ckpt}}/science_data.json'

  # ... 追加ステージ (generate_figures, search_related_work, write_paper, ...)

skills:
  - name: memory-skill
    path: "{{ari_root}}/ari-skill-memory"
  - name: idea-skill
    path: "{{ari_root}}/ari-skill-idea"
  - name: hpc-skill
    path: "{{ari_root}}/ari-skill-hpc"
  - name: evaluator-skill
    path: "{{ari_root}}/ari-skill-evaluator"
  - name: transform-skill
    path: "{{ari_root}}/ari-skill-transform"
  - name: plot-skill
    path: "{{ari_root}}/ari-skill-plot"
  - name: paper-skill
    path: "{{ari_root}}/ari-skill-paper"
  - name: paper-re-skill
    path: "{{ari_root}}/ari-skill-paper-re"
```

## 環境変数

| 変数 | 説明 | デフォルト |
|----------|-------------|---------|
| `ARI_MAX_NODES` | BFTS で探索するノードの最大数 | `50` |
| `ARI_PARALLEL` | 同時実行ノード数 | `1` |
| `ARI_EXECUTOR` | 実行バックエンド: `local`, `slurm`, `pbs`, `lsf` | `local` |
| `ARI_SLURM_PARTITION` | SLURM パーティション名 | (なし) |
| `SLURM_LOG_DIR` | SLURM 出力ファイルの保存先 | (なし) |
| `OLLAMA_HOST` | Ollama サーバーアドレス | `127.0.0.1:11434` |
| `OPENAI_API_KEY` | OpenAI API キー | (なし) |
| `ANTHROPIC_API_KEY` | Anthropic API キー | (なし) |

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
  model: claude-opus-4-5
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
