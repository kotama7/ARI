"""RQGM Task 13 — failure-injection machinery
(docs/guides/rqgm_evaluation.md §Failure injections).

The ten shipped specs in ``scripts/rqgm_eval/failure_injections.yaml`` are
valid, the ``eval_*`` namespace is disjoint from governance's ``adv_*`` /
``anchor_*`` case namespaces, fixture payloads exist, ``apply_injection`` is
deterministic + idempotent, the ``rqgm_injection_provenance.json`` marker
round-trips, and both eval filenames are registered in META_FILES and the
node-report internal-JSON blocklist.

No LLM, no network — pure file copies and JSON (P2).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ari.orchestrator.node_report.builder import _INTERNAL_JSON_NAMES
from ari.paths import PathManager
from ari.rqgm.evaluation.injection import (
    EVAL_ID_PREFIX,
    INJECTION_PROVENANCE_FILENAME,
    MECHANISMS,
    RESERVED_CASE_PREFIXES,
    apply_injection,
    default_specs_path,
    fixtures_root,
    load_injection_specs,
    read_injection_provenance,
    smoke_only_spec_ids,
    spec_violations,
    specs_digest,
    write_injection_provenance,
)
from ari.rqgm.evaluation.metrics import METRIC_REPORT_FILENAME

SPECS = load_injection_specs()
INJECTIONS = SPECS["injections"]
CONTROLS = SPECS["controls"]


# ── the shipped spec set ─────────────────────────────────────────────────────


def test_all_ten_injections_defined():
    assert len(INJECTIONS) == 10
    assert len(CONTROLS) >= 1
    assert default_specs_path().is_file()


@pytest.mark.parametrize(
    "spec", INJECTIONS + CONTROLS,
    ids=[s["injection_id"] for s in INJECTIONS + CONTROLS],
)
def test_every_spec_is_valid(spec):
    assert spec_violations(spec) == []


def test_ids_unique_and_eval_namespaced():
    ids = [s["injection_id"] for s in INJECTIONS + CONTROLS]
    assert len(ids) == len(set(ids))
    for injection_id in ids:
        assert injection_id.startswith(EVAL_ID_PREFIX)
        # Held out from what governance trains/audits on (plan 13 §5.3).
        assert not injection_id.startswith(RESERVED_CASE_PREFIXES)


def test_reserved_namespaces_match_governance():
    assert RESERVED_CASE_PREFIXES == ("adv_", "anchor_")
    from ari.rqgm.adversarial.records import format_case_id

    assert format_case_id(1).startswith("adv_")


def test_mechanism_split_matches_plan():
    by_mech = {}
    for spec in INJECTIONS:
        by_mech.setdefault(spec["mechanism"], []).append(
            spec["injection_id"]
        )
    assert set(by_mech) <= set(MECHANISMS)
    # Fixture: 1, 2, 3, 7, 9, 10 — scripted: 4, 5, 6, 8 (plan 13 §5.3).
    assert len(by_mech["fixture"]) == 6
    assert len(by_mech["scripted_component"]) == 4
    assert {s.split("_")[2] for s in by_mech["scripted_component"]} == {
        "004", "005", "006", "008",
    }


@pytest.mark.parametrize(
    "spec",
    [s for s in INJECTIONS + CONTROLS if s["mechanism"] == "fixture"],
    ids=[
        s["injection_id"]
        for s in INJECTIONS + CONTROLS
        if s["mechanism"] == "fixture"
    ],
)
def test_fixture_payloads_exist(spec):
    ref = str(spec["payload_ref"]).replace("fixtures/rqgm_eval/", "").strip("/")
    payload = fixtures_root() / ref
    assert payload.is_dir()
    assert any(payload.rglob("*"))


def test_scripted_specs_name_registered_doubles():
    from ari.rqgm.evaluation.doubles import DOUBLE_KEYS

    for spec in INJECTIONS:
        if spec["mechanism"] != "scripted_component":
            continue
        key = f"{spec['target_role']}/{spec['double']}"
        assert key in DOUBLE_KEYS, key


def test_every_spec_declares_detection_and_latency():
    for spec in INJECTIONS:
        expected = spec["expected_detection"]
        assert expected["channels"], spec["injection_id"]
        assert int(expected["max_latency_epochs"]) >= 0
        assert spec["min_condition"] in (
            "B0", "B2", "B4", "B5", "B6", "B7",
        ), spec["injection_id"]


# ── spec validation edges ────────────────────────────────────────────────────


def test_spec_violations_flag_bad_specs():
    assert spec_violations({}) != []
    bad_ns = dict(INJECTIONS[0], injection_id="adv_case_00001")
    assert any("namespace" in v for v in spec_violations(bad_ns))
    bad_mech = dict(INJECTIONS[0], mechanism="llm_prompt")
    assert any("mechanism" in v for v in spec_violations(bad_mech))
    bad_label = dict(INJECTIONS[0], ground_truth_label="meh")
    assert any("ground_truth_label" in v for v in spec_violations(bad_label))
    no_double = {
        k: v for k, v in INJECTIONS[3].items() if k != "double"
    }
    assert any("double" in v for v in spec_violations(no_double))


def test_smoke_only_spec_ids_are_the_four_scripted_injections():
    """Plan 13 §5.3: mechanism S is smoke-tier. run_ablation.py refuses
    these outside --smoke — no production code path consumes
    rqgm.eval.scripted_components, so a Tier-3 run given one would record a
    never-applied fault as active and corrupt the detection metrics."""
    assert smoke_only_spec_ids(INJECTIONS + CONTROLS) == [
        "eval_inj_004_adversary_overreach",
        "eval_inj_005_judge_bias",
        "eval_inj_006_bad_generator",
        "eval_inj_008_bad_prompt_mutator",
    ]
    fixtures_only = [
        s for s in INJECTIONS + CONTROLS if s["mechanism"] == "fixture"
    ]
    assert smoke_only_spec_ids(fixtures_only) == []
    assert smoke_only_spec_ids([]) == []


# ── apply_injection: deterministic + idempotent ──────────────────────────────


def _tree_hash(root: Path) -> dict:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_apply_fixture_injection_is_deterministic_and_idempotent(tmp_path):
    spec = next(s for s in INJECTIONS
                if s["injection_id"] == "eval_inj_010_stale_record_leakage")
    first = apply_injection(spec, tmp_path)
    assert first == sorted(first) and first
    snapshot = _tree_hash(tmp_path)
    second = apply_injection(spec, tmp_path)
    assert second == first
    assert _tree_hash(tmp_path) == snapshot        # byte-identical re-apply
    # Files match the committed payload byte-for-byte.
    payload = fixtures_root() / "stale_record_leakage"
    assert snapshot == _tree_hash(payload)


def test_apply_scripted_injection_writes_nothing(tmp_path):
    spec = next(s for s in INJECTIONS
                if s["mechanism"] == "scripted_component")
    assert apply_injection(spec, tmp_path) == []
    assert list(tmp_path.iterdir()) == []


def test_apply_unknown_mechanism_raises(tmp_path):
    with pytest.raises(ValueError):
        apply_injection({"mechanism": "wormhole"}, tmp_path)
    with pytest.raises(FileNotFoundError):
        apply_injection(
            {"mechanism": "fixture", "injection_id": "eval_missing",
             "payload_ref": "does_not_exist/"},
            tmp_path,
        )


# ── provenance marker ────────────────────────────────────────────────────────


def test_provenance_roundtrip_and_digest_stability(tmp_path):
    specs = INJECTIONS[:2]
    path = write_injection_provenance(tmp_path, specs)
    assert path.name == INJECTION_PROVENANCE_FILENAME
    marker = read_injection_provenance(tmp_path)
    assert marker["injection_ids"] == sorted(
        s["injection_id"] for s in specs
    )
    assert marker["specs_digest"] == specs_digest(specs)
    # Digest is order-independent (id-sorted canonical content).
    assert specs_digest(list(reversed(specs))) == specs_digest(specs)


def test_provenance_absent_returns_none(tmp_path):
    assert read_injection_provenance(tmp_path) is None


# ── checkpoint hygiene (pattern of test_new_filenames_are_meta_files) ────────


def test_eval_filenames_are_meta_files_and_report_internal():
    for name in (METRIC_REPORT_FILENAME, INJECTION_PROVENANCE_FILENAME):
        assert name in PathManager.META_FILES
        assert name in _INTERNAL_JSON_NAMES
