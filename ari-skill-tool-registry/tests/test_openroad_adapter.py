"""OpenROAD profile isolation, scientific evidence, lifecycle, and replay tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from broker import CatalogBroker
from catalog import build_catalog
from models import AdmissionEvidenceV1
from openroad_adapter import (
    OpenRoadArtifactPinV1,
    OpenRoadCommandV1,
    OpenRoadExperimentAdapter,
    OpenRoadExperimentV1,
    OpenRoadMetricV1,
    OpenRoadOutputArtifactV1,
    OpenRoadProviderPinV1,
    OpenRoadTechnologyV1,
    OpenRoadToolchainV1,
    OpenRoadWorkspaceV1,
    openroad_provider_release_pin,
    openroad_workspace_digest,
    verify_openroad_experiment_files,
    verify_openroad_provider_package,
)
from providers import (
    ProviderProtocolError,
    ProviderResponseV1,
    PythonStdioLauncherV1,
)
from sources import OpenRoadCatalogSource, OpenRoadSourceSpecV1
from storage import CassetteStore, RegistryArtifactStore


def _digest_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _digest_file(path: Path) -> str:
    return _digest_bytes(path.read_bytes())


def _provider_pin() -> OpenRoadProviderPinV1:
    return OpenRoadProviderPinV1.model_validate(openroad_provider_release_pin("0.6.1"))


def _launcher(root: Path) -> PythonStdioLauncherV1:
    package = root / "provider" / "openroad_mcp"
    package.mkdir(parents=True, exist_ok=True)
    (package / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
    return PythonStdioLauncherV1(
        python_executable=str(Path(sys.executable).resolve()),
        package_root=str(package.resolve()),
        python_module="openroad_mcp.main",
        python_callable="main",
        expected_architecture=platform.machine(),
        identity_globs=[
            "**/*",
            "**/*.py",
            "*.lock",
            "pyproject.toml",
            "requirements*.txt",
        ],
    )


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _profile(
    root: Path,
    *,
    profile_id: str = "gcd-nangate45",
    seed: int = 17,
    scientific: bool = False,
) -> OpenRoadExperimentV1:
    source = root / f"inputs-{profile_id}"
    inputs = {
        "rtl/top.v": ("rtl", b"module top(input clk); endmodule\n"),
        "constraints/top.sdc": ("constraint", b"create_clock -period 10 clk\n"),
        "tech/tech.lef": ("technology-lef", b"VERSION 5.8 ;\n"),
        "tech/cells.lib": ("liberty", b"library(cells) {}\n"),
    }
    artifacts: list[OpenRoadArtifactPinV1] = []
    for relative, (role, payload) in inputs.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        artifacts.append(
            OpenRoadArtifactPinV1(
                relative_path=relative,
                digest=_digest_bytes(payload),
                role=role,
            )
        )

    executable = root / "bin" / "openroad"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"pinned OpenROAD fixture executable\n")
    executable.chmod(0o700)
    metrics = [
        OpenRoadMetricV1(
            metric_id="worst-slack",
            source_artifact="reports/metrics.json",
            json_pointer="/timing/wns",
            unit="ns",
            corner="typical",
            mode="functional",
            stage="report",
            expected_min=-1.0 if scientific else None,
            expected_max=0.0 if scientific else None,
        ),
        OpenRoadMetricV1(
            metric_id="design-area",
            source_artifact="reports/metrics.json",
            json_pointer="/physical/area",
            unit="um^2",
            corner="typical",
            mode="functional",
            stage="report",
            expected_min=100.0 if scientific else None,
            expected_max=200.0 if scientific else None,
        ),
    ]
    values: dict[str, Any] = {
        "profile_id": profile_id,
        "description": "Pinned Nangate45 placement and routing fixture",
        "toolchain": OpenRoadToolchainV1(
            support_line="orfs-26q3",
            orfs_commit="adeb389e7fbf06ef6a939a895c014f69e6f7aa00",
            openroad_commit="7304ba78ade7cb9f78466c6d0231432d72dadd3b",
            openroad_version="26Q3",
            executable_path=str(executable.resolve()),
            executable_digest=_digest_file(executable),
            execution_image_digest="sha256:" + "1" * 64,
            architecture=platform.machine(),
            threads=1,
            seed=seed,
        ),
        "technology": OpenRoadTechnologyV1(
            pdk_id="nangate45",
            pdk_version="orfs-26q3",
            pdk_digest="sha256:" + "2" * 64,
            pdk_license_scope="redistributable",
            standard_cell_library_id="nangate45",
            standard_cell_library_version="orfs-26q3",
            standard_cell_library_digest="sha256:" + "3" * 64,
            corner="typical",
            mode="functional",
        ),
        "workspace": OpenRoadWorkspaceV1(
            source_root=str(source.resolve()),
            input_artifacts=artifacts,
            input_digest=openroad_workspace_digest(artifacts),
        ),
        "commands": [
            OpenRoadCommandV1(stage="setup", verb="set_thread_count", arguments=["1"]),
            OpenRoadCommandV1(
                stage="setup", verb="read_lef", arguments=["tech/tech.lef"]
            ),
            OpenRoadCommandV1(
                stage="setup", verb="read_liberty", arguments=["tech/cells.lib"]
            ),
            OpenRoadCommandV1(
                stage="setup", verb="read_verilog", arguments=["rtl/top.v"]
            ),
            OpenRoadCommandV1(stage="setup", verb="link_design", arguments=["top"]),
            OpenRoadCommandV1(
                stage="setup",
                verb="read_sdc",
                arguments=["constraints/top.sdc"],
            ),
            OpenRoadCommandV1(stage="placement", verb="global_placement"),
            OpenRoadCommandV1(
                stage="finishing",
                verb="write_def",
                arguments=["results/design.def"],
            ),
            OpenRoadCommandV1(stage="report", verb="report_worst_slack"),
        ],
        "output_artifacts": [
            OpenRoadOutputArtifactV1(
                relative_path="reports/metrics.json",
                logical_role="openroad-metrics",
                media_type="application/json",
            ),
            OpenRoadOutputArtifactV1(
                relative_path="results/design.def",
                logical_role="openroad-def",
                media_type="text/plain",
            ),
        ],
        "metrics": metrics,
        "limitations": [
            "Fixture validates the adapter contract, not production PPA quality."
        ],
        "evidence": AdmissionEvidenceV1(
            protocol_conformance=True,
            provider_pinned=True,
            launcher_verified=True,
            dependencies_pinned=True,
            limitations_documented=True,
            semantics_documented=True,
            units_documented=True,
            method_identity_documented=True,
            architecture="Pinned OpenROAD profile through isolated stdio MCP",
        ),
        "command_timeout_seconds": 5,
        "poll_interval_seconds": 0.05,
    }
    if not scientific:
        return OpenRoadExperimentV1.model_validate(values)

    golden_path = root / f"evidence/{profile_id}-golden.json"
    golden = {
        "schema_version": "ari.openroad-golden/v1",
        "profile_id": profile_id,
        "metrics": [
            {
                "metric_id": metric.metric_id,
                "unit": metric.unit,
                "corner": metric.corner,
                "mode": metric.mode,
                "stage": metric.stage,
                "expected_min": metric.expected_min,
                "expected_max": metric.expected_max,
            }
            for metric in metrics
        ],
    }
    _write_json(golden_path, golden)
    placeholder_path = root / f"evidence/{profile_id}-replay.json"
    _write_json(placeholder_path, {})
    placeholder_digest = _digest_file(placeholder_path)
    golden_digest = _digest_file(golden_path)
    values.update(
        {
            "golden_fixture_path": str(golden_path.resolve()),
            "golden_fixture_digest": golden_digest,
            "replay_fixture_path": str(placeholder_path.resolve()),
            "replay_fixture_digest": placeholder_digest,
            "evidence": AdmissionEvidenceV1(
                protocol_conformance=True,
                provider_pinned=True,
                launcher_verified=True,
                dependencies_pinned=True,
                replay_fixture_digest=placeholder_digest,
                scientific_validation_digest=golden_digest,
                limitations_documented=True,
                semantics_documented=True,
                units_documented=True,
                method_identity_documented=True,
                architecture="Pinned OpenROAD profile with exact golden and replay fixtures",
            ),
        }
    )
    provisional = OpenRoadExperimentV1.model_validate(values)
    replay = {
        "schema_version": "ari.openroad-replay-fixture/v1",
        "profile_id": profile_id,
        "experiment_digest": provisional.experiment_digest,
        "arguments": {"request_id": "golden-fixture"},
        "result": {
            "status": "completed",
            "experiment_digest": provisional.experiment_digest,
            "metrics": [
                {
                    "metric_id": "worst-slack",
                    "value": -0.25,
                    "unit": "ns",
                    "corner": "typical",
                    "mode": "functional",
                    "stage": "report",
                },
                {
                    "metric_id": "design-area",
                    "value": 150.0,
                    "unit": "um^2",
                    "corner": "typical",
                    "mode": "functional",
                    "stage": "report",
                },
            ],
        },
    }
    _write_json(placeholder_path, replay)
    replay_digest = _digest_file(placeholder_path)
    values["replay_fixture_digest"] = replay_digest
    values["evidence"] = values["evidence"].model_copy(
        update={"replay_fixture_digest": replay_digest}
    )
    return OpenRoadExperimentV1.model_validate(values)


def _source_spec(
    root: Path, experiments: list[OpenRoadExperimentV1]
) -> OpenRoadSourceSpecV1:
    return OpenRoadSourceSpecV1(
        source_id="openroad.fixture",
        provider_digest="sha256:" + "4" * 64,
        launcher=_launcher(root),
        experiments=experiments,
    )


class OpenRoadTransportFixture:
    def __init__(
        self,
        *,
        metric_value: float = -0.25,
        missing_output: str | None = None,
        unexpected_output: bool = False,
        block_commands: bool = False,
    ) -> None:
        self.metric_value = metric_value
        self.missing_output = missing_output
        self.unexpected_output = unexpected_output
        self.block_commands = block_commands
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.workspaces: list[Path] = []
        self.connections = 0
        self.active_connections = 0
        self.max_active_connections = 0
        self.command_entered = asyncio.Event()

    @asynccontextmanager
    async def connection(self):
        self.connections += 1
        self.active_connections += 1
        self.max_active_connections = max(
            self.max_active_connections, self.active_connections
        )
        try:
            yield self
        finally:
            self.active_connections -= 1

    async def list_tools(self):
        return []

    async def invoke(self, name: str, arguments: dict[str, Any]):
        self.calls.append((name, dict(arguments)))
        if name == "create_interactive_session":
            await asyncio.sleep(0.01)
            workspace = Path(arguments["cwd"])
            self.workspaces.append(workspace)
            outputs = {
                "reports/metrics.json": json.dumps(
                    {
                        "timing": {"wns": self.metric_value},
                        "physical": {"area": 150.0},
                    },
                    sort_keys=True,
                ).encode(),
                "results/design.def": b"VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n",
            }
            for relative, payload in outputs.items():
                if relative == self.missing_output:
                    continue
                path = workspace / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            if self.unexpected_output:
                (workspace / "undeclared.log").write_text("not declared\n")
            payload = {
                "session_id": arguments["session_id"],
                "is_alive": True,
            }
        elif name == "interactive_openroad_exec":
            self.command_entered.set()
            if self.block_commands:
                await asyncio.Event().wait()
            payload = {"output": f"ran {arguments['command']}", "error": None}
        elif name == "interactive_openroad_query":
            payload = {
                "output": arguments["command"].removeprefix("puts "),
                "error": None,
            }
        elif name == "terminate_interactive_session":
            payload = {"terminated": True}
        else:
            raise AssertionError(name)
        return ProviderResponseV1(
            text=json.dumps(payload, sort_keys=True), structured=payload
        )

    async def get_status(self, lifecycle, provider_handle):
        raise AssertionError("adapter owns the virtual lifecycle")

    async def get_result(self, lifecycle, provider_handle):
        raise AssertionError("adapter owns the virtual lifecycle")

    async def cancel(self, lifecycle, provider_handle):
        raise AssertionError("adapter owns the virtual lifecycle")


def _adapter(
    spec: OpenRoadSourceSpecV1,
    transport: OpenRoadTransportFixture,
    *,
    artifact_store: RegistryArtifactStore | None = None,
) -> OpenRoadExperimentAdapter:
    return OpenRoadExperimentAdapter(
        spec.effective_launcher,
        expected_provider_digest=spec.provider_digest,
        pin=spec.pin.model_dump(mode="json"),
        experiments=spec.experiments,
        artifact_store=artifact_store,
        allowed_leaf_names={
            OpenRoadExperimentAdapter.leaf_name(profile.profile_id)
            for profile in spec.experiments
        },
        timeout_seconds=spec.timeout_seconds,
        transport=transport,
        verify_package=False,
        verify_contract=False,
    )


async def _result_until_terminal(
    broker: CatalogBroker, handle: dict[str, Any]
) -> dict[str, Any]:
    for _ in range(200):
        result = await broker.get_result(handle)
        if result["status"] not in {"submitted", "running"}:
            return result
        await asyncio.sleep(0.01)
    raise AssertionError("OpenROAD fixture did not reach a terminal state")


def test_profile_rejects_arbitrary_tcl_and_source_fixes_provider_policy(tmp_path: Path):
    profile = _profile(tmp_path)
    with pytest.raises(ValidationError, match="literal"):
        OpenRoadCommandV1(stage="setup", verb="exec", arguments=["whoami"])

    spec = _source_spec(tmp_path, [profile])
    assert spec.effective_launcher.arguments == [
        "--transport",
        "stdio",
        "--log-level",
        "ERROR",
    ]
    assert spec.effective_launcher.literal_env == {
        "FASTMCP_CHECK_FOR_UPDATES": "off",
        "FASTMCP_SHOW_SERVER_BANNER": "false",
        "OPENROAD_ALLOWED_COMMANDS": "openroad",
        "OPENROAD_ENABLE_COMMAND_VALIDATION": "true",
        "OPENROAD_MAX_SESSIONS": "8",
        "OPENROAD_WHITELIST_ENABLED": "true",
    }
    unsafe = spec.launcher.model_copy(update={"literal_env": {"LOG_LEVEL": "DEBUG"}})
    with pytest.raises(ValidationError, match="environment must be empty"):
        OpenRoadSourceSpecV1(
            source_id="openroad.unsafe",
            provider_digest=spec.provider_digest,
            launcher=unsafe,
            experiments=[profile],
        )


def test_workspace_and_scientific_fixtures_are_digest_closed(tmp_path: Path):
    profile = _profile(tmp_path, scientific=True)
    verify_openroad_experiment_files(profile)

    extra = Path(profile.workspace.source_root) / "extra.txt"
    extra.write_text("undeclared\n", encoding="utf-8")
    with pytest.raises(ProviderProtocolError, match="undeclared input"):
        verify_openroad_experiment_files(profile)
    extra.unlink()

    golden = Path(profile.golden_fixture_path or "")
    golden.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ProviderProtocolError, match="fixture digest drifted"):
        verify_openroad_experiment_files(profile)


def test_provider_package_masquerade_and_contract_drift_fail_closed(tmp_path: Path):
    profile = _profile(tmp_path)
    launcher = _launcher(tmp_path)
    masquerade = launcher.model_copy(
        update={"package_root": str((tmp_path / "different_name").resolve())}
    )
    with pytest.raises(ProviderProtocolError, match="package_root must be"):
        verify_openroad_provider_package(
            masquerade, _provider_pin().model_dump(mode="json")
        )

    transport = OpenRoadTransportFixture()
    spec = _source_spec(tmp_path, [profile])
    adapter = OpenRoadExperimentAdapter(
        spec.effective_launcher,
        expected_provider_digest=spec.provider_digest,
        pin=spec.pin.model_dump(mode="json"),
        experiments=[profile],
        allowed_leaf_names={OpenRoadExperimentAdapter.leaf_name(profile.profile_id)},
        transport=transport,
        verify_package=False,
    )
    with pytest.raises(ProviderProtocolError, match="tool surface drifted"):
        asyncio.run(adapter.list_tools())


@pytest.mark.asyncio
async def test_catalog_admits_verified_profile_and_marks_same_backend_overlap(
    tmp_path: Path,
):
    first = _profile(tmp_path / "one", scientific=True)
    second = _profile(
        tmp_path / "two",
        profile_id="gcd-nangate45-alt",
        seed=23,
        scientific=True,
    )
    spec = _source_spec(tmp_path / "provider", [first, second])
    transport = OpenRoadTransportFixture()
    result = await build_catalog(
        [
            OpenRoadCatalogSource(
                spec,
                adapter=_adapter(spec, transport),
                verify_source=False,
            )
        ]
    )

    assert len(result.lock.tools) == 2
    assert {item.level for item in result.lock.admissions} == {
        "scientifically_admitted"
    }
    assert len({item.independence_group for item in result.lock.tools}) == 1
    assert result.lock.overlaps[0].relationship == "same-backend"
    descriptor = result.lock.tools[0]
    assert descriptor.async_lifecycle is not None
    assert descriptor.async_lifecycle.succeeded_states == ["completed"]
    assert descriptor.semantics["execution_model"] == "immutable-profile"
    assert descriptor.units == {"design-area": "um^2", "worst-slack": "ns"}


@pytest.mark.asyncio
async def test_recorded_run_captures_metrics_artifacts_and_replays_offline(
    tmp_path: Path,
):
    profile = _profile(tmp_path / "profile")
    spec = _source_spec(tmp_path / "provider", [profile])
    artifacts = RegistryArtifactStore(tmp_path / "ear" / "catalog")
    cassettes = CassetteStore(tmp_path / "cassettes", artifact_store=artifacts)
    transport = OpenRoadTransportFixture()
    adapter = _adapter(spec, transport, artifact_store=artifacts)
    catalog = await build_catalog(
        [OpenRoadCatalogSource(spec, adapter=adapter, verify_source=False)]
    )
    descriptor = catalog.lock.tools[0]
    broker = CatalogBroker(
        catalog.lock,
        index=catalog.index,
        adapters={spec.source_id: adapter},
        artifact_store=artifacts,
        cassette_store=cassettes,
    )

    submitted = await broker.invoke(
        descriptor.tool_ref, {"request_id": "recorded-run"}, mode="record"
    )
    assert submitted["status"] == "submitted"
    handle = submitted["structured_content"]["registry_handle"]
    completed = await _result_until_terminal(broker, handle)

    assert completed["status"] == "ok"
    assert "_ari_result_artifacts" not in completed["structured_content"]
    assert completed["structured_content"]["result_digest"].startswith("sha256:")
    metrics = {
        item["metric_id"]: item for item in completed["structured_content"]["metrics"]
    }
    assert metrics["worst-slack"]["value"] == -0.25
    assert metrics["worst-slack"]["unit"] == "ns"
    assert metrics["worst-slack"]["corner"] == "typical"
    assert metrics["worst-slack"]["mode"] == "functional"
    assert metrics["design-area"]["unit"] == "um^2"
    assert {item["logical_role"] for item in completed["artifacts"]} == {
        "openroad-def",
        "openroad-metrics",
        "openroad-session-transcript",
    }
    assert all(
        artifacts.get(item["logical_name"]).is_file() for item in completed["artifacts"]
    )
    assert len(cassettes.list_records()) == 1
    assert transport.connections == 1
    assert sum(name == "create_interactive_session" for name, _ in transport.calls) == 1
    assert (
        sum(name == "terminate_interactive_session" for name, _ in transport.calls) == 1
    )

    duplicate = await broker.invoke(
        descriptor.tool_ref, {"request_id": "recorded-run"}, mode="live"
    )
    assert (
        duplicate["structured_content"]["registry_handle"]["provider_handle"]
        == (handle["provider_handle"])
    )
    assert sum(name == "create_interactive_session" for name, _ in transport.calls) == 1

    class OfflineAdapter:
        async def invoke(self, name, arguments):
            raise AssertionError("offline replay must not contact OpenROAD")

    offline = CatalogBroker(
        catalog.lock,
        index=catalog.index,
        adapters={spec.source_id: OfflineAdapter()},
        artifact_store=artifacts,
        cassette_store=cassettes,
    )
    replayed = await offline.invoke(
        descriptor.tool_ref, {"request_id": "recorded-run"}, mode="replay"
    )
    assert replayed["status"] == "ok"
    assert replayed["artifacts"] == completed["artifacts"]
    assert "_registry_replay" in replayed["structured_content"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport", "message"),
    [
        (OpenRoadTransportFixture(unexpected_output=True), "undeclared artifacts"),
        (
            OpenRoadTransportFixture(missing_output="results/design.def"),
            "required artifact is missing",
        ),
        (OpenRoadTransportFixture(metric_value=0.5), "golden range"),
    ],
)
async def test_output_and_metric_contract_violations_fail_with_transcript(
    tmp_path: Path,
    transport: OpenRoadTransportFixture,
    message: str,
):
    profile = _profile(tmp_path / "profile", scientific=True)
    spec = _source_spec(tmp_path / "provider", [profile])
    artifacts = RegistryArtifactStore(tmp_path / "artifacts")
    adapter = _adapter(spec, transport, artifact_store=artifacts)
    catalog = await build_catalog(
        [OpenRoadCatalogSource(spec, adapter=adapter, verify_source=False)]
    )
    descriptor = catalog.lock.tools[0]
    broker = CatalogBroker(
        catalog.lock,
        index=catalog.index,
        adapters={spec.source_id: adapter},
        artifact_store=artifacts,
    )
    submitted = await broker.invoke(descriptor.tool_ref, {"request_id": "failing-run"})
    failed = await _result_until_terminal(
        broker, submitted["structured_content"]["registry_handle"]
    )

    assert failed["status"] == "error"
    assert message in failed["error"]["message"]
    assert [item["logical_role"] for item in failed["artifacts"]] == [
        "openroad-session-transcript"
    ]
    assert not transport.workspaces[0].exists()


@pytest.mark.asyncio
async def test_cancel_terminates_session_and_parallel_runs_use_distinct_workspaces(
    tmp_path: Path,
):
    profile = _profile(tmp_path / "profile")
    spec = _source_spec(tmp_path / "provider", [profile])
    artifacts = RegistryArtifactStore(tmp_path / "artifacts")
    blocking = OpenRoadTransportFixture(block_commands=True)
    blocking_adapter = _adapter(spec, blocking, artifact_store=artifacts)
    catalog = await build_catalog(
        [OpenRoadCatalogSource(spec, adapter=blocking_adapter, verify_source=False)]
    )
    descriptor = catalog.lock.tools[0]
    broker = CatalogBroker(
        catalog.lock,
        index=catalog.index,
        adapters={spec.source_id: blocking_adapter},
        artifact_store=artifacts,
    )
    submitted = await broker.invoke(
        descriptor.tool_ref, {"request_id": "cancel-this-run"}
    )
    await asyncio.wait_for(blocking.command_entered.wait(), timeout=2)
    cancelled = await broker.cancel(submitted["structured_content"]["registry_handle"])
    assert cancelled["status"] == "cancelled"
    assert [item["logical_role"] for item in cancelled["artifacts"]] == [
        "openroad-session-transcript"
    ]
    assert any(name == "terminate_interactive_session" for name, _ in blocking.calls)
    assert not blocking.workspaces[0].exists()

    parallel_transport = OpenRoadTransportFixture()
    parallel_adapter = _adapter(spec, parallel_transport, artifact_store=artifacts)
    parallel_broker = CatalogBroker(
        catalog.lock,
        index=catalog.index,
        adapters={spec.source_id: parallel_adapter},
        artifact_store=artifacts,
    )
    first, second = await asyncio.gather(
        parallel_broker.invoke(descriptor.tool_ref, {"request_id": "parallel-a"}),
        parallel_broker.invoke(descriptor.tool_ref, {"request_id": "parallel-b"}),
    )
    first_result, second_result = await asyncio.gather(
        _result_until_terminal(
            parallel_broker, first["structured_content"]["registry_handle"]
        ),
        _result_until_terminal(
            parallel_broker, second["structured_content"]["registry_handle"]
        ),
    )
    assert first_result["status"] == second_result["status"] == "ok"
    assert len({str(path) for path in parallel_transport.workspaces}) == 2
    assert parallel_transport.max_active_connections == 2
    assert all(not path.exists() for path in parallel_transport.workspaces)
