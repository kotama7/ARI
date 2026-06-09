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
    return "\n".join([
        f"METRIC-CORRECTNESS CONTRACT (required for a publishable claim of '{key}'):",
        f"'{key}' is a {concept} metric{inv_clause}. For the claim to be scientifically "
        "valid (not merely plausible), when you implement and run the experiment you MUST:",
        "  1. CORRECTNESS — compare your production output against an INDEPENDENT reference "
        "(a naive/known-correct implementation, an established baseline, or an analytic check) "
        "on the SAME problem sizes your headline numbers use, and write the residual "
        "(e.g. max_abs_err) into results.json measurements.",
        "  2. MEASURED CEILING — if the metric is normalized against a ceiling (a peak, a "
        "theoretical bound, or a baseline), MEASURE that ceiling empirically (a microbenchmark "
        "or a baseline run). NEVER hardcode a placeholder constant as the denominator.",
        "  3. PROVENANCE — tag each measured ceiling in results.json with "
        '"_provenance": {"<metric_name>": "microbench"} (or "benchmark"), so the gate can '
        "confirm it was measured rather than assumed.",
        f"  4. DECLARE — fill the metric_contract: 'formula' (how '{key}' is recomputed from "
        'the raw measured operands), \'correctness\' {"expr": "<residual> < <tol>", "requires": '
        '["<residual>"]}, and \'required_measured\' (the operand names that must be measured).',
        "Choose the reference and the ceiling measurement appropriate to YOUR domain. A claim "
        "whose ceiling is a hardcoded placeholder, or whose output is unverified, is BLOCKED at "
        "finalize.",
    ])
