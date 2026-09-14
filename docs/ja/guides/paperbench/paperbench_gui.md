---
sources:
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/PaperBench
    role: implementation
  - path: ari-core/ari/viz/frontend/src/app/routeRegistry.ts
    role: implementation
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/src/sandbox.py
    role: implementation
  - path: ari-skill-replicate/src/generator.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/contracts.py
    role: implementation
last_verified: 2026-08-16
---

# PaperBench GUI ガイド

ダッシュボードの **📚 PaperBench** サイドバーから入る。ルートは
hash ルート (`#/paperbench…`) で、ナビゲーション項目を持つのは
レジストリだけ。残り 3 つは画面内からしか辿れない:

- `#/paperbench` — 論文レジストリ一覧
- `#/paperbench/import` — 取り込みフォーム
- `#/paperbench/run` — 5 step 実行ウィザード
- `#/paperbench/results?job=<job_id>` — 結果ビュー (rubric tree + ライブ
  ログ + レポートダウンロード)

## 論文レジストリ (`#/paperbench`)

`{workspace_root}/paper_registry/manifest.jsonl` 内の全論文を表示。
ルートは `ARI_PAPER_REGISTRY_DIR` が設定されていればそれ、無ければ
`PathManager.from_env().paper_registry_root` (workspace 配下の
`{workspace}/paper_registry`、checkpoint が無い場合は `./paper_registry`)。
`~/.ari/` の下では**ない** — v0.5+ の ARI はユーザ単位のグローバル
データディレクトリを持たない。各行の表示:

- ☑ チェックボックス — マルチ選択。ただし選択はウィザードに引き継がれず、
  Step 1 で改めて選び直す
- `paper_id` — FS-safe にサニタイズされた slug
- タイトル
- ライセンスバッジ — 評価が `usable` (寛容 AND 再配布可 AND
  非商用でない) のとき緑 ✅、それ以外は赤 ⚠。 ホバーで詳細評価表示
- ソース — `arxiv:2404.14193`, `doi:10.1109/...` など
- 削除 — `POST /api/paperbench/papers/<paper_id>/delete`。manifest 行と
  論文ディレクトリを同時に削除

上部のアクションバー:
- **📥 論文を取り込む** → `#/paperbench/import`
- **🚀 PaperBench を実行 (N)** → `#/paperbench/run` (N≥1 で活性)
- **更新** — manifest を再読込

## 論文取り込み (`#/paperbench/import`)

v0.7.2 では最小限のフォーム:

| フィールド | 備考 |
|---|---|
| ソース種別 | `arxiv` \| `doi` \| `upload` \| `local` |
| ソース識別子 | arXiv ID (`2404.14193`)、DOI、PDF パス |
| PDF ファイル | `source_type=upload` のときだけ表示; `POST /api/upload` で退避 |
| タイトル | 必須 |
| 著者 | カンマまたはセミコロン区切り |
| 会議 / 年 | 任意 |
| ライセンス | フリーフォーム; サーバ側で分類 |
| アーティファクト URL | 任意のコードリポ URL |

`source_type=arxiv` のとき「**↓ メタデータ取得**」ボタンが現れ、
`GET /api/paperbench/arxiv/<id>` 経由で arXiv Atom API を叩き、 title /
authors / year / license を自動入力する。ただし **PDF は取得されない** —
レスポンスに `pdf_url` は入るが誰もダウンロードしない。実行 worker は
`papers/<paper_id>/paper.pdf` が無いと中断するので、arXiv 取り込みでも
PDF は手で添付する必要がある。

ライセンス入力欄の下のバッジはサーバの判定**ではない**。クライアント側の
楽観的な正規表現 (`/^cc(\s|-)by(\s|-)?(4\.?0)?$|^(mit|apache|bsd|arxiv)/i`)
で `_classify_license` を近似しているだけなので、例えば `CC0` はフォーム上
⚠ になるがサーバからは `usable` で返る。正式な `license_assessment` は
import レスポンスに載り、レジストリ行はそれを描画する。

- ✅ "寛容なライセンス — 利用可" — MIT, Apache-2.0, BSD-2/3-Clause, CC0,
  CC BY, CC BY-SA, arXiv 非独占
- ⚠ "ライセンスは要確認" — それ以外 (不明文字列含む)、および
  **CC BY-NC**。`_classify_license` は CC BY-NC を寛容だが非商用と判定し、
  したがって usable にはしない

## 実行ウィザード (`#/paperbench/run`)

5 step、全ての設定は単一の `POST /api/paperbench/run` body にまとまる。

### Step 1 — 論文選択

レジストリから複数選択。 1 件以上選択するまで Next 無効。

### Step 2 — ルーブリック設定

- **モデル** — ドロップダウンではなく自由記述フィールド。既定
  `gemini/gemini-2.5-pro`。LiteLLM が解釈できるモデル ID なら何でも通る
- **目標リーフ数** — `0` (paper 長から自動: `words // 75` を
  `[50, 400]` にクランプ)

二段階トグルは存在しない。ジェネレータは無条件に `hierarchical-v2`
(skeleton pass + 並列 subtree pass)。その `max_model_calls` (64) と
`subtree_concurrency` (4) は `POST /api/paperbench/run` が受け付けるが、
ウィザードには対応フィールドが無い。

### Step 3 — 再現設定

トップフォーム:
- **モデル** — 再現エージェントモデル (既定 `gpt-5-mini`)
- **時間上限** — 秒; 既定 12 h (PaperBench 論文 §5.2)
- **サンドボックス** — `auto` / `slurm` / `local` / `apptainer` / `docker`
- **パーティション** — `slurm` の時のみ意味あり

**実行プロファイル上書き** (v0.7.2 の焦点):

13 フィールドのグリッドが rubric から渡された execution_profile ヒントを
任意で上書きできる。 フィールドは常に `0` / `""` から始まる — ウィザードは
pre-fill を一切しない。rubric の `execution_profile` とのマージはサーバ側の
`run_reproduce` で行われ、非ゼロの caller 値が勝ち、0 / 空なら rubric の
ヒントに落ちる。

| フィールド | 型 | SLURM フラグ |
|---|---|---|
| nodes | int | `--nodes` (既定 1) |
| ntasks | int | `--ntasks` — 常に出力。既定は `ntasks_per_node × nodes`、それも無ければ 1 |
| ntasks_per_node | int | `--ntasks-per-node` |
| gpus_per_task | int | `--gpus-per-task=[<gpu_type>:]<n>` |
| memory_gb_per_node | int | `--mem=<n×1024>M` |
| exclusive | bool | `--exclusive` |
| gpu_type | str | GPU 数の前置修飾。単独 (count 無し) なら `gpus_per_node=1` を含意し `--gres=gpu:<type>:1` |
| constraint | str | `--constraint` |
| cpu_bind | str | **`sandbox=slurm` では拒否** — 下記参照 |
| mem_bind | str | **`sandbox=slurm` では拒否** — 下記参照 |
| hint | str | `--hint`。`compute_bound` / `memory_bound` / `multithread` / `nomultithread` のみ通る |
| nodelist | str | `--nodelist` |
| extra_sbatch_args | str (空白区切り) | 任意 pass-through では**ない**: `--account=` / `--qos=` / `--reservation=` / `--hint=` のみ受け付けて型付きフィールドに変換する。それ以外のエントリは run を失敗させる |

このグリッドの罠が 2 つ:

- `cpu_bind` / `mem_bind` は `srun --cpu-bind` / `--mem-bind` に変換され
  ない。`sandbox=slurm` でどちらかを設定すると
  `_execute_reproduction_slurm` が *"cpu_bind and mem_bind are srun
  job-step settings; place them explicitly in reproduce.sh"* を送出し、
  ツールは失敗 attempt として記録する。binding は `reproduce.sh` に書く。
- `gpus_per_node` と `gpus_per_task` は contract 層で排他であり、count の
  無い `gpu_type` もそこでは拒否される — 素の `gpu_type` を合法にして
  いるのは skill 側の暗黙の `gpus_per_node=1` である。

詳細セマンティクスは [実行プロファイル仕様](../../reference/execution_profile.md) 参照。

**fail-loud 前提条件 (v0.8.0)**。 要求した sandbox / GPU リソースが
ホストで利用できない場合、local CPU に黙って格下げせず run が失敗する。
例外は caller には伝播しない: `run_reproduce` が捕捉して
`{"executed": false, "error": …, "failure_kind": …, "attempt_status":
"failed"}` を返し、attempt は証跡として保持される。

- `sandbox=apptainer`/`singularity`/`docker` でランタイムバイナリが無い →
  `ReproductionContractError` *"sandbox runtime is unavailable"* →
  `failure_kind: "sandbox-unavailable"`
- `sandbox=slurm` で `sbatch` が無い、または partition が解決できない →
  `RuntimeError` → `failure_kind: "scheduler-failure"`
- 矛盾した / 未対応の型付き GPU 指定 → validation / scheduler エラー。
  記録のされ方は同じ

クライアントが PATH にあるのに docker daemon が落ちている場合は前提条件で
捕捉されず、`docker run` の非ゼロ終了として表面化する。

**network policy はウィザードから設定できない**。`run_reproduce` の既定は
`network_policy="deny"` かつ `network_isolation_attested=False` で、worker は
どちらの引数も転送しない。よってウィザードから `sandbox=local` /
`slurm` を起動すると plan 時点で *"sandbox_kind=… cannot prove network
denial"* により拒否される。deny を証明できるのは container sandbox の
namespace だけなので、それ以外では MCP ツールか bridge から Stage 2 を
駆動する (両引数はそちらに存在する)。

### Step 4 — 採点設定

- **モデル** — 自由記述; 既定 `gpt-5-mini`
- **n_runs** — 1 (PaperBench 論文 §4.1)。`0` は `ARI_JUDGE_N_RUNS`、
  無ければ 1 に解決され、`[1, 100]` の範囲外はツールが拒否する
- **ネガティブコントロールをスキップ** — off 推奨; 安価な sanity check

`grade_with_simplejudge` は何よりも先に `repo_dir` から verified な
`ReproductionRunV1` を解決する。レコードが無い / 読めない / `status` が
`succeeded` でない場合は `status="failed"`、`ors_score=None` の
`GradeReportV1` になる — 黙って採点範囲を狭めて pass することはない。

### Step 5 — 実行

サマリ + ライブコスト見積もり (`POST /api/paperbench/cost-estimate`)
を表示。 *Dry run* で検証後、 *🚀 すべて実行* でジョブ投入。 各 paper
が 1 `job_id` になる。

## 監視 + 結果

ウィザードは `job_id` リストを返す。 ステータス:

```bash
curl http://localhost:8765/api/paperbench/run/<job_id>
```

結果 (ステータスが `completed` になってから):

```bash
curl http://localhost:8765/api/paperbench/run/<job_id>/results
```

`/results` は `completed` 以外に対しては
`{"error": "results not available", "status": …}` を返す。

ジョブレコードは `{registry_root}/jobs/<job_id>.json` (mode `0o600`) に
永続化されるので viz サーバ再起動をまたいで残る。再起動後も
`queued` / `running` のままのレコードは追加ステータス `interrupted` で
報告される — worker スレッドは旧プロセスと共に死んでおり、意図的に
再起動されない。

実行中の論文は `#/paperbench/results?job=<job_id>` で:
- **ライブログパネル** — ステータスを 1 回読んだあと
  `/api/paperbench/run/<job_id>/logs` に `EventSource` を張り、`done`
  イベントが来るまで `log` イベントを追記する。 各ストリームはサーバ側で
  5 分に打ち切られ、ブラウザは `Last-Event-ID` で再開する

完了後の同 URL で:
- **ルーブリックツリー** — 色分け (pass = 緑, fail = 赤) + per-leaf weight
- **カテゴリ別合格率テーブル**
- **ネガティブコントロール結果**
- **レポートダウンロード** — en/ja/zh × pdf/html/md (`POST /run/<id>/report`)

## v0.8.0 アップデート

- **Step 3 Reproduce: `container_image` フィールド追加** — 非 symlink の
  ローカル SIF、完全な Docker `sha256:<image-id>`、または
  `@sha256:<digest>` 固定 URI を受領。mutable tag と短縮 alias は拒否する
  (フィールド自身の placeholder が示すタグも含む)。
  `sandbox=docker`/`apptainer`/`singularity` で必須。`local` / `slurm`
  では無視ではなく**拒否**され、`resolve_image` が
  *"container_image is only valid for a container sandbox"* を送出するので、
  非 container sandbox に戻すときは欄を空にする。
- **GPU resource整合**: 型付き共通schedulerがcount/typeを一つのdirectiveへ
  compileし、per-task/per-nodeの矛盾は拒否する。resourceを黙ってdropしない。
- **fail-loud 前提条件**: container runtime のバイナリ / `sbatch` /
  partition が不足する場合エラーで停止し、host-local fallback はない
  (クライアントだけ PATH にあり docker daemon が落ちている場合は前提条件
  では捕捉されない)。
- **Step 4 Judge: `code_only`** — verified Stage 2 recordに対する明示的な
  scope指定。reproduce record不在時はscoreを発行せず失敗する。ウィザードに
  対応するコントロールは**無い**: `judge_config.code_only` は
  `POST /api/paperbench/run` の body を手で組んだ場合にのみ skill に届く。

## 関連

- [論文取り込み](paper_import.md)
- [クイックスタート](paperbench_quickstart.md)
- [実行プロファイル仕様](../../reference/execution_profile.md)
- [API リファレンス](../../reference/api_paperbench.md)
