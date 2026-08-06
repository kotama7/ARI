"""MCP server for public typed scheduler and container job lifecycles."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from ari_skill_hpc import slurm
from ari_skill_hpc.contracts import JobSubmitArgumentsV1
from ari_skill_hpc.scheduler import (
    RemoteConfig,
    SchedulerError,
    SchedulerProtocolError,
    SchedulerTransportError,
    SchedulerValidationError,
    SubmissionUncertainError,
)
from ari_skill_hpc.slurm import SlurmClient


server = Server("hpc-skill")


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _get_slurm_client() -> SlurmClient:
    mode = os.environ.get("SLURM_MODE", "local").strip().lower()
    if mode in {"remote", "ssh"}:
        remote_config = RemoteConfig(
            hostname=os.environ.get("SLURM_SSH_HOST", ""),
            username=os.environ.get("SLURM_SSH_USER", ""),
            port=int(os.environ.get("SLURM_SSH_PORT", "22")),
            known_hosts=os.environ.get("SLURM_SSH_KNOWN_HOSTS", ""),
            key_filename=os.environ.get("SLURM_SSH_KEY") or None,
            password=os.environ.get("SLURM_SSH_PASSWORD") or None,
            connect_timeout=float(os.environ.get("SLURM_SSH_CONNECT_TIMEOUT", "15")),
            command_timeout=float(os.environ.get("SLURM_COMMAND_TIMEOUT", "30")),
            shared_filesystem=_bool_env("SLURM_SHARED_FILESYSTEM", True),
        )
        return SlurmClient(mode="remote", remote_config=remote_config)
    if mode != "local":
        raise ValueError("SLURM_MODE must be local or remote")
    return SlurmClient(mode="local")


def _handle_selector_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "handle_id": {
                "type": "string",
                "description": "ARI JobHandleV1 handle ID (preferred)",
            },
            "job_id": {
                "type": "string",
                "description": "Raw SLURM job ID (legacy compatibility)",
            },
        },
        "oneOf": [{"required": ["handle_id"]}, {"required": ["job_id"]}],
        "additionalProperties": False,
    }


def _legacy_submit_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "script": {
                "type": "string",
                "description": "Opaque batch body executed only on the allocated compute node",
            },
            "job_name": {"type": "string"},
            "partition": {"type": "string"},
            "nodes": {
                "type": "integer",
                "minimum": 1,
                "default": 1,
                "description": (
                    "Nodes to allocate. Allocating more than one does NOT "
                    "spread the script: the batch body runs on the first node "
                    "only. Launch the parallel step yourself (srun / mpirun) "
                    "or the extra nodes sit idle."
                ),
            },
            "tasks": {
                "type": "integer",
                "minimum": 1,
                "description": "Total tasks (--ntasks) for the allocation",
            },
            "tasks_per_node": {
                "type": "integer",
                "minimum": 1,
                "description": "Tasks per node (--ntasks-per-node)",
            },
            "cpus_per_task": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "CPUs per task (--cpus-per-task). Also what a single-task "
                    "step is bound to, so a threaded payload gets the cores it "
                    "asked for rather than the whole node."
                ),
            },
            "walltime": {"type": "string", "default": "01:00:00"},
            "work_dir": {
                "type": "string",
                "description": "Existing absolute shared-filesystem directory",
            },
            "modules": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Environment modules to load before the script runs. "
                    "Declaring them here purges first, so the toolchain is the "
                    "one asked for rather than whatever the node defaulted to, "
                    "and the job fails loudly if the node cannot provide them "
                    "instead of silently building with something else. Writing "
                    "`module load` inside the script works too, but is neither "
                    "purged nor checked."
                ),
            },
        },
        "required": ["script", "job_name", "partition"],
        "additionalProperties": False,
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    canonical_submit = JobSubmitArgumentsV1.model_json_schema()
    return [
        Tool(
            name="job_submit",
            description=(
                "Submit an immutable JobRequestV1 and immediately return an idempotent "
                "JobHandleV1. Commands are argv arrays; the login-node shell is never used."
            ),
            inputSchema=canonical_submit,
        ),
        Tool(
            name="container_submit",
            description=(
                "Submit a digest-pinned Apptainer/Singularity JobRequestV1. The request "
                "must include its container declaration."
            ),
            inputSchema=canonical_submit,
        ),
        Tool(
            name="job_status",
            description="Return a provider-neutral JobStatusV1 for an ARI handle or SLURM ID",
            inputSchema=_handle_selector_schema(),
        ),
        Tool(
            name="job_result",
            description=(
                "Collect a terminal JobResultV1, rehashing declared inputs, outputs, and logs"
            ),
            inputSchema=_handle_selector_schema(),
        ),
        Tool(
            name="job_logs",
            description="Read bounded, digest-bound stdout/stderr for an ARI job handle",
            inputSchema=_handle_selector_schema(),
        ),
        Tool(
            name="job_cancel",
            description="Request cancellation of an ARI or SLURM job",
            inputSchema=_handle_selector_schema(),
        ),
        Tool(
            name="slurm_submit",
            description=(
                "Compatibility bridge for the core agent's batch-script workflow. "
                "New programmatic callers should prefer job_submit."
            ),
            inputSchema=_legacy_submit_schema(),
        ),
        Tool(
            name="probe_platform_capabilities",
            description=(
                "Best-effort compute-partition capability probe with an atomic checkpoint cache"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "checkpoint_dir": {"type": "string"},
                    "partition": {"type": "string"},
                    "tools": {"type": "string"},
                },
                "required": ["checkpoint_dir"],
                "additionalProperties": False,
            },
        ),
    ]


def _selector(arguments: dict[str, Any]) -> str:
    return str(arguments.get("handle_id") or arguments.get("job_id") or "")


def _public_error_message(exc: Exception) -> str:
    value = str(exc).replace("\x00", " ")[:4000]
    value = re.sub(
        r"(?i)\b(password|token|secret|api[_-]?key)\s*([=:])\s*\S+",
        r"\1\2<redacted>",
        value,
    )
    value = re.sub(
        r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
        "<redacted-private-key>",
        value,
        flags=re.DOTALL,
    )
    return " ".join(value.split())[:2000]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    client: SlurmClient | None = None
    try:
        if name == "probe_platform_capabilities":
            result = await slurm.probe_platform_capabilities(
                checkpoint_dir=arguments["checkpoint_dir"],
                partition=arguments.get("partition", ""),
                tools=arguments.get("tools", ""),
            )
        else:
            client = _get_slurm_client()
            if name in {"job_submit", "container_submit"}:
                request = JobSubmitArgumentsV1.model_validate(arguments).request
                if name == "container_submit" and request.container is None:
                    raise ValueError("container_submit requires request.container")
                result = (await client.scheduler.submit(request)).model_dump(
                    mode="json"
                )
            elif name == "job_status":
                result = (
                    await client.scheduler.status(_selector(arguments))
                ).model_dump(mode="json")
            elif name == "job_result":
                result = (
                    await client.scheduler.result(_selector(arguments))
                ).model_dump(mode="json")
            elif name == "job_logs":
                logs = await client.scheduler.logs(_selector(arguments))
                result = {
                    "schema_version": "ari.hpc.job-logs/v1",
                    "logs": [item.model_dump(mode="json") for item in logs],
                }
            elif name == "job_cancel":
                result = await client.scheduler.cancel(_selector(arguments))
            elif name == "slurm_submit":
                result = await client.submit(
                    script=arguments["script"],
                    job_name=arguments.get("job_name", "mcp_job"),
                    partition=arguments.get("partition", ""),
                    nodes=arguments.get("nodes", 1),
                    walltime=arguments.get("walltime", "01:00:00"),
                    work_dir=arguments.get("work_dir", ""),
                    modules=arguments.get("modules") or (),
                    tasks=arguments.get("tasks"),
                    tasks_per_node=arguments.get("tasks_per_node"),
                    cpus_per_task=arguments.get("cpus_per_task"),
                )
            else:
                result = {
                    "error": {"kind": "validation", "message": f"unknown tool: {name}"}
                }
    except (SchedulerError, ValueError, KeyError) as exc:
        if isinstance(exc, SchedulerValidationError) or not isinstance(
            exc, SchedulerError
        ):
            kind = "validation"
            retryable = False
        elif isinstance(exc, SubmissionUncertainError):
            kind = "transport"
            retryable = False
        elif isinstance(exc, SchedulerTransportError):
            kind = "transport"
            retryable = True
        elif isinstance(exc, SchedulerProtocolError):
            kind = "scheduler"
            retryable = False
        else:
            kind = "scheduler"
            retryable = False
        result = {
            "error": {
                "kind": kind,
                "message": _public_error_message(exc),
                "retryable": retryable,
            }
        }
    except Exception as exc:
        result = {
            "error": {
                "kind": "unknown",
                "message": f"{name} failed: {type(exc).__name__}",
                "retryable": False,
            }
        }
    finally:
        if client is not None:
            client.close()
    return [
        TextContent(
            type="text", text=json.dumps(result, ensure_ascii=False, sort_keys=True)
        )
    ]


async def main() -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def cli() -> None:
    """Installed console entry point."""

    import asyncio

    asyncio.run(main())


if __name__ == "__main__":
    cli()
