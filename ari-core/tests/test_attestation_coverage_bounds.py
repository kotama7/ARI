"""An attestation may only report on the atoms it was handed.

Only one direction was checked: every REQUESTED atom had to be covered. Nothing
compared the other way, so a driver reporting on an atom the request never
granted was accepted, and that digest went straight into the bridge's coverage
map.

That direction is load-bearing. A run request is built by filtering the
baseline's requirements down to what the LOCK says this harness covers
(``request.py``), which is precisely how an atom no manifest can satisfy stays
unsatisfiable: the resolver flags it, no locked harness claims it, no request
grants it, no attestation reports it, and the verdict aggregation reads it as
inconclusive. Every one of the six shipped drivers respects that by iterating
``request.property_atoms`` -- but they respected it by construction, not because
anything made them, and a driver added later would not have been made to.

So the invariant is stated where it can be enforced instead of being a property
six files happen to share.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ari.assurance.attestation import validate_attestation


DIGEST = "sha256:" + "7" * 64


def _atom(digest: str):
    return SimpleNamespace(atom_digest=digest)


def _call(*, requested: tuple[str, ...], reported: tuple[str, ...]) -> None:
    """Everything but the coverage comparison made to agree, so only it decides."""
    harness = SimpleNamespace(
        manifest_digest="sha256:" + "1" * 64, driver_digest="sha256:" + "2" * 64,
        oracle_digest="sha256:" + "3" * 64, dataset_digest="sha256:" + "4" * 64,
        container_digest="sha256:" + "5" * 64)
    request = SimpleNamespace(
        active_harness_lock_digest="sha256:" + "6" * 64, harness=harness,
        target_digest=DIGEST,
        property_atoms=tuple(_atom(item) for item in requested))
    attestation = SimpleNamespace(
        producer_component_id="fixed_verifier_v1", producer_prompt_hash=None,
        active_harness_lock_digest=request.active_harness_lock_digest,
        baseline_harness_lock_digest="sha256:" + "8" * 64,
        target_digest=DIGEST, harness_manifest_digest=harness.manifest_digest,
        driver_digest=harness.driver_digest, oracle_digest=harness.oracle_digest,
        dataset_digest=harness.dataset_digest,
        container_digest=harness.container_digest,
        property_results=tuple(
            SimpleNamespace(covered_atom_digests=(item,)) for item in reported))
    validate_attestation(
        attestation=attestation, request=request,
        baseline_lock=SimpleNamespace(lock_digest="sha256:" + "8" * 64),
        current_target_digest=DIGEST)


def test_reporting_exactly_the_requested_atoms_is_accepted():
    _call(requested=("atom-a", "atom-b"), reported=("atom-a", "atom-b"))


def test_reporting_fewer_than_requested_is_refused():
    """The direction that was always checked."""
    with pytest.raises(ValueError, match="does not cover every requested"):
        _call(requested=("atom-a", "atom-b"), reported=("atom-a",))


def test_reporting_an_atom_the_request_never_granted_is_refused():
    """THE DEFECT. An atom no harness can satisfy is kept unsatisfiable by never
    being granted to one; a driver free to report on it anyway could satisfy it
    from nothing."""
    with pytest.raises(ValueError, match="did not grant"):
        _call(requested=("atom-a",), reported=("atom-a", "atom-unsatisfiable"))
