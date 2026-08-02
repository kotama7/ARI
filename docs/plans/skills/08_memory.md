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
  - path: ari-core/ari/call_context.py
    role: implementation
last_verified: 2026-08-02
---

# C08: `ari-skill-memory` 実装計画

> 状態: Completed (2026-08-02) — C08-01〜08、C08-D1〜D5を完了し、C08-D6を期限付き保持として閉じた。恒久仕様は [memory_contract.md](../../reference/memory_contract.md)。本書はP6の計画書一括cleanupで削除する。

## 1. 責務

BFTS lineageに沿ったancestor-scoped memory、typed research memory、artifact provenance、backup/restoreを所有する。memoryは証拠のsourceではなく、artifact-backed事実、reflection、failure、procedureを区別してconsumerへ渡す。

## 2. 現状と課題

- Letta production backendとtest-only in-memory backendを持つ。
- node-scoped MCP tool は tool-bound 署名付き `NodeContextV1` を I/O 前に検証し、
  writeはself、readは署名済みlineageのみを許可する。可変なprocess-global
  node stateとset-node toolは存在しない。
- typed memoryはcontent-addressed v1 recordとなり、embedding/retrieval versionを検索応答へ明示するためrankingの非決定性を隠さない。
- canonical manifest は13 tool全てとrun/node context requirementを列挙し、
  generated `mcp.json` と live list のdriftはconformance gateで検出する。
- Letta deployment modeは恒久support matrix、owner、pip再評価releaseを持つ。legacy migrationはoffline CLIだけに隔離した。

## 3. 目標契約

全read/writeは明示的`RunContext` / `NodeContext`を受け、ancestor setはlineage digestで検証する。`MemoryRecordV1`はkind、text、source node/run、artifact refs/digests、confidence、repro status、created-by tool refを持つ。retrieval結果はscoreに加えてbackend/model/versionとfilter evidenceを返す。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C08-01 | **完了**: runtime tool / manifest inventory |全typed toolを含むcanonical manifest |
| C08-02 | **完了**: explicit context API | env globalに依存しないCoW validation |
| C08-03 | **完了**: lineage proof | ancestor digest、sibling isolation、run boundary |
| C08-04 | **完了**: record schema versioning | `MemoryRecordV1`、offline typed migration、artifact integrity |
| C08-05 | **完了**: retrieval provenance | `MemoryRetrievalV1`、embedding/backend/version、filter trace、bounded result |
| C08-06 | **完了**: backup/restore portability | deterministic v1 backup、root/entry digest、record order、conflict policy、clean restore |
| C08-07 | **完了**: concurrent access hardening | file-locked parallel writer、digest idempotency、append-only event ledger |
| C08-08 | **完了**: deployment/support matrix | Letta Cloud/Docker/Apptainer/pip status、owner、v1.1再評価 |

## 5. 受け入れ基準

- [x] 4 parallel nodesが共有processでwriteしてもsibling contaminationがない。
- [x] callerが偽node IDを渡したwriteをlineage/context checkで拒否する。
- [x] claim用contextはartifact-backedかつrerun-failedでないrecordだけを区別する。
- [x] retrievalの非決定性を隠さずbackend/model/versionを記録する。
- [x] backupを新しいclean environmentへrestoreし、record digestとrepro event順序が一致する。
- [x] deleted/missing artifactをauditが検出し、memory textだけを証拠扱いしない。
- [x] manifestとlive tool listが完全一致する。
- [x] `PYTHONPATH=ari-core:ari-skill-memory/src pytest ari-skill-memory/tests -q` がgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C08-D1 | **完了**: private MCP tool `_set_current_node` | explicit `NodeContext` | P3 |parallel CoW suite、core caller 0 |
| C08-D2 | **完了**: `ARI_CURRENT_NODE_ID` をauthorization sourceにするpath | signed/validated call context | P3 |env spoof negative test、全write migration |
| C08-D3 | **完了**: manifestの4-tool限定stale declaration | canonical full manifest | P1 |live list完全一致 |
| C08-D4 | **完了**: legacy memory migration runtime hook |検証付きoffline `ari memory migrate` | P6 |runtime caller 0、migration/backup fixture green |
| C08-D5 | **完了**: productionで選択可能なtest-only in-memory backend | marker付きtest namespace only | P3 |workflow/config/startup rejection、unit tests保持 |
| C08-D6 | **期限付き保持**: pip local deployment fallback | supported containerless path | P6 |owner=ARI maintainers、static clean-launch test、v1.1でusage/issue再評価 |

deployment fallbackは利用状況を確認せず削除しない。削除しない場合はsupport ownerと再評価releaseを恒久文書へ記録する。

### 6.2 削除の検証と復旧

各 deletion PR はmemory全test、parallel CoW、env spoof、backup/restore、legacy migration、対象referenceへの `rg` を実行する。削除前backend/schema/commitをrollback基点にし、portable backupと旧record readerはsupport window中保持する。

### 6.3 計画書自身の削除

C08-01〜08、受け入れ基準、C08-D1〜D6を閉じ、memory schema、deployment、migrationを恒久文書へ移した後に削除する。

### 6.4 完了記録 (2026-08-02)

- normalized payloadをSHA-256 content address化する`MemoryRecordV1`、canonical
  JSON Schema、artifact/node-report digest、explicit metric unitを実装した。
- searchはbackend/client/server/model version、determinism、query digest、candidate
  count、bound、filter evidenceを含む`MemoryRetrievalV1`を常に返す。typed filterは
  mutable projectionではなく検証済みrecordを使う。
- `memory_backup.v1.json.gz`はroot/record/ReAct digestとlogical record orderを検証し、
  clean checkpointへのrestoreでもrecord digestとlatest reproducibility statusを保つ。
- 32並行同一writeを1 record/1 eventへ収束させ、backend purge後もevent ledgerが
  stale IDを返さないことを回帰testで固定した。
- public/backendのnode clear、runtime auto-migration、production in-memory selectionを
  削除した。旧JSONLはexplicit offline migrationでv1変換・backup成功後にarchiveする。
- Cloud/Docker/Apptainer/pipをLetta production pathとして文書化した。pipは
  containerless hostのため保持し、ARI maintainersがv1.1で再評価する。
