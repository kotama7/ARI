---
sources:
  - path: ari-core/ari/research_contract.py
    role: implementation
  - path: ari-skill-web/src/retrieval.py
    role: implementation
  - path: ari-skill-web/src/network_policy.py
    role: implementation
  - path: ari-skill-web/src/server.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-02
---

# 检索契约与网络策略

ARI 将来源获取与科学采纳判断分离。`ari-skill-web` 负责检索、规范化和来源记录；Idea、Evaluator 与 Paper 组件决定证据如何使用。

## 公共记录

标准结果 `ari.retrieval-result/v1` 包含 `RetrievalRecordV1` 的 `records`、受摘要约束的 `SurveySnapshotV1`、`survey_snapshot_digest`、可选的检查点相对 `snapshot_ref`，以及跨提供方的 `alias_groups`。`papers` / `results` 只是保留到 P6 的兼容投影。

每条记录保存 provider、provider record/version、query、检索时间、书目信息、source URL、raw payload digest、DOI/arXiv/S2 alias、license/use restriction。canonical ID 按提供方划分；即使 AlphaXiv 与 arXiv 描述同一论文，两条来源仍保持独立，只通过共同的 `arxiv:` alias 关联。

## 执行模式

| mode | 网络 | 写入artifact | 含义 |
|---|---:|---:|---|
| `live` | 是 | 否 | 当前提供方响应，不可重放 |
| `record` | 是 | 是 | 一个固定提供方及不可变cassette/snapshot |
| `replay` | 否 | 否 | 验证并原样返回已记录的规范化对象 |

`record` / `replay` 需要 `ARI_CHECKPOINT_DIR`，并使用以下布局：

```text
retrieval_cassettes/<raw-cassette-sha256>.json
retrieval_payloads/<raw-body-sha256>.bin
retrieval_snapshots/<snapshot-digest>.json
```

重放会校验 snapshot 自摘要、内容寻址路径、所有 artifact SHA-256、provider/query/operation/parameters、records、citation edges 与 warnings。提供方故障会显式报错，不会切换到另一提供方。需要多个提供方时，应分别执行固定调用，由上层 broker 在保留全部来源的前提下按 alias 合成。

## URL 与引用图安全

`fetch_url` 仅允许 HTTP(S) 的80/443端口，拒绝 userinfo 与任何非全局 DNS 地址。它直接连接已验证IP并保留TLS SNI，对每次重定向重新验证，拒绝HTTPS降级、重定向超限、响应过大与非文本媒体。正文在record模式保存为raw artifact，返回文本明确标记为不可信外部数据。

`walk_citations` 同时限制 depth、node 与 request budget，并检测环；达到上限时返回已保留的record/edge及 `partial_reason`。

确定性检索工具不调用LLM。`rerank_retrieval_records` 是独立的随机工具，记录model、API identity、temperature及prompt/input/output digest。

## Consumer规则

Idea 通过 `survey_snapshot_ref`，Paper 通过记录结果中的 `snapshot_ref`，使用共同的验证loader。类型化结果若没有记录引用，不得静默降级到inline papers。

另见 [Research contract](research_contracts.md) 与 [Execution contract](execution_contract.md)。
