"""Declared metric_contract enforcement (Phases 2-4 of the metric-correctness contract).

DOMAIN-GENERAL: every check evaluates a DECLARED expression / declaration from
``science_data["metric_contract"]`` over a config's measured metrics. The harness
supplies only the general machinery (safe expression evaluation, provenance
lookup, tolerance compare); all semantics (the formula, the invariants, the
correctness predicate, the regime conditional) are DECLARED per experiment by the
idea/rubric LLM. There is NO roofline/GFLOP/cache knowledge here.

Contract schema (all expressions are restricted-AST, see formula_eval):
  metric_contract = {
    "key": "<metric name the paper reports>",
    "formula": "geomean(gflops_byK / ceiling_byK)",          # B: harness recomputes 'value'
    "ceiling_select": "cache_bw if effective_bw > dram_peak_bw else dram_peak_bw",  # C: declared regime
    "invariants": ["value <= 1", "model_sec <= sec"],         # D/E: boolean exprs, False => violation
    "correctness": {"expr": "max_abs_err < 1e-4", "requires": ["max_abs_err"]},     # A
    "required_measured": ["dram_peak_bw", "cache_bw", "ceiling_byK"],               # B provenance
    "tolerance": {"absolute": 0.0, "relative": 0.02},
  }

Finding types (all added to policy.always_block_on): invariant_violation,
correctness_failed, correctness_uncovered, placeholder_denominator,
recompute_mismatch. Provenance is read from ``config["_provenance"]``
(name -> "microbench"|"benchmark"|"declared"|"constant"); a required_measured
operand must be microbench/benchmark, never declared/constant.
"""

from __future__ import annotations

from typing import Any, Iterator

from ari.pipeline.claim_gate import formula_eval, numeric

_MEASURED_SOURCES = {"microbench", "benchmark", "measurement", "measured"}


def _flatten_metrics(config: dict) -> dict:
    """Config result metrics as a flat {name: scalar|list} for expression binding.

    Scans measurements/scores/metrics (skips params and ``_``-prefixed internals,
    matching invariants._iter_result_metrics). Lists of numbers are kept (for
    per-K / per-sweep operands).
    """
    out: dict[str, Any] = {}

    def take(d: dict) -> None:
        for k, v in d.items():
            if not isinstance(k, str) or k.startswith("_"):
                continue
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                out.setdefault(k, float(v))
            elif isinstance(v, list) and v and all(isinstance(e, (int, float)) and not isinstance(e, bool) for e in v):
                out.setdefault(k, [float(e) for e in v])
            elif isinstance(v, dict):
                take(v)

    for container in ("measurements", "scores", "metrics"):
        d = config.get(container)
        if isinstance(d, dict):
            take(d)
    return out


def _provenance(config: dict) -> dict:
    prov = config.get("_provenance")
    return prov if isinstance(prov, dict) else {}


def _iter_configs(science_data: dict) -> Iterator[tuple[str, dict]]:
    for cfg in science_data.get("configurations", []) or []:
        if isinstance(cfg, dict):
            cid = cfg.get("config_id") or cfg.get("label") or cfg.get("node_id") or cfg.get("rank") or "?"
            yield str(cid), cfg


def check_contract(science_data: dict) -> list[dict]:
    """Enforce the declared metric_contract over every configuration.

    Returns a list of findings (empty when no contract or all pass). No-op when
    ``science_data`` has no ``metric_contract`` (legacy runs keep prior behaviour).
    """
    findings: list[dict] = []
    if not isinstance(science_data, dict):
        return findings
    mc = science_data.get("metric_contract")
    if not isinstance(mc, dict):
        return findings

    key = mc.get("key")
    formula = mc.get("formula")
    ceiling_select = mc.get("ceiling_select")
    invs = [e for e in (mc.get("invariants") or []) if isinstance(e, str)]
    correctness = mc.get("correctness") if isinstance(mc.get("correctness"), dict) else None
    required_measured = [n for n in (mc.get("required_measured") or []) if isinstance(n, str)]
    tol = mc.get("tolerance") or {"absolute": 0.0, "relative": 0.02}

    for cid, cfg in _iter_configs(science_data):
        vars_: dict[str, Any] = _flatten_metrics(cfg)
        prov = _provenance(cfg)

        # C: declared regime — evaluate the conditional to bind the selected
        # ceiling. The harness only EVALUATES the declared conditional; it never
        # infers the regime, so no domain (cache/DRAM) knowledge enters here.
        if isinstance(ceiling_select, str):
            sel = formula_eval.safe_eval(ceiling_select, vars_)
            if sel is not None:
                vars_["ceiling"] = sel

        # 'value' = the paper-reported metric (the key). Bound for invariants that
        # reference 'value', and used as the comparison target for owned recompute.
        reported = vars_.get(key) if isinstance(key, str) else None
        if reported is not None and isinstance(reported, (int, float)):
            vars_.setdefault("value", float(reported))

        # B: provenance — required ceilings/denominators must be MEASURED, not a
        # hardcoded placeholder/constant. This is what kills a placeholder bw.
        for nm in required_measured:
            src = str(prov.get(nm, "")).strip().lower()
            if src not in _MEASURED_SOURCES:
                findings.append({
                    "type": "placeholder_denominator", "config_id": cid, "metric": nm,
                    "provenance": src or "absent",
                    "message": (f"metric_contract requires '{nm}' to be a measured quantity "
                                f"(microbench/benchmark) but its provenance is '{src or 'absent'}' — "
                                f"a placeholder/constant denominator makes the normalized metric meaningless"),
                })

        # D/E: declared invariants (boolean exprs). False => violation; None
        # (unevaluable, e.g. missing operand) => skipped (not a false positive).
        for expr in invs:
            r = formula_eval.safe_eval(expr, vars_)
            if r is False:
                findings.append({
                    "type": "invariant_violation", "config_id": cid, "expr": expr,
                    "kind": "declared",
                    "message": f"declared invariant '{expr}' is violated for config '{cid}'",
                })

        # A: correctness — a declared pass predicate over a required residual that
        # the node must have emitted. Missing => uncovered (block); failing => failed.
        if correctness:
            req = [n for n in (correctness.get("requires") or []) if isinstance(n, str)]
            missing = [n for n in req if n not in vars_]
            if missing:
                findings.append({
                    "type": "correctness_uncovered", "config_id": cid, "missing": missing,
                    "message": (f"metric_contract declares a correctness check requiring {missing} "
                                f"but config '{cid}' did not emit it — the kernel's numerical "
                                f"correctness is unverified"),
                })
            else:
                expr = correctness.get("expr")
                r = formula_eval.safe_eval(expr, vars_) if isinstance(expr, str) else None
                if r is False:
                    findings.append({
                        "type": "correctness_failed", "config_id": cid, "expr": expr,
                        "message": f"correctness check '{expr}' failed for config '{cid}'",
                    })

        # B: harness-owned recompute — recompute the metric from raw operands via
        # the declared formula and require it to match the reported value. The node
        # cannot pass off a value computed against a placeholder ceiling.
        if isinstance(formula, str) and reported is not None and isinstance(reported, (int, float)):
            recomputed = formula_eval.safe_eval(formula, vars_)
            if isinstance(recomputed, (int, float)) and not numeric.within_tolerance(float(reported), float(recomputed), tol):
                findings.append({
                    "type": "recompute_mismatch", "config_id": cid, "metric": key,
                    "reported": float(reported), "recomputed": round(float(recomputed), 6),
                    "formula": formula,
                    "message": (f"reported '{key}'={reported} for config '{cid}' is not reproducible "
                                f"from the declared formula '{formula}' (recomputed "
                                f"{round(float(recomputed), 6)})"),
                })

    return findings
