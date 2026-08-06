from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ari.knowledge.catalog import load_knowledge_catalog
from ari.knowledge.registration_models import KnowledgeProviderPortabilityEvidenceV1
from ari.protocols.integrity import bytes_digest


CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config" / "knowledge_skills"
PERFORMANCE_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "knowledge"
    / "intel_performance_patterns_clean_task.c"
)


def test_intel_registration_evidence_is_digest_bound_and_does_not_promote():
    loaded = load_knowledge_catalog(CONFIG_ROOT / "catalog.yaml")
    entries = {
        item.manifest.id: item
        for item in loaded.snapshot.entries
        if item.manifest.id.startswith("intel.")
    }
    evidence = {
        item.skill_ref.id: item for item in loaded.registration_evidence.values()
    }

    assert (
        set(entries)
        == set(evidence)
        == {
            "intel.linux-perf",
            "intel.performance-patterns",
            "intel.phoronix-test-suite",
        }
    )
    assert evidence["intel.linux-perf"].clean_task.status == "unsatisfied"
    assert evidence["intel.performance-patterns"].clean_task.status == "pass"
    assert evidence["intel.phoronix-test-suite"].clean_task.status == "pass"

    for skill_id, entry in entries.items():
        report = loaded.registration_reports[entry.registration_report_digest]
        gates = {item.gate_id: item for item in report.gates}
        assert entry.status == "candidate"
        assert report.decision == "candidate"
        assert gates["clean_task"].passed == (
            evidence[skill_id].clean_task.status == "pass"
        )
        assert gates["provider_portability"].passed is False
        assert (
            evidence[skill_id].provider_portability.status
            == "not_applicable_no_second_provider"
        )


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
