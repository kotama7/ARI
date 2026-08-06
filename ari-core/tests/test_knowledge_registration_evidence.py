from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ari.knowledge.catalog import load_knowledge_catalog
from ari.capability_binding.substitution import CapabilityAbstractionReportV1
from ari.knowledge.registration_models import KnowledgeProviderPortabilityEvidenceV1
from ari.protocols.integrity import bytes_digest


CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config" / "knowledge_skills"
PERFORMANCE_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "knowledge"
    / "intel_performance_patterns_clean_task.c"
)
HPC_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "knowledge" / "hpc_clean_tasks.c"
)


EVIDENCED = {
    "hpc.gemm.optimization": "pass",
    "hpc.spmm.optimization": "pass",
    "hpc.stencil.optimization": "pass",
    "intel.linux-perf": "pass",
    "intel.performance-patterns": "pass",
    "intel.phoronix-test-suite": "pass",
}

# Every entry is now imported from a pinned commit, so source_commit_pin no
# longer holds any of them back; only stencil's measured clean task does.
EXPECTED_STATUS = {
    "hpc.gemm.optimization": "verified",
    "hpc.spmm.optimization": "verified",
    "hpc.stencil.optimization": "verified",
    "intel.linux-perf": "verified",
    "intel.performance-patterns": "verified",
    "intel.phoronix-test-suite": "verified",
}

EXPECTED_DECISION = {
    "hpc.gemm.optimization": "eligible-for-verified",
    "hpc.spmm.optimization": "eligible-for-verified",
    "hpc.stencil.optimization": "eligible-for-verified",
    "intel.linux-perf": "eligible-for-verified",
    "intel.performance-patterns": "eligible-for-verified",
    "intel.phoronix-test-suite": "eligible-for-verified",
}


def test_registration_evidence_is_digest_bound_and_does_not_promote():
    loaded = load_knowledge_catalog(CONFIG_ROOT / "catalog.yaml")
    evidence = {
        item.skill_ref.id: item for item in loaded.registration_evidence.values()
    }
    entries = {
        item.manifest.id: item
        for item in loaded.snapshot.entries
        if item.manifest.id in evidence
    }

    assert set(entries) == set(evidence) == set(EVIDENCED)
    for skill_id, expected in EVIDENCED.items():
        assert evidence[skill_id].clean_task.status == expected

    for skill_id, entry in entries.items():
        report = loaded.registration_reports[entry.registration_report_digest]
        gates = {item.gate_id: item for item in report.gates}
        portability = evidence[skill_id].provider_portability
        # Status moves only through an explicit authenticated transition, so it
        # tracks the approvals on disk rather than the gate count.
        assert entry.status == EXPECTED_STATUS[skill_id]
        assert report.decision == EXPECTED_DECISION[skill_id]
        assert gates["clean_task"].passed == (
            evidence[skill_id].clean_task.status == "pass"
        )
        # Portability is decided by withdrawing the incumbent, not by counting
        # the Provider population.
        assert portability.method == "synthetic-substitution"
        assert portability.status == "pass"
        assert portability.abstraction_report_digest is not None
        assert gates["provider_portability"].passed is True
        # Every entry now attests a commit that actually contains its body.
        assert gates["source_commit_pin"].passed is True


def test_abstraction_reports_are_stored_and_bind_their_own_digest():
    """The recorded digest must be recomputable from a stored report."""

    loaded = load_knowledge_catalog(CONFIG_ROOT / "catalog.yaml")
    for item in loaded.registration_evidence.values():
        stem = item.skill_ref.id.replace(".", "_").replace("-", "_")
        stem = {"intel_linux_perf": "intel_linux_perf"}.get(stem, stem)
        path = CONFIG_ROOT / "evidence" / f"{stem}.abstraction.json"
        assert path.is_file(), path
        stored = CapabilityAbstractionReportV1.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        assert stored.report_digest == item.provider_portability.abstraction_report_digest
        assert stored.status == "passed"
        assert stored.provider_bound_capability_refs == ()


def test_intel_clean_task_evidence_artifact_drift_is_rejected(tmp_path: Path):
    copied = tmp_path / "knowledge_skills"
    shutil.copytree(CONFIG_ROOT, copied)
    artifact = copied / "evidence" / "intel_phoronix_test_suite.clean_task.json"
    document = json.loads(artifact.read_text(encoding="utf-8"))
    document["pts_version"] = "substituted"
    artifact.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="clean-task evidence artifact differs"):
        load_knowledge_catalog(copied / "catalog.yaml")


def test_portability_pass_requires_two_provider_bindings():
    with pytest.raises(ValueError, match="two Providers and two Binding Locks"):
        KnowledgeProviderPortabilityEvidenceV1(
            status="pass",
            provider_catalog_digest="sha256:" + "1" * 64,
            compatible_provider_ids=("ari.provider.coding",),
            binding_lock_digests=("sha256:" + "2" * 64,),
            detail="insufficient single-provider claim",
        )


def test_tracked_intel_evidence_contains_no_physical_node_identity():
    forbidden_keys = {"gpu_uuid", "hostname", "node_name", "physical_node_name"}
    for path in sorted((CONFIG_ROOT / "evidence").glob("intel_*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        stack = [document]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                assert forbidden_keys.isdisjoint(value)
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)


def test_performance_patterns_evidence_binds_its_independent_fixture():
    summary = json.loads(
        (
            CONFIG_ROOT / "evidence" / "intel_performance_patterns.clean_task.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["fixture_sha256"] == bytes_digest(PERFORMANCE_FIXTURE.read_bytes())
    assert summary["attachment_execution"] == "none"


def test_hpc_clean_task_evidence_binds_its_independent_fixture():
    """Each HPC record must name the exact task source it measured."""

    expected = bytes_digest(HPC_FIXTURE.read_bytes())
    for stem in (
        "hpc_gemm_optimization",
        "hpc_spmm_optimization",
        "hpc_stencil_optimization",
    ):
        summary = json.loads(
            (CONFIG_ROOT / "evidence" / f"{stem}.clean_task.json").read_text(
                encoding="utf-8"
            )
        )
        assert summary["task_source_sha256"] == expected
        assert summary["attachment_execution"] == "none"
        assert summary["independently_authored_baseline"] is True
        assert summary["node_identifier_persisted"] is False
