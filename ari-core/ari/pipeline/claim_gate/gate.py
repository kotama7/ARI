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

from ari.pipeline.claim_gate import latex, numeric, policy as _pol, resolve


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


def _reported_mention(links: list[dict], mentions: list[dict], numeric_id: str) -> "dict | None":
    """The paper numeric mention bound to an anchor (value + unit), or None."""
    for l in links:
        if l.get("numeric_id") != numeric_id:
            continue
        lo, hi = (l.get("line_range") or [0, 0])[:2]
        in_range = [m for m in mentions if lo <= m.get("line", -1) <= hi]
        rc = [m for m in in_range if m.get("type") == "result_claim"]
        pick = rc or in_range
        if pick:
            return pick[0]
    return None


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
    _seen_na_ids = {na.get("id") for na in flat_nas if isinstance(na, dict)}
    writer_declared = 0
    for _wa in _writer_nas:
        if isinstance(_wa, dict) and _wa.get("id") not in _seen_na_ids:
            flat_nas.append(_wa)
            _seen_na_ids.add(_wa.get("id"))
            writer_declared += 1

    links = (paper_claim_links or {}).get("paper_claim_links", []) or []
    mentions = (paper_claim_links or {}).get("numeric_mentions")
    if mentions is None:
        mentions = latex.extract_numeric_mentions(paper_tex or "")
    unresolved_anchors = (paper_claim_links or {}).get("unresolved_anchors", []) or []

    errors: list[dict] = []
    warnings: list[dict] = []

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
                warnings.append({"claim_id": cid, "type": "node_not_executed",
                                 "message": f"claim {cid} node '{nid}' has no real data"})
                ok = False
        for op in sb.get("results", []) or []:
            val, _src = resolve.resolve_operand(ckpt, node_by_id, op.get("node_id", ""), op.get("metric_path", ""))
            if val is None:
                warnings.append({"claim_id": cid, "type": "result_unresolved",
                                 "message": f"claim {cid} result {op} did not resolve"})
                ok = False
        for art in sb.get("artifacts", []) or []:
            if not resolve.artifact_exists(ckpt, art):
                warnings.append({"claim_id": cid, "type": "artifact_missing",
                                 "message": f"claim {cid} artifact '{art}' not found"})
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
        operands = na.get("operands", {}) or {}
        tol = na.get("tolerance") or default_tol
        roles = numeric.required_roles(formula)
        values: dict[str, float] = {}
        unresolved_role = None
        for role in roles:
            op = operands.get(role, {}) or {}
            v, _src = resolve.resolve_operand(ckpt, node_by_id, op.get("node_id", ""), op.get("metric_path", ""))
            if v is None:
                unresolved_role = role
                break
            values[role] = v
        if unresolved_role is not None or not roles:
            errors.append({"claim_id": cid, "numeric_id": nid, "type": "operand_unresolved",
                           "message": f"{nid} operand '{unresolved_role or 'formula'}' "
                                      f"({operands.get(unresolved_role, {})}) did not resolve"})
            continue
        recomputed = numeric.recompute(formula, values)
        if recomputed is None:
            errors.append({"claim_id": cid, "numeric_id": nid, "type": "operand_unresolved",
                           "message": f"{nid} formula '{formula}' is undefined for the resolved operands"})
            continue
        # Operand scalars are resolved from executed data, so they are grounded
        # quantities: a baseline/reference number stated in prose (and used here
        # only as an operand) is covered by its exact value (unit absolute). Sound
        # — propagates a real data value, never searches for a derivation.
        for _ov in values.values():
            verified_values.append((_ov, ""))
        # same-environment check for comparison formulas. Severity is intent-
        # driven: a transparency WARNING by default ("any"), a blocking ERROR
        # only under "same_environment" intent (single-architecture studies).
        if "baseline" in roles and "proposed" in roles:
            b_env = resolve.env_signature(ckpt, operands.get("baseline", {}).get("node_id", ""))
            p_env = resolve.env_signature(ckpt, operands.get("proposed", {}).get("node_id", ""))
            if b_env.get("cpu_model") and p_env.get("cpu_model") and b_env != p_env:
                _envfind = {"claim_id": cid, "numeric_id": nid, "type": "environment_mismatch",
                            "message": f"{nid} baseline/proposed differ in environment "
                                       f"({b_env} vs {p_env})"}
                (errors if cmp_scope == "same_environment" else warnings).append(_envfind)
        _rm = _reported_mention(links, mentions, nid)
        reported = _rm.get("value") if _rm else None
        if reported is not None:
            if numeric.within_tolerance(reported, recomputed, tol):
                reproducible += 1
                verified_values.append((reported, (_rm or {}).get("unit", "")))
            else:
                mismatch_count += 1
                errors.append({"claim_id": cid, "numeric_id": nid, "type": "numeric_mismatch",
                               "message": f"{nid}: paper value {reported} not reproducible from "
                                          f"results.json (recomputed {round(recomputed, 6)})",
                               "reported": reported, "recomputed": round(recomputed, 6),
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

    status = "failed" if errors else ("warn" if warnings else "passed")
    should_block = (phase == "final" and pmode == "strict"
                    and any(e.get("type") in block_types for e in errors))

    report = {
        "gate": "claim_evidence_hard_gate",
        "phase": phase,
        "policy": pmode,
        "comparison_scope": cmp_scope,
        "status": status,
        "should_block": should_block,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
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
        },
    }

    if write:
        try:
            out_dir = ckpt / "evaluation"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"claim_evidence_hard_gate_{phase}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2)
            )
        except Exception as e:  # pragma: no cover - defensive
            report.setdefault("_write_error", str(e))
    return report
