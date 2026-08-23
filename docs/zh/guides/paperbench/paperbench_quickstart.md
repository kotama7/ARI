---
sources:
  - path: scripts/sc_paper_dogfood.py
    role: doc
  - path: scripts/build_pb_images.sh
    role: doc
  - path: ari-skill-paper-re
    role: implementation
  - path: ari-skill-replicate
    role: implementation
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/PaperBench
    role: implementation
  - path: ari-core/config/paperbench_rubrics
    role: config
  - path: report/Makefile
    role: config
last_verified: 2026-08-16
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
填写 (arXiv ID / DOI / 上传 PDF / 本地路径),然后 **保存到注册表**。
许可证输入框下方的徽章只是客户端的乐观正则猜测 (仅 `MIT` / `Apache*` /
`BSD*` / `arXiv*` / 裸 `CC BY` 显示绿色),因此 `CC0` 与 `CC BY-SA` 在
表单里显示 ⚠,而服务端仍把它们分类为 usable。注册表行显示的才是
服务端的真实判定。

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
2. **评分单** — 生成器模型 (默认 `gemini/gemini-2.5-pro`,calibrated
   `hierarchical-v2` 策略 — 该策略不可选)。
   参见[评分单 schema](../../reference/rubric_schema.md)。
3. **再现** — 再现模型与时间预算。展开「执行配置覆盖」即可手动覆盖
   SLURM 分配标志 (`--nodes`, `--ntasks`, `--ntasks-per-node`,
   `--gpus-per-task`, `gpu_type`, `memory_gb_per_node`, `--exclusive`,
   `--constraint`, `--hint`, `--nodelist`)。`account` / `qos` /
   `reservation` 没有各自的字段: 网格中自由文本的 `extra_sbatch_args`
   框只接受 `--account=`、`--qos=`、`--reservation=`、`--hint=` 这几种
   条目 (skill 会把它们翻译为 typed 字段),其他任何标志都会被拒绝。
   向导字段始终从 `0` / `""` 起步 — 不存在预填;评分单的
   `execution_profile` 是在服务端的 `run_reproduce` 里合并的,非零的
   向导值胜过评分单 hint。
4. **判分** — SimpleJudge 模型 + `n_runs` (默认 1, PaperBench 论文 §4.1)。
5. **启动** — 查看成本估算,点击 *Dry run* 验证,再点击 *全部启动*
   入队。

## 3. 等待

向导为每篇论文返回一个 `job_id`。打开
`#/paperbench/results?job=<job_id>`: Results 页面先读一次
`GET /api/paperbench/run/<job_id>` 取状态,随后通过 Server-Sent Events
订阅 `GET /api/paperbench/run/<job_id>/logs` 跟踪该作业,直至
`completed`、`failed` 或 `interrupted`。常见时长: CPU smoke 约 30 分钟,
完整 GPU 复现数小时。

> 若 worker 随 viz 服务器重启而死亡,该作业会以 `interrupted` 状态
> 报告,并且**不会**被重新拉起 — 请从向导重新启动。

## 4. 查看分数

状态变为 `completed` 后,Results 页面会渲染评分单树、每个叶节点的
通过/失败、以及聚合 ORS 分数。原始 JSON:
`GET /api/paperbench/run/<job_id>/results`。

## 5. 生成审计报告 (可选)

输出人类可读的报告。`AUDIT_FORMATS` 默认只有 `pdf` (要 HTML 必须显式
指定),`AUDIT_LANGS` 默认 `en`,`AUDIT_OUTPUT` 默认 `audit/$(PAPER_ID)`:

```bash
make -C report audit-report \
  CHECKPOINT=/var/tmp/ari/.../<checkpoint-id> \
  PAPER_ID=<paper_id> \
  AUDIT_LANGS="en ja zh" \
  AUDIT_FORMATS="pdf html"
```

同一个渲染器在 GUI 侧对应
`POST /api/paperbench/run/<job_id>/report`,其默认格式是
`["pdf", "html", "md"]`,输出写入 `{registry_root}/reports/<job_id>/`。

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

输出的 `rubric.json` **应当**拥有正好对应 `sc.yaml` 中 `top_level_axes`
的六个直接子节点, 叶子句式由「实现执行 X」切换为「X 在论文或 AD 中是否
可识别」。这两点都只由 prompt 指令保证 (`build_skeleton_venue_hint` 发出
「DO NOT ADD, REMOVE, RENAME, OR REORDER」的规范性区块),没有任何
validator 会拒绝轴集合漂移了的 rubric — 请检查脚本输出中的
`[rubric.summary] direct_children=`。
新增 venue 只需 YAML 一个文件 — 详见
[`rubric_schema.md`](../../reference/rubric_schema.md#venue-条件化模板-venue-conditioned-templates)。

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
    --rubric-model gpt-5-mini \
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

使用 vendor 镜像时先运行 `scripts/build_pb_images.sh`。Stage 2 使用脚本
输出的完整 Docker image ID；Stage 1 Apptainer rollout 先执行
`apptainer pull pb-env.sif docker-daemon://pb-env:latest`，再传入 SIF 的绝对
路径。不要直接传递可变标签。

> **fail-loud 前置条件 (v0.8.0)**。
> 当请求的 sandbox / GPU 资源在 host 不可满足时, 直接报错而不会静默
> 降级到 host CPU；legacy 回退路径已删除。
>
> GPU/resource 请求没有静默丢弃 override；应修复集群配置或选择兼容分区。
> 调用方看到的并不是抛出的异常 — `run_reproduce` 捕获异常、把失败的
> attempt 记录下来,并返回
> `{"executed": false, "error": …, "failure_kind": …}`,其中
> `failure_kind` 为 `"sandbox-unavailable"` (容器 runtime 缺失) 或
> `"scheduler-failure"` (无 `sbatch`、无法解析 partition)。
>
> network deny 默认开启；未隔离的 local/SLURM 需要管理员 attestation,
> 或显式选择 `network_policy=inherit`。向导两个参数都不发送,因此从 GUI
> 启动的 `local` / `slurm` 再现会在 plan 阶段以
> *"sandbox_kind=… cannot prove network denial"* 被拒绝。要用到这两个
> 参数,请改走 `run_reproduce` MCP 工具或
> `_paperbench_bridge.reproduce_submission` 入口。

## HPC 集群 sbatch 包装脚本(示例)

ARI bridge **不会**自动加载集群 module —— 这是用户的职责
(NERSC/OLCF/LLNL 都建议把 `module load` 放在 sbatch 脚本顶端)。
bridge 在 rollout 开始时以只读方式 probe `module spider` 与 `module avail`
(绝不执行 `module load`),并把目录作为数据交给 agent,由 agent 决定要
load 哪个。如需完整目录,在 sbatch 包装中**事前 load**:

示例(采用两级入口的 Env Modules 站点 — **请根据您的集群 module/partition/GPU 调整**):

```bash
#!/bin/bash
#SBATCH --partition=<partition>
#SBATCH --gres=gpu:L40S-44GB:1
#SBATCH --time=08:00:00
#SBATCH --output=workspace/checkpoints/<ts>_<slug>/sbatch.log
set -eu

# 预先加载论文所需的 module(集群命名各异,用 `module avail` 探索)
module load <site-entry-module>  # 集群特定的入口 module
module load nvhpc             # 若论文需要 CUDA / nvcc
# module load openmpi         # 若论文需要 MPI

cd /path/to/ARI
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/paper.pdf \
    --rubric-model gpt-5-mini \
    --with-rollout --rollout-model gpt-5-mini \
        --rollout-time-limit-sec 14400 --rollout-sandbox local \
    --with-reproduction --reproduce-sandbox local \
        --reproduce-time-limit-sec 7200 \
    --judge-dryrun --judge-model gpt-5-mini \
    --out workspace/checkpoints/<ts>_<slug>
```

收益:

- python 进程继承已加载的 env (PATH 上有 nvcc 等)。
- bridge 的 module probe (`_probe_module_avail`、`_detect_runtime_env`)
  是普通的 `subprocess.run` 调用,会继承该 env,所以目录以及展示给
  agent 的 `nvcc_path` / `module_path` 事实都会反映你预加载的内容。

**得不到**的收益 — 该环境**不会**到达 agent,也不会到达被评分的脚本:

- Stage 1 的 agent shell 是被清洗过的,而不是继承的。
  `_compute/computer.py:_agent_environment` 构造固定字典
  (`PATH=/usr/local/bin:/usr/bin:/bin`、`HOME=<work_dir>/.ari_home`),
  `LocalComputer.send_shell_command` 以 `bash --noprofile --norc -c`
  执行命令。因此 agent 在 PATH 上看不到你预加载的 nvcc,而且除非
  agent 自己 source module init,它的 shell 里连 `module` 命令都没有
  定义。
- Stage 2 的 `reproduce.sh` 同样被清洗。`execute_local_attempt` 在
  `ari.execution.build_minimal_environment()` 下运行它: `PATH` 重置为
  `/usr/local/bin:/usr/bin:/bin`,`HOME=/nonexistent`,只从父进程继承
  `LANG`、`LC_ALL`、`SSL_CERT_DIR`、`SSL_CERT_FILE`。SLURM 路径则以
  `#SBATCH --export=NIL` 提交,道理相同。不带自己 `module load` 链的
  `reproduce.sh`,无论你的包装脚本加载过什么,在评分时都会失败。

因此这**不能替代**:

agent **必须在 `submission/reproduce.sh` 顶部**写 `module load <NAME>`,
使脚本可移植到评分环境 (vendor PaperBench eval 在 Docker 中没有
module)。bridge 的 env-truth 注记 + paper-kind addendum 已在 STEP 2
明确要求 agent 这样做。

不预加载 (Pattern A: 无 module load 的最小 sbatch) 时:

- bridge 仍然可用。
- agent 通过 env-truth 注记中的 `module spider` / `module avail` 目录以及
  paper-kind addendum 的 runbook STEP 1 自我发现。
- 确定性较低 — 目录只是未扩展的 `MODULEPATH` 所暴露的内容,因此在两级
  入口的站点上,tier-2 module 只能通过 bridge 只读的 `module show` 展开
  才可见,agent 仍可能在自己的 shell 中加载失败,把 CUDA 论文做成
  Python 代理实现。
- ML / 纯 Python 论文无需预加载工具链,适合 Pattern A。

## 下一步

- [Rubric schema 与 venue 模板](../../reference/rubric_schema.md)
- [执行配置参考](../../reference/execution_profile.md)
- [多节点搭建](multi_node_setup.md)
- [计算节点安全约定](compute_node_safety.md)
- [故障排查](paperbench_troubleshooting.md)
- [PaperBench bridge API](../../reference/api_paperbench.md)
- [环境变量](../../reference/environment_variables.md)
