# ari-skill-memory ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md、Letta バックエンドの運用書)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | BFTS 木に対するノードスコープのメモリ提供(祖先専用、兄弟非可視) |
| LOC | 1957 |
| MCP ツール | `add_memory`, `search_memory`, `get_node_memory`, `clear_node_memory` |
| LLM 使用 | × |
| 決定論性 (P2) | △(Letta バックエンドの動作に依存) |
| 環境変数 | `ARI_CURRENT_NODE_ID`(自己設定) |
| ステート | あり(Letta backend / file_client / local_client から選択) |
| 既存 README | あり(品質要監査) |
| テスト | 15 ファイル(包括的) |

## 2. 計画

### 2-1. README.md の更新

```markdown
# ari-skill-memory

## 責務
BFTS の各ノードに対してスコープ付きメモリを提供する。重要な性質:
- **祖先スコープ**: ノード N のメモリ検索は N とその祖先のメモリのみを参照
- **兄弟非可視性**: BFTS の並列ブランチ間でメモリが汚染されない
- **CoW (Copy-on-Write) セマンティクス**: 派生ノードでの書き込みが親に伝播しない

## MCP ツール

### `add_memory`
**引数:** `text` (string), `tags` (list[string], optional), `metadata` (dict, optional)
**戻り値:** `{ "memory_id": "...", "node_id": "..." }`

### `search_memory`
**引数:** `query` (string), `top_k` (int, default 5)
**戻り値:** `[{ "text", "score", "tags", "node_id", ... }]`
**スコープ:** 現ノードと祖先のみ

### `get_node_memory`
**引数:** (なし、現ノード自動)
**戻り値:** ノードの全メモリ

### `clear_node_memory`
**引数:** (なし)
**副作用:** 現ノードのメモリのみクリア(祖先には影響なし)

## バックエンド選択
| バックエンド | 用途 | 決定論性 |
|---|---|---|
| `letta` (v0.6 既定) | プロダクション、ベクトル検索 | × |
| `file_client` (v0.5 互換) | レガシー、JSONL ベース | ○ |
| `local_client` | テスト用、in-memory | ○ |

切替: `settings.json` の `memory.backend` フィールド、または `ARI_MEMORY_BACKEND` env var。

## 環境変数
| 変数 | 用途 |
|---|---|
| `ARI_CURRENT_NODE_ID` | 現ノード ID(本スキルが自動設定、外部から設定しないこと) |
| `ARI_MEMORY_BACKEND` | バックエンド選択 |
| `LETTA_HOST` | Letta API ホスト(letta backend 時) |
| `LETTA_PORT` | Letta API ポート |
| `LETTA_EMBEDDING_CONFIG` | Letta embedding 設定パス(必須、要監査) |

## Letta デプロイ
3 つのデプロイパス:
1. Apptainer(HPC 向け): `containers/letta.sif`
2. docker-compose: `containers/letta/docker-compose.yml`
3. pip: `pip install letta && letta server`

詳細は CHANGELOG v0.6.0 の Letta 節 + (将来) `docs/howto/letta_deployment.md`。

## 開発
\`\`\`bash
pytest tests/ -q                          # 全 15 テスト
pytest tests/test_isolation.py -q         # 祖先スコープ・兄弟非可視
pytest tests/test_cow.py -q               # Copy-on-Write
pytest tests/test_letta.py -q             # Letta backend
\`\`\`

## 関連
- ari-core/ari/memory/auto_migrate.py — v0.5 → v0.6 メモリ移行
```

### 2-2. Letta デプロイガイド
新規 `docs/howto/letta_deployment.md` への寄稿(マスター計画 [../docs/DOCUMENTATION_PLAN.md §4](../docs/DOCUMENTATION_PLAN.md) で位置づけ)。Apptainer / docker-compose / pip の 3 デプロイパスを記載。

### 2-3. mcp.json と実装の同期

## 3. 受け入れ基準

- [ ] README.md に 4 ツール、3 バックエンド、env var、Letta デプロイの 3 パスが揃う
- [ ] `pytest tests/ -q` がグリーン(15 テスト)
- [ ] `docs/skills.md` の本スキル節と整合
- [ ] Letta バックエンド選択時の必須 env var(`LETTA_EMBEDDING_CONFIG` 等)が明記

---

## 実装完了後の削除

**README 更新 PR と Letta デプロイガイド寄稿 PR がマージされた時点で本ファイルを削除する。**
