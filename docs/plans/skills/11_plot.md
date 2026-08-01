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
last_verified: 2026-08-01
---

# C11: `ari-skill-plot` 実装計画

> 状態: Proposed。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

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
| C11-01 | manifest / tool schema同期 | canonical deterministic/stochastic metadata |
| C11-02 | FigureSpec / Manifest schema | units、uncertainty、source pointers、digests |
| C11-03 | deterministic renderer test corpus | line/bar/scatter/hist/error bars/empty data |
| C11-04 | generated-code sandbox統合 | coding execution contract、no network、resource limit |
| C11-05 | static/data-integrity checks | input mutation、hard-coded data、path escape検出 |
| C11-06 | VLM feedback loop versioning | feedback digest、iteration cap、before/after artifacts |
| C11-07 | benchmark plot migration | canonical figure pathへconsumer移行 |
| C11-08 | reproducible rendering | font/matplotlib/backend/container identity |

## 5. 受け入れ基準

- [ ] deterministic rendererのgolden data/semantic manifest testがある。
- [ ] generated codeはnetwork、workspace外read/write、process escapeを行えない。
- [ ] generated codeがsource valuesをhard-codeまたは変更した場合failする。
- [ ] axis labelにunitが必要なmetricで欠落を検出する。
- [ ] figureからsource record/node/artifact digestへ辿れる。
- [ ] VLM loopはmax iterationを守り、以前のfigureを上書きせず保持する。
- [ ] benchmark `plot`削除後も全pipeline figure fixtureがgreenである。
- [ ] 新設する`ari-skill-plot/tests` とmanifest contract testがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C11-D1 | private `_run_plot_code` process sandbox | common coding/execution interface | P3 |security/parity fixture、direct subprocess caller 0 |
| C11-D2 | schemaなしのlegacy figure manifest keys | `FigureManifestV1` | P6 |paper/VLM consumer migration、old reader fixture |
| C11-D3 | benchmark側のduplicated `plot` tool |本component renderer | P3 |C07-D1 gate完了 |
| C11-D4 | LLM caption passのimplicit VLM call |明示VLM review/caption stage | P3 |cost/provenance trace、default path LLM call 0 |
| C11-D5 | generated codeをinline resultだけに保持するpath | artifact-backed source/code | P2 |replay fixture、digest復元 |

### 6.2 削除の検証と復旧

各 deletion PR はfigure golden/semantic tests、generated-code sandbox、paper/VLM integration、benchmark parity、対象referenceへの `rg` を実行する。旧manifest/renderer削除前commitをrollback基点にし、published figure manifest readerはsupport window中保持する。

### 6.3 計画書自身の削除

C11-01〜08、全受け入れ基準、C11-D1〜D5を完了し、figure schemaとsandbox仕様を恒久referenceへ移した後に削除する。
