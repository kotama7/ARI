"""Qiskit scientific identity, source policy, and evidence tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from models import sha256_digest
from providers import ProviderProtocolError, StdioMCPAdapter
from qiskit_adapter import (
    QiskitCircuitV1,
    QiskitExperimentAdapter,
    QiskitExperimentV1,
    QiskitProviderPinV1,
    qiskit_effective_launcher,
    qiskit_provider_release_pin,
    verify_qiskit_experiment_files,
    verify_qiskit_provider_package,
)
from qiskit_fixtures import (
    FIXTURE_ROOT,
    FakeQiskitCore,
    experiment_profile,
    file_digest,
    launcher,
    source_spec,
)
from sources import SourcesDocumentV1


def test_official_support_pins_and_real_qpy_vectors_are_exact() -> None:
    core = QiskitProviderPinV1.model_validate(
        qiskit_provider_release_pin("circuit", "0.3.1")
    )
    runtime = QiskitProviderPinV1.model_validate(
        qiskit_provider_release_pin("runtime", "0.6.1")
    )
    assert (
        core.repository_url
        == runtime.repository_url
        == ("https://github.com/Qiskit/mcp-servers")
    )
    assert (
        core.repository_commit
        == runtime.repository_commit
        == ("8c1abcec04ea5d504cc178c42441c8363c6935b5")
    )
    assert core.license_id == runtime.license_id == "Apache-2.0"

    document = json.loads(
        (FIXTURE_ROOT / "scientific-fixtures-v1.json").read_text(encoding="utf-8")
    )
    assert document["schema_version"] == "ari.qiskit-scientific-fixtures/v1"
    assert {item["name"] for item in document["vectors"]} == {
        "bell-ideal-statevector",
        "bell-noisy-density-matrix",
        "ghz3-ideal-statevector",
    }
    for vector in document["vectors"]:
        circuit = FIXTURE_ROOT / vector["circuit"]
        transpiled = FIXTURE_ROOT / vector["transpiled_qpy"]
        assert file_digest(circuit) == vector["circuit_digest"]
        assert file_digest(transpiled) == vector["transpiled_qpy_digest"]
        assert circuit.read_bytes()[:10] in {
            b"QISKIT\x11\x02\x05\x01",
        }
        assert sum(vector["counts"].values()) == vector["shots"] == 4096


def test_profiles_require_seed_noise_units_and_remote_binding_policy(
    tmp_path: Path,
) -> None:
    local = experiment_profile(tmp_path / "local", scientific=False)
    values = local.model_dump(mode="json")
    values["seed_simulator"] = None
    with pytest.raises(ValidationError, match="simulator seed"):
        QiskitExperimentV1.model_validate(values)

    values = local.model_dump(mode="json")
    values["backend"]["kind"] = "local-noisy"
    with pytest.raises(ValidationError, match="noise policy"):
        QiskitExperimentV1.model_validate(values)

    circuit = local.circuit.model_dump(mode="json")
    circuit["parameter_bindings"] = {"theta": 1.5}
    with pytest.raises(ValidationError, match="explicit rad or 1 unit"):
        QiskitCircuitV1.model_validate(circuit)

    remote = experiment_profile(
        tmp_path / "remote", kind="remote-simulator", scientific=False
    )
    values = remote.model_dump(mode="json")
    values["circuit"]["parameter_bindings"] = {"theta": 1.5}
    values["circuit"]["parameter_units"] = {"theta": "rad"}
    with pytest.raises(ValidationError, match="cannot bind parameters"):
        QiskitExperimentV1.model_validate(values)


def test_qpy_golden_and_replay_evidence_fail_closed_on_byte_drift(
    tmp_path: Path,
) -> None:
    profile = experiment_profile(tmp_path / "verified")
    verify_qiskit_experiment_files(profile)

    qpy = Path(profile.circuit.qpy_path)
    qpy.write_bytes(qpy.read_bytes() + b"drift")
    with pytest.raises(ProviderProtocolError, match="QPY circuit digest drifted"):
        verify_qiskit_experiment_files(profile)

    qpy.write_bytes((FIXTURE_ROOT / "bell-phi-plus.qpy").read_bytes())
    golden = Path(profile.golden_fixture_path or "")
    golden.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ProviderProtocolError, match="fixture digest drifted"):
        verify_qiskit_experiment_files(profile)


def test_source_fixes_official_entrypoints_environment_and_credential_free_lock(
    tmp_path: Path,
) -> None:
    profiles = [
        experiment_profile(tmp_path / "profile-local"),
        experiment_profile(tmp_path / "profile-remote", kind="ibm-hardware"),
    ]
    spec = source_spec(tmp_path / "providers", profiles)
    core_root, _executable, core_entrypoint = spec.core_launcher.resolve()
    assert core_entrypoint == core_root / "__init__.py"
    assert spec.core_effective_launcher.literal_env == {
        "FASTMCP_CHECK_FOR_UPDATES": "off",
        "FASTMCP_SHOW_SERVER_BANNER": "false",
        "QISKIT_MCP_MAX_GATES": "10000",
        "QISKIT_MCP_MAX_QUBITS": "100",
    }
    assert spec.runtime_effective_launcher is not None
    assert (
        spec.runtime_effective_launcher.literal_env["QISKIT_IBM_RUNTIME_LOG_LEVEL"]
        == "ERROR"
    )

    locked = spec.to_locked_source(verify=False)
    rendered = json.dumps(locked.model_dump(mode="json"), sort_keys=True)
    assert locked.provider_digest == sha256_digest(
        {
            "core_provider_digest": spec.core_provider_digest,
            "runtime_provider_digest": spec.runtime_provider_digest,
        }
    )
    assert "QISKIT_IBM_TOKEN" not in rendered
    assert "fixture-instance" not in rendered
    assert "crn:v1" not in rendered

    unsafe = spec.core_launcher.model_copy(
        update={"literal_env": {"LOG_LEVEL": "DEBUG"}}
    )
    with pytest.raises(ValidationError, match="environment must be empty"):
        type(spec).model_validate(
            {**spec.model_dump(mode="json"), "core_launcher": unsafe}
        )


def test_runtime_token_is_resolved_only_for_the_runtime_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "ibm-runtime-test-token-that-must-not-escape"
    monkeypatch.setenv("QISKIT_IBM_TOKEN", secret)
    profile = experiment_profile(
        tmp_path / "profile", kind="remote-simulator", scientific=False
    )
    spec = source_spec(tmp_path / "providers", [profile])
    runtime_launcher = spec.runtime_effective_launcher
    assert runtime_launcher is not None
    adapter = QiskitExperimentAdapter(
        spec.core_launcher,
        core_provider_digest=spec.core_provider_digest,
        core_pin=spec.core_pin,
        experiments=[profile],
        runtime_launcher=runtime_launcher,
        runtime_provider_digest=spec.runtime_provider_digest,
        runtime_pin=spec.runtime_pin,
        core_transport=FakeQiskitCore(),
        verify_packages=False,
        verify_contract=False,
    )

    assert isinstance(adapter.runtime_transport, StdioMCPAdapter)
    assert adapter.runtime_transport.credential_env_values == {
        "QISKIT_IBM_TOKEN": secret
    }
    assert secret not in repr(spec.to_locked_source(verify=False))


def test_package_masquerade_and_source_schema_drift_are_rejected(
    tmp_path: Path,
) -> None:
    base = launcher(tmp_path, "circuit")
    wrong_root = tmp_path / "not_qiskit"
    wrong_root.mkdir()
    (wrong_root / "__init__.py").write_text("def main(): pass\n", encoding="utf-8")
    masquerade = base.model_copy(update={"package_root": str(wrong_root.resolve())})
    pin = QiskitProviderPinV1.model_validate(
        qiskit_provider_release_pin("circuit", "0.3.1")
    )
    with pytest.raises(ProviderProtocolError, match="package_root must be"):
        verify_qiskit_provider_package(masquerade, pin)

    effective = qiskit_effective_launcher(base, "circuit")
    assert effective.arguments == []
    schema = SourcesDocumentV1.model_json_schema()
    rendered = json.dumps(schema, sort_keys=True)
    assert "QiskitSourceSpecV1" in rendered
    assert '"qiskit"' in rendered
