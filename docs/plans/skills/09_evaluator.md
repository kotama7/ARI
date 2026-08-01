---
sources:
  - path: ari-skill-evaluator/src/server.py
    role: implementation
  - path: ari-skill-evaluator/REQUIREMENTS.md
    role: doc
  - path: ari-core/ari/pipeline/claim_gate/gate.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-01
---

# C09: `ari-skill-evaluator` 実装計画

> 状態: Proposed。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

idea-owned research contractからmetric specificationをmintし、実行証拠とpaper claimの客観的一致をdeterministic hard gateで検査し、解釈上のoverclaimを独立したadvisory LLM reviewで指摘する。単一scalarの「科学品質」を真実として生成しない。

## 2. 現状と課題

- `make_metric_spec`、`claim_evidence_hard_gate`、`evidence_grounded_semantic_review`を提供する。
- workflow metadataにはruntimeで公開されない`evaluate_node`参照が残る。
- deterministic parserとLLM fallback、idea/checkpointからのclaim再抽出が一serverに混在する。
- server末尾に参照されない可能性があるartifact extractor helperが残り、dead-code監査が必要である。
- hard gateはcore implementationのthin wrapperである一方、schema/version ownershipを明確にする必要がある。

## 3. 目標契約

- `MetricContractV1` はmint-onceで、metric、unit、direction、formula、operands、tolerance、required evidenceを持つ。
- hard gateは`GateReportV1`を返し、blocking findingとadvisory findingを型で分ける。
- semantic reviewはhard gateの数値判定を上書きせず、model/prompt/evidence digestを記録する。
- contract confidenceが不足する場合は自動で科学的admissionを上げず、人手確認対象にする。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C09-01 | runtime/workflow/manifest同期 | stale `evaluate_node`解消、canonical manifest |
| C09-02 | metric contract schemaをidea/transformと共有 | immutable digest、migration reader |
| C09-03 | deterministic mintとLLM提案を分離 | parser result、proposal、admission decision |
| C09-04 | hard gate API/version固定 | typed finding、policy digest、formula provenance |
| C09-05 | semantic reviewer independence | separate model/prompt、hard-gate非改変保証 |
| C09-06 | evidence/artifact resolver統合 | missing/tampered/cross-run evidence rejection |
| C09-07 | calibration corpus | numeric、unit、formula、overclaim、negative controls |
| C09-08 | dead code / duplicate ownership audit | reference graph、削除PR候補 |

## 5. 受け入れ基準

- [ ] first mint後にLLM再実行でcontract vocabularyが変わらない。
- [ ] numeric mismatch、operand unresolved、missing evidenceをdeterministically再現する。
- [ ] unit conversionは許可listとconversion provenanceを持ち、未知unitを推測しない。
- [ ] semantic review failureやtimeoutがhard gateの結果を成功へ変えない。
- [ ] cross-run artifact、digest mismatch、存在しないnodeをblocking findingにする。
- [ ] warn/strict/off policyとfinalize dependencyをintegration testする。
- [ ] workflowに存在しないtool referenceが0である。
- [ ] `pytest ari-skill-evaluator/tests -q` とcore claim-gate testsがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C09-D1 | workflowのstale `evaluate_node` reference |実在contract toolまたはcore evaluator path | P1 |workflow conformance、runtime behavior fixture |
| C09-D2 | new runでのidea claim再抽出fallback | immutable `MetricContractV1` | P3 |new caller 0、old checkpoint migration fixture |
| C09-D3 | deterministic mint内部のimplicit LLM fallback |明示proposal/admission step | P3 |offline deterministic test、UI/CLI確認経路 |
| C09-D4 |参照0の`_build_artifact_extractor_source`等private helper | none | P3 |static reference graph、targeted tests、coverage確認 |
| C09-D5 | hard gate schemaのskill側duplicate model | `ari.public.claim_gate` canonical model | P3 |serialization parity、consumer migration |
| C09-D6 |旧env model-resolution alias | canonical manifest/model policy | P6 |deprecation release、docs/caller 0 |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-evaluator/tests -q`、core claim-gate corpus、workflow conformance、old contract migration、対象referenceへの `rg` を実行する。削除前contract/schema/commitをrollback基点にし、published paperを検証する旧gate readerはsupport window中保持する。

### 6.3 計画書自身の削除

C09-01〜08、全受け入れ基準、C09-D1〜D6を完了し、metric/gate仕様とcalibration corpusを恒久資産へ移した後に削除する。
