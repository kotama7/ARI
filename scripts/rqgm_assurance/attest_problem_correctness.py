#!/usr/bin/env python3
"""Earn a problem-correctness Harness's attestations by RUNNING its controls.

THE DEFECT THIS REPAIRS. Five catalog rows carry ``status: verified``. Three of
them -- the ARI-native correctness families -- ship four ``HarnessAttestationV1``
artifacts each, plus ``logs/`` and ``resource_measurements.json``, produced by
``promote_native_harnesses.py``'s four-execution control sequence. The other two
ship none, because they were registered through ``repin_and_promote_harness.py``,
which writes ``clean_control_verdict="pass"`` and ``negative_control_verdict=
"fail"`` into ``registration_evidence.json`` as LITERALS and points
``attestation_digests`` at its own registration report. Nothing ran; the record
says something did.

The gap is structural, not an oversight: ``promote_native_harnesses.py``'s
``KIND_CONFIG`` names exactly the three native families, and its control loop is
welded to a manifest it also CONSTRUCTS, to a ``.so`` it compiles itself, and to
a contract that demands a ``reproducibility`` property this manifest does not
declare. This module is that loop, taken off those three assumptions.

WHY A NEW SCRIPT RATHER THAN A ``KIND_CONFIG`` ENTRY. Four things differ, and
each of them is load-bearing rather than cosmetic:

* The manifest is READ, not built. ``hpc_gemm_problem_correctness.yaml`` is
  already registered and signed. A promotion surface that reconstructed it from
  constants here would be free to move what it asserts -- which is the objection
  ``repin_and_promote_harness``'s docstring already makes about placement.
* The candidate is C SOURCE copied verbatim, not a shared library. Nothing is
  compiled on this side of the container wall; ``verify_problem_correctness``
  builds it INSIDE, against the problem's own frozen driver and header.
* The contract must be built from the properties this manifest declares -- two,
  not three. ``promote_native_harnesses._contract`` requires
  ``reproducibility @ certify`` and stamps ``target_kind: shared-library`` and
  ``dtype: (float32, float64)``; against this manifest that leaves atoms
  unsatisfied and ``resolve_harness_suite`` refuses.
* The sequence needs a FIFTH run. See ``CONTROLS``.

Also, plainly: ``promote_native_harnesses._immutable_outputs`` raises for any
existing artifact whose bytes change, and this harness already has a manifest, a
report, an approval and an evidence bundle on disk. It cannot move them.

WHAT IS REUSED, AND THEREFORE NOT REIMPLEMENTED HERE. The verifier
(``FixedVerifier``), the substrate (``PinnedContainerExecutor``), the driver
(``ProblemCorrectnessDriver``), the request minting (``build_native_harness_run_
request``, which already carries a worker argv branch for this driver), the
oracle (``verify_problem_correctness``, reached only through the container), the
interface control's transform (``_EXTRA_SYMBOL``, the driver's own), and the
gates (``register_harness``). This file contributes a control sequence and the
checks that decide whether it discriminated -- nothing else.

WHAT IT WILL NOT DO.

* It never DECLARES a control outcome. Every verdict written by this module is
  read back off a ``HarnessAttestationV1`` minted from a real container
  execution. ``check_control_sequence`` refuses the whole run if the observed
  map differs from the expected one, in either direction, and the registration
  evidence takes its control verdicts from the observed map rather than from a
  literal.
* It never weakens a control. The clean, wrong and slow kernels are the
  problem's OWN shipped files, read where they lie, and the interface control is
  the driver's own mechanical transform of the problem's own seed. There is no
  flag that lowers a bound, skips a case or accepts a different verdict.
* It refuses to run uncontainerised. The pinned image is a precondition, not a
  fallback: a correctness verdict taken outside it is not the verdict this
  manifest was registered for.
* ``controls`` writes nothing into the repository and needs no human identity.
  ``promote`` requires ``--actor-id`` and ``--authorization-basis`` and is an
  authenticated human-maintainer surface, exactly like the two scripts beside
  it. Building the capability is not the same act as exercising it.

WHERE THE BUNDLE LANDS. Adding attestations to an existing evidence directory
moves ``evidence_digest``, hence the catalog row, hence the promotion approval
signature. So these artifacts cannot be dropped beside the current bundle: the
run has to be part of a re-registration a maintainer signs, which is what
``promote`` does and why it is gated. ``--harness-root`` exists so the whole
write path can be rehearsed against a copy outside the repository first.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import socket
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ARI_CORE = REPO_ROOT / "ari-core"
sys.path.insert(0, str(ARI_CORE))
# The sibling promotion surface, so ``promote`` reuses its slug and stale-pin
# helpers rather than growing a second copy of the derived-pin rules. Inserted at
# import time, not inside ``main``, so importing this module is enough.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ari.assurance.catalog import build_harness_catalog_snapshot  # noqa: E402
from ari.assurance.contract import load_tolerance_policy  # noqa: E402
from ari.assurance.drivers.problem_correctness import (  # noqa: E402
    PROBLEM_CORRECTNESS_DRIVER_REVISION,
    ProblemCorrectnessDriver,
    _EXTRA_SYMBOL,
)
from ari.assurance.executors import PinnedContainerExecutor  # noqa: E402
from ari.assurance.models import (  # noqa: E402
    HarnessManifestV1,
    HarnessTargetDeclarationV1,
    VerificationContractV1,
    VerificationRequirementV1,
)
from ari.assurance.problems import load_problem  # noqa: E402
from ari.assurance.registration_models import (  # noqa: E402
    HarnessPromotionApprovalV1,
    HarnessRegistrationEvidenceV1,
)
from ari.assurance.registration_run import (  # noqa: E402
    register_harness,
    repository_commit,
)
from ari.assurance.request import (  # noqa: E402
    build_native_harness_run_request,
    harness_inapplicability,
)
from ari.assurance.resolver import (  # noqa: E402
    mint_baseline_harness_lock,
    resolve_harness_suite,
)
from ari.assurance.runner import FixedVerifier  # noqa: E402
from ari.assurance.target_abi import problem_target_kind  # noqa: E402
from ari.execution import WorkspaceRefV1  # noqa: E402
from ari.protocols.integrity import bytes_digest, canonical_digest  # noqa: E402
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1  # noqa: E402


HARNESS_ROOT = ARI_CORE / "config" / "harnesses"
BUILTIN = HARNESS_ROOT / "builtin"
POLICIES = HARNESS_ROOT / "policies"

#: Below this a term is an ordinary word. A passwd name like ``ari`` or a host
#: name like ``node1`` occurs inside JSON keys, digests, C identifiers and
#: English prose, so a guard that matched them would refuse every bundle and be
#: switched off -- which is worse than a narrower guard that is believed.
#: ``host_identity_terms`` refuses rather than dropping a candidate under it.
MINIMUM_IDENTITY_TERM_LENGTH = 6


class ControlSequenceError(RuntimeError):
    """The controls did not discriminate, so nothing may be attested."""


@dataclass(frozen=True)
class Control:
    """One labelled execution and the outcome it must produce ON ITS OWN.

    ``property_verdicts`` is not decoration. A sequence that only pinned the
    harness-level verdict would accept a negative control that failed for the
    wrong reason -- a build error, say, instead of the oracle -- and would let an
    interface-conformance claim rest on four runs that never saw it fail.
    """

    label: str
    #: Which of the problem's own files is staged, by the name the problem's
    #: ``scaffolding`` uses. ``seed_candidate+extra-symbol`` is the driver's
    #: mechanical transform, applied here exactly as ``parity_probe`` applies it.
    role: str
    tier: str
    retry_index: int
    verdict: str
    property_verdicts: dict[str, str]
    why: str


#: THE SEQUENCE. The first four are the shape ``promote_native_harnesses`` runs
#: for the three native families, with the same labels and the same expected
#: verdicts, so a reader can compare the two evidence bundles line for line.
#:
#: THE FIFTH IS NOT DECORATION. This manifest declares TWO properties, and in all
#: four of the native-shaped runs ``interface-conformance`` comes back ``pass`` --
#: including in ``negative-screen``, because ``wrong_gemm.c`` keeps the contract
#: perfectly and only misses the numbers. Registering a conformance claim on four
#: runs none of which ever saw it fail is the same defect as a declared constant,
#: one property smaller. The control that fails it is already in the codebase and
#: needs no new kernel: ``ProblemCorrectnessDriver`` appends one file-scope global
#: to the problem's OWN seed candidate, and the object audit refuses it.
#:
#: The specificity direction -- a correct-but-SLOW kernel must PASS, or the
#: instrument is a stopwatch wearing a correctness label -- is established by
#: ``ProblemCorrectnessDriver.parity_probe``, which ``register_harness`` runs and
#: gates on. It is deliberately not duplicated as a sixth container execution.
CONTROLS: tuple[Control, ...] = (
    Control(
        label="clean-screen",
        role="reference",
        tier="screen",
        retry_index=0,
        verdict="pass",
        property_verdicts={"numerical-equivalence": "pass",
                           "interface-conformance": "pass"},
        why="the problem's frozen reference is right about its own question",
    ),
    Control(
        label="clean-certify",
        role="reference",
        tier="certify",
        retry_index=0,
        verdict="pass",
        property_verdicts={"numerical-equivalence": "pass",
                           "interface-conformance": "pass"},
        why="and stays right at the tier a publication claim is made at",
    ),
    Control(
        label="clean-certify-repeat",
        role="reference",
        tier="certify",
        retry_index=1,
        verdict="pass",
        property_verdicts={"numerical-equivalence": "pass",
                           "interface-conformance": "pass"},
        why=("and again, at a different derived seed: the verdict is stable "
             "across instances, which is a weaker and more honest claim than "
             "digest equality"),
    ),
    Control(
        label="negative-screen",
        role="negative_control_wrong",
        tier="screen",
        retry_index=0,
        verdict="fail",
        property_verdicts={"numerical-equivalence": "fail",
                           "interface-conformance": "pass"},
        why=("a fast-but-wrong kernel is caught BY THE ORACLE: it builds, it "
             "conforms, it writes every element, and it misses the bound"),
    ),
    Control(
        label="negative-interface-screen",
        role="seed_candidate+extra-symbol",
        tier="screen",
        retry_index=0,
        verdict="fail",
        property_verdicts={"numerical-equivalence": "fail",
                           "interface-conformance": "fail"},
        why=("a kernel that exports a symbol the contract does not grant is "
             "refused by the object audit; this is the only run in which "
             "interface-conformance is ever seen to fail"),
    ),
)


# --------------------------------------------------------------------------
# host identity
# --------------------------------------------------------------------------

def host_identity_terms() -> tuple[str, ...]:
    """Strings that must not appear in anything this module writes.

    The bundle is committed and published. ``measurement_environment`` captures
    every variable under a prefix set and drops SECRETS by name fragment, but not
    host PATHS by value, and the worker's stdout is persisted verbatim under
    ``logs/``. Measured elsewhere in this repository: a bundle carried a home
    directory and a username that way, and the bundles that did not were clean
    only because the variable happened to be unset.

    Collected at run time and never written anywhere -- including into the
    refusal message, which names the artifact and the term's index, not the term.
    """
    candidates = {
        str(REPO_ROOT),
        str(Path.home()),
        socket.gethostname(),
        socket.getfqdn(),
        platform.node(),
    }
    try:
        candidates.add(getpass.getuser())
    except (KeyError, OSError):  # pragma: no cover - no passwd entry
        pass
    ordered = tuple(sorted(item for item in candidates if item))

    # THE LENGTH FLOOR IS CHECKED, NOT ASSUMED. It used to be a filter: anything
    # under it was dropped, silently, so the guard was narrowest exactly on the
    # machines whose identity is hardest to distinguish from ordinary text -- and
    # the bundle was published either way, carrying an unchecked term. Measured
    # on the machine this promotion runs from: every candidate above is a
    # filesystem path, a DNS name or a passwd name, and each clears the floor, so
    # the floor drops nothing here and the filter never had anything to hide.
    # That is a fact about one machine, which is why it is now asked rather than
    # written down. Where a candidate would be dropped, the honest answer is that
    # this guard cannot certify that bundle, not a guard that quietly stopped
    # covering a term.
    #
    # An UNSET candidate is not the same thing: there is no identity to leak, so
    # it is excluded above and does not refuse.
    short = [index for index, item in enumerate(ordered)
             if len(item) < MINIMUM_IDENTITY_TERM_LENGTH]
    if short:
        raise ControlSequenceError(
            f"local identity term(s) {short} are shorter than "
            f"{MINIMUM_IDENTITY_TERM_LENGTH} characters. Matching them would "
            f"refuse ordinary prose, and dropping them would publish a bundle "
            f"this guard had not checked for them, so the promotion is refused "
            f"instead. The terms are not named here, for the same reason the "
            f"leak refusal names an index")
    return ordered


def refuse_host_identity(artifacts: dict[str, bytes]) -> None:
    terms = host_identity_terms()
    for name, payload in sorted(artifacts.items()):
        text = payload.decode("utf-8", errors="replace")
        for index, term in enumerate(terms):
            if term in text:
                raise ControlSequenceError(
                    f"{name} carries host identity (local identity term "
                    f"#{index}); this bundle is published, so it is refused "
                    f"rather than scrubbed -- scrubbing would hide which "
                    f"artifact leaked it")


# --------------------------------------------------------------------------
# manifest, contract, declaration -- all DERIVED from what is registered
# --------------------------------------------------------------------------

def load_manifest(path: Path) -> HarnessManifestV1:
    manifest = HarnessManifestV1.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8")))
    if manifest.driver.revision != PROBLEM_CORRECTNESS_DRIVER_REVISION:
        raise ControlSequenceError(
            f"{manifest.id} pins driver {manifest.driver.revision!r}; this "
            f"sequence runs {PROBLEM_CORRECTNESS_DRIVER_REVISION!r} only")
    if len(manifest.target_kinds) != 1:
        raise ControlSequenceError(
            f"{manifest.id} accepts {list(manifest.target_kinds)}; a control "
            f"sequence stages ONE artifact, so the target kind must be one")
    return manifest


def _tolerance_ref(digest: str) -> str:
    """The policy REF for a digest a manifest pins, found rather than typed.

    A requirement carries both, and only the digest is compared by ``_coverage``,
    so a typed ref that names a different policy from the one being compared
    against is a mislabel nothing can catch.
    """
    for path in sorted(POLICIES.glob("*.yaml")):
        ref, found = load_tolerance_policy(path)
        if found == digest:
            return ref
    raise ControlSequenceError(
        f"no shipped tolerance policy has digest {digest}; the manifest pins a "
        f"policy this repository does not contain")


def build_control_contract(manifest: HarnessManifestV1) -> VerificationContractV1:
    """A contract over exactly the properties and tiers THIS manifest declares.

    Everything here is read off the manifest: the properties, their methods,
    their scopes, their tolerance digests and the target kind. Nothing is typed.
    That is the whole difference from ``promote_native_harnesses._contract``,
    which stamps three properties, ``shared-library`` and two dtypes -- true of
    the families it was written for and false here, so reusing it verbatim
    leaves atoms unsatisfied and the suite cannot resolve.
    """
    target_kind = manifest.target_kinds[0]
    tiers = tuple(sorted({control.tier for control in CONTROLS},
                         key=("screen", "validate", "certify").index))
    requirements: list[VerificationRequirementV1] = []
    for provided in manifest.properties:
        for tier in tiers:
            if tier not in provided.tiers:
                raise ControlSequenceError(
                    f"{manifest.id} does not declare {provided.property_id} at "
                    f"tier {tier!r}, which the control sequence runs")
            requirements.append(
                VerificationRequirementV1.create(
                    property_id=provided.property_id,
                    target_kind=target_kind,
                    required_methods=provided.methods,
                    required_tier=tier,
                    # The strongest tier this sequence runs blocks publication;
                    # the screening tier only excludes from the frontier. Same
                    # split the native contract makes, derived from the tier
                    # rather than written per requirement.
                    failure_policy=("block-publication" if tier == "certify"
                                    else "exclude-from-scientific-frontier"),
                    scope=provided.scope,
                    tolerance_policy_ref=_tolerance_ref(
                        provided.tolerance_policy_digest),
                    tolerance_policy_digest=provided.tolerance_policy_digest,
                    source_requirement_refs=("registration:" + manifest.id,),
                )
            )
    return VerificationContractV1.create(
        run_id="harness-registration-" + manifest.id.replace("/", "-"),
        research_contract_digest=canonical_digest(
            {"registration": manifest.id,
             "manifest_digest": manifest.manifest_digest}),
        requirements=tuple(sorted(requirements,
                                  key=lambda item: item.requirement_digest)),
        admission_confidence=1.0,
        human_review_identity=canonical_digest(
            "problem-correctness-harness-registration"),
        property_vocabulary_digest=bytes_digest(
            (HARNESS_ROOT / "property_vocabulary.yaml").read_bytes()),
    )


def build_declaration(
    manifest: HarnessManifestV1, workspace: WorkspaceRefV1, logical_name: str
) -> HarnessTargetDeclarationV1:
    """What the node WOULD declare for this candidate, derived the same way.

    ``target_kind`` comes from ``problem_target_kind`` and the contract name from
    the problem revision -- the two functions ``evaluator.assurance_measure.
    declare_target`` reads -- so the declaration this sequence stages cannot
    drift from the one a governed run mints. The remaining axes come off the
    manifest, and ``harness_inapplicability`` is asked before the request is
    minted so a mismatch is an error here rather than a verdict about a
    candidate later.
    """
    problem = load_problem(manifest.oracle.revision)
    definition = problem.definition
    declaration = HarnessTargetDeclarationV1.create(
        logical_name=logical_name,
        target_kind=problem_target_kind(definition.entry_point, definition.family),
        subject_type=manifest.subject_types[0],
        language=manifest.supported_languages[0],
        hardware=manifest.supported_hardware[0],
        architecture=platform.machine(),
        dtype=manifest.supported_dtypes[0],
        interface_contract=f"problem:{definition.revision}",
        target_digest=workspace.file_digest(logical_name),
    )
    refusal = harness_inapplicability(manifest=manifest, declaration=declaration)
    if refusal:
        raise ControlSequenceError(
            f"{manifest.id} cannot judge the candidate this sequence stages: "
            f"{refusal}")
    return declaration


def candidate_source(manifest: HarnessManifestV1, role: str) -> tuple[str, bytes]:
    """``(provenance, bytes)`` for one control, from the PROBLEM's own files.

    Nothing is authored here. A control kernel written into this script would be
    a control the instrument's own registration could not point at, and a
    weakened one would be indistinguishable from a strengthened instrument.
    """
    problem = load_problem(manifest.oracle.revision)
    scaffolding = problem.definition.scaffolding
    if role == "seed_candidate+extra-symbol":
        name = scaffolding.seed_candidate
        if not name:
            raise ControlSequenceError(
                f"problem {problem.definition.revision!r} declares no seed "
                f"candidate, so the interface control cannot be synthesised "
                f"from the problem's own C")
        payload = problem.path(name).read_text(encoding="utf-8") + _EXTRA_SYMBOL
        return (f"{name} + the driver's file-scope-global transform",
                payload.encode("utf-8"))
    name = getattr(scaffolding, role, None)
    if not name:
        raise ControlSequenceError(
            f"problem {problem.definition.revision!r} declares no {role!r}, so "
            f"this sequence could only show that the harness runs")
    return name, problem.path(name).read_bytes()


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------

def property_map(attestation: Any) -> dict[str, str]:
    """``property_id -> verdict``, refusing a self-contradictory attestation."""
    found: dict[str, str] = {}
    for item in attestation.property_results:
        previous = found.setdefault(item.property_id, item.verdict)
        if previous != item.verdict:
            raise ControlSequenceError(
                f"one attestation reports {item.property_id} as both "
                f"{previous!r} and {item.verdict!r}")
    return found


def _property_result(attestation: Any, property_id: str) -> Any:
    for item in attestation.property_results:
        if item.property_id == property_id:
            return item
    raise ControlSequenceError(
        f"the attestation carries no result for {property_id!r}")


def residual_ratio_limit(label: str, attestation: Any) -> float:
    """The bound THIS execution normalised its ratio to, READ off the run.

    This was a module constant, ``RESIDUAL_RATIO_LIMIT = 1.0``: compared against,
    and then republished into every run's discrimination record as though it had
    been observed. That is the declared-constant defect in the place it is least
    visible. A residual ratio means nothing without the bound it is normalised
    to, so a driver that moved its bound would leave this module checking every
    control against a stale 1.0 AND writing that same stale 1.0 beside the ratio
    -- both wrong in the same direction, so no artifact here could disagree with
    any other, and the bundle would read as consistent evidence for a comparison
    that never happened.

    ``ProblemCorrectnessDriver`` already publishes the bound per property result
    in ``tolerance_evidence``, which is why this is a read and not a new
    measurement.

    FAIL-CLOSED. Absent, non-numeric, boolean, non-finite or non-positive is a
    refusal rather than a fallback to 1.0: a ratio compared against a bound
    nobody stated is not a comparison, and a bound of zero or infinity accepts
    nothing or everything.
    """
    numeric = _property_result(attestation, "numerical-equivalence")
    found = dict(getattr(numeric, "tolerance_evidence", None) or {}).get(
        "residual_ratio_limit")
    if isinstance(found, bool) or not isinstance(found, (int, float)):
        raise ControlSequenceError(
            f"{label} states no numeric residual_ratio_limit in its tolerance "
            f"evidence, so the ratio it reports is normalised to a bound this "
            f"record does not carry and nothing here may compare against it")
    limit = float(found)
    if not limit > 0.0 or limit == float("inf"):
        raise ControlSequenceError(
            f"{label} reports residual_ratio_limit {limit!r}; a bound that is "
            f"not a positive finite number accepts everything or nothing, and "
            f"either way a verdict taken against it decides nothing")
    return limit


def discrimination_evidence(label: str, attestation: Any) -> dict[str, Any]:
    """WHY this run landed where it did, read back off the attestation.

    A verdict map alone is satisfied by an instrument that fails everything, or
    by a negative control that failed because it did not compile. These are the
    facts that separate those cases, and ``check_control_sequence`` refuses when
    they are absent -- so a control which stopped being a control is a refusal
    rather than a quieter bundle.
    """
    numeric = _property_result(attestation, "numerical-equivalence")
    interface = _property_result(attestation, "interface-conformance")
    measurements = dict(numeric.measurements or {})
    oracle = dict(numeric.oracle_comparison or {})
    sizes = dict(measurements.get("output_elements_by_case") or {})
    return {
        "case_count": measurements.get("case_count"),
        "failed_case_count": measurements.get("failed_case_count"),
        "worst_residual_ratio": measurements.get("worst_residual_ratio"),
        # READ off this execution's own tolerance evidence, so the ratio above
        # is published beside the bound it was actually judged against.
        "residual_ratio_limit": residual_ratio_limit(label, attestation),
        # ``None``, not ``False``, when no case ran: absent is not "some case
        # wrote the wrong count", and the interface control scores nothing.
        "every_case_wrote_the_expected_element_count": (
            all(entry.get("written") == entry.get("expected")
                for entry in sizes.values()) if sizes else None),
        "build_error": oracle.get("build_error"),
        "interface_error": dict(
            interface.oracle_comparison or {}).get("interface_error"),
        "verifier_report_digest": oracle.get("report_digest"),
        "label": label,
    }


def _refuse(reason: str) -> None:
    raise ControlSequenceError(reason)


def check_control_sequence(attestations: dict[str, Any]) -> dict[str, Any]:
    """Decide whether the sequence discriminated. THE ONLY PLACE THAT DECIDES.

    Returns the observed control verdicts. It raises rather than returning a
    weaker answer, because a partially-discriminating sequence is not evidence of
    anything: the ONE thing an attestation bundle is for is saying that this
    instrument was seen to accept a right answer and reject a wrong one.
    """
    expected_labels = tuple(control.label for control in CONTROLS)
    if tuple(sorted(attestations)) != tuple(sorted(expected_labels)):
        _refuse(f"the sequence ran {sorted(attestations)}, not "
                f"{sorted(expected_labels)}")

    observed = {label: attestations[label].verdict for label in expected_labels}
    wanted = {control.label: control.verdict for control in CONTROLS}
    if observed != wanted:
        _refuse(f"control verdicts differ from what this instrument must "
                f"produce: observed {observed}, required {wanted}")

    for control in CONTROLS:
        attestation = attestations[control.label]
        seen = property_map(attestation)
        if seen != control.property_verdicts:
            _refuse(f"{control.label}: property verdicts {seen} differ from the "
                    f"required {control.property_verdicts}; the run reached the "
                    f"right overall answer for the wrong reason")
        if getattr(attestation, "infrastructure_status", "ready") != "ready":
            _refuse(f"{control.label}: infrastructure status "
                    f"{attestation.infrastructure_status!r}, so its verdict is "
                    f"about the substrate and not about the candidate")

    # NONDETERMINISM, ON THE PASSING RUNS. Same check the native sequence makes:
    # a driver emits an observation only when a repeat launch of the SAME input
    # produced different bytes, and a clean control that did that has not shown
    # the instrument repeats.
    unstable = sorted(label for label, item in attestations.items()
                      if item.verdict == "pass" and item.nondeterminism_observations)
    if unstable:
        _refuse(f"clean controls were nondeterministic: {unstable}")

    evidence = {control.label: discrimination_evidence(
        control.label, attestations[control.label]) for control in CONTROLS}

    # ONE BOUND, READ FROM THE RUNS. Every ratio in this record is normalised to
    # it, so controls judged against different bounds are not comparable and the
    # pass/fail split below would be taken against whichever one happened to be
    # picked. Refusing on disagreement is the other half of refusing on absence:
    # both are ways for the comparison to be undefined.
    bounds = {label: found["residual_ratio_limit"]
              for label, found in evidence.items()}
    distinct = sorted(set(bounds.values()))
    if len(distinct) != 1:
        _refuse(f"the controls were judged against different residual bounds "
                f"{bounds}; a ratio is only readable beside the bound it was "
                f"normalised to, so this sequence compares nothing")
    limit = distinct[0]

    for control in CONTROLS:
        found = evidence[control.label]
        if control.verdict == "pass":
            worst = found["worst_residual_ratio"]
            if not isinstance(worst, (int, float)):
                _refuse(f"{control.label} passed while reporting no residual "
                        f"ratio at all; a pass with no measurement behind it is "
                        f"the defect this bundle exists to remove")
            if worst > limit:
                _refuse(f"{control.label} passed with a residual ratio {worst} "
                        f"above the bound {limit}")
            if found["failed_case_count"] != 0 or not found["case_count"]:
                _refuse(f"{control.label} passed with "
                        f"{found['failed_case_count']} failed case(s) out of "
                        f"{found['case_count']}")

    # THE WRONG KERNEL MUST BE CAUGHT BY THE ORACLE. If it were caught by the
    # build, by the object audit or by the element-count check, the bundle would
    # show that the harness rejects a file -- not that it can tell a wrong answer
    # from a right one.
    wrong = evidence["negative-screen"]
    if wrong["build_error"] or wrong["interface_error"]:
        _refuse("negative-screen failed before the oracle ran (build or "
                "interface fault); it therefore shows nothing about whether "
                "this instrument can detect a wrong answer")
    if not wrong["every_case_wrote_the_expected_element_count"]:
        _refuse("negative-screen was caught by the element-count check rather "
                "than by the residual bound")
    ratio = wrong["worst_residual_ratio"]
    if not isinstance(ratio, (int, float)) or ratio <= limit:
        _refuse(f"negative-screen reported worst residual ratio {ratio!r}, "
                f"which does not exceed the bound {limit}")
    if wrong["failed_case_count"] != wrong["case_count"]:
        _refuse(f"negative-screen failed {wrong['failed_case_count']} of "
                f"{wrong['case_count']} cases; a wrong kernel that is right "
                f"about some shapes is not the control this claims to be")

    # AND THE INTERFACE CONTROL MUST BE CAUGHT BY THE AUDIT, naming the symbol.
    exports = evidence["negative-interface-screen"]
    if not exports["interface_error"]:
        _refuse("negative-interface-screen failed without an interface error, "
                "so the interface-conformance claim still rests on no run that "
                "was ever seen to fail it")
    if exports["case_count"]:
        _refuse("negative-interface-screen scored cases; the audit was supposed "
                "to refuse the object before anything ran")

    return {
        "clean_control_verdict": _single(
            [observed[c.label] for c in CONTROLS if c.role == "reference"]),
        "negative_control_verdict": _single(
            [observed[c.label] for c in CONTROLS if c.role != "reference"]),
        "observed_verdicts": observed,
        "discrimination": evidence,
    }


def _single(values: list[str]) -> str:
    """One verdict for a group of controls, or ``not_available`` if they differ.

    ``not_available`` is a real value in ``HarnessRegistrationEvidenceV1``, and
    it is the honest answer when the runs disagree. It is unreachable while
    ``check_control_sequence`` refuses first -- which is the point: the literal
    is never the thing that decides.
    """
    distinct = set(values)
    return distinct.pop() if len(distinct) == 1 else "not_available"


def isolation_findings(
    manifest: HarnessManifestV1,
    *,
    executions: list[dict[str, Any]],
    target_digests: dict[str, tuple[str, str]],
    attestations: dict[str, Any],
) -> dict[str, Any]:
    """The remaining ``registration_evidence`` fields, derived rather than typed.

    ``clean_control_verdict`` and ``negative_control_verdict`` are the loud half
    of the declared-constants defect, but they are not all of it: BOTH shipped
    promotion surfaces also write ``network_isolation="proved"``,
    ``target_write_isolation="proved"``, ``oracle_visibility="denied"`` and
    ``result_schema_conformant=True`` as literals. Writing those fresh in a new
    file, having just removed two literals beside them, would be the same defect
    with a shorter blast radius. What each one below rests on:

    * NETWORK. Every execution declared ``network: deny`` and carried the
      manifest's own container digest. ``PinnedContainerExecutor`` refuses any
      other, and the reviewed argv it builds passes ``--net --network none`` --
      isolation is proved by that argv rather than by a caller's boolean, which
      is why the fact worth recording is the request each run actually carried.
    * TARGET WRITE. The candidate's digest before and after each execution, read
      from the workspace. ``FixedVerifier`` refuses to mint an attestation when
      they differ, so an attestation existing already implies it -- recorded
      explicitly so a reader does not have to know that.
    * ORACLE VISIBILITY. From the manifest's own ``hidden_test_policy``. This is
      the weakest of the four and is labelled as such: it is a statement about
      what the manifest DECLARES, not a measurement of what the candidate could
      reach. A stronger claim would need an execution that tried.
    * RESULT SCHEMA. The driver's emitted schema version and its digest must be
      the ones the manifest pins, AND every run's stdout must have parsed into
      that typed report -- which is exactly what ``normalize_result`` did, since
      a malformed report degrades the run to ``infrastructure_error``.
    """
    from ari.assurance.registration_run import result_schema_digest

    networks = {item.get("network") for item in executions}
    containers = {item.get("container_identity_digest") for item in executions}
    unchanged = {label: before == after
                 for label, (before, after) in target_digests.items()}
    emitted = ProblemCorrectnessDriver().report_schema_version
    schema_matches = (
        manifest.expected_result_schema == emitted
        and manifest.expected_result_schema_digest == result_schema_digest(emitted))
    parsed = all(getattr(item, "infrastructure_status", "") == "ready"
                 for item in attestations.values())
    return {
        "network_isolation": (
            "proved" if networks == {"deny"}
            and containers == {manifest.container.resolved_digest}
            else "not_proved"),
        "target_write_isolation": (
            "proved" if unchanged and all(unchanged.values()) else "not_proved"),
        "oracle_visibility": (
            "denied" if manifest.hidden_test_policy == "verifier-only"
            else "not_proved"),
        "result_schema_conformant": bool(schema_matches and parsed),
        "basis": {
            "declared_networks": sorted(value for value in networks if value),
            "container_identity_matched_the_manifest_pin": (
                containers == {manifest.container.resolved_digest}),
            "target_digest_unchanged_by_run": dict(sorted(unchanged.items())),
            "emitted_result_schema": emitted,
            "manifest_pins_that_schema_and_its_digest": schema_matches,
            "every_run_returned_a_parsed_typed_report": parsed,
            "oracle_visibility_note": (
                "read off the manifest's hidden_test_policy; this records what "
                "the manifest declares, not an execution that tried to reach "
                "the oracle"),
        },
    }


# --------------------------------------------------------------------------
# the sequence
# --------------------------------------------------------------------------

def _json_bytes(value: Any) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _wall_seconds(started_at: str, completed_at: str) -> float:
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    return max(0.0, (end - start).total_seconds())


def run_control_sequence(
    *,
    manifest: HarnessManifestV1,
    container_root: Path,
    working_root: Path,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Run every control through the pinned container; return what was observed.

    Nothing about the outcome is decided here. This function launches, collects
    and hands the attestations to ``check_control_sequence``.
    """
    if not container_root.is_absolute() or container_root.is_symlink() \
            or not container_root.is_dir():
        raise ControlSequenceError(
            "the pinned container root must be an absolute real directory; "
            "running this verifier outside its image is not a fallback, it is a "
            "different measurement")

    # BEFORE ANYTHING LAUNCHES. ``FixedVerifier`` already refuses a drifted
    # driver -- correctly -- but it does so inside the loop, so a repository
    # whose instrument files moved while the sequence was running produced four
    # minutes of container work and then a bare "Harness driver identity drift"
    # traceback. Measured, on exactly that: a concurrent writer touched
    # ``native_perf_common.py``, which sits inside this driver's digest, midway
    # through a run. Asked here, it is one sentence naming the repair.
    current = ProblemCorrectnessDriver().identity()["driver_digest"]
    if current != manifest.driver.sha256:
        raise ControlSequenceError(
            f"{manifest.id} pins driver bytes this repository no longer has, so "
            f"nothing measured here would describe the registered instrument. "
            f"Run from a clean worktree at the pinned commit, or re-pin with "
            f"repin_and_promote_harness.py and commit first")

    problem = load_problem(manifest.oracle.revision)
    logical_name = problem.definition.score_inputs[0]
    contract = build_control_contract(manifest)
    environment = EnvironmentSnapshotV1.create(
        resource_types=("cpu", "process"),
        features=tuple(manifest.resources.features),
        transports=("local-process",),
        network_classes=(manifest.network_policy,),
        metadata={
            "architecture": platform.machine(),
            "container_digest": manifest.container.resolved_digest,
            # From the pin. Written as a constant, the one field naming the
            # runtime is the one field that can be wrong about it.
            "container_runtime": manifest.container.reference.split(":", 1)[0],
            "kernel_release": platform.release(),
        },
    )
    placeholder = canonical_digest({"phase": "pre-registration", "id": manifest.id})
    catalog = build_harness_catalog_snapshot(
        catalog_source_revision="problem-correctness-registration/v1",
        property_vocabulary_digest=contract.property_vocabulary_digest,
        driver_protocol_version="ari.harness-driver/v1",
        manifests=(manifest,),
        registration_report_digests={manifest.id: placeholder},
        registration_evidence_digests={manifest.id: placeholder},
        promotion_approval_digests={manifest.id: placeholder},
    )
    suite = resolve_harness_suite(
        contract=contract, catalog=catalog, environment=environment)
    if suite.unsatisfied_atom_digests:
        raise ControlSequenceError(
            f"{len(suite.unsatisfied_atom_digests)} contract atom(s) are not "
            f"covered by {manifest.id}; the sequence would attest to less than "
            f"it claims")
    baseline = mint_baseline_harness_lock(
        run_id=contract.run_id,
        research_contract_digest=contract.research_contract_digest,
        contract=contract,
        catalog=catalog,
        environment=environment,
        oracle_bundle_digest=manifest.oracle.sha256,
        suite=suite,
    )

    executions: list[dict[str, Any]] = []
    logs: dict[str, bytes] = {}

    def observe(_manifest, request, result, attestation) -> None:
        wall = _wall_seconds(result.started_at, result.completed_at)
        executions.append({
            "attempt_id": request.attempt_id,
            "attestation_digest": attestation.attestation_digest,
            "completed_at": result.completed_at,
            "container_digest": manifest.container.resolved_digest,
            "cpu_core_seconds": wall * manifest.resources.cpu_cores,
            # WHAT THE REQUEST ACTUALLY CARRIED, so the isolation claims below
            # rest on the reviewed request rather than on a sentence.
            "container_identity_digest": (
                request.execution_request.container.digest
                if request.execution_request.container is not None else None),
            "network": request.execution_request.network,
            "execution_identity": result.execution_identity,
            "execution_result_digest": canonical_digest(result),
            "execution_status": result.status,
            "memory_byte_seconds": wall * manifest.resources.memory_bytes,
            "pricing_status": "unpriced",
            "started_at": result.started_at,
            "tier": request.property_atoms[0].tier,
            "wall_seconds": wall,
        })
        for artifact in result.artifacts:
            payload = request.execution_request.workspace.read_bytes(
                artifact.relative_path, max_bytes=result.limits.max_output_bytes)
            logs[request.node_id.replace("registration-", "") + "-"
                 + artifact.logical_role
                 + Path(artifact.relative_path).suffix] = payload

    verifier = FixedVerifier(
        {PROBLEM_CORRECTNESS_DRIVER_REVISION: ProblemCorrectnessDriver()},
        executor=PinnedContainerExecutor(package_root=ARI_CORE),
        execution_observer=observe,
    )
    previous_root = os.environ.get("ARI_HARNESS_CONTAINER_ROOT")
    os.environ["ARI_HARNESS_CONTAINER_ROOT"] = str(container_root)
    attestations: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    #: ``label -> (digest before the run, digest after it)``. The runner refuses
    #: to mint an attestation when these differ; recorded so the isolation claim
    #: names an observation instead of resting on that being known.
    target_digests: dict[str, tuple[str, str]] = {}
    try:
        for control in CONTROLS:
            candidate_root = working_root / control.label / "candidate"
            execution_root = working_root / control.label / "verification"
            candidate_root.mkdir(parents=True)
            execution_root.mkdir(parents=True)
            origin, payload = candidate_source(manifest, control.role)
            provenance[control.label] = origin
            (candidate_root / logical_name).write_bytes(payload)
            workspace = WorkspaceRefV1(root=str(candidate_root))
            declaration = build_declaration(manifest, workspace, logical_name)
            request = build_native_harness_run_request(
                run_id=contract.run_id,
                node_id="registration-" + control.label,
                epoch_id="registration-epoch",
                workspace=workspace,
                execution_workspace=WorkspaceRefV1(root=str(execution_root)),
                declaration=declaration,
                manifest=manifest,
                locked=baseline.harnesses[0],
                baseline=baseline,
                tier=control.tier,
                retry_index=control.retry_index,
            )
            attestations[control.label] = verifier.run(
                manifest=manifest,
                request=request,
                baseline_lock=baseline,
                research_contract_digest=contract.research_contract_digest,
                verification_contract_digest=contract.contract_digest,
                knowledge_skill_use_digest=canonical_digest(
                    "registration-no-knowledge"),
                capability_binding_lock_digest=canonical_digest(
                    "registration-no-provider"),
                producer_epoch_id="registration-epoch",
            )
            target_digests[control.label] = (
                declaration.target_digest, workspace.file_digest(logical_name))
    finally:
        if previous_root is None:
            os.environ.pop("ARI_HARNESS_CONTAINER_ROOT", None)
        else:
            os.environ["ARI_HARNESS_CONTAINER_ROOT"] = previous_root

    incomplete = sorted(item["attempt_id"] for item in executions
                        if item["execution_status"] != "completed")
    if incomplete:
        raise ControlSequenceError(
            f"{len(incomplete)} execution(s) did not complete; a control that "
            f"did not run is not a control")
    checked = check_control_sequence(attestations)
    isolation = isolation_findings(
        manifest, executions=executions, target_digests=target_digests,
        attestations=attestations)

    sequence: dict[str, Any] = {
        "schema_version": "ari.harness-control-sequence/v1",
        "harness_id": manifest.id,
        "harness_version": manifest.version,
        "manifest_digest": manifest.manifest_digest,
        "driver_revision": manifest.driver.revision,
        "driver_digest": manifest.driver.sha256,
        "container_digest": manifest.container.resolved_digest,
        "container_reference": manifest.container.reference,
        "problem_revision": manifest.oracle.revision,
        "problem_digest": manifest.oracle.sha256,
        "dataset_revision": manifest.dataset.revision,
        "dataset_digest": manifest.dataset.sha256,
        "verification_contract_digest": contract.contract_digest,
        "baseline_lock_digest": baseline.lock_digest,
        "environment_digest": environment.identity_digest,
        "target_logical_name": logical_name,
        "runs": [
            {
                "label": control.label,
                "candidate_provenance": provenance[control.label],
                "tier": control.tier,
                "retry_index": control.retry_index,
                "required_verdict": control.verdict,
                "observed_verdict": attestations[control.label].verdict,
                "required_property_verdicts": dict(
                    sorted(control.property_verdicts.items())),
                "observed_property_verdicts": dict(
                    sorted(property_map(attestations[control.label]).items())),
                "attempt_id": attestations[control.label].attempt_id,
                "attestation_digest": attestations[
                    control.label].attestation_digest,
                "nondeterminism_observations": list(
                    attestations[control.label].nondeterminism_observations),
                "discrimination": checked["discrimination"][control.label],
                "why": control.why,
            }
            for control in CONTROLS
        ],
        # OBSERVED, not declared. These are the fields ``registration_evidence``
        # reads; nothing in this module may write a literal into any of them.
        "clean_control_verdict": checked["clean_control_verdict"],
        "negative_control_verdict": checked["negative_control_verdict"],
        "isolation": isolation,
        "verdict_source": (
            "read back off HarnessAttestationV1 artifacts minted from container "
            "executions; no control outcome in this record was asserted"),
    }
    sequence["sequence_digest"] = canonical_digest(sequence)

    measurement = {
        "schema_version": "ari.harness-registration-resource-measurements/v1",
        "harness_id": manifest.id,
        "measurement_semantics": {
            "wall_seconds": "executor timestamps",
            "cpu_core_seconds": "declared cores multiplied by measured wall seconds",
            "memory_byte_seconds": "declared bytes multiplied by measured wall seconds",
            "monetary_cost": "unpriced without a locked rate card or invoice",
        },
        "executions": sorted(executions, key=lambda item: item["attempt_id"]),
    }
    measurement["measurement_digest"] = canonical_digest(measurement)

    artifacts: dict[str, bytes] = {
        f"{label}.attestation.json": _json_bytes(item)
        for label, item in attestations.items()
    }
    artifacts.update({f"logs/{name}": payload for name, payload in logs.items()})
    artifacts["resource_measurements.json"] = _json_bytes(measurement)
    artifacts["control_sequence.json"] = _json_bytes(sequence)
    refuse_host_identity(artifacts)

    result = {
        "sequence": sequence,
        "environment": environment,
        "contract": contract,
        "baseline": baseline,
        "attestations": attestations,
        "measurement": measurement,
    }
    return result, artifacts


def _write_bundle(destination: Path, artifacts: dict[str, bytes]) -> None:
    for name, payload in sorted(artifacts.items()):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name("." + path.name + ".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)


def published_artifacts(
    *,
    slug: str,
    artifacts: dict[str, bytes],
    evidence: Any,
    report: Any,
    approval: Any,
    catalog: Any,
) -> dict[str, bytes]:
    """EVERY byte ``promote`` writes into the Harness tree, keyed by its path.

    THE GAP THIS CLOSES. ``refuse_host_identity`` ran over the evidence bundle
    and then FOUR more files were written past it: the registration evidence,
    the registration report, the promotion approval and the catalog. Every one
    of them is committed and published, which is the guard's entire stated
    reason for existing, and every one of them was outside it. The evidence
    bundle is the likeliest leak, because it carries the worker's stdout
    verbatim; it was never the only published thing.

    The repair is structural rather than four more guard calls. ``promote``
    builds this map, guards it ONCE and writes it ONCE, so the guard's coverage
    is a property of the code's shape instead of the order of statements -- and
    a future artifact escapes it only by adding a second write path, which is a
    visible thing to add rather than a line appended after a call.

    Keys are relative to the Harness root, so a refusal names the exact file.

    The catalog is included because it is REWRITTEN whole, rows this promotion
    did not author included: those bytes are written by this mode and are
    therefore this mode's to answer for.
    """
    published = {f"evidence/{slug}/{name}": payload
                 for name, payload in artifacts.items()}
    published[f"evidence/{slug}/registration_evidence.json"] = _json_bytes(evidence)
    published[f"reports/{slug}.registration.json"] = _json_bytes(report)
    published[f"approvals/{slug}.approval.json"] = _json_bytes(approval)
    published["catalog.yaml"] = yaml.safe_dump(
        catalog, sort_keys=False, default_flow_style=False).encode("utf-8")
    return published


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------

def controls(args: argparse.Namespace) -> int:
    """Run the sequence and write its artifacts. No signature, no repo write."""
    manifest = load_manifest(BUILTIN / args.manifest)
    output = args.output_dir.resolve()
    if output.is_relative_to(HARNESS_ROOT):
        raise ControlSequenceError(
            "refusing to write into the registered Harness tree: an evidence "
            "bundle whose digests carry a signature is not a scratch directory")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ari-problem-correctness-") as scratch:
        result, artifacts = run_control_sequence(
            manifest=manifest,
            container_root=args.container_root.resolve(strict=True),
            working_root=Path(scratch) / "runs",
        )
    _write_bundle(output, artifacts)
    sequence = result["sequence"]
    for run in sequence["runs"]:
        print(f"{run['label']:<26} {run['observed_verdict']:<5} "
              f"{run['observed_property_verdicts']}")
    print(f"clean_control_verdict    : {sequence['clean_control_verdict']} "
          f"(observed)")
    print(f"negative_control_verdict : {sequence['negative_control_verdict']} "
          f"(observed)")
    print(f"artifacts                : {len(artifacts)}")
    return 0


def promote(args: argparse.Namespace) -> int:
    """Run the sequence, earn the gates, and sign the re-registration.

    AN AUTHENTICATED HUMAN-MAINTAINER SURFACE. ``--actor-id`` and
    ``--authorization-basis`` are a person's identity and what they actually
    saw; an agent that supplies them is forging both. The capability is the
    ``controls`` mode above.

    Ordering matters and is not tidiness: the sequence runs first, the gates run
    second and refuse a dirty tree, and only then is anything written -- because
    the first write dirties the tree that the source pin is taken from.

    That ordering now holds for EVERY published byte, not just the evidence
    bundle. This function performs exactly one write, of the map
    ``published_artifacts`` builds, immediately after ``refuse_host_identity``
    has passed over all of it. It previously wrote the bundle, then built and
    wrote the registration evidence, the report, the approval and the catalog
    afterwards -- four published artifacts on the far side of the guard.
    """
    from ari.assurance.drivers import builtin_driver_map
    from ari.assurance.native_perf_common import measurement_environment
    from ari.orchestrator.node_summary_view import scrub_host_identity
    from repin_and_promote_harness import _slug, stale_pins

    manifest = load_manifest(BUILTIN / args.manifest)
    stale = stale_pins(manifest)
    if stale:
        print(f"REFUSED: {manifest.id} pins {sorted(stale)} the code no longer "
              f"has. Re-pin with repin_and_promote_harness.py, commit, re-run.")
        return 3

    with tempfile.TemporaryDirectory(prefix="ari-problem-correctness-") as scratch:
        result, artifacts = run_control_sequence(
            manifest=manifest,
            container_root=args.container_root.resolve(strict=True),
            working_root=Path(scratch) / "runs",
        )

    driver = builtin_driver_map()[manifest.driver.revision]
    report = register_harness(manifest, driver, runs=args.runs, allow_dirty=False)
    for gate in report.gates:
        if not gate.passed:
            print(f"  FAIL {gate.gate_id}: {gate.detail[:96]}")
    if report.decision != "eligible-for-verified":
        print("REFUSED: nothing is written; a rejected registration is a result")
        return 4
    commit = repository_commit(allow_dirty=False)

    probe = driver.parity_probe(manifest)
    environment = measurement_environment()
    environment["variables"] = {key: scrub_host_identity(value)
                                for key, value in environment["variables"].items()}
    artifacts["registration_report.json"] = _json_bytes(report)
    artifacts["gate_findings.json"] = _json_bytes(
        {gate.gate_id: {"passed": gate.passed, "detail": gate.detail}
         for gate in report.gates})
    artifacts["official_runner_parity.json"] = _json_bytes(probe)
    artifacts["multiple_run_stability.json"] = _json_bytes(
        {"runs": args.runs, "clean_control": (probe.get("controls") or {}).get("clean")})
    artifacts["measurement_environment.json"] = _json_bytes({
        "environment": environment,
        "registration_commit": commit,
        "placement": None,
        "placement_note": ("this harness pins no placement, so its evidence does "
                           "not describe a machine"),
        "environment_note": "variable VALUES are scrubbed of host identity here",
    })
    harness_root = args.harness_root.resolve()
    slug = _slug(manifest.id)
    evidence_dir = harness_root / "evidence" / slug

    sequence = result["sequence"]
    digests = {f"evidence/{slug}/{name}": bytes_digest(payload)
               for name, payload in artifacts.items()}
    evidence = HarnessRegistrationEvidenceV1.create(
        harness_id=manifest.id,
        harness_version=manifest.version,
        manifest_digest=manifest.manifest_digest,
        source_full_commit_sha=commit,
        environment_digest=result["environment"].identity_digest,
        evidence_artifact_digests=dict(sorted(digests.items())),
        # THE REAL ATTESTATIONS. The path this replaces pointed this field at its
        # own registration report's digest, so the bundle cited itself as the
        # execution it never performed.
        attestation_digests=tuple(sorted(
            item.attestation_digest for item in result["attestations"].values())),
        # OBSERVED, from the sequence record. Not literals -- and not only the
        # two control verdicts: the isolation and schema-conformance fields
        # beside them are the same defect, and are derived in
        # ``isolation_findings`` from what each request carried and what each
        # run returned.
        clean_control_verdict=sequence["clean_control_verdict"],
        negative_control_verdict=sequence["negative_control_verdict"],
        official_runner_parity=bool(probe.get("passed")),
        result_schema_conformant=sequence["isolation"]["result_schema_conformant"],
        network_isolation=sequence["isolation"]["network_isolation"],
        target_write_isolation=sequence["isolation"]["target_write_isolation"],
        oracle_visibility=sequence["isolation"]["oracle_visibility"],
        run_count=len(result["attestations"]),
    )
    approval = HarnessPromotionApprovalV1.create(
        harness_id=manifest.id,
        harness_version=manifest.version,
        actor_kind="human-maintainer",
        actor_id=args.actor_id,
        authorization_basis=args.authorization_basis,
        approved_date=args.approved_date,
        harness_manifest_digest=manifest.manifest_digest,
        registration_report_digest=report.report_digest,
        evidence_bundle_digest=evidence.evidence_digest,
    )
    catalog_path = harness_root / "catalog.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    entry = {
        "id": manifest.id,
        "manifest": f"builtin/{args.manifest}",
        "registration_report": f"reports/{slug}.registration.json",
        "registration_report_digest": report.report_digest,
        "registration_evidence": f"evidence/{slug}/registration_evidence.json",
        "registration_evidence_digest": evidence.evidence_digest,
        "promotion_approval": f"approvals/{slug}.approval.json",
        "promotion_approval_digest": approval.approval_digest,
    }
    catalog["entries"] = sorted(
        [item for item in catalog["entries"] if item["id"] != manifest.id] + [entry],
        key=lambda item: item["id"])

    # NOTHING HAS BEEN WRITTEN YET. Everything above is computation, so the guard
    # below sees the complete set of bytes this mode puts into a published tree
    # -- the evidence bundle AND the registration evidence, the report, the
    # approval and the catalog, which used to be written past it. It refuses
    # rather than scrubs: a scrub would leave a clean-looking bundle and no way
    # to tell which artifact leaked, and the leak would recur on the next run.
    published = published_artifacts(
        slug=slug, artifacts=artifacts, evidence=evidence, report=report,
        approval=approval, catalog=catalog)
    refuse_host_identity(published)
    _write_bundle(harness_root, published)

    print(f"attested  : {len(result['attestations'])} container executions")
    print(f"signed    : {approval.actor_id} ({approval.actor_kind})")
    print(f"written   : {evidence_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)

    runner = sub.add_parser(
        "controls",
        help="run the control sequence and write its attestations; no signature")
    runner.add_argument("--container-root", type=Path, required=True,
                        help="the private directory holding the pinned SIF")
    runner.add_argument("--output-dir", type=Path, required=True,
                        help="where the attestation bundle is written. It may "
                             "not be inside config/harnesses/.")
    runner.add_argument("--manifest", default="hpc_gemm_problem_correctness.yaml",
                        help="file name under config/harnesses/builtin/")
    runner.set_defaults(func=controls)

    promoter = sub.add_parser(
        "promote",
        help="run the sequence, earn the gates and sign the re-registration")
    promoter.add_argument("--container-root", type=Path, required=True)
    promoter.add_argument("--manifest", default="hpc_gemm_problem_correctness.yaml")
    promoter.add_argument("--actor-id", required=True,
                          help="the human maintainer authorizing the promotion")
    promoter.add_argument("--authorization-basis", required=True,
                          help="what the maintainer actually saw. A basis "
                               "claiming a review that did not happen is the "
                               "defect the signature exists to prevent.")
    promoter.add_argument("--approved-date", required=True)
    promoter.add_argument("--runs", type=int, default=3,
                          help="parity-probe repetitions behind the stability "
                               "gate; fewer than two cannot show stability")
    promoter.add_argument("--harness-root", type=Path, default=HARNESS_ROOT,
                          help="where the bundle, report, approval and catalog "
                               "row are written. Defaults to the repository's "
                               "config/harnesses; point it at a copy to "
                               "rehearse the write path first.")
    promoter.set_defaults(func=promote)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ControlSequenceError as exc:
        print(f"REFUSED: {exc}")
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
