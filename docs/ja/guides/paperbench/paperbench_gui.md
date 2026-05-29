---
sources:
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
last_verified: 2026-05-26
---

# PaperBench GUI ガイド

ダッシュボードの **📚 PaperBench** サイドバーから:

- `/paperbench` — 論文レジストリ一覧
- `/paperbench/run` — 5 step 実行ウィザード
- `/paperbench/results?job=<id>` — 結果ビュー (rubric tree + ライブ
  ログ + レポートダウンロード)

## 論文レジストリ (`/paperbench`)

`~/.ari/paper_registry/manifest.jsonl` 内の全論文を表示 (上書きは
`ARI_PAPER_REGISTRY_DIR`)。各行の表示:

- ☑ チェックボックス — ウィザード用マルチ選択
- `paper_id` — FS-safe にサニタイズされた slug
- タイトル
- ライセンスバッジ — 寛容ライセンス (MIT, Apache, CC BY/SA, CC0,
  arXiv 非独占) は緑 ✅、 それ以外は黄 ⚠。 ホバーで詳細評価表示
- ソース — `arxiv:2404.14193`, `doi:10.1109/...` など
- 削除 — manifest 行と論文ディレクトリを同時に削除

上部のアクションバー:
- **📥 論文を取り込む** → `/paperbench/import`
- **🚀 PaperBench を実行 (N)** → `/paperbench/run` (N≥1 で活性)
- **更新** — manifest を再読込

## 論文取り込み (`/paperbench/import`)

v0.7.2 では最小限のフォーム:

| フィールド | 備考 |
|---|---|
| ソース種別 | `arxiv` \| `doi` \| `upload` \| `local` |
| ソース識別子 | arXiv ID (`2404.14193`)、DOI、PDF パス |
| タイトル | 必須 |
| 著者 | カンマ区切り |
| 会議 / 年 | 任意 |
| ライセンス | フリーフォーム; サーバ側で分類 |
| アーティファクト URL | 任意のコードリポ URL |

`source_type=arxiv` のとき「**↓ メタデータ取得**」ボタンが現れ、
`/api/paperbench/arxiv/<id>` 経由で arXiv Atom API を叩き、 title /
authors / year / license を自動入力する。

ライセンスバッジは `_classify_license` のサーバ判定をミラー:
- ✅ "寛容なライセンス — 利用可" — MIT, Apache-2.0, BSD, CC0, CC BY, CC BY-SA
- ⚠ "ライセンスは要確認" — それ以外 (不明文字列含む)

## 実行ウィザード (`/paperbench/run`)

5 step、全ての設定は単一の `POST /api/paperbench/run` body にまとまる。

### Step 1 — 論文選択

レジストリから複数選択。 1 件以上選択するまで Next 無効。

### Step 2 — ルーブリック設定

- **モデル** — `gemini-2.5-pro` (既定)、`gpt-5.4`、`claude-opus-4-7`
- **二段階** — skeleton + 並列 subtree 呼出。 ~4× リーフ数、~5× API
  コスト。 既定 on
- **目標リーフ数** — `0` (paper 長から自動、 ~1 leaf / 75 word)

### Step 3 — 再現設定

トップフォーム:
- **モデル** — 再現エージェントモデル (既定 `gpt-5-mini`)
- **時間上限** — 秒; 既定 12 h (PaperBench 論文 §5.2)
- **サンドボックス** — `auto` / `slurm` / `local` / `apptainer` / `docker`
- **パーティション** — `slurm` の時のみ意味あり

**実行プロファイル上書き** (v0.7.2 の焦点):

16 フィールドのグリッドが rubric から渡された execution_profile ヒントを
任意で上書きできる。 rubric が `execution_profile` を持つ場合、フィールドは
自動 pre-fill; なければ 0/"" 初期。

| フィールド | 型 | SLURM フラグ |
|---|---|---|
| nodes | int | `--nodes` |
| ntasks | int | `--ntasks` |
| ntasks_per_node | int | `--ntasks-per-node` |
| gpus_per_task | int | `--gpus-per-task` |
| memory_gb_per_node | int | `--mem` |
| exclusive | bool | `--exclusive` |
| gpu_type | str | `--gres=gpu:<type>:N` (`_slurm_has_gres()` でゲート) |
| constraint | str | `--constraint` |
| cpu_bind | str | `--cpu-bind` |
| mem_bind | str | `--mem-bind` |
| hint | str | `--hint` |
| nodelist | str | `--nodelist` |
| extra_sbatch_args | str (空白区切り) | pass-through |

詳細セマンティクスは [実行プロファイル仕様](../../reference/execution_profile.md) 参照。

### Step 4 — 採点設定

- **モデル** — `gpt-5-mini` (既定)、`claude-haiku-4-5-20251001`
- **n_runs** — 1 (PaperBench 論文 §4.1)
- **ネガティブコントロールをスキップ** — off 推奨; 安価な sanity check

### Step 5 — 実行

サマリ + ライブコスト見積もり (`POST /api/paperbench/cost-estimate`)
を表示。 *Dry run* で検証後、 *🚀 すべて実行* でジョブ投入。 各 paper
が 1 `job_id` になる。

## 監視 + 結果

ウィザードは `job_id` リストを返す。 ステータス:

```bash
curl http://localhost:8765/api/paperbench/run/<job_id>
```

実行中の論文は `/paperbench/results?job=<job_id>` で:
- **ライブログパネル** — Server-Sent Events (`/run/<id>/logs`) 経由で
  エージェントの出力をリアルタイム表示

完了後の同 URL で:
- **ルーブリックツリー** — 色分け (pass = 緑, fail = 赤) + per-leaf weight
- **カテゴリ別合格率テーブル**
- **ネガティブコントロール結果**
- **レポートダウンロード** — en/ja/zh × pdf/html/md (`POST /run/<id>/report`)

## v0.8.0 アップデート

- **Step 3 Reproduce: `container_image` フィールド追加** — SIF パス /
  `docker://` URI / `image:tag` / 短縮エイリアス `pb-env` /
  `pb-reproducer` (`scripts/build_pb_images.sh` で構築) を受領。
  `sandbox=docker`/`apptainer`/`singularity` 時のみ有効。
- **GPU フラグ整合**: `gpus_per_task` 単独 → `--ntasks 1` を自動 pair。
  `gpu_type` 設定時は `--gres=gpu:TYPE:N` を canonical として
  untyped `--gpus-per-task` を drop (SLURM 24.05 の typed/untyped 衝突回避)。
- **fail-loud 前提条件**: docker daemon / apptainer / sbatch / partition
  / GRES が不足する場合エラーで停止 (legacy 静黙フォールバックは
  `ARI_PHASE1_ALLOW_FALLBACK=1` / `ARI_SLURM_ALLOW_NO_GRES=1` で opt-in)。
- **Step 4 Judge: `code_only` 自動有効化** — Stage 2 がスキップされた
  時 (reproduce.log 不在), rubric が Code Development 葉のみに pruning
  され、Code Execution / Result Analysis 葉の structural 0 を回避。

## 関連

- [論文取り込み](paper_import.md)
- [クイックスタート](paperbench_quickstart.md)
- [実行プロファイル仕様](../../reference/execution_profile.md)
- [API リファレンス](../../reference/api_paperbench.md)
