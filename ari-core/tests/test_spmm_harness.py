"""Tests for the SpMM harness measurement CORE (B2b, login-testable parts).

Covers the reference oracle, the per-element correctness bound (eps model),
seeded matrix generation, and measure_node aggregation with an injected runner.
The real compile/run/timing runner is compute-node only and not exercised here.
"""
import math

import numpy as np
import pytest

from ari.evaluator.spmm_harness import (
    FAMILIES,
    gamma,
    gen_matrix,
    is_correct,
    measure_node,
    reference_spmm,
)


def test_gamma():
    assert gamma(10) > 0.0
    assert math.isinf(gamma(2, u=1.0))  # k*u >= 1


def test_gen_matrix_deterministic_and_valid():
    for fam in ("uniform", "banded", "diagonal_dominant", "block", "power_law", "skewed"):
        A1 = gen_matrix(fam, 64, seed=7)
        A2 = gen_matrix(fam, 64, seed=7)
        assert A1.shape == (64, 64)
        assert (A1 != A2).nnz == 0, f"{fam} not deterministic for fixed seed"
    # different seeds differ (uniform)
    assert (gen_matrix("uniform", 64, seed=1) != gen_matrix("uniform", 64, seed=2)).nnz > 0


def test_reference_spmm_matches_dense():
    A = gen_matrix("uniform", 48, seed=3)
    X = np.random.default_rng(0).standard_normal((48, 5))
    Y = reference_spmm(A, X)
    assert np.allclose(Y, A.toarray() @ X)


def test_is_correct_accepts_reference_and_within_bound_perturbation():
    import scipy.sparse as sp
    A = gen_matrix("uniform", 64, density=0.1, seed=4)
    X = np.random.default_rng(1).standard_normal((64, 6))
    Y = reference_spmm(A, X)
    ok, mr = is_correct(Y, Y, A, X)
    assert ok and mr < 1e-12
    # A perturbation at HALF the documented bound must be accepted; just OVER it
    # (x1.01) must be rejected — confirms the bound is the accept/reject knife-edge.
    Ac = sp.csr_matrix(A)
    g = np.array([gamma(int(k)) for k in np.diff(Ac.indptr)])
    absA = sp.csr_matrix((np.abs(Ac.data), Ac.indices, Ac.indptr), shape=Ac.shape)
    bound = 8.0 * g[:, None] * (absA @ np.abs(X))
    assert is_correct(Y + 0.5 * bound, Y, A, X)[0] is True
    assert is_correct(Y + 1.01 * bound, Y, A, X)[0] is False


def test_is_correct_rejects_gross_error():
    A = gen_matrix("uniform", 64, seed=5)
    X = np.random.default_rng(2).standard_normal((64, 4))
    Y = reference_spmm(A, X)
    ok, _ = is_correct(Y * 2.0 + 1.0, Y, A, X)  # wrong kernel
    assert not ok


def _mock_runner(kind, work_dir, A, X, warmup, reps):
    # baseline 1.0s, candidate 0.5s (2x) and correct
    return (1.0 if kind == "baseline" else 0.5), reference_spmm(A, X)


def test_measure_node_valid_with_speedup():
    res = measure_node("/tmp", run_kernel=_mock_runner,
                       families=("uniform", "banded"), n=64, k=4, reps=1, warmup=0)
    assert res["compile_ok"]
    assert set(res["families"]) == {"uniform", "banded"}
    for f in res["families"].values():
        assert f["valid"] and abs(f["speedup"] - 2.0) < 1e-9


def test_measure_node_incorrect_candidate_is_invalid():
    def bad(kind, wd, A, X, w, r):
        Y = reference_spmm(A, X)
        return (1.0, Y) if kind == "baseline" else (0.5, Y * 3.0 + 1.0)
    res = measure_node("/tmp", run_kernel=bad, families=("uniform",), n=64, k=4, reps=1, warmup=0)
    assert res["families"]["uniform"]["valid"] is False


def test_default_runner_missing_candidate_raises():
    from ari.evaluator.spmm_harness import _default_run_kernel
    A = gen_matrix("uniform", 16, seed=0)
    X = np.random.default_rng(0).standard_normal((16, 2))
    with pytest.raises(RuntimeError):
        _default_run_kernel("candidate", "/nonexistent_handoff_dir", A, X, 0, 1)


def test_default_runner_baseline_compiles_and_is_correct():
    """Login smoke: real compile+run of the frozen baseline is correct.

    Skips when no C compiler is available (e.g. minimal CI). TIMING is NOT
    asserted here — its representativeness is validated on a compute node.
    """
    import os
    import shutil
    from ari.evaluator.spmm_harness import _default_run_kernel
    if shutil.which(os.environ.get("ARI_SPMM_CC", "cc")) is None:
        pytest.skip("no C compiler available")
    A = gen_matrix("uniform", 32, density=0.1, seed=1)
    X = np.random.default_rng(2).standard_normal((32, 3))
    try:
        t, Y = _default_run_kernel("baseline", "", A, X, warmup=0, reps=2)
    except RuntimeError as e:
        pytest.skip(f"compile/run unavailable on this host: {e}")
    assert t >= 0.0
    ok, mr = is_correct(Y, reference_spmm(A, X), A, X)
    assert ok, f"baseline kernel output incorrect (max_rel={mr})"


def test_families_constant():
    assert "uniform" in FAMILIES and len(FAMILIES) == 6


def test_seed_work_dir_seeds_scaffolding_and_preserves_candidate(tmp_path):
    """seed_work_dir gives a node the frozen harness so the agent can build, and
    is idempotent: frozen files are restored, an edited candidate is kept."""
    import os
    from ari.evaluator.spmm_harness import seed_work_dir, _FROZEN_FIXTURES
    wd = str(tmp_path / "node")
    written = seed_work_dir(wd)
    for f in (*_FROZEN_FIXTURES, "candidate_spmm.c"):
        assert os.path.isfile(os.path.join(wd, f)), f"missing seeded {f}"
        assert f in written
    # An agent edit to the candidate survives a re-seed (child keeps its work).
    cand = os.path.join(wd, "candidate_spmm.c")
    with open(cand, "a") as fh:
        fh.write("\n/* agent-edit */\n")
    # A tampered frozen harness is restored to the canonical version.
    main_c = os.path.join(wd, "spmm_main.c")
    with open(main_c, "w") as fh:
        fh.write("/* tampered */\n")
    seed_work_dir(wd)
    assert "/* agent-edit */" in open(cand).read()      # candidate preserved
    assert "tampered" not in open(main_c).read()         # harness restored
    assert "median_sec" in open(main_c).read()


def test_seed_work_dir_built_candidate_is_correct():
    """Login smoke: the seeded scaffolding compiles (the agent's `make candidate`
    path) and the seeded naive candidate is itself a correct, valid baseline."""
    import os
    import shutil
    import tempfile
    from ari.evaluator.spmm_harness import seed_work_dir, _default_run_kernel
    if shutil.which(os.environ.get("ARI_SPMM_CC", "cc")) is None:
        pytest.skip("no C compiler available")
    wd = tempfile.mkdtemp(prefix="seed_smoke_")
    seed_work_dir(wd)
    A = gen_matrix("uniform", 32, density=0.1, seed=1)
    X = np.random.default_rng(2).standard_normal((32, 3))
    try:
        _t, Y = _default_run_kernel("candidate", wd, A, X, warmup=0, reps=2)
    except RuntimeError as e:
        pytest.skip(f"compile/run unavailable on this host: {e}")
    ok, mr = is_correct(Y, reference_spmm(A, X), A, X)
    assert ok, f"seeded naive candidate incorrect (max_rel={mr})"
