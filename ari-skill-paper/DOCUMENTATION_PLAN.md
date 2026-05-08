# ari-skill-paper ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md、ルブリック仕様書)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | LaTeX 論文の各セクションを LLM 生成 → ルブリックレビュー → 改稿のループで作成 |
| LOC | 3870(`server.py` + `rubric.py` + `review_engine.py`) |
| MCP ツール | 10 個(下表) |
| LLM 使用 | ○ |
| 決定論性 (P2) | × |
| 環境変数 | `ARI_RUBRIC_DIR`, `ARI_STRICT_DYNAMIC`, `ARI_CHECKPOINT_DIR`(fewshot cache 用), `ARI_RUBRIC`, `ARI_LLM_MODEL` |
| ステート | あり(`.ari_fewshot_cache`) |
| 既存 README | あり(要監査) |
| テスト | 4 ファイル(server / rubric / code_availability / conftest) |

## 2. 計画

### 2-1. README.md の更新

```markdown
# ari-skill-paper

## 責務
LaTeX 論文の **iterative 生成**:
1. ルブリック(評価基準)を LLM に提示
2. セクション草稿を生成
3. ルブリックでレビュー
4. フィードバックで改稿
5. 全セクション完成後 PDF コンパイル + 総合レビュー

## MCP ツール(10 個)

| ツール | 用途 |
|---|---|
| `list_venues` | 利用可能な投稿先テンプレート(ACM, NeurIPS, SC, ICPP, arXiv)を列挙 |
| `get_template` | 指定 venue の LaTeX テンプレートを取得 |
| `generate_section` | 1 セクションを LLM 生成 |
| `compile_paper` | pdflatex でコンパイル |
| `check_format` | LaTeX 形式の検証 |
| `review_section` | ルブリックでセクションをレビュー |
| `revise_section` | レビュー結果でセクションを改稿 |
| `write_paper_iterative` | 上記ループの一括実行 |
| `review_compiled_paper` | 完成 PDF の総合レビュー |
| `list_rubrics` | 利用可能なルブリック一覧 |

## ルブリックシステム(v0.6 で導入)
- ルブリックは YAML 形式で `ARI_RUBRIC_DIR` 配下に配置
- venue・分野ごとに複数のルブリックを切替可能
- `ARI_STRICT_DYNAMIC=true` で動的軸生成を強制
- 詳細は [docs/architecture.md](../docs/architecture.md) の rubric 節

## 環境変数
| 変数 | 用途 |
|---|---|
| `ARI_RUBRIC_DIR` | ルブリック YAML の格納ディレクトリ |
| `ARI_RUBRIC` | 既定ルブリック名 |
| `ARI_STRICT_DYNAMIC` | 動的軸生成の強制(true/false) |
| `ARI_CHECKPOINT_DIR` | fewshot cache (`.ari_fewshot_cache`) の格納先 |
| `ARI_LLM_MODEL` | 論文生成用 LLM モデル |

## テンプレート
`templates/` 配下:
- `acm.tex`
- `neurips.tex`
- `sc.tex`
- `icpp.tex`
- `arxiv.tex`

## 開発
\`\`\`bash
pytest tests/test_server.py -q             # MCP API
pytest tests/test_rubric.py -q             # ルブリック評価
pytest tests/test_code_availability.py -q  # コード可用性チェック
\`\`\`

## P2 例外
LLM を多用するため決定論的でない。同一入力でも生成結果は異なる。
```

### 2-2. ルブリック仕様
`docs/reference/rubric_format.md`(新規、または `docs/skills.md` の本スキル節に追記)で:
- ルブリック YAML のスキーマ
- カスタムルブリックの書き方
- ルブリック適用時の評価フロー

### 2-3. settings.json 連携
本スキルは `settings.json` に独自セクションを持つ(マスター計画 §1-3 参照)。
そのフィールドを README または `docs/configuration.md` に明記。

## 3. 受け入れ基準

- [ ] README.md に 10 ツール、5 env var、5 venue テンプレート、ルブリックシステムの説明
- [ ] `pytest tests/ -q` がグリーン(4 テスト)
- [ ] `docs/skills.md` の本スキル節に新スキル記載と整合

---

## 実装完了後の削除

**README 更新 PR がマージされた時点で本ファイルを削除する。**
