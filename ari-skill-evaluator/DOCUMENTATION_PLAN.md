# ari-skill-evaluator ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md とコード docstring)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | 実験成果物からの LLM ガイド付きメトリクス抽出 |
| LOC | 291 |
| MCP ツール | `evaluate`, `make_artifact_extractor`(README 記載) |
| LLM 使用 | ○(P2 例外) |
| 決定論性 (P2) | × |
| 環境変数 | `ARI_MODEL_EVAL`, fallback `ARI_MODEL`, `ARI_LLM_MODEL` |
| ステート | なし |
| 既存 README | あり(品質要監査) |
| テスト | 2 ファイル |

## 2. 計画

### 2-1. README.md の更新

```markdown
# ari-skill-evaluator

## 責務
実験成果物(出力ファイル、ログ、メトリクス JSON)から LLM 誘導でメトリクスを抽出し、
`has_real_data` フラグ付きで返す。フェイクデータの自動検出も含む。

## MCP ツール

### `evaluate`
**用途:** ノードの成果物からメトリクスを抽出する。
**引数:**
- `node_dir` (string, required): ノード作業ディレクトリ
- `expected_metrics` (list[string], required): experiment.md で定義されたメトリクス名
**戻り値:** `{ "metrics": {...}, "has_real_data": bool, "extractor_code": "..." }`

### `make_artifact_extractor`
**用途:** ノードの成果物形式から、メトリクス抽出関数(Python コード)を LLM で生成する。
**引数:** ...
**戻り値:** ...

## 環境変数
| 変数 | 用途 | フォールバック順 |
|---|---|---|
| `ARI_MODEL_EVAL` | 評価専用 LLM モデル | (なし) |
| `ARI_MODEL` | ARI 共通の LLM モデル | `ARI_MODEL_EVAL` 未設定時 |
| `ARI_LLM_MODEL` | グローバル LLM モデル | 上記未設定時 |

## 依存
- `mcp >= 1.0`
- LLM プロバイダ: litellm 経由

## P2 例外
このスキルは LLM を使用するため、P2(決定論性)を満たさない。
詳細は ari-core/docs/PHILOSOPHY.md の「P2 例外」節参照。

## 開発
\`\`\`bash
pytest tests/ -q
\`\`\`
```

### 2-2. mcp.json の補完
ツール記述・引数スキーマを実装と一致させる。

### 2-3. コード docstring
評価ロジック・LLM 呼び出し関数・メトリクス抽出関数に docstring を付与。

## 3. 受け入れ基準

- [ ] README.md にメトリクス抽出フローの説明、env var 3 件、P2 例外の明記
- [ ] `pytest tests/ -q` がグリーン
- [ ] 親計画 docs/skills.md の本スキル節と内容が整合

---

## 実装完了後の削除

**README 更新 PR がマージされた時点で本ファイルを削除する。**
