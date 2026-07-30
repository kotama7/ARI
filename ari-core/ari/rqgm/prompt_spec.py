"""PromptSpec — prompts as versioned, role-scoped objects (RQGM Task 07).

A :class:`PromptSpec` separates (plan ``docs/plans/ari_rqgm/07`` §5.1):

* **identity** — ``prompt_id`` / ``role`` / ``version`` / lineage
  (``parent_prompt_id``) / ``generation_mode``;
* **bytes** — a ``template_ref`` pointing at the template file whose bytes
  define ``prompt_hash = sha256(bytes)[:12]`` (the EXACT
  ``FilesystemPromptLoader.load_versioned`` scheme — one scheme, never a
  second implementation) plus the ``full_sha256`` pinned the same way
  ``tests/test_prompt_extraction.py`` pins committed templates;
* **contract** — the ``spec`` body: ``role_instruction``,
  ``constitutional_constraints``, ``input_contract``, ``output_schema``,
  ``rubric``, ``calibration_policy``, ``budget_policy``.

The template bytes stay dumb ``str.format`` Markdown; the PromptSpec is
metadata *about* the template and rendering is byte-identical to today.

Founding bootstrap (§5.2): the committed ``ari-core/ari/prompts/**/*.md``
templates map to v1 founding specs whose ``prompt_hash`` equals
``load_versioned(key)[1]`` — verifiable against ``_EXPECTED_HASHES`` and the
Gate 10 snapshots with zero new hashing. Founding specs are the SOLE
``active``-on-creation exception; everything else enters at ``candidate``.

Registry-version note: this module defines NO registry-version scheme. The
value stamped into provenance comes from Task 02's
``GovernedPromptRegistry.registry_version()`` (plan 02 §5.4 owns the formula).

Deterministic, pure stdlib: no LLM calls, no network, no randomness (P2).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ari.rqgm.events import (
    UTILITY_POLICY_ROLE,
    canonical_json,
    format_prompt_id,
    hash12,
)
from ari.rqgm.meta_rules import DEFAULT_FORBIDDEN_TARGETS

PROMPT_SPEC_SCHEMA_VERSION = 1

#: Reserved by Task 02 (``ari.rqgm.store.RQGM_PROMPTS_DIRNAME``); re-stated
#: here import-light so this pure module never pulls the loader or the state
#: store in (the ``prompt_loader.py:33`` precedent — and ``prompt_loader``
#: imports THIS module, so importing it back would be a cycle).
RQGM_PROMPTS_DIRNAME = "rqgm_prompts"

#: ``template_ref.kind`` values (plan 07 §6): ``package`` == committed loader
#: key; ``checkpoint`` == evolved body under ``{ckpt}/rqgm_prompts/``;
#: ``policy`` == a Task-14 utility-policy body (canonical JSON) under the
#: same directory.
#:
#: **Why a policy is a "prompt"** (plan 14 §5.3 decision; recorded here
#: because a future reader must not have to re-derive it). The governed
#: utility policy is registered as a PromptSpec / GovernedPromptEntry whose
#: ``prompt_hash`` IS ``utility_policy_hash``, rather than as a parallel
#: ``UtilitySpec`` type, because:
#:
#: 1. the identity arithmetic already lines up — prompt identity is
#:    ``hash12(bytes)`` and ``capture_utility_policy`` computes
#:    ``hash12(canonical_json(body))``, so making the body's BYTES that
#:    canonical JSON gives ``hash12(bytes) == utility_policy_hash`` by
#:    construction: one scheme, no second implementation;
#: 2. the retirement→repair join is prompt-keyed
#:    (``frontier_repair`` matches records on ``prompt_hash``), so a
#:    separate type would need a parallel retirement channel, audit event
#:    and repair entry point — three duplications for one object;
#: 3. the freeze seam is prompt-keyed — ``active_prompt_hashes()`` already
#:    yields ``role -> prompt_hash``, so the epoch's policy hash is free;
#: 4. ``UtilityRecord`` already defaults to ``component_id
#:    ="utility_policy_v1"`` / ``role="utility_policy"`` / ``prompt_hash =
#:    <policy hash>``: it was written against a registry entry that did not
#:    exist. Task 14 creates the entry rather than contradicting the record.
#:
#: A ``policy`` spec is never RENDERED: ``active_prompt_view`` filters it
#: out (a policy is not a prompt to render; it is a policy to freeze).
TEMPLATE_REF_KINDS: tuple[str, ...] = ("package", "checkpoint", "policy")

#: The ``template_ref.kind`` / ``source.kind`` marking a utility-policy body.
POLICY_TEMPLATE_REF_KIND = "policy"

#: The founding utility-policy identities (plan 14 §5.3). The component id is
#: exactly the one ``adversarial.records.UtilityRecord`` already stamps.
UTILITY_POLICY_PROMPT_ID = "utility_policy_prompt_v1"
UTILITY_POLICY_COMPONENT_ID = "utility_policy_v1"

#: How a spec came to exist (plan 07 §5.1).
GENERATION_MODES: tuple[str, ...] = ("founding", "mutation", "clean_room")

#: Machine-checkable constraint clauses each role's spec MUST carry verbatim
#: (plan 07 §5.3 stage 2). Task 07 owns this table; the kernel's frozen rule
#: tables (Task 04) stay untouched.
REQUIRED_CONSTRAINTS_BY_ROLE: dict[str, tuple[str, ...]] = {
    "reviewer": (
        "Do not override fixed verifier failures.",
        "Do not directly modify frontier scores.",
    ),
    "judge": ("Do not override fixed verifier failures.",),
    "router": ("Do not directly modify frontier scores.",),
    "adversary": ("Attack artifacts, never components.",),
    "prompt_mutator": (
        "Emit candidates only; never write to the registry.",
    ),
    # Task 14 (plan 14 §5.2): copied verbatim from ``prompt_mutator`` — the
    # PolicyMutator has the identical candidates-only contract.
    #
    # ``utility_policy`` deliberately gets NO row: constraint clauses are
    # instructions to an ACTOR, and the utility policy is a document.
    "policy_mutator": (
        "Emit candidates only; never write to the registry.",
    ),
    # plan 11 §5.2 items 3-4. Both roles emit RECOMMENDATIONS, and the clause
    # each carries is the exact property that makes the role safe to evolve.
    #
    # The replay selector's danger is suppression, not fabrication: a selector
    # that learned to omit the cases its own lineage keeps failing would erase
    # its evidence. ``meta_evolution._route_output`` already unions the
    # mandated minimum set regardless, so the clause states the invariant the
    # code enforces rather than asking the model to be trusted with it.
    "replay_selector": (
        "Recommend replay cases only; never suppress a mandated case.",
    ),
    # The compressor's danger is contamination: it reads failure evidence and
    # emits text that later flows into clean-room regeneration, which exists
    # precisely so a successor prompt never sees its predecessor's bytes.
    "failure_summary_compressor": (
        "Summarise failures abstractly; never reproduce raw attack, defense, "
        "or prompt text.",
    ),
    # Paper-archive co-evolution (plan ari_rqgm_paper/03 §5.4). The writer's
    # anti-fabrication clause (lifted from ari-skill-paper/src/prompts/
    # paper_writer.md's "Do NOT hallucinate results, hardware specs, or
    # citations not present in the experiment data") is a hard candidate-
    # admission gate; the reviewer clauses pin the Layer-0 invariant that an
    # evolvable evaluator never overrides the claim-evidence gate and never
    # writes frontier scores (mirroring the exploration ``reviewer``).
    "paper_writer": (
        "Do not fabricate results, hardware specs, or citations absent from "
        "the verified experiment data.",
    ),
    "paper_reviewer": (
        "Do not override the claim-evidence hard gate.",
        "Do not directly modify frontier scores.",
    ),
}

#: Placeholder names a candidate template may never introduce: these are the
#: contamination channels Task 08 forbids (raw adjudication material must
#: only ever flow through the AdversarialReplayPool's ``abstract_view``).
FORBIDDEN_PLACEHOLDERS: frozenset[str] = frozenset(
    {"raw_attack_text", "defense_text", "retired_prompt_text"}
)

#: Templates loaded raw and never ``.format``-ed (plan 07 §4 note): their
#: literal JSON braces would register as pseudo-placeholders, so their
#: founding specs record an EMPTY placeholder contract.
RAW_LOADED_KEYS: frozenset[str] = frozenset(
    {"orchestrator/lineage_decision", "orchestrator/root_idea_selector"}
)


@dataclass(frozen=True)
class PromptSpec:
    """One versioned prompt identity (plan 07 §6 schema). Immutable: any
    change is a NEW ``prompt_id`` + ``prompt_hash`` — never an edit."""

    prompt_id: str
    role: str
    version: int
    status: str = "candidate"
    generation_mode: str = "founding"
    parent_prompt_id: str | None = None
    #: ``{"kind": "package"|"checkpoint", "key": <loader key>}``.
    template_ref: dict = field(default_factory=dict)
    prompt_hash: str = ""
    full_sha256: str = ""
    evolvable: bool = True
    epoch_introduced: str = ""
    #: role_instruction / constitutional_constraints / input_contract /
    #: output_schema / rubric / calibration_policy / budget_policy.
    spec: dict = field(default_factory=dict)
    schema_version: int = PROMPT_SPEC_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "prompt_id": self.prompt_id,
            "role": self.role,
            "version": self.version,
            "status": self.status,
            "generation_mode": self.generation_mode,
            "parent_prompt_id": self.parent_prompt_id,
            "template_ref": dict(self.template_ref),
            "prompt_hash": self.prompt_hash,
            "full_sha256": self.full_sha256,
            "evolvable": self.evolvable,
            "epoch_introduced": self.epoch_introduced,
            "spec": dict(self.spec),
        }


def prompt_spec_from_dict(d: dict) -> PromptSpec:
    """Rebuild a :class:`PromptSpec` from a parsed JSON dict (replay path)."""
    return PromptSpec(
        prompt_id=str(d.get("prompt_id", "")),
        role=str(d.get("role", "")),
        version=int(d.get("version", 1)),
        status=str(d.get("status", "candidate")),
        generation_mode=str(d.get("generation_mode", "founding")),
        parent_prompt_id=d.get("parent_prompt_id"),
        template_ref=dict(d.get("template_ref") or {}),
        prompt_hash=str(d.get("prompt_hash", "")),
        full_sha256=str(d.get("full_sha256", "")),
        evolvable=bool(d.get("evolvable", True)),
        epoch_introduced=str(d.get("epoch_introduced", "")),
        spec=dict(d.get("spec") or {}),
        schema_version=int(d.get("schema_version", PROMPT_SPEC_SCHEMA_VERSION)),
    )


# ── founding bootstrap (plan 07 §5.2) ────────────────────────────────────────

#: The v1 founding mapping: ``(prompt_id, loader key, role, evolvable,
#: output_schema)`` for every governed committed template. Order matters for
#: the registry's "latest active wins" role rollup, so each evolving role's
#: PRIMARY template (the one named ``format_prompt_id(role, 1)``) comes last
#: within its role. Roles come from Task 02's closed vocabulary; the five
#: v1-out-of-scope templates are registered ``evolvable=False`` (plan 07
#: §5.2) under the nearest vocabulary role (``generator`` for the four
#: text-producing ones, ``router`` for the raw-loaded root-idea selector).
#:
#: ``output_schema`` uses the reserved ``__reply__`` key for the reply KIND
#: (``bare_index`` / ``json_array`` / ``json_object`` / ``freeform``); other
#: keys are required JSON fields with type names (plan 07 §6 example).
FOUNDING_PROMPT_TABLE: tuple[tuple[str, str, str, bool, dict], ...] = (
    ("agent_system_prompt_v1", "agent/system", "generator", False,
     {"__reply__": "freeform"}),
    ("keyword_librarian_prompt_v1", "pipeline/keyword_librarian", "generator",
     False, {"__reply__": "freeform"}),
    ("viz_wizard_chat_goal_prompt_v1", "viz/wizard_chat_goal", "generator",
     False, {"__reply__": "freeform"}),
    ("viz_wizard_generate_config_prompt_v1", "viz/wizard_generate_config",
     "generator", False, {"__reply__": "json_object"}),
    ("root_idea_selector_prompt_v1", "orchestrator/root_idea_selector",
     "router", False, {"__reply__": "json_object", "chosen_index": "int"}),
    # The governance Auditor template. #78b made ``auditor`` a real registrable
    # ROLE (its COMPONENT is now founding — ``auditor_v1``), but this PROMPT
    # stays registered under the nearest vocabulary role ``reviewer``
    # (``evolvable=False``, BEFORE the reviewer primaries so the role rollup
    # stays ``reviewer_prompt_v1``) — moving it to an "auditor" prompt role
    # would add a key to ``active_prompt_hashes`` and change ``registry_version``
    # for no functional gain (the pipeline loads it by key, and impeachability
    # comes from the COMPONENT, not the prompt's role). See the plan-07 §5.2
    # precedent for out-of-scope templates.
    ("auditor_prompt_v1", "governance/auditor", "reviewer", False,
     {"__reply__": "json_object", "file_motion": "bool"}),
    ("reviewer_metrics_prompt_v1", "evaluator/extract_metrics", "reviewer",
     True, {"__reply__": "json_object"}),
    ("reviewer_prompt_v1", "evaluator/peer_review", "reviewer", True,
     {"__reply__": "json_object"}),
    # RQGM-native adversarial-loop templates (Task 06 actors), alphabetical
    # by adversary type; ids match the engine's per-type component family.
    ("adversary_cost_explosion_prompt_v1", "rqgm/adversary_cost_explosion",
     "adversary", True, {"__reply__": "json_object", "attack_claim": "string"}),
    ("adversary_evidence_gap_prompt_v1", "rqgm/adversary_evidence_gap",
     "adversary", True, {"__reply__": "json_object", "attack_claim": "string"}),
    ("adversary_metric_gaming_prompt_v1", "rqgm/adversary_metric_gaming",
     "adversary", True, {"__reply__": "json_object", "attack_claim": "string"}),
    ("adversary_overclaim_prompt_v1", "rqgm/adversary_overclaim",
     "adversary", True, {"__reply__": "json_object", "attack_claim": "string"}),
    ("adversary_prior_art_prompt_v1", "rqgm/adversary_prior_art",
     "adversary", True, {"__reply__": "json_object", "attack_claim": "string"}),
    ("adversary_prompt_injection_prompt_v1", "rqgm/adversary_prompt_injection",
     "adversary", True, {"__reply__": "json_object", "attack_claim": "string"}),
    ("adversary_reproducibility_prompt_v1", "rqgm/adversary_reproducibility",
     "adversary", True, {"__reply__": "json_object", "attack_claim": "string"}),
    # Defender role: the governance defense template first, the
    # adversarial-loop defender last (primary — the role rollup winner).
    ("governance_defender_prompt_v1", "governance/defender", "defender",
     True, {"__reply__": "json_object", "defense": "string"}),
    ("defender_prompt_v1", "rqgm/defender", "defender", True,
     {"__reply__": "json_object", "stance": "string"}),
    # Judge role: artifact judge + governance judge BEFORE the lineage
    # decision primary (``judge_prompt_v1`` stays the role rollup winner).
    ("artifact_judge_prompt_v1", "rqgm/judge_adjudication", "judge", True,
     {"__reply__": "json_object", "verdict": "string"}),
    ("governance_judge_prompt_v1", "governance/governance_judge", "judge",
     True, {"__reply__": "json_object", "outcome": "string"}),
    # Meta-tier prompt-evolution templates (Tasks 07/08).
    ("prompt_mutator_prompt_v1", "rqgm/prompt_mutator", "prompt_mutator",
     True, {"__reply__": "freeform"}),
    # Task 14: the PolicyMutator's meta template. Consumed ONLY by the
    # opt-in ``freeform_policy_proposal`` kind (the four default kinds are
    # pure arithmetic and never touch an LLM).
    ("policy_mutator_prompt_v1", "rqgm/policy_mutator", "policy_mutator",
     True, {"__reply__": "json_object"}),
    ("clean_room_generator_prompt_v1", "rqgm/clean_room_generator",
     "clean_room_generator", True, {"__reply__": "freeform"}),
    # plan 11 §5.2 items 3-4. Both roles were in the closed role vocabulary and
    # the capability matrix but had NO founding prompt, NO founding component
    # and NO invoker, so ``run_epoch_boundary_step`` never reached them: they
    # were governance vocabulary with nothing behind it. Each row's schema
    # names the ONE field its invoker returns, so a reply that omits it is
    # rejected by the sandbox rather than routed as an empty recommendation.
    ("replay_selector_prompt_v1", "rqgm/replay_selector", "replay_selector",
     True, {"__reply__": "json_object", "replay_case_ids": "list"}),
    ("failure_summary_compressor_prompt_v1",
     "rqgm/failure_summary_compressor", "failure_summary_compressor", True,
     {"__reply__": "json_object", "failure_summary": "dict"}),
    ("router_expand_select_prompt_v1", "orchestrator/bfts_expand_select",
     "router", True, {"__reply__": "bare_index"}),
    ("router_prompt_v1", "orchestrator/bfts_select", "router", True,
     {"__reply__": "bare_index"}),
    # Proposal-router generator templates (ari.rqgm.proposals.generators): the
    # cheap / mutation / prior_art prompts the router renders to mint the
    # FOUNDING proposal and boundary candidates. Without these, a proposal
    # record's prompt_hash was outside the frozen active set (pillar-1 gap the
    # kernel flags as CK-EPO-001: the run-seeding hypothesis was scored under an
    # ungoverned prompt). Registered here so the hash is governed+active;
    # evolvable=False (governed for accountability, not an evolution target).
    # Placed BEFORE generator_prompt_v1 so the "generator" role incumbent
    # (orchestrator/bfts_expand) — used by resolution — is unchanged.
    ("proposal_cheap_prompt_v1", "rqgm/proposal_cheap", "generator", False,
     {"__reply__": "json_object"}),
    ("proposal_mutation_prompt_v1", "rqgm/proposal_mutation", "generator", False,
     {"__reply__": "json_object"}),
    ("proposal_prior_art_prompt_v1", "rqgm/proposal_prior_art", "generator",
     False, {"__reply__": "json_object"}),
    ("generator_prompt_v1", "orchestrator/bfts_expand", "generator", True,
     {"__reply__": "json_array"}),
    ("judge_prompt_v1", "orchestrator/lineage_decision", "judge", True,
     {"__reply__": "json_object", "action": "string"}),
)

#: The founding COMPONENT set (FIX for the never-invoked bootstrap): one
#: entry per component id the RUNTIME actually stamps today —
#: ``adversary_{type}_v1`` / ``defender_v1`` / ``artifact_judge_v1``
#: (``ari.rqgm.adversarial.engine``), ``prompt_mutator_v1``
#: (``ari.rqgm.prompt_evolution``), ``clean_room_generator_v1``
#: (``ari.rqgm.clean_room``) and ``proposal_router_v1``
#: (``ari.rqgm.proposals.router``). #78b (2026-07-28): the governance
#: pipeline's ``auditor`` / ``evidence_clerk`` / ``governance_judge`` actors
#: are now founding components too (``auditor_v1`` / ``evidence_clerk_v1`` /
#: ``governance_judge_v1``) — previously they ran on unregistered ``*_v0``
#: bootstrap ids, so a motion targeting them was dropped as "unknown
#: component" and the judiciary that adjudicates everyone was itself
#: unimpeachable (a P4 gap). ``governance_judge`` was added to the role
#: vocabulary (``kernel_rules._GOVERNANCE_ROLES``, a re-pinned constitutional
#: amendment); ``auditor`` / ``evidence_clerk`` were already in the matrix.
#: The auditor / governance_judge components carry their governance prompt for
#: provenance (``auditor_prompt_v1`` / ``governance_judge_prompt_v1``, still
#: registered under their nearest ``reviewer`` / ``judge`` prompt roles — the
#: pipeline loads them by key, and no check ties a component's role to its
#: prompt's role); the ``evidence_clerk`` is deterministic (no LLM, no prompt)
#: so its ``prompt_id`` is ``None`` (schema-nullable). Rows are
#: ``(component_id, role, tier, prompt_id, capabilities)`` sorted by
#: ``component_id`` (deterministic registration order; the sole same-role
#: family — adversary — rolls up to its alphabetically-last member).
FOUNDING_COMPONENT_TABLE: tuple[tuple[str, str, str, str, dict], ...] = (
    ("adversary_cost_explosion_v1", "adversary", "institutional",
     "adversary_cost_explosion_prompt_v1", {}),
    ("adversary_evidence_gap_v1", "adversary", "institutional",
     "adversary_evidence_gap_prompt_v1", {}),
    ("adversary_metric_gaming_v1", "adversary", "institutional",
     "adversary_metric_gaming_prompt_v1", {}),
    ("adversary_overclaim_v1", "adversary", "institutional",
     "adversary_overclaim_prompt_v1", {}),
    ("adversary_prior_art_v1", "adversary", "institutional",
     "adversary_prior_art_prompt_v1", {}),
    ("adversary_prompt_injection_v1", "adversary", "institutional",
     "adversary_prompt_injection_prompt_v1", {}),
    ("adversary_reproducibility_v1", "adversary", "institutional",
     "adversary_reproducibility_prompt_v1", {}),
    ("artifact_judge_v1", "judge", "institutional",
     "artifact_judge_prompt_v1", {}),
    # #78b: the governance Auditor as a founding component (was auditor_v0).
    # Institutional governance actor (matrix: base + read/append audit_log). It
    # files impeachment motions; being registered makes it targetable by
    # motions/bans in turn (P3 — the auditor is inside the audit net).
    ("auditor_v1", "auditor", "institutional", "auditor_prompt_v1", {}),
    ("clean_room_generator_v1", "clean_room_generator", "meta",
     "clean_room_generator_prompt_v1",
     {"can_emit_candidates": True,
      "forbidden_targets": list(DEFAULT_FORBIDDEN_TARGETS)}),
    ("defender_v1", "defender", "institutional", "defender_prompt_v1", {}),
    # #78b: the Evidence Clerk as a founding component (was evidence_clerk_v0).
    # Deterministic (no LLM, no prompt — it assembles evidence bundles), so its
    # prompt_id is None (schema-nullable). Registered so it is impeachable like
    # every other governance actor.
    ("evidence_clerk_v1", "evidence_clerk", "institutional", None, {}),
    # plan 11 §5.2 items 3-4. Each declares ONLY the one action it performs:
    # capability flags are deny-by-default (``meta_rules.meta_action_denials``),
    # so neither can emit prompt candidates, and the five
    # ``META_HARD_DENIED_FLAGS`` stay absent (a meta entry setting any of them
    # is a schema violation, not merely a denial). No ``forbidden_targets``:
    # that key bounds which ROLES a candidate-emitting mutator may target, and
    # neither of these emits candidates.
    ("failure_summary_compressor_v1", "failure_summary_compressor", "meta",
     "failure_summary_compressor_prompt_v1",
     {"can_emit_failure_summary": True}),
    # #78b: the Governance Judge as a founding component (was
    # governance_judge_v0). ``governance_judge`` is a NEW role in the capability
    # matrix (constitutional amendment, re-pinned CONSTITUTION_HASH); it gets
    # the same institutional grants as the other two governance actors. The
    # judge that adjudicates every impeachment is now itself impeachable — with
    # #78a's self-adjudication recusal, it cannot dismiss its own motion. Prompt
    # provenance is governance_judge_prompt_v1 (registered under the "judge"
    # prompt role; the pipeline loads it by key).
    ("governance_judge_v1", "governance_judge", "institutional",
     "governance_judge_prompt_v1", {}),
    # The exploration artifact producer is a first-class governed subject.
    # Its prompt was already registered and epoch-frozen; registering the
    # matching component closes the provenance → validated attack →
    # reliability/impeachment path for the seven research adversaries.
    ("generator_v1", "generator", "institutional",
     "generator_prompt_v1", {}),
    # Task 14 (plan 14 §5.3): the score's proposer. Same minimal meta grants
    # as prompt_mutator_v1 — no authority the other meta agents lack, no
    # immunity they lack (P3: the thing that proposes the score is itself
    # governed, sanctionable and evolvable).
    ("policy_mutator_v1", "policy_mutator", "meta",
     "policy_mutator_prompt_v1",
     {"can_emit_candidates": True,
      "forbidden_targets": list(DEFAULT_FORBIDDEN_TARGETS)}),
    ("prompt_mutator_v1", "prompt_mutator", "meta",
     "prompt_mutator_prompt_v1",
     {"can_emit_candidates": True,
      "forbidden_targets": list(DEFAULT_FORBIDDEN_TARGETS)}),
    ("proposal_router_v1", "router", "institutional", "router_prompt_v1", {}),
    ("replay_selector_v1", "replay_selector", "meta",
     "replay_selector_prompt_v1",
     {"can_emit_replay_recommendation": True}),
    # Task 14 (plan 14 §5.3): the governed score itself. Declares NO
    # capabilities and may never acquire any — a policy that could
    # ``invoke`` or ``write registry`` is not a policy. Its prompt row is
    # NOT in FOUNDING_PROMPT_TABLE (the policy body is cfg-derived, not a
    # code constant): it is appended by
    # ``founding_registration_events(cfg)``. Listed last, after
    # proposal_router_v1, keeping this table sorted by component_id.
    (UTILITY_POLICY_COMPONENT_ID, "utility_policy", "institutional",
     UTILITY_POLICY_PROMPT_ID, {}),
)

#: Paper-archive founding tables (plan ari_rqgm_paper/03 §5.5), kept SEPARATE
#: from the exploration tables so they are PAPER-MODE-GATED: they enter the
#: registry only when ``include_paper=True`` is threaded through
#: :func:`build_founding_specs` / :func:`founding_registration_events` (which
#: the ``PaperArchiveRuntime`` bootstrap sets, and only it). An exploration
#: ``ari_rqgm`` boot never sees these rows, so ``registry_version()`` and the
#: ``epoch_000`` fingerprint of a non-paper run are byte-identical.
#:
#: The writer returns the ENTIRE corrected LaTeX document (freeform reply);
#: the reviewer returns the academic_reviewer.md JSON contract with the
#: selection-bearing ``accept_recommendation`` field typed. Both are
#: ``evolvable=True``, tier ``institutional`` (task agents, not meta), with
#: empty extra capability maps (the matrix grants are role-derived, §5.2).
#: Single template per role, so the "primary last per role" rollup convention
#: is satisfied trivially.
#: Paper-archive Task 05 (docs/plans/ari_rqgm_paper/05 §5.6): the eighth
#: adversary is a founding prompt AND a founding component, on exactly the
#: seven's ``(role, tier, evolvable)`` terms, so it is registry-governed and
#: SANCTIONABLE (P3) rather than resolving to an unregistered ad-hoc id that
#: ``resolve_transition`` drops as ``unknown component``. It lives in the
#: PAPER-MODE-GATED table (NOT the shared FOUNDING_PROMPT_TABLE) so an
#: exploration boot is byte-identical — this SUPERSEDES the plan's §5.6
#: "insert alphabetically into the shared adversary block" sketch, exactly as
#: plan 03 §6.1's "append to the shared FOUNDING_* table" was superseded by
#: these gated tables. One consequence (recorded, not silent): because the
#: gated block is registered AFTER the seven, the adversary PROMPT/COMPONENT
#: role rollup winner in paper mode becomes ``adversary_paper_self_preference``
#: rather than ``adversary_reproducibility`` — a DEVIATION from §5.6/§9's
#: "rollup unperturbed" claim. It is harmless: every adversary still stamps
#: its own ``adversary_{type}_v1`` id (the family guard in
#: ``engine._component_id`` falls the rollup winner back to each type's own
#: default), so no record's bytes change; only ``active_prompt_hashes[
#: "adversary"]`` — which already differs from exploration in paper mode — moves.
PAPER_FOUNDING_PROMPT_TABLE: tuple[tuple[str, str, str, bool, dict], ...] = (
    ("adversary_paper_self_preference_prompt_v1",
     "rqgm/adversary_paper_self_preference", "adversary", True,
     {"__reply__": "json_object", "attack_claim": "string"}),
    ("paper_reviewer_prompt_v1", "rqgm/paper_reviewer", "paper_reviewer", True,
     {"__reply__": "json_object", "accept_recommendation": "string"}),
    ("paper_writer_prompt_v1", "rqgm/paper_writer", "paper_writer", True,
     {"__reply__": "freeform"}),
)

#: Paper-archive founding components (plan ari_rqgm_paper/03 §5.5), sorted by
#: ``component_id`` like :data:`FOUNDING_COMPONENT_TABLE`.
PAPER_FOUNDING_COMPONENT_TABLE: tuple[tuple[str, str, str, str, dict], ...] = (
    # Task 05 §5.6: the id ``engine._component_id`` already stamps for a
    # paper_self_preference attack (engine.py:738-740 fallback), now
    # registry-resolvable so ``resolve_transition`` lands T9/T10/T11 on it
    # instead of ``unknown component``. Sorted by component_id like
    # FOUNDING_COMPONENT_TABLE (adversary_* sorts before paper_*).
    ("adversary_paper_self_preference_v1", "adversary", "institutional",
     "adversary_paper_self_preference_prompt_v1", {}),
    ("paper_reviewer_v1", "paper_reviewer", "institutional",
     "paper_reviewer_prompt_v1", {}),
    ("paper_writer_v1", "paper_writer", "institutional",
     "paper_writer_prompt_v1", {}),
)


def founding_spec_from_entry(
    entry,
    role: str,
    *,
    evolvable: bool,
    prompt_id: str | None = None,
    output_schema: dict | None = None,
    loader=None,
) -> PromptSpec:
    """Build the v1 founding :class:`PromptSpec` for one catalogue *entry*
    (:class:`ari.prompts.PromptEntry`).

    Pure bytes → spec (P2): hashes are recomputed from the template text via
    the injectable *loader* so ``prompt_hash == load_versioned(key)[1]`` by
    construction. Founding specs are ``active`` on creation — the documented
    sole lifecycle exception (they ARE the incumbents; plan 07 §5.2).
    """
    if loader is None:
        from ari.prompts import FilesystemPromptLoader

        loader = FilesystemPromptLoader()
    text, version_id = loader.load_versioned(entry.key)
    full = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if full[:12] != version_id:
        raise ValueError(
            f"loader version_id {version_id!r} is not sha256[:12] of the text"
        )
    return PromptSpec(
        prompt_id=prompt_id or format_prompt_id(role, 1),
        role=role,
        version=1,
        status="active",
        generation_mode="founding",
        parent_prompt_id=None,
        template_ref={"kind": "package", "key": entry.key},
        prompt_hash=version_id,
        full_sha256=full,
        evolvable=bool(evolvable),
        epoch_introduced="epoch_000",
        spec={
            # Founding templates carry their instruction in the committed
            # bytes; the spec body records the contract, not a copy.
            "role_instruction": "",
            "constitutional_constraints": list(
                REQUIRED_CONSTRAINTS_BY_ROLE.get(role, ())
            ),
            # Raw-loaded templates (never ``.format``-ed) get an EMPTY
            # placeholder contract — their literal JSON braces are not
            # placeholders (plan 07 §4).
            "input_contract": {
                "required_fields": (
                    []
                    if entry.key in RAW_LOADED_KEYS
                    else sorted(entry.placeholders)
                ),
            },
            "output_schema": dict(output_schema or {}),
            "rubric": {},
            "calibration_policy": {},
            "budget_policy": {},
        },
    )


def build_founding_specs(
    registry=None, loader=None, *, include_paper: bool = False
) -> list[PromptSpec]:
    """Deterministic v1 bootstrap: one founding spec per governed committed
    template, in :data:`FOUNDING_PROMPT_TABLE` order (plan 07 §5.2).

    *registry* is an injectable :class:`ari.prompts.PromptRegistry`
    (placeholder introspection); *loader* feeds
    :func:`founding_spec_from_entry`. Pure bytes → specs, no goldens needed.

    *include_paper* (plan ari_rqgm_paper/03 §5.5) appends the paper-archive
    founding specs (``paper_writer`` / ``paper_reviewer``). Default ``False``
    keeps the exploration boot byte-identical; the ``PaperArchiveRuntime`` is
    the only caller that sets it ``True`` (so its mutator can rebuild the
    paper incumbents).
    """
    if registry is None:
        from ari.prompts import PromptRegistry

        registry = PromptRegistry()
    table = FOUNDING_PROMPT_TABLE + (
        PAPER_FOUNDING_PROMPT_TABLE if include_paper else ()
    )
    out: list[PromptSpec] = []
    for prompt_id, key, role, evolvable, output_schema in table:
        entry = registry.describe(key)
        out.append(
            founding_spec_from_entry(
                entry,
                role,
                evolvable=evolvable,
                prompt_id=prompt_id,
                output_schema=output_schema,
                loader=loader,
            )
        )
    return out


def utility_policy_body_path(prompt_id: str) -> str:
    """The checkpoint-relative path of a governed policy body (plan 14 §6.1):
    ``rqgm_prompts/<prompt_id>.json``. Stated here (not imported from
    ``prompt_loader``) so this pure module stays I/O-free."""
    return f"{RQGM_PROMPTS_DIRNAME}/{prompt_id}.json"


def utility_policy_spec(
    body: dict,
    *,
    prompt_id: str = UTILITY_POLICY_PROMPT_ID,
    version: int = 1,
    status: str = "active",
    generation_mode: str = "founding",
    parent_prompt_id: str | None = None,
    epoch_introduced: str = "epoch_000",
) -> PromptSpec:
    """A policy-backed :class:`PromptSpec` over a utility-policy *body*
    (plan 14 §5.3). Pure: body → spec, no I/O.

    ``prompt_hash`` is ``hash12(canonical_json(body))``, which IS the body
    file's bytes' hash, which IS ``utility_policy_hash`` — one value, three
    names (see the ``TEMPLATE_REF_KINDS`` docstring for why this identity
    arithmetic is the whole reason a policy is registered as a "prompt").
    """
    text = canonical_json(body)
    full = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path = utility_policy_body_path(prompt_id)
    return PromptSpec(
        prompt_id=prompt_id,
        role=UTILITY_POLICY_ROLE,
        version=int(version),
        status=status,
        generation_mode=generation_mode,
        parent_prompt_id=parent_prompt_id,
        template_ref={"kind": POLICY_TEMPLATE_REF_KIND, "path": path},
        prompt_hash=full[:12],
        full_sha256=full,
        evolvable=True,
        epoch_introduced=epoch_introduced,
        spec={
            # A policy is a document, not an actor: no role_instruction, no
            # constraint clauses (§5.2), no input/output contract, no
            # rubric. The ONE Task-14 key names the body path — the body is
            # never inlined here, because two copies of a hashed object is
            # exactly the split-brain the registry refuses.
            "role_instruction": "",
            "constitutional_constraints": [],
            "input_contract": {"required_fields": []},
            "output_schema": {},
            "rubric": {},
            "calibration_policy": {},
            "budget_policy": {},
            "utility_policy_ref": path,
        },
    )


def founding_utility_policy_spec(cfg) -> PromptSpec:
    """The epoch-0 utility policy as a founding spec (plan 14 §5.3).

    It is ``cfg``-derived, so it is deliberately NOT a member of
    :data:`FOUNDING_PROMPT_TABLE` — that table's reproducibility claim is
    about frozen CODE constants. Pure: cfg → spec, no I/O (the body bytes
    are written by the caller through
    ``ari.rqgm.prompt_loader.write_evolved_policy_body``).

    The founding policy is exactly ``capture_utility_policy(cfg)``'s body,
    i.e. today's behavior: a run that never adopts a successor freezes this
    policy in every epoch, with a constant hash, exactly as before Task 14.
    """
    from ari.rqgm.state import utility_policy_body

    return utility_policy_spec(utility_policy_body(cfg))


def founding_registration_payloads(
    specs: "list[PromptSpec] | None" = None,
) -> list[dict]:
    """``prompt_registered`` event payloads for the founding specs, ready for
    Task 02's :class:`ari.rqgm.store.EpochTransaction` (registration stays
    the event log's job — this module never writes the registry)."""
    if specs is None:
        specs = build_founding_specs()
    payloads: list[dict] = []
    for spec in specs:
        payloads.append(
            {
                "prompt_id": spec.prompt_id,
                "role": spec.role,
                "status": spec.status,
                "prompt_hash": spec.prompt_hash,
                "prompt_sha256": spec.full_sha256,
                "source": prompt_source(spec),
                "spec_ref": spec.prompt_id,
                "epoch_id": spec.epoch_introduced,
                "source_refs": [],
            }
        )
    return payloads


def prompt_source(spec: PromptSpec) -> dict:
    """The registry ``source`` block for *spec* — text is referenced by
    source, never inlined (``registry.GovernedPromptEntry``).

    A Task-14 ``policy`` spec references its write-once canonical-JSON body
    by checkpoint-relative path; every other founding spec references its
    committed loader key.
    """
    if str(spec.template_ref.get("kind", "")) == POLICY_TEMPLATE_REF_KIND:
        return {
            "kind": POLICY_TEMPLATE_REF_KIND,
            "path": str(spec.template_ref.get("path", "")),
        }
    return {
        "kind": "committed_template",
        "key": str(spec.template_ref.get("key", "")),
    }


def build_paper_founding_specs(loader=None) -> list[PromptSpec]:
    """The paper-archive founding specs only (plan ari_rqgm_paper/03 §5.5).

    Pure bytes → specs over :data:`PAPER_FOUNDING_PROMPT_TABLE`; used by the
    paper boundary to rebuild the ``paper_writer`` / ``paper_reviewer``
    incumbents for mutation and by :func:`founding_registration_events` under
    ``include_paper=True``."""
    from ari.prompts import PromptRegistry

    registry = PromptRegistry()
    out: list[PromptSpec] = []
    for prompt_id, key, role, evolvable, output_schema in (
        PAPER_FOUNDING_PROMPT_TABLE
    ):
        entry = registry.describe(key)
        out.append(
            founding_spec_from_entry(
                entry, role, evolvable=evolvable, prompt_id=prompt_id,
                output_schema=output_schema, loader=loader,
            )
        )
    return out


def founding_component_payloads(*, include_paper: bool = False) -> list[dict]:
    """``component_registered`` event payloads for the founding components
    (:data:`FOUNDING_COMPONENT_TABLE` order — sorted by ``component_id``,
    deterministic). Like the prompt payloads, registration stays the event
    log's job — this module never writes the registry.

    *include_paper* (plan ari_rqgm_paper/03 §5.5) appends the paper-archive
    founding components (paper-mode-gated; default ``False`` keeps
    exploration byte-identical)."""
    table = FOUNDING_COMPONENT_TABLE + (
        PAPER_FOUNDING_COMPONENT_TABLE if include_paper else ()
    )
    payloads: list[dict] = []
    for component_id, role, tier, prompt_id, capabilities in table:
        payloads.append(
            {
                "component_id": component_id,
                "role": role,
                "tier": tier,
                "status": "active",
                "prompt_id": prompt_id,
                "epoch_id": "epoch_000",
                "source_refs": [],
                "capabilities": dict(capabilities),
            }
        )
    return payloads


def founding_registration_events(
    cfg=None, *, include_paper: bool = False
) -> list[tuple[str, dict]]:
    """The full founding bootstrap as ordered ``(event_type, payload)``
    pairs: every prompt in :data:`FOUNDING_PROMPT_TABLE` order (primaries
    last per role — the rollup convention), then the Task-14
    ``utility_policy`` row when a *cfg* is supplied, then every component in
    :data:`FOUNDING_COMPONENT_TABLE` order.

    Reproducibility (amended by plan 14 §5.3): the tables are frozen code
    constants, so with ``cfg=None`` the emitted sequence — and therefore
    ``registry_version()`` and the ``epoch_000`` fingerprint — is
    reproducible across boots and machines (P2). WITH a *cfg*, the sequence
    is reproducible **for a fixed resolved cfg**: the founding utility
    policy's bytes are cfg-derived (§5.3), and ``registry_version()`` hashes
    ``prompt_sha256`` values.

    That honesty costs nothing new: ``epoch_fingerprint`` has ALWAYS
    included ``utility_policy`` (``state.epoch_state_payload``), so the
    epoch-0 identity of an ``ari_rqgm`` run has always been cfg-derived.
    Task 14 extends the same dependence to ``registry_version``, aligning
    the two identities rather than splitting them. The alternative — a
    founding policy that ignores cfg — would silently discard every user's
    configured axis weights at epoch 0, a far worse surprise.

    ``cfg=None`` keeps today's exact sequence, so every existing caller and
    test is unaffected.
    """
    prompt_payloads = founding_registration_payloads()
    if cfg is not None:
        prompt_payloads = prompt_payloads + founding_registration_payloads(
            [founding_utility_policy_spec(cfg)]
        )
    # Paper-archive founding prompts (plan ari_rqgm_paper/03 §5.5) — appended
    # AFTER the exploration + utility-policy prompts so the exploration
    # sequence (``include_paper=False``, the default) is byte-identical.
    if include_paper:
        prompt_payloads = prompt_payloads + founding_registration_payloads(
            build_paper_founding_specs()
        )
    return (
        [("prompt_registered", p) for p in prompt_payloads]
        + [
            ("component_registered", p)
            for p in founding_component_payloads(include_paper=include_paper)
        ]
    )


def verify_spec_hash(spec: PromptSpec, text: str) -> bool:
    """True iff *text*'s bytes hash to the spec's recorded identity — the
    deterministic primitive behind the kernel's no-in-place-mutation check."""
    return hash12(text) == spec.prompt_hash
