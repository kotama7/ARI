# ari/agent/ リファクタリング計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [../../../REFACTORING.md](../../../REFACTORING.md)

## 0. 挙動保証契約

[マスター計画 §2](../../../REFACTORING.md) の契約を厳守する。本ディレクトリは ARI の最重要層(P2 = 決定論性)を担うため、**特に厳格**:

- `AgentLoop` クラスの公開シグネチャ: `__init__(...)`, `run(...)` を一切変えない
- `run_react()` の公開シグネチャを変えない
- `WorkflowHints` の dataclass フィールドを変えない
- `capture_env()` `read_run_env()` の戻り値スキーマを変えない
- **同一 seed・同一 experiment.md・同一 settings.json で、BFTS ツリーの形状とリーフメトリクスが完全一致**
- LLM へのシステムプロンプト・ガイダンス文字列を一字一句変えない(変えるとエージェント挙動が変わる)
- ツール呼び出し順序のフィルタリング (`_active_tools`) ロジックを意味的に同一に保つ

## 1. 現状

| ファイル | 行数 | 責務 |
|---|---|---|
| `loop.py` | 1,459 | AgentLoop クラス本体(分割対象) |
| `react_driver.py` | 436 | 低レベル ReAct 実行(メッセージウィンドウ・ツール出力切り詰め・環境スナップショット) |
| `workflow.py` | 321 | WorkflowHints dataclass、experiment.md からのヒント生成 |
| `run_env.py` | 224 | 実行環境キャプチャ(CPU、コンパイラ、シェル設定) |

**テスト**: **0 件**(`ari-core/tests/` 配下に agent 配下のテストファイルなし)

## 2. 課題

1. `loop.py` 1,459 行が分割困難な god-method (`run()` だけで 717 行)
2. テスト 0 件で、分割時の回帰検出ができない
3. `_guidance()` `_validate_metrics()` `_active_tools()` `_extract_job_ids()` が `run()` から複雑に呼ばれる

## 3. 計画(3 ステップ)

### Step 1: テスト整備(Phase 0, PR-0)

`ari-core/tests/test_agent_smoke.py` を新設、最低 3 テスト:

```python
def test_agent_loop_single_node_roundtrip():
    """モック LLM・モック MCP で 1 ノードの ReAct 往復が完了する"""

def test_react_driver_tool_invocation():
    """react_driver.run_react() がツール呼び出しを正しくディスパッチする"""

def test_workflow_phase_transitions():
    """WorkflowHints.tool_sequence 通りにフェーズ遷移する"""
```

加えて、Phase 3D 直前に追加すべき決定論性回帰テスト:

```python
def test_bfts_deterministic_tree_with_fixed_seed():
    """同一 seed・モック LLM で BFTS ツリーが完全に同じ形状になる"""
```

### Step 2: `loop.py` 分割(Phase 3, PR-3D)

**前提条件**: Step 1 のテストすべてグリーン。テスト緑がない状態で本 PR は出さない。

#### 分割マッピング

| 新ファイル | 由来行 | 含めるシンボル |
|---|---|---|
| `agent/message_utils.py` | L66–106 | `_extract_job_ids` / `_tool_was_called` |
| `agent/tool_manager.py` | L133–249 | `_available_tools_openai` / `_execute_tool_calls` / `_active_tools` |
| `agent/guidance.py` | L250–362 | `_guidance` / `_validate_metrics` |
| `agent/loop.py`(残置) | L107–128, L363–1100 | `AgentLoop.__init__` / `_notify_progress` / `run` |

#### 移動方針
- 移動するヘルパは現在 `AgentLoop` のメソッドではなく**モジュール関数または `AgentLoop` のスタティックメソッド**として書かれている可能性が高いため、まず元の定義スタイル(self を取るか取らないか)を確認してから移動先を決める。
- メソッドの場合は、(a) staticmethod にしてからモジュール関数として切り出す、または (b) 別クラス `ToolManager` `Guidance` として切り出すかを選ぶ。**(a) を優先**(クラス分割は副作用が読みづらい)。
- `loop.py` 残置側では `from .tool_manager import _available_tools_openai, ...` のように import する。

#### 分割後の `loop.py`
- 約 738 行(`AgentLoop.__init__` ~30、`_notify_progress` ~20、`run()` ~717)
- `run()` 自体を更に分割するかは Phase 3D の本 PR ではやらない。**1 PR で 1 種類の操作**の規律を守る。
- `run()` の更なる分割は将来の独立 PR で検討(候補: システムプロンプト構築 / 初回ラウンドトリップ / ループ本体 / forced finish / 最終化 の 5 段)。

## 4. 挙動保証チェックリスト

PR-3D の merge 前に必ず実施:

- [ ] Step 1 の 3 テスト + 決定論性テストすべてグリーン
- [ ] 既存の任意の v0.7 チェックポイントを `ari resume <ckpt>` で再開し、追加 1 ノードのリーフ JSON が分割前後で完全一致(seed 固定、モック LLM 使用)
- [ ] `_active_tools` のフィルタリング順序が分割前後で完全一致(unit test で table-driven 検証)
- [ ] `_guidance()` が同じ入力で同じ文字列を返す
- [ ] **Step 3 の prompt 外部化チェック**: `sha256(抽出前 SYSTEM_PROMPT) == sha256(_loader.load("agent/system"))` がアサーション通過
- [ ] **Step 3 の format 後同一性**: 同じ `{tool_desc}` `{memory_rules}` `{extra}` を渡したときの完全な system prompt 文字列が抽出前後で一致
- [ ] `pytest ari-core/tests/ -q` がグリーン
- [ ] `python -c "from ari.agent.loop import AgentLoop; print(AgentLoop.__init__.__doc__)"` が成功
- [ ] `ari run <test experiment>` の最初のノードが完了するまでの LLM 呼び出し回数・ツール呼び出し回数が分割前後で同一(loglevel=DEBUG で比較)

## 5. 注意事項

- `run_env.py` `react_driver.py` `workflow.py` は **本 PR では一切触らない**(将来必要に応じて別 PR)。
- `run()` メソッド内のシステムプロンプト構築(L383–462)に含まれる文字列は、ARI のエージェント挙動の根幹。**コピー時にホワイトスペース・改行・テンプレ変数名を絶対に変えない**。
- ツール呼び出し履歴 (`tools_called` リストや message history) のキー名・形式を変えない。

### Step 3: SYSTEM_PROMPT の外部化(Phase PC3 / PR-3D と同 PR が望ましい)

マスター §11-4 (prompt/config 外部化)の適用。詳細は [/PROMPTS_AND_CONFIG.md §3-1](../../../PROMPTS_AND_CONFIG.md)。

#### 抽出対象
- `agent/loop.py:41` の `SYSTEM_PROMPT = """\..."""` モジュール定数
- 抽出先: `ari-core/ari/prompts/agent/system.md`
- テンプレート変数(維持): `{tool_desc}` `{memory_rules}` `{extra}`

#### 手順
1. `ari/prompts/agent/system.md` を作成し、`SYSTEM_PROMPT` の内容を**末尾改行・空白を含めバイト単位で同一に**転写
2. `loop.py` 冒頭で `_loader = FilesystemPromptLoader()` を取得
3. `loop.py:470` 付近の `SYSTEM_PROMPT.format(tool_desc=..., memory_rules=..., extra=...)` を `_loader.load("agent/system").format(...)` に置換
4. `loop.py:41` の `SYSTEM_PROMPT = """..."""` 定数を削除
5. ハッシュ回帰テストを `ari-core/tests/test_prompt_extraction.py` に追加:
   ```python
   def test_agent_system_prompt_byte_identical():
       assert hashlib.sha256(_loader.load("agent/system").encode()).hexdigest() == EXPECTED_SHA
   ```

#### 挙動保証(最重要)
- 抽出後の prompt が **byte-for-byte で同一**(改行・空白・タブを含む全文字)
- `SYSTEM_PROMPT.format(...)` の最終結果が抽出前後で完全一致
- agent スモークテスト(Step 1)が緑のまま
- Step 2 の BFTS 決定論性テストが緑のまま(prompt 変動による LLM 応答変化を防ぐ)

---

## 実装完了後の削除

**Phase 3D PR がマージされ、§4 のチェックリストすべてに合格した時点で本ファイルを削除する。**

恒久化する内容(削除前に転記):
- §1 現状の責務表 → `docs/architecture.md` の Agent 章
- §0 挙動保証契約のうち決定論性の部分 → `docs/PHILOSOPHY.md`
