# ARI プロンプト・設定外部化計画

> **このドキュメントは一時計画です。実装完了後に削除してください。**
> マスター計画: [REFACTORING.md](REFACTORING.md) §11-4 から本書を参照。

## 0. 設計目的

ARI コア内の **すべての LLM プロンプト** と **設定値(モデル名・URL・閾値)** をコード本体から分離する。

**狙い:**
- **テスト容易性**: prompt 差替テスト・回帰テストがコード変更なしで可能
- **A/B / バージョン管理**: prompt の差分が git diff で読みやすく、PR レビューが意味単位で行える
- **挙動の透明性**: ARI が LLM に何を渡しているかをコードを読まずに把握できる
- **再現性 (P5)**: 特定 prompt バージョンで生成した実験を後から再現可能
- **疎結合 (REFACTORING.md §11-2)**: コードは「prompt を使う」だけで「prompt を持つ」状態を解消

## 1. 現状(監査結果)

### 1-1. ari-core 内のハードコード prompt(必ず外部化)

| ファイル | 行 | 形態 | 用途 |
|---|---|---|---|
| `ari/agent/loop.py` | L41 | `SYSTEM_PROMPT = """\..."""` モジュール定数 | エージェントのシステムプロンプト(`{tool_desc}` `{memory_rules}` `{extra}` テンプレート変数を含む) |
| `ari/orchestrator/lineage_decision.py` | L239 | `_SYSTEM_PROMPT = (...)` モジュール定数 | lineage decision 用システムプロンプト |
| `ari/orchestrator/root_idea_selector.py` | L57 | `_SYSTEM_PROMPT = (...)` モジュール定数 | root idea 選定用システムプロンプト |
| `ari/orchestrator/bfts.py` | L215 | f-string インライン | BFTS ノード選定 prompt |
| `ari/orchestrator/bfts.py` | L296 | f-string インライン | 完了ノード expand 選定 prompt |
| `ari/orchestrator/bfts.py` | L481 | f-string インライン | BFTS ノード expand 用 prompt |
| `ari/pipeline.py` | L430 | f-string インライン | "You are a research librarian..."(キーワード抽出) |
| `ari/evaluator/llm_evaluator.py` | L165, L324 | インライン文字列 + `_build_system_prompt()` | メトリクス抽出 + ピアレビュー prompt |

### 1-2. ari-core 内のハードコード設定値(外部化検討)

| ファイル | 行 | 形態 | 用途 |
|---|---|---|---|
| `ari/cost_tracker.py` | L16–33 | `_PRICE_PER_1K = { ... }` dict | LLM モデル価格テーブル(18 モデル) |
| `ari/config.py` | L14 | `backend: str = "ollama"` | LLM バックエンド既定値 |
| `ari/config.py` | L240–241 | `os.environ.get("ARI_BACKEND", "ollama")` 等 | env フォールバック |
| `ari/orchestrator/lineage_decision.py` | L266 | `or "gpt-4o-mini"` | LLM モデル既定値ハードコード |
| `ari/core.py` | L159 | `if llm.config.backend == "ollama"` | ベースURL 分岐ロジック |

### 1-3. viz UI 補助 prompt(優先度: 低)

| ファイル | 行 | 用途 |
|---|---|---|
| `ari/viz/api_tools.py` | L53, L132 | UI ウィザード補助 prompt |

→ Phase 後半で対処。挙動保証契約上は同じ扱いだが、影響範囲が小さい。

### 1-4. スキル側の現状(参考、本計画の対象外)

スキルは既に **prompt 分離パターンを実装済み**:
- `ari-skill-replicate/src/prompts/` — `skeleton.md` `subtree.md` `auditor.md`
- `ari-skill-paper-re/src/prompts/` — vendored
- `ari-skill-paper/templates/` — LaTeX テンプレート

新規スキル開発時もこのパターンを踏襲すること(`docs/extension_guide.md` で明記する)。

## 2. 設計

### 2-1. ディレクトリ構造(新設)

```
ari-core/ari/
├── prompts/                      # 全プロンプトの所在
│   ├── __init__.py               # PromptLoader 公開
│   ├── _loader.py                # PromptLoader 実装
│   ├── agent/
│   │   └── system.md             # agent SYSTEM_PROMPT
│   ├── orchestrator/
│   │   ├── lineage_decision.md
│   │   ├── root_idea_selector.md
│   │   ├── bfts_select.md        # bfts.py L215
│   │   ├── bfts_expand_select.md # bfts.py L296
│   │   └── bfts_expand.md        # bfts.py L481
│   ├── pipeline/
│   │   └── keyword_librarian.md  # pipeline.py L430
│   ├── evaluator/
│   │   ├── extract_metrics.md
│   │   └── peer_review.md
│   └── viz/
│       └── wizard_*.md           # api_tools.py(後回し)
└── configs/                      # 既定値・参照テーブル
    ├── __init__.py
    ├── _loader.py                # ConfigLoader 実装
    ├── model_prices.yaml         # cost_tracker.py L16-33 の置換先
    └── defaults.yaml             # backend / llm model 等の既定値
```

### 2-2. PromptLoader Protocol(`ari/protocols/`)

```python
# ari/protocols/prompt_loader.py
from typing import Protocol

class PromptLoader(Protocol):
    """Loads prompt templates from external files.

    Implementations may load from filesystem, embedded resources, or remote.
    """
    def load(self, key: str) -> str:
        """Load raw prompt template for the given key (e.g. "agent/system")."""
        ...

    def load_versioned(self, key: str, version: str | None = None) -> tuple[str, str]:
        """Load prompt and return (text, version_id) for reproducibility."""
        ...
```

### 2-3. ConfigLoader Protocol

```python
# ari/protocols/config_loader.py
from typing import Protocol, Any

class ConfigLoader(Protocol):
    """Loads non-Pydantic config values (lookup tables, defaults)."""
    def load(self, key: str) -> Any:
        """Load YAML/JSON config blob (e.g. "model_prices")."""
        ...
```

### 2-4. 既定実装

```python
# ari/prompts/_loader.py
from pathlib import Path
from importlib.resources import files

class FilesystemPromptLoader:
    def __init__(self, base: Path | None = None):
        self._base = base or Path(files("ari.prompts"))

    def load(self, key: str) -> str:
        path = self._base / f"{key}.md"
        return path.read_text(encoding="utf-8")

    def load_versioned(self, key: str, version: str | None = None) -> tuple[str, str]:
        # version 指定なしなら現在バージョン(git sha or content hash)を返す
        text = self.load(key)
        import hashlib
        return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
```

### 2-5. テンプレート展開規約

- **Python の `str.format()` 構文** を使う(`{var_name}`)
  - 理由: 標準ライブラリのみで動く、Jinja2 等の外部依存を増やさない
  - 制約: 条件分岐・ループは prompt 内で書かない(必要なら呼び出し側で文字列を組み立て、`{extra}` のような変数経由で注入)
- **改行・末尾改行を完全に保持**(挙動保証 §3-1 で検証)

## 3. 移行計画(ファイル単位)

各ファイルの移行は **Phase 3 のサブ PR(独立)** または **対応する分割 PR と同時** に実施する。

### 3-1. `ari/agent/loop.py` (Phase 3D 内)

| ステップ | 内容 |
|---|---|
| 1 | `ari/prompts/agent/system.md` を作成し、L41 `SYSTEM_PROMPT` の三重引用符内文字列を**バイト単位で同一**に転写 |
| 2 | `loop.py` 冒頭で `_loader = FilesystemPromptLoader()` 取得 |
| 3 | L470 `SYSTEM_PROMPT.format(...)` を `_loader.load("agent/system").format(...)` に置換 |
| 4 | L41 の `SYSTEM_PROMPT = """..."""` 定数を削除 |
| 5 | `sha256(旧 SYSTEM_PROMPT) == sha256(load("agent/system"))` を回帰テストに追加 |

**詳細:** [ari-core/ari/agent/REFACTORING.md](ari-core/ari/agent/REFACTORING.md) Step 3。

### 3-2. `ari/orchestrator/lineage_decision.py`

- L239–284 (約 45 行)の `_SYSTEM_PROMPT` ブロックを `ari/prompts/orchestrator/lineage_decision.md` へ転写
- L286 の `{"role": "system", "content": _SYSTEM_PROMPT}` を `_loader.load("orchestrator/lineage_decision")` に
- L266 `or "gpt-4o-mini"` のモデル既定値も `ari/configs/defaults.yaml` に外部化

### 3-3. `ari/orchestrator/root_idea_selector.py`

- L57–155 (約 100 行)の `_SYSTEM_PROMPT` を `ari/prompts/orchestrator/root_idea_selector.md` へ
- L157 の使用箇所を Loader 経由に

### 3-4. `ari/orchestrator/bfts.py`

3 箇所(L215, L296, L481)のインライン f-string prompt をそれぞれ:
- `ari/prompts/orchestrator/bfts_select.md`
- `ari/prompts/orchestrator/bfts_expand_select.md`
- `ari/prompts/orchestrator/bfts_expand.md`

f-string の変数(`{node.id}` `{node.metrics}` 等)は `str.format()` 互換にして、呼び出し側で format()。

**重要:** bfts.py の prompt は P2(決定論性)に直結する。同一 seed でテンプレート展開後の文字列が完全一致すること。

### 3-5. `ari/pipeline.py` L430

`"You are a research librarian. ..."` を `ari/prompts/pipeline/keyword_librarian.md` へ。
`pipeline.py` の分割(Phase 3-PR-3C)と同 PR で実施。

### 3-6. `ari/evaluator/llm_evaluator.py`

- L165 のインライン文字列 → `ari/prompts/evaluator/extract_metrics.md`
- L324 `_build_system_prompt()` メソッドの組み立てロジックを **prompt 側のテンプレート変数で表現**(必要に応じて 2 ファイルに分割)
- 詳細は [ari-core/ari/evaluator/REFACTORING.md](ari-core/ari/evaluator/REFACTORING.md)

### 3-7. `ari/cost_tracker.py` モデル価格テーブル

L16–33 の dict を `ari/configs/model_prices.yaml` へ:

```yaml
# ari/configs/model_prices.yaml
# (input_per_1k_usd, output_per_1k_usd)
gpt-4o-mini:       [0.00015, 0.0006]
gpt-4o:            [0.0025, 0.010]
claude-opus-4-6:   [0.005, 0.025]
# ... (18 モデル全部)
```

`cost_tracker.py` 起動時に `ConfigLoader.load("model_prices")` で読み込む。

**注意:** 新規モデル追加時は YAML を更新するだけ → コード PR 不要。

### 3-8. `viz/api_tools.py` の UI prompt(優先度: 低)

L53, L132 を `ari/prompts/viz/wizard_*.md` へ。Phase 3 後半または Phase 5 で対応可。

## 4. 挙動保証契約

[REFACTORING.md §2](REFACTORING.md) と並ぶ厳格契約:

- **prompt 文字列のバイト一致**: 抽出前後で prompt が **byte-for-byte で完全に同一**
  - sha256 ハッシュ比較を回帰テストに追加(対象 8 prompt × 1 ハッシュ = 8 アサーション)
  - 末尾改行・タブ・全角空白を含むすべてを保持
- **テンプレート展開後も同一**: `prompt.format(**vars)` の結果が抽出前と同一
- **モデル価格テーブル**: YAML 化前後で `cost_tracker.record()` の出力が同一
- **既定値**: `defaults.yaml` 化前後で同一の env / 引数で同一の挙動
- **P2 決定論性**: 同一 seed での BFTS ツリー形状が prompt 抽出前後で完全一致

## 5. テスト戦略

### 5-1. 抽出時の回帰テスト(必須)

`ari-core/tests/test_prompt_extraction.py`(新規):
```python
def test_agent_system_prompt_byte_identical():
    """SYSTEM_PROMPT 抽出前と後で sha256 一致"""
    expected_sha = "<抽出前にビルド時に計測した値>"
    actual = FilesystemPromptLoader().load("agent/system")
    assert hashlib.sha256(actual.encode()).hexdigest() == expected_sha

# orchestrator/lineage_decision, root_idea_selector, bfts × 3, pipeline, evaluator × 2 すべて
```

### 5-2. プロンプト存在確認テスト
```python
def test_all_required_prompts_exist():
    loader = FilesystemPromptLoader()
    for key in REQUIRED_PROMPTS:  # 8〜10 keys
        assert loader.load(key)  # raises if missing
```

### 5-3. 統合テスト
- 既存 `test_agent_smoke.py`(REFACTORING Phase 0 で新設)が抽出後も緑

## 6. Phase 計画

| Phase | 内容 | PR | 期間 |
|---|---|---|---|
| **PC0** | `ari/protocols/` `ari/prompts/` `ari/configs/` 骨組み新設 + Loader 実装 + 回帰テスト雛形 | 1 | 2 日 |
| **PC1** | `cost_tracker.py` モデル価格テーブル外部化(最も独立) | 1 | 0.5 日 |
| **PC2** | `pipeline.py` L430 prompt 抽出(Phase 3-PR-3C と同 PR が望ましい) | 1 | 0.5 日 |
| **PC3** | `agent/loop.py` SYSTEM_PROMPT 抽出(Phase 3-PR-3D と同 PR) | 1 | 1 日 |
| **PC4** | `orchestrator/{lineage_decision, root_idea_selector}.py` の 2 prompt 抽出 | 1 | 1 日 |
| **PC5** | `orchestrator/bfts.py` の 3 inline prompt 抽出(P2 決定論回帰テスト必須) | 1 | 1.5 日 |
| **PC6** | `evaluator/{llm_evaluator, dynamic_axes}.py` 抽出 | 1 | 1 日 |
| **PC7** | `defaults.yaml` 既定値外部化(模型・URL・閾値) | 1 | 1 日 |
| **PC8** | `viz/api_tools.py` UI prompt 抽出(後回し可) | 1 | 0.5 日 |

**合計**: 約 9 日(リファクタ Phase 3 と並走可能、PC3/PC5 のみ Phase 3D と直接連動)

## 7. 受け入れ基準(全 PC PR 共通)

- [ ] 該当 prompt の sha256 が抽出前後で完全一致
- [ ] `pytest ari-core/tests/test_prompt_extraction.py -q` がグリーン
- [ ] `pytest ari-core/tests/test_agent_smoke.py -q` がグリーン
- [ ] `grep -rn '"""[^"]*role.*system\|f"You are' ari-core/ari/` のヒットが該当ファイル除去後に減少
- [ ] BFTS 同一 seed テスト(PC5 のみ)で形状一致

## 8. ドキュメンテーション計画との連動

[DOCUMENTATION_PLAN.md](DOCUMENTATION_PLAN.md) Phase D2 にて以下を追記:

- `docs/extension_guide.md` に「新スキル/新コア機能で LLM を使う場合は `ari/prompts/<area>/<purpose>.md` に prompt を置く」規約を追加
- `docs/architecture.md` に Prompt/Config レイヤを追加
- `docs/reference/prompts.md`(新規)で prompt キー一覧と各テンプレート変数を記載

## 9. 既存スキルとの整合

スキル側はそれぞれ独自の `src/prompts/` を持っているため**触らない**(P1: スキルが自律して prompt を持てるのが意図)。

ただし、新規スキル開発ガイド(`docs/extension_guide.md`)で「prompt は必ず `src/prompts/` に置くこと」を明記する。

## 10. リスク

| リスク | 緩和策 |
|---|---|
| 抽出時に末尾改行/空白が変わり LLM 応答が変動 | sha256 ハッシュ比較を CI で必須化 |
| 既存ユーザの fork が `_SYSTEM_PROMPT` 等を直接参照していると import エラー | 移行期は `from ari.prompts import ... as _SYSTEM_PROMPT` 互換 shim を 1 マイナーバージョン残す |
| YAML config の読み込み失敗時のフォールバック | パッケージ同梱の YAML を絶対パスで参照、欠損時は明確な FileNotFoundError |
| `bfts.py` の f-string を `.format()` に置換する際の変数名衝突 | Python AST 解析で変数を抽出し自動マッピング、回帰テストで担保 |

---

## 実装完了後の削除

**Phase PC0〜PC8 のすべての PR がマージされ、§7 の受け入れ基準を全 PR で満たした時点で本ファイルを削除する。** マスター計画 [REFACTORING.md](REFACTORING.md) の deletion バッチに含めること。

恒久化する内容(削除前に転記):
- §2 ディレクトリ構造 → `docs/architecture.md` の Prompt/Config レイヤ章
- §2-2, §2-3 Protocol 定義 → 実コード(`ari/protocols/`)が代替
- §2-5 テンプレート展開規約 → `docs/extension_guide.md` の規約節
- §9 既存スキルとの整合 → `docs/extension_guide.md`
