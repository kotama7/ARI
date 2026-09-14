# 06 — Configuration Studio and Launch Experience

> Status: planned  
> Dependencies: 01, 02, 03, 05  
> Gate: G4 — Vertical slices

## Purpose

現在の Settings と Wizard を、schema-driven Configuration Studio と durable run draft へ統合する。設定項目が増えても component-local state、手組み payload、重複 model catalog を増やさず、安全に「選ぶ・理解する・検証する・起動する・再現する」体験を提供する。

## Scope

- personal preferences、installation/secrets、project defaults、run templates、run drafts。
- Basic/Advanced/Expert disclosure、検索、filter、provenance、diff、raw editor。
- new run、clone、resume、validation、launch review、idempotent launch。
- schema-generated controls と explicit custom editor extension point。
- model/provider catalog、secret readiness、resource/cost impact。
- unsaved changes、draft autosave、revision conflict、recovery。

## Non-goals

- active run の immutable algorithm config を書き換えない。
- arbitrary JSON schema から無条件に使いやすい UI が生成されるとは仮定しない。
- secret 値の readback、browser persistence、manifest 埋込を行わない。
- Settings と Wizard を一度に削除しない。

## Workspace structure

### Personal

- Language、theme、density、reduced motion、Developer Mode、default landing page。
- browser-local であり run reproducibility には含めない。

### Connections and secrets

- provider、base URL、model availability、Semantic Scholar、Letta、SSH credential。
- secret は masked value ではなく configured/not configured と source を表示する。
- test connection は explicit action、rate limit、redacted result を持つ。

### Infrastructure defaults

- local/HPC/cloud execution environment、partition、CPU、memory、walltime。
- container、SSH、scheduler capability、availability warning。
- execution environment と governance mode を別用語・別 control にする。

### Run template and algorithms

- workflow/pipeline、BFTS、evaluation、retrieval/memory、VLM。
- RQGM exploration、paper archive、adversarial、evolution、budget、evaluation。
- mode interlock、new-run-only、resume behavior を field の隣に表示する。

### Effective configuration

- effective value、source、scope、applies when、mutability、validation warning。
- template vs draft、draft vs effective、current run vs clone の diff。
- raw YAML/JSON は Expert + permission で表示し、semantic form と双方向検証する。

### Diagnostics and danger

- schema/version mismatch、unknown field、deprecated alias、secret readiness、resolver trace。
- restart、delete、force action は Operations と連携し、通常設定と分離する。

## Interaction model

- 左 rail: category と validation/error count。
- top bar: scope、template、profile、search、Basic/Advanced/Expert。
- main form: dependency-aware sections と field provenance。
- right inspector: description、source stack、impact、raw path、docs link。
- bottom review: unsaved diff、validation、cost/resource、launch eligibility。

field は hidden にし過ぎず、search で常に発見可能にする。利用不能な field は消すのではなく capability/policy reason を示す。

## Schema-driven rendering

- primitive field は metadata から標準 control を生成する。
- domain-specific field は `field path/pattern → custom editor` registry で上書きする。
- form value は typed nested object とし、数値を string/env へ早期変換しない。
- dependency graph は enable/disable、required、conflict、derived preview を共通化する。
- frontend model/provider constants を廃止し server catalog を使う。
- unknown plugin field は raw extension section で lossless に保持する。

## Run draft state machine

現行 Wizard は 4 step（Goal / Scope / Resources / Launch。`StepGoal`〜`StepLaunch`）で、これを次の durable state machine へ拡張する。`governance` step は新設であり、現行 v1 の「RQGM に GUI toggle なし」決定（`docs/guides/execution_modes.md`）を supersede する ADR を伴う。PaperBench の 5-step wizard は別 flow のまま維持し、この state machine に統合しない。

```text
goal
→ scope
→ workflow
→ models_and_resources
→ governance
→ review
→ validating
→ ready
→ launching
→ launched | failed
```

- step navigation は前提 validation を通らない限り先へ進めない。
- draft は server-side revision document として保存し、non-secret field を refresh 後に復元する。
- browser unload、network failure、revision conflict を明示する。
- generated config response は canonical DTO 一つに統一し、silent discard を contract test で防ぐ。
- API key field は secret endpoint にのみ接続し、入力したのに launch へ効かない dead control を禁止する。

## Validation and review

launch 前に以下を一画面で確認する。

- project、run display name、unique run ID intent。
- workflow revision と enabled/disabled phase。
- execution environment、resource request、scheduler/container readiness。
- provider/model mapping と phase-specific override。
- execution mode（`ari.mode`）、paper mode（`paper.mode`）、RQGM interlock。
- effective config digest、changed fields、ignored/rejected override。
- secret readiness。値は表示しない。
- estimated cost/time は estimate と明記し、assumption/source を表示する。
- reproducibility warning と non-deterministic external dependency。

## Launch protocol

1. `resolve-config` で effective config と digest を得る。
2. `validate` で schema、capability、secret、resource、mode を検証する。
3. user が immutable review を承認する。
4. idempotency key 付き run create を送る。
5. backend が返した `run_id` と status URL を await する。
6. mtime/latest checkpoint polling を使わず canonical run overview へ遷移する。
7. launch failure は partial mutation、retryability、cleanup status を表示する。

accepted response 前の scheduler probe/LLM slug generation を bounded preparation または background lifecycle へ移し、double-click で subprocess を複製しない。

## Resume and clone

- Resume は checkpoint snapshot を base にし、resume-mutable field だけを編集する。
- immutable field への変更希望は「clone as new run」へ誘導する。
- Clone は old snapshot を current schema に migrate し、changed default/deprecated/unavailable capability を diff 表示する。
- execution/paper mode、RQGM policy history は resume で変更できない（`reconcile_resume_mode` が persisted mode を強制、downgrade-only）。
- reconstructed legacy snapshot は confidence warning と source file を示す。

## Migration sequence

1. current Settings/Wizard contract と known defect を fixture 化する。少なくとも: 24-key POST / 27-key GET の非対称、GET の shallow merge、POST が settings.json を **whole-file replace** し 24 key 以外を消す挙動、enum 非通過値の logged-drop（`_ALLOWED_FRONTIER/_COMPOSITE/_AXIS_MODE`）、api key の「20 文字以上かつ provider ∈ {openai,anthropic,gemini}」heuristic（ollama/cli-shim key は silent drop、`letta_api_key` は平文で settings.json に残る）、dead key（`temperature`/`container_pull` は保存されるが launch で読まれない。Settings の SLURM 値は launch へ直接届かず Wizard 初期値としてのみ効く）、`retrieval:` block が core で未消費（両側 decorative）、launch 応答の `_status` embedding、PaperBench F6a drift。
2. Configuration Studio shell に legacy Settings panel を mount する。
3. schema reader、search、provenance を read-only で導入する。
4. Personal/Secrets を scope 分離する。
5. Project defaults と templates を versioned PATCH へ移す。
6. Wizard を durable draft/state machine へ置換する。
7. new launch protocol と canonical run redirect を導入する。
8. shadow serialization で legacy 24-key/env mapping と差分監視する。
9. cutover 後に card-count/DOM-shape 固定 test と duplicate constants を削除する。

## Testing

- schema field coverage と generated/custom editor mapping test。
- GET → edit → validate → save → reload の value retention test。
- 0/null/empty、range、enum、dependency、unknown field、deprecated alias test。
- unsaved changes、refresh restore、revision conflict、offline/retry test。
- Wizard back/forward、direct-step guard、generate/upload、launch success/failure test。
- double click/idempotency、parallel run、canonical redirect test。
- secret input/redaction/readiness/no-browser-storage test。
- keyboard、screen reader、3 locale、mobile/desktop test。

## Completion criteria

- 全 config field が検索可能で、source/scope/applies-when を説明できる。
- Settings と Wizard が同じ schema/resolver/catalog を使う。
- durable draft と guarded state machine が refresh/concurrency に耐える。
- launch は backend の `run_id` を用い、latest-checkpoint 推測を行わない。
- active/resumed run の immutable setting を UI と backend の両方で変更できない。
- legacy 24-key adapter と shadow diff が migration gate を通る。

## Deletion criteria

- configuration/launch guide と schema extension guide を恒久文書へ移し、旧 Settings/Wizard state/payload mapping が削除済みである。

## Delete-after checklist

- [ ] configuration/launch user guide を三言語で更新した。
- [ ] custom field editor contract を developer docs へ移した。
- [ ] duplicate provider/model/default constants を削除した。
- [ ] legacy Settings/Wizard usage が removal threshold を満たした。
- [ ] main merge と CI green を確認した。
- [ ] `INDEX.md` を更新した。

