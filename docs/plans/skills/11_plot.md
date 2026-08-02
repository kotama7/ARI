---
sources:
  - path: ari-skill-plot/src/server.py
    role: implementation
  - path: ari-skill-plot/skill.yaml
    role: config
  - path: ari-skill-plot/mcp.json
    role: config
  - path: ari-skill-vlm/src/server.py
    role: implementation
last_verified: 2026-08-02
---

# C11: `ari-skill-plot` 実装計画

> 状態: Completed (2026-08-02)。恒久仕様は [figure/visual contract](../../reference/figure_visual_contract.md) へ移管済み。本書はP6最終cleanupで削除する。

## 1. 責務

typed science dataからscientific figureを生成し、source data、render specification、code、library/environment、caption、image/PDF digestを持つ`FigureManifestV1`を返す。visual quality判断は`ari-skill-vlm`が所有する。

## 2. 現状と課題

- deterministic `generate_figures` とLLM code generation `generate_figures_llm`がある。
- generated codeをlocal helper `_run_plot_code`で実行するが、coding/core sandboxとの共通contractがない。
- package-level automated testがない。
- benchmarkの`plot` toolと責務が重複する。
- 「同じmatplotlibならbyte deterministic」という条件をenvironment digestとして記録する必要がある。

## 3. 目標契約

`FigureSpecV1`はchart type、source columns/units、aggregation、uncertainty、scale、style policyを宣言する。LLMはspec/codeを提案できるが、data valueを書き換えず、sandboxとstatic policyを通す。`FigureManifestV1`はsource data sliceとrender artifactを双方向に追跡できる。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C11-01 | 完了: manifest / tool schema同期 | canonical deterministic/stochastic metadata |
| C11-02 | 完了: FigureSpec / Manifest schema | units、uncertainty、source pointers、digests |
| C11-03 | 完了: deterministic renderer test corpus | line/bar/scatter/hist/error bars/negative data |
| C11-04 | 完了: generated-code path削除 | fixed declarative renderer、closed workspace、resource bound |
| C11-05 | 完了: static/data-integrity checks | data digest、field/unit/path検証 |
| C11-06 | 完了: VLM feedback loop versioning | feedback digest、iteration cap、before/after artifacts |
| C11-07 | 完了: benchmark plot migration | canonical figure pathへconsumer移行 |
| C11-08 | 完了: reproducible rendering | font/matplotlib/backend/container identity |

## 5. 受け入れ基準

- [x] deterministic rendererのgolden data/semantic manifest testがある。
- [x] runtimeはgenerated codeを実行せず、network、workspace外I/O、process escape面を公開しない。
- [x] specのsource values変更、hard-code相当のdigest不一致をfailする。
- [x] axis label/unit/field整合性を検証する。
- [x] figureからsource record/node/artifact digestへ辿れる。
- [x] VLM loopはmax iterationを守り、以前のfigureを上書きせず保持する。
- [x] benchmark `plot`削除後も全pipeline figure fixtureがgreenである。
- [x] `pytest ari-skill-plot/tests -q` とmanifest contract testがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C11-D1 (deleted) | private `_run_plot_code` process sandbox | fixed declarative renderer | P3 |security/parity fixture、direct subprocess caller 0 |
| C11-D2 (deleted producer) | schemaなしのlegacy figure manifest keys | `FigureManifestV1` + isolated read-only reader | P6 |paper/VLM consumer migration、old reader fixture |
| C11-D3 (deleted) | benchmark側のduplicated `plot` tool |本component renderer | P3 |C07-D1 gate完了 |
| C11-D4 (deleted) | LLM caption passのimplicit VLM call |明示VLM review stage | P3 |cost/provenance trace、default path LLM call 0 |
| C11-D5 (deleted) | generated codeをinline resultだけに保持するpath | artifact-backed declarative spec | P2 |replay fixture、digest復元 |

### 6.2 削除の検証と復旧

各 deletion PR はfigure golden/semantic tests、generated-code sandbox、paper/VLM integration、benchmark parity、対象referenceへの `rg` を実行する。旧manifest/renderer削除前commitをrollback基点にし、published figure manifest readerはsupport window中保持する。

### 6.3 計画書自身の削除

C11-01〜08、全受け入れ基準、C11-D1〜D5を完了し、figure schemaとsandbox仕様を恒久referenceへ移した後に削除する。
