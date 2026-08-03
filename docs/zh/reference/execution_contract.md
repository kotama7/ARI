---
sources:
  - path: ari-core/ari/execution.py
    role: implementation
  - path: ari-core/ari/container.py
    role: implementation
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-core/ari/schemas/measurement_set_v1.schema.json
    role: schema
last_verified: 2026-08-02
---

# 执行与测量契约

ARI 通过 `ari.public.execution` 统一工作区、本地或容器进程、完整日志与科学测量；
调度器生命周期仍由 `ari-skill-hpc` 负责。

## 封闭工作区

`WorkspaceRefV1` 固定一个规范化绝对根目录，拒绝 `..`、根目录外绝对路径和符号链接
逃逸。读写通过目录文件描述符及 `O_NOFOLLOW` 遍历每个路径分量；写入使用私有临时
文件、`fsync` 和原子重命名。系统不会把被拒绝的路径悄悄改成 basename。

这只是 ARI 工具及其声明输入/产物的文件访问边界，并不是任意子代码的主机文件系统
沙箱。不可信任为 ARI 服务账号权限的代码必须使用经审查的容器、调度器隔离或其他
操作系统沙箱；执行记录不得声称比所选 substrate 更强的隔离。

## 执行请求与结果

`ExecutionRequestV1` 只允许结构化 `argv` 或显式 `shell_command` 二选一，并记录
workspace、timeout、最小环境、CPU/memory/process/output 限制、网络策略、输入
digest 和容器身份。声明的脚本在启动前验证 SHA-256，并由私有不可变快照执行。

父进程环境不会整体复制。主机无法证明 `network: deny` 时请求会被拒绝；容器仅在
精确 argv 含 Docker 或 Apptainer/Singularity 网络隔离时记录 deny。容器使用 clean
environment，未知 runtime 不会静默降级到主机。

`execution_identity` 是请求的规范 digest，重试时不变；`attempt_id` 每次启动唯一。
timeout/cancel 会终止并回收整个进程组。请求的限制与 `limit_report` 中实际由
kernel/executor 强制的限制分开记录，无法强制的请求 fail closed。

请求字段 `network` 也与执行结果 `network_report` 分离；后者只能是 `inherited`、
`isolated` 或 `external-unverified`。因此外部 launcher 的归一化结果不能把请求的
deny 静默升级成已经验证的网络隔离。

内联 stdout/stderr 只是有界预览。完整字节流始终以 digest 和 size 写入
`.ari-execution/` 的 content-addressed artifact。

## 测量

`MeasurementSetV1` 将 parameter、measurement、prediction、score 放入互不重叠的
命名空间。每个 `MeasurementRecordV1` 保存有限数值、显式单位或
`unit_status: missing`、provenance、parameters、execution identity/status/exit code
、execution attempt 以及证据 artifact digest。系统不推断单位或来源。

`coding-skill.emit_results` 只在 `measurement_set` 中写 canonical object。非有限值或
无法表示为 JSON 的值会被拒绝，而不会被强制转换为字符串。公共 parser 仍把旧 v1 或
无版本文件作为只读迁移输入；历史混合文档若同时携带两种表示，则会交叉核对并拒绝
split-brain 值。

只有至少存在一条测量，且所有测量都有单位、成功的 zero-exit execution identity 和
证据 artifact 时，coding-skill 才返回 `scientifically_admissible: true`。这只是完整性
前提，不能替代后续 evaluator 的领域与 claim 验证。

execution context 还包含不可猜测、由服务器签发的 receipt。写入时会把 receipt 与
workspace、execution attempt、status、exit code 和 artifact 列表逐项核对，并重新计算
每个 artifact 的 hash。伪造 context、服务器会话结束后失效的 receipt 或已修改日志都会
在写 results file 前 fail closed；receipt 本身不会写入科学记录。

规范生成 schema 为 `workspace_ref_v1.schema.json`、`execution_request_v1.schema.json`、
`execution_result_v1.schema.json` 和 `measurement_set_v1.schema.json`。运行
`python scripts/sync_skill_metadata.py` 检查 drift。flat writer/coercion 已删除；legacy
reader 保持严格只读，并按 compatibility support policy 的复审节点管理。
