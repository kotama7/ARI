# ARI リファクタリング マスター計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> 削除条件: Phase 0〜6 の全 PR がマージされ、`docs/architecture.md` への反映が完了したとき。

## 1. 目的

ARI プロジェクトに蓄積した以下を解消する:

- **巨大モジュール(god-object)**: `cli.py` 1,962 行 / `pipeline.py` 1,641 行 / `viz/server.py` 1,489 行 / `agent/loop.py` 1,459 行 / `viz/api_state.py` 1,434 行(計 7,985 行)
- **テスト空白**: `ari-core/ari/agent/` 配下 0 テスト(ReAct ループの中核)
- **状態管理の散在**: `ARI_CHECKPOINT_DIR` の env 直読み 31 箇所
- **クロスファイル重複**: workflow.yaml 探索が 3 箇所、checkpoint I/O が 3 箇所
- **移行債務**: v0.5 → v0.7 のバックワード互換コードが 48 箇所に拡散
- **ドキュメント残存**: `~/.ari/` パス記述が 7 ドキュメントに残存(v0.5.0 で削除済み)

## 2. 挙動保証契約 (Behavior Preservation Contract) — 最重要

このリファクタは **挙動を一切変えない**。下記すべてを変更してはならない:

| 保証項目 | 検証方法 |
|---|---|
| CLI コマンド体系 (`ari run/resume/paper/viz/status/projects/show/delete/settings/skills-list`) | `ari --help` の出力差分が空 |
| CLI 引数(必須/任意/型/既定値) | 各コマンドの `--help` 差分が空 |
| Web ダッシュボード REST API パス | `curl` で `/api/state` `/api/experiments` `/api/checkpoints` 等を叩き、レスポンス JSON のキー集合が一致 |
| WebSocket メッセージ形式 | 既存クライアント(React SPA)が再ビルドなしで動作 |
| MCP ツール名・引数スキーマ | 14 スキルの `mcp.json` / `skill.yaml` を変更しない |
| ファイル形式 | `tree.json` `nodes_tree.json` `results.json` `node_report.json` `settings.json` `workflow.yaml` `experiment.md` の読み書きスキーマ不変 |
| 環境変数 | `ARI_CHECKPOINT_DIR` `ARI_MEMORY_PATH` `ARI_LLM_MODEL` 他、すべての名前と既定値・フォールバック順を維持 |
| ログ出力 | レベル・形式・出力先(stdout / `{checkpoint}/run.log` / `access.log`)を維持 |
| チェックポイント互換 | v0.5 / v0.6 / v0.7 で作成された既存チェックポイントが読める |
| BFTS 決定論 (P2) | 同一 seed での BFTS ツリー形状が完全一致(回帰テストで検証) |
| LLM コスト計上 | `cost_tracker` が記録するキー集合・JSON 形式が同じ |

**実装規律:**
- 1 PR で「分割のみ」または「リネームのみ」または「移動のみ」のいずれかに限定。複数を混ぜない。
- 機能追加・バグ修正は別 PR で行う(本リファクタの PR には混ぜない)。
- すべての PR で `pytest ari-core/tests/ -q` がグリーン。
- すべての PR で「分割前と分割後の AST トップレベルシンボル集合が同一」を `git diff --stat` と grep で確認。

## 3. レイヤー構造(分割順序の根拠)

```
Layer 0: 内部依存ゼロ — config / paths / container / env_detect / cost_tracker / pidfile / schemas / lineage
Layer 1: ドメインモデル — llm / mcp / memory / clone / publish / evaluator / orchestrator.node
Layer 2: オーケストレータ — orchestrator.{bfts, lineage_decision, root_idea_selector, node_report, ...}
Layer 3: エージェント — agent.{workflow, react_driver, loop, run_env}
Layer 4: パイプライン — pipeline.py / core.py
Layer 5: エントリポイント — cli.py / cli_ear.py / viz / registry
```

**循環 import なし**(調査済み)。**下層から上に**リファクタを進める。

## 4. フェーズ計画

| Phase | 内容 | PR 数 | 期間目安 | 計画書 |
|---|---|---|---|---|
| 0 | 基盤整備(agent スモークテスト、監査ドキュメント、DEPRECATED バナー) | 1 | 2〜3 日 | 本ファイル §6 |
| 1 | 状態管理の単一化(PathManager に集約) | 2 | 3〜4 日 | [ari-core/REFACTORING.md](ari-core/REFACTORING.md) |
| 2 | 共有モジュール抽出(`ari/checkpoint.py`, `ari/config/finder.py`) | 2 | 2〜3 日 | [ari-core/REFACTORING.md](ari-core/REFACTORING.md) |
| 3 | 巨大モジュール分割(5 PR、独立に実施可) | 5 | 2 週間 | 各サブ計画(下記)|
| 4 | 公開 API 切り出し(`ari/public/`)+ スキル側移行 | 1 | 2〜3 日 | [ari-skill-coding](ari-skill-coding/REFACTORING.md), [ari-skill-plot](ari-skill-plot/REFACTORING.md) |
| 5 | 移行債務の隔離(`ari/migrations/v05_to_v07/`) | 1 | 1〜2 日 | [ari-core/ari/orchestrator/REFACTORING.md](ari-core/ari/orchestrator/REFACTORING.md) |
| 6 | ドキュメント整備(`docs/architecture.md` 再構成、`~/.ari/` 一掃) | 継続 | 各 PR に併走 | 本ファイル §8 |

## 5. 計画書の分配(このリポジトリ内)

| 計画書 | 対象 |
|---|---|
| [REFACTORING.md](REFACTORING.md)(本書)| マスター: フェーズ・契約・PR ポリシー |
| [ari-core/REFACTORING.md](ari-core/REFACTORING.md) | `cli.py` `pipeline.py` `core.py` 分割 + 共有モジュール新設 |
| [ari-core/ari/agent/REFACTORING.md](ari-core/ari/agent/REFACTORING.md) | `agent/loop.py` 1,459 行の分割 + テスト新設 |
| [ari-core/ari/viz/REFACTORING.md](ari-core/ari/viz/REFACTORING.md) | `viz/server.py` + `viz/api_state.py` 計 2,923 行の分割 |
| [ari-core/ari/orchestrator/REFACTORING.md](ari-core/ari/orchestrator/REFACTORING.md) | `node_report.py` 分割 + legacy 隔離 |
| [ari-skill-coding/REFACTORING.md](ari-skill-coding/REFACTORING.md) | `ari.container` → `ari.public.container` 移行 |
| [ari-skill-plot/REFACTORING.md](ari-skill-plot/REFACTORING.md) | `ari.cost_tracker` → `ari.public.cost_tracker` 移行 |

**変更不要の領域**(リネームも分割もない):
- `ari-core/ari/llm/` `ari-core/ari/mcp/` `ari-core/ari/memory/` `ari-core/ari/evaluator/` `ari-core/ari/clone/` `ari-core/ari/publish/` `ari-core/ari/registry/` `ari-core/ari/schemas/`
- `ari-skill-benchmark/` `ari-skill-evaluator/` `ari-skill-hpc/` `ari-skill-idea/` `ari-skill-memory/` `ari-skill-orchestrator/` `ari-skill-paper/` `ari-skill-paper-re/` `ari-skill-replicate/` `ari-skill-transform/` `ari-skill-vlm/` `ari-skill-web/`

## 6. Phase 0 の詳細(マスター計画書配下で実施)

### Phase 0 の成果物(1 PR)
1. `ari-core/tests/test_agent_smoke.py` を新設、3 ケース追加:
   - `test_agent_loop_single_node_roundtrip` — モック LLM/MCP で 1 ノードの ReAct 往復
   - `test_react_driver_tool_invocation` — `react_driver.run_react()` のツール呼び出し往復
   - `test_workflow_phase_transitions` — `workflow.WorkflowHints` のフェーズ遷移列
2. `docs/refactor_audit.md` を新設、以下の事実を表で記録:
   - `ARI_CHECKPOINT_DIR` 直読み 31 箇所のリスト
   - skill→core 内部 import 箇所(`ari-skill-coding/tests/test_server.py:102`, `ari-skill-plot/src/server.py:28`)
   - 巨大モジュール 5 件の現行行数
3. `docs/architecture.md` の `~/.ari/` 残存箇所(7 ファイル)に DEPRECATED バナーを付与
4. 本マスター計画とサブ計画 6 件を `refactoring` ブランチにコミット

### 受け入れ基準
- `pytest ari-core/tests/test_agent_smoke.py -v` がグリーン
- `grep -rn "~/.ari/" docs/` の各ヒットの直後に `[DEPRECATED since v0.5.0]` が現れる

## 7. PR ポリシー

- **タイトル形式**: `refactor(<area>): <what was split/moved> [no behavior change]`
  - 例: `refactor(cli): split lineage decision helpers into ari/cli/lineage.py [no behavior change]`
- **本文に必ず含める**:
  - 「挙動保証契約 (REFACTORING.md §2) を満たしていることの確認」
  - 「分割前後で公開シンボル集合が同一であることの grep 結果」
  - 「`pytest -q` のグリーンログ」
- **マージ先**: `refactoring` ブランチに小さく積み上げ、Phase 6 完了時に `main` へ一括 PR(または定期的にバンドル)。

## 8. ドキュメント整備(Phase 6、継続)

各 PR に併走して実施。専用 PR 不要。

- `docs/architecture.md`: §3 のレイヤー図を反映
- `docs/skills.md`: 14 スキルの責務・ツール・LLM 使用・決定論性を表で更新
- `docs/extension_guide.md`: 「`ari.public` だけが公開 API」を明記
- `~/.ari/` 残存記述 7 ファイル(英・日・中)を `$ARI_CHECKPOINT_DIR` 表記に置換
- README の Skill 一覧に `ari-skill-replicate` `ari-skill-paper-re` を追記

## 9. リスク管理

| リスク | 影響度 | 緩和策 |
|---|---|---|
| `agent/loop.py` 分割で BFTS 決定論性 (P2) を壊す | 高 | Phase 0 のスモーク 3 本 + 同一 seed の BFTS 同型ツリー回帰テストを Phase 3D 直前に追加 |
| viz の REST API が破ける | 中 | 各 PR のレビューで `curl` で代表 6 エンドポイントを叩く手順をテンプレ化 |
| 14 個の MCP server が分割中に動かなくなる | 高 | Phase 1〜3 中はスキル側を一切触らない。Phase 4 で 2 スキルのみ `ari.public` 移行 |
| 1 PR が大きすぎてレビュー不能 | 中 | 1 PR = 1 ファイル分割を上限。マスター計画 §7 で強制 |
| 既存チェックポイントが読めなくなる | 高 | Phase 5 で migrations を移動するだけで削除しない。v1.0 で削除予告のみ |

## 10. 受け入れ基準(全 PR 共通)

各 PR は以下をすべて満たすこと:

- [ ] `pytest ari-core/tests/ -q` がグリーン
- [ ] `ari --help` 出力が変更前と完全一致
- [ ] 影響範囲のサブコマンドの `--help` が変更前と完全一致
- [ ] `git log --diff-filter=D --summary` で削除されたファイルが計画通りであること
- [ ] 公開シンボル(クラス名・関数名)の集合が変更前と一致(計画的にプライベート化する場合を除く)
- [ ] 該当する計画書(ari-core/agent/viz/orchestrator/skill)の「挙動保証チェックリスト」に全パス

## 11. ソフトウェア工学原則(本リファクタの一級制約)

§2 挙動保証契約と並ぶ**最重要制約**。すべての PR は §2 と §11 の両方を満たすこと。
これに反する分割案は採用しない。

### 11-1. 関心の分離 (Separation of Concerns)

「**1 モジュール = 1 変更理由**」を貫く。

**禁則:**
- 1 ファイル内で「ビジネスロジック + I/O + プロンプト/テンプレート + 設定値」を混在させない
- 分割の動機が「行数を減らす」だけならば棄却。**変更理由の差** で分割すること
- viz の `do_GET` の if-elif チェーンに「認証」「キャッシュ」「ロギング」「ルーティング」「シリアライズ」を全部押し込まない

**実装:**
- §3 のレイヤー構造に従って、各層の関心事を厳格に分離
- `ari/cli.py` は「コマンド種別」(run / paper / projects)で分割([§C-1](#c-cli-split))
- `ari/pipeline/` は「ステージ実行」「YAML 解釈」「コンテキスト構築」を別ファイルに

### 11-2. 疎結合 (Loose Coupling)

具象クラスへの直接依存を最小化する。

**禁則:**
- 新規に `from ari.X.concrete import ConcreteClass` を増やさない(既存削減を目指す)
- グローバル状態(モジュール変数経由のインスタンス共有)を**新規追加禁止**
- 1 関数が 5 つ以上の `ari.*` モジュールを import する場合、それは設計の警告

**実装:**
- 主要な依存は §11-3 の Protocol 経由に置き換え
- `core.build_runtime()` を Composition Root とし、依存性注入を 1 箇所に集約
- `viz/state.py` のグローバル `_st` は本リファクタの範囲外だが、新規同様パターンの導入は禁止

### 11-3. 抽象化 (Abstraction via Protocols)

`ari/protocols/` を新設し、コア間インターフェースを Protocol / ABC で明示する。
**詳細設計**: [ari-core/REFACTORING.md §11](ari-core/REFACTORING.md)。

最小定義 Protocol(Phase 1〜3 で順次新設):
- `LLMClient` — completion / chat completion API
- `MCPClient` — tool registry + execute
- `MemoryClient` — 既存 ABC を Protocol 化(再エクスポート)
- `NodeStore` — tree.json / nodes_tree.json の I/O 抽象([§D `ari/checkpoint.py`](#d-shared) を Protocol 化)
- `PromptLoader` — プロンプト読み込み(§11-4)
- `ConfigLoader` — 既定値・参照テーブルの読み込み(§11-4)
- `Evaluator` — メトリクス抽出戦略
- `StageRunner` — pipeline ステージの実行戦略

### 11-4. プロンプト・設定の外部化(必須)

**ARI コア内の LLM プロンプトは、すべて外部ファイルに分離する**。
**マジック文字列・既定値もコードに直書きしない**。
**詳細**: [PROMPTS_AND_CONFIG.md](PROMPTS_AND_CONFIG.md)。

**抽出対象(監査済 8 prompt + 設定値)**:
- `ari/agent/loop.py:41` `SYSTEM_PROMPT` → `ari/prompts/agent/system.md`
- `ari/orchestrator/lineage_decision.py:239` → `ari/prompts/orchestrator/lineage_decision.md`
- `ari/orchestrator/root_idea_selector.py:57` → `ari/prompts/orchestrator/root_idea_selector.md`
- `ari/orchestrator/bfts.py:215, 296, 481` → `ari/prompts/orchestrator/bfts_*.md`(3 ファイル)
- `ari/pipeline.py:430` → `ari/prompts/pipeline/keyword_librarian.md`
- `ari/evaluator/llm_evaluator.py:165, 324` → `ari/prompts/evaluator/*.md`
- `ari/cost_tracker.py:16-33` モデル価格 dict → `ari/configs/model_prices.yaml`
- `ari/config.py` `lineage_decision.py:266` 等の既定値 → `ari/configs/defaults.yaml`

**禁則(本リファクタ後は新規導入も禁止)**:
- `f"You are..."` のインラインプロンプト
- `_SYSTEM_PROMPT = (...)` のモジュール定数化された prompt
- モデル名(`"gpt-4o-mini"` `"claude-..."` 等)のコード直書き
- 価格テーブル等の参照データのコード内 dict 化

## 12. 計画書の追加分配(§11 の適用)

§5 のリストに以下を追加。既存サブ計画書はこれらを参照するよう更新済み:

| 計画書 | 対象 |
|---|---|
| [PROMPTS_AND_CONFIG.md](PROMPTS_AND_CONFIG.md) | プロンプト・設定外部化マスター(`ari/prompts/` `ari/configs/` 新設、抽出対象 8 prompt、PromptLoader/ConfigLoader 設計、Phase PC0〜PC8) |
| [ari-core/ari/evaluator/REFACTORING.md](ari-core/ari/evaluator/REFACTORING.md) | evaluator の prompt 抽出 + LLMEvaluator の Protocol 化(従来 §5「変更不要」から昇格) |

§5 で「変更不要」としていた `ari-core/ari/evaluator/` は、§11-4 適用のため **変更スコープに追加**。

## 13. 廃止機能・不正パスの体系的削除

### 13-1. 監査結果(要旨)

ARI v0.5.0 のリリースで「`~/.ari/` グローバル状態を廃止」と宣言されたが、実コードには **13 箇所**の `~/.ari/` 直接参照が残存している。同時に v0.5→v0.7 移行債務、廃止予定 env エイリアス、廃止予定フィールド等が本流に混在(48 occurrences)。
詳細監査と対処は [DEPRECATION_REMOVAL.md](DEPRECATION_REMOVAL.md) を参照。

### 13-2. Tier 分類による対処方針

| Tier | 性質 | 対処 |
|---|---|---|
| **A** | 真に不要 | **即削除**(例: `memory/file_client.py:25` の `~/.ari/memory.json` デフォルト引数) |
| **B** | フォールバック中、ユーザ依存リスクあり | **DeprecationWarning → 1 マイナーバージョン後に削除**(例: `~/.ari/registries.yaml` `~/.ari/registry-data` `~/.ari/publish.yaml`) |
| **C** | 後方互換のため必須 | **隔離** (`ari/migrations/v05_to_v07/` へ。Phase 5 と整合) |
| **D** | テスト固有の不正書き込み | **tmp_path / monkeypatch 化、CI で再発防止** |

### 13-3. 計画書の追加分配

§5 のリストに以下を追加。既存「変更不要」だった領域 4 件を変更スコープに昇格:

| 計画書 | Tier | 主な対象 |
|---|---|---|
| [DEPRECATION_REMOVAL.md](DEPRECATION_REMOVAL.md) | マスター | DR0〜DR5 全体管理、`ari/_deprecation.py` ヘルパ、CHANGELOG v1.0 削除予告 |
| [ari-core/ari/memory/REFACTORING.md](ari-core/ari/memory/REFACTORING.md) | A+B+C | `file_client.py:25` デフォルト引数 / `memory_cli.py:111, 306` / `auto_migrate.py:43` |
| [ari-core/ari/publish/REFACTORING.md](ari-core/ari/publish/REFACTORING.md) | B | `backends/ari_registry.py:29, 98` のフォールバック |
| [ari-core/ari/clone/REFACTORING.md](ari-core/ari/clone/REFACTORING.md) | B | `resolvers/ari.py:29, 78` のフォールバック(publish と共通化) |
| [ari-core/ari/registry/REFACTORING.md](ari-core/ari/registry/REFACTORING.md) | B | `app.py:29` `cli.py:20` の `~/.ari/registry-data` |
| [ari-core/tests/REFACTORING.md](ari-core/tests/REFACTORING.md) | D | `test_ollama_gpu.py` `test_letta_restart_live.py` の monkeypatch 化、CI ガード |

### 13-4. Phase DR(リファクタ Phase と並走)

| Phase | 内容 | 互換破壊 |
|---|---|---|
| **DR0** | 監査確定 + `ari/_deprecation.py` ヘルパ実装 + 新規テスト雛形 | なし |
| **DR1** | Tier A 即削除(`memory/file_client.py:25` のデフォルト引数等) | 微小 |
| **DR2** | Tier B に DeprecationWarning 追加 | なし(警告のみ) |
| **DR3** | Tier B のフォールバック先をチェックポイントスコープへ拡張 | なし |
| **DR4** | テスト修正(Tier D)+ CI ガード | なし |
| **DR5(v1.0)** | Tier B のフォールバック完全削除 + 自動移行終了 | **v1.0 互換破壊** |

DR0〜DR4 は本リファクタの範囲。DR5 は v1.0 リリース PR で実施。

### 13-5. 既存「変更不要」領域からの昇格

§5 で「変更不要」としていた以下を本リファクタで触ることになる(§11-4 と §13 の合算):

- `ari-core/ari/evaluator/` — §11-4 prompt 抽出
- `ari-core/ari/memory/` — §13 廃止パス対処
- `ari-core/ari/publish/` — §13 廃止パス対処
- `ari-core/ari/clone/` — §13 廃止パス対処
- `ari-core/ari/registry/` — §13 廃止パス対処
- `ari-core/tests/` — §13-Tier D テスト修正

**変更しない領域**(本リファクタ通じて触らない):
- `ari-core/ari/llm/` `ari-core/ari/mcp/` `ari-core/ari/schemas/` `ari-core/ari/cli_ear.py` `ari-core/ari/lineage.py` `ari-core/ari/env_detect.py` `ari-core/ari/pidfile.py`
- 14 スキル中 12 スキル(coding と plot のみ Phase 4 で公開 API 移行)

---

## 実装完了後の削除

**Phase 0〜6 と Phase PC0〜PC8 の全 PR がマージされ、`docs/architecture.md` への反映が完了した時点で、本ファイルおよび配下の REFACTORING.md 計 8 ファイル + PROMPTS_AND_CONFIG.md を削除すること。** 一時的な計画書であり、リポジトリの恒久ドキュメントではない。

削除コマンド例(Phase 6 完了 PR の最終コミットに含める):

```bash
git rm REFACTORING.md \
       PROMPTS_AND_CONFIG.md \
       DEPRECATION_REMOVAL.md \
       ari-core/REFACTORING.md \
       ari-core/ari/agent/REFACTORING.md \
       ari-core/ari/viz/REFACTORING.md \
       ari-core/ari/orchestrator/REFACTORING.md \
       ari-core/ari/evaluator/REFACTORING.md \
       ari-core/ari/memory/REFACTORING.md \
       ari-core/ari/publish/REFACTORING.md \
       ari-core/ari/clone/REFACTORING.md \
       ari-core/ari/registry/REFACTORING.md \
       ari-core/tests/REFACTORING.md \
       ari-skill-coding/REFACTORING.md \
       ari-skill-plot/REFACTORING.md
```

恒久化したい知見は削除前に `docs/architecture.md` `docs/extension_guide.md` `CONTRIBUTING.md` に転記する。
特に §11 の原則(関心の分離・疎結合・抽象化・prompt/config 外部化)は **`CONTRIBUTING.md` の設計規律として恒久化** すること。
