# ari-skill-orchestrator ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md とコード docstring)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | ARI 自身を MCP サーバとして外部公開し、外部システムから実験を起動・問い合わせ可能に |
| LOC | 1043 |
| MCP ツール | `run_experiment`, `get_status`, `list_runs`, `get_paper` |
| LLM 使用 | × |
| 決定論性 (P2) | △(配下の ARI 実行に依存) |
| 環境変数 | `ARI_WORKSPACE`, `ARI_ORCHESTRATOR_PORT` (既定 9890), `ARI_ORCHESTRATOR_LOGS`, `ARI_PARENT_RUN_ID`, `ARI_MAX_RECURSION_DEPTH` |
| ステート | あり(チェックポイントディレクトリ) |
| 既存 README | あり(品質要監査) |
| テスト | **0 ファイル**(欠落) |

## 2. 計画

### 2-1. README.md の更新

```markdown
# ari-skill-orchestrator

## 責務
ARI を MCP サーバとして外部に公開し、別の ARI インスタンス・スクリプト・LLM エージェントから
ARI 実験を起動できるようにする。再帰的な ARI 内 ARI 実行も可能(`ARI_MAX_RECURSION_DEPTH` で制御)。

## MCP ツール

### `run_experiment`
**用途:** experiment.md を渡して非同期で ARI 実験を起動。
**引数:**
- `experiment_md` (string, required): experiment.md の本文
- `settings` (dict, optional): settings.json オーバーライド
- `parent_run_id` (string, optional): 親 run_id(再帰実行時)
**戻り値:** `{ "run_id": "...", "checkpoint_dir": "...", "status": "started" }`
**副作用:** バックグラウンドで `ari run` プロセスが起動

### `get_status`
**引数:** `run_id`
**戻り値:** `{ "run_id", "status", "node_count", "best_metric", "elapsed_sec", ... }`

### `list_runs`
**戻り値:** 全 run の概要リスト

### `get_paper`
**引数:** `run_id`
**戻り値:** 生成された LaTeX セクションまたはコンパイル済 PDF パス

## 環境変数
| 変数 | 用途 | 既定値 |
|---|---|---|
| `ARI_WORKSPACE` | 実験のルートディレクトリ | (なし、必須) |
| `ARI_ORCHESTRATOR_PORT` | MCP サーバのポート | 9890 |
| `ARI_ORCHESTRATOR_LOGS` | run ログの格納ディレクトリ | `$ARI_WORKSPACE/orchestrator_logs` |
| `ARI_PARENT_RUN_ID` | 親 run_id(再帰実行時に自動設定) | (空) |
| `ARI_MAX_RECURSION_DEPTH` | 再帰実行の最大深さ | 3 |

## 再帰実行の安全装置
`run_experiment` を ARI 内部から呼ぶと、`ARI_PARENT_RUN_ID` が設定された子プロセスが起動する。
親子チェーンの深さが `ARI_MAX_RECURSION_DEPTH` を超えると拒否され、無限再帰を防ぐ。

## 開発
\`\`\`bash
# テストは現状未整備。最低限のスモークを今後追加予定。
python -m ari_skill_orchestrator.server &
curl -X POST http://localhost:9890/api/run -d '{...}'
\`\`\`

## テストギャップ
本スキルには現状テストがない。最低限のスモークテスト(MCP プロトコルでのハンドシェイクと
モック ARI 実行)を追加すべき。詳細は本パッケージ [REFACTORING.md は無い]。
```

### 2-2. テストギャップの周知
README にテスト 0 件の事実を明記。本ドキュメンテーション計画はテストを書かないが、将来的な対応を明示する。

### 2-3. mcp.json / skill.yaml と実装の同期

## 3. 受け入れ基準

- [ ] README.md に 4 ツール、5 env var、再帰実行の安全装置説明、テストギャップ告知
- [ ] `docs/skills.md` の本スキル節と整合
- [ ] orchestrator がチェックポイントディレクトリに書き込むファイル群が記載されている

---

## 実装完了後の削除

**README 更新 PR がマージされた時点で本ファイルを削除する。**
