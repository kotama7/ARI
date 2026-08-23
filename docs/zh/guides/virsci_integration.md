---
sources:
  - path: ari-core/ari/rqgm/proposals/virsci_adapter.py
    role: implementation
  - path: ari-core/ari/rqgm/proposals/router.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/configs/defaults.yaml
    role: config
  - path: ari-skill-idea/src/server.py
    role: implementation
  - path: ari-core/tests/test_rqgm_virsci_adapter.py
    role: test
last_verified: 2026-08-16
---

# VirSci 集成

VirSci（多 agent 科研协作式想法生成器）通过两个相互独立的表面接入
ARI。两者默认都不启用，且互不依赖：

1. **`ari-skill-idea` MCP 技能**（两种执行模式均可用）——
   `workflow.yaml` 的 `generate_idea` 阶段在 BFTS 开始前调用一次该
   技能的 `generate_ideas` 工具。该技能在同一输出契约背后有两个引擎：
   默认的轻量级 **reimpl** 讨论循环，以及可选启用的 **real_wrap**
   引擎（`ARI_IDEA_VIRSCI_REAL=1`），后者运行 vendored 的 VirSci
   机制。见 [MCP 技能参考 → ari-skill-idea](../reference/skills.md)。
2. **RQGM `VirSciAdapter`**（仅 `ari_rqgm` 模式）—— `ProposalRouter`
   （`ari/rqgm/proposals/router.py`）背后的一个可选高成本审议式生成
   器。本指南讲的是这一表面。

该适配器（`ari/rqgm/proposals/virsci_adapter.py`）是一个**纯 MCP
归一化器**：它通过 MCP 调用 idea 技能的 `survey` 和 `generate_ideas`
工具，不从 `ari-skill-idea` 导入任何东西。重依赖
（torch/faiss/agentscope）留在技能进程内，这保持了技能的降级层级
完整，并使"未安装 VirSci 也能通过测试"成为结构性保证。

## 配置

该生成器是 `proposal_router.generators` 块中的一个条目
（`ari.config.VirSciGeneratorConfig`；默认值镜像在
`ari-core/ari/configs/defaults.yaml`，两处一致性由
`ari-core/tests/test_rqgm_proposals.py` 钉住）：

```yaml
proposal_router:
  summary_budget_chars: 6000
  generators:
    virsci:
      enabled: false            # opt-in; never enabled by default
      mode: event_triggered     # v1 supports only `event_triggered`
      max_calls_per_epoch: 2    # hard per-epoch cap on adapter invocations
      trigger_on: [initial_exploration, frontier_stagnation,
                   major_pivot, paper_candidate]
```

- **`enabled`**（默认 `false`）—— 适配器的总开关。见
  本页「`enabled: false` 时的保证」一节。
- **`mode`** —— 调用模式；v1 唯一接受的值是 `event_triggered`
  （没有轮询模式或按节点模式）。
- **`max_calls_per_epoch`** —— 每纪元调用预算。预算按**调度头**计数，
  而不是按记录：一次 VirSci 调用产出多条 `ProposalRecord`，但只消耗
  一个预算单位（`ProposalStore.count_for_epoch`）。计数从已存储的
  记录派生，因此跨 resume 是确定性的，且被完全去重的重试（MCP 3 次
  重试策略）不追加任何内容、不消耗任何预算。
- **`trigger_on`** —— 可以路由到该适配器的路由器触发事件。从此列表中
  移除某个事件即令 VirSci 对该事件不可用，除非该运行需要 typed
  Research Contract —— 见
  本页「`enabled: false` 时的保证」一节。

`proposal_router.*` 仅在生效模式为 `ari_rqgm` 时被消费（唯一例外
`record_only` 与 VirSci 无关 —— 见 [RQGM 迁移](rqgm_migration.md)）。
在 `simple_bfts` 下，现有的技能侧控制杆 —— `workflow.yaml` 的
`generate_idea` 阶段和 `ARI_IDEA_VIRSCI_REAL` —— 仍是仅有的 VirSci
控制手段。

## 事件触发路由与预算

路由是纯策略函数 `ari.rqgm.proposals.router.route`（确定性、无
I/O、无随机性 —— P2）：对一个触发事件，按固定优先级顺序取第一个
*已启用*且尚有预算的生成器。v1 优先级表：

| 触发事件 | 优先级顺序 |
|---|---|
| `initial_exploration` | `virsci` → `prior_art` → `cheap` |
| `frontier_stagnation` | `virsci` → `mutation` → `cheap` |
| `major_pivot` | `virsci` → `prior_art` → `cheap` |
| `paper_candidate` | `prior_art` → `mutation` → `cheap` |

因此在 VirSci 启用且尚有预算时，适配器是 `initial_exploration`、
`frontier_stagnation` 和 `major_pivot` 的第一优先选择；固定的
`paper_candidate` 顺序永远不会选择它，不论 `trigger_on` 怎么写。
预算耗尽时落到下一个生成器，而返回零草稿的生成器会降一档到不设上限
的 `cheap` 回退 —— BFTS 循环绝不会因路由器故障而死亡。

v1 运行循环接线：循环在根构思阶段调度 `initial_exploration`
（`generate_root_proposals`，它取代 agent 发起的根 `generate_ideas`
调用），并把扩展方向记录为观察。`ProposalRouter.on_event` 是其余
触发事件的再构思表面；运行中途的事件在相同预算下追加候选记录，但在
v1 中绝不移动 `ideas[0]` 指令 —— 晋升一个再构思结果属于治理决策。

适配器本身通过 MCP 先调用 `survey`（主题 → 论文列表，以及技能返回时
附带的 typed `survey_snapshot`；失败时降级为空列表），再调用
`generate_ideas` —— 有快照就原样转发快照，否则转发论文列表投影 ——
并把 `generate_ideas`
载荷归一化为每个想法一个 `ProposalDraft`。
`virsci_adapter.GENERATE_IDEAS_KEYS` 列出的是该契约的九个遗留顶层键；
归一化还会透传技能 typed contract 键中的九个 —— 即下文路由器上浮的
十个键中除 `survey_snapshot` 以外的全部。`generate_ideas` 失败会降级为零
草稿；存储层的内容键去重使整条路径在重试下幂等。

## 归档 vs. 摘要

VirSci 输出在写入时即被拆分（"存储全部，只展示摘要"）：

- **归档在检查点下** —— 完整的 `generate_ideas` 载荷（原始想法列表、
  `gap_analysis`、生成器配置）进入
  `{checkpoint}/proposals/archive/<record_id>/`（`raw_output.json`、
  `generator_config.json`）。技能在磁盘上的转录工件 ——
  `{checkpoint}/virsci_logs/virsci_stdout.log` 和
  `{checkpoint}/virsci_snapshot/` —— 在记录的 `archive_refs` 中被
  *引用*，绝不复制。
- **BFTS 看到的** —— 只有有界的 `ProposalSummaryView`（每字段硬性
  字符预算；渲染出的扩展上下文由
  `proposal_router.summary_budget_chars` 封顶，默认 6000 —— 与
  RQGM 之前的 `_build_idea_ctx_for_expand` 通道对齐）。任何转录或
  讨论内容都不会进入摘要字段或渲染的上下文；由
  `test_rqgm_virsci_adapter.py::test_transcript_content_never_reaches_expand_context`
  钉住。

共享的附加项还会一并进入 `idea.json` 投影的顶层键，从而保留 RQGM
之前的 `idea.json` 契约：`ProposalRouter._projection_meta` 重新读取
已归档的载荷，并把五个遗留键（`gap_analysis`、`papers_analyzed`、
`n_agents`、`discussion_rounds`、`virsci_integration_status`）以及技能
如今还会返回的十个 typed contract 键（`typed_schema_version`、
`contract_status`、`survey_snapshot`、`survey_snapshot_digest`、
`survey_snapshot_ref`、`idea_set`、`idea_set_digest`、
`research_contract`、`research_contract_digest`、`rejected_candidates`）
中存在的那些复制过去。

## `enabled: false` 时的保证

在默认的 `enabled: false` **且** typed contract 姿态保持默认
（`knowledge.mode: off`、`capability_binding.mode: legacy`、
`assurance.mode: off`）时（全部由
`ari-core/tests/test_rqgm_virsci_adapter.py` 钉住）：

- **适配器从不被构造。**`ProposalRouter._build_generators` 只在标志
  为 true 且存在 MCP 客户端时实例化 `VirSciAdapter`
  （`test_mode_virsci_matrix_config_and_boot`）。
- **适配器模块从不被导入。**导入语句位于该条件分支内部，且模块没有
  导入副作用
  （`test_virsci_disabled_adapter_module_never_imported`）。
- **永远不需要 VirSci 运行时。**适配器不从 `ari-skill-idea` 导入
  任何东西，也不依赖任何 VirSci 组件
  （`test_adapter_imports_nothing_from_the_idea_skill`）；测试模块
  全程使用伪造的 MCP 客户端 —— 不安装 VirSci、没有 vendored 子模块、
  没有真实 LLM 调用。
- **评估工具链强制其缺席。**在 B3（VirSci 关闭）消融条件中，
  `virsci_absence_violations` 会让出现 VirSci 提示词或转录文件的
  运行失败 —— 见 [RQGM 评估](rqgm_evaluation.md)。

以上保证只覆盖默认姿态。一旦 `knowledge.mode`、
`capability_binding.mode`、`assurance.mode` 中任何一个偏离默认值，
`ProposalRouter._typed_contract_required()` 即为 true，路由器便会
（只要存在 MCP 客户端）构造适配器，无论
`generators.virsci.enabled` 取何值都把 `virsci` 视为已启用，并且无论
`trigger_on` 怎么写都让它对每个触发事件留在路由表中。

## 模式 × VirSci 的四种组合

`proposal_router.generators.virsci.enabled` 与 `ari.mode` 正交：
模式解析从不读取 `proposal_router.*`，VirSci 门控也从不读取
`ari.mode`。四种组合都是有效配置并能干净启动
（`test_mode_virsci_matrix_config_and_boot`）：

| `ari.mode` | `virsci.enabled` | 行为 |
|---|---|---|
| `simple_bfts` | `false` | 默认。`proposal_router.*` 惰性；技能侧控制杆（`generate_idea` 阶段、`ARI_IDEA_VIRSCI_REAL`）是仅有的 VirSci 控制手段。 |
| `simple_bfts` | `true` | 有效但惰性：`simple_bfts` 中没有任何东西构造路由器，因此该标志无效果。技能侧控制杆保持权威。 |
| `ari_rqgm` | `false` | 在 typed contract 姿态保持默认时，路由器仅以 `cheap`/`mutation`/`prior_art` 运行：不触碰任何 VirSci 运行时、vendored 路径、提示词或快照语料库。 |
| `ari_rqgm` | `true` | `VirSciAdapter` 加入路由表；在每纪元上限内通过 MCP 调用 `survey` + `generate_ideas`。 |

## Vendored 子模块与技能

`ari-skill-idea/vendor/virsci` 是一个 git 子模块，存放**未经修改**的
上游 VirSci 源码。只有技能中可选启用的 `real_wrap` 引擎
（`ARI_IDEA_VIRSCI_REAL=1`）会运行 vendored 的 VirSci 机制 —— 即在
Semantic Scholar 快照上的 `select_coauthors` / `generate_idea` 路径。
默认的 reimpl 引擎只借用 vendored 的讨论提示词模板
（`sci_platform/utils/prompt.py`，在技能 import 时读取），子模块未检出
时退回内联提示词，因此两种情况下都能运行；`ari-core` 也从不导入它。
实际运行的是哪个引擎会在
`generate_ideas` 载荷的 `virsci_integration_status` 键中报告
（`"real_wrap"` vs 带原因的 `"reimpl: …"`）—— RQGM 适配器对两种
状态一视同仁地归一化。

因为 RQGM 集成是纯 MCP 的，`ari-core` 从不触碰该子模块。这一点被
钉住两次：适配器模块既不导入技能也不导入任何 VirSci 运行时
（`test_rqgm_virsci_adapter.py::test_adapter_imports_nothing_from_the_idea_skill`），
且没有任何对抗模块导入 VirSci
（`test_rqgm_adversarial.py::test_adversarial_package_never_imports_virsci`）。
RQGM 测试模块完全针对伪造的 MCP 客户端运行 —— 在从未检出该子模块、
从未安装 `virsci` pip extra 的机器上也能通过。

另请参阅：[执行模式](execution_modes.md) ·
[RQGM 迁移](rqgm_migration.md) ·
[RQGM 评估](rqgm_evaluation.md) ·
[MCP 工具参考](../reference/mcp_tools.md) ·
[环境变量](../reference/environment_variables.md)
