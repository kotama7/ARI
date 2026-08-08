"""The CUDA environment validator, as something a run can actually call.

The promoted bundle named a tool -- `ari_cuda_validate__exclusive_node_<arch>`
-- that existed nowhere but in the string which generated it. Two fully gated
Provider bundles were pinned to a capability that nothing could supply, and the
symptom was indistinguishable from a substrate with no GPU: a requirement for
`ari.environment.cuda.validate/v1` simply resolved `unsatisfied`.

This is the tool. It takes no arguments on purpose: the operation is fixed, and
everything that could vary -- which node, which compiler, which architecture --
is either pinned by the verified lock or observed from the node itself. The
selectors it needs are site-private, so they are read from an operator-supplied
configuration outside the repository, never from the caller.

The broker registers this through the existing `stdio-mcp` source kind, so
admitting it needs no new source model, no new adapter branch, and no new
catalog vocabulary.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent
for _dependency in (
    REPO_ROOT / "ari-core",
    REPO_ROOT / "ari-skill-hpc",
    PACKAGE_ROOT / "src",
):
    if str(_dependency) not in sys.path:
        sys.path.insert(0, str(_dependency))

from cuda_execution import run_cuda_validation  # noqa: E402
from cuda_promotion import (  # noqa: E402
    CUDA_CAPABILITY_REF,
    cuda_bundle,
    cuda_tool_name,
    verify_cuda_verified_lock,
)
from site_privacy import load_private_site_config  # noqa: E402


SITE_CONFIG_ENV = "ARI_CUDA_SITE_CONFIG"
WORK_ROOT_ENV = "ARI_CUDA_WORK_ROOT"
NVCC_ENV = "ARI_CUDA_NVCC"
WORKER_PYTHON_ENV = "ARI_CUDA_WORKER_PYTHON"
BUNDLE_ENV = "ARI_CUDA_BUNDLE"

RESULT_SCHEMA = "ari.result-envelope/v1"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set for the CUDA validator")
    return value


def _bundle_lock() -> tuple[Path, dict[str, Any]]:
    """The verified lock this server serves, and where it lives.

    The server refuses to answer for a bundle it cannot verify. A validator that
    would run the self-test regardless of whether its own promotion still checks
    out is a validator whose result means nothing.
    """

    directory = Path(_required(BUNDLE_ENV)).resolve(strict=True)
    lock_path = directory / "verified-lock-v1.json"
    document = json.loads(lock_path.read_text(encoding="utf-8"))
    lock = verify_cuda_verified_lock(
        lock_path, expected_lock_digest=document["lock_digest"]
    )
    target = lock["runtime_target"]
    if cuda_bundle(target["cuda_compiler_version"], target["compute_capability"]) != directory:
        raise RuntimeError("CUDA bundle directory does not match the hardware it records")
    return directory, lock


def _tool_descriptor(lock: dict[str, Any]) -> dict[str, Any]:
    name = cuda_tool_name(lock["runtime_target"]["compute_capability"])
    return {
        "name": name,
        "description": (
            "Run the fixed all-device CUDA vector-add self-test, with its "
            "negative control, on the exclusive-node inventory this Provider "
            "was promoted against. Takes no arguments: the operation is fixed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }


async def _validate(lock: dict[str, Any]) -> dict[str, Any]:
    site = load_private_site_config(_required(SITE_CONFIG_ENV), repository=REPO_ROOT)
    outcome = await run_cuda_validation(
        site=site,
        work_root=Path(_required(WORK_ROOT_ENV)),
        remote_nvcc=_required(NVCC_ENV),
        worker_python=_required(WORKER_PYTHON_ENV),
    )
    public = outcome["public_result"]
    target = lock["runtime_target"]
    # The live devices must be the ones the lock was promoted against. Without
    # this the tool would happily report a pass from different hardware than the
    # evidence describes.
    observed = public["device_classes"][0]
    if (
        public["device_count"] != target["accelerator_count"]
        or observed["name"] != target["accelerator_model"]
        or observed["compute_capability"] != target["compute_capability"]
    ):
        raise RuntimeError("live CUDA inventory differs from the verified lock")
    return {
        "schema_version": RESULT_SCHEMA,
        "status": "ok",
        "error": None,
        "capability_ref": CUDA_CAPABILITY_REF,
        "payload": {
            "verdict": public["verdict"],
            "device_count": public["device_count"],
            "device_classes": public["device_classes"],
            "architecture": public["architecture"],
            "maximum_absolute_error": public["maximum_absolute_error"],
            "all_repeats_equal": public["all_repeats_equal"],
            "all_negative_controls_detected": public["all_negative_controls_detected"],
            "source_digest": public["source_digest"],
            "compiler_digest": public["compiler_digest"],
        },
    }


def _envelope_error(message: str) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA,
        "status": "error",
        "error": {"kind": "cuda-validation-failed", "message": message},
        "capability_ref": CUDA_CAPABILITY_REF,
        "payload": None,
    }


def build_server():
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    _, lock = _bundle_lock()
    descriptor = _tool_descriptor(lock)
    server = Server("ari-cuda-environment-validator")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=descriptor["name"],
                description=descriptor["description"],
                inputSchema=descriptor["inputSchema"],
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        if name != descriptor["name"]:
            raise ValueError(f"unknown tool: {name}")
        try:
            envelope = await _validate(lock)
        except Exception as exc:  # noqa: BLE001 - reported, never raised past here
            # The site selectors can appear in scheduler errors, so only the
            # exception type crosses this boundary.
            envelope = _envelope_error(type(exc).__name__)
        return [TextContent(type="text", text=json.dumps(envelope, sort_keys=True))]

    return server


def main() -> int:
    from mcp.server.stdio import stdio_server

    async def _run() -> None:
        server = build_server()
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
