# ari-skill-benchmark ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md とコード docstring)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | 統計分析・可視化・仮説検定 |
| LOC | 436 |
| MCP ツール | `analyze_results`, `plot`, `statistical_test` |
| LLM 使用 | × |
| 決定論性 (P2) | ○(完全に決定論的) |
| 環境変数 | なし |
| ステート | なし |
| 既存 README | あり(品質要監査) |
| テスト | 2 ファイル |

## 2. 計画

### 2-1. README.md の更新
既存 README を以下の節構成で書き直す(または不足を補う):

```markdown
# ari-skill-benchmark

## 責務
統計分析、可視化、仮説検定を MCP ツールとして提供。LLM 不使用、完全決定論的。

## MCP ツール

### `analyze_results`
**用途:** CSV/JSON/npy の結果ファイルから統計サマリ(平均、分散、分位数 etc.)を抽出。
**引数:**
- `result_path` (string, required): 結果ファイルのパス
- `metrics` (list[string], optional): 抽出するメトリクス名(未指定時は全件)
**戻り値:** `{ "metric_name": { "mean": float, "std": float, ... } }`
**副作用:** なし

### `plot`
... (同様)

### `statistical_test`
... (同様)

## 環境変数
なし。

## 依存
- `numpy >= 1.26`
- `scipy >= 1.11`
- `matplotlib >= 3.8`
- `pandas >= 2.0`

## 例
\`\`\`json
{ "tool": "analyze_results", "args": { "result_path": "results.json" } }
\`\`\`

## 開発
\`\`\`bash
pytest tests/ -q
\`\`\`

## 互換性
P2 (決定論性) を満たす。同一入力で同一出力を保証。
```

### 2-2. `mcp.json` のツール記述追加
各ツールに `description` フィールドを追記(既存に無ければ)。実装の引数・戻り値と完全一致させる。

### 2-3. コード docstring
`src/server.py` の各 MCP ツールハンドラ関数に docstring を付与:
```python
@mcp.tool
def analyze_results(result_path: str, metrics: list[str] | None = None) -> dict:
    """Compute statistical summary from a result file.

    See ari-skill-benchmark/README.md for full reference.
    """
```

## 3. 受け入れ基準

- [ ] README.md に「責務」「MCP ツール(各引数・戻り値)」「環境変数」「依存」「例」「互換性」の節が揃う
- [ ] `mcp.json` のツール記述が `src/server.py` の実装シグネチャと一致
- [ ] `pytest tests/ -q` がグリーン
- [ ] 親計画 [../docs/DOCUMENTATION_PLAN.md §3-2](../docs/DOCUMENTATION_PLAN.md) の `mcp_tools.md` から本スキルへリンクが張られる

---

## 実装完了後の削除

**README 更新と `mcp.json` 整備の PR がマージされた時点で本ファイルを削除する。**
