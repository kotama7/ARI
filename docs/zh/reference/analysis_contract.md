---
sources:
  - path: ari-core/ari/analysis.py
    role: implementation
  - path: ari-skill-benchmark/src/server.py
    role: implementation
  - path: ari-skill-plot/src/server.py
    role: implementation
last_verified: 2026-08-02
---

# 确定性分析契约

ARI 将测量、统计分析、绘图和科学验收分离。`ari-skill-benchmark` 负责汇总、
统计检验和 run 比较；`ari-skill-plot` 负责绘图；`ari-skill-evaluator` 负责
科学验收门。

`ari.public.analysis` 发布 `AnalysisRequestV1`、
`StatisticalTestRequestV1`、`RunComparisonRequestV1` 和 `AnalysisResultV1`。
每个指标必须显式声明单位；指标或单位不一致、空样本、全缺失样本以及配对
长度不一致都会失败。缺失值按 `missing_policy` 处理，并记录删除数量。

统计结果同时包含样本数、检验统计量、原始及校正 p 值、效应量、置信区间、
假设诊断、Python/NumPy/SciPy 版本和解析后的输入摘要。多个比较必须选择
Bonferroni、Holm 或 Benjamini-Hochberg 校正。`analysis_plan_digest` 固定预注册
计划，但不被当作遵循该计划的证明。

CSV/JSON/npy 来源由闭合 `WorkspaceRefV1`、安全相对路径、字节上限和预期
SHA-256 绑定。系统不会把同一 backend/environment 的运行推断为独立重复；
跨环境排名默认拒绝，只有显式选择带警告的比较时才允许。

benchmark 的旧 `plot`、matplotlib/pandas、无 schema 解析以及仅含 p 值的公开
结果已在 v0.2 删除。绘图改由 `plot-skill:render_figure` 完成，并返回带来源、
数据、spec、环境以及 PNG/PDF 摘要的 manifest。
