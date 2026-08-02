---
sources:
  - path: ari-core/ari/mcp/client.py
    role: implementation
  - path: ari-core/ari/agent/react_driver.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: docs/reference/mcp_tools.md
    role: doc
last_verified: 2026-08-02
---

# C02: `ari-skill-tool-registry` federation 実装計画

> 状態: Proposed / new component。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務と範囲

新規 `ari-skill-tool-registry` は、外部 MCP server と MCP collection を provider-neutral に連合する。LLMへ公開するtoolは次の5個に固定する。

- `discover(query, constraints, strategy, top_k)`
- `describe(tool_ref, section, cursor)`
- `invoke(tool_ref, args, mode)`
- `get_status(handle)`
- `get_result(handle)`

このcomponentはmarketplace、科学的権威、agent loopにはならない。候補収集と実行admissionを分離し、実行はlock済みtoolだけに限定する。

## 2. 内部component

| Interface | 責務 |
|---|---|
| `CatalogSource` | source sync、cursor、candidate batch、origin chain |
| `ProviderAdapter` | describe、invoke、poll、result、cancel capability |
| `AdmissionPolicy` | discovered / callable / reproducible / scientifically_admitted 判定 |
| `ResultNormalizer` | upstream responseをResultEnvelopeへ変換 |
| catalog builder | canonical descriptor、digest、cycle/depth検出、lock/index生成 |
| runtime broker | active lockだけを読み、5-tool surfaceへdispatch |

## 3. Catalog lifecycle

```text
sources.yaml
  -> generated candidates
  -> normalization / supply-chain / conformance / scientific policy
  -> admission decisions
  -> CATALOG.lock + derived catalog.index
  -> immutable runtime snapshot
```

`sources.yaml` は少数のsourceだけを人手管理する。個別leaf toolのYAMLを手書きしない。candidateは発見されても実行不可であり、run中のsource refreshや`listChanged`はpending diffに送る。

## 4. 実装作業

| ID | 作業 | 成果物 | Exit条件 |
|---|---|---|---|
| C02-01 | A.0 static kernel | default-off Skill、5 tools、`StaticCatalogSource` | fixture 3 toolsのdiscover/describe/invoke |
| C02-02 | Generic stdio MCP adapter | initialize、paginated tools/list、tools/call、malformed stdout診断 | normal/error/large-output fixture |
| C02-03 | canonical descriptor / opaque digest | `tool_ref`、provider/schema/adapter digest | order-independent hash property test |
| C02-04 | generated catalog | `sources.yaml`、candidate objects、`CATALOG.lock`、index | deterministic rebuild、reviewable diff |
| C02-05 | federation graph safety | origin chain、visited set、depth limit、dedup | cycle / hidden leaf quarantine test |
| C02-06 | admission engine | 4 level、policy digest、evidence bundle | unadmitted invoke拒否 |
| C02-07 | async / artifact result | handle、poll、result、raw artifact | submit/poll/cancel fixture |
| C02-08 | record / replay | cassette key、EAR publish、offline replay | network/credential無しで再生 |
| C02-09 | overlap resolver | capability、equivalence、independence group、explanation | same-backendとindependent methodの識別 |
| C02-10 | scale / robustness | 1,000+ tool mock collection、pagination、bounded context | per-tool edit 0、memory/time budget内 |

## 5. Security と科学的制約

- launcherはcommand kindとargument schemaのallowlistで構築し、任意shell stringを実行しない。
- provider childにはmanifestで宣言したenvironment / credential scopeだけを渡す。
- description、schema、annotation、search scoreはuntrusted inputとしてsanitizeする。
- leaf implementationやdata sourceをcollectionが隠す場合はquarantineする。
- Toolを科学的に同等とみなすにはunit、semantics、backend/data lineageの証拠を要求する。
- disagreementは平均化せず、resultとprovenanceを別々に保持する。

## 6. 検証と受け入れ基準

- [ ] 5 tool以外のleaf schemaをLLM tool listへ直接登録しない。
- [ ] 1 source declarationで1,000 toolをimportし、個別file editがない。
- [ ] schema、adapter、provider、default semanticsの変更で`tool_ref`が変わる。
- [ ] policyだけの再評価はexecution identityとadmission digestを分離できる。
- [ ] exact duplicateはcollapseし、semantic near-matchは既定で別toolとなる。
- [ ] origin chainのcycle、深さ超過、leaf不明がquarantineされる。
- [ ] run中のcatalog updateがactive snapshotを変更しない。
- [ ] discover/describe/resultが出力上限とpaginationを守る。
- [ ] record/replayでraw result、selection reason、rejected candidate、policy versionがEARに残る。
- [ ] A64FX等のarchitecture-correct launcher、clean interpreter、stdout isolation fixtureを維持する。

## 7. 削除要件

### 7.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C02-D1 | prototypeのleaf toolごとのhand-written whitelist | `sources.yaml` + generated lock | P4 | 1,000-tool test、manual leaf record 0 |
| C02-D2 | runtime起動時のcatalog refresh / auto-admission path | reviewed `CATALOG.lock` | P4 | run immutability test、sync専用command |
| C02-D3 | leaf schemaを直接LLMへ大量公開するdebug mode | fixed 5-tool surface | P4 | progressive disclosure test、同等discover coverage |
| C02-D4 | unqualified nameによるinvoke | opaque `tool_ref` | P4 | ambiguity test、全cassette key移行 |
| C02-D5 | provider固有resultをそのまま返すadapter path | `ResultEnvelopeV1` | P4 | conformance fixture全provider green |
| C02-D6 | test用`StaticCatalogSource`のproduction registration | test fixture namespace | P5 | production config reference 0、test importは保持 |

`StaticCatalogSource`のclass自体はconformance test用に保持してよいが、production sourceとして選択できる暗黙経路は削除する。

### 7.2 削除の検証と復旧

各 deletion PR は federation conformance、1,000-tool import、catalog immutability、record/replay、対象referenceへの `rg` を実行する。削除前のlock/schema/adapter fixtureとcommitをrollback基点として保存し、archived `tool_ref` とcassette readerはsupport window中削除しない。

### 7.3 計画書自身の削除

C02-01〜10、全受け入れ基準、C02-D1〜D6を閉じ、catalog/admission/operator仕様を恒久referenceへ移した後に削除する。Stage C相当のremote transportが未実装でも、別issueへscopeを移していれば本書を完了できる。
