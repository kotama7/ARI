---
sources:
  - path: ari-skill-memory/src/server.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/schemas.py
    role: schema
  - path: ari-skill-memory/REQUIREMENTS.md
    role: doc
  - path: ari-core/ari/mcp/client.py
    role: implementation
last_verified: 2026-08-02
---

# C08: `ari-skill-memory` 実装計画

> 状態: Proposed。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

BFTS lineageに沿ったancestor-scoped memory、typed research memory、artifact provenance、backup/restoreを所有する。memoryは証拠のsourceではなく、artifact-backed事実、reflection、failure、procedureを区別してconsumerへ渡す。

## 2. 現状と課題

- Letta production backendとtest-only in-memory backendを持つ。
- write CoWはprocess-global `ARI_CURRENT_NODE_ID` とprivate `_set_current_node` toolに依存し、core側がlockで直列化する。
- typed memoryはprovenanceを持つが、embedding/retrieval versionによりrankingはbit reproducibleでない。
- MCP tool listがmanifestの4 toolを大幅に上回り、driftがある。
- Letta local deployment modeとcompat/migration surfaceが広く、support期限を明確にする必要がある。

## 3. 目標契約

全read/writeは明示的`RunContext` / `NodeContext`を受け、ancestor setはlineage digestで検証する。`MemoryRecordV1`はkind、text、source node/run、artifact refs/digests、confidence、repro status、created-by tool refを持つ。retrieval結果はscoreに加えてbackend/model/versionとfilter evidenceを返す。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C08-01 | runtime tool / manifest inventory |全typed toolを含むcanonical manifest |
| C08-02 | explicit context API | env globalに依存しないCoW validation |
| C08-03 | lineage proof | ancestor digest、sibling isolation、run boundary |
| C08-04 | record schema versioning | typed memory migration、artifact integrity |
| C08-05 | retrieval provenance | embedding/backend/version、filter trace、bounded result |
| C08-06 | backup/restore portability | content digest、conflict policy、offline restore |
| C08-07 | concurrent access hardening | parallel writer、retry/idempotency、append-only event |
| C08-08 | deployment/support matrix | Letta Cloud/Docker/Apptainer/pipの明示status |

## 5. 受け入れ基準

- [ ] 4 parallel nodesが共有processでwriteしてもsibling contaminationがない。
- [ ] callerが偽node IDを渡したwriteをlineage/context checkで拒否する。
- [ ] claim用contextはartifact-backedかつrerun-failedでないrecordだけを区別する。
- [ ] retrievalの非決定性を隠さずbackend/model/versionを記録する。
- [ ] backupを新しいclean environmentへrestoreし、record digestが一致する。
- [ ] deleted/missing artifactをauditが検出し、memory textだけを証拠扱いしない。
- [ ] manifestとlive tool listが完全一致する。
- [ ] `PYTHONPATH=ari-skill-memory/src pytest ari-skill-memory/tests -q` がgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C08-D1 | private MCP tool `_set_current_node` | explicit `NodeContext` | P3 |parallel CoW suite、core caller 0 |
| C08-D2 | `ARI_CURRENT_NODE_ID` をauthorization sourceにするpath | signed/validated call context | P3 |env spoof negative test、全write migration |
| C08-D3 | manifestの4-tool限定stale declaration | canonical full manifest | P1 |live list完全一致 |
| C08-D4 | support済みcheckpointで不要になったlegacy memory migration runtime hook | offline migration command | P6 |support window、migration fixture、runtime caller 0 |
| C08-D5 | productionで選択可能なtest-only in-memory backend | test namespace only | P3 |production config rejection、unit testsは保持 |
| C08-D6 |期限切れlocal deployment fallback | supported deployment path | P6 |usage/issue確認、migration guide、clean deploy test |

deployment fallbackは利用状況を確認せず削除しない。削除しない場合はsupport ownerと再評価releaseを恒久文書へ記録する。

### 6.2 削除の検証と復旧

各 deletion PR はmemory全test、parallel CoW、env spoof、backup/restore、legacy migration、対象referenceへの `rg` を実行する。削除前backend/schema/commitをrollback基点にし、portable backupと旧record readerはsupport window中保持する。

### 6.3 計画書自身の削除

C08-01〜08、受け入れ基準、C08-D1〜D6を閉じ、memory schema、deployment、migrationを恒久文書へ移した後に削除する。
