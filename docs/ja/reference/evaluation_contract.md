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
last_verified: 2026-08-17
---

# 科学評価契約

ARIは、科学的な採用、客観的な証拠検査、意味上の助言を別の層として扱います。
これらの層は意図的に互換ではありません。

## metricの採用

`MetricContractV1`はmetric名、unit、direction、comparison scope、formula、operand、
tolerance、必須測定、correctness、invariant、formula provenanceをdigest付きで固定します。
科学的fieldが一つでも変わればcanonical digestも変わります。evaluatorは採用済みの
idea所有契約を`MetricGateContractV1`へ射影し、一度だけ永続化します。

旧入力へのLLM出力は`MetricContractProposalV1`に留まり、model・revision・prompt・evidence・
ideaのdigestを記録します。名前付きreviewerが`MetricAdmissionDecisionV1`を作るまで科学契約には
昇格しません。決定論的parserの出力はその判断の材料であって、採用の近道ではありません。

## 決定論的hard gate

決定論的hard gateは`GateReportV1`を返します。run、policy、evidence、metric contract、
数式実装、制限付き式評価器、許可されたunit変換のdigestを固定し、型付きの
`blocking_findings`と`advisory_findings`を分離します。

canonical runでは同じrun/nodeの`MeasurementSetV1`と、
run id・node id・相対path・SHA-256を持つartifactだけを使用します。欠落、改変、未bind、
cross-run、untypedな証拠を推測しません。unit変換は次元を保つ閉じたregistryで行い、
未知unitは失敗します。`off`は所見を記録してもblockせず、
final phaseだけがfinalizeを止められます。

このgateが検証するのは証拠のidentityと、論文から結果への導出です。装置、simulator、
benchmark設計、科学的仮説が外的に妥当であることを証明するものではありません。

## 意味上の助言

`SemanticReviewV1`は独立model/revision、prompt digest、evidence digest、変更不能な
hard-gate report digestを記録する非ブロッキング助言です。overclaim、overgeneralization、
根拠のない主張、interpretation、visual semanticsを指摘できます。hard gateを変更できず、
失敗は捏造された成功ではなく`status: unavailable`として表現されます。

## 互換性とcalibration

readerはv1のdigestをすべて検証します。pre-v1契約・reportは保守的な明示migration readerで
読み、既存fileを上書きせず、記録されていない来歴を再構成しません。
`ari.calibration/evaluator_v1.json`はnumeric、unit、formula、evidence、policyのCIケースと、
人手ラベル付きsemantic positive/negative controlを保持します。

公開APIは`ari.public.evaluation`（`ari.public.claim_gate`からも再exportされます）、
schemaは`ari-core/ari/schemas/`です。
