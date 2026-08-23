---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-core/ari/cli_ear.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/clone
    role: implementation
  - path: ari-core/ari/registry
    role: implementation
  - path: ari-core/ari/publish
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/config/reviewer_rubrics
    role: config
  - path: ari-core/ari/pipeline/driver.py
    role: implementation
  - path: ari-skill-paper/src
    role: implementation
  - path: ari-skill-idea/src/server.py
    role: implementation
  - path: ari-skill-vlm/src/review.py
    role: implementation
  - path: ari-skill-web/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/config.py
    role: implementation
  - path: scripts/setup/install_deps.sh
    role: implementation
last_verified: 2026-08-16
---

# ARI CLI リファレンス

ARI のコマンドライン操作の完全なリファレンスです。CLI は [Web ダッシュボード](../getting-started/quickstart.md)と同等の機能をターミナルベースのワークフロー向けに提供します。

---

## コマンド一覧

| コマンド | 説明 | ダッシュボード相当 |
|---------|------|-------------------|
| `ari run` | 新しい実験を実行 | New Experiment ウィザード → Launch |
| `ari resume` | 中断された実験を再開 | Experiments ページ → Resume ボタン |
| `ari paper` | 論文のみ生成（実験をスキップ） | `POST /api/run-stage {stage: "paper"}` |
| `ari manuscript <subcmd>` | Manuscript Complete の compile / 検査 / repair / lock | — |
| `ari status` | 実験ツリーとサマリーを表示 | Monitor / Tree ページ |
| `ari viz` | Web ダッシュボードを起動 | -- |
| `ari projects` | 過去のすべての実験を一覧表示 | Experiments ページ |
| `ari show` | 実行結果の詳細を表示 | Results ページ |
| `ari delete` | チェックポイントを削除 | Experiments ページ → Delete ボタン |
| `ari settings` | 設定の表示または変更 | Settings ページ |
| `ari skills-list` | 利用可能なツールを一覧表示 | Settings → MCP Skills |
| `ari knowledge <subcmd>` | 非実行の Knowledge Skill を検査（`search` / `show` / `import` / `validate-manifest` / `validate-registration`、加えて `lock` と `use`） | — |
| `ari provider <subcmd>` | 実行可能な Capability Provider を検査（`search` / `show` / `probe` / `validate-manifest`、加えて `lock` と `bindings`） | — |
| `ari harness <subcmd>` | Harness と assurance 証跡を検査（`search` / `show` / `resolve` / `verify` / `validate-manifest` / `validate-registration`、加えて `lock`、`attestation`、`suite`） | — |
| `ari memory ...` | Letta メモリバックエンドを管理 | Settings → Memory (Letta) |
| `ari ear <subcmd>` | EAR キュレーション/公開/プロモーションのライフサイクル (v0.7.0) | — |
| `ari clone <ref>` | キュレート済み EAR バンドルを取得 (file/https/ari/gh/doi)、digest 検証 (v0.7.0) | — |
| `ari registry <subcmd>` | セルフホスト EAR レジストリ: `serve` / `token issue\|revoke\|list` (v0.7.0) | — |
| `ari migrate node-reports <checkpoint>` | 旧 (v0.6.0) checkpoint に `node_report.json` を補完 | — |
| `ari doctor claude-code` | `claude_code` LLM バックエンドのヘルスチェック（バイナリ/ポリシー/フラグ。`--live` で実呼び出し 1 回） | — |

> **実行モード。** オプトインの `ari_rqgm` モードは v1 で **CLI フラグを一切
> 追加しません** — 有効化は純粋に設定（workflow.yaml の
> `ari.mode: ari_rqgm` + `rqgm.enabled: true`）または `ARI_MODE` /
> `ARI_RQGM_ENABLED` 環境変数オーバーライドで行います。上記のすべての
> コマンドはデフォルトの `simple_bfts` モードで従来と同一に動作します。
> [実行モード](../guides/execution_modes.md)を参照。

## `ari manuscript` — 完全性と publication の操作

このコマンド群は、オプトインの exploration-to-authoring コンパイラに対する
機械可読なオペレータ面です。既定の `manuscript.mode: "off"` 経路では動作
しません。

```bash
ari manuscript compile CHECKPOINT [--mode audit|enforce] \
  [--profile generic_empirical_v1] [--repair-policy disabled|explicit|auto] \
  [--config WORKFLOW]
ari manuscript status CHECKPOINT [--fail-if-blocked]
ari manuscript inspect CHECKPOINT [--requirement ID] [--lane LANE] [--node ID]
ari manuscript plan-repair CHECKPOINT [--config WORKFLOW]
ari manuscript repair CHECKPOINT [--request REQUEST_ID]... [--config WORKFLOW]
ari manuscript explain-publication CHECKPOINT
ari manuscript lock-publication CHECKPOINT
```

`plan-repair` は外部システムに対して read-only です。`repair` はまず admit
された request と budget を永続化し、そのうえで通常の bounded research runtime
を使います。`ari paper` が research repair を開始することはありません。
`--mode` の既定は `audit` です。`--repair-policy auto` は `--mode enforce` を
併せて指定しない限り拒否されます。`--request` は繰り返し指定でき、**省略すると
plan 内のすべての request が選択されます** — 未知の id は
`unknown request IDs: ...` で拒否されます。`lock-publication` が成功するのは、
最終ビルドと PDF そのものに束縛された fresh で publishable な decision に
対してだけです。
[オペレータランブック](../guides/manuscript_complete_operations.md)を参照。

---

## ari migrate node-reports

v0.7.0 (task2.md) で `experiments/{run_id}/{node_id}/node_report.json` を
ノードごとに記録するようになりました。旧 checkpoint には存在しないため、
ダウンストリーム (generate_ear / nodes_to_science_data / bfts.expand /
GUI Tree Report タブ) はレガシーヒューリスティックにフォールバックします。
旧 checkpoint に対しては一度だけ以下を実行してレポートを補完してください:

```bash
ari migrate node-reports /path/to/checkpoint
ari migrate node-reports /path/to/checkpoint --overwrite   # 既存レポートも上書き
```

復元できないフィールド (`original_direction`,
`next_steps_hints`) は null になります。

---

## ari run

実験 Markdown ファイルから新しい実験を実行します。

```bash
ari run <experiment.md> [--config <config.yaml>] [--profile <profile>] \
                        [--virsci-live/--no-virsci-live] \
                        [--virsci-k N] [--virsci-team-size N] \
                        [--virsci-n-authors N] [--virsci-n-papers N] \
                        [--kca-audit/--no-kca-audit] [--task-tag TAG]...
```

| 引数 | 必須 | 説明 |
|------|------|------|
| `experiment.md` | はい | 実験 Markdown ファイルへのパス |
| `--config` | いいえ | カスタム設定 YAML（省略時は自動生成） |
| `--profile` | いいえ | 環境プロファイル: `laptop`、`hpc`、または `cloud` |
| `--virsci-live` / `--no-virsci-live` | いいえ | アイデアスキル: 再実装の議論ループの代わりに、ライブの Semantic Scholar スナップショット上で VirSci 本物のマルチエージェントエンジン（vendor-wrap）を実行。`ARI_IDEA_VIRSCI_REAL` を設定。既定 OFF。 |
| `--virsci-k` | いいえ | VirSci-live の議論ターン数（vendor `group_max_discuss_iteration`）。`ARI_IDEA_VIRSCI_K` を設定。既定 7。 |
| `--virsci-team-size` | いいえ | VirSci-live のチームあたり最大メンバー数。`ARI_IDEA_VIRSCI_TEAM_SIZE` を設定。既定 3。 |
| `--virsci-n-authors` | いいえ | VirSci-live の `select_coauthors` 用著者プールサイズ。`ARI_IDEA_VIRSCI_N_AUTHORS` を設定。既定 16。 |
| `--virsci-n-papers` | いいえ | VirSci-live の SPECTER2 検索コーパスサイズ。`ARI_IDEA_VIRSCI_N_PAPERS` を設定。既定 800。 |
| `--kca-audit` / `--no-kca-audit` | いいえ | Knowledge・capability binding・assurance を `audit` モードにし、それぞれの照会 Skill を公開。未設定なら `assurance.tolerance_policy` を `hpc-floating-point/v1` に既定設定する。既定 OFF。 |
| `--task-tag` | いいえ | 決定論的な Knowledge/Harness の task tag。複数指定は繰り返し。タグは小文字化・トリム・重複除去され、checkpoint の `workflow.yaml` の `resolved_launch.task_tags` に記録される。 |

これらのフラグは、アイデアスキルが読み込む `ARI_IDEA_VIRSCI_*` 環境変数の契約を
設定します（下記 [アイデア生成 (VirSci-live)](#アイデア生成-virsci-live) 参照）。
`--virsci-live` が ON のとき、仮説生成はライブの Semantic Scholar スナップショット
上で VirSci 本物の `select_coauthors` + `generate_idea` メカニズムを実行します。
依存が無い場合や実行時エラーが発生した場合は、`idea.json` の契約が同一のまま
再実装ループへ degrade します。

**使用例：**

```bash
# 基本的な実行（設定を自動検出）
ari run experiment.md

# 環境プロファイルを指定
ari run experiment.md --profile laptop

# カスタム設定を指定
ari run experiment.md --config ari-core/config/workflow.yaml

# 環境変数でオーバーライド
ARI_MAX_NODES=10 ARI_PARALLEL=2 ari run experiment.md

# アイデア生成に VirSci 本物のマルチエージェントエンジンを使用（vendor-wrap）
ari run experiment.md --virsci-live --virsci-k 7 --virsci-team-size 3
```

**実行される処理：**

1. ARI がユニークなプロジェクト名を生成（LLM が生成するタイトル）
2. チェックポイントディレクトリを作成: `./workspace/checkpoints/<run_id>/`
3. arXiv と Semantic Scholar で関連論文を検索
4. VirSci マルチエージェント議論で仮説を生成
5. Best-First Tree Search（BFTS）で実験を実行
6. LLM ピアレビューで結果を評価
7. 図表と引用を含む LaTeX 論文を執筆
8. 再現性を独立して検証

---

## ari resume

チェックポイントから中断された実験を再開します。

```bash
ari resume <checkpoint_dir> [--config <config.yaml>]
```

**使用例：**

```bash
ari resume ./workspace/checkpoints/20260328_matrix_opt/
```

保存されたツリーを読み込み、保留中または失敗したノードを特定し、停止した箇所から再開します。

---

## ari paper

実験を実行せずに論文のみを生成します。実験がすでに完了している場合に便利です。

```bash
ari paper <checkpoint_dir> [--experiment <experiment.md>] [--config <config.yaml>] \
                           [--rubric <rubric_id>] \
                           [--fewshot-mode static|dynamic] \
                           [--num-reviews-ensemble N] \
                           [--num-reflections N]

# 同梱ルーブリック (23 種): neurips、iclr、icml、cvpr、acl、sc、chi、osdi、
#   stoc、icra、siggraph、nature、usenix_security、aer、econometrica、qje、
#   apsr、ahr、philreview、pmla、journal_generic、workshop、
#   generic_conference。
#   ari-core/config/reviewer_rubrics/ に <id>.yaml を追加するだけで
#   新しい venue に対応できます。
```

**使用例 — 同梱の既定 (`generic_conference` 形式):**

```bash
ari paper ./workspace/checkpoints/20260328_matrix_opt/
```

**使用例 — Supercomputing (SC) ルーブリックで 5 名アンサンブル + メタ査読:**

```bash
ari paper ./workspace/checkpoints/20260328_matrix_opt/ \
          --rubric sc --num-reviews-ensemble 5
```

> **`--rubric` は論文査読者には届きません。** このフラグ (および `ARI_RUBRIC`)
> が選ぶのは、ARI 自身の評価器がスコア軸を導出する rubric (既定 `neurips`) と、
> lineage 判断が継承する rubric です。`write_paper` / `review_paper` ステージは
> `rubric_id` を workflow のトップレベルキー `paper_rubric:` から取ります —
> 同梱の `ari-core/config/workflow.yaml` では `generic_conference` です。
> paper スキルは意図的に `ARI_RUBRIC` を読まず既定値も推測しません
> (`resolve_rubric` は `rubric_id is required` を送出)。査読 venue を変えるには
> workflow YAML の `paper_rubric` を編集してください。

論文パイプラインは: データ変換、図生成、論文執筆、claim-evidence ゲート、
VLM 図査読、**ルーブリック駆動の論文査読** (rubric 形式 + reflection +
オプションのアンサンブル + Area Chair メタ査読)、refine/render と finalize、
そして ORS 再現性トラック (`ors_generate_rubric` → `ors_audit_rubric` →
`ors_seed_sandbox` → `ors_build_reproduce` → `ors_run_reproduce` →
`ors_grade`、`paper-re-skill` と `replicate-skill` が担当) を実行します。

CLI フラグは環境変数でも設定可能: `ARI_RUBRIC`、`ARI_FEWSHOT_MODE`、
`ARI_NUM_REVIEWS_ENSEMBLE`、`ARI_NUM_REFLECTIONS`。このうち査読側が実際に
読むのは `ARI_NUM_REVIEWS_ENSEMBLE` と `ARI_NUM_REFLECTIONS` だけです
(`review_compiled_paper` はどちらも 引数 > 環境変数 > rubric 既定値 の順で
解決)。`--fewshot-mode` は現在 inert です: 値を検証して `ARI_FEWSHOT_MODE`
を export しますが、この変数を読むコードは存在せず、`fewshot_mode` は
rubric YAML の `params` ブロックだけから決まります。

---

## ari status

実験ツリーとサマリー統計を表示します。

```bash
ari status <checkpoint_dir>
```

**使用例：**

```bash
ari status ./workspace/checkpoints/20260328_matrix_opt/

# 出力:
# Run: 20260328_matrix_opt
# └── root d=0 success
#     ├── improve_1 d=1 success
#     │   ├── ablation_1 d=2 success
#     │   └── validation_1 d=2 success
#     └── draft_2 d=1 failed
#
#         Summary
# ┏━━━━━━━━━┳━━━━━━━┓
# ┃ Status  ┃ Count ┃
# ┡━━━━━━━━━╇━━━━━━━┩
# │ failed  │     1 │
# │ success │     4 │
# └─────────┴───────┘
```

ノード行が持つのは id・深さ・ステータスだけで、`ari status` は **スコアを
表示しません**。ノードごとの score フィールドは廃止され、代替は用意されて
いません。

---

## ari viz

ビジュアル実験管理のための Web ダッシュボードを起動します。

```bash
ari viz <checkpoint_dir> [--port <port>]
```

| 引数 | デフォルト | 説明 |
|------|-----------|------|
| `checkpoint_dir` | （必須） | 監視するチェックポイントディレクトリ |
| `--port` | 8765 | サーバーのポート番号 |

**使用例：**

```bash
# ダッシュボードの起動
ari viz ./workspace/checkpoints/ --port 8765

# 特定の実行を監視
ari viz ./workspace/checkpoints/20260328_matrix_opt/ --port 9878
```

ブラウザで `http://localhost:<port>` を開いてください。ダッシュボードの使い方は[クイックスタートガイド](../getting-started/quickstart.md)を参照してください。

---

## ari projects

過去のすべての実験を一覧表示します。

```bash
ari projects [--checkpoints <dir>]
```

`--checkpoints` の既定値は `./checkpoints` であり、`ari run` が実際に書き込む
`workspace/checkpoints/` ツリーでは **ありません**。リポジトリルートで
`ari projects` を引数なしに実行すると `Directory not found: checkpoints` を
表示して終了コード 1 になります。実際のルートを明示してください。

**使用例：**

```bash
ari projects --checkpoints ./workspace/checkpoints

# 出力:
#                       ARI Projects
# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━┓
# ┃ ID                         ┃ Nodes ┃ Status  ┃ Score ┃ Modified    ┃
# ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━┩
# │ 20260328_matrix_opt        │    28 │ done    │ 8.40  │ 03/28 14:02 │
# │ 20260327_sorting_benchmark │    12 │ running │ —     │ 03/27 09:15 │
# │ 20260326_sample_experiment │     0 │ empty   │ —     │ 03/26 22:41 │
# └────────────────────────────┴───────┴─────────┴───────┴─────────────┘
```

Status は `tree.json` (無ければ `nodes_tree.json`) から導出され、
`running` / `done` / `empty` / `corrupt` のいずれかです — 成功/失敗の判定では
ありません。Score は `review_report.json` の `scientific_score` (無ければ
`score`) を小数 2 桁に整形した値で、レビューレポートが無ければ `—` です。

---

## ari show

特定の実験の詳細な結果を表示します。

```bash
ari show <checkpoint> [--checkpoints-dir <dir>]
```

実験ツリー、レビューレポートの概要、および成果物の一覧を表示します。
`<checkpoint>` はまずパスとして扱われ、そのパスが存在しない場合にだけ
`--checkpoints-dir` (既定 `./checkpoints`) を基準に解決されます。

---

## ari delete

チェックポイントディレクトリを削除します。

```bash
ari delete <checkpoint> [--checkpoints-dir <dir>] [--yes]
```

| フラグ | 説明 |
|--------|------|
| `--checkpoints-dir` | `<checkpoint>` 自体が既存パスでない場合にだけ使われるベースディレクトリ。既定 `./checkpoints` |
| `-y` / `--yes` | 確認プロンプトをスキップ |

ディレクトリを削除する前に、`ari delete` はそのチェックポイントの Letta
メモリ名前空間を purge します。この処理は best-effort で、失敗しても警告を
記録するだけでローカルの `rmtree` は続行され、孤立した Letta エントリは
`ari memory prune-local` で後から掃除することになります。

---

## ari settings

ARI の設定を表示または変更します。

```bash
ari settings [--config <config.yaml>] [options]
```

| オプション | 説明 |
|-----------|------|
| `--model <name>` | LLM モデル名を設定 |
| `--api-key <key>` | API キーを設定 |
| `--partition <name>` | SLURM パーティション名を設定 |
| `--cpus <count>` | CPU 数を設定 |
| `--mem <GB>` | メモリを GB 単位で設定 |

`--config` の既定値は `./config.yaml` で、そのファイルが存在しなければ終了
コード 1 で終わります — 同梱 workflow へのフォールバックはありません。
`--partition` / `--cpus` / `--mem` は型付きの `resources:` ブロックに
(`partition` / `cpus` / `mem_gb` として) 書き込まれます。experiment.md の
ヘッダから解析される実行ごとの `slurm_partition` / `slurm_max_cpus` ヒントは
これとは別物で、ここでの設定に上書きされません。

**使用例：**

```bash
# 現在の設定を表示
ari settings

# モデルを変更
ari settings --model gpt-4o

# 複数のオプションを設定
ari settings --model qwen3:32b --partition gpu --cpus 64 --mem 128
```

---

## ari doctor claude-code

`claude_code` LLM バックエンドのヘルスチェック
（[claude_code_provider.md](./claude_code_provider.md) 参照）: claude
バイナリとバージョン、解決済み設定の fail-loud ポリシー検証、実際に実行
される strict モードコマンド、静的なフラグサポート報告
（`--max-turns` / `--system-prompt-file` は `claude --help` に出ない
hidden-but-supported フラグ）。

```bash
ari doctor claude-code           # オフラインチェックのみ
ari doctor claude-code --live    # + schema 検証付き実 hermetic 呼び出し 1 回（トークン消費）
```

---

## ari ear — v0.7.0

1 つの checkpoint に対する **Experiment Artifact Repository** の
キュレーション・公開・プロモーションを行います。キュレーションは
決定論的 (LLM 不使用)、公開は curated tarball をバックエンドに送って
検証可能な ref を得ます。

```bash
ari ear curate   <checkpoint> [--show-files] [--json]
ari ear status   <checkpoint>
ari ear publish  <checkpoint> [--backend ari-registry|local-tarball|gh|zenodo] \
                              [--visibility staged] [--dry-run]
ari ear promote  <checkpoint> [--target public|unlisted]
```

| サブコマンド | 動作 |
|--------------|------|
| `curate` | `ear/publish.yaml` の allowlist と built-in deny list (`.env*`、`secrets/**`、`*.pem`、`*.key`、`id_rsa`、`id_ed25519`) を適用し、`{checkpoint}/ear_published/` + `manifest.lock` (決定論的 `bundle_sha256` 入り) を書き出す。`publish.yaml` が無ければ静かにスキップ。 |
| `status` | キュレーション manifest 概要 + `publish_record.json` を表示。 |
| `publish` | `ear_published/` から再現可能な tarball を構築し、バックエンドへ送信。最初は常に `visibility=staged` (FR-P5)。`ARI_PUBLISH_DRYRUN=1` で `--dry-run` を強制。 |
| `promote` | staged → `public`/`unlisted` に昇格。降格は拒否。 |

バックエンド: `ari-registry` (セルフホスト)、`local-tarball` (サーバ不要)、`gh` (GitHub release)、`zenodo` (DOI 採番)。

**エンドツーエンドの例**:

```bash
# 1. 著者が論文パイプライン後にバンドルをキュレート
ari ear curate ./workspace/checkpoints/run_20260504_xy/

# 2. allow/deny ルール後の中身を確認
ari ear status ./workspace/checkpoints/run_20260504_xy/
# bundle_sha256: 0ccabb16...
# files:         42
# visibility:    staged

# 3. registry に staged で publish
ari ear publish ./workspace/checkpoints/run_20260504_xy/ --backend ari-registry

# 4. 査読 + 再現性チェック合格後に public に昇格
ari ear promote ./workspace/checkpoints/run_20260504_xy/ --target public
```

`bundle_sha256` は `finalize_paper` ステージで論文の `\codedigest{...}` マクロに焼き付けられます。論文を持っている人なら、registry が落ちていても任意のコピーを digest で検証できます。

---

## ari memory

v0.6.0 で追加された Letta メモリバックエンド管理用のコマンド群。各
サブコマンドは `--checkpoint <path>` または `ARI_CHECKPOINT_DIR` 環境変数
から対象チェックポイントを解決します。

```bash
ari memory <subcommand> [options]
```

| サブコマンド | 説明 |
|------------|------|
| `health` | バックエンドへ ping、レイテンシ、namespace ハッシュ、サーバーバージョンを表示 |
| `migrate` | v0.5.x の `memory_store.jsonl` (および `--react` 付与時は `memory.json`) を Letta コレクションへ一括取り込み。元ファイルは `*.migrated-<ts>` にリネーム。`--dry-run` は取り込まずに件数だけ数える |
| `backup` | Letta 上のメモリを `{ckpt}/memory_backup.v1.json.gz` にスナップショット保存 — JSONL ではなく、gzip 圧縮された digest 束縛の JSON ドキュメント 1 件。`ari run` が `atexit` で登録するのでプロセス終了時に 1 回だけ書き出される。`ARI_HANDOFF_MEMORY_OFF=1` はこの自動書き出しだけを抑止する (明示的なコマンド実行は従来どおり動作) |
| `restore` | `backup` の逆。`--on-conflict=skip\|overwrite\|merge` (既定 `skip`)。`ari resume` 時に Letta が空なら自動実行 |
| `start-local` | ローカル Letta サーバを起動: `--path=auto\|docker\|singularity\|pip` |
| `stop-local` | docker/singularity/pip Letta を停止 (best-effort) |
| `prune-local` | ローカル Letta の状態 (volumes / venv / `~/.letta`) を削除。`--yes` 必須 |
| `compact-access` | ローテーション済みの `memory_access.<ts>.jsonl` を `memory_access.summary.json` に集約し原ファイルを削除 |

**使用例:**

```bash
# 現在のチェックポイントで Letta 到達性をチェック
ARI_CHECKPOINT_DIR=/path/to/ckpt ari memory health

# v0.5.x チェックポイントをアップグレード
ari memory migrate --checkpoint /path/to/ckpt --react

# ポータブルなアーカイブ
ari memory backup  --checkpoint /path/to/ckpt
rsync -a /path/to/ckpt/ other-host:/home/user/ckpt/
ssh other-host "ari memory restore --checkpoint /home/user/ckpt"

# `ari setup` で Letta が起動しなかった場合
ari memory start-local --path=docker
```

---

## ari skills-list

利用可能なすべての MCP ツールとその説明を一覧表示します。

```bash
ari skills-list [--config <config.yaml>]
```

---

## 環境変数

### コア設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ARI_BACKEND` | LLM バックエンド。ルーティング対象の識別子は `ollama`、`openai`、`anthropic` / `claude`、`claude_code` / `claude-code`、`cli-shim` / `cli_shim`。それ以外の値は prefix を付けずそのまま LiteLLM に渡される | `ollama` |
| `ARI_MODEL` | モデル名 | `qwen3:8b` |
| `OPENAI_API_KEY` | OpenAI API キー | -- |
| `ANTHROPIC_API_KEY` | Anthropic API キー | -- |
| `OLLAMA_HOST` | Ollama サーバーの URL | `http://localhost:11434` |
| `LLM_API_BASE` | 汎用 API ベース URL（フォールバック） | -- |
| `ARI_MODE` | 実行モードのオーバーライド: `simple_bfts` / `ari_rqgm`（[実行モード](../guides/execution_modes.md)を参照） | `simple_bfts` |
| `ARI_RQGM_ENABLED` | RQGM 安全インターロックのオーバーライド（`0`/`1`/`true`/`false`; `ARI_MODE=ari_rqgm` と一致している必要がある） | off |

### BFTS 設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ARI_MAX_NODES` | 実験の最大総数 | 50 |
| `ARI_MAX_DEPTH` | ツリーの最大深さ | 5 |
| `ARI_PARALLEL` | 同時実行の実験数 | 4 |
| `ARI_MAX_REACT` | ノードごとの最大 ReAct ステップ数 | 20 |
| `ARI_TIMEOUT_NODE` | ノードごとのタイムアウト（秒） | 7200 |

### HPC 設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ARI_EXECUTOR` | 実行バックエンドのヒント。触るのは orchestrator スキルだけで、サブ実験の `executor` フィールドの初期値にし、空でなければ子 run の環境へ再 export する。契約は enum 検査のない自由形式文字列 (128 文字以下) で、`ari-core` 側にこれを読むコードは無い | -- (未設定) |
| `ARI_SLURM_PARTITION` | SLURM パーティション名 | -- |
| `ARI_SLURM_CPUS` | SLURM ジョブの CPU 数オーバーライド | (`auto_config` では未設定。PaperBench の再現経路は `8` にフォールバック) |
| `ARI_SLURM_MEM_GB` | `resources` に記録されるメモリ (GB) | -- |
| `ARI_SLURM_GPUS` | `resources` に記録される GPU 数 | -- |
| `ARI_SLURM_WALLTIME` | `resources` に記録される walltime | -- |

### 検索・VLM

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ARI_RETRIEVAL_BACKEND` | 論文検索プロバイダの既定値: `semantic_scholar` (別名 `semantic-scholar`) / `arxiv` / `alphaxiv`。`both` は **拒否** される — pin した `search_papers` 呼び出しを 2 回発行し alias で統合すること | `semantic_scholar` |
| `ARI_VLM_MODEL` | 図レビュー用 VLM モデル。未設定なら `VLM_MODEL` にフォールバックし、どちらも未設定だと VLM 査読は `ARI_VLM_MODEL must select a visual review model` を送出 | -- (既定値なし) |
| `ARI_ORCHESTRATOR_HTTP_PORT` | orchestrator スキルの HTTP ポート (1〜65535 の整数として解釈できること)。ホストは `ARI_ORCHESTRATOR_HTTP_HOST`、既定 `127.0.0.1` | `9890` |

### メモリ (Letta)

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `LETTA_BASE_URL` | Letta サーバエンドポイント | `http://localhost:8283` |
| `LETTA_API_KEY` | Letta Cloud で必須 | -- |
| `LETTA_EMBEDDING_CONFIG` | アーカイバルメモリ用の埋め込みハンドル（チャット LLM は ARI から呼び出さないため固定） | `letta-default` |
| `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA` | `auto` / `pip` / `docker` / `singularity` / `none` | `auto` |
| `ARI_MEMORY_LETTA_TIMEOUT_S` | 呼び出しごとのタイムアウト | `10` |
| `ARI_MEMORY_LETTA_OVERFETCH` | 祖先ポストフィルタ用のオーバーフェッチ K | `200` |
| `ARI_MEMORY_LETTA_DISABLE_SELF_EDIT` | Letta self-edit を無効化 (CoW セーフ) | `true` |
| `ARI_MEMORY_ACCESS_LOG` | `{checkpoint}/memory_access.jsonl` への書き込み | `on` |
| `ARI_MEMORY_ACCESS_LOG_MAX_MB` | ローテーション閾値 | `100` |
| `ARI_MEMORY_AUTO_RESTORE` | `ari resume` 時にバックアップを自動復元 | `true` |

### 論文査読 (ルーブリック)

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ARI_RUBRIC` | 評価器のスコア軸と lineage 判断が使う rubric_id (例: `neurips`、`sc`、`nature`、`generic_conference`)。論文査読者には届かない (上記 `ari paper` の注記を参照) | `neurips` |
| `ARI_FEWSHOT_MODE` | 現在 inert。書き込む側しか存在せず、`fewshot_mode` は rubric YAML の `params` からのみ決まる | -- |
| `ARI_NUM_REVIEWS_ENSEMBLE` | 独立査読者数 (N>1 で Area Chair メタ査読も実行) | rubric 既定値 (同梱 23 種すべて `1`) |
| `ARI_NUM_REFLECTIONS` | self-reflection ループ回数 | rubric 既定値 (`generic_conference` と `workshop` は 3、他は 5) |

### フェーズごとのモデルオーバーライド

`ARI_MODEL_<PHASE>` として読まれ、未設定または空文字ならそのフェーズは
グローバルの `cfg.llm.model` のままです。

| 変数 | フェーズ |
|------|---------|
| `ARI_MODEL_IDEA` | アイデア生成 |
| `ARI_MODEL_CODING` | AgentLoop / ReAct (インプロセスのコーディングエージェント) |
| `ARI_MODEL_BFTS` | BFTS 実験 |
| `ARI_MODEL_EVAL` | 評価器 / judge |
| `ARI_MODEL_PAPER` | 論文執筆 |

### アイデア生成 (VirSci-live)

アイデア生成のオプトイン vendor-wrap 経路。`ARI_IDEA_VIRSCI_REAL` が ON の
とき、アイデアスキルはライブの Semantic Scholar スナップショット上で VirSci
本物のマルチエージェント機構（`select_coauthors` + `generate_idea`）を実行
します。既定の OFF では挙動は変わりません。`ari run` の `--virsci-live` /
`--virsci-k` / `--virsci-team-size` / `--virsci-n-authors` / `--virsci-n-papers`
フラグがこれらの変数を設定します。議論 LLM はフェーズごとの `ARI_MODEL_IDEA`
モデルに従います。`virsci` pip extra が必要で、無い場合や実行時エラー時は
`idea.json` の契約が同一のまま再実装ループへ degrade します。

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ARI_IDEA_VIRSCI_REAL` | real vendor-wrap 経路の切り替え | (未設定/OFF) |
| `ARI_IDEA_VIRSCI_K` | 議論ターン数（vendor `group_max_discuss_iteration`） | 7 |
| `ARI_IDEA_VIRSCI_TEAM_SIZE` | 最大チームメンバー数（vendor `max_teammember`） | 3 |
| `ARI_IDEA_VIRSCI_N_AUTHORS` | `select_coauthors` 用著者プール | 16 |
| `ARI_IDEA_VIRSCI_N_PAPERS` | SPECTER2 検索コーパスサイズ | 800 |
| `ARI_IDEA_VIRSCI_MAX_TEAMS` | `generate_idea` に通すチーム数の上限 | =`n_ideas` |
| `ARI_IDEA_VIRSCI_SPECTER2_MODEL` | ローカルのクエリ埋め込みモデル | `allenai/specter2_base` |

### .env ファイル

ARI は `.env` ファイルを自動的に読み込みます（以下の順序で確認）：

1. `$ARI_CHECKPOINT_DIR/.env` — この変数が設定されているときだけ（最優先）
2. `<project_root>/.env` — `$ARI_ROOT` が設定されていればそれ、無ければリポジトリルート
3. `<project_root>/ari-core/.env`
4. `~/.env`（最低優先）

形式: `KEY=VALUE`（`#` で始まる行は無視されます）。

いずれも `override=False` で読み込まれるため、シェルで既に export 済みの変数は
**4 つすべて** より優先されます。ファイル同士では、そのキーを最初に設定した
ファイルが勝ちます。

---

## HPC（SLURM）での実行

```bash
# エグゼキューターを設定
export ARI_EXECUTOR=slurm
export ARI_SLURM_PARTITION=your_partition

# SLURM ジョブとして投入
sbatch << 'EOF'
#!/bin/bash
#SBATCH --job-name=ari
#SBATCH --partition=your_partition
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --time=04:00:00
#SBATCH --output=ari_%j.out

# GPU ノードで Ollama を使用する場合:
ollama serve &
sleep 10

export ARI_BACKEND=ollama
export ARI_MODEL=qwen3:32b

cd /path/to/ARI
ari run /path/to/experiment.md --profile hpc
EOF
```

**重要なルール：**

- 常に絶対パスを使用してください（`~` や相対パスは使わない）
- SLURM スクリプト内で標準出力をリダイレクトしないでください（SLURM が `--output` で自動キャプチャします）
- クラスターで必要とされない限り、`--account` や `-A` フラグを追加しないでください

---

## `ari clone <ref> [<dest>]` — v0.7.0+

curated な EAR bundle を「取得 + digest 検証 + 展開」する。
**コード実行は伴わない**。論文を再現する読者の「1 行 install」経路を提供する。

### 対応スキーム

| スキーム | resolver |
|---|---|
| `file://<path>` | ローカル file/dir |
| `https://<url>` / `http://<url>` | tarball ダウンロード |
| `ari://<id>` | ari-registry |
| `gh:<user>/<repo>` | GitHub repo or release |
| `doi:<doi>` | Zenodo deposition |

### フラグ

```
--expect-sha256 <hex>   bundle digest を強制検証。不一致は hard fail。
                        --no-extract 時は無視される (下記参照)。
--no-extract            tarball のみ取得 (展開なし)。このとき digest 検証も
                        すべてスキップされる — digest は展開後のファイルから
                        しか再計算できないため、報告される bundle_sha256 は
                        空になり、--expect-sha256 は一度も比較されない。
--registry <name>       ari:// resolver を registries.yaml の特定 registry に限定。
                        `$ARI_REGISTRIES_FILE` env var を設定するか、
                        `./.ari/registries.yaml` に置くこと。レガシーの
                        `$HOME/.ari/registries.yaml` は v0.5.0 で廃止され
                        DeprecationWarning を出す（v1.0 でフォールバック削除）。
                        該当する名前が無ければ registry は 0 件となり、
                        "no ari-registry configured" で失敗する。
--token <env-or-value>  bearer token (環境変数名 → 値の順で解決)。
```

### 検証モデル

1. resolver が artifact (tarball またはディレクトリ) を一時 dir に書き出す
2. orchestrator が sibling の一時 dir (`_stage`) に展開する。絶対パス、`..`
   による脱出、外部を指すリンクは拒否する
3. 各ファイルの sha256 を再計算し manifest.lock と照合。manifest が挙げている
   のに bundle に無いファイルは hard fail
4. 正規化 manifest (`{version, files:[{path, sha256, size}]}`、`version: 2` では
   各ファイルの `role` も含む) から bundle digest を再計算し
   `manifest.lock.bundle_sha256` と照合 — ただし manifest が実際に宣言している
   場合のみで、`bundle_sha256` が無い manifest は受理される
5. `--expect-sha256` 指定時はそれが再計算 digest と一致しなければ hard fail
6. 全工程成功時のみ stage を dest に rename。失敗時は dest を残さない。
   `dest` は存在しないか空でなければならない

手順 2〜5 は展開する場合にのみ実行されます。`--no-extract` は生の artifact を
コピーするだけで、何も検証しません。

---

## `ari registry` — v0.7.0+

キュレート済み EAR バンドルをホスティングするセルフホスト HTTP
レジストリ。`ari ear publish` と `ari clone` の `ari://` resolver の
デフォルト backend です。サーバ無しで運用したいなら `local-tarball`
で問題ありませんし、学術的恒久性なら Zenodo / GitHub release を推奨します。

```bash
ari registry serve   [--host 0.0.0.0] [--port 8290] [--data-dir <dir>]
ari registry token issue  <user>          # 平文は1度のみ表示
ari registry token revoke <token-id>
ari registry token list
```

セットアップ:

```bash
# 1. サーバ依存は requirements.txt / lockfile に既に含まれているので、通常の
#    ./setup.sh でインストールされる。--with-registry は情報表示のみ。
./setup.sh --with-registry        # または pip install fastapi uvicorn[standard] python-multipart

# 2. データディレクトリを指定して起動 (デフォルトポート 8290)
#    NOTE: `$HOME/.ari/registry-data` は v0.5.0 でデフォルトから削除されました。
#    $ARI_REGISTRY_DATA を明示設定すること（レガシーフォールバックは v1.0 で削除）。
export ARI_REGISTRY_DATA="$PWD/.ari_registry"
./scripts/registry/start_local.sh

# 3. ユーザに token を発行
ari registry token issue alice
# 平文は 1 度のみ表示 — 安全に保管
```

| 項目 | 内容 |
|------|------|
| エンドポイント | `POST /artifact`、`GET\|HEAD /artifact/<id>`、`GET /artifact/<id>/manifest.lock`、`POST /artifact/<id>/promote?target=...`、`DELETE /artifact/<id>`、`/healthz`、`/version` |
| 認証 | bearer token (sqlite ハッシュ保管)。upload/delete/promote は所有者 token 必須。`HEAD /artifact/<id>` と `GET /artifact/<id>/manifest.lock` は token を **一切** 取らない — staged なバンドルの digest・長さ・可視性・ファイル manifest 全体が、id を知っている者なら誰でも読める |
| 可視性 | `staged` (所有者のみ) → `unlisted` (id 知っている者のみ) / `public` (公開)。降格は拒否 |
| Artifact id | `sha256(bundle.tar.gz)[:16]` のコンテンツアドレス |
| ストレージ | `${ARI_REGISTRY_DATA}/artifacts/<id>/{bundle.tar.gz, manifest.lock, meta.json}` |

デプロイモード (詳細は [docs/reference/registry.md](registry.md)):

- `scripts/registry/start_local.sh` — uvicorn + sqlite、シングルプロセス。Laptop / dev。
- `scripts/registry/docker-compose.yml` — nginx + uvicorn + sqlite-on-volume。Production。
- `scripts/registry/start_singularity.sh` — Apptainer / Singularity SIF。HPC。

クライアント設定の `registries.yaml` は `$ARI_REGISTRIES_FILE` env override、
または `./.ari/registries.yaml` に配置します。`$HOME/.ari/registries.yaml` は
v0.5.0 で廃止され DeprecationWarning を出し、フォールバックは v1.0 で削除され
ます。checkpoint スコープの `.ari/registries.yaml` は resolver の docstring に
記載がありますが、現状は **到達しません** — `ari clone` も `ari-registry`
publish バックエンドも lookup に checkpoint を渡さないためです。使いたい場合は
`$ARI_REGISTRIES_FILE` でそのファイルを指してください:

```yaml
registries:
  - name: default
    url: http://127.0.0.1:8290
    token: $ARI_REGISTRY_TOKEN
```

そのうえで `export ARI_REGISTRY_TOKEN=ari_<発行された値>` し、
`ari clone ari://<id>` (エントリを 1 つに固定するなら
`ari clone ari://<registry-name>/<id>`) や
`ari ear publish --backend ari-registry` を使います。`registries.yaml` が
どこにも無い場合、どちらも `$ARI_REGISTRY_URL` + `$ARI_REGISTRY_TOKEN` から
組み立てた単一 registry にフォールバックします。
