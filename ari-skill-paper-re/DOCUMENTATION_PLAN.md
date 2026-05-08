# ari-skill-paper-re ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

このスキルパッケージ配下のドキュメント(README.md、PaperBench 統合の運用書)。実装は変更しない。

## 1. スキルファクト(現状)

| 項目 | 値 |
|---|---|
| 責務 | PaperBench 互換の再現性評価。Phase 1 でコードをサンドボックス実行、Phase 2 で SimpleJudge ルブリックによる LLM 採点 |
| LOC | 5936(`server.py` + bridge + replicator + compute) |
| MCP ツール | `fetch_code_bundle`, `build_reproduce_sh`, `run_reproduce`, `grade_with_simplejudge` |
| LLM 使用 | ○ |
| 決定論性 (P2) | × |
| 環境変数 | `ARI_PAPERBENCH_PATH`, `ARI_MODEL_REPLICATOR`, `ARI_LLM_MODEL`, `ARI_REPLICATOR_TIME_LIMIT_SEC`(既定 12h) |
| ステート | あり(コードバンドル、サンドボックス結果) |
| 既存 README | あり(要監査) |
| テスト | 228 ファイル(うち PaperBench 配下が大半) |
| 重要 | v0.7.0 で導入された ORS(Object Repository Spec)再現性チェーンの心臓部 |

## 2. 計画

### 2-1. README.md の更新

```markdown
# ari-skill-paper-re

## 責務
**PaperBench 互換の再現性評価**を 2 フェーズで実行:

### Phase 1: 再現実行
1. `fetch_code_bundle`: 論文の成果物(arXiv の SI、GitHub リポジトリ等)からコードを取得
2. `build_reproduce_sh`: 自動的に再現スクリプト `reproduce.sh` を生成(LLM が依存・コマンドを推定)
3. `run_reproduce`: サンドボックス内で `reproduce.sh` を実行(時間制限あり)

### Phase 2: 採点
4. `grade_with_simplejudge`: 実行結果を SimpleJudge ルブリックで LLM 採点

## MCP ツール

### `fetch_code_bundle`
**引数:** `paper_artifact` (arXiv ID, GitHub URL, DOI, etc.)
**戻り値:** `{ "bundle_path": "...", "language": "...", "size_bytes": ... }`

### `build_reproduce_sh`
**引数:** `bundle_path`, `paper_text`(再現意図の手がかり)
**戻り値:** `{ "reproduce_sh_path": "...", "estimated_time": "..." }`

### `run_reproduce`
**引数:** `reproduce_sh_path`, `time_limit_sec` (default 43200 = 12h)
**戻り値:** `{ "exit_code", "stdout", "stderr", "outputs": [...], "wall_time_sec": ... }`
**副作用:** サンドボックス(コンテナまたは uv venv)を起動

### `grade_with_simplejudge`
**引数:** `paper_id`, `reproduce_outputs`, `rubric_path`
**戻り値:** `{ "score": float, "axes": [...], "rationale": "..." }`

## 環境変数
| 変数 | 用途 | 既定値 |
|---|---|---|
| `ARI_PAPERBENCH_PATH` | vendored PaperBench のパス上書き | `vendor/paperbench/` |
| `ARI_MODEL_REPLICATOR` | コード抽出・スクリプト生成用 LLM | `ARI_LLM_MODEL` 経由 |
| `ARI_LLM_MODEL` | 採点用 LLM | (なし) |
| `ARI_REPLICATOR_TIME_LIMIT_SEC` | 再現実行の最大時間 | 43200 (12h) |

## 内包(vendored)
- **PaperBench**: `vendor/paperbench/`
- **nanoeval, preparedness_turn_completer**: `src/_vendor_path.py` 経由で sys.path に注入
- ライセンスは PaperBench 元レポジトリに準拠

## ORS との関係(v0.7)
本スキルは v0.7.0 で導入された **ORS(Object Repository Spec)** の再現性チェーンを実現する中核。
ORS により、ARI が生成した実験チェックポイントを別環境で再現・採点できる。

## 開発
\`\`\`bash
pytest tests/ -q                          # 全テスト(228、時間がかかる)
pytest tests/test_litellm_completer.py -q # LLM 補完器
pytest tests/test_replicator_agent.py -q  # 再現エージェント
\`\`\`

## P2 例外
LLM を多用、サンドボックス実行は時間ベースで非決定的。
```

### 2-2. ORS / EAR との整合
- `docs/architecture.md` の ORS 節([../docs/DOCUMENTATION_PLAN.md §2-3](../docs/DOCUMENTATION_PLAN.md))から本スキルへリンク
- `docs/skills.md` への新スキル記載([../docs/DOCUMENTATION_PLAN.md §2-2](../docs/DOCUMENTATION_PLAN.md))

### 2-3. PaperBench 内包のドキュメント
`vendor/paperbench/` のライセンス・更新方針を README に明記。

## 3. 受け入れ基準

- [ ] README.md に 4 ツール、4 env var、PaperBench 内包の説明、ORS との関係
- [ ] `docs/skills.md` に本スキルの独立節
- [ ] `docs/architecture.md` の ORS 節から本スキルへリンク

---

## 実装完了後の削除

**README 更新 PR と `docs/skills.md` 追記 PR がマージされた時点で本ファイルを削除する。**
