---
sources:
  - path: ari-skill-hpc/src/server.py
    role: implementation
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
last_verified: 2026-05-26
---

# MCP Skills リファレンス

Skills は ARI エージェントにツールを提供する MCP サーバーです。ツールは可能な限り決定論的であり、LLM を使用するツールは明示的に注記されています。**全 14 skill**（デフォルト 13、追加 1）。v0.7.0 で PaperBench 形式の再現性フロー用に `ari-skill-replicate` が追加されました。

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

#### `generate_section(section, context, venue="arxiv", nodes_json_path="", refs_json="")`

LLM を使用して LaTeX セクションを生成します。セクションの種類: `introduction`, `related_work`, `method`, `experiment`, `conclusion`。

#### `compile_paper(tex_dir, main_file="main.tex")`

pdflatex コンパイルを実行します。成功ステータスとエラーメッセージを返します。

#### `check_format(venue, pdf_path)`

投稿先の要件に対して論文フォーマットを検証します（ページ数など）。

#### `review_section(latex, context, venue="arxiv")`

LaTeX セクションを査読します。強み、弱み、提案を返します。

#### `revise_section(section, latex, feedback, context, venue="arxiv")`

査読フィードバックに基づいて LaTeX セクションを修正します。

#### `write_paper_iterative(experiment_summary="", context="", nodes_json_path="", refs_json="", figures_manifest_json="", science_data_json="", venue="arxiv", max_revision_rounds=2, author_name="")`

反復的な下書き → 査読 → 修正ループによる完全な論文生成。主要なパイプラインツール。

#### `review_compiled_paper(tex_path, pdf_path, figures_manifest_json, experiment_summary, rubric_id="", vlm_findings_json="", num_reflections=None, num_fs_examples=None, num_reviews_ensemble=None)`

**AI Scientist v1/v2 互換** のルーブリック駆動論文査読 (Nature / arXiv:2408.06292
Appendix A.4 準拠)。`ari-core/config/reviewer_rubrics/<rubric_id>.yaml` を
読み込み、`score_dimensions` / `text_sections` / `decision` スキーマから
プロンプトを動的生成。VLM の図ごとの所見 (score / issues / suggestions) を
査読者ノートとしてプロンプトに注入し、Few-shot 例を先頭に付加、Self-reflection
ループで自己批判・改訂を行い、ルーブリック準拠の JSON で出力。

同梱ルーブリック (`ari-core/config/reviewer_rubrics/` に 16 個の YAML):

| 系統 | rubric_id |
|---|---|
| ML カンファレンス | `neurips` (既定、v2 互換) / `iclr` / `icml` / `cvpr` / `acl` |
| システム / HPC | `sc` / `osdi` / `usenix_security` |
| 理論 / グラフィックス | `stoc` / `siggraph` |
| HCI / ロボティクス | `chi` / `icra` |
| ジャーナル / 汎用 | `nature` / `journal_generic` / `workshop` / `generic_conference` |

`reviewer_rubrics/` に YAML を 1 枚追加するだけで新しい venue を拡張可能
(コード変更不要)。各ルーブリックは `score_dimensions` / `text_sections` /
`decision` ルール、実行パラメータ、P2 決定論用の SHA256 ハッシュを宣言します。

ルーブリック解決順序: 明示的な `rubric_id` 引数 → `ARI_RUBRIC` 環境変数 →
`neurips` → 内蔵 `legacy` フォールバック (v0.5 スキーマ、`rubric_id` も
合致 YAML も解決できないときに使用)。

Nature Ablation 由来の既定値:

- `num_reflections: 5` — +2% balanced accuracy
- `num_fs_examples: 1` — +2% accuracy (ICLR reviewer guidelines の 1-shot)
- `num_reviews_ensemble: 1` — アンサンブルは精度ではなく分散のみ改善
- `temperature: 0.75`

モデル: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`。

**アンサンブル + Area Chair メタ査読 (内蔵):** `review_compiled_paper` は
アンサンブル経路経由で N 名の独立査読者エージェント（温度ジッタ付き、AI
Scientist v1 best-config 方式）を実行します。N>1 のときは Area Chair
メタ査読も内部で走り、`ensemble_reviews: [...]` と `meta_review: {...}` が
出力に同梱されます。N の解決順: 明示引数 > `ARI_NUM_REVIEWS_ENSEMBLE` env >
`rubric.params.num_reviews_ensemble` (既定 1)。N=1 は単一査読と等価です。

#### `list_rubrics()`

利用可能なルーブリックの一覧 (id, venue, domain, version, SHA256 hash, path)
を返します。viz API `/api/rubrics` と New Experiment Wizard のドロップダウン
で使用されます。

#### `inject_code_availability(tex_path, ref="", sha256="", doi="", license_id="", checkpoint_dir="")` — v0.7.0

`finalize_paper` ステージで実行されます。`ear_published/manifest.lock` と `publish_record.json` から `ref` / `bundle_sha256` / `doi` を自動ロードし、機械可読な `\codeavailability{}` / `\codedigest{}` / `\coderef{}` マクロと人間可読な Code Availability セクションを `full_paper.tex` に注入します。digest が信頼の起点となり、読者は registry を信頼することなく `ari clone <ref> --expect-sha256 <baked-digest>` で検証可能です。キュレート済みバンドルが無ければ静かにスキップ（v0.6.0 checkpoint の互換維持）。

#### `merge_reviews(review_report_path, vlm_review_path="")` — v0.7.0

`review_report.json`（テキスト査読）と `vlm_review.json`（VLM 図表レビュー）を構造的にマージするポストホック処理。完全に決定論的、LLM なし。`vlm_figure_review` と `_review_composition` メタデータを付与して GUI / CLI の両出力を出典付きで表示できるようにします。上流ステージは独立性（AI Scientist v2 の `perform_review` 契約）を保ち、ここで初めて統合されます。

##### Few-shot コーパス管理

`ari-core/config/reviewer_rubrics/fewshot_examples/<rubric>/` 配下のファイルは、**New Experiment Wizard → Paper Review → Few-shot サンプル** サブパネル (GUI)、または `scripts/fewshot/sync.py` (CLI) から管理できます。

GUI 操作:

- **Auto-sync**: サーバ側で `scripts/fewshot/sync.py --venue <rubric>` を実行し、`manifest.yaml` 記載のエントリを取得。デフォルトで AI Scientist v2 の 3 本 (`132_automated_relational` / `2_carpe_diem` / `attention`) を Apache-2.0 の `SakanaAI/AI-Scientist-v2` リポジトリから pull。
- **Upload**: rubric スキーマに沿った JSON + 任意の `.txt` 抜粋 + 任意の PDF (base64) を受け付け、`_source: "GUI upload (rubric=<id>)"` を自動付与。
- **Delete**: 指定 example の全拡張子を削除。

REST エンドポイント:

- `GET  /api/fewshot/<rubric>`
- `POST /api/fewshot/<rubric>/sync`
- `POST /api/fewshot/<rubric>/upload`
- `POST /api/fewshot/<rubric>/<example>/delete`

すべて `reviewer_rubrics/` に存在しない rubric は拒否し、`../` / スラッシュは入力から除去します。

---

## ari-skill-paper-re

PaperBench (arXiv:2504.01848) **SimpleJudge** を用いた再現性採点。**LLM: Yes**（採点は upstream `SimpleJudge` 内の LLM 呼び出し。ARI 側はこのスキルで追加の LLM 呼び出しを行いません）。

v0.7.0 で v0.6.0 の LLM 駆動判定パスは、PaperBench をコアとする決定的なエンドツーエンドのチェーンに置き換えられました:

```
ors_generate_rubric  (replicate-skill)    → ors_rubric.json + ors_rubric.meta.json
ear_publish          (transform-skill)    → bundle.tar.gz + publish_record.json (local-tarball デフォルト)
ors_seed_sandbox     (paper-re-skill)     → repro_sandbox/{reproduce.sh, code/...}
                                              (決定論的; fetch_code_bundle ← publish_record.json)
ors_build_reproduce  (paper-re-skill)     → repro_sandbox/{reproduce.sh, source files}
                                              (LLM フォールバック; seed 済なら skip)
ors_run_reproduce    (paper-re-skill)     → ors_phase1.json   (Phase 1: reproduce.sh をサンドボックスで実行)
ors_grade            (paper-re-skill)     → ors_grade.json    (Phase 2: SimpleJudge で葉ノード採点)
```

EAR が ON の実行は `ors_seed_sandbox` 経由（決定論的）で reproduce.sh を取得します。LLM `ors_build_reproduce` は reproduce.sh が既存の場合スキップするので、EAR が OFF の実行（論文のみ再現）でのみ発火します。

PaperBench は `ari-skill-paper-re/vendor/paperbench` に同梱。メイン採点 completer は LiteLLM (`_litellm_completer.py`) を経由するので、任意のプロバイダ（`gpt-5-mini` / `anthropic/claude-...` / `gemini/...` / `ollama/...`）が使えます。スコアパース用 structured completer は `gpt-4o-2024-08-06` のまま（PaperBench 許可リスト内）。

### ツール

#### `fetch_code_bundle(ref="", sha256="", dest="", checkpoint_dir="", overwrite=False)`

決定論的にサンドボックスを populate（LLM なし）。**v0.7.0+**: `checkpoint_dir` を渡すと `{checkpoint_dir}/publish_record.json` から ref + sha256 を自動読込（`ari ear publish` が書き出すファイル）。`dest/reproduce.sh` 既存時は `populated=False, skipped_reason=...` を返してスキップ。

#### `build_reproduce_sh(paper_path="", paper_text="", rubric_path="", output_dir="", model="", time_limit_sec=43200, iterative_agent=False, max_steps=0, sandbox_kind="auto", container_image="", apptainer_image="", overwrite=False)`

**v0.7.0+ で追加された LLM 駆動の replicator**。`fetch_code_bundle` の兄弟ツール。論文（とルーブリックの `expected_artifacts`）を読み、自己完結の `reproduce.sh` + ソースファイル一式を `output_dir` に書き出します。LiteLLM 経由で任意プロバイダ対応。`output_dir/reproduce.sh` 既存時はスキップ。モデル: `model` 引数 > `ARI_MODEL_REPLICATE` > `ARI_LLM_MODEL` > `claude-opus-4-7`。

#### `run_reproduce(rubric_path, repo_dir, sandbox_kind="", container_image="", timeout_global_sec=0, partition="", cpus=0, walltime="", …SLURM flags)`

**Phase 1**。`repo_dir/reproduce.sh` をサンドボックスで実行し、`reproduce.log` と成果物リストを取得。ルーブリック envelope の `expected_artifacts` と突き合わせ、未生成の成果物を `missing` として返します。

サンドボックス優先順位（`auto` の場合）: `slurm`（sbatch + `ARI_SLURM_PARTITION` あり、BFTS と同じパーティション）→ `docker`（デーモン利用可かつ HPC 上ではない時）→ `apptainer` → `singularity` → `local`。**SLURM dispatch** は v0.5.0 から復元され、`sbatch --wait` で同期実行。spool relocation 対策 wrapper を生成して `$0` 相対 cd を保護します。

#### `grade_with_simplejudge(rubric_path, repo_dir, paper_path="", paper_text="", judge_model="", n_runs=0, skip_negative_control=False, code_only=False)`

**Phase 2**。LiteLLM 経由のメイン採点 completer + OpenAI 直叩きの structured score-parser で動作。`n_runs`（デフォルト 3）回の重み付き葉スコアを平均化。負例コントロール（空 repo + 自明な reproduce.sh）も実行。

戻り値: `{ors_score, raw_score, leaf_grades, judge_model, n_runs, rubric_sha256, elapsed_sec, negative_control: {empty, boilerplate, passed}}`。

モデル: `judge_model` 引数 > `ARI_MODEL_JUDGE` > `ARI_LLM_MODEL` > `gpt-5-mini`。LiteLLM 認識可能な任意の model id が動作（PaperBench 純正の `CONTEXT_WINDOW_LENGTHS` 制約を回避）。

---

## ari-skill-replicate

v0.7.0 で追加された PaperBench 形式の **オートルーブリック生成器・監査器**。論文を読み、frozen ルーブリック（`replication_rubric.schema.json`、provenance メタデータ付きの PaperBench `TaskNode` ツリー）を出力します。**LLM: Yes**。

`ari-skill-paper-re.grade_with_simplejudge` と組み合わせて、v0.6.0 の `react_driver` ベースの再現性チェックを置き換える ORS フローを構成します。

### ツール

#### `generate_rubric(paper_path, paper_text, output_path, target_leaf_count=0, model="", temperature=0.0, seed=0, two_stage=True)`

PaperBench 互換のルーブリックを生成。`target_leaf_count=0` の場合は論文長から自動算定（~1葉 / 75語、[50, 400] にクランプ）。

`two_stage=True`（デフォルト）では **二段階生成** を行います: ①スケルトンパスでルート + 直接子（contribution/experiment ごとに1ノード）と各子の葉数バジェットを決定 → ②サブツリーパスを各直接子について並列に走らせ、4–6階層深く再帰的に展開。マージ後、スキーマの `minLength=10` を満たさない葉（quote / requirements が短すぎる葉）は自動で除去されます。PaperBench 参照論文での測定では、単一コール比 **葉数約 4 倍・深さ +1〜2 層**、API トークン消費は約 5 倍。`two_stage=False` で従来の単一コール（`prompts/adversarial_reviewer.md`）に戻せます。

#### `audit_rubric(rubric_path, paper_path, paper_text, auditor_model="")`

独立した監査パス。問題のある葉を `vague_qualifier` / `no_paper_evidence` / `duplicate` / `unverifiable` でフラグ付けし、20% 超なら再生成を推奨します。

#### `suggest_target_leaf_count(paper_path, paper_text)`

論文長から自動算定した目標葉数と単語数を返します。GUI Wizard の "Target leaves" 欄の事前埋めに利用。

### 環境変数

| 変数 | デフォルト | 用途 |
|---|---|---|
| `ARI_MODEL_RUBRIC_GEN` | `gemini/gemini-2.5-pro` | 生成 LLM |
| `ARI_MODEL_RUBRIC_AUDIT` | `anthropic/claude-opus-4-7` | 監査 LLM（生成器とは独立） |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | (未設定) | 目標葉数の上書き。`0` / 未設定で論文長から自動。GUI Wizard の "Target leaves" 欄。 |
| `ARI_RUBRIC_GEN_TEMPERATURE` | (未設定) | 生成器 temperature の上書き。GUI Wizard の "Temperature" 欄。 |
| `ARI_RUBRIC_GEN_TWO_STAGE` | (未設定) | 二段階生成の強制 ON/OFF（`1`/`true`/`on` vs `0`/`false`/`off`）。未設定時は kwarg のデフォルト（現状 `True`）。GUI Wizard の "二段階生成" トグル。 |

`server.py` で「明示 kwarg → 環境変数 → デフォルト」の順で解決されます。`workflow.yaml` の `ors_generate_rubric` ステージはこの3項目を明示しないため、GUI Wizard の値が常に効きます。

---

## ari-skill-memory

祖先スコープのノードメモリ（v0.6.0 より [Letta](https://docs.letta.com) バックエンド）。ブランチ間汚染を防止し、ReAct エージェントのトレースも同じ Letta エージェントに格納します。**LLM: △**（埋め込みベースの検索。P2 緩和の詳細は `docs/concepts/PHILOSOPHY.md`）。

### ツール

#### `add_memory(node_id, text, metadata=None)`

`node_id` でタグ付けされたエントリを保存します。**Copy-on-Write**: `node_id` が `$ARI_CURRENT_NODE_ID` と一致しない書き込みは拒否されます。

#### `search_memory(query, ancestor_ids, limit=5)`

`ancestor_ids` に含まれるノードのエントリのみを **Letta の `passages.search` (embedding ベースの semantic search) ランク順** で返します。兄弟・子ノードは一切返しません。

実装メモ (Letta 0.16.7 で 2026-05-04 検証): SDK の `passages.list(search=q)` は意図的に **使いません**。当該 SDK は `GET /archival-memory?search=q` に変換され、サーバ側で **SQL substring match** (`WHERE LOWER(text) LIKE LOWER(%q%)`) — semantic search ではありません。`"Validate the loopline performance model"` のような長い自然文クエリは `RESULT SUMMARY metrics=[...]` のような構造化エントリに部分文字列でヒットしないため、本番で 84 件の有効 passage がありながら 0 件しか返らない問題が観測されました。本スキルは代わりに `passages.search` (`GET /archival-memory/search`、`embed_query=True`) を `top_k = max(letta_overfetch, limit*40)` で叩き、ランクされた結果を `ancestor_ids` / `ari_checkpoint` / `kind == "node_scope"` でローカル post-filter します。`add_memory` 挿入時に支払っている embedding コストが retrieval で正しく消費される形になり、子は `eval_summary` クエリに対して **意味的に最も関連するエントリ** を先頭から受け取ります。

#### `get_node_memory(node_id)`

特定ノードの全エントリを時系列で取得（スコアなし）。

#### `clear_node_memory(node_id)`

デバッグ用の単一ノード削除。`add_memory` と同じ CoW ルールを適用。

#### `get_experiment_context()`

Letta のコアメモリからシードされた実験ファクト（`experiment_goal`、`primary_metric`、`hardware_spec` など）を返します。シードは最初のノードで `generate_ideas` が完了したタイミング（`primary_metric` が確定する時点）で 1 回だけ実行されるため、それ以前は `{}` を返します。以降は何度呼び出しても安全（60 秒のインプロセスキャッシュ付き）。

ストレージ: チェックポイントごとに Letta エージェント（`ari_node_*` と `ari_react_*` の 2 コレクション）。`{ARI_CHECKPOINT_DIR}/memory_backup.jsonl.gz` にポータブルスナップショット、`{ARI_CHECKPOINT_DIR}/memory_access.jsonl` に write/read テレメトリ。v0.5.x の JSONL ストア（チェックポイントスコープの `memory_store.jsonl` と、かつて `$HOME/.ari/` 配下にあったレガシーグローバル JSONL）は v0.5.0 で削除。移行は `ari memory migrate --react`。クロス実験の「グローバルメモリ」は廃止。

---

## ari-skill-orchestrator

ARI を外部エージェントや IDE 向けの MCP サーバーとして公開します。再帰的なサブ実験をサポート。**LLM: No**（ARI CLI に委譲）。

デュアルトランスポート: **stdio**（Claude Desktop / 他 MCP クライアント向け）+ **HTTP**（REST + SSE、`ARI_ORCHESTRATOR_PORT`、デフォルト 9890）。

### ツール

#### `run_experiment(experiment_md, max_nodes=10, model="", max_recursion_depth=3, parent_run_id="", llm_backend="", llm_api_key="", llm_base_url="", executor="", cpus=0, timeout_minutes=0, retrieval_backend="")`

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

## ari-skill-transform

BFTS の内部表現を出版可能な科学データ形式に変換します。すべての内部フィールド（`node_id`、`label`、`depth`、`parent_id`）を除去し、科学的コンテンツ（`configurations`、`experiment_context`）のみを公開します。**LLM: Yes**。

### ツール

#### `nodes_to_science_data(nodes_json_path, llm_model="", llm_base_url="", primary_metric="", higher_is_better="true")`

LLM が BFTS ツリー全体を分析し、ハードウェアスペック、手法、主要な知見、比較を抽出します。`primary_metric` と `higher_is_better` は `evaluation_criteria.json` から `tpl_vars` 経由で渡され、`summary_stats` の方向考慮 best 算出に使われます（v0.7.0+）。

戻り値（v0.7.0+）:

```text
configurations[*]:
  rank, label, eval_summary
  parameters / measurements / predictions / scores  ← 型付き分割
                                                       (D: results.json or
                                                        C: _params_dict 経由)
  metrics                                            ← 互換性のための flat union
  _typed_source: "results.json" | "llm_evaluator" | (なし)
per_key_summary  (入力パラメタキー & 「_…」予約キーは除外)
summary_stats    { count, primary_metric, direction,
                   primary_metric_best, primary_metric_n,
                   typed_split_coverage }
experiment_context, implementation_overview, report_driven
```

**型付き分割の優先度** (D > C > legacy):

1. `experiments/{run_id}/{node_id}/results.json` — `coding-skill::emit_results` が書き出すファイル（D 契約）
2. `node.metrics::_params_dict` / `_measurements_dict` — LLM evaluator が `MetricSpec.expected_params` 設定下で出力（C 契約）
3. レガシー: `parameters: {}`、フラット `metrics` がすべてを保持

**頑健性**: LLM 応答パーサは `<think>` ブロックと ` ```json ` フェンスを除去し、各候補 `{` から balanced-brace を歩いて長さ降順で `json.loads` を試行します。`{...} prose {...}` のような shape も救えます。失敗時は raw 応答を `{checkpoint_dir}/science_data.debug.txt` に保存して事後監査可能にします。

モデル: `llm_model` 引数 > `LLM_MODEL` env > `gpt-4o-mini`。

**存在理由:** BFTS 内部の用語が論文や図表に漏洩しないようにすること、および入力サイズ記述子（`nnz`、`M`、`K`）と測定された出力（`GFlops_per_s`、accuracy）を best-of 集約で混同しないことを保証します。

#### `generate_ear(checkpoint_dir, llm_model="", llm_base_url="")`

再現性のための **Experiment Artifact Repository (EAR)** を `<checkpoint>/ear/` に構築します。node_report 駆動で、論文付随コード repo と同じレイアウトになります:

- `README.md` — 決定論的レンダリング。`science_data.json::implementation_overview.architecture` がある場合は `Architecture` セクションを追加
- `reproduce.sh` — best ノードの `node_report.json::{build_command, run_command}` を literal で挿入
- `environment.json` — 実行時環境キャプチャ（Python、プラットフォーム、pip、ハードウェア）
- `code/` — best chain の contributing ノードの `files_changed.added` ∪ `modified` を verbatim 配置（`code/<node_id>/` 形式は廃止）
- `data/` — `checkpoint/uploads/` を verbatim ミラー（**入力データのみ**、空なら不在）。**実験出力は ear/ に含めない** — `reproduce.sh` で再生成
- `figures/` — checkpoint 直下の `*.{pdf,png,svg,jpg,jpeg}` を top-level に配置
- `LICENSE` — `publish.yaml::license` から SPDX テンプレ生成（MIT / Apache-2.0 / BSD-3-Clause / GPL-3.0 / CC-BY-4.0）

ARI の監査ログ 2 つは `<checkpoint>/` 直下（`ear/` の外）に置かれ、公開アーティファクトには含まれません:

- `EVOLUTION.md` — Step / Label 形式の探索軌跡（delta、concerns 含む）。opaque な `node_id` は出現させない
- `_provenance.json` — 出自メタデータ（`from_node_id`, `introduced_by`, `excluded_nodes`）。中のパスは checkpoint 相対（`ear/code/...`）

その他の ARI 内部メタデータ（`tree.json`, `science_data.json`, `raw_metrics.json`, `eval_scores.json`, `commands.md`）も checkpoint root に残し、`ear/` には混入させません。`run_config.json` は `checkpoint/run_config.json` に移動しました。

戻り値: `{ear_dir, code_layout, verbatim_files, rendered_files, data_count, figure_count, top_node_id, best_chain_depth, excluded_count, has_readme, has_evolution, has_reproduce_sh, has_license, has_environment, ...}`。

#### `curate_ear(checkpoint_dir)` — v0.7.0

`{checkpoint}/ear/publish.yaml` の allowlist と built-in deny list（`.env*`, `secrets/**`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`）を用いて `{checkpoint}/ear/` を `{checkpoint}/ear_published/` にキュレートします。`manifest.lock` に正規化された `bundle_sha256`（ソート済み `{path, sha256, size}` JSON の sha256）を書き出します — これが論文の `\codedigest{...}` マクロに焼き付けられる digest です。**決定論的、LLM なし**。`publish.yaml` が無ければ静かにスキップ（v0.6.0 checkpoint の後方互換）。

#### `publish_ear(checkpoint_dir, backend="ari-registry", visibility="staged", dry_run=False)` — v0.7.0

`ari.publish.publish` の薄い MCP ラッパ。`ear_published/` から再現可能な tarball（ソート済み・mtime/uid/gid 正規化）を構築し、バックエンド（`ari-registry` / `gh` / `zenodo` / `local-tarball`）に転送し、`publish_record.json` を checkpoint root に記録します。最初の publish は常に `visibility=staged`（FR-P5）。`auto_promote=true` かつ再現性チェック合格時のみ public に昇格できます。

`ARI_PUBLISH_DRYRUN=1` で CI 安全のため dry-run を強制可能。

#### LICENSE テンプレート — v0.7.0

`publish.yaml::license` が指定されていて、かつ `ear/LICENSE` が著者作成で存在しない場合、`generate_ear` が **MIT** / **Apache-2.0** / **BSD-3-Clause** / **GPL-3.0** / **CC-BY-4.0** のいずれかを `ari-skill-transform/src/licenses/` から書き出します。

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

#### `search_papers(query, max_results=10)`

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

#### `read_uploaded_file(filename, max_chars=50000)`

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

#### `read_file(path, offset=0, limit=8000, work_dir="/tmp/ari_work")`

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

## ari-skill-plot

科学論文用の図生成器。2 モード: **決定論モード**（`generate_figures`、P2-safe な matplotlib + 固定スキーマ）と **LLM モード**（`generate_figures_llm`、AI-Scientist-v2 スタイルでコードを LLM が書いて実行、オプションで VLM キャプション付与）。**LLM: Mixed**（決定論 + P2 例外）。

### ツール

#### `generate_figures(nodes_json_path, output_dir, figures=None, science_data_path="", vlm_captions=True, experiment_context="")`

`nodes_tree.json` から正準比較図を `output_dir` に書き出します。出力された各図のキャプションとソースノード ID を含むマニフェストを返します。matplotlib バージョン固定下でバイト決定論的。

#### `generate_figures_llm(nodes_json_path, output_dir, experiment_summary="", context="", n_figures=3, science_data_path="", vlm_feedback="")`

LLM がデータ形状と自然文 `intent` を見て matplotlib コードを書き、`_run_plot_code` サンドボックスで実行し、（任意で）VLM がキャプションを付与。P2 例外。

### 環境変数

| 変数 | 用途 | 既定値 |
|---|---|---|
| `VLM_MODEL` | キャプション生成用 Vision LLM | `openai/gpt-4o` |
| `ARI_LLM_MODEL` | `_llm` モードでコードを書く LLM | （なし — `_llm` で必須）|
| `LLM_MODEL` | スキル間共通フォールバック | （なし）|
| `ARI_LLM_API_BASE` | LiteLLM API ベース URL 上書き | LiteLLM 既定 |
| `OPENAI_API_KEY` | OpenAI 系モデル時に必要 | （なし）|

### ari-core 境界

`src/server.py` が `from ari import cost_tracker` を import。リファクタ Phase 4 で `ari.public.cost_tracker` に移行予定。

---

## ari-skill-vlm

図表・テーブル品質レビューのための Vision-Language モデル。**LLM: Yes**（VLM）。

### ツール

#### `review_figure(image_path, context="", criteria=None)`

VLM が実験図表をレビューします。スコア（0-1）、問題点、提案を返します。

#### `review_table(latex_or_path, context="")`

VLM がテーブル（LaTeX ソースまたはレンダリング画像）をレビューします。スコア、問題点、提案を返します。

モデル: `VLM_MODEL` env > `openai/gpt-4o`。

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

2. `ari-core/config/workflow.yaml` に登録します。`phase` で
   どの pipeline-phase の ReAct エージェントが Skill を見えるか
   を指定 (1 つなら文字列、複数なら配列):

```yaml
skills:
  - name: your-skill
    path: '{{ari_root}}/ari-skill-yourskill'
    phase: [paper, reproduce]
```

   有効な phase 値: `bfts`、`paper`、`reproduce`、`all`、`none`。

3. `experiment.md` の `## Required Workflow` でツール名を参照。
