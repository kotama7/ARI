---
sources:
  - path: ari-skill-paper-re
    role: implementation
  - path: ari-skill-replicate
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/PaperBench/PaperBenchWizard.tsx
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: report/scripts/paperbench_report.py
    role: implementation
last_verified: 2026-08-16
---

# PaperBench 故障排查

常见失败模式与对策。审计运行流水线为
`generate_rubric → audit_rubric → build_reproduce_sh → run_reproduce →
grade_with_simplejudge`;问题通常属于其中某个阶段。`audit_rubric` 非致命 ——
审计失败只会被记录,运行继续。

## 评分单生成

### Q. 评分单只有 0 个叶节点

生成器在所有 3 次重试中都无法产生有效 JSON。查看 worklog 中的最后
失败。常见原因:
- LLM 速率限制 (几分钟后重试)
- 论文 PDF 解析为空字符串 — 重新上传,或先用 `pdftotext` 转换

### Q. grader 加载时 `task_category` 错误

grader 拒绝 `"Result Visualization"` 等非 PaperBench 类别。生成器的
`normalize_rubric_node` 阶段应把这些钳制到 allow-list
(`Code Development`, `Code Execution`, `Result Analysis`)。如果错误
依旧,用最新的 `gemini-2.5-pro` 构建重新生成 — 旧模型漂移更多。

## 复现器 (BasicAgent)

### Q. 代理从未写 `reproduce.sh`

12 h rollout 在没有调用 `submit` 的情况下用完了时间。可能原因:
- 模型输出被截断 (在 `agent.log` 查找 `TOOL OUTPUT TRUNCATED` — 通常
  良性)
- 论文文本超过模型 context;尝试小论文或 `iterative_agent=true`

### Q. 代理为 GPU 论文提交了 CPU 代码

rubric 的 `execution_profile.kind` 很可能为空。验证:

```bash
jq '.reproduce_contract.execution_profile' rubric.json
```

重新生成未必能把它填上:`skeleton.md` 指示生成器,除非论文明确陈述了并行 /
分布式执行属性 ("we evaluated at N MPI ranks"、"we trained on M GPUs with data
parallelism" 等),否则**整个 `execution_profile` 字段都要省略**。对单机论文
(包括单 GPU) 而言,没有该 profile 正是预期结果 —— profile 为空时
`_format_hpc_appendix` 根本不发出任何 HPC 指引。如果论文确实写明了 GPU / 并行
设置而生成器漏掉了,就重新生成;否则直接在 rubric 中显式设置 profile
(`kind` 取 `cpu_single`、`gpu_single`、`gpu_multi`、`mpi`、`mpi_gpu` 之一)。

### Q. 代理为 MPI 论文没有使用 `srun`

检查 `agent.log` 中的 user message,确认存在
`COMPUTE-NODE EXECUTION CONVENTIONS` 区块。如果缺失,呼叫方没有传
`execution_profile`。用下面的方式验证连接 —— 该技能发布的是扁平的顶层模块
(`_replicator_agent`、`server` 等) 而非 `ari_skill_paper_re` 包,所以导入需要把
`ari-skill-paper-re/src` 放到 `PYTHONPATH` 上:

```bash
PYTHONPATH=ari-skill-paper-re/src python -c "
from _replicator_agent import _format_hpc_appendix
print(_format_hpc_appendix(
    expected_artifacts=['results.csv'],
    execution_profile={'kind': 'mpi_gpu', 'metric_columns': ['x']},
    cluster_shape={'SLURM_JOB_NUM_NODES':'4','SLURM_NTASKS':'32','GPU_LIST':'v100'}
))"
```

输出必须包含 `srun -n $SLURM_NTASKS`。

## SLURM 调度 (`run_reproduce`)

### Q. `sbatch: error: Invalid GRES gpu:v100:1`

所选partition无法满足typed GPU请求。用`sinfo -o '%P %G'`检查，选择兼容
partition或修复site GRES配置。ARI不会删除请求并改为CPU运行。

### Q. sbatch 通过了但 `reproduce.sh` 在单节点上运行

`reproduce.sh` 作为第一个 allocated 节点上的一个 rank 启动。代理的
prompt 指示 `srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS` fan-out —
验证脚本实际是否有该行:

```bash
grep -E 'srun.*-N.*-n' repro_sandbox/reproduce.sh
```

如果缺失,手动追加或用更强的模型重新生成。

### Q. 计算节点上 `mpirun: command not found`

compute node 环境中没有加载 OpenMPI。要么:
- 把 `"openmpi/4.1"` (或你所在集群的名字) 加到 rubric 的
  `reproduce_contract.execution_profile.module_loads`
- 把脚本切换到 `srun` (PMI 集成的;大多数 SLURM 站点不需要显式
  OpenMPI 模块也能工作)

### Q. 任务运行但 rank > 0 时 `repo_dir` 文件丢失

`repo_dir` 在节点本地 FS 上。ARI 警告;修复是把 checkpoint 移到共享
mount (`$HOME`, `/work/...`, `/scratch/...`)。

### Q. `--mem=256G` 超出分区限制

rubric 为你的站点过度指定内存。在向导 Step 3 中覆盖
(`memory_gb_per_node = <你的限制>`),或直接编辑 rubric JSON 中的
`execution_profile.memory_gb_per_node`。

## 判分 (`grade_with_simplejudge`)

### Q. 判分响应里根本没有 `ors_score`

只有当判分报告的 status 不是 `failed` 时,才会出现 `ors_score` / `raw_score` /
`score_stddev`。够不到一份已验证复现的 grader 不会给出任何数字:它返回
`grade_status: "failed"` 并带 `error` / `errors`,存下的报告中 `ors_score: null`。
`grade_with_simplejudge` 必须解析到 `status` 为 `succeeded` 的 `ReproductionRunV1`
才会继续;常见的 `errors` 取值有
`no verified ReproductionRunV1 is available`、
`reproduction status is <state>; only succeeded runs are gradable`、
`judge returned invalid scores for leaves: ...`。

复现记录位于复现 workspace 之下,而不是某个扁平的结果文件:

```bash
ls repro_sandbox/                                  # reproduce.sh 存在?
jq . repro_sandbox/.ari-reproduction/latest.json   # 指针: status、run 路径、executed workspace
jq '.attempts[-1].status, .attempts[-1].exit_code, .attempts[-1].expected_missing' \
   repro_sandbox/.ari-reproduction/<plan_digest>/run.json
```

判分报告本身写在 `grade_report_path` 所指的 grade root 下的 `grade-report.json`。

### Q. 负向控制没有通过 (boilerplate > 5%)

rubric 的叶节点过于容易满足 — 它们与通用 boilerplate 模式匹配。
重新审计 rubric,使用更严格的 `task_category="Code Execution"` claim
要求特定日志输出或产物内容。

## GUI / 向导

### Q. 向导一直显示 "尚未注册任何论文"

检查 `<workspace_root>/paper_registry/manifest.jsonl` 存在且非空。该注册表以
workspace 为根 —— 经 `PathManager.paper_registry_root` 解析 —— 而不是 `~/.ari`
下的按用户目录;自 v0.5 起 ARI 不再保有任何全局的按用户数据目录。设置了
`ARI_PAPER_REGISTRY_DIR` 时以它为准。

### Q. 启动按钮一直禁用

Step 1 (Papers) 需要至少选择一篇论文。Launch 按钮与论文步骤上的 Next 按钮
都由 `selectedIds.size === 0` 把守。

### Q. 成本估算为 `$0`

没有选中任何论文。向导渲染的是 `llm_cost_usd × selectedIds.size`,所以空选择
无论 Step 3 怎么配都显示 `$0.00`。

`time_limit_sec` 不可能是原因:服务端估算读的是 `time_limit_sec or 12*3600`,
`0` 会回落到 12 h 默认值;而且 LLM 成本项是与时限无关的每篇固定常数
(rubric `$0.45` + reproduce `$2.00` + judge `$0.10 × n_runs`),只有
`wall_time_sec` 才依赖时限。另一种拿不到数字的情况是估算请求被拒:未知的
`rubric_config` 键会让 `POST /api/paperbench/cost-estimate` 返回
`{"error": "unknown rubric_config fields: ..."}`,里面完全没有成本字段。

## 报告生成

### Q. 审计报告只出了 `.tex`,没有 PDF

你不会看到 `latexmk: command not found` —— PDF 步骤由
`shutil.which("latexmk")` 把守,工具缺失时被静默跳过,命令以 `ok` 结束,只写出
`.tex` 源码。(即便 `latexmk` 存在,它也以 `check=False` 运行,所以 LaTeX 失败
只是留不下 `main.pdf`,同样不会抛异常。) PDF 目标需要 XeLaTeX:安装
`texlive-xetex` (Debian/Ubuntu) 或 `mactex` (macOS)。若想有意只要 `.tex`:

```bash
python -m report.scripts.paperbench_report paper \
    --checkpoint <ckpt> --paper-id <id> \
    --output-root report/audit/<id> \
    --formats tex   # 跳过 PDF
```

### Q. ja/zh PDF 中 CJK 字符渲染为方框

ja/zh 镜像需要 XeLaTeX + Noto CJK 字体。运行
`report/setup_fonts.sh` 并用 `fc-list | grep -i 'noto.*cjk'` 验证。

## v0.8.0 更新: sandbox / GPU 错误

### Q. `"error": "sandbox runtime is unavailable: docker"`, `failure_kind: "sandbox-unavailable"`

当调用方显式指定 sandbox kind 时,`run_reproduce` 拒绝静默降级为宿主本地执行。
它不抛异常:这次拒绝会被记为一次不可变的失败 attempt,并以 dict 返回,带
`executed: false`、`error` 与 `failure_kind`(`sandbox-unavailable`,SLURM 路径则是
`scheduler-failure`)。不要在调用方去找 `RuntimeError`。

检查方式是启动时的 `shutil.which(<runtime>)` —— 对显式的 `sandbox_kind=docker`
从不去探测 docker *daemon*(只有 `auto` 解析才探测),所以 "runtime unavailable"
的含义是该二进制不在 `PATH` 上。同样的 fail-closed 规则适用于
`apptainer` / `singularity`(二进制缺失) 与 `slurm`(sbatch 缺失或 partition 无法解析)。

### Q. `"error": "reproduction plan rejected: ..."`

计划在任何 attempt 产生之前就被拒绝,因此什么都没跑。三个常见原因:

1. `sandbox_kind=<container> requires an immutable container image` —— 既没有
   `container_image`,也没有 `ARI_PHASE1_DOCKER_IMAGE` /
   `ARI_PHASE1_APPTAINER_IMAGE`。
2. 可变的 image 引用。Docker 必须是完整的 `sha256:<image-id>` 或
   `name@sha256:<digest>`;远程 Apptainer 引用必须带 `@sha256:<digest>`;
   本地 SIF 必须是非符号链接的普通文件。
3. `sandbox_kind=... cannot prove network denial` —— `network_policy` 默认为
   `deny`,而 `local` / `slurm` 不是容器命名空间。显式传
   `network_policy="inherit"`、以 `network_isolation_attested=True` 提供管理员
   证明,或改在容器中运行。

### Q. 请求了 GPU 却拿回没有 GPU 的运行

系统有意不做静默降级:ARI 原样提交 typed 请求。`gpus_per_task` 发出为
`#SBATCH --gpus-per-task=[<type>:]<n>`,`gpus_per_node` 发出为
`#SBATCH --gres=gpu:[<type>:]<n>` —— 两者是互斥分支,同时请求会在提交前以
"mutually exclusive" 被拒。若是调度器拒绝了 GRES,请修复站点的 GRES 配置或
改选一个声明了该资源的 partition (`sinfo -o '%P %G'`)。

### Q. agent 完成 Stage 1, 但 Stage 3 所有 leaf 评分为 0

两种原因 (v0.8.0 都已处理):

1. **submission 里没有 `reproduce.log`** — Stage 2 被跳过, 在上游会触发
   vendor SimpleJudge 的保护 "`reproduce.sh` failed to modify or create
   any files. All result analysis tasks will be graded as 0"。ARI 的做法
   不同: 它拒绝这份缺失的复现记录, 不发布任何分数。请补跑 Stage 2, 或者
   显式选择 code-only 研究并且照样创建一条已验证的 Stage 2 记录。
2. **`paper_audit_mode` 误开** — paper-audit 评分论文本身, 与
   `code_only` 互斥, 两者同时 True 时 bridge 抛出 `ValueError`。

### Q. 已提交源码但 `reproduce.sh` 仍以 `src/…: No such file or directory` 失败

代理把仓库构建得深了一层。ARI 的宿主侧 sandbox 把 workspace 呈现为 cwd,
并把 vendor 的 `/home/submission` 路径重写为相对的 `submission/`,因此
逐字遵循 prompt 的代理会把自包含仓库 (`reproduce.sh` + `src/`) 落到
`<workspace>/submission/` 下。 post-rollout 步骤只把 `reproduce.sh` 提升
到 workspace root,使其与源码脱离;Stage 2 随后运行那个孤立副本,build
找不到 `src/…`,导致 Code Execution / Result Analysis 的每个 leaf 归零。

v0.8.0 自动解决此问题: 当 nested 的 `submission/` 持有真实仓库
(`reproduce.sh` 与 `.git` / 源码 co-located) 时,`reproduce_submission`
和 `judge_submission` 会降进去。这样 `reproduce.sh` 的相对路径解析方式
与代理自己的 `cd submission && bash reproduce.sh` 检查时完全一致。无需
操作;孤立的 top-level 副本被忽略。若仍看到旧失败,确认你在 v0.8.0 上。

### Q. 代理的 `apply_patch` / `applypatch` 编辑以 `command not found` 失败

gpt-5 / codex 模型即使没有任何 ARI 或 vendor prompt 指示,也会本能地
通过 `apply_patch <<'PATCH' … PATCH` 编辑文件。vendor Docker image 安装了
`/bin/apply_patch`,但宿主侧的 `LocalComputer` 不构建任何 image,因此
v0.8.0 之前每次这样的调用都失败,代理在 fallback 到 `cat`-heredoc 之前
耗尽 tool-call budget。

v0.8.0 镜像了 vendor 的设置: `LocalComputer` 把包装 vendor 自己
`apply_patch.py` 的 wrapper 放进 workspace 的 `bin/` 目录 (同时以
`apply_patch` 和 `applypatch` 两个名字),并把它 prepend 到每个代理命令
共享的 shell PATH 前面。若找不到 vendor 模块,它会优雅降级 (PATH 不变,
heredoc fallback)。无需操作;这是宿主 sandbox 专用 (Apptainer SIF 已
自带 `/bin/apply_patch`)。

## v0.8.0: HF_TOKEN / agent.env

### Q. 论文需要 HF_TOKEN 获取 gated 数据集 / 模型

通过 `setup.sh` 交互式输入注册, 或加入 `.env`:

```
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

`bridge.rollout_submission` 会自动从调用进程 env 转发。 论文级别 凭据
放入 `~/.ari/agent.env` (`KEY=VALUE` 每行一条) — bridge 在
`agent_env_path=None` 时自动发现。 通过 `ARI_AGENT_ENV_PATH` 覆盖路径。

## 重试 + executed-submission tarball

### Q. `reproduce.sh` 因缺少 Python 3.11 / 缺少 venv 而立刻失败

不存在 salvage wrapper。`salvage_retries` 与 `retry_threshold_sec` **不是**
`bridge.reproduce_submission` 的参数 —— vendor 的
`reproduce_on_computer_with_salvaging` 路径 (它会改写 submission 的环境再重跑)
在 ARI 中没有对应物,并且
`test_reproduce_submission_signature_includes_tarball_not_unsafe_salvage`
断言这两个参数保持缺席。请在 `reproduce.sh` 内部 (或容器 image 里) 修好环境,
然后用同一份 plan 再次调用 `reproduce_submission`:`run_reproduce` 会追加一次
不可变的、链接在一起的 attempt,而不会改动你的脚本。

### Q. executed submission 的 tarball 在哪里?

默认行为是在每次 reproduce 调用后写出 `submission_executed_<UTC>.tar.gz`,
位置在**已执行的** submission 旁边 —— 也就是 `.ari-reproduction` 下的私有
attempt 树内,而不是你传入的 `submission_dir` 旁边。返回 dict 的
`executed_tarball` 键是绝对路径,同时给出 `executed_tarball_digest` 与
`executed_tarball_size_bytes`。用 `tarball_dir=...` 改写目标位置,用
`capture_tarball=False` 关闭。抓取失败绝不会让整次运行失败:它会被记录并追加到
结果的 `warnings` 列表,所以要找的特征是 `executed_tarball` 键缺席而 `warnings`
中多出一条。

## 相关

- [快速入门](paperbench_quickstart.md)
- [多节点搭建](multi_node_setup.md)
- [计算节点安全](compute_node_safety.md)
- [执行配置参考](../../reference/execution_profile.md)
- [PaperBench API + bridge contract](../../reference/api_paperbench.md)
- [环境变量](../../reference/environment_variables.md)
