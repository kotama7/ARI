# 08 — RQGM Governance and Score Lineage

> Status: planned  
> Dependencies: 03, 04, 05  
> Gate: G4 — Vertical slices

## Purpose

RQGM の epoch、constitutional kernel、registry、transition、adversarial validation、evolution、frontier repair、paper archive を専用 workspace で可視化する。特に score の計算・penalty・policy change・再計算・無効化を immutable lineage として追跡し、「現在値だけが上書きされて過去の理由が見えない」状態を禁止する。

## Direct answer: score rewrite traceability

本計画では追跡対象に含める。各 score observation と rewrite について、最低限以下を GUI と API から辿れることを必須条件とする。

- node/proposal ID、epoch、policy hash、score policy version。
- base score、validated penalty、final score、rank と calculation components。
- old policy と new policy の parameter diff、変更理由、承認 transition。
- affected、recomputed、invalidated、stale、removed の各 node 集合。
- before/after score と rank。ただし比較可能性を policy 単位で明示する。
- kernel verdict、validated attack、audit event、source artifact、timestamp。
- frontier からの除外・再投入・repair への因果 link。

履歴は上書きしない。異なる policy hash の score は同じ連続 series として結ばず、epoch/policy ごとに facet または明確な断絶を表示する。

## Scope

- RQGM capability detection と run-scoped navigation。
- Overview、Epoch Timeline、Institution/Registry、Accountability、Score Lineage。
- Evolution/Frontier Repair、Paper Archive、Audit/Artifacts。
- committed artifact からの read model と不足 event の additive instrumentation。
- RQGM config interlock と effective snapshot の read-only 表示。
- legacy/incomplete/corrupt checkpoint の degraded representation。

## Non-goals

- GUI v1 から registry、policy、transition を直接 mutation しない。
- GUI が constitutional kernel や score policy の判断を再実行しない。
- policy legality/non-degeneracy を scientific quality improvement と表現しない。
- raw adversarial output を validated penalty として表示しない。
- stale/invalidated を物理 file deletion と同義にしない。

## Source artifacts

read model は次の canonical artifact を扱う。「truth（append-only、hash-chained）」と「snapshot/rollup（replay から再構築可能）」を区別し、projector は truth から構築して snapshot は検証にのみ使う。

**Truth（append-only log。hash chain は `finalize_event` の `event_hash`/`prev_event_hash`）**

- `rqgm_transitions.jsonl` — 制度状態の正本（`EpochStore.replay` の入力）
- `rqgm_audit.jsonl` — `ImmutableAuditLog`。governance_report、impeachment 系、erasure/rebuild event を含む
- `rqgm_adversarial_cases.jsonl` — raw_attack/defender_response/judgment_record/validated_attack の 4 record 型 + `UtilityRecord`
- `prompt_evolution.jsonl` — prompt/utility policy candidate（`UtilityPolicyCandidate` を含む）
- `rqgm_cleanroom.jsonl`、`rqgm_meta_outputs.jsonl`、`rqgm_governance_cache.jsonl`
- `proposals/proposal_records.jsonl`
- `paper_draft_archive.jsonl`、`paper_anchor_corpus.jsonl`

**Snapshot / rollup（削除・再構築可能）**

- `epoch_state.json`（`utility_policy` と `utility_policy_hash` を含む）
- `rqgm_registry.json`（`registry_version` と `as_of_event_hash` を持ち、replay 照合で verified 判定に使う）
- `prompt_specs.json`、`proposals/proposal_index.json`、`rqgm_erasure_state.json`
- `rqgm/adversarial_replay_pool.json`、`rqgm/paper_self_preference_stat.json`
- `paper_archive_state.json`（不在 = paper mode `linear`）

**State / provenance**

- `rqgm_state.json`（`mode`、`mode_source`、`switch_journal`。不在 = pure `simple_bfts`）
- `meta.json` の `constitution_hash`、checkpoint 内 `constitution.yaml` copy
- `rqgm_prompts/`（write-once の evolved template/policy body store）
- per-node: `tree.json`/`node_report.json` の `metrics` sentinel（`_scientific_score`、`_axis_scores`、`_pre_penalty_score`、`_validated_attack_penalty`、`_utility_policy_hash`、`_sterile`、`_stale`、`_valid_for_frontier`、`_stale_reason`、`_erasure_event_id`）

projector の parser は `ari/schemas/` の既存 20 schema（`rqgm_*`、`proposal_*`、`governance_report`、`epoch_state`、`epoch_transition`、`clean_room_*`、`erasure_state`、`selective_erasure_event`、`frontier_rebuild_event`）に対して検証し、GUI 独自の schema を発明しない。generic file explorer は fallback とし、主要 UI は typed read model を使う。source link から raw artifact/offset へ到達できるようにする。

## Governance state model

```text
RQGM Run
├── Epoch
│   ├── KernelDecision
│   ├── RegistrySnapshot
│   ├── Transition
│   ├── AdversarialValidation
│   ├── PolicyVersion
│   ├── ScoreObservation
│   └── FrontierSnapshot
├── EvolutionLineage
├── RepairLineage
├── PaperArchive
└── AuditEvent
```

- epoch、policy、registry snapshot は安定 ID/digest を持つ（hash は `hash12(canonical_json(...))`）。
- transition record の status は実装語彙 pending/committed/aborted/rejected/failed を用い、各 status_change は T1–T21 の `rule_id`（+ `EMERGENCY_EDGE`）を持つ。record は adoptions/sanctions/retirements/clean_room_requests/bans/fallbacks の配列と `next_active_components`、`kernel_validation` を含む。
- registry component/prompt の lifecycle 状態は実装の `STATUS_VALUES` をそのまま使う: candidate、validated、shadow、probationary_active、active、warning、probation、quarantine、retired、banned（active 集合 = active + probationary_active）。registry 状態の変更経路は `apply_registry_event` の 5 event 型（component_registered、prompt_registered、component_status_change、prompt_status_change、emergency_quarantine）のみ。
- この registry lifecycle 語彙と、node score の状態語彙（computed/recomputed/stale/invalidated/removed）は**別の state machine**であり、UI で混在させない。
- GUI の current state は committed transition の replay 結果であり、partial line や未 commit proposal を反映しない。
- research phase と governance stage は別 state machine とする。governance は epoch 境界の `GovernanceOrchestrator.audit_epoch`（九段階）で走る。

## Workspace tabs

### Overview

- RQGM enabled/capability、current epoch、policy hash、registry summary。
- research state と governance state の dual timeline。
- current/last completed stage、budget、degraded reason、pending accountability item。
- recent committed transitions と attention required。

### Epoch Timeline

- epoch start/end、trigger、policy、budget、candidate/winner、evaluation summary。
- prompt/utility/meta evolution と clean-room/repair の発生点。
- epoch 比較は schema/policy compatibility を確認してから表示する。

### Institution / Registry

- component/prompt の lifecycle graph と current registry snapshot（`rqgm_registry.json` の `registry_version`/`as_of_event_hash` を replay と照合して verified 表示）。
- lifecycle は実装語彙（candidate → validated → shadow → probationary_active → active、および warning/probation/quarantine/retired/banned）で表示し、T1–T21 の `rule_id` を transition edge に付す。
- role は `EVOLVABLE_ROLES`/`FIXED_ROLES`、tier は fixed/institutional/meta の実装語彙を用いる。`utility_policy` は role の一つとして registry に載る（T20 supersession、旧 hash の retirement）。
- incoming/outgoing accountability edge、transition history、source evidence。
- React Flow は lifecycle/relationship、table は監査可能な exact value に使う。

### Accountability

impeachment chain を実装の record 型で明示的に可視化する:

- raw_attack（`atk_*`）→ defender_response（`def_*`）→ judgment_record（`jdg_*`）→ validated_attack（`vat_*`、`target_component_id`、`affected_components`）→ `validated_attack_involvement` → `classify_target`（閾値 `ATTACK_THRESHOLD=2`）→ impeachment_motion（auditor 専任、requested_action ∈ demote/warn/quarantine/retire）→ governance_defense → adjudication → impeachment_outcome（upheld/partially_upheld/dismissed/inconclusive）→ registry transition。
- governance_report の `bond_accounting`（posted/refunded/forfeited/remaining_budget）と `recommendations` を段階に沿って表示する。
- transition reason、kernel verdict、constraints、validated evidence、actor/stage。
- proposed と committed の差分、rejection/degraded path。
- source event と raw artifact offset へ deep-link する。
- **責任接続の成立条件を正直に表示する**: exploration の 7 adversary は、
  登録済み `generator` に対し、ノードへ一度だけ付与した生成 component、
  prompt hash、epoch が凍結中の現職と一致する場合だけ impeachment chain
  を発火できる。旧記録、欠落、不一致は「攻撃 0 件 = 健全」とせず、
  `targetless provenance` という capability state で表示する。
  `paper_self_preference` は同じ原則で `paper_reviewer` /
  `paper_writer` に接続する。

### Score Lineage

score 書換えは実装上**二つの独立 channel** を持ち、UI は両者を区別して表示する。

1. **対審 penalty（node 単位、epoch 内）**: `apply_utility_penalty` が `metrics._scientific_score` を `max(0, base − penalty)` へ書換え、`_pre_penalty_score`/`_validated_attack_penalty` sentinel に旧値を保存する。監査 record は `UtilityRecord`（`utl_*`: `base_score`、`penalty`、`final_score`、`input_refs`（result/review/validated_attack ids）、`frozen_policy`、`supersedes`、`recomputed_in_epoch`）。penalty を駆動できるのは adjudicated な `ValidatedAttackRecord` のみ（raw attack は絶対に score へ触れない）。
2. **epoch 境界の utility policy 書換え（run 全体）**: policy body は `{composite, axis_weights, frontier_score, depth_penalty_lambda, ucb_c}`、`seal_utility_policy` が `utility_policy_hash`（hash12）を付す。全 scored node に `_utility_policy_hash` が stamp され、T20 で旧 policy が retire されると frontier repair が旧 hash 配下の node を invalidate する。原因と結果は `SelectiveErasureEvent`（`erase_*`: `invalidated_node_ids`、`recompute_node_ids`、`transitive_stale_record_ids` 等）と `FrontierRebuildEvent`（`rebuild_*`: `frontier_before/after`、`removed/reinstated/recomputed_utility_node_ids`）に記録済み。

表示要件:

- node 単位の score observation history（channel 1 と 2 を区別した marker 付き）。
- base → validated penalty/components → final の waterfall/table。
- policy version/hash、calculation version、epoch、rank、computed/recomputed marker。
- policy update の before/after table と parameter diff（policy body の 5 key）。
- affected/recomputed/invalidated/frontier-changed node set は erasure/rebuild event の実 field から導出する。
- rank movement は同一 policy 内を既定とし、cross-policy は explicit comparison mode のみ。
- 名称の subtlety に注意: 実装では penalty 側の frozen policy と epoch policy がともに `utility_policy_hash` の名を使い、policy 種 record では `prompt_hash` == `utility_policy_hash`。DTO では別名（penalty policy / epoch utility policy）に正規化して混同を防ぐ。

### Evolution and Frontier Repair

- adversarial、prompt、utility、meta evolution の input/output lineage。
- clean-room regeneration、selective erasure、frontier repair の原因と結果。
- raw candidate、validated candidate、adopted policy を混同しない。
- repair 後に score/registry/frontier のどれが変わったかを示す。

### Paper Archive

- paper epoch、draft/archive（`paper_archive_state.json`、`paper_draft_archive.jsonl`、`archive/{node_id}/*.tex`）、anchor corpus（`paper_anchor_corpus.jsonl`）、review/self-preference lineage（`rqgm/paper_self_preference_stat.json`）。
- execution mode（`ari.mode`）と paper mode（`paper.mode`）の独立性を常時表示する。
- selected paper と governance winner/research result を同義にしない。
- anchor 無効（`anchor.enabled: false` 既定）の場合、reviewed best-of-N である旨と writer sanction が発火しない旨を明示する。

### Audit and Raw Sources

- cursor-based transition/audit event table。
- filter: epoch、stage、entity、decision、policy hash、severity。
- event → parsed DTO → raw artifact/offset の三段 drill-down。
- corrupt/partial/index rebuilding を明示する。

## Score lineage DTOs

```ts
type ScoreObservation = {
  observationId: string
  runId: string
  nodeId: string
  epochId: string
  policyHash: string
  calculationVersion: string
  baseScore: number | null
  components: Array<{ key: string; value: number; validated: boolean }>
  validatedPenalty: number | null
  finalScore: number | null
  rank: number | null
  state: 'computed' | 'recomputed' | 'stale' | 'invalidated'
  sourceEventId: string
  occurredAt: string
}

type ScoreRewrite = {
  rewriteId: string
  transitionId: string
  epochId: string
  fromPolicyHash: string
  toPolicyHash: string
  reasonCode: string
  policyDiff: Array<{ path: string; before: unknown; after: unknown }>
  affectedNodeIds: string[]
  recomputedNodeIds: string[]
  invalidatedNodeIds: string[]
  removedNodeIds: string[]
  frontierAddedNodeIds: string[]
  frontierRemovedNodeIds: string[]
  sourceEventIds: string[]
  committedAt: string
}
```

field が legacy artifact に存在しない場合は推測値で埋めず、`unknown` と reconstruction confidence/source を返す。巨大 node set は inline 配列ではなく paginated relation endpoint に分離できるようにする。

## API surface

```text
GET /api/v1/runs/{run_id}/rqgm/capabilities
GET /api/v1/runs/{run_id}/rqgm/overview
GET /api/v1/runs/{run_id}/rqgm/epochs
GET /api/v1/runs/{run_id}/rqgm/epochs/{epoch_id}
GET /api/v1/runs/{run_id}/rqgm/registry
GET /api/v1/runs/{run_id}/rqgm/transitions?cursor=...
GET /api/v1/runs/{run_id}/rqgm/nodes/{node_id}/lineage
GET /api/v1/runs/{run_id}/rqgm/policies
GET /api/v1/runs/{run_id}/rqgm/score-rewrites?cursor=...
GET /api/v1/runs/{run_id}/rqgm/score-rewrites/{rewrite_id}/affected-nodes
GET /api/v1/runs/{run_id}/rqgm/evolution
GET /api/v1/runs/{run_id}/rqgm/paper-archive
GET /api/v1/runs/{run_id}/rqgm/audit?cursor=...
```

overview は bounded summary とし、transition/audit/affected node を埋め込まない。JSONL 系は stable cursor、filter、page size、source revision を持つ。

## Required runtime instrumentation

計画上の event の大半は**既存 record で賄える**。additive instrumentation を追加する前に、次の対応表で既存 artifact への projection を優先する。

| 論理 event | 既存の record / artifact | 追加要否 |
|---|---|---|
| `policy.update_proposed` | `UtilityPolicyCandidate`（`prompt_evolution.jsonl`） | 不要 |
| `policy.update_committed` | `epoch_transition` の adoption（role `utility_policy`、T20） | 不要 |
| `score.observation_committed` | `UtilityRecord`（`rqgm_adversarial_cases.jsonl`） | 不要 |
| `score.rewrite_committed` | `SelectiveErasureEvent` + `FrontierRebuildEvent`（`rqgm_audit.jsonl`） | 不要 |
| `registry.transition_committed` | `epoch_transition` record（`rqgm_transitions.jsonl`） | 不要 |
| `frontier.repair_committed` | `FrontierRebuildEvent` | 不要 |
| `governance.stage_started/completed/degraded` | なし（`audit_epoch` 九段階は epoch 境界でまとめて `governance_report` になる） | **live 進捗表示に必要な場合のみ additive 追加** |
| `score.recompute_started` | 完了後の `recomputed_in_epoch` のみ | live 表示が必要なら additive 追加 |

新設する event は deterministic ID、run/epoch/policy、causation/correlation ID、source artifact revision を持ち、既存の hash chain 契約（`finalize_event`）に従う。commit event より前の partial state を current view に採用しない。

## Truth and presentation rules

- governance blocked は research failed ではない。
- raw attack severity は validated penalty ではない。
- policy accepted は scientific quality improved ではない。
- stale、invalidated、removed、physically deleted を別 state とする。
- score は metric/calculation version、epoch、policy hash なしに表示しない。
- cross-policy comparison は警告、facet、parameter diff を伴う。
- missing source は 0 と表示しない。
- 「attack 0 件」を「問題なし」と表示しない。chain が構造的に inert な role では、その旨を capability state として示す。
- current registry は committed transitions の replay と snapshot（`rqgm_registry.json` の `registry_version`/`as_of_event_hash`）が一致した場合に verified とする。
- UI 集計から raw event/artifact へ必ず辿れる。

## Configuration integration

- Overview で RQGM effective config snapshot と source provenance を read-only 表示する。
- `ari.mode`/`rqgm.enabled` interlock と paper mode の独立軸を表示する。
- active/resumed run では mode/policy-affecting field を編集不可にする。
- new run への clone 時だけ current config を draft 化し、schema migration diff を示す。
- budget exhaustion、feature disabled、legacy unsupported を別 capability reason とする。

## Migration sequence

1. artifact inventory と schema/version fixture を固定する。
2. offline projector と overview/epoch/transition API を実装する。
3. source link 付き read-only tables を先に提供する。
4. explicit lifecycle/score rewrite event を runtime に additive 導入する。
5. Registry、Accountability、Score Lineage の vertical slice を追加する。
6. Evolution/Repair/Paper Archive を追加する。
7. SSE topic と live stage を有効化する。
8. legacy/file-only checkpoint の degraded mode と reconstruction warning を検証する。

## Testing

- committed/uncommitted/partial/corrupt transition replay test。
- snapshot digest と replay state の整合 test。
- score observation/rewrite の before/after/policy/source completeness test。
- cross-policy series を接続しない presentation contract test。
- raw attack と validated penalty、stale と removed の semantic test。
- affected/recomputed/invalidated/frontier relation の pagination integrity test。
- epoch/policy/node deep-link と raw artifact offset test。
- no-RQGM、legacy、running、degraded、completed、resumed fixture test。
- 10k events/large registry の cursor、virtualization、latency test。
- 三言語、keyboard、screen-reader table fallback、visual regression test。

## Completion criteria

- committed RQGM transition が Overview から raw source まで追跡できる。
- 全 score rewrite が old/new policy、before/after、reason、affected node、source event を持つ。
- score history が上書きされず、policy hash を跨ぐ誤った連続表示がない。
- research/governance、raw/validated、stale/removed の state が UI/API/test で分離される。
- RQGM disabled/legacy/degraded 時に推測で正常表示しない。
- v1 workspace が read-only であり、direct governance mutation endpoint を持たない。

## Deletion criteria

- RQGM GUI guide、API/artifact/event reference、score semantics を恒久文書へ移し、file-only debugging が主要 UI でなくなっている。

## Delete-after checklist

- [ ] RQGM GUI guide を三言語で公開した。
- [ ] score lineage/event schema を reference docs へ移した。
- [ ] truth rules を automated contract test に移した。
- [ ] main merge と CI green を確認した。
- [ ] `INDEX.md` を更新した。
