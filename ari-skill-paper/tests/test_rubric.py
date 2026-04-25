"""Tests for the rubric loader and review engine (v0.6.0)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.rubric import (  # type: ignore
    DEFAULT_RUBRIC_DIRS,
    Rubric,
    RubricError,
    list_available_rubrics,
    load_rubric,
)
from src.review_engine import (  # type: ignore
    build_system_prompt,
    build_user_prompt,
    decide,
    fewshot_block,
    load_static_fewshot,
    normalize_review,
    resolve_rubric,
    run_ensemble,
    run_meta_review,
    run_single_review,
)


# ----- rubric loader -----

def test_neurips_rubric_loads():
    r = load_rubric("neurips")
    assert r.id == "neurips"
    assert r.venue == "NeurIPS"
    assert "soundness" in r.dimension_names()
    assert "presentation" in r.dimension_names()
    assert "contribution" in r.dimension_names()
    assert "overall" in r.dimension_names()
    assert "confidence" in r.dimension_names()
    assert r.hash  # SHA256 populated
    assert r.params.num_reflections == 5
    assert r.params.num_fs_examples == 1
    assert r.params.num_reviews_ensemble == 1
    assert r.params.temperature == 0.75
    assert r.params.fewshot_mode == "static"


def test_sc_rubric_has_reproducibility_dimension():
    r = load_rubric("sc")
    names = r.dimension_names()
    assert "reproducibility" in names
    assert "scalability_evaluation" in names
    assert r.params.fewshot_mode == "static"  # dynamic unsupported for SC


def test_all_venues_load():
    ids = [
        "neurips", "iclr", "icml", "cvpr", "acl", "sc", "chi",
        "usenix_security", "osdi", "stoc", "icra", "siggraph",
        "nature", "journal_generic", "workshop", "generic_conference",
    ]
    for rid in ids:
        r = load_rubric(rid)
        assert r.id == rid, f"{rid} id mismatch: {r.id}"
        assert len(r.score_dimensions) >= 1
        assert r.hash, f"{rid} hash missing"


def test_unknown_rubric_raises():
    with pytest.raises(RubricError):
        load_rubric("definitely_not_a_real_venue_xyz")


def test_list_available_rubrics_returns_all():
    rubrics = list_available_rubrics()
    ids = {r["id"] for r in rubrics}
    expected = {
        "neurips", "iclr", "icml", "cvpr", "acl", "sc", "chi",
        "usenix_security", "osdi", "stoc", "icra", "siggraph",
        "nature", "journal_generic", "workshop", "generic_conference",
    }
    assert expected.issubset(ids), f"missing: {expected - ids}"


def test_rubric_hash_is_deterministic():
    """Same file content -> same hash across multiple loads."""
    r1 = load_rubric("neurips")
    r2 = load_rubric("neurips")
    assert r1.hash == r2.hash
    assert len(r1.hash) == 64  # SHA256 hex


# ----- review engine: prompt builders -----

def test_system_prompt_contains_dimensions():
    r = load_rubric("neurips")
    sp = build_system_prompt(r)
    assert "soundness" in sp
    assert "presentation" in sp
    assert "contribution" in sp
    assert "overall" in sp
    assert "decision" in sp.lower()
    assert "NeurIPS" in sp


def test_system_prompt_respects_venue():
    r = load_rubric("sc")
    sp = build_system_prompt(r)
    assert "Supercomputing" in sp or "SC" in sp
    assert "reproducibility" in sp
    assert "scalability_evaluation" in sp


def test_user_prompt_excludes_vlm_and_experiment_context():
    """Reviewer-independence contract: build_user_prompt must NOT inject
    VLM findings, the experiment brief, or the figures manifest into the
    text reviewer's user prompt. This keeps ARI's text reviewer output
    directly comparable to AI Scientist v2's perform_review, and avoids
    anchoring the LLM review to upstream automated tools.
    See review_engine.py:build_user_prompt docstring and workflow.yaml
    merge_reviews stage for how VLM output is re-attached post-hoc.
    """
    r = load_rubric("neurips")
    prompt = build_user_prompt(r, "paper body text", ["caption A"], "cite note")
    # Body + captions + citation audit remain
    assert "paper body text" in prompt
    assert "caption A" in prompt
    assert "cite note" in prompt
    # VLM-specific tokens must not appear
    assert "VLM" not in prompt
    assert "vlm_findings" not in prompt
    assert "axis labels missing" not in prompt  # would leak if injected
    # Experiment brief / figures manifest must not appear
    assert "Experiment context:" not in prompt
    assert "Figures manifest:" not in prompt


def test_user_prompt_handles_empty_captions():
    r = load_rubric("neurips")
    prompt = build_user_prompt(r, "body", [], "cite")
    assert "body" in prompt
    assert "(none)" in prompt   # captions placeholder when empty


# ----- decision logic -----

def test_binary_decision_accepts_on_threshold():
    r = load_rubric("neurips")
    assert decide(r, {"overall": 7}) == "accept"
    assert decide(r, {"overall": 5}) == "reject"
    assert decide(r, {"overall": 6}) == "accept"  # >= threshold


def test_categorical_decision_maps_to_options():
    r = load_rubric("sc")
    opts = r.decision.options  # [accept, weak_accept, borderline, weak_reject, reject]
    assert decide(r, {"overall": 5}) == opts[0]  # highest → accept
    assert decide(r, {"overall": 1}) == opts[-1]  # lowest → reject


# ----- normalize -----

def test_normalize_review_clamps_out_of_range():
    r = load_rubric("neurips")
    raw = {
        "soundness": 9,  # beyond scale hi=4 → clamp to 4
        "presentation": 0,  # below lo=1 → clamp to 1
        "contribution": 3,
        "overall": 7,
        "confidence": 4,
        "strengths": "s",
        "weaknesses": "w",
        "questions": "q",
        "decision": "accept",
    }
    out = normalize_review(r, raw)
    assert out["scores"]["soundness"] == 4
    assert out["scores"]["presentation"] == 1
    assert out["decision"] == "accept"
    assert out["rubric_id"] == "neurips"
    assert out["rubric_hash"] == r.hash
    assert out["overall_score"] == 7


def test_normalize_review_autofills_decision_when_missing():
    r = load_rubric("neurips")
    raw = {"soundness": 3, "presentation": 3, "contribution": 2, "overall": 3, "confidence": 3}
    out = normalize_review(r, raw)
    # overall=3 < 6 → reject
    assert out["decision"] == "reject"


# ----- fewshot -----

def test_static_fewshot_loads_from_neurips_dir():
    r = load_rubric("neurips")
    examples = load_static_fewshot(r)
    assert len(examples) == r.params.num_fs_examples
    assert examples[0].review_json.get("soundness") is not None


def test_static_fewshot_respects_n_zero():
    r = load_rubric("sc")  # num_fs_examples=0
    assert load_static_fewshot(r) == []


def test_fewshot_block_formats_examples():
    r = load_rubric("neurips")
    examples = load_static_fewshot(r)
    block = fewshot_block(examples)
    assert "EXAMPLE REVIEW" in block
    assert "END EXAMPLES" in block


def test_fewshot_block_empty_returns_empty_string():
    assert fewshot_block([]) == ""


# ----- resolve_rubric / env fallback -----

def test_resolve_rubric_arg_wins(monkeypatch):
    monkeypatch.setenv("ARI_RUBRIC", "sc")
    r = resolve_rubric("iclr")
    assert r.id == "iclr"


def test_resolve_rubric_env_fallback(monkeypatch):
    monkeypatch.setenv("ARI_RUBRIC", "sc")
    r = resolve_rubric(None)
    assert r.id == "sc"


def test_resolve_rubric_default_neurips(monkeypatch):
    monkeypatch.delenv("ARI_RUBRIC", raising=False)
    r = resolve_rubric(None)
    assert r.id == "neurips"


def test_resolve_rubric_falls_back_to_neurips_on_missing(monkeypatch):
    """Legacy rubric was removed in v0.6.0; unknown rubric_id now falls
    back to neurips (the guaranteed-present default rubric).
    """
    monkeypatch.setenv("ARI_RUBRIC", "completely_made_up_venue_zzz")
    r = resolve_rubric(None)
    assert r.id == "neurips"


# ----- end-to-end mocked LLM -----

class _FakeLLM:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def __call__(self, messages, temperature, model):
        self.calls.append(
            {"messages": messages, "temperature": temperature, "model": model}
        )
        if not self.responses:
            return "{}"
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_run_single_review_invokes_reflection_loop():
    r = load_rubric("neurips")
    r.params.num_reflections = 2
    good_json = json.dumps({
        "soundness": 3, "presentation": 3, "contribution": 3,
        "overall": 7, "confidence": 4,
        "strengths": "S", "weaknesses": "W", "questions": "Q",
        "decision": "accept",
    })
    llm = _FakeLLM([good_json] * 5)
    out = await run_single_review(r, "user prompt", llm, num_reflections=2)
    # initial + 2 reflections = 3 calls
    assert len(llm.calls) == 3
    assert out["decision"] == "accept"
    assert len(out["reflection_trace"]) == 3


@pytest.mark.asyncio
async def test_run_ensemble_runs_n_reviews():
    r = load_rubric("neurips")
    r.params.num_reviews_ensemble = 3
    r.params.num_reflections = 0  # keep test fast
    good_json = json.dumps({
        "soundness": 3, "presentation": 3, "contribution": 3,
        "overall": 6, "confidence": 3,
        "strengths": "S", "weaknesses": "W", "questions": "Q",
        "decision": "accept",
    })
    llm = _FakeLLM([good_json] * 10)
    reviews = await run_ensemble(r, "user", llm)
    assert len(reviews) == 3
    # temperatures should differ across ensemble members
    temps = [c["temperature"] for c in llm.calls]
    assert len(set(temps)) > 1


@pytest.mark.asyncio
async def test_meta_review_aggregates_ensemble():
    r = load_rubric("neurips")
    reviews = [
        {"scores": {"overall": 7, "soundness": 3, "presentation": 3, "contribution": 3, "confidence": 4},
         "overall_score": 7, "decision": "accept",
         "strengths": "a", "weaknesses": "b", "questions": "c"},
        {"scores": {"overall": 5, "soundness": 2, "presentation": 3, "contribution": 2, "confidence": 3},
         "overall_score": 5, "decision": "reject",
         "strengths": "a2", "weaknesses": "b2", "questions": "c2"},
    ]
    meta_raw = json.dumps({
        "soundness": 3, "presentation": 3, "contribution": 3,
        "overall": 6, "confidence": 4,
        "strengths": "aggregate s", "weaknesses": "aggregate w", "questions": "aggregate q",
        "decision": "accept",
    })
    llm = _FakeLLM([meta_raw])
    meta = await run_meta_review(r, reviews, llm)
    assert meta["decision"] == "accept"
    assert meta["scores"]["overall"] == 6
    assert meta["source_review_count"] if "source_review_count" in meta else True


@pytest.mark.asyncio
async def test_meta_review_single_review_shortcircuits():
    r = load_rubric("neurips")
    single = [{"scores": {"overall": 7}, "overall_score": 7, "decision": "accept"}]
    llm = _FakeLLM([])  # should not be called
    meta = await run_meta_review(r, single, llm)
    assert meta["overall_score"] == 7
    assert len(llm.calls) == 0


def test_default_rubric_dirs_includes_package_config():
    """Ensure the loader can find rubrics via the package-relative path."""
    found = False
    for d in DEFAULT_RUBRIC_DIRS:
        if not d:
            continue
        if Path(d).exists():
            yamls = list(Path(d).glob("*.yaml"))
            if any(y.stem == "neurips" for y in yamls):
                found = True
                break
    assert found, "neurips.yaml must be discoverable via DEFAULT_RUBRIC_DIRS"
