---
sources:
  - path: ari-core/ari/public/paper.py
    role: schema
  - path: ari-skill-paper/src/server.py
    role: implementation
  - path: ari-skill-paper/src/finalize.py
    role: implementation
  - path: ari-skill-paper/src/claim_links.py
    role: implementation
  - path: ari-core/ari/schemas/paper_build_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/paper_model_call_batch_v1.schema.json
    role: schema
last_verified: 2026-08-02
---

# 论文构建契约

`PaperBuildV1` 是 ARI 所撰科学论文的不可变记录。JSON Schema 发布于
`ari-core/ari/schemas/paper_build_v1.schema.json`；Skill 可从 `ari.public.paper` 使用稳定的
Python import。

## 构建生命周期

1. `write_paper_iterative` 验证同一 `WorkspaceRefV1` 下的原生证据，保存每次 authoring call，
   并写入 `.ari-paper/paper_build.draft.json`。
2. 文本、视觉、语义与 hard-gate review 相互独立运行。
3. `paper_refine` 仅应用唯一的替换，且该替换必须原样保留每条 `% CLAIM:` 声明
   （marker 及其 `metric=`、`formula=` 与 operand token），并使每个 renderer
   所有的 figure environment 保持逐字节不变；随后保存 digest-bound 的
   `PaperModelCallBatchV1`。
4. 以确定性方式注入代码可用性说明。
5. 对注入后的确切 TeX 重新执行 claim link、semantic review、hard gate 与编译。
6. `finalize_paper_build` 重新计算并验证 evidence graph，然后写入状态为 `finalized`、`blocked`
   或 `compile-error` 的 `paper_build.json`。

只有 `finalized` 才表示科学论文构建成功。blocked record 会在 MCP tool 报告失败前持久化，
因此失败原因仍可审计。

## 必需证据

authoring input set 包含以下唯一角色：

- `science-data` — 原生且 digest-bound 的 `ScienceDataV1`；
- `figure-batch` — fixed-renderer 的 `FigureBatchV1`；
- `retrieval-records` — 可通过 `snapshot_ref` 重放 snapshot 与 cassette 的
  `ari.retrieval-result/v1`；
- `ear-manifest` — 带 `evidence_index_digest` 的 EAR 生成结果；
- `template` 与 `rubric` — 为本次构建选定的确切字节。

finalization 会重新读取每个输入，并将大小和 SHA-256 与 draft record 比较。因此 authoring 后
更改输入属于 hard error。

当 `ARI_MANUSCRIPT_RUNTIME_MODE=enforce` 时，还额外要求 `manuscript-profile`、
`manuscript-context`、`manuscript-readiness`、`section-briefs` 与
`manuscript-authoring-binding` 这几个角色，各自通过对应的
`ARI_MANUSCRIPT_*_PATH` 提供。若 profile、context、readiness、brief-bundle 与
binding 的 digest 不构成同一条 lineage，或 readiness 不是
`ready`/`ready_with_disclosures`，authoring 会拒绝该 bundle；finalization 则针对
draft 的 `build_id` 与 `run_id` 重新校验同一条 lineage，并在 readiness 的
publication verdict 不为 `ready` 时 block 该构建。该模式默认为 `off`，默认
pipeline 不提供上述任何输入。

## Revision 与模型 provenance

每个 revision 绑定其直接 parent，并记录：

- 确切的 TeX 与 BibTeX 工件；
- 原因及关联的 model-call ID；
- claim anchor、citation key、canonical figure ID 与 math digest。

每个随机调用都保存独立的 `prompt` 与 `raw-model-response` 工件，以及 provider、model、可选的
immutable revision、sampling 值、token count 和报告成本。multi-pass refinement 使用
`PaperModelCallBatchV1`；每个网络调用仍是独立 item。

若最后一次 transformation 丢失已准入的 anchor、citation、figure，或改变数学内容，finalizer
将拒绝 finalize。早期单次 refinement-call record 的 published reader 保持只读；新 producer
始终输出 batch schema。

## Claim coverage

共享词法 parser 是 `ari.public.latex_claims`。paper 特有绑定位于
`ari-skill-paper/src/claim_links.py`，输出含以下内容的 `ari.paper-claim-links/v1`：

- final TeX digest；
- resolved/unresolved anchor；
- 分类后的 numeric mention 与未覆盖的 result mention；
- writer 声明的 formula operand；
- canonical figure reference；
- 完整 document digest。

位于与 FigureBatch 绑定的 figure environment 内的 numeric mention 会被归类为
`figure_evidence`，不承担 anchor 义务：该 caption 文本已由 `FigureBatchV1`
拥有并计入 digest。它们仍保留在 `numeric_mentions` 中以供审计。

finalization 不信任该中间结果，而是从 locked ScienceData、FigureBatch 与 final TeX 重新计算完整
document。finalized build 的 unresolved anchor 与 uncovered numeric result mention 均为零。
显式 numeric exclusion 需要内容寻址的 exclusion policy；默认 pipeline 不建立 exclusion。

## 独立审查集合

`PaperReviewSetV1` 分别保留四类工件：

- 独立 text review；
- 独立 VLM figure review；
- evidence-grounded semantic review；
- deterministic hard-gate report。

text review 必须绑定 authoring revision 并保留原始 model response。每个 VLM target 必须匹配确切的
FigureBatch manifest/artifact 及其字节。semantic review 的 evidence digest 必须匹配确切的 final
TeX、ScienceData projection、claim-link document 与 hard-gate digest。aggregate score 不能替代
这些记录。

## 编译策略

compiler 只接受固定命令名 `pdflatex` 和 `bibtex`、安全的 root-level main file、canonical
`refs.bib`，以及 `FigureBatchV1` 声明的 graphics。它始终添加 `-no-shell-escape`，并在执行前拒绝
TeX process/file I/O、`input`/`include`、`filecontents`、absolute/traversal path 与未声明 graphics。

编译使用公共 `ExecutionRequestV1` 的 process-group 与资源上限。每个 pass 保留完整 stdout/stderr
工件与 execution identity。timeout、cancellation、工具缺失、非零退出、PDF 缺失和 PDF digest
mismatch 均不能成为 completed compile。

## Rubric migration

论文 authoring 与 review 要求显式 `rubric_id`。它们不读取 `ARI_RUBRIC`、不猜测 `neurips`，也不会在
rubric 缺失后静默 fallback。`ARI_RUBRIC_DIR` 仍作为位置 override。

对于旧 launch document，运行 `src.rubric_migration.migrate_legacy_rubric_selection`。它只解析一次旧
explicit field、`ARI_RUBRIC` 或历史默认值，验证 rubric，并返回带 `paper_rubric` 与 version/digest
migration ledger 的配置。runtime authoring 不调用此 helper。

## 已删除 runtime 路径与回滚

版本 0.3.0 删除了逐 section 的 authoring runtime、通用 node-tree metric discovery、模型 figure
inserter、重复 LaTeX parser、caller 指定 compiler path 与 raw subprocess compilation。已注册的 tool
中不再有任何 section 级入口：`write_paper_iterative` 撰写整篇 document，`review_compiled_paper` 按
rubric 审查整篇 document，revision 由 `paper_refine` 执行——它应用 `merge_reviews` 输出的
`suggested_revisions`；即使某条 revision 标注了 `section`，编辑仍以保留 anchor 的定向替换落在同一份
manuscript 上。metric 来自原生 `ScienceDataV1` 契约，figure 来自 fixed renderer，claim 解析来自共享
parser，编译来自公共 execution contract。

回滚边界是最后一个 v0.2.0 paper Skill commit。已发布的 `PaperBuildV1`、legacy rubric migration 与
pre-batch call reader 作为 data reader 保留；replay 不会恢复已删除的不安全 producer 路径。

## 验证

```bash
PYTHONPATH=ari-core pytest -q ari-skill-paper/tests
ruff check ari-skill-paper/src ari-skill-paper/tests
python scripts/sync_skill_metadata.py
python scripts/snapshot_contracts.py --surface public --check
python scripts/snapshot_contracts.py --surface mcp --check
```
