---
sources:
  - path: ari-core/pyproject.toml
    role: config
  - path: setup.sh
    role: doc
  - path: scripts/setup/detect_env.sh
    role: config
  - path: scripts/setup/install_letta.sh
    role: config
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
  - path: ari-core/ari/llm/routing.py
    role: implementation
  - path: ari-core/ari/llm/client.py
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
last_verified: 2026-08-16
---

# 互換性 & サポート

ARI が動作する環境について。バージョンに関する*ポリシー*（SemVer、サポートウィンドウ、
非推奨化）については [リリース & バージョニングポリシー](release_policy.md) を参照してください。

## Python

| | バージョン |
|---|---|
| パッケージメタデータ | **Python ≥ 3.9** (`ari-core/pyproject.toml` の `requires-python`) |
| `setup.sh` が受け付ける範囲 | **Python ≥ 3.10** — `scripts/setup/detect_env.sh` はそれより古いものに警告を出し、3.10 に達するインタプリタが 1 つも無ければ `exit 1` します |

両者は食い違っています: `pip install` は 3.9 を受け入れますが、インストーラは受け入れません。
実際の下限は **3.10** と考えてください — いくつかの依存関係（`mcp>=1.1`）がそれを要求します。

`setup.sh` がインタプリタをチェックし、リポジトリルートに `.venv` を作成して、残りを
インストールします。通常のユーザーとして実行してください — `sudo` は決して使わないでください。

## オペレーティングシステム

| OS | ステータス |
|---|---|
| Linux | サポート |
| macOS | サポート |
| Windows | WSL2 経由 |

## メモリバックエンド (Letta)

ARI のメモリは v0.6.0 以降 [Letta](https://docs.letta.com)（旧 MemGPT）が
バックエンドです。`setup.sh` が最適なデプロイ方式を自動検出してブートストラップします:
Docker → Singularity/Apptainer → pip（`SKIP_LETTA_SETUP=1` でスキップ可能）。
`SLURM_CLUSTER_NAME` または `SLURM_JOB_ID` が設定されている場合、デーモンが使える状態でも
Docker は最初から除外されます。そのためジョブ確保の内側でセットアップを実行すると
Singularity/Apptainer に落ち着きます。

実際の動作は **Letta 0.16.7** に対して検証されています（[メモリアーキテクチャ](../concepts/memory.md)
の実装ノートを参照）。稼働中のバックエンドは `ari memory health` で確認できます。各チェックポイントには
`memory_backup.v1.json.gz` スナップショットも付随するため、Letta のバージョンをまたいでも
run はポータブルなまま保たれます。

## LLM バックエンド

モデルルーティングは LiteLLM を経由するため、あらゆる OpenAI 互換プロバイダが動作します。
`ARI_BACKEND` / `ARI_MODEL` で選択します。プロバイダプレフィックスを自分で書く必要は
ありません: `resolve_litellm_model` が `ARI_BACKEND` から導出します
（`ollama` → `ollama_chat/…`、`claude`/`anthropic` → `anthropic/…`、`cli-shim`
→ `openai/…`、`openai` および未知の値 → そのまま）。既知のプレフィックスが付いた
モデル ID はそのまま素通しされます。

| バックエンド | `ARI_BACKEND` | 備考 |
|---|---|---|
| Ollama | `ollama` | ローカル、無料、API キー不要（はじめる際のデフォルト） |
| OpenAI | `openai` | クラウド、有料; `OPENAI_API_KEY` |
| Anthropic | `claude` | クラウド、有料; `ANTHROPIC_API_KEY` |
| Claude Code CLI | `claude_code` | エージェントループでは LiteLLM 経由**ではありません** — `LLMClient` が `ari/llm/claude_code/` にディスパッチし、そこではツール呼び出しがサポートされません（明示的に失敗）。`ARI_BACKEND` を直接解決する MCP スキルは通常の Anthropic API に向かうため、`ANTHROPIC_API_KEY` が必要です。 |
| 任意の OpenAI 互換 | (カスタム) | LiteLLM 経由でルーティング |

フェーズごとのモデルオーバーライドも利用可能です（例: アイデア生成には安価なモデル、
論文執筆にはより強力なモデル）—
[Configuration](../reference/configuration.md) と
[環境変数](../reference/environment_variables.md) を参照してください。

## Skills と core

Skills は `ari-core` とは独立してバージョン管理されており、その番号は core を
追随していません: `ari-core` が `0.9.1` である一方、同梱スキルの番号は `0.1.0` から
`2.0.0` まで散らばっています。スキルと core のバージョン組み合わせを強制するコードは
存在しないため、番号の一致ではなく協調リリース単位で組み合わせてください。
[リリースポリシー → 互換性ウィンドウ](release_policy.md#compatibility-windows) を参照してください。

---

関連: [リリースポリシー](release_policy.md) · [ARI について](index.md) ·
[Quickstart](../getting-started/quickstart.md) ·
[環境変数](../reference/environment_variables.md)
