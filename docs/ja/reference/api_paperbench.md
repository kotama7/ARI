---
sources:
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-skill-paper-re/src/_paperbench_bridge.py
    role: implementation
  - path: ari-skill-paper-re/src/server.py
    role: implementation
last_verified: 2026-05-25
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
      "registry_dir": "/home/.../paper_registry/papers/2404.14193"
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
| `license` | 推奨 | サーバ側分類; 欠如 ⇒ "unknown" |
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
  "rubric_config":    {"model": "gemini/gemini-2.5-pro", "two_stage": true},
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
    "constraint": "skylake",
    "cpu_bind": "cores",
    "extra_sbatch_args": ["--account=projX"]
  },
  "judge_config":     {"model": "gpt-5-mini", "n_runs": 1},
  "dry_run": false
}
```

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

ステータススナップショット。 フィールド: `status` (`queued` /
`running` / `completed` / `failed`)、 `current_stage`、 `progress`、
`created_at`、 加えて元の `configs`。

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

viz サーバはダッシュボード endpoint で全 origin (`*`) を許可、 認証
なし — localhost バインド or SSH トンネル背後での利用を想定。 上流
リバースプロキシ無しで public interface に晒さないこと。

## 関連

- [PaperBench GUI ガイド](../guides/paperbench/paperbench_gui.md)
- [実行プロファイル仕様](execution_profile.md)
- ソース: `ari-core/ari/viz/api_paperbench.py`
