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
    "files_changed": {
        "added": [{"path": "spmm.c"}],
        "modified": [{"path": "run.sh"}],
        "deleted": [{"path": "old_results.json"}],
    },
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
    for token in ("changed_files", "spmm.c", "concerns",
                  "next_steps", "known_failures", "key_metrics",
                  "valid_geomean_speedup", "build_command", "run_command"):
        assert token in out, token


def test_machine_info_never_leaks():
    out = node_summary_view(REP)
    for s in _SECRETS:
        assert s not in out, f"machine info leaked: {s}"


def test_canonical_home_path_is_scrubbed(monkeypatch, tmp_path):
    physical_home = tmp_path / "mounted" / "home" / "testuser"
    physical_home.mkdir(parents=True)
    logical_home = tmp_path / "home" / "testuser"
    logical_home.parent.mkdir()
    logical_home.symlink_to(physical_home, target_is_directory=True)
    monkeypatch.setenv("HOME", str(logical_home))
    monkeypatch.setenv("USER", "testuser")
    monkeypatch.delenv("ARI_ROOT", raising=False)
    monkeypatch.delenv("ARI_WORK_DIR", raising=False)

    report = {
        "node_id": "node_failed",
        "status": "success",
        "measurement_valid": False,
        "evaluation_status": "candidate_invalid",
        "evaluator_reason": (
            f"compile failed: {physical_home}/ARI/workspace/node/candidate.c"
        ),
    }
    out = node_summary_view(report, summary_form="evidence")

    assert "known_failures:" in out
    assert str(physical_home) not in out
    assert str(logical_home) not in out
    assert "testuser" not in out
    assert "~/ARI/workspace/node/candidate.c" in out


def test_known_failures_derivation():
    kf = derive_known_failures(REP)
    assert any("regression" in x for x in kf)            # failed-node reason
    assert any("degraded banded" in x for x in kf)       # regression-style concern
    assert not any("clean and readable" in x for x in kf)  # benign concern excluded


def test_field_ablation_removes_field():
    out = node_summary_view(REP, fields_enabled=set(ALL_FIELDS) - {"known_failures"})
    assert "known_failures:" not in out
    assert "changed_files" in out  # others retained


def test_failure_only_form():
    out = node_summary_view(REP, summary_form="failure_only")
    assert "known_failures:" in out and "concerns:" in out
    assert "changed_files" not in out
    assert "key_metrics" not in out


def test_evidence_form_excludes_llm_reflection():
    rep = dict(REP)
    rep.update({
        "status": "success",
        "what_was_done": "LLM says row bucketing is the bottleneck fix",
        "measurement_valid": True,
        "evaluation_cases": {
            "banded": {
                "valid": True,
                "measurements": {
                    "speedup": 2.3,
                    "max_relative_error": 1e-12,
                    "n_clamped": 1,
                },
            },
        },
        "self_assessment": {"headline": "LLM headline", "concerns": ["LLM concern"]},
        "next_steps_hints": ["LLM next step"],
        "evaluator_reason": "deterministic evaluator ok",
    })
    out = node_summary_view(rep, summary_form="evidence")
    assert "Parent handoff" in out
    assert "measurement_valid: True" in out
    assert "succeeded:" not in out
    assert "deterministic evaluator ok" in out
    assert "valid_geomean_speedup" in out
    assert "evaluation_cases:" in out
    assert "max_relative_error" in out
    assert "'added': ['spmm.c']" in out
    assert "'modified': ['run.sh']" in out
    assert "'deleted': ['old_results.json']" in out
    assert "LLM says" not in out
    assert "LLM concern" not in out
    assert "LLM next step" not in out
    assert "build_command" not in out and "run_command" not in out


def test_evidence_reflection_form_adds_reflection_on_same_evidence():
    rep = dict(REP)
    rep.update({
        "status": "success",
        "what_was_done": "LLM says row bucketing is the bottleneck fix",
        "measurement_valid": True,
        "self_assessment": {"headline": "LLM headline", "concerns": ["LLM concern"]},
        "next_steps_hints": ["LLM next step"],
        "evaluator_reason": "deterministic evaluator ok",
    })
    ev = node_summary_view(rep, summary_form="evidence")
    refl = node_summary_view(rep, summary_form="evidence_reflection")
    assert "deterministic evaluator ok" in ev and "deterministic evaluator ok" in refl
    assert "LLM says" not in ev and "LLM says" in refl
    assert "LLM concern" not in ev and "LLM concern" in refl
    assert "LLM next step" not in ev and "LLM next step" in refl
    assert refl.startswith(ev + "\n")


def test_evidence_form_does_not_use_legacy_llm_fallbacks():
    rep = {
        "node_id": "node_legacy",
        "status": "success",
        "eval_summary": "LLM claims the candidate is correct and 99x faster",
        "self_assessment": {
            "succeeded": True,
            "headline": "LLM headline",
            "concerns": ["LLM concern"],
        },
    }
    out = node_summary_view(rep, summary_form="evidence")
    assert "measurement_valid:" not in out
    assert "evaluator_reason:" not in out
    assert "99x" not in out
    assert "LLM headline" not in out
    assert "LLM concern" not in out


def test_empty_report_is_blank():
    assert node_summary_view({}) == ""
    assert node_summary_view(None) == ""
