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


def collect_run_measurement_names(checkpoint_dir: str) -> set:
    """Union of measurement names emitted SO FAR by any node of this run.

    Names only — no values, no conclusions — so sibling-branch fault containment is
    preserved; this is run-level COORDINATION metadata (like the contract itself),
    used to tell a new node which declared claims still lack evidence anywhere in
    the run. Reads experiments/<run_id>/node_*/results*.json next to the checkpoint
    (same layout the transform's provenance union uses). Best-effort: {} on any miss.
    """
    names: set = set()
    try:
        from pathlib import Path
        import json as _json
        ckpt = Path(checkpoint_dir).expanduser().resolve()
        workspace = ckpt.parent.parent if ckpt.parent.name == "checkpoints" else ckpt.parent
        exp = workspace / "experiments" / ckpt.name

        # Align the steering view with the GATE's view: the gate unions evidence
        # only over nodes with has_real_data, so coverage must not count a node the
        # evaluator judged broken/dataless — otherwise a faulty branch's mere
        # measurement NAMES would tell siblings "already covered", suppressing the
        # independent re-measurement that branch fault-containment exists to keep.
        # Unknown/absent tree.json (root, early run) -> no filter (count all),
        # which errs toward optimism only before any evaluation exists.
        eligible: "set | None" = None
        tree = ckpt / "tree.json"
        if tree.is_file():
            try:
                tnodes = (_json.loads(tree.read_text()) or {}).get("nodes") or []
                ids = {str(n.get("id")) for n in tnodes if isinstance(n, dict)}
                if ids:
                    eligible = {str(n.get("id")) for n in tnodes
                                if isinstance(n, dict) and n.get("has_real_data")}
            except Exception:
                eligible = None

        if exp.is_dir():
            for p in exp.glob("node_*/results*.json"):
                if eligible is not None and p.parent.name not in eligible:
                    continue
                try:
                    d = _json.loads(p.read_text())
                except Exception:
                    continue
                m = d.get("measurements")
                if isinstance(m, dict):
                    names.update(k for k in m.keys() if isinstance(k, str))
    except Exception:
        pass
    return names


def build_coverage_status(contract: "dict | None", covered_names: set) -> str:
    """Run-level claim-coverage block appended to the per-node obligation.

    Without this, every node saw the SAME 12 claims with no idea what siblings had
    already evidenced — and a real 10-node run produced 10 variations of the headline
    experiment while the declared mechanism claims got zero dedicated experiments
    (nothing in the tree's search rewards or even mentions uncovered claims). Tells
    the node which claims are already covered run-wide and asks it to PRIORITIZE one
    or two still-uncovered ones it can feasibly measure. ``""`` when no claims.
    """
    if not isinstance(contract, dict):
        return ""
    claims = [c for c in (contract.get("claims") or []) if isinstance(c, dict)]
    if not claims:
        return ""
    cov = covered_names or set()
    covered, uncovered = [], []
    for c in claims:
        req = [n for n in (c.get("required_evidence") or []) if isinstance(n, str) and n.strip()]
        # STEERING uses a MAJORITY rule (>= half the names present), stricter than
        # the gate's R1 any-name rule: R1 exists to avoid over-BLOCKING, but for
        # steering an accidentally-shared single name (e.g. a generic token) would
        # mark a claim "covered" and stop any node from ever running its experiment.
        # Erring uncovered here only costs a possibly-redundant measurement.
        hits = sum(1 for n in req if n in cov)
        (covered if (req and hits >= max(1, (len(req) + 1) // 2)) else uncovered).append(c)
    lines = [
        f"RUN-LEVEL CLAIM COVERAGE (across all nodes so far): {len(covered)}/{len(claims)} covered."
    ]
    if uncovered:
        lines.append(
            "STILL UNCOVERED — pick ONE or TWO you can feasibly measure IN THIS NODE and design "
            "your experiment to produce their evidence (EXACT names; a negative result is fine):")
        for c in uncovered[:6]:
            ev = [str(e) for e in (c.get("required_evidence") or []) if e][:4]
            lines.append(f"  - \"{str(c.get('claim') or '')[:90]}\" -> [{', '.join(ev)}]")
        if len(uncovered) > 6:
            lines.append(f"  (+{len(uncovered) - 6} more uncovered)")
    else:
        lines.append("All declared claims have at least one supporting measurement somewhere in the run.")
    return "\n".join(lines)


def build_expand_coverage_hint(checkpoint_dir: str) -> str:
    """Coverage hint appended to the EXPANSION-SELECTION goal text (P3).

    The expansion selector already sees every branch's score/metrics/summary (it is
    inherently a cross-branch scheduler), but nothing told it which declared claims
    remain unevidenced -- so it optimized the headline metric and a real 10-node run
    produced ten variations of the same experiment. This appends the run-level
    coverage block (gate-aligned, majority-rule) so "covers a still-uncovered claim"
    can inform WHICH node to expand. ``""`` when no contract / no claims / error,
    so legacy behaviour is untouched.
    """
    try:
        from pathlib import Path
        import json as _json
        p = Path(checkpoint_dir) / "metric_contract.json"
        if not p.is_file():
            return ""
        mc = _json.loads(p.read_text())
        if not isinstance(mc, dict) or not (mc.get("claims") or []):
            return ""
        st = build_coverage_status(mc, collect_run_measurement_names(str(checkpoint_dir)))
        if not st:
            return ""
        return (
            "\n\n[Run-level claim coverage — prefer expanding a node whose next "
            "experiment can evidence a STILL-UNCOVERED claim]\n" + st)
    except Exception:
        return ""


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
