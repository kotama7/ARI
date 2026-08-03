---
sources:
  - path: ari-core/ari/research_contract.py
    role: implementation
  - path: ari-skill-web/src/retrieval.py
    role: implementation
  - path: ari-skill-web/src/network_policy.py
    role: implementation
  - path: ari-skill-web/src/server.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-02
---

# 検索契約とネットワークポリシー

ARI は情報取得と科学的採用判断を分離します。`ari-skill-web` は出典を取得・正規化し、Idea、Evaluator、Paper がその利用可否を判断します。

## 公開レコード

標準結果 `ari.retrieval-result/v1` は、`RetrievalRecordV1` の `records`、digest 拘束された `SurveySnapshotV1`、`survey_snapshot_digest`、任意の checkpoint 相対 `snapshot_ref`、および provider 間の `alias_groups` を返します。public writerはcanonical `records`だけを返します。

各 record は provider、provider record/version、query、取得時刻、書誌情報、source URL、raw payload digest、DOI/arXiv/S2 alias、license/use restriction を保持します。canonical ID は provider scoped です。同じ arXiv 論文を表す AlphaXiv record と arXiv record も別 origin のまま、共通 `arxiv:` alias で結ばれます。

## 実行モード

| mode | network | artifact | 意味 |
|---|---:|---:|---|
| `live` | あり | なし | 現在のprovider応答。replay不可 |
| `record` | あり | あり | 一つの固定providerと不変cassette/snapshot |
| `replay` | なし | なし | 記録済み正規化objectを検証してそのまま返す |

`record` / `replay` は `ARI_CHECKPOINT_DIR` を必須とし、次を保存します。

```text
retrieval_cassettes/<raw-cassette-sha256>.json
retrieval_payloads/<raw-body-sha256>.bin
retrieval_snapshots/<snapshot-digest>.json
```

replay は snapshot self-digest、content-addressed path、全 artifact SHA-256、provider/query/operation/parameters、records、citation edges、warnings を検証します。provider outage は明示 error となり、別providerへ切り替わりません。複数providerを使う場合は固定callを個別に行い、上位brokerが全originを保持したままaliasで合成します。

## URL と citation の安全性

`fetch_url` は HTTP(S) の80/443のみを許可し、userinfoと非global DNS addressを拒否します。検証済みIPへ直接接続してTLS SNIを保持し、redirectごとに再検証し、HTTPS downgrade、redirect超過、size超過、非text mediaを拒否します。本文はraw artifactとして記録され、返却textはuntrusted external dataと明示されます。

`walk_citations` は depth/node/request budget とcycle detectionを持ち、上限到達時は保持済みrecord/edgeと `partial_reason` を返します。

決定的取得toolはLLMを呼びません。`rerank_retrieval_records` は独立した stochastic tool で、model、API identity、temperature、prompt/input/output digestを記録します。

## Consumer規則

Idea は `survey_snapshot_ref`、Paper は記録結果中の `snapshot_ref` を共通検証loaderで読みます。型付き結果に記録参照がない場合、inline papersへの暗黙downgradeは行いません。

[Research contract](research_contracts.md) と [Execution contract](execution_contract.md) も参照してください。
