"""claim_evidence_hard_gate — deterministic claim/evidence verification
(Story2Proposal Phase B: execution data fidelity).

The only blocking gate of the integration. Deterministic (no LLM). Verifies:
  - claim existence: supported_by node ids exist in tree.json and are executed;
    referenced artifacts exist.
  - numeric recompute: numeric_assertion operands (node_id, metric_path) resolve
    from results.json/tree.json; the formula re-derives a value; the
    paper-reported number matches within tolerance.
  - numeric coverage: result-claim numbers in target sections are backed by a
    numeric_assertion (uncovered numbers flagged per section policy).
  - figure existence: referenced figures are registered; sources exist.

Verification boundary: this checks transcription/derivation consistency between
the paper and the recorded results — NOT the truthfulness of the recorded
results themselves (that is ORS / external reproducibility).

``run_hard_gate`` always writes the detailed report to
``{ckpt}/evaluation/claim_evidence_hard_gate_{phase}.json`` and returns it with a
``should_block`` flag. The MCP wrapper turns ``should_block`` into a hard
pipeline failure (final + strict only) so finalize is skipped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ari.pipeline.claim_gate import contract, invariants, latex, numeric, policy as _pol, resolve
from ari.claim_gate_contract import (
    GateFindingV1,
    GateFormulaProvenanceV1,
    GateReportV1,
    parse_metric_gate_contract,
)
from ari.research_contract import canonical_digest


def _typed_finding(raw: dict[str, Any], severity: str) -> GateFindingV1:
    known = {"type", "message", "claim_id", "numeric_id", "node_id", "artifact_path"}
    finding_type = str(raw.get("type") or "gate_internal_error")
    return GateFindingV1(
        severity=severity,
        type=finding_type,
        message=str(raw.get("message") or finding_type),
        claim_id=(str(raw["claim_id"]) if raw.get("claim_id") is not None else None),
        numeric_id=(str(raw["numeric_id"]) if raw.get("numeric_id") is not None else None),
        node_id=(str(raw["node_id"]) if raw.get("node_id") is not None else None),
        artifact_path=(
            str(raw["artifact_path"]) if raw.get("artifact_path") is not None else None
        ),
        details={key: value for key, value in raw.items() if key not in known},
    )


def _flatten_numeric_assertions(science_data: dict) -> list[dict]:
    flat = science_data.get("numeric_assertions")
    if isinstance(flat, list) and flat:
        return flat
    out: list[dict] = []
    for c in science_data.get("claims", []) or []:
        if not isinstance(c, dict):
            continue
        for na in c.get("numeric_assertions", []) or []:
            if isinstance(na, dict):
                out.append({**na, "claim_id": c.get("id")})
    return out


def _manifest_fig_ids(manifest: Any) -> set:
    ids: set = set()
    if isinstance(manifest, dict):
        figs = manifest.get("figures")
        if isinstance(figs, dict):
            ids.update(str(k) for k in figs.keys())
        elif isinstance(figs, list):
            for f in figs:
                if isinstance(f, dict) and f.get("id"):
                    ids.add(str(f["id"]))
    return ids


def _span_mentions(links: list[dict], mentions: list[dict], numeric_id: str) -> list[dict]:
    """EVERY numeric mention inside the anchor's span, best-typed first.

    An anchored sentence routinely states more than one number ("the scalar
    kernel (11.2286 GB/s) and the AVX2 kernel (16.3441 GB/s)"), so "the paper's
    value for this assertion" is genuinely ambiguous. Callers need the whole
    candidate set to tell "the paper states the wrong number" (no candidate
    matches) from "the binder picked the wrong one of several correct numbers".
    """
    for l in links:
        if l.get("numeric_id") != numeric_id:
            continue
        lo, hi = (l.get("line_range") or [0, 0])[:2]
        in_range = [m for m in mentions if lo <= m.get("line", -1) <= hi]
        rc = [m for m in in_range if m.get("type") == "result_claim"]
        return rc or in_range
    return []


def _reported_mention(links: list[dict], mentions: list[dict], numeric_id: str) -> "dict | None":
    """The paper numeric mention bound to an anchor (value + unit), or None."""
    pick = _span_mentions(links, mentions, numeric_id)
    return pick[0] if pick else None


def _reported_value(links: list[dict], mentions: list[dict], numeric_id: str) -> "float | None":
    m = _reported_mention(links, mentions, numeric_id)
    return m.get("value") if m else None


def run_hard_gate(
    checkpoint_dir: "str | Path",
    *,
    paper_tex: str,
    science_data: dict,
    paper_claim_links: "dict | None" = None,
    figures_manifest: Any = None,
    policy: "dict | None" = None,
    phase: str = "draft",
    write: bool = True,
) -> dict:
    ckpt = Path(checkpoint_dir)
    # Always merge with built-in defaults (a caller-supplied partial dict like
    # {"mode": "strict"} must still inherit target_sections / block_on).
    pol = _pol.load_policy(ckpt, policy)
    pmode = _pol.mode(pol)
    tsecs = _pol.target_sections(pol)
    strict_secs = set(tsecs.get("strict", []) or [])
    warn_secs = set(tsecs.get("warn", []) or [])
    excluded_secs = set(tsecs.get("excluded", []) or [])
    default_tol = _pol.default_tolerance(pol)
    cmp_scope = _pol.comparison_scope(pol)
    block_types = _pol.block_on(pol)
    if pmode == "strict":
        block_types = block_types | {"uncovered_numeric"}
    # Cross-environment comparisons are a transparency WARNING by default; only
    # the injected "same_environment" intent (single-architecture studies) makes
    # them blocking. Cross-architecture studies (scope="any") keep them as
    # warnings so the intended cross-host comparison is not blocked.
    if cmp_scope == "same_environment":
        block_types = block_types | {"environment_mismatch"}

    science_data = science_data or {}
    canonical_metric_contract = None
    raw_metric_contract = science_data.get("metric_contract")
    strict_evidence = bool(
        isinstance(raw_metric_contract, dict)
        and raw_metric_contract.get("schema_version")
        == "ari.metric-gate-contract/v1"
    )
    if strict_evidence:
        canonical_metric_contract = parse_metric_gate_contract(raw_metric_contract)
        science_data = dict(science_data)
        science_data["metric_contract"] = canonical_metric_contract.gate_projection()
    tree = resolve.load_tree(ckpt)
    node_by_id = resolve.index_nodes(tree)
    claims = science_data.get("claims", []) or []
    flat_nas = _flatten_numeric_assertions(science_data)
    # Story2Proposal (c): the writer's INLINE forward declarations (parsed by
    # link_paper_claims into writer_assertions) are verified exactly like the
    # generated assertions — recompute from results.json and compare to the
    # paper-reported number. This is FORWARD (declared operands/formula), never a
    # reverse search, so a wrong declaration surfaces as numeric_mismatch.
    _writer_nas = (paper_claim_links or {}).get("writer_assertions", []) or []
    _by_id = {na.get("id"): na for na in flat_nas if isinstance(na, dict)}
    _seen_na_ids = set(_by_id)
    writer_declared = 0
    # The paper writer and the science_data generator mint C<N>/NC<N> ids
    # INDEPENDENTLY, so the same id can name two unrelated assertions. The
    # writer's declaration used to be dropped on collision and the pre-generated
    # one silently kept — then the paper's number (belonging to the writer's
    # subject) was compared against the OTHER assertion's recomputation. Observed
    # live: the paper's C1/NC1 described cfg1 (11.2286 GB/s, a true value) while
    # science_data's C1/NC1 described a different node (16.3441), producing a
    # numeric_mismatch against a correct paper. Collisions on a DIFFERENT metric
    # are recorded here and skipped below instead of being "verified" as wrong.
    _colliding_ids: dict[str, dict] = {}
    for _wa in _writer_nas:
        if not isinstance(_wa, dict):
            continue
        _wid = _wa.get("id")
        if _wid not in _seen_na_ids:
            flat_nas.append(_wa)
            _seen_na_ids.add(_wid)
            writer_declared += 1
            continue
        _existing = _by_id.get(_wid) or {}
        _wm = str(_wa.get("metric") or "")
        _em = str(_existing.get("metric") or "")
        if _wm and _em and _wm != _em:
            _colliding_ids[str(_wid)] = {
                "paper_subject": f"metric {_wm}",
                "pre_generated_subject": f"metric {_em}",
            }

    # An anchor whose declaration was DROPPED (no inline formula=) still names
    # its subject. When the paper says the id is about config X and the
    # pre-generated assertion of the same id resolves to a different node, they
    # are two assertions sharing an id — the same-metric/different-node shape
    # that reported a correct 11.2286 as "not reproducible (recomputed 16.3441)".
    for _dd in (paper_claim_links or {}).get("dropped_declarations", []) or []:
        if not isinstance(_dd, dict):
            continue
        _did = str(_dd.get("numeric_id") or "")
        _pre = _by_id.get(_did)
        if not _did or not isinstance(_pre, dict) or _did in _colliding_ids:
            continue
        # The subject is (metric, node). A collision on EITHER axis means the two
        # assertions describe different quantities: same metric on a different
        # node, or a different metric on the same node.
        _dm = str(_dd.get("declared_metric") or "")
        _pm = str(_pre.get("metric") or "")
        if _dm and _pm and _dm != _pm:
            _colliding_ids[_did] = {
                "paper_subject": f"metric {_dm!r}",
                "pre_generated_subject": f"metric {_pm!r}",
            }
            continue
        _declared_nodes = {n for n in (_dd.get("declared_node_ids") or []) if n}
        _pre_nodes = {
            str((op or {}).get("node_id") or "")
            for op in (_pre.get("operands") or {}).values()
            if isinstance(op, dict)
        } - {""}
        if _declared_nodes and _pre_nodes and not (_declared_nodes & _pre_nodes):
            _colliding_ids[_did] = {
                "paper_subject": f"config {sorted(_dd.get('declared_config_ids') or [])} "
                                 f"-> node {sorted(_declared_nodes)}",
                "pre_generated_subject": f"node {sorted(_pre_nodes)}",
            }

    links = (paper_claim_links or {}).get("paper_claim_links", []) or []
    mentions = (paper_claim_links or {}).get("numeric_mentions")
    if mentions is None:
        mentions = latex.extract_numeric_mentions(paper_tex or "")
    unresolved_anchors = (paper_claim_links or {}).get("unresolved_anchors", []) or []

    errors: list[dict] = []
    warnings: list[dict] = []
    evidence_document_digests: set[str] = set()
    conversions_used: set[str] = set()
    formulas_used: set[str] = set()

    # ── claim existence ──────────────────────────────────────────────────
    grounded_claims = 0
    for c in claims:
        if not isinstance(c, dict):
            continue
        cid = c.get("id", "?")
        sb = c.get("supported_by", {}) or {}
        ok = True
        for nid in sb.get("nodes", []) or []:
            if not resolve.node_exists(node_by_id, nid):
                errors.append({"claim_id": cid, "type": "missing_evidence",
                               "message": f"claim {cid} references unknown node '{nid}'"})
                ok = False
            elif not resolve.node_executed(node_by_id, nid):
                target = errors if strict_evidence else warnings
                target.append({"claim_id": cid, "node_id": str(nid),
                               "type": "node_not_executed",
                               "message": f"claim {cid} node '{nid}' has no real data"})
                ok = False
        for op in sb.get("results", []) or []:
            if not isinstance(op, dict):
                errors.append({"claim_id": cid, "type": "result_unresolved",
                               "message": f"claim {cid} has a malformed result reference"})
                ok = False
                continue
            if (
                strict_evidence and op.get("run_id") != ckpt.name
            ) or (
                not strict_evidence and op.get("run_id") not in (None, ckpt.name)
            ):
                errors.append({"claim_id": cid, "type": "cross_run_evidence",
                               "node_id": str(op.get("node_id") or ""),
                               "message": f"claim {cid} result belongs to another run"})
                ok = False
                continue
            resolved = resolve.resolve_operand_evidence(
                ckpt, node_by_id, op.get("node_id", ""),
                op.get("metric_path", ""), strict=strict_evidence,
            )
            if resolved.document_digest:
                evidence_document_digests.add(resolved.document_digest)
            if resolved.value is None:
                target = errors if strict_evidence else warnings
                finding_type = (
                    resolved.error
                    if strict_evidence and resolved.error in {
                        "artifact_digest_mismatch", "artifact_missing",
                        "artifact_not_bound", "cross_run_or_unknown_node",
                        "invalid_measurement_contract",
                    }
                    else "result_unresolved"
                )
                target.append({"claim_id": cid, "type": finding_type,
                               "node_id": str(op.get("node_id") or ""),
                               "message": f"claim {cid} result did not resolve: "
                                          f"{resolved.error or 'not found'}",
                               "reason": resolved.error})
                ok = False
        for art in sb.get("artifacts", []) or []:
            verified, reason = resolve.verify_artifact(
                ckpt, art, strict=strict_evidence
            )
            if not verified:
                target = errors if strict_evidence else warnings
                finding_type = (
                    reason if reason in {
                        "cross_run_artifact", "artifact_digest_mismatch",
                        "artifact_reference_untyped", "invalid_artifact_reference",
                    } else "artifact_missing"
                )
                target.append({"claim_id": cid, "type": finding_type,
                               "artifact_path": str(art),
                               "message": f"claim {cid} artifact failed verification: {reason}"})
                ok = False
        if c.get("status") == "supported" and not (sb.get("nodes") or sb.get("results")):
            errors.append({"claim_id": cid, "type": "missing_evidence",
                           "message": f"supported claim {cid} has no supporting evidence"})
            ok = False
        if ok and (sb.get("nodes") or sb.get("results")):
            grounded_claims += 1

    # ── numeric recompute ────────────────────────────────────────────────
    reproducible = 0
    numeric_total = 0
    mismatch_count = 0
    # Values that were VERIFIED (paper number reproduced from executed data, within
    # tolerance), with their unit. A later restatement of the SAME value (e.g. the
    # headline number repeated in abstract/conclusion) is then credited as covered
    # without re-anchoring — sound because it propagates an EXISTING verified value
    # (exact match + unit), never searches for a derivation (no laundering).
    verified_values: list = []
    for na in flat_nas:
        if not isinstance(na, dict):
            continue
        numeric_total += 1
        nid = na.get("id", "?")
        cid = na.get("claim_id", "?")
        formula = na.get("formula", "")
        formulas_used.add(str(formula))
        operands = na.get("operands", {}) or {}
        tol = na.get("tolerance") or default_tol
        if nid in _colliding_ids:
            # Two independently-minted assertions share this id and describe
            # DIFFERENT metrics, so the paper's number and the recomputation
            # below belong to different subjects. Comparing them cannot verify
            # anything; asserting a mismatch would accuse a correct paper.
            _col = _colliding_ids[nid]
            errors.append({
                "claim_id": cid, "numeric_id": nid, "type": "claim_id_collision",
                "message": (
                    f"{nid} is declared twice by independent minters: the paper's "
                    f"anchor is about {_col['paper_subject']} while the "
                    f"pre-generated assertion is about "
                    f"{_col['pre_generated_subject']}; NOT verified (comparing "
                    f"them would test unrelated quantities)"
                ),
                "paper_subject": _col["paper_subject"],
                "pre_generated_subject": _col["pre_generated_subject"],
            })
            continue
        roles = numeric.required_roles(formula)
        if not roles:
            # An unknown formula NAME is a vocabulary error, not a data error.
            # It used to fall into `operand_unresolved` below and print
            # "operand 'formula' ({}) did not resolve" — where `{}` is just
            # `operands.get(None, {})` — so an operator chased missing operands
            # while the real cause was a token the registry never contained.
            # (Observed: the writer emitted `percent_change` for all 7
            # assertions; every one silently left verification, dropping
            # numeric_reproducible from 9/12 to 0/9 with no error naming why.)
            errors.append({
                "claim_id": cid, "numeric_id": nid, "type": "unknown_formula",
                "message": (
                    f"{nid} formula {formula!r} is not in the closed vocabulary "
                    f"{sorted(numeric.FORMULAS)}; the assertion cannot be "
                    f"recomputed and was NOT verified"
                ),
            })
            continue
        values: dict[str, float] = {}
        operand_units: dict[str, str] = {}
        unresolved_role = None
        unresolved_reason = None
        for role in roles:
            op = operands.get(role, {}) or {}
            if not isinstance(op, dict):
                unresolved_role = role
                unresolved_reason = "malformed_operand"
                break
            if (
                strict_evidence and op.get("run_id") != ckpt.name
            ) or (
                not strict_evidence and op.get("run_id") not in (None, ckpt.name)
            ):
                unresolved_role = role
                unresolved_reason = "cross_run_evidence"
                break
            resolved = resolve.resolve_operand_evidence(
                ckpt, node_by_id, op.get("node_id", ""),
                op.get("metric_path", ""), strict=strict_evidence,
            )
            if resolved.document_digest:
                evidence_document_digests.add(resolved.document_digest)
            if resolved.value is None:
                unresolved_role = role
                unresolved_reason = resolved.error
                break
            if strict_evidence and not resolved.unit:
                unresolved_role = role
                unresolved_reason = "measurement_unit_missing"
                break
            values[role] = resolved.value
            operand_units[role] = resolved.unit or ""
        if unresolved_role is not None or not roles:
            finding_type = (
                unresolved_reason
                if strict_evidence and unresolved_reason in {
                    "artifact_digest_mismatch", "artifact_missing",
                    "artifact_not_bound", "cross_run_evidence",
                    "cross_run_or_unknown_node", "invalid_measurement_contract",
                }
                else "operand_unresolved"
            )
            errors.append({"claim_id": cid, "numeric_id": nid, "type": finding_type,
                           "message": f"{nid} operand '{unresolved_role or 'formula'}' "
                                      f"did not resolve: {unresolved_reason or 'unknown formula'}",
                           "reason": unresolved_reason})
            continue

        declared_unit = str(na.get("unit") or "")
        if strict_evidence and not declared_unit and canonical_metric_contract is not None:
            declared_unit = canonical_metric_contract.metric_contract.unit
        if strict_evidence and not declared_unit:
            errors.append({"claim_id": cid, "numeric_id": nid,
                           "type": "unit_unresolved",
                           "message": f"{nid} has no declared output unit"})
            continue
        if "baseline" in roles and "proposed" in roles:
            converted, provenance = numeric.convert_value(
                values["proposed"], operand_units["proposed"], operand_units["baseline"]
            )
            if converted is None:
                errors.append({"claim_id": cid, "numeric_id": nid,
                               "type": "unit_mismatch",
                               "message": f"{nid} operands use incompatible units "
                                          f"{operand_units['baseline']!r} and "
                                          f"{operand_units['proposed']!r}"})
                continue
            values["proposed"] = converted
            if provenance:
                conversions_used.add(provenance)
        elif strict_evidence and roles == ("value",):
            converted, provenance = numeric.convert_value(
                values["value"], operand_units["value"], declared_unit
            )
            if converted is None:
                errors.append({"claim_id": cid, "numeric_id": nid,
                               "type": "unit_mismatch",
                               "message": f"{nid} operand unit "
                                          f"{operand_units['value']!r} cannot convert "
                                          f"to {declared_unit!r}"})
                continue
            values["value"] = converted
            if provenance:
                conversions_used.add(provenance)
        recomputed = numeric.recompute(formula, values)
        if recomputed is None:
            errors.append({"claim_id": cid, "numeric_id": nid, "type": "operand_unresolved",
                           "message": f"{nid} formula '{formula}' is undefined for the resolved operands"})
            continue
        # Operand scalars are resolved from executed data, so they are grounded
        # quantities: a baseline/reference number stated in prose (and used here
        # only as an operand) is covered by its exact value (unit absolute). Sound
        # — propagates a real data value, never searches for a derivation.
        for role, operand_value in values.items():
            verified_values.append((operand_value, operand_units.get(role, "")))
        # same-environment check for comparison formulas. Severity is intent-
        # driven: a transparency WARNING by default ("any"), a blocking ERROR
        # only under "same_environment" intent (single-architecture studies).
        if "baseline" in roles and "proposed" in roles:
            b_env = resolve.env_signature(
                ckpt, operands.get("baseline", {}).get("node_id", ""),
                strict=strict_evidence,
            )
            p_env = resolve.env_signature(
                ckpt, operands.get("proposed", {}).get("node_id", ""),
                strict=strict_evidence,
            )
            if b_env.get("_unreadable") or p_env.get("_unreadable"):
                # A node report that EXISTS but could not be read cannot confirm
                # the environments match. Previously it collapsed to the empty
                # signature and the guard below short-circuited, silencing a real
                # cross-machine comparison. Surface it — blocking under
                # same_environment intent, a warning otherwise.
                _envfind = {"claim_id": cid, "numeric_id": nid,
                            "type": "environment_unverified",
                            "message": (f"{nid} environment could not be verified "
                                        f"(unreadable node report: "
                                        f"{b_env.get('_unreadable') or p_env.get('_unreadable')})")}
                (errors if cmp_scope == "same_environment" else warnings).append(_envfind)
            elif b_env.get("cpu_model") and p_env.get("cpu_model") and b_env != p_env:
                _envfind = {"claim_id": cid, "numeric_id": nid, "type": "environment_mismatch",
                            "message": f"{nid} baseline/proposed differ in environment "
                                       f"({b_env} vs {p_env})"}
                (errors if cmp_scope == "same_environment" else warnings).append(_envfind)
        _rm = _reported_mention(links, mentions, nid)
        reported = _rm.get("value") if _rm else None
        if reported is not None:
            reported_unit = str((_rm or {}).get("unit") or "")
            comparable = float(reported)
            if strict_evidence:
                comparable, conversion = numeric.convert_value(
                    comparable, reported_unit, declared_unit
                )
                if comparable is None:
                    errors.append({"claim_id": cid, "numeric_id": nid,
                                   "type": "unit_mismatch",
                                   "message": f"{nid} paper unit {reported_unit!r} "
                                              f"cannot convert to {declared_unit!r}"})
                    continue
                if conversion:
                    conversions_used.add(conversion)
            if numeric.within_tolerance(comparable, recomputed, tol):
                reproducible += 1
                verified_values.append((reported, reported_unit))
            else:
                # Before accusing the paper, check whether ANOTHER number in the
                # same anchored sentence reproduces. A sentence stating two
                # measured values ("the scalar kernel (11.2286 GB/s) and the AVX2
                # kernel (16.3441 GB/s)") binds to whichever comes first, so a
                # correct paper was reported as "11.2286 not reproducible
                # (recomputed 16.3441)" — while 16.3441 sat in the same sentence.
                # That false accusation is what reaches the refiner as an
                # imperative to change a correct number.
                _alts: list[tuple[dict, float]] = []
                for candidate in _span_mentions(links, mentions, nid):
                    if candidate is _rm:
                        continue
                    try:
                        candidate_value = float(candidate.get("value"))
                    except (TypeError, ValueError):
                        continue
                    candidate_comparable = candidate_value
                    if strict_evidence:
                        candidate_comparable, candidate_conversion = numeric.convert_value(
                            candidate_value,
                            str(candidate.get("unit") or ""),
                            declared_unit,
                        )
                        if candidate_comparable is None:
                            continue
                        if candidate_conversion:
                            conversions_used.add(candidate_conversion)
                    if numeric.within_tolerance(
                        candidate_comparable, recomputed, tol
                    ):
                        _alts.append((candidate, candidate_comparable))
                if _alts:
                    matching_mention, matching_comparable = _alts[0]
                    warnings.append({
                        "claim_id": cid, "numeric_id": nid, "type": "ambiguous_span",
                        "message": (
                            f"{nid}: the anchored sentence states several numbers; the "
                            f"bound one ({reported}) does not reproduce but "
                            f"{matching_mention.get('value')} in the SAME sentence does "
                            f"(recomputed {round(recomputed, 6)}). Anchor the claim to "
                            f"the intended number rather than treating this as a "
                            f"wrong value."
                        ),
                        "reported": reported, "recomputed": round(recomputed, 6),
                        "reported_in_contract_unit": comparable,
                        "matching_alternative": matching_mention.get("value"),
                        "matching_alternative_in_contract_unit": matching_comparable,
                    })
                else:
                    mismatch_count += 1
                    errors.append({"claim_id": cid, "numeric_id": nid, "type": "numeric_mismatch",
                                   "message": f"{nid}: paper value {reported} not reproducible from "
                                              f"results.json (recomputed {round(recomputed, 6)})",
                                   "reported": reported,
                                   "reported_in_contract_unit": comparable,
                                   "recomputed": round(recomputed, 6),
                                   "formula": formula, "tolerance": tol})
        else:
            # no paper-linked number to compare; verify internal consistency only
            declared = na.get("value")
            if declared is not None and not numeric.within_tolerance(float(declared), recomputed, tol):
                warnings.append({"claim_id": cid, "numeric_id": nid, "type": "declared_value_drift",
                                 "message": f"{nid} declared value {declared} differs from recompute "
                                            f"{round(recomputed, 6)}"})
            else:
                reproducible += 1
            if links:
                warnings.append({"claim_id": cid, "numeric_id": nid, "type": "no_paper_anchor",
                                 "message": f"{nid} has no % CLAIM anchor linked in the paper"})

    # ── numeric coverage ─────────────────────────────────────────────────
    linked_lines: set = set()
    for l in links:
        if l.get("resolved"):
            lo, hi = (l.get("line_range") or [0, 0])[:2]
            for ln in range(lo, hi + 1):
                linked_lines.add(ln)
    covered = 0
    targeted_result_claims = 0
    uncovered_count = 0
    for m in mentions:
        if m.get("type") != "result_claim" or not m.get("requires_assertion"):
            continue
        sec = m.get("section", "body")
        if sec in excluded_secs:
            continue
        in_strict = sec in strict_secs
        in_warn = sec in warn_secs
        if not (in_strict or in_warn):
            continue
        targeted_result_claims += 1
        if m.get("line") in linked_lines:
            covered += 1
            continue
        # Restatement of an already-VERIFIED value (exact value + same unit): the
        # headline number repeated in abstract/conclusion is the same grounded
        # claim. Exact match only (no tolerance window) + unit match => no
        # laundering (we propagate a verified value, never search a derivation).
        _mv, _mu = m.get("value"), m.get("unit", "")
        if _mv is not None and any(_mv == vv and _mu == vu for vv, vu in verified_values):
            covered += 1
            continue
        uncovered_count += 1
        finding = {"type": "uncovered_numeric", "section": sec, "value": m.get("value"),
                   "line": m.get("line"), "classified_as": "result_claim",
                   "message": f"numeric '{m.get('value')}{m.get('unit', '')}' in {sec} "
                              f"maps to no numeric_assertion"}
        if in_strict and pmode == "strict":
            errors.append(finding)
        else:
            warnings.append(finding)

    # ── figure existence ─────────────────────────────────────────────────
    fig_ids = _manifest_fig_ids(figures_manifest)
    referenced_fig_ids: list[str] = (paper_claim_links or {}).get("figure_refs", []) or []
    for l in links:
        for fid in l.get("figures", []) or []:
            if fig_ids and fid not in fig_ids:
                warnings.append({"claim_id": l.get("claim_id"), "type": "figure_unregistered",
                                 "message": f"claim {l.get('claim_id')} references figure '{fid}' "
                                            f"not in figures_manifest"})
    # figure source existence + unreferenced figures
    if isinstance(figures_manifest, dict):
        figs = figures_manifest.get("figures")
        if isinstance(figs, dict):
            for fid, fpath in figs.items():
                if fpath and not resolve.artifact_exists(ckpt, str(fpath)) and not Path(str(fpath)).exists():
                    warnings.append({"type": "figure_source_missing",
                                     "message": f"figure '{fid}' source '{fpath}' not found"})
            if referenced_fig_ids:
                for fid in figs:
                    if str(fid) not in referenced_fig_ids:
                        warnings.append({"type": "figure_unreferenced",
                                         "message": f"figure '{fid}' is not referenced in the paper"})

    for ua in unresolved_anchors:
        warnings.append({"type": "unresolved_anchor",
                         "message": f"anchor {ua.get('anchor')} references unknown id",
                         **{k: ua[k] for k in ("claim_id", "numeric_id", "line") if k in ua}})

    # ── universal metric invariants (concept->invariant registry) ────────
    # Deterministic and domain-general: flags physically-impossible metric values
    # (e.g. a normalized metric > 1) in the configurations that feed the paper.
    # Pure math — no roofline/HPC knowledge. See invariants.py.
    invariant_violations = invariants.scan_science_data(science_data)
    errors.extend(invariant_violations)

    # ── declared metric_contract enforcement (correctness / provenance /
    # declared invariants / regime / owned recompute). Domain-general: evaluates
    # only DECLARED expressions over measured metrics. No-op for legacy runs that
    # carry no metric_contract. See contract.py.
    contract_violations = contract.check_contract(science_data)
    errors.extend(contract_violations)

    status = "failed" if errors else ("warn" if warnings else "passed")
    always_block = _pol.always_block_on(pol)
    should_block = (
        phase == "final" and pmode != "off" and (
            (pmode == "strict" and any(e.get("type") in block_types for e in errors))
            # Objective-falsehood findings block at final regardless of warn/strict.
            or any(e.get("type") in always_block for e in errors)
        )
    )

    gate_metrics = {
            "total_claims": len(claims),
            "grounded_claims": grounded_claims,
            "execution_grounded_claim_rate": (grounded_claims / len(claims)) if claims else 0.0,
            "numeric_assertions_total": numeric_total,
            "writer_declared_assertions": writer_declared,
            "numeric_reproducible": reproducible,
            "numeric_claim_reproducible_rate": (reproducible / numeric_total) if numeric_total else 0.0,
            "numeric_claim_mismatch_count": mismatch_count,
            "targeted_result_claims": targeted_result_claims,
            "numeric_coverage_rate": (covered / targeted_result_claims) if targeted_result_claims else 1.0,
            "uncovered_numeric_count": uncovered_count,
            "invariant_violation_count": len(invariant_violations),
            "contract_violation_count": len(contract_violations),
    }

    metric_contract_digest = (
        canonical_metric_contract.metric_contract.contract_digest
        if canonical_metric_contract is not None
        else None
    )
    evidence_digest = canonical_digest(
        {
            "source_run_id": ckpt.name,
            "tree": tree,
            "science_data": science_data,
            "paper_digest": canonical_digest(paper_tex or ""),
            "paper_claim_links": paper_claim_links or {},
            "figures_manifest": figures_manifest,
            "measurement_documents": sorted(evidence_document_digests),
        }
    )
    report_model = GateReportV1.create(
        source_run_id=ckpt.name,
        phase=phase,
        policy_mode=pmode,
        comparison_scope=cmp_scope,
        status=status,
        should_block=should_block,
        policy_digest=canonical_digest(pol),
        evidence_digest=evidence_digest,
        formula_provenance=GateFormulaProvenanceV1(
            registry_digest=numeric.formula_registry_digest(),
            formulas_used=tuple(sorted(formulas_used)),
            metric_contract_digest=metric_contract_digest,
            unit_conversions=tuple(sorted(conversions_used)),
        ),
        blocking_findings=tuple(_typed_finding(item, "blocking") for item in errors),
        advisory_findings=tuple(_typed_finding(item, "advisory") for item in warnings),
        metrics=gate_metrics,
    )
    report = report_model.model_dump(mode="json")

    if write:
        from ari.execution import WorkspaceRefV1

        workspace = WorkspaceRefV1(root=str(ckpt.expanduser().resolve()))
        workspace.atomic_write_bytes(
            f"evaluation/claim_evidence_hard_gate_{phase}.json",
            (
                json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n"
            ).encode("utf-8"),
        )
    return report
