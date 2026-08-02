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

> 状態: Completed (2026-08-02) — C19-01〜08とD1〜D6を完了。マスター計画は [00_master_plan.md](00_master_plan.md)。恒久仕様は [qiskit_profiles.md](../../reference/qiskit_profiles.md) へ移行済み。本書はP6の計画書一括cleanupで削除する。

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

| ID | 作業 | 成果物 | 状態 |
|---|---|---|---|
| C19-01 | provider capability/conformance調査 | local/remote tool map、supported version、license | 完了 |
| C19-02 | circuit/input normalizer | stable serialization、parameter/unit validation | 完了 |
| C19-03 | capability profile分割 | ideal/noisy/remote simulator/hardware contracts | 完了 |
| C19-04 | async job adapter | submit/status/result/cancel、rate/queue/error taxonomy | 完了 |
| C19-05 | provenance collector | transpiler/backend/noise/calibration/shots/seeds | 完了 |
| C19-06 | credential policy | scoped env/token、redaction、tenant/access-tier identity | 完了 |
| C19-07 | scientific fixtures | Bell/GHZ、seeded simulator、noise、backend mismatch、tolerance | 完了 |
| C19-08 | record/replay | circuit/job/result/raw metadata cassette、offline analysis | 完了 |

## 4. 受け入れ基準

- [x] ideal、noisy、hardwareをsemantic near-matchとして区別し、replay時に入れ替えない。
- [x] circuit、transpiler、backend target、shots、seed/noise identityが欠けるrunをreproducibleとしない。
- [x] remote submitが短時間でhandleを返し、queue/poll/cancelをtyped stateで扱う。
- [x] provider token/API keyがlog、error、lock、cassette、EAR、digest inputに現れない。
- [x] backend nameだけでなくsnapshot可能なconfiguration/calibration identityを記録する。
- [x] same backend/wrapper由来の2 resultを独立method agreementと数えない。
- [x] seeded local simulator fixtureが宣言tolerance内で再現する。
- [x] remote providerなしでもrecord済みresultをoffline解析できる。

## 5. 削除要件

### 5.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate | 状態 |
|---|---|---|---|---|---|
| C19-D1 | ideal/noisy/hardwareを一つのgeneric toolとして暗黙選択するpath |分離capability + explicit `tool_ref` | P5 |semantic routing tests、replay identity test | 完了。generic pathを導入せず4 capabilityに固定 |
| C19-D2 | implicit transpiler/simulator seed/default path | explicit versioned defaults | P5 |same-input fixture、missing field admission failure | 完了。全profile fieldをclosed modelで必須化 |
| C19-D3 | full parent env/credentialをproviderへ渡すpath | scoped credential policy | P5 |secret propagation/redaction tests | 完了。Runtimeだけに`QISKIT_IBM_TOKEN`を転送 |
| C19-D4 | ad-hoc remote polling loop | common async handle adapter | P5 |timeout/cancel/retry/state fixtures | 完了。typed lifecycleとsubmit/cancel raceを実装 |
| C19-D5 | mutable backend nameだけをprovenanceにするrecord | backend target/snapshot identity | P5 |metadata completeness gate | 完了。target/config/calibration/raw snapshotを固定 |
| C19-D6 | raw resultをinline JSONだけで保持するpath | content-addressed raw artifact + normalized result | P5 |large result/replay fixture | 完了。role別artifactとoffline cassetteへ置換 |

### 5.2 削除の検証と復旧

ideal/noisy/hardware routing、seeded simulator、credential redaction、async job、offline replay、対象referenceへの `rg` を実行した。公式provider package/tree/distribution/tool contractを隔離環境で検証し、公式core MCPのtranspileとAer 2 Bell + 1 GHZ vectorも実行した。削除前adapter/provider/backend fixtureをrollback基点にし、published circuit/result readerはsupport window中保持する。

検証command:

```bash
PYTHONPATH=../ari-core:../ari-skill-hpc uv run --no-sync pytest -q
python scripts/verify_qiskit.py --core-python ... --core-package-root ... \
  --experiment ... --smoke --run-profile ... --artifact-root ...
python scripts/sync_contracts.py
python ../scripts/check_skill_manifests.py
```

### 5.3 計画書自身の削除

C19-01〜08、全受け入れ基準、C19-D1〜D6を閉じ、Qiskit support、credential、domain provenanceを恒久domain guideへ移した。単独削除はせず、マスター11.4に従いP6で全計画書を一括削除する。
