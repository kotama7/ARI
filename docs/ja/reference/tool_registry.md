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
  - path: ari-skill-tool-registry/providers/tooluniverse/1.3.1+ari.2/build-recipe-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/tooluniverse/1.3.1+ari.2/provider-manifest-v1.json
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
  - path: ari-skill-tool-registry/src/openroad_promotion.py
    role: implementation
  - path: ari-skill-tool-registry/providers/openroad-support-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/openroad/0.6.1+orfs-26q3-gcd-nangate45/verified-lock-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/openroad/0.6.1+orfs-26q3-gcd-nangate45-slurm-cpu/verified-lock-v1.json
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
last_verified: 2026-08-07
---

# 科学ツール連合レジストリ

`ari-skill-tool-registry` は多数のMCP collectionを `discover`、`describe`、
`invoke`、`get_status`、`get_result` の5操作の背後に統合するSkillです。これを
担うMCP toolは6つで、`invoke_scheduled` が同じdispatch操作の第2面だからです。
Providerのside-effect classはpermissionから導かれるため、共有の`invoke`に
`scheduler`を載せると背後の全leafのenvelopeが上がってしまいます。Skill
自体は既定で有効ですが、有効化してもleafは有効になりません。実行できるのは
選択したcatalogに載るsourceだけで、Skill flagとcatalogは独立した2つのgate
です。catalogはruntimeに `ARI_TOOL_REGISTRY_LOCK` と `ARI_TOOL_REGISTRY_INDEX`
で選択します。checked-inの `CATALOG.lock` が空なのは設計どおりで、これは
可搬なdefaultであり、中身の入ったcatalogは機械固有のevidenceだからです。
leaf schemaをすべてモデルへ渡さず、collection追加時にもleafごとの
ファイル編集を要求しません。

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

## ToolUniverse 1.3.1 / 1.3.1+ari.1 / 1.3.1+ari.2 adapter

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

さらに別identityの`1.3.1+ari.2`があります。`1.3.1+ari.1`の
`fitz>=0.0.1.dev2` -> `PyMuPDF==1.26.4` metadata修正はそのまま引き継ぎ、加えて
SMCPのresponse上限を引き上げます。`smcp.SMCP`のresponse `max_chars`を
100_000から2_000_000へ、serialization箇所2つとも変更します。ari.1と違い、
これはsource codeを変えるartifactです（`source_code_changes: true`）。upstreamは
compact MCP responseを一律100,000文字で打ち切り、structural trimmingで収まらない
ときはraw string truncationへfallbackして不正なJSONを出すため、collection全体の
列挙が成立しません。`get_tool_info(detail_level=full)`はbatch size 1でも最大級の
leafで上限を超えます。loadした2,601 leaf全体で実測すると単一responseの最大は
510,904文字、100,000を超えるのは2件だけです。2,000,000は観測された最悪のbatchを
約3倍の余裕で収めつつ、7,103,230文字のfull-collection dumpよりは十分小さい値です。

leaf identityはinstall場所に依存しません。upstreamは`source_file`をabsolute
install pathとして報告し、それがleaf metadataと`tool_spec_digest`の両方に入って
いたため、同じreview済みwheelでも機械ごとに別のleaf identityになり、promotionを
実行したhostのabsolute pathがpromotion evidenceへ書き込まれていました。adapterは
両方の手前でreview済みpackage rootからの相対pathへ正規化し、package外のpathは
開示せず`<outside-reviewed-package>`へ置き換えます。

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

`ari-patched-wheel`のToolUniverse sourceは`verified_lock_path`を省略できます。
そのsourceはcollection全体を対象としleaf promotionを持たないため、
`evidence.replay_fixture_digest`と`evidence.scientific_validation_digest`を
主張してはなりません。これらのlevelはverified lockに結合したleaf evidenceを
要求するからです。lockのないsourceは`callable`までで、`reproducible`にも
`scientifically_admitted`にも到達しません。retainedしたexact wheelはどの場合でも
必須です。

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
work rootが必須です。execution substrateは、review済みの
PRoot/SIF/unsquashfs/worker-Python portable runtimeか、toolchainと同じdigestの
clean/contained containerかの、ちょうど1つだけをpinします。どちらになるかは
siteの性質であり、契約が保証するのは「ちょうど1つである」という不変条件です。
どちらのsubstrateもexecution contractがadmitします。
`environment_requirements`は書き下すのではなくprofileから導出し、
`cpu` / `exclusive-node` / `slurm` に`proot-sif`または
`<runtime>-sif`を加えます。`runtime_target`の`worker_python` /
`execution_substrate` / `network`も宣言したsubstrateに追従し、typed jobの
`container_digest`はprofileがpinした値、すなわちcontainer runならimage digest、
PRoot runならcontainerなし、と完全一致しなければなりません。

scheduler handle/status/cancel、environment/module/container digest、logとprovenanceを
result/EARに保存し、terminal状態を確認した場合だけworkspaceを削除します。
transport結果が不明な場合はledger照合のためfail closedで保持します。terminal状態は、
schedulerにaccounting storageがあるsiteではscheduler自身（`scheduler_state`
COMPLETED、`exit_code` 0）から、無いsiteではnonce-boundのfixed-wrapper record
（reason `fixed-wrapper-completion-v1`）から取ります。どちらでもjobが実際に成功して
いることが条件です。scheduler handleの`workspace_scope` / `artifact_scope`は宣言した
work rootからの相対で記録し、work rootの外へ出るscopeは拒否します。公開に値するのは
digest由来のscope名だけで、prefixはpromotionを実行した機械を示すにすぎないためです。

物理cluster名、partition名、node名はruntime-privateです。256-bit nonceを持つ
Git-ignored site fileだけから読み、追跡対象のprofile、snapshot、fixture、evidence、
lock、file名、test、文書には一切書きません。公開identityはsalt済みfull SHA-256
`site_identity_digest`だけです。promotionの前後にGit candidate集合を検査し、site
fileが追跡可能になった場合、またはclear identityが漏れた場合はfail closedします。
`scripts/check_site_privacy.py`はworktree candidateに加えてstaged blob、file名、
symlink targetも独立に検査し、private site fileが存在するcheckoutではrepositoryの
pre-commit hookが必ずこれを実行します。

scheduler snapshotの検証は、liveのcontrollerをreview済みsnapshotが宣言した値
（slurm version、GRES type、partitionのMaxTime、nodeの
architecture / CPUTot / Sockets / ThreadsPerCore）と突き合わせ、repositoryに
入らないselectorであるcluster名とnode名はoperatorのprivate site configuration
と突き合わせます。さらにsite特性
ではないinvariant（`Arch=x86_64`、`Gres=(null)`、`OverSubscribe=EXCLUSIVE`）を
確認します。GPU authorityを主張するsnapshotは拒否します。site特性をliteralで
書かずsnapshotを唯一の宣言にしたので、同じpromotionを別のscheduler siteでも
実行でき、snapshotとlive controllerのdriftは従来どおりfail closedです。

正式にpromoteしたlocal OpenROAD identityは
`openroad/0.6.1+orfs-26q3-gcd-nangate45`です。verified lock digestは
`sha256:fbc4be322a03aa50e666a0dcdb3b1afdfe60fa52bbc570e9cd8f1c800168825e`
です。exact GCD placed database、Nangate45 PDK/library、x86_64 CPU、1 thread、
local-MCP、live schema parity、DRC 0 metrics、golden/replay、公式ORFS参照run、
15 registration gate、人間承認を固定します。固定binaryがSIGILLとなったため公式
参照runではCTS timing repairを無効化しており、full default-flow parityではなく
独立reference passとして記録します。1.54 GB SIF本体はGit外のretained artifactで、
OCI manifest、SIF、inner OpenROADのfull digestと配置pathをlockします。support
recordのretained SIFは`singularity` 4.5.0-1.el9でlocalに再materializeしたもので、
digestは`sha256:b8af5db8db5feb98720faf0959f6d3d478aac89f41cc9ad9d385467800c6580c`、
size 1540308992 bytesです。SIF headerはhash対象のfile内部にrandom UUIDと
wall-clockの作成時刻を持つため、`retained_sif_digest`はどのcontainer runtimeでも
再現できません。pinしたOCI manifest digestとinner OpenROAD binary digestは完全に
一致したので、封筒は再現できなくてもpayloadが同一であることは証明されています。

独立した`openroad/0.6.1+orfs-26q3-gcd-nangate45-slurm-cpu` identityも正式に
promote済みです。lock
`sha256:def08a69e7c0c13e8e76e026163337f39667ee8467792c16cad91d96ee9bd203`
は匿名exclusive-node CPU site digest、scheduler client、scheduler snapshot digest、
digest-pinnedのclean container（`singularity`、`network` none、`contain_all`、
`clean_environment`、GPUなし）、runtime-owned metrics lifecycle、scheduler由来の
terminal evidence、live DRC 0 result、fixture、gate、人間承認を固定します。
`environment_requirements`は`cpu` / `exclusive-node` / `singularity-sif` /
`slurm`、`runtime_target`は`execution_substrate` `singularity-sif`、
`worker_python` `container-provided`、`network` `isolated`です。review済みの
PRoot/unsquashfs/worker-Python buildが、promotionを実行するsiteの提供するhost
glibcより新しいglibcへlinkしているため、同じprofileをdigest-pinnedのclean
containerで実行しています。closureがSIFとportable runtimeが固定するhost binary
3本（PRoot、`unsquashfs`、worker Python）ではなくSIF単体になるので、隔離はむしろ
強くなります。
GPUに関するlimitationはreview済みscheduler snapshotから読みます。schedulerが
GRES typeを宣言しないならそもそもGPUを要求できず、宣言するなら根拠は割り当て
られたnodeがacceleratorを露出しないことです。どちらの場合もprofileのGPU要求は0
で、GPU capabilityは与えません。GPU実行、別design/PDK/corner/imageはいずれの
lockにも含まれません。対応する
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
`sha256:57b60bbdb84ba0364e038a6df51f3de2a48cdf8c776d31066efeec5ea68be195`
です。credential不要のseeded Bell-state local Aerと
`ari.quantum.sample.local-ideal/v1`だけを対象に、QPY bytes/version、target、software、
seed、count範囲、live MCP schema、golden/replay、15 Provider gate、人間承認を固定します。
IBM Runtime MCP、remote simulator、IBM hardwareはcandidateのままです。admit済み
credential、exact live backend/configuration/calibration identity、backend-bound
golden/replay evidenceがなく、local Aerのpromotionを継承できません。
対応するhuman-admin entry pointは`scripts/promote_qiskit_local_aer.py`であり、
Agent MCPへは公開しません。

Provider promotionはgoverned eligibilityの変更でありactivationではありません。
promote済みidentityはいずれもcommit済みの空の`CATALOG.lock`には追加せず、operatorが
exact環境をmaterializeし、source sync/review後にrun用Provider/Capability Binding
Lockを固定します。

### ARI Capabilityへの到達

このcatalogのleafはARI Providerではなく`SKILLS.lock`にも現れないので、Capability
Binderが直接authorizeすることはできません。両者を橋渡しするのが
`ari-core/config/providers/catalog.yaml`の`ari.provider.tool-registry` entryです。
その`brokered` blockが、このcatalog lock、既定のdispatch tool（`invoke`）、
scheduler投入leafを`invoke_scheduled`へ振り分けるleaf単位の
`dispatch_tool_by_leaf`、leaf `tool_ref`
からARI `capability_ref`へのreviewed tableを指定します。reviewed leafは1件ずつ、
呼び出しidentityがその経路が指すdispatch面、意味identityがleafであるcomposite
`CapabilityProvisionV1`になります。descriptor自身の`capability_ref`はこのregistryの
namespaceに属し、mappingとしては読みません。決めるのはchecked-inのreviewed tableだけです。

ARIはbrokerと同じ`ARI_TOOL_REGISTRY_LOCK`でlockを解決し、未設定ならpackagedのpathへ
fall backします。両者が同じ1つのlockに解決しなければ、ARIはbrokerがdispatchして
いないleafを記述することになります。materialize済みのlockは絶対local pathを記録する
ためrepositoryに置けません。commitするのはreviewed tableだけで、lockはcommitしないの
はこのためです。

authorityは2hopのenvelopeです。compositeのside-effect classはleafと`invoke`の宣言の
うち重い方になり、contractのrequired permissionは両者が付与していなければなりません。
`invoke`は`stateful`を宣言するので、この経路から`read-only`のcapabilityを供給する
ことは現状できません。ただし`ari.literature.search/v1`がこの制約で止まっているわけ
ではありません。`read-only`を宣言していたcontract側が誤りで（admitされたretrievalは
自らをevidenceにするrecordを書きます）、現在は`workspace-write`へ修正済みです。
reviewed PubMed leafはこのcontractに対してcompositeを構成します。

descriptorがasynchronous lifecycleを宣言するleafは、`invoke`で投入し`get_status`と
`get_result`で回収します。これらはentryの`lifecycle_tools`が名指しし、bindingに載って
運ばれるので、authorization viewは同じbinding・phase・call contextの下でそれらを
通します。別capabilityではありません。投入をauthorizeされたjobをpollしてもauthorityは
増えないからです。これが無いと、bind済みのasync capabilityは仕事を開始できても
回収できません。運ぶようにする前は実際にそうなっていました。

compositeが運ぶcredential scopeは、Providerが宣言したもののうち値が実際に存在する
ものだけです。宣言されていても値の無いcredentialはauthorityを与えません。子processは
存在する値だけから組み立てられ、call contextも同じfilterをかけるからです。宣言集合を
そのまま運んでいた頃は、multi-domain Providerのprovisionが使う可能性のある全scopeを
要求し、OpenROAD leafのbindがどこにも設定されていない`quantum.ibm-runtime`を要求して
いました。`QISKIT_IBM_TOKEN`が未設定のhost——出荷時の状態——では、brokerのIBM Quantum
scopeは存在する値を記録せず、compositeはscopeを1つも運ばないので、OpenROAD leafのbindに
credentialの付与は一切要りません。付与が必要になるのはtokenが設定されているとき、つまり
authorityが実在するときちょうどです。存在有無はlock時に観測してProvider Lockへ凍結する
ので、後から現れたtokenはlockを動かすだけで、検査をすり抜けません。これは直接Provider
経路と同じ規則であり、fail closedです。

call contextを運ぶbroker toolは`invoke`、`invoke_scheduled`、`get_status`、
`get_result`の4つで、いずれも
input schemaに`ari_context`を宣言します。4つとも`context_requirement: run`なので、
transportはauthorize済みのcall contextをこの名前で注入します。
`additionalProperties: false`のschemaがこれを省くと、authorizeされた呼び出しがすべて
拒否されます。

result normalizerの欠陥ではない粗い箇所が1つ残っています。ARIはbroker自身の
`ari.result-envelope/v1`をもう一枚のenvelopeで包むため、brokered asyncのsubmitは
handleを`structured_content.structured_content`に置き、外側の`async_handle`はnullの
ままになります。このfieldが運ぶのは`ari.async-tool-handle/v1`で、`get_async_status` /
`get_async_result` / `cancel_async`を駆動し、manifestで宣言されたARI async tool向けに
作られています。一方brokered leafのhandleはbroker自身のprotocolである
`ari.registry-handle/v1`です。相互変換は機械的には可能ですが（bindingはlifecycle
toolのrefを知り、brokerはstate mapを返します）、現状それを呼ぶ側はいません。
呼ばれないconverterを足すことは、この作業がずっと取り消してきた失敗の繰り返しに
なります。必要になるまで、brokered asyncのcallerはbind済みlifecycle toolを直接
pollします。

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
