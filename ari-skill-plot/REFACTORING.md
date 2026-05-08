# ari-skill-plot リファクタリング計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../REFACTORING.md](../REFACTORING.md)

## 0. 挙動保証契約

[マスター計画 §2](../REFACTORING.md) の契約を厳守する。本スキルは**機能の変更なし**(import パスのみ変更):

- MCP ツール名 (`generate_figures` / `generate_figures_llm`) を変えない
- ツールの引数・戻り値スキーマを変えない
- 環境変数 `VLM_MODEL` `ARI_LLM_MODEL` `LLM_MODEL` `ARI_LLM_API_BASE` `OPENAI_API_KEY` の名前・既定値を変えない
- VLM キャプション生成の prompt を変えない
- 出力する図ファイル(matplotlib 出力)の形式を変えない
- LLM コスト計上のキー(`bootstrap_skill` 経由で記録)を変えない

## 1. 現状

このスキルは `ari-core` 内部 (`ari.cost_tracker`) を 1 箇所で参照している:

| ファイル | 行 | import 文 | 用途 |
|---|---|---|---|
| `src/server.py` | 28 | `from ari import cost_tracker` | LLM 呼び出しのコスト計上を ari 中央トラッカーへ送る |

これは「skill が core 内部に依存している」境界違反だが、**コスト計上は中央集約が必要なため、公開 API として正規化する**。

## 2. 計画 (Phase 4, PR-4)

[ari-core/REFACTORING.md §7](../ari-core/REFACTORING.md) で `ari/public/cost_tracker.py` が新設された後に実施する。

### 変更内容

`src/server.py:28` の import 文を変更:

```diff
- from ari import cost_tracker
+ from ari.public import cost_tracker
```

`cost_tracker.bootstrap_skill(...)` `cost_tracker.record(...)` などの呼び出し側はそのまま動く(`ari/public/cost_tracker.py` は薄い再エクスポート)。

### タイミング

- **前提**: PR-4(`ari/public/` 新設)が `ari-core` 側で先行マージされていること
- **依存**: なし
- **後続**: PR-4 と同 PR、または PR-4 直後の追従 PR で実施

## 3. 挙動保証チェックリスト

- [ ] `pytest ari-skill-plot/` 配下に既存テストがあれば全グリーン(現状 0 件)
- [ ] スキルサーバ起動: MCP プロトコルでのハンドシェイクが成功
- [ ] **コスト計上スモーク**: `generate_figures_llm` を 1 回呼び出し、`{checkpoint}/cost.json` または同等の出力に LLM コストレコードが記録される
- [ ] レコードのキー集合・形式が変更前と一致
- [ ] `mcp.json` の内容が変更前と完全一致
- [ ] パッケージの依存関係(requirements / pyproject)が変更されていない
- [ ] `generate_figures`(LLM 不使用)の出力 PNG が分割前後でバイト一致(matplotlib 決定論)

## 4. 将来の選択肢

本スキルは現状テストファイルが 0 件である。本リファクタの範囲外だが、`ari.public.cost_tracker` 移行と合わせて、最低 1 つのスモークテスト(モック LLM で `generate_figures` を呼ぶ)を追加することを別 PR で検討する価値がある。

---

## 実装完了後の削除

**PR-4 がマージされ、§3 のチェックリストすべてに合格した時点で本ファイルを削除する。**

恒久化する内容(削除前に転記):
- §1 の boundary 違反の事実 → `ari-core/tests/test_public_api_boundary.py` のコメント
- §2 の import 移行手順 → 不要(削除して問題ない)
