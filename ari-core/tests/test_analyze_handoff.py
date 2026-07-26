"""Tests for the handoff-sweep analyzer's outcome extraction.

The analyzer is a study-specific CLI (not a package). It lives under
``workspace/`` (gitignored, self-contained with the harnesses), with a legacy
``scripts/`` fallback; import it by path and skip if neither location exists.
We exercise run_outcome — the per-run reduction (best valid geomean speedup over
nodes) that maps a run dir to its analysis outcome — on synthetic node_reports.
"""
import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = next((p for p in (_ROOT / "workspace" / "analyze_handoff_ablation.py",
                            _ROOT / "scripts" / "analyze_handoff_ablation.py") if p.is_file()), None)
if _SCRIPT is None:
    pytest.skip("analyze_handoff_ablation.py not found (workspace/ or scripts/)", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("analyze_handoff_ablation", _SCRIPT)
ana = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ana)


def _node(run_dir: Path, name: str, *, valid_geomean):
    nd = run_dir / f"node_{name}"
    nd.mkdir(parents=True, exist_ok=True)
    metrics = {} if valid_geomean is None else {"valid_geomean_speedup": valid_geomean}
    (nd / "node_report.json").write_text(json.dumps({"node_id": name, "metrics": metrics}))


def test_run_outcome_picks_best_valid(tmp_path):
    run = tmp_path / "run1"
    _node(run, "root", valid_geomean=0.0)     # invalid (evaluator zeroes it)
    _node(run, "a", valid_geomean=3.5)        # valid
    _node(run, "b", valid_geomean=9.0)        # valid, best
    _node(run, "c", valid_geomean=None)       # failed (no metric)
    best, n_valid, n_nodes = ana.run_outcome(str(run))
    assert best == 9.0
    assert n_valid == 2
    assert n_nodes == 4


def test_run_outcome_no_valid_node_is_zero(tmp_path):
    run = tmp_path / "run2"
    _node(run, "root", valid_geomean=0.0)
    _node(run, "a", valid_geomean=None)
    best, n_valid, n_nodes = ana.run_outcome(str(run))
    assert best == 0.0 and n_valid == 0 and n_nodes == 2


def test_run_outcome_missing_dir(tmp_path):
    assert ana.run_outcome(None) == (0.0, 0, 0)
    assert ana.run_outcome(str(tmp_path / "nope")) == (0.0, 0, 0)


def test_analyzer_excludes_primary_from_holm(tmp_path):
    """End-to-end: the PREREG primary contrast is reported un-adjusted, and is
    NOT included in the secondary Holm-adjusted pairwise set."""
    import json as _json
    import subprocess
    import sys
    arms = {
        "code_only": [3.0, 3.3],
        "code_plus_summary": [5.0, 5.2],
        "code_plus_full_log": [5.0, 5.1],
    }
    rows = []
    for arm, vals in arms.items():
        for seed, v in enumerate(vals):
            rd = tmp_path / f"{arm}_{seed}"
            _node(rd, "a", valid_geomean=v)
            rows.append({"arm": arm, "seed": seed, "run_dir": str(rd), "rc": 0})
    (tmp_path / "manifest.jsonl").write_text(
        "\n".join(_json.dumps(r) for r in rows) + "\n")
    import os as _os
    # Pin the primary contrast to the pair under test (the default is now the
    # nested code_plus_summary_plus_full_log arm); this checks the exclusion
    # MECHANISM independent of which pair is primary.
    _env = {**_os.environ, "ARI_HANDOFF_PRIMARY": "code_plus_summary,code_plus_full_log"}
    subprocess.run([sys.executable, str(_SCRIPT), str(tmp_path)],
                   check=True, capture_output=True, env=_env)
    c = _json.loads((tmp_path / "analysis.json").read_text())["contrasts"]
    # primary present (reported), but NOT Holm-adjusted
    assert "code_plus_summary_vs_code_plus_full_log" in c
    assert "holm_p" not in c["code_plus_summary_vs_code_plus_full_log"]
    # every Holm-adjusted pair is a secondary (code_only) contrast
    holm_keys = [k for k, v in c.items() if "holm_p" in v]
    assert holm_keys and all("code_only" in k for k in holm_keys)


def test_lineage_stats_parent_child_improve_break(tmp_path):
    """REGRESSION: lineage_stats reads tree.json and compares each child to its
    parent. A refactor of the validity rule left a stale `g` reference in the
    parent/child branch, so the whole function raised NameError on ANY run with a
    readable tree.json — but no unit test exercised that path, so it shipped and
    only surfaced on real smoke data. This drives the tree.json branch directly."""
    run = tmp_path / "experiments" / "run_x"
    ck = tmp_path / "checkpoints" / "run_x"
    ck.mkdir(parents=True)
    tree = {"nodes": [
        {"id": "root", "parent_id": None,
         "metrics": {"valid_geomean_speedup": 2.0}, "self_assessment": {"succeeded": True}},
        {"id": "c_up", "parent_id": "root",           # child improved on parent
         "metrics": {"valid_geomean_speedup": 3.0}, "self_assessment": {"succeeded": True}},
        {"id": "c_break", "parent_id": "root",         # child went invalid
         "metrics": {"valid_geomean_speedup": 0.0}, "self_assessment": {"succeeded": False}},
    ]}
    (ck / "tree.json").write_text(json.dumps(tree))
    run.mkdir(parents=True)

    out = ana.lineage_stats(str(run))          # must NOT raise
    assert out["n_nodes"] == 3
    assert out["n_valid"] == 2                  # root + c_up (c_break is invalid)
    assert out["child_total"] == 2             # both children have a valid parent
    assert out["child_improve"] == 1           # c_up beat the parent
    assert out["child_break"] == 1             # c_break went invalid


def test_lineage_stats_score_axis_zero_child_is_not_a_break(tmp_path):
    """A score-axis child that legitimately scored 0.0 (succeeded=True) is a VALID
    child, not a break — the validity fix must reach the parent/child comparison."""
    run = tmp_path / "experiments" / "run_s"
    ck = tmp_path / "checkpoints" / "run_s"
    ck.mkdir(parents=True)
    tree = {"nodes": [
        {"id": "root", "parent_id": None,
         "metrics": {"valid_geomean_speedup": 0.6}, "self_assessment": {"succeeded": True}},
        {"id": "c0", "parent_id": "root",              # measured 0.0 but valid
         "metrics": {"valid_geomean_speedup": 0.0}, "self_assessment": {"succeeded": True}},
    ]}
    (ck / "tree.json").write_text(json.dumps(tree))
    run.mkdir(parents=True)
    out = ana.lineage_stats(str(run))
    assert out["n_valid"] == 2                  # the 0.0 child is valid
    assert out["child_break"] == 0             # and is NOT counted as a break
