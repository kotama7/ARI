---
sources:
  - path: ari-core/ari/manuscript/coordinator.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-core/ari/manuscript/state.py
    role: implementation
  - path: ari-core/ari/manuscript/builder.py
    role: implementation
  - path: ari-core/ari/manuscript/readiness.py
    role: implementation
  - path: ari-core/ari/cli/manuscript.py
    role: implementation
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
  - path: scripts/manuscript_complete_release_gates.json
    role: config
  - path: scripts/run_manuscript_complete_release.py
    role: implementation
last_verified: 2026-08-09
---

# Manuscript Complete 的迁移与回滚

legacy 检查点绝不会被追溯地宣告为 complete。

- `off` 不执行任何迁移，也不创建 `.ari-manuscript` 目录。
- `audit` 惰性地清点仍然存在的文件。历史缺口保持为 `missing` 或
  `unavailable`，不会被重建成成功的事实。
- `enforce` 要求在新的 authoring 之前有一份重新生成的当前 profile/readiness，
  在 lock 之前有一份重新生成的 publication 决定。

推荐的迁移流程：

1. 原样复制或保留 legacy 检查点。
2. 运行 `ari manuscript compile CHECKPOINT --mode audit`。
3. 检查 omission、negative lane 以及未解决的 requirement。
4. 选择明确的 recovery、retrieval、experiment、certification、disclosure
   或 human action。绝不要为了制造证据而修改旧的论文/build。
5. compile 一次 enforce attempt，只有在就绪时才撰写新的 bound build。
6. 把旧论文作为 legacy artifact 保留；不要用新的决定覆盖它的历史 status。

回滚把配置改回 `off`。追加式的 attempt 会为取证保留，并可随检查点一起归档。
回滚绝不能删除 repair 失败、被 block 的 draft，或旧的 publication 决定。

已知的 legacy 信息丢失包括 bounded 的 configuration、claim、reference、source
与 prompt 投影。audit 报告仍然可观测的内容，并在可能时报告一个 omission
原因；历史字节的缺失并不能证明某一项从未存在过。

永久的演练是 `ari-core/tests/test_manuscript_complete.py` 中的
`test_legacy_migration_and_rollback_are_additive`。它验证：off 不创建任何
Manuscript state，audit 记录缺口，历史不可验证时 enforce 保持 block，以及回滚
保留此前的每一次 attempt 与逐字节一致的 legacy 论文。发布清单会执行这个测试
并保留它的日志；不要用手工编辑的迁移检查清单取代它。
