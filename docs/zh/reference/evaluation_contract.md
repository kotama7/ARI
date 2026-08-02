---
sources:
  - path: ari-core/ari/claim_gate_contract.py
    role: implementation
  - path: ari-core/ari/pipeline/claim_gate/gate.py
    role: implementation
  - path: ari-skill-evaluator/src/server.py
    role: implementation
  - path: ari-core/ari/calibration/evaluator_v1.json
    role: test
last_verified: 2026-08-02
---

# 科学评估契约

ARI 将科学准入、客观证据检查和语义建议划分为不可互换的层。

`MetricContractV1`以摘要固定指标名、单位、方向、比较范围、公式、操作数、容差、必需测量、
正确性条件、不变量和公式来源。旧输入的LLM输出只能成为`MetricContractProposalV1`，并记录
模型、修订、提示词与证据摘要；具名人工审核者生成`MetricAdmissionDecisionV1`之前，不能升级
为科学契约。

确定性硬门输出`GateReportV1`，绑定run、策略、证据、指标契约、公式实现、受限表达式求值器及
单位换算摘要，并区分`blocking_findings`与`advisory_findings`。规范run只读取同一run/node的
`MeasurementSetV1`和包含run id、node id、相对路径及SHA-256的artifact引用。缺失、篡改、未绑定、
跨run、无类型证据或未知单位都不会被猜测。`off`模式记录发现但不阻塞，只有final阶段可停止发布。

`SemanticReviewV1`是非阻塞建议，记录独立模型/修订、完整提示词摘要、证据摘要和不可变硬门摘要；
失败明确表示为`status: unavailable`，且不能修改硬门结论。

pre-v1契约和报告通过保守的显式迁移读取器读取，不重建从未记录的来源。
`ari.calibration/evaluator_v1.json`包含numeric、unit、formula、evidence、policy的CI案例，以及人工
标注的语义正负对照。稳定API是`ari.public.evaluation`，schema位于`ari-core/ari/schemas/`。
