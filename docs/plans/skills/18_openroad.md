---
sources:
  - path: ari-skill-tool-registry/src/openroad_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_contracts.py
    role: schema
  - path: ari-skill-tool-registry/src/openroad_identity.py
    role: schema
  - path: ari-skill-tool-registry/src/openroad_verification.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_local.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_results.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_hpc.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_hpc_workspace.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_worker.py
    role: implementation
  - path: docs/plans/skills/02_tool_registry.md
    role: doc
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
  - path: docs/reference/execution_profile.md
    role: doc
last_verified: 2026-08-02
---

# C18: OpenROAD domain profile 実装計画

> 状態: Completed (2026-08-02) — C18-01〜08とD1〜D6を完了。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、P6の計画書一括cleanupで削除する。

## 1. 責務

OpenROAD系MCP providerを、stateful EDA session、restricted workspace、long-running task、domain artifact、scientific admissionのpilotとして統合する。OpenROAD/ORFS本体をforkせず、provider adapterとARI domain profileを実装する。

## 2. Domain contract

一つのrun/sessionについて最低限次を固定する。

- OpenROAD/ORFS commitまたはcontainer digest
- PDK、standard-cell library、technology filesのversion/digest/license scope
- RTL、constraints、LEF/DEF/SDC、flow configのartifact digest
- initialization policy、seed、thread count、host/architecture
- 実行command sequenceとsession state transition
- timing、power、area、DRC、congestion等のreport schemaとunit
- generated netlist/layout/report/logのartifact lineage

stateは暗黙global processに置かず、`SessionHandle`とworkspace digestに結び付ける。

## 3. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C18-01 | provider capability/conformance調査 | supported tool/session/task map、pin候補 |
| C18-02 | stateful adapter | create/invoke/status/result/close、session recovery policy |
| C18-03 | restricted command profile | allowed flow command、argument/path validation |
| C18-04 | `OpenRoadExperimentV1` manifest | design/PDK/tool/seed/resource/input identity |
| C18-05 | result normalizer | metric units、corner/mode、report/artifact refs |
| C18-06 | scientific admission fixtures | tiny public design、golden QoR/tolerance、negative cases |
| C18-07 | HPC/container execution | C06 handle、resource/cancel/log integration |
| C18-08 | record/replay | reports/artifacts/session transcript、tool無しoffline inspection |

### 実装進捗（2026-08-02）

- 公式 `The-OpenROAD-Project/OpenROAD-MCP` v0.6.1とORFS 26Q3/OpenROAD
  submodule commitをsupport matrixへ固定し、source/license/lock/package tree/
  十ツールMCP contractを実provider processで照合した。
- upstream interactive toolをleafとして公開せず、一つの
  `OpenRoadExperimentV1`を一つのvirtual async leafへ変換した。caller入力は
  idempotent `request_id`だけで、任意Tcl/shell/env/cwd/pathは受け付けない。
- closed verb/flat inert list、`-no_init`、private workspace、copy後digest検証、
  declared outputだけのcapture、missing/unexpected/symlink/size/digest failureを実装した。
- metricをvalue/unit/corner/mode/stage/report digest/JSON pointerへ正規化し、exact
  golden/replay fixtureファイルとrangeを検証する。digest文字列だけのevidenceは拒否する。
- provider sessionを一接続で保持し、sentinel completion、bounded concurrency/
  retained handles、success/failure/cancel transcript、全terminal pathのterminate、
  restart時fail-closedを実装した。
- brokerがadapter artifact参照のpath/size/SHA-256/result digestを再検証し、record
  cassetteからOpenROAD/PDK無しでoffline replayする。parallel workspace、cancel、
  same-backend overlap、negative artifact/rangeを50件のregistry suiteで検証した。
- `local-mcp` と `slurm` をexperiment/method identityに含むclosed execution
  policyを追加した。SLURM経路は固定commandをdigest-pinned Tclへcompileし、
  standard-library workerと全inputをC06 `JobRequestV1`へpinする。一node/task、
  threads/CPU一致、clean/contained SIF digest、shared work rootをfail closedで検証する。
- C06 handle/status/result/cancel/log/environment/module/container provenanceをOpenROAD
  result/EARへ取り込んだ。cancelはscheduler terminal確認後だけworkspaceを削除し、
  delivery不明なtransport failureはledger照合用workspaceを保持する。

## 4. 受け入れ基準

- [x] PDK/tool/design/configがunpinnedならreproducible以上にadmitしない。
- [x] session handleなしにstateful commandを実行できない。
- [x] workspace外path、arbitrary Tcl/shell escape、undeclared networkを拒否する。
- [x] QoR metricにunit、corner、mode、stage、source report pointerがある。
- [x] timeout/cancelでscheduler/container/sessionをcleanupする。
- [x] golden designのexpected report rangeとartifact digest policyを検証する。
- [x] disagreementするflow/version結果を同一methodの独立証拠として数えない。
- [x] record bundleをOpenROAD/PDKなしでinspection/replayできる。

## 5. 削除要件

### 5.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C18-D1 (deleted) | unrestricted command/Tcl execution prototype | restricted command profile | P5 |escape corpus、required flow coverage |
| C18-D2 (deleted) | process-global/shared session state | scoped `SessionHandle` | P5 |parallel design isolation、restart behavior test |
| C18-D3 (deleted) | mutable image tag、latest tool、implicit host PDK fallback | pinned experiment manifest | P5 |clean environment/golden design test |
| C18-D4 (deleted) | filesystem scanだけでoutputを発見するpath | declared artifact manifest | P5 |expected/missing/unexpected artifact tests |
| C18-D5 (deleted) | corner/mode/unitを欠くgeneric QoR result | domain result schema | P5 |normalizer fixtures、consumer migration |
| C18-D6 (deleted) | pilot専用hard-coded design/PDK paths | source/profile configuration | P6 |second design/PDK fixture、hard-coded reference 0 |

### 5.2 削除の検証と復旧

各 deletion PR はgolden design、command/path escape、parallel session、HPC cancel、artifact replay、対象referenceへの `rg` を実行する。削除前adapter/image/PDK/profile pinをrollback基点にし、published EDA manifest readerはsupport window中保持する。

### 5.3 計画書自身の削除

C18-01〜08、全受け入れ基準、C18-D1〜D6は閉じ、OpenROAD
support/admission/security/scheduler手順は `docs/reference/tool_registry.md` へ移管済み。
masterの追跡linkと他planの削除と合わせ、P6で本書を削除する。
