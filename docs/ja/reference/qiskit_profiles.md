---
sources:
  - path: ari-skill-tool-registry/src/qiskit_contracts.py
    role: schema
  - path: ari-skill-tool-registry/src/qiskit_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_local.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_remote.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_results.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_verification.py
    role: implementation
  - path: ari-skill-tool-registry/providers/qiskit-support-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/qiskit/core-0.3.1+aer-0.17.2-local-ideal/verified-lock-v1.json
    role: config
last_verified: 2026-08-17
---

# Qiskit / IBM Quantum 実験 profile

ARI は Qiskit を個別 tool wrapper の集合としてではなく、federated tool
registry の immutable experiment として統合する。上流の MCP コレクションを
科学的権威とは見なさず（知名度や接続成功も科学的正当性ではない）、上流 tool
1 つにつき ARI wrapper を 1 つ登録することもしない。一つの reviewed source に
多数の profile を持たせても、
LLM に見せる surface は registry の5操作のままである。

## 信頼境界

現行の support record（`qiskit-support-v1.json`）は公式
[Qiskit MCP repository](https://github.com/Qiskit/mcp-servers)
のcommit、provider wheel/source archive、license、dependency lock、完全な installed package
tree、正確な MCP tool contractを固定する。これとは別に Qiskit 2.5.1、Qiskit Aer 0.17.2、
Qiskit IBM Runtime 0.48.0を固定する。実行前に、選択した interpreter、package tree、
distribution、entry point、architecture、policy environment を検証する。version range 指定、
改変された install、別 module、実行時 download、想定外の tool contract は admit しない。

これらの検査が確立するのはsoftware identityとprotocol conformanceであり、物理的正しさではない。
科学admissionには閉じた実験、宣言された limitations、統計範囲、実在する validation/replay 証拠、
domain reviewが別途必要である。関連する上流の一次資料は
[Qiskit MCP repository](https://github.com/Qiskit/mcp-servers)、
[IBM MCP server guide](https://quantum.cloud.ibm.com/docs/en/guides/qiskit-mcp-servers)、
[Qiskit QPY API](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qpy)、および support record が
pin する distribution の公式 PyPI release ページである。

正式にpromoteしたidentityは
`qiskit/core-0.3.1+aer-0.17.2-local-ideal`だけであり、verified lock digestは
`sha256:57b60bbdb84ba0364e038a6df51f3de2a48cdf8c776d31066efeec5ea68be195`
である。scopeはcredential不要のseeded Bell-state Aer実行を
`ari.quantum.sample.local-ideal/v1`の下で行うことだけであり、QPY、target、software、seed、count範囲、
live MCP schema、golden/replay、15個のProvider gate、人間承認をdigestで固定する。
IBM Runtime、remote simulator、IBM hardwareはcandidateのままである。admit済みcredential、
exact live backend/configuration/calibration identity、backend-bound golden/replay evidenceが
存在しないためであり、local promotionからremote authorityを継承することはできない。promotionは
Provider activationではなく、commit済みの既定`CATALOG.lock`は空のままである。各runは
review済みProvider LockとCapability Binding Lockを明示的にfreezeする。

公式 core MCP contract が行うのは circuit の解析／変換と transpile であり、simulation は
行わない。公式 Runtime MCP contract には account 管理操作が含まれる。ARI はどちらの
contract も直接には公開しない。内部で review 済みの最小限の leaf だけを使い、local な
Aer 実行は別の固定 worker で実装する。

## 能力の分離

| backend | capability | 必要な identity | 再現性の意味 |
|---|---|---|---|
| `local-ideal` | `ari.quantum.sample.local-ideal/v1` | Aer method、precision、thread、target、seed | noise modelを持たないseeded software simulation |
| `local-noisy` | `ari.quantum.sample.local-noisy/v1` | ideal の全項目 + 正確な noise model | 明示したnoise modelのseeded simulation（hardware の予測ではない） |
| `remote-simulator` | `ari.quantum.sample.remote-simulator/v1` | Runtime の backend/target/access tier と live snapshot | remote service上のstochasticな結果 |
| `ibm-hardware` | `ari.quantum.sample.ibm-hardware/v1` | hardware target、calibration snapshot、mitigation | live calibration された 1 backend のstochastic測定 |

brokerはinvoke/replay時にこれらの行を互いに代替しない。同じbackend kind/name、target、software
stackを共有するprofileは同じindependence groupであり、複数wrapperや反復runを
独立method agreementとして数えない。

## 閉じた実験契約

`QiskitExperimentV1` は次を固定する。

- canonical な QPY bytes、SHA-256、QPY format byte、生成元 Qiskit version、qubit/classical bit 数、
  および `rad` または `1` の unit を持つ全 parameter binding;
- preset pass manager、optimization level、transpiler seed、任意の initial layout;
- target の qubit 数、ソート済みで一意な basis gates、有向 coupling map、およびそれらの field
  だけから導出した digest;
- shots と期待 bitstring の確率区間（列挙されていない確率質量の上限を含む）;
- local profile では Aer version、method、precision、CPU/thread 上限、simulator seed、および
  noise なしか完全に宣言された noise model のいずれか;
- remote profile では Runtime client version、backend/version、opaque な instance digest、
  access-tier ID、calibration 要件、mitigation option;
- 正確な golden/replay 証拠 file、limitations、timeout、polling interval。

QPY header の検証により、別の Qiskit version が生成した file が古い profile identity を黙って
保持することを防ぐ。review 済み Runtime provider は sampler contract 経由で parameter binding
を渡せないため、binding を持つ remote profile は暗黙に再 bind されるのではなく validation で
失敗する。

callerが渡せる唯一の入力は、有界で安全な`request_id`だけである。これはidempotency keyであって
科学的入力ではない。circuit bytes、backend、shots、path、provider operation、environmentを
callerが上書きすることはできない。

## 実行と来歴

local 実行は次の閉じた手順に従う。

1. QPY、profile 証拠、provider bytes、正確な distribution を再検査する。
2. 宣言された basis/coupling と optimization level で公式 core MCP に transpile を依頼する。
3. 返された transpiled QPY を検証して保存する。
4. 最小 environment と正確な distribution version の assertion 付きで固定 local worker を起動する。
5. 宣言された method、precision、thread、shots、seed、noise で Aer を実行し、counts と統計上限を
   検証し、正規化済みと raw の artifact を publish する。

remote 実行は job ごとに隔離された Runtime MCP session を 1 つ開く。

1. scoped token を注入し、account 探索・account 削除の leaf を公開せずに review 済み channel を選ぶ。
2. opaque な instance identity を確認し、backend property、coupling、calibration を取得し、
   backend／target／simulator・hardware kind の不一致を拒否する。
3. 閉じた circuit を transpile し、宣言された sampler request を submit し、共通の非同期 handle を返す。
4. provider の status を submitted/running/completed/failed/cancelled へ写像する。timeout は cancel を
   要求する。submit と race した cancel は、provider job ID が判明した時点で完了させ、orphan job を
   残さない。
5. 最終 envelope を publish する前に backend、target、shots、result type/shape、bitstring、counts、
   宣言された統計上限を検証する。いずれかが不一致なら fail closed となる。

raw な property/calibration/submission/status/result の応答はすべて、役割で区別され digest を
prefix にした artifact 名を持つ。これにより、
異なる役割に使われた同一 bytes が artifact identity を混同させることを防ぐ。安定 backend snapshot
digest からは揮発的な capture time、queue 数、operational status を除くが、timestamp 付きの元の
応答は保存する。結果には circuit／transpiled circuit／target／software／method／backend snapshot／
calibration／job／result の identity と正規化 counts を記録する。

## credential

このadapterが受け付ける唯一のcredentialは`QISKIT_IBM_TOKEN`であり、Skill の
`quantum.ibm-runtime` credential scopeから宣言する。`sources.yaml`、profile、launcher の
`literal_env`、CLI 引数、lock、notebook、fixture、checkpointへ書いてはならない。

core providerとlocal workerには決して渡らない。Runtime subprocess だけが最小 environment
bridge 経由で受け取る。正確なsecret値は、provider境界を越える前に MCP text、structured content、
diagnostic、exception、stderrからredactする。sourceとlockのidentityはtoken値を記録せず、
IBM instanceはraw CRNを保存せず、operator-reviewedなdigestとaccess-tier IDだけをidentityにする。
record/replay fileも同じ不在検査を
通過しなければならない。

## 証拠、replay、解釈

`ari.qiskit-golden/v1`はprofile ID、experiment digest、検証済みcountsを束縛する。
`ari.qiskit-replay-fixture/v1`はさらにinvocation引数、method digest、shots、完了した
normalized resultを束縛する。両方のfileが存在し、宣言されたSHA-256と一致しなければならない。
digestだけを含むmetadataでは不十分である。

record modeでは加えて実在するraw artifactと、正確なcatalog/policy選択を記録する。replayは
同じ immutable tool identity を要求し、provider package、network、IBM credential、backend access
なしで記録済み結果を返す。replayが示すのは来歴を保った解析であって、live quantum backendが
同じstochastic countsを再現するという主張ではない。

Bell/GHZ fixture はseededなideal/noisyのlocal実行を行使する。統計上限はprofileの一部であり、
意図する主張に対して正当化されていなければならない。それらを通過しても、任意のcircuit、
新しいnoise model、別のbackend、後日のcalibration、より大きな研究結論を検証したことにはならない。

## 運用手順

`ari-skill-tool-registry/providers/qiskit-source.example.yaml`から開始し、隔離された正確な
環境を用いる。optional dependency group は利便のための pin であり、production の provider
環境は immutable な review 証拠として構築・保持すべきである。

```bash
cd ari-skill-tool-registry
python scripts/verify_qiskit.py \
  --core-python /absolute/qiskit-env/bin/python \
  --core-package-root /absolute/qiskit-env/lib/python3.13/site-packages/qiskit_mcp_server \
  --experiment /absolute/local-profile.yaml \
  --smoke --run-profile bell-local-ideal \
  --artifact-root /absolute/verification-artifacts
python src/sync_catalog.py
python src/sync_catalog.py --approve --approve-schema-changes
```

Runtime profileには`--runtime-python`と`--runtime-package-root`の両方を追加する。remoteの
smoke検査がquotaを消費したりworkをsubmitしたりするのは、`--run-profile`がremote profileを
名指しした場合だけであり、package/profileの検証だけでjobがsubmitされることはない。

pending catalog diffのcapability、backend lineage、independence group、permission、schema、
evidence、limitationsをreviewする。承認はactiveなrunの外で行うoperatorの操作である。promotionの
前に registry test、生成contract検査、manifest検査、credential redaction test、offline replayを
実行する。

## 更新・rollback・削除の gate

provider、Qiskit、Aer、Runtime、backend target、mitigation、circuitの更新は、新しいimmutableな
support/profile identityを作る。過去のsupport recordを別のbytesを意味するように書き換えては
ならない。隔離環境を再構築し、上流のdiffとlicenseをreviewし、tool／package-tree／contractの
digestを再生成し、科学fixtureを再実行し、結果のcatalog/schema diffを承認する。

rollbackは以前のsupport record、環境、profile、QPY/evidence、catalog lock、cassetteを選ぶ。
先にsubmit済みのremote handleをすべて解消すること。rollbackはlive provider jobに対する責任を
消せない。

Qiskit support lineの退役には、activeなcatalog参照が0であること、remote jobがterminalまたは
reconciledであること、置換/migration note、providerなしでのpublished cassette replayの成功、
support windowが必要とするreaderの保持がgateとなる。それらを満たして初めて、provider環境と
到達不能なadapter branchを削除できる。published evidenceが依存する限り、QPY、result、cassette、
migrationのreaderは残す。
