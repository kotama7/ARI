---
sources:
  - path: ari-core/ari/rqgm
    role: implementation
  - path: ari-core/ari/rqgm/runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/prompt_spec.py
    role: implementation
  - path: ari-core/ari/rqgm/prompt_evolution.py
    role: implementation
  - path: ari-core/ari/rqgm/transition_rules.py
    role: implementation
  - path: ari-core/ari/rqgm/utility_evolution.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_anchor.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_self_preference.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/ari/configs/defaults.yaml
    role: config
  - path: ari-core/tests/test_rqgm_kernel.py
    role: test
last_verified: 2026-08-03
---

# RQGM Runtime Walkthrough

[RQGM Architecture](rqgm_architecture.md) explains *why* Constitutional
ARI-RQGM exists and which invariants it holds. This page shows the machine
**in motion**: one `ari_rqgm` run traced end to end — what happens at boot,
per node, at every epoch boundary, and which bytes land in which checkpoint
file. Every event-log excerpt below is taken from real runs (lines
truncated, run-specific values elided with `…`).

![Vertical flow of one ari_rqgm run: boot and mode resolution, RQGMRuntime construction, the founding-registration transaction (32 prompt-or-policy records + 20 components), epoch_000 opening with the frozen active set, the per-node loop (proposal routing, node execution, governance level, adversarial round), the epoch boundary (audit, transition engine + kernel, boundary transaction, frontier repair), and the next epoch opening.](../assets/images/rqgm/rqgm_run_lifecycle.svg)

The same flow, compressed:

```text
boot ──▶ mode resolution ──▶ RQGMRuntime ──▶ founding registration ──▶ epoch_000 open
                                              (1 txn: 32 prompts,        (active set
                                               20 components)             frozen)
                                                                             │
        ┌────────────────────────────────────────────────────────────────────┘
        ▼
  ┌─ per node ────────────────────────────────────────────────┐
  │ proposal → summary-only view → node executes →            │◀─┐
  │ governance level → (maybe) adversarial round              │──┘ next node
  └───────────────┬───────────────────────────────────────────┘
                  │ every nodes_per_epoch new nodes (loop-head tick + end-of-run flush)
                  ▼
  ┌─ epoch boundary ──────────────────────────────────────────┐
  │ audit_epoch → GovernanceReport → resolve (T1–T21) →       │
  │ kernel validate → prepare/close/open/commit →             │
  │ frontier repair → clean room                              │
  └───────────────┬───────────────────────────────────────────┘
                  ▼
            epoch_001 open (repeat)
```

---

## Step-by-step: one run

### 1. Boot — mode resolution

`ari run` resolves the effective mode once, before anything else:
`ari.mode: ari_rqgm` and `rqgm.enabled: true` must both agree
(`ari.rqgm.mode.resolve_effective_mode`), with `ARI_MODE` /
`ARI_RQGM_ENABLED` env overrides applied last. Any disagreement degrades to
`simple_bfts` with a warning. Under the default `simple_bfts`, **no
`ari.rqgm` module is imported at all** — everything below happens only in
`ari_rqgm`. Details and the switch-timing policy:
[Execution Modes](../guides/execution_modes.md).

`build_runtime` then constructs one `RQGMRuntime`
(`ari/rqgm/runtime.py`), wraps the BFTS strategy in a pure-delegation
`GovernedSearchStrategy`, writes `rqgm_state.json` (mode provenance:
`mode_source` ∈ `config|env|resume`), and copies the human-readable
`constitution.yaml` into the checkpoint. The run loop discovers RQGM by a
single duck-typed read: `getattr(bfts, "rqgm", None)`.

### 2. Founding registration — one transaction, the whole institution

On the first `ensure_epoch` tick (loop start, main thread), a fresh RQGM
checkpoint runs the **founding registration**
(`RQGMRuntime._register_founding`): every prompt and component from the
frozen founding tables in `ari/rqgm/prompt_spec.py` is registered through a
single prepare → … → commit transaction on `rqgm_transitions.jsonl` —
**32 `prompt_registered` + 20 `component_registered` events** between one
`epoch_transaction_prepare` and one `epoch_transaction_commit`
(`transition_id: transition_founding`):

```jsonc
{"event_id": "evt_000000", "event_type": "epoch_transaction_prepare",
 "payload": {"transition_id": "transition_founding"}, "prev_event_hash": ""}
{"event_id": "evt_000001", "event_type": "prompt_registered",
 "payload": {"prompt_id": "agent_system_prompt_v1", "role": "generator",
             "status": "active", "prompt_hash": "a50abe13d568",
             "source": {"kind": "committed_template", "key": "agent/system"}, …}}
// … 31 more prompt_registered, then 20 component_registered …
{"event_id": "evt_000053", "event_type": "epoch_transaction_commit",
 "payload": {"transition_id": "transition_founding"}}
```

The 20 founding components are `generator_v1`, the seven exploration adversary types (each
`adversary_{type}_v1`, one per attack family: cost explosion, evidence gap,
metric gaming, overclaim, prior art, prompt injection, reproducibility),
`defender_v1`, `artifact_judge_v1`, `proposal_router_v1`,
`prompt_mutator_v1`, `clean_room_generator_v1`, `policy_mutator_v1`,
`utility_policy_v1`, the live meta actors `replay_selector_v1` and
`failure_summary_compressor_v1`, and the registry-addressable judiciary
`auditor_v1`, `evidence_clerk_v1`, `governance_judge_v1`. The 32 prompts
cover those prompted roles, proposal generators, and BFTS orchestration;
the deterministic Evidence Clerk has no prompt. Paper archive adds three
gated prompts/components (35/23 total). Replaying the log reconstructs
`rqgm_registry.json` byte-identically; the
registration is **write-once** — any resume that finds an epoch or
committed registrations in the log never re-registers, and a crashed
founding transaction (prepare without commit) is invisible to replay and
safely re-run.

### 3. `epoch_000` opens — the institution freezes

Immediately after the founding commit, `epoch_000` opens and the founding
active set is frozen into `epoch_state.json`: `active_components` (one
rollup winner per role) and `active_prompt_hashes` (one 12-hex hash per
role), plus the utility policy, all pinned under a deterministic
`policy_fingerprint`, a separately declared `execution_fingerprint`, and
their composite `epoch_fingerprint`, all excluding timestamps. Missing
provider/environment revision pins are recorded as `unresolved`. Nothing in this set can
change until the next boundary.

```jsonc
{"event_id": "evt_000054", "event_type": "epoch_open",
 "payload": {"epoch_state": {"epoch_id": "epoch_000", "epoch_seq": 0,
   "node_count_at_open": 1,
   "active_components": {"adversary": "adversary_reproducibility_v1",
                         "judge": "artifact_judge_v1", "defender": "defender_v1", …},
   "active_prompt_hashes": {"generator": "af0aba2d5805", "router": "38b1ea409ff5", …}}}}
```

### 4. Per node — proposal, execution, governance level

For every node, three best-effort hooks run around the unchanged BFTS
lifecycle:

1. **Proposal routing.** The `ProposalRouter` records each root idea /
   expansion direction as a full `ProposalRecord` in
   `proposals/proposal_records.jsonl` ("store everything"). BFTS itself
   only ever receives the capped **`ProposalSummaryView`** (title, short
   description, hypothesis, plan, success metric, risks, expected
   artifacts, dissent summary, scores) — the summary-only channel that
   keeps full proposal text out of the search context.
2. **Node execution.** The agent loop runs exactly as in `simple_bfts`.
   Governance never vetoes node execution — every hook is fail-open.
3. **Governance level.** After evaluation, the budget ladder assigns the
   node a level L0 (fixed checks only) … L3 (fully adjudicated) from
   deterministic triggers (`top_k`, `score_jump`, `paper_candidate`,
   `novelty_claim`, `low_confidence`) and audit-logs it:

```jsonc
{"event_type": "governance_level",
 "payload": {"epoch_id": "epoch_000", "node_id": "node_a37b4c06",
             "level": 3, "triggers": ["top_k"]},
 "event_hash": "ae8eeb7521f1", "prev_event_hash": "23567870882b"}
```

Note the `event_hash` / `prev_event_hash` pair — every line of
`rqgm_audit.jsonl` is hash-chained, and resume re-verifies the chain.

### 5. Per node — the adversarial round (event-driven)

An adversarial round runs only when the trigger disjunction fires (node in
the top-K of the frontier, score jump vs. parent beyond the threshold,
paper candidate, novelty claim, a cheap per-type pre-signal, or a
deterministic hash-based sample). When it does:

1. Triggered adversary types attack the node's **artifacts** (the attack
   schema has no component field) → `raw_attack` records. Raw attacks are
   **score-inert**: nothing changes yet.
2. The defender responds → `defender_response`.
3. The `ArtifactJudge` adjudicates → `judgment_record`. Only a
   judge-validated attack becomes a `validated_attack` and applies a
   bounded utility penalty (epoch-frozen weights and cap; the pre-penalty
   score is preserved in additive metric keys). Judge failure falls back
   to `invalid` — no penalty.
4. Validated attacks feed the `AdversarialReplayPool` (snapshot updated at
   boundaries only), which later regression-tests prompt candidates.

Everything is journaled to `rqgm_adversarial_cases.jsonl`, including an
idempotency **round marker** (`rqgm_adversarial_round`, keyed by
`node_id` + `epoch_id`) so a resumed run never re-attacks a node.

### 6. The epoch boundary — audit, transition, repair

The v1 boundary trigger is node count (`rqgm.epoch.nodes_per_epoch`,
default 10), checked by `ensure_epoch` at the outer-loop head — main
thread, no node in flight. The same tick runs **once more at end-of-run**,
so a trigger met by the final loop iteration still fires (a trailing epoch
that has not met the trigger stays open). Inside the boundary window:

![Epoch boundary swimlane diagram: the GovernanceOrchestrator runs its nine audit steps and writes to rqgm_audit.jsonl; the RegistryTransitionEngine resolves the transition against T1–T21 and runs the boundary transaction; the ConstitutionalKernel validates or blocks the transition; the checkpoint store receives the transitions quadruple, epoch_state.json, rqgm_registry.json, and frontier-repair events.](../assets/images/rqgm/rqgm_epoch_boundary.svg)

1. **Audit.** `GovernanceOrchestrator.audit_epoch` runs the nine-step
   pipeline: collect observations → reliability assessment → evidence
   assembly (the **EvidenceClerk** is the only evidence assembler;
   inadmissible same-role material is dropped here) → prosecution decision
   (only the **Auditor** may file an `ImpeachmentMotion`, consuming a
   per-epoch quota unit; the legacy counters transfer no value) → defense generation →
   adjudication panel (motions + prompt-candidate evaluations) →
   replay-pool update → **governance self-audit** (the pipeline audits its
   own four actors: auditor, evidence clerk, defender, governance judge) →
   `GovernanceReport`. The report is advisory — the orchestrator never
   writes a registry. A real first-boundary report:
   `record_id: govreport_epoch_000`, `self_audit.checked_components:
   ["auditor_v1", "defender_v1", "evidence_clerk_v1",
   "governance_judge_v1"]`, `bond_accounting: {posted: 0, …}`. All four are
   registry-addressable and sanctionable; if the Governance Judge itself is
   the motion target, it recuses rather than adjudicating its own case.
2. **Meta step.** The meta tier runs the prompt mutator, policy mutator,
   replay selector, failure-summary compressor, and any pending clean-room
   generation in a read-only sandbox; every output enters the lifecycle as a
   `candidate` or an audit-only recommendation, never as an activation.
   Candidate minting is not failure-gated: at
   **every** boundary — calm epochs included — the `PromptMutator`
   proposes one candidate per evolvable role with an active incumbent,
   within the `rqgm.prompt_evolution` caps and the per-candidate budget
   gate; with no LLM available (or under budget degradation) it falls
   back to the deterministic LLM-less kinds (`threshold_tuning`,
   `schema_tightening`), and an interrupted-boundary re-run never
   duplicates a candidate (the deterministic candidate id is the dedup
   key). The step is always audit-visible: enabled boundaries leave a
   `meta_evolution` summary line (outcome `proposed`/`no_op`, counts,
   skip reasons — unregistered invokers included), and
   `rqgm.prompt_evolution.enabled: false` emits
   `prompt_evolution_skipped` instead of minting.
3. **Transition.** The `RegistryTransitionEngine` — the sole registry
   status writer — resolves adoptions, sanctions, and retirements from the
   report's recommendations and candidate evaluations, purely against the
   fixed T1–T21 table (the T1–T19 base plus the two role-scoped
   supersession rows T20/T21). The `ConstitutionalKernel` validates the
   resolved transition: illegal edges block (`CK-REG-001` table violation,
   `CK-REG-002` boundary-only edge stamped mid-epoch), non-engine registry
   writers block (`CK-ROL-901` — a judge can never write the registry),
   while T16 `emergency_quarantine` force-closes the current epoch and opens
   a newly fingerprinted epoch atomically. A blocked
   transition means the incumbent active set carries over. Continuing
   candidate generation is safe only under the documented side-effect-free
   sandbox assumption; external irreversible operations require a separate
   fixed fail-closed gate.
4. **Commit.** The boundary lands as a four-event transaction on
   `rqgm_transitions.jsonl`:

```jsonc
{"event_type": "epoch_transaction_prepare", "payload": {"transition_id": "transition_000_to_001"}}
{"event_type": "epoch_close",  "payload": {"epoch_id": "epoch_000",
                                           "transition_id": "transition_000_to_001", "node_count_at_close": 2}}
{"event_type": "epoch_open",   "payload": {"transition_id": "transition_000_to_001",
                                           "epoch_state": {"epoch_id": "epoch_001", "previous_epoch_id": "epoch_000", …}}}
{"event_type": "epoch_transaction_commit", "payload": {"transition_id": "transition_000_to_001"}}
```

   A committed `epoch_transition` record (with the governance report's
   SHA-256 among its inputs) is simultaneously appended to
   `rqgm_audit.jsonl`. Double commits of the same `transition_id` are
   guarded no-ops; interrupted transactions are discarded on resume and
   re-run deterministically.
5. **Frontier repair** (only when the committed transition retired
   something). The `FrontierRepairEngine` traces the dependency closure
   from each retired `prompt_hash`, marks dependent records stale
   (`_stale`, `_valid_for_frontier` sentinels persisted through
   `tree.json`), and rebuilds the frontier. Erasure is **logical only** —
   nothing is physically deleted — and role-specific. If scored evidence
   goes stale, its utility is recomputed from surviving inputs under the
   original epoch's frozen weights. If the utility policy itself retires,
   nodes are instead re-scored from stored policy-independent `_axis_scores`
   under the new criterion; unusable raw axes fail closed to invalidation.
6. **Clean room.** Pending regeneration requests for retired roles execute
   inside the window; admissible outputs enter the next cycle as
   candidates. Then the next epoch's active set is frozen and search
   resumes.

### 7. Prompt evolution — candidates crawl, the RTE adopts

From ablation rung B7 upward, the `PromptMutator` emits **candidates
only** — it can never write the registry. Every candidate crawls the
six-stage validation lifecycle before it is even eligible for adoption:

![PromptSpec lifecycle state machine: a candidate passes static validation, constitutional validation, schema dry run (terminal on failure), replay evaluation against the adversarial replay pool, anchor evaluation, and shadow; adoption into probationary_active happens only through the RegistryTransitionEngine at an epoch boundary; sanction edges lead through warning, probation, and quarantine to retired and the absorbing banned state; a dashed arrow shows clean-room regeneration re-entering as a new candidate.](../assets/images/rqgm/rqgm_prompt_lifecycle.svg)

`static_validation` → `constitutional_validation` (both deterministic and
free) → `schema_dry_run` (one injected LLM call; **failure is terminal**)
→ `replay_evaluation` (against the `AdversarialReplayPool` accumulated in
step 5) → `anchor_evaluation` (fixed anchor set; ties favor the incumbent)
→ `shadow` (sampled side-by-side, observation-only). Stage skipping is a
constitutional violation. Adoption happens **only** through the RTE at a
boundary (`shadow → probationary_active`, rule T6), one adoption per role
per boundary, and there is no `candidate → active` shortcut.

When a prompt is retired, its replacement is **clean-room generated**: the
fixed tier assembles a closed, kernel-screened input bundle — committed
catalogs plus abstract failure summaries — and the retired prompt text
itself is a forbidden input (contamination rules `CK-CLN-001/002`, enforced
by a word-shingle screen and the `RetiredPromptAccessGuard`). The meta tier
can propose, never appoint (deny-by-default capability flags, authority
non-expansion checked as subset arithmetic).

What detection looks like in the audit log (from the B8 injection smoke
harness, which plants scripted misbehaving components):

```jsonc
{"event_type": "validated_attack", "payload": {"case_type": "overclaim",
   "attack_summary": "scripted always_attack double: unconditional attack", …}}
{"event_type": "constitutional_violation", "payload": {"check": "validate_record_schema",
   "injection_id": "eval_inj_006_bad_generator", "codes": ["CK-SCH-N01"]}}
{"event_type": "prompt_candidate_rejected", "payload": {"candidate_id": "eval_cand_degenerate",
   "stage": "schema_dry_run", "failure_count": 4}}
```

A planted always-validate judge produces validated attacks that the
reliability assessment flags; a bad generator double trips the schema
check; a degenerate mutator candidate dies in `schema_dry_run` — all
without interrupting a single node.

### 8. Run end

The end-of-run `ensure_epoch` flush (step 6) fires a final boundary if the
node-count trigger is met; otherwise the trailing epoch simply stays
`open`, matching crash-recovery semantics — `ari resume` replays the event
logs, re-verifies the audit-log hash chain, and continues (a blocking
integrity finding degrades to governance-suspended carry-over, never a
refusal to resume).

The paper phase that follows then runs the **paper-candidate pre-flight**:
persisted utility penalties are replayed onto the loaded nodes, the best
node is escalated through one L3 paper-candidate adversarial round, and the
selection is repeated until the winner is stable — so a node crowned by
another node's demotion still gets its own round. Every entry (`ari run`,
`ari resume`, `ari paper`) reaches it through the shared paper dispatch. The
round attacks the paper's own artifacts, so it is gated on those existing:
on a checkpoint that has not produced a paper yet it defers until after the
pipeline wrote them, because its one-shot marker spent on an empty bundle
would suppress the artifact-grounded round for that node permanently.

---

## A utility rewrite at a boundary (Task 14)

The boundary above adopts *prompts*. It can also rewrite the **score
itself**. Each epoch's frozen `utility_policy_hash` is the adopted policy's
seal (`capture_utility_policy` reads the active `utility_policy` entry,
falling back to the resolved `cfg` at epoch 0). When a `policy_mutator`
candidate crawls the lifecycle and adopts, the hash **changes across
boundaries** — over a real multi-epoch run it walks, e.g.,
`fed4460f44f6 → 8a9da4fb9dc3 → 8ea0dac3cd1b`, and the `epoch_fingerprint`
moves with it.

Unlike a behavioral role, the utility policy is a criterion, so it is
adopted by **supersession** (edge T20): the same-boundary T6 adoption of the
successor emits an `active → retired` status change that retires the
*healthy* incumbent with its **old** hash. `frontier_repair` then treats the
old hash as a retired dependency and re-scores every node stamped
`_utility_policy_hash: <old>` from its stored `_axis_scores` under the newly
frozen composite and weights. A node without usable raw axes is marked
`utility_invalidated`; no stale-policy score survives. In the live boundary
that exposed this seam, five nodes were re-scored and none invalidated:

```jsonc
{"event_type": "component_status_change", "payload": {"role": "utility_policy",
   "component_id": "utility_policy_v1", "from_status": "active",
   "to_status": "retired", "rule_id": "T20", …}}
{"event_type": "selective_erasure", "payload":
   {"retired_prompt_hashes": ["fed4460f44f6"],
    "policy_rescored_node_ids": ["node_…"], "invalidated_node_ids": [], …}}
```

**Honest limit.** At the default config (`axis_mode: dynamic`, empty static
`axis_weights`) there is no fixed per-axis basis, so T3's "scores at least as
well" gate has nothing to order and supersession reduces to legality plus
non-degeneracy — the criterion rolls within the legal simplex rather than
provably improving. That is the honest Red-Queen posture (no ground truth ⇒
nothing to be strictly-better against), and it is exactly the gap the paper
phase's anchor closes for the reviewer criterion.

---

## A paper-archive run (paper.mode: rqgm_archive)

The paper phase is a **separate, orthogonal** mode: `paper.mode:
rqgm_archive` + `rqgm.paper.enabled: true` (see
[The paper-archive layer](rqgm_architecture.md#the-paper-archive-layer)). One
`PaperArchiveRuntime` epoch is one archive round; a co-evolution run does
`rqgm.paper.epoch.rounds` of them.

1. **Seed → refine tree.** `run_archive` builds a best-first tree over draft
   space: the `paper_root` fans out into K = `archive.width` seed drafts
   (each a `write_paper_iterative` skill call), and each draft fans out into
   up to `archive.refine_rounds` `paper_refine` **child** nodes down to
   `archive.depth`. `select_best_to_expand` ranks the frontier by the
   governed `paper_reviewer` composite plus a real `diversity_bonus`; the
   population is capped at `min(width·(1+refine_rounds), max_expansions)` at
   any depth. Every draft is journaled to `paper_draft_archive.jsonl`.
2. **Anchor → adversary → impeachment.** At each round head the active
   `paper_reviewer` is scored on the held-out anchor corpus. A reviewer that
   over-accepts (accepts a draft whose ground truth is `reject`) is both
   below the reliability floor and low on the anchor board — **and** the
   anchor's over-acceptance signal drives a genuine `paper_self_preference`
   round (adversary → Defender → ArtifactJudge). Its `ValidatedAttackRecord`
   carries `target_component_id: paper_reviewer_v1` (the Task-15 binding), so
   `validated_attack_involvement → classify_target` opens an
   `ImpeachmentMotion` against the reviewer — the sanctioned path to a role
   opening.

   ```jsonc
   {"event_type": "validated_attack", "payload": {"case_type": "paper_self_preference",
      "target_component_id": "paper_reviewer_v1", …}}
   ```

   The **writer** is sanctioned on the same round, through its own anchor. The
   active writer's best draft is scored against the Layer-0 claim-evidence
   gate (`run_hard_gate(write=False)` — read-only, deterministic), the score is
   landed on the anchor board keyed on that writer's `prompt_hash` alone, and
   an over-accepted draft that is **also** unfaithful binds a second record:

   ```jsonc
   {"event_type": "validated_attack", "payload": {"case_type": "paper_self_preference",
      "target_component_id": "paper_writer_v1", "affected_components": ["paper_writer"], …}}
   ```

   The hash keying matters: one component id spans successive prompt versions,
   so a component-keyed score would leak the incumbent's faithfulness onto its
   successor and make a fresh writer instantly impeachable.
3. **Adoption (co-evolution witness).** With the role opened, a co-evolved
   successor prompt can climb `validated → shadow → probationary_active` and
   adopt; T21 then moves the demoted incumbent to a reinstatable `shadow`
   standby. The witness is the active `prompt_hash` observed at each round
   head. Over a real 8-round proof the reviewer moves
   `04b3c49d070d → c0dfd764abab`, and the writer moves
   `f38a15f0f140 → b2c36f9a8232` (four rounds flat, then adopted). Remove the
   anchor and there is no attack, no adoption, and the sequence stays flat —
   with **faithful** drafts the same driver yields zero writer attacks, zero
   writer motions and a constant writer hash, while the reviewer is still
   attacked and impeached. The writer's successor is not adopted for being
   better; it is adopted because the incumbent regressed.
4. **Best draft → the untouched claim gate.** After the rounds,
   `materialize_winner` copies the best draft's `.tex` **once** to
   `{ckpt}/full_paper.tex` (pure select-and-copy, no gate/kernel/LLM call).
   The **existing** compile + `claim_evidence_hard_gate_final` + finalize
   tail (Layer 0, untouched) runs on it byte-for-byte as in a linear run —
   `write_paper`'s `skip_if_exists` picks it up.

**Honest limits.** Both prompts co-evolve, but the writer only on a
**regression**: a writer successor waits at `shadow` until the incumbent is
sanctioned for regressing on claim-gate faithfulness — a merely-better
challenger never displaces a faithful incumbent. The writer's *draft* winners
are still epoch-local (ranked by the in-epoch-frozen reviewer). The
writer-targeted attack rides the `paper_self_preference` round, which fires
only on an **over-accepted** anchor case, so an unfaithful writer under a
reviewer that over-accepts nothing is not sanctioned today. At the default
`rqgm.paper.epoch.rounds: 2` the boundary and impeachment fire but the
~5-boundary climb does not *complete* an adoption (the proofs drive 8). With
the anchor at its default `false`, `rqgm_archive` is reviewed best-of-N until
a corpus is supplied — and since the writer's faithfulness case is landed on
that same pool, no pool means no writer sanction either. And the
self-preference round currently demotes a *synthetic* accountability node, not
a real over-accepted archive draft (that in-phase demotion is deferred) — the
accountability / co-evolution channel is the one that fires.

---

## What you see on disk

After even a two-node `ari_rqgm` run, the checkpoint contains (RQGM files
only; the full inventory with writers is in
[RQGM Architecture](rqgm_architecture.md#records-on-the-checkpoint), exact
formats in the [File Formats Reference](../reference/file_formats.md)):

```text
{checkpoint}/
├── rqgm_state.json               # mode provenance (written at boot, before node 1)
├── constitution.yaml             # human-readable copy; hash pinned in meta.json
├── rqgm_transitions.jsonl        # event-log truth: founding + boundary transactions
├── epoch_state.json              # frozen open-epoch snapshot (fingerprint excludes timestamps)
├── rqgm_registry.json            # registry snapshot replayed from the transitions log
├── rqgm_audit.jsonl              # hash-chained audit log (all facades append here)
├── rqgm_adversarial_cases.jsonl  # raw/defense/judgment/validated records + round markers
├── rqgm/adversarial_replay_pool.json
├── proposals/                    # proposal_records.jsonl + proposal_index.json
├── rqgm_prompts/                 # write-once evolved prompt bodies (B7+; hash-verified)
└── prompt_trace.jsonl            # every rendered prompt, stamped with prompt_version
```

`meta.json` additionally records the `constitution_hash` (currently
`5e455c17da51`) — the pin over all kernel rule tables. Constitutional
amendments are deliberate, hand-made re-pins: a rule-table edit fails
`tests/test_rqgm_kernel.py` until the expected hash is re-pinned with a
dated comment. The recent chain walks the amendments:
`… → 951a294dc3c4` (T20, the `utility_policy` supersession edge and the
`CK-UTL-*` rules) `→ 564a204dc694` (the paper founding roles) `→
6643c12a510e` (T21, the paper-role shadow-standby edge) `→ 2edf93776904`
(#78b, adding `governance_judge` to the role vocabulary so the impeachment
judge is itself a governed, sanctionable actor) `→ 5e455c17da51` (Tasks
16–19, adding the fixed Knowledge/Capability/Harness roles, resource matrix,
and `CK-KNW-*` / `CK-CAP-*` / `CK-HAR-*` integrity rules).

## How to observe a run

The two files worth `tail -f`-ing are `rqgm_audit.jsonl` (what governance
is deciding) and `rqgm_transitions.jsonl` (when the institution changes):

```bash
tail -f {checkpoint}/rqgm_audit.jsonl | python3 -c \
  'import json,sys; [print(json.loads(l)["event_type"], json.loads(l)["payload"].get("node_id","")) for l in sys.stdin]'
```

`rqgm_transitions.jsonl` uses a **closed** event vocabulary
(`ari/rqgm/events.py`); `rqgm_audit.jsonl` is open but these are the types
you will actually see:

| File | `event_type` | Meaning | Emitted by |
|---|---|---|---|
| transitions | `epoch_transaction_prepare` / `epoch_transaction_commit` | transaction brackets; anything between them is atomic on replay | `RqgmStateStore` (founding: `RQGMRuntime`; boundary: `RegistryTransitionEngine`) |
| transitions | `prompt_registered` / `component_registered` | founding registration payloads | `RQGMRuntime._register_founding` |
| transitions | `prompt_status_change` / `component_status_change` | a resolved T1–T21 edge (adoption, sanction, retirement) | `RegistryTransitionEngine` |
| transitions | `epoch_close` / `epoch_open` | boundary: old epoch closes, new frozen epoch opens | `RegistryTransitionEngine` / `RqgmStateStore` |
| transitions | `emergency_quarantine` | T16 quarantine inside a forced emergency boundary | `RegistryTransitionEngine` |
| audit | `governance_level` | per-node ladder level (L0–L3) + triggers | `GovernanceBudgetManager` |
| audit | `budget_consumed` | a governance decision point spent budget | `GovernanceBudgetManager` |
| audit | `raw_attack` / `defender_response` / `judgment_record` / `validated_attack` / `utility_record` | one adversarial round, record by record | adversarial loop |
| audit | `governance_report` (+ per-record motion/defense/adjudication lines) | the epoch audit and its outcome | `GovernanceOrchestrator` |
| audit | `epoch_transition` | the committed transition, with report hash in `inputs` | `RegistryTransitionEngine` |
| audit | `kernel_report` / `constitutional_violation` | warn-and-flag findings / rule violations (`CK-*` codes) | `ConstitutionalKernel` adapters |
| audit | `selective_erasure` / `frontier_rebuild` | logical erasure + rebuild after retirements | `FrontierRepairEngine` |
| audit | `prompt_candidate_rejected` | a candidate failed a lifecycle stage | prompt-evolution pipeline |
| audit | `prompt_evolution_skipped` | boundary candidate minting disabled (`rqgm.prompt_evolution.enabled: false`) | `RQGMRuntime` boundary prompt evolution |
| audit | `clean_room_violation` | a contaminated clean-room bundle was blocked | `CleanRoomCoordinator` |
| audit | `meta_evolution` | boundary meta-step summary: outcome `proposed`/`no_op` (or a skip/failure reason), counts, skipped invokers | `MetaEvolutionCoordinator` (skip/failure lines: `RQGMRuntime`) |
| audit | `meta_evolution_skipped` / meta output lines | the disabled-path meta skip / per-output records | `MetaEvolutionCoordinator` |

Three quick health checks on any checkpoint:

- `python3 -c "import json;print(json.load(open('rqgm_registry.json'))['registry_version'])"` —
  the registry snapshot exists and replayed cleanly.
- `grep -c epoch_open rqgm_transitions.jsonl` — how many epochs opened.
- The last line of `rqgm_audit.jsonl` has a `prev_event_hash` equal to the
  previous line's `event_hash` — the chain is intact (resume verifies the
  whole chain automatically).

---

## See also

[RQGM Architecture](rqgm_architecture.md) ·
[Execution Modes](../guides/execution_modes.md) ·
[RQGM Evaluation and Ablation](../guides/rqgm_evaluation.md) ·
[RQGM Schema Reference](../reference/rqgm_schemas.md) ·
[File Formats Reference](../reference/file_formats.md) ·
[BFTS algorithm](bfts.md)
