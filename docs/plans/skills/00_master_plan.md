---
sources:
  - path: ari-core/ari/mcp/client.py
    role: implementation
  - path: ari-core/ari/mcp/child_environment.py
    role: implementation
  - path: ari-core/ari/call_context.py
    role: implementation
  - path: ari-skill-memory/src/server.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: docs/concepts/architecture.md
    role: doc
  - path: docs/reference/internal_boundaries.md
    role: doc
last_verified: 2026-08-02
---

# ARI Skill Platform マスター実装計画

| 項目 | 値 |
|---|---|
| 状態 | In progress — P5 provider pilots complete; component cleanup and P6 remain |
| 基準ブランチ | `skills` |
| 基準コミット | `4cd56f9` |
| 作成日 | 2026-08-01 |
| 対象 | `ari-core`、全 `ari-skill-*`、新規 federation component、ToolUniverse / OpenROAD / Qiskit pilot |

> **この文書と配下のサブ計画書は一時的な実装管理資料である。**
> 実装成果、移行記録、恒久仕様へ知識を移した後は、[削除要件](#11-削除要件)に従って計画書群そのものを削除する。

### 実装進捗（2026-08-02）

- 全14既存Skillを `SkillManifestV1` へ移行し、旧 `mcp.json` を生成物へ変更。
- package/runtime AST/workflow/version/compatibility metadata/collision のconformance gateを追加。
- `ari-core` のdiscovery、entrypoint、timeout classをmanifestへ接続し、bare-name後勝ちをregistration errorへ変更。
- runtime input/output schemaまで束縛したimmutable `tool_ref` dispatchと、一意bare aliasの互換経路を追加。
- `ResultEnvelopeV1`、typed error/provenance、4,000文字超raw responseのcontent-addressed artifact化を追加。
- run-level `SKILLS.lock`、provider/schema digest、phase別active set、atomic create/verify、provider fail-closedを追加。
- 全14 Skillをcomplete環境allowlistとnamed credential scopeへ移行し、実MCP process/Claude direct-MCP proxyでsecret non-propagationとredactionを固定。
- explicit `RunContextV1` / `NodeContextV1`、tool-bound署名 capability、
  direct-MCP proxy injectionを追加し、memoryのself-write / ancestor-readをcall単位で認可。
- process-global current-node環境変数、private set-node tool、CoW tool名listを削除し、
  4 parallel nodeの実process testでcross-branch isolationを固定。
- tool名別timeout tableを削除し、manifest-declared bounded budgetと
  capability-based async submit/status/result/cancel handleを追加。SLURMと外部ARI runを
  同じportable handleへ移行。
- viz source scraping、暗黙directory discovery、legacy runtime admissionを削除し、
  read-only migration readerとgolden checkpoint contractへ置換。C01-01〜10と
  C01-D1〜D7を完了。C08-D1/D2/D3も完了済み。
- 15番目のdefault-off `ari-skill-tool-registry` を追加し、LLM surfaceを5操作へ固定。
  generic stdio MCP、canonical `tool_ref`、4段階admission、reviewed `CATALOG.lock`、
  graph quarantine、overlap説明、async、artifact、credential-free record/replay、
  1 source/1,000-tool importを実装。C02-01〜10とC02-D1〜D6を完了。
- ToolUniverse v1.3.1を一つのcompact collection adapterとして統合し、公式
  wheel/source/license/dependency/3,542-file treeをpinした。category profile、
  active-lock leaf制限、schema dialect正規化/quarantine、cache/coercion無効化、
  schema-change別承認、direct MCP混在、record/offline replayを実装。
  1,000-leaf fixture、公式UniProt 17 leaf、実live responseでC17-01〜08と
  C17-D1〜D6を完了。
- 公式OpenROAD-MCP v0.6.1とORFS 26Q3をpinし、任意interactive shellを公開しない
  immutable experiment leaf、closed Tcl profile、private workspace、QoR context、
  exact golden/replay evidence、async session cleanup、artifact再検証、offline replayを
  実装。公式provider contract smokeとparallel/cancel/negative fixtureを通過した。
  固定Tcl/worker/inputをC06 typed jobへpinするSLURM + clean SIF経路、handle/
  cancel/log/provenance/EAR統合、terminal-only cleanupを追加しC18-01〜08/D1〜D6を完了。
- C06 scheduler coreを`JobRequestV1/JobHandleV1/JobStatusV1/JobResultV1`へ移行し、
  durable idempotency claim、shell-free local argv+stdin、strict known-host SSH、
  `--export=NIL` clean environment、module/container/input/output/log provenanceを実装。
  非実装`run_bash`宣言、親env/`.env`再注入、AutoAddPolicy、Singularity内部重複を削除し、
  no-SLURM/A64FX/GPU/remote/shared-FS/timeout fixturesを通過。公開Python packageへ
  移し、manifest entrypointから品質gateが追跡するようにした。
- C05を`WorkspaceRefV1`、`ExecutionRequestV1/ResultV1`、`MeasurementSetV1`へ移行した。
  dirfd/O_NOFOLLOW/atomic write、minimal non-secret env、POSIX resource/process-group
  cleanup、要求と実施を分離したnetwork provenance、完全log artifact、stable retry
  identity、strict measurement parserを実装した。coding/transform/evaluatorを共通契約へ
  移し、同一requestのlocal/container/SLURM handoffをdigest付きで固定した。
  C05-01〜08とD1/D2/D3/D5を完了し、D4 flat compatibility removalだけをP6へ残した。
- paper-reの直接`sbatch --wait`、`--export ALL`、GRES silent drop、任意flag連結、
  spool wrapperを削除し、digest付きrequest→handle→status/log/cancelへ移行した。
  rubric schemaもtyped account/QoS/reservationと矛盾resource拒否へ更新し、157件の
  paper-re suiteと54件のHPC suiteを通過。C06-07はOpenROAD consumerを含め完了。
- 公式Qiskit MCP server 0.3.1、IBM Runtime MCP server 0.6.1、Qiskit 2.5.1、
  Aer 0.17.2、IBM Runtime 0.48.0をpinし、完全package tree/distribution/tool contractを
  検証した。QPY、parameter unit、transpiler/target/shots/seed/noise/mitigation、backend
  snapshot/calibrationをclosed profileへ固定し、local ideal/noisy、remote simulator、
  IBM hardwareを別capabilityにした。typed async、token scope/redaction、raw artifact、
  Bell/GHZ scientific fixture、official transpile/Aer run、offline replayを実装し、
  C19-01〜08/D1〜D6を完了。P5 provider gateを閉じた。
- C04 Webをprovider-neutral `RetrievalRecordV1`へ移行し、固定provider、
  content-addressed cassette/snapshot、artifact-verified offline replay、DOI/arXiv/S2
  alias lineageを実装した。pinned-IP SSRF/redirect/size/type policy、bounded citation
  graph、明示LLM rerankerを追加し、implicit fallback/composite partial successを削除。
  default paper workflowとIdea/Paper consumerをverified snapshot refへ移行し、
  C04-01〜08/D1/D2/D3/D5/D6を完了した（D4 alias removalはP6）。

## 1. 決定

ARI の Skill 群を、個別の MCP server を都度追加する集合から、次の性質を持つ一つの **科学実験用 Skill Platform** へ移行する。

1. `ari-core` は実験実行、Skill lifecycle、run snapshot、policy enforcement を所有する。
2. 各 Skill は一つの明確な科学・運用能力を所有し、共通 manifest、結果 envelope、provenance 契約に従う。
3. 大規模・外部 MCP 群は、個別 tool ではなく `CatalogSource` または provider adapter 単位で追加する。
4. 発見された tool と実験で実行可能な tool を分離し、実行時は immutable lock に固定する。
5. 同機能 tool の競合は bare name の上書きで解決せず、能力、意味、由来、独立性を明示して選択する。
6. 通信可能性、再現可能性、科学的妥当性を別々の admission level として扱う。
7. 新実装を追加するだけで終わらせず、置換済みの重複実装、暗黙 fallback、互換 shim、古い契約を計画的に削除する。

## 2. 目的

- 全 Skill の登録、起動、schema、権限、結果、artifact、エラーを共通契約にする。
- Tool 数が数千規模になっても、LLM に直接公開する tool surface と context 使用量を一定に保つ。
- BFTS、post-BFTS、reproduce の各 phase で、許可された能力だけを再現可能な snapshot として提供する。
- ToolUniverse や将来の MCP 集合を、一 collection 一 adapter 以下で統合できるようにする。
- OpenROAD と Qiskit を、stateful、長時間実行、artifact、domain provenance の pilot として扱う。
- claim、measurement、unit、source、method、environment、tool version を EAR まで追跡する。
- 既存 checkpoint と公開 API を、明示的な移行期間を設けずに破壊しない。

## 3. 非目標

- ARI を一般公開 MCP marketplace にすること。
- MCP conformance や provider の知名度を科学的正当性の証明とみなすこと。
- ToolUniverse、OpenROAD、Qiskit の内部 workflow engine を ARI の agent loop と置き換えること。
- 初期段階から任意 shell launcher、任意 remote HTTP、OAuth、破壊的 tool を無制限に許可すること。
- 全 Skill を一つの Python process または一つの巨大 broker implementation に統合すること。

## 4. 現状と解消すべき構造的ギャップ

2026-08-01 時点の実装監査では、次の横断課題がある。

| ID | 現状 | 必要な変更 |
|---|---|---|
| G-01 | `mcp.json`、`skill.yaml`、実際の `tools/list`、`workflow.yaml` の tool 名と version が一致しない package がある | 一つの canonical manifest と CI conformance check |
| G-02 | `ari-core` の tool registry は bare tool name を key にするため、同名 tool が衝突し得る | immutable `tool_ref` と明示的な collision error |
| G-03 | Skill subprocess に親の `os.environ` をほぼそのまま渡す | 最小環境、credential scope、permission 宣言 |
| G-04 | timeout が tool 名の hard-coded set で決まる | manifest の execution class / declared budget |
| G-05 | JSON text、独自 dict、path 文字列が混在する | versioned `ResultEnvelope` と content-addressed artifact |
| G-06 | deterministic tool、LLM tool、live API tool の区別が description に留まる | machine-readable determinism / side-effect / admission metadata |
| G-07 | phase 開始時の tool set と実行根拠を immutable artifact として残さない | run-level `SKILLS.lock` / `CATALOG.lock` |
| G-08 | sandbox、SLURM、container、LaTeX/claim parsing に重複実装がある | owner component へ集約し、parity test 後に重複を削除 |
| G-09 | `ari-skill-orchestrator` と `ari-skill-plot` は package-level test gap がある | 最低限の MCP contract / security / failure-path test |
| G-10 | provider fallback が record/replay の意味を変え得る | live / record / replay mode を明示し、record 中の暗黙 provider 変更を禁止 |

## 5. 目標アーキテクチャ

```text
experiment.md / workflow.yaml
             |
      ari-core control plane
      - canonical manifest loader
      - phase policy + run snapshot
      - namespaced dispatch
      - ResultEnvelope / artifact store
      - minimal child environment
             |
       +-----+-------------------------------+
       |                                     |
 built-in ari-skill-*                ari-skill-tool-registry
 (idea, coding, hpc, ...)             discover / describe / invoke
       |                               get_status / get_result
       |                                     |
       |                      locked provider adapters / catalogs
       |                        |          |          |
       +------------------ ToolUniverse  OpenROAD   Qiskit / future
             |
      claim + provenance + EAR
             |
       isolated reproduction
```

`ari-skill-tool-registry` は大量の外部能力を束ねるが、既存 Skill の責務を吸収しない。例えば scheduler lifecycle は `ari-skill-hpc`、claim gate は `ari-skill-evaluator` / `ari-core`、paper generation は `ari-skill-paper` が引き続き owner である。

## 6. 共通契約

### 6.1 Canonical Skill Manifest

各 Skill は versioned manifest を一つだけ source of truth とし、最低限次を宣言する。

```yaml
schema_version: 1
name: coding-skill
package: ari-skill-coding
version: 0.2.0
entrypoint: {transport: stdio, command_kind: python, module: src/server.py}
tools:
  - name: run_code
    capability_ref: ari.execution.code
    phases: [bfts, reproduce]
    side_effects: stateful
    determinism: conditional
    timeout_class: bounded
    permissions: [workspace-write, process]
    result_schema: ari.result-envelope/v1
```

- `mcp.json` が必要な consumer には canonical manifest から生成する。
- CI は manifest、`tools/list`、workflow reference、package version の差分を fail させる。
- 未宣言 tool、schema の縮退、version 不整合は warning ではなく admission failure とする。

### 6.2 Tool identity と競合

- 実行 identity は `provider/tool@digest` 形式の opaque `tool_ref` とする。
- 類似能力は別軸の `capability_ref` で表し、name collision と semantic overlap を混同しない。
- 同一 leaf implementation は alias として collapse できるが、同じ backend の別 wrapper を独立証拠として数えない。
- `invoke` 時に bare name を再解決しない。選択済み `tool_ref` を実行する。

### 6.3 Result と artifact

全 component は次の共通 envelope へ正規化する。

```yaml
schema_version: ari.result-envelope/v1
status: ok | error | submitted | running | cancelled
structured_content: {}
artifacts: [{digest, media_type, size, logical_role}]
error: {kind, message, retryable} | null
provenance:
  tool_ref: <immutable ref>
  run_id: <run>
  node_id: <node or null>
  started_at: <timestamp>
  completed_at: <timestamp or null>
```

大きな stdout、schema、image、PDF、EDA report、quantum result は inline text に詰めず artifact store へ置く。raw upstream response も digest 付き artifact として保持する。

### 6.4 Scientific Admission

| Level | 実行可否 | 意味 |
|---|---|---|
| `discovered` | 不可 | metadata を取得しただけ |
| `callable` | 条件付き | protocol、sandbox、dependency、smoke test を通過 |
| `reproducible` | 可 | code、schema、data、environment、cassette を固定可能 |
| `scientifically_admitted` | 可 | domain validation、単位、限界、比較可能範囲まで確認 |

Admission は tool popularity や collection の trust を推移的に継承しない。実験ごとに必要 level を policy で指定する。

### 6.5 Security と実行 mode

- `live`: 外部状態を使用できるが、取得時刻、backend、credential scope identity を記録する。
- `record`: strict validation を使い、raw result と依存 identity を cassette / EAR に固定する。
- `replay`: network と credential なしで lock と cassette だけを使用し、欠落時は fail closed とする。
- secret は lock、log、error、artifact、digest input に含めない。
- destructive / stateful tool は read-only tool より強い policy と明示的承認を要求する。

### 6.6 互換性

- 公開 tool の削除・schema 破壊は release policy に従い、deprecated alias と migration note を先に提供する。
- checkpoint reader は最低でも現在サポート対象の既存形式を migration fixture で検証する。
- 内部重複実装は parity fixture があれば同一 PR で置換・削除できる。
- security 上危険な fallback は、明示的 error と移行手順を同時提供する場合、通常の猶予を短縮できる。

## 7. Component 計画

### 現行 component

| ID | Component | 所有責務 | サブ計画 |
|---|---|---|---|
| C01 | `ari-core` | lifecycle、policy、dispatch、snapshot、public contract | [01_ari_core.md](01_ari_core.md) |
| C03 | `ari-skill-idea` | 仮説、研究契約、idea provenance | [03_idea.md](03_idea.md) |
| C04 | `ari-skill-web` | literature retrieval と source provenance | [04_web.md](04_web.md) |
| C05 | `ari-skill-coding` | workspace 内 code / process execution | [05_coding.md](05_coding.md) |
| C06 | `ari-skill-hpc` | scheduler、remote execution、container jobs | [06_hpc.md](06_hpc.md) |
| C07 | `ari-skill-benchmark` | deterministic statistics と比較 | [07_benchmark.md](07_benchmark.md) |
| C08 | `ari-skill-memory` | lineage-scoped research memory | [08_memory.md](08_memory.md) |
| C09 | `ari-skill-evaluator` | metric contract、hard gate、semantic review | [09_evaluator.md](09_evaluator.md) |
| C10 | `ari-skill-transform` | canonical science data、claim / EAR materialization | [10_transform.md](10_transform.md) |
| C11 | `ari-skill-plot` | scientific figure generation | [11_plot.md](11_plot.md) |
| C12 | `ari-skill-vlm` | multimodal figure / table review | [12_vlm.md](12_vlm.md) |
| C13 | `ari-skill-paper` | evidence-grounded paper generation / review | [13_paper.md](13_paper.md) |
| C14 | `ari-skill-replicate` | reproducibility rubric generation / audit | [14_replicate.md](14_replicate.md) |
| C15 | `ari-skill-paper-re` | isolated reproduction と grading | [15_paper_re.md](15_paper_re.md) |
| C16 | `ari-skill-orchestrator` | ARI run の外部非同期 control | [16_orchestrator.md](16_orchestrator.md) |

### 新規 federation / domain component

| ID | Component | 所有責務 | サブ計画 |
|---|---|---|---|
| C02 | `ari-skill-tool-registry` | provider-neutral federation と5-tool surface | [02_tool_registry.md](02_tool_registry.md) |
| C17 | ToolUniverse adapter | compact collection import / dispatch | [17_tooluniverse.md](17_tooluniverse.md) |
| C18 | OpenROAD profile | stateful EDA admission / artifacts | [18_openroad.md](18_openroad.md) |
| C19 | Qiskit profile | simulator / hardware job admission / provenance | [19_qiskit.md](19_qiskit.md) |

## 8. 実装フェーズと gate

| Phase | 主な成果 | Exit gate |
|---|---|---|
| P0: Baseline | manifest schema、tool inventory、dependency graph、deletion ledger、golden checkpoint | 現行 tool / workflow / artifact が machine-readable inventory で再現される |
| P1: Contract | 全既存 Skill の manifest、ResultEnvelope adapter、contract tests | 15 package の manifest と実 `tools/list` が一致し、collision が fail する |
| P2: Core safety | minimal env、namespaced dispatch、run lock、timeout metadata、explicit node context | secret leak test、parallel node test、旧 checkpoint fixture が green |
| P3: Ownership cleanup | execution、scheduler、claim formula、plotting等の owner 集約 | 各置換に parity evidence があり、削除 ledger の内部重複を除去 |
| P4: Federation | `ari-skill-tool-registry` A.0/A.1、catalog lock、admission、cassette | 1 source 宣言で1,000 tool fixture、record/replay、cycle rejection |
| P5: Providers | ToolUniverse、OpenROAD、Qiskit pilot | 3 provider が同一 discovery contract、domain provenance、artifact replayを満たす |
| P6: Migration / removal | deprecated alias / fallback の移行、恒久 docs、不要依存・shim削除 | 全 deletion gate、全CI、release note、rollback tag、計画書削除可否レビュー |

P0 と P1 は全 component に横断する。P2 以降は dependency を満たす component を並行実装できるが、P6 の削除を先行させない。

## 9. PR と変更単位

- 一つの PR は、一つの contract または一つの component milestone に限定する。
- behavior change と deletion は、parity evidence が同じ PR にある場合を除き分ける。
- PR 本文には requirement ID、影響する manifest/schema、migration、削除対象、rollback を記載する。
- generated lock / schema の差分は review 可能な deterministic output とする。
- 外部 provider update を runtime 起動時に自動採用しない。専用 sync PR で lock 差分を審査する。

## 10. 全体受け入れ基準

- [x] 全 component に canonical manifest と owner が一つだけある。
- [x] manifest、runtime `tools/list`、workflow、docs、package version の conformance CI が通る。
- [x] 同名 tool は黙って上書きされず、完全重複以外は別 identity として保持される。
- [x] run 開始後に active tool set、schema、provider digest が変わらない。
- [x] ResultEnvelope、artifact digest、tool selection reason、admission evidence が EAR に残る。
- [x] record した fixture が network、credential、MCP server なしの replay で成功する。
- [x] parallel BFTS で node context と memory write が交差しない。
- [x] 最小 child environment に含めない secret が Skill processへ渡らない。
- [x] 1,000 tool mock collection を一つの source 定義で追加できる。
- [x] ToolUniverse、direct MCP、OpenROAD、Qiskit の能力が同じ discovery contract から選択できる。
- [x] deterministic / stochastic / live-data の再現性主張が区別される。
- [ ] 各サブ計画の component-specific test と deletion gate が通る。
- [ ] `pytest`、docs link、manifest/schema、security、replay の全CIが green である。

## 11. 削除要件

### 11.1 全計画に必須の削除 ledger

各サブ計画は、実装作業だけでなく次を必ず列挙する。

| 項目 | 必須内容 |
|---|---|
| 削除対象 | file、symbol、tool、config key、dependency、fallback、生成物のいずれかまで特定 |
| 置換先 | 新しい owner / contract / migration path |
| 最早削除 phase | replacement より前に削除しないための順序 |
| 削除gate | internal caller 0、fixture parity、deprecation、replay等の客観条件 |
| 検証 | test command または CI check |
| 復旧 | revert 可能な commit/tag、旧 artifact reader、feature flag の期限 |

「不要なら削除」「将来削除」のように判定不能な記述は禁止する。削除しないと決めた対象も、理由と再評価時点を記録する。

### 11.2 削除の分類

1. **同一 PR で削除可能**: dead code、未使用 private helper、parity test 済み内部重複、generated file の旧 source。
2. **移行後に削除**: 公開 tool alias、checkpoint field、environment variable、backend、外部 consumer があり得る API。
3. **即時停止を優先**: secret leakage、fail-open admission、unrestricted path / command、結果を捏造し得る silent fallback。互換より安全を優先し、明示 error と migration note を同時に出す。
4. **保持**: replay に必要な reader、schema、cassette。support window 終了までは runtime path から隔離して保持する。

### 11.3 実装削除の共通 gate

- replacement が既定経路になっている。
- repo 内 caller、workflow reference、manifest reference が 0 である。
- public surface は deprecation policy と release note を満たす。
- golden checkpoint、record/replay、component test が replacement で成功する。
- dependency 削除後に clean environment install と license inventory が成功する。
- rollback に必要な最後の互換 commit/tag と migration note がある。

### 11.4 計画書自身の削除

以下をすべて満たした最終 cleanup PR で、`docs/plans/skills/` 全体を削除する。

1. P0〜P6 と全サブ計画の受け入れ基準が完了している。
2. 全 deletion ledger が `deleted`、`retained with rationale`、`deferred to <issue>` のいずれかで閉じている。
3. 残すべき architecture、manifest、migration、運用手順が `docs/concepts`、`docs/reference`、`docs/guides`、`CONTRIBUTING.md`、schema内へ移されている。
4. 未完了作業を計画書の削除で消さず、追跡可能な issue / ADR に移している。
5. cleanup PR で docs link check と `rg 'docs/plans/skills'` による dangling reference check が通る。

削除コマンドは対象を明示して実行する。

```bash
git rm -r docs/plans/skills
```

## 12. リスク

| リスク | 緩和策 |
|---|---|
| 共通化が巨大 rewrite になる | manifest、envelope、env、registryを別PRにし、既存Skill adapterから移行 |
| 科学 admission が形式審査だけになる | domain profile、golden data、limitations、independenceを別 field と testで要求 |
| ToolUniverse依存が基盤へ漏れる | compact adapterの内部に閉じ、public APIをprovider-neutralに固定 |
| 類似 tool が誤って統合される | equivalenceの証拠がない場合は別 capabilityを既定とする |
| cleanupでreplay不能になる | old reader/cassetteはsupport windowまでruntimeから隔離して保持 |
| planが恒久仕様の代わりになる | 各 phase の完了条件に恒久文書への転記と計画書削除を含める |
