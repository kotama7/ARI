---
sources:
  - path: ari-skill-tool-registry/src/models.py
    role: implementation
  - path: ari-skill-tool-registry/src/providers.py
    role: implementation
  - path: ari-skill-tool-registry/src/sources.py
    role: implementation
  - path: ari-skill-tool-registry/src/admission.py
    role: implementation
  - path: ari-skill-tool-registry/src/catalog.py
    role: implementation
  - path: ari-skill-tool-registry/src/broker.py
    role: implementation
  - path: ari-skill-tool-registry/src/storage.py
    role: implementation
  - path: ari-skill-tool-registry/src/tooluniverse_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/providers/tooluniverse-support-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/tooluniverse/1.3.1+ari.1/provider-manifest-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/tooluniverse/1.3.1+ari.1/verified-lock-v1.json
    role: config
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
  - path: ari-skill-tool-registry/providers/openroad-support-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/openroad/0.6.1+orfs-26q3-gcd-nangate45/verified-lock-v1.json
    role: config
  - path: ari-skill-tool-registry/src/qiskit_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_contracts.py
    role: schema
  - path: ari-skill-tool-registry/src/qiskit_remote.py
    role: implementation
  - path: ari-skill-tool-registry/providers/qiskit-support-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/qiskit/core-0.3.1+aer-0.17.2-local-ideal/verified-lock-v1.json
    role: config
last_verified: 2026-08-05
---

# 科学ツール連合レジストリ

`ari-skill-tool-registry` は多数のMCP collectionを `discover`、`describe`、
`invoke`、`get_status`、`get_result` の5操作の背後に統合する、デフォルトOFF
のSkillです。leaf schemaをすべてモデルへ渡さず、collection追加時にもleaf
ごとのファイル編集を要求しません。

## 境界とライフサイクル

```text
少数のreview済み sources.yaml
  -> 隔離したprovider discovery
  -> canonical descriptorと可視なorigin chain
  -> graph・supply chain・conformance・科学admission
  -> review済み CATALOG.lock + 派生index
  -> immutableな5操作broker
```

runtimeは `sources.yaml` を読みません。sync差分はpending lock/indexとreview用
diffになり、`--approve` でだけactive lockを置換します。実行中brokerのsnapshot
は変化しません。

`tool_ref` はprovider、adapter、schema、明示default、permission/effect、
determinism、実行意味、method identity、async lifecycleから作るopaque digest
です。policyとsource aliasは別identityなので、policy再評価で実装変更を偽装
できません。

## 科学的admission

| Level | 必要な根拠 |
|---|---|
| `discovered` | candidateとleaf originが明示される |
| `callable` | MCP conformance、provider pin、launcher検証、permission許可 |
| `reproducible` | callableに加えdependency pinとoffline replay fixture |
| `scientifically_admitted` | validation、limitation、semantics、unit、method identity |

発見されたこと自体は権威や科学的正当性を意味しません。registryは根拠と
policy判定を報告し、upstream collectionを無条件には信頼しません。

## collectionの合成と競合

同一execution identityのaliasだけをcollapseし、全source/origin chainを保持
します。同様のcapabilityは既定で別toolです。exact duplicate、same backend、
semantic near-match、independent methodを区別し、名前が似ているだけで平均化
しません。結果の不一致も別々のprovenance付きで残します。

この境界により、ToolUniverse型collection、OpenROAD、量子simulator、将来の
MCP bundleをpackage固有routingなしで共存させられます。direct stdio MCPは
custom leaf code不要です。異なるtransportはcollection全体につき1個の
`CatalogSource` と `ProviderAdapter`、およびconformance fixtureを追加します。

## ToolUniverse 1.3.1 / 1.3.1+ari.1 adapter

ToolUniverseは数千個のpublic MCP toolではなく、一つのcompact collectionとして
統合します。registry processはToolUniverseをimportしません。operator syncだけが
compactなlist/info/execute surfaceをcanonical leaf descriptorへ展開し、runtimeは
active lockに含まれるexact leaf名だけを `execute_tool` へ渡します。

upstream `1.3.1` support recordは `candidate` のままです。`fitz` requirementが
意図したPyMuPDFではないdistributionへ解決され、その `pyxnat` / `pathlib==1.0.1`
依存が対応Python runtimeを壊すためです。このrecordは弱化しません。別identityの
`1.3.1+ari.1`は、source codeを変えず、package metadataの依存を
`PyMuPDF==1.26.4`へ置換してlocal versionを付けたartifactです。support recordは
upstream commit/wheel、patch、決定的build recipe、二回のbuildでbyte-identicalな
wheel、完全runtime lock、package tree、license、Provider manifestを固定します。
productionはoperator artifact storeのretained wheelをfull SHA-256で検査し、package
registryから解決しません。

checked-in `verified-lock-v1.json`がpromoteするのは
`tooluniverse-pubmed@1.3.1+ari.1`とexact leaf
`PubMed_search_articles -> ari.literature.search/v1`だけです。Provider manifest、
artifact、adapter/projection実装、CPython 3.13 linux-x86_64、live compact
`tools/list` schema、leaf/spec/input/output/normalized-output schema digest、
Capability contract、evidence bundle、15個すべてのregistration gate、および
人間maintainerによる明示的な`candidate -> verified`承認を固定します。承認digestは
lockとexact capability scopeに結合されます。`status`だけの書換え、承認の削除・
変更、scope拡張、evidenceの1 byte変更はいずれも拒否されます。
他のToolUniverse leafと未修正upstream releaseはpromoteしません。

leafごとのwrapperではなくcategory/type profileでeffect、determinism、permission、
limitation、lineageを割り当てます。upstream CLIが背景でより広い集合をloadしても
ARI側category filterを再適用し、runtimeではlock済みleaf名でも再制限します。
dynamic MCP loader、agentic/compose/code execution、credential必須、未reviewまたは
曖昧なprofile、不正schemaはquarantineします。v1.3.1固有のproperty-level
`required: true` だけは標準の親 `required` 配列へ決定的に正規化して履歴を残し、
その他のschemaを推測で修復しません。

Capability substitutionはexact semantic projectionであり、tool名やdescriptionの
類似判定ではありません。profileはadmitする各leaf、そのexact `capability_ref`、
semantic result contract、result normalizerを明示します。leafの消失または
category/type変更はsyncを失敗させ、locked schemaまたはProvider identityのdriftは
runtimeを失敗させます。PubMed projectionはexact `PubMed_search_articles`
responseを、recordごとのcontent/provenance digestを持つ
`ari.retrieval-result/v1`へ正規化します。このverified identityのcredential scopeは
空です。upstreamがoptional `NCBI_API_KEY`を宣言していても渡さず、匿名live probeを
promotion evidenceに含めます。API keyを使う構成は別Provider identityとして
credential scope reviewとpromotionをやり直します。

default admission policyはontologyのexact `network-read` permissionを許可しますが、
network write権限へ拡張しません。このverified identityからsyncしたsourceは
PubMed leaf一件だけが`callable`になり、commit済みdefault catalogは空のままです。
正式promotionはgoverned statusの変更であり、自動activationではありません。
有効化するrunごとにenvironment-specific catalogとBinding Lockを明示的に固定します。

argumentはlocked schemaでstrictに検証し、型coercionは無効です。明示 `null` は
upstreamが黙って削除するため拒否します。ToolUniverse cache/persistence、update
check、hook、searchを無効化し、resultへcollection/wheel/provider/leaf-spec identityと
`upstream_cache: disabled`を記録します。replay authorityはARI cassette/EARだけです。
collection-level trustをleafのreplay/scientific validationへ推移させません。

全stdio Providerはvalue-free supervisor経由で起動します。Provider本体を独立process
groupに置き、正常終了、timeout、cancelの全経路でgroup全体を回収します。実process
testはspawnされたdescendantが残らないことを検証します。promotionはadmin専用の
`scripts/promote_tooluniverse_pubmed.py`だけが行い、agent向けMCP surfaceにはpromotion
もlock rewriteもありません。実runはchecked-in dependency/verified lockと
installation固有の `provider_digest` の両方を固定します。

bulk updateはpending diffとなり、input/output/default schema変更は通常の
`--approve`だけでは承認できません。review後に
`--approve-schema-changes`も明示する必要があります。

## OpenROAD profile adapter

OpenROAD-MCPのinteractive toolはleafに公開せず、review済み
`OpenRoadExperimentV1` を1つのvirtual async leafにします。callerが渡すのは
`request_id`だけで、Tcl、path、PDK/library、OpenROAD/ORFS commit、seed、
threads、resource、containerはexperiment/method identityに固定されます。

`local-mcp` は検証済みtyped command列をprivateなruntime-owned Tclへcompileし、
MCPにはその固定fileだけを起動させ、read-only session stateだけをpollします。
OpenROADが正常終了して`-metrics`をflushした後にartifactを収集し、PTY echoや短い
output lullを完了判定に使いません。全terminal pathでsessionをcleanupします。
`slurm` はclosed commandをdigest-pinned Tclにcompileし、固定worker/inputとともに
C06 `JobRequestV1` へsubmitします。1 node/task、threads/CPU一致、shared
work root、toolchainと同じdigestのclean/contained SIF、またはreview済みの
PRoot/SIF/unsquashfs/worker-Python portable runtimeが必須です。
scheduler handle/status/cancel、environment/module/container digest、logとprovenanceを
result/EARに保存し、terminal状態を確認した場合だけworkspaceを削除します。
transport結果が不明な場合はledger照合のためfail closedで保持します。

物理cluster名、partition名、node名はruntime-privateです。256-bit nonceを持つ
Git-ignored site fileだけから読み、追跡対象のprofile、snapshot、fixture、evidence、
lock、file名、test、文書には一切書きません。公開identityはsalt済みfull SHA-256
`site_identity_digest`だけです。promotionの前後にGit candidate集合を検査し、site
fileが追跡可能になった場合、またはclear identityが漏れた場合はfail closedします。
`scripts/check_site_privacy.py`はworktree candidateに加えてstaged blob、file名、
symlink targetも独立に検査し、private site fileが存在するcheckoutではrepositoryの
pre-commit hookが必ずこれを実行します。

正式にpromoteしたlocal OpenROAD identityは
`openroad/0.6.1+orfs-26q3-gcd-nangate45`です。verified lock digestは
`sha256:ecd7cc79542acfcfa177186d3bbe154678f1a378454834b6276efb1383eeab28`
です。exact GCD placed database、Nangate45 PDK/library、x86_64 CPU、1 thread、
local-MCP、live schema parity、DRC 0 metrics、golden/replay、公式ORFS参照run、
15 registration gate、人間承認を固定します。固定binaryがSIGILLとなったため公式
参照runではCTS timing repairを無効化しており、full default-flow parityではなく
独立reference passとして記録します。1.54 GB SIF本体はGit外のretained artifactで、
OCI manifest、SIF、inner OpenROADのfull digestと配置pathをlockします。

独立した`openroad/0.6.1+orfs-26q3-gcd-nangate45-slurm-cpu` identityも正式に
promote済みです。lock
`sha256:d640dd226c101f9027e11f11c2201afd694b4914c11d7d45b458d142bc2971fd`
は匿名exclusive-node CPU site digest、scheduler client、PRoot/SIF/unsquashfs/
worker Python、runtime-owned metrics lifecycle、nonce-bound fixed-wrapper
completion、live DRC 0 result、fixture、gate、人間承認を固定します。GPU要求は0です。
GPU実行、別design/PDK/corner/imageはいずれのlockにも含まれません。対応する
human-admin entry pointは`scripts/promote_openroad_gcd_cpu.py`と
`scripts/promote_openroad_gcd_slurm_cpu.py`であり、Agent MCPへは公開しません。

## Qiskit profile adapter

公式Qiskit core MCPとIBM Runtime MCPはsupply-chain inputであり、public leafでは
ありません。review済み`QiskitExperimentV1`一つをvirtual async leafにします。
QPY/version、parameter unit、transpilation target/seed、shots、simulator/noiseまたは
Runtime backend、mitigation、evidence、limitationsを固定し、callerは`request_id`
だけを渡します。

local ideal、local noisy、remote simulator、IBM hardwareは別capabilityです。core MCPは
transpileだけに使い、local Aerはexact distributionを検証するworkerで実行します。
remoteではreview済みsetup、backend snapshot、sampler、status、result、cancelだけを
内部利用し、account管理leafを公開しません。backend/target mismatchはsubmit前に拒否し、
live snapshotとjob/result raw recordを検証済みartifactとして残します。

`QISKIT_IBM_TOKEN`はnamed credential scopeから隔離Runtime processだけに渡し、provider
境界でexact-value redactします。lock、cassette、artifact、identityにはtokenもraw
instance CRNも残しません。科学契約、運用、update/rollback、削除gateは
[Qiskit / IBM Quantum 実験 profile](qiskit_profiles.md)を参照してください。

正式にpromoteしたQiskit identityは
`qiskit/core-0.3.1+aer-0.17.2-local-ideal`だけです。verified lock digestは
`sha256:074755af42b998ca9e0369b156eb124bfa029e8a6c586cfe7dc4b239836c6684`
です。credential不要のseeded Bell-state local Aerと
`ari.quantum.sample.local-ideal/v1`だけを対象に、QPY bytes/version、target、software、
seed、count範囲、live MCP schema、golden/replay、15 Provider gate、人間承認を固定します。
IBM Runtime MCP、remote simulator、IBM hardwareはcandidateのままです。admit済み
credential、exact live backend/configuration/calibration identity、backend-bound
golden/replay evidenceがなく、local Aerのpromotionを継承できません。
対応するhuman-admin entry pointは`scripts/promote_qiskit_local_aer.py`であり、
Agent MCPへは公開しません。

Provider promotionはgoverned eligibilityの変更でありactivationではありません。
両identityともcommit済みの空の`CATALOG.lock`には追加せず、operatorがexact環境を
materializeし、source sync/review後にrun用Provider/Capability Binding Lockを固定します。

## record/replayとEAR

recordはexact arguments、catalog/policy digest、選択理由、却下候補、raw応答
digest/artifact、正規化ResultEnvelopeを保存します。replayは同じcatalogの下で
providerを起動せず再生します。証跡は `{checkpoint}/ear/catalog/` に置かれ、
既定EAR curatorで公開対象になります。

```bash
cd ari-skill-tool-registry
python src/sync_catalog.py
python src/sync_catalog.py --approve   # diffをreviewした後だけ
python src/sync_catalog.py --approve --approve-schema-changes
python scripts/verify_tooluniverse.py --help
python scripts/verify_openroad.py --help
python scripts/verify_qiskit.py --help
python scripts/promote_openroad_gcd_cpu.py --help
python scripts/promote_qiskit_local_aer.py --help
python scripts/sync_contracts.py
pytest -q
```

leafごとのproduction record、runtime refresh、leaf schemaの直接公開、bare name
dispatch、provider固有resultの素通し、static fixtureのproduction登録は禁止です。
