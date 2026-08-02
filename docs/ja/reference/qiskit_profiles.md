---
sources:
  - path: ari-skill-tool-registry/src/qiskit_contracts.py
    role: schema
  - path: ari-skill-tool-registry/src/qiskit_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_remote.py
    role: implementation
  - path: ari-skill-tool-registry/providers/qiskit-support-v1.json
    role: config
last_verified: 2026-08-02
---

# Qiskit / IBM Quantum 実験 profile

ARI は Qiskit を個別 tool wrapper の集合としてではなく、federated tool
registry の immutable experiment として統合する。上流 MCP の知名度や接続成功を
科学的正当性とは見なさない。一つの reviewed source に多数の profile を持たせても、
LLM に見せる surface は registry の5操作のままである。

## 信頼境界

`qiskit-support-v1.json` は公式 [Qiskit MCP repository](https://github.com/Qiskit/mcp-servers)
のcommit、provider wheel/source、license、dependency lock、完全な installed package
tree、tool contractを固定する。科学計算側も Qiskit 2.5.1、Qiskit Aer 0.17.2、
Qiskit IBM Runtime 0.48.0を固定する。実行前にinterpreter、entry point、architecture、
distribution version、package bytesを検証し、range指定、改変install、別entry point、
起動時downloadは拒否する。一次資料は
[IBM MCP guide](https://quantum.cloud.ibm.com/docs/en/guides/qiskit-mcp-servers) と
[QPY API](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qpy) も参照する。

これはsoftware identityとprotocol conformanceの証拠であり、物理的正しさの証明ではない。
科学admissionには閉じた実験、limitations、統計範囲、実在するgolden/replay fixture、
domain reviewが別途必要である。

## 能力の分離

| backend | capability | 意味 |
|---|---|---|
| `local-ideal` | `ari.quantum.sample.local-ideal` | noiseを持たないseeded Aer simulation |
| `local-noisy` | `ari.quantum.sample.local-noisy` | 明示したnoise modelのseeded simulation |
| `remote-simulator` | `ari.quantum.sample.remote-simulator` | remote service上のstochastic simulation |
| `ibm-hardware` | `ari.quantum.sample.ibm-hardware` | live calibrationを持つhardware measurement |

brokerはinvoke/replay時にこれらを代替しない。同じbackend kind/name、target、software
stackを共有するprofileは同じindependence groupであり、複数wrapperや反復runを
独立method agreementとして数えない。

## 閉じた実験契約

`QiskitExperimentV1` はQPY bytes/digest/format/producer version、qubit数、全parameter
bindingと`rad`または`1`のunit、transpiler level/seed/layout、basis/coupling/target digest、
shots、期待bitstringの確率範囲を固定する。local profileはAer method、precision、CPU
thread、simulator seed、noise modelを固定する。remote profileはbackend/version、opaque
instance digest、access tier、calibration要件、mitigationを固定する。

callerが渡せるのはidempotency用の`request_id`だけである。circuit、backend、shots、path、
provider operation、environmentは変更できない。review済みRuntime MCPはparameter bindingを
samplerへ渡せないため、remote bindingは暗黙変換せずvalidation errorにする。

localでは公式core MCPでtranspileした後、exact distributionを検証する隔離Aer workerで
実行する。remoteではtokenを隔離Runtime processへ渡し、instance、backend property、
coupling、calibration、backend kind/targetを検証してからsubmitする。submitは共通async
handleを即時返し、status/result/cancelをtyped stateへ正規化する。timeoutはcancelを要求し、
submitとcancelのraceでもprovider job ID確定後にreconcileしてorphanを残さない。

raw property/calibration/submission/status/resultはrole別content-addressed artifactとして残す。
stable snapshot digestからqueue、operational state、capture timeは除くが、元のtimestamp付き
responseは保存する。backend/target/shots/result shape/counts/statistical boundの不一致は
fail closedとなる。

## credential

唯一許可するcredentialは`QISKIT_IBM_TOKEN`であり、`quantum.ibm-runtime` named scopeから
供給する。`sources.yaml`、profile、launcher env、lock、fixture、checkpointへ書いてはならない。
core MCPとlocal workerには渡らず、隔離Runtime processだけが受け取る。provider text、
structured response、diagnostic、exception、stderrではsecret valueを境界内でredactする。
raw instance CRNも保存せず、operator-reviewed digestとaccess-tier IDだけをidentityにする。

## evidence、運用、rollback

golden fixtureはprofile/experiment digest/counts、replay fixtureはさらにrequest、method digest、
shots、normalized resultを束縛する。fileのbytesまで検証し、digest文字列だけではadmitしない。
replayはprovider、network、credential、backend accessなしで同じlocked identityから実行できる。
これはprovenanceを保ったoffline analysisの再現であり、live hardwareが同じcountを返す主張ではない。

`ari-skill-tool-registry/providers/qiskit-source.example.yaml`から開始し、次を実行する。

```bash
cd ari-skill-tool-registry
python scripts/verify_qiskit.py \
  --core-python /absolute/qiskit-env/bin/python \
  --core-package-root /absolute/qiskit-env/lib/python3.13/site-packages/qiskit_mcp_server \
  --experiment /absolute/profile.yaml --smoke
python src/sync_catalog.py
python src/sync_catalog.py --approve --approve-schema-changes
```

local validation runには`--run-profile`と`--artifact-root`、remoteにはruntime interpreter/
package rootを追加する。pending diffのcapability、schema、backend lineage、independence、
permission、evidence、limitationsをreviewし、credential redactionとoffline replayを含む全testを
通してから採用する。

provider/Qiskit/Aer/Runtime/backend/circuit更新は新しいimmutable record/profileとして追加する。
rollbackは以前のsupport record、環境、profile、QPY/evidence、catalog lock、cassetteを選ぶ。
remote handleは先にterminalまたはreconciledにし、rollbackでlive jobを隠してはならない。
削除はactive referenceが0、remote job解消、migration note、providerなしreplay成功をgateとし、
published evidenceが参照するQPY/result/cassette readerはsupport window中保持する。

