---
sources:
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/service.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/registry.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/execution.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/migration.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/runtime.py
    role: implementation
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/contracts.py
    role: schema
last_verified: 2026-08-02
---

# Orchestrator control plane

`ari-skill-orchestrator`はARIの外部向けasynchronous control surfaceです。submission、status、
cancellation、lineage quota、authorization、安全なresult retrievalを所有します。BFTS内部や
federated leaf-tool selectionは所有しません。

## 公開契約

すべてのmodelはunknown fieldを拒否し、`ari-skill-orchestrator/schemas/`へcheck-inされています。

- `RunRequestV1`はexperiment text、idempotency key、parent、model profile、すべての
  recursion/resource/cost limitを`request_digest`へbindします。
- `RunHandleV1`は正確なrun、owner、root、depth、現在stateを識別します。
- `RunStatusV1`はtimestamp、exit/error state、上限付きnode progress、lineage budget usageを加えます。
- `RunResultV1`はstatusと`ArtifactRefV1`値を返します。
- `ArtifactRefV1`は検証済み`sha256:…` digestを`artifact_id`として使い、role、media type、sizeを
  含みますがfilesystem pathは含みません。

lifecycleは次の通りです。

```text
submitted -> running -> succeeded | failed
                     -> cancelling -> cancelled | succeeded | failed
submitted -------------------------> cancelled | failed
```

terminal rowはimmutableです。state transitionとappend-only event recordは`BEGIN IMMEDIATE`、WAL、
full synchronizationを使って`logs/.ari-orchestrator/runs.sqlite3`へcommitされます。正確な
`(principal_id, idempotency_key)` retryでは、request digestが等しければ既存handleを返し、異なれば
失敗します。

## Restartとcancellation

各runは新しいprocess sessionで小さなwrapperを開始します。wrapperは独自child process groupで
`ari run`を起動し、`run_id`と`request_digest`にbindされたreceiptをatomicに記録します。wrapperと
childのidentityは`/proc` start tickを含むため、再利用されたPIDへsignalせず、evidenceとしても
受け入れません。restart時は次のように処理します。

- 生存しidentityが一致するwrapperは`running`のままです。
- 有効なterminal receiptは記録済みterminal stateを確定します。
- terminal receiptなしでprocessが消えた場合はfail closedします。
- `submitted` rowは自動再launchせず、scienceの重複実行を防ぎます。

`stop_experiment`は最初に`cancelling`を記録し、wrapperへsignalを送り、上限付きgrace intervalを
待った後、必要ならidentityを再検証してchild/wrapper process groupをkillします。

durable process executionには現在Linux `/proc`が必要です。platformが`sched_setaffinity`を
提供する場合、wrapperは宣言CPU数をprocess affinityへ適用し、childへ共通OpenMP/BLAS thread上限を
設定します。各runにはmode 0700のprivate `HOME`を与えます。timeout enforcementはexperimentへ
委譲せずwrapperが所有します。

## Authorizationとtransport

stdioは`ARI_ORCHESTRATOR_PRINCIPAL_ID`と、任意のcomma-separated role
`ARI_ORCHESTRATOR_PRINCIPAL_ROLES`を使います。run ownerは自身のrecordへaccessでき、`admin` roleは
すべてを検査できます。status detail、artifact discovery、cancellation、lock inspectionより前に
authorizationを行います。

stdioとMCP Streamable HTTPは同じfunction/serviceを呼びます。Streamable HTTPはdefaultで
`127.0.0.1`へbindし、`ARI_ORCHESTRATOR_HTTP_TOKENS_FILE`を必須とします。このfileはsymlinkでなく
mode 0600でなければなりません。

```json
{
  "schema_version": "ari.orchestrator-token-digests/v1",
  "tokens": [
    {
      "token_sha256": "<64 lowercase hex characters>",
      "principal_id": "automation-user",
      "roles": []
    }
  ]
}
```

保存するのはtoken digestだけです。adapterはMCP SDKの`TokenVerifier`を実装するため、toolやservice
semanticsを変えずにlocal fileをOAuth resource-server verifierへ置換できます。issuer/resource
metadataは`ARI_ORCHESTRATOR_OAUTH_ISSUER_URL`と`ARI_ORCHESTRATOR_OAUTH_RESOURCE_URL`で設定します。

## Quota

各requestはper-run/lineage boundを宣言します。deployment ceilingは次の通りです。

| Environment variable | Default |
|---|---:|
| `ARI_ORCHESTRATOR_MAX_ACTIVE_RUNS` | 16 |
| `ARI_ORCHESTRATOR_MAX_NODES_PER_RUN` | 1000 |
| `ARI_ORCHESTRATOR_MAX_TOTAL_NODES` | 10000 |
| `ARI_ORCHESTRATOR_MAX_DESCENDANT_RUNS` | 1000 |
| `ARI_ORCHESTRATOR_MAX_COST_USD` | 10000 |
| `ARI_ORCHESTRATOR_MAX_CPUS` | 256 |
| `ARI_ORCHESTRATOR_MAX_TIMEOUT_MINUTES` | 2880 |

registryはparentからchild depthを導出し、root-lineageのrun、node、estimated-cost consumptionをatomicに
検査します。callerはancestorのdepth limitを増やせません。違反時はrun rowもcheckpointも作りません。

これらはadmission/execution boundでありcontainer boundaryではありません。`estimated_cost_usd`は
caller宣言値で、このserviceはmemory/GPU isolationを提供しません。experiment processは
orchestratorのUnix identityと設定済みworkspace accessで動きます。untrustedまたは相互に敵対する
workloadには、このcontrol plane外のcontainer、scheduler、別executor identityが必要です。

## Artifact admission

公開APIはfilenameを受け付けません。closed setのroot outputだけをadmitし、EAR fileは検証済み
`evidence.index.json`または`ear_published/manifest.lock` v2を通じてのみ追加します。discoveryは
traversal、symlink（parent componentを含む）、non-regular file、secret風name、record欠落、余分な
published file、size drift、digest driftを拒否します。read時にcontentを再hashし、inline payloadは
2 MiBに制限します。より大きいartifactはdigestでlistできますが`read_artifact`からdownloadできません。
deploymentは別途authorizationされたartifact storeで公開する必要があります。

`list_skills(run_id)`と`get_workflow(run_id)`には有効なrun-bound `SKILLS.lock`が必要です。返すのは
identity/digest/phase membershipだけで、entrypoint path、environment名、credential scope、raw schema、
LLM configuration、resourceは返しません。

## Credentialとenvironment boundary

launcherは`ari.public.execution.build_minimal_environment`を使い、parent environment全体をcopyしません。
model credentialはmanifestの`model.provider` scopeだけを通れます。credential値はchild processが
memory上でinheritしますが、request JSON、SQLite、metadata、argv、runner receiptには現れません。
tool schemaにAPI-key argumentはありません。per-run private `HOME`はshared home経由の通常credential/
cache再利用を防ぎますが、OS-level isolationの代替ではありません。

## Migrationと削除

通常のstatus/list callはcheckpoint directoryをscanしません。controlled migrationには
`python ari-skill-orchestrator/src/server.py --repair-registry`を実行します。これは`experiment.md`を持つ
安全なdirect-child checkpointだけをimportします。ambiguousまたはapparently liveなlegacy stateは
`failed`となり、再launchされません。検証後、release support windowに従って古いcheckpoint metadata
readerを削除します。

version 2ではarbitraryな`read_file`/`list_files`、substring run matching、environment copy、raw
workflow/Skill configuration、request-level credential、scan由来live state、独自REST/SSE実装を
削除しました。network adapterはauthenticated MCP Streamable HTTPだけです。
