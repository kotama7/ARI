# ari-skill-coding ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md 新規作成 + docstring)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | コード書き出しと実行(オプションで Singularity コンテナ対応) |
| LOC | 893 |
| MCP ツール | mcp.json には未列挙(内部 CLI 経由) |
| LLM 使用 | × |
| 決定論性 (P2) | ○(任意のユーザコードを実行) |
| 環境変数 | `ARI_MAX_CHILD_PROCS` (既定 1024), `ARI_WORK_DIR` (既定 `/tmp/ari_work`), `ARI_CONTAINER_IMAGE`, `ARI_CONTAINER_MODE` |
| ステート | あり(`ARI_WORK_DIR` 配下) |
| 既存 README | **なし**(新規作成必要) |
| テスト | 2 ファイル |

## 2. 計画

### 2-1. README.md の新規作成
以下の節構成で:

```markdown
# ari-skill-coding

## 責務
ARI エージェントのコード書き出し・実行を MCP ツールとして提供。Singularity コンテナでのサンドボックス実行をサポート。

## MCP ツール
(現状 mcp.json は空、内部 API 経由でコード実行を提供)
将来的に列挙する場合は本書で追記。

## 環境変数
| 変数 | 用途 | 既定値 |
|---|---|---|
| `ARI_MAX_CHILD_PROCS` | 並行実行する子プロセスの上限 | 1024 |
| `ARI_WORK_DIR` | コード書き出し先のディレクトリ | `/tmp/ari_work` |
| `ARI_CONTAINER_IMAGE` | Singularity イメージ | (未設定時はホスト直接実行)|
| `ARI_CONTAINER_MODE` | コンテナ実行モード(`exec`/`shell`)| `exec` |

## 依存
- `mcp >= 1.0`
- `pydantic >= 2.0`

## アーキテクチャ
- ホスト直接実行 vs コンテナ実行の切替は `ARI_CONTAINER_IMAGE` の有無で判定
- コンテナラップは ari-core の `ari.public.container` API を使用(リファクタ計画 Phase 4 完了後)
- 詳細は ari-core/ari/container.py 参照

## 例
\`\`\`bash
ARI_WORK_DIR=/tmp/ari ARI_CONTAINER_IMAGE=python:3.11.sif python -m ari_skill_coding.server
\`\`\`

## 開発
\`\`\`bash
pytest tests/ -q
\`\`\`

## ari-core との境界
本スキルはテストで `ari.container` を import している([REFACTORING.md §1](REFACTORING.md))。
リファクタ計画 Phase 4 で `ari.public.container` への移行が予定されている。
```

### 2-2. コード docstring
`src/server.py` のトップレベルに モジュール docstring、主要関数(コード書き出し・実行・サンドボックス処理)に docstring を付与。

### 2-3. mcp.json の補完
将来 MCP ツールを露出させる場合、本 README と mcp.json を同時更新する規律。

## 3. リファクタリング計画との連動

[REFACTORING.md](REFACTORING.md) Phase 4 で `ari.container` → `ari.public.container` 移行が行われる。本ドキュメンテーション計画の §2-1 の「ari-core との境界」節は、Phase 4 完了後に「テスト import が `ari.public.container` に移行済み」と更新する。

## 4. 受け入れ基準

- [ ] README.md が新規作成されている
- [ ] 環境変数 4 件が `src/server.py` の実装と一致
- [ ] `pytest tests/ -q` がグリーン
- [ ] 親計画 [../docs/DOCUMENTATION_PLAN.md §3-3](../docs/DOCUMENTATION_PLAN.md) の `environment_variables.md` から本スキルの env var が参照される

---

## 実装完了後の削除

**README 新規作成 PR がマージされた時点で本ファイルを削除する。**
