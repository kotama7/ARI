"""Tests for the handoff-study node_summary_view (G3): field ablation,
known_failures derivation, failure_only form, and the machine-info leak guard.
"""
from ari.orchestrator.node_summary_view import (
    ALL_FIELDS,
    derive_known_failures,
    node_summary_view,
)

# node_report.json-shaped sample, incl. machine-provenance fields that MUST NOT leak.
REP = {
    "node_id": "abcdef1234567890",
    "label": "improve_perf",
    "status": "failed",
    "evaluator_reason": "candidate slower than baseline on banded (regression)",
    "delta_vs_parent": "switched to dynamic OpenMP scheduling",
    "files_changed": {"added": [{"path": "spmm.c"}], "modified": [{"path": "run.sh"}]},
    "self_assessment": {"concerns": [
        "dynamic scheduling degraded banded matrices",
        "code is clean and readable",
    ]},
    "next_steps_hints": ["try row-length bucketing for skewed matrices"],
    "metrics": {
        "valid_geomean_speedup": 2.31, "_scientific_score": 0.58,
        "speedup_uniform": 1.9, "max_relative_error": 1e-7,
    },
    "build_command": "make",
    "run_command": "./bench",
    # machine info — must NEVER appear in the rendered view:
    "hostname": "SECRETHOST", "slurm_partition": "SECRETPART",
    "slurm_nodelist": "SECRETNODES", "cpu_info": {"model": "SECRETCPU"},
}

_SECRETS = ("SECRETHOST", "SECRETPART", "SECRETNODES", "SECRETCPU")


def test_full_view_has_operational_fields():
    out = node_summary_view(REP)
    for token in ("delta_vs_parent", "changed_files", "spmm.c", "concerns",
                  "next_steps", "known_failures", "key_metrics",
                  "valid_geomean_speedup", "build_command", "run_command"):
        assert token in out, token


def test_machine_info_never_leaks():
    out = node_summary_view(REP)
    for s in _SECRETS:
        assert s not in out, f"machine info leaked: {s}"


def test_known_failures_derivation():
    kf = derive_known_failures(REP)
    assert any("regression" in x for x in kf)            # failed-node reason
    assert any("degraded banded" in x for x in kf)       # regression-style concern
    assert not any("clean and readable" in x for x in kf)  # benign concern excluded


def test_field_ablation_removes_field():
    out = node_summary_view(REP, fields_enabled=set(ALL_FIELDS) - {"known_failures"})
    assert "known_failures:" not in out
    assert "delta_vs_parent" in out  # others retained


def test_failure_only_form():
    out = node_summary_view(REP, summary_form="failure_only")
    assert "known_failures:" in out and "concerns:" in out
    assert "delta_vs_parent" not in out and "changed_files" not in out
    assert "key_metrics" not in out


def test_empty_report_is_blank():
    assert node_summary_view({}) == ""
    assert node_summary_view(None) == ""
