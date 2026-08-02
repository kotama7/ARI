---
sources:
  - path: ari-skill-benchmark/src/server.py
    role: implementation
  - path: ari-skill-benchmark/REQUIREMENTS.md
    role: doc
  - path: ari-skill-benchmark/mcp.json
    role: config
  - path: ari-skill-plot/src/server.py
    role: implementation
last_verified: 2026-08-02
---

# C07: `ari-skill-benchmark` 実装計画

> 状態: Completed (2026-08-02) — C07-01〜07とC07-D1〜D5を完了。恒久仕様は [analysis_contract.md](../../reference/analysis_contract.md) へ移行済み。本書はP6の計画書一括cleanupで削除する。

## 1. 責務

実験measurementに対するdeterministic summary、statistical test、run comparisonを所有する。figure renderingは`ari-skill-plot`、scientific acceptance gateは`ari-skill-evaluator`の責務とする。

## 2. 現状と課題

- `analyze_results`、`plot`、`statistical_test`を提供するが、REQUIREMENTSには未実装の`compare_runs`が記載されている。
- `plot`は`ari-skill-plot`と責務が競合する。
- file path入力とarray入力、NaN、missing unit、sample independence、multiple testingの扱いがschema化されていない。
- numerical library/versionとtest assumptionが結果provenanceへ十分残らない。

## 3. 目標契約

`AnalysisRequestV1`はmetric identity、unit、samples、pairing/grouping、missing policy、test family、alpha、correction、alternative hypothesisを明示する。`AnalysisResultV1`はeffect size、confidence interval、test statistic、p-value、assumption diagnostics、library versions、input digestを返す。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C07-01 | manifest/requirements/runtime同期 | canonical tool inventory |
| C07-02 | typed data loader | JSON/CSV/npyのschema、unit/missing policy |
| C07-03 | statistical contract | paired/unpaired、normality、effect size、CI |
| C07-04 | multiple comparisonとpre-registration link | correction、analysis plan digest |
| C07-05 | run comparison | environment compatibilityとprovenance差分 |
| C07-06 | ResultEnvelope / artifact出力 | table、machine JSON、input/library digest |
| C07-07 | property/golden tests | edge case、large/small sample、NaN、constant data |

## 5. 受け入れ基準

- [x] unit不一致、paired length不一致、空sample、全NaNを明示errorにする。
- [x] p-valueだけでなくeffect size、CI、sample count、assumptionを返す。
- [x] random手法を追加する場合seedとlibrary versionを記録する。
- [x] 同一backend/環境由来のrunを独立replicateと誤表示しない。
- [x] benchmarkからfigure renderingを除いてもplot pipelineが同等artifactを生成する。
- [x] scipy/numpy reference fixtureとproperty testがgreenである。
- [x] `pytest ari-skill-benchmark/tests -q` とmanifest contract testがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C07-D1 | public `plot` toolとmatplotlib依存 | `ari-skill-plot` | P3 |plot golden parity、workflow/external deprecation、caller 0 |
| C07-D2 | requirementsの未実装`compare_runs`宣言 |実装済みtyped comparisonまたは宣言削除 | P1 |manifest/runtime/docs一致 |
| C07-D3 | schemaなしのad-hoc file parsing | typed data loader | P3 |全format fixture、invalid input fail |
| C07-D4 | significance boolだけに依存するlegacy result key | `AnalysisResultV1` | P6 |consumer migration、old reader fixture |
| C07-D5 | plot削除後の未使用matplotlib dependency | none | P3 |clean install/test、dependency graph reference 0 |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-benchmark/tests -q`、numerical golden/property tests、plot pipeline parity、clean dependency install、対象referenceへの `rg` を実行する。公開result/tool削除前commitをrollback基点にし、旧result readerはsupport window中保持する。

### 6.3 計画書自身の削除

C07-01〜07、受け入れ基準、C07-D1〜D5を完了し、統計契約とmigrationを恒久referenceへ移した後に削除する。

### 6.4 完了記録 (2026-08-02)

- C07-01〜06: manifest/runtime/requirementsをv0.2へ同期し、`ari.public.analysis`
  の4契約、digest-bound CSV/JSON/npy loader、paired/unpaired test、effect size/CI、
  Bonferroni/Holm/BH、pre-registration digest、environment/provenance比較、JSON/CSV
  artifactを実装した。
- C07-07: SciPy reference、大小sample property、NaN/全欠損/constant、paired、unit、
  correction、artifact replay、shared substrate fixtureを追加した。
- C07-D1/D5: benchmarkの公開`plot`とmatplotlib/pandas依存を削除し、同等以上の
  chart corpusを`plot-skill:render_figure`へ移した。
- C07-D2/D3/D4: `compare_runs`をtyped実装し、schema無しparserとp-value-only公開
  resultを削除した。恒久仕様とrollback境界はanalysis contractへ移した。
