---
sources:
  - path: scripts/sc_paper_dogfood.py
    role: doc
  - path: ari-skill-paper-re
    role: implementation
  - path: ari-skill-replicate
    role: implementation
last_verified: 2026-05-25
---

# PaperBench 快速入门

5 分钟内完成「导入外部论文 → 查看 PaperBench 审计分数」全流程。

## 先决条件

- 已安装 ARI (`pip install -e ari-core/`)。
- viz 服务器已启动 (`ari viz` 或 `python -m ari.viz.server`)。
- `.env` 中配置了 LLM 提供方密钥 (例如 `OPENAI_API_KEY` /
  `GEMINI_API_KEY`)。
- 如需 SLURM 调度: `sbatch` 在 PATH 上,且参照
  [`docs/guides/paperbench/multi_node_setup.md`](multi_node_setup.md) 完成集群准备。

## 1. 导入论文

打开仪表盘的 **📚 PaperBench** 侧栏入口,点击 **📥 导入论文**。在表单中
填写 (arXiv ID / DOI / 上传 PDF),然后 **保存到注册表**。当许可证被
自动识别为宽松类型 (MIT, Apache-2.0, CC BY/SA, CC0) 时,徽章会变为
绿色 ✅。

CLI 等价命令:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "arxiv",
    "source": "2404.14193",
    "title": "LLAMP: assessing latency tolerance",
    "license": "CC BY 4.0",
    "authors": ["Alice", "Bob"]
  }'
```

## 2. 启动 PaperBench 向导

在注册表页面勾选论文,点击 **🚀 运行 PaperBench**。共 5 步:

1. **论文** — 确认选择。
2. **评分单** — 生成器模型 (默认 `gemini-2.5-pro`, two_stage 开)。
   参见[评分单 schema](../../reference/rubric_schema.md)。
3. **再现** — 再现模型与时间预算。展开「执行配置覆盖」即可手动覆盖
   SLURM 分配标志 (`--nodes`, `--gpus-per-task`, `--exclusive`, ...)。
   评分单已自带 `execution_profile` 时字段会预填。
4. **判分** — SimpleJudge 模型 + `n_runs` (默认 1, PaperBench 论文 §4.1)。
5. **启动** — 查看成本估算,点击 *Dry run* 验证,再点击 *全部启动*
   入队。

## 3. 等待

每篇论文返回一个 `job_id`。Monitor 页面会轮询
`GET /api/paperbench/run/<job_id>`。常见时长: CPU smoke 约 30 分钟,
完整 GPU 复现数小时。

## 4. 查看分数

状态变为 `completed` 后,Results 页面会渲染评分单树、每个叶节点的
通过/失败、以及聚合 ORS 分数。原始 JSON:
`GET /api/paperbench/run/<job_id>/results`。

## 5. 生成审计报告 (可选)

输出人类可读的 PDF/HTML 报告:

```bash
make -C report audit-report \
  CHECKPOINT=/var/tmp/ari/.../<checkpoint-id> \
  PAPER_ID=<paper_id> \
  AUDIT_LANGS="en ja zh"
```

Python API: [`report/scripts/paperbench_report.py`](../../../../report/scripts/paperbench_report.py)。

## 6. (进阶) 按 venue 切换 rubric 范式

`generate_rubric` 默认使用原始 PaperBench 范式 (直接子节点按论文贡献分解、
叶节点评分 submission 输出)。若要进行**论文审计** (论文本身是否描述了足够
信息以再现?), 通过 `paperbench_rubric_id` 选择 venue 模板。已自带的 ID:

- `generic` — 向后兼容默认
- `sc` — HPC 六轴 (环境 / 数据 / 执行 / 图表 / 扩展性 / 结论)
- `neurips` — NeurIPS Reproducibility Checklist 六轴
- `nature` — wet-lab Reporting Summary 五轴

CLI dogfood (无 GUI、无 SLURM、通过 `scripts/sc_paper_dogfood.py` 直接调用
`generate_rubric_async`):

```bash
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/sc24_paper.pdf \
    --rubric-template sc \
    --rubric-model gpt-5-mini \
    --target-leaves 30
```

输出的 `rubric.json` 将拥有正好对应 `sc.yaml` 中 `top_level_axes` 的六个
直接子节点, 叶子句式由「实现执行 X」切换为「X 在论文或 AD 中是否可识别」。
新增 venue 只需 YAML 一个文件 — 详见
[`rubric_schema.md`](../../reference/rubric_schema.md#venue-conditioned-templates)。

## 7. (进阶) 通过 CLI 执行完整 3-stage 协议 (v0.8.0)

dogfood 脚本通过 bridge surface
(`ari-skill-paper-re/src/_paperbench_bridge.py`) 驱动 PaperBench 的
Stage 1 → 2 → 3:

- **Stage 1** (`rollout_submission`) — vendor BasicAgent / IterativeAgent
  编写 `reproduce.sh`
- **Stage 2** (`reproduce_submission`) — 在所选 sandbox 中执行,
  抓取 `reproduce.log` 与 `submission_executed_<UTC>.tar.gz`
- **Stage 3** (`judge_submission`) — 对执行后的 submission 评分

```bash
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/paper.pdf \
    --rubric-model gpt-5-mini --two-stage \
    --with-rollout \
        --rollout-model gpt-5-mini \
        --rollout-time-limit-sec 14400 \
        --rollout-sandbox local \
    --with-reproduction \
        --reproduce-sandbox slurm \
        --reproduce-partition <PARTITION> \
        --reproduce-gpus-per-task 1 \
        --reproduce-time-limit-sec 7200 \
    --judge-dryrun --judge-model gpt-5-mini \
    --out $HOME/.ari_pb_<run_id>
```

与 `--paper-audit-mode`(以及 `sc.yaml` 等 `paper_audit` 模板)
**互斥** — paper_audit 评分论文本身; `--with-reproduction` 评分执行
后的 submission, 二者不可同时启用。

若需使用 vendor 镜像, 请先执行 `scripts/build_pb_images.sh` 构建
`pb-env` / `pb-reproducer`, 然后传入
`--rollout-container-image pb-env --reproduce-container-image pb-reproducer`。

> **fail-loud 前置条件 (v0.8.0)**。
> 当请求的 sandbox / GPU 资源在 host 不可满足时, 直接报错而不会静默
> 降级到 host CPU:
> - `ARI_PHASE1_ALLOW_FALLBACK=1` — 当 docker / apptainer / sbatch
>   缺失时, opt-in 回到 legacy 静默降级
> - `ARI_SLURM_ALLOW_NO_GRES=1` — 集群无 GRES 配置时, opt-in 静默
>   丢弃 `--gres` / `--gpus-*` 标志
>
> 两者默认 OFF (报错并给出可操作的提示)。

## HPC 集群 sbatch 包装脚本(示例)

ARI bridge **不会**自动加载集群 module —— 这是用户的职责
(NERSC/OLCF/LLNL 都建议把 `module load` 放在 sbatch 脚本顶端)。
bridge 在 rollout 开始时 probe `module avail` 并把目录作为数据交给
agent,由 agent 决定要 load 哪个。如需确定性,在 sbatch 包装中
**事前 load**:

示例(R-CCS ai-l40s — **请根据您的集群 module/partition/GPU 调整**):

```bash
#!/bin/bash
#SBATCH --partition=ai-l40s
#SBATCH --gres=gpu:L40S-44GB:1
#SBATCH --time=08:00:00
#SBATCH --output=workspace/checkpoints/<ts>_<slug>/sbatch.log
set -eu

# 预先加载论文所需的 module(集群命名各异,用 `module avail` 探索)
module load system/ai-l40s   # 集群特定的入口 module
module load nvhpc             # 若论文需要 CUDA / nvcc
# module load openmpi         # 若论文需要 MPI

cd /path/to/ARI
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/paper.pdf \
    --rubric-model gpt-5-mini --two-stage \
    --with-rollout --rollout-model gpt-5-mini \
        --rollout-time-limit-sec 14400 --rollout-sandbox local \
    --with-reproduction --reproduce-sandbox local \
        --reproduce-time-limit-sec 7200 \
    --judge-dryrun --judge-model gpt-5-mini \
    --out workspace/checkpoints/<ts>_<slug>
```

收益:python 进程 → Stage 1 agent 子进程 → Stage 2
`bash submission/reproduce.sh` 全程继承 env,nvcc 等始终在 PATH 上。

替代:不预加载 bridge 也能运行(agent 通过 `module avail` 目录自我
发现),但 agent 可能忘记加载而退化到 Python 代理
(SC41406 v2 = 0.8%)。

agent **应当在 reproduce.sh 顶部** 也写 `module load <NAME>`
(vendor PaperBench eval 在 Docker 中没有 module,为可移植性),
这点 bridge 的 env-truth + paper-kind addendum 已经明确指示。

## 下一步

- [Rubric schema 与 venue 模板](../../reference/rubric_schema.md)
- [执行配置参考](../../reference/execution_profile.md)
- [多节点搭建](multi_node_setup.md)
- [计算节点安全约定](compute_node_safety.md)
- [故障排查](paperbench_troubleshooting.md)
- [PaperBench bridge API](../../reference/api_paperbench.md)
- [环境变量](../../reference/environment_variables.md)
