# ari-skill-transform ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md **新規作成** + コード docstring)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | 実験ツリーを巡回し、方法論セットアップと主要発見を LLM で抽出 |
| LOC | 2872 |
| MCP ツール | mcp.json/skill.yaml に未列挙(内部 API 経由) |
| LLM 使用 | ○ |
| 決定論性 (P2) | × |
| 環境変数 | `LLM_MODEL`(既定 `gpt-4o-mini`) |
| ステート | なし |
| 既存 README | **なし**(新規作成必要) |
| テスト | 2 ファイル |

## 2. 計画

### 2-1. README.md の新規作成

```markdown
# ari-skill-transform

## 責務
ARI の実験ツリー(BFTS の全ノード)を巡回し、以下を LLM で抽出:
- **方法論セットアップ**: 各ノードの仮説・実装・パラメータの構造化要約
- **主要発見**: ツリー全体から得られた知見の合成

paper 生成パイプライン(ari-skill-paper)の前段で使われ、論文の「Methods」「Results」セクションの素材を準備する。

## MCP ツール
現状 mcp.json には未列挙(内部 API 経由)。
将来的に外部公開する場合は本書で追記する。

実装上の主要関数(`src/server.py`):
- `extract_context_from_tree(tree_path)` — ツリー全体から方法論コンテキスト抽出
- `extract_findings_from_tree(tree_path)` — 主要発見の合成

## 環境変数
| 変数 | 用途 | 既定値 |
|---|---|---|
| `LLM_MODEL` | 抽出用 LLM | `gpt-4o-mini` |

(`ARI_LLM_MODEL` `ARI_LLM_API_BASE` 等の他のスキル共通フォールバックを尊重するか要確認)

## 依存
- 標準ライブラリ中心(具体的依存は `pyproject.toml` 参照)

## ノード巡回戦略
- BFTS 木を root → leaves で深さ優先または幅優先で走査
- 各ノードの `node_report.json` `experiment.md` を読み込み
- LLM コンテキストウィンドウに収まるようチャンク化

## 開発
\`\`\`bash
pytest tests/ -q
\`\`\`

## P2 例外
LLM を使用するため決定論的でない。

## 関連
- [ari-skill-paper](../ari-skill-paper/README.md) — 本スキルの抽出結果を消費
- ari-core/ari/orchestrator/node_report.py — ノードレポート形式
```

### 2-2. コード docstring
`src/server.py` 全体のモジュール docstring を追加。各内部関数(ツリー巡回、コンテキスト抽出、発見合成)に docstring を付与。

### 2-3. mcp.json / skill.yaml の整理
将来 MCP ツールを外部公開するか判断する。判断結果を README に明記。

## 3. 受け入れ基準

- [ ] README.md が新規作成されている
- [ ] 責務、内部 API、env var、巡回戦略、関連スキル
- [ ] `pytest tests/ -q` がグリーン

---

## 実装完了後の削除

**README 新規作成 PR がマージされた時点で本ファイルを削除する。**
