"""Formula-level numeric re-computation utility (Story2Proposal Phase B2).

Canonical home of the numeric-assertion formula registry used by the
``claim_evidence_hard_gate``. The same registry is mirrored in
``ari-skill-transform/src/claims.py`` (which *declares* the assertions). Keep
the two in sync — divergence only affects the transform-declared ``value``
(seed), because the gate verifies the **paper-reported** number against this
recomputation, not against the seed.

The documented master-plan formulas are the lower-is-better family
(speedup / improvement / reduction). ``relative_gain`` / ``relative_increase_percent``
are the higher-is-better counterparts and ``identity`` is the absolute-value
form, both required for real single- and multi-config experiments.
"""

from __future__ import annotations

from typing import Callable


def _f_identity(o: dict) -> "float | None":
    return o["value"]


def _f_relative_speedup(o: dict) -> "float | None":
    return o["baseline"] / o["proposed"] if o["proposed"] else None


def _f_relative_gain(o: dict) -> "float | None":
    return o["proposed"] / o["baseline"] if o["baseline"] else None


def _f_relative_improvement_percent(o: dict) -> "float | None":
    return (o["baseline"] - o["proposed"]) / o["baseline"] * 100 if o["baseline"] else None


def _f_relative_increase_percent(o: dict) -> "float | None":
    return (o["proposed"] - o["baseline"]) / o["baseline"] * 100 if o["baseline"] else None


def _f_relative_reduction_percent(o: dict) -> "float | None":
    return (o["baseline"] - o["proposed"]) / o["baseline"] * 100 if o["baseline"] else None


def _f_absolute_difference(o: dict) -> "float | None":
    return o["proposed"] - o["baseline"]


def _f_ratio_percent(o: dict) -> "float | None":
    # proposed / baseline * 100. Generic attainment-ratio form (e.g. measured /
    # roofline-ceiling * 100); operands may reference different metrics of the
    # same config via the cfgN:metric declaration form.
    return o["proposed"] / o["baseline"] * 100 if o["baseline"] else None


FORMULAS: dict[str, tuple[tuple[str, ...], Callable[[dict], "float | None"]]] = {
    "identity": (("value",), _f_identity),
    "relative_speedup": (("baseline", "proposed"), _f_relative_speedup),
    "relative_gain": (("baseline", "proposed"), _f_relative_gain),
    "relative_improvement_percent": (("baseline", "proposed"), _f_relative_improvement_percent),
    "relative_increase_percent": (("baseline", "proposed"), _f_relative_increase_percent),
    "relative_reduction_percent": (("baseline", "proposed"), _f_relative_reduction_percent),
    "absolute_difference": (("baseline", "proposed"), _f_absolute_difference),
    "ratio_percent": (("baseline", "proposed"), _f_ratio_percent),
}


def required_roles(formula: str) -> tuple[str, ...]:
    spec = FORMULAS.get(formula)
    return spec[0] if spec else ()


def recompute(formula: str, operand_values: dict[str, float]) -> "float | None":
    """Re-derive a numeric value from resolved operand scalars.

    Returns ``None`` when the formula is unknown, an operand is missing/None,
    or the computation is undefined (division by zero).
    """
    spec = FORMULAS.get(formula)
    if spec is None:
        return None
    roles, fn = spec
    if any(r not in operand_values or operand_values[r] is None for r in roles):
        return None
    try:
        return fn(operand_values)
    except ZeroDivisionError:
        return None


def within_tolerance(reported: float, recomputed: float, tolerance: dict) -> bool:
    """True iff ``reported`` matches ``recomputed`` within absolute OR relative
    tolerance. An empty tolerance dict defaults to exact match."""
    if recomputed is None or reported is None:
        return False
    abs_tol = float((tolerance or {}).get("absolute", 0.0) or 0.0)
    rel_tol = float((tolerance or {}).get("relative", 0.0) or 0.0)
    diff = abs(reported - recomputed)
    if diff <= abs_tol:
        return True
    if rel_tol and abs(recomputed) > 0:
        return diff / abs(recomputed) <= rel_tol
    return diff == 0.0
