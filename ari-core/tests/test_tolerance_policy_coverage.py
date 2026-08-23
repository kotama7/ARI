"""A governed run must be able to state the tolerance a Harness actually pins.

The regression: `build_verification_contract` stamped every correctness
requirement with the digest of the Research Contract's own {absolute, relative}
pair, while a Harness pins the sha256 of a symbolic policy FILE. `resolver`
compares those two digests for equality, so coverage resolved to nothing
whatever numbers the contract carried -- and the failure surfaced far away, as
`unsatisfied Harness coverage`.
"""
from pathlib import Path

import pytest
import yaml

from ari.assurance.contract import load_tolerance_policy

POLICIES = Path(__file__).resolve().parents[1] / "config" / "harnesses" / "policies"
BUILTIN = Path(__file__).resolve().parents[1] / "config" / "harnesses" / "builtin"


def test_policy_digest_is_over_the_file_bytes():
    path = POLICIES / "hpc-floating-point-v1.yaml"
    ref, digest = load_tolerance_policy(path)
    assert ref == "hpc-floating-point/v1"
    import hashlib
    assert digest == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_resolved_digest_equals_what_the_shipped_harness_pins():
    _ref, digest = load_tolerance_policy(POLICIES / "hpc-floating-point-v1.yaml")
    manifest = yaml.safe_load((BUILTIN / "hpc_gemm_correctness.yaml").read_text())
    pinned = {p["tolerance_policy_digest"] for p in manifest["properties"]}
    assert pinned == {digest}, (
        "the correctness Harness pins a tolerance policy the run cannot name; "
        "coverage compares these for equality"
    )


def test_a_policy_without_an_id_is_refused(tmp_path):
    bad = tmp_path / "nameless.yaml"
    bad.write_text("comparison: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="declares no id"):
        load_tolerance_policy(bad)
