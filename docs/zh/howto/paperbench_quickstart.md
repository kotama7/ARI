# PaperBench 快速入门

5 分钟内完成「导入外部论文 → 查看 PaperBench 审计分数」全流程。

## 先决条件

- 已安装 ARI (`pip install -e ari-core/`)。
- viz 服务器已启动 (`ari viz` 或 `python -m ari.viz.server`)。
- `.env` 中配置了 LLM 提供方密钥 (例如 `OPENAI_API_KEY` /
  `GEMINI_API_KEY`)。
- 如需 SLURM 调度: `sbatch` 在 PATH 上,且参照
  [`docs/howto/multi_node_setup.md`](multi_node_setup.md) 完成集群准备。

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
   参见[评分单 schema](../reference/rubric_schema.md)。
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

Python API: [`report/scripts/paperbench_report.py`](../../../report/scripts/paperbench_report.py)。

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
[`rubric_schema.md`](../reference/rubric_schema.md#venue-conditioned-templates)。

## 下一步

- [Rubric schema 与 venue 模板](../reference/rubric_schema.md)
- [执行配置参考](../reference/execution_profile.md)
- [多节点搭建](multi_node_setup.md)
- [计算节点安全约定](compute_node_safety.md)
- [故障排查](paperbench_troubleshooting.md)
