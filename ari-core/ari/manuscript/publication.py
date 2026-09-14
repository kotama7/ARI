"""Independent, fail-closed publication decision assembly."""

from __future__ import annotations

from ari.manuscript.contracts import (
    ManuscriptAuthoringBindingV1,
    ManuscriptReadinessReportV1,
    PublicationDecisionV1,
    PublicationSubVerdictV1,
)


def _sub(gate: str, passed: bool | None, artifacts=(), reasons=()):
    return PublicationSubVerdictV1(
        gate=gate,
        status="not_required" if passed is None else "pass" if passed else "fail",
        artifact_digests=tuple(artifacts),
        reason_codes=tuple(reasons if not passed and passed is not None else ()),
    )


def build_publication_decision(
    *,
    run_id: str,
    attempt_id: str,
    paper_build_digest: str,
    binding: ManuscriptAuthoringBindingV1,
    readiness: ManuscriptReadinessReportV1,
    claim_gate_passed: bool,
    claim_gate_digest: str,
    assurance_required: bool,
    assurance_passed: bool | None,
    assurance_artifact_digests: tuple[str, ...] = (),
    compile_passed: bool,
    compile_digest: str,
    reproduction_passed: bool,
    reproduction_digest: str,
    inputs_fresh: bool,
) -> PublicationDecisionV1:
    if binding.run_id != run_id or readiness.run_id != run_id:
        raise ValueError("publication artifacts belong to another run")
    if binding.readiness_digest != readiness.readiness_digest:
        raise ValueError("publication binding names another readiness report")
    manuscript_passed = readiness.publication_verdict == "ready"
    if assurance_required and assurance_passed is None:
        assurance_passed = False
    subverdicts = (
        _sub("manuscript_readiness", manuscript_passed, (readiness.readiness_digest,), ("manuscript_not_publication_ready",)),
        _sub("claim_evidence", claim_gate_passed, (claim_gate_digest,), ("final_claim_gate_failed",)),
        _sub(
            "assurance",
            assurance_passed if assurance_required else None,
            assurance_artifact_digests,
            ("required_certification_missing_or_failed",),
        ),
        _sub("build_compile", compile_passed, (compile_digest,), ("paper_compile_failed",)),
        _sub("reproduction", reproduction_passed, (reproduction_digest,), ("paper_reproduction_failed",)),
        _sub("freshness", inputs_fresh, (), ("publication_input_stale",)),
    )
    decision = "publishable" if all(item.status != "fail" for item in subverdicts) else "blocked"
    return PublicationDecisionV1.create(
        run_id=run_id,
        attempt_id=attempt_id,
        paper_build_digest=paper_build_digest,
        authoring_binding_digest=binding.binding_digest,
        readiness_digest=readiness.readiness_digest,
        subverdicts=subverdicts,
        decision=decision,
    )


__all__ = ["build_publication_decision"]
