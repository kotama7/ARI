---
sources:
  - path: ari-core/ari/mcp/client.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: docs/reference/internal_boundaries.md
    role: doc
  - path: ari-core/ari/result.py
    role: implementation
  - path: ari-core/ari/schemas/result_envelope_v1.schema.json
    role: config
last_verified: 2026-08-02
---

# C01: `ari-core` Skill control plane 実装計画

> 状態: In progress（C01-01/02/05完了、C01-03/04/09/10は互換移行中）。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務と範囲

`ari-core` は Skill の業務ロジックを持たず、次を所有する。

- canonical manifest の読み込みと検証
- Skill process lifecycle、transport、timeout、cancellation
- phase policy、tool identity、collision detection、dispatch
- run-level immutable Skill snapshot
-最小環境とcredential scopeの構築
- ResultEnvelope、artifact store、trace / EAR handoff
- `ari.public.*` による stable cross-package contract

個別の論文生成、統計、scheduler command、domain tool validation は各 owner component に残す。

## 2. 現状根拠

- `ari/mcp/client.py` は Python stdio server を固定形式で起動し、親の環境をほぼ全て渡す。
- tool registry は `tool_name -> skill.name` であり、同名 tool の後勝ちを検出しない。
- slow tool timeout と memory CoW tool は tool 名の hard-coded set である。
- `ari/config/__init__.py` は `ari-skill-*` directory を走査し、`src/server.py` の存在で自動登録する。
- viz settings は manifest に不足がある場合 `server.py` から tool 名を抽出する fallback を持つ。
- `ari.public.*` は既に一部 cross-package API を提供しており、移行の足場として使える。

## 3. 目標契約

1. `SkillManifestV1` を Pydantic / JSON Schema で定義し、起動前に検証する。
2. runtime identity を `skill_ref` と `tool_ref` に分け、bare name は表示用 alias に限定する。
3. `MCPClient` は phase ごとの `SKILLS.lock` から接続を構築し、run 中に再発見しない。
4. tool call は versioned `ResultEnvelope` を返し、大きな content は artifact reference にする。
5. child environment は allowlist と credential broker から構築し、未宣言 secret を継承しない。
6. timeout、async、side effect、permissions、node-context requirement は manifest metadata から解決する。
7. record / replay は core trace と artifact store を通り、Skill 固有 cache を authority にしない。

## 4. 実装作業

| ID | 作業 | 成果物 | 依存 |
|---|---|---|---|
| C01-01 | 現行 package / tool / workflow inventoryをgolden fixture化 | `SkillInventoryV1` fixture、drift report | P0 |
| C01-02 | `SkillManifestV1` とschema loaderを追加 | `ari.public.skill_manifest`、schema、validation error | C01-01 |
| C01-03 | manifestからconnection specを構築 | stdio Python互換adapter、launcher allowlist | C01-02 |
| C01-04 | namespaced registryとcollision policyを追加 | immutable `tool_ref`、duplicate/equivalence判定hook | C01-02 |
| C01-05 | `ResultEnvelopeV1` とartifact externalization | public model、bounded rendering、raw response保存 | C01-02 |
| C01-06 | child environment policyを実装 | allowlist、secret redaction、credential scope identity | C01-03 |
| C01-07 | run snapshotを固定 | `SKILLS.lock`、schema/provider digest、phase別active set | C01-04 |
| C01-08 | explicit `RunContext` / `NodeContext` をcallへ渡す | parallel-safe context、memory連携 | C01-05 |
| C01-09 | capability-based timeout / async handle | hard-coded tool名に依存しないbudgetとpolling | C01-05 |
| C01-10 | conformance CIとmigration reader | manifest/tools/workflow/version check、旧config fixture | C01-02〜09 |

## 5. Compatibility と rollout

- 最初は現行 `SkillConfig` から `SkillManifestV1` へ変換する compatibility adapter を置く。
- P1では旧 `mcp.json` / `skill.yaml` を読み取り専用入力として許すが、生成した manifest diff をCIで表示する。
- P2で canonical manifest を既定にし、旧config readerはmigration専用に隔離する。
- `call_tool(name, args)` は内部で一意に解決できる期間だけ維持し、collision 時は明示 error と候補を返す。
- old checkpoint readerはruntime registrationに使用せず、replay/migration pathだけに残す。

## 6. 検証と受け入れ基準

- [x] 全既存 Skill の manifest がschema validationを通る。
- [ ] manifest tools と live `tools/list` の追加・欠落・schema drift がCIでfailする。
- [x] 同名の異なる2 toolを登録すると起動時にcollision errorになり、黙って上書きされない。
- [ ] run開始後にmanifest fileを変更してもactive snapshotは変わらない。
- [ ] secret markerを親envへ置いたtestで、未許可Skillから参照できない。
- [x] 4 parallel nodeのmemory writeでnode contextが交差しない。
- [x] 4,000文字を超える結果がartifact化され、digestから復元できる。
- [x] stdio server error、timeout、cancel、malformed stdoutがtyped errorになる。
- [ ] 現行golden checkpointを新readerで開き、paper/replay contractが維持される。
- [x] `pytest ari-core/tests -q` と全manifest contract testがgreenである。

## 7. 削除要件

### 7.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C01-D1 | bare-nameのlast-writer-wins `_tool_registry` | namespaced immutable registry | P2 | collision test、全call siteが`tool_ref`または一意aliasを使用 |
| C01-D2 | `_server_params()` の `{**os.environ, ...}` | child environment policy | P2 | secret non-propagation test、全Skillのrequired env宣言 |
| C01-D3 | `_SLOW_TOOLS` / `_VERY_SLOW_TOOLS` のtool名list | manifest timeout class / per-call budget | P2 | timeout fixture parity、manifest coverage 100% |
| C01-D4 | `_COW_TOOLS` と `_set_current_node` 依存 | explicit `NodeContext` | P3 | parallel memory conformance test、旧call site 0 |
| C01-D5 | vizによる`server.py` source scraping | canonical manifest index | P3 | dashboard contract test、全package manifest移行 |
| C01-D6 | directory存在だけでproduction Skillを暗黙登録する経路 | approved manifest / lock | P4 | clean install、explicit local-dev opt-in、run lock test |
| C01-D7 | runtime registrationに使う旧`mcp.json`/`skill.yaml` reader | migration-only reader | P6 | deprecation期間、repo caller 0、旧checkpoint fixtureは別readerでgreen |

削除は各行の replacement と test を同じ変更系列に含める。旧 reader は support window 中、runtime import path から隔離した migration module として保持してよい。

### 7.2 削除の検証と復旧

各 deletion PR は `pytest ari-core/tests -q`、manifest conformance、golden checkpoint replay、対象symbol/configへの `rg` が全てgreenであることを記録する。削除直前commitをrollback基点として明示し、公開契約と旧checkpoint readerはsupport window中revertまたはmigration-only moduleで復旧可能にする。

### 7.3 計画書自身の削除

本書は C01-01〜10、受け入れ基準、C01-D1〜D7 の判定が完了し、恒久仕様が `docs/reference/skills.md`、`docs/reference/public_api.md`、`docs/reference/internal_boundaries.md`、schema docへ移された後、マスター計画の最終cleanup PRで削除する。未完了削除はissueへ移すまで本書を削除しない。
