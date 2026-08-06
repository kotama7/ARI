"""Read-only dashboard projection keeps K/C/A identities separate."""

from __future__ import annotations

import json

from ari.viz import api_kca


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_kca_dashboard_projection_is_separate_and_read_only(tmp_path, monkeypatch):
    admission = tmp_path / "rqgm" / "kca" / "admission-v1"
    _write(admission / "run_admission.json", {
        "run_id": tmp_path.name,
        "modes": {"knowledge": "enforce", "capability_binding": "enforce", "assurance": "enforce"},
        "provider_lock_digest": "sha256:" + "1" * 64,
    })
    _write(admission / "knowledge_catalog_snapshot.json", {
        "snapshot_digest": "sha256:" + "2" * 64,
        "entries": [{"manifest": {"id": "hpc.gemm", "version": "1.0.0"}, "status": "verified"}],
    })
    _write(admission / "provider_catalog_snapshot.json", {
        "snapshot_digest": "sha256:" + "3" * 64,
        "providers": [{"provider_id": "ari.coding", "provider_status": "verified"}],
    })
    _write(admission / "harness_catalog_snapshot.json", {
        "snapshot_digest": "sha256:" + "4" * 64,
        "manifests": [{"id": "hpc/gemm-correctness", "status": "verified"}],
    })
    _write(admission / "capability_binding_lock.json", {
        "lock_digest": "sha256:" + "5" * 64,
        "bindings": [{"capability_ref": "ari.execution.run/v1"}],
        "unsatisfied": [],
    })
    _write(admission / "verification_contract.json", {
        "contract_digest": "sha256:" + "6" * 64,
        "requirements": [{"property_id": "numerical-equivalence"}],
    })
    monkeypatch.setattr(api_kca, "_resolve_checkpoint_dir", lambda _run_id: tmp_path)

    result = api_kca._api_checkpoint_kca("run-x")

    assert result["present"] is True
    assert result["knowledge"]["catalog_entries"][0]["manifest"]["id"] == "hpc.gemm"
    assert result["providers"]["catalog_entries"][0]["provider_id"] == "ari.coding"
    assert result["assurance"]["catalog_entries"][0]["id"] == "hpc/gemm-correctness"
    assert not ({"catalog_entries"} & set(result))
    assert result["degraded_reasons"] == []


def test_kca_dashboard_projection_rejects_symlinked_document(tmp_path, monkeypatch):
    outside = tmp_path.parent / (tmp_path.name + "-outside.json")
    outside.write_text("{}", encoding="utf-8")
    admission = tmp_path / "rqgm" / "kca" / "admission-v1"
    admission.mkdir(parents=True)
    (admission / "run_admission.json").symlink_to(outside)
    monkeypatch.setattr(api_kca, "_resolve_checkpoint_dir", lambda _run_id: tmp_path)

    result = api_kca._api_checkpoint_kca("run-x")

    assert result["present"] is False
    assert result["knowledge"] != result["providers"]
    assert result["providers"] != result["assurance"]
