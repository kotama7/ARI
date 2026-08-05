"""OpenROAD profile isolation, scientific evidence, lifecycle, and replay tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import openroad_worker

from broker import CatalogBroker
from catalog import build_catalog
from ari_skill_hpc import (
    ArtifactPinV1 as HpcArtifactPinV1,
    ContainerRequestV1,
    JobHandleV1,
    JobLogV1,
    JobRequestV1,
    JobResultV1,
    JobStatusV1,
    ResourceRequestV1,
    sha256_digest as hpc_sha256_digest,
)
from models import AdmissionEvidenceV1
from openroad_adapter import (
    OpenRoadArtifactPinV1,
    OpenRoadCommandV1,
    OpenRoadExecutionV1,
    OpenRoadExperimentAdapter,
    OpenRoadExperimentV1,
    OpenRoadMetricV1,
    OpenRoadOutputArtifactV1,
    OpenRoadPortableRuntimeV1,
    OpenRoadProviderPinV1,
    OpenRoadTechnologyV1,
    OpenRoadToolchainV1,
    OpenRoadWorkspaceV1,
    openroad_provider_release_pin,
    openroad_workspace_digest,
    verify_openroad_experiment_files,
    verify_openroad_provider_package,
)
from openroad_worker import run as run_openroad_worker
from openroad_hpc_workspace import openroad_batch_tcl
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
    execution: OpenRoadExecutionV1 | None = None,
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
            execution_image_digest=(
                execution.container.image.digest
                if execution is not None and execution.container is not None
                else execution.portable_runtime.image.digest
                if execution is not None and execution.portable_runtime is not None
                else "sha256:" + "1" * 64
            ),
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
        "execution": execution or OpenRoadExecutionV1(),
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


def _slurm_execution(root: Path) -> OpenRoadExecutionV1:
    work_root = root / "shared-work"
    work_root.mkdir(parents=True, exist_ok=True)
    image = root / "openroad.sif"
    image.write_bytes(b"pinned OpenROAD container fixture\n")
    return OpenRoadExecutionV1(
        backend="slurm",
        site_identity_digest="sha256:" + "9" * 64,
        work_root=str(work_root.resolve()),
        resources=ResourceRequestV1(
            partition="eda",
            nodes=1,
            tasks=1,
            cpus_per_task=1,
            memory_mb_per_node=2048,
            walltime="00:01:00",
            account="research",
        ),
        container=ContainerRequestV1(
            image=HpcArtifactPinV1(
                logical_name="openroad-image",
                path=str(image.resolve()),
                digest=_digest_file(image),
                size_bytes=image.stat().st_size,
                media_type="application/vnd.sylabs.sif",
            ),
            network="none",
        ),
    )


def _portable_slurm_execution(root: Path) -> OpenRoadExecutionV1:
    work_root = root / "shared-work"
    work_root.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, HpcArtifactPinV1] = {}
    for filename, logical_name in (
        ("proot", "openroad-proot-runtime"),
        ("openroad.sif", "openroad-sif-image"),
        ("unsquashfs", "openroad-unsquashfs-runtime"),
        ("python3", "openroad-worker-python"),
    ):
        path = root / filename
        path.write_bytes((logical_name + "\n").encode())
        path.chmod(0o700)
        artifacts[logical_name] = HpcArtifactPinV1(
            logical_name=logical_name,
            path=str(path.resolve()),
            digest=_digest_file(path),
            size_bytes=path.stat().st_size,
        )
    worker_python = artifacts["openroad-worker-python"]
    return OpenRoadExecutionV1(
        backend="slurm",
        site_identity_digest="sha256:" + "8" * 64,
        work_root=str(work_root.resolve()),
        resources=ResourceRequestV1(
            partition="eda-private",
            nodes=1,
            tasks=1,
            cpus_per_task=1,
            walltime="00:01:00",
            nodelist="compute-node-a",
            exclusive=True,
        ),
        portable_runtime=OpenRoadPortableRuntimeV1(
            proot=artifacts["openroad-proot-runtime"],
            image=artifacts["openroad-sif-image"],
            unsquashfs=artifacts["openroad-unsquashfs-runtime"],
            squashfs_offset=40960,
        ),
        worker_python=worker_python.path,
        worker_python_pin=worker_python,
        terminal_evidence_policy="fixed-wrapper-marker",
    )


class FakeOpenRoadScheduler:
    def __init__(self, *, block: bool = False) -> None:
        self.block = block
        self.cancelled = False
        self.requests: list[JobRequestV1] = []
        self.batch_specs: list[dict[str, Any]] = []
        self.handle: JobHandleV1 | None = None
        self._log_path: Path | None = None
        self._provenance_path: Path | None = None

    async def submit(self, request: JobRequestV1) -> JobHandleV1:
        self.requests.append(request)
        scope = Path(request.work_dir) / ".ari-hpc" / "fake"
        scope.mkdir(parents=True, exist_ok=True)
        self._log_path = scope / "slurm-42.out"
        self._log_path.write_text("OpenROAD scheduler fixture log\n", encoding="utf-8")
        self._provenance_path = scope / "execution-environment.txt"
        self._provenance_path.write_text(
            "hostname=fixture\narchitecture=" + platform.machine() + "\n",
            encoding="utf-8",
        )
        if not self.block:
            for output in request.outputs:
                path = Path(output.path)
                if output.logical_name == "openroad-batch-result":
                    spec_path = next(
                        Path(item.path)
                        for item in request.inputs
                        if item.logical_name == "openroad-batch-spec"
                    )
                    spec = json.loads(spec_path.read_text(encoding="utf-8"))
                    self.batch_specs.append(spec)
                    _write_json(
                        path,
                        {
                            "schema_version": "ari.openroad-batch-result/v1",
                            "experiment_digest": spec["experiment_digest"],
                            "started_at": "2026-08-02T00:00:00Z",
                            "completed_at": "2026-08-02T00:00:01Z",
                            "architecture": platform.machine(),
                            "executable_digest": spec["executable_digest"],
                            "tcl_digest": spec["tcl_digest"],
                            "return_code": 0,
                            "error": None,
                            "metrics_materialization": "direct-workspace",
                        },
                    )
                elif path.suffix == ".json":
                    _write_json(
                        path,
                        {
                            "timing": {"wns": -0.25},
                            "physical": {"area": 150.0},
                        },
                    )
                elif path.suffix == ".def":
                    path.write_text(
                        "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n",
                        encoding="utf-8",
                    )
        digest = request.request_digest
        self.handle = JobHandleV1(
            handle_id="hpc-openroad-fixture",
            request_id=request.request_id,
            request_digest=digest,
            cluster_identity="sha256:" + "a" * 64,
            job_id="42",
            submission_digest="sha256:" + "b" * 64,
            workspace_scope=request.work_dir,
            artifact_scope=str(scope),
            submitted_at="2026-08-02T00:00:00Z",
        )
        return self.handle

    async def status(self, handle_or_job_id: str) -> JobStatusV1:
        assert self.handle is not None
        if self.cancelled:
            state = "cancelled"
            scheduler_state = "CANCELLED"
            exit_code = None
        elif self.block:
            state = "running"
            scheduler_state = "RUNNING"
            exit_code = None
        else:
            state = "succeeded"
            scheduler_state = "COMPLETED"
            exit_code = 0
        return JobStatusV1(
            handle_id=self.handle.handle_id,
            job_id=self.handle.job_id,
            state=state,
            scheduler_state=scheduler_state,
            exit_code=exit_code,
        )

    async def result(self, handle_or_job_id: str) -> JobResultV1:
        assert self.handle is not None
        request = self.requests[0]
        status = await self.status(handle_or_job_id)
        outputs = tuple(
            HpcArtifactPinV1(
                logical_name=output.logical_name,
                path=output.path,
                digest=_digest_file(Path(output.path)),
                size_bytes=Path(output.path).stat().st_size,
                media_type=output.media_type,
            )
            for output in request.outputs
            if Path(output.path).is_file()
        )
        assert self._log_path is not None
        assert self._provenance_path is not None
        return JobResultV1(
            handle=self.handle,
            status=status,
            request_digest=request.request_digest,
            environment_digest=hpc_sha256_digest(
                request.environment.model_dump(mode="json")
            ),
            module_digest=hpc_sha256_digest(list(request.environment.modules)),
            container_digest=request.container.image.digest
            if request.container is not None
            else None,
            inputs=request.inputs,
            outputs=outputs,
            provenance=(
                HpcArtifactPinV1(
                    logical_name="execution-environment",
                    path=str(self._provenance_path),
                    digest=_digest_file(self._provenance_path),
                    size_bytes=self._provenance_path.stat().st_size,
                    media_type="text/plain",
                ),
            ),
            logs=(
                JobLogV1(
                    stream="stdout",
                    path=str(self._log_path),
                    digest=_digest_file(self._log_path),
                    size_bytes=self._log_path.stat().st_size,
                    text=self._log_path.read_text(encoding="utf-8"),
                ),
            ),
        ).with_digest()

    async def cancel(self, handle_or_job_id: str) -> dict[str, Any]:
        self.cancelled = True
        return {"status": "cancel_requested"}


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
            self.command_entered.set()
        elif name == "inspect_interactive_session":
            payload = {
                "session_id": arguments["session_id"],
                "metrics": {
                    "state": "running" if self.block_commands else "terminated",
                    "is_alive": self.block_commands,
                },
            }
        elif name == "interactive_openroad_exec":
            self.command_entered.set()
            if self.block_commands:
                await asyncio.Event().wait()
            payload = {"output": f"ran {arguments['command']}", "error": None}
        elif name == "interactive_openroad_query":
            command = arguments["command"]
            prefix = "puts [join {ARI DONE "
            suffix = "} _]"
            if command.startswith(prefix) and command.endswith(suffix):
                token = command[len(prefix) : -len(suffix)]
                output = f"ARI_DONE_{token}"
            else:
                output = command.removeprefix("puts ")
            payload = {
                "output": output,
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
    scheduler: FakeOpenRoadScheduler | None = None,
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
        scheduler=scheduler,
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


@pytest.mark.asyncio
async def test_slurm_profile_uses_typed_container_job_and_captures_provenance(
    tmp_path: Path,
):
    execution = _slurm_execution(tmp_path / "execution")
    profile = _profile(tmp_path / "profile", execution=execution)
    spec = _source_spec(tmp_path / "provider", [profile])
    artifacts = RegistryArtifactStore(tmp_path / "artifacts")
    scheduler = FakeOpenRoadScheduler()
    adapter = _adapter(
        spec,
        OpenRoadTransportFixture(),
        artifact_store=artifacts,
        scheduler=scheduler,
    )
    leaf = OpenRoadExperimentAdapter.leaf_name(profile.profile_id)
    submitted = await adapter.invoke(leaf, {"request_id": "scheduler-run"})
    handle_id = str((submitted.structured or {})["handle_id"])
    for _ in range(200):
        response = await adapter.get_result(None, handle_id)
        if (response.structured or {}).get("status") == "completed":
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("scheduler-backed OpenROAD run did not complete")

    completed = response.structured or {}
    assert completed["hpc_job"]["handle"]["handle_id"] == "hpc-openroad-fixture"
    assert completed["hpc_job"]["container_digest"] == (
        execution.container.image.digest if execution.container is not None else None
    )
    assert completed["execution"]["backend"] == "slurm"
    assert {item["metric_id"] for item in completed["metrics"]} == {
        "worst-slack",
        "design-area",
    }
    roles = {item["logical_role"] for item in completed["_ari_result_artifacts"]}
    assert {
        "openroad-def",
        "openroad-metrics",
        "openroad-session-transcript",
        "openroad-hpc-execution-environment",
        "openroad-scheduler-stdout",
    } <= roles
    request = scheduler.requests[0]
    assert request.resources.partition == "eda"
    assert request.resources.cpus_per_task == profile.toolchain.threads
    assert request.container is not None
    assert request.container.clean_environment is True
    assert request.container.network == "none"
    assert {item.logical_name for item in request.inputs} >= {
        "openroad-batch-worker",
        "openroad-batch-tcl",
        "openroad-batch-spec",
    }
    assert not list(Path(execution.work_root or "").glob("ari-openroad-*"))


@pytest.mark.asyncio
async def test_slurm_portable_runtime_is_digest_pinned_without_native_container(
    tmp_path: Path,
):
    execution = _portable_slurm_execution(tmp_path / "execution")
    profile = _profile(tmp_path / "profile", execution=execution)
    spec = _source_spec(tmp_path / "provider", [profile])
    scheduler = FakeOpenRoadScheduler()
    adapter = _adapter(
        spec,
        OpenRoadTransportFixture(),
        artifact_store=RegistryArtifactStore(tmp_path / "artifacts"),
        scheduler=scheduler,
    )
    leaf = OpenRoadExperimentAdapter.leaf_name(profile.profile_id)
    submitted = await adapter.invoke(leaf, {"request_id": "portable-run"})
    handle_id = str((submitted.structured or {})["handle_id"])
    for _ in range(200):
        response = await adapter.get_result(None, handle_id)
        if (response.structured or {}).get("status") == "completed":
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("portable scheduler-backed run did not complete")

    request = scheduler.requests[0]
    assert request.container is None
    assert request.resources.exclusive is True
    assert request.resources.nodelist == "compute-node-a"
    assert {item.logical_name for item in request.inputs} >= {
        "openroad-proot-runtime",
        "openroad-sif-image",
        "openroad-unsquashfs-runtime",
        "openroad-worker-python",
    }
    batch_spec = scheduler.batch_specs[0]
    assert batch_spec["portable_runtime"]["kind"] == "proot-sif"
    assert batch_spec["portable_runtime"]["network_policy"] == (
        "host-uncredentialed"
    )
    assert not list(Path(execution.work_root or "").glob("ari-openroad-*"))


@pytest.mark.asyncio
async def test_slurm_cancel_reaps_scheduler_and_workspace(tmp_path: Path):
    execution = _slurm_execution(tmp_path / "execution")
    profile = _profile(tmp_path / "profile", execution=execution)
    spec = _source_spec(tmp_path / "provider", [profile])
    artifacts = RegistryArtifactStore(tmp_path / "artifacts")
    scheduler = FakeOpenRoadScheduler(block=True)
    adapter = _adapter(
        spec,
        OpenRoadTransportFixture(),
        artifact_store=artifacts,
        scheduler=scheduler,
    )
    leaf = OpenRoadExperimentAdapter.leaf_name(profile.profile_id)
    submitted = await adapter.invoke(leaf, {"request_id": "cancel-scheduler-run"})
    handle_id = str((submitted.structured or {})["handle_id"])
    for _ in range(200):
        status = await adapter.get_status(None, handle_id)
        if (status.structured or {}).get("hpc_handle"):
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("OpenROAD scheduler handle was not published")

    cancelled = await adapter.cancel(None, handle_id)
    structured = cancelled.structured or {}
    assert structured["status"] == "cancelled"
    assert structured["cleanup_deferred"] is False
    assert scheduler.cancelled is True
    assert not list(Path(execution.work_root or "").glob("ari-openroad-*"))
    roles = {item["logical_role"] for item in structured["_ari_result_artifacts"]}
    assert "openroad-scheduler-stdout" in roles
    assert "openroad-session-transcript" in roles


def test_batch_worker_verifies_runtime_identity_and_writes_closed_result(
    tmp_path: Path,
):
    work = (tmp_path / "work").resolve()
    work.mkdir()
    executable = work / "openroad"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "metrics = Path('reports/metrics.json')\n"
        "metrics.parent.mkdir(parents=True, exist_ok=True)\n"
        "metrics.write_text(json.dumps({'timing': {'wns': -0.25}}))\n"
        "out = Path('results/design.def')\n"
        "out.parent.mkdir(parents=True, exist_ok=True)\n"
        "out.write_text('VERSION 5.8 ;\\nEND DESIGN\\n')\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    tcl_path = work / "flow.tcl"
    tcl_path.write_text("report_worst_slack\n", encoding="utf-8")
    result_path = work / "result.json"
    spec_path = work / "spec.json"
    spec = {
        "schema_version": "ari.openroad-batch-spec/v1",
        "experiment_digest": "sha256:" + "c" * 64,
        "work_dir": str(work),
        "executable_path": str(executable),
        "executable_digest": _digest_file(executable),
        "architecture": platform.machine(),
        "tcl_path": str(tcl_path),
        "tcl_digest": _digest_file(tcl_path),
        "metrics_path": str(work / "reports/metrics.json"),
        "result_path": str(result_path),
    }
    _write_json(spec_path, spec)

    assert run_openroad_worker(spec_path) == 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["return_code"] == 0
    assert result["error"] is None
    assert result["executable_digest"] == spec["executable_digest"]
    assert result["metrics_materialization"] == "direct-workspace"

    executable.write_text("drifted\n", encoding="utf-8")
    executable.chmod(0o700)
    assert run_openroad_worker(spec_path) == 70
    failed = json.loads(result_path.read_text(encoding="utf-8"))
    assert "executable digest drifted" in failed["error"]


def test_scheduler_batch_tcl_has_runtime_owned_metrics_lifecycle(tmp_path: Path):
    profile = _profile(tmp_path)

    compiled = openroad_batch_tcl(profile)

    assert compiled.splitlines()[0] == (
        "utl::open_metrics {reports/metrics.json}"
    )
    assert compiled.splitlines()[-1] == (
        "utl::close_metrics {reports/metrics.json}"
    )
    assert compiled.count("utl::open_metrics") == 1
    assert compiled.count("utl::close_metrics") == 1


def test_portable_worker_passes_workspace_relative_paths_to_guest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    work = (tmp_path / "work").resolve()
    work.mkdir()
    tcl = work / "ari-openroad-flow.tcl"
    tcl.write_text("report_design_area\n", encoding="utf-8")
    metrics = work / "reports/metrics.json"
    metrics.parent.mkdir()
    executable_bytes = b"digest-pinned guest executable\n"
    pins: dict[str, HpcArtifactPinV1] = {}
    for filename, logical_name in (
        ("proot", "openroad-proot-runtime"),
        ("image.sif", "openroad-sif-image"),
        ("unsquashfs", "openroad-unsquashfs-runtime"),
    ):
        path = tmp_path / filename
        path.write_bytes((logical_name + "\n").encode())
        pins[logical_name] = HpcArtifactPinV1(
            logical_name=logical_name,
            path=str(path.resolve()),
            digest=_digest_file(path),
            size_bytes=path.stat().st_size,
        )

    def fake_extract(argv, **_kwargs):
        rootfs = Path(argv[argv.index("-dest") + 1])
        executable = rootfs / "opt/openroad"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(executable_bytes)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(openroad_worker.subprocess, "run", fake_extract)
    command, rootfs = openroad_worker._portable_openroad_command(
        {
            "schema_version": "ari.openroad-portable-runtime/v1",
            "kind": "proot-sif",
            "network_policy": "host-uncredentialed",
            "proot": pins["openroad-proot-runtime"].model_dump(mode="json"),
            "image": pins["openroad-sif-image"].model_dump(mode="json"),
            "unsquashfs": pins["openroad-unsquashfs-runtime"].model_dump(
                mode="json"
            ),
            "squashfs_offset": 40960,
        },
        work_dir=work,
        executable_path="/opt/openroad",
        executable_digest=_digest_bytes(executable_bytes),
        tcl_path=tcl,
    )
    try:
        assert command[-2:] == ["-no_init", "ari-openroad-flow.tcl"]
        assert str(work) not in command[-1:]
        guest_metrics = rootfs / metrics.relative_to("/")
        guest_metrics.parent.mkdir(parents=True, exist_ok=True)
        guest_metrics.write_text('{"route__drc_errors": 0}\n', encoding="utf-8")
        assert (
            openroad_worker._materialize_metrics(
                metrics, work_dir=work, portable_rootfs=rootfs
            )
            == "portable-rootfs-export"
        )
        assert json.loads(metrics.read_text(encoding="utf-8")) == {
            "route__drc_errors": 0
        }
    finally:
        shutil.rmtree(rootfs)


def test_slurm_profile_rejects_unpinned_or_inconsistent_resources(tmp_path: Path):
    execution = _slurm_execution(tmp_path / "execution")
    profile = _profile(tmp_path / "profile", execution=execution)
    assert profile.execution.backend == "slurm"

    with pytest.raises(ValidationError, match="CPUs per task"):
        OpenRoadExperimentV1.model_validate(
            profile.model_copy(
                update={
                    "execution": execution.model_copy(
                        update={
                            "resources": execution.resources.model_copy(
                                update={"cpus_per_task": 2}
                            )
                        }
                    )
                }
            ).model_dump(mode="json")
        )
    with pytest.raises(ValidationError, match="container digest"):
        OpenRoadExperimentV1.model_validate(
            profile.model_copy(
                update={
                    "toolchain": profile.toolchain.model_copy(
                        update={"execution_image_digest": "sha256:" + "f" * 64}
                    )
                }
            ).model_dump(mode="json")
        )
