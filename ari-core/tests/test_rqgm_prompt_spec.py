"""RQGM Task 07 — PromptSpec schema + founding bootstrap
(docs/reference/rqgm_schemas.md "rqgm_prompt_spec.schema.json";
docs/concepts/rqgm_runtime_walkthrough.md "Founding registration — one
transaction, the whole institution").

Covers: schema round-trip + jsonschema validation, the founding bootstrap
mapping every governed committed template to a spec whose ``prompt_hash``
equals ``load_versioned(key)[1]`` (parity with the ``_EXPECTED_HASHES``
scheme — single hash scheme, no migration), empty placeholder contracts for
the raw-loaded templates, the role/evolvable assignment table, registration
payloads round-tripping through Task 02's replay path, and the
``prompt_registry_version`` stamped through ``record_prompt_use`` matching
Task 02's ``GovernedPromptRegistry.registry_version()`` (parity only — the
formula and its determinism tests are owned by Task 02).

No test calls a real LLM (P2).
"""

from __future__ import annotations

import hashlib
import json

import pytest

from ari.prompts import FilesystemPromptLoader, PromptRegistry
from ari.rqgm.prompt_spec import (
    FOUNDING_PROMPT_TABLE,
    RAW_LOADED_KEYS,
    REQUIRED_CONSTRAINTS_BY_ROLE,
    PromptSpec,
    build_founding_specs,
    founding_registration_payloads,
    founding_spec_from_entry,
    prompt_spec_from_dict,
    verify_spec_hash,
)


@pytest.fixture(autouse=True)
def _no_env_run_pin(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)


def _spec(**overrides) -> PromptSpec:
    base = dict(
        prompt_id="reviewer_prompt_v4",
        role="reviewer",
        version=4,
        status="candidate",
        generation_mode="mutation",
        parent_prompt_id="reviewer_prompt_v3",
        template_ref={"kind": "checkpoint",
                      "key": "rqgm_prompts/reviewer_prompt_v4"},
        prompt_hash="a" * 12,
        full_sha256="a" * 64,
        evolvable=True,
        epoch_introduced="epoch_004",
        spec={
            "role_instruction": "…",
            "constitutional_constraints": list(
                REQUIRED_CONSTRAINTS_BY_ROLE["reviewer"]
            ),
            "input_contract": {"required_fields": ["proposal"]},
            "output_schema": {"major_issues": "list", "confidence": "float"},
            "rubric": {},
            "calibration_policy": {"all_accept_guard": True},
            "budget_policy": {"max_tokens": 1200},
        },
    )
    base.update(overrides)
    return PromptSpec(**base)


# ── schema round-trip ────────────────────────────────────────────────────────
# PromptSpec is frozen, survives a dict round-trip, and validates against
# rqgm_prompt_spec.schema.json — which structurally rejects a second hash
# scheme and any generation_mode outside the enum.


def test_prompt_spec_round_trip():
    spec = _spec()
    clone = prompt_spec_from_dict(json.loads(json.dumps(spec.to_dict())))
    assert clone == spec


def test_prompt_spec_is_frozen():
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        _spec().prompt_hash = "b" * 12  # type: ignore[misc]


def test_prompt_spec_schema_validates():
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    schema = schemas.load("rqgm_prompt_spec.schema")
    jsonschema.validate(_spec().to_dict(), schema)
    for founding in build_founding_specs():
        jsonschema.validate(founding.to_dict(), schema)
    # A second hash scheme is rejected structurally.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            _spec(prompt_hash="not-a-hash12").to_dict(), schema
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            _spec(generation_mode="instant_activation").to_dict(), schema
        )


# ── founding bootstrap ───────────────────────────────────────────────────────
# One founding spec per governed committed template, each carrying
# prompt_hash == load_versioned(key)[1] — a single hash scheme, no migration.


def test_founding_table_covers_exactly_the_committed_inventory():
    """One founding spec per governed committed template: the 11 pre-RQGM
    keys PLUS every RQGM-native / governance actor template used at runtime
    (GAP-3 fix — previously those ran on ad-hoc ids outside registry
    governance). The three ``rqgm/proposal_*`` router templates are NOW governed
    too (evolvable=False): a proposal SEEDS the scored tree, so a record under an
    unregistered prompt tripped the kernel's epoch-invariance check (CK-EPO-001,
    "record prompt_hash outside the frozen active set"). Registering them puts
    their hash in the frozen active set — accountable/frozen, but not evolution
    targets. (Superseded the earlier "stay ungoverned — carry their own
    provenance" stance: self-provenance did not satisfy the epoch-freeze
    invariant for the run-seeding proposal.)"""
    keys = sorted(key for _pid, key, _r, _e, _o in FOUNDING_PROMPT_TABLE)
    assert keys == sorted(
        [
            "agent/system",
            "evaluator/extract_metrics",
            "evaluator/peer_review",
            "governance/auditor",
            "governance/defender",
            "governance/governance_judge",
            "orchestrator/bfts_select",
            "orchestrator/bfts_expand",
            "orchestrator/bfts_expand_select",
            "orchestrator/lineage_decision",
            "orchestrator/root_idea_selector",
            "pipeline/keyword_librarian",
            "rqgm/adversary_cost_explosion",
            "rqgm/adversary_evidence_gap",
            "rqgm/adversary_metric_gaming",
            "rqgm/adversary_overclaim",
            "rqgm/adversary_prior_art",
            "rqgm/adversary_prompt_injection",
            "rqgm/adversary_reproducibility",
            "rqgm/clean_room_generator",
            "rqgm/defender",
            # The two live meta actors: both emit RECOMMENDATIONS the caller
            # is free to widen, never decisions, which is what makes them safe
            # to evolve.
            "rqgm/failure_summary_compressor",
            "rqgm/replay_selector",
            "rqgm/judge_adjudication",
            # Task 14: the PolicyMutator's meta template. Reviewed expectation
            # update — the founding inventory genuinely gains one committed
            # template. The utility POLICY itself has no row here: its body is
            # cfg-derived, so it cannot live in a table whose contract is
            # "frozen code constants" (every row names a committed file).
            "rqgm/policy_mutator",
            "rqgm/prompt_mutator",
            # Proposal-router generator templates — governed so a proposal
            # record's prompt_hash is in the frozen active set (CK-EPO-001).
            "rqgm/proposal_cheap",
            "rqgm/proposal_mutation",
            "rqgm/proposal_prior_art",
            "viz/wizard_chat_goal",
            "viz/wizard_generate_config",
        ]
    )
    ids = [pid for pid, *_ in FOUNDING_PROMPT_TABLE]
    assert len(ids) == len(set(ids)), "founding prompt_ids must be unique"


def test_founding_specs_hash_identical_to_load_versioned():
    loader = FilesystemPromptLoader()
    for spec in build_founding_specs():
        key = spec.template_ref["key"]
        text, version_id = loader.load_versioned(key)
        assert spec.prompt_hash == version_id
        assert spec.full_sha256 == hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()
        assert spec.full_sha256[:12] == spec.prompt_hash
        assert verify_spec_hash(spec, text)
        # Founding identity invariants: every founding spec is generation_mode
        # "founding", active, version 1, parentless, and package-backed.
        assert spec.generation_mode == "founding"
        assert spec.status == "active"
        assert spec.version == 1
        assert spec.parent_prompt_id is None
        assert spec.template_ref["kind"] == "package"


def test_founding_role_and_evolvable_assignment():
    by_key = {
        s.template_ref["key"]: s for s in build_founding_specs()
    }
    assert by_key["orchestrator/bfts_select"].role == "router"
    assert by_key["orchestrator/bfts_expand_select"].role == "router"
    assert by_key["orchestrator/bfts_expand"].role == "generator"
    assert by_key["evaluator/peer_review"].role == "reviewer"
    assert by_key["evaluator/extract_metrics"].role == "reviewer"
    assert by_key["orchestrator/lineage_decision"].role == "judge"
    # RQGM-native actors (GAP-3): roles from the CLOSED Task 02 vocabulary.
    for adversary_key in (
        "rqgm/adversary_cost_explosion", "rqgm/adversary_evidence_gap",
        "rqgm/adversary_metric_gaming", "rqgm/adversary_overclaim",
        "rqgm/adversary_prior_art", "rqgm/adversary_prompt_injection",
        "rqgm/adversary_reproducibility",
    ):
        assert by_key[adversary_key].role == "adversary"
    assert by_key["rqgm/defender"].role == "defender"
    assert by_key["governance/defender"].role == "defender"
    assert by_key["rqgm/judge_adjudication"].role == "judge"
    assert by_key["governance/governance_judge"].role == "judge"
    assert by_key["rqgm/prompt_mutator"].role == "prompt_mutator"
    assert by_key["rqgm/policy_mutator"].role == "policy_mutator"
    assert by_key["rqgm/clean_room_generator"].role == "clean_room_generator"
    assert by_key["rqgm/replay_selector"].role == "replay_selector"
    assert (by_key["rqgm/failure_summary_compressor"].role
            == "failure_summary_compressor")
    # #78b made "auditor" a real registrable ROLE (its COMPONENT is founding,
    # auditor_v1), but this PROMPT stays under the nearest vocabulary role
    # "reviewer", evolvable=False — moving it to an "auditor" prompt role would
    # add an active_prompt_hashes key and shift registry_version for no gain
    # (the pipeline loads it by key; impeachability comes from the component).
    assert by_key["governance/auditor"].role == "reviewer"
    assert not by_key["governance/auditor"].evolvable
    evolvable = {k for k, s in by_key.items() if s.evolvable}
    assert evolvable == {
        # The two live meta actors. Being evolvable is the point: their prompt
        # bytes are what the PromptMutator now mints successors for.
        "rqgm/replay_selector",
        "rqgm/failure_summary_compressor",
        "orchestrator/bfts_select",
        "orchestrator/bfts_expand_select",
        "orchestrator/bfts_expand",
        "evaluator/peer_review",
        "evaluator/extract_metrics",
        "orchestrator/lineage_decision",
        "governance/defender",
        "governance/governance_judge",
        "rqgm/adversary_cost_explosion",
        "rqgm/adversary_evidence_gap",
        "rqgm/adversary_metric_gaming",
        "rqgm/adversary_overclaim",
        "rqgm/adversary_prior_art",
        "rqgm/adversary_prompt_injection",
        "rqgm/adversary_reproducibility",
        "rqgm/clean_room_generator",
        "rqgm/defender",
        "rqgm/judge_adjudication",
        "rqgm/prompt_mutator",
        # Task 14: the PolicyMutator's own template is evolved by the
        # PromptMutator like any other meta template (P3 — the thing that
        # proposes the score holds no immunity its siblings lack).
        "rqgm/policy_mutator",
    }
    # evolvable=True appears ONLY on roles in the evolvable vocabulary.
    from ari.rqgm.events import EVOLVABLE_ROLES

    for spec in by_key.values():
        if spec.evolvable:
            assert spec.role in EVOLVABLE_ROLES
    # Required role constraints are carried verbatim from bootstrap on.
    for spec in by_key.values():
        carried = spec.spec["constitutional_constraints"]
        for required in REQUIRED_CONSTRAINTS_BY_ROLE.get(spec.role, ()):
            assert required in carried


def test_raw_loaded_templates_get_empty_placeholder_contract():
    by_key = {s.template_ref["key"]: s for s in build_founding_specs()}
    for key in RAW_LOADED_KEYS:
        assert by_key[key].spec["input_contract"]["required_fields"] == []
    # A .format-ed template records its real placeholder set.
    assert by_key["orchestrator/bfts_select"].spec["input_contract"][
        "required_fields"
    ] == ["candidates", "experiment_goal", "memory_context"]


def test_founding_spec_from_entry_matches_catalogue():
    registry = PromptRegistry()
    entry = registry.describe("orchestrator/bfts_expand")
    spec = founding_spec_from_entry(entry, "generator", evolvable=True)
    assert spec.prompt_id == "generator_prompt_v1"
    assert spec.prompt_hash == entry.version_id
    assert spec.spec["input_contract"]["required_fields"] == sorted(
        entry.placeholders
    )


def test_founding_spec_rejects_divergent_loader_scheme():
    class _BadLoader:
        def load_versioned(self, key):
            return "text", "not-sha256-12"

    entry = PromptRegistry().describe("agent/system")
    with pytest.raises(ValueError):
        founding_spec_from_entry(
            entry, "generator", evolvable=False, loader=_BadLoader()
        )


# ── registration + provenance parity ─────────────────────────────────────────
# The founding payloads replay through Task 02's event log to an identical
# registry, and the version stamped into the prompt trace is that registry's
# own registry_version().


def _registry_from_founding():
    from ari.rqgm.registry import GovernedPromptRegistry, apply_registry_event

    comps: dict = {}
    prompts: dict = {}
    for payload in founding_registration_payloads():
        apply_registry_event(comps, prompts, "prompt_registered", payload)
    return GovernedPromptRegistry(prompts)


def test_registration_payloads_round_trip_through_task02_replay():
    registry = _registry_from_founding()
    assert len(registry.entries()) == len(FOUNDING_PROMPT_TABLE)
    text, version_id = registry.resolve_text("generator_prompt_v1")
    loader_text, loader_vid = FilesystemPromptLoader().load_versioned(
        "orchestrator/bfts_expand"
    )
    assert (text, version_id) == (loader_text, loader_vid)
    # "Latest active wins" resolves each evolving role to its primary spec.
    hashes = registry.active_prompt_hashes()
    assert hashes["router"] == FilesystemPromptLoader().load_versioned(
        "orchestrator/bfts_select"
    )[1]
    assert hashes["reviewer"] == FilesystemPromptLoader().load_versioned(
        "evaluator/peer_review"
    )[1]
    assert hashes["judge"] == FilesystemPromptLoader().load_versioned(
        "orchestrator/lineage_decision"
    )[1]


def test_record_prompt_use_stamps_task02_registry_version(tmp_path):
    """Under RQGM the reserved provenance fields are finally populated — and
    the stamped value IS Task 02's ``registry_version()`` (parity only)."""
    from ari.prompts import load_prompt_trace

    registry = _registry_from_founding()
    registry.record_use(
        "reviewer_prompt_v1", model="m", node_id="node_1", phase="bfts",
        checkpoint_dir=tmp_path,
    )
    rows = load_prompt_trace(tmp_path)
    assert len(rows) == 1
    assert rows[0]["prompt_version"] == "reviewer_prompt_v1"
    assert rows[0]["prompt_registry_version"] == registry.registry_version()
    assert rows[0]["prompt_name"] == "evaluator/peer_review"


def test_simple_bfts_leaves_reserved_provenance_fields_none(tmp_path):
    """simple_bfts never stamps the reserved fields: on the default path both
    prompt_version and prompt_registry_version stay None."""
    from ari.prompts import load_prompt_trace, record_prompt_use

    record_prompt_use("agent/system", "0" * 12, checkpoint_dir=tmp_path)
    rows = load_prompt_trace(tmp_path)
    assert rows[0]["prompt_version"] is None
    assert rows[0]["prompt_registry_version"] is None
