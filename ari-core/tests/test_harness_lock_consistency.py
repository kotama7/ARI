"""A lock cannot say an atom is beyond every harness and also covered by one.

The resolver builds those two sets as complements: an atom is "unsatisfied" when
NO compatible manifest covers it, so it appears in no coverage record. Everything
downstream leans on that. A verdict for an unsatisfied atom is only ever
``inconclusive`` because no locked harness claims it, so no run request grants
it, so no attestation reports it, so it never reaches the coverage map the
verdict is aggregated from.

That was a property of how the sets happen to be BUILT, asserted nowhere. Mint
copies both straight from the suite without comparing them, and
``coverage_proof_digest`` is computed over the lock's own claims so it cannot
notice them disagreeing. A suite and a lock making both claims at once were
accepted, digest and all.

It used to not matter much, because the bridge re-asserted it at use time: any
unsatisfied required atom short-circuited the whole tier to ``inconclusive``
before a harness ran. That short-circuit is gone -- deliberately, so the
harnesses that CAN run produce evidence -- and with it went the only place the
invariant was checked between the resolver's construction and the verdict. So it
is checked here, where it is declared.
"""

from __future__ import annotations

import pytest

from ari.assurance.models import (
    BaselineHarnessLockV1,
    HarnessCoverageV1,
    HarnessSuiteV1,
    LockedHarnessV1,
)


D = {name: "sha256:" + char * 64 for name, char in
     (("a", "a"), ("b", "b"), ("c", "c"), ("d", "d"), ("e", "e"), ("f", "f"))}

ATOM_ONE = "sha256:" + "1" * 64
ATOM_TWO = "sha256:" + "2" * 64


def _suite(*, covered: tuple[str, ...], unsatisfied: tuple[str, ...]):
    return HarnessSuiteV1.create(
        requirements=(),
        harness_manifest_digests=(D["a"],),
        coverage=(HarnessCoverageV1(harness_manifest_digest=D["a"],
                                    covered_atom_digests=covered),),
        covered_atom_digests=covered,
        unsatisfied_atom_digests=unsatisfied,
        aggregate_resource_cost=(0, 0, 0, 0),
        verification_environment_digest=D["b"],
        resolver_objective=(),
    )


def _lock(*, covered: tuple[str, ...], unsatisfied: tuple[str, ...]):
    return BaselineHarnessLockV1.create(
        run_id="run",
        research_contract_digest=D["a"],
        verification_contract_digest=D["b"],
        harness_catalog_snapshot_digest=D["c"],
        verification_environment_digest=D["d"],
        oracle_bundle_digest=D["e"],
        suite_digest=D["f"],
        requirements=(),
        unsatisfied_atom_digests=unsatisfied,
        harnesses=(LockedHarnessV1(
            harness_id="hpc/example", version="1.0.0", kind="artifact_verifier",
            manifest_digest=D["a"], dataset_digest=D["b"], oracle_digest=D["c"],
            driver_digest=D["d"], container_digest=D["e"],
            result_schema_digest=D["f"], tolerance_policy_digest=D["a"],
            covered_atom_digests=covered),),
        coverage_proof_digest=D["b"],
    )


def test_a_suite_with_disjoint_sets_is_accepted():
    suite = _suite(covered=(ATOM_ONE,), unsatisfied=(ATOM_TWO,))
    assert suite.unsatisfied_atom_digests == (ATOM_TWO,)


def test_a_suite_claiming_an_atom_both_ways_is_refused():
    with pytest.raises(ValueError, match="both unsatisfied and covered"):
        _suite(covered=(ATOM_ONE,), unsatisfied=(ATOM_ONE,))


def test_a_lock_with_disjoint_sets_is_accepted():
    lock = _lock(covered=(ATOM_ONE,), unsatisfied=(ATOM_TWO,))
    assert lock.unsatisfied_atom_digests == (ATOM_TWO,)


def test_a_lock_claiming_an_atom_both_ways_is_refused():
    """The one point between the resolver and the verdict where it is visible."""
    with pytest.raises(ValueError, match="both unsatisfied and covered"):
        _lock(covered=(ATOM_ONE,), unsatisfied=(ATOM_ONE,))


def test_the_shipped_production_lock_still_validates():
    """The invariant has to describe the locks this repository actually mints."""
    import json
    from pathlib import Path

    path = (Path(__file__).resolve().parents[1] / "config" / "harnesses"
            / "evidence" / "production_e2e" / "baseline_harness_lock.json")
    BaselineHarnessLockV1.model_validate_json(path.read_text(encoding="utf-8"))
