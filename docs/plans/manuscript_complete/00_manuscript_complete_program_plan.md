# Task 00: Manuscript Complete Program Plan

> **Status**: planned
> **Internal dependencies**: none
> **External integration dependencies**: ARI-RQGM Tasks 18/19 for KCA-bound
> publication; ARI-RQGM-paper Task 07 for the existing final claim-gate handoff
> **Planning boundary**: this plan is owned only by
> `docs/plans/manuscript_complete/`; it is not a new ARI-RQGM or paper-archive
> task. See [INDEX.md](INDEX.md).

## 1. Purpose

探索の終了と論文執筆の開始の間に、決定論的で digest-bound な Manuscript Complete
境界を設ける。目的は「writer に大量の raw context を渡す」ことではない。原稿に必要な
研究情報を要件として列挙し、各要件を証拠へ結び、不足・不適用・取得不能・除外を区別し、
必要なら制約付き研究修復を実行した後でのみ執筆と publication lock を許可することである。

この計画は次の問いに実装可能な答えを与える。

1. 探索で得た全成果のうち、何が論文へ渡されたか。
2. 渡されなかった情報は、無関係、容量制限、破損、失敗、未認証のどれか。
3. 原稿要件に対して本当に足りない情報は何か。
4. 不足は既存 artifact の再投影、文献取得、追加実験、KCA certification、人手判断の
   どれで解消すべきか。
5. `simple_bfts | ari_rqgm` と `linear | rqgm_archive` の全組合せで同じ completeness
   contract を使用できるか。
6. claim gate、KCA certification、compile/reproduction gate を混同せずに publication
   を止められるか。

## 2. Ownership boundary

### 2.1 This plan owns

- Manuscript requirement profile と applicability 規則。
- exploration artifact から manuscript context への決定論的 projection。
- positive、exploratory、negative、excluded evidence の分類。
- omission manifest と context budget の規則。
- manuscript readiness の状態、gate、blocking semantics。
- research repair request、repair budget、resume/idempotence。
- section-specific authoring brief。
- manuscript input と paper build の digest binding。
- readiness、claim、KCA、reproduction を独立に保持する publication decision。
- research mode × paper mode × manuscript mode の activation matrix。

### 2.2 This plan does not own

- BFTS または RQGM の探索アルゴリズム、utility、frontier score。
- Knowledge catalog、Provider catalog、Harness catalog の admission/promotion。
- RQGM constitutional roles、governance transition、paper archive search の内部実装。
- ScienceData の「実行された測定事実」という既存意味。
- claim-evidence hard gate の既存判定式。
- venue template、rubric、reviewer score の内容。
- GUI refresh の情報設計。

外部機能との接続には adapter を置く。この計画の契約を外部計画へコピーせず、外部計画の
契約もこの計画内で再定義しない。

## 3. Current-state findings

### 3.1 Current handoff

現在の主経路は次の一方向 artifact handoff である。

```text
BFTS / RQGM
  -> nodes_tree.json, node reports, memory
  -> node_provenance_audit.json
  -> science_data.json / verified_context.json
  -> EAR / figures / related_refs.json
  -> writer
  -> claim links / review / refine / final gate
  -> paper build / reproduction lock
```

`ari-core/ari/cli/run.py` は `_run_loop` の終了後に
`ari.cli.paper_dispatch.run_paper_phase` を呼ぶ。`run_paper_phase` は paper mode を解決し、
`linear` では `ari.core.generate_paper_section`、`rqgm_archive` では
`ari.rqgm.paper_runtime.PaperArchiveRuntime` を実行する。

`ari.core.generate_paper_section` は `ari-core/config/workflow.yaml` の post-BFTS pipeline
全体を一回で実行する。現行 stage driver の loop-back は paper stage 間の反復用であり、
Agent/BFTS runtime を再構築して追加探索を実行する transaction boundary ではない。

### 3.2 Existing paper evidence preparation

workflow の主要順序は次である。

1. `search_related_work`
2. `audit_node_provenance`
3. `transform_data`
4. `generate_ear` / `ear_curate`
5. `generate_figures` / `vlm_review_figures`
6. `write_paper`
7. claim linking、draft gate、review、refine、final gate、finalize、reproduction

`audit_node_provenance` は明示的に signal-only であり gate ではない。したがって hash
mismatch または missing artifact が見つかっても、manuscript の positive evidence から
自動除外される保証はない。

### 3.3 Current context loss

現行 writer 入力には、少なくとも次の有界 projection がある。

- configuration は先頭 10 件。
- candidate claim は先頭 20 件。
- verified-context claim は既定最大 20 件。
- reference rendering は先頭 12 件、検索自体は既定最大 15 件。
- source payload は約 32,000 bytes、transform 側の selected source は 16,384 bytes。
- experiment summary は writer prompt で 48,000 characters に切られる。

上限自体は必要だが、現在は全 inventory と omitted item の対応が paper authoring contract
に存在しない。特に、failed/null/inconclusive node、off-lineage sibling、棄却仮説、選択理由、
KCA assurance、provenance failure が原稿へ届かない、または positive result と同じ context
で扱われる可能性がある。

### 3.4 Selection and assurance seam

`ari-core/ari/orchestrator/node_selection.py` の既存 criteria は
`for_synthesis | for_code | for_narrative` である。`for_narrative` は原則 success のみを
含み、失敗ノードを研究経緯から落とす。source loader は size budget 超過 item を返却値から
省くが、型付き omission record を必須にはしない。

RQGM node には `assurance_status`、`frontier_class`、attestation binding が付与されるが、
既存 paper candidate selection と ScienceData の fact eligibility は publication
certification と同じ判定ではない。これは ScienceData の欠陥ではない。実測事実と
publication admissibility は別契約として維持すべきである。

### 3.5 Current reverse feedback

`run_paper_candidate_preflight` は RQGM exploration runtime が存在する場合に paper artifact
を読み、candidate penalty/re-ranking を行える。ただし初回 preflight 時点では paper
artifact が未生成のため、post-pipeline 側で得た signal は既に書かれた当該 paper を
再生成せず、主として次回 invocation へ影響する。

Manuscript Complete の repair loop はこの非同期 penalty と区別する。current-run の不足は
writer 実行前に型付き repair request として扱う。

## 4. Goals

- 原稿に必要な requirement を versioned profile として固定する。
- 全 requirement を `satisfied | not_applicable | unavailable | missing` のいずれかにする。
- requirement status を LLM の自由記述ではなく、固定 evaluator と証拠参照で決める。
- 全探索ノードと主要 artifact の inventory を持ち、authoring payload の省略を説明する。
- failed/null/inconclusive result を positive claim から分離しつつ narrative-visible にする。
- readiness failure を typed repair action に変換する。
- repair が権限、budget、tool binding、KCA posture を拡張しないようにする。
- linear と RQGM archive が同一 context/readiness digest を読む。
- publication lock を readiness、claim、KCA、reproduction の独立 gate で守る。
- legacy default の実行、import、artifact、paper bytes を変えない。

## 5. Non-goals

- あらゆる研究分野・venue の要件を v1 で完全自動判定しない。
- raw nodes tree、全 source file、全論文を一つの LLM prompt へ詰め込まない。
- LLM summary を claim-eligible fact に昇格しない。
- paper reviewer の低スコアを、それだけで追加実験要求に変換しない。
- RQGM archive candidate が research evidence、readiness policy、KCA verdict を変更しない。
- `ari paper` から暗黙に実験、network access、catalog promotionを開始しない。
- assurance failure を claim wording の弱化だけで pass にしない。
- `simple_bfts` を RQGM dependency に変えない。
- この計画のために既存 plan index または task numbering を変更しない。

## 6. Normative terminology

| Term | Meaning |
|---|---|
| requirement | 原稿に必要な情報・証拠・開示・publication条件 |
| profile | requirement 集合、適用条件、severity、resolver を固定した versioned policy |
| source snapshot | 一回の compile が参照する探索・文献・EAR・図表・assurance artifact の digest集合 |
| manuscript context | source snapshot を要件別に投影した決定論的文書 |
| readiness | requirement ごとの status と blocking verdict |
| section brief | 一つの原稿セクションに必要な bounded authoring input |
| repair request | 一つの不足を解消する権限制約付き作業要求 |
| authoring-ready | authoring-blocking requirement に unresolved `missing` がない状態 |
| publication-ready | publication-blocking requirement と全独立 gate が pass した状態 |
| evidence lane | manuscript 内での証拠利用可能性分類 |
| omission | inventory にはあるが、特定の projection/payload へ含めなかった item |

「complete」は「全世界の情報が揃った」ことではない。選択された profile の全 requirement
について、状態、理由、証拠、修復可能性が説明できることを意味する。

## 7. Global invariants

### MC-I1 — deterministic fact / stochastic annotation separation

source inventory、digest、measurement、status、applicability、evidence lane、gate verdict は
固定コードで生成する。LLM が作る summary、novelty prose、section draft は annotation であり、
それだけでは claim-eligible にならない。

### MC-I2 — no silent omission

budget、missing file、parse failure、policy exclusion、duplicate、stale により payload へ入らない
item は、stable ID と reason を omission manifest に持つ。全 inventory 件数と
included + omitted 件数が一致しなければ context build は失敗する。

### MC-I3 — negative results remain visible

failed、null、inconclusive、abandoned、反証結果は positive evidence にはならないが、研究経緯、
limitations、selection rationale の入力から消してはならない。

### MC-I4 — gates remain independent

readiness、claim-evidence、KCA certification、compile/reproduction は別 verdict と別 reason を
保持する。加重和、平均、review score で hard failure を相殺しない。

### MC-I5 — authoring cannot rewrite readiness

linear writer、paper reviewer、RQGM archive の prompt/output は requirement status、evidence lane、
applicability、omission reason、certification verdict を変更できない。

### MC-I6 — repair cannot expand authority

repair は元 run の Knowledge lock、Capability binding、Harness catalog、tool allowlist、resource
policy、data access policy を継承する。repair request は新しい権限を付与しない。

### MC-I7 — digest-bound handoff

profile、source snapshot、context、readiness、brief bundle、paper build、publication decision は
親 artifact digest を固定する。親が変われば下流は stale になる。

### MC-I8 — topology neutrality

同じ source facts から作る context/readiness は `paper.mode` に依存しない。paper archive を
有効化しても requirement profile または evidence classification は変わらない。

### MC-I9 — identity default

`manuscript.mode: off` は現在の code path をそのまま使用し、`.ari-manuscript/` を作成せず、
manuscript package を lazy path より前に import せず、既存 artifact bytes を変更しない。

### MC-I10 — fail closed at publication

audit/authoring は適切な disclosure 付きで継続可能でも、publication-critical requirement、
current-target certification、final claim gate、reproduction lock のいずれかが失敗した paper は
locked/finalized publication にならない。

## 8. Execution axes and activation rules

### 8.1 Axes

```yaml
ari:
  mode: simple_bfts        # simple_bfts | ari_rqgm

paper:
  mode: linear             # linear | rqgm_archive

manuscript:
  mode: off                # off | audit | enforce
  profile: generic_empirical_v1
  repair:
    policy: disabled       # disabled | explicit | auto

knowledge:
  mode: off                # off | audit | enforce

capability_binding:
  mode: legacy             # legacy | audit | enforce

assurance:
  mode: off                # off | audit | enforce
```

### 8.2 Activation table

| Manuscript mode | Build artifacts | Stop authoring on missing | Stop publication | Legacy identity |
|---|---:|---:|---:|---:|
| `off` | no | no | existing gates only | required |
| `audit` | yes | no | existing gates only; report shadow decision | not byte-identical by opt-in |
| `enforce` | yes | yes for authoring-blocking | yes for publication-blocking | not applicable |

### 8.3 Invalid or constrained combinations

- `repair.policy=auto` with `manuscript.mode=off` is a config error.
- `repair.policy=explicit|auto` with `manuscript.mode=audit` may generate a plan but does not execute
  it unless an explicit repair command is issued.
- `ari paper` never receives a research executor; `auto` is downgraded to a structured
  `repair_required` result, not silently executed.
- `assurance.mode=enforce` without a current certification provider is not converted to pass。
  authoring may continue only if profile marks assurance as publication-only; publication blocks.
- `paper.mode=rqgm_archive` does not require `ari.mode=ari_rqgm`。
- `ari.mode=ari_rqgm` does not enable `paper.mode=rqgm_archive`。

Activation resolution is covered by cheap exhaustive tests over all enum combinations. E2E tests
use the representative topology matrix in §18.

## 9. Target architecture

```text
Research execution
  ├── simple BFTS adapter
  └── ARI-RQGM adapter
             │
             ▼
ExplorationSnapshot (internal, immutable view)
             │
             ▼
Evidence preparation
  ├── provenance audit
  ├── ScienceData
  ├── recorded retrieval
  ├── EAR
  ├── figures
  └── KCA attestations when present
             │
             ▼
ManuscriptCompiler (fixed code)
  ├── RequirementProfileV1
  ├── ManuscriptContextV1
  ├── ReadinessReportV1
  ├── OmissionManifestV1
  └── SectionBriefBundleV1
             │
       ready │ missing
             │     └── ResearchRepairPlanV1
             │              └── bounded coordinator -> research execution
             ▼
PaperBackend
  ├── LinearPaperBackend
  └── RqgmArchivePaperBackend
             │
             ▼
PublicationEvaluator (fixed code)
  ├── readiness verdict
  ├── final claim gate
  ├── current KCA certification
  └── build/reproduction verdict
             │
             ▼
PublicationDecisionV1 -> lock or block
```

## 10. Contracts and artifacts

All normative JSON uses canonical serialization, strict unknown-field rejection, SHA-256 digests,
safe relative artifact paths, explicit schema version, run ID, and parent digest validation.
Timestamps may be metadata but are excluded from normative decision digests unless source contracts
already require them。

### 10.1 `ManuscriptRequirementProfileV1`

Schema ID: `ari.manuscript-requirement-profile/v1`。

Required fields:

- `profile_id`, `profile_version`, `profile_digest`。
- `paper_family`: initially `generic_empirical`。
- `requirements[]`:
  - `requirement_id`。
  - `section_targets[]`。
  - `description`。
  - `applicability_rule_id`。
  - `authoring_blocking`。
  - `publication_blocking`。
  - `allowed_terminal_statuses`。
  - `resolver_kinds[]`。
  - `evidence_kinds[]`。
- `policy_version` and fixed evaluator compatibility range。

Profile is fixed input。writer/reviewer cannot edit it。venue-specific profile extends by explicit
composition and records every parent profile digest; it does not mutate the generic profile。

### 10.2 `ExplorationSnapshotV1` — internal boundary

This is an internal typed view, not necessarily a public API in v1。

- research contract and goal。
- all node IDs, parent links, statuses, metrics, artifact refs。
- node report refs and provenance findings。
- scientific best ID and selection policy digest。
- optional RQGM epoch/frontier/assurance refs。
- source artifact inventory。
- checkpoint/run identity。

There are two providers:

- `SimpleBftsSnapshotProvider`。
- `RqgmSnapshotProvider`。

Both emit the same semantic fields。RQGM-only fields remain optional typed blocks, not loose extras。

### 10.3 `ManuscriptContextV1`

Schema ID: `ari.manuscript-context/v1`。

Digest bindings:

- requirement profile。
- research contract。
- nodes tree / node report inventory。
- provenance audit。
- ScienceData deterministic digest。
- retrieval records。
- EAR manifest / published lock when present。
- figure batch。
- assurance/catalog/attestation snapshot when present。
- omission manifest。

Content blocks:

1. `research_question` — question、hypothesis、falsification conditions。
2. `contribution_map` — proposed contribution and evidence obligations。
3. `method_inventory` — implementation、configuration、environment、protocol。
4. `subject_set` — scientific winner、publication candidate、comparators、contextual nodes。
5. `evidence_matrix` — claims/measurements/configurations/artifacts/figures。
6. `exploration_history` — chosen/rejected branches and reasons。
7. `negative_results` — failed/null/inconclusive/contradictory outcomes。
8. `related_work` — recorded references, queries, novelty comparison inputs。
9. `limitations_and_threats`。
10. `reproducibility` — EAR、commands、environment、source locks。
11. `assurance` — screen/certify/current target/staleness。
12. `omissions` — every omitted item and reason。

Any LLM-generated explanation lives under `annotations[]` with
`claim_eligible=false`, model call provenance, prompt digest, and source refs。

### 10.4 `ManuscriptReadinessReportV1`

Schema ID: `ari.manuscript-readiness/v1`。

Each requirement result contains:

- `requirement_id`。
- `applicable: true|false` and fixed applicability trace。
- `status: satisfied|not_applicable|unavailable|missing`。
- `evidence_refs[]`。
- `reason_code` and bounded human-readable explanation。
- `authoring_blocking`, `publication_blocking` copied from profile。
- `resolver_kind` when repairable。
- `repair_request_id` when emitted。
- `evaluator_version` and policy digest。

Aggregate verdicts:

- `authoring_verdict: ready|ready_with_disclosures|repair_required|blocked`。
- `publication_verdict: ready|blocked`。
- counts by status and severity。
- exact context/profile digests。

`not_applicable` is allowed only when the fixed applicability rule returns false or an admitted
research contract field explicitly supplies the required decision。writer prose is not admissible。

### 10.5 `OmissionManifestV1`

Every item contains:

- stable item ID and kind。
- source artifact/path/node ID。
- digest and size when available。
- intended projection/section。
- reason enum:
  - `budget_exceeded`
  - `not_relevant_by_profile`
  - `duplicate`
  - `missing_on_disk`
  - `digest_mismatch`
  - `parse_failure`
  - `stale`
  - `policy_excluded`
  - `unsafe_path`
- whether omission creates a readiness failure。

The manifest records both context-level omissions and section-brief omissions。A budget omission
must not automatically mean evidence is absent; the item remains addressable by digest/ref。

### 10.6 `ResearchRepairPlanV1`

Schema ID: `ari.research-repair-plan/v1`。

Each request contains:

- stable `request_id = digest(requirement_id, target_claims, source_context_digest, action)`。
- `kind`:
  - `artifact_recovery`
  - `projection_rebuild`
  - `literature_search`
  - `baseline_comparison`
  - `repetition_or_uncertainty`
  - `ablation`
  - `validation_experiment`
  - `assurance_certification`
  - `method_clarification`
  - `limitation_disclosure`
  - `human_decision`
- target requirement/claim/configuration/node IDs。
- fixed variables and allowed changes。
- required capability/harness semantic IDs。
- max new nodes、experiment runs、LLM calls、resource units。
- preconditions、success conditions、stop conditions。
- executor owner and `pending|running|satisfied|failed|exhausted|cancelled` state。

Plan generation does not execute requests。Execution is an explicit coordinator operation。

### 10.7 `SectionBriefBundleV1`

Schema ID: `ari.section-brief-bundle/v1`。

The bundle contains one brief per profile section。Each brief binds:

- context and readiness digests。
- allowed evidence/claim/reference IDs。
- negative/contextual evidence IDs。
- required disclosures。
- forbidden positive-evidence IDs。
- token/character budget。
- included item list and omission manifest slice。
- renderer version and deterministic ordering。

The paper model receives briefs, not arbitrary raw nodes。Raw artifact access, when needed, is by
safe relative reference through an explicit reader with the same inclusion/omission accounting。

### 10.8 `ManuscriptAuthoringBindingV1`

This companion contract avoids changing legacy `PaperBuildV1` bytes in `manuscript.mode=off`。
It binds:

- profile、context、readiness、brief bundle digests。
- target paper build ID/revision。
- paper mode and backend version。
- source snapshot digest。

`PaperArtifactRole` gains additive roles for manuscript artifacts, but the existing four required
roles remain unchanged for legacy builds。Under `audit|enforce`, a fixed validator requires the
additional roles。No unconditional field is added to legacy serialized builds。

### 10.9 `PublicationDecisionV1`

Schema ID: `ari.publication-decision/v1`。

It binds the final paper build digest and records independent sub-verdicts:

- manuscript publication readiness。
- final claim-evidence gate。
- KCA certification for the exact publication subject/target digest when required。
- compile/build status。
- reproduction/code-bundle lock status。
- stale-input check。

Top-level `decision` is `publishable|blocked` and is the logical AND of applicable hard gates。
No scalar score is accepted。The lock manifest binds this decision digest; the decision does not
participate in a circular parent digest with the build it evaluates。

## 11. Evidence lanes and subject selection

### 11.1 Lanes

| Lane | Conditions | Allowed paper use |
|---|---|---|
| `publishable` | typed completed measurement; provenance acceptable; current non-stale certification when required | result and headline claim |
| `exploratory` | measured or screened but uncertified/incomplete | caveated hypothesis, future work, exploratory discussion |
| `contextual_negative` | failure, null, inconclusive, abandoned, contradiction | negative result, limitation, method history |
| `excluded` | tampered, missing, stale, target mismatch, inadmissible | audit/omission reason only |

Evidence lane is separate from ScienceData `claim_eligible`。A measurement may be a valid executed
fact but not publishable under assurance enforcement。

### 11.2 Subject set

Context records at least:

- `scientific_winner` — existing scientific selection result。
- `publication_candidate` — highest admissible subject under fixed publication policy。
- `comparators[]`。
- `contextual_nodes[]`。
- `excluded_nodes[]`。

If scientific winner and publication candidate differ, the decision and reason are mandatory。
Fallback to a certified runner-up is allowed only when:

1. profile permits fallback。
2. contribution identity remains the same。
3. comparison obligations remain satisfied。
4. the substitution is visible in context and paper limitations。

Otherwise readiness emits certification/validation repair instead of silently changing the paper
subject。

### 11.3 Compatibility rule

Do not change current `filter_nodes(..., for_synthesis|for_code|for_narrative)` semantics in place
for the legacy path。Add a manuscript-specific classifier/selector or criteria entry used only under
`manuscript.mode != off`。This avoids changing ScienceData/EAR/EVOLUTION bytes for default runs。

## 12. Requirement profile v1

The first profile is `generic_empirical_v1`。

| ID | Requirement | Applicability | Authoring block | Publication block | Primary resolver |
|---|---|---|---:|---:|---|
| `MC-RQ-001` | research question and objective | always | yes | yes | method clarification / human decision |
| `MC-RQ-002` | hypothesis and falsification condition | hypothesis-testing paper | yes | yes | research contract repair |
| `MC-ME-001` | method/algorithm description | always | yes | yes | artifact recovery / clarification |
| `MC-ME-002` | configuration and environment | empirical execution | yes | yes | artifact recovery |
| `MC-ME-003` | protocol, dataset/workload, stopping rule | empirical execution | yes | yes | artifact recovery / validation run |
| `MC-RS-001` | primary metric, direction, unit, run IDs | result claim exists | yes | yes | projection / measurement |
| `MC-RS-002` | repetition and uncertainty | stochastic or aggregate claim | yes | yes | repetition experiment |
| `MC-CP-001` | baseline/comparator | superiority/comparative claim | yes | yes | baseline experiment |
| `MC-CP-002` | comparison protocol equivalence | comparator exists | yes | yes | validation experiment |
| `MC-AB-001` | ablation | component-causal or multi-part contribution claim | yes | yes | ablation experiment |
| `MC-CL-001` | claim-to-measurement coverage | result claim exists | yes | yes | projection rebuild |
| `MC-CL-002` | numeric assertions reproducible | numeric result exists | yes | yes | projection / correction |
| `MC-NG-001` | failed/null/inconclusive accounting | always | no | yes when omission changes conclusion | projection rebuild / disclosure |
| `MC-SL-001` | selection rationale and off-lineage accounting | more than one evaluated candidate | no | yes when winner selection unsupported | projection rebuild |
| `MC-RW-001` | recorded related-work snapshot | always unless profile exemption | yes | yes | literature search |
| `MC-RW-002` | novelty distinction | novelty claim exists | yes | yes | literature analysis / human decision |
| `MC-LM-001` | limitations | always | yes | yes | disclosure |
| `MC-LM-002` | validity threats | empirical execution | no | yes | disclosure |
| `MC-RP-001` | EAR/source/environment inventory | empirical execution | yes | yes | artifact recovery |
| `MC-RP-002` | reproduction commands and locks | reproducibility claimed | yes | yes | artifact recovery / reproduction |
| `MC-AS-001` | publication certification | assurance enforce | no | yes | assurance certification |
| `MC-OM-001` | complete omission manifest | manuscript enabled | yes | yes | projection rebuild |

Applicability rules inspect typed research contract、claim categories、configuration counts、metric
records、profile metadata。They do not inspect draft prose unless the prose claim has already been
parsed into a typed candidate-claim record and independently linked to evidence。

## 13. Context budgeting

### 13.1 Two-level representation

`ManuscriptContextV1` stores a complete structured inventory and bounded summaries。Large source
bytes remain external but digest-addressable。`SectionBriefBundleV1` selects the relevant subset for
each authoring call。

### 13.2 Deterministic selection order

Within a section:

1. profile-required facts。
2. publication candidate direct evidence。
3. comparator evidence。
4. contradiction/negative evidence needed for disclosure。
5. method/reproduction details。
6. related work by fixed retrieval rank and recorded relevance category。
7. optional exploratory context。

Tie-breaking uses stable IDs, not filesystem mtime or model score unless that score is an explicit
bound input field。

### 13.3 Budget behavior

- Required item that cannot fit causes brief build failure or a split brief; it is not silently
  omitted。
- Optional item may be omitted with `budget_exceeded` and stable reference。
- The writer sees included and omitted counts。
- A section may use multiple sequential briefs, but every model call records the exact brief digest。
- Context budget changes create a new renderer/profile digest and invalidate downstream briefs。

### 13.4 Replacement of current caps

The current 10/20/12/48k caps remain untouched in the off path。In manuscript mode they are replaced
by section-specific budgets and omission accounting。The old ad-hoc assembly is deleted only after
all manuscript-enabled backends consume briefs and compatibility tests prove the off path unchanged。

## 14. Workflow integration

### 14.1 Required segmentation

The current post-BFTS workflow must be executable in three segments without duplicating stage
definitions:

1. `evidence`
   - related-work retrieval。
   - provenance audit。
   - ScienceData transform。
   - EAR generation/curation。
   - figures and VLM review。
2. `authoring`
   - linear writer or RQGM archive winner materialization。
3. `verification`
   - claim links、hard gates、reviews/refinement as applicable、compile、finalize、reproduction。

Additive workflow metadata may name the segment。The default `generate_paper_section` invocation
continues to run all stages in current file order。A segmented runner records completed segment input
digests and treats cross-segment dependencies as satisfied only when their outputs exist and match。

### 14.2 Fixed coordinator boundary

Manuscript compilation/readiness is not an ordinary MCP/LLM pipeline stage。It runs in fixed core
code between `evidence` and `authoring` so pipeline exception swallowing or score loop-back cannot
bypass the gate。

```text
_run_loop
  -> run evidence segment
  -> ManuscriptCoordinator.compile_and_assess
       -> ready: run selected PaperBackend + verification segment
       -> repair_required: persist plan and return/repair
       -> blocked: persist exact reasons and stop
```

### 14.3 CLI entry behavior

- `ari run` and `ari resume` possess a research executor and may execute allowed explicit/auto
  repairs。
- `ari paper` possesses only existing checkpoint evidence。It may rebuild projection, retrieval if
  already authorized by command/config, or certification if explicitly requested, but it never
  starts research experiments implicitly。
- `run_paper_phase` receives a ready `ManuscriptAuthoringBindingV1`/bundle in manuscript mode。
  It does not rediscover or mutate completeness inputs。
- Legacy calls without a bundle continue current dispatch unchanged。

### 14.4 Failure posture

- `audit`: compiler failure is recorded and legacy authoring continues; failure is visible。
- `enforce`: compiler/readiness failure blocks authoring, not merely finalize。
- verification failure blocks publication but preserves draft and diagnostics。
- artifact corruption never falls back from enforce to a weaker manuscript or assurance posture。

## 15. Repair routing and execution

### 15.1 Resolver classes

| Gap class | Examples | Executor |
|---|---|---|
| projection | fact exists but was not included; failed nodes omitted | ManuscriptCompiler |
| artifact recovery | source/config/EAR exists but is unreadable or unindexed | deterministic recovery |
| literature | missing related work or novelty comparison source | recorded retrieval |
| experiment | baseline, repetition, uncertainty, ablation, validation | BFTS/RQGM research executor |
| assurance | absent/stale/mismatched certification | fixed Harness/certifier |
| disclosure | limitation or negative result needs explicit accounting | brief/compiler, then authoring |
| human | contribution identity or policy choice cannot be inferred | stop with exact question |

### 15.2 Research repair transaction

For experiment repair:

1. Verify request digest and source context is current。
2. Resolve required capability/harness against the run-frozen locks。
3. Reserve request budget from run-level repair budget。
4. Materialize targeted pending nodes carrying `repair_request_id` and `requirement_id`。
5. Execute through the normal research loop; do not call experiment tools directly from paper code。
6. Persist result/failed/exhausted state。
7. Re-run evidence segment only for invalidated outputs。
8. Build a new context/readiness attempt。
9. Mark request satisfied only when the fixed success predicate passes。

### 15.3 Budget

Initial configuration:

```yaml
manuscript:
  repair:
    policy: disabled
    max_rounds: 2
    max_new_nodes: 8
    max_experiment_runs: 12
    max_llm_calls: 8
    on_exhaustion: block
```

Normative termination uses rounds/nodes/runs/calls, not wall-clock time。Operational timeout may
stop a process but does not decide scientific satisfaction。Unused budget from one request is not
silently transferred to a request requiring broader authority。

### 15.4 Idempotence and deduplication

- Same current context + same requirement + same action produces the same request ID。
- A completed request is never re-executed on resume。
- A failed request can be retried only under an explicit new attempt/retry policy, retaining parent
  request digest。
- Equivalent baseline/ablation requests are deduplicated by semantic target and fixed variables。
- New evidence invalidates readiness and may close several requests simultaneously, but closure is
  recomputed rather than asserted by the executor。

## 16. RQGM, paper archive, and KCA composition

### 16.1 Responsibility layers

```text
Layer 0 — fixed truth and policy
  research contract, ScienceData, provenance, KCA locks/attestations

Layer 1 — fixed manuscript projection
  context, readiness, omission manifest, repair plan, section briefs

Layer 2 — stochastic authoring search
  linear writer or RQGM paper archive

Layer 3 — fixed publication verification
  claim gate, certification, build/reproduction, lock
```

Layer 2 cannot write Layers 0/1/3。Research RQGM may add new Layer 0 execution artifacts only through
a repair transaction, after which Layer 1 is rebuilt from scratch against new digests。

### 16.2 Four topology rollout

| Order | Research | Paper | Purpose |
|---:|---|---|---|
| 1 | `simple_bfts` | `linear` | reference context/readiness behavior |
| 2 | `ari_rqgm` | `linear` | RQGM frontier/KCA adapter isolation |
| 3 | `simple_bfts` | `rqgm_archive` | paper archive consumer isolation |
| 4 | `ari_rqgm` | `rqgm_archive` | complete composition |

This order changes one axis at a time。The full topology is not enabled until the first three cells
meet their own acceptance gates。

### 16.3 Research RQGM adapter

`RqgmSnapshotProvider` reads, without recomputing:

- epoch/run identity and frozen policy refs。
- frontier class and erasure/stale state。
- `assurance_status`。
- screen/certify attestation refs and target digests。
- governance/adversarial exclusions that affect evidence admissibility。
- scientific best and current publication candidate inputs。

Typed repair requests become constrained proposal seeds。RQGM may choose an execution path within
the request's allowed change set, but cannot change requirement severity、success predicate、budget、
tool binding、Harness selection policy。Every repair-generated node records the request lineage。

### 16.4 Paper RQGM archive adapter

All archive candidates receive the same context/readiness/brief digests。Archive scoring may include:

- required-item coverage。
- claim-evidence coverage。
- citation suitability。
- limitation disclosure completeness。
- readability/rubric score。
- unsupported-claim count。

Hard violations are disqualifiers, not negative score terms。Archive winner materialization is
followed by the same fixed verification segment as linear authoring。

Paper archive review cannot trigger nested BFTS execution。If a candidate exposes a genuine evidence
gap, it emits a typed diagnostic; the current archive run ends blocked or returns to the outer
ManuscriptCoordinator in a subsequent bounded repair round。This prevents research search and paper
search from recursively owning each other。

### 16.5 Existing paper-candidate preflight

Under `manuscript.mode=off`, current `run_paper_candidate_preflight` behavior remains unchanged。
Under manuscript mode:

- readiness runs before authoring and owns current-run evidence gaps。
- preflight penalty remains an exploration governance signal, not a readiness verdict。
- equivalent signals carry a digest and are applied once; post-pipeline signal must not duplicate a
  repair already emitted by readiness。
- no untyped penalty is interpreted as proof that a requirement was satisfied。

### 16.6 Knowledge and Capability

- Knowledge entries may supply terminology、method context、related-work candidates and provenance,
  but do not prove experimental results。
- Capability binding controls what repair executor may call。`enforce` uses only admitted bound
  tools; `audit` records proposed substitutions; `legacy` preserves current behavior。
- A repair plan names semantic capability needs, not provider-specific tool names chosen by an LLM。
- Missing capability becomes `unavailable` or `human_decision`; it never causes automatic authority
  expansion。

### 16.7 Assurance and publication

Assurance screen may classify a node for exploration。Publication requires certify when
`assurance.mode=enforce`。The publication evaluator invokes the existing fixed integrity check with
publication intent and exact target binding, after Tasks 18/19 expose a production-ready provider。

Certification must bind at least:

- publication subject node/configuration。
- selected source/code digest set。
- ScienceData deterministic digest or the exact covered measurement set。
- Harness identity/version/runner digest。
- environment/data locks required by the Harness contract。
- attestation revision and non-stale catalog lock。

Absence, stale attestation, target mismatch, failed required check, or unpromoted Harness blocks
publication。It does not erase the executed fact; the fact moves to exploratory/contextual use as
defined by profile。

## 17. Persistence, state, and resume

### 17.1 Artifact namespace

All new runtime artifacts live under an isolated namespace:

```text
{checkpoint}/.ari-manuscript/
  state.json
  transitions.jsonl
  attempts/
    mca-<source_digest_prefix>/
      source_snapshot.json
      requirement_profile.json
      context.json
      omission_manifest.json
      readiness.json
      repair_plan.json             # when needed
      section_briefs.json          # when authoring-ready
      authoring_binding.json       # when authoring starts
      publication_decision.json    # after verification
```

No new file is written when mode is off。

### 17.2 Attempt identity

`attempt_id` is derived from the complete source snapshot/profile/evaluator version digest, with
collision detection against the full digest。Re-running against identical input reuses and verifies
the existing attempt。Changed evidence creates a new immutable attempt; prior attempts remain for
audit。

### 17.3 State machine

```text
absent
  -> source_bound
  -> compiled
  -> assessed
       -> ready
       -> ready_with_disclosures
       -> repair_pending
       -> blocked_unavailable
  -> repairing -> source_bound(new attempt)
  -> authoring
  -> authored
  -> publication_blocked | finalized
```

Transitions are append-only and hash chained。`state.json` is a rebuildable latest-state projection。
Illegal transitions fail closed。

### 17.4 Staleness propagation

| Changed input | Invalidates |
|---|---|
| nodes/reports/ScienceData | context onward |
| provenance audit | lane classification onward |
| references | related-work context/readiness/briefs onward |
| EAR/source lock | reproducibility readiness onward |
| figures | result briefs and paper build onward |
| profile/evaluator version | readiness/context projection onward |
| attestation/catalog lock | assurance readiness/publication decision |
| paper draft/build | claim/compile/reproduction/publication decision |

Old artifacts are marked stale by relationship, not physically deleted。

### 17.5 Legacy checkpoint migration

- No in-place checkpoint schema migration is required for `off`。
- `audit|enforce` lazily builds an attempt from artifacts that exist。
- Missing historical data becomes typed `unavailable`/`missing`; it is never reconstructed as a
  successful measurement without source evidence。
- Legacy `verified_context.json` may be used as a source reference but not as a complete all-node
  inventory。
- Resume honors the persisted manuscript mode/profile for an in-progress authoring attempt; a mode
  change starts a new attempt and cannot rewrite old records。

## 18. CLI and API surface

### 18.1 CLI

Proposed commands:

```text
ari manuscript status <checkpoint>
ari manuscript inspect <checkpoint> [--requirement ID] [--section NAME]
ari manuscript plan-repair <checkpoint>
ari manuscript repair <checkpoint> [--request ID]
ari manuscript certify <checkpoint> [--request ID]
ari manuscript explain-publication <checkpoint>
```

Mutating commands clearly distinguish projection rebuild, external retrieval, experiment execution,
and certification。`status`/`inspect`/`explain-publication` are read-only。

Exit/result categories:

- `ready`
- `ready_with_disclosures`
- `repair_required`
- `blocked_unavailable`
- `publication_blocked`
- `invalid_or_stale`

Machine-readable JSON output contains artifact paths and digests。

### 18.2 Core/API

Keep public contracts behind `ari.public.manuscript` after schema stabilization。Before public export,
use internal modules and contract snapshot tests。If public export is added:

- update `ari.public` module inventory/docstring。
- add stable import tests。
- add schema fixtures and snapshot update review。
- do not expose mutable coordinator internals as public API。

### 18.3 GUI integration boundary

GUI work is a downstream consumer, not part of initial completion。It may display:

- requirement status matrix。
- evidence lane and omission reasons。
- repair requests/budgets。
- attempt lineage and staleness。
- independent publication gates。

GUI must call the same read model/API and cannot implement its own readiness calculation。

## 19. Implementation work packages

### WP0 — Baseline and decision freeze ([Task 01](01_baseline_and_decision_freeze.md))

Deliverables:

- small, large, failed/null, RQGM-assured, legacy checkpoint fixtures。
- golden default `simple_bfts + linear` paper artifacts/import trace。
- current context-loss inventory for 10/20/12/48k caps。
- ADRs for contract namespace、attempt identity、workflow segmentation、PaperBuild binding。

Gate G0:

- baseline fixtures reproduce current behavior。
- no normative open decision blocks contract implementation。

### WP1 — Contracts and deterministic compiler core ([Task 02](02_contracts_and_compiler_core.md))

Deliverables:

- `ari/manuscript/contracts.py` or focused contract modules。
- JSON schemas and canonical digest helpers。
- generic empirical profile。
- source snapshot providers for existing simple BFTS artifacts。
- context、omission、readiness builders。

Gate G1:

- same inputs produce byte-identical normative artifacts。
- tamper/stale/unknown fields fail validation。
- inventory conservation and no-silent-omission property passes。

### WP2 — Audit-only simple BFTS + linear vertical slice ([Task 03](03_audit_vertical_slice.md))

Deliverables:

- `.ari-manuscript` attempt persistence。
- workflow evidence boundary observation without changing writer path。
- status/inspect CLI。
- audit report comparing existing writer payload against full manuscript inventory。

Gate G2:

- existing paper output remains unchanged in audit mode except new isolated audit artifacts。
- off mode remains byte/import/artifact identical。
- known failed/null/off-lineage fixture appears in correct lanes。

### WP3 — Segmented pipeline and enforce gate ([Task 04](04_segmented_pipeline_and_enforce_gate.md))

Deliverables:

- evidence/authoring/verification segment execution。
- fixed ManuscriptCoordinator between evidence and authoring。
- section brief bundle and linear backend adapter。
- authoring binding and stale checks。

Gate G3:

- authoring never starts with authoring-blocking `missing` under enforce。
- ready inputs run existing verification tail。
- segment resume is idempotent and dependency-safe。

### WP4 — Research RQGM and KCA adapter ([Task 05](05_rqgm_kca_integration.md))

Deliverables:

- `RqgmSnapshotProvider`。
- assurance/frontier/erasure classification。
- publication subject and certification binding。
- shadow and enforce publication decisions。

External dependency:

- certify/publication production closure depends on ARI-RQGM Tasks 18/19。Audit classification can
  land earlier。

Gate G4:

- high-score debug/failed/stale node cannot become publishable evidence。
- target mismatch and missing certification block publication in enforce。
- no RQGM import occurs on legacy off/simple path。

### WP5 — Paper RQGM archive adapter ([Task 06](06_paper_archive_integration.md))

Deliverables:

- shared ManuscriptBundle input for archive candidates。
- coverage/unsupported-claim diagnostics。
- hard-gate disqualification separate from candidate utility。
- winner materialization followed by common verification segment。

Gate G5:

- all candidates bind identical context/readiness/profile digests。
- archive cannot change readiness or evidence lanes。
- archive failure posture is explicit; enforce never silently falls back to an unbound linear build。

### WP6 — Explicit repair ([Task 07](07_explicit_repair_and_resume.md))

Deliverables:

- repair plan compiler。
- projection/artifact/literature/assurance resolver adapters。
- research repair executor through normal run/resume loop。
- request lineage、budget ledger、deduplication。

Gate G6:

- every executed repair is authorized and bounded。
- satisfied state is decided by re-evaluation, not executor assertion。
- interruption/resume neither duplicates nor loses work。

### WP7 — Auto repair and complete topology ([Task 08](08_auto_repair_and_full_topology.md))

Deliverables:

- outer bounded coordinator loop。
- all four research×paper topologies。
- current-run typed feedback without duplicate legacy preflight penalty。
- exhaustion and human-decision UX/API。

Gate G7:

- loop always terminates within configured bounds。
- full `ari_rqgm + rqgm_archive` keeps Layer 0/1/2/3 authority separation。
- auto repair never activates from `ari paper` or manuscript off/audit unexpectedly。

### WP8 — Publication lock, evaluation, migration, docs ([Task 09](09_publication_evaluation_migration_docs.md))

Deliverables:

- final PublicationDecision binding and lock integration。
- evaluation metrics and failure injections。
- legacy checkpoint guide、operator runbook、schema/reference docs。
- optional GUI read model/API after core stabilizes。

Gate G8:

- completion criteria in §25 pass in local and remote CI environments applicable to each Harness。
- permanent documentation owns all normative post-plan decisions。

## 20. Expected code touchpoints

### 20.1 New core modules

Proposed isolated package:

```text
ari-core/ari/manuscript/
  __init__.py
  contracts.py
  profiles.py
  snapshot.py
  inventory.py
  selection.py
  builder.py
  readiness.py
  omissions.py
  briefs.py
  repair.py
  coordinator.py
  publication.py
  state.py
```

Modules may be split further, but dependency direction is fixed:

```text
contracts <- inventory/builder/readiness/briefs
contracts <- repair
contracts <- publication
builder/readiness/repair/publication <- coordinator
coordinator must not be imported by contracts
paper/RQGM adapters depend on manuscript public/internal facade, not reverse
```

### 20.2 Existing core files likely modified

- `ari-core/ari/config/__init__.py` — typed manuscript config。
- `ari-core/ari/configs/defaults.yaml` — identity-default off/disabled values。
- `ari-core/config/workflow.yaml` — additive segment metadata and authoring bindings。
- `ari-core/ari/cli/run.py` — coordinator boundary after research loop。
- `ari-core/ari/cli/paper_dispatch.py` — bound bundle/backend dispatch。
- `ari-core/ari/core.py` — legacy wrapper plus segmented manuscript path。
- `ari-core/ari/pipeline/` — segment execution/state support。
- `ari-core/ari/paper_contract.py` — additive artifact roles/validators without legacy byte change。
- `ari-core/ari/rqgm/paper_runtime.py` — archive backend adapter。
- `ari-core/ari/rqgm/assurance_bridge.py` — read-only adapter surface if missing fields need export。
- `ari-core/ari/public/__init__.py` and new `ari/public/manuscript.py` only after public freeze。

### 20.3 Skills likely modified

- `ari-skill-paper/src/authoring.py` — section brief/binding input。
- `ari-skill-paper/src/server.py` — manuscript-enabled writer path; legacy assembly retained for off。
- `ari-skill-paper/src/finalize.py` — binding and publication decision validation。
- `ari-skill-transform/src/server.py` — only if a non-legacy inventory export is needed; do not alter
  ScienceData fact semantics。

### 20.4 Schemas and fixtures

- `ari-core/ari/schemas/manuscript_*.schema.json`。
- contract fixtures and snapshots under existing test conventions。
- representative checkpoint fixtures with explicit provenance and assurance states。

## 21. Test strategy

### 21.1 Unit and contract tests

- strict schema validation and unknown-field rejection。
- canonical digest determinism。
- parent digest/tamper mismatch rejection。
- applicability rule table coverage。
- legal/illegal readiness transitions。
- `not_applicable` provenance requirements。
- inventory conservation: total = included + omitted。
- omission reason completeness。
- lane classification for success/fail/null/stale/tampered/uncertified/certified。
- section brief deterministic selection and required-item non-omission。
- repair ID stability、deduplication、budget arithmetic。
- publication logical-AND behavior and independent reasons。

### 21.2 Compatibility tests

- `manuscript.mode=off` creates no new file。
- off path does not import `ari.manuscript` or `ari.rqgm` unexpectedly。
- default `simple_bfts + linear` command sequence and paper artifacts are golden-identical。
- existing config without `manuscript` block resolves to off/disabled。
- legacy checkpoint opens without migration。
- current paper mode persistence/resume remains authoritative on off path。

### 21.3 Topology matrix

Minimum E2E cells:

| Research | Paper | Manuscript | Repair | Assurance |
|---|---|---|---|---|
| simple | linear | off | disabled | off |
| simple | linear | audit | disabled | off |
| simple | linear | enforce | disabled | off |
| RQGM | linear | audit | disabled | audit |
| RQGM | linear | enforce | explicit | enforce |
| simple | archive | audit | disabled | off |
| simple | archive | enforce | explicit | off |
| RQGM | archive | enforce | disabled | enforce |
| RQGM | archive | enforce | auto | enforce |

Enum activation resolver tests are exhaustive; expensive E2E tests use this boundary-focused set。

### 21.4 Repair tests

- baseline request creates only comparator nodes with fixed dataset/metric/environment。
- repetition request preserves configuration and changes only allowed seed/repetition fields。
- ablation request removes/changes exactly declared components。
- validation request cannot broaden tool allowlist。
- unavailable capability/harness fails closed。
- max rounds/nodes/runs/calls terminate the coordinator。
- interruption after node creation, execution, evidence preparation, and assessment resumes exactly once。
- same evidence may satisfy multiple requirements without double-counting work。

### 21.5 Publication safety tests

- readiness pass + claim pass + certify fail => blocked。
- readiness pass + claim fail + certify pass => blocked。
- both pass + reproduction fail => blocked。
- all applicable gates pass => publishable。
- stale attestation => blocked。
- target/source digest mismatch => blocked。
- high-scoring `debug_frontier` node cannot support positive headline claim。
- contextual-negative evidence cannot be linked as positive result evidence。
- archive candidate utility cannot override any hard gate。

### 21.6 Failure injections

- source file changed after node report hash。
- artifact missing after context build。
- more than 10 configurations and more than 20 candidate claims。
- budget overflow at first optional and first required item。
- related-work provider unavailable with and without recorded cache。
- malformed/unknown schema version。
- no LLM available for annotations/authoring。
- no network available during resume。
- all candidate nodes uncertified。
- scientific winner erased/stale after readiness。
- paper draft inserts unsupported number after ready context。

## 22. Evaluation and observability

### 22.1 Metrics

| Metric | Definition |
|---|---|
| requirement accounting rate | terminal-status requirements / applicable requirements |
| missing detection precision | true required gaps / emitted missing gaps |
| missing detection recall | detected true gaps / all fixture-labelled true gaps |
| silent omission count | inventory items absent from included and omission sets; target 0 |
| headline publishable coverage | headline claims linked to publishable lane / all headline claims |
| negative-result visibility | represented labelled negative results / all labelled negative results |
| unnecessary repair rate | repair requests whose evidence already existed / all requests |
| repair success rate | satisfied repair requests / executed requests |
| repair marginal cost | added nodes/runs/tokens/resources per newly satisfied requirement |
| readiness-to-finalization churn | attempts from first assessment to publication decision |

### 22.2 Audit records

Record:

- compiler/evaluator versions and policy digests。
- counts by requirement status/evidence lane/omission reason。
- repair request lifecycle and budget usage。
- context/brief/model-call digest lineage。
- independent publication sub-verdicts。
- stale invalidation event and source change。

Do not put raw secrets、provider credentials、unbounded source bytes、unredacted environment values
into the manuscript audit namespace。

## 23. Migration and rollout

### 23.1 Rollout sequence

1. off default ships with code unreachable by default。
2. audit enabled on controlled fixtures and selected real checkpoints。
3. audit metrics establish false-positive/false-negative baseline。
4. enforce without repair for new runs。
5. explicit repair for projection/literature/assurance, then experiments。
6. paper archive adapter。
7. auto repair only after termination and authority tests。

### 23.2 Rollback

- Set manuscript mode to off before a new paper attempt to use the legacy path。
- Existing `.ari-manuscript` artifacts remain inert and auditable; rollback does not delete them。
- An enforce-bound in-progress attempt is not silently continued under off; starting legacy authoring
  is a separate attempt/action and is visibly unbound。
- No schema downgrade rewrites committed artifacts。

### 23.3 Deletion of legacy assembly

Legacy context assembly and caps are not deleted merely because manuscript mode exists。Deletion
requires:

1. all supported manuscript-enabled backends use section briefs。
2. off compatibility policy has an approved replacement or deprecation release。
3. equivalent legacy fixture coverage exists in the new path。
4. migration/release docs identify changed output behavior。

Until then, legacy and manuscript paths are explicit, not partially interleaved。

## 24. Risks and controls

| Risk | Control |
|---|---|
| More context reduces model quality | section briefs, deterministic priority, per-call digest |
| Gate over-blocks non-applicable work | explicit applicability rules and admissible `not_applicable` provenance |
| LLM invents missing method/result | annotations non-claimable; fixed readiness evaluator |
| Failed experiments disappear | all-node inventory and contextual-negative lane |
| RQGM and paper archive recursively trigger each other | outer coordinator only; no nested research execution |
| Repair cost runs away | fixed rounds/nodes/runs/calls and fail-closed exhaustion |
| Repair broadens tool authority | inherit frozen capability binding; semantic request only |
| KCA rollout incomplete | audit first; enforce blocks rather than fabricate certification |
| Certified runner-up silently replaces winner | explicit subject-set decision and fallback conditions |
| Existing default changes | lazy imports, zero-artifact off path, golden identity tests |
| Plan ownership drifts into RQGM plans | isolated directory/index and adapter-only external references |
| Schema proliferation | minimum public contracts, companion binding, V1 immutability |
| Old attempts become misleading | digest staleness and append-only attempt lineage |

## 25. Completion criteria

Task 00 is `implemented` only when all applicable criteria have executable evidence。

### Contracts and completeness

1. Every profile requirement has a typed result and evidence/applicability trace。
2. `enforce` authoring starts with zero authoring-blocking `missing` requirements。
3. Inventory conservation holds for nodes、measurements、sources、references、figures。
4. Silent omission count is zero in all fixtures。
5. Failed/null/inconclusive/off-lineage items remain visible in correct lanes。
6. LLM annotation alone can never satisfy a factual requirement。

### Evidence and publication safety

7. Every headline result claim is linked only to publishable evidence。
8. Uncertified、stale、tampered、target-mismatched evidence cannot support positive publication
   claims under enforce。
9. readiness、claim、KCA、reproduction failures remain independently visible and each can block。
10. Final paper build、authoring binding、publication decision bind exact parent digests。
11. Changed evidence invalidates affected downstream artifacts before lock。

### Repair

12. Every repair action traces to one or more requirement IDs and an admitted executor。
13. Repair does not exceed fixed authority or budget and always terminates。
14. Resume is idempotent across all transaction interruption points。
15. Human-required decisions stop with an exact request rather than an inferred choice。

### Composition

16. All four research×paper topologies consume the same manuscript contract semantics。
17. Paper RQGM cannot modify readiness/evidence/KCA verdicts。
18. Research RQGM repair nodes retain request lineage and fixed constraints。
19. `ari paper` never starts research experiments implicitly。
20. KCA publication integration passes authentic Task 18/19 parity requirements where configured;
    unavailable external Harnesses remain blocked, not mocked。

### Compatibility and operations

21. `manuscript.mode=off` writes no manuscript artifacts and preserves default paper identity。
22. Legacy checkpoints require no migration for off mode and produce honest missing/unavailable states
    when audited。
23. Local suite and applicable remote/CI Harness suites are green。
24. Schema/reference/operator/migration documentation is permanent and current。
25. No existing plan file or index is required to understand this plan's implementation status。

## 26. Deletion criteria

This temporary plan may be deleted only when:

1. All §25 completion criteria are met and the implementation is merged。
2. Remote CI is green for all generally available execution paths。
3. Contract definitions and invariants are moved to permanent schema/reference documentation。
4. Architecture and authority boundaries are moved to a permanent developer guide/ADR set。
5. CLI/API behavior, repair operations, failure handling, and rollback are in operator docs。
6. Migration behavior for legacy checkpoints is in release/migration docs。
7. RQGM/KCA/paper archive adapters document their own stable integration interfaces in permanent docs
   without copying this temporary plan。
8. No downstream implementation or test cites this plan as its only normative specification。
9. [INDEX.md](INDEX.md) records the deletion status and reason。

## 27. Delete-after checklist

- [ ] All G0–G8 gates have executable evidence。
- [ ] All §25 criteria have been checked against the merged revision。
- [ ] `manuscript.mode=off` identity evidence is preserved in CI。
- [ ] JSON schemas and public/internal contract reference are permanent。
- [ ] Requirement profile authoring guide is permanent。
- [ ] Architecture/authority ADRs are permanent。
- [ ] Repair and resume runbook is permanent。
- [ ] Publication/KCA troubleshooting guide is permanent。
- [ ] Legacy checkpoint migration and rollback guide is permanent。
- [ ] RQGM and paper archive adapter interfaces are documented at their implementation locations。
- [ ] No unresolved safety or applicability decision remains only in this plan。
- [ ] Main merge and required CI/Harness evidence are confirmed。
- [ ] `INDEX.md` has been updated before deletion。

## 28. Open decisions to close at G0

These questions do not change the ownership boundary but must be decided before enforce work begins。

1. Whether manuscript public contracts enter `ari.public` in WP1 or after audit evidence in WP2。
2. Whether workflow segmentation is represented by additive `segment` metadata or an equivalent
   driver range API; duplicate workflow files are not acceptable。
3. Exact generic profile rule for stochasticity detection and minimum uncertainty evidence。
4. Whether venue-specific profiles use explicit composition or a fully materialized resolved
   profile artifact; the resolved digest is mandatory either way。
5. Whether audit mode records a shadow publication decision when KCA providers are unavailable。
6. Exact policy for certified runner-up fallback; default must be no silent fallback。
7. Which projection/literature/certification repairs are allowed from `ari paper` only when explicitly
   named, while experiment repair remains prohibited。
8. Artifact role integration strategy after v1: continue companion binding or introduce
   `PaperBuildV2`; legacy `PaperBuildV1` bytes must not be rewritten。

Every decision receives an ADR or a contract test before its dependent work package leaves
`planned` status。
