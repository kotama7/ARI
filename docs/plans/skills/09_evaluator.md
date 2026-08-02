---
sources:
  - path: ari-skill-evaluator/src/server.py
    role: implementation
  - path: ari-skill-evaluator/REQUIREMENTS.md
    role: doc
  - path: ari-core/ari/pipeline/claim_gate/gate.py
    role: implementation
  - path: ari-core/ari/claim_gate_contract.py
    role: schema
  - path: ari-core/ari/calibration/evaluator_v1.json
    role: test
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-01
---

# C09: `ari-skill-evaluator` 実装計画

> 状態: Completed (2026-08-02) — C09-01〜08とC09-D1〜D6を完了。恒久仕様は [evaluation_contract.md](../../reference/evaluation_contract.md)。本書はP6の計画書一括cleanupで削除する。

## 1. 責務

idea-owned research contractからmetric specificationをmintし、実行証拠とpaper claimの客観的一致をdeterministic hard gateで検査し、解釈上のoverclaimを独立したadvisory LLM reviewで指摘する。単一scalarの「科学品質」を真実として生成しない。

## 2. 現状と課題

- `make_metric_spec`、`claim_evidence_hard_gate`、`evidence_grounded_semantic_review`を提供する。
- workflowは非MCPのcore BFTS evaluator pathを空toolで明示し、manifest checkerが全非空参照を検証する。
- deterministic mint、明示LLM proposal、人手admissionは別tool/recordとなり、暗黙fallbackは存在しない。
- dead artifact extractorとclaim/flag re-extraction helper/promptを削除し、負のreference testで固定した。
- hard gate/semantic review/admission schemaは`ari.public.evaluation`が単独所有する。

## 3. 目標契約

- `MetricContractV1` はmint-onceで、metric、unit、direction、formula、operands、tolerance、required evidenceを持つ。
- hard gateは`GateReportV1`を返し、blocking findingとadvisory findingを型で分ける。
- semantic reviewはhard gateの数値判定を上書きせず、model/prompt/evidence digestを記録する。
- contract confidenceが不足する場合は自動で科学的admissionを上げず、人手確認対象にする。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C09-01 | **完了**: runtime/workflow/manifest同期 | stale `evaluate_node`解消、canonical manifest |
| C09-02 | **完了**: metric contract schemaをidea/transformと共有 | immutable digest、migration reader |
| C09-03 | **完了**: deterministic mintとLLM提案を分離 | parser result、proposal、admission decision |
| C09-04 | **完了**: hard gate API/version固定 | typed finding、policy digest、formula provenance |
| C09-05 | **完了**: semantic reviewer independence | separate model/prompt、hard-gate非改変保証 |
| C09-06 | **完了**: evidence/artifact resolver統合 | missing/tampered/cross-run evidence rejection |
| C09-07 | **完了**: calibration corpus | numeric、unit、formula、overclaim、negative controls |
| C09-08 | **完了**: dead code / duplicate ownership audit | reference graph、削除済みhelper/prompt |

## 5. 受け入れ基準

- [x] first mint後にLLM再実行でcontract vocabularyが変わらない。
- [x] numeric mismatch、operand unresolved、missing evidenceをdeterministically再現する。
- [x] unit conversionは許可listとconversion provenanceを持ち、未知unitを推測しない。
- [x] semantic review failureやtimeoutがhard gateの結果を成功へ変えない。
- [x] cross-run artifact、digest mismatch、存在しないnodeをblocking findingにする。
- [x] warn/strict/off policyとfinalize dependencyをintegration testする。
- [x] workflowに存在しないtool referenceが0である。
- [x] `pytest ari-skill-evaluator/tests -q` とcore claim-gate testsがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C09-D1 | **完了**: workflowのstale `evaluate_node` reference | core evaluator path | P1 |workflow conformance、runtime behavior fixture |
| C09-D2 | **完了**: new runでのidea claim再抽出fallback | immutable `MetricContractV1` | P3 |new caller 0、old checkpoint migration fixture |
| C09-D3 | **完了**: deterministic mint内部のimplicit LLM fallback |明示proposal/admission step | P3 |offline deterministic test、確認経路 |
| C09-D4 | **完了**: `_build_artifact_extractor_source`等private helper | none | P3 |static reference graph、targeted tests |
| C09-D5 | **完了**: hard gate schemaのskill側duplicate model | `ari.public.evaluation` canonical model | P3 |serialization parity、consumer migration |
| C09-D6 | **完了**: evaluator-skillの旧env model-resolution alias | dedicated proposal/semantic model policy | P6 |manifest/docs/runtime caller 0 |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-evaluator/tests -q`、core claim-gate corpus、workflow conformance、old contract migration、対象referenceへの `rg` を実行する。削除前contract/schema/commitをrollback基点にし、published paperを検証する旧gate readerはsupport window中保持する。

### 6.3 計画書自身の削除

C09-01〜08、全受け入れ基準、C09-D1〜D6を完了し、metric/gate仕様とcalibration corpusを恒久資産へ移した後に削除する。

### 6.4 完了記録 (2026-08-02)

- `MetricContractV1`へunit、formula、operand、tolerance、correctness、invariant、
  confidence、admission、canonical digestを追加し、Idea/Transform/Evaluatorを同じ
  `ari.public` contractへ移した。
- deterministic `make_metric_spec`、明示`propose_metric_contract`、名前付きhuman
  admissionを分離し、proposal/model/prompt/evidence/decision digestを固定した。
- `GateReportV1`をrun/policy/evidence/formula implementation/unit conversion digestへ
  bindingし、exact-run typed measurementとartifact SHA-256だけを証拠として採用する。
- semantic reviewerを専用model/promptへ分離し、失敗を`unavailable`とし、hard-gate
  bytes非改変をtestした。
- pre-v1 metric/gate reader、v1 JSON Schema、日英中の恒久仕様、numeric/unit/formula/
  evidence/policy/overclaimのpositive/negative calibration corpusを追加した。
- 旧extractor/helper/prompt、implicit LLM、skill側schema duplicate、stale workflow tool、
  evaluator固有の旧model aliasを削除した。global `ARI_MODEL_EVAL`はcore BFTS/lineageの
  別owner互換性として本componentの削除対象外である。
