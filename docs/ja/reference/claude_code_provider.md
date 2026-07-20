---
sources:
  - path: ari-core/ari/llm/claude_code
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/llm/client.py
    role: implementation
last_verified: 2026-07-03
---

# Claude Code LLM プロバイダ（`backend: claude_code`）

`claude_code` バックエンドは、ローカルにインストールされた **Claude Code** を
ARI の既存プロバイダ抽象の背後で、ステートレスな LLM API として駆動する。
ARI 側のコードは Ollama/OpenAI/Anthropic と同じ `LLMClient.complete()` を
呼ぶだけであり、プロバイダは加えて schema 検証付き JSON 用の
`structured_complete()` を公開する。ここでは Claude Code を**エージェント
エグゼキュータとしては使わない** — ツールなし、MCP なし、メモリなし、
CLAUDE.md なし、hooks/plugins/skills なし、セッション再利用なし。ARI の
BFTS 制御、`claim_evidence_hard_gate`、メトリクス再計算、EAR 生成、
再現性チェックの責務はすべて ARI 側に残る。

実装: `ari-core/ari/llm/claude_code/`（policy、serializer、command builder、
CLI/SDK runner、provenance、provider）。Claude Code 2.1.198 で検証済み。

## モード

### `strict_reproducibility`（既定）

実験・論文・baseline 用。各リクエストは:

1. ARI 側のメッセージ履歴全体を 1 つの決定的な prompt にシリアライズする
   （`serializer.py`。会話状態の正本は常に ARI — Claude Code のトランス
   クリプトを正本にしない）、
2. **毎回 fresh な** `claude -p` サブプロセスを hermetic なプロファイルで
   起動する:

   ```
   claude -p --output-format json --max-turns 1 --model <model>
          [--system-prompt-file system.txt] [--bare] --safe-mode
          --strict-mcp-config --disable-slash-commands --no-chrome
          --no-session-persistence --setting-sources "" --tools ""
          --disallowedTools "*" --permission-mode plan
   ```

   `--setting-sources ""` は常に明示する: フラグを省略すると CLI は既定で
   user/project/local の settings を読み込み、`--safe-mode` でも settings の
   `env`/認証上書きは適用されてしまう（2.1.198 で A/B 検証済み）。

   prompt は stdin 渡し、呼び出しごとの使い捨て `cwd/`、環境変数は
   **allowlist**（認証・プロキシ・ロケールのみ。親セッションの
   `CLAUDE_CODE_*` は落とす）に加えて
   `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`、
   `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1`、
   `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` を強制する、
3. 単一 JSON result envelope をパースし、response schema があれば ARI 側で
   検証し、provenance とコストを記録して `LLMResponse` を返す。

`--bare` は認証を `ANTHROPIC_API_KEY`/apiKeyHelper に限定する（OAuth
クレデンシャルは一切読まれない）。そのため既定の `bare: null` は自動解決に
なる: `ANTHROPIC_API_KEY` または `ANTHROPIC_AUTH_TOKEN` があるときだけ
`--bare` を付け、なければこのフラグだけ落とし（他の隔離フラグは維持）、
判断を provenance に記録する（`bare_auto_resolved`）。鍵なしで明示的に
`bare: true` とした場合はそのまま実行され、"Not logged in" で fail-loud
する（黙って隔離を弱めることはない）。`home_mode: sandbox` は呼び出しごとに
一時 `$HOME` を与える（OAuth クレデンシャルは実 `$HOME` 配下にあるため、
鍵認証が必須）。

### `low_overhead`

実装効率・速度用。Python のプロバイダオブジェクト（と Agent SDK ワーカー）
は常駐してよいが、**各リクエストは fresh な `claude_agent_sdk.query()`**
であり、`max_turns=1`、ツール空、MCP サーバ空、setting sources 空、
メモリ抑制環境変数の強制、さらに SDK の `extra_args` 経由の
`--no-session-persistence` 付きで実行される（`extra_args` を持たない SDK
は fail-loud — さもないとトランスクリプトが `~/.claude/projects/` 配下に
残ってしまう）。解決された sandbox HOME は `options.env["HOME"]` で適用
される。`resume` / `continue_conversation` / session-id の再利用は決して
渡されない — runner にはそれらを受け取る API 自体が存在しない。SDK の
イベントストリームは `trace.jsonl` に保存される。`claude-agent-sdk` が
未インストールの場合は明示的にエラーになる。strict CLI runner への
フォールバックは、明示的な `sdk_fallback_to_cli: true` があるときのみ
許可され、provenance に記録される。

既知の差分: SDK のサブプロセストランスポートは親プロセスの環境を継承する
（options.env は追加のみ）ため、このモードでは strict の env allowlist を
強制できない — provenance に `hermetic_env: false` として記録される。SDK
には strict モードと同じ CLI バイナリを使わせる（`cli_path` = 解決済み
`claude_bin`。PATH に無い場合は SDK バンドル CLI にフォールバック）。
provenance には `sdk_version` と options スナップショット全体が記録される。
claude-agent-sdk 0.2.110 で実機検証済み（導入は
`pip install 'ari-core[claude-code]'` または `pip install claude-agent-sdk`）。

## 設定

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
    bare: null                    # ANTHROPIC_API_KEY の有無で auto
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

環境変数オーバーライド: `ARI_BACKEND=claude_code`、`ARI_CLAUDE_CODE_MODE`、
`ARI_CLAUDE_CODE_MODEL`、`ARI_CLAUDE_CODE_MAX_TURNS`、
`ARI_CLAUDE_CODE_TIMEOUT_SEC`、`ARI_CLAUDE_CODE_RECORD_PROVENANCE`、
`ARI_CLAUDE_CODE_BIN`
（[environment_variables.md](./environment_variables.md) 参照）。

GUI: New Experiment ウィザードと Settings ページの Provider に
**Claude Code** が選択肢として並ぶ。ランチャーは `ARI_BACKEND=claude_code`
をエクスポートする（モデル未指定時の既定は `claude-sonnet-5`）。API キー
欄はオプション — 既存の Claude Code OAuth ログインでも動作し、キーが
あれば `--bare` プロファイルが有効になる。

## ポリシー強制（fail-loud）

`ClaudeCodePolicy`（`policy.py`）が hermetic 契約を凍結し、
`validate_policy()` は違反を**全件まとめて**列挙して拒否する: `tools` が
非空、deny リストに `"*"` がない、MCP 有効、セッション resume、メモリ/
履歴抑制の無効化、`safe_mode`/`no_session_persistence` の無効化、明示的な
`allow_multi_turn` なしの `max_turns > 1`。さらにセッション再利用系 CLI
フラグ（`--resume`、`--continue`、`--session-id`、`--fork-session`）は
ビルドされる全コマンドについて不在が assert される。

インストール済み Claude Code がフラグを拒否した場合（バージョンドリフト）、
呼び出しは `ClaudeCodeUnsupportedFlagError` で失敗する。`compat_drop_flags`
に列挙したフラグのみ明示的に落とされ、provenance に `unsupported_flags`
として記録される — 隔離が黙って弱まることはない。

## 構造化出力

`response_schema` は常に `schema.json` として保存され、最終出力は**常に
ARI 側で検証**される（jsonschema、Draft 2020-12）。トランスポートは 2 つ:

- `prompt`（既定）: canonical な schema JSON を prompt の
  `<response_contract>` ブロックに埋め込む。最も厳格なフラグプロファイル
  （`--permission-mode plan`、`--max-turns 1`、`--disallowedTools "*"`）を
  維持する。
- `native`: schema を `--json-schema` で渡す。2.1.198 での検証結果:
  Claude Code はこれを `StructuredOutput` **ツール**呼び出しとして実装して
  おり、plan モードはその呼び出しを deny し、ラウンドトリップに 1 ターン
  余計にかかる — そのためこのトランスポートは `--allowedTools
  StructuredOutput --permission-mode default --max-turns 2` で実行され
  （`--tools ""` により他のツールは引き続きすべて無効）、検証済み
  オブジェクトは envelope の `structured_output` から読まれる。

検証失敗時、プロバイダは最大 **1 回**の repair リトライを行い（同じ
hermetic ポリシー、prompt = 元 prompt + 不正出力 + 検証エラー、
`attempt_2/` に記録）、それでも失敗なら `ClaudeCodeSchemaError` を送出する。

## Provenance

`record_provenance: true`（既定）では、全呼び出しが
`<checkpoint>/claude_code/<call_id>/` に成果物を書く（checkpoint 未設定時は
一時ディレクトリ。パスは `LLMResponse.provenance_path` として返る）:

```
input/messages.json  prompt.txt  system.txt  schema.json
command.json  env_allowlist.json  claude_version.txt
stdout.json  stderr.log  result.json  validation.json
input_hashes.json  output_hashes.json  provenance.json
trace.jsonl（low_overhead）  cwd/  attempt_2/（repair リトライ）
```

`provenance.json` は provider/mode/model、`claude --version` または SDK
バージョン、正確な argv/options、cwd、env allowlist マーカー（名前のみ —
秘密の値は決して書かれない）、`resume_used: false` を含む全ポリシー、
`session_id`（記録のみ、再利用しない）、`unsupported_params`（CLI に対応
物がない `temperature`/`max_tokens` など）、リターンコード、attempts、
検証結果を保持する。コストは Claude の正値 `total_cost_usd` とともに
`ari.cost_tracker` 経由で `cost_trace.jsonl` に記帳される（このバックエンド
は litellm を経由しないため、litellm のグローバルコールバックには乗らない）。

## interactive セッション + `/clear` を使わない理由

常駐 interactive Claude Code に `/clear` を挟む方式は、単一の長命プロセスの
状態（読み込まれた settings、メモリディレクティブ、compaction、skill/hook
サーフェス、作業ディレクトリ）を*近似的に*リセットするに過ぎず、その状態は
呼び出しごとに観測もハッシュ検証もできない。fresh プロセス（または fresh
SDK query）なら、実行の単位が provenance の単位と一致する: すべての
呼び出しに対し、正確に 1 つのコマンド、1 つの env、1 組の入力ハッシュ、
1 つの出力が対応する。

## resume / セッション履歴を使わない理由

Claude Code のセッショントランスクリプトを再生・手書き生成して `--resume`
する方式は、Claude Code のオンディスクセッション形式 — ARI が検証できない、
バージョンドリフトする非公開形式 — を会話状態の正本にしてしまう。ARI は
代わりにメッセージ履歴を自分で保持し、毎リクエスト全体をシリアライズする。
`--no-session-persistence` により resume 可能なものはディスク上に何も
残らない。result envelope に現れる `session_id` は監査用に provenance に
記録されるだけで、決して渡し返されない。

## 推奨設定

- **paper / idea / eval の completion 呼び出し**（BFTS セレクタ、judge、
  サマライザ）: 既定値（`strict_reproducibility`、`max_turns: 1`、
  `structured_output_transport: prompt`、`record_provenance: true`）。
- **プロンプトや配線の反復開発**: `mode: low_overhead`
  （`pip install claude-agent-sdk`）。実ランの外では
  `record_provenance: false` も可。
- **ReAct エージェントフェーズと MCP スキルはこのバックエンドを通らない。**
  エージェントループのツール呼び出しは fail-loud
  （`ClaudeCodeToolsUnsupportedError`）— ツール呼び出し可能なバックエンド
  （`cli-shim`、`ollama`、`openai` など）に向けること。MCP スキルの直接
  litellm 呼び出しは素の Anthropic API（`anthropic/<model>`、
  `ANTHROPIC_API_KEY` 必須）へ決定的にルーティングされる。
- 将来 Claude Code をエージェントエグゼキュータとして使う場合は、この
  ポリシーの緩和ではなく**別バックエンド**（例:
  `claude_code_agent_executor`）として独自のポリシーサーフェスを持つこと。

## 再現性の限界

同じ prompt でも LLM 出力の bit-level 一致は保証されない（サンプリング、
サーバ側の変更）。このプロバイダが保証するのは*検証可能性*である: 全入力、
全ポリシー、モデル ID、Claude Code/SDK バージョン、コマンド、環境
allowlist、出力とその SHA-256 ハッシュが呼び出しごとに保存されるため、
任意の結果を監査し、記録された条件で再実行できる。

## ヘルスチェック

```bash
ari doctor claude-code          # バイナリ、バージョン、ポリシー、コマンド、フラグ報告
ari doctor claude-code --live   # + schema 検証付きの実 hermetic 呼び出し 1 回
```
