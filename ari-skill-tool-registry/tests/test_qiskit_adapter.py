"""Qiskit catalog, local/remote lifecycle, artifacts, and replay tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import qiskit_local
import qiskit_remote
from broker import CatalogBroker
from catalog import build_catalog
from providers import ProviderProtocolError, ProviderToolV1
from qiskit_adapter import QiskitExperimentAdapter
from qiskit_fixtures import (
    FakeQiskitCore,
    FakeQiskitRuntime,
    adapter,
    experiment_profile,
    source_spec,
    write_fake_worker,
)
from sources import QiskitCatalogSource
from storage import CassetteStore, RegistryArtifactStore


async def _adapter_result(
    adapter_value: QiskitExperimentAdapter, handle_id: str
) -> dict:
    for _ in range(200):
        response = await adapter_value.get_result(None, handle_id)
        structured = response.structured or {}
        if structured.get("status") not in {"submitted", "running"}:
            return structured
        await asyncio.sleep(0.01)
    raise AssertionError("Qiskit adapter did not reach a terminal state")


async def _broker_result(broker: CatalogBroker, handle: dict) -> dict:
    for _ in range(200):
        result = await broker.get_result(handle)
        if result["status"] not in {"submitted", "running"}:
            return result
        await asyncio.sleep(0.01)
    raise AssertionError("Qiskit broker operation did not reach a terminal state")


@pytest.mark.asyncio
async def test_catalog_keeps_four_quantum_capabilities_and_backend_independence(
    tmp_path: Path,
) -> None:
    profiles = [
        experiment_profile(tmp_path / "ideal", kind="local-ideal"),
        experiment_profile(tmp_path / "noisy", kind="local-noisy"),
        experiment_profile(tmp_path / "remote", kind="remote-simulator"),
        experiment_profile(tmp_path / "hardware", kind="ibm-hardware"),
        experiment_profile(
            tmp_path / "ideal-second",
            kind="local-ideal",
            profile_id="local-ideal-second",
        ),
    ]
    spec = source_spec(tmp_path / "providers", profiles)
    runtime = FakeQiskitRuntime(profiles[3])
    adapter_value = adapter(
        spec,
        core=FakeQiskitCore(),
        runtime=runtime,
    )
    result = await build_catalog(
        [QiskitCatalogSource(spec, adapter=adapter_value, verify_source=False)]
    )

    assert len(result.lock.tools) == 5
    assert {item.level for item in result.lock.admissions} == {
        "scientifically_admitted"
    }
    assert {item.capability_ref for item in result.lock.tools} == {
        "ari.quantum.sample.local-ideal",
        "ari.quantum.sample.local-noisy",
        "ari.quantum.sample.remote-simulator",
        "ari.quantum.sample.ibm-hardware",
    }
    ideal = [
        item
        for item in result.lock.tools
        if item.capability_ref == "ari.quantum.sample.local-ideal"
    ]
    assert len({item.independence_group for item in ideal}) == 1
    assert any(
        item.relationship == "same-backend"
        and item.capability_ref == "ari.quantum.sample.local-ideal"
        for item in result.lock.overlaps
    )
    noisy = next(
        item
        for item in result.lock.tools
        if item.capability_ref == "ari.quantum.sample.local-noisy"
    )
    assert noisy.semantics["backend"]["noise_model"]["kind"] == ("depolarizing-readout")
    assert noisy.units["noise.two_qubit_error"] == "1"
    hardware = next(
        item
        for item in result.lock.tools
        if item.capability_ref == "ari.quantum.sample.ibm-hardware"
    )
    assert hardware.side_effects == "stateful"
    assert hardware.permissions == [
        "network",
        "process",
        "workspace-read",
        "workspace-write",
    ]
    assert hardware.units["calibration.t1"] == "us"


@pytest.mark.asyncio
async def test_local_seeded_run_captures_raw_evidence_and_replays_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = experiment_profile(tmp_path / "profile")
    spec = source_spec(tmp_path / "providers", [profile])
    fake_worker = tmp_path / "fake-qiskit-worker.py"
    write_fake_worker(fake_worker)
    monkeypatch.setattr(qiskit_local, "_WORKER", fake_worker)
    artifacts = RegistryArtifactStore(tmp_path / "ear" / "catalog")
    cassettes = CassetteStore(tmp_path / "cassettes", artifact_store=artifacts)
    core = FakeQiskitCore()
    adapter_value = adapter(
        spec,
        core=core,
        artifact_store=artifacts,
    )
    catalog = await build_catalog(
        [QiskitCatalogSource(spec, adapter=adapter_value, verify_source=False)]
    )
    descriptor = catalog.lock.tools[0]
    broker = CatalogBroker(
        catalog.lock,
        index=catalog.index,
        adapters={spec.source_id: adapter_value},
        artifact_store=artifacts,
        cassette_store=cassettes,
    )

    submitted = await broker.invoke(
        descriptor.tool_ref, {"request_id": "seeded-record"}, mode="record"
    )
    handle = submitted["structured_content"]["registry_handle"]
    completed = await _broker_result(broker, handle)

    assert completed["status"] == "ok"
    structured = completed["structured_content"]
    assert structured["counts"] == {"00": 2046, "11": 2050}
    assert structured["seed_simulator"] == 20260802
    assert structured["method_digest"] == profile.method_digest
    assert structured["effective_method_digest"].startswith("sha256:")
    assert {item["logical_role"] for item in completed["artifacts"]} == {
        "qiskit-execution-transcript",
        "qiskit-input-circuit-qpy",
        "qiskit-raw-aer-result",
        "qiskit-transpiled-circuit-qpy",
    }
    assert len({item["logical_name"] for item in completed["artifacts"]}) == 4
    assert len(core.calls) == 1
    assert len(cassettes.list_records()) == 1

    class OfflineAdapter:
        async def invoke(self, name, arguments):
            raise AssertionError("offline replay must not contact Qiskit")

    offline = CatalogBroker(
        catalog.lock,
        index=catalog.index,
        adapters={spec.source_id: OfflineAdapter()},
        artifact_store=artifacts,
        cassette_store=cassettes,
    )
    replayed = await offline.invoke(
        descriptor.tool_ref, {"request_id": "seeded-record"}, mode="replay"
    )
    assert replayed["status"] == "ok"
    assert replayed["artifacts"] == completed["artifacts"]
    assert replayed["structured_content"]["counts"] == structured["counts"]
    assert "_registry_replay" in replayed["structured_content"]


@pytest.mark.asyncio
async def test_remote_submit_poll_result_snapshot_and_closed_tool_subset(
    tmp_path: Path,
) -> None:
    profile = experiment_profile(tmp_path / "profile", kind="remote-simulator")
    spec = source_spec(tmp_path / "providers", [profile])
    runtime = FakeQiskitRuntime(profile, states=["QUEUED", "DONE"])
    artifacts = RegistryArtifactStore(tmp_path / "artifacts")
    adapter_value = adapter(
        spec,
        core=FakeQiskitCore(),
        runtime=runtime,
        artifact_store=artifacts,
    )
    leaf = QiskitExperimentAdapter.leaf_name(profile.profile_id)
    submitted = await adapter_value.invoke(leaf, {"request_id": "runtime-result"})
    handle_id = str((submitted.structured or {})["handle_id"])
    duplicate = await adapter_value.invoke(leaf, {"request_id": "runtime-result"})
    assert (duplicate.structured or {})["handle_id"] == handle_id
    completed = await _adapter_result(adapter_value, handle_id)

    assert completed["status"] == "completed"
    assert completed["remote_job_id"] == "runtime-job-fixture"
    assert completed["counts"] == {"00": 2046, "11": 2050}
    assert completed["backend_snapshot"]["snapshot_digest"].startswith("sha256:")
    assert completed["backend_snapshot"]["target_digest"] == (
        profile.backend.target.target_digest
    )
    assert completed["raw_result"]["captured"] is True
    called_names = {name for name, _arguments in runtime.calls}
    assert called_names <= {
        "active_instance_info_tool",
        "cancel_job_tool",
        "get_backend_calibration_tool",
        "get_backend_properties_tool",
        "get_coupling_map_tool",
        "get_job_results_tool",
        "get_job_status_tool",
        "run_sampler_tool",
        "setup_ibm_quantum_account_tool",
    }
    assert "delete_saved_account_tool" not in called_names
    assert sum(name == "run_sampler_tool" for name, _ in runtime.calls) == 1
    rendered = json.dumps(completed, sort_keys=True)
    assert "QISKIT_IBM_TOKEN" not in rendered
    assert "crn:v1" not in rendered
    roles = {item["logical_role"] for item in completed["_ari_result_artifacts"]}
    assert {
        "qiskit-backend-snapshot",
        "qiskit-execution-transcript",
        "qiskit-raw-runtime-result",
    } <= roles


@pytest.mark.asyncio
async def test_remote_cancel_during_submission_does_not_orphan_job(
    tmp_path: Path,
) -> None:
    profile = experiment_profile(tmp_path / "profile", kind="ibm-hardware")
    spec = source_spec(tmp_path / "providers", [profile])
    runtime = FakeQiskitRuntime(profile, block_submission=True)
    adapter_value = adapter(
        spec,
        core=FakeQiskitCore(),
        runtime=runtime,
    )
    leaf = QiskitExperimentAdapter.leaf_name(profile.profile_id)
    submitted = await adapter_value.invoke(leaf, {"request_id": "cancel-race"})
    handle_id = str((submitted.structured or {})["handle_id"])
    await asyncio.wait_for(runtime.submission_entered.wait(), timeout=2)
    cancellation = asyncio.create_task(adapter_value.cancel(None, handle_id))
    await asyncio.sleep(0)
    runtime.release_submission.set()
    response = await asyncio.wait_for(cancellation, timeout=2)

    assert (response.structured or {})["status"] == "cancelled"
    assert runtime.cancelled is True
    assert any(name == "cancel_job_tool" for name, _ in runtime.calls)


@pytest.mark.asyncio
async def test_backend_and_provider_surface_drift_fail_closed(
    tmp_path: Path,
) -> None:
    profile = experiment_profile(tmp_path / "profile", kind="ibm-hardware")
    spec = source_spec(tmp_path / "providers", [profile])
    mismatch = FakeQiskitRuntime(profile, backend_mismatch=True)
    adapter_value = adapter(
        spec,
        core=FakeQiskitCore(),
        runtime=mismatch,
    )
    leaf = QiskitExperimentAdapter.leaf_name(profile.profile_id)
    submitted = await adapter_value.invoke(leaf, {"request_id": "backend-drift"})
    failed = await _adapter_result(
        adapter_value, str((submitted.structured or {})["handle_id"])
    )
    assert failed["status"] == "failed"
    assert "backend properties differ" in failed["error"]

    class DriftingCore(FakeQiskitCore):
        async def list_tools(self):
            return [ProviderToolV1(name="transpile_circuit_tool")]

    drift_adapter = adapter(
        spec,
        core=DriftingCore(),
        runtime=FakeQiskitRuntime(profile),
    )
    with pytest.raises(ProviderProtocolError, match="tool surface drifted"):
        await drift_adapter.list_tools()


@pytest.mark.asyncio
async def test_remote_timeout_requests_cancel_and_returns_terminal_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic = 100.0
    monkeypatch.setattr(qiskit_remote.time, "monotonic", lambda: monotonic)
    profile = experiment_profile(
        tmp_path / "profile", kind="remote-simulator", scientific=False
    )
    spec = source_spec(tmp_path / "providers", [profile])
    runtime = FakeQiskitRuntime(profile, states=["RUNNING"])
    adapter_value = adapter(
        spec,
        core=FakeQiskitCore(),
        runtime=runtime,
    )
    leaf = QiskitExperimentAdapter.leaf_name(profile.profile_id)
    submitted = await adapter_value.invoke(leaf, {"request_id": "runtime-timeout"})
    handle_id = str((submitted.structured or {})["handle_id"])
    await asyncio.wait_for(runtime.submission_entered.wait(), timeout=2)
    for _ in range(100):
        if adapter_value._job(handle_id).remote_job_id is not None:
            break
        await asyncio.sleep(0.01)
    monotonic = 106.0
    response = await adapter_value.get_status(None, handle_id)
    structured = response.structured or {}
    assert structured["status"] == "failed"
    assert "timed out" in structured["error"]
    assert runtime.cancelled is True
