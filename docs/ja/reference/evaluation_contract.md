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

# 科学評価契約

ARIは、科学的な採用、客観的な証拠検査、意味上の助言を別の層として扱います。

`MetricContractV1`はmetric名、unit、direction、comparison scope、formula、operand、
tolerance、必須測定、correctness、invariant、formula provenanceをdigest付きで固定します。
旧入力へのLLM出力は`MetricContractProposalV1`に留まり、model・revision・prompt・evidenceの
digestを記録します。名前付きreviewerが`MetricAdmissionDecisionV1`を作るまで科学契約には
昇格しません。

決定論的hard gateは`GateReportV1`を返します。run、policy、evidence、metric contract、
数式実装、制限付き式評価器、unit変換のdigestを固定し、`blocking_findings`と
`advisory_findings`を分離します。canonical runでは同じrun/nodeの`MeasurementSetV1`と、
run id・node id・相対path・SHA-256を持つartifactだけを使用します。欠落、改変、未bind、
cross-run、untypedな証拠や未知unitを推測しません。`off`は所見を記録してもblockせず、
final phaseだけがfinalizeを止められます。

`SemanticReviewV1`は独立model/revision、prompt digest、evidence digest、hard-gate digestを
記録する非ブロッキング助言です。hard gateを変更できず、失敗は`status: unavailable`です。

pre-v1契約・reportは保守的な明示migration readerで読み、未記録の来歴を再構成しません。
`ari.calibration/evaluator_v1.json`はnumeric、unit、formula、evidence、policyのCIケースと、
人手ラベル付きsemantic positive/negative controlを保持します。公開APIは
`ari.public.evaluation`、schemaは`ari-core/ari/schemas/`です。
