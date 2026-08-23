---
sources:
  - path: ari-core/tests
    role: test
  - path: ari-core/tests/fixtures/gui_refresh
    role: test
  - path: pytest.ini
    role: config
  - path: scripts/docs
    role: test
  - path: scripts/check_dashboard_ux.py
    role: test
  - path: scripts/check_bundle_budget.py
    role: test
  - path: scripts/quality/check_bundle_budget.yaml
    role: config
  - path: ari-core/ari/viz/frontend/src/i18n
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__
    role: test
  - path: ari-core/ari/viz/frontend/vitest.config.ts
    role: config
  - path: ari-core/ari/viz/frontend/package.json
    role: config
  - path: .github/workflows
    role: config
last_verified: 2026-08-17
---

# 如何测试 ARI 代码

本指南涵盖 `ari-core` 和 `ari-skill-*` 包的测试规范：测试文件的
存放位置、预期的 fixture，以及如何维护确定性保证。

## 仓库布局

```
ari-core/tests/                    — core regression tests
ari-skill-<name>/tests/            — skill-local tests
ari-skill-<name>/tests/conftest.py — skill-level fixtures（17 个 skill 中的 13 个；
                                     harness 与 knowledge 根本没有 tests/，
                                     idea 与 paper-re 有 tests/ 但没有 conftest；
                                     benchmark 与 plot 在包根目录另有第二个）
pytest.ini                         — repo-wide config
```

仓库根目录下的 `pytest.ini` 规定了裸 `pytest` 所遍历的 `testpaths`：
`ari-core/tests` 与 `workspace/harnesses`（后者在没有 workspace 的检出中
并不存在，pytest 会容忍这一点）。`ari-skill-*` 套件被有意排除在
`testpaths` 之外——每个 skill 都自带 `src/server.py`，在同一进程中导入
两个 skill 会产生歧义。请按包单独运行，或用
`bash scripts/run_all_tests.sh` 运行完整套件（每条路径一个 pytest 进程）。

## 运行测试套件

```bash
pytest -q                                        # 仅默认的 testpaths
bash scripts/run_all_tests.sh                    # 完整套件，每条路径一个进程
pytest ari-skill-memory/tests -q                 # 单个 skill
pytest ari-core/tests/test_react_driver.py -q    # 单个文件
pytest ari-core/tests/test_react_driver.py::TestRunReact  # 单个类
pytest ari-core/tests/test_gui_v1_api.py::test_projects_happy_path  # 单个用例
pytest -k 'memory and not letta' -q              # 按关键字
```

## ari-core 规范

### 始终隔离写操作

ARI 过去将文件写入 `$HOME/.ari/`，v0.5.0 已移除该路径，并由两道防护维持。
`ari-core/tests/test_no_user_home_writes.py` 只有一个测试
`test_module_imports_do_not_write_user_home`：它在伪造的 `HOME` 下导入一份固定的
八个核心模块清单（`ari.config`、`ari.paths`、`ari.cost_tracker`、`ari.lineage`、
`ari.memory.client`、`ari.memory.local_client`、
`ari.publish.backends.ari_registry`、`ari.clone.resolvers.ari`），断言它们在导入
时都不会创建 `$HOME/.ari/`。覆盖整个套件的那道防护是 `refactor-guards`
workflow：它把 `HOME` 重定向后运行全部 `ari-core/tests`，若结束时 `$HOME/.ari/`
存在就让该 job 失败——"没有任何测试会在那里创建文件"是靠它强制的，而不是靠假设。
编写涉及文件系统的新测试时：

- 使用 `monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))`。
- 对所有辅助目录使用 `tmp_path`。
- 不要在生产代码中直接调用 `Path.home()`；若必须在测试中使用，
  请说明原因并将其加入审计列表。

### 智能体循环的冒烟测试

`ari-core/tests/test_react_driver.py` 以桩替换 `LLMClient` 与 `MCPClient` 来覆盖
`ari.agent.react_driver`，因此不接触真实 LLM 或 MCP 服务器。它是一个单元测试
文件，而非跨节点的集成运行：三个辅助类固定纯函数（`TestValidatePaths` —— 针对
`_validate_paths_in_args` 的 11 个用例，覆盖沙箱逃逸与路径穿越规则；
`TestBuildWindow` —— 对话窗口截断；`TestFinalToolDef`），`TestRunReact` 则以四种
方式驱动 `run_react` —— 调用 final tool 后完成、沙箱违规阻断 dispatch、final tool
始终未触发时的 max-steps 退出，以及日志文件持久化。

新增智能体级特性时请沿用同样的形态：把客户端桩化，断言循环可观测的状态转换，
并让该文件不含网络与子进程调用。

### 确定性保证（P2）

本仓库中没有任何东西端到端地断言整轮运行的"相同种子，相同树"不变量。真正被固定
的范围更窄，值得按名字记住：
`ari-core/tests/test_gui_baseline_run_fixtures.py::test_same_seed_is_byte_identical`
用同一组 `(nodes, seed)` 生成两份 checkpoint 并逐字节比较（其反面用例是
`test_different_seed_changes_content`）；memory 套件则固定确定性树所依赖的隔离
性质 —— `ari-skill-memory/tests/test_checkpoint_isolation.py`（两个 checkpoint
互不可见）与 `ari-skill-memory/tests/test_ancestor_scope.py`（三条兄弟分支之间
不互相污染）。

当确定性回归悄然出现时：

1. 首先编写一个能固定预期树形结构的回归测试。
2. 二分查找变更集；问题几乎总出在引入了 `dict` 顺序依赖或
   依赖 `id(...)` 的哈希上。
3. 将测试加入对应领域的测试套件（memory、BFTS 等）。

### 合成 checkpoint fixture

GUI 与 `/api/v1` 的读取端测试并不附带 checkpoint —— 它们自己生成。
`ari-core/tests/fixtures/gui_refresh/` 下有两个纯 Python 工厂：

- `run_fixture_factory.py` —— `make_run_checkpoint(dest, nodes=N, seed=S)`
  写出一份运行 checkpoint：`tree.json`、`nodes_tree.json`、`results.json` 走真实的
  `ari.checkpoint.save_tree_json` / `save_nodes_tree_json` / `save_results_json`，
  因此它们的格式与生产写入端逐字节一致；`experiment.md`、`idea.json`、
  `meta.json`、`cost_trace.jsonl` 则直接写出，因为没有对应的 `save_*_json`
  辅助函数。可选的 `paper` / `review` / `ors` / `ear` 结果层默认全部关闭。
- `rqgm_fixture_factory.py` —— `make_rqgm_checkpoint(dest, nodes=10,
  epochs=2, ...)` 先调用基础工厂，再在其上叠加一层确定性的 RQGM 治理面
  （哈希链式的 transition 与 audit 日志、registry 汇总、prompt 主体、节点
  metrics 哨兵值）；哈希与状态辅助函数是从真实的 `ari.rqgm` 导入的，而不是
  重新实现。

使用时有三条性质值得注意。

**不提交任何东西。** 两个工厂都生成到调用方给定的目录里（所有消费方都是
`tmp_path`），因此仓库中不会留下会过期的 fixture 数据。

**确定性（P2）。** 每个值要么是固定字面量，要么由种子经 `hashlib` 推导；
`random` 从未被导入，时间戳是对字面量 `2026-07-23T00:00:00Z` 的定点算术，
而不是 `datetime.now()`。相同的 `(nodes, seed)` 产生逐字节相同的文件，
`ari-core/tests/test_gui_baseline_run_fixtures.py` 直接断言了这一点。

**损坏模式就是健壮性输入。** `corrupt=` 先写出一份完全合法的 checkpoint，
然后只破坏一处，因此一个测试每次只隔离一种失败形态：`"truncated_jsonl"`
把 `cost_trace.jsonl` 的最后一行从中间截断，`"invalid_json"` 削掉
`tree.json` 的尾部，`"partial_write"` 删除 `tree.json` 而让
`nodes_tree.json` 保持合法。RQGM 工厂有自己的三种 —— `"broken_chain"`、
`"truncated_transitions"`、`"registry_mismatch"`。两者都会以 `ValueError`
拒绝无法识别的模式。

尺寸档位是命名约定，而不是契约。工厂的 docstring 与
`ari-core/tests/fixtures/gui_refresh/README.md` 把 `nodes=10` / `1000` /
`10000` 称作 small / medium / large，并称 small 档是"every reader must load
it（每个读取端都必须加载）"的那一档 —— 但没有任何机制强制这一点。`nodes`
只是一个普通整数参数，仅带一条 `nodes >= 1` 校验；真正跑遍三个档位的只有
`test_gui_baseline_run_fixtures.py`（而且它的确定性用例用的是 `nodes=50`）；
读取端套件只传断言所需的数量，在其余 `test_gui_*` 各文件中是 `nodes=2` 到
`nodes=10`。请把档位名当作阅读那些测试时的简称，而不是必须遵守的规则。另外，
在 `test_gui_baseline_run_fixtures.py` 中 large 档只被生成、从不被重新加载，
因为本仓库没有定义可供挂载 skip 的 `slow` 标记。

消费方并不导入这个包，而是用
`importlib.util.spec_from_file_location` 按文件路径加载工厂，因此每个消费文件
的开头都重复着一个小小的加载辅助函数。

## Skill 级规范

### MCP 服务器测试

17 个 `ari-skill-*` 包中有 10 个带 `tests/test_server.py`（benchmark、coding、
evaluator、hpc、idea、paper、tool-registry、transform、vlm、web）；其余要么把
这类文件叫作别的名字，要么没有 —— `ari-skill-orchestrator/tests/test_mcp_surface.py`
就是换了名字的同类文件。这十个里有九个的做法是：在进程内导入服务器模块，
以 fixture 输入直接调用工具函数，并断言响应结构。多数通过
`from src.server import …` 拿到它；已打包的 skill 改为导入已安装的模块
（`ari_skill_hpc.server`），而 `ari-skill-coding` 还会用
`importlib.util.spec_from_file_location` 按路径加载。唯一的例外是
`ari-skill-tool-registry`，而且是有意为之：它的对外面是一个 broker，所以它的
`tests/test_server.py` 会把 `src/server.py` 作为真正的 stdio 子进程启动
（`PythonStdioLauncherV1` + `StdioMCPAdapter`，落到
`ari-skill-tool-registry/src/providers.py`:514 的 `stdio_client`），并通过 MCP
会话驱动它。在这十个之外，那个换了名字的同类文件也一样：
`ari-skill-orchestrator/tests/test_mcp_surface.py` 会把 `src/server.py` 作为子进程
启动两次 —— 一次经 `streamable-http`（`subprocess.Popen`，:188），一次经 stdio
（`stdio_client`，:282）。只有这两个套件才会有子进程。

有两件事这一层原则上交给 workflow 的关卡管。工具列表与 `skill.yaml`
是否一致、生成的 `mcp.json` 是否漂移，属于下文"PR 时的测试内容"里 `contracts`
工作流的 `scripts/check_skill_manifests.py`；不过恰好有一个套件自己也固定了它们，
所以不要把某个 skill 套件变绿读作已覆盖这两项 ——
`ari-skill-orchestrator/tests/test_mcp_surface.py`:38-43 断言运行时的工具名、
`skill.yaml` 的 `tools:`、`mcp.json` 的 `tools`，以及一份含 12 项的字面量
`EXPECTED` 集合完全相同。此外并不存在
共用的 MCP 测试框架：没有 `mcp.testing` 这个模块（`mcp` 包提供的是 `cli`、
`client`、`os`、`server`、`shared`、`types`），仓库里也没有任何代码导入它。每个
套件都自建 fixture —— `ari-skill-memory/tests/conftest.py` 是这一模式易读的参考
（限定在 `tmp_path` 的 `ARI_CHECKPOINT_DIR`、backend fixture、签名调用上下文的
签发器，以及一个假的 Letta 客户端）。

确实调用 `list_tools()` 的套件有好几个，各自比对的对象并不相同：`ari-skill-coding`
校验带 `outputSchema` 的那五个工具的 schema（`tests/test_server.py`:715-723）；
`ari-skill-hpc`（`tests/test_server.py`:40-46）与 `ari-skill-idea`
（`TestMcpToolRegistration`）断言特定工具名已注册（hpc 还断言某些未注册）；
`ari-skill-tool-registry` 断言运行中的 broker 面恰好是它的六个公开操作
（`tests/test_server.py`:48-50）；`ari-skill-transform` 则读取已注册的名字
（`tests/test_metric_contract_seam.py`:22）。这些期望值都是写在测试里的字面量 ——
只有 `ari-skill-orchestrator` 会拿它跟清单比对。

### LLM mock

调用 LLM 的 skill（`evaluator`、`paper`、`paper-re`、`idea`、
`replicate`、`transform`、`plot` —— 调用点在带 `litellm.acompletion` 的
`src/planning.py` —— 以及 `vlm`）在单元测试中必须 mock LLM。

参考示例是 `ari-skill-paper-re/tests/test_litellm_completer.py`，其手法是模块注入
而非 HTTP 拦截：`_install_fake_litellm` 构造一个带桩 `acompletion` 的
`types.ModuleType("litellm")`，再用 `monkeypatch.setitem(sys.modules, "litellm", fake)`
替换，因此完全不触网，并且可以断言 completer 转发的确切 kwargs。`respx` 用在真实
HTTP 客户端本身就是被测对象的场合
（`ari-skill-memory/tests/test_letta_http_regression.py`）；`pytest-mock` 也为同样
的目的装在 CI 里。

### 依赖状态的 fixture

当 skill 需要 `ARI_CHECKPOINT_DIR` 风格的环境时，在 fixture 中设置：

```python
@pytest.fixture
def ckpt(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    return tmp_path
```

不要在模块导入时设置 `ARI_CHECKPOINT_DIR` —— 其值必须限定在
测试作用域内。

## PR 时的测试内容

多个 GitHub Actions 工作流为每个面向 `main` 的 PR 设关。

**测试** — Python 套件分散在两个工作流中，彼此不会跑对方的路径。

- `refactor-guards` 只运行一次 `pytest ari-core/tests/ -q`，把 `HOME` 重定向到
  临时目录，并用 `--ignore` 排除四个文件（`test_letta_restart_live.py`、
  `test_letta_start_scripts.py`、`test_ollama_gpu.py`、`test_dashboard_html.py`
  —— 最后一个是因为它需要一份没有任何 job 会产出的 Vite 构建）。
  `test_no_user_home_writes.py` 与 `test_public_api_boundary.py`（Phase 4，确保
  skill 仅从 `ari.public.*` 导入）是随这一次调用一起跑的，并不是独立步骤。之后
  若 `$HOME/.ari/` 存在则该 job 失败；另一个 job 会在 PR 的 diff 中查找允许列表
  之外新增的 `~/.ari` 引用。另有五个 job（import boundaries、directory policy、
  complexity、ruff lint、dead code）全部是**建议性**的 —— 每一个都带
  `continue-on-error: true`，且除 ruff lint（裸的 `ruff check ari-core`）之外都还
  传 `--warning-only`，因此发现问题也不会让 PR 变红。它是同时在 `refactoring`
  分支上触发的两个工作流之一（文件内的注释至今仍写着"唯一"，而 `skill-tests`
  是后来以相同触发条件加入的）。
- `skill-tests` 以每条路径一个 pytest 进程的方式运行七个 skill 套件（`paper`、
  `evaluator`、`web`、`plot`、`memory`、`transform`、`replicate`），并带
  `-p no:randomly`。`ari-skill-coding` **不在其中**，`ari-skill-paper-re` 因为要
  通过 `git+chz` vendor PaperBench 而被有意排除。按进程拆分的理由，和 `pytest.ini`
  把这些 skill 排除在 `testpaths` 之外的理由相同。

**仪表盘前端** — `dashboard-frontend` 工作流是针对 `ari-core/ari/viz/frontend`
的硬关卡（没有任何 `continue-on-error`）：`npm ci`、`npm run typecheck`
（`tsc --noEmit`）、然后 `npm test`（`vitest run`）。它有意不运行 `npm run build`
和 Playwright 截图。由于 `npm test` 跑的是整个套件，它也一并带上了
`src/__tests__/v1TypesDrift.test.ts` —— 该测试在内存中从 `ari/viz/v1/openapi.json`
重新生成 `src/services/api/v1types.gen.ts` 并断言逐字节相等 —— 所以改了 OpenAPI
文档却没有重跑 `npm run gen:v1types`，会在这里失败。

**文档与结构** — 三个工作流保持文档集同步：

- `readme-sync` — 每个目录的 `## Contents` 索引都列出其下的文件
  (`scripts/readme_sync.py --check`)。
- `docs-sync` — 全树不变量。硬关卡共六道：声明的 `sources:` 路径存在
  (`check_doc_sources.py`)、`docs/i18n/landing.{en,ja,zh}.js` 的键集一致
  (`check_i18n_js.py`)、HTML 站点的 i18n 完整性与对外版本 pin
  (`check_site_i18n.py`)、手写 `docs/*.html` 中的每个 `href`/`src` 都能解析
  (`check_doc_links.py --html-only`)、根 `README.{md,ja,zh}` 的标题结构一致
  (`check_readme_parity.py`)、`report/{en,ja,zh}` 在结构上并行
  (`report/scripts/check_i18n.py`，Gate 6)。其后是三个 advisory（非阻塞）步骤：
  翻译新鲜度 (`check_translation_freshness.py`)、Markdown 链接完整性
  (`check_doc_links.py` —— 它检查链接的两半，因此会分别报告断裂文件数与断裂
  *锚点*数)，以及主干状态的陈旧检查
  (`check_docs_source_sync.py --warning-only`)。最后这一项覆盖了其余关卡看不见的
  唯一维度：某个源在 `main` 上的最新提交比声明它的 doc 的 `last_verified` 更新。
  它的冻结基线为空（`scripts/check_docs_source_sync.allow.yaml`:34，
  `known-offenders: []`），因此它报告的每一条都是新增的。另一个 job 会检查
  report PDF 是否同步 (`sync_report_pdf.sh --check`) 并构建 VitePress 站点。
- `docs-change-coupling` — 基于差分：`report/{en,ja,zh}` 的语言配对文件
  （章节、`strings.tex`、`main.tex`）在一种语言中被编辑时，必须在同一 PR 中
  镜像到其他两种语言 (`check_report_cochange.py`，硬关卡)；并且当 doc 的
  `sources:` 中列出的源发生变更时，应当更新该 doc 的 `last_verified`
  (`check_ref_coupling.py`，advisory)。

任何 doc 关卡都可从仓库根目录本地运行，例如
`python scripts/docs/check_i18n_js.py`。

**仪表盘翻译** — 仪表盘 UI 自带三语词典
`ari-core/ari/viz/frontend/src/i18n/{en,ja,zh}.ts`，而 docs 侧的关卡够不到它们：
`check_i18n_js.py` 只读取 `docs/i18n/landing.{en,ja,zh}.js`（其 `SURFACES` 元组
只有一项），且键模式 `^\s*'([^']+)'\s*:` 仅匹配单引号键，因此无法解析以裸标识符
作为键的词典。规则与 docs 侧相同 —— 三种
语言必须声明**完全相同的键集**，且同一文件内不得重复键 —— 所以新增的 UI
字符串必须在同一次变更中加入全部三个词典。某个语言有而另一个语言缺失的键
会回退为英文字符串；若 `en` 中也不存在，则直接显示键名本身
（`src/i18n/index.ts` 中的 `t()`）。值被有意排除在比较之外：专有名词在三种
语言中读法相同是合理的。

有两项检查负责保障这一点，其中只有一项在 CI 中运行：

- `python scripts/check_dashboard_ux.py --fail-on-regression` —— 对三个 `.ts`
  文件做键集一致性与重复键检测，与该脚本的其他仪表盘 UX 检查打包在一起。
  **没有任何工作流会调用它**，所以修改仪表盘字符串时请自行运行。
  只要存在未冻结在 `scripts/quality/check_dashboard_ux.allow.yaml` 中的
  finding，它就以 exit 1 退出；该允许列表中没有任何 i18n 条目，因此一致性
  一旦被破坏，首次运行即失败。不加该标志时，脚本只打印报告并以 exit 0 退出。
- 在 `ari-core/ari/viz/frontend` 下运行
  `npx vitest run src/i18n/__tests__/parity.test.tsx` —— 针对实际导入的词典
  断言同一不变量，其 `KNOWN_DRIFT` 允许列表目前为空。这一项**是**被设关的：
  `dashboard-frontend` 工作流的 `npm test` 步骤会跑整个 Vitest 套件，包含这个
  文件。它的重复键断言弱于 Python 一侧，因为 TypeScript 对象字面量在测试读取
  之前就已折叠了重复键。

在当前代码树上两者均为绿：三个词典持有完全相同的键集，且没有重复键。

**仪表盘无障碍** — 仪表盘**未声明任何 WCAG 合规级别**。本文档集与前端测试套件
中都不存在合规目标，此处的任何内容都不应被读作合规声明。真正存在的是
`ari-core/ari/viz/frontend/src/__tests__/shellA11yBaseline.test.tsx` 中的一组
冻结基线。它作为 `dashboard-frontend` 工作流 `npm test` 步骤的一部分在 CI 中
运行，同时也是人工执行的 cutover 前检查清单中的一行
(`docs/guides/gui_cutover_runbook.md` §2)。若只想
运行这个文件，在 `ari-core/ari/viz/frontend` 下执行：

```bash
npx vitest run src/__tests__/shellA11yBaseline.test.tsx
```

该文件固定了三样东西：

- **已经成立的正向不变量。** 恰好一个 `navigation` 地标；每个侧边栏条目
  （`gui_v2` 开启时为 15 个）都是带 `tabindex="0"` 的原生 button；四个导航分组
  通过 `aria-labelledby` 命名；移动端汉堡按钮带有
  `aria-label`/`aria-controls`/`aria-expanded`；活动项目 `combobox` 具有可访问
  名称。
- **针对在 `#/home` 渲染的外壳的 axe-core violation id 基线**，当前为空列表。
  断言是完全相等，因此出现新的 violation 会失败，*并且* 在问题修复后仍把 id
  留在基线里也会失败。由于 jsdom 不做绘制，`color-contrast` 规则在那里被
  **禁用** —— 本仓库中没有任何自动检查会计算颜色对比度。
- **覆盖测试中 `ROUTE_MARKERS` 内 18 条路由的 `<h1>` 计数基线。** 其中四条是
  明知不合规而被固定下来的：`#/paperbench`、`#/workflow` 和 `#/settings` 用
  `<h2>` 作页面标题且没有 `<h1>`，`#/idea` 则完全没有标题元素。其余 14 条各渲染
  恰好一个 `<h1>`。同样是完全相等断言，所以修好一条路由就要在同一次变更中收缩
  这个冻结字面量。

没有任何检查覆盖的部分：不存在端到端断言来验证主要 journey 可以完全不用鼠标
完成，也没有屏幕阅读器检查。键盘*可达性*只对侧边栏做了断言（见上，可聚焦的原生
button）；真正用键盘*驱动*界面则只对 `#/tree2` 的表格做了断言
（`src/components/TreeV2/__tests__/TreeV2LargeTree.test.tsx` 在
roving tabindex 上走 <kbd>↓</kbd>/<kbd>→</kbd>/<kbd>Enter</kbd>；按键对照表见
`docs/guides/dashboard.md`）。减弱动效是全局遵守的 —— `src/styles/motion.css`
在 `prefers-reduced-motion: reduce` 下把动效 token 归零 —— 但这是样式表的性质，
不是测试的性质。

WCAG 2.2 AA 关卡——无论自动还是人工——是仪表盘改版的目标，而不是本测试套件已经
确立的性质。不要把一次绿色运行读作 AA 合规的证据。

**SPA 打包体积** —— `scripts/check_bundle_budget.py` 把仪表盘构建产物约束在一组
gzip 预算内，而它同样**未接入任何工作流**。这里的原因是结构性的：没有任何工作流
会构建前端，且 `ari-core/ari/viz/static/dist/` 是生成物而非提交物，所以该检查器
要测量的目录在 runner 上根本不存在。它*确实*登记在
`scripts/quality/generate_quality_report.yaml` 中，但读取该文件的聚合器在
`contracts.yml` 里以 `--target` 模式运行 —— 它只合并其他作业上传的 JSON 制品，
不执行任何检查器 —— 因此打包预算在那里显示为 `unavailable`。请在构建之后自行
运行；它是人工执行的 cutover 前检查清单中的一行
（`docs/guides/gui_cutover_runbook.md` §2）：

```bash
cd ari-core/ari/viz/frontend && npm run build   # the checker never builds
python scripts/check_bundle_budget.py --fail-on-regression
```

它在进程内对每个 `ari-core/ari/viz/static/dist/assets/*.js` 做 gzip（level 6、
`mtime=0`，因此对同一份构建重跑会给出完全相同的数字），并把每个 chunk 与其
类别预算（单位为 KiB 的 gzip 体积）比较：

| 类别 | 匹配对象 | 预算 |
|---|---|---|
| `entry` | `dist/index.html` 引用的 `<script type="module">` chunk | 100 |
| `route` | 懒加载路由 chunk，按 `<Name>Page-<hash>.js` 匹配 | 150，其中 `SettingsPage` 与 `WizardPage` 收紧到 50 |
| `shared` | 其余所有 `.js` chunk —— vendor 拆分、语言词典、共享组件 | 150 |
| `total` | 所有 `.js` chunk 的 gzip 体积之和 | 600 |

`shared` 的上限是刻意保守的超集：当初被单独定预算的只有路由 chunk，把同一个
数字扩展到其余部分，是为了让一个拆分失当的 vendor bundle 无法躲在路由类别之外。
`total` 是棘轮式的天花板而非目标值 —— 它存在的意义是抓住逐 chunk 预算看不见的
唯一一种失败模式：某个依赖被重复打进多个 chunk，或者涌现出一大批各自都不超预算
的新 chunk。

浏览器指标（LCP、INP、CLS）被刻意**排除**在关卡之外：jsdom 不做绘制，而共享
runner 对 pass/fail 预算而言噪声太大。因此一次绿色的打包检查对体感性能什么都
没说；那一半是在固定机器上的人工 profile，记录在发布证据中。

退出码约定与 `scripts/quality` 家族的其余成员一致。裸执行只打印报告并以 exit 0
退出。`--fail-on-regression` 在存在任何未冻结于
`scripts/quality/check_bundle_budget.allow.yaml` 的 finding 时以 exit 1 退出，
而该文件并不存在 —— 从来没有哪条预算需要被冻结，而允许列表文件缺失即等于空
允许列表，因此超预算的 chunk 在首次运行即失败。缺少 `dist/assets` 时以 exit 2
退出，因为构建缺失属于环境问题，而不是预算回归。

预算本身位于 `scripts/quality/check_bundle_budget.yaml` —— dist 路径、路由
chunk 的正则、四个类别预算以及按路由的覆盖值。所有键都可省略，且检查器在代码里
携带着同样的默认值，因此这份 YAML 的全部价值就在于让预算变更成为一行可评审的
diff，而不是一次代码编辑。请在那里调整，而不是改脚本。

**测试覆盖率 —— 一处已知缺口 (known gap)。** 本仓库没有任何东西会测量测试套件
实际执行了代码库中多少内容，两侧皆然。
`ari-core/ari/viz/frontend/vitest.config.ts` 中没有声明 `coverage` 块；
`package.json` 把 `test` 定义为裸的 `vitest run`，既没有覆盖率脚本，
devDependencies 中也没有任何覆盖率 provider —— `@vitest/coverage-v8` 只是作为
vitest 自身的可选 peer dependency 出现在 `package-lock.json` 里，因此
`vitest run --coverage` 得先把它装上才能跑。Python 一侧同样未被测量：
`pytest.ini` 没有设置 `--cov`，也没有任何 ARI 包依赖 `pytest-cov`。两侧都从未
记录过覆盖率基线。

在仪表盘改版期间曾设定过两个目标数字，但从未实现。这里把它们记录为
**已知缺口 (known gap)** 而非策略，而且一次绿色的运行对二者都不构成证据：
前端纯逻辑层的 line/branch 覆盖率 90%，以及整体覆盖率在首次测量时取基线、
随后向 80% 棘轮式提升，任何下降都视为回归。

在这两个数字能有意义之前，有两件事必须先解决。其一，90% 目标所点名的那些层
—— reducer、serializer、API wrapper 与 config resolver adapter —— 只有一部分能
对应到这份代码上。`src/services/api/` 确实存在，就是 API wrapper 层。但前端里
根本没有 reducer（不论大小写，`reducer` 在 `src/` 下任何地方都不出现），也没有
serializer 模块（`src/` 下 `serializ` 仅有的两处匹配是注释，位于
`services/api/client.ts` 与 `hooks/useRunEvents.ts`），而 config resolver 是
Python 的 —— `ari-core/ari/config/resolver.py`，经由 HTTP 访问，而不是通过某个
前端 adapter。其二，棘轮需要一份存好的基线，以及用来跟它比对的东西。
`dashboard-frontend` 工作流现在给了前端测试套件一个运行的地方，但它跑的是
`npm test` 而不是 `npm test -- --coverage`，而且两侧都没有提交任何基线文件
—— 地方有了，测量仍然没有。

## 编写回归测试

规范：

1. 将 bug 捕获为一个以 `assert <observed> ==
   <expected>` 失败的测试。
2. 先单独提交该测试（红色 commit）。
3. 在其上提交修复。

这样在 `git log` 中将"我们期望什么"与"我们如何修复"分离，
并能在后续重写修复方案时保持不变。

## 参见

- `pytest.ini` —— 仓库范围的配置。
- `docs/concepts/architecture.md` —— 运行时架构（有助于选择正确的测试层）。
- `docs/reference/public_api.md` —— 边界测试依此检查导入。
