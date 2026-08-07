"""Run the evidence a registration is made of, instead of being told it.

WHAT WAS MISSING. ``registration_gates`` can compute every gate, but only from
evidence someone hands it, and nothing in production produced any. In
particular ``parity_probe`` -- the one piece of code that establishes an
instrument can tell a wrong answer from a slow one -- had no caller outside
tests. So the gates could be computed and never were, which is a shorter
distance from "the gates are decorative" than it looks.

This module is that caller. It runs the probe against the driver being
registered, repeats it enough times to say something about stability, reads the
commit out of the repository rather than accepting one, resolves the result
schema from the report type the harness actually emits, and hands the result to
``registration_report``.

WHAT IT REFUSES. A dirty working tree, because a pin taken from uncommitted code
names a commit that does not describe what ran. A probe run against a different
driver. A stability claim from fewer than two runs. None of these are policy
choices: each is a way the evidence would be about something other than the
thing being registered.

WHAT IT COSTS. The probe compiles and runs the reference, a slow control and a
wrong control, once per repetition. That is the price of a registration meaning
something, and it is why nothing did this by accident.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ari.assurance.registration import registration_report
from ari.assurance.registration_gates import GateEvidence


class RegistrationEvidenceError(RuntimeError):
    """The evidence could not be produced, so no registration can be minted."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def repository_commit(*, allow_dirty: bool = False) -> str:
    """HEAD, and only if the tree is clean.

    A registration pins ``source_full_commit_sha``. Taken while files are
    modified, that pin names a commit whose bytes are not the bytes that were
    measured -- which is how a shipped report came to pin a commit that is not
    the one it describes and to be regex-checked only.
    """
    root = repository_root()
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RegistrationEvidenceError(f"could not read the repository: {exc}") from exc
    if head.returncode != 0:
        raise RegistrationEvidenceError(
            f"could not resolve HEAD: {head.stderr.strip()[-200:]}")
    dirty = [line for line in status.stdout.splitlines() if line.strip()]
    if dirty and not allow_dirty:
        raise RegistrationEvidenceError(
            f"the working tree has {len(dirty)} modified path(s); a source pin "
            f"taken here would name a commit whose bytes are not the bytes that "
            f"were measured. Commit first, or pass allow_dirty for a dry run.")
    return head.stdout.strip()


def result_schema_for(schema_version: str) -> dict | None:
    """The JSON schema for the typed result a harness emits, if ARI ships one.

    Returns None rather than raising: a missing schema is a finding the gate
    reports, not an error that hides it.
    """
    stem = (schema_version.replace("ari.", "").replace("/", "_")
            .replace("-", "_").replace(".", "_"))
    root = repository_root() / "ari-core" / "ari" / "schemas"
    for candidate in (root / f"{stem}.schema.json",
                      root / f"{stem}_schema.json"):
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return None


def _clean_control_speedup(probe: dict) -> float | None:
    value = ((probe.get("results") or {}).get("clean_control") or {}).get(
        "median_speedup")
    return float(value) if isinstance(value, (int, float)) else None


def probe_repeatedly(driver: Any, manifest: Any, *, runs: int = 3) -> tuple[dict, dict]:
    """Run the parity probe ``runs`` times; return the last probe and the spread.

    The stability gate needs repeated measurement of ONE thing, and the clean
    control is that thing: the frozen reference scored as a candidate, which
    should read the same on every run. Its spread across runs is the honest
    answer to "does this instrument repeat", and it costs nothing extra because
    the probe has to run anyway.
    """
    if runs < 2:
        raise RegistrationEvidenceError(
            f"{runs} probe run cannot show stability; a stability gate that "
            f"passes without repeating anything is the defect being fixed")
    probes: list[dict] = []
    for _ in range(runs):
        probes.append(driver.parity_probe(manifest))
    observed = [value for value in map(_clean_control_speedup, probes)
                if value is not None and value > 0]
    stability: dict[str, Any] = {"runs": len(observed)}
    if len(observed) >= 2:
        centre = sorted(observed)[len(observed) // 2]
        stability["relative_spread"] = ((max(observed) - min(observed)) / centre
                                        if centre else None)
        stability["clean_control_speedups"] = observed
    # The LAST probe is reported, not the best: picking the one that passed
    # would make the record describe a run chosen for its answer.
    return probes[-1], stability


def gather_evidence(manifest: Any, driver: Any, *, runs: int = 3,
                    allow_dirty: bool = False) -> GateEvidence:
    """Everything the gates read, produced rather than asserted."""
    identity = driver.identity() or {}
    driver_digest = identity.get("driver_digest")
    if not driver_digest:
        raise RegistrationEvidenceError(
            "the driver reports no digest, so nothing can say which driver was "
            "probed")
    probe, stability = probe_repeatedly(driver, manifest, runs=runs)
    return GateEvidence(
        manifest=manifest,
        parity=probe,
        driver_digest=driver_digest,
        report_schema=result_schema_for(getattr(driver, "report_schema_version", "")),
        stability=stability,
        repo_commit=repository_commit(allow_dirty=allow_dirty),
    )


def register_harness(manifest: Any, driver: Any, *, runs: int = 3,
                     allow_dirty: bool = False):
    """Evaluate a harness for promotion, from evidence this call produced.

    The report it returns is NOT an approval. It records what the gates found;
    a maintainer's signature over it is a separate act, and the three gates only
    a person can settle say so in their own detail.
    """
    evidence = gather_evidence(manifest, driver, runs=runs, allow_dirty=allow_dirty)
    return registration_report(
        harness_id=manifest.id,
        manifest_digest=manifest.manifest_digest,
        evidence=evidence,
    )


__all__ = [
    "RegistrationEvidenceError",
    "gather_evidence",
    "probe_repeatedly",
    "register_harness",
    "repository_commit",
    "repository_root",
    "result_schema_for",
]
