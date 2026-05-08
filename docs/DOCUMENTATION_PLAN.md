# docs/ ドキュメンテーション計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md)

## 0. 範囲

`/home/t-kotama/workplace/ARI/docs/` 配下のユーザ向けドキュメント全体。実装(コード)は変更しない。

## 1. 既存ドキュメント インベントリ

### 1-1. 英語(`docs/*.md`)

| ファイル | サイズ | 最終更新 | 分類 | 状態 |
|---|---|---|---|---|
| `architecture.md` | 57 KB | May 8 (v0.7) | Explanation | 大幅改稿が必要(v0.6/v0.7 機能の反映、レイヤー図の追加) |
| `cli_reference.md` | 19 KB | May 8 | Reference | コマンド体系反映 OK、`~/.ari/` 残存箇所を確認 |
| `configuration.md` | 23 KB | May 8 | Reference | env var 一覧の独立化が必要 |
| `experiment_file.md` | 2.5 KB | Apr 17 | Reference | **更新停止中**: v0.6 以降の experiment.md 機能(ORS、rubric)未反映 |
| `extension_guide.md` | 9 KB | Apr 17 | How-to | **更新停止中**: `ari/public/` API 反映必須 |
| `hpc_setup.md` | 2.8 KB | Apr 17 | How-to | **更新停止中**: container 設定の追加必要 |
| `PHILOSOPHY.md` | 7 KB | May 8 | Explanation | P1〜P5 設計原則ベース、軽微な追従のみ |
| `quickstart.md` | 19 KB | May 8 | Tutorial | v0.7 機能(ORS / EAR / lineage)反映 OK?要監査 |
| `registry.md` | 3.5 KB | May 8 | Explanation | OK |
| `skills.md` | 37 KB | May 8 | Reference + Explanation | **重大欠落**: `ari-skill-replicate` `ari-skill-paper-re` 未掲載 |

### 1-2. 翻訳(ja/zh)

- **ja/**: 10 ファイル、英語版にほぼ追従。`experiment_file.md` `extension_guide.md` `hpc_setup.md` `PHILOSOPHY.md` は Apr 17 で停止。
- **zh/**: 4 ファイル(`architecture.md` `cli_reference.md` 等)。英語版との網羅性に不足。
- **i18n.js**: ローカライズ辞書(en.js, ja.js, zh.js)。HTML 版ドキュメントで参照。

## 2. Phase D1: 既存ドキュメントの追従(優先順)

### 2-1. **`~/.ari/` 残存記述の一掃**(最高優先・破壊的)
影響範囲: `configuration.md` `cli_reference.md` `registry.md` `quickstart.md`、および ja/zh 対応版(計 7 ファイル)

各箇所で次の置換を実施:

| 旧記述 | 新記述 |
|---|---|
| `~/.ari/registries.yaml` | `$ARI_CHECKPOINT_DIR/settings.json` の `registries` セクション |
| `~/.ari/registry-data` | `$ARI_CHECKPOINT_DIR/.ari_registry/` |
| `~/.ari/settings.json` | `$ARI_CHECKPOINT_DIR/settings.json` |
| `~/.ari/global_memory.jsonl` | `$ARI_CHECKPOINT_DIR/memory_store.jsonl` または Letta backend |

各置換の上に `> **Note:** v0.5.0 で `~/.ari/` グローバル状態は廃止。本書はチェックポイントスコープの新仕様を記載。` を追記。

### 2-2. **`skills.md` への新スキル追記**
- `ari-skill-replicate`: 2 ツール(`generate_rubric` `audit_rubric`)、PaperBench 互換ルブリック自動生成
- `ari-skill-paper-re`: 4 ツール(`fetch_code_bundle` `build_reproduce_sh` `run_reproduce` `grade_with_simplejudge`)、PaperBench フェーズ 1+2

各スキルにつき:
- 責務(1 段落)
- ツール一覧(名前・引数・戻り値)
- 環境変数(`ARI_*`)
- 決定論性(P2)の扱い
- v0.7 で追加された旨

### 2-3. **`architecture.md` の v0.6/v0.7 反映**
追加すべき節:
- BFTS Lineage Decisions(v0.7): stagnation 検出、frontier 拡張ロジック
- ORS(Object Repository Spec)と EAR レジストリ(v0.7): 再現性チェーン
- Letta memory backend(v0.6): in_memory との切替、API キー設定
- Rubric-driven paper review(v0.6): `ari-skill-paper` の rubric サブシステム
- レイヤー図([../REFACTORING.md §3](../REFACTORING.md) と整合)

### 2-4. **Apr 17 停止の 4 ドキュメント追従**
- `experiment_file.md`: v0.6 以降の experiment.md セクション(ORS metadata、rubric override)を追記
- `extension_guide.md`: スキル開発時の `ari.public` 利用方法、`mcp.json` フォーマット、テスト書き方
- `hpc_setup.md`: container セクション(Docker/Singularity)、Letta backend のデプロイ
- `PHILOSOPHY.md`: P2 (決定論性) の例外として Letta backend が許容された経緯

### 2-5. 受け入れ基準
- `grep -rn "~/.ari/" docs/` のヒットが 0 件
- `grep -rn "ari-skill-replicate\|ari-skill-paper-re" docs/skills.md` でそれぞれ独立節を発見
- `architecture.md` の目次に「BFTS Lineage」「ORS / EAR」「Letta backend」が出現

## 3. Phase D3: Reference 新規作成

### 3-1. `docs/reference/rest_api.md`(新規)
ターゲット: スキル開発者・GUI 拡張者

各 REST エンドポイントを以下の形式で記載:

```markdown
### GET /api/checkpoints/{ckpt_id}/summary

**Description:** チェックポイントのサマリ(experiment goal、ノード数、ステータス、上位メトリクス)。

**Path parameters:**
- `ckpt_id` (string, required): チェックポイントディレクトリ名

**Response 200:** application/json
```json
{
  "ckpt_id": "...",
  "experiment_goal": "...",
  "node_count": 42,
  "status": "running" | "completed" | "errored",
  ...
}
```

**Source:** `ari-core/ari/viz/checkpoint_api.py:_api_checkpoint_summary`(リファクタ後)
```

最低限カバーすべきエンドポイント(リファクタ計画の `viz/api_state.py` 分割マッピングから網羅):
- `/api/state` `/api/models` `/api/checkpoints` `/api/checkpoints/{id}/summary` `/api/checkpoints/{id}/files` `/api/checkpoints/{id}/files/{name}` `/api/checkpoints/{id}/ear` `/api/checkpoints/{id}/lineage_decisions` `/api/checkpoints/{id}/file/{path}` `/api/checkpoints/{id}/filetree` `/api/checkpoints/{id}/memory` `/api/checkpoints/{id}/compile` `/api/tools` `/api/memory/health` `/api/settings` `/api/workflow` `/api/launch` 他

### 3-2. `docs/reference/mcp_tools.md`(新規)
14 スキルが提供する全 MCP ツールの一覧。各スキルの `mcp.json` / `skill.yaml` から取得し、以下を記載:

- ツール名
- 引数スキーマ(JSON Schema)
- 戻り値スキーマ
- 副作用(ファイル書き込み・サブプロセス起動 等)
- LLM 使用の有無
- 例

**自動生成の可能性**: 各スキルの `mcp.json` を集約して Markdown 化するスクリプトを `scripts/gen_mcp_reference.py` として用意することを検討。

### 3-3. `docs/reference/environment_variables.md`(新規)
プロジェクト全体の環境変数を以下の表で:

| 変数名 | 用途 | 既定値 | 設定箇所 | 必須? |
|---|---|---|---|---|
| `ARI_CHECKPOINT_DIR` | チェックポイントディレクトリ | (なし) | `ari-core/ari/paths.py` | はい |
| `ARI_MEMORY_PATH` | メモリストアパス | `$ARI_CHECKPOINT_DIR/memory_store.jsonl` | `ari-core/ari/memory/...` | いいえ |
| `ARI_LLM_MODEL` | 既定 LLM モデル | (なし) | `ari-core/ari/llm/client.py` | スキル次第 |
| ... | ... | ... | ... | ... |

リファクタリング計画の Phase 1(`PathManager` 集約)が完了すれば、env var 群の所在が一意になり本リファレンスの正確性が保証される。

### 3-4. `docs/reference/file_formats.md`(新規)
ARI が読み書きする JSON ファイルのスキーマ:

- `tree.json`: BFTS 木の状態
- `nodes_tree.json`: ノードごとの詳細
- `results.json`: 最終結果
- `node_report.json`: ノード単位レポート(legacy 互換含む)
- `settings.json`: チェックポイントスコープ設定
- `workflow.yaml`: パイプライン定義
- `experiment.md`: 実験仕様(セクション構造)

各形式について JSON Schema または例ベースで記載。**リファクタ計画の Phase 2 (`ari/checkpoint.py` 共有モジュール) と整合**を取る。

## 4. Phase D4: How-to 新規

### 4-1. `docs/howto/testing.md`(新規)
- ari-core のテスト方針(`agent/` のスモークテストを含む — リファクタ計画 Phase 0 のテスト 3 本を例示)
- スキル側テストの書き方(MCP モック、LLM モック)
- 決定論性回帰テストの書き方(同一 seed での BFTS 同型ツリー検証)
- pytest fixtures の慣習

### 4-2. `docs/howto/migration.md`(新規)
- v0.5 → v0.6: メモリ backend 切替、`~/.ari/` 廃止
- v0.6 → v0.7: ORS / EAR / lineage decisions 導入
- v0.7 → v0.8(将来): リファクタ計画完了後のチェックポイント形式
- v0.8 → v1.0(将来): legacy 互換コード削除予定の予告

### 4-3. `docs/howto/troubleshooting.md`(新規)
よくあるエラーと対処:
- `ARI_CHECKPOINT_DIR not set` → 起動方法
- SLURM ジョブが pending のまま → partition 設定
- Letta backend 接続失敗 → API キー、ポート
- LLM クォータ超過 → cost_tracker の確認方法
- VLM 図解析失敗 → モデル設定

## 5. Phase D5: i18n 同期 + リリース方針

### 5-1. ja/zh 翻訳の追従
英語版で更新したすべての箇所を ja/zh に反映。新規 reference docs(REST/MCP/env/file format)は最初は英語のみ可とし、ja/zh は後追いを許容。

優先順:
1. `~/.ari/` 一掃(全言語同時)
2. `skills.md` の新スキル(ja は同時、zh は後追い可)
3. `architecture.md` の v0.6/v0.7 反映
4. Apr 17 停止 4 ドキュメント

### 5-2. `docs/release_policy.md`(新規)
- SemVer の解釈(MAJOR=互換破壊、MINOR=機能追加、PATCH=バグ修正)
- 各バージョンのサポート期間
- legacy 互換コードの削除タイミング(リファクタ計画 Phase 5 と整合)
- リリース手順(CHANGELOG 更新、タグ付け、リリースノート作成)

## 6. ドキュメント間の相互リンク要件

| 元 | 先 | リンクテキスト |
|---|---|---|
| `architecture.md` | `reference/rest_api.md` | "Web ダッシュボード API は完全リファレンスを参照" |
| `extension_guide.md` | `reference/mcp_tools.md` | "既存スキルのツールスキーマは MCP Tools Reference を参照" |
| `extension_guide.md` | `howto/testing.md` | "新スキルのテスト書き方" |
| `configuration.md` | `reference/environment_variables.md` | "環境変数の完全リスト" |
| `quickstart.md` | `howto/troubleshooting.md` | "起動に失敗したら" |
| `howto/migration.md` | `architecture.md` | "v0.7 で導入された ORS の詳細" |

## 7. 挙動保証

ドキュメント変更のみ。コードは触らない。例外:
- `scripts/gen_mcp_reference.py` を新設する場合、これは独立スクリプトでありランタイム挙動に影響しない
- HTML 版(`docs.html` `index.html`)を再ビルドする場合、生成元の `.md` の変更を反映するのみで挙動変化なし

## 8. 受け入れ基準

- [ ] `grep -rn "~/.ari/" docs/` ヒット 0
- [ ] `docs/reference/` 配下に rest_api.md / mcp_tools.md / environment_variables.md / file_formats.md が存在
- [ ] `docs/howto/` 配下に testing.md / migration.md / troubleshooting.md が存在
- [ ] `docs/skills.md` に 14 スキルすべての節が独立して存在
- [ ] `docs/architecture.md` の目次に v0.6/v0.7 の主要機能が掲載
- [ ] ja/zh の節構成が英語版と一致(新規 reference 系を除く)
- [ ] `grep -nE '\]\([^)]*\)' docs/**/*.md` の各リンクが解決(壊れリンク 0)

---

## 実装完了後の削除

**Phase D1〜D5 の docs PR がすべてマージされた時点で本ファイルを削除する。** マスター計画 [../DOCUMENTATION_PLAN.md](../DOCUMENTATION_PLAN.md) と同じタイミング。

恒久化する内容:
- §1 ドキュメントインベントリ → 不要(`ls docs/` が事実)
- §3〜4 の新規ドキュメント仕様 → 完成した実ドキュメントが代替
- §6 相互リンク要件 → 各ドキュメント内のリンクとして実装済みになる
