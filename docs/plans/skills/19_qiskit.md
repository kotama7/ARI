---
sources:
  - path: docs/plans/skills/02_tool_registry.md
    role: doc
  - path: ari-core/ari/mcp/client.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: docs/reference/execution_profile.md
    role: doc
last_verified: 2026-08-02
---

# C19: Qiskit / IBM Quantum domain profile 実装計画

> 状態: Proposed / pilot integration component。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

Qiskit系MCP providerを、local simulator、noise simulation、remote simulator、remote hardwareという異なる能力として統合し、circuit、transpilation、backend、shots、noise、job、resultのprovenanceを固定する。credentialはprovider processに閉じ込めEARへ保存しない。

## 2. Domain contract

実行ごとに最低限次を記録する。

- Qiskit、provider、simulator package/version/digest
- canonical circuit serializationとdigest、parameter bindings
- transpiler optimization level、seed、pass manager/version
- basis gates、coupling map、target/backend snapshot identity
- shots、simulator method、precision、noise model、seed
- mitigation/post-processing configurationとcode digest
- remote job non-secret reference、queue/start/end time、backend calibration identity
- counts/quasi-distribution/statevector等のresult type、schema、raw artifact

local ideal simulationとnoisy/hardware resultは、同じ`capability_ref`へ無条件にまとめない。

## 3. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C19-01 | provider capability/conformance調査 | local/remote tool map、supported version、license |
| C19-02 | circuit/input normalizer | stable serialization、parameter/unit validation |
| C19-03 | capability profile分割 | ideal/noisy/remote simulator/hardware contracts |
| C19-04 | async job adapter | submit/status/result/cancel、rate/queue/error taxonomy |
| C19-05 | provenance collector | transpiler/backend/noise/calibration/shots/seeds |
| C19-06 | credential policy | scoped env/token、redaction、tenant/access-tier identity |
| C19-07 | scientific fixtures | Bell/GHZ、seeded simulator、noise、backend mismatch、tolerance |
| C19-08 | record/replay | circuit/job/result/raw metadata cassette、offline analysis |

## 4. 受け入れ基準

- [ ] ideal、noisy、hardwareをsemantic near-matchとして区別し、replay時に入れ替えない。
- [ ] circuit、transpiler、backend target、shots、seed/noise identityが欠けるrunをreproducibleとしない。
- [ ] remote submitが短時間でhandleを返し、queue/poll/cancelをtyped stateで扱う。
- [ ] provider token/API keyがlog、error、lock、cassette、EAR、digest inputに現れない。
- [ ] backend nameだけでなくsnapshot可能なconfiguration/calibration identityを記録する。
- [ ] same backend/wrapper由来の2 resultを独立method agreementと数えない。
- [ ] seeded local simulator fixtureが宣言tolerance内で再現する。
- [ ] remote providerなしでもrecord済みresultをoffline解析できる。

## 5. 削除要件

### 5.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C19-D1 | ideal/noisy/hardwareを一つのgeneric toolとして暗黙選択するpath |分離capability + explicit `tool_ref` | P5 |semantic routing tests、replay identity test |
| C19-D2 | implicit transpiler/simulator seed/default path | explicit versioned defaults | P5 |same-input fixture、missing field admission failure |
| C19-D3 | full parent env/credentialをproviderへ渡すpath | scoped credential policy | P5 |secret propagation/redaction tests |
| C19-D4 | ad-hoc remote polling loop | common async handle adapter | P5 |timeout/cancel/retry/state fixtures |
| C19-D5 | mutable backend nameだけをprovenanceにするrecord | backend target/snapshot identity | P5 |metadata completeness gate |
| C19-D6 | raw resultをinline JSONだけで保持するpath | content-addressed raw artifact + normalized result | P5 |large result/replay fixture |

### 5.2 削除の検証と復旧

各 deletion PR はideal/noisy/hardware routing、seeded simulator、credential redaction、async job、offline replay、対象referenceへの `rg` を実行する。削除前adapter/provider/backend fixtureをrollback基点にし、published circuit/result readerはsupport window中保持する。

### 5.3 計画書自身の削除

C19-01〜08、全受け入れ基準、C19-D1〜D6を閉じ、Qiskit support、credential、domain provenanceを恒久domain guideへ移した後に削除する。
