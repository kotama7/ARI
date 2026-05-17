# 导入外部论文

论文注册表 (`~/.ari/paper_registry/`,可用 `ARI_PAPER_REGISTRY_DIR`
覆盖) 保存可供 PaperBench 向导审计的外部论文。本页介绍 4 种导入
路径与许可证处理。

## 存储布局

```
{ARI_PAPER_REGISTRY_DIR or ~/.ari/paper_registry}/
├── manifest.jsonl            # 每行一篇论文 (JSON)
└── papers/
    └── <paper_id>/
        ├── paper.pdf         # 源 PDF (推荐)
        ├── ad.pdf            # 工件描述 (可选)
        └── ae.pdf            # 工件评价 (可选)
```

根目录可用 `ARI_PAPER_REGISTRY_DIR` 替换。

## 导入路径

### arXiv ID

最常用的路径。向导设置 `source_type=arxiv`,`source=2404.14193`。
点击 **「↓ 抓取元数据」按钮** 触发 `/api/paperbench/arxiv/<id>`,
后端调用 arXiv Atom API 自动填充 title / authors / year / license。

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

`source_type=upload`。先用 `/api/upload` 把 PDF 暂存到 tmp,然后将
路径作为 `pdf_path` 传入:

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
`ad_pdf_path` / `ae_pdf_path` 同理。

### Local path

`source_type=local`。注册磁盘上已有的 PDF 路径,ARI 不重新托管 —
注册条目只指向已存在的路径。

## 许可证分类

许可证字符串经过规范化 (小写、去空白) 并分类为 4 象限评估:

| 状态 | 示例 |
|---|---|
| **usable** (宽松 AND 可再分发) | MIT, Apache-2.0, BSD-2/3-Clause, CC0, CC BY, CC BY-SA, CC BY-NC, arXiv 非独占 |
| 仅宽松 (NOT redistributable) | (当前无 — 占位) |
| **NOT usable** | 专有、 IEEE Author、 ACM Author、 "All rights reserved"、未知字符串 |

分类是启发式 (**仅供参考**)。最终法律审查仍是用户的责任。GUI 对
usable 显示绿色 ✅ 徽章,对 not usable 显示黄色 ⚠ — 两种都允许注册。

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

`paper_id` 本身会被规范化为 `[A-Za-z0-9._-]{1,64}` (其他字符变 `-`)。

## 删除

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/<paper_id>/delete
```

idempotent (未知 id 返回 `{deleted: false, reason: "not found"}`)。

## 元数据 patch

不丢失注册槽的修字:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/<paper_id>/metadata \
  -H 'Content-Type: application/json' \
  -d '{"venue": "SC25", "year": 2025}'
```

`paper_id` 不可变。

## 相关

- [PaperBench GUI 指南](paperbench_gui.md)
- [API 参考](../reference/api_paperbench.md)
