---
sources:
  - path: ari-core/tests
    role: test
  - path: pytest.ini
    role: config
last_verified: 2026-05-25
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

仓库根目录下的 `pytest.ini` 使 `pytest` 在任意位置运行时都能遍历
所有测试目录。

## 运行测试套件

```bash
pytest -q                                        # everything
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

`refactor-guards` GitHub Actions 工作流运行：

- `pytest ari-core/tests -q`
- `pytest ari-skill-coding/tests -q`
- `pytest ari-skill-memory/tests -q`
- ... 各 skill 的测试套件

它还运行 `tests/test_no_user_home_writes.py` 和
`tests/test_public_api_boundary.py`（Phase 4，确保 skill 仅从
`ari.public.*` 导入）。

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
