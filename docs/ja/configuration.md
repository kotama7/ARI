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
  # ─── EAR キュレーション/公開/最終化 (v0.7.0) ───
  - stage: ear_curate
    skill: transform-skill
    tool: curate_ear
    depends_on: [generate_ear]
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'
    outputs:
      file: '{{checkpoint_dir}}/ear_curate.status.json'
  - stage: finalize_paper
    skill: paper-skill
    tool: inject_code_availability
    depends_on: [write_paper, ear_curate]
    # ear_published/manifest.lock と publish_record.json から ref/sha/doi
    # を自動ロードし、\codeavailability/\codedigest/\coderef マクロを
    # full_paper.tex に注入。バンドル無しなら静かにスキップ。
  - stage: ear_publish
    skill: transform-skill
    tool: publish_ear
    depends_on: [ear_curate]
    enabled: false           # opt-in。true にするか publish=true を渡す
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'
      backend: ari-registry
      visibility: staged
      dry_run: false
    outputs:
      file: '{{checkpoint_dir}}/publish_record.json'
  - stage: merge_reviews
    skill: paper-skill
    tool: merge_reviews
    depends_on: [review_paper, vlm_review_figures]
    # text + VLM 査読出力の構造合成 (LLM 不使用)。

  # ─── ORS オートルーブリック再現性 (PaperBench, v0.7.0) ───
  # 旧 `reproducibility_check` を置き換える。
  - stage: ors_generate_rubric
    skill: replicate-skill
    tool: generate_rubric
    depends_on: [write_paper]
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      output_path: '{{checkpoint_dir}}/ors_rubric.json'
      target_leaf_count: 0     # 0 = 論文長から自動算定
  - stage: ear_publish          # v0.7.0+: デフォルト有効、local-tarball
    skill: transform-skill
    tool: publish_ear
    depends_on: [ear_curate]
    enabled: true
    inputs:
      backend: local-tarball    # 依存ゼロ。チェックポイント横に bundle.tar.gz
      visibility: staged
  - stage: ors_seed_sandbox     # v0.7.0+: EAR バンドルから決定論的に種をまく
    skill: paper-re-skill
    tool: fetch_code_bundle
    depends_on: [ear_publish]
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'    # publish_record.json から ref 自動読込
      dest: '{{checkpoint_dir}}/repro_sandbox'
  - stage: ors_build_reproduce  # v0.7.0+: LLM フォールバック (上で seed 済なら skip)
    skill: paper-re-skill
    tool: build_reproduce_sh
    depends_on: [ors_generate_rubric, ors_seed_sandbox, finalize_paper]
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      output_dir: '{{checkpoint_dir}}/repro_sandbox'
      overwrite: false
  - stage: ors_run_reproduce
    skill: paper-re-skill
    tool: run_reproduce        # Phase 1 (reproduce.sh をサンドボックス実行)
    depends_on: [ors_generate_rubric, ors_build_reproduce]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      repo_dir: '{{checkpoint_dir}}/repro_sandbox'
      sandbox_kind: ''         # auto: slurm → docker → apptainer → singularity → local
      timeout_global_sec: 0    # 0 = rubric.reproduce_contract.max_runtime_sec
      partition: ''            # 空 → ARI_SLURM_PARTITION → launch_config.json
      cpus: 0                  # 空 → ARI_SLURM_CPUS (default 8)
      walltime: ''             # 空 → ARI_SLURM_WALLTIME → timeout から算出
  - stage: ors_grade
    skill: paper-re-skill
    tool: grade_with_simplejudge   # Phase 2 (PaperBench SimpleJudge via LiteLLM)
    depends_on: [ors_run_reproduce]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      repo_dir: '{{checkpoint_dir}}/repro_sandbox'
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      n_runs: 3
      judge_model: gpt-5-mini  # LiteLLM 認識可能な任意のモデル ID

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
  # v0.7.0: PaperBench 形式オートルーブリック生成器・監査器
  - name: replicate-skill
    path: "{{ari_root}}/ari-skill-replicate"
    phase: paper
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
| `ARI_MODEL_RUBRIC_GEN` | `replicate-skill.generate_rubric` の生成 LLM (v0.7.0) | `gemini/gemini-2.5-pro` |
| `ARI_MODEL_RUBRIC_AUDIT` | `audit_rubric` の監査 LLM (生成器とは独立) | `anthropic/claude-opus-4-7` |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | `generate_rubric` の目標葉数の上書き。`0` / 未設定で論文長から自動 (~1葉/75語、[50,400] にクランプ)。GUI Wizard の "Target leaves" 欄。 | (未設定) |
| `ARI_RUBRIC_GEN_TEMPERATURE` | 生成器 temperature の上書き。GUI Wizard の "Temperature" 欄。 | (未設定) |
| `ARI_RUBRIC_GEN_TWO_STAGE` | 二段階生成（スケルトン + 並列サブツリー）の強制 ON/OFF (`1`/`true`/`on` vs `0`/`false`/`off`)。単一コール比で葉数約 4 倍・深さ +1〜2 層、API トークン消費約 5 倍。未設定時は kwarg デフォルト（現状 ON）。GUI Wizard の "二段階生成" トグル。 | (未設定、既定 ON) |
| `ARI_MODEL_REPLICATE` | `build_reproduce_sh` (論文 → reproduce.sh, v0.7.0) のリプリケータ LLM | `claude-opus-4-7` |
| `ARI_MODEL_JUDGE` | `grade_with_simplejudge` (PaperBench Phase 2, v0.7.0; LiteLLM 経由でプロバイダ自由) の判定 LLM | `gpt-5-mini` |
| `ARI_MODEL_LINEAGE` | `decide_lineage_action` の判定 LLM (lineage decision, v0.7.0)。未指定時は `ARI_MODEL_EVAL` → `ARI_MODEL` → `ARI_LLM_MODEL` → `gpt-4o-mini` の順にフォールバック | (auto) |
| `ARI_MODEL_ROOT_SELECT` | VirSci プールから `ideas[0]` を選び直す LLM (lineage decision, v0.7.0)。フォールバック順は `ARI_MODEL_LINEAGE` と同じ | (auto) |
| `ARI_PHASE1_SANDBOX` | Phase 1 サンドボックス: `auto` / `slurm` / `docker` / `apptainer` / `singularity` / `local` | `auto` |
| `ARI_SLURM_WALLTIME` | SLURM Phase 1 の `--time` HH:MM:SS (v0.7.0, 復元)。空ならルーブリックの `max_runtime_sec` から算出。 | (auto) |
| `ARI_PHASE1_DOCKER_IMAGE` | docker サンドボックスのコンテナイメージ | `ubuntu:24.04` |
| `ARI_PHASE1_APPTAINER_IMAGE` / `ARI_PHASE1_SINGULARITY_IMAGE` | Apptainer/Singularity サンドボックスのイメージ | `docker://ubuntu:24.04` |
| `ARI_PUBLISH_DRYRUN` | `ari ear publish --dry-run` を強制 (CI 安全, v0.7.0) | (off) |
| `ARI_REGISTRY_DATA` | `ari registry serve` の sqlite + artifact 保管 root | `~/.ari/registry-data` |
| `ARI_REGISTRY_TOKEN` | `ari clone ari://...` / `ari ear publish --backend ari-registry` 用 bearer token | (なし) |
| `ARI_REPRO_CLONE_POLICY` | 再現性サンドボックス git shim ポリシー: `passthrough` / `deny` / `warn` | `passthrough` |

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

## Plan Promote (v0.7.0+)

`plan_promote` は VirSci の experiment plan を **チェックポイント内**の
`experiment.md` にどう展開するかを制御します。CLI で渡したユーザの
ソース `experiment.md` は **改変されません** — チェックポイント側のコピー
にだけ HTML コメントマーカで囲んだ自動追記ブロックが付きます (再実行で
重複しない idempotent)。

```yaml
plan_promote: index_only          # full | index_only | off
```

| Mode | 追加内容 | 典型サイズ |
|---|---|---|
| `full` | 選定 idea + plan §タグ本文 + Alternatives | ~5 KB |
| `index_only` (default) | 選定 idea + plan §タグタイトル + Alternatives | ~1.5 KB |
| `off` | (追記なし) | 0 |

Phase 3 の評価器と BFTS expand idea_ctx は **idea.json の生 plan** を読むので、
`full` か `index_only` かは主に **人間と paper-skill が experiment.md で何を
読むか** だけの違いです。

## Lineage Decision (v0.7.0+)

BFTS が停滞したとき、LLM judge が「探索継続 / 代替案へ切替 / 並列展開 /
終了」のいずれかを判断します。LLM の出力は 4 アクションに制限され、
代替案 pool 内の index でのみ有効、エラー時は無条件に `continue` に
degrade するため BFTS ループはこの hook で詰まりません。

```yaml
lineage_decision:
  mode: stagnation_rule           # off | stagnation_rule | every_node
  stagnation_window: 5            # composite score の window
  stagnation_threshold: 0.02      # max-min < threshold で停滞
  min_nodes_before_decision: 3    # 序盤での発火を抑制
  rate_limit_per_run: 5           # 1 run あたりの escalation 上限
```

| Mode | トリガ | コスト |
|---|---|---|
| `off` | 発火しない | 0 |
| `stagnation_rule` (default) | 連続 `stagnation_window` ノードで composite が flat | 0–`rate_limit_per_run` LLM call |
| `every_node` | 各 BFTS step 後 (LLM が timing 自体も判断) | 1 LLM call/node |

発火した全 decision (continue 含む) は `{checkpoint}/lineage_decisions.jsonl`
に追記され、後から「どこで停滞 / 切替 / 終了したか」が完全に再現できます。
`root_idea_selection` も同じファイルに別 `trigger` で記録されます。

## Root Idea Selection (v0.7.0+)

VirSci が `idea.json` を書いた直後、LLM が venue rubric と ancestor
research thread を見て「`ideas[0]` を据え置きにするか、`ideas[N]` に
入れ替えるか」を判定します。Default は `ideas[0]` (= VirSci スコア順)
維持、LLM 出力が pool 範囲外なら同じく `ideas[0]` にフォールバック。
起動時 1 LLM call、ノード単位の追加コストはなし。

```yaml
root_idea_selection:
  enabled: true                   # v0.7.0+ default
```

決定は `lineage_decisions.jsonl` に
`{trigger: "root_idea_selection", action: "root_swap" | "root_keep"}`
で記録され、`idea.json` の `_root_choice` にも provenance として
保存されます。子 (recursion) は `_inherited_from` または `_root_choice`
を検出して再選択を skip します。

## BFTS チューニング

環境変数で BFTS の動作を制御します:

```bash
export ARI_MAX_NODES=12      # 最大 12 ノードを探索（小規模実行）
export ARI_PARALLEL=4        # 4 ノードを同時実行
export ARI_EXECUTOR=slurm    # 各ノードを SLURM ジョブとして投入
```

または `workflow.yaml` の `bfts:` セクションでデフォルト値を設定できます（バージョンがサポートしている場合）。

---

## EAR キュレーション (`ear/publish.yaml`) — v0.7.0+

キュレーションは `{checkpoint}/ear/` のうち何を公開対象にするかを著者が
allowlist で制御し、`{checkpoint}/ear_published/` + `manifest.lock`
に出力する仕組みです。ari-core 側には **built-in deny list** が組み込まれ
ており、`include` よりも常に強く効きます (機密ファイルの誤公開防止)。

### スキーマ (`ari-core/ari/schemas/publish.schema.json`)

```yaml
# 例: <checkpoint>/ear/publish.yaml
include:                     # ear/ からの相対 glob (allowlist)
  - "README.md"
  - "LICENSE"
  - "reproduce.sh"
  - "code/**"                # contributing chain の verbatim ソース
  - "data/**"                # アップロード入力のみ。実験出力は含めない
  - "figures/**"             # top-level の figures
  - "environment.json"
# 注: EVOLUTION.md と _provenance.json は ear/ の外（checkpoint root）に置かれる
# ARI 監査ログで、公開バンドルの対象外です。
exclude: []                  # ユーザ指定の除外 (include の後に適用)
max_file_mb: 100             # この値を超える allowlist 該当ファイルは明示的にエラー
visibility: staged           # staged|public|unlisted|private-token|embargoed-until:YYYY-MM-DD
required: false              # true のとき publish 失敗は paper pipeline を hard-fail させる
auto_promote: false          # true のとき再現性通過後に staged→public を自動 promote
license: MIT                 # SPDX id。同じ id から ear/LICENSE が生成される
backend: ari-registry        # ari-registry|gh|zenodo|s3|local-tarball (CLI --backend が優先)
```

v0.6.0 旧パス (`code/<node_id>/**`, `data/raw_metrics.json`, `logs/**`, `reproducibility/**`) は v0.7.0 の `generate_ear` では生成されません。古い `publish.yaml` からは削除してください。詳細は `docs/skills.md` を参照。

### Built-in deny パターン

`include` に該当しても **常に** 除外:

```
.env, .env.*, **/.env, **/.env.*
**/secrets/**, secrets/**
**/*.pem, **/*.key
**/id_rsa, **/id_ed25519
```

除外ファイルのパスは `manifest.lock` に記録されません (件数のみ)。
manifest 自体から機密ファイル名が漏れない設計です。

### 動作

- `publish.yaml` が **無い** とき、`ear_curate` ステージは静かに skip され、
  論文の Code Availability 節も省略されます (v0.6.0 チェックポイントと完全後方互換)。
- **bundle digest** (`manifest.lock` の `bundle_sha256`) はソート済みファイル
  レコード (path + size + sha256) の正規化 JSON の sha256 で、マシン間で再現可能。
  論文に焼き込まれる「永続的真実」となる値です。
- キュレーションは **atomic**: `max_file_mb` 超過などで hard-fail した場合でも、
  直前の正常な `ear_published/` は破壊されません。

### CLI

```bash
# Curate
ari ear curate <checkpoint>            # 整形出力
ari ear curate <checkpoint> --json     # 機械可読
ari ear status <checkpoint>            # manifest サマリ表示

# Publish & promote
ari ear publish <checkpoint> --backend ari-registry --visibility staged
ari ear promote <checkpoint> --target public
```

### Pipeline 統合

`workflow.yaml` の paper パイプラインに `ear_curate` ステージが
`generate_ear` と `generate_figures` の間に挿入されます。transform
skill の `curate_ear` MCP ツールを呼び、`publish.yaml` 不在時は no-op。
