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

# PaperBench API 参考

所有 endpoint 由 ARI viz 服务器 (`ari viz` /
`python -m ari.viz.server`) 在仪表盘同主机上提供。JSON body 使用
`Content-Type: application/json`。DELETE 等价操作走 POST `.../delete`
以匹配现有路由约定 (`ari-core/ari/viz/routes.py`)。

## Papers

### `GET /api/paperbench/papers`

列出注册表中每篇论文。

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

### `GET /api/paperbench/arxiv/<id>` (v0.7.2)

通过 arXiv Atom API 抓取元数据:

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

接受 legacy (cs.LG/0102030) 和 new-style (2404.14193v2) ID 格式。

### `POST /api/paperbench/papers/import`

注册新论文。Body 字段:

| 字段 | 必需 | 备注 |
|---|---|---|
| `source_type` | yes | `arxiv` \| `doi` \| `upload` \| `local` |
| `source` | yes | 标识或路径 |
| `title` | yes | 自由形式 |
| `license` | 推荐 | 服务端分类;缺失 ⇒ "unknown" |
| `authors` | no | 字符串列表 |
| `venue` / `year` / `artifact_url` | no | 可选元数据 |
| `paper_id` | no | 默认: sanitize 的 `source`;`[A-Za-z0-9._-]{1,64}` |
| `pdf_path` | no | 本地 PDF 绝对路径;复制到 `papers/<paper_id>/paper.pdf` |
| `ad_pdf_path` / `ae_pdf_path` | no | 可选工件附录 |
| `overwrite` | no | `true` ⇒ 替换重复 |

成功返回 manifest 条目,冲突 (无 overwrite) 或验证失败返回
`{error: "..."}`。

### `POST /api/paperbench/papers/<paper_id>/delete`

移除 manifest 行 + 磁盘上的论文目录。idempotent。

```json
{"deleted": true, "paper_id": "2404.14193"}
```

### `POST /api/paperbench/papers/<paper_id>/metadata`

patch manifest 条目。传任意可写字段子集 (`paper_id` 本身不可变)。
body 含 `license` 时重新分类。

### `GET /api/paperbench/papers/<paper_id>/license`

返回单一论文的结构化许可证评估:

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

提交 PaperBench run。

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

响应 (真实 launch):

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

`dry_run: true` 时不创建 job;仅返回成本估算 + `papers` (数量) +
总计。

### `GET /api/paperbench/run/<job_id>`

状态快照。字段: `status` (`queued` / `running` / `completed` /
`failed`)、`current_stage`、`progress`、`created_at`,加上原始 `configs`。

### `GET /api/paperbench/run/<job_id>/results`

`status=completed` 时返回 grader 输出;否则返回
`{error: "results not available", status: "<state>"}`。

### `GET /api/paperbench/run/<job_id>/logs` (SSE)

Server-Sent Events 流 (v0.7.2)。浏览器用 EventSource 订阅;每条 log
条目以 `event: log` push。任务结束时以 `event: done` 关闭。
`Last-Event-ID` 支持重新连接续传。

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

为完成任务生成 / 抓取审计报告。Query:
- `languages` (例如 `en,ja,zh`,默认 `en`)
- `formats` (例如 `pdf,html,md`,默认 `pdf,html,md`)
- `output_root` (可选;默认 `{registry_root}/reports/<job_id>`)

返回 renderer 结果 + `download_urls` (`<lang>/<fmt>` → path) 映射。

## 成本估算

### `POST /api/paperbench/cost-estimate`

`/api/paperbench/run` 的 body 形状减去 `paper_ids` 和 `dry_run`。返回
单论文的 wall-time + 成本预测。

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

## CORS / 认证

viz 服务器对仪表盘 endpoint 允许所有 origin (`*`),不执行认证 —
期望绑定 localhost 或在 SSH 隧道之后。**不要**在没有上游反向代理
的情况下暴露到公网接口。

## 相关

- [PaperBench GUI 指南](../guides/paperbench/paperbench_gui.md)
- [执行配置参考](execution_profile.md)
- 源码: `ari-core/ari/viz/api_paperbench.py`
