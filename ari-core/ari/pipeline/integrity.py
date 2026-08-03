"""Run-integrity summary — the one place that answers "is this paper trustworthy?".

Every integrity check in the pipeline already writes a finding somewhere: the
claim-evidence gate emits typed errors, ``link_paper_claims`` records the
declarations it dropped, ``audit_node_provenance`` re-hashes artifacts,
``paper_refine`` reports sentences it INSERTED. What did not exist was any place
that read them together, so a run could ship a paper containing a fabricated
verification claim and print nothing but ``DONE`` eighteen times.

This module is a pure reader: it opens the artifacts a completed run leaves in
the checkpoint and produces one ``run_integrity.json`` plus a short console
summary. It recomputes nothing (each producer stays authoritative), asserts
nothing about severity beyond what the producers declared, and never raises —
an unreadable artifact is reported as unreadable, never as clean. Absence of a
producer's artifact is reported as ``null``, NOT as zero findings: "the check
did not run" and "the check found nothing" must not look the same.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Gate finding types that mean a claim was NOT verified (as opposed to
#: verified-and-wrong). Split out because a reader asking "how much of this
#: paper is machine-checked?" needs the unverified count, not just the errors.
_UNVERIFIED_TYPES = frozenset({
    "unknown_formula", "operand_unresolved", "claim_id_collision",
})


def _read(path: Path) -> Any:
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text())
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("run-integrity: cannot read %s: %s", path.name, exc)
        return {"_unreadable": str(exc)}


def build_integrity_report(checkpoint_dir: str | Path) -> dict:
    """Collect the run's integrity findings into one dict."""
    ckpt = Path(checkpoint_dir)
    ev = ckpt / "evaluation"
    out: dict[str, Any] = {"stage": "run_integrity", "checkpoint_dir": str(ckpt)}

    gate = _read(ev / "claim_evidence_hard_gate_final.json") or _read(
        ev / "claim_evidence_hard_gate_draft.json")
    if gate is None:
        out["claim_gate"] = None       # the gate did not run — NOT "clean"
    else:
        errs = gate.get("blocking_findings")
        if errs is None:  # historical pre-GateReportV1 checkpoints
            errs = gate.get("errors") or []
        warns = gate.get("advisory_findings")
        if warns is None:  # historical pre-GateReportV1 checkpoints
            warns = gate.get("warnings") or []
        by_type: dict[str, int] = {}
        for e in errs:
            k = str((e or {}).get("type") or "?")
            by_type[k] = by_type.get(k, 0) + 1
        metrics = gate.get("metrics") or {}
        out["claim_gate"] = {
            "status": gate.get("status"),
            "should_block": bool(gate.get("should_block", False)),
            "errors_by_type": by_type,
            "warnings": len(warns),
            "unverified_assertions": sum(
                n for t, n in by_type.items() if t in _UNVERIFIED_TYPES),
            "numeric_claim_reproducible_rate":
                metrics.get("numeric_claim_reproducible_rate"),
        }

    # Evidence-grounded SEMANTIC review (post-refine preferred): the numeric hard
    # gate is semantically blind — it re-checks anchored NUMBERS but not whether a
    # sentence overclaims. Without aggregating this, a finalized paper carrying a
    # KNOWN unresolved overclaim (status="revise", detected_overclaim_count>0)
    # read as clean at the run level. Absent (LLM unavailable) stays null, not 0.
    sem = _read(ev / "evidence_grounded_semantic_review_post_refine.json") or _read(
        ev / "evidence_grounded_semantic_review.json")
    if sem is None:
        out["semantic_review"] = None
    else:
        out["semantic_review"] = {
            "status": sem.get("status"),
            "unresolved_overclaims": sem.get("detected_overclaim_count"),
            "resolved_overclaims": sem.get("resolved_overclaim_count"),
            "phase": sem.get("phase"),
        }

    prov = _read(ckpt / "node_provenance_audit.json")
    out["artifact_provenance"] = (
        None if prov is None else (prov.get("summary") or {}))

    links = _read(ckpt / "paper_claim_links_final.json") or _read(
        ckpt / "paper_claim_links.json")
    if links is None:
        out["claim_links"] = None
    else:
        counts = links.get("counts") or {}
        out["claim_links"] = {
            "anchors": counts.get("anchors"),
            "resolved_anchors": counts.get("resolved_anchors"),
            "dropped_declarations": counts.get("dropped_declarations"),
            "suspect_declarations": counts.get("suspect_declarations"),
        }

    refine = _read(ckpt / "paper_refine.json")
    if refine is None:
        out["refine_insertions"] = None
    else:
        out["refine_insertions"] = {
            "inserted_sentences": len(refine.get("inserted_sentences") or []),
            "unrequested_process_claims":
                len(refine.get("unrequested_process_claims") or []),
            "examples": [s[:200] for s in
                         (refine.get("unrequested_process_claims") or [])[:2]],
        }

    refs = _read(ckpt / "related_refs.json")
    if refs is None:
        out["literature"] = None
    elif isinstance(refs, dict):
        out["literature"] = {
            "count": refs.get("count"),
            "s2_available": refs.get("s2_available"),
            "fallback_used": refs.get("fallback_used"),
            "rounds_used": refs.get("rounds_used"),
            "productive_rounds": refs.get("productive_rounds"),
        }

    idea = _read(ckpt / "idea.json")
    if isinstance(idea, dict):
        _gen = str(idea.get("virsci_integration_status") or "")
        # The root idea's novelty is ungrounded when no prior art reached it.
        # Two independent grounding paths exist and EITHER counts:
        #   (a) the idea-skill's own survey indexed papers (papers_analyzed>0);
        #   (b) the RQGM router's PriorArtDifferentiationGenerator fired
        #       (generator == "...prior_art"), which only happens when
        #       ``_root_survey_refs`` supplied non-empty survey_refs — else it
        #       degrades to ``cheap``. Keying novelty_grounded on (a) alone
        #       reported a false "NO prior art" concern for a run whose novelty
        #       WAS grounded via (b) (idea.json's novelty text cited the refs).
        out["ideation"] = {
            "papers_analyzed": idea.get("papers_analyzed"),
            "generator": _gen,
            "novelty_grounded": bool(idea.get("papers_analyzed"))
            or "prior_art" in _gen,
        }

    out["concerns"] = _concerns(out)
    return out


def _concerns(rep: dict) -> list[str]:
    """Human-facing lines for the things a reader must not miss."""
    c: list[str] = []
    gate = rep.get("claim_gate")
    if gate is None:
        c.append("claim-evidence gate produced NO report (not the same as clean)")
    else:
        unv = gate.get("unverified_assertions") or 0
        if unv:
            c.append(f"{unv} numeric assertion(s) were NOT verified "
                     f"({gate.get('errors_by_type')})")
        rate = gate.get("numeric_claim_reproducible_rate")
        if rate == 0.0:
            c.append("numeric_claim_reproducible_rate is 0.0 — no number in the "
                     "paper was machine-checked")
    # The numeric gate is semantically blind; the semantic review is the only
    # check for unsupported/overclaimed prose. An unresolved overclaim surviving
    # into the FINALIZED paper must surface at the run level, not just in the
    # per-stage artifact.
    sem = rep.get("semantic_review")
    if isinstance(sem, dict):
        unresolved = sem.get("unresolved_overclaims") or 0
        if unresolved:
            c.append(f"{unresolved} unresolved overclaim(s) remain in the "
                     f"finalized paper (semantic review status="
                     f"{sem.get('status')!r})")
    prov = rep.get("artifact_provenance")
    if isinstance(prov, dict):
        for bad in ("mismatch", "missing"):
            if prov.get(bad):
                c.append(f"{prov[bad]} artifact(s) {bad} vs their recorded sha256")
    ref = rep.get("refine_insertions") or {}
    if ref.get("unrequested_process_claims"):
        c.append(f"{ref['unrequested_process_claims']} inserted sentence(s) assert "
                 f"a verification/validation nobody requested")
    idea = rep.get("ideation") or {}
    if idea and not idea.get("novelty_grounded"):
        c.append("root ideation saw NO prior art — the novelty claim is the "
                 "model's own assessment of itself")
    lit = rep.get("literature") or {}
    if lit.get("fallback_used"):
        c.append("bibliography came from the keyword fallback, not the "
                 "retrieval backend")
    return c


def write_integrity_report(checkpoint_dir: str | Path) -> dict:
    """Build, persist to ``run_integrity.json``, and print the concerns."""
    try:
        rep = build_integrity_report(checkpoint_dir)
    except Exception:  # pragma: no cover - never break a completed run
        log.warning("run-integrity report failed", exc_info=True)
        return {}
    try:
        (Path(checkpoint_dir) / "run_integrity.json").write_text(
            json.dumps(rep, indent=2, ensure_ascii=False))
    except Exception as exc:  # pragma: no cover
        log.warning("run-integrity: cannot write report: %s", exc)
    concerns = rep.get("concerns") or []
    if concerns:
        print(f"[Run Integrity] {len(concerns)} concern(s):", flush=True)
        for line in concerns:
            print(f"[Run Integrity]   - {line}", flush=True)
            log.warning("run integrity: %s", line)
    else:
        print("[Run Integrity] no concerns raised by the checks that ran",
              flush=True)
    return rep
