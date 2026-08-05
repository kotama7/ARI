#!/usr/bin/env python3
"""Promote the exact credential-free OpenROAD GCD/Nangate45 CPU profile."""

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
from openroad_adapter import (  # noqa: E402
    OpenRoadArtifactPinV1,
    OpenRoadCommandV1,
    OpenRoadExecutionV1,
    OpenRoadExperimentAdapter,
    OpenRoadExperimentV1,
    OpenRoadMetricV1,
    OpenRoadOutputArtifactV1,
    OpenRoadProviderPinV1,
    OpenRoadTechnologyV1,
    OpenRoadToolchainV1,
    OpenRoadWorkspaceV1,
    openroad_effective_launcher,
    openroad_provider_release_pin,
    openroad_workspace_digest,
    verify_openroad_experiment_files,
    verify_openroad_provider_package,
)
from openroad_promotion import (  # noqa: E402
    OPENROAD_VERIFIED_EVIDENCE_SCHEMA,
    OPENROAD_VERIFIED_LOCK_SCHEMA,
    OPENROAD_VERIFIED_MANIFEST_SCHEMA,
    OPENROAD_VERIFIED_PROFILE_ID,
    OPENROAD_VERIFIED_PROVIDER_ID,
    OPENROAD_VERIFIED_PROVIDER_VERSION,
    OPENROAD_WRAPPER,
    openroad_verified_adapter,
    openroad_verified_artifact,
    openroad_verified_runtime_target,
    openroad_verified_scope,
    verify_openroad_verified_lock,
)
from providers import (  # noqa: E402
    ProviderProtocolError,
    PythonStdioLauncherV1,
    StdioMCPAdapter,
    provider_digest,
)
from storage import RegistryArtifactStore  # noqa: E402


TEST_IDS = (
    "ari-skill-tool-registry/tests/test_openroad_adapter.py",
    "ari-skill-tool-registry/tests/test_stdio_adapter.py::test_stdio_timeout_reaps_the_provider_process_group",
)
EXPECTED_ORFS_COMMIT = "adeb389e7fbf06ef6a939a895c014f69e6f7aa00"
EXPECTED_OPENROAD_COMMIT = "7304ba78ade7cb9f78466c6d0231432d72dadd3b"
EXPECTED_IMAGE_DIGEST = (
    "sha256:d8f4db657ce86e647a0ecd0d1c7197a7e9abdae8c5b365a3b2d0b243aeb85f39"
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


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        check=True,
        timeout=30,
        text=True,
    )
    return completed.stdout.strip()


def _launcher(args: argparse.Namespace) -> PythonStdioLauncherV1:
    return PythonStdioLauncherV1(
        python_executable=os.path.abspath(args.provider_python),
        package_root=str(Path(args.provider_package_root).resolve()),
        python_module="openroad_mcp.main",
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


def _copy_inputs(args: argparse.Namespace, output: Path) -> Path:
    workspace = output / "workspace"
    inputs = workspace / "inputs"
    sources = {
        "3_place.odb": Path(args.placed_odb).resolve(strict=True),
        "3_place.sdc": Path(args.placed_sdc).resolve(strict=True),
        "NangateOpenCellLibrary.tech.lef": Path(args.technology_lef).resolve(
            strict=True
        ),
        "NangateOpenCellLibrary.macro.lef": Path(args.library_lef).resolve(strict=True),
        "NangateOpenCellLibrary_typical.lib": Path(args.liberty).resolve(strict=True),
        "Nangate45.LICENSE": Path(args.pdk_license).resolve(strict=True),
    }
    if workspace.is_symlink():
        raise FileExistsError("OpenROAD promotion workspace cannot be a symlink")
    if workspace.exists():
        expected_paths = {f"inputs/{name}" for name in sources}
        actual_paths = {
            path.relative_to(workspace).as_posix()
            for path in workspace.rglob("*")
            if path.is_file()
        }
        if actual_paths != expected_paths:
            raise FileExistsError(
                "existing OpenROAD promotion workspace is not the exact input set"
            )
        for name, source in sources.items():
            target = inputs / name
            if target.is_symlink() or _file_digest(target) != _file_digest(source):
                raise FileExistsError(
                    "existing OpenROAD promotion input differs from its source"
                )
        return workspace
    inputs.mkdir(parents=True)
    for name, source in sources.items():
        target = inputs / name
        shutil.copyfile(source, target)
        target.chmod(0o644)
    return workspace


def _artifact(
    path: Path, root: Path, role: str, media_type: str
) -> OpenRoadArtifactPinV1:
    return OpenRoadArtifactPinV1(
        relative_path=path.relative_to(root).as_posix(),
        digest=_file_digest(path),
        role=role,
        media_type=media_type,
    )


def _provisional_profile(workspace: Path) -> OpenRoadExperimentV1:
    inputs = workspace / "inputs"
    artifacts = [
        _artifact(
            inputs / "3_place.odb", workspace, "database", "application/octet-stream"
        ),
        _artifact(inputs / "3_place.sdc", workspace, "constraint", "text/plain"),
        _artifact(
            inputs / "NangateOpenCellLibrary.tech.lef",
            workspace,
            "technology-lef",
            "text/plain",
        ),
        _artifact(
            inputs / "NangateOpenCellLibrary.macro.lef",
            workspace,
            "library-lef",
            "text/plain",
        ),
        _artifact(
            inputs / "NangateOpenCellLibrary_typical.lib",
            workspace,
            "liberty",
            "text/plain",
        ),
        _artifact(inputs / "Nangate45.LICENSE", workspace, "other", "text/plain"),
    ]
    by_name = {Path(item.relative_path).name: item.digest for item in artifacts}
    pdk_digest = sha256_digest(
        {
            "technology_lef": by_name["NangateOpenCellLibrary.tech.lef"],
            "library_lef": by_name["NangateOpenCellLibrary.macro.lef"],
            "license": by_name["Nangate45.LICENSE"],
        }
    )
    commands = [
        OpenRoadCommandV1(stage="setup", verb="set_thread_count", arguments=["1"]),
        OpenRoadCommandV1(
            stage="setup",
            verb="read_liberty",
            arguments=["inputs/NangateOpenCellLibrary_typical.lib"],
        ),
        OpenRoadCommandV1(
            stage="setup", verb="read_db", arguments=["inputs/3_place.odb"]
        ),
        OpenRoadCommandV1(
            stage="setup", verb="read_sdc", arguments=["inputs/3_place.sdc"]
        ),
        OpenRoadCommandV1(
            stage="cts",
            verb="set_wire_rc",
            arguments=["-signal", "-layer", "metal3"],
        ),
        OpenRoadCommandV1(
            stage="cts",
            verb="set_wire_rc",
            arguments=["-clock", "-layer", "metal5"],
        ),
        OpenRoadCommandV1(
            stage="cts",
            verb="clock_tree_synthesis",
            arguments=[
                "-sink_clustering_enable",
                "-repair_clock_nets",
                "-buf_list",
                "{CLKBUF_X3}",
            ],
        ),
        OpenRoadCommandV1(
            stage="cts", verb="estimate_parasitics", arguments=["-placement"]
        ),
        OpenRoadCommandV1(stage="cts", verb="detailed_placement"),
        OpenRoadCommandV1(
            stage="routing",
            verb="global_route",
            arguments=["-congestion_iterations", "30"],
        ),
        OpenRoadCommandV1(
            stage="routing",
            verb="estimate_parasitics",
            arguments=["-global_routing"],
        ),
        OpenRoadCommandV1(
            stage="routing",
            verb="detailed_route",
            arguments=[
                "-output_drc",
                "reports/drc.rpt",
                "-output_maze",
                "results/maze.log",
                "-droute_end_iter",
                "64",
                "-verbose",
                "1",
                "-drc_report_iter_step",
                "5",
            ],
        ),
        OpenRoadCommandV1(
            stage="finishing",
            verb="filler_placement",
            arguments=[
                "{FILLCELL_X1 FILLCELL_X2 FILLCELL_X4 FILLCELL_X8 FILLCELL_X16 FILLCELL_X32}"
            ],
        ),
        OpenRoadCommandV1(
            stage="finishing", verb="write_def", arguments=["results/gcd.def"]
        ),
        OpenRoadCommandV1(
            stage="finishing", verb="write_verilog", arguments=["results/gcd.v"]
        ),
        OpenRoadCommandV1(stage="report", verb="report_worst_slack"),
        OpenRoadCommandV1(stage="report", verb="report_design_area"),
    ]
    outputs = [
        OpenRoadOutputArtifactV1(
            relative_path="reports/metrics.json",
            logical_role="openroad-metrics",
            media_type="application/json",
        ),
        OpenRoadOutputArtifactV1(
            relative_path="reports/drc.rpt",
            logical_role="openroad-drc-report",
            media_type="text/plain",
            required=False,
        ),
        OpenRoadOutputArtifactV1(
            relative_path="results/maze.log",
            logical_role="openroad-route-log",
            media_type="text/plain",
            required=False,
            max_bytes=100_000_000,
        ),
        OpenRoadOutputArtifactV1(
            relative_path="results/gcd.def",
            logical_role="openroad-def",
            media_type="text/plain",
        ),
        OpenRoadOutputArtifactV1(
            relative_path="results/gcd.v",
            logical_role="openroad-netlist",
            media_type="text/x-verilog",
        ),
    ]
    metrics = [
        OpenRoadMetricV1(
            metric_id="route-drc-errors",
            source_artifact="reports/metrics.json",
            json_pointer="/route__drc_errors",
            unit="count",
            corner="typical",
            mode="functional",
            stage="routing",
            expected_min=0.0,
            expected_max=0.0,
        ),
        OpenRoadMetricV1(
            metric_id="route-wirelength",
            source_artifact="reports/metrics.json",
            json_pointer="/route__wirelength",
            unit="um",
            corner="typical",
            mode="functional",
            stage="routing",
            expected_min=3_500.0,
            expected_max=3_700.0,
        ),
        OpenRoadMetricV1(
            metric_id="route-vias",
            source_artifact="reports/metrics.json",
            json_pointer="/route__vias",
            unit="count",
            corner="typical",
            mode="functional",
            stage="routing",
            expected_min=3_200.0,
            expected_max=3_500.0,
        ),
    ]
    return OpenRoadExperimentV1(
        profile_id=OPENROAD_VERIFIED_PROFILE_ID,
        description=(
            "Digest-pinned GCD Nangate45 post-placement CTS and routing through "
            "OpenROAD-MCP and the retained ORFS CPU image."
        ),
        toolchain=OpenRoadToolchainV1(
            support_line="orfs-26q3",
            orfs_commit=EXPECTED_ORFS_COMMIT,
            openroad_commit=EXPECTED_OPENROAD_COMMIT,
            openroad_version="26Q2-2517-g7304ba78ad",
            executable_path=str(OPENROAD_WRAPPER.resolve()),
            executable_digest=_file_digest(OPENROAD_WRAPPER),
            execution_image_digest=EXPECTED_IMAGE_DIGEST,
            architecture="x86_64",
            threads=1,
            seed=17,
        ),
        technology=OpenRoadTechnologyV1(
            pdk_id="nangate45",
            pdk_version="orfs-26q3-gadeb389e7",
            pdk_digest=pdk_digest,
            pdk_license_scope="redistributable",
            standard_cell_library_id="nangate45",
            standard_cell_library_version="orfs-26q3-gadeb389e7-typical",
            standard_cell_library_digest=by_name["NangateOpenCellLibrary_typical.lib"],
            corner="typical",
            mode="functional",
        ),
        workspace=OpenRoadWorkspaceV1(
            source_root=str(workspace.resolve()),
            input_artifacts=artifacts,
            input_digest=openroad_workspace_digest(artifacts),
        ),
        execution=OpenRoadExecutionV1(),
        commands=commands,
        output_artifacts=outputs,
        metrics=metrics,
        evidence=AdmissionEvidenceV1(
            protocol_conformance=True,
            provider_pinned=True,
            launcher_verified=True,
            dependencies_pinned=True,
            limitations_documented=True,
            semantics_documented=True,
            units_documented=True,
            method_identity_documented=True,
            architecture=(
                "x86_64 / Apptainer 1.5.0-rc.1 / ORFS adeb389e7 / "
                "OpenROAD 7304ba78ad / one CPU thread"
            ),
        ),
        limitations=[
            "The verified identity covers only the fixed GCD placed database, Nangate45 data, CPU image, commands, seed, and one-thread execution.",
            "It does not promote GPU, SLURM, another design, another PDK, another corner, or another OpenROAD image.",
            "The provider capability executes a routed-artifact contract; its verified status is not a general timing-closure guarantee.",
        ],
        command_timeout_seconds=3_600,
        poll_interval_seconds=0.1,
    )


async def _wait(adapter: OpenRoadExperimentAdapter, handle_id: str) -> dict[str, Any]:
    async with asyncio.timeout(1_200):
        while True:
            response = await adapter.get_result(None, handle_id)
            value = response.structured or {}
            if value.get("status") not in {"submitted", "running"}:
                return value
            await asyncio.sleep(0.1)


async def _live_observations(
    *,
    launcher: PythonStdioLauncherV1,
    pin: OpenRoadProviderPinV1,
    profile: OpenRoadExperimentV1,
    artifact_root: Path,
) -> dict[str, Any]:
    effective = openroad_effective_launcher(launcher)
    digest = provider_digest(effective)
    raw = StdioMCPAdapter(
        effective,
        expected_provider_digest=digest,
        timeout_seconds=120,
        max_pages=8,
        max_tools=32,
    )
    upstream = sorted(await raw.list_tools(), key=lambda item: item.name)
    adapter = OpenRoadExperimentAdapter(
        effective,
        expected_provider_digest=digest,
        pin=pin.model_dump(mode="json"),
        experiments=[profile],
        artifact_store=RegistryArtifactStore(artifact_root),
        allowed_leaf_names={OpenRoadExperimentAdapter.leaf_name(profile.profile_id)},
        timeout_seconds=120,
        verify_package=False,
    )
    leaves = await adapter.list_tools()
    if len(leaves) != 1:
        raise ProviderProtocolError("OpenROAD verified scope did not produce one leaf")
    submitted = await adapter.invoke(
        leaves[0].name, {"request_id": "promotion-gcd-nangate45-cpu"}
    )
    handle_id = str((submitted.structured or {}).get("handle_id") or "")
    result = await _wait(adapter, handle_id)
    if result.get("status") != "completed":
        raise ProviderProtocolError(f"OpenROAD live validation failed: {result}")
    metrics = result.get("metrics") or []
    observed = {item["metric_id"]: item["value"] for item in metrics}
    if observed.get("route-drc-errors") != 0.0:
        raise ProviderProtocolError("OpenROAD reference route has DRC errors")
    try:
        await adapter.invoke("ari_openroad_run__not_bound", {"request_id": "no"})
    except ProviderProtocolError:
        unbound_rejected = True
    else:
        raise ProviderProtocolError("unbound OpenROAD profile invocation succeeded")
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
            "experiment_digest": result["experiment_digest"],
            "method_digest": result["method_digest"],
            "result_digest": result["result_digest"],
            "metrics": metrics,
            "artifact_manifest": result["artifact_manifest"],
            "session_transcript": result["session_transcript"],
            "hpc_job": result.get("hpc_job"),
        },
        "execution_artifact_refs": result.get("_ari_result_artifacts", []),
        "unbound_invocation_rejected": unbound_rejected,
    }


def _official_orfs_observation(flow_root: Path) -> dict[str, Any]:
    if _git_head(flow_root.parent) != EXPECTED_ORFS_COMMIT:
        raise ProviderProtocolError("official ORFS checkout commit differs")
    result_root = flow_root / "results/nangate45/gcd/ari_verified"
    log_root = flow_root / "logs/nangate45/gcd/ari_verified"
    report_root = flow_root / "reports/nangate45/gcd/ari_verified"
    metrics_path = log_root / "6_report.json"
    drc_path = report_root / "5_route_drc.rpt"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    if drc_path.read_bytes() or metrics.get("finish__timing__setup__ws", -1) < 0:
        raise ProviderProtocolError("official ORFS reference did not pass DRC/timing")
    artifacts: dict[str, dict[str, Any]] = {}
    for name in (
        "6_final.def",
        "6_final.gds",
        "6_final.odb",
        "6_final.sdc",
        "6_final.spef",
        "6_final.v",
    ):
        path = result_root / name
        artifacts[name] = {"digest": _file_digest(path), "size": path.stat().st_size}
    return {
        "runner": "OpenROAD-flow-scripts make target",
        "invocation": [
            "make",
            "DESIGN_CONFIG=designs/nangate45/gcd/config.mk",
            "FLOW_VARIANT=ari_verified",
            "SKIP_CTS_REPAIR_TIMING=1",
        ],
        "orfs_commit": EXPECTED_ORFS_COMMIT,
        "execution_image_digest": EXPECTED_IMAGE_DIGEST,
        "metrics_report_digest": _file_digest(metrics_path),
        "drc_report_digest": _file_digest(drc_path),
        "selected_metrics": {
            "finish__design__instance__area": metrics["finish__design__instance__area"],
            "finish__timing__setup__ws": metrics["finish__timing__setup__ws"],
            "finish__timing__hold__ws": metrics["finish__timing__hold__ws"],
        },
        "result_artifacts": artifacts,
        "qualification": (
            "Independent upstream reference pass only; CTS timing repair was disabled "
            "after the pinned binary raised SIGILL, so this is not full default-flow parity."
        ),
    }


def _tests(test_python: str) -> dict[str, Any]:
    command = [test_python, "-m", "pytest", *TEST_IDS, "-q"]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        timeout=900,
    )
    output = completed.stdout + completed.stderr
    if completed.returncode:
        raise RuntimeError(output.decode("utf-8", errors="replace")[-12_000:])
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
            "artifact": manifest["artifact"],
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
            "official_orfs_reference": observations["official_orfs"],
        },
        "side_effect_declaration": {
            "side_effects": scope["side_effects"],
            "permissions": scope["permissions"],
        },
        "credential_scope": {"credential_scope_ids": []},
        "environment_allowlist": {
            "runtime_target": manifest["runtime_target"],
            "provider_digest": observations[
                "provider_digest_in_validation_environment"
            ],
        },
        "timeout_cancellation_process_group": {
            "bounded_command_timeout_seconds": 3_600,
            "test_ids": tests["test_ids"],
            **common,
        },
        "result_schema": observations["result"],
        "malicious_description_boundary": {
            "authority_source": "immutable profile and active catalog lock",
            **common,
        },
        "workspace_isolation": {
            "workspace_input_digest": profile["workspace_input_digest"],
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
    pin: OpenRoadProviderPinV1,
    profile: OpenRoadExperimentV1,
    observations: dict[str, Any],
    tests: dict[str, Any],
) -> dict[str, str]:
    artifact = openroad_verified_artifact(pin, [profile])
    scope = openroad_verified_scope([profile])
    runtime_target = openroad_verified_runtime_target([profile])
    slurm = profile.execution.backend == "slurm"
    manifest = {
        "schema_version": OPENROAD_VERIFIED_MANIFEST_SCHEMA,
        "provider_id": OPENROAD_VERIFIED_PROVIDER_ID,
        "provider_version": OPENROAD_VERIFIED_PROVIDER_VERSION,
        "artifact": artifact,
        "adapter": openroad_verified_adapter(),
        "runtime_target": runtime_target,
        "environment_policy": {
            "network": "host-uncredentialed" if slurm else "deny",
            "credential_scope_ids": [],
            "device": "CPU",
            "threads": 1,
            "scheduler": "exclusive-node" if slurm else None,
        },
        "capability_scope": scope,
    }
    manifest_digest = sha256_digest(manifest)
    gate_evidence = _gate_evidence(
        manifest=manifest, observations=observations, tests=tests
    )
    if tuple(gate_evidence) != PROVIDER_REGISTRATION_GATES:
        raise ValueError("OpenROAD registration gates are incomplete or out of order")
    evidence = {
        "schema_version": OPENROAD_VERIFIED_EVIDENCE_SCHEMA,
        "provider_id": OPENROAD_VERIFIED_PROVIDER_ID,
        "provider_version": OPENROAD_VERIFIED_PROVIDER_VERSION,
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
            detail=(
                "closed OpenROAD GCD/Nangate45 exclusive-node CPU registration evidence passed"
                if slurm
                else "closed OpenROAD GCD/Nangate45 CPU registration evidence passed"
            ),
        )
        for gate_id in PROVIDER_REGISTRATION_GATES
    )
    report = registration_report(
        provider_id=OPENROAD_VERIFIED_PROVIDER_ID,
        manifest_sha256=manifest_digest,
        gates=gates,
    ).model_dump(mode="json")
    approval = {
        "schema_version": "ari.capability-provider-promotion-approval/v1",
        "provider_id": OPENROAD_VERIFIED_PROVIDER_ID,
        "provider_version": OPENROAD_VERIFIED_PROVIDER_VERSION,
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
        "schema_version": OPENROAD_VERIFIED_LOCK_SCHEMA,
        "provider_id": OPENROAD_VERIFIED_PROVIDER_ID,
        "provider_version": OPENROAD_VERIFIED_PROVIDER_VERSION,
        "status": "verified",
        "artifact": artifact,
        "adapter": openroad_verified_adapter(),
        "runtime_target": runtime_target,
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
    verified = verify_openroad_verified_lock(
        output / "verified-lock-v1.json",
        expected_lock_digest=lock["lock_digest"],
        pin=pin,
        experiments=[profile],
    )
    return {
        "lock_digest": verified["lock_digest"],
        "approval_digest": approval["approval_digest"],
        "report_digest": report["report_digest"],
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output).resolve()
    if output != OPENROAD_WRAPPER.parent.parent.resolve():
        raise ValueError(
            "OpenROAD promotion output must be the canonical bundle directory"
        )
    output.mkdir(parents=True, exist_ok=True)
    if _file_digest(Path(args.execution_image).resolve(strict=True)) != (
        EXPECTED_IMAGE_DIGEST
    ):
        raise ProviderProtocolError("materialized ORFS image digest differs")
    if (
        Path(args.execution_image).resolve()
        != (OPENROAD_WRAPPER.parent / "openroad-orfs-26q3.sif").resolve()
    ):
        raise ProviderProtocolError("ORFS image is outside the canonical runtime path")
    if _git_head(Path(args.provider_checkout).resolve(strict=True)) != (
        "39d78c091d9f41d217c8c28ddb20fa105942eba5"
    ):
        raise ProviderProtocolError("OpenROAD-MCP checkout commit differs")
    workspace = _copy_inputs(args, output)
    pin = OpenRoadProviderPinV1.model_validate(openroad_provider_release_pin("0.6.1"))
    launcher = _launcher(args)
    verify_openroad_provider_package(launcher, pin.model_dump(mode="json"))
    profile = _provisional_profile(workspace)
    verify_openroad_experiment_files(profile)
    with tempfile.TemporaryDirectory(prefix="ari-openroad-promotion-") as artifact_dir:
        observations = await _live_observations(
            launcher=launcher,
            pin=pin,
            profile=profile,
            artifact_root=Path(artifact_dir),
        )
    observations["official_orfs"] = _official_orfs_observation(
        Path(args.orfs_flow_root).resolve(strict=True)
    )

    golden_path = output / "gcd-nangate45-26q3.golden.json"
    replay_path = output / "gcd-nangate45-26q3.replay.json"
    _write_json(
        golden_path,
        {
            "schema_version": "ari.openroad-golden/v1",
            "profile_id": profile.profile_id,
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
                for metric in profile.metrics
            ],
        },
    )
    replay_metrics = [
        {
            key: item[key]
            for key in ("metric_id", "value", "unit", "corner", "mode", "stage")
        }
        for item in observations["result"]["metrics"]
    ]
    _write_json(
        replay_path,
        {
            "schema_version": "ari.openroad-replay-fixture/v1",
            "profile_id": profile.profile_id,
            "experiment_digest": profile.experiment_digest,
            "arguments": {"request_id": "offline-fixture"},
            "result": {
                "status": "completed",
                "experiment_digest": profile.experiment_digest,
                "metrics": replay_metrics,
            },
        },
    )
    golden_digest = _file_digest(golden_path)
    replay_digest = _file_digest(replay_path)
    payload = profile.model_dump(mode="json")
    payload.update(
        {
            "golden_fixture_path": str(golden_path),
            "golden_fixture_digest": golden_digest,
            "replay_fixture_path": str(replay_path),
            "replay_fixture_digest": replay_digest,
            "evidence": AdmissionEvidenceV1(
                protocol_conformance=True,
                provider_pinned=True,
                launcher_verified=True,
                dependencies_pinned=True,
                replay_fixture_digest=replay_digest,
                scientific_validation_digest=golden_digest,
                limitations_documented=True,
                semantics_documented=True,
                units_documented=True,
                method_identity_documented=True,
                architecture=(
                    "x86_64 / Apptainer 1.5.0-rc.1 / ORFS adeb389e7 / "
                    "OpenROAD 7304ba78ad / one CPU thread"
                ),
                notes=[
                    "SLURM and GPU are outside this verified identity.",
                    "The upstream reference disabled CTS timing repair after a pinned-image SIGILL.",
                ],
            ).model_dump(mode="json"),
        }
    )
    profile = OpenRoadExperimentV1.model_validate(payload)
    verify_openroad_experiment_files(profile)
    observations["fixtures"] = {
        "golden_digest": golden_digest,
        "replay_digest": replay_digest,
    }
    tests = _tests(args.test_python)
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
            "schema_version": "ari.openroad-materialized-profile/v1",
            "profile": profile.model_dump(mode="json"),
            "provider_digest": provider_digest(openroad_effective_launcher(launcher)),
            "verified_lock_digest": result["lock_digest"],
        },
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-python", required=True)
    parser.add_argument("--provider-package-root", required=True)
    parser.add_argument("--provider-checkout", required=True)
    parser.add_argument("--execution-image", required=True)
    parser.add_argument("--placed-odb", required=True)
    parser.add_argument("--placed-sdc", required=True)
    parser.add_argument("--technology-lef", required=True)
    parser.add_argument("--library-lef", required=True)
    parser.add_argument("--liberty", required=True)
    parser.add_argument("--pdk-license", required=True)
    parser.add_argument("--orfs-flow-root", required=True)
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
