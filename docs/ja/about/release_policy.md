---
sources:
  - path: CHANGELOG.md
    role: doc
  - path: CONTRIBUTING.md
    role: doc
  - path: ari-core/pyproject.toml
    role: config
last_verified: 2026-05-25
---

# リリース & バージョニングポリシー

## SemVer の解釈

ARI は [Semantic Versioning 2.0](https://semver.org/spec/v2.0.0.html) に従います。

| バンプ | 変更内容 | 例 |
|---|---|---|
| **MAJOR** (1.0 → 2.0) | **パブリック**サーフェスへの後方非互換な変更 | `ari.public.*` シンボルの削除、MCP ツールのセマンティクス変更、チェックポイントフォーマットの破壊的変更 |
| **MINOR** (0.6 → 0.7) | 後方互換な機能追加 | 新 `ari.public.*` シンボル、新 MCP ツール、新 `ari` サブコマンド、安全なデフォルト値を持つ新環境変数 |
| **PATCH** (0.7.0 → 0.7.1) | バグ修正、ドキュメント更新、API サーフェスに影響しない内部リファクタリング | ツール I/O を変えない LLM プロンプト調整、ダッシュボード CSS、依存関係バンプ |

SemVer 目的での**パブリックサーフェス**:

- CLI (`ari ...`) — ドキュメント化されたすべてのサブコマンドとフラグ。
- `ari.public.*` Python インポート。
- 各スキルの `mcp.json` ツール一覧、名前、リクエスト/レスポンスの形状。
- viz REST API (`/api/` 配下のすべて)。
- ドキュメント化されたチェックポイントファイル (`tree.json`、`nodes_tree.json`、
  `node_report.json`、`settings.json`、`workflow.yaml`、
  `experiment.md`、`manifest.lock`、`publish_record.json`、
  `lineage_decisions.jsonl`)。
- ドキュメント化された環境変数 (`docs/reference/environment_variables.md` に記載のもの)。

パブリックサーフェスに**含まれない**もの:

- `ari.public.*` 外のモジュール。
- 内部専用ヘルパー (`_` プレフィックスの名前)。
- テストフィクスチャと `vendor/` スナップショット (PaperBench、VirSci など)。
- `ari/prompts/` 配下のプロンプト文字列 (フェーズ PC が管理するが SemVer 保護対象外 — ツール I/O コントラクトが維持される限り、マイナーリリースで変更可能)。

## サポートポリシー

| ブランチ | ステータス | バックポート対象 |
|---|---|---|
| `main` (最新マイナー) | アクティブ | 機能追加 + バグ修正 |
| 直前のマイナー | 次のマイナーリリース後 **6 か月** メンテナンス | セキュリティ + 重大バグ修正のみ |
| それ以前のマイナー | サポート終了 | なし |

現在の状態は `CHANGELOG.md` と
[GitHub releases](https://github.com/) ページで確認できます。

## 非推奨化 & 削除

*非推奨化* とは、パブリックシンボルまたは動作が削除される予告です。
以下のライフサイクルに従います:

1. **アナウンス** — リリースノートと `CHANGELOG.md` で変更を告知。
2. **警告** — ランタイムが少なくとも 1 つのマイナーリリースの間 `DeprecationWarning` を出力。
3. **削除** — 次の MAJOR で警告を削除し、コードを除去。

現在進行中の例 (全プログラムは
`CONTRIBUTING.md::Deprecation process` に折り込まれています):

| 項目 | アナウンス | 警告開始 | 削除予定 |
|---|---|---|---|
| `$HOME/.ari/registries.yaml` フォールバック | v0.5.0 | v0.7.1 | v1.0 |
| `$HOME/.ari/registry-data` フォールバック | v0.5.0 | v0.7.1 | v1.0 |
| レガシー v0.5 JSONL メモリストア | v0.5.0 | v0.5.0 | v1.0 |
| `~/.ari/memory.json` デフォルト引数 | v0.7.0 | v0.7.1 (削除済み) | v1.0 |
| `ari/migrations/v05_to_v07/` シム | v0.7.0 | v0.7.0 | v1.0 |

## リリースチェックリスト

リリースを切る際:

1. `CHANGELOG.md` に新しいセクションを追加する。エントリは
   **Added** / **Changed** / **Fixed** / **Deprecated** /
   **Removed** / **Security** に分類してまとめる。
2. `ari-core/pyproject.toml` と各
   `ari-skill-*/pyproject.toml` のバージョンをバンプする。
3. フルテストスイートと refactor-guards CI ワークフローを実行する。
4. ドキュメントゲートを実行する:
   - `grep -rn '~/\.ari/' docs/` (`refactor_audit.md` を除く) がゼロを返す。
   - ドキュメント化されたすべての環境変数が実際のソース参照にマップされる。
   - ドキュメント化されたすべての MCP ツールがスキルの `mcp.json` に存在する。
5. タグ付け: `git tag v0.X.Y && git push origin v0.X.Y`。
6. GitHub でリリースを作成し、changelog の抜粋を添付する。
7. バンドルを公開する: 同梱する必要があるアーティファクトに対して `ari ear publish` を実行する。

## 互換性ウィンドウ

- **MINOR** リリースは前方互換です: 直前のマイナーで生成したチェックポイントは
  新しいマイナーでも動作し続ける必要があります。
- **MAJOR** リリースでは 1 回限りのマイグレーションステップが必要になる場合があります。
  マイグレーションは `docs/howto/migration.md` に記載されており、
  `ari migrate ...` で実行します。
- スキルは独立してバージョン管理されます。`0.7.x` のスキルは
  `ari-core` の任意の `0.7.y` と動作するはずです (マイナー内での互換性)。
  マイナーをまたぐ場合は協調リリースを予定します。

## 関連

- `CHANGELOG.md` — リリースごとのノート。
- `CONTRIBUTING.md::Deprecation process` — 非推奨化の全プログラム。
- `docs/howto/migration.md` — バージョンごとのマイグレーションレシピ。
- `docs/reference/public_api.md` — このポリシーが保護するサーフェス。
