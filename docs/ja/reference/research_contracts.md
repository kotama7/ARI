---
sources:
  - path: ari-core/ari/research_contract.py
    role: implementation
  - path: ari-skill-idea/src/contracts.py
    role: implementation
  - path: ari-skill-evaluator/src/server.py
    role: implementation
last_verified: 2026-08-02
---

# 研究契約

ARIは文献取得から実験実行までの科学的判断を3つのimmutable recordとして固定します。

1. `SurveySnapshotV1`は固定provider、query、取得時刻、正規化record、citation edge、
   artifact、および元のlive操作がbyte reproducibleかを記録します。
2. `IdeaSetV1`はmodel、prompt template digest、sampling、seed、adapter/vendor revision、
   source snapshot、採用candidate、決定論的なreject理由を記録します。
3. `ResearchContractV1`は採用candidateから一度だけmintされ、仮説、反証条件、metric名、
   unit、direction、comparison scope、required evidence、引用、制約、source digestを固定します。

各recordはdigest field自身を除くcanonical JSONのSHA-256を持ち、readerはparse時に検証します。
evaluatorは`ResearchContractV1`をそのまま使用し、同じ`research_contract_digest`を
`metric_contract.json`へ書きます。LLMによるmetric/evidence語彙の再抽出は行いません。

`survey(mode="record")`は障害時にproviderを変更しません。`survey(mode="replay")`はnetworkを
使わず、指定checkpoint artifactだけを読み、欠落・破損・digest不一致を拒否します。

top-levelのflatな`ideas`や`primary_metric`は旧checkpoint用projectionです。新consumerはtyped
recordを使います。新形式を宣言しながら採用contractがないdocumentはfail-closedとなり、旧prose
推論へdowngradeできません。schemaは`ari-core/ari/schemas/`、公開APIは
`ari.public.research_contract`です。

provider cassette、検証済みsnapshot ref、URL policy、alias合成は
[検索契約](retrieval_contract.md)で定義します。
