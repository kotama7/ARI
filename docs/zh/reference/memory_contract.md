---
sources:
  - path: ari-core/ari/memory_contract.py
    role: schema
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/writer.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/retriever.py
    role: implementation
last_verified: 2026-08-02
---

# 研究记忆契约

ARI 记忆是谱系作用域的索引，而不是科学证据本身。规范存储格式为
`ari.memory-record/v1`，搜索响应为 `ari.memory-retrieval/v1`，可移植快照使用
`ari.memory-backup/v1`。JSON Schema 位于
`ari-core/ari/schemas/memory_record_v1.schema.json`、
`memory_retrieval_v1.schema.json` 与 `memory_backup_v1.schema.json`。

## 不可变记录

`MemoryRecordV1` 将 kind/text 与 source run/node、有序 ancestor、artifact、
node report、带单位 metric、confidence、可重现性事件和创建 tool 绑定。
`record_id` 与 `record_digest` 是规范化 payload 的同一 SHA-256 内容地址；检索和
恢复会重新验证并拒绝篡改。

artifact ref 包含安全相对路径、完整 SHA-256、字节数、role 和
`verified`/`unverified`。只有 writer 在声明 root 下读取真实文件且 digest 相同时才标为
`verified`。metric 必须显式给出单位，node-report ref 必须给出 report digest。
记忆文本或 `unverified` ref 不能单独作为论文证据。

写入仅追加，并按 record digest 幂等。可重现性状态以新的
`reproducibility_event` 追加，不修改目标。公共 MCP 刻意不提供 clear/delete tool；
checkpoint purge 仅作为显式恢复和部署修复的管理操作。

## 检索来源

每次搜索返回 backend、client/server version、embedding model/version、ranking、
determinism、query digest、候选/返回数量、边界和 filter evidence。Letta embedding
排序明确标为非确定性。类型过滤使用已验证的规范记录，而非可变投影；旧的无版本行会被排除。

## 备份、恢复与迁移

`ari memory backup` 生成确定性的 `memory_backup.v1.json.gz`，包含根 digest、
排序的 record-digest 索引、经验证的逻辑 record order 和逐 ReAct-entry digest。
恢复在任何写入前验证完整文档，支持
`skip` / `merge` / `overwrite`，并按内容 digest 去重。备份不依赖 checkpoint
namespace，可恢复到全新的 Letta 部署。

run/resume 不读取旧记忆文件。v0.5 JSONL 必须显式运行 `ari memory migrate`：验证、
转换为 v1、成功写出 portable backup 后才归档源文件。跨实验 global memory 只报告，
不导入。

## 部署支持

所有生产模式都使用 Letta。`InMemoryBackend` 需要 test marker，且不能由 workflow 选择。

| 模式 | 状态 | 范围 / gate |
|---|---|---|
| Letta Cloud | 支持 | HTTPS endpoint/API key；必须通过 health check |
| Docker Compose | 支持，本地工作站首选 | Postgres compose 与 clean-start test |
| Apptainer / Singularity | 支持，HPC 首选 | portable start script、env/runtime 检查 |
| pip | 支持的 fallback | 无容器本地服务、静态 clean-launch test；容器失败后不静默回退 |

四种路径的 support owner 均为 ARI maintainers。为无容器主机保留 pip，并在 v1.1
依据部署 issue 与使用报告重新评估。任何路径都不得静默回退到 test backend。

## 消费规则

论文或图表声明应使用 `get_verified_context`。未验证记忆可作为补充上下文显示，但只有
全部 artifact 均 verified 且最新重跑事件不是 `rerun_failed` 的记录才进入
`usable_for_claims`。
