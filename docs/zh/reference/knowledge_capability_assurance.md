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
状态也会阻止 enforce mode 的固定 Knowledge Binder 激活它们，直到 clean-task、portability 与
human-promotion evidence 完整。

ToolUniverse collection profile 可包含 Knowledge subpath 与 admin profile，但没有 Provider
ID、launcher、tool、credential 或 transport field。所得 identity 使用
`ari://knowledge-source/tooluniverse/...` namespace，并输出`provider_activated: false`；它与
ToolUniverse MCP Provider 及 nested Provider lock 相互独立。

## Capability ontology 与 Provider binding

`CapabilityContractV1`固定 semantic input/output、side effect、determinism、context、
permission、resource、version 和 compatibility。Provider registration 检查 live input/output
schema 与该契约的兼容性；相同文字 label 不足以证明语义兼容。

无 prompt 的 Capability Binder 只考虑现有 Provider lock 中 verified Provider 的 exact
capability ref 与 contract digest。它按 role、phase、call context、side-effect ceiling、
credential scope、environment、disabled tool 与 live schema identity 过滤，再按 exactness、
verified status、explicit pin、context fit、最小 side effect、determinism、reproducibility、
feasibility、resource cost、lexicographic `tool_ref`确定排序。缺少 coverage 返回
`unsatisfied`，不存在 substring、bare-name、LLM 或 network fallback。

enforce mode 下 Agent 可见集合严格等于：

```text
Provider Lock tools
intersect Capability Binding Lock
intersect role authority
intersect phase policy
intersect call context
minus user-disabled tools
```

### environment evidence 与 Provider substitution

`ari.capability_binding.environment`在 binding 前记录 substrate 观测事实。它以 bounded、
shell-free probe 检查 SLURM partition、local NVIDIA device 和 CUDA compiler。当
`resources.gpus > 0`、SLURM ready 且看不到 local device 时，才通过`srun`执行一次 bounded
compute-node `nvidia-smi` query。config 声明不能虚构 resource。

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

## extension gate

新的 Knowledge、Provider、Harness entry 分别使用`ari.knowledge.registration`、
`ari.providers.registration`、`ari.assurance.registration`的 gate。candidate file 不进入现有
run lock。修改 status 为`verified`前，maintainer 必须保留完整 source/data/container/license
pin 与全部 gate evidence。
