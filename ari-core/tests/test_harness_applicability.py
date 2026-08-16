"""A Harness that cannot judge this artifact must not silence the ones that can.

A baseline lock is resolved for a CONTRACT; a node produces ONE artifact. So a
lock legitimately holds Harnesses this candidate cannot be handed, and the
shipped catalog is exactly that shape: three verifiers over three different
interface contracts, plus a benchmark whose target kind is different again.

Reaching for an inapplicable Harness raised ``HarnessRequestError``, and a
request error abandoned the whole TIER -- it returned ``inconclusive`` for
everything and every Harness after it went unrun. So a node could end up
carrying no evidence at all for a property something in its own lock was able
to check, and which one you lost depended on the order the lock happened to be
in.

Applicability is now decided before the Harness is reached for, from the same
comparison the validator uses, and an inapplicable one is skipped and recorded.
That is not a weakening: its atoms stay uncovered, so they read inconclusive and
the tier can be no better than that. It is the difference between finding that
out and finding nothing out.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ari.assurance.request import HarnessRequestError, harness_inapplicability
from ari.rqgm.assurance_bridge import RQGMAssuranceBridge


BUILTIN = Path(__file__).resolve().parents[1] / "config" / "harnesses" / "builtin"

PERF = "sha256:" + "a" * 64
GEMM = "sha256:" + "b" * 64


def _declaration(interface: str = "gemm-c-abi/v1"):
    return SimpleNamespace(
        target_kind="shared-library", subject_type="program", language="c",
        hardware="cpu", architecture="x86_64", dtype="float64",
        interface_contract=interface, target_digest="sha256:" + "6" * 64)


def _manifest(digest: str, ident: str, *, kinds: tuple[str, ...], interface: str):
    return SimpleNamespace(
        manifest_digest=digest, id=ident, target_kinds=kinds,
        subject_types=("program",), supported_languages=("c",),
        supported_hardware=("cpu",), supported_architectures=("x86_64",),
        supported_dtypes=("float64",), target_interface_contract=interface)


def _bridge(tmp_path: Path, *, verify):
    bridge = RQGMAssuranceBridge.__new__(RQGMAssuranceBridge)
    bridge.checkpoint_dir = tmp_path
    bridge.admission = SimpleNamespace(
        run_id="run", active_harness_lock_digest="sha256:" + "1" * 64,
        modes=SimpleNamespace(assurance="enforce"))
    bridge.contract = SimpleNamespace(contract_digest="sha256:" + "2" * 64)
    bridge.baseline = SimpleNamespace(
        lock_digest="sha256:" + "3" * 64,
        harnesses=(
            SimpleNamespace(manifest_digest=PERF, covered_atom_digests=("atom-perf",)),
            SimpleNamespace(manifest_digest=GEMM, covered_atom_digests=("atom-num",)),
        ))
    bridge.catalog = SimpleNamespace(manifests=(
        _manifest(PERF, "hpc/gemm-performance",
                  kinds=("benchmark-submission",), interface="gemm-c-abi/v1"),
        _manifest(GEMM, "hpc/gemm-correctness",
                  kinds=("shared-library",), interface="gemm-c-abi/v1")))
    bridge._verify_locked = verify
    return bridge


def _node():
    return SimpleNamespace(id="node-1", status="success", property_verdicts={},
                           attestation_refs=[], verified_target_digest="",
                           assurance_status="", assurance_tier="", frontier_class="")


REQUIRED = (
    SimpleNamespace(tier="screen", atom_digest="atom-perf",
                    property_id="performance-regression"),
    SimpleNamespace(tier="screen", atom_digest="atom-num",
                    property_id="numerical-equivalence"),
)


# --- the comparison itself -----------------------------------------------------

def test_a_matching_harness_is_applicable():
    manifest = _manifest(GEMM, "hpc/gemm-correctness",
                         kinds=("shared-library",), interface="gemm-c-abi/v1")
    assert harness_inapplicability(manifest=manifest,
                                   declaration=_declaration()) == ""


@pytest.mark.parametrize("kinds,interface,expected", [
    (("benchmark-submission",), "gemm-c-abi/v1", "target kind"),
    (("shared-library",), "spmm-csr-c-abi/v1", "target interface"),
])
def test_a_harness_for_another_target_reports_why(kinds, interface, expected):
    manifest = _manifest(GEMM, "x", kinds=kinds, interface=interface)
    assert expected in harness_inapplicability(manifest=manifest,
                                               declaration=_declaration())


def test_the_shipped_catalog_really_is_this_shape():
    """Otherwise this is a defence against nothing."""
    manifests = [yaml.safe_load(p.read_text()) for p in sorted(BUILTIN.glob("hpc_*.yaml"))]
    kinds = {tuple(m["target_kinds"]) for m in manifests}
    interfaces = {m["target_interface_contract"] for m in manifests}
    assert len(kinds) > 1, "no shipped Harness disagrees about target kind"
    assert len(interfaces) > 1, "no shipped Harness disagrees about interface"


# --- what the bridge does with it ----------------------------------------------

def test_the_applicable_harness_still_runs(tmp_path):
    """THE DEFECT: it used to be skipped along with the tier."""
    ran: list[str] = []

    def verify(node, workspace, declaration, manifest, locked, *, tier):
        ran.append(manifest.id)
        return SimpleNamespace(property_results=(SimpleNamespace(
            covered_atom_digests=("atom-num",), verdict="pass"),))

    bridge = _bridge(tmp_path, verify=verify)
    attestations, status, reason = bridge._run_tier_suite(
        _node(), None, _declaration(), REQUIRED, tier="screen")

    assert ran == ["hpc/gemm-correctness"]
    assert status == "", "an inapplicable Harness must not fail the tier"
    assert "hpc/gemm-performance" in reason and "target kind" in reason
    assert len(attestations) == 1


def test_the_skipped_harness_leaves_its_property_unverified(tmp_path):
    """FAIL-CLOSED. Skipping must not let the tier read better than inconclusive."""
    def verify(node, workspace, declaration, manifest, locked, *, tier):
        return SimpleNamespace(property_results=(SimpleNamespace(
            covered_atom_digests=("atom-num",), verdict="pass"),))

    bridge, node = _bridge(tmp_path, verify=verify), _node()
    bridge.baseline.requirements = REQUIRED
    bridge._candidate_target = lambda _n: (
        object(), _declaration(), "")

    frontier = bridge.assure(node)

    assert node.property_verdicts["numerical-equivalence"] == "pass", (
        "the Harness that could run should have produced real evidence")
    assert node.property_verdicts["performance-regression"] == "inconclusive", (
        "the property nothing could check must not read as verified")
    assert node.assurance_status == "inconclusive"
    assert frontier == "uncertified_frontier"

    summary = json.loads(
        (tmp_path / "rqgm" / "kca" / "nodes" / "node-1" / "assurance_summary.json"
         ).read_text())
    assert "hpc/gemm-performance" in summary["status_reason"], (
        "the record must say the tier covered less than the lock provides")


def test_a_request_error_that_is_not_applicability_still_stops_the_tier(tmp_path):
    """Not every request error is a harmless mismatch.

    ``candidate target changed before request minting`` means the artifact under
    test moved after it was declared. Continuing to run the remaining Harnesses
    against it would be judging something nobody declared, so the tier still
    stops -- the fix narrows what counts as inapplicable, it does not broaden
    what counts as survivable.
    """
    ran: list[str] = []

    def verify(node, workspace, declaration, manifest, locked, *, tier):
        ran.append(manifest.id)
        raise HarnessRequestError("candidate target changed before request minting")

    bridge = _bridge(tmp_path, verify=verify)
    _attestations, status, reason = bridge._run_tier_suite(
        _node(), None, _declaration(), REQUIRED, tier="screen")

    assert ran == ["hpc/gemm-correctness"], "only the applicable Harness is reached"
    assert status == "inconclusive"
    assert "candidate target changed" in reason


def test_a_skip_is_still_reported_when_a_later_harness_fails(tmp_path):
    """Accumulating the notes and emitting them only on the clean exit made the
    record WORSE than what it replaced.

    A tier that skipped one Harness and then hit an error reported the error
    alone. Abandoning the tier at the inapplicable Harness had at least recorded
    that much, so the fix had quietly lost the very thing it was for.
    """
    def verify(node, workspace, declaration, manifest, locked, *, tier):
        raise HarnessRequestError("candidate target changed before request minting")

    bridge = _bridge(tmp_path, verify=verify)
    _attestations, status, reason = bridge._run_tier_suite(
        _node(), None, _declaration(), REQUIRED, tier="screen")

    assert status == "inconclusive"
    assert "candidate target changed" in reason, "the failure must still be named"
    assert "hpc/gemm-performance" in reason, (
        "the Harness that was skipped went unrecorded because a later one failed")


def test_the_skip_note_is_bounded_and_carries_no_host_identity(tmp_path, monkeypatch):
    """It is written into a checkpoint that can leave with a reproduction
    bundle, and it interpolates a manifest id out of catalog YAML anyone may
    extend. An all-inapplicable lock of forty Harnesses produced a
    4,908-character note before this -- ten times the cap."""
    home = tmp_path / "somebody"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    bridge = _bridge(tmp_path, verify=lambda *a, **k: None)
    bridge.baseline.harnesses = tuple(
        SimpleNamespace(manifest_digest=f"sha256:{index:064d}",
                        covered_atom_digests=("atom-perf",))
        for index in range(40))
    bridge.catalog = SimpleNamespace(manifests=tuple(
        _manifest(f"sha256:{index:064d}", f"site/{home}/harness-{index}",
                  kinds=("benchmark-submission",), interface="gemm-c-abi/v1")
        for index in range(40)))

    _attestations, _status, reason = bridge._run_tier_suite(
        _node(), None, _declaration(), REQUIRED, tier="screen")

    assert len(reason) <= 480, f"the note ran to {len(reason)} characters"
    assert str(home) not in reason, "a checkpoint record must not carry host identity"


# --- the pin that decides whether a Harness can run at all ---------------------

def test_every_shipped_manifest_pins_the_driver_that_exists():
    """A registered Harness that `prepare` refuses is registered in name only.

    There was a test for this and it named the three correctness manifests one
    by one, so the performance manifest -- added later, and the only one whose
    driver changed afterwards -- was outside it. Its pin went stale when the
    placement check was added to perf.py, and it was then re-registered four
    times at 15/15 gates while `prepare` refused it with "driver bytes drifted".

    Enumerating the directory instead of the names is the point: the next
    manifest is covered without anyone remembering to add it.

    Keyed on the manifest's DRIVER REVISION, not on its kind. Kind identified a
    driver only while each kind had exactly one, and the second artifact_verifier
    driver -- problem-correctness, which verifies a candidate against a pinned
    problem's own header -- made that mapping wrong: it compared the new
    manifest's pin against the ARI-native driver's digest and failed a manifest
    that pins its own driver correctly. The revision is what `prepare` reads, so
    it is what this should read.
    """
    from ari.assurance.drivers import builtin_driver_map

    drivers = builtin_driver_map()
    expected = {revision: driver.identity()["driver_digest"]
                for revision, driver in drivers.items()}
    checked = 0
    for path in sorted(BUILTIN.glob("*.yaml")):
        manifest = yaml.safe_load(path.read_text())
        want = expected.get(manifest["driver"]["revision"])
        if want is None:
            continue
        checked += 1
        assert manifest["driver"]["sha256"] == want, (
            f"{path.name} pins a driver digest that is not the driver in this "
            f"tree; prepare refuses it and no gate notices")
    assert checked >= 4, f"only {checked} manifests were checked"


# --- a manifest must be satisfiable by something ------------------------------

def _declaration_for(problem_revision: str):
    """What ``declare_target`` would write for a shipped problem.

    Built from the production functions rather than from the ABI files. An
    earlier version of this test read ``target_kind`` straight out of
    config/harnesses/target_abis/*.yaml and concluded that two Harnesses could
    never be handed a candidate. Both halves were wrong: declare_target derives
    the kind from ``problem_target_kind``, not from those files, so it writes
    ``benchmark-submission`` for a problem whose entry point is not one of its
    family's ABI symbols -- and only ONE Harness is unreachable, for a different
    reason. Re-deriving what production computes is how a test comes to assert a
    world that no longer exists.
    """
    import platform
    from types import SimpleNamespace

    from ari.assurance.problems import load_problem
    from ari.assurance.target_abi import abi_identity, problem_target_kind

    definition = load_problem(problem_revision).definition
    abi = abi_identity(definition.family)
    kind = problem_target_kind(definition.entry_point, definition.family)
    contract = (abi.interface_contract if kind == abi.target_kind
                else f"problem:{definition.revision}")
    return SimpleNamespace(
        target_kind=kind, subject_type="program", language="c", hardware="cpu",
        architecture=platform.machine(), dtype="float64",
        interface_contract=contract, target_digest="sha256:" + "6" * 64)


def _shipped_problems() -> list[str]:
    root = Path(__file__).resolve().parents[1] / "config" / "harnesses" / "problems"
    revisions = []
    for path in sorted(root.glob("*/problem.yaml")):
        revisions.append(yaml.safe_load(path.read_text())["revision"])
    return revisions


@pytest.mark.xfail(strict=True, reason=(
    "KNOWN, UNFIXED, and narrower than it first looked. hpc/gemm-performance "
    "pins target_interface_contract 'gemm-c-abi/v1', while a declaration for the "
    "gemm problem carries 'problem:gemm-dense-fp64/v1@2026q3' -- the contract, "
    "not the kind, is what makes it unreachable. Correcting the manifest moves "
    "its digest, so it is a re-registration and a signature. strict=True: this "
    "turns red the moment it is fixed."))
def test_a_registered_harness_can_be_reached_by_some_shipped_problem():
    """A Harness no declaration can satisfy is certified and never chosen.

    Not every skip is a defect -- hpc/gemm-correctness verifies shared libraries
    and is rightly skipped for a submission -- so this asks only that SOME
    shipped problem can reach each Harness, not that every problem can.
    """
    from ari.assurance.models import HarnessManifestV1

    declarations = [(rev, _declaration_for(rev)) for rev in _shipped_problems()]
    assert declarations, "no shipped problem to declare"
    unreachable = []
    for path in sorted(BUILTIN.glob("*.yaml")):
        manifest = HarnessManifestV1.model_validate(yaml.safe_load(path.read_text()))
        # ONLY the Harnesses whose input can come from nowhere else. An
        # artifact_verifier that accepts an external target is fed by other
        # producers -- the publication E2E hands hpc/gemm-correctness a shared
        # library it built itself -- so a problem being unable to reach it says
        # nothing. A benchmark cannot accept an external target at all
        # (models.py forbids it), so a run's own declaration is its only input.
        if manifest.accepts_external_target:
            continue
        reasons = {rev: harness_inapplicability(manifest=manifest, declaration=decl)
                   for rev, decl in declarations}
        if all(reasons.values()):
            unreachable.append(f"{manifest.id}: {sorted(set(reasons.values()))}")
    assert not unreachable, (
        "no shipped problem can be handed to these Harnesses: " + "; ".join(unreachable))


@pytest.mark.xfail(strict=True, reason=(
    "KNOWN, UNFIXED. hpc/gemm-performance supports x86_64 and is registered on "
    "aarch64, so it is refused on aarch64 for the architecture and on x86_64 for "
    "the placement. The evidence says aarch64 -- that is where its clean control "
    "resolves -- so supported_architectures is the half that is wrong. strict=True."))
def test_a_registered_placement_is_one_of_the_architectures_it_supports():
    """Otherwise no host can satisfy both halves.

    ``harness_inapplicability`` requires the declaration's architecture to be in
    ``supported_architectures``, and the performance driver's ``prepare``
    requires the host to BE the registered placement. Nothing compared the two
    fields, so it was registered and signed in that state.
    """
    contradictory = []
    for path in sorted(BUILTIN.glob("*.yaml")):
        manifest = yaml.safe_load(path.read_text())
        machine = (manifest.get("registered_placement") or {}).get("machine")
        if machine and machine not in manifest["supported_architectures"]:
            contradictory.append(
                f"{manifest['id']} is registered on {machine!r} and supports "
                f"{manifest['supported_architectures']}")
    assert not contradictory, (
        "no host can satisfy both halves of these manifests: "
        + "; ".join(contradictory))
