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

### `POST /api/paperbench/run/<job_id>/report`

同一个 handler,供更愿意发送 body 而不是 query string 的调用方使用;
仪表盘的结果视图用它来实现 EN / JA / ZH 三个报告按钮。

```json
{"languages": ["en"], "formats": ["pdf", "html", "md"]}
```

这里的 `languages` 与 `formats` 是真正的 JSON 数组 —— 逗号切分只是 GET
query string 的性质。`output_root` 的读取方式相同,格式正确的 body 返回的
内容与 GET 形式完全一致。

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

## Bridge 契约 (in-process Python 接口)

对于在同一进程内运行的调用方 (编排器、dogfood 脚本、自定义流水线),
`ari-skill-paper-re/src/_paperbench_bridge.py` 暴露三个仅限关键字参数的
async callable,对应 PaperBench 的三阶段协议 (arXiv:2504.01848 §3)。
三者共享同一套
`(paper_md, work_dir 或 submission_dir, model, …)` 词汇,因而可以直接串联。

| Stage | 函数 | 包装对象 |
|---|---|---|
| 1 — Agent rollout | `rollout_submission(paper_md, work_dir, agent_model, sandbox_kind, container_image, iterative_agent, env, agent_env_path, forbid_host_filesystem, blacklist_urls, time_limit_sec, …)` | `_replicator_agent.run_replicator_agent` (vendor 的 BasicAgent / IterativeAgent) |
| 2 — Reproduction | `reproduce_submission(submission_dir, sandbox_kind, container_image, time_limit_sec, network_policy, network_isolation_attested, partition, gpus_per_task, gpu_type, memory_gb_per_node, exclusive, extra_sbatch_args, capture_tarball, tarball_dir)` | `server.run_reproduce` (类型化 HPC handle,或分派到宿主沙箱;已弃用的 `extra_sbatch_args` 读取器现在只接受 `--account=` / `--qos=` / `--reservation=` / `--hint=`,其余一律抛出异常) |
| 3 — Grading | `judge_submission(paper_md, rubric, submission_dir, reproduce_log, judge_model, paper_audit_mode, code_only, …)` | 直接使用 vendor `SimpleJudge` |

bridge 内建的 vendor 保真行为:

- **submission 根目录解析 (v0.8.0)** —— 当 agent 把自包含仓库建在嵌套的
  `submission/` 下时,`reproduce_submission` 与 `judge_submission` 会下沉
  到该目录 (workspace 把 vendor 的 `/home/submission` 呈现为相对
  workspace 的 `submission/`,因此按提示行事的 agent 会多嵌套一层)。
  复现与评分随后在 `reproduce.sh` 与其源码同处一地的那一侧运行,与 vendor
  reproducer 先 cd 进 submission 的语义一致;顶层那份被孤立的
  `reproduce.sh` 副本会被忽略。正是这一点挡住了
  `src/…: No such file or directory` 构建失败——否则它会把 Code Execution /
  Result Analysis 的每个 leaf 都归零。
- **apply_patch 命令对等 (v0.8.0)** —— 宿主侧的 `LocalComputer` 把 vendor
  自带的 `apply_patch.py` 放到 PATH 上 (同时提供 `apply_patch` 与
  `applypatch` 两个名字),镜像 vendor Docker 镜像里的
  `/bin/apply_patch`。gpt-5 / codex 类 agent 会条件反射地用
  `apply_patch <<'PATCH' … PATCH` 编辑文件;没有它就会以 `command not
  found` 失败并浪费 tool-call 预算。Apptainer SIF 本身已带该命令,因此这个
  shim 只用于宿主沙箱。
- **不可变的容器身份** —— 本地非符号链接 SIF 会被 hash;Docker 接受完整的
  `sha256:<image-id>` 或 `name@sha256:<digest>`;远程 Apptainer 引用必须带
  `@sha256:<digest>`。可变 tag 以及从前的 `pb-env` / `pb-reproducer`
  别名一律 fail closed。
- **agent.env 自动加载** —— `agent_env_path` 未设置时,依次自动发现
  `$ARI_AGENT_ENV_PATH` 与 `~/.ari/agent.env`。调用进程 env 中的
  `HF_TOKEN` 会被自动转发给 agent。
- **forbid_host_filesystem** —— 拒绝 `sandbox_kind=local/slurm` 组合
  (宿主文件系统泄漏面)。默认 False,保留开发工作流。
- **blacklist_urls** —— 在 agent 的指令提示词前面插入一段
  `FORBIDDEN URLS` 块,并同时导出 `ARI_BLACKLIST_URLS` 环境变量,使下游
  工具包装层能够拒绝。
- **没有会改写源码的 salvage** —— vendor 的
  `reproduce_on_computer_with_salvaging` 重试 (会在重跑前改写 submission
  的环境) 在 bridge 侧没有等价物;`salvage_retries` / `retry_threshold_sec`
  不是 `reproduce_submission` 的参数,而
  `test_reproduce_submission_signature_includes_tarball_not_unsafe_salvage`
  断言 `salvage_retries` 的缺席。失败的复现通过用同一 plan 再次调用
  `reproduce_submission` 来重试;这会追加一次不可变的链接 attempt,而不是
  改写 `reproduce.sh`。
- **capture_tarball** (默认 True) —— 把带时间戳的
  `submission_executed_<UTC>.tar.gz` 写在*被执行的* submission 旁边,即
  私有 attempt 树内 (而不是调用方 `submission_dir` 的旁边),除非用
  `tarball_dir` 覆盖目标目录;返回值会增加 `executed_tarball`、
  `executed_tarball_digest` 和 `executed_tarball_size_bytes`。capture
  失败不致命:它会被记录到日志,并追加进结果的 `warnings` 列表。
- **code_only** —— 为 True 时,通过 vendor 的 `TaskNode.code_only` 归约
  (vendor `paperbench/grade.py:109-112`) 把*评分标准树*剪枝到
  `Code Development` leaf。它用于 Stage 2 被刻意跳过的情形,避免
  Code Execution / Result Analysis 的 leaf 对着空 submission 被评分。它不能
  替代复现记录:`grade_with_simplejudge` 仍然要求一份 `status ==
  "succeeded"` 的已验证 `ReproductionRunV1`,否则返回 `status: "failed"`
  且 `ors_score: null` 的报告。
- **paper_audit_mode** —— 把 vendor 的 `TASK_CATEGORY_QUESTIONS` patch 成
  paper-audit 措辞。与 `code_only` 互斥。

高声失败的前置条件 (没有 host-local 降级)。它们都不会以异常的形式到达调用方:
`run_reproduce` 会捕获失败,将其记录为一次不可变的失败 attempt,并返回带
`executed: false`、`error` 和 `failure_kind` (`sandbox-unavailable`、
`scheduler-failure`、`network-policy`) 的 dict —— 或者,当 plan 在 attempt
存在之前就被拒绝时,返回
`{"executed": false, "error": "reproduction plan rejected: ..."}`。

| 条件 | 处置 |
|---|---|
| `sandbox_kind=docker/apptainer/singularity` 但 runtime 二进制不在 `PATH` 上 (启动时用 `which` 检查——对显式的 `docker` 请求从不去 probe 守护进程本身) | 安装该 runtime,或改选另一种已审查的沙箱 |
| `sandbox_kind=docker/apptainer/singularity` 却既无 `container_image` 也无 `ARI_PHASE1_DOCKER_IMAGE` / `ARI_PHASE1_APPTAINER_IMAGE` | 提供一个不可变镜像;plan 会以 "requires an immutable container image" 被拒 |
| 未以不可变方式 pin 的容器镜像 (可变 Docker tag、不带 `@sha256:` 的远程 Apptainer 引用、符号链接 SIF) | 把它 pin 住;见上文「不可变的容器身份」 |
| `sandbox_kind=slurm` 但 `sbatch` 缺失,或解析不出分区 | 配置调度器 / 分区 |
| 默认 `network_policy="deny"` 下的 `sandbox_kind=local`/`slurm` | 非容器基底无法证明网络已被拒绝:显式传 `network_policy="inherit"`、提供 `network_isolation_attested=True`,或改在容器中运行 |
| 向 SLURM 复现传入 `cpu_bind` / `mem_bind` | 把绑定写进 `reproduce.sh`;调度器路径会以 srun job-step 设置为由拒绝它们 |
| 所选分区不支持的 GPU 请求 | 修正 GRES / 改选兼容的分区;不做静默降级 |

## 相关

- [PaperBench GUI 指南](../guides/paperbench/paperbench_gui.md)
- [执行配置参考](execution_profile.md)
- 源码: `ari-core/ari/viz/api_paperbench.py`
