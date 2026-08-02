---
sources:
  - path: ari-skill-tool-registry/src/models.py
    role: implementation
  - path: ari-skill-tool-registry/src/providers.py
    role: implementation
  - path: ari-skill-tool-registry/src/sources.py
    role: implementation
  - path: ari-skill-tool-registry/src/admission.py
    role: implementation
  - path: ari-skill-tool-registry/src/catalog.py
    role: implementation
  - path: ari-skill-tool-registry/src/broker.py
    role: implementation
  - path: ari-skill-tool-registry/src/storage.py
    role: implementation
last_verified: 2026-08-02
---

# 科学ツール連合レジストリ

`ari-skill-tool-registry` は多数のMCP collectionを `discover`、`describe`、
`invoke`、`get_status`、`get_result` の5操作の背後に統合する、デフォルトOFF
のSkillです。leaf schemaをすべてモデルへ渡さず、collection追加時にもleaf
ごとのファイル編集を要求しません。

## 境界とライフサイクル

```text
少数のreview済み sources.yaml
  -> 隔離したprovider discovery
  -> canonical descriptorと可視なorigin chain
  -> graph・supply chain・conformance・科学admission
  -> review済み CATALOG.lock + 派生index
  -> immutableな5操作broker
```

runtimeは `sources.yaml` を読みません。sync差分はpending lock/indexとreview用
diffになり、`--approve` でだけactive lockを置換します。実行中brokerのsnapshot
は変化しません。

`tool_ref` はprovider、adapter、schema、明示default、permission/effect、
determinism、実行意味、method identity、async lifecycleから作るopaque digest
です。policyとsource aliasは別identityなので、policy再評価で実装変更を偽装
できません。

## 科学的admission

| Level | 必要な根拠 |
|---|---|
| `discovered` | candidateとleaf originが明示される |
| `callable` | MCP conformance、provider pin、launcher検証、permission許可 |
| `reproducible` | callableに加えdependency pinとoffline replay fixture |
| `scientifically_admitted` | validation、limitation、semantics、unit、method identity |

発見されたこと自体は権威や科学的正当性を意味しません。registryは根拠と
policy判定を報告し、upstream collectionを無条件には信頼しません。

## collectionの合成と競合

同一execution identityのaliasだけをcollapseし、全source/origin chainを保持
します。同様のcapabilityは既定で別toolです。exact duplicate、same backend、
semantic near-match、independent methodを区別し、名前が似ているだけで平均化
しません。結果の不一致も別々のprovenance付きで残します。

この境界により、ToolUniverse型collection、OpenROAD、量子simulator、将来の
MCP bundleをpackage固有routingなしで共存させられます。direct stdio MCPは
custom leaf code不要です。異なるtransportはcollection全体につき1個の
`CatalogSource` と `ProviderAdapter`、およびconformance fixtureを追加します。

## record/replayとEAR

recordはexact arguments、catalog/policy digest、選択理由、却下候補、raw応答
digest/artifact、正規化ResultEnvelopeを保存します。replayは同じcatalogの下で
providerを起動せず再生します。証跡は `{checkpoint}/ear/catalog/` に置かれ、
既定EAR curatorで公開対象になります。

```bash
cd ari-skill-tool-registry
python src/sync_catalog.py
python src/sync_catalog.py --approve   # diffをreviewした後だけ
python scripts/sync_contracts.py
pytest -q
```

leafごとのproduction record、runtime refresh、leaf schemaの直接公開、bare name
dispatch、provider固有resultの素通し、static fixtureのproduction登録は禁止です。
