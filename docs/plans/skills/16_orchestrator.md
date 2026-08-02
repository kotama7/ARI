---
sources:
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/service.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/registry.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/execution.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/migration.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/runtime.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/contracts.py
    role: schema
  - path: ari-skill-orchestrator/skill.yaml
    role: config
  - path: ari-skill-orchestrator/mcp.json
    role: config
  - path: ari-skill-orchestrator/tests
    role: test
  - path: docs/reference/orchestrator.md
    role: doc
last_verified: 2026-08-02
---

# C16: `ari-skill-orchestrator` 実装計画

> 状態: Completed。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、P6の計画書削除PRで削除する。

## 1. 責務

ARI runを外部clientから非同期に開始、参照、停止し、paper/EAR/artifactを安全に取得するcontrol surfaceを所有する。内部BFTS/post-BFTS engine自体や外部tool federationは所有しない。

## 2. 現状と課題

- v2 runtime/manifestは12 toolで一致し、stdioと標準MCP Streamable HTTPは同じserviceを呼ぶ。
- package suiteはcontract、process、restart、parallel idempotency、path、auth、cancel、recursion、実HTTP clientを含む。
- file APIはpathを受けず、allowlist/index/manifestで検証したSHA-256 artifactだけを返す。
- SQLite registryとrunner receiptが正本であり、directory scanは明示repair commandに隔離した。

## 3. 目標契約

`RunRequestV1`、`RunHandleV1`、`RunStatusV1`、`ArtifactRefV1`を定義する。createはidempotency keyとparent/depth policyを持ち、status/stopはdurable state machineに従う。file accessは任意pathではなくallowlisted content-addressed artifact/resourceに限定する。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C16-01 | **完了**: runtime/manifest/docs inventory | 12 toolのcanonical manifestとsnapshot |
| C16-02 | **完了**: durable run registry | SQLite atomic state/event、PID start-time + receipt recovery |
| C16-03 | **完了**: idempotent async API | create/status/stop/result、exact ID、parent/child lineage |
| C16-04 | **完了**: artifact/resource API | allowlisted paper/EAR/logをdigestとroleで取得 |
| C16-05 | **完了**: auth/authorization | stdio principal、hashed bearer token/OAuth-ready verifier、owner scope |
| C16-06 | **完了**: recursion/budget policy | depth/run/node/cost/CPU/timeout quotaをatomic preflight |
| C16-07 | **完了**: transport adapter | stdio + authenticated MCP Streamable HTTPをshared serviceへ接続 |
| C16-08 | **完了**: federation visibility | verified `SKILLS.lock`のsanitized metadataだけを表示 |
| C16-09 | **完了**: test suite | lifecycle、restart、parallel、path、auth、cancel、recursion、HTTP |

## 5. 受け入れ基準

- [x]同一idempotency keyのretryでrunを二重起動しない。
- [x] process restart後もrunning/failed/succeeded stateをreceipt/PID identityから復元する。
- [x] stopがchild process groupへ伝播し、terminal stateを一度だけ確定する。
- [x] run外path、symlink、secret fileをartifact APIから読めない。
- [x] unauthorized principalが他runのstatus/artifactを取得できない。
- [x] recursion depth、run/node/cost/resource budget超過を起動前に拒否する。
- [x] stdioとMCP Streamable HTTP adapterで同じschema/state semanticsを返す。
- [x]新設した`ari-skill-orchestrator/tests` とMCP lifecycle suiteがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C16-D1 (deleted) |任意filenameを受ける`read_file` / directory listing path | scoped `ArtifactRefV1` | P2 |path/symlink/secret/size testsとmanifest/runtime negative checkを通過 |
| C16-D2 (deleted) |checkpoint scanだけでrun stateを推測する主要path | durable SQLite registry | P3 |restart fixtureを通過し、scanはexplicit fail-closed repairだけに隔離 |
| C16-D3 (deleted) |manifestのstale declaration | canonical 12-tool manifest | P1 |runtime/manifest/mcp.json/snapshot完全一致 |
| C16-D4 (deleted) |stdioと別実装のcustom HTTP business logic | shared `OrchestratorService` | P3 |実MCP clientのtransport parityを通過 |
| C16-D5 (deleted) |非標準HTTP transport | authenticated MCP Streamable HTTP | P6 |旧REST/SSE symbol/env/docs reference 0、unauthenticated start拒否 |
| C16-D6 (deleted) |workflow/Skillのsecret-bearing raw config返却 | verified lockのsanitized view | P2 |secret/schema/path negative testを通過 |

### 6.2 削除の検証と復旧

各 deletion PR はMCP lifecycle、restart、parallel、auth/path、cancel/recursion、transport parity、対象referenceへの `rg` を実行する。旧transport/state reader削除前commitをrollback基点にし、run registry migration/repair commandはsupport window中保持する。

### 6.3 計画書自身の削除

C16-01〜09、全受け入れ基準、C16-D1〜D6は完了し、恒久仕様を
[`docs/reference/orchestrator.md`](../../reference/orchestrator.md)へ移した。legacy repair
support windowを含む全体P6 cleanupで本書を削除する。

## 7. 実装記録

- checked-in schema: request/handle/status/result/artifact/principalの6契約。
- verification: package suite 44件（実process、実stdio/認証付きStreamable HTTPを含む）と
  core orchestrator/snapshot 19件がgreen。
- quality: orchestrator sourceのcomplexity/LOC regression、import boundary、prompt、
  manifest、schema、MCP snapshot findingは0。
- rollback基点: v1実装の最終commitは本変更直前の`5929694`。旧state readerをruntimeへ
  戻さず、必要なcheckpointは`--repair-registry`でterminal importする。
