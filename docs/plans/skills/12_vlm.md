---
sources:
  - path: ari-skill-vlm/src/server.py
    role: implementation
  - path: ari-skill-vlm/mcp.json
    role: config
  - path: ari-skill-vlm/REQUIREMENTS.md
    role: doc
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-01
---

# C12: `ari-skill-vlm` 実装計画

> 状態: Proposed。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

figure/table artifactとpaper contextをmultimodal modelで審査し、evidence-groundedな`VisualReviewV1`を返す。figure生成やpaper本文のrewriteは行わず、問題の検出、severity、対象領域、提案、review provenanceを所有する。

## 2. 現状と課題

- runtimeには`review_figure`、`review_figures_all`、`review_table`があるが`mcp.json`は空で、READMEのfunction名も一部一致しない。
- model outputをJSON parseするfallbackがあり、schema failureとreview successの区別が必要である。
- image path/raster sibling解決がartifact identityではなくfilesystem conventionに依存する。
- VLMのstochastic outputとmodel/provider revisionを記録する共通envelopeがない。
-単一test fileだけでbatch、corrupt image、large image、malicious metadata等のcoverageが不足する。

## 3. 目標契約

`VisualReviewV1`はartifact digest、render variant、context digest、criteria version、issues、severity、region/page/figure ID、model/provider/prompt、raw response artifactを持つ。schema parseに失敗したreviewは成功扱いせずtyped errorにする。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C12-01 | manifest/README/runtime同期 | 3 toolのcanonical declaration |
| C12-02 | artifact resolver統合 | digest-based PNG/PDF/page/LaTeX input |
| C12-03 | strict structured output | JSON schema、repairは別status、raw artifact |
| C12-04 | criterion profiles | figure/table/domain別versioned rubric |
| C12-05 | batching/limits | image size/token/cost/concurrency budget |
| C12-06 | review reproducibility metadata | model revision、sampling、prompt digest |
| C12-07 | paper/plot feedback contract | stable figure ID、iteration lineage |
| C12-08 | test corpus | good/bad/corrupt/oversize/missing-unit/mismatch fixtures |

## 5. 受け入れ基準

- [ ] manifestとlive `tools/list`、READMEが一致する。
- [ ] corrupt/unsupported/oversize artifactをtyped errorとして扱う。
- [ ] review対象artifactとcontextのdigestを必ず記録する。
- [ ] schema-invalid model responseをempty successへ変換しない。
- [ ] batch resultで個別failureを保持し、全体scoreから欠落させない。
- [ ]同一figureのrevision lineageを追跡し、feedbackが別figureに混ざらない。
- [ ] model call costとprovider/model revisionがtraceに残る。
- [ ] `pytest ari-skill-vlm/tests -q` と新しいcontract corpusがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C12-D1 |空/stale `mcp.json` とREADMEの旧function名 | canonical manifest/docs | P1 |live list conformance |
| C12-D2 |filesystem namingでraster siblingを推測する主要path | artifact resolver | P3 |PNG/PDF variant fixtures、caller migration |
| C12-D3 |schema-invalid raw textをbest-effort successにするfallback | typed parse error / explicit repair result | P3 |invalid response corpus |
| C12-D4 |inline base64/raw responseをtraceに残すpath | content-addressed artifact | P2 |secret/size audit、replay fixture |
| C12-D5 |paper側のVLM result ad-hoc normalization | `VisualReviewV1` consumer | P3 |paper integration parity |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-vlm/tests -q`、invalid/oversize artifact corpus、schema failure、paper integration、対象referenceへの `rg` を実行する。旧review schema/parser削除前commitをrollback基点にし、過去review artifact readerはsupport window中保持する。

### 6.3 計画書自身の削除

C12-01〜08、受け入れ基準、C12-D1〜D5を完了し、visual review contractを恒久referenceへ移した後に削除する。
