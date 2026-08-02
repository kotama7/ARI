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
  - path: ari-skill-tool-registry/src/tooluniverse_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/providers/tooluniverse-support-v1.json
    role: config
  - path: ari-skill-tool-registry/src/openroad_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_contracts.py
    role: schema
  - path: ari-skill-tool-registry/src/openroad_identity.py
    role: schema
  - path: ari-skill-tool-registry/src/openroad_verification.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_local.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_results.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_hpc.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_hpc_workspace.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_worker.py
    role: implementation
  - path: ari-skill-tool-registry/providers/openroad-support-v1.json
    role: config
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

## ToolUniverse v1.3.1 adapter

ToolUniverseは数千個のpublic MCP toolではなく、一つのcompact collectionとして
統合します。registry processはToolUniverseをimportしません。operator syncだけが
compactなlist/info/execute surfaceをcanonical leaf descriptorへ展開し、runtimeは
active lockに含まれるexact leaf名だけを `execute_tool` へ渡します。

support matrixはrepository commit/tag、PyPI wheel/sdist、Apache-2.0 license、
upstream dependency lock、compact contract、installed package全3,542ファイルの
canonical tree digestを固定します。sync/runtimeの双方が完全treeとshell-freeな
`tooluniverse.smcp_server:run_stdio_server` callableを検証します。version range、
起動時install、変更済みpackage、別entry pointはfail closedです。

leafごとのwrapperではなくcategory/type profileでeffect、determinism、permission、
limitation、lineageを割り当てます。upstream CLIが背景でより広い集合をloadしても
ARI側category filterを再適用し、runtimeではlock済みleaf名でも再制限します。
dynamic MCP loader、agentic/compose/code execution、credential必須、未reviewまたは
曖昧なprofile、不正schemaはquarantineします。v1.3.1固有のproperty-level
`required: true` だけは標準の親 `required` 配列へ決定的に正規化して履歴を残し、
その他のschemaを推測で修復しません。

argumentはlocked schemaでstrictに検証し、型coercionは無効です。明示 `null` は
upstreamが黙って削除するため拒否します。ToolUniverse cache/persistence、update
check、hook、searchを無効化し、resultへcollection/wheel/provider/leaf-spec identityと
`upstream_cache: disabled`を記録します。replay authorityはARI cassette/EARだけです。
collection-level trustをleafのreplay/scientific validationへ推移させません。

bulk updateはpending diffとなり、input/output/default schema変更は通常の
`--approve`だけでは承認できません。review後に
`--approve-schema-changes`も明示する必要があります。

## OpenROAD profile adapter

OpenROAD-MCPのinteractive toolはleafに公開せず、review済み
`OpenRoadExperimentV1` を1つのvirtual async leafにします。callerが渡すのは
`request_id`だけで、Tcl、path、PDK/library、OpenROAD/ORFS commit、seed、
threads、resource、containerはexperiment/method identityに固定されます。

`local-mcp` はscoped stateful sessionを使い、全terminal pathでterminateします。
`slurm` はclosed commandをdigest-pinned Tclにcompileし、固定worker/inputとともに
C06 `JobRequestV1` へsubmitします。1 node/task、threads/CPU一致、shared
work root、toolchainと同じdigestのclean/contained SIF、`network: none` が必須です。
scheduler handle/status/cancel、environment/module/container digest、logとprovenanceを
result/EARに保存し、terminal状態を確認した場合だけworkspaceを削除します。
transport結果が不明な場合はledger照合のためfail closedで保持します。

## record/replayとEAR

recordはexact arguments、catalog/policy digest、選択理由、却下候補、raw応答
digest/artifact、正規化ResultEnvelopeを保存します。replayは同じcatalogの下で
providerを起動せず再生します。証跡は `{checkpoint}/ear/catalog/` に置かれ、
既定EAR curatorで公開対象になります。

```bash
cd ari-skill-tool-registry
python src/sync_catalog.py
python src/sync_catalog.py --approve   # diffをreviewした後だけ
python src/sync_catalog.py --approve --approve-schema-changes
python scripts/verify_tooluniverse.py --help
python scripts/sync_contracts.py
pytest -q
```

leafごとのproduction record、runtime refresh、leaf schemaの直接公開、bare name
dispatch、provider固有resultの素通し、static fixtureのproduction登録は禁止です。
