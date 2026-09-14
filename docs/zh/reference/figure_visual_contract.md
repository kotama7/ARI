---
sources:
  - path: ari-core/ari/public/figures.py
    role: schema
  - path: ari-core/ari/public/visual_review.py
    role: schema
  - path: ari-skill-plot/src/server.py
    role: implementation
  - path: ari-skill-vlm/src/server.py
    role: implementation
  - path: ari-core/ari/schemas/figure_batch_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/visual_review_batch_v1.schema.json
    role: schema
last_verified: 2026-08-02
---

# 科学图表与视觉审查契约

ARI 将图表构造与视觉判断分离。`ari-skill-plot` 是渲染图像字节的唯一所有者；
`ari-skill-vlm` 读取不可变工件并报告问题，不会重写工件。稳定的 Python import 由
`ari.public.figures` 与 `ari.public.visual_review` 提供。

## 图表身份

`FigureSpecV1` 是声明式规范。它将精确且有限的数据切片及源工件摘要绑定到字段、单位、
坐标尺度、聚合、不确定性、标题和固定样式配置。它不接受 Python、SVG、shell、路径或
嵌入图像 payload。模型只能提出已准入的字段；所有数值与输出字节均由固定渲染器负责。

`FigureManifestV1` 将规范绑定到 source-data/spec/PNG/PDF 工件，以及包含渲染器、Python、
Matplotlib/backend、平台、字体字节和可选容器身份的 `FigureEnvironmentV1`。由 LLM 规划的
图表还保留确切 prompt 与原始 response。`FigureBatchV1` 要求所有 ID/path/LaTeX/kind map
与各 manifest 一致。

渲染在封闭 workspace 中进行，使用固定 `Agg` backend、受限尺寸与行数以及原子写入。
无 schema 的 legacy manifest 仅由显式离线 reader 接受；新 producer 只生成 v1。

## Feedback lineage

`FigureFeedbackV1` 将一个 review digest 精确绑定到一个 parent manifest 和下一个 revision。
revision 最多两次，保留此前工件，且不得跨 figure ID。重新渲染总会建立新的 manifest 与
batch digest，不会原地覆盖科学证据。

## 视觉审查

每个 `VisualReviewV1` 绑定：

- 目标工件的确切字节、figure/manifest 身份及 context digest；
- 带版本的 criteria-profile ID 与 digest；
- 包含 severity、evidence、suggestion 和可选 region 的结构化问题；
- provider/model/revision、prompt digest、sampling、token/cost 状态，以及内容寻址的原始
  model response；
- 带受限分数的 `completed`，或显式类型化的 artifact/limit/model/schema error。

server 在调用模型前重新读取目标字节并检查大小与摘要。不支持、损坏、过大、缺失或发生变化的
工件都会失败，不能成为空的成功审查。模型 JSON 采用严格验证；格式错误的 response 成为
`schema-error`，同时保留原始字节。

`VisualReviewBatchV1` 使用 `minimum-fail-closed`：每个目标都必须保留，任一目标失败则 batch
score 为零，否则取各项 score 的最小值。publication consumer 必须将该分数与显式的
`VisualCriteriaProfileV1.passing_score` 比较；`PaperBuildV1` 同时记录 observed 与 required score。

## 已删除路径与回滚

runtime 不再执行生成的 plotting code、不再从文件名推断 raster sibling、不接受 inline base64
target、不把无效模型输出视为成功审查，也不在 paper Skill 中临时规范化 VLM 结果。benchmark
中的重复 plotting 已由 canonical renderer 取代。已发布的 v1 契约与隔离的 legacy manifest reader
仍用于 replay；已删除 producer 路径只能通过还原迁移前的组件 commit 恢复，不能通过静默
compatibility fallback 启用。

## 验证

```bash
PYTHONPATH=ari-core pytest -q ari-skill-plot/tests ari-skill-vlm/tests
python scripts/sync_skill_metadata.py
python scripts/snapshot_contracts.py --surface public --check
python scripts/snapshot_contracts.py --surface mcp --check
```
