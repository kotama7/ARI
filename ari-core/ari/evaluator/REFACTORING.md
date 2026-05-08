# ari/evaluator/ リファクタリング計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../../../REFACTORING.md](../../../REFACTORING.md)
> 関連: [../../../PROMPTS_AND_CONFIG.md](../../../PROMPTS_AND_CONFIG.md)

## 0. 挙動保証契約

[マスター計画 §2](../../../REFACTORING.md) の契約を厳守する。本ディレクトリは LLM ベース評価を担うため:

- `LLMEvaluator.evaluate()` の公開シグネチャを変えない
- メトリクス抽出の出力 JSON スキーマ(`{ "metrics": ..., "has_real_data": bool, ... }`)を変えない
- 動的軸生成の出力(`AxisDef` dataclass フィールド)を変えない
- prompt 抽出時は **byte-for-byte の同一性** を保つ([PROMPTS_AND_CONFIG.md §4](../../../PROMPTS_AND_CONFIG.md))
- legacy 5-axis フォールバック(`llm_evaluator.py:586–589`)の動作を変えない

## 1. 範囲を「変更不要」から「変更スコープ」へ昇格した理由

[ari-core/REFACTORING.md §1](../../REFACTORING.md) では本ディレクトリは「変更不要」だった。
しかしマスター計画 §11-4(prompt/config 外部化)の適用により、以下のため変更スコープに昇格:

- `llm_evaluator.py:165` インライン system prompt
- `llm_evaluator.py:324` `_build_system_prompt()` メソッド
- `llm_evaluator.py:586–589` legacy 5-axis フォールバック
- `dynamic_axes.py` 内の rubric→axes / plan→axes 変換にも LLM prompt が含まれる可能性(要確認)

## 2. 現状

| ファイル | 行数 | 責務 |
|---|---|---|
| `llm_evaluator.py` | 638 | LLM 評価器(メトリクス抽出 + ピアレビュー) |
| `dynamic_axes.py` | 516 | 動的軸生成(rubric→axes / plan→axes / vocab 解決) |

## 3. 計画

### Step 1: prompt 抽出 (Phase 3, PC6)

#### 3-1. `llm_evaluator.py` の prompt 外部化

| 抽出元 | 行 | 抽出先 |
|---|---|---|
| インライン文字列 | L165 | `ari/prompts/evaluator/extract_metrics.md` |
| `_build_system_prompt()` の組み立てロジック | L324〜 | `ari/prompts/evaluator/peer_review.md`(テンプレート変数で組み立てを表現) |

`_build_system_prompt()` のような「動的に組み立てるメソッド」は、できる限り **テンプレート変数** に置き換える。組み立てロジックがどうしても残る場合は、**抽出した部品 prompt 群をメソッド内で `.format()` してつなぐ** 形にして、構成要素を外部ファイル化する。

#### 3-2. `dynamic_axes.py` の prompt 外部化(あれば)

`dynamic_axes.py` 内の prompt(`rubric_to_axes` `plan_to_axes` 等の LLM 呼び出し箇所)を確認し、あれば `ari/prompts/evaluator/dynamic_axes_*.md` へ。

### Step 2: Evaluator Protocol 化 (Phase 3, PC6 と同 PR または直後)

[REFACTORING.md §11-3](../../../REFACTORING.md) の抽象化原則の適用。

#### 2-1. Evaluator Protocol の定義

```python
# ari/protocols/evaluator.py
from typing import Protocol
from ari.evaluator.llm_evaluator import MetricSpec  # 既存 dataclass

class Evaluator(Protocol):
    """Extracts metrics from a node's artifacts.

    Implementations may use LLM, regex, or any other strategy.
    """
    def evaluate(
        self,
        node_dir: Path,
        metrics_spec: list[MetricSpec],
    ) -> dict:
        """Return { "metrics": {...}, "has_real_data": bool, ... }."""
        ...
```

#### 2-2. LLMEvaluator を Protocol 実装として位置づける
- `LLMEvaluator` の名前・公開メソッドは変えない
- `ari/protocols/evaluator.py` の `Evaluator` Protocol を満たすことを **型チェック**(`isinstance` ではなく `cast` または `assert_type`)で保証
- 利用側(`agent/loop.py` 等)は `Evaluator` 型として受け取る(具象クラス依存を切る)

### Step 3: legacy 5-axis フォールバックの隔離 (Phase 5 と連動)

`llm_evaluator.py:586–589` の legacy フォールバックは、リファクタ計画 [Phase 5 移行債務隔離](../../REFACTORING.md) で `ari/migrations/v05_to_v07/legacy_axes.py` へ移動する。

移動方針:
- `llm_evaluator.py` 側には migrations モジュールを呼ぶ薄い shim を残す
- 関数シグネチャ・戻り値を変えない
- v0.8 リリースノートで「v1.0 で削除予定」と予告

## 4. 触らない範囲

- `LLMEvaluator` `MetricSpec` `AxisDef` の dataclass フィールド
- `evaluate()` `rubric_to_axes()` `plan_to_axes()` `axes_to_weights()` の公開シグネチャ
- ファイル分割は **行わない**(638 + 516 行は分割閾値以下、責務も明確)

## 5. 挙動保証チェックリスト

PR-PC6 の merge 前に必ず実施:

- [ ] **prompt sha256 一致**: `sha256(抽出前 prompt) == sha256(open("ari/prompts/evaluator/*.md").read())` が全 prompt で成立
- [ ] **テンプレート展開後の同一性**: `_build_system_prompt()` が抽出前後で同じ最終 prompt 文字列を返す(差分テスト)
- [ ] `pytest ari-core/tests/` がグリーン(evaluator 関連の既存テストすべてパス)
- [ ] **メトリクス抽出回帰**: 既存チェックポイントの実 node に対して `LLMEvaluator.evaluate()` を呼び、出力 JSON のキー集合・型が抽出前後で一致(モック LLM 使用、決定的)
- [ ] **legacy フォールバック**: legacy 形式の入力で `evaluate()` が同じ legacy 出力を返す
- [ ] `Evaluator` Protocol を実装していることが mypy / pyright で検証
- [ ] `from ari.evaluator import LLMEvaluator, MetricSpec, AxisDef` が動作

## 6. 注意事項

- **`_build_system_prompt()` の挙動を変えない**: prompt を外部化しても、最終的に LLM に渡る system prompt 文字列が完全に同一であること
- **temperature / top_p などの LLM 呼び出しパラメータも変えない**: prompt 抽出は文字列のみが対象
- **prompt 内のテンプレート変数を新規追加しない**: 既存変数(`{rubric}` `{node_outputs}` 等)のみを使う

---

## 実装完了後の削除

**PR-PC6 がマージされ、§5 のチェックリストすべてに合格した時点で本ファイルを削除する。** Phase 5(legacy 隔離)の追従 PR まで含む場合はそれも待つ。

恒久化する内容(削除前に転記):
- §2 現状の責務表 → `docs/architecture.md` の Evaluator 章
- §3 Step 2 Evaluator Protocol → 実コード(`ari/protocols/evaluator.py`)が代替
