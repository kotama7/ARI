# リファクタリング監査 (フェーズ 0)

> v0.7.1 リファクタリング開始時点の歴史的インベントリスナップショット。原文のまま保存。
> 以下の表の「計画」セルはすべて完了済みです — 現在のアーキテクチャは `docs/architecture.md`
> (Layered architecture セクション) と `CONTRIBUTING.md`
> (Software-engineering discipline §1–5) に記載されています。本ファイルは考古学的記録として保存します。
> 作業が進行中であるかのように編集しないでください。

## 1. 巨大モジュール (フェーズ 3 分割対象)

| ファイル | 行数 | 計画 |
|---|---:|---|
| `ari-core/ari/cli.py` | 1,962 | フェーズ 3A — `ari/cli/{lineage,bfts_loop,run,projects,commands,migrate}.py` に分割 |
| `ari-core/ari/pipeline.py` | 1,641 | フェーズ 3C — `ari/pipeline/{experiment_md,yaml_loader,stage_control,context_builder,stage_runner,orchestrator}.py` に分割 |
| `ari-core/ari/viz/server.py` | 1,489 | フェーズ 3B — `viz/{websocket,ui_helpers,routes}.py` に分割 |
| `ari-core/ari/agent/loop.py` | 1,459 | フェーズ 3D — `agent/{message_utils,tool_manager,guidance}.py` を抽出 |
| `ari-core/ari/viz/api_state.py` | 1,434 | フェーズ 3B — `viz/{checkpoint_finder,state_sync,checkpoint_api,ear,file_api,checkpoint_lifecycle,node_work_api}.py` に分割 |
| `ari-core/ari/orchestrator/node_report.py` | 706 | フェーズ 3E — `node_report/{builder,legacy_reconstruct}.py` に分割 |

合計: 6 ファイル合わせて **8,691 行**。

## 2. `ARI_CHECKPOINT_DIR` の直接環境変数参照 (フェーズ 1 対象)

cli/pipeline/agent/orchestrator/viz/memory にわたる 31 か所。
フェーズ 1 (PR-1A + PR-1B) 後はすべて
`PathManager.from_env()` を経由します:

```text
ari-core/ari/config.py:153,244
ari-core/ari/orchestrator/bfts.py:27,58
ari-core/ari/lineage.py:56
ari-core/ari/cost_tracker.py:197
ari-core/ari/cli.py:1203,1445,1898
ari-core/ari/pipeline.py:786,791,829,976
ari-core/ari/memory_cli.py:36,46
ari-core/ari/memory/letta_client.py:25
ari-core/ari/memory/auto_migrate.py:51
ari-core/ari/viz/api_experiment.py:622
ari-core/ari/viz/api_memory.py:38
ari-core/ari/viz/api_orchestrator.py:284
ari-core/ari/viz/api_state.py:1389
ari-core/ari/viz/server.py:383
```

(読み取り箇所のみ。MCP 子プロセス env に同期する書き込みは
``os.environ[...] = ...`` のまま — フェーズ 1 の対象外。)

## 3. ファイル横断の重複

| 関心事 | 実装箇所 |
|---|---|
| `workflow.yaml` の探索 | `cli.py:_resolve_cfg`、`pipeline.py:load_workflow`、`viz/server.py:_build_experiment_detail_config` |
| チェックポイント tree.json I/O | `cli.py:_save_tree_incremental`、`cli.py` (削除パス)、`viz/api_state.py:_load_nodes_tree` |

フェーズ 2 でそれぞれ 1 モジュールに統合:
- `ari/config/finder.py` (PR-2A)
- `ari/checkpoint.py` (PR-2B)

## 4. スキル → コア 内部インポート境界違反

| 呼び出し元 | インポート |
|---|---|
| `ari-skill-coding/tests/test_server.py:102` | `import ari.container` |
| `ari-skill-plot/src/server.py:28` | `from ari import cost_tracker` |

フェーズ 4 で両方を `ari/public/` 経由にルーティングし、
`tests/test_public_api_boundary.py` で回帰を防止。

## 5. コード中の `~/.ari/` レガシーパス (DEPRECATION_REMOVAL.md §1-1)

publish/clone/registry/memory/viz_api_publish にわたる 13 か所:

| ファイル:行 | Tier | アクション |
|---|:---:|---|
| `ari/memory/file_client.py:25` | A | DR1 — デフォルト引数を削除 |
| `ari/memory_cli.py:111` | C | DR3 / フェーズ 5 — `migrations/v05_to_v07/memory.py` に移動 |
| `ari/memory_cli.py:306` | B | DR2 → 警告、DR5 → 必須 env |
| `ari/memory/auto_migrate.py:43` | C | migrations モジュールに移動 (フェーズ 5) |
| `ari/publish/backends/ari_registry.py:29,98` | B | DR2 警告 + チェックポイントスコープの参照 |
| `ari/clone/resolvers/ari.py:29,78` | B | publish と同様 (共有ヘルパー) |
| `ari/registry/app.py:29` | B | DR2 + `resolve_data_dir()` ヘルパー |
| `ari/registry/cli.py:20` | B | `app.py` と同様 |
| `ari/viz/api_publish.py:24` | B | モジュールレベルの Path.home() を関数内に移動 |
| `ari/core.py:91` (docstring) | doc | フェーズ 6 |
| `ari/paths.py:113` (docstring) | doc | フェーズ 6 |

## 6. ドキュメント中の `~/.ari/` レガシーパス (フェーズ 6)

`grep -rln "~/\.ari" docs/` → 16 ファイル (en + ja + zh)。フェーズ 0 で
各出現箇所に `[DEPRECATED since v0.5.0]` バナーを追加。フェーズ 6 で
`$ARI_CHECKPOINT_DIR/...` スタイルへの書き換えを完了する。

## 7. 分離すべきマイグレーション負債 (フェーズ 5)

| ソース | 説明 |
|---|---|
| `cli.py:246–305 cmd_migrate_node_reports` | v0.5 → v0.7 node_report マイグレーター |
| `cli.py:1135–1352 backfill_node_reports` (呼び出し元) | レガシーオンデマンドバックフィル |
| `memory/auto_migrate.py` | v0.5 グローバル JSONL → チェックポイントメモリ |
| `evaluator/llm_evaluator.py:586–589` | レガシー 5 軸フォールバック |
| `orchestrator/node_report.py:650 reconstruct_report_from_legacy` | 旧ツリー → node_report 再構築 |

すべて `ari/migrations/v05_to_v07/` に移動し、元のインポートパスには
薄いシムを残す。

## 8. プロンプト / 設定の外部化 (PROMPTS_AND_CONFIG.md §1)

フェーズ PC0–PC8 で対象となる 8 プロンプト + 価格テーブル 1 件 + デフォルトテーブル 1 件:

| ファイル:行 | 出力先 |
|---|---|
| `agent/loop.py:41 SYSTEM_PROMPT` | `ari/prompts/agent/system.md` |
| `orchestrator/lineage_decision.py:239` | `ari/prompts/orchestrator/lineage_decision.md` |
| `orchestrator/root_idea_selector.py:57` | `ari/prompts/orchestrator/root_idea_selector.md` |
| `orchestrator/bfts.py:215,296,481` | `ari/prompts/orchestrator/bfts_*.md` |
| `pipeline.py:430` | `ari/prompts/pipeline/keyword_librarian.md` |
| `evaluator/llm_evaluator.py:165,324` | `ari/prompts/evaluator/{extract_metrics,peer_review}.md` |
| `cost_tracker.py:16–33` 価格辞書 | `ari/configs/model_prices.yaml` |
| `config.py` デフォルト値 | `ari/configs/defaults.yaml` |

## 9. テスト側の監査 (DEPRECATION_REMOVAL.md §1-3)

| ファイル:行 | 問題 | アクション |
|---|---|---|
| `tests/test_ollama_gpu.py:25,125,150,175,190` | `_st._settings_path.write_text(...)` | DR4 — 各呼び出しが `monkeypatch.setattr` の内側にあることを確認 |
| `tests/test_letta_restart_live.py:43` | `Path.home() / ".ari" / "letta-pid"` を読み取る | DR4 — `monkeypatch.setenv("ARI_LETTA_PIDFILE", ...)` フィクスチャを使用 |
| `tests/test_settings_roundtrip.py:8` | docstring に `~/.ari/settings.json` が記載 | フェーズ 6 — コメントを編集 |
| `tests/test_clone.py:190` | docstring | フェーズ 6 |
| `tests/test_paths.py:131` | コメント ("no global ~/.ari anymore") | そのままで OK |

## 10. サブ計画マップ (歴史的記録)

以下のリファクタリングサブ計画はスコープが完了した時点で
`[plan-deletion]` コミットで削除された一回限りの計画ファイルです。
`git log --oneline --diff-filter=D --follow -- <path>` で歴史的記録を
復元できます。

| 計画 (現在は削除済み) | オーナー |
|---|---|
| `REFACTORING.md` (ルート) | マスター |
| `ari-core/REFACTORING.md` | cli/pipeline/core 分割 + 共有モジュール |
| `ari-core/ari/agent/REFACTORING.md` | agent/loop.py 分割 + テスト |
| `ari-core/ari/viz/REFACTORING.md` | viz server/api_state 分割 |
| `ari-core/ari/orchestrator/REFACTORING.md` | node_report 分割 + レガシー分離 |
| `ari-core/ari/evaluator/REFACTORING.md` | プロンプト抽出 + Evaluator Protocol |
| `ari-core/ari/memory/REFACTORING.md` | Tier A/B/C クリーンアップ |
| `ari-core/ari/publish/REFACTORING.md` | Tier B クリーンアップ |
| `ari-core/ari/clone/REFACTORING.md` | Tier B クリーンアップ (publish と共有ヘルパー) |
| `ari-core/ari/registry/REFACTORING.md` | Tier B クリーンアップ (`resolve_data_dir`) |
| `ari-core/tests/REFACTORING.md` | Tier D テスト分離 |
| `ari-skill-coding/REFACTORING.md` | `ari.public.container` 移行 |
| `ari-skill-plot/REFACTORING.md` | `ari.public.cost_tracker` 移行 |
| `PROMPTS_AND_CONFIG.md` | プロンプト/設定外部化マスター |
| `DEPRECATION_REMOVAL.md` | Tier 分類 + DR0–DR5 フェーズ |

## 11. ドキュメント監査 (フェーズ D0 — DOCUMENTATION_PLAN.md)

マスター `DOCUMENTATION_PLAN.md` とその 16 サブ計画に対して
2026-05-09 に取得したスナップショット。計画が「欠けている」と指摘した
一部の項目はすでに完了していました。以下の表で計画と実態を照合します。

### 11-1. ドキュメント中の `~/.ari/` 残留 (DOCUMENTATION_PLAN.md §2-1)

`grep -rn '~/\.ari' docs/` が 17 ファイルにヒット (16 製品ドキュメント + 本監査ファイル)。
§9 品質ゲートが `docs/` 全体でヒット数ゼロを要求するため、すべての参照を
v0.5.0+ のスコープ付き表記に書き換える必要があります:

| 旧 | 新 |
|---|---|
| `~/.ari/registries.yaml` | `$ARI_CHECKPOINT_DIR/.ari/registries.yaml` (または `$ARI_REGISTRIES_FILE`) |
| `~/.ari/registry-data` | `$ARI_REGISTRY_DATA` (グローバルデフォルトなし) |
| `~/.ari/settings.json` | `$ARI_CHECKPOINT_DIR/settings.json` |
| `~/.ari/global_memory.jsonl` | `$ARI_CHECKPOINT_DIR/memory_store.jsonl` (ファイルバックエンド) または Letta ストア |
| `~/.ari/letta-pid` | `$ARI_LETTA_PIDFILE` |

書き換えが必要なファイル (すべて *非推奨注記* は残すが、`~/.ari/...` の
リテラルパスは記載しない):

```
docs/architecture.md       docs/ja/architecture.md       docs/zh/architecture.md
docs/cli_reference.md      docs/ja/cli_reference.md      docs/zh/cli_reference.md
docs/configuration.md      docs/ja/configuration.md      docs/zh/configuration.md
docs/registry.md           docs/ja/registry.md           docs/zh/registry.md
docs/skills.md             docs/ja/skills.md             docs/zh/skills.md
```

(`docs/refactor_audit.md` と `docs/DOCUMENTATION_PLAN.md` はそのまま残す —
これらは意図的にレガシー状態を扱うファイルです。§9 の grep は製品ドキュメントのみを対象とします。)

### 11-2. マスター計画 §2 との照合

| 計画の主張 | 実態 (5月9日) | アクション |
|---|---|---|
| `architecture.md` が v0.6/v0.7 の反映を欠く | §"Publication Lifecycle (v0.7.0)"、§"Plan / Venue contract (v0.7.0+)"、§"work_dir inheritance (v0.7.0 / Phase 7)"、§"v0.6.0: backed by Letta"、§"Layered architecture (v0.7+ refactor)" がすでに存在 | **完了 — 書き換え不要。** §"Module Reference" から新しいリファレンスドキュメントへのクロスリンクのみ追加。 |
| `skills.md` に `ari-skill-replicate`、`ari-skill-paper-re` が欠ける | L273 (`paper-re`) と L430 (`replicate`) にフルツールテーブルと v0.7.0 マーカー付きでがすでに存在 | **完了。** ja/zh のパリティを確認する。 |
| `experiment_file.md`、`extension_guide.md`、`hpc_setup.md`、`PHILOSOPHY.md` が Apr 17 のまま | `extension_guide.md` (May 8)、`PHILOSOPHY.md` (May 8) は最新。古いのは `experiment_file.md` と `hpc_setup.md` のみ。 | 4 件ではなく **2 件** のドキュメントを更新する。 |
| `ari-skill-coding/`、`plot/`、`transform/` に README がない | 確認済み。 | 作成する。 |
| `ari/public/` がまだ存在しない | すでに 5 モジュール (`config_schema.py`、`container.py`、`cost_tracker.py`、`llm.py`、`paths.py`) を持って存在している。 | フェーズ 4 はコードで**すでに完了**。フェーズ D2 ではリファレンスドキュメントの執筆のみ必要。 |
| `ari-core/ari/<subdir>/__init__.py` がほぼ空 | 空: `agent`、`llm`、`mcp`、`memory`、`orchestrator`。1 行: `viz`。それ以外は docstring あり。 | 5 サブディレクトリを埋める。 |

### 11-3. 執筆すべきドキュメントの差分 (優先順)

| # | 項目 | 種別 | フェーズ | オーナードキュメント |
|---|---|:---:|:---:|---|
| 1 | 15 製品ドキュメント (en + ja + zh) の `~/.ari/` 一括置換 | 機械的 | D1-2-1 | `cli_reference.md`、`configuration.md`、`registry.md`、`skills.md`、`architecture.md` × 3 言語 |
| 2 | `skills.md` ja/zh に en と同等の replicate + paper-re セクションがあるか再確認 | パリティ | D1-2-2 | `docs/{ja,zh}/skills.md` |
| 3 | `experiment_file.md` を v0.6 (rubric、ORS メタデータ) および v0.7 (experiment.md の lineage decisions) 向けに更新 | コンテンツ | D1-2-4 | `docs/{,ja/,zh/}experiment_file.md` |
| 4 | `hpc_setup.md` をコンテナデプロイ + Letta バックエンドデプロイ向けに更新 | コンテンツ | D1-2-4 | `docs/{,ja/,zh/}hpc_setup.md` |
| 5 | 空の 5 サブディレクトリの `__init__.py` docstring + `viz` の書き直し | コードドキュメント | D2 | `ari/{agent,llm,mcp,memory,orchestrator,viz}/__init__.py` |
| 6 | `ari-skill-coding/`、`plot/`、`transform/` の README | コードドキュメント | D2 | 新規ファイル |
| 7 | `ari.public.*` を扱う `docs/reference/public_api.md` | リファレンス | D2/D3 | 新規ファイル |
| 8 | `viz/routes.py` + 兄弟 `viz/api_*.py` を対象とする `docs/reference/rest_api.md` | リファレンス | D3 | 新規ファイル |
| 9 | `mcp.json` × 14 スキルを集約する `docs/reference/mcp_tools.md` | リファレンス | D3 | 新規ファイル |
| 10 | `docs/reference/environment_variables.md` | リファレンス | D3 | 新規ファイル |
| 11 | `docs/reference/file_formats.md` (`tree.json`、`nodes_tree.json`、`node_report.json`、`settings.json`、`workflow.yaml`、`experiment.md`) | リファレンス | D3 | 新規ファイル |
| 12 | `docs/howto/testing.md` | ハウツー | D4 | 新規ファイル |
| 13 | `docs/howto/migration.md` (v0.5 → v0.6 → v0.7) | ハウツー | D4 | 新規ファイル |
| 14 | `docs/howto/troubleshooting.md` | ハウツー | D4 | 新規ファイル |
| 15 | `docs/release_policy.md` (SemVer、サポートウィンドウ) | ハウツー | D5 | 新規ファイル |
| 16 | 項目 1、3、4、12–15 の ja/zh 同期 | i18n | D5 | 翻訳 |

### 11-4. 引き継ぐ受け入れゲート

各 PR が自己チェックできるよう、§9 マスター計画のゲートをここに再掲します:

- `grep -rn '~/\.ari/' docs/` (`docs/DOCUMENTATION_PLAN.md` と
  `docs/refactor_audit.md` を除く) がゼロを返す。
- ドキュメント化されたすべての CLI フラグ、環境変数、REST エンドポイント、MCP ツール名が
  対応するソースツリーの `grep -rn` で実際のシンボルにマップされる。
- ja と zh は *レガシー* ドキュメントについて en とセクション構造のパリティを保つ
  (新しいリファレンスドキュメントは en ファースト。ja/zh は遅れても可)。
- Markdown リンクチェック (`grep -nE '\]\([^)]*\)' docs/**/*.md` による
  手動またはスクリプトによる検証) でリポジトリ内の壊れたリンクがゼロを返す。
