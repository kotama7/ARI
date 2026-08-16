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
last_verified: 2026-08-16
---

# 联邦科学工具注册表

`ari-skill-tool-registry` 将大型 MCP 集合隐藏在五个稳定操作之后：
`discover`、`describe`、`invoke`、`get_status` 和 `get_result`。承载它们的是
六个 MCP tool，因为 `invoke_scheduled` 是同一 dispatch 操作的第二个面：Provider
的 side-effect class 由其 permission 导出，把 `scheduler` 放到共享的 `invoke`
上会抬高其后每个 leaf 的 envelope。Skill 默认启用，
但不会把全部叶工具 schema 放入模型上下文，也不要求为每个叶工具手写配置。启用
Skill 不等于启用任何叶工具：只有所选 catalog 中的 source 才能执行，Skill flag
与 catalog 是两道独立 gate。运行时用 `ARI_TOOL_REGISTRY_LOCK` 和
`ARI_TOOL_REGISTRY_INDEX` 选择 catalog。

## 生命周期

```text
少量已审查 sources.yaml
  -> 隔离的 provider discovery
  -> canonical descriptor 与可见 origin chain
  -> 图、安全、conformance 与科学 admission
  -> 已审查 CATALOG.lock + 派生 index
  -> 不可变五操作 broker
```

运行时不读取 `sources.yaml`。同步变化只生成 pending lock/index 和审查 diff；
只有显式 `--approve` 才替换活动 lock，已运行的 broker 永不刷新快照。

不透明 `tool_ref` 绑定 provider、adapter、schema、显式默认值、权限/副作用、
确定性、执行语义、方法身份和异步生命周期。策略和来源别名使用独立身份，
因此策略重评不会伪装成实现变更。

## 科学 admission

| 级别 | 所需证据 |
|---|---|
| `discovered` | 候选及其叶来源透明可见 |
| `callable` | MCP conformance、provider pin、launcher 验证及允许权限 |
| `reproducible` | 再加依赖 pin 与离线 replay fixture |
| `scientifically_admitted` | 再加验证、局限、语义、单位及方法身份 |

被发现不等于权威或科学正确。注册表报告证据和策略判定，不会无条件信任上游。

## 集合合成与冲突

只有执行身份完全相同的别名会合并，同时保留全部来源链。相似能力默认仍是
独立工具。目录明确区分 exact duplicate、same backend、semantic near-match
与 independent method，不因名称相似而自动平均，并分别保存分歧与 provenance。

因此 ToolUniverse 类集合、OpenROAD、量子模拟器及未来 MCP bundle 可以通过
同一边界共存。直接 stdio MCP 无需自定义叶代码；其他 transport 每个集合只需
一个 `CatalogSource`、一个 `ProviderAdapter` 及其 conformance fixture。

## ToolUniverse 1.3.1 / 1.3.1+ari.1 / 1.3.1+ari.2 adapter

ToolUniverse 作为一个 compact collection 接入，而不是暴露数千个公共 MCP 工具。
注册表进程不导入 ToolUniverse；operator sync 通过 compact list/info/execute surface
生成 canonical 叶 descriptor，运行时只把活动 lock 中的精确叶名称传给
`execute_tool`。

上游把 `source_file` 报告为绝对安装路径。adapter 先把它规范化为相对已审查
package root 的路径，再同时写入 leaf metadata 与 `tool_spec_digest`；位于该
package 之外的路径记为 `<outside-reviewed-package>` 而不披露。此前该绝对路径进入
了 digest，同一个已审查 wheel 在每台机器上都得到不同的 leaf identity，promoting
host 的绝对路径还会被写进 promotion evidence。

上游 `1.3.1` support record 仍为 `candidate`：其 `fitz` requirement 会解析到并非
PyMuPDF 的 distribution，继而引入破坏受支持 Python runtime 的
`pyxnat`/`pathlib==1.0.1`。ARI 不会弱化该记录。独立 identity
`1.3.1+ari.1` 不改 source code，只把 package metadata 的依赖替换为
`PyMuPDF==1.26.4` 并使用 local version。support record 固定上游 commit/wheel、
patch、确定性 build recipe、两次构建 byte-identical 的 wheel、完整 runtime lock、
package tree、license 与 Provider manifest。production 只接受 operator artifact
store 中 full SHA-256 匹配的 retained wheel，不从 package registry 动态解析。

`1.3.1+ari.2` 是又一个独立 identity。它原样保留 ari.1 的
`fitz>=0.0.1.dev2 -> PyMuPDF==1.26.4` metadata 修复，并额外在 `smcp.SMCP` 的两处
serialization site 把响应上限从 `100_000` 提高到 `2_000_000`；与 ari.1 不同，它确实
修改 source code（`source_code_changes: true`）。上游对每个 compact MCP 响应设
100,000 字符上限，且在结构化裁剪无法容纳时回退为裸字符串截断并输出非法 JSON，使
整集合枚举不可能：即使 batch size 为 1，`get_tool_info(detail_level=full)` 对最大的
叶工具仍会超限。在全部 2,601 个已加载叶工具上测量，单次响应最大 510,904 字符，只有
两个超过 100,000，因此 2,000,000 能以约三倍余量容纳观测到的最坏 batch，同时远低于
7,103,230 字符的整集合 dump。该版本只提供 build recipe、metadata patch、Provider
manifest 与 runtime lock；它声明的能力与 ari.1 相同
（`PubMed_search_articles -> ari.literature.search/v1`），但没有 verified lock。

checked-in `verified-lock-v1.json` 只 promotion
`tooluniverse-pubmed@1.3.1+ari.1` 及 exact leaf
`PubMed_search_articles -> ari.literature.search/v1`。它固定 Provider manifest、
artifact、adapter/projection 实现、CPython 3.13 linux-x86_64、live compact
`tools/list` schema、leaf/spec/input/output/normalized-output schema digest、
Capability contract、evidence bundle、全部十五个 registration gate，以及 human
maintainer 明确作出的 `candidate -> verified` 批准。批准 digest 与 lock 和精确的
capability scope 绑定。仅修改 `status`、删除或更改批准、扩大 scope 或改变任一
evidence byte 都会被拒绝。其他 ToolUniverse leaf
和未经修改的上游 release 均未 promotion。

category/type profile 为一组叶工具声明副作用、确定性、权限、局限和 lineage，
无需逐叶 wrapper。即使上游 CLI 在后台加载更大的集合，ARI 仍会独立执行 category
过滤，并在运行时再次限制为 lock 中的叶名称。dynamic MCP loader、agentic/compose/
code execution、需要 credential、未审查或匹配不唯一的 profile，以及无效 schema
都会被 quarantine。仅对 v1.3.1 已知的 property-level `required: true` 方言做确定性
转换，将其移入标准父级 `required` 数组并记录 provenance；不会猜测修复其他 schema。

Capability substitution 必须是 exact semantic projection，不得依据工具名称或
description 的相似性决定。profile 明确列出每个 admitted leaf、精确
`capability_ref`、semantic result contract 与 result normalizer。leaf 消失或
category/type 改变会使 sync 失败；locked schema 或 Provider identity drift 会使
runtime 失败。PubMed projection 把精确的 `PubMed_search_articles` response
规范化为 `ari.retrieval-result/v1`，并为每条 record 记录 content/provenance digest。
该 verified identity 的 credential scope 为空；即使上游声明 optional
`NCBI_API_KEY`，ARI 也不会传入，并把匿名 live probe 纳入 promotion evidence。使用
API key 的配置必须成为新的 Provider identity，重新接受 credential scope review 和
promotion。

默认 admission policy 接受 ontology 中精确的 `network-read` permission，但不会
扩大为 network write 权限。从该 verified identity 同步后，只有一个 PubMed leaf
达到 `callable`；仓库中提交的默认 catalog 仍为空。正式 promotion 改变 governed
status，而不是自动 activation；每个启用它的 run 仍须显式固定环境专属 catalog 与
Binding Lock。

ari-patched-wheel 的 ToolUniverse source 也可以不提供 verified lock。这样的
source 是 collection-wide 的，不携带任何 leaf promotion，因此不得声明
`evidence.replay_fixture_digest` 或 `evidence.scientific_validation_digest`——这两个
级别要求绑定 verified lock 的 leaf evidence。没有 lock 时 source 仍可 `callable`，
但无法达到 `reproducible` 或 `scientifically_admitted`；无论哪种情况，都仍要求
retained wheel 完整 SHA-256 精确匹配。

参数始终按 locked schema 严格验证，不允许类型 coercion。由于上游会静默删除显式
`null`，adapter 会拒绝它。ToolUniverse cache/persistence、update check、hook 和
search 均被关闭；结果记录 collection/wheel/provider/leaf-spec identity 和
`upstream_cache: disabled`。只有 ARI cassette/EAR 是 replay authority，集合级信任
不会传递成叶工具的 replay 或科学验证。

所有 stdio Provider 都通过 value-free supervisor 启动。Provider 本体位于独立
process group，正常退出、timeout 与 cancel 都会回收整个 group；真实 process test
验证 spawned descendant 不会残留。只有 admin 命令
`scripts/promote_tooluniverse_pubmed.py` 能执行 promotion，agent MCP surface 不暴露
promotion 或 lock rewrite。实际 run 同时固定 checked-in dependency/verified lock 和
installation-specific `provider_digest`。

批量更新只生成 pending diff。input/output/default schema 变化不能仅凭普通
`--approve` 通过，还必须在审查后显式使用 `--approve-schema-changes`。

## OpenROAD profile adapter

OpenROAD-MCP 的交互工具不会暴露为叶子；一个已审查
`OpenRoadExperimentV1` 对应一个虚拟异步叶子。调用者只提供 `request_id`，
Tcl、路径、PDK/library、OpenROAD/ORFS commit、seed、threads、资源和容器都固定在
experiment/method identity 中。

`local-mcp` 把通过验证的 typed command 编译为 runtime 私有的固定 Tcl 文件，只让
MCP 启动该文件，并通过只读 session 状态轮询完成情况。OpenROAD 正常退出并 flush
`-metrics` 后才收集 artifact；PTY echo 或短暂无输出都不能作为完成信号。所有终态
路径都会 terminate session，临时 local run 不能续跑。

正式 promote 的本地 OpenROAD identity 是 checked-in bundle
`openroad/0.6.1+orfs-26q3-gcd-nangate45`。其 verified lock digest 为
`sha256:fbc4be322a03aa50e666a0dcdb3b1afdfe60fa52bbc570e9cd8f1c800168825e`。
它只覆盖 x86_64、单线程、local-MCP CPU、固定 GCD placed database 和 Nangate45
PDK/library，并绑定 live schema parity、DRC-zero metrics、golden/replay、独立 ORFS
reference、十五项 registration gate 与 human approval。固定 binary 在默认 CTS timing
repair 中触发 SIGILL，因此 reference run 使用 `SKIP_CTS_REPAIR_TIMING=1`；这被记录为
独立 reference pass，而不是完整 default-flow parity。1.54 GB SIF 是 Git 外的 retained
artifact；lock 固定 OCI manifest、SIF、inner OpenROAD 的完整 digest 与配置路径。
SIF header 内含随机 UUID 与 wall-clock 创建时间，且它们参与文件哈希，因此没有任何
容器 runtime 能重现 `retained_sif_digest`：本地重新 materialize 后该 digest 与 SIF
字节数都变了，而固定的 OCI manifest digest 与 inner OpenROAD binary digest 完全一致，
payload 由此被证明相同，只是 envelope 无法重现。support record 中重新 materialize
后的 retained SIF 在 `singularity` 4.5.0-1.el9 下的 digest 为
`sha256:b8af5db8db5feb98720faf0959f6d3d478aac89f41cc9ad9d385467800c6580c`，
大小 1,540,308,992 字节。

独立的`openroad/0.6.1+orfs-26q3-gcd-nangate45-slurm-cpu` identity 也已正式
promote。其 lock
`sha256:def08a69e7c0c13e8e76e026163337f39667ee8467792c16cad91d96ee9bd203`
固定匿名 exclusive-node CPU site digest、scheduler client、scheduler snapshot
digest、digest 固定的 clean container（`singularity` 4.5.0-1.el9、`contain_all`、
clean environment、`network: none`、无 GPU passthrough）、runtime-owned metrics
lifecycle、来自 scheduler 的终态证据、live DRC-zero result、fixture、gate 与
human approval，并请求零 GPU。已审查的 PRoot/unsquashfs/worker-Python 构建所链接
的 host glibc 版本高于 promoting site 提供的版本，因此该 SLURM profile 改为固定这个 clean
container；隔离反而更强：closure 只是 SIF 本身，而不是 SIF 加上 portable runtime
固定的三个 host binary（PRoot、`unsquashfs`、worker Python）。
`environment_requirements` 现在由 profile 派生而不是写死，该 lock 列出
`cpu`、`exclusive-node`、`singularity-sif`、`slurm`；`runtime_target` 随所声明的
基底记为 `worker_python: container-provided`、
`execution_substrate: singularity-sif`、`network: isolated`。
GPU 限制的措辞取自已审查的 scheduler snapshot，而不是把某一个 site 的情况当作
普遍事实：scheduler 未声明 GRES type 时根本无法请求 GPU；声明了 GRES type 时，
保证来自被分配 node 上不暴露加速器。两种情况下 profile 都请求零 GPU，也不授予任何
GPU 能力。GPU 执行、其他 design/PDK/corner 或 image 不属于任一 lock。对应的
human-admin entry point 是`scripts/promote_openroad_gcd_cpu.py`和
`scripts/promote_openroad_gcd_slurm_cpu.py`，均不会通过 Agent MCP 暴露。

`slurm` 将封闭命令编译为 digest-pinned Tcl，并把固定 worker/input 通过
C06 `JobRequestV1` 提交。必须使用单 node/task、与 threads 一致的 CPU、共享
work root，并且恰好固定一种执行基底：digest 与 toolchain 一致的 clean/contained
SIF container，或经过审核并固定 digest 的 PRoot/SIF/unsquashfs/worker-Python
portable runtime。两种基底都仍被 execution contract 接受，用哪一种是 site 属性，
恰好固定一种才是不变式。typed job 记录的 container digest 必须与 profile 所固定的
完全相同：container run 是 image digest，PRoot run 则完全没有 container。
scheduler snapshot 验证把 live controller 与已审查 snapshot 中声明的值（slurm 版本、
GRES type、partition MaxTime、node 架构、CPUTot、Sockets、
ThreadsPerCore）逐项比较，而 cluster 名与 node 名这两个永不进入 repository 的
selector 则与 operator 的 private site configuration 比较；另加一小组不属于 site 特征的不变式（`Arch=x86_64`、
`Gres=(null)`、`OverSubscribe=EXCLUSIVE`），并拒绝声称拥有 GPU authority 的
snapshot；因此同一个 promotion 也能在另一个 scheduler site 运行，而 snapshot 与
live controller 之间的漂移仍然 fail closed。
scheduler handle/status/cancel、environment/module/container digest、日志与 provenance 会进入
result/EAR。终态来源随 scheduler 而定：具备 accounting storage 时取自 scheduler
（`scheduler_state COMPLETED`、`exit_code 0`），否则取自 nonce 绑定的 fixed-wrapper
记录（reason `fixed-wrapper-completion-v1`）；两种情况下 job 都必须真的成功。只有确认 scheduler 终态后才删除 workspace；
transport 结果不明时 fail closed 并保留现场以供 ledger 对账。

物理 cluster、partition 和 node 名称仅属于 runtime private 数据。它们只能从带有
256-bit nonce 且被 Git ignore 的 site 文件读取，不得写入可追踪的 profile、snapshot、
fixture、evidence、lock、文件名、测试或文档。公开 identity 只能是加盐后的完整
SHA-256 `site_identity_digest`。scheduler handle 的 `workspace_scope` 与
`artifact_scope` 以所声明的 work root 为基准记录为相对路径：digest 派生的 scope
名称才是可发布的部分，前缀只说明哪台机器执行了 promotion；scope 逃出 work root
会被拒绝。promotion 前后都会扫描 Git candidate 集合；site 文件
一旦可追踪，或任何明文 site identity 泄漏，流程立即 fail closed。
`scripts/check_site_privacy.py` 还会独立扫描 worktree candidate、staged blob、文件名与
symlink target；private site file 存在时，repository 的 pre-commit hook 必须执行该检查。

## Qiskit profile adapter

官方 Qiskit core MCP 与 IBM Runtime MCP 是供应链输入，而不是公共 catalog leaf。
一个审核后的 `QiskitExperimentV1` 对应一个虚拟异步 leaf；QPY/version、parameter
unit、transpilation target/seed、shots、simulator/noise 或 Runtime backend、mitigation、
evidence 和 limitations 都不可变，调用者只能传 `request_id`。

local ideal、local noisy、remote simulator 和 IBM hardware 使用不同 capability。core
MCP 只负责 transpile，本地 Aer 由验证精确 distribution 的 worker 执行。remote 仅内部
使用审核后的 setup、backend snapshot、sampler、status、result 和 cancel leaf，不发布
账户管理操作。backend/target mismatch 在提交前失败，live snapshot 与 job/result 原始
记录保存为验证过的 artifact。

`QISKIT_IBM_TOKEN` 通过 named credential scope 只交给隔离 Runtime 进程，并在 provider
边界按精确值脱敏。lock、cassette、artifact 和 identity 不包含 token 或原始 instance
CRN。科学契约、运维、更新/回滚和删除 gate 见
[Qiskit 与 IBM Quantum 实验配置](qiskit_profiles.md)。

唯一正式 promote 的 Qiskit identity 是
`qiskit/core-0.3.1+aer-0.17.2-local-ideal`。其 verified lock digest 为
`sha256:57b60bbdb84ba0364e038a6df51f3de2a48cdf8c776d31066efeec5ea68be195`。
它只覆盖无需 credential 的 seeded Bell-state local Aer 与
`ari.quantum.sample.local-ideal/v1`，并固定 QPY bytes/version、target、software、seed、
count 范围、live MCP schema、golden/replay、十五项 Provider gate 与 human approval。
IBM Runtime MCP、remote simulator 与 IBM hardware 仍为 candidate：当前没有 admitted
credential、精确 live backend/configuration/calibration identity 和 backend-bound
golden/replay evidence，不能继承 local Aer 的 promotion。
对应的 human-admin entry point 是`scripts/promote_qiskit_local_aer.py`，不会通过 Agent
MCP 暴露。

Provider promotion 只改变 governed eligibility，并不自动 activation。每一个已 promote
的 identity 都不会加入 committed 的空 `CATALOG.lock`；operator 必须 materialize 精确环境，审核
source sync，再为每个 run 固定 Provider Lock 与 Capability Binding Lock。

### 抵达 ARI Capability

本 catalog 中的 leaf 不是 ARI Provider，也从不出现在 `SKILLS.lock` 中，因此
Capability Binder 无法直接 authorize 它。`ari-core/config/providers/catalog.yaml`
中的 `ari.provider.tool-registry` entry 把两者接起来：它的 `brokered` block 指名
本 catalog lock、默认 dispatch tool（`invoke`）、把提交调度器的 leaf 路由到
`invoke_scheduled` 的按 leaf 覆盖表 `dispatch_tool_by_leaf`，以及一张从 leaf
`tool_ref` 到 ARI `capability_ref` 的 reviewed table。每个 reviewed leaf 成为一条
composite `CapabilityProvisionV1`，其可调用身份是其路由指名的 dispatch 面，
语义身份是该 leaf。descriptor
自身的 `capability_ref` 属于本注册表的 namespace，绝不当作那张 mapping 读取；
决定权只在已签入的 table。

ARI 用 `ARI_TOOL_REGISTRY_LOCK` 解析该 lock——与 broker 用的是同一个变量——未设置
时回退到随包提供的路径。两者必须解析到同一个 lock，否则 ARI 描述的会是 broker
并未 dispatch 的 leaf。materialize 后的 lock 记录绝对本地路径、不进入仓库，
因此签入的是 reviewed table 而不是 lock。

authority 是两跳的 envelope：composite 的 side-effect class 取 leaf 与 `invoke`
两者中较重者，contract 的 required permission 必须由两者共同授予。`invoke` 声明
`stateful`，因此当前没有 `read-only` capability 能经由它供给。
`ari.literature.search/v1` 一度被记在这条规则名下，但真正挡住它的是它自己的
contract：一次 admitted retrieval 会写下让自己成为证据的记录，ladder 依据调用对
该 substrate 做了什么来定级，而不是它是否改动远端索引。该 contract 现为
`workspace-write`，reviewed 的 PubMed leaf 可以对它构造 composite；要登记这条
mapping，还需要一个含有该 leaf 的 site lock。

descriptor 声明异步 lifecycle 的 leaf 由 `invoke` 提交，由 `get_status` 与
`get_result` 收取。它们写在该 entry 的 `lifecycle_tools` 中并随 binding 一同携带，
因此 authorization view 在同一 binding、phase 与 call context 下放行。它们不是
独立的 capability——轮询一个你已被授权提交的 job 并不增加 authority。没有它们，
一个已 bind 的异步 capability 会启动它收不回来的工作；在它们被携带之前，发生的
正是这件事。

broker 是一个进程、一个 credential surface，因此 composite 携带该 Provider 的
credential scope，但只携带值确实存在的那些。声明了却缺席的 credential 不授予任何
authority——子进程只用存在的值构建，call context 本来就按同样方式过滤——若携带
声明集合，多领域 Provider 的每一条 provision 都会索要它可能用到的全部 scope：
bind 一个 OpenROAD leaf 会要求授予 `quantum.ibm-runtime`，而那与 EDA 无关。
在 `QISKIT_IBM_TOKEN` 未设置的 host 上——也就是出厂状态——broker 的 IBM Quantum scope
记录不到存在的值，composite 一个 scope 也不携带，bind OpenROAD leaf 完全不需要授予
credential。需要授予的时机恰好是 token 已设置之时，也即 authority 真实存在之时。
存在性在 lock 时观测并冻结进 Provider Lock，因此之后才出现的 token 会改变 lock，
而不是绕过这道检查。这与直连 Provider 路径适用的是同一条规则，并且 fail closed。

携带 call context 的四个 broker tool——`invoke`、`invoke_scheduled`、`get_status`
与 `get_result`——
在 input schema 中声明 `ari_context`。它们是 `context_requirement: run`，transport
按该名称注入已授权的 call context；一个设了 `additionalProperties: false` 却省略
它的 schema 会拒绝每一次已授权的调用。

还剩一处粗糙，且它不是 result normalizer 的缺陷。ARI 把 broker 自己的
`ari.result-envelope/v1` 再包一层 envelope，于是 brokered 异步提交把 handle 放在
`structured_content.structured_content` 里，而外层的 `async_handle` 仍为 null。
该字段承载 `ari.async-tool-handle/v1`，它驱动 `get_async_status` /
`get_async_result` / `cancel_async`，是为 manifest 声明的 ARI 异步 tool 而建的；
brokered leaf 的 handle 则是 broker 自己的协议 `ari.registry-handle/v1`。二者互转
在机制上可行——binding 现在知道 lifecycle tool ref，broker 也会返回它的 state
map——但当前没有调用者，而加一个没人调用的 converter，只会重犯这项工作一直在
消除的那个错误。在有需要之前，brokered 异步调用者直接轮询已 bind 的
lifecycle tool。

## record/replay 与 EAR

record 保存精确参数、catalog/policy digest、选择原因、被拒候选、原始响应
digest/artifact 和规范化 ResultEnvelope。replay 在相同不可变 catalog 下无需
启动 provider。证据位于 `{checkpoint}/ear/catalog/`，默认 EAR curator 会包含它。

```bash
cd ari-skill-tool-registry
python src/sync_catalog.py
python src/sync_catalog.py --approve   # 仅在审查 diff 后
python src/sync_catalog.py --approve --approve-schema-changes
python scripts/verify_tooluniverse.py --help
python scripts/verify_openroad.py --help
python scripts/verify_qiskit.py --help
python scripts/promote_openroad_gcd_cpu.py --help
python scripts/promote_qiskit_local_aer.py --help
python scripts/sync_contracts.py
pytest -q
```

禁止逐叶 production 配置、运行时刷新、直接公开叶 schema、裸名称 dispatch、
透传 provider 特有结果，以及在生产配置中注册 static fixture。
