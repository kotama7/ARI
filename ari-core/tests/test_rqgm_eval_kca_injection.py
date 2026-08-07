"""Task-20 K/C/A injected failures and their same-shape clean controls."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from ari.rqgm.evaluation.injection import (
    apply_injection,
    load_injection_specs,
    smoke_only_spec_ids,
    spec_violations,
)


SPECS = load_injection_specs()
BAD = SPECS["kca_injections"]
GOOD = SPECS["kca_controls"]


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_kca_fault_panel_has_exact_layer_counts_and_one_control_each():
    assert len(BAD) == len(GOOD) == 38
    assert Counter(item["layer"] for item in BAD) == {
        "knowledge": 11,
        "provider": 12,
        "harness": 15,
    }
    assert Counter(item["layer"] for item in GOOD) == Counter(
        item["layer"] for item in BAD
    )
    controls = {item["control_for"]: item for item in GOOD}
    assert set(controls) == {item["injection_id"] for item in BAD}


def test_every_kca_spec_is_valid_held_out_and_unique():
    all_specs = BAD + GOOD
    ids = [item["injection_id"] for item in all_specs]
    assert len(ids) == len(set(ids))
    assert set(smoke_only_spec_ids(all_specs)) == set(ids)
    for item in all_specs:
        assert item["injection_id"].startswith("eval_")
        assert spec_violations(item) == []


def test_clean_controls_preserve_shape_but_remove_the_mutation():
    bad_by_id = {item["injection_id"]: item for item in BAD}
    for control in GOOD:
        fault = bad_by_id[control["control_for"]]
        assert control["layer"] == fault["layer"]
        assert control["mechanism"] == fault["mechanism"] == "kca_mutation"
        assert control["target_refs"] == fault["target_refs"]
        assert control["min_condition"] == fault["min_condition"]
        assert control["ground_truth_label"] == "good"
        assert control["mutation"] == "clean_control"
        assert control["expected_detection"]["channels"] == ["none"]


def test_kca_fixture_application_is_byte_stable_and_isolated(tmp_path):
    spec = BAD[0]
    written = apply_injection(spec, tmp_path)
    assert len(written) == 1
    assert written[0].startswith("rqgm/kca/evaluation/injections/")
    before = _hash_tree(tmp_path)
    assert apply_injection(spec, tmp_path) == written
    assert _hash_tree(tmp_path) == before
    payload = json.loads((tmp_path / written[0]).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "ari.rqgm-eval-kca-mutation/v1"
    assert payload["ground_truth_label"] == "bad"
    assert not any(
        part in {"knowledge_skills", "providers", "harnesses"}
        for part in Path(written[0]).parts
    )
