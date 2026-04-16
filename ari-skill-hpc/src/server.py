"""MCP Server for HPC operations (SLURM + Singularity)."""

from __future__ import annotations

import json
import os

from mcp.server import Server
from mcp.types import TextContent, Tool

from src.slurm import SlurmClient, RemoteConfig
from src import singularity

server = Server("hpc-skill")


def _get_slurm_client() -> SlurmClient:
    """Create a SlurmClient based on environment configuration."""
    mode = os.environ.get("SLURM_MODE", "local")
    if mode == "remote":
        remote_config = RemoteConfig(
            hostname=os.environ.get("SLURM_SSH_HOST", "localhost"),
            username=os.environ.get("SLURM_SSH_USER", ""),
            port=int(os.environ.get("SLURM_SSH_PORT", "22")),
            key_filename=os.environ.get("SLURM_SSH_KEY", None),
            password=os.environ.get("SLURM_SSH_PASSWORD", None),
        )
        return SlurmClient(mode="remote", remote_config=remote_config)
    return SlurmClient(mode="local")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="slurm_submit",
            description="Submit a SLURM batch job",
            inputSchema={
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "sbatch script content",
                    },
                    "job_name": {
                        "type": "string",
                        "description": "Job name",
                    },
                    "partition": {
                        "type": "string",
                        "description": "Partition name",
                    },
                    "nodes": {
                        "type": "integer",
                        "description": "Number of nodes",
                        "default": 1,
                    },
                    "walltime": {
                        "type": "string",
                        "description": "Maximum wall time",
                        "default": "01:00:00",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory for the job (sets SBATCH --chdir). Use absolute path.",
                    },
                },
                "required": ["script", "job_name", "partition"],
            },
        ),
        Tool(
            name="job_status",
            description="Get the status of a SLURM job",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "SLURM job ID",
                    },
                },
                "required": ["job_id"],
            },
        ),
        Tool(
            name="job_cancel",
            description="Cancel a SLURM job",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "SLURM job ID",
                    },
                },
                "required": ["job_id"],
            },
        ),
        Tool(
            name="singularity_build",
            description="Build a Singularity image file by submitting a SLURM job",
            inputSchema={
                "type": "object",
                "properties": {
                    "definition_file": {
                        "type": "string",
                        "description": "Singularity definition file content",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output SIF file path",
                    },
                    "partition": {
                        "type": "string",
                        "description": "Partition name",
                    },
                },
                "required": ["definition_file", "output_path", "partition"],
            },
        ),
        Tool(
            name="singularity_run",
            description="Run a command inside a Singularity container via SLURM",
            inputSchema={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "SIF file path",
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to execute",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                    },
                    "partition": {
                        "type": "string",
                        "description": "Partition name",
                    },
                    "nodes": {
                        "type": "integer",
                        "description": "Number of nodes",
                        "default": 1,
                    },
                    "walltime": {
                        "type": "string",
                        "description": "Maximum wall time",
                        "default": "01:00:00",
                    },
                },
                "required": ["image_path", "command", "work_dir", "partition"],
            },
        ),
        Tool(
            name="singularity_pull",
            description="Pull a Singularity/Apptainer image from Docker Hub or Sylabs Cloud via SLURM",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Image source URI (e.g. 'docker://nvidia/cuda:12.0-base' or 'library://user/repo/image')",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Local SIF output path (e.g. '~/containers/cuda12.sif')",
                    },
                    "partition": {"type": "string", "description": "SLURM partition"},
                },
                "required": ["source", "output_path", "partition"],
            },
        ),
        Tool(
            name="singularity_build_fakeroot",
            description="Build a Singularity image using --fakeroot (no root required). HPC-compatible.",
            inputSchema={
                "type": "object",
                "properties": {
                    "definition_content": {
                        "type": "string",
                        "description": "Full content of the Singularity definition file",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output SIF file path",
                    },
                    "partition": {"type": "string", "description": "SLURM partition"},
                    "walltime": {"type": "string", "description": "Max walltime (default 02:00:00)"},
                },
                "required": ["definition_content", "output_path", "partition"],
            },
        ),
        Tool(
            name="singularity_run_gpu",
            description="Run a command inside a Singularity container with GPU access (--nv flag) via SLURM",
            inputSchema={
                "type": "object",
                "properties": {
                    "image_path": {"type": "string", "description": "SIF file path"},
                    "command": {"type": "string", "description": "Command to execute inside container"},
                    "work_dir": {"type": "string", "description": "Working directory", "default": "."},
                    "partition": {"type": "string", "description": "SLURM GPU partition"},
                    "gres": {"type": "string", "description": "GRES spec (e.g. 'gpu:1')", "default": "gpu:1"},
                    "cpus_per_task": {"type": "integer", "description": "CPUs per task", "default": 8},
                    "walltime": {"type": "string", "description": "Max walltime", "default": "01:00:00"},
                    "bind_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Bind mount paths as 'host:container' strings",
                        "default": [],
                    },
                },
                "required": ["image_path", "command", "partition"],
            },
        ),
    ]


import logging as _logging
_hpc_log = _logging.getLogger("ari.skill.hpc")


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    client = _get_slurm_client()
    try:
        if name == "slurm_submit":
            result = await client.submit(
                script=arguments["script"],
                job_name=arguments.get("job_name", "mcp_job"),
                partition=arguments.get("partition", "default"),
                nodes=arguments.get("nodes", 1),
                walltime=arguments.get("walltime", "01:00:00"),
                account=arguments.get("account"),
                work_dir=arguments.get("work_dir", __import__("os").environ.get("SLURM_DEFAULT_WORK_DIR", "")),
            )
        elif name == "job_status":
            result = await client.status(job_id=arguments["job_id"])
        elif name == "job_cancel":
            result = await client.cancel(job_id=arguments["job_id"])
        elif name == "singularity_build":
            result = await singularity.build(client, arguments)
        elif name == "singularity_run":
            result = await singularity.run(client, arguments)
        elif name == "singularity_pull":
            result = await singularity.pull(client, arguments)
        elif name == "singularity_build_fakeroot":
            result = await singularity.build_fakeroot(client, arguments)
        elif name == "singularity_run_gpu":
            result = await singularity.run_gpu(client, arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}
    except Exception as exc:
        result = {"error": f"{name} failed: {type(exc).__name__}: {exc}"}
    finally:
        client.close()

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


async def main() -> None:
    from mcp.server.stdio import stdio_server
    from mcp.server import InitializationOptions
    import mcp.types as types

    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
