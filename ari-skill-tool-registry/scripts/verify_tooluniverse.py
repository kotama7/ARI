#!/usr/bin/env python3
"""Verify a pinned ToolUniverse installation and optionally smoke its compact MCP."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src"
sys.path.insert(0, str(SRC))

from providers import PythonStdioLauncherV1, provider_digest  # noqa: E402
from tooluniverse_adapter import (  # noqa: E402
    ToolUniverseCompactAdapter,
    dangerous_leaf,
    verify_tooluniverse_dependency_lock,
    verify_tooluniverse_environment,
    verify_tooluniverse_package,
    verify_tooluniverse_pin,
    verify_tooluniverse_verified_lock,
    verify_tooluniverse_wheel,
)


def _pin(version: str) -> dict:
    document = json.loads(
        (PACKAGE_ROOT / "providers" / "tooluniverse-support-v1.json").read_text(
            encoding="utf-8"
        )
    )
    matches = [item for item in document["releases"] if item["version"] == version]
    if len(matches) != 1:
        raise ValueError(f"ToolUniverse version {version!r} is not supported")
    return matches[0]


async def _verify(args: argparse.Namespace) -> dict:
    pin = _pin(args.version)
    verify_tooluniverse_pin(pin)
    dependency_lock_digest = verify_tooluniverse_dependency_lock(
        args.dependency_lock, pin
    )
    wheel_digest = verify_tooluniverse_wheel(args.wheel, pin) if args.wheel else None
    if pin.get("artifact_kind") == "ari-patched-wheel" and wheel_digest is None:
        raise ValueError("ARI-patched ToolUniverse verification requires --wheel")
    verified_lock = (
        verify_tooluniverse_verified_lock(args.verified_lock, pin)
        if args.verified_lock
        else None
    )
    base = PythonStdioLauncherV1(
        python_executable=str(Path(args.python).absolute()),
        package_root=str(Path(args.package_root).absolute()),
        python_module="tooluniverse.smcp_server",
        python_callable="run_stdio_server",
        expected_architecture=args.architecture,
        identity_globs=[
            "**/*",
            "**/*.py",
            "*.lock",
            "pyproject.toml",
            "requirements*.txt",
        ],
    )
    verify_tooluniverse_package(base, pin)
    environment_report = verify_tooluniverse_environment(base, pin)
    arguments = ["--compact-mode", "--no-search", "--max-workers", "1"]
    if args.category:
        arguments.extend(["--categories", *sorted(set(args.category))])
    launcher = base.model_copy(update={"arguments": arguments})
    digest = provider_digest(launcher)
    report: dict = {
        "schema_version": "ari.tooluniverse-verification/v1",
        "version": pin["version"],
        "wheel_digest": pin["wheel_digest"],
        "package_tree_digest": pin["package_tree_digest"],
        "dependency_lock_digest": pin["dependency_lock_digest"],
        "observed_dependency_lock_digest": dependency_lock_digest,
        "observed_wheel_digest": wheel_digest,
        "dependency_environment": environment_report,
        "provider_digest": digest,
        "verified_lock_digest": (
            verified_lock["lock_digest"] if verified_lock is not None else None
        ),
        "launcher": base.model_dump(mode="json"),
        "categories": sorted(set(args.category)),
        "tools": sorted(set(args.tool)),
        "smoke": False,
    }
    if args.smoke:
        adapter = ToolUniverseCompactAdapter(
            launcher,
            expected_provider_digest=digest,
            pin=pin,
            include_categories=args.category,
            include_leaf_names=args.tool,
            timeout_seconds=args.timeout,
            page_size=args.page_size,
            info_batch_size=args.info_batch_size,
            max_tools=args.max_tools,
        )
        tools = await adapter.list_tools()
        report.update(
            {
                "smoke": True,
                "leaf_count": len(tools),
                "schema_quarantine_count": sum(
                    bool(
                        tool.annotations.get("ari_tooluniverse", {}).get(
                            "schema_errors"
                        )
                    )
                    for tool in tools
                ),
                "dangerous_leaf_count": sum(
                    dangerous_leaf(
                        str(
                            tool.annotations.get("ari_tooluniverse", {}).get(
                                "category", "unknown"
                            )
                        ),
                        str(
                            tool.annotations.get("ari_tooluniverse", {}).get(
                                "type", "Unknown"
                            )
                        ),
                    )
                    is not None
                    for tool in tools
                ),
                "sample_names": [tool.name for tool in tools[:20]],
            }
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, help="isolated Python executable")
    parser.add_argument(
        "--package-root",
        required=True,
        help="exact installed .../site-packages/tooluniverse directory",
    )
    parser.add_argument("--version", default="1.3.1")
    parser.add_argument("--wheel", help="retained exact Provider wheel")
    parser.add_argument(
        "--verified-lock",
        help="closed Provider promotion lock; required by production source admission",
    )
    parser.add_argument(
        "--dependency-lock",
        required=True,
        help="exact upstream uv.lock matching the support-matrix digest",
    )
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--tool", action="append", default=[])
    parser.add_argument("--architecture", default=platform.machine())
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--page-size", type=int, default=250)
    parser.add_argument("--info-batch-size", type=int, default=20)
    parser.add_argument("--max-tools", type=int, default=100_000)
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
