"""Tests for the erfc accuracy-coverage harness (Goldilocks task B, login parts)."""
import os

import numpy as np
import pytest

from ari.evaluator import erfc_harness as E


def test_gen_points_seed_dependent_and_in_domain():
    x0, r0 = E.gen_points(seed=0)
    x1, _r1 = E.gen_points(seed=1)
    assert x0.size > 100 and (r0 > 0).all()
    assert x0.min() >= E.DOMAIN[0] - 1e-9 and x0.max() <= E.DOMAIN[1] + 1e-9
    # different seeds => essentially disjoint point sets (anti-gaming)
    assert np.intersect1d(x0, x1).size < 5


def test_measure_node_perfect_and_bad_runner():
    from scipy.special import erfc as ref
    # perfect candidate -> score 1.0
    out = E.measure_node("", run_kernel=lambda wd, x: ref(x))
    assert out["compile_ok"] and out["score"] == pytest.approx(1.0)
    assert set(out["regions"]) == {"center", "mid", "tail", "deeptail"}
    # constant-1 candidate -> only correct very near 0 -> low score
    bad = E.measure_node("", run_kernel=lambda wd, x: np.ones_like(x))
    assert bad["compile_ok"] and bad["score"] < 0.3


def test_measure_node_run_failure_is_zero():
    def boom(wd, x):
        raise RuntimeError("nope")
    out = E.measure_node("", run_kernel=boom)
    assert out["compile_ok"] is False and out["score"] == 0.0


def test_seed_work_dir_seeds_scaffolding_and_refpoints(tmp_path):
    wd = str(tmp_path / "node")
    written = E.seed_work_dir(wd)
    for f in (*E._FROZEN_FIXTURES, "candidate_erfc.c", "ref_points.csv"):
        assert os.path.isfile(os.path.join(wd, f)), f"missing {f}"
        assert f in written
    # ref_points.csv parses as "x ref" with ref>0
    rows = [ln.split() for ln in open(os.path.join(wd, "ref_points.csv")) if ln.strip()]
    assert len(rows) > 100 and all(float(r[1]) > 0 for r in rows[:20])


def test_evaluator_score_shaped_path():
    from ari.evaluator.deterministic_evaluator import DeterministicEvaluator
    ev = DeterministicEvaluator()
    out = ev._score({"compile_ok": True, "score": 0.62,
                     "regions": {"center": 1.0, "mid": 1.0, "tail": 0.3, "deeptail": 0.0},
                     "reason": "ok"})
    assert out["metrics"]["_scientific_score"] == pytest.approx(0.62)
    assert out["metrics"]["valid_geomean_speedup"] == pytest.approx(0.62)  # so analyzer works
    assert out["valid"] and out["has_real_data"]
    assert out["metrics"]["region_tail"] == pytest.approx(0.3)
