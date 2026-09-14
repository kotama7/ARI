#!/usr/bin/env python3
"""Verify exact Qiskit MCP bytes, profiles, contracts, and optional execution."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from pathlib import Path

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
for dependency in (REPOSITORY_ROOT / "ari-core", PACKAGE_ROOT / "src"):
    if str(dependency) not in sys.path:
        sys.path.insert(0, str(dependency))

from providers import PythonStdioLauncherV1, provider_digest  # noqa: E402
from qiskit_adapter import (  # noqa: E402
    QiskitExperimentAdapter,
    QiskitExperimentV1,
    QiskitLocalBackendV1,
    QiskitProviderPinV1,
    qiskit_effective_launcher,
    qiskit_provider_release_pin,
    verify_qiskit_experiment_files,
    verify_qiskit_provider_package,
)
from qiskit_identity import verify_qiskit_python_distributions  # noqa: E402
from storage import RegistryArtifactStore  # noqa: E402


def _launcher(
    *, python: str, package_root: str, module: str, architecture: str
) -> PythonStdioLauncherV1:
    return PythonStdioLauncherV1(
        python_executable=str(Path(python).absolute()),
        package_root=str(Path(package_root).absolute()),
        python_module=module,
        python_callable="main",
        expected_architecture=architecture,
        identity_globs=[
            "**/*",
            "**/*.py",
            "*.lock",
            "pyproject.toml",
            "requirements*.txt",
        ],
    )


def _load_experiment(path: Path) -> QiskitExperimentV1:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load Qiskit experiment {path}: {exc}") from exc
    return QiskitExperimentV1.model_validate(raw)


async def _wait_for_result(
    adapter: QiskitExperimentAdapter,
    handle_id: str,
    timeout_seconds: float,
) -> dict:
    async with asyncio.timeout(timeout_seconds):
        while True:
            response = await adapter.get_result(None, handle_id)
            structured = response.structured or {}
            if structured.get("status") not in {"submitted", "running"}:
                return structured
            await asyncio.sleep(0.25)


async def _verify(args: argparse.Namespace) -> dict:
    core_pin = QiskitProviderPinV1.model_validate(
        qiskit_provider_release_pin("circuit", args.core_version)
    )
    core_base = _launcher(
        python=args.core_python,
        package_root=args.core_package_root,
        module="qiskit_mcp_server",
        architecture=args.architecture,
    )
    verify_qiskit_provider_package(core_base, core_pin)
    experiments = [_load_experiment(Path(path)) for path in args.experiment]
    for experiment in experiments:
        verify_qiskit_experiment_files(experiment)
    core_distributions = {
        "qiskit": "2.5.1",
        "qiskit-mcp-server": core_pin.version,
    }
    if any(isinstance(item.backend, QiskitLocalBackendV1) for item in experiments):
        core_distributions["qiskit-aer"] = "0.17.2"
    verify_qiskit_python_distributions(core_base, core_distributions)
    core_launcher = qiskit_effective_launcher(core_base, "circuit")
    core_digest = provider_digest(core_launcher)

    runtime_base: PythonStdioLauncherV1 | None = None
    runtime_launcher: PythonStdioLauncherV1 | None = None
    runtime_pin: QiskitProviderPinV1 | None = None
    runtime_digest: str | None = None
    if args.runtime_python or args.runtime_package_root:
        if not args.runtime_python or not args.runtime_package_root:
            raise ValueError(
                "--runtime-python and --runtime-package-root must be set together"
            )
        runtime_pin = QiskitProviderPinV1.model_validate(
            qiskit_provider_release_pin("runtime", args.runtime_version)
        )
        runtime_base = _launcher(
            python=args.runtime_python,
            package_root=args.runtime_package_root,
            module="qiskit_ibm_runtime_mcp_server",
            architecture=args.architecture,
        )
        verify_qiskit_provider_package(runtime_base, runtime_pin)
        verify_qiskit_python_distributions(
            runtime_base,
            {
                "qiskit": "2.5.1",
                "qiskit-ibm-runtime": "0.48.0",
                "qiskit-ibm-runtime-mcp-server": runtime_pin.version,
                "qiskit-mcp-server": core_pin.version,
            },
        )
        runtime_launcher = qiskit_effective_launcher(runtime_base, "runtime")
        runtime_digest = provider_digest(runtime_launcher)

    artifacts = (
        RegistryArtifactStore(Path(args.artifact_root)) if args.artifact_root else None
    )
    adapter = QiskitExperimentAdapter(
        core_launcher,
        core_provider_digest=core_digest,
        core_pin=core_pin,
        runtime_launcher=runtime_launcher,
        runtime_provider_digest=runtime_digest,
        runtime_pin=runtime_pin,
        experiments=experiments,
        artifact_store=artifacts,
        allowed_leaf_names={
            QiskitExperimentAdapter.leaf_name(item.profile_id) for item in experiments
        },
        timeout_seconds=args.timeout,
        verify_packages=False,
    )
    report: dict = {
        "schema_version": "ari.qiskit-verification/v1",
        "core_provider": {
            "version": core_pin.version,
            "repository_commit": core_pin.repository_commit,
            "package_tree_digest": core_pin.package_tree_digest,
            "dependency_lock_digest": core_pin.dependency_lock_digest,
            "mcp_contract_digest": core_pin.mcp_contract_digest,
            "provider_digest": core_digest,
        },
        "runtime_provider": (
            {
                "version": runtime_pin.version,
                "repository_commit": runtime_pin.repository_commit,
                "package_tree_digest": runtime_pin.package_tree_digest,
                "dependency_lock_digest": runtime_pin.dependency_lock_digest,
                "mcp_contract_digest": runtime_pin.mcp_contract_digest,
                "provider_digest": runtime_digest,
            }
            if runtime_pin is not None
            else None
        ),
        "profiles": [
            {
                "profile_id": item.profile_id,
                "capability_ref": item.capability_ref,
                "experiment_digest": item.experiment_digest,
                "method_digest": item.method_digest,
                "circuit_digest": item.circuit.qpy_digest,
                "target_digest": item.backend.target.target_digest,
            }
            for item in experiments
        ],
        "mcp_contract_smoke": False,
        "run": None,
    }
    if args.smoke or args.run_profile:
        report["virtual_leaf_names"] = [
            item.name for item in await adapter.list_tools()
        ]
        report["mcp_contract_smoke"] = True
    if args.run_profile:
        matches = [item for item in experiments if item.profile_id == args.run_profile]
        if len(matches) != 1:
            raise ValueError("--run-profile must name exactly one --experiment")
        if artifacts is None:
            raise ValueError("--run-profile requires --artifact-root")
        leaf = QiskitExperimentAdapter.leaf_name(matches[0].profile_id)
        submission = await adapter.invoke(leaf, {"request_id": args.request_id})
        handle_id = str((submission.structured or {}).get("handle_id") or "")
        if not handle_id:
            raise RuntimeError("Qiskit adapter did not return a handle")
        try:
            report["run"] = await _wait_for_result(adapter, handle_id, args.run_timeout)
        except TimeoutError:
            await adapter.cancel(None, handle_id)
            raise RuntimeError("Qiskit verification run timed out and was cancelled")
        if report["run"].get("status") != "completed":
            raise RuntimeError(
                f"Qiskit verification run failed: {report['run'].get('error')}"
            )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-python", required=True)
    parser.add_argument("--core-package-root", required=True)
    parser.add_argument("--core-version", default="0.3.1")
    parser.add_argument("--runtime-python", default="")
    parser.add_argument("--runtime-package-root", default="")
    parser.add_argument("--runtime-version", default="0.6.1")
    parser.add_argument("--architecture", default=platform.machine())
    parser.add_argument("--experiment", action="append", default=[])
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--run-profile", default="")
    parser.add_argument("--request-id", default="operator-verification")
    parser.add_argument("--artifact-root", default="")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--run-timeout", type=float, default=7_200.0)
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(_verify(args))
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps({"ok": True, **report}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
