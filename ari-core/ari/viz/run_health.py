"""Read-only derivation of terminal run health from durable artifacts.

Tree and review artifacts describe work that happened, not whether the whole
paper pipeline succeeded.  In particular, a review can exist even when the
immutable paper-build lock subsequently blocks publication.  This module is
the shared precedence rule used by both API generations so they cannot report
that terminal failure as a completed run.
"""

from __future__ import annotations

import json
from pathlib import Path


def paper_build_health(checkpoint_dir: str | Path) -> tuple[str | None, list[str]]:
    """Return a terminal status override and human-readable reasons.

    ``None`` means the build artifact is absent or finalized and the caller may
    retain its tree/process-derived status.  An unreadable build is a failure,
    never an implicit success.
    """

    path = Path(checkpoint_dir) / "paper_build.json"
    if not path.is_file():
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        return "failed", [f"paper_build.json is not valid JSON: {exc}"]
    if not isinstance(data, dict):
        return "failed", ["paper_build.json top level is not an object"]

    status = str(data.get("status") or "").strip().lower()
    raw_reasons = data.get("blocking_reasons")
    reasons = [
        str(reason)
        for reason in (raw_reasons if isinstance(raw_reasons, list) else [])
        if str(reason).strip()
    ]
    if status == "blocked":
        return "blocked", reasons or ["paper build is blocked"]
    if status == "compile-error":
        return "failed", reasons or ["paper build failed to compile"]
    if status not in {"draft", "finalized"}:
        return "failed", [f"paper_build.json has unknown status {status!r}"]
    return None, []


def run_terminal_health(checkpoint_dir: str | Path) -> tuple[str | None, list[str]]:
    """Combine the build lock with the terminal run-integrity verdict.

    A strict claim gate can stop the pipeline before ``paper_build.json`` is
    minted.  Treating the build file as the only terminal signal therefore
    still rendered that failed run as completed and left degraded reasons
    empty.  ``run_integrity.json`` is written after the driver has collected
    those failures, so it is the durable fallback for this pre-lock path.
    """

    status, reasons = paper_build_health(checkpoint_dir)
    path = Path(checkpoint_dir) / "run_integrity.json"
    if not path.is_file():
        return status, reasons
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        return status or "failed", [
            *reasons,
            f"run_integrity.json is not valid JSON: {exc}",
        ]
    if not isinstance(data, dict):
        return status or "failed", [
            *reasons,
            "run_integrity.json top level is not an object",
        ]

    terminal_failure = False
    claim_gate = data.get("claim_gate")
    if isinstance(claim_gate, dict) and (
        claim_gate.get("should_block") is True
        or str(claim_gate.get("status") or "").lower() == "failed"
    ):
        terminal_failure = True
        reasons.append("claim-evidence hard gate failed")
    ors = data.get("ors")
    if isinstance(ors, dict) and str(ors.get("status") or "").lower() == "incomplete":
        terminal_failure = True

    concerns = data.get("concerns")
    if isinstance(concerns, list):
        reasons.extend(str(item) for item in concerns if str(item).strip())

    # Preserve order while avoiding a paper-build reason repeated by the
    # integrity summary.
    reasons = list(dict.fromkeys(reasons))
    return (status or "failed" if terminal_failure else status), reasons
