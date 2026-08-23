---
sources:
  - path: CHANGELOG.md
    role: doc
  - path: CONTRIBUTING.md
    role: doc
  - path: DEPRECATION_REMOVAL.md
    role: doc
  - path: ari-core/pyproject.toml
    role: config
  - path: .github/workflows/refactor-guards.yml
    role: config
  - path: .github/workflows/docs-sync.yml
    role: config
  - path: scripts/docs
    role: implementation
last_verified: 2026-08-17
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

正式な台帳はリポジトリルートの `DEPRECATION_REMOVAL.md` です (tier、フェーズ
DR1–DR5、および公認された **5 つ** の Tier-B `~/.ari/` フォールバック地点 — 下表の
2 つに加えて `~/.ari/publish.yaml`、`~/.ari/letta-venv/`、そして 2 つ目の
`registries.yaml` リーダー)。`CONTRIBUTING.md::Deprecation process` は執筆者向けの
短い手順書です。現在進行中の例:

| 項目 | アナウンス | 警告開始 | 削除予定 |
|---|---|---|---|
| `$HOME/.ari/registries.yaml` フォールバック | v0.5.0 | v0.7.1 | v1.0 |
| `$HOME/.ari/registry-data` フォールバック | v0.5.0 | v0.7.1 | v1.0 |
| レガシー v0.5 JSONL メモリストア | v0.5.0 | v0.5.0 | v1.0 |
| `~/.ari/memory.json` デフォルト引数 | v0.7.0 | v0.7.1 (削除済み) | v1.0 |
| `ari/migrations/v05_to_v07/` シム | v0.7.0 | v0.7.0 | v1.0 |

5 つの Tier-B フォールバック、`ari.migrations.v05_to_v07` パッケージ、および
`legacy_reconstruct` シムは DR5 / v1.0 でまとめて削除され、その時点で
`ARI_LETTA_VENV` が必須になります。

## リリースチェックリスト

リリースを切る際:

1. `CHANGELOG.md` に新しいセクションを追加する。エントリは
   **Added** / **Changed** / **Fixed** / **Deprecated** /
   **Removed** / **Security** に分類してまとめる。
2. `ari-core/pyproject.toml` のバージョンをバンプする。これが
   **パッケージバージョン**であり、そこから派生する値は自動的に追随します
   (`scripts/snapshot_contracts.py` の `_read_ari_core_version()` が、4 つの
   contract golden の `_meta.ari_core_version` に刻み込みます)。

   **`ari-skill-*` を一斉にバンプしてはいけません。** これらは独立に versioning
   されており、現在 `0.1.0` から `2.0.0` まで散っています —
   [互換性 → Skills と core](compatibility.md#skills-と-core) を参照。skill の
   バージョンは飾りではありません: `LockedSkillV1` が manifest / provider の
   digest と並べて run ごとの skills lock に記録し、`write_or_verify_skills_lock`
   はその lock が既に存在すれば厳密一致を要求します。したがって skill の番号を
   動かすことは、**その skill が変わったと主張すること**です。17 個を 1 つの番号に
   揃えれば、意味のある 17 個の値が同じ値の 17 個のコピーに置き換わり、replay 時に
   lock からどの skill が動いたのかを読み取れなくなります。
   `scripts/check_skill_manifests.py` は manifest↔pyproject の `version-drift` で
   失敗するので、この主張は `skill.yaml` にもそのまま伝播します。

   skill は**それ自身の**表面が変わったときにバンプし、`ari-core>=` の下限は
   本当に新しいコアを必要とするときだけ引き上げます。結合はすでにその下限が
   担っており、意図的に不揃いです（`harness` と `knowledge` は `>=0.8.0`、
   他 7 つは `>=0.9.1`、残りは宣言なし）。一斉バンプは、実際に `0.8.0` で動く
   skill にそうでないと名乗らせることになります。どのバージョン群が組み合わさるかを
   決めるのは**協調リリース** — すなわち git タグ — であって、番号の一致では
   ありません。

   その上で、このリリースが**公開バージョンピン** — 読者に対して掲げる番号 —
   も動かすのかどうかを、明示的に判断する。これはもう 1 つ別のレジスタであり、
   独自の単一ソース (`docs/version.json`。`docs/i18n/version.js` がページ
   ロード時に取得する) を持ち、同一コミットで一緒に動かすべき 6 ファイルが
   それを再掲しています:

   - `README.md`、`README.ja.md`、`README.zh.md` — shields.io の
     `version-vX.Y.Z` バッジ。
   - `report/en/main.tex`、`report/ja/main.tex`、`report/zh/main.tex` —
     `\date{vX.Y.Z, ...}` 行。

   ピンを動かす場合は、3 つの `report/<lang>/main.pdf` を再ビルドし、
   `scripts/docs/sync_report_pdf.sh` を再実行することまでが必要です
   (このスクリプトは `docs/assets/report/` と `docs/public/report/` の
   **両方**に書き込みます)。PDF は生成物なので、LaTeX を再ビルドせずに
   `\date` だけを書き換えると、公開されている PDF はすべて古い番号のままに
   なります。

   さらに、3 つの README に新しい番号のリリースノート節
   (`## What's new in vX.Y.Z`。`README.ja.md` / `README.zh.md` では
   訳題) を追加することも必要です。v0.8.1 と v0.9.0 はそのように
   リリースされました。`check_readme_parity.py` は見出し構造を比較するので
   3 言語同時に追加することは強制されますが、その節が**存在すること自体**は
   どのゲートも検査しません。つまりこのチェックリストだけが拠り所です。
   README が記載していないバージョンをバッジが掲げるのは、それ自体が欠陥です。

   **パッケージのみのバンプは許容されており**、その場合ピンは据え置きます:
   contract を保存するリリースでユーザから見える変化が無いなら、掲げるものが
   無いからです。v0.9.1 (2026-07-05) がまさにそれで (`CHANGELOG.md` の該当
   エントリ参照)、`ari-core` が `0.9.1` でありながらピンが `v0.9.0` のままな
   のはこのためです。したがってピンはパッケージバージョンより**遅れて**いて
   構いませんが、**先行**してはなりません。パッケージ化されたことのない
   バージョンを掲げることになるからです。
   `python scripts/docs/check_site_i18n.py` がこの両面 — 上記 7 ファイルが
   互いに一致していること、およびピンが `ari-core/pyproject.toml` を追い越して
   いないこと — を検査します。
3. フルテストスイートと `refactor-guards`・`docs-sync`・`docs-change-coupling`
   CI ワークフローを実行する。
4. ドキュメントゲートを実行する。CI (`docs-sync.yml`、`refactor-guards.yml`) が
   実際にブロックしているのは次のものです:
   - `refactor-guards.yml` は、`ari-core/ari/**.py` の許可リスト外に **新規追加** された
     `~/.ari/` の行 (許可されるのは deprecation ヘルパー、`migrations/`、および
     フォールスルー前に警告を出すシム地点)、および pytest 実行が作成した
     `$HOME/.ari/` ディレクトリで失敗します。`docs/` 全体に対する `grep` は
     ありません: そこにある `~/.ari/` の言及の多くは正当なものです (vendor 化された
     PaperBench の `agent.env` 参照、`start.sh` の PID ファイル、Tier-B フォールバック
     そのもの)。
   - ドキュメント化されたすべての環境変数が実際のソース参照にマップされる。
   - ドキュメント化されたすべての MCP ツールがスキルの `mcp.json` に存在する。
   - `python scripts/docs/check_doc_sources.py` が 0 で終了する
     (宣言された `sources:` パスがすべて実在する)。より厳しい `--require-all`
     — *すべての* live doc が `sources:` を宣言していることも要求する — は段階的
     ロールアウト中で、現時点では**通りません**: ディレクトリごとの `README.md` が
     front matter を持たないためです。
   - `python scripts/docs/check_doc_links.py --html-only` が 0 で終了する。
     Markdown リンクの全走査 (フラグなしの `check_doc_links.py`) は CI では
     アドバイザリ実行のみです。
   - `python scripts/docs/check_i18n_js.py` が 0 で終了する
     (ランディング面の `docs/i18n/landing.{en,ja,zh}.js` が同一のキー集合を宣言する。
     レガシーの `docs.{en,ja,zh}.js` ビューア辞書は、docs が VitePress へ移行した際に
     削除されました)。
   - `python scripts/docs/check_readme_parity.py` が 0 で終了する
     (ルート `README.{md,ja,zh}` の見出し構造が一致する)。
   - `python scripts/docs/check_site_i18n.py` と、report の 3 言語パリティ /
     report PDF 同期のステップが 0 で終了する。
   - アドバイザリ: `python scripts/docs/check_translation_freshness.py`
     (`ja`/`zh` 翻訳の `last_verified` が英語版より古くない — [ソーストレーサビリティ](../../README.md#source-traceability) 参照)。
     `--strict` を付けるとブロッキングになりますが、英語だけを更新した直後は
     失敗するのが想定どおりです。
5. タグ付け: `git tag v0.X.Y && git push origin v0.X.Y`。
6. GitHub でリリースを作成し、changelog の抜粋を添付する。
7. バンドルを公開する: 同梱する必要があるアーティファクトに対して `ari ear publish` を実行する。

## 互換性ウィンドウ

- **MINOR** リリースは前方互換です: 直前のマイナーで生成したチェックポイントは
  新しいマイナーでも動作し続ける必要があります。
- **MAJOR** リリースでは 1 回限りのマイグレーションステップが必要になる場合があります。
  マイグレーションは `docs/guides/migration.md` に記載されており、
  `ari migrate ...` で実行します。
- スキルは独立してバージョン管理されており、その番号は `ari-core` を追随して
  **いません**: `ari-core` 0.9.1 に対し、同梱スキルの番号は `0.1.0`
  (`ari-skill-harness`、`ari-skill-knowledge`) から `2.0.0`
  (`ari-skill-orchestrator`) まで散らばっています。スキルと core のバージョン
  組み合わせを強制するコードは存在せず、スキルのバージョンはそのスキル自身の API に
  ついての表明であって、どの core を必要とするかを表すものではありません。
  番号の一致ではなく協調リリース単位で組み合わせてください。

## 関連

- `CHANGELOG.md` — リリースごとのノート。
- `CONTRIBUTING.md::Deprecation process` — 非推奨化の全プログラム。
- `docs/guides/migration.md` — バージョンごとのマイグレーションレシピ。
- `docs/reference/public_api.md` — このポリシーが保護するサーフェス。
