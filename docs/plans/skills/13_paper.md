---
sources:
  - path: ari-skill-paper/src/server.py
    role: implementation
  - path: ari-skill-paper/src/claim_links.py
    role: implementation
  - path: ari-skill-paper/src/review_engine.py
    role: implementation
  - path: ari-skill-paper/REQUIREMENTS.md
    role: doc
last_verified: 2026-08-01
---

# C13: `ari-skill-paper` 実装計画

> 状態: Completed (2026-08-02)。マスター計画は [00_master_plan.md](00_master_plan.md)。恒久仕様は [Paper build contract](../../reference/paper_build_contract.md) へ移管済み。本書はP6最終cleanupで削除する。

## 1. 責務

verified science data、references、figures、EAR identityからLaTeX paperを生成し、compile、format check、rubric review、claim link、refinement、code availability injectionを行う。実行データの正しさはhard gate、visual qualityはVLM、再現実行はpaper-reの責務である。

## 2. 現状と課題

- 約3,000行の`server.py`にtemplate、BibTeX、generation、compile、review、claim link、refine、availabilityが集中する。
- manifestとruntime tool list/versionにdriftがある。
- claim parsingの一部がcore hard gate側のLaTeX parserとmirrorされる。
- legacy rubric fallback、per-section API、whole-document APIが共存し、ownerとsupport policyが不明確である。
- LLM生成物、review、refinementでmodel/prompt/input/evidence digestを一貫して追跡する必要がある。

## 3. 目標契約

`PaperBuildV1`はinput artifact set、venue/template/rubric digest、model/prompt、draft revisions、compile log、claim links、gate reports、final PDF/TeX/BibTeX digestを持つ。writerは`ScienceDataV1`に存在しないnumeric assertionを自由に作らず、claim anchorをrevision間で維持する。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C13-01 | 完了: manifest/runtime/docs同期 |全tool、version、LLM/side-effect metadata |
| C13-02 | 完了: runtime責務分割 | authoring、compiler、review、claim、finalize modules。MCP composition/template formattingのみserverに保持 |
| C13-03 | 完了: PaperBuild schema | revision lineage、input/output digest、status |
| C13-04 | 完了: evidence-only numeric authoring | metric/claim registry injection、unregistered number detection |
| C13-05 | 完了: shared LaTeX/claim parser | core gateとの一つのcanonical implementation |
| C13-06 | 完了: compile sandbox | command allowlist、resource limit、full logs/artifacts |
| C13-07 | 完了: rubric/venue contract versioning | template/rubric hash、offline legacy migration |
| C13-08 | 完了: review independence | text/VLM/semantic/hard-gate結果を別fieldでmerge |
| C13-09 | 完了: deterministic finalize | code availability、claim final gate、artifact lock |

## 5. 受け入れ基準

- [x] final paperの全numeric claimがclaim linkまたは明示excluded policyを持つ。
- [x] hard gate blocking errorがあるstrict runでfinalizeしない。
- [x] revision後もclaim anchor、math、citation key、figure IDが保持される。
- [x] template/rubric/model/prompt/input/EAR digestがbuild recordに残る。
- [x] compile timeout/errorのfull logをartifact化し、orphan processを残さない。
- [x] independent text review、VLM、semantic reviewを一つのscoreへ不可逆に潰さない。
- [x] legacy venue/rubric fixtureを明示migration pathで読める。
- [x] `pytest ari-skill-paper/tests -q` とend-to-end paper fixtureがgreenである（124 passed、core contractを含む統合139 passed）。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C13-D1 (deleted) | paper/coreに重複するLaTeX numeric/anchor parser | canonical shared parser | P3 |shared corpus parity、duplicate code reference 0 |
| C13-D2 (deleted) | unversioned built-in `legacy` rubric fallback | versioned explicit rubric | P6 |offline migration fixture、runtime fallback 0 |
| C13-D3 (deleted) | structured `ScienceDataV1`を迂回するgeneric metric fallback | evidence-only authoring | P3 |numeric coverage corpus、new run caller 0 |
| C13-D4 (deleted) | raw subprocess compile implementation | common execution sandbox | P3 |compile parity、process cleanup test |
| C13-D5 (deleted) | runtime未公開/未使用のlegacy per-section API | supported public API set | P6 |恒久migration note、workflow/docs caller 0 |
| C13-D6 (deleted) | inline-only LLM/review response | artifact-backed `PaperBuildV1` | P2 |replay/audit fixture |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-paper/tests -q`、end-to-end compile、claim/gate corpus、legacy venue/rubric migration、対象referenceへの `rg` を実行する。旧template/rubric/parser削除前commitをrollback基点にし、公開済みpaper build readerはsupport window中保持する。

### 6.3 計画書自身の削除

C13-01〜09、受け入れ基準、C13-D1〜D6を閉じ、paper build/rubric/migration仕様を恒久referenceへ移した後に削除する。
