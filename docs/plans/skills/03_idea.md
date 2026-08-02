---
sources:
  - path: ari-skill-idea/src/server.py
    role: implementation
  - path: ari-skill-idea/src/virsci_runtime.py
    role: implementation
  - path: ari-skill-idea/REQUIREMENTS.md
    role: doc
  - path: ari-skill-idea/mcp.json
    role: config
last_verified: 2026-08-01
---

# C03: `ari-skill-idea` 実装計画

> 状態: Implemented（2026-08-02）。マスター計画は [00_master_plan.md](00_master_plan.md)。本書はP6削除監査までの一時計画である。

## 1. 責務

研究目標、prior-work snapshot、ancestor evidenceから、検証可能な仮説候補とidea-owned research contractを生成する。文献取得そのもののownerは `ari-skill-web`、metric enforcementのownerは `ari-skill-evaluator` とし、本componentは「なぜこの仮説と測定契約を選んだか」を所有する。

## 2. 現状と課題

- `survey` と `generate_ideas`、defaultの再実装discussion loop、opt-in VirSci vendor-wrapが共存する。
- live Semantic Scholar / snapshot / citation traversalのidentityが最終idea provenanceへ一様に残らない。
- `mcp.json`、`skill.yaml`、runtime tool surface、package versionにdriftがある。
- LLM出力を凍結する境界はあるが、model/prompt/sampling/source snapshotの完全なlockが必要である。
- metric / falsifiable claimのownershipがidea、evaluator、transform間に分散している。

## 3. 目標契約

`IdeaSetV1` は各候補について、仮説、反証条件、primary metric、unit、direction、required evidence、comparison scope、prior-work引用、source snapshot digest、generation provenanceを持つ。選択されたideaからmintする`ResearchContractV1`はrun中に語彙を再抽出せず、変更は明示的version migrationだけにする。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C03-01 | runtime tool / manifest / READMEのinventory同期 | canonical manifest、drift CI |
| C03-02 | `SurveySnapshotV1`をweb componentと共通化 | provider、query、取得時刻、result digest、citation edge |
| C03-03 | `IdeaSetV1` / `ResearchContractV1` schema | claim、metric、unit、evidence、limitations |
| C03-04 | default loopとVirSci adapterを同一input/outputへ正規化 | provider-neutral generation adapter |
| C03-05 | prompt/model/sampling/vendor commitをlockへ記録 | idea generation provenance |
| C03-06 | ancestor contextにartifact-backed entryだけを区別表示 | memory provenance integration |
| C03-07 | invalid / duplicate / non-falsifiable ideaのdeterministic preflight | rejection reason付きcandidate set |
| C03-08 | record/replay fixtureとablation | same snapshot replay、loop別比較 |

## 5. 受け入れ基準

- [x] 同じfrozen survey、prompt、seed/model条件でinput digestとcandidate provenanceが一致する。
- [x] live retrievalを使ったrunはbyte reproducibleと表示されず、snapshot artifactを持つ。
- [x] 採用ideaは少なくとも一つの反証条件、metric contract、required evidenceを持つ。不完全候補は理由付きでrejectする。
- [x] evaluatorがidea contractを再生成せず、同じcontract digestを使用する。
- [x] default loopとVirSci pathが同じschemaを満たし、consumer側分岐がない。
- [x] citationのない主張、存在しないartifact reference、不明unitがpreflightで明示される。
- [x] `pytest ari-skill-idea/tests -q` とmanifest contract testがgreenである。

実装証跡: `ari.public.research_contract`、生成JSON Schema、
`ari-skill-idea/src/contracts.py`、offline replay/tamper/parity tests、
`ari-skill-evaluator`のtyped-contract優先経路。C03-02の共通schema公開は完了し、
`ari-skill-web` producer側の採用はC04で行う。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C03-D1 | **削除済み**: record/replay中の暗黙live retrieval fallback | `SurveySnapshotV1` | P3 | offline replay、snapshot欠落時fail-closed |
| C03-D2 | **新runから削除済み**: evaluator側でidea語彙を再抽出するpath（旧checkpoint readerのみsupport windowまで保持） | immutable `ResearchContractV1` | P3 |旧checkpoint migration fixture、new run caller 0 |
| C03-D3 | **削除済み**: default loopとVirSci pathに重複するoutput normalization |共通adapter | P3 |両path contract test parity |
| C03-D4 | **削除済み**: manifestに残る未実装・旧tool declaration | canonical runtime-derived manifest update | P1 | `tools/list` conformance、workflow reference 0 |
| C03-D5 | **削除済み**: unversioned vendor/snapshot path selection | pinned adapter / snapshot ref | P5 | vendor commitとlicense lock、clean install fixture |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-idea/tests -q`、frozen-survey replay、manifest conformance、対象referenceへの `rg` を実行する。削除前のprompt/snapshot/vendor pinとcommitをrollback基点にし、旧idea/metric contract readerはsupport window中migration fixtureと共に保持する。

### 6.3 計画書自身の削除

C03-01〜08、受け入れ基準、C03-D1〜D5を完了し、idea schemaと運用を恒久referenceへ移した後、最終cleanup PRで削除する。
