---
sources:
  - path: ari-skill-transform/src/server.py
    role: implementation
  - path: ari-skill-transform/src/claims.py
    role: implementation
  - path: ari-skill-transform/src/schemas/science_data_claims.schema.json
    role: schema
  - path: ari-core/ari/pipeline/claim_gate/numeric.py
    role: implementation
last_verified: 2026-08-01
---

# C10: `ari-skill-transform` 実装計画

> 状態: Proposed。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

BFTS tree、node report、measurement、metric contractをcanonical `ScienceDataV1`へ変換し、EARのgenerate / curate handoffを所有する。publish backend implementationは`ari-core/ari/publish`、paper proseは`ari-skill-paper`が所有する。

## 2. 現状と課題

- `nodes_to_science_data`のみLLMを使い、EAR生成/curate/publish/promoteはdeterministicである。
- node reportを優先しつつ`trace_log`とsource fileをlegacy fallbackとして読む。
- claim formula registryがcore claim gate側にもmirrorされ、drift riskがある。
- 3,000行超のserverにtree walk、LLM extraction、claim、EAR、publish orchestrationが集中する。
- source artifactとLLM summaryの区別をschema上さらに明示する必要がある。

## 3. 目標契約

`ScienceDataV1`はraw measurement、derived value、LLM interpretationを別sectionにし、各fieldにsource pointerとdigestを持つ。derived formulaは一つのcanonical registryから評価し、LLMが数値を新規生成しない。EAR manifestはrun lock、tool refs、provider/admission/cassetteを包含する。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C10-01 | `ScienceDataV1` schema/version | parameters、measurements、claims、limitations、provenance |
| C10-02 | deterministic extraction layer | node report/measurementからraw facts生成 |
| C10-03 | LLM interpretation layer分離 | source factsを変更しないannotation |
| C10-04 | formula registry共通化 | core hard gateと同一evaluator / test vectors |
| C10-05 | EAR manifest拡張 | Skill/CATALOG lock、ResultEnvelope、cassette/admission evidence |
| C10-06 | server module分割 | science data、claims、EAR、publish adapterのowner明確化 |
| C10-07 | old checkpoint migration | trace fallbackをoffline converterへ移行 |
| C10-08 | deterministic bundle tests | file order/mtimeに依存しないdigest |

## 5. 受け入れ基準

- [ ] raw measurementとLLM interpretationをschemaで区別し、paper claimはraw/derived sourceへ辿れる。
- [ ]同じcheckpointから同じ`ScienceDataV1` deterministic sectionとEAR digestを得る。
- [ ] formula test vectorをtransformとhard gateが同じ結果で評価する。
- [ ] missing/tampered node reportをsilent source scanで正当化せず、migration statusを付ける。
- [ ] EARに実行tool lock、input/output artifact digest、selection/admission evidenceが入る。
- [ ] publish backend failureがcurated local bundleを破壊しない。
- [ ] currentとlegacy checkpoint fixturesを明示的readerで処理する。
- [ ] `pytest ari-skill-transform/tests -q` とEAR round-trip testsがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C10-D1 | new runの`trace_log` extraction fallback | canonical `node_report` / measurement records | P3 |new golden run coverage 100%、legacy converter fixture |
| C10-D2 | transform側のmirrored formula implementation | canonical public formula registry | P3 |shared test vector parity、duplicate symbol 0 |
| C10-D3 | LLM outputからnumeric factを採用するpath | deterministic raw/derived layer | P3 |mutation/overclaim negative tests |
| C10-D4 | server.py内のpublish backend直結分岐 | `ari-core` publish interface | P3 |all backend contract tests |
| C10-D5 | legacy checkpoint fallbackのruntime常時分岐 | versioned offline migration reader | P6 |support window、runtime new-path caller 0 |
| C10-D6 | replacement後のunused LLM/parsing dependency | component-specific minimal deps | P6 |clean install、dependency audit |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-transform/tests -q`、formula parity、current/legacy checkpoint、EAR round-trip、対象referenceへの `rg` を実行する。削除前ScienceData/EAR schemaとcommitをrollback基点にし、published bundle用readerはsupport window中保持する。

### 6.3 計画書自身の削除

C10-01〜08、全受け入れ基準、C10-D1〜D6を閉じ、ScienceData/EAR/migration仕様を恒久referenceへ移した後に削除する。
