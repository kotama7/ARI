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
    "claims": [{"claim": "huge pages help reach-limited regimes",                   # F plan-fidelity
                "required_evidence": ["thp_on_tput", "thp_off_tput"]}],
    "correctness_required": true,     # G idea-owned: a correctness residual MUST be emitted (tagged)
    "ceiling_must_be_measured": true, # G idea-owned: a measured-provenance ceiling MUST be emitted
    "tolerance": {"absolute": 0.0, "relative": 0.02},
  }

The G flags are IDEA-OWNED (the agent cannot drop them) but satisfied by EVIDENCE,
not by an agent-declared name: the agent emits a tagged measurement
(_provenance "microbench"/"benchmark" for a ceiling, "correctness"/"reference" for a
residual) and the gate keys on that tag's PRESENCE run-level -- so an honest run is
never blocked and only a placeholder/no-check 骨抜き is. Finding types (all added to
policy.always_block_on): invariant_violation, correctness_failed,
correctness_uncovered, placeholder_denominator, recompute_mismatch,
claim_evidence_missing, ceiling_unmeasured. Provenance is read from
``config["_provenance"]`` (name -> "microbench"|"benchmark"|"correctness"|"declared"|
"constant"); a required_measured operand must be microbench/benchmark, never
declared/constant.
"""

from __future__ import annotations

from typing import Any, Iterator

from ari.pipeline.claim_gate import formula_eval, numeric

_MEASURED_SOURCES = {"microbench", "benchmark", "measurement", "measured"}
# Root tokens for TOLERANT provenance recognition in the idea-owned requirement-flag
# checks (G). Exact-set membership over-blocks an HONEST run that paraphrases the tag
# (e.g. "verified" instead of "correctness", "stream" instead of "microbench"), so the
# flag checks match a SUBSTRING root instead. Domain-neutral: the gate only checks the
# tag looks like a measured/verification source, never what the number means. (The
# stricter per-operand placeholder_denominator check keeps exact _MEASURED_SOURCES.)
# "baseline" is a measured-ceiling method (the obligation calls "a baseline run" a way
# to MEASURE a normalization ceiling), so it lives in the MEASURED roots -- NOT in the
# correctness roots, where it would wrongly discharge correctness_required for a
# perf-only run. "check" was dropped: as a bare 5-char token it substring-matched
# clearly-non-correctness values the pipeline emits (checkpoint / checksum /
# sanity_check). The remaining correctness roots are unambiguous verification words.
_MEASURED_ROOTS = ("bench", "measur", "empiric", "stream", "baseline")
_CORRECTNESS_ROOTS = ("correct", "verif", "referenc", "valid", "gold", "truth",
                      "oracle", "ground_truth")


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


def _has_provenance_root(science_data: dict, roots: tuple) -> bool:
    """True if ANY configuration tags ANY operand with a provenance value whose text
    contains one of *roots*.

    Run-level evidence presence: this is how the idea-owned requirement flags are
    satisfied -- the agent emits a tagged measurement (a measured ceiling, a
    correctness residual) into results.json, which flows to ``config["_provenance"]``.
    Substring/root matching is deliberately TOLERANT so an honest run that paraphrases
    the tag is not over-blocked. Presence-only (the accepted boundary): the gate checks
    the tag looks like a measured/verification source, not that the number is truthful.
    """
    for _cid, cfg in _iter_configs(science_data):
        for v in _provenance(cfg).values():
            text = str(v).strip().lower()
            if text and any(root in text for root in roots):
                return True
    return False


def _any_root(values, roots: tuple) -> bool:
    for v in values:
        text = str(v).strip().lower()
        if text and any(root in text for root in roots):
            return True
    return False


def check_emission(contract: dict, measurements: dict, provenance: dict) -> list:
    """Point-of-emission contract feedback for the PRODUCER (emit_results).

    The final gate runs long after the node is gone; an agent that did the work but
    DROPPED the evidence in its final emit (observed on a real run: the kernel was
    verified correct -- correctness columns sat in its own results.csv -- yet
    emit_results carried only throughput, so the paper was blocked for a check that
    HAD passed) gets no chance to fix it. This mirrors the gate's presence checks at
    the moment the agent reports, returning human-readable WARNINGS the tool result
    surfaces so the agent can immediately re-emit (emit_results overwrites by
    design). Advisory only -- the emission itself is never blocked or altered.
    Domain-neutral: evaluates only the DECLARED contract.
    """
    warnings: list = []
    if not isinstance(contract, dict) or not contract:
        return warnings
    meas = measurements if isinstance(measurements, dict) else {}
    prov = provenance if isinstance(provenance, dict) else {}

    if contract.get("correctness_required") and not _any_root(prov.values(), _CORRECTNESS_ROOTS):
        warnings.append(
            "correctness_required: no measurement is tagged as correctness evidence — if you "
            "verified against an independent reference, RE-EMIT including the residual (e.g. "
            'max_abs_err) in measurements with provenance {"<residual>": "correctness"}; '
            "otherwise the paper will be BLOCKED at finalize (correctness_uncovered).")
    if contract.get("ceiling_must_be_measured") and not _any_root(prov.values(), _MEASURED_ROOTS):
        warnings.append(
            "ceiling_must_be_measured: no measurement carries a measured (microbench/benchmark) "
            "provenance tag — tag your empirically measured ceiling/peak or the paper will be "
            "BLOCKED at finalize (ceiling_unmeasured).")
    claims = [c for c in (contract.get("claims") or []) if isinstance(c, dict)]
    if claims:
        present = set(meas.keys())
        uncovered = []
        for c in claims:
            req = [n for n in (c.get("required_evidence") or []) if isinstance(n, str) and n.strip()]
            if req and not any(n in present for n in req):
                uncovered.append((str(c.get("claim") or "")[:80], req[:4]))
        if uncovered:
            lines = "; ".join(f"{cl!r} needs one of {ev}" for cl, ev in uncovered[:6])
            warnings.append(
                f"claims: {len(uncovered)} declared claim(s) have NO supporting measurement in "
                f"this emission ({lines}{' …' if len(uncovered) > 6 else ''}) — the gate matches "
                "measurement names EXACTLY: re-emit your evidence UNDER THESE EXACT NAMES (rename "
                "your own keys if they measure the same thing; a negative result is fine) or the "
                "paper will be BLOCKED at finalize (claim_evidence_missing).")
    return warnings


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

    # F: plan-fidelity — declared falsifiable claims must be EVALUABLE from the
    # emitted data. A claim the idea promised (e.g. "mechanism M helps regime R")
    # whose required_evidence measurements are WHOLLY ABSENT across the run is an
    # untested claim — the experiment produced no data to evaluate it (the
    # claim_implementation骨抜き failure: a mechanism is claimed but never measured).
    # Run-level: union of measured metric names over every configuration. Presence-
    # only — a NEGATIVE result is fine (the measurements exist, the outcome is just
    # unfavourable); only ZERO supporting evidence blocks. High-precision: a claim
    # with ANY of its declared evidence present is NOT blocked here (the advisory
    # review layer handles partial/weak support). Names are coordinated top-down
    # via the producer obligation, like ``required_measured``.
    claims = [c for c in (mc.get("claims") or []) if isinstance(c, dict)]
    if claims:
        present: set[str] = set()
        for _cid, cfg in _iter_configs(science_data):
            present.update(_flatten_metrics(cfg).keys())
        for idx, c in enumerate(claims):
            req = [n for n in (c.get("required_evidence") or []) if isinstance(n, str) and n.strip()]
            if not req:
                continue
            if not any(n in present for n in req):
                findings.append({
                    "type": "claim_evidence_missing",
                    "claim": str(c.get("claim") or f"claim[{idx}]"),
                    "missing": req,
                    "message": (f"the idea declares the falsifiable claim "
                                f"\"{str(c.get('claim') or '')[:160]}\" but the run emitted NONE of the "
                                f"measurement(s) {req} needed to evaluate it — the claimed result/"
                                f"mechanism is unsupported by any evidence (declared but never tested)"),
                })

    # G: idea-owned requirement flags. The IDEA decides WHETHER a measured ceiling /
    # a correctness check is required (domain-aware: a theory result / analytic-constant
    # normalization sets neither). The AGENT satisfies the requirement by emitting the
    # corresponding _provenance EVIDENCE (a microbench/benchmark-tagged ceiling, a
    # correctness/reference-tagged residual) into results.json -- which already flows to
    # config["_provenance"]. The gate keys on evidence PRESENCE, run-level, so:
    #   * an honest run that measured a ceiling / verified correctness is NEVER blocked
    #     (the tag is present) -- no cross-party naming, no universal over-block;
    #   * a run that emitted NO such evidence (a placeholder denominator / no correctness
    #     check at all -- the D1/D2/D3 骨抜き) IS blocked. The agent cannot drop the
    #     requirement (idea-owned); it can only satisfy it by producing the evidence.
    if mc.get("ceiling_must_be_measured") and not _has_provenance_root(science_data, _MEASURED_ROOTS):
        findings.append({
            "type": "ceiling_unmeasured", "config_id": "*",
            "message": ("the idea requires this normalized metric's denominator to be "
                        "empirically measured (ceiling_must_be_measured) but no configuration "
                        "emitted any measured (microbench/benchmark) operand — the normalization "
                        "rests on an unmeasured placeholder ceiling"),
        })
    if mc.get("correctness_required") and not _has_provenance_root(science_data, _CORRECTNESS_ROOTS):
        findings.append({
            "type": "correctness_uncovered", "config_id": "*", "missing": ["correctness"],
            "message": ("the idea requires a correctness check for this metric "
                        "(correctness_required) but no configuration emitted a correctness/reference "
                        "residual (no operand tagged correctness/reference/validation in _provenance) "
                        "— the production output is unverified against any independent reference"),
        })

    return findings
