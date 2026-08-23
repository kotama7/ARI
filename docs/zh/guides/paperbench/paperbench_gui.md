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

# PaperBench GUI 指南

仪表盘 **📚 PaperBench** 侧栏入口下。路由都是 hash 路由
(`#/paperbench…`);只有注册表有导航入口,其余三个只能在页面内到达:

- `#/paperbench` — 论文注册表列表
- `#/paperbench/import` — 导入表单
- `#/paperbench/run` — 5 步执行向导
- `#/paperbench/results?job=<job_id>` — 结果视图 (评分单树 + 实时日志 +
  报告下载)

## 论文注册表 (`#/paperbench`)

显示 `{workspace_root}/paper_registry/manifest.jsonl` 内全部论文。根目录
在设置了 `ARI_PAPER_REGISTRY_DIR` 时取该值,否则取
`PathManager.from_env().paper_registry_root` (以 workspace 为根的目录;
没有活动 checkpoint 时回退到 `./paper_registry`)。它**不在** `~/.ari/`
之下 — v0.5+ 的 ARI 不再维护全局的用户级数据目录。每行:

- ☑ 复选框 — 多选。该选择**不会**带进向导,Step 1 会重新询问
- `paper_id` — FS-safe 的 slug
- 标题
- 许可证徽章 — 评估结果为 `usable` (宽松 AND 可再分发 AND 非
  non-commercial) 时显示绿色 ✅,否则显示红色 ⚠。悬停查看详细评估
- 来源 — `arxiv:2404.14193`, `doi:10.1109/...` 等
- 删除 — `POST /api/paperbench/papers/<paper_id>/delete`;同时移除
  manifest 行与论文目录

顶部操作栏:
- **📥 导入论文** → `#/paperbench/import`
- **🚀 运行 PaperBench (N)** → `#/paperbench/run` (N≥1 时可用)
- **刷新** — 重新读取 manifest

## 论文导入 (`#/paperbench/import`)

v0.7.2 的最小表单:

| 字段 | 备注 |
|---|---|
| 来源类型 | `arxiv` \| `doi` \| `upload` \| `local` |
| 来源标识 | arXiv ID (`2404.14193`)、DOI、PDF 路径 |
| PDF 文件 | 仅 `source_type=upload` 时出现;经 `POST /api/upload` 暂存 |
| 标题 | 必填 |
| 作者 | 以逗号**或**分号分隔 |
| 会议 / 年份 | 可选 |
| 许可证 | 自由形式; 服务端分类 |
| 工件 URL | 可选代码库 URL |

arXiv 元数据自动抓取已经落地: `source_type=arxiv` 时出现
**「↓ 抓取元数据」按钮**,触发 `GET /api/paperbench/arxiv/<id>` 调用
arXiv Atom API 并自动填充 title / authors / year / license
(`"arXiv non-exclusive"`)。但它**不抓 PDF** — 响应里带回一个 `pdf_url`,
没有任何代码去下载它。由于 `papers/<paper_id>/paper.pdf` 缺失时运行
worker 会中止,只走 arXiv 导入的论文仍需手工附上 PDF。

许可证输入框下方的徽章**不是**服务端判定: 它是客户端一个乐观的正则
(`/^cc(\s|-)by(\s|-)?(4\.?0)?$|^(mit|apache|bsd|arxiv)/i`),只是近似
`_classify_license` — 例如 `CC0` 在表单里显示 ⚠,而服务端返回 `usable`。
权威的 `license_assessment` 随 import 响应返回,注册表行渲染的就是它。

- ✅ "Permissive license — usable" — MIT, Apache-2.0, BSD-2/3-Clause,
  CC0, CC BY, CC BY-SA, arXiv 非独占
- ⚠ "License may require review" — 其他 (含未知字符串),**以及
  CC BY-NC** — `_classify_license` 判定它 permissive 但 non-commercial,
  因此 NOT usable

## 运行向导 (`#/paperbench/run`)

5 步,所有配置汇聚为单一 `POST /api/paperbench/run` body。

### Step 1 — 论文选择

从注册表多选。选中 ≥1 篇前 Next 不可用。

### Step 2 — 评分单配置

- **模型** — 自由文本输入框 (非下拉),默认 `gemini/gemini-2.5-pro`。
  LiteLLM 能识别的任何模型都可以
- **目标叶节点数** — `0` (从论文长度自动: `words // 75`,钳制到
  `[50, 400]`)

不存在「两阶段」开关。生成器无条件是 `hierarchical-v2` (skeleton pass +
并行 subtree pass);它的 `max_model_calls` (64) 与 `subtree_concurrency`
(4) 虽被 `POST /api/paperbench/run` 接受,但向导里没有对应字段。

### Step 3 — 再现配置

顶部表单:
- **模型** — 再现代理模型 (默认 `gpt-5-mini`)
- **时间上限** — 秒数;默认 12 h (PaperBench 论文 §5.2)
- **沙箱** — `auto` / `slurm` / `local` / `apptainer` / `docker`
- **分区** — 仅 `slurm` 时有意义

**执行配置覆盖** (v0.7.2 的焦点):

13 字段网格允许覆盖 rubric 内 execution_profile hint。字段始终从
`0` / `""` 起步 — 向导不做任何预填。与评分单 `execution_profile` 的合并
发生在服务端的 `run_reproduce` 里: 非零的调用方值胜出,为零/为空则落回
评分单 hint。

| 字段 | 类型 | SLURM 标志 |
|---|---|---|
| nodes | int | `--nodes` (默认 1) |
| ntasks | int | `--ntasks` — 始终发出;默认 `ntasks_per_node × nodes`,否则 1 |
| ntasks_per_node | int | `--ntasks-per-node` |
| gpus_per_task | int | `--gpus-per-task=[<gpu_type>:]<n>` |
| memory_gb_per_node | int | `--mem=<n×1024>M` |
| exclusive | bool | `--exclusive` |
| gpu_type | str | 作为 GPU 数量的前缀;单独给出 (无数量) 时隐含 `gpus_per_node=1` → `--gres=gpu:<type>:1` |
| constraint | str | `--constraint` |
| cpu_bind | str | **`sandbox=slurm` 下被拒绝** — 见下 |
| mem_bind | str | **`sandbox=slurm` 下被拒绝** — 见下 |
| hint | str | `--hint`;只有 `compute_bound`、`memory_bound`、`multithread`、`nomultithread` 通过校验 |
| nodelist | str | `--nodelist` |
| extra_sbatch_args | str (空格分隔) | **不是** pass-through: 只接受 `--account=`、`--qos=`、`--reservation=`、`--hint=` 并翻译为 typed 字段;出现其他条目则该次运行失败 |

该网格里的两个陷阱:

- `cpu_bind` / `mem_bind` 不会被翻译成 `srun --cpu-bind` /
  `--mem-bind`。在 `sandbox=slurm` 下设置任一个,都会让
  `_execute_reproduction_slurm` 抛出 *"cpu_bind and mem_bind are srun
  job-step settings; place them explicitly in reproduce.sh"*,工具把它
  记为一次失败的 attempt。请把绑定写进 `reproduce.sh`。
- `gpus_per_node` 与 `gpus_per_task` 在契约层互斥,且在那里不接受没有
  任何数量的 `gpu_type` — 是 skill 隐含的 `gpus_per_node=1` 让裸
  `gpu_type` 合法。

完整语义见 [执行配置参考](../../reference/execution_profile.md)。

**向导不暴露 network policy。** `run_reproduce` 默认
`network_policy="deny"` 且 `network_isolation_attested=False`,而 worker
两个参数都不转发,因此以 `sandbox=local` 或 `slurm` 从向导启动的运行会在
plan 阶段以 *"sandbox_kind=… cannot prove network denial"* 被拒绝。只有
容器 sandbox 能通过其 namespace 证明拒网;否则请从 MCP 工具或 bridge
驱动 Stage 2 — 那里才有这两个参数。

### Step 4 — 判分配置

- **模型** — 自由文本;默认 `gpt-5-mini`
- **n_runs** — 1 (PaperBench 论文 §4.1)。`0` 解析为 `ARI_JUDGE_N_RUNS`,
  否则为 1;工具拒绝 `[1, 100]` 之外的任何值
- **跳过负向控制** — 建议关;这是廉价的 sanity check

`grade_with_simplejudge` 会先从 `repo_dir` 解析出一份经 digest 验证的
`ReproductionRunV1`。没有记录、记录不可读,或记录的 `status` 不是
`succeeded` 时,产出的 `GradeReportV1` 带 `status="failed"` 与
`ors_score=None` — 绝不会静默改小评分范围后判通过。

### Step 5 — 启动

显示汇总 + 实时成本估算 (`POST /api/paperbench/cost-estimate`)。
*Dry run* 验证后,*🚀 全部启动* 入队。每篇论文 1 个 `job_id`。

## 监控 + 结果

向导返回 `job_id` 列表。状态:

```bash
curl http://localhost:8765/api/paperbench/run/<job_id>
```

运行中的论文,在 `#/paperbench/results?job=<job_id>`: 页面先读一次状态,
然后对 `/api/paperbench/run/<job_id>/logs` 打开一个 `EventSource`,不断
追加 `log` 事件直到收到 `done` 事件。
- **实时日志面板** — 通过 Server-Sent Events (`/run/<id>/logs`) 实时
  显示代理输出。服务端对每条流设 5 分钟上限,浏览器凭 `Last-Event-ID`
  续接

完成后同 URL:
- **评分单树** — 彩色编码 (pass = 绿色,fail = 红色) + 每叶节点权重
- **按类别通过率表**
- **负向控制结果**
- **报告下载** — en/ja/zh × pdf/html/md (`POST /run/<id>/report`)

作业记录持久化到 `{registry_root}/jobs/<job_id>.json` (权限 `0o600`),
因此能挺过 viz 服务器重启。重启后仍带 `queued`/`running` 的记录会以
附加状态 `interrupted` 报告 — 其 worker 线程随旧进程一起死亡,并且刻意
不会被重新拉起。对非 `completed` 的作业,`/results` 返回
`{"error": "results not available", "status": …}`。

## v0.8.0 更新

- **Step 3 Reproduce: 新增 `container_image` 字段** — 接受非 symlink 的
  本地 SIF、完整 Docker `sha256:<image-id>` 或以
  `@sha256:<digest>` 固定的 URI；拒绝可变标签和短别名 (包括该字段自身
  placeholder 里展示的那些)。`sandbox=docker`/`apptainer`/`singularity`
  时必填;而 `local` / `slurm` 下它是**被拒绝而非被忽略** —
  `resolve_image` 抛出 *"container_image is only valid for a container
  sandbox"*,所以切回非容器 sandbox 时要清空该框。
- **GPU resource 一致性**: 共享typed scheduler把count/type编译为单一directive，
  拒绝per-task/per-node矛盾，并且不会静默drop资源。
- **fail-loud 前置条件**: 请求的 sandbox / GPU 资源在 host 不可用时报错
  停止，不存在 host-local 回退。异常不会传播给调用方: `run_reproduce`
  捕获后返回 `{"executed": false, "error": …, "failure_kind": …,
  "attempt_status": "failed"}`,并把该 attempt 作为证据保留。
  - 容器 runtime 二进制缺失 → `ReproductionContractError`
    *"sandbox runtime is unavailable"* → `failure_kind:
    "sandbox-unavailable"`
  - `sandbox=slurm` 但 `sbatch` 缺失或 partition 无法解析 →
    `RuntimeError` → `failure_kind: "scheduler-failure"`
  - 矛盾或不受支持的 typed GPU 形状 → 校验/调度器错误,记录方式相同
  - 客户端在 PATH 上但 docker daemon 已停的情况**不**被前置条件捕获,
    它表现为 `docker run` 的非零退出码
- **Step 4 Judge: `code_only`** — 仅作为 verified Stage 2 record 的显式
  scope；没有 reproduction record 时失败且不发布分数。向导里**没有**
  对应控件: `judge_config.code_only` 只有手工构造
  `POST /api/paperbench/run` body 才能传到 skill。

## 相关

- [论文导入](paper_import.md)
- [快速入门](paperbench_quickstart.md)
- [执行配置参考](../../reference/execution_profile.md)
- [API 参考](../../reference/api_paperbench.md)
