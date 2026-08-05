#!/usr/bin/env python3
"""Promote the exact credential-free Qiskit local-Aer profile."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent
for dependency in (REPO_ROOT / "ari-core", PACKAGE_ROOT / "src"):
    if str(dependency) not in sys.path:
        sys.path.insert(0, str(dependency))

from ari.providers.models import ProviderRegistrationGateV1  # noqa: E402
from ari.providers.registration import (  # noqa: E402
    PROVIDER_REGISTRATION_GATES,
    registration_report,
)
from models import AdmissionEvidenceV1, sha256_digest  # noqa: E402
from providers import (  # noqa: E402
    ProviderProtocolError,
    PythonStdioLauncherV1,
    StdioMCPAdapter,
    provider_digest,
)
from qiskit_adapter import (  # noqa: E402
    QiskitCircuitV1,
    QiskitExperimentAdapter,
    QiskitExperimentV1,
    QiskitLocalBackendV1,
    QiskitMitigationV1,
    QiskitOutcomeExpectationV1,
    QiskitProviderPinV1,
    QiskitSoftwareV1,
    QiskitTargetV1,
    QiskitTranspilationV1,
    qiskit_effective_launcher,
    qiskit_provider_release_pin,
    qiskit_software_stack_digest,
    verify_qiskit_experiment_files,
    verify_qiskit_provider_package,
)
from qiskit_identity import verify_qiskit_python_distributions  # noqa: E402
from qiskit_promotion import (  # noqa: E402
    QISKIT_VERIFIED_EVIDENCE_SCHEMA,
    QISKIT_VERIFIED_LOCK_SCHEMA,
    QISKIT_VERIFIED_MANIFEST_SCHEMA,
    QISKIT_VERIFIED_PROVIDER_ID,
    QISKIT_VERIFIED_PROVIDER_VERSION,
    qiskit_verified_adapter,
    qiskit_verified_artifact,
    qiskit_verified_runtime_target,
    qiskit_verified_scope,
    verify_qiskit_verified_lock,
)
from qiskit_verification import validate_qiskit_counts  # noqa: E402
from storage import RegistryArtifactStore  # noqa: E402


TEST_IDS = (
    "ari-skill-tool-registry/tests/test_qiskit_contracts.py",
    "ari-skill-tool-registry/tests/test_qiskit_adapter.py",
    "ari-skill-tool-registry/tests/test_qiskit_worker.py",
    "ari-skill-tool-registry/tests/test_stdio_adapter.py::test_stdio_timeout_reaps_the_provider_process_group",
)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _launcher(args: argparse.Namespace) -> PythonStdioLauncherV1:
    return PythonStdioLauncherV1(
        python_executable=os.path.abspath(args.core_python),
        package_root=str(Path(args.core_package_root).resolve()),
        python_module="qiskit_mcp_server",
        python_callable="main",
        expected_architecture="x86_64",
        identity_globs=[
            "**/*",
            "**/*.py",
            "*.lock",
            "pyproject.toml",
            "requirements*.txt",
        ],
    )


def _provisional_profile(qpy_path: Path) -> QiskitExperimentV1:
    target_material = {
        "num_qubits": 2,
        "basis_gates": ["cx", "id", "rz", "sx", "x"],
        "coupling_map": [[0, 1], [1, 0]],
    }
    return QiskitExperimentV1(
        profile_id="local-ideal",
        description=(
            "Seeded Bell-state sampling on the digest-pinned local Qiskit Aer "
            "2.5.1/0.17.2 CPU profile."
        ),
        software=QiskitSoftwareV1(
            qiskit_aer_version="0.17.2",
            stack_digest=qiskit_software_stack_digest(
                {"qiskit": "2.5.1", "qiskit-aer": "0.17.2"}
            ),
        ),
        circuit=QiskitCircuitV1(
            qpy_path=str(qpy_path.resolve()),
            qpy_digest=_file_digest(qpy_path),
            qpy_version=qpy_path.read_bytes()[6],
            num_qubits=2,
            num_clbits=2,
        ),
        transpilation=QiskitTranspilationV1(
            optimization_level=1,
            seed_transpiler=731,
            initial_layout=[0, 1],
        ),
        backend=QiskitLocalBackendV1(
            kind="local-ideal",
            target=QiskitTargetV1(
                **target_material,
                target_digest=sha256_digest(target_material),
            ),
            simulator_method="statevector",
            precision="double",
            device="CPU",
            max_parallel_threads=1,
        ),
        shots=4096,
        seed_simulator=20260802,
        mitigation=QiskitMitigationV1(),
        expected_outcomes=[
            QiskitOutcomeExpectationV1(
                bitstring="00", probability_min=0.45, probability_max=0.55
            ),
            QiskitOutcomeExpectationV1(
                bitstring="11", probability_min=0.45, probability_max=0.55
            ),
        ],
        max_unlisted_probability=0.0,
        limitations=[
            "The promotion applies only to this QPY, target, software stack, seeds, method, and shot count.",
            "A seeded Aer pass is not evidence about an IBM Quantum hardware backend.",
        ],
        timeout_seconds=3600,
        poll_interval_seconds=0.1,
    )


async def _wait(adapter: QiskitExperimentAdapter, handle_id: str) -> dict[str, Any]:
    async with asyncio.timeout(600):
        while True:
            response = await adapter.get_result(None, handle_id)
            value = response.structured or {}
            if value.get("status") not in {"submitted", "running"}:
                return value
            await asyncio.sleep(0.1)


async def _live_observations(
    *,
    launcher: PythonStdioLauncherV1,
    pin: QiskitProviderPinV1,
    profile: QiskitExperimentV1,
    artifact_root: Path,
) -> dict[str, Any]:
    effective = qiskit_effective_launcher(launcher, "circuit")
    digest = provider_digest(effective)
    raw = StdioMCPAdapter(
        effective,
        expected_provider_digest=digest,
        timeout_seconds=120,
        max_pages=8,
        max_tools=32,
    )
    upstream = sorted(await raw.list_tools(), key=lambda item: item.name)
    adapter = QiskitExperimentAdapter(
        effective,
        core_provider_digest=digest,
        core_pin=pin,
        experiments=[profile],
        artifact_store=RegistryArtifactStore(artifact_root),
        allowed_leaf_names={QiskitExperimentAdapter.leaf_name(profile.profile_id)},
        timeout_seconds=120,
        verify_packages=False,
    )
    leaves = await adapter.list_tools()
    if len(leaves) != 1:
        raise ProviderProtocolError("Qiskit verified scope did not produce one leaf")
    submitted = await adapter.invoke(
        leaves[0].name, {"request_id": "promotion-local-ideal"}
    )
    handle_id = str((submitted.structured or {}).get("handle_id") or "")
    result = await _wait(adapter, handle_id)
    if result.get("status") != "completed":
        raise ProviderProtocolError(f"Qiskit local validation failed: {result}")
    counts = validate_qiskit_counts(profile, result.get("counts") or {})
    try:
        await adapter.invoke("ari_qiskit_sample__not_bound", {"request_id": "no"})
    except ProviderProtocolError:
        unbound_rejected = True
    else:
        raise ProviderProtocolError("unbound Qiskit profile invocation succeeded")
    return {
        "provider_digest_in_validation_environment": digest,
        "upstream_mcp_tools": [item.name for item in upstream],
        "upstream_mcp_schema_snapshot_digest": sha256_digest(
            [item.model_dump(mode="json") for item in upstream]
        ),
        "virtual_leaf": {
            "name": leaves[0].name,
            "input_schema_digest": sha256_digest(leaves[0].input_schema),
            "output_schema_digest": sha256_digest(leaves[0].output_schema),
        },
        "result": {
            "counts": counts,
            "shots": result["shots"],
            "experiment_digest": result["experiment_digest"],
            "method_digest": result["method_digest"],
            "result_digest": result["result_digest"],
        },
        "execution_artifact_refs": result.get("_ari_result_artifacts", []),
        "unbound_invocation_rejected": unbound_rejected,
    }


def _tests(test_python: str, qiskit_python: str) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["ARI_QISKIT_TEST_PYTHON"] = qiskit_python
    command = [test_python, "-m", "pytest", *TEST_IDS, "-q"]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        timeout=600,
    )
    output = completed.stdout + completed.stderr
    if completed.returncode:
        raise RuntimeError(output.decode("utf-8", errors="replace")[-12000:])
    return {
        "command": ["<test-python>", "-m", "pytest", *TEST_IDS, "-q"],
        "exit_code": 0,
        "output_sha256": "sha256:" + hashlib.sha256(output).hexdigest(),
        "test_ids": list(TEST_IDS),
    }


def _gate_evidence(
    *, manifest: dict[str, Any], observations: dict[str, Any], tests: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    common = {"test_output_sha256": tests["output_sha256"]}
    scope = manifest["capability_scope"]
    profile = scope["profiles"][0]
    return {
        "manifest_schema": {"schema": manifest["schema_version"], **common},
        "source_package_digest_pin": {
            "core_mcp": manifest["artifact"]["core_mcp"],
            "qiskit": manifest["artifact"]["qiskit"],
            "qiskit_aer": manifest["artifact"]["qiskit_aer"],
        },
        "live_tools_list_parity": {
            "upstream_tools": observations["upstream_mcp_tools"],
            "snapshot_digest": observations["upstream_mcp_schema_snapshot_digest"],
            "admitted_leaf": observations["virtual_leaf"]["name"],
        },
        "schema_digest_pin": observations["virtual_leaf"],
        "capability_contract_conformance": {
            "capability_ref": profile["capability_ref"],
            "experiment_digest": profile["experiment_digest"],
            "method_digest": profile["method_digest"],
        },
        "side_effect_declaration": {
            "side_effects": scope["side_effects"],
            "permissions": scope["permissions"],
        },
        "credential_scope": {
            "credential_scope_ids": [],
            "ibm_runtime_loaded": False,
            "ibm_backend_admitted": False,
        },
        "environment_allowlist": {
            "runtime_target": manifest["runtime_target"],
            "provider_digest": observations[
                "provider_digest_in_validation_environment"
            ],
        },
        "timeout_cancellation_process_group": {
            "bounded_timeout": 120,
            "test_ids": tests["test_ids"],
            **common,
        },
        "result_schema": observations["result"],
        "malicious_description_boundary": {
            "authority_source": "immutable profile and active catalog lock",
            **common,
        },
        "workspace_isolation": {
            "qpy_digest": profile["qpy_digest"],
            "artifact_refs": observations["execution_artifact_refs"],
        },
        "revocation_behavior": {
            "rule": "non-verified status is ineligible for enforce binding"
        },
        "schema_drift_detection": {
            "upstream_contract_digest": observations[
                "upstream_mcp_schema_snapshot_digest"
            ],
            "virtual_leaf_schema": observations["virtual_leaf"],
        },
        "unbound_invocation_rejection": {
            "live_adapter_check": observations["unbound_invocation_rejected"]
        },
    }


def _bundle(
    *,
    output: Path,
    captured_date: str,
    actor: str,
    pin: QiskitProviderPinV1,
    profile: QiskitExperimentV1,
    observations: dict[str, Any],
    tests: dict[str, Any],
) -> dict[str, str]:
    artifact = qiskit_verified_artifact(pin)
    scope = qiskit_verified_scope([profile])
    manifest = {
        "schema_version": QISKIT_VERIFIED_MANIFEST_SCHEMA,
        "provider_id": QISKIT_VERIFIED_PROVIDER_ID,
        "provider_version": QISKIT_VERIFIED_PROVIDER_VERSION,
        "artifact": artifact,
        "adapter": qiskit_verified_adapter(),
        "runtime_target": qiskit_verified_runtime_target(),
        "environment_policy": {
            "network": "deny",
            "credential_scope_ids": [],
            "device": "CPU",
            "max_parallel_threads": 1,
        },
        "capability_scope": scope,
    }
    manifest_digest = sha256_digest(manifest)
    gate_evidence = _gate_evidence(
        manifest=manifest, observations=observations, tests=tests
    )
    if tuple(gate_evidence) != PROVIDER_REGISTRATION_GATES:
        raise ValueError("Qiskit registration gates are incomplete or out of order")
    evidence = {
        "schema_version": QISKIT_VERIFIED_EVIDENCE_SCHEMA,
        "provider_id": QISKIT_VERIFIED_PROVIDER_ID,
        "provider_version": QISKIT_VERIFIED_PROVIDER_VERSION,
        "captured_date": captured_date,
        "artifact": artifact,
        "capability_scope": scope,
        "observations": observations,
        "test_run": tests,
        "gate_evidence": gate_evidence,
    }
    evidence["bundle_digest"] = sha256_digest(evidence)
    gates = tuple(
        ProviderRegistrationGateV1(
            gate_id=gate_id,
            passed=True,
            evidence_digest=sha256_digest(gate_evidence[gate_id]),
            detail="closed Qiskit local-Aer registration evidence passed",
        )
        for gate_id in PROVIDER_REGISTRATION_GATES
    )
    report = registration_report(
        provider_id=QISKIT_VERIFIED_PROVIDER_ID,
        manifest_sha256=manifest_digest,
        gates=gates,
    ).model_dump(mode="json")
    approval = {
        "schema_version": "ari.capability-provider-promotion-approval/v1",
        "provider_id": QISKIT_VERIFIED_PROVIDER_ID,
        "provider_version": QISKIT_VERIFIED_PROVIDER_VERSION,
        "from_status": "candidate",
        "to_status": "verified",
        "actor_kind": "human-maintainer",
        "actor_id": actor,
        "authorization_basis": "explicit-maintainer-approval",
        "approved_date": captured_date,
        "provider_manifest_digest": manifest_digest,
        "registration_report_digest": report["report_digest"],
        "evidence_bundle_digest": evidence["bundle_digest"],
        "capability_scope_digest": sha256_digest(scope),
    }
    approval["approval_digest"] = sha256_digest(approval)
    lock = {
        "schema_version": QISKIT_VERIFIED_LOCK_SCHEMA,
        "provider_id": QISKIT_VERIFIED_PROVIDER_ID,
        "provider_version": QISKIT_VERIFIED_PROVIDER_VERSION,
        "status": "verified",
        "artifact": artifact,
        "adapter": qiskit_verified_adapter(),
        "runtime_target": qiskit_verified_runtime_target(),
        "capability_scope": scope,
        "registration": {
            "provider_manifest_path": "provider-manifest-v1.json",
            "provider_manifest_digest": manifest_digest,
            "evidence_path": "registration-evidence-v1.json",
            "evidence_bundle_digest": evidence["bundle_digest"],
            "report_path": "registration-report-v1.json",
            "report_digest": report["report_digest"],
        },
        "promotion": {
            "approval_path": "promotion-approval-v1.json",
            "approval_digest": approval["approval_digest"],
        },
    }
    lock["lock_digest"] = sha256_digest(lock)
    for name, document in (
        ("provider-manifest-v1.json", manifest),
        ("registration-evidence-v1.json", evidence),
        ("registration-report-v1.json", report),
        ("promotion-approval-v1.json", approval),
        ("verified-lock-v1.json", lock),
    ):
        _write_json(output / name, document)
    verified = verify_qiskit_verified_lock(
        output / "verified-lock-v1.json",
        expected_lock_digest=lock["lock_digest"],
        core_pin=pin,
        experiments=[profile],
    )
    return {
        "lock_digest": verified["lock_digest"],
        "approval_digest": approval["approval_digest"],
        "report_digest": report["report_digest"],
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    qpy = output / "bell-phi-plus.qpy"
    shutil.copyfile(Path(args.qpy).resolve(strict=True), qpy)
    qpy.chmod(0o644)
    pin = QiskitProviderPinV1.model_validate(
        qiskit_provider_release_pin("circuit", "0.3.1")
    )
    launcher = _launcher(args)
    verify_qiskit_provider_package(launcher, pin)
    verify_qiskit_python_distributions(
        launcher,
        {"qiskit": "2.5.1", "qiskit-aer": "0.17.2", "qiskit-mcp-server": "0.3.1"},
    )
    profile = _provisional_profile(qpy)
    with tempfile.TemporaryDirectory(prefix="ari-qiskit-promotion-") as artifact_dir:
        observations = await _live_observations(
            launcher=launcher,
            pin=pin,
            profile=profile,
            artifact_root=Path(artifact_dir),
        )
    counts = observations["result"]["counts"]
    golden_path = output / "local-ideal.golden.json"
    replay_path = output / "local-ideal.replay.json"
    _write_json(
        golden_path,
        {
            "schema_version": "ari.qiskit-golden/v1",
            "profile_id": profile.profile_id,
            "experiment_digest": profile.experiment_digest,
            "counts": counts,
        },
    )
    _write_json(
        replay_path,
        {
            "schema_version": "ari.qiskit-replay-fixture/v1",
            "profile_id": profile.profile_id,
            "arguments": {"request_id": "offline-fixture"},
            "result": {
                "status": "completed",
                "experiment_digest": profile.experiment_digest,
                "method_digest": profile.method_digest,
                "counts": counts,
                "shots": profile.shots,
            },
        },
    )
    payload = profile.model_dump(mode="json")
    payload.update(
        {
            "golden_fixture_path": str(golden_path),
            "golden_fixture_digest": _file_digest(golden_path),
            "replay_fixture_path": str(replay_path),
            "replay_fixture_digest": _file_digest(replay_path),
            "evidence": AdmissionEvidenceV1(
                protocol_conformance=True,
                provider_pinned=True,
                launcher_verified=True,
                dependencies_pinned=True,
                replay_fixture_digest=_file_digest(replay_path),
                scientific_validation_digest=_file_digest(golden_path),
                limitations_documented=True,
                semantics_documented=True,
                units_documented=True,
                method_identity_documented=True,
                architecture="x86_64 CPython 3.13 / Qiskit 2.5.1 / Aer 0.17.2 CPU",
                notes=[
                    "IBM Runtime and IBM hardware are outside this verified identity."
                ],
            ).model_dump(mode="json"),
        }
    )
    profile = QiskitExperimentV1.model_validate(payload)
    verify_qiskit_experiment_files(profile)
    observations["fixtures"] = {
        "qpy_digest": profile.circuit.qpy_digest,
        "golden_digest": profile.golden_fixture_digest,
        "replay_digest": profile.replay_fixture_digest,
    }
    tests = _tests(args.test_python, str(Path(args.core_python).absolute()))
    result = _bundle(
        output=output,
        captured_date=args.captured_date,
        actor=args.authorized_by,
        pin=pin,
        profile=profile,
        observations=observations,
        tests=tests,
    )
    _write_json(
        output / "materialized-profile-v1.json",
        {
            "schema_version": "ari.qiskit-materialized-profile/v1",
            "profile": profile.model_dump(mode="json"),
            "core_provider_digest": provider_digest(
                qiskit_effective_launcher(launcher, "circuit")
            ),
            "verified_lock_digest": result["lock_digest"],
        },
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-python", required=True)
    parser.add_argument("--core-package-root", required=True)
    parser.add_argument("--qpy", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--authorized-by", required=True)
    parser.add_argument("--captured-date", required=True)
    parser.add_argument("--test-python", default=sys.executable)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps({"ok": True, **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
