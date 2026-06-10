"""Domain-general metric-correctness OBLIGATION for the implementing agent.

The *producer* half of the metric-correctness contract (the enforcement half is
``ari.pipeline.claim_gate``). When a node's metric is concept-classified
(``make_metric_spec`` emits a ``metric_contract`` scaffold), the agent is told —
in DOMAIN-NEUTRAL terms — what it must DO for the claim to be scientifically
valid, not merely plausible: verify correctness against a reference, MEASURE
(never hardcode) any normalization ceiling, emit provenance, and fill the
contract. The agent fulfils each obligation in a way appropriate to ITS domain
(a STREAM-style microbench for an HPC bandwidth ceiling; a baseline run for an ML
accuracy ceiling; an analytic check for a numerical method; ...).

This module contains NO domain knowledge — no roofline, no GFLOP, no bandwidth,
no cache. The obligation text it emits is identical across HPC / ML / theory; the
agent supplies the domain-specific fulfilment. This mirrors the enforcement side:
the harness states the obligation generally, the agent satisfies it specifically.
"""

from __future__ import annotations


def build_emission_nudge(warnings: list, steps_left: int) -> str:
    """Continuation nudge for the agent after emit_results returns contract warnings.

    Observed on a real run: the agent emitted once, the tool result carried the
    contract warnings -- and the node ended anyway (the harness force-finishes after
    the first completed job, and nothing told the agent it could continue). This text
    is injected by the loop WITH the force-finish hold, so the agent both knows what
    is missing and has the steps to act. Domain-neutral; "" when nothing to say.
    """
    if not warnings or steps_left <= 0:
        return ""
    lines = "\n".join(f"  - {str(w)}" for w in list(warnings)[:4])
    return (
        "CONTRACT FEEDBACK on your emit_results — the run-level metric contract is NOT yet satisfied:\n"
        + lines
        + f"\nYou have ~{steps_left} steps remaining. If the missing measurement(s) are feasible here, "
        "run them NOW and call emit_results again (it overwrites the previous file). Conclude only if "
        "they are infeasible in this node; unmet items will BLOCK the paper at finalize."
    )


def build_contract_obligation(contract: "dict | None") -> str:
    """Return the domain-neutral obligation text for a contract-bearing metric.

    Returns ``""`` when there is no ``metric_contract`` (the metric is not
    concept-classified, so no obligation applies — e.g. a raw throughput or a
    theory result). Callers inject the returned text into the implementing
    agent's context.
    """
    if not isinstance(contract, dict) or not contract:
        return ""
    key = str(contract.get("key") or "the primary metric")
    concept = str(contract.get("concept") or "bounded")
    invs = [str(i) for i in (contract.get("invariants") or []) if i]
    inv_clause = f" with invariant(s) [{'; '.join(invs)}]" if invs else ""
    lines = [
        f"METRIC-CORRECTNESS CONTRACT (required for a publishable claim of '{key}'):",
        f"'{key}' is a {concept} metric{inv_clause}. For the claim to be scientifically "
        "valid (not merely plausible), when you implement and run the experiment you MUST:",
        "  1. CORRECTNESS — compare your production output against an INDEPENDENT reference "
        "(a naive/known-correct implementation, an established baseline, or an analytic check) "
        "on the SAME problem sizes your headline numbers use, write the residual "
        "(e.g. max_abs_err) into your emit_results measurements (an unverified output is "
        "BLOCKED at finalize) and tag its provenance per item 3.",
        "  2. MEASURED CEILING — if the metric is normalized against a ceiling (a peak, a "
        "theoretical bound, or a baseline), MEASURE that ceiling empirically (a microbenchmark "
        "or a baseline run). NEVER hardcode a placeholder constant as the denominator.",
        "  3. PROVENANCE — pass a `provenance` map to the emit_results tool tagging each "
        'measured ceiling {"<operand>": "microbench"} (or "benchmark") and your correctness '
        'residual {"<residual>": "correctness"} (or "reference"), so the gate can confirm a '
        "measured ceiling / a correctness check was actually run rather than assumed.",
        f"  4. DECLARE — fill the metric_contract: 'formula' (how '{key}' is recomputed from "
        'the raw measured operands), \'correctness\' {"expr": "<residual> < <tol>", "requires": '
        '["<residual>"]}, and \'required_measured\' (the operand names that must be measured).',
    ]
    # F: plan-fidelity — when the idea declared falsifiable claims, the agent must
    # EMIT the named measurement(s) that make each claim evaluable, or it is blocked.
    # This is what stops a declared mechanism being claimed but never measured. The
    # names come from the idea (top-down), surfaced here so the agent emits them.
    claims = [c for c in (contract.get("claims") or []) if isinstance(c, dict)]
    if claims:
        lines.append(
            "  5. CLAIMS — your plan declares the falsifiable claim(s) below. For EACH, emit into "
            "results.json the NAMED measurement(s) that let the claim be EVALUATED, using the "
            "EXACT names listed (the gate matches names exactly — measurements under your own "
            "naming will NOT count; rename rather than invent). A claim with NO supporting "
            "measurement is BLOCKED at finalize (a positive OR a negative outcome is fine — what "
            "is mandatory is the evidence to judge it; do not claim a mechanism you did not "
            "measure):")
        for c in claims:
            ev = [str(e) for e in (c.get("required_evidence") or []) if e]
            ctext = str(c.get("claim") or "")[:140]
            lines.append(
                f"     - \"{ctext}\" -> emit measurement(s) named: [{', '.join(ev)}]" if ev
                else f"     - \"{ctext}\"")
    lines.append(
        "Choose the reference and the ceiling measurement appropriate to YOUR domain. A claim "
        "whose ceiling is a hardcoded placeholder, whose output is unverified, or that has no "
        "supporting measurement, is BLOCKED at finalize.")
    return "\n".join(lines)
