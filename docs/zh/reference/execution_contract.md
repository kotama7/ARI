---
sources:
  - path: ari-core/ari/execution.py
    role: implementation
  - path: ari-core/ari/container.py
    role: implementation
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-core/ari/schemas/execution_request_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/execution_result_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/measurement_set_v1.schema.json
    role: schema
last_verified: 2026-08-17
---

# 执行与测量契约

ARI 通过 `ari.public.execution` 统一工作区、本地或容器进程、完整日志与科学测量；
调度器生命周期仍由 `ari-skill-hpc` 负责。

## 封闭工作区

`WorkspaceRefV1` 固定一个规范化绝对根目录，拒绝 `..`、根目录外绝对路径和符号链接
逃逸。读写通过目录文件描述符及 `O_NOFOLLOW` 遍历每个路径分量；写入使用私有
文件、`fsync` 和原子重命名。调用方选择的 `work_dir` 只有在通过同一套 containment
policy 之后才会被创建。

这套策略刻意不提供任何"贴心的" basename 回退：被拒绝的路径就是错误，绝不会被改写
成另一个目标。

这只是 ARI 工具及其声明输入/产物的文件访问边界，并不是任意子代码的主机文件系统
沙箱。不可信任为 ARI 服务账号权限的代码必须使用经审查的容器、调度器隔离或其他
操作系统沙箱；执行记录不得声称比所选 substrate 更强的隔离。

## 执行请求

`ExecutionRequestV1` 只允许结构化 `argv` 或显式启用的 `shell_command` 二选一，
此外还包含：

- 规范化的 workspace 与 wall-time 上限；
- 一份最小的显式环境（不复制父进程环境）；
- CPU、地址空间、进程数和输出大小限制；
- `inherit` 或 `deny` 的网络策略；
- 绑定到 SHA-256 摘要的相对输入路径；
- 可选的、不可变或显式未解析的容器身份。

声明的脚本操作数在启动前验证摘要，并被替换为私有的不可变快照。其他已声明的输入
标记为 `verified-at-launch`；结果绝不声称它们被快照过。

主机执行无法证明网络拒绝，因此拒绝 `network: deny`。经审查的容器适配器只有在其
精确 argv 含运行时隔离边界（Docker 的 `--network none`，或 Apptainer/Singularity
对应的网络命名空间）时才能请求拒绝。容器执行使用 clean environment，并拒绝在不受
支持的 runtime 上回退到主机。

## 执行结果

`ExecutionResultV1` 区分两个标识：

- `execution_identity` 是请求的规范 digest，重试时不变；
- `attempt_id` 每次实际启动唯一。

timeout/cancel 会终止并回收整个进程组。请求的限制与 `limit_report`（说明 POSIX
内核/执行器实际强制了什么）分开记录，无法强制的内核控制请求 fail closed。

请求字段 `network` 也与执行结果 `network_report` 分离；后者只能是 `inherited`、
`isolated` 或 `external-unverified`。因此外部 launcher 的归一化结果不能把请求的
deny 静默升级成已经验证的网络隔离。

内联 stdout/stderr 只是有界预览。完整字节流始终以 digest 和 size 写入
`.ari-execution/` 的 content-addressed artifact，消费者无需重跑命令即可恢复并校验
完整输出。

## 测量

`MeasurementSetV1` 将 parameter、measurement、prediction、score 放入互不重叠的
命名空间。每个 `MeasurementRecordV1` 记录：

- 指标身份与一个有限数值；
- 声明的单位，或显式状态 `unit_status: missing`；
- method/source 来源；
- 测量时所处的 parameters；
- execution identity、attempt identity、终止状态与 exit code；
- 支撑该数值的 SHA-256 artifact。

`coding-skill.emit_results` 只在 `measurement_set` 中写 canonical object。非有限值或
无法表示为 JSON 的值会被拒绝，而不会被强制转换为字符串。公共 parser 仍把旧 flat v1 或
无版本文件作为只读迁移输入；历史混合文档若同时携带两种表示，则会交叉核对并拒绝
split-brain 值。缺失的单位与执行证据（含 provenance）保持显式缺失，不会被推断。

只有至少存在一条测量，且所有测量都有单位、成功的 zero-exit execution identity 和
至少一个证据 artifact 时，coding-skill 才返回 `scientifically_admissible: true`。
这只是完整性前提，而非领域有效性判断；评估器的 claim gate 与领域 gate 依然适用。

execution context 还包含不可猜测、由服务器签发的 receipt。写入时会把 receipt 与
workspace、execution attempt、status、exit code 和 artifact 列表逐项核对，并重新计算
每个 artifact 的 hash。伪造 context、服务器会话结束后失效的 receipt 或已修改日志都会
在写 results file 前 fail closed；receipt 本身不会写入科学记录。

## schema 与迁移

生成的规范 schema 为：

- `workspace_ref_v1.schema.json`
- `execution_request_v1.schema.json`
- `execution_result_v1.schema.json`
- `measurement_set_v1.schema.json`

运行 `python scripts/sync_skill_metadata.py` 检查 schema drift。生产方必须输出
canonical measurement set，消费方必须使用 `parse_measurement_document`。flat writer
与强制转换路径已删除；legacy reader 保持刻意的只读，并按 compatibility support
policy 的复审节点管理。
