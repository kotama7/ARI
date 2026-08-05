from __future__ import annotations

from types import SimpleNamespace

from ari.assurance.models import (
    HarnessAttestationV1,
    HarnessPropertyResultV1,
    VerificationScopeV1,
)
from ari.manuscript.builder import _lane
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
