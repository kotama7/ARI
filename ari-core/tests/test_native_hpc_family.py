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


def test_the_registered_harnesses_pin_the_driver_that_exists():
    """THE COST OF THE FAMILY MIGRATION, now paid.

    Changing the driver changed its digest, and the three correctness harnesses
    pinned the old one -- so every one of them was REFUSED by prepare. Their
    manifests were not quietly re-pinned at the time: a signature covers what
    was signed, and re-pinning alone would have made three attestations describe
    code nobody approved.

    They were re-registered instead, from evidence: three parity-probe runs per
    harness, 15/15 gates, and a fresh approval. This asserts the repaired state
    -- the pins match the driver that exists, so prepare no longer refuses.
    """
    import pathlib

    import yaml

    from ari.assurance.drivers.native import native_driver_digest

    root = pathlib.Path(__file__).resolve().parents[1] / "config" / "harnesses" / "builtin"
    current = native_driver_digest()
    for name in ("gemm", "spmm", "stencil"):
        manifest = yaml.safe_load((root / f"hpc_{name}_correctness.yaml").read_text())
        assert manifest["driver"]["sha256"] == current, (
            f"hpc_{name}_correctness pins a driver digest that is not the driver "
            f"in this tree; prepare will refuse it")


def test_target_abi_registry_agrees_with_correctness_harnesses():
    """The declaration and verifier must meet at an independently stated ABI.

    The registry is deliberately not derived from these manifests.  Comparing
    the two here catches a renamed contract or dtype before every governed run
    is rejected as incompatible.
    """
    import pathlib

    import yaml

    from ari.assurance.target_abi import abi_identity, target_abi_root

    manifests_root = (
        pathlib.Path(__file__).resolve().parents[1]
        / "config" / "harnesses" / "builtin"
    )
    manifests = [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(manifests_root.glob("*.yaml"))
    ]
    identity_files = sorted(target_abi_root().glob("*.yaml"))
    assert identity_files, "the target ABI registry must not be vacuous"
    for path in identity_files:
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        family = record["family"]
        identity = abi_identity(family)
        assert identity is not None
        compatible = [
            manifest for manifest in manifests
            if manifest.get("accepts_external_target")
            and family in manifest.get("supported_domains", ())
        ]
        assert len(compatible) == 1, (
            f"{family!r} must resolve to one external-target correctness Harness"
        )
        manifest = compatible[0]
        assert identity.interface_contract == manifest["target_interface_contract"]
        assert identity.dtype in manifest["supported_dtypes"]
        assert identity.language in manifest["supported_languages"]
        assert identity.subject_type in manifest["subject_types"]
        assert identity.target_kind in manifest["target_kinds"]
