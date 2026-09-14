---
sources:
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-skill-paper-re/src/_paperbench_bridge.py
    role: implementation
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/src/sandbox.py
    role: implementation
  - path: ari-skill-paper-re/src/_compute/computer.py
    role: implementation
last_verified: 2026-08-16
---

# PaperBench API リファレンス

全 endpoint はダッシュボードと同ホスト上の ARI viz サーバ
(`ari viz` / `python -m ari.viz.server`) で提供。 JSON body は
`Content-Type: application/json`。 DELETE 同等の操作は既存の routing
規約に合わせて POST `.../delete` を使う (`ari-core/ari/viz/routes.py`)。

## Papers

### `GET /api/paperbench/papers`

レジストリ内の全論文を一覧。

```json
{
  "papers": [
    {
      "paper_id": "2404.14193",
      "title": "LLAMP: assessing latency tolerance",
      "license": "cc by 4.0",
      "license_assessment": {"usable": true, "note": "permissive — usable"},
      "source_type": "arxiv",
      "source": "2404.14193",
      "imported_at": "2026-05-13T...",
      "registry_dir": "<registry_root>/papers/2404.14193"
    }
  ]
}
```

### `GET /api/paperbench/arxiv/<id>`

arXiv Atom API 経由でメタデータを取得 (v0.7.2):

```json
{
  "arxiv_id": "2404.14193",
  "title": "LLAMP: ...",
  "authors": ["Alice", "Bob"],
  "year": 2024,
  "license": "arXiv non-exclusive",
  "license_assessment": {"usable": true, "note": "..."},
  "pdf_url": "https://arxiv.org/pdf/2404.14193v1.pdf",
  "abs_url": "https://arxiv.org/abs/2404.14193"
}
```

レガシー (cs.LG/0102030) と new-style (2404.14193v2) 両方の ID 形式を
受け付ける。

### `POST /api/paperbench/papers/import`

新規論文を登録。 Body フィールド:

| フィールド | 必須 | 備考 |
|---|---|---|
| `source_type` | yes | `arxiv` \| `doi` \| `upload` \| `local` |
| `source` | yes | 識別子またはパス |
| `title` | yes | フリーフォーム |
| `license` | 推奨 | サーバ側分類; 欠如 ⇒ `license: ""` に `usable: false` と note `"license unknown — manual review required"` |
| `authors` | no | 文字列リスト |
| `venue` / `year` / `artifact_url` | no | 任意メタデータ |
| `paper_id` | no | 既定: sanitize された `source`; `[A-Za-z0-9._-]{1,64}` |
| `pdf_path` | no | ローカル PDF の絶対パス; `papers/<paper_id>/paper.pdf` にコピー |
| `ad_pdf_path` / `ae_pdf_path` | no | 任意のアーティファクト付録 |
| `overwrite` | no | `true` で重複置換 |

成功時は manifest エントリ、 衝突 (overwrite なし) または検証失敗時は
`{error: "..."}` を返す。

### `POST /api/paperbench/papers/<paper_id>/delete`

manifest 行とディスク上の論文ディレクトリを削除。 idempotent。

```json
{"deleted": true, "paper_id": "2404.14193"}
```

未知の id もエラーにはならない。 HTTP 200 のまま
`{"deleted": false, "reason": "not found", "paper_id": "<id>"}` を返す。

### `POST /api/paperbench/papers/<paper_id>/metadata`

manifest エントリにパッチ。 任意のフィールド (paper_id 不変) を渡す。
body に `license` が含まれる場合は再分類。

### `GET /api/paperbench/papers/<paper_id>/license`

単一論文のライセンス評価を返す:

```json
{
  "license": "cc by 4.0",
  "permissive": true,
  "modifiable": true,
  "redistributable": true,
  "usable": true,
  "note": "permissive license — ari may use freely"
}
```

## Runs

### `POST /api/paperbench/run`

PaperBench run を投入。

```json
{
  "paper_ids": ["2404.14193"],
  "rubric_config":    {"model": "gemini/gemini-2.5-pro"},
  "reproduce_config": {
    "model": "gpt-5-mini",
    "time_limit_sec": 43200,
    "sandbox_kind": "slurm",
    "partition": "large",
    "nodes": 4,
    "ntasks": 32,
    "ntasks_per_node": 8,
    "exclusive": true,
    "gpus_per_task": 1,
    "gpu_type": "v100",
    "memory_gb_per_node": 256,
    "constraint": "skylake"
  },
  "judge_config":     {"model": "gpt-5-mini", "n_runs": 1},
  "dry_run": false
}
```

検証されるのは `rubric_config` だけ。 未知のキーがあるとリクエスト全体が
`{"error": "unknown rubric_config fields: ..."}` で失敗する。 受け付ける
キーは `model`、 `target_leaf_count`、 `temperature`、 `seed`、
`paperbench_rubric_id`、 `max_model_calls`、 `subtree_concurrency`、
`provider`、 `model_revision` の 9 個。

`reproduce_config` と `judge_config` は検証されず、 viz worker が知って
いるキーだけが skill へ転送される。 `account` / `qos` / `reservation` /
`walltime` / `gpus_per_node` などは endpoint には通るが skill へ渡る途中で
黙って落ちる (`run_reproduce` 自体は引数として持っている) ので、
ルーブリックの `execution_profile` 経由で指定すること。

`cpu_bind` / `mem_bind` は `reproduce_config` に入れないこと: worker は
これらを転送し、 SLURM 経路が「cpu_bind and mem_bind are srun job-step
settings; place them explicitly in reproduce.sh」で run を拒否する。

レジストリに無い `paper_id` があると launch 全体が
`{"error": "paper not in registry: <paper_id>"}` で中断する — 同一
リクエスト内で先に作成済みの job はそのまま走り続ける。

レスポンス (実 launch):

```json
{
  "dry_run": false,
  "job_ids": ["abc123..."],
  "estimated_cost": {
    "wall_time_sec": 43560,
    "llm_cost_usd": 2.55,
    "breakdown": { ... }
  }
}
```

`dry_run: true` のときは job 作成なしでコスト見積もりのみ返す。

### `GET /api/paperbench/run/<job_id>`

ステータススナップショット。 フィールド: `status`、 `current_stage`、
`progress`、 `created_at`、 `paper_id`、 `results`、 `error`、 `logs`、
加えて元の `configs`。 未知の id には
`{"error": "job not found", "job_id": "<id>"}` を返す。

`status` は `queued` / `running` / `completed` / `failed`、 加えて
`interrupted` の 5 種。 job の更新は毎回
`{registry_root}/jobs/{job_id}.json` にミラーされるので viz サーバ再起動
後も job は残るが、 再起動後もなお `queued`/`running` のままの永続レコード
はその worker スレッドがプロセスと共に死んだことを意味し、 ディスク読み出し
側が説明用の `error` を付けて `interrupted` として報告する。 worker が
再起動されることはない。

### `GET /api/paperbench/run/<job_id>/results`

`status=completed` のとき grader 出力を返す。 それ以外は
`{error: "results not available", status: "<state>"}`。

### `GET /api/paperbench/run/<job_id>/logs` (SSE)

Server-Sent Events ストリーム (v0.7.2)。 ブラウザ EventSource で
購読すると、 各 log エントリが `event: log` で push される。 job が
終了すると `event: done` でクローズ。 Last-Event-ID で reconnect 再開。

```
event: log
id: 0
data: {"ts":"2026-05-13T05:57:00Z","level":"info","msg":"rubric starting"}

event: log
id: 1
data: {"ts":"2026-05-13T05:57:01Z","level":"info","msg":"..."}

event: done
data: {"status":"completed"}
```

### `GET /api/paperbench/run/<job_id>/report` (v0.7.2)

完了済 job に対して監査レポートを生成 / フェッチ。 Query:
- `languages` (例: `en,ja,zh`、 既定 `en`)
- `formats` (例: `pdf,html,md`、 既定 `pdf,html,md`)
- `output_root` (任意; 既定 `{registry_root}/reports/<job_id>`)

返り値は renderer 結果 + `download_urls` (`<lang>/<fmt>` → path) マップ。

### `POST /api/paperbench/run/<job_id>/report`

query string ではなく body を送りたい呼び出し側のための、 同じハンドラ。
ダッシュボードの結果ビューは EN / JA / ZH のレポートボタンでこちらを使う。

```json
{"languages": ["en"], "formats": ["pdf", "html", "md"]}
```

ここでの `languages` と `formats` は本物の JSON 配列である —
カンマ分割は GET の query string 側だけの性質。 `output_root` の読み方も
同じで、 妥当な body に対しては GET 形式とまったく同じものを返す。

## コスト見積もり

### `POST /api/paperbench/cost-estimate`

`/api/paperbench/run` から `paper_ids` と `dry_run` を除いた body
形状。 1 論文あたりの wall-time + コスト予測を返す。

```json
{
  "wall_time_sec": 43560,
  "llm_cost_usd": 2.55,
  "breakdown": {
    "rubric":    {"wall_time_sec": 300, "cost_usd": 0.45},
    "reproduce": {"wall_time_sec": 43200, "cost_usd": 2.0},
    "judge":     {"wall_time_sec": 60, "cost_usd": 0.10}
  }
}
```

## CORS / 認証

viz サーバは **same-origin のみ**: リクエストの `Origin` が
サーバ自身の origin (`Host` ヘッダ、 またはサーバポート上の loopback 形式)
に一致するときだけ `Access-Control-Allow-Origin` にエコーされる。
cross-origin リクエストには ACAO ヘッダが一切付かないのでブラウザが
レスポンスを拒否する。 ページ origin が API origin に一致し得ない
トンネル / ポータル構成向けに、 `ARI_GUI_CORS_ANY=1` で従来の無条件 `*`
に戻せる。

認証は bind 次第。 loopback bind (既定) はトークンなしで従来どおり。
`ARI_GUI_BIND` が非 loopback ホストを指す場合、 すべての `do_GET` /
`do_POST` / `do_PUT` / `do_PATCH` / `do_DELETE` の手前に置かれた単一の
ゲートが `Authorization: Bearer <ARI_GUI_TOKEN>` を要求し、 無ければ
型付き JSON body 付きの 401 を返す。 `/health*` は免除、 SSE の job ログ
ストリームは `EventSource` がヘッダを設定できないため同じトークンを
`token=` クエリパラメータとして受け付ける。 リモート bind で
`ARI_GUI_TOKEN` が未設定の場合は未認証で起動せずトークンを生成して表示する。
`ARI_GUI_AUTH=0` でゲートを無効化できる。 上流リバースプロキシ無しで
public interface に晒さないこと。

## Bridge 契約 (in-process Python インターフェース)

in-process で動く呼び出し側 (オーケストレータ、 dogfood スクリプト、
独自パイプライン) 向けに、 `ari-skill-paper-re/src/_paperbench_bridge.py`
は PaperBench の 3 段プロトコル (arXiv:2504.01848 §3) に対応する 3 つの
キーワード専用 async callable を公開する。 3 つとも
`(paper_md, work_dir または submission_dir, model, …)` という同じ語彙を
共有するので、 そのまま連鎖できる。

| Stage | 関数 | ラップ対象 |
|---|---|---|
| 1 — Agent rollout | `rollout_submission(paper_md, work_dir, agent_model, sandbox_kind, container_image, iterative_agent, env, agent_env_path, forbid_host_filesystem, blacklist_urls, time_limit_sec, …)` | `_replicator_agent.run_replicator_agent` (vendor の BasicAgent / IterativeAgent) |
| 2 — Reproduction | `reproduce_submission(submission_dir, sandbox_kind, container_image, time_limit_sec, network_policy, network_isolation_attested, partition, gpus_per_task, gpu_type, memory_gb_per_node, exclusive, extra_sbatch_args, capture_tarball, tarball_dir)` | `server.run_reproduce` (型付き HPC ハンドル、 またはホストサンドボックスへのディスパッチ; 非推奨となった `extra_sbatch_args` リーダが受け付けるのは `--account=` / `--qos=` / `--reservation=` / `--hint=` だけで、 それ以外は例外を送出する) |
| 3 — Grading | `judge_submission(paper_md, rubric, submission_dir, reproduce_log, judge_model, paper_audit_mode, code_only, …)` | vendor `SimpleJudge` を直接 |

bridge に組み込まれた vendor 忠実性のふるまい:

- **submission ルートの解決 (v0.8.0)** — エージェントが自己完結リポジトリ
  を入れ子の `submission/` 以下に作った場合、 `reproduce_submission` と
  `judge_submission` はそこへ降りる (ワークスペースは vendor の
  `/home/submission` をワークスペース相対の `submission/` として提示する
  ので、 プロンプトに従ったエージェントは 1 段入れ子にする)。 再現と採点は
  `reproduce.sh` がそのソースと同じ場所に置かれている側で走り、 vendor の
  reproducer が submission へ cd する意味論と一致する; トップレベルに残った
  孤立した `reproduce.sh` のコピーは無視される。 これが、 放置すると Code
  Execution / Result Analysis の leaf をすべて 0 にする
  `src/…: No such file or directory` ビルド失敗を止めている。
- **apply_patch コマンドの同等性 (v0.8.0)** — ホスト側の `LocalComputer`
  が vendor 自身の `apply_patch.py` を PATH 上に (`apply_patch` と
  `applypatch` の両方の名前で) 公開し、 vendor Docker イメージの
  `/bin/apply_patch` を模倣する。 gpt-5 / codex 系エージェントは反射的に
  `apply_patch <<'PATCH' … PATCH` でファイルを編集するため、 これが無いと
  `command not found` で失敗し tool-call 予算を浪費する。 Apptainer SIF は
  既にこのコマンドを持つので、 このシムはホストサンドボックス専用。
- **不変なコンテナ同一性** — ローカルの非シンボリックリンク SIF は
  ハッシュされる; Docker は完全な `sha256:<image-id>` または
  `name@sha256:<digest>` を受け付ける; リモートの Apptainer 参照は
  `@sha256:<digest>` を要求する。 可変タグと、 かつての `pb-env` /
  `pb-reproducer` エイリアスは fail closed。
- **agent.env の自動読み込み** — `agent_env_path` 未指定のとき、
  `$ARI_AGENT_ENV_PATH`、 次に `~/.ari/agent.env` を自動探索する。
  呼び出しプロセスの env にある `HF_TOKEN` は自動でエージェントへ転送される。
- **forbid_host_filesystem** — `sandbox_kind=local/slurm` の組み合わせ
  (ホスト FS 漏洩面) を拒否する。 既定の False は開発ワークフローを保つ。
- **blacklist_urls** — エージェントの指示プロンプト先頭に
  `FORBIDDEN URLS` ブロックを差し込み、 併せて `ARI_BLACKLIST_URLS`
  環境変数を export して下流の tool ラッパが拒否できるようにする。
- **ソースを書き換える salvage は無い** — vendor の
  `reproduce_on_computer_with_salvaging` リトライ (再実行の前に submission
  の環境を書き換える) に bridge 側の等価物は無い;
  `salvage_retries` / `retry_threshold_sec` は `reproduce_submission` の
  パラメータではなく、 `test_reproduce_submission_signature_includes_tarball_not_unsafe_salvage`
  が `salvage_retries` の不在を主張する。 失敗した再現は同じ plan で
  `reproduce_submission` をもう一度呼んでリトライする。 これは
  `reproduce.sh` を書き換えるのではなく、 不変なリンク済み attempt を
  追加する。
- **capture_tarball** (既定 True) — タイムスタンプ付きの
  `submission_executed_<UTC>.tar.gz` を、 *実行された* submission の隣、
  すなわち非公開の attempt ツリー内に書き出す (呼び出し側の
  `submission_dir` の隣ではない)。 `tarball_dir` を渡すと書き出し先を
  上書きできる。 返り値には `executed_tarball`、
  `executed_tarball_digest`、 `executed_tarball_size_bytes` が加わる。
  capture の失敗は致命的ではなく、 ログに出したうえで結果の `warnings`
  リストへ追記される。
- **code_only** — True のとき、 vendor の `TaskNode.code_only`
  リダクション (vendor `paperbench/grade.py:109-112`) で *ルーブリック
  ツリー* を `Code Development` leaf へ刈り込む。 Stage 2 を意図的に
  飛ばした場合のためのもので、 Code Execution / Result Analysis の leaf が
  空の submission に対して採点されないようにする。 再現記録の代わりには
  ならない: `grade_with_simplejudge` は依然として `status == "succeeded"`
  の検証済み `ReproductionRunV1` を要求し、 無ければ `status: "failed"` と
  `ors_score: null` のレポートを返す。
- **paper_audit_mode** — vendor の `TASK_CATEGORY_QUESTIONS` を
  paper-audit 向けの言い回しにパッチする。 `code_only` とは排他。

fail-loud な前提条件 (host-local へのダウングレードは無い)。 これらが
呼び出し側に例外として届くことはない: `run_reproduce` が失敗を捕捉し、
不変な失敗 attempt として記録し、 `executed: false`、 `error`、
`failure_kind` (`sandbox-unavailable` / `scheduler-failure` /
`network-policy`) を載せた dict を返す — attempt が存在する前に plan が
拒否された場合は `{"executed": false, "error": "reproduction plan
rejected: ..."}` を返す。

| 条件 | 対処 |
|---|---|
| `sandbox_kind=docker/apptainer/singularity` だが runtime バイナリが `PATH` に無い (launch 時に `which` で確認 — 明示的な `docker` 指定ではデーモン自体を probe しない) | runtime を入れるか、 別のレビュー済みサンドボックスを選ぶ |
| `sandbox_kind=docker/apptainer/singularity` で `container_image` も `ARI_PHASE1_DOCKER_IMAGE` / `ARI_PHASE1_APPTAINER_IMAGE` も無い | 不変なイメージを与える; plan は "requires an immutable container image" で拒否される |
| 不変に pin されていないコンテナイメージ (可変な Docker タグ、 `@sha256:` 無しのリモート Apptainer 参照、 シンボリックリンクの SIF) | pin する; 上記「不変なコンテナ同一性」を参照 |
| `sandbox_kind=slurm` だが `sbatch` が無い、 またはパーティションが解決できない | スケジューラ / パーティションを設定する |
| 既定の `network_policy="deny"` のまま `sandbox_kind=local`/`slurm` | 非コンテナ基盤はネットワーク遮断を証明できない: `network_policy="inherit"` を明示するか、 `network_isolation_attested=True` を渡すか、 コンテナで走らせる |
| SLURM 再現へ `cpu_bind` / `mem_bind` を渡した | バインドは `reproduce.sh` に書く; スケジューラ経路はこれらを srun の job-step 設定として拒否する |
| 選んだパーティションが対応していない GPU 要求 | GRES を直すか互換のあるパーティションを選ぶ; 黙ったダウングレードは無い |

## 関連

- [PaperBench GUI ガイド](../guides/paperbench/paperbench_gui.md)
- [実行プロファイル仕様](execution_profile.md)
- ソース: `ari-core/ari/viz/api_paperbench.py`
