---
sources:
  - path: ari-core/ari/pipeline
    role: implementation
  - path: ari-skill-paper
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-06-12
---

# 发布生命周期 (v0.7.0)

ARI v0.7.0 把 EAR 从「整盘塞入 ear/」演进为 **digest 锚定的发布链**。作者只需写一个简短的 `ear/publish.yaml`，digest 计算与传输由 ari-core 处理。digest 烧录于论文 (`\codedigest{...}`)，即使发布托管的 registry 消失，任何地方依然可以验证。

```
generate_ear ──▶ {checkpoint}/ear/                 (作者完整 repo)
                  + ear/publish.yaml               (allowlist + license/visibility)
        │
        ▼ ear_curate (transform-skill)
        ▼
{checkpoint}/ear_published/  +  manifest.lock      ({path,sha256,size} 正规化 JSON 的 sha256)
        │
        ▼ ear_publish (transform-skill, 可选)
        ▼
backend.publish ──▶ ari-registry / gh / zenodo / local-tarball
        │
        ▼ 写入 publish_record.json
        │
        │   (并行地, 当 write_paper 产出 full_paper.tex 后,
        │    默认开启的 Story2Proposal claim-evidence 回路对论文正文运行:)
        │
        │   write_paper ──▶ full_paper.tex
        │        │
        │        ▼ link_paper_claims (draft)        ──▶ paper_claim_links.json
        │        ▼ claim_evidence_hard_gate (draft, 非阻塞)
        │        │                                   ──▶ evaluation/claim_evidence_hard_gate_draft.json
        │        ▼ review_paper / evidence_grounded_semantic_review (非阻塞)
        │        ▼ merge_reviews
        │        ▼ paper_refine (保留 anchor — 保留 % CLAIM anchor)
        │        ▼ render_paper (重新编译 refine 后的 .tex ──▶ full_paper.pdf)
        │        ▼ link_paper_claims (final)          ──▶ paper_claim_links_final.json
        │        ▼ claim_evidence_hard_gate (FINAL)   ──▶ evaluation/claim_evidence_hard_gate_final.json
        │        │   (strict 模式下阻塞 finalize)
        ▼        ▼
        └────────┴──▶ finalize_paper (paper-skill: inject_code_availability)
                       依赖 ear_publish 与 FINAL hard gate 两者
        ▼
full_paper.tex 注入 \codeavailability{} \codedigest{} \coderef{}
        │
        ▼ ari clone <ref> --expect-sha256 <baked digest>
        ▼
读者本机：bundle 字节经 digest 校验，无任何代码执行
```

### Claim-evidence 闸门（Story2Proposal 回路）

每次论文构建现在都会在既有论文阶段之上，运行一个确定性的 claim-evidence
**hard gate**、一个非阻塞的 **evidence-grounded semantic review**，以及一个
**保留 anchor 的 refine/render 回路**。该回路把论文的 `% CLAIM` anchor 关联到
已记录的结果（`link_paper_claims`），并与实验数据比对校验
（`claim_evidence_hard_gate`，在 draft 上运行一次、在 refine 后的论文上再运行
一次），把 hard gate 与 semantic review 一并织入合并后的评审，在保留 claim
anchor 的同时应用建议修订（`paper_refine`），并重新编译 refine 后的 `.tex`
（`render_paper`）。其行为由 `ari-core/config/workflow.yaml` 中的
`claim_gate_policy` 块控制，**默认以 `warn`（仅报告）模式开启** —— 闸门只记录
发现，不会阻塞构建。设置 `claim_gate_policy.mode: strict`（或
`ARI_CLAIM_GATE_MODE=strict`）后，**FINAL** 闸门在出现阻塞性错误（数值不匹配、
未解析操作数、缺失证据）时会阻塞 `finalize_paper`。

四个健壮性行为保证该回路端到端诚实：

- **阻塞只保留给客观谬误。**闸门的必阻塞层只包含可确定性检验的发现
  （与运行自身数据相矛盾的数值、不变量违规、在整个运行中找不到任何
  证据的已声明 claim）。主观发现 —— LLM 语义评审的 overclaim 与
  解释性警告 —— 依设计保持仅咨询性：LLM 判定跨运行不可复现，因此
  绝不能拥有否决论文的权力。主观发现的补救途径是上述 review→refine
  回路，通过 refine 后评审的原始已解决计数差值来度量（而非强制）。

- **评审反馈确实落地。**`merge_reviews` 把每条语义评审警告作为咨询性
  修订条目转发给 `paper_refine`（没有并行建议修订的警告永远到不了
  refiner，警告计数也就永远不会下降）。报告的
  `resolved_overclaim_count` 是原始的 previous−current 差值 ——
  负值意味着计数在 refine 后*增长*了，会作为回归被呈现，而不是被
  钳制为零。
- **数值校验理解科学计数法。**数值提及扫描器（镜像存在于
  `ari-skill-paper/src/claim_links.py` 与 ari-core 的
  `claim_gate/latex.py`）解析尾数 × 10^exp 形式
  （`4.44 \times 10^{-16}`，支持 `x`/`\times`/`\cdot`）与贴连的
  e 记法（含句尾形式），保留含数字的 token，并在定位数值单位时把
  `\( \)` 视为数学定界符 —— 消除此类数值上的伪
  `numeric_mismatch` 发现。巨大的指数会被跳过，绝不使闸门崩溃。
- **写手声明在解析时被归一化。**仅靠指令被证明不可靠，因此解析器
  吸收常见的怪癖：公式同义词（`value`、`raw`、`abs`、…）归一化为
  注册表名称；裸 `k=v` token 前多余的 `operands=` 标签前缀被剥除；
  当所有 anchor 共享同一个 id 时（例如每行都盖 `% CLAIM:Cw:NCw`），
  anchor 会被逐行消歧，使每条声明独立校验。
- **指标契约只铸造一次。**第一次产生含 claim 契约的
  `make_metric_spec` 调用会把它持久化为
  `{checkpoint}/metric_contract.json`；之后的每次调用都原样返回该
  文件（响应携带 `contract_frozen: true`）。LLM 命名不具备指称
  稳定性 —— 运行中途重新生成契约会改变证据词汇表，使兄弟节点以
  旧名称发出的证据对精确匹配闸门不可见（在真实运行中观测到）。
  每节点的 spec 字段（评分指南等）仍按调用计算；仅脚手架的契约
  （无 claim）永不冻结。

产物：`paper_claim_links.json`（draft）/
`paper_claim_links_final.json`，以及
`evaluation/claim_evidence_hard_gate_{draft,final}.json`。

信任模型：**信任锚是论文本身，而非 registry**。`ari clone` 会对任何重算 digest
与 `--expect-sha256`（或 `manifest.lock` 声明）不匹配的 bundle 直接 hard-fail。
即使 registry 消失，pin 在其他位置（S3、Zenodo、gh release、本地镜像）的同一
bundle 仍可校验。这属于 **bundle 完整性**（digest 匹配）；FINAL hard gate 再加上
**claim 完整性** —— 它从已记录的结果重新推导论文中报告的数值，并标记任何超出
容差的项。

### `ari clone` resolvers

| Scheme | 解析 | 备注 |
|--------|------|------|
| `file://<path>` | 本地文件/目录 | 离线 / 镜像 |
| `https://<url>` / `http://<url>` | tarball 下载 | 任意 HTTPS host |
| `ari://<id>` | ari-registry 客户端 | 从 `registries.yaml` 读取 endpoint/token。解析顺序：`$ARI_REGISTRIES_FILE` → `{checkpoint}/.ari/registries.yaml` → `./.ari/registries.yaml`。位于 `$HOME/.ari/` 下的遗留位置在 v0.5.0 已被废弃，发出 `DeprecationWarning`，v1.0 中删除回退。 |
| `gh:<user>/<repo>` | GitHub repo / release | API + tarball |
| `doi:<doi>` | Zenodo deposition | DOI → 文件列表 → bundle |

### `ari registry`（可选自托管）

`ari/registry/` 中的极简 FastAPI 服务。SQLite token store，`${ARI_REGISTRY_DATA}/artifacts/<id>/{bundle.tar.gz, manifest.lock, meta.json}` 内容寻址存储。可见性单调可升 `staged` → `unlisted` / `public`（降级被拒）。部署方式：uvicorn (laptop)、docker-compose (production)、Apptainer (HPC)。详见 [docs/reference/registry.md](../reference/registry.md)。

### 可复现性沙箱补强

- **`_run_env.json`** — `ari/agent/run_env.py` 在每个 work_dir 内（在执行进程内部）写入 hostname / SLURM job/partition/nodelist / CPU model/threads/MHz/arch / mem_total / 编译器版本，使 SLURM 作业（运行节点与代理不同）也能保留准确的硬件元数据。`node_report` builder 据此丰富报告，下游阶段（论文、可复现性）可以复原 "在 计算 partition、hostname X、CPU model …上运行" 的事实，不必从空的 artefact 中猜测。
- **Git shim** (`ari/agent/shims/git.sh`) — 通过 `PATH=<sandbox>/.shims:<orig_path>` 接入可复现性沙箱。仅拦截与论文 `code_availability_ref` 匹配的 `git clone` URL；其余命令透传给真实 git。所有 clone 尝试记录到 `<sandbox>/repro_clone_log.jsonl`。可通过 `ARI_REPRO_CLONE_POLICY=passthrough|deny|warn` 切换行为。

---

## 另请参阅

[架构](architecture.md) · [注册表](../reference/registry.md) · [评分准则模式](../reference/rubric_schema.md) · [PaperBench 快速开始](../guides/paperbench/paperbench_quickstart.md)
