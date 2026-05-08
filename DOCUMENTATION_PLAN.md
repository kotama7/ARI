# ARI 網羅的ドキュメンテーション計画 マスター

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> 削除条件: Phase D0〜D5 の全ドキュメント PR がマージされ、§9 の品質ゲートをすべて通過したとき。

## 1. 目的

ARI のドキュメントを「実装に追従し、読者が自走できる」状態にする。並行して進めるリファクタリング計画([REFACTORING.md](REFACTORING.md))と同じ規律で、**実装の挙動を変えずに**ドキュメントだけを整備する。

## 2. 解決すべき課題(現状ギャップ)

### 2-1. 実装と乖離している既存ドキュメント
- `~/.ari/` パス記述が 7 ファイル(en/ja/zh)に残存(v0.5.0 で削除済み)
- v0.6.0 (Letta backend, rubric paper review) と v0.7.0 (ORS, EAR registry, BFTS lineage) の機能が `architecture.md` に部分的にしか反映されていない
- `ari-skill-replicate` `ari-skill-paper-re` が `docs/skills.md` に未掲載
- `experiment_file.md` `extension_guide.md` `hpc_setup.md` `PHILOSOPHY.md` (en) は Apr 17 から更新停止 → v0.5〜v0.7 の差分未反映
- 翻訳 (ja/zh) がさらに後追いで遅れている可能性大

### 2-2. 完全に欠落しているドキュメント
- **REST API リファレンス**: viz ダッシュボードの `/api/*` 50+ エンドポイントが体系的に文書化されていない
- **MCP ツールスキーマリファレンス**: 14 スキルが提供する全ツールの引数・戻り値が一覧化されていない
- **環境変数リファレンス**: `ARI_*` `SLURM_*` `VLM_*` 等の env var が散在
- **ファイル形式リファレンス**: `tree.json` `nodes_tree.json` `results.json` `node_report.json` `settings.json` のスキーマが docstring 以外に存在しない
- **エラー/トラブルシューティング**: ランタイムエラーや SLURM エラーの対応表
- **マイグレーションガイド**: v0.5 → v0.6 → v0.7、および v0.7 → v1.0 (将来) のチェックポイント・設定移行手順
- **テストガイド**: 新スキル/新コアモジュールに対するテスト書き方
- **リリース/バージョニング方針**: SemVer の解釈、サポートポリシー

### 2-3. コードレベル
- `ari-core/ari/<subdir>/__init__.py` のうち 5/6 が docstring 空(viz のみ 1 行あり)
- `ari-skill-coding/` `ari-skill-plot/` `ari-skill-transform/` に README なし
- 公開 API の境界 (`ari/public/`) が未確立(リファクタリング計画の Phase 4 で確立される)
- Pydantic Config モデル (`ari/config.py`) のフィールド docstring が断片的

## 3. 読者像(Audience Taxonomy)

| 読者 | ニーズ | 主に読むドキュメント |
|---|---|---|
| **エンドユーザ(研究者)** | experiment.md を書いて実験を回したい、論文を得たい | `quickstart.md` / `experiment_file.md` / `cli_reference.md` / トラブル時に troubleshooting |
| **スキル開発者** | 新しい MCP スキルを足して ARI に組み込みたい | `extension_guide.md` / 各スキル README / MCP ツールリファレンス / `ari/public/` API リファレンス |
| **コア貢献者** | ari-core のロジックを変更したい | `architecture.md` / `PHILOSOPHY.md` / 各サブディレクトリ README / テストガイド |
| **オペレータ(HPC 管理者)** | ARI を SLURM クラスタに展開・運用したい | `hpc_setup.md` / `configuration.md` / 環境変数リファレンス / トラブルシューティング |

## 4. ドキュメント分類(Diátaxis フレームワーク)

| 分類 | 性質 | 既存例 | 不足 |
|---|---|---|---|
| **Tutorial**(学習指向) | 「やってみる」 | `quickstart.md` | (十分) |
| **How-to**(課題指向) | 「○○するには」 | `hpc_setup.md` `extension_guide.md` | テストガイド、マイグレーションガイド |
| **Reference**(情報指向) | 「定義はこう」 | `cli_reference.md` `configuration.md` `skills.md` | REST API、MCP ツール、環境変数、ファイル形式 |
| **Explanation**(理解指向) | 「なぜこうなっている」 | `architecture.md` `PHILOSOPHY.md` `registry.md` | (内容は十分、追従が必要) |

## 5. 計画書の分配

| 計画書 | 対象 |
|---|---|
| [DOCUMENTATION_PLAN.md](DOCUMENTATION_PLAN.md)(本書) | マスター: ギャップ分析・読者像・フェーズ・品質ゲート |
| [docs/DOCUMENTATION_PLAN.md](docs/DOCUMENTATION_PLAN.md) | 既存ユーザ向けドキュメントの追従、新規 reference docs(REST/MCP/env/file format)、i18n 戦略 |
| [ari-core/DOCUMENTATION_PLAN.md](ari-core/DOCUMENTATION_PLAN.md) | コードレベル: 各サブディレクトリの `__init__.py` docstring、`ari/public/` API リファレンス、Pydantic config フィールド docstring |
| [ari-skill-benchmark/DOCUMENTATION_PLAN.md](ari-skill-benchmark/DOCUMENTATION_PLAN.md) | benchmark スキル README + ツールスキーマ |
| [ari-skill-coding/DOCUMENTATION_PLAN.md](ari-skill-coding/DOCUMENTATION_PLAN.md) | coding スキル(README 新規作成) |
| [ari-skill-evaluator/DOCUMENTATION_PLAN.md](ari-skill-evaluator/DOCUMENTATION_PLAN.md) | evaluator スキル |
| [ari-skill-hpc/DOCUMENTATION_PLAN.md](ari-skill-hpc/DOCUMENTATION_PLAN.md) | hpc スキル |
| [ari-skill-idea/DOCUMENTATION_PLAN.md](ari-skill-idea/DOCUMENTATION_PLAN.md) | idea スキル(VirSci 統合の文書化を含む)|
| [ari-skill-memory/DOCUMENTATION_PLAN.md](ari-skill-memory/DOCUMENTATION_PLAN.md) | memory スキル(Letta 運用) |
| [ari-skill-orchestrator/DOCUMENTATION_PLAN.md](ari-skill-orchestrator/DOCUMENTATION_PLAN.md) | orchestrator スキル(再帰実行) |
| [ari-skill-paper/DOCUMENTATION_PLAN.md](ari-skill-paper/DOCUMENTATION_PLAN.md) | paper スキル(10 ツール、ルブリック)|
| [ari-skill-paper-re/DOCUMENTATION_PLAN.md](ari-skill-paper-re/DOCUMENTATION_PLAN.md) | paper-re スキル(PaperBench 統合)|
| [ari-skill-plot/DOCUMENTATION_PLAN.md](ari-skill-plot/DOCUMENTATION_PLAN.md) | plot スキル(README 新規作成)|
| [ari-skill-replicate/DOCUMENTATION_PLAN.md](ari-skill-replicate/DOCUMENTATION_PLAN.md) | replicate スキル(rubric 自動生成)|
| [ari-skill-transform/DOCUMENTATION_PLAN.md](ari-skill-transform/DOCUMENTATION_PLAN.md) | transform スキル(README 新規作成)|
| [ari-skill-vlm/DOCUMENTATION_PLAN.md](ari-skill-vlm/DOCUMENTATION_PLAN.md) | vlm スキル |
| [ari-skill-web/DOCUMENTATION_PLAN.md](ari-skill-web/DOCUMENTATION_PLAN.md) | web スキル |

## 6. フェーズ計画

| Phase | 内容 | 期間目安 | 並走可否 |
|---|---|---|---|
| **D0** | 監査と既存差分の特定([docs/DOCUMENTATION_PLAN.md §2](docs/DOCUMENTATION_PLAN.md))。`docs/refactor_audit.md`(リファクタ Phase 0 で作成済の場合は流用)に doc audit を追記 | 1〜2 日 | リファクタ Phase 0 と同 PR でも可 |
| **D1** | 既存 docs の追従(`~/.ari/` 一掃、v0.5–v0.7 機能反映、`skills.md` への新スキル追記)| 3〜4 日 | リファクタ Phase 1〜2 と並走可 |
| **D2** | コードレベル: 各 `__init__.py` の docstring、`ari/public/` の API リファレンス、不足 README 3 件 | 3〜4 日 | リファクタ Phase 4 と連動(`ari/public/` 確立後) |
| **D3** | Reference 新規作成: REST API / MCP tool / environment variables / file formats | 5〜7 日 | 単独可 |
| **D4** | How-to 新規: テストガイド、マイグレーションガイド、トラブルシューティング | 3〜4 日 | 単独可 |
| **D5** | i18n 同期(ja/zh 翻訳)、目次更新、リリース/バージョニング方針追加 | 3〜4 日 | D1〜D4 完了後 |

**合計**: 約 18〜26 日(リファクタリングと並走可、独立完了も可)

## 7. PR ポリシー

- **タイトル形式**: `docs(<area>): <what was added/updated>`
  - 例: `docs(viz): add REST API reference for /api/checkpoints/* endpoints`
- **本文に必ず含める**:
  - 「対象読者(エンドユーザ/スキル開発者/コア貢献者/オペレータ)」
  - 「Diátaxis 分類(Tutorial/How-to/Reference/Explanation)」
  - 「実装との突合せ確認(対応コードへの file:line リンクまたはリファクタ計画との整合)」
- **マージ先**: ドキュメント専用ブランチ (`docs-update`) または `refactoring` ブランチに併走

## 8. 挙動保証(ドキュメント版)

ドキュメント作業は**コード挙動を一切変えない**:

- コード変更を伴わない:
  - `docs/` 配下の追加・更新
  - `__init__.py` の docstring 追加(モジュール挙動に影響しない)
  - 各スキルの `README.md` 追加・更新
- ただし以下は本計画の範囲外(必要なら別 PR):
  - Pydantic Config モデルのフィールドに docstring を**新規追加**するのは OK だが、**既定値や型は変えない**
  - `ari/public/` の新設はリファクタ計画 Phase 4 の責務(本計画はそのリファレンスを書くのみ)

## 9. 品質ゲート(全 docs PR 共通)

各 PR は以下を満たすこと:

- [ ] 記述された CLI コマンドを実際に実行して挙動が一致(`ari --help` ベース)
- [ ] 記述された環境変数名・既定値が `ari-core/ari/config.py` または当該スキル `src/server.py` の実装と一致
- [ ] 記述された REST エンドポイントが `viz/server.py`(または分割後の `viz/routes.py`)に実在
- [ ] 記述された MCP ツール名が当該スキルの `mcp.json` または `skill.yaml` に実在
- [ ] 記述された ファイル形式が現行コードで実際に読み書きされる JSON キーと一致
- [ ] リンク切れがない(`grep -nE '\]\([^)]*\)' <doc.md>` で確認)
- [ ] 翻訳ファイル (ja/zh) を更新した場合、英語版との節構成が一致
- [ ] サンプルコード/コマンドが構文的に有効(可能ならテストで実行検証)

## 10. リスク

| リスク | 緩和策 |
|---|---|
| ドキュメントとコードがすぐに再乖離する | 各 PR の品質ゲート(§9)を CI 化(例: env var 名の grep チェック) |
| 翻訳の追従漏れ | 英語版の更新と同 PR 内で ja/zh も更新する規律(D5) |
| REST API リファレンスが手書きで陳腐化する | OpenAPI スキーマの自動生成を将来検討(本計画では手動でも可) |
| マイグレーションガイドが書かれずに v0.5 互換が削除される | リファクタリング計画 Phase 5 と必ずセットで実施 |

---

## 実装完了後の削除

**Phase D0〜D5 の全 PR がマージされ、§9 の品質ゲートをすべて通過した時点で、本ファイルおよび配下の DOCUMENTATION_PLAN.md 計 17 ファイルを削除すること。**

削除コマンド例:

```bash
git rm DOCUMENTATION_PLAN.md \
       docs/DOCUMENTATION_PLAN.md \
       ari-core/DOCUMENTATION_PLAN.md \
       ari-skill-*/DOCUMENTATION_PLAN.md
```

恒久化したい知見は削除前に `docs/architecture.md` `docs/extension_guide.md` `CONTRIBUTING.md` 等に転記する。一時計画書としての性質は本書末尾の「実装完了後の削除」節を参照。
