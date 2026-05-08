# ari-skill-replicate ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md とルブリック生成仕様の文書化)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | PaperBench 互換の再現性ルブリックを論文から自動生成、品質監査 |
| LOC | 2764 |
| MCP ツール | `generate_rubric`, `audit_rubric` |
| LLM 使用 | ○ |
| 決定論性 (P2) | × |
| 環境変数 | `ARI_RUBRIC_GEN_TARGET_LEAVES`, `ARI_RUBRIC_GEN_TEMPERATURE`, `ARI_RUBRIC_GEN_TWO_STAGE`, `ARI_MODEL_RUBRIC_AUDIT`, `ARI_LLM_MODEL` |
| ステート | なし |
| 既存 README | あり |
| テスト | 7 ファイル |
| 重要 | v0.7.0 で導入。docs/skills.md には未掲載 |

## 2. 計画

### 2-1. README.md の更新

```markdown
# ari-skill-replicate

## 責務
**PaperBench 互換のルブリックを LLM で自動生成**。2 段階生成方式:
1. **Skeleton 段階**: ルブリックの骨格(主要軸とその下のサブ軸)を生成
2. **Subtree 段階**: 各サブツリーの leaf を並列で詳細化

加えて `audit_rubric` で生成済ルブリックの品質をチェック(曖昧・検証不能・重複の検出)。

## MCP ツール

### `generate_rubric`
**用途:** 論文テキストとメタ情報から PaperBench 互換ルブリックを生成。
**引数:**
- `paper_text` (string, required): 論文本文
- `target_leaves` (int, optional): 目標 leaf 数 (env: `ARI_RUBRIC_GEN_TARGET_LEAVES`)
- `temperature` (float, optional): LLM 温度 (env: `ARI_RUBRIC_GEN_TEMPERATURE`)
- `two_stage` (bool, optional): 2 段階生成を使うか (env: `ARI_RUBRIC_GEN_TWO_STAGE`)
**戻り値:** PaperBench 互換のルブリック JSON

### `audit_rubric`
**用途:** 既存ルブリックの leaf を以下の観点でフラグ:
- **曖昧**: 「適切に」「効率的に」など測定不能な表現
- **検証不能**: 必要な実装情報が手元にない
- **重複**: 他 leaf と意味的に同一

**引数:** `rubric_json`
**戻り値:** `{ "issues": [{ "leaf_id": "...", "category": "vague|unverifiable|duplicate", "rationale": "..." }] }`

## 環境変数
| 変数 | 用途 | 既定値 |
|---|---|---|
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | 目標 leaf 数 | (実装の既定値、要確認) |
| `ARI_RUBRIC_GEN_TEMPERATURE` | LLM 温度 | (実装の既定値) |
| `ARI_RUBRIC_GEN_TWO_STAGE` | 2 段階生成の使用 | true |
| `ARI_MODEL_RUBRIC_AUDIT` | 監査用 LLM | `ARI_LLM_MODEL` フォールバック |
| `ARI_LLM_MODEL` | 生成用 LLM | (なし、必須) |

## プロンプト
`src/prompts/skeleton.md` `src/prompts/subtree.md` `src/prompts/auditor.md` に LLM プロンプトテンプレート。
プロンプト変更は出力ルブリックを変えるため、慎重に扱うこと。

## スキーマ
`schemas/` 配下に PaperBench スキーマ定義。生成ルブリックは `jsonschema` で検証される。

## 開発
\`\`\`bash
pytest tests/test_generator.py -q   # ルブリック生成
pytest tests/test_auditor.py -q     # 監査
pytest tests/test_schema.py -q      # スキーマ検証
pytest tests/test_categories.py -q  # カテゴリ分類
pytest tests/test_manifest.py -q    # マニフェスト
pytest tests/test_server_env.py -q  # env var 取り扱い
\`\`\`

## ari-skill-paper-re との関係
本スキルが生成したルブリックは [ari-skill-paper-re](../ari-skill-paper-re/README.md) の
`grade_with_simplejudge` で採点に使用される。

## v0.7.0 で導入
リリースノート: CHANGELOG v0.7.0
```

### 2-2. docs/skills.md への追記
[../docs/DOCUMENTATION_PLAN.md §2-2](../docs/DOCUMENTATION_PLAN.md) の責務。本書から参照。

### 2-3. プロンプト変更時の規律
README に「プロンプト変更は挙動変化を伴うので独立 PR で評価ベンチを伴うべき」を明記。

## 3. 受け入れ基準

- [ ] README.md に 2 ツール、5 env var、PaperBench スキーマ、プロンプト所在
- [ ] `pytest tests/ -q` がグリーン(7 テスト)
- [ ] `docs/skills.md` に本スキルの独立節(マスター §2-2 が完了した結果)

---

## 実装完了後の削除

**README 更新 PR と `docs/skills.md` 追記 PR がマージされた時点で本ファイルを削除する。**
