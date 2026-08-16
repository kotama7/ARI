---
sources:
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_tools.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/PaperBench/PaperImportDialog.tsx
    role: implementation
last_verified: 2026-08-16
---

# 导入外部论文

论文注册表 (`{ARI_PAPER_REGISTRY_DIR or {workspace_root}/paper_registry}/`)
保存可供 PaperBench 向导审计的外部论文。本页介绍 4 种导入路径与许可证
处理。

## 存储布局

```
{ARI_PAPER_REGISTRY_DIR or {workspace_root}/paper_registry}/
├── manifest.jsonl            # 每行一篇论文 (JSON)
├── jobs/
│   └── <job_id>.json         # 持久化的运行记录 (权限 0600)
└── papers/
    └── <paper_id>/
        ├── paper.pdf         # 运行开始前必须存在
        ├── ad.pdf            # 工件描述 (可选)
        └── ae.pdf            # 工件评价 (可选)
```

设置了 `ARI_PAPER_REGISTRY_DIR` 时取该值,否则取
`PathManager.from_env().paper_registry_root` —
即 `{workspace_root}/paper_registry`,其中 workspace 根目录由
`ARI_CHECKPOINT_DIR` 推断,推断不出时回退到当前工作目录。它**不在**
`~/.ari/` 之下: v0.5+ 的 ARI 不再维护全局的用户级数据目录。

import 端点把 `paper.pdf` 描述为可选,但它是运行的硬前提: 向导 worker
会在第一个 stage 之前以
`"paper.pdf missing under …; cannot launch PaperBench"` 中止。

## 导入路径

### arXiv ID

最常用的路径。向导设置 `source_type=arxiv`,`source=2404.14193`。
元数据自动抓取已经落地 — 导入表单的 **「↓ 抓取元数据」按钮**
(以及 `GET /api/paperbench/arxiv/<id>`) 查询 arXiv Atom API,返回
`title`、`authors`、`year`、`license: "arXiv non-exclusive"`、`summary`、
`pdf_url` 与 `abs_url`。新式 (`2404.14193`、`2404.14193v2` — 版本后缀会
被去掉) 与旧式 (`cs.LG/0102030`) id 都接受,并允许可选的 `arxiv:` 前缀。

但 **PDF 仍然不会被抓取**: 响应里带回 `pdf_url`,没有任何代码去下载它。
请自行通过下面的 upload 路径附上 `paper.pdf`,否则运行 worker 会中止。

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "arxiv",
    "source": "2404.14193",
    "title": "LLAMP: assessing latency tolerance",
    "license": "CC BY 4.0",
    "authors": ["Alice", "Bob"],
    "year": 2024,
    "venue": "SC24",
    "artifact_url": "https://github.com/spcl/llamp"
  }'
```

### DOI

与 arXiv 同样的表单,设置 `source_type=doi`,
`source=10.1109/<conf>.YYYY.NNNNN` 格式
(例:ACM DL 或 IEEE Xplore 上的 SC / OSDI / USENIX 论文的 DOI)。
用于不在 arXiv 上的 IEEE / ACM 论文。

### Upload (本地 PDF)

`source_type=upload`。先用 `/api/upload` 暂存 PDF,然后将其路径作为
`pdf_path` 传入:

```bash
TMP=$(curl -F 'file=@./mypaper.pdf' http://localhost:8765/api/upload | jq -r .path)
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d "{
    \"source_type\": \"upload\",
    \"source\": \"local-upload-$(date +%s)\",
    \"title\": \"My SC24 camera-ready\",
    \"license\": \"IEEE Author proprietary\",
    \"pdf_path\": \"$TMP\"
  }"
```

PDF 会被复制到 `papers/<paper_id>/paper.pdf`。AD / AE 附录通过
`ad_pdf_path` / `ae_pdf_path` 走同一条路径 — 但注意其中的不对称:
`paper.pdf` 复制失败会以 `{"error": "could not copy paper PDF: …"}`
中止整个 import,而 AD/AE 复制失败只写一条日志,import 照样成功,只是
没有这两个文件。

### Local path

`source_type=local`。用于磁盘上已有、不需要 ARI 重新托管的 PDF。注意
`source` 是原样存储的,永远不会被当作路径解释 — 只有 `pdf_path` 才会把
文件复制进注册表。因此没有 `pdf_path` 的 `local` 条目不存在
`paper.pdf`,也就无法运行;想让运行能启动,请传入指向磁盘 PDF 的
`pdf_path`。

## 许可证分类

许可证字符串经过规范化 (小写、去空白) 并分类为
`{permissive, modifiable, redistributable, usable, note}` 评估:

| 状态 | 示例 |
|---|---|
| **usable** (宽松 AND 可再分发 AND 非 non-commercial) | MIT, Apache-2.0, BSD-2/3-Clause, CC0, CC BY, CC BY-SA, arXiv 非独占 |
| 仅宽松 (NOT redistributable) | CC BY-NC — 标注 *"non-commercial ⚠ NOT usable — CC BY-NC restricts commercial reuse"*,因为 ARI 下游可能被商业使用 |
| **NOT usable** | 专有、 IEEE Author、 ACM Author、 "All rights reserved"、未知字符串,以及空/缺失的许可证 |

`modifiable` 比 `permissive` 更窄: `arXiv non-exclusive` 可再分发但不可
修改。

分类是启发式 (**仅供参考**)。最终法律审查仍是用户的责任。GUI 对
usable 显示绿色 ✅ 徽章,对 not usable 显示 ⚠ — 两种都允许注册。

查看论文许可证评估:

```bash
curl http://localhost:8765/api/paperbench/papers/<paper_id>/license
```

## 重复检测

同 `paper_id` (默认: sanitize 的 `source`) 的 import 在没有
`overwrite=true` 时会被阻止:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "arxiv", "source": "2404.14193",
    "title": "LLAMP v2", "license": "CC BY 4.0",
    "overwrite": true
  }'
```

冲突是写在 body 里而不是状态行里的: 响应为 HTTP 200,内容是
`{"error": "paper_id already registered: <id>", "paper_id": …,
"existing": <当前的 manifest 条目>}`。带 `overwrite=true` 时 manifest
条目是**整条替换**而非合并 — 你没写的字段会丢失。论文目录会被复用,
因此已有的 `paper.pdf` 除非被新的 `pdf_path` 覆盖,否则保留。

`paper_id` 本身会被规范化为 `[A-Za-z0-9._-]` (其他字符变 `-`),并截断到
64 字符。空 id 会变成随机的 12 位十六进制 UUID4 片段。

## 删除

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/<paper_id>/delete
```

idempotent (未知 id 返回 `{deleted: false, reason: "not found"}`)。模块
docstring 至今仍写着 `DELETE /api/paperbench/papers/<paper_id>`,但实际
只路由了上面的 `POST …/delete` 形式。

删除会移除 manifest 条目并 `rmtree` `papers/<paper_id>/`,连同其下的
`runs/<job_id>/` sandbox 一起删掉。`{registry_root}/jobs/` 里持久化的
作业记录不受影响。

## 元数据 patch

不丢失注册槽的修字:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/<paper_id>/metadata \
  -H 'Content-Type: application/json' \
  -d '{"venue": "SC25", "year": 2025}'
```

`paper_id` 不可变 — 合并之后它会从 URL 重新盖章写入,因此 body 里的
`paper_id` 会被忽略。patch `license` 会重跑 `_classify_license`,存入
小写化后的字符串以及一份新的 `license_assessment`。

## 相关

- [PaperBench GUI 指南](paperbench_gui.md)
- [API 参考](../../reference/api_paperbench.md)
