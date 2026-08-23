---
sources:
  - path: ari-core/ari/research_contract.py
    role: implementation
  - path: ari-skill-idea/src/contracts.py
    role: implementation
  - path: ari-skill-evaluator/src/server.py
    role: implementation
last_verified: 2026-08-16
---

# 研究契约

ARI把从文献检索到实验执行的科学决策冻结为三个immutable record：

1. `SurveySnapshotV1`记录固定provider、query、检索时间、规范化record、citation edge、
   artifact，以及原始live操作是否byte reproducible。
2. `IdeaSetV1`记录model、prompt template digest、sampling、seed、adapter/vendor revision、
   source snapshot、被接纳candidate和确定性的拒绝原因。
3. `ResearchContractV1`只从一个被接纳candidate生成一次，并冻结假说、证伪条件、metric名称、
   unit、direction、comparison scope、required evidence、引用、限制和source digest。

每个record都携带其canonical JSON（不含digest字段本身）的SHA-256，reader在parse时验证。
evaluator逐字使用`ResearchContractV1`，并把同一个`research_contract_digest`写入
`metric_contract.json`；不会用LLM重新命名metric或evidence词汇。

`survey(mode="record")`在故障时不会更换provider。`survey(mode="replay")`不访问network，
只读取指定checkpoint artifact，并拒绝缺失、损坏或digest不匹配的snapshot。

顶层flat `ideas`、`primary_metric`等字段只是旧checkpoint投影。新consumer必须使用typed
record。声明新格式却没有被接纳contract的document会fail-closed，不能降级到旧prose推断。
schema位于`ari-core/ari/schemas/`，稳定公开API是`ari.public.research_contract`。

provider cassette、已验证snapshot ref、URL policy与alias合成规则见
[检索契约](retrieval_contract.md)。
