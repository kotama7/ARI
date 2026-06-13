"""Concept->invariant registry + scanner (Phase 1 of the metric-correctness contract).

DOMAIN-GENERAL BY CONSTRUCTION. This module encodes ONLY universal mathematical
invariants (a value normalized to an upper bound cannot exceed 1; a probability
lies in [0,1]). It contains NO domain knowledge — no roofline, no GFLOP, no
bandwidth, no cache. The CSR-SpMM run that motivated it (a "roofline-normalized"
geomean of 3.15 > 1) is caught here only because *normalized <= 1* is true in
every domain, never because the harness knows what a roofline is.

Two paths:
  1. DECLARED (authoritative): a ``metric_contract`` (future runs) declares a
     concept and/or explicit invariants; those are enforced verbatim.
  2. NAME-INFERRED (backstop, for legacy/undeclared metrics): the metric *name*
     is classified into a mathematical concept by general keyword tokens
     (``normalized``/``efficiency``/``probability``/...), with an exclusion list
     for ambiguous magnitudes (``grad_norm`` etc.). A violation here means EITHER
     the value is impossible OR the metric is mis-named — both are defects; the
     finding message points the author to declare a ``metric_contract`` to
     disambiguate.

Used by ``claim_evidence_hard_gate`` (gate.py) which turns invariant_violation
findings into blocking errors at the final phase (see policy.always_block_on).
"""

from __future__ import annotations

import re
from typing import Iterator

# Float comparison slack so a legitimate 1.0 that lands at 1.0000000002 passes.
_EPS = 1e-6

# Concept -> list of (op, rhs) universal invariants. PURE MATH; no domain values.
# Kept intentionally minimal and unambiguous: only invariants that hold by the
# DEFINITION of the concept in every field.
CONCEPT_INVARIANTS: dict[str, list[tuple[str, float]]] = {
    # A throughput/efficiency normalized to an upper bound (roofline, peak, ideal)
    # cannot exceed 1 by definition. (No lower bound asserted: a normalized
    # *reduction*/*delta* can legitimately be signed.)
    "normalized": [("<=", 1.0)],
    # A probability/likelihood lies in the closed unit interval.
    "probability": [(">=", 0.0), ("<=", 1.0)],
}

# Tokens that, as a whole word inside an underscore/camel-split name, indicate a
# normalized (<=1) quantity. General across domains (HPC efficiency, ML utilization).
_NORMALIZED_TOKENS = frozenset({
    "normalized", "normalised", "normalize", "normalised", "norm",
    "efficiency", "utilization", "utilisation", "attainment",
})
_PROB_TOKENS = frozenset({"probability", "prob"})

# Names where a "norm" token means a vector/matrix MAGNITUDE (can exceed 1), or a
# percent that can exceed 100 — must NOT be classified as normalized<=1.
_EXCLUDE_SUBSTR = (
    "grad_norm", "gradient_norm", "gradnorm", "weight_norm", "weightnorm",
    "l1_norm", "l2_norm", "l1norm", "l2norm", "l_inf", "linf",
    "spectral_norm", "batch_norm", "batchnorm", "layer_norm", "layernorm",
    "group_norm", "groupnorm", "clip_norm", "norm_clip", "renorm",
    "norm_time", "normalization_time",
)


def classify_concept(name: str) -> "str | None":
    """Classify a metric NAME into a mathematical concept, or None.

    Conservative: percent-like names (which can exceed 100) and vector-norm names
    (which can exceed 1) are deliberately left unclassified to avoid false blocks.
    """
    if not isinstance(name, str) or not name:
        return None
    n = name.lower()
    if any(x in n for x in _EXCLUDE_SUBSTR):
        return None
    # percent / improvement / speedup can legitimately exceed 100 / 1 -> no bound.
    if "percent" in n or "%" in n or re.search(r"(?:^|_)pct(?:_|$)", n):
        return None
    if "fraction_of_peak" in n or "frac_of_peak" in n:
        return "normalized"
    toks = {t for t in re.split(r"[^a-z0-9]+", n) if t}
    if toks & _NORMALIZED_TOKENS or any(t.startswith("normali") for t in toks):
        return "normalized"
    if toks & _PROB_TOKENS:
        return "probability"
    return None


def _holds(value: float, op: str, rhs: float) -> bool:
    if op == "<=":
        return value <= rhs + _EPS
    if op == ">=":
        return value >= rhs - _EPS
    if op == "<":
        return value < rhs - _EPS
    if op == ">":
        return value > rhs + _EPS
    if op == "==":
        return abs(value - rhs) <= _EPS
    return True  # unknown op: do not flag


def _declared_bounds(science_data: dict) -> dict[str, list[tuple[str, float]]]:
    """Bound-type invariants declared in a metric_contract, keyed by metric name.

    Schema: ``metric_contract.invariants[] = {type:"bound", expr:"<metric>",
    op:"<=", rhs:1.0}``. Order-type invariants (cross-metric) are handled in a
    later phase (they need operand resolution); bound-type is sufficient for the
    universal-invariant guarantee here.
    """
    out: dict[str, list[tuple[str, float]]] = {}
    mc = science_data.get("metric_contract") if isinstance(science_data, dict) else None
    if not isinstance(mc, dict):
        return out
    for inv in mc.get("invariants", []) or []:
        if not isinstance(inv, dict) or inv.get("type") != "bound":
            continue
        expr = inv.get("expr")
        op = inv.get("op")
        rhs = inv.get("rhs")
        if isinstance(expr, str) and op in ("<=", ">=", "<", ">", "==") and isinstance(rhs, (int, float)):
            out.setdefault(expr, []).append((op, float(rhs)))
    return out


def _iter_result_metrics(config: dict) -> Iterator[tuple[str, float]]:
    """Yield (leaf_name, value) over a config's RESULT containers.

    Scans the typed result containers (measurements/scores) and the legacy flat
    ``metrics`` bag; skips inputs (``parameters``/``params``) and internal keys
    (``_``-prefixed, e.g. ``_axis_scores``/``_measurements_dict``). Recurses into
    nested dicts. The leaf key name is used for concept classification.
    """
    seen: set[tuple[str, float]] = set()

    def walk(d: dict) -> Iterator[tuple[str, float]]:
        for k, v in d.items():
            if not isinstance(k, str) or k.startswith("_"):
                continue
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                key = (k, float(v))
                if key not in seen:
                    seen.add(key)
                    yield k, float(v)
            elif isinstance(v, dict):
                yield from walk(v)

    for container in ("measurements", "scores", "metrics"):
        d = config.get(container)
        if isinstance(d, dict):
            yield from walk(d)


def scan_science_data(science_data: dict) -> list[dict]:
    """Scan all configurations' result metrics for universal-invariant violations.

    Returns a list of ``invariant_violation`` findings (empty when clean). Each
    violation is reported once per (config, metric, invariant).
    """
    findings: list[dict] = []
    if not isinstance(science_data, dict):
        return findings
    declared = _declared_bounds(science_data)
    emitted: set[tuple] = set()
    for cfg in science_data.get("configurations", []) or []:
        if not isinstance(cfg, dict):
            continue
        cid = cfg.get("config_id") or cfg.get("label") or cfg.get("node_id") or cfg.get("rank") or "?"
        for name, value in _iter_result_metrics(cfg):
            concept = classify_concept(name)
            invs: list[tuple[str, float]] = list(CONCEPT_INVARIANTS.get(concept, [])) if concept else []
            invs += declared.get(name, [])
            for op, rhs in invs:
                if _holds(value, op, rhs):
                    continue
                key = (str(cid), name, op, rhs)
                if key in emitted:
                    continue
                emitted.add(key)
                findings.append({
                    "type": "invariant_violation",
                    "config_id": str(cid),
                    "metric": name,
                    "value": value,
                    "invariant": f"value {op} {rhs:g}",
                    "concept": concept or "declared",
                    "message": (
                        f"metric '{name}'={value:g} violates universal invariant "
                        f"'value {op} {rhs:g}' for concept '{concept or 'declared'}' — "
                        f"the value is physically impossible, or the metric is mis-named "
                        f"(declare a metric_contract to disambiguate)"
                    ),
                })
    return findings
