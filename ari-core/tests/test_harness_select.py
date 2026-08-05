"""Selection must never be able to see a result, and silence must never pass.

WHY THIS FILE EXISTS. The selector decides which harness measures a study. Two
ways of getting that wrong are worse than having no selector at all.

The first is ranking on outcomes. "Choose the harness under which the candidate
does best" is a natural sentence and a machine for score hacking. The defence is
structural -- the module is given no access to a score -- so the test is
structural too: it reads the module's imports and its call surface.

The second is treating an undeclared property as an acceptable one. A harness
that never had its band measured is not a harness with a good band, and the two
are indistinguishable unless silence is refused explicitly. This is why two of
the registered harnesses declare no band at all rather than a plausible number.

The third case is the one this project already paid for: a study was run to 270
runs before it emerged that every contrast had effect/MDE < 1 -- the measurement
could not resolve the effect being looked for. A selector that answers that
question from declarations costs nothing and would have said so first.
"""
import ast
import pathlib

import pytest

from ari.harness_select import Requirement, Verdict, evaluate, format_table, rank

MODULE = pathlib.Path(__file__).resolve().parents[1] / "ari/harness_select.py"


class _D:
    """A declaration, built inline so the tests do not depend on the pool."""

    def __init__(self, **kw):
        self.question = kw.get("question", "")
        self.denominator = kw.get("denominator", "")
        self.resolves = kw.get("resolves")
        self.resolves_measured_on = kw.get("resolves_measured_on", "")
        self.resolves_reps = kw.get("resolves_reps")
        self.cost_s = kw.get("cost_s")
        self.requires = tuple(kw.get("requires", ()))
        self.sees = tuple(kw.get("sees", ()))
        self.blind_to = tuple(kw.get("blind_to", ()))
        self._drift_pairs = tuple(kw.get("band_conditions", ()))

    @property
    def band_is_measured(self):
        return self.resolves is not None and bool(self.resolves_measured_on)

    def band_condition_drift(self):
        import os
        return [f"{k}: band measured with {v!r}, now {os.environ.get(k)!r}"
                for k, v in self._drift_pairs
                if (os.environ.get(k) or "") != (v or "")]


MEASURED = dict(resolves=0.0015, resolves_measured_on="2026-08-03", resolves_reps=15)


# ── the structural guarantee ────────────────────────────────────────────────
def test_the_selector_cannot_reach_anything_that_scores():
    """Ranking on results is the failure this module is shaped to prevent."""
    tree = ast.parse(MODULE.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"ari", "subprocess", "json", "pathlib", "os"}
    assert not (imported & forbidden), (
        f"harness_select imports {sorted(imported & forbidden)}. It must not be "
        f"able to load a harness, read a result file, or run anything: the "
        f"guarantee that selection cannot rank on outcomes is enforced by what "
        f"this module can reach, not by intent.")


def test_no_public_entry_point_accepts_a_score_or_a_work_dir():
    tree = ast.parse(MODULE.read_text())
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)
               and not n.name.startswith("_")]:
        names = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        bad = {n for n in names
               if any(w in n for w in ("score", "result", "work_dir", "speedup"))}
        assert not bad, f"{fn.name}() takes {bad}; selection must not see outcomes"


# ── silence is not suitability ──────────────────────────────────────────────
def test_an_unmeasured_band_is_refused_when_a_resolution_is_required():
    v = evaluate("nobody_measured_it", _D(), Requirement(resolve=0.005))
    assert not v.eligible
    assert "no measured band" in " ".join(v.reasons)


def test_a_band_without_a_measurement_date_is_not_a_measurement():
    """A number somebody typed and a number somebody took look identical."""
    v = evaluate("t", _D(resolves=0.0001), Requirement(resolve=0.005))
    assert not v.eligible, (
        "resolves=0.0001 with no measurement behind it would qualify this "
        "harness for almost any study")


def test_an_undeclared_axis_is_unknown_not_observable():
    v = evaluate("t", _D(**MEASURED, sees=("bandwidth",)),
                 Requirement(resolve=0.005, must_see=("large_page_policy",)))
    assert not v.eligible
    assert "says nothing about" in " ".join(v.reasons)


# ── the properties that actually disqualify ─────────────────────────────────
def test_a_band_wider_than_the_effect_is_refused():
    v = evaluate("t", _D(**MEASURED), Requirement(resolve=0.001))
    assert not v.eligible
    assert "wider than" in " ".join(v.reasons)


def test_a_structurally_blind_harness_is_refused_however_good_its_band():
    v = evaluate("t", _D(resolves=0.00001, resolves_measured_on="2026-08-03",
                         blind_to=("large_page_policy",)),
                 Requirement(resolve=0.005, must_see=("large_page_policy",)))
    assert not v.eligible, (
        "a 0.001% band does not help with an axis the harness cannot observe; "
        "resolution and coverage are different properties")


def test_a_missing_capability_is_refused():
    v = evaluate("t", _D(**MEASURED, requires=("vendor_profiler",)),
                 Requirement(resolve=0.005, have=("c_compiler",)))
    assert not v.eligible


def test_an_undeclared_cost_does_not_silently_pass_a_budget():
    v = evaluate("t", _D(**MEASURED), Requirement(resolve=0.005, budget_s=10))
    assert "cost not declared" in " ".join(v.reasons), (
        "an unchecked budget must be visible; silently treating it as met is "
        "how a study discovers its per-scoring cost from the queue")


def test_a_declared_cost_over_budget_is_refused():
    v = evaluate("t", _D(**MEASURED, cost_s=97.7),
                 Requirement(resolve=0.005, budget_s=10))
    assert not v.eligible


def test_a_wrong_denominator_is_refused():
    v = evaluate("t", _D(**MEASURED, denominator="naive"),
                 Requirement(resolve=0.005, denominator="anchor_matched"))
    assert not v.eligible


# ── the ranking keeps its evidence ──────────────────────────────────────────
def test_rejected_harnesses_stay_in_the_result():
    pool = [("wide", _D(resolves=0.02, resolves_measured_on="2026-08-03")),
            ("narrow", _D(**MEASURED))]
    got = rank(pool, Requirement(resolve=0.005))
    assert [v.task for v in got] == ["narrow", "wide"]
    assert len(got) == 2, (
        "returning only the winners would hide that the pool had an "
        "alternative and why it was dropped")


def test_more_headroom_ranks_first():
    pool = [("ok", _D(resolves=0.004, resolves_measured_on="2026-08-03")),
            ("better", _D(resolves=0.0005, resolves_measured_on="2026-08-03"))]
    assert [v.task for v in rank(pool, Requirement(resolve=0.005))][0] == "better"


def test_an_unanswerable_question_says_so_rather_than_returning_the_closest():
    """The 270-run lesson: no eligible harness is a finding, not a fallback."""
    pool = [("a", _D(**MEASURED)), ("b", _D(resolves=0.003,
                                            resolves_measured_on="2026-08-03"))]
    got = rank(pool, Requirement(resolve=0.0001))
    assert not any(v.eligible for v in got)
    text = format_table(got)
    assert "NO HARNESS IN THE POOL CAN ANSWER THIS QUESTION" in text
    assert "produces a number, not an answer" in text


def test_a_requirement_that_asks_for_nothing_accepts_an_uncharacterised_harness():
    """Not every use needs a guarantee; the refusal is tied to the ASK."""
    assert evaluate("t", _D(), Requirement()).eligible


@pytest.mark.parametrize("field_name", ["resolve", "budget_s", "must_see",
                                        "have", "denominator"])
def test_every_requirement_field_is_optional(field_name):
    assert evaluate("t", _D(**MEASURED), Requirement()).eligible
    assert isinstance(Requirement(), Requirement)
    assert hasattr(Requirement(), field_name)


def test_the_verdict_reports_why_it_qualified_not_only_that_it_did():
    v = evaluate("t", _D(**MEASURED), Requirement(resolve=0.005))
    assert v.eligible and v.reasons and "headroom" in " ".join(v.reasons), (
        "an eligible verdict with no stated grounds is an appeal to authority")
    assert isinstance(v, Verdict)


def test_a_band_measured_under_other_conditions_is_refused(monkeypatch):
    """The knob that made this necessary moves nothing a digest can see.

    ARI_STENCIL_SHAPES replaces the scored problem outright: the manifest hash
    does not move, measure_kwargs does not move, and the harness goes on
    advertising a band it measured on a different problem. Without this check
    the selector would accept a resolution guarantee for a measurement that was
    never taken.
    """
    monkeypatch.setenv("ARI_STENCIL_SHAPES", "64,64,64,1")
    d = _D(**MEASURED, band_conditions=(("ARI_STENCIL_SHAPES", ""),))
    v = evaluate("t", d, Requirement(resolve=0.005))
    assert not v.eligible
    assert "different measurement" in " ".join(v.reasons)


def test_matching_conditions_do_not_block_a_measured_band(monkeypatch):
    monkeypatch.delenv("ARI_STENCIL_SHAPES", raising=False)
    d = _D(**MEASURED, band_conditions=(("ARI_STENCIL_SHAPES", ""),))
    assert evaluate("t", d, Requirement(resolve=0.005)).eligible


def test_a_harness_that_names_no_conditions_is_not_treated_as_verified():
    """No drift and no claim look the same; only one of them is a guarantee."""
    d = _D(**MEASURED)
    assert d.band_condition_drift() == []
    assert d._drift_pairs == (), (
        "an empty drift list from a harness that named nothing must not be "
        "read as 'conditions checked and matching'")
