"""The correctness families ARI ships, and what stopped being written out.

The set of verifiable kernels used to appear in FIVE places: a ``Literal``, the
facade's dispatch dict, the parity probe's reference table, the ABI dispatch
dict, and two argparse ``choices`` tuples. Adding one meant finding all five,
and a family added to four of them was dispatchable, scored and attested while
the probe never touched it -- and the probe would still have reported ``passed``.

Each family declares itself once now. This does NOT make families free the way
pinned problems are: adding one is still an ARI change, because an oracle a
caller could supply is an oracle a caller could weaken.
"""

from __future__ import annotations

import pytest

from ari.assurance.drivers.shared_library import abi_adapter_kinds
from ari.assurance.native_hpc import native_reference, registered_native_families
from ari.assurance.native_hpc_family import (
    NativeFamilyError, get_native_family, register_native_family)


def test_a_family_supplies_all_three_of_its_parts():
    """Cases-and-oracle, the independent reference, and the ABI its candidates
    are called through. A family missing one is dispatchable until the moment
    the missing part is needed."""
    for kind in registered_native_families():
        family = get_native_family(kind)
        assert family.name == kind
        for part in ("verify", "reference", "call_shared_library"):
            assert callable(getattr(family, part, None)), f"{kind} has no {part}"


def test_the_abi_adapters_and_the_verifiers_describe_the_same_set():
    """They are registered in different modules, so nothing but this makes them
    agree. A kind with an oracle and no adapter cannot be run against a real
    library; one with an adapter and no oracle would be run and never judged."""
    assert set(abi_adapter_kinds()) == set(registered_native_families())


def test_re_registering_a_family_name_is_refused():
    class Impostor:
        name = "gemm"

    with pytest.raises(NativeFamilyError, match="already registered"):
        register_native_family(Impostor())


def test_an_unknown_kind_is_refused_and_says_what_exists():
    with pytest.raises(NativeFamilyError, match="unsupported native Harness kind"):
        get_native_family("no-such-kernel")


def test_the_parity_probe_covers_every_registered_family():
    """The probe's list was the one that decided what got certified."""
    import inspect

    from ari.assurance.drivers import native

    source = inspect.getsource(native.NativeHPCDriver.parity_probe)
    assert "registered_native_families()" in source
    for kind in registered_native_families():
        assert f'"{kind}"' not in source, (
            f"the probe names {kind} instead of asking the registry")


def test_the_registry_is_inside_the_driver_digest():
    """It decides WHICH ORACLE judges a run, so a change to it must move the
    digest a manifest pins -- otherwise the judging oracle could be swapped
    under an attestation that still verified."""
    from pathlib import Path

    from ari.assurance.drivers.native import native_driver_digest

    before = native_driver_digest()
    path = (Path(__file__).resolve().parents[1] / "ari" / "assurance"
            / "native_hpc_family.py")
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n# drift\n")
        assert native_driver_digest() != before
    finally:
        path.write_bytes(original)
    assert native_driver_digest() == before


def test_a_deleted_verifier_file_fails_loudly_rather_than_leaving_the_digest():
    from pathlib import Path

    from ari.assurance.drivers.native import native_driver_digest

    path = (Path(__file__).resolve().parents[1] / "ari" / "assurance"
            / "native_hpc_family.py")
    original = path.read_bytes()
    try:
        path.unlink()
        with pytest.raises(FileNotFoundError, match="native_hpc_family.py"):
            native_driver_digest()
    finally:
        path.write_bytes(original)


def test_the_registered_harnesses_now_refuse_until_they_are_re_registered():
    """THE COST OF THIS CHANGE, asserted rather than described.

    The three correctness harnesses carry human-maintainer approvals over
    manifests that pin the driver digest. Changing the driver changes that
    digest, so every one of them now REFUSES to run. That is the registration
    system working: the pins were not quietly rewritten to match, because a
    signature covers what was signed and re-pinning would have made the
    attestation describe code nobody approved.
    """
    import pathlib

    import yaml

    from ari.assurance.drivers.native import NativeHPCDriver, native_driver_digest

    class _Asset:
        def __init__(self, revision, sha256):
            self.revision, self.sha256 = revision, sha256

    class _Manifest:
        kind = "artifact_verifier"
        accepts_external_target = True
        network_policy = "deny"
        credential_policy = "none"

        def __init__(self, sha256):
            self.driver = _Asset("ari.assurance.native-hpc/v1", sha256)

    root = pathlib.Path(__file__).resolve().parents[1] / "config" / "harnesses" / "builtin"
    for name in ("gemm", "spmm", "stencil"):
        manifest = yaml.safe_load((root / f"hpc_{name}_correctness.yaml").read_text())
        pinned = manifest["driver"]["sha256"]
        assert pinned != native_driver_digest(), (
            f"hpc_{name}_correctness was re-pinned; a signature covers what was "
            f"signed, and re-pinning makes the attestation describe code nobody "
            f"approved")
        with pytest.raises(ValueError, match="driver bytes drifted"):
            NativeHPCDriver().prepare(_Manifest(pinned), None)
