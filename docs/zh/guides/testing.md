---
sources:
  - path: ari-core/tests
    role: test
  - path: pytest.ini
    role: config
  - path: scripts/docs
    role: test
  - path: scripts/check_dashboard_ux.py
    role: test
  - path: ari-core/ari/viz/frontend/src/i18n
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__
    role: test
  - path: .github/workflows
    role: config
last_verified: 2026-08-07
---

# 如何测试 ARI 代码

本指南涵盖 `ari-core` 和 `ari-skill-*` 包的测试规范：测试文件的
存放位置、预期的 fixture，以及如何维护确定性保证。

## 仓库布局

```
ari-core/tests/                 — core regression tests
ari-skill-<name>/tests/         — skill-local tests
ari-skill-<name>/conftest.py    — skill-level fixtures
pytest.ini                      — repo-wide config
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
pytest ari-core/tests/test_react_driver.py -q    # one file
pytest ari-core/tests/test_react_driver.py::test_runs_for_two_nodes  # one case
pytest -k 'memory and not letta' -q              # by keyword
```

## ari-core 规范

### 始终隔离写操作

ARI 过去将文件写入 `$HOME/.ari/`。v0.5.0 已移除该路径；防护测试
`ari-core/tests/test_no_user_home_writes.py` 断言此后不再有任何测试
在该路径创建文件。编写涉及文件系统的新测试时：

- 使用 `monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))`。
- 对所有辅助目录使用 `tmp_path`。
- 不要在生产代码中直接调用 `Path.home()`；若必须在测试中使用，
  请说明原因并将其加入审计列表。

### 智能体循环的冒烟测试

`ari-core/tests/test_react_driver.py` 运行三个确定性的
"智能体完成两个节点"测试：

1. **正常路径** —— 两个节点，使用真实 LLM 存根，在每次状态转换时
   断言 BFTS 状态。
2. **工具失败恢复** —— coding skill 返回错误；智能体以固定种子重试。
3. **内存写入隔离** —— 兄弟节点看到不相交的内存存储。

每次新增智能体级特性时，请镜像这个三元组。

### 确定性保证（P2）

"相同种子，相同树"的不变量由
`ari-core/tests/test_no_user_home_writes.py`（间接验证：断言运行
之间无全局状态变化）以及各 skill 测试套件
（`ari-skill-memory/tests/test_isolation.py`、
`ari-skill-memory/tests/test_cow.py`）共同验证。

当确定性回归悄然出现时：

1. 首先编写一个能固定预期树形结构的回归测试。
2. 二分查找变更集；问题几乎总出在引入了 `dict` 顺序依赖或
   依赖 `id(...)` 的哈希上。
3. 将测试加入对应领域的测试套件（memory、BFTS 等）。

## Skill 级规范

### MCP 服务器测试

每个 skill 附带一个 `test_server.py`，它：

1. 在进程内启动 MCP 服务器（无子进程）。
2. 调用 `list_tools()` 并断言工具列表与 `mcp.json` 一致。
3. 以 fixture 输入调用每个工具并断言响应结构。

使用 `mcp.testing` 辅助工具（各 skill 的测试套件略有差异 ——
参见 `ari-skill-memory/tests/conftest.py` 作为参考）。

### LLM mock

调用 LLM 的 skill（`evaluator`、`paper`、`paper-re`、`idea`、
`replicate`、`transform`、`plot/_llm`、`vlm`）在单元测试中必须
mock LLM。使用 LiteLLM `respx` 适配器或 `pytest-mock` 将
`litellm.completion` 替换为固定响应。

`ari-skill-paper-re/tests/test_litellm_completer.py` 是参考示例。

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

**测试** — `refactor-guards` 工作流运行：

- `pytest ari-core/tests -q`
- `pytest ari-skill-coding/tests -q`
- `pytest ari-skill-memory/tests -q`
- ... 各 skill 的测试套件

它还运行 `tests/test_no_user_home_writes.py` 和
`tests/test_public_api_boundary.py`（Phase 4，确保 skill 仅从
`ari.public.*` 导入）。

**文档与结构** — 三个工作流保持文档集同步：

- `readme-sync` — 每个目录的 `## Contents` 索引都列出其下的文件
  (`scripts/readme_sync.py --check`)。
- `docs-sync` — 全树不变量，全部为硬关卡：声明的 `sources:` 路径存在
  (`check_doc_sources.py`)、`docs/i18n/landing.{en,ja,zh}.js` 的键集一致
  (`check_i18n_js.py`)、根 `README.{md,ja,zh}` 的标题结构一致
  (`check_readme_parity.py`)、`report/{en,ja,zh}` 在结构上并行
  (`report/scripts/check_i18n.py`，Gate 6)。翻译新鲜度
  (`check_translation_freshness.py`) 与 docs 内链接 (`check_doc_links.py`)
  作为 advisory（非阻塞）步骤运行。
- `docs-change-coupling` — 基于差分：`report/{en,ja,zh}` 的语言配对文件
  （章节、`strings.tex`、`main.tex`）在一种语言中被编辑时，必须在同一 PR 中
  镜像到其他两种语言 (`check_report_cochange.py`，硬关卡)；并且当 doc 的
  `sources:` 中列出的源发生变更时，应当更新该 doc 的 `last_verified`
  (`check_ref_coupling.py`，advisory)。

任何 doc 关卡都可从仓库根目录本地运行，例如
`python scripts/docs/check_i18n_js.py`。

**仪表盘翻译** — 仪表盘 UI 自带三语词典
`ari-core/ari/viz/frontend/src/i18n/{en,ja,zh}.ts`，而上述工作流均未覆盖它们：
`check_i18n_js.py` 只读取 `docs/i18n/landing.{en,ja,zh}.js`，且其键模式仅匹配
单引号键，因此无法解析以裸标识符作为键的词典。规则与 docs 侧相同 —— 三种
语言必须声明**完全相同的键集**，且同一文件内不得重复键 —— 所以新增的 UI
字符串必须在同一次变更中加入全部三个词典。某个语言有而另一个语言缺失的键
会回退为英文字符串；若 `en` 中也不存在，则直接显示键名本身
（`src/i18n/index.ts` 中的 `t()`）。值被有意排除在比较之外：专有名词在三种
语言中读法相同是合理的。

有两项检查负责保障这一点，且**两者都未接入任何工作流** —— 修改仪表盘字符串
时请自行运行：

- `python scripts/check_dashboard_ux.py --fail-on-regression` —— 对三个 `.ts`
  文件做键集一致性与重复键检测，与该脚本的其他仪表盘 UX 检查打包在一起。
  只要存在未冻结在 `scripts/quality/check_dashboard_ux.allow.yaml` 中的
  finding，它就以 exit 1 退出；该允许列表中没有任何 i18n 条目，因此一致性
  一旦被破坏，首次运行即失败。不加该标志时，脚本只打印报告并以 exit 0 退出。
- 在 `ari-core/ari/viz/frontend` 下运行
  `npx vitest run src/i18n/__tests__/parity.test.tsx` —— 针对实际导入的词典
  断言同一不变量，其 `KNOWN_DRIFT` 允许列表目前为空。它的重复键断言弱于
  Python 一侧，因为 TypeScript 对象字面量在测试读取之前就已折叠了重复键。

在当前代码树上两者均为绿：三个词典持有完全相同的键集，且没有重复键。

**仪表盘无障碍** — 仪表盘**未声明任何 WCAG 合规级别**。本文档集与前端测试套件
中都不存在合规目标，此处的任何内容都不应被读作合规声明。真正存在的是
`ari-core/ari/viz/frontend/src/__tests__/shellA11yBaseline.test.tsx` 中的一组
冻结基线。与上面的 i18n 检查一样，它**未接入任何工作流** —— 根本没有工作流会
运行前端测试套件（CI 中仅有的 Node 步骤是构建 VitePress 文档站点），因此它是
人工执行的 cutover 前检查清单中的一条硬关卡 (`npm test`，
`docs/guides/gui_cutover_runbook.md` §2)。若只想
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
