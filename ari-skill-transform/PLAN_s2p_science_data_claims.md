# 詳細実装計画: ari-skill-transform — science_data.json への Research Contract（claims）拡張

対象: Story2Proposal 統合 マスター計画の **Phase A ＋ Phase A2(生成側)**。
親計画: `../Story2Proposal計画書.md`（統合マスター計画）。本書は **ari-skill-transform 担当分**。
ステータス: コード実装＋単体テスト完了（`tests/test_claims.py`、恒久仕様は `REQUIREMENTS.md` に反映済み）。§5 実機(compute node)検証が未実施のため、削除要件未充足 → 本ファイルは削除しない。

> **削除要件（必読）**: 本ファイルは下記「受け入れ基準」を全て満たし、恒久仕様を
> `ari-skill-transform/REQUIREMENTS.md`（無ければ新規作成）に反映（fold）した時点で、完了を記録する同じ PR で削除する。
> 部分完了では削除しない。途中放棄する場合も放棄理由を REQUIREMENTS.md に1行残してから削除する。
> （リポジトリ慣習:「完了記録と同 PR で要件/計画ファイル削除」に準拠。`../PLAN_memory_inheritance.md` と同方式。）

---

## 0. このタスクの責務

`science_data.json`（`nodes_to_science_data`, `ari-skill-transform/src/server.py`）を **Research Contract substrate** 化する。
EAR は対象外（公開バンドルのまま）。writer 側の % CLAIM 注釈・後処理検証は `../ari-skill-paper/PLAN_s2p_claim_annotation.md` 担当。

## 1. 変更/新規ファイル

```text
ari-skill-transform/src/server.py        # nodes_to_science_data に claims 生成を追加
ari-skill-transform/（claims JSON Schema） # dataclass + JSON Schema（Pydantic 不可）
ari-skill-transform/tests/               # claims[] 生成・後方互換テスト
```

## 2. 実装内容（マスター §Phase A, §Phase A2-生成側）

- science_data.json に top-level `claims[]` / `numeric_assertions[]` を追加（既存 consumer は `.get()` で安全）。
- 各 claim:
  - `supported_by.nodes` に **実 node_id を直書き**（configuration は node_id を剥がすため依拠しない。生成器は `good_nodes` の `nid` を保持している）。
  - result は `(node_id, metric_path)`。`operands` も `node_id + metric_path`。
  - `figures` は draft 時 **空**（generate_figures 後に paper 側で late-bind）。
  - `numeric_assertions`: value/unit/formula/operands/tolerance、`aggregation` は記録のみ。
- candidate claim 生成は **LLM draft 工程**。接地先は **決定論部分**（`configurations.metrics` / `results.json`）のみ。LLM 生成の `experiment_context` / `implementation_overview` には依拠しない。
- スキーマは dataclass + JSON Schema（`node_report.schema.json` 隣）。

## 3. 依存

```text
前段: なし（統合実装の最初）
後段: ari-skill-paper（注釈）, ari-core（hard gate）が本タスクの claims[] を前提とする
```

## 4. 受け入れ基準（完了条件）

```text
- science_data.json に claims[] / numeric_assertions[] を保存・読込できる。
- claim が実 node_id と (node_id, metric_path) を保持し、figures は空で開始する。
- status を draft | supported | unsupported | rejected で管理できる。
- 既存 consumer（write_paper / generate_figures / viz / orchestrator）が壊れない。
- 数値 operand 参照は決定論的（同一 tree.json/results.json から再現）。claim 文の LLM 揺れは許容。
```

## 5. 検証（実機）

```text
- compute node で transform_data を実走し、claims[] 付き science_data.json を生成して確認する。
- fake/login node 不可。出力は workspace/checkpoints/<ts>_<slug>/ に揃える。
- テスト緑だけを完了条件にしない。
```
