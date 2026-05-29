---
sources:
  - path: ari-core/pyproject.toml
    role: config
  - path: setup.sh
    role: doc
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
last_verified: 2026-05-26
---

# 互換性 & サポート

ARI が動作する環境について。バージョンに関する*ポリシー*（SemVer、サポートウィンドウ、
非推奨化）については [リリース & バージョニングポリシー](release_policy.md) を参照してください。

## Python

| | バージョン |
|---|---|
| 必須要件 | **Python ≥ 3.9** (`ari-core/pyproject.toml` の `requires-python`) |
| 推奨 | **3.10+** ([Quickstart](../getting-started/quickstart.md) は 3.10 以降を対象) |

`setup.sh` がインタプリタをチェックし、残りをインストールします。通常のユーザーとして実行してください
— `sudo` は決して使わないでください。

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

実際の動作は **Letta 0.16.7** に対して検証されています（[メモリアーキテクチャ](../concepts/memory.md)
の実装ノートを参照）。稼働中のバックエンドは `ari memory health` で確認できます。各チェックポイントには
`memory_backup.jsonl.gz` スナップショットも付随するため、Letta のバージョンをまたいでも
run はポータブルなまま保たれます。

## LLM バックエンド

モデルルーティングは LiteLLM を経由するため、あらゆる OpenAI 互換プロバイダが動作します。
`ARI_BACKEND` / `ARI_MODEL` で選択します（プロバイダプレフィックスは常に付けてください。例:
`openai/gpt-4o`）。

| バックエンド | `ARI_BACKEND` | 備考 |
|---|---|---|
| Ollama | `ollama` | ローカル、無料、API キー不要（はじめる際のデフォルト） |
| OpenAI | `openai` | クラウド、有料; `OPENAI_API_KEY` |
| Anthropic | `claude` | クラウド、有料; `ANTHROPIC_API_KEY` |
| 任意の OpenAI 互換 | (カスタム) | LiteLLM 経由でルーティング |

フェーズごとのモデルオーバーライドも利用可能です（例: アイデア生成には安価なモデル、
論文執筆にはより強力なモデル）—
[Configuration](../reference/configuration.md) と
[環境変数](../reference/environment_variables.md) を参照してください。

## Skills と core

Skills は `ari-core` とは独立してバージョン管理されます。`0.7.x` のスキルは
任意の `ari-core` `0.7.y` と動作します（マイナー内での互換性）。マイナーをまたぐ場合は
協調リリースを予定します。[リリースポリシー → 互換性ウィンドウ](release_policy.md#compatibility-windows) を参照してください。

---

関連: [リリースポリシー](release_policy.md) · [ARI について](index.md) ·
[Quickstart](../getting-started/quickstart.md) ·
[環境変数](../reference/environment_variables.md)
