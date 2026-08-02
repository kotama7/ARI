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
last_verified: 2026-08-02
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

## ToolUniverse v1.3.1 adapter

ToolUniverse 作为一个 compact collection 接入，而不是暴露数千个公共 MCP 工具。
注册表进程不导入 ToolUniverse；operator sync 通过 compact list/info/execute surface
生成 canonical 叶 descriptor，运行时只把活动 lock 中的精确叶名称传给
`execute_tool`。

支持矩阵固定上游 repository commit/tag、PyPI wheel/sdist、Apache-2.0 license、
上游依赖 lock、compact contract，以及已安装包全部 3,542 个文件的 canonical tree
digest。同步和运行时都会验证完整文件树和 shell-free 的
`tooluniverse.smcp_server:run_stdio_server` callable。版本范围、启动时安装、修改过的
包和其他入口都会 fail closed。

category/type profile 为一组叶工具声明副作用、确定性、权限、局限和 lineage，
无需逐叶 wrapper。即使上游 CLI 在后台加载更大的集合，ARI 仍会独立执行 category
过滤，并在运行时再次限制为 lock 中的叶名称。dynamic MCP loader、agentic/compose/
code execution、需要 credential、未审查或匹配不唯一的 profile，以及无效 schema
都会被 quarantine。仅对 v1.3.1 已知的 property-level `required: true` 方言做确定性
转换，将其移入标准父级 `required` 数组并记录 provenance；不会猜测修复其他 schema。

参数始终按 locked schema 严格验证，不允许类型 coercion。由于上游会静默删除显式
`null`，adapter 会拒绝它。ToolUniverse cache/persistence、update check、hook 和
search 均被关闭；结果记录 collection/wheel/provider/leaf-spec identity 和
`upstream_cache: disabled`。只有 ARI cassette/EAR 是 replay authority，集合级信任
不会传递成叶工具的 replay 或科学验证。

批量更新只生成 pending diff。input/output/default schema 变化不能仅凭普通
`--approve` 通过，还必须在审查后显式使用 `--approve-schema-changes`。

## OpenROAD profile adapter

OpenROAD-MCP 的交互工具不会暴露为叶子；一个已审查
`OpenRoadExperimentV1` 对应一个虚拟异步叶子。调用者只提供 `request_id`，
Tcl、路径、PDK/library、OpenROAD/ORFS commit、seed、threads、资源和容器都固定在
experiment/method identity 中。

`local-mcp` 使用有作用域的 stateful session，并在所有终态路径中 terminate。
`slurm` 将封闭命令编译为 digest-pinned Tcl，并把固定 worker/input 通过
C06 `JobRequestV1` 提交。必须使用单 node/task、与 threads 一致的 CPU、共享
work root、digest 与 toolchain 一致的 clean/contained SIF，以及 `network: none`。
scheduler handle/status/cancel、environment/module/container digest、日志与 provenance 会进入
result/EAR。只有确认 scheduler 终态后才删除 workspace；transport 结果不明时
fail closed 并保留现场以供 ledger 对账。

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
python scripts/sync_contracts.py
pytest -q
```

禁止逐叶 production 配置、运行时刷新、直接公开叶 schema、裸名称 dispatch、
透传 provider 特有结果，以及在生产配置中注册 static fixture。
