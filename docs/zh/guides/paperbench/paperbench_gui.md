# PaperBench GUI 指南

仪表盘 **📚 PaperBench** 侧栏入口下:

- `/paperbench` — 论文注册表列表
- `/paperbench/run` — 5 步执行向导
- `/paperbench/results?job=<id>` — 结果视图 (评分单树 + 实时日志 +
  报告下载)

## 论文注册表 (`/paperbench`)

显示 `~/.ari/paper_registry/manifest.jsonl` 内全部论文 (上面可用
`ARI_PAPER_REGISTRY_DIR` 覆盖)。每行:

- ☑ 复选框 — 向导多选
- `paper_id` — FS-safe 的 slug
- 标题
- 许可证徽章 — 宽松许可证 (MIT, Apache, CC BY/SA, CC0, arXiv 非独占)
  显示绿色 ✅,其他显示黄色 ⚠。悬停查看详细评估
- 来源 — `arxiv:2404.14193`, `doi:10.1109/...` 等
- 删除 — 同时移除 manifest 行与论文目录

顶部操作栏:
- **📥 导入论文** → `/paperbench/import`
- **🚀 运行 PaperBench (N)** → `/paperbench/run` (N≥1 时可用)
- **刷新** — 重新读取 manifest

## 论文导入 (`/paperbench/import`)

v0.7.2 的最小表单:

| 字段 | 备注 |
|---|---|
| 来源类型 | `arxiv` \| `doi` \| `upload` \| `local` |
| 来源标识 | arXiv ID (`2404.14193`)、DOI、PDF 路径 |
| 标题 | 必填 |
| 作者 | 逗号分隔 |
| 会议 / 年份 | 可选 |
| 许可证 | 自由形式; 服务端分类 |
| 工件 URL | 可选代码库 URL |

`source_type=arxiv` 时出现 **「↓ 抓取元数据」按钮**,触发
`/api/paperbench/arxiv/<id>` 调用 arXiv Atom API 并自动填充
title / authors / year / license。

许可证徽章镜像 `_classify_license` 服务端判定:
- ✅ "Permissive license — usable" — MIT, Apache-2.0, BSD, CC0, CC BY,
  CC BY-SA
- ⚠ "License may require review" — 其他 (含未知字符串)

## 运行向导 (`/paperbench/run`)

5 步,所有配置汇聚为单一 `POST /api/paperbench/run` body。

### Step 1 — 论文选择

从注册表多选。选中 ≥1 篇前 Next 不可用。

### Step 2 — 评分单配置

- **模型** — `gemini-2.5-pro` (默认)、`gpt-5.4`、`claude-opus-4-7`
- **两阶段** — skeleton + 并行 subtree 调用。~4× 叶节点数,~5× API
  成本。默认开
- **目标叶节点数** — `0` (从论文长度自动,~1 leaf / 75 word)

### Step 3 — 再现配置

顶部表单:
- **模型** — 再现代理模型 (默认 `gpt-5-mini`)
- **时间上限** — 秒数;默认 12 h (PaperBench 论文 §5.2)
- **沙箱** — `auto` / `slurm` / `local` / `apptainer` / `docker`
- **分区** — 仅 `slurm` 时有意义

**执行配置覆盖** (v0.7.2 的焦点):

16 字段网格允许覆盖 rubric 内 execution_profile hint。当所选论文的
rubric 已有 `execution_profile`,字段会预填;否则从 0/"" 开始。

| 字段 | 类型 | SLURM 标志 |
|---|---|---|
| nodes | int | `--nodes` |
| ntasks | int | `--ntasks` |
| ntasks_per_node | int | `--ntasks-per-node` |
| gpus_per_task | int | `--gpus-per-task` |
| memory_gb_per_node | int | `--mem` |
| exclusive | bool | `--exclusive` |
| gpu_type | str | `--gres=gpu:<type>:N` (`_slurm_has_gres()` 把关) |
| constraint | str | `--constraint` |
| cpu_bind | str | `--cpu-bind` |
| mem_bind | str | `--mem-bind` |
| hint | str | `--hint` |
| nodelist | str | `--nodelist` |
| extra_sbatch_args | str (空格分隔) | pass-through |

完整语义见 [执行配置参考](../reference/execution_profile.md)。

### Step 4 — 判分配置

- **模型** — `gpt-5-mini` (默认)、`claude-haiku-4-5-20251001`
- **n_runs** — 1 (PaperBench 论文 §4.1)
- **跳过负向控制** — 建议关;这是廉价的 sanity check

### Step 5 — 启动

显示汇总 + 实时成本估算 (`POST /api/paperbench/cost-estimate`)。
*Dry run* 验证后,*🚀 全部启动* 入队。每篇论文 1 个 `job_id`。

## 监控 + 结果

向导返回 `job_id` 列表。状态:

```bash
curl http://localhost:8765/api/paperbench/run/<job_id>
```

运行中的论文,在 `/paperbench/results?job=<job_id>`:
- **实时日志面板** — 通过 Server-Sent Events (`/run/<id>/logs`) 实时
  显示代理输出

完成后同 URL:
- **评分单树** — 彩色编码 (pass = 绿色,fail = 红色) + 每叶节点权重
- **按类别通过率表**
- **负向控制结果**
- **报告下载** — en/ja/zh × pdf/html/md (`POST /run/<id>/report`)

## v0.7.3 更新

- **Step 3 Reproduce: 新增 `container_image` 字段** — 接受 SIF 路径 /
  `docker://` URI / `image:tag` / 短别名 `pb-env` / `pb-reproducer`
  (由 `scripts/build_pb_images.sh` 构建)。仅在
  `sandbox=docker`/`apptainer`/`singularity` 时生效。
- **GPU 标志一致性**: `gpus_per_task` 单独 → 自动配对 `--ntasks 1`;
  设置 `gpu_type` 时 `--gres=gpu:TYPE:N` 为 canonical, 同时 drop
  untyped `--gpus-per-task` (避免 SLURM 24.05 的 typed/untyped 冲突)。
- **fail-loud 前置条件**: docker daemon / apptainer / sbatch / partition
  / GRES 缺失时报错停止 (设置
  `ARI_PHASE1_ALLOW_FALLBACK=1` / `ARI_SLURM_ALLOW_NO_GRES=1` opt-in
  回到 legacy 静默降级)。
- **Step 4 Judge: `code_only` 自动启用** — 当 Stage 2 被跳过
  (无 reproduce.log) 时, rubric 被裁剪为仅 Code Development 叶,
  避免 Code Execution / Result Analysis 叶被 structural 0 化。

## 相关

- [论文导入](paper_import.md)
- [快速入门](paperbench_quickstart.md)
- [执行配置参考](../reference/execution_profile.md)
- [API 参考](../reference/api_paperbench.md)
