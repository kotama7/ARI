"""Verdict model of the ConstitutionalKernel (RQGM Task 04, plan 04 §5.3).

Pure frozen dataclasses — no I/O, no LLM, no wall clock (P2). The kernel
*returns* :class:`KernelReport`; it never raises on rule violations (only on
programmer error) and never writes anything. Callers persist verdicts to the
Task 02 audit log (``rqgm_audit.jsonl``) via
:func:`kernel_report_audit_payload`.

Severity is part of the constitution: it is fixed per violation code in
``ari.rqgm.kernel_rules.SEVERITY``, never chosen by callers. In mid-epoch
contexts adapters downgrade *behavior* to warn-and-flag; the violation record
itself keeps its severity so the boundary pass can act on it (plan 04 §5.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Verdict contexts (plan 04 §5.3 plus the audit/clean-room/context-scope
#: check families of §5.4; closed vocabulary).
KERNEL_CONTEXTS: tuple[str, ...] = (
    "epoch_transition",
    "frontier_rebuild",
    "registry_write",
    "node_record",
    "capability",
    "audit_log",
    "clean_room",
    "context_scope",
)

SEVERITY_BLOCK = "block"
SEVERITY_WARN = "warn"


@dataclass(frozen=True)
class Violation:
    """One deterministic finding (plan 04 §5.3).

    ``code`` is a stable id (e.g. ``"CK-REG-001"``, never renumbered);
    ``detail`` is a deterministic message — no timestamps, no absolute paths.
    """

    code: str            # stable id, frozen once implemented
    check: str           # "validate_transition", ...
    severity: str        # "block" | "warn" (fixed per code in SEVERITY)
    subject_ref: str     # record_id / component_id / prompt_hash / line no.
    rule_id: str         # pointer into the kernel_rules / transition tables
    detail: str          # deterministic message

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "check": self.check,
            "severity": self.severity,
            "subject_ref": self.subject_ref,
            "rule_id": self.rule_id,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class KernelReport:
    """The kernel's verdict over one check invocation (plan 04 §5.3).

    ``violations`` are sorted by ``(code, subject_ref)`` at construction
    (see :func:`make_report`) so identical inputs yield byte-identical
    reports (P2 double-invocation equality).
    """

    context: str
    violations: tuple[Violation, ...] = field(default=())

    @property
    def blocking(self) -> bool:
        """True iff any violation carries block severity. Whether a blocking
        report actually vetoes a state change is the caller's context per the
        §5.5 blocking matrix (and ``enforcement: audit_only`` downgrades)."""
        return any(v.severity == SEVERITY_BLOCK for v in self.violations)

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict:
        return {
            "context": self.context,
            "blocking": self.blocking,
            "violations": [v.to_dict() for v in self.violations],
        }


def make_report(context: str, violations: list[Violation]) -> KernelReport:
    """Canonical constructor: deterministic violation order (P2)."""
    ordered = tuple(
        sorted(violations, key=lambda v: (v.code, v.subject_ref, v.detail))
    )
    return KernelReport(context=context, violations=ordered)


def merge_reports(context: str, reports: "list[KernelReport]") -> KernelReport:
    """Fold sub-check reports into one (used by composite checks)."""
    out: list[Violation] = []
    for rep in reports:
        out.extend(rep.violations)
    return make_report(context, out)


def kernel_report_audit_payload(
    report: KernelReport, constitution_hash: str
) -> dict:
    """The ``kernel_report`` audit-log entry payload (plan 04 §6): every
    verdict is replayable — context, pinned constitution, sorted findings."""
    return {
        "context": report.context,
        "constitution_hash": constitution_hash,
        "blocking": report.blocking,
        "violations": [v.to_dict() for v in report.violations],
    }
