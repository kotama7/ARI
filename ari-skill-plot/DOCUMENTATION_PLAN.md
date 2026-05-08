# ari-skill-plot ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md **新規作成** + コード docstring)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | データから決定論的に図を生成、または LLM 書き出しの matplotlib コードで生成。VLM キャプション付与もサポート。 |
| LOC | 788 |
| MCP ツール | `generate_figures`(決定論)、`generate_figures_llm`(LLM、P2 例外) |
| LLM 使用 | △(`generate_figures_llm` のみ) |
| 決定論性 (P2) | △ |
| 環境変数 | `VLM_MODEL`(既定 `openai/gpt-4o`), `ARI_LLM_MODEL`, `LLM_MODEL`, `ARI_LLM_API_BASE`, `OPENAI_API_KEY` |
| ステート | なし |
| 既存 README | **なし**(新規作成必要) |
| テスト | **0 ファイル**(欠落) |
| 重要 | `ari.cost_tracker` を `src/server.py:28` で import している([REFACTORING.md](REFACTORING.md))|

## 2. 計画

### 2-1. README.md の新規作成

```markdown
# ari-skill-plot

## 責務
科学論文用の図を生成する MCP スキル。2 つのモード:
- **決定論モード** (`generate_figures`): データと指定スキーマから matplotlib で直接生成。完全決定論的。
- **LLM モード** (`generate_figures_llm`): データの形状を LLM が解析し、matplotlib コードを生成・実行。P2 例外。

VLM(Vision LLM)による図のキャプション自動生成もオプションでサポート。

## MCP ツール

### `generate_figures`(決定論的)
**用途:** データと出力仕様から決定論的に図を生成。
**引数:**
- `data_path` (string, required): CSV/JSON/npy パス
- `figure_spec` (dict, required): 図の種類・軸・タイトル等
- `output_path` (string, required): PNG/PDF 出力先
**戻り値:** `{ "figure_path": "...", "size_bytes": ... }`

### `generate_figures_llm`(P2 例外)
**用途:** LLM がデータ形状を見て matplotlib コードを書き、実行して図を生成。
**引数:**
- `data_path` (string, required)
- `intent` (string, required): 何を可視化したいか自然言語で
- `output_path` (string, required)
**戻り値:** `{ "figure_path", "matplotlib_code", "vlm_caption": "..." | null }`

## 環境変数
| 変数 | 用途 | 既定値 |
|---|---|---|
| `VLM_MODEL` | キャプション生成用 VLM モデル | `openai/gpt-4o` |
| `ARI_LLM_MODEL` | 図コード生成用 LLM | (なし) |
| `LLM_MODEL` | スキル間共通フォールバック | `ARI_LLM_MODEL` 経由 |
| `ARI_LLM_API_BASE` | LLM API ベース URL | LiteLLM 既定 |
| `OPENAI_API_KEY` | OpenAI 系モデル使用時のキー | (なし) |

## 依存
- `mcp >= 1.0`
- `litellm >= 1.0`
- `matplotlib`(間接依存)

## ari-core との境界
`from ari import cost_tracker`(`src/server.py:28`)を経由して LLM コスト計上を ari 中央トラッカーへ送る。
リファクタ計画 Phase 4 で `ari.public.cost_tracker` への移行が予定されている([REFACTORING.md](REFACTORING.md))。

## テストギャップ
現状 0 件。最低限のスモーク(モック LLM で `generate_figures` を呼ぶ)を将来追加すべき。

## 開発
\`\`\`bash
# テストはまだ存在しない。将来追加予定。
python -m ari_skill_plot.server
\`\`\`

## P2 例外
`generate_figures_llm` は LLM を使用するため決定論的でない。
`generate_figures` は決定論的(matplotlib のみ)で、同一入力で同一の PNG を出力する。
```

### 2-2. コード docstring
`src/server.py` 全体のモジュール docstring と各 MCP ツール関数の docstring を追加。

### 2-3. リファクタリング計画との連動
[REFACTORING.md](REFACTORING.md) Phase 4 完了後、README の「ari-core との境界」節を更新。

## 3. 受け入れ基準

- [ ] README.md が新規作成されている
- [ ] 2 ツール、5 env var、ari-core との境界、テストギャップ告知が含まれる
- [ ] 親計画 [../docs/DOCUMENTATION_PLAN.md §3-3](../docs/DOCUMENTATION_PLAN.md) の `environment_variables.md` から本スキルの env var が参照される

---

## 実装完了後の削除

**README 新規作成 PR がマージされた時点で本ファイルを削除する。**
