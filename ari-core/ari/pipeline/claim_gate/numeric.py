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

import json
import hashlib
import inspect
from typing import Callable

from ari.pipeline.claim_gate.formula_eval import evaluator_digest


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


# Closed, dimension-preserving conversion registry.  Unknown spellings are
# rejected; the evaluator never infers a unit from a metric name.
_UNIT_SCALE: dict[str, tuple[str, float]] = {
    "s": ("time", 1.0),
    "ms": ("time", 1e-3),
    "us": ("time", 1e-6),
    "µs": ("time", 1e-6),
    "ns": ("time", 1e-9),
    "fraction": ("fraction", 1.0),
    "%": ("fraction", 1e-2),
    "percent": ("fraction", 1e-2),
    "B": ("bytes", 1.0),
    "kB": ("bytes", 1e3),
    "MB": ("bytes", 1e6),
    "GB": ("bytes", 1e9),
    "KiB": ("bytes", 1024.0),
    "MiB": ("bytes", 1024.0**2),
    "GiB": ("bytes", 1024.0**3),
    "Hz": ("frequency", 1.0),
    "kHz": ("frequency", 1e3),
    "MHz": ("frequency", 1e6),
    "GHz": ("frequency", 1e9),
    "ratio": ("ratio", 1.0),
    "count": ("count", 1.0),
}


def unit_registry_digest() -> str:
    payload = json.dumps(
        _UNIT_SCALE, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def convert_value(
    value: float, source_unit: str, target_unit: str
) -> tuple["float | None", "str | None"]:
    """Convert through the closed registry and return conversion provenance."""

    if source_unit == target_unit:
        if source_unit in _UNIT_SCALE or source_unit == "":
            return float(value), None
        return None, None
    source = _UNIT_SCALE.get(source_unit)
    target = _UNIT_SCALE.get(target_unit)
    if source is None or target is None or source[0] != target[0]:
        return None, None
    converted = float(value) * source[1] / target[1]
    return converted, f"{source_unit}->{target_unit}@{unit_registry_digest()}"


def formula_registry_digest() -> str:
    payload = {
        "declared_expression_evaluator": evaluator_digest(),
        "named_formulas": {
            name: {
                "roles": list(roles),
                "implementation": inspect.getsource(implementation).strip(),
            }
            for name, (roles, implementation) in sorted(FORMULAS.items())
        },
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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
