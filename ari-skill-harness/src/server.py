"""Read-only/request-only MCP surface for Scientific Assurance."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from ari.public.assurance import canonical_digest, load_harness_catalog


server = Server("ari-harness-query-skill")


def _repo_root() -> Path:
    configured = os.environ.get("ARI_ROOT", "").strip()
    # parents[2] IS the repository root: this file is <repo>/<package>/src/server.py.
    # The trailing .parent walked one directory ABOVE the repo, so with no
    # ARI_ROOT set the catalog path did not exist -- and because every failure
    # here is returned as data in an error envelope rather than raised, that
    # read as "no harnesses registered" instead of as a misconfiguration.
    # ari-skill-paper-re/src/server.py:129 has it right at the same depth.
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[2]


def _catalog_path() -> Path:
    configured = os.environ.get("ARI_HARNESS_CATALOG", "").strip()
    return Path(configured) if configured else _repo_root() / "ari-core" / "config" / "harnesses" / "catalog.yaml"


def _checkpoint() -> Path:
    configured = os.environ.get("ARI_CHECKPOINT_DIR", "").strip()
    if not configured:
        raise ValueError("ARI_CHECKPOINT_DIR is required for run-frozen queries")
    root = Path(configured)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("ARI_CHECKPOINT_DIR must be an absolute real directory")
    return root.resolve(strict=True)


def _admission(name: str) -> dict[str, Any]:
    path = _checkpoint() / "rqgm" / "kca" / "admission-v1" / name
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"run-frozen artifact is unavailable: {name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"run-frozen artifact is not an object: {name}")
    return value


def _render(value: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(value, ensure_ascii=False, sort_keys=True))]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_harnesses",
            description="Search independent verification definitions; no Harness is selected.",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string", "maxLength": 2000}},
                "additionalProperties": False,
            },
        ),
        Tool(
            name="describe_harness",
            description="Describe one Harness and its declared assurance scope.",
            inputSchema={
                "type": "object",
                "properties": {"harness_id": {"type": "string", "minLength": 1}},
                "required": ["harness_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="request_auxiliary_verification",
            description="Create a non-authoritative property request; fixed resolution remains internal.",
            inputSchema={
                "type": "object",
                "properties": {
                    "property_id": {"type": "string", "minLength": 1},
                    "method": {"type": "string", "minLength": 1},
                    "reason": {"type": "string", "minLength": 1, "maxLength": 8192},
                    "harness_hint": {"type": "string"},
                },
                "required": ["property_id", "method", "reason"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="read_attestation",
            description="Read one immutable target-bound Attestation by full SHA-256.",
            inputSchema={
                "type": "object",
                "properties": {"attestation_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}},
                "required": ["attestation_digest"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="list_verification_requirements",
            description="Read requirements from the immutable Verification Contract.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
    ]


def _manifests() -> list[dict[str, Any]]:
    return [
        item.model_dump(mode="json")
        for item in load_harness_catalog(_catalog_path()).manifests
    ]


def _attestation_by_digest(digest: str) -> dict[str, Any]:
    expected_name = digest.removeprefix("sha256:") + ".json"
    root = _checkpoint() / "rqgm" / "kca" / "nodes"
    matches = sorted(root.glob(f"*/attestations/{expected_name}"))
    if len(matches) != 1:
        raise ValueError("Attestation digest does not resolve uniquely")
    path = matches[0]
    if path.is_symlink() or not path.is_file():
        raise ValueError("Attestation is not a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("attestation_digest") != digest:
        raise ValueError("Attestation identity differs from requested digest")
    return value


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "search_harnesses":
            needle = str(arguments.get("query") or "").casefold().strip()
            matches = [
                item for item in _manifests()
                if not needle or needle in json.dumps(item, ensure_ascii=False).casefold()
            ]
            result = {"schema_version": "ari.harness-search/v1", "matches": matches}
        elif name == "describe_harness":
            harness_id = str(arguments.get("harness_id") or "")
            result = {
                "schema_version": "ari.harness-description/v1",
                "entries": [item for item in _manifests() if item["id"] == harness_id],
            }
        elif name == "list_verification_requirements":
            contract = _admission("verification_contract.json")
            result = {
                "schema_version": "ari.verification-requirements-view/v1",
                "contract_digest": contract.get("contract_digest"),
                "requirements": contract.get("requirements") or [],
            }
        elif name == "read_attestation":
            result = _attestation_by_digest(str(arguments.get("attestation_digest") or ""))
        elif name == "request_auxiliary_verification":
            admission = _admission("run_admission.json")
            body = {
                "schema_version": "ari.auxiliary-verification-request-hint/v1",
                "authoritative": False,
                "run_id": admission.get("run_id"),
                "property_id": str(arguments.get("property_id") or ""),
                "method": str(arguments.get("method") or ""),
                "reason": str(arguments.get("reason") or ""),
                "non_authoritative_harness_hint": str(arguments.get("harness_hint") or "") or None,
                "parent_verification_contract_digest": admission.get("verification_contract_digest"),
                "active_harness_lock_digest": admission.get("active_harness_lock_digest"),
                "activation": "fixed-harness-resolver-required-at-epoch-boundary",
            }
            body["request_digest"] = canonical_digest(body)
            result = body
        else:
            raise ValueError(f"unknown Harness operation: {name}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": "ari.harness-query-error/v1",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return _render(result)


async def main() -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
