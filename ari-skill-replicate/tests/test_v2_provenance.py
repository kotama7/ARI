from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

import auditor as A
import generator as G


QUOTE = "The solver writes results.json after every completed experiment."
PAPER = f"A reproducibility fixture. {QUOTE} Latency is reported in milliseconds."


def _leaf(requirement: str, *, identifier: str = "invalid") -> dict:
    return {
        "id": identifier,
        "requirements": requirement,
        "weight": "2",
        "sub_tasks": [],
        "task_category": "Code Execution",
        "finegrained_task_category": "Experimental Setup",
        "rationale_from_paper": {"section": "Results", "quote": QUOTE},
    }


def _single_envelope() -> dict:
    return {
        "reproduce_contract": {
            "script_path": "reproduce.sh",
            "max_runtime_sec": 600,
            "expected_artifacts": ["results.json"],
        },
        "rubric": {
            "id": "also-invalid",
            "requirements": "Replicate the deterministic solver experiment.",
            "weight": 1,
            "sub_tasks": [_leaf("The solver execution writes results.json.")],
        },
    }


@pytest.mark.asyncio
async def test_v2_generation_records_calls_repairs_and_exact_leaf_contract(
    tmp_path: Path,
):
    async def model_call(prompt: str) -> str:
        if "SKELETON" in prompt:
            response = _single_envelope()
        else:
            response = {
                "id": "invalid-subtree",
                "requirements": "Replicate the deterministic solver experiment.",
                "weight": "2",
                "sub_tasks": [_leaf("The solver execution writes results.json.")],
            }
        return "```json\n" + json.dumps(response) + "\n```"

    output = tmp_path / "rubric.json"
    result = await G.generate_rubric_async(
        paper_text=PAPER,
        output_path=str(output),
        model="fixture/generator",
        model_revision="immutable-r1",
        provider="fixture",
        llm_call=model_call,
    )
    assert "error" not in result, result
    document = json.loads(output.read_text())
    assert document["schema_version"] == "ari.replication-rubric/v2"
    assert document["generator"]["quality_profile"] == "calibrated"
    assert len(document["generator"]["calls"]) == 2
    call = document["generator"]["calls"][0]
    for artifact_name in ("prompt", "raw_response"):
        artifact = call[artifact_name]
        payload = (tmp_path / artifact["relative_path"]).read_bytes()
        assert len(payload) == artifact["size_bytes"]
        assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]
    actions = {item["action"] for item in document["repair_ledger"]["actions"]}
    assert {
        "json-sanitize",
        "identity-normalize",
        "evidence-bind",
        "verification-bind",
    } <= actions
    leaf = document["rubric"]
    while leaf["sub_tasks"]:
        leaf = leaf["sub_tasks"][0]
    span = leaf["evidence_span"]
    assert span["kind"] == "paper-span"
    assert PAPER[span["start_char"] : span["end_char"]] == span["quote"]
    assert leaf["verification"]["kind"] == "log-pattern"


@pytest.mark.asyncio
async def test_hierarchical_partial_failure_is_not_silently_omitted(tmp_path: Path):
    parent_ok = "Replicate the solver's completed experiment output."
    parent_missing = "Replicate the unavailable auxiliary experiment."
    skeleton = {
        "reproduce_contract": {
            "script_path": "reproduce.sh",
            "max_runtime_sec": 600,
            "expected_artifacts": ["results.json"],
        },
        "rubric": {
            "id": str(uuid.uuid4()),
            "requirements": "Replicate the paper's reported experiments.",
            "weight": 1,
            "sub_tasks": [
                {
                    "id": str(uuid.uuid4()),
                    "requirements": parent_ok,
                    "weight": 1,
                    "target_subtree_leaves": 8,
                    "sub_tasks": [],
                },
                {
                    "id": str(uuid.uuid4()),
                    "requirements": parent_missing,
                    "weight": 1,
                    "target_subtree_leaves": 8,
                    "sub_tasks": [],
                },
            ],
        },
    }
    subtree = {
        "id": str(uuid.uuid4()),
        "requirements": parent_ok,
        "weight": 1,
        "sub_tasks": [
            _leaf(
                "The solver execution writes results.json.",
                identifier=str(uuid.uuid4()),
            )
        ],
    }

    async def model_call(prompt: str) -> str:
        if "SKELETON" in prompt:
            return json.dumps(skeleton)
        if parent_missing in prompt:
            raise RuntimeError("fixture subtree unavailable")
        return json.dumps(subtree)

    output = tmp_path / "rubric.json"
    result = await G.generate_rubric_async(
        paper_text=PAPER,
        output_path=str(output),
        model="fixture/generator",
        provider="fixture",
        llm_call=model_call,
        target_leaf_count=16,
        max_model_calls=8,
        subtree_concurrency=2,
    )
    assert "error" not in result, result
    assert result["partial_failures"]
    document = json.loads(output.read_text())
    assert document["generator"]["partial_failures"]
    assert any(
        action["action"] == "invalid-prune"
        for action in document["repair_ledger"]["actions"]
    )


@pytest.mark.asyncio
async def test_generation_model_call_budget_fails_closed(tmp_path: Path):
    skeleton = _single_envelope()

    async def model_call(prompt: str) -> str:
        return json.dumps(skeleton)

    result = await G.generate_rubric_async(
        paper_text=PAPER,
        output_path=str(tmp_path / "rubric.json"),
        model="fixture/generator",
        provider="fixture",
        llm_call=model_call,
        max_model_calls=1,
    )
    assert "error" in result
    assert len(result["model_calls"]) == 1


@pytest.mark.asyncio
async def test_audit_reports_same_model_as_not_independent_and_verifies_artifacts(
    tmp_path: Path,
):
    async def generator_call(prompt: str) -> str:
        return json.dumps(_single_envelope())

    rubric_path = tmp_path / "rubric.json"
    generated = await G.generate_rubric_async(
        paper_text=PAPER,
        output_path=str(rubric_path),
        model="fixture/shared",
        provider="fixture",
        llm_call=generator_call,
    )
    assert "error" not in generated
    before = rubric_path.read_bytes()

    async def audit_call(prompt: str) -> dict:
        return {"vague_qualifier": False, "unverifiable": False}

    result = await A.audit_rubric_async(
        rubric_path=str(rubric_path),
        paper_text=PAPER,
        auditor_model="fixture/shared",
        llm_call=audit_call,
    )
    assert result["independence_status"] == "not-independent"
    assert rubric_path.read_bytes() == before

    document = json.loads(rubric_path.read_text())
    prompt_path = (
        tmp_path / document["generator"]["calls"][0]["prompt"]["relative_path"]
    )
    prompt_path.write_text("tampered")
    with pytest.raises(ValueError, match="artifact bytes differ"):
        await A.audit_rubric_async(
            rubric_path=str(rubric_path),
            paper_text=PAPER,
            auditor_model="fixture/other",
            llm_call=audit_call,
        )


def test_calibration_corpus_detects_declared_deterministic_flags():
    fixture_path = (
        Path(__file__).resolve().parent / "fixtures" / "calibration_cases.json"
    )
    fixture = json.loads(fixture_path.read_text())
    paper = fixture["paper_text"]
    for case in fixture["cases"]:
        leaf = _leaf(case["requirements"], identifier=str(uuid.uuid4()))
        quote = case["quote"]
        start = paper.find(quote)
        leaf["rationale_from_paper"]["quote"] = quote
        leaf["evidence_span"] = {
            "kind": "paper-span",
            "section": "fixture",
            "quote": quote,
            "start_char": max(0, start),
            "end_char": max(0, start) + len(quote),
            "paper_sha256": hashlib.sha256(paper.encode()).hexdigest(),
        }
        observed: set[str] = set()
        if A.detect_vague_qualifier(case["requirements"]):
            observed.add("vague_qualifier")
        if A.detect_no_paper_evidence(leaf, paper):
            observed.add("no_paper_evidence")
        assert observed == set(case["expected_flags"]), case["id"]
