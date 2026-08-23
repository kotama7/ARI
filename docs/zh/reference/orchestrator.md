---
sources:
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/service.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/registry.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/execution.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/migration.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/runtime.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/contracts.py
    role: schema
last_verified: 2026-08-02
---

# Orchestrator 控制平面

`ari-skill-orchestrator` 是 ARI 对外的异步控制面。它负责 submission、status、cancellation、
lineage quota、authorization 与安全的结果读取，不负责 BFTS 内部实现或 federated leaf-tool selection。

## 公开契约

所有 model 都拒绝未知字段，并已检入 `ari-skill-orchestrator/schemas/`：

- `RunRequestV1` 将 experiment text、idempotency key、parent、model profile 及所有
  recursion/resource/cost limit 绑定到 `request_digest`；
- `RunHandleV1` 标识确切的 run、owner、root、depth 与当前 state；
- `RunStatusV1` 增加 timestamp、exit/error state、受限 node progress 与 lineage budget usage；
- `RunResultV1` 返回 status 和 `ArtifactRefV1` 值；
- `ArtifactRefV1` 使用已验证的 `sha256:…` digest 作为 `artifact_id`，包含 role、media type 与
  size，但不包含 filesystem path。

生命周期如下：

```text
submitted -> running -> succeeded | failed
                     -> cancelling -> cancelled | succeeded | failed
submitted -------------------------> cancelled | failed
```

terminal row 不可变。state transition 和 append-only event record 使用 `BEGIN IMMEDIATE`、WAL 与
full synchronization 提交到 `logs/.ari-orchestrator/runs.sqlite3`。对于相同的
`(principal_id, idempotency_key)` retry，若 request digest 相同则返回现有 handle；不同则失败。

## 重启与取消

每个 run 在新的 process session 中启动一个小型 wrapper。wrapper 在独立 child process group 中启动
`ari run`，并原子记录绑定到 `run_id` 与 `request_digest` 的 receipt。wrapper 与 child identity 均含
`/proc` start tick，因此复用的 PID 不会收到 signal，也不会被当作证据。重启时：

- 存活且 identity 匹配的 wrapper 保持 `running`；
- 有效 terminal receipt 确定其记录的 terminal state；
- process 消失且没有 terminal receipt 时 fail closed；
- `submitted` row 不会自动重新 launch，以避免重复科学实验。

`stop_experiment` 先记录 `cancelling`，向 wrapper 发送 signal，等待受限 grace interval；如有必要，
再次检查 identity 后终止 child/wrapper process group。

durable process execution 当前需要 Linux `/proc`。平台提供 `sched_setaffinity` 时，wrapper 将声明的
CPU 数应用到 process affinity，并设置 child 的公共 OpenMP/BLAS thread 上限。每个 run 获得 mode 0700
的 private `HOME`。timeout enforcement 由 wrapper 负责，不委托给 experiment。

## Authorization 与 transport

stdio 使用 `ARI_ORCHESTRATOR_PRINCIPAL_ID` 和可选的逗号分隔角色
`ARI_ORCHESTRATOR_PRINCIPAL_ROLES`。run owner 可访问自己的记录；`admin` 角色可检查所有记录。
authorization 在 status detail、artifact discovery、cancellation 与 lock inspection 之前执行。

stdio 与 MCP Streamable HTTP 调用相同的 function 和 service。Streamable HTTP 默认绑定
`127.0.0.1`，并要求 `ARI_ORCHESTRATOR_HTTP_TOKENS_FILE`。该文件不得为 symlink，且 mode 必须为
0600：

```json
{
  "schema_version": "ari.orchestrator-token-digests/v1",
  "tokens": [
    {
      "token_sha256": "<64 lowercase hex characters>",
      "principal_id": "automation-user",
      "roles": []
    }
  ]
}
```

系统只保存 token digest。adapter 实现 MCP SDK `TokenVerifier`，因此可在不改变工具或 service semantics
的情况下，以 OAuth resource-server verifier 替换本地文件。issuer/resource metadata 通过
`ARI_ORCHESTRATOR_OAUTH_ISSUER_URL` 与 `ARI_ORCHESTRATOR_OAUTH_RESOURCE_URL` 配置。

## Quota

每个 request 声明 per-run 与 lineage bound。deployment ceiling 为：

| Environment variable | Default |
|---|---:|
| `ARI_ORCHESTRATOR_MAX_ACTIVE_RUNS` | 16 |
| `ARI_ORCHESTRATOR_MAX_NODES_PER_RUN` | 1000 |
| `ARI_ORCHESTRATOR_MAX_TOTAL_NODES` | 10000 |
| `ARI_ORCHESTRATOR_MAX_DESCENDANT_RUNS` | 1000 |
| `ARI_ORCHESTRATOR_MAX_COST_USD` | 10000 |
| `ARI_ORCHESTRATOR_MAX_CPUS` | 256 |
| `ARI_ORCHESTRATOR_MAX_TIMEOUT_MINUTES` | 2880 |

registry 从 parent 推导 child depth，并原子检查 root-lineage 的 run、node 与 estimated-cost consumption。
caller 不能提高 ancestor 的 depth limit。违反限制时既不建立 run row，也不建立 checkpoint。

这些值是 admission/execution bound，而不是 container boundary：`estimated_cost_usd` 由 caller 声明，
本 service 不提供 memory/GPU isolation。experiment process 仍以 orchestrator 的 Unix identity 运行，
拥有配置的 workspace access。不可信或相互敌对的 workload 需要此 control plane 之外的 container、
scheduler 或独立 executor identity。

## Artifact admission

公开 API 不接受文件名。系统只准入封闭集合中的 root output；EAR 文件只能通过已验证的
`evidence.index.json` 或 `ear_published/manifest.lock` v2 添加。discovery 拒绝 traversal、symlink
（包括 parent component）、non-regular file、类似 secret 的名称、缺失 record、额外 published file、
size drift 与 digest drift。读取时重新计算 content hash，并将 inline payload 限制为 2 MiB。更大的
artifact 仍可按 digest 列出，但不能通过 `read_artifact` 下载；deployment 必须使用另行授权的 artifact
store 对外提供。

`list_skills(run_id)` 与 `get_workflow(run_id)` 要求有效且 run-bound 的 `SKILLS.lock`。它们只返回
identity/digest/phase membership，不返回 entrypoint path、environment 名称、credential scope、raw
schema、LLM configuration 或 resources。

## Credential 与 environment boundary

launcher 使用 `ari.public.execution.build_minimal_environment`，绝不复制完整 parent environment。
model credential 只能通过 manifest 的 `model.provider` scope。credential 值由 child process 在内存中
继承，但不会出现在 request JSON、SQLite、metadata、argv 或 runner receipt 中。tool schema 没有
API-key argument。per-run private `HOME` 防止通过共享 home 进行常规 credential/cache 复用，但不能
替代 OS-level isolation。

## Migration 与删除

正常 status/list call 不扫描 checkpoint directory。受控迁移运行
`python ari-skill-orchestrator/src/server.py --repair-registry`。它只导入带 `experiment.md` 的安全
direct-child checkpoint；ambiguous 或看似仍存活的 legacy state 会成为 `failed`，且永不重新 launch。
验证后，按 release support window 删除旧 checkpoint metadata reader。

版本 2 删除了任意 `read_file`/`list_files`、substring run matching、environment copying、raw
workflow/Skill configuration、request-level credential、由扫描推导的 live state 与自定义 REST/SSE
实现。唯一的网络 adapter 是 authenticated MCP Streamable HTTP。
