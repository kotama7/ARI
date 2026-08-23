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

# Knowledge、Capability 与 Scientific Assurance

ARI 将程序性知识、执行权限和独立验证分开。三者拥有不同 registry 与 identity；即使
package 名、transport、vendor 或 repository 相同，也不会合并。

| 概念 | 含义 | canonical 实现 |
|---|---|---|
| **Knowledge Skill** | 描述做什么、为什么、何时以及顺序的不可执行、内容寻址知识 | `ari.knowledge` |
| **Capability** | 如 `ari.execution.compile/v1` 的带版本语义执行契约 | `ari.capability_binding` ontology |
| **Capability Provider** | 提供一项或多项 Capability 的执行主体 | `ari.providers`，复用 `ari.mcp` 与现有 Provider lock |
| **MCP** | Provider 的 transport / discovery protocol | `ari.mcp` |
| **Tool** | Provider 的原子 operation | 固定在 Provider lock 中 |
| **Capability Binding** | 对单个 run/epoch 从 requirement 到 `tool_ref` 的确定性解析 | `ari.capability_binding` |
| **Harness** | 对声明 target/property/scope 的独立 verifier | `ari.assurance` |
| **RQGM** | 治理谁生成、使用、忽略或歪曲权限与证据 | `ari.rqgm` bridge |

规范上的不等式为：

```text
Knowledge Skill != Capability Provider
Capability Provider != Harness
Harness != Evaluator
MCP != Skill
Tool description != procedural knowledge
Skill instruction != executable authority
```

## legacy Provider 名称

历史 Python 类型与磁盘名称描述的是可执行 MCP Provider，而不是 Knowledge Skill。

| legacy 名称 | 正式产品含义 |
|---|---|
| `SkillManifestV1` / `skill.yaml` | Capability Provider Manifest |
| `SkillConfig` | Capability Provider runtime configuration |
| `SkillConnection` | MCP Provider connection |
| `SKILLS.lock` | Provider 与 live tool schema 的 run snapshot |

`CapabilityProviderManifest`、`CapabilityProviderConfig`、
`MCPProviderConnection`、`ProviderLock`是现有 class 与 serialized bytes 的 semantic alias。
`skill.yaml`和`SKILLS.lock`仍是唯一 canonical v1 文件；ARI 不创建`provider.yaml`或
`PROVIDERS.lock`，因此一个 run 不会有两个真相源。`ari-skill-*` prefix 保持兼容；CLI、
API 和 UI 在表示执行权限时使用“Capability Provider”。

## dependency 边界

```text
ari.rqgm.knowledge_bridge -> ari.knowledge
ari.knowledge             -> ari.capability_binding contracts
ari.capability_binding    -> ari.providers / ari.mcp

ari.rqgm.assurance_bridge -> ari.assurance
```

`ari.knowledge`和`ari.assurance`不 import `ari.rqgm`。`ari.assurance`不绑定 Agent tool，
`ari.providers`不选择 Knowledge 或 Harness。共享契约位于`ari.protocols`，read-only
supported API 位于`ari.public`。

## 全局 invariant

支配这三个 registry 的 invariant 大多写在各自适用的小节里。下面四条足够跨节，缺了它们
去读任何单独一节都会得出错误推断。

1. **每个 trust anchor 都是完整 digest。** manifest、body、snapshot、contract、lock 与
   Attestation 一律以`sha256:`加 64 位小写十六进制固定。RQGM 较短的`hash12`在这里只是
   兼容与显示用的 key：`hash12`仍是 RQGM 自己对 prompt、policy、registry 与 schema-v1
   event 的 content identity 方案，但本文所述的任何 admission、binding 或 Attestation
   都不由截短值决定。
2. **`active`是 lock membership，而不是可变的 catalog status。** 一个 Knowledge Skill、
   Provider 或 Harness 之所以在某次 run 中 active，是因为被冻结的 lock 指名了它。catalog
   的行是 entry 被 review 与 promote 的地方，不是被开启的地方；因此编辑 catalog 无法激活
   一次已经 admit 的 run 内部的任何东西。
3. **capability 可见性是交集，绝非并集。** 可见集合是 Provider Lock、active Capability
   Binding Lock、role authority、phase policy 与 call context 的交，再减去 user-disabled
   tool。缺少其中任何一项的 tool 都不可见，无论其余各项接纳了多少次。
4. **compatibility default 下的`simple_bfts`是 null diff。** 选择`simple_bfts`并让本文
   所有特性保持 default 时，不会出现任何新的 import、file、metric、field、snapshot、
   lock、prompt byte 或 visible tool。

## run admission 与固定 identity

启用`ari_rqgm`时，trusted coordinator 必须在第一个 research node 前完成：

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

admission transaction 保存在`rqgm/kca/admission-v1/`。resume 读取持久化 snapshot 与 lock，
不会对当前 catalog 重新解析。Skill、binding 或 Harness 只能通过 append-only revision 在
epoch 边界增加；node 启动后不能替换 active Knowledge body、binding 或 target Attestation。

instruction identity 包含 base 与 active RQGM prompt hash、有序 Knowledge body hash、
composition digest、Capability Binding Lock、Verification Contract 及 active Harness Lock
digest。Provider tool description 是位于 authoritative instruction 下方的不可信 operation
metadata；Knowledge 正文或 Provider description 不能扩大 visible tool 集合。

## Knowledge package

package 包含`SKILL.md`、`skill.meta.yaml`及可选`references/`，manifest 为
`KnowledgeSkillManifestV1`。执行 field、command、environment/credential 声明、entrypoint
与 transport 都是 schema error。import 发现的 script/notebook 保持为 non-executable
attachment；执行前必须另行注册为 Capability Provider、Harness driver 或 trusted build-time
importer。

外部 source 由 repository、full commit、subpath、manifest/body/reference full SHA-256、
license 和 importer version 固定。branch、tag 与`latest`不能成为 runtime source。正文中的
tool 名只记录为 non-authoritative hint。无 prompt 的固定 Knowledge Binder 在 mint epoch
lock 前检查 verified status、applicability、dependency、conflict、authority ceiling、
forbidden capability 与 evaluation obligation。

### 外部 import adapter

`ari.knowledge.external_importer`提供四条只产生 candidate 的 admin path：

- exact Git repository commit 与 subtree；
- 对明确配置 scientific Skill source 使用相同 Git adapter；
- 支持 required YAML frontmatter 及可选`references/`、`scripts/`、`assets/`的
  [Open Agent Skills specification](https://openagentskills.dev/docs/specification)；
- 由独立 ARI 侧`ToolUniverseKnowledgeCollectionProfileV1`描述的 ToolUniverse Knowledge
  collection。

Git import 初始化临时 bare object database，只 fetch 并验证调用者提供的 full commit，再以
`ls-tree`/`cat-file`读取 regular blob。它不 checkout、不调用 source hook、不读取 branch/tag、
不执行 imported script。symlink、submodule、special entry、path escape、不安全 remote-helper
scheme 以及 URL 内 credential 均被拒绝。material 记录 repository、commit、subtree、tree
snapshot、原始`SKILL.md`、生成 body/manifest/reference、attachment、importer 与独立 admin
profile digest。

Open Agent Skills frontmatter 仅为 source metadata。`allowed-tools`和`compatibility`是
non-authoritative hint；`scripts/`、notebook 与 asset 是`authority: none`的 digest-bound
attachment。Capability requirement、evaluation obligation、authority ceiling 与 forbidden
capability 只能来自不可信 source 外部的`KnowledgeSkillImportProfileV1`。
`body_normalization: strict`要求 upstream body 包含 ARI 必需 section。经审核的
`ari-wrapper-v1`会引用每一行 upstream 内容，并放入含 precondition、authority 边界、failure
semantics、expected artifact、scientific caution 与 evaluation obligation 的固定 ARI 正文。
`curation_notes`也只来自另行 hash 的 admin profile。两种模式都不授予执行权限，所有 import
都以`candidate`进入。

`ari.knowledge-import-material/v1`是 self-contained material，保存 normalized body、manifest、
reference、attachment 与 source executable bit、tool hint、外部 provenance 和自身 full
SHA-256。checked-in catalog 可直接引用该 material，不再创建第二份 manifest/body 真相源。
catalog load 离线验证完整 material，不重新 fetch repository。

```bash
ari knowledge import \
  --source-kind open-agent-skills \
  --repository https://github.com/example/scientific-skills.git \
  --commit 0123456789abcdef0123456789abcdef01234567 \
  --subpath skills/reproduction-method \
  --profile reviewed-import-profile.yaml \
  --output candidate-import-material.json
```

### 已注册 Intel performance candidate

catalog 将`intel/intel-performance-skills`固定在 full commit
`e9d0b6410fb1ad7a50fb81e0868fd23ae886882c`，并把三个 Knowledge identity 分别注册为
candidate。

| Knowledge ID | upstream subtree | 边界 |
|---|---|---|
| `intel.performance-patterns` | `skills/performance-patterns` | x86 C/C++ 优化知识；bundled C 与 executable test asset 是 authority-none attachment |
| `intel.linux-perf` | `skills/linux-perf` | 要求 bound hardware-counter capability 的 profiling 知识；禁止`sudo`及 host sysctl 修改 |
| `intel.phoronix-test-suite` | `skills/phoronix-test-suite` | 用于预先 pinned PTS input 的 workflow；禁止 runtime refresh/download/install、home 及`/var/lib` write |

三者既不是 Provider 也不是 Harness，不会激活`perf`、Phoronix、compiler、shell 或 credential；
实际执行仅由 Capability Binding Lock 解析。Phoronix score 不是 Harness Attestation。candidate
三者现已具备实测的 clean-task 与 portability evidence，通过全部十六个 gate，并依据已
记录的 approval 晋升为 `verified`，因此固定 Knowledge Binder 可以 admit 它们。三个 HPC 优化 Skill 走了同样的路径，因此 catalog 中的每个条目现在都依据已记录的
approval 处于 verified。多线程 clean task 起初低于自身的串行 baseline：
型化 Provider 在 batch step 中执行 payload，而 batch step 会继承整个节点的 affinity
mask；Provider 现在将单 task 的 payload 作为受绑定的 job step 运行。

### eligibility 不等于 promotion

通过 gate 只代表 eligible。catalog 中的 `status: verified` 还需要
`ari.knowledge-skill-promotion-approval/v1`，并绑定到精确的 `skill_ref`（manifest 与 body
字节）以及经审阅的 registration evidence。catalog 加载会拒绝注册决定不是
`eligible-for-verified` 的 verified 条目、缺少 approval 的条目、以及指向其他字节的
approval；同样拒绝挂在无人晋升条目上的 approval。修改 manifest、body 或 evidence 会使
approval 失效，而不会被悄悄沿用。

promotion 只有一个写入者：`scripts/promote_knowledge_skill.py`。它拒绝决定不是
`eligible-for-verified` 的 Skill，写明批准者与依据，并同时记录 approval 与
append-only 的 `ari.knowledge-skill-status-transition/v1`。
`GovernedKnowledgeSkillRegistry.transition` 同样拒绝缺少匹配 approval 的晋升，
因此台账与 catalog 不会在“谁晋升了什么”上产生分歧。

portability 通过撤下在任 Provider、并以保留的替身身份重新提供完全相同的 capability 契约
来判定（`method: synthetic-substitution`），它询问的是该 Skill 指向 capability 还是指向某个
Provider。这严格弱于执行第二个实现，绝不称之为 cross-Provider portability。原有的
`method: two-providers` 规则保持可用且未改动。

ToolUniverse collection profile 可包含 Knowledge subpath 与 admin profile，但没有 Provider
ID、launcher、tool、credential 或 transport field。所得 identity 使用
`ari://knowledge-source/tooluniverse/...` namespace，并输出`provider_activated: false`；它与
ToolUniverse MCP Provider 及 nested Provider lock 相互独立。

## Capability ontology 与 Provider binding

`CapabilityContractV1`固定 semantic input/output、side effect、determinism、context、
permission、resource、version 和 compatibility。Provider registration 检查 live input/output
schema 与该契约的兼容性；相同文字 label 不足以证明语义兼容。

`compatibility_rules`是一个封闭词表。它原本是一个 free-form 字符串 tuple——被 digest 绑定、
被写进文档，却没有任何代码读它，因此 ontology 里每一个 rule 名字都是惰性的。现在，reviewed
表之外的名字一律被拒绝，且每个名字都说明自己在哪里被检查：`measurement-envelope-v1`在 core，
五个在供给该 capability 的 Provider——其中四个对着自己的 golden 与 replay evidence，
`exclusive-allocation-witness-v1`由它提交的 job 从 allocation 内部见证——其余显式为
`unenforced`。

`json-schema-structural-conformance`被**废止**而非实现，它与留下的三个`unenforced`之间的
区别，正是保留后者的理由。那三个各自指名一种可以据以判定 Provider 的*payload 形状*——
envelope、artifact、async handle——只是尚未写。被废止的那个指名的是「tool 的 schema 与
capability 侧结构之间的关系」，而没有任何契约陈述过该结构：十三个契约的`semantic_inputs`
与`semantic_outputs`全为空，这两个字段连同`SemanticFieldV1`在整个仓库里没有任何读者——这是
一个缺了实参的谓词。它还挂在 13 个契约中的 13 个上，而对一切都为真的性质不区分任何东西。
该 rule 与那片孤立的 semantic surface 一并移除，三个契约现在正当地声明零条 compatibility
rule：这是真话，而不是占位符。

人们归给该 rule 的东西早已在别处强制：构建 provision 时的 side-effect class 相等与
`required_permissions`覆盖、binder 的`provider_lock_mismatch`所保证的整个 lock 的 identity，
以及把 tool 的 live `input_schema`与`output_schema`原样折入的 provision digest——schema 一变，
provision 就变，与是否有人为它写过 rule 无关。

与之并列还有另一个缺口，对承载 capability 的 tool 而言它已经被补上。以前每个 Provider tool
发布的 MCP `outputSchema`都是**空**的，于是每条 provision 的`output_schema_digest`都是`{}`
的 digest，对谁都检测不出 drift。当时被分类的九个 tool——`ari-skill-coding`五个、
`ari-skill-hpc`四个——现在都声明了一份，而每份声明的 schema 都是该 tool 成功形状与它自身
失败形状的`anyOf`: 只描述成功，会把一次真实的执行失败变成 output 校验错误，并丢掉那条说明
出了什么事的 message；而`oneOf`会拒绝一个正当地同时属于两者的 payload，例如一次超时的
执行——它既是完整结果又携带错误。声明 schema 同时使 handler 有义务在 text 之外返回
structured content，因为 library 会拿`structuredContent`去校验所声明的内容。声明 schema
与被分类进某个 capability 仍是两件事: `counter_support`根本没有被分类却声明了一份，而 web
Provider 的四个 retrieval tool 是后来才被分类的、并未声明，因此它们的
`output_schema_digest`至今仍是`{}`的 digest。

`measurement-envelope-v1`说的是：一次测量只有连同它被取得时的条件才可解释，因此声称该 rule
的契约必须声明作为这些条件的`nondeterminism_fields`。一份声称该 rule 却不指名任何条件的
契约会在 load 时被拒绝——它根本没有在陈述一个 envelope。

只有`declared_capability_refs_by_tool`会产生 provision。skill.yaml 一侧的`capability_ref`
作为`declared_capability_ref`被携带，但不参与 bind。因此不在该表中的 tool，无论自称什么
capability，都不会成为某个 Capability requirement 的解决对象——在 legacy/audit mode 下这
不意味着它不能被调用，只意味着它不是 bind 的候选；在 enforce mode 下，未被 bind 的 tool
会以`unbound_tool`被拒绝。

一次 run 的 requirement 来自两个 source。被 admit 的 Knowledge Skill 声明其指令所预设的
东西，而`capability_binding.required_capability_refs`让 operator 声明这次 run 自己的任务
需要什么。后者之所以存在，是因为先前只有前者: 一件没有任何 Knowledge Skill 恰好提到的
domain instrument，可以拥有契约、经审阅的供给方、已 admit 的 evidence 和已验证的调用路径，
却始终不会被*要求*，因此永远不会被 bind。该声明是 config，绝非模型输出；不在经审阅
ontology 中的 ref 会被拒绝而不是被忽略；决定 side-effect ceiling、resource 与 environment
的是契约而不是该声明；同一 capability 上 Knowledge Skill 的 requirement 也绝不会被它取代。
指名了 required ref 却把 binding 留在`legacy` mode 会被拒绝，否则该 requirement 会被悄悄
丢弃。`optional_capability_refs`在有供给时 bind，且永远不会让一次 run 失败。

无 prompt 的 Capability Binder 只考虑现有 Provider lock 中 verified Provider 的 exact
capability ref 与 contract digest。它按 role、phase、call context、side-effect ceiling、
credential scope、environment、disabled tool 与 live schema identity 过滤，再按 exactness、
verified status、explicit pin、context fit、最小 side effect、determinism、reproducibility、
feasibility、resource cost、lexicographic `tool_ref`与`subject_tool_ref`确定排序。缺少
coverage 返回`unsatisfied`，不存在 substring、bare-name、LLM 或 network fallback。

enforce mode 下 Agent 可见集合严格等于：

```text
Provider Lock tools
intersect Capability Binding Lock
intersect role authority
intersect phase policy
intersect call context
minus user-disabled tools
```

### brokered leaf 与 composite provision

经由 broker 到达的 domain instrument 不是 ARI Provider，也从不出现在 Provider Lock 中，
因此 Binder 无法直接 authorize 它。`ari.providers.brokered`补上这一半：Provider catalog
entry 可携带一个`brokered` block，内含 federated catalog lock、dispatch tool，以及从 leaf
`tool_ref`到 ARI `capability_ref`的 reviewed table。每个 reviewed leaf 成为一条
`CapabilityProvisionV1`，其`tool_ref`与`dispatch_tool_ref`是 broker 的 dispatch
tool——run lock 中唯一存在的 ref——而`subject_tool_ref`是该 leaf。`subject_argument`给出
承载该 leaf 的 dispatch 参数名；一次真实的 dispatch 调用若在参数中指向本次 run 未曾 bind 的
leaf，则被拒绝：所有 composite 在构造上共享同一个 dispatch `tool_ref`，缺少这一比对时，
单个 reviewed leaf 的 authorization 就会带上 federated catalog 中的每一个 leaf。可见性检查
不提供参数，lifecycle ref 承载的是 job handle 而非 leaf，两者都不受 subject gate 约束。
`nested_source_lock_digests`承载 leaf 的 source digest，federated lock 自身的
`catalog_digest`并入该 Provider 的`nested_source_lock_digests`；因此在 broker 背后替换
leaf 会改变 binding request 所 pin 的 Provider catalog snapshot。

site 用`ARI_TOOL_REGISTRY_LOCK`选择 federated lock，ARI 读取同一个变量。这不是便利设施：
若 ARI 在 project packaged lock 而 broker 却向 site lock dispatch，则每一条 composite
provision 描述的都是并未被调用的 leaf。packaged 的`CATALOG.lock`为空是刻意的——materialize
后的 lock 记录绝对本地路径，无法提交——因此仓库里只保留 reviewed leaf→capability 表，它所指
向的 lock 留在 site。

一条 provision 只携带那些取值确实存在的 credential scope。已声明却缺席的 credential 不授予
任何权限——子进程只由存在的取值构建，call context 也按同样方式过滤——所以携带被声明的整个
集合，曾让一个多领域 Provider 的每条 provision 都索取它可能用到的每一项 scope: 经 broker
bind 一个 EDA tool，需要授予一份根本没有设置的 IBM Quantum credential。存在性在 lock 时被
观测并冻结进 Provider Lock，因此后来才出现的 token 改变的是 lock，而不是溜过去。

descriptor 声明异步 lifecycle 的 leaf，由 dispatch tool 提交、由另外的 tool 收取。它们不是
独立的 capability——轮询一个你已被授权提交的 job 并不增加 authority——但它们是不同的
tool_ref，因此 composite 以`lifecycle_tool_refs`携带它们，authorization view 在同一 binding、
phase 与 call context 下放行。否则一个已 bind 的异步 capability 会启动它无权收取结果的工作。
同步 leaf 不获得 lifecycle 面。

有四项性质是被强制检查而非假定的：

- federated lock 会被重新认证。ARI 以 broker 自身的 canonicalization 重算
  `catalog_digest`，并重新检查每个 tool 恰有一条 admission、id 唯一、policy digest 单一。
  被编辑过的 lock 被拒绝，而不是被 project。
- authority 是两跳的 envelope。side-effect class 取 leaf 与 dispatch tool 声明中较重者；
  contract 的 required permission 必须由两者共同授予——broker 因为 runtime 对它设 gate，
  leaf 因为实际工作由它完成。
- mapping 从不属于 broker。descriptor 自身的`capability_ref`属于 broker 的 namespace，
  仅作为`declared_capability_ref`记录以便发现 drift，绝不当作 mapping 读取。决定权只在
  已签入的 reviewed table。
- reproducibility 受 admission 封顶。仅达到`callable`的 leaf 无论 determinism 字段声称
  什么都记为`unknown`；`reproducible`最高`bounded`，`scientifically_admitted`最高
  `exact`。低于自身`required_level`的 leaf、被 quarantine 的 leaf，以及 run lock 中
  不存在的 dispatch tool，一律拒绝。所选 site lock 中不存在的 reviewed leaf 则是跳过而
  非拒绝：所选 lock 可以有意窄于 reviewed table，缺席的 leaf 不授予任何权限，而没有任何
  leaf 能供给的 required capability 会在 binder 处保持可见的`unsatisfied`。

### environment evidence 与 Provider substitution

`ari.capability_binding.environment`在 binding 前记录 substrate 观测事实。它以 bounded、
shell-free probe 检查 SLURM partition、local NVIDIA device 和 CUDA compiler。当
`resources.gpus > 0`、SLURM ready 且看不到 local device 时，才通过`srun`执行一次 bounded
compute-node `nvidia-smi` query。config 声明不能虚构 resource。

container runtime 同样以执行来判定。`shutil.which`找到二进制并不是关键事实——runtime 可能
已安装却因缺少 user namespace 而拒绝启动——而且 Singularity 的两个 fork 在不同 site 以不同
名字安装。因此实际运行`--version`，并按应答者的名字记录。executable 的路径刻意不保留：它依
赖 site，而 binding 并不需要它。

把观测到的事实变成 ontology 的 resource class 是另一件事，发生在
`ari-core/config/capabilities/resource_derivations.yaml`。每一行声明它 emit 什么、必须已存在什么，
以及理由；没有 rationale 的行在 load 时被拒绝——没有理由的 derivation 就是 alias，而 alias
正是这张表存在的目的所要防止的。行被应用到 fixpoint，因此一行可以消费另一行 emit 的结果；
这里无法凭空造出 prober 未观测到的事实，而触发过的行记录在`metadata.derived_from_review`
中——依赖 derived resource class 的 binding 可以一路审计到允许它的那句话。随包的表记录了
Apptainer 与 SingularityCE 都执行 SIF、而 podman 与 docker 都不执行，并由 CPU 加 SIF
runtime 推导出`eda-cpu`。

向外的可达性是从路由表观测的，而不是靠联系任何人。一条 default route 是 kernel 在说它有
一条离开本 host 的路径：它必要而不充分——proxy 或防火墙仍可能拒绝该调用——这与`sinfo`能
应答给 scheduler 的地位相同。一条 default 目的地的行只有在它是 up、不是 reject route、
且不在 loopback 上时才算数：kernel 在每台 host 上都带着一条不可达的`::/0`，所以只匹配
目的地会把一台 air-gapped 机器读成有出口。更强的证据——解析一个名字或建立一次连接——
则是为了描述我们自己的 substrate 而向别人的服务发出一次向外请求。在 air-gapped node 上
没有 route，retrieval capability 保持未获供给。

SLURM GPU visibility 与 scheduler authority 不同。在没有 advertised GPU GRES 的 node 上
观察到 device 时，记录保留在`metadata.slurm_gpu`并增加
`gpu-observed-on-slurm-node`，但不增加`gpu` resource type。只有观察到 GRES，或 operator
在`resources`中 pin 一份 exclusive-node inventory 时才可调度 ——
`gpu_allocation_mode: exclusive-node-inventory`、`exclusive: true`、一个`gpu_node`，
以及必须与观察到的 inventory 一致的 full-SHA `gpu_inventory_digest`；不一致的 pin 记为
`exclusive-node-inventory-mismatch`，仍不可调度。device UUID/model/
compute capability/memory/driver 和 output digest 都进入 frozen environment identity；resume
不会重新 probe 并替换。加载持久化数据时`EnvironmentSnapshotV1`重算 canonical full-SHA
identity，添加虚假 resource 或修改事实会使 admission 失效。

ToolUniverse Capability authority 同样使用 exact mapping。经审核 category profile 可将 exact
leaf 名映射到 canonical `capability_ref`、equivalence key 和 result normalizer；substring 与
Provider description 不参与。首个 projection 把`PubMed_search_articles`映射为
`ari.literature.search/v1`，并将 live response 转换为含逐条 source identity 与 full payload
digest 的`ari.retrieval-result/v1`。production sync 要求 reviewed wheel/package tree、exact
upstream dependency-lock bytes、closed installed environment 与 live compact-MCP schema parity。

`probe_provider_substitution`禁用 primary Provider 的 exact locked tool，并运行 production Binder
两次。digest-bound report 将 binding determinism/status 与可选 live operation observation 分开。
因此，即使两个 Provider 返回相同 semantic result，只要其中一个是 candidate、drifted 或其他
inadmissible 状态，substitution 仍为 binding `unsatisfied`。

## Verification、Harness 与 Attestation

Harness kind 是封闭且不可互换的：

- `benchmark`评估固定 benchmark subject，不能验证任意 external target；
- `artifact_verifier`针对声明 target kind/property 验证生成 program/library；
- `reproduction`评估 paper/repository reproduction package；
- `claim_verifier`检查 claim/evidence 一致性，但不证明已记录计算本身正确。

`VerificationContractV1`是 mint-once、canonical JSON、full-SHA bound。Knowledge obligation
只能增加 property/method，不能删除 requirement、弱化`certify -> validate -> screen`、放宽
tolerance 或指定 authoritative Harness。固定 Resolver 执行 exact compatibility filter 与
deterministic set cover。baseline lock immutable；revision 只能在 epoch 边界增加 Harness 或
强化 property。

Fixed Verifier 接收 immutable target snapshot，只执行 lock 中的 driver、oracle、dataset 与
container。它生成 full-SHA `HarnessAttestationV1`，绑定 run/node/epoch、contract、Knowledge
use、Provider/Binding/Harness lock、source asset、target digest、execution identity、逐 property
verdict 与 evidence artifact。verdict 为`pass`、`fail`、`inconclusive`、
`infrastructure_error`或`tampered`。Provider success 不是 Attestation；普通 candidate failure
本身也不是 constitutional violation。

启动哪一个 verifier 进程，由 manifest 所 pin 的 driver revision 决定，而不由 Harness id 决定。
已注册的 revision 有三个——`ari.assurance.native-hpc/v1`、
`ari.assurance.problem-correctness/v1`和`ari.assurance.native-perf/v1`——每一个都组装自己的
argv。以 problem 为轴的两个分支，从 manifest 自身的`oracle`/`dataset` pin 与 target 声明取得
问题与 candidate，而不是从 id 中截取的文本；只有 native-HPC 分支仍然从 id 读出 family 名
(`hpc/gemm-correctness`→`gemm`)，那是唯一一处该截取能得到已注册 family 的地方。没有任何分支指名的 revision 会被拒绝为
无法 launch，这与"验证失败"是不同的结论：没有这一拒绝，request 会启动错误的 verifier，
不匹配将在更下一层表现为 infrastructure outage。evidence reference 的 media type 出于同样
理由取自声明的 target kind，因此 C submission 不会被记为 shared library。

correctness requirement 携带该 run 的 candidate 实际所是的 artifact kind。property vocabulary
对每个 property 只陈述一个 target kind，而 Resolver 在查看 property 之前就会丢弃 kind 不在
manifest `target_kinds` 中的 atom——因此验证另一种 kind 的 Harness 即使被 registration 与
promote，也永远不会被选中。当一次 run 用`ARI_PROBLEM`指名 pinned problem 时，admission 推导出
该 problem 的 artifact kind 并传入 Verification Contract，其中只有 correctness property 接受
它：若 problem 声明的 entry point 是 family ABI 的 exported symbol 之一，则取该 ABI 自己的
target kind，否则为`benchmark-submission`。不指名 problem、或指名了无法 load 的 problem 的
run 不传任何值，每条 requirement 的标记与此前完全相同。node 侧的 target 声明从同一个函数
推导 kind，因此 resolution 与 declaration 不会就"验证了什么"产生分歧。

native `hpc/gemm-correctness`、`hpc/spmm-correctness`和`hpc/stencil-correctness`包含
deterministic generated case、独立 reference、dtype/accumulation-aware error model、
metamorphic/shape/boundary/repeat coverage 与 negative control。promote 为 checked-in verified
catalog entry 是 release admission 操作，要求 committed source revision、immutable container、
license review、reference pass、negative-control fail 与 retained registration report。
registration 还会把 manifest 与它所 pin 的 driver 对照：`result_schema_conformance`只有在
`expected_result_schema`正是该 driver 发出的 report type、且`expected_result_schema_digest`
正是 ARI 为该 type 所提供的 schema 文件的 byte digest 时才通过。两者不齐全的 evidence 不会
跳过比较，而是 gate 失败；schema 在 pin 之下发生 drift 的 pin 会被拒绝而不是就地更正，因为
pin 记录的是被 registration 的内容，只有 re-registration 才可以移动它。

这三者各是一个 correctness family，在`ari.assurance.native_hpc_family`中一次性自我注册，
并提供三样东西：`verify`（hidden case 与判定它们的 oracle）、`reference`（独立实现，也是
parity probe 的 clean control）以及`call_shared_library`（candidate 被调用时经过的 ctypes
ABI）。可验证 kernel 的集合过去写在五处——一个`Literal`、facade 的 dispatch dict、parity
probe 的 reference table、ABI dispatch dict 和两个 argparse `choices` tuple——因此只加入其中
四处的 family 仍可被 dispatch、被 score、被 attest，而 probe 从未触及它，probe 却依旧报告
`passed`。现在每个 dispatch site 都向 registry 查询，重复注册同名会被拒绝，import 顺序
无法决定由哪个 oracle 判定一次 run。registry 位于 native driver digest 之内，因为它决定
由哪个 oracle 判定一次 run；若在其外，judging oracle 可在 attestation 依然通过验证的情况下
被替换。digest 现在还会在其中某个 verifier 文件缺失时报错，而不是让该文件悄悄退出。以上
并不使 correctness family 像 pinned problem 那样自由：problem 是一个 data 目录，而 family
持有 oracle。新增一个仍是需要照常 review 的 ARI 变更，因为 caller 能提供的 oracle 就是
caller 能削弱的 oracle。改变的只是集合按 family 声明一次，而不再是按集合声明五次。

cost 是真实的，而且已被支付而非被吸收：driver digest 曾改变，所以三者一度都以
`native Harness driver bytes drifted`拒绝运行。它们的 manifest 没有被简单地重新 pin，因为
signature 只覆盖被签署的内容，仅重新 pin 会让三份 human-maintainer attestation 描述无人
批准的 code。它们改为被重新 registration——在 clean worktree 上各跑三次 parity probe，
15/15 gate，`eligible-for-verified`，registration report、evidence bundle 与 maintainer
approval 全部重新签发——这些 pin 现在指向真实存在的 driver。

checked-in catalog 已不止这三者。它还包含一个针对 pinned problem 的 correctness Harness——
它以 problem 自身的 C contract 而非 family ABI 来验证 candidate，拒绝规范化描述了与 manifest
所 pin 不同的 problem、case set 或 digest 的 result，并且其 harness 层 verdict 取自 request
实际声明的 property，而不是 report 合并的两个 property——以及一个 performance Harness。

performance verdict 是对照该次测量实际显示的 spread 来读的。candidate 必须达到的比值是
`DEFAULT_REGRESSION_THRESHOLD`，只存在于一处，由 worker、parity probe 与 measurement 同样
取用：governed path 不传 threshold，因此一个用来读出 verdict 的数值不能是各调用点各自的
default。不足是该 threshold 减去 median 比值，并对照这次 run 实际拥有的 band 来读：band 即
repetition 自身的 max 减 min，或者当没有可测 spread 时（典型是单次 repetition）取
median×`MAX_TRUSTED_SPREAD`（这台仪器被读取的最大 spread）。超出该 band 的不足是`fail`，
而且这一判定排在最前，因此足够低于 threshold 的 candidate 即使只有单次 repetition、即使在
noisy 到什么都分辨不了的机器上也会被拒——slow 的 negative control 之所以持续失败正是如此。
在此之下，宽于`MAX_TRUSTED_SPREAD`的实测 spread，无论 median 落在 threshold 哪一侧都是
`inconclusive`：noise 扩大的是"未能分辨"，而绝不是"pass"；来自单次 repetition 的剩余不足
同样是`inconclusive`。clean control 的 timed duration 与其 spread 并列记录，因为 spread 是相对
duration 的比例，而短到承载不了仪器自身 overhead 的 case，与一台 noisy 的机器是不同的结论。

未被取得的测量报告为 absent，而不是 zero。launch 未完成的 case、或 oracle 给出非有限
residual 的 case 不携带 residual ratio；report 的 aggregate 只在每个 case 都给出数值时才存在：
仅对给出答案的那些 case 取最大值，是 evidence 不支持的 bound，而且它就印在读者会拿来比较的
limit 旁边。correctness report 还会绑定 candidate 自身的 digest，否则达成相同 verdict 的不同
candidate 会产生 byte-identical 的 report，因而只有一个 report digest。report 从 launch 的
sandbox 中保留的是一个 allowlist——untrusted candidate 是否被隔离、由什么隔离、以及它未覆盖
什么——而绝不包含 per-run 的 writable root：那是一个 host 文件系统路径，并且会让 report
digest 每次 run 都不同。

Inspect、Harbor、KernelBench/ComputeEval/scBench 和 PaperBench adapter 不 fork upstream
framework。其 driver 验证 pinned official route 并规范化 strict result envelope。没有
digest-bound official runner parity report 时，registration 为`not_available`且 entry 保持
`candidate`；不使用缩小或 local fallback。

`ExternalHarnessParityReportV1`是 authoritative parity input。`passed` report 必须绑定 Harness
Manifest、source revision、dataset、container 与 driver，保留 official invocation/result 和
normalized result digest，通过 reference，并使错误 submission negative control 失败，同时证明
result-schema parity。API import、CLI presence 或 scorer unit compatibility 只能出现在
`non_authoritative_checks`。`passed` schema 也拒绝缩短 source revision 与全零 digest
placeholder。`ari-skill-paper-re/scripts/verify_paperbench_upstream.py`诊断 credential-free
upstream API 与 deterministic aggregation，但在 official rollout、reproduction、judge route
及全部 external pin 完整前明确输出`official_runner_status: not_available`。

### verification resource accounting

构造并重新验证 valid Attestation 后，RQGM Assurance bridge 在`cost_trace.jsonl`记录一条
verifier execution，绑定 Harness、execution identity/attempt、Attestation、node、epoch、tier、
status、backend、executor wall interval 及 declared CPU/accelerator/memory allocation。derived
resource 值是 allocation × observed wall interval，而不是 utilization sample。Task 20 分别报告
`screen`、`validate`、`certify`的总量与每个 valid node 值。只有存在 authoritative charge/price
时才记录 dollar 值；否则`cost_status: unpriced`防止把未知费用显示为免费。

## mode 与兼容性

```yaml
knowledge:
  mode: off       # off | audit | enforce
capability_binding:
  mode: legacy    # legacy | audit | enforce
assurance:
  mode: off       # off | audit | enforce
```

default 保持`simple_bfts`。三项均为 default 时，run path 不 import 新 domain package，也不产生
catalog snapshot、lock、checkpoint field、metric、prompt byte 或 visible-tool 差异。明确的
Knowledge/capability/verification requirement 与 off/legacy mode 冲突时，run admission 失败。
`ari_rqgm` enforce 要求所有对应 immutable snapshot 与 lock。

## surface 与管理

人类 diagnostic command 位于`ari knowledge`、`ari provider`、`ari harness`。dashboard
Governance workspace 将三类 catalog card 及其 lock/provenance 分开显示。
`ari-skill-knowledge`和`ari-skill-harness`是 default-off 的 query/request Capability Provider；
其 MCP request 不具 authority，不能 register、promote、revoke、rewrite lock、替换 oracle、
改变 tolerance 或 force pass。

catalog lifecycle 变化需要 reviewed repository change 或 authenticated human admin path。
revocation append taint/status history，绝不改写旧 lock、Attestation 或 provenance。

## 已记录的验证 checkpoint

以下是带日期的观测记录，不是当前 status。之所以保留，是因为后续关于 environment、cost
或 promotion 的任何主张都必须能对照真正产出的 artifact 来核对，而 digest 是该 artifact
唯一的 identity。这里的 digest 指的是记录在所标日期时的状态，不是对当前 catalog 的断言。

### 观测到的外部 cell（2026-08-04）

冻结的 environment snapshot
`sha256:e0fdcf428bf8b2168dfc06e14faad4ceb2197b7269b90e843b699aa818d92cbb`
记录了可用的 CPU SLURM、CUDA toolkit 12.4，以及在匿名 compute node 上可见的四个 V100
device。由于 scheduler 未广告 GPU GRES，这些 device 仅为 observation-only：不产生`gpu`
resource type，且在没有明确的 operator 调度决定前，accelerator campaign 保持
`not_available`。这正是「environment evidence 与 Provider substitution」所述的规则——
device 可见性不等于 scheduler 权限——以实测而非论证给出。

一个 batch job 运行了 native verifier 的三个 reference/negative-control family：3 项
pass，6 项未选中的 test 完成。GNU time 观测到 wall 1.61 秒、user CPU 0.89 秒、system CPU
0.13 秒、最大 RSS 55,537,664 字节。该 cost 观测绑定到 digest
`sha256:3c451a31416880fd32a71c6e3fefa4d1aba9663f6052f27e84d2aec54fa0839d`。

该观测被刻意认定**不是**权威 cost trace，理由与测量质量无关。观测当时，production
Harness catalog 没有 verified 的 pin 定 container，该 run 也未签发 Attestation。production
cost accounting 只在 valid Attestation 构造并重新验证之后才开始：「verification resource
accounting」所述的记录来自 Attestation，而不是来自一次计时运行。在给出 scheduler 或
cloud 费用之前，dollar 值保持`unpriced`。

ToolUniverse/Web 的 live operation substitution 在归一化 result contract 层面成功，但由于
精确冻结的 upstream environment 不可 promote，ToolUniverse binding 仍为`unsatisfied`。
PaperBench compatibility 通过，而 official-runner parity 仍为`not_available`。这些是实测
到的缺失 cell：既不是 pass，也不是未决的设计选择。

### ToolUniverse promotion 的解决（2026-08-05）

2026-08-04 的结果作为对 upstream ToolUniverse `1.3.1`的不可变观测保留，既未改写也未重新
贴标签。ARI 转而 mint 了独立 identity 的 metadata-only Provider artifact
`tooluniverse-pubmed@1.3.1+ari.1`。其已 check-in 的 registration evidence、全部十五项
Provider gate 以及明确的 human-maintainer 批准，产出 verified lock
`sha256:c85e73726b1182c3fe88b682a8bcd0e0d7a57713f7ecb1818056886eaa5442bf`
与 promotion approval
`sha256:9317c4ff7e15f488f758fc253b9afd96345abd6d3730405f5669c93a6eabc608`。
该 lock 只允许把匿名`PubMed_search_articles`作为`ari.literature.search/v1`，且无
credential scope；scope 扩张、evidence 改动、schema drift 与 revoked status 均 fail closed。

promotion 并未把先前的 diagnostic 变成 pass。新的 campaign 必须使用由该 verified artifact
导出的 run 专属`CATALOG.lock`、`SKILLS.lock`、environment identity 与 Capability Binding
Lock。一个 run 专属的单 leaf `CATALOG.lock` 已生成并达到`callable`，其匿名 broker
invocation 返回了一条 credential scope 列表为空的归一化`ari.retrieval-result/v1`记录。
在正式 maintainer promotion 之后于封闭 environment 重新同步，得到 verified 的单 leaf
catalog digest
`sha256:73e1225dc30b4cfc735858bad4615e08da6723a0f0ced6dd560897d7db3551ff`。

这三个 digest 都属于该 checkpoint，且此后至少被 supersede 过一次。2026-08-07 的
portability 再 promotion 把 promote 方 host 的 install path 从 leaf identity 中移除，因此
lock、approval 与 catalog digest 都改变，而被允许的 scope 不变；当前生效的 lock 与
approval 位于已 check-in 的 bundle
`ari-skill-tool-registry/providers/tooluniverse/1.3.1+ari.1/`
之下，而单 leaf catalog 是 environment 专属的 evidence，不是 repository default。被
supersede 的 digest 作为它所记录之物的 identity 依然有效，resume 期间也绝不改写既有的
catalog 或 lock。

## 诚实的限制

Knowledge 质量和 capability ontology 需要人工 curation。同一 capability 的多个 Provider
可能行为不同。external service、model 与 hardware identity 的完整程度受 substrate 暴露信息
限制。static inspection 无法证明所有 Provider description 都无害。Harness pass 只适用于声明
property/scope；只有 formal-verifier Harness 能证明 formal specification。nondeterminism 与缺失
external pin 保留在 provenance。infrastructure error 绝不 fail-open。RQGM 不创造 Verifier 的
科学结论，而是治理忽略、压制或歪曲固定结果的 actor。

composite provision 路径已端到端**完成调用**。一个真实 materialize 的 OpenROAD leaf
（`scientifically_admitted`的 descriptor）在 enforce mode 下被 bind，经 broker 的`invoke`
dispatch，通过已 bind 的 lifecycle tool 轮询至完成，并返回落在其 promotion golden 区间内的
CTS 与 routing metric：DRC error 0、wire length 3603 um、via 3361，在 pin 定的 SIF 内约 50 秒。

抵达这一步需要三处修复，且每一处都使该路径不可用而非仅仅不便。broker 的 tool schema 设了
`additionalProperties: false`却未声明`ari_context`，于是 transport 注入的 call context 被拒绝，
任何 context-gated 的 broker tool 都无法被调用。result normalizer 把`error`键的**存在**当作
失败，于是任何返回`ari.result-envelope/v1`——ARI 自己定义的 schema——的 Provider，其成功都被
报告为 message 为`null`的 tool error。而已 bind 的异步 capability 对自己的 lifecycle tool 没有
authority，因此能启动工作却无法收取。

挡住`ari.literature.search/v1`的不是 envelope 规则，而是它自己的契约。它声明`read-only`，
而 reviewed 的 PubMed leaf 与 broker 的`invoke`都声明`stateful`，因此谁都无法供给它。错的
是契约：一次被 admit 的 retrieval 会写下使其成为 evidence 的记录——cassette 与
content-addressed payload 进入该 run 的 EAR——而 ladder 评定一次调用，看的是它对这个
substrate 做了什么，而不是它是否改动了远端 index。它现在是`workspace-write`，reviewed 的
PubMed leaf 据此构成 composite。注册这一 mapping 需要一个包含该 leaf 的 site lock；reviewed
表跨 site 的所有 source 指名 leaf，因此同时需要 EDA 与 retrieval 的 site 会把两者
materialize 进同一个 lock，而不是每个 domain 一个。

`ari.quantum.sample.local-ideal/v1`已获供给。其 promote 后的 local-Aer bundle 曾被
materialize 却从未注册，于是从该 bundle 自身的 materialized profile 组出一个 site source
——没有任何臆造，错误的值会让 catalog build 失败——该 leaf 现在可以 bind 并运行：seed 过的
Bell 电路 4096 shot 返回`{"00": 2046, "11": 2050}`且无其他结果，落在 promotion golden 的
区间内，约 10 秒。这就是同一个 lock 同时持有两个 source 时，bridge 在第二个 domain、第二种
adapter 上的运转。

其`environment_requirements: [cpu]`是同一类 category error，已更正。`quantum-simulator`
现在有一条仅从`cpu`出发的 derivation 行。在没有任何东西供给该 capability 期间，这一行是被
刻意压住的——一条在任何 substrate 上都触发、把未获供给的 capability 显示为已解决的行，比
没有这一行更糟——如今它只是准确：一次 seed 过的双量子比特 CPU statevector pass 只需要 CPU。
为它划定边界的是 catalog 校验的 digest-pin artifact，那是任何 derivation 都看不见的；
substrate 声明不是 availability 声明。

CUDA 契约的`slurm` requirement 是同一类 category error，现在写作`slurm-controller`；
`gpu-slurm`获得了一条来自 prober 分别 emit 的两半的 derivation。在真实 GPU node 上运行
prober 又关掉了两处，并发现了一个 login node 无法暴露的缺陷。

`cuda-12.9`与`nvidia-sm70`是同一错误再深一层，也已从契约中移除。toolkit 发行版与 device
世代是关于该 Provider 被 promote 的那台**机器**的事实，而不是关于该 capability 含义的事实；
要求它们会使该 capability 在除那台机器以外的所有 substrate 上都无法 bind，却不额外证明任何
东西——精确的版本与每个 device 的 compute capability 早已记录在 Provider 自己的
`runtime_target`里。契约现在要求`cuda-toolkit`、`nvidia-gpu`与`slurm-controller`，三者都由
prober 从观测中 emit。这是实测而非论证：在真实 GPU node 上，prober 与通用 feature 并列报告
`cuda-13.2`和`nvidia-sm121`，self-test 针对它实际找到的 architecture 编译，并以 negative
control 被检出、绝对误差为 0 通过；同一次运行中 device 经 CUDA API 报告 130 GB，而
`nvidia-smi --query-gpu=memory.total`返回`[N/A]`。

self-test 自身的 architecture 参数曾被钉死为单一值`sm_70`。约束它是对的——它会进入`nvcc`
的命令行——但约束为单一值不是 safety property，而是一个无法运行的 validation。现在按**形状**
检查，因此`sm_70; rm -rf /`仍被拒绝，而真实的 architecture 不会。promotion 中那份
requirement 列表副本，也沿着与它本地构造的 contract digest 相同的路径消失了：两者现在都来自
契约。手写的列表在 retirement 生效之后仍长期声称`exclusive-node`与`slurm`，而没有任何东西
比较过这两者。

toolkit 版本与 device 世代都被观测后丢弃，因此任何指名其一的契约都永远无法被满足。prober
现在从观测到的 compiler release emit `cuda-<major>.<minor>`，从每个 device 报告的 compute
capability emit `nvidia-sm<major><minor>`——是 observation，不是 derivation。12.0 的 node
不会自称 12.9，Blackwell device 也不会自称`nvidia-sm70`：一个 sm70 build 能否在更新的
architecture 上运行取决于它是怎么 build 的，猜这个不是 prober 的职责。

`exclusive-node`从该契约中消失，而不是被 emit，因为它根本不是 environment feature。它是关于
Provider 被 invoke 时所创建的 allocation 的断言，而 bind 时并不存在 allocation——job 要在数
分钟后才提交，prober 能测的东西与该命题并不相同。`JobRequestV1`本就拒绝构建不*请求*
pin 定 nodelist、无 GRES 的 exclusive 单 node 的 job；缺的那一半是 scheduler 确实*批准*了它
的证明。这件事现在发生在能够回答它的地方：`exclusive-allocation-witness-v1`由被提交的 job
从 allocation 内部检查，在 device probe 之前以 exit 88 拒绝，且无论结果如何都把 witness
保留为 job provenance。

witness 用`SLURM_JOB_CPUS_PER_NODE`与该 node 的`CPUTot`比较，这个选择来自实测而非假定。
`SLURM_CPUS_ON_NODE`是*step*的 cpu 数——在一个真正 exclusive 的 node 上，job 持有 20 时它被
观测为 4——建立在它之上的 witness 会恰好在它本该确认的 allocation 上失败。`OverSubscribe`
被记录但无人读取：在某个 sharing partition 上，`--exclusive`的 job 与共享 job 都报告`YES`，
该字段本身不区分任何东西。两个对照都在真实集群上跑过：sharing partition 上加`--exclusive`
得到 8 分之 8 allocated 且`held`；同一 partition 不加则是 8 分之 4 中的 2 allocated 且
`refused`。

发现的缺陷：在 Grace-Blackwell 上内存是统一的，`memory.total`读到`[N/A]`，而 device parser
会丢弃任何内存无法解析的行。于是 ARI 在一台确实有 GPU 的 node 上**一个 GPU 都没看到**，使
那里的所有 GPU capability 静默地无法 bind。一个内存数值解析不出来的 device 仍然是 device。

### 什么已被 promote，以及 promotion 不做什么

在出现真实 evidence 之前，upstream entry 一律保持`candidate`；这个`candidate`是关于
repository 的事实，而不是形式。remote Provider transport，以及 Inspect、Harbor、
PaperBench、KernelBench、ComputeEval 与 scBench 的 Harness entry 全部仍为 candidate：
promote 其中任何一个都需要真实的 upstream full commit、dataset/container/license pin、
official-runner parity、negative control，以及获准的 GPU 调度或 model credential。这六者
都不出现在已 check-in 的 Harness catalog 中，该 catalog 只有 native HPC entry。已 check-in
的外部 driver facade fail closed，不会以可变 source、伪造 pin、被跳过的 parity 结果或恒
pass 的 placeholder 作为替代。PaperBench 的 upstream API 与 aggregation parity 通过，但
官方的 rollout、reproduction 与 judge parity 仍不可得。

精确的 upstream ToolUniverse `1.3.1` lock 仍是失败的 candidate。已 promote 的只有独立
identity 的 metadata-only artifact `1.3.1+ari.1`，且范围仅限把匿名
`PubMed_search_articles`作为`ari.literature.search/v1`；其余 ToolUniverse leaf 均未 admit。

另有两个 Provider scope 拥有独立且绑定 evidence 的 verified lock。被允许的边界是那把
lock，而不是 upstream 产品的功能清单：

- **Qiskit MCP 0.3.1 与 Qiskit Aer 0.17.2**，仅就匿名 local ideal simulation 被 admit，
  以空 credential scope 供给`ari.quantum.sample.local-ideal/v1`。IBM Quantum Runtime、
  remote simulator 与硬件仍为 candidate，因为不存在与 credential 绑定的 backend、
  configuration、calibration、QPY、golden 或 replay evidence。
- **OpenROAD MCP 0.6.1 与 OpenROAD-flow-scripts `26Q3`**，仅就 GCD/Nangate45 的 local
  x86_64 CPU flow 被 admit，供给`ari.eda.openroad.place-route/v1`。同一设计的匿名
  exclusive-node SLURM CPU 执行是另一个单独 promote 的 Provider identity，其 lock 不请求
  GPU，且只保存加盐的 site digest。OpenROAD 的 GPU 执行、其他设计与 PDK，以及完整
  default flow 的 parity，都在这两个 identity 之外，各自需要单独命名的 candidate、
  evidence bundle、人工批准与 verified lock。

promotion 不是 activation。两个 Provider 都不在已 check-in 的`CATALOG.lock`中处于 active
——那个 lock 是有意为空的。activation 仍是 admission 时另行作出、按 run 冻结的
catalog/Provider/Binding lock 决定。

## extension gate

新的 Knowledge、Provider、Harness entry 分别使用`ari.knowledge.registration`、
`ari.providers.registration`、`ari.assurance.registration`的 gate。candidate file 不进入现有
run lock。修改 status 为`verified`前，maintainer 必须保留完整 source/data/container/license
pin 与全部 gate evidence。
