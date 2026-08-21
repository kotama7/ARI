from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import ari.assurance
import ari.pipeline.claim_gate
from ari.assurance.models import (
    HarnessAttestationV1,
    HarnessPropertyResultV1,
    VerificationScopeV1,
)
from ari.manuscript.builder import _lane
from ari.manuscript.contracts import (
    ManuscriptAuthoringBindingV1,
    ManuscriptReadinessReportV1,
    RequirementResultV1,
)
from ari.manuscript.publication import build_publication_decision
from ari.manuscript.snapshot import build_exploration_snapshot


SHA = "sha256:" + "a" * 64


def _attestation(*, node_id: str = "node-1", tier: str = "certify"):
    return HarnessAttestationV1.create(
        run_id="run-1",
        node_id=node_id,
        epoch_id="epoch-000",
        producer_epoch_id="epoch-000",
        research_contract_digest=SHA,
        verification_contract_digest=SHA,
        knowledge_skill_use_digest=SHA,
        capability_binding_lock_digest=SHA,
        baseline_harness_lock_digest=SHA,
        active_harness_lock_digest=SHA,
        harness_manifest_digest=SHA,
        driver_digest=SHA,
        oracle_digest=SHA,
        dataset_digest=SHA,
        container_digest=SHA,
        target_logical_name="candidate.so",
        target_digest=SHA,
        target_kind="shared-library",
        execution_identity=SHA,
        execution_result_digest=SHA,
        verdict="pass",
        property_results=(
            HarnessPropertyResultV1(
                property_id="numerical-equivalence",
                method="differential-testing",
                tier=tier,
                tested_scope=VerificationScopeV1(
                    values={
                        "language": ("c",),
                        "hardware": ("cpu",),
                        "dtype": ("float64",),
                    }
                ),
                verdict="pass",
                covered_atom_digests=(SHA,),
                evidence_artifact_refs=(),
            ),
        ),
        evidence_artifact_refs=(),
        infrastructure_status="ready",
        nondeterminism_declaration="none",
        nondeterminism_observations=(),
        attempt_id="attempt-1",
        retry_index=0,
    )


def _node(*, attestation_ref: str, target_digest: str = SHA):
    return SimpleNamespace(
        id="node-1",
        parent_id=None,
        ancestor_ids=[],
        depth=0,
        status="success",
        label="validation",
        name="candidate",
        original_direction=None,
        has_real_data=True,
        metrics={"_scientific_score": 1.0},
        assurance_status="pass",
        assurance_tier="certify",
        frontier_class="scientific_frontier",
        attestation_refs=[attestation_ref],
        verified_target_digest=target_digest,
        property_verdicts={"numerical-equivalence": "pass"},
        artifacts=[],
        error_log=None,
    )


def test_only_exact_target_certify_attestation_makes_node_publishable(tmp_path):
    relative = "rqgm/kca/nodes/node-1/attestations/certify.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(_attestation().model_dump_json(), encoding="utf-8")

    snapshot = build_exploration_snapshot(
        tmp_path,
        [_node(attestation_ref=relative)],
        exploration_mode="ari_rqgm",
    )

    node = snapshot.nodes[0]
    assert len(node.certify_attestation_item_ids) == 1
    assert _lane(node, "enforce")[0] == "publishable"
    attestation = next(
        item for item in snapshot.artifacts if item.kind == "harness-attestation"
    )
    assert attestation.status == "present"
    assert attestation.metadata["certify_pass"] is True


def test_screen_attestation_is_valid_evidence_but_not_publication_certification(tmp_path):
    relative = "rqgm/kca/nodes/node-1/attestations/screen.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        _attestation(tier="screen").model_dump_json(), encoding="utf-8"
    )

    snapshot = build_exploration_snapshot(
        tmp_path,
        [_node(attestation_ref=relative)],
        exploration_mode="ari_rqgm",
    )

    node = snapshot.nodes[0]
    attestation = next(
        item for item in snapshot.artifacts if item.kind == "harness-attestation"
    )
    assert attestation.status == "present"
    assert attestation.metadata["certify_pass"] is False
    assert node.certify_attestation_item_ids == ()
    assert _lane(node, "enforce")[0] == "exploratory"


def test_stale_target_attestation_remains_visible_but_cannot_publish(tmp_path):
    relative = "rqgm/kca/nodes/node-1/attestations/stale.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(_attestation().model_dump_json(), encoding="utf-8")

    different_target = "sha256:" + "b" * 64
    snapshot = build_exploration_snapshot(
        tmp_path,
        [_node(attestation_ref=relative, target_digest=different_target)],
        exploration_mode="ari_rqgm",
    )

    node = snapshot.nodes[0]
    attestation = next(
        item for item in snapshot.artifacts if item.kind == "harness-attestation"
    )
    assert attestation.status == "stale"
    assert attestation.metadata["target_matches"] is False
    assert node.certify_attestation_item_ids == ()
    assert _lane(node, "enforce")[0] == "exploratory"


# ── criterion 58: the claim gate and the program verifier are independent ────


D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
D3 = "sha256:" + "3" * 64
D4 = "sha256:" + "4" * 64


def _publication_binding_and_readiness():
    """One publication-ready manuscript, so only the two gates below vary."""

    readiness = ManuscriptReadinessReportV1.create(
        run_id="run-independence",
        profile_digest=D1,
        context_digest=D2,
        evaluator_version="manuscript-evaluator-v1",
        requirement_results=(
            RequirementResultV1(
                requirement_id="MC-TEST-READY",
                applicable=True,
                status="satisfied",
                reason_code="evidence_present",
                authoring_blocking=False,
                publication_blocking=True,
                evaluator_version="manuscript-evaluator-v1",
            ),
        ),
        authoring_verdict="ready",
        publication_verdict="ready",
        counts={"satisfied": 1, "not_applicable": 0, "unavailable": 0, "missing": 0},
    )
    binding = ManuscriptAuthoringBindingV1.create(
        run_id="run-independence",
        attempt_id="mca-independence",
        source_snapshot_digest=D3,
        profile_digest=D1,
        context_digest=D2,
        readiness_digest=readiness.readiness_digest,
        brief_bundle_digest=D4,
        paper_mode="linear",
        backend_version="linear-manuscript-v1",
        target_build_id="paper-run-independence",
        target_build_revision=0,
    )
    return binding, readiness


def _decision(*, claim_passed: bool, assurance_passed: bool | None):
    """The publication decision with every gate but the two of interest green."""

    binding, readiness = _publication_binding_and_readiness()
    return build_publication_decision(
        run_id="run-independence",
        attempt_id="mca-independence",
        paper_build_digest=D1,
        binding=binding,
        readiness=readiness,
        claim_gate_passed=claim_passed,
        claim_gate_digest=CLAIM_DIGEST,
        assurance_required=True,
        assurance_passed=assurance_passed,
        assurance_artifact_digests=ASSURANCE_DIGESTS,
        compile_passed=True,
        compile_digest=D3,
        reproduction_passed=True,
        reproduction_digest=D4,
        inputs_fresh=True,
    )


CLAIM_DIGEST = "sha256:" + "c" * 64
ASSURANCE_DIGESTS = ("sha256:" + "e" * 64, "sha256:" + "f" * 64)


def _gate(decision, name: str):
    return next(item for item in decision.subverdicts if item.gate == name)


def _dotted_imports(path: Path) -> set[str]:
    """Every absolute module name *path* imports, including inside functions."""

    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _package_reaches(package_dir: Path, target: str) -> set[str]:
    """Files under *package_dir* that import ``target`` or a submodule of it."""

    sources = sorted(package_dir.rglob("*.py"))
    assert sources, f"the import scanner found no source under {package_dir}"
    return {
        str(path.relative_to(package_dir))
        for path in sources
        if any(
            name == target or name.startswith(f"{target}.")
            for name in _dotted_imports(path)
        )
    }


def test_claim_and_program_gates_independent():
    """Task 20 criterion 58: two hard gates, and neither can satisfy the other.

    Task 19 section 14 states the requirement as "program correctness and claim
    consistency remain two independent hard gates.  Neither can satisfy the
    other."  A merged implementation would not look broken from either side:
    the failure it produces is a paper whose numbers were transcribed correctly
    from a computation nobody verified, or a certified artifact whose paper says
    something the certificate never covered.  Both read as ``publishable``.

    Independence is asserted three ways, because it can be lost at three
    different places: the decision (one gate's pass covering the other's fail),
    the evidence (one gate's artifact standing in for the other's), and the code
    (one gate importing the other and inheriting its verdict).  The gate
    inventory is taken from a real decision rather than written out here, so a
    gate added to ``PublicationDecisionV1`` later cannot quietly avoid the
    "nothing else was implicated" check below.
    """

    clean = _decision(claim_passed=True, assurance_passed=True)
    gates = {item.gate for item in clean.subverdicts}
    assert gates, "the publication decision emitted no gates"
    assert {"claim_evidence", "assurance"} <= gates
    assert clean.decision == "publishable"

    # 1. Neither gate's pass rescues the other's fail, and neither failure
    #    implicates any other gate.
    claim_failed = _decision(claim_passed=False, assurance_passed=True)
    assert claim_failed.decision == "blocked"
    assert _gate(claim_failed, "claim_evidence").status == "fail"
    assert _gate(claim_failed, "assurance").status == "pass"
    assert {
        item.gate for item in claim_failed.subverdicts if item.status == "fail"
    } == {"claim_evidence"}

    assurance_failed = _decision(claim_passed=True, assurance_passed=False)
    assert assurance_failed.decision == "blocked"
    assert _gate(assurance_failed, "assurance").status == "fail"
    assert _gate(assurance_failed, "claim_evidence").status == "pass"
    assert {
        item.gate for item in assurance_failed.subverdicts if item.status == "fail"
    } == {"assurance"}

    # An unknown certification is a failed one: "the Harness never ran" must not
    # be readable as "the claim gate already covered it".
    unknown = _decision(claim_passed=True, assurance_passed=None)
    assert unknown.decision == "blocked"
    assert _gate(unknown, "assurance").status == "fail"
    assert _gate(unknown, "claim_evidence").status == "pass"

    # 2. The two gates cite different evidence.  A shared reason code or a
    #    shared artifact digest would mean one record answers for both.
    assert not set(_gate(claim_failed, "claim_evidence").reason_codes) & set(
        _gate(assurance_failed, "assurance").reason_codes
    )
    assert _gate(clean, "claim_evidence").artifact_digests == (CLAIM_DIGEST,)
    assert _gate(clean, "assurance").artifact_digests == ASSURANCE_DIGESTS
    for subverdict in clean.subverdicts:
        if subverdict.gate != "claim_evidence":
            assert CLAIM_DIGEST not in subverdict.artifact_digests
        if subverdict.gate != "assurance":
            assert not set(ASSURANCE_DIGESTS) & set(subverdict.artifact_digests)

    # 3. The implementations do not know about each other.  Scanned over every
    #    module in both packages rather than a chosen few, so a new file cannot
    #    open the coupling unseen.
    claim_package = Path(ari.pipeline.claim_gate.__file__).parent
    assurance_package = Path(ari.assurance.__file__).parent
    assert _package_reaches(claim_package, "ari.assurance") == set()
    assert _package_reaches(assurance_package, "ari.pipeline.claim_gate") == set()
    # The scanner can see a dependency: each package does reach its own gate.
    assert _package_reaches(claim_package, "ari.pipeline.claim_gate")
    assert _package_reaches(assurance_package, "ari.assurance")
