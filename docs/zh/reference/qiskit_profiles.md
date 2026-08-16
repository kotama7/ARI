---
sources:
  - path: ari-skill-tool-registry/src/qiskit_contracts.py
    role: schema
  - path: ari-skill-tool-registry/src/qiskit_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_local.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_remote.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_results.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_verification.py
    role: implementation
  - path: ari-skill-tool-registry/providers/qiskit-support-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/qiskit/core-0.3.1+aer-0.17.2-local-ideal/verified-lock-v1.json
    role: config
last_verified: 2026-08-17
---

# Qiskit 与 IBM Quantum 实验配置

ARI 把 Qiskit 作为联邦工具注册表中的不可变实验配置，而不是逐个添加上游工具包装器。
它不把上游 MCP 集合当作科学权威（上游 MCP 的知名度或连接成功也不等于科学有效性），
也不为每个上游工具注册一个 ARI wrapper。一个经审核的 source 可以包含多个
profile，而模型仍只看到注册表的五个稳定操作。

## 信任边界

当前的 support record（`qiskit-support-v1.json`）固定官方
[Qiskit MCP 仓库](https://github.com/Qiskit/mcp-servers)
的完整 commit、provider wheel/source archive、许可证、依赖锁、完整安装包文件树和精确的
MCP 工具契约；此外单独固定 Qiskit 2.5.1、Qiskit Aer 0.17.2 和 Qiskit IBM Runtime 0.48.0。
使用前会验证所选解释器、包文件树、distribution、入口点、架构和 policy environment。
版本范围、被修改的安装、替代 module、运行时下载以及非预期的工具契约都不会被准入。

这些检查只确立软件身份和协议一致性，而非物理正确性。科学 admission 还要求封闭实验、
声明的局限、统计边界、精确的 validation/replay 证据和领域审核。相关的上游一手资料包括
[Qiskit MCP 仓库](https://github.com/Qiskit/mcp-servers)、
[IBM MCP 服务器指南](https://quantum.cloud.ibm.com/docs/en/guides/qiskit-mcp-servers)、
[Qiskit QPY API](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qpy)，以及 support record
所 pin 的各 distribution 的官方 PyPI 发布页。

唯一正式 promote 的 identity 是
`qiskit/core-0.3.1+aer-0.17.2-local-ideal`，verified lock digest 为
`sha256:57b60bbdb84ba0364e038a6df51f3de2a48cdf8c776d31066efeec5ea68be195`。
其 scope 仅为在 `ari.quantum.sample.local-ideal/v1` 之下执行无需 credential 的
seeded Bell-state Aer 运行，并以 digest 固定 QPY、target、software、seed、count
范围、live MCP schema、golden/replay、十五项 Provider gate 与 human approval。IBM Runtime、
remote simulator 和 IBM hardware 仍为 candidate，因为尚无 admitted credential、精确 live
backend/configuration/calibration identity 及 backend-bound golden/replay evidence；local
promotion 不能授予 remote authority。promotion 不等于 Provider activation；committed 的默认
`CATALOG.lock` 保持为空，每个 run 必须显式冻结已审核的 Provider Lock 和 Capability Binding Lock。

官方 core MCP 契约做的是电路分析/转换与 transpile，而不是仿真；官方 Runtime MCP 契约
包含账户管理操作。ARI 不直接暴露其中任何一个契约：它在内部只使用经审核的最小 leaf，
并在一个独立的固定 worker 中实现本地 Aer 执行。

## 能力分离

| backend | capability | 所需 identity | 可复现性含义 |
|---|---|---|---|
| `local-ideal` | `ari.quantum.sample.local-ideal/v1` | Aer method、precision、线程、target、seed | 无噪声模型、带 seed 的软件模拟 |
| `local-noisy` | `ari.quantum.sample.local-noisy/v1` | ideal 的全部字段 + 精确噪声模型 | 对所声明噪声模型的带 seed 模拟（不是硬件预测） |
| `remote-simulator` | `ari.quantum.sample.remote-simulator/v1` | Runtime 的 backend/target/access tier 与 live 快照 | 远程服务上的随机结果 |
| `ibm-hardware` | `ari.quantum.sample.ibm-hardware/v1` | 硬件 target、校准快照与 mitigation | 对一个实时校准 backend 的随机测量 |

broker 在调用或 replay 时不会用一行替换另一行。共享 backend kind/name、target 和软件栈的
profile 属于同一 independence group，多个包装器或重复作业不能算作独立方法的一致证据。

## 封闭实验契约

`QiskitExperimentV1` 固定：

- canonical QPY 字节、SHA-256、QPY format 字节、生成它的 Qiskit 版本、qubit/classical bit 数，
  以及每个带 `rad` 或 `1` 单位的 parameter binding；
- preset pass manager、optimization level、transpiler seed 和可选的 initial layout；
- target 的 qubit 数、排序去重后的 basis gates、有向 coupling map，以及仅由这些字段导出的摘要；
- shots 和预期 bitstring 概率区间（含未列出概率质量的上限）；
- local profile 还固定 Aer 版本、method、precision、CPU/线程上限、simulator seed，以及
  「无噪声」或完整声明的噪声模型；
- remote profile 固定 Runtime 客户端版本、backend/version、不透明的 instance 摘要、
  access-tier ID、校准要求和 mitigation 选项；
- 精确的 golden 与 replay 证据文件、limitations、timeout 和轮询间隔。

QPY header 校验可防止由另一个 Qiskit 版本生成的文件静默地沿用旧的 profile identity。
经审核的 Runtime provider 无法通过其 sampler 契约传递 parameter binding，因此带 binding 的
remote profile 会校验失败，而不会被静默重新绑定。

调用时唯一的输入是一个有界且安全的 `request_id`。它是幂等键，不是科学输入。circuit 字节、
backend、shots、路径、provider 操作和环境都不能被调用者覆盖。

## 执行与来源

local 执行遵循如下封闭序列：

1. 重新检查 QPY、profile 证据、provider 字节和精确的 distribution。
2. 按声明的 basis/coupling 与 optimization level 请求官方 core MCP 做 transpile。
3. 校验并保存返回的 transpiled QPY。
4. 以最小环境和精确的 distribution 版本断言启动固定的本地 worker。
5. 按声明的 method、precision、线程、shots、seed 与噪声执行 Aer；校验 counts 与统计上限；
   发布归一化与原始 artifact。

remote 执行为每个作业打开一个隔离的 Runtime MCP 会话：

1. 注入受限 token 并选择经审核的 channel，不暴露账户发现与账户删除类 leaf。
2. 确认不透明的 instance identity；采集 backend properties、coupling 与 calibration；
   拒绝 backend、target 或 simulator/hardware kind 不匹配。
3. transpile 封闭电路，提交声明的 sampler 请求，并返回一个公共异步 handle。
4. 把 provider 状态映射为 submitted/running/completed/failed/cancelled。超时会请求取消；
   与提交竞态的取消会在得知 provider job ID 后完成，不遗留孤儿作业。
5. 在发布最终 envelope 前校验 backend、target、shots、结果类型/结构、bitstring、counts 与声明的
   统计边界；任一不匹配即 fail closed。

每一个原始 properties/calibration/submission/status/result 响应都有按角色区分、以摘要为前缀的
artifact 名称。这可以避免用于不同
角色的相同字节混淆 artifact 身份。稳定的 backend 快照摘要排除易变的 capture time、队列数
与运行状态，但仍保留带时间戳的原始响应。结果记录 circuit／transpiled circuit／target／
software／method／backend 快照／calibration／job／result 的身份以及归一化 counts。

## 凭据处理

该适配器接受的唯一凭据是 `QISKIT_IBM_TOKEN`，须通过 Skill 的 `quantum.ibm-runtime`
credential scope 声明。不得写入 `sources.yaml`、profile、launcher 的 `literal_env`、
CLI 参数、lock、notebook、fixture 或 checkpoint。

core provider 与 local worker 永远收不到它；只有 Runtime 子进程通过最小环境桥接获得它。
精确的 secret 值在越过 provider 边界之前，会从 MCP 文本、structured content、diagnostic、
exception 和 stderr 中脱敏。source 与 lock 的 identity 不记录任何 token 值；IBM instance 由
不保存原始 CRN，只以经运维审核的摘要和 access-tier ID 作为 identity。record/replay 文件必须
通过同样的「不存在」检查。

## 证据、replay 与解释

`ari.qiskit-golden/v1` 绑定 profile ID、experiment 摘要与已校验 counts；
`ari.qiskit-replay-fixture/v1` 还绑定调用参数、method 摘要、shots 与完成的 normalized result。
两个文件都必须存在并与声明的 SHA-256 相符；只带摘要的 metadata 不足以准入。

record 模式还会额外记录真实的原始 artifact，以及精确的 catalog 与 policy 选择。replay 要求
相同的不可变工具身份，并在没有 provider 包、network、IBM 凭据或 backend 访问的情况下返回
已记录的结果。replay 展示的是保持来源的分析，而不是「实时量子 backend 会复现同样的随机
counts」。

Bell/GHZ fixture 行使带 seed 的 ideal 与 noisy 本地执行。统计边界是 profile 的一部分，必须
针对预期主张给出理由。通过它们并不等于验证了任意电路、新的噪声模型、另一个 backend、
更晚的校准，或更大的研究结论。

## 运维流程

从 `ari-skill-tool-registry/providers/qiskit-source.example.yaml` 开始，并使用一个隔离的
精确环境。可选依赖组只是便利性的 pin；生产用的 provider 环境应当被构建并作为不可变的
审核证据保留。

```bash
cd ari-skill-tool-registry
python scripts/verify_qiskit.py \
  --core-python /absolute/qiskit-env/bin/python \
  --core-package-root /absolute/qiskit-env/lib/python3.13/site-packages/qiskit_mcp_server \
  --experiment /absolute/local-profile.yaml \
  --smoke --run-profile bell-local-ideal \
  --artifact-root /absolute/verification-artifacts
python src/sync_catalog.py
python src/sync_catalog.py --approve --approve-schema-changes
```

对 Runtime profile 需同时加上 `--runtime-python` 与 `--runtime-package-root`。只有当
`--run-profile` 指名一个 remote profile 时，远程 smoke 检查才可能消耗配额或提交作业；
仅做包/profile 验证不会提交任何作业。

审核 pending catalog diff 中的 capability、backend lineage、independence group、permission、
schema、evidence 和 limitations。批准是在活动 run 之外的运维动作。promote 之前请运行注册表
测试、生成契约检查、manifest 检查、凭据脱敏测试与离线 replay。

## 更新、rollback 与删除 gate

provider、Qiskit、Aer、Runtime、backend target、mitigation 或电路的更新都会创建新的不可变
support/profile identity。绝不要修改历史 support record 使其指向不同的字节。要重建隔离环境、
审核上游 diff 与许可证、重新生成 tool／package-tree／contract 摘要、重跑科学 fixture，并批准
由此产生的 catalog/schema diff。

rollback 选择旧的 support record、环境、profile、QPY/evidence、catalog lock 和 cassette。
必须先协调每一个已提交的 remote handle；rollback 无法免除对一个 live provider 作业的责任。

退役一条 Qiskit support line 的 gate 包括：active catalog 引用为零、remote job 已终止或已协调、
替换/迁移说明、在没有 provider 的情况下成功 replay 其已发布的 cassette，以及保留 support
窗口所需的 reader。只有满足这些之后，才可以移除 provider 环境和不可达的 adapter 分支。
只要已发布证据仍依赖它们，QPY、result、cassette 与迁移 reader 就继续保留。
