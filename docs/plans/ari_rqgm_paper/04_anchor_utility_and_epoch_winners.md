# Task 04: Anchor Utility and Epoch Winners

> **Status**: planned · **Depends on**: 00, 03, ../ari_rqgm/10, ../ari_rqgm/13, ../ari_rqgm/14 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

The co-evolving `paper_reviewer` (promoted to a governed EVALUATOR role in
[03_writer_reviewer_governed_roles.md](03_writer_reviewer_governed_roles.md)) needs a
utility signal that does **not** reduce to "the reviewer approves of itself". In the RQGM
paper this is the APReS ground truth: evaluators earn trust by agreeing with a held-out,
human-labelled accept/reject anchor set; generators (writers) have no such anchor in the paper's
*paper-writing* domain and are therefore only ever ranked *within* an epoch by the currently-trusted
evaluator. ARI's writer, however, writes about experiments that were actually RUN, so it IS anchored
— to the Layer-0 claim-evidence gate (§5.1, revised 2026-07-16), the paper's *coding*-domain shape.
This task designs both anchors for the paper-archive path:

- an **APReS-equivalent ground-truth anchor corpus** — reference manuscripts labelled
  `accept` / `reject` — that lives at `rqgm.paper.anchor.corpus_path`;
- the **held-out agreement metric** that scores a `paper_reviewer` candidate on how well its
  verdicts match the anchor labels over a fixed held-out sample of `rqgm.paper.anchor.sample_size`
  cases, riding the EXISTING candidate-lifecycle `anchor_evaluation` stage and `AnchorBoard`;
- the **writer faithfulness anchor** (§5.1): the Layer-0 claim gate deterministically scores the
  ACTIVE writer's drafts, the score lands on the AnchorBoard keyed on the writer's `prompt_hash`,
  and a REGRESSION is a real sanction source that opens the writer role — so the writer PROMPT
  co-evolves via the existing T6, while its **DRAFT** winners stay **epoch-local** (ranked only by
  the in-epoch-frozen `paper_reviewer`, never cross-epoch-comparable, §5.6);
- the **utility-policy freeze**: the anchor corpus digest, the held-out split, and the agreement
  metric are captured into a `paper_utility_policy` that is frozen into the paper epoch
  fingerprint, mirroring `capture_utility_policy`
  ([Governed utility evolution](../../concepts/rqgm_architecture.md#governed-utility-evolution)) /
  `epoch_fingerprint` ([Id and hash discipline](../../reference/rqgm_schemas.md#id-and-hash-discipline));
- how anchor scoring **rides selective erasure and best-belief**: reviewer retirement stales the
  draft utilities that reviewer produced (via the topology-agnostic logical-erasure closure,
  [RQGM Architecture → Key invariants](../../concepts/rqgm_architecture.md#key-invariants) invariant 6),
  and best-belief draft selection consumes only non-stale, in-epoch-frozen utilities.

This task **RESOLVES the anchor half of Q-49** ("ARI's ground-truth anchor definition and
curation") left open in [../ari_rqgm/00_current_ari_investigation.md](../ari_rqgm/00_current_ari_investigation.md)
§5.9 and routed to Task 13. The *per-epoch output versioning* half of Q-49 is resolved by
[02_paper_draft_archive_search.md](02_paper_draft_archive_search.md) (drafts are archive nodes,
not overwrites of `full_paper.tex`); Task 13's own resolution stands ("no per-epoch versioning
of the linear pipeline outputs"). Corpus curation is the **irreducible data cost** of this
feature; §5.9 states it plainly and gives a minimal bootstrap so the plan is buildable without
a large hand-labelled corpus on day one.

## 2. Scope

- The `rqgm.paper.anchor.{corpus_path, sample_size, enabled, max_bootstrap_label_fraction}` config
  block and its typed home under the paper RQGM subtree (§5.7, §6.4).
- The `paper_anchor_corpus.jsonl` schema — accept/reject-labelled reference manuscripts, each
  declaring a REQUIRED `label_source` — and its checkpoint registration (§6.1).
- The deterministic **held-out split** and per-epoch anchor sampling (fixed for the run, P2-pure),
  and the **machine-enforced bootstrap-label cap** that keeps the corpus from becoming ARI's own
  self-certification (§5.3).
- The **agreement metric** that turns a `paper_reviewer` verdict + an anchor label into a boolean
  case result. *(Corrected 2026-07-17: this is NOT wired into a live
  `CandidateValidationPipeline` `anchor_evaluation` stage — that class is instantiated nowhere in
  production. For paper candidates the metric is computed by `score_reviewer_on_anchor` inside
  `PaperArchiveRuntime._paper_candidate_evaluator` and emitted as the candidate's `anchor_score`;
  see 05 §5.5. This §'s references to the `anchor_evaluation` stage / `AnchorBoard` as the LIVE
  mechanism describe the intended-but-unbuilt pipeline path, not what runs.)* (§5.3, §5.4).
- The `paper_utility_policy` payload + hash and its freeze into the paper epoch fingerprint (§5.5).
- The writer's faithfulness anchor (§5.1) and the epoch-local DRAFT-winners rule with its
  comparability consequence (§5.6).
- How reviewer retirement + best-belief selection interact with anchor evidence (§5.7, §5.8).
- The Q-49 anchor-half resolution and the corpus bootstrap policy (§5.9).

## 3. Non-goals

- **The archive search substrate.** `PaperArchiveStrategy`, the draft NodeExecutor, and
  `paper_draft_archive.jsonl` belong to [02_paper_draft_archive_search.md](02_paper_draft_archive_search.md);
  this task consumes drafts-as-nodes, it does not design the search.
- **The `paper_reviewer` role definition itself.** The constitutional amendment (promote
  `paper_writer`, add `paper_reviewer`, capability matrix, context views incl. the `anchor_case`
  view field, founding prompts, `CONSTITUTION_HASH` re-pin) is
  [03_writer_reviewer_governed_roles.md](03_writer_reviewer_governed_roles.md). This task only
  supplies the CONTENT that fills the reviewer's `anchor_case` view during anchor scoring and the
  utility signal that ranks reviewer candidates.
- **The `paper_self_preference` adversary and the AI/human paper corpus.** That is
  [05_adversarial_self_preference.md](05_adversarial_self_preference.md); the anchor corpus here
  is a *labelled-quality* corpus (accept/reject), distinct from the AI-authorship corpus there.
- **The selective-erasure engine.** Reused verbatim
  ([RQGM Architecture → Key invariants](../../concepts/rqgm_architecture.md#key-invariants) invariant 6;
  [Frontier-repair schemas](../../reference/rqgm_schemas.md#frontier-repair-schemas-task-10));
  this task only states which paper records ride its closure.
- **The paper mode switch / runtime construction.** `paper.mode`, `PaperMode`,
  `resolve_paper_mode`, `PaperArchiveRuntime`, and `paper_archive_state.json` ownership are
  [01_paper_execution_mode.md](01_paper_execution_mode.md); this task only adds anchor-provenance
  fields to that file.
- **Cost accounting.** Anchor-scoring token budgets ride
  [06_cost_control_and_budget.md](06_cost_control_and_budget.md) and the inherited
  `GovernanceBudgetManager`; this task states only that anchor scoring is sampled and cached.
- **Any change to `linear` mode**, the exploration `reviewer` (peer_review), or the exploration
  AnchorBoard (which is unpopulated in v1).

## 4. Existing ARI touchpoints

All paths repo-relative. Verified against branch `RQGM` (ari-core v0.9.1).

| Touchpoint | File / symbol | Why it matters here |
|---|---|---|
| Deterministic anchor board (REUSE) | `ari-core/ari/rqgm/governance/_adjudication.py` — `board_score` (line 59), `anchor_cases` (98), `evaluate_candidates` (267), `BOARD_HIGH`/`BOARD_LOW` (34-35), `CANDIDATE_PASS_THRESHOLD` (38) | `anchor_cases(pool)` = `getattr(pool, "anchor_cases", None)` — a pool-shaped seam that is **absent (None) on every v1 exploration pool**. The paper anchor corpus becomes exactly this `anchor_cases` source; `board_score` (mean over cached case results, sorted by `case_id`, deterministic) scores the reviewer with zero new scoring code. |
| Candidate anchor stage (REUSE) | `ari-core/ari/rqgm/prompt_evolution.py` — `STAGES` incl. `"anchor_evaluation"` (94), `CandidateValidationPipeline._case_evaluation` (906), the `anchor_evaluation` branch (826-834) with `ties_favor_incumbent=True`, the empty-set "pass with zero coverage" rule (924-927) | This is the co-evolution gate a `paper_reviewer` candidate must pass. `_case_evaluation` calls an injected `case_evaluator(candidate, case) -> bool` over the anchor cases and reports `anchor_pass_rate`. The paper anchor evaluator is the §5.4 agreement function; the empty-corpus branch is the degraded on-ramp. |
| Utility-policy freeze (MIRROR) | `ari-core/ari/rqgm/state.py` — `capture_utility_policy` (354), `epoch_fingerprint` (276), `freeze_epoch` (340), `EpochState.utility_policy` (241) | `EpochState` freezes the scoring policy into a `hash12` fingerprint that excludes wall-clock (P2). `capture_paper_utility_policy` (§5.5) mirrors this exactly, adding the anchor corpus digest / split / agreement-metric id / label-source mix, and the paper epoch fingerprint is built the same way. Since Task 14 `capture_utility_policy` (`state.py:354`) resolves the ADOPTED policy from the registries with a cfg fallback, so the frozen policy is epoch-varying — the method-wide constancy gap closed by [../ari_rqgm/14](../ari_rqgm/14_governed_utility_evolution.md) and INHERITED here (§5.5), never re-implemented paper-side. |
| Cross-epoch replay caching (REUSE) | `ari-core/ari/rqgm/governance_cache.py` — `replay_lookup_key` (98), `case_origin_epoch` (86), `GovernanceCache` (122); consumed by `_adjudication._cached_board_score` (215) | The cache key carries `prompt_hash`, so a reviewer candidate's anchor score is keyed to **that reviewer's hash**: anchor evidence never leaks across reviewer versions, which is why retiring a reviewer does not require re-scoring the anchor set for its successor. `use_cached_results` (defaults.yaml line 53) keeps repeat anchor scoring free. |
| Held-out anchor pool seam (REUSE) | `ari-core/ari/rqgm/adversarial/pool.py` — `AdversarialReplayPool` (183), `admit` (212), `cases` (366), `save_snapshot` (404); the `anchor_cases` attribute is simply absent today | The paper anchor corpus is exposed through a small pool-like object carrying `.anchor_cases` (and an empty `.cases`), so it plugs into `anchor_cases(pool)` / `board_score` and `CandidateValidationPipeline(anchor_cases=...)` with no change to either. |
| Selective erasure closure (REUSE) | `ari-core/ari/rqgm/frontier_repair.py` — prompt-hash dependency closure, `_pending_anchor` (789), `_latest_utility` (804) + [Key invariants](../../concepts/rqgm_architecture.md#key-invariants) invariant 6 / [Frontier-repair schemas](../../reference/rqgm_schemas.md#frontier-repair-schemas-task-10) | Topology-agnostic: the paper draft archive is a best-first draft tree ([02](02_paper_draft_archive_search.md) §5.1, `archive.depth` default 3), so draft `ReviewRecord`/`UtilityRecord`s produced by a retired `paper_reviewer` are staled by the identical closure at any depth. Anchor evidence for the retired reviewer is not reused (keyed on its `prompt_hash`; P-D "erase, don't re-scale"). |
| Best-belief selection precedent | `ari-core/ari/pipeline/verified_context.py` — `select_best_node` (36), `_scientific_score` (20) | The paper entry already picks the best node here for `run_paper_candidate_escalation`. Best-belief draft selection (owned by [02](02_paper_draft_archive_search.md)) is the archive analog; this task pins that it consumes only non-stale, in-epoch-frozen draft utilities (§5.8). |
| Reviewer verdict surface | `ari-skill-paper/src/prompts/academic_reviewer.md` — `accept_recommendation ∈ {strong_accept, accept, weak_accept, reject}` (line 7) | The exact output field the anchor agreement metric compares against a corpus label. The seed prompt is LIFTED into the governed `paper_reviewer` founding prompt by [03](03_writer_reviewer_governed_roles.md); this task fixes the accept/reject binarization (§5.4). |
| Reviewer anchor-case view | `ari-core/ari/rqgm/kernel_rules.py` — `CONTEXT_VIEW_WHITELISTS` (234), `constitution_hash` (292), `CONSTITUTION_HASH` (304) | [03](03_writer_reviewer_governed_roles.md) adds the `paper_reviewer` row whose view includes `reference_context/anchor_case`; this task owns the CONTENT of that `anchor_case` field (one reference manuscript + no leakage of its label). No `CONSTITUTION_HASH` change is authored here. |
| Replay/anchor case sizing | `ari-core/ari/configs/defaults.yaml` — `rqgm.replay.max_cases_per_epoch: 8` (51), `use_cached_results: true` (53); `ari-core/ari/config/__init__.py` — `RQGMReplayConfig` (410), `RQGMConfig` (1039) | `sample_size` reuses this sizing idiom; the `rqgm.paper.anchor` block is a typed subsection of the paper RQGM config the same way `RQGMReplayConfig` is of `RQGMConfig`. |
| Checkpoint registration | `ari-core/ari/paths.py` — `PathManager.META_FILES` (404); `ari-core/ari/orchestrator/node_report/builder.py` — `_INTERNAL_JSON_NAMES` (327) | `paper_anchor_corpus.jsonl` (and any anchor result snapshot) must be registered here or it contaminates node work dirs — the exact pattern used for `epoch_state.json` / `rqgm_erasure_state.json`. |
| Ablation / metric consumer | [Failure injections](../../guides/rqgm_evaluation.md#failure-injections) (injection 5 "Judge bias" → AnchorBoard; the held-out `eval_*` namespace disjoint from the reserved `adv_*` / `anchor_*` prefixes) and [Metrics](../../guides/rqgm_evaluation.md#metrics) (4–8 detection quality, incl. validated-attack precision) | The evaluation harness already holds the eval set disjoint from `anchor_*` cases and audits judge/reviewer bias against anchor verdicts. The paper anchor corpus is the paper-phase instance of that anchor namespace; this task keeps the held-out sample disjoint from any eval fixture. |

## 5. Proposed design

### 5.1 The anchor asymmetry (why only the reviewer is anchored)

The RQGM governance layer trusts an evaluator to the extent it agrees with ground truth, and
trusts a generator only through the evaluator. ARI already implements exactly this for
exploration: the candidate lifecycle's `anchor_evaluation` stage
(`ari/rqgm/prompt_evolution.py:826`) scores an evaluator candidate against a "fixed held-out
anchor set … never generated by evolving components" — the corpus is written once by
curation/bootstrap tooling and **never** by a governed role, "a fixed ground truth, not an
evolvable artifact"
([`paper_anchor_corpus.jsonl`](../../reference/rqgm_schemas.md#paper-anchor-corpus-jsonl-—-the-read-only-accept-reject-anchor))
— and the `AnchorBoard` (`ari/rqgm/governance/_adjudication.py`) bounds what the
LLM `GovernanceJudge` may conclude
([The audit's determinism budget](../../reference/rqgm_schemas.md#the-audit-s-determinism-budget)).
**We reuse this machinery unchanged and only supply a paper-phase anchor corpus.**

Decision — BOTH roles are anchored (revised 2026-07-16; supersedes the earlier "mirror the
paper's anchor-less writer" decision):

- **`paper_reviewer` is anchored** to the APReS-equivalent accept/reject corpus (§5.2). Its utility
  across epochs is its held-out agreement with that human ground truth. A reviewer that disagrees
  with the corpus loses trust and is a candidate for probation/retirement through the EXISTING
  `RegistryTransitionEngine` + `GovernanceOrchestrator` (wired by
  [03](03_writer_reviewer_governed_roles.md), reused unchanged —
  [RQGM Architecture → The four facades](../../concepts/rqgm_architecture.md#the-four-facades)).
- **`paper_writer` is ALSO anchored** — to a ground truth the RQGM paper's writer never had. The
  earlier decision copied the paper's *paper-writing* domain, where the writer writes from APReS
  titles/abstracts with no experiment to be faithful to, so "there is no correct manuscript" holds.
  **But ARI writes about experiments that were actually RUN**, and the claim-evidence hard gate
  (`ari-core/ari/pipeline/claim_gate/gate.py`) already verifies a manuscript's claims against those
  results **deterministically**, emitting `execution_grounded_claim_rate` (:361),
  `numeric_claim_reproducible_rate` (:365) and `numeric_coverage_rate` (:368). Run per draft via
  `run_hard_gate(write=False)` on the draft's `.tex`, these are a **faithfulness anchor**: a
  manuscript that overclaims or misreports the verified findings is objectively worse, independent
  of any evolving reviewer. So ARI's paper writer is the analogue of the RQGM paper's **coding
  domain** (a coder anchored to executable Polyglot tests *and* scored by a co-evolving code
  reviewer), NOT its anchor-less paper-writing domain.
- **The writer utility is a composite:** the faithfulness anchor (objective, claim gate) AND the
  co-evolving `paper_reviewer` score (subjective quality — clarity, narrative, novelty). Faithfulness
  ALONE would reward a dry, over-hedged paper that passes the gate but reads poorly; the co-evolving
  critic supplies the quality axis the gate cannot. This is exactly the coding domain's
  tests-plus-reviewer structure.
- **The writer therefore CO-EVOLVES through the existing governed path** (no new transition edge —
  contrast `utility_policy`'s T20). The faithfulness anchor is a real SANCTION SOURCE: a writer whose
  drafts regress on the deterministic claim-gate metrics is sanctionable — either through the
  existing overclaim / evidence_gap adversaries (which already attack claims not grounded in
  evidence; giving them a `_AFFECTED_ROLES_BY_TYPE` row targeting `paper_writer` for paper-draft
  artifacts closes Task-15's chain for the writer too) or through a reliability signal keyed on the
  deterministic faithfulness score. That sanction opens the writer role, and the writer successor
  candidate — which today climbs to `shadow` and then WAITS forever for want of an opening — adopts
  via the EXISTING T6. The `paper_writer` PROMPT genuinely co-evolves.
- **The claim gate stays Layer-0** (plan 04 / [07](07_claim_gate_handoff_and_evaluation.md)): RQGM
  READS its deterministic findings offline/read-only as a signal — exactly as the adversarial
  pre-signals already do via `run_hard_gate` in `adversarial/engine.py` — and never wraps or evolves
  it. The curated *human* accept/reject corpus is still needed only for the reviewer; the writer's
  anchor is the gate ARI already computes for free, so the added data cost is zero.

**Implementation status (2026-07-16): LANDED and proven by execution.** `paper_anchor.py` now
carries `WRITER_ANCHOR_DESCRIPTOR` (metric `claim_evidence_faithfulness_v1`) in place of the interim
`writer_anchor: None`, `writer_faithfulness_score` folds the gate's three rates, and
`PaperAnchorPool.record_writer_faithfulness` LANDS that score on the AnchorBoard — the step that
makes the anchor operative rather than merely computed. (The dead seam was exactly this: the score
was computed and discarded, so `board_score(anchor_cases(pool), writer_keys)` returned `None`,
`_bounded_outcome` could not clamp, and every writer motion was dismissed "in favor of the
incumbent".) `_AFFECTED_ROLES_BY_TYPE["paper_self_preference"]` names both roles and the round emits
one validated attack per resolvable role. Observed: the active writer `prompt_hash` moves
`f38a15f0f140 → b2c36f9a8232` over 8 rounds (4 flat, then adopted); the causal control (claim-gate
faithfulness forced to 1.0) yields zero writer attacks, zero writer motions and a constant hash while
the reviewer is still attacked and impeached.

Two implementation decisions worth preserving:

- **The writer's faithfulness case is keyed on `prompt_hash` ALONE, never `component_id`.** One
  component id spans successive prompt versions (an adoption rewrites the prompt, not the component),
  so a component-keyed score would leak the incumbent's faithfulness onto its successor and make the
  fresh writer instantly impeachable. Same rule `replay_lookup_key` applies to the reviewer (P-D).
- **The writer's evidence is a SEPARATE case type** (`PaperWriterFaithfulnessCase`), never a writer
  result stamped onto a reference-manuscript case, and `reviewer_anchor_cases` filters the corpus
  cases IN for every reviewer-side consumer. Stamping would have been cheaper but would make
  `anchor_refs` cite a manuscript the writer never wrote — a forged evidence citation. (`grep -rn
  _emit_anchor_attack ari-core/ari` stays empty: no manufactured records.)

**Honest nuances that remain.** (a) The writer adopts only on a REGRESSION — a better challenger
alone never displaces a faithful incumbent; it waits at `shadow` (the conservative behavioral-role
model). (b) The writer's DRAFT winners are still epoch-local (§5.6) — only the PROMPT co-evolves
cross-epoch. (c) The writer-targeted attack rides the `paper_self_preference` round, which returns
early unless there is an over-accepted anchor case, so an unfaithful writer under a reviewer that
over-accepts nothing is not sanctioned today; a dedicated writer-adversary type remains a separate
decision. (d) The writer's faithfulness case lands on the anchor pool, so `anchor.enabled: false`
(the default on-ramp) gates the writer sanction too — even though the writer's own anchor needs no
curated data.

### 5.2 The anchor corpus (`paper_anchor_corpus.jsonl`)

A JSONL corpus of reference manuscripts with human accept/reject labels. One case per line,
sorted by `case_id` on write (deterministic `board_score` sampling depends on this order):

```json
{
  "case_id": "anchor_0007",
  "record_type": "PaperAnchorCase",
  "venue": "ICLR",
  "manuscript_ref": "anchor_corpus/iclr2023_1234.tex",
  "manuscript_sha256": "9f8e...c1",
  "ground_truth_label": "accept",
  "label_source": "human_curated",
  "split": "held_out",
  "origin_epoch_id": "anchor_static",
  "expected_behavior": {"accept_recommendation_binary": "accept"},
  "results": {}
}
```

- `ground_truth_label ∈ {accept, reject}` is the label the reviewer is scored against. It is the
  **binarization** of `academic_reviewer.md`'s four-level `accept_recommendation` (§5.4).
- `label_source ∈ {human_curated, gate_bootstrap}` is **REQUIRED** — it records *who authored the
  ground truth*. `human_curated` = a human labelled this case (Bootstrap B, §5.9); `gate_bootstrap`
  = the label was derived from ARI's own Layer-0 claim-gate outcome (Bootstrap A, §5.9), which is
  a weak proxy (gate pass ≠ venue accept, §10 R2). A case with a missing or unrecognized
  `label_source` is an integrity error and is rejected at load (§5.3) — there is no default,
  because "unlabelled provenance" is exactly the state that lets a self-labelled corpus pass as
  ground truth. This replaces the previously-undefined `source_recommendation` field, which is
  **dropped**: it duplicated `ground_truth_label` and no consumer read it.
  (It supersedes nothing else in the line schema; `authorship: human | ai` — the shared label
  dimension [05](05_adversarial_self_preference.md) §5.3 adds to this same corpus — is orthogonal
  and owned there.)
- `manuscript_ref` is a path under a corpus dir (kept out of node work dirs; §6.1) or, for tiny
  bootstrap sets, an inline `manuscript_text` field; `manuscript_sha256` pins content for the
  policy digest (§5.5).
- `split ∈ {train, held_out}` is assigned deterministically at load time (§5.3); the corpus author
  may pre-pin it, otherwise the loader computes it. Only `held_out` cases score the reviewer.
- `expected_behavior` matches the shape `_case_evaluation` already reads
  (`prompt_evolution.py:936-941`); `results` is filled with the per-subject agreement score during
  scoring so `board_score` (governance-adjudication path) works identically.
- `origin_epoch_id="anchor_static"` marks the corpus as a fixed, non-evolving source so
  `governance_cache.replay_lookup_key` caches anchor scores correctly across paper epochs
  (`case_origin_epoch` reads this field, `governance_cache.py:86`).

The corpus is **read-only** to every governed component: it is never authored, mutated, or
extended by an evolving role — written once by curation/bootstrap tooling, never by a governed
role ([`paper_anchor_corpus.jsonl`](../../reference/rqgm_schemas.md#paper-anchor-corpus-jsonl-—-the-read-only-accept-reject-anchor)).

### 5.3 Held-out split and per-epoch sampling (deterministic, P2)

Decision: the train/held-out split is **fixed for the whole run**, not re-drawn per epoch. This
is the only way anchor scores of `reviewer_vN` and `reviewer_vN+1` are comparable (they are scored
on the same held-out set), which is what lets the AnchorBoard rank successive reviewers at a
boundary.

```python
# planned: ari-core/ari/rqgm/paper_anchor.py
def assign_split(cases: list[dict], *, sample_size: int, corpus_digest: str) -> list[dict]:
    """Deterministically mark `sample_size` cases as held_out (the rest train).

    Pure: the choice is a hash of (case_id, corpus_digest) — no wall clock, no
    RNG state, no epoch input (P2; and epoch-independent so the held-out set is
    stable across the run). Cases with a pre-pinned `split` are honored as-is.
    """
    pinned = [c for c in cases if c.get("split") in ("train", "held_out")]
    free = [c for c in cases if c not in pinned]
    ranked = sorted(free, key=lambda c: hash12(f"{c['case_id']}:{corpus_digest}"))
    held = {c["case_id"] for c in ranked[:max(0, sample_size - _count_held(pinned))]}
    return [{**c, "split": ("held_out" if c["case_id"] in held else c.get("split", "train"))}
            for c in cases]
```

- `sample_size` (`rqgm.paper.anchor.sample_size`, default 8, reusing the `replay.max_cases_per_epoch`
  idiom) bounds the held-out set the reviewer is scored on per epoch — the cost knob. The same
  held-out cases are re-scored each epoch only for a *new* reviewer hash; cached hits make repeat
  scoring free (`use_cached_results`).
- The split identity `(corpus_digest, sample_size, held_out case-id set)` is frozen into the paper
  utility policy (§5.5); it cannot drift mid-run without changing the epoch fingerprint (a
  constitutional violation, exactly like a mid-epoch active-set change).
- **No leakage guard**: the `held_out` cases must be disjoint from anything the reviewer's founding
  prompt was distilled from and from Task 13's `eval_*` injection set. Enforced by a load-time
  assertion on `case_id` namespaces (`anchor_*` vs `eval_*`, mirroring the harness's own
  namespace-disjointness rule — [Failure injections](../../guides/rqgm_evaluation.md#failure-injections)).
- **Bootstrap-label cap (the corpus is itself an attack surface).** The anchor corpus is the
  evaluation of the evaluator — the single external ground the whole anti-collusion story stands
  on. A corpus that drifts to mostly `gate_bootstrap` labels silently redefines "fair reviewing"
  as "whatever ARI's own gate already passed", which is collusion with extra steps: the system
  becomes its own ground truth. §10 R2's "keep them a minority" is therefore **machine-enforced,
  not advisory**. After `assign_split`, the loader computes the `gate_bootstrap` fraction over
  **the whole corpus AND over the held-out subset** (the subset that actually scores the reviewer —
  a corpus that is 40% bootstrap overall can still be 100% bootstrap in the held-out sample) and
  compares both against `rqgm.paper.anchor.max_bootstrap_label_fraction` (default `0.5`, §6.4).
  Either breach ⇒ the corpus is refused: `load_anchor_corpus` logs and returns `None`, which is the
  §5.9 degraded on-ramp (reviewer not anchor-gated) — **never an exception into the run** (§7's
  never-raises contract). Refusing to anchor is strictly safer than anchoring on self-labels: the
  on-ramp merely withholds a trust signal, whereas a self-labelled anchor actively certifies the
  reviewer's own bias as ground truth and drives retirements with it.
- **Self-label integrity error (the acute case).** Any case with `label_source: gate_bootstrap` AND
  `ground_truth_label: accept` AND `authorship: ai` ([05](05_adversarial_self_preference.md) §5.3's
  shared dimension) is flagged at load: it is an ARI-authored draft that ARI's own gate passed and
  that ARI then labelled `accept` — a closed self-labelling loop. Such a case teaches the reviewer
  to accept exactly the AI-authored acceptance that [05](05_adversarial_self_preference.md)'s
  `replay_evaluation` pool trains it to reject, so the two mechanisms would cancel. Decision: these
  cases are **excluded from `held_out`** (train-only, so they may shape a corpus but can never
  score the reviewer) **and** counted against the corpus-level cap. The check is pure — labels
  only, no LLM, no wall clock, no network, no gate artifact re-read (P2).
- Rejected alternative: make *all* `gate_bootstrap` cases train-only. It is cleaner, but it reduces
  a pure Bootstrap-A corpus to the on-ramp (zero held-out cases ⇒ zero coverage ⇒ no anchor gate) —
  which is arguably the honest outcome and is what the cap produces anyway at fraction `1.0`. The
  cap is chosen instead because it keeps a *mixed* corpus (the realistic Bootstrap A + B path)
  usable while still bounding how much of the ground truth ARI is allowed to author.

### 5.4 The agreement metric (reviewer verdict vs anchor label)

The `case_evaluator` injected into the `anchor_evaluation` stage for `paper_reviewer` candidates:

```python
# planned: ari-core/ari/rqgm/paper_anchor.py
_ACCEPT = {"strong_accept", "accept", "weak_accept"}   # academic_reviewer.md:7 four-level scale
_REJECT = {"reject"}

def binarize_recommendation(rec: str) -> str | None:
    r = (rec or "").strip().lower()
    if r in _ACCEPT:
        return "accept"
    if r in _REJECT:
        return "reject"
    return None                       # unparseable => treated as a miss (conservative)

def paper_reviewer_agreement(candidate_verdict: dict, case: dict) -> bool:
    """`case_evaluator(candidate, case) -> bool`: did the reviewer candidate's
    accept/reject verdict on this reference manuscript match the anchor label?"""
    got = binarize_recommendation(str(candidate_verdict.get("accept_recommendation", "")))
    want = str(case.get("expected_behavior", {}).get("accept_recommendation_binary")
               or case.get("ground_truth_label", ""))
    return got is not None and got == want
```

**The label is never an input — enforced structurally (recorded 2026-07-17).** §4's anchor-case view
row ("one reference manuscript + **no leakage of its label**") and §10 R4 are now enforced by
construction rather than by convention:

* `anchor_case_view(case)` (`paper_anchor.py`) is the ONLY thing any verdict source receives. It is a
  whitelist — `case_id`, `venue`, `manuscript_ref`, `manuscript_sha256`, `manuscript_text` — so
  `ground_truth_label`, `expected_behavior`, `label_source`, `split`, `results` and `authorship` (an
  ai/human tag correlates with the label in an AI-vs-human corpus) do not EXIST in the dict the judge
  reads; `case["ground_truth_label"]` raises `KeyError`. Asking a judge not to look is not a control
  when its utility IS agreement with what it is looking at.
* `GovernedPaperReviewer.anchor_verdict` previously fell back to
  `if "reject" in self.prompt_text.lower(): return str(case.get("ground_truth_label", "reject"))`.
  The founding `paper_reviewer` prompt contains "reject" inside its own output-schema enumeration, so
  the branch **always fired** and the verdict WAS the answer key: `paper_reviewer_agreement` then
  compared the label against itself and agreement was **1.0 by construction**. Since production
  (`cli/projects.py:219`) injects no `reviewer_verdict_fn`, this was the production path — the anchor
  measured nothing and the self-preference round, which reads the same verdicts, never armed.
* It is deleted. `verdict_fn is None` ⇒ `anchor_verdict` returns `None` = **NO VERDICT SOURCE / zero
  coverage**, never a forged verdict (§5.3: "refusing to anchor is strictly safer than anchoring on
  self-labels"; §5.9: "the honest response is to have no anchor rather than a captured one").
* **`None` is an absence, not a miss.** `binarize_recommendation(str(None))` → `"None"` →
  unparseable → a MISS scoring 0.0, so scoring a `None` would turn "nothing was wired" into a 0.0
  anchor board and drive impeachment on evidence nobody produced — inverting the bug into false
  impeachment. Every caller therefore SKIPS: `score_reviewer_on_anchor` (accuracy is over the cases
  actually judged; all-abstain ⇒ `(None, [])`), `PaperArchiveRuntime._score_reviewer_on_anchor` (no
  `total`, no board result, no `review_record`), and `paper_self_preference._reviewer_accepts`
  (`None` ⇒ `False` — no verdict is not an over-acceptance; its `except: rec = "accept"` forged one).

**Residual:** with the fallback gone and no LLM-backed verdict wired (doc 03 §5.8's residual), the
production paper anchor now reports **zero coverage** rather than a fabricated 1.0. That is the §5.9
on-ramp behaving as specified — the anchor is *withheld*, not forged — but it means the paper
adversarial layer stays disarmed in production until a real verdict source is injected. The absence
is now visible instead of masked by a perfect score.

- The stage's reported `anchor_pass_rate` (`_case_evaluation`, `prompt_evolution.py:914`) is the
  reviewer's **held-out accuracy** — the paper-phase APReS utility. `ties_favor_incumbent=True`
  is set by the existing `anchor_evaluation` branch (line 834), so a tie on anchors keeps the
  incumbent reviewer (paper-faithful; "fixed anchor set; ties favor the incumbent" —
  [RQGM Runtime Walkthrough → Prompt evolution](../../concepts/rqgm_runtime_walkthrough.md#_7-prompt-evolution-—-candidates-crawl-the-rte-adopts)).
- The same boolean, cached as a 0/1 score keyed on `(case, reviewer prompt_hash)` via
  `replay_lookup_key`, feeds `AnchorBoard.board_score` when a reviewer impeachment/adoption motion
  is adjudicated — so the governance path and the lifecycle path agree by construction.
- **Binarization decision**: `strong_accept/accept/weak_accept → accept`, `reject → reject`. The
  boundary at "weak_accept" matches conference semantics (weak-accept papers are accepted). An
  unparseable verdict is a miss (never silently counted as agreement) — conservative, and it
  penalizes reviewers that violate the output schema.
- **Metric id** `binary_accept_reject_v1` is frozen into the utility policy (§5.5) so a future
  metric change (e.g. a three-way scale) is a versioned, fingerprint-visible policy change.

### 5.5 Utility-policy freeze in the epoch fingerprint

The paper phase runs on the same epoch machinery as exploration (topology-agnostic governance);
the analog of `EpochState.utility_policy` is a `paper_utility_policy` captured at paper-epoch open
and frozen into the paper epoch fingerprint (container = `paper_archive_state.json`, owned by
[01](01_paper_execution_mode.md)):

```python
# planned: ari-core/ari/rqgm/paper_anchor.py  (mirrors state.py:capture_utility_policy)
def capture_paper_utility_policy(
    cfg,
    *,
    corpus_digest: str,
    held_out_ids: list[str],
    label_source_mix: dict[str, int],
    held_out_label_source_mix: dict[str, int],
) -> dict:
    a = getattr(getattr(getattr(cfg, "rqgm", None), "paper", None), "anchor", None)
    policy = {
        "reviewer_score_source": "paper_reviewer",   # who provides draft utility (§5.1)
        # LANDED as WRITER_ANCHOR_DESCRIPTOR (§5.1, revised 2026-07-16), superseding the
        # interim `None`: the writer IS anchored to the Layer-0 claim gate, and the epoch
        # fingerprint records WHAT it is anchored to (metric id + source + component rates
        # + threshold), so a future metric change is a versioned, diffable policy change.
        "writer_anchor": dict(WRITER_ANCHOR_DESCRIPTOR),
        "anchor_enabled": bool(getattr(a, "enabled", False)),
        "anchor_corpus_digest": corpus_digest,         # hash12 of sorted case (id, sha256) pairs
        "anchor_sample_size": int(getattr(a, "sample_size", 8)),
        "anchor_held_out_ids": sorted(held_out_ids),   # the frozen held-out identity
        # WHO AUTHORED THE GROUND TRUTH (§5.3). Counts, not fractions: the cap is
        # recomputable from them and a mix shift is visible in the hash.
        "anchor_label_source_mix": {                    # over the whole corpus
            k: int(label_source_mix.get(k, 0))
            for k in ("human_curated", "gate_bootstrap")
        },
        "anchor_held_out_label_source_mix": {          # over the scoring subset
            k: int(held_out_label_source_mix.get(k, 0))
            for k in ("human_curated", "gate_bootstrap")
        },
        "anchor_max_bootstrap_label_fraction": float(
            getattr(a, "max_bootstrap_label_fraction", 0.5)
        ),
        "agreement_metric": "binary_accept_reject_v1",
        "ties_favor_incumbent": True,
    }
    policy["paper_utility_policy_hash"] = hash12(canonical_json(policy))
    return policy
```

- Frozen at paper-epoch open, exactly like `freeze_epoch` (`state.py:340`), and hashed with the
  same `canonical_json` + `hash12` discipline (P2: no wall clock). The paper epoch fingerprint
  therefore changes iff the corpus, the held-out sample, the sample size, the metric, **or the
  label-source mix** changes — making an accidental mid-run anchor swap a kernel-visible
  epoch-invariance violation (`CK-EPO-002` analog).
- **Why the mix is in the hash, not just in a log.** `anchor_corpus_digest` already moves when the
  corpus content changes, but it says nothing about *who authored the labels*: a digest change
  looks identical whether a human added 10 curated cases or the Bootstrap-A importer added 10
  self-labelled ones. Freezing the counts makes the ground truth's provenance a first-class,
  fingerprinted property of the epoch — the fingerprint moves when the ground truth becomes more
  self-labelled, so "the anchor quietly became ARI grading its own homework" cannot happen without
  a visible, diffable epoch-identity change. The cap (§5.3) refuses the corpus; the mix makes even
  a legal, under-cap drift auditable after the fact.
- **Within-epoch freeze (global invariant "within-epoch freeze")**: for the duration of a paper
  epoch the active `paper_writer`/`paper_reviewer` hashes AND this policy are immutable;
  co-evolution happens only at boundaries through the reused `RegistryTransitionEngine` +
  `ConstitutionalKernel`. This is the direct paper analog of the exploration active-set freeze
  ([RQGM Architecture → Key invariants](../../concepts/rqgm_architecture.md#key-invariants) invariant 1;
  [the institution freezes](../../concepts/rqgm_runtime_walkthrough.md#_3-epoch-000-opens-—-the-institution-freezes)).
- **Cross-epoch REWRITE of this policy rides [../ari_rqgm/14](../ari_rqgm/14_governed_utility_evolution.md), not this doc.**
  `capture_utility_policy` (`ari-core/ari/rqgm/state.py:354-382`) now resolves the ADOPTED
  `utility_policy` entry from the registries, falling back to the resolved cfg only at epoch 0 /
  `simple_bfts` / a pre-14 resume — so `utility_policy_hash` changes across epochs exactly when the
  score is genuinely rewritten through the governed path, and this mirror inherits THAT. (Before
  Task 14 the function read only the statically resolved cfg and its docstring recorded the
  constancy — "in v1 the frozen policy is constant across epochs within a run (status quo B-17);
  per-epoch re-weighting is a Task 10/13 decision"; that text no longer exists.) The constancy was a
  **method-wide** gap (the exploration phase had it identically), closed ONCE at the parent level by
  [../ari_rqgm/14_governed_utility_evolution.md](../ari_rqgm/14_governed_utility_evolution.md),
  which makes `utility_policy` a governed, boundary-rewritable artifact. The consequence side is
  shipped but **bound to the wrong policy**, and task 14 §5.8 is what closes the circuit:
  `frontier_repair.py:99-101` `INVALIDATE_ROLES = {"generator", "router", "utility_policy"}` carries
  the right semantic ("its score's policy (`utility_policy`) came from the retired prompt — no
  recompute can launder that", `frontier_repair.py:96-98`), but the only record bearing that role is
  `UtilityRecord`, whose `utility_policy_hash` is `UtilityPenaltyPolicy`'s hash over
  `{penalty_cap, severity_weights, verdict_factors}` (`adversarial/engine.py:947-963`) — a
  *different* policy from `capture_utility_policy`'s `{composite, axis_weights, frontier_score, …}`
  (`state.py:336`). Until task 14 lands, a scoring-policy retirement would match no record at all.
  **This doc therefore invents NO paper-local utility machinery.** `capture_paper_utility_policy`
  is the paper-phase *instance* of task 14's governed capture: whatever cadence, transition rules
  and kernel checks task 14 pins for the `utility_policy` role apply here unchanged, because that
  path is topology-agnostic and the paper archive is just another node population. What this doc
  owns is the payload's CONTENT (the anchor identity above) and nothing about when or how it is
  rewritten. The *active reviewer hash* is not in this policy either; it is tracked in
  `active_prompt_hashes` and changes only at boundaries.

### 5.6 Draft QUALITY has no ground truth → epoch-local draft winners

The writer's *prompt* is anchored (§5.1), but a draft's **quality** utility — clarity, narrative,
novelty, the axes the claim gate cannot see — is still whatever the **active, frozen**
`paper_reviewer` scored it. (This is the composite of §5.1: faithfulness alone would reward a dry,
over-hedged paper that passes the gate but reads poorly.) Two drafts scored by *different* reviewer
versions are therefore not comparable:

- **In-epoch**: the reviewer hash is frozen (§5.5), so all drafts of an epoch are ranked on one
  consistent policy — best-belief selection within the epoch is valid.
- **Across epochs**: a boundary may adopt `paper_reviewer_v2`. A draft scored by `v1` and a draft
  scored by `v2` cannot be compared directly. This is the score-comparability invariant
  ([Research and Governance State → Scores are only comparable inside one policy](../../concepts/research_and_governance_state.md#_5-scores-are-only-comparable-inside-one-policy))
  and ARI's B-17 status quo. Decision: **"best draft" is always the best under the CURRENT epoch's
  frozen reviewer**, computed over drafts whose utility was produced under that reviewer (or
  recomputed under it via the erasure recompute path, §5.7). We do NOT re-rank a `v1`-scored draft
  against a `v2`-scored draft by their stored scalars.
- **At defaults this is the DEFAULT path, not an edge case.** A paper epoch is one archive round and
  `rqgm.paper.epoch.rounds` defaults to `2` ([01](01_paper_execution_mode.md) §5.7), so a default
  `rqgm_archive` run crosses exactly one boundary: round 2's drafts are written and scored under
  whatever reviewer that boundary adopted. The rule above therefore fires on every default run
  rather than sitting dormant — round 2's best-belief ranks only drafts scored under the round-2
  reviewer, and a round-1 draft re-enters the ranking **only** through the §5.7 erasure-recompute
  path. That recompute path is consequently DEFAULT machinery, not a rarely-exercised branch, and
  §9's smoke coverage treats it as such. Consistent with the paper: generator winners are
  epoch-scoped, evaluators carry the cross-epoch ground truth.

> **Default rounds — landed decision (wave 3c, 2026-07-16).** `rounds: 2` crosses
> one boundary, which EXERCISES the whole loop (adversary → impeachment → warning
> → candidate spine) but does NOT complete a full `paper_reviewer` prompt
> *adoption*: opening the reviewer role and climbing
> candidate→validated→shadow→probationary_active is a ~5-boundary chain (the
> incumbent must first be sanctioned to a role-opening status, then the
> successor climbs T1/T3/T6). So a default run never witnesses a changed active
> reviewer hash. **Decision:** keep `rounds: 2` as the deliberate cheap default
> (documented in `defaults.yaml`'s `rqgm.paper.epoch` comment), and have the
> co-evolution PROOF test drive enough rounds (8) to complete a REAL organic
> adoption and assert the active hash changed. A run that must complete a
> reviewer adoption raises `rounds`. (doc 05 §5.5 boundary-reward, wave 3c.)

> **How the "don't re-rank across reviewer versions" rule is actually enforced, and what is
> deferred (corrected 2026-07-17, work order #30 item 5).** The rule holds STRUCTURALLY, not via a
> reviewer-hash filter on a stored scalar: each round builds a FRESH `PaperArchiveStrategy`
> (`paper_runtime.py::_run_one_round`), so a round's frontier and `_finalize_best` see ONLY that
> round's own draft tree — a round-2 best-belief can never contain a round-1 node to mis-rank in the
> first place. `select_best_to_expand` (`paper_archive.py:126`) ranks purely on
> `metrics["_scientific_score"]` filtered by `_valid_for_frontier`/`_sterile`; it carries no
> reviewer-hash/epoch gate because it never needs one. What IS deferred: the §5.7 erasure-recompute
> path that would let a round-1 draft legitimately RE-ENTER a later ranking under the new reviewer is
> unwired for paper roles (see §5.7's dated residual — no record carries `role="paper_writer"` and
> the paper roles are absent from `frontier_repair`'s role sets). Consequently the §9 cross-epoch
> "recompute as the DEFAULT path" smoke bullet is deferred WITH that residual and is not landed. Note
> also that at the default `rounds: 2` no reviewer adoption completes (the landed box above), so the
> two rounds are scored under the same `v1` reviewer and cross-version comparability does not arise at
> defaults; the recompute path only becomes reachable at the higher round counts the proof test uses.

### 5.7 Riding selective erasure

The paper draft archive is a best-first tree whose nodes are drafts ([02](02_paper_draft_archive_search.md)
§5.1), so it is a first-class citizen of the topology-agnostic erasure closure
([RQGM Architecture → Key invariants](../../concepts/rqgm_architecture.md#key-invariants) invariant 6,
`ari/rqgm/frontier_repair.py`). Decision — the paper case maps onto the EXISTING per-role policy
(no new erasure code):

| Retired paper role | Stale records | Draft-node consequence (reuses the slot-scoped per-role erasure policy, [Key invariants](../../concepts/rqgm_architecture.md#key-invariants) invariant 6) |
|---|---|---|
| `paper_reviewer` | draft `ReviewRecord` → dependent draft `UtilityRecord` | **Recompute** the draft's utility under the incoming reviewer if `rqgm.frontier_repair.recompute_utilities: true`, else **invalidate** the draft for best-belief. Never arithmetic un-scaling (P-D). |
| `paper_writer` | draft `ProposalRecord`/seed record (its very direction came from the retired writer) | **Invalidate**: the draft direction came from the retired writer prompt; the node stays in the archive as history, excluded from best-belief. |

> **Residual — the paper roles are NOT wired into `frontier_repair` yet (2026-07-17, work order
> #25).** The "maps onto the EXISTING per-role policy (no new erasure code)" claim above is a design
> intent, NOT the current code. `frontier_repair.py:103-120` lists only `{generator, router,
> utility_policy}` in `INVALIDATE_ROLES`/`_ROLE_STALE_REASONS` and `{reviewer, adversary, defender,
> judge}` in `RECOMPUTE_ROLES` — neither `paper_writer` nor `paper_reviewer` appears, and no record
> in the paper phase carries `role="paper_writer"`. So a retired paper prompt does NOT invalidate or
> recompute its drafts today; the table above overstates what runs. The fix is three-part and cannot
> be a two-line role add: (1) add `paper_reviewer` to `RECOMPUTE_ROLES` and `paper_writer` to BOTH
> `INVALIDATE_ROLES` AND `_ROLE_STALE_REASONS` (the second without the first raises `KeyError` inside
> `repair()`'s blanket `except`, silently killing the whole boundary's repair pass), and (2) add an
> emitter so draft records carry `role="paper_writer"`. Deferred — mitigant: best-belief already
> excludes stale/invalid nodes and a retired reviewer's cached anchor hits simply stop mattering
> (§5.7 bullet 1), so a retired prompt's drafts lose their trust signal at the next scoring even
> without the explicit invalidation edge; the gap is that the archived node is not affirmatively
> marked stale.

- **Anchor evidence itself is never staled-then-reused across reviewers.** A reviewer candidate's
  anchor scores are cached under its own `prompt_hash` (`replay_lookup_key`), so retiring
  `reviewer_v1` simply stops those hits from mattering; `reviewer_v2` is scored on the same
  held-out set under its own hash. This is the "never mix utility evidence across epochs /
  evaluators" principle (P-D) applied to anchors — erase, do not re-scale.
- The paper anchor corpus, being `origin_epoch_id="anchor_static"` and never authored by an
  evolving role, is outside every prompt-hash closure: it is never staled by any retirement
  (invariant 13 / physical-erasure-free; the corpus file is byte-compared unchanged in the §9
  no-deletion test).

### 5.8 Riding best-belief

Best-belief draft selection (the "hand the best draft to the claim gate" step, owned by
[02](02_paper_draft_archive_search.md) and analogous to `verified_context.select_best_node`)
consumes ONLY:

1. drafts with `status=SUCCESS` and `_valid_for_frontier=True` and `_stale=False` (the erasure
   sentinels — [Research and Governance State → Stale, invalidated, removed, deleted](../../concepts/research_and_governance_state.md#_6-stale-invalidated-removed-deleted-—-four-different-things)),
   and
2. utilities produced (or recomputed, §5.7) under the **current** epoch's frozen `paper_reviewer`.

Anchor scoring never directly ranks drafts — it only governs *which* reviewer is active. So
best-belief is a pure max over non-stale, in-epoch-frozen draft utilities; the anchor layer sits
one level up, deciding whose scores those are. The selected draft is then handed to the EXISTING
compile + claim-gate Layer-0 unchanged ([07](07_claim_gate_handoff_and_evaluation.md); the gate is
never kernel-wrapped, global invariant).

### 5.9 Q-49 anchor-half resolution + corpus curation cost and bootstrap

**Resolution of Q-49 (anchor half).** ARI's paper-phase ground-truth anchor is defined as: a
curated, read-only `paper_anchor_corpus.jsonl` of accept/reject-labelled reference manuscripts,
with a run-fixed held-out split, scored by held-out accept/reject **agreement**
(`binary_accept_reject_v1`), consumed through the EXISTING `anchor_evaluation` stage /
`AnchorBoard`. That corpus anchors `paper_reviewer`; `paper_writer` is anchored separately to the
Layer-0 claim gate's deterministic faithfulness, which needs no curated corpus (§5.1). This closes the
anchor half of Q-49 recorded in [../ari_rqgm/00](../ari_rqgm/00_current_ari_investigation.md) §5.9.
The versioning half is closed by [02](02_paper_draft_archive_search.md).

**The irreducible data cost, stated plainly.** A useful anchor corpus requires human-labelled
manuscripts. This is real, unavoidable work — there is no way to co-evolve a *trustworthy* reviewer
without an external signal it did not author. The plan does not pretend otherwise. What the plan
DOES do is make the corpus small, optional, and bootstrappable so the feature is buildable before a
large corpus exists:

- **Bootstrap A (self-labelled, zero new curation).** Reuse ARI's own history: manuscripts whose
  `claim_evidence_hard_gate_final.json` **passed** the Layer-0 claim gate are weak-`accept`
  exemplars; drafts that the gate **blocked** (or that were abandoned) are weak-`reject` exemplars.
  This is a deterministic, already-available signal (the gate is RQGM-independent and Layer-0),
  giving a starter corpus with no human labelling. The importer stamps `label_source:
  gate_bootstrap` on every case it writes (§5.2), which is what makes these labels *countable*
  rather than merely *disclaimed*: they are low-confidence by construction (noisy anchor, §10 R2)
  and are therefore capped at `max_bootstrap_label_fraction` and barred from `held_out` when they
  are accept+ai self-labels (§5.3). A pure Bootstrap-A corpus (fraction `1.0`) is refused at the
  default cap and lands on the on-ramp below — deliberately: a corpus ARI labelled entirely by
  itself is not ground truth, and the honest response is to have no anchor rather than a captured
  one.
- **Bootstrap B (small seed set).** A hand-curated set of ~10-20 published-vs-desk-rejected papers
  for the target venue, labelled once. Small enough to label in an afternoon; `sample_size`
  defaults to 8 so even a 16-case corpus supports an 8-case held-out sample.
- **Degraded on-ramp (no corpus at all).** With `rqgm.paper.anchor.enabled: false`, an empty /
  missing corpus, OR a corpus refused by the §5.3 bootstrap-label cap, the `anchor_evaluation` stage
  takes its existing empty-set branch — "a pass with zero coverage"
  (`prompt_evolution.py:924-927`) — so reviewer candidates are *not* anchor-gated
  and the reviewer's only signal is in-epoch. This composes with
  `rqgm.paper.prompt_evolution.enabled: false` (the analog of the paper's B4/B5 baselines): with
  both off, the paper phase is best-of-N reviewed drafts with NO co-evolution and NO anchor — the
  cheap, buildable-today on-ramp. Anchor + co-evolution are the paid upgrade.

**How the on-ramp reaches the spine: the `no_replay_basis` / `no_shadow_basis` sentinels
(amended 2026-07-17).** This section is cited by `transition_engine.NO_REPLAY_BASIS_ROLES` as
authority for admitting `paper_writer` and `paper_reviewer`, so it records the mechanism here
rather than leaving the citation to point at text that does not say it (the plan 14 §5.5
dated-amendment convention). A zero-coverage candidate reports its boards as **absent**
(`replay_score`/`anchor_score` `None`, `case_refs` `[]`, `shadow_samples` `0`) and **declares**
the absence; the T3 `replay_min_cases` and T6 `shadow_min_samples` COUNT floors are then waived
at the decision site, by role, in the open, with a note on the transition record. Without this
the on-ramp is not merely un-anchored but **dead**: an honestly empty board strands every
candidate at `validated` → T4 → T5 retirement, and the paper roles stop co-evolving silently.

The scope is deliberately narrow and is spelled out in doc [05](05_adversarial_self_preference.md)
§5.5, which owns the sentinel contract:

* `no_replay_basis` (T3) is declared **only when the board is genuinely absent** — this
  section's on-ramp, and nothing wider. A `paper_reviewer` that HAS pooled cases is **counted**
  against `replay_min_cases`, not waived.
* `no_shadow_basis` (T6) is declared **always** for the paper roles, because there is no
  shadow-serving path in the paper phase: the stage is vacuous BY CONSTRUCTION, not merely
  under-populated.
* Neither waives a SCORE. A reported board still clears `CANDIDATE_PASS_THRESHOLD` or fails; a
  failed `verdict` is never rescued; and T6's `_role_opening` guard is untouched, so `paper_writer`
  adoption still requires the real §5.1 claim-gate faithfulness sanction against the incumbent.

This is what "refusing to anchor is strictly safer than anchoring on self-labels" (§5.3) costs
and buys: the un-anchored reviewer keeps moving through the spine, and every gate it did not
actually clear is recorded as waived rather than papered over with numbers nobody computed.

## 6. Data structures / schema changes

### 6.1 `paper_anchor_corpus.jsonl` (checkpoint root; read-only corpus)

Schema per §5.2. Written once (by curation tooling or a bootstrap importer), never by a governed
role. Registration requirements (mirroring `epoch_state.json`):

- `paper_anchor_corpus.jsonl` added to `PathManager.META_FILES` (`ari-core/ari/paths.py:404`) so it
  is never copied into node work dirs; the corpus *manuscript* files live under a
  `anchor_corpus/` subdir that is likewise META-classified (or referenced by an absolute
  `corpus_path` outside the checkpoint, in which case only the JSONL index is in-checkpoint).
- No `_INTERNAL_JSON_NAMES` entry is needed for the `.jsonl` (that set is JSON-report-adjacent);
  if an anchor **result snapshot** is added (below) it is registered there.

### 6.2 Anchor result snapshot (derived; optional)

Anchor scores already persist as `PromptCandidateValidation` records
(`stage="anchor_evaluation"`, `metrics.anchor_pass_rate`) in the existing
`prompt_evolution.jsonl` and in the `GovernanceCache` (`rqgm_governance_cache.jsonl`). Decision:
**no new result store** in v1 — the reviewer's anchor utility is fully reconstructable from those
existing artifacts. A derived rollup (`paper_anchor_scores.json`: `{reviewer_prompt_hash:
{held_out_accuracy, cases_used}}`) is an OPTIONAL observability convenience; if added it is a
rewrite-snapshot (`indent=2, ensure_ascii=False`), `META_FILES` + `_INTERNAL_JSON_NAMES` registered,
and rebuildable by folding the candidate-validation records.

### 6.3 `paper_utility_policy` (frozen into the paper epoch fingerprint)

The §5.5 payload. Lives inside `paper_archive_state.json` (owned by [01](01_paper_execution_mode.md))
as an additive field; this task pins its content and hash, not the container.

**What actually ships (corrected 2026-07-17).** `paper_archive_state["paper_epoch_fingerprint"]` is
set to `policy["paper_utility_policy_hash"]` (`paper_runtime.py::_freeze_paper_utility_policy`), i.e.
`hash12(canonical_json(paper_utility_policy))` — the hash of the policy payload itself, NOT a hash
over a wider "paper epoch payload" wrapping `epoch_id`/active prompt hashes. This is what makes §5.5's
biconditional hold: the fingerprint changes iff the anchor identity (corpus digest / held-out sample /
sample size / metric / either label-source mix) changes, because those are exactly the fields the
policy hash covers. Epoch identity (`epoch_id`, active `paper_writer`/`paper_reviewer` hashes) is
carried by the INHERITED exploration `epoch_fingerprint` (`state.py:epoch_fingerprint`), not
re-implemented here; the field name `paper_epoch_fingerprint` is therefore a mild misnomer for a
policy fingerprint, retained for continuity with the persisted state schema. A resume against a
mutated corpus is detected by comparing this hash and warned (§8.5), never silently flipped.

### 6.4 Config: `rqgm.paper.anchor`

Typed subsection of the paper RQGM config (the `rqgm.paper.*` home is introduced by
[01](01_paper_execution_mode.md); this task owns the `anchor` block only):

```yaml
rqgm:
  paper:
    enabled: false                 # interlock (owned by 01); anchor is inert unless this + paper.mode agree
    anchor:
      enabled: false               # default off => degraded on-ramp (§5.9); no corpus required
      corpus_path: ""              # path to paper_anchor_corpus.jsonl (checkpoint-relative or absolute)
      sample_size: 8               # held-out cases scored per reviewer per epoch (reuses replay sizing)
      max_bootstrap_label_fraction: 0.5   # §5.3: max share of label_source=gate_bootstrap cases,
                                          # checked over the corpus AND the held_out subset;
                                          # breach => corpus refused => on-ramp (§5.9), never raises
    prompt_evolution:
      enabled: true                # owned by 03; false => no reviewer co-evolution (on-ramp)
```

Defaults live in `ari-core/ari/configs/defaults.yaml` under the `rqgm.paper` block and are mirrored
by a typed `RQGMPaperAnchorConfig` (same `model_config = {"extra": "allow"}` forward-compat posture
as every other RQGM subsection, `config/__init__.py`). All defaults inert: `anchor.enabled: false`
means no corpus is read and no anchor call is made.

`max_bootstrap_label_fraction: 0.5` is the literal encoding of §10 R2's "keep them a minority" — a
policy that was previously prose only, and therefore unenforced. `0.5` (strict minority) is chosen
over a stricter value because Bootstrap A is explicitly the day-one path (§5.9): a cap that refused
every bootstrap-heavy corpus would make the buildable on-ramp the only reachable state. Setting it
to `0.0` yields the strict "human labels only" corpus; `1.0` disables the check and is the
documented way to say "I accept a self-labelled anchor", which the frozen mix (§5.5) then records
in the epoch fingerprint for the audit trail.

## 7. API / class changes

All new code is internal (`ari-core/ari/rqgm/paper_anchor.py`); nothing enters `ari.public.*`, the
CLI tree, or the MCP namespace (zero contract-snapshot churn — the same "internal machinery, no
contract-surface change" posture the evaluation harness holds,
[RQGM Evaluation and Ablation](../../guides/rqgm_evaluation.md#rqgm-evaluation-and-ablation), and the
mode-wide rule in [Internal boundaries → RQGM mode boundary](../../reference/internal_boundaries.md#rqgm-mode-boundary-ari-rqgm)).

| Symbol | Location (planned) | Contract |
|---|---|---|
| `PaperAnchorCase` (TypedDict/dataclass) | `ari/rqgm/paper_anchor.py` | §5.2 line schema; frozen field set; `to_dict` for board interop. |
| `load_anchor_corpus(cfg, checkpoint_dir) -> PaperAnchorPool \| None` | `ari/rqgm/paper_anchor.py` | Absence-tolerant: returns `None` when `anchor.enabled=false` or the corpus is missing/empty (drives the on-ramp). Loads, sorts by `case_id`, rejects cases with missing/unknown `label_source` (§5.2), asserts `anchor_*`/`eval_*` namespace disjointness, computes `corpus_digest`, excludes accept+ai+gate_bootstrap self-labels from `held_out` (§5.3), calls `assign_split`, then computes the `gate_bootstrap` fraction over **both** the corpus and the resulting `held_out` set and returns `None` if **either** exceeds `anchor.max_bootstrap_label_fraction` (§5.3; logged at WARNING with both fractions, drives the §5.9 on-ramp). **Never raises into the run** — every integrity failure degrades to `None`, i.e. to "no anchor gate", never to a crash and never to a silently weaker anchor. Also returns the two label-source mixes for §5.5. |
| `PaperAnchorPool` | `ari/rqgm/paper_anchor.py` | Pool-shaped adapter exposing `.anchor_cases` (held-out cases) and an empty `.cases`, so `anchor_cases(pool)` / `board_score` and `CandidateValidationPipeline(anchor_cases=...)` consume it unchanged. Carries `corpus_digest`, `held_out_ids`, and the `label_source_mix` / `held_out_label_source_mix` counts (§5.5). |
| `assign_split(cases, *, sample_size, corpus_digest)` | `ari/rqgm/paper_anchor.py` | §5.3 pure, deterministic, epoch-independent held-out selection. |
| `binarize_recommendation(rec) -> "accept"\|"reject"\|None` | `ari/rqgm/paper_anchor.py` | §5.4 four-level → binary; unparseable → `None`. |
| `paper_reviewer_agreement(candidate_verdict, case) -> bool` | `ari/rqgm/paper_anchor.py` | §5.4 `case_evaluator` for the `anchor_evaluation` stage. |
| `capture_paper_utility_policy(cfg, *, corpus_digest, held_out_ids, label_source_mix, held_out_label_source_mix) -> dict` | `ari/rqgm/paper_anchor.py` | §5.5; mirrors `state.py:capture_utility_policy` (`state.py:313`); content-only hash; the payload's cross-epoch rewrite is [../ari_rqgm/14](../ari_rqgm/14_governed_utility_evolution.md)'s, not this doc's. |

Reused unchanged (no signature change): `board_score`, `anchor_cases`, `evaluate_candidates`
(`ari/rqgm/governance/_adjudication.py`); `CandidateValidationPipeline.run_stage` /
`_case_evaluation` (`ari/rqgm/prompt_evolution.py`); `replay_lookup_key` / `GovernanceCache`
(`ari/rqgm/governance_cache.py`); the FrontierRepairEngine closure (`ari/rqgm/frontier_repair.py`).
The `PaperArchiveRuntime` ([01](01_paper_execution_mode.md)) constructs the `PaperAnchorPool` at the
paper entry and injects it into the reviewer co-evolution path ([03](03_writer_reviewer_governed_roles.md)).

## 8. Migration / compatibility

Preserve-existing-behavior policy (normative):

1. **`linear` and default `rqgm_archive`-without-anchor are unaffected.** `anchor.enabled: false`
   (default) reads no corpus, makes no anchor call, freezes `anchor_enabled: false` into the paper
   utility policy, and takes the empty-set "pass with zero coverage" branch. The paper pipeline is
   byte-identical to today under `paper.mode: linear` (global invariant), and the archive path
   without anchor is the degraded on-ramp (§5.9).
2. **Exploration is untouched.** The exploration `reviewer` (peer_review) and its (unpopulated)
   AnchorBoard are unchanged; `anchor_cases(pool)` still returns `None` for every exploration pool.
   The paper anchor corpus is a *separate* pool object handed only to the paper reviewer lifecycle.
3. **No physical erasure of the corpus.** The corpus is `origin_epoch_id="anchor_static"`, outside
   every prompt-hash closure; the §9 byte-compare test asserts it is never rewritten (erasure is
   logical-only — nothing is physically deleted,
   [RQGM Architecture → Key invariants](../../concepts/rqgm_architecture.md#key-invariants) invariant 6).
4. **Additive schema only.** `paper_utility_policy` is an additive field in `paper_archive_state.json`;
   `RQGMPaperAnchorConfig` is a typed subsection with `extra: allow`; `paper_anchor_corpus.jsonl` is
   a new META file. Nothing existing changes shape.
5. **Resume-safe / deterministic.** The held-out split is a pure function of `(case_id,
   corpus_digest, sample_size)` with no epoch or wall-clock input, so `resume` reconstructs the same
   held-out set; the frozen `paper_utility_policy_hash` in `paper_archive_state.json` detects a
   corpus swap across resume (warning, never a silent mid-run policy flip — mirrors
   [01](01_paper_execution_mode.md) resume semantics).
6. **Old checkpoints.** A checkpoint with no `paper_anchor_corpus.jsonl` and no
   `paper_utility_policy` resolves to the on-ramp (anchor disabled) — the safe default direction.

## 9. Tests

Unit (new `ari-core/tests/test_paper_anchor.py`, listed in `ari-core/tests/README.md` for the
readme-sync gate; no litellm/network import):

- `binarize_recommendation`: the four `academic_reviewer.md` levels map correctly; unparseable →
  `None`; a `None` verdict is a miss in `paper_reviewer_agreement` (never counted as agreement).
- `paper_reviewer_agreement`: accept-vs-accept / reject-vs-reject pass; cross-label fails; schema
  violation (missing `accept_recommendation`) fails.
- `assign_split`: deterministic (same corpus + `sample_size` ⇒ identical held-out id set, twice);
  epoch-independent (no epoch arg); honors pre-pinned splits; `sample_size ≥ len(corpus)` ⇒ all-free
  held out; namespace-disjointness assertion (`anchor_*` vs `eval_*`).
- `capture_paper_utility_policy`: `writer_anchor` is the `WRITER_ANCHOR_DESCRIPTOR` dict naming the
  Layer-0 gate and its three component rates (§5.1); hash excludes wall clock; the hash
  changes iff corpus digest / sample size / held-out ids / metric id **/ either label-source mix**
  change and is stable otherwise. Specifically: two corpora with the SAME digest-relevant content
  but different `label_source` stamps ⇒ **different** `paper_utility_policy_hash` (the ground truth
  became more self-labelled and the fingerprint says so); re-capturing the identical corpus twice ⇒
  byte-identical hash.
- `load_anchor_corpus` bootstrap cap (§5.3), all asserting **return `None`, never raise**:
  corpus-level breach (e.g. 6/10 `gate_bootstrap` at cap `0.5`) ⇒ `None`; corpus-level PASS but
  held-out-level breach (a 40%-bootstrap corpus whose 8-case held-out sample is 100% bootstrap) ⇒
  `None` — the case the corpus-only check would miss; exactly-at-cap (5/10) ⇒ loads (the cap is
  a strict-exceed test); `max_bootstrap_label_fraction: 1.0` ⇒ loads a fully self-labelled corpus
  (opt-out is explicit and fingerprinted); and the `None` return lands the run on the §5.9 on-ramp
  (`anchor_evaluation` takes its "pass with zero coverage" branch, `prompt_evolution.py:924-927`)
  rather than aborting.
- Self-label detector: a case with `label_source: gate_bootstrap` + `ground_truth_label: accept` +
  `authorship: ai` is never assigned `split: held_out` and is counted against the corpus cap; the
  same case with `authorship: human` is eligible for `held_out`.
- `label_source` is required: a case omitting it (or carrying an unknown value) is rejected at load;
  a corpus of only such cases ⇒ `None` (on-ramp), not a partial corpus.
- `PaperAnchorPool` interop: `anchor_cases(pool)` returns the held-out cases; `board_score` over a
  fixture with cached per-subject results equals the hand-computed mean (agreement accuracy).

Regression (linear + exploration unchanged):

- `paper.mode: linear` paper run: no `paper_anchor_corpus.jsonl` read, no anchor call, no
  `paper_utility_policy` written; byte-identical paper artifacts vs the pre-feature golden.
- Exploration `anchor_cases(pool)` still `None` for every v1 exploration pool (no cross-contamination);
  the full existing `test_rqgm_governance.py` / `test_rqgm_prompt_lifecycle.py` suites stay green.
- Contract snapshots unchanged (no public/CLI/MCP symbol).

Smoke (`paper.mode: rqgm_archive`, `rqgm.paper.enabled: true`, `anchor.enabled: true`, stub LLM):

- A `paper_reviewer` candidate runs the `anchor_evaluation` stage against a fixture corpus; a
  reviewer double that always outputs `reject` scores its held-out accuracy = (reject-labelled
  fraction) of the sample; `ties_favor_incumbent` observed on a tie.
- Empty/`enabled:false` corpus ⇒ the stage's "pass with zero coverage" branch fires; the reviewer
  is not anchor-gated; the run completes (on-ramp path).
- The paper epoch fingerprint in `paper_archive_state.json` embeds `paper_utility_policy_hash`;
  flipping `sample_size` between two runs changes it, and so does swapping one case's
  `label_source` from `human_curated` to `gate_bootstrap` (§5.5).
- **Cross-epoch winners at the default `rqgm.paper.epoch.rounds: 2` (§5.6).** A two-round run whose
  boundary adopts `paper_reviewer_v2`: round-2 best-belief never ranks a round-1 `v1`-scored draft
  by its stored scalar; a round-1 draft re-enters the ranking only after the §5.7 recompute path
  re-derives its utility under `v2` (or stays invalidated when
  `rqgm.frontier_repair.recompute_utilities: false`). This exercises the recompute path as the
  DEFAULT path, not as an edge case.

Resume:

- Run a paper epoch with anchor on, kill, `resume` ⇒ same held-out id set reconstructed, same
  `paper_utility_policy_hash`; a resume with a mutated corpus ⇒ digest mismatch warning, no silent
  policy flip.

## 10. Risks

- **R1 — Corpus curation cost (the irreducible one).** A quality anchor needs human labels;
  Mitigation: `sample_size` keeps it small, Bootstrap A reuses the Layer-0 claim gate for zero-label
  starters, and the on-ramp (§5.9) ships value with no corpus at all. Stated plainly in §5.9; not
  hidden.
- **R2 — Noisy / self-labelled anchors (the corpus as an attack surface).** Bootstrap A's
  claim-gate-pass labels are weak (gate pass ≠ venue accept), and the anchor corpus is the one
  evaluation authority nothing else checks: a mislabelled corpus silently redefines what "fair
  reviewing" means for every epoch, and a mostly-self-labelled one turns the anti-collusion story
  into ARI certifying its own output. Mitigation, primary and **machine-enforced**: every case must
  declare `label_source` (§5.2); `rqgm.paper.anchor.max_bootstrap_label_fraction` (default `0.5`,
  §6.4) caps the `gate_bootstrap` share over the corpus AND over the held-out subset, breach ⇒
  `load_anchor_corpus` returns `None` ⇒ the §5.9 on-ramp (no anchor gate) rather than a
  self-certifying one (§5.3); accept+ai+gate_bootstrap self-labels are excluded from `held_out`
  outright; and both label-source mixes are frozen into the epoch fingerprint (§5.5) so a drift
  toward self-labelling cannot happen without changing epoch identity. Secondary (observability,
  not enforcement): reviewer held-out accuracy is surfaced in the eval harness as metric P2
  ([Paper metrics P1–P5](../../guides/rqgm_evaluation.md#paper-metrics-p1–p5)) so a corpus that teaches the wrong
  thing is *also* visible to a human before it drives retirements. Residual: the cap bounds *how
  much* of the ground truth ARI authors, not whether a human-curated label is itself wrong — R3/R4
  cover thin and leaked evidence, and no in-band mechanism can validate a human label.
- **R3 — Tiny corpus false-confidence.** An 8-case held-out set can rank two reviewers on luck.
  Mitigation: `ties_favor_incumbent` (incumbent presumption on thin evidence), the AnchorBoard
  `BOARD_HIGH/LOW` bounding of judge verdicts, and the transition thresholds
  (`replay_min_cases`-style floors,
  [Configuration → `rqgm.transition`](../../reference/configuration.md#rqgm-transition-—-registrytransitionengine-thresholds))
  that gate retirement on the reused RegistryTransitionEngine.
- **R4 — Held-out leakage.** If a held-out manuscript was in the reviewer's founding-prompt
  distillation, agreement is inflated. Mitigation: the load-time namespace-disjointness assertion
  (§5.3) plus a curation rule that anchor manuscripts are never used as seed prompts; the split is
  frozen in the fingerprint so leakage cannot be introduced silently mid-run.
- **R5 — Cross-epoch comparability.** Comparing a `reviewer_v1`-scored draft to a `reviewer_v2`-scored
  draft is invalid (§5.6), and at the default `rqgm.paper.epoch.rounds: 2` this is the normal case,
  not a corner (§5.6). Mitigation: best-belief always ranks under the current frozen reviewer and
  consumes only non-stale utilities; the erasure recompute path (§5.7) re-derives utilities under
  the incoming reviewer. **Cross-epoch re-weighting of the utility policy itself is INHERITED, not
  out of scope, and not paper-local.** It is owned by
  [../ari_rqgm/14_governed_utility_evolution.md](../ari_rqgm/14_governed_utility_evolution.md),
  which makes `utility_policy` a governed role rewritten at boundaries through the same
  `RegistryTransitionEngine` + `ConstitutionalKernel` path every other governed artifact uses;
  the paper phase consumes that path topology-agnostically and this doc adds no utility machinery
  of its own (§5.5). This supersedes the earlier reading that inherited I-11 "axes frozen per
  run" as a permanent scope boundary — that invariant is now repealed
  ([RQGM Architecture → Governed utility evolution](../../concepts/rqgm_architecture.md#governed-utility-evolution)):
  I-11 described the *status quo* (`state.py:318-320` — "in v1
  the frozen policy is constant across epochs within a run … per-epoch re-weighting is a Task 10/13
  decision"), and task 14 is where that decision is now made. Residual risk for this doc: none of
  its own — **task 14 has landed** (`capture_utility_policy` resolves the adopted policy,
  `ari-core/ari/rqgm/state.py:354-382`; the T20 supersession edge fires at real boundaries), so the
  paper phase inherits a genuinely epoch-varying policy and the score-rewrite half is no longer
  unimplemented method-wide.
- **R6 — Writer overfits to reviewer blind spots.** A writer can learn to please a biased reviewer.
  Mitigation (strengthened by §5.1's writer anchor): the claim-gate faithfulness score is
  reviewer-INDEPENDENT, so a writer that pleases a lenient reviewer by overclaiming is sanctioned by
  the gate no matter what the reviewer thinks; plus the `paper_self_preference` adversary
  ([05_adversarial_self_preference.md](05_adversarial_self_preference.md)) and the reviewer's own
  anchor accuracy guard the reviewer — one that rewards over-claiming loses anchor agreement and is
  retired. Residual: the writer sanction is emitted BY the self-preference round, which returns early
  without an over-accepted anchor case, so the one uncovered configuration is a lenient reviewer that
  over-accepts nothing while the writer overclaims. A dedicated writer-adversary type (paper-gated,
  mirroring `paper_self_preference`'s registration) would decouple them; deferred as a separate
  decision.
- **R7 — Anchor scoring cost.** Scoring every reviewer candidate on the held-out set is LLM calls.
  Mitigation: `use_cached_results` keys scores on `(case, reviewer prompt_hash)` so repeats are free;
  `sample_size` caps per-epoch calls; the whole anchor budget rides the inherited
  `GovernanceBudgetManager` ([06_cost_control_and_budget.md](06_cost_control_and_budget.md)).

## 11. Completion criteria

This task is complete when all of the following hold:

1. **Anchor corpus defined** — `paper_anchor_corpus.jsonl` schema (§5.2/§6.1), its accept/reject
   label semantics, its read-only / `anchor_static` status, and its `PathManager.META_FILES`
   registration are specified.
2. **Held-out agreement metric defined** — the deterministic run-fixed split (§5.3), the
   `binary_accept_reject_v1` binarization and `paper_reviewer_agreement` evaluator (§5.4), and their
   wiring into the EXISTING `anchor_evaluation` stage / `AnchorBoard` `board_score` (reused, not
   rebuilt) are specified with `sample_size` as the cost knob.
3. **The two anchors + epoch-local draft winners settled** — the asymmetry (§5.1: reviewer →
   accept/reject corpus, writer → Layer-0 claim-gate faithfulness) and the
   cross-epoch-comparability rule for DRAFT utilities (§5.6) are written, with best-belief always
   ranking under the current frozen reviewer.
4. **Utility-policy freeze specified** — `capture_paper_utility_policy` (§5.5), its hash, and its
   freeze into the paper epoch fingerprint (mirroring `state.py`) are defined, including the
   `writer_anchor` descriptor, the corpus/split/metric identity, and both label-source mixes; and the
   doc pins that the policy's cross-epoch REWRITE is inherited from
   [../ari_rqgm/14](../ari_rqgm/14_governed_utility_evolution.md) with no paper-local utility
   machinery.
5. **The anchor corpus is itself constrained, not merely observed** — `label_source` is required
   (§5.2), `max_bootstrap_label_fraction` caps the self-labelled share over the corpus and the
   held-out subset with a `None` → on-ramp degrade on breach (§5.3, §6.4, §7), accept+ai+
   gate_bootstrap self-labels are barred from `held_out`, and the label-source mix is
   fingerprinted (§5.5) — so a corpus that turns ARI into its own ground truth is refused by the
   loader rather than caught by a human reading the eval harness (§10 R2).
6. **Erasure + best-belief interaction settled** — the per-role erasure mapping for
   `paper_reviewer`/`paper_writer` (§5.7) reuses [../ari_rqgm/10](../ari_rqgm/10_frontier_repair_and_selective_erasure.md)
   §5.4 verbatim, and best-belief consumes only non-stale in-epoch utilities (§5.8) — the
   recompute path being DEFAULT machinery at `rqgm.paper.epoch.rounds: 2` (§5.6).
7. **Q-49 anchor half resolved + bootstrap given** — §5.9 states the irreducible curation cost, the
   two bootstraps (self-labelled via the Layer-0 claim gate; small seed set), and the corpus-free
   on-ramp; downstream tasks (03, 05, 06, 07) can consume the anchor contract without re-opening it.

## 12. Deletion criteria

This plan file may be deleted only when all of the following hold:

- The target feature/design is merged into the main branch.
- Corresponding tests have been added.
- CI is green.
- Key design decisions have been moved to permanent docs or code comments.
- No unresolved open questions remain, or they have been moved to another task plan.
- No downstream task depends solely on this plan file.
- INDEX.md task status has been updated to completed/deleted.
- Developers will not be confused by this file's absence.
- The deleted content remains available in git history.

Task-specific criteria (all additionally required):

- `paper_anchor_corpus.jsonl` schema (incl. the required `label_source`) and
  `rqgm.paper.anchor.{corpus_path, sample_size, enabled, max_bootstrap_label_fraction}` are
  implemented as typed config with defaults, and the corpus file is registered in
  `PathManager.META_FILES`.
- The `anchor_evaluation` agreement metric (`binary_accept_reject_v1`), the deterministic held-out
  split, the bootstrap-label cap (corpus + held-out, degrade-to-`None`), and
  `capture_paper_utility_policy` are implemented, with the paper epoch fingerprint embedding
  `paper_utility_policy_hash` and both label-source mixes.
- Unit, regression (linear + exploration unchanged), smoke, and resume tests per §9 exist and pass;
  the no-physical-deletion byte-compare covers the corpus.
- The writer's faithfulness anchor (§5.1), the epoch-local DRAFT-winners rule, and the corpus
  bootstrap policy are moved to the permanent paper-co-evolution guide under `docs/`.
- Q-49's anchor half is confirmed resolved in the permanent docs (and struck from any open-questions
  register).

## 13. Delete-after checklist

Verify before deleting this file:

- [ ] Implementation is complete.
- [ ] Tests exist.
- [ ] CI is green.
- [ ] Key design decisions have been moved to permanent docs.
- [ ] Unfinished items have been moved to another task plan.
- [ ] INDEX.md has been updated.
- [ ] Deleting this plan file will not strand any developer.
- [ ] The deletion reason can be stated in the commit message.

Task-specific items:

- [ ] `paper_anchor_corpus.jsonl` schema (with required `label_source`) + `rqgm.paper.anchor` config
      implemented and META-registered.
- [ ] Held-out split + `binary_accept_reject_v1` agreement metric wired into the reused
      `anchor_evaluation` stage / `AnchorBoard`; determinism test in CI.
- [ ] `max_bootstrap_label_fraction` enforced over the corpus AND the held-out set with a
      `None` → on-ramp degrade (never raises); accept+ai+gate_bootstrap self-labels barred from
      `held_out`; both tests in CI.
- [ ] `capture_paper_utility_policy` frozen into the paper epoch fingerprint; hash-stability test
      in CI, incl. the hash moving iff the label-source mix moves.
- [ ] The paper utility policy's cross-epoch rewrite is confirmed to ride
      [../ari_rqgm/14](../ari_rqgm/14_governed_utility_evolution.md)'s governed path, with no
      paper-local utility machinery added here.
- [ ] Writer faithfulness anchor (§5.1) + epoch-local DRAFT winners + erasure/best-belief
      interaction documented in the permanent guide.
- [ ] Q-49 anchor half marked resolved; corpus bootstrap (Layer-0 gate reuse + seed set) documented.
- [ ] No-physical-deletion byte-compare includes the anchor corpus; linear-mode byte-identity smoke green.
