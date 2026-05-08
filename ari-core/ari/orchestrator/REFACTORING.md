# ari/orchestrator/ リファクタリング計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../../../REFACTORING.md](../../../REFACTORING.md)

## 0. 挙動保証契約

[マスター計画 §2](../../../REFACTORING.md) の契約を厳守する。特に:

- `Node` `NodeStatus` `NodeLabel` の dataclass フィールド・enum 値を変えない
- `BFTS` クラスの公開シグネチャを変えない
- `LineageDecision` `LineageState` の dataclass フィールドを変えない
- `node_report.json` のスキーマを変えない(legacy 互換含む)
- 同一 seed での BFTS 選択順序を変えない(P2 決定論性)
- `reconstruct_report_from_legacy` の動作を変えない(古いチェックポイントが読めなくなってはならない)

## 1. 現状

| ファイル | 行数 | 責務 |
|---|---|---|
| `node.py` | 160 | Node データモデル(NodeStatus / NodeLabel enum) — **触らない** |
| `scheduler.py` | 67 | SchedulerStats — **触らない** |
| `bfts.py` | 605 | BFTS 最適化、ノード選択、獲得関数 — **触らない**(本リファクタの範囲外) |
| `node_selection.py` | 302 | ノード選択ユーティリティ — **触らない** |
| `node_report.py` | 706 | ノードレポート生成、ログパース、メトリクス集約(分割対象) |
| `lineage_decision.py` | 525 | Lineage decision エンジン — **触らない** |
| `root_idea_selector.py` | 257 | 初期 idea 選択 — **触らない** |

**合計: 2,622 行**

## 2. 計画

### Step 1: `node_report.py` の分割 (Phase 3, PR-3E)

現状: 706 行。本流ロジックと legacy 互換ロジックが混在。

#### 分割マッピング

| 新ファイル | 由来行 | 含めるシンボル |
|---|---|---|
| `node_report/__init__.py` | — | `from .builder import build_node_report` 等の再エクスポート |
| `node_report/builder.py` | L1–649 (現行ファイルの大部分) | `build_node_report` / `read_decision_log` / メトリクス集約・サマリ生成 |
| `node_report/legacy_reconstruct.py` | L650–706 | `reconstruct_report_from_legacy`(古いツリー形式から node_report.json を再構築) |

#### 公開シンボルの後方互換
- `from ari.orchestrator.node_report import build_node_report, reconstruct_report_from_legacy` がリファクタ後も動くこと
- `__init__.py` ですべて再エクスポート

### Step 2: 移行債務の隔離 (Phase 5)

`legacy_reconstruct.py` を更に `ari/migrations/v05_to_v07/node_reports.py` へ移動する(Step 1 の後に独立 PR として実施)。

#### 移動先と shim 配置

```
ari/migrations/v05_to_v07/
├── __init__.py
└── node_reports.py     # legacy_reconstruct.py を移動
```

`ari/orchestrator/node_report/legacy_reconstruct.py` には薄い shim を残す:
```python
# legacy_reconstruct.py(shim 化後)
from ari.migrations.v05_to_v07.node_reports import reconstruct_report_from_legacy

__all__ = ["reconstruct_report_from_legacy"]
```

これにより:
- 既存の `from ari.orchestrator.node_report import reconstruct_report_from_legacy` が動き続ける
- 「移行コードはここ」という所在が明確になる
- v0.8 リリースノートで「v1.0 で `legacy_reconstruct.py` shim を削除予定」と予告

### Step 3: 関連: `cmd_migrate_node_reports` の集約

`ari/cli.py:251–324` の `cmd_migrate_node_reports`(Phase 3 の PR-3A で `ari/cli/migrate.py` に移動済み)を、Phase 5 で `ari/migrations/v05_to_v07/node_reports.py` 内のロジックを呼ぶ形にリファクタする。CLI コマンド名 `ari migrate node-reports` は不変。

### Step 3: prompt 外部化(Phase PC4 + PC5)

マスター §11-4 適用。詳細 [/PROMPTS_AND_CONFIG.md §3-2 〜 §3-4](../../../PROMPTS_AND_CONFIG.md)。

本ディレクトリ内の prompt 抽出対象は **5 件**(行範囲は実装で確定):

| ファイル | 行 | 抽出先 | LLM 呼び出し性質 |
|---|---|---|---|
| `lineage_decision.py` | L239– | `ari/prompts/orchestrator/lineage_decision.md` | 単純 system prompt |
| `root_idea_selector.py` | L57– | `ari/prompts/orchestrator/root_idea_selector.md` | 単純 system prompt |
| `bfts.py` | L215 | `ari/prompts/orchestrator/bfts_select.md` | f-string インライン(BFTS ノード選定) |
| `bfts.py` | L296 | `ari/prompts/orchestrator/bfts_expand_select.md` | f-string インライン(完了ノード expand 選定) |
| `bfts.py` | L481 | `ari/prompts/orchestrator/bfts_expand.md` | f-string インライン(BFTS ノード expand) |

#### 重要 — `bfts.py` の P2(決定論性)
`bfts.py` の 3 prompt は BFTS の選択ロジックに直結する。**抽出時に格別の検証**:
- 同一 seed・同一モック LLM・同一履歴 で抽出前後の BFTS ツリー形状が完全一致
- f-string 変数(`{node.id}` 等)を `str.format()` 互換に変換する際、変数名の意味を変えない
- `ari-core/tests/test_bfts_determinism.py` に prompt 抽出回帰テストを追加

#### 設定値の外部化(同 PC PR で同時に)
- `lineage_decision.py:266` の `or "gpt-4o-mini"` モデル既定値を `ari/configs/defaults.yaml` の `models.lineage_decision_default` キーへ
- `bfts.py` 内の温度(temperature)等のハードコード値があれば同様に外部化

## 3. 触らない範囲

以下は本ディレクトリ内であっても**本リファクタでは一切触らない**(prompt 抽出を除く):

- `node.py` — データモデルは安定
- `scheduler.py` — 67 行、変更不要
- `bfts.py` の最適化ロジック — prompt 抽出 (Step 3) のみ。獲得関数・ノード選定ロジックは触らない
- `lineage_decision.py` の判定ロジック — prompt 抽出 (Step 3) のみ
- `root_idea_selector.py` の選定ロジック — prompt 抽出 (Step 3) のみ
- `node_selection.py` — 302 行、ユーティリティとして安定

## 4. 挙動保証チェックリスト

PR-3E、PC4、PC5 および Phase 5 の merge 前に必ず実施:

- [ ] `pytest ari-core/tests/test_orchestrator*.py -q` がグリーン(既存テストすべてパス)
- [ ] **古いチェックポイントの読み込みテスト**: v0.5.x 形式のチェックポイント(test fixture を別途用意)を `ari resume` で開き、`node_report.json` が再構築されること
- [ ] **新しいチェックポイントの読み書き**: v0.7 で作成したチェックポイントの `node_report.json` のキー集合・値が分割前後で一致
- [ ] `from ari.orchestrator.node_report import build_node_report, reconstruct_report_from_legacy` が成功
- [ ] `ari migrate node-reports <legacy ckpt>` の出力(stdout + 生成ファイル)が分割前後で一致
- [ ] BFTS の決定論性: 同一 seed で `ari run --dry-run` 相当の実行を行い、ノード選択順序が分割前後で完全一致(モック LLM 使用)
- [ ] **Step 3 prompt 抽出**: 5 prompt すべてで `sha256(抽出前) == sha256(load("orchestrator/X"))` 成立
- [ ] **Step 3 format 後同一性**: 同じ変数で format した最終 prompt 文字列が抽出前後で一致
- [ ] **Step 3 BFTS 決定論回帰**: prompt 抽出前後で BFTS ツリー形状が完全一致(モック LLM、seed 固定)
- [ ] `lineage_decision.py:266` のモデル既定値が `defaults.yaml` 経由で同じ値を返す

## 5. 注意事項

- `node_report.py` 内のメトリクス集約ロジックは、複数の場所(builder.py 側と legacy 側)で似た計算をしている可能性がある。**意図せず統合してはならない**(legacy の数値解釈と現行の数値解釈が違う場合がある)。
- 分割時は legacy 側のコメント・docstring を必ず引き継ぐ。

---

## 実装完了後の削除

**PR-3E および Phase 5 PR がマージされ、§4 のチェックリストすべてに合格した時点で本ファイルを削除する。**

恒久化する内容(削除前に転記):
- §1 ファイル責務表 → `docs/architecture.md` の Orchestrator 章
- §2 Step 2 の shim 設計 → `docs/extension_guide.md` の「廃止予定 API」章
- §0 BFTS 決定論性の制約 → `docs/PHILOSOPHY.md` の P2 章
