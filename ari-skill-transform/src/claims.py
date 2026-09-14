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
  - claims ground only on canonical ``results.json`` **measurements**, never on
    compatibility scores, the legacy node metric bag, or the
    LLM-generated ``experiment_context`` / ``implementation_overview``.

Formula evaluation is imported through ``ari.public.science_data``.  The
transform producer and hard gate therefore execute the exact same registry and
implementation digest; this module contains no mathematical mirror.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ari.public.science_data import FORMULAS as FORMULAS, recompute


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
    cross_environment: bool = (
        False  # True iff operands span different execution environments
    )
    aggregation: dict = field(
        default_factory=lambda: {"statistic": "mean", "trials": None}
    )
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
# Metric resolution (deterministic, typed measurements only)
# ──────────────────────────────────────────────────────────────────────────


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _resolve_metric(node: dict, results: dict, metric: str) -> tuple[float | None, str]:
    """Return (value, metric_path) for ``metric`` on a node, deterministically.

    Only the canonical measurement projection is eligible. ``params``,
    ``scores``, and the flat legacy node metric bag are intentionally skipped.
    """
    del node
    meas = results.get("measurements") if isinstance(results, dict) else None
    if isinstance(meas, dict) and _is_number(meas.get(metric)):
        return float(meas[metric]), f"measurements.{metric}"
    return None, ""


def _autodetect_primary_metric(
    good_nodes: list[dict], typed_results: dict[str, dict]
) -> str:
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
    run_id: str = "",
    metric_unit: str = "",
    tolerance: "dict | None" = None,
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
    assertion_tolerance = dict(tolerance or {"absolute": 0.0, "relative": 0.02})

    def _operand(node_id: str, metric_path: str, environment: dict) -> dict:
        value = {
            "node_id": node_id,
            "metric_path": metric_path,
            "environment": environment,
        }
        if run_id:
            value["run_id"] = run_id
        return value

    def _result_ref(node_id: str, metric_path: str) -> dict:
        value = {"node_id": node_id, "metric_path": metric_path}
        if run_id:
            value["run_id"] = run_id
        return value

    def _env_of(nid: str) -> dict:
        e = node_env.get(nid) or {}
        return {
            "executor": e.get("executor", ""),
            "cpu_model": e.get("cpu_model", ""),
            "arch": e.get("arch", ""),
        }

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

    best = (
        max(cands, key=lambda c: c[2])
        if higher_is_better
        else min(cands, key=lambda c: c[2])
    )
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
        worst = (
            min(others, key=lambda c: c[2])
            if higher_is_better
            else max(others, key=lambda c: c[2])
        )

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
        unit=metric_unit,
        formula="identity",
        operands={"value": _operand(best_nid, best_path, best_env)},
        cross_environment=False,
        tolerance=assertion_tolerance,
    )
    claim = Claim(
        id=cid,
        text=f"The proposed configuration achieves {_fmt(best_val)} for {pm}.",
        section="results",
        status="draft",
        supported_by={
            "nodes": [best_nid],
            "results": [_result_ref(best_nid, best_path)],
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
        formula = (
            "relative_increase_percent"
            if higher_is_better
            else "relative_reduction_percent"
        )
        comp_val = recompute(formula, {"baseline": worst_val, "proposed": best_val})
        verb = "improves" if higher_is_better else "reduces"
        cid2 = _next_cc()
        if comp_val is None:
            return {
                "claims": [asdict(c) for c in claims],
                "numeric_assertions": flat,
            }
        na2 = NumericAssertion(
            id=_next_nc(),
            text_span=f"{verb} {pm} by {_fmt(comp_val)}%",
            metric=pm,
            value=comp_val,
            unit="%",
            formula=formula,
            operands={
                "baseline": _operand(worst_nid, worst_path, worst_env),
                "proposed": _operand(best_nid, best_path, best_env),
            },
            cross_environment=cross,
            tolerance=assertion_tolerance,
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
                    _result_ref(best_nid, best_path),
                    _result_ref(worst_nid, worst_path),
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
