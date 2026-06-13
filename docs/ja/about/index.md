---
sources:
  - path: CONTRIBUTING.md
    role: doc
  - path: CHANGELOG.md
    role: doc
last_verified: 2026-06-10
---

# ARI について

プロジェクトのメタ情報 — 個々の機能ではなく、プロジェクト全体を統括するポリシーとリファレンス群です。

## ポリシー & リファレンス

| ドキュメント | 内容 |
|---|---|
| [リリース & バージョニングポリシー](release_policy.md) | SemVer の解釈、パブリックサーフェス、サポートウィンドウ、非推奨化ライフサイクル、リリースチェックリスト（ドキュメントゲートを含む）。 |
| [互換性 & サポート](compatibility.md) | サポートする Python、Letta メモリバックエンド、LLM バックエンド。 |
| [コントリビューション](../../../CONTRIBUTING.md) | ソフトウェアエンジニアリングの規律、レイヤード・アーキテクチャ、パブリック API ルール、非推奨化プロセス。 |
| [変更履歴](../../../CHANGELOG.md) | リリースごとのノート（Added / Changed / Fixed / Deprecated / Removed / Security）。 |
| [セキュリティポリシー](../../../SECURITY.md) | 脆弱性の報告方法と、修正が提供されるバージョン。 |

## ライセンス

ARI はリポジトリレベルのライセンスファイルを 1 つだけ同梱するわけではありません。ライセンスは
**公開アーティファクトごと**に決まります。Experiment Artifact Repository
(EAR) を公開すると、その `ear/publish.yaml` が SPDX の `license`
(MIT / Apache-2.0 / BSD-3-Clause / GPL-3.0 / CC-BY-4.0) を宣言し、`generate_ear`
が対応する `LICENSE` ファイルをバンドルに出力します。
[Configuration → EAR Curation](../reference/configuration.md#ear-curation-earpublishyaml--v070) を参照してください。

---

関連: [ドキュメント索引](../../README.md) ·
[リリースポリシー](release_policy.md) · [互換性](compatibility.md)
