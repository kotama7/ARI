"""Candidate claim / numeric-assertion generation for the Research Contract substrate.

Phase A of the Story2Proposal architectural integration (see
``../PLAN_s2p_science_data_claims.md`` and ``../../Story2Proposal計画書.md``).

``science_data.json`` is the Research Contract substrate consumed by the paper
writer. This module deterministically derives candidate ``claims[]`` and
``numeric_assertions[]`` from the executed-node evidence so the writer can
reference them by id and the hard gate can re-verify the numbers.

Grounding is **deterministic**: every operand references a real
``(node_id, metric_path)`` resolvable from ``tree.json`` / ``results.json``.
The claim *prose* generated here is a templated *seed*; the paper writer
(``ari-skill-paper``) produces the final wording while preserving the
``% CLAIM:Cx:NCx`` anchors (Phase A2). The deterministic hard gate
(``ari-core``) re-computes the asserted numbers from ``results.json``.

Design constraints honoured (master plan §Phase A):
  - claim carries the **real node_id** directly (configurations strip node_id,
    so we never rely on rank/label to recover it);
  - result is ``(node_id, metric_path)`` — not an opaque id;
  - ``supported_by.figures`` starts **empty** (figures are late-bound by the
    paper post-processor after ``generate_figures``);
  - claims ground only on the **deterministic** part of science_data
    (``results.json`` measurements/scores or the node metrics), never on the
    LLM-generated ``experiment_context`` / ``implementation_overview``.

The formula registry below is mirrored by ari-core's
``ari/pipeline/claim_gate/numeric.py`` so the gate recomputes with identical
semantics. **Keep the two in sync.**
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


# ──────────────────────────────────────────────────────────────────────────
# Formula registry (mirrored in ari-core/ari/pipeline/claim_gate/numeric.py)
# ──────────────────────────────────────────────────────────────────────────
# Each entry maps a formula name to (required operand roles, callable). The
# callable receives a dict {role: float} and returns a float (or None when the
# computation is undefined, e.g. division by zero). The documented master-plan
# formulas are the lower-is-better family (speedup / improvement / reduction);
# the *_increase_percent / relative_gain / identity entries are the
# higher-is-better and absolute counterparts needed for real single- and
# multi-config experiments (master plan lists "formula examples", non-exhaustive).

def _f_identity(o: dict) -> float | None:
    return o["value"]


def _f_relative_speedup(o: dict) -> float | None:
    return o["baseline"] / o["proposed"] if o["proposed"] else None


def _f_relative_gain(o: dict) -> float | None:
    return o["proposed"] / o["baseline"] if o["baseline"] else None


def _f_relative_improvement_percent(o: dict) -> float | None:
    return (o["baseline"] - o["proposed"]) / o["baseline"] * 100 if o["baseline"] else None


def _f_relative_increase_percent(o: dict) -> float | None:
    return (o["proposed"] - o["baseline"]) / o["baseline"] * 100 if o["baseline"] else None


def _f_relative_reduction_percent(o: dict) -> float | None:
    return (o["baseline"] - o["proposed"]) / o["baseline"] * 100 if o["baseline"] else None


def _f_absolute_difference(o: dict) -> float | None:
    return o["proposed"] - o["baseline"]


def _f_ratio_percent(o: dict) -> float | None:
    # proposed / baseline * 100 (generic attainment ratio, e.g. measured/ceiling).
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


def recompute(formula: str, operand_values: dict[str, float]) -> float | None:
    """Re-derive a numeric assertion value from resolved operand scalars.

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


# ──────────────────────────────────────────────────────────────────────────
# Dataclasses (serialized to plain dicts for science_data.json)
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class NumericAssertion:
    id: str
    text_span: str
    metric: str
    value: float | None
    unit: str
    formula: str
    operands: dict
    cross_environment: bool = False  # True iff operands span different execution environments
    aggregation: dict = field(default_factory=lambda: {"statistic": "mean", "trials": None})
    tolerance: dict = field(default_factory=lambda: {"absolute": 0.0, "relative": 0.02})


@dataclass
class Claim:
    id: str
    text: str
    section: str
    status: str
    supported_by: dict
    numeric_assertions: list
    risk: str


# ──────────────────────────────────────────────────────────────────────────
# Metric resolution (deterministic) — mirrors hard-gate operand resolution
# ──────────────────────────────────────────────────────────────────────────

def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _resolve_metric(node: dict, results: dict, metric: str) -> tuple[float | None, str]:
    """Return (value, metric_path) for ``metric`` on a node, deterministically.

    Resolution order mirrors the hard gate's operand resolver:
      1. results.json ``measurements.<metric>``
      2. results.json ``scores.<metric>``
      3. node ``metrics.<metric>`` (flat legacy bag)
    ``params`` is intentionally skipped: those are inputs, not measurements.
    """
    meas = results.get("measurements") if isinstance(results, dict) else None
    if isinstance(meas, dict) and _is_number(meas.get(metric)):
        return float(meas[metric]), f"measurements.{metric}"
    scores = results.get("scores") if isinstance(results, dict) else None
    if isinstance(scores, dict) and _is_number(scores.get(metric)):
        return float(scores[metric]), f"scores.{metric}"
    metrics = node.get("metrics") if isinstance(node, dict) else None
    if isinstance(metrics, dict) and _is_number(metrics.get(metric)):
        return float(metrics[metric]), f"metrics.{metric}"
    return None, ""


def _autodetect_primary_metric(good_nodes: list[dict], typed_results: dict[str, dict]) -> str:
    """Pick the most-covered measurement key when no primary_metric is given.

    Excludes reserved ``_`` keys and any key declared as an input parameter in
    some node's ``results.json`` ``params`` (those are inputs, not results).
    Deterministic: ranks by coverage (descending), tie-break alphabetical.
    """
    input_keys: set[str] = set()
    for rj in typed_results.values():
        if isinstance(rj, dict) and isinstance(rj.get("params"), dict):
            input_keys.update(str(k) for k in rj["params"].keys())
    coverage: dict[str, int] = {}
    for n in good_nodes:
        nid = n.get("id") or n.get("node_id") or ""
        rj = typed_results.get(nid, {})
        keys: set[str] = set()
        meas = rj.get("measurements") if isinstance(rj, dict) else None
        if isinstance(meas, dict):
            keys.update(k for k, v in meas.items() if _is_number(v))
        scores = rj.get("scores") if isinstance(rj, dict) else None
        if isinstance(scores, dict):
            keys.update(k for k, v in scores.items() if _is_number(v))
        metrics = n.get("metrics") if isinstance(n, dict) else None
        if isinstance(metrics, dict):
            keys.update(k for k, v in metrics.items() if _is_number(v))
        for k in keys:
            if not isinstance(k, str) or k.startswith("_") or k in input_keys:
                continue
            coverage[k] = coverage.get(k, 0) + 1
    if not coverage:
        return ""
    return sorted(coverage.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _fmt(v: float | None) -> str:
    if v is None:
        return "?"
    return f"{v:g}"


def build_science_claims(
    good_nodes: list[dict],
    typed_results: dict[str, dict],
    primary_metric: str = "",
    higher_is_better: bool = True,
    node_env: "dict[str, dict] | None" = None,
    comparison_scope: str = "any",
) -> dict:
    """Deterministically build candidate claims[] + flattened numeric_assertions[].

    Returns ``{"claims": [...], "numeric_assertions": [...]}``; empty when no
    measurement resolves. Each operand is tagged with its execution
    ``environment`` (provenance transparency); a comparison assertion records
    ``cross_environment`` when its operands span different environments.

    ``node_env`` maps node_id -> {executor, cpu_model, arch} (from node_report).
    ``comparison_scope`` is INJECTED research intent (P4), NOT a hardcoded rule:
      - ``"any"`` (default): build the comparison from the global best/worst,
        tagging cross-environment transparently — correct for cross-architecture
        studies where the cross-host comparison IS the contribution.
      - ``"same_environment"``: restrict the comparison baseline to the best
        node's own environment; skip the comparison when no same-env peer exists
        — correct for single-architecture optimization studies, so an accidental
        cross-host run is never turned into a spurious speedup claim.
    The generator never hard-forbids cross-env: it makes provenance explicit and
    lets the injected intent (and the hard gate) decide.
    """
    node_env = node_env or {}
    scope = (comparison_scope or "any").strip().lower() or "any"

    def _env_of(nid: str) -> dict:
        e = node_env.get(nid) or {}
        return {"executor": e.get("executor", ""), "cpu_model": e.get("cpu_model", ""),
                "arch": e.get("arch", "")}

    def _env_key(e: dict) -> tuple:
        return (e.get("executor", ""), e.get("cpu_model", ""), e.get("arch", ""))

    def _collect(metric: str) -> list[tuple[str, dict, float, str]]:
        out: list[tuple[str, dict, float, str]] = []
        if not metric:
            return out
        for n in good_nodes:
            nid = n.get("id") or n.get("node_id") or ""
            if not nid:
                continue
            val, path = _resolve_metric(n, typed_results.get(nid, {}), metric)
            if val is None:
                continue
            out.append((nid, n, val, path))
        return out

    # The configured primary_metric may be a prose description (the idea-skill
    # often emits a sentence, not a metric key). Try it verbatim first; if it
    # resolves to no node metric, fall back to the most-covered measurement key.
    pm = (primary_metric or "").strip()
    cands = _collect(pm)
    if not cands:
        auto = _autodetect_primary_metric(good_nodes, typed_results)
        if auto and auto != pm:
            pm = auto
            cands = _collect(pm)
    if not cands:
        return {"claims": [], "numeric_assertions": []}

    best = max(cands, key=lambda c: c[2]) if higher_is_better else min(cands, key=lambda c: c[2])
    best_nid, _bn, best_val, best_path = best
    best_env = _env_of(best_nid)

    # Baseline (worst) selection respects the injected comparison_scope. Under
    # "same_environment" the baseline must share the best node's environment, so
    # an accidental cross-host run is not turned into a spurious comparison.
    others = [c for c in cands if c[0] != best_nid]
    if scope == "same_environment":
        others = [c for c in others if _env_key(_env_of(c[0])) == _env_key(best_env)]
    worst = None
    if others:
        worst = min(others, key=lambda c: c[2]) if higher_is_better else max(others, key=lambda c: c[2])

    claims: list[Claim] = []
    flat: list[dict] = []
    _nc = [0]
    _cc = [0]

    def _next_nc() -> str:
        _nc[0] += 1
        return f"NC{_nc[0]}"

    def _next_cc() -> str:
        _cc[0] += 1
        return f"C{_cc[0]}"

    risk = f"Evidence is based on {len(cands)} executed configuration(s) on a single benchmark."

    # ── C1: absolute value of the primary metric for the best configuration ──
    cid = _next_cc()
    na = NumericAssertion(
        id=_next_nc(),
        text_span=f"{_fmt(best_val)} {pm}",
        metric=pm,
        value=best_val,
        unit="",
        formula="identity",
        operands={"value": {"node_id": best_nid, "metric_path": best_path, "environment": best_env}},
        cross_environment=False,
    )
    claim = Claim(
        id=cid,
        text=f"The proposed configuration achieves {_fmt(best_val)} for {pm}.",
        section="results",
        status="draft",
        supported_by={
            "nodes": [best_nid],
            "results": [{"node_id": best_nid, "metric_path": best_path}],
            "figures": [],
            "artifacts": [],
        },
        numeric_assertions=[asdict(na)],
        risk=risk,
    )
    claims.append(claim)
    flat.append({**asdict(na), "claim_id": cid})

    # ── C2: comparison best vs baseline (per injected comparison_scope) ──
    if worst is not None and worst[2]:
        worst_nid, _wn, worst_val, worst_path = worst
        worst_env = _env_of(worst_nid)
        cross = _env_key(worst_env) != _env_key(best_env)
        formula = "relative_increase_percent" if higher_is_better else "relative_reduction_percent"
        comp_val = recompute(formula, {"baseline": worst_val, "proposed": best_val})
        verb = "improves" if higher_is_better else "reduces"
        cid2 = _next_cc()
        na2 = NumericAssertion(
            id=_next_nc(),
            text_span=f"{verb} {pm} by {_fmt(comp_val)}%",
            metric=pm,
            value=comp_val,
            unit="%",
            formula=formula,
            operands={
                "baseline": {"node_id": worst_nid, "metric_path": worst_path, "environment": worst_env},
                "proposed": {"node_id": best_nid, "metric_path": best_path, "environment": best_env},
            },
            cross_environment=cross,
        )
        _suffix = " across different execution environments" if cross else ""
        claim2 = Claim(
            id=cid2,
            text=(
                f"The proposed configuration {verb} {pm} by {_fmt(comp_val)}% "
                f"relative to the baseline configuration{_suffix}."
            ),
            section="results",
            status="draft",
            supported_by={
                "nodes": [best_nid, worst_nid],
                "results": [
                    {"node_id": best_nid, "metric_path": best_path},
                    {"node_id": worst_nid, "metric_path": worst_path},
                ],
                "figures": [],
                "artifacts": [],
            },
            numeric_assertions=[asdict(na2)],
            risk=risk,
        )
        claims.append(claim2)
        flat.append({**asdict(na2), "claim_id": cid2})

    return {
        "claims": [asdict(c) for c in claims],
        "numeric_assertions": flat,
    }
