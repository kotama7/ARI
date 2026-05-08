# ari-skill-idea ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md と vendored VirSci の文書化)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | arXiv / Semantic Scholar からの文献調査と LLM ベースのアイデア生成 |
| LOC | 4226(うち vendor/virsci/ 含む) |
| MCP ツール | `survey`(決定論)、`generate_ideas`(LLM、P2 例外) |
| LLM 使用 | △(`generate_ideas` のみ) |
| 決定論性 (P2) | △ |
| 環境変数 | `ARI_MODEL_IDEA`, `ARI_LLM_MODEL`, `LLM_MODEL`, `ARI_LLM_API_BASE` |
| ステート | なし |
| 既存 README | あり(要監査) |
| テスト | 2 ファイル |

## 2. 計画

### 2-1. README.md の更新

```markdown
# ari-skill-idea

## 責務
- `survey`: arXiv + Semantic Scholar API で文献を取得(完全決定論)
- `generate_ideas`: LLM で研究アイデア候補を生成(P2 例外、pre-BFTS 段階のみ)

## MCP ツール

### `survey`(決定論的)
**用途:** クエリ・著者・年範囲で文献を検索。
**引数:**
- `query` (string, required)
- `max_results` (int, default 50)
- `years` (tuple[int, int], optional)
- `backend` (string, optional): `arxiv` | `semantic_scholar` | `both`
**戻り値:** `[{ "title", "authors", "abstract", "doi", "url", ... }]`

### `generate_ideas`(P2 例外)
**用途:** survey 結果と既存実験コンテキストから新規アイデア候補を生成。
**引数:**
- `context` (string, required): 既存の研究文脈
- `papers` (list, required): survey() の結果
- `n_ideas` (int, default 5)
**戻り値:** `[{ "idea": "...", "rationale": "...", "novelty_score": float }]`

## 環境変数
| 変数 | 用途 | フォールバック順 |
|---|---|---|
| `ARI_MODEL_IDEA` | アイデア生成専用 LLM | (なし) |
| `ARI_LLM_MODEL` | グローバル LLM | `ARI_MODEL_IDEA` 未設定時 |
| `LLM_MODEL` | スキル間共通フォールバック | 上記未設定時 |
| `ARI_LLM_API_BASE` | LLM API のベース URL | LiteLLM 既定 |

## VirSci 統合
本スキルは `vendor/virsci/` ディレクトリに VirSci(2-hop Semantic Scholar 引用グラフ)を内包している。
詳細は VirSci の元レポジトリと CHANGELOG v0.4.x の VirSci 統合節を参照。

## 開発
\`\`\`bash
pytest tests/test_server.py -q       # スキル本体
pytest tests/test_virsci.py -q       # VirSci 統合
\`\`\`

## P2 例外
`generate_ideas` は LLM を使用するため決定論的でない。
ただし pre-BFTS 段階のみで使われるため、BFTS ツリー形成後の決定論性は保たれる。
```

### 2-2. mcp.json と実装の同期

### 2-3. VirSci サブシステムの最小ドキュメント
`vendor/virsci/` にローカル README が無ければ、`ari-skill-idea/README.md` 内で「VirSci の責務とライセンス」を明記。

## 3. 受け入れ基準

- [ ] README.md に 2 ツール、4 env var、P2 例外、VirSci 統合説明
- [ ] `pytest tests/ -q` がグリーン
- [ ] `docs/skills.md` の本スキル節と内容整合

---

## 実装完了後の削除

**README 更新 PR がマージされた時点で本ファイルを削除する。**
