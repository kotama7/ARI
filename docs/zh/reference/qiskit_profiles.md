---
sources:
  - path: ari-skill-tool-registry/src/qiskit_contracts.py
    role: schema
  - path: ari-skill-tool-registry/src/qiskit_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_remote.py
    role: implementation
  - path: ari-skill-tool-registry/providers/qiskit-support-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/qiskit/core-0.3.1+aer-0.17.2-local-ideal/verified-lock-v1.json
    role: config
last_verified: 2026-08-05
---

# Qiskit 与 IBM Quantum 实验配置

ARI 把 Qiskit 作为联邦工具注册表中的不可变实验配置，而不是逐个添加上游工具包装器。
上游 MCP 的知名度或连接成功不等于科学有效性。一个经审核的 source 可以包含多个
profile，而模型仍只看到注册表的五个稳定操作。

## 信任边界

`qiskit-support-v1.json` 固定官方 [Qiskit MCP 仓库](https://github.com/Qiskit/mcp-servers)
的完整 commit、provider wheel/source、许可证、依赖锁、完整安装包文件树和工具契约；
同时固定 Qiskit 2.5.1、Qiskit Aer 0.17.2 和 Qiskit IBM Runtime 0.48.0。启动前验证
解释器、入口点、架构、distribution 版本和包字节。版本范围、被修改的安装、替代入口、
运行时下载都会被拒绝。相关一手资料还包括
[IBM MCP 指南](https://quantum.cloud.ibm.com/docs/en/guides/qiskit-mcp-servers) 与
[QPY API](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qpy)。

这些检查只证明软件身份和协议一致性。科学 admission 还要求封闭实验、局限说明、统计边界、
真实的 golden/replay 文件和领域审核。

唯一正式 promote 的 identity 是
`qiskit/core-0.3.1+aer-0.17.2-local-ideal`，verified lock digest 为
`sha256:57b60bbdb84ba0364e038a6df51f3de2a48cdf8c776d31066efeec5ea68be195`。
其 scope 仅为无需 credential 的 seeded Bell-state Aer 执行和
`ari.quantum.sample.local-ideal/v1`，并以 digest 固定 QPY、target、software、seed、count
范围、live MCP schema、golden/replay、十五项 Provider gate 与 human approval。IBM Runtime、
remote simulator 和 IBM hardware 仍为 candidate，因为尚无 admitted credential、精确 live
backend/configuration/calibration identity 及 backend-bound golden/replay evidence；local
promotion 不能授予 remote authority。promotion 不等于 Provider activation；committed 的默认
`CATALOG.lock` 保持为空，每个 run 必须显式冻结已审核的 Provider Lock 和 Capability Binding Lock。

## 能力分离

| backend | capability | 含义 |
|---|---|---|
| `local-ideal` | `ari.quantum.sample.local-ideal/v1` | 无噪声、带 seed 的 Aer 模拟 |
| `local-noisy` | `ari.quantum.sample.local-noisy/v1` | 仅模拟声明的固定噪声模型 |
| `remote-simulator` | `ari.quantum.sample.remote-simulator/v1` | 远程服务上的随机模拟 |
| `ibm-hardware` | `ari.quantum.sample.ibm-hardware/v1` | 具有实时校准快照的硬件测量 |

broker 在调用或 replay 时不会互换这些能力。共享 backend kind/name、target 和软件栈的
profile 属于同一 independence group，多个包装器或重复作业不能算作独立方法的一致证据。

## 封闭实验契约

`QiskitExperimentV1` 固定 QPY 字节/摘要/格式/生成者版本、qubit/classical bit 数、每个
parameter binding 的 `rad` 或 `1` 单位、transpiler level/seed/layout、basis/coupling/target
摘要、shots 和预期 bitstring 概率区间。local profile 还固定 Aer method、precision、CPU
线程、simulator seed 和噪声模型；remote profile 固定 backend/version、不可逆 instance
摘要、access tier、校准要求和 mitigation。

调用者只能提供用于幂等性的 `request_id`，不能改变 circuit、backend、shots、路径、provider
操作或环境。当前审核的 Runtime MCP 不能向 sampler 传递 parameter binding，因此 remote
binding 会失败，不会被静默改写。

local 流程先使用官方 core MCP transpile，再由验证精确 distribution 的隔离 Aer worker
执行。remote 流程只把 token 交给隔离 Runtime 进程，在提交前验证 instance、backend
properties、coupling、calibration、backend kind 和 target。提交立即返回公共异步 handle，
status/result/cancel 映射为 typed state；超时请求取消，submit/cancel 竞态在获得 provider
job ID 后继续协调，避免遗留孤儿作业。

原始 properties/calibration/submission/status/result 以角色区分的内容寻址 artifact 保存。
稳定科学快照摘要排除 queue、operational state 和 capture time，但保留原始带时间响应。
backend、target、shots、结果结构、counts 或统计边界不匹配时 fail closed。

## 凭据、证据与运维

唯一允许的凭据是 `QISKIT_IBM_TOKEN`，必须由 `quantum.ibm-runtime` named scope 提供。
不得写入 `sources.yaml`、profile、launcher env、lock、fixture 或 checkpoint。core MCP 与
local worker 不接收它；只有隔离 Runtime 进程可见。provider 文本、structured response、
diagnostic、exception 和 stderr 在边界内按精确 secret value 脱敏。原始 instance CRN 也不
保存，只记录审核后的摘要和 access-tier ID。

golden fixture 绑定 profile/experiment digest/counts；replay fixture 还绑定 request、method
digest、shots 与 normalized result。必须验证实际文件字节，单独的摘要字符串不能 admission。
replay 在无 provider、network、credential 或 backend access 时工作，表示可追溯的离线分析，
不表示实时硬件会产生相同随机 counts。

从 `ari-skill-tool-registry/providers/qiskit-source.example.yaml` 开始：

```bash
cd ari-skill-tool-registry
python scripts/verify_qiskit.py \
  --core-python /absolute/qiskit-env/bin/python \
  --core-package-root /absolute/qiskit-env/lib/python3.13/site-packages/qiskit_mcp_server \
  --experiment /absolute/profile.yaml --smoke
python src/sync_catalog.py
python src/sync_catalog.py --approve --approve-schema-changes
```

本地验证可加 `--run-profile` 与 `--artifact-root`；远程 profile 还需 Runtime interpreter 与
package root。审核 pending diff 中的 capability、schema、backend lineage、independence、
permission、evidence 和 limitations，并运行凭据脱敏及离线 replay 测试。

provider/Qiskit/Aer/Runtime/backend/circuit 更新必须创建新的不可变 record/profile。
rollback 选择旧 support record、环境、profile、QPY/evidence、catalog lock 和 cassette；
所有 remote handle 必须先终止或协调，不能用 rollback 隐藏 live job。删除 gate 包括 active
reference 为零、remote job 已处理、migration note 完整、无 provider replay 成功；published
evidence 仍依赖的 QPY/result/cassette reader 在支持窗口内保留。
