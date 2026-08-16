---
sources:
  - path: ari-core/ari/knowledge
    role: implementation
  - path: ari-core/ari/providers
    role: implementation
  - path: ari-core/ari/capability_binding
    role: implementation
  - path: ari-core/ari/assurance
    role: implementation
  - path: ari-core/ari/rqgm/admission_builder.py
    role: implementation
last_verified: 2026-08-17
---

# Knowledge、Capability、Scientific Assurance

ARIは手続き知識、実行権限、独立検証を分離する。三つは別registryと別identityを
持ち、package名、transport、vendor、repositoryが共通でも統合されない。

| 概念 | 意味 | canonical実装 |
|---|---|---|
| **Knowledge Skill** | 何を、なぜ、いつ、どの順序で行うかを示す非実行・content-addressed知識 | `ari.knowledge` |
| **Capability** | `ari.execution.compile/v1`等のversion付き意味実行契約 | `ari.capability_binding` ontology |
| **Capability Provider** | 一つ以上のCapabilityを提供する実行主体 | 既存`ari.mcp`とProvider lockを再利用する`ari.providers` |
| **MCP** | Providerのtransport / discovery protocol | `ari.mcp` |
| **Tool** | Providerの原子的operation | Provider lockで固定 |
| **Capability Binding** | 一run/epochに対するrequirementから`tool_ref`への決定論的解決 | `ari.capability_binding` |
| **Harness** | 宣言target/property/scopeの独立検証器 | `ari.assurance` |
| **RQGM** | 権限・証拠を誰が生成、利用、無視、歪曲したかの統治 | `ari.rqgm` bridge |

規範上の非同一関係は次である。

```text
Knowledge Skill != Capability Provider
Capability Provider != Harness
Harness != Evaluator
MCP != Skill
Tool description != procedural knowledge
Skill instruction != executable authority
```

## legacy Provider名称

従来のPython型名とdisk上の名称はKnowledge Skillではなく、実行可能なMCP Providerを
表している。

| legacy名称 | 正式な製品上の意味 |
|---|---|
| `SkillManifestV1` / `skill.yaml` | Capability Provider Manifest |
| `SkillConfig` | Capability Provider runtime configuration |
| `SkillConnection` | MCP Provider connection |
| `SKILLS.lock` | Providerとlive tool schemaのrun snapshot |

`CapabilityProviderManifest`、`CapabilityProviderConfig`、
`MCPProviderConnection`、`ProviderLock`は既存classとserialized bytesへのsemantic alias
である。v1のcanonical fileは`skill.yaml`と`SKILLS.lock`のままで、`provider.yaml`や
`PROVIDERS.lock`は作らない。`ari-skill-*` prefixも互換維持し、CLI、API、UIでは実行
権限を指す場合に「Capability Provider」と表示する。

## dependency境界

```text
ari.rqgm.knowledge_bridge -> ari.knowledge
ari.knowledge             -> ari.capability_binding contracts
ari.capability_binding    -> ari.providers / ari.mcp

ari.rqgm.assurance_bridge -> ari.assurance
```

`ari.knowledge`と`ari.assurance`は`ari.rqgm`をimportしない。`ari.assurance`はAgent
toolをbindせず、`ari.providers`はKnowledgeやHarnessを選択しない。共通契約は
`ari.protocols`、read-onlyのsupported APIは`ari.public`に置く。

## 全体invariant

三つのregistryを支配するinvariantの大半は、それが効く節の中で述べている。次の四つは
横断的であり、これを知らずに個別節だけを読むと誤った推論に至る。

1. **trust anchorは全てfull digestである。** manifest、body、snapshot、contract、lock、
   Attestationは`sha256:`と64桁の小文字hexで固定する。RQGMの短い`hash12`は、ここでは
   互換/表示用のkeyである。`hash12`はprompt、policy、registry、schema-v1 eventに対する
   RQGM自身のcontent identity方式として残るが、本書が述べるadmission、binding、
   Attestationのいずれも短縮値では決まらない。
2. **`active`はlock membershipであり、可変なcatalog statusではない。** Knowledge Skill、
   Provider、Harnessがrunでactiveなのは、固定lockがそれを名指しているからである。catalog
   の行はentryをreviewしpromoteする場所であって、有効化する場所ではない。したがって
   admission済みのrunの内側を、catalog編集で有効化することはできない。
3. **capability可視性はintersectionであり、unionではない。** 可視集合はProvider Lock、
   active Capability Binding Lock、role authority、phase policy、call contextの積から
   user-disabled toolを引いたものである。どれか一項に欠けるtoolは、他の何項が認めても
   可視にならない。
4. **compatibility defaultの`simple_bfts`はnull diffである。** `simple_bfts`を選び本書の
   全機能をdefaultのままにした場合、新しいimport、file、metric、field、snapshot、lock、
   prompt byte、visible toolは一つも生じない。

## run admissionと固定identity

有効な`ari_rqgm` runでは、最初のresearch node前にtrusted coordinatorが次を完了する。

```text
foundation bootstrap
  -> catalog snapshots
  -> ResearchContractV1
  -> Router selection proposal
  -> fixed Knowledge admission and EpochKnowledgeSkillLockV1
  -> capability requirement union
  -> fixed CapabilityBindingLockV1
  -> VerificationContractV1
  -> fixed Harness suite resolution and BaselineHarnessLockV1
  -> run admission commit
  -> first execution epoch freeze
  -> Agent execution through bound Providers
  -> target-bound HarnessAttestationV1
```

admission transactionは`rqgm/kca/admission-v1/`へ保存する。resumeは保存済みsnapshotと
lockを読み、現在のcatalogへ再解決しない。Skill、binding、Harnessの追加はappend-only
revisionとしてepoch境界でのみ採用する。node開始後はactive Knowledge body、binding、
target Attestationを差し替えられない。

instruction identityはbase/RQGM prompt hash、順序付きKnowledge body hash、composition
digest、Capability Binding Lock、Verification Contract、active Harness Lock digestを含む。
Provider tool descriptionはauthoritative instructionより下のuntrusted operation metadataで、
Knowledge本文やProvider descriptionからvisible toolを拡張できない。

## Knowledge package

packageは`SKILL.md`、`skill.meta.yaml`、任意の`references/`から成り、manifestは
`KnowledgeSkillManifestV1`である。実行field、command、environment/credential宣言、
entrypoint、transportはschema errorになる。importで見つかったscript/notebookは
non-executable attachmentであり、実行にはCapability Provider、Harness driver、または
trusted build-time importerとしての別登録が必要である。

外部sourceはrepository、full commit、subpath、manifest/body/referenceのfull SHA-256、
license、importer versionで固定する。branch、tag、`latest`をruntime sourceにしない。
本文中のtool名はnon-authoritative hintにすぎない。prompt-freeの固定Knowledge Binderが
verified status、applicability、dependency、conflict、authority ceiling、forbidden
capability、evaluation obligationを検査してepoch lockをmintする。

### 外部import adapter

`ari.knowledge.external_importer`はcandidate限定のadmin pathを4種類提供する。

- exact Git repository commitとsubtree
- 明示設定したscientific Skill sourceに対する同じGit adapter
- required YAML frontmatterと任意の`references/`、`scripts/`、`assets/`を扱う
  [Open Agent Skills specification](https://openagentskills.dev/docs/specification)
- 独立したARI側`ToolUniverseKnowledgeCollectionProfileV1`で記述するToolUniverse
  Knowledge collection

Git importは一時bare object databaseを初期化し、指定full commitだけをfetch・検証し、
`ls-tree`/`cat-file`でregular blobを読む。checkout、source hook、branch/tag参照、import
script実行は行わない。symlink、submodule、special entry、path escape、安全でない
remote-helper scheme、URL埋込みcredentialを拒否する。materialにはrepository、commit、
subtree、tree snapshot、元`SKILL.md`、生成body/manifest/reference、attachment、importer、
別admin profileの各digestを記録する。

Open Agent Skills frontmatterはsource metadataだけである。`allowed-tools`と
`compatibility`はnon-authoritative hint、`scripts/`、notebook、assetは
`authority: none`のdigest-bound attachmentとなる。Capability requirement、evaluation
obligation、authority ceiling、forbidden capabilityはuntrusted sourceの外にある
`KnowledgeSkillImportProfileV1`だけから得る。`body_normalization: strict`はARI必須section
を要求する。review済み`ari-wrapper-v1`は全upstream行をquoteし、必須precondition、
authority境界、failure semantics、expected artifact、scientific caution、evaluation
obligationを持つ固定ARI本文に包む。`curation_notes`も別hashのadmin profile由来である。
どちらも実行権限を付与せず、全importは`candidate`で入る。

`ari.knowledge-import-material/v1`はnormalized body、manifest、reference、attachmentと
source executable bit、tool hint、外部provenance、自身のfull SHA-256を保持するself-contained
materialである。checked-in catalogは第二のmanifest/bodyを作らず、このmaterialを参照
できる。catalog loadは全materialをoffline検証し、repositoryを再fetchしない。

```bash
ari knowledge import \
  --source-kind open-agent-skills \
  --repository https://github.com/example/scientific-skills.git \
  --commit 0123456789abcdef0123456789abcdef01234567 \
  --subpath skills/reproduction-method \
  --profile reviewed-import-profile.yaml \
  --output candidate-import-material.json
```

### 登録済みIntel performance candidate

catalogは`intel/intel-performance-skills`をfull commit
`e9d0b6410fb1ad7a50fb81e0868fd23ae886882c`でpinし、三つのKnowledge identityを別々の
candidateとして登録する。

| Knowledge ID | upstream subtree | 境界 |
|---|---|---|
| `intel.performance-patterns` | `skills/performance-patterns` | x86 C/C++最適化知識。bundled Cと実行可能test assetはauthority-none attachment |
| `intel.linux-perf` | `skills/linux-perf` | bound hardware-counter capabilityを要求するprofiling知識。`sudo`とhost sysctl変更は禁止 |
| `intel.phoronix-test-suite` | `skills/phoronix-test-suite` | 事前pin済みPTS input向けworkflow知識。runtime refresh/download/install、home、`/var/lib` writeは禁止 |

これらはProviderでもHarnessでもなく、`perf`、Phoronix、compiler、shell、credentialを
active化しない。実行はCapability Binding Lockだけから解決する。Phoronix scoreはHarness
Attestationではない。3件とも実測のclean-taskとportability evidenceを持ち、16 gateを
すべて通過し、記録されたapprovalに基づいて`verified`へ昇格済みであるため、固定
Knowledge Binderがadmitできる。HPC最適化Skillも同じ経路を通り、catalogの全entryが記録されたapprovalに基づいて
verifiedである。スレッド化したclean-taskは当初、自分の直列baselineを
下回った。型付きProviderがpayloadをbatch stepで実行しており、batch stepはノード全体を
affinity maskに継承するためである。Providerは現在、単一taskのpayloadを束縛されたjob step
として実行する。

### eligibilityはpromotionではない

gateを通過してもeligibleになるだけである。catalogの`status: verified`にはさらに
`ari.knowledge-skill-promotion-approval/v1`が必要で、正確な`skill_ref`（manifestとbodyの
バイト列）および審査したregistration evidenceに束縛される。catalog loadは、登録決定が
`eligible-for-verified`でないverified entry、approvalを欠くentry、別のバイト列を指す
approvalを拒否し、誰も昇格させていないentryに付いたapprovalも同様に拒否する。manifest、
body、evidenceを編集するとapprovalは無効化され、黙って引き継がれることはない。

promotionの書き手は`scripts/promote_knowledge_skill.py`ただ一つである。決定が
`eligible-for-verified`でないSkillを拒否し、承認者と根拠を明記し、approvalと
append-onlyな`ari.knowledge-skill-status-transition/v1`の両方を記録する。
`GovernedKnowledgeSkillRegistry.transition`も一致するapprovalの無い昇格を拒否
するため、台帳とcatalogが「誰が何を昇格させたか」で食い違うことはない。

portabilityは、現職Providerを取り下げて同一のcapability契約を予約済みのstand-in identity
で再提示することで判定する（`method: synthetic-substitution`）。これはSkillがcapabilityを
指しているのかProviderを指しているのかを問う。2つ目の実装を実行するより厳密に弱い証拠で
あり、cross-Provider portabilityとは決して呼ばない。従来の`method: two-providers`規則も
そのまま利用できる。

ToolUniverse collection profileはKnowledge subpathとadmin profileを持てるが、Provider ID、
launcher、tool、credential、transport fieldを持たない。identityは
`ari://knowledge-source/tooluniverse/...` namespaceを使い、`provider_activated: false`を
出力する。ToolUniverse MCP Providerとそのnested Provider lockから独立している。

## Capability ontologyとProvider binding

`CapabilityContractV1`はsemantic input/output、side effect、determinism、context、
permission、resource、version、compatibilityを固定する。Provider registrationはlive
input/output schemaと契約の整合を検査し、同じtext labelだけでは互換としない。

`compatibility_rules`はclosed vocabularyである。以前はdigestに束縛され、documentされ、そして
誰にも参照されないfree-form stringのtupleだった——つまりontology中の全rule名がinertだった。
reviewed table外の名前は現在拒否され、各名前は自分がどこで検査されるかを述べる。
`measurement-envelope-v1`はcoreで、5つはcapabilityを供給するProviderで——うち4つは自身の
goldenとreplay evidenceに対して、`exclusive-allocation-witness-v1`は投入したjobがallocationの
内側から——残りは明示的に`unenforced`である。

`json-schema-structural-conformance`は実装ではなく**廃止**された。残る3つの`unenforced`との
差が、それらを残す根拠でもある。3つはいずれもProviderを判定できる*payloadの形*——envelope、
artifact、async handle——を名指す。未実装なだけだ。廃止された1つは、どの契約も述べていない
「toolのschemaとcapability側structureの関係」を名指していた。13契約すべてが`semantic_inputs`と
`semantic_outputs`を空にしており、それらのfieldと`SemanticFieldV1`はrepository内に読み手が
一人もいなかった——引数の欠けた述語である。しかも13契約中13に載っており、すべてに真な性質は
何も区別しない。ruleとorphanなsemantic surfaceは共に消え、3契約は今や正当に
compatibility ruleゼロを宣言する。placeholderではなく、それが真である。

このruleに帰されがちなものは既に別の場所で強制されている。provision構築時のside-effect class
一致と`required_permissions` coverage、binderの`provider_lock_mismatch`によるlock全体の
identity、そしてtoolのlive `input_schema`/`output_schema`をそのまま畳み込むprovision digest——
schemaが変わればruleを誰が書いたかに関係なくprovisionが変わる。

これと並んで別の穴があり、capabilityを担うtoolについては既に塞がれている。以前はどの
Provider toolもMCPの`outputSchema`を**空**で公開しており、各provisionの
`output_schema_digest`は`{}`のdigestであって、誰に対してもdriftを検出しなかった。当時分類
されていた9つのtool——`ari-skill-coding`に5つ、`ari-skill-hpc`に4つ——は現在それを宣言して
おり、宣言された各schemaはtoolの成功形とそれ自身の失敗形の`anyOf`である。成功だけを記述
すると実際の実行失敗がoutput validation errorに化け、何が起きたかを述べるmessageを捨てて
しまう。`oneOf`では、timeoutした実行——完全な結果でありながらerrorも運ぶ——のように正当に
両方であるpayloadを拒否してしまう。schemaを宣言することは、handlerがtextと並べてstructured
contentを返す義務も伴う。libraryが`structuredContent`を宣言内容に照らして検証するから
である。schemaを宣言することとcapabilityへ分類されることは別の行為のままである:
`counter_support`は一切分類されないままschemaを宣言し、web Providerのretrieval tool 4つは
後から分類されschemaを宣言していないので、その`output_schema_digest`は今も`{}`のdigestで
ある。

`measurement-envelope-v1`は、測定はそれが取られた条件と一緒でなければ解釈できない、と述べる。
したがってこのruleを主張する契約は、その条件である`nondeterminism_fields`を宣言しなければ
ならない。ruleを主張しながら条件を一つも挙げない契約はload時に拒否される——それはenvelopeを
述べていないからである。

`declared_capability_refs_by_tool`だけがprovisionを作る。skill.yaml側の`capability_ref`は
`declared_capability_ref`として運ばれるが、bindはしない。だからこのtableに載らないtoolは、
どれだけ自分でcapabilityを名乗ってもCapability requirementの解決先にはならない——legacy/audit
modeで呼べなくなるわけではなく、bindの対象にならないという意味である（enforce modeでは、
bindされていないtoolは`unbound_tool`として拒否される）。

runのrequirementは二つのsourceから来る。admit済みKnowledge Skillは自分の指示が前提とする
ものを宣言し、`capability_binding.required_capability_refs`はrun自身のtaskが必要とするものを
operatorが宣言できるようにする。後者が存在するのは、前者しか無かったからである: どの
Knowledge Skillも偶々言及しないdomain instrumentは、契約もreview済みsupplierもadmit済み
evidenceも実証済みの呼び出し経路も持ちながら、一度も*要求されない*ため決してbindされ得な
かった。この宣言はconfigであってmodel出力ではない。review済みontologyに無いrefは無視では
なく拒否される。side-effect ceiling、resource、environmentを決めるのは宣言ではなく契約で
ある。同じcapabilityに対するKnowledge Skillのrequirementがこれで置き換わることはない。
required refを名指しながらbindingを`legacy` modeのままにすることは拒否される。さもなければ
requirementが黙って落ちるからである。`optional_capability_refs`は供給されればbindし、runを
失敗させることは決してない。

prompt-free Capability Binderは既存Provider lockにあるverified Providerのexact capability
refとcontract digestだけを候補にする。role、phase、call context、side-effect ceiling、
credential scope、environment、disabled tool、live schema identityでfilterし、exactness、
verified status、explicit pin、context fit、side effect最小、determinism、reproducibility、
feasibility、resource cost、lexicographic `tool_ref`と`subject_tool_ref`順で決定する。
coverage不足は`unsatisfied`で、substring、bare-name、LLM、network fallbackはない。

enforce modeでAgentが見る集合は次に等しい。

```text
Provider Lock tools
intersect Capability Binding Lock
intersect role authority
intersect phase policy
intersect call context
minus user-disabled tools
```

### brokered leafとcomposite provision

brokerを経由して届くdomain instrumentはARI Providerではなく、Provider Lockに現れない。
したがってBinderは直接authorizeできない。`ari.providers.brokered`がその半分を供給する。
Provider catalog entryは`brokered` blockを持てる。中身はfederated catalog lock、dispatch
tool、leaf `tool_ref`からARI `capability_ref`へのreviewed tableである。reviewed leafは1件
ずつ`CapabilityProvisionV1`になり、`tool_ref`と`dispatch_tool_ref`はbrokerのdispatch tool
——run lockに存在する唯一のref——、`subject_tool_ref`がleafになる。`subject_argument`は
そのleafを運ぶdispatch引数の名前であり、実際のdispatch callがこのrunでbindしていないleafを
引数で指した場合は拒否される。compositeは構造上すべて同じdispatch `tool_ref`を共有するため、
この照合が無ければreviewed leaf 1件のauthorizationがfederated catalogの全leafを運んでしまう。
可視性チェックは引数を渡さず、lifecycle refはleafではなくjob handleを運ぶので、どちらも
subject gateの対象外である。
`nested_source_lock_digests`はleafのsource digestを運び、federated lock自身の
`catalog_digest`はProviderの`nested_source_lock_digests`に加わる。broker背後でleafを
差し替えると、binding requestがpinするProvider catalog snapshotが動く。

siteは`ARI_TOOL_REGISTRY_LOCK`でfederated lockを選び、ARIも同じ変数を読む。これは
利便性ではない。ARIがpackaged lockをprojectしている間にbrokerがsite lockへdispatchすると、
すべてのcomposite provisionが「呼ばれていないleaf」を記述することになる。packagedの
`CATALOG.lock`が空なのは意図的で、materialize済みのものは絶対local pathを記録するため
commitできない。reviewed leaf→capability tableだけがrepositoryに残り、それが指すlockは
site側に留まる。

provisionは、値が実際に存在するcredential scopeだけを運ぶ。宣言されていても存在しない
credentialは何の権限も与えない——子processは存在する値だけから組み立てられ、call contextも
同じようにfilterする——ので、宣言された集合をそのまま運ぶと、multi-domain Providerの
すべてのprovisionが、使うかもしれないscopeを全部要求することになっていた。brokerを通して
EDA toolをbindするのに、どこにも設定されていないIBM Quantumのcredentialを与える必要が
あったのである。存在はlock時に観測されProvider Lockへ凍結されるので、後から現れたtokenは
lockを変えるのであって、すり抜けるのではない。

descriptorがasynchronous lifecycleを宣言するleafは、dispatch toolで投入し別のtoolで回収
する。それらは別capabilityではない——投入をauthorizeされたjobをpollしてもauthorityは増えない
——が、tool_refとしては別物なので、compositeは`lifecycle_tool_refs`として持ち、authorization
viewは同じbinding・phase・call contextの下でそれらを通す。これが無いと、bind済みのasync
capabilityは「結果を回収するauthorityが無い仕事」を開始してしまう。synchronousなleafには
lifecycle面を与えない。

前提ではなく検査される性質が4つある。

- federated lockは再認証される。ARIはbroker自身のcanonicalizationで`catalog_digest`を
  再計算し、tool毎に1件のadmission、id一意性、単一policy digestを再検査する。編集された
  lockはprojectionではなく拒否になる。
- authorityは2hopのenvelopeである。side-effect classはleafとdispatch toolの宣言のうち
  重い方、contractのrequired permissionは両者が付与していなければならない。runtimeが
  gateするのはbroker、実際に作業するのはleafだからである。
- mappingはbrokerのものではない。descriptor自身の`capability_ref`はbrokerのnamespaceで
  あり、drift検出用に`declared_capability_ref`として記録するだけで、mappingとしては
  読まない。決めるのはcheck-in済みreviewed tableだけである。
- reproducibilityはadmissionで上限が付く。`callable`止まりのleafはdeterminism fieldが
  何を主張しても`unknown`、`reproducible`は最良で`bounded`、`scientifically_admitted`は
  最良で`exact`。自身の`required_level`未満のleaf、quarantined leaf、run lockに無い
  dispatch toolはいずれも拒否である。選択されたsite lockに含まれないreviewed leafは
  拒否ではなくskipされる。選択されたlockはreviewed tableより意図的に狭くてよく、
  存在しないleafは何の権限も与えず、それを供給できないrequired capabilityはbinderで
  `unsatisfied`として可視のまま残る。

### environment evidenceとProvider substitution

`ari.capability_binding.environment`はbinding前にsubstrateの観測事実を記録する。SLURM
partition、local NVIDIA device、CUDA compilerをbounded・shell-free probeで調べる。
`resources.gpus > 0`、SLURM ready、local deviceなしの場合だけ、`srun`で一回のbounded
compute-node `nvidia-smi` queryを行う。config宣言からresourceを捏造できない。

container runtimeも実行して判定する。`shutil.which`がbinaryを見つけることは重要な事実では
ない——installされていてもuser namespace不足で起動を拒む runtime はある——し、Singularityの
2つのforkはsiteごとに別名でinstallされる。よって`--version`を実行し、応答した名前をそのまま
記録する。executableのpathは意図的に保持しない。site依存であり、bindingはそれを必要としない。

観測された事実をontologyのresource classへ変換するのは別の行為であり、
`ari-core/config/capabilities/resource_derivations.yaml`がその場所である。各rowは何をemitするか、
何が既に存在していなければならないか、そして理由を述べる。rationaleの無いrowはload時に拒否
される——理由の無いderivationはaliasであり、aliasこそこのtableが防ぐために存在するものだから
である。rowはfixpointまで適用されるので、あるrowが別のrowのemitを消費できる。proberが観測
しなかった事実をここで発明することはできず、発火したrowは`metadata.derived_from_review`に
記録される——derivedなresource classに依存したbindingは、それを許した一文まで監査できる。
同梱tableはApptainerとSingularityCEが共にSIFを実行すること、podman/dockerは実行しないことを
記録し、そこからCPU + SIF runtimeで`eda-cpu`を導く。

外向きの到達性は、何かに接続するのではなくroute tableから観測する。default routeは、この
hostの外へ出る経路があるとkernelが述べている、ということである。それは必要条件であって
十分条件ではない——proxyやfirewallが呼び出しを拒みうる——のは、`sinfo`が応答することが
schedulerについて与えるのと同じ立場である。default宛先の行が数えられるのは、upであり、
reject routeでなく、loopback上でもない場合だけである: kernelはどのhostでも到達不能な
`::/0`を持つので、宛先だけを照合するとair-gapped nodeでもそれを経路として読んでしまった。
より強い証拠——名前を解決する、接続を開く——は、自分のsubstrateを記述するためだけに他人の
serviceへ外向きrequestを出すことになる。air-gapped nodeにはrouteが無く、retrieval
capabilityは供給されないままになる。

SLURM GPU visibilityとscheduler authorityは別である。GPU GRESがadvertiseされないnodeで
deviceを観測した場合、`metadata.slurm_gpu`と`gpu-observed-on-slurm-node`は残すが`gpu`
resource typeを追加しない。schedulableになるのはGRES観測時か、operatorが`resources`で
exclusive-node inventoryをpinした場合だけである — `gpu_allocation_mode:
exclusive-node-inventory`、`exclusive: true`、`gpu_node`、そして観測inventoryと一致すべき
full-SHAの`gpu_inventory_digest`。一致しないpinは`exclusive-node-inventory-mismatch`として
記録され、schedulableにはならない。device UUID/model/
compute capability/memory/driverとoutput digestを含む全観測はfrozen environment identityへ
入る。resumeはreprobeで置換しない。persist済み`EnvironmentSnapshotV1`はcanonical full-SHA
identityを再計算し、resourceや観測値の改竄を無効にする。

ToolUniverse authorityもexactである。review済みcategory profileはexact leaf名をcanonical
`capability_ref`、equivalence key、result normalizerへ対応付ける。substringやdescriptionは
使わない。最初のprojectionは`PubMed_search_articles`を`ari.literature.search/v1`へmapし、
live responseをrecord単位のsource identityとfull payload digestを持つ
`ari.retrieval-result/v1`へ変換する。production syncはreview済みwheel/package tree、exact
upstream dependency lock bytes、closed dependency environment、live compact-MCP schema parityを
要求する。

`probe_provider_substitution`はprimary Providerのexact locked toolをdisableし、production
Binderを二回実行する。digest-bound reportはbinding determinism/statusと任意のlive operation
observationを分離する。そのため二Providerのsemantic resultが同じでも、一方がcandidate、
drifted、inadmissibleならsubstitutionはbinding `unsatisfied`のままである。

## Verification、Harness、Attestation

Harness kindは閉じており相互代替しない。

- `benchmark`: 固定benchmark subjectを評価し、任意external targetを検証しない
- `artifact_verifier`: 生成program/libraryを宣言target kind/propertyについて検証する
- `reproduction`: paper/repository reproduction packageを評価する
- `claim_verifier`: claim/evidence整合を検査するが記録計算の正しさを証明しない

`VerificationContractV1`はmint-once、canonical JSON、full-SHA boundである。Knowledge由来
obligationはproperty/methodを追加するだけで、requirement削除、`certify -> validate -> screen`
弱化、tolerance緩和、authoritative Harness指定はできない。固定Resolverがexact compatibility
filterとdeterministic set coverを実行する。baseline lockはimmutableで、revisionはepoch境界で
Harness追加またはproperty強化だけを行う。

Fixed Verifierはimmutable target snapshotを受け、lock済みdriver、oracle、dataset、container
だけを実行する。run/node/epoch、contract、Knowledge use、Provider/Binding/Harness lock、source
asset、target digest、execution identity、property verdict、evidence artifactにboundされた
full-SHA `HarnessAttestationV1`を出す。verdictは`pass`、`fail`、`inconclusive`、
`infrastructure_error`、`tampered`である。Provider successはAttestationではなく、通常の
candidate failureだけではconstitutional violationにならない。

どのverifier processを起動するかは、manifestがpinしたdriver revisionが決める。Harness idでは
決めない。登録済みrevisionは`ari.assurance.native-hpc/v1`、
`ari.assurance.problem-correctness/v1`、`ari.assurance.native-perf/v1`の三つで、それぞれが
自分のargvを組み立てる。problemを軸にする二つの分岐は、問いとcandidateをmanifest自身の
`oracle`/`dataset` pinとtarget宣言から取り、idから切り出した文字列からは取らない。native-HPCの
分岐だけは今もidからfamily名を読み出す(`hpc/gemm-correctness`→`gemm`)。そこだけは、その切り出し
が登録済みfamilyを与えるからである。どの分岐も名指さないrevisionは
launch不能として拒否される。これは「検証に失敗した」とは別の所見である。この拒否がなければ
requestは誤ったverifierを起動し、不一致は一層下でinfrastructure outageとして現れる。evidence
referenceのmedia typeも同じ理由で宣言されたtarget kindから決まり、C submissionがshared library
として記録されることはない。

correctness requirementは、そのrunのcandidateが実際に何であるかというartifact kindを持つ。
property vocabularyはproperty毎にtarget kindを一つだけ述べ、Resolverはmanifestの
`target_kinds`に無いkindのatomをproperty検査より前に落とす。別kindを検証するHarnessは、
登録されpromotionされても選ばれない。runが`ARI_PROBLEM`でpinned problemを名指すと、admissionは
そのproblemのartifact kindを導出してVerification Contractへ渡し、correctness propertyだけが
それを受け取る。problemの宣言entry pointがfamily ABIのexported symbolの一つであればそのABIの
target kind、そうでなければ`benchmark-submission`である。problemを名指さないrun、または
load不能なproblemを名指すrunは何も渡さず、requirementの刻印は従来のままである。node側の
target宣言も同じ関数からkindを導くので、resolutionとdeclarationが「何を検証したか」で
食い違うことはない。

native `hpc/gemm-correctness`、`hpc/spmm-correctness`、`hpc/stencil-correctness`は
deterministic generated case、独立reference、dtype/accumulation-aware error model、
metamorphic/shape/boundary/repeat coverage、negative controlを持つ。checked-in verified catalog
へのpromotionはrelease admissionであり、commit済みsource revision、immutable container、
license review、reference pass、negative-control fail、registration reportが必要である。
registrationはmanifestをpin先のdriverにも突き合わせる。`result_schema_conformance`は、
`expected_result_schema`がそのdriverの出すreport typeであり、
`expected_result_schema_digest`がARIがそのtypeについて配布するschema fileのbyte digestである
場合にのみ通る。両方を持たないevidenceは比較を省略せずgate失敗となり、schemaが下でdriftした
pinは黙って直さず拒否する。pinはregistrationされた内容の記録であり、動かせるのは
re-registrationだけだからである。

この三つはそれぞれcorrectness familyであり、`ari.assurance.native_hpc_family`で一度だけ
自己登録し、三つを供給する。`verify`(hidden caseとそれを判定するoracle)、`reference`
(独立実装であり、parity probeのclean controlでもある)、`call_shared_library`(candidateを
呼ぶctypes ABI)である。検証可能kernelのsetは以前は五箇所——`Literal`、facadeのdispatch
dict、parity probeのreference table、ABI dispatch dict、二つのargparse `choices` tuple——に
書かれていた。そのため四箇所にしか追加されなかったfamilyはdispatchされscoreされattestされる
一方でprobeは一度も触れず、それでもprobeは`passed`と報告した。現在は全dispatch siteが
registryへ問い合わせ、同名の再registerは拒否される。どのoracleがrunを判定したかをimport順序が
決めることはない。registryはnative driver digestの内側にある。どのoracleがrunを判定するかを
決めるからで、外側にあればattestationが検証を通したままjudging oracleを差し替えられる。
digestはverifier fileが一つ欠けたとき、黙って対象から外さずraiseするようになった。以上は
correctness familyをpinned problemのように自由にはしない。problemはdataのdirectoryだが、
familyはoracleを持つ。family追加は今も他と同様にreviewされるARI変更である。callerが供給
できるoracleはcallerが弱められるoracleだからである。変わったのは、setがsetごとに五箇所では
なくfamilyごとに一箇所で宣言される点だけである。

costは実在し、吸収ではなく支払われた。driver digestが変わったため、三つとも
`native Harness driver bytes drifted`で実行を拒否していた。manifestを単に再pinはしなかった。
signatureは署名した対象だけを覆うので、再pinだけでは三つのhuman-maintainer attestationが
誰も承認していないcodeを記述することになるからである。代わりにre-registrationした——
clean worktreeで各三回のparity probe run、15/15 gate、`eligible-for-verified`、
registration report・evidence bundle・maintainer approvalはいずれも新規である。
pinは現に存在するdriverを指している。

checked-in catalogはもうこの三つだけではない。pinned problemに対するcorrectness Harness——
family ABIではなくproblem自身のC contractに対してcandidateを検証し、manifestがpinするものと
異なるproblem、case set、digestを記述するresultの正規化を拒否し、harness levelのverdictを、
reportが合成する両propertyではなくrequestが実際に宣言したpropertyについて取る——と、
performance Harnessも持つ。

performance verdictは、その測定が実際に示したspreadに対して読む。candidateが到達すべき比は
`DEFAULT_REGRESSION_THRESHOLD`一箇所であり、worker、parity probe、measurementが等しくそこから
取る。governed pathはthresholdを渡さないので、verdictを読み取る数値がcall site毎のdefaultで
あってはならない。不足とは、そのthresholdからmedian比を引いた差であり、そのrunが実際に
持つbandに対して読む。bandとは、repetitionのmax−min、またはspreadが測れないとき(単一
repetitionが典型)は median×`MAX_TRUSTED_SPREAD`(この計器が読まれる最大値)である。bandを超える不足は
`fail`であり、この判定が先に置かれる。だからthresholdを十分に下回るcandidateは、単一
repetitionからでも、何も解像できないほどnoisyなmachine上でも拒否される——slowなnegative
controlが落ち続けるのはそのためである。それに達しない範囲では、`MAX_TRUSTED_SPREAD`より
広い測定spreadは、medianがthresholdのどちら側にあっても`inconclusive`である——noiseが広げるの
は「解像しなかった」であって「pass」ではない——単一repetitionから残る不足も同じく
`inconclusive`である。clean controlのtimed durationはspreadの
隣に記録される。spreadはdurationに対する割合であり、計器自身のoverheadを支えるには短すぎる
caseは、noisyなmachineとは別の所見だからである。

取られなかった測定はzeroではなくabsentとして報告する。launchが完了しなかったcase、または
oracleが有限でないresidualを答えたcaseはresidual ratioを持たず、reportのaggregateは全caseが
値を出したときだけ存在する。答えたcaseだけの最大値はevidenceが支持しないboundであり、しかも
読者が比較するlimitの隣に載る。correctness reportはcandidate自身のdigestもbindする。これが
無いと、同じverdictに達した別のcandidateがbyte-identicalなreport、したがって一つの
report digestを生む。reportがlaunchのsandboxから保持するのはallowlistであり——untrusted
candidateが隔離されたか、何によってか、それが覆わないものは何か——per-runのwritable rootは
含めない。host filesystem pathであり、report digestを毎run変えてしまうからである。

Inspect、Harbor、KernelBench/ComputeEval/scBench、PaperBench adapterはupstream frameworkを
forkしない。pinned official routeを検証してstrict result envelopeへ正規化する。digest-bound
official runner parity reportなしではregistrationは`not_available`、entryは`candidate`で、
縮小local fallbackを使わない。

`ExternalHarnessParityReportV1`がauthoritative parity inputである。`passed` reportはHarness
Manifest、source revision、dataset、container、driverをbindし、official invocation/result、
normalized result digestを保持し、reference pass、wrong-submission negative-control fail、
result-schema parityを証明する。API import、CLI presence、scorer unit compatibilityは
`non_authoritative_checks`にしか置けない。`passed` schemaは短いsource revisionとall-zero
digest placeholderも拒否する。`ari-skill-paper-re/scripts/verify_paperbench_upstream.py`は
credential-free upstream APIとdeterministic aggregationを診断するが、official rollout、
reproduction、judge routeと全external pinが揃うまで
`official_runner_status: not_available`を出す。

### verification resource accounting

valid Attestationの構築・再検証後、RQGM Assurance bridgeはverifier executionを
`cost_trace.jsonl`へ一件記録する。Harness、execution identity/attempt、Attestation、node、
epoch、tier、status、backend、executor wall interval、declared CPU/accelerator/memory allocationを
bindする。derived resource値はallocation×observed wall intervalで、utilization sampleではない。
Task 20は`screen`、`validate`、`certify`ごとの総量とvalid node当りの値を分離する。dollar値は
authoritative charge/priceがある場合だけ記録し、それ以外は`cost_status: unpriced`として
unknown costを無料と表示しない。

## modeと互換性

```yaml
knowledge:
  mode: off       # off | audit | enforce
capability_binding:
  mode: legacy    # legacy | audit | enforce
assurance:
  mode: off       # off | audit | enforce
```

defaultは`simple_bfts`を保持する。三つがdefaultならrun pathは新domain packageをimportせず、
catalog snapshot、lock、checkpoint field、metric、prompt byte、visible-tool差分を生成しない。
明示Knowledge/capability/verification requirementとoff/legacy modeの競合はrun admission errorに
なる。`ari_rqgm` enforceは対応する全immutable snapshotとlockを要求する。

## surfaceと管理

人間向けdiagnostic commandは`ari knowledge`、`ari provider`、`ari harness`にある。
dashboard Governance workspaceは三つのcatalog cardとlock/provenanceを分離表示する。
`ari-skill-knowledge`と`ari-skill-harness`はdefault-offのquery/request Capability Providerで、
MCP requestはnon-authoritativeである。register、promote、revoke、lock rewrite、oracle交換、
tolerance変更、force passはできない。

catalog lifecycle変更にはreview済みrepository changeまたはauthenticated human admin pathが
必要である。revocationはtaint/status historyをappendし、過去lock、Attestation、provenanceを
書き換えない。

## 記録済み検証checkpoint

以下は日付付きの観測記録であって、現在のstatusではない。environment、cost、promotionに
関する後の主張は、実際に生成されたartifactに照らして検査できねばならず、digestはその
artifactの唯一のidentityである。だから残す。ここに載るdigestは記載日時点の記録を指すの
であって、現在のcatalogについての言明ではない。

### 観測された外部cell(2026-08-04)

固定environment snapshot
`sha256:e0fdcf428bf8b2168dfc06e14faad4ceb2197b7269b90e843b699aa818d92cbb`
は、利用可能なCPU SLURM、CUDA toolkit 12.4、匿名compute nodeで見えた四つのV100 deviceを
記録する。schedulerがGPU GRESを広告していなかったため、これらのdeviceはobservation-only
であり、`gpu` resource typeは付かず、accelerator campaignは明示的なoperatorのscheduling
決定なしには`not_available`のままだった。これは「environment evidenceとProvider
substitution」が述べる規則——deviceの可視性はschedulerの権限ではない——を、議論ではなく
実測で示したものである。

一件のbatch jobがnative verifierのreference/negative-control三families を走らせ、3件が
passし6件の非選択testが完了した。GNU timeはwall 1.61秒、user CPU 0.89秒、system CPU
0.13秒、最大RSS 55,537,664 bytesを観測した。このcost観測はdigest
`sha256:3c451a31416880fd32a71c6e3fefa4d1aba9663f6052f27e84d2aec54fa0839d`
にbindされている。

この観測は意図的にauthoritativeなcost traceで**ない**。理由は測定の品質ではない。観測
時点で、production Harness catalogにverified pinned containerは無く、runはAttestationを
発行しなかった。production cost accountingが始まるのはvalid Attestationを構築し再検証し
た後であり、「verification resource accounting」の記録はtiming runではなくAttestationから
書かれる。dollar値はscheduler charge/cloud chargeが与えられるまで`unpriced`のままである。

ToolUniverse/Webのlive operation substitutionは正規化済みresult contractの水準では成功
したが、正確な凍結upstream environmentがpromote不能だったため、ToolUniverse bindingは
`unsatisfied`のままだった。PaperBench compatibilityはpassし、official-runner parityは
`not_available`のままだった。これらは実測された欠落cellであり、passでもなく、未解決の
design選択でもない。

### ToolUniverse promotionの解決(2026-08-05)

2026-08-04の結果はupstream ToolUniverse `1.3.1`に対する不変の観測として残り、書き換えも
label張り替えもされていない。ARIは代わりに、別identityのmetadata-only Provider artifact
`tooluniverse-pubmed@1.3.1+ari.1`をmintした。そのcheck-in済みregistration evidence、
Provider gate十五件全て、明示的なhuman-maintainer承認から、verified lock
`sha256:c85e73726b1182c3fe88b682a8bcd0e0d7a57713f7ecb1818056886eaa5442bf`
とpromotion approval
`sha256:9317c4ff7e15f488f758fc253b9afd96345abd6d3730405f5669c93a6eabc608`
が生じた。このlockが認めるのは匿名`PubMed_search_articles`を
`ari.literature.search/v1`とすることだけで、credential scopeは無い。scope拡大、evidence
改変、schema drift、revoked statusはfail closeする。

promotionは以前のdiagnosticをpassに変えたわけではない。新しいcampaignは、verified
artifactから導いたrun固有の`CATALOG.lock`、`SKILLS.lock`、environment identity、
Capability Binding Lockを使わねばならない。run固有の一leaf `CATALOG.lock`が生成されて
`callable`に達し、その匿名broker invocationは空のcredential scope listを持つ正規化済み
`ari.retrieval-result/v1` recordを一件返した。正式なmaintainer promotionの後、閉じた
environmentで再同期した結果、verifiedな一leaf catalog digest
`sha256:73e1225dc30b4cfc735858bad4615e08da6723a0f0ced6dd560897d7db3551ff`
が得られた。

三つのdigestはいずれもこのcheckpointに属し、その後少なくとも一度supersedeされている。
2026-08-07のportability再promotionが、promoteした側hostのinstall pathをleaf identityから
取り除き、lock、approval、catalog digestが変わった——認められたscopeは不変である。現在
有効なlockとapprovalは
`ari-skill-tool-registry/providers/tooluniverse/1.3.1+ari.1/`
配下のcheck-in済みbundleにあり、一leaf catalogはrepository defaultではなくenvironment固有
のevidenceである。supersedeされたdigestも、それが記録した対象のidentityとしては有効な
ままであり、resume中に既存のcatalogやlockが書き換えられることはない。

## 正直な限界

Knowledge品質とcapability ontologyには人間のcurationが必要である。同じcapabilityのProvider
も挙動が異なり得る。external service、model、hardware identityの完全性はsubstrateが公開する
範囲に限られる。static inspectionだけで全Provider descriptionの無害性は証明できない。
Harness passは宣言property/scope内に限り、formal-verifier Harnessだけがformal specificationを
証明する。nondeterminismと不足external pinはprovenanceへ残す。infrastructure errorは
fail-openしない。RQGMはVerifierの科学的結論を発明せず、固定結果を無視、抑圧、歪曲した
actorを統治する。

composite provision経路はend-to-endで**呼び出しまで到達した**。実materialize済みのOpenROAD
leaf(`scientifically_admitted`なdescriptor)をenforce modeでbindし、brokerの`invoke`へdispatch、
bind済みlifecycle toolでpollして完了させ、promotion goldenが定める範囲内のCTS+routing metricを
得た——DRC error 0、wire length 3603 um、via 3361、pin済みSIF内で約50秒。

そこに至るまでに3つの修正が要り、いずれも「不便」ではなく「経路が使用不能」だった。broker側の
tool schemaが`ari_context`を宣言せずに`additionalProperties: false`だったため、transportが注入
するcall contextが拒否され、context-gatedなbroker toolは一つも呼べなかった。result normalizerが
`error`キーの**存在**を失敗と見なしていたため、`ari.result-envelope/v1`——ARI自身が定義する
schema——を返すProviderは成功が全て`null`というmessageのtool errorとして報告されていた。そして
bind済みasync capabilityは自分のlifecycle toolに対するauthorityを持たず、仕事を開始できても
回収できなかった。

`ari.literature.search/v1`を塞いでいたのはenvelope則ではなく、自分自身の契約だった。
`read-only`を宣言していたが、reviewed PubMed leafもbrokerの`invoke`も`stateful`である以上、
誰も供給できなかった。誤っていたのは契約の方である——admitted retrievalは、それをevidenceに
する記録を書く(cassetteとcontent-addressed payloadがrunのEARへ入る)のであり、ladderが等級を
つけるのは「このsubstrateに何をしたか」であって「remote indexを変更したか」ではない。現在は
`workspace-write`であり、reviewed PubMed leafがそれに対してcompositeを構成する。このmapping
のregisterにはleafを含むsite lockが要る。reviewed tableはsiteの全sourceにまたがってleafを
名指すので、EDAとretrievalの両方が欲しいsiteはdomainごとにlockを分けず、両者を1つのlockへ
materializeする。

`ari.quantum.sample.local-ideal/v1`は供給済みである。promote済みlocal-Aer bundleは
materializeされていたがregisterされていなかったので、bundle自身のmaterialized profileから
site sourceを組んだ——捏造は無い、誤った値はcatalog buildで落ちる——そしてleafはbindして走る。
seed済みBell回路4096 shotが`{"00": 2046, "11": 2050}`のみを返し、promotion goldenの範囲内、
約10秒。1つのlockが両sourceを保持したまま、bridgeが第二のdomainと第二のadapter種別で動いた
ということである。

その`environment_requirements: [cpu]`も同種のcategory errorで、訂正済みである。
`quantum-simulator`は`cpu`のみからのderivation rowを持つ。このrowは、capabilityを供給する
ものが無い間は意図的に伏せてあった——あらゆるsubstrateで発火し、未供給のcapabilityを解決済みに
見せるrowは、rowが無いより悪い——今は単に正確である。seed済み2-qubit CPU statevector passに
必要なのはCPUだけだ。境界を与えるのはcatalogが検証するdigest-pinned artifactであり、それは
どのderivationにも見えない。substrateの主張はavailabilityの主張ではない。

CUDA契約の`slurm` requirementも同じcategory errorで、今は`slurm-controller`と読む。
`gpu-slurm`はproberが別々にemitする2つの半分からのderivationを得た。実GPU nodeでproberを
走らせたことで、さらに2つが閉じ、login nodeでは見えないdefectが1つ見つかった。

`cuda-12.9`と`nvidia-sm70`は同じ誤りのもう一段先であり、契約から取り除いた。toolkitの
releaseとdeviceのgenerationは、そのProviderがpromoteされた**機械**についての事実であって、
capabilityの意味についての事実ではない。それを要求することは、その機械でない全substrateで
capabilityをbind不能にする一方、何も余分に証明しない——正確なversionとdevice毎のcompute
capabilityはProviderの`runtime_target`に既に記録されている。契約は今`cuda-toolkit`、
`nvidia-gpu`、`slurm-controller`を要求し、3つともproberが観測からemitする。これは議論では
なく実測である。実GPU nodeでproberは汎用featureと並べて`cuda-13.2`と`nvidia-sm121`を報告し、
self-testは実際に見つけたarchitecture向けにcompileされ、negative control検出・絶対誤差0で
passした。同じrunで、deviceはCUDA API経由で130 GBを報告する一方
`nvidia-smi --query-gpu=memory.total`は`[N/A]`を返した。

self-test自身のarchitecture引数は`sm_70`という単一値に固定されていた。制約すること自体は
正しい——`nvcc`のcommand lineに届くからだ——が、単一値への固定はsafety propertyではなく、
「実行できないvalidation」である。現在は**形**で検査するので、`sm_70; rm -rf /`は依然
拒否される一方、実在のarchitectureは拒否されない。promotionが持っていたrequirement listの
複製も、locally構築されていたcontract digestと同じ経路で消えた。どちらも今は契約から来る。
手書きのlistは、retirementが効いている間ずっと`exclusive-node`と`slurm`を名乗り続け、
両者を比較するものが一つも無かったからである。

toolkit versionとdevice generationはどちらも観測しては捨てられていたので、いずれかを名指す
契約は決して満たされ得なかった。proberは観測したcompiler releaseから`cuda-<major>.<minor>`を、
各deviceが報告するcompute capabilityから`nvidia-sm<major><minor>`をemitする——derivationでは
なくobservationである。12.0のnodeが12.9を名乗ることはなく、Blackwell deviceが`nvidia-sm70`を
名乗ることもない。sm70 buildが新しいarchitectureで走るかはbuildのされ方に依存し、それを推測
するのはproberの仕事ではない。

`exclusive-node`はその契約からemitされるのではなく、消えた。そもそもenvironment featureでは
ないからである。それはProviderがinvokeされたときに作るallocationについての主張であり、bind
時点でallocationは存在しない——jobが投入されるのは数分後で、proberが試せるものは同じ命題では
ない。`JobRequestV1`は既に、pin済みnodelistとGRESなしのexclusive single nodeを*要求*しない
限りそのjobを組み立てることを拒否している。欠けていたのはschedulerがそれを*許可した*という
証明の側だった。それは答えられる場所で行われるようになった——`exclusive-allocation-witness-v1`が
投入されたjobの内側からallocationを検査し、device probeより前にexit 88で拒否し、いずれの結果
でもwitnessをjob provenanceとして保持する。

witnessは`SLURM_JOB_CPUS_PER_NODE`をnodeの`CPUTot`と比較する。この選択は仮定ではなく実測に
基づく。`SLURM_CPUS_ON_NODE`は*step*のcpu数であり——真にexclusiveなnodeでjobが20を保持している
間に4と観測された——これを土台にしたwitnessは、まさに確認すべきallocationで落ちることになる。
`OverSubscribe`は記録するが何も読まない。あるsharing partitionでは`--exclusive`なjobと共有job
の双方が`YES`を報告し、このfieldだけでは何も判別しない。両方のcontrolを実clusterで走らせた。
sharing partitionでの`--exclusive`は8のうち8 allocatedで`held`、同じpartitionで付けない場合は
8のうち4のうち2 allocatedで`refused`。

見つかったdefect: Grace-Blackwellではmemoryがunifiedのため`memory.total`が`[N/A]`を返し、
device parserはmemoryがparseできないrowを丸ごと捨てていた。よってARIはGPUを持つnodeで
**GPUを1つも見ていなかった**——そこでは全GPU capabilityが黙ってbind不能になる。memoryの値が
parseできないdeviceも、deviceである。

### 何がpromote済みで、promotionが何をしないか

upstream entryは、それに対する真正なevidenceが揃うまで`candidate`のままである。この
`candidate`は形式ではなくrepositoryについての事実である。remote Provider transportと、
Inspect、Harbor、PaperBench、KernelBench、ComputeEval、scBenchのHarness entryは全て
candidateのままで、いずれをpromoteするにも真正なupstream full commit、dataset/container/
license pin、official-runner parity、negative control、許可されたGPU schedulingまたは
model credentialが要る。この六つはいずれもcheck-in済みHarness catalogに現れず、当該
catalogはnative HPC entryのみを持つ。check-in済みの外部driver facadeはfail closeし、可変
source、捏造pin、省略されたparity結果、常時passのplaceholderがその代替として認められる
ことはない。PaperBenchのupstream APIとaggregation parityはpassするが、公式の
rollout、reproduction、judgeのparityは依然として利用できない。

正確なupstream ToolUniverse `1.3.1` lockは失敗したcandidateのままである。promote済みなの
は別identityのmetadata-only artifact `1.3.1+ari.1`だけであり、その範囲も匿名
`PubMed_search_articles`を`ari.literature.search/v1`とすることに限られる。他のToolUniverse
leafは全て未admitである。

さらに二つのProvider scopeが、独立でevidenceにbindされたverified lockを持つ。認められた
境界はupstream製品の機能一覧ではなく、そのlockである。

- **Qiskit MCP 0.3.1とQiskit Aer 0.17.2**。匿名のlocal ideal simulationのみでadmitされ、
  `ari.quantum.sample.local-ideal/v1`を空のcredential scopeで供給する。IBM Quantum
  Runtime、remote simulator、hardwareは、credentialにbindされたbackend、configuration、
  calibration、QPY、golden、replayのevidenceが存在しないためcandidateのままである。
- **OpenROAD MCP 0.6.1とOpenROAD-flow-scripts `26Q3`**。GCD/Nangate45のlocal x86_64 CPU
  flowのみでadmitされ、`ari.eda.openroad.place-route/v1`を供給する。同じdesignの匿名
  exclusive-node SLURM CPU実行は別途promoteされたProvider identityであり、そのlockはGPUを
  要求せず、salted site digestのみを保持する。OpenROADのGPU実行、他のdesignやPDK、
  default flow全体のparityは、この二つのidentityの外側にあり、それぞれ別名のcandidate、
  evidence bundle、人間の承認、verified lockを要する。

promotionはactivationではない。どちらのProviderも、意図的に空であるcheck-in済み
`CATALOG.lock`ではactiveでない。activationはadmission時に取られる、run単位で凍結される
catalog/Provider/Binding lockの別決定のままである。

## extension gate

新しいKnowledge、Provider、Harness entryはそれぞれ`ari.knowledge.registration`、
`ari.providers.registration`、`ari.assurance.registration`のgateを使う。candidate fileは
既存run lockへ入らない。statusを`verified`へ変える前にmaintainerがfull source/data/
container/license pinと全gate evidenceを保持しなければならない。
