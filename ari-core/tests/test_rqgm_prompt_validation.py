"""RQGM Task 07 — deterministic validation stages
(docs/concepts/rqgm_runtime_walkthrough.md "Prompt evolution — candidates
crawl, the RTE adopts"; docs/reference/file_formats.md
"prompt_evolution.jsonl (RQGM Task 07)").

Covers: static validation (placeholder drift, forbidden placeholders,
oversized templates, hash discipline, dead-parent lineage, in-place-mutation
detection, threshold_tuning non-numeric diffs, schema_tightening direction),
constitutional validation (missing mandatory constraints, clean_room
contamination rules, no instant activation, same-role generation),
``check_output_against_schema``, and the LLM-free guarantee of the
deterministic stages (import scan).

No test calls a real LLM (P2): the dry-run stage is exercised elsewhere via
injected fakes.
"""

from __future__ import annotations

import hashlib

from ari.rqgm.events import hash12
from ari.rqgm.prompt_evolution import (
    PromptCandidate,
    check_output_against_schema,
    constitutional_validation_failures,
    static_validation_failures,
)
from ari.rqgm.prompt_spec import (
    REQUIRED_CONSTRAINTS_BY_ROLE,
    PromptSpec,
    prompt_spec_from_dict,
)

INCUMBENT_TEXT = "Review {proposal} using {node_report}.\n"
CANDIDATE_TEXT = "Carefully review {proposal} using {node_report}.\n"


def _incumbent() -> PromptSpec:
    return PromptSpec(
        prompt_id="reviewer_prompt_v3",
        role="reviewer",
        version=3,
        status="active",
        generation_mode="mutation",
        parent_prompt_id="reviewer_prompt_v2",
        template_ref={"kind": "checkpoint",
                      "key": "rqgm_prompts/reviewer_prompt_v3"},
        prompt_hash=hash12(INCUMBENT_TEXT),
        full_sha256=hashlib.sha256(INCUMBENT_TEXT.encode()).hexdigest(),
        spec={
            "role_instruction": INCUMBENT_TEXT,
            "constitutional_constraints": list(
                REQUIRED_CONSTRAINTS_BY_ROLE["reviewer"]
            ),
            "input_contract": {
                "required_fields": ["node_report", "proposal"],
            },
            "output_schema": {"__reply__": "json_object",
                              "major_issues": "list",
                              "confidence": "float"},
            "rubric": {"novelty": "novel enough?"},
            "calibration_policy": {"confidence_threshold": 0.5,
                                   "all_accept_guard": True},
            "budget_policy": {"max_tokens": 1200},
        },
    )


def _candidate(
    text: str = CANDIDATE_TEXT,
    *,
    body_overrides: dict | None = None,
    **overrides,
) -> PromptCandidate:
    incumbent = _incumbent()
    body = dict(incumbent.spec)
    body["role_instruction"] = text
    body["input_contract"] = {"required_fields": ["node_report", "proposal"]}
    body.update(body_overrides or {})
    spec = prompt_spec_from_dict(
        {
            **incumbent.to_dict(),
            "prompt_id": "reviewer_prompt_v4",
            "version": 4,
            "status": "candidate",
            "parent_prompt_id": incumbent.prompt_id,
            "template_ref": {"kind": "checkpoint",
                             "key": "rqgm_prompts/reviewer_prompt_v4"},
            "prompt_hash": hash12(text),
            "full_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "spec": body,
        }
    )
    base = dict(
        record_id="pcand_00001",
        epoch_id="epoch_004",
        component_id="prompt_mutator_v1",
        prompt_hash=spec.prompt_hash,
        candidate_id="reviewer_prompt_v4",
        role="reviewer",
        generated_by={"component_id": "prompt_mutator_v1"},
        generation_mode="mutation",
        mutation_kind="freeform_mutation",
        source_prompt_id=incumbent.prompt_id,
        prompt_spec=spec.to_dict(),
    )
    base.update(overrides)
    return PromptCandidate(**base)


# ── static_validation — first stage, a pure function (no LLM, no budget) ─────


def test_clean_candidate_passes_static_validation():
    assert static_validation_failures(
        _candidate(), CANDIDATE_TEXT, incumbent=_incumbent(),
        known_specs={"reviewer_prompt_v3": _incumbent()},
    ) == []


def test_placeholder_drift_is_caught():
    drifted = "Review {proposal} using {web_search_results}.\n"
    failures = static_validation_failures(
        _candidate(drifted), drifted, incumbent=_incumbent()
    )
    assert any("placeholder" in f for f in failures)


def test_forbidden_placeholder_is_caught():
    tainted = "Review {proposal} {node_report} {raw_attack_text}.\n"
    cand = _candidate(
        tainted,
        body_overrides={
            "input_contract": {"required_fields": [
                "node_report", "proposal", "raw_attack_text",
            ]},
        },
    )
    failures = static_validation_failures(cand, tainted)
    assert any("forbidden placeholders" in f for f in failures)


def test_hash_mismatch_is_caught():
    failures = static_validation_failures(_candidate(), INCUMBENT_TEXT)
    assert any("prompt_hash" in f for f in failures)


def test_oversized_template_is_caught():
    cand = _candidate(
        body_overrides={"budget_policy": {"max_tokens": 2}}
    )
    failures = static_validation_failures(cand, CANDIDATE_TEXT)
    assert any("max_tokens" in f for f in failures)


def test_dead_or_missing_parent_is_caught():
    retired = prompt_spec_from_dict(
        {**_incumbent().to_dict(), "status": "retired"}
    )
    failures = static_validation_failures(
        _candidate(), CANDIDATE_TEXT,
        known_specs={"reviewer_prompt_v3": retired},
    )
    assert any("retired" in f for f in failures)
    failures = static_validation_failures(
        _candidate(), CANDIDATE_TEXT, known_specs={}
    )
    assert any("unknown" in f for f in failures)


def test_reused_prompt_id_with_different_bytes_is_caught():
    other = prompt_spec_from_dict(
        {**_incumbent().to_dict(), "prompt_id": "reviewer_prompt_v4",
         "prompt_hash": hash12("completely different bytes")}
    )
    failures = static_validation_failures(
        _candidate(), CANDIDATE_TEXT,
        known_specs={"reviewer_prompt_v3": _incumbent(),
                     "reviewer_prompt_v4": other},
    )
    assert any("in-place mutation" in f for f in failures)


def test_threshold_tuning_numeric_only_diff():
    # Legal: only numeric knobs (incl. the bool guards) change.
    ok = _candidate(
        INCUMBENT_TEXT,
        mutation_kind="threshold_tuning",
        body_overrides={
            "role_instruction": INCUMBENT_TEXT,
            "calibration_policy": {"confidence_threshold": 0.7,
                                   "all_accept_guard": False},
        },
    )
    assert static_validation_failures(
        ok, INCUMBENT_TEXT, incumbent=_incumbent()
    ) == []
    # Illegal: a non-numeric rubric string changes.
    bad = _candidate(
        INCUMBENT_TEXT,
        mutation_kind="threshold_tuning",
        body_overrides={
            "role_instruction": INCUMBENT_TEXT,
            "rubric": {"novelty": "reworded rubric"},
        },
    )
    failures = static_validation_failures(
        bad, INCUMBENT_TEXT, incumbent=_incumbent()
    )
    assert any("non-numeric" in f for f in failures)
    # Illegal: threshold_tuning rewrites the instruction text.
    rewrite = _candidate(mutation_kind="threshold_tuning")
    failures = static_validation_failures(
        rewrite, CANDIDATE_TEXT, incumbent=_incumbent()
    )
    assert any("role_instruction" in f for f in failures)


def test_schema_tightening_never_widens():
    # Legal: add a required field.
    tightened = _candidate(
        INCUMBENT_TEXT,
        mutation_kind="schema_tightening",
        body_overrides={
            "role_instruction": INCUMBENT_TEXT,
            "output_schema": {"__reply__": "json_object",
                              "major_issues": "list",
                              "confidence": "float",
                              "evidence_refs": "list"},
        },
    )
    assert static_validation_failures(
        tightened, INCUMBENT_TEXT, incumbent=_incumbent()
    ) == []
    # Illegal: drop a required field (loosening).
    loosened = _candidate(
        INCUMBENT_TEXT,
        mutation_kind="schema_tightening",
        body_overrides={
            "role_instruction": INCUMBENT_TEXT,
            "output_schema": {"__reply__": "json_object",
                              "major_issues": "list"},
        },
    )
    failures = static_validation_failures(
        loosened, INCUMBENT_TEXT, incumbent=_incumbent()
    )
    assert any("loosened" in f for f in failures)


def test_candidate_must_accept_incumbent_placeholder_set():
    # Key-swap safety: a candidate must accept the incumbent's EXACT
    # placeholder set, so narrowing it is rejected even when the declared
    # input_contract was narrowed to match.
    narrowed = "Review {proposal} only.\n"
    cand = _candidate(
        narrowed,
        body_overrides={"input_contract": {"required_fields": ["proposal"]}},
    )
    failures = static_validation_failures(
        cand, narrowed, incumbent=_incumbent()
    )
    assert any("incumbent's exact placeholder set" in f for f in failures)


# ── constitutional_validation — second stage, also a pure function ───────────


def test_clean_candidate_passes_constitutional_validation():
    assert constitutional_validation_failures(_candidate()) == []


def test_missing_mandatory_constraint_is_rejected():
    cand = _candidate(
        body_overrides={"constitutional_constraints": ["Be nice."]}
    )
    failures = constitutional_validation_failures(cand)
    assert any(
        "Do not override fixed verifier failures." in f for f in failures
    )


def test_clean_room_contamination_rules():
    # clean_room + source_prompt_id → forbidden (Task 08 rule).
    cand = _candidate(generation_mode="clean_room")
    failures = constitutional_validation_failures(cand)
    assert any("source_prompt_id" in f for f in failures)
    # clean_room referencing raw adjudication material → forbidden.
    cand = _candidate(
        generation_mode="clean_room", source_prompt_id=None,
        source_refs=("atk_000001",),
    )
    failures = constitutional_validation_failures(cand)
    assert any("raw adjudication" in f for f in failures)
    # mutation without lineage → forbidden.
    cand = _candidate(source_prompt_id=None)
    failures = constitutional_validation_failures(cand)
    assert any("source_prompt_id" in f for f in failures)


def test_no_instant_activation_is_constitutional():
    cand = _candidate(status="active")
    failures = constitutional_validation_failures(cand)
    assert any("must be 'candidate'" in f for f in failures)
    spec = dict(_candidate().prompt_spec)
    spec["status"] = "active"
    cand = _candidate(prompt_spec=spec)
    failures = constitutional_validation_failures(cand)
    assert any("prompt_spec.status" in f for f in failures)


def test_founding_mode_never_enters_the_pipeline():
    cand = _candidate(generation_mode="founding", source_prompt_id=None)
    failures = constitutional_validation_failures(cand)
    assert any("bootstrap-only" in f for f in failures)


def test_same_role_generation_is_rejected():
    roles = {"prompt_mutator_v1": "prompt_mutator", "reviewer_v2": "reviewer"}
    assert constitutional_validation_failures(
        _candidate(), component_roles=roles
    ) == []
    cand = _candidate(
        component_id="reviewer_v2",
        generated_by={"component_id": "reviewer_v2"},
    )
    failures = constitutional_validation_failures(
        cand, component_roles=roles
    )
    assert any("same-role" in f or "prompt_mutator" in f for f in failures)


# ── output-schema checker — the primitive the schema_dry_run stage uses ──────


def test_check_output_bare_index():
    assert check_output_against_schema("2", {"__reply__": "bare_index"}) == []
    assert check_output_against_schema(" 0 \n", {"__reply__": "bare_index"}) == []
    assert check_output_against_schema("first", {"__reply__": "bare_index"})


def test_check_output_json_object_fields_and_types():
    schema = {"__reply__": "json_object", "major_issues": "list",
              "confidence": "float", "recommended_action": "string"}
    good = '{"major_issues": [], "confidence": 0.8, "recommended_action": "revise"}'
    assert check_output_against_schema(good, schema) == []
    missing = '{"major_issues": []}'
    failures = check_output_against_schema(missing, schema)
    assert any("confidence" in f for f in failures)
    wrong_type = '{"major_issues": "none", "confidence": 0.8, "recommended_action": "x"}'
    failures = check_output_against_schema(wrong_type, schema)
    assert any("major_issues" in f for f in failures)
    assert check_output_against_schema("not json", schema)


def test_check_output_json_array_and_freeform():
    assert check_output_against_schema('[{"a": 1}]', {"__reply__": "json_array"}) == []
    assert check_output_against_schema('{"a": 1}', {"__reply__": "json_array"})
    assert check_output_against_schema("anything", {"__reply__": "freeform"}) == []
    assert check_output_against_schema("", {"__reply__": "freeform"})


# ── determinism guard: the deterministic stages import no LLM/network/random ─


def test_prompt_modules_are_offline_and_random_free():
    """The Task 07 modules perform zero LLM/network calls of their own and
    contain no randomness (P2); LLM access is injection-only."""
    import ari.rqgm.prompt_evolution as pe
    import ari.rqgm.prompt_loader as pl
    import ari.rqgm.prompt_records as pr
    import ari.rqgm.prompt_spec as ps

    for mod in (ps, pl, pr, pe):
        text = open(mod.__file__, encoding="utf-8").read()
        for forbidden in (
            "import litellm", "import requests", "import urllib",
            "import socket", "import http", "import random",
            "from ari.llm", "import openai",
        ):
            assert forbidden not in text, f"{mod.__name__}: {forbidden}"
