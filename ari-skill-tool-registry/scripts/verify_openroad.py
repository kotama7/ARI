#!/usr/bin/env python3
"""Verify pinned OpenROAD-MCP bytes, profiles, schemas, and optional execution."""

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

from openroad_adapter import (  # noqa: E402
    OpenRoadExperimentAdapter,
    OpenRoadExperimentV1,
    OpenRoadProviderPinV1,
    openroad_effective_launcher,
    openroad_provider_release_pin,
    verify_openroad_experiment_files,
    verify_openroad_provider_package,
)
from providers import PythonStdioLauncherV1, provider_digest  # noqa: E402
from storage import RegistryArtifactStore  # noqa: E402


def _load_experiment(path: Path) -> OpenRoadExperimentV1:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load OpenROAD experiment {path}: {exc}") from exc
    return OpenRoadExperimentV1.model_validate(raw)


async def _wait_for_result(
    adapter: OpenRoadExperimentAdapter,
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
    pin = OpenRoadProviderPinV1.model_validate(
        openroad_provider_release_pin(args.version)
    )
    base = PythonStdioLauncherV1(
        python_executable=str(Path(args.python).absolute()),
        package_root=str(Path(args.package_root).absolute()),
        python_module="openroad_mcp.main",
        python_callable="main",
        expected_architecture=args.architecture,
        identity_globs=[
            "**/*",
            "**/*.py",
            "*.lock",
            "pyproject.toml",
            "requirements*.txt",
        ],
    )
    verify_openroad_provider_package(base, pin.model_dump(mode="json"))
    launcher = openroad_effective_launcher(base)
    digest = provider_digest(launcher)
    experiments = [_load_experiment(Path(path)) for path in args.experiment]
    for experiment in experiments:
        verify_openroad_experiment_files(experiment)

    artifact_store = (
        RegistryArtifactStore(Path(args.artifact_root)) if args.artifact_root else None
    )
    adapter = OpenRoadExperimentAdapter(
        launcher,
        expected_provider_digest=digest,
        pin=pin.model_dump(mode="json"),
        experiments=experiments,
        artifact_store=artifact_store,
        allowed_leaf_names={
            OpenRoadExperimentAdapter.leaf_name(item.profile_id) for item in experiments
        },
        timeout_seconds=args.timeout,
        verify_package=False,
    )
    report: dict = {
        "schema_version": "ari.openroad-verification/v1",
        "provider_version": pin.version,
        "provider_commit": pin.repository_commit,
        "package_tree_digest": pin.package_tree_digest,
        "dependency_lock_digest": pin.dependency_lock_digest,
        "mcp_contract_digest": pin.mcp_contract_digest,
        "provider_digest": digest,
        "launcher": base.model_dump(mode="json"),
        "profiles": [
            {
                "profile_id": item.profile_id,
                "experiment_digest": item.experiment_digest,
                "method_digest": item.method_digest,
                "workspace_input_digest": item.workspace.input_digest,
                "toolchain_support_line": item.toolchain.support_line,
            }
            for item in experiments
        ],
        "mcp_contract_smoke": False,
        "run": None,
    }
    if args.smoke or args.run_profile:
        tools = await adapter.list_tools()
        report["mcp_contract_smoke"] = True
        report["virtual_leaf_names"] = [item.name for item in tools]
    if args.run_profile:
        matches = [item for item in experiments if item.profile_id == args.run_profile]
        if len(matches) != 1:
            raise ValueError("--run-profile must name exactly one --experiment")
        if artifact_store is None:
            raise ValueError("--run-profile requires --artifact-root")
        leaf_name = OpenRoadExperimentAdapter.leaf_name(matches[0].profile_id)
        submission = await adapter.invoke(leaf_name, {"request_id": args.request_id})
        handle_id = str((submission.structured or {}).get("handle_id") or "")
        if not handle_id:
            raise RuntimeError("OpenROAD adapter did not return a handle")
        try:
            report["run"] = await _wait_for_result(adapter, handle_id, args.run_timeout)
        except TimeoutError:
            await adapter.cancel(None, handle_id)
            raise RuntimeError("OpenROAD verification run timed out and was cancelled")
        if report["run"].get("status") != "completed":
            raise RuntimeError(
                f"OpenROAD verification run failed: {report['run'].get('error')}"
            )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, help="isolated Python executable")
    parser.add_argument(
        "--package-root",
        required=True,
        help="exact installed .../site-packages/openroad_mcp directory",
    )
    parser.add_argument("--version", default="0.6.1")
    parser.add_argument("--architecture", default=platform.machine())
    parser.add_argument(
        "--experiment",
        action="append",
        default=[],
        help="OpenRoadExperimentV1 YAML/JSON; may be repeated",
    )
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
