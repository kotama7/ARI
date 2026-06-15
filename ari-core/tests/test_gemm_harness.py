"""Tests for the GEMM harness (task A, login-testable parts).

Covers the fp64 reference, the contraction-length correctness bound, deterministic
problem generation, measure_node aggregation with an injected runner, and the
work_dir seeder. The real compile/run/timing runner is compute-node only; a
login smoke test of the frozen baseline is included (skips without a compiler).
"""
import math
import os

import numpy as np
import pytest

from ari.evaluator.gemm_harness import (
    SHAPES,
    gamma,
    gen_problem,
    is_correct,
    measure_node,
    reference_gemm,
    seed_work_dir,
    _FROZEN_FIXTURES,
)


def test_gamma():
    assert gamma(10) > 0.0
    assert math.isinf(gamma(2, u=1.0))


def test_gen_problem_deterministic_and_shaped():
    A1, B1 = gen_problem((8, 6, 4), seed=3)
    A2, B2 = gen_problem((8, 6, 4), seed=3)
    assert A1.shape == (8, 6) and B1.shape == (6, 4)
    assert np.array_equal(A1, A2) and np.array_equal(B1, B2)


def test_reference_matches_dense():
    A, B = gen_problem((12, 9, 7), seed=1)
    assert np.allclose(reference_gemm(A, B), A @ B)


def test_is_correct_accepts_reference_rejects_gross():
    A, B = gen_problem((16, 16, 16), seed=2)
    C = reference_gemm(A, B)
    ok, mr = is_correct(C, C, A, B)
    assert ok and mr == 0.0
    bad = C.copy(); bad[0, 0] += 1e3
    ok2, _ = is_correct(bad, C, A, B)
    assert not ok2


def test_is_correct_allows_reduction_reordering():
    # summing in reverse is within the contraction-length eps bound
    A, B = gen_problem((20, 50, 20), seed=4)
    C = reference_gemm(A, B)
    C_rev = (A[:, ::-1] @ B[::-1, :])
    ok, _ = is_correct(C_rev, C, A, B)
    assert ok


def _fake_runner(good=True):
    def run(kind, work_dir, A, B, warmup, reps):
        C = reference_gemm(A, B)
        if kind == "candidate":
            if not good:
                C = C + 1e3  # wrong
            return 0.01, C        # candidate faster
        return 1.0, C             # baseline slower
    return run


def test_measure_node_valid_with_speedup():
    out = measure_node("", run_kernel=_fake_runner(good=True),
                       shapes=((16, 16, 16),), warmup=0, reps=1)
    fam = out["families"]["16x16x16"]
    assert out["compile_ok"] and fam["valid"]
    assert fam["speedup"] == pytest.approx(100.0)


def test_measure_node_incorrect_candidate_is_invalid():
    out = measure_node("", run_kernel=_fake_runner(good=False),
                       shapes=((16, 16, 16),), warmup=0, reps=1)
    assert not out["families"]["16x16x16"]["valid"]


def test_seed_work_dir_seeds_and_preserves_candidate(tmp_path):
    wd = str(tmp_path / "node")
    written = seed_work_dir(wd)
    for f in (*_FROZEN_FIXTURES, "candidate_gemm.c"):
        assert os.path.isfile(os.path.join(wd, f)), f"missing {f}"
        assert f in written
    cand = os.path.join(wd, "candidate_gemm.c")
    with open(cand, "a") as fh:
        fh.write("\n/* edit */\n")
    main_c = os.path.join(wd, "gemm_main.c")
    with open(main_c, "w") as fh:
        fh.write("/* tampered */\n")
    seed_work_dir(wd)
    assert "/* edit */" in open(cand).read()        # candidate preserved
    assert "tampered" not in open(main_c).read()      # frozen restored


def test_shapes_nonsquare():
    assert (512, 512, 512) in SHAPES
    assert any(n != m for (n, _p, m) in SHAPES)  # at least one rectangular shape


def test_default_runner_baseline_compiles_and_is_correct():
    """Login smoke: real compile+run of the frozen baseline is correct (no BLAS)."""
    import shutil
    from ari.evaluator.gemm_harness import _default_run_kernel
    if shutil.which(os.environ.get("ARI_GEMM_CC", "cc")) is None:
        pytest.skip("no C compiler")
    A, B = gen_problem((64, 48, 32), seed=1)
    try:
        t, C = _default_run_kernel("baseline", "", A, B, warmup=0, reps=1)
    except RuntimeError as e:
        pytest.skip(f"compile/run unavailable: {e}")
    assert t >= 0.0
    ok, mr = is_correct(C, reference_gemm(A, B), A, B)
    assert ok, f"baseline incorrect (max_rel={mr})"
