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
      "registry_dir": "<registry_root>/papers/2404.14193"
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
| `license` | 推荐 | 服务端分类;缺失 ⇒ `license: ""`、`usable: false`,note 为 "license unknown — manual review required" |
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

未知 id 不算错误:调用仍以 HTTP 200 返回
`{"deleted": false, "reason": "not found", "paper_id": "<id>"}`。

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

`rubric_config` 是唯一被校验的块:出现未知键会让整个请求失败并返回
`{"error": "unknown rubric_config fields: ..."}`。允许的键为 `model`、
`target_leaf_count`、`temperature`、`seed`、`paperbench_rubric_id`、
`max_model_calls`、`subtree_concurrency`、`provider`、`model_revision`。

`reproduce_config` 与 `judge_config` **不**校验,viz worker 只转发它认识的键。
`account`、`qos`、`reservation`、`walltime`、`gpus_per_node` 等会被 endpoint 接受
但在送往技能的路上被静默丢弃(尽管 `run_reproduce` 本身接受这些参数)——
改为通过 rubric 的 `execution_profile` 提供。

不要把 `cpu_bind` / `mem_bind` 放进 `reproduce_config`:worker 会转发它们,
SLURM 路径随后会以 "cpu_bind and mem_bind are srun job-step settings; place them
explicitly in reproduce.sh" 拒绝这次运行。

不在注册表中的 `paper_id` 会让整次 launch 中止并返回
`{"error": "paper not in registry: <paper_id>"}` —— 同一请求中更早的 id 已创建的
job 会继续运行。

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

状态快照。字段: `status`、`current_stage`、`progress`、`created_at`、
`paper_id`、`results`、`error`、`logs`,加上原始 `configs`。未知 id 返回
`{"error": "job not found", "job_id": "<id>"}`。

`status` 取 `queued`、`running`、`completed`、`failed` —— 或 `interrupted`。
每次 job 变更都会镜像写入 `{registry_root}/jobs/{job_id}.json`,因此 job 能挺过
viz 服务器重启;重启后仍写着 `queued`/`running` 的持久化记录意味着它的 worker
线程随进程一同死亡,磁盘读取器会把它报告为 `interrupted` 并附带说明性的 `error`。
worker 不会被重新拉起。

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

viz 服务器**仅同源**:只有当请求的 `Origin` 与服务器自身的 origin
(`Host` 头,或服务端口上的 loopback 形式) 一致时,才会在
`Access-Control-Allow-Origin` 中回显它。跨源请求根本拿不到 ACAO 头,
浏览器因此拒收响应。`ARI_GUI_CORS_ANY=1` 可恢复历史上无条件的 `*`,
用于页面 origin 无法与 API origin 一致的隧道 / 门户拓扑。

认证取决于绑定方式。loopback 绑定 (默认) 解析不出 token,行为与以往一致。
当 `ARI_GUI_BIND` 指向非 loopback 主机时,位于每个 `do_GET` / `do_POST` /
`do_PUT` / `do_PATCH` / `do_DELETE` 之前的单一 gate 会要求
`Authorization: Bearer <ARI_GUI_TOKEN>`,否则以 401 + 类型化 JSON body 拒绝;
`/health*` 豁免,SSE 任务日志流因 `EventSource` 无法设置头部而接受同一 token
作为 `token=` query 参数。远程绑定但未设置 `ARI_GUI_TOKEN` 时会生成并打印一个
token,而不是无认证启动;`ARI_GUI_AUTH=0` 关闭该 gate。**不要**在没有上游反向
代理的情况下暴露到公网接口。

## 相关

- [PaperBench GUI 指南](../guides/paperbench/paperbench_gui.md)
- [执行配置参考](execution_profile.md)
- 源码: `ari-core/ari/viz/api_paperbench.py`
