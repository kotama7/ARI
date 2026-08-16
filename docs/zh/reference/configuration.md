---
sources:
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/config/default.yaml
    role: config
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/config/finder.py
    role: implementation
  - path: ari-core/ari/configs
    role: config
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/ari/viz/ui_helpers.py
    role: implementation
  - path: ari-core/ari/viz/services/state_service.py
    role: implementation
  - path: ari-core/ari/viz/state.py
    role: implementation
  - path: ari-core/ari/viz/v1/secrets.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/rqgm/budget.py
    role: implementation
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: ari-core/ari/config/resolver.py
    role: implementation
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/viz/v1/config_api.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/cli/lineage.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-core/ari/cli/manuscript.py
    role: implementation
  - path: ari-core/tests/test_gui_baseline_settings_contract.py
    role: test
  - path: ari-core/tests/test_gui_config_shadow_legacy.py
    role: test
  - path: ari-core/tests/test_gui_v1_mode_selection.py
    role: test
  - path: ari-core/ari/viz/frontend/src/components/Settings/__tests__/SettingsContract.test.tsx
    role: test
last_verified: 2026-08-13
---

# 配置参考

## 配置优先级（实测行为）

ARI 的配置来自多个入口。存在**两条优先级链** —— 一个设置最终解析成
什么值，取决于*是谁在问*：

- **运行时（core/CLI）** —— 智能体循环与流水线实际使用的值。
  由 `ari.config.load_config()` 构建（无 YAML 时为 `auto_config()`）：
  **`ARI_*` 环境变量 > workflow.yaml/config YAML > Pydantic 字段默认值**。
  环境变量总是获胜，因为 `_apply_*_env_overrides` 系列函数*最后*运行
  （在 profile 合并之后）。`auto_config()` 是无文件时的回退（环境变量
  优先于硬编码值）。Profile（`--profile laptop|hpc|cloud`）在 YAML 与
  环境变量之间被应用，但它**不是**深度合并 —— `_apply_profile`
  （`ari/cli/run.py`）恰好只复制四个键，profile 文件中的其他每一个键都会
  被静默忽略（见下文*解析模型*中的「4 键 profile 合并的注意事项」）。
- **GUI 设置面板** —— `/api/settings` 展示的值。由
  `_api_get_settings()` 构建：**已保存的 `settings.json`（若为 truthy）>
  `ARI_*` 环境变量 > `workflow.yaml` > 硬编码默认值**，并带有一个
  falsy 重填充的怪癖（已保存但为空的 `llm_model`/`llm_provider` 只会
  从 `workflow.yaml` 重新填充，丢掉环境变量这一层）。

**桥接**：GUI 的 `/api/launch` **不会**把选项作为参数传给被启动的
CLI —— 它把选项写入子进程的 `ARI_*` 环境变量，**并**快照到
`{checkpoint}/launch_config.json`。CLI 随后按上面的运行时链解析。
`launch_config.json` 只会被 `/api/run-stage` 和仪表盘显示状态的重建
重新从磁盘读取；`ari.config` *不会*重新解析它。

| 设置 | 获胜顺序（最高在前） | 决定位置 |
|---------|-------------------------------|-----------|
| `llm_model`（运行时） | `ARI_MODEL` > `ARI_LLM_MODEL` > YAML `llm.model` > `qwen3:8b` | `config/__init__.py:_apply_llm_env_overrides` |
| `llm_model`（GUI 显示） | 内存中的 `_launch_llm_model` > `launch_config.json` > `settings.json` > `workflow.yaml` > `''` | `viz/routes.py`、`viz/ui_helpers.py` |
| `llm_model`（Settings 合并） | 已保存的 `settings.json`（若为 truthy）> `ARI_LLM_MODEL` > `workflow.yaml` > `''` | `viz/api_settings.py:_api_get_settings` |
| `llm_provider`/`backend`（运行时） | `ARI_BACKEND` > YAML `llm.backend` > `ollama` | `config/__init__.py:_apply_llm_env_overrides` |
| 论文 `language` | 仅 `ARI_PAPER_LANGUAGE` 环境变量（由 GUI 启动设置；手动运行 CLI 时*不会*从 `launch_config.json` 重新推导） | `ari-skill-paper` 读取环境变量；`viz/api_experiment.py` 设置它 |
| GUI 端口 | `ARI_GUI_PORT`（经 `start.sh`）> `--port`（argparse 默认 **8765**）> `state.py` 的 `9886` 占位值 | `start.sh`、`viz/server.py:main` |
| SLURM 分区 | 显式工具 `partition` kwarg（经 sinfo 校验）> `SLURM_DEFAULT_PARTITION` > sinfo 首个分区；该 kwarg 依次取自：experiment.md 的 `Partition:` > `ARI_SLURM_PARTITION` > sinfo | `ari-skill-hpc/slurm.py`、`ari/agent/workflow.py` |
| checkpoint 目录 | `ARI_CHECKPOINT_DIR` > YAML `checkpoint.dir` > `workspace/checkpoints/{run_id}` | `config/__init__.py:_apply_checkpoint_env_overrides`、`PathManager` |
| workspace 根目录 | `ARI_CHECKPOINT_DIR`（据此还原：最外层 `checkpoints/` 祖先目录的父目录；若不存在这样的祖先，则取该 checkpoint 自身的父目录）> 显式传入的 `workspace_root` 参数 > `{ARI_ROOT}/workspace` > `{repo_root}/workspace`（仅当 `{repo_root}/ari-core` 是目录时）> 解析后的当前工作目录 | `paths.py:RuntimePathResolver.resolve_workspace_root` |
| `bfts_pipeline[].enabled` | `{checkpoint}/workflow.yaml` > 包内自带的 `ari-core/config/workflow.yaml` > `true` | `cli/bfts_loop.py`（原始 YAML 读取） |
| `lineage_decision.*` | 生效 rubric 的 `lineage_thresholds`（`ARI_RUBRIC`；仅四个阈值键，不含 `mode`）> 包内自带的 `ari-core/config/workflow.yaml` > `./config/workflow.yaml`（进程 cwd）> 调用点默认值 | `cli/lineage.py:_load_lineage_decision_config` |
| `root_idea_selection.enabled` | **仅**包内自带的 `ari-core/config/workflow.yaml` > `false` | `cli/bfts_loop.py`（原始 YAML 读取） |

**「workspace 根目录是什么」只有一个所有者。** 上表中的五级阶梯只存在于一个
函数里 —— `RuntimePathResolver.resolve_workspace_root()`
（`ari-core/ari/paths.py`），并且已有四个生产调用点走这条路径：
`ARI_CHECKPOINT_DIR` 未设置时的 `auto_config()`
（`ari/config/__init__.py`）、`workspace_harness_root()`
（`ari/harness_registry.py`，在它自己的 `ARI_WORKSPACE` 短路之后）、GUI 文档
存储（`ari/viz/v1/store.py`），以及铸造
`{workspace_root}/checkpoints/{run_id}` 的 v1 启动路径
（`ari/viz/v1/launch.py`）。打开代码时有两处需要略过：该方法自己的 docstring
仍称自身是*additive*、并说 opt-in「推迟到 005」—— 这句话已经过时，上面四个
调用点就是那个 opt-in；另外 [环境变量](environment_variables.md) 在
*检查点 + 路径* 一节把 `ARI_ROOT` 定位为「测试时使用」，这低估了它。
`ARI_ROOT` 是这条阶梯的第三级，因此在 `ARI_CHECKPOINT_DIR` 未设置时，它决定
真实运行落在哪里。而*没有*改变的是：`PathManager()` 的裸构造函数仍然默认当前
工作目录，并不查询这条阶梯。

**falsy 与缺失的区别：** core 侧的环境变量覆盖守卫（`if _m:` 等）把
空环境变量当作缺失处理（保留 YAML/默认值；`base_url` 使用显式的
`!= ""`）。GUI 的合并 `{**defaults, **saved}` 允许"存在但为空"的已保存
键获胜，然后只对 `llm_model`/`llm_provider` 从 `workflow.yaml` 强制
重填。

**env 覆盖层是多个函数而不是一个，而且它不做重新校验。** 上面那句「env 总是
获胜」背后有两个值得明说的细节：两者都很关键，而且都不会体现在表里。

第一，覆盖*在哪里*执行。`load_config()` 在返回前恰好应用两个覆盖族 ——
`_apply_llm_env_overrides`（其内部再调用 `_apply_claude_code_env_overrides`）
与 `_apply_checkpoint_env_overrides` —— 外加 `allow_web` 的阶段改写。BFTS、
evaluator、RQGM、handoff 与 paper 各族是独立的*公开*函数
（`apply_bfts_env_overrides`、`apply_evaluator_env_overrides`、
`apply_rqgm_env_overrides`、`apply_handoff_env_overrides`、
`apply_paper_env_overrides`），需要调用方自己去调。`ari/cli/run.py` 在
`_apply_profile` 之后立刻调用前四个 —— 这正是 env 能压过 profile 的原因 ——
paper 那个则由 `ari/cli/paper_dispatch.py` 调用。因此只调用 `load_config()`
的调用方会拿到 `ARI_MODEL`、`ARI_BACKEND`、`ARI_LLM_API_BASE`、
`ARI_CHECKPOINT_DIR` 与 `ARI_LOG_DIR`，而**不会**拿到 `ARI_MAX_NODES`、
`ARI_FRONTIER_SCORE`、`ARI_COMPOSITE`、`ARI_MODE`、`ARI_RQGM_ENABLED` 或
`ARI_PAPER_MODE`；`ari/cli/manuscript.py` 之所以手工再调一次
`apply_rqgm_env_overrides`，正是出于这个原因。优先级表里的 env 这一层是若干
调用点拼起来的，而不是任何单个函数拥有的一层。

第二，*由什么来检查值*。这些函数是往一个已构造好的模型上赋值，而 `ari/` 之下
没有任何地方设置 pydantic 的 `validate_assignment`，所以模型不会重新校验写进去
的东西 —— 代码里的注释也是这么说的（「Pydantic does not validate on
assignment, so guard against unknown values from env」）。取而代之的是每个函数
各自的手写守卫：`ARI_FRONTIER_SCORE` 会与一个复制自
`BFTSConfig.frontier_score` 的 `Literal` 成员的四元组字面量比对，
`ARI_COMPOSITE` 与 `ARI_AXIS_MODE` 各自与自己的字面量比对，而整数类旋钮是把
`int()` 包在 `try/except ValueError: pass` 里。被拒绝的值会不会说点什么，取决于
它归哪个函数管：`apply_rqgm_env_overrides` 与 `apply_paper_env_overrides` 会
记录一条点名变量与取值的 `warning`，而 `apply_bfts_env_overrides` /
`apply_evaluator_env_overrides` 的守卫以及所有 `int()` 回退都会静默丢弃 ——
没有异常、没有日志行，任何响应里也没有。于是 `ARI_FRONTIER_SCORE=ucb` 会让这
次运行停留在 YAML 或默认值上，且没有任何迹象表明该变量被读到过；而
`ARI_MODE=rqgm` 至少还会留下日志。这些复制出来的枚举列表是手抄的，可能与它们
所镜像的 `Literal` 发生漂移；给其中一处加成员时，请在同一次改动里给另一处也
加上。

**两个 `workflow.yaml` 块只会从包内自带的那份副本读取（反模式）。**
`lineage_decision` 和 `root_idea_selection` 都不是 `ARIConfig` 的已声明
字段，因此 `load_config` 的
`{k: v for k, v in raw.items() if k in ARIConfig.model_fields}` 过滤器会把
它们丢掉，两个块各自由专门的读取器重读原始 YAML。而这两个读取器在*读哪
一份* `workflow.yaml` 上与其余读取器并不一致。`bfts_pipeline` 是 checkpoint
优先读取的 —— 先看 `{checkpoint}/workflow.yaml`，包内副本只是回退；而
`_load_lineage_decision_config`（`ari/cli/lineage.py`）读取包内自带的
`ari-core/config/workflow.yaml`，只有当该文件缺失时才回退到相对进程工作
目录的 `./config/workflow.yaml`；`root_idea_selection` 块更是只读包内副本。
checkpoint 优先的读取与只读包内的读取共处于同一个文件
`ari/cli/bfts_loop.py` 中。后果是：把这两个块写进
`{checkpoint}/workflow.yaml` 不会生效，用 `--config` 传入同样不会生效
（类型化加载器会丢弃它们，而这两个读取器都不看那条路径）。要为某次运行
修改它们，请编辑包内自带的 `workflow.yaml`；就 `lineage_decision` 的四个
阈值键而言，生效 rubric 的 `lineage_thresholds` 覆盖层才是按会场调参的
正规手段。这是已知的不一致，而不是设计出来的分层；新的读取器不应沿用这种
只读包内副本的模式。

**未知的顶层键会被丢弃且没有任何运行时警告。** `load_config` 只用那些
已声明为 pydantic 字段的顶层 YAML 键来构建 `ARIConfig` —— 即
`ari/config/__init__.py` 中的
`{k: v for k, v in raw.items() if k in ARIConfig.model_fields}` 过滤器。
`ARIConfig` 设置了 `extra="allow"`，但在这里救不了任何东西：过滤发生在
构造*之前*。有些未声明的块仍然生效，是因为有专门的读取器绕过类型化配置
直接重读原始 YAML —— `memory` 走 `_apply_memory_section`，`container` 走
`ari/cli/run.py`，`lineage_decision` 走
`ari/cli/lineage.py:_load_lineage_decision_config`，此外还有
`bfts_pipeline`、`pipeline` 和 `claim_gate_policy`。
`ari.config.resolver.KNOWN_NON_CONFIG_TOP_KEYS` 枚举了解析器目前认定拥有
这类读取器的顶层键 —— 但它是手工维护的清单而非推导出来的，而且**并不
完整**。有第二个通用消费者没有被它计入：流水线驱动器
（`ari/pipeline/driver.py`）会重读原始 `workflow.yaml`，把每一个顶层标量
都灌进阶段模板的命名空间（顶层 dict 也会以点号形式暴露，`pipeline`/
`skills`/`stages` 除外）。因此一个未声明的顶层键虽然从 `ARIConfig` 里被
丢掉，却仍可在阶段的 `inputs:` 中以 `{{key}}` 触达。内置的 `ari-core/config/workflow.yaml` 正是依赖这一点：
`paper_venue: arxiv` 与 `paper_rubric: generic_conference` 既不在
`ARIConfig.model_fields` 中也不在 `KNOWN_NON_CONFIG_TOP_KEYS` 中，却是活的
—— `write_paper` 取 `rubric_id: '{{paper_rubric}}'` 与
`venue: '{{paper_venue}}'`，`review_compiled_paper` 再次取 `rubric_id`。
`paper_rubric` 就是挑选评审 rubric 的那个设置，而 `write_paper_iterative`
对它既没有环境变量兜底也没有猜测出来的默认值，所以它恰恰不是死配置。
一个*没有任何地方以模板引用*的顶层键才会被彻底丢掉，且丢掉时不会记录任何
日志；`ari.config` 中**不存在近似拼写（"你是不是想输入…"）检查**。因此把
`rqgm:` 拼成 `rqmg:`，这次运行就会静默地停留在默认值上，没有任何错误可供
察觉。有两件事可以部分弥补，但都不在加载时的 CLI 上：

- **解析器会在其载荷中给出警告。** `_apply_workflow_layer`
  （`ari/config/resolver.py`）会为每个既不在 `ARIConfig.model_fields`
  也不在 `KNOWN_NON_CONFIG_TOP_KEYS` 中的键追加
  `workflow.yaml top-level key '…' is not an ARIConfig field — load_config
  silently drops it (no reader consumes it)`。它通过
  `GET /api/v1/runs/{run_id}/resolved-config`（读取 checkpoint 中
  `workflow.yaml` 的副本）以及新运行预览（读取内置的那份）的 `warnings`
  数组传达给你。它只是一份列举，不是拼写建议；由于 `ari.viz.v1` 之外没有
  任何代码调用解析器，手动运行的 CLI 永远看不到它。另外，别把其中
  `(no reader consumes it)` 的措辞当成已核实的结论：在内置
  `workflow.yaml` 上它只会发出两条警告，分别针对 `paper_venue` 和
  `paper_rubric`，而这两个键都*确实*有人消费。该警告证明的是这个键没进入
  `ARIConfig`，而不是这个键无效。
- **缺失在 checkpoint 中是可观测的。** 只有当 `ari.mode: ari_rqgm` 与
  `rqgm.enabled: true` 同时成立时才会写出
  `{checkpoint}/rqgm_state.json`（`ari/cli/run.py`），所以该文件不存在就
  意味着这次运行是 `simple_bfts`。请用这个文件来确认非默认的执行模式是否
  真的生效，而不是依据"没有报错"。

同一个过滤器也让向后的方向是安全的：某个 `ari-core` 构建未声明为字段的
块会被忽略而不是致命失败，所以把较新的 YAML 部署到较旧的 core 上，只会
退化为该 core 的默认值，而不会加载失败。

**两条链都不会读的第三个 YAML。** CLI 加载的是
`ari-core/config/workflow.yaml`。与它相邻的 `ari-core/config/default.yaml`
看起来像是属于同一条链，实际上两条链都不属于：它是一个旧 schema 的文件，
任何运行时加载器都不会独自触达它。（第三个名字
`ari-core/ari/configs/defaults.yaml` 又是另一回事 ——
它是下文*执行模式与 RQGM 治理（可选启用）*中描述的 RQGM /
proposal_router 平价镜像，另外还有一个活的键
`models.lineage_decision_default`，由 `ari/orchestrator/lineage_decision.py`
中的 `_config_default` 读取。）

CLI 的加载阶梯是 `_resolve_cfg`（`ari-core/ari/cli/run.py`）：给了显式
`--config` 就用它，否则用包内自带的 `ari-core/config/workflow.yaml`，再否则
用 `auto_config()`。`default.yaml` 在其中根本没有出现。它确实出现在
`find_workflow_yaml`（`ari-core/ari/config/finder.py`）四步搜索的第 3 步，
但这个函数在整棵树里没有任何调用者 —— 同一模块的 `package_config_root`、
`find_workflow_in_dir`、`find_profile_yaml` 和 `load_workflow_config` 被广泛
调用，唯独 `find_workflow_yaml` 没有 —— 所以它 docstring 描述的那条阶梯
从未运行过。

确实存在三个读取器，而且三个都在 GUI 侧、只用于展示：

| 读取器 | 它拿这个文件做什么 |
|---|---|
| `ari/viz/services/state_service.py` | `build_app_state()`（`/state` 载荷）把它深拷贝为合并后 `experiment_config` 块的底座，并把它的 `bfts` / `evaluator` 值当作 `{checkpoint}/workflow.yaml` 之下的逐键回退。还有一个分支只在上面没有构建出 `experiment_config` 时才会走到，那里的 BFTS/HPC 值只取自所选的 profile YAML 和 `default.yaml`。 |
| `ari/viz/ui_helpers.py` | `_build_experiment_detail_config()` 为 `/api/experiment-detail` 的文本块再做一遍同样的合并。 |
| `ari/viz/api_settings.py` | `_api_get_workflow()`（`GET /api/workflow`）只读它的 `skills` 条目，用来填充每个 `skill_mcp` 条目的 `phase` 字段。 |

因此，编辑 `default.yaml` 改变的只是 legacy 仪表盘*显示*什么，而不会改变一次
运行*做*什么 —— 除非你自己把这个文件交给 `--config`；CLI 接受这样做，但没有
任何默认路径会这样做。

它的内容也不是 `ARIConfig` 的形状，这是不该把它当作默认值文件来读的另一半
原因。顶层的 `hpc:` 和 `output:` 不是 `ARIConfig` 字段，会被上文那个
`model_fields` 过滤器移除；`bfts.score_threshold`、`checkpoint.trigger` 和
`logging.output` 不是各自子模型的字段，在构造时被忽略；它的 `skills` 路径是
`/path/to/ari/…` 占位符，所以 `_hydrate_skill_manifests` 在其中任何一个路径
上都找不到 manifest，会跳过每一条；而它的 `llm.backend` / `llm.model`
（`claude` / `claude-haiku-4-5`）与默认运行实际使用的 pydantic 默认值
（`ollama` / `qwen3:8b`）相互矛盾。请把它当作历史示例，而不是优先级链条中的
一层。

> ⚠ 这里的优先级是**按今天的实测行为记录**的，并非被改动过。在任何整合之前，
> 该顺序由测试锁定（`test_config.py`、`test_default_provider.py`、
> `test_launch_config.py`、`test_settings_*`）。曾经作为后续提案的集中式配置
> 加载器如今只存在于 GUI 路径 —— `ari.config.resolver`
> （`legacy-compatible-1`，见下一节）。它只是事后**重建**这条链，并不取代它；
> CLI 仍然完全按上面的顺序解析。

## 配置控制平面（`/api/v1/config/*`）

GUI 的配置接口面建立在三个可被机器校验的部件之上：

1. 一个**字段注册表** —— 所有已声明配置叶子的规范元数据清单
   （`ari-core/ari/config/field_registry.py`）；
2. 一个**解析器** —— 每种解析上下文一个函数，用于解释每个生效值来自何处
   （`ari-core/ari/config/resolver.py`）；
3. 一个**文档存储** —— 仅供 GUI 使用的 project 配置 / run 模板 / run 草稿
   （`ari-core/ari/viz/v1/store.py`）。

这三者相对于运行时都是只读的：它们从不修改 `ARIConfig`，从不写
`os.environ`，而 CLI / `simple_bfts` 路径也从不读取它们。它们的存在是为了让
UI 能够*解释*配置；一次运行真正使用的值，仍然通过上文的优先级链抵达。

### 字段注册表（规范字段元数据）

`GET /api/v1/config/schema` 提供这份注册表 —— **仅元数据，绝不包含生效值**。
每个条目描述一个 `ARIConfig` 叶子：

| 键 | 含义 |
|---|---|
| `path` | 点分叶子路径（`bfts.max_total_nodes`）。稳定的身份标识。 |
| `value_type` | 渲染后的 pydantic 注解（`int`、`str \| None`、`list[SkillConfig]`、`dict[str, float]` 等）。`Literal` 渲染为其成员的类型（`str`），成员本身放在 `enum` 中。 |
| `default` | pydantic 默认值（或默认工厂产生的值）。对 `secret_reference` 叶子强制为 `null`。 |
| `enum` | 当注解是闭合集合时为其 `Literal` 成员，否则为 `null`。 |
| `required` | 该字段是否没有默认值。 |
| `category` | UI 分组：Models、Skills、Search (BFTS)、Infrastructure、Evaluation、Execution mode、Governance、Proposal routing。 |
| `level` | `basic` / `advanced` / `expert` —— 供渐进式披露使用。**仅声明**：没有任何界面按它过滤（见下文*两个只声明、未强制的键*）。 |
| `scope` | `preference` / `installation` / `project` / `template` / `run` —— 哪种文档可以拥有该值。 |
| `sensitivity` | `public` / `internal` / `secret_reference`。 |
| `mutability` | `draft` / `new_run_only` / `resume_mutable` / `read_only`。 |
| `applies_when` | 依赖谓词（`bfts.frontier_score=depth_penalized`）、配对说明，或 `null`。**仅声明**：只作为文本渲染，从不被解析（见下文*两个只声明、未强制的键*）。 |
| `notes` | 手写的注意事项（例如「yaml_only: no GUI field or `ARI_*` hook」）。 |
| `source` | `pydantic` —— 遍历只覆盖已声明的模型字段。 |
| `env_override` | 覆盖该叶子的 `ARI_*` 变量，或 `null`。 |

**覆盖率不变式。** 注册表目前有 **205 个叶子且元数据覆盖率 100 %**：当任何
被遍历到的叶子缺少 `FIELD_META` 前缀或精确条目时，`build_field_registry()`
会抛出 `LookupError`，因此新增配置字段无法在没有 schema 元数据的情况下发布。
当前分布：104 个 Governance / 32 个 Models / 24 个 Search (BFTS) /
14 个 Proposal routing / 10 个 Manuscript completeness / 6 个 Scientific assurance /
5 个 Infrastructure / 4 个 Evaluation / 4 个 Execution mode /
2 个 Skills；151 个 expert、18 个 advanced、36 个 basic；204 个 `public` +
1 个 `secret_reference`（`llm.api_key`）；147 个 `new_run_only` + 58 个
`draft`；20 个叶子带有 `env_override`。

有意为之的保真度限制（已记录在案，而非静默存在）：

- 只遍历**已声明的 pydantic 字段**。`extra="allow"` 的 YAML 块（`hpc`、
  `container`、`memory`、`letta`、`claim_gate_policy`、`lineage_decision`
  等）没有模型字段，因此也没有叶子；它们的 `FIELD_META` 前缀是为将来被
  类型化的那一天预先声明的。
- 列表/字典字段（`skills`、`resources`、`evaluator.axis_weights`、
  `evaluator.custom_axes`）是**单个复合叶子** —— 元素路径依赖下标，无法作为
  稳定身份标识。
- 该模块是纯函数式的：无文件系统、无时钟、不读环境变量、无 LLM 调用。两次
  构建的结果逐字节相同（P2）。
- 这些元数据词汇表是**闭合并受校验的，但只被部分填充**。`_validate_meta` 会
  拒绝 `level`、`scope`、`sensitivity` 或 `mutability` 落在允许集合之外的条目，
  然而注册表实际产出的叶子在其中两个轴上只占了一个子集。在 mutability 轴上，
  今天每个叶子不是 `draft` 就是 `new_run_only`；没有 `resume_mutable`，也没有
  `read_only`。在 scope 轴上，除了 `llm.api_key`（唯一的 `installation` 叶子）
  之外，每个叶子不是 `run` 就是 `project`；没有 `preference`，也没有
  `template`。由此有两个后果。`validate_patch` 的 `read_only` 拒绝虽然属于那份
  闭合的理由词汇表，但对当前注册表根本无法触发 —— 它只能经由 `mutability` 为
  `read_only` 的叶子到达，因此今天一个 PATCH 被拒绝的理由只会是
  `unknown_path`、`secret_reference`、`not_project_scope`、`invalid_enum`、
  `invalid_type` 或 `mode_interlock_mismatch`。而 Studio 的 `resume_mutable`
  与 `read_only` 徽章（见 [Configuration Studio](../guides/configuration_studio.md)
  的 *Mutability badges*）描述的是当前没有任何字段处于的状态。这些未被使用的
  取值是前置声明，为的是等 resume 切片或按用户的 preference 到来时不必再改动
  词汇表本身；请把它们读作预留，而不是你能在某个字段上找到的状态。

同一份注册表也驱动写入校验。`PATCH` 请求体是
`{"values": {"dotted.path": value}}`，由 `validate_patch` 检查，其闭合的拒绝
词汇表为 `unknown_path`、`secret_reference`、`read_only`、
`not_project_scope`、`invalid_enum`、`invalid_type`，外加跨路径的
`mode_interlock_mismatch`。secret 与 `read_only`
字段对所有目标一律拒绝；`new_run_only` 字段在模板/草稿中是合法的（它们配置
未来的运行），但在 project 配置中会被拒绝，除非其 scope 就是 `project`。

**模式叶子与互锁规则。** 四个 `Execution mode` 叶子（`ari.mode`、
`rqgm.enabled`、`paper.mode`、`rqgm.paper.enabled`）都是 `scope: run`、
`mutability: new_run_only`，并构成**两个配对** —— `field_registry.py` 中的
`MODE_INTERLOCK_PAIRS` 是其唯一来源，`resolver.INTERLOCK_PAIRS` 只是它的别名。
一个配对就是一个意图：若某个文档中只出现了一半而缺少与之一致的另一半，就会被
以 `mode_interlock_mismatch` 拒绝（`validate_mode_interlocks`，作用于合并后的
文档取值，而不是原始 patch）。自 ADR-09 起，这四个是 GUI 客户端唯一可写的
模式/治理叶子，且仅限新建运行；`Execution mode` 分类与 `rqgm.*` 树中其余 104 条
路径仍然仅限文件，并由 `POST /api/v1/runs` 以 `mode_locked` 拒绝
（`viz/v1/launch.py:locked_launch_paths`）。它们的
`applies_when` 元数据携带的是一条配对*说明*（"paired with `rqgm.enabled`
(one intent — set both)"），而不是 `path=value` 门控，因为用其中一半去门控
另一半会让互锁本身变成自我门控。

**两个只声明、未强制的键。** `applies_when` 与 `level` 会随每个条目一起返回，
但两者描述的都是尚无任何界面付诸实施的意图 —— 把它们当作实际行为来读是最容易
犯的错误。

- **`applies_when` 是说明，不是门控。** 它经由
  `GET /api/v1/config/schema`（`ari/viz/v1/dto.py` 中的
  `ConfigFieldV1.applies_when`）传出，并且恰好在三个地方以原文形式打印在字段
  路径下方 —— Config browser 的只读表格
  （`ConfigBrowser/ConfigReadOnlyTable.tsx`）、Studio 表单
  （`ConfigStudio/ConfigStudioPage.tsx`）以及 Studio 启动面板的
  *Changed vs defaults* 差异表（`ConfigStudio/LaunchPanel.tsx`），每处都是一行
  `Applies when: …`。没有任何代码解析它：`validate_patch` 从不读取它，没有任何
  控件因它而被禁用、标为必填或做冲突检查，`ari/config/resolver.py` 中甚至没有
  提到它。今天真正带有 `path=value` / `path!=value` 谓词的叶子共 135 个。
  其中 104 个正是下文 ADR-09 的锁定集合，因此让它们只读的并不是谓词。
  其余 31 个在谓词为假时仍然可编辑、可 patch：`bfts.depth_penalty_lambda`、
  `bfts.ucb_c`、`evaluator.custom_axes`、`manuscript.profile`、
  `manuscript.brief_character_budget`、7 个 `manuscript.repair.*` 叶子、
  6 个 `knowledge` / `capability_binding` / `assurance` 叶子，以及 13 个
  `proposal_router.*` 叶子。
  即使把 `bfts.frontier_score` 保持在默认值 `scientific_plus_diversity`，一个
  设置 `bfts.depth_penalty_lambda` 的 patch 依然校验通过，也依然会被解析器合并。
  GUI 计划所要求的统一依赖图 —— 用一套机制统管 enable/disable、required、
  conflict 与 derived preview —— 是一个**已知缺口 (known gap)**。凡是依赖关系
  确实被强制的地方，强制逻辑都在别处的代码里，而不在这个字符串里：模式互锁由
  作用于合并后文档的 `validate_mode_interlocks` 检查（这正是那四个模式叶子在此
  携带配对说明而非谓词的原因）；`rqgm.*` 树在 Studio 中只读，是因为 ADR-09 的
  `mode_locked` 策略，而不是因为它的 `applies_when` 写着 `ari.mode=ari_rqgm`。
- **`level` 没有消费者。** 它是必填元数据 —— `field_registry.py` 的
  `_REQUIRED_META_KEYS` 中包含 `level`，因此任何条目都不能省略它 —— 但两个配置
  界面都没有提供 Basic / Advanced / Expert 开关。Studio 会渲染左侧栏所选分类下
  的全部字段；Config browser 把所有字段按分类分组，只用路径/分类的搜索字符串做
  过滤。因此一个 `expert` 叶子与一个 `basic` 叶子在两个界面上同样可见。按 level
  的渐进式披露是一个**已知缺口 (known gap)**；这个值今天只对自行按它过滤的
  客户端有用。

`env_override` 一列是 `ari/config/__init__.py` 中 `apply_*_env_overrides`
系列函数的逐条转写：

| 配置叶子 | 环境变量 |
|---|---|
| `llm.model` | `ARI_MODEL`（别名 `ARI_LLM_MODEL`） |
| `llm.backend` | `ARI_BACKEND` |
| `llm.base_url` | `ARI_LLM_API_BASE` |
| `checkpoint.dir` | `ARI_CHECKPOINT_DIR` |
| `logging.dir` | `ARI_LOG_DIR` |
| `logging.level` | `ARI_LOG_LEVEL`（仅 auto-config / 无 YAML 路径） |
| `bfts.max_total_nodes` | `ARI_MAX_NODES` |
| `bfts.max_depth` | `ARI_MAX_DEPTH` |
| `bfts.max_react_steps` | `ARI_MAX_REACT` |
| `bfts.max_parallel_nodes` | `ARI_PARALLEL` |
| `bfts.timeout_per_node` | `ARI_TIMEOUT_NODE` |
| `bfts.frontier_score` | `ARI_FRONTIER_SCORE` |
| `bfts.allow_web` | `ARI_BFTS_ALLOW_WEB` |
| `evaluator.composite` | `ARI_COMPOSITE` |
| `evaluator.axis_mode` | `ARI_AXIS_MODE` |
| `ari.mode` | `ARI_MODE` |
| `rqgm.enabled` | `ARI_RQGM_ENABLED` |
| `paper.mode` | `ARI_PAPER_MODE` |
| `rqgm.paper.enabled` | `ARI_RQGM_PAPER_ENABLED` |
| `rqgm.paper.reviewer.agent_as_judge.enabled` | `ARI_PAPER_AGENT_AS_JUDGE` |

### 解析模型

两种解析模式都报告 `resolver_version: "legacy-compatible-1"` —— 这是算法的
身份标识，与载荷的 `schema_version` 分开版本化。初版解析器有意*复现*当前的
命令式优先级，而不是去改进它。

**A）既有检查点**（`GET /api/v1/runs/{run_id}/resolved-config`）—— 在不重新
运行 `load_config` 的前提下事后解释一次运行：

| # | 层 | `source` | 置信度 |
|:--:|---|---|---|
| 1 | pydantic 默认值 | `default` | high |
| 2 | `{ckpt}/workflow.yaml`（模型字段键） | `workflow` | high |
| 3 | `{ckpt}/launch_config.json` 中的旋钮 | `launch_config` | high |
| 4 | **当前**环境，仅限有文档记录的 `ARI_*` | `env` | **low** |
| 5 | `{ckpt}/rqgm_state.json` 中持久化的模式 | `checkpoint_state` | high，`mutable: false` |

第 4 层被有意标为低置信度：被读取的环境是*服务器*此刻的环境，未必是该运行
启动时所处的环境。第 5 层不可变，因为一次运行的执行模式在启动时就已固定
（resume 阶段的调和只允许降级）。

**B）新运行**（`POST /api/v1/run-drafts/{draft_id}/resolve-config`）—— 预览
一个尚不存在的运行：

| # | 层 | `source` |
|:--:|---|---|
| 1 | pydantic 默认值 | `default` |
| 2 | **捆绑的** `config/workflow.yaml` | `workflow` |
| 3 | 选定的执行环境 profile（`--profile laptop\|hpc\|cloud`） | `profile` |
| 4 | project 配置文档 | `project` |
| 5 | run 模板文档 | `template` |
| 6 | run 草稿文档 | `draft` |
| 7 | 有文档记录的 `ARI_*` 环境变量覆盖 | `env`（置信度 low） |

随后是两个收尾步骤：

- **已校验的生效值** —— 合并后的值被构造成一个 `ARIConfig`；被 pydantic
  拒绝的值会回退到最后一个*有效*层的值，并附上一条 `rejected_override`
  溯源条目以及一条警告。被拒绝或被忽略的覆盖都会作为解释返回，绝不会被
  静默丢弃。
- **互锁解析** —— `ari.mode` + `rqgm.enabled` 与 `paper.mode` +
  `rqgm.paper.enabled` 必须一致。运行时对不匹配的处理是*警告 + 回退*
  （`simple_bfts` / `linear`），清单中展示的是**生效**模式。草稿校验
  （`POST /api/v1/run-drafts/{draft_id}/validate`）更严格：在那里不匹配是
  一个 `interlock_mismatch` **错误**，因此 GUI 会拒绝以不一致的意图启动。

> **已知缺口 (known gap) —— 没有 installation policy 这一层。** 这套控制平面
> 当初对标的解析链比上面的表多一步：在执行 profile 与 project 默认之间还有一层
> *installation policy*，让运维可以设置一个 project 文档无法覆盖的整机取值。
> 它没有被实现。`resolve_new_run_config` 恰好只走列出的那七层，`gui_store/`
> 只存放 project 配置、run 模板、run 草稿与启动记录，也没有任何路由读写
> installation 文档。`installation` 这个取值仍留在注册表的 `scope` 词汇表里，
> 并且恰好由一个叶子 `llm.api_key` 承载 —— 在那里它标记的是「这属于机器，不属于
> project」的 secret 路径语义，并不会选择某一个解析层。
> [GUI-ADR-12](../../adr/gui/GUI-ADR-12-config-store-location.md) 在其
> program-context 段落里引用了那条九步链；请把它读作计划的目标，而不是解析器的
> 行为。

> **4 键 profile 合并的注意事项。** `--profile` 并*不*对 profile YAML 做
> 深度合并。`_apply_profile`（`ari/cli/run.py`）恰好只合并四个键：
> `bfts.max_total_nodes`、`bfts.max_parallel_nodes`（历史写法
> `bfts.parallel`，仅在 `max_parallel_nodes` 缺失时才被接受）、
> `hpc.enabled` → `resources.hpc_enabled`，以及 `hpc.scheduler` →
> `resources.scheduler`。解析器精确复现这一行为，并发出一条警告列出
> **它忽略掉的其他每一个 profile 键**，这样一个不起作用的 profile 旋钮就是
> 可见的，而不是隐形的。profile 也不会被记录在检查点的任何地方 —— 对既有
> 运行而言，其影响只能通过 `launch_config.json` / 环境变量观察到。

其他有意存在的差距，每一处都以警告方式呈现而非静默差异：`skills` 自动发现
与 `allow_web` 阶段改写都是仅运行时的；检查点的 `settings.json` 不是一个
叠加层（它只通过启动时的环境变量转换抵达一次运行，而 `launch_config` 与
`env` 两层已经代表了这一点）。

### 溯源与置信度

每个已解析的叶子都携带一条溯源条目：

| 字段 | 含义 |
|---|---|
| `source` | 胜出的层。既有检查点词汇表：`default`、`workflow`、`launch_config`、`env`、`checkpoint_state`。新运行词汇表：`default`、`workflow`、`profile`、`project`、`template`、`draft`、`env`。 |
| `mutable` | 该值是否仍可更改。在新运行预览中，每个非 `read_only` 字段都是可变的（启动之前连 `new_run_only` 的窗口也还开着）；对既有检查点而言，持久化的模式是 `mutable: false`。 |
| `confidence` | 当源工件存在时为 `high`；环境叠加层（以及被重建的层）为 `low` —— 启动时的环境可能与被读取的环境不同。 |
| `rejected_override` | 仅新运行：当某一层的值被校验拒绝而保留了前一层的值时，为 `{source, value, reason, expected}`。 |

`source_stack` 列出实际参与的层。请注意这个有文档记录的不对称性：既有检查点
的 stack 总是包含 `env`（该叠加层总会被求值），而新运行的 stack 只列出实际
存在的层。

### `resolved_config.json`（启动清单）

`POST /api/v1/runs` 会把预览过的清单物化到检查点中，成为
`{ckpt}/resolved_config.json` —— 「被解析的清单在启动时成为现实」。它是增量
新增的：为了 legacy 展示路径，`launch_config.json` 仍会被写出。

```json
{
  "schema_version": 1,
  "resolver_version": "legacy-compatible-1",
  "run_id": "20260726T101500_matmul-9f3a12",
  "resolved_at": "2026-07-26T10:15:00Z",
  "digest": "sha256:1f0c…",
  "source_stack": ["default", "workflow", "profile", "draft"],
  "values":   { "bfts": { "max_total_nodes": 24 }, "...": "..." },
  "provenance": { "bfts.max_total_nodes": { "source": "draft", "mutable": true, "confidence": "high" } },
  "secret_references": { "llm.api_key": { "provider": "env", "configured": true } },
  "warnings": ["profile 'hpc': ignored non-merged keys …"]
}
```

值得知道的规则：

- **secret 在结构上被排除。** 注册表敏感度为 `secret_reference` 的叶子绝不会
  出现在 `values`、`provenance` 或摘要输入中；它们只以 `secret_references`
  条目形式出现，携带 `{provider, configured}` —— 根本不存在可供泄漏的值字段。
- **`digest` = 仅对 `values` 的规范 JSON 求 `sha256:`**（`sort_keys=True`、
  无空白、`ensure_ascii=False`）。由于 secret 已被排除，摘要是在脱敏后的
  文档上计算的，而有文档记录的 `ARI_*` 家族之外的环境噪声永远不会影响它。
  两份完全相同的配置在任何机器上都会产生相同的摘要。
- **解析器内部没有时钟。** `resolved_at` 由调用方从源文件的 mtime 填入，绝不
  使用 `now()`，因此重复 GET 的结果逐字节稳定。

### GUI 文档存储（`gui_store/`）

仅供 GUI 使用的配置文档与检查点放在一起，绝不放在全局 home 目录：

```
{workspace_root}/gui_store/
├── project_config.json              # the single default project's config
├── run_templates/{template_id}.json
├── run_drafts/{draft_id}.json
└── launches/{idempotency_key}.json  # idempotent-launch records
```

| 属性 | 契约 |
|---|---|
| 信封 | `{"schema_version": 1, "kind": ..., "revision": n, "body": {...}}`，确定性序列化（`sort_keys`、2 空格缩进、末尾换行）。 |
| `revision` | 每文档一个整数，从 1 开始，每次写入递增；它就是 HTTP API 的 `If-Match` 令牌（`0` 表示「必须尚不存在」）。 |
| 持久性 | 同目录临时文件 + `fsync` + `os.replace`（外加尽力而为的目录 fsync）：写入中途崩溃会保留前一版文档的字节完整性。 |
| 权限 | 文件 `0o600`，存储目录 `0o700`。 |
| ID | 由调用方提供并按 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` 校验 —— 不含 `/`、不含 `.`，因此路径穿越在结构上不可能发生。草稿 id 由服务端生成（`draft-<12 hex>`）。 |
| 根目录 | `RuntimePathResolver.resolve_workspace_root()` —— 与每个 workspace 消费者相同的策略（`ARI_CHECKPOINT_DIR` 胜出）。 |

**CLI 从不读取 `gui_store/`。** 它是一个 GUI 便利层：模板的寿命长于它们所
派生的运行，而启动会像以前一样把每个生效值物化进检查点。`ari.viz.v1` 之外的
`ari/` 中没有任何东西导入该存储。

**已知缺口 (known gap) —— 原子性不等于备份。** 这个存储给你的是一把锁、一个
同目录临时文件、`fsync`、一次原子 rename 以及仅属主可读写的权限；它不给你备份。
没有文档的第二份副本，没有可以逐步回退的修订历史（`revision` 是乐观并发的令牌，
不是可以恢复的版本），也没有任何路由能把文档导出以作保全、或用于退回 legacy
文件。确实成立的两条保证比备份要窄，值得精确陈述：由于 rename 是唯一的变更，
写入中途崩溃会让*前一版*文档保持字节完整；以及 JSON 或 `revision` 不可读的文档
会抛出 `CorruptDocument`，而不是被悄悄当作不存在，因此损坏的文件不会被误认成
一个全新的文件。覆盖一个已损坏的文档需要一次无条件写入
（`expected_revision=None`），此时它的 revision 会从 1 重新开始。

### legacy Settings 键：实际接线情况

legacy 的 `GET/POST /api/settings` 接口面已冻结（其精确的键集合、默认值与
保存路径行为由 `ari-core/tests/test_gui_baseline_settings_contract.py`
固定），连同其怪癖一起冻结。下面的一切都是**实测到的冻结行为** —— 记录在
这里是因为测试依赖它、运维会被它绊倒，而不是因为它值得效仿。阅读 Settings
页面时有六点尤为重要：

这份契约在线路的**两侧**都被钉住了，而且这两个钉子并不在同一个地方运行。服务端
由 `ari-core/tests/test_gui_baseline_settings_contract.py` 冻结键集合、默认值与
保存路径行为。客户端由
`ari-core/ari/viz/frontend/src/components/Settings/__tests__/SettingsContract.test.tsx`
断言 Save 会 POST 一个恰好带那 24 个键的扁平对象 —— 以及作为第二条、也弱得多的
不变式，断言该页面渲染出十个 `<Card>` 区块。这个 DOM 计数是对当前 Settings 布局
的结构性冻结，而不是线路契约：即便一次重新设计保住了 24 键的请求体，也仍然要去
改这个数字。现在两个钉子都会在 PR 时运行。Python 那一侧的钉子与其他测试跑在
同一套 pytest 里；前端那一侧的钉子跑在 `dashboard-frontend` workflow
（`.github/workflows/dashboard-frontend.yml`）里，它的 `npm test` 步骤会在每个
指向 `main` 的 pull request 上完整运行 Vitest 套件，且没有任何
`continue-on-error`，因此只破坏契约客户端一半的改动会让该门禁失败。

**1. GET 与 POST 的键集合并不一致。** `GET /api/settings` 恰好返回 **27** 个
顶层键（26 个标量/列表 + 嵌套的 `ors` 对象，后者含 10 个子键）；Save 按钮
恰好 POST **24** 个扁平键，而且 `POST` 是*整文件替换*（请求体中缺失的键会被
从 `settings.json` 中抹去）。共享的键有 16 个：

| 仅在 POST 请求体中（8） | 仅在 GET 响应中（11） |
|---|---|
| `llm_backend`、`llm_base_url`、`ssh_host`、`ssh_port`、`ssh_user`、`ssh_path`、`ssh_key`、`slurm_partitions` | `llm_provider`、`ollama_host`、`mcp_skills`、`slurm_gpus`、`vlm_review_enabled`、`vlm_review_max_iter`、`vlm_review_threshold`、`letta_deployment`、`letta_deployment_image`、`letta_deployment_venv`、`ors` |

后果：provider 以 `llm_backend` 写入，却以 `llm_provider` 读回，这正是为什么
当已保存的值为 falsy 时，GET 的合并逻辑会从 `workflow.yaml` 重新强制
`llm_provider`（与 `llm_model`）—— 也就是上文优先级一节提到的
「falsy 重新强制怪癖」。

**2. 有些键只是装饰性的。** 它们会被持久化并渲染，但没有任何运行时读取
它们：

| Settings 键 | 状态 | 详情 |
|---|---|---|
| `temperature` | **失效** | 从不导出到启动环境，也不存在对应的 `ARI_*` 钩子；一次运行保持 pydantic 的 `llm.temperature` 默认值。（规范配置 API *确实*会应用 `llm.temperature` 叶子 —— 两条路径在这里的差异是冻结设计的产物。） |
| `container_pull` | **两条路径上都失效** | 从不导出到环境变量，也不存在对应的规范配置叶子。 |
| `retrieval_backend` | **在 `workflow.yaml` 中是装饰性的** | 该值在启动时*确实*被导出为 `ARI_RETRIEVAL_BACKEND`，但 `retrieval` 是一个无类型的顶层 workflow 键，没有类型化叶子 —— 注册表只是预先声明了它。 |
| `slurm_partition` / `slurm_cpus` / `slurm_memory_gb` / `slurm_walltime` | **仅作预填** | SLURM 卡片中的值从不抵达启动环境。`slurm_cpus` / `slurm_memory_gb` / `slurm_walltime` 用于预填向导的 HPC 步骤；真正被使用的是向导自身的值。 |
| `slurm_partitions` | **仅 UI 本地** | 这是 Settings 页面的一个多选控件状态；向导的分区列表改为来自 `GET /api/slurm/partitions` 的探测结果。 |
| `container_mode` / `container_image` / `vlm_review_model` / `letta_*` | **仅环境变量** | 会被导出为 `ARI_CONTAINER_MODE` / `ARI_CONTAINER_IMAGE` / `VLM_MODEL` / `LETTA_*`，但对应的 workflow 块是无类型的 `extra="allow"` 区段，因此字段注册表尚无对应的类型化叶子。 |
| `letta_api_key` | **被冻结的缺陷** | 以明文原样持久化进 `settings.json`。规范配置 API 拒绝在 `values` 中出现 secret；请改用 `PUT /api/v1/secrets/{secret_id}`。 |

**3. 被冻结的不只是键名，还有默认*值*。**
`_api_get_settings`（`ari/viz/api_settings.py`）构造出一个字面量 `defaults`
字典，`test_frozen_default_values` 固定了它的内容。请把它们读作「没有任何
东西会重新推导的固定字面量」—— 它们不是调优后的推荐值，也没有任何运行时
依据它们做决定。

二十个顶层槽位与五个 `ors` 子键是纯常量：

| 键 | 冻结值 |
|---|---|
| `llm_api_key` | `""` |
| `semantic_scholar_key` | `""` |
| `temperature` | `1.0` |
| `slurm_partition` | `""` |
| `slurm_cpus` | `null` |
| `slurm_memory_gb` | `null` |
| `slurm_gpus` | `0` |
| `slurm_walltime` | `"04:00:00"` |
| `mcp_skills` | `[]` |
| `container_mode` | `"auto"` |
| `container_image` | `""` |
| `container_pull` | `"on_start"` |
| `vlm_review_enabled` | `true` |
| `vlm_review_model` | `"openai/gpt-4o"` |
| `vlm_review_max_iter` | `3` |
| `vlm_review_threshold` | `0.7` |
| `letta_deployment` | `"auto"` |
| `letta_deployment_image` | `""` |
| `letta_deployment_venv` | `""` |
| `letta_api_key` | `""` |
| `ors.rubric_gen_temperature` | `0.0` |
| `ors.rubric_gen_target_leaves` | `0` |
| `ors.rubric_gen_two_stage` | `true` |
| `ors.judge_n_runs` | `3` |
| `ors.phase1_max_runtime_sec` | `21600` |

其余六个顶层槽位与五个 `ors` 子键是**环境变量优先**的；被冻结的只是回退值，
所以不要把它们当常量引用：

| 键 | 优先读取 | 该变量未设置时的取值 |
|---|---|---|
| `ollama_host` | `OLLAMA_HOST` | `"http://localhost:11434"` |
| `retrieval_backend` | `ARI_RETRIEVAL_BACKEND` | `"semantic_scholar"` |
| `letta_base_url` | `LETTA_BASE_URL` | `"http://localhost:8283"` |
| `letta_embedding_config` | `LETTA_EMBEDDING_CONFIG` | `"letta-default"` |
| `ors.replicator_model` | `ARI_MODEL_REPLICATE` | `"claude-opus-4-7"` |
| `ors.rubric_gen_model` | `ARI_MODEL_RUBRIC_GEN` | `"gemini/gemini-2.5-pro"` |
| `ors.rubric_audit_model` | `ARI_MODEL_RUBRIC_AUDIT` | `"claude-opus-4-7"` |
| `ors.judge_model` | `ARI_MODEL_JUDGE` | `"gpt-4o-2024-11-20"` |
| `ors.phase1_sandbox_kind` | `ARI_PHASE1_SANDBOX` | `"auto"` |
| `llm_model` | `ARI_LLM_MODEL` | 包内自带 `workflow.yaml` 的 `llm.model`，否则 `""` |
| `llm_provider` | `ARI_BACKEND` | 包内自带 `workflow.yaml` 的 `llm.backend`，否则 `""` |

有两个细节表格无法呈现。那九个 `os.environ.get(VAR, 字面量)` 槽位只有在变量
**不存在**时才回退 —— 被设为空字符串的变量会得到 `""`，而不是字面量。
`llm_model` / `llm_provider` 用的是 `os.environ.get(VAR, "") or …`，因此只有
这两个在变量为空时也会继续回退。契约测试之所以能看到这些冻结字面量，仅仅是
因为它的 `_clean_env` fixture 先删掉了全部十一个变量；在开发者的 shell 上
payload 会不一样。

**4. `api_key` 不会进入 `settings.json` —— 它写入 `.env` 文件并写进存活的
服务器进程。** `POST /api/settings` 会从请求体里 pop 掉 `api_key`（其次是
`llm_api_key`），并且无条件再 pop 一次，因此两者都不会被持久化。只有当该值
通过下面第 5 点的可信度守卫，*并且* provider 能映射到某个环境变量名时，
`_upsert_env_key(name, key, quote=False)` 才会执行。这个 helper 会：

- 重写目标文件中 strip 之后以 `NAME=` 开头的**每一**行；若一行都没有则追加
  一行。（helper 自己的 docstring 写的是「第一行」；但循环没有提前退出，因此
  一个已经含有重复 `NAME` 条目的文件会被全部重写。）；
- 原子写入 —— 同目录 `mkstemp`、`fchmod 0o600`、`fsync`、`os.replace`，最后
  尽力而为地 `chmod 0o600`；
- 渲染**不带引号**的 `NAME=value` 形式。写 `NAME="value"`（`quote=True`）的
  是环境变量编辑器与 `PUT /api/v1/secrets/{secret_id}`，两者走同一个 helper。
  helper 的 docstring 记录了：这两个调用方在历史上只有引号这一点不同，统一
  它属于行为变更；
- 最后在**存活的服务器进程**中设置 `os.environ[name] = value`。一次设置保存
  改写的不只是文件，还有实时环境。

写入目标是模块级全局 `ari.viz.state._env_write_path`，它在 import 时被一次性
绑定到 ARI 仓库根目录的 `.env`。`set_active_checkpoint` 只重绑
`_checkpoint_dir` 与 `_settings_path`，不碰 `_env_write_path`，而 `ari/` 下也
没有任何代码重新赋值它 —— 所以这是**仓库根目录**的 `.env`，不是所选
checkpoint 的。（契约测试看起来写的是 checkpoint 本地的 `.env`，只是因为它的
fixture monkeypatch 了那个全局量。）规范路由抵达的是同一个文件：参见
[Configuration Studio](../guides/configuration_studio.md) 的 *secret 如何工作*。

**5. 怪癖 —— api key 被静默丢弃的三条路径。** 整个 `.env` 分支挂在一个条件
上：`if _raw_key and "test" not in _raw_key and len(_raw_key) >= 20:`，其后是
在一个内联 dict 中查找 provider。既没有 `else` 分支，也没有日志行，响应里
也没有对应字段，因此下面每一种情况都会整块跳过写入；只要存在活动的
checkpoint，handler 随后仍会返回 `{"ok": true}`：运维被告知保存成功，而凭据
已被丢掉。

| 丢弃的条件 | 详情 |
|---|---|
| key 短于 20 个字符 | `20` 是写死在条件里的魔数 —— 没有具名常量，没有配置开关，也没有提示信息。 |
| key 中任意位置出现 `test` | 对整个 key 做区分大小写的子串判断，且在长度检查之前生效。一个恰好含有这四个字符的真实凭据，会像占位符一样被丢弃；而 `TEST` 根本不会命中。 |
| provider 不在映射表中 | 映射为 `openai` → `OPENAI_API_KEY`；`anthropic`、`claude_code`、`claude-code` → `ANTHROPIC_API_KEY`；`gemini` → `GOOGLE_API_KEY`。五种写法，三个变量。`.get(provider, "")` 对其它一切（`ollama`、vLLM，以及所有其它 OpenAI 兼容的 `base_url` 后端）返回 `""`，写入被跳过。 |

这三条都是被测试固定下来的长度与子串启发式。它们既不是校验，也不是 secret
检测，请勿如此描述。这张映射表同时也是这条路由的全部覆盖范围：
`GEMINI_API_KEY`、`SEMANTIC_SCHOLAR_API_KEY`、`LETTA_API_KEY`、`ZENODO_TOKEN`
和 `ARI_REGISTRY_TOKEN` 都在 v1 secret 白名单
（`ari/viz/v1/secrets.py`）中，却没有一个能从这里抵达。

怪癖 1 的一个后果落在这条路径上。provider 名读作
`data.get("llm_provider", "") or data.get("llm_backend", "")`，而前端 24 键的
Save 请求体带的是 `llm_backend`、没有 `llm_provider` —— 因此真实 Settings
页面的每一次保存都是通过*回退*那一支来解析 provider 的。正是这个回退让 GUI
能够配置 key；若两个键都缺失或为 falsy，provider 就是 `""`，映射到 `""`，
key 被丢弃。

**6. 怪癖 —— 被拒绝的保存并不是 no-op。** `_api_save_settings` 的执行顺序
是：解析请求体 → `retrieval_backend` 守卫 → pop api key 并做 `.env` upsert →
活动 checkpoint 检查 → 写 `settings.json`。因此两种拒绝留下的痕迹不同：

| 拒绝（两者 `_status` 均为 400） | 副作用 |
|---|---|
| `{"ok": false, "error": "retrieval_backend must select one pinned provider"}` —— 请求体带了一个不属于 `semantic_scholar`、`arxiv`、`alphaxiv` 的 `retrieval_backend`（该键缺失则放行） | 无。它在读取 key 之前就返回了。 |
| `{"ok": false, "error": "No active project. Create or select a checkpoint before saving settings."}` —— `state._settings_path` 为 `None` | key **已经**被写入 `.env` 并导出到 `os.environ`。`_env_write_path` 与 `_settings_path` 是彼此独立的状态，因此在没有选中 checkpoint 时它依然可写。 |

需要记住的是第二行：这个端点返回 400 并不意味着「什么都没发生」—— 无论如何
secret 都已经在磁盘上、也已经在进程里。它就这样被冻结；调整 handler 的顺序
属于行为变更。

24 个 POST 键、legacy 启动环境变量导出与规范配置叶子三者之间的重叠关系 ——
包括上面每一处分歧 —— 都由
`ari-core/tests/test_gui_config_shadow_legacy.py` 逐条断言。

## workflow.yaml（权威开发者配置）

`workflow.yaml` 是整个 ARI 流水线的**唯一真实来源**。
将其放置在 `ari-core/config/workflow.yaml`。

在技能路径中使用 `{{ari_root}}` — 它会解析为 `$ARI_ROOT` 环境变量或项目根目录。

```yaml
llm:
  backend: openai          # ollama | openai | anthropic
  model: gpt-5.2           # Model identifier
  base_url: ""             # Leave empty for OpenAI; set for Ollama/vLLM

author_name: "Autonomous Research Infrastructure"

resources:
  cpus: 48                 # Default CPU count for reproducibility experiments
  timeout_minutes: 60      # Default job timeout
  executor: slurm          # Job executor: slurm / local / pbs / lsf

# BFTS 阶段（在树搜索期间按顺序执行）
bfts_pipeline:
  - stage: generate_idea
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
  - stage: select_and_run
    skill: hpc-skill
    phase: bfts
  - stage: evaluate
    skill: evaluator-skill
    tool: ''                   # 仅用于展示的行：评估由 ari-core 的进程内
                               # LLMEvaluator 负责，而不是某个 MCP 工具
    phase: bfts
  - stage: frontier_expand
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
    loop_back_to: select_and_run

# Post-BFTS 流水线阶段
pipeline:
  - stage: search_related_work
    skill: web-skill
    tool: search_papers
    params:
      provider: semantic-scholar
      max_results: 15
      mode: record
    skip_if_exists: '{{ckpt}}/related_refs.json'
    # ...
  - stage: transform_data
    skill: transform-skill
    tool: nodes_to_science_data
    inputs:
      nodes_json_path: '{{ckpt}}/nodes_tree.json'
      llm_model: '{{llm.model}}'
      llm_base_url: '{{llm.base_url}}'
    outputs:
      file: '{{ckpt}}/science_data.json'
    skip_if_exists: '{{ckpt}}/science_data.json'
  - stage: generate_figures
    skill: plot-skill
    tool: generate_figures_llm
    depends_on: [transform_data]
    # ...
  - stage: write_paper
    skill: paper-skill
    tool: write_paper_iterative
    depends_on: [search_related_work, generate_figures]
    # ...
  - stage: review_paper
    skill: paper-skill
    tool: review_compiled_paper
    depends_on: [write_paper]
    # ...
  # ─── EAR 策展/发布/最终化 (v0.7.0) ───
  - stage: ear_curate
    skill: transform-skill
    tool: curate_ear
    depends_on: [generate_ear]
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'
    outputs:
      file: '{{checkpoint_dir}}/ear_curate.status.json'
  - stage: finalize_paper
    skill: paper-skill
    tool: inject_code_availability
    depends_on: [write_paper, ear_curate]
    # 从 ear_published/manifest.lock 与 publish_record.json 自动加载
    # ref/sha/doi，将 \codeavailability/\codedigest/\coderef 宏注入
    # full_paper.tex；若无策展过的 bundle 则静默跳过。
  - stage: ear_publish
    skill: transform-skill
    tool: publish_ear
    depends_on: [ear_curate]
    enabled: false           # 默认禁用；置 true 或传 publish=true
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'
      backend: ari-registry
      visibility: staged
      dry_run: false
    outputs:
      file: '{{checkpoint_dir}}/publish_record.json'
  - stage: merge_reviews
    skill: paper-skill
    tool: merge_reviews
    depends_on: [review_paper, vlm_review_figures]
    # 文本与 VLM 评审结果的事后结构合并（无 LLM）。

  # ─── ORS 自动 rubric 可复现性（PaperBench, v0.7.0）───
  # 取代旧的 `reproducibility_check`。
  # 在 node 产物成为论文证据之前，用记录的 sha256 重新校验。
  # {{run_id}}/{{experiments_root}} 由 driver 从 checkpoint_dir 解析
  # (tree.json 优先于目录名)。
  - stage: audit_node_provenance
    skill: memory-skill
    tool: audit_memory
    depends_on: []
    inputs:
      experiments_root: '{{experiments_root}}'
      run_id: '{{run_id}}'
  - stage: ors_generate_rubric
    skill: replicate-skill
    tool: generate_rubric
    depends_on: [write_paper]
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      output_path: '{{checkpoint_dir}}/ors_rubric.json'
      target_leaf_count: 0     # 0 = 按论文长度自动估算
  - stage: ors_audit_rubric    # 对评分所依据的 rubric 本身做质量审计
    skill: replicate-skill
    tool: audit_rubric
    depends_on: [ors_generate_rubric]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'   # 就地写入标记
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
  - stage: ear_publish          # v0.7.0+：默认启用，使用 local-tarball
    skill: transform-skill
    tool: publish_ear
    depends_on: [ear_curate]
    enabled: true
    inputs:
      backend: local-tarball    # 零依赖；在 checkpoint 旁生成 bundle.tar.gz
      visibility: staged
  - stage: ors_seed_sandbox     # v0.7.0+：从 EAR bundle 确定性播种到沙箱
    skill: paper-re-skill
    tool: fetch_code_bundle
    depends_on: [ear_publish]
    inputs:
      checkpoint_dir: '{{checkpoint_dir}}'    # 从 publish_record.json 自动读取 ref
      dest: '{{checkpoint_dir}}/repro_sandbox'
  - stage: ors_build_reproduce  # v0.7.0+：LLM 回退（如已 seed 则跳过）
    skill: paper-re-skill
    tool: build_reproduce_sh
    depends_on: [ors_audit_rubric, ors_seed_sandbox, finalize_paper]
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      output_dir: '{{checkpoint_dir}}/repro_sandbox'
      overwrite: false
  - stage: ors_run_reproduce
    skill: paper-re-skill
    tool: run_reproduce        # Phase 1（在沙箱中执行 reproduce.sh）
    depends_on: [ors_audit_rubric, ors_build_reproduce]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      repo_dir: '{{checkpoint_dir}}/repro_sandbox'
      sandbox_kind: ''         # auto: slurm → docker → apptainer → singularity → local
      timeout_global_sec: 0    # 0 = 使用 rubric.reproduce_contract.max_runtime_sec
      partition: ''            # 留空 → ARI_SLURM_PARTITION → launch_config.json
      cpus: 0                  # 留空 → ARI_SLURM_CPUS（默认 8）
      walltime: ''             # 留空 → ARI_SLURM_WALLTIME → 由 timeout 推导
  - stage: ors_grade
    skill: paper-re-skill
    tool: grade_with_simplejudge   # Phase 2（PaperBench SimpleJudge via LiteLLM）
    depends_on: [ors_run_reproduce]
    inputs:
      rubric_path: '{{checkpoint_dir}}/ors_rubric.json'
      repo_dir: '{{checkpoint_dir}}/repro_sandbox'
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
      n_runs: 3
      judge_model: gpt-5-mini  # 任意 LiteLLM 可识别的模型 ID

retrieval:
  backend: semantic_scholar    # semantic_scholar | alphaxiv | both
  alphaxiv_endpoint: https://api.alphaxiv.org/mcp/v1

# ── 论文审阅 (基于评审规范，AI Scientist v1/v2 兼容) ─────────────────
# 通过 CLI 标志（--rubric、--fewshot-mode、--num-reviews-ensemble、
# --num-reflections）或环境变量（ARI_RUBRIC、ARI_FEWSHOT_MODE、
# ARI_NUM_REVIEWS_ENSEMBLE、ARI_NUM_REFLECTIONS）覆盖。
# ari-core/config/reviewer_rubrics/ 中内置 23 个 YAML 评审规范：
#   neurips（默认，v2 兼容）| iclr | icml | cvpr | acl | sc | osdi
#   | usenix_security | stoc | siggraph | chi | icra | nature
#   | journal_generic | workshop | generic_conference
#   | aer | ahr | apsr | econometrica | philreview | pmla | qje
# 加上内置的 `legacy` 回退（v0.5 schema）。新 venue 只需把 <id>.yaml
# 放进 reviewer_rubrics/ 即可，无需修改代码。
#
# Few-shot 语料库管理
# ------------------
# reviewer_rubrics/fewshot_examples/<rubric>/ 下的文件可通过 GUI
# (New Experiment 向导 → Paper Review → Few-shot 示例) 或
# scripts/fewshot/sync.py 管理。viz 服务器暴露的 REST 端点：
#   GET  /api/rubrics                           rubric 列表（向导用）
#   GET  /api/fewshot/<rubric>                  fewshot 示例列表
#   POST /api/fewshot/<rubric>/sync             从 manifest.yaml 拉取
#   POST /api/fewshot/<rubric>/upload           上传一个示例
#   POST /api/fewshot/<rubric>/<example>/delete 删除一个示例

memory:
  # v0.6.0: Letta 是唯一的生产后端。这里的值会在加载时被注入到
  # 技能子进程的环境变量中。智能体的聊天 LLM 句柄已固定为
  # `letta/letta-free`，因为 ari-skill-memory 只调用
  # archival_insert / archival_search 而从不发送聊天消息，
  # 因此该选择器没有运行时效果。
  backend: letta
  letta:
    base_url: http://localhost:8283
    collection_prefix: ari_
    embedding_config: letta-default

container:
  mode: auto                   # auto | docker | singularity | apptainer | none
  image: ""                    # 容器镜像名（空 = 不使用容器）
  pull: on_start               # always | on_start | never

skills:
  # `phase` 控制 ReAct 智能体在哪些 pipeline-phase 下能看到该技能的
  # MCP 工具。字符串仅加入一个 phase，数组可加入多个 phase。标注
  # `reproduce` 的技能会暴露给可复现性 ReAct(见上方 reproducibility_check
  # stage)。`memory-skill` / `transform-skill` / `evaluator-skill`
  # 被刻意排除在 reproduce 之外，以防止智能体访问 BFTS 阶段的产物。
  - name: web-skill
    path: "{{ari_root}}/ari-skill-web"
    phase: [paper, reproduce]
  - name: plot-skill
    path: "{{ari_root}}/ari-skill-plot"
    phase: paper
  - name: paper-skill
    path: "{{ari_root}}/ari-skill-paper"
    phase: paper
  - name: paper-re-skill
    path: "{{ari_root}}/ari-skill-paper-re"
    phase: paper
  - name: memory-skill
    path: "{{ari_root}}/ari-skill-memory"
    phase: bfts
  - name: evaluator-skill
    path: "{{ari_root}}/ari-skill-evaluator"
    phase: bfts
  - name: idea-skill
    path: "{{ari_root}}/ari-skill-idea"
    phase: bfts
  - name: hpc-skill
    path: "{{ari_root}}/ari-skill-hpc"
    phase: [bfts, reproduce]
  - name: coding-skill
    path: "{{ari_root}}/ari-skill-coding"
    phase: [bfts, reproduce]
  - name: transform-skill
    path: "{{ari_root}}/ari-skill-transform"
    phase: paper
  - name: benchmark-skill
    path: "{{ari_root}}/ari-skill-benchmark"
    phase: bfts
  - name: vlm-skill
    path: "{{ari_root}}/ari-skill-vlm"
    phase: [paper, reproduce]
  # v0.7.0：PaperBench 形式自动 rubric 生成与审计
  - name: replicate-skill
    path: "{{ari_root}}/ari-skill-replicate"
    phase: paper
```

## 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `ARI_MAX_NODES` | BFTS 最大探索节点数 | `50` |
| `ARI_PARALLEL` | 并发节点执行数 | `1` |
| `ARI_EXECUTOR` | 执行后端：`local`、`slurm`、`pbs`、`lsf` | `local` |
| `ARI_SLURM_PARTITION` | SLURM 分区名称 | （无） |
| `ARI_SLURM_CPUS` | 覆盖 SLURM 作业的 CPU 数 | （自动检测） |
| `SLURM_LOG_DIR` | SLURM 输出文件存放位置 | （无） |
| `OLLAMA_HOST` | Ollama 服务器地址 | `127.0.0.1:11434` |
| `OPENAI_API_KEY` | OpenAI API 密钥 | （无） |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | （无） |
| `ARI_RETRIEVAL_BACKEND` | 论文搜索后端: `semantic_scholar` / `alphaxiv` / `both` | `semantic_scholar` |
| `VLM_MODEL` | 图表审阅 VLM 模型 | `openai/gpt-4o` |
| `ARI_ORCHESTRATOR_PORT` | orchestrator 技能的 HTTP 端口 | `9890` |
| `LETTA_BASE_URL` | Letta 服务器端点 | `http://localhost:8283` |
| `LETTA_API_KEY` | Letta Cloud 必需 | （无） |
| `LETTA_EMBEDDING_CONFIG` | 归档内存使用的嵌入句柄（智能体的聊天 LLM 不被 ARI 调用，已固定为 `letta/letta-free`） | `letta-default` |
| `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA` | `auto` / `pip` / `docker` / `singularity` / `none` | `auto` |
| `ARI_MEMORY_LETTA_TIMEOUT_S` | 单次调用超时 | `10` |
| `ARI_MEMORY_LETTA_OVERFETCH` | 祖先后过滤的 over-fetch K 值 | `200` |
| `ARI_MEMORY_LETTA_DISABLE_SELF_EDIT` | 禁用 Letta self-edit (CoW 安全) | `true` |
| `ARI_MEMORY_ACCESS_LOG` | 启用 `{checkpoint}/memory_access.jsonl` | `on` |
| `ARI_MEMORY_AUTO_RESTORE` | `ari resume` 时自动恢复备份 | `true` |
| `ARI_RUBRIC` | BFTS 动态打分轴（Phase 3）与 lineage 判定阈值读取的 rubric_id（例 `neurips`、`sc`、`nature`）。论文评审不再读取它：`review_paper` 从 `workflow.yaml` 顶层的 `paper_rubric` 取得显式 `rubric_id`，而 `resolve_rubric` 对空 id 直接拒绝，不回退到环境变量 | `neurips` |
| `ARI_FEWSHOT_MODE` | `static` / `dynamic` | `static` |
| `ARI_NUM_REVIEWS_ENSEMBLE` | 独立审稿人数量 | `1` |
| `ARI_NUM_REFLECTIONS` | self-reflection 循环轮数 | `5` |
| `ARI_MODEL_RUBRIC_GEN` | `replicate-skill.generate_rubric` 的生成 LLM (v0.7.0) | `gemini/gemini-2.5-pro` |
| `ARI_MODEL_RUBRIC_AUDIT` | `audit_rubric` 的审计 LLM（与生成器独立） | `anthropic/claude-opus-4-7` |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | 覆盖 `generate_rubric` 的目标叶数。`0` / 未设置时按论文长度自动（约 1 叶 / 75 词，限制在 [50, 400]）。GUI Wizard "Target leaves" 字段。 | (未设置) |
| `ARI_RUBRIC_GEN_TEMPERATURE` | 覆盖生成器 temperature。GUI Wizard "Temperature" 字段。 | (未设置) |
| `ARI_MODEL_REPLICATOR` | `build_reproduce_sh`（论文 → reproduce.sh，v0.7.0）的复现器 LLM。`ARI_MODEL_REPLICATE` 只是 GUI 设置键，由 GUI 映射到此名 | `gpt-5-mini` |
| `ARI_MODEL_JUDGE` | `grade_with_simplejudge`（PaperBench Phase 2, v0.7.0；LiteLLM 路由，任意提供方均可）的裁判 LLM | `gpt-5-mini` |
| `ARI_MODEL_LINEAGE` | `decide_lineage_action` 的判定 LLM（lineage decision, v0.7.0）。未设置时按 `ARI_MODEL_EVAL` → `ARI_MODEL` → `ARI_LLM_MODEL` → `gpt-4o-mini` 顺序回退 | (auto) |
| `ARI_MODEL_ROOT_SELECT` | 从 VirSci 池中重选 `ideas[0]` 的 LLM（lineage decision, v0.7.0）。回退顺序与 `ARI_MODEL_LINEAGE` 相同 | (auto) |
| `ARI_PHASE1_SANDBOX` | Phase 1 沙箱：`auto` / `slurm` / `docker` / `apptainer` / `singularity` / `local` | `auto` |
| `ARI_SLURM_WALLTIME` | SLURM Phase 1 沙箱的 `--time` HH:MM:SS（v0.7.0, 已恢复）。留空则从 rubric 的 `max_runtime_sec` 推导。 | (auto) |
| `ARI_PHASE1_DOCKER_IMAGE` | docker 沙箱镜像 | (无 —— 未设置则拒绝) |
| `ARI_PHASE1_APPTAINER_IMAGE` | Apptainer/Singularity 沙箱镜像 | (无 —— 未设置则拒绝) |
| `ARI_PUBLISH_DRYRUN` | 强制 `ari ear publish --dry-run`（CI 安全开关, v0.7.0） | (off) |
| `ARI_REGISTRY_DATA` | `ari registry serve` 的 sqlite + artifact 存储根目录 | (无 — 必须显式设置。v0.5.0 以前的 `$HOME/.ari/registry-data` 回退会发出 DeprecationWarning，v1.0 中移除) |
| `ARI_REGISTRY_TOKEN` | 用于 `ari clone ari://...` / `ari ear publish --backend ari-registry` 的 bearer token | (无) |
| `ARI_REPRO_CLONE_POLICY` | 可复现性沙箱 git shim 策略：`passthrough` / `deny` / `warn` | `passthrough` |

## 记忆后端 (Letta)

v0.6.0 用 [Letta](https://docs.letta.com) 替换了原本的确定性 JSONL 记忆
存储。Letta 可在以下四种模式下运行：

| 模式 | 要求 | 存储 | 备注 |
|------|------|------|------|
| Docker Compose | `docker` + `docker compose` | Postgres | 笔记本默认，支持 pre-filter |
| Singularity / Apptainer | `singularity` / `apptainer` | Postgres | HPC 默认，SLURM 感知的数据目录 |
| pip（无容器） | Python 3.10+ | SQLite | 祖先作用域回落到 over-fetch + post-filter |
| Letta Cloud | API key | 托管 | `LETTA_BASE_URL=https://api.letta.com` |

`ari setup` 自动检测最佳模式。也可通过 `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA`
强制指定。start/stop/health/backup/restore 由 `ari memory` 子命令处理 —
详情见 `docs/zh/reference/cli_reference.md`。

一次性迁移 v0.5.x 检查点：

```bash
ari memory migrate --checkpoint /path/to/ckpt --react
```

## LLM 后端

### Ollama（本地，推荐用于离线 HPC）

```yaml
llm:
  backend: ollama
  model: qwen3:32b
  base_url: http://127.0.0.1:11434
```

### OpenAI

```yaml
llm:
  backend: openai
  model: gpt-4o
```

### Anthropic

```yaml
llm:
  backend: anthropic
  model: claude-sonnet-4-5
```

### Claude Code（claude_code）

将本地安装的 Claude Code 作为无状态 LLM API 使用（不启用工具、MCP、记忆或
会话复用）。完整参考：
[claude_code_provider.md](./claude_code_provider.md)。

```yaml
llm:
  backend: claude_code
  model: claude-sonnet-5
  claude_code:
    mode: strict_reproducibility   # 或 low_overhead（Agent SDK 常驻 worker）
    max_turns: 1
    timeout_sec: 300
    record_provenance: true
    # bare: true                   # 默认 auto：仅当设置了 ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN 时为 true
    # structured_output_transport: prompt   # 或 native（--json-schema）
```

环境变量覆盖：`ARI_CLAUDE_CODE_MODE`、`ARI_CLAUDE_CODE_MODEL`、
`ARI_CLAUDE_CODE_MAX_TURNS`、`ARI_CLAUDE_CODE_TIMEOUT_SEC`、
`ARI_CLAUDE_CODE_RECORD_PROVENANCE`、`ARI_CLAUDE_CODE_BIN`。健康检查：
`ari doctor claude-code [--live]`。注意：在此后端下 MCP 技能不经过
Claude Code —— 其直接的 litellm 调用会路由到普通 Anthropic API（需要
`ANTHROPIC_API_KEY`）；ReAct 代理阶段需要支持工具调用的后端（传入
`tools=` 会立即报错）。

### 任何 OpenAI 兼容 API（vLLM、LM Studio 等）

```yaml
llm:
  backend: openai
  model: your-model-name
  base_url: http://your-server:8000/v1
```

---

## workflow.yaml 中的模板变量

`inputs:` 中的任何值都支持 `{{variable}}` 替换：

| 变量 | 值 |
|------|-----|
| `{{ckpt}}` | 检查点目录路径 |
| `{{checkpoint_dir}}` | 与 `{{ckpt}}` 同值（两者都已绑定；多数阶段使用此拼写） |
| `{{run_id}}` | 运行 ID。优先读取 `{checkpoint_dir}/tree.json`，否则取目录名。`ari resume` 会把 `checkpoint.dir` 指向改名后的目录，此时两者会不一致 |
| `{{experiments_root}}` | `{workspace_root}/experiments` — 每个节点的工作树，是 `checkpoints/` 的同级目录，由 `ari.paths.PathManager` 解析。节点目录为 `{{experiments_root}}/{{run_id}}/<node_id>/` |
| `{{ari_root}}` | ARI 项目根目录（`$ARI_ROOT` 或自动检测） |
| `{{llm.model}}` | `llm:` 部分中的 LLM 模型名称 |
| `{{llm.base_url}}` | `llm:` 部分中的 LLM 基础 URL |
| `{{resources.cpus}}` | `resources:` 部分中的 CPU 数量 |
| `{{resources.timeout_minutes}}` | `resources:` 部分中的超时时间 |
| `{{stages.<name>.outputs.file}}` | 已完成阶段的输出文件路径 |
| `{{author_name}}` | 顶层配置中的作者名称 |
| `{{vlm_feedback}}` | VLM 审阅反馈（在从 `vlm_review_figures` 回环时注入） |
| `{{paper_context}}` | 面向科研的实验摘要 |
| `{{keywords}}` | LLM 生成的搜索关键词 |

---

## skip_if_exists 验证

带有 `skip_if_exists` 的阶段在以下情况下会**重新运行**：
- 输出文件不存在
- 输出文件为空
- 输出文件是包含顶层 `"error"` 键的 JSON 文件

这可以防止损坏的输出悄无声息地阻塞下游阶段。

---

## Plan Promote (v0.7.0+)

`plan_promote` 控制 VirSci 的 experiment plan 如何展开到检查点的
`experiment.md`。CLI 传入的用户源 `experiment.md` **不会被修改** —
只有检查点内的副本会被以 HTML 注释为边界自动追加块（重复运行幂等）。

```yaml
plan_promote: index_only          # full | index_only | off
```

| Mode | 内容 | 典型大小 |
|---|---|---|
| `full` | 选定 idea + plan §标题正文 + Alternatives | ~5 KB |
| `index_only` (default) | 选定 idea + plan §标题 + Alternatives | ~1.5 KB |
| `off` | 不追加 | 0 |

Phase 3 评估器和 BFTS expand idea_ctx 都从 `idea.json` 读取**原始** plan，
所以 `full` / `index_only` 主要是 experiment.md 中**人和 paper-skill 看到
什么**的差异。

## Lineage Decision (v0.7.0+)

BFTS 停滞时 LLM judge 决定继续 / 切换备选 idea / 并行 fanout / 终止。
LLM 输出限定为 4 个动作，target index 必须在备选池内，任何错误都
silently 降级为 `continue`，BFTS 循环不会因此 hook 卡住。

```yaml
lineage_decision:
  mode: stagnation_rule           # off | stagnation_rule | every_node
  stagnation_window: 5
  stagnation_threshold: 0.05
  min_nodes_before_decision: 3
  rate_limit_per_run: 5
```

| Mode | 触发 | 成本 |
|---|---|---|
| `off` | 不触发 | 0 |
| `stagnation_rule` (default) | 连续 `stagnation_window` 节点 composite 平稳 | 每 run 0–`rate_limit_per_run` 次 LLM 调用 |
| `every_node` | 每个 BFTS step（LLM 也决定时机） | 每 node 1 次 LLM 调用 |

每次触发的 decision（含 `continue`）追加到 `{checkpoint}/lineage_decisions.jsonl`，
事后可完整复盘「何时停滞、何时切换、何时终止」。`root_idea_selection`
也写入同一文件（不同 `trigger`）。

## Root Idea Selection (v0.7.0+)

VirSci 写完 `idea.json` 后，LLM 根据 venue rubric 与 ancestor research
thread 决定 `ideas[0]` 保持还是换为 `ideas[N]`。Default 保留 VirSci
的分数顺序（`ideas[0]`）；LLM 输出超出范围时同样回退到 `ideas[0]`。
启动时 1 次 LLM 调用，无 per-node 成本。

```yaml
root_idea_selection:
  enabled: true                   # v0.7.0+ default
```

决定记录到 `lineage_decisions.jsonl`（`trigger: "root_idea_selection"`），
并在 `idea.json` 中以 `_root_choice` 持久化。子（recursion）检测到
`_inherited_from` / `_root_choice` 即跳过重选。

## Claim Gate Policy (v0.7.0+)

`claim_gate_policy` 是控制 claim–evidence hard gate（Story2Proposal
Phase B3）的顶层配置块。gate 阶段在每次论文构建时运行，通过
`{{claim_gate_policy}}` 配线；该块由
`ari-core/ari/pipeline/claim_gate/policy.py` 加载。

```yaml
claim_gate_policy:
  mode: warn                  # off | warn | strict
  comparison_scope: any       # any | same_environment
  numeric_coverage:
    target_sections:
      strict: [abstract, results, conclusion]
      warn: [introduction, discussion, limitations]
      excluded: [related_work, references, appendix, equations]
  numeric_match:
    default_tolerance: {absolute: 0.0, relative: 0.02}
  blocking:
    block_on: [numeric_mismatch, operand_unresolved, missing_evidence]
```

`mode` 控制阻断行为（环境变量 `ARI_CLAIM_GATE_MODE` 可覆盖）：

| Mode | 行为 |
|---|---|
| `off` | 从不阻断。 |
| `warn`（默认） | 报告错误/警告，但不阻断 `finalize_paper`。 |
| `strict` | 存在 `block_on` 错误时**最终** gate 阻断（跳过 `finalize_paper`），strict 节中未覆盖的结果数值也会变为阻断项。draft gate 从不阻断。 |

`comparison_scope` 是注入的研究意图（环境变量 `ARI_COMPARISON_SCOPE`
可覆盖）：

| Scope | 跨环境比较 |
|---|---|
| `any`（默认） | 透明性**警告**——适用于以跨主机比较本身为贡献的跨架构研究。 |
| `same_environment` | **阻断**错误——适用于单一架构的优化研究。 |

`numeric_coverage.target_sections` 按 gate 严重级别列出需检查数值论断的
论文章节（`strict`/`warn`）以及忽略的章节（`excluded`）。
`numeric_match.default_tolerance` 是在论断未携带单独 tolerance 时应用的
匹配容差（`absolute: 0.0`、`relative: 0.02`＝2%）。`blocking.block_on`
是在 `strict` 下阻断最终 gate 的 finding type 列表：
`numeric_mismatch`、`operand_unresolved`、`missing_evidence`。

> 另一组**客观虚假**的 finding type
> （`invariant_violation`、`correctness_failed`、`correctness_uncovered`、
> `placeholder_denominator`、`recompute_mismatch`、`claim_evidence_missing`、
> `ceiling_unmeasured`）**无论** `mode` 为何都会阻断最终论文。
> 这些默认值位于 `policy.py` 的 `blocking.always_block_on`，
> 不在 `workflow.yaml` 中设置。

## BFTS 调优

通过环境变量控制 BFTS 行为：

```bash
export ARI_MAX_NODES=12      # Explore up to 12 nodes (small run)
export ARI_PARALLEL=4        # Run 4 nodes concurrently
export ARI_EXECUTOR=slurm    # Submit each node as a SLURM job
```

或在 `workflow.yaml` 的 `bfts:` 部分设置默认值（如果您的版本支持）。

---

## BFTS 评估层 (可通过配置切换)

BFTS 评估由 4 层组成，每层可在 `default.yaml`（或自定义 YAML）中
独立选择。默认值保留原有行为，未修改的 config 等同于 no-op。

```yaml
bfts:
  frontier_score: scientific_plus_diversity   # 回退选择器对前沿节点的排名策略
  depth_penalty_lambda: 0.05                  # 供 frontier_score=depth_penalized 使用
  ucb_c: 0.5                                  # 供 frontier_score=ucb_like 使用
  select_prompt: orchestrator/bfts_select               # select_next_node 的 LLM prompt
  expand_select_prompt: orchestrator/bfts_expand_select # select_best_to_expand 的 LLM prompt

evaluator:
  composite: harmonic_mean   # 将各轴分数合成 _scientific_score 的公式
  axis_mode: dynamic         # 提交给 judge LLM 的轴集合
  custom_axes: []            # 仅在 axis_mode=custom 时使用
  axis_weights: { ... }      # 现有；每轴权重覆盖
```

### Layer A — `evaluator.composite`

选择把每轴分数压缩成节点上 `_scientific_score` 的公式
（见 `ari/evaluator/llm_evaluator.py`）。`_scientific_score`
驱动排名、lineage decision 和最终报告 best-of 选择。

| 值 | 行为 |
|---|---|
| `harmonic_mean`（默认） | 加权调和平均。单个弱轴会被强烈惩罚，复刻原有行为。 |
| `arithmetic_mean` | 加权算术平均。各轴线性互补，较宽容。 |
| `weighted_min` | 返回最低轴值的瓶颈式。权重作为「该轴是否参与」的门，不缩放分数。 |
| `geometric_mean` | 加权几何平均，介于调和与算术之间。 |

### Layer B — `bfts.frontier_score`

LLM 选择器无法选中候选时，BFTS **确定性**回退评分
（`ari/orchestrator/bfts.py` 的 `_select_fallback`）所用的策略。
LLM 选择器本身不受此设置影响。

| 值 | 计算式 |
|---|---|
| `scientific_plus_diversity`（默认） | `_scientific_score + diversity_bonus` |
| `scientific_only` | `_scientific_score`（无 diversity tiebreaker） |
| `depth_penalized` | `_scientific_score + diversity_bonus − λ·depth`（`λ = bfts.depth_penalty_lambda`） |
| `ucb_like` | `_scientific_score + diversity_bonus + c · √(log N / (visits + 1))`（`c = bfts.ucb_c`，`visits` 为该节点已展开次数，`N = total_visits + frontier_size`） |

`depth_penalty_lambda = 0.0` 会让 `depth_penalized` 退化为默认策略；
`ucb_c = 0.0` 会让 `ucb_like` 退化为默认策略。

### Layer C — `evaluator.axis_mode`

决定向 judge LLM 提交的轴集合。

| 值 | 轴来源 |
|---|---|
| `dynamic`（默认） | 通用 5 轴 floor + 有效 rubric (`ARI_RUBRIC`) 派生 + `idea.json` 中的 plan-keyword 轴。当 `idea.json` mtime 变化时自动刷新。 |
| `legacy` | 固定的 5 轴 (`measurement_validity`, `comparative_rigor`, `novelty`, `reproducibility`, `clarity_of_contribution`)。不读 rubric / plan。 |
| `custom` | 原样使用 `evaluator.custom_axes`。 |

`custom_axes` 是 `{name, description, weight}` 的列表。`description`
会发送给 judge LLM，请写明该轴的含义：

```yaml
evaluator:
  axis_mode: custom
  custom_axes:
    - name: speedup
      description: "Wall-clock speedup vs. baseline (1.0 = no change)."
      weight: 0.5
    - name: accuracy
      description: "Numerical accuracy preserved within tolerance."
      weight: 0.5
```

当 `axis_mode=custom` 时，`axis_weights` 中的既有键名不会自动转换为
自定义轴名。若要从 YAML weights 表覆盖权重，请用新轴名重新写入。

### Layer D — `bfts.select_prompt` / `bfts.expand_select_prompt`

两者均为 `FilesystemPromptLoader` 键（相对 `ari-core/ari/prompts/`，
不含 `.md` 扩展名）。默认指向项目内置模板。

用户自定义模板必须声明 BFTS formatter 使用的占位符：

- `select_prompt`：`{experiment_goal}`、`{memory_context}`、`{candidates}` — LLM 必须仅返回一个 0-based 整数索引。
- `expand_select_prompt`：`{experiment_goal}`、`{candidates}` — 返回格式相同。

若键所指向的文件不存在，`FilesystemPromptLoader` 会立即抛出异常
（fail-fast，无静默回退）。

### 快速食谱

- **宽松评分 + UCB 探索:**
  ```yaml
  evaluator: { composite: arithmetic_mean }
  bfts: { frontier_score: ucb_like, ucb_c: 1.0 }
  ```
- **瓶颈评分（仅在每个轴都好时才发布）:**
  ```yaml
  evaluator: { composite: weighted_min }
  ```
- **judge 固定为 5 轴（复刻 legacy）:**
  ```yaml
  evaluator: { axis_mode: legacy }
  ```

---

## 执行模式与 RQGM 治理（可选启用）

ARI 有两种执行模式。`simple_bfts` 是默认且行为不变 —— 一份没有
`ari:` / `rqgm:` 块的配置（即所有 RQGM 之前的配置）行为与从前完全
一致，且永远不会加载任何 `ari.rqgm` 模块。`ari_rqgm` 选择启用
Constitutional ARI-RQGM 纪元治理。语义见
[执行模式](../guides/execution_modes.md)，它持久化的记录见
[RQGM Schema 参考](rqgm_schemas.md)。

下方所有 `rqgm.*` / `proposal_router.*` 默认值都位于
`ari-core/ari/configs/defaults.yaml`，并镜像
`ari-core/ari/config/__init__.py` 中的类型化 Pydantic 模型（两处的
一致性由 `ari-core/tests/test_rqgm_*.py` 套件钉住）。除非该模式
激活，每个块在结构上都是惰性的；未知的后续版本键可无警告解析
（`extra: allow`）。

### 激活：`ari.mode` + `rqgm.enabled`

```yaml
ari:
  mode: simple_bfts     # simple_bfts | ari_rqgm  (master switch)
rqgm:
  enabled: false        # redundant safety interlock
```

两个键必须一致；任何不一致都带着警告安全回退到 `simple_bfts`
（`ari.rqgm.mode.resolve_effective_mode`）。环境变量覆盖（在
profile 之后应用，因此显式的环境变量选择优先于 YAML）：
`ARI_MODE` ∈ {`simple_bfts`, `ari_rqgm`} 和 `ARI_RQGM_ENABLED` ∈
{`0`,`1`,`true`,`false`}；无效值警告并被忽略。没有 `--mode` CLI 标志，
且 profile（`--profile`）不合并 RQGM 键。仪表盘的配置工作室可以为**新建**
运行设置这个配对（以及 `paper.mode` 配对）—— 一个控件写入两个键 —— 但没有
任何界面能更改一个已经存在的运行的模式，其余 `rqgm.*` 参数也仍然仅限配置
文件（ADR-09；见[执行模式](../guides/execution_modes.md)）。

四个可选环境固定值可使执行指纹更具体。任一缺失时，纪元记录
`unresolved` 且 `execution_identity.complete` 为 `false`；ARI 不把会变化的
提供者别名宣称为可复现。

| 环境变量 | 固定的身份 |
|---|---|
| `ARI_MODEL_REVISION` | 提供者/模型权重/部署的精确修订 |
| `ARI_TOOL_BUNDLE_REVISION` | 不可变工具包修订 |
| `ARI_ENVIRONMENT_DIGEST` | 容器或解析环境摘要 |
| `ARI_DATA_SNAPSHOT_DIGEST` | 不可变外部数据快照 |

### `rqgm.epoch` —— 纪元边界尺寸

| 键 | 默认值 | 含义 |
|---|---|---|
| `boundary` | `node_count` | 边界触发器类型；v1 仅支持 `node_count`。 |
| `nodes_per_epoch` | `10` | 每产生多少个新 BFTS 节点后触发边界事务；`<= 0` 禁用自动边界（运行停留在 `epoch_000`）。 |

### `rqgm.kernel` —— ConstitutionalKernel 姿态

仅数值容差和姿态 —— 规则表是冻结的代码
（`ari/rqgm/kernel_rules.py` + `ari/rqgm/transition_rules.py`），
绝不是配置。

| 键 | 默认值 | 含义 |
|---|---|---|
| `enforcement` | `standard` | `standard` 应用阻断矩阵；`audit_only` 把所有上下文降级为仅警告并记录（分阶段上线 / 消融）。仅在运行开始 / 纪元边界读取。 |
| `audit_chain` | `auto` | 链校验姿态；v1：仅 `auto`（当且仅当链字段存在时校验哈希链）。 |
| `float_tolerance` | `1.0e-9` | 内核检查使用的唯一浮点比较容差。 |

### `rqgm.governance` —— GovernanceOrchestrator 预算与姿态

| 键 | 默认值 | 含义 |
|---|---|---|
| `enabled` | `true` | `ari_rqgm` 内的纪元边界治理审计开/关（消融档位以治理关闭的方式运行 `ari_rqgm`）。 |
| `default_level` | `1` | 盖印到报告中的默认每纪元治理级别。 |
| `full_governance_only_on_top_k` | `3` | 仅对 top-k 节点投入完整的对抗者/辩护者/裁判注意力。 |
| `judge_on_disputed_only` | `true` | **仅**作用于逐节点的对抗回合：当预算闸门拒绝 Defender 调用时，未被反驳的攻击不会到达逐节点的 `ArtifactJudge`，而是作为一条已记录的观测失效（`ari/rqgm/adversarial/round.py`）。它**不**约束纪元边界的 `GovernanceJudge` —— `audit_epoch` 的裁定步骤从不读取此键。 |
| `impeachment_only_at_epoch_boundary` | `true` | 仅为声明 —— **没有任何代码路径读取此键**。动议只在 `audit_epoch` 内提出，是因为那是门面唯一的动议入口；这是结构性质而非开关。把它设为 `false` 也不会启用纪元中途的动议。 |
| `max_llm_calls_per_audit` | `12` | 每次 `audit_epoch` 的硬上限；超过后每一步都降级到其确定性回退。 |
| `max_defender_calls_per_epoch` | `12` | Defender 每纪元 LLM 调用上限（对抗者上限只存在于 `rqgm.adversarial.max_adversary_calls_per_epoch`）。 |
| `max_judge_calls_per_epoch` | `8` | Judge 每纪元 LLM 调用上限。 |
| `low_confidence_threshold` | `0.4` | 评审置信度低于此值时把该节点标记为有争议。 |
| `novelty_claim_threshold` | `0.8` | 新颖性轴达到/超过此值（或存在非空的 novelty risks）时触发争议层。 |
| `max_motions_per_epoch` | `2` | 每纪元弹劾动议的硬上限。 |
| `bond_units_per_motion` | `1` | 动议配额单位的旧字段名。成立时返还配额、驳回时消耗；不转移价值。 |
| `jury_panel_enabled` | `false` | JuryPanel（多次采样的裁判聚合）；v1 中关闭。 |
| `fail_mode` | `open` | v1：仅 `open` —— 降级为无操作报告，绝不阻塞运行循环。 |

### `rqgm.replay` —— 重放/锚定案例尺寸

| 键 | 默认值 | 含义 |
|---|---|---|
| `max_cases_per_epoch` | `8` | 每次审计中，每个主体评分的重放/锚定案例上限。 |
| `max_cases_for_retirement` | `12` | 当动议把 RetirementEvent 纳入考虑时的更高上限。 |
| `use_cached_results` | `true` | 优先使用缓存的案例结果（`rqgm_governance_cache.jsonl`）；给定缓存结果时各评议板是确定性的。 |

### `rqgm.transition` —— RegistryTransitionEngine 阈值

这些阈值是转换层**唯一**可调的部分；T1–T21 表的拓扑是固定代码
（`ari/rqgm/transition_rules.py`）。

| 键 | 默认值 | 含义 |
|---|---|---|
| `replay_pass_threshold` | `0.8` | T3：已验证候选进入 shadow 所需的最低重放板分数。 |
| `replay_min_cases` | `4` | T3：支撑该分数的最少重放案例数。对于结构上不存在已执行重放案例并显式声明这一点的角色（`transition_engine.NO_REPLAY_BASIS_ROLES` —— `utility_policy`、`paper_writer`、`paper_reviewer`）予以豁免，豁免会记录在该次转换的 notes 中。行为类探索角色始终受此下限约束。 |
| `shadow_pass_threshold` | `0.7` | T6：试用采纳所需的最低 shadow 一致度；样本充足而低于它即 T5 拒绝。 |
| `shadow_min_samples` | `5` | T6：可判定采纳/拒绝前所需的最少实时 shadow 比较数。同样对已声明的 `NO_REPLAY_BASIS_ROLES` 予以豁免：被动的 `utility_policy` 文档从不被 shadow 执行，paper 类角色也没有 shadow 服务路径，因此其 shadow 阶段在结构上是空的，而非样本不足（plan 14 §5.5）。已报告的 `shadow_score` 仍须达到 `shadow_pass_threshold`——豁免的只是计数。 |
| `shadow_max_epochs` | `2` | T4：样本不足时在 shadow 中停留的纪元数，超过后进入有界重试。 |
| `shadow_retry_limit` | `1` | T4：有界的 shadow 重试次数；超过后候选进入 T5 拒绝。 |
| `probation_min_epochs` | `1` | T7/T14：晋升为 active 前须服满的完整干净纪元数。 |
| `warning_escalation_count` | `2` | T10：升级为 probation 前的连续警告纪元数。 |
| `warning_memory_epochs` | `3` | T13：进入 warning 后的复发窗口，复发则升级为 probation。 |
| `retirement_replay_min_cases` | `8` | T17：退役提交前 ReplayBoard 案例覆盖的最低数量（`<= rqgm.replay.max_cases_for_retirement`）。 |
| `candidate_max_age_epochs` | `3` | T2：候选等待验证的纪元数上限，超过即过期。 |
| `max_adoptions_per_role_per_boundary` | `1` | T6：每个纪元边界每角色的采纳上限。 |

### `rqgm.adversarial` —— 攻击→辩护→裁决循环

| 键 | 默认值 | 含义 |
|---|---|---|
| `enabled` | `true` | 是否对每个已完成节点运行对抗回合。 |
| `types` | 全部八种 | 启用的对抗者类型（封闭集合）：七种探索类型 `overclaim`、`metric_gaming`、`prior_art`、`reproducibility`、`evidence_gap`、`cost_explosion`、`prompt_injection`，再加 `paper_self_preference`。第八种仅在 paper-archive 阶段激活。 |
| `max_attacks_per_node` | `3` | 每回合原始攻击的硬上限。 |
| `max_adversary_calls_per_epoch` | `24` | 对抗者 LLM 调用的每纪元硬上限（该上限的唯一 schema 归属）。 |
| `sample_mod` | `5` | 确定性的 1/N 节点采样（`hash(node_id+epoch_id) mod N == 0`；P2 安全）。`<= 0` 禁用采样。 |
| `jump_threshold` | `0.25` | 相对父节点的分数跃升超过此值时触发一轮。 |
| `full_governance_only_on_top_k` | `3` | 位于前沿 top-K 之内即触发一轮。 |
| `penalty.cap` | `0.5` | 每节点已验证攻击惩罚合计的硬上限（惩罚永不抬高分数）。 |
| `penalty.severity_weights` | `low: 0.05`、`medium: 0.15`、`high: 0.3`、`critical: 0.5` | 裁判指定的严重度 → 权重，再乘以固定的裁定因子（valid = 1.0，partially_valid = 0.5）。 |
| `pool.max_cases` | `64` | 有界的 AdversarialReplayPool 大小（逐出为仅逻辑）。 |
| `pool.min_severity` | `medium` | 池准入对裁判指定严重度的下限。 |
| `pool.min_per_type` | `2` | 每类型的逐出下限，使对抗者类型覆盖在容量上限下仍幸存。 |

### `rqgm.shadow` —— shadow 实时评估采样

Shadow 输出是仅观察的：它绝不触达 BFTS 分数、前沿或记忆。

| 键 | 默认值 | 含义 |
|---|---|---|
| `enabled` | `true` | Shadow 实时评估开/关（关闭 == 零 shadow 预算）。 |
| `sample_rate` | `0.2` | 每个候选被 shadow 采样的实时调用比例（确定性哈希采样）。 |
| `max_shadow_calls_per_epoch` | `10` | 每纪元 shadow 并排调用的硬上限。 |

### `rqgm.prompt_evolution` —— 候选上限

| 键 | 默认值 | 含义 |
|---|---|---|
| `enabled` | `true` | `ari_rqgm` 内的提示词进化开/关（支持治理开启但提示词冻结的消融）。 |
| `max_candidates_per_role_per_epoch` | `1` | 每纪元每角色新提示词候选的上限。 |
| `max_total_candidates_per_epoch` | `4` | 每纪元跨所有角色的新提示词候选上限。 |
| `max_clean_room_generations_per_epoch` | `1` | 每纪元洁净室再生成的上限（由洁净室流水线消耗）。 |
| `mutation_kinds` | 全部五种 | 启用的 PromptMutator 家族：`freeform_mutation`、`threshold_tuning`、`schema_tightening`、`specialization`、`distillation`。 |

### `rqgm.utility_evolution` —— 对评分函数自身的受治理改写

在纪元边界上，效用函数本身也是一个被治理的对象：它只能沿
`PolicyMutator` → `CandidateValidationPipeline` → `RegistryTransitionEngine`
→ `ConstitutionalKernel` 的路径被改写，绝不就地修改。

**只有数值与词表旋钮。** 合法性规则 —— 封闭的取值空间与轴权重上下界 ——
是 `ari.rqgm.kernel_rules.UTILITY_POLICY_RULES` 中被冻结的代码，位于
`constitution_hash` *内部*；一个可调的权重上界就等于一部可调的宪法。有两类
看起来该放在这里、但被刻意排除的预算，因为它们各自已有唯一的 schema 归属：
候选上限走 `rqgm.prompt_evolution.max_candidates_*`，采纳上限走
`rqgm.transition.max_adoptions_per_role_per_boundary`。

| 键 | 默认值 | 含义 |
|---|---|---|
| `enabled` | `true` | `ari_rqgm` 内受治理的效用进化开关。`false` 精确复现引入改写之前的评分行为 —— 不铸造任何候选，不发生任何取代，`utility_policy_hash` 在整次运行中恒定（消融档位）。它**不会**注销 founding 时注册的 `utility_policy_v1` / `policy_mutator_v1` 组件。 |
| `mutation_kinds` | `axis_reweighting`、`composite_swap`、`frontier_score_swap`、`exploration_tuning` | 启用的 `PolicyMutator` 家族。四个默认项都是对边界证据的纯算术 —— 无 LLM、无时钟、无随机 —— 因此默认的改写流是确定性的。`freeform_policy_proposal` 会调用 LLM，属于可选启用；启用它会失去候选流的逐字节可复现性（但一个不可复现的*提案*仍然不可能变成未经校验的 policy —— 内核在两种情况下都会校验）。 |
| `min_epochs_between_rewrites` | `1` | 两次被采纳的改写之间的最小纪元数。用于约束修复成本：一次改写会作废在旧策略下评过分的全部节点，在早期边界上这可能就是整棵树。 |

### `rqgm.clean_room` —— 洁净室再生成姿态

筛查*策略*是代码（`ari/rqgm/clean_room_rules.py`）；这里只有数值
旋钮。每纪元生成预算走
`rqgm.prompt_evolution.max_clean_room_generations_per_epoch`。

| 键 | 默认值 | 含义 |
|---|---|---|
| `generation_backend` | `one_shot` | v1 唯一的后端：单次 LLM 补全，无工具/文件系统（带工具的循环可能读到已退役提示词文本）。 |
| `contamination_screen.shingle_k` | `8` | 确定性污染筛查的词 shingle 长度。 |
| `contamination_screen.fail_on_any_hit` | `true` | 与禁止语料库有任何幸存 k-shingle 重叠即阻断候选准入。 |
| `generator_prompt_key` | `rqgm/clean_room_generator` | CleanRoomPromptGenerator 的已提交元提示词键。 |

### `rqgm.frontier_repair` —— 选择性擦除 / 前沿重建

仅当已提交的 EpochTransition 带有退役时才运行。

| 键 | 默认值 | 含义 |
|---|---|---|
| `enabled` | `true` | 带退役的边界是否运行修复。 |
| `max_trace_depth` | `8` | 依赖闭包追踪器的 BFS 上限；超过后消费者被保守地一并纳入（invalidate）。 |
| `recompute_utilities` | `true` | 对过期的已评分证据，在原始纪元冻结权重下由幸存输入重算效用；`false` 则改为使该节点无效。效用策略退役会另行在新策略下重评分已存 `_axis_scores`，因此此开关不会禁用策略重写。 |
| `abandon_stale_pending` | `true` | 放弃提案记录在其运行之前就已过期的 pending 子节点。 |

### `rqgm.meta_evolution` —— 元层预算与开关

权限矩阵本身是冻结代码（`ari/rqgm/meta_rules.py`），绝不是配置。

| 键 | 默认值 | 含义 |
|---|---|---|
| `enabled` | `true` | 元进化步骤开/关（禁用时协调器以一条审计行 no-op）。 |
| `evolving_roles` | `prompt_mutator`、`clean_room_generator`、`replay_selector`、`failure_summary_compressor`、`policy_mutator` | v1 的可进化元角色；可缩减为 `[]`，无需代码改动即可冻结该层。 |
| `max_meta_candidates_per_epoch` | `1` | 每纪元元候选的上限（跨所有元角色合计）。 |
| `sandbox.max_cases` | `6` | 每次沙箱评估重放的历史元任务 bundle 数。 |
| `sandbox.use_cached_results` | `true` | 复用按内容为键的沙箱结果。 |
| `shadow.min_epochs_before_probation` | `2` | 元候选进入 `probationary_active` 前至少在 shadow 中度过的纪元数（比制度层下限更严格）。 |
| `metric_spec_weight_cap` | `true` | 宪法上限：节点发起的 MetricSpec 轴权重被抑制，改用纪元冻结的权重体制（在 `simple_bfts` 下被忽略）。 |

### `rqgm.budgets` —— 每纪元治理花费上限

对照被动的 `cost_tracker` 记录读取；`0` 表示不限（仅归因 ——
惰性的默认值）。耗尽时降级的是治理，绝不是节点执行；固定层在
构造上即豁免。

| 键 | 默认值 | 含义 |
|---|---|---|
| `max_governance_cost_usd_per_epoch` | `0` | 治理阶段 LLM 花费的每纪元美元上限。 |
| `max_governance_tokens_per_epoch` | `0` | 治理阶段 LLM 花费的每纪元 token 上限。 |
| `on_exhausted` | `degrade` | `degrade` 限制该节点的生效治理级别；`skip` 丢弃单个动作。绝不崩溃。 |

**被计入预算的动作种类。** 上面三个键是本块唯一拥有的旋钮，但它们并不是
`GovernanceBudgetManager` 计数的全部。提交给它的每个治理动作都带有十种
*动作种类*（`ari/rqgm/budget.py` 中的 `ACTION_KINDS`）之一，各自拥有独立的
每纪元计数器；每种的上限都从拥有该旋钮的那个块读取 —— 不存在别名。这个词表
是封闭的：

| 动作种类 | 每纪元上限来自 | 默认值 |
|---|---|---|
| `adversary_call` | `rqgm.adversarial.max_adversary_calls_per_epoch` | `24` |
| `defender_call` | `rqgm.governance.max_defender_calls_per_epoch` | `12` |
| `judge_call` | `rqgm.governance.max_judge_calls_per_epoch` | `8` |
| `shadow_call` | `rqgm.shadow.max_shadow_calls_per_epoch`；`rqgm.shadow.enabled` 为 false 时为 `0` | `10` |
| `replay_case` | `rqgm.replay.max_cases_per_epoch`；当 RetirementEvent 正在被考虑时改用 `rqgm.replay.max_cases_for_retirement` | `8` / `12` |
| `virsci_call` | `proposal_router.generators.virsci.max_calls_per_epoch`；该生成器被禁用时为 `0`，取值 `<= 0` 表示不限 | `2` |
| `prompt_candidate` | `rqgm.prompt_evolution.max_candidates_per_role_per_epoch`（按角色计数），并以 `max_total_candidates_per_epoch` 作为跨全部角色的第二道天花板 | `1` / `4` |
| `clean_room_generation` | `rqgm.prompt_evolution.max_clean_room_generations_per_epoch` | `1` |
| `governance_llm_call` | `rqgm.governance.max_llm_calls_per_audit` | `12` |
| `paper_anchor_scoring` | `rqgm.paper.anchor.sample_size`；`rqgm.paper.anchor.enabled` 为 false 时为 `0` | `8` |

第 0 级的固定检查从不提交动作，在构造上即豁免。计数器以
`(epoch_id, kind)` 为键（按角色计数的 `prompt_candidate` 则为
`(epoch_id, kind:role)`），并在构造时从 `budget_consumed` 审计行重建，因此
上限能跨 `ari resume` 存活。没有上限即表示不限；检查内部的任何失败都会
记录警告并**失败即放行**，而不是阻断运行。`paper_anchor_scoring` 是
paper-archive 阶段在原有九种之上新增的唯一一种；其上限背后的成本模型见下面
的 `rqgm.paper.anchor` 小节。

### `rqgm.eval` —— 评估工具链姿态

默认全部关闭：脚本化的评估替身会被拒绝，注入也绝不被应用，除非
`scripts/rqgm_eval` 工具链在它自己启动的运行上启用它们。见
[RQGM 评估](../guides/rqgm_evaluation.md)。

| 键 | 默认值 | 含义 |
|---|---|---|
| `enabled` | `false` | 评估工具链的主联锁。默认永不启用。 |
| `scripted_components` | `{}` | `role -> double_name` 替换（仅限工具链）。 |
| `injection_specs` | `[]` | 激活的 `eval_*` 注入 id；被记录进 `rqgm_injection_provenance.json`。 |
| `paper_ablation.condition_id` | `""` | 与 RQGM 原论文对齐的评估专用条件（`P0_hgm_h_fixed_critic` 至 `P4_constitutional_rqgm`）。空值或 `eval.enabled: false` 保持正常行为；它不是 `paper.mode`。 |

### `rqgm.paper` —— paper-archive 协同进化

整个 `rqgm.paper.*` 块**在生效 paper 模式不是 `rqgm_archive` 时完全惰性**
（`paper.mode: rqgm_archive` 与 `rqgm.paper.enabled: true` 必须一致）。它与
`ari.mode` 正交，并且绝不会遮蔽上面探索侧的 `rqgm.*` 旋钮 —— 即便名字相近，
两层也各有独立的 schema 归属。语义在概念侧：
[RQGM 架构](../concepts/rqgm_architecture.md) 的 *paper-archive 层*。

| 键 | 默认值 | 含义 |
|---|---|---|
| `enabled` | `false` | 冗余的安全互锁，镜像 `rqgm.enabled`。 |
| `archive.width` | `4` | 深度 1 上的种子草稿数 —— 根节点的分支因子。 |
| `archive.refine_rounds` | `2` | 每份草稿的 refine 子节点数 —— 草稿的分支因子。 |
| `archive.max_expansions` | `12` | 每纪元的节点预算。archive 实际用作 BFTS `max_total_nodes` 的*生效*上限是 `min(width × (1 + refine_rounds), max_expansions)`；在默认值下两项恰好相等（4 × 3 = 12）。正是这个界限在结构上限制了那些没有自己预算动作种类的 paper 参与者。 |
| `archive.depth` | `3` | 草稿树深度，用作 archive 的 BFTS `max_depth`。更深的树只是把同一份节点预算重新分配，绝不会让它变多。 |
| `archive.compile_threshold` | `0.0` | 惰性编译胜出草稿所需的 best-belief 分数下限。 |
| `epoch.rounds` | `2` | 每个 paper 阶段的 archive 轮数；一轮即一个 paper 纪元。这个廉价的默认值刻意买不到一次完成的 reviewer 采纳：那条路径是 candidate → validated → shadow → probationary_active，而且需要先出现角色空缺，因此大约需要五个边界。在 `2` 下，默认运行会跑通循环、adversary 与弹劾，但你不会看到生效的 reviewer 哈希发生变化。若某次运行必须见证一次采纳，请调高它。 |
| `self_preference.enabled` | `true` | self-preference adversary；仅在 `rqgm_archive` paper 模式下有意义。 |
| `self_preference.corpus_path` | `""` | `""` 表示复用锚语料库及其作者身份标签。 |
| `self_preference.sample_size` | `8` | 每纪元评分的留出论文数（镜像锚的采样数）。 |
| `self_preference.accept_threshold` | `0.6` | reviewer 的「accepted」判定阈值。 |
| `self_preference.margin` | `0.1` | 触发前置信号的 AI 对人类平均分差。 |
| `prompt_evolution.enabled` | `true` | archive 内的 reviewer / writer 协同进化。`false` 会退化为不带协同进化的 best-of-N 已评审草稿。 |

### `rqgm.paper.anchor` —— 留出集上的 accept/reject 一致度

`paper_reviewer` 的基准真值锚：一份按 `train` / `held_out` 划分的只读
accept/reject 语料库，其形状记录在
[RQGM Schema 参考](rqgm_schemas.md) 的
*`paper_anchor_corpus.jsonl` —— 只读 accept/reject 锚* 一节。默认关闭，这就是
那条降级的入门坡道：不读取任何语料库，`anchor_evaluation` 阶段走它的零覆盖
通过路径，reviewer 候选不受锚门控。`paper_writer` 同样有锚，但它锚在第 0 层
的论断–证据门上，不需要任何精选语料库 —— 不过 writer 的忠实性案例仍然落在
这个池子里，所以 `enabled: false` 同时也门控了对 writer 的制裁。

| 键 | 默认值 | 含义 |
|---|---|---|
| `enabled` | `false` | 锚语料库评分开关。它同时是 `paper_anchor_scoring` 的预算开关：禁用即上限为 `0` —— 与 `shadow_call`、`virsci_call` 相同的「禁用即归零」规则。 |
| `corpus_path` | `""` | accept/reject 语料库路径（相对 checkpoint 或绝对路径）。 |
| `sample_size` | `8` | 留出一致度的采样数，**同时**也是 `paper_anchor_scoring` 的每纪元上限。reviewer 候选是通过在 `sample_size` 篇留出论文上被评分来获得其锚一致度效用的，因此治理成本是 O(候选数 × `sample_size`)；这正是上限取采样数本身、而不是另行调优某个数字的原因。请把它读作成本模型，而不是调优出来的常量。 |
| `max_bootstrap_label_fraction` | `0.5` | 对 `label_source=gate_bootstrap` 案例占比的机器强制上限，在整个语料库*以及*留出子集上分别检查。一旦越界，语料库会被拒绝 —— 加载不返回任何东西，运行落回入门坡道 —— 而绝不会把异常抛进运行。`0.0` 表示只接受人工标注；`1.0` 表示接受完全自标注的锚（会被指纹化）。 |

有一处不一致需要知道：`enabled` 的类型化默认值是 `false`
（`RQGMPaperAnchorConfig`），而预算管理器在**根本找不到** anchor 块对象时
自身的回退值是 `true`。该回退只对完全不带 `anchor` 块的配置生效；由随附默认
值构建出来的配置总是呈现 `enabled: false`。

### `rqgm.paper.reviewer.agent_as_judge` —— agent-as-judge 草稿评分

**仅**在实际 paper 模式为 `rqgm_archive`（`paper.mode: rqgm_archive` 与
`rqgm.paper.enabled: true` 必须一致）时被读取；它与 `ari.mode` 正交。默认
关闭，因此归档的草稿评分器保持为确定性的、不调用 LLM 的 venue 评分细则，
草稿评分路径上没有实时 LLM 调用（P2）。开启后，共享的 paper 派发
（`ari/cli/paper_dispatch.py`，由 `ari paper` / `ari run` / `ari resume` 使用）
注入一个由 `LLMClient` 支撑的评审评分器（`ari/rqgm/paper_judge.py`），它在
**相同**的 venue 细则轴上给每份草稿评分，但权重来自**激活**的受治理
`paper_reviewer` 提示词的侧重 —— 这是唯一能读取确定性读取器无法读取的轴
（`novelty`、`significance`）的路径。失败即回退：LLM 错误、无法解析的回复，
或覆盖不足细则总轴权重 50% 的回复，都会退化为确定性细则分数，而绝不是伪造的
常数（非有限的轴取值会被丢弃，不会传播进选择）。由于 judge 分数与回退分数对
任何消费者而言都是同一个 float，同一派发会把该次运行的 judged / degraded
计数记入 `ari.log`。

| 键 | 默认值 | 含义 |
|---|---|---|
| `enabled` | `false` | agent-as-judge 草稿评分的开关。可被 `ARI_PAPER_AGENT_AS_JUDGE` ∈ {`0`,`1`,`true`,`false`} 覆盖；非法值会告警并被忽略。 |
| `max_tokens` | `1024` | judge 回复长度上限（成本控制），经 `LLMClient.complete(max_tokens=...)` 传入。 |

### `proposal_router` —— 提案生成路由

**仅**在生效模式为 `ari_rqgm` 时被消费 —— 例外是 `record_only`，
它在 `simple_bfts` 下也生效（仅记录双写，消融 B1）。
`generators.virsci.enabled` 被刻意设计为在 `simple_bfts` 下不读取：
现有的 VirSci 控制杆
（`bfts_pipeline.generate_idea.enabled` / `ARI_IDEA_VIRSCI_REAL`）
在那里保持权威，且模式解析从不读取 `proposal_router.*`
（VirSci 与 `ari.mode` 正交）。

| 键 | 默认值 | 含义 |
|---|---|---|
| `record_only` | `false` | 在 `simple_bfts` 下，把 agent 循环的 `idea.json` 输出额外导入 `proposals/proposal_records.jsonl`，作为 `legacy_idea_json` 记录。零行为变化；回滚 = 删除该标志。 |
| `summary_budget_chars` | `6000` | 渲染出的 ProposalSummaryView 扩展上下文的总字符预算。 |

`proposal_router.generators.*` 下的每个生成器条目共享两个键：
`enabled`（路由器是否可以路由到它）和 `max_calls_per_epoch`
（`0` = 不限）：

| 生成器 | `enabled` | `max_calls_per_epoch` | 备注 |
|---|---|---|---|
| `cheap` | `true` | `0`（不限） | 单次 LLM 提案生成器；确定性的路由回退。 |
| `mutation` | `true` | `2` | 变异一个现有 ProposalRecord 的单个侧面。 |
| `attack_driven` | `false` | `0` | 消费 ValidatedAttackRecord；默认禁用且不在路由表中。 |
| `prior_art` | `true` | `1` | 依据调研/相关文献对提案做差异化；无先前工作来源时降级为跳过。 |
| `virsci` | `false` | `2` | 可选启用的高成本审议式 VirSciAdapter；默认永不启用。额外键：`mode: event_triggered`（v1 唯一模式）和 `trigger_on: [initial_exploration, frontier_stagnation, major_pivot, paper_candidate]`。 |

---

## EAR 精选 (`ear/publish.yaml`) — v0.7.0+

精选机制让作者通过 allowlist 控制 `{checkpoint}/ear/` 中哪些子集进入
可发布的 bundle (`{checkpoint}/ear_published/` + `manifest.lock`)。
ari-core 内置的 **deny list** 始终强于 `include`,
防止意外公开机密文件。

### Schema (`ari-core/ari/schemas/publish.schema.json`)

```yaml
# 示例：<checkpoint>/ear/publish.yaml
include:                     # 相对 ear/ 的 glob (allowlist)
  - "README.md"
  - "LICENSE"
  - "reproduce.sh"
  - "code/**"                # contributing 链的 verbatim 源文件
  - "data/**"                # 仅上传输入数据；不打包实验输出
  - "figures/**"             # 顶层 figures
  - "environment.json"
# 注：EVOLUTION.md 和 _provenance.json 是位于 ear/ 外（checkpoint 根目录）
# 的 ARI 审计日志，不会被收入发布 bundle。
exclude: []                  # 用户指定排除 (在 include 之后应用)
max_file_mb: 100             # 超过此大小的 allowlist 文件会显式失败
visibility: staged           # staged|public|unlisted|private-token|embargoed-until:YYYY-MM-DD
required: false
auto_promote: false
license: MIT                 # SPDX；ear/LICENSE 据此从模板生成
backend: ari-registry
```

v0.6.0 旧路径（`code/<node_id>/**`、`data/raw_metrics.json`、`logs/**`、`reproducibility/**`）在 v0.7.0 中不再产生；请从旧的 `publish.yaml` 中移除。

### 内置 deny 模式

以下模式 **始终** 排除,即便 `include` 命中:

```
.env, .env.*, **/.env, **/.env.*
**/secrets/**, secrets/**
**/*.pem, **/*.key
**/id_rsa, **/id_ed25519
```

`manifest.lock` 仅记录被排除的数量,不记录路径。

### 行为

- `publish.yaml` **不存在** 时,`ear_curate` 阶段静默跳过,
  论文 Code Availability 段落省略 (与 v0.6.0 检查点完全向后兼容)。
- **bundle digest** (`manifest.lock` 中的 `bundle_sha256`) 是
  按路径排序的文件记录 (path + size + sha256) 的规范 JSON 的 sha256,
  跨机器可复现, 是写入论文的永久真实值。
- 精选是 **原子的**: `max_file_mb` 超限等硬失败时,
  之前正常的 `ear_published/` 不会被破坏。

### CLI

```bash
ari ear curate <checkpoint>            # 友好输出
ari ear curate <checkpoint> --json     # 机器可读
ari ear status <checkpoint>            # 显示 manifest 摘要

ari ear publish <checkpoint> --backend ari-registry --visibility staged
ari ear promote <checkpoint> --target public
```

### Pipeline 集成

`workflow.yaml` 在 paper 管线中,`ear_curate` 阶段插入到 `generate_ear`
与 `generate_figures` 之间, 调用 transform skill 的 `curate_ear`
MCP 工具; `publish.yaml` 不存在时为 no-op。
