---
sources:
  - path: ari-core/ari/manuscript/contracts.py
    role: implementation
  - path: ari-core/ari/manuscript/digest.py
    role: implementation
  - path: ari-core/ari/manuscript/snapshot.py
    role: implementation
  - path: ari-core/ari/manuscript/builder.py
    role: implementation
  - path: ari-core/ari/manuscript/profiles.py
    role: implementation
  - path: ari-core/ari/manuscript/readiness.py
    role: implementation
  - path: ari-core/ari/manuscript/briefs.py
    role: implementation
  - path: ari-core/ari/manuscript/coordinator.py
    role: implementation
  - path: ari-core/ari/manuscript/state.py
    role: implementation
  - path: ari-core/ari/manuscript/repair.py
    role: implementation
  - path: ari-core/ari/manuscript/publication.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-core/ari/manuscript/evaluation.py
    role: implementation
  - path: ari-core/ari/public/manuscript.py
    role: implementation
  - path: ari-core/ari/paper_contract.py
    role: implementation
  - path: ari-core/ari/cli/manuscript.py
    role: implementation
  - path: ari-core/ari/cli/manuscript_repair_runtime.py
    role: implementation
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_draft_executor.py
    role: implementation
  - path: ari-core/ari/rqgm/kernel_harness_integrity.py
    role: implementation
  - path: ari-core/ari/rqgm/evaluation/kca_probe.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/pipeline/stages.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/schemas/manuscript_requirement_profile_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_exploration_snapshot_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_omission_manifest_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_context_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_readiness_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_section_brief_bundle_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_authoring_binding_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_segment_record_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/research_repair_request_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/research_repair_plan_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_repair_transaction_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_auto_repair_round_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_publication_decision_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_publication_lock_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_evaluation_report_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_transition_v1.schema.json
    role: schema
  - path: scripts/sync_manuscript_schemas.py
    role: implementation
  - path: scripts/evaluate_manuscript_complete.py
    role: implementation
  - path: scripts/run_manuscript_complete_release.py
    role: implementation
  - path: scripts/manuscript_complete_release_gates.json
    role: config
last_verified: 2026-08-09
---

# Manuscript Complete V1 契約

規範documentはいずれもunknown fieldを拒否し、安全なcheckpoint相対path、
canonical JSONのSHA-256 identityを用い、read時に自身が広告するdigestを
検証します。生成されたJSON Schemaは`ari-core/ari/schemas/`に置かれ、次で
検査します。

```bash
PYTHONPATH=ari-core python scripts/sync_manuscript_schemas.py --check
```

| Document | Schema version | 恒久的な役割 |
|---|---|---|
| requirement profile | `ari.manuscript-requirement-profile/v1` | requirement、適用可能性、severity |
| exploration snapshot | `ari.manuscript-exploration-snapshot/v1` | 完全なnode/artifact inventoryとscientific winner |
| omission manifest | `ari.manuscript-omission-manifest/v1` | includedとomittedを合わせたinventoryの保存 |
| context | `ari.manuscript-context/v1` | 決定論的でrequirement指向のprojection |
| readiness | `ari.manuscript-readiness/v1` | requirement単位のstatusとauthoring/publication verdict |
| section brief bundle | `ari.manuscript-section-brief-bundle/v1` | 有界かつlaneを意識したwriter入力。必須項目のsilentなomissionがない |
| authoring binding | `ari.manuscript-authoring-binding/v1` | 正確なprofile/context/readiness/briefとtarget build |
| segment record | `ari.manuscript-segment-record/v1` | resume可能なworkflowの入出力transaction |
| repair request/plan | `ari.research-repair-request/v1`、`ari.research-repair-plan/v1` | 固定されたaction、authority、累積budget |
| repair transaction | `ari.manuscript-repair-transaction/v1` | commit済みでimmutableなresolver結果と正確なresource使用量 |
| automatic repair round | `ari.manuscript-auto-repair-round/v1` | 連続したcoordinator roundと累積使用量 |
| publication decision | `ari.manuscript-publication-decision/v1` | 1つのbuildに束縛された6つの独立したgate verdict |
| publication lock | `ari.manuscript-publication-lock/v1` | 最終的にfreshなdecision/build/PDFのinterlock |
| evaluation report | `ari.manuscript-evaluation-report/v1` | 分母の適用可能性を明示したlabel付きprogram metric |
| transition | `ari.manuscript-transition/v1` | append-onlyなstate hash chain |

## Digest lineage

規範上のchainは次のとおりです。

```text
profile + source files/nodes
  → snapshot
  → context + omission manifest
  → readiness
  → section briefs
  → authoring binding
  → PaperBuildV1
  → PublicationDecisionV1
  → PublicationLockV1
```

親のいずれかを変更すると、下流の再利用は無効になります。finalizerはlockを
書く前に、snapshot source、nestされた全`PaperArtifactV1`、5つのmanuscript
input、reproduction結果、そして最終PDFを再hashします。さらに、正確な最終
TeXをbriefのcontextual-negative/forbidden evidence IDと必須disclosureに
照らして検査します。上流のpaper gateが通っていても、この束縛されたcontent
検査の失敗を埋め合わせることはできません。

evidence laneの検査は2か所——archiveのcandidate単位のscreenと、finalizerに
よる正確な最終TeXの検査——にありますが、どちらもidentifierの言及検査であり、
draftがそのevidenceをどう使っているかの判断ではありません。いずれも、全
section briefにまたがる`contextual_negative_ids`と`forbidden_evidence_ids`の
和集合について、evidence ID自体をdelimiterで区切られたcase-insensitiveな
tokenとしてdraft中に探します。tokenのalphabetは`A-Za-z0-9_:/-`なので、
末尾のピリオドはdelimiterになります。そのIDがdraftのどこかに1度でも現れれば
検査は落ちます。どちらの箇所も周囲のclaimの極性を調べませんし、section
briefのIDをそのsectionに限定することもしません。この粗さは意図的です。
ruleは決定論的であり、意図について議論する余地を残しません。renderされた
brief blockはprose上より弱い極性ruleを述べています（「discloseせよ、
positive supportとして使うな」）が、機械的に強制される条件はより厳しい方
——IDが一切現れてはならない——です。したがってnegativeな履歴やinconclusiveな
履歴が原稿に届く経路は、briefの`required_disclosures`と、`negative-results`
および`limitations`のcontent itemです。これらはevidence IDではなく自分自身の
item IDを持ちます。鋭い縁は`results`のcontent itemです。ここにはevidence IDを
keyとするexploratory laneのevidence recordが含まれ、しかもexploratory laneは
`forbidden_evidence_ids`の一部でもあるため、briefはwriterに対して「その
identifierを決してdraftへ書いてはならない」contentを手渡すことがあり得ます。

この2か所は帰結だけが異なります。finalizerの検査はmodeでscopeされません。
publication decisionが計算される限り必ず適用され、`claim_evidence`
sub-verdictへANDで畳み込まれるので、言及があればdecisionはnon-publishableに
なり、lock stepはそれを拒否します。archiveのscreenでは、言及がhardな失格
——`contextual_negative_evidence:<id>`または`forbidden_evidence:<id>`として
記録され、candidateにはさらに`_valid_for_frontier: false`が付く——になるのは
`enforce`のときだけです。`audit`は同一のdiagnosticsを記録しますが、candidate
のeligibilityは変えません。

## Status の意味論

requirement statusはちょうど`satisfied`、`not_applicable`、`unavailable`、
`missing`のいずれかです。`unavailable`はresolverのavailabilityについての
evidenceであって、成功についてのevidenceではありません。authoringは
authoring-criticalな`missing|unavailable`によってblockされ、publicationは
未解決のpublication-critical requirementすべてによってblockされます。

top-levelのpublication decisionがpublishableになるのは、適用される
`manuscript_readiness`、`claim_evidence`、`assurance`、`build_compile`、
`reproduction`、`freshness`の各sub-verdictがどれもfailしない場合に限ります。
model validatorはこの論理ANDを再計算します。

## 公開 gate

### Sub-verdict の不変条件

`PublicationDecisionV1`はちょうど6つの`PublicationSubVerdictV1` entryを持ち、
その`decision`はその6つだけの関数です。この構造はread時に強制されるため、
手で編集されたdecision documentや切り詰められたdecision documentが、自分の
reasonが支える以上に緩いverdictを提示することはできません。

- gate名は[Status の意味論](#status-の意味論)で挙げた6つと厳密に一致し、
  それぞれ1度ずつ現れなければなりません。gateの欠落、gateの重複、その集合の
  外のgateは拒否されます。
- reason codeのない`fail` sub-verdictは拒否されるため、blockされたdecisionは
  常に「なぜblockされたか」を述べます。
- 1つのsub-verdict内でのartifact digestの重複は拒否されます。
- `decision`は6つのstatusから再計算した論理ANDと一致しなければなりません。

契約が制約*しない*ものも、制約するものと同じくらい重要です。6つの
sub-verdictはsequenceではなくsetとして検証されます。gateが別の順序で並んだ
decisionも検証は通りますが、その順序はcanonical JSONの一部なので
`decision_digest`が変わり、並べ替えたcopyは下流のすべてにとって別のdecision
になります。`artifact_digests`と`reason_codes`はpatternもclosedな語彙も持たない
ただの文字列であり、この層ではlinkされたdigestがdigestであることすら検査され
ません。そして`reason_codes`は`pass`と`not_required`にも許されています——
書かないのはproducerの側だけです。

そのproducerが`ari-core/ari/manuscript/publication.py`の固定assemblerであり、
schemaを4つの点で狭めます。gateを下表の順序でemitすること、reason codeを
`fail`にだけ書くこと、失敗したgate1つにつきreason codeをちょうど1つ書くこと、
そして`not_required`をemitするのは`assurance` gateだけであることです。

| Gate | `fail` 時の reason code | link される artifact |
|---|---|---|
| `manuscript_readiness` | `manuscript_not_publication_ready` | readiness reportのdigest |
| `claim_evidence` | `final_claim_gate_failed` | paper buildのclaim gate reportのdigest |
| `assurance` | `required_certification_missing_or_failed` | admitされたcertify-attestationのdigest群——0個以上 |
| `build_compile` | `paper_compile_failed` | buildのcompile digest |
| `reproduction` | `paper_reproduction_failed` | reproduction recordのdigest |
| `freshness` | `publication_input_stale` | なし |

1 gate 1 artifactというpatternを破るgateが2つあります。`freshness`は意図的に
何もlinkしません。これは、再hashしたattempt snapshot source、記録された
manuscript stateが`authored`または`finalized`であること、正確なbuildにnestされた
`PaperArtifactV1`の集合が空でなく記録されたidentityへ再hashすること、そして
——enforceのときだけ——束縛された5つのmanuscript inputの連言だからです。個々の
artifactではなく、その入力集合全体の性質なのです。`assurance`は空になり得る
setをlinkします。admitされたcertify-attestation itemのsnapshot digestであり、
1件もadmitされなかった場合やattemptの`source_snapshot.json`が読めなかった
場合には空tupleになります。残る4つは常にdigestをちょうど1つlinkします。

3番目の場合はrecordが存在しないときです。gateが判定するevidenceがそもそも
存在しない——paper buildがclaim gateを持たない、compile recordがない、
checkpointに安全なnon-symlink pathのreproduction fileがない——とき、runtimeは
それでもgateをemitし、実digestの代わりに全ゼロのsentinel
`sha256:0000…0000`をlinkします。3つのいずれの場合もgateはすでに`fail`なので、
sentinelは荷重を担うものではなく診断的です。evidenceが存在しなかったことを
記録するだけで、passしているgateに付くことは決してありません。

### Evidence と pass 条件

各gateは自分が読むevidenceを名指しし、固定されたpass条件を1つ適用します。
不在から何かが推論されることはありません。evidenceが欠けている、読めない、
あるいは安全なnon-symlink pathで到達できないgateは失敗します。

| Gate | Evidence | pass する条件 |
|---|---|---|
| `manuscript_readiness` | 束縛された`ManuscriptReadinessReportV1` | その`publication_verdict`が`ready`であること |
| `claim_evidence` | buildのclaim gateと正確な最終TeX | gate statusが`pass`であり、**かつ**最終TeXが束縛されたbriefの要求する全disclosureを載せ、それらのbriefのcontextual-negativeまたはforbidden evidence IDを一切言及していないこと |
| `assurance` | compile済みcontextの`assurance` blockとattemptの`source_snapshot.json` | [Assurance sub-verdict と予約されている kernel binding](#assurance-sub-verdict-と予約されている-kernel-binding)の条件が成り立つこと。contextが`assurance.mode: enforce`を記録していない限り`not_required`になります |
| `build_compile` | `PaperBuildV1.status`とそのcompile record | statusが`finalized`であり、compile recordのstatusが`completed`であること |
| `reproduction` | checkpoint内の`ors_phase1.json` | fileがnon-symlink pathに存在し、`executed`、`exit_code = 0`、空の`missing` list、`error`なしを記録していること |
| `freshness` | attempt snapshot、記録されたmanuscript state、buildにnestされたartifact、そしてenforce時は束縛された5つのinput | それらすべてが記録されたidentityへ再hashし、stateが`authored`または`finalized`であること——[Sub-verdict の不変条件](#sub-verdict-の不変条件)で述べた連言です |

このうち2つの条件は、evidence列が示唆するより広い範囲を持ちます。
`claim_evidence`は、section brief bundleがcheckpoint内に露出していない、
symlinkである、parseできない場合にも失敗します。buildが`final-tex` artifactを
ちょうど1つ名指ししていない場合、あるいはそのTeXが読めない場合も同様です——
義務は読めなくすることで免除できません。そのdisclosure側は、必須textとTeXの
双方をnormalise（TeXのcontrol sequenceを落とし、非英数字をすべて単一の空白へ
畳み、case foldする）した後に走るsubstring検査なので、markup、句読点、大文字
小文字、改行では破れません。ただしdisclosureの語は依然として連続して現れる
必要があります。evidence ID側は[Digest lineage](#digest-lineage)の
delimited-token ruleです。

`freshness`は、attempt snapshotが`missing`と記録したsourceが再び現れたとき、
そしてpathを持つsourceにdigestとsizeが記録されていないときにも失敗します——
安定したbyte identityを持たないentryはpublicationをauthoriseできません。
enforce時のみのbound-input節は、5つのinputがattempt directory自身の
`requirement_profile.json`、`context.json`、`readiness.json`、
`section_briefs.json`、`authoring_binding.json`であること、buildのinput artifact
の中でまさにそれらの相対pathで宣言されていること、buildが宣言するidentityへ
再hashすること、bindingと1本のprofile/context/readiness/brief lineageを共有する
こと、target buildのID、revision、runを名指しすること、そしてauthoring verdictが
`ready`または`ready_with_disclosures`であることを要求します。`audit`ではこの節は
一切適用されません。auditは意図的にwriterをcompile済みbundleへ束縛しないから
です。snapshot、state、build-artifactの各節は依然として成り立ちます。

decisionが計算されるのは、runtime manuscript modeが`off`でなく、
`paper_build.json`が存在し、context、readiness、bindingのpathが露出している
ときだけです。そうでなければ何も書かれず、decisionの不在はpassではありません。
その3つのpathと`paper_build.json`については、checkpointの外の位置やsymlink
componentはgateの失敗ではなくraiseになります。decisionは`audit`と`enforce`の
どちらでもattemptへ`publication_decision.json`として書かれます。transitionを
記録するのは`enforce`だけで、reason code `publication_publishable`または
`publication_blocked`とともに`finalized`または`publication_blocked`へ遷移します。
lock stepは3つのfreshness検査すべてを——modeに関わらずbound-input節も含めて
——再実行し、記録されたattemptがbindingのものであること、そのstateが
`finalized`であることを要求し、さらに`reproduction` sub-verdictが`pass`でない
decision、そのsub-verdictが記録したdigestへもはやhashしない`ors_phase1.json`、
最終PDFをちょうど1つ特定できないbuildを拒否します。

### decision が束縛しないもの

record自体は意図的に狭く作られています。field集合の全体は`schema_version`、
`run_id`、`attempt_id`、`paper_build_digest`、`authoring_binding_digest`、
`readiness_digest`、6つのsub-verdict、`decision`、`decision_digest`であり、
unknown fieldは拒否されるため、それ以外のものを付けることはできません。
lineage中の他のidentityはいずれかのdigestをdereferenceして辿るものであり、
必要とするconsumerはそれが指すartifactを読まなければなりません。

| Identity | 到達経路 |
|---|---|
| profile、context、brief-bundle、source-snapshotの各digest、target buildのIDとrevision | `authoring_binding_digest` |
| checkpoint ID | bindingの`source_snapshot_digest`が名指しするexploration snapshot |
| PDFとclaim-links artifactのdigest | `paper_build_digest`、finalized buildの`final_artifacts`内 |
| EAR digest | `paper_build_digest`、必須の`PaperBuildV1.ear_digest`として |
| code-bundle lockのpathとdigest | contextの`reproducibility`。checkpointがそのlockを持つ場合 |
| readiness evaluatorのversion | `readiness_digest`、`ManuscriptReadinessReportV1.evaluator_version`として |
| requirement-profileのpolicy version | bindingの`profile_digest`が名指しするprofile |

linkされたdigestが、その背後の検査より狭いこともあります。`claim_evidence`は
最終hard gateと、[Digest lineage](#digest-lineage)で述べたfinalizerによる正確な
最終TeXの検査との連言ですが、linkするのはgate reportのdigestと、失敗時には
上表のreason code 1つだけです。したがってこのsub-verdictは、2つ目の検査が
読んだbrief bundleや最終TeXを特定しませんし、2つの条件のどちらが失敗したかも
特定しません。

間接ではなく実際に欠けているものが2つあります。Harness catalog snapshotの
digestはdecisionにfieldを持たず、`ari.manuscript`のどこにもありません。
[RQGM node projection](#rqgm-node-projection)に記すとおり、それは保持された
attestation fileの内側に留まり、そのfileの相対pathとcontent digestだけで
addressされます。そしてdecisionは`schema_version`定数を超える自身のversionを
持ちません——それを生成したcodeを名指しするevaluator versionやpolicy versionは
recordにありません。したがってdecisionの再現は、記録されたevaluator identity
ではなく、`decision_digest`と固定assemblerとpin済みinputに依拠します。

## Harness attestation の projection

nodeの`attestation_refs`にある空白でない文字列は、それぞれexploration snapshot
の1つの`harness-attestation` artifactになります。artifactに記録されるstatusは
admissibilityについての言明であって、attestation自身のverdictの写しでは
ありません。

| Artifact status | 条件 |
|---|---|
| `invalid` | 記録されたpathが安全なcheckpoint相対pathでない、symlink componentを辿る、fileが読めないか有効なJSONでない、`HarnessAttestationV1`の検証（自ら広告する`attestation_digest`の再計算を含む）に落ちる、あるいはその`node_id`が参照元のnodeでない |
| `missing` | 安全な相対pathが通常fileに解決しない |
| `stale` | 有効でnodeに属するが、その`target_digest`がnodeの`verified_target_digest`でない——nodeがそれを持たない場合を含む |
| `present` | 有効でnodeに属し、nodeの正確な現在のtargetへ束縛されている |

parseできたattestationは、拒否されたからといって捨てられることはありません。
artifactは`attestation_digest`、`target_digest`、`verdict`、`tiers`（sort済みの
distinctなproperty tier）、`belongs_to_node`、`target_matches`、
`verification_contract_digest`、`baseline_harness_lock_digest`をmetadataとして
保持するので、node不一致やstaleなattestationも診断可能なまま残ります。parse
より前に拒否されたattestationが持つ情報はより少なくなります。安全でない記録
pathは`unsafe_path` markerを記録し——path自体が使えない場合は逐語の
`recorded_ref`も加わります——一方、fileが不在、読めない、あるいはinvalidな場合は
metadataを一切持ちません。attestation自身のcontent、`screen`/`validate`/`certify`
のtier ladder、verdictの語彙は
[Knowledge、Capability、Scientific Assurance](knowledge_capability_assurance.md)
で定義します。

`certify_pass`はさらに別のmetadata上の事実で、artifact statusとは独立に記録
されます。これは4条件の連言であり、そのどれか1つから推論されることは決して
ありません。attestationがそのnodeに属すること、全体の`verdict`が`pass`である
こと、その`target_digest`がnodeの`verified_target_digest`と等しいこと、そして
`certify` tierのproperty resultを少なくとも1つ持ち、`certify` tierの結果が
すべてpassしていること。`HarnessAttestationV1`はpropertyがすべてpassしていない
`pass` verdictをすでに拒否するので、最後の条件で荷重を担っているのは`certify`
tierが存在すること自体です。

nodeの`certify_attestation_item_ids`に入るのは、`certify_pass`が真である
`present` artifactだけです。`enforce` assurance modeでは、先行するlane ruleを
生き延びたnodeが`publishable`になるのは、そのtupleが空でなく、*かつ*
`assurance_status`が`pass`であり、*かつ*`assurance_tier`が`certify`であり、
*かつ*`verified_target_digest`が空でない場合に限ります。4つのいずれかを欠く
nodeは、理由`certification_required`とともに`exploratory` laneへ入ります。
したがってscreen tierのpassも、置き換えられたtargetに束縛されたcertify passも、
どちらもadmissibleなevidenceとして保持されますが、どちらもpublication
certificationではありません。

admissibilityはsnapshotがcompileされるときに一度だけ決まり、以降のstepが
それを見直すことはありません。attestation fileを開いて判定する場所は
`ari.manuscript.snapshot`だけであり、下流のconsumerはいずれも凍結された結果を
読みます——contextの`assurance.attestation_item_ids`、`MC-AS-001` readiness
resolver、finalizerは、いずれもitem IDとstatusを所与として扱います。
`finalize_runtime_publication`も`lock_runtime_publication`も、attestationを再度
parseしたり、node所有やtarget一致を再検査したり、何かをcertifyしたりしません。
finalizerが消費するattestationの事実は、admitされたitem IDについてすでに記録
されているdigestだけであり、それをattemptの`source_snapshot.json`から読み戻す
ため、`assurance` sub-verdictは自分が再解釈していないbyteを引用することに
なります。

後段のstepが再検証するのはfileであって、verdictではありません。finalizerと
lock stepはどちらも、pathを持つsnapshot artifact——Harness attestationを含みます
——を、compile時に記録されたdigestとsizeに対して再hashし、`missing`と記録された
artifactが依然として不在であることを要求し、byte identityを一切持たないpath
付きartifactを拒否します。この最後のruleがあるため、symlinkされた、あるいは
parseできないattestationは単に不活性なのではありません。それはdigestの記録が
ない`invalid`なので`freshness`に落ち、decisionが計算されるあらゆる場所で
decisionをblockします。保持されたattestationをその場で編集した場合も同様に
freshnessに落ちるのであって、admitされる内容が変わるわけではありません。
freshnessが見ない拒否は1つだけ——相対pathに解決しなかった安全でない記録path
です。再hashすべきpathが保存されなかったからです。

要求に応じたcertificationは存在しますが、decisionの上流かつbudgetの下でのみで
あり、決してdecisionの内側ではありません。`assurance_certification`はrepair
resolver kindの1つで、そのexecutorは選ばれたcandidateに対してRQGM runtime自身の
`certify_node`を呼んでcheckpointを書き換え、experiment run 1件を課金され、その
runtimeへ到達できないときは`certification_runtime_unavailable`とともに
`unavailable`を記録します。admissibilityへの効果は、repair loopのrebuild stepで
snapshotが再compileされたときにだけ現れます。実際、attestationのstatusを動かし
得る唯一のものが再compileです。`stale`なattestationが`present`になるのは、それを
名指しするnodeが次のcompile時に一致する`verified_target_digest`を持つときで
あり、それより前ではありません。

## Assurance sub-verdict と予約されている kernel binding

`assurance` sub-verdictはmanuscript層の内部で計算されます。Constitutional
Kernelへ委譲されるものではありません。これが必要になるのはcontextの
`assurance.mode`が`enforce`のときだけで、それ以外では`not_required`として記録
され、その場合decisionをfailさせることはできません。enforceの下でpassするのは、
contextが`publication_candidate`を持ち、admitされたcertify attestationのitem IDが
少なくとも1つあり、それらのitemについてattemptの`source_snapshot.json`から読み
戻したdigestの集合が空でないときだけです。candidateの欠落、item集合が空である
こと、snapshotが読めないことは、いずれも
`required_certification_missing_or_failed`でfail-closedになります。それらのitem
IDの背後にあるadmission ruleは上記の`certify_pass`の連言です。この層では
attestationを開き直すものは何もなく、記録された
`verification_contract_digest`や`baseline_harness_lock_digest`を現在のlockと
比較するものもありません。

`ConstitutionalKernel.validate_harness_integrity`は`publication`引数を受け取り、
attestationがpassしていないのにpublicationが主張された場合、あるいは
verification contractが`certify` tierを要求するか`block-publication`のfailure
policyを持つのにpassしているcertify property resultが存在しない場合に
`CK-HAR-018`をraiseします。**production pathで`publication=True`を渡すものは
ありません。** RQGM runtimeのK/C/A harness reportはこの引数なしで検査を呼び、
manuscript publication evaluatorはそもそもこの検査を呼びません。このflagを立てる
codeは、kernelのcode別のtest fixtureと、K/C/A fault-injection probeの
`reviewer_publishes_uncertified` mutationだけであり、これらはruleが発火することを
示すために存在するのであって、実際のpublicationをgateするためではありません。

2つの層をつなぐbindingは設計されていますが、**未実装**です。それはpublication
evaluatorに、正確なtarget contractとattestationを固定integrity検査へ手渡させる
もので、publication subjectのnodeとconfiguration ID、選択されたsourceとcode
digestの集合、カバーされたScienceData measurement、HarnessのID/version、runner、
containerとdatasetのlock、Harness契約が要求するenvironmentまたはProvider binding、
そして現在のcatalog lockとattestation revisionを覆い、不一致、必須certificationの
欠落、block-publicationの所見、staleなbindingのいずれも、assurance verdictへ畳み
込むのではなく独立したpublication failureとしてraiseするものでした。今日その
どれも存在しません。実際に成り立っているbindingは、`HarnessAttestationV1`自身が
持つものと、projection時に記録されたnode所有、target digest、verdict、certify
tierの各条件です。

### Certification は検証されるだけで、再実行されない

finalizerはcertificationを取得できません。`finalize_runtime_publication`は、
compileがすでにcontextへprojectした`assurance` blockを読み、admitされたitem IDを
attemptの`source_snapshot.json`のdigestへ解決し、そこで止まります。Harness runを
dispatchせず、assurance runnerをimportもしません。`assurance` gateはそのprojection
を追認するか拒否するかしかできず、そこに何かを付け加えることはできません。

したがって上記のprojection ruleがそのままfailure modeでもあります。projectionが
拒否したattestation——nodeに属さない、置き換えられたtargetへ束縛されている、
passしている`certify` tierを持たない——は`attestation_item_ids`に何も寄与しない
ので、`enforce`の下では、certificationがすべて拒否されたcandidateはadmitされた
集合が空のままfinalizerに届き、certificationが一度も試みられなかった場合と
まったく同じようにfail-closedになります。どちらも
`required_certification_missing_or_failed`に着地します。finalizerはこの2つの場合を
区別もしませんし、どちらも修復しません。

現在のattestationを得ることは、別の、より早い段階の行為です。存在する経路は
`assurance_certification` repair kindです。そのexecutorは
`ari-core/ari/cli/manuscript_repair_runtime.py`にあり、verified-context selectorが
返すcandidateに対してRQGM runtimeの`certify_node`を呼び、その最小costが宣言する
experiment run 1件を課金し、残りbudgetでそれを賄えないときは
`certification_budget_exhausted`で、そうしたruntimeがattachされていないときは
`certification_runtime_unavailable`で拒否します。coordinatorはこれをmanuscript
準備中——authoringの前、そしてfinalizerが従うpaper stageの前——に実行し、
`ari manuscript repair`は同じrequestを明示的に受け付けます。publish時にcertifyする
経路は存在しません。publicationはcertification evidenceを消費するのであって、
決してそれを製造しません。

## RQGM node projection

compilerは、手渡されたnodeオブジェクトからRQGM stateを読みます。
`ari.manuscript`は`ari.rqgm`から何もimportせず、読み取りはすべてduck-typedです。
attributeまたはmapping keyであり、無ければdefaultです。
`ManuscriptNodeSnapshotV1`上のnode単位の型付きprojectionは、
`assurance_status`、`assurance_tier`、`frontier_class`、`attestation_refs`、
`certify_attestation_item_ids`、`verified_target_digest`、`property_verdicts`と、
repair lineageの`repair_request_id`、`repair_requirement_ids`、
`repair_context_digest`、`repair_allowed_changes`です。

`valid_for_frontier`は読まれるのではなく導出されます。nodeのmetricsが
`_valid_for_frontier: false`または真値の`_stale`——RQGM frontier repairが論理的
消去のために書くsentinel——を持つときにfalseになります。`metrics`自体はJSON
serialisableである限り逐語でcopyされるため、残りのRQGM sentinel——
`_stale_reason`、`_erasure_event_id`、`_utility_policy_hash`のstamp——は、
compilerのどのruleも読まない型なしのmetricとしてsnapshotへ生き残ります。
compilerが解釈する唯一のmetric keyは`_scientific_score`で、これは型付きの
`scientific_score`になります。それが無い場合、compilerはunderscoreで始まらない
有限のmetricのうち最大のものへfallbackします。

optional fieldの欠落は明示的な不在であって、legacyの成功ではありません。

| Field | Default | default が主張すること |
|---|---|---|
| `assurance_status`、`assurance_tier`、`frontier_class` | `""` | assurance verdictが記録されなかった |
| `verified_target_digest` | null | verified targetが束縛されなかった |
| `certify_attestation_item_ids` | 空 | nodeに属し、かつcertifyをpassしたattestationが無い |
| `valid_for_frontier` | true | erasure sentinelが存在しなかった |

これらのdefaultが上記の`enforce` certification ruleを満たすことは決してありません。
`off`と`audit`ではこれらはlegacyの姿勢であり、それ自体でnodeを降格させることは
ありません。`audit`が降格させるのは`pass`でない`assurance_status`を記録した
nodeだけなので、assurance stateをまったく持たず先行するlane ruleを生き延びた
nodeは、どちらのmodeでも`publishable`のままです。

run levelのidentityはnodeのprojectionより薄いものです。`run_id`は`tree.json`
または`nodes_tree.json`から読み、checkpoint directory名へfallbackします。
`checkpoint_id`はそのdirectory名です。`exploration_mode`、
`research_contract_digest`、`research_question`はそれらと並べて運ばれます。
`selection_policy_digest`はcompiler自身の固定scientific-winner policyのdigestで
あって、RQGMのutility policyのdigestではありません——これはcompiler versionの定数
なので、winnerがどう選ばれたかを特定しますが、どのpolicyがnodeをscoreしたかは
決して特定しません。

projectされないもの: RQGMのepoch identityとHarness catalog snapshotのdigestは、
`ExplorationSnapshotV1`にも`ManuscriptNodeSnapshotV1`にもfieldを持ちません。
attestation自身の`epoch_id`と`producer_epoch_id`、そして上記の
`baseline_harness_lock_digest`から辿れるcatalog snapshotのdigestは、保持された
attestation fileの中に留まり、その相対pathとcontent digestだけでaddressされます。
governanceとadversarialの所見はそもそもadmissibilityの入力ではありません。
`ari.manuscript`はどちらのsubsystemへの参照も含まないため、それらが原稿に届くのは、
上記のnode fieldやcompilerが読むcheckpoint artifactへすでに書き込まれたstateを
通じてだけです。

## PaperBuild との関係

legacyな`PaperBuildV1`はpaper buildの契約であり続けます。enforceの下では、その
input artifact集合にさらに`manuscript-profile`、`manuscript-context`、
`manuscript-readiness`、`section-briefs`、`manuscript-authoring-binding`が含まれ
ます。`PaperBuildV1.status=finalized`だけでは、Manuscript Completeのpublicationが
許可されたことにはなりません。`PublicationLockV1`が最終のinterlockです。

この統合は2つ目の契約を作るのではなく、その契約の内側に留まりました。`PaperBuildV2`
は存在しません。5つのmanuscript inputは`ari-core/ari/paper_contract.py`の
`PaperArtifactRole`語彙に追加され、authoring skillによって通常のinput artifactとして
束縛されます。これらはbuildの`required_inputs`には入っておらず、そこは今も
`science-data`、`figure-batch`、`retrieval-records`、`ear-manifest`だけを挙げます。
これらの存在と同一性を強制するのはbuild schemaではなく、`freshness` gateの
enforce限定のbound-input条項です。5つを1つも持たないlegacyなbuildが今も変更なしに
validateを通るのはそのためです。

この語彙には、予約されたまま使われていないメンバーが1つあります。
`publication-decision`は5つと並んで宣言され、生成される`paper_build_v1`と
`paper_model_call_batch_v1`のrole enumにも現れますが、どのmodeでもこのroleを持つ
artifactを構築するコードは存在しません。decisionはattempt directoryに
`publication_decision.json`として書かれ、buildのartifact集合の完全に外側に置かれま
す。つまりrole一覧は、buildが運べるものを実際より多く見せています。これをinventory
として読む読者は`input_artifacts`や`final_artifacts`の中にdecisionを探して、どちらに
も見つけられません。finalizedなbuildのartifactを辿って公開が許可されたかどうかを知ろ
うとするconsumerは、明示的に失敗するのではなく何も分からないまま終わります。束縛は逆
向きです。`PublicationDecisionV1.paper_build_digest`がbuildを名指し、`PaperBuildV1`
にはdecisionを名指すfieldがありません。したがってこの辿り方はdecisionを起点にしたと
きだけ成立します。

安定したread typeと固定のcompiler helperは`ari.public.manuscript`からexportされ
ます。可変なcoordinator内部はpublic APIではありません。

## RQGM archive の provenance

`paper_draft_archive.jsonl`はpaper archiveの既存のrecord streamであり続けます。
Manuscript Completeが有効なとき、各recordはさらにattempt、
binding/profile/context/readiness/briefの各digest、順序付きのsection brief digest、
evidence laneのID集合、disclosure、omission数、そしてcanonicalな
`manuscript_input_fingerprint`を運びます。candidateのdiagnosticsは、正確な
artifact digest、read-onlyなgate-report digest、contextual-negativeおよびforbidden
evidence IDの言及、欠けているdisclosure、hard失格の理由を記録します。

`paper_archive_state.json.manuscript_authoring`は同じfingerprintを凍結し、runの
現在のstatusを記録します。このstatusはoutcomeのclosedな集合ではありません。
draftが1つも生成される前に1つの値が書かれ——enforceでは`bound`、auditでは
`audit_legacy_authoring_observed`、直前のstate、manuscript mode、あるいはすでに
記録されたdraftが現在のbundleと食い違うときは`stale_detected`——その後、outcome
`manuscript_bound_winner`、`bound_linear_fallback`、`authoring_backend_failed`、
`audit_legacy_archive_winner`、`audit_legacy_linear_fallback`、
`verification_or_fallback_failed`のいずれかで上書きされます。最後のものは、共通の
verification tailへの——あるいはlinear fallback自体への——handoffがraiseしたときに
書かれます。`bound`のまま残されたcheckpointは、そのarchiveがoutcomeの書き込みに
到達しなかったものです。`stale_detected`が終端になるのはenforceの下だけで、
enforceは続行を拒否します。auditではrunは進行し、recordは
`audit_legacy_linear_fallback`で上書きされます。したがってresumeされたenforce runは、
欠けている、異なる、あるいは束縛されていないdraft fingerprintを継続の前に拒否
します。これらのarchive recordはprovenanceのsurfaceであり、規範的なreadinessや
最終的な`PublicationDecisionV1`の契約を置き換えるものではありません。

canonicalなdraft pathへ到達するarchive winnerはちょうど1つです。
`materialize_winner`は純粋なselect-and-copyです。勝ったdraft自身の`.tex`を
checkpointの`full_paper.tex`へcopyし、それ以外は何もしません——gate呼び出しも、
再scoringも、LLM呼び出しもありません——そしてwinnerがmaterialise可能な`.tex`を
持たないときはそのpathに手を触れないので、winnerのいないarchiveは失敗するのでは
なくlinearの結果へ縮退します。そのfileを*生成*するstageの中で、archive経路上の
writerはこれだけです。`write_paper`は自身の
`skip_if_exists: {{checkpoint_dir}}/full_paper.tex` guardによってno-opになり、
`paper_refine`——`ari-core/config/workflow.yaml`で
`{{checkpoint_dir}}/full_paper.tex`をoutputとして宣言する唯一の他のstageであり、
そうでなければmaterialiseされたbyteの上でrefineしてしまうもの——は
`HANDOFF_DISABLED_STAGES`に名指しされ、linear pipelineへのhandoff呼び出しで
disabled stageとして渡されます。この集合が持つのは`paper_refine`だけです。この
抑止はwinnerが実際に存在することを条件とします。handoffは永続的なbest-belief
archive recordと既存の`full_paper.tex`の*両方*をkeyにするので、fail-openやfallbackの
runでは元のstage集合が渡され、両stageともlinear runと完全に同じ挙動をします。
stageの無効化はcascadeしません——`depends_on`が無効化されたstageを名指しするstage
も走ります——そして無効化されるのは`paper_refine`だけなので、`review_paper`と
`merge_reviews`はいつもどおりのartifactを生成し続けます。handoffが抑止するのは、
それらのreviewをTeXへ適用することであって、reviewの計算ではありません。

single-writerであることはgenerationについての言明であって、immutabilityについての
言明ではありません。verification tailは、linearなdraftに対するのと正確に同じ
ように、canonical path上で自らin-placeな編集を行います——`finalize_paper`はCode
Availability blockを注入または更新し、lockされたclaim-evidence検査はその後に編集済み
fileに対して再実行されます。handoffが保証するのは、materialisationとそれを読む
claim-evidence gateとの間で、winnerのcontentを再authoringしたり改稿したりするものが
何も無いということです。

outcome recordはmaterialiseしたwinnerを名指しします。勝ったdraftが`.tex`へ解決する
限り、`manuscript_authoring`はさらに`winner_id`と`winner_tex_sha256`——そのdraft自身の
`.tex`のSHA-256、すなわちcanonical pathへcopyされた正確なbyteであり、そのbyteが
読めないときは空のまま——を運ぶので、buildを`paper_draft_archive.jsonl`のcandidate
recordへ結び戻せます。1つの帰結は意図的なもので、述べておく価値があります。
archive winnerがlinear pipelineの`paper_refine`改稿passを受けることは決してありません。
その改稿は代わりにarchive自身のreviewer駆動の`paper_refine`子ノードで起きるので、
それは各roundのreviewerが構築されるのとちょうど同じだけliveです。そのreviewerは
defaultの経路では最初のroundからliveです。reviewer oracleが注入されていない場合、
`run_archive`はco-evolution branchを取り、各roundはepochのactiveな`paper_reviewer`
promptから`GovernedPaperReviewer`を組み直し——governanceがどれも採用していないときは
founding promptのbyteへfallbackします——その`review`は、revision seamが注入されて
いなくても実際のrevision instructionを返します。`review`がactionableなrevisionを
まったく返さない決定論的でLLMなしのdefault reviewerに至るのは、内側のRQGM runtimeを
構築できずarchiveが統治されない単一roundへ縮退する場合か、callerが自分のreviewer
oracleを注入する場合だけです。

## Program evaluation

`scripts/evaluate_manuscript_complete.py CASES.json --output REPORT.json`は
`ManuscriptEvaluationReportV1`を構築します。各ratioは分子、分母、evidence refを
保持します。分母がゼロのものはstatusが`not_applicable`で値を持たず、満点として
報告されることは決してありません。object入力は`dataset_id`を与えることができます。
裸のlistには`--dataset-id DATASET_ID`が必要です。

reportは固定のevaluator identityでversion付けされます。`evaluator_version`は常に
`manuscript-program-evaluator-v1`であり、caseから読まれる何かではなく
`ari-core/ari/manuscript/evaluation.py`の定数です。これはcompilerの
`manuscript-evaluator-v1`とは別のidentityです。後者はrequirement profileが自身の
`evaluator_compatibility`として広告し、requirement resultとreadiness reportが運ぶ
ものです。2つの文字列は別のものをversion付けしており、独立に動きます。evaluator
関数は`ari.public.manuscript`から`evaluate_labelled_cases`としてexportされ、
`case_id`が重複するcase集合を拒否します。compile、authoring、publicationのどの経路も
これを呼びません。これは手でlabel付けしたcaseに対するofflineの測定であって、決して
gateではありません。

### Metric 語彙

語彙はclosedかつ無条件です。どのreportも、caseの中身に関わらず同じ13のmetric IDを
同じ順序で運びます——測るものが何も無いmetricも、分母ゼロかつstatus
`not_applicable`として存在し、省略されることはありません。12個はratioで、
`silent-omission-count`が唯一のcountです。countは分母がnullで、分子をそのまま値と
して保ち、したがって常に`measured`です。

| Metric ID | 分子 | 分母 |
|---|---|---|
| `requirement-accounting-rate` | `observed_status`が4つのstatus値のいずれかであるlabel付きrequirement | 全label付きrequirement |
| `missing-detection-precision` | `expected_missing`とlabel付けされ、`missing`または`unavailable`と観測されたrequirement | `missing`または`unavailable`と観測された全requirement |
| `missing-detection-recall` | 同じ分子 | `expected_missing`とlabel付けされた全requirement |
| `silent-omission-count` | Σ `max(0, inventory_count − included_count − omission_count)` | なし——これはcountです |
| `inventory-projection-accounting-rate` | Σ (`included_count` + `omission_count`) | Σ `inventory_count` |
| `headline-publishable-evidence-coverage` | Σ `headline_evidence_covered` | Σ `headline_claim_count` |
| `negative-result-visibility` | Σ `negative_result_visible` | Σ `negative_result_count` |
| `unnecessary-repair-rate` | Σ `unnecessary_repair_count` | Σ `repair_request_count` |
| `repair-success-rate` | Σ `repair_satisfied_count` | Σ `repair_request_count` |
| `repair-marginal-cost` | Σ `repair_cost` | Σ `repair_satisfied_count` |
| `attempts-to-finalization` | finalizedなcaseにわたる Σ `attempt_count` | finalizedなcase |
| `rounds-to-finalization` | finalizedなcaseにわたる Σ `round_count` | finalizedなcase |
| `legacy-off-identity-rate` | `off_identity`が真値であるcase | `off_identity` keyを持つcase |

これらの分母のうち4つは、算術ではなく論拠を運びます。

missing-detectionのprecisionとrecallは`missing`と`unavailable`を1つの検出eventへ
畳み込みます。どちらもcompilerが解決できなかったevidenceについての言明だからです。
どちらのmetricも、artifactの不在とresolverの障害を区別しません。

`silent-omission-count`は、includedでもomissionとして記録されてもいないinventory
なので、保存的なprojectionはゼロを報告します。これはcaseごとにゼロでclampされる
ため、自分のinventoryより多くprojectしたcaseは、別のcaseの本物のomissionを相殺
するのではなく何も寄与しません。`inventory-projection-accounting-rate`にはこの
clampが無く1を超え得るので、過剰projectionはcountの内側に隠れるのではなくそちらで
可視のままになります。

attemptとroundはfinalizedなcaseだけで合計され除算されます。未完了のcaseは分子にも
分母にも寄与しないので、難しいcaseを放棄しても平均をよく見せることはできません。

`legacy-off-identity-rate`は、`off_identity` verdictをそもそも述べているcaseで
除されます。このkeyを省いたcaseは、失敗として数えられるのではなく分子にも分母にも
入りません。したがってこのmetricはlabel付けされたoff modeの部分集合を記述するので
あって、datasetを記述するものではありません。

どのmetricの`evidence_refs`も、同一の完全で順序付きのcase IDのtupleです。これらの
refはmetricが計算されたcase集合を特定するものであり、metricごとのprovenanceでは
なく、特定の数値を動かしたcaseへ絞り込まれることもありません。

### metric ではない report field

reportのfieldのうち2つはmetricではなく、分母の意味論を持たず、分母ゼロruleの外に
あります。

`blocked_reason_distribution`は、caseが`blocked_reasons`に列挙した文字列をすべて
数え、理由をkeyとしてsortします。語彙はlabel付けされたcaseが供給したものが
そのままであり、evaluatorはそれを契約に照らして検証もしなければ、closedな理由集合を
定義もしません。

`topology_costs`は`topology`の値ごとに1行で、その値でsortされ、case数に加えて、
caseが`cost`の下で報告した`llm_calls`、`experiment_runs`、`resource_units`の合計を
運びます。`topology`を持たないcaseは`unspecified`の下に集計されます。この3つの
counterがこの契約のemitするcost語彙のすべてです。token counterもwall-clock fieldも
ありません。

## Release evidence

`scripts/manuscript_complete_release_gates.json`は恒久的でclosedなrelease manifest
です。4つのresearch/paper topologyすべて、必須の13のfailure-injection family、
legacyのmigration/rollback test、そして各実行可能suiteを名指しします。
`scripts/run_manuscript_complete_release.py`は、所有する全testが依然として存在する
ことを検証し、suiteを実行し、stdout/stderrをSHA-256で保持し、正確なGit
commit/treeとmanifest digestに束縛された`ari.manuscript-release-evidence/v1`を
emitします。これは運用上のrelease recordであって、科学的なAttestationではなく、
保持されたnative Harness evidenceの代替でもありません。

## Repair の admission と順序

repair requestの集合はreadiness reportだけから導かれます。その周りのplanは、admit
されたpolicy、budget、authority digestを加えるだけです。statusが`missing`または
`unavailable`であり、profile entryが少なくとも1つのresolverを宣言している
requirementはすべて、そのresolver kind——そのrequirementの`resolver_kinds`の最初の
entry——ごとにgroup化されて、ちょうど1つのrequestへIDを寄与します。したがって
resolver kindを共有する複数のrequirementは、requestが1つずつではなく1つの有界な
requestになります。`satisfied`または`not_applicable`のrequirement、およびprofileが
resolverを1つも宣言していないrequirementは、requestをまったく生みません。

requestのidentityは、source contextのdigest、sort済みのrequirement ID、resolver
kind、success predicateにわたるcanonical digestを24桁のhexへ切り詰め、`repair-`
prefixを付けたものです。したがって同じcontext上の同じgapは常に同じrequest IDを
生み、それによってその名を持つcommit済みのtransactionがidempotency keyとして機能
します。

requestは`ari-core/ari/manuscript/repair.py`の固定priority tableで、tier内では
resolver kind名で順序付けられます。tableに無いkindは最後にsortされます。request内の
requirement IDはsortされます。この順序は装飾ではなく荷重を担います。実行はplanの
requestをまさにその順序で辿り、進みながら共有budgetを課金するので、安価な回復が
常にexperimentがbudgetを使い切る前に走ります。`repair.policy: auto`ではcoordinatorは
planの全requestをadmitします。`ari manuscript repair --request`は名指しされた部分
集合だけをadmitします。policyが`disabled`のplanは、そのrequestが何を言おうと何も
実行しません。

| Tier | Resolver kind | なぜここにsortされるか |
|---:|---|---|
| 1 | `projection_rebuild`、`artifact_recovery` | すでに存在するものを再計算または回復してgapを閉じられる可能性がある |
| 2 | `assurance_certification` | すでに存在するevidenceをcertifyする |
| 3 | `literature_search` | 記録された取得であり、新しい測定は無い |
| 4 | `validation_experiment` | 矛盾する、あるいはintegrity上重要な結果を検証する |
| 5 | `baseline_comparison`、`repetition_or_uncertainty`、`ablation` | blockしているclaimのための最小限の新規測定 |
| 6 | `method_clarification` | admitされたmethod recordを必要とする |
| 7 | `limitation_disclosure` | disclosureを記録するのであって、事実を記録するのではない |
| 8 | `human_decision` | 人間なしには閉じられない |

各requestはplan budgetを自分自身の上限として持ち、各kindは固定の最小costを持ちます。
resolverが呼ばれる前の残budgetはplan budgetからすでにcommitされた使用量を引いた
ものです。自分のkindが収まらないrequestは、**resolverが呼ばれることなく**理由
`plan_budget_exhausted`とともに`exhausted`と記録されるので、budget不足のroundが
experimentを中途半端に実行してしまうことはありません。executorが登録されていない
kindも同様に、理由`resolver_unavailable`とともに`unavailable`と記録され、何も消費
しません。

| Resolver kind | 最小の new node / experiment run / LLM call |
|---|---|
| `baseline_comparison`、`repetition_or_uncertainty`、`ablation`、`validation_experiment` | 1 / 1 / 1 |
| `assurance_certification` | 0 / 1 / 0 |
| `literature_search`、`method_clarification` | 0 / 0 / 1 |
| その他すべてのkind | 0 / 0 / 0 |

このadmission検査が覆うのはその3つのcounterだけです。`max_resource_units`はその
一部ではありません。resourceの超過はexecutorが返った後、報告された使用量が
requestまたはplanの上限を超えたときに捕捉され、呼び出しはfail-closedになります。

group化がbudgetの帰属をmergeすることはありません。各requestは自分自身のsuccess
predicate、自分自身のallowed-change集合、そして自分が消費したnode、experiment run、
LLM call、resource unitを正確に記録する自分自身のcommit済みtransactionを保ちます。
累積使用量はmemoryに持ち回るのではなく、検証されたそれらのtransaction recordを合計
して再計算されるので、resumeされたroundはcommit済みのevidenceから始まります。

## Repair commit record

自動repairは、実行された各requestを`ManuscriptRepairTransactionV1`として、
coordinatorの各roundを`ManuscriptAutoRepairRoundV1`として永続化します。どちらも
immutableかつdigest boundです。resumeは、別のresolverを呼ぶ前に、request/authorityの
identity、transaction digest、round digest、roundの連続したsequence、累積budgetを
検証します。改変された、あるいはsymlinkされたtransaction/round recordはfail-closedに
なります。

roundは、それが実行したplanのdigestで識別されます。そのrecordは`auto-rounds/`の下に、
そのdigestから`sha256:`prefixを除いた先頭32文字を名前とするfileで保存され、書き込みと
resume時の読み取りの双方がこの名前を強制するので、filenameが自身の`plan_digest`と
食い違うrecordは拒否されます——空または重複した`plan_digest`、そしてちょうど
`0 … n-1`になっていない`round` sequenceも同様です。transactionはそのrequestで識別され、
`repair-transactions/`の下に`request_id`を名前とするfileで、同じfilename ruleの下に
保存されます。どちらの書き込みもstate storeのwrite-once pathを通り、byteの異なる既存
recordの置き換えを拒否します。

したがって`repair.max_rounds`は、呼び出しごとではなくcheckpoint全体でcommitされた
distinctなroundの数を制限します。新しい呼び出しは最初のexecutor呼び出しの前に永続化
された全round recordをloadし、guardは永続化されたroundの総数——回復されたものに加えて
その後にcommitされたもの——を最大値と比較し、`round_budget_exhausted`として終了します。
再起動してもround budgetは補充されません。loopが返す`rounds`の数は、その1回の呼び出しが
commitしたroundというより狭い数です。

累積の`new_nodes`、`experiment_runs`、`llm_calls`、`resource_units`も同じやり方で、
loopが始まる前に永続化された全transactionの記録された使用量を合計して回復されます。
回復された値が非数値、負、あるいは非有限であれば、ゼロとして読まれるのではなく呼び出しを
fail-closedにします。回復された使用量がすでに設定された最大値を超えている場合、loopは
resolverを1つも呼ばずに`cumulative_budget_exhausted`で終わります。この検査はround
budgetの検査の後に走るので、両方の上限を超えた呼び出しは`round_budget_exhausted`を
報告します。runtime環境に存在しない最大値はゼロとして読まれます。ただしresourceの
最大値だけは任意であり、未設定のときは何も制限しません。

round内では、回復された使用量をplan budgetから引いて各requestに残りのbudgetを与え、
自分のkindの固定最小costが残りに収まらないrequestは、試みられる代わりに`exhausted`で
返されます。`executed`にも`satisfied`にもならなかったroundはloopを終了させ、その理由は
残りのstatusから固定の順序で読み取られます。`human_required`が1つでもあれば
`human_decision_required`、そうでなく`exhausted`が1つでもあれば
`cumulative_budget_exhausted`、そうでなければ`required_resolver_unavailable`です。
自分自身のrequest budgetより多くの使用量を報告するexecutor、あるいは累積使用量をplan
budgetの先へ押し出すexecutorは、silentな切り捨てではなくhard errorになります。

再実行はroundだけでなくrequestの単位でblockされます。resolverはwrapされていて、
transaction fileがすでに存在するrequestが再び呼ばれることはありません。wrapperはその
transactionを読み直し、そのrun、request、request digest、source context digest、
authority digestがadmitされようとしているrequestと一致することを要求し、使用量を
ゼロにした記録済みstatusに加えて`idempotent_reuse` markerと、それが元々課金した
`prior_budget_use`を返します。したがってresumeされたrunは、commit済みの副作用を繰り返す
ことも、そのcostを二重計上することも、別のauthorityの下でそれを再admitすることもできま
せん。1つの場合だけが意図的に両方のbudget検査に先行します。round recordがすでに永続化
されているplanは、resolverを1つも呼ばずにevidenceを再構築して再compileすることで、1回の
呼び出しにつき高々1度だけ調整されます。これはroundをcommitしてからそのroundが生んだ
evidenceを再構築するまでの窓を閉じるものです。再compileが同じcontext digestと
requirement statusのvectorを返した場合、loopは`no_progress_cycle`として停止します。
