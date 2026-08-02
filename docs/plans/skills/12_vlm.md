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
last_verified: 2026-08-02
---

# C12: `ari-skill-vlm` 実装計画

> 状態: Completed (2026-08-02)。恒久仕様は [figure/visual contract](../../reference/figure_visual_contract.md) へ移管済み。本書はP6最終cleanupで削除する。

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
| C12-01 | 完了: manifest/README/runtime同期 | 3 toolのcanonical declaration |
| C12-02 | 完了: artifact resolver統合 | digest-based PNG/PDF/table input |
| C12-03 | 完了: strict structured output | JSON schema、typed failure、raw artifact |
| C12-04 | 完了: criterion profiles | figure/table/domain別versioned rubric |
| C12-05 | 完了: batching/limits | image size/token/cost/concurrency budget |
| C12-06 | 完了: review reproducibility metadata | model revision、sampling、prompt digest |
| C12-07 | 完了: paper/plot feedback contract | stable figure ID、iteration lineage |
| C12-08 | 完了: test corpus | good/bad/corrupt/oversize/missing-unit/mismatch fixtures |

## 5. 受け入れ基準

- [x] manifestとlive `tools/list`、READMEが一致する。
- [x] corrupt/unsupported/oversize artifactをtyped errorとして扱う。
- [x] review対象artifactとcontextのdigestを必ず記録する。
- [x] schema-invalid model responseをempty successへ変換しない。
- [x] batch resultで個別failureを保持し、全体scoreから欠落させない。
- [x]同一figureのrevision lineageを追跡し、feedbackが別figureに混ざらない。
- [x] model call costとprovider/model revisionがtraceに残る。
- [x] `pytest ari-skill-vlm/tests -q` とcontract corpusがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C12-D1 (deleted) |空/stale `mcp.json` とREADMEの旧function名 | canonical manifest/docs | P1 |live list conformance |
| C12-D2 (deleted) |filesystem namingでraster siblingを推測する主要path | artifact resolver | P3 |PNG/PDF variant fixtures、caller migration |
| C12-D3 (deleted) |schema-invalid raw textをbest-effort successにするfallback | typed parse error | P3 |invalid response corpus |
| C12-D4 (deleted) |inline base64/raw responseをtraceに残すpath | content-addressed artifact | P2 |secret/size audit、replay fixture |
| C12-D5 (deleted) |paper側のVLM result ad-hoc normalization | `VisualReviewV1` consumer | P3 |paper integration parity |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-vlm/tests -q`、invalid/oversize artifact corpus、schema failure、paper integration、対象referenceへの `rg` を実行する。旧review schema/parser削除前commitをrollback基点にし、過去review artifact readerはsupport window中保持する。

### 6.3 計画書自身の削除

C12-01〜08、受け入れ基準、C12-D1〜D5を完了し、visual review contractを恒久referenceへ移した後に削除する。
