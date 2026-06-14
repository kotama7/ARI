"""Tests for the handoff-sweep analyzer's outcome extraction (scripts/).

The analyzer lives in scripts/ (a CLI, not a package), so import it by path.
We exercise run_outcome — the per-run reduction (best valid geomean speedup over
nodes) that maps a run dir to its analysis outcome — on synthetic node_reports.
"""
import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "analyze_handoff_ablation.py"
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
