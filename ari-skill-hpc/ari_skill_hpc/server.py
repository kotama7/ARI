"""MCP server for public typed scheduler and container job lifecycles."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from ari_skill_hpc import counters, slurm
from ari_skill_hpc.contracts import JobHandleV1, JobSubmitArgumentsV1
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
            "launcher": {
                "type": "string",
                "enum": ["auto", "srun", "none"],
                "default": "auto",
                "description": (
                    "How the script is started inside the allocation. "
                    "'auto' binds a single-task job to its CPUs and starts "
                    "anything larger directly, leaving the parallel launch to "
                    "you — this is what you want when your script already "
                    "calls srun or mpirun. 'srun' starts the script itself "
                    "with the declared nodes/tasks, which is what an MPI or "
                    "SPMD binary needs; do NOT combine it with your own "
                    "launcher or you get tasks x your own count. 'none' never "
                    "wraps."
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
            outputSchema=_result_or_error(_model_schema(JobHandleV1)),
        ),
        Tool(
            name="container_submit",
            description=(
                "Submit a digest-pinned Apptainer/Singularity JobRequestV1. The request "
                "must include its container declaration."
            ),
            inputSchema=canonical_submit,
            outputSchema=_result_or_error(_model_schema(JobHandleV1)),
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
            # NOT _model_schema(JobHandleV1). This bridge does not return a
            # JobHandleV1 dump -- SlurmClient.submit builds its own flatter
            # dict, and JobHandleV1 forbids extra properties while requiring
            # five the bridge never carries. Declaring the sibling tools' shape
            # here refused every successful submission *after* sbatch had
            # already queued the job, leaving the handle unreachable.
            outputSchema=_result_or_error(
                {
                    "type": "object",
                    "properties": {
                        "schema_version": {"type": "string"},
                        "handle_id": {"type": "string"},
                        "job_id": {"type": "string"},
                        "state": {"type": ["string", "null"]},
                        "status": {"type": ["string", "null"]},
                        "message": {"type": "string"},
                        "partition": {"type": "string"},
                        "request_digest": {"type": "string"},
                        "submission_digest": {"type": "string"},
                    },
                    "required": ["job_id", "status"],
                }
            ),
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
        Tool(
            name="counter_support",
            description=(
                "Report whether this node grants hardware counters, established by "
                "opening one rather than by looking for a profiler binary."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            # Declaring this obliges the handler to return structured content --
            # the library validates it and refuses the call outright if it is
            # missing. It must therefore admit the error envelope every handler
            # can return, or a failure would surface as an output-validation
            # error and the real message would be lost.
            outputSchema=_result_or_error(
                {
                    "type": "object",
                    "properties": {
                        "schema_version": {"const": "ari.hpc.counter-support/v1"},
                        "architecture": {"type": "string"},
                        "perf_event_paranoid": {"type": ["integer", "null"]},
                        "reviewed_events": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "status": {
                            "type": "string",
                            "enum": ["ready", "denied", "unsupported", "unavailable"],
                        },
                        "detail": {"type": ["string", "null"]},
                    },
                    "required": ["schema_version", "status", "architecture"],
                }
            ),
        ),
        Tool(
            name="measure_counters",
            description=(
                "Count reviewed hardware events on an existing process over a bounded "
                "window. Creates no process and writes nothing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "pid": {"type": "integer", "minimum": 1},
                    "window_ms": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": counters.MAX_WINDOW_MS,
                        "default": 1000,
                    },
                    "events": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": sorted(counters.REVIEWED_EVENTS),
                        },
                        "minItems": 1,
                        "default": list(counters.DEFAULT_EVENTS),
                    },
                    # The transport injects the node context under this name for
                    # any tool declaring context_requirement: node. A schema that
                    # refuses it refuses every authorized call.
                    "ari_context": {"type": "object"},
                },
                "required": ["pid"],
                "additionalProperties": False,
            },
            outputSchema=_result_or_error(
                {
                    "type": "object",
                    "properties": {
                        "schema_version": {
                            "const": "ari.hpc.counter-measurement/v1"
                        },
                        "status": {
                            "type": "string",
                            "enum": ["measured", "denied", "unavailable", "unsupported"],
                        },
                        # The envelope the measurement is only interpretable
                        # inside: the support record it was taken under, the
                        # window it covers, and what was excluded from it.
                        "support": {"type": "object"},
                        "counters": {
                            "type": "object",
                            "additionalProperties": {"type": "integer"},
                        },
                        "pid": {"type": "integer"},
                        "window_seconds": {"type": "number"},
                        "excluded": {"type": "array", "items": {"type": "string"}},
                        "detail": {"type": ["string", "null"]},
                    },
                    "required": ["schema_version", "status", "support", "counters"],
                }
            ),
        ),
    ]


def _model_schema(model) -> dict:
    """Derive a tool's declared output shape from the model that produces it.

    Hand-writing a copy would be a second source of truth for the same bytes,
    and the two would drift the first time the contract gained a field.
    """

    schema = model.model_json_schema()
    schema.pop("title", None)
    return schema


def _result_or_error(success: dict) -> dict:
    """Admit the tool's own result, the handler's error envelope, or both.

    Every handler here funnels failures into ``{"error": {...}}``. A schema that
    described only success would turn a scheduler failure into an output
    validation error and discard the message that says what went wrong, so the
    declared shape has to be the union the handler can actually produce -- and
    an inclusive union, because a payload may legitimately satisfy both arms.
    """

    # anyOf, not oneOf: oneOf demands exactly one arm matches, and these
    # shapes are not exclusive. A timed-out execution is a complete result
    # that also carries an error string, so it satisfies both arms and
    # oneOf rejects it -- destroying the very payload that says what
    # happened, after the work was already done.
    return {
        "anyOf": [
            success,
            {
                "type": "object",
                "properties": {
                    "error": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string"},
                            "message": {"type": "string"},
                            "retryable": {"type": "boolean"},
                        },
                        "required": ["kind", "message"],
                    }
                },
                "required": ["error"],
            },
        ]
    }


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
async def call_tool(
    name: str, arguments: dict[str, Any]
) -> tuple[list[TextContent], dict[str, Any]]:
    client: SlurmClient | None = None
    try:
        if name == "counter_support":
            result = counters.counter_support()
        elif name == "measure_counters":
            result = counters.measure_counters(
                pid=int(arguments["pid"]),
                window_ms=int(arguments.get("window_ms", 1000)),
                events=tuple(arguments.get("events") or counters.DEFAULT_EVENTS),
            )
        elif name == "probe_platform_capabilities":
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
                    launcher=arguments.get("launcher") or "auto",
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
    rendered = [
        TextContent(
            type="text", text=json.dumps(result, ensure_ascii=False, sort_keys=True)
        )
    ]
    # Both halves: the text keeps the exact bytes ARI already digests, and the
    # structured copy is what a declared outputSchema is validated against.
    return rendered, result


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
