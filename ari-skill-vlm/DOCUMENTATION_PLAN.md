# ari-skill-vlm ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md とコード docstring)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | 論文中の図表を VLM(Vision LLM)でレビューし、品質評価とフィードバックを返す |
| LOC | 785 |
| MCP ツール | mcp.json には未列挙(内部 API) |
| LLM 使用 | ○(VLM) |
| 決定論性 (P2) | × |
| 環境変数 | `VLM_MODEL`(既定 `openai/gpt-4o`) |
| ステート | なし |
| 既存 README | あり(要監査) |
| テスト | 2 ファイル |

## 2. 計画

### 2-1. README.md の更新

```markdown
# ari-skill-vlm

## 責務
論文中の **図 (Figure) と表 (Table) を VLM でレビュー**:
- 図の可読性・正確性のチェック
- 表のフォーマットチェック
- 改善フィードバックの生成

## 機能
現状 mcp.json には未列挙だが、内部 API を提供:
- `review_figure(image_path, context)` — 単一図のレビュー
- `review_table(table_text, context)` — 表のレビュー
- `review_paper_figures(paper_dir)` — 論文ディレクトリ内の全図表をバッチレビュー

## VLM プロンプト戦略
- 図: 画像を base64 エンコードし VLM に直接渡す
- 表: LaTeX/markdown 表をテキストとして VLM に渡す
- レビュー観点: 軸ラベル、単位、凡例、可読性、論文本文との整合性

## 環境変数
| 変数 | 用途 | 既定値 |
|---|---|---|
| `VLM_MODEL` | 利用する Vision LLM モデル | `openai/gpt-4o` |
| `OPENAI_API_KEY` | OpenAI 系モデル使用時 | (なし) |

## 依存
- `mcp >= 1.0`
- `litellm >= 1.0`(VLM 呼び出し)
- `pillow >= 10.0`(画像エンコード)

## 開発
\`\`\`bash
pytest tests/ -q
\`\`\`

## P2 例外
VLM 出力は非決定的(同じ画像でも応答が変動)。

## 関連
- [ari-skill-paper](../ari-skill-paper/README.md) — `review_compiled_paper` から本スキルを呼ぶ
- ari-core/ari/pipeline.py の `_format_vlm_feedback` — VLM フィードバックの整形(loop_back セマンティクス)
```

### 2-2. mcp.json / skill.yaml の整理
将来 MCP ツールを外部公開するか判断。

### 2-3. コード docstring
`src/server.py` のレビュー関数群に docstring を追加。

## 3. 受け入れ基準

- [ ] README.md に責務、内部 API、VLM プロンプト戦略、env var、関連スキル
- [ ] `pytest tests/ -q` がグリーン
- [ ] `docs/skills.md` の本スキル節と整合

---

## 実装完了後の削除

**README 更新 PR がマージされた時点で本ファイルを削除する。**
