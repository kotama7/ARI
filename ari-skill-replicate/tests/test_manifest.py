"""Tests for manifest.py — sha256 freezing + PaperBench format conversion."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator

import manifest as M

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "replication_rubric.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema) -> Draft202012Validator:
    return Draft202012Validator(schema)


def _leaf(text: str = "The MaskNetwork class outputs 0 for critical states.") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": text,
        "weight": 2,
        "sub_tasks": [],
        "task_category": "Code Development",
        "finegrained_task_category": "Method Implementation",
        "rationale_from_paper": {"section": "§3.1", "quote": "the mask network outputs 0 for critical steps"},
    }


def _root() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": "Replicate the paper's main contribution.",
        "weight": 1,
        "sub_tasks": [_leaf(), _leaf("The reproduce.sh script runs Experiment II.")],
    }


def _bare_envelope() -> dict:
    return {
        "reproduce_contract": {"script_path": "reproduce.sh", "max_runtime_sec": 21600},
        "rubric": _root(),
    }


# ── compute_paper_sha256 / prompt_sha256 ──

def test_paper_sha256_deterministic():
    a = M.compute_paper_sha256("hello paper")
    b = M.compute_paper_sha256("hello paper")
    assert a == b
    assert len(a) == 64


def test_paper_sha256_changes_on_text_change():
    assert M.compute_paper_sha256("a") != M.compute_paper_sha256("b")


# ── freeze ──

def test_freeze_produces_schema_valid_envelope(validator):
    env = _bare_envelope()
    frozen = M.freeze(
        env,
        generator_model="gemini/gemini-2.5-pro",
        prompt="adversarial reviewer prompt body",
        paper_text="paper text",
        temperature=0.0,
        seed=42,
    )
    validator.validate(frozen)
    assert frozen["version"] == "3"
    assert len(frozen["paper_sha256"]) == 64
    assert frozen["generator"]["model"] == "gemini/gemini-2.5-pro"
    assert frozen["generator"]["seed"] == 42
    assert len(frozen["rubric_sha256"]) == 64


def test_freeze_is_deterministic_for_same_input():
    env1 = _bare_envelope()
    env2 = copy.deepcopy(env1)
    f1 = M.freeze(env1, generator_model="m", prompt="p", paper_text="t", temperature=0.0)
    f2 = M.freeze(env2, generator_model="m", prompt="p", paper_text="t", temperature=0.0)
    # rubric_sha256 must match because rubric content + reproduce_contract are
    # identical and the sha excludes generator (which has a wall-clock timestamp).
    assert f1["rubric_sha256"] == f2["rubric_sha256"]


# ── verify ──

def test_verify_round_trip():
    env = _bare_envelope()
    frozen = M.freeze(env, generator_model="m", prompt="p", paper_text="t")
    assert M.verify(frozen) is True


def test_verify_detects_tampering():
    env = _bare_envelope()
    frozen = M.freeze(env, generator_model="m", prompt="p", paper_text="t")
    frozen["rubric"]["sub_tasks"][0]["requirements"] = "tampered"
    assert M.verify(frozen) is False


def test_verify_ignores_audit_field():
    env = _bare_envelope()
    frozen = M.freeze(env, generator_model="m", prompt="p", paper_text="t")
    M.add_audit_metadata(frozen, auditor_model="claude-opus", flags_count=5)
    assert M.verify(frozen) is True


# ── to_paperbench_format ──

def test_to_paperbench_strips_metadata():
    env = _bare_envelope()
    frozen = M.freeze(env, generator_model="m", prompt="p", paper_text="t")
    pb = M.to_paperbench_format(frozen)
    # Top level must NOT have envelope wrappers
    assert "paper_sha256" not in pb
    assert "generator" not in pb
    assert "reproduce_contract" not in pb
    assert "rubric" not in pb
    # Top level IS a TaskNode
    assert pb["id"] == frozen["rubric"]["id"]
    assert pb["weight"] == 1
    assert len(pb["sub_tasks"]) == 2


def test_to_paperbench_strips_rationale_and_flags():
    env = _bare_envelope()
    env["rubric"]["sub_tasks"][0]["flags"] = ["vague_qualifier"]
    frozen = M.freeze(env, generator_model="m", prompt="p", paper_text="t")
    pb = M.to_paperbench_format(frozen)
    leaf = pb["sub_tasks"][0]
    assert "rationale_from_paper" not in leaf
    assert "flags" not in leaf


def test_to_paperbench_coerces_weight_to_int():
    env = _bare_envelope()
    env["rubric"]["sub_tasks"][0]["weight"] = 3.0  # not int
    frozen = M.freeze(env, generator_model="m", prompt="p", paper_text="t")
    pb = M.to_paperbench_format(frozen)
    assert isinstance(pb["sub_tasks"][0]["weight"], int)
    assert pb["sub_tasks"][0]["weight"] == 3


def test_to_paperbench_recursive():
    deep = {
        "id": str(uuid.uuid4()),
        "requirements": "Deep grouping node for replication.",
        "weight": 5,
        "sub_tasks": [_leaf()],
    }
    env = {
        "reproduce_contract": {"script_path": "reproduce.sh", "max_runtime_sec": 1000},
        "rubric": {
            "id": str(uuid.uuid4()),
            "requirements": "Replicate the paper's main contribution.",
            "weight": 1,
            "sub_tasks": [deep],
        },
    }
    frozen = M.freeze(env, generator_model="m", prompt="p", paper_text="t")
    pb = M.to_paperbench_format(frozen)
    assert len(pb["sub_tasks"]) == 1
    assert len(pb["sub_tasks"][0]["sub_tasks"]) == 1


# ── audit metadata ──

def test_add_audit_metadata():
    env = _bare_envelope()
    frozen = M.freeze(env, generator_model="m", prompt="p", paper_text="t")
    M.add_audit_metadata(frozen, auditor_model="claude-opus-4-7", flags_count=3)
    assert frozen["audit"]["auditor_model"] == "claude-opus-4-7"
    assert frozen["audit"]["flags_count"] == 3
