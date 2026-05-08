# ari-skill-web ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md とコード docstring)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | Web 検索(DuckDuckGo)、URL 取得、arXiv / Semantic Scholar 検索、参考文献の反復収集 |
| LOC | 1219 |
| MCP ツール | `web_search`, `fetch_url`, `search_arxiv`, `search_semantic_scholar`, `collect_references_iterative` |
| LLM 使用 | ×(コアツールには含まれない) |
| 決定論性 (P2) | △(Web 検索結果のインデックスが時間で変動) |
| 環境変数 | `ARI_RETRIEVAL_BACKEND`(既定 `semantic_scholar`), `ARI_ALPHAXIV_ENDPOINT`, `ARI_LLM_MODEL`, `LLM_MODEL`, `ARI_LLM_API_BASE` |
| ステート | なし |
| 既存 README | あり |
| テスト | 2 ファイル(server / collect_references) |

## 2. 計画

### 2-1. README.md の更新

```markdown
# ari-skill-web

## 責務
Web 上の情報源(検索エンジン、arXiv、Semantic Scholar、任意 URL)から研究関連情報を取得する MCP スキル。

## MCP ツール

### `web_search`
**用途:** DuckDuckGo で検索(API キー不要)。
**引数:** `query` (string), `max_results` (int, default 10)
**戻り値:** `[{ "title", "url", "snippet" }]`

### `fetch_url`
**用途:** URL を取得し、可読テキストを抽出。
**引数:** `url` (string)
**戻り値:** `{ "url", "title", "text", "error": null | "..." }`

### `search_arxiv`
**用途:** arXiv の検索 API を直接叩く。
**引数:** `query` (string), `max_results` (int, default 50)

### `search_semantic_scholar`
**用途:** Semantic Scholar の検索 API。
**引数:** `query` (string), `max_results` (int, default 50)

### `collect_references_iterative`
**用途:** 起点論文から反復的に参照文献グラフを辿って収集。
**引数:**
- `seed_paper` (string): arXiv ID または DOI
- `depth` (int, default 2)
- `max_papers` (int, default 100)
**戻り値:** 文献リスト(タイトル、著者、要約、引用関係)

## 環境変数
| 変数 | 用途 | 既定値 |
|---|---|---|
| `ARI_RETRIEVAL_BACKEND` | デフォルト検索バックエンド (`semantic_scholar` / `arxiv` / `alphaxiv`) | `semantic_scholar` |
| `ARI_ALPHAXIV_ENDPOINT` | alphaxiv バックエンド使用時のエンドポイント | (なし) |
| `ARI_LLM_MODEL` | LLM ベースの再ランキング用(現状未使用、将来用) | (なし) |
| `LLM_MODEL` | スキル間共通フォールバック | (なし) |
| `ARI_LLM_API_BASE` | LLM API ベース URL | LiteLLM 既定 |

## 依存
- `mcp >= 1.0`
- `requests >= 2.28`
- バックエンド固有: `arxiv` `semanticscholar` 等

## 注意: Web 検索の決定論性
- DuckDuckGo / arXiv / Semantic Scholar の結果はインデックスが時間で変動する
- 同一クエリでも結果が変わり得るため、再現性が必要な実験では取得結果をチェックポイントに保存すること
- ari-core 側で `clone` メカニズムにより取得結果バンドルを再利用可能(P5: 再現性原則)

## 開発
\`\`\`bash
pytest tests/test_server.py -q              # 各検索バックエンド
pytest tests/test_collect_references.py -q  # 反復収集
\`\`\`
```

### 2-2. mcp.json と実装の同期
ツール記述を `src/server.py` の実装と一致させる。

### 2-3. P5 (再現性) との整合
README に「Web 検索結果は時間で変動するため、再現性のためにチェックポイント保存が必須」を明記。

## 3. 受け入れ基準

- [ ] README.md に 5 ツール、5 env var、検索バックエンド切替、決定論性についての注意
- [ ] `pytest tests/ -q` がグリーン
- [ ] `docs/skills.md` の本スキル節と整合

---

## 実装完了後の削除

**README 更新 PR がマージされた時点で本ファイルを削除する。**
