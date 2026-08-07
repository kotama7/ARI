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
last_verified: 2026-08-05
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

只有`declared_capability_refs_by_tool`会产生 provision。skill.yaml 一侧的`capability_ref`
作为`declared_capability_ref`被携带，但不参与 bind。因此不在该表中的 tool，无论自称什么
capability，都不会成为某个 Capability requirement 的解决对象——这不意味着它不能被调用，
只意味着它不是 bind 的候选。

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
  `exact`。低于自身`required_level`的 leaf、被 quarantine 的 leaf、catalog 中不存在的
  reviewed leaf，以及 run lock 中不存在的 dispatch tool，一律拒绝。

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
`config/capabilities/resource_derivations.yaml`。每一行声明它 emit 什么、必须已存在什么，
以及理由；没有 rationale 的行在 load 时被拒绝——没有理由的 derivation 就是 alias，而 alias
正是这张表存在的目的所要防止的。行被应用到 fixpoint，因此一行可以消费另一行 emit 的结果；
这里无法凭空造出 prober 未观测到的事实，而触发过的行记录在`metadata.derived_from_review`
中——依赖 derived resource class 的 binding 可以一路审计到允许它的那句话。随包的表记录了
Apptainer 与 SingularityCE 都执行 SIF、而 podman 与 docker 都不执行，并由 CPU 加 SIF
runtime 推导出`eda-cpu`。

SLURM GPU visibility 与 scheduler authority 不同。在没有 advertised GPU GRES 的 node 上
观察到 device 时，记录保留在`metadata.slurm_gpu`并增加
`gpu-observed-on-slurm-node`，但不增加`gpu` resource type。只有观察到 GRES，或 operator
明确启用现有 escape hatch `ARI_SLURM_ALLOW_NO_GRES=1`时才可调度。device UUID/model/
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

native `hpc/gemm-correctness`、`hpc/spmm-correctness`和`hpc/stencil-correctness`包含
deterministic generated case、独立 reference、dtype/accumulation-aware error model、
metamorphic/shape/boundary/repeat coverage 与 negative control。promote 为 checked-in verified
catalog entry 是 release admission 操作，要求 committed source revision、immutable container、
license review、reference pass、negative-control fail 与 retained registration report。

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

## extension gate

新的 Knowledge、Provider、Harness entry 分别使用`ari.knowledge.registration`、
`ari.providers.registration`、`ari.assurance.registration`的 gate。candidate file 不进入现有
run lock。修改 status 为`verified`前，maintainer 必须保留完整 source/data/container/license
pin 与全部 gate evidence。
