# PaperBench 故障排查

常见失败模式与对策。审计运行流水线为
`rubric_path → build_reproduce_sh → run_reproduce → grade_with_simplejudge`;
问题通常属于这 4 阶段之一。

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

如果为空,重新生成 rubric (v0.7.2 的 `skeleton.md` prompt 现在指示
LLM 从论文的实验设置章节填充 `execution_profile`)。

### Q. 代理为 MPI 论文没有使用 `srun`

检查 `agent.log` 中的 user message,确认存在
`COMPUTE-NODE EXECUTION CONVENTIONS` 区块。如果缺失,呼叫方没有传
`execution_profile`。验证连接:

```bash
python -c "
from ari_skill_paper_re._replicator_agent import _format_hpc_appendix
print(_format_hpc_appendix(
    expected_artifacts=['results.csv'],
    execution_profile={'kind': 'mpi_gpu', 'metric_columns': ['x']},
    cluster_shape={'SLURM_JOB_NUM_NODES':'4','SLURM_NTASKS':'32','GPU_LIST':'v100'}
))"
```

输出必须包含 `srun -n $SLURM_NTASKS`。

## SLURM 调度 (`run_reproduce`)

### Q. `sbatch: error: Invalid GRES gpu:v100:1`

集群未配置 GRES。v0.7.2 通过 `_slurm_has_gres()` 自动剥离 flag — 如果
你仍看到此错误,你在更旧的构建上,或 `sinfo` 不在 PATH 上。
解决方法: 让向导的 *执行配置覆盖* 中的 `gpu_type` 留空。

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
- 把 `"openmpi/4.1"` (或集群名) 加到 rubric 的 `module_loads`
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

### Q. `ors_score` 恰好为 `0.0`

grader 找不到 `reproduce.sh` 或任何预期产物。检查:

```bash
ls repro_sandbox/                  # reproduce.sh 存在?
jq '.executed, .exit_code' repro_result.json   # 干净运行?
jq '.missing' repro_result.json    # 缺少 expected_artifacts?
```

一个常见原因: 代理把 `submission/reproduce.sh` 写到了那儿而非
workspace root。v0.7+ 自动提升此路径;如果你在更旧的构建上,手动 cp。

### Q. 负向控制没有通过 (boilerplate > 5%)

rubric 的叶节点过于容易满足 — 它们与通用 boilerplate 模式匹配。
重新审计 rubric,使用更严格的 `task_category="Code Execution"` claim
要求特定日志输出或产物内容。

## GUI / 向导

### Q. 向导一直显示 "尚未注册任何论文"

检查 `~/.ari/paper_registry/manifest.jsonl` 存在且非空。如果你设置了
`ARI_PAPER_REGISTRY_DIR`,路径会相应改变。

### Q. 启动按钮一直禁用

Step 1 (Papers) 需要至少选择一篇论文。按钮在 `selected_count >= 1`
之前保持禁用。

### Q. 成本估算为 `$0`

你在 Step 3 (Reproduce) 中没有设置 `time_limit_sec`。默认 12 h;
0 让估算的再现 wall-time 项坍塌。

## 报告生成

### Q. `latexmk: command not found`

审计报告 PDF 目标需要 XeLaTeX。安装 `texlive-xetex` (Debian/Ubuntu)
或 `mactex` (macOS),或跳过 PDF 只发出 `.tex` 源码:

```bash
python -m report.scripts.paperbench_report paper \
    --checkpoint <ckpt> --paper-id <id> \
    --output-root report/audit/<id> \
    --formats tex   # 跳过 PDF
```

### Q. ja/zh PDF 中 CJK 字符渲染为方框

ja/zh 镜像需要 XeLaTeX + Noto CJK 字体。运行
`report/setup_fonts.sh` 并用 `fc-list | grep -i 'noto.*cjk'` 验证。

## 相关

- [快速入门](paperbench_quickstart.md)
- [多节点搭建](multi_node_setup.md)
- [计算节点安全](compute_node_safety.md)
- [执行配置参考](../reference/execution_profile.md)
