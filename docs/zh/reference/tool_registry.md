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

## record/replay 与 EAR

record 保存精确参数、catalog/policy digest、选择原因、被拒候选、原始响应
digest/artifact 和规范化 ResultEnvelope。replay 在相同不可变 catalog 下无需
启动 provider。证据位于 `{checkpoint}/ear/catalog/`，默认 EAR curator 会包含它。

```bash
cd ari-skill-tool-registry
python src/sync_catalog.py
python src/sync_catalog.py --approve   # 仅在审查 diff 后
python scripts/sync_contracts.py
pytest -q
```

禁止逐叶 production 配置、运行时刷新、直接公开叶 schema、裸名称 dispatch、
透传 provider 特有结果，以及在生产配置中注册 static fixture。
