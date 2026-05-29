---
sources:
  - path: ari-core/ari/migrations/v05_to_v07
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
last_verified: 2026-05-25
---

# マイグレーションガイド

ARI のチェックポイントフォーマットは 3 回のリリースを経て進化してきました。
このガイドではアップグレードパスを説明します。

| 移行元 | 移行先 | 主な変更点 |
|---|---|---|
| v0.5 | v0.6 | Letta メモリバックエンドが JSONL を置き換え |
| v0.6 | v0.7 | ORS / EAR レジストリ / lineage decisions |
| v0.7 | v0.8 (予定) | リファクタリングされたチェックポイントフォーマット (`ari.public/` 境界) |
| v0.8 | v1.0 (予定) | レガシー互換シムの削除 |

## v0.5 → v0.6

### 変更内容

- **メモリバックエンド。** チェックポイントごとの `memory_store.jsonl` と
  グローバル `$HOME/.ari/global_memory.jsonl` (実験横断) は廃止されました。
  デフォルトバックエンドは Letta になりました (チェックポイントごとのエージェントで、
  アーカイブコレクション `ari_node_*` および `ari_react_*` を使用)。
- **`$HOME/.ari/` の削除。** v0.5.0 でグローバル設定ディレクトリはすでに削除済み。
  v0.6 では新しいレイアウトが唯一の書き込み可能サーフェスになります。
- **ルーブリックシステム。** `ari-skill-paper` が `ARI_RUBRIC` で選択する
  YAML ルーブリックを採用しました。

### 手順

1. **Letta サービスを起動する。** `docs/guides/hpc_setup.md#6-letta-memory-backend-deployment`
   のデプロイパス (Apptainer SIF、docker-compose、または pip) から 1 つ選択します:
2. **必要な環境変数を設定する。**
   ```bash
   export LETTA_BASE_URL=http://127.0.0.1:8283
   export LETTA_EMBEDDING_CONFIG=/path/to/embedding.json
   export ARI_MEMORY_BACKEND=letta
   ```
3. **既存のメモリを移行する。** v0.5 の各チェックポイントで:
   ```bash
   ARI_CHECKPOINT_DIR=/path/to/ckpt ari memory migrate
   ```
   マイグレーターは `memory_store.jsonl` (およびレガシーグローバル JSONL が
   存在すれば) を読み込み、Letta エージェントに書き込み、結果を
   `memory_backup.jsonl.gz` にスナップショット保存します。
4. **レガシー JSONL を削除する。** マイグレーションを確認したあとに:
   ```bash
   rm /path/to/ckpt/memory_store.jsonl
   rm $HOME/.ari/global_memory.jsonl   # if it ever existed
   ```
5. **ルーブリックを選択する。** `ari-core/config/reviewer_rubrics/` から
   YAML を選択してエクスポートします:
   ```bash
   export ARI_RUBRIC=neurips2025
   ```
   以降の論文レビューと BFTS スコアリングが新しい軸を使用します。

### 確認

- `ari memory health` が `ok` を返し、エージェント名を報告する。
- エージェントループからの `search_memory` 呼び出しが埋め込みランクの結果を返す。
- ダッシュボードの `/api/memory/health` エンドポイントが 200 を返す。

## v0.6 → v0.7

### 変更内容

- **ORS (Object Repository Spec)。** 再現性チェーンが `react_driver` のアドホックな
  複製から `ari-skill-replicate` (ルーブリック生成) と `ari-skill-paper-re`
  (PaperBench SimpleJudge 採点) に移行しました。
- **EAR レジストリ。** EAR バンドルをセルフホスト型 `ari-registry` サーバに公開
  できるようになりました (local-tarball / Zenodo / GitHub release に加えて)。
- **Lineage decisions。** `stagnation_rule` が BFTS の複合スコアを監視し、
  発火すると LLM が `continue` / `switch_to_idea` / `fanout` / `terminate` を
  選択します。決定は `lineage_decisions.jsonl` に追記されます。
- **work_dir ブラックリスト。** 子ノードの `work_dir` は結果ファイル
  (`results.csv`、`slurm-*.out` など) を継承しなくなりました。
  既存のチェックポイントは引き続き動作しますが、継承に依存していた子実行は
  再実行が必要です。

### 手順

1. **ルーブリックディレクトリを設定する。**
   `ari-core/config/reviewer_rubrics/` に使用したいルーブリックがあることを
   確認します。`ARI_RUBRIC` でアクティブなものを選択します。
2. **(任意) `ari registry serve` を起動する。** `ari://` 経由でバンドルを
   公開したい場合のみ必要です。先に `ARI_REGISTRY_DATA` を設定してください。
   クライアント側の設定は `ARI_REGISTRIES_FILE` と `ARI_REGISTRY_TOKEN` です。
3. **結果継承に依存していたサブ実験を再実行する。**
   ブラックリストにより、子ノードが `results.csv` / `slurm-*.out` /
   `node_report.json` をコピーしなくなりました。コード、コンパイル済みバイナリ、
   入力ファイルは引き続き継承されます。
4. **(任意) 再現性フローを組み込む。** 論文が準備できたら実行します:
   ```bash
   ari ear curate <checkpoint>
   ari ear publish <checkpoint> --backend ari-registry
   ari replicate generate-rubric <checkpoint>
   ari paper-re grade <checkpoint>
   ```

### 確認

- stagnation rule が初めて発火したときに `lineage_decisions.jsonl` が作成される。
- `ari ear publish` 後に `manifest.lock` と `publish_record.json` が現れる。

## v0.7 → v0.8 (予定)

### 想定される変更

- スキルは `ari.public.*` からのみインポート可能になります。
  `tests/test_public_api_boundary.py` ガードレールはすでに存在します。
  v0.8 では非推奨シムを削除します。
- `ari/migrations/v05_to_v07/` のハウスキーピングヘルパーが `ari run` に
  混在している状態から、専用の CLI サーフェス (`ari migrate ...`) に移動します。

### 事前対応手順

- カスタムスキルで直接 `from ari import <internal>` しているインポートを確認します。
  `python -m ari.dev.public_audit` (計画中) でリストアップできます。
  現状は `grep -rn 'from ari import\|from ari\.' my-skill/src/` で代替できます。
- 内部インポートが見つかった場合は、対応する `ari.public.*` モジュールに
  切り替えます (`docs/reference/public_api.md` を参照)。

## v0.8 → v1.0 (予定)

非推奨化プログラム (`CONTRIBUTING.md::Deprecation process`、
`docs/about/release_policy.md`) では以下を予定しています:

- `DeprecationWarning` を発行中のすべての `$HOME/.ari/...` ファイルシステム
  フォールバックの削除。
- `ari/migrations/v05_to_v07/` の削除 (アップグレード前の移行を強制)。
- レガシー `node_report` 再構築ヘルパーの削除。

v1.0 までに移行していない場合、ARI は本ガイドへのポインタとともに
ハードエラーで起動を拒否します。

## 関連

- `docs/_archive/refactor_audit.md` — マイグレーション負債の現状。
- `CHANGELOG.md` — リリースごとのノート。
- `ari memory migrate --help` — v0.5 → v0.6 マイグレーターの CLI オプション。
- `docs/guides/troubleshooting.md` — マイグレーション失敗時の対処法。
