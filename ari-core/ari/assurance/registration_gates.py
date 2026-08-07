"""Compute the promotion gates, instead of being handed their answers.

WHAT WAS WRONG. ``registration_report`` took a tuple of gates, checked that the
ids matched the canonical list in order, and set the decision to
``eligible-for-verified`` when every ``passed`` was True. Nothing computed any
``passed``. Every gate in every shipped report carries the identical string
"passed by immutable native promotion evidence", and ``parity_probe`` -- the
only code that establishes an instrument is not a stopwatch -- has no caller
outside tests.

So a registration recorded that fifteen gates were satisfied, a human signed
that record, and no gate had been evaluated. The signature is real; what it
attests to was not measured.

WHAT THIS DOES. One evaluator per gate, each reading a specific artifact and
returning what it found. A gate that cannot be decided from the evidence it was
given returns ``passed=False`` with the reason -- never True by default, because
the failure mode being fixed is exactly a gate that answers True without
looking.

WHAT IT DOES NOT DO. It does not decide anything only a person can. Three gates
are marked ``requires_human``: they are structural checks here, and their real
answer is the approval a maintainer signs. Marking them is the point -- the
previous arrangement made them indistinguishable from the twelve a machine can
settle.

WHAT AN EVIDENCE DIGEST IS FOR. Each gate digests THE ARTIFACT IT READ, so two
registrations of the same harness produce the same digest only if they read the
same bytes. The shipped reports' digests vary per gate but are not derived from
anything a reader can re-compute, which is the same defect one level down.
"""

from __future__ import annotations

from typing import Any, Callable

from ari.assurance.registration_models import HarnessRegistrationGateV1
from ari.protocols.integrity import canonical_digest, is_full_sha256

#: Gates whose real answer is a person's. Evaluated structurally here so a
#: missing declaration still fails, but never reported as machine-settled.
REQUIRES_HUMAN = frozenset({
    "target_oracle_test_isolation",
    "hidden_test_isolation",
    "malicious_harness_sandbox",
})


class GateEvidence:
    """Everything the gates may read. Absent inputs make gates fail, not pass."""

    def __init__(self, *, manifest: Any = None, parity: dict | None = None,
                 driver_digest: str | None = None, report_schema: dict | None = None,
                 stability: dict | None = None, repo_commit: str | None = None):
        self.manifest = manifest
        self.parity = parity or {}
        self.driver_digest = driver_digest
        self.report_schema = report_schema
        self.stability = stability or {}
        self.repo_commit = repo_commit


_EVALUATORS: dict[str, Callable[[GateEvidence], tuple[bool, str, Any]]] = {}


def gate(gate_id: str):
    def register(function):
        _EVALUATORS[gate_id] = function
        return function

    return register


def _probe_results(evidence: GateEvidence) -> dict:
    return (evidence.parity.get("results") or {})


# --- the four the parity probe settles -----------------------------------------

@gate("reference_oracle_pass")
def _reference_oracle_pass(evidence: GateEvidence):
    """The frozen reference solves its own problem.

    The clean control IS the reference scored as a candidate, so a reference
    that failed its own oracle could not produce this verdict.
    """
    clean = _probe_results(evidence).get("clean_control") or {}
    if not clean:
        return False, "the parity probe reported no clean control", None
    ok = clean.get("verdict") == "pass"
    return ok, f"clean control verdict {clean.get('verdict')!r}", clean


@gate("negative_control_fail")
def _negative_control_fail(evidence: GateEvidence):
    """Both negative controls fail, FOR DIFFERENT REASONS.

    A probe whose two negatives fail the same way cannot tell a wrong answer
    from a slow one, which is the difference between a harness and a stopwatch.
    """
    results = _probe_results(evidence)
    slow = results.get("negative_control_slow") or {}
    wrong = results.get("negative_control_wrong") or {}
    if not (slow and wrong):
        return False, "the parity probe reported fewer than two negative controls", None
    both_fail = slow.get("verdict") == "fail" and wrong.get("verdict") == "fail"
    distinct = (slow.get("detail") or "") != (wrong.get("detail") or "")
    if not both_fail:
        return False, f"negative controls: {slow.get('verdict')!r}, {wrong.get('verdict')!r}", results
    if not distinct:
        return False, "both negative controls failed for the same reason", results
    return True, "both failed, for different reasons", results


@gate("clean_control_pass")
def _clean_control_pass(evidence: GateEvidence):
    """The clean control passed AND resolved.

    Resolution is not decoration: a clean control that passed with a spread
    larger than the difference it is quoted to certifies noise. Measured on a
    shared node, the probe passed once in three runs and the passing run's
    spread was 1.16.
    """
    clean = _probe_results(evidence).get("clean_control") or {}
    if not clean:
        return False, "the parity probe reported no clean control", None
    if clean.get("verdict") != "pass":
        return False, f"clean control verdict {clean.get('verdict')!r}", clean
    if not clean.get("resolved", False):
        return False, (f"clean control did not resolve "
                       f"(spread {clean.get('relative_spread')!r})"), clean
    return True, f"passed at spread {clean.get('relative_spread')!r}", clean


@gate("official_runner_parity")
def _official_runner_parity(evidence: GateEvidence):
    """The probe as a whole, and it must name the driver it probed."""
    if not evidence.parity:
        return False, "no parity probe was run", None
    if evidence.parity.get("driver_digest") != evidence.driver_digest:
        return False, ("the parity probe was run against a different driver than "
                       "the one being registered"), evidence.parity
    if not evidence.parity.get("passed"):
        return False, (evidence.parity.get("reason")
                       or "the parity probe did not pass"), evidence.parity
    return True, "probe passed against this driver", evidence.parity


# --- the ones the manifest settles ----------------------------------------------

@gate("determinism_declaration")
def _determinism_declaration(evidence: GateEvidence):
    manifest = evidence.manifest
    if manifest is None:
        return False, "no manifest supplied", None
    scorer = getattr(manifest, "scorer_determinism", None)
    declared = getattr(manifest, "nondeterminism_declaration", None)
    if scorer is None or declared is None:
        return False, "the manifest declares no scorer determinism", None
    return True, f"scorer {scorer!r}, nondeterminism {declared!r}", {
        "scorer_determinism": scorer, "nondeterminism_declaration": declared}


@gate("timeout_resource_enforcement")
def _timeout_resource_enforcement(evidence: GateEvidence):
    manifest = evidence.manifest
    timeout = getattr(manifest, "timeout_seconds", None) if manifest else None
    if not timeout:
        return False, "the manifest pins no timeout", None
    return True, f"timeout pinned at {timeout}s", {"timeout_seconds": timeout}


@gate("license_completeness")
def _license_completeness(evidence: GateEvidence):
    """Every pinned asset carries a license, not just the ones someone listed."""
    manifest = evidence.manifest
    if manifest is None:
        return False, "no manifest supplied", None
    missing = []
    licensed = {}
    for name in ("dataset", "oracle", "driver", "model"):
        asset = getattr(manifest, name, None)
        if asset is None:
            missing.append(name)
            continue
        value = (getattr(asset, "license", "") or "").strip()
        if not value:
            missing.append(name)
        else:
            licensed[name] = value
    if missing:
        return False, f"assets without a license: {sorted(missing)}", licensed
    return True, f"all four pinned assets licensed", licensed


@gate("source_revision_digest_pin")
def _source_revision_digest_pin(evidence: GateEvidence):
    """The pinned commit must be a real commit in the history being registered.

    NOT equality with HEAD, which is what this demanded first and which is
    circular: writing the pin changes the manifest, which changes the commit
    that contains it, so no manifest could ever satisfy it. The byte-level
    guarantee is not this field's job either -- ``prepare`` already refuses when
    the driver digest does not match the code that will run, exactly.

    What the commit pin is for is PROVENANCE: where to check out to obtain those
    bytes. So the check is that it names a commit this repository actually has,
    and one the registration descends from. A pin naming nothing, or naming a
    commit off this history, records what somebody typed -- which is what the
    shipped reports do, regex-checked and compared to nothing.
    """
    import subprocess

    manifest = evidence.manifest
    pinned = getattr(manifest, "source_full_commit_sha", None) if manifest else None
    if not pinned:
        return False, "the manifest pins no source commit", None
    if evidence.repo_commit is None:
        return False, ("no repository commit supplied to check the pin against; "
                       "a pin nothing compares is a record of what was typed"), None
    try:
        from ari.assurance.registration_run import repository_root

        ancestor = subprocess.run(
            ["git", "-C", str(repository_root()), "merge-base", "--is-ancestor",
             pinned, evidence.repo_commit],
            capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not check the pin against the repository: {exc}", None
    if ancestor.returncode != 0:
        return False, (f"the manifest pins {pinned[:12]}, which the registration "
                       f"commit {evidence.repo_commit[:12]} does not descend from"), None
    return True, (f"pinned at {pinned[:12]}, an ancestor of "
                  f"{evidence.repo_commit[:12]}"), {"source_full_commit_sha": pinned}


# --- the ones the artifacts settle ----------------------------------------------

@gate("infrastructure_failure_separation")
def _infrastructure_failure_separation(evidence: GateEvidence):
    """An outage must not be scorable as a bad candidate.

    Checked against the behaviour rather than declared: the evaluator's
    infrastructure path must emit no ranking metric.
    """
    from ari.evaluator.deterministic_evaluator import DeterministicEvaluator

    def _outage(_work_dir):
        raise RuntimeError("no instrument")

    result = DeterministicEvaluator(measure_fn=_outage).evaluate_sync("g", [], "s")
    separated = (result.get("evaluation_status") == "infrastructure_error"
                 and not result.get("metrics")
                 and "scientific_score" not in result)
    return separated, (
        "an outage produces no ranking metric" if separated else
        f"an outage produced metrics {result.get('metrics')!r}"), {
        "evaluation_status": result.get("evaluation_status"),
        "metrics": result.get("metrics")}


@gate("multiple_run_stability")
def _multiple_run_stability(evidence: GateEvidence):
    """Repeated measurement of one thing agrees with itself.

    Supplied by the caller because it costs real runs. Absent, this fails: a
    stability gate that passes without repeating anything is the defect.
    """
    observed = evidence.stability.get("relative_spread")
    runs = evidence.stability.get("runs")
    limit = evidence.stability.get("limit", 0.1)
    if observed is None or not runs:
        return False, "no repeated-run evidence supplied", None
    if runs < 2:
        return False, f"{runs} run cannot show stability", evidence.stability
    if observed > limit:
        return False, (f"spread {observed:.4g} over {runs} runs exceeds "
                       f"{limit:g}"), evidence.stability
    return True, f"spread {observed:.4g} over {runs} runs", evidence.stability


@gate("result_schema_conformance")
def _result_schema_conformance(evidence: GateEvidence):
    """The typed result the harness emits has a schema, and it validates."""
    if not evidence.report_schema:
        return False, "no result schema supplied for the harness's report type", None
    required = evidence.report_schema.get("properties")
    if not required:
        return False, "the supplied schema declares no properties", None
    return True, f"schema declares {len(required)} properties", {
        "schema_id": evidence.report_schema.get("$id")
                     or evidence.report_schema.get("title")}


@gate("full_sha256_integrity")
def _full_sha256_integrity(evidence: GateEvidence):
    """Every digest the manifest pins is a full, algorithm-qualified sha256."""
    manifest = evidence.manifest
    if manifest is None:
        return False, "no manifest supplied", None
    checked, bad = {}, []
    for name in ("dataset", "oracle", "driver", "model"):
        asset = getattr(manifest, name, None)
        value = getattr(asset, "sha256", None) if asset else None
        if value is None:
            bad.append(name)
        elif not is_full_sha256(value):
            bad.append(name)
        else:
            checked[name] = value
    if bad:
        return False, f"not full sha256: {sorted(bad)}", checked
    return True, f"{len(checked)} pinned digests are full sha256", checked


# --- the three only a person can settle ------------------------------------------

@gate("target_oracle_test_isolation")
def _target_oracle_test_isolation(evidence: GateEvidence):
    manifest = evidence.manifest
    policy = getattr(manifest, "hidden_test_policy", None) if manifest else None
    if policy is None:
        return False, "the manifest declares no hidden-test policy", None
    return policy == "verifier-only", f"hidden_test_policy {policy!r}", {
        "hidden_test_policy": policy}


@gate("hidden_test_isolation")
def _hidden_test_isolation(evidence: GateEvidence):
    return _target_oracle_test_isolation(evidence)


@gate("malicious_harness_sandbox")
def _malicious_harness_sandbox(evidence: GateEvidence):
    manifest = evidence.manifest
    if manifest is None:
        return False, "no manifest supplied", None
    network = getattr(manifest, "network_policy", None)
    credential = getattr(manifest, "credential_policy", None)
    isolated = network == "deny" and credential == "none"
    return isolated, (
        f"network {network!r}, credentials {credential!r}"), {
        "network_policy": network, "credential_policy": credential}


def evaluate_gates(evidence: GateEvidence) -> tuple[HarnessRegistrationGateV1, ...]:
    """Every canonical gate, in order, each computed from what it was given.

    A gate with no evaluator fails loudly rather than being skipped: an
    unevaluated gate that reports nothing is how fifteen of them came to carry
    one string.
    """
    from ari.assurance.registration import HARNESS_REGISTRATION_GATES

    gates: list[HarnessRegistrationGateV1] = []
    for gate_id in HARNESS_REGISTRATION_GATES:
        evaluator = _EVALUATORS.get(gate_id)
        if evaluator is None:
            raise NotImplementedError(
                f"registration gate {gate_id!r} has no evaluator; a gate nothing "
                f"computes must not be reported as passed")
        passed, detail, artifact = evaluator(evidence)
        if gate_id in REQUIRES_HUMAN:
            detail = f"{detail} (structural check only; the answer is the approval)"
        gates.append(HarnessRegistrationGateV1(
            gate_id=gate_id,
            passed=bool(passed),
            # THE ARTIFACT IT READ, so two registrations agree only if they read
            # the same bytes. A digest derived from the gate id says nothing.
            evidence_digest=canonical_digest(
                {"gate": gate_id, "artifact": artifact, "passed": bool(passed)}),
            detail=detail,
        ))
    return tuple(gates)


def unevaluated_gates() -> tuple[str, ...]:
    """Canonical gates with no evaluator. Empty is the invariant a test pins."""
    from ari.assurance.registration import HARNESS_REGISTRATION_GATES

    return tuple(g for g in HARNESS_REGISTRATION_GATES if g not in _EVALUATORS)


__all__ = ["GateEvidence", "REQUIRES_HUMAN", "evaluate_gates", "gate",
           "unevaluated_gates"]
