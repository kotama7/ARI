---
sources:
  - path: ari-core/ari/execution.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-paper-re/src/rubric_contract.py
    role: implementation
  - path: ari-skill-paper-re/paperbench_patches.json
    role: config
last_verified: 2026-08-08
---

# Compatibility support policy

兼容路径只有在只读或严格限域、fail closed、有 owner 且具有客观删除 gate 时才保留。
新 producer 不输出退役格式。

| 对象 | 边界与保留理由 | owner | 复审 / 删除 gate |
|---|---|---|---|
| 历史 measurement 文档 | parser 只读旧 flat v1/unversioned，不虚构单位或执行 provenance；writer 只写 canonical。 | ARI core maintainers | v1.1：published checkpoint 使用为零并保留 migration fixture。 |
| 历史 research/retrieval/result/figure/review/paper/EAR artifact | 仅用于 replay、验证或显式迁移，不作为 runtime producer fallback。 | 各 skill maintainer | publication/replay 支持窗口结束后按格式删除。 |
| Letta pip deployment | 支持无容器的本地安装，不是自动 backend fallback。 | ARI maintainers | v1.1 复审 usage 与 issue。 |
| `slurm_submit` bridge | 仅用于 core agent batch-script workflow；新集成使用 `job_submit`/`container_submit`。 | core + HPC maintainers | v1.1：agent 直接生成 `JobRequestV1` 且 caller 为零。 |
| Rubric V1 reader/offline migration | 校验 digest 并无损迁移到 V2；不存在 V1 runtime generator。 | replicate + paper-re maintainers | v1.1：workflow/artifact 使用为零。 |
| PaperBench adaptation | 仅允许 exact pin 与 `paperbench_patches.json` 所列适配，并运行 conformance test。 | paper-re maintainers | 每次 pin 更新；所声明的 `deletion_gate` 条件成立且目标 suite 通过后删除。 |
| Orchestrator registry repair | 只显式导入明显终态的旧 run；禁止自动 discovery/state 推断。 | orchestrator maintainers | v1.1 支持 checkpoint 迁移完成后。 |
| archived lock/cassette | published dispatch replay 所需；校验 digest，且不隐式 admission 到新 run。 | registry/provider maintainers | publication/replay 窗口结束后按格式删除。 |

新增 compatibility writer 或 silent fallback 需要独立 architecture decision。删除时记录
pre-removal commit、changelog、caller 为零以及 owner contract/replay suite。
