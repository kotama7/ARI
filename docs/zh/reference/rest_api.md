---
sources:
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_experiment.py
    role: implementation
last_verified: 2026-06-10
---

# REST API 参考

viz 仪表盘服务器（`ari viz` → `ari-core/ari/viz/server.py`）暴露了一个 JSON HTTP API，供捆绑的 Web UI 使用，也可供外部集成访问。端点由 `viz/routes.py` 分发到各领域处理器模块（`viz/api_*.py`、`viz/checkpoint_api.py`、`viz/file_api.py` 等，在第 3B 阶段拆分）。

默认情况下所有端点均无需认证 — `ari viz` 绑定到 `127.0.0.1`，面向本地用户使用。如需对外暴露，请使用 nginx / oauth2-proxy 进行封装。

## 约定

- Base URL：`http://127.0.0.1:<port>`（端口由 `ari viz` 设置默认值）。
- 除非另有说明，所有响应体均为 JSON。
- 错误以 `{"error": "<message>"}` 格式返回，附带非 2xx HTTP 状态码。
- CORS 预检（`OPTIONS`）在 `/api/*` 上宽松处理。

## 实战示例

最常先用到的端点的最小 `curl` 请求/响应示例。示例假设仪表盘运行在默认端口 `8765`。

**读取实时状态：**

```bash
curl http://localhost:8765/state
```

```json
{
  "phase": "bfts",
  "nodes": { "total": 7, "completed": 5, "running": 2, "failed": 0 },
  "model": { "provider": "ollama", "model": "qwen3:8b" },
  "cost": { "usd": 0.0, "tokens": 0 }
}
```

**启动一次运行：**

```bash
curl -X POST http://localhost:8765/api/launch \
  -H 'Content-Type: application/json' \
  -d '{"experiment_md": "# Goal\nImprove GFLOP/s of a dense matmul.\n",
       "profile": "laptop", "provider": "ollama", "model": "qwen3:8b",
       "max_nodes": 8, "max_depth": 3, "workers": 2}'
```

```json
{ "ok": true, "pid": 48213, "checkpoint_path": "workspace/checkpoints/20260526T101500_matmul" }
```

**列出检查点：**

```bash
curl http://localhost:8765/api/checkpoints
```

```json
[
  { "id": "20260526T101500_matmul", "status": "running", "nodes": 7, "review_score": null },
  { "id": "20260520T090000_sort",   "status": "done",    "nodes": 12, "review_score": 0.71 }
]
```

**错误格式**（任意端点，非 2xx）：

```json
{ "error": "no active checkpoint" }
```

## 状态 + 仪表盘

| 方法 | 路径 | 用途 | 来源 |
|---|---|---|---|
| GET | `/state` | 仪表盘实时视图使用的当前 BFTS 状态快照 | `routes.py:211` |
| GET | `/api/gpu-monitor` | GPU 利用率轮询 | `routes.py:654` |
| GET | `/api/resource-metrics` | CPU / 内存 / 磁盘指标 | `routes.py:886` |
| GET | `/api/logs` | 当前运行的最近日志行 | `routes.py:903` |

## 模型 + 技能

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/models` | 发现通过 LiteLLM + Ollama 可用的 LLM |
| GET | `/api/ollama-resources` | 模型所需的内存 / 磁盘 |
| GET | `/api/ollama/<...>` | 代理到本地 Ollama 守护进程 |
| GET | `/api/skills` | 枚举已注册的技能 + 其工具数量 |
| GET | `/api/skill/<skill_name>` | 每个技能的元数据（工具列表、环境变量） |
| GET | `/api/tools` | 跨所有技能的合并工具目录 |
| GET | `/api/scheduler/detect` | `local` / `slurm` / `apptainer` 自动检测 |
| GET | `/api/slurm/partitions` | SLURM 分区列表 |
| GET | `/api/container/info` | 容器运行时探测 |
| GET | `/api/container/images` | 已缓存的 SIF / OCI 镜像 |
| POST | `/api/container/pull` | 拉取 / 构建 `ARI_CONTAINER_IMAGE` 引用的镜像 |

## 检查点浏览

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/checkpoints` | 列出 `ARI_CHECKPOINT_DIR` 父目录下的所有检查点 |
| GET | `/api/checkpoint/<id>/summary` | 运行摘要（目标、节点数、状态、最优指标） |
| GET | `/api/checkpoint/<id>/memory` | Letta 记忆内容 |
| GET | `/api/checkpoint/<id>/memory_access` | 记忆写入/读取遥测数据 |
| GET | `/api/checkpoint/<id>/files` | 含大小 + 类型的文件列表 |
| GET | `/api/checkpoint/<id>/file?path=...` | 原始文件内容（文本或 base64） |
| GET | `/api/checkpoint/<id>/file/raw` | 同上，备用路由 |
| GET | `/api/checkpoint/<id>/filetree` | 层级树形视图 |
| GET | `/api/checkpoint/<id>/filecontent` | 多文件批量读取 |
| GET | `/api/active-checkpoint` | 当前选中的检查点 |
| POST | `/api/switch-checkpoint` | 切换当前检查点 |
| POST | `/api/delete-checkpoint` | 删除检查点（同时删除对应的 Letta 智能体） |
| POST | `/api/checkpoint/file/save` | 原地编辑检查点中的文件 |
| POST | `/api/checkpoint/file/delete` | 从检查点删除文件 |
| POST | `/api/checkpoint/compile` | 对论文草稿运行 `pdflatex` |

## 运行生命周期

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/launch` | 启动新的 BFTS 运行（以编程方式调用 `ari run`） |
| POST | `/api/run-stage` | 运行单个流水线阶段 |
| POST | `/api/stop` | 停止当前运行 |

## 子实验 + 沿袭

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/sub-experiments` | 所有子实验记录 |
| GET | `/api/sub-experiments/<run_id>` | 单个子实验详情 |
| POST | `/api/sub-experiments/launch` | 从父检查点继承启动子运行 |
| GET | `/api/lineage-decisions/<run_id>` | 停滞规则生成的决策（v0.7.0） |

## 记忆后端

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/memory/health` | Letta 健康探测 |
| GET | `/api/memory/detect` | 运行中的 Letta 部署路径清单 |
| POST | `/api/memory/start-local` | 启动本地 Letta 服务器 |
| POST | `/api/memory/stop-local` | 停止本地 Letta 服务器 |
| POST | `/api/memory/restart` | 重启本地 Letta 服务器 |

## 设置 + workflow

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/settings` | 读取 settings.json |
| POST | `/api/settings` | 写入 settings.json |
| GET | `/api/profiles` | 已保存的配置文件列表 |
| GET | `/api/env-keys` | ARI 已知的环境变量键名（不含值） |
| POST | `/api/env-keys` | 将环境变量键/值对持久化到 `.env` |
| GET | `/api/workflow` | 当前 workflow.yaml |
| GET | `/api/workflow/default` | 捆绑的默认值 |
| GET | `/api/workflow/flow` | Workflow 可视化为 DAG 节点 / 边 |
| POST | `/api/workflow` | 保存 workflow.yaml |
| POST | `/api/workflow/flow` | 保存 DAG 视图 |
| POST | `/api/workflow/skills` | 切换启用的技能 |
| POST | `/api/workflow/disabled-tools` | 每技能工具白名单 / 黑名单 |

## 向导 / 配置生成

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/experiment-detail` | 向导解析的 experiment.md |
| POST | `/api/config/generate` | 根据向导回答生成 `ari.yaml` |
| POST | `/api/chat-goal` | LLM 辅助的目标叙述精炼 |
| POST | `/api/ssh/test` | 探测 SSH 集群登录 |

## 上传 + few-shot 语料库

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/upload` | 多部分上传到当前检查点 |
| POST | `/api/upload/delete` | 删除已上传的文件 |
| GET | `/api/fewshot/<rubric_id>` | 某规范的 few-shot 示例 |
| POST | `/api/fewshot/<rubric_id>/sync` | 拉取已发布的语料库 |
| POST | `/api/fewshot/<rubric_id>/upload` | 添加示例 |
| POST | `/api/fewshot/<rubric_id>/delete` | 删除示例 |
| GET | `/api/rubrics` | 可用的评审规范（由 `ARI_RUBRIC` 驱动） |

## 节点报告

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/nodes/<...>/report` | 每节点的 `node_report.json` |

## EAR + 发布（v0.7.0）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/ear/<run_id>` | 某次运行的 EAR bundle 元数据 |
| GET | `/api/ear/<run_id>/publish-yaml` | 生成的 publish.yaml 预览 |
| POST | `/api/ear/<run_id>/curate` | 运行策展步骤 |
| POST | `/api/ear/<run_id>/publish-yaml` | 保存 publish.yaml |
| POST | `/api/ear/clone-verify` | 按哈希校验远程 bundle |
| GET | `/api/publish/settings` | 后端配置 |
| POST | `/api/publish/settings` | 更新后端配置 |
| GET | `/api/publish/<run_id>/preview` | 发布前有效载荷预览 |
| GET | `/api/publish/<run_id>/record` | 读取 `publish_record.json` |
| POST | `/api/publish/<run_id>/promote` | 将 `staged` 提升为 `unlisted` / `public` |
| POST | `/api/publish/<run_id>` | 推送到已配置的后端 |

## 静态文件 + 前端

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/static/<path>` | 捆绑的 UI 资源 |
| GET | `/memory/<path>` | 记忆检查器静态页面 |
| GET | `/codefile?path=...` | 源文件查看器 |

## 更新本参考文档

路由表是 `ari-core/ari/viz/routes.py` 中的分发链 — 添加路由时，请同步更新此处。未来的改进可能会根据分发链自动生成本页（主计划建议出于同样原因生成 OpenAPI）。

## 另请参阅

- `docs/concepts/architecture.md` — viz 包概览。
- `ari-core/ari/viz/__init__.py` — 包含当前子模块映射的模块级文档字符串。
