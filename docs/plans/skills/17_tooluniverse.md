---
sources:
  - path: docs/plans/skills/02_tool_registry.md
    role: doc
  - path: ari-core/ari/mcp/client.py
    role: implementation
  - path: docs/reference/skills.md
    role: doc
last_verified: 2026-08-01
---

# C17: ToolUniverse collection adapter 実装計画

> 状態: Proposed / new integration component。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

ToolUniverseを`ari-skill-tool-registry`の一つの`CompactCollectionProvider`として同期・実行する。ToolUniverseの内部modelをARIのcanonical schema、registry、trust boundaryにはしない。

## 2. Integration原則

- collection package/repository/dependency closureをimmutable version/digestでpinする。
- compact discovery/info/execute surfaceからleaf descriptorをgenerated candidateへ展開する。
- runtimeはlock済みleaf referenceだけをexecuteし、category全体の動的autoloadを許可しない。
- record modeはstrict input validation、明示default、implicit coercion禁止を要求する。
- ToolUniverse cacheはoptimizationであり、ARI cassette/EARをprovenance authorityにする。
- collectionのreview/trustをleaf toolの科学admissionへ推移させない。

## 3. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C17-01 | pinned integration spike | supported version、dependency/license inventory |
| C17-02 | compact discovery adapter | list/search/infoからcandidate descriptor生成 |
| C17-03 | strict invocation adapter | explicit defaults、schema validation、raw result artifact |
| C17-04 | leaf provenance extraction | implementation/data/API/source identityとorigin chain |
| C17-05 | category/admission profiles | read-only data、local compute、remote API、ML等のpolicy |
| C17-06 | cache/cassette semantics | hit/miss/source metadata、empty/auth failureのfail-loud |
| C17-07 | bulk update workflow | candidate diff、changed schema quarantine、lock regeneration |
| C17-08 | scale/conformance | large approved subset、rate limit、pagination、replay |

## 4. 受け入れ基準

- [ ] collection-level adapter一つでapproved tool群をimportし、leafごとのARI codeを追加しない。
- [ ] ToolUniverse updateがreviewable candidate/lock diffになり、running experimentを変えない。
- [ ] leaf implementation/data source不明のtoolをscientifically admittedにしない。
- [ ] implicit type coercion、unknown field、missing required fieldをrecord modeで拒否する。
- [ ] internal cache hitでもsource/version/acquisition identityを記録する。
- [ ] auth failure/empty resultをvalid cassetteとして保存しない。
- [ ] direct MCP providerと同じdiscover/result contractで混在できる。
- [ ] offline replayがToolUniverse package/serverなしで成功する。

## 5. 削除要件

### 5.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C17-D1 | leaf toolごとのwrapper/config/whitelist prototype | compact collection adapter + generated lock | P5 |approved setのmanual leaf code 0 |
| C17-D2 | ToolUniverse固有概念をARI public 5-tool APIへ露出するfield | provider-neutral descriptor extension | P5 |generic/direct provider conformance |
| C17-D3 | dynamic external MCP autoload | explicit source sync/admission | P5 |runtime network discovery 0、lock test |
| C17-D4 | refresh-on-launch / unpinned install path | pinned environment | P5 |clean/offline install、digest verification |
| C17-D5 | ToolUniverse cacheだけをreplay authorityにするpath | ARI cassette/EAR | P5 |cache-disabled record/replay fixture |
| C17-D6 | permissive coercionをrecord modeで許すcompat path | strict validator | P5 |type confusion corpus、live-only例外もpolicy化 |

### 5.2 削除の検証と復旧

各 deletion PR はbulk import、strict validation、cache on/off、provider outage、offline replay、generic-provider conformance、対象referenceへの `rg` を実行する。削除前adapter/package pinとcatalog fixtureをrollback基点にし、archived lock/cassette readerはsupport window中保持する。

### 5.3 計画書自身の削除

C17-01〜08、全受け入れ基準、C17-D1〜D6を閉じ、adapter support matrix、update手順、admission profileを恒久文書へ移した後に削除する。
