"""GovernanceSelfAudit — step 8 of the nine-step audit pipeline, deterministic
and kernel-backed (docs/reference/rqgm_schemas.md, "The motion-pipeline
records").

MetaMonitor-style audit of the governance components' own outputs this
epoch: auditor motion precision so far, judge consistency vs. the board
scores (clamp count), defender participation rate — plus kernel
re-validation of every record the pipeline produced in steps 3-6, so a buggy
or evolved governance component cannot smuggle a violating record into the
report (the kernel is the authority; the orchestrator's constructive checks
are an early optimization, never the guarantee).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_ROUND = 6


#: Codes the constitution treats as CONTAMINATION / critical findings for the
#: purposes of T19 (``retired -> banned``, whose contamination class is
#: prompt-injection content, audit-log tampering attribution, or repeated
#: clean-room-descendant failure traced to a lineage). A component implicated
#: by one of these is recommended for a ban; the transition engine still
#: applies T19 only where the component is actually ``retired``, so a
#: recommendation is never a sanction on its own.
CONTAMINATION_CODES: frozenset[str] = frozenset({
    "CK-AUD-001",   # audit-log append-only violation
    "CK-AUD-002",   # audit-log prefix tampering
    "CK-AUD-003",   # audit-log hash chain broken
    "CK-ACC-002",   # retired-prompt-text access
    "CK-ROL-901",   # forged registry-writer authority
})


def _ban_recommendations(escalations, findings) -> list:
    """Components implicated by a contamination/critical finding.

    This is the PRODUCER the transition engine's ``_ban_targets`` reads
    (``self_audit.ban_recommendations``). Nothing wrote that key, so T19 could
    never fire: the engine looked up an absent field on every boundary.
    """
    out: set[str] = set()
    for entry in escalations or ():
        code, _, subject = str(entry).partition(":")
        if code in CONTAMINATION_CODES and subject:
            out.add(subject)
    for f in findings or ():
        if not isinstance(f, dict):
            continue
        if str(f.get("kind", "")) in ("contamination", "clean_room_lineage_failure"):
            subject = str(f.get("component_id") or f.get("subject_ref") or "")
            if subject:
                out.add(subject)
    return sorted(out)


def run_self_audit(
    *,
    kernel,
    produced_records: list,
    motions: list,
    outcomes_by_motion: dict,
    defenses: list,
    findings: list,
    checked_components: list,
    degradations: list,
) -> dict:
    """Build the governance report's ``self_audit`` block (never raises;
    degrades into ``degradations`` instead)."""
    posted = len(motions)
    upheldish = sum(
        1
        for m in motions
        if outcomes_by_motion.get(m.record_id) in ("upheld", "partially_upheld")
    )
    substantive = sum(1 for d in defenses if not d.procedural_default)
    clamps = sum(
        1 for f in findings if f.get("kind") == "judge_clamped_by_board"
    )
    stats = {
        "auditor_motion_precision": (
            round(upheldish / posted, _ROUND) if posted else None
        ),
        "judge_board_clamp_count": clamps,
        "defender_substantive_rate": (
            round(substantive / posted, _ROUND) if posted else None
        ),
    }
    violations_found = 0
    escalations: list = []
    if kernel is None:
        degradations.append("self_audit_degraded")
    else:
        try:
            for rec in produced_records:
                for report in (
                    kernel.validate_record_schema(rec),
                    kernel.validate_role_separation(rec),
                ):
                    violations_found += len(report.violations)
                    if report.blocking:
                        escalations.extend(
                            sorted(
                                f"{v.code}:{v.subject_ref}"
                                for v in report.violations
                            )
                        )
        except Exception:
            log.warning("self-audit kernel re-validation failed",
                        exc_info=True)
            degradations.append("self_audit_degraded")
    return {
        "checked_components": sorted(set(checked_components)),
        "kernel_violations_found": violations_found,
        "findings": list(findings),
        "escalations": escalations,
        "ban_recommendations": _ban_recommendations(escalations, findings),
        "stats": stats,
    }
