"""Read-only MCP surface for non-executable Knowledge Skills."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from ari.public.knowledge import canonical_digest, load_knowledge_catalog


server = Server("ari-knowledge-skill")


def _repo_root() -> Path:
    configured = os.environ.get("ARI_ROOT", "").strip()
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[2].parent


def _catalog_path() -> Path:
    configured = os.environ.get("ARI_KNOWLEDGE_CATALOG", "").strip()
    return Path(configured) if configured else _repo_root() / "ari-core" / "config" / "knowledge_skills" / "catalog.yaml"


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
            name="search_knowledge_skills",
            description="Search non-executable procedural knowledge; results grant no tool authority.",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string", "maxLength": 2000}},
                "additionalProperties": False,
            },
        ),
        Tool(
            name="describe_knowledge_skill",
            description="Describe one content-addressed Knowledge Skill as untrusted instruction data.",
            inputSchema={
                "type": "object",
                "properties": {"skill_id": {"type": "string", "minLength": 1}},
                "required": ["skill_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="list_active_knowledge_skills",
            description="Read the immutable active epoch Knowledge lock for this run.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        Tool(
            name="request_knowledge_skill",
            description="Create a non-authoritative next-epoch request; only the fixed Knowledge Binder may admit it.",
            inputSchema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "minLength": 1},
                    "reason": {"type": "string", "minLength": 1, "maxLength": 8192},
                    "required": {"type": "boolean", "default": False},
                },
                "required": ["skill_id", "reason"],
                "additionalProperties": False,
            },
        ),
    ]


def _catalog_entries() -> list[dict[str, Any]]:
    loaded = load_knowledge_catalog(_catalog_path())
    return [item.model_dump(mode="json") for item in loaded.snapshot.entries]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "search_knowledge_skills":
            needle = str(arguments.get("query") or "").casefold().strip()
            matches = []
            for entry in _catalog_entries():
                manifest = entry["manifest"]
                haystack = " ".join(
                    str(manifest.get(key) or "")
                    for key in ("id", "title", "description")
                ).casefold()
                if not needle or needle in haystack:
                    matches.append({
                        "id": manifest["id"],
                        "version": manifest["version"],
                        "status": entry["status"],
                        "body_sha256": manifest["source"]["body_sha256"],
                        "manifest_sha256": manifest["source"]["manifest_sha256"],
                    })
            result = {"schema_version": "ari.knowledge-search/v1", "matches": matches}
        elif name == "describe_knowledge_skill":
            skill_id = str(arguments.get("skill_id") or "")
            matches = [
                entry for entry in _catalog_entries()
                if entry["manifest"]["id"] == skill_id
            ]
            result = {
                "schema_version": "ari.knowledge-description/v1",
                "authority": "instruction-only",
                "entries": matches,
            }
        elif name == "list_active_knowledge_skills":
            lock = _admission("knowledge_skill_lock.json")
            result = {
                "schema_version": "ari.active-knowledge-view/v1",
                "lock_digest": lock.get("lock_digest"),
                "epoch_id": lock.get("epoch_id"),
                "admitted": lock.get("admitted") or [],
            }
        elif name == "request_knowledge_skill":
            admission = _admission("run_admission.json")
            skill_id = str(arguments.get("skill_id") or "")
            exact = [
                entry["manifest"] for entry in _catalog_entries()
                if entry["manifest"]["id"] == skill_id
            ]
            body = {
                "schema_version": "ari.knowledge-skill-request/v1",
                "authoritative": False,
                "run_id": admission.get("run_id"),
                "skill_id": skill_id,
                "available_exact_refs": [
                    {
                        "id": item["id"],
                        "version": item["version"],
                        "body_sha256": item["source"]["body_sha256"],
                        "manifest_sha256": item["source"]["manifest_sha256"],
                    }
                    for item in exact
                ],
                "reason": str(arguments.get("reason") or ""),
                "required": bool(arguments.get("required", False)),
                "activation": "fixed-knowledge-binder-required",
            }
            body["request_digest"] = canonical_digest(body)
            result = body
        else:
            raise ValueError(f"unknown Knowledge operation: {name}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": "ari.knowledge-query-error/v1",
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
