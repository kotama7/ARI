"""The families ARI ships, and the properties that make a second one cheap.

WHAT THIS FILE IS FOR. spmm and stencil are the first two consumers of the
problem mechanism, and the reason to have them is not that ARI needs three
benchmarks — it is that a mechanism claimed to generalize has not generalized
until something other than the thing it was built for goes through it. So the
assertions here are mostly about the SEAM: that a family supplies only a
generator and an oracle, that the instrument is shared rather than copied, and
that the parity property (a slow kernel fails on the RATIO, a wrong one on the
ORACLE) holds for each of them and not just for gemm.

The oracles themselves are checked against hand-computable cases rather than
against the reference implementation they were ported from, because "it agrees
with itself" is what a ported oracle always says.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ari.assurance.native_perf_family import get_family, registered_families
from ari.assurance.problems import load_problem, registered_problems

CORE = Path(__file__).resolve().parents[1]

PROBLEMS = {
    "gemm": "gemm-dense-fp64/v1@2026q3",
    "spmm": "spmm-csr-fp64/v1@2026q3",
    "stencil": "stencil-jacobi7-fp64/v1@2026q3",
}


# --- the seam ------------------------------------------------------------------

def test_every_shipped_family_has_a_problem_and_every_problem_a_family():
    """A family with no problem is unreachable; a problem with no family cannot
    be measured. Either one is a half-finished port that still imports."""
    families = set(registered_families())
    assert families == set(PROBLEMS)
    for revision in registered_problems():
        assert load_problem(revision).definition.family in families


@pytest.mark.parametrize("family_name", sorted(PROBLEMS))
def test_a_family_supplies_only_a_generator_and_an_oracle(family_name):
    """The instrument is shared, not copied.

    Each anti-gaming property of the measurement loop — header-less staging,
    the driver built with default flags, the object-level symbol audit, all
    timed launches before the oracle, the anchor/matched pair — was paid for by
    a defect. A family that could bring its own loop would have to re-establish
    every one of them, and would silently not.
    """
    family = get_family(family_name)
    module = type(family).__module__
    source = (CORE / "ari" / "assurance"
              / f"{module.rsplit('.', 1)[-1]}.py").read_text()
    for forbidden in ("run_timed", "compile_binary", "screen_flags",
                      "measurement_placement", "TIER_REPETITIONS"):
        assert forbidden not in source, (
            f"{module} reaches into the measurement loop via {forbidden}; a "
            f"family supplies a generator and an oracle and nothing else")


@pytest.mark.parametrize("family_name", sorted(PROBLEMS))
def test_a_case_set_belongs_to_exactly_one_family(family_name):
    """Shapes handed to the wrong oracle mean nothing, and would not say so."""
    from ari.assurance.native_perf_common import load_case_set

    definition = load_problem(PROBLEMS[family_name]).definition
    for revision in (definition.case_set, definition.parity_case_set):
        case_set, _digest = load_case_set(revision)
        assert case_set.kind == family_name


def test_re_registering_a_family_name_is_refused():
    """Two oracles under one name would make the judging one an import-order
    accident, which is invisible until a result is wrong."""
    from ari.assurance.native_perf_common import PerfInfrastructureError
    from ari.assurance.native_perf_family import register_family

    class Impostor:
        name = "gemm"

    with pytest.raises(PerfInfrastructureError, match="already registered"):
        register_family(Impostor())


# --- the oracles, against cases whose answer is known independently -------------

def test_the_spmm_bound_scales_with_the_ROW_and_not_the_matrix():
    """A single global tolerance cannot serve a power-law matrix.

    The bound is C*gamma(nnz_i)*(|A|@|X|) per row, so a long row buys more
    slack than a short one. Asserted through the gamma the oracle uses, because
    a matrix-wide tolerance would either reject legitimate reassociation on the
    dense rows or accept wrong output on the short ones — and this problem is
    scored on both kinds at once.
    """
    from ari.assurance.native_perf_spmm import gamma

    assert gamma(1) < gamma(64) < gamma(4096)


def test_the_spmm_oracle_accepts_a_reassociated_sum_and_rejects_a_dropped_term():
    import scipy.sparse as sp

    family = get_family("spmm")
    case = ("uniform", 64, 8)
    a, x = family.generate(case, seed=3)
    exact = np.asarray(sp.csr_matrix(a).astype(np.float64) @ x)

    ok, _worst = family.check(exact.ravel(), case, (a, x))
    assert ok

    # A rounding-sized perturbation is legitimate ON A ROW THAT HAS ROUNDING TO
    # do. One ulp, not a hand-picked multiple of eps: the bound is about 8u on a
    # single-nonzero row, so a "small" 16u nudge is correctly rejected. Tight
    # where the summation is short is the property it exists to have.
    nnz_per_row = np.diff(a.indptr)
    populated = nnz_per_row > 0
    nudged = exact.copy()
    nudged[populated] = np.nextafter(exact[populated], np.inf)
    ok_nudged, _ = family.check(nudged.ravel(), case, (a, x))
    assert ok_nudged

    # An EMPTY row has no rounding freedom at all: its output is exactly 0.0,
    # its bound is exactly 0.0, and one subnormal off is a wrong answer. That is
    # the oracle being right, not being brittle -- nothing was summed.
    assert populated.sum() < len(nnz_per_row), "fixture has no empty row to test"
    subnormal = exact.copy()
    subnormal[~populated] = np.nextafter(0.0, np.inf)
    ok_subnormal, _ = family.check(subnormal.ravel(), case, (a, x))
    assert not ok_subnormal

    broken = exact.copy()
    broken[np.argmax(nnz_per_row), 0] += 1.0
    ok_broken, worst = family.check(broken.ravel(), case, (a, x))
    assert not ok_broken and worst > 1.0


def test_the_stencil_oracle_knows_a_constant_field_is_its_own_answer():
    """The seven weights sum to one, so a constant field is a fixed point.

    An answer computable by hand, unlike "it agrees with the implementation it
    was ported from" — which is what a ported oracle always says.
    """
    family = get_family("stencil")
    from ari.assurance.native_perf_stencil import reference_jacobi

    field = np.full((8, 8, 8), 2.5, dtype=np.float64)
    swept = reference_jacobi(field, 8, 8, 8, 5)
    assert np.allclose(swept, 2.5, rtol=0, atol=1e-12)


def test_the_stencil_oracle_rejects_a_kernel_that_applies_no_sweep():
    """Which is the fast-but-wrong control, so this is the property the parity
    probe rests on for this family."""
    family = get_family("stencil")
    case = (16, 16, 16, 3)
    u0, _nt = family.generate(case, seed=1)
    ok, worst = family.check(np.asarray(u0).ravel(), case, (u0, 3))
    assert not ok and worst > 1.0


def test_a_stencil_case_with_no_sweep_is_refused():
    """At nt=0 handing back the input IS correct, so the wrong control would
    pass and the probe would certify an instrument that checks nothing."""
    from ari.assurance.native_perf_common import PerfInfrastructureError

    with pytest.raises(PerfInfrastructureError, match="a copy would be right"):
        get_family("stencil").output_elements((16, 16, 16, 0))


def test_the_stencil_boundary_is_fixed():
    """Dirichlet planes keep their u0 value; a kernel that sweeps them is wrong
    and the oracle has to be the thing that knows it."""
    from ari.assurance.native_perf_stencil import reference_jacobi

    rng = np.random.default_rng(0)
    u0 = rng.standard_normal((6, 6, 6))
    swept = reference_jacobi(u0, 6, 6, 6, 4)
    assert np.array_equal(swept[0], u0[0]) and np.array_equal(swept[-1], u0[-1])
    assert np.array_equal(swept[:, 0], u0[:, 0])
    assert np.array_equal(swept[:, :, 0], u0[:, :, 0])


# --- what a case may be --------------------------------------------------------

def test_a_case_may_carry_a_categorical_not_only_sizes():
    """An SpMM case names a matrix family. Coercing cases to int would have
    forced "sparse matrices that look like this" to become a separate problem
    for no reason but a type."""
    from ari.assurance.native_perf_common import load_case_set

    case_set, _digest = load_case_set("native-perf-spmm-cases/v1@scored-2026q3")
    assert {case[0] for case in case_set.cases} == {
        "uniform", "banded", "power_law", "block", "diagonal_dominant", "skewed"}


def test_an_unknown_matrix_family_is_refused_rather_than_generated():
    from ari.assurance.native_perf_common import PerfInfrastructureError

    with pytest.raises(PerfInfrastructureError, match="unknown spmm matrix family"):
        get_family("spmm").output_elements(("invented", 16, 4))


# --- the registration evidence a free problem still has to produce --------------

@pytest.mark.parametrize("family_name", sorted(PROBLEMS))
def test_each_problem_declares_both_negative_controls(family_name):
    """A problem may be added without approval, but not REGISTERED without
    evidence: the probe refuses when a control is missing rather than skipping
    it, and a probe with only the slow control cannot tell a performance
    harness from a stopwatch."""
    scaffolding = load_problem(PROBLEMS[family_name]).definition.scaffolding
    assert scaffolding.negative_control_slow
    assert scaffolding.negative_control_wrong


@pytest.mark.parametrize("family_name", sorted(PROBLEMS))
def test_the_parity_set_resolves(family_name):
    """An instrument certified where its own spread swamps the difference it
    reports has not been certified. The driver refuses such a set; this asserts
    the shipped problems do not depend on that refusal."""
    from ari.assurance.native_perf_common import load_case_set

    definition = load_problem(PROBLEMS[family_name]).definition
    case_set, _digest = load_case_set(definition.parity_case_set)
    assert case_set.resolves


def test_the_probe_refuses_a_parity_set_that_cannot_resolve(monkeypatch):
    from ari.assurance.drivers.perf import NativePerfDriver, perf_driver_digest
    from ari.assurance import problems as problems_mod

    loaded = load_problem(PROBLEMS["gemm"])
    swapped = loaded.definition.model_copy(
        update={"parity_case_set": "native-perf-gemm-cases/v1@smoke"})
    monkeypatch.setattr(
        problems_mod, "load_problem",
        lambda _rev: loaded.model_copy(update={"definition": swapped}))
    import ari.assurance.drivers.perf as perf_mod
    monkeypatch.setattr(perf_mod, "load_problem", problems_mod.load_problem)

    class _Asset:
        def __init__(self, revision):
            self.revision = revision
            self.sha256 = loaded.digest

    class _M:
        oracle = _Asset(PROBLEMS["gemm"])

    report = NativePerfDriver().parity_probe(_M())
    assert report["passed"] is False
    assert "resolves=false" in report["reason"]
    assert report["driver_digest"] == perf_driver_digest()
