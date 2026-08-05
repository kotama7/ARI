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

# 联邦科学工具注册表

`ari-skill-tool-registry` 将大型 MCP 集合隐藏在五个稳定操作之后：
`discover`、`describe`、`invoke`、`get_status` 和 `get_result`。它默认关闭，
不会把全部叶工具 schema 放入模型上下文，也不要求为每个叶工具手写配置。

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

## ToolUniverse 1.3.1 / 1.3.1+ari.1 adapter

ToolUniverse 作为一个 compact collection 接入，而不是暴露数千个公共 MCP 工具。
注册表进程不导入 ToolUniverse；operator sync 通过 compact list/info/execute surface
生成 canonical 叶 descriptor，运行时只把活动 lock 中的精确叶名称传给
`execute_tool`。

上游 `1.3.1` support record 仍为 `candidate`：其 `fitz` requirement 会解析到并非
PyMuPDF 的 distribution，继而引入破坏受支持 Python runtime 的
`pyxnat`/`pathlib==1.0.1`。ARI 不会弱化该记录。独立 identity
`1.3.1+ari.1` 不改 source code，只把 package metadata 的依赖替换为
`PyMuPDF==1.26.4` 并使用 local version。support record 固定上游 commit/wheel、
patch、确定性 build recipe、两次构建 byte-identical 的 wheel、完整 runtime lock、
package tree、license 与 Provider manifest。production 只接受 operator artifact
store 中 full SHA-256 匹配的 retained wheel，不从 package registry 动态解析。

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
`sha256:ecd7cc79542acfcfa177186d3bbe154678f1a378454834b6276efb1383eeab28`。
它只覆盖 x86_64、单线程、local-MCP CPU、固定 GCD placed database 和 Nangate45
PDK/library，并绑定 live schema parity、DRC-zero metrics、golden/replay、独立 ORFS
reference、十五项 registration gate 与 human approval。固定 binary 在默认 CTS timing
repair 中触发 SIGILL，因此 reference run 使用 `SKIP_CTS_REPAIR_TIMING=1`；这被记录为
独立 reference pass，而不是完整 default-flow parity。1.54 GB SIF 是 Git 外的 retained
artifact；lock 固定 OCI manifest、SIF、inner OpenROAD 的完整 digest 与配置路径。

独立的`openroad/0.6.1+orfs-26q3-gcd-nangate45-slurm-cpu` identity 也已正式
promote。其 lock
`sha256:d640dd226c101f9027e11f11c2201afd694b4914c11d7d45b458d142bc2971fd`
固定匿名 exclusive-node CPU site digest、scheduler client、PRoot/SIF/unsquashfs/
worker Python、runtime-owned metrics lifecycle、nonce-bound fixed-wrapper
completion、live DRC-zero result、fixture、gate 与 human approval，并请求零 GPU。
GPU 执行、其他 design/PDK/corner 或 image 不属于任一 lock。对应的 human-admin
entry point 是`scripts/promote_openroad_gcd_cpu.py`和
`scripts/promote_openroad_gcd_slurm_cpu.py`，均不会通过 Agent MCP 暴露。

`slurm` 将封闭命令编译为 digest-pinned Tcl，并把固定 worker/input 通过
C06 `JobRequestV1` 提交。必须使用单 node/task、与 threads 一致的 CPU、共享
work root，以及 digest 与 toolchain 一致的 clean/contained SIF，或经过审核并固定
digest 的 PRoot/SIF/unsquashfs/worker-Python portable runtime。
scheduler handle/status/cancel、environment/module/container digest、日志与 provenance 会进入
result/EAR。只有确认 scheduler 终态后才删除 workspace；transport 结果不明时
fail closed 并保留现场以供 ledger 对账。

物理 cluster、partition 和 node 名称仅属于 runtime private 数据。它们只能从带有
256-bit nonce 且被 Git ignore 的 site 文件读取，不得写入可追踪的 profile、snapshot、
fixture、evidence、lock、文件名、测试或文档。公开 identity 只能是加盐后的完整
SHA-256 `site_identity_digest`。promotion 前后都会扫描 Git candidate 集合；site 文件
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
`sha256:074755af42b998ca9e0369b156eb124bfa029e8a6c586cfe7dc4b239836c6684`。
它只覆盖无需 credential 的 seeded Bell-state local Aer 与
`ari.quantum.sample.local-ideal/v1`，并固定 QPY bytes/version、target、software、seed、
count 范围、live MCP schema、golden/replay、十五项 Provider gate 与 human approval。
IBM Runtime MCP、remote simulator 与 IBM hardware 仍为 candidate：当前没有 admitted
credential、精确 live backend/configuration/calibration identity 和 backend-bound
golden/replay evidence，不能继承 local Aer 的 promotion。
对应的 human-admin entry point 是`scripts/promote_qiskit_local_aer.py`，不会通过 Agent
MCP 暴露。

Provider promotion 只改变 governed eligibility，并不自动 activation。两个 identity
都不会加入 committed 的空 `CATALOG.lock`；operator 必须 materialize 精确环境，审核
source sync，再为每个 run 固定 Provider Lock 与 Capability Binding Lock。

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
