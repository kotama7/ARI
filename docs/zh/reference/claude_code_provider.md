---
sources:
  - path: ari-core/ari/llm/claude_code
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/llm/client.py
    role: implementation
last_verified: 2026-08-17
---

# Claude Code LLM 提供方（`backend: claude_code`）

`claude_code` 后端把本地安装的 **Claude Code** 置于 ARI 现有 provider
抽象之后，作为无状态 LLM API 驱动：ARI 代码调用与 Ollama/OpenAI/Anthropic
相同的 `LLMClient.complete()`，provider 另外提供带 schema 校验的
`structured_complete()`。这里**不**把 Claude Code 当作代理执行器 ——
无工具、无 MCP、无记忆、无 CLAUDE.md、无 hooks/plugins/skills、无会话复用。
ARI 的 BFTS 控制、`claim_evidence_hard_gate`、指标重算、EAR 生成与可复现性
检查全部留在 ARI 侧。

实现：`ari-core/ari/llm/claude_code/`（policy、serializer、command builder、
CLI/SDK runner、provenance、provider）。已在 Claude Code 2.1.198 上验证。

## 模式

### `strict_reproducibility`（默认）

用于实验、论文与基线。每个请求：

1. 把 ARI 侧完整消息历史序列化为一个确定性 prompt（`serializer.py`；会话
   状态的权威副本始终在 ARI —— 绝不以 Claude Code 的 transcript 为准），
2. 以 hermetic 配置启动**全新** `claude -p` 子进程：

   ```
   claude -p --output-format json --max-turns 1 --model <model>
          [--system-prompt-file system.txt] [--bare] --safe-mode
          --strict-mcp-config --disable-slash-commands --no-chrome
          --no-session-persistence --setting-sources "" --tools ""
          --disallowedTools "*" --permission-mode plan
   ```

   `--setting-sources ""` 总是显式给出：省略该 flag 时 CLI 默认加载
   user/project/local settings，且 `--safe-mode` 并不能阻止 settings 的
   `env`/认证覆盖生效（已在 2.1.198 上 A/B 验证）。

   prompt 走 stdin，每次调用使用一次性 `cwd/`，环境变量使用**白名单**
   （仅认证/代理/locale；父会话的 `CLAUDE_CODE_*` 一律丢弃），并强制
   `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`、
   `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1`、
   `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`，
3. 解析单个 JSON result envelope，若有 response schema 则在 ARI 侧校验，
   记录 provenance 与成本，返回 `LLMResponse`。

`--bare` 把认证限制为 `ANTHROPIC_API_KEY`/apiKeyHelper（绝不读取 OAuth
凭据）。因此默认 `bare: null` 为自动解析：仅当存在 `ANTHROPIC_API_KEY` 或
`ANTHROPIC_AUTH_TOKEN` 时使用 `--bare`；否则仅去掉该 flag（其余隔离 flag
保留），并把该决定记入 provenance（`bare_auto_resolved`）。无密钥却显式
`bare: true` 会照常执行并以 "Not logged in" 立即失败（绝不静默降低隔离）。
`home_mode: sandbox` 为每次调用提供一次性 `$HOME`，创建在该次调用的
provenance 目录下的 `home/`（要求密钥认证，因为 OAuth 凭据位于真实
`$HOME` 下）。

### `low_overhead`

用于追求实现效率与速度。Python provider 对象（及 Agent SDK worker）可以
常驻，但**每个请求都是全新的 `claude_agent_sdk.query()`**：`max_turns=1`、
工具为空、MCP 服务器为空、setting sources 为空，强制记忆抑制环境变量，并
通过 SDK 的 `extra_args` 传递 `--no-session-persistence`（没有
`extra_args` 的 SDK 会立即报错 —— 否则每次调用都会在
`~/.claude/projects/` 下留下 transcript）。解析出的 sandbox HOME 通过
`options.env["HOME"]` 应用。绝不传递 `resume` / `continue_conversation` /
session-id 复用 —— runner 根本没有能接收它们的 API。SDK 事件流保存到
`trace.jsonl`。若未安装 `claude-agent-sdk` 则给出明确错误；只有显式设置
`sdk_fallback_to_cli: true` 才允许回退到 strict CLI runner（并记入
provenance）。

已知差异：SDK 的子进程传输继承父进程环境（options.env 只做增量），因此
该模式下无法强制 strict 的环境白名单 —— 在 provenance 中记为
`hermetic_env: false`。SDK 被指向与 strict 模式相同的 CLI 可执行文件
（`cli_path` = 解析后的 `claude_bin`；不在 PATH 上时回退到 SDK 捆绑的
CLI）；provenance 记录 `sdk_version` 及完整 options 快照。已在
claude-agent-sdk 0.2.110 上实机验证（安装：
`pip install 'ari-core[claude-code]'` 或 `pip install claude-agent-sdk`）。

## 配置

```yaml
llm:
  backend: claude_code
  model: claude-sonnet-5
  claude_code:
    mode: strict_reproducibility  # strict_reproducibility | low_overhead
    max_turns: 1
    timeout_sec: 300
    output_format: json
    hermetic: true
    tools: []
    disallowed_tools: ["*"]
    disable_auto_memory: true
    disable_prompt_history: true
    bare: null                    # 按 ANTHROPIC_API_KEY 是否存在自动解析
    safe_mode: true
    strict_mcp_config: true
    disable_slash_commands: true
    no_chrome: true
    no_session_persistence: true
    permission_mode: plan
    setting_sources: []
    record_provenance: true
    structured_output_transport: prompt   # prompt | native
    schema_repair_retries: 1
    home_mode: auto               # auto | real | sandbox
    claude_bin: claude
    sdk_fallback_to_cli: false
```

环境变量覆盖：`ARI_BACKEND=claude_code`、`ARI_CLAUDE_CODE_MODE`、
`ARI_CLAUDE_CODE_MODEL`、`ARI_CLAUDE_CODE_MAX_TURNS`、
`ARI_CLAUDE_CODE_TIMEOUT_SEC`、`ARI_CLAUDE_CODE_RECORD_PROVENANCE`、
`ARI_CLAUDE_CODE_BIN`
（参见 [environment_variables.md](./environment_variables.md)）。

GUI：New Experiment 向导与 Settings 页面的 Provider 中提供 **Claude
Code** 选项；启动器会导出 `ARI_BACKEND=claude_code`（未选模型时默认
`claude-sonnet-5`）。API 密钥栏为可选 —— 已有的 Claude Code OAuth 登录
即可工作，提供密钥则启用 `--bare` 配置。

## 策略强制（fail-loud）

`ClaudeCodePolicy`（`policy.py`）冻结 hermetic 契约；`validate_policy()`
会**一次性列出全部违规**并拒绝：`tools` 非空、deny 列表缺少 `"*"`、启用
MCP、会话 resume、关闭记忆/历史抑制、关闭 `safe_mode`/
`no_session_persistence`、或在没有显式 `allow_multi_turn` 时设置
`max_turns > 1`。此外，每个构建出的命令都会断言不含会话复用类 CLI flag
（`--resume`、`--continue`、`--session-id`、`--fork-session`）。

若已安装的 Claude Code 拒绝某个 flag（版本漂移），调用以
`ClaudeCodeUnsupportedFlagError` 失败。只有列入 `compat_drop_flags` 的
flag 才会被显式去除，并作为 `unsupported_flags` 记入 provenance ——
隔离绝不静默削弱。

## 结构化输出

`response_schema` 总是保存为 `schema.json`，最终输出**总是在 ARI 侧校验**
（jsonschema，Draft 2020-12）。两种传输方式：

- `prompt`（默认）：把 canonical schema JSON 嵌入 prompt 的
  `<response_contract>` 块；保持最严格的 flag 配置
  （`--permission-mode plan`、`--max-turns 1`、`--disallowedTools "*"`）。
- `native`：通过 `--json-schema` 传递。2.1.198 验证结果：Claude Code 以
  `StructuredOutput` **工具**调用实现该功能，plan 模式会拒绝该调用且往返
  多消耗一个 turn —— 因此该传输以 `--allowedTools StructuredOutput
  --permission-mode default --max-turns 2` 运行（`--tools ""` 仍禁用其余
  全部工具），校验后的对象从 envelope 的 `structured_output` 读取。

校验失败时 provider 至多进行 **1 次**修复重试（同一 hermetic 策略，
prompt = 原 prompt + 无效输出 + 校验错误，记录在 `attempt_2/`），仍失败
则抛出 `ClaudeCodeSchemaError`。

## Provenance

`record_provenance: true`（默认）时，每次调用写入
`<checkpoint>/claude_code/<call_id>/`（未固定 checkpoint 时用临时目录；
路径通过 `LLMResponse.provenance_path` 返回）：

```
input/messages.json  prompt.txt  system.txt  schema.json
command.json  env_allowlist.json  claude_version.txt
stdout.json  stderr.log  result.json  validation.json
input_hashes.json  output_hashes.json  provenance.json
trace.jsonl（low_overhead）  cwd/  attempt_2/（修复重试）
```

`provenance.json` 记录 provider/mode/model、`claude --version` 或 SDK
版本、精确 argv/options、cwd、环境白名单标记（仅名称 —— 绝不写入机密
值）、包含 `resume_used: false` 的完整策略、`session_id`（仅记录、绝不
复用）、`unsupported_params`（如 CLI 没有对应物的 `temperature`/
`max_tokens`）、返回码、attempts 及校验结果。成本连同 Claude 的权威
`total_cost_usd` 经 `ari.cost_tracker` 记入 `cost_trace.jsonl`（该后端
绕过 litellm，litellm 全局回调看不到它）。

## 为何不用 interactive 会话 + `/clear`

常驻 interactive Claude Code 加 `/clear` 的方案，只能*近似*重置单个长命
进程的状态（已加载 settings、记忆指令、compaction、skill/hook 表面、工作
目录）——这些状态每次调用既不可观测也不可哈希验证。全新进程（或全新 SDK
query）让执行单元与 provenance 单元一致：每次调用恰好对应一条命令、一套
环境、一组输入哈希与一个输出。

## 为何不用 resume / 会话历史

重放或手写 Claude Code 会话 transcript 再 `--resume`，会让 Claude Code 的
磁盘会话格式 —— 一种 ARI 无法校验、随版本漂移的私有格式 —— 成为会话状态的
权威副本。ARI 改为自己持有消息历史并在每个请求完整序列化；
`--no-session-persistence` 保证磁盘上没有任何可 resume 的内容。result
envelope 中出现的 `session_id` 仅为审计记入 provenance，绝不回传。

## 推荐设置

- **paper / idea / eval 的补全调用**（BFTS 选择器、judge、摘要器）：
  使用默认值（`strict_reproducibility`、`max_turns: 1`、
  `structured_output_transport: prompt`、`record_provenance: true`）。
- **迭代 prompt / 管线**：`mode: low_overhead`
  （`pip install claude-agent-sdk`）；正式运行之外可
  `record_provenance: false`。
- **ReAct 代理阶段与 MCP 技能不经过此后端。** 代理循环的工具调用会立即
  失败（`ClaudeCodeToolsUnsupportedError`）—— 请指向支持工具调用的后端
  （如 `cli-shim`、`ollama`、`openai`）。MCP 技能的直接 litellm 调用被
  确定性地路由到普通 Anthropic API（`anthropic/<model>`，需要
  `ANTHROPIC_API_KEY`）。
- 未来若把 Claude Code 用作代理执行器，必须是**独立后端**（如
  `claude_code_agent_executor`）并拥有自己的策略面，而不是放宽本策略。

## 可复现性的边界

相同 prompt 不保证 LLM 输出比特级一致（采样、服务端变更）。此 provider
保证的是*可验证性*：每次调用的全部输入、完整策略、模型 ID、Claude
Code/SDK 版本、命令、环境白名单、输出及其 SHA-256 哈希均被持久化，任何
结果都可审计并在记录的条件下重跑。

## 健康检查

```bash
ari doctor claude-code          # 可执行文件、版本、策略、命令、flag 报告
ari doctor claude-code --live   # + 一次带 schema 校验的真实 hermetic 调用
```
