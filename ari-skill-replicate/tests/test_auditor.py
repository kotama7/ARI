"""Tests for auditor.py."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

import auditor as A
import generator as G
import manifest as M

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _leaf(text: str, quote: str = "the mask network outputs 0 for critical steps") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": text,
        "weight": 1,
        "sub_tasks": [],
        "task_category": "Code Development",
        "finegrained_task_category": "Method Implementation",
        "rationale_from_paper": {"section": "§1", "quote": quote},
    }


def _frozen_envelope_with_leaves(leaves: list[dict], paper_text: str) -> dict:
    env = {
        "reproduce_contract": {"script_path": "reproduce.sh", "max_runtime_sec": 7200},
        "rubric": {
            "id": str(uuid.uuid4()),
            "requirements": "Replicate the paper's main contribution.",
            "weight": 1,
            "sub_tasks": leaves,
        },
    }
    return M.freeze(env, generator_model="m", prompt="p", paper_text=paper_text)


# ── deterministic checks ──

def test_detect_vague_qualifier():
    assert A.detect_vague_qualifier("The output is appropriate for the task.")
    assert A.detect_vague_qualifier("The code is well-organized.")
    assert A.detect_vague_qualifier("The implementation is good and clear.")
    assert not A.detect_vague_qualifier("The MaskNetwork outputs 0 for critical states.")


def test_detect_no_paper_evidence():
    paper = "the mask network outputs 0 for critical steps and 1 otherwise."
    leaf_ok = _leaf("X", quote="the mask network outputs 0 for critical steps")
    leaf_bad = _leaf("X", quote="this quote is not present in the paper")
    assert A.detect_no_paper_evidence(leaf_ok, paper) is False
    assert A.detect_no_paper_evidence(leaf_bad, paper) is True


def test_detect_duplicates():
    a = _leaf("Same definite requirement.")
    b = _leaf("Same definite requirement.")
    c = _leaf("Different requirement entirely.")
    dups = A.detect_duplicates([a, b, c])
    assert a["id"] in dups
    assert b["id"] in dups
    assert c["id"] not in dups


# ── orchestrator ──

@pytest.mark.asyncio
async def test_audit_writes_flags_and_metadata(tmp_path):
    paper = (FIXTURES / "paper_simple.tex").read_text()
    leaves = [
        _leaf("The MaskNetwork class outputs 0 for inputs identified as critical states.",
              quote="The MaskNetwork class outputs 0 for inputs identified as critical states"),
        _leaf("The implementation is appropriate and well-organized.",
              quote="The MaskNetwork class outputs 0 for inputs identified as critical states"),
        _leaf("Same definite requirement about Experiment II.",
              quote="Experiment II runs the selfish mining environment"),
        _leaf("Same definite requirement about Experiment II.",
              quote="Experiment II runs the selfish mining environment"),
        _leaf("Some claim that does not appear anywhere in the paper.",
              quote="this exact text does not exist in the fixture paper xyzzy"),
    ]
    frozen = _frozen_envelope_with_leaves(leaves, paper)
    p = tmp_path / "rubric.json"
    p.write_text(json.dumps(frozen))

    async def no_llm(prompt: str) -> dict:
        return {}

    res = await A.audit_rubric_async(
        rubric_path=str(p),
        paper_text=paper,
        auditor_model="test/mock",
        llm_call=no_llm,
    )

    assert res["leaves_total"] == 5
    assert res["by_flag"]["vague_qualifier"] >= 1
    assert res["by_flag"]["duplicate"] == 2
    assert res["by_flag"]["no_paper_evidence"] >= 1

    # rubric file mutated with flags + audit metadata
    after = json.loads(p.read_text())
    assert "audit" in after
    assert after["audit"]["auditor_model"] == "test/mock"
    found_vague = any("vague_qualifier" in (n.get("flags") or [])
                      for n in after["rubric"]["sub_tasks"])
    assert found_vague


@pytest.mark.asyncio
async def test_audit_regen_recommended_threshold(tmp_path):
    paper = "the quote text appears verbatim here."
    # 6 of 6 leaves vague → 100% > 20% → regen_recommended = True
    leaves = [
        _leaf(f"This is appropriate for case {i}.", quote="the quote text appears verbatim")
        for i in range(6)
    ]
    frozen = _frozen_envelope_with_leaves(leaves, paper)
    p = tmp_path / "rubric.json"
    p.write_text(json.dumps(frozen))

    async def no_llm(prompt: str) -> dict:
        return {}

    res = await A.audit_rubric_async(
        rubric_path=str(p), paper_text=paper, auditor_model="m", llm_call=no_llm,
    )
    assert res["regen_recommended"] is True


@pytest.mark.asyncio
async def test_audit_no_regen_when_clean(tmp_path):
    paper = "the quote text appears verbatim here, repeatedly."
    leaves = [
        _leaf(f"Definite verifiable claim about implementation step {i}.",
              quote="the quote text appears verbatim")
        for i in range(8)
    ]
    frozen = _frozen_envelope_with_leaves(leaves, paper)
    p = tmp_path / "rubric.json"
    p.write_text(json.dumps(frozen))

    async def no_llm(prompt: str) -> dict:
        return {}

    res = await A.audit_rubric_async(
        rubric_path=str(p), paper_text=paper, auditor_model="m", llm_call=no_llm,
    )
    assert res["regen_recommended"] is False
    assert res["leaves_flagged"] == 0


@pytest.mark.asyncio
async def test_audit_invokes_llm_for_unverifiable(tmp_path):
    paper = "the quote text appears verbatim here."
    leaves = [
        _leaf("Step A: a definite verifiable claim.", quote="the quote text appears verbatim"),
        _leaf("Step B: a definite verifiable claim.", quote="the quote text appears verbatim"),
    ]
    frozen = _frozen_envelope_with_leaves(leaves, paper)
    p = tmp_path / "rubric.json"
    p.write_text(json.dumps(frozen))

    calls = {"n": 0}

    async def llm(prompt: str) -> dict:
        calls["n"] += 1
        # First leaf: flagged unverifiable; second: clean.
        if calls["n"] == 1:
            return {"vague_qualifier": False, "unverifiable": True, "concerns": "needs network"}
        return {"vague_qualifier": False, "unverifiable": False, "concerns": ""}

    res = await A.audit_rubric_async(
        rubric_path=str(p), paper_text=paper, auditor_model="test/mock", llm_call=llm,
    )
    assert calls["n"] == 2
    assert res["by_flag"]["unverifiable"] == 1
