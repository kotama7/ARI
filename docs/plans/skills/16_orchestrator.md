---
sources:
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/skill.yaml
    role: config
  - path: ari-skill-orchestrator/mcp.json
    role: config
  - path: ari-core/ari/viz/api_orchestrator.py
    role: implementation
last_verified: 2026-08-02
---

# C16: `ari-skill-orchestrator` 実装計画

> 状態: Proposed。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

ARI runを外部clientから非同期に開始、参照、停止し、paper/EAR/artifactを安全に取得するcontrol surfaceを所有する。内部BFTS/post-BFTS engine自体や外部tool federationは所有しない。

## 2. 現状と課題

- runtimeはrun/status/list/children/paper/files/EAR/stop/skills/workflow等11 toolを公開するが、manifestは4 toolだけである。
- custom stdio MCPとcustom HTTP serverの二surfaceを持つ。
- package testが0で、process、recursion、path、stop、concurrency、authの回帰検出がない。
- `read_file`等がrun artifact scopeを厳密に型付けせず、path traversal/secret exposure riskがある。
- run metadataをcheckpoint directory scanで再構築し、durable task stateとidempotencyが弱い。

## 3. 目標契約

`RunRequestV1`、`RunHandleV1`、`RunStatusV1`、`ArtifactRefV1`を定義する。createはidempotency keyとparent/depth policyを持ち、status/stopはdurable state machineに従う。file accessは任意pathではなくallowlisted content-addressed artifact/resourceに限定する。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C16-01 | runtime/manifest/docs inventory | 11 toolのsupport分類とcanonical manifest |
| C16-02 | durable run registry | atomic metadata、state transitions、restart recovery |
| C16-03 | idempotent async API | create/status/stop/result、parent/child lineage |
| C16-04 | artifact/resource API | paper/EAR/logをdigestとroleで取得 |
| C16-05 | auth/authorization | local token/OAuth-ready principal、workspace/run scope |
| C16-06 | recursion/budget policy | depthだけでなくrun/node/cost/resource quota |
| C16-07 | transport adapter | stdio contractをcanonicalにしHTTPをadapter化 |
| C16-08 | federation visibility | lock済みSkill/toolだけをsanitized metadataで表示 |
| C16-09 | test suite | lifecycle、restart、parallel、path、auth、cancel、recursion |

## 5. 受け入れ基準

- [ ]同一idempotency keyのretryでrunを二重起動しない。
- [ ] process restart後もrunning/failed/completed stateを正しく復元する。
- [ ] stopがchild process/jobへ伝播し、terminal stateを一度だけ確定する。
- [ ] run外path、symlink、secret fileをartifact APIから読めない。
- [ ] unauthorized principalが他runのstatus/artifactを取得できない。
- [ ] recursion depth、cost/resource budget超過を起動前に拒否する。
- [ ] stdioとHTTP adapterで同じschema/state semanticsを返す。
- [ ]新設する`ari-skill-orchestrator/tests` とMCP lifecycle suiteがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C16-D1 |任意filenameを受ける`read_file` / directory listing path | scoped `ArtifactRefV1` / MCP resource | P2 |path security tests、paper/EAR consumer migration |
| C16-D2 |checkpoint scanだけでrun stateを推測する主要path | durable run registry | P3 |restart/migration fixture、fallbackはrepair commandへ隔離 |
| C16-D3 |manifestの4-tool限定stale declaration | canonical runtime manifest | P1 |tools/list完全一致 |
| C16-D4 |stdioと別実装のcustom HTTP business logic | shared service + transport adapter | P3 |transport contract parity |
| C16-D5 |非標準HTTP transport | MCP Streamable HTTPまたはdocumented local-only adapter | P6 |client migration、auth parity、deprecation release |
| C16-D6 |workflow/Skillのsecret-bearing raw config返却 | sanitized locked view | P2 |secret scan、authorized debug path分離 |

### 6.2 削除の検証と復旧

各 deletion PR はMCP lifecycle、restart、parallel、auth/path、cancel/recursion、transport parity、対象referenceへの `rg` を実行する。旧transport/state reader削除前commitをrollback基点にし、run registry migration/repair commandはsupport window中保持する。

### 6.3 計画書自身の削除

C16-01〜09、全受け入れ基準、C16-D1〜D6を閉じ、orchestrator API、auth、operationsを恒久referenceへ移した後に削除する。
